# Phase 3 — FIFO Lot Engine & Reconciliation

**Status:** Complete (12-Aug-2026)  
**Prerequisite:** Phase 2 complete (Neon PostgreSQL, `dhan_trades`, `holdings_current`)

Reference: [`.cursor/rules/holdings-tracker-plan.mdc`](../.cursor/rules/holdings-tracker-plan.mdc)  
Prerequisites: [Phase 1](PHASE_1_PLAN.md) · [Phase 2](PHASE_2_PLAN.md)  
Observations: [`OBSERVATIONS.md`](OBSERVATIONS.md)

---

## Goal

Reconstruct **open lots** from `dhan_trades` using FIFO, calculate **long-term conversion date** per lot (>12 months from purchase), and **reconcile** against `holdings_current`.

---

## Input data

| Source | Table | Role |
|--------|-------|------|
| Trade History (stored) | `dhan_trades` | Event stream — BUY creates lots, SELL consumes lots |
| Holdings (stored) | `holdings_current` | Reconciliation snapshot |

### Trade filters (FIFO input)

Only process rows where:

- `product_type = 'CNC'`
- `exchange_segment IN ('NSE_EQ', 'BSE_EQ')`
- `transaction_type IN ('BUY', 'SELL')`

Sort by `exchange_time` ascending, then by `id` for stable ordering.

### Known edge cases (from live data)

See [`OBSERVATIONS.md`](OBSERVATIONS.md):

1. **IPO allotment** — `orderId`/`securityId`/`price` = 0; use `isin` + `tradedQuantity`; cost basis may be 0 / unknown
2. **`exchangeTradeId` always `"0"`** — dedup uses composite key including `isin`
3. **Partial fills / iceberg** — same `orderId`, multiple rows possible
4. **T+1 settlement lag** — after SELL, trade history and holdings update on different schedules; do not use `total_qty` for reconciliation (see [`OBSERVATIONS.md`](OBSERVATIONS.md) §2)
5. **BSE_EQ trades** — must be included in FIFO (holdings are per ISIN across exchanges)

---

## Output schema (new tables)

### `lots`

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL PK | |
| `isin` | TEXT NOT NULL | Primary grouping key |
| `security_id` | TEXT | From trade; may be `"0"` for IPO |
| `custom_symbol` | TEXT | Display |
| `purchase_date` | TIMESTAMPTZ | From BUY `exchange_time` |
| `lt_conversion_date` | DATE | purchase_date + 12 calendar months + 1 day |
| `original_quantity` | INTEGER | Qty at lot creation |
| `remaining_quantity` | INTEGER | Qty still open |
| `cost_per_share` | NUMERIC | From `traded_price`; 0 for IPO → flag |
| `cost_basis_unknown` | BOOLEAN | True when IPO / price = 0 |
| `source_trade_id` | BIGINT FK | → `dhan_trades.id` |
| `status` | TEXT | `open` / `closed` |
| `created_at`, `updated_at` | TIMESTAMPTZ | Rails-style triggers |

### `lot_allocations`

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL PK | |
| `sell_trade_id` | BIGINT FK | → `dhan_trades.id` |
| `lot_id` | BIGINT FK | → `lots.id` |
| `quantity` | INTEGER | Qty consumed from lot |
| `created_at`, `updated_at` | TIMESTAMPTZ | |

---

## FIFO algorithm

```
open_lots = {}  # isin → queue of lots (oldest first)

for trade in sorted_trades:
  if BUY:
    create lot (remaining_qty = traded_quantity)
    push to open_lots[isin]
  if SELL:
    qty_to_fill = traded_quantity
    while qty_to_fill > 0:
      lot = open_lots[isin].peek_oldest_with_remaining()
      if no lot: FAIL LOUDLY (oversell)
      consume = min(lot.remaining, qty_to_fill)
      record lot_allocation
      lot.remaining -= consume
      qty_to_fill -= consume
      if lot.remaining == 0: mark closed
```

