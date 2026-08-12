from __future__ import annotations

from dataclasses import dataclass

from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import Json

UPSERT_HOLDING_SQL = """
INSERT INTO holdings_current (
  security_id,
  trading_symbol,
  isin,
  exchange,
  total_qty,
  dp_qty,
  t1_qty,
  mtf_t1_qty,
  mtf_qty,
  available_qty,
  collateral_qty,
  avg_cost_price,
  last_traded_price,
  raw_payload
) VALUES (
  %(security_id)s,
  %(trading_symbol)s,
  %(isin)s,
  %(exchange)s,
  %(total_qty)s,
  %(dp_qty)s,
  %(t1_qty)s,
  %(mtf_t1_qty)s,
  %(mtf_qty)s,
  %(available_qty)s,
  %(collateral_qty)s,
  %(avg_cost_price)s,
  %(last_traded_price)s,
  %(raw_payload)s
)
ON CONFLICT (security_id) DO UPDATE SET
  trading_symbol = EXCLUDED.trading_symbol,
  isin = EXCLUDED.isin,
  exchange = EXCLUDED.exchange,
  total_qty = EXCLUDED.total_qty,
  dp_qty = EXCLUDED.dp_qty,
  t1_qty = EXCLUDED.t1_qty,
  mtf_t1_qty = EXCLUDED.mtf_t1_qty,
  mtf_qty = EXCLUDED.mtf_qty,
  available_qty = EXCLUDED.available_qty,
  collateral_qty = EXCLUDED.collateral_qty,
  avg_cost_price = EXCLUDED.avg_cost_price,
  last_traded_price = EXCLUDED.last_traded_price,
  raw_payload = EXCLUDED.raw_payload
"""

DELETE_HOLDINGS_NOT_IN_SQL = """
DELETE FROM holdings_current
WHERE NOT (security_id = ANY(%s))
"""


@dataclass(frozen=True)
class HoldingsSyncResult:
    upserted: int
    deleted: int


def _holding_row(holding: dict) -> dict:
    security_id = holding.get("securityId")
    if not security_id:
        raise ValueError(f"Holding missing securityId: {holding}")

    return {
        "security_id": str(security_id),
        "trading_symbol": holding.get("tradingSymbol"),
        "isin": holding.get("isin"),
        "exchange": holding.get("exchange"),
        "total_qty": holding.get("totalQty"),
        "dp_qty": holding.get("dpQty"),
        "t1_qty": holding.get("t1Qty"),
        "mtf_t1_qty": holding.get("mtf_t1_qty"),
        "mtf_qty": holding.get("mtf_qty"),
        "available_qty": holding.get("availableQty"),
        "collateral_qty": holding.get("collateralQty"),
        "avg_cost_price": holding.get("avgCostPrice"),
        "last_traded_price": holding.get("lastTradedPrice"),
        "raw_payload": Json(holding),
    }


def sync_holdings_snapshot(
    conn: PgConnection, holdings: list[dict]
) -> HoldingsSyncResult:
    """Upsert API holdings and remove DB rows absent from the latest snapshot."""
    api_security_ids: list[str] = []
    for holding in holdings:
        security_id = holding.get("securityId")
        if not security_id:
            raise ValueError(f"Holding missing securityId: {holding}")
        api_security_ids.append(str(security_id))

    with conn.cursor() as cur:
        for holding in holdings:
            cur.execute(UPSERT_HOLDING_SQL, _holding_row(holding))

        if api_security_ids:
            cur.execute(DELETE_HOLDINGS_NOT_IN_SQL, (api_security_ids,))
        else:
            cur.execute("DELETE FROM holdings_current")
        deleted = cur.rowcount

    return HoldingsSyncResult(upserted=len(holdings), deleted=deleted)


def sync_holdings(conn: PgConnection, holdings: list[dict]) -> HoldingsSyncResult:
    """Alias for snapshot sync (Phase 4)."""
    return sync_holdings_snapshot(conn, holdings)
