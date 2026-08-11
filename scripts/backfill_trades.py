#!/usr/bin/env python3
"""Backfill Dhan trade history and current holdings into PostgreSQL."""

from __future__ import annotations

import calendar
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.auth import get_access_token
from src.config import Settings
from src.db import get_connection
from src.dhan_client import DhanClient
from src.holdings_sync import sync_holdings
from src.trade_ingest import ingest_trades

DEFAULT_TRADE_FROM = date(2025, 9, 20)


def monthly_chunks(start: date, end: date) -> list[tuple[date, date]]:
    chunks: list[tuple[date, date]] = []
    current = start

    while current <= end:
        last_day = calendar.monthrange(current.year, current.month)[1]
        chunk_end = min(date(current.year, current.month, last_day), end)
        chunks.append((current, chunk_end))

        if chunk_end >= end:
            break

        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)

    return chunks


def create_sync_run(conn, trade_from: date, trade_to: date) -> int:
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
    conn,
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


def main() -> int:
    settings = Settings.from_env()

    if not settings.database_url:
        print("ERROR: DATABASE_URL is not set in .env", file=sys.stderr)
        return 1

    trade_from = (
        date.fromisoformat(settings.trade_from)
        if settings.trade_from
        else DEFAULT_TRADE_FROM
    )
    trade_to = (
        date.fromisoformat(settings.trade_to) if settings.trade_to else date.today()
    )

    if trade_from > trade_to:
        print("ERROR: trade_from must be on or before trade_to", file=sys.stderr)
        return 1

    chunks = monthly_chunks(trade_from, trade_to)

    print("=" * 60)
    print("Backfill — Dhan Trade History + Holdings")
    print(f"As of: {datetime.now().strftime('%d-%b-%Y %H:%M:%S')}")
    print(f"Date range: {trade_from.isoformat()} -> {trade_to.isoformat()}")
    print(f"Monthly chunks: {len(chunks)}")
    print("=" * 60)

    conn = get_connection(settings)
    sync_run_id: int | None = None
    total_fetched = 0
    total_inserted = 0
    total_skipped = 0

    try:
        print("\n[1/3] Authenticating with TOTP...")
        auth_payload, reused = get_access_token(settings)
        print(f"  {'Reusing cached' if reused else 'Generated new'} access token")
        client = DhanClient(auth_payload["accessToken"], settings)

        with conn:
            sync_run_id = create_sync_run(conn, trade_from, trade_to)
            print(f"  sync_run_id: {sync_run_id}")

            print("\n[2/3] Fetching trade history...")
            for index, (chunk_from, chunk_to) in enumerate(chunks):
                if index > 0 and settings.trade_history_sleep_seconds > 0:
                    time.sleep(settings.trade_history_sleep_seconds)

                chunk_label = f"{chunk_from.isoformat()} -> {chunk_to.isoformat()}"
                print(f"  chunk {index + 1}/{len(chunks)}: {chunk_label}")

                trades, pages_fetched = client.get_trade_history(
                    chunk_from.isoformat(),
                    chunk_to.isoformat(),
                )
                result = ingest_trades(conn, trades, sync_run_id=sync_run_id)

                total_fetched += result.fetched
                total_inserted += result.inserted
                total_skipped += result.skipped

                print(
                    f"    pages={pages_fetched} fetched={result.fetched} "
                    f"inserted={result.inserted} skipped={result.skipped}"
                )

            print("\n[3/3] Fetching holdings...")
            holdings = client.get_holdings()
            holdings_result = sync_holdings(conn, holdings)
            print(f"  upserted={holdings_result.upserted}")

            finalize_sync_run(
                conn,
                sync_run_id,
                status="success",
                trades_fetched=total_fetched,
                trades_inserted=total_inserted,
                trades_skipped=total_skipped,
            )

        print("\n" + "=" * 60)
        print("Backfill complete.")
        print(
            f"Trades: fetched={total_fetched} inserted={total_inserted} "
            f"skipped={total_skipped}"
        )
        print(f"Holdings upserted: {holdings_result.upserted}")
        print("=" * 60)
        return 0

    except Exception as exc:
        if sync_run_id is not None:
            try:
                with conn:
                    finalize_sync_run(
                        conn,
                        sync_run_id,
                        status="failed",
                        trades_fetched=total_fetched,
                        trades_inserted=total_inserted,
                        trades_skipped=total_skipped,
                        error_message=str(exc),
                    )
            except Exception:
                pass

        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
