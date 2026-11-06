from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from knowledge_base.shared.utils import parse_metadata_json


logger = logging.getLogger(__name__)

BACKGROUND_JOB_TYPE_BRAND_KNOWLEDGE_UPDATE = "brand_knowledge_update_full_generation"
BACKGROUND_JOB_TYPE_BRAND_FULL_KNOWLEDGE_REFRESH = "brand_full_knowledge_refresh"
BACKGROUND_JOB_TYPE_ATTACHMENT_CONFIRM_PIPELINE = "attachment_confirm_pipeline"
BACKGROUND_JOB_TYPE_ATTACHMENT_CONFIRM = "attachment_confirm_full_generation"
BACKGROUND_JOB_TYPE_ATTACHMENT_CONFLICT_RESOLUTION = "attachment_conflict_resolution"
BACKGROUND_JOB_TYPE_UPLOAD_TASK_PROCESS = "upload_task_process"


@dataclass(frozen=True)
class BrandKnowledgeStatusQueryDependencies:
    background_jobs: Any
    brand_knowledge_update_audits: Any
    get_latest_attachment_conflict_session: Callable[..., dict[str, Any] | None]
    upload_tasks: Any = None


class BrandKnowledgeStatusQueryService:
    def __init__(self, dependencies: BrandKnowledgeStatusQueryDependencies) -> None:
        self._deps = dependencies

    @staticmethod
    def format_background_job_datetime(value: Any) -> str | None:
        if isinstance(value, datetime):
            return value.isoformat(sep=" ")
        return str(value) if value is not None else None

    def _serialize_background_job(self, job: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": str(job.get("job_id") or ""),
            "job_type": str(job.get("job_type") or ""),
            "source_type": job.get("source_type"),
            "source_id": job.get("source_id"),
            "status": str(job.get("status") or ""),
            "priority": int(job.get("priority") or 0),
            "retry_count": int(job.get("retry_count") or 0),
            "max_retries": int(job.get("max_retries") or 0),
            "next_retry_at": self.format_background_job_datetime(job.get("next_retry_at")),
            "locked_by": job.get("locked_by"),
            "locked_at": self.format_background_job_datetime(job.get("locked_at")),
            "last_error_message": job.get("last_error_message"),
            "started_at": self.format_background_job_datetime(job.get("started_at")),
            "finished_at": self.format_background_job_datetime(job.get("finished_at")),
            "created_at": self.format_background_job_datetime(job.get("created_at")),
            "updated_at": self.format_background_job_datetime(job.get("updated_at")),
            "payload": parse_metadata_json(job.get("payload_json")),
            "result": parse_metadata_json(job.get("result_json")),
        }

    def _resolve_background_job_upload_task_id(self, job: dict[str, Any]) -> str:
        if str(job.get("job_type") or "") != BACKGROUND_JOB_TYPE_UPLOAD_TASK_PROCESS:
            return ""
        source_id = str(job.get("source_id") or "").strip()
        if source_id:
            return source_id
        payload = (
            job.get("payload")
            if isinstance(job.get("payload"), dict)
            else parse_metadata_json(job.get("payload_json"))
        )
        return str(payload.get("task_id") or "").strip()

    def _serialize_upload_task_file_summary(self, file_item: dict[str, Any]) -> dict[str, Any]:
        return {
            "file_id": int(file_item.get("id") or file_item.get("file_id") or 0),
            "file_index": int(file_item.get("file_index") or 0),
            "file_name": str(file_item.get("original_filename") or file_item.get("file_name") or ""),
            "file_role": file_item.get("file_role"),
            "status": str(file_item.get("status") or ""),
            "file_size": file_item.get("file_size"),
            "file_hash": file_item.get("file_hash"),
            "content_type": file_item.get("content_type"),
            "converted_version": file_item.get("converted_version"),
            "document_id": file_item.get("document_id"),
            "source_type": file_item.get("source_type"),
            "chunk_count": file_item.get("chunk_count"),
            "asset_id": file_item.get("asset_id"),
            "full_knowledge_file_id": file_item.get("full_knowledge_file_id"),
            "error_message": file_item.get("error_message"),
            "created_at": self.format_background_job_datetime(file_item.get("created_at")),
            "updated_at": self.format_background_job_datetime(file_item.get("updated_at")),
        }

    def _serialize_upload_task_summary(
        self,
        task: dict[str, Any],
        files: list[dict[str, Any]],
    ) -> dict[str, Any]:
        metadata = parse_metadata_json(task.get("metadata_json"))
        brand_name = str(metadata.get("brand_name") or metadata.get("category") or "").strip() or None
        brand_code = str(metadata.get("brand_code") or "").strip() or None
        return {
            "task_id": str(task.get("task_id") or ""),
            "task_type": task.get("task_type"),
            "status": str(task.get("status") or ""),
            "file_count": int(task.get("file_count") or 0),
            "success_count": int(task.get("success_count") or 0),
            "failed_count": int(task.get("failed_count") or 0),
            "pending_count": int(task.get("pending_count") or 0),
            "processing_count": int(task.get("processing_count") or 0),
            "brand_code": brand_code,
            "brand_name": brand_name,
            "metadata": metadata,
            "error_message": task.get("error_message"),
            "created_at": self.format_background_job_datetime(task.get("created_at")),
            "updated_at": self.format_background_job_datetime(task.get("updated_at")),
            "files": [self._serialize_upload_task_file_summary(file_item) for file_item in files],
        }

    def _attach_upload_task_summaries(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        upload_tasks = self._deps.upload_tasks
        if upload_tasks is None:
            return jobs
        list_tasks = getattr(upload_tasks, "get_upload_tasks_by_ids", None)
        list_files = getattr(upload_tasks, "list_upload_task_file_summaries_by_task_ids", None)
        if not callable(list_tasks) or not callable(list_files):
            return jobs

        task_ids = [self._resolve_background_job_upload_task_id(job) for job in jobs]
        task_ids = [task_id for task_id in dict.fromkeys(task_ids) if task_id]
        if not task_ids:
            return jobs

        tasks_by_id = list_tasks(task_ids)
        files_by_task_id = list_files(task_ids)
        enriched_jobs: list[dict[str, Any]] = []
        for job in jobs:
            task_id = self._resolve_background_job_upload_task_id(job)
            task = tasks_by_id.get(task_id) if task_id else None
            enriched_job = dict(job)
            if task:
                enriched_job["upload_task"] = self._serialize_upload_task_summary(
                    task,
                    files_by_task_id.get(task_id, []),
                )
            enriched_jobs.append(enriched_job)
        return enriched_jobs

    def get_background_job(self, job_id: str) -> dict[str, Any] | None:
        normalized_job_id = str(job_id or "").strip()
        if not normalized_job_id or self._deps.background_jobs is None:
            return None
        job = self._deps.background_jobs.get_job(normalized_job_id)
        if not job:
            return None
        return self._attach_upload_task_summaries([self._serialize_background_job(job)])[0]

    def list_background_jobs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if self._deps.background_jobs is None:
            return []
        jobs = self._deps.background_jobs.list_recent_jobs(limit=limit)
        return [self._serialize_background_job(job) for job in jobs]

    def query_background_jobs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        statuses: list[str] | None = None,
        excluded_statuses: list[str] | None = None,
        keyword: str | None = None,
    ) -> dict[str, Any]:
        if self._deps.background_jobs is None:
            return {
                "jobs": [],
                "limit": limit,
                "offset": offset,
                "total": 0,
                "status_counts": {},
            }
        normalized_keyword = str(keyword or "").strip()
        keyword_source_ids: list[str] = []
        search_upload_task_ids = getattr(self._deps.upload_tasks, "search_upload_task_ids", None)
        if normalized_keyword and callable(search_upload_task_ids):
            keyword_source_ids = search_upload_task_ids(normalized_keyword)
        jobs = self._deps.background_jobs.list_recent_jobs(
            limit=limit,
            offset=offset,
            statuses=statuses,
            excluded_statuses=excluded_statuses,
            keyword=normalized_keyword,
            source_ids=keyword_source_ids,
        )
        status_counts = self._deps.background_jobs.count_jobs_by_status(
            keyword=normalized_keyword,
            source_ids=keyword_source_ids,
        )
        status_counts["all"] = self._deps.background_jobs.count_jobs(
            keyword=normalized_keyword,
            source_ids=keyword_source_ids,
        )
        serialized_jobs = [self._serialize_background_job(job) for job in jobs]
        return {
            "jobs": self._attach_upload_task_summaries(serialized_jobs),
            "limit": limit,
            "offset": offset,
            "total": self._deps.background_jobs.count_jobs(
                statuses=statuses,
                excluded_statuses=excluded_statuses,
                keyword=normalized_keyword,
                source_ids=keyword_source_ids,
            ),
            "status_counts": status_counts,
        }

    def get_attachment_confirm_result(self, job_id: str) -> dict[str, Any] | None:
        job = self.get_background_job(job_id)
        if job is None:
            return None
        if str(job.get("job_type") or "") not in {
            BACKGROUND_JOB_TYPE_ATTACHMENT_CONFIRM,
            BACKGROUND_JOB_TYPE_ATTACHMENT_CONFIRM_PIPELINE,
        }:
            raise ValueError("background job 不是附件确认生成任务")

        status = str(job.get("status") or "").strip()
        if status != "success":
            message = status if status in {"waiting", "processing", "retrying", "failed"} else "waiting"
            return {
                "code": -1,
                "message": message,
                "data": None,
            }

        result = job.get("result")
        result_payload = result if isinstance(result, dict) else {}
        callback_payload = (
            result_payload.get("callback_payload")
            if isinstance(result_payload.get("callback_payload"), dict)
            else {}
        )
        knowledge_mete = (
            callback_payload.get("knowledge_mete")
            if isinstance(callback_payload.get("knowledge_mete"), dict)
            else {}
        )
        payload = job.get("payload")
        source_payload = payload if isinstance(payload, dict) else {}
        ai_knowledge_payload = (
            result_payload.get("ai_knowledge_payload")
            if isinstance(result_payload.get("ai_knowledge_payload"), dict)
            else {}
        )
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "version": str(
                    knowledge_mete.get("version")
                    or source_payload.get("knowledge_revision")
                    or result_payload.get("knowledge_revision")
                    or ""
                ).strip(),
                "brand_code": str(
                    result_payload.get("brand_code")
                    or source_payload.get("brand_code")
                    or callback_payload.get("brand_code")
                    or ""
                ).strip()
                or None,
                "brand_id": result_payload.get("brand_id"),
                "brand_name": str(result_payload.get("brand_name") or source_payload.get("brand_name") or "").strip(),
                "updated_sections": list(result_payload.get("updated_sections") or []),
                "knowledge_revision": str(
                    result_payload.get("knowledge_revision")
                    or source_payload.get("knowledge_revision")
                    or ""
                ).strip(),
                "final_markdown_oss_key": str(result_payload.get("final_markdown_oss_key") or "").strip(),
                "final_markdown_oss_url": str(result_payload.get("final_markdown_oss_url") or "").strip(),
                "final_document_id": str(result_payload.get("final_document_id") or "").strip(),
                "original_attachments": list(result_payload.get("original_attachments") or []),
                "attachment_documents": list(result_payload.get("attachment_documents") or []),
                "confirm_callback_status": str(result_payload.get("confirm_callback_status") or "").strip(),
                "full_knowledge_refresh_job_id": str(result_payload.get("full_knowledge_refresh_job_id") or "").strip(),
                "full_knowledge_refresh_status": str(
                    result_payload.get("full_knowledge_refresh_status") or ""
                ).strip(),
                "oss_url_md": str(
                    knowledge_mete.get("oss_url_md")
                    or ai_knowledge_payload.get("knowledge_oss_url_md")
                    or ""
                ).strip(),
                "oss_url_pdf": str(
                    knowledge_mete.get("oss_url_pdf")
                    or ai_knowledge_payload.get("knowledge_oss_url_pdf")
                    or ""
                ).strip(),
            },
        }

    def get_latest_brand_attachment_conflict_session(
        self,
        *,
        brand_code: str,
        brand_name: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_brand_code = str(brand_code or "").strip()
        result = self._deps.get_latest_attachment_conflict_session(
            brand_code=normalized_brand_code,
            brand_name=brand_name,
        )
        if result is None:
            effective_status = self.resolve_latest_brand_update_markdown_status(
                brand_code=normalized_brand_code,
                fallback_status="no_conflicts",
            )
            if effective_status == "no_conflicts":
                return None
            return {
                "brand_code": normalized_brand_code or None,
                "brand_name": self.resolve_latest_brand_update_brand_name(
                    brand_code=normalized_brand_code,
                    fallback_brand_name=brand_name,
                ),
                "status": effective_status,
                "knowledge_markdown_status": effective_status,
            }
        enriched_result = dict(result)
        effective_status = self.resolve_latest_brand_update_markdown_status(
            brand_code=normalized_brand_code,
            fallback_status=str(result.get("status") or ""),
        )
        enriched_result["status"] = effective_status
        enriched_result["knowledge_markdown_status"] = effective_status
        return enriched_result

    def resolve_latest_brand_update_markdown_status(
        self,
        *,
        brand_code: str,
        fallback_status: str | None = None,
    ) -> str:
        normalized_brand_code = str(brand_code or "").strip()
        normalized_fallback_status = str(fallback_status or "").strip()
        if not normalized_brand_code or self._deps.background_jobs is None:
            return normalized_fallback_status or "running"
        pending_audit_count = self.count_pending_full_knowledge_audits(brand_code=normalized_brand_code)
        latest_job = self.get_latest_brand_update_job(brand_code=normalized_brand_code)
        if not isinstance(latest_job, dict):
            if pending_audit_count > 0:
                return "running"
            return normalized_fallback_status or "running"
        status = str(latest_job.get("status") or "").strip()
        if status in {"waiting", "processing", "retrying"}:
            return "running"
        if pending_audit_count > 0:
            return "running"
        if status == "success":
            return "completed"
        if status == "failed":
            return "failed"
        return normalized_fallback_status or "running"

    def count_pending_full_knowledge_audits(self, *, brand_code: str) -> int:
        audit_store = self._deps.brand_knowledge_update_audits
        if audit_store is None or not hasattr(audit_store, "count_unconsumed_for_full_knowledge"):
            return 0
        try:
            return int(
                audit_store.count_unconsumed_for_full_knowledge(
                    brand_code=brand_code,
                    source_types=["knowledge_update", "attachment_confirm"],
                )
                or 0
            )
        except Exception:
            logger.warning("Failed to count pending full knowledge audits brand_code=%s", brand_code, exc_info=True)
            return 0

    def get_latest_brand_update_job(
        self,
        *,
        brand_code: str,
    ) -> dict[str, Any] | None:
        normalized_brand_code = str(brand_code or "").strip()
        if not normalized_brand_code or self._deps.background_jobs is None:
            return None
        get_latest = getattr(self._deps.background_jobs, "get_latest_job_by_type_and_brand_code", None)
        if not callable(get_latest):
            return None
        latest_job: dict[str, Any] | None = None
        latest_sort_key = (datetime.min, 0)
        for job_type in (
            BACKGROUND_JOB_TYPE_BRAND_FULL_KNOWLEDGE_REFRESH,
            BACKGROUND_JOB_TYPE_ATTACHMENT_CONFIRM_PIPELINE,
            BACKGROUND_JOB_TYPE_ATTACHMENT_CONFLICT_RESOLUTION,
            BACKGROUND_JOB_TYPE_BRAND_KNOWLEDGE_UPDATE,
        ):
            job = get_latest(
                job_type=job_type,
                brand_code=normalized_brand_code,
            )
            if not isinstance(job, dict):
                continue
            sort_key = self.background_job_recency_sort_key(job)
            if latest_job is None or sort_key > latest_sort_key:
                latest_job = job
                latest_sort_key = sort_key
        return latest_job

    @staticmethod
    def background_job_recency_sort_key(job: dict[str, Any]) -> tuple[datetime, int]:
        timestamp = (
            BrandKnowledgeStatusQueryService.parse_background_job_datetime(job.get("updated_at"))
            or BrandKnowledgeStatusQueryService.parse_background_job_datetime(job.get("created_at"))
            or BrandKnowledgeStatusQueryService.parse_background_job_datetime(job.get("started_at"))
            or BrandKnowledgeStatusQueryService.parse_background_job_datetime(job.get("finished_at"))
            or datetime.min
        )
        try:
            job_id = int(job.get("id") or 0)
        except (TypeError, ValueError):
            job_id = 0
        return (timestamp, job_id)

    @staticmethod
    def parse_background_job_datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            with suppress(ValueError):
                return datetime.fromisoformat(value)
        return None

    def resolve_latest_brand_update_brand_name(
        self,
        *,
        brand_code: str,
        fallback_brand_name: str | None = None,
    ) -> str:
        normalized_fallback = str(fallback_brand_name or "").strip()
        if normalized_fallback:
            return normalized_fallback
        latest_job = self.get_latest_brand_update_job(brand_code=brand_code)
        if not isinstance(latest_job, dict):
            return ""
        payload = parse_metadata_json(latest_job.get("payload_json"))
        if not isinstance(payload, dict):
            payload = latest_job.get("payload") if isinstance(latest_job.get("payload"), dict) else {}
        return str(payload.get("brand_name") or "").strip()
