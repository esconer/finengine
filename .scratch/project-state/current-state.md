# Daisy Risk Engine — Current State of the Project

Recorded: 2026-08-25 · Scope: full read of `backend/app/**`, `frontend/src/**`, configs, tests, CI

---

## 1. What this project is

**Daisy Risk Engine** is a personal, single-user financial risk analytics platform for managing a stock
portfolio (Indian-market focused) and computing risk metrics on it.

- **Backend** (`backend/`, Python 3.12, uv): FastAPI + SQLite (async SQLAlchemy) + yfinance market data +
  quantstats/arch/statsmodels analytics. Runs on port 8000.
- **Frontend** (`frontend/`, Bun): Next.js 16 App Router + React 19 + TypeScript + Tailwind + Recharts +
  Zustand + TanStack Query/Table. Runs on port 3000, proxies `/api/v1/*` to the backend.
- **Origin doc**: `instructions/project_details.md` is the original 10-step AI-vibe-coding build guide;
  `instructions/doc/` holds ~30 historical fix/verification reports from that build process.

Status: **functional MVP**. Portfolio CRUD, market-data caching, and most analytics pages work end-to-end,
but several analytics paths still run on demo/hardcoded data instead of the user's actual positions
(details in §7).

---

## 2. Architecture & data flow

```
yfinance (NSE/BSE tickers auto-suffixed .NS/.BO)
   → DataService (retry ×3, asyncio timeout, multi-index flattening)
      → SQLite cache (stock_timeseries upsert-by-(ticker,date)) + FetchLog
         → AnalyticsEngine (quantstats-style metrics, GARCH/EGARCH/EWMA forecasts)
            → REST /api/v1/{portfolio,data,analytics} + WebSocket /api/v1/ws/ws/{client_id}
               → Next.js dashboard (Zustand stores + hooks + Recharts)
```

---

## 3. Backend

### Entry point & app setup — `backend/main.py`
- FastAPI app "Daisy Risk Engine API" v0.1.0, lifespan initializes DB (`init_db`) — `main.py:54-77`.
- Middleware: CORS (localhost:3000), GZip, security headers; HTTPS-redirect + trusted-host only in
  production (`main.py:79-101`). Production host hint: `daisy-risk-engine.com`.
- Routers mounted: `/api/v1/portfolio`, `/api/v1/data`, `/api/v1/analytics`, `/api/v1/ws`
  (`main.py:114-137`), plus `/health` and `/`.

### Config — `app/config.py`
Pydantic Settings, env-file driven: `DATABASE_URL` (default `sqlite:///./data/daisy.db`),
`YFINANCE_TIMEOUT=30s`, `CACHE_TTL_MINUTES=60`, `DEBUG=true`, CORS origins. Note `settings.debug`
defaults true → SQL echo on.

### Database — `app/db/database.py`, `app/models/database.py`
Async engine (aiosqlite) with SQLite pragmas (WAL, foreign_keys ON, mmap 256MB).
Tables:
| Table | Purpose |
|---|---|
| `portfolio_positions` | holdings: ticker, weight, **quantity, buy_price** (added later via `migrations/add_portfolio_columns.py`), last_price, sector/industry, region |
| `stock_timeseries` | OHLCV+adj_close cache, unique-ish (ticker,date) composite index |
| `analytics_cache` | metric TTL cache (ticker, metric_name, expires_at) — **defined but barely used** |
| `fetch_logs` | yfinance fetch attempt audit |

Alembic is declared in deps but migrations are ad-hoc scripts under `migrations/`.

### Services
- **DataService** (`services/data_service.py`, ~730 lines): Indian-market defaults — bare tickers get `.NS`
  appended (`_normalize_indian_ticker`), 20 popular NSE stocks seeded. `fetch_historical_data`: SQLite cache
  check → yfinance download wrapped in executor + timeout, 3 retries, multi-index flattening, validation
  (OHLC sanity, >50% moves, dupes/nulls), row-wise INSERT-or-UPDATE upsert. Also quotes, batch fetch
  (500ms spacing between tickers), corporate actions, `check_data_integrity`.
- **CacheService** (`services/cache_service.py`): TTL get/set on `analytics_cache`, fetch logging, stats.
  Only `log_fetch_attempt` is heavily used; analytics endpoints do **not** go through this cache.
