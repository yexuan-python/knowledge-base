from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable
from uuid import uuid4

from knowledge_base.background_jobs.brand_full_knowledge_refresh import BrandFullKnowledgeRefreshJobHandler
from knowledge_base.background_jobs.retry_policy import (
    DEFAULT_RETRY_DELAYS_SECONDS,
    BackgroundJobRetryPolicy,
)
from knowledge_base.shared.callback_delivery import deliver_upload_task_callback
from knowledge_base.shared.http import post_json_text_response
from knowledge_base.shared.utils import parse_metadata_json
from knowledge_base.upload_task.application.lifecycle import UploadTaskLifecycle

try:
    from knowledge_base.brand.callback_mapper import format_brand_callback_knowledge_from_snapshot
except ImportError:  # pragma: no cover - keeps background job unit tests independent of optional infra deps
    def format_brand_callback_knowledge_from_snapshot(*, brand: dict[str, Any], knowledge_snapshot: dict[str, Any]):
        return {
            "basic_info": {
                **(knowledge_snapshot.get("basic_info") or {}),
                "brand_code": brand.get("brand_code"),
                "brand_name": brand.get("brand_name"),
            }
        }


logger = logging.getLogger(__name__)

JOB_TYPE_BRAND_KNOWLEDGE_UPDATE = "brand_knowledge_update_full_generation"
JOB_TYPE_BRAND_FULL_KNOWLEDGE_REFRESH = "brand_full_knowledge_refresh"
JOB_TYPE_BRAND_RENAME_MILVUS_SYNC = "brand_rename_milvus_sync"
JOB_TYPE_ATTACHMENT_CONFIRM_PIPELINE = "attachment_confirm_pipeline"
JOB_TYPE_ATTACHMENT_CONFIRM = "attachment_confirm_full_generation"
JOB_TYPE_ATTACHMENT_CONFLICT_RESOLUTION = "attachment_conflict_resolution"
JOB_TYPE_UPLOAD_TASK_PROCESS = "upload_task_process"
CALLBACK_TYPE_BRAND_KNOWLEDGE = "brand_knowledge_completed"
SOURCE_TYPE_BRAND_KNOWLEDGE = "brand_knowledge"
SOURCE_TYPE_UPLOAD_TASK = "upload_task"
_RETRY_DELAYS_SECONDS = DEFAULT_RETRY_DELAYS_SECONDS
_WORKER_IDLE_SECONDS = 5

BackgroundJobHandler = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class BackgroundJobDependencies:
    settings: Any
    background_jobs: Any
    brands: Any
    upload_tasks: Any
    build_full_knowledge_from_update: Any
    build_full_knowledge_from_confirmed_markdown: Any
    process_upload_task: Any
    queue: asyncio.Queue[str]
    queued_job_ids: set[str]
    queue_lock: asyncio.Lock
    store: Any = None
    process_attachment_confirm_pipeline: Any = None
    process_attachment_conflict_resolution: Any = None
    build_current_brand_callback_knowledge: Any = None
    brand_knowledge_update_audits: Any = None
    oss_client: Any = None


