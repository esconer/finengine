# Detail — Quantitative & financial correctness (`backend/app/services/` + wire contracts)

**Scope of this file.** The numerical core only:
`analytics_engine.py` (6,772 lines), `cointegration_service.py`, `optimization_service.py`,
`tail_risk_service.py`, `backtest_service.py`, `volatility_service.py`, `regime_service.py`,
`monte_carlo_service.py`, `correlation_service.py`, `indicators_service.py`,
`screener_service.py`, `equity_research_service.py`, plus `app/utils/holdings.py`,
`app/services/benchmark_service.py` and the schema field contracts in `app/models/schemas.py`.

**This is a different axis from `detail/services.md`.** That file audited *fabrication*: a
number produced where no measurement happened. This one asks, for every named statistic,
**is the implemented formula the standard definition of that statistic** — and then whether a
correct formula is made to produce the wrong number (aggregation order, `ddof`, double
annualisation, lookahead, degenerate inputs, units, library parameterisation). Where
`SVC-*` findings overlap, they are cross-referenced and **not re-derived**; the overlap is
stated so the assembler can merge rather than double-count.

**Evidence standard applied.** Every `path:line` below was opened at the cited line before
emission. Where a claim turns on a library's parameterisation or on a definition, the
library's own source or docstring **in `backend/.venv`** is quoted. Six arithmetic probes
were run under `backend/.venv` (pure numpy/scipy/statsmodels/cvxpy; no network, no DB, no
project service import); the commands are reproduced verbatim in *Numeric probes*.

**Coverage of `analytics_engine.py` — read in full: lines 1–2,922 and 3,460–6,772.
Lines 2,923–3,459 were covered by targeted scan for arithmetic on published statistics**
(every line matching `np.`, `/ 0`, `* 0`, `.sum(`, `.mean(`, `sqrt`, `log(`, `percentile`,
`/ len`, `* 252`, `* 100`, `/ 100`); the only hits were `np.zeros((0, 0))` at 3,182 and a
finite-count `.sum()` at 3,235–3,237, neither of which produces a published statistic. That
range is the `_risk_score_audit` disclosure builder and the `_risk_score_precision` block;
it emits strings and counts, not statistics. **I state the gap rather than hide it.**

---

## Findings

---

### QM-1 — `cov_bl` is not the Black-Litterman posterior covariance; it *inflates* the prior while the posterior shrinks it
- **Class**: quantitative-correctness defect
- **Severity**: WRONG-NUMBER
- **Confidence**: VERIFIED (code read; algebra verified numerically; reference quoted)
- **Location**: `backend/app/services/optimization_service.py:829` (formula), `:786-832` (the
  whole posterior block), `:838-845` (where `cov_bl` is consumed)
