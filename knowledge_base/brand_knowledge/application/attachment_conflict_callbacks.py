from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from knowledge_base.shared.callback_delivery import (
    deliver_upload_task_callback,
    load_callback_payload,
    seconds_until,
)
from knowledge_base.shared.http import post_json_text_response


BRAND_KNOWLEDGE_STATUS_CALLBACK_TYPE = "brand_knowledge_status"
BRAND_KNOWLEDGE_COMPLETED_CALLBACK_TYPE = "brand_knowledge_completed"
ATTACHMENT_CONFLICT_WAITING_CALLBACK_TYPE = BRAND_KNOWLEDGE_STATUS_CALLBACK_TYPE
ATTACHMENT_CONFLICT_COMPLETED_CALLBACK_TYPE = BRAND_KNOWLEDGE_COMPLETED_CALLBACK_TYPE
_ATTACHMENT_CONFLICT_CALLBACK_RETRY_DELAYS_SECONDS = (60, 120, 180)


class BrandKnowledgeAttachmentConflictCallbackMixin:
    @staticmethod
    def _attachment_conflict_callback_task_id(*, session_id: str, stage: str) -> str:
        return f"attachment_conflict:{stage}:{session_id}"[:128]

    def _get_attachment_conflict_callback_store(self) -> Any | None:
        upload_tasks = getattr(self._deps, "upload_tasks", None)
        required_methods = (
            "upsert_upload_task_callback",
            "get_upload_task_callback",
            "update_upload_task_callback_result",
        )
        if upload_tasks is None or not all(hasattr(upload_tasks, method_name) for method_name in required_methods):
            return None
        return upload_tasks

    @staticmethod
    def _post_attachment_conflict_callback(
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

    def _build_attachment_conflict_waiting_callback_payload(
        self,
        *,
        session_id: str,
        brand_code: str | None,
        status: str,
    ) -> dict[str, Any]:
        normalized_status = str(status or "").strip() or "waiting_user_input"
        return {
            "brand_code": str(brand_code or "").strip(),
            "completed_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
            "overall_status": normalized_status,
            "knowledge_session_id": session_id,
            "knowledge_session_status": normalized_status,
            "knowledge_markdown_status": normalized_status,
            "knowledge_extraction_status": "skipped",
        }

    def _build_attachment_conflict_completed_callback_payload(
        self,
        *,
        session_id: str,
        brand_code: str | None,
        knowledge_oss_url_md: str | None,
        knowledge_oss_url_pdf: str | None,
        knowledge_payload: dict[str, Any] | None = None,
        knowledge_revision: str | None = None,
        knowledge_extraction_status: str = "success",
    ) -> dict[str, Any]:
        normalized_brand_code = str(brand_code or "").strip()
        brand = self._deps.brands.get_brand_by_code(normalized_brand_code) if normalized_brand_code else None
        resolved_knowledge_payload = knowledge_payload if isinstance(knowledge_payload, dict) else None
        if resolved_knowledge_payload is None and callable(self._deps.build_current_brand_callback_knowledge):
            current_knowledge = self._deps.build_current_brand_callback_knowledge(brand_code=normalized_brand_code)
            if isinstance(current_knowledge, dict):
                resolved_knowledge_payload = current_knowledge
        if not isinstance(resolved_knowledge_payload, dict) or not resolved_knowledge_payload:
            raise ValueError(f"completed callback knowledge missing brand_code={normalized_brand_code}")
        return {
            "brand_code": normalized_brand_code,
            "completed_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
            "knowledge_mete": {
                "version": str(knowledge_revision or (brand or {}).get("knowledge_revision") or "").strip(),
                "oss_url_md": str(knowledge_oss_url_md or "").strip(),
                "oss_url_pdf": str(knowledge_oss_url_pdf or "").strip(),
            },
            "overall_status": "completed",
            "knowledge_session_id": session_id,
            "knowledge_session_status": "completed",
            "knowledge_markdown_status": "completed",
            "knowledge_extraction_status": knowledge_extraction_status,
            "knowledge": resolved_knowledge_payload,
        }

    def _load_attachment_conflict_callback_payload(self, callback: dict[str, Any]) -> dict[str, Any]:
        return load_callback_payload(callback, label="attachment conflict")

    async def _send_attachment_conflict_callback(
        self,
        *,
        payload: dict[str, Any],
        callback_type: str,
        callback_task_id: str,
    ) -> dict[str, Any]:
        return await deliver_upload_task_callback(
            callback_store=self._get_attachment_conflict_callback_store(),
            task_id=callback_task_id,
            callback_type=callback_type,
            callback_url=str(getattr(self._deps.settings, "brand_completion_callback_url", "") or "").strip(),
            payload=payload,
            timeout_seconds=float(getattr(self._deps.settings, "brand_completion_callback_timeout_seconds", 5.0)),
            retry_delays_seconds=_ATTACHMENT_CONFLICT_CALLBACK_RETRY_DELAYS_SECONDS,
            post_callback=self._post_attachment_conflict_callback,
            missing_url_error="brand_completion_callback_url 未配置",
        )

    async def _run_persisted_attachment_conflict_callback_retries(
        self,
        *,
        callback_task_id: str,
        callback_type: str,
        initial_delay_seconds: float,
    ) -> None:
        try:
            delay_seconds = initial_delay_seconds
            while True:
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)
                upload_tasks = self._get_attachment_conflict_callback_store()
                if upload_tasks is None:
                    return
                callback = upload_tasks.get_upload_task_callback(
                    task_id=callback_task_id,
                    callback_type=callback_type,
                )
                if not callback or str(callback.get("status") or "") != "retrying":
                    return
                try:
                    payload = self._load_attachment_conflict_callback_payload(callback)
                except Exception as exc:  # noqa: BLE001
                    upload_tasks.update_upload_task_callback_result(
                        task_id=callback_task_id,
                        callback_type=callback_type,
                        request_payload_json=None,
                        status="failed",
                        retry_count=int(callback.get("retry_count") or 0),
                        next_retry_at=None,
                        last_response_code=None,
                        last_response_body=None,
                        last_error_message=str(exc),
                        sent_at=None,
                    )
                    return
                result = await self._send_attachment_conflict_callback(
                    payload=payload,
                    callback_type=callback_type,
                    callback_task_id=callback_task_id,
                )
                if result.get("status") != "retrying":
                    return
                refreshed_callback = upload_tasks.get_upload_task_callback(
                    task_id=callback_task_id,
                    callback_type=callback_type,
                )
                delay_seconds = seconds_until((refreshed_callback or {}).get("next_retry_at"))
        finally:
            runtime = getattr(self._deps, "runtime", None)
            scheduled = getattr(runtime, "scheduled_attachment_conflict_callback_retries", None)
            if isinstance(scheduled, set):
                scheduled.discard(callback_task_id)

    def _schedule_attachment_conflict_callback_retries_if_needed(
        self,
        *,
        callback_task_id: str,
        callback_type: str,
    ) -> bool:
        upload_tasks = self._get_attachment_conflict_callback_store()
        runtime = getattr(self._deps, "runtime", None)
        spawn_background_task = getattr(self._deps, "spawn_background_task", None)
        scheduled = getattr(runtime, "scheduled_attachment_conflict_callback_retries", None)
        if upload_tasks is None or not isinstance(scheduled, set) or not callable(spawn_background_task):
            return False
        callback = upload_tasks.get_upload_task_callback(
            task_id=callback_task_id,
            callback_type=callback_type,
        )
        if not callback or str(callback.get("status") or "") != "retrying":
            return False
        if callback_task_id in scheduled:
            return True
        scheduled.add(callback_task_id)
        spawn_background_task(
            self._run_persisted_attachment_conflict_callback_retries(
                callback_task_id=callback_task_id,
                callback_type=callback_type,
                initial_delay_seconds=seconds_until(callback.get("next_retry_at")),
            )
        )
        return True

    def schedule_due_attachment_conflict_callback_retries(self) -> None:
        upload_tasks = self._get_attachment_conflict_callback_store()
        runtime = getattr(self._deps, "runtime", None)
        spawn_background_task = getattr(self._deps, "spawn_background_task", None)
        scheduled = getattr(runtime, "scheduled_attachment_conflict_callback_retries", None)
        if upload_tasks is None or not hasattr(upload_tasks, "list_retryable_upload_task_callbacks"):
            return
        if not isinstance(scheduled, set) or not callable(spawn_background_task):
            return
        for callback_type in (
            BRAND_KNOWLEDGE_STATUS_CALLBACK_TYPE,
            BRAND_KNOWLEDGE_COMPLETED_CALLBACK_TYPE,
        ):
            for callback in upload_tasks.list_retryable_upload_task_callbacks(callback_type=callback_type):
                callback_task_id = str(callback.get("task_id") or "").strip()
                if not callback_task_id or callback_task_id in scheduled:
                    continue
                scheduled.add(callback_task_id)
                spawn_background_task(
                    self._run_persisted_attachment_conflict_callback_retries(
                        callback_task_id=callback_task_id,
                        callback_type=callback_type,
                        initial_delay_seconds=0,
                    )
                )
