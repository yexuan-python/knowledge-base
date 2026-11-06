from __future__ import annotations

import types
import unittest
from unittest.mock import AsyncMock

from knowledge_base.brand.application import BrandApplicationDependencies, BrandApplicationService

from tests.fakes.brand_flow import (
    FakeBrandFullKnowledgeStore,
    FakeBrandKnowledgeStore,
    FakeBrandProductStore,
    FakeBrandStore,
    FakeDocumentCategoryStore,
    FakeDocumentRegistryStore,
    FakeIndustryStore,
    FakeSettings,
)
from tests.fakes.delete_flow import FakeAiKnowledgeOSSClient


class BrandAiKnowledgeLookupTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_latest_ai_knowledge_returns_latest_db_record(self) -> None:
        brand_full_knowledge = FakeBrandFullKnowledgeStore()
        brand_full_knowledge.rows = [
            {
                "id": 1,
                "brand_id": 1,
                "brand_name": "示例品牌",
                "version_no": 1,
                "file_name": "【示例品牌】品牌AI知识库_V1_20260701.md",
                "oss_key": "示例品牌/ai_knowledge/【示例品牌】品牌AI知识库_V1_20260701.md",
                "created_at": None,
            },
            {
                "id": 2,
                "brand_id": 1,
                "brand_name": "示例品牌",
                "version_no": 3,
                "file_name": "【示例品牌】品牌AI知识库_V3_20260703.md",
                "oss_key": "示例品牌/ai_knowledge/【示例品牌】品牌AI知识库_V3_20260703.md",
                "created_at": None,
            },
        ]
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
                brand_full_knowledge=brand_full_knowledge,
                industries=FakeIndustryStore(),
                brand_knowledge_sessions=types.SimpleNamespace(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=FakeDocumentCategoryStore(),
                fact_relations=None,
                store=None,
                document_app=None,
                delete_document=AsyncMock(),
                get_full_text=lambda _document_id: None,
                ingest_staged_file=AsyncMock(),
                ingest_from_url=AsyncMock(),
                delete_document_by_attachment_name=AsyncMock(),
                oss_client=FakeAiKnowledgeOSSClient([]),
            )
        )

        result = application.get_latest_ai_knowledge(brand_code="BRAND-001")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["file_name"], "【示例品牌】品牌AI知识库_V3_20260703.md")
        self.assertEqual(result["version_no"], 3)
        self.assertEqual(result["source"], "brand_full_knowledge_files")
        self.assertEqual(
            result["oss_url"],
            "https://oss.example.com/示例品牌/ai_knowledge/【示例品牌】品牌AI知识库_V3_20260703.md",
        )

    async def test_get_latest_ai_knowledge_ignores_skipped_draft_records(self) -> None:
        brand_full_knowledge = FakeBrandFullKnowledgeStore()
        brand_full_knowledge.rows = [
            {
                "id": 1,
                "brand_id": 1,
                "brand_name": "示例品牌",
                "version_no": 1,
                "file_name": "【示例品牌】品牌AI知识库_V1_20260701.md",
                "oss_key": "示例品牌/ai_knowledge/【示例品牌】品牌AI知识库_V1_20260701.md",
                "is_latest": True,
                "ingest_status": "success",
                "created_at": None,
            },
            {
                "id": 2,
                "brand_id": 1,
                "brand_name": "示例品牌",
                "version_no": 2,
                "file_name": "【示例品牌】品牌AI知识库_V2_20260702.md",
                "oss_key": "示例品牌/ai_knowledge/【示例品牌】品牌AI知识库_V2_20260702.md",
                "is_latest": False,
                "ingest_status": "skipped",
                "error_message": "draft_only: skipped vector/fact/search ingestion",
                "created_at": None,
            },
        ]
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
                brand_full_knowledge=brand_full_knowledge,
                industries=FakeIndustryStore(),
                brand_knowledge_sessions=types.SimpleNamespace(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=FakeDocumentCategoryStore(),
                fact_relations=None,
                store=None,
                document_app=None,
                delete_document=AsyncMock(),
                get_full_text=lambda _document_id: None,
                ingest_staged_file=AsyncMock(),
                ingest_from_url=AsyncMock(),
                delete_document_by_attachment_name=AsyncMock(),
                oss_client=FakeAiKnowledgeOSSClient([]),
            )
        )

        result = application.get_latest_ai_knowledge(brand_code="BRAND-001")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["file_name"], "【示例品牌】品牌AI知识库_V1_20260701.md")
        self.assertEqual(result["version_no"], 1)

    async def test_get_latest_ai_knowledge_falls_back_to_latest_oss_markdown(self) -> None:
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
                brand_full_knowledge=FakeBrandFullKnowledgeStore(),
                industries=FakeIndustryStore(),
                brand_knowledge_sessions=types.SimpleNamespace(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=FakeDocumentCategoryStore(),
                fact_relations=None,
                store=None,
                document_app=None,
                delete_document=AsyncMock(),
                get_full_text=lambda _document_id: None,
                ingest_staged_file=AsyncMock(),
                ingest_from_url=AsyncMock(),
                delete_document_by_attachment_name=AsyncMock(),
                oss_client=FakeAiKnowledgeOSSClient(
                    [
                        "示例品牌/ai_knowledge/【示例品牌】品牌AI知识库_V1_20260701.md",
                        "示例品牌/ai_knowledge/【示例品牌】品牌AI知识库_V4_20260702.md",
                        "示例品牌/ai_knowledge/【示例品牌】品牌AI知识库_V3_20260703.md",
                        "示例品牌/ai_knowledge/【示例品牌】品牌AI知识库_V4_20260702.pdf",
                    ]
                ),
            )
        )

        result = application.get_latest_ai_knowledge(brand_code="BRAND-001")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["file_name"], "【示例品牌】品牌AI知识库_V4_20260702.md")
        self.assertEqual(result["version_no"], 4)
        self.assertEqual(result["source"], "oss")
