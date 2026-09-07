# Spec: User-Selectable Data Source Preference & True Cache Purge

**Status**: `closed` (implemented & verified 2026-09-06)
**Created**: 2026-09-06
**Scope**: Backend data pipeline + `/dashboard/settings` UI

---

## 1. Problem

1. The market-data cascade is **hardcoded** `bfinance → yfinance → Alpha Vantage`
   (`data_service.py::_download_with_timeout`, `fetch_quote`, and
   `company_data_service.py::get_fundamentals`). The user cannot choose which
   vendor is hit first; a flaky bfinance upstream forces every fetch through the
   same failing tier before falling back.
2. The Settings page "Purge Cache & Recompute Models" button is **fake** — it
   merely calls `fetchPortfolio()` (a GET). No backend endpoint clears cached
   market data, so "clean data in" is impossible without deleting the SQLite file
   by hand (which would also nuke holdings).

## 2. Requirements (from user)

- **R1** — User picks the primary data source independently:
  - `bfinance` primary ⇒ `yfinance` fallback.
  - `yfinance` primary ⇒ `bfinance` fallback.
  - **Alpha Vantage is ALWAYS last**, regardless of the choice.
- **R2** — Settings UI button that truly clears the cache so fresh data is
  pulled, **except portfolio entries** (what the user owns: ticker, quantity,
  avg buy price, weight, etc.). Holdings are user-owned truth and have nothing
  to do with cached market data.
- **R3** — Document in `.scratch/` before implementing (this file).

## 3. Design Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Preference persisted **backend-side** in a new `app_settings` key-value table via `GET/PUT /api/v1/data/config` | The cascade runs in the backend; localStorage-only would never influence fetch order. Single-row SQLite read per fetch is negligible. |
| D2 | Key `primary_data_source` ∈ {`bfinance`, `yfinance`}; default **`bfinance`** | Preserves today's Tier-1 behavior when the setting has never been touched. |
| D3 | Preference applies to every fetch path where the two vendors are genuinely interchangeable: **OHLCV history** (`fetch_historical_data`), **live quotes** (`fetch_quote`), **fundamentals** (`company_data_service.get_fundamentals`) | These are the paths where swapping order is meaningful. |
| D4 | Screener, Equity Research, AI Dossier stay bfinance-only; USD/INR FX stays yfinance-only | Concall MP3s / Ind AS statements / `bfinance.screens` do not exist on yfinance — there is nothing to fall back to. Documented as "vendor-exclusive pipelines". |
| D5 | `POST /api/v1/data/cache/clear` wipes: `stock_timeseries`, `analytics_cache`, `fetch_logs`, `nse_bhavcopy`, `nse_institutional_flows`, `nse_bulk_block_deals`, `nse_shareholding_patterns` **+ in-memory caches** (`DataService._in_memory_df_cache`, screener `_cache`, currency `_exchange_rates`) | "Clean data in" must include in-process memo caches or stale frames would survive a DB wipe. `fetch_logs` are diagnostic, not user data. |
| D6 | `portfolio_positions` is **never** touched by the clear endpoint | R2 — holdings truth. Response explicitly reports what was cleared and that holdings were preserved. |
| D7 | Actual source used is recorded (`source_used` on `stock_timeseries` + `fetch_logs`) instead of the current hardcoded `"yfinance"` | Auditable data lineage per row — needed to *verify* the cascade order works. |

## 4. Effective Fallback Chain

```
primary = bfinance :  bfinance → yfinance → Alpha Vantage (always last)
primary = yfinance :  yfinance → bfinance → Alpha Vantage (always last)
```

Applies per-fetch (read at request time — changes take effect immediately,
no restart).

## 5. API Contract

### `GET /api/v1/data/config` (extended)
```json
{ "primary_source": "bfinance", "cache_ttl_minutes": 60, "enable_cache": true }
```

### `PUT /api/v1/data/config?primary_source=yfinance` (new param)
- Validates `primary_source ∈ {bfinance, yfinance}` → `400` otherwise.
- Persists to `app_settings`, returns the updated config.

### `POST /api/v1/data/cache/clear` (new)
```json
{
  "cleared": {
    "stock_timeseries": 15230, "analytics_cache": 48, "fetch_logs": 310,
    "nse_bhavcopy": 0, "nse_institutional_flows": 0,
    "nse_bulk_block_deals": 0, "nse_shareholding_patterns": 0,
    "in_memory_caches": 3
  },
  "total_rows_cleared": 15588,
  "portfolio_preserved": true,
  "message": "…"
}
```

