# QH-03 — GARCH/EGARCH rescaling for optimizer convergence

Status: closed
Type: task
Blocked by: —

## What

`_garch_forecast` (~line 762) and `_egarch_forecast` (~line 792) in `analytics_engine.py`
pass raw daily returns (magnitude ~0.01) to `arch_model()` without rescaling. The `arch`
library's optimizer frequently fails to converge on such small values, producing inaccurate
volatility forecasts. These failures are silently caught by the broad `try/except` and
mapped to `_empty_forecast()` — the user sees zeros instead of a useful forecast.

## Fix

Pass `rescale=True` to `arch_model()`, which auto-scales returns to percentage units
internally and unscales the output. This is the library's recommended practice.

## Why

Forecast-risk page shows empty/zero forecasts for many real tickers when it should show
valid GARCH projections. The `arch` package documentation explicitly warns about this.

## Proof of done
- [ ] GARCH forecast for RELIANCE.NS returns non-zero vol values
- [ ] No `ConvergenceWarning` in server logs for typical NSE tickers
- [ ] Test: feed small-magnitude returns, assert forecast vol > 0
