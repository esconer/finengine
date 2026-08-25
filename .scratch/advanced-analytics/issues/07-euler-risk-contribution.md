# 07 — Euler risk contribution endpoint + UI

Status: ready-for-agent
Type: task
Blocked by: 01

## What
`GET /api/v1/analytics/risk-contribution`: per-position % of portfolio risk under three models
(volatility, CVaR, CDaR) using Euler decomposition — riskfolio-lib provides
`RiskContrib.over_contributor` style utilities or compute via marginal contribution math.
Frontend: add to `/analytics/risk-studio` (or realized-risk page): sorted bar chart +
per-sector rollup.

## Why
Answers "where does my risk actually come from" → which positions to trim. Spec §F3 / Phase P1.

## Proof of done
- [ ] Contributions sum to ~100% per model.
- [ ] A concentrated position visibly dominates the bar chart.
