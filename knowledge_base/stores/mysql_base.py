from __future__ import annotations

import queue
import threading
from pathlib import Path
from time import monotonic

import pymysql

from knowledge_base.infrastructure.settings import Settings


def _schema_files_by_table(migrations_dir: Path) -> list[tuple[str, Path]]:
    schema_files = sorted(migrations_dir.glob("*.sql"))
    return [
        (schema_file.stem.split("_", 1)[1], schema_file)
        for schema_file in schema_files
    ]


def ensure_mysql_schema_ready(
    *,
    settings: Settings,
    migrations_dir: Path,
    migrations_table: str,
) -> None:
    expected_versions = {
        schema_file.name
        for _, schema_file in _schema_files_by_table(migrations_dir)
    }
    with pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset="utf8mb4",
        autocommit=True,
    ) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = %s
                LIMIT 1
                """,
                (settings.mysql_database, migrations_table),
            )
            if cursor.fetchone() is None:
                raise RuntimeError(
                    "数据库 schema 未初始化：缺少 schema_migrations 表，请先运行 `knowledge-base-db-migrate`"
                )

            cursor.execute(f"SELECT version FROM {migrations_table}")
            applied_versions = {str(row[0]) for row in cursor.fetchall()}

    missing_versions = sorted(expected_versions - applied_versions)
    if missing_versions:
        raise RuntimeError(
            "数据库 schema 未更新到最新版本，请先运行 `knowledge-base-db-migrate`。"
            f" 缺失 migrations: {', '.join(missing_versions)}"
        )


class PooledConnection:
    def __init__(self, pool: queue.LifoQueue, conn):
        self._pool = pool
        self._conn = conn

    def __getattr__(self, item):
        return getattr(self._conn, item)

    def __enter__(self):
        self._conn.__enter__()
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        suppress_error = self._conn.__exit__(exc_type, exc, tb)
        try:
            self._pool.put_nowait(self._conn)
        except queue.Full:
            self._conn.close()
        return suppress_error


class MySQLStoreBase:
    MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "sql" / "migrations"
    MIGRATIONS_TABLE = "schema_migrations"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._conn_pool: queue.LifoQueue[pymysql.connections.Connection] = queue.LifoQueue(
            maxsize=self.settings.mysql_pool_size
        )
        self._latest_doc_cache_ttl = max(0.0, self.settings.category_latest_cache_ttl_seconds)
        self._latest_doc_cache: dict[tuple[str, str | None], tuple[float, list[str]]] = {}
        self._latest_doc_cache_lock = threading.Lock()

    def _get_conn(self):
        try:
            conn = self._conn_pool.get_nowait()
        except queue.Empty:
            conn = self._new_conn()
        else:
            try:
                conn.ping(reconnect=True)
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                conn = self._new_conn()
        return PooledConnection(self._conn_pool, conn)

    def _new_conn(self):
        return pymysql.connect(
            host=self.settings.mysql_host,
            port=self.settings.mysql_port,
            user=self.settings.mysql_user,
            password=self.settings.mysql_password,
            database=self.settings.mysql_database,
            charset="utf8mb4",
            autocommit=True,
        )

    def _cache_latest_document_ids(
        self,
        *,
        category: str,
        subcategory: str | None,
        document_ids: list[str],
    ) -> None:
        if self._latest_doc_cache_ttl <= 0:
            return
        expires_at = monotonic() + self._latest_doc_cache_ttl
        with self._latest_doc_cache_lock:
            self._latest_doc_cache[(category, subcategory)] = (expires_at, list(document_ids))

    def _get_cached_latest_document_ids(
        self,
        *,
        category: str,
        subcategory: str | None,
    ) -> list[str] | None:
        if self._latest_doc_cache_ttl <= 0:
            return None
        cache_key = (category, subcategory)
        now = monotonic()
        with self._latest_doc_cache_lock:
            cached = self._latest_doc_cache.get(cache_key)
            if cached is None:
                return None
            expires_at, document_ids = cached
            if expires_at <= now:
                self._latest_doc_cache.pop(cache_key, None)
                return None
            return list(document_ids)

    def invalidate_latest_document_ids_cache(self, category: str | None = None) -> None:
        with self._latest_doc_cache_lock:
            if category is None:
                self._latest_doc_cache.clear()
                return
            stale_keys = [key for key in self._latest_doc_cache if key[0] == category]
            for key in stale_keys:
                self._latest_doc_cache.pop(key, None)

    @classmethod
    def _schema_files_by_table(cls) -> list[tuple[str, Path]]:
        return _schema_files_by_table(cls.MIGRATIONS_DIR)

    def ensure_schema_ready(self) -> None:
        ensure_mysql_schema_ready(
            settings=self.settings,
            migrations_dir=self.MIGRATIONS_DIR,
            migrations_table=self.MIGRATIONS_TABLE,
        )
