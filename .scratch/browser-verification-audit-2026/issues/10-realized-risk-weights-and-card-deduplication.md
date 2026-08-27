# 10: Realized Risk Position Weights & Metric Card Deduplication Audit

## Status: Resolved
**Triage**: `ready-for-agent` -> Closed

## Screenshot Audit Findings (Page 2: /dashboard/realized-risk)

### 1. Hardcoded Equal-Weight Override in `resolve_allocation` (All Rows showing 7.14%)
- **Symptom in Screenshots 3 & 4**: In the Position-Level Risk Analysis table, every single stock showed `WEIGHT = 7.14%` (1/14 equal weighting), despite the user having unequal real positions in SQLite (e.g. `MOTHERSON: 13.86%`, `JUNIORBEES: 13.09%`, `ELECTCAST: 3.67%`, `NIFTYIETF: 2.54%`).
- **Root Cause**: When the frontend hook `usePortfolioAnalytics` requested `/realized-risk?tickers=...`, `resolve_allocation` forced `eq = 1.0 / len(ticker_list) = 7.14%` for all tickers whenever `tickers_param` was passed, ignoring DB market-value weights!
- **Fix**: Updated `resolve_allocation` to check `_load_portfolio_allocation(db)`. If the requested tickers exist in the user's DB portfolio, it uses their real market-value weights normalized to sum to 1.0. Applied to `get_realized_risk`, `get_forecast_risk`, and `get_factor_exposure`.

### 2. Triple Metric Card Duplication & Repetitive Layout
- **Symptom in Screenshots 1 & 2**:
  - `Sharpe Ratio` rendered twice (`1.41` in row 1, and `1.41` in `RiskMetricsDisplay`).
  - `VaR (95%)` rendered twice (`-1.79%` in `RiskMetricsDisplay`, and `-1.79%` in the row below).
  - `CVaR (95%)` rendered twice (`-2.46%` in `RiskMetricsDisplay`, and `-2.46%` in the row below).
- **Fix**: Removed the redundant `RiskMetricsDisplay` container from the Realized Risk page and reorganized the layout into two clean, distinct 4-card rows:
  - **Row 1 (Return & Efficiency)**: `Annual Return`, `Annual Volatility`, `Sharpe Ratio`, `Sortino Ratio`.
  - **Row 2 (Downside & Tail Risk)**: `Max Drawdown`, `Value at Risk (95% Daily)`, `Conditional VaR (95% Daily)`, `Hit Ratio (% Positive Days)`.

### 3. Duplicate Position-Level Table Header & Working Export CSV
- **Symptom in Screenshot 3**: Double header ("Position-Level Risk Analysis" card header + "Portfolio Positions (14)" table sub-header).
- **Fix**: Replaced with clean single `DataTable` header supporting `title="Position-Level Risk Analysis"` and wired the `actions` prop to `CSVExporter.exportToCSV(positionData, 'realized_risk_positions')`.

### 4. Insufficient Historical Depth & Denominator Collapse Guard
- **Symptom in Screenshot**: `NIFTYIETF.NS` (which only started on Yahoo Finance on 2026-08-24 with 4 bars) displayed an artificial Sharpe ratio of `-4.54` due to 248 backfilled zeros collapsing the volatility denominator to `0.34%`.
- **Fix**:
  - `AnalyticsEngine._calculate_position_metrics` now runs on each asset's raw active price series.
  - Added sample-size guard: If an asset has $< 10$ trading days ($N < 10$), annualization is constrained, returning cumulative return and Sharpe `0.00`.
  - Added `warnings` list to `GET /api/v1/analytics/realized-risk` response.
  - Added prominent **Warning Banner** and table badge (`⚠️ <30d history` / `-- (Limited)`) on `/dashboard/realized-risk` advising the user with alternative continuous ETF tickers (e.g. `NIFTYBEES.NS` or `SETFNIF50.NS`).

## Verification
- Backend tests: `249 / 249 passed`
- Frontend tests: `60 / 60 passed`
- Live API response verified: `MOTHERSON.NS: 13.86%`, `JUNIORBEES.NS: 13.09%`, `MIDCAPIETF.NS: 10.72%`, `CIPLA.NS: 6.59%`, `ELECTCAST.NS: 3.67%`, `NIFTYIETF.NS: 2.54%` (with `is_limited_history: true` and `warnings` payload).
