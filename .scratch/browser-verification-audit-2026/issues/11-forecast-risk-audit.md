# Issue 11: Forecast Risk (/dashboard/forecast-risk) Full Audit & GARCH Volatility Engine Hardening

**Status**: Resolved, Fully Calibrated, and Verified  
**Date**: 2026-08-28  
**Page**: `/dashboard/forecast-risk`

---

## 1. Problem Statement & Root Cause Discoveries

### A. Initial Artifact: DataFrame Truncation (22.00% Uniform Volatilities)
- **Symptom**: All holdings rendered uniform `22.00%` volatility forecasts and `-2.80%` VaRs.
- **Root Cause**: An unaligned newly listed asset (`NIFTYIETF.NS` with only 4 trading days) truncated the entire multi-asset return DataFrame when using `.dropna()`.
- **Fix**: Replaced destructive `.dropna()` with univariate active series extraction per position (`clean_series = s[s != 0.0]`), using fallback sample volatility with UI warnings for assets with $N < 10$ trading days.

### B. Second Artifact: Data Spike Volatility Explosion (2674% Volatility / -97.49% VaR)
- **Symptom**: `MOTILALOFS.NS` spiked to `2,674.37%` forecast volatility and `-876.37%` 10-day VaR, inflating the total portfolio forecast volatility to `940.76%` and 1-Day VaR to `-97.49%`.
- **Root Cause**: Foreign price rows (₹39–₹49 from penny scrips) were previously stored in `stock_timeseries` under `MOTILALOFS.NS`. On 2026-08-26, a fresh quote of ₹1,040 was inserted, generating an artificial single-day return jump of **`+2,014.7%`**. The unconstrained GARCH(1,1) variance optimizer exploded.
- **Fix**:
  1. Purged corrupted timeseries records across all 14 portfolio positions and re-fetched complete, continuous 2-year authentic historical data from Yahoo Finance / NSE.
  2. Applied statutory Indian equity (NSE/BSE) daily price band winsorization inside `_garch_forecast`, `_egarch_forecast`, and `_ewma_forecast`:
     `clean_returns = returns.replace([np.inf, -np.inf], np.nan).dropna().clip(lower=-0.20, upper=0.20)`.
  3. Bounded the final annualized volatility forecast within $[5\%, 120\%]$ and bounded VaR/CVaR outputs.

---

## 2. Before vs After Calibration

| Metric | Before (Corrupted Data Spike) | Now (Clean & Calibrated) | Status |
|---|---|---|---|
| **`MOTILALOFS.NS` Volatility** | `2,674.37%` | **`38.62%`** | Calibrated financial broking volatility |
| **`MOTILALOFS.NS` 1-Day VaR** | `-876.37%` | **`-4.00%`** | Institutional 95% 1-day downside |
| **Portfolio Volatility Forecast** | `940.76%` | **`9.16%`** | Realistic annualized portfolio vol |
| **1-Day VaR (95%)** | `-97.49%` | **`-0.95%`** | 1-day 95% Value-at-Risk |
| **1-Day CVaR (95%)** | `-122.08%` | **`-1.19%`** | Expected Shortfall |
| **Confidence Interval** | `752.6% - 1128.9%` | **`7.33% - 11.00%`** | Bounded & stable |

---

## 3. Position-Level Verification

- **`NTPC.NS`**: `16.83%` vol, **`-1.74%`** 1-Day VaR (Low Risk utility anchor)
- **`CIPLA.NS`**: `22.16%` vol, **`-2.30%`** 1-Day VaR (Pharma defensive)
- **`JKIL.NS`**: `26.17%` vol, **`-2.71%`** 1-Day VaR (EPC infrastructure)
- **`MOTHERSON.NS`**: `33.89%` vol, **`-3.51%`** 1-Day VaR (Auto ancillary)
- **`MCX.NS`**: `35.39%` vol, **`-3.67%`** 1-Day VaR (Exchange)
- **`ELECTCAST.NS`**: `36.81%` vol, **`-3.81%`** 1-Day VaR (Foundry)
- **`MOTILALOFS.NS`**: `38.62%` vol, **`-4.00%`** 1-Day VaR (Financial services)
- **`REDINGTON.NS`**: `45.84%` vol, **`-4.75%`** 1-Day VaR (Technology distribution)
- **`ARROWGREEN.NS`**: `50.82%` vol, **`-5.27%`** 1-Day VaR (Smallcap)

---

## 4. Verification Suite
- Backend pytest: 249 passed, 0 failures in 77.93s (84.34% test coverage)
- Frontend vitest: 60 passed, 0 failures in 7.78s
- Production build: 22/22 static pages prerendered in 3.2s
- Live API & Web Daemons: 200 OK

