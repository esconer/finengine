# Library parameterisation traps — assessed against THIS codebase

External reference research (librarian, 2026-10-02) against statsmodels 0.15.0, arch 8.0.0,
SciPy 1.18.1, scikit-learn 1.9.1, cvxpy 1.9.3, quantstats 0.0.86, yfinance 1.7.0, plus the
installed source in `backend/.venv`. Full sheet with URLs lives in the session transcript; this
file records the **verdict per trap for this repo**, which is the part that changes decisions.

## Correction to the brief that produced this

`coint_johansen`'s `det_order` is `{-1, 0, 1}` only — **not** `0..5`. That range does not exist in
statsmodels. Out-of-range values only *warn* (`HypothesisTestWarning`) and return **all-NaN critical
values**, which makes every `stat > crit` False and silently reports "no cointegration, always".
`cointegration_service.py:937` uses `det_order=0` — **correct**. Recorded because the incorrect
mental model was briefed to the researcher.

---

## Traps that DO NOT fire here — verified against current source

| Trap | Severity if present | Verdict here | Evidence |
|---|---|---|---|
| **`arch` `rescale=True` silently rescales by 10/100/1000** → 100× vol | high | **DOES NOT FIRE** | all three `arch_model` calls pass `rescale=False` explicitly — `analytics_engine.py:6640`, `:6644`, `volatility_service.py:285`. Deliberate. |
| **sklearn covariance is `ddof=0`, pandas `.cov()` is `ddof=1`** | low | **DOES NOT FIRE** | all covariance comes from pandas `.cov()` — `analytics_engine.py:4520`, `optimization_service.py:89`, `:679`. No sklearn estimator used. Consistent convention. |
| **`quantstats.value_at_risk(sigma=X)` — `sigma` is a MULTIPLIER, not vol** | high | **DOES NOT FIRE** | `value_at_risk` / `qs.stats.var` never called directly (zero matches in `backend/app`). |
| **yfinance `auto_adjust` now defaults True and removes `Adj Close`** | high | **DOES NOT FIRE** | `data_service.py:1233`, `:1241` pass `auto_adjust=False` explicitly; `:1416` requires `Adj Close`; `:1433` and `indicators_service.py:65` map it. Internally coherent. |
| **adjusted prices + `Dividends` column = dividend double-count** | high | **DOES NOT FIRE** | follows from the above — with `auto_adjust=False` and no `Dividends` consumption path found. |
| **`coint` collinear → `t=-inf, p=0.0`, warning only** | medium | **DID FIRE — now fixed** | `cointegration_service.py` published `is_cointegrated: True` and emitted bare `-Infinity`. Fixed in `52ca968`; guard reads the return value, leaves `CollinearityWarning` propagating. |
| **`coint_johansen` complex eigenvalues** | medium | **DID FIRE — now fixed** | corrected earlier in the session: the real trigger is `eig >= 1`, not complex values (`inv(skk)@sig` is similar to a symmetric matrix, so its spectrum is all-real). |

## Traps still OPEN — not yet checked, ranked by blast radius

These touch code paths that exist and publish numbers. None has been assessed.

1. **`scipy.stats.t.fit` returns `(df, loc, scale)`** — reading element 0 as a variance gives a
   plausible-looking number off by ~10⁴. **`tail_risk_service.py:499` calls `stats.t.fit(r_a)`**
   and unpacks `df_a, _, _`, then averages and clips. *Plausibly correct — but the unpacking was
   not verified against the return contract.*
2. **`scipy.stats.genpareto.fit` sign convention** — `c > 0` means unbounded/heavy tail; `c < 0`
   means a **bounded** tail on `[0, -1/c]`. Reporting `ξ = -0.15` as "mildly fat" when it is a
   finite-endpoint tail **inverts the classification**. `tail_risk_service.py:326-339` fits a GPD.
   **This is the highest-value unchecked trap in the codebase.**
3. **`scipy.cluster.hierarchy.linkage` ids `>= n` are cluster nodes, not assets** — an HRP
   implementation keying weights positionally off `Z[:, :2]` either raises `IndexError` or
   **silently assigns weight to the wrong ticker**. `optimization_service.py:626` `_hrp_weights`.
   *Mitigating:* the repo's own comment at `:96` and `:891` says results are "keyed in scipy-linkage
   leaf order - deliberately NOT assumed to be" — so someone already hit this. **Unverified.**
4. **`cvxpy` `optimal_inaccurate` / `user_limit` are in `SOLUTION_PRESENT`** — the weight vector is
   populated, `prob.value` is set, and **no exception is raised**. Publishing that is publishing
   garbage that looks bounded, sums to 1, and is mostly positive. `optimization_service.py` solves
   several problems. *Mitigating:* the quant auditor measured `optimal` on the cases it tried, so
   this is **latent, not firing**.
5. **`genpareto` moments return `nan` past their existence bounds** — variance needs `c < 1/2`,
   skew `c < 1/3`. A genuinely heavy-tailed fit has **no finite variance**, and
   `genpareto.stats(c, moments='v')` returns `nan` silently.
6. **`quantstats` prices-vs-returns decided by heuristic** (`min>=0 and max>1` ⇒ prices). A
   normalised wealth curve starting at 1.0 that never exceeds 1.0 is read as *returns*, so
   `mean/std` is taken over price **levels** — Sharpe in the hundreds. **Unresolved:** what exactly
   is `port_ret` at `analytics.py:9368`?
7. **`quantstats` `rf` is ANNUALISED** (de-annualised geometrically); **`empyrical` `risk_free` is
   PER-PERIOD**. Same concept, opposite units, both defaulting to 0. Passing 0.06 to empyrical
   subtracts 6% from every *daily* return → Sharpe ≈ −79 instead of ≈0.94. *Mitigating:* the repo
   computes its own ratios in `analytics_engine`; empyrical/pyfolio are not imported.
8. **`linkage(corr_matrix)` reads an n×n array as n observation vectors** — no error, no warning,
   and the result is *plausible* because `‖corr_i − corr_j‖² = 2(1−ρ_ij)`. Same bug family as #3.
9. **`max_drawdown` takes prices, prepends a phantom baseline, returns a negative** — a hand-rolled
   MDD disagrees by tens of bps whenever the first return is negative.
10. **`coint`'s p-value and critical values come from different MacKinnon surfaces** — `crit` depends
    on `nobs`, `pvalue` does not, so they can straddle 0.05. **Disclosure gap, upstream-acknowledged.**

## Highest-value next check

**#2, the `genpareto` sign convention.** It is the one trap that can invert a published risk
*classification* rather than merely perturb a magnitude, and `tail_risk_service.py` fits a GPD and
publishes `gpd_shape_xi` as a headline field. A one-assertion test settles it:
`assert c > 0` on a synthetic heavy-tail sample, plus a bounded-tail case asserting the code
refuses rather than reporting a fat tail.

Then #1 and #3 — both are unpack/indexing mistakes where the wrong answer is plausible.

---

## Method note

Every "DOES NOT FIRE" above was checked by opening the cited line. The one trap whose absence is
*asserted* rather than shown — `empyrical`/`pyfolio` not being imported — rests on a single search;
per this project's own tooling rules that search should be treated as a hypothesis until a control
search proves the pattern is matchable at all.

**Prove every absence with a control search.** `rg` with a quoted `"` silently returns nothing on
this machine and **`-F` does not fix it**; use `Select-String`.