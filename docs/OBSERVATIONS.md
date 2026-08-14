# Holdings Tracker — Live Data Observations

Observations from real Dhan Trade History data stored in PostgreSQL (`dhan_trades.raw_payload`).

---

## 1. IPO allotment rows — `orderId` / `securityId` / price are zero

**Date observed:** 2026-08-11  
**ISIN:** `INE549H01021` (Anand Rathi Share & Stock Brokers)

Three rows for the same stock — two normal trades and one IPO credit row.

### Normal SELL (2025-10-17)

```json
{
  "orderId": "31125101737034",
  "securityId": "759956",
  "exchangeTradeId": "0",
  "transactionType": "SELL",
  "tradedQuantity": 69,
  "tradedPrice": 511.7819,
  "exchangeTime": "2025-10-17T13:09:45",
  "customSymbol": "Anand Rathi Share & Stock Brokers"
}
```

### Normal BUY (2025-10-01)

```json
{
  "orderId": "3125100114954",
  "securityId": "759956",
  "exchangeTradeId": "0",
  "transactionType": "BUY",
  "tradedQuantity": 33,
  "tradedPrice": 459,
  "exchangeTime": "2025-10-01T10:15:47",
  "customSymbol": "Anand Rathi Share & Stock Brokers"
}
```

### IPO allotment BUY (2025-09-29) — anomalous row

```json
{
  "orderId": "0",
  "securityId": "0",
  "exchangeOrderId": "0",
  "exchangeTradeId": "0",
  "transactionType": "BUY",
  "tradedQuantity": 36,
  "tradedPrice": 0,
  "exchangeTime": "2025-09-29T00:00:00",
  "customSymbol": "Anand Rathi Shar",
  "isin": "INE549H01021",
  "sebiTax": 0,
  "stt": 0,
  "brokerageCharges": 0,
  "stampDuty": 0
}
```

### Interpretation

| Field | Normal trade | IPO row |
|-------|--------------|---------|
| `orderId` | Real Dhan order ID | `"0"` |
| `securityId` | e.g. `"759956"` | `"0"` |
| `exchangeOrderId` | Real exchange ID | `"0"` |
| `tradedPrice` | Actual price | `0` |
| `exchangeTime` | Exact execution time | Midnight `00:00:00` (allotment date) |
| `customSymbol` | Full name | Truncated |
| Charges | Non-zero on trades | All zero |

**Conclusion:** Shares credited via **IPO allotment** appear as BUY rows in Trade History with placeholder zeros. This reflects how Dhan returns IPO credits, not an ingest bug.

**Reliable fields on IPO rows:** `isin`, `tradedQuantity`, `transactionType`, `exchangeTime`.

---

## Impact on dedup key (Phase 2 fix)

Original unique key (without `isin`):

```
(order_id, exchange_time, transaction_type, traded_quantity, traded_price, security_id)
```

For IPO rows, `order_id` and `security_id` are both `"0"`. Two different IPO allotments on the same date with the same quantity and price `0` would **incorrectly deduplicate** as one row.

**Fix applied:** `isin` added to the composite unique key (migration `002_add_isin_to_dedup_key.sql`).

---

## Impact on FIFO / lot engine (Phase 3)

- Treat IPO row as a **BUY lot**: qty from `tradedQuantity`, purchase date from `exchangeTime`.
- **`tradedPrice: 0` is not a real cost basis** — IPO price may be absent from Trade History. Flag lot as cost-unknown or allow manual override.
- Reconcile and group lots by **`isin`**, not `security_id` (IPO rows have `securityId: "0"`).

---

## 2. T+1 settlement — holdings lag behind trade history after SELL

**Date observed:** 2026-08-11 / 2026-08-12  
**ISIN:** `INE0OWZ01020` (MVELECTRO, `securityId` `764397`)

### Holdings snapshot (11 Aug night — after same-day SELL ~2:30 PM)

```json
{
  "isin": "INE0OWZ01020",
  "securityId": "764397",
  "tradingSymbol": "MVELECTRO",
  "totalQty": 32,
  "dpQty": 0,
  "t1Qty": 0,
  "availableQty": 0,
  "avgCostPrice": 641.6,
  "lastTradedPrice": 599.45
}
```

### Timeline observed

| When | Event |
|------|--------|
| 11 Aug ~2:30 PM | SELL order placed (T+1 market) |
| 11 Aug night | DB backfill — holdings still show `totalQty: 32` |
| 12 Aug ~12 PM | SELL appears in Trade History API |
| By 13 Aug ~12 PM (worst case) | Holdings may finally drop qty (3 working days) |

### Interpretation

- **Trade History** and **Holdings** update on different schedules under T+1 settlement.
- After a SELL, trade history can show the SELL while holdings still list the stock (or show inconsistent qty fields).
- In this snapshot: `totalQty` is 32 but `dpQty`, `t1Qty`, and `availableQty` are all 0 — do **not** reconcile against `totalQty` during settlement windows.

### Reconciliation qty field (Phase 3)

**Do not use `total_qty`** — it can include qty still settling or not yet removed after a SELL.

