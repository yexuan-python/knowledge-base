from __future__ import annotations

import json
import uuid
from typing import Any

from qdrant_client import QdrantClient, models

from knowledge_base.infrastructure.settings import Settings


_POINT_ID_NAMESPACE = uuid.UUID("4d33f467-46c5-4b4b-9c50-c6df0d202231")


def _qdrant_point_id(source_id: Any) -> str:
    return str(uuid.uuid5(_POINT_ID_NAMESPACE, str(source_id)))


def _payload(record: Any) -> dict[str, Any]:
    payload = getattr(record, "payload", None) or {}
    return dict(payload) if isinstance(payload, dict) else {}


def _vector(record: Any) -> list[float] | None:
    vector = getattr(record, "vector", None)
    if isinstance(vector, dict):
        value = vector.get("") or vector.get("vector")
        return list(value) if value is not None else None
    return list(vector) if vector is not None else None


class QdrantVectorStore:
    def __init__(self, settings: Settings, dimension: int) -> None:
        self._settings = settings
        self._dimension = dimension
        self._collection_name = settings.qdrant_collection_name
        self._facts_collection_name = settings.qdrant_facts_collection_name
        self._client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
            timeout=int(settings.qdrant_timeout_seconds),
        )
        self._ensure_collection(self._collection_name)
        self._ensure_collection(self._facts_collection_name)

    @property
    def collection_name(self) -> str:
        return self._collection_name

    def insert_chunks(
        self,
        *,
        document_id: str,
        source_name: str,
        source_type: str,
        chunk_payloads: list[dict[str, Any]],
    ) -> None:
        points = [
            models.PointStruct(
                id=_qdrant_point_id(row["id"]),
                vector=row["vector"],
                payload=self._chunk_payload(row),
            )
            for row in chunk_payloads
        ]
        if points:
            self._client.upsert(collection_name=self.collection_name, points=points, wait=True)

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
        conditions: list[Any] = []
        if document_ids:
            conditions.append(self._match_any("document_id", document_ids))
        if source_types:
            conditions.append(self._match_any("source_type", source_types))
        if brand_code:
            conditions.append(self._match_value("brand_code", brand_code))
        if product_code:
            conditions.append(self._match_value("product_code", product_code))

        hits = self._search_points(
            collection_name=self.collection_name,
            query_vector=query_vector,
            top_k=top_k,
            query_filter=self._filter(conditions),
        )
        return [self._chunk_hit(hit) for hit in hits]

    def rename_brand(
        self,
        *,
        brand_code: str,
        old_brand_name: str,
        new_brand_name: str,
    ) -> dict[str, int]:
        normalized_brand_code = str(brand_code or "").strip()
        normalized_new_brand_name = str(new_brand_name or "").strip()
        if not normalized_brand_code:
            raise ValueError("brand_code 不能为空")
        if not normalized_new_brand_name:
            raise ValueError("new_brand_name 不能为空")
        if str(old_brand_name or "").strip() == normalized_new_brand_name:
            return {"chunks": 0, "facts": 0}

        chunks = self._rename_payloads(
            collection_name=self.collection_name,
            brand_code=normalized_brand_code,
            new_brand_name=normalized_new_brand_name,
            payload_factory=self._renamed_chunk_payload,
        )
        facts = self._rename_payloads(
            collection_name=self._facts_collection_name,
            brand_code=normalized_brand_code,
            new_brand_name=normalized_new_brand_name,
            payload_factory=self._renamed_fact_payload,
        )
        return {"chunks": chunks, "facts": facts}

    def delete_document(self, document_id: str) -> None:
        if not document_id:
            return
        self._delete_by_filter(self.collection_name, [self._match_value("document_id", document_id)])

    def delete_documents_by_ids(self, document_ids: list[str]) -> None:
        if not document_ids:
            return
        self._delete_by_filter(self.collection_name, [self._match_any("document_id", document_ids)])

    def delete_documents_by_brand_code(self, brand_code: str) -> None:
        if not brand_code:
            return
        self._delete_by_filter(self.collection_name, [self._match_value("brand_code", brand_code)])

    def get_documents_info_by_ids(self, document_ids: list[str]) -> list[dict[str, Any]]:
        if not document_ids:
            return []
        records = self._scroll_all(
            collection_name=self.collection_name,
            scroll_filter=self._filter([self._match_any("document_id", document_ids)]),
            with_vectors=False,
        )
        seen: set[str] = set()
        documents: list[dict[str, Any]] = []
        for record in records:
            item = _payload(record)
            doc_id = str(item.get("document_id") or "")
            if not doc_id or doc_id in seen:
                continue
            seen.add(doc_id)
            documents.append(
                {
                    "document_id": item.get("document_id"),
                    "source_name": item.get("source_name"),
                    "source_type": item.get("source_type"),
                    "metadata_json": item.get("metadata_json"),
                }
            )
        return documents

    def get_fact_by_id(self, fact_id: str) -> dict[str, Any] | None:
        if not fact_id:
            return None
        records = self._client.retrieve(
            collection_name=self._facts_collection_name,
            ids=[_qdrant_point_id(fact_id)],
            with_payload=True,
            with_vectors=True,
        )
        if not records:
            return None
        return self._fact_record(records[0])

    def get_facts_by_ids(self, fact_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not fact_ids:
            return {}
        records = self._client.retrieve(
            collection_name=self._facts_collection_name,
            ids=[_qdrant_point_id(fact_id) for fact_id in fact_ids],
            with_payload=True,
            with_vectors=True,
        )
        results: dict[str, dict[str, Any]] = {}
        for record in records or []:
            item = self._fact_record(record)
            fact_id = str(item.get("fact_id") or "")
            if fact_id:
                results[fact_id] = item
        return results

    def upsert_fact(self, fact_data: dict[str, Any], *, partial_update: bool = False) -> None:
        self.upsert_facts([fact_data], partial_update=partial_update)

    def upsert_facts(self, facts_data: list[dict[str, Any]], *, partial_update: bool = False) -> None:
        points = [
            models.PointStruct(
                id=_qdrant_point_id(row["fact_id"]),
                vector=row["vector"],
                payload=self._fact_payload(row),
            )
            for row in facts_data
        ]
        if points:
            self._client.upsert(collection_name=self._facts_collection_name, points=points, wait=True)

    def delete_fact(self, fact_id: str) -> None:
        if not fact_id:
            return
        self._client.delete(
            collection_name=self._facts_collection_name,
            points_selector=models.PointIdsList(points=[_qdrant_point_id(fact_id)]),
            wait=True,
        )

    def delete_facts_by_ids(self, fact_ids: list[str]) -> None:
        if not fact_ids:
            return
        self._client.delete(
            collection_name=self._facts_collection_name,
            points_selector=models.PointIdsList(points=[_qdrant_point_id(fact_id) for fact_id in fact_ids]),
            wait=True,
        )

    def delete_facts_by_brand_code(self, brand_code: str) -> None:
        if not brand_code:
            return
        self._delete_by_filter(self._facts_collection_name, [self._match_value("brand_code", brand_code)])

    def delete_facts_by_document_ids(self, document_ids: list[str]) -> None:
        if not document_ids:
            return
        self._delete_by_filter(self._facts_collection_name, [self._match_any("source_document_id", document_ids)])

    def search_facts(
        self,
        query_vector: list[float],
        category: str,
        top_k: int,
        *,
        source_document_id: str | None = None,
        brand_code: str | None = None,
        product_code: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions = [self._match_value("category", category)]
        if brand_code:
            conditions.append(self._match_value("brand_code", brand_code))
        if product_code:
            conditions.append(self._match_value("product_code", product_code))
        if source_document_id:
            conditions.append(self._match_value("source_document_id", source_document_id))

        hits = self._search_points(
            collection_name=self._facts_collection_name,
            query_vector=query_vector,
            top_k=top_k,
            query_filter=self._filter(conditions),
        )
        return [self._fact_hit(hit) for hit in hits]

    def _ensure_collection(self, collection_name: str) -> None:
        if self._client.collection_exists(collection_name):
            return
        self._client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=self._dimension,
                distance=models.Distance.COSINE,
                on_disk=bool(getattr(self._settings, "qdrant_on_disk_vectors", True)),
            ),
            on_disk_payload=True,
        )

    @staticmethod
    def _chunk_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "document_id": row["document_id"],
            "source_name": row["source_name"],
            "source_type": row["source_type"],
            "brand_code": row.get("brand_code"),
            "brand_name": row.get("brand_name"),
            "product_code": row.get("product_code"),
            "product_name": row.get("product_name"),
            "chunk_index": row["chunk_index"],
            "text": row["text"],
            "metadata_json": row.get("metadata_json") or "{}",
        }

    @staticmethod
    def _fact_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "fact_id": row["fact_id"],
            "fact_text": row["fact_text"],
            "category": row["category"],
            "brand_code": row.get("brand_code"),
            "brand_name": row.get("brand_name"),
            "product_code": row.get("product_code"),
            "product_name": row.get("product_name"),
            "source_document_id": row["source_document_id"],
            "document_ids": row["document_ids"],
        }

    @staticmethod
    def _match_value(key: str, value: Any) -> Any:
        return models.FieldCondition(key=key, match=models.MatchValue(value=value))

    @staticmethod
    def _match_any(key: str, values: list[str]) -> Any:
        return models.FieldCondition(key=key, match=models.MatchAny(any=list(values)))

    @staticmethod
    def _filter(conditions: list[Any]) -> Any | None:
        return models.Filter(must=conditions) if conditions else None

    def _delete_by_filter(self, collection_name: str, conditions: list[Any]) -> None:
        self._client.delete(
            collection_name=collection_name,
            points_selector=models.FilterSelector(filter=self._filter(conditions)),
            wait=True,
        )

    def _search_points(
        self,
        *,
        collection_name: str,
        query_vector: list[float],
        top_k: int,
        query_filter: Any | None,
    ) -> list[Any]:
        query_points = getattr(self._client, "query_points", None)
        if callable(query_points):
            response = query_points(
                collection_name=collection_name,
                query=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
            return list(getattr(response, "points", response) or [])

        search = getattr(self._client, "search")
        return list(
            search(
                collection_name=collection_name,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
        )

    @staticmethod
    def _chunk_hit(hit: Any) -> dict[str, Any]:
        payload = _payload(hit)
        return {
            "id": payload.get("id", str(getattr(hit, "id", ""))),
            "distance": float(getattr(hit, "score", 0.0)),
            "entity": {
                "document_id": payload.get("document_id", ""),
                "source_name": payload.get("source_name", ""),
                "source_type": payload.get("source_type", ""),
                "chunk_index": payload.get("chunk_index", 0),
                "text": payload.get("text", ""),
                "metadata_json": payload.get("metadata_json") or "{}",
            },
        }

    @staticmethod
    def _fact_hit(hit: Any) -> dict[str, Any]:
        payload = _payload(hit)
        fact_id = payload.get("fact_id", str(getattr(hit, "id", "")))
        return {
            "id": fact_id,
            "distance": float(getattr(hit, "score", 0.0)),
            "entity": {
                "fact_id": fact_id,
                "fact_text": payload.get("fact_text", ""),
                "category": payload.get("category", ""),
                "brand_code": payload.get("brand_code", ""),
                "brand_name": payload.get("brand_name", ""),
                "product_code": payload.get("product_code", ""),
                "product_name": payload.get("product_name", ""),
                "source_document_id": payload.get("source_document_id", ""),
                "document_ids": payload.get("document_ids") or "[]",
            },
        }

    @staticmethod
    def _fact_record(record: Any) -> dict[str, Any]:
        payload = _payload(record)
        vector = _vector(record)
        if vector is not None:
            payload["vector"] = vector
        return payload

    def _scroll_all(
        self,
        *,
        collection_name: str,
        scroll_filter: Any | None,
        with_vectors: bool,
    ) -> list[Any]:
        records: list[Any] = []
        offset = None
        while True:
            batch, offset = self._client.scroll(
                collection_name=collection_name,
                scroll_filter=scroll_filter,
                limit=1000,
                offset=offset,
                with_payload=True,
                with_vectors=with_vectors,
            )
            records.extend(batch or [])
            if offset is None:
                return records

    def _rename_payloads(
        self,
        *,
        collection_name: str,
        brand_code: str,
        new_brand_name: str,
        payload_factory: Any,
    ) -> int:
        records = self._scroll_all(
            collection_name=collection_name,
            scroll_filter=self._filter([self._match_value("brand_code", brand_code)]),
            with_vectors=True,
        )
        points = []
        for record in records:
            vector = _vector(record)
            if vector is None:
                raise ValueError(f"Qdrant row missing vector id={getattr(record, 'id', '')}")
            points.append(
                models.PointStruct(
                    id=getattr(record, "id"),
                    vector=vector,
                    payload=payload_factory(_payload(record), new_brand_name),
                )
            )
        if points:
            self._client.upsert(collection_name=collection_name, points=points, wait=True)
        return len(points)

    @staticmethod
    def _renamed_chunk_payload(payload: dict[str, Any], new_brand_name: str) -> dict[str, Any]:
        metadata = {}
        try:
            metadata = json.loads(str(payload.get("metadata_json") or "{}"))
        except Exception:
            metadata = {}
        if isinstance(metadata, dict):
            metadata["brand_name"] = new_brand_name
            metadata["category"] = new_brand_name
            payload["metadata_json"] = json.dumps(metadata, ensure_ascii=False)
        payload["brand_name"] = new_brand_name
        return payload

    @staticmethod
    def _renamed_fact_payload(payload: dict[str, Any], new_brand_name: str) -> dict[str, Any]:
        payload["brand_name"] = new_brand_name
        payload["category"] = new_brand_name
        return payload
