from __future__ import annotations

from knowledge_base.infrastructure.settings import Settings

from .mysql_base import MySQLStoreBase


class DocumentFactRelationStore(MySQLStoreBase):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)

    def replace_document_fact_relations(self, document_id: str, fact_ids: list[str]) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM document_fact_relations WHERE document_id = %s", (document_id,))
                if not fact_ids:
                    return
                values = [(document_id, fact_id) for fact_id in fact_ids]
                cursor.executemany(
                    "INSERT IGNORE INTO document_fact_relations (document_id, fact_id) VALUES (%s, %s)",
                    values,
                )

    def delete_document_fact_relations(self, document_id: str) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM document_fact_relations WHERE document_id = %s", (document_id,))

    def get_fact_ids_by_document(self, document_id: str) -> list[str]:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT fact_id FROM document_fact_relations WHERE document_id = %s", (document_id,))
                return [row[0] for row in cursor.fetchall()]

    def count_document_fact_relations(self, document_ids: list[str]) -> int:
        if not document_ids:
            return 0
        placeholders = ", ".join(["%s"] * len(document_ids))
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM document_fact_relations
                    WHERE document_id IN ({placeholders})
                    """,
                    document_ids,
                )
                row = cursor.fetchone()
        return int(row[0] or 0) if row else 0
