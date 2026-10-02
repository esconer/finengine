# 14 — Unify the three EWMA implementations

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `backend/`
Severity: **MEDIUM**

## What

Three places implement "EWMA volatility", three different ways.

| Site | Implementation |
|---|---|
| `volatility_service.py:109-117` | Normalized exponential weights over the **full** history, **zero-mean** (`Σwᵢrᵢ²`) |
| `analytics_engine.py:2207-2211` | Seeds `var` with **full-sample `np.var(r)`** (ddof=0), then recurses over only `r[-min(len(r),60):]` |
| `regime_service.py:165,191` | `ewm(span=10).std()` — **demeaned**, and *span* semantics rather than *λ* |

All three are presented to the user simply as "EWMA".

## Why

Measured on 400 t₄-like days:
```
volatility_service = 0.171604
_ewma_forecast     = 0.170495    (-0.65%)
```

The 60-day cap alone is worth 11%: cap=20 → 0.190326, cap=∞ → 0.171604.

The functional consequence is the important part. `volatility_sizing` uses `_ewma_forecast` to
build **inverse-volatility parity weights** (`:1249`), while the Vol Cone page displays
`volatility_service`'s numbers. **The scale the sizing is computed on and the volatility the user
sees are not the same quantity.**

The regime service's version is a third thing again: `ewm().std()` demeans, which is not the
RiskMetrics estimator at all. `CONTEXT.md` §9.24 already specifies the correct form:

> *"EWMA = single-pass RiskMetrics `σ²=λσ²+(1-λ)r²` with flat term structure (no rolling-std
> pre-smooth)"*

So the codebase has a documented correct answer and three divergent implementations.

## Change

- One shared helper, implementing the `CONTEXT.md` §9.24 form exactly.
- The 60-observation cap, if intentional, becomes a **named parameter with a stated rationale** —
  not an inline `min(len(r),60)`.
- `regime_service`'s demeaning is either intentional (and then it should be named
  `ewm_std_vol`, not "EWMA") or replaced.
- All three call sites use the shared helper.

## Proof of done

- [ ] One EWMA implementation exists. Grep confirms three copies do not.
- [ ] `volatility_service` and `_ewma_forecast` return **identical** values for the same input. A
      test asserts equality.
- [ ] The shared helper matches the `CONTEXT.md` §9.24 formula. A test asserts it against a
      hand-computed reference.
- [ ] The 60-day cap is a named parameter with a comment explaining why.
- [ ] `regime_service`'s variant is either the shared helper or distinctly named.
- [ ] The Vol Cone displayed volatility and the volatility used for sizing weights are now the
      same number. A test asserts the two endpoints agree for the same input.
- [ ] Add to `test_quantitative_invariants.py`.

## Notes

The sizing/display mismatch is the real bug here, not the 0.65% numeric divergence. A user who
tunes a target volatility and then sees sizing built on a different estimator has no way to reason
about the result.

Refs: `../spec.md`, `backend/app/services/volatility_service.py:109-117`, `backend/app/services/analytics_engine.py:1249,2207-2211`, `backend/app/services/regime_service.py:165,191`, `CONTEXT.md` §9.24
