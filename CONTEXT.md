# Daisy Risk Engine — Project Context & System Documentation

**Daisy Risk Engine** (`finengine`) is a personal, single-user Bloomberg-grade financial risk analytics platform and decision terminal focused on Indian equity portfolios (NSE/BSE).

---

## 1. Core Philosophy & Value Proposition

- **The "Not on Free Sites" Filter**: Free platforms (TradingView, Screener.in, Chartink, Yahoo) already excel at simple candlestick charts, RSI/MACD, screening ratios (P/E, ROE), and basic pie charts. This engine **only builds pro-grade capabilities that free platforms lack**:
  - Portfolio-level factor and risk decomposition on *actual user holdings*
  - Mathematical portfolio optimization (HRP, Min Vol, Max Sharpe, Min CVaR) under realistic constraints
  - Market regime detection (Gaussian Hidden Markov Models on ^NSEI)
  - Fat-tailed Monte Carlo goal forecasting (Politis-Romano Stationary Bootstrap & Student-t)
  - EVT tail-risk modeling & Copula tail-dependence matrices
  - Indian market microstructure (delivery %, FII/DII flow anomalies, bulk/block deals)
- **Library-First Architecture**: Avoid hand-rolling standard quantitative math; leverage public scipy, cvxpy, hmmlearn, arch, and quantstats.

---

## 2. Technology Stack & Runtime

| Layer | Technologies & Libraries | Port / Mode |
|---|---|---|
| **Backend** | Python 3.12, FastAPI 0.120+, `uv`, SQLite (async SQLAlchemy + `aiosqlite`), `scipy`, `numpy`, `cvxpy`, `arch`, `quantstats`, `hmmlearn`, `stockstats`, `yfinance`, `httpx` | `http://localhost:8000/api/v1` |
| **Frontend** | Bun 1.x, Next.js 16 (App Router), React 19, TypeScript 5.7+, Tailwind CSS, Recharts, Zustand 5.0, TanStack Table & Query, Lucide React, Vitest | `http://localhost:3000` (Dev) / `:3001` (Verify) |
| **Data Vendors** | Primary: `yfinance` (auto-suffixed `.NS`/`.BO`), Fallback: Alpha Vantage (multi-key rotation pool) | Cached in SQLite `stock_timeseries` |

---

## 3. System Architecture & Data Flow

```
yfinance (NSE: .NS, BSE: .BO)  ──[3 retries + timeout]──┐
                                                         ├──► DataService ──► SQLite (`stock_timeseries` + `fetch_logs`)
Alpha Vantage (Multi-Key Pool) ──[Automatic Fallback]───┘           │
                                                                   ▼
                                                         Analytics & Quant Services
                                  ┌────────────────────────────────┴────────────────────────────────┐
                                  ▼                                                                 ▼
                         AnalyticsEngine                                                Specialized Quant Services
                   (QuantStats Tear-Sheet, Realized,                              (Optimization, HMM Regime, Monte Carlo,
                    Forecast Risk, Factor Exposures)                               Indicators, Company Data, Benchmark)
                                  │                                                                 │
                                  └────────────────────────────────┬────────────────────────────────┘
                                                                   ▼
                                                      FastAPI REST & WebSocket APIs
                                                    (`/api/v1/{portfolio,data,analytics,ws}`)
                                                                   │
                                                                   ▼
                                                        Next.js 16 Dashboard UI
                                            (Zustand Stores, TanStack Query, Recharts, SVG)
```

---

## 4. Codebase Directory Structure

