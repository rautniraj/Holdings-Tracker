from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from src.lt_rules import LtRules, load_lt_rules, lt_conversion_date

if TYPE_CHECKING:
    from psycopg2.extensions import connection as PgConnection

FIFO_TRADES_SQL = """
SELECT
  id,
  order_id,
  exchange_time,
  transaction_type,
  traded_quantity,
  traded_price,
  security_id,
  custom_symbol,
  isin
FROM dhan_trades
WHERE product_type = 'CNC'
  AND exchange_segment IN ('NSE_EQ', 'BSE_EQ')
  AND transaction_type IN ('BUY', 'SELL')
ORDER BY exchange_time ASC, id ASC
"""

INSERT_LOT_SQL = """
INSERT INTO lots (
  isin,
  security_id,
  custom_symbol,
  purchase_date,
  lt_conversion_date,
  original_quantity,
  remaining_quantity,
  cost_per_share,
  cost_basis_unknown,
  source_trade_id,
  status
) VALUES (
  %(isin)s,
  %(security_id)s,
  %(custom_symbol)s,
  %(purchase_date)s,
  %(lt_conversion_date)s,
  %(original_quantity)s,
  %(remaining_quantity)s,
  %(cost_per_share)s,
  %(cost_basis_unknown)s,
  %(source_trade_id)s,
  %(status)s
)
RETURNING id
"""

INSERT_ALLOCATION_SQL = """
INSERT INTO lot_allocations (
  sell_trade_id,
  lot_id,
  quantity
) VALUES (
  %(sell_trade_id)s,
  %(lot_id)s,
  %(quantity)s
)
"""


class FifoError(Exception):
    """Base error for FIFO processing failures."""


class OversellError(FifoError):
    def __init__(
        self,
        isin: str,
        sell_trade_id: int,
        qty_unfilled: int,
        *,
        custom_symbol: str | None = None,
    ) -> None:
        self.isin = isin
        self.sell_trade_id = sell_trade_id
        self.qty_unfilled = qty_unfilled
        self.custom_symbol = custom_symbol
        symbol = f" ({custom_symbol})" if custom_symbol else ""
        super().__init__(
            f"Oversell for ISIN {isin}{symbol}: sell trade id={sell_trade_id} "
            f"has {qty_unfilled} shares with no open lots"
        )


class MissingIsinError(FifoError):
    def __init__(self, trade_id: int) -> None:
        self.trade_id = trade_id
        super().__init__(f"Trade id={trade_id} is missing isin — required for FIFO grouping")


@dataclass(frozen=True)
class TradeRow:
    id: int
    order_id: str
    exchange_time: datetime
    transaction_type: str
    traded_quantity: int
    traded_price: Decimal
    security_id: str
    custom_symbol: str | None
    isin: str | None


@dataclass
class OpenLot:
    lot_index: int
    remaining_quantity: int


@dataclass
class LotRecord:
    isin: str
    security_id: str
    custom_symbol: str | None
    purchase_date: datetime
    lt_conversion_date: date
    original_quantity: int
    remaining_quantity: int
    cost_per_share: Decimal
    cost_basis_unknown: bool
    source_trade_id: int
    status: str


@dataclass(frozen=True)
class AllocationRecord:
    sell_trade_id: int
    lot_index: int
    quantity: int


@dataclass(frozen=True)
class FifoResult:
    trades_processed: int
    lots_created: int
    lots_closed: int
    allocations_created: int
    open_lots: int


def is_ipo_lot(trade: TradeRow) -> bool:
    return trade.traded_price == 0 and trade.order_id == "0"


def fetch_fifo_trades(conn: PgConnection) -> list[TradeRow]:
    with conn.cursor() as cur:
        cur.execute(FIFO_TRADES_SQL)
        rows = cur.fetchall()

    return [
        TradeRow(
            id=row[0],
            order_id=row[1],
            exchange_time=row[2],
            transaction_type=row[3],
            traded_quantity=row[4],
            traded_price=row[5],
            security_id=row[6],
            custom_symbol=row[7],
            isin=row[8],
        )
        for row in rows
    ]


