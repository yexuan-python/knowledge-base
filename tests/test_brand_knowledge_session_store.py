from __future__ import annotations

import types
import unittest

from knowledge_base.stores.brand_knowledge_session_store import BrandKnowledgeSessionStore


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, query: str, params: tuple) -> None:
        self.executed.append((query, params))

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakePooledConnection:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    def __enter__(self) -> _FakeConnection:
        return self._connection

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _InspectableBrandKnowledgeSessionStore(BrandKnowledgeSessionStore):
    def __init__(self) -> None:
        self.settings = types.SimpleNamespace()
        self.cursor = _FakeCursor()

    def _get_conn(self):
        return _FakePooledConnection(_FakeConnection(self.cursor))


class BrandKnowledgeSessionStoreTests(unittest.TestCase):
    def test_create_session_insert_placeholders_match_parameters(self) -> None:
        store = _InspectableBrandKnowledgeSessionStore()

        store.create_session(
            session_id="bks_demo",
            brand_id=7,
            brand_code="BR001",
            brand_name="测试品牌",
            source_task_id="task-1",
            session_kind="attachment_conflict",
            status="running",
            current_round=1,
            initial_user_message="请扫描冲突",
            latest_user_message="请扫描冲突",
            latest_assistant_message=None,
            source_documents=[{"document_id": "asset_1"}],
        )

        self.assertEqual(len(store.cursor.executed), 1)
        query, params = store.cursor.executed[0]
        self.assertIn("INSERT INTO brand_knowledge_sessions", query)
        self.assertEqual(query.count("%s"), len(params))
        self.assertEqual(len(params), 13)


if __name__ == "__main__":
    unittest.main()
