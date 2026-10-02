# 19 — Unoccupied HMM states are ranked on a fabricated `0.0`

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `backend/`
Severity: **MEDIUM**

## What

`regime_service.py:236-248` — in the `n_sub == 0` branch:
```python
cagr  = 0.0
ann_v = 0.0
```

These feed `_label_states_by_risk` at `:252`, which sorts by `cagr` at `:48-68` and assigns
`crisis` / `calm` / `bull`.

## Why

An **unoccupied** state — one the HMM never visited in the sample — receives `cagr = 0.0`, which
then competes in `sort_values("cagr")` and can be crowned **"calm"** or even **"bull"**, published
with `historical_days_pct: 0.0` and `ann_vol: 0.0`.

A state that never occurred is being given a regime label and a performance figure.

## Two adjacent defects in the same function

### a) No tie-break or minimum-separation guard

`:60` sorts with no tie-break. Two states whose CAGRs differ by 0.01% can swap `crisis` ↔ `calm`
between refreshes — **silently inverting every downstream regime series**, because the label is
attached by rank rather than by fitted property.

### b) A silent formula switch inside a field named `cagr`

`regime_service.py:238` and `holdings.py:465` — when `cum_p <= 0`, the code silently switches from
geometric to arithmetic (`mean() * 252`) **inside a field named `cagr`**. That arithmetic value is
then used for the label ordering. Two different quantities share one name.

## Change

- `None` for an unoccupied state's `cagr` and `ann_vol`.
- Exclude `None` states from the label ordering. Label them `state_<n>` — the mechanism already
  exists at `:57-58` for the non-3-state case.
- Add a minimum-separation guard to `_label_states_by_risk`. If two states' CAGRs are within a
  tolerance, the labels are ambiguous and the response should say so rather than pick arbitrarily.
- Either rename the fallback field or move the arithmetic fallback out of a `cagr`-named key.
  `cagr` should mean CAGR or nothing.

## Proof of done

- [ ] A 3-state fit where one component collapses produces `cagr: None` for that state and a
      `state_<n>`-style label. A test forces this condition.
- [ ] No state is labelled `crisis`/`calm`/`bull` with `historical_days_pct: 0.0`.
- [ ] Two states within the separation tolerance produce an explicit "labels ambiguous" flag
      rather than an arbitrary assignment.
- [ ] The same fit run twice gives the same labels. A test asserts stability.
- [ ] The geometric/arithmetic fallback is either in a distinctly named field or removed.
- [ ] The regime page renders the unoccupied state honestly, and the timeline is unaffected.
- [ ] Add to `test_quantitative_invariants.py`.

## Notes

Fix alongside issue 20 — both are about the HMM being trusted more than it deserves. And note
`CONTEXT.md`'s own anti-pattern guidance: HMM regimes on `^NSEI` alone are a low-identification
problem and **must never gate capital allocation**. That constraint becomes binding when Phase 5
issue 21 is considered.

Refs: `../spec.md`, `backend/app/services/regime_service.py:48-68,57-58,60,165,191,226-228,236-248,252,371`, `backend/app/utils/holdings.py:450,465`