def process_fifo(
    trades: list[TradeRow],
    lt_rules: LtRules | None = None,
) -> tuple[list[LotRecord], list[AllocationRecord]]:
    rules = lt_rules or LtRules(default_lt_months=12, exceptions={})
    open_lots: dict[str, deque[OpenLot]] = {}
    lots: list[LotRecord] = []
    allocations: list[AllocationRecord] = []

    for trade in trades:
        if not trade.isin or not str(trade.isin).strip():
            raise MissingIsinError(trade.id)

        isin = str(trade.isin).strip()

        if trade.transaction_type == "BUY":
            cost_basis_unknown = is_ipo_lot(trade)
            lot = LotRecord(
                isin=isin,
                security_id=trade.security_id,
                custom_symbol=trade.custom_symbol,
                purchase_date=trade.exchange_time,
                lt_conversion_date=lt_conversion_date(
                    trade.exchange_time, isin, rules
                ),
                original_quantity=trade.traded_quantity,
                remaining_quantity=trade.traded_quantity,
                cost_per_share=trade.traded_price,
                cost_basis_unknown=cost_basis_unknown,
                source_trade_id=trade.id,
                status="open",
            )
            lots.append(lot)
            open_lots.setdefault(isin, deque()).append(
                OpenLot(lot_index=len(lots) - 1, remaining_quantity=trade.traded_quantity)
            )
            continue

        if trade.transaction_type != "SELL":
            continue

        qty_to_fill = trade.traded_quantity
        queue = open_lots.get(isin)

        while qty_to_fill > 0:
            if not queue:
                raise OversellError(
                    isin,
                    trade.id,
                    qty_to_fill,
                    custom_symbol=trade.custom_symbol,
                )

            open_lot = queue[0]
            lot = lots[open_lot.lot_index]
            consume = min(open_lot.remaining_quantity, qty_to_fill)

            allocations.append(
                AllocationRecord(
                    sell_trade_id=trade.id,
                    lot_index=open_lot.lot_index,
                    quantity=consume,
                )
            )

            open_lot.remaining_quantity -= consume
            lot.remaining_quantity -= consume
            qty_to_fill -= consume

            if lot.remaining_quantity < 0:
                raise FifoError(
                    f"Negative remaining quantity on lot index {open_lot.lot_index} "
                    f"for ISIN {isin}"
                )

            if open_lot.remaining_quantity == 0:
                lot.status = "closed"
                queue.popleft()

    return lots, allocations


def _clear_lot_tables(conn: PgConnection) -> None:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE lot_allocations, lots RESTART IDENTITY")


def _persist_lots(
    conn: PgConnection,
    lots: list[LotRecord],
    allocations: list[AllocationRecord],
) -> None:
    lot_ids: list[int] = []

    with conn.cursor() as cur:
        for lot in lots:
            cur.execute(
                INSERT_LOT_SQL,
                {
                    "isin": lot.isin,
                    "security_id": lot.security_id,
                    "custom_symbol": lot.custom_symbol,
                    "purchase_date": lot.purchase_date,
                    "lt_conversion_date": lot.lt_conversion_date,
                    "original_quantity": lot.original_quantity,
                    "remaining_quantity": lot.remaining_quantity,
                    "cost_basis_unknown": lot.cost_basis_unknown,
                    "source_trade_id": lot.source_trade_id,
                    "status": lot.status,
                    "cost_per_share": lot.cost_per_share,
                },
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("Failed to insert lot row")
            lot_ids.append(row[0])

        for allocation in allocations:
            cur.execute(
                INSERT_ALLOCATION_SQL,
                {
                    "sell_trade_id": allocation.sell_trade_id,
                    "lot_id": lot_ids[allocation.lot_index],
                    "quantity": allocation.quantity,
                },
            )


def build_lots(
    conn: PgConnection,
    lt_rules_path: Path | None = None,
) -> FifoResult:
    lt_rules = load_lt_rules(lt_rules_path)
    trades = fetch_fifo_trades(conn)
    lots, allocations = process_fifo(trades, lt_rules)

    with conn:
        _clear_lot_tables(conn)
        _persist_lots(conn, lots, allocations)

    open_count = sum(1 for lot in lots if lot.status == "open")
    closed_count = sum(1 for lot in lots if lot.status == "closed")

    return FifoResult(
        trades_processed=len(trades),
        lots_created=len(lots),
        lots_closed=closed_count,
        allocations_created=len(allocations),
        open_lots=open_count,
    )
