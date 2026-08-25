# 15 — Cointegration / pairs scanner

Status: ready-for-agent
Type: task
Blocked by: 05

## What
`GET /api/v1/analytics/coint`: for all pairs in holdings ∪ watchlist, run Engle-Granger
(statsmodels `coint`) and Johansen (for >2 sets later); estimate mean-reversion half-life via
OU fit on the spread; output ranked table: pair, p-value, half-life, current z-score of spread.
Frontend `/pairs` page with the ranked table.

## Why
Relative-value candidates inside your own universe — nothing free does this for your holdings.
Spec §F10 / Phase P4.

## Proof of done
- [ ] Scanner on 10 tickers completes <30s (cache pairwise results).
- [ ] A known cointegrated pair (e.g. two PSU banks) scores plausible p-value.