## 6. UI (Settings → Data Feed Architecture card)

1. **Primary Data Source** selector (`bfinance` / `yfinance`) with the live
   fallback-chain explainer (`bfinance → yfinance → Alpha Vantage (last)`),
   loaded from `GET /data/config` on mount and persisted via `PUT /data/config`
   on Save.
2. **Clear Market Data Cache** button replaces the fake purge: confirm dialog →
   `POST /data/cache/clear` → renders per-store row counts cleared and a
   "portfolio holdings preserved" assurance.

## 7. Tickets

- [x] **DSP-01** `app_settings` model + source-preference store
- [x] **DSP-02** Configurable cascade in `data_service` (OHLCV + quotes)
- [x] **DSP-03** Configurable cascade in `company_data_service` (fundamentals)
- [x] **DSP-04** `GET/PUT /data/config` + `POST /data/cache/clear`
- [x] **DSP-05** Backend tests (order, roundtrip, holdings preservation)
- [x] **DSP-06** Frontend: api client + Settings UI wiring
- [x] **DSP-07** Full test suites green (pytest + vitest + tsc)
- [x] **DSP-08** Shared-AsyncSession race fix for concurrent batch fetching (see §10)
- [x] **DSP-09** Cross-session SQLite contention + dead pragma listener fix (see §11)
- [x] **DSP-10** Two-window risk split: instrument risk on full history, realized P&L on holding period (see §12; discovered in the full-page audit `.scratch/page-audit-2026-09/audit.md`)

## 8. Out of Scope / Follow-ups

- Per-position source pinning (`portfolio_positions.primary_source` columns
  remain informational defaults).
- Alphavantage-as-primary (user explicitly wants it pinned last).
- UI for alphavantage key pool management.

---

## 9. Implementation Record (2026-09-06)

| File | Change |
|---|---|
| `backend/app/models/database.py` | New `AppSetting` model (`app_settings` KV table; auto-created via `create_all` on next backend start) |
| `backend/app/services/source_preference_service.py` | NEW — `get_primary_source` / `set_primary_source` (validated upsert + `expire_all`) / `source_order_for` / `validate_source`; `SELECTABLE_SOURCES = (bfinance, yfinance)`; default `bfinance` |
| `backend/app/services/data_service.py` | `_resolve_source_order()` read per fetch; `_download_with_timeout(source_order)` symmetric cascade (empty frames fall through to next vendor); `fetch_quote` split into `_fetch_bf_quote`/`_fetch_yf_quote` driven by preference; `validate_ticker` honors order; **real bug fix**: `source_used` now read from the raw vendor frame BEFORE `_normalize_yfinance_data` (previously `reset_index` dropped the `_source` marker so every bfinance row was mislabeled `yfinance`) |
| `backend/app/services/company_data_service.py` | `get_fundamentals(source_order=...)` loop; vendor failures fall through, deepest error keeps 404/503 semantics |
| `backend/app/services/cache_service.py` | `clear_market_data_cache(db)` — wipes 7 cache tables + resets `DataService._in_memory_df_cache`, `ScreenerService._cache`, currency FX cache; never touches `portfolio_positions` |
| `backend/app/api/data.py` | `GET /data/config` returns persisted `primary_source`; `PUT /data/config?primary_source=` validates + persists (400 on invalid); NEW `POST /data/cache/clear`; `/fundamentals/{ticker}` passes the cascade |
| `frontend/src/lib/api.ts` | `getConfig`/`updateConfig` typed with `primary_source`; new `dataApi.clearCache()` |
| `frontend/src/app/dashboard/settings/page.tsx` | Primary-source cards (bfinance/yfinance) with live fallback-chain explainer, loaded from backend on mount, persisted on Save; "Clear Market Data Cache" button (confirm → purge → per-store counts + holdings-preserved note) replacing the old fake purge that only refetched the portfolio |
| `backend/tests/test_source_preference_and_cache.py` | NEW — 20 tests: preference store, OHLCV/quote/fundamentals cascade ordering in both directions, AV-always-last, config API roundtrip + 400 on alphavantage, purge preserves positions, idempotent purge |
| `frontend/src/test/pages/Settings.test.tsx` | NEW — 4 tests: chain render, save persistence, purge counts + holdings preserved, confirm-dismissed no-op |

