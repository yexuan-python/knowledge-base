from __future__ import annotations

import json
from typing import Any

import pymysql

from .mysql_base import MySQLStoreBase


class BrandKnowledgeSessionStore(MySQLStoreBase):
    @staticmethod
    def _brand_identifier_clause(
        *,
        brand_code: str | None,
        brand_name: str | None,
    ) -> tuple[str, tuple[Any, ...]] | None:
        normalized_brand_code = str(brand_code or "").strip()
        normalized_brand_name = str(brand_name or "").strip()
        clauses: list[str] = []
        params: list[Any] = []
        if normalized_brand_code:
            clauses.append("brand_code = %s")
            params.append(normalized_brand_code)
            clauses.append("brand_id IN (SELECT id FROM brands WHERE brand_code = %s)")
            params.append(normalized_brand_code)
        if normalized_brand_name:
            clauses.append("brand_name = %s")
            params.append(normalized_brand_name)
        if not clauses:
            return None
        return "(" + " OR ".join(clauses) + ")", tuple(params)

    def create_session(
        self,
        *,
        session_id: str,
        brand_id: int | None,
        brand_code: str | None,
        brand_name: str | None,
        source_task_id: str | None,
        session_kind: str,
        status: str,
        current_round: int,
        initial_user_message: str | None,
        latest_user_message: str | None,
        latest_assistant_message: str | None,
        source_documents: list[dict[str, Any]],
    ) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO brand_knowledge_sessions (
                        session_id,
                        brand_id,
                        brand_code,
                        brand_name,
                        source_task_id,
                        session_kind,
                        status,
                        current_round,
                        initial_user_message,
                        latest_user_message,
                        latest_assistant_message,
                        source_documents_json,
                        resolution_history_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        session_id,
                        brand_id,
                        brand_code,
                        brand_name,
                        source_task_id,
                        session_kind,
                        status,
                        current_round,
                        initial_user_message,
                        latest_user_message,
                        latest_assistant_message,
                        json.dumps(source_documents, ensure_ascii=False),
                        json.dumps([], ensure_ascii=False),
                    ),
                )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM brand_knowledge_sessions
                    WHERE session_id = %s
                    LIMIT 1
                    """,
                    (session_id,),
                )
                row = cursor.fetchone()
        return row or None

    def get_latest_by_source_task_id(
        self,
        *,
        source_task_id: str,
        session_kind: str | None = None,
    ) -> dict[str, Any] | None:
        query = """
            SELECT *
            FROM brand_knowledge_sessions
            WHERE source_task_id = %s
        """
        params: list[Any] = [source_task_id]
        if session_kind is not None:
            query += " AND session_kind = %s"
            params.append(session_kind)
        query += " ORDER BY updated_at DESC, id DESC LIMIT 1"
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(query, tuple(params))
                row = cursor.fetchone()
        return row or None

    def get_latest_by_brand_code(
        self,
        *,
        brand_code: str,
        session_kind: str = "attachment_conflict",
        preferred_statuses: list[str] | None = None,
    ) -> dict[str, Any] | None:
        normalized_brand_code = str(brand_code or "").strip()
        if not normalized_brand_code:
            return None

        def _fetch(statuses: list[str] | None) -> dict[str, Any] | None:
            query = """
                SELECT *
                FROM brand_knowledge_sessions
                WHERE brand_code = %s
                  AND session_kind = %s
            """
            params: list[Any] = [normalized_brand_code, session_kind]
            if statuses:
                placeholders = ", ".join(["%s"] * len(statuses))
                query += f" AND status IN ({placeholders})"
                params.extend(statuses)
            query += " ORDER BY updated_at DESC, id DESC LIMIT 1"
            with self._get_conn() as conn:
                with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                    cursor.execute(query, tuple(params))
                    row = cursor.fetchone()
            return row or None

        row = _fetch(preferred_statuses)
        if row is not None or not preferred_statuses:
            return row
        return _fetch(None)

    def update_session_progress(
        self,
        *,
        session_id: str,
        status: str,
        current_round: int,
        latest_draft_markdown: str | None,
        latest_conflicts: list[dict[str, Any]] | None,
        latest_conflict_markdown: str | None,
        latest_scan_summary: str | None = None,
        latest_auto_merged: list[dict[str, Any]] | None = None,
        latest_user_message: str | None = None,
        latest_assistant_message: str | None = None,
        resolution_history: list[dict[str, Any]] | None = None,
        final_markdown: str | None = None,
        final_oss_key: str | None = None,
        final_full_knowledge_file_id: int | None = None,
        final_document_id: str | None = None,
    ) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE brand_knowledge_sessions
                    SET
                        status = %s,
                        current_round = %s,
                        latest_draft_markdown = %s,
                        latest_conflicts_json = %s,
                        latest_conflict_markdown = %s,
                        latest_scan_summary = COALESCE(%s, latest_scan_summary),
                        latest_auto_merged_json = COALESCE(%s, latest_auto_merged_json),
                        latest_user_message = COALESCE(%s, latest_user_message),
                        latest_assistant_message = COALESCE(%s, latest_assistant_message),
                        resolution_history_json = COALESCE(%s, resolution_history_json),
                        final_markdown = COALESCE(%s, final_markdown),
                        final_oss_key = COALESCE(%s, final_oss_key),
                        final_full_knowledge_file_id = COALESCE(%s, final_full_knowledge_file_id),
                        final_document_id = COALESCE(%s, final_document_id)
                    WHERE session_id = %s
                    """,
                    (
                        status,
                        current_round,
                        latest_draft_markdown,
                        json.dumps(latest_conflicts, ensure_ascii=False) if latest_conflicts is not None else None,
                        latest_conflict_markdown,
                        latest_scan_summary,
                        json.dumps(latest_auto_merged, ensure_ascii=False) if latest_auto_merged is not None else None,
                        latest_user_message,
                        latest_assistant_message,
                        json.dumps(resolution_history, ensure_ascii=False) if resolution_history is not None else None,
                        final_markdown,
                        final_oss_key,
                        final_full_knowledge_file_id,
                        final_document_id,
                        session_id,
                    ),
                )

    def create_round(
        self,
        *,
        session_id: str,
        round_no: int,
        stage: str,
        request_payload: dict[str, Any] | None,
        response_payload: dict[str, Any] | None,
        user_message_text: str | None,
        assistant_message_text: str | None,
        draft_markdown: str | None,
        conflicts: list[dict[str, Any]] | None,
        conflict_markdown: str | None,
        user_resolution: list[dict[str, Any]] | None = None,
    ) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO brand_knowledge_session_rounds (
                        session_id,
                        round_no,
                        stage,
                        user_message_text,
                        assistant_message_text,
                        request_payload_json,
                        response_payload_json,
                        draft_markdown,
                        conflicts_json,
                        conflict_markdown,
                        user_resolution_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        session_id,
                        round_no,
                        stage,
                        user_message_text,
                        assistant_message_text,
                        json.dumps(request_payload, ensure_ascii=False) if request_payload is not None else None,
                        json.dumps(response_payload, ensure_ascii=False) if response_payload is not None else None,
                        draft_markdown,
                        json.dumps(conflicts, ensure_ascii=False) if conflicts is not None else None,
                        conflict_markdown,
                        json.dumps(user_resolution, ensure_ascii=False) if user_resolution is not None else None,
                    ),
                )

    def get_rounds(self, session_id: str) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM brand_knowledge_session_rounds
                    WHERE session_id = %s
                    ORDER BY round_no ASC, id ASC
                    """,
                    (session_id,),
                )
                rows = cursor.fetchall()
        return list(rows)

    def count_by_brand_identifier(
        self,
        *,
        brand_code: str | None,
        brand_name: str | None,
    ) -> dict[str, int]:
        clause_and_params = self._brand_identifier_clause(
            brand_code=brand_code,
            brand_name=brand_name,
        )
        if clause_and_params is None:
            return {
                "brand_knowledge_sessions": 0,
                "brand_knowledge_session_rounds": 0,
            }
        clause, params = clause_and_params
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM brand_knowledge_sessions
                    WHERE {clause}
                    """,
                    params,
                )
                session_count = int((cursor.fetchone() or [0])[0] or 0)
                cursor.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM brand_knowledge_session_rounds AS rounds
                    INNER JOIN brand_knowledge_sessions AS sessions
                        ON sessions.session_id = rounds.session_id
                    WHERE {clause}
                    """,
                    params,
                )
                round_count = int((cursor.fetchone() or [0])[0] or 0)
        return {
            "brand_knowledge_sessions": session_count,
            "brand_knowledge_session_rounds": round_count,
        }

    def delete_by_brand_identifier(
        self,
        *,
        brand_code: str | None,
        brand_name: str | None,
    ) -> dict[str, int]:
        clause_and_params = self._brand_identifier_clause(
            brand_code=brand_code,
            brand_name=brand_name,
        )
        if clause_and_params is None:
            return {
                "brand_knowledge_sessions": 0,
                "brand_knowledge_session_rounds": 0,
            }
        clause, params = clause_and_params
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    DELETE rounds
                    FROM brand_knowledge_session_rounds AS rounds
                    INNER JOIN brand_knowledge_sessions AS sessions
                        ON sessions.session_id = rounds.session_id
                    WHERE {clause}
                    """,
                    params,
                )
                deleted_round_count = int(cursor.rowcount or 0)
                cursor.execute(
                    f"""
                    DELETE FROM brand_knowledge_sessions
                    WHERE {clause}
                    """,
                    params,
                )
                deleted_session_count = int(cursor.rowcount or 0)
        return {
            "brand_knowledge_sessions": deleted_session_count,
            "brand_knowledge_session_rounds": deleted_round_count,
        }
