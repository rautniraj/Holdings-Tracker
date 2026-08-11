# Holdings Tracker

A personal portfolio service that tracks **when each stock lot will convert from short-term to long-term** (more than 12 months holding period), using the [DhanHQ API v2](https://docs.dhanhq.co/api/v2/).

Dhan shows ST/LT classification only after conversion. This project reconstructs open lots from trade history (FIFO) so you can decide **before** each lot crosses the 12-month threshold.

---

## Project status

| Phase | Scope | Status |
|-------|--------|--------|
| **Phase 1** | Dhan API & authentication validation | **Complete** |
| Phase 2 | FIFO lot engine + CSV validation | Not started |
| Phase 3 | Neon PostgreSQL + GitHub Actions | Not started |
| Phase 4 | NTFY notifications + ops hardening | Not started |

Planning reference: `Dhan-Project---Serious-Problem-Troubleshooting-2026-08-11.html`  
API reference (local export): `dhan-api-docs.md`

---

## Phase 1 — what was built and why

Phase 1 proves we can **reliably talk to Dhan** before building business logic. No database, FIFO engine, notifications, or GitHub Actions yet.

### Goal

Validate end-to-end:

1. TOTP-based authentication → access token
2. `GET /profile` (token sanity check)
3. `GET /holdings` (current portfolio snapshot)
4. `GET /trades/{from-date}/{to-date}/{page-number}` (paginated trade history)

### Design decisions

#### 1. TOTP authentication (not manual 24h web token)

Dhan supports several auth methods. We chose **TOTP → `generateAccessToken`** because:

- Fully automatable (no browser login each day)
- Suitable for future GitHub Actions daily cron
- No static IP required for read-only APIs (Trade History, Holdings, Profile)

**How it works each run:**

```
DHAN_TOTP_SECRET (stored in .env)
        ↓
pyotp generates current 6-digit TOTP
        ↓
POST https://auth.dhan.co/app/generateAccessToken
        ↓
accessToken (~24h validity)
        ↓
used for this run only, then discarded
```

You do **not** open an authenticator app manually. The secret is stored once; the code is generated programmatically.

**Token reuse:** With `DHAN_REUSE_ACCESS_TOKEN=true` (development), a valid token in `output/auth_response.json` is reused across runs. Set to `false` in production — each run generates a fresh token with no disk cache.

#### 2. Read-only APIs only

This project never places, modifies, or cancels orders. Static IP whitelisting is **not** required for our endpoints.

| Endpoint | Role in project |
|----------|-----------------|
| `POST …/generateAccessToken` | Authentication |
| `GET /profile` | Verify token + account setup |
| `GET /holdings` | Reconciliation (Phase 2+) — compare our calculated qty vs Dhan |
| `GET /trades/…` | **Primary data source** — reconstruct lots from BUY/SELL history |

Trade History is the authoritative event stream. Holdings is secondary validation, not the historical ledger.

#### 3. Retry policy

Configurable via environment variables. Simple linear retries — **no exponential backoff, no rate-limit detection** (per approved plan).

| Variable | Default | Used for |
|----------|---------|----------|
| `DHAN_AUTH_MAX_RETRIES` | 10 | Token generation |
| `DHAN_MAX_RETRIES` | 10 | Profile, holdings, trade history |

If authentication fails after all retries, the entire run fails (we never call APIs with a bad token).

#### 4. Trade history pagination

Endpoint: `GET /v2/trades/{from-date}/{to-date}/{page-number}`  
Start at page `0`. Loop until an **empty array** is returned.

Default date range: last 30 days. Override with `DHAN_TRADE_FROM` / `DHAN_TRADE_TO`.

#### 5. Phase 1 output files

Raw API responses are saved under `output/` for inspection (gitignored — may contain account data):

| File | Contents |
|------|----------|
| `auth_response.json` | Token metadata + expiry; reused in dev when `DHAN_REUSE_ACCESS_TOKEN=true` |
| `profile.json` | Account profile |
| `holdings.json` | Current demat holdings |
| `trade_history.json` | All trades in the requested date range |

---

## Live validation results (Phase 1)

Tested successfully against a real Dhan account on **11-Aug-2026**:

| Step | Result |
|------|--------|
| TOTP auth | Success — token expiry ~24 hours |
| Profile | Success |
| Holdings | 25 securities |
| Trade history (30 days) | 19 trades, 1 page |

### Important observations (for Phase 2/3)

These are documented in detail in [`docs/DHAN_API_QUESTIONS.md`](docs/DHAN_API_QUESTIONS.md) for the Dhan API team.

1. **`exchangeTradeId` is always `"0"`** in live Trade History — cannot be used alone as a unique trade key. Phase 3 will use a **composite key** (e.g. `orderId` + `exchangeTime` + `tradedQuantity` + `tradedPrice` + `transactionType`).

2. **`exchangeTime` format** in live data is ISO (`2026-08-10T10:17:36`), not the space-separated format shown in some doc examples. Code will parse what the API actually returns.

3. **`orderId` is not safe as sole unique key** — Dhan docs state one order can produce multiple trade rows on partial fills. Composite key handles this.

4. **Token lifecycle** — each run gets a fresh token; we do not persist tokens between runs.

---

## Project structure

```
Holdings-Tracker/
├── README.md                          # This file
├── docs/
│   └── DHAN_API_QUESTIONS.md          # Questions for Dhan API team
├── requirements.txt                   # Python dependencies
├── sample.env                         # Environment variable template
├── dhan-api-docs.md                   # Local DhanHQ API v2 export
├── scripts/
│   └── phase1_validate.py             # Phase 1 validation script
├── src/
│   ├── auth.py                        # TOTP → access token
│   ├── config.py                      # Environment loading
│   ├── dhan_client.py                 # Profile, holdings, trade history
│   └── retry.py                       # Configurable retry helper
└── output/                            # Phase 1 API dumps (gitignored)
```

---

## Prerequisites

- Python 3.11+ (3.10+ should work)
- A Dhan account with **TOTP enabled** for API access
- Credentials: Client ID, PIN, TOTP secret

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

Copy the template and fill in your credentials:

```bash
cp sample.env .env
```

Edit `.env`:

```env
DHAN_CLIENT_ID=your_client_id
DHAN_PIN=your_pin
DHAN_TOTP_SECRET=your_totp_secret

# Optional
DHAN_MAX_RETRIES=10
DHAN_AUTH_MAX_RETRIES=10

# Optional — override trade history date range (YYYY-MM-DD)
# DHAN_TRADE_FROM=2025-01-01
# DHAN_TRADE_TO=2026-08-11
```

**Never commit `.env`.** It is listed in `.gitignore`.

---

## How to run (Phase 1)

From the project root with the virtual environment activated:

```bash
python scripts/phase1_validate.py
```

Expected flow:

```
============================================================
Phase 1 — Dhan API & Authentication
As of: 11-Aug-2026 13:05:10
============================================================

[1/4] Authenticating with TOTP...
[2/4] Fetching profile...
[3/4] Fetching holdings...
[4/4] Fetching trade history (paginated)...

============================================================
Phase 1 validation complete.
Raw responses saved under: output/
============================================================
```

Inspect results:

```bash
ls output/
# auth_response.json  holdings.json  profile.json  trade_history.json
```

---

## Module reference

### `src/config.py`

Loads and validates environment variables. Fails fast if required vars are missing.

### `src/auth.py`

- `generate_totp(secret)` — current 6-digit code via `pyotp`
- `generate_access_token(settings)` — POST to `auth.dhan.co/app/generateAccessToken` with retries

Uses query parameters per Dhan docs: `dhanClientId`, `pin`, `totp`.

### `src/dhan_client.py`

- `DhanClient(access_token, settings)` — session with `access-token` header
- `get_profile()` → `GET /v2/profile`
- `get_holdings()` → `GET /v2/holdings`
- `get_trade_history(from_date, to_date)` → paginated `GET /v2/trades/…`

### `src/retry.py`

Generic retry wrapper: attempt 1…N, log failures, hard fail on exhaustion. No backoff.

### `scripts/phase1_validate.py`

Orchestrates the four validation steps and writes JSON output.

---

## Security notes

- `.env` and `output/` are gitignored
- `output/auth_response.json` contains a live JWT — treat as secret; do not share or commit
- Store production credentials in **GitHub Secrets** (Phase 3), not in the repo
- Rotate PIN/TOTP secret if credentials were ever exposed

---

## What's next — Phase 2

Phase 2 builds the FIFO lot engine:

- Normalize trades from Dhan (or CSV for validation)
- BUY → create lot; SELL → consume lots (FIFO)
- Calculate long-term conversion date per lot (>12 months from purchase)
- Reconcile open quantities against Dhan Holdings
- Validate against your transaction CSV

Start a new chat titled **Phase 2 — FIFO & Lot Engine** when ready.

---

## References

- [DhanHQ API v2](https://docs.dhanhq.co/api/v2/)
- [DhanHQ docs (alternate)](https://dhanhq.co/docs/v2/)
- Local export: `dhan-api-docs.md`
- Open questions for Dhan: `docs/DHAN_API_QUESTIONS.md`
