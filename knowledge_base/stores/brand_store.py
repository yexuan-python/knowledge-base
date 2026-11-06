from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

import pymysql

from .mysql_base import MySQLStoreBase


BRAND_RENAME_MILVUS_SYNC_JOB_TYPE = "brand_rename_milvus_sync"


def _compact_background_job_identity(value: str, *, max_length: int) -> str:
    normalized_value = str(value or "").strip()
    if len(normalized_value) <= max_length:
        return normalized_value
    digest = hashlib.sha256(normalized_value.encode("utf-8")).hexdigest()[:16]
    head_length = max(0, max_length - 17)
    return f"{normalized_value[:head_length]}:{digest}"


def _build_brand_rename_job_identity(*, brand_code: str, new_brand_name: str) -> tuple[str, str]:
    source_id = _compact_background_job_identity(f"{brand_code}:{new_brand_name}", max_length=128)
    job_id = _compact_background_job_identity(
        f"bg:{BRAND_RENAME_MILVUS_SYNC_JOB_TYPE}:{source_id}",
        max_length=128,
    )
    return job_id, source_id


class BrandStore(MySQLStoreBase):
    @staticmethod
    def _dump_json(value: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, default=str)

    def list_brands(self, *, keyword: str | None = None) -> list[dict[str, Any]]:
        normalized_keyword = (keyword or "").strip()
        query = """
            SELECT
                id,
                brand_code,
                brand_name,
                brand_alias,
                website,
                intro,
                updated_at
            FROM brands
        """
        params: list[Any] = []
        if normalized_keyword:
            query += """
                WHERE brand_name LIKE %s
                   OR brand_alias LIKE %s
                   OR brand_code LIKE %s
            """
            like_keyword = f"%{normalized_keyword}%"
            params.extend([like_keyword, like_keyword, like_keyword])
        query += " ORDER BY updated_at DESC, id DESC"

        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(query, params)
                return list(cursor.fetchall())

    def upsert_brand(
        self,
        *,
        brand_code: Optional[str] = None,
        brand_name: str,
        brand_alias: Optional[str] = None,
        brand_logo: Optional[str] = None,
        website: Optional[str] = None,
        customer_service_hotline: Optional[list[str]] = None,
        official_wechat_account: Optional[str] = None,
        intro: Optional[str] = None,
        email: Optional[str] = None,
        brand_enterprise_entity: Optional[str] = None,
        business_license_image_path: Optional[str] = None,
        industry_id: Optional[int] = None,
        knowledge_revision: Optional[str] = None,
        english_name: Optional[str] = None,
        positioning: Optional[list[str]] = None,
        advantages: Optional[list[str]] = None,
        mission: Optional[list[str]] = None,
        vision: Optional[list[str]] = None,
        target_regions: Optional[list[str]] = None,
        other_info: Optional[str] = None,
        competitors: Optional[list[str]] = None,
    ) -> int:
        competitors_json = json.dumps(competitors, ensure_ascii=False) if competitors else None
        serialized_customer_service_hotline = (
            json.dumps(customer_service_hotline, ensure_ascii=False) if customer_service_hotline is not None else None
        )
        serialized_positioning = json.dumps(positioning, ensure_ascii=False) if positioning is not None else None
        serialized_advantages = json.dumps(advantages, ensure_ascii=False) if advantages is not None else None
        serialized_mission = json.dumps(mission, ensure_ascii=False) if mission is not None else None
        serialized_vision = json.dumps(vision, ensure_ascii=False) if vision is not None else None
        target_regions_json = json.dumps(target_regions, ensure_ascii=False) if target_regions is not None else None
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO brands (
                        brand_code,
                        brand_name,
                        brand_alias,
                        brand_logo,
                        website,
                        customer_service_hotline,
                        official_wechat_account,
                        intro,
                        email,
                        brand_enterprise_entity,
                        business_license_image_path,
                        industry_id,
                        knowledge_revision,
                        english_name,
                        positioning,
                        advantages,
                        mission,
                        vision,
                        target_regions_json,
                        other_info,
                        competitors_json
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    ON DUPLICATE KEY UPDATE
                        id = LAST_INSERT_ID(id),
                        brand_code = COALESCE(VALUES(brand_code), brand_code),
                        brand_alias = COALESCE(VALUES(brand_alias), brand_alias),
                        brand_logo = COALESCE(VALUES(brand_logo), brand_logo),
                        website = COALESCE(VALUES(website), website),
                        customer_service_hotline = COALESCE(
                            VALUES(customer_service_hotline),
                            customer_service_hotline
                        ),
                        official_wechat_account = COALESCE(
                            VALUES(official_wechat_account),
                            official_wechat_account
                        ),
                        intro = COALESCE(VALUES(intro), intro),
                        email = COALESCE(VALUES(email), email),
                        brand_enterprise_entity = COALESCE(VALUES(brand_enterprise_entity), brand_enterprise_entity),
                        business_license_image_path = COALESCE(
                            VALUES(business_license_image_path),
                            business_license_image_path
                        ),
                        industry_id = COALESCE(VALUES(industry_id), industry_id),
                        knowledge_revision = COALESCE(VALUES(knowledge_revision), knowledge_revision),
                        english_name = COALESCE(VALUES(english_name), english_name),
                        positioning = COALESCE(VALUES(positioning), positioning),
                        advantages = COALESCE(VALUES(advantages), advantages),
                        mission = COALESCE(VALUES(mission), mission),
                        vision = COALESCE(VALUES(vision), vision),
                        target_regions_json = COALESCE(VALUES(target_regions_json), target_regions_json),
                        other_info = COALESCE(VALUES(other_info), other_info),
                        competitors_json = COALESCE(VALUES(competitors_json), competitors_json)
                    """,
                    (
                        brand_code,
                        brand_name,
                        brand_alias,
                        brand_logo,
                        website,
                        serialized_customer_service_hotline,
                        official_wechat_account,
                        intro,
                        email,
                        brand_enterprise_entity,
                        business_license_image_path,
                        industry_id,
                        knowledge_revision,
                        english_name,
                        serialized_positioning,
                        serialized_advantages,
                        serialized_mission,
                        serialized_vision,
                        target_regions_json,
                        other_info,
                        competitors_json,
                    ),
                )
                return int(cursor.lastrowid)

    def get_brand_by_name(self, brand_name: str) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM brands
                    WHERE brand_name = %s
                    LIMIT 1
                    """,
                    (brand_name,),
                )
                row = cursor.fetchone()
        return row or None

    def get_brand_by_code(self, brand_code: str) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM brands
                    WHERE brand_code = %s
                    LIMIT 1
                    """,
                    (brand_code,),
                )
                row = cursor.fetchone()
        return row or None

    def get_brand_by_id(self, brand_id: int) -> Optional[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM brands
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (brand_id,),
                )
                row = cursor.fetchone()
        return row or None

    def get_brand_id_by_name(self, brand_name: str) -> Optional[int]:
        record = self.get_brand_by_name(brand_name)
        if not record or record.get("id") is None:
            return None
        return int(record["id"])

    def delete_brand(self, *, brand_id: int) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM brands
                    WHERE id = %s
                    """,
                    (brand_id,),
                )

    def rename_brand(
        self,
        *,
        brand_code: str,
        new_brand_name: str,
    ) -> dict[str, Any] | None:
        normalized_brand_code = str(brand_code or "").strip()
        normalized_new_brand_name = str(new_brand_name or "").strip()
        if not normalized_brand_code:
            raise ValueError("brand_code 不能为空")
        if not normalized_new_brand_name:
            raise ValueError("new_brand_name 不能为空")

        existing_brand = self.get_brand_by_code(normalized_brand_code)
        if existing_brand is None or existing_brand.get("id") is None:
            return None

        brand_id = int(existing_brand["id"])
        old_brand_name = str(existing_brand.get("brand_name") or "").strip()
        if not old_brand_name:
            old_brand_name = normalized_new_brand_name
        if old_brand_name == normalized_new_brand_name:
            return {
                "brand_id": brand_id,
                "brand_code": normalized_brand_code,
                "old_brand_name": old_brand_name,
                "brand_name": normalized_new_brand_name,
                "counts": {
                    "brands": 0,
                    "brand_products": 0,
                    "brand_full_knowledge_files": 0,
                    "brand_knowledge_facts": 0,
                    "brand_attachment_assets": 0,
                    "brand_knowledge_ingestion_jobs": 0,
                    "brand_knowledge_sessions": 0,
                    "document_registry": 0,
                    "document_categories": 0,
                    "background_jobs": 0,
                    "upload_tasks": 0,
                },
                "updated_tables": [],
            }

        conflicting_brand = self.get_brand_by_name(normalized_new_brand_name)
        if conflicting_brand is not None and int(conflicting_brand.get("id") or 0) != brand_id:
            raise ValueError("new_brand_name 对应的品牌已存在")

        counts = {
            "brands": 0,
            "brand_products": 0,
            "brand_full_knowledge_files": 0,
            "brand_knowledge_facts": 0,
            "brand_attachment_assets": 0,
            "brand_knowledge_ingestion_jobs": 0,
            "brand_knowledge_sessions": 0,
            "document_registry": 0,
            "document_categories": 0,
            "background_jobs": 0,
            "upload_tasks": 0,
        }
        rename_job_id, rename_job_source_id = _build_brand_rename_job_identity(
            brand_code=normalized_brand_code,
            new_brand_name=normalized_new_brand_name,
        )
        rename_job_payload = {
            "brand_id": brand_id,
            "brand_code": normalized_brand_code,
            "old_brand_name": old_brand_name,
            "brand_name": normalized_new_brand_name,
        }

        with self._get_conn() as conn:
            conn.begin()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE brands
                        SET brand_name = %s
                        WHERE id = %s
                        """,
                        (normalized_new_brand_name, brand_id),
                    )
                    counts["brands"] = int(cursor.rowcount or 0)

                    cursor.execute(
                        """
                        UPDATE brand_products
                        SET brand_name = %s
                        WHERE brand_id = %s
                           OR brand_name = %s
                        """,
                        (normalized_new_brand_name, brand_id, old_brand_name),
                    )
                    counts["brand_products"] = int(cursor.rowcount or 0)

                    cursor.execute(
                        """
                        UPDATE brand_full_knowledge_files
                        SET brand_name = %s
                        WHERE brand_id = %s
                           OR brand_name = %s
                        """,
                        (normalized_new_brand_name, brand_id, old_brand_name),
                    )
                    counts["brand_full_knowledge_files"] = int(cursor.rowcount or 0)

                    cursor.execute(
                        """
                        UPDATE brand_knowledge_facts
                        SET brand_name = %s
                        WHERE brand_code = %s
                        """,
                        (normalized_new_brand_name, normalized_brand_code),
                    )
                    counts["brand_knowledge_facts"] = int(cursor.rowcount or 0)

                    cursor.execute(
                        """
                        UPDATE brand_attachment_assets
                        SET brand_name = %s
                        WHERE brand_code = %s
                        """,
                        (normalized_new_brand_name, normalized_brand_code),
                    )
                    counts["brand_attachment_assets"] = int(cursor.rowcount or 0)

                    cursor.execute(
                        """
                        UPDATE brand_knowledge_ingestion_jobs
                        SET brand_name = %s
                        WHERE brand_code = %s
                        """,
                        (normalized_new_brand_name, normalized_brand_code),
                    )
                    counts["brand_knowledge_ingestion_jobs"] = int(cursor.rowcount or 0)

                    cursor.execute(
                        """
                        UPDATE brand_knowledge_sessions
                        SET brand_name = %s
                        WHERE brand_id = %s
                           OR brand_name = %s
                        """,
                        (normalized_new_brand_name, brand_id, old_brand_name),
                    )
                    counts["brand_knowledge_sessions"] = int(cursor.rowcount or 0)

                    cursor.execute(
                        """
                        UPDATE document_registry
                        SET category = %s
                        WHERE category = %s
                        """,
                        (normalized_new_brand_name, old_brand_name),
                    )
                    counts["document_registry"] = int(cursor.rowcount or 0)

                    cursor.execute(
                        """
                        UPDATE document_categories
                        SET category = %s
                        WHERE category = %s
                        """,
                        (normalized_new_brand_name, old_brand_name),
                    )
                    counts["document_categories"] = int(cursor.rowcount or 0)

                    cursor.execute(
                        """
                        UPDATE background_jobs
                        SET payload_json = JSON_SET(
                            COALESCE(payload_json, JSON_OBJECT()),
                            '$.brand_name', %s
                        )
                        WHERE JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.brand_code')) = %s
                           OR JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.brand_name')) = %s
                        """,
                        (normalized_new_brand_name, normalized_brand_code, old_brand_name),
                    )
                    counts["background_jobs"] = int(cursor.rowcount or 0)

                    cursor.execute(
                        """
                        UPDATE upload_tasks
                        SET metadata_json = JSON_SET(
                            COALESCE(metadata_json, JSON_OBJECT()),
                            '$.brand_name', %s,
                            '$.category', %s
                        )
                        WHERE JSON_UNQUOTE(JSON_EXTRACT(metadata_json, '$.brand_code')) = %s
                           OR JSON_UNQUOTE(JSON_EXTRACT(metadata_json, '$.brand_name')) = %s
                           OR JSON_UNQUOTE(JSON_EXTRACT(metadata_json, '$.category')) = %s
                        """,
                        (
                            normalized_new_brand_name,
                            normalized_new_brand_name,
                            normalized_brand_code,
                            old_brand_name,
                            old_brand_name,
                        ),
                    )
                    counts["upload_tasks"] = int(cursor.rowcount or 0)

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
                        VALUES (%s, %s, %s, %s, 'waiting', %s, %s, NULL, 0, %s, NULL, NULL, NULL, NULL, NULL, NULL)
                        ON DUPLICATE KEY UPDATE
                            source_type = VALUES(source_type),
                            payload_json = VALUES(payload_json),
                            priority = VALUES(priority),
                            max_retries = VALUES(max_retries),
                            status = CASE
                                WHEN status = 'success' THEN status
                                ELSE VALUES(status)
                            END,
                            next_retry_at = CASE
                                WHEN status = 'success' THEN next_retry_at
                                ELSE NULL
                            END,
                            last_error_message = CASE
                                WHEN status = 'success' THEN last_error_message
                                ELSE NULL
                            END
                        """,
                        (
                            rename_job_id,
                            BRAND_RENAME_MILVUS_SYNC_JOB_TYPE,
                            "brand_rename",
                            rename_job_source_id,
                            50,
                            self._dump_json(rename_job_payload),
                            8,
                        ),
                    )
                    counts["background_jobs"] += int(cursor.rowcount or 0)

                background_job: dict[str, Any] | None = None
                with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                    cursor.execute(
                        """
                        SELECT
                            job_id,
                            job_type,
                            source_type,
                            source_id,
                            status,
                            priority,
                            retry_count,
                            max_retries,
                            next_retry_at,
                            last_error_message,
                            started_at,
                            finished_at,
                            created_at,
                            updated_at
                        FROM background_jobs
                        WHERE job_id = %s
                        LIMIT 1
                        """,
                        (rename_job_id,),
                    )
                    background_job = cursor.fetchone()

                conn.commit()
            except Exception:
                conn.rollback()
                raise

        updated_tables = [table_name for table_name, count in counts.items() if count > 0]
        return {
            "brand_id": brand_id,
            "brand_code": normalized_brand_code,
            "old_brand_name": old_brand_name,
            "brand_name": normalized_new_brand_name,
            "counts": counts,
            "updated_tables": updated_tables,
            "background_job": background_job
            or {
                "job_id": rename_job_id,
                "job_type": BRAND_RENAME_MILVUS_SYNC_JOB_TYPE,
                "source_type": "brand_rename",
                "source_id": rename_job_source_id,
                "status": "waiting",
            },
        }
