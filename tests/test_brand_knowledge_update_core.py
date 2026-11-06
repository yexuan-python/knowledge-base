from __future__ import annotations

import types
import unittest
from unittest.mock import AsyncMock, patch

from knowledge_base.brand.application import BrandApplicationDependencies, BrandApplicationService
from knowledge_base.brand.schemas import KnowledgeBasicInfo, KnowledgeProduct, KnowledgeUpdateRequest

from tests.fakes.brand_flow import (
    EmptyBrandProductStore,
    FakeBrandKnowledgeStore,
    FakeBrandProductStore,
    FakeBrandStore,
    FakeDocumentCategoryStore,
    FakeIndustryStore,
    FakeSettings,
)
from tests.fakes.attachment_assets import (
    FakeAttachmentOSSClient,
    FakeAttachmentParser,
    FakeBrandAttachmentAssetStore,
    fake_temp_file_download,
)


def _build_application(**dependency_overrides) -> BrandApplicationService:
    dependencies = {
        "settings": FakeSettings(),
        "brands": FakeBrandStore(),
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


class BrandKnowledgeUpdateCoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_knowledge_update_writes_brand_products_and_json_sections(self) -> None:
        application = _build_application()

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
                brand_enterprise_entity="示例企业主体",
            ),
            products=[
                KnowledgeProduct(
                    product_code="PROD-A",
                    name="产品A",
                    product_website="https://example.com/a",
                    price_info="99元",
                )
            ],
            company_profile={
                "brand_subject_name": "示例品牌主体名称",
                "business_license_url": "https://example.com/license.png",
            },
            management_team=[{"member_name": "张三"}],
            official_media_matrix=[
                {
                    "platform": "微信",
                    "account_name": "示例品牌服务号",
                    "account_id": "demo_service",
                    "url": "https://example.com/wechat",
                    "description": "官方服务号",
                    "related_products": ["产品A"],
                    "other_info": ["新品发布"],
                }
            ],
            official_malls=[
                {
                    "platform": "天猫",
                    "store_name": "示例品牌旗舰店",
                    "url": "https://example.com/tmall",
                    "description": "官方旗舰店",
                    "related_products": ["产品A"],
                    "other_info": ["支持售后咨询"],
                }
            ],
            other_info=[
                {
                    "title": "补充说明",
                    "content": "品牌知识库其他信息",
                }
            ],
        )

        result = await application.update_knowledge(request)

        self.assertEqual(result["brand_id"], 1)
        self.assertEqual(result["brand_name"], "示例品牌")
        self.assertEqual(application._deps.brands.last_upsert_brand_kwargs["brand_enterprise_entity"], "示例企业主体")
        self.assertEqual(
            application._deps.brands.last_upsert_brand_kwargs["business_license_image_path"],
            "https://example.com/license.png",
        )
        self.assertRegex(
            application._deps.brands.last_upsert_brand_kwargs["knowledge_revision"],
            r"^LXKG-SLPP-V1\.0\.0-\d{14}$",
        )
        self.assertRegex(result["knowledge_revision"], r"^LXKG-SLPP-V1\.0\.0-\d{14}$")
        self.assertEqual(application._deps.brand_products.last_products_upsert["brand_id"], 1)
        self.assertEqual(application._deps.brand_products.last_products_upsert["products"][0]["product_name"], "产品A")
        knowledge_types = [item[1] for item in application._deps.brand_knowledge.last_knowledge_upserts]
        self.assertIn("company_profile", knowledge_types)
        self.assertIn("management_team", knowledge_types)
        self.assertIn("official_media_matrix", knowledge_types)
        self.assertIn("official_malls", knowledge_types)
        company_profile_upsert = next(
            item for item in application._deps.brand_knowledge.last_knowledge_upserts
            if item[1] == "company_profile"
        )
        self.assertEqual(
            company_profile_upsert[3]["business_license_image_path"],
            "https://example.com/license.png",
        )
        self.assertNotIn("business_license_url", company_profile_upsert[3])
        official_media_upsert = next(
            item for item in application._deps.brand_knowledge.last_knowledge_upserts
            if item[1] == "official_media_matrix"
        )
        self.assertEqual(official_media_upsert[3][0]["account_name"], "示例品牌服务号")
        official_malls_upsert = next(
            item for item in application._deps.brand_knowledge.last_knowledge_upserts
            if item[1] == "official_malls"
        )
        self.assertEqual(official_malls_upsert[3][0]["store_name"], "示例品牌旗舰店")
        other_info_upsert = next(
            item for item in application._deps.brand_knowledge.last_knowledge_upserts
            if item[1] == "other_info"
        )
        self.assertEqual(
            other_info_upsert[3],
            [
                {
                    "title": "补充说明",
                    "content": "品牌知识库其他信息",
                }
            ],
        )

        clear_request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
            ),
            official_media_matrix=[],
            official_malls=[],
            other_info=[],
        )

        clear_result = await application.update_knowledge(clear_request)

        self.assertEqual(clear_result["status"], "success")
        self.assertEqual(
            application._deps.brand_knowledge.deleted_knowledge_types[-3:],
            [
                (1, "official_media_matrix"),
                (1, "official_malls"),
                (1, "other_info"),
            ],
        )

    async def test_knowledge_update_updated_sections_excludes_unchanged_brand(self) -> None:
        application = _build_application(
            brand_products=EmptyBrandProductStore(),
        )

        result = await application.update_knowledge(
            KnowledgeUpdateRequest(
                basic_info=KnowledgeBasicInfo(
                    brand_name="示例品牌",
                    brand_code="BRAND-001",
                ),
                products=[
                    KnowledgeProduct(
                        product_code="PROD-001",
                        name="产品A",
                    )
                ],
            )
        )

        self.assertEqual(result["updated_sections"], ["products"])

    async def test_knowledge_update_writes_website_list_as_json_string(self) -> None:
        application = _build_application()

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
                website=["https://www.lixiang.com", "https://www.lixiang.com/about"],
            ),
        )

        result = await application.update_knowledge(request)

        self.assertEqual(result["status"], "success")
        self.assertEqual(
            application._deps.brands.last_upsert_brand_kwargs["website"],
            "[\"https://www.lixiang.com\", \"https://www.lixiang.com/about\"]",
        )

    async def test_knowledge_update_is_visible_to_paths_load_with_current_revision(self) -> None:
        brand_store = FakeBrandStore()
        brand_knowledge = FakeBrandKnowledgeStore()
        application = _build_application(
            brands=brand_store,
            brand_knowledge=brand_knowledge,
        )

        update_result = await application.update_knowledge(
            KnowledgeUpdateRequest(
                basic_info=KnowledgeBasicInfo(
                    brand_name="示例品牌",
                    brand_code="BRAND-001",
                    intro="更新后的品牌简介，会展示在品牌路径读取结果里。",
                    website=["https://new.example.com"],
                ),
            )
        )

        current_revision = update_result["knowledge_revision"]
        path_result = application.load_brand_paths(
            brand_code="BRAND-001",
            paths=["品牌基础信息/品牌介绍"],
            knowledge_revision=current_revision,
        )

        self.assertIsNotNone(path_result)
        assert path_result is not None
        self.assertEqual([], path_result["missing_paths"])
        self.assertEqual(1, len(path_result["assets"]))
        overview = path_result["assets"][0]
        self.assertEqual("品牌基础信息/品牌介绍", overview["path"])
        self.assertEqual(current_revision, overview["knowledge_revision"])
        self.assertIn("更新后的品牌简介，会展示在品牌路径读取结果里。", overview["content"])
        self.assertIn("https://new.example.com", overview["content"])
        self.assertNotIn("https://example.com", overview["content"])

        with self.assertRaisesRegex(RuntimeError, "knowledge_revision 不匹配"):
            application.load_brand_paths(
                brand_code="BRAND-001",
                paths=["品牌基础信息/品牌介绍"],
                knowledge_revision="demo-2026-06-23",
            )

    async def test_knowledge_update_syncs_attachment_products_from_other_info_and_rebuilds_snapshot(self) -> None:
        enqueue_job = AsyncMock(return_value={"job_id": "job-1", "status": "queued"})
        brand_knowledge = FakeBrandKnowledgeStore()
        brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "other_info",
                "content_json": [
                    {
                        "title": "补充说明",
                        "content": "旧说明",
                    },
                    {
                        "title": "附件解析新增产品",
                        "content": [
                            {
                                "name": "旧附件产品",
                                "product_description": "旧描述",
                            }
                        ],
                    },
                ],
            },
            {
                "knowledge_type": "attachment_products",
                "content_json": [
                    {
                        "name": "旧附件产品",
                        "product_description": "旧描述",
                    }
                ],
            },
        ]
        application = _build_application(
            brands=FakeBrandStore(knowledge_revision="LXKG-SLPP-V1.0.0-20260630010101"),
            brand_knowledge=brand_knowledge,
            enqueue_brand_knowledge_update_job=enqueue_job,
        )

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
            ),
            other_info=[
                {
                    "title": "补充说明",
                    "content": "新说明",
                },
                {
                    "title": "附件解析新增产品",
                    "content": [
                        {
                            "name": "附件新品A",
                            "product_description": "新描述A",
                            "coverage_regions": ["中国", "东南亚"],
                        }
                    ],
                },
            ],
        )

        result = await application.update_knowledge(request)

        self.assertEqual(result["status"], "success")
        self.assertIn("other_info", result["updated_sections"])
        self.assertIn("attachment_products", result["updated_sections"])
        attachment_products_upsert = next(
            item for item in brand_knowledge.last_knowledge_upserts
            if item[1] == "attachment_products"
        )
        self.assertEqual(
            attachment_products_upsert[3],
            [
                {
                    "name": "附件新品A",
                    "product_alias": None,
                    "product_description": "新描述A",
                    "product_website": None,
                    "price_info": None,
                    "product_advantages": None,
                    "target_scenarios": None,
                    "service_standard": None,
                    "service_process": None,
                    "cases_and_reputation": None,
                    "certification_info": None,
                    "core_technology": None,
                    "other_info": None,
                    "product_images": [],
                    "coverage_regions": ["中国", "东南亚"],
                }
            ],
        )
        other_info_upsert = next(
            item for item in brand_knowledge.last_knowledge_upserts
            if item[1] == "other_info"
        )
        self.assertEqual(
            other_info_upsert[3],
            [
                {
                    "title": "补充说明",
                    "content": "新说明",
                },
                {
                    "title": "附件解析新增产品",
                    "content": attachment_products_upsert[3],
                },
            ],
        )

        enqueue_kwargs = enqueue_job.await_args.kwargs
        self.assertEqual(enqueue_kwargs["knowledge_snapshot"]["other_info"], other_info_upsert[3])
        self.assertEqual(
            enqueue_kwargs["knowledge_snapshot"]["products"][0]["name"],
            "明星产品",
        )

    async def test_knowledge_update_attachment_change_increments_minor_version(self) -> None:
        brand_knowledge = FakeBrandKnowledgeStore()
        brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "attachments",
                "content_json": [
                    {"name": "旧附件.docx", "url": "https://example.com/old.docx"},
                ],
            }
        ]
        application = _build_application(
            brands=FakeBrandStore(knowledge_revision="LXKG-SLPP-V1.0.7-20260630010101"),
            brand_knowledge=brand_knowledge,
            brand_attachment_assets=FakeBrandAttachmentAssetStore(),
            oss_client=FakeAttachmentOSSClient(),
            parser=FakeAttachmentParser(),
        )

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
            ),
            attachments=[
                {"name": "旧附件.docx", "url": "https://example.com/old.docx"},
                {"name": "新增附件.docx", "url": "https://example.com/new.docx"},
            ],
        )

        download_stub, _created_paths = await fake_temp_file_download(
            payloads=[
                (b"new-attachment-content", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ],
        )
        with patch(
            "knowledge_base.brand.application.service.download_remote_content_to_temp_file",
            new=AsyncMock(side_effect=download_stub),
        ):
            result = await application.update_knowledge(request)

        self.assertRegex(result["knowledge_revision"], r"^LXKG-SLPP-V1\.1\.0-\d{14}$")

    async def test_knowledge_update_writes_sensitive_topics_object_and_allows_explicit_clear(self) -> None:
        brand_knowledge = FakeBrandKnowledgeStore()
        brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "sensitive_topics",
                "content_json": {
                    "sensitive_contents": ["旧敏感内容"],
                    "controversial_events": ["旧争议事件"],
                    "forbidden_words": [],
                    "negative_clarifications": ["旧口径"],
                    "other_info": [],
                },
            }
        ]
        application = _build_application(
            brand_knowledge=brand_knowledge,
        )

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
            ),
            sensitive_topics={
                "sensitive_contents": ["价格争议"],
                "controversial_events": ["社媒舆情"],
                "forbidden_words": ["保本", "稳赚"],
                "negative_clarifications": ["统一回应口径"],
                "other_info": ["客服注意转述方式"],
            },
        )

        result = await application.update_knowledge(request)

        self.assertEqual(result["status"], "success")
        sensitive_topics_upserts = [
            item for item in application._deps.brand_knowledge.last_knowledge_upserts
            if item[1] == "sensitive_topics"
        ]
        self.assertEqual(
            sensitive_topics_upserts[-1][3],
            {
                "sensitive_contents": ["价格争议"],
                "controversial_events": ["社媒舆情"],
                "forbidden_words": ["保本", "稳赚"],
                "negative_clarifications": ["统一回应口径"],
                "other_info": ["客服注意转述方式"],
            },
        )

        clear_request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
            ),
            sensitive_topics={},
        )

        clear_result = await application.update_knowledge(clear_request)

        self.assertEqual(clear_result["status"], "success")
        sensitive_topics_upserts = [
            item for item in application._deps.brand_knowledge.last_knowledge_upserts
            if item[1] == "sensitive_topics"
        ]
        self.assertEqual(
            sensitive_topics_upserts[-1][3],
            {},
        )
