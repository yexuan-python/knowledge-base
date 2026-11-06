from __future__ import annotations

import asyncio
import types
import unittest
from unittest.mock import AsyncMock, patch

from knowledge_base.brand.application import BrandApplicationDependencies, BrandApplicationService

from tests.fakes.brand_flow import (
    EmptyBrandProductStore,
    EmptyWebsiteAndEnglishBrandStore,
    FakeBrandKnowledgeStore,
    FakeBrandStore,
    FakeDocumentCategoryStore,
    FakeDocumentRegistryStore,
    FakeIndustryStore,
    FakeSettings,
    _build_brand_application,
)


class BrandMetaQueryTests(unittest.TestCase):
    def test_get_brand_meta_builds_meta_and_path_index(self) -> None:
        application = _build_brand_application()
        application._deps.brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "company_info",
                "content_json": {
                    "brand_subject_name": "示例品牌主体名称",
                    "company_intro": "示例企业简介",
                    "company_address": "上海市徐汇区示例路 8 号",
                },
            },
            {
                "knowledge_type": "competitors",
                "content_json": [{"name": "竞品A"}],
            },
            {
                "knowledge_type": "official_malls",
                "content_json": [
                    {
                        "store_name": "品牌旗舰店",
                        "platform": "天猫",
                        "homepage_urls": ["https://mall.example.com"],
                        "main_categories": ["智能汽车"],
                        "advantages": ["官方正品"],
                        "related_products": [1001],
                        "other_info": ["支持售后咨询"],
                    }
                ],
            },
            {
                "knowledge_type": "official_media_matrix",
                "content_json": [
                    {
                        "media_platform": "微信公众号",
                        "account_name": "品牌服务号",
                        "account_id": "brand-service",
                        "is_official": "是",
                        "related_products": ["200001"],
                        "other_info": ["新品发布"],
                    }
                ],
            },
            {
                "knowledge_type": "attachment_products",
                "content_json": [
                    {
                        "name": "明星产品",
                        "product_description": "重复产品不会覆盖正式产品",
                    },
                    {
                        "name": "附件新品",
                        "product_description": "附件解析出来的新产品",
                        "product_website": "https://example.com/attachment-product",
                    },
                ],
            },
        ]

        async def _fake_summarize(text: str, model: str | None = None, settings=None) -> str:
            for line in text.splitlines():
                normalized = line.strip()
                if normalized.startswith("# "):
                    return f"{normalized[2:]} 摘要"
            return "默认摘要"

        with patch(
            "knowledge_base.brand.application.service.summarize_text",
            AsyncMock(side_effect=_fake_summarize),
        ):
            result = asyncio.run(
                application.get_brand_meta(
                    brand_code="BRAND-001",
                    include_path_index=True,
                )
            )

        self.assertIsNotNone(result)
        meta = result["meta"]
        self.assertEqual(meta["brand_code"], "BRAND-001")
        self.assertEqual(meta["brand_name"], "示例品牌")
        self.assertEqual(meta["industry"], "消费品")
        self.assertEqual(meta["official_websites"], ["https://example.com"])
        self.assertEqual(meta["knowledge_revision"], "demo-2026-06-23")
        self.assertEqual(meta["company_profile"]["brand_subject_name"], "示例品牌主体名称")
        self.assertEqual(meta["products"][0]["path"], "产品信息/明星产品")
        self.assertEqual(meta["products"][1]["path"], "产品信息/附件新品")
        self.assertEqual(meta["competitors"][0]["path"], "竞品信息/竞品A")
        self.assertNotIn("official_malls", meta)
        self.assertNotIn("official_media_matrix", meta)
        paths = [item["path"] for item in result["path_index"]]
        self.assertIn("品牌基础信息/品牌介绍", paths)
        self.assertIn("品牌基础信息/公司档案", paths)
        self.assertIn("产品信息/明星产品", paths)
        self.assertIn("产品信息/附件新品", paths)
        self.assertIn("竞品信息/竞品A", paths)
        self.assertIn("品牌基础信息/官方商城", paths)
        self.assertIn("品牌基础信息/官方媒体与矩阵", paths)
        self.assertNotIn("品牌基础信息/附件资料", paths)
        summaries = {item["path"]: item["summary"] for item in result["path_index"]}
        self.assertEqual(summaries["品牌基础信息/品牌介绍"], "品牌介绍 摘要")
        self.assertEqual(summaries["品牌基础信息/公司档案"], "公司档案 摘要")
        self.assertEqual(summaries["产品信息/明星产品"], "明星产品 摘要")
        self.assertEqual(summaries["产品信息/附件新品"], "附件新品 摘要")
        self.assertEqual(summaries["竞品信息/竞品A"], "竞品A 摘要")

    def test_get_brand_meta_splits_comma_delimited_brand_aliases(self) -> None:
        brand_store = FakeBrandStore()
        brand_store._brand_row["brand_alias"] = "嘉禾妇儿医院,北京嘉禾妇儿医院,嘉禾医院,嘉禾妇儿专科"
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=brand_store,
                brand_products=EmptyBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
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
            )
        )

        result = asyncio.run(
            application.get_brand_meta(
                brand_code="BRAND-001",
                include_path_index=False,
            )
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(
            result["meta"]["brand_aliases"],
            ["嘉禾妇儿医院", "北京嘉禾妇儿医院", "嘉禾医院", "嘉禾妇儿专科"],
        )

    def test_get_brand_official_malls_returns_normalized_structured_data(self) -> None:
        application = _build_brand_application()
        application._deps.brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "official_malls",
                "content_json": [
                    {
                        "store_name": "品牌旗舰店",
                        "platform": "天猫",
                        "homepage_urls": "https://mall.example.com",
                        "store_ids": ["TM-001"],
                        "main_categories": ["智能汽车"],
                        "advantages": ["官方正品", "售后无忧"],
                        "related_products": [1001, "产品B"],
                        "other_info": "支持售后咨询",
                    }
                ],
            }
        ]

        result = asyncio.run(
            application.get_brand_official_malls(
                brand_code="BRAND-001",
            )
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["brand_code"], "BRAND-001")
        self.assertEqual(result["brand_name"], "示例品牌")
        self.assertEqual(result["knowledge_revision"], "demo-2026-06-23")
        self.assertEqual(
            result["official_malls"],
            [
                {
                    "store_name": "品牌旗舰店",
                    "platform": "天猫",
                    "homepage_urls": ["https://mall.example.com"],
                    "store_ids": ["TM-001"],
                    "main_categories": ["智能汽车"],
                    "advantages": ["官方正品", "售后无忧"],
                    "related_products": [1001, "产品B"],
                    "other_info": ["支持售后咨询"],
                }
            ],
        )

    def test_get_brand_official_malls_returns_empty_list_when_missing(self) -> None:
        application = _build_brand_application()

        result = asyncio.run(
            application.get_brand_official_malls(
                brand_code="BRAND-001",
            )
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["official_malls"], [])

    def test_get_brand_meta_caches_path_index_summary_by_revision_and_truncates_content(self) -> None:
        brand_store = EmptyWebsiteAndEnglishBrandStore()
        brand_store._brand_row["intro"] = "FIRST " + ("A" * 7000)
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=brand_store,
                brand_products=EmptyBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
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
            )
        )
        application._deps.brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "company_info",
                "content_json": {
                    "brand_subject_name": "示例品牌主体名称",
                    "company_intro": "稳定的公司档案",
                },
            }
        ]

        captured_inputs: list[str] = []

        async def _fake_summarize(text: str, model: str | None = None, settings=None) -> str:
            captured_inputs.append(text)
            if "# 公司档案" in text:
                return "公司档案 摘要"
            return "FIRST 摘要" if "FIRST" in text else "SECOND 摘要"

        with patch(
            "knowledge_base.brand.application.service.summarize_text",
            AsyncMock(side_effect=_fake_summarize),
        ) as mocked_summarize:
            first_result = asyncio.run(
                application.get_brand_meta(
                    brand_code="BRAND-001",
                    include_path_index=True,
                )
            )
            brand_store._brand_row["intro"] = "SECOND " + ("B" * 7000)
            second_result = asyncio.run(
                application.get_brand_meta(
                    brand_code="BRAND-001",
                    include_path_index=True,
                )
            )
            brand_store.knowledge_revision = "demo-2026-07-01"
            brand_store._brand_row["knowledge_revision"] = "demo-2026-07-01"
            third_result = asyncio.run(
                application.get_brand_meta(
                    brand_code="BRAND-001",
                    include_path_index=True,
                )
            )

        self.assertIsNotNone(first_result)
        self.assertIsNotNone(second_result)
        self.assertIsNotNone(third_result)
        assert first_result is not None and second_result is not None and third_result is not None
        first_summaries = {item["path"]: item["summary"] for item in first_result["path_index"]}
        second_summaries = {item["path"]: item["summary"] for item in second_result["path_index"]}
        third_summaries = {item["path"]: item["summary"] for item in third_result["path_index"]}
        self.assertEqual(first_summaries["品牌基础信息/品牌介绍"], "FIRST 摘要")
        self.assertEqual(first_summaries["品牌基础信息/公司档案"], "公司档案 摘要")
        self.assertEqual(second_summaries["品牌基础信息/品牌介绍"], "FIRST 摘要")
        self.assertEqual(second_summaries["品牌基础信息/公司档案"], "公司档案 摘要")
        self.assertEqual(third_summaries["品牌基础信息/品牌介绍"], "SECOND 摘要")
        self.assertEqual(third_summaries["品牌基础信息/公司档案"], "公司档案 摘要")
        self.assertEqual(mocked_summarize.await_count, 4)
        self.assertTrue(captured_inputs)
        self.assertTrue(all(len(text) <= BrandApplicationService.PATH_INDEX_SUMMARY_MAX_CONTENT_CHARS for text in captured_inputs))
