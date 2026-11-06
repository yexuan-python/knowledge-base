from __future__ import annotations

import json
from typing import Any

from .mysql_base import MySQLStoreBase


class BrandKnowledgeUpdateAuditStore(MySQLStoreBase):
    @staticmethod
    def _dump_json(value: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, default=str)

    def create_audit_entries(
        self,
        *,
        audit_id: str,
        brand_id: int,
        brand_code: str | None,
        brand_name: str,
        knowledge_revision: str | None,
        entries: list[dict[str, Any]],
        source_type: str = "knowledge_update",
        source_task_id: str | None = None,
        source_job_id: str | None = None,
        source_name: str | None = None,
        source_oss_key: str | None = None,
    ) -> int:
        rows: list[tuple[Any, ...]] = []
        normalized_source_type = str(source_type or "knowledge_update").strip() or "knowledge_update"
        normalized_source_task_id = str(source_task_id or "").strip() or None
        normalized_source_job_id = str(source_job_id or "").strip() or None
        normalized_source_name = str(source_name or "").strip() or None
        normalized_source_oss_key = str(source_oss_key or "").strip() or None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            section = str(entry.get("section") or "").strip()
            if not section:
                continue
            rows.append(
                (
                    audit_id,
                    brand_id,
                    str(brand_code or "").strip() or None,
                    str(brand_name or "").strip(),
                    str(knowledge_revision or "").strip() or None,
                    section,
                    str(entry.get("title") or section).strip(),
                    str(entry.get("action") or "update").strip(),
                    self._dump_json(entry.get("before")),
                    self._dump_json(entry.get("after")),
                    normalized_source_type,
                    normalized_source_task_id,
                    normalized_source_job_id,
                    normalized_source_name,
                    normalized_source_oss_key,
                )
            )
        if not rows:
            return 0

        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO brand_knowledge_update_audits (
                        audit_id,
                        brand_id,
                        brand_code,
                        brand_name,
                        knowledge_revision,
                        section,
                        section_title,
                        change_action,
                        before_json,
                        after_json,
                        source_type,
                        source_task_id,
                        source_job_id,
                        source_name,
                        source_oss_key
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    rows,
                )
        return len(rows)

    def list_unconsumed_for_full_knowledge(
        self,
        *,
        brand_code: str,
        source_types: list[str] | tuple[str, ...],
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        normalized_brand_code = str(brand_code or "").strip()
        normalized_source_types = [str(item or "").strip() for item in source_types if str(item or "").strip()]
        if not normalized_brand_code or not normalized_source_types:
            return []
        placeholders = ", ".join(["%s"] * len(normalized_source_types))
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT *
                    FROM brand_knowledge_update_audits
                    WHERE brand_code = %s
                      AND source_type IN ({placeholders})
                      AND full_knowledge_job_id IS NULL
                      AND full_knowledge_claimed_job_id IS NULL
                    ORDER BY created_at ASC, id ASC
                    LIMIT %s
                    """,
                    (normalized_brand_code, *normalized_source_types, int(limit)),
                )
                columns = [item[0] for item in cursor.description]
                return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]

    def count_unconsumed_for_full_knowledge(
        self,
        *,
        brand_code: str,
        source_types: list[str] | tuple[str, ...],
    ) -> int:
        normalized_brand_code = str(brand_code or "").strip()
        normalized_source_types = [str(item or "").strip() for item in source_types if str(item or "").strip()]
        if not normalized_brand_code or not normalized_source_types:
            return 0
        placeholders = ", ".join(["%s"] * len(normalized_source_types))
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM brand_knowledge_update_audits
                    WHERE brand_code = %s
                      AND source_type IN ({placeholders})
                      AND full_knowledge_job_id IS NULL
                    """,
                    (normalized_brand_code, *normalized_source_types),
                )
                return int((cursor.fetchone() or [0])[0] or 0)

    def claim_for_full_knowledge(
        self,
        *,
        audit_ids: list[int],
        full_knowledge_job_id: str,
    ) -> int:
        normalized_ids = [int(item) for item in audit_ids if item is not None]
        normalized_job_id = str(full_knowledge_job_id or "").strip()
        if not normalized_ids or not normalized_job_id:
            return 0
        placeholders = ", ".join(["%s"] * len(normalized_ids))
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE brand_knowledge_update_audits
                    SET full_knowledge_claimed_job_id = %s,
                        full_knowledge_claimed_at = CURRENT_TIMESTAMP
                    WHERE id IN ({placeholders})
                      AND full_knowledge_job_id IS NULL
                      AND full_knowledge_claimed_job_id IS NULL
                    """,
                    (normalized_job_id, *normalized_ids),
                )
                return int(cursor.rowcount or 0)

    def mark_full_knowledge_consumed(
        self,
        *,
        audit_ids: list[int],
        full_knowledge_job_id: str,
    ) -> int:
        normalized_ids = [int(item) for item in audit_ids if item is not None]
        normalized_job_id = str(full_knowledge_job_id or "").strip()
        if not normalized_ids or not normalized_job_id:
            return 0
        placeholders = ", ".join(["%s"] * len(normalized_ids))
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE brand_knowledge_update_audits
                    SET full_knowledge_job_id = %s,
                        full_knowledge_consumed_at = CURRENT_TIMESTAMP,
                        full_knowledge_claimed_job_id = NULL,
                        full_knowledge_claimed_at = NULL
                    WHERE id IN ({placeholders})
                    """,
                    (normalized_job_id, *normalized_ids),
                )
                return int(cursor.rowcount or 0)

    def release_full_knowledge_claim(self, *, full_knowledge_job_id: str) -> int:
        normalized_job_id = str(full_knowledge_job_id or "").strip()
        if not normalized_job_id:
            return 0
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE brand_knowledge_update_audits
                    SET full_knowledge_claimed_job_id = NULL,
                        full_knowledge_claimed_at = NULL
                    WHERE full_knowledge_claimed_job_id = %s
                      AND full_knowledge_job_id IS NULL
                    """,
                    (normalized_job_id,),
                )
                return int(cursor.rowcount or 0)
