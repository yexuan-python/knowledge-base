from __future__ import annotations

import unittest
from datetime import datetime

from knowledge_base.stores.background_job_store import BackgroundJobStore


class _FakeCursor:
    def __init__(self, *, rows: list[tuple[object, ...]] | None = None, rowcount: int = 1) -> None:
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []
        self._rows = rows or []
        self.rowcount = rowcount

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        self.executed.append((sql, params))

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        if not self._rows:
            return None
        return self._rows[0]


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, *_args, **_kwargs):
        return self._cursor


class BackgroundJobStoreTests(unittest.TestCase):
    def test_upsert_job_does_not_restart_completed_jobs_by_default(self) -> None:
        cursor = _FakeCursor()
        store = BackgroundJobStore.__new__(BackgroundJobStore)
        store._get_conn = lambda: _FakeConnection(cursor)
        store.get_job = lambda job_id: {"job_id": job_id}

        store.upsert_job(
            job_id="bg:brand_rename_milvus_sync:100052:新品牌",
            job_type="brand_rename_milvus_sync",
            source_type="brand_knowledge",
            source_id=None,
            payload_json={"brand_code": "100052"},
        )

        _sql, params = cursor.executed[0]
        self.assertEqual((0, 0, 0, 0, 0, 0, 0, 0, 0), params[-9:])

    def test_upsert_job_uses_restart_completed_independently_from_reopen_terminal(self) -> None:
        cursor = _FakeCursor()
        store = BackgroundJobStore.__new__(BackgroundJobStore)
        store._get_conn = lambda: _FakeConnection(cursor)
        store.get_job = lambda job_id: {"job_id": job_id}

        job = store.upsert_job(
            job_id="bg:brand_full_knowledge_refresh:100052",
            job_type="brand_full_knowledge_refresh",
            source_type="brand_knowledge",
            source_id=None,
            payload_json={"brand_code": "100052"},
            status="waiting",
            next_retry_at=datetime(2026, 9, 9, 12, 18, 35),
            reopen_terminal=False,
            restart_completed=True,
        )

        self.assertEqual("bg:brand_full_knowledge_refresh:100052", job["job_id"])
        sql, params = cursor.executed[0]
        self.assertIn("ON DUPLICATE KEY UPDATE", sql)
        self.assertEqual((1, 1, 1, 1, 1, 1, 1, 1, 1), params[-9:])

    def test_reset_processing_jobs_only_releases_expired_locks(self) -> None:
        cursor = _FakeCursor(rows=[("bg:stale-job",)])
        store = BackgroundJobStore.__new__(BackgroundJobStore)
        store._get_conn = lambda: _FakeConnection(cursor)

        reset_ids = store.reset_processing_jobs(lock_timeout_seconds=1800)

        self.assertEqual(["bg:stale-job"], reset_ids)
        select_sql, select_params = cursor.executed[0]
        update_sql, update_params = cursor.executed[1]
        self.assertIn("locked_at IS NOT NULL", select_sql)
        self.assertIn("locked_at <= DATE_SUB(CURRENT_TIMESTAMP, INTERVAL %s SECOND)", select_sql)
        self.assertEqual((1800,), select_params)
        self.assertIn("locked_at IS NOT NULL", update_sql)
        self.assertIn("locked_at <= DATE_SUB(CURRENT_TIMESTAMP, INTERVAL %s SECOND)", update_sql)
        self.assertEqual((1800,), update_params)

    def test_list_recent_jobs_orders_newest_first_filters_status_and_clamps_limit(self) -> None:
        rows = [
            {
                "job_id": "bg:job-2",
                "job_type": "upload_task_process",
                "status": "success",
            }
        ]
        cursor = _FakeCursor(rows=rows)
        store = BackgroundJobStore.__new__(BackgroundJobStore)
        store._get_conn = lambda: _FakeConnection(cursor)

        result = store.list_recent_jobs(limit=999, offset=7, statuses=["success"])

        self.assertEqual(rows, result)
        sql, params = cursor.executed[0]
        self.assertIn("FROM background_jobs", sql)
        self.assertIn("WHERE status IN (%s)", sql)
        self.assertIn("ORDER BY created_at DESC, id DESC", sql)
        self.assertEqual(("success", 500, 7), params)

    def test_count_jobs_filters_status(self) -> None:
        cursor = _FakeCursor(rows=[(3,)])
        store = BackgroundJobStore.__new__(BackgroundJobStore)
        store._get_conn = lambda: _FakeConnection(cursor)

        result = store.count_jobs(statuses=["waiting", "retrying"])

        self.assertEqual(3, result)
        sql, params = cursor.executed[0]
        self.assertIn("WHERE status IN (%s, %s)", sql)
        self.assertEqual(("waiting", "retrying"), params)

    def test_count_jobs_by_status_groups_statuses(self) -> None:
        cursor = _FakeCursor(rows=[("success", 4), ("failed", 2)])
        store = BackgroundJobStore.__new__(BackgroundJobStore)
        store._get_conn = lambda: _FakeConnection(cursor)

        result = store.count_jobs_by_status()

        self.assertEqual({"success": 4, "failed": 2}, result)
        sql, params = cursor.executed[0]
        self.assertIn("GROUP BY status", sql)
        self.assertIsNone(params)

    def test_list_recent_jobs_filters_keyword_and_upload_task_source_ids(self) -> None:
        rows = [{"job_id": "bg:upload_task_process:task-1"}]
        cursor = _FakeCursor(rows=rows)
        store = BackgroundJobStore.__new__(BackgroundJobStore)
        store._get_conn = lambda: _FakeConnection(cursor)

        result = store.list_recent_jobs(
            limit=20,
            offset=0,
            keyword="狄耐克",
            source_ids=["task-1", "task-1"],
        )

        self.assertEqual(rows, result)
        sql, params = cursor.executed[0]
        self.assertIn("job_id LIKE %s", sql)
        self.assertIn("CAST(payload_json AS CHAR) LIKE %s", sql)
        self.assertIn("source_id IN (%s)", sql)
        self.assertEqual("%狄耐克%", params[0])
        self.assertIn("task-1", params)

    def test_count_jobs_filters_keyword_and_status(self) -> None:
        cursor = _FakeCursor(rows=[(1,)])
        store = BackgroundJobStore.__new__(BackgroundJobStore)
        store._get_conn = lambda: _FakeConnection(cursor)

        result = store.count_jobs(statuses=["success"], keyword="task-1", source_ids=["task-1"])

        self.assertEqual(1, result)
        sql, params = cursor.executed[0]
        self.assertIn("status IN (%s)", sql)
        self.assertIn("job_id LIKE %s", sql)
        self.assertEqual("success", params[0])
        self.assertEqual("%task-1%", params[1])

    def test_mark_success_requires_current_worker_lock(self) -> None:
        cursor = _FakeCursor()
        store = BackgroundJobStore.__new__(BackgroundJobStore)
        store._get_conn = lambda: _FakeConnection(cursor)

        store.mark_success(
            job_id="bg:job-1",
            result_json={"ok": True},
            worker_id="worker-a",
        )

        sql, params = cursor.executed[0]
        self.assertIn("WHERE job_id = %s", sql)
        self.assertIn("AND locked_by = %s", sql)
        self.assertEqual(('{"ok": true}', "bg:job-1", "worker-a"), params)

    def test_mark_retrying_and_failed_require_current_worker_lock(self) -> None:
        cursor = _FakeCursor()
        store = BackgroundJobStore.__new__(BackgroundJobStore)
        store._get_conn = lambda: _FakeConnection(cursor)
        next_retry_at = datetime(2026, 9, 22, 10, 30, 0)

        store.mark_retrying(
            job_id="bg:job-1",
            retry_count=2,
            next_retry_at=next_retry_at,
            result_json={"step": "partial"},
            last_error_message="boom",
            worker_id="worker-a",
        )
        store.mark_failed(
            job_id="bg:job-1",
            retry_count=3,
            result_json={"step": "partial"},
            last_error_message="boom",
            worker_id="worker-a",
        )

        retry_sql, retry_params = cursor.executed[0]
        failed_sql, failed_params = cursor.executed[1]
        self.assertIn("WHERE job_id = %s", retry_sql)
        self.assertIn("AND locked_by = %s", retry_sql)
        self.assertEqual(
            (2, next_retry_at, '{"step": "partial"}', "boom", "bg:job-1", "worker-a"),
            retry_params,
        )
        self.assertIn("WHERE job_id = %s", failed_sql)
        self.assertIn("AND locked_by = %s", failed_sql)
        self.assertEqual(
            (3, '{"step": "partial"}', "boom", "bg:job-1", "worker-a"),
            failed_params,
        )
