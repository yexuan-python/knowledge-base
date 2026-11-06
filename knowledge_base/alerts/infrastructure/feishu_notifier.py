from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any

import requests

from knowledge_base.alerts.schemas import DocumentAlert
from knowledge_base.infrastructure.settings import Settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationResult:
    status: str
    request_payload: dict[str, Any] | None = None
    response_status: int | None = None
    response_body: str | None = None
    error_message: str | None = None
    sent_at: datetime | None = None


class FeishuNotifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send_payload(self, payload: dict[str, Any]) -> NotificationResult:
        if not self.settings.business_alerts_enabled:
            return NotificationResult(
                status="skipped",
                request_payload=payload,
                error_message="feishu_disabled",
            )

        webhook_url = self.settings.business_alert_notify_url
        if not webhook_url:
            return NotificationResult(
                status="skipped",
                request_payload=payload,
                error_message="missing_webhook_url",
            )

        sent_at = datetime.now()
        request_payload = self._build_bot_text_payload(payload)
        try:
            response = requests.post(
                webhook_url,
                json=request_payload,
                headers=self._build_headers(),
                timeout=self.settings.business_alert_timeout_seconds,
            )
        except Exception as exc:
            logger.warning("飞书 webhook 请求失败: %s", exc)
            return NotificationResult(
                status="failed",
                request_payload=request_payload,
                error_message=str(exc),
                sent_at=sent_at,
            )

        if self._is_success_response(response):
            return NotificationResult(
                status="success",
                request_payload=request_payload,
                response_status=response.status_code,
                response_body=response.text,
                sent_at=sent_at,
            )

        return NotificationResult(
            status="failed",
            request_payload=request_payload,
            response_status=response.status_code,
            response_body=response.text,
            error_message=self._extract_error_message(response) or "unknown_feishu_error",
            sent_at=sent_at,
        )

    def send_alert(self, alert: DocumentAlert) -> NotificationResult:
        payload = dict(alert.payload_json or {})
        if not payload:
            payload = self._build_payload_from_alert(alert)
        return self.send_payload(payload)

    @staticmethod
    def _build_payload_from_alert(alert: DocumentAlert) -> dict[str, Any]:
        return {
            "alert_type": alert.alert_type,
            "title": "上传文件失败告警" if alert.alert_type == "upload_file_failed" else "AI提取失败告警",
            "name": alert.alert_name,
            "task_id": alert.task_id,
            "document_id": alert.document_id,
            "reason": alert.reason,
            "date": FeishuNotifier._format_datetime(alert.created_at),
        }

    @staticmethod
    def _build_headers() -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def _build_bot_text_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = {
            "msg_type": "text",
            "content": {
                "text": self._format_bot_text(payload),
            },
        }
        secret = self.settings.business_alert_notify_secret
        if secret:
            timestamp = str(int(time.time()))
            request_payload["timestamp"] = timestamp
            request_payload["sign"] = self._build_bot_signature(secret=secret, timestamp=timestamp)
        return request_payload

    @staticmethod
    def _build_bot_signature(*, secret: str, timestamp: str) -> str:
        string_to_sign = f"{timestamp}\n{secret}"
        digest = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    @staticmethod
    def _format_bot_text(payload: dict[str, Any]) -> str:
        if payload.get("alert_type") == "request_validation_failed":
            return FeishuNotifier._format_request_validation_text(payload)

        title = str(payload.get("title") or payload.get("alert_type") or "").strip()
        field_mappings = (
            ("name", "名称"),
            ("task_id", "task_id"),
            ("document_id", "document_id"),
            ("reason", "原因"),
            ("date", "日期"),
        )
        lines: list[str] = []
        if title:
            lines.append(title)
        for key, label in field_mappings:
            value = payload.get(key)
            value_text = "" if value is None else str(value).strip()
            lines.append(f"{label}：{value_text}")

        if not any("：" in line and line.split("：", 1)[1].strip() for line in lines):
            lines.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return "\n".join(lines)

    @staticmethod
    def _format_request_validation_text(payload: dict[str, Any]) -> str:
        title = str(payload.get("title") or "接口请求参数校验失败告警").strip()
        lines = [title]
        field_mappings = (
            ("name", "接口"),
            ("client", "客户端"),
            ("content_type", "Content-Type"),
            ("content_length", "Content-Length"),
            ("reason", "原因"),
            ("date", "日期"),
        )
        for key, label in field_mappings:
            value = payload.get(key)
            value_text = "" if value is None else str(value).strip()
            lines.append(f"{label}：{value_text}")

        errors = payload.get("errors")
        if errors:
            try:
                errors_text = json.dumps(errors, ensure_ascii=False, sort_keys=True)
            except Exception:
                errors_text = str(errors)
            lines.append(f"errors：{errors_text}")

        body_preview = str(payload.get("request_body_preview") or "").strip()
        if body_preview:
            suffix = "（已截断）" if payload.get("request_body_preview_truncated") else ""
            lines.append(f"请求体预览{suffix}：{body_preview}")

        return "\n".join(lines)

    def _is_success_response(self, response: requests.Response) -> bool:
        if not response.ok:
            return False

        payload = self._parse_response_json(response)
        if payload is None:
            return True

        code = payload.get("code")
        if code is None:
            return True
        try:
            return int(code) == 0
        except (TypeError, ValueError):
            return False

    def _extract_error_message(self, response: requests.Response) -> str | None:
        payload = self._parse_response_json(response)
        if payload is None:
            body_text = (response.text or "").strip()
            return body_text or None

        for key in ("msg", "message", "errmsg"):
            value = payload.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()

        code = payload.get("code")
        if code is not None:
            return f"feishu_business_error code={code}"
        return (response.text or "").strip() or None

    @staticmethod
    def _parse_response_json(response: requests.Response) -> dict[str, Any] | None:
        body_text = (response.text or "").strip()
        if not body_text:
            return None
        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _format_datetime(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.isoformat(sep=" ")


@lru_cache(maxsize=1)
def get_feishu_notifier(settings: Settings) -> FeishuNotifier:
    return FeishuNotifier(settings)
