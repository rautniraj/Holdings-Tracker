from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_LT_EXCEPTIONS_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "lt_exceptions.json"
)

# Stored in lots.lt_conversion_date when never_lt applies (column is NOT NULL).
NEVER_LT_DATE = date(9999, 12, 31)


class LtRulesError(Exception):
    """Invalid or unreadable LT exceptions config."""


@dataclass(frozen=True)
class LtException:
    isin: str
    lt_months: int | None = None
    never_lt: bool = False
    note: str | None = None


@dataclass(frozen=True)
class LtRules:
    default_lt_months: int
    exceptions: dict[str, LtException]

    def rule_for(self, isin: str) -> LtException | None:
        return self.exceptions.get(isin.strip().upper())

    def lt_months_for(self, isin: str) -> int | None:
        rule = self.rule_for(isin)
        if rule is None:
            return self.default_lt_months
        if rule.never_lt:
            return None
        return rule.lt_months if rule.lt_months is not None else self.default_lt_months


def _add_calendar_months(purchase_day: date, months: int) -> date:
    month = purchase_day.month + months
    year = purchase_day.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(purchase_day.day, max_day)
    return date(year, month, day)


def lt_conversion_date(
    purchase_date: datetime,
    isin: str,
    rules: LtRules | None = None,
) -> date:
    """First calendar day the lot qualifies as long-term.

    Indian equity rule: held *more than* 12 calendar months — not 365/366 days.
    Buy on 15 Jan → still short-term on 15 Jan next year → long-term from 16 Jan.
    Leap years are ignored; only calendar month boundaries matter.
    """
    active_rules = rules or LtRules(default_lt_months=12, exceptions={})
    months = active_rules.lt_months_for(isin)
    if months is None:
        return NEVER_LT_DATE
    purchase_day = purchase_date.date()
    return _add_calendar_months(purchase_day, months) + timedelta(days=1)


def is_never_lt(lt_conversion_date_value: date) -> bool:
    return lt_conversion_date_value == NEVER_LT_DATE


def is_long_term(
    lt_conversion_date_value: date,
    *,
    as_of: date | None = None,
) -> bool:
    if is_never_lt(lt_conversion_date_value):
        return False
    check_date = as_of or date.today()
    return check_date >= lt_conversion_date_value


def _parse_exception(raw: dict) -> LtException:
    isin = str(raw.get("isin", "")).strip().upper()
    if not isin:
        raise LtRulesError("LT exception entry missing isin")

    never_lt = bool(raw.get("never_lt", False))
    lt_months_raw = raw.get("lt_months")
    lt_months = None

    if lt_months_raw is not None:
        try:
            lt_months = int(lt_months_raw)
        except (TypeError, ValueError) as exc:
            raise LtRulesError(f"Invalid lt_months for ISIN {isin}: {lt_months_raw!r}") from exc
        if lt_months < 1:
            raise LtRulesError(f"lt_months must be >= 1 for ISIN {isin}, got: {lt_months}")

    if never_lt and lt_months is not None:
        raise LtRulesError(
            f"ISIN {isin}: set either never_lt or lt_months, not both"
        )

    if not never_lt and lt_months is None:
        raise LtRulesError(
            f"ISIN {isin}: must set never_lt=true or a positive lt_months"
        )

    note = raw.get("note")
    return LtException(
        isin=isin,
        lt_months=lt_months,
        never_lt=never_lt,
        note=str(note).strip() if note else None,
    )


def load_lt_rules(path: Path | None = None) -> LtRules:
    config_path = path or DEFAULT_LT_EXCEPTIONS_PATH
    if not config_path.is_file():
        return LtRules(default_lt_months=12, exceptions={})

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LtRulesError(f"Invalid JSON in {config_path}: {exc}") from exc

    default_lt_months_raw = payload.get("default_lt_months", 12)
    try:
        default_lt_months = int(default_lt_months_raw)
    except (TypeError, ValueError) as exc:
        raise LtRulesError(
            f"default_lt_months must be an integer, got: {default_lt_months_raw!r}"
        ) from exc
    if default_lt_months < 1:
        raise LtRulesError(f"default_lt_months must be >= 1, got: {default_lt_months}")

    exceptions: dict[str, LtException] = {}
    for index, raw in enumerate(payload.get("exceptions", []), start=1):
        if not isinstance(raw, dict):
            raise LtRulesError(f"exceptions[{index}] must be an object")
        rule = _parse_exception(raw)
        if rule.isin in exceptions:
            raise LtRulesError(f"Duplicate ISIN in LT exceptions: {rule.isin}")
        exceptions[rule.isin] = rule

    return LtRules(default_lt_months=default_lt_months, exceptions=exceptions)
