# 21 — Cointegration publishes `zscore: 0.0` for a dispersionless spread

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `backend/`
Severity: **MEDIUM**

## What

`cointegration_service.py:865`
```python
z_val = round(..., 2) if spread_std > 1e-8 else 0.0
```

The headline field at `:810-811` in the **same function** correctly returns `None` under the same
condition.

## Why

A perfectly collinear pair produces a zero-dispersion spread. The headline correctly says "no
measurable dispersion, so no z-score exists", but the **series** emits `0.0` for every point.

Verified on `A = 2 + 3B`:
```
current_spread_zscore = None      ou_half_life = None
spread_series[0]      = {'date': '2024-01-01', 'spread': 0.0, 'zscore': 0.0}
```

The spread chart draws a flat line at z=0, which reads as **"the spread is exactly at its mean,
forever"** — the opposite of "the spread has no measurable dispersion".

## The related defect: the collinearity warning is ignored

`statsmodels.coint` emits `CollinearityWarning: … Cointegration test is not reliable in this case`
for exactly-collinear series. The code ignores it **and publishes a p-value from the test anyway**.

So a degenerate pair gets both a meaningless p-value and a flat z=0 line.

## Change

- `z_val = None`, matching `:810-811`.
- Detect the collinearity condition and mark the pair: no p-value, no z-score, and an explicit
  reason. statsmodels exposes this via the warning — catch it rather than ignoring it.
- The frontend must render a `None` z-score as a gap, not a zero. (Phase 3 issue 04 fixes the
  crash on the headline field; this is the series field.)

## Proof of done

- [ ] A perfectly-collinear pair produces `zscore: None` in the series and no plotted line.
- [ ] The collinearity warning is caught and surfaced as a reason. A test forces a collinear pair
      and asserts no p-value is published.
- [ ] A genuine pair with real dispersion is unaffected. A test confirms the p-value and z-score
      are produced.
- [ ] `current_spread_zscore` and `spread_series[].zscore` agree about when the value is
      unavailable. One implementation, not two.
- [ ] The frontend renders a gap for a `None` z-score.
- [ ] Add to `test_quantitative_invariants.py`.

## Notes

Two adjacent items in the same service:

- `cointegration_service.py:781-783` and `:793-795` — a `statsmodels.coint` convergence failure or
  a `polyfit` `LinAlgError` returns `None` and the pair **vanishes** from the scanner with a
  `logger.debug`. There is no `test_failed_pairs` counter in the route's coverage block
  (`analytics.py:7204-7256`, which tracks only `depth_status`, `shallow_tickers`,
  `unpairable_tickers`). An ill-conditioned but genuinely cointegrated pair is reported as "no
  pairs found". Add a counter and surface it.
- `tail_risk_service.py:366-371` — a 1-ticker universe returns `matrix: [[1.0]]`, i.e. a
  fabricated "perfect tail dependence" diagonal for a matrix with no pairs. Related to issue 22.

Refs: `../spec.md`, `backend/app/services/cointegration_service.py:781-783,793-795,810-811,865`, `backend/app/api/analytics.py:6932,7204-7256`, `backend/app/models/schemas.py:449`
