# 22 — Remaining degenerate-zero returns across the services

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `backend/`
Severity: **MEDIUM**

## What

Six places return a plausible-looking `0.0` where the truth is "unmeasurable". Ranked by how
plausible the fabricated number looks to a user.

| # | Location | Fabricated | Should be |
|---|---|---|---|
| 1 | `analytics_engine.py:2531` | `diversification_score: 0.0` on the error path | Issue 09 — `None` |
| 2 | `websocket.py:422` | `sharpe_ratio: 0.0` with `data_status: "measured"` | Issue 13 — `None` |
| 3 | `analytics_engine.py:1770-1771,1778,1786` | `sharpe_ratio = 0.0`, `sortino_ratio = 0.0` | Issue 13 — `None` |
| 4 | `cointegration_service.py:865` | `zscore: 0.0` per point | Issue 21 — `None` |
| 5 | `regime_service.py:238,241` | `cagr: 0.0`, `ann_vol: 0.0` for an unoccupied state | Issue 19 — `None` |
| 6 | `volatility_service.py:106` → `:150-156` | `annualized_vol: 0.0` from a 1-observation series | `None` + reason |

Plus three not covered by a dedicated ticket:

### a) `monte_carlo_service.py:380-383`

`expected_shortfall_vs_target = 0.0` when `prob_success == 1.0`.

Correct — nothing failed the target, so there is no shortfall. But `0.0` implies "the shortfall is
zero" rather than "no path failed". `None` plus a reason.

### b) `utils/holdings.py:450`

`total_ret = 0.0` for a **zero-day** regime overlap. `regime_service.py:371` deliberately always
emits this block, so a portfolio with no days in the current regime publishes
"0.00% return in this regime" — which reads as "the regime cost you nothing" rather than
"you have no history in this regime".

### c) `tail_risk_service.py:366-371`

A 1-ticker universe returns `matrix: [[1.0]]` — a **fabricated perfect tail dependence diagonal**
for a matrix that has no pairs. A self-correlation of 1.0 is mathematically true but presenting it
as a tail-dependence matrix implies a result that was not computed.

### d) `analytics_engine.py:1811`

`cvar_95 = var_95` when the ≤p5 tail is empty. Assigning the VaR to the CVaR is a specific
plausible-looking fabrication: it will render as two identical numbers, which looks like a stable
result rather than an absent one.

## Change

Each becomes `None` plus a reason string, following the `data_status` / `_reason` convention
already established in the codebase.

## Proof of done

- [ ] Each of the nine locations returns `None` (or a documented equivalent) instead of `0.0`.
- [ ] Each has a test asserting `None` for the degenerate case and a real value for the healthy
      case. **Both directions** — a test that only checks the degenerate case would pass against a
      function that always returns `None`.
- [ ] The frontend renders `None` as `N/A` or an em-dash at each of these sites, never `0.00`.
- [ ] The 1-ticker tail-dependence case returns an empty matrix or an explicit "insufficient
      universe" status.
- [ ] `cvar_95 != var_95` whenever a real tail exists, and is `None` when it does not.
- [ ] Add all nine to `test_quantitative_invariants.py`.
- [ ] The API schema changes appear in the OpenAPI diff, deliberately.

## Notes

This ticket is the catch-all for the `0.0`-instead-of-`None` pattern. Items 1–5 are cross-referenced
to their dedicated tickets and should be fixed there; this ticket owns 6, a, b, c, and d.

The general rule, worth writing into `CONTEXT.md` as a numbered gotcha: **a zero is a measurement.
Absence is not zero.**

Refs: `../spec.md`, `backend/app/services/analytics_engine.py:1770-1771,1778,1786,1811,2531`, `backend/app/api/websocket.py:422`, `backend/app/services/cointegration_service.py:865`, `backend/app/services/regime_service.py:238,241,371`, `backend/app/services/volatility_service.py:106,150-156`, `backend/app/services/monte_carlo_service.py:380-383`, `backend/app/utils/holdings.py:450`, `backend/app/services/tail_risk_service.py:366-371`
