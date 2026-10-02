# Phase 2 — finengine data layer

Status: ready-for-agent
Repo: this project, `backend/`
Tickets: 20
Gate: **issues 01 and 02 must ship together with Phase 1 issue 03.** Landing real OHLCV while
SQLite still holds synthetic rows leaves the cache worse than either state alone.

## The problem in one paragraph

`DataService` implements a 3-tier cascade (bfinance → yfinance → Alpha Vantage) with a SQLite cache
and an in-memory L1. The architecture is sound. The implementation has 6 CRITICAL and 10 HIGH
defects, and the net effect is that **vendor failures are invisible**: the app serves stale prices
as live, returns 404 for tickers that exist, publishes `0.00%` change on a weeks-old close, and
cannot tell you which vendor actually served a given row.

Alpha Vantage was also found to be **100% dead** for this product's entire universe, so the
documented 3-tier cascade is 2-tier in practice.

## Ticket map

| # | Ticket | Severity | Summary |
|---|---|---|---|
| 01 | Read `bfinance_synthetic_ohlc` at ingestion | CRITICAL | RC1 guardrail. Must land with Phase 1 issue 03 |
| 02 | Purge `stock_timeseries` and refetch | CRITICAL | The only irreversible step in the spec. Needs the Phase 0 issue 02 backup |
| 03 | `fetch_historical_data` must raise, not return `None` | CRITICAL | `ProviderInvalidInputError` falls through to a bare `return None` → HTTP 404 "No data found" |
| 04 | Per-vendor normalization adapter | CRITICAL | One normalizer named for one vendor, with no real-vendor test |
| 05 | Add `source` to the cache natural key | HIGH | bfinance and yfinance rows silently overwrite each other |
| 06 | Wire the real TTL | MEDIUM | `_L1_TTL_SECONDS = 300` is dead code; effective TTL is 60 minutes |
| 07 | Real retry backoff | HIGH | 3 attempts × 2 tiers with `asyncio.sleep(0)` — no wall-clock delay |
| 08 | Record cascade fallbacks in `fetch_logs` | HIGH | Fallbacks are **structurally unrecordable** despite the columns existing |
| 09 | Portfolio refresh must not serve stale as live | CRITICAL | Stale `last_price` returned as HTTP 200; `as_of` makes the whole book look fresh |
| 10 | WebSocket honesty | CRITICAL | Publishes `change: 0.00`, `volume: 0`, and a weeks-old close stamped "now" |
| 11 | Shareholding `NaN` → `None` | CRITICAL | A missing promoter quarter becomes a `0.00%` bar |
| 12 | Resolve the Alpha Vantage Tier-3 dead branch | HIGH | `AV_SYMBOL_MAP` is empty; `.NS`/`.BO` returns `None` before any HTTP call |
| 13 | `_db_lock` coverage | MEDIUM | The lock is per-instance; the session is request-scoped and shared across 3 instances |
| 14 | Timezone parity on the date column | MEDIUM | Write path does no utc normalization; read path does `utc=True` |
| 15 | `dropna()` compresses the time axis | MEDIUM | Drops rows with a NaN in *any* column, producing a wrong return series |
| 16 | Wire `get_corporate_actions` to a route | MEDIUM | Exists, returns splits + dividends, exposed on no route |
| 17 | Screener source and status honesty | HIGH | Silently drops symbols, publishes `0.0` for NaN, hardcodes the source string |
| 18 | Preserve the vendor name on the error path | MEDIUM | A yfinance rate limit logs as a generic outage |
| 19 | Log identifiers and redact upstream text | MEDIUM | Vendor failures are unattributable; one module logs raw upstream exceptions |
| 20 | Remove dead code | LOW | `check_data_integrity` has no caller |
| 21 | Close and volume reconciliation against NSE | HIGH | Third-party check that a vendor's close is actually right. Would have caught RC1 and RC2 at ingestion |
| 22 | **Source degradation contract** | HIGH | **No contract exists for what happens when a source dies.** Most paths degrade silently; there is no health endpoint at all |

## What is already correct — do not regress

- **The aiosqlite pragma trap is already fixed.** `db/database.py:92-115` applies WAL,
  `busy_timeout=30000`, and the rest unconditionally through the adapter's sync `execute()`, with
  **no** `isinstance(dbapi_connection, sqlite3.Connection)` guard. The docstring documents the
  exact historical failure. This was the trap described in `CONTEXT.md` §9.21 and it is genuinely
  resolved. Keep it that way.
- **Preference-switch invalidation is thorough.** `source_preference_service.set_primary_source:83-87`
  and `data.py:420-427` both delete the affected tables, advance the generation, and call
  `clear_service_memos()` — before *and* after commit. Correct.
- **The `data_status` / `universe_coverage` disclosure contract is unusually mature.**
  `analytics.py:283-374`. Most empty-data paths do set it. The gaps are concentrated in
  `portfolio.py`, `websocket.py`, `data.py`, `equity_research_service.py`, `screener_service.py`
  and the `fetch_logs` path.
- **`clear_service_memos` reaches every known memo** — DataService L1/quote, screener, FX, company
  fundamentals, cointegration, tails. `cache_service.py:137-212`.
- **Cache key normalization is consistent** — `canonical_ticker(ticker).upper()` on both read
  (`:1472`) and write (`:1645`). No cross-ticker contamination.
- **FX fallback is honestly labelled** — `currency_service.py` surfaces `provenance="fallback"` and
  `coerce_live_fx_rate:76-124` refuses to use it as live. This is the one place the contract fully
  holds. Use it as the template for the rest.

## Rollback

| Change | Rollback |
|---|---|
| Issue 02 purge | **Irreversible.** Requires the Phase 0 issue 02 file backup |
| Issue 05 `source` column | Requires a migration. Keep the old unique index name so the downgrade is mechanical |
| Issue 07 backoff | Config-driven; revert the constants |
| Issue 12 Tier-3 | Additive; either implement or remove the docs/UI |

## Verification

- After issue 02: no `stock_timeseries` row carries a synthetic-OHLC marker, and a spot-check
  ticker matches yfinance O/H/L/C within 0.01%.
- A test that forces both vendors to fail asserts the response is a **provider error**, never a 404,
  never an empty `200`.
- A test that forces only the primary to fail asserts a `fetch_logs` row exists with
  `primary_attempt=True, fallback_attempt=True` and the correct `source_used`.
- A test asserts a stale position is flagged as stale and that `as_of` reflects the oldest stale
  position, not the newest fresh one.
- A test corrupts a vendor close by 100× and asserts issue 21's reconciliation **catches it**. This
  is the RC1/RC2-class guard.
- `pytest --cov-fail-under=80` and ruff `E9`+`F` stay green.
