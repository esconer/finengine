# Daisy Risk Engine — Current State of the Project

Recorded: 2026-08-27 · Scope: full codebase audit, test execution, git status, three-way deep code review

---

## 1. What this project is

**Daisy Risk Engine** is a personal, single-user Bloomberg-grade financial risk analytics
platform for managing and analyzing an Indian equity portfolio (NSE/BSE focused).

- **Backend** (`backend/`, Python 3.12, uv): FastAPI + SQLite (async SQLAlchemy/aiosqlite) +
  yfinance market data + Alpha Vantage multi-key fallback + quantstats/arch/scipy/cvxpy/
  hmmlearn/stockstats analytics. Runs on port 8000.
- **Frontend** (`frontend/`, Bun): Next.js 16 App Router + React 19 + TypeScript + Tailwind +
  Recharts + Zustand + TanStack Query/Table. Runs on port 3000, proxies `/api/v1/*` to backend.
- **Design principle**: "Not on Free Sites" — only builds capabilities that TradingView,
  Screener.in, Chartink, Yahoo Finance do NOT provide.

Status: **advanced quant analytics MVP**. Portfolio CRUD, market-data caching, tear-sheet,
risk contribution, portfolio optimization (4 strategies), regime detection, Monte Carlo goal
engine, volatility cones, EVT tail risk, copula tail dependence, correlation monitoring,
cointegration pairs scanning, India flows dashboard, and CSV portfolio import all work
end-to-end on real NSE data.

---

## 2. Architecture & data flow

```
yfinance (NSE/BSE tickers auto-suffixed .NS/.BO)
   → DataService (retry ×3, asyncio timeout, multi-index flattening)
      → Alpha Vantage fallback (multi-key rotation, per-key budgets, .NS→.BSE bridge)
         → SQLite cache (stock_timeseries upsert, FetchLog audit)
            → Quant Services:
               ├── AnalyticsEngine (quantstats, GARCH/EGARCH/EWMA, stress testing, factor OLS)
               ├── OptimizationService (HRP, MinVol, MaxSharpe, MinCVaR via cvxpy/scipy)
               ├── RegimeService (3-state Gaussian HMM on ^NSEI returns+21d vol)
               ├── MonteCarloService (StationaryBootstrap, Student-t, GBM goal simulation)
               ├── BenchmarkService (^NSEI daily cache)
               ├── VolatilityService (rolling quantile cones + GARCH/EWMA forecast)
               ├── TailRiskService (EVT-POT GenPareto + Student-t Copula matrix)
               ├── CorrelationService (rolling 60d avg pairwise corr + regime breaks)
               ├── CointegrationService (Engle-Granger, Johansen, OU half-life)
               ├── IndiaDataService (bhavcopy delivery %, FII/DII, Amihud illiquidity)
               ├── IndicatorsService (stockstats 13 technical indicators)
               └── CompanyDataService (fundamentals, statements, insider trades)
                  → REST /api/v1/{portfolio,data,analytics} + WebSocket /api/v1/ws/ws/{client_id}
                     → Next.js dashboard (Zustand stores + hooks + Recharts + SVG charts)
```

---

## 3. Backend services (15 total)

| Service | File | What it does |
|---|---|---|
| DataService | `data_service.py` (~730 ln) | yfinance fetch, retry, cache, batch, AV fallback |
| AnalyticsEngine | `analytics_engine.py` (~1100 ln) | Realized/forecast metrics, concentration, stress testing |
| OptimizationService | `optimization_service.py` | HRP, MinVol, MaxSharpe, MinCVaR (cvxpy/scipy) |
| RegimeService | `regime_service.py` | 3-state Gaussian HMM on ^NSEI |
| MonteCarloService | `monte_carlo_service.py` | StationaryBootstrap, Student-t, GBM simulation |
| BenchmarkService | `benchmark_service.py` | ^NSEI benchmark caching |
| VolatilityService | `volatility_service.py` | Rolling vol cones + GARCH/EWMA forecast |
| TailRiskService | `tail_risk_service.py` | EVT-POT GenPareto + Student-t Copula matrix |
| CorrelationService | `correlation_service.py` | Rolling 60d correlation + regime breaks |
| CointegrationService | `cointegration_service.py` | Engle-Granger, Johansen, OU half-life |
| IndiaDataService | `india_data_service.py` | Delivery %, FII/DII, Amihud, days-to-liquidate |
| IndicatorsService | `indicators_service.py` | stockstats 13 indicators (TradingAgents) |
| CompanyDataService | `company_data_service.py` | Fundamentals, statements, insider trades |
| AlphaVantageService | `alpha_vantage_service.py` | Multi-key rotation pool |
| CurrencyService | `currency_service.py` | USD↔INR, fixed 83.0 fallback, Indian formatting |

