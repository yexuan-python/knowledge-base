from __future__ import annotations

import asyncio
import hashlib
import sys
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from tests._stub_utils import ensure_stub_module


requests_stub = ensure_stub_module("requests")
if requests_stub is not None:
    requests_stub.post = lambda *args, **kwargs: None
    sys.modules.setdefault("requests", requests_stub)

qdrant_stub = ensure_stub_module("qdrant_client")
if qdrant_stub is not None:
    qdrant_stub.QdrantClient = type("QdrantClient", (), {})
    qdrant_stub.models = types.SimpleNamespace()
    sys.modules.setdefault("qdrant_client", qdrant_stub)

dashscope_stub = ensure_stub_module("dashscope")
if dashscope_stub is not None:
    dashscope_stub.Generation = type("Generation", (), {"call": staticmethod(lambda *args, **kwargs: None)})
    dashscope_stub.MultiModalConversation = type(
        "MultiModalConversation",
        (),
        {"call": staticmethod(lambda *args, **kwargs: None)},
    )
    dashscope_stub.MultiModalEmbedding = type(
        "MultiModalEmbedding",
        (),
        {"call": staticmethod(lambda *args, **kwargs: None)},
    )
    sys.modules.setdefault("dashscope", dashscope_stub)

from knowledge_base.background_jobs.application import (
    BackgroundJobDependencies,
    BackgroundJobService,
)
from knowledge_base.brand.full_markdown import generate_full_brand_knowledge_markdown_from_update
from tests.fakes.brand_flow import FakeBrandFullKnowledgeStore, FakeBrandStore, FakeSettings


class FakeUploadTaskStore:
    def __init__(self) -> None:
        self.callback_rows: dict[tuple[str, str], dict[str, object]] = {}

    def upsert_upload_task_callback(
        self,
        *,
        task_id: str,
        callback_type: str,
        callback_url: str,
        request_payload_json: dict | None,
        status: str,
    ) -> None:
        key = (task_id, callback_type)
        row = dict(self.callback_rows.get(key) or {})
        row.update(
            {
                "task_id": task_id,
                "callback_type": callback_type,
                "callback_url": callback_url,
                "status": status,
            }
        )
        if request_payload_json is not None:
            row["request_payload_json"] = request_payload_json
        row.setdefault("retry_count", 0)
        row.setdefault("next_retry_at", None)
        row.setdefault("last_response_code", None)
        row.setdefault("last_response_body", None)
        row.setdefault("last_error_message", None)
        row.setdefault("sent_at", None)
        self.callback_rows[key] = row

    def get_upload_task_callback(self, *, task_id: str, callback_type: str) -> dict | None:
        return self.callback_rows.get((task_id, callback_type))

    def update_upload_task_callback_result(self, **kwargs) -> None:
        key = (kwargs["task_id"], kwargs["callback_type"])
        row = dict(self.callback_rows.get(key) or {})
        row.update(kwargs)
        self.callback_rows[key] = row


class FakeMilvusRenameStore:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.rename_calls: list[dict[str, object]] = []

    def rename_brand(self, *, brand_code: str, old_brand_name: str, new_brand_name: str):
        self.rename_calls.append(
            {
                "brand_code": brand_code,
                "old_brand_name": old_brand_name,
                "new_brand_name": new_brand_name,
            }
        )
        if self.should_fail:
            raise RuntimeError("Milvus rename failed")
        return {"chunks": 2, "facts": 3}


