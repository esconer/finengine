# 11 — Monte Carlo goal engine

Status: resolved
Type: task
Blocked by: 05

## What (shipped 2026-08-26)
`app/services/monte_carlo_service.py` (not simulation_service.py — kept next to sibling
services): THREE engines, all library-first per repo principle —
- gbm: numpy closed-form GBM calibrated on historical mu/sigma
- student_t: scipy.stats.t fit + analytic-moment innovations, winsorized ±8z (fat tails,
  df exposed as `student_t_df` diagnostic)
- bootstrap: **arch.bootstrap.StationaryBootstrap** (Politis-Romano; arch was already a
  dependency) — chains resamples for horizons longer than history
16 service tests (determinism, monotonic percentiles, bounds, near-Cauchy finiteness,
long-horizon chaining, invalid inputs) + numeric property audit vs closed forms.
Endpoint `POST /api/v1/analytics/monte-carlo` {target_value, horizon_years, initial_value?,
method?, num_paths?, seed?} — initial defaults to DB market value.
Frontend `/dashboard/monte-carlo`: target input, horizon slider, engine segmented control,
P(goal) MetricCards, SVG fan chart (5/25/50/75/95 bands + target line), below-coin-flip
insight, disclaimer.

## Proof of done
- [x] Same inputs → deterministic results (seeded; test asserts exact equality).
- [x] P(goal) responds sensibly: monotonic in target (property check), live demo
      ₹2L target → sub-coin-flip with honest median callout; screenshot
      `.impeccable/review/desktop-monte-carlo-results.png`.
- Note: drawdown-distribution stats from original ticket not included (percentile fan +
      shortfall cover the "how bad can it get" question); revisit if needed.
