from __future__ import annotations

import unittest

from knowledge_base.stores.brand_knowledge_ingestion_job_store import BrandKnowledgeIngestionJobStore


class _FakeCursor:
    def __init__(
        self,
        *,
        raise_on_execute: Exception | None = None,
        fetchone_result: dict[str, object] | None = None,
        lastrowid: int = 0,
    ) -> None:
        self.raise_on_execute = raise_on_execute
        self.fetchone_result = fetchone_result
        self.lastrowid = lastrowid
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        self.executed.append((sql, params))
        if self.raise_on_execute is not None:
            raise self.raise_on_execute

    def fetchone(self):
        return self.fetchone_result


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, *_args, **_kwargs):
        return self._cursor


class BrandKnowledgeIngestionJobStoreTests(unittest.TestCase):
    def test_create_job_uses_atomic_upsert_for_existing_job_id(self) -> None:
        insert_cursor = _FakeCursor(lastrowid=42)
        connections = [_FakeConnection(insert_cursor)]
        store = BrandKnowledgeIngestionJobStore.__new__(BrandKnowledgeIngestionJobStore)
        store._get_conn = lambda: connections.pop(0)

        created_id = store.create_job(
            job_id="brand-ai-kb-generated:bg:brand_full_knowledge_refresh:100052",
            brand_code="100052",
            brand_name="灵犀智擎",
            version_no=8,
            knowledge_date="20260909",
            revision_no=1,
            original_filename="【灵犀智擎】品牌AI知识库_V8_20260909.md",
            source_ext="md",
            force_reingest=False,
            status="processing",
            current_step="parse",
            document_id="doc-1",
        )

        self.assertEqual(created_id, 42)
        self.assertIn("INSERT INTO brand_knowledge_ingestion_jobs", insert_cursor.executed[0][0])
        self.assertIn("ON DUPLICATE KEY UPDATE", insert_cursor.executed[0][0])
        self.assertIn("id = LAST_INSERT_ID(id)", insert_cursor.executed[0][0])
        self.assertEqual(connections, [])
