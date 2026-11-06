from __future__ import annotations

import types
import unittest
from unittest.mock import AsyncMock

from knowledge_base.brand.application import BrandApplicationDependencies, BrandApplicationService
from knowledge_base.brand.schemas import KnowledgeBasicInfo, KnowledgeUpdateRequest

from tests.fakes.brand_flow import (
    FakeBrandKnowledgeStore,
    FakeBrandProductStore,
    FakeBrandStore,
    FakeDocumentCategoryStore,
    FakeIndustryStore,
    FakeMilvusRenameStore,
    FakeSettings,
)


def _build_application(*, brand_store, document_categories=None, enqueue_job=None) -> BrandApplicationService:
    return BrandApplicationService(
        BrandApplicationDependencies(
            settings=FakeSettings(),
            brands=brand_store,
            brand_products=FakeBrandProductStore(),
            brand_knowledge=FakeBrandKnowledgeStore(),
            industries=FakeIndustryStore(),
            brand_knowledge_sessions=types.SimpleNamespace(),
            document_registry=None,
            document_categories=document_categories or FakeDocumentCategoryStore(),
            fact_relations=None,
            store=FakeMilvusRenameStore(),
            document_app=None,
            delete_document=AsyncMock(),
            get_full_text=lambda _document_id: None,
            ingest_staged_file=AsyncMock(),
            ingest_from_url=AsyncMock(),
            delete_document_by_attachment_name=AsyncMock(),
            enqueue_brand_knowledge_update_job=enqueue_job,
        )
    )


class BrandKnowledgeUpdateRenameTests(unittest.IsolatedAsyncioTestCase):
    async def test_knowledge_update_auto_renames_when_brand_code_matches_but_brand_name_differs(self) -> None:
        brand_store = FakeBrandStore()
        document_categories = FakeDocumentCategoryStore()
        application = _build_application(
            brand_store=brand_store,
            document_categories=document_categories,
        )

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="珠海示例品牌",
                brand_code="BRAND-001",
                intro="更新后的简介",
            ),
            skip_full_ai_knowledge_sync=True,
        )

        result = await application.update_knowledge(request)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["brand_name"], "珠海示例品牌")
        self.assertEqual(
            brand_store.rename_calls,
            [
                {
                    "brand_code": "BRAND-001",
                    "new_brand_name": "珠海示例品牌",
                }
            ],
        )
        self.assertEqual(brand_store._brand_row["brand_name"], "珠海示例品牌")
        self.assertEqual(
            application._deps.brands.last_upsert_brand_kwargs["brand_name"],
            "珠海示例品牌",
        )
        self.assertEqual(
            brand_store.rename_job_calls,
            [
                {
                    "brand_code": "BRAND-001",
                    "new_brand_name": "珠海示例品牌",
                    "old_brand_name": "示例品牌",
                    "background_job": {
                        "job_id": "bg:brand_rename_milvus_sync:BRAND-001:珠海示例品牌",
                        "job_type": "brand_rename_milvus_sync",
                        "source_type": "brand_rename",
                        "source_id": "BRAND-001:珠海示例品牌",
                        "status": "waiting",
                    },
                }
            ],
        )
        self.assertEqual(document_categories.invalidated_categories, [None])

    async def test_knowledge_update_rename_only_keeps_revision_and_skips_background_job(self) -> None:
        enqueue_job = AsyncMock(return_value={"job_id": "job-1", "status": "queued"})
        brand_store = FakeBrandStore(knowledge_revision="LXKG-SLPP-V1.0.3-20260902160000")
        application = _build_application(
            brand_store=brand_store,
            enqueue_job=enqueue_job,
        )

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="珠海示例品牌",
                brand_code="BRAND-001",
            ),
        )

        result = await application.update_knowledge(request)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["brand_name"], "珠海示例品牌")
        self.assertEqual(result["knowledge_revision"], "LXKG-SLPP-V1.0.3-20260902160000")
        self.assertNotIn("background_job_id", result)
        self.assertEqual(
            brand_store.rename_calls,
            [
                {
                    "brand_code": "BRAND-001",
                    "new_brand_name": "珠海示例品牌",
                }
            ],
        )
        self.assertEqual(
            brand_store.rename_job_calls,
            [
                {
                    "brand_code": "BRAND-001",
                    "new_brand_name": "珠海示例品牌",
                    "old_brand_name": "示例品牌",
                    "background_job": {
                        "job_id": "bg:brand_rename_milvus_sync:BRAND-001:珠海示例品牌",
                        "job_type": "brand_rename_milvus_sync",
                        "source_type": "brand_rename",
                        "source_id": "BRAND-001:珠海示例品牌",
                        "status": "waiting",
                    },
                }
            ],
        )
        self.assertNotIn("knowledge_revision", application._deps.brands.last_upsert_brand_kwargs)
        enqueue_job.assert_not_awaited()