- **AnalyticsEngine** (`services/analytics_engine.py`, ~1100 lines): pure-calculation class.
  - Realized: annualized return/vol, Sharpe (rf=2%), Sortino, hit ratio, historical VaR/CVaR 95%, max
    drawdown, skew/kurtosis, per-position breakdown.
  - Forecast: GARCH(1,1)/EGARCH(1,1) via `arch` (simulation forecast), EWMA λ=0.94 with mean-reversion;
    VaR/CVaR derived as z×vol.
  - Concentration: HHI, effective positions, top-N weights. Liquidity: volume-tier heuristic scoring.
  - Stress test: 4 historical windows (2018Q4, COVID, 2022 inflation, vol spike) with fallback simulation;
    recovery-time estimate.
  - Volatility sizing: EWMA vols + correlation matrix → scale weights toward target vol, trade deltas
    against a **hardcoded ₹/$100k portfolio value assumption**.
  - Risk score: weighted components (concentration 20%, vol 25%, correlation 20%, factor 25%, market 10%),
    alerts generated.
  - Factor exposure: OLS alpha+market beta only; **momentum/size/value/min_vol/quality/rates/volatility/
    meme/ai are hardcoded placeholders** (`analytics_engine.py:866-874`). Benchmark series is never wired
    (SPY comment at `analytics_engine.py:153-157`), so R² falls back to 0.5 unless caller supplies data.
  - Every method degrades to `_empty_*()` canned payloads on insufficient data.
- **CurrencyConversionService** (`services/currency_service.py`): USD↔INR with 30-min in-memory cache, but
  the rate itself is a **fixed fallback 83.0** (`currency_service.py:165-174`); Indian lakh/crore formatting.

### API surface
**Portfolio** (`api/portfolio.py`, prefix `/api/v1/portfolio`)
| Method+Path | Behavior |
|---|---|
| `GET ""` | list + refresh prices from yfinance (sequential per position), computed cost/gain fields, sector mix, optional currency conversion |
| `POST /add` | validates ticker vs yfinance (typo suggestions via edit-distance, `:773-875`), 409 on duplicate, persists with live price |
| `POST /bulk_add` | staged validate-then-single-atomic-commit pipeline (`:250-473`) |
| `GET /{ticker}` | single position (⚠ hardcodes market_value = 100000 × weight, `:529`) |
| `PUT /{ticker}` | update weight/quantity/buy_price/name |
| `DELETE /{ticker}` | delete |
| `GET /export/csv` | CSV text of all positions |
| `POST /normalize` | proportional weight normalization to 1.0 |

**Data** (`api/data.py`, prefix `/api/v1/data`): `GET /{ticker}` (timeseries w/ metadata),
`GET /quote/{ticker}`, `POST /batch`, `POST /validate`, `POST /refresh`, `GET/PUT /config`
(PUT is an acknowledged placeholder).

**Analytics** (`api/analytics.py`, prefix `/api/v1/analytics`): `realized-risk`, `forecast-risk`,
`factor-exposure`, `concentration`, `liquidity`, `stress-test` (POST), `volatility-sizing`, `risk-score`,
`summary`. ⚠ Except realized/forecast/factor (which accept `tickers=`), concentration, liquidity,
stress-test, volatility-sizing, risk-score and summary run on a **hardcoded demo portfolio**
AAPL/MSFT/GOOGL/AMZN @ 25% each (`analytics.py:312,354,410,457,501,546`) — user's actual DB positions are
ignored there.

**WebSocket** (`api/websocket.py`, path `/ws/{client_id}`): connection manager with topic
subscribe/unsubscribe/ping-pong; `/status`; `/broadcast`. Background task broadcasts `portfolio_update`,
`analytics_update`, `market_data_update` every 30s — **all mock/hash-jittered data**
(`websocket.py:94-165`), and its service construction `GlobalDataService()` lacks the required
db_session arg (`websocket.py:73`), so the loop mostly logs errors and retries.

---

## 4. Frontend

### Routes (`src/app`)
| Route | File | What it does |
|---|---|---|
| `/` | `page.tsx` | redirect stub to dashboard |
| `/dashboard` | `dashboard/page.tsx` (464 ln) | summary: hero, 4 metric cards, RiskMetricsDisplay, performance + sector charts, positions DataTable, add modal, quick actions (add/run/rebalance/stress), health summary |
| `/dashboard/realized-risk` | uses `usePortfolioAnalytics` hook (realized-risk section) | metrics table + rolling context |
| `/dashboard/forecast-risk` | `forecast-risk/page.tsx` | model selector (EWMA/GARCH/EGARCH), horizon, per-ticker forecast cards |
| `/dashboard/factor-exposure` | `factor-exposure/page.tsx` | heatmap-style factor betas |
| `/dashboard/concentration` | `concentration/page.tsx` | top-N, HHI, effective positions visuals |
| `/dashboard/liquidity` | `liquidity/page.tsx` | score gauge, per-position liquidity |
| `/dashboard/stress-testing` | `stress-testing/page.tsx` | scenario picker, runs stress test (two call sites) |
| `/dashboard/volatility-sizing` | `volatility-sizing/page.tsx` | target-vol slider, recommended weights/trades |
| `/portfolio/manage` | `manage/page.tsx` (831 ln) | full CRUD table, inline edit, currency toggle USD/INR, per-position GARCH forecast badges, filters/sort, add/edit modals |