- **Standard definition**. The Bayesian posterior covariance of the BL mean is

  Σ_post = [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹ , which is algebraically identical to
  τΣ − τΣPᵀ(Ω + τPΣPᵀ)⁻¹PτΣ  (Idzorek 2004, *A Step-By-Step Guide to the Black-Litterman
  Model*, Theorem 1). With the **He–Litterman proportional** view uncertainty
  Ω = diag(PτΣPᵀ) — which is exactly what this file uses — the posterior is a
  **contraction** of the prior.
- **Implemented formula**:
  ```python
  821:            tau_sigma = tau * cov_ann
  822:            omega_diag = np.diag(P @ tau_sigma @ P.T)
  823:            omega_diag = np.clip(omega_diag, 1e-6, None)
  824:            Omega = np.diag(omega_diag)
  825:
  826:            inner = P @ tau_sigma @ P.T + Omega
  827:            inv_inner = np.linalg.pinv(inner)
  828:            mu_bl = pi + (tau_sigma @ P.T @ inv_inner @ (Q - P @ pi))
  829:            cov_bl = (1.0 + tau) * cov_ann - (tau * tau) * (cov_ann @ P.T @ inv_inner @ P @ cov_ann)
  ```
- **Evidence** (probe P2e/P4, `backend/.venv`, k=4 assets, n=60, τ=0.05, two rows of `P`):

  ```
  ||L  - G||   = 1.04e-17        # L = [(τΣ)⁻¹+PᵀΩ⁻¹P]⁻¹ , G = τΣ − τΣPᵀ(Ω+τPΣPᵀ)⁻¹PτΣ  -> the two reference forms agree
  ||code - L|| = 9.60e-01        # max abs element
  trace(S)=3.466289   trace(code)=3.574071   trace(L)=0.107781
  ```
  i.e. the published `cov_bl` **grows** the prior's trace by **+3.11 %** where the BL
  posterior **shrinks** it by **−96.9 %**. Solving the same tangency programme the code
  solves:
  ```
  code      (cov_bl as coded)            : [0.2107 0.3614 0.2038 0.2241]
  BL correct(posterior cov)             : [0.2698 0.2276 0.2541 0.2485]
  max weight difference                  : 0.1338   (top leg 0.3614 vs 0.2698)
  isolate: correct cov + double-rf       : [0.2674 0.2328 0.2548 0.2451]
  isolate: coded cov,   no double-rf     : [0.2138 0.3547 0.2040 0.2275]
  cov alone moves max weight by         : 0.1271
  ```
- **Mechanism**. The code's expression is not any of the standard BL posterior forms. It has
  (a) a **minus** sign where the `τ²ΣPᵀ(PτΣPᵀ+Ω)⁻¹PΣ` variant has a **plus**, and (b) the
  leading term `(1+τ)Σ` where the τ-parameterisation requires `τΣ − τ²ΣPᵀ(...)⁻¹PΣΣ` and the
  Σ-parameterisation requires `Σ + τΣPᵀ(...)⁻¹PΣ`. Because `P` has rank 2 of 4, the matrix
  `X = ΣPᵀM⁻¹PΣ` is not a scalar multiple of Σ, so the discrepancy is a *rotation* of the
  covariance, not a scale — the tangency portfolio is scale-invariant to `cΣ` but not to a
  differently-shaped matrix.
- **Impact**: every `black_litterman` recommendation's weights. The route supplies
  `views` / `relative_views` from the request body
  (`backend/app/api/analytics.py:10201-10202` → `:10329-10331`), so the branch is reachable.
  `expected_annual_volatility` beside the weights is scored on the *prior* `cov_ann`, not on
  `cov_bl`, so the payload does not show the matrix the weights were solved from at all.
- **Suggested fix**: `cov_bl = tau_sigma - tau_sigma @ P.T @ np.linalg.inv(Omega + P @ tau_sigma @ P.T) @ P @ tau_sigma`,
  publish it on `model_params` (so a reader can recompute `expected_annual_*`), and keep the
  no-views branch as `cov_ann`. Also publish `tau`, `delta`, `omega_diag`, `P` and `Q`.

---

### QM-2 — `adjusted_r_squared` is clipped at zero, so a negative adjusted R² is published as a measured `0.0`
- **Severity**: WRONG-NUMBER
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/analytics_engine.py:6212`
- **Standard definition**. `rsquared_adj` in statsmodels is
  `1 − (1 − R²)(n − 1)/(n − k − 1)`. With one regressor, `k = 1`, so it is
  `1 − (1 − R²)(n − 1)/(n − 2)`. It is **negative whenever R² < 1/(n − 1)** — a perfectly
  normal outcome for a single-regressor model, and the value that tells a reader the fit is
  worse than a one-mean model.
- **Implemented formula**:
  ```python
  6212:                            adj_r_squared = round(float(max(0.0, port_model.rsquared_adj)), 4)
  ```
- **Evidence** (probe P3, closed form, `n` = paired regression rows, `R²` = published `r_squared`):
  ```
  n=10  R2=0.05   true adjR2=-0.0687   published max(0,adj)=0.0000
  n=10  R2=0.11   true adjR2=-0.0012   published max(0,adj)=0.0000
  n=40  R2=0.05   true adjR2=+0.0250   published max(0,adj)=0.0250
  n=40  R2=0.30   true adjR2=+0.2816   published max(0,adj)=0.2816
  ```
  The engine's own floor is `_FACTOR_FIT_MIN_ROWS = 10` (`analytics_engine.py:2476`, enforced
  at `:6199`), so `n = 10` with `R² = 0.05` is inside the accepted region, not an edge case.
- **Mechanism**. `max(0.0, …)` is Python's two-argument `max`, which returns the non-NaN
  argument; on a negative input it returns `0.0`. Nothing on the payload says the value was
  floored, and no key distinguishes "adjusted R² measured at 0.0" from "adjusted R² was
  negative and was clipped".
- **Impact**: `adjusted_r_squared` on `factor_exposure_analysis`, i.e. the single number a
  reader consults to decide whether the benchmark regression is worth anything. A pair with
  `R² = 0.05` over 10 rows reads exactly like a pair with `R² = (n-2)/(n-1) = 0.889`… i.e.
  a pair with `R² = 1/(n-1)` reading like a perfect fit at the threshold.
- **Suggested fix**: publish `float(port_model.rsquared_adj)` unchanged, or publish both
  `adjusted_r_squared` and `adjusted_r_squared_floor_applied: bool`.

---

### QM-3 — `sharpe_ratio` and `sortino_ratio` publish a hard `0.0` on a zero or NaN denominator
- **Severity**: WRONG-NUMBER
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/analytics_engine.py:5468` and `:5476`
- **Cross-reference**: **duplicates `SVC-2` in `detail/services.md`**. It is re-listed here
  because it is a *formula* defect as well as a fabrication defect — the `else 0.0` is a value
  the ratio does not mean. The assembler should keep one finding, not two.
- **Standard definition**. Sharpe = excess return ÷ standard deviation of the **same**
  excess return; Sortino = excess return ÷ **downside** deviation. Both are undefined when the
  denominator is 0 or non-finite.
- **Implemented formula**:
  ```python
  5464:                annual_return = float(returns.mean() * 252)
  5465:                annual_volatility = float(returns.std() * np.sqrt(252))
  5468:                sharpe_ratio = float((annual_return - self.risk_free_rate) / annual_volatility) if annual_volatility > 0 else 0.0
  5475:                downside_deviation = float(np.sqrt(np.mean(downside ** 2)) * np.sqrt(252)) if len(returns) else 0.0
  5476:                sortino_ratio = float((annual_return - self.risk_free_rate) / downside_deviation) if downside_deviation > 0 else 0.0
  ```
- **Mechanism** (restated from `SVC-2`, confirmed): `float(nan) > 0` is `False` in CPython, so
  both guards fall through to `0.0`. Probe P3 re-confirms the family: `min(30, float('nan')*100) == 30`
  and `np.minimum(30, np.nan) == nan` — i.e. the naive "just clamp it" fix in this module's
  idiom would fabricate a **maximum** risk score instead. That is why the fix must be a
  refusal, not a clamp.
- **Impact**: `sharpe_ratio`, `sortino_ratio` on the portfolio block and on every position in
  `positions{}`, and — via `_estimate_uncertainty_block` — the *centre* of the published
  percentile interval for both.
- **Suggested fix**: publish `None` plus a reason on both guards, matching the sibling
  `< 10` branch at `:5460-5461` which already does this.

---

### QM-4 — a perfectly collinear pair publishes `is_cointegrated: true`, `p = 0.0`, and `t = -Infinity` (which is not valid JSON)
- **Severity**: WRONG-NUMBER
- **Confidence**: VERIFIED (control search + library docstring + probe)
- **Location**: `backend/app/services/cointegration_service.py:1401-1410`; the t-stat field
  contract at `backend/app/models/schemas.py:489`
- **Standard definition / control search.** `statsmodels.tsa.stattools.coint`, installed
  source `backend/.venv/Lib/site-packages/statsmodels/tsa/stattools/_stattools.py`, docstring:

  > *"If the two series are almost perfectly collinear, then computing the test is numerically
  > unstable. However, the two series will be cointegrated under the maintained assumption
  > that they are integrated. In this case **the t-statistic will be set to `-inf` and the
  > pvalue to zero**."*

  A `CollinearityWarning` is raised. **Control search** confirms the service catches only
  `Exception` (`:1406-1408`); `CollinearityWarning` is a `Warning`, so it is not caught,
  not logged, and not published.
- **Implemented formula**:
  ```python
  1403:        t_stat, p_val, _ = coint(p_a, p_b)
  1404:        engle_granger_tstat = float(t_stat)
  1405:        engle_granger_pvalue = float(p_val)
  ...
  1410:        is_coint = bool(engle_granger_pvalue < p_value_threshold)
  ```
- **Evidence** (probe P3, CPython 3.12, statsmodels 0.15.0):
  ```
  collinear  coint(2x, x)   -> t=-inf p=0.0  is_coint(p<0.05)=True
  identical   coint(x, x)   -> t=-inf p=0.0  is_coint=True
  affine      coint(x+5, x) -> t=-inf p=0.0  is_coint=True
  json.dumps(-inf) -> {"engle_granger_tstat": -Infinity}
  ```
- **Mechanism**, three compounding consequences:
  1. The library's own words are that the result is *not reliable*. The service adopts it as
     the **published decision** (`DECISION_TEST = "engle_granger"`, `:71`) and it is the first
     rung of the directive gate (`:1485`).
  2. `engle_granger_pvalue: 0.0` is indistinguishable from a genuinely decisive p-value.
  3. `engle_granger_tstat: float` (`schemas.py:489`) accepts `-inf`, and FastAPI's default
     serialiser emits the bare token `-Infinity`, which is **not valid JSON** (RFC 8259 §6).
     `JSON.parse` in the browser throws on it, so a book containing one duplicated ticker
     breaks the whole response, not just that pair.
- **Impact**: `is_cointegrated`, `engle_granger_pvalue`, `engle_granger_tstat`,
  `signal`, `johansen_agrees_with_decision` on any pair whose two legs are collinear — which
  is exactly the realistic case of the same fund imported under two symbols, or two symbols
  that track the same index.
- **Suggested fix**: catch `statsmodels.tools.sm_exceptions.CollinearityWarning` (or test
  `math.isfinite(t_stat)`) and return `None` from `analyze_pair_cointegration`, mirroring
  what `test_johansen_cointegration` already does for a non-finite statistic
  (`:1066-1068`). Add `t_stat` finiteness to the same guard.

---

### QM-5 — the Black-Litterman tangency subtracts the risk-free rate a second time
- **Severity**: WRONG-NUMBER
- **Confidence**: VERIFIED (the contradiction is internal to one function's own docstring)
- **Location**: `backend/app/services/optimization_service.py:776` (docstring), `:793`
  (prior), `:834` (the subtraction)
- **Standard definition**. `Π = δΣw_mkt` is the vector of **equilibrium excess returns** — the
  market risk premium. The function's own docstring says so in the function's own words:
  `optimization_service.py:776`: *"- Implied equilibrium excess returns: Pi = delta * Sigma * w_mkt"*.
  Views are therefore expressed in excess space and the posterior mean is already an excess
  return; nothing further is subtracted.
- **Implemented formula**:
  ```python
  776:    - Implied equilibrium excess returns: Pi = delta * Sigma * w_mkt
  ...
  793:        pi = delta * (cov_ann @ w_mkt)
  828:            mu_bl = pi + (tau_sigma @ P.T @ inv_inner @ (Q - P @ pi))
  834:        excess = mu_bl - risk_free_rate
  ```
- **Evidence** (probe P4, same instance as QM-1):
  ```
  prior pi = delta*Sigma*w_mkt (equilibrium EXCESS) = [-0.30121 1.60013 -0.25325 0.35997 0.83055]
  posterior mu_bl (excess space)                    = [-0.08481 1.23173 -0.08129 0.23297 0.60372]
  code  excess = mu_bl - rf  (line 834)             = [-0.10481 1.21173 -0.10129 0.21297 0.58372]
  uniform shift the line-834 subtraction applies (pp) = -2.0
  ```
- **Mechanism**. `mu_bl` is a convex blend of `pi` (excess) and `Q` (documented at
  `:780-782` as already de-risk-freed by the caller: *"Express absolute-return views as view
  minus risk-free rate"*), so it is in excess space. `:834` treats it as a total return. The
  error is a **uniform −`risk_free_rate` shift on every leg** — it does not change the ranking
  of legs, which is why it is easy to miss, but it does change the tangency solution.
- **Impact**: measured, modest — `double-rf alone moves max weight by 0.0052` in probe P4 —
  plus a systematic −2 pp bias in the expected excess returns the solver sees. The dominant
  BL defect is QM-1 (0.127 in the same probe); this one is a quarter of it.
- **Suggested fix**: `excess = mu_bl`. If the intent really was total space, the prior must be
  `pi + rf` instead — but that contradicts `:776`, so the docstring wins.

---

### QM-6 — the EWMA forecast's `return_space_volatility` (and therefore its VaR/ES) is built from the **clipped** sigma while GARCH/EGARCH use the raw one
- **Severity**: WRONG-CONVENTION
- **Confidence**: VERIFIED
- **Location**: `analytics_engine.py:6558-6566` (EWMA) vs `:6642-6652` (GARCH/EGARCH);
  consumer at `:6013-6027`
- **Implemented formula**:
  ```python
  6557:        raw = float(np.sqrt(max(0.0, var) * 252))
  6558:        annualized = np.array([float(np.clip(raw, FORECAST_VOL_CLIP_LOW,
  6559:                                            FORECAST_VOL_CLIP_HIGH))] * h)
  ...
  6563:            "volatility_forecast": float(annualized[-1]),
  6564:            "raw_volatility_forecast": raw,
  6565:            "return_space_volatility": float(annualized[-1] * np.sqrt(h / 252.0)),
  ```
  versus
  ```python
  6642:    annualized_path, return_space_path = (
  6643:        AnalyticsEngine._cumulative_forecast_volatility(variance_path)
  6644:    )
  6645:    raw = float(annualized_path[-1])
  6650:        "volatility_forecast": float(clipped[-1]),
  6651:        "raw_volatility_forecast": raw,
  6652:        "return_space_volatility": float(return_space_path[-1]),   # <- UNCLIPPED
  ```
- **Mechanism**. `FORECAST_VOL_CLIP_LOW = 0.05` / `FORECAST_VOL_CLIP_HIGH = 1.20`
  (`:849-850`). For GARCH and EGARCH the h-day sigma comes from the raw variance path; for
  EWMA it is the *clipped* annualized sigma times `sqrt(h/252)`. A book whose true EWMA
  volatility is 3 % has its VaR computed at 5 % — **67 % overstated** — while `raw_volatility_forecast`
  published beside it reads 0.03. `_ewma_forecast` (`:6013`, `:6016`, `:6022`) uses the clipped
  value for `return_space_vol`, `var_forecast` and `cvar_forecast`.
- **Mitigation that exists elsewhere**: `volatility_sizing` deliberately prefers the *raw*
  value for exactly this reason — `analytics_engine.py:4628-4631`: *"Use the un-floored model
  estimate for inverse-volatility parity. The public forecast remains clipped for stable UI
  bounds, but a 1 % asset must not become a 5 % peer."* The tail block does not follow its own
  repo's rule.
- **Suggested fix**: `"return_space_volatility": float(raw * np.sqrt(h / 252.0))` in the EWMA
  branch, and use `raw` in `_ewma_forecast`'s VaR/ES; keep the clip for display only.

---

### QM-7 — a regime state's `ann_vol` is the mean of overlapping *annualized* 21-day volatilities
- **Severity**: WRONG-CONVENTION
- **Confidence**: DERIVED (arithmetic; the reference is the standard aggregation identity)
- **Location**: `backend/app/services/regime_service.py:295` (feature), `:343` (the statistic)
- **Standard definition / mechanism**. A regime state's volatility is the volatility of the
  daily returns assigned to that state: `sqrt(Var(r_state)) · sqrt(252)`. The code instead
  averages 2,000-odd *overlapping* 21-day rolling annualized volatilities:
  ```python
  295:        vol21 = (ret_1d.rolling(REGIME_FEATURE_WINDOW_DAYS).std() * np.sqrt(TRADING_DAYS_PER_YEAR)).dropna()
  ...
  343:            ann_v = float(vol21.loc[common].values[mask].mean()) if n_sub > 0 else 0.0
  ```
  Because `E[√v] ≤ √(E[v])` (Jensen, `√` concave) and the windows overlap by 20/21, the
  published figure is biased **low** relative to the volatility of the concatenated state
  returns, and it is biased low by an amount that depends on the within-state volatility
  clustering — i.e. it is *largest exactly in the calm states*, compressing the difference
  the three labels are supposed to separate.
- **Impact**: `states[].ann_vol` and the regime comparison a reader draws from it. The
  `ann_ret` beside it is the correct geometric CAGR (`(∏(1+r))^(252/n) − 1`, `:339-340`), so
  the two are on different aggregation conventions under one key pair, with nothing saying so.
  `units` (`:601-602`) declares only `annualized_fraction`.
- **Suggested fix**: `ann_v = float(r_sub.std(ddof=1) * np.sqrt(252))`, or publish
  `ann_vol_root_mean_square = sqrt(mean(vol21**2))` alongside if the rolling average is
  wanted. Either way, name the aggregation in `units`.

---

### QM-8 — the Johansen diagnostic's `det_order` and `k_ar_diff` are hardcoded, and the verdict gates a trade directive
- **Severity**: WRONG-CONVENTION
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/cointegration_service.py:1062-1063`; the gate that
  consumes it at `:1485-1538` (rule 2 of the directive, `:114-115`)
- **Implemented formula**:
  ```python
  1062:            # det_order=0 (constant term), k_ar_diff=1 (lag order)
  1063:            res = coint_johansen(data, det_order=0, k_ar_diff=1)
  ```
- **Mechanism**. `statsmodels.tsa.vector_ar.vecm.coint_johansen(data, det_order, k_ar_diff)`
  exposes both as arguments; the choice of `k_ar_diff` changes the trace statistic, and the
  service fixes it at 1 for every pair, on every sample size, with no AIC/BIC selection and
  no published basis. The contrast with the module's own stationarity block is stark — there,
  `STATIONARITY_ADF_MAX_LAGS` and the KPSS bandwidth are named constants with a written
  rationale and are published on every result (`:227-232`).
- **Impact**: bounded, because the service labels Johansen `JOHANSEN_ROLE = "diagnostic_only"`
  (`:73`) — but `johansen_agrees_with_decision` is **rule 2 of the five** that must all hold
  before a `LONG_SPREAD` / `SHORT_SPREAD` directive is published (`:110-119`). A hardcoded
  `k_ar_diff` therefore decides trades. Neither `det_order` nor `k_ar_diff` appears on
  `CointPairResult` (`schemas.py:486-535` region), so a reader cannot check it.
- **Suggested fix**: select `k_ar_diff` per pair over 0–3 by the Johansen trace statistic's
  own criterion (or by AIC on the VECM), publish the resolved value beside the verdict, and
  add `k_ar_diff_basis` to `CointPairResult`.

---

### QM-9 — the stationarity gate is tested on log prices; the decision test it gates runs on levels
- **Severity**: WRONG-CONVENTION
- **Confidence**: DERIVED
- **Location**: `cointegration_service.py:181-182` + `:1208` (gate, log prices) vs
  `:1403` + `:1426` + `:1459` (decision + hedge ratio + spread, levels)
- **Evidence**.
  ```python
  181:    # Prices are non-stationary by construction, so the object of the test is
  182:    # log(price), never the price.
  ...
  1208:        log_prices = np.log(values)                       # stationarity gate: LOG
  ...
  1403:        t_stat, p_val, _ = coint(p_a, p_b)               # decision:      LEVELS
  1426:        beta, alpha = np.polyfit(p_b, p_a, 1)            # hedge ratio:    LEVELS
  1459:        spread = p_a - (alpha + beta * p_b)              # spread:         LEVELS
  ```
- **Mechanism**. `statsmodels.tsa.stattools.coint` regresses `y0` on `y1` **in levels** and
  tests the residuals for a unit root. The precondition for *that* test is that both series are
  I(1) **in levels**. The gate that is supposed to establish the precondition establishes
  I(1) in **logs**. A cointegrating relation in logs is not the same as one in levels, so the
  gate can pass on a leg whose level is a trend-stationary series, which is precisely the
  spurious case the whole gate was written to stop (`:170-179`).
- **What is *right* here**: the spread construction **does** match the hedge ratio used
  downstream — both are the level-OLS `α + β·P_B` (`:1426` and `:1459`), and
  `SIGNAL_NOTIONAL_CONVENTION` (`:131-136`) states the notional convention that follows from
  it correctly. That half is VERIFIED-CORRECT.
- **Suggested fix**: state the transform the decision test is on (`"eg_level_prices"`) beside
  `p_value`, and either run `coint` on log prices (and rebuild the spread in logs) or run the
  ADF/KPSS pair on levels. Either is defensible; mixing them silently is not.

---

### QM-10 — the benchmark is the NIFTY 50 **price** index; no total-return index is used and nothing declares it
- **Severity**: WRONG-CONVENTION
- **Confidence**: VERIFIED (symbol and column selection read); DERIVED (magnitude)
- **Location**: `backend/app/services/benchmark_service.py:20`, `:24`, `:133-143`;
  consumers: `analytics_engine.py:6122` (factor regression), `:5150` (risk-score factor leg),
  `regime_service.py:447-460`
- **Implemented formula**:
  ```python
  20:    BENCHMARK_SYMBOL = "^NSEI"  # NIFTY 50
  24:    _CLOSE_CANDIDATES = ("adj_close", "close", "Adj Close", "Close")
  ...
  142:        returns = series.pct_change(fill_method=None).dropna()
  ```
- **Mechanism**. `^NSEI` is the NIFTY 50 **price** index. Whichever of the four close columns
  the feed returns, the series is a price-return series: dividends are not reinvested. NSE
  publishes a separate total-return index for exactly this reason. Every benchmark-relative
  number in the product — `beta_vs_benchmark`, `alpha`, `annualized_alpha`, `r_squared`,
  `benchmark_sharpe`, `benchmark_cagr`, and the whole regime classification — is therefore
  measured against a price index while the portfolio legs are total-return series.
- **Amplifiers**: (a) `analytics.py:555` hardcodes a second `TEAR_SHEET_RISK_FREE_RATE = 0.02`
  alongside `settings.risk_free_rate` (`config.py:53`) — see QM-18; (b) 252 trading days is
  used consistently across the module, which is correct for NSE and worth saying so.
- **Impact**: `r_squared` (the risk score's factor leg at `:5162`) is biased low by the missing
  dividend return, which pushes the factor sub-score toward its 30-point cap; `beta` is
  biased high by the same amount; `benchmark_cagr` and `benchmark_sharpe` understate by
  roughly the index dividend yield. `regime_service._regime_metadata` publishes
  `"name": "NIFTY 50"` and nothing about the return basis.
- **Suggested fix**: use a TRI symbol (`^NSEI` has no TRI on Yahoo; the usual Indian proxies
  are `^CNXPHARMA`-style variants or an explicit NIFTY 50 TRI feed) or carry the dividend
  yield forward into the benchmark return series, and publish
  `benchmark.return_basis: "price_index" | "total_return_index"` beside
  `regime_metadata.benchmark` and on every factor-exposure payload.

---

### QM-11 — `kurtosis` crosses the wire as **excess** kurtosis under a plain field name, with no unit declaration anywhere
- **Severity**: WRONG-CONVENTION
- **Confidence**: VERIFIED
- **Location**: `analytics_engine.py:5534-5543`; the schema field at `schemas.py:266`
- **Implemented formula**:
  ```python
  5540:            return {
  5541:                "skewness": returns.skew(),
  5542:                "kurtosis": returns.kurtosis()
  5543:            }
  ```
- **Mechanism**. pandas `Series.kurtosis()` defaults to `fisher=True` — it returns the
  **Fisher (excess) kurtosis**, i.e. `m4/m2² − 3`. A normal distribution therefore reads
  `0.0`, not `3.0`. The field is named `kurtosis`; the sibling field `skewness` is unbiased
  either way, so only one of the pair is affected and nothing on the payload says which.
- **Control search (proves the schema is not the missing declaration)**:
  ```
  Select-String -Path "backend\app\**\*.py" -Pattern "RealizedRiskMetrics|ForecastRiskMetrics|
      ConcentrationMetrics|FactorExposure\b|LiquidityMetrics|RiskScore\b"
    models\schemas.py:259: class RealizedRiskMetrics(BaseModel):
    models\schemas.py:276: class ForecastRiskMetrics(BaseModel):
    models\schemas.py:287: class FactorExposure(BaseModel):
    models\schemas.py:295: class ConcentrationMetrics(BaseModel):
    models\schemas.py:307: class LiquidityMetrics(BaseModel):
    models\schemas.py:316: class RiskScore(BaseModel):
  ```
  Six hits, **all six in the declaring file** — no route, no service and no consumer
  references any of them. `RealizedRiskMetrics` (`schemas.py:259-273`) is the only place a
  unit could have been declared for `kurtosis`, `var_95`, `cvar_95` or `hit_ratio`, and it is
  never applied to a response.
- **Impact**: `kurtosis` on the realized-risk block and on every position. A reader who
  compares it to the normal-theory value of 3 (or to the "excess kurtosis > 0.5" threshold the
  tail-risk service uses at `tail_risk_service.py:51`) reads two different statistics as one.
  Note the tail service's `excess_kurtosis` **is** correctly Fisher-excess (scipy
  `stats.kurtosis` default `fisher=True`, `:348`) — so the product contains both, under
  similar names, on different pages.
- **Suggested fix**: rename to `excess_kurtosis` and add `kurtosis_units: "fisher_excess"` to
  the block; or publish `kurtosis_raw = excess + 3`. Then either wire
  `RealizedRiskMetrics` into the route's `response_model=` or delete the six dead models.

---

### QM-12 — `var_95` / `cvar_95` are published as **negative returns** under loss-shaped names, with no sign or unit declaration
- **Severity**: WRONG-CONVENTION
- **Confidence**: VERIFIED (value); DERIVED (reader impact)
- **Location**: `analytics_engine.py:5491-5508`
- **Implemented formula**:
  ```python
  5497:            # Historical VaR (95%)
  5498:            var_95 = np.percentile(returns, 5)
  5499:
  5500:            # Conditional VaR (Expected Shortfall)
  5501:            cvar_95 = returns[returns <= var_95].mean() if len(returns[returns <= var_95]) > 0 else var_95
  ```
- **What is right**: both formulas are the standard **historical** VaR and **historical**
  expected shortfall at the 95 % level, and the code says so in the comments. The estimator
  (`_tail_measure_disclosure`, `:5811-5820`) correctly declares its *parametric* VaR/ES
  (`var_method: fitted_conditional_sigma_x_normal_quantile`,
  `var_distribution: normal`) — so the codebase already knows how to declare an estimator and
  this block simply does not do it.
- **Mechanism**. `np.percentile(returns, 5)` of a daily return series is negative. Published
  as `var_95: -0.0312`, that reads as a *gain* of 3.12 % unless the reader knows the sign
  convention; a loss-magnitude reading would be `0.0312`. The tail-risk service gets this
  right by publishing `var_sign_convention: "negative_is_loss"`
  (`tail_risk_service.py` → consumed at `:5815`), and the forecast block publishes the same
  (`:5815`). The realized-risk block publishes neither.
- **Impact**: `var_95`, `cvar_95` on the portfolio block and every position. Aggravated by the
  dead `RealizedRiskMetrics` contract (QM-11's control search).
- **Note on the tail/mask convention** (`r <= percentile(r,5)`): under `numpy`'s default
  *linear* interpolation the 5th percentile of a finite sample usually falls between two order
  statistics, so the mask selects `≥ 5 %` of observations and `cvar_95` is an average over
  more than the nominal tail. This is a legitimate convention, but it is undeclared. The
  bootstrap restatement (`analytics_engine.py:2262-2272`) reproduces it exactly, which is
  correct behaviour for an interval and is not a defect.
- **Suggested fix**: publish `var_95_units: "fraction_daily_return_negative_is_loss"` and
  `var_95_estimator: "historical_percentile_5"` beside the two numbers. No value changes.

---

### QM-13 — `var_forecast` / `cvar_forecast` are **parametric normal** and are labelled as such, but sit under a generic forecast name next to a historical VaR/ES product
- **Severity**: WRONG-CONVENTION
- **Confidence**: VERIFIED
- **Location**: `analytics_engine.py:833-835`, `:5778-5837`, `:5864-5869`
- **Implemented formula**:
  ```python
  834:    TAIL_Z_MULTIPLIER = 1.645
  835:    TAIL_ES_MULTIPLIER = 2.06
  ...
  5864:            var_forecast = float(
  5865:                np.clip(-return_space_vol * TAIL_Z_MULTIPLIER, TAIL_CLIP_LOW, TAIL_CLIP_HIGH)
  5866:            )
  5867:            cvar_forecast = float(
  5868:                np.clip(-return_space_vol * TAIL_ES_MULTIPLIER, TAIL_CLIP_LOW, TAIL_CLIP_HIGH)
  5869:            )
  ```
- **Verification of the constants** (they are the standard normal's quantiles, and the code
  says so at `:826-831`). Measured: `scipy.stats.norm.ppf(0.95) = 1.6448536…`;
  `norm.pdf(1.6448536)/0.05 = 2.0627128…`. So `1.645` and `2.06` are correct to the declared
  precision, and the ES multiplier is the correct normal ES, **not** the common
  `1.25 × z` shortcut. This part is right.
- **Mechanism / impact**: the disclosed block is excellent
  (`var_confidence_level`, `var_units`, `var_sign_convention`, `var_distribution`,
  `var_method`, `var_z_multiplier`, `cvar_es_multiplier`,
  `cvar_to_var_ratio_fixed_by_construction: True`). The residue is naming: the field is
  `var_forecast`, the same word the historical `historical_var` uses in
  `tail_risk_service.py:360`, and the two estimators are never named in the *key*. A
  comparison of "the 99 % VaR" (`tail_risk_service`) against "the 95 % VaR"
  (`analytics_engine`) is a level mismatch *and* an estimator mismatch, on two pages, with
  no field that says which is which at the top level.
- **Suggested fix**: rename to `var_forecast_normal` / `cvar_forecast_normal`, or add
  `"var_forecast_estimator": "parametric_normal_on_fitted_conditional_sigma"` at the top
  level of the forecast payload so a consumer reading only the top-level keys still sees it.

---

### QM-14 — the volatility cone publishes `horizon_days: 21` on a forecast that has no horizon
- **Severity**: WRONG-CONVENTION
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/volatility_service.py:439-441`, `:484-491`
- **Implemented formula**:
  ```python
  439:        if forecast_model.upper() == "EWMA":
  440:            ann_vol_forecast = cls.calculate_ewma_volatility(clean_returns)
  441:            model_label = "EWMA"
  ...
  484:        forecast_overlay = {
  485:            "model": model_label,
  486:            "annualized_vol": round(ann_vol_forecast, 4),
  487:            "horizon_days": int(forecast_horizon),
  ```
- **Mechanism**. `calculate_ewma_volatility` (`:190-241`) is a **spot** RiskMetrics estimate:
  a weighted sum of squared daily returns times `sqrt(252)`. It takes no horizon and does not
  use `forecast_horizon`. The overlay nonetheless publishes `horizon_days: 21` beside it. The
  GARCH branch (`:443`) *does* use the horizon (mean of the 21-step variance path, `:292`),
  so the same field name carries two different quantities depending on `model`.
- **Impact**: `current_forecast.horizon_days` and therefore any reader comparing the EWMA
  overlay with the GARCH overlay on the same page. Compounded by the same field name on
  `analytics_engine._ewma_forecast`, which is at least self-consistent there (flat
  `term_structure`, `:6007`).
- **Suggested fix**: `"horizon_days": int(forecast_horizon) if model_label != "EWMA" else None`
  plus `"horizon_note": "RiskMetrics EWMA is a spot estimate with no mean reversion; it has no horizon"`.

---

### QM-15 — the rolling average pairwise correlation averages over a shrinking pair denominator
- **Severity**: WRONG-NUMBER
- **Confidence**: VERIFIED
- **Cross-reference**: **duplicates `SVC-8` in `detail/services.md`** — same code, same
  mechanism. Re-listed here because it is also a *formula* defect: the published statistic is
  not the `rho_bar_t` the module's own docstring declares.
- **Location**: `backend/app/services/correlation_service.py:22-24` (declared formula), `:61-62`
  (implemented)
- **Declared**:
  ```python
  24:        rho_bar_t = (2 / (N * (N - 1))) * sum_{i < j} rho_{i, j, t}
  ```
- **Implemented**:
  ```python
  61:    pairs_df = pd.concat(pair_corrs, axis=1)
  62:    avg_corr_series = pairs_df.mean(axis=1).dropna()
  ```
- **Mechanism**. `DataFrame.mean(axis=1)` defaults to `skipna=True`, so on a date where only
  `m` of the `N(N−1)/2` pairs are finite the published value is `Σ_{m finite} ρ / m`, not
  `Σ_{all} ρ / (N(N−1)/2)`. `min_periods = min(window_days, 30)` (`:50`) makes each pair's
  rolling correlation NaN until its own window fills, so the denominator climbs from 0 to
  `N(N−1)/2` over the first `window_days` rows — for the default 60-day window, the first 30
  dates are exactly the region where the denominator is still climbing.
- **Impact**: `series[].avg_correlation`, `current_avg_correlation`, and through them the
  75th/90th/10th percentile comparisons that set `alert_level` and `is_regime_break`
  (`:121-123`, `:141-178`). A user is shown a diversification-break alert derived from a
  2-pair mean presented as a book-wide mean.
- **Suggested fix**: publish `pairs_contributing` per date and gate the series below
  `N(N−1)/2`; do **not** `fillna(0.0)` — a missing pair correlation is not zero correlation.

---

### QM-16 — the liquidity `score` on an all-NaN `Volume` column is `5.9`, not the tier's intended `3.0`
- **Severity**: WRONG-CONVENTION
- **Confidence**: VERIFIED
- **Cross-reference**: **duplicates `SVC-1` in `detail/services.md`**. Re-listed because it is
  a units/guard defect on the tier ladder's arithmetic.
- **Location**: `analytics_engine.py:3944-3973`
- **Implemented formula**:
  ```python
  3945:                volume = float(df[vol_col].mean())      # NaN on an all-NaN column
  3947:                daily_turnover = volume * price
  ...
  3972:                    score_raw = max(2.5, min(5.9, 3.0 + (daily_turnover / 2e7) * 2.9))
  ```
- **Mechanism**. Probe P3 confirms the language rule: Python's two-argument `min(a, b)` returns
  `a` unless `b < a`, so `min(5.9, nan)` is `5.9`, `max(2.5, 5.9)` is `5.9`. The published
  `score` is therefore **5.9** — Tier 4's *ceiling*, i.e. the best score a small-cap can get
  — produced from no volume measurement at all. `numpy` would propagate the NaN
  (`np.minimum(5.9, nan) == nan`, also measured), which is why this is a Python-`min` trap
  specifically and why a clamp-based "fix" would be wrong.
- **Impact**: `by_position.<t>.score`, `.category`, `.liquidation_days`, and the portfolio
  `overall_score` (`:4000`, the mean over published scores). Mitigated by
  `market_cap_provenance: "fallback"` / `is_estimate: true` (`:3986-3988`), which discloses
  that the *cap* was not measured but says nothing about the *score*.
- **Suggested fix**: test `np.isfinite(daily_turnover)` before the ladder and publish
  `score: None` plus a reason.

---

### QM-17 — `stress_test` consumes its weights un-normalized, unlike every other engine entry point
- **Severity**: WRONG-CONVENTION
- **Confidence**: VERIFIED
- **Location**: `analytics_engine.py:4197` and `:4285`; contrast `:3677-3680`
  (`calculate_portfolio_metrics`), `:3787-3789` (`factor_exposure_analysis`),
  `:3846-3848` (`concentration_analysis`)
- **Implemented formula**:
  ```python
  4197:            for ticker, weight in weights.items():
  ...
  4285:                weighted_impact += ticker_impact * weight
  4287:            portfolio_impact = round(weighted_impact, 4)
  4288:            max_drawdown = round(portfolio_impact * STRESS_DRAWDOWN_UPLIFT, 4)
  ```
  There is no `weight_sum = sum(...); weights = {k: v/weight_sum ...}` anywhere in
  `stress_test`. `portfolio_impact` and `max_drawdown` are therefore **proportional to the
  weight total**, and the payload publishes neither the total nor that a unit total is assumed
  (`methodology` at `:4443-4463` says only `portfolio_impact = sum of position_impact * weight`).
- **Mitigation (verified, not assumed)**: the only caller normalizes.
  `api/analytics.py:7688` calls `resolve_allocation`, which returns `{t: v/tot}` on the
  subset path and equal weights on the ad-hoc path, and `_load_portfolio_allocation`
  (`api/analytics.py:4276-4310`) divides by `total_mv` / `total_weight` on both of its
  branches. **So the live route is safe today.** The defect is that the invariant lives only in
  the caller, in a function that is documented as taking "market-value weights", and the next
  caller inherits it.
- **Impact**: `portfolio_impact`, `max_drawdown` — scaled by the weight total, and therefore
  silently wrong on a short or over-allocated book.
- **Suggested fix**: normalise at the top of `stress_test` (two lines), publish
  `weights_total_used`, and note that a negative weight is a short position and correctly
  contributes a gain under a negative shock.

---

### QM-18 — the risk-free rate is a hardcoded flat `0.02` for an Indian book, and it exists in two literals
- **Severity**: WRONG-CONVENTION
- **Confidence**: VERIFIED
- **Location**: `backend/app/config.py:53`; `backend/app/api/analytics.py:555`;
  consumers `analytics_engine.py:3630`, `:5468`, `:5473`, `optimization_service.py:729-745`,
  `:834`, `api/analytics.py:9414-9415`, `:9459-9460`, `:9630`
- **Implemented**:
  ```python
  53:    risk_free_rate: float = Field(default=0.02)  # 2% annual risk-free rate
  ...
  555:  TEAR_SHEET_RISK_FREE_RATE = 0.02
  ```
- **Mechanism**. Every excess-return statistic in the product — Sharpe, Sortino, the tangency
  portfolios, the quantstats tear sheet — deducts a constant 2 % with no indication of tenor,
  instrument or date. For an NSE book the conventional proxy is the 91-day or 364-day T-bill
  secondary-market yield, which has ranged widely around that level in the period this product
  covers. The duplication means an operator who changes `settings.risk_free_rate` fixes the
  engine and the tear sheet is still on 0.02 (or vice versa) — and nothing tests that they
  agree.
- **What is right, and worth stating so it is not re-litigated**: **252 trading days is used
  consistently** for every annualisation factor in this area — `TRADING_DAYS = 252` in
  `backtest_service.py:16`, `optimization_service.py:56`,
  `monte_carlo_service.py:32`, `regime_service.py:36`,
  `volatility_service.calculate_rolling_realized_volatility`'s default
  `annualization_factor=np.sqrt(252.0)` (`:153`), `analytics_engine.py:5459/5465/5045/5204`,
  `optimization_service._as_matrices` (`:88-89`). **No 365 anywhere.** Indian equities do not
  trade 365 days a year; 252 is the right convention and the codebase holds it.
- **Suggested fix**: single source of truth (`settings.risk_free_rate` only; delete
  `TEAR_SHEET_RISK_FREE_RATE` and reference `settings`), publish `risk_free_rate`,
  `risk_free_rate_source` and `annualization_trading_days: 252` on every block that uses one.
  A dated T-bill series is a separate piece of work; the duplication is the cheap half.

---

### QM-19 — the walk-forward backtest annualises CAGR without the repo's own `MIN_ANNUALIZE_DAYS` gate
- **Severity**: WRONG-CONVENTION
- **Confidence**: VERIFIED
- **Cross-reference**: **duplicates `SVC-7` in `detail/services.md`**.
- **Location**: `backtest_service.py:185-188`; the rule being skipped at
  `app/utils/holdings.py:32-35`
- **Implemented formula**:
  ```python
  185:    n_days = len(strat_rets)
  186:    years = n_days / TRADING_DAYS
  188:    strat_cagr = float((strat_cum[-1]) ** (1.0 / years) - 1.0) if years > 0 else 0.0
  ```
- **Mechanism**. `years = n_days/252` and the only guard is `years > 0`, true for any
  `n_days ≥ 1`, so a 10-simulated-day run publishes `cum ** 25.2`. `MIN_ANNUALIZE_DAYS = 30`
  exists (`holdings.py:35`, comment: *"annualizing a week of history fabricates triple-digit
  percentages"*) and is applied by the route to the **input** frame, not to `n_days`.
- **Impact**: `cagr`, `benchmark_cagr`. **The formula itself is the standard one** —
  `(terminal wealth)^(1/years) − 1` over compounded simple returns with `years = n/252` is
  textbook, and `benchmark_cagr` at `:189` is identical — so this is a disclosure gate, not a
  formula defect.
- **Suggested fix**: gate on `n_days >= MIN_ANNUALIZE_DAYS` and publish `None` plus the
  reason, matching `:201` and `:207` in the same function, which already do exactly that.

---

### QM-20 — the concentration refusal payload publishes `herfindahl_index: 0.0`
- **Severity**: WRONG-CONVENTION
- **Confidence**: VERIFIED
- **Location**: `analytics_engine.py:6316-6347`
- **Implemented formula**:
  ```python
  6318:            "largest_position": 0.0,
  6322:            "herfindahl_index": 0.0,
  6323:            "effective_positions": 0.0,
  6324:            "diversification_score": 0.0,
  6325:            "diversification_ratio": 1.0,
  6326:            "gini_coefficient": 0.0,
  ```
- **Mechanism**. For any non-empty book of `n` positive weights summing to 1,
  `HHI = Σw² ≥ 1/n > 0`, so **`0.0` is not a reachable measurement**. The file says so itself
  at `:6330-6335` ("diversification_score 0.0 on an empty book is indistinguishable from a
  measured single-holding book") and at `:5021-5023` in `risk_scoring` ("a 0.0 Herfindahl is
  impossible for a non-empty book") — and then publishes it anyway. `diversification_score 0.0`
  is the repo's *documented* correct value for a single-holding book
  (`CONCENTRATION_DIVERSIFICATION_SCALE`, `:413-418`), so `0.0` is right for `n = 1` and
  wrong-as-a-measurement for `n = 0`.
- **Mitigation that exists**: `n_holdings: 0` (`:6336`) and `error: "No position data available"`
  (`:6346`) are published, so a careful consumer can tell. `risk_scoring` correctly refuses to
  credit the leg in that case and adds an alert (`:5027`, `:5350-5355`).
- **Suggested fix**: `None` for `herfindahl_index`, `effective_positions`, `diversification_score`
  and `gini_coefficient` on the refusal path. The single-holding case still publishes `0.0`
  because there `n_holdings == 1` and it is the real value.

---

### QM-21 — no cvxpy solve ever checks `Problem.status` before its weights are published
- **Severity**: FRAGILE
- **Confidence**: VERIFIED
- **Location**: `optimization_service.py:521-527` (`_solve`), and the three checks that stand
  in for it: `:723-725` (`_min_vol`), `:740-745` (`_max_sharpe`), `:761-763` (`_min_cvar`);
  the un-`_solve`d path at `:843-845` (`_black_litterman`)
- **Implemented formula**:
  ```python
  521: def _solve(prob: cp.Problem) -> None:
  522:     """Solve in place; map cvxpy SolverError to ValueError so API routes
  523:     map solver failures to 400, not 500 (SolverError is not a ValueError)."""
  524:     try:
  525:         prob.solve(solver=cp.CLARABEL)
  526:     except cp.error.SolverError as e:
  527:         raise ValueError(f"Optimization solver failed: {e}") from e
  ```
  followed everywhere by `if w.value is None: raise ...`.
- **Mechanism**. `cvxpy.Problem.status` takes the values `optimal`, `optimal_inaccurate`,
  `infeasible`, `unbounded`, `solver_error` (cvxpy 1.9.3, installed). `w.value is None` catches
  `infeasible` / `unbounded` / `solver_error`, but **`optimal_inaccurate` leaves `w.value`
  populated** and every constraint satisfied only to the solver's own tolerance. That
  solution is then published as weights, as `expected_annual_return`, as
  `expected_annual_volatility` and as `expected_sharpe`, and — because
  `optimization_service.py:935` hardcodes `"solver": "cvxpy/clarabel"` — with a solver label
  that reads as a clean solve. `backtest_service.py:103-113` compounds it: an exception from
  `optimize()` is caught, logged as a warning and **silently replaced by the previous
  weights**, so a persistently `optimal_inaccurate` book backtests as a book that never
  rebalanced.
- **Impact**: any `min_vol`, `max_sharpe`, `min_cvar` or `black_litterman` recommendation on a
  hard (near-singular covariance, many nearly-collinear legs) book. Nothing on the payload
  distinguishes `optimal` from `optimal_inaccurate`.
- **Suggested fix**: in `_solve`, `if prob.status not in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE):
  raise ValueError(...)`, and **publish `problem_status` on every optimisation record** so
  `optimal_inaccurate` is visible rather than inferred.

---

### QM-22 — tail dependence publishes `rho = 0.0` for a constant leg
- **Severity**: FRAGILE
- **Confidence**: VERIFIED
- **Location**: `tail_risk_service.py:487-492`
- **Implemented formula**:
  ```python
  487:        # Linear correlation rho
  488:        if np.std(r_a) > 0 and np.std(r_b) > 0:
  489:            rho = float(np.corrcoef(r_a, r_b)[0, 1])
  490:        else:
  491:            rho = 0.0
  492:        rho = float(np.clip(rho, -0.9999, 0.9999))
  ```
- **Mechanism**. A zero-dispersion leg has **no** Pearson correlation. `0.0` is the strongest
  claim in the matrix's range ("no relationship whatsoever"), and it then feeds the copula
  formula at `:511-512` to produce a finite `lower_tail_lambda` that is published in the
  `N×N` matrix (`:582`) and in `high_tail_risk_pairs`. The rest of this file is scrupulous
  about exactly this distinction — see `UNMEASURABLE_CORRELATION_REASON` in
  `analytics_engine.py:511-514` and `measurable_clustering_universe` in
  `optimization_service.py:572-623`, both of which refuse rather than substitute. This one
  path does not.
- **Suggested fix**: raise `ValueError` (the function already raises for `< 10` overlapping
  observations, `:478-482`), or return `lambda_l = None` with a reason.

---

### QM-23 — `expected_shortfall_vs_target` publishes `0.0` when no path fails
- **Severity**: FRAGILE
- **Confidence**: VERIFIED
- **Location**: `monte_carlo_service.py:380-383`
- **Implemented formula**:
  ```python
  380:        failing = terminal[terminal < target_value]
  381:        expected_shortfall = (
  382:            round(float(failing.mean() - target_value), 2) if len(failing) else 0.0
  383:        )
  ```
- **Mechanism**. The conditional mean over an empty set is undefined; `0.0` is published
  instead. It is a *defensible* sentinel **only** because `prob_success` (`:379`, rounded to
  4 dp) is published beside it and would read `1.0` — so the combination is self-explaining
  at the 4-dp level. It stops self-explaining when `num_paths` is large enough that
  `round(prob_success, 4) == 1.0` while a handful of paths still missed (e.g. 19,999/20,000
  → `0.99995` → rounds to `1.0000`), where `0.0` asserts a certainty the sample does not have.
- **Suggested fix**: `None` when `len(failing) == 0`, or publish `failing_paths: int`
  alongside so the reader can see the support.

---

### QM-24 — `calculate_ewma_volatility` returns `0.0` for a single observation
- **Severity**: FRAGILE
- **Confidence**: VERIFIED
- **Location**: `volatility_service.py:225-230`, reached from `:274` and `:311`
- **Implemented formula**:
  ```python
  225:        if n == 1:
  226:            # A single return contains no dispersion estimate.  Returning its
  227:            # absolute value conflates return level with volatility; use the
  228:            # explicit zero-assumption contract until a second observation is
  229:            # available.
  230:            return 0.0
  ```
- **Mechanism**. The docstring is honest that a single observation has no dispersion
  estimate, then publishes `0.0` for it. In `forecast_garch_volatility` the `len(r) < 30`
  gate routes to this (`:272-280`), so a 1-row series returns
  `{"annualized_vol": 0.0, "model": "EWMA"}` — and in `calculate_volatility_cone` that `0.0`
  is ranked against the realized-vol distribution (`:466-470`) and lands in
  `valuation: "cheap"` (`:477-478`), i.e. "volatility is at or below the 25th percentile of
  its own history" as a *measurement*. `analytics_engine.volatility_forecast_point`'s EWMA
  branch uses the same zero-assumption contract at `:6554` with the same consequence.
- **Suggested fix**: return `None` (or raise, as the `n == 0` branch at `:221-224` already
  does) and have the cone publish `annualized_vol: None` + `valuation: "unknown"` — the
  `"unknown"` branch already exists at `:474-476`.

---

### QM-25 — every GARCH / EGARCH / EWMA fit is run on a ±20 %-winsorised return series, undisclosed
- **Severity**: FRAGILE
- **Confidence**: VERIFIED
- **Location**: `analytics_engine.py:6527-6528`
- **Implemented formula**:
  ```python
  6527:    clean = returns.replace([np.inf, -np.inf], np.nan).dropna()
  6528:    clean = clean.clip(lower=-0.20, upper=0.20)
  ```
- **Mechanism**. The clip is applied to the input of **all three** models before the fit, so
  the fitted conditional variance is the variance of a censored series. For NSE large-caps
  this is close to a no-op; for a book containing a small-cap or an IPO/F&O segment it is a
  material left-tail truncation applied to the very series the tail model is supposed to
  characterise — and it interacts with `is_fat_tailed` / GPD shape reported elsewhere. The
  same clip appears in `stress_test` at `:4263` where it *is* disclosed
  (`"return_clip": [-0.20, 0.20]`, `:4424`); in the forecast block it is disclosed nowhere —
  neither in the payload, nor in `FORECAST_REFIT_COUNT_RULE`, nor in the module constants
  section.
- **Suggested fix**: name the clip as a constant next to `FORECAST_VOL_CLIP_LOW`
  (`analytics_engine.py:849`) and publish `input_return_clip: [-0.20, 0.20]` on every
  forecast — exactly as `stress_test` already does.

---

### QM-26 — `hedge_ratio_beta` is published with no finiteness guard, and it sizes the directive
- **Severity**: FRAGILE
- **Confidence**: DERIVED
- **Location**: `cointegration_service.py:1423-1431`; the sign gate at `:1539`; the notional
  convention at `:131-136`
- **Implemented formula**:
  ```python
  1426:        beta, alpha = np.polyfit(p_b, p_a, 1)
  1427:        beta = float(beta)
  1428:        alpha = float(alpha)
  ```
- **Mechanism**. `np.polyfit` on a perfectly collinear pair returns a finite slope, and the
  module guards only `beta <= 0.0` (`:1539`) — never `math.isfinite`. In the identical-series
  case `spread_std` collapses, `current_zscore` correctly becomes `None` (`:1471-1472`) and
  the directive is withheld, so the live consequence is limited to the published
  `hedge_ratio_beta` / `intercept_alpha` values and their SEs. It matters because
  `SIGNAL_NOTIONAL_CONVENTION` tells a reader that `beta` *is* the trade size, and the
  module has already been bitten once by an unguarded polyfit elsewhere — see the
  `_COMPLEX_WARNING` block at `:991-999` and the note at `:1088-1097` about `float()` on a
  numpy complex scalar.
- **Suggested fix**: reject non-finite `beta`/`alpha` alongside the EG result in QM-4.

---

### QM-27 — `risk_scoring`'s concentration leg scores `min(30, hhi*100)` from an unmeasured Herfindahl
- **Severity**: FRAGILE
- **Confidence**: VERIFIED
- **Location**: `analytics_engine.py:5027-5037`
- **Implemented formula**:
  ```python
  5027:            concentration_unavailable = bool(concentration_result.get("error"))
  5028:            hhi = concentration_result.get('herfindahl_index', 0.1)
  5029:            concentration_score = min(30, hhi * 100)
  ```
- **Mechanism**. When `concentration_analysis` refuses (`:6316-6347`), it returns
  `herfindahl_index: 0.0`, so `concentration_score` becomes `min(30, 0.0) = 0.0` — the leg's
  **best possible** risk score — and it is *not* added to `excluded`, so it keeps its 0.20
  nominal weight and drags `overall_score` down by up to 6 points. The code is *aware* of
  this (`:5020-5026` spells it out) and mitigates it by publishing
  `inputs['concentration'] = None` and adding an alert (`:5350-5355`), but the published
  `components.concentration` is still `0.0` and `components.concentration.status` is still
  `"measured"`, because `_is_saturated`/`included` at `:2671-2675` key off `scores` and
  `excluded`, not off `concentration_unavailable`.
- **Live reachability**: low — `risk_scoring` already returns early on `not weights`
  (`:4992`), and `concentration_analysis` only sets `error` on an empty/all-non-positive
  weight set or an exception. Listed as FRAGILE, not WRONG-NUMBER, on that basis.
- **Suggested fix**: `if concentration_unavailable: scores['concentration'] = None;
  excluded.append('concentration')` — the pattern the volatility, correlation and factor legs
  already use at `:5049-5055`, `:5098-5104` and `:5154-5167`.

---

### QM-28 — the factor-exposure per-ticker handler turns every exception into the same two-field block
- **Severity**: FRAGILE
- **Confidence**: VERIFIED
- **Location**: `analytics_engine.py:6175-6182`
- **Implemented formula**:
  ```python
  6175:                        except Exception:
  6176:                            positions_exp[ticker] = {
  6177:                                'alpha': None, 'annualized_alpha': None, 'market': None,
  6178:                                'alpha_std_error': None, 'market_std_error': None,
  6179:                                'std_error_basis': None, 'std_error_robust': None,
  6180:                                'is_limited_history': False, 'history_warning': None,
  6181:                                'data_points': 0, 'error': 'factor regression failed'
  6182:                            }
  ```
- **Mechanism**. `data_points` is set to **0** even though `:6130` had already measured the
  real count, so a ticker with 180 usable rows that failed on the HAC fit publishes
  `data_points: 0` and `is_limited_history: False` — two statements that are both false and
  that point a reader at "no data" instead of "the regression failed". Compare the careful
  degradation elsewhere in the same file (`_finite_param` returns `None` and says why, `:6086`;
  `_ols_with_published_se` returns `"ols_uncorrected_hac_unavailable"`, `False` and keeps the
  fit, `:6081-6083`).
- **Impact**: `positions.<ticker>` on `factor_exposure_analysis`. No published number is
  wrong, but the diagnostic surface misdirects.
- **Suggested fix**: carry `data_pts`, `is_limited` and `exc` into the failure block.

---

## VERIFIED-CORRECT — do not re-audit these by name

Each of the following was read at the cited line **and** checked against a reference
(a library source in `.venv`, a closed-form identity, or a numeric probe). They are emitted
because the absence of a finding is the most re-litigated thing in an audit.

### VERIFIED-CORRECT — realized risk (`analytics_engine.py`)

- **VC-1 `annual_return` = `returns.mean() * 252`** (`:5464`). Arithmetic-mean annualisation,
  the standard Sharpe/Lo (2002) convention. Correctly **not** used for CAGR, which is computed
  geometrically elsewhere. `annual_return` is `None` below 10 observations (`:5458-5461`) —
  a refusal, not a substitute number.
- **VC-2 `annual_volatility` = `returns.std() * np.sqrt(252)`** (`:5465`). pandas `.std()`
  defaults to `ddof=1`; the input is daily and unannualised, so there is **no
  double-annualisation** anywhere on this path.
- **VC-3 `sharpe_ratio` = `(252·mean − rf) / (std·√252)`** (`:5468`, formula quoted in QM-3).
  The formula is the standard Sharpe; only the `else 0.0` branch is defective (QM-3).
- **VC-4 `sortino_ratio`, downside denominator** (`:5470-5476`).
  ```python
  5473:                target = self.risk_free_rate / 252
  5474:                downside = np.minimum(0.0, returns.to_numpy(dtype=float) - target)
  5475:                downside_deviation = float(np.sqrt(np.mean(downside ** 2)) * np.sqrt(252)) if len(returns) else 0.0
  ```
  `np.mean` over the **full sample length**, not over the count of downside observations.
  This is the standard *target downside deviation* (Sortino & Price 1994) and is what
  `quantstats` does — see VC-10. **The frequently-wrong denominator is not wrong here.**
  The numerator is the arithmetic annualised excess return, consistent with the Sharpe
  convention in the same function; that pairing is a convention, and the docstring at
  `:5470-5472` states it.
- **VC-5 `hit_ratio` = `(returns > 0).mean()`** (`:5479`). Share of positive days against a
  **zero** threshold (not the MAR). Defensible for a field named `hit_ratio`; the MAR-based
  alternative would be a different statistic and would need a different name.
- **VC-6 `var_95` / `cvar_95` formulas** (`:5498-5501`). Historical percentile VaR and
  historical mean-excess-at-or-below-VaR ES, both standard. Only the *declaration* is missing
  (QM-12).
- **VC-7 `max_drawdown`** (`:5510-5530`). `(1 + r).cumprod()` with a `1.0` baseline prepended,
  `cummax`, `(wealth − peak)/peak`, `.min()`. The baseline is what lets a first-day loss
  register; verified identical to `quantstats.stats.max_drawdown` (VC-10) and to the engine's
  own bootstrap restatement at `:2274-2280`.
- **VC-8 `skewness` / `kurtosis` formulas** (`:5541-5542`). pandas bias-corrected
  Fisher-Pearson skewness and Fisher **excess** kurtosis. The *values* are right; only the
  *name* is wrong (QM-11).
- **VC-9 portfolio return aggregation** (`aggregate_active_returns`, `:255-293`).
  `PORTFOLIO_RETURN_MIN_COVERAGE = 1.0` (`:56`): a date is published only when the **whole
  declared book** traded, and short dates are **dropped**, never zero-filled and never
  renormalised. This is the opposite of the common partial-basket bug and it is deliberate and
  documented at `:260-275`. Verified correct.
- **VC-10 the quantstats restatements** (`quantstats_ratio_statistics`, `:2015-2121`) were
  checked line-by-line against `quantstats 0.0.85` in `.venv`:
  - `sortino` (`:2042-2047`) vs `quantstats/stats.py:1124`
    `downside = _np.sqrt((returns[returns < 0] ** 2).sum() / returns.count())` — **identical**
    (full-`N` denominator).
  - `cagr` (`:2064-2069`) vs `quantstats/stats.py:1674-1676`
    `_np.abs(total + 1.0) ** (1.0 / years) - 1`, `years = returns.count() / periods` —
    **identical**, including the `abs()` quirk the code reproduces deliberately.
  - `calmar` (`:2098-2100`) vs `quantstats/stats.py:1816` `cagr_ratio / abs(max_dd)` —
    **identical**.
  - `omega` (`:2049-2057`) vs `quantstats/stats.py:1548-1560`: with `rf=0`,
    `required_return=0`, the threshold is `(1+0)^(1/252)−1 = 0`, so numerator/denominator are
    the positive/negative parts — **identical**.
  - `tail_ratio` (`:2102-2109`) vs `quantstats/stats.py:2229` `abs(upper/lower)` with
    pandas default linear interpolation — **identical**.
  - `max_drawdown` (`:2075-2096`) vs `quantstats/stats.py:2700-2716`, including the
    `from_returns` baseline rule from `_get_baseline_value` (`:2629-2664`) — **identical**.
  - `daily_rf` (`:2034`) `(1+rf)**(1/periods) − 1` matches `quantstats/utils.py`
    `to_excess_returns`: `rf = _np.power(1 + rf, 1.0 / nperiods) - 1.0` — **identical**
    (compounded, not divided — the two differ in the 4th decimal at `rf=0.02, 252`, and the
    code gets it right).
  - `volatility` (`:2071-2073`) uses `ddof=1` and `√252` — **identical**.
  These matter because `measure_estimate_uncertainty` refuses to publish an interval unless
  the resampling restatement reproduces the published point, and `api/analytics.py:9412-9422`
  computes the published tear-sheet values from these very `quantstats` functions.
- **VC-11 `market_model_statistics` beta/alpha** (`:2135-2148`). `cov(p,b)/var(b)` with both
  terms on `ddof=1` (the `ddof` cancels in the ratio, so this equals the population ratio —
  no double-counting), and `alpha = (p̄ − β·b̄)·252`, the standard arithmetic Jensen alpha.
  `market_model_witness` (`:2159-2214`) is a genuinely independent `np.linalg.lstsq`
  derivation of the same two numbers and agrees on a correctly aligned frame.
- **VC-12 `regression_r_squared_statistics`** (`:2437-2447`). `Sxy²/(Sxx·Syy)` on centred sums,
  no `ddof` — which is correct because the `ddof` cancels, and it matches statsmodels'
  `rsquared` (which the code notes at `:2427-2431`). The bootstrap restatement of the risk
  score's factor leg is therefore an interval for the number actually printed.
- **VC-13 `pairwise_average_correlation_statistics`** (`:2333-2419`). Reproduces
  `pandas.DataFrame.corr()`'s **pairwise-complete** semantics with batched
  `(k,rows)@(rows,k)` accumulators, including pandas' own NaN rule (fewer than 2 shared rows
  or no variation ⇒ not measurable, skipped by the mean). Verified correct, and the reason it
  exists — a late-listed leg makes the complete-case mean a *different number* — is correct.
- **VC-14 `ar1_autocorrelation`** (`:1022-1040`).
  `Σ(right−mean)(left−mean)/Σ(right−mean)²` with `left = series[1:]` (r_t) and
  `right = series[:-1]` (r_{t−1}) — the regressor is in the **denominator**, so this is the OLS
  slope of `r_t` on `r_{t−1}` exactly as the docstring says. No sign flip.
- **VC-15 `effective_sample_size` = `n(1−ρ)/(1+ρ)`** (`:1043-1060`). The standard
  Quenouille/Bartlett AR(1) variance-inflation adjustment of the sample mean. Guarded against
  `|ρ| ≥ 1`.
- **VC-16 `moving_block_size` = `n^(1/3)`** (`:1197-1202`) and `moving_block_indices`
  (`:1205-1224`) implement the circular moving-block bootstrap of Politis & Romano (1994) /
  Politis & White (2004) as documented at `:1006-1019`. The `ceil(n/L)` starts, the modulo wrap
  and the truncation to `n` are all correct.
- **VC-17 `TAIL_ES_MULTIPLIER = 2.06` / `TAIL_Z_MULTIPLIER = 1.645`** (`:834-835`).
  Measured against `scipy.stats.norm`: `ppf(0.95) = 1.6448536`, and the normal ES at 95 % is
  `pdf(z)/0.05 = 2.0627128`. Both correct to the declared precision, and the ES constant is the
  exact normal ES rather than the common `1.25·z` approximation. Correctly disclosed at
  `:824-832`.

### VERIFIED-CORRECT — concentration, risk score, sizing, stress (`analytics_engine.py`)

- **VC-18 `herfindahl_index` = `Σw²` over normalised positive weights** (`:3861`). Zero,
  negative and non-finite rows are dropped **before** normalisation (`:3837-3848`), so they
  cannot dilute the index. Matches the repo's own invariant.
- **VC-19 `effective_positions` = `1/HHI`** (`:3864`) — the standard effective number of
  independent bets, `N_eff = 1/HHI`. Matches `AGENTS.md`'s stated invariant
  (`$N_{\text{eff}} = 1/HHI$`).
- **VC-20 `diversification_score` = `((1 − HHI)/(1 − 1/n))·100`** (`:3868`), `0.0` for
  `n ≤ 1`. This is the standard HHI normalised against its equal-weight value, it saturates at
  100 exactly at equal weight, at 0 exactly when one name holds the book, and the formula is
  published on every payload (`:437-443`, `:3891-3893`). Matches `AGENTS.md`'s invariant.
- **VC-21 `diversification_ratio` = `N_eff / n`** (`:3869`). A *different* statistic from the
  score, and the payload says so at length and correctly explains the orientation
  (`:445-466`). Publishing both and refusing to reconcile them is the right call.
- **VC-22 `gini_coefficient`** (`:3873`).
  `(2·Σ(i·w_(i)) − (n+1)) / n` over ascending-sorted weights. Probe P3 confirms this equals the
  reference form `2·Σ(i·w_i)/(n·Σw) − (n+1)/n` exactly on normalised weights
  (`[0.05,0.05,0.1,0.1,0.7] → 0.540000` both ways; `[0.1,0.2,0.3,0.4] → 0.250000` both ways).
  **Correct**, including the degenerate cases (equal weights → 0; single holding → 0).
- **VC-23 `top_3` / `top_5` / `top_10`** (`:3856-3858`). `np.sort(w)[-k:].sum()`; for `n < 10`
  `top_10` is the whole book and is published as `1.0`, which is the correct value for a
  fully-concentrated 3-name book.
- **VC-24 the risk-score sub-score formulas** (`:5029`, `:5057`, `:5118-5123`, `:5162`,
  `:5216`). Each is `min(30, <one published input>)` and matches `RISK_SCORE_LEG_SPECS`
  (`:590-663`) exactly, including the `√252` annualisation on the two volatility legs and
  `ddof=1` pandas std. `RISK_SCORE_WEIGHTS` sums to **1.00**
  (`0.20+0.25+0.20+0.25+0.10`, `:566-572`), and excluded legs are dropped with the remainder
  renormalised (`:5241-5247`) rather than counted as zero — the hard-zero failure this module
  has already fixed twice.
- **VC-25 `avg_pairwise_correlation`** (`:5092-5097`). Mean of the **finite** upper-triangle
  of `returns.corr()`; a leg with no measurable correlation excludes the leg rather than
  contributing `0.0`. A pair below two shared rows is NaN in pandas and is skipped, which
  matches `MIN_SHARED_ROWS_FOR_CORRELATION` (`:498`) and `UNMEASURABLE_CORRELATION_REASON`
  (`:511-514`).
- **VC-26 inverse-volatility risk parity weights** (`:4720-4743`). `w_i ∝ 1/σ_i` on the
  **annualized** volatilities (the common `√252` factor cancels), normalised over positive-weight,
  positive-σ legs only. Exactly `AGENTS.md`'s stated invariant
  (`$w_i \propto 1/\sigma_i$`). Zero-weight positions are never given a synthetic allocation.
- **VC-27 the scale-to-target identity** (`:4799`, `:4820`, `:4943-4946`).
  `scale = target / rec_vol_ann` and `imposed_target_volatility = rec_vol_ann · scale`, which
  is the target **by construction** — and the payload says exactly that rather than selling
  the restatement as a measurement (`"sizing_volatility_times_scale_equals_target_by_construction"`).
  `achieved_volatility` is separately and correctly measured on the sample covariance of the
  measured returns (`:4824-4826`, `:4487-4526`), which is *not* the same number.
- **VC-28 `portfolio_impact` per ticker** (`:4281-4282`).
  `market_shock · sector_elasticity · volatility_adjustment`, clipped to `[-0.75, -0.02]` for a
  negative shock, with the volatility factor measured from `clip(lower=−0.20, upper=0.20)`
  annualised at `√252` and bounded to `[0.85, 1.25]`. Every input is published in
  `shock_inputs` (`:4363-4428`) and every output in `units` (`:4429-4442`), and the whole
  object states it is a deterministic proxy with **no path sampling** (`:4443-4463`).
  `max_drawdown = portfolio_impact × 1.15` is labelled
  `derived_from_shock_proxy` with the constant in the key name — a fixed uplift, not a
  simulated drawdown, correctly declared.
- **VC-29 the stress co-movement diagnostic** (`:3516-3621`). Leave-one-out regression of each
  holding on the **equal-weighted mean of the others**, `coefficient = (c_h·c_r)/(c_r·c_r)`.
  Correctly guarded: `None` + reason below 3 reference legs (because on a two-name book each
  coefficient is 1.0 by arithmetic), below 30 paired observations, on a zero-variance
  reference, and on a non-finite coefficient. And — correctly — it is **not** applied to any
  shock, with the reason stated at `:3519-3546`. This is the clearest example in the codebase
  of a cheap-substitute statistic that was measured, published as a diagnostic, and
  deliberately *not* used as the thing it resembles.

### VERIFIED-CORRECT — other services

- **VC-30 backtest CAGR / Sharpe / Calmar / turnover** (`backtest_service.py:188`, `:201-207`,
  `:118`). CAGR `(cum[-1])^(252/n) − 1` over compounded simple returns with `n` = simulated
  out-of-sample days; Sharpe `(mean_daily·252 − rf)/(std_ddof1·√252)` (arithmetic-mean
  annualisation, matching Lo 2002); Calmar `CAGR/|max_drawdown|` with the baseline-inclusive
  drawdown of `:175-183`; turnover `0.5·Σ|Δw|` (`:118`) correctly **halved** so a 10 % A→B
  reallocation reads 0.10, not 0.20. All formulas standard. Only the annualisation *gate* is
  missing (QM-19).
- **VC-31 walk-forward weight drift** (`:157-158`).
  `w[t+1] = w[t]·(1+r[t])/(1 + w[t]ᵀr[t])` is the correct self-financing drift, and the
  weights used for the period's return are the **pre-drift** ones (`:137`, `:140-144`) — the
  classic off-by-one that would make day *t* earn its own rebalance is not present.
- **VC-32 `rolling_realized_volatility`** (`volatility_service.py:186-188`).
  `.rolling(window).std(ddof=1) · √252`, with `min_periods = max(5, min(window, finite_count))`
  (`:184`) so a window cannot report on fewer than 5 observations.
- **VC-33 `calculate_ewma_volatility`** (`:233-241`). Vectorised RiskMetrics:
  weights `(1−λ)λ^(N−1−t)`, renormalised to sum 1, `Σw·r²`, `√·√252`, **no mean subtraction**
  — which is correct for an EWMA, since the recursion assumes a zero conditional mean.
- **VC-34 `forecast_garch_volatility`** (`volatility_service.py:284-300`). Returns are scaled
  by 100 for the arch optimiser, `mean="Zero"`, `rescale=False`, `dist="normal"`; the
  variance path is read off `forecast.variance.iloc[-1]`, and the rescale is
  `√(mean_path_variance · 252)/100` (`:292-294`) — the `100` appears exactly once, in the
  right place. The `omega`/`alpha[1]`/`beta[1]` parameter extraction matches `arch`'s naming
  for a zero-mean GARCH(1,1). The EWMA fallback on `len(r) < 30` (`:272-280`) and on any
  exception (`:309-317`) is **disclosed** via `model: "EWMA"` and `params.fallback: true`.
- **VC-35 the vol-cone effective-`n` correction** (`volatility_service.py:53-57`). For `n_windows`
  overlapping windows of length `L`, `effective_n = n_windows / L` under iid returns — the
  standard order-of-magnitude correction, and the counts, the Wald half-width and the
  withholding rule are all published (`:131-140`) rather than asserted.
- **VC-36 Parkinson volatility** (`regime_service.py:264-273`).
  `(ln(H/L))²` pooled **before** the sqrt and divided by `4·ln 2`:
  `pooled_var = rolling(10).mean(log_hl²)/(4·ln 2)`, `parkinson_vol = √pooled · √252`. The
  comment at `:269-271` names the Jensen trap (annualising each observation then averaging the
  sigmas) and avoids it. Correct.
- **VC-37 per-state CAGR** (`regime_service.py:339-340`).
  `(∏(1+r_sub))^(252/n_sub) − 1` — geometric, annualised by the state's **own** observation
  count, which is published beside it as `observations` and `annualization_factor`
  (`:354-357`). Correct. (The arithmetic fallback `r_sub.mean()*252` on `cum_prod <= 0` at
  `:340` is an undisclosed definition switch — noted under QM-07's neighbourhood, low
  materiality.)
- **VC-38 the regime HMM's disclosed non-estimates** (`regime_service.py:220-227`, `:313-323`).
  `params="mc"` fixes the transition matrix and start probabilities at the configured sticky
  prior, and the docstring says so in those words: *"the published diagonal is a CONFIGURED
  PRIOR, not a fitted quantity; the fitted parameters are the per-state means and
  covariances."* `hmmlearn`'s ConvergenceMonitor is read and both "tolerance met" and "cap
  exhausted" are reported separately (`:116-201`), and the in-sample / no-holdout nature of
  the posterior is stated in the payload (`:192-199`).
- **VC-39 `portfolio_regime_summary`** (`app/utils/holdings.py:450-467`). CAGR
  `(∏(1+r))^(252/n) − 1` and `ann_vol = std·√252` (pandas `ddof=1`), both gated on
  `MIN_ANNUALIZE_DAYS = 30`, with the holding-period total always published. Correct, and the
  gate is the right gate.
- **VC-40 Monte Carlo calibration** (`monte_carlo_service.py:76-77`). `mean·252` and
  `std(ddof=1)·√252` from the dropna'd daily series, with `MIN_HIST_OBS = 60`. Correct.
- **VC-41 `prob_success` semantics** (`monte_carlo_service.py:379`, `:394-408`). The fraction
  of paths whose **terminal** value clears the target, and the payload states in plain words
  that this is **not** the path-touch probability and is a **lower bound** on it — with the
  correct direction of the bound. This is exactly the disclosure the Merton (1990)
  "probability of reaching a goal" ambiguity usually gets wrong.
- **VC-42 Student-t moment matching** (`monte_carlo_service.py:159-164`). Analytic
  `analytic_std = scale·√(ν/(ν−2))` — the correct Student-t variance-to-standard-deviation
  conversion for scipy's `scale` parameterisation — and the daily simulation is
  `r̄ + s̄·z`, i.e. matched to the **sample** mean and `ddof=1` std. Innovations are winsorised
  at ±8 z and simple returns floored at −95 % so `log1p` stays finite; both are disclosed in
  the docstring at `:146-152`.
- **VC-43 `_simulate_gbm`'s drift** (`monte_carlo_service.py:119-120`).
  `drift = (μ − σ²/2)·dt`, `diffusion = σ·√dt` with `dt = 1/252`. This is the internally
  consistent GBM form when `μ` is the **arithmetic** expected return rate, which is what
  `_calibrate` supplies (`:76`). `E[S_T] = S₀·e^{μT}` follows correctly.
- **VC-44 the EVT-POT machinery** (`tail_risk_service.py`).
  - Historical VaR/ES: `np.percentile(losses, 100·c)` and the mean of the tail at or above it
    (`:244-246`) — standard.
  - POT VaR: `u + (β/ξ)[(N/n_u)·α]^(−ξ) − 1` (`:259`) with the `ξ→0` exponential limit
    `u − β·ln(ratio)` (`:261`) — the standard single-threshold EVT estimator.
  - **POT ES: `(VaR + β − ξ·u)/(1 − ξ)`** (`:262`). **Verified by probe P1b.** Algebraically
    identical to `u + E[Y | Y > y]` with `y = VaR − u` and the GPD conditional mean
    `E[Y | Y > y] = (y + β)/(1 − ξ)` (probe reports `diff = -5.551e-17`), and the end-to-end
    check against a 400,000-observation synthetic with a known GPD tail puts it **0.51 % from
    the Monte-Carlo truth** `E[X | X > VaR]`, versus 39 % for the first derivation I tested.
    **The formula is right.**
  - `stats.genpareto.fit(exceedances, floc=0.0)` (`:286`) — the correct scipy call, with the
    sign convention of `c` stated and defended at length in `GPD_SHAPE_SIGN_RULE` (`:61-69`)
    from the scipy pdf itself.
  - The stability clip is applied to a **separately named** `xi_constrained` / `xi_raw` pair
    and disclosed (`constraint_applied`, `constraint_reason`, `gpd_shape_xi_raw`), so a clipped
    value is never mistaken for the MLE fit.
- **VC-45 the t-copula lower-tail dependence coefficient**
  (`tail_risk_service.py:451`, `:511-512`). `λ_L = 2·T_{ν+1}(−√((ν+1)(1−ρ)/(1+ρ)))` is the
  standard Student-t copula lower-tail dependence coefficient, and the code's docstring states
  it verbatim. The fact that `ν` is the **average of two univariate marginal t-fits**, not a
  joint copula fit, is disclosed at `:469-475` as "an approximation, not a joint copula fit" —
  which is the honest label. `stats.t.fit(...)[0]` correctly takes the df as the first
  element of scipy's `(df, loc, scale)` return.
- **VC-46 the ADF + KPSS pair** (`cointegration_service.py:1157-1288`).
  ADF null = unit root, KPSS null = stationarity; `i1` only when ADF does **not** reject and
  KPSS **does**; `stationary` only in the mirror case; anything else is `undetermined` with a
  reason. Both on `log(price)` (`:1208`), both with `trend="c"` (`:1214`, `:1219`),
  `max_lags=1` with `method="aic"` (`:1211-1213`) — verified against
  `arch 8.0.0` `ADF.__init__(y, lags=None, trend="c", max_lags=None, method="aic", ...)` and
  `KPSS(y, lags=..., trend=...)`, so the keyword names and the `method="aic"` are right — and
  the KPSS `lags` is the Newey–West (1994) bandwidth `⌊4(n/100)^{2/9}⌋` (`:1119-1133`), never
  0. The rule, the transform, the lags and the alpha are all published on every result
  (`:1236-1248`). This is the single most rigorously specified numeric block in the codebase.
- **VC-47 OU half-life** (`cointegration_service.py:962-986`).
  `Δz = a + γ·z_{t−1}`, `γ = e^{−θ} − 1`, `θ = −ln(1+γ)`, `t½ = ln2/θ`. `np.polyfit(z_lag, dz, 1)`
  returns `[slope, intercept]` for degree 1, so `gamma` is the slope — correct. Guarded for
  `γ ≥ 0` (no mean reversion), `−1 ≥ γ` (oscillatory ⇒ **no** half-life exists, returns
  `None` rather than fabricating `1.0`) and a degenerate spread variance.
- **VC-48 the Bonferroni / Benjamini–Hochberg corrections**
  (`cointegration_service.py:427-466`). `α/m` is Bonferroni; BH is a correct step-up taking the
  largest `k` with `p_(k) ≤ k·q/m`, and it publishes the critical value `k·q/m` at that `k` so
  the rejection set is re-derivable. Both are published beside the ungated p-value, and the
  module explains **why** the trade-directive gate uses Bonferroni (family-wise error rate)
  while BH controls the expected false-discovery proportion (`:138-144`) — correct reasoning,
  correctly stated.
- **VC-49 the concentration and liquidity band rules** (`analytics_engine.py:308-312`,
  `:2566-2572`). Bands are derived from the **already-rounded published** score
  (`round(raw,1)` applied once, `:3977`), which is a documented fix for a real defect
  (`:299-304`), and the whole table ships with the payload (`:4025`).
- **VC-50 MFI's scale** (`indicators_service.py:154-159`). **The prior finding is correctly
  fixed.** The installed `stockstats 0.6.8` `_get_mfi`
  (`backend/.venv/Lib/site-packages/stockstats.py:1462-1479`) computes
  `mfi = pos_sum / total_flow` with `out=np.full_like(..., 0.5)` and `mfi[:window] = 0.5` —
  i.e. a **0–1 fraction**. `values = values * 100.0` at `:159` is therefore the right
  conversion to the documented 0–100 contract, and the NaN guard at `:163-175` correctly
  refuses a row with any non-finite or non-positive price. **Do not re-audit MFI.**
- **VC-51 stockstats RSI** (`stockstats.py:517-531`). `100 · up_sma/(up_sma+down_sma)` with
  `smma` (Wilder's smoothing), `rsi[0] = 50`. That is Wilder's RSI, not a simple-average
  variant. Bollinger (`:1207-1225`) is `MA ± 2·mov_std`, matching the service's
  `SUPPORTED_INDICATORS` contract string at `indicators_service.py:43-44` ("~2 std").
- **VC-52 screener filter units** (`screener_service.py:317-324` vs
  `bfinance/market/quotes.py:241-246`). `info["returnOnEquity"]` is emitted as `r.roe / 100`
  (a **fraction**) and `info["returnOnCapitalEmployed"]` as `r.roce` (declared
  `"Return on Capital Employed (ROCE %)"`, `bfinance/models/company.py:20`, a **percent**).
  The filter multiplies ROE by 100 and leaves ROCE alone — which is the only correct handling
  of that upstream asymmetry, and `min_roce` / `min_roe` therefore both mean percent.
  `dividendYield` is emitted raw and documented as percent (`company.py:19`), and the comment
  at `screener_service.py:321-324` records the exact upstream lines that establish it.
- **VC-53 Graham upside** (`equity_research_service.py:60`, `:235`).
  `((graham_number − current_price)/current_price)·100` — correct, and `None` rather than 0.0
  when either input is absent.

---

## Numeric probes

All run from `backend/` as `uv run --extra dev python <file>` against
`backend/.venv` (CPython 3.12, numpy/scipy/statsmodels 0.15/cvxpy 1.9.3). **Pure computation:
no network, no database, no project-service import.**

| # | Script | What it proved |
|---|---|---|
| **P1a/P1b** | POT ES. 400,000 draws with an exactly-GPD(ξ=0.35, β=0.02) tail above the 95th percentile; fit `scipy.stats.genpareto`; evaluate `tail_risk_service.py:262`; compare with `u + (y+β)/(1−ξ)` and with a Monte-Carlo `E[X\|X>VaR]`. | The published ES is **correct**: algebraically identical to the derived conditional mean (`diff = −5.55e-17`) and **0.51 %** from Monte-Carlo truth. My first derivation was wrong, not the code. → **VC-44** |
| **P2c/P2e** | Black-Litterman posterior covariance. Compare `[(τΣ)⁻¹+PᵀΩ⁻¹P]⁻¹`, `τΣ−τΣPᵀ(Ω+τPΣPᵀ)⁻¹PτΣ`, `Σ+τΣPᵀM⁻¹PΣ`, `Σ+τ²ΣPᵀM⁻¹PΣ` and the code's `(1+τ)Σ−τ²ΣPᵀM⁻¹PΣ`. | The two reference forms agree to `1.0e-17`; the code's differs by `9.6e-1` max element and **inflates** the prior's trace by +3.11 % where the posterior shrinks it by −96.9 %. → **QM-1** |
| **P4** | Same instance, solved as the tangency programme the code solves (`cvxpy` CLARABEL, long-only, `excess·y = 1`, normalised). | Code weights `[0.2107 0.3614 0.2038 0.2241]` vs correct `[0.2698 0.2276 0.2541 0.2485]`, max Δ 0.134. Isolates the causes: the covariance form moves the max weight by **0.1271**, the double-`rf` by **0.0052**. Confirms `cvxpy` status is `optimal` in both cases (so QM-21 is latent, not currently firing). → **QM-1, QM-5** |
| **P3** | Degenerate inputs on bare libraries: `statsmodels.coint` on `coint(2x,x)`, `coint(x,x)`, `coint(x+5,x)`; `max(0.0, rsquared_adj)` closed form; the Gini identity; Python `min` vs NaN. | Collinear legs give `t=−inf, p=0.0` with only a `CollinearityWarning` (not an `Exception`) → `is_cointegrated=True` and `json.dumps` emits bare `-Infinity`. `n=10, R²=0.05 → adjR²=−0.0687 → published 0.0`. Gini matches the reference form to 6 dp on two books. `min(30, nan*100)==30` and `np.minimum(30,nan)==nan` — the Python-`min` trap that makes a clamp-based "fix" wrong. → **QM-2, QM-4, QM-16, VC-22** |

---

## Uncertainty — what I could **not** verify

1. **`^NSEI`'s actual close basis at runtime** (QM-10). I verified the symbol, the column
   preference order and the fact that no TRI is used. Whether the feed returns an adjusted
   series identical to the raw close is a data question I cannot answer without a fetch, and
   I did not make one.
2. **The t-copula `λ_L` formula's canonical citation** (VC-45). The code states it verbatim at
   `tail_risk_service.py:451` and it matches my recollection of the Student-t copula
   literature, but I did not locate it in a source document inside this environment. Treated
   as **DERIVED**, not VERIFIED; the disclosed approximation (marginal-`ν`, not a joint fit)
   is the larger caveat anyway.
3. **`quantstats` `cint`** — `inspect.getsource(statsmodels...coint)` raised
   `NameError: name 'cint' is not defined` in this environment, so the reference for `coint` is
   the docstring quoted in QM-4 plus the observed behaviour in probe P3, both from the
   installed `statsmodels 0.15.0`. That is sufficient for QM-4; a curious name in that
   function's body I did not chase.
4. **`arch` simulation determinism** (QM-21's blast radius). The module's comment at
   `:6591-6635` documents at length why `rng=seeded.simulate([])` is the only seeding path
   `arch 8.0.0` reads, and that the old int seed was ignored. I did not re-derive that
   experimentally; I read the code path and accepted the repo's account.
5. **The MFI scaling fix's git history.** I verified the *current* code against the *installed*
   `stockstats 0.6.8` source, which is decisive. I did not check whether the previously-audited
   version also multiplied by 100 (i.e. whether the prior finding and the fix were the same
   commit), and I do not need to — the present code is right.
6. **`ai_context_service.py` (2,779 lines) and `data_service.py` (1,764 lines)** were **not
   audited** — outside the declared scope. They build the export that consumes these numbers.
7. **`analytics_engine.py:2,923–3,459`** was **scanned, not read line by line** (QM-07 header).
   The scan covered every arithmetic token that could produce a published statistic and found
   only shape/count operations. I am stating this as a *scanned* range, not an *unread* one,
   because that is what the evidence supports.
