# 09 — `_empty_concentration` fabricates a minimum-risk score

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `backend/`
Severity: **HIGH**

## What

`analytics_engine.py:2523-2536` returns, with `error: "No position data available"`:

```python
herfindahl_index: 0.0
effective_positions: 0.0
diversification_score: 0.0
diversification_ratio: 1.0
gini_coefficient: 0.0
```

Consumed at `:1559` (scored) and `:1675-1684` (weighted in) — **never added to `excluded`** — and
at `analytics.py:5080-5083`.

## Why

Every other leg of the risk score handles this correctly. The file's own comment at `:1562-1566`
says:

> *"An empty series is UNMEASURED … return null + exclude, exactly as the correlation leg below
> does"*

The volatility, correlation, factor, and market legs all return `None` + `excluded`. Concentration
is **the one leg that breaks that rule.**

Consequence: an **unmeasurable** concentration leg contributes a hard `0.0` to `overall_score` —
`min(30, 0.0 * 100) = 0.0` — which is the **minimum-risk value**. So an unmeasurable input biases
the risk grade toward LOW/MEDIUM. It also ships `concentration_score: 0.0` on the dashboard
summary.

The internal contradiction is explicit: `_empty_liquidity` at `:2538-2540` carries a comment
warning that returning a plausible `overall_score=5.0` "made an absence" — and
`_empty_concentration`, two methods above, does exactly that.

## Trigger

`risk_scoring` with `weights` truthy but every weight ≤ 0 or non-finite (e.g. `{'A': 0.0}`).
`concentration_analysis` filters them all out (`:642-648`) and returns the empty block.
`risk_scoring`'s only guard is `if not weights` (`:1537`).

## Change

- Return `None` for every statistic; keep the `error` key.
- In `risk_scoring`, append `'concentration'` to `excluded` with a reason — matching the treatment
  the other legs already receive.
- Apply the same treatment to any other leg discovered to have the same pattern while auditing.

## Proof of done

- [ ] `_empty_concentration()` returns `None` for every statistic.
- [ ] `risk_scoring` adds `'concentration'` to `excluded` with a reason when the leg is empty.
- [ ] A test with `weights = {'A': 0.0}` asserts `overall_score` is computed from the remaining
      legs only, and that the score is **not** lower than a score computed with a genuinely
      diversified portfolio. This is the meaningful regression test.
- [ ] The dashboard summary no longer publishes `concentration_score: 0.0` for an empty portfolio.
- [ ] Add to `test_quantitative_invariants.py`.
- [ ] Audit the other `_empty_*` functions for the same pattern and confirm each either returns
      `None` or is genuinely measurable. `_empty_liquidity` is the reference for correct behaviour.

## Notes

The general rule this ticket enforces: **an absent input must never lower a risk score.** An
unmeasurable leg should be excluded and disclosed, not scored as zero.

Refs: `../spec.md`, `backend/app/services/analytics_engine.py:642-648,1537,1559,1562-1566,1675-1684,2523-2536,2538-2540`, `backend/app/api/analytics.py:5080-5083`
