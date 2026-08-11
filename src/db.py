from __future__ import annotations

from typing import TYPE_CHECKING

import psycopg2
from psycopg2.extensions import connection as PgConnection

if TYPE_CHECKING:
    from src.config import Settings


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
