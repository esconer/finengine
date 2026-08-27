# Issue 13: Stress Testing (/dashboard/stress-testing) Audit, Multi-Factor Sector Elasticity & Educational Explainer Engine

**Status**: Resolved, Fully Calibrated, and Verified
**Date**: 2026-08-28
**Page**: /dashboard/stress-testing

---

## 1. Problem Statement & Root Cause Discoveries

### A. Initial Artifact: Zero-Padding Volatility Compression (-18.0% Uniform Drawdowns)
- **Symptom**: High-beta smallcaps (`ARROWGREEN.NS`) and defensive utilities (`NTPC.NS`) were rendering identical `-18.0%` stress impacts.
- **Root Cause**: Querying a 3-year lookback (756 days) across assets with mixed listing dates resulted in 500 zero-padded return days for newer assets. Computing standard deviation across the padded array deflated active volatility down to market baseline (16%), forcing volatility factors to evaluate to exactly 1.00.
- **Fix**: Volatilities are computed strictly on active non-zero returns (`s[s != 0.0]`).

### B. Second Artifact: Corporate Action Volatility Spikes (-98.0% / -26.3% Clamped Ceiling)
- **Symptom**: Unadjusted stock splits / historical boundary jumps (+74% / -52% single-day moves in raw timeseries) caused sample standard deviation to explode to >100% annual volatility. Any stock with sigma > 44% hit the upper clamp ceiling (2.8x in market crash = -98.0%, 1.75x in interest rate shock = -26.3%).
- **Root Cause**: Lack of return winsorization and excessive reliance on univariate volatility without sector/macro factors.
- **Fix**: 
  1. Applied statutory NSE/BSE daily circuit limit winsorization: `s.clip(lower=-0.20, upper=0.20)`.
  2. Built a Multi-Factor Macro & Sector Elasticity Matrix (Healthcare 0.25-0.55x, Utilities 0.20-0.70x, Tech 1.10-1.80x, Financials 0.50-1.50x, Cyclicals 0.60-1.55x).
  3. Bounded individual equity drawdowns within realistic institutional parameters ([-75%, -2%]).

---

## 2. Quantitative Verification Across Scenarios

| Scenario | Simulated Portfolio Drawdown | Historical Recovery (MTTR) | Microstructure Dynamics |
|---|---|---|---|
| **Market Crash** | **-50.8%** | 24 months | -35% base NIFTY shock scaled by portfolio beta; high-beta cyclicals (-67.8%) vs defensive utilities (-17.4%). |
| **Volatility Spike** | **-31.0%** | 5 months | -22% VIX > 40 panic shock; rapid V-shaped recovery with defensive healthcare outperformance (-8.8%). |
| **Interest Rate Shock** | **-20.8%** | 9 months | -15% monetary tightening (+300bp hike); debt-heavy industrials/financials (-22.5%) vs cash-rich defensives (-7.5%). |
| **Tech Sector Correction** | **-14.1%** | 12 months | -18% tech multiple de-rating; US Tech (-36.0%) and IT (-32.4%) absorb primary shock while non-tech holdings insulate the portfolio. |

**Top Metric Card Summary**:
- **Worst Case Scenario**: `-50.8%` (Market Crash)
- **Best Case Scenario**: `-14.1%` (Tech Sector Correction)
- **Average Impact**: `-29.2%` (Exact arithmetic mean: `(-50.8 - 20.8 - 31.0 - 14.1) / 4 = -29.175%`)
- **Scenarios Tested**: `4 of 4` (Auto-runs on initial page load)

---

## 3. UI & Educational Enhancements
1. **Interactive ? Help Explainer System**: Clickable help buttons next to every metric card, scenario, custom shock builder, position impact table column, severity tier, and recovery insight.
2. **Active Scenario Switcher**: Dropdown in the table header and "View Positions" buttons on each scenario card allow users to inspect constituent drawdowns for any specific macro scenario.
3. **Consolidated Table Header**: Clean single-header DataTable with CSV export and scenario switcher.
4. **Auto-Run Suite**: Automatically evaluates all 4 standard macro models on page load without manual clicks.

---

## 4. Verification Suite
- Backend pytest: 249 passed, 0 failures in 56.97s
- Frontend vitest: 60 passed, 0 failures in 6.77s
- Production build: 22/22 static routes prerendered in 2.7s
- Live API & Web Daemons: 200 OK