```
finengine/
├── .agents/skills/           # Custom agent skills (caveman, brandkit, impeccable, etc.)
├── .scratch/                 # Local markdown issue tracking & project session logs
│   ├── project-state/        # Deep codebase audits (`current-state.md`)
│   ├── advanced-analytics/   # Advanced analytics specification & ticket tracker
│   │   ├── spec.md           # Product spec, decision maps, and filter rules
│   │   └── issues/           # Tickets 01 through 23 (status, implementation, verification)
│   └── session-log-2025-08-25.md # Session chronology, key decisions, and historical context
├── backend/                  # FastAPI Application
│   ├── app/
│   │   ├── api/              # Routers: `portfolio.py`, `data.py`, `analytics.py`, `websocket.py`
│   │   ├── db/               # Async database setup (`database.py`)
│   │   ├── models/           # SQLAlchemy models (`database.py`) & Pydantic schemas (`schemas.py`)
│   │   ├── services/         # Domain services:
│   │   │   ├── analytics_engine.py      # Core realized/forecast metrics, factor OLS, stress testing
│   │   │   ├── optimization_service.py  # HRP, Min Vol, Max Sharpe, Min CVaR via cvxpy/scipy
│   │   │   ├── regime_service.py        # 3-state Gaussian HMM on NIFTY returns + 21d vol
│   │   │   ├── monte_carlo_service.py   # StationaryBootstrap & Student-t goal simulation
│   │   │   ├── benchmark_service.py     # ^NSEI benchmark data ingestion & caching
│   │   │   ├── indicators_service.py    # stockstats indicators (TradingAgents adaptation)
│   │   │   ├── company_data_service.py  # Fundamentals, statements, insider trades
│   │   │   ├── alpha_vantage_service.py # Rotating multi-key API client with budget tracking
│   │   │   ├── data_service.py          # yfinance market data fetcher & SQLite cache
│   │   │   └── currency_service.py      # USD/INR currency conversion and Indian formatting
│   │   └── config.py         # Pydantic Settings (env configurations)
│   ├── data/                 # SQLite storage (`daisy.db`)
│   ├── tests/                # Pytest suites with async fixtures and isolated test DB
│   ├── main.py               # FastAPI application entrypoint and middleware
│   └── pyproject.toml        # Dependencies and tool configurations
├── frontend/                 # Next.js 16 Client
│   ├── src/
│   │   ├── app/              # App Router pages:
│   │   │   ├── dashboard/    # Main overview, realized-risk, forecast-risk, factor-exposure,
│   │   │   │                 # concentration, liquidity, stress-testing, volatility-sizing,
│   │   │   │                 # tear-sheet, risk-contribution, optimize, regime, monte-carlo
│   │   │   └── portfolio/    # Portfolio management (`manage/page.tsx`)
│   │   ├── components/       # Layout, Charts, Portfolio tables, MetricCards, Modals
│   │   ├── hooks/            # `useAnalytics`, `useRealTime`, `usePortfolioAnalytics`
│   │   ├── lib/              # `api.ts` (Axios client), `store.ts` (Zustand), `export.ts`, `websocket.ts`
│   │   ├── types/            # TypeScript schemas mirroring backend DTOs
│   │   └── test/             # Vitest test setup and component tests
│   └── package.json          # Frontend dependencies & Bun scripts
├── docs/                     # Agent guides (`docs/agents/`) and privacy guides
├── instructions/             # Origin guide (`project_details.md`) and historical verification reports
├── AGENTS.md                 # Agent configuration guidelines
└── RELEASE_NOTES.md          # Comprehensive release notes and changelogs
```

---

## 5. Domain Concepts & Vocabulary

- **Holding / Position**: A specific equity investment (`portfolio_positions` table) identified by a ticker (e.g., `RELIANCE.NS`), holding quantity, buy price, current market price, and portfolio weight.
- **Euler Risk Contribution**: Decomposes total portfolio volatility into additive component contributions: \(\sum_i \text{RC}_i = \sigma_p\). Used to detect which stock is the primary risk driver regardless of nominal weight.
- **Hierarchical Risk Parity (HRP)**: Machine-learning-based portfolio optimization using hierarchical tree clustering on correlation distance matrices, avoiding matrix inversion instability.
- **Gaussian HMM Regime**: 3-state Hidden Markov Model (`Calm Bull`, `Volatile / Correction`, `Crisis`) fit on NIFTY 50 (^NSEI) log-returns and 21-day realized volatility.
- **Stationary Bootstrap**: Politis & Romano block-resampling technique that preserves autocorrelation and volatility clustering in financial return series.
- **Student-t Innovation Engine**: Fat-tailed simulation modeling kurtosis by fitting degrees of freedom (\(\nu\)) directly from historical asset returns with analytic moment scaling.

