# Project: FinEngine (Daisy Risk Engine) Quantitative & Production Hardening

## Architecture
- **Backend**: FastAPI / Python 3.12 (uv), SQLAlchemy + aiosqlite (WAL mode SQLite), Pydantic v2 schemas.
  - Core Math Stack: `arch`, `scipy.stats`, `statsmodels`, `cvxpy` (Clarabel solver), `stockstats`, `quantstats`, `hmmlearn`.
  - Service Layer: Dedicated domain modules under `backend/app/services/` (`volatility_service.py`, `tail_risk_service.py`, `correlation_service.py`, `cointegration_service.py`, `india_data_service.py`, `analytics_engine.py`).
  - API Routers: Mounted under `/api/v1/` (`portfolio`, `data`, `analytics`, `india`, `ws`).
- **Frontend**: Next.js 16 (App Router) / React 19 / TypeScript / Bun.
  - Styling: Tailwind CSS v4 design tokens.
  - UI State: Zustand stores (`usePortfolioStore`, `useAnalyticsStore`, `useUIStore`).
  - Visualizations: Recharts charts, Lucide icons, TanStack Table.
  - Reports: Client-side `jsPDF` institutional PDF report generator.
- **Data & Caching Layer**:
  - SQLite database `backend/data/daisy.db` with indexed tables: `portfolio_positions`, `stock_timeseries`, `analytics_cache`, `fetch_logs`, `nse_bhavcopy`, `nse_institutional_flows`, `nse_bulk_block_deals`, `nse_shareholding_patterns`.
  - Local raw NSE archive storage in `data/nse/YYYY-MM-DD/`.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Volatility Term Structure & Quantile Cone | Multi-window (10/21/63/126/252d) rolling quantiles + GARCH/EWMA forecast at `GET /api/v1/analytics/vol-cone` | M1 | ORIGINAL_REQUEST §R1 |
| F2 | EVT Peaks-Over-Threshold 99% VaR/ES | Generalized Pareto Distribution tail fit on 95% exceedance losses (`scipy.stats.genpareto`) | M1 | ORIGINAL_REQUEST §R1 |
| F3 | Copula Lower-Tail Dependence Matrix | Student-t copula lower-tail lambda parameter matrix ($N \times N$) for portfolio holdings | M1 | ORIGINAL_REQUEST §R1 |
| F4 | Rolling 60d Correlation Monitor & Regime Breaks | 60-day average pairwise correlation with historical 90th-percentile regime-break alerts | M2 | ORIGINAL_REQUEST §R2 |
| F5 | Cointegration Pairs Scanner | Engle-Granger & Johansen tests, OU mean-reversion half-life, spread z-score & SQLite cache at `GET /api/v1/analytics/coint` | M2 | ORIGINAL_REQUEST §R2 |
| F6 | NSE Bhavcopy & Delivery % Ingestion | Daily bhavcopy fetcher, delivery moving averages, and >2σ delivery accumulation anomaly detector | M3 | ORIGINAL_REQUEST §R3 |
| F7 | Institutional Flows, Bulk Deals & Pledges | FII/DII net flows, bulk/block deals, quarterly promoter shareholding & pledge delta alerts | M3 | ORIGINAL_REQUEST §R3 |
| F8 | Liquidity Limits & Sizing Engine | 20d ADV/ADTV, days-to-liquidate @ 10% and 20% participation, Amihud illiquidity, max sane position limits | M3 | ORIGINAL_REQUEST §R3 |
| F9 | Cointegration Pairs UI (`/pairs`) | Ranked table with p-values, half-lives, z-scores, and interactive spread chart | M4 | ORIGINAL_REQUEST §R4 |
| F10 | India Flows Dashboard UI (`/india-flows`) | 30d FII/DII net bars, delivery % anomaly flags (>2σ), bulk/block deals feed, promoter pledge cards | M4 | ORIGINAL_REQUEST §R4 |
| F11 | Volatility Cone & Copula Panels | Vol cone quantile band chart on `/forecast-risk`, Copula heatmap & EVT VaR card on `/risk-contribution` | M4 | ORIGINAL_REQUEST §R4 |
| F12 | Client-Side PDF Portfolio Review Export | Institutional multi-page tear-sheet PDF via jsPDF with live holdings, risk, regime, and Monte Carlo | M4 | ORIGINAL_REQUEST §R4 |
| F13 | Zero-Mock & Pseudo-Random Purge | Delete all fabricated MetricCard deltas, hardcoded mock fallback objects, and replace Math.random with crypto.randomUUID | M4 | ORIGINAL_REQUEST §R4 |
| F14 | Backend Test Hardening & 80%+ Coverage | Resolve 19 test errors, enforce isolated SQLite fixtures, add comprehensive quant tests, enforce 80%+ gate | M5 | ORIGINAL_REQUEST §R5 |
| F15 | Frontend TypeScript & Vitest Verification | Zero type errors (`bun x tsc --noEmit`) and passing Vitest test suite (`bun run test:run`) | M5 | ORIGINAL_REQUEST §R5 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M0 | E2E Testing Track | Requirement-driven test harness, runner, and Tiers 1-4 test suites (`TEST_READY.md`) | none | IN_PROGRESS |
| M1 | Volatility & Tail Risk Suite | `volatility_service.py`, `tail_risk_service.py`, `GET /api/v1/analytics/vol-cone`, `GET /api/v1/analytics/tails` | none | PLANNED |
| M2 | Correlation & Cointegration | `correlation_service.py`, `cointegration_service.py`, `GET /api/v1/analytics/correlation-stability`, `GET /api/v1/analytics/coint` | none | PLANNED |
| M3 | NSE Microstructure & Liquidity | `india_data_service.py`, database models, `GET /api/v1/analytics/liquidity`, `/api/v1/india/*` | none | PLANNED |
| M4 | Frontend Studio & Zero-Mock Purge | `/pairs`, `/india-flows`, Vol Cone & Tail heatmap panels, jsPDF export, zero-mock purge | M1, M2, M3 | PLANNED |
| M5 | 80%+ Coverage Gate & Verification | 100% E2E test pass, pytest 80%+ coverage gate (`pytest --cov=app --cov-fail-under=80`), frontend tsc/vitest pass | M0, M1, M2, M3, M4 | PLANNED |

