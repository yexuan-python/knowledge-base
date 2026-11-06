from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pymysql

from .mysql_base import MySQLStoreBase


class BrandAttachmentAssetStore(MySQLStoreBase):
    @staticmethod
    def _hydrate_asset_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        hydrated = dict(row)
        raw_tags_json = hydrated.get("image_tags_json")
        image_tags: list[str] = []
        if isinstance(raw_tags_json, str) and raw_tags_json.strip():
            try:
                parsed = json.loads(raw_tags_json)
            except json.JSONDecodeError:
                parsed = []
            if isinstance(parsed, list):
                image_tags = [str(item).strip() for item in parsed if str(item).strip()]
        hydrated["image_tags"] = image_tags
        return hydrated

    def get_by_brand_code_and_file_hash(
        self,
        *,
        brand_code: str,
        file_hash: str,
    ) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM brand_attachment_assets
                    WHERE brand_code = %s AND file_hash = %s
                    LIMIT 1
                    """,
                    (brand_code, file_hash),
                )
                return self._hydrate_asset_row(cursor.fetchone())

    def get_by_brand_code_and_attachment(
        self,
        *,
        brand_code: str,
        original_filename: str,
        source_url: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_brand_code = str(brand_code or "").strip()
        normalized_filename = str(original_filename or "").strip()
        normalized_source_url = str(source_url or "").strip() or None
        if not normalized_brand_code or not normalized_filename:
            return None

        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                if normalized_source_url:
                    cursor.execute(
                        """
                        SELECT *
                        FROM brand_attachment_assets
                        WHERE brand_code = %s
                          AND original_filename = %s
                          AND source_url = %s
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (normalized_brand_code, normalized_filename, normalized_source_url),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT *
                        FROM brand_attachment_assets
                        WHERE brand_code = %s
                          AND original_filename = %s
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (normalized_brand_code, normalized_filename),
                    )
                return self._hydrate_asset_row(cursor.fetchone())

    def get_by_id(self, *, asset_id: int) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM brand_attachment_assets
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (asset_id,),
                )
                return self._hydrate_asset_row(cursor.fetchone())

    def get_by_ids(self, *, asset_ids: list[int]) -> dict[int, dict[str, Any]]:
        normalized_asset_ids = sorted({int(asset_id) for asset_id in asset_ids if int(asset_id) > 0})
        if not normalized_asset_ids:
            return {}
        placeholders = ", ".join(["%s"] * len(normalized_asset_ids))
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT *
                    FROM brand_attachment_assets
                    WHERE id IN ({placeholders})
                    """,
                    normalized_asset_ids,
                )
                rows = cursor.fetchall()
        return {
            int(row["id"]): hydrated
            for row in rows
            if row.get("id") is not None
            for hydrated in [self._hydrate_asset_row(row)]
            if hydrated is not None
        }

    def create_asset(
        self,
        *,
        brand_code: str,
        brand_name: str,
        upload_task_id: str | None,
        upload_task_file_id: int | None,
        original_filename: str,
        content_type: str | None,
        parsed_source_type: str | None = None,
        parsed_markdown: str | None = None,
        converted_version: int | None,
        fulltext_key: str | None,
        fulltext_url: str | None,
        file_size: int | None,
        file_hash: str,
        oss_key: str,
        oss_url: str | None,
        source_url: str | None,
        asset_kind: str | None = "file",
        image_summary: str | None = None,
        image_tags_json: str | None = None,
        status: str = "success",
        error_message: str | None = None,
    ) -> int:
        file_ext = Path(original_filename).suffix.lower() or None
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO brand_attachment_assets (
                        brand_code,
                        brand_name,
                        upload_task_id,
                        upload_task_file_id,
                        original_filename,
                        file_ext,
                        content_type,
                        asset_kind,
                        parsed_source_type,
                        parsed_markdown,
                        converted_version,
                        fulltext_key,
                        fulltext_url,
                        image_summary,
                        image_tags_json,
                        file_size,
                        file_hash,
                        oss_key,
                        oss_url,
                        source_url,
                        status,
                        error_message
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        brand_code,
                        brand_name,
                        upload_task_id,
                        upload_task_file_id,
                        original_filename,
                        file_ext,
                        content_type,
                        asset_kind,
                        parsed_source_type,
                        parsed_markdown,
                        converted_version,
                        fulltext_key,
                        fulltext_url,
                        image_summary,
                        image_tags_json,
                        file_size,
                        file_hash,
                        oss_key,
                        oss_url,
                        source_url,
                        status,
                        error_message,
                    ),
                )
                return int(cursor.lastrowid)

    def update_parsed_content(
        self,
        *,
        asset_id: int,
        parsed_source_type: str | None,
        parsed_markdown: str | None,
        converted_version: int | None = None,
        fulltext_key: str | None = None,
        fulltext_url: str | None = None,
    ) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE brand_attachment_assets
                    SET parsed_source_type = %s,
                        parsed_markdown = %s,
                        converted_version = COALESCE(%s, converted_version),
                        fulltext_key = COALESCE(%s, fulltext_key),
                        fulltext_url = COALESCE(%s, fulltext_url)
                    WHERE id = %s
                    """,
                    (
                        parsed_source_type,
                        parsed_markdown,
                        converted_version,
                        fulltext_key,
                        fulltext_url,
                        asset_id,
                    ),
                )

    def delete_by_id(self, *, asset_id: int) -> int:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM brand_attachment_assets
                    WHERE id = %s
                    """,
                    (asset_id,),
                )
                return int(cursor.rowcount or 0)

    def get_next_converted_version(
        self,
        *,
        brand_code: str,
        original_filename: str,
    ) -> int:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COALESCE(MAX(converted_version), 0)
                    FROM brand_attachment_assets
                    WHERE brand_code = %s
                      AND original_filename = %s
                    """,
                    (brand_code, original_filename),
                )
                row = cursor.fetchone()
        current_max = int((row or [0])[0] or 0)
        return current_max + 1

    def list_by_brand_code(self, *, brand_code: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM brand_attachment_assets
                    WHERE brand_code = %s
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (brand_code, limit),
                )
                return [
                    hydrated
                    for row in cursor.fetchall()
                    if (hydrated := self._hydrate_asset_row(row)) is not None
                ]

    def list_by_upload_task_id(self, *, upload_task_id: str) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM brand_attachment_assets
                    WHERE upload_task_id = %s
                    ORDER BY upload_task_file_id ASC, id ASC
                    """,
                    (upload_task_id,),
                )
                return [
                    hydrated
                    for row in cursor.fetchall()
                    if (hydrated := self._hydrate_asset_row(row)) is not None
                ]

    def count_by_brand_code(self, *, brand_code: str) -> int:
        normalized_brand_code = str(brand_code or "").strip()
        if not normalized_brand_code:
            return 0
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM brand_attachment_assets
                    WHERE brand_code = %s
                    """,
                    (normalized_brand_code,),
                )
                row = cursor.fetchone()
        return int((row or [0])[0] or 0)

    def delete_by_brand_code(self, *, brand_code: str) -> int:
        normalized_brand_code = str(brand_code or "").strip()
        if not normalized_brand_code:
            return 0
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM brand_attachment_assets
                    WHERE brand_code = %s
                    """,
                    (normalized_brand_code,),
                )
                return int(cursor.rowcount or 0)