---

## 6. Project Status & Feature Map

### Shipped & Verified
- **Holdings-Truth Plumbing (F1 / t01)**: All analytics endpoints read user DB positions dynamically with strict quantity source-of-truth.
- **QuantStats Tear-Sheet (F2 / t06)**: `/dashboard/tear-sheet` with monthly returns heatmap and underwater drawdown curves vs NIFTY.
- **Euler Risk Contribution (F3 / t07)**: `/dashboard/risk-contribution` with volatility and CVaR tail attributions, plus sector rollups.
- **Optimizer Studio (F4 / t08, t09, t30)**: `/dashboard/optimize` supporting HRP, Min Vol, Max Sharpe, Min CVaR, and Black-Litterman Bayesian optimization with subjective view tilts.
- **Walk-Forward Strategy Backtester (t32)**: `BacktestService` (`POST /api/v1/analytics/backtest`) simulating out-of-sample rolling rebalances with transaction cost friction and drawdowns.
- **Regime Engine (F5 / t10)**: `/dashboard/regime` with 120-day regime history, stability index, and portfolio behavior under each state.
- **Monte Carlo Goal Engine (F6 / t11)**: `/dashboard/monte-carlo` with GBM, Student-t, and Stationary Bootstrap engines with interactive target/horizon inputs.
- **Volatility Term Structure & Cones (F7 / t12)**: `VolatilityService` computing 10/21/63/126/252-day rolling realized vol quantile bands with GARCH(1,1) and RiskMetrics EWMA forecasts.
- **Extreme Value Theory & Tail Dependence (F8 / t13)**: `TailRiskService` computing 99% EVT-POT (Peaks-Over-Threshold) VaR/Expected Shortfall via `scipy.stats.genpareto` and bivariate Student-t Copula lower-tail crash dependence matrix.
- **Correlation Stability Monitor (F9 / t14)**: `CorrelationService` computing rolling 60-day average pairwise correlation with historical 90th-percentile diversification breakdown alerts.
- **Cointegration Pairs Scanner (F10 / t15)**: `CointegrationService` executing Engle-Granger and Johansen cointegration tests with Ornstein-Uhlenbeck mean-reversion speed/half-life estimation and spread z-scores.
- **Technical Indicators & Company Data (t21)**: stockstats engine (13 indicators) + fundamentals/financials/insider trades.
- **Alpha Vantage Fallback (t22)**: In-process multi-key rotation pool with rate-limit budget tracking.
- **Backend Test Suite Hardening (80%+ Gate Reached)**: 249/249 tests passing (0 failures), 84.98% total line coverage across the entire backend.
- **Frontend Test Suite (Vitest Foundation)**: 60/60 unit and component tests passing with zero TypeScript errors.
- **Production Hardening (QH-01 to QH-13)**: Native SQLite upserts, concurrent batch fetching, frontend memoization, type-safe API responses, structured error handling, and robust GitHub Actions CI workflow.

---

## 7. Current Open Tickets & Roadmap (TODOs)

The ongoing and planned tasks are tracked as local markdown issues under `.scratch/portfolio-audit-2026/issues/` and `.scratch/advanced-analytics/issues/`:

### Priority 0: Browser Quantitative Verification & Ad-Hoc Fixes (`.scratch/browser-verification-audit-2026/`)
| Ticket | Name | Status | Summary / Scope |
|---|---|---|---|
| **BVA-01** | Fix Backend `total_weight` NameError 500 | `closed` | Fix `NameError: name 'total_weight' is not defined` in `portfolio.py:130` unblocking `/dashboard` and `/portfolio/manage` |
| **BVA-02** | Fix Risk Studio Copula Matrix & Metrics | `closed` | Fix copula response key mapping (rendering schema keys as tickers) and bind EVT VaR / ES metric cards |
| **BVA-03** | Fix Tear-Sheet Monthly Returns Grid | `closed` | Fix empty monthly return cells on `/dashboard/tear-sheet` by formatting month returns correctly |
| **BVA-04** | Fix Volatility Sizing Risk Parity Math | `closed` | Invert vol allocation ($w_i \propto 1/\sigma_i$) so higher vol assets receive lower weights, and format Total Positions integer |
| **BVA-05** | Fix Liquidity Currency & Market Cap | `closed` | Change `$` to `₹` and compute market cap from Screener.in fundamentals / price * shares on `/dashboard/liquidity` |
| **BVA-06** | Fix Add Position Zero-State Auto-Weight | `closed` | Guarantee $100.00\%$ initial weight on empty portfolio and expand ticker regex for all NSE/BSE scrip formats |
| **BVA-07** | Ground Diversification Score in HHI | `closed` | Ground Health Summary in true Herfindahl concentration math ($HHI$), strictly rendering $0\%$ for single-stock portfolios |
| **BVA-08** | Deduplicate Factor Exposure Cards | `closed` | Clean up duplicate $R^2$ / Adjusted $R^2$ cards and eliminate placeholder synthetic deltas |

