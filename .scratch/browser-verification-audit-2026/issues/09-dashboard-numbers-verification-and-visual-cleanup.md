# 09: Dashboard Numbers Verification & Visual Cleanup Audit

## Status: Resolved
**Triage**: `ready-for-agent` -> Closed

## Screenshot Audit Findings & Root Causes

### 1. Inception-Date Truncation Bug (Sharpe 11.65, VaR 0.19%, Vol 1.86%, Risk Drivers 155%)
- **Symptom**: Astronomical Sharpe ratio of `11.65`, tiny portfolio volatility `1.86%`, daily VaR `0.19%`, and top risk driver percentages exceeding 100% (`REDINGTON 155%`, `MOTHERSON 129%`).
- **Root Cause**: `NIFTYIETF.NS` only had 4 daily bars in the database (listed on August 24). Wide DataFrame construction in `_build_wide_returns` and `analytics_engine.py` called `.dropna()` across all 14 tickers, which dropped all 248 trading days prior to August 24! The covariance matrix on 4 days was rank-deficient and variance was close to zero.
- **Fix**: Replaced `.dropna()` with defensive forward/back filling (`prices.ffill().bfill()` and `returns.fillna(0.0)`) across `_build_wide_returns`, `calculate_portfolio_metrics`, `factor_exposure_analysis`, `stress_test`, `volatility_sizing`, and `risk_scoring`.

### 2. Performance History Chart Scale Discrepancy (Chart showing ?2.5K vs ?43.1K Total)
- **Symptom**: Performance history chart showed ?2,502 instead of ?43.1K.
- **Root Cause**: When `tickers` query parameter was passed by the frontend hook, `get_performance_history` was overriding holdings to `quantities = {t: 1.0}`, plotting the price sum of 1 share each.
- **Fix**: Updated `get_performance_history` to always look up true holding quantities (`p.quantity` or `market_value / last_price`) from DB for the resolved ticker universe.

### 3. Metric Card Duplication (Violating AGENTS.md Invariant)
- **Symptom**: `Risk Score` (9.9) and `Sharpe Ratio` (11.65) were rendered twice in both the top summary cards and the Risk Metrics section.
- **Fix**: Restructured top summary row to display distinct high-level portfolio KPIs: Total Value (`?43.1K`), Unrealized P&L (`+?3,021.50 (+7.54%)`), Realized Volatility (`17.38%`), and Diversification Score (`100%`), while keeping deep quant risk metrics in `RiskMetricsDisplay`.

### 4. Duplicate Positions Table Header & Text Overlap
- **Symptom**: "Portfolio Positions (14)" rendered twice, and table header sort indicators caused text clipping ("MARKET VAI UF").
- **Fix**: Consolidated into a single `DataTable` header with action button props, and cleaned up sort direction indicators.

## Verification
- Backend tests: `249 / 249 passed`
- Frontend tests: `60 / 60 passed`
- Institutional-grade quantitative figures restored: Annual Volatility `17.38%`, 1-Day VaR `-1.69%`, 1-Day CVaR `-2.43%`, Risk Drivers sum to 100%.
