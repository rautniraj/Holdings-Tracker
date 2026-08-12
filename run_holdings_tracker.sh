#!/usr/bin/env bash
set -euo pipefail


python3 -m venv .venv

# Install dependencies
.venv/bin/pip install -r requirements.txt

# Run phase1 validation
.venv/bin/python scripts/phase1_validate.py

# Verify connection
.venv/bin/python scripts/test_db_connection.py

# Apply migrations (safe to re-run — skips already applied)
.venv/bin/python scripts/run_migrations.py

# Backfill trades + sync holdings from Dhan API.
# Run when you need fresh trade history or holdings snapshot (e.g. after new trades, # or before FIFO if dhan_trades / holdings_current may be stale).
.venv/bin/python scripts/backfill_trades.py

# FIFO lot engine + reconciliation (Phase 3).
# Run after backfill when dhan_trades is up to date — rebuilds lots from trade history
# and checks open qty vs holdings_current.available_qty by ISIN.
# Also re-run after editing config/lt_exceptions.json (custom LT months or never_lt ISINs).
.venv/bin/python scripts/run_fifo.py