### Notable test pitfalls encountered (for future reference)

- `yf.download`/`yf.Ticker` must be patched with **plain functions/classes**, not
  `Mock` — `data_service` treats a Mock as "unit-test seam" and skips real
  vendors (`is_yf_mocked` guard), which silently disables the bfinance tier.
- Vendor-style frames must carry a `Date`-named index — `_normalize_yfinance_data`
  depends on `reset_index()` producing the `Date` column.
- bfinance fundamentals read `ratios` off the **profile** object, not the ticker.
- `async_sessionmaker(expire_on_commit=False)` identity maps serve stale rows
  after an in-place upsert; `set_primary_source` calls `db.expire_all()`.

### Verification

- `uv run pytest --no-cov` → **368 passed** (348 pre-existing + 20 new; 2 stale
  contract tests updated to the new documented default)
- `uv run ruff check` (E9+F scope) → clean on all touched files
- `bun run test:run` → **66 passed** (62 pre-existing + 4 new)
- `bunx tsc --noEmit` → exit 0

---

## 10. DSP-08: Shared-AsyncSession Race in Concurrent Batch Fetching (closed)

### Evidence (2026-09-06, `backend/server.log`, 17:40–18:08 IST)

Two portfolio-refresh bursts produced **321 ERRORs**:

| Signature | Count | Impact |
|---|---|---|
| `Error storing timeseries data for <ticker>` | 145 (all 14 holdings) | OHLCV upsert dropped for that attempt |
| `Error logging fetch attempt` | 75 | fetch_logs rows lost |
| `Error reading primary source preference` | 25 | fetch silently fell back to the DEFAULT cascade (bfinance) instead of the user's yfinance choice |

All were session-state violations on the ONE request-scoped `AsyncSession`
shared by the 5 concurrent batch workers (`commit() can't be called here`,
`transaction is closed`, `session is provisioning a new connection`, `session
is in 'prepared' state`). HTTP responses stayed 200 and later retries won, so
no net data loss — but any burst losing all retries for a ticker would
silently leave it stale. This is the runtime face of ticket **QH-06**
(concurrent batch fetching was added without session isolation).

### Fix

**Serialize DB operations, keep network parallel.** `DataService` now owns an
instance-level `asyncio.Lock` (`_db_lock`, the "DB gate") and every
session-touching section runs inside it:

- `_resolve_source_order` (preference read — also used by `fetch_quote`)
- cache read in `fetch_historical_data`
- `_store_timeseries_data` + success `log_fetch_attempt` (paired, atomic)
- failed-fetch log write
- `_fetch_from_alpha_vantage` log+store pair
- `_fallback_quote` log write

Network vendor calls (the slow part that justifies concurrency) are NOT under
the lock.

**One preference read per batch**: `fetch_ohlcv_batch` resolves the cascade
once and passes it down via the new `fetch_historical_data(..., source_order=)`
parameter — N redundant reads → 1, and all tickers in a batch use the same
chain even if the setting flips mid-batch.

**Dedupe fetch_logs**: `_log_storage_metrics` no longer inserts its redundant
`FetchLog` row (hardcoded `source_used="yfinance"`, duplicating every success
already logged with the real source). One fetch = one log row.

### Tests (`backend/tests/test_db_gate_concurrency.py`)

`OverlapGuardSession` proxies the session and counts in-flight
`execute/commit/rollback` calls with a sleep widening the interleaving window
— any overlap is a recorded violation:

- concurrent 10-ticker batch through the real pipeline → **0 violations**, all
  tickers stored, bfinance fallback recorded
- concurrent bare `fetch_historical_data` calls on one instance → 0 violations
- preference read exactly **once** per batch, identical cascade passed to all
  workers

Post-fix suite: **371 passed**, ruff clean.

### Gotcha added to CONTEXT.md (#21)

Concurrent coroutines sharing one AsyncSession must gate DB ops; batching
helpers resolve config reads once and thread results down.

---

## 11. DSP-09: Cross-Session SQLite Contention + Dead Pragma Listener (closed)

### Evidence (2026-09-06, post-DSP-08 `server.log`, 18:57 IST)

