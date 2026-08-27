# Daisy Risk Engine: Backend & Quantitative Analytics Architecture Survey

**Date**: 2026-08-26  
**Author**: Explorer 1 (Backend & Quantitative Analytics Survey)  
**Scope**: FastAPI Architecture, Quant Analytics Stack, Gap Analysis for R1 & R2, Dependency Audit, and Test Hardening Roadmap  
**Target Path**: `c:\sukanta\coding\finengine\.agents\explorer_survey_backend\handoff.md`

---

## 1. Observation

### 1.1 Codebase & File Structure
A full audit of `backend/` reveals the following structure:
- **Application Entry Point**: `backend/main.py`
  - Lifespan initializes database via `init_db()` (`main.py:55-67`).
  - Configures security headers, CORS (`localhost:3000`), GZip compression.
  - Mounts four router modules under `/api/v1`:
    - `portfolio.router` -> `/api/v1/portfolio` (`main.py:119-123`)
    - `data.router` -> `/api/v1/data` (`main.py:125-129`)
    - `analytics.router` -> `/api/v1/analytics` (`main.py:131-135`)
    - `websocket.router` -> `/api/v1/ws` (`main.py:137-141`)
  - Exposes `/health` and `/api/v1/health` (`main.py:144-153`).

- **Database Layer**: `app/db/database.py`, `app/models/database.py`
  - Async SQLite engine via `aiosqlite` with WAL mode and foreign key constraints enabled (`db/database.py:19-38`).
  - Tables:
    1. `portfolio_positions`: `id, ticker, weight, quantity, buy_price, region, last_price, market_value, sector, industry, custom_name, added_on, updated_on` (`models/database.py:12-38`).
    2. `stock_timeseries`: `id, ticker, date, open, high, low, close, adj_close, volume, source_used, fetch_status, fetched_on, position_id` with index `ix_ticker_date` (`models/database.py:40-68`).
    3. `analytics_cache`: `id, ticker, metric_name, metric_value, calculation_date, calculated_at, expires_at, model_params` with index `ix_ticker_metric` (`models/database.py:70-90`).
    4. `fetch_logs`: `id, ticker, timestamp, primary_attempt, fallback_attempt, status, error_message, source_used` (`models/database.py:92-112`).

- **Pydantic Schemas**: `app/models/schemas.py`
  - `PortfolioPositionBase`, `PortfolioPositionCreate`, `PortfolioPositionUpdate`, `PortfolioPositionResponse`, `PortfolioSummaryResponse` (`schemas.py:12-90`).
  - `StockDataResponse`, `StockTimeseriesResponse`, `StockQuoteResponse`, `BatchStockDataRequest`, `BatchStockDataResponse` (`schemas.py:93-160`).
  - Analytics DTOs: `RealizedRiskMetrics`, `ForecastRiskMetrics`, `FactorExposure`, `ConcentrationMetrics`, `LiquidityMetrics`, `RiskScore`, `StressTestRequest`, `StressTestResponse`, `VolatilitySizingRequest`, `VolatilitySizingResponse` (`schemas.py:162-256`).

- **Services Layer**: `app/services/`
  1. `analytics_engine.py` (1,133 lines): Realized metrics (ann return, ann vol, Sharpe, Sortino, hit ratio, VaR 95%, CVaR 95%, max drawdown, skew, kurtosis), GARCH/EGARCH/EWMA forecasts, OLS factor exposure against benchmark, HHI concentration, volume liquidity scoring, scenario stress testing, volatility-adjusted position sizing, composite risk score.
  2. `optimization_service.py` (193 lines): Implements HRP (Lopez de Prado hierarchical tree bisection via `scipy.cluster.hierarchy.linkage`), Min Vol (`cvxpy` Clarabel quadratic program), Max Sharpe (excess return tangency LP/QP), and Min CVaR 95% (Rockafellar-Uryasev scenario LP).
  3. `regime_service.py` (144 lines): 3-state Gaussian HMM (`hmmlearn.hmm.GaussianHMM`) fitted to NIFTY 50 returns + 21-day rolling volatility, ordered by risk into `crisis`, `volatile`, `calm`.
  4. `monte_carlo_service.py` (218 lines): Geometric Brownian Motion (GBM), Student-t fat-tailed innovations (`scipy.stats.t`), and Politis-Romano Stationary Bootstrap (`arch.bootstrap.StationaryBootstrap`).
  5. `benchmark_service.py` (97 lines): Ingestion and SQLite caching of NIFTY 50 index (`^NSEI`).
  6. `indicators_service.py` (230 lines): Technical indicator engine using `stockstats.StockDataFrame`.
  7. `company_data_service.py` (180 lines): Fundamentals, financial statements, insider transactions.
  8. `alpha_vantage_service.py` (338 lines): Multi-key rotation pool with daily/per-minute rate budget tracking.
  9. `data_service.py` (806 lines): yfinance market data fetcher with Indian ticker normalizer (`.NS` / `.BO`), 3 retries, timeout guard, SQLite timeseries upsert.
  10. `currency_service.py` (185 lines): USD/INR conversion and Indian currency formatting (lakhs/crores).
  11. `cache_service.py` (194 lines): Operations on `analytics_cache` and `fetch_logs`.

