from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from knowledge_base.document.application.service import (
    DocumentApplicationDependencies,
    DocumentApplicationService,
)
from knowledge_base.shared.utils import object_key_matches_current_oss_prefix


class _FakeDocumentStore:
    def __init__(self) -> None:
        self.deleted_documents: list[str] = []

    def get_fact_by_id(self, fact_id: str):
        return None

    def delete_document(self, document_id: str) -> None:
        self.deleted_documents.append(document_id)


class _FakeDocumentRegistry:
    def __init__(self) -> None:
        self.deleted_documents: list[str] = []

    def get_document_registry_entry(self, document_id: str):
        return {
            "document_id": document_id,
            "category": "示例品牌",
            "original_file_key": "示例品牌/original/doc.pdf",
            "fulltext_key": "test/示例品牌/converted/doc.md",
        }

    def delete_document_registration(self, document_id: str) -> None:
        self.deleted_documents.append(document_id)


class _FakeAttachmentLookupRegistry(_FakeDocumentRegistry):
    def __init__(self, rows: list[dict[str, object]]) -> None:
        super().__init__()
        self.rows = rows
        self.calls: list[dict[str, object]] = []

    def find_latest_success_documents_by_filename(
        self,
        original_filename: str,
        *,
        category: str | None = None,
        source_url: str | None = None,
    ) -> list[dict[str, object]]:
        self.calls.append(
            {
                "original_filename": original_filename,
                "category": category,
                "source_url": source_url,
            }
        )
        return self.rows

    def get_document_registry_entry(self, document_id: str):
        for row in self.rows:
            if row.get("document_id") == document_id:
                return {
                    "document_id": document_id,
                    "category": row.get("category") or "demo",
                }
        return None


class _FakeDocumentCategories:
    def __init__(self) -> None:
        self.removed_documents: list[str] = []
        self.invalidated_categories: list[str] = []

    def document_exists(self, document_id: str) -> bool:
        return True

    def invalidate_latest_document_ids_cache(self, category: str) -> None:
        self.invalidated_categories.append(category)

    def remove_document(self, document_id: str) -> None:
        self.removed_documents.append(document_id)


class _FakeFactRelations:
    def get_fact_ids_by_document(self, document_id: str):
        return []

    def delete_document_fact_relations(self, document_id: str) -> None:
        return None


class _FactRelationsWithSingleRelation:
    def __init__(self) -> None:
        self.deleted_relations: list[str] = []

    def get_fact_ids_by_document(self, document_id: str):
        return ["fact-1"]

    def delete_document_fact_relations(self, document_id: str) -> None:
        self.deleted_relations.append(document_id)


class _FakeOSSClient:
    enabled = True

    def __init__(self) -> None:
        self.deleted_keys: list[str] = []

    def delete_object(self, object_key: str) -> bool:
        self.deleted_keys.append(object_key)
        return True


class _FakeStoreWithFactVector:
    def __init__(self) -> None:
        self.upserted_facts: list[dict[str, object]] = []
        self.deleted_fact_ids: list[str] = []

    def get_fact_by_id(self, fact_id: str):
        return {
            "fact_id": fact_id,
            "fact_text": "示例 fact",
            "category": "示例品牌",
            "document_ids": '["doc-1", "doc-2"]',
            "vector": [0.1, 0.2, 0.3],
        }

    def upsert_fact(self, fact_data: dict, *, partial_update: bool = False) -> None:
        self.upserted_facts.append(
            {
                **fact_data,
                "_partial_update": partial_update,
            }
        )

    def delete_fact(self, fact_id: str) -> None:
        self.deleted_fact_ids.append(fact_id)


class _EmbeddingsShouldNotBeCalled:
    def embed_documents(self, _texts):
        raise AssertionError("embed_documents should not be called when fact vector is already present")


