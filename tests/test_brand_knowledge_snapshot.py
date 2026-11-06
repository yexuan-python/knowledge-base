from __future__ import annotations

import types
import unittest

from knowledge_base.brand import knowledge_extraction as brand_knowledge_extraction

from tests.fakes.brand_flow import (
    EmptyBrandProductStore,
    FakeBrandKnowledgeStore,
    FakeBrandProductStore,
    FakeBrandStore,
    FakeSettings,
)


class BrandKnowledgeSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_brand_knowledge_snapshot_uses_brand_products_as_whitelist_and_keeps_attachment_products(self) -> None:
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _settings=FakeSettings(),
            _tianyancha_client=types.SimpleNamespace(enabled=lambda: False),
        )

        async def fake_extract(
            markdown_text: str,
            *,
            brand_name: str,
            source_name: str,
            subcategory: str | None = None,
            model: str = "qwen-plus",
            settings=None,
        ):
            return {
                "basic_info": {},
                "products": [
                    {
                        "name": "明星产品",
                        "product_description": "来自 Markdown 的主产品补充",
                    },
                    {
                        "name": "附件新品",
                        "product_description": "附件里抽到的新产品",
                    },
                ],
                "company_profile": {},
                "management_team": [],
                "competitors": [],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": [],
            }

        saved_extract = brand_knowledge_extraction.extract_brand_knowledge_from_markdown
        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = fake_extract
        try:
            result = await brand_knowledge_extraction.build_brand_knowledge_snapshot_from_markdown(
                service,
                brand_name="示例品牌",
                markdown_text="# 示例品牌\n\n正文",
                source_name="示例品牌-知识库.md",
                attachments=[],
            )
        finally:
            brand_knowledge_extraction.extract_brand_knowledge_from_markdown = saved_extract

        snapshot = result["snapshot"]
        self.assertEqual([item["name"] for item in snapshot["products"]], ["明星产品"])
        self.assertEqual(
            [item["name"] for item in snapshot["attachment_products"]],
            ["明星产品", "附件新品"],
        )
        attachment_products_other_info = next(
            item for item in snapshot["other_info"]
            if item["title"] == "附件解析新增产品"
        )
        self.assertEqual(
            [item["name"] for item in attachment_products_other_info["content"]],
            ["明星产品", "附件新品"],
        )

    async def test_build_brand_knowledge_snapshot_does_not_copy_markdown_sections_into_other_info(self) -> None:
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _settings=FakeSettings(),
            _tianyancha_client=types.SimpleNamespace(enabled=lambda: False),
        )

        async def fake_extract(
            markdown_text: str,
            *,
            brand_name: str,
            source_name: str,
            subcategory: str | None = None,
            model: str = "qwen-plus",
            settings=None,
        ):
            return {
                "basic_info": {
                    "brand_name": brand_name,
                    "intro": "示例简介",
                    "positioning": ["高品质品牌"],
                    "advantages": ["安全舒适"],
                },
                "products": [
                    {
                        "name": "明星产品",
                        "product_description": "标准产品描述",
                    }
                ],
                "company_profile": {
                    "company_intro": "标准公司简介",
                    "development_history": "2018年成立品牌。",
                },
                "management_team": [],
                "competitors": [],
                "authority_honors": [{"title": "高新技术企业"}],
                "customers_cases": [],
                "sensitive_topics": [],
                "other_info": [
                    {
                        "title": "品牌推广与公益",
                        "content": "已有整理后的公益内容",
                    },
                    {
                        "title": "计价模型",
                        "content": "按件计价",
                    },
                ],
            }

        markdown_text = """
**示例品牌 · 品牌知识库**

**品牌定位(positioning)**

高品质品牌

**品牌故事/发展里程碑**

2018年成立品牌。

**公司简介**

标准公司简介

**公司所获荣誉**

1. 高新技术企业

**2.1 产品线(主推)**

* **明星产品**: 标准产品描述

**品牌推广/公益活动**

已有整理后的公益内容

**五、高频问答 FAQ**

**Q:这是什么品牌?**
A:这是一个测试品牌。

**九、服务、价格与政策**

| 维度 | 字段 | 内容 |
| --- | --- | --- |
| 价格、套餐、促销与退费 | 计价模型 | 按件计价 |
""".strip()

        saved_extract = brand_knowledge_extraction.extract_brand_knowledge_from_markdown
        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = fake_extract
        try:
            result = await brand_knowledge_extraction.build_brand_knowledge_snapshot_from_markdown(
                service,
                brand_name="示例品牌",
                markdown_text=markdown_text,
                source_name="示例品牌-知识库.md",
                attachments=[],
            )
        finally:
            brand_knowledge_extraction.extract_brand_knowledge_from_markdown = saved_extract

        snapshot = result["snapshot"]
        other_info_by_title = {
            item["title"]: item["content"]
            for item in snapshot["other_info"]
        }
        self.assertNotIn("品牌定位(positioning)", other_info_by_title)
        self.assertNotIn("品牌故事/发展里程碑", other_info_by_title)
        self.assertNotIn("公司简介", other_info_by_title)
        self.assertNotIn("公司所获荣誉", other_info_by_title)
        self.assertNotIn("2.1 产品线(主推)", other_info_by_title)
        self.assertNotIn("品牌推广/公益活动", other_info_by_title)
        self.assertNotIn("Q:这是什么品牌?", other_info_by_title)
        self.assertNotIn("五、高频问答 FAQ", other_info_by_title)
        self.assertNotIn("九、服务、价格与政策", other_info_by_title)
        self.assertIn("计价模型", other_info_by_title)
        self.assertEqual("按件计价", other_info_by_title["计价模型"])

    def test_persist_brand_knowledge_snapshot_does_not_create_main_products_without_whitelist(self) -> None:
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_products=EmptyBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
        )

        result = brand_knowledge_extraction.persist_brand_knowledge_snapshot(
            service,
            brand_name="示例品牌",
            snapshot={
                "basic_info": {"brand_name": "示例品牌"},
                "products": [
                    {
                        "name": "附件新品",
                        "product_description": "不应直接进入主产品表",
                    }
                ],
                "attachment_products": [
                    {
                        "name": "附件新品",
                        "product_description": "不应直接进入主产品表",
                    }
                ],
                "company_profile": {},
                "management_team": [],
                "competitors": [],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": [],
                "attachments": [],
                "official_malls": [],
                "official_media_matrix": [],
                "other_info": [],
            },
            source_task_id="task-snapshot-1",
        )

        self.assertIsNone(service._brand_products.last_products_upsert)
        self.assertEqual(result["snapshot"]["products"], [])
        attachment_products_upsert = next(
            item
            for item in service._brand_knowledge.last_knowledge_upserts
            if item[1] == "attachment_products"
        )
        self.assertEqual(
            attachment_products_upsert[3],
            [
                {
                    "name": "附件新品",
                    "product_alias": None,
                    "product_description": "不应直接进入主产品表",
                    "product_website": None,
                    "product_images": [],
                    "price_info": None,
                    "coverage_regions": [],
                    "product_advantages": None,
                    "target_scenarios": None,
                    "service_standard": None,
                    "service_process": None,
                    "cases_and_reputation": None,
                    "certification_info": None,
                    "core_technology": None,
                    "other_info": None,
                }
            ],
        )

    async def test_snapshot_builder_can_skip_tianyancha_while_preserving_web_fallback(self) -> None:
        class _NoTianyanchaCalls:
            def enabled(self):
                return True

            def lookup_company_profile(self, **_kwargs):
                raise AssertionError("天眼查不应在 enable_tianyancha=False 时被调用")

            def lookup_company_management(self, **_kwargs):
                raise AssertionError("天眼查管理团队不应在 enable_tianyancha=False 时被调用")

        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_products=EmptyBrandProductStore(),
            _brand_knowledge=types.SimpleNamespace(get_all_brand_knowledge_json=lambda *, brand_id: []),
            _settings=FakeSettings(tianyancha_enabled=True, tianyancha_api_key="test-key"),
            _tianyancha_client=_NoTianyanchaCalls(),
        )

        async def fake_extract(
            markdown_text: str,
            *,
            brand_name: str,
            source_name: str,
            subcategory: str | None = None,
            model: str = "qwen-plus",
            settings=None,
        ):
            return {
                "basic_info": {},
                "products": [],
                "company_profile": {},
                "management_team": [
                    {
                        "member_name": "张三",
                        "position": "",
                        "profile": "",
                        "introduction_website": "",
                        "source_section": "团队",
                    }
                ],
                "competitors": [],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": [],
            }

        async def fake_web_enrichment(**kwargs):
            self.assertEqual(kwargs["brand_name"], "示例品牌")
            return {
                "management_team": [
                    {
                        "member_name": "张三",
                        "position": "总经理",
                        "profile": "官网人物简介",
                        "introduction_website": "https://example.com/team/zhangsan",
                    }
                ]
            }

        saved_extract = brand_knowledge_extraction.extract_brand_knowledge_from_markdown
        enrichment_module = __import__("knowledge_base.brand.enrichment", fromlist=["enrich_brand_fields_from_web"])
        saved_web_func = enrichment_module.enrich_brand_fields_from_web
        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = fake_extract
        enrichment_module.enrich_brand_fields_from_web = fake_web_enrichment
        try:
            result = await brand_knowledge_extraction.build_brand_knowledge_snapshot_from_markdown(
                service,
                brand_name="示例品牌",
                markdown_text="# 示例品牌\n团队信息",
                source_name="final.md",
                enable_tianyancha=False,
            )
        finally:
            brand_knowledge_extraction.extract_brand_knowledge_from_markdown = saved_extract
            enrichment_module.enrich_brand_fields_from_web = saved_web_func

        self.assertEqual(result["snapshot"]["management_team"][0]["position"], "总经理")
        self.assertEqual(result["snapshot"]["management_team"][0]["profile"], "官网人物简介")
        self.assertEqual(
            result["snapshot"]["management_team"][0]["introduction_website"],
            "https://example.com/team/zhangsan",
        )
