from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import Json

INSERT_TRADE_SQL = """
INSERT INTO dhan_trades (
  order_id,
  exchange_time,
  transaction_type,
  traded_quantity,
  traded_price,
  security_id,
  dhan_client_id,
  exchange_order_id,
  exchange_trade_id,
  exchange_segment,
  product_type,
  order_type,
  custom_symbol,
  isin,
  instrument,
  sebi_tax,
  stt,
  brokerage_charges,
  service_tax,
  exchange_transaction_charges,
  stamp_duty,
  create_time,
  update_time,
  drv_expiry_date,
  drv_option_type,
  drv_strike_price,
  raw_payload,
  sync_run_id
) VALUES (
  %(order_id)s,
  %(exchange_time)s,
  %(transaction_type)s,
  %(traded_quantity)s,
  %(traded_price)s,
  %(security_id)s,
  %(dhan_client_id)s,
  %(exchange_order_id)s,
  %(exchange_trade_id)s,
  %(exchange_segment)s,
  %(product_type)s,
  %(order_type)s,
  %(custom_symbol)s,
  %(isin)s,
  %(instrument)s,
  %(sebi_tax)s,
  %(stt)s,
  %(brokerage_charges)s,
  %(service_tax)s,
  %(exchange_transaction_charges)s,
  %(stamp_duty)s,
  %(create_time)s,
  %(update_time)s,
  %(drv_expiry_date)s,
  %(drv_option_type)s,
  %(drv_strike_price)s,
  %(raw_payload)s,
  %(sync_run_id)s
)
ON CONFLICT (order_id, exchange_time, transaction_type, traded_quantity, traded_price, security_id, isin)
DO UPDATE SET
  dhan_client_id = EXCLUDED.dhan_client_id,
  exchange_order_id = EXCLUDED.exchange_order_id,
  exchange_trade_id = EXCLUDED.exchange_trade_id,
  exchange_segment = EXCLUDED.exchange_segment,
  product_type = EXCLUDED.product_type,
  order_type = EXCLUDED.order_type,
  custom_symbol = EXCLUDED.custom_symbol,
  instrument = EXCLUDED.instrument,
  sebi_tax = EXCLUDED.sebi_tax,
  stt = EXCLUDED.stt,
  brokerage_charges = EXCLUDED.brokerage_charges,
  service_tax = EXCLUDED.service_tax,
  exchange_transaction_charges = EXCLUDED.exchange_transaction_charges,
  stamp_duty = EXCLUDED.stamp_duty,
  create_time = EXCLUDED.create_time,
  update_time = EXCLUDED.update_time,
  drv_expiry_date = EXCLUDED.drv_expiry_date,
  drv_option_type = EXCLUDED.drv_option_type,
  drv_strike_price = EXCLUDED.drv_strike_price,
  raw_payload = EXCLUDED.raw_payload,
  sync_run_id = EXCLUDED.sync_run_id
WHERE dhan_trades.raw_payload IS DISTINCT FROM EXCLUDED.raw_payload
RETURNING (xmax = 0) AS inserted
"""


@dataclass(frozen=True)
class IngestResult:
    fetched: int
    inserted: int
    updated: int
    unchanged: int


def parse_exchange_time(value: str) -> datetime:
    normalized = value.strip()
    if not normalized or normalized.upper() == "NA":
        raise ValueError("exchangeTime is missing or NA")

    if "T" in normalized:
        parsed = datetime.fromisoformat(normalized)
    else:
        parsed = datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")

    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _normalize_price(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def dedup_key_from_row(row: dict) -> tuple[Any, ...]:
    exchange_time = row["exchange_time"]
    if isinstance(exchange_time, datetime) and exchange_time.tzinfo is not None:
        exchange_time = exchange_time.astimezone(timezone.utc).replace(tzinfo=None)
    return (
        row["order_id"],
        exchange_time,
        row["transaction_type"],
        int(row["traded_quantity"]),
        _normalize_price(row["traded_price"]),
        row["security_id"],
        row["isin"],
    )


def dedup_key_from_api_trade(trade: dict) -> tuple[Any, ...]:
    return dedup_key_from_row(_trade_row(trade, sync_run_id=None))


def _trade_row(trade: dict, sync_run_id: int | None) -> dict:
    order_id = trade.get("orderId")
    security_id = trade.get("securityId")
    transaction_type = trade.get("transactionType")
    traded_quantity = trade.get("tradedQuantity")
    traded_price = trade.get("tradedPrice")
    isin = trade.get("isin")
    exchange_time_raw = trade.get("exchangeTime")

    if order_id is None or str(order_id).strip() == "":
        raise ValueError(f"Trade missing orderId: {trade}")
    if security_id is None or str(security_id).strip() == "":
        raise ValueError(f"Trade missing securityId: {trade}")
    if not isin or str(isin).strip() == "":
        raise ValueError(f"Trade missing isin: {trade}")
    if not transaction_type:
        raise ValueError(f"Trade missing transactionType: {trade}")
    if traded_quantity is None:
        raise ValueError(f"Trade missing tradedQuantity: {trade}")
    if traded_price is None:
        raise ValueError(f"Trade missing tradedPrice: {trade}")
    if not exchange_time_raw:
        raise ValueError(f"Trade missing exchangeTime: {trade}")

    return {
        "order_id": str(order_id),
        "exchange_time": parse_exchange_time(str(exchange_time_raw)),
        "transaction_type": str(transaction_type),
        "traded_quantity": int(traded_quantity),
        "traded_price": traded_price,
        "security_id": str(security_id),
        "dhan_client_id": trade.get("dhanClientId"),
        "exchange_order_id": trade.get("exchangeOrderId"),
        "exchange_trade_id": trade.get("exchangeTradeId"),
        "exchange_segment": trade.get("exchangeSegment"),
        "product_type": trade.get("productType"),
        "order_type": trade.get("orderType"),
        "custom_symbol": trade.get("customSymbol"),
        "isin": str(isin).strip(),
        "instrument": trade.get("instrument"),
        "sebi_tax": trade.get("sebiTax"),
        "stt": trade.get("stt"),
        "brokerage_charges": trade.get("brokerageCharges"),
        "service_tax": trade.get("serviceTax"),
        "exchange_transaction_charges": trade.get("exchangeTransactionCharges"),
        "stamp_duty": trade.get("stampDuty"),
        "create_time": trade.get("createTime"),
        "update_time": trade.get("updateTime"),
        "drv_expiry_date": trade.get("drvExpiryDate"),
        "drv_option_type": trade.get("drvOptionType"),
        "drv_strike_price": trade.get("drvStrikePrice"),
        "raw_payload": Json(trade),
        "sync_run_id": sync_run_id,
    }


def ingest_trades(
    conn: PgConnection,
    trades: list[dict],
    sync_run_id: int | None = None,
) -> IngestResult:
    inserted = 0
    updated = 0
    unchanged = 0

    with conn.cursor() as cur:
        for trade in trades:
            row = _trade_row(trade, sync_run_id)
            cur.execute(INSERT_TRADE_SQL, row)
            result = cur.fetchone()
            if result is None:
                unchanged += 1
            elif result[0]:
                inserted += 1
            else:
                updated += 1

    return IngestResult(
        fetched=len(trades),
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
    )