The shared-session race was **gone** (0 occurrences). But one dashboard burst
produced **135 errors in a single minute**, all
`(sqlite3.OperationalError) database is locked`: 15 dropped timeseries stores +
failed fetch-log writes across tickers. Self-healed on the next load (every
ticker fully stored), but the class remained.

### Root causes (two stacked bugs)

1. **Cross-session writer contention.** The DB gate serializes per-DataService
   session; the dashboard fires many parallel HTTP requests, each with its own
   session/connection. WAL allows one writer + many readers, but parallel
   *writers* still queue — and with sqlite's 5s default busy timeout,
   losers fail with `database is locked`.
2. **The pragma listener was dead code.** `set_sqlite_pragma` guarded with
   `isinstance(dbapi_connection, sqlite3.Connection)`, but the aiosqlite
   dialect delivers SQLAlchemy's `AsyncAdapt_aiosqlite_connection` — the check
   never matched, so **no pragma ever ran** (verified: live `daisy.db` reported
   `journal_mode=delete` despite the listener "setting" WAL). The project's own
   `.scratch/caching-architecture-sqlite-wal-optimization.md` (Hazard 1)
   predicted the missing `busy_timeout`; in reality every pragma in the block
   was inactive.

### Fix (`backend/app/db/database.py`)

- Dropped the isinstance guard; pragmas execute through the adapter's
  synchronous `execute()` (verified: `journal_mode` reads back `wal`,
  `busy_timeout` 30000). `foreign_keys=ON` now actually enforces for the first
  time.
- Added `PRAGMA busy_timeout=30000` — parallel writers wait up to 30s instead
  of failing at 5s.

### Verification

- Full suite **371 passed**, ruff clean.
- One-time effect visible immediately: `daisy.db` now persists
  `journal_mode=wal`.

### Notes on the Data Quality Notice (reported same session)

The realized-risk "Limited Historical Depth" banner is **working as designed**:
all 14 holdings were added 2026-08-27, so the holdings-truth truncation gives
each instrument 7 bars → 6 return observations ("6 trading days"), and
`apply_annualization_gate` prevents annualizing that window into fake
triple-digit risk figures. Informational, not a bug; it clears itself as the
holding period grows.

---

## 12. DSP-10: Two-Window Risk Split (closed, 2026-09-06)

Discovered during the full-page visual audit (`.scratch/page-audit-2026-09/audit.md`,
20 routes driven in the browser): the holdings-truth truncation (correct for
realized P&L) was also feeding analytics whose subject is the ASSET, not the
ownership tenure. With every holding added 2026-08-27 (6 return observations):

- realized-risk: Annual Return / Volatility / Sharpe / Sortino all N/A.
- factor-exposure: the regression degenerated and the engine's
  `_empty_factor_exposure()` placeholder (`{alpha: 0, market: 1}`) rendered as
  **β = +1.000 "Market-Like" for all 14 positions, R² 0.000**.

### Principle

**Weights come from the portfolio; risk comes from the assets.** Realized P&L
stays holding-truthed; risk characteristics (vol, Sharpe, beta, drawdown,
covariance) are asset properties and use full exchange history.

### Changes

- `get_realized_risk`: new `instrument_risk` block (portfolio + per-position
  metrics computed on the unmasked ~174-day window; per-position `total_return`;
  annualization gate vs each ticker's own days); `history_coverage` gained
  `full_history_days` / `full_history_start`; warning reworded to a precision
  statement ("realized P&L covers 6 trading days…; instrument risk metrics use
  the full 174 trading days").
- `get_factor_exposure`: regression on full history; holding window disclosed
  via `history_coverage` only. Verified live: portfolio β 1.093, R² 0.669,
  per-position β 0.54–1.86 (was 1.000 everywhere).
- `realized-risk/page.tsx`: two-window layout — "Instrument Risk — Full
  Exchange History (174 trading days…)" cards + "Holding-Period Realized P&L
  (since …)" section + position table on full-history rows.
- `get_realized_risk` except-clause: `logger.exception` (tracebacks reach the log).

### Verification

Live endpoints: instrument portfolio Annual Return 28.06%, Vol 19.79%,
Sharpe 1.32, Max DD -14.07% (annualized=True, 174 days); holding max DD -0.75%
(6 days). Backend 371/371 pytest, ruff clean; frontend tsc clean, 66/66 vitest;
browser screenshot `21b-realized-risk-FIXED-loaded.png`.
