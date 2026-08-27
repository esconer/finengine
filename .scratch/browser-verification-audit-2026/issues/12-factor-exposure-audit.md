# Issue 12: Factor Exposure (/dashboard/factor-exposure) Audit & Educational Explainer Engine

**Status**: Resolved and Verified
**Date**: 2026-08-28
**Page**: /dashboard/factor-exposure

## 1. Problem Statement & Audit Findings
1. **Numbers Meaning & Interpretation**:
   - Market Beta (β = +1.083): Represents the portfolio's systematic sensitivity vs NIFTY 50 (moves 1.083% for every 1.0% market move). Correctly classified as Market-Like (0.8 - 1.2).
   - Jensen's Alpha (α = +0.0016): Displayed as raw daily decimal fraction without showing annualized excess return (+40.32% p.a.).
   - R-Squared (R² = 0.679 = 67.9%): Explains 67.9% systematic variance vs 32.1% company-specific risk.
2. **Visual & Layout Clutter**:
   - Duplicate Header Bar: Outer card rendered a header with lookback selector while DataTable rendered a second inner header.
   - Column Labels: Rendered English letters (B) and (A) instead of unicode Greek symbols (β) and (α).
   - Limited History ETF: NIFTYIETF.NS has only 4 historical trading days, yielding beta +0.001 without explanatory warning badge.
3. **Missing Explainer System**:
   - Users lacked interactive contextual guidance on how beta, alpha, R², variance decomposition, and lookback windows are calculated and interpreted.

## 2. Quantitative & UI Enhancements Applied
1. **Backend Enhancements**:
   - Added annualized_alpha to factor regression outputs.
   - Added active non-zero trading day checks and data_points counts for each constituent.
   - Added warnings array for newly listed tickers (<30 days).
2. **Frontend Educational Engine**:
   - Added interactive ? help buttons to all metric cards, factor loadings, variance decomposition, lookback selector, and table columns.
   - Built a comprehensive 4-tier educational modal (What it means, How calculated, Why important, How to interpret).
3. **Layout & Table Refinements**:
   - Consolidated lookback selector (6m, 1y, 2y, 3y) and CSV Export into DataTable actions, eliminating duplicate headers.
   - Added unicode Greek symbols (β) and (α).
   - Added dual daily and annualized alpha display (+40.32% p.a., +0.160%/d).
   - Added Data Quality Notice Banner and ⚠️ <30d history badge for newly listed assets.

## 3. Verification
- Backend pytest: 249 passed, 0 failures in 53.92s
- Frontend vitest: 60 passed, 0 failures in 35.26s
- Frontend build: 22/22 static pages generated in 2.8s
- Live API & Web Daemons: 200 OK