class BackgroundJobService:
    def __init__(self, dependencies: BackgroundJobDependencies) -> None:
        self._deps = dependencies
        self._worker_id = f"background-worker:{uuid4().hex}"
        self._retry_policy = BackgroundJobRetryPolicy(retry_delays_seconds=_RETRY_DELAYS_SECONDS)
        self._handlers: dict[str, BackgroundJobHandler] = {
            JOB_TYPE_BRAND_KNOWLEDGE_UPDATE: self._handle_brand_knowledge_update,
            JOB_TYPE_BRAND_FULL_KNOWLEDGE_REFRESH: self._handle_brand_full_knowledge_refresh,
            JOB_TYPE_BRAND_RENAME_MILVUS_SYNC: self._handle_brand_rename_milvus_sync,
            JOB_TYPE_ATTACHMENT_CONFIRM_PIPELINE: self._handle_attachment_confirm_pipeline,
            JOB_TYPE_ATTACHMENT_CONFIRM: self._handle_attachment_confirm,
            JOB_TYPE_ATTACHMENT_CONFLICT_RESOLUTION: self._handle_attachment_conflict_resolution,
            JOB_TYPE_UPLOAD_TASK_PROCESS: self._handle_upload_task_process,
        }

    @staticmethod
    def _normalize_optional_str(value: Any) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @staticmethod
    def _source_job_id(*, job_type: str, source_id: str) -> str:
        candidate = f"bg:{job_type}:{source_id}"
        return candidate[:128] if len(candidate) <= 128 else f"bg:{uuid4().hex}"

    async def enqueue_brand_knowledge_update(
        self,
        *,
        brand_id: int | None,
        brand_code: str | None,
        brand_name: str,
        knowledge_revision: str | None,
        update_reason: str,
        source_task_id: str,
        deleted_sections: list[str] | None = None,
        structured_knowledge_markdown: str | None = None,
        knowledge_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "brand_id": brand_id,
            "brand_code": brand_code,
            "brand_name": brand_name,
            "knowledge_revision": knowledge_revision,
            "update_reason": update_reason,
            "source_task_id": source_task_id,
            "deleted_sections": deleted_sections or [],
            "structured_knowledge_markdown": str(structured_knowledge_markdown or "").strip(),
            "knowledge_snapshot": knowledge_snapshot or {},
            "callback_url": str(getattr(self._deps.settings, "brand_completion_callback_url", "") or "").strip(),
        }
        return await self.enqueue(
            job_type=JOB_TYPE_BRAND_KNOWLEDGE_UPDATE,
            source_type=SOURCE_TYPE_BRAND_KNOWLEDGE,
            source_id=source_task_id,
            payload=payload,
        )

    async def enqueue_brand_full_knowledge_refresh(
        self,
        *,
        brand_code: str,
        brand_name: str,
        trigger_source_type: str,
        trigger_source_task_id: str | None,
        knowledge_revision: str | None,
        delay_seconds: int = 120,
        source_types: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized_brand_code = self._normalize_optional_str(brand_code)
        normalized_brand_name = self._normalize_optional_str(brand_name)
        if not normalized_brand_code:
            raise ValueError("brand_code 不能为空")
        if not normalized_brand_name:
            raise ValueError("brand_name 不能为空")
        normalized_trigger_source_type = self._normalize_optional_str(trigger_source_type)
        default_source_types = ["knowledge_update", "attachment_confirm"]
        if normalized_trigger_source_type and normalized_trigger_source_type not in default_source_types:
            default_source_types.append(normalized_trigger_source_type)
        normalized_source_types = [
            item
            for item in (source_types or default_source_types)
            if self._normalize_optional_str(item)
        ]
        if not normalized_source_types:
            normalized_source_types = ["knowledge_update", "attachment_confirm"]
        payload = {
            "brand_code": normalized_brand_code,
            "brand_name": normalized_brand_name,
            "knowledge_revision": self._normalize_optional_str(knowledge_revision),
            "trigger_source_type": normalized_trigger_source_type,
            "trigger_source_task_id": self._normalize_optional_str(trigger_source_task_id),
            "source_types": normalized_source_types,
            "delay_seconds": int(delay_seconds),
            "callback_url": str(getattr(self._deps.settings, "brand_completion_callback_url", "") or "").strip(),
        }
        return await self.enqueue(
            job_type=JOB_TYPE_BRAND_FULL_KNOWLEDGE_REFRESH,
            source_type=SOURCE_TYPE_BRAND_KNOWLEDGE,
            source_id=normalized_brand_code,
            payload=payload,
            next_retry_at=datetime.now() + timedelta(seconds=max(0, int(delay_seconds))),
            reopen_terminal=False,
            restart_completed=True,
        )

    async def enqueue_brand_rename_milvus_sync(
        self,
        *,
        brand_id: int | None,
        brand_code: str,
        old_brand_name: str,
        brand_name: str,
    ) -> dict[str, Any]:
        normalized_brand_code = self._normalize_optional_str(brand_code)
        normalized_old_brand_name = self._normalize_optional_str(old_brand_name)
        normalized_brand_name = self._normalize_optional_str(brand_name)
        if not normalized_brand_code:
            raise ValueError("brand_code 不能为空")
        if not normalized_brand_name:
            raise ValueError("brand_name 不能为空")
        source_id = f"{normalized_brand_code}:{normalized_brand_name}"
        payload = {
            "brand_id": brand_id,
            "brand_code": normalized_brand_code,
            "old_brand_name": normalized_old_brand_name,
            "brand_name": normalized_brand_name,
        }
        return await self.enqueue(
            job_type=JOB_TYPE_BRAND_RENAME_MILVUS_SYNC,
            source_type="brand_rename",
            source_id=source_id,
            payload=payload,
            max_retries=8,
        )

    async def enqueue_attachment_confirm(
        self,
        *,
        brand: dict[str, Any],
        merged_snapshot: dict[str, Any],
        knowledge_revision: str | None,
        confirmed_markdown: str,
        source_task_id: str,
    ) -> dict[str, Any]:
        basic_info = merged_snapshot.get("basic_info") if isinstance(merged_snapshot.get("basic_info"), dict) else {}
        brand_code = self._normalize_optional_str(basic_info.get("brand_code")) or self._normalize_optional_str(
            brand.get("brand_code")
        )
        brand_name = self._normalize_optional_str(brand.get("brand_name")) or self._normalize_optional_str(
            basic_info.get("brand_name")
        )
        if not brand_name:
            raise ValueError("brand_name 不能为空")
        payload = {
            "brand": brand,
            "brand_id": brand.get("id"),
            "brand_code": brand_code,
            "brand_name": brand_name,
            "knowledge_revision": knowledge_revision,
            "merged_snapshot": merged_snapshot,
            "confirmed_markdown": confirmed_markdown,
            "source_task_id": source_task_id,
            "callback_url": str(getattr(self._deps.settings, "brand_completion_callback_url", "") or "").strip(),
        }
        return await self.enqueue(
            job_type=JOB_TYPE_ATTACHMENT_CONFIRM,
            source_type=SOURCE_TYPE_BRAND_KNOWLEDGE,
            source_id=source_task_id,
            payload=payload,
        )

    async def enqueue_attachment_confirm_pipeline(
        self,
        *,
        draft_id: str,
        review_id: str,
        brand_name: str,
        brand_code: str | None,
        knowledge_revision: str | None,
        request_payload: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_draft_id = str(draft_id or "").strip()
        normalized_review_id = str(review_id or "").strip()
        normalized_brand_name = str(brand_name or "").strip()
        if not normalized_draft_id:
            raise ValueError("draft_id 不能为空")
        if not normalized_review_id:
            raise ValueError("review_id 不能为空")
        if not normalized_brand_name:
            raise ValueError("brand_name 不能为空")
        source_task_id = f"confirm:{normalized_draft_id}:{normalized_review_id}"
        payload = {
            "draft_id": normalized_draft_id,
            "review_id": normalized_review_id,
            "brand_code": self._normalize_optional_str(brand_code),
            "brand_name": normalized_brand_name,
            "knowledge_revision": self._normalize_optional_str(knowledge_revision),
            "request_payload": request_payload,
            "source_task_id": source_task_id,
            "callback_url": str(getattr(self._deps.settings, "brand_completion_callback_url", "") or "").strip(),
        }
        return await self.enqueue(
            job_type=JOB_TYPE_ATTACHMENT_CONFIRM_PIPELINE,
            source_type=SOURCE_TYPE_BRAND_KNOWLEDGE,
            source_id=source_task_id,
            payload=payload,
        )

    async def enqueue_attachment_conflict_resolution(
        self,
        *,
        session_id: str,
        brand_code: str | None,
        brand_name: str,
        source_task_id: str | None,
        submitted_round_no: int,
        generation_round_no: int,
        history_resolutions: list[dict[str, Any]] | None,
        current_resolutions: list[dict[str, Any]] | None,
        auto_merged: list[dict[str, Any]] | None,
        force_reingest: bool,
        publish_mode: str | None = None,
    ) -> dict[str, Any]:
        normalized_session_id = str(session_id or "").strip()
        normalized_brand_name = str(brand_name or "").strip()
        if not normalized_session_id:
            raise ValueError("session_id 不能为空")
        if not normalized_brand_name:
            raise ValueError("brand_name 不能为空")
        payload = {
            "session_id": normalized_session_id,
            "brand_code": self._normalize_optional_str(brand_code),
            "brand_name": normalized_brand_name,
            "source_task_id": self._normalize_optional_str(source_task_id),
            "submitted_round_no": int(submitted_round_no),
            "generation_round_no": int(generation_round_no),
            "history_resolutions": history_resolutions or [],
            "current_resolutions": current_resolutions or [],
            "auto_merged": auto_merged or [],
            "force_reingest": bool(force_reingest),
            "publish_mode": str(publish_mode or "").strip() or None,
            "callback_url": str(getattr(self._deps.settings, "brand_completion_callback_url", "") or "").strip(),
        }
        return await self.enqueue(
            job_type=JOB_TYPE_ATTACHMENT_CONFLICT_RESOLUTION,
            source_type=SOURCE_TYPE_BRAND_KNOWLEDGE,
            source_id=normalized_session_id,
            payload=payload,
        )

    async def enqueue_upload_task_process(self, task_id: str) -> dict[str, Any]:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            raise ValueError("task_id 不能为空")
        return await self.enqueue(
            job_type=JOB_TYPE_UPLOAD_TASK_PROCESS,
            source_type=SOURCE_TYPE_UPLOAD_TASK,
            source_id=normalized_task_id,
            payload={"task_id": normalized_task_id},
            max_retries=0,
        )

    async def enqueue(
        self,
        *,
        job_type: str,
        source_type: str | None,
        source_id: str | None,
        payload: dict[str, Any],
        priority: int = 100,
        max_retries: int = len(_RETRY_DELAYS_SECONDS),
        next_retry_at: datetime | None = None,
        reopen_terminal: bool = False,
        restart_completed: bool = False,
    ) -> dict[str, Any]:
        job_id = self._source_job_id(job_type=job_type, source_id=source_id or uuid4().hex)
        job = self._deps.background_jobs.upsert_job(
            job_id=job_id,
            job_type=job_type,
            source_type=source_type,
            source_id=source_id,
            payload_json=payload,
            priority=priority,
            max_retries=max_retries,
            status="waiting",
            next_retry_at=next_retry_at,
            reopen_terminal=reopen_terminal,
            restart_completed=restart_completed,
        )
        if next_retry_at is None or next_retry_at <= datetime.now():
            await self.schedule_job(str(job.get("job_id") or job_id))
        return job

    async def schedule_job(self, job_id: str) -> None:
        async with self._deps.queue_lock:
            if job_id in self._deps.queued_job_ids:
                return
            self._deps.queued_job_ids.add(job_id)
            await self._deps.queue.put(job_id)

    async def schedule_due_jobs(self) -> None:
        for job in self._deps.background_jobs.list_due_jobs():
            job_id = str(job.get("job_id") or "").strip()
            if job_id:
                await self.schedule_job(job_id)

    def reset_processing_jobs(self) -> list[str]:
        lock_timeout_seconds = int(getattr(self._deps.settings, "background_job_lock_timeout_seconds", 1800) or 1800)
        reset_job_ids = list(
            self._deps.background_jobs.reset_processing_jobs(
                lock_timeout_seconds=max(lock_timeout_seconds, 1),
            )
        )
        audit_store = getattr(self._deps, "brand_knowledge_update_audits", None)
        if audit_store is None or not hasattr(audit_store, "release_full_knowledge_claim"):
            return reset_job_ids

        refresh_prefix = f"bg:{JOB_TYPE_BRAND_FULL_KNOWLEDGE_REFRESH}:"
        for job_id in reset_job_ids:
            normalized_job_id = str(job_id or "").strip()
            if normalized_job_id.startswith(refresh_prefix):
                audit_store.release_full_knowledge_claim(full_knowledge_job_id=normalized_job_id)
        return reset_job_ids

    async def worker(self) -> None:
        while True:
            try:
                job_id = await asyncio.wait_for(self._deps.queue.get(), timeout=_WORKER_IDLE_SECONDS)
            except asyncio.TimeoutError:
                await self.schedule_due_jobs()
                continue
            async with self._deps.queue_lock:
                self._deps.queued_job_ids.discard(job_id)
            try:
                await self.process_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Background job failed unexpectedly job_id=%s", job_id)
            finally:
                self._deps.queue.task_done()

    async def process_job(self, job_id: str) -> None:
        if not self._deps.background_jobs.mark_processing(job_id=job_id, worker_id=self._worker_id):
            return
        job = self._deps.background_jobs.get_job(job_id)
        if not job:
            return
        result_payload: dict[str, Any] | None = None
        job_type = str(job.get("job_type") or "")
        try:
            payload = parse_metadata_json(job.get("payload_json"))
            handler = self._handlers.get(job_type)
            if handler is None:
                raise ValueError(f"Unsupported background job_type={job_type}")
            result_payload = await handler(job, payload)
            self._deps.background_jobs.mark_success(
                job_id=job_id,
                result_json=result_payload,
                worker_id=self._worker_id,
            )
            if (
                job_type == JOB_TYPE_BRAND_FULL_KNOWLEDGE_REFRESH
                and int((result_payload or {}).get("pending_audit_count_after") or 0) > 0
            ):
                await self.enqueue_brand_full_knowledge_refresh(
                    brand_code=str(payload.get("brand_code") or ""),
                    brand_name=str(payload.get("brand_name") or ""),
                    trigger_source_type="pending_audits_after_refresh",
                    trigger_source_task_id=job_id,
                    knowledge_revision=self._normalize_optional_str(payload.get("knowledge_revision")),
                    delay_seconds=int(payload.get("delay_seconds") or 120),
                    source_types=payload.get("source_types") or None,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Background job attempt failed job_id=%s error=%s", job_id, exc, exc_info=True)
            retry_decision = self._retry_policy.decide(job=job)
            if retry_decision.should_retry:
                self._deps.background_jobs.mark_retrying(
                    job_id=job_id,
                    retry_count=retry_decision.retry_count,
                    next_retry_at=retry_decision.next_retry_at,
                    result_json=result_payload,
                    last_error_message=str(exc),
                    worker_id=self._worker_id,
                )
            else:
                self._deps.background_jobs.mark_failed(
                    job_id=job_id,
                    retry_count=retry_decision.retry_count,
                    result_json=result_payload,
                    last_error_message=str(exc),
                    worker_id=self._worker_id,
                )

    async def _handle_brand_knowledge_update(
        self,
        job: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        brand_name = str(payload.get("brand_name") or "").strip()
        source_task_id = str(payload.get("source_task_id") or job.get("source_id") or "").strip()
        ai_knowledge_payload = await self._deps.build_full_knowledge_from_update(
            brand_name=brand_name,
            update_reason=str(payload.get("update_reason") or "knowledge_update"),
            source_task_id=source_task_id,
            change_origin="frontend",
            knowledge_revision=self._normalize_optional_str(payload.get("knowledge_revision")),
            deleted_sections=payload.get("deleted_sections") or [],
            structured_knowledge_markdown=str(payload.get("structured_knowledge_markdown") or "").strip(),
        )
        callback_payload = self._build_callback_payload(
            brand_code=self._normalize_optional_str(payload.get("brand_code")),
            knowledge_revision=self._normalize_optional_str(payload.get("knowledge_revision")),
            ai_knowledge_payload=ai_knowledge_payload,
        )
        knowledge_snapshot = payload.get("knowledge_snapshot")
        if isinstance(knowledge_snapshot, dict) and knowledge_snapshot:
            brand = self._resolve_brand(payload=payload)
            callback_payload["knowledge"] = format_brand_callback_knowledge_from_snapshot(
                brand=brand or {},
                knowledge_snapshot=knowledge_snapshot,
            )
        if not isinstance(callback_payload.get("knowledge"), dict) or not callback_payload.get("knowledge"):
            raise ValueError("brand knowledge completed callback 缺少 knowledge")
        callback_result = await self._post_callback_if_configured(
            job=job,
            payload=payload,
            callback_payload=callback_payload,
        )
        return {
            "ai_knowledge_payload": ai_knowledge_payload,
            "callback_payload": callback_payload,
            "callback_result": callback_result,
        }

    async def _handle_brand_full_knowledge_refresh(
        self,
        job: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._brand_full_knowledge_refresh_handler().handle(job, payload)

    def _brand_full_knowledge_refresh_handler(self) -> BrandFullKnowledgeRefreshJobHandler:
        return BrandFullKnowledgeRefreshJobHandler(
            deps=self._deps,
            normalize_optional_str=self._normalize_optional_str,
            build_callback_payload=self._build_callback_payload,
            post_callback_if_configured=self._post_callback_if_configured,
        )

    @classmethod
    def _build_full_knowledge_refresh_source_task_id(
        cls,
        *,
        job_id: str,
        knowledge_revision: str | None,
        audits: list[dict[str, Any]],
    ) -> str:
        return BrandFullKnowledgeRefreshJobHandler.build_source_task_id(
            job_id=job_id,
            knowledge_revision=knowledge_revision,
            audits=audits,
        )

    @staticmethod
    def _resolve_full_knowledge_change_origin_from_audits(audits: list[dict[str, Any]]) -> str:
        return BrandFullKnowledgeRefreshJobHandler.resolve_change_origin(audits)

    @staticmethod
    def _build_full_knowledge_refresh_batch_hash(audits: list[dict[str, Any]]) -> str:
        return BrandFullKnowledgeRefreshJobHandler.build_batch_hash(audits)

    @staticmethod
    def _deleted_sections_from_audits(audits: list[dict[str, Any]]) -> list[str]:
        return BrandFullKnowledgeRefreshJobHandler.deleted_sections_from_audits(audits)

    @staticmethod
    def _is_empty_audit_value(value: Any) -> bool:
        return BrandFullKnowledgeRefreshJobHandler.is_empty_audit_value(value)

    def _load_attachment_confirm_markdowns(self, audits: list[dict[str, Any]]) -> list[dict[str, str]]:
        return self._brand_full_knowledge_refresh_handler().load_attachment_confirm_markdowns(audits)

    @staticmethod
    def _build_refresh_structured_markdown(
        *,
        brand_name: str,
        audits: list[dict[str, Any]],
        attachment_markdowns: list[dict[str, str]],
    ) -> str:
        return BrandFullKnowledgeRefreshJobHandler.build_structured_markdown(
            brand_name=brand_name,
            audits=audits,
            attachment_markdowns=attachment_markdowns,
        )

    @staticmethod
    def _parse_audit_json(value: Any) -> Any:
        return BrandFullKnowledgeRefreshJobHandler.parse_audit_json(value)

    async def _handle_brand_rename_milvus_sync(
        self,
        job: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        brand_code = str(payload.get("brand_code") or "").strip()
        old_brand_name = str(payload.get("old_brand_name") or "").strip()
        brand_name = str(payload.get("brand_name") or "").strip()
        if not brand_code:
            raise ValueError("brand_rename_milvus_sync 缺少 brand_code")
        if not brand_name:
            raise ValueError("brand_rename_milvus_sync 缺少 brand_name")
        store = getattr(self._deps, "store", None)
        if store is None or not hasattr(store, "rename_brand"):
            raise RuntimeError("Milvus store is not initialized")
        sync_result = store.rename_brand(
            brand_code=brand_code,
            old_brand_name=old_brand_name or brand_name,
            new_brand_name=brand_name,
        )
        return {
            "brand_id": payload.get("brand_id"),
            "brand_code": brand_code,
            "old_brand_name": old_brand_name or brand_name,
            "brand_name": brand_name,
            "milvus_result": sync_result,
        }

    async def _handle_upload_task_process(
        self,
        job: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        task_id = str(payload.get("task_id") or job.get("source_id") or "").strip()
        if not task_id:
            raise ValueError("upload_task_process 缺少 task_id")
        try:
            await self._deps.process_upload_task(task_id)
        except Exception:
            logger.exception("Upload task failed unexpectedly task_id=%s", task_id)
            UploadTaskLifecycle(dependencies=self._deps).fail_task_for_background_exception(task_id)
            raise
        return {"task_id": task_id, "status": "completed"}

    async def _handle_attachment_confirm_pipeline(
        self,
        job: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not callable(self._deps.process_attachment_confirm_pipeline):
            raise RuntimeError("attachment confirm pipeline dependency is not initialized")
        return await self._deps.process_attachment_confirm_pipeline(
            payload=payload,
            job=job,
        )

    async def _handle_attachment_confirm(
        self,
        job: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        brand_name = str(payload.get("brand_name") or "").strip()
        confirmed_markdown = str(payload.get("confirmed_markdown") or "").strip()
        source_task_id = str(payload.get("source_task_id") or job.get("source_id") or "").strip()
        ai_knowledge_payload = await self._deps.build_full_knowledge_from_confirmed_markdown(
            brand_name=brand_name,
            confirmed_markdown=confirmed_markdown,
            source_task_id=source_task_id,
        )
        callback_payload = self._build_callback_payload(
            brand_code=self._normalize_optional_str(payload.get("brand_code")),
            knowledge_revision=self._normalize_optional_str(payload.get("knowledge_revision")),
            ai_knowledge_payload=ai_knowledge_payload,
        )
        merged_snapshot = payload.get("merged_snapshot")
        if isinstance(merged_snapshot, dict):
            brand = payload.get("brand")
            if not isinstance(brand, dict):
                brand = self._resolve_brand(payload=payload) or {}
            callback_payload["knowledge"] = format_brand_callback_knowledge_from_snapshot(
                brand=brand,
                knowledge_snapshot=merged_snapshot,
            )
        elif callable(self._deps.build_current_brand_callback_knowledge):
            knowledge = self._deps.build_current_brand_callback_knowledge(
                brand_code=self._normalize_optional_str(payload.get("brand_code")) or "",
            )
            if isinstance(knowledge, dict):
                callback_payload["knowledge"] = knowledge
        if not isinstance(callback_payload.get("knowledge"), dict) or not callback_payload.get("knowledge"):
            raise ValueError("brand knowledge completed callback 缺少 knowledge")
        callback_result = await self._post_callback_if_configured(
            job=job,
            payload=payload,
            callback_payload=callback_payload,
        )
        return {
            "ai_knowledge_payload": ai_knowledge_payload,
            "callback_payload": callback_payload,
            "callback_result": callback_result,
        }

    async def _handle_attachment_conflict_resolution(
        self,
        job: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not callable(self._deps.process_attachment_conflict_resolution):
            raise RuntimeError("attachment conflict resolution dependency is not initialized")
        return await self._deps.process_attachment_conflict_resolution(
            payload=payload,
            job=job,
        )

    async def _post_callback_if_configured(
        self,
        *,
        job: dict[str, Any],
        payload: dict[str, Any],
        callback_payload: dict[str, Any],
    ) -> dict[str, Any]:
        callback_url = str(payload.get("callback_url") or "").strip()
        if not callback_url:
            return {"status": "skipped", "response_code": None, "response_body": None}
        callback_task_id, callback_type = self._callback_record_identifiers(job=job, payload=payload)
        return await deliver_upload_task_callback(
            callback_store=self._get_callback_store(),
            task_id=callback_task_id,
            callback_type=callback_type,
            callback_url=callback_url,
            payload=callback_payload,
            timeout_seconds=float(getattr(self._deps.settings, "brand_completion_callback_timeout_seconds", 5.0)),
            retry_delays_seconds=_RETRY_DELAYS_SECONDS,
            post_callback=self._post_callback,
            missing_url_error="callback_url 未配置",
            max_retries=int(job.get("max_retries") or len(_RETRY_DELAYS_SECONDS)),
            raise_on_failure=True,
            include_response_body=True,
        )

    def _callback_record_identifiers(
        self,
        *,
        job: dict[str, Any],
        payload: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        callback_task_id = self._normalize_optional_str(payload.get("source_task_id")) or self._normalize_optional_str(
            job.get("source_id")
        )
        job_type = str(job.get("job_type") or "").strip()
        if job_type == JOB_TYPE_ATTACHMENT_CONFIRM:
            return callback_task_id, CALLBACK_TYPE_BRAND_KNOWLEDGE
        if job_type == JOB_TYPE_BRAND_KNOWLEDGE_UPDATE:
            return callback_task_id, CALLBACK_TYPE_BRAND_KNOWLEDGE
        if job_type == JOB_TYPE_BRAND_FULL_KNOWLEDGE_REFRESH:
            return self._normalize_optional_str(job.get("job_id")) or callback_task_id, CALLBACK_TYPE_BRAND_KNOWLEDGE
        return callback_task_id, None

    def _get_callback_store(self) -> Any | None:
        upload_tasks = getattr(self._deps, "upload_tasks", None)
        required_methods = (
            "upsert_upload_task_callback",
            "get_upload_task_callback",
            "update_upload_task_callback_result",
        )
        if upload_tasks is None or not all(hasattr(upload_tasks, method_name) for method_name in required_methods):
            return None
        return upload_tasks

    def _resolve_brand(self, *, payload: dict[str, Any]) -> dict[str, Any] | None:
        brand_code = self._normalize_optional_str(payload.get("brand_code"))
        brand_name = self._normalize_optional_str(payload.get("brand_name"))
        if brand_code and hasattr(self._deps.brands, "get_brand_by_code"):
            brand = self._deps.brands.get_brand_by_code(brand_code)
            if isinstance(brand, dict):
                return brand
        if brand_name and hasattr(self._deps.brands, "get_brand_by_name"):
            brand = self._deps.brands.get_brand_by_name(brand_name)
            if isinstance(brand, dict):
                return brand
        return None

    @staticmethod
    def _build_callback_payload(
        *,
        brand_code: str | None,
        knowledge_revision: str | None,
        ai_knowledge_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "brand_code": brand_code or "",
            "overall_status": "completed",
            "completed_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
            "knowledge_extraction_status": "success",
            "knowledge_markdown_status": "success",
            "knowledge_mete": {
                "version": str(knowledge_revision or "").strip(),
                "oss_url_md": str((ai_knowledge_payload or {}).get("knowledge_oss_url_md") or "").strip(),
                "oss_url_pdf": str((ai_knowledge_payload or {}).get("knowledge_oss_url_pdf") or "").strip(),
            },
        }

    @staticmethod
    def _post_callback(
        callback_url: str,
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[int | None, str | None]:
        status_code, response_body = post_json_text_response(
            callback_url,
            payload,
            timeout_seconds=timeout_seconds,
        )
        return status_code, response_body
