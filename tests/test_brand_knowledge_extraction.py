from __future__ import annotations

import types
import unittest

from knowledge_base.brand import knowledge_extraction as brand_knowledge_extraction

from tests.fakes.brand_flow import (
    FakeBrandKnowledgeStore,
    FakeBrandProductStore,
    FakeBrandStore,
    FakeDocumentCategoryStore,
    FakeDocumentRegistryStore,
    FakeSettings,
    FakeUploadTaskStore,
)


class BrandKnowledgeExtractionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._original_extract = brand_knowledge_extraction.extract_brand_knowledge_from_markdown

    def tearDown(self) -> None:
        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = self._original_extract

    async def test_extract_brand_knowledge_merges_per_file_results(self) -> None:
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _document_categories=FakeDocumentCategoryStore(),
            _document_registry=FakeDocumentRegistryStore(),
            _upload_tasks=FakeUploadTaskStore(),
            _settings=FakeSettings(),
            _tianyancha_client=types.SimpleNamespace(enabled=lambda: False),
            get_full_text=lambda document_id: f"# {document_id}\n正文",
            _get_document_info=lambda document_id: {"metadata_json": {"subcategory": "产品A" if document_id == "doc-2" else None}},
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
            if source_name == "品牌手册.md":
                return {
                    "basic_info": {
                        "official_wechat_account": "md_wechat",
                        "target_regions": ["中国", "新加坡"],
                    },
                    "products": [
                        {
                            "name": "明星产品",
                            "product_alias": "A产品",
                            "product_description": "来自md的产品介绍",
                            "product_website": "https://md.example.com/product-a",
                            "product_images": ["https://md.example.com/product-a.png"],
                            "price_info": "99元/月",
                            "coverage_regions": ["中国", "新加坡"],
                            "product_advantages": "上手快，成本低",
                            "target_scenarios": "客服、运营、销售",
                            "service_standard": "7x24小时支持",
                            "service_process": "咨询-开通-培训-运营",
                            "cases_and_reputation": "服务过多家头部企业",
                            "certification_info": "ISO认证",
                            "core_technology": "自研智能引擎",
                        },
                        {
                            "name": "无关产品",
                            "product_alias": "无关别名",
                            "product_description": "这条不该进入结果",
                        }
                    ],
                    "company_profile": {"company_intro": "品牌介绍", "company_address": "上海"},
                    "management_team": [{"member_name": "张三", "position": "CEO", "profile": "负责战略", "introduction_website": "", "source_section": "团队"}],
                    "competitors": [{"name": "竞品A", "competitors_alias": "竞A", "competitors_description": "竞品介绍", "website": "", "competitors_logo": "", "competitive_advantages": "渠道广", "differentiated_positioning": "", "comparison_dimensions": "", "source_section": "竞品"}],
                    "authority_honors": [],
                    "customers_cases": [{"case_name": "门店升级", "cooperation_time": "", "customer_name": "客户A", "cooperation_product": "", "cooperation_highlight": "转化提升", "customer_feedback": "帮助客户升级门店", "source_section": "案例"}],
                    "sensitive_topics": [],
                }
            return {
                "basic_info": {},
                "products": [],
                "company_profile": {"brand_subject_name": "示例品牌主体名称", "company_address": "上海市"},
                "management_team": [{"member_name": "张三", "position": "创始人兼CEO", "profile": "曾任高管", "introduction_website": "", "source_section": "团队"}],
                "competitors": [{"name": "竞品A", "competitors_alias": "竞A", "competitors_description": "竞品更高端", "website": "", "competitors_logo": "", "competitive_advantages": "渠道广泛", "differentiated_positioning": "价格更高", "comparison_dimensions": "", "source_section": "竞品"}],
                "authority_honors": [{"title": "高新技术企业", "description": "国家认定", "report_link": "", "year": "2024", "qualification_proof": "", "source_section": "荣誉"}],
                "customers_cases": [{"case_name": "门店升级", "cooperation_time": "", "customer_name": "客户A", "cooperation_product": "", "cooperation_highlight": "GMV提升", "customer_feedback": "帮助客户升级", "source_section": "案例"}],
                "sensitive_topics": [{"topic": "价格较高", "description": "部分用户认为偏贵", "forbidden_terms": "", "history_negative_clarification": "强调品质价值", "source_section": "FAQ"}],
            }

        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = fake_extract

        payload = await brand_knowledge_extraction.extract_brand_knowledge_for_task(service, task_id="task-1")

        self.assertEqual(payload["company_profile"]["brand_subject_name"], "示例品牌主体名称")
        self.assertEqual(payload["company_profile"]["company_address"], "上海市")
        self.assertEqual(payload["management_team"][0]["position"], "创始人兼CEO")
        self.assertEqual(len(payload["competitors"]), 1)
        self.assertEqual(payload["competitors"][0]["differentiated_positioning"], "价格更高")
        self.assertEqual(payload["customers_cases"][0]["cooperation_highlight"], "转化提升；GMV提升")
        self.assertEqual(payload["basic_info"]["official_wechat_account"], "md_wechat")
        self.assertEqual(len(payload["products"]), 1)
        self.assertEqual(payload["products"][0]["product_alias"], "爆款")
        self.assertEqual(payload["products"][0]["product_website"], "https://example.com/product")
        self.assertEqual(payload["sensitive_topics"][0]["topic"], "价格较高")
        self.assertEqual(len(payload["attachments"]), 2)
        self.assertEqual(len(service._brand_knowledge.last_knowledge_upserts), 11)
        attachment_products_upsert = next(
            item
            for item in service._brand_knowledge.last_knowledge_upserts
            if item[1] == "attachment_products"
        )
        self.assertEqual(
            [product["name"] for product in attachment_products_upsert[3]],
            ["明星产品", "无关产品"],
        )
        self.assertNotIn(
            "附件解析新增产品",
            [item["title"] for item in payload["other_info"]],
        )
        self.assertEqual(service._brands.last_upsert_brand_kwargs["official_wechat_account"], "md_wechat")
        self.assertEqual(service._brand_products.last_products_upsert["products"][0]["product_name"], "明星产品")

    async def test_extract_brand_knowledge_returns_empty_products_when_upload_request_has_no_products(self) -> None:
        class NoRequestedProductsUploadTaskStore(FakeUploadTaskStore):
            def get_upload_task(self, task_id: str):
                task = super().get_upload_task(task_id)
                if not task:
                    return None
                task = dict(task)
                metadata = dict(task["metadata_json"])
                task_payload = dict(metadata["_task_payload"])
                task_payload.pop("requested_products", None)
                metadata["_task_payload"] = task_payload
                task["metadata_json"] = metadata
                return task

        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _document_categories=FakeDocumentCategoryStore(),
            _document_registry=FakeDocumentRegistryStore(),
            _upload_tasks=NoRequestedProductsUploadTaskStore(),
            _settings=FakeSettings(),
            _tianyancha_client=types.SimpleNamespace(enabled=lambda: False),
            get_full_text=lambda document_id: f"# {document_id}\n正文",
            _get_document_info=lambda document_id: {"metadata_json": {"subcategory": None}},
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
                        "product_alias": "爆款",
                        "product_description": "这条不该进入结果",
                    }
                ],
                "company_profile": {},
                "management_team": [],
                "competitors": [],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": [],
            }

        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = fake_extract

        payload = await brand_knowledge_extraction.extract_brand_knowledge_for_task(service, task_id="task-1")

        self.assertEqual(payload["products"], [])
        self.assertIsNone(service._brand_products.last_products_upsert)
        attachment_products_upsert = next(
            item
            for item in service._brand_knowledge.last_knowledge_upserts
            if item[1] == "attachment_products"
        )
        self.assertEqual(
            attachment_products_upsert[3],
            [
                {
                    "name": "明星产品",
                    "product_alias": "爆款",
                    "product_description": "这条不该进入结果",
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
        self.assertNotIn(
            "附件解析新增产品",
            [item["title"] for item in payload["other_info"]],
        )

    async def test_extract_brand_knowledge_allows_new_competitors_when_upload_request_has_no_competitors(self) -> None:
        class NoRequestedCompetitorsUploadTaskStore(FakeUploadTaskStore):
            def get_upload_task(self, task_id: str):
                task = super().get_upload_task(task_id)
                if not task:
                    return None
                task = dict(task)
                metadata = dict(task["metadata_json"])
                task_payload = dict(metadata["_task_payload"])
                task_payload.pop("requested_competitors", None)
                metadata["_task_payload"] = task_payload
                task["metadata_json"] = metadata
                return task

        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _document_categories=FakeDocumentCategoryStore(),
            _document_registry=FakeDocumentRegistryStore(),
            _upload_tasks=NoRequestedCompetitorsUploadTaskStore(),
            _settings=FakeSettings(),
            _tianyancha_client=types.SimpleNamespace(enabled=lambda: False),
            get_full_text=lambda document_id: f"# {document_id}\n正文",
            _get_document_info=lambda document_id: {"metadata_json": {"subcategory": None}},
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
                "management_team": [],
                "competitors": [
                    {
                        "name": "竞品A",
                        "competitors_alias": "竞A",
                        "competitors_description": "新竞品介绍",
                        "website": "https://competitor-a.example.com",
                        "competitors_logo": "",
                        "competitive_advantages": "",
                        "differentiated_positioning": "",
                        "comparison_dimensions": "",
                        "source_section": "竞品",
                    }
                ],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": [],
            }

        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = fake_extract

        payload = await brand_knowledge_extraction.extract_brand_knowledge_for_task(service, task_id="task-1")

        self.assertEqual(len(payload["competitors"]), 1)
        self.assertEqual(payload["competitors"][0]["name"], "竞品A")
        self.assertEqual(payload["competitors"][0]["competitors_description"], "新竞品介绍")

    async def test_extract_brand_knowledge_summarizes_competitor_sections_from_attachment_markdown(self) -> None:
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _document_categories=FakeDocumentCategoryStore(),
            _document_registry=FakeDocumentRegistryStore(),
            _upload_tasks=FakeUploadTaskStore(),
            _settings=FakeSettings(),
            _tianyancha_client=types.SimpleNamespace(enabled=lambda: False),
            get_full_text=lambda document_id: """
**4.3 竞品多维对比**

| 对比维度 | 校园及第 |
| --- | --- |
| 面料体感 | 原纱冰感 |

**4.4 优劣势对比**

* **差异化\"护城河\"**:本土快反
""".strip(),
            _get_document_info=lambda document_id: {"metadata_json": {"subcategory": None}},
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
                "management_team": [],
                "competitors": [
                    {
                        "name": "竞品A",
                        "competitors_alias": "",
                        "competitors_description": "新竞品介绍",
                        "website": "",
                        "competitors_logo": "",
                        "competitive_advantages": "",
                        "differentiated_positioning": "",
                        "comparison_dimensions": "",
                        "source_section": "竞品",
                    }
                ],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": [],
                "other_info": [],
            }

        saved_call = brand_knowledge_extraction.call_text_llm_json

        def fake_call(prompt: str, *, settings):
            self.assertIn("4.3 竞品多维对比", prompt)
            self.assertIn("4.4 优劣势对比", prompt)
            return {
                "comparison_dimensions": ["面料体感", "价格定位"],
                "differentiated_positioning": ["原纱冰感体验更强", "本土补码更快"],
            }

        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = fake_extract
        brand_knowledge_extraction.call_text_llm_json = fake_call
        try:
            payload = await brand_knowledge_extraction.extract_brand_knowledge_for_task(service, task_id="task-1")
        finally:
            brand_knowledge_extraction.call_text_llm_json = saved_call

        self.assertEqual(payload["competitors"][0]["comparison_dimensions"], "面料体感；价格定位")
        self.assertEqual(payload["competitors"][0]["differentiated_positioning"], "原纱冰感体验更强；本土补码更快")
        self.assertNotIn("4.3 竞品多维对比", [item["title"] for item in payload["other_info"]])
        self.assertNotIn("4.4 优劣势对比", [item["title"] for item in payload["other_info"]])
