from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

import pymysql

from .mysql_base import MySQLStoreBase


logger = logging.getLogger(__name__)


class DocumentRegistryStore(MySQLStoreBase):
    def get_document_ai_statuses(self, document_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not document_ids:
            return {}

        placeholders = ", ".join(["%s"] * len(document_ids))
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        document_id,
                        facts_status,
                        facts_error
                    FROM document_registry
                    WHERE document_id IN ({placeholders})
                    """,
                    document_ids,
                )
                rows = cursor.fetchall()
        return {
            str(row["document_id"]): {
                "facts_status": row.get("facts_status"),
                "facts_error": row.get("facts_error"),
            }
            for row in rows
        }

    def reserve_document_uploads(
        self,
        *,
        category: str,
        task_id: Optional[str],
        files: list[dict[str, Any]],
        allow_partial: bool = False,
    ) -> dict[str, list[dict[str, Any]]]:
        if not files:
            return {"reserved_files": [], "duplicate_files": []}

        file_hashes = [str(file["file_hash"]) for file in files]
        placeholders = ", ".join(["%s"] * len(file_hashes))
        lock_names = [
            self._build_upload_lock_name(category=category, original_filename=str(name))
            for name in sorted({str(file["original_filename"]) for file in files})
        ]

        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                try:
                    for lock_name in lock_names:
                        cursor.execute("SELECT GET_LOCK(%s, 10) AS acquired", (lock_name,))
                        lock_row = cursor.fetchone() or {}
                        if int(lock_row.get("acquired") or 0) != 1:
                            raise TimeoutError("获取文档版本锁超时，请稍后重试")

                    cursor.execute(
                        f"""
                        SELECT file_hash, original_filename
                        FROM document_registry
                        WHERE category = %s AND file_hash IN ({placeholders})
                        """,
                        [category, *file_hashes],
                    )
                    existing = cursor.fetchall()
                    duplicate_files: list[dict[str, Any]] = []
                    reservable_files = list(files)
                    if existing:
                        existing_hashes = {row["file_hash"] for row in existing}
                        duplicate_files = [
                            file for file in files if file["file_hash"] in existing_hashes
                        ]
                        if not allow_partial:
                            duplicate_list = "、".join(file["original_filename"] for file in duplicate_files)
                            raise ValueError(f"发现相同文件已存在，不能重复上传: {duplicate_list}")
                        reservable_files = [
                            file for file in files if file["file_hash"] not in existing_hashes
                        ]

                    if reservable_files:
                        filenames = [str(file["original_filename"]) for file in reservable_files]
                        filename_placeholders = ", ".join(["%s"] * len(filenames))
                        cursor.execute(
                            f"""
                            SELECT original_filename, MAX(COALESCE(converted_version, 0)) AS max_version
                            FROM document_registry
                            WHERE category = %s AND original_filename IN ({filename_placeholders})
                            GROUP BY original_filename
                            """,
                            [category, *filenames],
                        )
                        existing_versions = {
                            str(row["original_filename"]): int(row["max_version"] or 0)
                            for row in cursor.fetchall()
                        }

                        next_versions = dict(existing_versions)
                        for file in reservable_files:
                            original_filename = str(file["original_filename"])
                            version = next_versions.get(original_filename, 0) + 1
                            file["converted_version"] = version
                            next_versions[original_filename] = version

                        if allow_partial:
                            actually_reserved: list[dict[str, Any]] = []
                            for file in reservable_files:
                                try:
                                    cursor.execute(
                                        """
                                        INSERT INTO document_registry (
                                            document_id,
                                            category,
                                            original_filename,
                                            file_hash,
                                            file_size,
                                            upload_task_id,
                                            converted_version,
                                            is_latest,
                                            status
                                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 'queued')
                                        """,
                                        (
                                            file["reservation_id"],
                                            category,
                                            file["original_filename"],
                                            file["file_hash"],
                                            file.get("file_size"),
                                            task_id,
                                            file.get("converted_version"),
                                        ),
                                    )
                                except pymysql.err.IntegrityError:
                                    duplicate_files.append(file)
                                else:
                                    actually_reserved.append(file)
                            reservable_files = actually_reserved
                        else:
                            cursor.executemany(
                                """
                                INSERT INTO document_registry (
                                    document_id,
                                    category,
                                    original_filename,
                                    file_hash,
                                    file_size,
                                    upload_task_id,
                                    converted_version,
                                    is_latest,
                                    status
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 'queued')
                                """,
                                [
                                    (
                                        file["reservation_id"],
                                        category,
                                        file["original_filename"],
                                        file["file_hash"],
                                        file.get("file_size"),
                                        task_id,
                                        file.get("converted_version"),
                                    )
                                    for file in reservable_files
                                ],
                            )
                except pymysql.err.IntegrityError:
                    duplicate_list = "、".join(file["original_filename"] for file in files)
                    raise ValueError(f"发现相同文件已存在，不能重复上传: {duplicate_list}") from None
                finally:
                    for lock_name in reversed(lock_names):
                        try:
                            cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
                        except Exception:
                            logger.warning("Failed to release upload version lock lock_name=%s", lock_name, exc_info=True)
        return {"reserved_files": reservable_files, "duplicate_files": duplicate_files}

    def document_upload_exists(self, *, category: str, file_hash: str) -> bool:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1
                    FROM document_registry
                    WHERE category = %s AND file_hash = %s
                    LIMIT 1
                    """,
                    (category, file_hash),
                )
                return cursor.fetchone() is not None

    def update_document_registry_status(self, *, category: str, file_hash: str, status: str) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE document_registry
                    SET status = %s
                    WHERE category = %s AND file_hash = %s
                    """,
                    (status, category, file_hash),
                )

    def update_document_registry_upload_result(
        self,
        *,
        category: str,
        file_hash: str,
        original_file_key: str | None,
        source_type: str | None,
        converted_version: int | None,
        status: str,
    ) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE document_registry
                    SET
                        original_file_key = %s,
                        source_type = %s,
                        converted_version = %s,
                        status = %s
                    WHERE category = %s AND file_hash = %s
                    """,
                    (
                        original_file_key,
                        source_type,
                        converted_version,
                        status,
                        category,
                        file_hash,
                    ),
                )

    def update_document_ai_status(
        self,
        *,
        category: str,
        file_hash: str,
        task_type: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        if task_type != "facts":
            raise ValueError(f"Unsupported AI task type: {task_type}")

        status_column = f"{task_type}_status"
        error_column = f"{task_type}_error"
        updated_at_column = f"{task_type}_updated_at"

        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE document_registry
                    SET
                        {status_column} = %s,
                        {error_column} = %s,
                        {updated_at_column} = CURRENT_TIMESTAMP
                    WHERE category = %s AND file_hash = %s
                    """,
                    (status, error_message, category, file_hash),
                )

    def get_document_registry_record(
        self,
        *,
        category: str,
        file_hash: str,
    ) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        document_id,
                        upload_task_id,
                        original_filename,
                        file_hash,
                        facts_status,
                        facts_error,
                        facts_updated_at
                    FROM document_registry
                    WHERE category = %s AND file_hash = %s
                    LIMIT 1
                    """,
                    (category, file_hash),
                )
                return cursor.fetchone()

    def get_document_registry_entry(self, document_id: str) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        document_id,
                        category,
                        original_filename,
                        file_hash,
                        file_size,
                        source_type,
                        source_url,
                        upload_task_id,
                        original_file_key,
                        fulltext_key,
                        converted_version,
                        is_latest,
                        status,
                        created_at,
                        updated_at
                    FROM document_registry
                    WHERE document_id = %s
                    LIMIT 1
                    """,
                    (document_id,),
                )
                return cursor.fetchone()

    def get_document_registry_entries_by_category(self, category: str) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        document_id,
                        category,
                        original_filename,
                        file_hash,
                        file_size,
                        source_type,
                        source_url,
                        upload_task_id,
                        original_file_key,
                        fulltext_key,
                        converted_version,
                        is_latest,
                        status,
                        created_at,
                        updated_at
                    FROM document_registry
                    WHERE category = %s
                    ORDER BY created_at ASC, document_id ASC
                    """,
                    (category,),
                )
                return list(cursor.fetchall())

    def find_latest_success_documents_by_filename(
        self,
        original_filename: str,
        *,
        category: str | None = None,
        source_url: str | None = None,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                document_id,
                category,
                original_filename,
                source_url,
                converted_version,
                is_latest,
                status,
                created_at,
                updated_at
            FROM document_registry
            WHERE original_filename = %s
              AND is_latest = 1
              AND status = 'success'
        """
        params: list[Any] = [original_filename]
        if source_url:
            query += " AND source_url = %s"
            params.append(source_url)
        if category:
            query += " AND category = %s"
            params.append(category)
        query += " ORDER BY updated_at DESC, created_at DESC, document_id DESC"

        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(query, params)
                return list(cursor.fetchall())

    def complete_document_upload(
        self,
        *,
        category: str,
        file_hash: str,
        document_id: str,
        source_type: Optional[str],
        source_url: Optional[str],
        original_file_key: Optional[str],
        fulltext_key: Optional[str],
        converted_version: Optional[int],
    ) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE document_registry
                    SET
                        document_id = %s,
                        source_type = %s,
                        source_url = %s,
                        original_file_key = %s,
                        fulltext_key = %s,
                        converted_version = %s,
                        is_latest = 1,
                        status = 'success'
                    WHERE category = %s AND file_hash = %s
                    """,
                    (
                        document_id,
                        source_type,
                        source_url,
                        original_file_key,
                        fulltext_key,
                        converted_version,
                        category,
                        file_hash,
                    ),
                )
                cursor.execute(
                    """
                    UPDATE document_registry
                    SET is_latest = 0
                    WHERE category = %s
                      AND original_filename = (
                          SELECT original_filename
                          FROM (
                              SELECT original_filename
                              FROM document_registry
                              WHERE category = %s AND file_hash = %s
                              LIMIT 1
                          ) AS current_doc
                      )
                      AND file_hash != %s
                    """,
                    (category, category, file_hash, file_hash),
                )
    def release_document_upload(self, *, category: str, file_hash: str) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM document_registry
                    WHERE category = %s AND file_hash = %s AND status != 'success'
                    """,
                    (category, file_hash),
                )

    def delete_document_registration(self, document_id: str) -> None:
        category: Optional[str] = None
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT category, original_filename, is_latest
                    FROM document_registry
                    WHERE document_id = %s
                    """,
                    (document_id,),
                )
                row = cursor.fetchone()
                cursor.execute("DELETE FROM document_registry WHERE document_id = %s", (document_id,))
                if not row:
                    return
                category, original_filename, was_latest = row
                if was_latest:
                    cursor.execute(
                        """
                        SELECT document_id
                        FROM document_registry
                        WHERE category = %s
                          AND original_filename = %s
                          AND status = 'success'
                        ORDER BY COALESCE(converted_version, 0) DESC, updated_at DESC
                        LIMIT 1
                        """,
                        (category, original_filename),
                    )
                    fallback = cursor.fetchone()
                    if fallback:
                        cursor.execute(
                            "UPDATE document_registry SET is_latest = 1 WHERE document_id = %s",
                            (fallback[0],),
                        )
    def resolve_latest_document_id(self, document_id: str) -> Optional[str]:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT category, original_filename
                    FROM document_registry
                    WHERE document_id = %s
                    """,
                    (document_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                category, original_filename = row
                cursor.execute(
                    """
                    SELECT document_id
                    FROM document_registry
                    WHERE category = %s
                      AND original_filename = %s
                      AND is_latest = 1
                      AND status = 'success'
                    LIMIT 1
                    """,
                    (category, original_filename),
                )
                latest = cursor.fetchone()
                if latest:
                    return latest[0]
                return document_id

    @staticmethod
    def _build_upload_lock_name(*, category: str, original_filename: str) -> str:
        digest = hashlib.sha256(f"{category}\0{original_filename}".encode("utf-8")).hexdigest()
        return f"kb_upload_ver_{digest[:48]}"
