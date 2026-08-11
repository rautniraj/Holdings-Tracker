#!/usr/bin/env python3
"""Verify connectivity to Neon PostgreSQL."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import Settings
from src.db import check_connection


def main() -> int:
    settings = Settings.from_env()

    if not settings.database_url:
        print("ERROR: DATABASE_URL is not set in .env", file=sys.stderr)
        return 1

    try:
        version = check_connection(settings)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("Connected to Neon PostgreSQL")
    print(f"Server version: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