| Field | Dhan docs meaning | Reconciliation use |
|-------|-------------------|-------------------|
| `dpQty` | Delivered (demat) qty | Candidate — settled shares only |
| `t1Qty` | T+1 qty (bought yesterday, settling today) | Not for reconciliation total |
| `availableQty` | Total qty minus pledged | **Working hypothesis for Phase 3** — tradable/settled view |

**Pending Dhan confirmation:** which field should reconciliation compare against FIFO open qty? See [`DHAN_API_QUESTIONS.md`](DHAN_API_QUESTIONS.md) §7.

Until Dhan responds, Phase 3 will compare FIFO open qty vs `holdings_current.available_qty` (not `total_qty`).

### Phase 2 handling

Phase 2 stores **all** qty fields as returned — no T+1 logic at ingest time. Both `dp_qty`, `t1_qty`, and `available_qty` are in `holdings_current`.

---

## 3. BSE_EQ trades excluded from NSE-only FIFO filter

**Date observed:** 2026-08-12  
**ISIN:** `INF109KC1Y56` (ICICI Pru Silver ETF)

Reconciliation showed FIFO open qty **51** vs holdings **52** (diff −1).

### Root cause

One CNC **BSE_EQ** BUY was in `dhan_trades` but Phase 3 FIFO initially filtered only `exchange_segment = 'NSE_EQ'`:

| Trade | Segment | Qty |
|-------|---------|-----|
| 2025-09-25 BUY | BSE_EQ | 1 |
| All other trades | NSE_EQ | net 51 open after FIFO |

Holdings API reports **total demat qty across exchanges** by ISIN, so the BSE share counted toward 52 while FIFO ignored it.

### Fix

FIFO input filter now includes **`BSE_EQ`** alongside **`NSE_EQ`** for CNC delivery trades. Lots are still grouped by **ISIN**, so NSE and BSE fills for the same stock share one FIFO queue.

---

## 4. Trade ingest policy — upsert + stale duplicate detection

**Date documented:** 2026-08-12

### Row identity (unchanged)

Dedup / unique key on `dhan_trades`:

```
(order_id, exchange_time, transaction_type, traded_quantity, traded_price, security_id, isin)
```

Partial fills (same `order_id`, different qty/time/price) remain **separate rows**. Iceberg orders are **not** flagged.

### Tier 1 — metadata upsert on re-fetch

`ON CONFLICT` on the key above **`DO UPDATE`** mutable fields (`raw_payload`, charges, symbol, etc.) when `raw_payload` changed.

Key fields (qty, price, time) are **not** updated — they define identity.

Ingest counts: `inserted` | `updated` | `unchanged`.

### Tier 2 — stale duplicate warnings (not auto-fix)

After each backfill, compare latest API trades vs DB **per group** `(order_id, isin, transaction_type)` using the **same 7-key** as ingest:

```
(order_id, exchange_time, transaction_type, traded_quantity, traded_price, security_id, isin)
```

**Warn** when DB has **more 7-key rows** than the latest API for that group (possible Dhan correction leaving a stale row). IPO rows use the same rule (`order_id` may be `"0"`).

**Do not warn** when API and DB have the same 7-key set (partial fills / iceberg).

Output: `output/ingest_warnings_latest.json`. Exit code 1 if warnings. NTFY if `NTFY_TOPIC` set.

**Fix:** manually delete stale `dhan_trades` row(s) listed in `db_trade_ids`, then re-run FIFO.

### Daily rollup (reporting only)

SQL view `daily_trade_rollup`: per ISIN, per day, sum of BUY/SELL qty. Not used by FIFO or reconciliation.

---

## 6. Trade History day-atomicity (incremental daily sync)

**Date observed:** 2026-08-12  
**Context:** Phase 4 daily sync cursor

For a given **calendar day** (IST), Dhan Trade History appears to return **either all trades for that day or none** — not a partial day that grows on a later fetch.

**Incremental cursor:**

```
trade_from = MAX(exchange_time)::date in IST + 1 day
trade_to   = today in IST
```

If any row exists for day **D**, day **D** is treated as closed; the next fetch starts at **D + 1**.

**Holiday lag example:** Trade placed Friday, not in API until Monday. DB max stays Thursday through Sat/Sun runs (empty fetches for Fri–Sun). Monday fetch returns Friday's trades (`exchange_time` still Friday).

**Dedup safety net:** 7-field unique key + `ON CONFLICT DO UPDATE` makes accidental re-fetch idempotent.

---

## 7. Holdings snapshot sync — sold-out positions

**Date observed:** 2026-08-12  
**Context:** Phase 4 `sync_holdings_snapshot()`

Dhan `/holdings` omits fully sold securities. Snapshot sync upserts the API response then **deletes** `holdings_current` rows whose `security_id` is absent. An empty API response (HTTP 200) clears the table — e.g. all positions sold. API/HTTP failures must fail before sync (no silent wipe on error).

---

## 8. Timestamp columns — TIMESTAMPTZ everywhere (leave as-is)

**Date documented:** 2026-08-12  
**Decision:** No schema migration to `TIMESTAMP WITHOUT TIME ZONE`. Document semantics instead.