---

## 4. Frontend routes (16+ pages)

| Route | What it does |
|---|---|
| `/dashboard` | Summary: hero, metric cards, charts, positions table, add modal |
| `/dashboard/realized-risk` | Metrics table + rolling context |
| `/dashboard/forecast-risk` | EWMA/GARCH/EGARCH model selector, per-ticker forecasts |
| `/dashboard/factor-exposure` | Heatmap-style factor betas |
| `/dashboard/concentration` | Top-N, HHI, effective positions |
| `/dashboard/liquidity` | Score gauge, per-position liquidity |
| `/dashboard/stress-testing` | Scenario picker, stress test runner |
| `/dashboard/volatility-sizing` | Target-vol slider, recommended weights/trades |
| `/dashboard/tear-sheet` | QuantStats vs NIFTY: monthly heatmap + underwater SVG |
| `/dashboard/risk-contribution` | Euler vol + CVaR bars + sector rollup |
| `/dashboard/optimize` | Optimizer Studio: 4-strategy, weights diff, trade list |
| `/dashboard/regime` | HMM state, 120-day timeline, stability %, portfolio behavior |
| `/dashboard/monte-carlo` | Goal form + SVG fan chart + engine selector |
| `/dashboard/risk-studio` | Consolidated Euler risk + copula heatmap + vol cones |
| `/dashboard/pairs` | Cointegration scanner UI |
| `/dashboard/india-flows` | India microstructure & FII/DII institutional flows |
| `/portfolio/manage` | Full CRUD table, inline edit, currency toggle, GARCH badges |
| `/dashboard/settings` | Currency, lookback, and cache controls |

---

## 5. Development history (waves)

### Wave 1 (2026-08-25): Truth pass + test rebuild
- Wired all analytics to DB positions (`_load_portfolio_allocation`)
- Rebuilt conftest (httpx ASGITransport, isolated per-test SQLite)
- Fixed 11 product bugs (volatility sizing, stress-test indexing, CSV nulls, etc.)
- Added TradingAgents indicators/company data + Alpha Vantage fallback
- 88 tests passing

### Wave 2 (2026-08-26): Quant core goes visible
- 5 new dashboard pages (tear-sheet, risk-contribution, optimize, regime, monte-carlo)
- Monte Carlo engine (arch.bootstrap.StationaryBootstrap + Student-t)
- Dashboard home widgets (regime banner, risk drivers)
- 128 tests passing, 62% coverage

### Wave 3 (2026-08-26/27): Advanced analytics + polish
- Shipped: VolatilityService, TailRiskService, CorrelationService, CointegrationService,
  IndiaDataService
- Frontend: /dashboard/pairs, /dashboard/india-flows, portfolio importer, efficient frontier,
  risk studio canvas, PDF report trigger, settings page
- Multiple audit passes (browser verification, terminal UX, portfolio audit)
- Reached 85.36% coverage (243 tests) per session log

