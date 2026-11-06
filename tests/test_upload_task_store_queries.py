from __future__ import annotations

import unittest

from knowledge_base.stores.upload_task_store import UploadTaskStore


class _FakeCursor:
    def __init__(self, *, rows: list[dict] | None = None) -> None:
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []
        self._rows = rows or []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        self.executed.append((sql, params))

    def fetchall(self):
        return list(self._rows)


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, *_args, **_kwargs):
        return self._cursor


class UploadTaskStoreQueryTests(unittest.TestCase):
    def test_get_upload_tasks_by_ids_deduplicates_and_queries_existing_tasks(self) -> None:
        cursor = _FakeCursor(
            rows=[
                {
                    "task_id": "task-1",
                    "task_type": "document_upload",
                    "status": "processing",
                }
            ]
        )
        store = UploadTaskStore.__new__(UploadTaskStore)
        store._get_conn = lambda: _FakeConnection(cursor)

        result = store.get_upload_tasks_by_ids(["task-1", "task-1", "", "task-2"])

        self.assertEqual("processing", result["task-1"]["status"])
        sql, params = cursor.executed[0]
        self.assertIn("FROM upload_tasks", sql)
        self.assertIn("WHERE task_id IN (%s, %s)", sql)
        self.assertEqual(("task-1", "task-2"), params)

    def test_list_upload_task_file_summaries_groups_files_by_task(self) -> None:
        cursor = _FakeCursor(
            rows=[
                {
                    "id": 1,
                    "task_id": "task-1",
                    "file_index": 0,
                    "original_filename": "a.pdf",
                    "status": "success",
                },
                {
                    "id": 2,
                    "task_id": "task-2",
                    "file_index": 0,
                    "original_filename": "b.pdf",
                    "status": "failed",
                },
            ]
        )
        store = UploadTaskStore.__new__(UploadTaskStore)
        store._get_conn = lambda: _FakeConnection(cursor)

        result = store.list_upload_task_file_summaries_by_task_ids(["task-1", "task-2"])

        self.assertEqual("a.pdf", result["task-1"][0]["original_filename"])
        self.assertEqual("failed", result["task-2"][0]["status"])
        sql, params = cursor.executed[0]
        self.assertIn("FROM upload_task_files", sql)
        self.assertIn("WHERE task_id IN (%s, %s)", sql)
        self.assertEqual(("task-1", "task-2"), params)

    def test_search_upload_task_ids_matches_metadata_and_files(self) -> None:
        cursor = _FakeCursor(rows=[("task-1",), ("task-2",)])
        store = UploadTaskStore.__new__(UploadTaskStore)
        store._get_conn = lambda: _FakeConnection(cursor)

        result = store.search_upload_task_ids("狄耐克", limit=9999)

        self.assertEqual(["task-1", "task-2"], result)
        sql, params = cursor.executed[0]
        self.assertIn("LEFT JOIN upload_task_files", sql)
        self.assertIn("$.brand_name", sql)
        self.assertIn("f.original_filename LIKE %s", sql)
        self.assertEqual("%狄耐克%", params[0])
        self.assertEqual(5000, params[-1])


if __name__ == "__main__":
    unittest.main()
