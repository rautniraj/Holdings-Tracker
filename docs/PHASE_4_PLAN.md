# Phase 4 — Daily Sync (Trade Ingest + Holdings Snapshot)

**Status:** Complete (12-Aug-2026)  
**Prerequisite:** Phase 3 complete ([`PHASE_3_PLAN.md`](PHASE_3_PLAN.md))

Reference: [`.cursor/rules/holdings-tracker-plan.mdc`](../.cursor/rules/holdings-tracker-plan.mdc)  
Observations: [`OBSERVATIONS.md`](OBSERVATIONS.md)

---

## Goal

A script you run daily that:

1. **Incrementally ingests trades** — fetch from `MAX(exchange_time)+1` through today (no fixed lookback window).
2. **Refreshes holdings snapshot** — upsert current holdings and remove rows for fully sold positions.

**Out of scope (this phase):** FIFO rebuild, reconciliation, GitHub Actions cron (Phase 5), NTFY ops hardening (Phase 6).

---

## Updated phase roadmap

| Phase | Scope | Status |
|-------|--------|--------|
| 1 | Dhan API & authentication | Complete |
| 2 | Neon PostgreSQL + backfill ingestion | Complete |
| 3 | FIFO lot engine + reconciliation | Complete |
| **4** | **Daily sync — incremental trades + holdings snapshot** | **Complete** |
| 5 | GitHub Actions daily cron | Not started |
| 6 | NTFY & operations hardening | Not started |

---

## Trade ingest: incremental cursor

### Algorithm

```
trade_from = MAX(exchange_time)::date in IST + 1 day
trade_to   = today in IST
```

If `trade_from > trade_to`, skip trade fetch. Holdings sync always runs.

### Canonical example: Friday trade, holiday weekend, appears Monday

| Run day | max `exchange_time` in DB | Fetch range | API result | max after run |
|---------|---------------------------|-------------|------------|---------------|
| Friday | Thursday | Fri → Fri | empty | Thursday |
| Saturday | Thursday | Fri → Sat | empty | Thursday |
| Sunday | Thursday | Fri → Sun | empty | Thursday |
| Monday | Thursday | Fri → Mon | Friday's trades | Friday |
| Tuesday | Friday | Sat → Tue | Sat/Sun empty; Tue empty or full | Fri or Tue |

No fixed overlap window — cursor waits until Dhan publishes the next closed day.

### Dhan day-atomicity assumption

For a calendar day **D**, Trade History returns **either all trades for D or none**. If any row exists for D, day D is closed; next fetch starts at D+1.

Document in [`OBSERVATIONS.md`](OBSERVATIONS.md). Existing dedup key remains safety net.

**Timezone:** IST (`Asia/Kolkata`) for calendar-day boundaries.

### Two-step lifecycle

| Step | Script | Range |
|------|--------|-------|
| **Once (setup)** | [`backfill_trades.py`](../scripts/backfill_trades.py) | `DHAN_TRADE_FROM` → today |
| **Daily** | [`daily_sync.py`](../scripts/daily_sync.py) | `MAX(exchange_time)+1` → today |

Empty DB → daily sync fails with message to run backfill first.

---

## Holdings sync: sold-out positions

[`sync_holdings_snapshot()`](../src/holdings_sync.py) upserts the API response and deletes rows whose `security_id` is absent (including sell-all when API returns `[]`).

---

## Daily script flow

New [`scripts/daily_sync.py`](../scripts/daily_sync.py):

```
1. Auth (TOTP)
2. Resolve trade_from / trade_to (incremental cursor)
3. Create sync_runs row
4. If trade_from <= trade_to: fetch + ingest trades
5. Snapshot-sync holdings (always)
6. Stale trade duplicate check (if trades fetched)
7. Finalize sync_run; NTFY on failure / warnings
```

---

## Files to deliver

| File | Purpose |
|------|---------|
| `src/sync_range.py` (or extend `trade_ingest.py`) | `resolve_trade_sync_range(conn)` |
| `src/holdings_sync.py` | Snapshot sync: upsert + delete missing |
| `scripts/daily_sync.py` | Daily orchestrator |
| `scripts/backfill_trades.py` | Use snapshot holdings sync |
| `sample.env` | Document `DHAN_TRADE_FROM` for initial backfill |
| `docs/OBSERVATIONS.md` | Day-atomicity + sold-position delete |

---

## Success criteria

- [x] `daily_sync.py` runs after backfill without date env vars
- [x] Incremental range derived from DB cursor only
- [x] Holiday lag handled (Friday trade appearing Monday)
- [x] Fully sold security removed from `holdings_current`
- [x] Empty DB fails with backfill hint
- [x] Empty holdings API clears table (sell-all); HTTP errors fail before sync

---

## Next — Phase 5

GitHub Actions daily cron to run `daily_sync.py` (and optionally FIFO/reconcile — TBD). Credentials in GitHub Secrets; `DHAN_REUSE_ACCESS_TOKEN=false` in production.