### Current working tree (2026-08-27)
- 22 modified + 5 untracked files uncommitted
- `uv run pytest --no-cov` yields 148 tests (146 pass, 2 fail)
- Note: test count discrepancy (148 vs session-log's 243) suggests some test files
  may have been modified or the working tree is in a transitional state

---

## 6. Test & quality status

- **Backend**: 148 tests (146 pass, 2 fail). Coverage ~62% (when run from current state).
  Failing tests have identified root causes (see QH-01):
  - `test_no_positions_404`: conftest dependency_overrides leak (no try/finally)
  - `test_contributions_sum_to_one_and_ranking`: rounding tolerance 1e-6 too tight
- **Frontend**: 35 tests pass (only MetricCard.test.tsx). Zero page/hook/store coverage.
- **CI**: Backend: ruff/mypy/pytest. Frontend steps missing. Deploy references nonexistent k8s/.

---

## 7. Active workstreams & ticket trackers

### Feature roadmap (`.scratch/advanced-analytics/`)
Original tickets t01–t23, plus t24–t32 added in Wave 3.
Resolved: t01–t11, t24–t27. Open: t12 (vol cone—may be superseded by VolatilityService),
t13–t15 (may be superseded by TailRisk/Correlation/Cointegration services), t16–t23, t28–t32.

### Browser verification audit (`.scratch/browser-verification-audit-2026/`)
Tickets BVA-01 through BVA-05. All closed.

### Terminal UX audit (`.scratch/terminal-ux-audit-2026/`)
Tickets UA-01 through UA-06. All closed.

### Portfolio audit (`.scratch/portfolio-audit-2026/`)
Tickets PA-01 through PA-03. All closed.

### Quality hardening (`.scratch/quality-hardening/`) — NEW, 2026-08-27
13 tickets from deep code audit:

| # | Name | Tier | Status |
|---|---|---|---|
| QH-01 | Fix failing tests (conftest leak + tolerance) | 🔴 Correctness | ready-for-agent |
| QH-02 | Auto-normalize weights on delete | 🔴 Correctness | ready-for-agent |
| QH-03 | GARCH/EGARCH rescaling | 🔴 Correctness | ready-for-agent |
| QH-04 | Structured error envelopes | 🔴 Correctness | ready-for-agent |
| QH-05 | WebSocket worker perf (unbounded query + N+1) | 🟡 Performance | ready-for-agent |
| QH-06 | Concurrent batch fetching | 🟡 Performance | ready-for-agent |
| QH-07 | Currency cache stampede fix | 🟡 Performance | ready-for-agent |
| QH-08 | Frontend memoization + React Compiler | 🟡 Performance | ready-for-agent |
| QH-09 | Frontend type safety pass | 🟠 Quality | ready-for-agent |
| QH-10 | SQLite upsert + unused deps cleanup | 🟠 Quality | ready-for-agent |
| QH-11 | Backend test coverage to 80% | 🔵 Testing | ready-for-agent |
| QH-12 | Frontend test foundation | 🔵 Testing | ready-for-agent |
| QH-13 | CI/CD pipeline fixes | 🔵 Testing | ready-for-agent |

---

## 8. Persisting tech debt

- Factor model: 8 of 11 factors hardcoded placeholders (analytics_engine.py)
- Fixed FX rate: USD/INR pinned at 83.0, no live feed (currency_service.py)
- Dead code: ~700-line AddPositionModal, legacy PortfolioManagement, placeholder
  useAutoRefresh in store.ts, analytics_cache table written by nothing
- Performance: GET /portfolio refreshes every position's quote sequentially via yfinance
- Frontend `any` epidemic: api.ts returns Promise<any>, stores use Map<string, any>

---

## 9. Documentation map (where future agents should look)

| File | What it contains |
|---|---|
| `CONTEXT.md` | Root domain guide: architecture, vocabulary, runbooks, gotchas |
| `AGENTS.md` | Agent configuration: issue tracker, triage labels, domain docs |
| `.scratch/project-state/current-state.md` | THIS FILE — full codebase state |
| `.scratch/session-log-2025-08-25.md` | Wave 1+2 chronology, decisions, 12 gotchas |
| `.scratch/session-log-2026-08-26.md` | Wave 3 accomplishments summary |
| `.scratch/advanced-analytics/spec.md` | Feature roadmap (P0–P6, F1–F14) |
| `.scratch/advanced-analytics/issues/` | Feature tickets (t01–t32) |
| `.scratch/quality-hardening/spec.md` | Quality hardening plan from 2026-08-27 audit |
| `.scratch/quality-hardening/issues/` | Quality tickets (QH-01 through QH-13) |
| `.scratch/browser-verification-audit-2026/` | Browser audit tickets (BVA-01–05, all closed) |
| `.scratch/terminal-ux-audit-2026/` | Terminal UX tickets (UA-01–06, all closed) |
| `.scratch/portfolio-audit-2026/` | Portfolio audit tickets (PA-01–03, all closed) |
| `RELEASE_NOTES.md` | Detailed changelogs for shipped waves |
| `instructions/project_details.md` | Original 10-step build guide (historical) |
| `instructions/doc/` | 28 historical fix/verification reports |
| `docs/agents/` | Agent protocols (issue-tracker, triage-labels, domain) |

---

## 10. Conventions & gotchas (comprehensive)

1. Tickers are uppercased; Indian normalization appends `.NS` aggressively.
2. Currency default is INR end-to-end (API, formatters, store).
3. PowerShell: no heredocs, no `&&`; write temp script files for multiline Python.
4. `uv add` on unpinned graphs can churn minutes; pin versions surgically.
5. Patch targets must match the importing namespace (from-imports bind originals).
6. Cache schema = lowercase OHLCV; yfinance raw = Title-case; normalize at boundaries.
7. Never `asyncio.run()` inside pytest tests.
8. Sum-to-1 assertions on rounded payloads need ~1e-4 tolerance, not 1e-6.
9. NSE `.info` intermittently 401s ("Invalid Crumb") → map to 503 upstream-outage.
10. `arch.bootstrap`: iterate via `bs.bootstrap(n)` generator, NOT `for x in bs`.
11. Student-t moment matching: use analytic scale·sqrt(df/(df−2)), not sample std.
12. Lucide icons: audit `icon={X}` vs imports per page.
13. conftest `dependency_overrides` must use try/finally to prevent test isolation leaks.
14. `all uv commands are pre-approved` — run non-interactively without confirmation prompts.
