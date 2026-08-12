# Phase 3 — FIFO Lot Engine & Reconciliation

**Status:** Not started  
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
- `exchange_segment = 'NSE_EQ'`
- `transaction_type IN ('BUY', 'SELL')`

Sort by `exchange_time` ascending, then by `id` for stable ordering.

### Known edge cases (from live data)

See [`OBSERVATIONS.md`](OBSERVATIONS.md):

1. **IPO allotment** — `orderId`/`securityId`/`price` = 0; use `isin` + `tradedQuantity`; cost basis may be 0 / unknown
2. **`exchangeTradeId` always `"0"`** — dedup uses composite key including `isin`
3. **Partial fills** — same `orderId`, multiple rows possible
4. **T+1 settlement lag** — after SELL, trade history updates before holdings; do not use `total_qty` for reconciliation (see [`OBSERVATIONS.md`](OBSERVATIONS.md) §2)

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
| `lt_conversion_date` | DATE | purchase_date + 12 months + 1 day (calendar) |
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

**LT conversion date:** lot becomes long-term the day after 12 calendar months from `purchase_date` (not 365 days).

**IPO lots:** create lot with `cost_basis_unknown = true` when `traded_price = 0` and `order_id = '0'`.

---

## Reconciliation

After FIFO, per ISIN:

```
fifo_open_qty = SUM(lots.remaining_quantity WHERE status = 'open')
holdings_qty  = holdings_current.available_qty   # working hypothesis — match by isin
```

**Do not use `total_qty`** — can be stale after a SELL while settlement is in progress (see [`OBSERVATIONS.md`](OBSERVATIONS.md) §2).

**Pending Dhan confirmation:** `available_qty` vs `dp_qty` vs `total_qty`. Questions in [`DHAN_API_QUESTIONS.md`](DHAN_API_QUESTIONS.md) §7. Update reconciliation code once Dhan responds.

| Result | Action |
|--------|--------|
| Match | Success |
| Mismatch | Fail loudly — print ISIN, FIFO qty, Dhan qty, diff |

Use **ISIN** as reconciliation key (not `security_id` — IPO rows have `securityId: "0"`).

**Timing:** run holdings sync after trades are up to date; allow for T+1 lag when interpreting mismatches on recent SELLs.

---

## CSV validation (optional)

Compare FIFO output against user's transaction CSV:

- Match by ISIN + date + qty + side
- Report discrepancies
- CSV is validation only; `dhan_trades` remains authoritative

---

## Files to add

| File | Purpose |
|------|---------|
| `migrations/003_lots_schema.sql` | `lots`, `lot_allocations` tables |
| `src/fifo_engine.py` | Core FIFO logic |
| `src/reconciliation.py` | Compare FIFO vs `holdings_current` |
| `scripts/run_fifo.py` | Build lots from `dhan_trades`, run reconciliation |

---

## Execution order

1. Migration `003_lots_schema.sql`
2. `fifo_engine.py` — read trades, write lots + allocations
3. `reconciliation.py` — compare vs holdings
4. `run_fifo.py` — CLI orchestrator
5. Validate against CSV (manual step)

---

## Out of scope (V1)

- Corporate actions (bonus, split, merger)
- Cost basis override UI
- NTFY alerts (Phase 5)
- GitHub Actions cron (Phase 4)

---

## Success criteria

- [ ] All CNC NSE_EQ trades processed in chronological order
- [ ] Open lot qty per ISIN matches `holdings_current.available_qty` (pending Dhan confirm on qty field)
- [ ] Each open lot has `lt_conversion_date`
- [ ] IPO lots flagged with `cost_basis_unknown`
- [ ] Oversell or negative remaining qty fails loudly
- [ ] CSV validation documented (pass/fail noted)
