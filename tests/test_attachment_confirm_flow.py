from __future__ import annotations

import asyncio
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from knowledge_base.brand.application import BrandApplicationDependencies, BrandApplicationService
from knowledge_base.brand_knowledge.application import AttachmentDraftDependencies, AttachmentDraftService
from knowledge_base.brand_knowledge.schemas import AttachmentConfirmSaveRequest

from tests.fakes.brand_flow import (
    FakeBrandKnowledgeStore,
    FakeBrandProductStore,
    FakeBrandStore,
    FakeDocumentCategoryStore,
    FakeDocumentRegistryStore,
    FakeIndustryStore,
    FakeSettings,
    FakeUploadTaskStore,
    _fake_runtime,
)


class AttachmentConfirmFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirm_save_merges_existing_knowledge_and_callbacks_changed_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            draft_id = "bad_demo"
            review_id = "bar_demo"
            draft_dir = Path(temp_dir) / "attachment_parse_drafts" / draft_id
            review_dir = draft_dir / "reviews"
            review_dir.mkdir(parents=True, exist_ok=True)

            manifest = {
                "draft_id": draft_id,
                "brand_name": "示例品牌",
                "brand_code": "BRAND-001",
                "attachments": [
                    {
                        "name": "新附件.pdf",
                        "url": "https://example.com/new.pdf",
                        "status": "success",
                        "markdown_text": "# 新附件\n补充内容",
                    }
                ],
            }
            (draft_dir / "draft.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            review_payload = {
                "review_id": review_id,
                "draft_id": draft_id,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "knowledge_revision": "demo-2026-06-23",
                "combined_markdown_text": "# 确认后的知识",
                "update_request_payload": {
                    "basic_info": {
                        "brand_code": "BRAND-001",
                        "brand_name": "示例品牌",
                        "website": ["https://example.com/new-home"],
                        "official_wechat_account": "new_wechat",
                        "target_regions": ["美国", "中国"],
                    },
                    "products": [
                        {
                            "name": "明星产品",
                            "product_description": "新的产品介绍",
                        },
                        {
                            "name": "新品系列",
                            "product_description": "新增产品介绍",
                        },
                    ],
                    "company_profile": {
                        "company_intro": "新的公司介绍",
                    },
                    "management_team": [
                        {
                            "name": "张三",
                            "title": "创始人",
                        },
                        {
                            "name": "李四",
                            "title": "CTO",
                            "profile": "新增成员",
                        },
                    ],
                    "competitors": [
                        {
                            "name": "竞品A",
                            "competitors_description": "竞品A新描述",
                        },
                        {
                            "name": "竞品B",
                            "competitors_description": "新增竞品",
                        },
                    ],
                    "authority_honors": [
                        {
                            "title": "奖项A",
                            "year": "2024",
                            "description": "奖项A新描述",
                        },
                        {
                            "title": "奖项B",
                            "year": "2025",
                            "description": "新增奖项",
                        },
                    ],
                    "customers_cases": [
                        {
                            "case_name": "案例A",
                            "cooperation_highlight": "案例A新亮点",
                        },
                        {
                            "case_name": "案例B",
                            "customer_name": "客户B",
                            "cooperation_highlight": "新增案例",
                        },
                    ],
                    "sensitive_topics": {
                        "sensitive_contents": ["敏感点1"],
                        "forbidden_words": ["禁词B"],
                    },
                    "attachments": [
                        {
                            "name": "新附件.pdf",
                            "url": "https://example.com/new.pdf",
                        }
                    ],
                },
            }
            (review_dir / f"{review_id}.json").write_text(
                json.dumps(review_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            brand_store = FakeBrandStore()
            product_store = FakeBrandProductStore()
            knowledge_store = FakeBrandKnowledgeStore()
            knowledge_store.knowledge_rows = [
                {
                    "knowledge_type": "company_profile",
                    "content_json": {
                        "brand_subject_name": "示例企业主体",
                        "company_intro": "旧公司介绍",
                    },
                },
                {
                    "knowledge_type": "management_team",
                    "content_json": [
                        {
                            "name": "张三",
                            "title": "CEO",
                            "profile": "旧简介",
                        }
                    ],
                },
                {
                    "knowledge_type": "competitors",
                    "content_json": [
                        {
                            "name": "竞品A",
                            "competitors_description": "旧竞品描述",
                        }
                    ],
                },
                {
                    "knowledge_type": "authority_honors",
                    "content_json": [
                        {
                            "title": "奖项A",
                            "year": "2024",
                            "description": "旧奖项描述",
                        }
                    ],
                },
                {
                    "knowledge_type": "customers_cases",
                    "content_json": [
                        {
                            "case_name": "案例A",
                            "customer_name": "客户A",
                            "cooperation_highlight": "旧案例亮点",
                        }
                    ],
                },
                {
                    "knowledge_type": "sensitive_topics",
                    "content_json": {
                        "forbidden_words": ["禁词A"],
                    },
                },
                {
                    "knowledge_type": "attachments",
                    "content_json": [
                        {
                            "name": "旧附件.pdf",
                            "url": "https://example.com/old.pdf",
                        }
                    ],
                },
            ]

            brand_application = BrandApplicationService(
                BrandApplicationDependencies(
                    settings=FakeSettings(upload_staging_dir=temp_dir),
                    brands=brand_store,
                    brand_products=product_store,
                    brand_knowledge=knowledge_store,
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
                )
            )

            ingest_calls: list[dict[str, object]] = []

            async def fake_ingest_text_document(**kwargs):
                ingest_calls.append(kwargs)
                return types.SimpleNamespace(
                    document_id="confirmed-doc-1",
                    metadata={"fulltext_key": None},
                )

            async def fake_build_next_brand_full_knowledge(**kwargs):
                return {
                    "knowledge_oss_key_md": "ai_knowledge/demo.md",
                    "knowledge_oss_url_md": "https://oss.example.com/ai_knowledge/demo.md",
                    "knowledge_oss_key_pdf": "ai_knowledge/demo.pdf",
                    "knowledge_oss_url_pdf": "https://oss.example.com/ai_knowledge/demo.pdf",
                    "version_no": 2,
                }

            upload_tasks = FakeUploadTaskStore()
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=FakeSettings(upload_staging_dir=temp_dir),
                    parser=None,
                    oss_client=types.SimpleNamespace(
                        enabled=False,
                        build_object_url=lambda object_key: f"https://oss.example.com/{object_key}",
                    ),
                    brands=brand_store,
                    brand_products=product_store,
                    brand_knowledge=knowledge_store,
                    update_knowledge=brand_application.update_knowledge,
                    ingest_text_document=fake_ingest_text_document,
                    ingest_staged_file=None,
                    build_next_brand_full_knowledge=fake_build_next_brand_full_knowledge,
                    runtime=_fake_runtime(),
                    spawn_background_task=asyncio.create_task,
                    upload_tasks=upload_tasks,
                )
            )

            captured_callback: dict[str, object] = {}
            original_post = AttachmentDraftService._post_confirm_callback

            def fake_post_confirm_callback(callback_url: str, payload: dict[str, object], timeout_seconds: float):
                captured_callback["url"] = callback_url
                captured_callback["payload"] = payload
                captured_callback["timeout_seconds"] = timeout_seconds
                return 200, "ok"

            AttachmentDraftService._post_confirm_callback = staticmethod(fake_post_confirm_callback)
            try:
                with patch(
                    "knowledge_base.brand_knowledge.application.attachment_flow.build_brand_knowledge_snapshot_from_markdown",
                    new=AsyncMock(return_value={"supplemental_markdown_sources": []}),
                ):
                    result = await service._process_confirm_pipeline(
                        request=AttachmentConfirmSaveRequest(
                            draft_id=draft_id,
                            review_id=review_id,
                            knowledge_revision="demo-2026-06-23",
                        ),
                        draft_id=draft_id,
                    )
            finally:
                AttachmentDraftService._post_confirm_callback = original_post

            knowledge_map = {
                row["knowledge_type"]: row["content_json"]
                for row in knowledge_store.knowledge_rows
            }
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["confirm_callback_status"], "success")
            callback_row = upload_tasks.get_upload_task_callback(
                task_id=f"confirm:{draft_id}:{review_id}",
                callback_type="brand_knowledge_completed",
            )
            self.assertEqual(callback_row["status"], "success")
            self.assertEqual(callback_row["retry_count"], 0)
            self.assertEqual(callback_row["last_response_code"], 200)
            self.assertIsNotNone(callback_row["sent_at"])
            self.assertEqual(callback_row["request_payload_json"], captured_callback["payload"])
            self.assertEqual(0, len(ingest_calls))
            self.assertIn("management_team", result["updated_sections"])
            self.assertIn("attachments", result["updated_sections"])

            management_team = knowledge_map["management_team"]
            self.assertEqual(
                management_team,
                [
                    {
                        "name": "张三",
                        "title": "创始人",
                        "profile": "旧简介",
                        "introduction_website": None,
                        "source_section": None,
                        "other_info": None,
                    },
                    {
                        "name": "李四",
                        "title": "CTO",
                        "profile": "新增成员",
                        "introduction_website": None,
                        "source_section": None,
                        "other_info": None,
                    },
                ],
            )
            self.assertEqual(
                knowledge_map["competitors"],
                [
                    {
                        "name": "竞品A",
                        "aliases": [],
                        "introduction": "竞品A新描述",
                        "official_websites": [],
                        "logo_urls": [],
                        "strengths": [],
                        "differentiated_positioning": [],
                        "comparison_dimensions": [],
                        "other_info": [],
                    },
                    {
                        "name": "竞品B",
                        "aliases": [],
                        "introduction": "新增竞品",
                        "official_websites": [],
                        "logo_urls": [],
                        "strengths": [],
                        "differentiated_positioning": [],
                        "comparison_dimensions": [],
                        "other_info": [],
                    },
                ],
            )
            self.assertEqual(
                knowledge_map["sensitive_topics"],
                {
                    "sensitive_contents": ["敏感点1"],
                    "controversial_events": [],
                    "forbidden_words": ["禁词A", "禁词B"],
                    "negative_clarifications": [],
                    "other_info": [],
                },
            )
            self.assertEqual(
                knowledge_map["attachments"],
                [
                    {
                        "name": "旧附件.pdf",
                        "url": "https://example.com/old.pdf",
                    },
                    {
                        "name": "新附件.pdf",
                        "url": "https://example.com/new.pdf",
                    },
                ],
            )
            callback_payload = captured_callback["payload"]
            self.assertNotIn("knowledge_mete", callback_payload)
            self.assertEqual(len(callback_payload["knowledge"]["management_team"]["members"]), 2)
            self.assertEqual(callback_payload["knowledge"]["management_team"]["members"][0]["name"], "张三")
            self.assertEqual(callback_payload["knowledge"]["management_team"]["members"][0]["title"], "创始人")
            self.assertEqual(callback_payload["knowledge"]["management_team"]["members"][1]["name"], "李四")
            self.assertEqual(callback_payload["knowledge"]["sensitive_topics"]["forbidden_words"], ["禁词B"])
            self.assertEqual(
                callback_payload["knowledge"]["basic_info"]["website"],
                ["https://example.com/new-home"],
            )
            self.assertEqual(
                callback_payload["knowledge"]["basic_info"]["extra_info"]["target_region"],
                ["美国", "中国"],
            )
            self.assertEqual(
                callback_payload["knowledge"]["attachments"]["files"],
                [
                    {
                        "name": "新附件.pdf",
                        "url": "https://example.com/new.pdf",
                        "type": "",
                        "description": "",
                    }
                ],
            )

    async def test_confirm_save_callback_retries_in_background(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            draft_id = "bad_retry"
            review_id = "bar_retry"
            draft_dir = Path(temp_dir) / "attachment_parse_drafts" / draft_id
            review_dir = draft_dir / "reviews"
            review_dir.mkdir(parents=True, exist_ok=True)

            (draft_dir / "draft.json").write_text(
                json.dumps(
                    {
                        "draft_id": draft_id,
                        "brand_name": "示例品牌",
                        "brand_code": "BRAND-001",
                        "attachments": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (review_dir / f"{review_id}.json").write_text(
                json.dumps(
                    {
                        "review_id": review_id,
                        "draft_id": draft_id,
                        "brand_code": "BRAND-001",
                        "brand_name": "示例品牌",
                        "knowledge_revision": "demo-2026-06-23",
                        "combined_markdown_text": "# 确认后的知识",
                        "update_request_payload": {
                            "basic_info": {
                                "brand_code": "BRAND-001",
                                "brand_name": "示例品牌",
                            },
                            "attachments": [],
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            brand_store = FakeBrandStore()
            product_store = FakeBrandProductStore()
            knowledge_store = FakeBrandKnowledgeStore()
            brand_application = BrandApplicationService(
                BrandApplicationDependencies(
                    settings=FakeSettings(upload_staging_dir=temp_dir),
                    brands=brand_store,
                    brand_products=product_store,
                    brand_knowledge=knowledge_store,
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
                )
            )

            ingest_calls: list[dict[str, object]] = []

            async def fake_ingest_text_document(**kwargs):
                ingest_calls.append(kwargs)
                return types.SimpleNamespace(document_id="confirmed-doc-1", metadata={"fulltext_key": None})

            runtime = _fake_runtime()
            background_tasks: list[asyncio.Task[object]] = []

            def spawn_background_task(coro):
                task = asyncio.create_task(coro)
                background_tasks.append(task)
                return task

            upload_tasks = FakeUploadTaskStore()
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=FakeSettings(upload_staging_dir=temp_dir),
                    parser=None,
                    oss_client=types.SimpleNamespace(
                        enabled=False,
                        build_object_url=lambda object_key: f"https://oss.example.com/{object_key}",
                    ),
                    brands=brand_store,
                    brand_products=product_store,
                    brand_knowledge=knowledge_store,
                    update_knowledge=brand_application.update_knowledge,
                    ingest_text_document=fake_ingest_text_document,
                    ingest_staged_file=None,
                    build_next_brand_full_knowledge=None,
                    runtime=runtime,
                    spawn_background_task=spawn_background_task,
                    upload_tasks=upload_tasks,
                )
            )

            original_post = AttachmentDraftService._post_confirm_callback
            original_delays = AttachmentDraftService._CONFIRM_CALLBACK_RETRY_DELAYS_SECONDS
            attempts = {"count": 0}

            def fake_post_confirm_callback(callback_url: str, payload: dict[str, object], timeout_seconds: float):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    return 500, "fail"
                return 200, "ok"

            AttachmentDraftService._post_confirm_callback = staticmethod(fake_post_confirm_callback)
            AttachmentDraftService._CONFIRM_CALLBACK_RETRY_DELAYS_SECONDS = (0, 0, 0)
            try:
                with patch(
                    "knowledge_base.brand_knowledge.application.attachment_flow.build_brand_knowledge_snapshot_from_markdown",
                    new=AsyncMock(return_value={"supplemental_markdown_sources": []}),
                ):
                    result = await service._process_confirm_pipeline(
                        request=AttachmentConfirmSaveRequest(
                            draft_id=draft_id,
                            review_id=review_id,
                            knowledge_revision="demo-2026-06-23",
                        ),
                        draft_id=draft_id,
                    )
                    if background_tasks:
                        await asyncio.gather(*background_tasks)
            finally:
                AttachmentDraftService._post_confirm_callback = original_post
                AttachmentDraftService._CONFIRM_CALLBACK_RETRY_DELAYS_SECONDS = original_delays

            self.assertEqual(result["confirm_callback_status"], "retrying")
            self.assertEqual(attempts["count"], 2)
            self.assertEqual(runtime.scheduled_attachment_confirm_callback_retries, set())
            callback_row = upload_tasks.get_upload_task_callback(
                task_id=f"confirm:{draft_id}:{review_id}",
                callback_type="brand_knowledge_completed",
            )
            self.assertEqual(callback_row["status"], "success")
            self.assertEqual(callback_row["retry_count"], 1)
            self.assertEqual(callback_row["last_response_code"], 200)
            self.assertIsNone(callback_row["next_retry_at"])
            self.assertIsNotNone(callback_row["sent_at"])
