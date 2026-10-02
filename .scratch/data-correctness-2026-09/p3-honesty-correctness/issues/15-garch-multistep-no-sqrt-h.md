# 15 — GARCH "multi-step" forecast has no √h scaling

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: 14
Repo: `backend/`
Severity: **MEDIUM**

## What

`volatility_service.py:126` (docstring) says *"annualized multi-step volatility forecast"*, and
`:164-170` implements:
```python
var_steps = forecasts.variance.iloc[-1].values
mean_daily_variance = float(np.mean(var_steps))       # AVERAGE, not cumsum
ann_vol = float(np.sqrt(max(0.0, mean_daily_variance * 252.0)) / 100.0)
```

The return payload is `{"annualized_vol": …, "horizon": horizon}`.

## Why

The **mean** of per-period conditional variances × 252 is the annualized **1-day-equivalent**
volatility. `horizon` only moves it through mean reversion in σ² — never through a √h or a cumsum.

Measured on 1500 normal days:
```
horizon= 1  annualized_vol=0.197242
horizon=21  annualized_vol=0.191075
horizon=63  annualized_vol=0.190774     <-- flat; no h scaling
```

The true 63-day figure is ≈ 0.191 × √63 ≈ 1.51, not 0.191.

**User-visible:** the Vol Cone publishes `current_forecast = {annualized_vol, horizon_days: 21}`,
and a reader takes "21-day vol = 19.1%" when the true 21-day figure is ≈ 87%.

The codebase already contains the correct implementation:
`analytics_engine._cumulative_forecast_volatility:1932-1949` does the cumsum properly and **was
verified correct**.

So there are **two GARCH conventions in one codebase** for the same quantity.

## Change

- Use `np.cumsum(var_steps)` (or reuse `_cumulative_forecast_volatility`) for the h-day figure.
- Decide what the key means. If it is the annualized equivalent of the h-day horizon, keep the key
  and fix the math. If it is the 1-day-equivalent, rename the key to
  `annualized_1day_vol` and drop `horizon` from the payload, because publishing `horizon` next to
  a 1-day number is the misleading part.
- One implementation, shared with `analytics_engine`.

## Proof of done

- [ ] A multi-step forecast's value equals the cumsum-based reference. A test asserts against
      `_cumulative_forecast_volatility`.
- [ ] `horizon=63` produces a materially larger number than `horizon=1`, scaling roughly with √h
      after removing the mean-reversion effect. A test asserts the ratio is in a sane band.
- [ ] One GARCH multi-step implementation exists. Grep confirms.
- [ ] The payload key and its value agree about the horizon. A test asserts the key name matches
      the semantics.
- [ ] The Vol Cone's published forecast is the h-day figure, and the axis or tooltip says so.
- [ ] Add to `test_quantitative_invariants.py`.

## Notes

Also in this file, two degenerate-zero issues were found and should be fixed in the same pass:

- `:101-106` `calculate_ewma_volatility` returns **`0.0`** for a single observation, and
  `:148-156` passes that straight through as `{"annualized_vol": 0.0, "model": "EWMA"}` for any
  series with <30 obs. A cone then shows a **0.0% forecast**. → `None` plus a reason.
- `:185-193` a GARCH failure silently substitutes EWMA, reporting `model: "EWMA"`,
  `params.fallback: True`, and `params.error: str(e)` — **raw exception text**. The route's
  `data_status` does not reflect the substitution, so a user asking for GARCH receives EWMA
  numbers labelled as a GARCH result without being told. Surface the substitution in `data_status`
  and redact the error text.

Refs: `../spec.md`, `backend/app/services/volatility_service.py:101-106,126,148-156,164-170,185-193`, `backend/app/services/analytics_engine.py:1932-1949,2037-2049`
