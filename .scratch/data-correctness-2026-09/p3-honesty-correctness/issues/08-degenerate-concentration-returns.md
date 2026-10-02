# 08 — Degenerate concentration returns

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `backend/`
Severity: **HIGH**

## What

`analytics_engine.py:674` and `:2532`

`diversification_ratio = effective_positions / n_assets` with **no N≤1 guard**.

## Why

A single-holding portfolio publishes, simultaneously:

```
{'RELIANCE.NS': 1.0} -> herfindahl_index=1.0  diversification_score=0.0
                        diversification_ratio=1.0   <-- contradicts
```

`diversification_score` is correctly guarded to `0.0` on line 673. `diversification_ratio` is not.

`CONTEXT.md` §9.16 states a single-holding portfolio (N≤1) "**must strictly render 0%
diversification score**". The ratio field reads "1.00", which a consumer will interpret as
"perfectly diversified" — the exact opposite of the score sitting next to it.

This is also the same root defect as issue 09 in a different location: the guarded path
(`:669-674`) and the error path (`:2523-2536`) have **inverted semantics** for the same field.

## Change

Guard N≤1 → `diversification_ratio = 0.0` (or `None`), matching line 673. Apply the guard in
`_empty_concentration` too, so the two paths agree.

Prefer `None` over `0.0` for the error path, since "no positions" is genuinely different from
"one position". For the N=1 path, `0.0` is defensible since the concentration is real and maximal.

Decide once, apply in both places, and add a shared helper so the two paths cannot diverge again.

## Proof of done

- [ ] A 1-position portfolio publishes `diversification_score: 0.0` **and** a consistent
      `diversification_ratio`. A test asserts the two are not contradictory.
- [ ] `_empty_concentration()` does not publish `diversification_ratio: 1.0`.
- [ ] A 5-position equal-weight portfolio publishes the expected `effective_positions = 5.0` and
      `diversification_ratio = 1.0` — the guard must not break the legitimate case.
- [ ] The concentration function and the empty-concentration function share one implementation of
      the guard. Grep confirms.
- [ ] Add to `test_quantitative_invariants.py`.

## Notes

Extend to the sibling statistics in the same block: `effective_positions` and `gini_coefficient`
should also be `None` rather than `0.0` on the empty path, per issue 09.

Refs: `../spec.md`, `backend/app/services/analytics_engine.py:669-674,2523-2536`, `CONTEXT.md` §9.16
