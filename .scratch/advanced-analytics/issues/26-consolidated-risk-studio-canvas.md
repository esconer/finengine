# 26 — Consolidated Risk Studio Command Center View

Status: closed
Type: feature
Blocked by: 07, 12, 13, 14

## What
Create a unified `/dashboard/risk-studio` page combining all four specialized risk visualization dimensions:
1. Euler Risk Contribution percentage bar & sector rollup (F3)
2. Bivariate Student-t Copula lower-tail crash dependence heatmap (F7)
3. Multi-window Realized Volatility Cone & GARCH forecast dot (F9)
4. Rolling 60-day pairwise correlation stability chart with 90th-percentile regime break alert flag (F8)

## Why
Provides an institutional all-in-one risk terminal view without needing to navigate across separate sub-pages.

## Proof of done
- [ ] `/dashboard/risk-studio` renders all 4 risk models side-by-side on real DB holdings.
