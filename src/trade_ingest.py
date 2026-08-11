from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
ON CONFLICT (order_id, exchange_time, transaction_type, traded_quantity, traded_price, security_id)
DO NOTHING
"""


@dataclass(frozen=True)
class IngestResult:
    fetched: int
    inserted: int
    skipped: int


def parse_exchange_time(value: str) -> datetime:
    normalized = value.strip()
    if not normalized or normalized.upper() == "NA":
        raise ValueError("exchangeTime is missing or NA")

    if "T" in normalized:
        return datetime.fromisoformat(normalized)

    return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")


def _trade_row(trade: dict, sync_run_id: int | None) -> dict:
    order_id = trade.get("orderId")
    security_id = trade.get("securityId")
    transaction_type = trade.get("transactionType")
    traded_quantity = trade.get("tradedQuantity")
    traded_price = trade.get("tradedPrice")
    exchange_time_raw = trade.get("exchangeTime")

    if not order_id:
        raise ValueError(f"Trade missing orderId: {trade}")
    if not security_id:
        raise ValueError(f"Trade missing securityId: {trade}")
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
        "isin": trade.get("isin"),
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
    skipped = 0

    with conn.cursor() as cur:
        for trade in trades:
            row = _trade_row(trade, sync_run_id)
            cur.execute(INSERT_TRADE_SQL, row)
            if cur.rowcount:
                inserted += 1
            else:
                skipped += 1

    return IngestResult(fetched=len(trades), inserted=inserted, skipped=skipped)
