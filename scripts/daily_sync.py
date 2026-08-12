#!/usr/bin/env python3
"""Daily sync — incremental trade ingest + holdings snapshot (Phase 4)."""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.auth import get_access_token
from src.config import Settings
from src.db import get_connection
from src.dhan_client import DhanClient
from src.holdings_sync import sync_holdings_snapshot
from src.ingest_warnings import (
    detect_stale_trade_duplicates,
    write_ingest_warnings,
)
from src.ntfy import send_notification
from src.sync_range import (
    EmptyTradeLedgerError,
    monthly_chunks,
    resolve_trade_sync_range,
    today_ist,
)
from src.sync_run import create_sync_run, finalize_sync_run
from src.trade_ingest import ingest_trades


def main() -> int:
    settings = Settings.from_env()

    if not settings.database_url:
        print("ERROR: DATABASE_URL is not set in .env", file=sys.stderr)
        return 1

    print("=" * 60)
    print("Daily Sync — Incremental Trades + Holdings Snapshot")
    print(f"As of: {datetime.now().strftime('%d-%b-%Y %H:%M:%S')}")
    print("=" * 60)

    conn = get_connection(settings)
    sync_run_id: int | None = None
    total_fetched = 0
    total_inserted = 0
    total_updated = 0
    total_unchanged = 0
    all_api_trades: list[dict] = []
    ingest_warnings = []
    warnings_path: Path | None = None
    holdings_result = None
    run_at = datetime.now().astimezone()
    trade_sync_skipped = False

    try:
        with conn:
            trade_range = resolve_trade_sync_range(conn)

        if trade_range is None:
            trade_sync_skipped = True
            today = today_ist()
            trade_from = trade_to = today
            chunks: list[tuple] = []
            print(
                f"\nTrade cursor: up to date (last closed day is today or later). "
                f"Skipping trade fetch."
            )
        else:
            trade_from = trade_range.trade_from
            trade_to = trade_range.trade_to
            chunks = monthly_chunks(trade_from, trade_to)
            print(
                f"\nTrade cursor: {trade_from.isoformat()} -> {trade_to.isoformat()} "
                f"({len(chunks)} chunk(s))"
            )

        print("\n[1/4] Authenticating with TOTP...")
        auth_payload, reused = get_access_token(settings)
        print(f"  {'Reusing cached' if reused else 'Generated new'} access token")
        client = DhanClient(auth_payload["accessToken"], settings)

        with conn:
            sync_run_id = create_sync_run(conn, trade_from, trade_to)
            print(f"  sync_run_id: {sync_run_id}")

            if not trade_sync_skipped:
                print("\n[2/4] Fetching trade history...")
                for index, (chunk_from, chunk_to) in enumerate(chunks):
                    if index > 0 and settings.trade_history_sleep_seconds > 0:
                        time.sleep(settings.trade_history_sleep_seconds)

                    chunk_label = f"{chunk_from.isoformat()} -> {chunk_to.isoformat()}"
                    print(f"  chunk {index + 1}/{len(chunks)}: {chunk_label}")

                    trades, pages_fetched = client.get_trade_history(
                        chunk_from.isoformat(),
                        chunk_to.isoformat(),
                    )
                    all_api_trades.extend(trades)
                    result = ingest_trades(conn, trades, sync_run_id=sync_run_id)

                    total_fetched += result.fetched
                    total_inserted += result.inserted
                    total_updated += result.updated
                    total_unchanged += result.unchanged

                    print(
                        f"    pages={pages_fetched} fetched={result.fetched} "
                        f"inserted={result.inserted} updated={result.updated} "
                        f"unchanged={result.unchanged}"
                    )
            else:
                print("\n[2/4] Fetching trade history... skipped (cursor up to date)")

            print("\n[3/4] Fetching holdings snapshot...")
            holdings = client.get_holdings()
            holdings_result = sync_holdings_snapshot(conn, holdings)
            print(
                f"  upserted={holdings_result.upserted} "
                f"deleted={holdings_result.deleted}"
            )

            print("\n[4/4] Checking for stale trade duplicates...")
            if all_api_trades:
                ingest_warnings = detect_stale_trade_duplicates(conn, all_api_trades)
            else:
                ingest_warnings = []
            warnings_path = write_ingest_warnings(
                ingest_warnings,
                run_at=run_at,
                sync_run_id=sync_run_id,
            )
            if ingest_warnings:
                print(f"  warnings: {len(ingest_warnings)} (see {warnings_path})")
                for warning in ingest_warnings:
                    print(f"    - {warning.isin}: {warning.message}")
            else:
                print(f"  no warnings (report: {warnings_path})")

            finalize_sync_run(
                conn,
                sync_run_id,
                status="success",
                trades_fetched=total_fetched,
                trades_inserted=total_inserted,
                trades_skipped=total_unchanged,
            )

        if ingest_warnings:
            send_notification(
                settings,
                title="Holdings Tracker — ingest warnings",
                message=(
                    f"{len(ingest_warnings)} stale trade duplicate(s) detected.\n"
                    f"See ingest_warnings_latest.json — review and re-run FIFO."
                ),
                priority="high",
                tags="warning",
            )

        print("\n" + "=" * 60)
        print("Daily sync complete.")
        if trade_sync_skipped:
            print("Trades: skipped (cursor up to date)")
        else:
            print(
                f"Trades: fetched={total_fetched} inserted={total_inserted} "
                f"updated={total_updated} unchanged={total_unchanged}"
            )
        if holdings_result:
            print(
                f"Holdings: upserted={holdings_result.upserted} "
                f"deleted={holdings_result.deleted}"
            )
        print("=" * 60)
        return 1 if ingest_warnings else 0

    except EmptyTradeLedgerError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1

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
                        trades_skipped=total_unchanged,
                        error_message=str(exc),
                    )
            except Exception:
                pass

        send_notification(
            settings,
            title="Holdings Tracker — daily sync failed",
            message=str(exc),
            priority="urgent",
            tags="x",
        )
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
