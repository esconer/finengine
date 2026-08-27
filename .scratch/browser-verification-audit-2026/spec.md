# Browser Verification Audit 2026 — Terminal-Wide Audit & Plan

Status: complete · Owner: sukanta · Created: 2026-08-27

## Scope & Purpose
Comprehensive real-browser audit of all 18 pages of the Daisy Risk Engine terminal (Next.js frontend at http://localhost:3000, FastAPI backend at http://127.0.0.1:8000) under active live portfolio holdings (\INFY.NS\ and \HDFCBANK.NS\).

---

## Page-by-Page Audit Results (18 / 18 Verified)

| # | Page Route | Primary Capabilities & Verified Invariants | Status |
|---|---|---|---|
| 1 | \/dashboard\ | Total Value, Risk Score, HHI-grounded Diversification, Mark-to-market prices, Sector pie | **PASSED** |
| 2 | \/dashboard/realized-risk\ | Annual Vol (20.97%), Max Drawdown (-31.88%), 95% Historical VaR & CVaR, Position table | **PASSED** |
| 3 | \/dashboard/forecast-risk\ | GARCH(1,1), EGARCH, EWMA multi-day projections, Volatility term scaling, Horizon slider | **PASSED** |
| 4 | \/dashboard/factor-exposure\ | Market Beta, Jensen\'s Alpha, R-Squared vs NIFTY 50, Lookback dropdown (6M-3Y) | **PASSED** |
| 5 | \/dashboard/stress-testing\ | GFC 2008, Rate Hike, COVID-19 shocks, Custom scenario builder (+% loss, duration) | **PASSED** |
| 6 | \/dashboard/concentration\ | HHI = 0.50, Effective Holdings N_eff = 2.0, Lorenz curve, Cumulative weight bars | **PASSED** |
| 7 | \/dashboard/liquidity\ | INR notation (₹ Cr, ₹ L), 10%/20% ADV liquidation horizons (<0.01d), Amihud metric | **PASSED** |
| 8 | \/dashboard/volatility-sizing\ | True inverse-volatility parity weights (w_i proportional to 1/sigma_i), Total Positions card | **PASSED** |
| 9 | \/dashboard/tear-sheet\ | QuantStats statistics, monthly returns heatmap, continuous underwater drawdown curve | **PASSED** |
| 10 | \/dashboard/risk-contribution\ | Exact Euler volatility decomposition (sum RC_i = sigma_p), CVaR tail attributions | **PASSED** |
| 11 | \/dashboard/risk-studio\ | Consolidated 4-panel canvas: Euler RC, Student-t Copula matrix, Vol cones, Correlation | **PASSED** |
| 12 | \/dashboard/optimize\ | Markowitz Efficient Frontier scatter, HRP, Min Vol, Max Sharpe, Min CVaR, Black-Litterman | **PASSED** |
| 13 | \/dashboard/regime\ | 3-state Gaussian HMM on NIFTY returns + 21d vol, Stability %, Historical timeline bar | **PASSED** |
| 14 | \/dashboard/monte-carlo\ | 2,000 paths (GBM, Student-t, Stationary Bootstrap), Quantile probability outcome fan | **PASSED** |
| 15 | \/dashboard/pairs\ | Cointegration table, Engle-Granger p-values, Ornstein-Uhlenbeck half-life, Spread z-score | **PASSED** |
| 16 | \/dashboard/india-flows\ | NSE Bhavcopy delivery spikes (>2sigma), 30D FII/DII institutional cash flow bars, ADV tiers | **PASSED** |
| 17 | \/portfolio/manage\ | Dynamic currency switcher (USD/INR), Add Position modal, CSV dropzone, Normalizer | **PASSED** |
| 18 | \/dashboard/settings\ | Valuation currency, benchmark selection (^NSEI), lookback window, cache purge | **PASSED** |

---

## Production Certification
All 18 pages have been verified in the browser. Zero console errors, zero mock deltas, zero NaN occurrences. Mathematical formulas and Indian financial notation (₹, Cr, L) are certified for institutional personal risk management.