### 1.2 Quantitative Dependency Audit (`pyproject.toml`)
- `fastapi`, `uvicorn`, `sqlalchemy`, `aiosqlite`: Core web & async ORM stack.
- `numpy`, `pandas`, `scipy` (>=1.16): High-performance array, statistical, and linear algebra routines.
- `arch` (>=7.0): GARCH volatility modeling & Stationary Bootstrap.
- `statsmodels` (>=0.14): Cointegration tests (`coint`, `coint_johansen`), OLS regression, time-series analysis.
- `cvxpy` (>=1.6.0) with `Clarabel` solver: Convex portfolio optimization.
- `quantstats`: Financial tear-sheet metrics and drawdown computations.
- `hmmlearn` (>=0.3.3): Gaussian Hidden Markov Models.
- `stockstats` (>=0.6.8): Technical indicators.
- **Finding**: All required open-source math libraries (`arch`, `scipy`, `statsmodels`, `cvxpy`, `stockstats`) are already declared and installed in the Python 3.12 environment. No external C-dependencies or proprietary solvers are needed.

### 1.3 Implementation Gap Analysis for R1 & R2

| Requirement | Target Endpoint / Capability | Current Status in Codebase | Missing Elements & Technical Gaps |
|---|---|---|---|
| **R1.1: Volatility Cone & Term Structure** | `GET /api/v1/analytics/vol-cone` | **NOT IMPLEMENTED** | - No endpoint `GET /vol-cone` in `app/api/analytics.py`<br>- No multi-window rolling vol engine (10, 21, 63, 126, 252 days)<br>- No historical quantile distribution calculator (min, p25, p50, p75, max)<br>- No current realized vs GARCH/EWMA forecast overlay positioning |
| **R1.2: EVT Peaks-Over-Threshold (POT) VaR/ES** | `GET /api/v1/analytics/tail-risk` (or `/tails`) | **NOT IMPLEMENTED** | - `analytics_engine.py:689-706` only computes empirical 95% percentile VaR/CVaR<br>- No Generalized Pareto Distribution fitting (`scipy.stats.genpareto.fit`) on 95th percentile excess losses<br>- No analytical 99% EVT-POT VaR and 99% Expected Shortfall formulas<br>- No side-by-side comparison with historical 99% VaR |
| **R1.3: Copula Lower-Tail Dependence Matrix** | `GET /api/v1/analytics/tail-dependence` (or `/tails`) | **NOT IMPLEMENTED** | - Only Pearson correlation / covariance exists (`analytics_engine.py:828, 1103`)<br>- No bivariate Student-t copula tail parameter calculation: \(\lambda_L = 2 t_{\nu+1}\left(-\sqrt{\frac{(\nu+1)(1-\rho)}{1+\rho}}\right)\)<br>- No empirical tail co-exceedance estimator<br>- No symmetric \(N \times N\) tail-dependence matrix output |
| **R2.1: Rolling 60d Correlation Monitor & Regime Breaks** | `GET /api/v1/analytics/correlation-stability` | **NOT IMPLEMENTED** | - No rolling pairwise correlation series generator<br>- No average off-diagonal correlation tracker \(\bar{\rho}_t = \frac{2}{N(N-1)}\sum_{i<j}\rho_{i,j,t}\)<br>- No historical 90th percentile regime-break threshold calculation<br>- No alert generator for diversification breakdown |
| **R2.2: Cointegration Pairs Scanner** | `GET /api/v1/analytics/coint` | **NOT IMPLEMENTED** | - No pairs scanner across holdings \(\cup\) watchlist tickers<br>- No Engle-Granger two-step cointegration test (`statsmodels.tsa.stattools.coint`)<br>- No Johansen cointegration rank test (`statsmodels.tsa.vector_ar.vecm.coint_johansen`)<br>- No Ornstein-Uhlenbeck (OU) mean-reversion half-life regression (\(\Delta z_t = \gamma z_{t-1} + \mu \implies t_{1/2} = -\ln 2 / \ln(1+\gamma)\))<br>- No spread z-score calculation<br>- No pairwise calculation caching mechanism for fast response times (<30s for 10 tickers) |

