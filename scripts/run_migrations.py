#!/usr/bin/env python3
"""Apply pending SQL migrations to Neon PostgreSQL."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import Settings
from src.db import run_migrations


def main() -> int:
    settings = Settings.from_env()

    if not settings.database_url:
        print("ERROR: DATABASE_URL is not set in .env", file=sys.stderr)
        return 1

    try:
        applied = run_migrations(settings)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if applied:
        print("Applied migrations:")
        for version in applied:
            print(f"  - {version}")
    else:
        print("No pending migrations.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
