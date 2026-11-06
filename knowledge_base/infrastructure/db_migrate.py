from __future__ import annotations

import logging
from pathlib import Path

import pymysql

from knowledge_base.infrastructure.settings import Settings, get_settings


logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "sql" / "migrations"
MIGRATIONS_TABLE = "schema_migrations"


def _get_conn(settings: Settings) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset="utf8mb4",
        autocommit=False,
    )


def _schema_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _ensure_migrations_table(cursor: pymysql.cursors.Cursor) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} (
            version VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) COMMENT='记录已执行的数据库 schema 版本'
        """
    )


def _read_single_statement(schema_file: Path) -> str:
    statement = schema_file.read_text(encoding="utf-8").strip()
    if not statement:
        raise ValueError(f"Migration file is empty: {schema_file.name}")
    return statement


def migrate(settings: Settings | None = None) -> None:
    resolved_settings = settings or get_settings()
    schema_files = _schema_files()
    if not schema_files:
        logger.warning("No migration files found under %s", MIGRATIONS_DIR)
        return

    with _get_conn(resolved_settings) as conn:
        with conn.cursor() as cursor:
            _ensure_migrations_table(cursor)
            conn.commit()
            cursor.execute(f"SELECT version FROM {MIGRATIONS_TABLE}")
            applied_versions = {str(row[0]) for row in cursor.fetchall()}

            applied_now: list[str] = []
            for schema_file in schema_files:
                version = schema_file.name
                if version in applied_versions:
                    continue
                logger.info("Applying schema migration version=%s", version)
                try:
                    cursor.execute(_read_single_statement(schema_file))
                    cursor.execute(
                        f"INSERT INTO {MIGRATIONS_TABLE} (version) VALUES (%s)",
                        (version,),
                    )
                except Exception:
                    conn.rollback()
                    logger.exception("Schema migration failed version=%s", version)
                    raise
                else:
                    conn.commit()
                    applied_now.append(version)

    if applied_now:
        logger.info("Schema migrations applied count=%s versions=%s", len(applied_now), applied_now)
    else:
        logger.info("Schema migrations already up to date")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    migrate()


if __name__ == "__main__":
    main()