### Priority 1: Quality Hardening & Engineering Robustness (`.scratch/quality-hardening/`)
| Ticket | Name | Status | Summary / Scope |
|---|---|---|---|
| **QH-01** | Fix Failing Tests & Teardown Leaks | `closed` | Ensure clean pytest run (verified: 248/248 tests passing across the backend) |
| **QH-02** | Auto-Normalize Weights on Position Delete | `ready-for-agent` | Normalize remaining portfolio positions to sum to 1.0 when a position is deleted |
| **QH-03** | GARCH/EGARCH Return Rescaling | `ready-for-agent` | Rescale returns ($\times 100$) before GARCH optimizer fitting to prevent convergence warnings |
| **QH-04** | Structured Error Envelopes in Analytics | `ready-for-agent` | Standardize API error payloads and prevent silent failure masking across quant endpoints |
| **QH-05** | WebSocket Background Worker Performance | `ready-for-agent` | Eliminate redundant full database queries on tick intervals in WebSocket streaming worker |
| **QH-06** | Concurrent Batch Data Fetching | `ready-for-agent` | Parallelize yfinance / Alpha Vantage batch fetching in `data_service.py` and `portfolio.py` |
| **QH-07** | Currency Service Cache Stampede Fix | `ready-for-agent` | Add mutex / single-flight locking for USD/INR live FX quote refresh |
| **QH-08** | Frontend Memoization & Re-render Polish | `ready-for-agent` | Wrap heavy Recharts/SVG components in `useMemo`/`memo` to minimize re-render cycles |
| **QH-09** | Frontend Type Safety & `any` Elimination | `ready-for-agent` | Replace `Promise<any>` in `lib/api.ts` with strict TypeScript response types |
| **QH-10** | SQLite Upsert Robustness & Dep Cleanup | `ready-for-agent` | Clean up unused dependencies and ensure robust `sqlite_upsert` index handling |
| **QH-11** | Backend Test Coverage Push (80%+ Gate) | `ready-for-agent` | Add deterministic mocked tests for uncovered routes to permanently exceed 80% coverage |
| **QH-12** | Frontend Test Foundation (Vitest) | `ready-for-agent` | Expand Vitest component tests to cover every primary dashboard page route |
| **QH-13** | CI/CD Pipeline & GitHub Action Fixes | `ready-for-agent` | Modernize GitHub Actions workflow for non-interactive `uv` and `bun` execution |

### Priority 2: Terminal UX & Data-Binding Audit (`.scratch/terminal-ux-audit-2026/`)
| Ticket | Name | Status | Summary / Scope |
|---|---|---|---|
| **UA-01** | Fix TanStack Table `row.original` Accessors | `closed` | Fix `NaN%` & blank rows across 7 dashboard analytics tables by reading `row.original` |
| **UA-02** | Create `/dashboard/settings` Page | `closed` | Build dedicated Settings page resolving HTTP 404 with currency, lookback, and cache controls |
| **UA-03** | Fix Risk Studio Double Layout | `closed` | Remove inner `<DashboardLayout>` in `risk-studio/page.tsx` eliminating duplicate sidebars |
| **UA-04** | Fix Forecast Unwrap & Negative P&L Signs | `closed` | Handle unnested API payload on `/portfolio/manage` and retain algebraic `-` on losses |
| **UA-05** | Standardize Currency (INR ₹) & Notation | `closed` | Standardize dynamic `₹`/`$`, format India Flows ADV in Crores (`Cr`), fix `0.95%` in Stress Test |
| **UA-06** | Wire Dashboard Quick Action Navigations | `closed` | Connect Quick Action buttons to instantaneous Next.js client router navigations |