### Column types in use

| Kind | Columns | Type | Meaning |
|------|---------|------|---------|
| Audit | `created_at`, `updated_at`, `started_at`, `finished_at`, `applied_at` | `TIMESTAMPTZ` | When the row was written/updated (Postgres `now()` — a real instant) |
| Business | `exchange_time`, `purchase_date` | `TIMESTAMPTZ` | Event time from Dhan / derived from trade (IST wall clock in practice) |
| Calendar | `lt_conversion_date`, `trade_from`, `trade_to` | `DATE` | Calendar date only — no timezone |

All tables use the same audit pattern (`DEFAULT now()` + `set_updated_at()` trigger).

### Why Neon shows UTC

`TIMESTAMPTZ` is stored as an absolute instant; many clients (including Neon console) **display in UTC**. That is normal — not a sign that audit times are “wrong.”

### Business times vs audit times

- **Audit** (`created_at`, etc.): system-defined at insert/update. UTC internally is fine; means “when did we persist this row.”
- **Business** (`exchange_time`): from Dhan API, typically strings like `2025-10-17T13:09:45` with **no timezone** — interpret as **IST** (NSE/BSE local time). Ingest strips tz if present (`src/trade_ingest.py` → `parse_exchange_time`).

Do not treat `exchange_time` and `created_at` as the same kind of timestamp.

### Calendar-day logic uses IST explicitly

Daily sync cursor and trade-day grouping must not rely on UTC display:

```sql
MAX((exchange_time AT TIME ZONE 'Asia/Kolkata')::date)
```

See §6. The `daily_trade_rollup` view uses `exchange_time::date` without IST conversion — reporting only; do not use it for sync cursor logic.

### Future work (out of scope for now)

If business timestamps ever need stricter typing, migrate **`exchange_time` / `purchase_date` only** to `TIMESTAMP WITHOUT TIME ZONE` documented as IST — not audit columns. GitHub Actions (Phase 5) runs in UTC; audit columns should stay `TIMESTAMPTZ`.

---

## 9. Incremental FIFO lot engine

**Date documented:** 2026-08-12  
**Context:** Daily `run_fifo.py` after Phase 4 daily sync

### Previous behaviour

Full rebuild every run: `TRUNCATE lots, lot_allocations` → reprocess **all** CNC NSE/BSE trades from scratch.

### Current behaviour

**Incremental (default):** process only FIFO-eligible trades **not** in `fifo_processed_trades`, in `(exchange_time, id)` order. Open lots loaded from DB per ISIN (FIFO queue). BUY → INSERT lot; SELL → UPDATE lots + INSERT allocations.

**No-op:** zero unprocessed trades → skip lot writes, reconcile only.

**Full rebuild** when:

| Trigger | Action |
|---------|--------|
| First bootstrap (`lots` empty, unprocessed trades exist) | Full rebuild |
| `fifo_processed_trades` empty but `lots` non-empty (post-migration) | Full rebuild |
| `lt_rules_hash` ≠ stored hash (`config/lt_exceptions.json` changed) | Full rebuild |
| Reconciliation fails after incremental | Auto full rebuild **once**, reconcile again |
| Still failing after rebuild | Fail loudly + NTFY |
| Manual | `python scripts/run_fifo.py --full` |

**Stale trade fix:** deleting a `dhan_trades` row CASCADE-removes its `fifo_processed_trades` marker → next run detects state mismatch → full rebuild.

### Why not `WHERE id > cursor`

Late-arriving trades (holiday lag) have a **high `id`** but **earlier `exchange_time`**. Unprocessed set + chronological sort handles this; see §6.

### Reconciliation

Unchanged — cheap `SUM(remaining_quantity)` vs `SUM(available_qty)` by ISIN after incremental or full FIFO.

---

## Related

- [`DHAN_API_QUESTIONS.md`](DHAN_API_QUESTIONS.md) — `exchangeTradeId` always `"0"`, null placeholders
- [`PHASE_3_PLAN.md`](PHASE_3_PLAN.md) — FIFO engine handling IPO lots

---

## Changelog

| Date | Observation |
|------|-------------|
| 2026-08-11 | IPO allotment BUY rows: `orderId`/`securityId`/`price` zero; ISIN + qty present |
| 2026-08-12 | Added `isin` to dedup key after IPO collision risk identified |
| 2026-08-12 | T+1 SELL lag: trade history vs holdings; reconcile via `availableQty` (pending Dhan confirm) |
| 2026-08-12 | BSE_EQ CNC trade missed by NSE-only FIFO filter; include BSE_EQ (INF109KC1Y56) |
| 2026-08-12 | Trade ingest: metadata upsert (Tier 1) + stale duplicate warnings (Tier 2) |
| 2026-08-12 | Phase 4: day-atomic trade cursor; holdings snapshot delete for sold-out |
| 2026-08-12 | Timestamp convention: TIMESTAMPTZ as-is; business times IST, audit times instant (§8) |
| 2026-08-12 | Incremental FIFO via fifo_processed_trades; full rebuild fallback (§9) |
