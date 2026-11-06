from __future__ import annotations

import asyncio
import json
import types
import unittest
from unittest.mock import AsyncMock, patch

from knowledge_base.brand.application import BrandApplicationDependencies, BrandApplicationService
from knowledge_base.brand.schemas import KnowledgeBasicInfo, KnowledgeProduct, KnowledgeUpdateRequest
from knowledge_base.composition import build_applications
from knowledge_base.background_jobs.brand_full_knowledge_refresh import BrandFullKnowledgeRefreshJobHandler
from knowledge_base.brand.full_markdown import generate_full_brand_knowledge_markdown_from_update
from knowledge_base.api_app.routers.knowledge import update_knowledge as update_knowledge_endpoint

from tests.fakes.brand_flow import (
    FakeBrandFullKnowledgeStore,
    FakeBrandKnowledgeStore,
    FakeBrandKnowledgeUpdateAuditStore,
    FakeBrandProductStore,
    FakeBrandStore,
    FakeDocumentCategoryStore,
    FakeDocumentRegistryStore,
    FakeIndustryStore,
    FakeSettings,
    FakeUploadTaskStore,
    _fake_spawn_background_task,
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


class BrandKnowledgeUpdateSideEffectsTests(unittest.IsolatedAsyncioTestCase):
    async def test_products_snapshot_removes_missing_products_and_records_deletion(self) -> None:
        for clear_all in (False, True):
            with self.subTest(clear_all=clear_all):
                products = FakeBrandProductStore()
                products.synced_products = [
                    {"product_code": "A", "product_name": "产品A"},
                    {"product_code": "B", "product_name": "产品B"},
                ]
                audit_store = FakeBrandKnowledgeUpdateAuditStore()
                enqueue = AsyncMock(return_value={"job_id": "refresh:1", "status": "waiting"})
                application = _build_application(
                    brand_products=products,
                    brand_knowledge_update_audits=audit_store,
                    enqueue_brand_full_knowledge_refresh_job=enqueue,
                )
                request_products = [] if clear_all else [KnowledgeProduct(product_code="A", name="产品A")]
                result = await application.update_knowledge(KnowledgeUpdateRequest(
                    basic_info=KnowledgeBasicInfo(brand_name="示例品牌", brand_code="BRAND-001"),
                    products=request_products,
                ))
                self.assertEqual(result["updated_sections"], ["products"])
                self.assertEqual(result["deleted_sections"], ["products"])
                self.assertRegex(result["knowledge_revision"], r"^LXKG-SLPP-V1\.0\.1-\d{14}$")
                self.assertEqual([row["product_code"] for row in products.get_brand_products(brand_id=1)], [] if clear_all else ["A"])
                enqueue.assert_awaited_once()
                entry = audit_store.created_calls[0]["entries"][0]
                self.assertEqual(entry["action"], "delete")
                self.assertEqual([row["product_code"] for row in entry["before"]], ["A", "B"])
                self.assertEqual([row["product_code"] for row in entry["after"]], [] if clear_all else ["A"])
                enqueue.reset_mock()
                repeated = await application.update_knowledge(KnowledgeUpdateRequest(
                    basic_info=KnowledgeBasicInfo(brand_name="示例品牌", brand_code="BRAND-001"),
                    products=request_products,
                ))
                self.assertEqual(repeated["updated_sections"], [])
                self.assertEqual(repeated["deleted_sections"], [])
                enqueue.assert_not_awaited()

    async def test_products_with_missing_name_cannot_silently_clear_existing_products(self) -> None:
        products = FakeBrandProductStore()
        original = products.get_brand_products(brand_id=1)
        application = _build_application(brand_products=products)
        with self.assertRaisesRegex(ValueError, "产品.*名称"):
            await application.update_knowledge(KnowledgeUpdateRequest(
                basic_info=KnowledgeBasicInfo(brand_name="示例品牌", brand_code="BRAND-001"),
                products=[KnowledgeProduct(product_code="A")],
            ))
        self.assertEqual(products.get_brand_products(brand_id=1), original)

    async def test_endpoint_omitted_products_and_empty_products_clear_the_last_product(self) -> None:
        for product_fields in ({}, {"products": []}):
            with self.subTest(product_fields=product_fields):
                products = FakeBrandProductStore()
                products.synced_products = [{"product_code": "A", "product_name": "最后一个产品"}]
                audit_store = FakeBrandKnowledgeUpdateAuditStore()
                enqueue = AsyncMock(return_value={"job_id": "refresh:1", "status": "waiting"})
                application = _build_application(
                    brand_products=products,
                    brand_knowledge_update_audits=audit_store,
                    enqueue_brand_full_knowledge_refresh_job=enqueue,
                )
                request = KnowledgeUpdateRequest(
                    basic_info=KnowledgeBasicInfo(brand_name="示例品牌", brand_code="BRAND-001"),
                    **product_fields,
                )
                result = await update_knowledge_endpoint(request, service=application)
                self.assertEqual(products.get_brand_products(brand_id=1), [])
                self.assertEqual(result["updated_sections"], ["products"])
                self.assertEqual(result["deleted_sections"], ["products"])
                self.assertRegex(result["knowledge_revision"], r"^LXKG-SLPP-V1\.0\.1-\d{14}$")
                entry = audit_store.created_calls[0]["entries"][0]
                self.assertEqual(entry["action"], "delete")
                self.assertEqual(entry["before"][0]["product_code"], "A")
                self.assertEqual(entry["after"], [])
                enqueue.assert_awaited_once()
                enqueue.reset_mock()
                repeated = await update_knowledge_endpoint(request, service=application)
                self.assertEqual(repeated["updated_sections"], [])
                self.assertEqual(repeated["deleted_sections"], [])
                enqueue.assert_not_awaited()

    async def test_internal_update_omitted_products_preserve_snapshot_and_do_not_enqueue_refresh(self) -> None:
        products = FakeBrandProductStore()
        products.sync_brand_products = AsyncMock()
        enqueue = AsyncMock()
        application = _build_application(brand_products=products, enqueue_brand_full_knowledge_refresh_job=enqueue)
        result = await application.update_knowledge(KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(brand_name="示例品牌", brand_code="BRAND-001"),
        ))
        products.sync_brand_products.assert_not_called()
        enqueue.assert_not_awaited()
        self.assertEqual(result["updated_sections"], [])
        self.assertEqual(result["deleted_sections"], [])

    async def test_products_snapshot_same_names_use_codes_and_reordering_is_not_deletion(self) -> None:
        for request_codes, deleted in ((["B", "A"], False), (["A"], True)):
            with self.subTest(request_codes=request_codes):
                products = FakeBrandProductStore()
                products.synced_products = [
                    {"product_code": "A", "product_name": "同名产品"},
                    {"product_code": "B", "product_name": "同名产品"},
                ]
                enqueue = AsyncMock(return_value={"job_id": "refresh:1"})
                application = _build_application(brand_products=products, enqueue_brand_full_knowledge_refresh_job=enqueue)
                result = await application.update_knowledge(KnowledgeUpdateRequest(
                    basic_info=KnowledgeBasicInfo(brand_name="示例品牌", brand_code="BRAND-001"),
                    products=[KnowledgeProduct(product_code=code, name="同名产品") for code in request_codes],
                ))
                self.assertEqual(result["deleted_sections"], ["products"] if deleted else [])
                self.assertEqual(enqueue.await_count, int(deleted))

    async def test_product_deletion_audit_drives_refresh_patch_and_preserves_other_sections(self) -> None:
        products = FakeBrandProductStore()
        products.synced_products = [
            {"product_code": "A", "product_name": "产品A"},
            {"product_code": "B", "product_name": "产品B"},
        ]
        audit_store = FakeBrandKnowledgeUpdateAuditStore()
        application = _build_application(
            brand_products=products, brand_knowledge_update_audits=audit_store,
            enqueue_brand_full_knowledge_refresh_job=AsyncMock(return_value={"job_id": "refresh:1"}),
        )
        result = await application.update_knowledge(KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(brand_name="示例品牌", brand_code="BRAND-001"),
            products=[KnowledgeProduct(product_code="A", name="产品A")],
        ))
        entry = audit_store.created_calls[0]["entries"][0]
        audits = [{
            "id": 1, "section": "products", "section_title": "产品信息",
            "source_type": "knowledge_update", "change_action": entry["action"],
            "before_json": json.dumps(entry["before"], ensure_ascii=False),
            "after_json": json.dumps(entry["after"], ensure_ascii=False),
        }]
        full_store = FakeBrandFullKnowledgeStore()
        full_store.rows.append({
            "id": 1, "brand_id": 1, "version_no": 1,
            "content_markdown": "# 示例品牌\n\n## 产品信息\n\n### 产品A\n\nA介绍。\n\n### 产品B\n\nB介绍。\n\n## 保留章节\n\n原文保留。",
        })
        service = types.SimpleNamespace(_brands=application._deps.brands, _brand_full_knowledge=full_store, _settings=FakeSettings())

        async def generate(**kwargs):
            return await generate_full_brand_knowledge_markdown_from_update(service, **kwargs)

        handler = BrandFullKnowledgeRefreshJobHandler(
            deps=types.SimpleNamespace(
                brand_knowledge_update_audits=types.SimpleNamespace(list_unconsumed_for_full_knowledge=lambda **kwargs: audits),
                build_full_knowledge_from_update=generate,
            ),
            normalize_optional_str=lambda value: str(value).strip() if value else None,
            build_callback_payload=lambda **kwargs: {},
            post_callback_if_configured=AsyncMock(return_value={}),
        )
        with patch("knowledge_base.brand_knowledge.ai.rounds.call_anthropic_json", return_value={
            "operations": [{"op": "delete_section", "target_heading": "### 产品B", "content": ""}],
        }) as llm:
            refreshed = await handler.handle({"job_id": "refresh:1"}, {
                "brand_code": "BRAND-001", "brand_name": "示例品牌", "knowledge_revision": result["knowledge_revision"],
            })
        llm.assert_called_once()
        self.assertIn("change_type：`delete`", llm.call_args.args[0])
        self.assertIn("产品B", llm.call_args.args[0])
        self.assertEqual(
            refreshed["ai_knowledge_payload"]["knowledge_markdown"],
            "# 示例品牌\n\n## 产品信息\n\n### 产品A\n\nA介绍。\n\n## 保留章节\n\n原文保留。",
        )

    async def test_knowledge_update_manual_change_increments_patch_version(self) -> None:
        captured_build_calls: list[dict[str, object]] = []

        async def fake_build_next_brand_full_knowledge(**kwargs):
            captured_build_calls.append(kwargs)
            return {
                "knowledge_oss_url_md": "https://oss.example.com/ai_knowledge/update.md",
                "knowledge_oss_url_pdf": "https://oss.example.com/ai_knowledge/update.pdf",
            }

        application = _build_application(
            build_next_brand_full_knowledge=fake_build_next_brand_full_knowledge,
        )

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
                intro="更新后的简介",
            ),
        )

        result = await application.update_knowledge(request)

        self.assertRegex(result["knowledge_revision"], r"^LXKG-SLPP-V1\.0\.1-\d{14}$")
        self.assertEqual(captured_build_calls[0]["update_reason"], "knowledge_update")
        self.assertEqual(captured_build_calls[0]["change_origin"], "frontend")
        self.assertEqual(captured_build_calls[0]["deleted_sections"], [])
        structured_delta = str(captured_build_calls[0]["structured_knowledge_markdown"])
        self.assertIn("本次结构化知识变更", structured_delta)
        self.assertIn('"intro": "更新后的简介"', structured_delta)
        self.assertNotIn("核心产品介绍", structured_delta)

    async def test_knowledge_update_persists_structured_change_audits_to_store(self) -> None:
        audit_store = FakeBrandKnowledgeUpdateAuditStore()
        application = _build_application(
            brand_knowledge_update_audits=audit_store,
        )

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
                intro="更新后的简介",
            ),
            skip_full_ai_knowledge_sync=True,
        )

        result = await application.update_knowledge(request)

        self.assertEqual(len(audit_store.created_calls), 1)
        created_call = audit_store.created_calls[0]
        self.assertRegex(str(created_call["audit_id"]), r"^knowledge_update:[0-9a-f]{32}$")
        self.assertEqual(created_call["brand_id"], 1)
        self.assertEqual(created_call["brand_code"], "BRAND-001")
        self.assertEqual(created_call["brand_name"], "示例品牌")
        self.assertEqual(created_call["knowledge_revision"], result["knowledge_revision"])
        self.assertEqual(created_call["source_type"], "knowledge_update")
        self.assertRegex(str(created_call["source_task_id"]), r"^knowledge_update:[0-9a-f]{32}$")
        self.assertIsNone(created_call["source_job_id"])
        self.assertIsNone(created_call["source_name"])
        self.assertIsNone(created_call["source_oss_key"])
        self.assertEqual(
            created_call["entries"],
            [
                {
                    "section": "brands",
                    "title": "品牌基础信息",
                    "action": "update",
                    "before": {"intro": "品牌简介"},
                    "after": {"intro": "更新后的简介"},
                }
            ],
        )

    async def test_knowledge_update_only_persists_products_with_product_code_to_brand_products(self) -> None:
        application = _build_application()

        result = await application.update_knowledge(
            KnowledgeUpdateRequest(
                basic_info=KnowledgeBasicInfo(
                    brand_name="示例品牌",
                    brand_code="BRAND-001",
                ),
                products=[
                    KnowledgeProduct(
                        name="无编码产品",
                        product_description="不应写入 brand_products",
                    ),
                    KnowledgeProduct(
                        product_code="PROD-CODED",
                        name="有编码产品",
                        product_description="应写入 brand_products",
                    ),
                ],
                skip_full_ai_knowledge_sync=True,
            )
        )

        self.assertIn("products", result["updated_sections"])
        persisted_products = application._deps.brand_products.last_products_upsert["products"]
        self.assertEqual(len(persisted_products), 1)
        self.assertEqual(persisted_products[0]["product_code"], "PROD-CODED")
        self.assertEqual(persisted_products[0]["product_name"], "有编码产品")
        self.assertEqual(persisted_products[0]["product_description"], "应写入 brand_products")

    async def test_knowledge_update_skips_brand_products_upsert_when_products_have_no_product_code(self) -> None:
        application = _build_application()

        result = await application.update_knowledge(
            KnowledgeUpdateRequest(
                basic_info=KnowledgeBasicInfo(
                    brand_name="示例品牌",
                    brand_code="BRAND-001",
                ),
                products=[
                    KnowledgeProduct(
                        name="无编码产品A",
                        product_description="保留在本次知识变更里",
                    ),
                    KnowledgeProduct(
                        name="无编码产品B",
                        product_description="也不写入 brand_products",
                    ),
                ],
                skip_full_ai_knowledge_sync=True,
            )
        )

        self.assertIn("products", result["updated_sections"])
        self.assertIsNone(application._deps.brand_products.last_products_upsert)

    async def test_knowledge_update_enqueues_debounced_full_knowledge_refresh(self) -> None:
        enqueue_refresh = AsyncMock(
            return_value={
                "job_id": "bg:brand_full_knowledge_refresh:BRAND-001",
                "status": "waiting",
            }
        )
        settings = FakeSettings()
        settings.brand_full_knowledge_refresh_delay_seconds = 450
        application = _build_application(
            settings=settings,
            enqueue_brand_full_knowledge_refresh_job=enqueue_refresh,
        )

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
                intro="更新后的简介",
            ),
        )

        result = await application.update_knowledge(request)

        enqueue_refresh.assert_awaited_once()
        self.assertEqual("BRAND-001", enqueue_refresh.await_args.kwargs["brand_code"])
        self.assertEqual("示例品牌", enqueue_refresh.await_args.kwargs["brand_name"])
        self.assertEqual("knowledge_update", enqueue_refresh.await_args.kwargs["trigger_source_type"])
        self.assertRegex(str(enqueue_refresh.await_args.kwargs["trigger_source_task_id"]), r"^knowledge_update:[0-9a-f]{32}$")
        self.assertEqual(450, enqueue_refresh.await_args.kwargs["delay_seconds"])
        self.assertEqual("bg:brand_full_knowledge_refresh:BRAND-001", result["background_job_id"])
        self.assertEqual("waiting", result["background_job_status"])

    async def test_knowledge_update_does_not_fail_when_audit_write_fails(self) -> None:
        audit_store = FakeBrandKnowledgeUpdateAuditStore(should_raise=True)
        application = _build_application(
            brand_knowledge_update_audits=audit_store,
        )

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
                intro="更新后的简介",
            ),
            skip_full_ai_knowledge_sync=True,
        )

        result = await application.update_knowledge(request)

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(audit_store.created_calls), 0)

    def test_build_applications_wires_brand_knowledge_update_audit_store_into_brand_app(self) -> None:
        audit_store = FakeBrandKnowledgeUpdateAuditStore()
        kb_service = types.SimpleNamespace(
            _settings=FakeSettings(),
            _brands=FakeBrandStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _brand_full_knowledge=FakeBrandFullKnowledgeStore(),
            _brand_knowledge_facts=None,
            _brand_knowledge_ingestion_jobs=None,
            _brand_knowledge_update_audits=audit_store,
            _brand_knowledge_sessions=types.SimpleNamespace(),
            _document_alerts=types.SimpleNamespace(),
            _document_categories=FakeDocumentCategoryStore(),
            _document_registry=FakeDocumentRegistryStore(),
            _fact_relations=types.SimpleNamespace(),
            _industries=FakeIndustryStore(),
            _upload_tasks=FakeUploadTaskStore(),
            _background_jobs=None,
            _brand_attachment_assets=None,
            _parser=types.SimpleNamespace(),
            _embeddings=types.SimpleNamespace(dimension=3),
            _store=types.SimpleNamespace(),
            _runtime=types.SimpleNamespace(
                upload_queue=asyncio.Queue(),
                queued_task_ids=set(),
                queue_lock=asyncio.Lock(),
                background_job_queue=asyncio.Queue(),
                queued_background_job_ids=set(),
                background_job_queue_lock=asyncio.Lock(),
                inflight_brand_callbacks=set(),
                scheduled_brand_callback_retries=set(),
                scheduled_brand_completion_checks=set(),
                scheduled_attachment_conflict_callback_retries=set(),
                scheduled_attachment_confirm_callback_retries=set(),
                scheduled_attachment_delete_callback_retries=set(),
            ),
            _tianyancha_client=None,
            _spawn_background_task=_fake_spawn_background_task,
            _get_document_info=lambda _document_id: {},
            get_full_text=lambda _document_id: None,
            delete_document=AsyncMock(),
            ingest_from_url=AsyncMock(),
            delete_document_by_attachment_name=AsyncMock(),
            update_knowledge=AsyncMock(),
            oss_client=types.SimpleNamespace(enabled=True),
        )

        with patch("knowledge_base.composition.get_feishu_notifier", return_value=None):
            applications = build_applications(kb_service)

        self.assertIs(applications.brand_app._deps.brand_knowledge_update_audits, audit_store)
