from __future__ import annotations

import json
from typing import Any, Optional

import pymysql

from knowledge_base.infrastructure.settings import Settings

from .mysql_base import MySQLStoreBase


class UploadTaskStore(MySQLStoreBase):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)

    def create_upload_task(
        self,
        *,
        task_id: str,
        task_type: str | None = None,
        metadata: dict[str, Any],
        chunk_size: Optional[int],
        chunk_overlap: Optional[int],
        files: list[dict[str, Any]],
    ) -> None:
        file_count = len(files)
        success_count = sum(1 for file in files if file.get("status") == "success")
        failed_count = sum(1 for file in files if file.get("status") == "failed")
        pending_count = sum(1 for file in files if file.get("status", "pending") == "pending")
        processing_count = sum(1 for file in files if file.get("status") == "processing")
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO upload_tasks (
                        task_id,
                        task_type,
                        status,
                        file_count,
                        success_count,
                        failed_count,
                        pending_count,
                        processing_count,
                        metadata_json,
                        chunk_size,
                        chunk_overlap,
                        error_message
                    ) VALUES (%s, %s, 'queued', %s, %s, %s, %s, %s, %s, %s, %s, NULL)
                    """,
                    (
                        task_id,
                        task_type,
                        file_count,
                        success_count,
                        failed_count,
                        pending_count,
                        processing_count,
                        json.dumps(metadata, ensure_ascii=False),
                        chunk_size,
                        chunk_overlap,
                    ),
                )
                cursor.executemany(
                    """
                    INSERT INTO upload_task_files (
                        task_id,
                        file_index,
                        original_filename,
                        file_role,
                        stored_path,
                        file_size,
                        file_hash,
                        converted_version,
                        content_type,
                        status,
                        error_message
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            task_id,
                            file["file_index"],
                            file["original_filename"],
                            file.get("file_role"),
                            file["stored_path"],
                            file.get("file_size"),
                            file.get("file_hash"),
                            file.get("converted_version"),
                            file.get("content_type"),
                            file.get("status", "pending"),
                            file.get("error_message"),
                        )
                        for file in files
                    ],
                )

    def get_upload_task(self, task_id: str) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        task_id,
                        task_type,
                        status,
                        file_count,
                        success_count,
                        failed_count,
                        pending_count,
                        processing_count,
                        metadata_json,
                        chunk_size,
                        chunk_overlap,
                        error_message,
                        created_at,
                        updated_at
                    FROM upload_tasks
                    WHERE task_id = %s
                    """,
                    (task_id,),
                )
                return cursor.fetchone()

    def get_upload_tasks_by_ids(self, task_ids: list[str]) -> dict[str, dict[str, Any]]:
        normalized_task_ids = [str(task_id or "").strip() for task_id in task_ids]
        normalized_task_ids = [task_id for task_id in dict.fromkeys(normalized_task_ids) if task_id]
        if not normalized_task_ids:
            return {}
        placeholders = ", ".join(["%s"] * len(normalized_task_ids))
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        task_id,
                        task_type,
                        status,
                        file_count,
                        success_count,
                        failed_count,
                        pending_count,
                        processing_count,
                        metadata_json,
                        chunk_size,
                        chunk_overlap,
                        error_message,
                        created_at,
                        updated_at
                    FROM upload_tasks
                    WHERE task_id IN ({placeholders})
                    """,
                    tuple(normalized_task_ids),
                )
                return {str(row.get("task_id") or ""): row for row in cursor.fetchall()}

    @staticmethod
    def _brand_identifier_task_predicate(
        *,
        brand_code: str | None,
        brand_name: str | None,
    ) -> tuple[str, tuple[Any, ...]] | None:
        normalized_brand_code = str(brand_code or "").strip()
        normalized_brand_name = str(brand_name or "").strip()
        clauses: list[str] = []
        params: list[Any] = []
        if normalized_brand_code:
            clauses.append("JSON_UNQUOTE(JSON_EXTRACT(metadata_json, '$.brand_code')) = %s")
            params.append(normalized_brand_code)
        if normalized_brand_name:
            clauses.append("JSON_UNQUOTE(JSON_EXTRACT(metadata_json, '$.brand_name')) = %s")
            params.append(normalized_brand_name)
            clauses.append("JSON_UNQUOTE(JSON_EXTRACT(metadata_json, '$.category')) = %s")
            params.append(normalized_brand_name)
        if not clauses:
            return None
        return "(" + " OR ".join(clauses) + ")", tuple(params)

    def list_task_ids_by_brand_identifier(
        self,
        *,
        brand_code: str | None,
        brand_name: str | None,
    ) -> list[str]:
        predicate_and_params = self._brand_identifier_task_predicate(
            brand_code=brand_code,
            brand_name=brand_name,
        )
        if predicate_and_params is None:
            return []
        predicate, params = predicate_and_params
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT task_id
                    FROM upload_tasks
                    WHERE {predicate}
                    ORDER BY created_at ASC, task_id ASC
                    """,
                    params,
                )
                return [str(row[0]) for row in cursor.fetchall() if str((row or [None])[0] or "").strip()]

    def count_by_brand_identifier(
        self,
        *,
        brand_code: str | None,
        brand_name: str | None,
    ) -> dict[str, int]:
        task_ids = self.list_task_ids_by_brand_identifier(
            brand_code=brand_code,
            brand_name=brand_name,
        )
        if not task_ids:
            return {
                "upload_tasks": 0,
                "upload_task_files": 0,
                "upload_task_callbacks": 0,
            }
        placeholders = ", ".join(["%s"] * len(task_ids))
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM upload_task_files
                    WHERE task_id IN ({placeholders})
                    """,
                    tuple(task_ids),
                )
                file_count = int((cursor.fetchone() or [0])[0] or 0)
                cursor.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM upload_task_callbacks
                    WHERE task_id IN ({placeholders})
                    """,
                    tuple(task_ids),
                )
                callback_count = int((cursor.fetchone() or [0])[0] or 0)
        return {
            "upload_tasks": len(task_ids),
            "upload_task_files": file_count,
            "upload_task_callbacks": callback_count,
        }

    def delete_by_brand_identifier(
        self,
        *,
        brand_code: str | None,
        brand_name: str | None,
    ) -> dict[str, int]:
        task_ids = self.list_task_ids_by_brand_identifier(
            brand_code=brand_code,
            brand_name=brand_name,
        )
        if not task_ids:
            return {
                "upload_tasks": 0,
                "upload_task_files": 0,
                "upload_task_callbacks": 0,
            }
        placeholders = ", ".join(["%s"] * len(task_ids))
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    DELETE FROM upload_task_callbacks
                    WHERE task_id IN ({placeholders})
                    """,
                    tuple(task_ids),
                )
                deleted_callback_count = int(cursor.rowcount or 0)
                cursor.execute(
                    f"""
                    DELETE FROM upload_task_files
                    WHERE task_id IN ({placeholders})
                    """,
                    tuple(task_ids),
                )
                deleted_file_count = int(cursor.rowcount or 0)
                cursor.execute(
                    f"""
                    DELETE FROM upload_tasks
                    WHERE task_id IN ({placeholders})
                    """,
                    tuple(task_ids),
                )
                deleted_task_count = int(cursor.rowcount or 0)
        return {
            "upload_tasks": deleted_task_count,
            "upload_task_files": deleted_file_count,
            "upload_task_callbacks": deleted_callback_count,
        }

    def get_upload_task_files(self, task_id: str) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        task_id,
                        file_index,
                        original_filename,
                        file_role,
                        stored_path,
                        file_size,
                        file_hash,
                        converted_version,
                        content_type,
                        status,
                        document_id,
                        source_type,
                        chunk_count,
                        oss_key,
                        oss_url,
                        asset_id,
                        full_knowledge_file_id,
                        error_message,
                        created_at,
                        updated_at
                    FROM upload_task_files
                    WHERE task_id = %s
                    ORDER BY file_index ASC
                    """,
                    (task_id,),
                )
                return cursor.fetchall()

    def list_upload_task_file_summaries_by_task_ids(self, task_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        normalized_task_ids = [str(task_id or "").strip() for task_id in task_ids]
        normalized_task_ids = [task_id for task_id in dict.fromkeys(normalized_task_ids) if task_id]
        if not normalized_task_ids:
            return {}
        placeholders = ", ".join(["%s"] * len(normalized_task_ids))
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        id,
                        task_id,
                        file_index,
                        original_filename,
                        file_role,
                        file_size,
                        file_hash,
                        converted_version,
                        content_type,
                        status,
                        document_id,
                        source_type,
                        chunk_count,
                        asset_id,
                        full_knowledge_file_id,
                        error_message,
                        created_at,
                        updated_at
                    FROM upload_task_files
                    WHERE task_id IN ({placeholders})
                    ORDER BY task_id ASC, file_index ASC
                    """,
                    tuple(normalized_task_ids),
                )
                files_by_task_id: dict[str, list[dict[str, Any]]] = {}
                for row in cursor.fetchall():
                    files_by_task_id.setdefault(str(row.get("task_id") or ""), []).append(row)
                return files_by_task_id

    def search_upload_task_ids(self, keyword: str, *, limit: int = 1000) -> list[str]:
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return []
        normalized_limit = max(1, min(int(limit or 1000), 5000))
        like_keyword = f"%{normalized_keyword}%"
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT t.task_id
                    FROM upload_tasks t
                    LEFT JOIN upload_task_files f ON f.task_id = t.task_id
                    WHERE t.task_id LIKE %s
                       OR t.task_type LIKE %s
                       OR t.status LIKE %s
                       OR t.error_message LIKE %s
                       OR JSON_UNQUOTE(JSON_EXTRACT(t.metadata_json, '$.brand_name')) LIKE %s
                       OR JSON_UNQUOTE(JSON_EXTRACT(t.metadata_json, '$.brand_code')) LIKE %s
                       OR JSON_UNQUOTE(JSON_EXTRACT(t.metadata_json, '$.category')) LIKE %s
                       OR f.original_filename LIKE %s
                       OR f.file_role LIKE %s
                       OR f.status LIKE %s
                       OR f.document_id LIKE %s
                       OR f.source_type LIKE %s
                       OR f.error_message LIKE %s
                    GROUP BY t.task_id
                    ORDER BY MAX(t.updated_at) DESC, MAX(t.created_at) DESC, t.task_id DESC
                    LIMIT %s
                    """,
                    (
                        like_keyword,
                        like_keyword,
                        like_keyword,
                        like_keyword,
                        like_keyword,
                        like_keyword,
                        like_keyword,
                        like_keyword,
                        like_keyword,
                        like_keyword,
                        like_keyword,
                        like_keyword,
                        like_keyword,
                        normalized_limit,
                    ),
                )
                return [str(row[0]) for row in cursor.fetchall() if str((row or [None])[0] or "").strip()]

    def refresh_upload_task_counts(self, task_id: str) -> Optional[dict[str, int]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) AS file_count,
                        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_count,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                        SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_count,
                        SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) AS processing_count
                    FROM upload_task_files
                    WHERE task_id = %s
                    """,
                    (task_id,),
                )
                counts = cursor.fetchone()
                if not counts:
                    return None
                cursor.execute(
                    """
                    UPDATE upload_tasks
                    SET
                        file_count = %s,
                        success_count = %s,
                        failed_count = %s,
                        pending_count = %s,
                        processing_count = %s
                    WHERE task_id = %s
                    """,
                    (
                        counts["file_count"] or 0,
                        counts["success_count"] or 0,
                        counts["failed_count"] or 0,
                        counts["pending_count"] or 0,
                        counts["processing_count"] or 0,
                        task_id,
                    ),
                )
                return {
                    "file_count": int(counts["file_count"] or 0),
                    "success_count": int(counts["success_count"] or 0),
                    "failed_count": int(counts["failed_count"] or 0),
                    "pending_count": int(counts["pending_count"] or 0),
                    "processing_count": int(counts["processing_count"] or 0),
                }

    def update_upload_task_status(
        self,
        task_id: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE upload_tasks
                    SET status = %s, error_message = %s
                    WHERE task_id = %s
                    """,
                    (status, error_message, task_id),
                )

    def update_upload_task_file_status(
        self,
        file_id: int,
        status: str,
        *,
        document_id: Optional[str] = None,
        source_type: Optional[str] = None,
        chunk_count: Optional[int] = None,
        oss_key: Optional[str] = None,
        oss_url: Optional[str] = None,
        asset_id: Optional[int] = None,
        full_knowledge_file_id: Optional[int] = None,
        content_type: Optional[str] = None,
        file_size: Optional[int] = None,
        file_hash: Optional[str] = None,
        converted_version: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE upload_task_files
                    SET
                        status = %s,
                        document_id = %s,
                        source_type = %s,
                        chunk_count = %s,
                        oss_key = %s,
                        oss_url = %s,
                        asset_id = %s,
                        full_knowledge_file_id = %s,
                        content_type = COALESCE(%s, content_type),
                        file_size = COALESCE(%s, file_size),
                        file_hash = COALESCE(%s, file_hash),
                        converted_version = COALESCE(%s, converted_version),
                        error_message = %s
                    WHERE id = %s
                    """,
                    (
                        status,
                        document_id,
                        source_type,
                        chunk_count,
                        oss_key,
                        oss_url,
                        asset_id,
                        full_knowledge_file_id,
                        content_type,
                        file_size,
                        file_hash,
                        converted_version,
                        error_message,
                        file_id,
                    ),
                )

    def list_incomplete_upload_task_ids(self) -> list[str]:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT task_id
                    FROM upload_tasks
                    WHERE status IN ('queued', 'processing')
                    ORDER BY created_at ASC
                    """
                )
                return [row[0] for row in cursor.fetchall()]

    def reset_incomplete_upload_tasks(self) -> list[str]:
        task_ids = self.list_incomplete_upload_task_ids()
        if not task_ids:
            return []

        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE upload_tasks
                    SET status = 'queued', error_message = NULL
                    WHERE status IN ('queued', 'processing')
                    """
                )
                cursor.execute(
                    """
                    UPDATE upload_task_files
                    SET status = 'pending', error_message = NULL
                    WHERE task_id IN (
                        SELECT task_id
                        FROM upload_tasks
                        WHERE status = 'queued'
                    ) AND status = 'processing'
                    """
                )

        return task_ids

    def upsert_upload_task_callback(
        self,
        *,
        task_id: str,
        callback_type: str,
        callback_url: str,
        request_payload_json: dict[str, Any] | None,
        status: str,
    ) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO upload_task_callbacks (
                        task_id,
                        callback_type,
                        callback_url,
                        request_payload_json,
                        status,
                        retry_count,
                        next_retry_at,
                        last_response_code,
                        last_response_body,
                        last_error_message,
                        sent_at
                    )
                    VALUES (%s, %s, %s, %s, %s, 0, NULL, NULL, NULL, NULL, NULL)
                    ON DUPLICATE KEY UPDATE
                        callback_url = VALUES(callback_url),
                        request_payload_json = COALESCE(VALUES(request_payload_json), request_payload_json),
                        status = VALUES(status)
                    """,
                    (
                        task_id,
                        callback_type,
                        callback_url,
                        json.dumps(request_payload_json, ensure_ascii=False)
                        if request_payload_json is not None
                        else None,
                        status,
                    ),
                )

    def get_upload_task_callback(self, *, task_id: str, callback_type: str) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        task_id,
                        callback_type,
                        callback_url,
                        request_payload_json,
                        status,
                        retry_count,
                        next_retry_at,
                        last_response_code,
                        last_response_body,
                        last_error_message,
                        sent_at,
                        created_at,
                        updated_at
                    FROM upload_task_callbacks
                    WHERE task_id = %s AND callback_type = %s
                    LIMIT 1
                    """,
                    (task_id, callback_type),
                )
                return cursor.fetchone()

    def update_upload_task_callback_result(
        self,
        *,
        task_id: str,
        callback_type: str,
        request_payload_json: dict[str, Any] | None = None,
        status: str,
        retry_count: int,
        next_retry_at=None,
        last_response_code: int | None = None,
        last_response_body: str | None = None,
        last_error_message: str | None = None,
        sent_at=None,
    ) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE upload_task_callbacks
                    SET
                        request_payload_json = COALESCE(%s, request_payload_json),
                        status = %s,
                        retry_count = %s,
                        next_retry_at = %s,
                        last_response_code = %s,
                        last_response_body = %s,
                        last_error_message = %s,
                        sent_at = %s
                    WHERE task_id = %s AND callback_type = %s
                    """,
                    (
                        json.dumps(request_payload_json, ensure_ascii=False)
                        if request_payload_json is not None
                        else None,
                        status,
                        retry_count,
                        next_retry_at,
                        last_response_code,
                        last_response_body,
                        last_error_message,
                        sent_at,
                        task_id,
                        callback_type,
                    ),
                )

    def list_retryable_upload_task_callbacks(self, *, callback_type: str) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        task_id,
                        callback_type,
                        callback_url,
                        request_payload_json,
                        status,
                        retry_count,
                        next_retry_at,
                        last_response_code,
                        last_response_body,
                        last_error_message,
                        sent_at,
                        created_at,
                        updated_at
                    FROM upload_task_callbacks
                    WHERE callback_type = %s
                      AND status = 'retrying'
                      AND next_retry_at IS NOT NULL
                      AND next_retry_at <= CURRENT_TIMESTAMP
                    ORDER BY next_retry_at ASC, id ASC
                    """,
                    (callback_type,),
                )
                return list(cursor.fetchall())