class FakeBackgroundJobStore:
    def __init__(self, *, job: dict[str, object]) -> None:
        self.job = dict(job)
        self.mark_processing_calls: list[dict[str, object]] = []
        self.success_calls: list[dict[str, object]] = []
        self.retrying_calls: list[dict[str, object]] = []
        self.failed_calls: list[dict[str, object]] = []

    def mark_processing(self, *, job_id: str, worker_id: str) -> bool:
        self.mark_processing_calls.append({"job_id": job_id, "worker_id": worker_id})
        self.job["status"] = "processing"
        return True

    def get_job(self, job_id: str) -> dict | None:
        if self.job.get("job_id") != job_id:
            return None
        return dict(self.job)

    def mark_success(self, *, job_id: str, result_json: dict[str, object], worker_id: str) -> None:
        self.success_calls.append({"job_id": job_id, "result_json": result_json, "worker_id": worker_id})
        self.job["status"] = "success"
        self.job["result_json"] = result_json

    def mark_retrying(
        self,
        *,
        job_id: str,
        retry_count: int,
        next_retry_at: datetime,
        result_json: dict[str, object] | None,
        last_error_message: str | None,
        worker_id: str,
    ) -> None:
        self.retrying_calls.append(
            {
                "job_id": job_id,
                "retry_count": retry_count,
                "next_retry_at": next_retry_at,
                "result_json": result_json,
                "last_error_message": last_error_message,
                "worker_id": worker_id,
            }
        )
        self.job["status"] = "retrying"
        self.job["retry_count"] = retry_count
        self.job["next_retry_at"] = next_retry_at
        self.job["last_error_message"] = last_error_message

    def mark_failed(
        self,
        *,
        job_id: str,
        retry_count: int,
        result_json: dict[str, object] | None,
        last_error_message: str | None,
        worker_id: str,
    ) -> None:
        self.failed_calls.append(
            {
                "job_id": job_id,
                "retry_count": retry_count,
                "result_json": result_json,
                "last_error_message": last_error_message,
                "worker_id": worker_id,
            }
        )
        self.job["status"] = "failed"
        self.job["retry_count"] = retry_count
        self.job["last_error_message"] = last_error_message


class FakeEnqueueBackgroundJobStore:
    def __init__(self) -> None:
        self.upsert_calls: list[dict[str, object]] = []
        self.jobs: dict[str, dict[str, object]] = {}

    def upsert_job(self, **kwargs) -> dict[str, object]:
        self.upsert_calls.append(kwargs)
        job = {
            "job_id": kwargs["job_id"],
            "job_type": kwargs["job_type"],
            "source_type": kwargs["source_type"],
            "source_id": kwargs["source_id"],
            "status": kwargs["status"],
            "next_retry_at": kwargs.get("next_retry_at"),
        }
        self.jobs[str(kwargs["job_id"])] = job
        return dict(job)


class FakeResetBackgroundJobStore:
    def __init__(self, job_ids: list[str]) -> None:
        self.job_ids = job_ids
        self.reset_calls: list[dict[str, object]] = []

    def reset_processing_jobs(self, *, lock_timeout_seconds: int) -> list[str]:
        self.reset_calls.append({"lock_timeout_seconds": lock_timeout_seconds})
        return list(self.job_ids)


class FakeRefreshAuditStore:
    def __init__(self) -> None:
        self.audits = [
            {
                "id": 1,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "source_type": "knowledge_update",
                "source_task_id": "knowledge_update:abc",
                "source_job_id": None,
                "source_name": None,
                "source_oss_key": None,
                "section": "brands",
                "section_title": "品牌基础信息",
                "change_action": "update",
                "before_json": '{"intro": "旧简介"}',
                "after_json": '{"intro": "新简介"}',
            },
            {
                "id": 2,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "source_type": "attachment_confirm",
                "source_task_id": "confirm:bad_1:bar_1",
                "source_job_id": "bg:attachment_confirm_pipeline:confirm:bad_1:bar_1",
                "source_name": "示例品牌-bad_1-bar_1-confirmed-knowledge.md",
                "source_oss_key": "示例品牌/confirmed_knowledge/示例品牌-bad_1-bar_1-confirmed-knowledge.md",
                "section": "attachments",
                "section_title": "附件资料",
                "change_action": "update",
                "before_json": "[]",
                "after_json": '[{"name": "品牌手册.pdf"}]',
            },
        ]
        self.claim_calls: list[dict[str, object]] = []
        self.consume_calls: list[dict[str, object]] = []
        self.release_calls: list[dict[str, object]] = []

    def list_unconsumed_for_full_knowledge(self, *, brand_code: str, source_types: list[str]):
        return [
            audit
            for audit in self.audits
            if audit["brand_code"] == brand_code and audit["source_type"] in source_types
        ]

    def claim_for_full_knowledge(self, *, audit_ids: list[int], full_knowledge_job_id: str) -> int:
        self.claim_calls.append({"audit_ids": audit_ids, "full_knowledge_job_id": full_knowledge_job_id})
        return len(audit_ids)

    def mark_full_knowledge_consumed(self, *, audit_ids: list[int], full_knowledge_job_id: str) -> int:
        self.consume_calls.append({"audit_ids": audit_ids, "full_knowledge_job_id": full_knowledge_job_id})
        return len(audit_ids)

    def release_full_knowledge_claim(self, *, full_knowledge_job_id: str) -> int:
        self.release_calls.append({"full_knowledge_job_id": full_knowledge_job_id})
        return 1