### 1.4 Test Suite Baseline & Coverage Audit
Running `uv run pytest` produced:
- **Test execution result**: 202 passed, 19 failed, 1 error in 57.79s.
- **Coverage result**: **75.16%** (Target: **80.0%** threshold; failed coverage gate).
- **Module Coverage Breakdown**:
  - `app/api/analytics.py`: 38% (567 statements, 351 missed)
  - `app/api/portfolio.py`: 42% (384 statements, 222 missed)
  - `app/db/database.py`: 50% (42 statements, 21 missed)
  - `app/api/data.py`: 75% (173 statements, 43 missed)
  - `app/services/benchmark_service.py`: 76% (55 statements, 13 missed)
  - `app/services/regime_service.py`: 78% (60 statements, 13 missed)
  - `app/services/analytics_engine.py`: 81% (508 statements, 99 missed)
  - `app/services/optimization_service.py`: 88% (102 statements, 12 missed)
  - `app/services/alpha_vantage_service.py`: 93% (180 statements, 12 missed)
  - `app/services/currency_service.py`: 97% (112 statements, 3 missed)
  - `app/services/monte_carlo_service.py`: 99% (94 statements, 1 missed)
- **Root Cause Analysis of 19 Test Failures**:
  1. `test_wave1_regressions.py` & `conftest.py`: SQLite fixture concurrency and session refresh conflict on `seeded_positions` (`sqlalchemy.exc.InvalidRequestError`).
  2. `test_coverage_alpha_vantage.py`: `YFRateLimitError` test mock signature mismatch.
  3. `test_coverage_analytics_all_routes.py` & `test_coverage_portfolio_api.py`: Route validation HTTP status codes (422 vs 400).
  4. `test_coverage_data_service.py`: yfinance mock data column case sensitivity (`date` vs DatetimeIndex).

---

## 2. Logic Chain

### 2.1 Architectural Placement for R1 & R2
1. **Separation of Concerns**:
   - Rather than bloating `analytics_engine.py` (already >1,100 lines) with complex mathematical sub-routines, create dedicated domain services under `app/services/`:
     - `app/services/volatility_service.py`: Volatility cone multi-window rolling quantiles + GARCH/EWMA forecast positioning.
     - `app/services/tail_risk_service.py`: EVT-POT (Generalized Pareto Distribution via `scipy.stats.genpareto`) + Student-t / Empirical Copula Lower-Tail Dependence Matrix.
     - `app/services/correlation_service.py`: Rolling 60-day average pairwise correlation monitor with 2-year 90th-percentile regime break detection.
     - `app/services/cointegration_service.py`: Engle-Granger, Johansen cointegration tests, OLS hedge ratios, Ornstein-Uhlenbeck spread half-life, z-score calculations, with caching via SQLite `AnalyticsCache`.
2. **Router Integration**:
   - Expose the endpoints cleanly in `app/api/analytics.py` (or delegate to sub-routers):
     - `GET /api/v1/analytics/vol-cone`
     - `GET /api/v1/analytics/tails` (or `/tail-risk`)
     - `GET /api/v1/analytics/correlation-stability`
     - `GET /api/v1/analytics/coint`
   - Use existing `resolve_allocation(tickers, db)` and `_build_wide_returns(...)` helpers for consistent data extraction from SQLite cached prices.

