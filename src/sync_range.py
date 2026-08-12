"""Incremental trade sync date range derived from dhan_trades cursor."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from psycopg2.extensions import connection as PgConnection

IST = ZoneInfo("Asia/Kolkata")

LAST_TRADE_DAY_SQL = """
SELECT MAX((exchange_time AT TIME ZONE 'Asia/Kolkata')::date)
FROM dhan_trades
"""


class EmptyTradeLedgerError(Exception):
    """Raised when daily sync runs against an empty dhan_trades table."""


@dataclass(frozen=True)
class TradeSyncRange:
    trade_from: date
    trade_to: date


def today_ist() -> date:
    return datetime.now(tz=IST).date()


def resolve_trade_sync_range(conn: PgConnection) -> TradeSyncRange | None:
    """Return [last_trade_day + 1, today] in IST, or None when already up to date."""
    with conn.cursor() as cur:
        cur.execute(LAST_TRADE_DAY_SQL)
        row = cur.fetchone()

    last_trade_day: date | None = row[0] if row else None
    if last_trade_day is None:
        raise EmptyTradeLedgerError(
            "dhan_trades is empty — run scripts/backfill_trades.py first "
            "(set DHAN_TRADE_FROM in .env for the start date)."
        )

    trade_from = last_trade_day + timedelta(days=1)
    trade_to = today_ist()

    if trade_from > trade_to:
        return None

    return TradeSyncRange(trade_from=trade_from, trade_to=trade_to)


def monthly_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Split [start, end] into calendar-month windows for Trade History API calls."""
    chunks: list[tuple[date, date]] = []
    current = start

    while current <= end:
        last_day = calendar.monthrange(current.year, current.month)[1]
        chunk_end = min(date(current.year, current.month, last_day), end)
        chunks.append((current, chunk_end))

        if chunk_end >= end:
            break

        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)

    return chunks
