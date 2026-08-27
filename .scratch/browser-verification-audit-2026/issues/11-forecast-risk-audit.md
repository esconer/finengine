# Issue 11: Forecast Risk (/dashboard/forecast-risk) Full Audit & Educational Engine

**Status**: Resolved and Verified
**Date**: 2026-08-27
**Page**: /dashboard/forecast-risk

## 1. Problem Statement
1. In the position table, all holdings showed 22.00% Vol and -2.80% VaR because NIFTYIETF.NS dropped 248 days of data with dropna().
2. Multi-day horizon VaR did not scale by sqrt(horizon / 252).
3. Raw JSON parameters displayed in hero banner.
4. Missing contextual tooltips and educational guidance.

## 2. Fixes Applied
1. Fixed DataFrame alignment with ffill().bfill() and univariate position calculation.
2. Implemented square-root-of-time scaling for multi-day VaR and CVaR.
3. Added interactive ? button and educational modal across all cards, models, horizons, charts, and table columns.
4. Cleaned hero header parameters into discrete badge pills.
5. Added CSV export to position forecast table.

## 3. Verification
- Backend pytest: 249 passed
- Frontend vitest: 60 passed
- Frontend build: 22/22 routes passed
