# 07 — Ground Dashboard Diversification Score in True HHI Concentration Math

Status: closed
Type: bug
Target: rontend/src/app/dashboard/page.tsx

## Problem
1. Health summary widget displayed 100 - risk_score (e.g. 76%) as 'Diversification Score' for a 1-stock portfolio.
2. A single-stock portfolio has zero diversification benefit; displaying 76% was mathematically misleading.

## Fix
1. Replaced inverted risk score with true Herfindahl-Hirschman concentration index (HHI = sum(w_i^2)) and effective number of positions (N_eff = 1 / HHI).
2. For N <= 1, Diversification Score strictly evaluates to 0% (highlighted in red alert text).
3. Position score scales from 0% to 100% based on N_eff and sector count.

## Verification
- bun x tsc --noEmit passed with 0 errors.
- Single-holding portfolio displays 0% Diversification Score.
- Git commit 0bc4a76.
