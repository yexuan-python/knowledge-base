from __future__ import annotations

import json
from typing import Any, Optional

import pymysql

from .mysql_base import MySQLStoreBase


class BrandFullKnowledgeStore(MySQLStoreBase):
    _SELECT_COLUMNS = """
        brand_full_knowledge_files.id,
        brand_full_knowledge_files.brand_id,
        brand_full_knowledge_files.brand_code,
        brand_full_knowledge_files.brand_name,
        brand_full_knowledge_files.version_no,
        brand_full_knowledge_files.knowledge_date,
        brand_full_knowledge_files.revision_no,
        brand_full_knowledge_files.file_name,
        brand_full_knowledge_files.source_ext,
        brand_full_knowledge_files.pdf_file_name,
        brand_full_knowledge_files.oss_key,
        brand_full_knowledge_files.oss_url,
        brand_full_knowledge_files.pdf_oss_key,
        brand_full_knowledge_files.pdf_oss_url,
        brand_full_knowledge_files.content_markdown,
        brand_full_knowledge_files.content_hash,
        brand_full_knowledge_files.document_id,
        brand_full_knowledge_files.is_latest,
        brand_full_knowledge_files.ingest_status,
        brand_full_knowledge_files.milvus_status,
        brand_full_knowledge_files.facts_status,
        brand_full_knowledge_files.conflict_count,
        brand_full_knowledge_files.conflicts_json,
        brand_full_knowledge_files.source_task_id,
        brand_full_knowledge_files.change_origin,
        brand_full_knowledge_files.error_message,
        brand_full_knowledge_files.created_at,
        brand_full_knowledge_files.updated_at
    """

    def get_latest_by_brand_id(self, *, brand_id: int) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._SELECT_COLUMNS}
                    FROM brand_full_knowledge_files
                    WHERE brand_id = %s
                      AND COALESCE(ingest_status, '') <> 'skipped'
                    ORDER BY is_latest DESC, version_no DESC, revision_no DESC, id DESC
                    LIMIT 1
                    """,
                    (brand_id,),
                )
                row = cursor.fetchone()
        return row or None

    def get_by_brand_code_and_task_id(
        self,
        *,
        brand_code: str,
        source_task_id: str,
    ) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        {self._SELECT_COLUMNS},
                        COALESCE(brand_full_knowledge_files.brand_code, brands.brand_code) AS resolved_brand_code
                    FROM brand_full_knowledge_files
                    LEFT JOIN brands ON brands.id = brand_full_knowledge_files.brand_id
                    WHERE COALESCE(brand_full_knowledge_files.brand_code, brands.brand_code) = %s
                      AND brand_full_knowledge_files.source_task_id = %s
                    LIMIT 1
                    """,
                    (brand_code, source_task_id),
                )
                row = cursor.fetchone()
        if row and not row.get("brand_code") and row.get("resolved_brand_code"):
            row["brand_code"] = row["resolved_brand_code"]
        if row is not None:
            row.pop("resolved_brand_code", None)
        return row or None

    def get_by_brand_code_source_task_file(
        self,
        *,
        brand_code: str,
        source_task_id: str,
        file_name: str,
    ) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        {self._SELECT_COLUMNS},
                        COALESCE(brand_full_knowledge_files.brand_code, brands.brand_code) AS resolved_brand_code
                    FROM brand_full_knowledge_files
                    LEFT JOIN brands ON brands.id = brand_full_knowledge_files.brand_id
                    WHERE COALESCE(brand_full_knowledge_files.brand_code, brands.brand_code) = %s
                      AND brand_full_knowledge_files.source_task_id = %s
                      AND brand_full_knowledge_files.file_name = %s
                    LIMIT 1
                    """,
                    (brand_code, source_task_id, file_name),
                )
                row = cursor.fetchone()
        if row and not row.get("brand_code") and row.get("resolved_brand_code"):
            row["brand_code"] = row["resolved_brand_code"]
        if row is not None:
            row.pop("resolved_brand_code", None)
        return row or None

    def get_by_brand_id_and_task_id(
        self,
        *,
        brand_id: int,
        source_task_id: str,
    ) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._SELECT_COLUMNS}
                    FROM brand_full_knowledge_files
                    WHERE brand_id = %s AND source_task_id = %s
                    LIMIT 1
                    """,
                    (brand_id, source_task_id),
                )
                row = cursor.fetchone()
        return row or None

    def list_by_brand_id(self, *, brand_id: int) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._SELECT_COLUMNS}
                    FROM brand_full_knowledge_files
                    WHERE brand_id = %s
                    ORDER BY version_no ASC, id ASC
                    """,
                    (brand_id,),
                )
                return list(cursor.fetchall())

    def list_by_brand_code(self, *, brand_code: str) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        {self._SELECT_COLUMNS},
                        COALESCE(brand_full_knowledge_files.brand_code, brands.brand_code) AS resolved_brand_code
                    FROM brand_full_knowledge_files
                    LEFT JOIN brands ON brands.id = brand_full_knowledge_files.brand_id
                    WHERE COALESCE(brand_full_knowledge_files.brand_code, brands.brand_code) = %s
                    ORDER BY brand_full_knowledge_files.version_no ASC, brand_full_knowledge_files.id ASC
                    """,
                    (brand_code,),
                )
                rows = list(cursor.fetchall())
        for row in rows:
            if not row.get("brand_code") and row.get("resolved_brand_code"):
                row["brand_code"] = row["resolved_brand_code"]
            row.pop("resolved_brand_code", None)
        return rows

    def delete_by_brand_id(self, *, brand_id: int) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM brand_full_knowledge_files
                    WHERE brand_id = %s
                    """,
                    (brand_id,),
                )

    def delete_by_brand_code(self, *, brand_code: str) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM brand_full_knowledge_files
                    WHERE brand_code = %s
                       OR brand_id IN (
                           SELECT id FROM brands WHERE brand_code = %s
                       )
                    """,
                    (brand_code, brand_code),
                )

    def get_next_version_no(self, *, brand_id: int) -> int:
        latest = self.get_latest_by_brand_id(brand_id=brand_id)
        if not latest:
            return 1
        return int(latest.get("version_no") or 0) + 1

    def get_next_version_no_by_brand_code(self, *, brand_code: str) -> int:
        latest = self.get_latest_by_brand_code(brand_code=brand_code)
        if not latest:
            return 1
        return int(latest.get("version_no") or 0) + 1

    def get_latest_by_brand_code(self, *, brand_code: str) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        {self._SELECT_COLUMNS},
                        COALESCE(brand_full_knowledge_files.brand_code, brands.brand_code) AS resolved_brand_code
                    FROM brand_full_knowledge_files
                    LEFT JOIN brands ON brands.id = brand_full_knowledge_files.brand_id
                    WHERE COALESCE(brand_full_knowledge_files.brand_code, brands.brand_code) = %s
                      AND COALESCE(brand_full_knowledge_files.ingest_status, '') <> 'skipped'
                    ORDER BY
                        brand_full_knowledge_files.is_latest DESC,
                        brand_full_knowledge_files.version_no DESC,
                        brand_full_knowledge_files.revision_no DESC,
                        brand_full_knowledge_files.id DESC
                    LIMIT 1
                    """,
                    (brand_code,),
                )
                row = cursor.fetchone()
        if row and not row.get("brand_code") and row.get("resolved_brand_code"):
            row["brand_code"] = row["resolved_brand_code"]
        if row is not None:
            row.pop("resolved_brand_code", None)
        return row or None

    def get_latest_by_brand_code_and_origin(
        self,
        *,
        brand_code: str,
        change_origin: str,
    ) -> Optional[dict[str, Any]]:
        normalized_origin = str(change_origin or "").strip()
        if not normalized_origin:
            return None
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        {self._SELECT_COLUMNS},
                        COALESCE(brand_full_knowledge_files.brand_code, brands.brand_code) AS resolved_brand_code
                    FROM brand_full_knowledge_files
                    LEFT JOIN brands ON brands.id = brand_full_knowledge_files.brand_id
                    WHERE COALESCE(brand_full_knowledge_files.brand_code, brands.brand_code) = %s
                      AND brand_full_knowledge_files.change_origin = %s
                      AND COALESCE(brand_full_knowledge_files.ingest_status, '') <> 'skipped'
                    ORDER BY
                        brand_full_knowledge_files.is_latest DESC,
                        brand_full_knowledge_files.version_no DESC,
                        brand_full_knowledge_files.revision_no DESC,
                        brand_full_knowledge_files.id DESC
                    LIMIT 1
                    """,
                    (brand_code, normalized_origin),
                )
                row = cursor.fetchone()
        if row and not row.get("brand_code") and row.get("resolved_brand_code"):
            row["brand_code"] = row["resolved_brand_code"]
        if row is not None:
            row.pop("resolved_brand_code", None)
        return row or None

    def get_latest_by_brand_code_and_origin_including_skipped(
        self,
        *,
        brand_code: str,
        change_origin: str,
    ) -> Optional[dict[str, Any]]:
        normalized_origin = str(change_origin or "").strip()
        if not normalized_origin:
            return None
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        {self._SELECT_COLUMNS},
                        COALESCE(brand_full_knowledge_files.brand_code, brands.brand_code) AS resolved_brand_code
                    FROM brand_full_knowledge_files
                    LEFT JOIN brands ON brands.id = brand_full_knowledge_files.brand_id
                    WHERE COALESCE(brand_full_knowledge_files.brand_code, brands.brand_code) = %s
                      AND brand_full_knowledge_files.change_origin = %s
                    ORDER BY
                        brand_full_knowledge_files.version_no DESC,
                        brand_full_knowledge_files.knowledge_date DESC,
                        brand_full_knowledge_files.revision_no DESC,
                        brand_full_knowledge_files.id DESC
                    LIMIT 1
                    """,
                    (brand_code, normalized_origin),
                )
                row = cursor.fetchone()
        if row and not row.get("brand_code") and row.get("resolved_brand_code"):
            row["brand_code"] = row["resolved_brand_code"]
        if row is not None:
            row.pop("resolved_brand_code", None)
        return row or None

    def get_latest_by_brand_id_and_origin(
        self,
        *,
        brand_id: int,
        change_origin: str,
    ) -> Optional[dict[str, Any]]:
        normalized_origin = str(change_origin or "").strip()
        if not normalized_origin:
            return None
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._SELECT_COLUMNS}
                    FROM brand_full_knowledge_files
                    WHERE brand_id = %s
                      AND change_origin = %s
                      AND COALESCE(ingest_status, '') <> 'skipped'
                    ORDER BY is_latest DESC, version_no DESC, revision_no DESC, id DESC
                    LIMIT 1
                    """,
                    (brand_id, normalized_origin),
                )
                row = cursor.fetchone()
        return row or None

    def get_latest_by_brand_id_and_origin_including_skipped(
        self,
        *,
        brand_id: int,
        change_origin: str,
    ) -> Optional[dict[str, Any]]:
        normalized_origin = str(change_origin or "").strip()
        if not normalized_origin:
            return None
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._SELECT_COLUMNS}
                    FROM brand_full_knowledge_files
                    WHERE brand_id = %s
                      AND change_origin = %s
                    ORDER BY version_no DESC, knowledge_date DESC, revision_no DESC, id DESC
                    LIMIT 1
                    """,
                    (brand_id, normalized_origin),
                )
                row = cursor.fetchone()
        return row or None

    def get_latest_version_no_by_brand_code(self, *, brand_code: str) -> int | None:
        latest = self.get_latest_by_brand_code(brand_code=brand_code)
        if not latest:
            return None
        return int(latest.get("version_no") or 0) or None

    def get_by_brand_code_and_content_hash(
        self,
        *,
        brand_code: str,
        content_hash: str,
    ) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        {self._SELECT_COLUMNS},
                        COALESCE(brand_full_knowledge_files.brand_code, brands.brand_code) AS resolved_brand_code
                    FROM brand_full_knowledge_files
                    LEFT JOIN brands ON brands.id = brand_full_knowledge_files.brand_id
                    WHERE COALESCE(brand_full_knowledge_files.brand_code, brands.brand_code) = %s
                      AND brand_full_knowledge_files.content_hash = %s
                    ORDER BY brand_full_knowledge_files.id DESC
                    LIMIT 1
                    """,
                    (brand_code, content_hash),
                )
                row = cursor.fetchone()
        if row and not row.get("brand_code") and row.get("resolved_brand_code"):
            row["brand_code"] = row["resolved_brand_code"]
        if row is not None:
            row.pop("resolved_brand_code", None)
        return row or None

    def get_by_ids(self, *, file_ids: list[int]) -> dict[int, dict[str, Any]]:
        normalized_ids = [int(file_id) for file_id in file_ids if int(file_id) > 0]
        if not normalized_ids:
            return {}
        placeholders = ", ".join(["%s"] * len(normalized_ids))
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._SELECT_COLUMNS}
                    FROM brand_full_knowledge_files
                    WHERE id IN ({placeholders})
                    """,
                    normalized_ids,
                )
                rows = cursor.fetchall()
        return {
            int(row["id"]): row
            for row in rows
            if row.get("id") is not None
        }

    def get_next_revision_no(
        self,
        *,
        brand_code: str,
        version_no: int,
        knowledge_date: str,
    ) -> int:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT MAX(revision_no)
                    FROM brand_full_knowledge_files
                    WHERE brand_code = %s
                      AND version_no = %s
                      AND knowledge_date = %s
                    """,
                    (brand_code, version_no, knowledge_date),
                )
                row = cursor.fetchone()
        latest_revision = int((row or [0])[0] or 0)
        return latest_revision + 1

    def list_old_document_ids(
        self,
        *,
        brand_code: str,
        keep_document_id: str | None = None,
    ) -> list[str]:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                if keep_document_id:
                    cursor.execute(
                        """
                        SELECT document_id
                        FROM brand_full_knowledge_files
                        WHERE brand_code = %s
                          AND document_id IS NOT NULL
                          AND document_id <> %s
                        ORDER BY id DESC
                        """,
                        (brand_code, keep_document_id),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT document_id
                        FROM brand_full_knowledge_files
                        WHERE brand_code = %s
                          AND document_id IS NOT NULL
                        ORDER BY id DESC
                        """,
                        (brand_code,),
                    )
                return [str(row[0]) for row in cursor.fetchall() if row and row[0]]

    def create_brand_full_knowledge_file(
        self,
        *,
        brand_id: int,
        brand_code: str | None = None,
        brand_name: str,
        version_no: int,
        knowledge_date: str | None = None,
        revision_no: int = 1,
        file_name: str,
        source_ext: str | None = None,
        pdf_file_name: str | None,
        oss_key: str | None,
        oss_url: str | None,
        pdf_oss_key: str | None,
        pdf_oss_url: str | None,
        content_markdown: str,
        content_hash: str | None = None,
        document_id: str | None = None,
        is_latest: bool = False,
        ingest_status: str | None = None,
        milvus_status: str | None = None,
        facts_status: str | None = None,
        conflict_count: int,
        conflicts_json: Any,
        source_task_id: str | None,
        change_origin: str = "frontend",
        error_message: str | None = None,
    ) -> int:
        serialized_conflicts = json.dumps(conflicts_json, ensure_ascii=False) if conflicts_json is not None else None
        normalized_change_origin = str(change_origin or "frontend").strip() or "frontend"
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO brand_full_knowledge_files (
                        brand_id,
                        brand_code,
                        brand_name,
                        version_no,
                        knowledge_date,
                        revision_no,
                        file_name,
                        source_ext,
                        pdf_file_name,
                        oss_key,
                        oss_url,
                        pdf_oss_key,
                        pdf_oss_url,
                        content_markdown,
                        content_hash,
                        document_id,
                        is_latest,
                        ingest_status,
                        milvus_status,
                        facts_status,
                        conflict_count,
                        conflicts_json,
                        source_task_id,
                        change_origin,
                        error_message
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        brand_id,
                        brand_code,
                        brand_name,
                        version_no,
                        knowledge_date,
                        revision_no,
                        file_name,
                        source_ext,
                        pdf_file_name,
                        oss_key,
                        oss_url,
                        pdf_oss_key,
                        pdf_oss_url,
                        content_markdown,
                        content_hash,
                        document_id,
                        1 if is_latest else 0,
                        ingest_status,
                        milvus_status,
                        facts_status,
                        conflict_count,
                        serialized_conflicts,
                        source_task_id,
                        normalized_change_origin,
                        error_message,
                    ),
                )
                return int(cursor.lastrowid)

    def promote_latest(
        self,
        *,
        brand_code: str,
        file_id: int,
        knowledge_revision: str | None = None,
    ) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE brand_full_knowledge_files
                    SET is_latest = 0
                    WHERE brand_code = %s
                    """,
                    (brand_code,),
                )
                cursor.execute(
                    """
                    UPDATE brand_full_knowledge_files
                    SET is_latest = 1
                    WHERE id = %s
                    """,
                    (file_id,),
                )
                if knowledge_revision is not None:
                    cursor.execute(
                        """
                        UPDATE brands
                        SET knowledge_revision = %s
                        WHERE brand_code = %s
                        """,
                        (knowledge_revision, brand_code),
                    )

    def update_ingestion_result(
        self,
        *,
        file_id: int,
        document_id: str | None = None,
        content_hash: str | None = None,
        ingest_status: str | None = None,
        milvus_status: str | None = None,
        facts_status: str | None = None,
        error_message: str | None = None,
    ) -> None:
        assignments: list[str] = []
        params: list[Any] = []
        updates = {
            "document_id": document_id,
            "content_hash": content_hash,
            "ingest_status": ingest_status,
            "milvus_status": milvus_status,
            "facts_status": facts_status,
            "error_message": error_message,
        }
        for column_name, column_value in updates.items():
            if column_value is None:
                continue
            assignments.append(f"{column_name} = %s")
            params.append(column_value)
        if not assignments:
            return
        params.append(file_id)
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE brand_full_knowledge_files
                    SET {', '.join(assignments)}
                    WHERE id = %s
                    """,
                    params,
                )

    def update_storage_assets(
        self,
        *,
        file_id: int,
        oss_key: str | None = None,
        oss_url: str | None = None,
        pdf_oss_key: str | None = None,
        pdf_oss_url: str | None = None,
    ) -> None:
        assignments: list[str] = []
        params: list[Any] = []
        updates = {
            "oss_key": oss_key,
            "oss_url": oss_url,
            "pdf_oss_key": pdf_oss_key,
            "pdf_oss_url": pdf_oss_url,
        }
        for column_name, column_value in updates.items():
            if column_value is None:
                continue
            assignments.append(f"{column_name} = %s")
            params.append(column_value)
        if not assignments:
            return
        params.append(file_id)
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE brand_full_knowledge_files
                    SET {', '.join(assignments)}
                    WHERE id = %s
                    """,
                    params,
                )
