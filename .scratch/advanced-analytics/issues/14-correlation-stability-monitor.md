# 14 — Correlation stability monitor

Status: ready-for-agent
Type: task
Blocked by: 05

## What
Rolling 60d average pairwise correlation of holdings, tracked over time. Alert when it crosses
its own 2-year 90th percentile ("diversification breaking down"). Endpoint returns series +
alert flag; frontend: small chart + alert row in risk-studio.

## Why
Diversification is regime-dependent; this is the cheap early-warning version of F7.
Spec §F8 / Phase P4.

## Proof of done
- [ ] March-2020 style windows trigger the alert historically (backtest the flag).