**LT conversion date:** lot becomes long-term the day after 12 **calendar** months from `purchase_date` (not 365 days). Per-ISIN overrides in `config/lt_exceptions.json`.

**IPO lots:** create lot with `cost_basis_unknown = true` when `traded_price = 0` and `order_id = '0'`.

**Rebuild strategy:** full truncate-and-rebuild of `lots` + `lot_allocations` on each FIFO run.

---

## Reconciliation

After FIFO, per ISIN:

```
fifo_open_qty = SUM(lots.remaining_quantity WHERE status = 'open')
holdings_qty  = holdings_current.available_qty   # working hypothesis — match by isin
```

**Do not use `total_qty`** — can be stale after a SELL while settlement is in progress (see [`OBSERVATIONS.md`](OBSERVATIONS.md) §2).

**Pending Dhan confirmation:** `available_qty` vs `dp_qty` vs `total_qty`. Questions in [`DHAN_API_QUESTIONS.md`](DHAN_API_QUESTIONS.md) §7.

| Result | Action |
|--------|--------|
| Match | Success — write `output/reconciliation_latest.json` |
| Mismatch | Fail loudly — print all ISINs; NTFY if configured |

---

## Trade ingest hardening (added during Phase 3)

See [`OBSERVATIONS.md`](OBSERVATIONS.md) §4:

- **Tier 1:** `ON CONFLICT DO UPDATE` for metadata (`raw_payload`, charges, symbol) on same 7-key
- **Tier 2:** stale duplicate detection after backfill → `output/ingest_warnings_latest.json`
- **View:** `daily_trade_rollup` — per ISIN/day BUY/SELL totals (reporting only)

---

## CSV validation (optional — skipped)

Deferred by choice. `dhan_trades` remains authoritative.

---

## Files added

| File | Purpose |
|------|---------|
| `migrations/003_lots_schema.sql` | `lots`, `lot_allocations` tables |
| `migrations/004_daily_trade_rollup_view.sql` | Reporting view |
| `src/fifo_engine.py` | Core FIFO logic |
| `src/reconciliation.py` | Compare FIFO vs `holdings_current` |
| `src/lt_rules.py` | LT conversion + `config/lt_exceptions.json` |
| `src/ingest_warnings.py` | Tier 2 stale duplicate detection |
| `src/ntfy.py` | Push notifications (wired; full ops in Phase 6) |
| `config/lt_exceptions.json` | Per-ISIN LT month overrides |
| `scripts/run_fifo.py` | Build lots + reconciliation CLI |

---

## How to run

```bash
./run_holdings_tracker.sh
# or: backfill_trades.py → run_fifo.py
```

---

## Live results (12-Aug-2026)

| Metric | Value |
|--------|-------|
| CNC trades processed (NSE_EQ + BSE_EQ) | 194 |
| Lots created | 167 (118 open, 49 closed) |
| Allocations | 51 |
| Reconciliation | **25/25 ISINs matched** |
| Ingest warnings | 0 |

---

## Out of scope (V1)

- Corporate actions (bonus, split, merger)
- Cost basis override UI
- CSV validation
- Daily sync script (Phase 4)
- GitHub Actions cron (Phase 5)
- Full NTFY ops hardening (Phase 6)

---

## Success criteria

- [x] All CNC NSE_EQ + BSE_EQ trades processed in chronological order
- [x] Open lot qty per ISIN matches `holdings_current.available_qty` (25/25 on 12-Aug-2026; qty field pending Dhan confirm)
- [x] Each open lot has `lt_conversion_date`
- [x] IPO lots flagged with `cost_basis_unknown`
- [x] Oversell or negative remaining qty fails loudly
- [x] CSV validation — skipped (not required)

---

## Next — Phase 4

Daily sync: incremental trade ingest (`MAX(exchange_time)+1` → today) + holdings snapshot sync. See [`PHASE_4_PLAN.md`](PHASE_4_PLAN.md).
