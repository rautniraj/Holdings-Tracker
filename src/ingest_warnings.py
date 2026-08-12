from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.trade_ingest import dedup_key_from_api_trade, dedup_key_from_row

if TYPE_CHECKING:
    from psycopg2.extensions import connection as PgConnection

DEFAULT_INGEST_WARNINGS_PATH = (
    Path(__file__).resolve().parents[1] / "output" / "ingest_warnings_latest.json"
)

DB_TRADES_SQL = """
SELECT
  id,
  order_id,
  exchange_time,
  transaction_type,
  traded_quantity,
  traded_price,
  security_id,
  isin
FROM dhan_trades
"""

# Same 7-field dedup key as dhan_trades unique constraint (via trade_ingest.dedup_key_from_*).
# Group fills by order + ISIN + side; warn when DB has more 7-keys than latest API for that group.


@dataclass(frozen=True)
class IngestWarning:
    type: str
    order_id: str
    isin: str
    transaction_type: str
    rows_in_db: int
    rows_in_latest_api: int
    stale_dedup_keys: int
    db_trade_ids: tuple[int, ...]
    message: str


def _group_key(order_id: str, isin: str, transaction_type: str) -> tuple[str, str, str]:
    return (order_id, isin, transaction_type)


def dedup_key_from_db_row(
    order_id: str,
    exchange_time: datetime,
    transaction_type: str,
    traded_quantity: int,
    traded_price: Decimal,
    security_id: str,
    isin: str,
) -> tuple[Any, ...]:
    return dedup_key_from_row(
        {
            "order_id": order_id,
            "exchange_time": exchange_time,
            "transaction_type": transaction_type,
            "traded_quantity": traded_quantity,
            "traded_price": traded_price,
            "security_id": security_id,
            "isin": isin,
        }
    )


def _api_groups(api_trades: list[dict]) -> dict[tuple[str, str, str], set[tuple[Any, ...]]]:
    groups: dict[tuple[str, str, str], set[tuple[Any, ...]]] = defaultdict(set)
    for trade in api_trades:
        try:
            dedup_key = dedup_key_from_api_trade(trade)
        except ValueError:
            continue
        order_id = str(trade.get("orderId", "")).strip()
        isin = str(trade.get("isin", "")).strip()
        transaction_type = str(trade.get("transactionType", "")).strip()
        if not isin or not transaction_type:
            continue
        group = _group_key(order_id, isin, transaction_type)
        groups[group].add(dedup_key)
    return groups


def _db_groups(
    conn: PgConnection,
) -> dict[tuple[str, str, str], dict[tuple[Any, ...], list[int]]]:
    groups: dict[tuple[str, str, str], dict[tuple[Any, ...], list[int]]] = defaultdict(dict)
    with conn.cursor() as cur:
        cur.execute(DB_TRADES_SQL)
        rows = cur.fetchall()

    for row in rows:
        trade_id, order_id, exchange_time, transaction_type, qty, price, security_id, isin = row
        if not isin:
            continue
        order_id = str(order_id)
        isin = str(isin).strip()
        transaction_type = str(transaction_type)
        group = _group_key(order_id, isin, transaction_type)
        dedup_key = dedup_key_from_db_row(
            order_id, exchange_time, transaction_type, qty, price, str(security_id), isin
        )
        groups[group].setdefault(dedup_key, []).append(trade_id)

    return groups


def detect_stale_trade_duplicates(
    conn: PgConnection,
    api_trades: list[dict],
) -> list[IngestWarning]:
    """Warn when DB has extra 7-key fill rows vs latest API for the same order+ISIN+side."""
    api_by_group = _api_groups(api_trades)
    db_by_group = _db_groups(conn)
    warnings: list[IngestWarning] = []

    for group, api_keys in sorted(api_by_group.items()):
        db_key_map = db_by_group.get(group, {})
        db_keys = set(db_key_map)
        stale_keys = db_keys - api_keys
        api_count = len(api_keys)
        db_count = len(db_keys)

        if db_count <= api_count and not stale_keys:
            continue

        order_id, isin, transaction_type = group
        context = f"order_id={order_id} isin={isin} {transaction_type}"

        stale_ids: list[int] = []
        for key in stale_keys:
            stale_ids.extend(db_key_map[key])

        warnings.append(
            IngestWarning(
                type="stale_trade_duplicate",
                order_id=order_id,
                isin=isin,
                transaction_type=transaction_type,
                rows_in_db=db_count,
                rows_in_latest_api=api_count,
                stale_dedup_keys=len(stale_keys),
                db_trade_ids=tuple(sorted(stale_ids)),
                message=(
                    f"{context}: DB has {db_count} fill row(s) but latest API has {api_count}. "
                    f"{len(stale_keys)} stale 7-key row(s) not in API — possible Dhan correction. "
                    "Review dhan_trades, delete stale row(s), re-run FIFO."
                ),
            )
        )

    return warnings


def warnings_to_dict(
    warnings: list[IngestWarning],
    *,
    run_at: datetime | None = None,
    sync_run_id: int | None = None,
) -> dict[str, Any]:
    timestamp = run_at or datetime.now(timezone.utc)
    return {
        "run_at": timestamp.isoformat(),
        "sync_run_id": sync_run_id,
        "warning_count": len(warnings),
        "warnings": [
            {
                "type": warning.type,
                "order_id": warning.order_id,
                "isin": warning.isin,
                "transaction_type": warning.transaction_type,
                "rows_in_db": warning.rows_in_db,
                "rows_in_latest_api": warning.rows_in_latest_api,
                "stale_dedup_keys": warning.stale_dedup_keys,
                "db_trade_ids": list(warning.db_trade_ids),
                "message": warning.message,
            }
            for warning in warnings
        ],
    }


def write_ingest_warnings(
    warnings: list[IngestWarning],
    path: Path | None = None,
    *,
    run_at: datetime | None = None,
    sync_run_id: int | None = None,
) -> Path:
    report_path = path or DEFAULT_INGEST_WARNINGS_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = warnings_to_dict(warnings, run_at=run_at, sync_run_id=sync_run_id)
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return report_path