### Priority 3: Portfolio Audit & Microstructure Polish (`.scratch/portfolio-audit-2026/`)
| Ticket | Name | Status | Summary / Scope |
|---|---|---|---|
| **PA-01** | Wire Vol-Cone & Tails Contract Routes | `closed` | Mount dedicated route aliases `/api/v1/analytics/vol-cone` and `/tails` to match full external contract spec |
| **PA-02** | Defensive Timeseries Date Alignment | `closed` | Ensure inner-join index alignment on cross-asset return series with mismatched holiday calendars |
| **PA-03** | Screener.in Fundamentals Enrichment | `closed` | Enrich portfolio summary cards with live Screener.in ratios (Market Cap, TTM P/E, ROE, 52W High/Low) |

### Priority 4: Terminal UI & Operational Automation (`.scratch/advanced-analytics/`)
| Ticket | Name | Status | Summary / Scope |
|---|---|---|---|
| **t24** | Portfolio CSV/XLSX Importer UI | `closed` | Drag-and-drop dropzone for Zerodha/Groww/AngelOne CSVs pre-filling `POST /portfolio/bulk_add` |
| **t25** | Interactive Efficient Frontier Curve | `closed` | Recharts/SVG Markowitz frontier scatter curve with current vs optimal asset overlays |
| **t26** | Consolidated Risk Studio Canvas | `closed` | `/dashboard/risk-studio` linking Euler risk, copula heatmap, and vol cones side-by-side |
| **t27** | One-Click PDF Report Header Trigger | `closed` | Global header trigger downloading multi-page branded PDF tear-sheet via jsPDF |
| **t28** | Scheduled Post-Market NSE Ingestion Cron | `deferred` | Background scheduler (18:30 IST) pulling daily bhavcopy, delivery %, and FII/DII net flows |
| **t29** | Promoter Pledge & Bulk Deal Scraper | `needs-info` | Ingest quarterly shareholding pattern XMLs & track promoter pledge delta alerts |
| **t30** | Black-Litterman Bayesian Optimizer | `ready-for-agent` | Blending market equilibrium priors with subjective investor return views |
| **t31** | Options Greeks & IV Surface Tracking | `needs-info` | Net portfolio delta/gamma/vega exposures and implied volatility smile surface |
| **t32** | Walk-Forward Strategy Backtester | `ready-for-agent` | Rolling historical simulation of rebalancing strategies vs buy-and-hold |

---

## 8. Development Runbook & Commands

### Backend (`backend/`)
```bash
# Install dependencies
uv sync --extra dev

# Run development server
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Run test suite
uv run pytest --no-cov

# Run full test suite with coverage
uv run pytest
```

### Frontend (`frontend/`)
```bash
# Install dependencies
bun install

# Run dev server
bun run dev --port 3000

# Run Vitest test suite
bun run test:run
```

---

## 9. Critical Engineering Gotchas