### 2.2 Mathematical Formulations

#### (A) Volatility Cone (`GET /api/v1/analytics/vol-cone`)
- **Windows**: \( W \in \{10, 21, 63, 126, 252\} \) trading days.
- **Rolling Realized Volatility**: For price series \( P_t \), daily log or percentage returns \( r_t = \ln(P_t / P_{t-1}) \).
  \[
  \sigma_{t}^{(W)} = \sqrt{\frac{252}{W - 1} \sum_{k=0}^{W-1} \left( r_{t-k} - \bar{r}_t \right)^2}
  \]
- **Historical Quantiles**: Over historical lookback (e.g. 504 to 1260 days), calculate per window \( W \):
  - `min`: \( \min_t \sigma_t^{(W)} \)
  - `p25`: 25th percentile
  - `median` (`p50`): 50th percentile
  - `p75`: 75th percentile
  - `max`: \( \max_t \sigma_t^{(W)} \)
  - `current_realized`: \( \sigma_{\text{latest}}^{(W)} \)
- **Forecast Overlay**:
  - Fit GARCH(1,1) using `arch.arch_model(r, vol="Garch", p=1, q=1, dist="normal")`.
  - Multi-step volatility forecast over 21d / 63d horizons.
  - Position evaluation:
    - If forecast \( \le \text{p25} \): `"cheap"`
    - If \( \text{p25} < \text{forecast} \le \text{p75} \): `"normal"`
    - If forecast \( > \text{p75} \): `"rich"`

#### (B) EVT Peaks-Over-Threshold (POT) VaR / Expected Shortfall
- Let \( L_t = -R_t \) be daily portfolio losses (positive values = losses).
- Select high threshold \( u \) at the 95th percentile of historical losses:
  \[
  u = \text{Percentile}(L, 95)
  \]
- Identify exceedances \( y_j = L_j - u \) for all \( L_j > u \). Let \( N_u \) be the count of exceedances out of total sample size \( N \).
- Fit Generalized Pareto Distribution (GPD) on exceedances using `scipy.stats.genpareto.fit(y, floc=0)`:
  - Estimated parameters: shape parameter \( \xi \) (`c`), scale parameter \( \beta \) (`scale`).
- **99% EVT VaR** (\( \alpha = 0.01 \)):
  \[
  \text{VaR}_{0.99}^{\text{EVT}} = u + \frac{\beta}{\xi} \left[ \left( \frac{N}{N_u} \cdot 0.01 \right)^{-\xi} - 1 \right] \quad (\text{if } \xi \neq 0)
  \]
  \[
  \text{VaR}_{0.99}^{\text{EVT}} = u + \beta \ln\left( \frac{N_u}{N \cdot 0.01} \right) \quad (\text{if } \xi = 0)
  \]
- **99% EVT Expected Shortfall (CVaR)**:
  \[
  \text{ES}_{0.99}^{\text{EVT}} = \frac{\text{VaR}_{0.99}^{\text{EVT}} + \beta - \xi u}{1 - \xi} \quad (\text{valid for } \xi < 1)
  \]
- Compare against historical empirical 99% VaR (\( \text{Percentile}(L, 99) \)) and historical 99% ES. On fat-tailed equity returns, \( \text{VaR}_{0.99}^{\text{EVT}} \ge \text{VaR}_{0.99}^{\text{Hist}} \).

#### (C) Copula Lower-Tail Dependence Matrix
- For each asset pair \( (i, j) \) with returns \( R_i, R_j \):
  - Linear correlation: \( \rho = \text{corr}(R_i, R_j) \).
  - Degrees of freedom \( \nu \): fitted via `scipy.stats.t.fit` on standardized returns (clipped to \( [2.5, 30] \)).
  - Bivariate Student-t Copula Lower Tail Dependence Coefficient:
    \[
    \lambda_L = 2 \cdot t_{\nu+1}\left( -\sqrt{ \frac{(\nu + 1)(1 - \rho)}{1 + \rho} } \right)
    \]
    where \( t_{\nu+1} \) is the Student-t CDF with \( \nu+1 \) degrees of freedom (`scipy.stats.t.cdf`).
  - Bounds: \( 0 \le \lambda_L \le 1 \). When \( \rho \to 1 \), \( \lambda_L \to 1 \); when \( \rho \to -1 \), \( \lambda_L \to 0 \).
