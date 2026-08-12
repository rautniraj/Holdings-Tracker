#!/usr/bin/env python3
"""Build FIFO lots from dhan_trades and reconcile against holdings_current."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import Settings
from src.db import get_connection, run_migrations
from src.fifo_engine import FifoError, build_lots
from src.lt_rules import LtRulesError
from src.ntfy import send_notification
from src.reconciliation import (
    format_reconciliation_report,
    reconcile,
    write_reconciliation_report,
)


def main() -> int:
    settings = Settings.from_env()

    if not settings.database_url:
        print("ERROR: DATABASE_URL is not set in .env", file=sys.stderr)
        return 1

    print("=" * 60)
    print("FIFO Lot Engine + Reconciliation")
    print(f"As of: {datetime.now().strftime('%d-%b-%Y %H:%M:%S')}")
    print("=" * 60)

    try:
        applied = run_migrations(settings)
        if applied:
            print("\nApplied migrations:")
            for version in applied:
                print(f"  - {version}")

        conn = get_connection(settings)
        try:
            print("\n[1/2] Building lots from dhan_trades (CNC / NSE_EQ + BSE_EQ)...")
            fifo_result = build_lots(conn)
            print(f"  trades processed: {fifo_result.trades_processed}")
            print(f"  lots created:     {fifo_result.lots_created}")
            print(f"  lots closed:      {fifo_result.lots_closed}")
            print(f"  lots open:        {fifo_result.open_lots}")
            print(f"  allocations:      {fifo_result.allocations_created}")

            print("\n[2/2] Reconciling open qty vs holdings_current.available_qty...")
            run_at = datetime.now().astimezone()
            result = reconcile(conn)
            report_path = write_reconciliation_report(result, run_at=run_at)
            print(format_reconciliation_report(result))
            print(f"\n  report saved: {report_path}")

            if not result.ok:
                mismatch_lines = format_reconciliation_report(result)
                send_notification(
                    settings,
                    title="Holdings Tracker — reconciliation failed",
                    message=mismatch_lines,
                    priority="high",
                    tags="warning",
                )
                print(
                    "\nERROR: Reconciliation failed. "
                    "See mismatches above (T+1 settlement may cause recent SELL lag).",
                    file=sys.stderr,
                )
                return 1

            print("\n" + "=" * 60)
            print("FIFO + reconciliation complete.")
            print("=" * 60)
            return 0
        finally:
            conn.close()

    except FifoError as exc:
        print(f"\nERROR: FIFO processing failed: {exc}", file=sys.stderr)
        return 1
    except LtRulesError as exc:
        print(f"\nERROR: Invalid LT exceptions config: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
