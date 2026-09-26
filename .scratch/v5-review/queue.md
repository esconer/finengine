# Remediation queue — v5 review findings

One mission per wave. Six persona reviewers produced ~30 findings; this is the
ordered queue that closed them. State lives here so the loop resumes correctly
after any interruption.

**Why sequential, not parallel:** the fixes kept landing in `analytics.py` /
`analytics_engine.py`, and each one *created a new contradiction that had to be
integrated before the next could start*. QM-1 moved `measured_window.start` to
2026-08-25 and tripped XS-010 against `holding_window_start`. Parallel edits to
those two files have cost two incidents in this repo. Where file ownership was
genuinely disjoint the waves DID run in parallel — waves 4, 6, 9 and 10 at once
— and that was safe precisely because the split was by file, not by convenience.

**Definition of done for every wave:** the owning agent's tests pass, the full
backend suite shows no new failures beyond the 5 pre-existing, `ruff check app
tests` is clean, the integrator re-derives the claim independently, and the wave
is committed separately.

**Pre-existing failures — not defects, do not chase:** 3 order-dependent
(`test_rebalance_rejects_zero_portfolio_value`,
`test_summary_passes_benchmark_to_risk_scoring`,
`test_stock_data_reports_source_and_from_cache`) and 2 error-wording
(`test_config_get_propagates_errors`,
`test_full_profile_runtime_error_maps_to_503`). All pass in isolation.

**Standing limitation — the gate is NOT a truth gate.** 8 injected defects
still pass, including relabelling all 14 positions USD at `fx_rate 1` and a
Sharpe inflated to 99. No rule in the table asks whether a number is *true*.
Green means "no known pattern matched." Making it a truth gate requires
recomputation from a published input frame — a different tool, not a bigger
rule table.

---

## Final state

**Gate 55/55, zero reds.** Suite **1611 passed / 5 failed** (the 5 above),
ruff clean, on a single uncontended run.

| Export | Provenance |
|---|---|
| `v5.json` (876 KB) | the reviewed pre-fix artifact, 10 red |
| `v17.json` (825 KB) | current, `portfolio-83c484b9eec5`, 55/55 |

| # | Wave | Sev | Outcome |
|---|------|-----|---------|
| 1 | PA-1 optimizer moments | P0 | `11ebcae` — same weights, every moment moved. Fixed; Sharpe no longer mislabelled. |
| 2 | Disclosure sweep (6) | P0/P1 | `cc0410a` — 50→53 |
| 3 | ENV-020 uncertainty | P0 | `6e3268d` — 53→54; +64% artifact size, see cost note |
| 4 | XS-001 | P0 | `22062ed` — **54→55, gate closed** |
| 5 | QM-2 benchmark window | P0 | OPEN |
| 6 | RL-3 risk-score pinning | P0 | `f38d2a5` — disclosed, not re-weighted (product decision) |
| 7 | RL-2/RL-1/RL-6/RL-7 | P0/P1 | OPEN |
| 9 | SI-11 regime / SI-7 cone / AD-9 | P1 | closed — vol-cone withholds all 5 ranks; correlation now two-sided |
| 10 | AD-16 snapshot / AD-8 costs | P1 | `e88bbe3` |
| 11 | Conventions batch | P1 | OPEN |

## Open, and not tracked by any rule

- **`risk_contribution` 500s in every export.** No rule catches it; the
  section is simply `unavailable`. Now the most visible defect in the artifact.
- **Per-state `ann_ret` is not withheld** below ~30 state-days, though
  `portfolio_in_current_regime` does withhold. Deliberate: a test outside the
  wave's file set consumes the value, so adding the gate is a separate mission.
- **`historical_threshold_10th` needed a schema change** to become
  machine-readable; done in the integrator pass, since no wave owned
  `app/models/schemas.py` at the time.
- **The export is 825 KB**, up from 453 KB before this queue, almost entirely
  the uncertainty blocks. Right trade for not publishing naked point estimates —
  but an agent reading it pays ~80% more tokens. If the consumer is a
  small-context agent, a per-section opt-in would be better.
- **The risk score still double-counts volatility and pins a quarter of its
  weight.** Disclosed in full, deliberately not re-weighted: any change moves
  `overall_score` and can flip `risk_level`. That is the user's call.
- **NIFTYIETF's price gaps** — genuine exchange/vendor gap or cache artifact?
  Undetermined. The artifact publishes no per-leg missing dates.
- **`correlation` sub-score of exactly 0.0** is reachable from a *measured*
  negative average correlation via `max(0, avg)`. NUM-018 tolerates it only
  because `avg_pairwise_correlation` is published as evidence.
- **`components` values are numpy scalars** before JSON. Harmless today.

## Corrections to the review, on the record

Six headline numbers did not survive verification. Recorded so they are not
re-cited:

1. PA-1 was reported as a 25.93pp error with a **sign inversion**. The code
   defect is real and proven at unit level, but the live error is **8.55pp** and
   the live Sharpe is positive before and after. The 25.93pp figure came from a
   reviewer's own `mu`/`cov`, not the service's.
2. MAFANG was flagged as "5.4x overweight into the thinnest name with a ≥1.00%
   vol floor". It ranks **8 of 14** on volatility; the thinnest is NIFTYIETF; the
   1.00% was a Cauchy–Schwarz feasibility bound, not a measurement. Against
   equal weight it is 2.08x, not 5.4x.
3. `performance_history` was named as the XS-001 subject. The rule **excludes it
   by construction** — the rule's own docstring cites that exact date. The real
   defect was three blocks *mislabelling* their count population.
4. `model_observation_count` was reported as "not the regression sample". It is
   `38` with scope `active_benchmark_overlap_return_rows`, equal to
   `factor_model`'s own count. The `36` came from an older export.
5. The vol-cone's pre-fix `percentile_rank` was reported as `1.9` in one place
   and `88.8` in another. Neither matches the live book. Now moot — all five
   windows withhold the rank.
6. Two rules I wrote were themselves broken: `ENV-012` tested membership rather
   than ordering, and `ENV-016` exempted `available` sections — the exact status
   every P0 carried.

## Confirmed clean — do not re-litigate

Pair p-values **are** the right test's p-values (`mackinnonp` max Δ 2.4e-05, 0
monotonicity violations). No hardcoded p-values. Stationarity is not confused
with cointegration. SELECTIPO contamination does not exist (+4.0% portfolio
vol). Position arithmetic is exact: 7 identities × 14 positions at delta 0.00e+00.
Weights bit-identical in 4 places. No lookahead bias in the optimizer.
`concentration` arithmetic exact. Stress shocks multiplicative, post-shock book
re-normalising to 1.0000000000. `sum(trades.amount)` equals
`financing_requirement` to the paisa. The optimizer's HRP allocation is
monotonically inverse-vol at the extremes — the alignment fix alone explains its
moments, there is no second defect there. `regime`'s transition-matrix
provenance and n=19 withholding are exemplary and were not regressed.
