# 10 — `annual_return` and `annual_volatility` ship on different time bases

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `backend/`
Severity: **HIGH**

## What

`analytics_engine.py:1766-1771`:
```python
annual_return = float(returns.sum())      # un-annualized multi-day cumulative
annual_volatility = ... std(...) * sqrt(252)   # annualized
```

The dict key is `annual_return`. The sibling key on line 1769 **is** annualized. The in-code
comment admits it computes a "period cumulative return".

## Why

**Return and volatility in the same object are on different time bases.** That is exactly the
class of unit error the whole phase is about.

Measured: 5 daily returns of +1%, +2%, −1%, +0.5%, +3% publish `annual_return = 0.055` (5.5%),
while the true annualized figure is **2.772 (277%)**. A **50× understatement** of a position's
annual return.

## Reachability — read this carefully

`MIN_ANNUALIZE_DAYS = 30` (`app/utils/holdings.py:35`) and `apply_annualization_gate`
(`holdings.py:356-367`, applied at `analytics.py:3083-3095`, `:2961-2965`, `:5102`) **null this on
the `analytics.py` routes**.

It is **live on `app/api/websocket.py:413`**, which calls `calculate_portfolio_metrics` and consumes
the same block with **no gate at all** (see issue 13).

So this is a latent engine-contract defect that already has one ungated consumer. Fix the engine,
and the WS consumer inherits the fix.

## Change

Either:

- **Option A** — `annual_return = returns.mean() * 252`, keeping the key and its meaning.
- **Option B** — rename the key to `cumulative_return` and null `annual_volatility` in the same
  branch, so the two never ship on mismatched bases.

Option A is simpler and keeps the key contract. Option B is more honest when the window is short.

Whichever is chosen: **never ship an annualized return beside an annualized volatility unless both
are annualized**, and never ship a cumulative return under a key that says "annual".

## Proof of done

- [ ] For any window, `annual_return` and `annual_volatility` are on the same time base. A test
      asserts this across window lengths from 5 to 252 observations.
- [ ] The 5-observation case publishes either a correctly annualized return or a `None` — not
      `0.055`.
- [ ] `websocket.py:413` publishes a consistent pair. This is the test that proves the ungated
      consumer is fixed.
- [ ] If Option B: any consumer of the old key is updated, and the API change appears in the
      OpenAPI diff.
- [ ] Add to `test_quantitative_invariants.py`.
- [ ] Audit the other metrics in `_calculate_basic_metrics` for the same time-base mismatch.

## Notes

The two-window split documented in `CONTEXT.md` §9.23 is the right pattern here: return `N/A` plus a
flag when the window is too short to annualize, exactly as `apply_annualization_gate` already does
on the routes.

Refs: `../spec.md`, `backend/app/services/analytics_engine.py:1766-1771,1769,1770-1771,1778,1786`, `backend/app/utils/holdings.py:35,356-367`, `backend/app/api/analytics.py:2961-2965,3083-3095,5102`, `backend/app/api/websocket.py:413`