Sidebar nav (`components/layout/Sidebar.tsx:35-84`) exposes all nine entries. Dark mode via `document.documentElement.classList` toggle persisted in Zustand.

### Data layer (`src/lib`)
- **api.ts**: axios instance, baseURL `NEXT_PUBLIC_API_URL || http://localhost:8000/api/v1`, 30s timeout,
  request/response logging interceptors, rich 422/409 error extraction. Namespaced clients
  `portfolioApi` (7 fns), `dataApi` (7), `analyticsApi` (9), `healthApi`. `getPortfolio` defaults
  `currency=INR`.
- **store.ts**: three Zustand stores — `usePortfolioStore` (persisted positions/selectedTickers; CRUD
  actions call portfolioApi then refetch), `useUIStore` (persisted darkMode/sidebar/liveDataMode),
  `useAnalyticsStore` (in-memory Map cache w/ 5-min TTL + realtime payload slots). Plus `useCSVExport`
  helper. (A separate placeholder `useAutoRefresh` lives here too; the real one is in `hooks/useRealTime.ts`.)
- **websocket.ts**: `WebSocketClient` class — exponential-backoff reconnect (max 5), 30s ping heartbeat,
  topic subscriptions; URL built as `ws://<host>/api/v1/ws/ws/<clientId>` (double `ws` is intentional:
  router prefix + route). Hooks: `useWebSocket` (auto connect when liveDataMode) and
  `useRealTimeAnalytics` (subscribes analytics/market_data/portfolio topics).
- **export.ts**: client-side CSV/XLSX (via `xlsx`) and PDF (jsPDF) export helpers + number/currency
  formatters.
- **utils.ts**: `cn`, INR-default currency formatting, debounce, misc string helpers.

### Hooks (`src/hooks`)
- **useAnalytics.ts**: `usePortfolioAnalytics` — fires all 7 analytics endpoints in parallel
  (`Promise.allSettled`), passing comma-joined tickers from the store where supported; tolerates partial
  failure. `usePerformanceData` — ⚠ **generates mock 90-day performance client-side**
  (`useAnalytics.ts:99-133`). `useSectorAllocation` — derives sectors from positions.
- **useRealTime.ts**: working `useAutoRefresh` (interval refresh gated by liveDataMode) +
  `useEnhancedRealTimeAnalytics` (bridges WebSocket messages into `useAnalyticsStore`, tracks freshness).

### Components (`src/components`)
- **layout**: `DashboardLayout`, `Header` (refresh, live/manual toggle, dark mode), `Sidebar`.
- **charts**: `PerformanceChart`, `SectorAllocationChart`, `RiskMetricsDisplay` (realized + forecast
  tiles), `PortfolioManagement` (legacy composite).
- **portfolio**: `AddPositionModalSimple` (used on dashboard + manage), `EditPositionModal`,
  `PortfolioStats`, `PortfolioTable`, `PortfolioFilters`, `PortfolioCharts`, `CurrencySelector`, and
  **`AddPositionModal` (~700-line "bulletproof" version — imported nowhere; dead code)**.
- **ui**: `MetricCard`, `DataTable` (TanStack), `LoadingState` (skeletons), `NotificationSystem`
  (toasts), `ExportPanel`, shadcn-style `dialog`/`select`.

### Config
- `next.config.ts`: React Compiler disabled; rewrite `/api/v1/:path*` → `http://localhost:8000/api/v1/:path*`
  (so relative-fetch exports work through the dev-server proxy).
- Types mirror backend schemas in `src/types/index.ts` incl. currency types and chart props.

---

## 5. Tests & CI/CD

- **Backend** (`backend/tests/`): pytest + pytest-asyncio, in-memory SQLite fixtures in `conftest.py`;
  suites for analytics engine, data/portfolio/analytics API endpoints, and extensive websocket coverage.
  Coverage gate ≥80% enforced in `pyproject.toml:64`. Root-level integration scripts:
  `test_api_integrity.py`, `test_bulk_operations_integrity.py`, `test_integrity_api.sh`.
