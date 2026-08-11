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

# Backfill trades
.venv/bin/python scripts/backfill_trades.py
