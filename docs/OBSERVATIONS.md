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
