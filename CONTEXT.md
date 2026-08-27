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
- **Optimizer Studio (F4 / t08, t09)**: `/dashboard/optimize` supporting HRP, Min Vol, Max Sharpe, and Min CVaR with current vs recommended trade lists.
- **Regime Engine (F5 / t10)**: `/dashboard/regime` with 120-day regime history, stability index, and portfolio behavior under each state.
- **Monte Carlo Goal Engine (F6 / t11)**: `/dashboard/monte-carlo` with GBM, Student-t, and Stationary Bootstrap engines with interactive target/horizon inputs.
- **Volatility Term Structure & Cones (F7 / t12)**: `VolatilityService` computing 10/21/63/126/252-day rolling realized vol quantile bands with GARCH(1,1) and RiskMetrics EWMA forecasts.
- **Extreme Value Theory & Tail Dependence (F8 / t13)**: `TailRiskService` computing 99% EVT-POT (Peaks-Over-Threshold) VaR/Expected Shortfall via `scipy.stats.genpareto` and bivariate Student-t Copula lower-tail crash dependence matrix.
- **Correlation Stability Monitor (F9 / t14)**: `CorrelationService` computing rolling 60-day average pairwise correlation with historical 90th-percentile diversification breakdown alerts.
- **Cointegration Pairs Scanner (F10 / t15)**: `CointegrationService` executing Engle-Granger and Johansen cointegration tests with Ornstein-Uhlenbeck mean-reversion speed/half-life estimation and spread z-scores.
- **Technical Indicators & Company Data (t21)**: stockstats engine (13 indicators) + fundamentals/financials/insider trades.
- **Alpha Vantage Fallback (t22)**: In-process multi-key rotation pool with rate-limit budget tracking.
- **Backend Test Suite Hardening (80%+ Gate Reached)**: 240/240 tests passing (0 failures), 85.61% total line coverage across the entire backend.
- **Frontend Consolidation (t03, t04)**: Unified Axios client, normalized rebalancing, and dark mode UI overhaul (35/35 Vitest passing, zero TypeScript errors).

---

## 7. Current Open Tickets & Roadmap (TODOs)

The ongoing and planned tasks are tracked as local markdown issues under `.scratch/advanced-analytics/issues/`:

| Ticket | Name | Status | Summary / Scope |
|---|---|---|---|
| **t24** | Portfolio CSV/XLSX Importer UI | `ready-for-agent` | Drag-and-drop dropzone for Zerodha/Groww/AngelOne CSVs pre-filling `POST /portfolio/bulk_add` |
| **t25** | Interactive Efficient Frontier Curve | `ready-for-agent` | Recharts/SVG Markowitz frontier scatter curve with current vs optimal asset overlays |
| **t26** | Consolidated Risk Studio Canvas | `ready-for-agent` | `/dashboard/risk-studio` linking Euler risk, copula heatmap, and vol cones side-by-side |
| **t27** | One-Click PDF Report Header Trigger | `ready-for-agent` | Global header trigger downloading multi-page branded PDF tear-sheet via jsPDF |
| **t28** | Scheduled Post-Market NSE Ingestion Cron | `ready-for-agent` | Background scheduler (18:30 IST) pulling daily bhavcopy, delivery %, and FII/DII net flows |
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
