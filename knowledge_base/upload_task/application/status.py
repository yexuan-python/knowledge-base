from __future__ import annotations

from typing import Any, Callable

from knowledge_base.shared.utils import parse_metadata_json


class UploadTaskStatusBuilder:
    def __init__(
        self,
        *,
        dependencies: Any,
        normalize_int: Callable[[Any], int | None],
        resolve_metadata_brand_name: Callable[[dict[str, Any]], str | None],
        resolve_brand_ai_knowledge_job_id: Callable[..., str],
    ) -> None:
        self._deps = dependencies
        self._normalize_int = normalize_int
        self._resolve_metadata_brand_name = resolve_metadata_brand_name
        self._resolve_brand_ai_knowledge_job_id = resolve_brand_ai_knowledge_job_id

    def get_upload_task_status(self, task_id: str) -> dict[str, Any] | None:
        self._deps.upload_tasks.refresh_upload_task_counts(task_id)
        task = self._deps.upload_tasks.get_upload_task(task_id)
        if not task:
            return None
        task_metadata = parse_metadata_json(task.get("metadata_json"))
        task_brand_name = self._resolve_metadata_brand_name(task_metadata)
        task_brand_code = str(task_metadata.get("brand_code") or "").strip() or None
        files = self._deps.upload_tasks.get_upload_task_files(task_id)
        full_knowledge_ids = [
            int(item["full_knowledge_file_id"])
            for item in files
            if self._normalize_int(item.get("full_knowledge_file_id")) is not None
        ]
        full_knowledge_map: dict[int, dict[str, Any]] = {}
        if full_knowledge_ids:
            store = getattr(self._deps, "brand_full_knowledge", None)
            if store is not None and hasattr(store, "get_by_ids"):
                full_knowledge_map = store.get_by_ids(file_ids=full_knowledge_ids)

        ingestion_job_map: dict[int, dict[str, Any]] = {}
        ingestion_jobs = getattr(self._deps, "brand_knowledge_ingestion_jobs", None)
        if ingestion_jobs is not None and hasattr(ingestion_jobs, "get_job"):
            for item in files:
                file_id = self._normalize_int(item.get("id"))
                if file_id is None:
                    continue
                job = ingestion_jobs.get_job(
                    job_id=self._resolve_brand_ai_knowledge_job_id(task_id=task_id, file_id=file_id)
                )
                if job is not None:
                    ingestion_job_map[file_id] = job
        knowledge_session = None
        session_store = getattr(self._deps, "brand_knowledge_sessions", None)
        if session_store is not None and hasattr(session_store, "get_latest_by_source_task_id"):
            knowledge_session = session_store.get_latest_by_source_task_id(
                source_task_id=task_id,
                session_kind="attachment_conflict",
            )
        return {
            "task_id": task["task_id"],
            "task_type": task.get("task_type"),
            "status": task["status"],
            "file_count": int(task.get("file_count") or 0),
            "success_count": int(task.get("success_count") or 0),
            "failed_count": int(task.get("failed_count") or 0),
            "pending_count": int(task.get("pending_count") or 0),
            "processing_count": int(task.get("processing_count") or 0),
            "brand_code": task_brand_code,
            "brand_name": task_brand_name,
            "knowledge_session_id": str((knowledge_session or {}).get("session_id") or "").strip() or None,
            "knowledge_session_status": str((knowledge_session or {}).get("status") or "").strip() or None,
            "created_at": task["created_at"].isoformat(sep=" ") if task.get("created_at") else None,
            "updated_at": task["updated_at"].isoformat(sep=" ") if task.get("updated_at") else None,
            "files": [
                self.build_upload_task_file_status(
                    task_brand_code=task_brand_code,
                    task_brand_name=task_brand_name,
                    file_row=item,
                    full_knowledge_map=full_knowledge_map,
                    ingestion_job_map=ingestion_job_map,
                )
                for item in files
            ],
        }

    def build_upload_task_file_status(
        self,
        *,
        task_brand_code: str | None,
        task_brand_name: str | None,
        file_row: dict[str, Any],
        full_knowledge_map: dict[int, dict[str, Any]],
        ingestion_job_map: dict[int, dict[str, Any]],
    ) -> dict[str, Any]:
        file_id = int(file_row["id"])
        full_knowledge_file_id = self._normalize_int(file_row.get("full_knowledge_file_id"))
        full_knowledge_row = full_knowledge_map.get(full_knowledge_file_id or -1, {})
        ingestion_job = ingestion_job_map.get(file_id, {})
        document_id = str(file_row.get("document_id") or "").strip() or None

        row_brand_name = (
            str(full_knowledge_row.get("brand_name") or "").strip()
            or str(ingestion_job.get("brand_name") or "").strip()
            or task_brand_name
        )
        row_brand_code = (
            str(full_knowledge_row.get("brand_code") or "").strip()
            or str(ingestion_job.get("brand_code") or "").strip()
            or task_brand_code
        )

        return {
            "file_id": file_id,
            "file_index": int(file_row["file_index"]),
            "file_name": file_row["original_filename"],
            "file_role": file_row.get("file_role"),
            "status": file_row["status"],
            "file_size": int(file_row["file_size"]) if file_row.get("file_size") is not None else None,
            "file_hash": file_row.get("file_hash"),
            "content_type": file_row.get("content_type"),
            "converted_version": self._normalize_int(file_row.get("converted_version")),
            "document_id": document_id,
            "source_type": file_row.get("source_type"),
            "chunk_count": int(file_row["chunk_count"]) if file_row.get("chunk_count") is not None else None,
            "oss_key": file_row.get("oss_key"),
            "oss_url": file_row.get("oss_url"),
            "knowledge_markdown_oss_url": full_knowledge_row.get("oss_url"),
            "knowledge_pdf_oss_url": full_knowledge_row.get("pdf_oss_url"),
            "asset_id": self._normalize_int(file_row.get("asset_id")),
            "full_knowledge_file_id": full_knowledge_file_id,
            "brand_name": row_brand_name or None,
            "brand_code": row_brand_code or None,
            "current_step": ingestion_job.get("current_step"),
            "parse_status": ingestion_job.get("parse_status"),
            "pdf_status": ingestion_job.get("pdf_status"),
            "ingest_status": full_knowledge_row.get("ingest_status") or ingestion_job.get("status"),
            "mysql_status": ingestion_job.get("mysql_status"),
            "milvus_status": full_knowledge_row.get("milvus_status") or ingestion_job.get("milvus_status"),
            "facts_status": full_knowledge_row.get("facts_status") or ingestion_job.get("facts_status"),
            "cleanup_status": ingestion_job.get("cleanup_status"),
            "is_latest": bool(full_knowledge_row.get("is_latest")) if full_knowledge_row.get("is_latest") is not None else None,
            "error_message": file_row.get("error_message") or full_knowledge_row.get("error_message") or ingestion_job.get("error_message"),
            "facts_error": None,
            "created_at": file_row["created_at"].isoformat(sep=" ") if file_row.get("created_at") else None,
            "updated_at": file_row["updated_at"].isoformat(sep=" ") if file_row.get("updated_at") else None,
        }
