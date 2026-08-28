# Issue 16: Volatility Sizing (/dashboard/volatility-sizing) Audit & Real Rebalancing Engine

**Status**: Resolved, Fully Verified, and Production Ready  
**Date**: 2026-08-28  
**Page**: /dashboard/volatility-sizing

---

## 1. Problem Statement & Audit Findings

### A. Number Verification & Mathematical Rigor
Across the 14-constituent portfolio:
1. **Model Calibration & Econometric Selection**:
   - The backend now genuinely executes the selected volatility model:
     - **EWMA**: Exponentially weighted moving average with RiskMetrics decay $\lambda = 0.94$.
     - **GARCH**: Mean-reverting GARCH(1,1) conditional volatility.
     - **EGARCH**: Exponential GARCH capturing asymmetric leverage down-market shock spikes.
2. **Annualized Volatility Display & Double Square Root Bug**:
   - Previously, the backend annualized volatility with $\sqrt{252}$, and the frontend erroneously multiplied by $\sqrt{252}$ a second time, inflating numbers into unreadable values.
   - Fixed: Constituent annualized volatilities ($\sigma_i$) and estimated portfolio volatility ($\sigma_p = \sqrt{w^T \Sigma w} \times \sqrt{252}$) are accurately scaled and formatted.
3. **Volatility Risk Tiers**:
   - Dynamic classification based on annualized volatility:
     - **Low Risk** (< 20%): Index ETFs (NIFTYIETF ~16%, MAFANG ~19%)
     - **Moderate Risk** (20% – 35%): Large-Cap Equities (CIPLA, NTPC, MOTHERSON)
     - **Elevated Risk** (> 35%): High-Beta Small Caps (ELECTCAST, ARROWGREEN, MCX)
4. **Inverse-Volatility Risk Parity Weighting**:
   - ^* = \frac{1/\sigma_i}{\sum_j 1/\sigma_j}$
   - Normalizes portfolio risk contribution so volatile holdings receive smaller weights while stable assets receive higher sizing.

### B. Functional Rebalance Execution
- Replaced placeholder mock alert (Rebalancing functionality would be implemented here) with:
  - Atomic backend endpoint: POST /api/v1/portfolio/rebalance
  - Rebalance preview confirmation modal displaying Buy/Sell orders, turnover delta, and trade allocations.
  - Updates position target weights in the SQLite database atomically and re-normalizes.

### C. Interactive Explainer System
- Added EXPLAINERS modal engine with clickable ? buttons for:
  - Target Volatility Setting
  - Estimated Portfolio Volatility
  - Active Volatility Forecasting Model
  - Total Positions
  - Volatility-Adjusted Weights Chart
  - Volatility Forecast & Parity Targets
  - Rebalancing Recommendations
  - All Table Column Headers (Ticker, Current Weight, Recommended Weight, Volatility, Weight Delta, Action).
- Added CSV Export button for volatility-adjusted sizing table.

---

## 2. Verification Suite
- Backend pytest: 250 passed, 0 failures (> 83.6% test coverage)
- Next.js production build: 22/22 static pages prerendered
- Live API & Web Daemons: 200 OK
