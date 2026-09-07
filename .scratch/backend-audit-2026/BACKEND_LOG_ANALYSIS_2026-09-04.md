# Backend Log Analysis — 2026-09-04

## Sources

| Source | Window | Size |
|---|---|---|
| `backend/_server.log` | 2026-08-26 15:23 → 16:52 UTC | 1222 lines, 83 HTTP requests |
| `backend/_server.err.log` | 2026-08-26 | 5 lines |
| Live terminal paste (`uv run uvicorn main:app --reload`) | 2026-09-04 11:13 → 11:28 UTC (~15 min) | ~7 server lifecycles |

Method: `Select-String` grouping on `backend/_server.log` for status codes,
endpoint paths, tickers, warnings; manual pass over the 09-04 terminal log for
restart causes, 429s, cache/upsert behaviour, and NSE queries.

---

## 1. TL;DR

- **Health is good:** 83/83 requests `200 OK` in the file log; every request in
  the 09-04 session also `200 OK`. No 4xx/5xx anywhere. DB initializes cleanly
  on every boot.
- **Full analytics surface is exercised and responding:** concentration,
  risk-score, forecast-risk (incl. `?model=GARCH`), realized-risk,
  factor-exposure, summary, liquidity (+ `liquidity-limits`), performance-history
  (`days=90/252`), regime, tear-sheet, volatility-sizing (`?model=EWMA`),
  monte-carlo (POST), portfolio, india-flows, delivery-anomalies, company
  profiles, financial statements.
- **Data layer works end-to-end:** cache-hit path, cache-miss + atomic upsert
  path (`SELECTIPO.NS`, 77 records), and portfolio price refresh (`UPDATE
  portfolio_positions SET last_price, market_value`) all observed succeeding.
- **Known stress points (not outages):**
  1. Screener.in `HTTP 429` rate-limiting on ETF tickers (~22 backoff lines).
  2. One isolated `No price data available for RELIANCE.NS` (08-26 only).
  3. Reload churn during the 09-04 session — per operator note this was active
     code editing; one residual finding is that `--reload` also watches `.venv`
     (faker/pytest/coverage/xdist file events), which causes reloads unrelated
     to edits.
  4. Read-path inefficiency: repeated `SELECT * FROM portfolio_positions` bursts
     + re-fetching the same 14 tickers across overlapping windows;
     `analytics_cache` table exists but is never queried in either log.

---

## 2. What's working (with evidence)

### 2.1 Boot + schema — HEALTHY

Every boot logs `Starting Daisy Risk Engine Backend` → `PRAGMA
main.table_info(...)` for all 8 tables → `Database initialized` →
`Application startup complete.` No migration/schema error in either log.

Tables verified present (08-26 file log shows 4; 09-04 boots show all 8):

- `portfolio_positions`, `stock_timeseries`, `analytics_cache`, `fetch_logs`
- `nse_bhavcopy`, `nse_institutional_flows`, `nse_bulk_block_deals`,
  `nse_shareholding_patterns`

### 2.2 HTTP surface — all 200

File-log endpoint breakdown (83 requests, 100% `200`):

| Endpoint | Hits |
|---|---|
| `/api/v1/analytics/concentration` | 10 |
| `/api/v1/analytics/forecast-risk` | 10 |
| `/api/v1/analytics/factor-exposure` | 10 |
| `/api/v1/analytics/realized-risk` | 10 |
| `/api/v1/analytics/liquidity` | 9 |
| `/api/v1/analytics/summary` | 9 |
| `/api/v1/analytics/risk-score` | 9 |
| `/api/v1/analytics/risk-contribution` | 4 |
| `/api/v1/portfolio` | 4 |
| `/api/v1/analytics/regime` | 4 |
| `/api/v1/analytics/monte-carlo` (POST + OPTIONS) | 3 |
| `/health` | 1 |

