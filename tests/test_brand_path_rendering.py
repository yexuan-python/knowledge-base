from __future__ import annotations

import types
import unittest
from unittest.mock import AsyncMock

from knowledge_base.brand.application import BrandApplicationDependencies, BrandApplicationService

from tests.fakes.brand_flow import (
    EmptyBrandProductStore,
    FakeBrandFullKnowledgeStore,
    FakeBrandKnowledgeStore,
    FakeBrandProductStore,
    FakeBrandStore,
    FakeDocumentCategoryStore,
    FakeDocumentRegistryStore,
    FakeIndustryStore,
    FakeSettings,
    _build_brand_application,
)


class BrandPathRenderingTests(unittest.TestCase):
    def test_load_brand_paths_renders_sensitive_topics_object(self) -> None:
        brand_knowledge = FakeBrandKnowledgeStore()
        brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "sensitive_topics",
                "content_json": {
                    "sensitive_contents": ["价格争议"],
                    "controversial_events": ["社媒舆情"],
                    "forbidden_words": ["保本"],
                    "negative_clarifications": ["统一回应口径"],
                    "other_info": ["客服注意转述方式"],
                },
            }
        ]
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                brand_knowledge=brand_knowledge,
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

        result = application.load_brand_paths(
            brand_code="BRAND-001",
            paths=["品牌基础信息/敏感话题"],
        )

        self.assertIsNotNone(result)
        self.assertEqual(len(result["assets"]), 1)
        content = result["assets"][0]["content"]
        self.assertIn("敏感内容", content)
        self.assertIn("价格争议", content)
        self.assertIn("负面澄清口径", content)

    def test_load_brand_paths_renders_assets_and_missing_paths(self) -> None:
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
                        "name": "附件新品",
                        "product_description": "附件解析出来的新产品",
                        "product_website": "https://example.com/attachment-product",
                    },
                ],
            },
        ]

        result = application.load_brand_paths(
            brand_code="BRAND-001",
            paths=[
                "品牌基础信息/品牌介绍",
                "品牌基础信息/公司档案",
                "产品信息/明星产品",
                "产品信息/附件新品",
                "竞品信息/竞品A",
                "品牌基础信息/官方商城",
                "品牌基础信息/官方媒体与矩阵",
                "不存在/路径",
            ],
            knowledge_revision="demo-2026-06-23",
        )

        self.assertIsNotNone(result)
        self.assertEqual(len(result["assets"]), 7)
        self.assertEqual(result["assets"][0]["knowledge_revision"], "demo-2026-06-23")
        overview = next(item for item in result["assets"] if item["path"] == "品牌基础信息/品牌介绍")
        self.assertIn("# 品牌介绍", overview["content"])
        company_profile = next(item for item in result["assets"] if item["path"] == "品牌基础信息/公司档案")
        self.assertIn("# 公司档案", company_profile["content"])
        self.assertIn("示例企业简介", company_profile["content"])
        product = next(item for item in result["assets"] if item["path"] == "产品信息/明星产品")
        self.assertIn("## 产品介绍", product["content"])
        attachment_product = next(item for item in result["assets"] if item["path"] == "产品信息/附件新品")
        self.assertIn("附件解析出来的新产品", attachment_product["content"])
        self.assertIn("https://example.com/attachment-product", attachment_product["content"])
        competitor = next(item for item in result["assets"] if item["path"] == "竞品信息/竞品A")
        self.assertIn("# 竞品A", competitor["content"])
        official_malls = next(item for item in result["assets"] if item["path"] == "品牌基础信息/官方商城")
        self.assertIn("# 官方商城", official_malls["content"])
        official_media = next(item for item in result["assets"] if item["path"] == "品牌基础信息/官方媒体与矩阵")
        self.assertIn("# 官方媒体与矩阵", official_media["content"])
        self.assertEqual(result["missing_paths"], [{"path": "不存在/路径", "reason": "not_found"}])

    def test_load_brand_paths_prefers_full_markdown_when_available(self) -> None:
        brand_full_knowledge = FakeBrandFullKnowledgeStore()
        brand_full_knowledge.rows = [
            {
                "id": 11,
                "brand_id": 1,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "version_no": 8,
                "file_name": "【示例品牌】品牌AI知识库_V8_20260808.md",
                "content_markdown": "\n".join(
                    [
                        "# 示例品牌 当前结构化知识基线",
                        "",
                        "## 基础信息",
                        "",
                        "- **品牌编码**：BRAND-001",
                        "- **品牌简介**：正式知识库里的品牌介绍。",
                        "",
                        "## 产品信息",
                        "",
                        "### 花悦系列",
                        "",
                        "- **产品别名**：花悦系列别名",
                        "- **产品介绍**：正式知识库里的花悦系列介绍。",
                        "- **产品官网**：[https://product.example.com](https://product.example.com)",
                        "",
                        "## 竞品信息",
                        "",
                        "- **name**：欧派家居；**competitors_description**：正式知识库里的欧派家居介绍。",
                        "- **name**：索菲亚；**competitors_description**：正式知识库里的索菲亚介绍。",
                        "",
                        "## 官方商城",
                        "",
                        "- **store_name**：金牌厨柜全屋定制官方旗舰店；**platform**：京东；**other_info**：正式知识库里的官方商城说明。",
                    ]
                ),
            }
        ]
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=FakeBrandStore(),
                brand_products=EmptyBrandProductStore(),
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
            )
        )

        result = application.load_brand_paths(
            brand_code="BRAND-001",
            paths=[
                "品牌基础信息/品牌介绍",
                "产品信息/花悦系列",
                "竞品信息/欧派家居",
                "品牌基础信息/官方商城",
            ],
            knowledge_revision="demo-2026-06-23",
        )

        self.assertIsNotNone(result)
        assert result is not None
        overview = next(item for item in result["assets"] if item["path"] == "品牌基础信息/品牌介绍")
        self.assertIn("# 示例品牌 当前结构化知识基线", overview["content"])
        self.assertIn("正式知识库里的品牌介绍", overview["content"])
        product = next(item for item in result["assets"] if item["path"] == "产品信息/花悦系列")
        self.assertIn("### 花悦系列", product["content"])
        self.assertIn("正式知识库里的花悦系列介绍", product["content"])
        competitor = next(item for item in result["assets"] if item["path"] == "竞品信息/欧派家居")
        self.assertIn("## 竞品信息", competitor["content"])
        self.assertIn("正式知识库里的欧派家居介绍", competitor["content"])
        official_mall = next(item for item in result["assets"] if item["path"] == "品牌基础信息/官方商城")
        self.assertIn("正式知识库里的官方商城说明", official_mall["content"])

    def test_load_brand_paths_extracts_product_bullet_block_from_full_markdown(self) -> None:
        brand_full_knowledge = FakeBrandFullKnowledgeStore()
        brand_full_knowledge.rows = [
            {
                "id": 12,
                "brand_id": 1,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "version_no": 9,
                "file_name": "【示例品牌】品牌AI知识库_V9_20260808.md",
                "content_markdown": "\n".join(
                    [
                        "# 示例品牌 当前结构化知识基线",
                        "",
                        "## **三、 产品矩阵与核心系列**",
                        "",
                        "### **3.1 按系列划分的产品线 (来自客户填写的表格)**",
                        "",
                        "- **花悦系列**",
                        "",
                        "- **价格区间**: 799-1099元（*具体请咨询当地门店）",
                        "",
                        "- **定位**: 橱柜、衣柜、木门等全屋定制",
                        "",
                        "- **目标人群**: 新房装修客户、老房改造装修客户、二手房装修客户",
                        "",
                        "- **户型/风格**: 现代简约/新中式/中古风/现代轻奢",
                        "",
                        "- **核心卖点**: ENF环保进阶、抗变形、耐磨耐刮、环保健康、耐水防潮、花色丰富",
                        "",
                        "- **峰睿系列**",
                        "",
                        "- **价格**: 1499-1899元",
                    ]
                ),
            }
        ]
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=FakeBrandStore(),
                brand_products=EmptyBrandProductStore(),
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
            )
        )

        result = application.load_brand_paths(
            brand_code="BRAND-001",
            paths=["产品信息/花悦系列"],
            knowledge_revision="demo-2026-06-23",
        )

        self.assertIsNotNone(result)
        assert result is not None
        product = result["assets"][0]
        self.assertEqual(product["title"], "花悦系列")
        self.assertIn("# 花悦系列", product["content"])
        self.assertIn("- **价格区间**: 799-1099元", product["content"])
        self.assertIn("- **目标人群**: 新房装修客户、老房改造装修客户、二手房装修客户", product["content"])
        self.assertIn("- **核心卖点**: ENF环保进阶", product["content"])
        self.assertNotIn("## 基本信息", product["content"])
        self.assertNotIn("- **峰睿系列**", product["content"])

    def test_load_brand_paths_renders_richer_overview_content(self) -> None:
        brand_knowledge = FakeBrandKnowledgeStore()
        brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "company_profile",
                "content_json": {
                    "brand_subject_name": "示例品牌主体名称",
                    "company_intro": "一家专注消费品的品牌公司。",
                    "registered_capital": "5000万人民币",
                    "established_time": "2016-06-18",
                    "company_address": "北京市朝阳区",
                    "stock_info": "未上市",
                },
            },
            {
                "knowledge_type": "competitors",
                "content_json": [
                    {
                        "name": "竞品A",
                        "competitors_description": "竞品A主打直营网点覆盖。",
                    }
                ],
            },
        ]
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                brand_knowledge=brand_knowledge,
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

        result = application.load_brand_paths(
            brand_code="BRAND-001",
            paths=["品牌基础信息/品牌介绍"],
            knowledge_revision="demo-2026-06-23",
        )

        self.assertIsNotNone(result)
        content = result["assets"][0]["content"]
        self.assertIn("## 基本信息", content)
        self.assertIn("知识版本：demo-2026-06-23", content)
        self.assertIn("## 公司档案", content)
        self.assertIn("成立时间：2016-06-18", content)
        self.assertIn("注册资本：5000万人民币", content)
        self.assertIn("## 重点产品", content)
        self.assertIn("path：产品信息/明星产品", content)
        self.assertIn("## 主要竞品", content)
        self.assertIn("path：竞品信息/竞品A", content)

    def test_load_brand_paths_renders_richer_product_and_competitor_content(self) -> None:
        brand_knowledge = FakeBrandKnowledgeStore()
        brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "competitors",
                "content_json": [
                    {
                        "name": "竞品A",
                        "competitors_alias": "竞A",
                        "competitors_description": "竞品A提供同类解决方案。",
                        "website": "https://competitor-a.example.com",
                        "competitors_logo": "https://img.example.com/competitor-a.png",
                        "competitive_advantages": "直营网点覆盖广",
                        "differentiated_positioning": "偏高端市场",
                        "comparison_dimensions": "价格、服务、覆盖城市",
                        "other_info": "企业名称：竞品A科技有限公司",
                    }
                ],
            }
        ]
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                brand_knowledge=brand_knowledge,
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

        result = application.load_brand_paths(
            brand_code="BRAND-001",
            paths=["产品信息/明星产品", "竞品信息/竞品A"],
            knowledge_revision="demo-2026-06-23",
        )

        self.assertIsNotNone(result)
        product_content = next(item for item in result["assets"] if item["path"] == "产品信息/明星产品")["content"]
        self.assertIn("## 基本信息", product_content)
        self.assertIn("## 产品官网", product_content)
        self.assertIn("## 产品图片", product_content)
        self.assertIn("[https://example.com/product-1.png](https://example.com/product-1.png)", product_content)

        competitor_content = next(item for item in result["assets"] if item["path"] == "竞品信息/竞品A")["content"]
        self.assertIn("## 基本信息", competitor_content)
        self.assertIn("## 品牌标识", competitor_content)
        self.assertIn("## 建议对比维度", competitor_content)
        self.assertIn("价格、服务、覆盖城市", competitor_content)

    def test_load_brand_paths_hides_stringified_empty_product_sections(self) -> None:
        class PlaceholderBrandProductStore(FakeBrandProductStore):
            def get_brand_products(self, *, brand_id: int):
                return [
                    {
                        "product_name": "陈素文",
                        "product_description": "首都医科大学附属北京妇产医院 计划生育科",
                        "product_advantages": "[]",
                        "target_scenarios": "[]",
                        "service_standard": "[]",
                        "service_process": "[]",
                        "cases_and_reputation": "[]",
                        "certification_info": "[]",
                        "core_technology": "[]",
                        "other_info": "[]",
                    }
                ]

        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=FakeBrandStore(),
                brand_products=PlaceholderBrandProductStore(),
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

        result = application.load_brand_paths(
            brand_code="BRAND-001",
            paths=["产品信息/陈素文"],
            knowledge_revision="demo-2026-06-23",
        )

        self.assertIsNotNone(result)
        assert result is not None
        content = result["assets"][0]["content"]
        self.assertIn("# 陈素文", content)
        self.assertIn("## 产品介绍", content)
        self.assertNotIn("## 产品优势", content)
        self.assertNotIn("## 适用场景", content)
        self.assertNotIn("## 服务标准", content)
        self.assertNotIn("## 服务流程", content)
        self.assertNotIn("## 案例与口碑", content)
        self.assertNotIn("## 认证信息", content)
        self.assertNotIn("## 核心技术", content)
        self.assertNotIn("## 其他信息", content)

    def test_load_brand_paths_renders_richer_team_honors_cases_and_attachments(self) -> None:
        brand_knowledge = FakeBrandKnowledgeStore()
        brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "management_team",
                "content_json": [
                    {
                        "member_name": "张三",
                        "position": "创始人兼CEO",
                        "profile": "负责公司整体战略与经营管理",
                        "introduction_website": "https://example.com/team/zhangsan",
                        "other_info": "法定代表人",
                        "source_section": "团队",
                    }
                ],
            },
            {
                "knowledge_type": "authority_honors",
                "content_json": [
                    {
                        "title": "高新技术企业",
                        "description": "国家认定",
                        "year": "2024",
                        "report_link": "https://example.com/honor-report",
                        "qualification_proof": "https://example.com/honor-proof.pdf",
                        "source_section": "荣誉",
                    }
                ],
            },
            {
                "knowledge_type": "customers_cases",
                "content_json": [
                    {
                        "case_name": "门店升级",
                        "customer_name": "客户A",
                        "cooperation_time": "2025",
                        "cooperation_product": "明星产品",
                        "cooperation_highlight": "转化提升",
                        "customer_feedback": "帮助客户升级门店",
                        "source_section": "案例",
                    }
                ],
            },
            {
                "knowledge_type": "attachments",
                "content_json": [
                    {
                        "name": "品牌手册.pdf",
                        "url": "https://example.com/brand-book.pdf",
                        "description": "品牌对外介绍手册",
                        "type": "pdf",
                    }
                ],
            },
        ]
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                brand_knowledge=brand_knowledge,
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

        result = application.load_brand_paths(
            brand_code="BRAND-001",
            paths=[
                "品牌基础信息/管理团队",
                "品牌基础信息/权威荣誉",
                "品牌基础信息/客户案例",
                "品牌基础信息/附件资料",
            ],
            knowledge_revision="demo-2026-06-23",
        )

        self.assertIsNotNone(result)
        team_content = next(item for item in result["assets"] if item["path"] == "品牌基础信息/管理团队")["content"]
        self.assertIn("资料链接：https://example.com/team/zhangsan", team_content)
        self.assertIn("其他信息：法定代表人", team_content)
        self.assertIn("来源：团队", team_content)

        honors_content = next(item for item in result["assets"] if item["path"] == "品牌基础信息/权威荣誉")["content"]
        self.assertIn("报告链接：https://example.com/honor-report", honors_content)
        self.assertIn("证明材料：https://example.com/honor-proof.pdf", honors_content)
        self.assertIn("来源：荣誉", honors_content)

        cases_content = next(item for item in result["assets"] if item["path"] == "品牌基础信息/客户案例")["content"]
        self.assertIn("合作时间：2025", cases_content)
        self.assertIn("合作产品：明星产品", cases_content)
        self.assertIn("客户反馈：帮助客户升级门店", cases_content)

        attachments_content = next(item for item in result["assets"] if item["path"] == "品牌基础信息/附件资料")["content"]
        self.assertIn("类型：pdf", attachments_content)
        self.assertIn("说明：品牌对外介绍手册", attachments_content)
        self.assertIn("[https://example.com/brand-book.pdf](https://example.com/brand-book.pdf)", attachments_content)

    def test_load_brand_paths_rejects_mismatched_revision(self) -> None:
        application = _build_brand_application()

        with self.assertRaises(RuntimeError):
            application.load_brand_paths(
                brand_code="BRAND-001",
                paths=["品牌基础信息/品牌介绍"],
                knowledge_revision="old-revision",
            )
