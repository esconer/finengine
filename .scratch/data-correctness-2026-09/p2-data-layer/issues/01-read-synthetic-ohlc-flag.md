# 01 — Read `bfinance_synthetic_ohlc` at the ingestion boundary

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: Phase 1 issue 03
Repo: `backend/`
Severity: **CRITICAL — root cause RC1**

## What

`data_service.py:924` ingests a bfinance frame without ever inspecting the flag bfinance sets on
it.

bfinance sets, on **every** frame it returns:
```python
# bfinance/src/bfinance/market/ohlcv.py:165,249
df.attrs["bfinance_synthetic_ohlc"] = True   # when O/H/L are fabricated
```

Nothing on the finengine side reads `df.attrs` at all.

## Why

Until Phase 1 issue 03 lands, bfinance returns a frame with:

```python
Open = prev_close.shift(1).bfill()
High = max(O, C) * 1.002
Low  = min(O, C) * 0.998
```

Measured 0.4–0.6% mean error against yfinance, and a max/min envelope is **mathematically
incapable** of representing a real intraday range.

Every quantitative page in this app computes on that path: realized vol, GARCH/EWMA forecasts,
EVT-POT tail fits, Student-t copulas, vol cones, stress-test elasticities, cointegration spreads,
Parkinson volatility, and ₹-denominated average daily volume.

The flag already exists. It is one `attrs` read away. This ticket is the guardrail that makes the
problem **visible** even before the underlying fix ships, and it prevents the problem recurring if
a future bfinance change reintroduces a synthetic path.

## Proof of done

- [ ] `data_service.py` inspects `df.attrs.get("bfinance_synthetic_ohlc")` at the ingestion
      boundary and persists the value.
- [ ] A synthetic frame is either **rejected** (configurable) or stored with
      `synthetic_ohlc = 1` and surfaced with an explicit `synthetic_ohlc: true` marker on every
      response that uses it. Silent acceptance is not an option.
- [ ] The marker propagates through `StockQuoteResponse`, the OHLCV endpoint, and the analytics
      responses, so a consumer can always tell.
- [ ] Analytics that depend on intraday range (ATR, Parkinson, true range, `(High-Low)/Close`,
      gap detection) are **disabled or flagged** when the frame is synthetic, since the input
      cannot support them. Returning a number computed from a fabricated envelope is worse than
      returning `None`.
- [ ] A test constructs a synthetic-flagged frame and asserts the marker reaches the response.
- [ ] A test constructs a real frame and asserts no marker.
- [ ] An unknown/absent flag is treated as **unknown provenance**, not as real. Fail toward
      disclosure.
- [ ] The flag check happens **before** persistence, so a synthetic frame never lands in
      `stock_timeseries` unmarked.

## Notes

This is the highest-value single change in Phase 2 for its size — roughly ten lines plus tests. It
converts a silent correctness problem into a visible one, which is the precondition for trusting
every other number in the app.

Refs: `../spec.md`, `app/services/data_service.py:924`, Phase 1 issue 03
