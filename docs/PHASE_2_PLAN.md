# Phase 2 — Neon PostgreSQL & Data Ingestion

**Status:** Complete  
**Completed:** 11-Aug-2026

Reference: [`.cursor/rules/holdings-tracker-plan.mdc`](../.cursor/rules/holdings-tracker-plan.mdc)  
Observations: [`OBSERVATIONS.md`](OBSERVATIONS.md)  
Prerequisite: [Phase 1 complete](PHASE_1_PLAN.md)

---

## Goal

Persist Dhan Trade History and Holdings in **Neon PostgreSQL** as a permanent, queryable ledger before building the FIFO lot engine (Phase 3).

Dhan Trade History remains the recovery source if DB is lost; DB is an optimization for incremental sync.

---

## Execution sub-steps

| Step | Scope | Status |
|------|-------|--------|
| 2a | Neon connection + `test_db_connection.py` | Complete |
| 2b | Schema migrations (`001`, `002`) | Complete |
| 2c | Trade ingest (`trade_ingest.py`) | Complete |
| 2d | Holdings sync (`holdings_sync.py`) | Complete |
| 2e | Historical backfill (`backfill_trades.py`) | Complete |

---

## Postgres schema

### Tables

| Table | Source | Purpose |
|-------|--------|---------|
| `dhan_trades` | Trade History API | Permanent raw ledger — every BUY/SELL |
| `holdings_current` | Holdings API | Latest snapshot for reconciliation |
| `sync_runs` | Internal | Log each backfill/sync run |
| `schema_migrations` | Internal | Track applied SQL migrations |

All data tables include Rails-style `created_at` / `updated_at` with PostgreSQL triggers.

### Migrations

| File | Purpose |
|------|---------|
| `migrations/001_initial_schema.sql` | Tables + triggers |
| `migrations/002_add_isin_to_dedup_key.sql` | Add `isin` to dedup constraint (IPO fix) |

---

## Dedup key

`exchangeTradeId` is always `"0"` in live data. Trades deduplicated on:

```
(order_id, exchange_time, transaction_type, traded_quantity, traded_price, security_id, isin)
```

- `ON CONFLICT DO NOTHING` — re-runs are idempotent
- `isin` required — IPO rows have `order_id` and `security_id` as `"0"` (see [`OBSERVATIONS.md`](OBSERVATIONS.md))

---

## Fetch & ingest strategy

### Trade history

```
for each monthly chunk (2025-09-20 → today):
  sleep DHAN_TRADE_HISTORY_SLEEP_SECONDS (except first chunk)
  for page 0, 1, 2 … until []:
    GET /v2/trades/{from}/{to}/{page}
    sleep between pages
    ingest → dhan_trades
```

### Holdings

Single `GET /v2/holdings` → upsert `holdings_current` (no pagination).

All qty fields stored: `total_qty`, `dp_qty`, `t1_qty`, `available_qty`. Phase 3 reconciliation will use `available_qty` by ISIN (working hypothesis; pending Dhan — see [`OBSERVATIONS.md`](OBSERVATIONS.md) §2).

### Auth

Uses Phase 1 `get_access_token()` — token held in memory on `DhanClient` for entire run.

---

## Files delivered

| File | Purpose |
|------|---------|
| `src/db.py` | Postgres connection + migration runner |
| `src/trade_ingest.py` | Parse Dhan JSON → insert `dhan_trades` |
| `src/holdings_sync.py` | Upsert `holdings_current` |
| `scripts/test_db_connection.py` | Verify Neon connectivity |
| `scripts/run_migrations.py` | Apply pending migrations |
| `scripts/backfill_trades.py` | Auth → sync_run → fetch → ingest → holdings |

---

## Environment variables (Phase 2 additions)

```env
DATABASE_URL=postgresql://...           # Neon pooled connection string
DHAN_TRADE_HISTORY_SLEEP_SECONDS=1      # Pause between Trade History requests
DHAN_REUSE_ACCESS_TOKEN=true            # dev only
DHAN_TRADE_FROM=2025-09-20              # optional backfill start
DHAN_TRADE_TO=2026-08-11                # optional backfill end
```

---

## How to run

```bash
python scripts/test_db_connection.py
python scripts/run_migrations.py
python scripts/backfill_trades.py
```

Or full pipeline: `./run_holdings_tracker.sh`

### Verify in Neon

```sql
SELECT COUNT(*) FROM dhan_trades;
SELECT COUNT(*) FROM holdings_current;
SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1;
```

---

## Backfill results (11-Aug-2026)

| Metric | Value |
|--------|-------|
| Date range | 2025-09-20 → 2026-08-11 |
| Trades ingested | 192 |
| Holdings upserted | 25 |
| Monthly chunks | 12 |
| Idempotent re-run | 192 skipped, 0 inserted |

---

## Success criteria

- [x] Neon PostgreSQL connected from local machine
- [x] Schema applied via migration runner
- [x] All historical trades backfilled (Sep 2025 → today)
- [x] Holdings snapshot upserted
- [x] Dedup prevents duplicate inserts on re-run
- [x] `sync_runs` logs each execution
- [x] `isin` in dedup key for IPO edge case
- [x] Rate safety sleep between Trade History requests

---

## Out of scope (Phase 2)

- FIFO lot engine
- LT conversion dates
- Reconciliation (FIFO vs holdings)
- GitHub Actions daily cron
- NTFY alerts
- Corporate actions

**Next:** [`PHASE_3_PLAN.md`](PHASE_3_PLAN.md)
