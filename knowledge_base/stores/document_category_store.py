from __future__ import annotations

from typing import Any, List, Optional

from .mysql_base import MySQLStoreBase


class DocumentCategoryStore(MySQLStoreBase):
    def add_document(
        self, document_id: str, category: str, subcategory: Optional[str] = None
    ) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "REPLACE INTO document_categories (document_id, category, subcategory) VALUES (%s, %s, %s)",
                    (document_id, category, subcategory),
                )
        self.invalidate_latest_document_ids_cache(category)

    def remove_document(self, document_id: str) -> None:
        category: Optional[str] = None
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT category FROM document_categories WHERE document_id = %s", (document_id,))
                row = cursor.fetchone()
                if row:
                    category = row[0]
                cursor.execute("DELETE FROM document_categories WHERE document_id = %s", (document_id,))
        if category:
            self.invalidate_latest_document_ids_cache(category)

    def get_document_ids_by_category(self, category: str) -> List[str]:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT document_id FROM document_categories WHERE category = %s", (category,))
                return [row[0] for row in cursor.fetchall()]

    def get_document_ids_by_category_and_subcategory(self, category: str, subcategory: str) -> List[str]:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT document_id FROM document_categories WHERE category = %s AND subcategory = %s",
                    (category, subcategory),
                )
                return [row[0] for row in cursor.fetchall()]

    def get_latest_document_ids_by_category(self, category: str) -> List[str]:
        cached = self._get_cached_latest_document_ids(category=category, subcategory=None)
        if cached is not None:
            return cached
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT dc.document_id
                    FROM document_categories AS dc
                    LEFT JOIN document_registry AS dr
                      ON dc.document_id = dr.document_id
                    WHERE dc.category = %s
                      AND (
                          dr.document_id IS NULL
                          OR (dr.is_latest = 1 AND dr.status = 'success')
                      )
                    """,
                    (category,),
                )
                document_ids = [row[0] for row in cursor.fetchall()]
        self._cache_latest_document_ids(
            category=category,
            subcategory=None,
            document_ids=document_ids,
        )
        return document_ids

    def get_latest_document_ids_by_category_and_subcategory(self, category: str, subcategory: str) -> List[str]:
        cached = self._get_cached_latest_document_ids(category=category, subcategory=subcategory)
        if cached is not None:
            return cached
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT dc.document_id
                    FROM document_categories AS dc
                    LEFT JOIN document_registry AS dr
                      ON dc.document_id = dr.document_id
                    WHERE dc.category = %s
                      AND dc.subcategory = %s
                      AND (
                          dr.document_id IS NULL
                          OR (dr.is_latest = 1 AND dr.status = 'success')
                      )
                    """,
                    (category, subcategory),
                )
                document_ids = [row[0] for row in cursor.fetchall()]
        self._cache_latest_document_ids(
            category=category,
            subcategory=subcategory,
            document_ids=document_ids,
        )
        return document_ids

    def get_searchable_document_ids(self, document_ids: Optional[List[str]] = None) -> List[str]:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                params: list[Any] = []
                document_filter = ""
                if document_ids:
                    placeholders = ", ".join(["%s"] * len(document_ids))
                    document_filter = f"AND dc.document_id IN ({placeholders})"
                    params.extend(document_ids)

                cursor.execute(
                    f"""
                    SELECT dc.document_id
                    FROM document_categories AS dc
                    LEFT JOIN document_registry AS dr
                      ON dc.document_id = dr.document_id
                    WHERE (
                        dr.document_id IS NULL
                        OR (dr.is_latest = 1 AND dr.status = 'success')
                    )
                    {document_filter}
                    """,
                    params,
                )
                return [row[0] for row in cursor.fetchall()]

    def document_exists(self, document_id: str) -> bool:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM document_categories WHERE document_id = %s", (document_id,))
                return cursor.fetchone() is not None