class FakeRefreshOSSClient:
    enabled = True

    def __init__(self) -> None:
        self.read_keys: list[str] = []

    def get_object_text(self, object_key: str, encoding: str = "utf-8"):
        del encoding
        self.read_keys.append(object_key)
        return "# 附件确认稿\n这里是附件确认后的 Markdown"


class BackgroundJobCallbackAuditTests(unittest.IsolatedAsyncioTestCase):
    def _build_service(
        self,
        upload_tasks: FakeUploadTaskStore,
        *,
        background_jobs: FakeBackgroundJobStore | None = None,
        store: FakeMilvusRenameStore | None = None,
    ) -> BackgroundJobService:
        return BackgroundJobService(
            BackgroundJobDependencies(
                settings=types.SimpleNamespace(
                    brand_completion_callback_timeout_seconds=5.0,
                    background_job_lock_timeout_seconds=42,
                ),
                background_jobs=background_jobs or types.SimpleNamespace(),
                store=store,
                brands=types.SimpleNamespace(),
                upload_tasks=upload_tasks,
                build_full_knowledge_from_update=None,
                build_full_knowledge_from_confirmed_markdown=None,
                process_upload_task=None,
                queue=asyncio.Queue(),
                queued_job_ids=set(),
                queue_lock=asyncio.Lock(),
            )
        )

    async def test_enqueue_attachment_conflict_resolution_preserves_publish_mode(self) -> None:
        upload_tasks = FakeUploadTaskStore()
        background_jobs = FakeEnqueueBackgroundJobStore()
        service = self._build_service(upload_tasks, background_jobs=background_jobs)

        result = await service.enqueue_attachment_conflict_resolution(
            session_id="bks_123",
            brand_code="BR001",
            brand_name="测试品牌",
            source_task_id="task-1",
            submitted_round_no=1,
            generation_round_no=2,
            history_resolutions=[],
            current_resolutions=[{"conflict_id": "C-1", "decision": "choose_option"}],
            auto_merged=[],
            force_reingest=False,
            publish_mode="draft_only",
        )

        self.assertEqual(result["job_type"], "attachment_conflict_resolution")
        self.assertEqual(len(background_jobs.upsert_calls), 1)
        payload = background_jobs.upsert_calls[0]["payload_json"]
        self.assertEqual(payload["session_id"], "bks_123")
        self.assertEqual(payload["publish_mode"], "draft_only")
        self.assertEqual(payload["generation_round_no"], 2)

    async def test_attachment_confirm_callback_records_success(self) -> None:
        upload_tasks = FakeUploadTaskStore()
        service = self._build_service(upload_tasks)
        job = {
            "job_type": "attachment_confirm_full_generation",
            "source_id": "confirm:draft-1:review-1",
            "max_retries": 4,
        }
        payload = {
            "source_task_id": "confirm:draft-1:review-1",
            "callback_url": "https://callback.example.com",
        }
        callback_payload = {"brand_code": "BRAND-001"}
        original_post = BackgroundJobService._post_callback
        BackgroundJobService._post_callback = staticmethod(lambda *args, **kwargs: (200, "ok"))
        try:
            result = await service._post_callback_if_configured(
                job=job,
                payload=payload,
                callback_payload=callback_payload,
            )
        finally:
            BackgroundJobService._post_callback = original_post

        self.assertEqual(result["status"], "success")
        row = upload_tasks.get_upload_task_callback(
            task_id="confirm:draft-1:review-1",
            callback_type="brand_knowledge_completed",
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["request_payload_json"], callback_payload)
        self.assertEqual(row["last_response_code"], 200)
        self.assertEqual(row["last_response_body"], "ok")
        self.assertIsNone(row["last_error_message"])
        self.assertIsInstance(row["sent_at"], datetime)

    async def test_knowledge_update_callback_records_retrying_on_non_2xx(self) -> None:
        upload_tasks = FakeUploadTaskStore()
        service = self._build_service(upload_tasks)
        job = {
            "job_type": "brand_knowledge_update_full_generation",
            "source_id": "knowledge_update:418:rev-1",
            "max_retries": 4,
        }
        payload = {
            "source_task_id": "knowledge_update:418:rev-1",
            "callback_url": "https://callback.example.com",
        }
        callback_payload = {"brand_code": "BRAND-001"}
        original_post = BackgroundJobService._post_callback
        BackgroundJobService._post_callback = staticmethod(lambda *args, **kwargs: (404, "missing"))
        try:
            with self.assertRaisesRegex(RuntimeError, "callback response code=404"):
                await service._post_callback_if_configured(
                    job=job,
                    payload=payload,
                    callback_payload=callback_payload,
                )
        finally:
            BackgroundJobService._post_callback = original_post

        row = upload_tasks.get_upload_task_callback(
            task_id="knowledge_update:418:rev-1",
            callback_type="brand_knowledge_completed",
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "retrying")
        self.assertEqual(row["retry_count"], 1)
        self.assertEqual(row["last_response_code"], 404)
        self.assertEqual(row["last_response_body"], "missing")
        self.assertEqual(row["last_error_message"], "callback response code=404")
        self.assertIsInstance(row["next_retry_at"], datetime)

    async def test_knowledge_update_job_passes_structured_delta_to_generator(self) -> None:
        upload_tasks = FakeUploadTaskStore()
        service = self._build_service(upload_tasks)
        captured_kwargs: dict[str, object] = {}

        async def fake_build_full_knowledge_from_update(**kwargs):
            captured_kwargs.update(kwargs)
            return {
                "knowledge_oss_url_md": "https://oss.example.com/update.md",
                "knowledge_oss_url_pdf": "https://oss.example.com/update.pdf",
            }

        service._deps = types.SimpleNamespace(
            **{
                **service._deps.__dict__,
                "build_full_knowledge_from_update": fake_build_full_knowledge_from_update,
            }
        )
        job = {
            "job_type": "brand_knowledge_update_full_generation",
            "source_id": "knowledge_update:418:rev-1",
            "max_retries": 4,
        }
        payload = {
            "brand_code": "BRAND-001",
            "brand_name": "示例品牌",
            "knowledge_revision": "rev-1",
            "update_reason": "knowledge_update",
            "source_task_id": "knowledge_update:418:rev-1",
            "deleted_sections": [],
            "structured_knowledge_markdown": "# 本次结构化知识变更\n- intro",
            "knowledge_snapshot": {
                "basic_info": {
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                }
            },
        }

        result = await service._handle_brand_knowledge_update(job, payload)

        self.assertEqual(captured_kwargs["change_origin"], "frontend")
        self.assertEqual(
            captured_kwargs["structured_knowledge_markdown"],
            "# 本次结构化知识变更\n- intro",
        )
        self.assertEqual(result["ai_knowledge_payload"]["knowledge_oss_url_md"], "https://oss.example.com/update.md")

    async def test_knowledge_update_job_uses_patch_generation_when_base_markdown_exists(self) -> None:
        upload_tasks = FakeUploadTaskStore()
        service = self._build_service(upload_tasks)
        full_knowledge_store = FakeBrandFullKnowledgeStore()
        full_knowledge_store.rows.append(
            {
                "id": 1,
                "brand_id": 1,
                "brand_name": "示例品牌",
                "version_no": 1,
                "is_latest": True,
                "ingest_status": "success",
                "content_markdown": "# 示例品牌\n\n## 品牌基础信息\n旧简介\n\n## 联系方式\n旧电话",
            }
        )
        generator_service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_full_knowledge=full_knowledge_store,
            _settings=FakeSettings(),
        )

        async def build_full_knowledge_from_update(**kwargs):
            return await generate_full_brand_knowledge_markdown_from_update(
                generator_service,
                **kwargs,
            )

        patch_generator = AsyncMock(
            return_value={
                "final_markdown": "# 示例品牌\n\n## 品牌基础信息\n新版简介\n\n## 联系方式\n旧电话",
            }
        )
        full_generator = AsyncMock(side_effect=AssertionError("full generator should not be used"))
        service._deps = types.SimpleNamespace(
            **{
                **service._deps.__dict__,
                "build_full_knowledge_from_update": build_full_knowledge_from_update,
            }
        )
        job = {
            "job_type": "brand_knowledge_update_full_generation",
            "source_id": "knowledge_update:418:rev-1",
            "max_retries": 4,
        }
        payload = {
            "brand_code": "BRAND-001",
            "brand_name": "示例品牌",
            "knowledge_revision": "rev-1",
            "update_reason": "knowledge_update",
            "source_task_id": "knowledge_update:418:rev-1",
            "deleted_sections": [],
            "structured_knowledge_markdown": "# 本次结构化知识变更\n- intro: 新版简介",
            "knowledge_snapshot": {
                "basic_info": {
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                }
            },
        }

        with (
            patch(
                "knowledge_base.brand.full_markdown.generate_brand_ai_knowledge_patch_from_structured_update",
                patch_generator,
            ),
            patch(
                "knowledge_base.brand.full_markdown.generate_brand_ai_knowledge_from_structured_update",
                full_generator,
            ),
        ):
            result = await service._handle_brand_knowledge_update(job, payload)

        patch_generator.assert_awaited_once()
        full_generator.assert_not_awaited()
        ai_payload = result["ai_knowledge_payload"]
        self.assertEqual(ai_payload["knowledge_markdown"], "# 示例品牌\n\n## 品牌基础信息\n新版简介\n\n## 联系方式\n旧电话")
        self.assertEqual(ai_payload["version_no"], 2)
        self.assertIn("旧电话", ai_payload["knowledge_markdown"])

    async def test_enqueue_brand_full_knowledge_refresh_debounces_without_immediate_queueing(self) -> None:
        background_jobs = FakeEnqueueBackgroundJobStore()
        queue: asyncio.Queue[str] = asyncio.Queue()
        service = BackgroundJobService(
            BackgroundJobDependencies(
                settings=types.SimpleNamespace(
                    brand_completion_callback_timeout_seconds=5.0,
                    background_job_lock_timeout_seconds=42,
                ),
                background_jobs=background_jobs,
                store=types.SimpleNamespace(),
                brands=types.SimpleNamespace(),
                upload_tasks=types.SimpleNamespace(),
                build_full_knowledge_from_update=None,
                build_full_knowledge_from_confirmed_markdown=None,
                process_upload_task=None,
                queue=queue,
                queued_job_ids=set(),
                queue_lock=asyncio.Lock(),
            )
        )

        before = datetime.now()
        job = await service.enqueue_brand_full_knowledge_refresh(
            brand_code="BRAND-001",
            brand_name="示例品牌",
            trigger_source_type="attachment_confirm",
            trigger_source_task_id="confirm:bad_1:bar_1",
            knowledge_revision="LXKG-SLPP-V1.0.1-20260630020202",
            delay_seconds=120,
        )
        after = datetime.now()

        self.assertEqual("bg:brand_full_knowledge_refresh:BRAND-001", job["job_id"])
        self.assertEqual(queue.qsize(), 0)
        self.assertEqual(len(background_jobs.upsert_calls), 1)
        call = background_jobs.upsert_calls[0]
        self.assertEqual("brand_full_knowledge_refresh", call["job_type"])
        self.assertEqual("BRAND-001", call["source_id"])
        self.assertFalse(call["reopen_terminal"])
        self.assertTrue(call["restart_completed"])
        self.assertGreaterEqual(call["next_retry_at"], before + timedelta(seconds=120))
        self.assertLessEqual(call["next_retry_at"], after + timedelta(seconds=120))

    async def test_reset_processing_jobs_releases_interrupted_full_refresh_claims(self) -> None:
        background_jobs = FakeResetBackgroundJobStore(
            [
                "bg:brand_full_knowledge_refresh:BRAND-001",
                "bg:brand_rename_milvus_sync:BRAND-001:示例品牌",
            ]
        )
        audit_store = FakeRefreshAuditStore()
        service = BackgroundJobService(
            BackgroundJobDependencies(
                settings=types.SimpleNamespace(
                    brand_completion_callback_timeout_seconds=5.0,
                    background_job_lock_timeout_seconds=42,
                ),
                background_jobs=background_jobs,
                store=types.SimpleNamespace(),
                brands=types.SimpleNamespace(),
                upload_tasks=FakeUploadTaskStore(),
                build_full_knowledge_from_update=None,
                build_full_knowledge_from_confirmed_markdown=None,
                process_upload_task=None,
                queue=asyncio.Queue(),
                queued_job_ids=set(),
                queue_lock=asyncio.Lock(),
                brand_knowledge_update_audits=audit_store,
            )
        )

        reset_ids = service.reset_processing_jobs()

        self.assertEqual(
            [
                "bg:brand_full_knowledge_refresh:BRAND-001",
                "bg:brand_rename_milvus_sync:BRAND-001:示例品牌",
            ],
            reset_ids,
        )
        self.assertEqual(background_jobs.reset_calls, [{"lock_timeout_seconds": 42}])
        self.assertEqual(
            [{"full_knowledge_job_id": "bg:brand_full_knowledge_refresh:BRAND-001"}],
            audit_store.release_calls,
        )

    async def test_process_job_marks_success_with_current_worker_lock(self) -> None:
        upload_tasks = FakeUploadTaskStore()
        background_jobs = FakeBackgroundJobStore(
            job={
                "job_id": "bg:brand_rename_milvus_sync:BRAND-001:珠海示例品牌",
                "job_type": "brand_rename_milvus_sync",
                "source_id": "BRAND-001:珠海示例品牌",
                "status": "waiting",
                "retry_count": 0,
                "max_retries": 8,
                "payload_json": {
                    "brand_id": 1,
                    "brand_code": "BRAND-001",
                    "old_brand_name": "示例品牌",
                    "brand_name": "珠海示例品牌",
                },
            }
        )
        milvus_store = FakeMilvusRenameStore(should_fail=False)
        service = self._build_service(upload_tasks, background_jobs=background_jobs, store=milvus_store)

        await service.process_job("bg:brand_rename_milvus_sync:BRAND-001:珠海示例品牌")

        worker_id = background_jobs.mark_processing_calls[0]["worker_id"]
        self.assertEqual(len(background_jobs.success_calls), 1)
        self.assertEqual(background_jobs.success_calls[0]["worker_id"], worker_id)

    async def test_brand_full_knowledge_refresh_consumes_update_and_attachment_audits(self) -> None:
        upload_tasks = FakeUploadTaskStore()
        audit_store = FakeRefreshAuditStore()
        oss_client = FakeRefreshOSSClient()
        service = self._build_service(upload_tasks)
        captured_kwargs: dict[str, object] = {}

        async def fake_build_full_knowledge_from_update(**kwargs):
            captured_kwargs.update(kwargs)
            return {
                "knowledge_oss_url_md": "https://oss.example.com/ai_knowledge/refresh.md",
                "knowledge_oss_url_pdf": "https://oss.example.com/ai_knowledge/refresh.pdf",
            }

        service._deps = types.SimpleNamespace(
            **{
                **service._deps.__dict__,
                "brand_knowledge_update_audits": audit_store,
                "oss_client": oss_client,
                "build_full_knowledge_from_update": fake_build_full_knowledge_from_update,
            }
        )
        job = {
            "job_id": "bg:brand_full_knowledge_refresh:BRAND-001",
            "job_type": "brand_full_knowledge_refresh",
            "source_id": "BRAND-001",
            "max_retries": 4,
        }
        payload = {
            "brand_code": "BRAND-001",
            "brand_name": "示例品牌",
            "knowledge_revision": "LXKG-SLPP-V1.0.1-20260630020202",
            "source_types": ["knowledge_update", "attachment_confirm"],
            "callback_url": "",
        }

        result = await service._handle_brand_full_knowledge_refresh(job, payload)

        self.assertEqual(result["consumed_audit_count"], 2)
        self.assertEqual(
            oss_client.read_keys,
            ["示例品牌/confirmed_knowledge/示例品牌-bad_1-bar_1-confirmed-knowledge.md"],
        )
        structured_markdown = str(captured_kwargs["structured_knowledge_markdown"])
        self.assertIn("knowledge_update: 1 条", structured_markdown)
        self.assertIn("attachment_confirm: 1 条", structured_markdown)
        self.assertIn("- section：`brands`", structured_markdown)
        self.assertIn("- change_type：`update`", structured_markdown)
        self.assertIn("变更前内容：", structured_markdown)
        self.assertIn("本次更新后的内容：", structured_markdown)
        self.assertIn("# 附件确认稿", structured_markdown)
        self.assertEqual(captured_kwargs["update_reason"], "brand_full_knowledge_refresh")
        self.assertEqual(captured_kwargs["change_origin"], "frontend")
        self.assertEqual(result["change_origin"], "frontend")
        expected_batch_hash = hashlib.sha256(
            "\n".join(
                [
                    "1|knowledge_update|knowledge_update:abc|brands|update",
                    "2|attachment_confirm|confirm:bad_1:bar_1|attachments|update",
                ]
            ).encode("utf-8")
        ).hexdigest()[:16]
        self.assertEqual(
            captured_kwargs["source_task_id"],
            f"bg:brand_full_knowledge_refresh:BRAND-001:LXKG-SLPP-V1.0.1-20260630020202:{expected_batch_hash}",
        )
        self.assertEqual(audit_store.claim_calls[0]["audit_ids"], [1, 2])
        self.assertEqual(audit_store.consume_calls[0]["audit_ids"], [1, 2])
        self.assertEqual(audit_store.release_calls, [])

    def test_brand_full_knowledge_refresh_resolves_change_origin_from_audit_sources(self) -> None:
        cases = [
            (["knowledge_update"], "frontend"),
            (["knowledge_update", "attachment_confirm"], "frontend"),
            (["attachment_confirm"], "api"),
            (["frontend"], "frontend"),
            ([], "frontend"),
        ]
        for source_types, expected_origin in cases:
            with self.subTest(source_types=source_types):
                self.assertEqual(
                    BackgroundJobService._resolve_full_knowledge_change_origin_from_audits(
                        [{"source_type": source_type} for source_type in source_types]
                    ),
                    expected_origin,
                )

    async def test_brand_full_knowledge_refresh_delete_sections_require_empty_after_json(self) -> None:
        deleted_sections = BackgroundJobService._deleted_sections_from_audits(
            [
                {
                    "section": "management_team",
                    "change_action": "delete",
                    "before_json": '[{"name": "江浩辰", "bio": "旧"}]',
                    "after_json": '[{"name": "江浩辰", "bio": "新"}]',
                },
                {
                    "section": "competitors",
                    "change_action": "delete",
                    "before_json": '[{"name": "旧竞品"}]',
                    "after_json": "[]",
                },
            ]
        )

        self.assertEqual(deleted_sections, ["competitors"])

    async def test_brand_full_knowledge_refresh_records_completion_callback(self) -> None:
        upload_tasks = FakeUploadTaskStore()
        audit_store = FakeRefreshAuditStore()
        service = self._build_service(upload_tasks)

        async def fake_build_full_knowledge_from_update(**_kwargs):
            return {
                "knowledge_oss_url_md": "https://oss.example.com/ai_knowledge/refresh.md",
                "knowledge_oss_url_pdf": "https://oss.example.com/ai_knowledge/refresh.pdf",
            }

        service._deps = types.SimpleNamespace(
            **{
                **service._deps.__dict__,
                "brand_knowledge_update_audits": audit_store,
                "build_full_knowledge_from_update": fake_build_full_knowledge_from_update,
            }
        )
        original_post = BackgroundJobService._post_callback
        BackgroundJobService._post_callback = staticmethod(lambda *args, **kwargs: (200, "ok"))
        try:
            await service._handle_brand_full_knowledge_refresh(
                {
                    "job_id": "bg:brand_full_knowledge_refresh:BRAND-001",
                    "job_type": "brand_full_knowledge_refresh",
                    "source_id": "BRAND-001",
                    "max_retries": 4,
                },
                {
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "knowledge_revision": "LXKG-SLPP-V1.0.1-20260630020202",
                    "source_types": ["knowledge_update", "attachment_confirm"],
                    "callback_url": "https://callback.example.com",
                },
            )
        finally:
            BackgroundJobService._post_callback = original_post

        row = upload_tasks.get_upload_task_callback(
            task_id="bg:brand_full_knowledge_refresh:BRAND-001",
            callback_type="brand_knowledge_completed",
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["last_response_code"], 200)
        self.assertEqual(row["last_response_body"], "ok")

    async def test_brand_rename_job_retries_on_milvus_failure(self) -> None:
        upload_tasks = FakeUploadTaskStore()
        background_jobs = FakeBackgroundJobStore(
            job={
                "job_id": "bg:brand_rename_milvus_sync:BRAND-001:珠海示例品牌",
                "job_type": "brand_rename_milvus_sync",
                "source_id": "BRAND-001:珠海示例品牌",
                "status": "waiting",
                "retry_count": 0,
                "max_retries": 8,
                "payload_json": {
                    "brand_id": 1,
                    "brand_code": "BRAND-001",
                    "old_brand_name": "示例品牌",
                    "brand_name": "珠海示例品牌",
                },
            }
        )
        milvus_store = FakeMilvusRenameStore(should_fail=True)
        service = self._build_service(upload_tasks, background_jobs=background_jobs, store=milvus_store)

        await service.process_job("bg:brand_rename_milvus_sync:BRAND-001:珠海示例品牌")

        self.assertEqual(
            milvus_store.rename_calls,
            [
                {
                    "brand_code": "BRAND-001",
                    "old_brand_name": "示例品牌",
                    "new_brand_name": "珠海示例品牌",
                }
            ],
        )
        self.assertEqual(len(background_jobs.retrying_calls), 1)
        self.assertEqual(background_jobs.retrying_calls[0]["job_id"], "bg:brand_rename_milvus_sync:BRAND-001:珠海示例品牌")
        self.assertEqual(background_jobs.retrying_calls[0]["retry_count"], 1)
        self.assertEqual(background_jobs.retrying_calls[0]["last_error_message"], "Milvus rename failed")
        self.assertEqual(
            background_jobs.retrying_calls[0]["worker_id"],
            background_jobs.mark_processing_calls[0]["worker_id"],
        )
        self.assertEqual(background_jobs.success_calls, [])


if __name__ == "__main__":
    unittest.main()
