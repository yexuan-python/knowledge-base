from __future__ import annotations

import types
import unittest
from unittest.mock import AsyncMock

from knowledge_base.brand.application import BrandApplicationDependencies, BrandApplicationService
from knowledge_base.brand.schemas import KnowledgeBasicInfo, KnowledgeProduct, KnowledgeUpdateRequest

from tests.fakes.brand_flow import (
    FakeBrandKnowledgeStore,
    FakeBrandKnowledgeUpdateAuditStore,
    FakeBrandProductStore,
    FakeBrandStore,
    FakeDocumentCategoryStore,
    FakeIndustryStore,
    FakeSettings,
)


def _build_application(**dependency_overrides) -> BrandApplicationService:
    dependencies = {
        "settings": FakeSettings(),
        "brands": FakeBrandStore(knowledge_revision="LXKG-SLPP-V1.0.0-20260630010101"),
        "brand_products": FakeBrandProductStore(),
        "brand_knowledge": FakeBrandKnowledgeStore(),
        "industries": FakeIndustryStore(),
        "brand_knowledge_sessions": types.SimpleNamespace(),
        "document_registry": None,
        "document_categories": FakeDocumentCategoryStore(),
        "fact_relations": None,
        "store": None,
        "document_app": None,
        "delete_document": AsyncMock(),
        "get_full_text": lambda _document_id: None,
        "ingest_staged_file": AsyncMock(),
        "ingest_from_url": AsyncMock(),
        "delete_document_by_attachment_name": AsyncMock(),
    }
    dependencies.update(dependency_overrides)
    return BrandApplicationService(BrandApplicationDependencies(**dependencies))


class BrandKnowledgeUpdateRevisionGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_knowledge_update_no_change_keeps_current_revision(self) -> None:
        application = _build_application()

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
                website=["https://example.com"],
                customer_service_hotline="400-000-0000",
                official_wechat_account="example_wechat",
                intro="品牌简介",
                brand_enterprise_entity="示例企业主体",
                business_license_image_path="https://example.com/license.png",
                industry_id="1",
                english_name="Demo Brand",
                positioning="高端定位",
                advantages="渠道优势",
                mission="服务用户",
                vision="成为第一",
                target_regions=["中国", "新加坡"],
            ),
        )

        result = await application.update_knowledge(request)

        self.assertEqual(result["knowledge_revision"], "LXKG-SLPP-V1.0.0-20260630010101")
        self.assertNotIn("knowledge_revision", application._deps.brands.last_upsert_brand_kwargs)

    async def test_knowledge_update_product_code_only_change_keeps_current_revision(self) -> None:
        audit_store = FakeBrandKnowledgeUpdateAuditStore()
        enqueue_refresh = AsyncMock()
        application = _build_application(
            brand_knowledge_update_audits=audit_store,
            enqueue_brand_full_knowledge_refresh_job=enqueue_refresh,
        )

        result = await application.update_knowledge(
            KnowledgeUpdateRequest(
                basic_info=KnowledgeBasicInfo(
                    brand_name="示例品牌",
                    brand_code="BRAND-001",
                ),
                products=[
                    KnowledgeProduct(
                        product_code="PROD-STAR",
                        name="明星产品",
                    )
                ],
            )
        )

        self.assertEqual(result["knowledge_revision"], "LXKG-SLPP-V1.0.0-20260630010101")
        self.assertEqual(result["updated_sections"], [])
        self.assertNotIn("background_job_id", result)
        self.assertEqual(audit_store.created_calls, [])
        enqueue_refresh.assert_not_awaited()
        self.assertEqual(
            application._deps.brand_products.last_products_upsert["products"][0]["product_code"],
            "PROD-STAR",
        )

    async def test_knowledge_update_industry_id_only_change_keeps_current_revision(self) -> None:
        audit_store = FakeBrandKnowledgeUpdateAuditStore()
        enqueue_refresh = AsyncMock()
        application = _build_application(
            brand_knowledge_update_audits=audit_store,
            enqueue_brand_full_knowledge_refresh_job=enqueue_refresh,
        )

        result = await application.update_knowledge(
            KnowledgeUpdateRequest(
                basic_info=KnowledgeBasicInfo(
                    brand_name="示例品牌",
                    brand_code="BRAND-001",
                    industry_id="223",
                ),
            )
        )

        self.assertEqual(result["knowledge_revision"], "LXKG-SLPP-V1.0.0-20260630010101")
        self.assertEqual(result["updated_sections"], [])
        self.assertNotIn("background_job_id", result)
        self.assertEqual(len(audit_store.created_calls), 1)
        created_call = audit_store.created_calls[0]
        self.assertRegex(str(created_call["audit_id"]), r"^knowledge_metadata_update:[0-9a-f]{32}$")
        self.assertEqual(created_call["source_type"], "knowledge_metadata_update")
        self.assertRegex(str(created_call["source_task_id"]), r"^knowledge_update:[0-9a-f]{32}$")
        self.assertEqual(created_call["knowledge_revision"], "LXKG-SLPP-V1.0.0-20260630010101")
        self.assertEqual(
            created_call["entries"],
            [
                {
                    "section": "brands",
                    "title": "品牌基础信息",
                    "action": "update",
                    "before": {"industry_id": 1},
                    "after": {"industry_id": 223},
                }
            ],
        )
        enqueue_refresh.assert_not_awaited()
        self.assertEqual(application._deps.brands.last_upsert_brand_kwargs["industry_id"], 223)
        self.assertNotIn("knowledge_revision", application._deps.brands.last_upsert_brand_kwargs)

    async def test_knowledge_update_competitor_aliases_only_change_keeps_current_revision(self) -> None:
        audit_store = FakeBrandKnowledgeUpdateAuditStore()
        enqueue_refresh = AsyncMock()
        brand_knowledge = FakeBrandKnowledgeStore()
        brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "competitors",
                "content_json": [
                    {
                        "name": "小罐茶",
                        "aliases": ["小罐", "小罐茶业", "小罐茶大成实效", "小罐茶XiaoGuanCha"],
                        "introduction": "",
                        "official_websites": [],
                        "logo_urls": [],
                        "strengths": [],
                        "differentiated_positioning": [],
                        "comparison_dimensions": [],
                        "other_info": [],
                    }
                ],
            }
        ]
        application = _build_application(
            brand_knowledge=brand_knowledge,
            brand_knowledge_update_audits=audit_store,
            enqueue_brand_full_knowledge_refresh_job=enqueue_refresh,
        )

        result = await application.update_knowledge(
            KnowledgeUpdateRequest(
                basic_info=KnowledgeBasicInfo(
                    brand_name="示例品牌",
                    brand_code="BRAND-001",
                ),
                competitors=[
                    {
                        "name": "小罐茶",
                        "aliases": [],
                    }
                ],
            )
        )

        self.assertEqual(result["knowledge_revision"], "LXKG-SLPP-V1.0.0-20260630010101")
        self.assertEqual(result["updated_sections"], [])
        self.assertEqual(result["deleted_sections"], [])
        self.assertNotIn("background_job_id", result)
        self.assertEqual(audit_store.created_calls, [])
        enqueue_refresh.assert_not_awaited()
        competitor_upserts = [
            item for item in brand_knowledge.last_knowledge_upserts
            if item[1] == "competitors"
        ]
        self.assertEqual(
            competitor_upserts[-1][3],
            [
                {
                    "name": "小罐茶",
                    "aliases": [],
                    "introduction": "",
                    "official_websites": [],
                    "logo_urls": [],
                    "strengths": [],
                    "differentiated_positioning": [],
                    "comparison_dimensions": [],
                    "other_info": [],
                }
            ],
        )
