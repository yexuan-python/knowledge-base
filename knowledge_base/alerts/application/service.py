from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from knowledge_base.alerts.schemas import DocumentAlert


logger = logging.getLogger(__name__)

_AI_TERMINAL_STATUSES = {"success", "failed", "skipped"}


@dataclass(frozen=True)
class AlertApplicationDependencies:
    settings: Any
    document_alerts: Any
    document_registry: Any
    notifier: Any


class AlertApplicationService:
    REQUEST_VALIDATION_BODY_MAX_CHARS = 12000
    REQUEST_VALIDATION_BODY_PREVIEW_MAX_CHARS = 1500

    def __init__(self, dependencies: AlertApplicationDependencies) -> None:
        self._deps = dependencies

    @staticmethod
    def _format_datetime(value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat(sep=" ")
        if value is None:
            return datetime.now().isoformat(sep=" ", timespec="seconds")
        return str(value)

    async def _send_document_alert(self, alert: DocumentAlert) -> None:
        alert_id, created = self._deps.document_alerts.insert_document_alert(alert)
        if not created:
            logger.info(
                "Skip duplicate document alert dedupe_key=%s alert_id=%s",
                alert.dedupe_key,
                alert_id,
            )
            return

        result = await asyncio.to_thread(self._deps.notifier.send_alert, alert)
        self._deps.document_alerts.update_document_alert_send_result(
            dedupe_key=alert.dedupe_key,
            send_status=result.status,
            send_response=result.response_body,
            send_error=result.error_message,
            sent_at=result.sent_at,
        )

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, dict):
            return {str(key): AlertApplicationService._jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [AlertApplicationService._jsonable(item) for item in value]
        return str(value)

    @staticmethod
    def _compact_json(value: Any) -> str:
        try:
            return json.dumps(
                AlertApplicationService._jsonable(value),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except Exception:
            return str(value)

    @staticmethod
    def _truncate_text(value: str, max_chars: int) -> tuple[str, bool]:
        if len(value) <= max_chars:
            return value, False
        return value[:max_chars] + "...[truncated]", True

    @classmethod
    def _sanitize_request_validation_body(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): cls._sanitize_request_validation_body(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._sanitize_request_validation_body(item) for item in value]
        return cls._jsonable(value)

    async def notify_request_validation_failure(
        self,
        *,
        method: str,
        path: str,
        query_params: dict[str, Any],
        content_type: str | None,
        content_length: str | None,
        client_host: str | None,
        errors: list[dict[str, Any]],
        request_body: Any,
        occurred_at: Any = None,
    ) -> None:
        sanitized_request_body = self._sanitize_request_validation_body(request_body)
        body_text = self._compact_json(sanitized_request_body)
        errors_text = self._compact_json(errors)
        stored_body_text, body_truncated = self._truncate_text(
            body_text,
            self.REQUEST_VALIDATION_BODY_MAX_CHARS,
        )
        body_preview, preview_truncated = self._truncate_text(
            body_text,
            self.REQUEST_VALIDATION_BODY_PREVIEW_MAX_CHARS,
        )
        normalized_method = str(method or "").upper()
        normalized_path = str(path or "").strip() or "unknown_path"
        occurred_text = self._format_datetime(occurred_at)
        minute_bucket = occurred_text[:16] if occurred_text else datetime.now().strftime("%Y-%m-%d %H:%M")
        identity_source = "|".join(
            [
                normalized_method,
                normalized_path,
                body_text,
                errors_text,
                minute_bucket,
            ]
        )
        identity_hash = hashlib.sha256(identity_source.encode("utf-8")).hexdigest()[:24]
        first_error = errors[0] if errors else {}
        first_loc = first_error.get("loc")
        first_msg = str(first_error.get("msg") or "请求参数校验失败").strip()
        first_error_path = ".".join(str(part) for part in first_loc) if isinstance(first_loc, (list, tuple)) else str(first_loc or "")
        reason = first_msg if not first_error_path else f"{first_error_path}: {first_msg}"
        payload = {
            "alert_type": "request_validation_failed",
            "title": "接口请求参数校验失败告警",
            "name": f"{normalized_method} {normalized_path}",
            "method": normalized_method,
            "path": normalized_path,
            "query": self._jsonable(query_params),
            "content_type": content_type,
            "content_length": content_length,
            "client": client_host,
            "reason": reason,
            "errors": self._jsonable(errors),
            "request_body": stored_body_text,
            "request_body_sanitized": False,
            "request_body_truncated": body_truncated,
            "request_body_preview": body_preview,
            "request_body_preview_truncated": preview_truncated,
            "date": occurred_text,
        }
        alert = DocumentAlert(
            alert_type="request_validation_failed",
            alert_name=payload["name"][:128],
            dedupe_key=f"request_validation_failed:{identity_hash}",
            task_id=None,
            document_id=None,
            document_name=normalized_path[:128],
            reason=reason,
            payload_json=payload,
            send_status="pending",
        )
        await self._send_document_alert(alert)

    async def notify_upload_failure(
        self,
        *,
        task_id: str,
        file_index: int,
        original_filename: str,
        error_message: str | None,
        created_at: Any = None,
        document_name: str | None = None,
    ) -> None:
        dedupe_key = f"upload_file_failed:{task_id}:{file_index}"
        reason = (error_message or "").strip() or "未知错误"
        payload = {
            "alert_type": "upload_file_failed",
            "title": "上传文件失败告警",
            "name": f"{original_filename}上传失败",
            "task_id": task_id,
            "document_id": None,
            "reason": reason,
            "date": self._format_datetime(created_at),
        }
        alert = DocumentAlert(
            alert_type="upload_file_failed",
            alert_name=payload["name"],
            dedupe_key=dedupe_key,
            task_id=task_id,
            document_id=None,
            document_name=document_name or original_filename,
            reason=reason,
            payload_json=payload,
            send_status="pending",
        )
        await self._send_document_alert(alert)

    async def notify_ai_failure_if_ready(
        self,
        *,
        category: str,
        file_hash: str,
    ) -> None:
        record = self._deps.document_registry.get_document_registry_record(
            category=category,
            file_hash=file_hash,
        )
        if not record:
            return

        facts_status = str(record.get("facts_status") or "")
        if facts_status not in _AI_TERMINAL_STATUSES:
            return

        facts_failed = facts_status == "failed"
        if not facts_failed:
            return

        original_filename = str(record.get("original_filename") or "")
        document_id = str(record.get("document_id") or "")
        upload_task_id = str(record.get("upload_task_id") or "") or None
        if not document_id:
            logger.warning(
                "AI alert skipped because document_id missing category=%s file_hash=%s",
                category,
                file_hash,
            )
            return

        name = f"{original_filename} AI事实失败"

        reason_parts: list[str] = []
        facts_error = (record.get("facts_error") or "").strip()
        reason_parts.append(f"AI事实失败: {facts_error or '未知错误'}")
        reason = "；".join(reason_parts)

        facts_updated_at = record.get("facts_updated_at")
        alert_time = facts_updated_at

        payload = {
            "alert_type": "ai_extract_failed",
            "title": "AI提取失败告警",
            "name": name,
            "task_id": upload_task_id,
            "document_id": document_id,
            "reason": reason,
            "date": self._format_datetime(alert_time),
        }
        alert = DocumentAlert(
            alert_type="ai_extract_failed",
            alert_name=name,
            dedupe_key=f"ai_extract_failed:{document_id}",
            task_id=upload_task_id,
            document_id=document_id,
            document_name=original_filename,
            reason=reason,
            payload_json=payload,
            send_status="pending",
        )
        await self._send_document_alert(alert)
