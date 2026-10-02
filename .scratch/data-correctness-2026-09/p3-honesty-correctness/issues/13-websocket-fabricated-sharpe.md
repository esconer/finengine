# 13 — WebSocket broadcasts a fabricated Sharpe as "measured"

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: 10
Repo: `backend/`
Severity: **HIGH**

## What

`websocket.py:413-424`:
```python
if sharpe is not None and sortino is not None and vol is not None:
    analytics_status = "measured"      # :424
```

The values come from `analytics_engine.py:1766-1786`, where `_calculate_basic_metrics`
**fabricates** zeros in two branches:

```python
if len(returns) < 10:
    sharpe_ratio = 0.0                  # :1770-1771
    sortino_ratio = 0.0                 # :1770-1771
...
if annual_volatility == 0:
    sharpe_ratio = 0.0                  # :1778
if downside_deviation == 0:
    sortino_ratio = 0.0                 # :1786
```

## Why

Those are `0.0`, **not** `None`, so the `is not None` guard passes and the value is broadcast with
`data_status: "measured"`.

A live **"Sharpe 0.00"** tile appears on every connected dashboard client for a young or
zero-variance portfolio, labelled as a measurement.

It also defeats the `unavailable` status the WebSocket **already has a code path for** — the
mechanism exists and is simply unreachable for this case.

## Trigger

`6 ≤ price_rows < 15` (yields 5–13 return rows, hitting the `<10` branch), or any book with a
constant portfolio-return series. A newly-seeded portfolio hits this on day one.

## Change

- Return `None` (not `0.0`) for Sharpe and Sortino on a short or zero-variance window.
- The WS guard then correctly falls through to `data_status: "unavailable"`.
- Apply the same to the `< 10 observations` branch: a Sharpe over 5 observations is not a Sharpe.
  `CONTEXT.md` §9.10 already establishes this principle for individual positions
  ("For newly listed assets with N < 10 trading days, constrain the Sharpe ratio to 0.00 and emit
  UI warnings") — note that even §9.10 prescribes `0.00`, which this ticket argues should be
  `N/A`. **Flag this to the owner: §9.10 may need updating to match the §9.23 principle.**

## Proof of done

- [ ] A 5-observation series returns `sharpe_ratio: None`, not `0.0`.
- [ ] A zero-variance series returns `sharpe_ratio: None`.
- [ ] The WebSocket publishes `data_status: "unavailable"` in both cases, and the reachable
      `unavailable` path is now exercised. A test asserts it.
- [ ] The client renders "N/A", not "0.00".
- [ ] A portfolio with sufficient history still publishes a real Sharpe with `"measured"`.
- [ ] The frontend renders a distinguishable state for `"unavailable"` on the live tiles.
- [ ] Add to `test_quantitative_invariants.py`.
- [ ] `CONTEXT.md` §9.10 is updated if the owner agrees that `0.00` should become `N/A`.

## Notes

The trigger is a **new portfolio**, which is the most common state for a new user. So this is
likely to be the first thing a new user sees.

Refs: `../spec.md`, `backend/app/api/websocket.py:413-424`, `backend/app/services/analytics_engine.py:1766-1786`, `CONTEXT.md` §9.10, §9.23
