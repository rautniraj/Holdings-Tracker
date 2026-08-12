# Holdings Tracker

A personal portfolio service that tracks **when each stock lot will convert from short-term to long-term** (more than 12 months holding period), using the [DhanHQ API v2](https://docs.dhanhq.co/api/v2/).

Dhan shows ST/LT classification only after conversion. This project reconstructs open lots from trade history (FIFO) so you can decide **before** each lot crosses the 12-month threshold.

---

## Project status

| Phase | Scope | Status |
|-------|--------|--------|
| **Phase 1** | Dhan API & authentication validation | **Complete** |
| **Phase 2** | Neon PostgreSQL + trade/holdings ingestion | **Complete** |
| **Phase 3** | FIFO lot engine + reconciliation | **Complete** |
| **Phase 4** | Daily sync — incremental trades + holdings snapshot | Not started |
| Phase 5 | GitHub Actions daily cron | Not started |
| Phase 6 | NTFY notifications + ops hardening | Not started |

Planning docs: [`docs/PHASE_1_PLAN.md`](docs/PHASE_1_PLAN.md) · [`docs/PHASE_2_PLAN.md`](docs/PHASE_2_PLAN.md) · [`docs/PHASE_3_PLAN.md`](docs/PHASE_3_PLAN.md) · [`docs/PHASE_4_PLAN.md`](docs/PHASE_4_PLAN.md)  
Planning reference: `Dhan-Project---Serious-Problem-Troubleshooting-2026-08-11.html`  
API reference (local export): `dhan-api-docs.md`

---

## Phase 1 — Dhan API & authentication

Phase 1 proves we can **reliably talk to Dhan** before building business logic.

### Validated

1. TOTP-based authentication → access token
2. `GET /profile` (token sanity check)
3. `GET /holdings` (current portfolio snapshot)
4. `GET /trades/{from-date}/{to-date}/{page-number}` (paginated trade history)

### Key design decisions

**TOTP authentication** — fully automatable, no browser login, no static IP for read-only APIs.

**Token reuse (development)** — with `DHAN_REUSE_ACCESS_TOKEN=true`, a valid token in `output/auth_response.json` is reused across runs (checked via `expiryTime` + `GET /profile`). Set to `false` in production.

**Read-only APIs only** — Trade History is the authoritative event stream; Holdings is for reconciliation.

**Retry policy** — configurable linear retries, no exponential backoff (per approved plan).

**Trade history pagination** — start at page `0`, loop until empty array.

Run: `python scripts/phase1_validate.py` — saves raw API dumps under `output/`.

---

## Phase 2 — PostgreSQL & data ingestion

Phase 2 persists Dhan data in **Neon PostgreSQL** so we have a permanent, queryable ledger before building the FIFO engine.

### What was built

| Component | Purpose |
|-----------|---------|
| Neon connection | `DATABASE_URL` + `scripts/test_db_connection.py` |
| Schema migrations | `sync_runs`, `dhan_trades`, `holdings_current` |
| Trade ingest | Idempotent insert with composite dedup key |
| Holdings sync | Upsert current portfolio snapshot |
| Backfill | Fetch all trades from 2025-09-20 → today in monthly chunks |

### Postgres tables

| Table | Source | Purpose |
|-------|--------|---------|
| `dhan_trades` | Trade History API | Permanent raw ledger (every BUY/SELL) |
| `holdings_current` | Holdings API | Latest snapshot for reconciliation (`dp_qty`, `t1_qty`, `available_qty` stored) |
| `sync_runs` | Internal | Log each backfill/sync run |

All tables include Rails-style `created_at` / `updated_at` (auto-updated via PostgreSQL triggers).

### Dedup key

`exchangeTradeId` is always `"0"` in live data. Trades are deduplicated on:

`(order_id, exchange_time, transaction_type, traded_quantity, traded_price, security_id, isin)`

`isin` is required — IPO allotment rows have `order_id` and `security_id` as `"0"`; without `isin`, different IPO credits could collide. See [`docs/OBSERVATIONS.md`](docs/OBSERVATIONS.md).

Re-running backfill is safe — duplicates are skipped via `ON CONFLICT DO NOTHING`.

### Reconciliation qty field (Phase 3)

FIFO open qty will be compared against **`holdings_current.available_qty`** by ISIN (working hypothesis). **Not `total_qty`** — it can stay non-zero after a SELL while T+1 settlement completes. Pending confirmation from Dhan — see [`docs/OBSERVATIONS.md`](docs/OBSERVATIONS.md) §2 and [`docs/DHAN_API_QUESTIONS.md`](docs/DHAN_API_QUESTIONS.md) §7.

### Fetch strategy

- **Date range:** monthly chunks (defensive — Dhan docs don't specify max range per request)
- **Pagination:** page `0` until empty array within each chunk
- **Rate safety:** `DHAN_TRADE_HISTORY_SLEEP_SECONDS` pause between Trade History requests (pages and chunks)

### Backfill results (11-Aug-2026)

| Metric | Value |
|--------|-------|
| Date range | 2025-09-20 → 2026-08-11 |
| Trades ingested | 192 |
| Holdings upserted | 25 |
| Monthly chunks | 12 |

---

## Phase 3 — FIFO lot engine & reconciliation

Phase 3 reconstructs **open lots** from trade history (FIFO), calculates **long-term conversion date** per lot, and reconciles against holdings.

### What was built

| Component | Purpose |
|-----------|---------|
| `lots` + `lot_allocations` | FIFO output tables |
| `src/fifo_engine.py` | BUY → lot, SELL → consume oldest (by ISIN) |
| `src/reconciliation.py` | FIFO open qty vs `holdings_current.available_qty` |
| `src/lt_rules.py` | Indian LT calendar rule + `config/lt_exceptions.json` |
| `src/ingest_warnings.py` | Stale duplicate detection after backfill |
| `src/ntfy.py` | Push alerts on warnings / reconciliation failure |
| `scripts/run_fifo.py` | Rebuild lots + reconcile |
| `daily_trade_rollup` view | Per ISIN/day BUY/SELL totals (reporting only) |

### Key rules

- **FIFO filter:** CNC, `NSE_EQ` + `BSE_EQ`, BUY/SELL only
- **LT date:** day after 12 calendar months from purchase (not 365 days)
- **Reconciliation:** by ISIN vs `available_qty` (not `total_qty`)
- **Reports:** `output/reconciliation_latest.json`, `output/ingest_warnings_latest.json`

### Live results (12-Aug-2026)

| Metric | Value |
|--------|-------|
| Trades processed | 194 |
| Lots open / closed | 118 / 49 |
| Reconciliation | 25/25 matched |

Run: `./run_holdings_tracker.sh` (backfill + FIFO)

---

## Project structure

```
Holdings-Tracker/
├── README.md
├── docs/
│   ├── DHAN_API_QUESTIONS.md
│   ├── OBSERVATIONS.md              # Live data edge cases (IPO, etc.)
│   ├── PHASE_1_PLAN.md              # Dhan API validation (complete)
│   ├── PHASE_2_PLAN.md              # PostgreSQL + ingestion (complete)
│   └── PHASE_3_PLAN.md              # FIFO lot engine (complete)
├── config/
│   └── lt_exceptions.json           # Per-ISIN LT month overrides
├── migrations/
│   ├── 001_initial_schema.sql
│   ├── 002_add_isin_to_dedup_key.sql
│   ├── 003_lots_schema.sql
│   └── 004_daily_trade_rollup_view.sql
├── requirements.txt
├── sample.env
├── run_holdings_tracker.sh          # Full dev pipeline
├── dhan-api-docs.md
├── scripts/
│   ├── phase1_validate.py           # Phase 1 — API validation
│   ├── test_db_connection.py        # Verify Neon connectivity
│   ├── run_migrations.py            # Apply SQL migrations
│   ├── backfill_trades.py           # Fetch + ingest trades + holdings
│   └── run_fifo.py                  # Phase 3 — FIFO + reconciliation
├── src/
│   ├── auth.py                      # TOTP auth + token reuse
│   ├── config.py                    # Environment loading
│   ├── db.py                        # Postgres connection + migrations
│   ├── dhan_client.py               # Profile, holdings, trade history
│   ├── trade_ingest.py              # Upsert dhan_trades (7-key dedup)
│   ├── holdings_sync.py             # Upsert holdings_current
│   ├── fifo_engine.py               # FIFO lot builder
│   ├── reconciliation.py            # Holdings reconciliation
│   ├── lt_rules.py                  # LT conversion dates
│   ├── ingest_warnings.py           # Stale duplicate detection
│   ├── ntfy.py                      # Push notifications
│   └── retry.py                     # Configurable retry helper
└── output/                          # Reports + API dumps (gitignored)
```

---

## Prerequisites

- Python 3.11+ (3.10+ should work)
- A Dhan account with **TOTP enabled** for API access
- Credentials: Client ID, PIN, TOTP secret
- Neon PostgreSQL database (free tier works)

Setup TOTP on Dhan: web.dhan.co → My Profile → Access DhanHQ APIs → Setup TOTP.

---

## Setup

### 1. Clone and create virtual environment

```bash
cd Holdings-Tracker
python3 -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp sample.env .env
```

Edit `.env`:

```env
DHAN_CLIENT_ID=your_client_id
DHAN_PIN=your_pin
DHAN_TOTP_SECRET=your_totp_secret
DATABASE_URL=postgresql://...    # Neon pooled connection string

# Optional
DHAN_MAX_RETRIES=5
DHAN_AUTH_MAX_RETRIES=5
DHAN_TRADE_HISTORY_SLEEP_SECONDS=1
DHAN_REUSE_ACCESS_TOKEN=true     # dev only; false in production

# Optional — backfill date range (YYYY-MM-DD)
# DHAN_TRADE_FROM=2025-09-20
# DHAN_TRADE_TO=2026-08-11
```

**Never commit `.env`.** It is listed in `.gitignore`.

---

## How to run

### Full pipeline (development)

```bash
./run_holdings_tracker.sh
```

Or step by step:

```bash
# 1. Verify Dhan API (optional — saves JSON to output/)
python scripts/phase1_validate.py

# 2. Verify Neon connection
python scripts/test_db_connection.py

# 3. Apply schema migrations (safe to re-run)
python scripts/run_migrations.py

# 4. Backfill trades + sync holdings
python scripts/backfill_trades.py

# 5. FIFO lot engine + reconciliation
python scripts/run_fifo.py
```

### Verify data in Neon

```sql
SELECT COUNT(*) FROM dhan_trades;
SELECT COUNT(*) FROM holdings_current;
SELECT COUNT(*) FROM lots WHERE status = 'open';
SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1;
SELECT * FROM daily_trade_rollup ORDER BY trade_date DESC LIMIT 10;
```

---

## Module reference

### `src/auth.py`

- `get_access_token(settings)` — reuse cached token if valid, else generate new via TOTP
- `generate_access_token(settings)` — force new token from Dhan auth endpoint
- Cache file: `output/auth_response.json` (when `DHAN_REUSE_ACCESS_TOKEN=true`)

### `src/dhan_client.py`

- `DhanClient(access_token, settings)` — session with `access-token` header
- `get_profile()` → `GET /v2/profile`
- `get_holdings()` → `GET /v2/holdings`
- `get_trade_history(from_date, to_date)` → paginated `GET /v2/trades/…` with sleep between pages

### `src/db.py`

- `get_connection()` / `check_connection()` — Postgres connectivity
- `run_migrations()` — apply pending SQL from `migrations/`

### `src/trade_ingest.py`

- `ingest_trades(conn, trades, sync_run_id)` — parse Dhan JSON → insert into `dhan_trades`

### `src/holdings_sync.py`

- `sync_holdings(conn, holdings)` — upsert into `holdings_current`

### `scripts/backfill_trades.py`

Orchestrates: auth → sync_run → monthly trade fetch → ingest → holdings sync → stale duplicate check.

### `scripts/run_fifo.py`

Rebuilds `lots` + `lot_allocations` from `dhan_trades`, reconciles vs holdings, writes `output/reconciliation_latest.json`.

---

## Important API observations

Documented in [`docs/OBSERVATIONS.md`](docs/OBSERVATIONS.md) and [`docs/DHAN_API_QUESTIONS.md`](docs/DHAN_API_QUESTIONS.md):

1. **`exchangeTradeId` is always `"0"`** — composite dedup key includes `isin`
2. **IPO allotment** — `orderId`/`securityId`/`price` = 0; ISIN + qty reliable
3. **T+1 settlement lag** — after SELL, trade history updates before holdings; reconcile using `available_qty` (pending Dhan confirm), not `total_qty`
4. **`exchangeTime` format** — ISO in live data; parser handles both formats
5. **`orderId` can map to multiple fills** — composite key handles partial fills
6. **Token lifecycle** — fresh token each production run; dev reuse via `auth_response.json`

---

## Security notes

- `.env` and `output/` are gitignored
- `output/auth_response.json` contains a live JWT — treat as secret
- Store production credentials in **GitHub Secrets** (Phase 5), not in the repo
- Set `DHAN_REUSE_ACCESS_TOKEN=false` in production
- Rotate PIN/TOTP secret if credentials were ever exposed

---

## What's next — Phase 4

Daily sync script: incremental trade ingest from `MAX(exchange_time)+1` through today, plus holdings snapshot sync (including cleanup for fully sold positions). Prerequisite: one-time backfill via `DHAN_TRADE_FROM`.

Phase 5 will schedule this via GitHub Actions. Phase 6 adds NTFY ops hardening.

---

## References

- [DhanHQ API v2](https://docs.dhanhq.co/api/v2/)
- [DhanHQ docs (alternate)](https://dhanhq.co/docs/v2/)
- Local export: `dhan-api-docs.md`
- Open questions for Dhan: [`docs/DHAN_API_QUESTIONS.md`](docs/DHAN_API_QUESTIONS.md)
- Live data observations: [`docs/OBSERVATIONS.md`](docs/OBSERVATIONS.md)
