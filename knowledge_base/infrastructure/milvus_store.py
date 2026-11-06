from __future__ import annotations

import json
import logging
from typing import Any, Optional

from pymilvus import DataType, MilvusClient

from knowledge_base.infrastructure.settings import Settings

logger = logging.getLogger(__name__)


def _milvus_literal(value: Any) -> str:
    """Preserve non-ASCII text when building Milvus filter expressions."""
    return json.dumps(value, ensure_ascii=False)


class MilvusVectorStore:
    def __init__(self, settings: Settings, dimension: int) -> None:
        self._settings = settings
        self._client = MilvusClient(
            uri=settings.milvus_uri,
            keepalive_options={
                "keepalive_time_ms": 30000,
                "keepalive_timeout_ms": 10000,
                "keepalive_permit_without_calls": False,
            }
        )
        self._dimension = dimension
        self._ensure_collection()
        self._facts_collection_name = f"{settings.collection_name}_facts"
        self._ensure_facts_collection()

    @property
    def collection_name(self) -> str:
        return self._settings.collection_name

    def insert_chunks(
        self,
        *,
        document_id: str,
        source_name: str,
        source_type: str,
        chunk_payloads: list[dict[str, Any]],
    ) -> None:
        self._insert_rows_in_batches(collection_name=self.collection_name, rows=chunk_payloads)

    def rename_brand(
        self,
        *,
        brand_code: str,
        old_brand_name: str,
        new_brand_name: str,
    ) -> dict[str, int]:
        normalized_brand_code = str(brand_code or "").strip()
        normalized_old_brand_name = str(old_brand_name or "").strip()
        normalized_new_brand_name = str(new_brand_name or "").strip()
        if not normalized_brand_code:
            raise ValueError("brand_code 不能为空")
        if not normalized_new_brand_name:
            raise ValueError("new_brand_name 不能为空")
        if not normalized_old_brand_name:
            normalized_old_brand_name = normalized_new_brand_name
        if normalized_old_brand_name == normalized_new_brand_name:
            return {
                "chunks": 0,
                "facts": 0,
            }

        chunk_count = 0
        for batch in self._iter_rows_by_brand_code(
            collection_name=self.collection_name,
            brand_code=normalized_brand_code,
            output_fields=[
                "id",
                "document_id",
                "source_name",
                "source_type",
                "brand_code",
                "brand_name",
                "product_code",
                "product_name",
                "chunk_index",
                "text",
                "metadata_json",
                "vector",
            ],
        ):
            renamed_chunk_rows = [
                self._build_renamed_chunk_row(row, new_brand_name=normalized_new_brand_name)
                for row in batch
            ]
            self._upsert_rows_in_batches(collection_name=self.collection_name, rows=renamed_chunk_rows)
            chunk_count += len(renamed_chunk_rows)

        fact_count = 0
        for batch in self._iter_rows_by_brand_code(
            collection_name=self._facts_collection_name,
            brand_code=normalized_brand_code,
            output_fields=[
                "fact_id",
                "fact_text",
                "category",
                "brand_code",
                "brand_name",
                "product_code",
                "product_name",
                "source_document_id",
                "document_ids",
                "vector",
            ],
        ):
            renamed_fact_rows = [
                self._build_renamed_fact_row(row, new_brand_name=normalized_new_brand_name)
                for row in batch
            ]
            self._upsert_rows_in_batches(collection_name=self._facts_collection_name, rows=renamed_fact_rows)
            fact_count += len(renamed_fact_rows)

        return {
            "chunks": chunk_count,
            "facts": fact_count,
        }

    def search(
        self,
        *,
        query_vector: list[float],
        top_k: int,
        document_ids: list[str] | None = None,
        source_types: list[str] | None = None,
        brand_code: str | None = None,
        product_code: str | None = None,
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        if document_ids:
            filters.append(f"document_id in {_milvus_literal(document_ids)}")
        if source_types:
            filters.append(f"source_type in {_milvus_literal(source_types)}")
        if brand_code:
            filters.append(f"brand_code == {_milvus_literal(brand_code)}")
        if product_code and self._collection_supports_field(self.collection_name, "product_code"):
            filters.append(f"product_code == {_milvus_literal(product_code)}")

        results = self._client.search(
            collection_name=self.collection_name,
            anns_field="vector",
            data=[query_vector],
            limit=top_k,
            output_fields=self._existing_output_fields(
                self.collection_name,
                [
                    "document_id",
                    "source_name",
                    "source_type",
                    "brand_code",
                    "brand_name",
                    "product_code",
                    "product_name",
                    "chunk_index",
                    "text",
                    "metadata_json",
                ],
            ),
            filter=" and ".join(filters) if filters else None,
            search_params={"metric_type": "COSINE"},
        )

        return results[0]

    def _query_rows_by_brand_code(
        self,
        *,
        collection_name: str,
        brand_code: str,
        output_fields: list[str],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for batch in self._iter_rows_by_brand_code(
            collection_name=collection_name,
            brand_code=brand_code,
            output_fields=output_fields,
        ):
            rows.extend(batch)
        return rows

    def _iter_rows_by_brand_code(
        self,
        *,
        collection_name: str,
        brand_code: str,
        output_fields: list[str],
    ):
        query_iterator = getattr(self._client, "query_iterator", None)
        if callable(query_iterator):
            iterator = query_iterator(
                collection_name=collection_name,
                filter=f"brand_code == {_milvus_literal(brand_code)}",
                output_fields=self._existing_output_fields(collection_name, output_fields),
                batch_size=self._milvus_iterator_batch_size(),
            )
            try:
                while True:
                    batch = iterator.next()
                    if not batch:
                        break
                    yield batch
            finally:
                close = getattr(iterator, "close", None)
                if callable(close):
                    close()
            return
        raise RuntimeError("Milvus client does not support query_iterator; refusing partial brand rename")

    def _insert_rows_in_batches(self, *, collection_name: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        rows = self._filter_rows_to_existing_fields(collection_name=collection_name, rows=rows)
        batch_size = self._milvus_write_batch_size()
        for index in range(0, len(rows), batch_size):
            self._client.insert(
                collection_name=collection_name,
                data=rows[index:index + batch_size],
            )

    def _upsert_rows_in_batches(
        self,
        *,
        collection_name: str,
        rows: list[dict[str, Any]],
        partial_update: bool | None = None,
    ) -> None:
        if not rows:
            return
        rows = self._filter_rows_to_existing_fields(collection_name=collection_name, rows=rows)
        batch_size = self._milvus_write_batch_size()
        for index in range(0, len(rows), batch_size):
            kwargs: dict[str, Any] = {
                "collection_name": collection_name,
                "data": rows[index:index + batch_size],
            }
            if partial_update is not None:
                kwargs["partial_update"] = partial_update
            self._client.upsert(**kwargs)

    def _milvus_iterator_batch_size(self) -> int:
        settings = getattr(self, "_settings", None)
        return max(1, int(getattr(settings, "milvus_iterator_batch_size", 100) or 100))

    def _milvus_write_batch_size(self) -> int:
        settings = getattr(self, "_settings", None)
        return max(1, int(getattr(settings, "milvus_write_batch_size", 100) or 100))

    def _collection_field_names(self, collection_name: str) -> set[str] | None:
        cache = getattr(self, "_collection_field_names_cache", None)
        if cache is None:
            cache = {}
            self._collection_field_names_cache = cache
        if collection_name in cache:
            return cache[collection_name]

        describe_collection = getattr(self._client, "describe_collection", None)
        if not callable(describe_collection):
            cache[collection_name] = None
            return None
        try:
            description = describe_collection(collection_name=collection_name)
        except Exception:
            logger.warning("Failed to describe Milvus collection schema collection_name=%s", collection_name, exc_info=True)
            cache[collection_name] = None
            return None

        raw_fields = []
        if isinstance(description, dict):
            raw_fields = list(description.get("fields") or [])
            schema = description.get("schema")
            if not raw_fields and isinstance(schema, dict):
                raw_fields = list(schema.get("fields") or [])
        else:
            schema = getattr(description, "schema", None)
            raw_fields = list(getattr(description, "fields", None) or getattr(schema, "fields", None) or [])

        field_names: set[str] = set()
        for field in raw_fields:
            if isinstance(field, dict):
                field_name = field.get("name") or field.get("field_name")
            else:
                field_name = getattr(field, "name", None) or getattr(field, "field_name", None)
            if field_name:
                field_names.add(str(field_name))
        cache[collection_name] = field_names or None
        return cache[collection_name]

    def _collection_supports_field(self, collection_name: str, field_name: str) -> bool:
        field_names = self._collection_field_names(collection_name)
        return field_names is None or field_name in field_names

    def _existing_output_fields(self, collection_name: str, output_fields: list[str]) -> list[str]:
        field_names = self._collection_field_names(collection_name)
        if field_names is None:
            return output_fields
        return [field_name for field_name in output_fields if field_name in field_names]

    def _filter_rows_to_existing_fields(
        self,
        *,
        collection_name: str,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        field_names = self._collection_field_names(collection_name)
        if field_names is None:
            return rows
        return [
            {
                key: value
                for key, value in row.items()
                if key in field_names
            }
            for row in rows
        ]

    @staticmethod
    def _parse_metadata_json(metadata_json: Any) -> dict[str, Any]:
        if isinstance(metadata_json, dict):
            return dict(metadata_json)
        if not metadata_json:
            return {}
        try:
            parsed = json.loads(str(metadata_json))
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _build_renamed_chunk_row(self, row: dict[str, Any], *, new_brand_name: str) -> dict[str, Any]:
        metadata = self._parse_metadata_json(row.get("metadata_json"))
        metadata["brand_name"] = new_brand_name
        metadata["category"] = new_brand_name
        vector = row.get("vector")
        if vector is None:
            raise ValueError(f"Milvus chunk row missing vector id={row.get('id')}")
        return {
            "id": row["id"],
            "document_id": row["document_id"],
            "source_name": row["source_name"],
            "source_type": row["source_type"],
            "brand_code": row["brand_code"],
            "brand_name": new_brand_name,
            "product_code": row.get("product_code"),
            "product_name": row.get("product_name"),
            "chunk_index": row["chunk_index"],
            "text": row["text"],
            "metadata_json": json.dumps(metadata, ensure_ascii=False),
            "vector": vector,
        }

    def _build_renamed_fact_row(self, row: dict[str, Any], *, new_brand_name: str) -> dict[str, Any]:
        vector = row.get("vector")
        if vector is None:
            raise ValueError(f"Milvus fact row missing vector fact_id={row.get('fact_id')}")
        return {
            "fact_id": row["fact_id"],
            "fact_text": row["fact_text"],
            "category": new_brand_name,
            "brand_code": row["brand_code"],
            "brand_name": new_brand_name,
            "product_code": row.get("product_code"),
            "product_name": row.get("product_name"),
            "source_document_id": row["source_document_id"],
            "document_ids": row["document_ids"],
            "vector": vector,
        }

    def _ensure_collection(self) -> None:
        if self.collection_name in self._client.list_collections():
            logger.debug("Milvus collection already exists collection_name=%s", self.collection_name)
            return

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=128)
        schema.add_field(field_name="document_id", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="source_name", datatype=DataType.VARCHAR, max_length=1024)
        schema.add_field(field_name="source_type", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="brand_code", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="brand_name", datatype=DataType.VARCHAR, max_length=255)
        schema.add_field(field_name="product_code", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="product_name", datatype=DataType.VARCHAR, max_length=255)
        schema.add_field(field_name="chunk_index", datatype=DataType.INT64)
        schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="metadata_json", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=self._dimension)

        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")

        self._client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
        )

    def delete_document(self, document_id: str) -> None:
        """删除指定 document_id 的所有向量数据"""
        # 根据 document_id 过滤删除
        self._client.delete(
            collection_name=self.collection_name,
            filter=f"document_id == '{document_id}'"
        )

    def delete_documents_by_ids(self, document_ids: list[str]) -> None:
        if not document_ids:
            return
        if len(document_ids) == 1:
            self.delete_document(document_ids[0])
            return
        self._client.delete(
            collection_name=self.collection_name,
            filter=f"document_id in {_milvus_literal(document_ids)}",
        )

    def delete_documents_by_brand_code(self, brand_code: str) -> None:
        if not brand_code:
            return
        self._client.delete(
            collection_name=self.collection_name,
            filter=f"brand_code == {_milvus_literal(brand_code)}",
        )

    def get_documents_info_by_ids(self, document_ids: list[str]) -> list[dict[str, Any]]:
        """根据 document_id 列表批量查询文档基本信息（去重）"""
        if not document_ids:
            return []
        # 构造 filter 表达式
        ids_json = _milvus_literal(document_ids)
        filter_expr = f"document_id in {ids_json}"
        # 查询所有匹配的 chunks
        results = self._client.query(
            collection_name=self.collection_name,
            filter=filter_expr,
            output_fields=["document_id", "source_name", "source_type", "metadata_json"],
            limit=len(document_ids) * 10,  # 避免一个文档太多 chunk 导致截断
        )
        # 按 document_id 去重，保留第一个遇到的记录
        seen = set()
        unique = []
        for item in results:
            doc_id = item["document_id"]
            if doc_id not in seen:
                seen.add(doc_id)
                unique.append(item)
        return unique
    

    # ===============facts=====================
    def _ensure_facts_collection(self) -> None:
        """确保事实 collection 存在，schema 包含 document_ids 数组（存储为 JSON 字符串）"""
        if self._facts_collection_name in self._client.list_collections():
            logger.debug("Facts collection already exists: %s", self._facts_collection_name)
            return

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(field_name="fact_id", datatype=DataType.VARCHAR, is_primary=True, max_length=128)
        schema.add_field(field_name="fact_text", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="category", datatype=DataType.VARCHAR, max_length=255)
        schema.add_field(field_name="brand_code", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="brand_name", datatype=DataType.VARCHAR, max_length=255)
        schema.add_field(field_name="product_code", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="product_name", datatype=DataType.VARCHAR, max_length=255)
        schema.add_field(field_name="source_document_id", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="document_ids", datatype=DataType.VARCHAR, max_length=65535)  # JSON 数组
        schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=self._dimension)

        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")

        self._client.create_collection(
            collection_name=self._facts_collection_name,
            schema=schema,
            index_params=index_params,
        )
        logger.info("Facts collection created: %s", self._facts_collection_name)

    def get_fact_by_id(self, fact_id: str) -> Optional[dict]:
        """根据 fact_id 获取事实实体"""
        res = self._client.get(
            collection_name=self._facts_collection_name,
            ids=[fact_id],
            output_fields=["fact_text", "category", "document_ids", "vector"]
        )
        if res:
            return res[0]
        return None

    def get_facts_by_ids(self, fact_ids: list[str]) -> dict[str, dict]:
        """根据 fact_id 列表批量获取事实实体"""
        if not fact_ids:
            return {}
        results = self._client.get(
            collection_name=self._facts_collection_name,
            ids=fact_ids,
            output_fields=["fact_id", "fact_text", "category", "document_ids", "vector"],
        )
        return {
            str(item["fact_id"]): item
            for item in results or []
            if item.get("fact_id")
        }

    def upsert_fact(self, fact_data: dict, *, partial_update: bool = False) -> None:
        """插入或更新事实（如果 fact_id 已存在则更新）"""
        self.upsert_facts([fact_data], partial_update=partial_update)

    def upsert_facts(self, facts_data: list[dict], *, partial_update: bool = False) -> None:
        """批量插入或更新事实"""
        if not facts_data:
            return
        self._upsert_rows_in_batches(
            collection_name=self._facts_collection_name,
            rows=facts_data,
            partial_update=partial_update,
        )

    def delete_fact(self, fact_id: str) -> None:
        """删除单个事实"""
        self._client.delete(
            collection_name=self._facts_collection_name,
            ids=[fact_id]
        )

    def delete_facts_by_ids(self, fact_ids: list[str]) -> None:
        if not fact_ids:
            return
        self._client.delete(
            collection_name=self._facts_collection_name,
            ids=fact_ids,
        )

    def delete_facts_by_brand_code(self, brand_code: str) -> None:
        if not brand_code:
            return
        self._client.delete(
            collection_name=self._facts_collection_name,
            filter=f"brand_code == {_milvus_literal(brand_code)}",
        )

    def delete_facts_by_document_ids(self, document_ids: list[str]) -> None:
        if not document_ids:
            return
        self._client.delete(
            collection_name=self._facts_collection_name,
            filter=f"source_document_id in {_milvus_literal(document_ids)}",
        )

    def search_facts(
        self,
        query_vector: list[float],
        category: str,
        top_k: int,
        *,
        source_document_id: str | None = None,
        brand_code: str | None = None,
        product_code: str | None = None,
    ) -> list[dict]:
        """在事实 collection 中搜索，返回按相似度排序的结果（已去重）"""
        filters = [f"category == {_milvus_literal(category)}"]
        if brand_code:
            filters.append(f"brand_code == {_milvus_literal(brand_code)}")
        if product_code and self._collection_supports_field(self._facts_collection_name, "product_code"):
            filters.append(f"product_code == {_milvus_literal(product_code)}")
        if source_document_id:
            filters.append(f"source_document_id == {_milvus_literal(source_document_id)}")
        results = self._client.search(
            collection_name=self._facts_collection_name,
            anns_field="vector",
            data=[query_vector],
            limit=top_k,
            output_fields=self._existing_output_fields(
                self._facts_collection_name,
                [
                    "fact_id",
                    "fact_text",
                    "document_ids",
                    "category",
                    "brand_code",
                    "brand_name",
                    "product_code",
                    "product_name",
                ],
            ),
            filter=" and ".join(filters),
            search_params={"metric_type": "COSINE"},
        )
        # 返回单查询的第一个结果集
        return results[0] if results else []