- Output: \( N \times N \) symmetric matrix with labels, diagonal = 1.0, and a list of high tail-risk pairs (\( \lambda_L \ge 0.35 \)).

#### (D) Rolling 60d Pairwise Correlation Monitor & 90th Percentile Regime Breaks
- Let \( R \in \mathbb{R}^{T \times N} \) be wide returns over lookback period (e.g. \( T \ge 504 \) trading days).
- For each rolling window \( t \in [60, T] \):
  - Compute sample correlation matrix \( C_t \in \mathbb{R}^{N \times N} \).
  - Average pairwise correlation:
    \[
    \bar{\rho}_t = \frac{2}{N(N - 1)} \sum_{1 \le i < j \le N} C_{t, i, j}
    \]
- Historical 90th percentile threshold:
  \[
  \theta_{90} = \text{Percentile}(\{ \bar{\rho}_t \}_{t=60}^T, 90)
  \]
- Current 60d average correlation: \( \bar{\rho}_{\text{curr}} = \bar{\rho}_T \).
- Regime break alert triggered if \( \bar{\rho}_{\text{curr}} > \theta_{90} \).

#### (E) Cointegration Scanner (`GET /api/v1/analytics/coint`)
- Universe: All pairs \( (X, Y) \) from portfolio holdings \(\cup\) watchlist tickers.
- For each unique pair:
  1. **Engle-Granger Two-Step Test**: `statsmodels.tsa.stattools.coint(Y, X)`
     - Yields: test statistic, p-value, critical values (1%, 5%, 10%).
     - Cointegrated if \( p < 0.05 \).
  2. **OLS Hedge Ratio & Spread**:
     \[
     Y_t = \alpha + \beta X_t + \epsilon_t \implies z_t = Y_t - (\alpha + \beta X_t)
     \]
  3. **Johansen Cointegration Rank Test**:
     - `statsmodels.tsa.vector_ar.vecm.coint_johansen(np.column_stack([Y, X]), det_order=0, k_ar_diff=1)`
     - Compare trace statistic vs 95% critical value.
  4. **Ornstein-Uhlenbeck (OU) Mean Reversion Half-Life**:
     - Continuous OU: \( dz_t = \theta (\mu - z_t) dt + \sigma dW_t \).
     - Discrete regression: \( \Delta z_t = z_t - z_{t-1} = a + \gamma z_{t-1} + e_t \).
     - Mean-reversion speed: \( \theta = -\ln(1 + \gamma) \) (if \( -1 < \gamma < 0 \)).
     - Half-life in trading days:
       \[
       t_{1/2} = \frac{\ln 2}{\theta} = -\frac{\ln 2}{\ln(1 + \gamma)} \approx -\frac{\ln 2}{\gamma}
       \]
     - If \( \gamma \ge 0 \), spread is non-mean-reverting (half-life = \(\infty\) / `None`).
  5. **Current Spread Z-Score**:
     \[
     z_{\text{score}} = \frac{z_T - \text{mean}(z)}{\text{std}(z)}
     \]
  6. **Caching Strategy**:
     - Store computed results in `analytics_cache` table or memory with key `f"coint_{ticker_a}_{ticker_b}_{date}"` and TTL of 24 hours.

---

## 3. Caveats

1. **Sample Size Requirements**:
   - Volatility cone requires at least 252 trading days of history (preferably 504–756 days) to form meaningful quartile bands for the 126d and 252d windows.
   - EVT-POT fitting requires sufficient tail exceedances (at least \( N_u \ge 20 \)). For a 252-day window, 5% tail gives ~13 points, which can be noisy; recommended lookback for EVT is at least 500–756 trading days (~2–3 years).
   - Cointegration and OU half-life tests require synchronized trading calendars (inner join on date indices) to eliminate non-overlapping holiday artifacts.
