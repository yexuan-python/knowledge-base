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
    FakeSettings,
)


def _build_application(*, brands=None) -> BrandApplicationService:
    return BrandApplicationService(
        BrandApplicationDependencies(
            settings=FakeSettings(),
            brands=brands or FakeBrandStore(knowledge_revision="LXKG-SLPP-V1.0.0-20260630010101"),
            brand_products=FakeBrandProductStore(),
            brand_knowledge=FakeBrandKnowledgeStore(),
            industries=FakeIndustryStore(),
            brand_knowledge_sessions=types.SimpleNamespace(),
            document_registry=None,
            document_categories=FakeDocumentCategoryStore(),
            fact_relations=None,
            store=None,
            document_app=None,
            delete_document=AsyncMock(),
            get_full_text=lambda _document_id: None,
            ingest_staged_file=AsyncMock(),
            ingest_from_url=AsyncMock(),
            delete_document_by_attachment_name=AsyncMock(),
        )
    )


class BrandKnowledgeUpdateNormalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_knowledge_update_treats_brand_other_info_stringified_empty_list_as_none(self) -> None:
        brand_store = FakeBrandStore()
        brand_store._brand_row["other_info"] = "旧补充信息"
        application = _build_application(brands=brand_store)

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
                other_info="[]",
            ),
        )

        result = await application.update_knowledge(request)

        self.assertEqual(result["status"], "success")
        self.assertIsNone(application._deps.brands.last_upsert_brand_kwargs["other_info"])
        self.assertEqual(application._deps.brands._brand_row["other_info"], "旧补充信息")

    async def test_knowledge_update_accepts_basic_info_scalar_lists(self) -> None:
        application = _build_application()

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
                customer_service_hotline=[],
                positioning=["新定位"],
                advantages=["优势A", "优势B"],
                mission=[],
                vision=["新愿景"],
            ),
            skip_full_ai_knowledge_sync=True,
        )

        await application.update_knowledge(request)

        payload = application._deps.brands.last_upsert_brand_kwargs
        self.assertEqual(payload["customer_service_hotline"], [])
        self.assertEqual(payload["positioning"], ["新定位"])
        self.assertEqual(payload["advantages"], ["优势A", "优势B"])
        self.assertEqual(payload["mission"], [])
        self.assertEqual(payload["vision"], ["新愿景"])

    async def test_knowledge_update_splits_customer_service_hotline_values(self) -> None:
        application = _build_application()

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
                customer_service_hotline=["400-9191-666,13366757920,13366757976"],
                positioning=["新定位A,新定位B"],
            ),
            skip_full_ai_knowledge_sync=True,
        )

        await application.update_knowledge(request)

        payload = application._deps.brands.last_upsert_brand_kwargs
        self.assertEqual(
            payload["customer_service_hotline"],
            ["400-9191-666", "13366757920", "13366757976"],
        )
        self.assertEqual(payload["positioning"], ["新定位A,新定位B"])

    async def test_knowledge_update_brand_long_text_fields_only_split_on_newlines(self) -> None:
        application = _build_application()

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
                positioning="中国领先的原生AI营销技术公司\n端到端，一站式的AI营销Agent服务体系",
                advantages="AI数字资产沉淀（知识库，内容矩阵，AI官网，AI百科）\n转化归因承接（推荐，留资，线索到成交闭环）",
                mission="成为企业在 AI 世界中不可替代的增长基础设施。",
                vision="让品牌赢在AI时代",
            ),
            skip_full_ai_knowledge_sync=True,
        )

        await application.update_knowledge(request)

        payload = application._deps.brands.last_upsert_brand_kwargs
        self.assertEqual(
            payload["positioning"],
            [
                "中国领先的原生AI营销技术公司",
                "端到端，一站式的AI营销Agent服务体系",
            ],
        )
        self.assertEqual(
            payload["advantages"],
            [
                "AI数字资产沉淀（知识库，内容矩阵，AI官网，AI百科）",
                "转化归因承接（推荐，留资，线索到成交闭环）",
            ],
        )
        self.assertEqual(
            payload["mission"],
            ["成为企业在 AI 世界中不可替代的增长基础设施。"],
        )
        self.assertEqual(payload["vision"], ["让品牌赢在AI时代"])