09-04 session additionally exercised (all `200 OK`): `tear-sheet`,
`volatility-sizing?model=EWMA&target_volatility=0.15/0.1`,
`forecast-risk?model=GARCH&horizon=1`, `performance-history?days=90/252`,
`india-flows?lookback_days=30`, `delivery-anomalies`, `liquidity-limits`,
`company/{RELIANCE,OLAELEC}/{custom-ratios,shareholding,full-profile,concalls}`,
`data/financials/{income,balance,cashflow}?freq={annual,quarterly}`.

### 2.3 Price-data cache (hit path) — HEALTHY

Steady-state requests are served from `stock_timeseries` without network
fetch. 08-26 portfolio: `RELIANCE.NS`, `TCS.NS` + benchmark `^NSEI`.
09-04 portfolio (14 holdings):

```text
CIPLA.NS, ELECTCAST.NS, MOTILALOFS.NS, ARROWGREEN.NS, JKIL.NS, NTPC.NS,
MCX.NS, MOTHERSON.NS, REDINGTON.NS, NIFTYIETF.NS, MIDCAPIETF.NS,
JUNIORBEES.NS, MAFANG.NS, SELECTIPO.NS  (+ ^NSEI benchmark)
```

### 2.4 Cache-miss + atomic upsert (miss path) — HEALTHY

09-04 11:26:34–11:26:35, monte-carlo with a 2-year window:

```text
Cache miss for SELECTIPO.NS: cached has 370 records from 2025-03-10, requested from 2024-09-04
Storing 77 records for SELECTIPO.NS with upsert logic
INSERT INTO stock_timeseries ... ON CONFLICT (ticker, date) DO UPDATE ...
COMMIT
Successfully atomic upserted 77 records for SELECTIPO.NS
INSERT INTO fetch_logs ... status='success', source_used='yfinance'
Successfully fetched 77 records for SELECTIPO.NS
POST /api/v1/analytics/monte-carlo → 200 OK
```

Gap-fill, conflict-safe upsert, and fetch audit logging all fire correctly.

### 2.5 Portfolio price refresh — HEALTHY

Both logs show live price writes, e.g. 09-04 11:19:45:

```text
UPDATE portfolio_positions SET last_price=?, market_value=?, updated_on=? ...
[(272.07..., 1088.28..., id 10), (24.13..., 4586.59..., id 11),
 (791.78..., 5542.46..., id 12), (207.55..., 1037.79..., id 13),
 (48.90..., 1956.39..., id 14)]
COMMIT
GET /api/v1/portfolio?currency=INR → 200 OK
```

### 2.6 NSE microstructure tables — HEALTHY

09-04 11:27:50: `nse_institutional_flows` 30-day query → 200, followed by
per-symbol `nse_bhavcopy` lookups for all 14 holdings
(`CIPLA`…`SELECTIPO`) → `delivery-anomalies` 200, `liquidity-limits` 200.

---

## 3. What's not working / needs attention

### 3.1 [P1] Screener.in `HTTP 429` rate-limiting — DEGRADED, self-recovering

~22 backoff lines in the 09-04 session, e.g.:

```text
HTTP 429 Rate Limit from Screener.in on https://www.screener.in/company/MIDCAPIETF/. Backing off for 3.22s (attempt 1/3)...
HTTP 429 Rate Limit from Screener.in on https://www.screener.in/api/company/1274872/peers/. Backing off for 3.09s (attempt 1/3)...
HTTP 429 Rate Limit from Screener.in on https://www.screener.in/company/JUNIORBEES/. Backing off for 5.03s (attempt 2/3)...
```

- Affected symbols are all **ETFs** (`MIDCAPIETF`, `JUNIORBEES`, `NIFTYIETF`,
  `MAFANG`, `SELECTIPO`) plus the peers API — company-fundamentals scraping
  being applied to instruments that have no company peers page.
- Retry-with-backoff works (endpoints still return 200), but it stalls
  responses: the `liquidity` call at 11:19:26 didn't complete until ~11:19:44.
- Fixes: throttle/serialize Screener calls (or cache peers payloads), and skip
  the company-peers path for ETF tickers.

### 3.2 [P2] Isolated price-data gap, 08-26 — RECOVERED, watch item

