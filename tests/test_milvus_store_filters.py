from __future__ import annotations

import importlib.util
import types
import unittest
from pathlib import Path

from tests._stub_utils import ensure_stub_module

_PYMILVUS_STUB = ensure_stub_module("pymilvus")
if _PYMILVUS_STUB is not None:
    _PYMILVUS_STUB.DataType = type("DataType", (), {})
    _PYMILVUS_STUB.MilvusClient = type("MilvusClient", (), {})

_MILVUS_STORE_PATH = Path(__file__).resolve().parents[1] / "knowledge_base" / "infrastructure" / "milvus_store.py"
_MILVUS_SPEC = importlib.util.spec_from_file_location("knowledge_base.infrastructure.milvus_store_test", _MILVUS_STORE_PATH)
assert _MILVUS_SPEC is not None and _MILVUS_SPEC.loader is not None
_MILVUS_MODULE = importlib.util.module_from_spec(_MILVUS_SPEC)
_MILVUS_SPEC.loader.exec_module(_MILVUS_MODULE)
MilvusVectorStore = _MILVUS_MODULE.MilvusVectorStore


class _FakeMilvusClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.inserts: list[dict[str, object]] = []
        self.upserts: list[dict[str, object]] = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return [[]]

    def insert(self, **kwargs):
        self.inserts.append(kwargs)

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)


class _SchemaAwareFakeMilvusClient(_FakeMilvusClient):
    def __init__(self, fields_by_collection: dict[str, list[str]]) -> None:
        super().__init__()
        self.fields_by_collection = fields_by_collection
        self.describe_calls: list[str] = []

    def describe_collection(self, *, collection_name: str):
        self.describe_calls.append(collection_name)
        return {
            "fields": [
                {"name": field_name}
                for field_name in self.fields_by_collection.get(collection_name, [])
            ]
        }


class _FakeQueryIterator:
    def __init__(self, batches: list[list[dict[str, object]]]) -> None:
        self._batches = list(batches)
        self.closed = False

    def next(self):
        if not self._batches:
            return []
        return self._batches.pop(0)

    def close(self):
        self.closed = True


class _FakeRenameMilvusClient:
    def __init__(self) -> None:
        self.query_calls: list[dict[str, object]] = []
        self.upsert_calls: list[dict[str, object]] = []
        self._iterators = {
            "documents": _FakeQueryIterator(
                [
                    [
                        {
                            "id": "chunk-1",
                            "document_id": "doc-1",
                            "source_name": "source.md",
                            "source_type": "text",
                            "brand_code": "BRAND-001",
                            "brand_name": "旧品牌",
                            "chunk_index": 0,
                            "text": "第一段",
                            "metadata_json": '{"brand_name":"旧品牌","category":"旧品牌"}',
                            "vector": [0.1, 0.2],
                        }
                    ],
                    [
                        {
                            "id": "chunk-2",
                            "document_id": "doc-1",
                            "source_name": "source.md",
                            "source_type": "text",
                            "brand_code": "BRAND-001",
                            "brand_name": "旧品牌",
                            "chunk_index": 1,
                            "text": "第二段",
                            "metadata_json": '{"brand_name":"旧品牌","category":"旧品牌"}',
                            "vector": [0.2, 0.3],
                        }
                    ],
                ]
            ),
            "documents_facts": _FakeQueryIterator(
                [
                    [
                        {
                            "fact_id": "fact-1",
                            "fact_text": "事实",
                            "category": "旧品牌",
                            "brand_code": "BRAND-001",
                            "brand_name": "旧品牌",
                            "source_document_id": "doc-1",
                            "document_ids": '["doc-1"]',
                            "vector": [0.3, 0.4],
                        }
                    ]
                ]
            ),
        }

    def query_iterator(self, **kwargs):
        self.query_calls.append(kwargs)
        return self._iterators[kwargs["collection_name"]]

    def upsert(self, **kwargs):
        self.upsert_calls.append(kwargs)


