from __future__ import annotations

import json
from typing import Any, Optional

import pymysql

from .mysql_base import MySQLStoreBase


class BrandKnowledgeStore(MySQLStoreBase):
    KNOWLEDGE_TYPE_NAMES = {
        "company_profile": "公司档案",
        "management_team": "管理团队",
        "competitors": "竞品信息",
        "attachment_products": "附件解析产品",
        "authority_honors": "权威荣誉",
        "customers_cases": "客户案例",
        "sensitive_topics": "敏感话题",
        "attachments": "附件资料",
        "official_malls": "官方商城",
        "official_media_matrix": "官方媒体与矩阵",
        "other_info": "其他信息",
    }

    def count_brand_knowledge_json(self, *, brand_id: int) -> int:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM brand_knowledge_json
                    WHERE brand_id = %s
                    """,
                    (brand_id,),
                )
                row = cursor.fetchone()
        return int(row[0] or 0) if row else 0

    def delete_brand_knowledge_json(self, *, brand_id: int) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM brand_knowledge_json
                    WHERE brand_id = %s
                    """,
                    (brand_id,),
                )

    def delete_brand_knowledge_type(self, *, brand_id: int, knowledge_type: str) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM brand_knowledge_json
                    WHERE brand_id = %s AND knowledge_type = %s
                    """,
                    (brand_id, knowledge_type),
                )

    def upsert_brand_knowledge_json(
        self,
        *,
        brand_id: int,
        knowledge_type: str,
        knowledge_name: Optional[str] = None,
        content_json: Any,
        source_task_id: Optional[str] = None,
    ) -> None:
        serialized_content = json.dumps(content_json, ensure_ascii=False)
        resolved_knowledge_name = knowledge_name or self.KNOWLEDGE_TYPE_NAMES.get(knowledge_type) or knowledge_type
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO brand_knowledge_json (
                        brand_id,
                        knowledge_type,
                        knowledge_name,
                        content_json,
                        source_task_id
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        knowledge_name = COALESCE(VALUES(knowledge_name), knowledge_name),
                        content_json = VALUES(content_json),
                        source_task_id = COALESCE(VALUES(source_task_id), source_task_id)
                    """,
                    (
                        brand_id,
                        knowledge_type,
                        resolved_knowledge_name,
                        serialized_content,
                        source_task_id,
                    ),
                )

    def get_brand_knowledge_json(
        self,
        *,
        brand_id: int,
        knowledge_type: str,
    ) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, brand_id, knowledge_type, knowledge_name, content_json, source_task_id, created_at, updated_at
                    FROM brand_knowledge_json
                    WHERE brand_id = %s AND knowledge_type = %s
                    LIMIT 1
                    """,
                    (brand_id, knowledge_type),
                )
                row = cursor.fetchone()
        return row or None

    def get_all_brand_knowledge_json(self, *, brand_id: int) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, brand_id, knowledge_type, knowledge_name, content_json, source_task_id, created_at, updated_at
                    FROM brand_knowledge_json
                    WHERE brand_id = %s
                    ORDER BY knowledge_type ASC
                    """,
                    (brand_id,),
                )
                return list(cursor.fetchall())
