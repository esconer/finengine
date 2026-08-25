# 06 — Quantstats tear-sheet endpoint + page

Status: ready-for-agent
Type: task
Blocked by: 01, 05

## What
Backend `GET /api/v1/analytics/tear-sheet`: portfolio returns (from real holdings) + NIFTY
benchmark → quantstats metrics (omega, tail ratio, sortino, calmar, up/down capture, skew,
kurtosis, monthly returns table) computed server-side and returned as JSON.
Frontend route `/analytics/tear-sheet`: metrics grid, monthly heatmap, underwater chart.

Replace hand-rolled metric math in `analytics_engine.py` `_calculate_basic_metrics` family with
quantstats calls where equivalent (keep VaR/CVaR custom if simpler).

## Why
Pro-grade report free sites don't offer for custom portfolios. Spec §F2 / Phase P1.

## Proof of done
- [ ] Tear-sheet page renders for a real portfolio with ≥60 days history.
- [ ] Numbers spot-check against a notebook running quantstats on same data.
