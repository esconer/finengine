# 10 — Regime engine (HMM on NIFTY)

Status: ready-for-agent
Type: task
Blocked by: 05

## What
`app/services/regime_service.py`: fit 3-state Gaussian HMM (hmmlearn, fixed random_state) on
NIFTY daily returns (+ rolling vol as second feature). Output per day: regime label
(e.g. calm/volatile/crisis by mapping states to vol ordering). Endpoint
`GET /api/v1/analytics/regime`: current regime + last 90d history + portfolio's historical mean
return/vol CONDITIONAL on current regime. Frontend: banner strip on `/dashboard` showing
regime + "portfolio historically does X in this regime"; alert color when in worst state.

If HMM flips labels too often week-to-week, fall back to 200d-vol threshold classifier.

## Why
"Is the tape hostile right now?" — the de-risk/stay-invested decision. Spec §F5 / Phase P3.

## Proof of done
- [ ] Regime series stable (label persistence >80% day-over-day).
- [ ] Banner reflects regime without page reload after refresh.
