from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from knowledge_base.brand.callback_mapper import (
    format_brand_callback_knowledge,
    format_brand_callback_knowledge_from_snapshot,
)
from knowledge_base.brand.knowledge_extraction import extract_brand_knowledge_for_task
from knowledge_base.shared.callback_delivery import deliver_upload_task_callback, seconds_until
from knowledge_base.shared.http import post_json_text_response
from knowledge_base.shared.utils import parse_metadata_json

STATUS_CALLBACK_TYPE = "brand_knowledge_status"
COMPLETED_CALLBACK_TYPE = "brand_knowledge_completed"
_TASK_TERMINAL_STATUSES = {"completed", "completed_with_errors", "failed"}
_FILE_TERMINAL_STATUSES = {"success", "failed"}
_RETRY_DELAYS_SECONDS = (60, 120, 180)

if TYPE_CHECKING:
    from knowledge_base.service import KnowledgeBaseService


logger = logging.getLogger(__name__)


class FullMarkdownNotReadyError(RuntimeError):
    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause


@dataclass(frozen=True)
class BrandCallbackCoordinatorDependencies:
    settings: Any
    brands: Any
    upload_tasks: Any
    document_registry: Any
    runtime: Any
    spawn_background_task: Any
    extract_brand_knowledge_for_task: Any
    format_brand_callback_knowledge: Any
    build_current_brand_callback_knowledge: Any = None
    build_current_brand_knowledge_mete: Any = None
    build_attachment_delete_callback_payload: Any = None
    brand_knowledge_sessions: Any = None
    ensure_attachment_conflict_session: Any = None