```text
2026-08-26 16:49:26 - app.services.data_service - WARNING - No price data available for RELIANCE.NS
$RELIANCE.NS: possibly delisted; no price data found  (period=2d)   # _server.err.log
```

Single ticker, single session; the position was still repriced via
`UPDATE portfolio_positions` two seconds later, and no recurrence appears in
the 09-04 log. Likely a transient yfinance gap, not a delisting. No action
unless it reappears — consider alerting on repeated `No price data` warnings
per ticker rather than silent fallback.

### 3.3 [P2] `--reload` also watches `.venv` — DEV-ONLY noise

Operator note: the 09-04 restarts were driven by active code editing — that is
expected with `--reload`. Residual finding: several reloads list **only**
`.venv` files as the trigger:

```text
WARNING: WatchFiles detected changes in
'.venv\Lib\site-packages\faker\providers\...', '.venv\...\_pytest\...',
'.venv\...\coverage\...', '.venv\...\xdist\...' Reloading...
```

plus one reload race that killed a worker with a `KeyboardInterrupt` traceback
through `multiprocessing/spawn.py` → `uvicorn/config.py` → `logging/handlers`.
Suggest narrowing the watcher so dependency installs/cache writes don't bounce
the server during dev:

```powershell
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload `
  --reload-dir app --reload-dir main.py --reload-exclude .venv
```

Also: `zz_hook_probe.py` edits at the repo root trigger reloads — either
exclude it or keep probe files outside the watched tree.

### 3.4 [P2] Read-path over-fetching; `analytics_cache` unused — PERF RISK

Observed pattern on every analytics burst (e.g. 09-04 11:19:23, six
`portfolio_positions` selects within ~40 ms; same shape throughout):

- 4–6× `SELECT * FROM portfolio_positions` (full row, all columns) per single
  user action, then the same again per sub-endpoint (`IN (...)` variant).
- The same 14 tickers re-fetched across overlapping windows in one session:
  `2025-12-26→now`, `2025-09-04→now`, `2026-06-06→now`, `2026-08-05→now`,
  `2024-09-04→now`, `2023-08-31→now`.
- `analytics_cache` is created at boot but **never queried** in either log —
  every analytics call recomputes from raw timeseries reads.

Not a correctness bug (results return 200), but request latency and DB read
amplification grow with portfolio size. Fixes: fetch positions once per
request (dependency injection), normalize to one canonical window per caller,
and actually route repeat analytics reads through `analytics_cache`.

### 3.5 [P3] SQLAlchemy echo spam — OBSERVABILITY

~90% of both logs is `sqlalchemy.engine.Engine` INFO (`PRAGMA`, per-query
`SELECT ... [cached since ...]`, `BEGIN/COMMIT/ROLLBACK`). It buries the lines
that matter (the 429s, the RELIANCE warning, the upsert success). Suggest
`echo=False` (or WARN level for the engine logger) in dev, full SQL only behind
a flag.

### 3.6 Non-issues confirmed

- **No 4xx/5xx** in either log — but that also means error/validation paths
  (bad ticker, empty portfolio, auth) weren't exercised in these windows.
- `ROLLBACK` after read-only GETs is normal session cleanup, not an error.
- Duplicate `INSERT INTO fetch_logs` statements (two column shapes) both commit
  `success` — harmless but suggests two writers; worth a dedupe pass.

---

## 4. Recommended actions

| # | Action | Why (log ref) | Priority |
|---|---|---|---|
| 1 | Throttle + cache Screener calls; skip peers path for ETFs | §3.1, ~22× 429 | P1 |
| 2 | Narrow `--reload` scope, exclude `.venv` / probe files | §3.3, 7 restarts | P2 |
| 3 | Single positions-fetch per request; canonicalize date windows | §3.4 | P2 |
| 4 | Wire `analytics_cache` reads into analytics endpoints | §3.4, zero hits | P2 |
| 5 | Alert on repeated `No price data` per ticker | §3.2, one occurrence | P3 |
| 6 | SQL echo off by default | §3.5 | P3 |
| 7 | Exercise error paths (bad ticker, empty portfolio) and confirm 4xx shape | §3.6 | P3 |
