from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from knowledge_base.brand.callback_mapper import format_brand_callback_knowledge_from_snapshot
from knowledge_base.shared.callback_delivery import (
    deliver_upload_task_callback,
    load_callback_payload,
    seconds_until,
)
from knowledge_base.shared.http import post_json_text_response


CONFIRM_CALLBACK_TYPE = "brand_knowledge_completed"


class AttachmentDraftConfirmCallbackMixin:
    def _build_confirm_callback_payload(
        self,
        *,
        brand: dict[str, Any],
        merged_snapshot: dict[str, Any],
        changed_snapshot: dict[str, Any] | None = None,
        knowledge_revision: str | None,
        ai_knowledge_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        callback_snapshot = changed_snapshot if isinstance(changed_snapshot, dict) else merged_snapshot
        basic_info = merged_snapshot.get("basic_info") if isinstance(merged_snapshot.get("basic_info"), dict) else {}
        brand_code = self._normalize_optional_str(basic_info.get("brand_code")) or self._normalize_optional_str(
            brand.get("brand_code")
        )
        knowledge_markdown_status = (
            "success"
            if changed_snapshot is not None or isinstance(ai_knowledge_payload, dict)
            else "skipped"
        )
        payload = {
            "brand_code": brand_code or "",
            "overall_status": "completed",
            "completed_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
            "knowledge_extraction_status": "success",
            "knowledge_markdown_status": knowledge_markdown_status,
            "knowledge": self._build_confirm_callback_changed_knowledge(
                changed_snapshot=callback_snapshot,
            ),
        }
        if changed_snapshot is None and isinstance(ai_knowledge_payload, dict):
            payload["knowledge_mete"] = {
                "version": str(knowledge_revision or brand.get("knowledge_revision") or "").strip(),
                "oss_url_md": str((ai_knowledge_payload or {}).get("knowledge_oss_url_md") or "").strip(),
                "oss_url_pdf": str((ai_knowledge_payload or {}).get("knowledge_oss_url_pdf") or "").strip(),
            }
        return payload

    @classmethod
    def _build_confirm_callback_changed_knowledge(
        cls,
        *,
        changed_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot = changed_snapshot if isinstance(changed_snapshot, dict) else {}
        formatted = format_brand_callback_knowledge_from_snapshot(
            brand=None,
            knowledge_snapshot=snapshot,
        )
        changed_knowledge: dict[str, Any] = {}
        for section in (
            "basic_info",
            "company_profile",
            "management_team",
            "competitors",
            "authority_honors",
            "customers_cases",
            "products",
            "sensitive_topics",
            "attachments",
            "official_malls",
            "official_media_matrix",
            "other_info",
        ):
            if not cls._has_confirm_callback_section_change(section=section, value=snapshot.get(section)):
                continue
            if section in formatted:
                changed_knowledge[section] = formatted[section]
        return changed_knowledge

    @classmethod
    def _has_confirm_callback_section_change(cls, *, section: str, value: Any) -> bool:
        if section == "basic_info" and isinstance(value, dict):
            meaningful_basic_info = {
                key: item
                for key, item in value.items()
                if key not in {"brand_code", "brand_name"} and cls._has_confirm_callback_value(item)
            }
            return bool(meaningful_basic_info)
        return cls._has_confirm_callback_value(value)

    @classmethod
    def _has_confirm_callback_value(cls, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, dict):
            return any(cls._has_confirm_callback_value(item) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return any(cls._has_confirm_callback_value(item) for item in value)
        return True

    @staticmethod
    def _post_confirm_callback(
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

    async def _send_confirm_callback(
        self,
        *,
        payload: dict[str, Any],
        callback_task_id: str | None = None,
    ) -> dict[str, Any]:
        return await deliver_upload_task_callback(
            callback_store=self._get_confirm_callback_store(),
            task_id=callback_task_id,
            callback_type=CONFIRM_CALLBACK_TYPE,
            callback_url=str(getattr(self._deps.settings, "brand_completion_callback_url", "") or "").strip(),
            payload=payload,
            timeout_seconds=float(getattr(self._deps.settings, "brand_completion_callback_timeout_seconds", 5.0)),
            retry_delays_seconds=self._CONFIRM_CALLBACK_RETRY_DELAYS_SECONDS,
            post_callback=self._post_confirm_callback,
            missing_url_error="brand_completion_callback_url 未配置",
        )

    def _confirm_callback_retry_key(self, *, draft_id: str, review_id: str | None, brand_name: str) -> str:
        return f"{draft_id}:{review_id or 'manual'}:{brand_name}"

    @staticmethod
    def _confirm_callback_task_id(*, draft_id: str, review_id: str | None) -> str:
        return f"confirm:{draft_id}:{review_id or 'manual'}"

    def _get_confirm_callback_store(self) -> Any | None:
        upload_tasks = getattr(self._deps, "upload_tasks", None)
        required_methods = (
            "upsert_upload_task_callback",
            "get_upload_task_callback",
            "update_upload_task_callback_result",
        )
        if upload_tasks is None or not all(hasattr(upload_tasks, method_name) for method_name in required_methods):
            return None
        return upload_tasks

    def _load_confirm_callback_payload(self, callback: dict[str, Any]) -> dict[str, Any]:
        return load_callback_payload(callback, label="confirm")

    async def _run_confirm_callback_retries(
        self,
        *,
        retry_key: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            for delay_seconds in self._CONFIRM_CALLBACK_RETRY_DELAYS_SECONDS:
                await asyncio.sleep(delay_seconds)
                result = await self._send_confirm_callback(payload=payload)
                if result.get("status") == "success":
                    return
        finally:
            runtime = getattr(self._deps, "runtime", None)
            scheduled = getattr(runtime, "scheduled_attachment_confirm_callback_retries", None)
            if isinstance(scheduled, set):
                scheduled.discard(retry_key)

    async def _run_persisted_confirm_callback_retries(
        self,
        *,
        callback_task_id: str,
        initial_delay_seconds: float,
    ) -> None:
        try:
            delay_seconds = initial_delay_seconds
            while True:
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)
                upload_tasks = self._get_confirm_callback_store()
                if upload_tasks is None:
                    return
                callback = upload_tasks.get_upload_task_callback(
                    task_id=callback_task_id,
                    callback_type=CONFIRM_CALLBACK_TYPE,
                )
                if not callback or str(callback.get("status") or "") != "retrying":
                    return
                try:
                    payload = self._load_confirm_callback_payload(callback)
                except Exception as exc:  # noqa: BLE001
                    upload_tasks.update_upload_task_callback_result(
                        task_id=callback_task_id,
                        callback_type=CONFIRM_CALLBACK_TYPE,
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
                result = await self._send_confirm_callback(
                    payload=payload,
                    callback_task_id=callback_task_id,
                )
                if result.get("status") != "retrying":
                    return
                refreshed_callback = upload_tasks.get_upload_task_callback(
                    task_id=callback_task_id,
                    callback_type=CONFIRM_CALLBACK_TYPE,
                )
                delay_seconds = seconds_until((refreshed_callback or {}).get("next_retry_at"))
        finally:
            runtime = getattr(self._deps, "runtime", None)
            scheduled = getattr(runtime, "scheduled_attachment_confirm_callback_retries", None)
            if isinstance(scheduled, set):
                scheduled.discard(callback_task_id)

    def _schedule_confirm_callback_retries_if_needed(
        self,
        *,
        draft_id: str,
        review_id: str | None,
        brand_name: str,
        payload: dict[str, Any],
    ) -> bool:
        runtime = getattr(self._deps, "runtime", None)
        spawn_background_task = getattr(self._deps, "spawn_background_task", None)
        scheduled = getattr(runtime, "scheduled_attachment_confirm_callback_retries", None)
        if not isinstance(scheduled, set) or not callable(spawn_background_task):
            return False
        callback_task_id = self._confirm_callback_task_id(draft_id=draft_id, review_id=review_id)
        upload_tasks = self._get_confirm_callback_store()
        if upload_tasks is not None:
            callback = upload_tasks.get_upload_task_callback(
                task_id=callback_task_id,
                callback_type=CONFIRM_CALLBACK_TYPE,
            )
            if not callback or str(callback.get("status") or "") != "retrying":
                return False
            if callback_task_id in scheduled:
                return True
            scheduled.add(callback_task_id)
            spawn_background_task(
                self._run_persisted_confirm_callback_retries(
                    callback_task_id=callback_task_id,
                    initial_delay_seconds=seconds_until(callback.get("next_retry_at")),
                )
            )
            return True
        retry_key = self._confirm_callback_retry_key(
            draft_id=draft_id,
            review_id=review_id,
            brand_name=brand_name,
        )
        if retry_key in scheduled:
            return True
        scheduled.add(retry_key)
        spawn_background_task(
            self._run_confirm_callback_retries(
                retry_key=retry_key,
                payload=payload,
            )
        )
        return True

    def schedule_due_confirm_callback_retries(self) -> None:
        upload_tasks = self._get_confirm_callback_store()
        runtime = getattr(self._deps, "runtime", None)
        spawn_background_task = getattr(self._deps, "spawn_background_task", None)
        scheduled = getattr(runtime, "scheduled_attachment_confirm_callback_retries", None)
        if upload_tasks is None or not hasattr(upload_tasks, "list_retryable_upload_task_callbacks"):
            return
        if not isinstance(scheduled, set) or not callable(spawn_background_task):
            return
        for callback in upload_tasks.list_retryable_upload_task_callbacks(callback_type=CONFIRM_CALLBACK_TYPE):
            callback_task_id = str(callback.get("task_id") or "").strip()
            if not callback_task_id or callback_task_id in scheduled:
                continue
            scheduled.add(callback_task_id)
            spawn_background_task(
                self._run_persisted_confirm_callback_retries(
                    callback_task_id=callback_task_id,
                    initial_delay_seconds=0,
                )
            )
