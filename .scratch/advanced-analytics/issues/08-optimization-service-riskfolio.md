# 08 — Optimization service wrapping riskfolio-lib

Status: ready-for-agent
Type: task
Blocked by: 05

## What
`app/services/optimization_service.py`: input = returns DataFrame + constraints DTO
(min/max weight per asset, sector caps, target model). Models to support via riskfolio-lib:
HRP, CVaR optimization, max diversification, risk parity, Black-Litterman (views optional),
classic MV. Output: weights, frontier points (for chosen 2-model pair), expected risk/return.

**First step**: `uv add riskfolio-lib` is already present — smoke-test `import riskfolio as rp`
and a 5-line HRP fit on Windows before writing any service code (cvxpy solver wheels).

## Why
The single most "Bloomberg" feature; library does the math. Spec §F4 / Phase P2.

## Proof of done
- [ ] Script: HRP + CVaR-opt on 4 tickers returns weights summing to 1 in <10s.
- [ ] `POST /api/v1/optimize/run` accepts constraints DTO and returns weights + diagnostics.
