#!/usr/bin/env python3
"""Phase 1 — Dhan API & Authentication validation."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.auth import AUTH_RESPONSE_PATH, get_access_token
from src.config import Settings
from src.dhan_client import DhanClient, default_trade_date_range

OUTPUT_DIR = ROOT / "output"


def save_json(name: str, payload: object) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def main() -> int:
    print("=" * 60)
    print("Phase 1 — Dhan API & Authentication")
    print(f"As of: {datetime.now().strftime('%d-%b-%Y %H:%M:%S')}")
    print("=" * 60)

    settings = Settings.from_env()

    print("\n[1/4] Authenticating with TOTP...")
    auth_payload, reused = get_access_token(settings)
    if not settings.reuse_access_token:
        save_json("auth_response.json", auth_payload)
    print(
        f"  {'Reusing cached' if reused else 'Generated new'} access token "
        f"(metadata in {AUTH_RESPONSE_PATH.name})"
    )
    print(f"  expiryTime:  {auth_payload.get('expiryTime')}")
    print(f"  clientName:  {auth_payload.get('dhanClientName')}")

    client = DhanClient(auth_payload["accessToken"], settings)

    print("\n[2/4] Fetching profile...")
    profile = client.get_profile()
    profile_path = save_json("profile.json", profile)
    print(f"  saved → {profile_path.name}")
    print(f"  keys:  {', '.join(sorted(profile.keys()) if isinstance(profile, dict) else [])}")

    print("\n[3/4] Fetching holdings...")
    holdings = client.get_holdings()
    holdings_path = save_json("holdings.json", holdings)
    print(f"  saved → {holdings_path.name}")
    print(f"  count: {len(holdings)} securities")

    print("\n[4/4] Fetching trade history (paginated)...")
    from_date, to_date = default_trade_date_range(settings)
    print(f"  date range: {from_date} → {to_date}")
    trades, pages_fetched = client.get_trade_history(from_date, to_date)
    trades_path = save_json("trade_history.json", trades)
    print(f"  saved → {trades_path.name}")
    print(f"  pages fetched: {pages_fetched}")
    print(f"  trades total:  {len(trades)}")

    if trades:
        sample = trades[0]
        print(f"  sample keys:   {', '.join(sorted(sample.keys()))}")

    print("\n" + "=" * 60)
    print("Phase 1 validation complete.")
    print(f"Raw responses saved under: {OUTPUT_DIR}/")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
