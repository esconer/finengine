# 11 — Black-Litterman publishes the wrong Sharpe

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `backend/`
Severity: **HIGH**

## What

`optimization_service.py:56-63` declares:
```python
STRATEGY_OBJECTIVES = { …, "black_litterman": "maximum Sharpe of the Black-Litterman posterior" }
```

and `:160` sets `expected_sharpe_was_the_optimised_objective: True`, with `:163-165` supplying
`expected_sharpe_basis`.

The objective actually solved at `:503-504` and `:513-517` maximises
`(μ_BL − r_f) / √(wᵀ Σ_BL w)` over `mu_bl` / `cov_bl`.

But `optimize()` then computes at `:557` and publishes at `:582`:
```python
moments = _moments(mu, cov, w_vec, rf)      # ← raw SAMPLE mu/cov
```

## Why

The payload makes a **false methodological claim** to a user comparing BL against
`min_vol`/`hrp`/`max_sharpe`, and the number itself is the wrong one for the decision.

Measured (4 assets, 500 days, 2 absolute views):
```
expected_sharpe (published, sample mu)  = 0.5494
BL-posterior Sharpe actually maximised = 0.4950
discrepancy                            = -0.0544   (published is 11% high)
```

## Change

Either:

- **Option A (preferred)** — return `mu_bl` and `cov_bl` from `_black_litterman` and compute
  `expected_sharpe` from them. Then the published number is genuinely the objective value, and the
  claim is true.
- **Option B** — remove `black_litterman` from `SHARPE_OBJECTIVE_STRATEGIES` and correct
  `expected_sharpe_basis` to say the Sharpe is computed on sample moments, not the posterior.

Option A is better: the BL posterior Sharpe is the number the user actually wants, since it
embeds their views.

Whichever is chosen, `expected_sharpe_basis` must describe what was computed, in plain language,
and the frontend must render it.

## Proof of done

- [ ] The published `expected_sharpe` equals `(μ_BL − r_f)/√(wᵀ Σ_BL w)` at the published weights.
      A test asserts this identity.
- [ ] `expected_sharpe_basis` describes the actual computation.
- [ ] `expected_sharpe_was_the_optimised_objective` is `True` only when it is true.
- [ ] The frontend renders `expected_sharpe_basis` so the user can see the methodology.
- [ ] A test with zero views (BL reducing to market equilibrium) behaves sensibly.
- [ ] Add to `test_quantitative_invariants.py`.

## Notes

While in this file, two adjacent issues were found and should be fixed in the same pass:

- **`min_cvar` claims "at the requested beta"** (`:60`) but `OptimizeRequest`
  (`analytics.py:91-98`) has **no beta or confidence field**, so `min_cvar` is always 95%. Either
  add the field or correct the claim.
- **Black-Litterman's `tau`, `Omega`, and `P` prior shrinkage** should be checked against the
  standard formulation while the file is open. The audit could not confirm these are wrong, but
  they were not verified as correct either.

Refs: `../spec.md`, `backend/app/services/optimization_service.py:56-63,60,160,163-165,503-504,513-517,557,582`, `backend/app/api/analytics.py:85,91-98`
