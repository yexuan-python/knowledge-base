from __future__ import annotations

import types
import unittest

from knowledge_base.brand import knowledge_extraction as brand_knowledge_extraction

from tests.fakes.brand_flow import (
    EmptyWebsiteAndEnglishBrandStore,
    FakeBrandKnowledgeStore,
    FakeBrandProductStore,
    FakeBrandStore,
    FakeDocumentCategoryStore,
    FakeDocumentRegistryStore,
    FakeSettings,
    FakeUploadTaskStore,
)


class BrandKnowledgeEnrichmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._original_extract = brand_knowledge_extraction.extract_brand_knowledge_from_markdown

    def tearDown(self) -> None:
        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = self._original_extract

    async def test_extract_brand_knowledge_enriches_missing_fields_from_tianyancha(self) -> None:
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _document_categories=FakeDocumentCategoryStore(),
            _document_registry=FakeDocumentRegistryStore(),
            _upload_tasks=FakeUploadTaskStore(),
            _settings=FakeSettings(tianyancha_enabled=True, tianyancha_api_key="test-key"),
            _tianyancha_client=types.SimpleNamespace(
                enabled=lambda: True,
                lookup_company_profile=lambda **kwargs: types.SimpleNamespace(
                    company_name="天眼企业主体",
                    english_name="Tyc Brand",
                    brand_logo="https://img.tyc.example.com/logo.png",
                    website="https://tyc.example.com/brand",
                    company_intro="天眼企业简介",
                    email="service@tyc.example.com",
                    customer_service_hotline="400-111-2222",
                    official_wechat_account="tyc_wechat",
                    registered_capital="1000万人民币",
                    established_time="2018-05-20",
                    company_address="杭州市余杭区",
                    unified_social_credit_code="91330100TEST",
                    legal_representative="李四",
                    registration_status="存续",
                    registration_authority="杭州市市场监督管理局",
                    company_type="有限责任公司",
                    industry="软件和信息技术服务业",
                    industry_classification="软件开发",
                    insured_count="88",
                    personnel_scale="50-99人",
                    company_tags="高新技术企业;科技型中小企业",
                    approval_date="2024-03-01",
                    business_term_start="2018-05-20",
                    business_term_end="长期",
                ),
                lookup_company_management=lambda **kwargs: [],
            ),
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
                "competitors": [],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": [],
            }

        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = fake_extract

        payload = await brand_knowledge_extraction.extract_brand_knowledge_for_task(service, task_id="task-1")

        self.assertEqual(payload["basic_info"]["website"], ["https://example.com"])
        self.assertEqual(payload["basic_info"]["official_wechat_account"], "example_wechat")
        self.assertEqual(payload["basic_info"]["brand_logo"], "https://img.tyc.example.com/logo.png")
        self.assertEqual(payload["company_profile"]["registered_capital"], "1000万人民币")
        self.assertEqual(payload["company_profile"]["established_time"], "2018-05-20")
        self.assertEqual(payload["company_profile"]["company_address"], "杭州市余杭区")
        self.assertEqual(payload["company_profile"]["company_intro"], "天眼企业简介")
        self.assertFalse(payload["basic_info"].get("other_info"))
        self.assertIn("统一社会信用代码：91330100TEST", payload["company_profile"]["other_info"])
        self.assertIn("法定代表人：李四", payload["company_profile"]["other_info"])
        self.assertIn("行业：软件和信息技术服务业", payload["company_profile"]["other_info"])
        self.assertIn("登记状态：存续", payload["company_profile"]["other_info"])
        self.assertEqual(service._brands.last_upsert_brand_kwargs["brand_enterprise_entity"], "天眼企业主体")
        self.assertEqual(service._brands.last_upsert_brand_kwargs["brand_logo"], "https://img.tyc.example.com/logo.png")
        self.assertEqual(service._brands.last_upsert_brand_kwargs["intro"], "品牌简介")
        self.assertNotIn(
            "统一社会信用代码：91330100TEST",
            service._brands.last_upsert_brand_kwargs.get("other_info") or "",
        )
        self.assertNotIn(
            "法定代表人：李四",
            service._brands.last_upsert_brand_kwargs.get("other_info") or "",
        )

    async def test_extract_brand_knowledge_ignores_tianyancha_failure(self) -> None:
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _document_categories=FakeDocumentCategoryStore(),
            _document_registry=FakeDocumentRegistryStore(),
            _upload_tasks=FakeUploadTaskStore(),
            _settings=FakeSettings(tianyancha_enabled=True, tianyancha_api_key="test-key"),
            _tianyancha_client=types.SimpleNamespace(
                enabled=lambda: True,
                lookup_company_profile=lambda **kwargs: None,
                lookup_company_management=lambda **kwargs: [],
            ),
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
                "basic_info": {"website": ["https://md.example.com"]},
                "products": [],
                "company_profile": {"brand_subject_name": "Markdown主体"},
                "management_team": [],
                "competitors": [],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": [],
            }

        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = fake_extract

        payload = await brand_knowledge_extraction.extract_brand_knowledge_for_task(service, task_id="task-1")

        self.assertEqual(payload["company_profile"]["brand_subject_name"], "Markdown主体")
        self.assertEqual(
            service._brands.last_upsert_brand_kwargs["website"],
            "[\"https://example.com\", \"https://md.example.com\"]",
        )

    async def test_extract_brand_knowledge_keeps_ai_values_when_tianyancha_also_has_values(self) -> None:
        service = types.SimpleNamespace(
            _brands=EmptyWebsiteAndEnglishBrandStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _document_categories=FakeDocumentCategoryStore(),
            _document_registry=FakeDocumentRegistryStore(),
            _upload_tasks=FakeUploadTaskStore(),
            _settings=FakeSettings(tianyancha_enabled=True, tianyancha_api_key="test-key"),
            _tianyancha_client=types.SimpleNamespace(
                enabled=lambda: True,
                lookup_company_profile=lambda **kwargs: types.SimpleNamespace(
                    company_name="天眼企业主体",
                    english_name="Tyc Brand",
                    brand_logo="https://img.tyc.example.com/logo.png",
                    website="https://tyc.example.com/brand",
                    company_intro="天眼企业简介",
                    email="service@tyc.example.com",
                    customer_service_hotline="400-111-2222",
                    official_wechat_account="tyc_wechat",
                    registered_capital="1000万人民币",
                    established_time="2018-05-20",
                    company_address="杭州市余杭区",
                    unified_social_credit_code="91330100TEST",
                    legal_representative="李四",
                    registration_status="存续",
                    registration_authority="杭州市市场监督管理局",
                    company_type="有限责任公司",
                    industry="软件和信息技术服务业",
                    industry_classification="软件开发",
                    insured_count="88",
                    personnel_scale="50-99人",
                    company_tags="高新技术企业;科技型中小企业",
                    approval_date="2024-03-01",
                    business_term_start="2018-05-20",
                    business_term_end="长期",
                ),
                lookup_company_management=lambda **kwargs: [],
            ),
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
                "basic_info": {
                    "website": ["https://ai.example.com"],
                    "english_name": "AI Brand",
                },
                "products": [],
                "company_profile": {
                    "brand_subject_name": "AI主体",
                    "registered_capital": "888万人民币",
                    "company_address": "上海市徐汇区",
                    "company_intro": "AI提取的企业简介",
                    "established_time": "2020-01-01",
                    "other_info": "AI侧其他信息",
                },
                "management_team": [],
                "competitors": [],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": [],
            }

        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = fake_extract

        payload = await brand_knowledge_extraction.extract_brand_knowledge_for_task(service, task_id="task-1")

        self.assertEqual(payload["basic_info"]["website"], ["https://ai.example.com"])
        self.assertEqual(payload["basic_info"]["english_name"], "AI Brand")
        self.assertEqual(payload["company_profile"]["brand_subject_name"], "AI主体")
        self.assertEqual(payload["company_profile"]["registered_capital"], "888万人民币")
        self.assertEqual(payload["company_profile"]["company_address"], "上海市徐汇区")
        self.assertEqual(payload["company_profile"]["company_intro"], "AI提取的企业简介")
        self.assertEqual(payload["company_profile"]["established_time"], "2020-01-01")
        self.assertIn("AI侧其他信息", payload["company_profile"]["other_info"])
        self.assertIn("统一社会信用代码：91330100TEST", payload["company_profile"]["other_info"])
        self.assertIn("行业分类：软件开发", payload["company_profile"]["other_info"])
        self.assertRegex(
            service._brands.last_upsert_brand_kwargs["knowledge_revision"],
            r"^LXKG-SLPP-V1\.0\.0-\d{14}$",
        )

    async def test_extract_brand_knowledge_enriches_management_and_competitors_from_tianyancha(self) -> None:
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _document_categories=FakeDocumentCategoryStore(),
            _document_registry=FakeDocumentRegistryStore(),
            _upload_tasks=FakeUploadTaskStore(),
            _settings=FakeSettings(tianyancha_enabled=True, tianyancha_api_key="test-key"),
            _tianyancha_client=types.SimpleNamespace(
                enabled=lambda: True,
                lookup_company_profile=lambda **kwargs: (
                    types.SimpleNamespace(
                        company_name="竞品A科技有限公司",
                        english_name="",
                        brand_logo="https://img.example.com/competitor-a.png",
                        website="https://competitor-a.example.com",
                        company_intro="竞品A企业介绍",
                        email="info@competitor-a.example.com",
                        customer_service_hotline="400-123-4567",
                        official_wechat_account="",
                        registered_capital="5000万人民币",
                        established_time="2016-06-18",
                        company_address="北京市朝阳区",
                        unified_social_credit_code="",
                        legal_representative="王五",
                        registration_status="存续",
                        registration_authority="北京市市场监督管理局",
                        company_type="有限责任公司",
                        industry="软件和信息技术服务业",
                        industry_classification="软件开发",
                        insured_count="66",
                        personnel_scale="100-499人",
                        company_tags="专精特新",
                        approval_date="2025-01-01",
                        business_term_start="2016-06-18",
                        business_term_end="长期",
                    )
                    if kwargs.get("company_name") == "竞品A"
                    else types.SimpleNamespace(
                        company_name="示例企业主体",
                        english_name="",
                        brand_logo="",
                        website="",
                        company_intro="",
                        email="",
                        customer_service_hotline="",
                        official_wechat_account="",
                        registered_capital="",
                        established_time="",
                        company_address="",
                        unified_social_credit_code="",
                        legal_representative="",
                        registration_status="",
                        registration_authority="",
                        company_type="",
                        industry="",
                        industry_classification="",
                        insured_count="",
                        personnel_scale="",
                        company_tags="",
                        approval_date="",
                        business_term_start="",
                        business_term_end="",
                    )
                ),
                lookup_company_management=lambda **kwargs: [
                    types.SimpleNamespace(
                        name="张三",
                        title="创始人兼CEO",
                        profile="负责公司整体战略与经营管理",
                        other_info="法定代表人",
                    )
                ],
            ),
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
                "management_team": [{"member_name": "张三", "position": "", "profile": "", "introduction_website": "", "source_section": "团队"}],
                "competitors": [{"name": "竞品A", "competitors_alias": "", "competitors_description": "", "website": "", "competitors_logo": "", "competitive_advantages": "", "differentiated_positioning": "", "comparison_dimensions": "", "source_section": "竞品"}],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": [],
            }

        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = fake_extract

        payload = await brand_knowledge_extraction.extract_brand_knowledge_for_task(service, task_id="task-1")

        self.assertEqual(payload["management_team"][0]["position"], "创始人兼CEO")
        self.assertEqual(payload["management_team"][0]["profile"], "负责公司整体战略与经营管理")
        self.assertEqual(payload["management_team"][0]["other_info"], "法定代表人")
        self.assertEqual(payload["competitors"][0]["website"], "https://competitor-a.example.com")
        self.assertEqual(payload["competitors"][0]["competitors_logo"], "https://img.example.com/competitor-a.png")
        self.assertEqual(payload["competitors"][0]["competitors_description"], "竞品A企业介绍")
        self.assertIn("企业名称：竞品A科技有限公司", payload["competitors"][0]["other_info"])

    async def test_extract_brand_knowledge_tianyancha_adds_management_members_when_initially_empty(self) -> None:
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _document_categories=FakeDocumentCategoryStore(),
            _document_registry=FakeDocumentRegistryStore(),
            _upload_tasks=FakeUploadTaskStore(),
            _settings=FakeSettings(tianyancha_enabled=True, tianyancha_api_key="test-key"),
            _tianyancha_client=types.SimpleNamespace(
                enabled=lambda: True,
                lookup_company_profile=lambda **kwargs: None,
                lookup_company_management=lambda **kwargs: [
                    types.SimpleNamespace(
                        name="张三",
                        title="创始人兼CEO",
                        profile="负责公司整体战略与经营管理",
                        other_info="法定代表人",
                    ),
                    types.SimpleNamespace(
                        name="李四",
                        title="联合创始人",
                        profile="负责供应链与交付",
                        other_info="核心管理层",
                    ),
                ],
            ),
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
                "competitors": [],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": [],
            }

        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = fake_extract

        payload = await brand_knowledge_extraction.extract_brand_knowledge_for_task(service, task_id="task-1")

        self.assertEqual(len(payload["management_team"]), 2)
        self.assertEqual(payload["management_team"][0]["member_name"], "张三")
        self.assertEqual(payload["management_team"][0]["position"], "创始人兼CEO")
        self.assertEqual(payload["management_team"][0]["profile"], "负责公司整体战略与经营管理")
        self.assertEqual(payload["management_team"][0]["other_info"], "法定代表人")
        self.assertEqual(payload["management_team"][1]["member_name"], "李四")
        self.assertEqual(payload["management_team"][1]["position"], "联合创始人")

    async def test_extract_brand_knowledge_web_fallback_only_fills_remaining_empty_fields(self) -> None:
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _document_categories=FakeDocumentCategoryStore(),
            _document_registry=FakeDocumentRegistryStore(),
            _upload_tasks=FakeUploadTaskStore(),
            _settings=FakeSettings(tianyancha_enabled=True, tianyancha_api_key="test-key"),
            _tianyancha_client=types.SimpleNamespace(
                enabled=lambda: True,
                lookup_company_profile=lambda **kwargs: None,
                lookup_company_management=lambda **kwargs: [],
            ),
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
                "management_team": [{"member_name": "张三", "position": "", "profile": "AI已有简介", "introduction_website": "", "source_section": "团队"}],
                "competitors": [{"name": "竞品A", "competitors_alias": "", "competitors_description": "", "website": "", "competitors_logo": "", "competitive_advantages": "", "differentiated_positioning": "", "comparison_dimensions": "", "source_section": "竞品"}],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": [],
            }

        async def fake_web_enrichment(**kwargs):
            return {
                "management_team": [
                    {
                        "member_name": "张三",
                        "position": "联合创始人",
                        "profile": "官网人物简介",
                        "introduction_website": "https://example.com/team/zhangsan",
                        "other_info": "官网团队页",
                    }
                ],
                "competitors": [
                    {
                        "name": "竞品A",
                        "competitors_alias": "竞品A别名",
                        "competitors_description": "官网竞品介绍",
                        "website": "https://competitor-a.example.com",
                        "competitors_logo": "https://competitor-a.example.com/logo.png",
                        "competitive_advantages": "直营网点覆盖广",
                        "differentiated_positioning": "聚焦高端市场",
                        "comparison_dimensions": "价格、服务、覆盖城市",
                        "other_info": "官网与公示信息整理",
                    }
                ],
            }

        enrichment_module = __import__("knowledge_base.brand.enrichment", fromlist=["enrich_brand_fields_from_web"])
        saved_web_func = enrichment_module.enrich_brand_fields_from_web
        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = fake_extract
        enrichment_module.enrich_brand_fields_from_web = fake_web_enrichment
        try:
            payload = await brand_knowledge_extraction.extract_brand_knowledge_for_task(service, task_id="task-1")
        finally:
            enrichment_module.enrich_brand_fields_from_web = saved_web_func

        self.assertEqual(payload["management_team"][0]["position"], "联合创始人")
        self.assertEqual(payload["management_team"][0]["profile"], "AI已有简介")
        self.assertEqual(payload["management_team"][0]["introduction_website"], "https://example.com/team/zhangsan")
        self.assertEqual(payload["competitors"][0]["competitors_alias"], "竞品A别名")
        self.assertEqual(payload["competitors"][0]["website"], "https://competitor-a.example.com")
        self.assertEqual(payload["competitors"][0]["competitive_advantages"], "直营网点覆盖广")
        self.assertEqual(payload["competitors"][0]["comparison_dimensions"], "价格、服务、覆盖城市")
