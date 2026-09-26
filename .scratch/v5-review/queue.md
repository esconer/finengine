# Remediation queue — v5 review findings

One mission per wave, run **sequentially**. Six persona reviewers produced ~30
findings; this is the ordered queue to close them. State lives here so the loop
resumes correctly after any interruption.

**Why sequential, not parallel:** the last two fixes each landed in
`analytics.py` / `analytics_engine.py`, and each *created a new contradiction
that had to be integrated before the next could start*. QM-1 moved
`measured_window.start` to 2026-08-25 and tripped XS-010 against
`holding_window_start`. Parallel edits to those two files have already cost two
incidents in this repo. Concurrency buys nothing here and risks the work.

**Definition of done for every wave:** the owning agent's tests pass, the full
backend suite shows no new failures beyond the 5 pre-existing, `ruff check app
tests` is clean, the integrator re-verifies the claim independently, and the
wave is committed separately.

**Pre-existing failures — not defects, do not chase:** 3 order-dependent
(`test_rebalance_rejects_zero_portfolio_value`,
`test_summary_passes_benchmark_to_risk_scoring`,
`test_stock_data_reports_source_and_from_cache`) and 2 error-wording
(`test_config_get_propagates_errors`,
`test_full_profile_runtime_error_maps_to_503`). All pass in isolation.

**Standing limitation:** the audit gate is not a truth gate. 8 injected defects
pass, including relabelling all 14 positions USD at `fx_rate 1`. Green means no
known pattern matched. No rule in the table can become one; that needs
recomputation from a published input frame, which is a different tool.

---

## Baseline at queue start

`export_id portfolio-2e408e137bef` · gate **50/55** · suite **1337 passed /
5 failed** · 55 rules, 10 added this round.

Gate reds: `ENV-016`, `ENV-019`, `ENV-020`, `ENV-021`, `XS-001`.

## The queue

| # | Wave | Sev | Target | Gate |
|---|------|-----|--------|------|
| 1 | PA-1 optimizer moments | **P0** | `optimization_service.py` | — |
| 2 | Disclosure sweep (6 items) | P0/P1 | `analytics.py`, `portfolio.py` | 50→52 |
| 3 | ENV-020 uncertainty, systemic | P0 | multi-file | 52→53 |
| 4 | XS-001 root cause | P0 | unknown — **investigate first** | 53→**55/55** |
| 5 | QM-2 benchmark window | P0 | `analytics.py` | — |
| 6 | RL-3 risk score pinning | P0 | `analytics_engine.py` | — |
| 7 | RL-2 fat-tail flag, RL-1 liq days, RL-6 sector, RL-7 look-through | P0/P1 | 2 files | — |
| 8 | DI-1/2/5 + ENV-019 trades | P0 | `portfolio.py`, `analytics.py` | (in wave 2) |
| 9 | SI-11 regime labels, SI-7 vol-cone, AD-9 one-sided correlation | P1 | `regime_service.py`, `volatility_service.py`, `correlation_service.py` | — |
| 10 | AD-16 snapshot consistency, AD-8 cost basis disclosure | P1 | `portfolio.py` | — |
| 11 | Conventions: Calmar, rf, stress maxDD ×1.15, PA-3 count, PA-4 two Sharpes | P1 | 2 files | — |

### Ordering rationale

- **PA-1 first** because it is the worst open defect: a sign-inverted Sharpe on a
  recommended portfolio. It was in the consolidated report the whole time and I
  did not assign it in the first wave — a triage miss, not a discovery failure.
- **Wave 2 before wave 3** so a fully-green gate is reached by wave 4, giving a
  clean checkpoint before the structural work.
- **Wave 4 is an investigate wave, not an implement wave.** It is the one open
  P0 whose cause is unknown: a *wider* 90-day request returns *less* history
  (2026-08-25) than a narrower one (2026-01-19), and no position's `added_on`
  explains it. Do not send an implementer at a bug whose location is unknown.
- **PA-2 folds into wave 1**: `hrp` does not maximise Sharpe, so publishing
  `expected_sharpe` needs a stated basis or removal, and there is no
  current-portfolio objective on the same 170-row sample to answer "is this
  better than what I hold?".

## Verification discipline

Every wave is re-derived by the integrator before it is committed. Three agent
claims have already needed correcting, and one correction of mine was itself
wrong (`QM-4`: I assumed the sizing scale was built from `current_volatility`;
it uses a third figure, `0.115802`, and the agent was right). Do not promote a
subagent's finding to a stronger claim than it made.

## Confirmed clean — do not re-litigate

Pair p-values **are** the right test's p-values (`mackinnonp` max Δ 2.4e-05, 0
monotonicity violations). No hardcoded p-values. Stationarity is not confused
with cointegration. `regime` and `india_flows` disclosure is exemplary. SELECTIPO
contamination does not exist (+4.0% portfolio vol). Weights are bit-identical in
4 places and provably current market value on a book that drifted 5.36pp. No
lookahead bias in the optimizer. `concentration` and `risk_contribution`
arithmetic is exact. Stress shocks are multiplicative with the post-shock book
re-normalising to 1.0000000000. `sum(trades.amount)` equals
`financing_requirement` to the paisa.