## Interface Contracts

### M1: Volatility & Tail Risk
- `GET /api/v1/analytics/vol-cone?tickers={tickers}&lookback_days=756`
  - Returns: `VolConeResponse { symbol, as_of, windows: [ { window_days, min, p25, median, p75, max, current_realized } ], current_forecast: { model, annualized_vol, horizon_days, percentile_rank, valuation } }`
- `GET /api/v1/analytics/tails?tickers={tickers}&lookback_days=756`
  - Returns: `TailRiskResponse { as_of, evt_var: { confidence_level, evt_pot_var_99, evt_pot_es_99, historical_var_99, historical_es_99, threshold_u, gpd_shape_xi, gpd_scale_beta, exceedances_count, total_observations, is_fat_tailed }, tail_dependence_matrix: { tickers, matrix, high_tail_risk_pairs } }`

### M2: Correlation Stability & Cointegration
- `GET /api/v1/analytics/correlation-stability?tickers={tickers}&lookback_days=756`
  - Returns: `CorrelationStabilityResponse { as_of, current_avg_correlation, historical_threshold_90th, historical_threshold_75th, historical_median, is_regime_break, alert_level, message, series }`
- `GET /api/v1/analytics/coint?tickers={tickers}&p_value_threshold=0.05&max_half_life=60`
  - Returns: `CointScannerResponse { as_of, universe_size, scanned_pairs_count, cointegrated_pairs_count, pairs: [ { ticker_a, ticker_b, engle_granger_pvalue, engle_granger_tstat, is_cointegrated, hedge_ratio_beta, intercept_alpha, ou_half_life_days, ou_reversion_speed_theta, current_spread_zscore, johansen_cointegrated, last_price_a, last_price_b, signal } ] }`