- **Frontend**: vitest + Testing Library; currently only `src/test/components/MetricCard.test.tsx` (+ setup).
- **CI** (`.github/workflows/ci-cd.yml`): on push main/develop + PRs to main; backend job installs uv, runs
  ruff lint/format, mypy, pytest. (Frontend/docker jobs continue beyond the portion inspected.)
- **Deploy artifacts**: `Dockerfile` in both apps, `scripts/deploy.sh`, GHCR image naming in CI env.

---

## 6. Conventions & quirks worth knowing

- Tickers are uppercased everywhere; Indian normalization appends `.NS` aggressively — a US ticker like
  `AAPL` becomes `AAPL.NS` server-side (intended: this deployment targets NSE).
- Currency default is INR end-to-end (API default param, formatters, store), but several UI spots render `$`.
- WebSocket topic names in payloads are `portfolio_update`/`analytics_update`/`market_data_update`, while
  subscription topics are `portfolio`/`analytics`/`market_data`.
- The `docs/agents/*.md` files configure agent tooling (issue tracker = local markdown under `.scratch/`),
  not the product.

---

## 7. Known gaps / tech debt (evidence-backed)

1. **Demo portfolio leakage** — 6 analytics endpoints ignore DB positions and use AAPL/MSFT/GOOGL/AMZN
   @25% (`backend/app/api/analytics.py:312,354,410,457,501,546`).
2. **WebSocket realtime is fake** — broadcasts hash-jittered mock data; background task constructs
   `GlobalDataService()` without its required session (`backend/app/api/websocket.py:73,94-165`).
3. **Factor model placeholders** — 8 of 11 factors hardcoded; benchmark never fetched
   (`backend/app/services/analytics_engine.py:866-874,153-157`).
4. **Suspected bulk-add breakage** — module-level `_validate_portfolio_position(self, position)`
   (`portfolio.py:475`) is called with one arg (`portfolio.py:362`) → TypeError swallowed into
   `failed_positions`, so every position in a bulk add likely reports failure. Needs a runtime check.
5. **Dead "Rebalance" action** — dashboard POSTs `/portfolio/rebalance` which doesn't exist; backend
   endpoint is `/portfolio/normalize` (`frontend/src/app/dashboard/page.tsx:393`).
6. **Raw `fetch('http://localhost:8000/...')` bypasses the axios client** in `dashboard/page.tsx:156,393`
   and `portfolio/manage/page.tsx:147,195,222,246` — breaks non-local deployments; inconsistent error
   handling vs `lib/api.ts`.
7. **Mock performance chart** — `usePerformanceData` fabricates data client-side
   (`frontend/src/hooks/useAnalytics.ts:99-133`); hardcoded fake "change" deltas on summary MetricCards
   (`dashboard/page.tsx:259,267,275,283`).
8. **Fixed FX rate** — USD/INR pinned at 83.0, no live feed (`currency_service.py:165-174`).
9. **$100k assumptions** — single-position GET and normalize set `market_value = 100000 × weight`
   (`portfolio.py:529,755`); volatility-sizing assumes ₹/$100k notional
   (`analytics_engine.py:485`).
10. **Dead code** — `AddPositionModal` (~700 lines) unused; legacy `PortfolioManagement` chart composite;
    placeholder `useAutoRefresh` duplicated in `store.ts`; `analytics_cache` table written by nothing.
11. **Performance** — `GET /portfolio` refreshes every position's quote sequentially via yfinance on each
    page load (`portfolio.py:71,878-897`).
12. **Minor mismatches** — `/data/batch` response builder passes `source_used`/`fetch_status` kwargs not on
    `StockDataResponse` (`data.py:176-177`); `api.ts.updatePosition` omits `quantity`/`buy_price` although
    backend accepts them; `pyproject.toml` pins Python ≥3.12 while guide says 3.11; Alembic installed but
    unused (ad-hoc migration scripts).

---

## 8. Suggested next steps (if picking work up)

1. Wire analytics endpoints to real `PortfolioPosition` rows (weights from DB, tickers from holdings) —
   kills gap #1 and makes every dashboard page reflect reality.
2. Fix bulk-add validator signature (#4) and point Rebalance at `/portfolio/normalize` (#5).
3. Consolidate all frontend HTTP through `lib/api.ts` (#6) and replace mock performance data with a real
   portfolio-timeseries endpoint (#7).
4. Either implement the WS background worker properly or hide live-mode until then (#2).
5. Replace fixed FX rate with a real provider (#8).