2. **Numerical Edge Cases**:
   - GPD Shape parameter \( \xi \ge 1 \): Expected Shortfall is theoretically infinite; in practice, clip \( \xi \le 0.95 \) or fall back to numerical integration.
   - Student-t degrees of freedom \( \nu \le 2 \): Variance is undefined; clip \( \nu \ge 2.1 \).
   - Non-stationary spreads with \( \gamma \ge 0 \): OU half-life is undefined; must return `None` or `null` gracefully without throwing division by zero.
3. **Database Concurrency in Pytest**:
   - The test suite uses SQLite (`test.db`). Async tests sharing a single database file without table isolation experience `InvalidRequestError` or duplicate key errors during parallel or rapid sequential executions. Tests must use isolated per-test SQLite memory databases (`sqlite+aiosqlite:///:memory:`) or fresh tempfiles.

---

## 4. Conclusion & Proposed Architecture

### 4.1 Recommended Service Decomposition

```
backend/app/
├── services/
│   ├── volatility_service.py       # [NEW] Volatility cone 10/21/63/126/252d quantile bands & GARCH overlay
│   ├── tail_risk_service.py        # [NEW] EVT-POT 99% VaR/ES (genpareto) & Student-t copula tail matrix
│   ├── correlation_service.py      # [NEW] Rolling 60d pairwise correlation & 90th-percentile regime breaks
│   ├── cointegration_service.py    # [NEW] Engle-Granger & Johansen tests, OU half-life, spread z-scores, caching
│   ├── analytics_engine.py         # Existing core analytics engine
│   ├── optimization_service.py     # Existing HRP / Min Vol / Max Sharpe / Min CVaR
│   ├── regime_service.py           # Existing 3-state Gaussian HMM
│   ├── monte_carlo_service.py      # Existing Goal simulation
│   └── data_service.py             # Existing market data & caching
├── api/
│   └── analytics.py                # Mounts GET /vol-cone, GET /tails, GET /correlation-stability, GET /coint
└── models/
    └── schemas.py                  # DTOs: VolConeResponse, TailRiskResponse, CorrelationStabilityResponse, CointScannerResponse
```

### 4.2 API Contract Specifications

#### 1. `GET /api/v1/analytics/vol-cone`
- **Query Params**: `tickers: Optional[str]`, `lookback_days: int = 756`
- **Response Schema**:
```json
{
  "symbol": "PORTFOLIO",
  "as_of": "2026-08-26",
  "windows": [
    {
      "window_days": 10,
      "min": 0.082,
      "p25": 0.124,
      "median": 0.165,
      "p75": 0.218,
      "max": 0.384,
      "current_realized": 0.142
    },
    {
      "window_days": 21,
      "min": 0.091,
      "p25": 0.131,
      "median": 0.170,
      "p75": 0.224,
      "max": 0.362,
      "current_realized": 0.155
    },
    { "window_days": 63, "min": 0.105, "p25": 0.142, "median": 0.178, "p75": 0.215, "max": 0.312, "current_realized": 0.168 },
    { "window_days": 126, "min": 0.118, "p25": 0.149, "median": 0.182, "p75": 0.208, "max": 0.285, "current_realized": 0.172 },
    { "window_days": 252, "min": 0.132, "p25": 0.158, "median": 0.185, "p75": 0.201, "max": 0.260, "current_realized": 0.180 }
  ],
  "current_forecast": {
    "model": "GARCH",
    "annualized_vol": 0.162,
    "horizon_days": 21,
    "percentile_rank": 42.5,
    "valuation": "normal"
  }
}
```

