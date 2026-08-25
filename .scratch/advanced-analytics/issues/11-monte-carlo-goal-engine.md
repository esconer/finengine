# 11 — Monte Carlo goal engine

Status: ready-for-agent
Type: task
Blocked by: 05

## What
`app/services/simulation_service.py`: block bootstrap (30d blocks) + Student-t innovations,
10k paths over horizon H from current holdings' joint return distribution (use empirical cov).
Endpoint `POST /api/v1/analytics/monte-carlo` {target_value, horizon_days} → fan-chart percentiles
(5/25/50/75/95), P(final > target), drawdown distribution stats.
Frontend `/analytics/monte-carlo`: fan chart + target slider showing live P(goal) readout.

## Why
"What can I expect / how bad can it get" with fat tails, not the Gaussian fairy tale.
Spec §F6 / Phase P3.

## Proof of done
- [ ] Same inputs → deterministic results (seeded).
- [ ] P(goal) responds sensibly as target slider moves.