1. **PowerShell Windows Execution**: Avoid Unix-specific bash syntax (no heredocs, no inline `&&`); for multi-line scripts, write temporary `.py` files.
2. **Package Pinning with `uv`**: Bare `uv add` can trigger broad resolution churn on Windows; always specify pinned versions and verify C-extension binary wheels (e.g. `scipy`, `cvxpy`).
3. **Database Column Casing**: Cache stores lowercase columns (`open`, `high`, `low`, `close`, `volume`), while raw yfinance returns TitleCase (`Close`, `Volume`). Always normalize at ingestion boundaries.
4. **Mocking & Async Seams**: In pytest, never call `asyncio.run()` inside tests. Set every awaited mock return value explicitly on `AsyncMock`.
5. **Payload Precision**: Quant calculations round JSON outputs to 6 decimal places; floating-point assertions checking sum-to-1 properties must use a tolerance of `~1e-4` rather than `1e-6`.
6. **Yahoo Finance Crumb Auth**: Upstream Yahoo `.info` occasionally returns 401 ("Invalid Crumb"); backend gracefully maps this to a `503 Service Unavailable` with upstream outage semantics.
7. **Mixed Inception Dates & Return Alignment**: When combining multiple asset timeseries with different history lengths or newly listed ETFs (e.g. `NIFTYIETF.NS`), avoid calling `.dropna()` across the wide DataFrame as it drops all rows prior to the newest asset's inception date. Always use defensive `.ffill().bfill()` and `.fillna(0.0)` to preserve the full historical window for other assets.
8. **Next.js Memory Footprint (Dev vs Prod)**: In dev mode (`next dev`), Next.js maintains active AST parse trees and Turbopack compiler caches in RAM (~1GB). For lightweight runtime, build static bundles via `bun run build` and serve using `bun run start` (~150MB).
9. **GARCH Analytical Expectation**: For real-time multi-asset volatility forecasting, evaluate GARCH(1,1) closed-form analytical formulas (`method='analytic'`) rather than Monte Carlo path simulations (`simulations=1000`) to avoid CPU thread spikes during concurrent requests.
10. **Insufficient Historical Depth & Active Asset Calculation**: When calculating standalone risk ratios (Sharpe, Sortino, annual return, volatility) for individual positions in a portfolio with mixed histories, calculate metrics on each asset's raw *active* trading history rather than the zero-padded multi-asset matrix. For newly listed assets with $N < 10$ trading days, constrain the Sharpe ratio to `0.00` and emit UI warnings to prevent denominator collapse artifacts.
11. **Multi-Day Value-at-Risk & Horizon Scaling**: Analytical VaR and CVaR for a multi-day forecast horizon $h$ must explicitly scale with the square root of time: $\text{VaR}_h = - \sigma_{\text{ann}} \times 1.645 \times \sqrt{\frac{h}{252}}$ and $\text{CVaR}_h = - \sigma_{\text{ann}} \times 2.06 \times \sqrt{\frac{h}{252}}$. Never omit the $\sqrt{h}$ factor, as doing so leaves 30-day downside risk invariant to 1-day estimates.
12. **Daily vs Annualized Alpha Reporting**: In single-factor CAPM OLS regressions, the regression intercept $\alpha_{\text{daily}}$ represents daily excess return. In UI reporting, always compute and display both annualized alpha ($\alpha_{\text{ann}} = \alpha_{\text{daily}} \times 252$) and percentage daily excess returns (+0.160%/d) to avoid user confusion between basis-point daily figures and annualized performance expectations.
13. **Stress Testing Multi-Factor Sector Elasticity & Circuit Winsorization**: When computing constituent drawdowns across macro stress test scenarios (Market Crash $-35\%$, Interest Rate Shock $-15\%$, Volatility Spike $-22\%$, Tech Correction $-18\%$), do not rely solely on unadjusted univariate volatility. First, winsorize daily returns to $[-20\%, +20\%]$ to eliminate unadjusted split/bonus data spikes. Second, apply sector-specific macroeconomic elasticity multipliers (Healthcare $0.25-0.55\times$, Utilities $0.20-0.70\times$, Tech $1.10-1.80\times$, Financials $0.50-1.50\times$, Cyclicals $0.60-1.55\times$) with active non-zero volatility fine-tuning. This prevents artificial $-98\%$ bankruptcy wipeout artifacts and flat $-26.3\%$ clamp clusters, producing realistic institutional stress profiles.
14. **GARCH & Volatility Forecasting Return Winsorization**: When evaluating GARCH, EGARCH, or EWMA statistical models on historical daily timeseries, always clean and winsorize daily returns to statutory equity price bands (`clean_returns.clip(lower=-0.20, upper=0.20)`). Unadjusted historical stock splits, bonus issues, or single-day data feed spikes can cause unconstrained autoregressive conditional variance to explode to multi-thousand percent annualized figures (e.g. 2600%), which artificially destroys portfolio Value-at-Risk calculations.





