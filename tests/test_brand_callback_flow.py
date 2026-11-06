from __future__ import annotations

import asyncio
import types
import unittest
from datetime import datetime
from unittest.mock import AsyncMock

from knowledge_base.brand import knowledge_extraction as brand_knowledge_extraction
from knowledge_base.brand.application import callbacks as brand_callbacks

from tests.fakes.brand_flow import (
    FakeBrandFullKnowledgeStore,
    FakeBrandKnowledgeStore,
    FakeBrandProductStore,
    FakeBrandStore,
    FakeDocumentCategoryStore,
    FakeDocumentRegistryStore,
    FakeSettings,
    FakeUploadTaskStore,
    _fake_runtime,
    _fake_spawn_background_task,
)


class BrandCallbackFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._original_extract = brand_knowledge_extraction.extract_brand_knowledge_from_markdown

    def tearDown(self) -> None:
        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = self._original_extract

    async def test_callback_payload_builds_final_counts(self) -> None:
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_full_knowledge=FakeBrandFullKnowledgeStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _document_categories=FakeDocumentCategoryStore(),
            _document_registry=FakeDocumentRegistryStore(),
            _upload_tasks=FakeUploadTaskStore(),
            _settings=FakeSettings(),
            _runtime=_fake_runtime(),
            oss_client=types.SimpleNamespace(
                enabled=True,
                upload_bytes=lambda data, object_key, content_type=None: object_key,
                build_object_url=lambda object_key: f"https://oss.example.com/{object_key}",
            ),
            _spawn_background_task=_fake_spawn_background_task,
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
                        "english_name": "Example Brand",
                        "website": ["https://md.example.com"],
                        "customer_service_hotline": "123456",
                        "official_wechat_account": "md_wechat",
                        "positioning": "高端智能服务品牌",
                        "advantages": "渠道广、交付快、服务稳定",
                        "mission": "让企业服务更高效",
                        "vision": "成为行业领先品牌",
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
                            "product_description": "这条不该进入回调",
                        }
                    ],
                    "company_profile": {"brand_subject_name": "示例品牌主体名称", "company_intro": "品牌介绍"},
                    "management_team": [{"member_name": "张三", "position": "CEO", "profile": "负责战略", "introduction_website": "", "source_section": "管理团队"}],
                    "competitors": [{"name": "竞品A", "competitors_alias": "", "competitors_description": "竞品介绍", "website": "", "competitors_logo": "", "competitive_advantages": "渠道广", "differentiated_positioning": "", "comparison_dimensions": "", "source_section": "竞品"}],
                    "authority_honors": [],
                    "customers_cases": [],
                    "sensitive_topics": [],
                }
            return {
                "basic_info": {},
                "products": [],
                "company_profile": {"brand_subject_name": "示例品牌主体名称"},
                "management_team": [{"member_name": "张三", "position": "创始人兼CEO", "profile": "曾任高管", "introduction_website": "", "source_section": "团队"}],
                "competitors": [],
                "authority_honors": [{"title": "高新技术企业", "description": "国家认定", "report_link": "", "year": "2024", "qualification_proof": "", "source_section": "荣誉"}],
                "customers_cases": [],
                "sensitive_topics": [{"topic": "价格较高", "description": "部分用户认为偏贵", "forbidden_terms": "", "history_negative_clarification": "强调品质价值", "source_section": "FAQ"}],
                "official_malls": [
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
                "official_media_matrix": [
                    {
                        "media_platform": "微信公众号",
                        "account_name": "品牌服务号",
                        "account_id": "brand-service",
                        "is_official": "是",
                        "related_products": ["200001"],
                        "other_info": ["新品发布"],
                    }
                ],
            }

        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = fake_extract

        callback_result = await brand_callbacks._build_callback_payload_with_knowledge(service, "task-1")

        self.assertIsNotNone(callback_result)
        payload = callback_result
        self.assertEqual(payload["brand_code"], "BRAND-001")
        self.assertEqual(payload["overall_status"], "completed")
        self.assertEqual(payload["completed_at"], "2026-06-08 12:00:00")
        self.assertEqual(payload["knowledge_extraction_status"], "success")
        self.assertEqual(payload["knowledge_markdown_status"], "skipped")
        self.assertEqual(payload["knowledge_mete"]["oss_url_md"], "")
        self.assertEqual(payload["knowledge_mete"]["oss_url_pdf"], "")
        self.assertEqual(payload["knowledge_mete"]["version"], service._brands.knowledge_revision)
        self.assertRegex(payload["knowledge_mete"]["version"], r"^LXKG-SLPP-V1\.0\.0-\d{14}$")
        self.assertEqual(payload["knowledge"]["basic_info"]["extra_info"]["official_wechat"], "md_wechat")
        self.assertEqual(
            payload["knowledge"]["basic_info"]["website"],
            ["https://example.com", "https://md.example.com"],
        )
        self.assertEqual(len(payload["knowledge"]["products"]), 1)
        self.assertEqual(payload["knowledge"]["products"][0]["base_info"]["name"], "明星产品")
        self.assertEqual(
            payload["knowledge"]["products"][0]["base_info"]["product_description"],
            "核心产品介绍",
        )
        self.assertEqual(payload["knowledge"]["company_profile"]["subject_info"], "示例品牌主体名称")
        self.assertEqual(payload["knowledge"]["management_team"]["members"][0]["title"], "创始人兼CEO")
        self.assertEqual(payload["knowledge"]["sensitive_topics"]["sensitive_contents"], ["价格较高"])
        self.assertEqual(
            payload["knowledge"]["sensitive_topics"]["negative_clarifications"],
            ["强调品质价值"],
        )
        self.assertEqual(payload["knowledge"]["attachments"]["files"][0]["name"], "品牌手册.md")
        self.assertEqual(payload["knowledge"]["attachments"]["files"][0]["url"], "https://example.com/brand-book.pdf")
        self.assertEqual(payload["knowledge"]["attachments"]["files"][0]["description"], "")
        self.assertEqual(payload["knowledge"]["official_malls"][0]["store_name"], "品牌旗舰店")
        self.assertEqual(payload["knowledge"]["official_malls"][0]["related_products"], [1001])
        self.assertEqual(payload["knowledge"]["official_media_matrix"][0]["account_name"], "品牌服务号")
        self.assertEqual(payload["knowledge"]["official_media_matrix"][0]["related_products"], ["200001"])
        self.assertEqual(service._brand_full_knowledge.rows, [])

    async def test_callback_required_fields_fallback_to_space(self) -> None:
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _brand_full_knowledge=FakeBrandFullKnowledgeStore(),
            _document_categories=FakeDocumentCategoryStore(),
            _document_registry=FakeDocumentRegistryStore(),
            _upload_tasks=FakeUploadTaskStore(),
            _settings=FakeSettings(),
            _runtime=_fake_runtime(),
            oss_client=types.SimpleNamespace(
                enabled=True,
                upload_bytes=lambda data, object_key, content_type=None: object_key,
                build_object_url=lambda object_key: f"https://oss.example.com/{object_key}",
            ),
            _spawn_background_task=_fake_spawn_background_task,
            get_full_text=lambda document_id: f"# {document_id}\n正文",
            _get_document_info=lambda document_id: {"metadata_json": {}},
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
                "management_team": [{"member_name": "张三", "position": "", "profile": "成员介绍", "introduction_website": "", "source_section": "团队"}],
                "competitors": [{"name": "竞品A", "competitors_alias": "", "competitors_description": "", "website": "", "competitors_logo": "", "competitive_advantages": "", "differentiated_positioning": "", "comparison_dimensions": "", "source_section": "竞品"}],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": [],
            }

        brand_knowledge_extraction.extract_brand_knowledge_from_markdown = fake_extract

        callback_result = await brand_callbacks._build_callback_payload_with_knowledge(service, "task-1")

        self.assertIsNotNone(callback_result)
        payload = callback_result
        self.assertEqual(payload["knowledge_markdown_status"], "skipped")
        self.assertEqual(payload["knowledge_mete"]["oss_url_md"], "")
        self.assertEqual(payload["knowledge_mete"]["oss_url_pdf"], "")
        self.assertEqual(payload["knowledge_mete"]["version"], service._brands.knowledge_revision)
        self.assertRegex(payload["knowledge_mete"]["version"], r"^LXKG-SLPP-V1\.0\.0-\d{14}$")
        self.assertEqual(payload["knowledge"]["company_profile"]["subject_info"], "示例企业主体")
        self.assertEqual(payload["knowledge"]["company_profile"]["business_license_url"], "https://example.com/license.png")
        self.assertIn("aliases", payload["knowledge"]["competitors"]["competitors"][0])
        self.assertEqual(payload["knowledge"]["attachments"]["files"][0]["type"], "pdf")

    async def test_callback_with_attachment_auto_completed_uses_current_brand_snapshot(self) -> None:
        class AttachmentOnlyUploadTaskStore(FakeUploadTaskStore):
            def refresh_upload_task_counts(self, task_id: str):
                return {
                    "file_count": 1,
                    "success_count": 1,
                    "failed_count": 0,
                    "pending_count": 0,
                    "processing_count": 0,
                }

            def get_upload_task(self, task_id: str):
                if task_id != "task-1":
                    return None
                return {
                    "task_id": task_id,
                    "status": "completed",
                    "file_count": 1,
                    "success_count": 1,
                    "failed_count": 0,
                    "pending_count": 0,
                    "processing_count": 0,
                    "metadata_json": {
                        "category": "示例品牌",
                        "brand_callback_enabled": True,
                        "brand_code": "BRAND-001",
                        "_task_payload": {
                            "file_metadata_by_index": {
                                "0": {"source_url": "https://example.com/brand-book.pdf"},
                            }
                        },
                    },
                    "updated_at": datetime(2026, 7, 16, 13, 40, 0),
                }

            def get_upload_task_files(self, task_id: str):
                return [
                    {
                        "status": "success",
                        "document_id": None,
                        "file_index": 0,
                        "original_filename": "品牌手册.docx",
                        "source_type": "docx",
                        "file_role": "attachment",
                    }
                ]

        service = types.SimpleNamespace(
            _brands=FakeBrandStore(knowledge_revision="LXKG-SLPP-V1.1.0-20260716134015"),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _brand_full_knowledge=FakeBrandFullKnowledgeStore(),
            _document_categories=FakeDocumentCategoryStore(),
            _document_registry=FakeDocumentRegistryStore(),
            _upload_tasks=AttachmentOnlyUploadTaskStore(),
            _settings=FakeSettings(),
            _runtime=_fake_runtime(),
            oss_client=types.SimpleNamespace(
                enabled=True,
                upload_bytes=lambda data, object_key, content_type=None: object_key,
                build_object_url=lambda object_key: f"https://oss.example.com/{object_key}",
            ),
            _spawn_background_task=_fake_spawn_background_task,
            start_brand_attachment_conflict_session=AsyncMock(
                return_value={
                    "session_id": "bks_demo",
                    "status": "completed",
                    "knowledge_oss_url_md": "https://oss.example.com/test/示例品牌/ai_knowledge/【示例品牌】品牌AI知识库_V1_20260716.md",
                    "knowledge_oss_url_pdf": "https://oss.example.com/test/示例品牌/ai_knowledge/【示例品牌】品牌AI知识库_V1_20260716.pdf",
                }
            ),
            _load_brand_knowledge_snapshot=lambda *, brand: {
                "basic_info": {
                    "brand_code": brand.get("brand_code"),
                    "brand_name": brand.get("brand_name"),
                    "website": ["https://example.com"],
                },
                "company_profile": {
                    "brand_subject_name": "示例企业主体",
                },
                "attachments": [
                    {
                        "name": "品牌手册.docx",
                        "url": "https://example.com/brand-book.pdf",
                    }
                ],
            },
            _current_brand_knowledge_mete=lambda *, brand: (
                "success",
                {
                    "version": str(brand.get("knowledge_revision") or ""),
                    "oss_url_md": "https://oss.example.com/test/示例品牌/ai_knowledge/【示例品牌】品牌AI知识库_V1_20260716.md",
                    "oss_url_pdf": "https://oss.example.com/test/示例品牌/ai_knowledge/【示例品牌】品牌AI知识库_V1_20260716.pdf",
                },
            ),
        )

        payload = await brand_callbacks._build_callback_payload_with_knowledge(service, "task-1")

        self.assertIsNone(payload)
        self.assertEqual(service.start_brand_attachment_conflict_session.await_count, 1)

    async def test_maybe_finalize_task_callback_skips_duplicate_inflight_generation(self) -> None:
        class RecordingCoordinator(brand_callbacks.BrandCallbackCoordinator):
            def __init__(self, dependencies, gate: asyncio.Event, calls: list[str]) -> None:
                super().__init__(dependencies)
                self._gate = gate
                self._calls = calls

            async def build_callback_payload_with_knowledge(self, task_id: str) -> dict[str, object] | None:
                self._calls.append(task_id)
                await self._gate.wait()
                return ("brand_knowledge_completed", {"task_id": task_id, "knowledge": {"ok": True}})

        gate = asyncio.Event()
        calls: list[str] = []
        coordinator = RecordingCoordinator(
            brand_callbacks.BrandCallbackCoordinatorDependencies(
                settings=FakeSettings(),
                brands=FakeBrandStore(),
                upload_tasks=FakeUploadTaskStore(),
                document_registry=FakeDocumentRegistryStore(),
                runtime=_fake_runtime(),
                spawn_background_task=_fake_spawn_background_task,
                extract_brand_knowledge_for_task=None,
                format_brand_callback_knowledge=None,
            ),
            gate,
            calls,
        )

        original_send = brand_callbacks.BrandCallbackCoordinator._send_callback_request
        brand_callbacks.BrandCallbackCoordinator._send_callback_request = staticmethod(lambda *args, **kwargs: (200, "ok", None))
        try:
            first_task = asyncio.create_task(coordinator.maybe_finalize_task_callback("task-1"))
            await asyncio.sleep(0)
            second_result = await coordinator.maybe_finalize_task_callback("task-1")
            gate.set()
            first_result = await first_task
        finally:
            brand_callbacks.BrandCallbackCoordinator._send_callback_request = original_send

        self.assertTrue(first_result)
        self.assertFalse(second_result)
        self.assertEqual(calls, ["task-1"])
