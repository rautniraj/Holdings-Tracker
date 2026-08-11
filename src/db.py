from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import psycopg2
from psycopg2.extensions import connection as PgConnection

if TYPE_CHECKING:
    from src.config import Settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def get_connection(settings: Settings | None = None) -> PgConnection:
    if settings is None:
        from src.config import Settings

        settings = Settings.from_env()

    if not settings.database_url:
        raise ValueError("Missing required environment variable: DATABASE_URL")

    return psycopg2.connect(settings.database_url, connect_timeout=10)


def check_connection(settings: Settings | None = None) -> str:
    conn = get_connection(settings)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            row = cur.fetchone()
            if not row or not row[0]:
                raise RuntimeError("Could not read PostgreSQL version")
            return row[0]
    finally:
        conn.close()


def _split_sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    token: list[str] = []
    in_dollar_quote = False
    i = 0

    while i < len(sql):
        if not in_dollar_quote and sql[i : i + 2] == "$$":
            in_dollar_quote = True
            token.append("$$")
            i += 2
            continue

        if in_dollar_quote and sql[i : i + 2] == "$$":
            in_dollar_quote = False
            token.append("$$")
            i += 2
            continue

        if not in_dollar_quote and sql[i] == ";":
            statement = "".join(token).strip()
            if statement:
                statements.append(statement)
            token = []
            i += 1
            continue

        token.append(sql[i])
        i += 1

    statement = "".join(token).strip()
    if statement:
        statements.append(statement)

    return statements


def _ensure_schema_migrations(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version TEXT PRIMARY KEY,
          applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def _applied_migrations(cur) -> set[str]:
    _ensure_schema_migrations(cur)
    cur.execute("SELECT version FROM schema_migrations")
    return {row[0] for row in cur.fetchall()}


def run_migrations(
    settings: Settings | None = None,
    migrations_dir: Path | None = None,
) -> list[str]:
    migrations_path = migrations_dir or MIGRATIONS_DIR
    if not migrations_path.is_dir():
        raise FileNotFoundError(f"Migrations directory not found: {migrations_path}")

    migration_files = sorted(migrations_path.glob("*.sql"))
    if not migration_files:
        raise FileNotFoundError(f"No migration files found in: {migrations_path}")

    conn = get_connection(settings)
    applied: list[str] = []

    try:
        with conn:
            with conn.cursor() as cur:
                already_applied = _applied_migrations(cur)

                for path in migration_files:
                    version = path.name
                    if version in already_applied:
                        continue

                    sql = path.read_text(encoding="utf-8")
                    for statement in _split_sql_statements(sql):
                        cur.execute(statement)

                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (version,),
                    )
                    applied.append(version)
    finally:
        conn.close()

    return applied
