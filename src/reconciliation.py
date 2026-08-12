from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from psycopg2.extensions import connection as PgConnection

DEFAULT_RECONCILIATION_REPORT_PATH = (
    Path(__file__).resolve().parents[1] / "output" / "reconciliation_latest.json"
)

FIFO_QTY_BY_ISIN_SQL = """
SELECT isin, COALESCE(SUM(remaining_quantity), 0)::INTEGER AS fifo_qty
FROM lots
WHERE status = 'open'
GROUP BY isin
"""

HOLDINGS_QTY_BY_ISIN_SQL = """
SELECT isin, COALESCE(SUM(available_qty), 0)::INTEGER AS holdings_qty
FROM holdings_current
WHERE isin IS NOT NULL
  AND isin <> ''
GROUP BY isin
"""


class ReconciliationError(Exception):
    """Raised when FIFO open qty does not match holdings."""


@dataclass(frozen=True)
class IsinMismatch:
    isin: str
    fifo_qty: int
    holdings_qty: int

    @property
    def diff(self) -> int:
        return self.fifo_qty - self.holdings_qty


@dataclass(frozen=True)
class ReconciliationResult:
    matched_isins: int
    fifo_only_isins: list[IsinMismatch]
    holdings_only_isins: list[IsinMismatch]
    qty_mismatches: list[IsinMismatch]

    @property
    def ok(self) -> bool:
        return (
            not self.fifo_only_isins
            and not self.holdings_only_isins
            and not self.qty_mismatches
        )

    @property
    def total_mismatches(self) -> int:
        return (
            len(self.fifo_only_isins)
            + len(self.holdings_only_isins)
            + len(self.qty_mismatches)
        )


def _fetch_qty_map(conn: PgConnection, sql: str) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return {row[0]: row[1] for row in rows}


def reconcile(conn: PgConnection) -> ReconciliationResult:
    fifo_qty = _fetch_qty_map(conn, FIFO_QTY_BY_ISIN_SQL)
    holdings_qty = _fetch_qty_map(conn, HOLDINGS_QTY_BY_ISIN_SQL)

    fifo_only: list[IsinMismatch] = []
    holdings_only: list[IsinMismatch] = []
    qty_mismatches: list[IsinMismatch] = []
    matched = 0

    all_isins = set(fifo_qty) | set(holdings_qty)

    for isin in sorted(all_isins):
        fifo = fifo_qty.get(isin, 0)
        holdings = holdings_qty.get(isin, 0)

        if fifo == 0 and holdings == 0:
            continue

        if isin not in holdings_qty and fifo > 0:
            fifo_only.append(IsinMismatch(isin, fifo, 0))
            continue

        if isin not in fifo_qty and holdings > 0:
            holdings_only.append(IsinMismatch(isin, 0, holdings))
            continue

        if fifo == holdings:
            matched += 1
        else:
            qty_mismatches.append(IsinMismatch(isin, fifo, holdings))

    return ReconciliationResult(
        matched_isins=matched,
        fifo_only_isins=fifo_only,
        holdings_only_isins=holdings_only,
        qty_mismatches=qty_mismatches,
    )


def format_reconciliation_report(result: ReconciliationResult) -> str:
    lines = [
        "Reconciliation (FIFO open qty vs holdings_current.available_qty by ISIN):",
        f"  matched: {result.matched_isins}",
    ]

    if result.ok:
        lines.append("  status: OK")
        return "\n".join(lines)

    lines.append(f"  mismatches: {result.total_mismatches}")

    for label, mismatches in (
        ("FIFO only (no holdings row)", result.fifo_only_isins),
        ("Holdings only (no open FIFO lots)", result.holdings_only_isins),
        ("Quantity mismatch", result.qty_mismatches),
    ):
        if not mismatches:
            continue
        lines.append(f"  {label}:")
        for item in mismatches:
            lines.append(
                f"    {item.isin}: fifo={item.fifo_qty} holdings={item.holdings_qty} "
                f"diff={item.diff:+d}"
            )

    return "\n".join(lines)


def assert_reconciled(conn: PgConnection) -> ReconciliationResult:
    result = reconcile(conn)
    if not result.ok:
        raise ReconciliationError(format_reconciliation_report(result))
    return result


def _mismatch_payload(
    category: str,
    mismatches: list[IsinMismatch],
) -> list[dict[str, Any]]:
    return [
        {
            "category": category,
            "isin": item.isin,
            "fifo_qty": item.fifo_qty,
            "holdings_qty": item.holdings_qty,
            "diff": item.diff,
        }
        for item in mismatches
    ]


def reconciliation_to_dict(
    result: ReconciliationResult,
    *,
    run_at: datetime | None = None,
) -> dict[str, Any]:
    timestamp = run_at or datetime.now(timezone.utc)
    all_mismatches = [
        *_mismatch_payload("fifo_only", result.fifo_only_isins),
        *_mismatch_payload("holdings_only", result.holdings_only_isins),
        *_mismatch_payload("qty_mismatch", result.qty_mismatches),
    ]
    return {
        "run_at": timestamp.isoformat(),
        "status": "ok" if result.ok else "failed",
        "matched_isins": result.matched_isins,
        "total_mismatches": result.total_mismatches,
        "mismatches": all_mismatches,
    }


def write_reconciliation_report(
    result: ReconciliationResult,
    path: Path | None = None,
    *,
    run_at: datetime | None = None,
) -> Path:
    report_path = path or DEFAULT_RECONCILIATION_REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = reconciliation_to_dict(result, run_at=run_at)
    report_path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return report_path
