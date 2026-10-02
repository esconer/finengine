# 03 — Tracking error, active risk, information ratio, capture ratios

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: Phase 3 issue 27
Repo: `backend/`
Effort: S | Score: 40

## What

Add the active-risk metric family. Currently **zero occurrences** of `tracking_error` or
`information_ratio` anywhere in the codebase outside a debug string list.

| Metric | Formula |
|---|---|
| Tracking error | `σ(active_return)`, annualised |
| Active return | `r_p − r_b` |
| Information ratio | `mean(active) / σ(active) × √annualisation` |
| Up / down capture | Return during benchmark up periods / during down periods |
| Beta (already present) | `cov(r_p, r_b) / var(r_b)` |

## Why

**"Am I adding value, or just buying the index?"** is the most-asked question about any equity book,
and the app cannot answer it.

The benchmark series and the portfolio return series both already exist. This is close to pure
derivation.

It also completes issue 02's story: shrinkage de-noises the optimiser, and tracking error tells you
whether the de-noised result is actually any good.

## Change

- A new service or a block on the existing tear-sheet / risk-summary response.
- Against the **Total Return** benchmark (Phase 3 issue 27), not the price index. Tracking error
  against a price index is inflated by the benchmark's dividend gap and therefore not comparable to
  any published number.
- `region` and multi-currency: the active return must be computed on returns in a **consistent
  currency**. Phase 5 issue 19 (FX history) matters here — a single live FX rate applied to the
  whole history fabricates returns on any non-INR leg.
- Report over multiple windows (1y, 3y, since inception) rather than a single number.

## Proof of done

- [ ] Each metric is validated against a **closed-form reference** on a constructed input.
- [ ] Capture ratios are `None` when the benchmark had no up (or no down) periods in the window,
      with a reason. A test forces that case.
- [ ] Tracking error is `0.0` only when the portfolio exactly equals the benchmark. A test
      asserts a small non-zero value for a genuinely different portfolio.
- [ ] The benchmark used is Total Return, and the response states which index vintage.
- [ ] Multiple windows are reported, and a window with insufficient data returns `None` with a
      reason.
- [ ] Non-INR legs use a time-varying FX rate once issue 19 lands; until then, the response states
      that FX is applied at a single rate and is therefore approximate.
- [ ] The response declares units for every metric.
- [ ] A frontend section renders these, with the empty states handled.

## Notes

The capture ratios are the most intuitive of the set for a non-specialist user — "you captured 112%
of the market's up moves and 94% of its down moves" is immediately interpretable. Lead with those
rather than the information ratio.

Barra and FactSet both treat active risk as a first-class reporting category, and the
risk-budgeting literature treats `RC_i = b_i · R(x)` as the primitive. This metric family is the
missing half of the existing Euler risk contribution work.

Refs: `../spec.md`, Phase 3 issue 27, Phase 5 issues 02, 19, 20