#### 2. `GET /api/v1/analytics/tails`
- **Query Params**: `tickers: Optional[str]`, `lookback_days: int = 756`
- **Response Schema**:
```json
{
  "as_of": "2026-08-26",
  "evt_var": {
    "confidence_level": 0.99,
    "evt_pot_var_99": -0.0385,
    "evt_pot_es_99": -0.0492,
    "historical_var_99": -0.0312,
    "historical_es_99": -0.0415,
    "threshold_u": 0.0185,
    "gpd_shape_xi": 0.182,
    "gpd_scale_beta": 0.0074,
    "exceedances_count": 38,
    "total_observations": 756,
    "is_fat_tailed": true
  },
  "tail_dependence_matrix": {
    "tickers": ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"],
    "matrix": [
      [1.00, 0.18, 0.15, 0.22],
      [0.18, 1.00, 0.58, 0.20],
      [0.15, 0.58, 1.00, 0.19],
      [0.22, 0.20, 0.19, 1.00]
    ],
    "high_tail_risk_pairs": [
      {
        "pair": ["TCS.NS", "INFY.NS"],
        "lower_tail_lambda": 0.582,
        "linear_correlation": 0.684,
        "degrees_of_freedom": 4.2,
        "risk_category": "HIGH"
      }
    ]
  }
}
```

#### 3. `GET /api/v1/analytics/correlation-stability`
- **Query Params**: `tickers: Optional[str]`, `lookback_days: int = 756`
- **Response Schema**:
```json
{
  "as_of": "2026-08-26",
  "current_avg_correlation": 0.524,
  "historical_threshold_90th": 0.485,
  "historical_threshold_75th": 0.412,
  "historical_median": 0.320,
  "is_regime_break": true,
  "alert_level": "CRITICAL",
  "message": "Average pairwise correlation (0.524) exceeds 90th percentile (0.485). Diversification breakdown detected.",
  "series": [
    { "date": "2026-01-05", "avg_correlation": 0.312, "threshold_90th": 0.485 },
    { "date": "2026-08-26", "avg_correlation": 0.524, "threshold_90th": 0.485 }
  ]
}
```

#### 4. `GET /api/v1/analytics/coint`
- **Query Params**: `tickers: Optional[str]`, `p_value_threshold: float = 0.05`, `max_half_life: int = 60`
- **Response Schema**:
```json
{
  "as_of": "2026-08-26",
  "universe_size": 8,
  "scanned_pairs_count": 28,
  "cointegrated_pairs_count": 2,
  "pairs": [
    {
      "ticker_a": "TCS.NS",
      "ticker_b": "INFY.NS",
      "engle_granger_pvalue": 0.0124,
      "engle_granger_tstat": -3.84,
      "is_cointegrated": true,
      "hedge_ratio_beta": 2.145,
      "intercept_alpha": 120.5,
      "ou_half_life_days": 18.4,
      "ou_reversion_speed_theta": 0.0376,
      "current_spread_zscore": 2.15,
      "johansen_cointegrated": true,
      "last_price_a": 3850.0,
      "last_price_b": 1740.0,
      "signal": "SHORT_SPREAD (Short TCS.NS, Long INFY.NS)"
    }
  ]
}
```

---

## 5. Verification Method

To independently verify the implementation and ensure the 80%+ test coverage gate is satisfied:

1. **Unit & Integration Tests Execution**:
   ```bash
   cd backend
   uv run pytest -v tests/test_volatility_cone.py tests/test_tail_risk.py tests/test_correlation_stability.py tests/test_cointegration.py
   ```
2. **Full Test Suite & Coverage Gate Check**:
   ```bash
   cd backend
   uv run pytest --cov=app --cov-report=term-missing --cov-fail-under=80
   ```
   *Verification criteria*: Exits with code 0, all tests pass synchronously, overall line coverage is \(\ge 80\%\).

3. **Numerical Sanity & Mathematical Proofs**:
   - **Vol Cone**: Monotonic quantile ordering verified for every window: \( \text{min} \le \text{p25} \le \text{median} \le \text{p75} \le \text{max} \).
   - **EVT-POT**: 99% EVT VaR is strictly more conservative than standard normal VaR on Student-t / historical stock returns with kurtosis \( > 3 \).
   - **Copula Matrix**: Diagonal elements equal 1.0, matrix is symmetric (\( \lambda_{i,j} = \lambda_{j,i} \)), and all values bounded in \( [0, 1] \).
   - **Cointegration & OU Half-Life**: Synthetic cointegrated AR(1) pair \( Y_t = 2 X_t + z_t \) with known \( \theta = 0.05 \) produces estimated half-life \( t_{1/2} \approx \ln(2)/0.05 \approx 13.86 \pm 2 \) days and p-value \( < 0.01 \).
