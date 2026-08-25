# Release Notes

## 2026-08-25 — Analytics foundation, test-suite repair, data-vendor resilience

Full-stack financial risk analytics ("Daisy Risk Engine"): Next.js 16 frontend + FastAPI/SQLite
backend, NSE-focused portfolio risk tooling.

This release makes every analytics endpoint compute on the user's **actual holdings** instead of a
hardcoded demo portfolio, repairs a test suite that had rotted to 35 failures, adds three new
data-capability surfaces adapted from open-source projects, and wires an Alpha Vantage multi-key
fallback vendor.

---

### 1) Fixed — real product bugs

| # | Bug | Impact before | Fix |
|---|-----|---------------|-----|
| 1 | All 9 analytics endpoints defaulted to hardcoded demo portfolio (`AAPL,MSFT,GOOGL,AMZN` @ 25%) | concentration / liquidity / stress / sizing / risk-score / summary pages ignored user holdings | `_load_portfolio_allocation(db)` derives weights from DB positions (market-value → weight column → equal); explicit `tickers=` param still overrides |
| 2 | `volatility_sizing` computed row-vector `wᵀM` instead of quadratic form `wᵀMw` | endpoint **never worked** — array-truthiness exception swallowed into empty results | proper covariance quadratic form via `np.outer(vols, vols)` |
| 3 | Stress-test filtered returns by date on integer-indexed series (fresh fetch shape) | crash `int64 vs str` on any non-cached portfolio | new `_price_series()` / `_assign_price()` helpers return date-indexed closes at all 6 call sites |
| 4 | `GET /data/config` declared after dynamic `GET /data/{ticker}` | route shadowed → 404 in production | static routes moved above the dynamic one |
| 5 | `GET /portfolio/{ticker}` response missing schema-required fields (`quantity`, `buy_price`, computed gains) added in an earlier schema change | guaranteed 500 | full response construction + eager `db.refresh()` (also fixes greenlet lazy-IO on `updated_on`) |
| 6 | CSV export called `.isoformat()` on NULL `updated_on` | 500 for fresh rows | falls back to `added_on` |
| 7 | Timeseries metadata passed raw `sector=None`/`industry=None` | 500 for tickers lacking fundamentals (ETFs, many BSE names) | None values filtered before serialization |
| 8 | WebSocket background worker constructed `GlobalDataService()` without required session arg | crash-loop every cycle; no broadcasts ever sent | removed dead construction inside loop |
| 9 | Bulk-add module-level validator defined `(self, position)` but called with one arg | TypeError swallowed per-row → **every bulk position failed** | signature fixed; regression test asserts `added==2, failed==0` |
| 10 | Liquidity endpoint expected capital-`V` `Volume` while cache stores lowercase | empty liquidity analysis from cache path | case-adaptive column mapping + engine-shaped frames |
| 11 | Default `DATABASE_URL=sqlite:///…` (sync driver) fed to async engine | app could not boot without env override | default now `sqlite+aiosqlite:///./data/daisy.db` |

### 2) Added — features & endpoints

**Technical indicators (adapted from [TauricResearch/TradingAgents] `dataflows`, Apache-2.0)**
- `app/services/indicators_service.py` — stockstats-powered engine over our SQLite cache;
  13 curated indicators (RSI, MACD family, SMA/EMA, Bollinger, ATR, VWMA, MFI) with usage notes;
  stale-frame rejection (>10 days old data refused); CPU work off-thread.
- `GET /api/v1/data/indicators/{ticker}?indicators=rsi,macd&lookback_days=90`
- `GET /api/v1/data/verified-snapshot/{ticker}` — deterministic ground-truth row (latest OHLCV +
  core indicators + recent closes).

**Company reference data (adapted from TradingAgents `y_finance.py`, Apache-2.0)**
- `app/services/company_data_service.py`
- `GET /api/v1/data/fundamentals/{ticker}` — curated ~28-field snapshot; stub-info guard;
  distinguishes 404 (no data) vs 503 (upstream outage, e.g. Yahoo crumb-auth 401).
- `GET /api/v1/data/financials/{ticker}?statement=income|balance|cashflow&freq=quarterly|annual`
  structured JSON (periods × metrics), look-ahead period filter ported.
- `GET /api/v1/data/insider/{ticker}` — insider transactions feed.

**Alpha Vantage fallback vendor (multi-key rotation)**
- `app/services/alpha_vantage_service.py` — automatic fallback behind yfinance after retries fail.
- Key pool: N free keys ⇒ N×25 req/day, N×5 req/min; per-key budgets tracked in-process so
  exhausted keys are skipped **without network calls**; daily-limit notice retires key until
  midnight, frequency notice imposes 60 s cooldown, invalid keys dropped; error taxonomy per
  TradingAgents #991 (rate-limit phrasing classified before api-key phrasing).
- Symbol bridge `.NS → .BSE` (AV has no NSE feed); US symbols pass through.
- Rows stored with `source_used='alphavantage'`; fetch log records `fallback_attempt=True`.
- Enable via `backend/.env`: `ALPHA_VANTAGE_API_KEYS=key1,key2,…` (template: `backend/.env.example`).

### 3) Test suite — from 35 failures / broken infra → **88 passed (~3 s)**

- conftest: httpx ≥0.27 migration (`ASGITransport`), per-test isolated SQLite via FastAPI
  dependency overrides (tests previously hit the real production DB!), seeded-position +
  schema-correct OHLCV factory fixtures.
- Rewrote stale suites asserting pre-`quantity/buy_price` payloads, wrong URLs
  (`/analytics/stress-testing` vs POST `/stress-test`), methods endpoints don't call
  (`fetch_ohlcv_batch`), sync mocks on async seams, and websocket tests that waited for messages
  the server never emits unsolicited.
- New `tests/test_alpha_vantage.py`: rotation-on-daily-limit, retire-honored-on-retry,
  cooldown→reuse, local budget guard (zero wasted calls), no-key no-op, symbol bridge.

### 4) Changed — infra & deps

- Python pinned to **3.12** (`.python-version`) — `ecos`/cvxpy solver chain ships Windows wheels
  for 3.12 only; matches CI matrix. `uv sync --extra dev` now completes cleanly on Windows.
- Added dependency: `stockstats==0.6.8`.
- Repo hygiene: untracked live `data/daisy.db`; ignored `*.db`; `backend/.env.example` template.

### 5) Agent tooling & project tracking

- `AGENTS.md` + `docs/agents/{issue-tracker,triage-labels,domain}.md` — local-markdown tracker
  convention under `.scratch/<feature>/`.
- `.scratch/project-state/current-state.md` — full codebase state audit (file-by-file).
- `.scratch/advanced-analytics/spec.md` — "Bloomberg-grade" roadmap: free-site filter test,
  resource map (riskfolio-lib / PyPortfolioOpt / quantstats / QuantLib already-in-deps strategy),
  13 decision-mapped features, phases P0–P6, risks.
- `.scratch/advanced-analytics/issues/01–22` — ticketed plan incl. completed t01/t02/t21/t22.

### 6) Known issues / next up

- Fundamentals endpoint returns **503** until Yahoo's transient crumb-auth rejection clears
  (endpoint contract correct; will self-heal).
- Alpha Vantage fallback activates once keys are placed in `backend/.env`.
- Roadmap pending: benchmark ingestion (^NSEI) → quantstats tear-sheet → Euler risk contribution →
  optimizer studio → regime/Monte-Carlo/tails → NSE flows dashboard → PDF review (tickets 03–20).

[TauricResearch/TradingAgents]: https://github.com/TauricResearch/TradingAgents
