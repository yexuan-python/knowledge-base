from __future__ import annotations

import json
import types
import unittest
import uuid

from knowledge_base.infrastructure.qdrant_store import QdrantVectorStore, _qdrant_point_id


class _FakeQdrantClient:
    def __init__(self) -> None:
        self.upserts: list[dict[str, object]] = []
        self.searches: list[dict[str, object]] = []
        self.deletes: list[dict[str, object]] = []
        self.retrieves: list[dict[str, object]] = []
        self.scrolls: list[dict[str, object]] = []
        self.search_result: list[object] = []
        self.retrieve_result: list[object] = []
        self.scroll_result: tuple[list[object], object | None] = ([], None)

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)

    def search(self, **kwargs):
        self.searches.append(kwargs)
        return self.search_result

    def delete(self, **kwargs):
        self.deletes.append(kwargs)

    def retrieve(self, **kwargs):
        self.retrieves.append(kwargs)
        return self.retrieve_result

    def scroll(self, **kwargs):
        self.scrolls.append(kwargs)
        return self.scroll_result


class QdrantVectorStoreTests(unittest.TestCase):
    def _build_store(self, client: _FakeQdrantClient | None = None) -> QdrantVectorStore:
        settings = types.SimpleNamespace(
            qdrant_collection_name="documents",
            qdrant_facts_collection_name="documents_facts",
        )
        store = QdrantVectorStore.__new__(QdrantVectorStore)
        store._settings = settings
        store._client = client or _FakeQdrantClient()
        store._collection_name = "documents"
        store._facts_collection_name = "documents_facts"
        return store

    def test_qdrant_point_id_maps_arbitrary_source_ids_to_stable_uuid(self) -> None:
        point_id = _qdrant_point_id("asset_21:0")

        self.assertEqual(point_id, _qdrant_point_id("asset_21:0"))
        self.assertNotEqual(point_id, "asset_21:0")
        self.assertEqual(str(uuid.UUID(point_id)), point_id)

    def test_insert_chunks_preserves_original_chunk_id_in_payload(self) -> None:
        client = _FakeQdrantClient()
        store = self._build_store(client)

        store.insert_chunks(
            document_id="doc-1",
            source_name="source.md",
            source_type="text",
            chunk_payloads=[
                {
                    "id": "chunk:1",
                    "document_id": "doc-1",
                    "source_name": "source.md",
                    "source_type": "text",
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "chunk_index": 0,
                    "text": "hello",
                    "metadata_json": json.dumps({"category": "示例品牌"}, ensure_ascii=False),
                    "vector": [0.1, 0.2],
                }
            ],
        )

        point = client.upserts[0]["points"][0]
        self.assertEqual(point.id, _qdrant_point_id("chunk:1"))
        self.assertEqual(point.payload["id"], "chunk:1")
        self.assertEqual(point.payload["document_id"], "doc-1")
        self.assertEqual(point.vector, [0.1, 0.2])

    def test_search_uses_document_and_source_filters_and_returns_milvus_shaped_hits(self) -> None:
        client = _FakeQdrantClient()
        client.search_result = [
            types.SimpleNamespace(
                id=_qdrant_point_id("chunk:1"),
                score=0.91,
                payload={
                    "id": "chunk:1",
                    "document_id": "doc-1",
                    "source_name": "source.md",
                    "source_type": "text",
                    "chunk_index": 0,
                    "text": "hello",
                    "metadata_json": "{}",
                },
            )
        ]
        store = self._build_store(client)

        result = store.search(
            query_vector=[0.1, 0.2],
            top_k=3,
            document_ids=["doc-1", "doc-2"],
            source_types=["text"],
        )

        query_filter = client.searches[0]["query_filter"]
        conditions = {condition.key: condition.match for condition in query_filter.must}
        self.assertEqual(conditions["document_id"].any, ["doc-1", "doc-2"])
        self.assertEqual(conditions["source_type"].any, ["text"])
        self.assertEqual(
            result,
            [
                {
                    "id": "chunk:1",
                    "distance": 0.91,
                    "entity": {
                        "document_id": "doc-1",
                        "source_name": "source.md",
                        "source_type": "text",
                        "chunk_index": 0,
                        "text": "hello",
                        "metadata_json": "{}",
                    },
                }
            ],
        )

    def test_search_facts_uses_category_and_brand_filters(self) -> None:
        client = _FakeQdrantClient()
        client.search_result = [
            types.SimpleNamespace(
                id=_qdrant_point_id("fact-1"),
                score=0.87,
                payload={
                    "fact_id": "fact-1",
                    "fact_text": "示例事实",
                    "category": "示例品牌",
                    "document_ids": json.dumps(["doc-1"]),
                },
            )
        ]
        store = self._build_store(client)

        result = store.search_facts(
            [0.1, 0.2],
            "示例品牌",
            5,
            brand_code="BRAND-001",
        )

        query_filter = client.searches[0]["query_filter"]
        conditions = {condition.key: condition.match for condition in query_filter.must}
        self.assertEqual(conditions["category"].value, "示例品牌")
        self.assertEqual(conditions["brand_code"].value, "BRAND-001")
        self.assertEqual(result[0]["id"], "fact-1")
        self.assertEqual(result[0]["entity"]["fact_text"], "示例事实")

    def test_delete_documents_by_brand_code_uses_payload_filter(self) -> None:
        client = _FakeQdrantClient()
        store = self._build_store(client)

        store.delete_documents_by_brand_code("BRAND-001")

        points_selector = client.deletes[0]["points_selector"]
        condition = points_selector.filter.must[0]
        self.assertEqual(condition.key, "brand_code")
        self.assertEqual(condition.match.value, "BRAND-001")


if __name__ == "__main__":
    unittest.main()