### M3: India Microstructure & Liquidity
- `GET /api/v1/analytics/liquidity`
  - Returns: `LiquidityMetricsResponse { overall_score, portfolio_days_to_liquidate_20pct, high_liquidity_pct, positions: [ { ticker, quantity, market_value, adv_20d_shares, adtv_20d_inr, days_to_liquidate_10pct, days_to_liquidate_20pct, amihud_score, max_sane_value_inr, capacity_utilization_pct, risk_category, illiquid_flag } ] }`
- `GET /api/v1/india/flows/fii-dii?days=30`
  - Returns: `FIIDIISummaryResponse { as_of, cumulative_fii_crores, cumulative_dii_crores, institutional_trend, history: [ { date, fii_buy, fii_sell, fii_net, dii_buy, dii_sell, dii_net } ] }`
- `GET /api/v1/india/delivery-anomalies?tickers={tickers}`
  - Returns: `DeliveryAnomaliesResponse { as_of, anomalies: [ { symbol, date, close, deliv_per, deliv_per_20d_mean, deliv_per_20d_std, z_score, is_accumulation } ] }`

## Code Layout
```
backend/
├── app/
│   ├── api/
│   │   ├── analytics.py        # Vol cone, tails, correlation, coint, liquidity
│   │   ├── india.py            # FII/DII flows, delivery anomalies, bulk deals, shareholding
│   │   ├── portfolio.py        # Position management
│   │   ├── data.py             # Market data & quotes
│   │   └── websocket.py        # Live database-backed updates
│   ├── db/
│   │   └── database.py         # Async SQLite engine & init_db()
│   ├── models/
│   │   ├── database.py         # SQLAlchemy models (Positions, Bhavcopy, Flows, Deals, Patterns)
│   │   └── schemas.py          # Pydantic DTOs
│   └── services/
│       ├── volatility_service.py     # Multi-window vol cone & GARCH overlay
│       ├── tail_risk_service.py      # EVT-POT 99% VaR/ES & Copula Tail matrix
│       ├── correlation_service.py    # Rolling 60d correlation & regime breaks
│       ├── cointegration_service.py  # Engle-Granger, Johansen, OU half-life & caching
│       ├── india_data_service.py     # NSE session warmup, raw caching, bhavcopy & flow parser
│       ├── analytics_engine.py       # ADV, DTL @ 10%/20%, Amihud ILLIQ, risk metrics
│       └── data_service.py           # yfinance & market data
└── tests/
    ├── conftest.py                   # Isolated SQLite per-test database fixture
    ├── test_volatility_cone.py       # Volatility cone & GARCH tests
    ├── test_tail_risk.py             # EVT-POT & Copula tests
    ├── test_correlation_stability.py # Rolling correlation tests
    ├── test_cointegration.py         # Engle-Granger, Johansen & OU half-life tests
    ├── test_india_microstructure.py  # Bhavcopy, flows, deals & liquidity tests
    └── test_coverage_*.py            # Full coverage suite (>80% gate)

frontend/
├── src/
│   ├── app/
│   │   ├── dashboard/
│   │   │   ├── page.tsx               # Overview with live metrics
│   │   │   ├── forecast-risk/page.tsx # Forecast risk + Volatility Cone panel
│   │   │   ├── risk-contribution/page.tsx # Tail risk & Copula heatmap
│   │   │   ├── liquidity/page.tsx     # ADV & days-to-liquidate metrics
│   │   │   ├── factor-exposure/page.tsx # Purged fake deltas
│   │   │   └── stress-testing/page.tsx  # Purged fake deltas
│   │   ├── pairs/page.tsx             # Cointegration pairs scanner view
│   │   └── india-flows/page.tsx       # India market microstructure dashboard
│   ├── components/
│   │   ├── layout/Sidebar.tsx         # Navigation links
│   │   ├── analytics/VolConeChart.tsx # Volatility Cone multi-window chart
│   │   ├── analytics/TailCopulaHeatmap.tsx # Tail-dependence matrix heatmap
│   │   └── pairs/SpreadChart.tsx      # Cointegration spread & z-score chart
│   └── lib/
│       ├── api.ts                     # API client endpoints
│       └── export.ts                  # jsPDF institutional portfolio review generator
```