class BrandCallbackCoordinator:
    def __init__(self, dependencies: BrandCallbackCoordinatorDependencies) -> None:
        self._deps = dependencies

    @staticmethod
    def _parse_callback_payload(raw_payload: Any) -> dict[str, Any] | None:
        if isinstance(raw_payload, dict):
            return raw_payload
        if isinstance(raw_payload, str) and raw_payload:
            try:
                parsed = json.loads(raw_payload)
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, dict):
                return parsed
        return None

    def _is_brand_callback_enabled(self, task_id: str) -> bool:
        task = self._deps.upload_tasks.get_upload_task(task_id)
        if not task:
            return False
        metadata = parse_metadata_json(task.get("metadata_json"))
        return bool(metadata.get("brand_callback_enabled"))

    def _build_callback_payload(self, task_id: str) -> dict[str, Any] | None:
        if not self._is_brand_callback_enabled(task_id):
            return None
        self._deps.upload_tasks.refresh_upload_task_counts(task_id)
        task = self._deps.upload_tasks.get_upload_task(task_id)
        if not task:
            return None

        task_status = str(task.get("status") or "")
        if task_status not in _TASK_TERMINAL_STATUSES:
            return None
        if int(task.get("pending_count") or 0) > 0 or int(task.get("processing_count") or 0) > 0:
            return None

        files = self._deps.upload_tasks.get_upload_task_files(task_id)
        for file_item in files:
            file_status = str(file_item.get("status") or "")
            if file_status not in _FILE_TERMINAL_STATUSES:
                return None

        metadata = parse_metadata_json(task.get("metadata_json"))
        brand_code = str(metadata.get("brand_code") or "").strip()
        completed_at = task.get("updated_at")
        if isinstance(completed_at, datetime):
            completed_at_text = completed_at.isoformat(sep=" ")
        else:
            completed_at_text = datetime.now().isoformat(sep=" ", timespec="seconds")

        return {
            "brand_code": brand_code,
            "overall_status": task_status,
            "completed_at": completed_at_text,
        }

    def _build_knowledge_mete(
        self,
        *,
        brand_code: str,
        knowledge_oss_url_md: str | None,
        knowledge_oss_url_pdf: str | None,
    ) -> dict[str, str]:
        if callable(self._deps.build_current_brand_knowledge_mete):
            current = self._deps.build_current_brand_knowledge_mete(brand_code=brand_code)
            if isinstance(current, dict):
                return {
                    "version": str(current.get("version") or "").strip(),
                    "oss_url_md": str(knowledge_oss_url_md or current.get("oss_url_md") or "").strip(),
                    "oss_url_pdf": str(knowledge_oss_url_pdf or current.get("oss_url_pdf") or "").strip(),
                }
        version = ""
        normalized_brand_code = str(brand_code or "").strip()
        if normalized_brand_code:
            brand = self._deps.brands.get_brand_by_code(normalized_brand_code)
            if isinstance(brand, dict):
                version = str(brand.get("knowledge_revision") or "").strip()
        return {
            "version": version,
            "oss_url_md": str(knowledge_oss_url_md or "").strip(),
            "oss_url_pdf": str(knowledge_oss_url_pdf or "").strip(),
        }

    def _build_status_payload(
        self,
        *,
        brand_code: str,
        completed_at: str,
        overall_status: str,
        knowledge_markdown_status: str,
        knowledge_extraction_status: str,
        knowledge_session_id: str | None = None,
        knowledge_session_status: str | None = None,
        knowledge_markdown_error: str | None = None,
        knowledge_extraction_error: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "brand_code": brand_code,
            "overall_status": overall_status,
            "completed_at": completed_at,
            "knowledge_markdown_status": knowledge_markdown_status,
            "knowledge_extraction_status": knowledge_extraction_status,
        }
        if knowledge_session_id:
            payload["knowledge_session_id"] = knowledge_session_id
        if knowledge_session_status:
            payload["knowledge_session_status"] = knowledge_session_status
        if knowledge_markdown_error:
            payload["knowledge_markdown_error"] = knowledge_markdown_error
        if knowledge_extraction_error:
            payload["knowledge_extraction_error"] = knowledge_extraction_error
        return payload

    def _build_completed_payload(
        self,
        *,
        brand_code: str,
        completed_at: str,
        overall_status: str,
        knowledge_markdown_status: str,
        knowledge_extraction_status: str,
        knowledge_mete: dict[str, str],
        knowledge: dict[str, Any],
        knowledge_session_id: str | None = None,
        knowledge_session_status: str | None = None,
        knowledge_markdown_error: str | None = None,
        knowledge_extraction_error: str | None = None,
    ) -> dict[str, Any]:
        payload = self._build_status_payload(
            brand_code=brand_code,
            completed_at=completed_at,
            overall_status=overall_status,
            knowledge_markdown_status=knowledge_markdown_status,
            knowledge_extraction_status=knowledge_extraction_status,
            knowledge_session_id=knowledge_session_id,
            knowledge_session_status=knowledge_session_status,
            knowledge_markdown_error=knowledge_markdown_error,
            knowledge_extraction_error=knowledge_extraction_error,
        )
        payload["knowledge_mete"] = knowledge_mete
        payload["knowledge"] = knowledge
        return payload

    def build_attachment_delete_callback_payload(self, *, brand: dict[str, Any]) -> dict[str, Any] | None:
        if not callable(self._deps.build_attachment_delete_callback_payload):
            return None
        payload = self._deps.build_attachment_delete_callback_payload(brand=brand)
        return payload if isinstance(payload, dict) else None

    async def build_callback_payload_with_knowledge(self, task_id: str) -> tuple[str, dict[str, Any]] | None:
        payload = self._build_callback_payload(task_id)
        if payload is None:
            return None

        task = self._deps.upload_tasks.get_upload_task(task_id)
        task_metadata = parse_metadata_json((task or {}).get("metadata_json"))
        files = self._deps.upload_tasks.get_upload_task_files(task_id)
        document_ids = [str(item.get("document_id")) for item in files if item.get("document_id")]
        has_attachment_files = any(
            str(item.get("file_role") or "").strip() == "attachment"
            for item in files
        )
        has_brand_ai_knowledge_files = any(
            str(item.get("file_role") or "").strip() == "brand_ai_knowledge"
            for item in files
        )
        knowledge_payload: dict[str, Any] | None = None
        completed_knowledge_payload: dict[str, Any] | None = None
        knowledge_extraction_status = "skipped"
        knowledge_extraction_error: str | None = None
        knowledge_markdown_payload: dict[str, Any] | None = None
        knowledge_markdown_status = "waiting_user_input" if has_attachment_files and not document_ids else "skipped"
        knowledge_markdown_error: str | None = None
        knowledge_session_payload: dict[str, Any] | None = None
        if has_brand_ai_knowledge_files:
            knowledge_extraction_status = "success"
            knowledge_markdown_status = "success"
        elif document_ids:
            try:
                knowledge_payload = await self._deps.extract_brand_knowledge_for_task(task_id=task_id)
                knowledge_extraction_status = "success"
            except Exception as exc:  # noqa: BLE001
                logger.exception("Brand knowledge extraction failed task_id=%s", task_id)
                knowledge_extraction_status = "failed"
                knowledge_extraction_error = str(exc)
        if has_brand_ai_knowledge_files:
            if callable(self._deps.build_current_brand_callback_knowledge):
                current_knowledge = self._deps.build_current_brand_callback_knowledge(
                    brand_code=str(task_metadata.get("brand_code") or "").strip(),
                )
                if isinstance(current_knowledge, dict):
                    completed_knowledge_payload = current_knowledge
        elif has_attachment_files and callable(self._deps.ensure_attachment_conflict_session):
            try:
                knowledge_session_payload = await self._deps.ensure_attachment_conflict_session(task_id=task_id)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Brand attachment conflict scan failed task_id=%s", task_id)
                knowledge_markdown_status = "failed"
                knowledge_markdown_error = str(exc)
            return None

        overall_status = str(payload.get("overall_status") or "").strip()
        brand_code = str(payload.get("brand_code") or "").strip()
        completed_at = str(payload.get("completed_at") or "").strip()

        if overall_status == "failed":
            return (
                STATUS_CALLBACK_TYPE,
                self._build_status_payload(
                    brand_code=brand_code,
                    completed_at=completed_at,
                    overall_status=overall_status,
                    knowledge_markdown_status="failed" if knowledge_markdown_error else knowledge_markdown_status,
                    knowledge_extraction_status="failed" if knowledge_extraction_error else knowledge_extraction_status,
                    knowledge_markdown_error=knowledge_markdown_error,
                    knowledge_extraction_error=knowledge_extraction_error,
                ),
            )

        knowledge_oss_url_md = ""
        knowledge_oss_url_pdf = ""
        if isinstance(knowledge_markdown_payload, dict):
            knowledge_oss_url_md = str(knowledge_markdown_payload.get("knowledge_oss_url_md") or "").strip()
            knowledge_oss_url_pdf = str(knowledge_markdown_payload.get("knowledge_oss_url_pdf") or "").strip()
        elif isinstance(knowledge_session_payload, dict):
            knowledge_oss_url_md = str(knowledge_session_payload.get("knowledge_oss_url_md") or "").strip()
            knowledge_oss_url_pdf = str(knowledge_session_payload.get("knowledge_oss_url_pdf") or "").strip()
        knowledge_mete = self._build_knowledge_mete(
            brand_code=brand_code,
            knowledge_oss_url_md=knowledge_oss_url_md,
            knowledge_oss_url_pdf=knowledge_oss_url_pdf,
        )
        if knowledge_payload is not None:
            completed_knowledge_payload = self._deps.format_brand_callback_knowledge(
                task_id,
                knowledge_payload,
                knowledge_markdown_payload=knowledge_markdown_payload,
            )
        elif callable(self._deps.build_current_brand_callback_knowledge):
            current_knowledge = self._deps.build_current_brand_callback_knowledge(
                brand_code=brand_code,
            )
            if isinstance(current_knowledge, dict):
                completed_knowledge_payload = current_knowledge

        if not isinstance(completed_knowledge_payload, dict) or not completed_knowledge_payload:
            raise FullMarkdownNotReadyError(
                f"Completed callback knowledge is not ready for callback task_id={task_id}",
                cause=ValueError("knowledge payload is missing"),
            )

        knowledge_session_id: str | None = None
        knowledge_session_status: str | None = None
        if isinstance(knowledge_session_payload, dict):
            knowledge_session_id = str(knowledge_session_payload.get("session_id") or "").strip() or None
            knowledge_session_status = str(knowledge_session_payload.get("status") or "").strip() or None

        completed_payload = self._build_completed_payload(
            brand_code=brand_code,
            completed_at=completed_at,
            overall_status=overall_status,
            knowledge_markdown_status=knowledge_markdown_status,
            knowledge_extraction_status=knowledge_extraction_status,
            knowledge_mete=knowledge_mete,
            knowledge=completed_knowledge_payload,
            knowledge_session_id=knowledge_session_id,
            knowledge_session_status=knowledge_session_status,
            knowledge_markdown_error=knowledge_markdown_error,
            knowledge_extraction_error=knowledge_extraction_error,
        )
        return COMPLETED_CALLBACK_TYPE, completed_payload

    @staticmethod
    def _send_callback_request(
        url: str,
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[int | None, str | None, str | None]:
        try:
            status_code, response_body = post_json_text_response(
                url,
                payload,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            return None, None, str(exc)
        return status_code, response_body, None

    def _register_callback_if_needed(self, task_id: str, *, callback_type: str) -> str | None:
        if not self._is_brand_callback_enabled(task_id):
            return None
        callback_url = self._deps.settings.brand_completion_callback_url.strip()
        if not callback_url:
            return None
        callback = self._deps.upload_tasks.get_upload_task_callback(
            task_id=task_id,
            callback_type=callback_type,
        )
        if callback is None:
            self._deps.upload_tasks.upsert_upload_task_callback(
                task_id=task_id,
                callback_type=callback_type,
                callback_url=callback_url,
                request_payload_json=None,
                status="waiting",
            )
        return callback_url

    async def maybe_finalize_task_callback(self, task_id: str) -> bool:
        callback = self._deps.upload_tasks.get_upload_task_callback(task_id=task_id, callback_type=COMPLETED_CALLBACK_TYPE)
        if callback and str(callback.get("status") or "") == "success":
            return True

        in_flight = self._deps.runtime.inflight_brand_callbacks
        if task_id in in_flight:
            return False

        in_flight.add(task_id)
        try:
            existing_completed = self._deps.upload_tasks.get_upload_task_callback(
                task_id=task_id,
                callback_type=COMPLETED_CALLBACK_TYPE,
            )
            if existing_completed and str(existing_completed.get("status") or "") == "success":
                return True

            try:
                callback_result = await self.build_callback_payload_with_knowledge(task_id)
            except FullMarkdownNotReadyError as exc:
                callback_url = self._register_callback_if_needed(task_id, callback_type=COMPLETED_CALLBACK_TYPE)
                if not callback_url:
                    return False
                callback = self._deps.upload_tasks.get_upload_task_callback(
                    task_id=task_id,
                    callback_type=COMPLETED_CALLBACK_TYPE,
                )
                retry_count = int((callback or {}).get("retry_count") or 0)
                delay_seconds = _RETRY_DELAYS_SECONDS[min(retry_count, len(_RETRY_DELAYS_SECONDS) - 1)]
                next_retry_at = datetime.now() + timedelta(seconds=delay_seconds)
                self._deps.upload_tasks.upsert_upload_task_callback(
                    task_id=task_id,
                    callback_type=COMPLETED_CALLBACK_TYPE,
                    callback_url=callback_url,
                    request_payload_json=None,
                    status="retrying",
                )
                self._deps.upload_tasks.update_upload_task_callback_result(
                    task_id=task_id,
                    callback_type=COMPLETED_CALLBACK_TYPE,
                    request_payload_json=None,
                    status="retrying",
                    retry_count=retry_count,
                    next_retry_at=next_retry_at,
                    last_response_code=None,
                    last_response_body=None,
                    last_error_message=str(exc.cause or exc),
                    sent_at=None,
                )
                self.schedule_callback_retry(task_id, delay_seconds=delay_seconds)
                return False
            if callback_result is None:
                return False
            callback_type, payload = callback_result

            callback_url = self._register_callback_if_needed(task_id, callback_type=callback_type)
            if not callback_url:
                return False
            callback_result = await deliver_upload_task_callback(
                callback_store=self._deps.upload_tasks,
                task_id=task_id,
                callback_type=callback_type,
                callback_url=callback_url,
                payload=payload,
                timeout_seconds=float(self._deps.settings.brand_completion_callback_timeout_seconds),
                retry_delays_seconds=_RETRY_DELAYS_SECONDS,
                post_callback=self._send_callback_request,
                missing_url_error="brand_completion_callback_url 未配置",
                non_2xx_error_message=None,
            )
            if callback_result.get("status") == "success":
                return True
            if callback_result.get("status") == "retrying":
                refreshed_callback = self._deps.upload_tasks.get_upload_task_callback(
                    task_id=task_id,
                    callback_type=callback_type,
                )
                self.schedule_callback_retry(
                    task_id,
                    delay_seconds=int(seconds_until((refreshed_callback or {}).get("next_retry_at"))),
                )
            return False
        finally:
            in_flight.discard(task_id)

    async def maybe_finalize_task_callback_from_document(
        self,
        *,
        category: str,
        file_hash: str,
    ) -> bool:
        record = self._deps.document_registry.get_document_registry_record(
            category=category,
            file_hash=file_hash,
        )
        if not record:
            return False
        task_id = str(record.get("upload_task_id") or "")
        if not task_id:
            return False
        return await self.maybe_finalize_task_callback(task_id)

    def schedule_callback_retry(self, task_id: str, *, delay_seconds: int) -> None:
        scheduled = self._deps.runtime.scheduled_brand_callback_retries
        if task_id in scheduled:
            return

        async def _runner() -> None:
            try:
                await asyncio.sleep(delay_seconds)
                await self.maybe_finalize_task_callback(task_id)
            finally:
                scheduled.discard(task_id)

        scheduled.add(task_id)
        self._deps.spawn_background_task(_runner())

    def schedule_delayed_completion_check(
        self,
        task_id: str,
        *,
        delay_seconds: int = 600,
    ) -> None:
        scheduled = self._deps.runtime.scheduled_brand_completion_checks
        if task_id in scheduled:
            return

        async def _runner() -> None:
            try:
                await asyncio.sleep(delay_seconds)
                await self.maybe_finalize_task_callback(task_id)
            finally:
                scheduled.discard(task_id)

        scheduled.add(task_id)
        self._deps.spawn_background_task(_runner())

    def schedule_due_callback_retries(self) -> None:
        for callback_type in (COMPLETED_CALLBACK_TYPE, STATUS_CALLBACK_TYPE):
            for callback in self._deps.upload_tasks.list_retryable_upload_task_callbacks(
                callback_type=callback_type,
            ):
                task_id = str(callback.get("task_id") or "")
                if not task_id:
                    continue
                self.schedule_callback_retry(task_id, delay_seconds=0)


def bind_brand_callbacks(service: KnowledgeBaseService) -> BrandCallbackCoordinator:
    dependencies = BrandCallbackCoordinatorDependencies(
        settings=service._settings,
        brands=service._brands,
        upload_tasks=service._upload_tasks,
        document_registry=service._document_registry,
        runtime=service._runtime,
        spawn_background_task=service._spawn_background_task,
        extract_brand_knowledge_for_task=lambda *, task_id: extract_brand_knowledge_for_task(
            service,
            task_id=task_id,
        ),
        format_brand_callback_knowledge=lambda task_id, knowledge_payload, knowledge_markdown_payload=None: format_brand_callback_knowledge(
            service,
            task_id,
            knowledge_payload,
            knowledge_markdown_payload=knowledge_markdown_payload,
        ),
        build_current_brand_callback_knowledge=(
            (lambda *, brand_code: build_current_brand_callback_knowledge_for_service(service, brand_code=brand_code))
            if hasattr(service, "_load_brand_knowledge_snapshot")
            else None
        ),
        build_current_brand_knowledge_mete=(
            (lambda *, brand_code: build_current_brand_knowledge_mete_for_service(service, brand_code=brand_code))
            if hasattr(service, "_current_brand_knowledge_mete")
            else None
        ),
        build_attachment_delete_callback_payload=(
            (lambda *, brand: build_attachment_delete_callback_payload_for_service(service, brand=brand))
            if hasattr(service, "_current_brand_knowledge_mete") and hasattr(service, "_load_brand_knowledge_snapshot")
            else None
        ),
        brand_knowledge_sessions=getattr(service, "_brand_knowledge_sessions", None),
        ensure_attachment_conflict_session=(
            (lambda *, task_id: service.start_brand_attachment_conflict_session(task_id=task_id))
            if hasattr(service, "start_brand_attachment_conflict_session")
            else None
        ),
    )
    return BrandCallbackCoordinator(dependencies)


async def _build_callback_payload_with_knowledge(
    service: KnowledgeBaseService,
    task_id: str,
) -> dict[str, Any] | None:
    try:
        result = await bind_brand_callbacks(service).build_callback_payload_with_knowledge(task_id)
        if result is None:
            return None
        _, payload = result
        return payload
    except FullMarkdownNotReadyError:
        return None


async def maybe_finalize_task_callback(service: KnowledgeBaseService, task_id: str) -> bool:
    return await bind_brand_callbacks(service).maybe_finalize_task_callback(task_id)


async def maybe_finalize_task_callback_from_document(
    service: KnowledgeBaseService,
    *,
    category: str,
    file_hash: str,
) -> bool:
    return await bind_brand_callbacks(service).maybe_finalize_task_callback_from_document(
        category=category,
        file_hash=file_hash,
    )


def schedule_callback_retry(service: KnowledgeBaseService, task_id: str, *, delay_seconds: int) -> None:
    bind_brand_callbacks(service).schedule_callback_retry(task_id, delay_seconds=delay_seconds)


def schedule_delayed_completion_check(
    service: KnowledgeBaseService,
    task_id: str,
    *,
    delay_seconds: int = 600,
) -> None:
    bind_brand_callbacks(service).schedule_delayed_completion_check(
        task_id,
        delay_seconds=delay_seconds,
    )


def build_attachment_delete_callback_payload_for_service(
    service: Any,
    *,
    brand: dict[str, Any],
) -> dict[str, Any]:
    knowledge_markdown_status, knowledge_mete = service._current_brand_knowledge_mete(brand=brand)
    knowledge = build_current_brand_callback_knowledge_for_service(
        service,
        brand_code=str(brand.get("brand_code") or "").strip(),
    )
    if not isinstance(knowledge, dict):
        knowledge = format_brand_callback_knowledge_from_snapshot(
            brand=brand,
            knowledge_snapshot=service._load_brand_knowledge_snapshot(brand=brand),
        )
    return {
        "brand_code": str(brand.get("brand_code") or "").strip(),
        "overall_status": "completed",
        "completed_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "knowledge_extraction_status": "success",
        "knowledge_markdown_status": knowledge_markdown_status,
        "knowledge_mete": knowledge_mete,
        "knowledge": knowledge,
    }


def build_current_brand_callback_knowledge_for_service(
    service: Any,
    *,
    brand_code: str,
) -> dict[str, Any] | None:
    normalized_brand_code = str(brand_code or "").strip()
    if not normalized_brand_code:
        return None
    brand = service._brands.get_brand_by_code(normalized_brand_code)
    if not isinstance(brand, dict):
        return None
    snapshot = service._load_brand_knowledge_snapshot(brand=brand)
    return format_brand_callback_knowledge_from_snapshot(
        brand=brand,
        knowledge_snapshot=snapshot,
    )


def build_current_brand_knowledge_mete_for_service(
    service: Any,
    *,
    brand_code: str,
) -> dict[str, str] | None:
    normalized_brand_code = str(brand_code or "").strip()
    if not normalized_brand_code:
        return None
    brand = service._brands.get_brand_by_code(normalized_brand_code)
    if not isinstance(brand, dict):
        return None
    _status, knowledge_mete = service._current_brand_knowledge_mete(brand=brand)
    return knowledge_mete


def _build_current_brand_callback_knowledge(
    service: KnowledgeBaseService,
    *,
    brand_code: str,
) -> dict[str, Any] | None:
    return build_current_brand_callback_knowledge_for_service(
        service,
        brand_code=brand_code,
    )


def _build_current_brand_knowledge_mete(
    service: KnowledgeBaseService,
    *,
    brand_code: str,
) -> dict[str, str] | None:
    return build_current_brand_knowledge_mete_for_service(
        service,
        brand_code=brand_code,
    )


def schedule_due_callback_retries(service: KnowledgeBaseService) -> None:
    bind_brand_callbacks(service).schedule_due_callback_retries()
