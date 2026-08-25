# 13 — EVT VaR + copula tail-dependence matrix

Status: ready-for-agent
Type: task
Blocked by: 11

## What
Two additions to simulation_service:
1. EVT: peaks-over-threshold fit (scipy `stats.genpareto`) at 95th percentile → tail VaR/ES at
   99% vs historical estimate; show both.
2. Tail-dependence: t-copula (or empirical) lower-tail dependence λ per pair from joint returns;
   matrix endpoint + heatmap UI next to correlation matrix.

## Why
Correlation understates crash co-movement; λ answers "which pairs die together".
Spec §F7 / Phase P4.

## Proof of done
- [ ] 99% EVT VaR more conservative than historical VaR for equity portfolio (sanity).
- [ ] Heatmap highlights ≥1 known high-λ pair (e.g. two IT names).
