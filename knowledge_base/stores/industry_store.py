from __future__ import annotations

from typing import Any, Optional

import pymysql

from .mysql_base import MySQLStoreBase


class IndustryStore(MySQLStoreBase):
    def list_industries(self) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, code, name, level, created_at
                    FROM industries
                    ORDER BY level ASC, id ASC
                    """
                )
                return list(cursor.fetchall())

    def get_industry_by_id(self, industry_id: int) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, code, name, level, created_at
                    FROM industries
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (industry_id,),
                )
                row = cursor.fetchone()
        return row or None

    def get_industry_by_code(self, code: str) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, code, name, level, created_at
                    FROM industries
                    WHERE code = %s
                    LIMIT 1
                    """,
                    (code,),
                )
                row = cursor.fetchone()
        return row or None

    def upsert_industry(
        self,
        *,
        industry_id: int,
        code: str | None,
        name: str | None,
        level: int = 1,
    ) -> int:
        normalized_code = (code or "").strip() or None
        normalized_name = (name or "").strip() or None
        if industry_id <= 0:
            raise ValueError("industry_id 必须为正整数")
        if not normalized_code and not normalized_name:
            raise ValueError("industry_code 和 industry_name 不能同时为空")

        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO industries (id, code, name, level)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        id = LAST_INSERT_ID(id),
                        code = COALESCE(VALUES(code), code),
                        name = COALESCE(VALUES(name), name),
                        level = COALESCE(VALUES(level), level)
                    """,
                    (
                        industry_id,
                        normalized_code,
                        normalized_name,
                        level,
                    ),
                )
                return int(cursor.lastrowid or industry_id)
