from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pymysql

from knowledge_base.infrastructure.settings import Settings

from .mysql_base import MySQLStoreBase


class BackgroundJobStore(MySQLStoreBase):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)

    @staticmethod
    def _dump_json(value: dict[str, Any] | None) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, default=str)

    def upsert_job(
        self,
        *,
        job_id: str,
        job_type: str,
        source_type: str | None,
        source_id: str | None,
        payload_json: dict[str, Any] | None,
        priority: int = 100,
        max_retries: int = 3,
        status: str = "waiting",
        next_retry_at: datetime | None = None,
        reopen_terminal: bool = False,
        restart_completed: bool = False,
    ) -> dict[str, Any]:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO background_jobs (
                        job_id,
                        job_type,
                        source_type,
                        source_id,
                        status,
                        priority,
                        payload_json,
                        result_json,
                        retry_count,
                        max_retries,
                        next_retry_at,
                        locked_by,
                        locked_at,
                        last_error_message,
                        started_at,
                        finished_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, 0, %s, %s, NULL, NULL, NULL, NULL, NULL)
                    ON DUPLICATE KEY UPDATE
                        source_type = VALUES(source_type),
                        payload_json = VALUES(payload_json),
                        priority = VALUES(priority),
                        max_retries = VALUES(max_retries),
                        status = CASE
                            WHEN status = 'processing' THEN status
                            WHEN %s THEN VALUES(status)
                            WHEN status = 'success' THEN status
                            ELSE VALUES(status)
                        END,
                        next_retry_at = CASE
                            WHEN status = 'processing' THEN next_retry_at
                            WHEN %s THEN VALUES(next_retry_at)
                            WHEN status = 'success' THEN next_retry_at
                            ELSE VALUES(next_retry_at)
                        END,
                        last_error_message = CASE
                            WHEN %s AND status <> 'processing' THEN NULL
                            WHEN status = 'success' THEN last_error_message
                            ELSE NULL
                        END,
                        result_json = CASE
                            WHEN %s AND status <> 'processing' THEN NULL
                            ELSE result_json
                        END,
                        retry_count = CASE
                            WHEN %s AND status <> 'processing' THEN 0
                            ELSE retry_count
                        END,
                        locked_by = CASE
                            WHEN %s AND status <> 'processing' THEN NULL
                            ELSE locked_by
                        END,
                        locked_at = CASE
                            WHEN %s AND status <> 'processing' THEN NULL
                            ELSE locked_at
                        END,
                        started_at = CASE
                            WHEN %s AND status <> 'processing' THEN NULL
                            ELSE started_at
                        END,
                        finished_at = CASE
                            WHEN %s AND status <> 'processing' THEN NULL
                            ELSE finished_at
                        END
                    """,
                    (
                        job_id,
                        job_type,
                        source_type,
                        source_id,
                        status,
                        priority,
                        self._dump_json(payload_json),
                        max_retries,
                        next_retry_at,
                        1 if restart_completed else 0,
                        1 if restart_completed else 0,
                        1 if restart_completed else 0,
                        1 if restart_completed else 0,
                        1 if restart_completed else 0,
                        1 if restart_completed else 0,
                        1 if restart_completed else 0,
                        1 if restart_completed else 0,
                        1 if restart_completed else 0,
                    ),
                )
        if source_id:
            existing = self.get_job_by_source(job_type=job_type, source_id=source_id)
            if existing is not None:
                return existing
        return self.get_job(job_id) or {
            "job_id": job_id,
            "job_type": job_type,
            "source_id": source_id,
            "status": status,
        }

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM background_jobs
                    WHERE job_id = %s
                    LIMIT 1
                    """,
                    (job_id,),
                )
                return cursor.fetchone()

    def get_job_by_source(self, *, job_type: str, source_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM background_jobs
                    WHERE job_type = %s AND source_id = %s
                    LIMIT 1
                    """,
                    (job_type, source_id),
                )
                return cursor.fetchone()

    def get_latest_job_by_type_and_brand_code(
        self,
        *,
        job_type: str,
        brand_code: str,
    ) -> dict[str, Any] | None:
        normalized_brand_code = str(brand_code or "").strip()
        if not normalized_brand_code:
            return None
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM background_jobs
                    WHERE job_type = %s
                      AND JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.brand_code')) = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """,
                    (job_type, normalized_brand_code),
                )
                return cursor.fetchone()

    @staticmethod
    def _status_filter_clause(
        statuses: list[str] | None,
        *,
        excluded_statuses: list[str] | None = None,
    ) -> tuple[str, tuple[Any, ...]]:
        normalized_statuses = [str(status or "").strip() for status in (statuses or []) if str(status or "").strip()]
        normalized_excluded_statuses = [
            str(status or "").strip() for status in (excluded_statuses or []) if str(status or "").strip()
        ]
        if normalized_statuses:
            placeholders = ", ".join(["%s"] * len(normalized_statuses))
            return f"WHERE status IN ({placeholders})", tuple(normalized_statuses)
        if normalized_excluded_statuses:
            placeholders = ", ".join(["%s"] * len(normalized_excluded_statuses))
            return f"WHERE status NOT IN ({placeholders})", tuple(normalized_excluded_statuses)
        else:
            return "", ()

    @classmethod
    def _query_filter_clause(
        cls,
        statuses: list[str] | None,
        *,
        excluded_statuses: list[str] | None = None,
        keyword: str | None = None,
        source_ids: list[str] | None = None,
    ) -> tuple[str, tuple[Any, ...]]:
        status_clause, status_params = cls._status_filter_clause(
            statuses,
            excluded_statuses=excluded_statuses,
        )
        clauses: list[str] = []
        params: list[Any] = []
        if status_clause:
            clauses.append(status_clause.removeprefix("WHERE ").strip())
            params.extend(status_params)

        normalized_keyword = str(keyword or "").strip()
        normalized_source_ids = [str(source_id or "").strip() for source_id in (source_ids or [])]
        normalized_source_ids = [source_id for source_id in dict.fromkeys(normalized_source_ids) if source_id]
        keyword_clauses: list[str] = []
        keyword_params: list[Any] = []
        if normalized_keyword:
            like_keyword = f"%{normalized_keyword}%"
            keyword_clauses.extend(
                [
                    "job_id LIKE %s",
                    "job_type LIKE %s",
                    "source_type LIKE %s",
                    "source_id LIKE %s",
                    "status LIKE %s",
                    "last_error_message LIKE %s",
                    "CAST(payload_json AS CHAR) LIKE %s",
                    "CAST(result_json AS CHAR) LIKE %s",
                ]
            )
            keyword_params.extend([like_keyword] * 8)
        if normalized_source_ids:
            placeholders = ", ".join(["%s"] * len(normalized_source_ids))
            keyword_clauses.extend(
                [
                    f"source_id IN ({placeholders})",
                    f"JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.task_id')) IN ({placeholders})",
                    f"JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.source_task_id')) IN ({placeholders})",
                ]
            )
            keyword_params.extend(normalized_source_ids)
            keyword_params.extend(normalized_source_ids)
            keyword_params.extend(normalized_source_ids)
        if keyword_clauses:
            clauses.append("(" + " OR ".join(keyword_clauses) + ")")
            params.extend(keyword_params)

        if not clauses:
            return "", ()
        return "WHERE " + " AND ".join(clauses), tuple(params)

    def list_recent_jobs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        statuses: list[str] | None = None,
        excluded_statuses: list[str] | None = None,
        keyword: str | None = None,
        source_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        normalized_limit = max(1, min(int(limit or 20), 500))
        normalized_offset = max(0, int(offset or 0))
        where_clause, where_params = self._query_filter_clause(
            statuses,
            excluded_statuses=excluded_statuses,
            keyword=keyword,
            source_ids=source_ids,
        )
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT *
                    FROM background_jobs
                    {where_clause}
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (*where_params, normalized_limit, normalized_offset),
                )
                return list(cursor.fetchall())

    def count_jobs(
        self,
        *,
        statuses: list[str] | None = None,
        excluded_statuses: list[str] | None = None,
        keyword: str | None = None,
        source_ids: list[str] | None = None,
    ) -> int:
        where_clause, where_params = self._query_filter_clause(
            statuses,
            excluded_statuses=excluded_statuses,
            keyword=keyword,
            source_ids=source_ids,
        )
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM background_jobs
                    {where_clause}
                    """,
                    where_params,
                )
                return int((cursor.fetchone() or [0])[0] or 0)

    def count_jobs_by_status(
        self,
        *,
        keyword: str | None = None,
        source_ids: list[str] | None = None,
    ) -> dict[str, int]:
        where_clause, where_params = self._query_filter_clause(
            None,
            keyword=keyword,
            source_ids=source_ids,
        )
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT status, COUNT(*)
                    FROM background_jobs
                    {where_clause}
                    GROUP BY status
                    """,
                    where_params or None,
                )
                return {str(status or ""): int(count or 0) for status, count in cursor.fetchall()}

    def list_due_jobs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM background_jobs
                    WHERE (
                            status = 'waiting'
                            AND (
                                next_retry_at IS NULL
                                OR next_retry_at <= CURRENT_TIMESTAMP
                            )
                        )
                       OR (
                            status = 'retrying'
                            AND next_retry_at IS NOT NULL
                            AND next_retry_at <= CURRENT_TIMESTAMP
                       )
                    ORDER BY
                        priority ASC,
                        COALESCE(next_retry_at, created_at) ASC,
                        id ASC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return list(cursor.fetchall())

    def mark_processing(self, *, job_id: str, worker_id: str) -> bool:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE background_jobs
                    SET status = 'processing',
                        locked_by = %s,
                        locked_at = CURRENT_TIMESTAMP,
                        started_at = CURRENT_TIMESTAMP,
                        last_error_message = NULL
                    WHERE job_id = %s
                      AND status IN ('waiting', 'retrying')
                      AND (
                        next_retry_at IS NULL
                        OR next_retry_at <= CURRENT_TIMESTAMP
                      )
                    """,
                    (worker_id, job_id),
                )
                return cursor.rowcount > 0

    def mark_success(
        self,
        *,
        job_id: str,
        result_json: dict[str, Any],
        worker_id: str,
    ) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE background_jobs
                    SET status = 'success',
                        result_json = %s,
                        next_retry_at = NULL,
                        locked_by = NULL,
                        locked_at = NULL,
                        last_error_message = NULL,
                        finished_at = CURRENT_TIMESTAMP
                    WHERE job_id = %s
                      AND locked_by = %s
                    """,
                    (self._dump_json(result_json), job_id, worker_id),
                )

    def mark_retrying(
        self,
        *,
        job_id: str,
        retry_count: int,
        next_retry_at: datetime,
        result_json: dict[str, Any] | None,
        last_error_message: str | None,
        worker_id: str,
    ) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE background_jobs
                    SET status = 'retrying',
                        retry_count = %s,
                        next_retry_at = %s,
                        result_json = COALESCE(%s, result_json),
                        locked_by = NULL,
                        locked_at = NULL,
                        last_error_message = %s
                    WHERE job_id = %s
                      AND locked_by = %s
                    """,
                    (
                        retry_count,
                        next_retry_at,
                        self._dump_json(result_json),
                        last_error_message,
                        job_id,
                        worker_id,
                    ),
                )

    def mark_failed(
        self,
        *,
        job_id: str,
        retry_count: int,
        result_json: dict[str, Any] | None,
        last_error_message: str | None,
        worker_id: str,
    ) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE background_jobs
                    SET status = 'failed',
                        retry_count = %s,
                        next_retry_at = NULL,
                        result_json = COALESCE(%s, result_json),
                        locked_by = NULL,
                        locked_at = NULL,
                        last_error_message = %s,
                        finished_at = CURRENT_TIMESTAMP
                    WHERE job_id = %s
                      AND locked_by = %s
                    """,
                    (
                        retry_count,
                        self._dump_json(result_json),
                        last_error_message,
                        job_id,
                        worker_id,
                    ),
                )

    def reset_processing_jobs(self, *, lock_timeout_seconds: int) -> list[str]:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT job_id
                    FROM background_jobs
                    WHERE status = 'processing'
                      AND locked_at IS NOT NULL
                      AND locked_at <= DATE_SUB(CURRENT_TIMESTAMP, INTERVAL %s SECOND)
                    ORDER BY updated_at ASC
                    """,
                    (lock_timeout_seconds,),
                )
                job_ids = [str(row[0]) for row in cursor.fetchall()]
                cursor.execute(
                    """
                    UPDATE background_jobs
                    SET status = 'waiting',
                        locked_by = NULL,
                        locked_at = NULL,
                        started_at = NULL
                    WHERE status = 'processing'
                      AND locked_at IS NOT NULL
                      AND locked_at <= DATE_SUB(CURRENT_TIMESTAMP, INTERVAL %s SECOND)
                    """,
                    (lock_timeout_seconds,),
                )
                return job_ids

    @staticmethod
    def _brand_job_predicate(
        *,
        brand_code: str | None,
        brand_name: str | None,
        source_ids: list[str] | None = None,
    ) -> tuple[str, tuple[Any, ...]] | None:
        normalized_brand_code = str(brand_code or "").strip()
        normalized_brand_name = str(brand_name or "").strip()
        normalized_source_ids = [str(item).strip() for item in (source_ids or []) if str(item).strip()]

        clauses: list[str] = []
        params: list[Any] = []

        if normalized_brand_code:
            clauses.append("JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.brand_code')) = %s")
            params.append(normalized_brand_code)

        if normalized_brand_name:
            clauses.append("JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.brand_name')) = %s")
            params.append(normalized_brand_name)

        if normalized_source_ids:
            placeholders = ", ".join(["%s"] * len(normalized_source_ids))
            clauses.append(f"source_id IN ({placeholders})")
            params.extend(normalized_source_ids)
            clauses.append(f"JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.task_id')) IN ({placeholders})")
            params.extend(normalized_source_ids)
            clauses.append(f"JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.source_task_id')) IN ({placeholders})")
            params.extend(normalized_source_ids)

        if not clauses:
            return None
        return "(" + " OR ".join(clauses) + ")", tuple(params)

    def count_by_brand_identifier(
        self,
        *,
        brand_code: str | None,
        brand_name: str | None,
        source_ids: list[str] | None = None,
    ) -> int:
        predicate_and_params = self._brand_job_predicate(
            brand_code=brand_code,
            brand_name=brand_name,
            source_ids=source_ids,
        )
        if predicate_and_params is None:
            return 0
        predicate, params = predicate_and_params
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM background_jobs
                    WHERE {predicate}
                    """,
                    params,
                )
                return int((cursor.fetchone() or [0])[0] or 0)

    def delete_by_brand_identifier(
        self,
        *,
        brand_code: str | None,
        brand_name: str | None,
        source_ids: list[str] | None = None,
    ) -> int:
        predicate_and_params = self._brand_job_predicate(
            brand_code=brand_code,
            brand_name=brand_name,
            source_ids=source_ids,
        )
        if predicate_and_params is None:
            return 0
        predicate, params = predicate_and_params
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    DELETE FROM background_jobs
                    WHERE {predicate}
                    """,
                    params,
                )
                return int(cursor.rowcount or 0)