class MilvusStoreFilterTests(unittest.TestCase):
    def test_search_facts_preserves_non_ascii_category_filter(self) -> None:
        client = _FakeMilvusClient()
        store = MilvusVectorStore.__new__(MilvusVectorStore)
        store._client = client
        store._facts_collection_name = "documents_facts"

        result = store.search_facts(
            [0.1, 0.2],
            "理想汽车",
            5,
            brand_code="100097",
        )

        self.assertEqual(result, [])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(
            client.calls[0]["filter"],
            'category == "理想汽车" and brand_code == "100097"',
        )

    def test_search_omits_product_output_fields_when_existing_collection_lacks_them(self) -> None:
        client = _SchemaAwareFakeMilvusClient(
            {
                "documents": [
                    "id",
                    "document_id",
                    "source_name",
                    "source_type",
                    "brand_code",
                    "brand_name",
                    "chunk_index",
                    "text",
                    "metadata_json",
                    "vector",
                ]
            }
        )
        store = MilvusVectorStore.__new__(MilvusVectorStore)
        store._client = client
        store._settings = types.SimpleNamespace(collection_name="documents")

        store.search(query_vector=[0.1, 0.2], top_k=5, brand_code="BRAND-001")

        self.assertNotIn("product_code", client.calls[0]["output_fields"])
        self.assertNotIn("product_name", client.calls[0]["output_fields"])
        self.assertEqual(client.calls[0]["filter"], 'brand_code == "BRAND-001"')

    def test_search_facts_omits_product_output_fields_when_existing_collection_lacks_them(self) -> None:
        client = _SchemaAwareFakeMilvusClient(
            {
                "documents_facts": [
                    "fact_id",
                    "fact_text",
                    "category",
                    "brand_code",
                    "brand_name",
                    "source_document_id",
                    "document_ids",
                    "vector",
                ]
            }
        )
        store = MilvusVectorStore.__new__(MilvusVectorStore)
        store._client = client
        store._facts_collection_name = "documents_facts"

        store.search_facts([0.1, 0.2], "示例品牌", 5, brand_code="BRAND-001")

        self.assertNotIn("product_code", client.calls[0]["output_fields"])
        self.assertNotIn("product_name", client.calls[0]["output_fields"])
        self.assertEqual(client.calls[0]["filter"], 'category == "示例品牌" and brand_code == "BRAND-001"')

    def test_insert_chunks_filters_rows_to_existing_collection_schema(self) -> None:
        client = _SchemaAwareFakeMilvusClient(
            {
                "documents": [
                    "id",
                    "document_id",
                    "source_name",
                    "source_type",
                    "brand_code",
                    "brand_name",
                    "chunk_index",
                    "text",
                    "metadata_json",
                    "vector",
                ]
            }
        )
        store = MilvusVectorStore.__new__(MilvusVectorStore)
        store._client = client
        store._settings = types.SimpleNamespace(collection_name="documents", milvus_write_batch_size=100)

        store.insert_chunks(
            document_id="doc-1",
            source_name="source.md",
            source_type="text",
            chunk_payloads=[
                {
                    "id": "chunk-1",
                    "document_id": "doc-1",
                    "source_name": "source.md",
                    "source_type": "text",
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "product_code": "PROD-001",
                    "product_name": "产品A",
                    "chunk_index": 0,
                    "text": "正文",
                    "metadata_json": "{}",
                    "vector": [0.1],
                }
            ],
        )

        inserted_row = client.inserts[0]["data"][0]
        self.assertNotIn("product_code", inserted_row)
        self.assertNotIn("product_name", inserted_row)
        self.assertEqual(inserted_row["brand_code"], "BRAND-001")

    def test_query_rows_by_brand_code_uses_query_iterator(self) -> None:
        iterator = _FakeQueryIterator(
            [
                [{"id": "1", "brand_code": "100204"}],
                [{"id": "2", "brand_code": "100204"}],
            ]
        )

        class _Client:
            def query_iterator(self, **kwargs):
                self.calls = kwargs
                return iterator

        store = MilvusVectorStore.__new__(MilvusVectorStore)
        store._client = _Client()

        rows = store._query_rows_by_brand_code(
            collection_name="brand_chunks",
            brand_code="100204",
            output_fields=["id", "brand_code"],
        )

        self.assertEqual(
            rows,
            [
                {"id": "1", "brand_code": "100204"},
                {"id": "2", "brand_code": "100204"},
            ],
        )
        self.assertTrue(iterator.closed)
        self.assertEqual(store._client.calls["filter"], 'brand_code == "100204"')

    def test_query_rows_by_brand_code_refuses_partial_fallback(self) -> None:
        class _Client:
            def query(self, **kwargs):
                raise AssertionError("query() should not be called")

        store = MilvusVectorStore.__new__(MilvusVectorStore)
        store._client = _Client()

        with self.assertRaisesRegex(RuntimeError, "refusing partial brand rename"):
            store._query_rows_by_brand_code(
                collection_name="brand_chunks",
                brand_code="100204",
                output_fields=["id", "brand_code"],
            )

    def test_rename_brand_streams_rows_with_configured_iterator_batch_size(self) -> None:
        client = _FakeRenameMilvusClient()
        store = MilvusVectorStore.__new__(MilvusVectorStore)
        store._client = client
        store._settings = types.SimpleNamespace(
            collection_name="documents",
            milvus_iterator_batch_size=1,
            milvus_write_batch_size=1,
        )
        store._facts_collection_name = "documents_facts"

        result = store.rename_brand(
            brand_code="BRAND-001",
            old_brand_name="旧品牌",
            new_brand_name="新品牌",
        )

        self.assertEqual(result, {"chunks": 2, "facts": 1})
        self.assertEqual([call["batch_size"] for call in client.query_calls], [1, 1])
        self.assertEqual(
            [(call["collection_name"], len(call["data"])) for call in client.upsert_calls],
            [("documents", 1), ("documents", 1), ("documents_facts", 1)],
        )
        self.assertEqual(client.upsert_calls[0]["data"][0]["brand_name"], "新品牌")
        self.assertIn('"category": "新品牌"', client.upsert_calls[0]["data"][0]["metadata_json"])

    def test_insert_chunks_uses_configured_write_batch_size(self) -> None:
        client = _FakeMilvusClient()
        store = MilvusVectorStore.__new__(MilvusVectorStore)
        store._client = client
        store._settings = types.SimpleNamespace(collection_name="documents", milvus_write_batch_size=2)

        store.insert_chunks(
            document_id="doc-1",
            source_name="source.md",
            source_type="text",
            chunk_payloads=[
                {"id": "chunk-1", "vector": [0.1]},
                {"id": "chunk-2", "vector": [0.2]},
                {"id": "chunk-3", "vector": [0.3]},
            ],
        )

        self.assertEqual(
            [(call["collection_name"], len(call["data"])) for call in client.inserts],
            [("documents", 2), ("documents", 1)],
        )

    def test_upsert_facts_uses_configured_write_batch_size(self) -> None:
        client = _FakeMilvusClient()
        store = MilvusVectorStore.__new__(MilvusVectorStore)
        store._client = client
        store._settings = types.SimpleNamespace(milvus_write_batch_size=2)
        store._facts_collection_name = "documents_facts"

        store.upsert_facts(
            [
                {"fact_id": "fact-1", "vector": [0.1]},
                {"fact_id": "fact-2", "vector": [0.2]},
                {"fact_id": "fact-3", "vector": [0.3]},
            ]
        )

        self.assertEqual(
            [(call["collection_name"], len(call["data"])) for call in client.upserts],
            [("documents_facts", 2), ("documents_facts", 1)],
        )


if __name__ == "__main__":
    unittest.main()
