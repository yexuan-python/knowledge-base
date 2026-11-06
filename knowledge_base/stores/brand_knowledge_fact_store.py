from __future__ import annotations

from typing import Any

import pymysql

from .mysql_base import MySQLStoreBase


class BrandKnowledgeFactStore(MySQLStoreBase):
    def count_by_brand_code(self, *, brand_code: str) -> int:
        normalized_brand_code = str(brand_code or "").strip()
        if not normalized_brand_code:
            return 0
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM brand_knowledge_facts
                    WHERE brand_code = %s
                    """,
                    (normalized_brand_code,),
                )
                row = cursor.fetchone()
        return int((row or [0])[0] or 0)

    def list_by_brand_code(self, *, brand_code: str) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM brand_knowledge_facts
                    WHERE brand_code = %s
                    ORDER BY id DESC
                    """,
                    (brand_code,),
                )
                return list(cursor.fetchall())

    def get_by_brand_code_and_hash(
        self,
        *,
        brand_code: str,
        normalized_fact_hash: str,
    ) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM brand_knowledge_facts
                    WHERE brand_code = %s AND normalized_fact_hash = %s
                    LIMIT 1
                    """,
                    (brand_code, normalized_fact_hash),
                )
                return cursor.fetchone()

    def upsert_fact(
        self,
        *,
        brand_code: str,
        brand_name: str,
        fact_scope: str = "official_kb",
        fact_id: str,
        fact_text: str,
        normalized_fact_hash: str,
        source_document_id: str,
        source_task_id: str | None = None,
        source_asset_id: int | None = None,
        full_knowledge_file_id: int | None,
        version_no: int | None,
        knowledge_date: str | None,
        section_path: str | None,
    ) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO brand_knowledge_facts (
                        brand_code,
                        brand_name,
                        fact_scope,
                        fact_id,
                        fact_text,
                        normalized_fact_hash,
                        source_document_id,
                        source_task_id,
                        source_asset_id,
                        full_knowledge_file_id,
                        version_no,
                        knowledge_date,
                        section_path
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        brand_name = VALUES(brand_name),
                        fact_scope = VALUES(fact_scope),
                        fact_id = VALUES(fact_id),
                        fact_text = VALUES(fact_text),
                        source_document_id = VALUES(source_document_id),
                        source_task_id = VALUES(source_task_id),
                        source_asset_id = VALUES(source_asset_id),
                        full_knowledge_file_id = VALUES(full_knowledge_file_id),
                        version_no = VALUES(version_no),
                        knowledge_date = VALUES(knowledge_date),
                        section_path = VALUES(section_path),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        brand_code,
                        brand_name,
                        fact_scope,
                        fact_id,
                        fact_text,
                        normalized_fact_hash,
                        source_document_id,
                        source_task_id,
                        source_asset_id,
                        full_knowledge_file_id,
                        version_no,
                        knowledge_date,
                        section_path,
                    ),
                )

    def list_by_source_task_id_and_scope(
        self,
        *,
        source_task_id: str,
        fact_scope: str,
    ) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM brand_knowledge_facts
                    WHERE source_task_id = %s
                      AND fact_scope = %s
                    ORDER BY id DESC
                    """,
                    (source_task_id, fact_scope),
                )
                return list(cursor.fetchall())

    def delete_by_source_task_id_and_scope(
        self,
        *,
        source_task_id: str,
        fact_scope: str,
    ) -> int:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM brand_knowledge_facts
                    WHERE source_task_id = %s
                      AND fact_scope = %s
                    """,
                    (source_task_id, fact_scope),
                )
                return int(cursor.rowcount or 0)

    def delete_by_brand_code(self, *, brand_code: str) -> int:
        normalized_brand_code = str(brand_code or "").strip()
        if not normalized_brand_code:
            return 0
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM brand_knowledge_facts
                    WHERE brand_code = %s
                    """,
                    (normalized_brand_code,),
                )
                return int(cursor.rowcount or 0)

    def delete_by_brand_code_excluding_document(
        self,
        *,
        brand_code: str,
        keep_document_id: str,
    ) -> int:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM brand_knowledge_facts
                    WHERE brand_code = %s
                      AND source_document_id <> %s
                    """,
                    (brand_code, keep_document_id),
                )
                return int(cursor.rowcount or 0)