class DocumentDeleteBehaviorTests(unittest.IsolatedAsyncioTestCase):
    def _build_application(
        self,
        *,
        document_registry,
        store: _FakeDocumentStore | None = None,
        document_categories: _FakeDocumentCategories | None = None,
        oss_client: _FakeOSSClient | None = None,
    ) -> DocumentApplicationService:
        return DocumentApplicationService(
            DocumentApplicationDependencies(
                settings=None,
                store=store or _FakeDocumentStore(),
                embeddings=None,
                document_categories=document_categories or _FakeDocumentCategories(),
                document_registry=document_registry,
                fact_relations=_FakeFactRelations(),
                oss_client=oss_client or _FakeOSSClient(),
                get_document_info=lambda _document_id: None,
                get_full_text=lambda _document_id: None,
                notify_ai_failure_if_ready=None,
                finalize_task_callback_from_document=None,
            )
        )

    async def test_delete_document_filters_oss_objects_when_filter_is_provided(self) -> None:
        oss_client = _FakeOSSClient()
        store = _FakeDocumentStore()
        application = DocumentApplicationService(
            DocumentApplicationDependencies(
                settings=None,
                store=store,
                embeddings=None,
                document_categories=_FakeDocumentCategories(),
                document_registry=_FakeDocumentRegistry(),
                fact_relations=_FakeFactRelations(),
                oss_client=oss_client,
                get_document_info=lambda _document_id: {
                    "metadata_json": {
                        "oss_key": "prod/示例品牌/original/doc.pdf",
                    },
                },
                get_full_text=lambda _document_id: None,
                notify_ai_failure_if_ready=None,
                finalize_task_callback_from_document=None,
            )
        )

        with patch.dict(os.environ, {"OSS_OBJECT_KEY_PREFIX": ""}):
            deleted = await application.delete_document(
                "doc-1",
                oss_object_key_filter=object_key_matches_current_oss_prefix,
            )

        self.assertTrue(deleted)
        self.assertEqual(oss_client.deleted_keys, ["示例品牌/original/doc.pdf", "fulltext/doc-1.txt"])
        self.assertEqual(store.deleted_documents, ["doc-1"])

    async def test_delete_attachment_uses_url_for_precise_lookup(self) -> None:
        store = _FakeDocumentStore()
        registry = _FakeAttachmentLookupRegistry(
            [{"document_id": "doc-1", "category": "demo", "source_url": "https://example.com/a.pdf"}]
        )
        application = self._build_application(document_registry=registry, store=store)

        deleted_document_id = await application.delete_document_by_attachment_name(
            "品牌手册.pdf",
            url="https://example.com/a.pdf",
            category="demo",
        )

        self.assertEqual("doc-1", deleted_document_id)
        self.assertEqual(["doc-1"], store.deleted_documents)
        self.assertEqual(
            [
                {
                    "original_filename": "品牌手册.pdf",
                    "category": "demo",
                    "source_url": "https://example.com/a.pdf",
                }
            ],
            registry.calls,
        )

    async def test_delete_attachment_without_url_keeps_legacy_lookup(self) -> None:
        store = _FakeDocumentStore()
        registry = _FakeAttachmentLookupRegistry(
            [{"document_id": "doc-2", "category": "demo", "source_url": ""}]
        )
        application = self._build_application(document_registry=registry, store=store)

        deleted_document_id = await application.delete_document_by_attachment_name(
            "品牌手册.pdf",
            category="demo",
        )

        self.assertEqual("doc-2", deleted_document_id)
        self.assertEqual(["doc-2"], store.deleted_documents)
        self.assertEqual(
            [
                {
                    "original_filename": "品牌手册.pdf",
                    "category": "demo",
                    "source_url": None,
                }
            ],
            registry.calls,
        )

    async def test_delete_attachment_with_url_requires_category_when_multiple_categories_match(self) -> None:
        store = _FakeDocumentStore()
        registry = _FakeAttachmentLookupRegistry(
            [
                {"document_id": "doc-1", "category": "brand-a", "source_url": "https://example.com/a.pdf"},
                {"document_id": "doc-2", "category": "brand-b", "source_url": "https://example.com/a.pdf"},
            ]
        )
        application = self._build_application(document_registry=registry, store=store)

        with self.assertRaisesRegex(ValueError, "同 URL 附件"):
            await application.delete_document_by_attachment_name(
                "品牌手册.pdf",
                url="https://example.com/a.pdf",
            )

        self.assertEqual([], store.deleted_documents)

    async def test_remove_document_from_facts_reuses_existing_vector(self) -> None:
        store = _FakeStoreWithFactVector()
        fact_relations = _FactRelationsWithSingleRelation()
        application = DocumentApplicationService(
            DocumentApplicationDependencies(
                settings=None,
                store=store,
                embeddings=_EmbeddingsShouldNotBeCalled(),
                document_categories=_FakeDocumentCategories(),
                document_registry=_FakeDocumentRegistry(),
                fact_relations=fact_relations,
                oss_client=_FakeOSSClient(),
                get_document_info=lambda _document_id: None,
                get_full_text=lambda _document_id: None,
                notify_ai_failure_if_ready=None,
                finalize_task_callback_from_document=None,
            )
        )

        await application.remove_document_from_facts("doc-1")

        self.assertEqual(len(store.upserted_facts), 1)
        self.assertEqual(store.upserted_facts[0]["fact_id"], "fact-1")
        self.assertEqual(store.upserted_facts[0]["document_ids"], '["doc-2"]')
        self.assertEqual(store.upserted_facts[0]["vector"], [0.1, 0.2, 0.3])
        self.assertEqual(fact_relations.deleted_relations, ["doc-1"])


if __name__ == "__main__":
    unittest.main()
