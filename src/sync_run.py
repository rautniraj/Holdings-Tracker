"""sync_runs audit helpers shared by backfill and daily sync."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg2.extensions import connection as PgConnection


def create_sync_run(conn: PgConnection, trade_from: date, trade_to: date) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sync_runs (trade_from, trade_to)
            VALUES (%s, %s)
            RETURNING id
            """,
            (trade_from, trade_to),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("Failed to create sync_runs row")
        return row[0]


def finalize_sync_run(
    conn: PgConnection,
    sync_run_id: int,
    *,
    status: str,
    trades_fetched: int,
    trades_inserted: int,
    trades_skipped: int,
    error_message: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE sync_runs
            SET finished_at = now(),
                status = %s,
                trades_fetched = %s,
                trades_inserted = %s,
                trades_skipped = %s,
                error_message = %s
            WHERE id = %s
            """,
            (
                status,
                trades_fetched,
                trades_inserted,
                trades_skipped,
                error_message,
                sync_run_id,
            ),
        )
