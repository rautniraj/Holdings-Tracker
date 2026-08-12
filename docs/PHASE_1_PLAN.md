# Phase 1 — Dhan API & Authentication Validation

**Status:** Complete  
**Validated:** 11-Aug-2026

Reference: [`.cursor/rules/holdings-tracker-plan.mdc`](../.cursor/rules/holdings-tracker-plan.mdc)  
API questions: [`DHAN_API_QUESTIONS.md`](DHAN_API_QUESTIONS.md)

---

## Goal

Prove we can **reliably talk to Dhan** before building business logic. No database, FIFO engine, notifications, or GitHub Actions.

---

## Scope

Validate end-to-end:

1. TOTP-based authentication → access token
2. `GET /v2/profile` — token sanity check
3. `GET /v2/holdings` — current portfolio snapshot
4. `GET /v2/trades/{from-date}/{to-date}/{page-number}` — paginated trade history

---

## APIs used (read-only)

| Endpoint | Method | Role |
|----------|--------|------|
| `https://auth.dhan.co/app/generateAccessToken` | POST | TOTP → access token (~24h) |
| `/v2/profile` | GET | Verify token + account setup |
| `/v2/holdings` | GET | Current demat holdings (reconciliation later) |
| `/v2/trades/{from}/{to}/{page}` | GET | Primary data source — trade ledger |

No order placement, modification, or cancellation. Static IP whitelisting **not required** for these endpoints.

---

## Design decisions

### TOTP authentication

```
DHAN_TOTP_SECRET (.env)
        ↓
pyotp → 6-digit TOTP
        ↓
POST generateAccessToken
        ↓
accessToken (~24h)
        ↓
used for this run (in-memory on DhanClient session)
```

### Token reuse (development)

With `DHAN_REUSE_ACCESS_TOKEN=true`:

- Valid token loaded from `output/auth_response.json`
- Checked via `expiryTime` (5-min buffer) + `GET /profile`
- Avoids TOTP rate limits during dev

Set `DHAN_REUSE_ACCESS_TOKEN=false` in production.

### Retry policy

Configurable linear retries — no exponential backoff, no rate-limit detection.

| Variable | Default | Used for |
|----------|---------|----------|
| `DHAN_AUTH_MAX_RETRIES` | 5 | Token generation |
| `DHAN_MAX_RETRIES` | 5 | Profile, holdings, trade history |

Auth failure after all retries → entire run fails.

### Trade history pagination

- Start at page `0`
- Loop until response is empty array `[]`
- No assumed page size or `hasMore` flag

---

## Files delivered

| File | Purpose |
|------|---------|
| `src/auth.py` | TOTP auth, `get_access_token()`, token reuse |
| `src/config.py` | Environment loading |
| `src/dhan_client.py` | Profile, holdings, paginated trade history |
| `src/retry.py` | Configurable retry helper |
| `scripts/phase1_validate.py` | Orchestrates validation, saves JSON to `output/` |

---

## Output files (gitignored)

| File | Contents |
|------|----------|
| `output/auth_response.json` | Token metadata + expiry; dev reuse cache |
| `output/profile.json` | Account profile |
| `output/holdings.json` | Current demat holdings |
| `output/trade_history.json` | Trades in requested date range |

---

## How to run

```bash
python scripts/phase1_validate.py
```

---

## Live validation results (11-Aug-2026)

| Step | Result |
|------|--------|
| TOTP auth | Success — token expiry ~24 hours |
| Profile | Success |
| Holdings | 25 securities |
| Trade history (30 days) | 19 trades, 1 page |

---

## Key observations (carried forward)

Documented in [`DHAN_API_QUESTIONS.md`](DHAN_API_QUESTIONS.md) and [`OBSERVATIONS.md`](OBSERVATIONS.md):

1. `exchangeTradeId` always `"0"` in live NSE_EQ CNC data
2. `exchangeTime` uses ISO format (`2026-08-10T10:17:36`)
3. `orderId` can map to multiple fills (partial execution)
4. IPO allotment rows have `orderId`/`securityId`/`price` = 0

---

## Success criteria

- [x] TOTP auth works programmatically
- [x] Profile, holdings, trade history return valid data
- [x] Pagination loop terminates correctly on empty page
- [x] Raw responses saved for inspection
- [x] Retry policy configurable via env

---

## Out of scope (Phase 1)

- PostgreSQL / Neon
- Trade ingestion / dedup
- FIFO lot engine
- GitHub Actions
- NTFY notifications

**Next:** [`PHASE_2_PLAN.md`](PHASE_2_PLAN.md)
