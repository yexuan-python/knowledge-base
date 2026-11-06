from __future__ import annotations

from typing import Any

import pymysql

from .mysql_base import MySQLStoreBase


class BrandKnowledgeIngestionJobStore(MySQLStoreBase):
    def create_job(
        self,
        *,
        job_id: str,
        brand_code: str,
        brand_name: str,
        version_no: int,
        knowledge_date: str,
        revision_no: int,
        original_filename: str,
        source_ext: str | None,
        force_reingest: bool,
        status: str = "waiting",
        current_step: str | None = None,
        full_knowledge_file_id: int | None = None,
        document_id: str | None = None,
        content_hash: str | None = None,
    ) -> int:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO brand_knowledge_ingestion_jobs (
                        job_id,
                        brand_code,
                        brand_name,
                        full_knowledge_file_id,
                        document_id,
                        version_no,
                        knowledge_date,
                        revision_no,
                        original_filename,
                        source_ext,
                        content_hash,
                        force_reingest,
                        status,
                        current_step
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        id = LAST_INSERT_ID(id)
                    """,
                    (
                        job_id,
                        brand_code,
                        brand_name,
                        full_knowledge_file_id,
                        document_id,
                        version_no,
                        knowledge_date,
                        revision_no,
                        original_filename,
                        source_ext,
                        content_hash,
                        1 if force_reingest else 0,
                        status,
                        current_step,
                    ),
                )
                return int(cursor.lastrowid)

    def get_job(self, *, job_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM brand_knowledge_ingestion_jobs
                    WHERE job_id = %s
                    LIMIT 1
                    """,
                    (job_id,),
                )
                return cursor.fetchone()

    def update_job_status(
        self,
        *,
        job_id: str,
        status: str,
        current_step: str | None = None,
        parse_status: str | None = None,
        pdf_status: str | None = None,
        mysql_status: str | None = None,
        milvus_status: str | None = None,
        facts_status: str | None = None,
        cleanup_status: str | None = None,
        error_message: str | None = None,
        full_knowledge_file_id: int | None = None,
        document_id: str | None = None,
        content_hash: str | None = None,
    ) -> None:
        assignments = ["status = %s"]
        params: list[Any] = [status]

        optional_updates = {
            "current_step": current_step,
            "parse_status": parse_status,
            "pdf_status": pdf_status,
            "mysql_status": mysql_status,
            "milvus_status": milvus_status,
            "facts_status": facts_status,
            "cleanup_status": cleanup_status,
            "error_message": error_message,
            "full_knowledge_file_id": full_knowledge_file_id,
            "document_id": document_id,
            "content_hash": content_hash,
        }
        for column_name, column_value in optional_updates.items():
            if column_value is None:
                continue
            assignments.append(f"{column_name} = %s")
            params.append(column_value)

        params.append(job_id)
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE brand_knowledge_ingestion_jobs
                    SET {', '.join(assignments)}
                    WHERE job_id = %s
                    """,
                    params,
                )

    def list_jobs_by_brand_code(self, *, brand_code: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM brand_knowledge_ingestion_jobs
                    WHERE brand_code = %s
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (brand_code, limit),
                )
                return list(cursor.fetchall())

    def count_by_brand_code(self, *, brand_code: str) -> int:
        normalized_brand_code = str(brand_code or "").strip()
        if not normalized_brand_code:
            return 0
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM brand_knowledge_ingestion_jobs
                    WHERE brand_code = %s
                    """,
                    (normalized_brand_code,),
                )
                return int((cursor.fetchone() or [0])[0] or 0)

    def delete_by_brand_code(self, *, brand_code: str) -> int:
        normalized_brand_code = str(brand_code or "").strip()
        if not normalized_brand_code:
            return 0
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM brand_knowledge_ingestion_jobs
                    WHERE brand_code = %s
                    """,
                    (normalized_brand_code,),
                )
                return int(cursor.rowcount or 0)
