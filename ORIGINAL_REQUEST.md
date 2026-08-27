# Original User Request

## 2026-08-26T15:56:14Z

# Teamwork Project: FinEngine (Daisy Risk Engine) Quantitative & Production Hardening

Daisy Risk Engine is an institutional-grade, Bloomberg-style personal portfolio risk and quantitative analytics terminal for Indian equities (NSE), built with FastAPI/Python 3.12 (uv) and Next.js 16/React 19 (Bun). This task executes the full remaining advanced quantitative analytics, Indian market microstructure, test coverage hardening (reaching 80%+ coverage gate), and production polish roadmap.

Working directory: c:/sukanta/coding/finengine
Integrity mode: development

## Requirements

### R1. Advanced Volatility Term Structure & Tail Risk Suite
Implement the volatility cone analytics endpoint (`GET /api/v1/analytics/vol-cone`) providing 10/21/63/126/252-day historical quantile bands alongside GARCH/EWMA forecasts. Implement Extreme Value Theory (EVT) Peaks-Over-Threshold (POT) VaR/Expected Shortfall at the 99% level (via `scipy.stats.genpareto`) and compute the pairwise lower-tail dependence copula matrix for portfolio holdings.

### R2. Correlation Stability & Cointegration Pairs Scanner
Build the rolling 60-day average pairwise correlation monitor with historical 90th-percentile regime-break alerts. Build the cointegration scanner (`GET /api/v1/analytics/coint`) executing Engle-Granger and Johansen cointegration tests with Ornstein-Uhlenbeck mean-reversion half-life estimation over portfolio holdings and watchlist tickers, caching pairwise calculations to ensure snappy response times.

### R3. India Market Microstructure & ADV Liquidity Limits
Build the daily NSE data ingestion pipeline (`app/services/india_data_service.py`) to fetch, parse, and locally cache (`data/nse/`) daily bhavcopy delivery percentages, FII/DII net institutional flows, bulk/block deals, and quarterly promoter shareholding/pledge deltas. Implement participation-based liquidity sizing (days-to-liquidate @ 10% and 20% ADV, Amihud illiquidity metric).

### R4. Frontend Visual Studio, PDF Export & Zero-Mock Purge
Build dedicated UI views for the Cointegration Pairs page (`/pairs`), India Flows Dashboard (`/india-flows`), Volatility Cone panel, and Tail-Dependence heatmap using existing design tokens. Implement client-side PDF Portfolio Review export (using jsPDF) aggregating live metrics. Eliminate all mock data, pseudo-random generators (`Math.random`, `hash()`), and fake MetricCard deltas across frontend and backend.

### R5. Library-First Architecture & Test Suite Hardening (80%+ Coverage)
Rely on established open-source quant and statistical packages (`arch`, `scipy`, `statsmodels`, `cvxpy`, `stockstats`) rather than hand-rolling math. Maintain isolated per-test SQLite database fixtures and deterministic data factories, raising backend test coverage to meet the project's 80%+ gate (`pytest --cov=app --cov-fail-under=80`).

## Acceptance Criteria

### Quantitative Integrity & Accuracy
- [ ] `GET /api/v1/analytics/vol-cone` computes realized vol quantiles across 10, 21, 63, 126, and 252-day windows and returns current GARCH forecast positioning.
- [ ] 99% EVT-POT VaR outputs are numerically valid and more conservative than standard historical VaR on equity test distributions.
- [ ] Cointegration scanner successfully computes Engle-Granger p-values, OU spread half-life, and spread z-scores for a 10-stock portfolio in under 30 seconds.
- [ ] Liquidity calculations return valid days-to-liquidate across varying position sizes with zero division-by-zero or NaN values.

### Microstructure & Data Hygiene
- [ ] Daily NSE archive fetcher runs idempotently with warmup headers, storing raw artifacts in `data/nse/` and structured data in SQLite.
- [ ] All synthetic mock generators in `backend/app/api/websocket.py` and frontend hooks (`usePerformanceData`, fake MetricCard deltas) are deleted or replaced with live database-backed endpoints.
- [ ] One-click PDF portfolio report compiles genuine holdings, tear-sheet stats, regime state, and Monte Carlo probability into a clean downloadable PDF.

### Testing & Quality Bar
- [ ] All existing and new backend test suites pass synchronously via pytest with isolated SQLite schemas.
- [ ] Overall backend test suite coverage reaches or exceeds the 80% threshold without breaking regression safety (`pytest --cov=app --cov-fail-under=80` exits with code 0).
- [ ] Frontend `bun x tsc --noEmit` and `bun x vitest run` pass with zero errors.
