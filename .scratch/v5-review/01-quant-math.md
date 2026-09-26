# QM — Quantitative / Mathematical Accuracy Review
**Artifact:** `C:\es\others things\finengine-portfolio-ai-context v5.json`
`export_id portfolio-4b78905b588c` · `schema_version 2.0` · `generated_at 2026-09-26T15:33:25Z` · `base_currency INR` · `detail=summary` · 17 sections · 14 holdings
**Sections owned:** `tear_sheet`, `realized_risk`, `forecast_risk`, `stress_testing`, `monte_carlo`, `risk_studio`, `volatility_sizing`
**Reviewer stance:** re-derive everything from raw inputs; a label is not evidence.

---

## VERDICT

**The arithmetic is CORRECT.** Not "approximately correct" — *bit-level* correct. I rebuilt the price frame from `backend/data/daisy.db` (`stock_timeseries.adj_close`), reproduced the exact portfolio-return construction (`holdings.py:217 holding_window` → `pct_change(fill_method=None)` → `allocations.aggregate_active_returns`), and re-ran every metric. **`tear_sheet`'s eleven metrics reproduce to |Δ| < 5e-7. `realized_risk`'s portfolio *and* all 14 per-position metrics reproduce to |Δ| < 1e-12. `risk_studio.risk_contribution`'s 14 Euler risk contributions reproduce to |Δ| = 0.000000. `monte_carlo` reproduces from `seed=42` (`prob_success` 0.3720 vs 0.3715, `chunk_size_paths` 793 exact, all 5 terminal percentiles and all 11 fan points within 2%). `forecast_risk`'s GARCH(1,1) refit in `arch` gives 0.13767283 against a published 0.13767283 (Δ = 6e-10). `volatility_sizing`'s 14 EWMA volatilities reproduce to |Δ| = 0.0, `w_i = scale·(1/σ_i)/Σ(1/σ_j)` is exact, and all 14 `shares_delta` are exact half-up. `stress_testing` reconciles to 1e-5 across 4 scenarios × 14 legs. There is no fabricated number in these seven sections.** I found no P0 arithmetic error, and I want to be explicit about that because the headline numbers look absurd — they are absurd, but they are not *miscomputed*.

**The statistical interpretation is NOT DEFENSIBLE as published.** The failure mode is not arithmetic; it is that 39 observations are extrapolated to a full year and published to six decimals with `annualized: true`, no standard error, no confidence interval, and no per-metric sample size. Worse, the 39 observations are **not the portfolio**: 20 of the 39 days are partial baskets (weight-renormalized over whichever legs had a bar), and the **final observation — the one that sets the terminal total return, the CAGR, the Sharpe and the Sortino — is a single stock, `ELECTCAST.NS`, alone, with a 30.14× weight renormalization**. A Sharpe of 3.49 has a 95% CI of [−1.36, 8.74]; the daily mean has a two-sided p-value of 0.155; the 43% CAGR has a 95% CI of [−13%, +138%]. A 36-day "beta vs NIFTY" of 0.6743 is published with a 74.23% *annualized* alpha whose beta CI is [0.26, 1.09]. Three separate findings below (QM-1, QM-2, QM-3, QM-5) are money-affecting labelling/aggregation defects, and QM-4 shows the export's own two sections publishing portfolio volatilities 36% apart with no reconciliation note.

**Where the export is genuinely excellent** (and I say so plainly): disclosure of proxies. `stress_testing` labels its own drawdown as `derived_from_shock_proxy` with the formula, labels `recovery_time` as `configured_recovery_estimate_not_simulated` and `confidence_level` as `nominal_label_not_simulated`, and publishes the full shock input tree. `risk_studio.tail_dependence` publishes the raw GPD shape, the constrained shape, the shape *used*, the basis, and the reason for the constraint. `realized_risk` refuses NIFTYIETF.NS with `null` + `annualized: false` + a prose warning rather than defaulting. `volatility_sizing` flags `MCX.NS` as `below_minimum_notional` with a reason instead of rounding to a fractional share. That discipline is real and it is why this review found 0 fabricated numbers. The gap is that the *headline* `tear_sheet` block does not apply the same discipline to the numbers a reader will actually act on.

### How this was verified
The DB cache is the exact source of the export (weights match `market_value/total` to 1e-16; the rebuilt 39-day series reproduces the published `underwater` series to 4.8e-7 = the export's own 6-dp rounding). All figures below come from re-running the code path, not from reading labels. Scripts: `%TEMP%\opencode\recon2..14.py`, run via `uv run python` in `backend`.

---

## FINDINGS (ranked by severity)

### QM-1 — P0 — The 39-observation series is not the portfolio; the last day is one stock
**JSON path:** `sections.tear_sheet.data.metrics.*` (all 11), `sections.realized_risk.data.portfolio.*`
**Observed:** `observation_count: 39`, `annualized: true`, `total_return 0.056879`, `cagr 0.429686`, `sharpe 3.487604`, `sortino 5.314715`, `calmar 20.189083`, `volatility 0.098238`, `max_drawdown -0.021283`. `underwater[38].date = 2026-09-25`.

**Expected:** a portfolio return series in which each day is a weighted average of the 14 holdings. Recomputation of the active-weight coverage day by day:

```
date        legs  active_weight  renorm   missing
2026-08-04   13     0.975907      1.0247  [NIFTYIETF.NS]
   ... (all 15 days to 08-24 identical) ...
2026-08-25   14     1.000000      1.0000  []
   ... (14 clean days to 09-11) ...
2026-09-14   12     0.874347      1.1437  [NIFTYIETF.NS, MIDCAPIETF.NS]
2026-09-15   12     0.874347      1.1437  [NIFTYIETF.NS, MIDCAPIETF.NS]
   ...
2026-09-23   11     0.804696      1.2427  [JUNIORBEES, MAFANG, SELECTIPO]
2026-09-24    7     0.561575      1.7807  [MOTILALOFS, ARROWGREEN, JKIL, NIFTYIETF, JUNIORBEES, MAFANG, SELECTIPO]
2026-09-25    1     0.033177     30.1415  [all but ELECTCAST.NS]

days where active weight < 1: 20 of 39
max renormalisation uplift on a single day: 2914.15%
last-day basket = ['ELECTCAST.NS'] -> return -0.01199001
```

The final return of the series is `ELECTCAST.NS`'s one-day return, relabelled as 100% of the portfolio. Every annualized ratio in `tear_sheet.metrics` and every number in `realized_risk.portfolio` is computed on that series.

The magnitudes are not robust to this. Restricting to the 19 days where **all 14** legs have a bar:

| metric | published (39 mixed-basket days) | complete-case (19 days) |
|---|---|---|
| total_return | 0.056879 | 0.038450 |
| cagr | 0.429686 | 0.649388 |
| sharpe (rf .02) | 3.487604 | 6.468492 |
| sortino | 5.314715 | 13.126589 |
| calmar | 20.189083 | 88.812369 |
| volatility | 0.098238 | 0.074784 |

Either series supports "high Sharpe"; neither is the portfolio's Sharpe, and the export publishes no indication that the composition changes day to day. `measured_window.covered_days_scope = "holding_window_aligned_return_rows"` describes *which rows*, not *which basket*.

**Root cause:** `backend/app/utils/allocations.py` `aggregate_active_returns` (called at `analytics.py:5252` and `analytics_engine.py:1335`) renormalises the surviving positive weights per date and returns the result as `portfolio_returns` with no record of which legs were dropped:
```python
active_weight = active.mul(weight_frame, axis=1).sum(axis=1)
numerator = clean.where(active, 0.0).mul(weight_frame, axis=1).sum(axis=1)
portfolio = numerator.loc[active_weight > 0.0] / active_weight.loc[active_weight > 0.0]
```
**Confidence:** high — reproduced exactly, twice, with two independent scripts.

---

### QM-2 — P0 — `relative_vs_nifty` silently mixes a 244-day benchmark with a 39-day portfolio
**JSON path:** `sections.tear_sheet.data.relative_vs_nifty.*`
**Observed:**
```json
{"beta_vs_nifty": 0.6743, "alpha_annualized": 0.7423, "benchmark_sharpe": -0.636734,
 "benchmark_volatility": 0.132634, "benchmark_max_drawdown": -0.151818,
 "benchmark_total_return": -0.068626, "overlap_days": 36}
```
**Expected:** all four `benchmark_*` fields on the same window as the `metrics` block they sit beside (the 39-day measured window), or the window labelled per field.

Recomputed against `^NSEI` in the same cache:

| field | 244-day requested window | 36-day holding window | published |
|---|---|---|---|
| `benchmark_total_return` | **−0.068626** | −0.064244 | −0.068626 |
| `benchmark_volatility` | **0.132634** | 0.068640 | 0.132634 |
| `benchmark_max_drawdown` | **−0.151818** | −0.066831 | −0.151818 |
| `benchmark_sharpe` | **−0.636734** | −7.020455 | −0.636734 |

Exact match to the **244-day** window on all four. The block therefore invites the reader to compute "portfolio Sharpe +3.49 vs benchmark Sharpe −0.64" — a 4.1-point skill gap. The like-for-like comparison is +3.49 vs **−7.02**, a 10.5-point gap. Neither is the truth; the panel is uninterpretable as published, and `overlap_days: 36` refers only to beta/alpha, not to the four `benchmark_*` fields beside it.

Separately: `alpha_annualized = 0.742305` is `(mean_p − β·mean_b)·252` on 36 overlapping days. β 95% CI ≈ [0.26, 1.09]. The code comment at `analytics.py:5472-5473` states the intent — *"Beta/alpha genuinely need joint history: gate on the common window so a handful of overlapping days never annualizes noise"* — and the gate at line 5475 is `if len(common) >= MIN_ANNUALIZE_DAYS` = **30**. Thirty-six passes. The gate admits exactly the failure it was written to prevent.

**Root cause:** `backend/app/api/analytics.py:5459-5471`
```python
bench_window = bench_ret
try:
    bench_window = bench_ret[bench_ret.index >= start]   # start = the 365-day REQUEST start
...
relative = {..., "benchmark_sharpe": _q(qs.stats.sharpe, bench_window, rf=0.02), ...}
```
and `analytics.py:5475` `if len(common) >= MIN_ANNUALIZE_DAYS:` (30, from `utils/holdings.py:35`).
**Confidence:** high.

---

### QM-3 — P0 — `forecast_risk.confidence_interval` is a hardcoded ±20% band, not a confidence interval
**JSON path:** `sections.forecast_risk.data.portfolio.confidence_interval`
**Observed:** `[0.11013826613761486, 0.16520739920642227]`
**Expected:** either a real interval with a declared level and a sampling error, or no such field.

```
volatility_forecast            = 0.13767283267201857
vol * 0.8                      = 0.11013826613761486   <-- published lower bound, EXACT
vol * 1.2                      = 0.16520739920642227   <-- published upper bound, EXACT
```
The field is `[0.8σ, 1.2σ]` to the last bit. It is a fixed ±20% haircut on the point forecast, carrying **no confidence level, no degrees of freedom, no sampling error, and no distributional assumption**. A reader — human or LLM — will read "confidence interval" as a statement about estimator uncertainty and will conclude the forecast is tight and well-identified. Nothing in the section says otherwise; `methodology` is the single string `"Volatility forecasting using GARCH model with 1-day horizon"`.

**Root cause:** `backend/app/services/analytics_engine.py:1577-1580`
```python
"confidence_interval": [
    max(0.0, float(vol_final * 0.8)),
    float(vol_final * 1.2)
],
```
(The same construct is duplicated at lines 1649-1652 for EGARCH and 1696-1699 for EWMA.)
**Confidence:** high — the identity is exact to 1e-17.

---

### QM-4 — P0 — `volatility_sizing` publishes a target-vol that the data does not deliver, and contradicts `realized_risk`
**JSON path:** `sections.volatility_sizing.data.achieved_volatility`, `.current_volatility`, `.scale_factor`
**Observed:** `achieved_volatility: 0.15`, `current_volatility: 0.145465131056991`, `scale_factor: 1.295309`, `target_volatility: 0.15`
**Expected:** `achieved_volatility` to be the volatility of the recommended book under a stated, published covariance convention — and that convention to reconcile with the other sections.

Two defects, both verified:

**(a) `achieved_volatility` is a tautology.** `analytics_engine.py:1034` sets `scale = target_volatility / rec_vol_ann`; `analytics_engine.py:1053` sets `achieved_vol = rec_vol_ann * scale`. Algebraically `achieved_vol ≡ target_volatility` for every possible input. Recomputed: `rec_vol_ann = 0.1158024919`, `scale = 0.15/0.1158024919 = 1.295309` (matches published exactly), `achieved_vol = 0.1500000000`. It is the target restated; it carries zero information and reads as a verification.

**(b) The covariance is synthetic and the target is not met on the data's own covariance.** `analytics_engine.py:1022-1027` builds `Σ = corr(returns) ⊙ outer(EWMA daily vols)` — a plain 174-day Pearson correlation combined with recency-weighted (last-60-day, λ=0.94) marginal vols. Under the *sample* covariance of the same returns:

| quantity | published (corr × EWMA) | sample covariance of the same book |
|---|---|---|
| current book vol | 0.145465 | **0.199850** (+37.4%) |
| recommended book vol × scale | 0.150000 (`achieved_volatility`) | **0.224888** (+49.9%) |

So the recommended book, which the section authorises with a **30.14% borrowed notional (INR 12,878.08)**, has a 174-day realized volatility of ~22.5%, not the 15% the section claims it achieves. The understatement comes from pairing recency-weighted vols with an equal-weighted correlation. No covariance convention is published anywhere in the section, so `current_volatility` and `achieved_volatility` cannot be derived from any published input.

**(c) Cross-section contradiction.** `sections.realized_risk.data.instrument_risk.portfolio.annual_volatility = 0.197796` vs `sections.volatility_sizing.data.current_volatility = 0.145465` — the **same book, essentially the same window (175 vs 174 days)**, a 36% disagreement, with no reconciliation note anywhere in the export. A third number, `sections.risk_studio…risk_contribution.portfolio_volatility_annualized = 0.178900`, sits between them (that one *is* the sample-covariance value and I verified it: σ_p = 0.178878, Δ = 2.2e-5). So three sections, three portfolio volatilities, one of which is arithmetically fabricated by construction.

**Root cause:** `analytics_engine.py:977-985` (current) and `1022-1034` + `1053` (recommended/achieved) — `current_corr = returns[current_tickers].corr(); current_cov = current_corr_values * np.outer(current_vol_values, current_vol_values)`.
**Confidence:** high.

---

### QM-5 — P0 — Annualization gate of 30 observations; 39 observations published to 6 dp as a full year
**JSON path:** `sections.tear_sheet.data.annualized`, `.observation_count`, `.metrics.*`; `sections.realized_risk.data.portfolio.annualized`
**Observed:** `annualized: true`, `observation_count: 39`, `cagr 0.429686`, `sharpe 3.487604`, `sortino 5.314715`, `calmar 20.189083`. No standard error, no confidence interval, no per-metric sample size, no `annualization_factor`, no `ddof` anywhere in the 876 KB file.

**The arithmetic is right.** Given 39 observations, the 252 factor, `ddof=1`, `rf=0.02` and quantstats 0.0.81, every number is exact:

```
n=39, mean=0.0014381633, std(ddof=1)=0.0061883851, std(ddof=0)=0.0061085316
cagr      = (1+0.056879)^(252/39)-1                     = 0.429686   ✓ published
sharpe    = (mean - (1.02^(1/252)-1))/std(ddof=1)*sqrt252 = 3.487604 ✓ published
vol       = std(ddof=1)*sqrt252                          = 0.098238  ✓ published
maxDD     = min over the equity curve (phantom 1.0 base)  = -0.021283 ✓ published
sortino   = mean_excess / sqrt(sum(r<0)^2/n) * sqrt252    = 5.314715 ✓ published
omega     = sum(r>0)/-sum(r<0), threshold 0              = 1.916946 ✓ published
tail_ratio= |q95/q05|                                    = 1.172416 ✓ published
skew/kurt = pandas .skew()/.kurtosis() (excess)          = -0.743865 / 2.622096 ✓
```
**Unannualized (per-period) values, for the reader who wants them:** Sharpe 0.219572, Sortino 0.337157, period total return 0.056879, period excess return 0.053784. At 365 periods instead of 252: CAGR 0.678234, Sharpe 4.270779. At `ddof=0`: Sharpe 3.531168. The export declares none of these choices.

**The policy is indefensible.** The full-sample return series, sorted, is 14 negative days out of 39 (35.9%), worst −1.8773% (2026-09-15), and the 5.6879% total return is a 39-day streak:

```
per-period Sharpe 0.232397 -> annualized 3.689191 (rf=0) / 3.487604 (rf=0.02)
Lo (2002) SE(annualized Sharpe) = sqrt((1+S^2/2)/n)*sqrt(252) = 2.576049
  -> 95% CI on the annualized Sharpe = [-1.36, 8.74]
t-test on the daily mean: t = 1.4513, df = 38, two-sided p = 0.1549
  one-sided p(H0: mean <= 0) = 0.0774
95% CI on the daily mean = [-0.000568, +0.003444]  -> annualized [-14.31%, +86.79%]  (contains 0)
95% CI on the CAGR implied by that mean-CI = [-13.34%, +137.84%]   (published: 42.97%)
P(39-day mean >= observed | sigma_ann = 9.82%) = 0.0733
n required for a 95% CI half-width of 0.5 on the annualized Sharpe = 3,977 obs (15.0 years)
lag-1 autocorrelation 0.0398 -> effective n = 36.0 (no autocorrelation excuse)
```
**The mean daily return is not statistically distinguishable from zero at the 5% level.** A Sharpe whose numerator has p = 0.155 is published as 3.49 with six significant figures and `annualized: true`. The gate that let it through is `MIN_ANNUALIZE_DAYS = 30` (`utils/holdings.py:35`), applied via `annualizable()` at `holdings.py:250-252` and `apply_annualization_gate` at `holdings.py:356`. Thirty observations is **one trading month**; the standard requirement for a stable annual Sharpe is 2–3 years of daily returns.

**What a reader is misled by:** they will conclude this book has a persistent 3.5-Sharpe skill and a 43% growth rate, and will size positions, allocate risk, or buy a "quant" product on that basis. The 95% CI admits a Sharpe of −1.36 and a CAGR of −13%. The correct statement, which the export could make and does not, is: *"over 39 trading days the book returned +5.69% with a 9.82% annualized volatility; the annualized figures are extrapolations from 15% of a year and carry a 95% CI on Sharpe of roughly [−1.4, +8.7]."*

**Root cause:** `utils/holdings.py:35` `MIN_ANNUALIZE_DAYS = 30`; consumed at `analytics.py:5401-5403` and `5536`, `analytics_engine.py:292`. The gate is a *coverage* gate being used as a *reliability* gate — those are not the same question.
**Confidence:** high.

---

### QM-6 — P1 — Calmar mixes annualization conventions; its denominator is a one-day dip
**JSON path:** `sections.tear_sheet.data.metrics.calmar`
**Observed:** `20.189083`
**Expected:** numerator and denominator on the same annualization basis.

```
cagr = 0.429686   (252/39 geometric extrapolation of a 39-day return)
|mdd| = 0.021283  (RAW 39-day peak-to-trough, NOT annualized)
0.429686 / 0.021283 = 20.189097  -> published 20.189083  (cagr/|mdd| confirmed)
consistent annualization of BOTH legs:
   |mdd| * sqrt(252/39) = 0.054099  ->  calmar = 7.942348
```
The 2.5× gap is the entire finding. Worse, the denominator is not a drawdown in any meaningful sense:

```
peak  2026-09-08  equity 1.058524
trough 2026-09-15 drawdown -0.021283  entered by a SINGLE -1.8773% day
recovery 2026-09-18  (3 trading days / 7 calendar days later)
equity at end 1.056879, terminal drawdown -0.013475 -> a NEW drawdown, unrecovered
underwater fraction of the sample: 51.3% ; 7 distinct drawdown episodes
```
A "Calmar ratio of 20.19" here means "a 43% extrapolated CAGR divided by the worst single day in seven weeks." No Calmar published on a 39-day sample is interpretable, and this one is published to six decimals with no caveat.

**Root cause:** `analytics.py:5393` `"calmar": _q(qs.stats.calmar, port_ret)` — quantstats 0.0.81 `calmar` = `cagr(returns, periods=252) / abs(max_drawdown(returns))`, i.e. it annualizes the numerator and not the denominator. That is quantstats' behaviour, faithfully reproduced; the defect is that the export applies a 252-period metric to a 39-observation sample without adjusting the policy.
**Confidence:** high.

---

### QM-7 — P1 — Risk-free rate 0.02 is used, is never published, and is computed two different ways
**JSON path:** `sections.tear_sheet.data.metrics.sharpe` / `.sortino`; `sections.realized_risk.data.portfolio.sharpe_ratio` / `.sortino_ratio`
**Observed:** `sharpe: 3.487604` (tear_sheet) and `sharpe_ratio: 3.4856030104352476` (realized_risk) — two different published Sharpe ratios for the same portfolio, same 39 observations, same 9.82% volatility.
**Expected:** one number, with the risk-free rate and its convention published.

```
implied rf from realized_risk.sharpe_ratio: 0.02000000  (exact)
tear_sheet  : rf enters as (1.02)^(1/252)-1 = 7.72469e-05  (geometric, quantstats _prepare_returns)
engine      : rf enters as 0.02/252        = 7.93651e-05  (simple, analytics_engine.py:1362)
=> 3.487604 vs 3.485603, a 0.06% disagreement between two sections
```
`risk_free_rate` is `settings.risk_free_rate` (`analytics_engine.py:199`, default 0.02) and `rf=0.02` is hardcoded at `analytics.py:5391-5392` and `5417-5418`. Searching the whole 876 KB export: `risk_free` appears **once**, and only inside the `optimization` section (not mine). Neither `tear_sheet` nor `realized_risk` publishes it. A reader cannot tell that a 2% risk-free rate was assumed, let alone which daily convention.

**Also in the same family:** `realized_risk.portfolio.annual_return = 0.3624171632` (arithmetic mean × 252) sits in the same export as `tear_sheet.metrics.cagr = 0.429686` (geometric, 252/39) for the identical sample — a 19% divergence between two "annual return" numbers with no note. Both are defensible; publishing both without distinguishing them is not.

**Root cause:** `analytics.py:5391-5392` (`rf=0.02` into quantstats) vs `analytics_engine.py:1357,1362` (`self.risk_free_rate`, default from settings, simple daily division); neither is emitted into the response.
**Confidence:** high.

---

### QM-8 — P1 — GARCH VaR/CVaR are hardcoded Gaussian multiples; level, units, sign convention and convergence all undeclared
**JSON path:** `sections.forecast_risk.data.portfolio.var_forecast`, `.cvar_forecast`, `.model_params`
**Observed:** `var_forecast: -0.014266383036982124`, `cvar_forecast: -0.01786550094600801`, `model_params: {p:1, q:1, type:"GARCH", forecast_method:"analytic"}`, `observations: 174`
**Expected:** a declared confidence level, units, sign convention, fitted GPD/distribution parameters, and a convergence flag.

```
sigma_1d = 0.13767283267201857 / sqrt(252) = 0.0086725733
var_forecast  / -sigma_1d = 1.64500000   <- hardcoded, analytics_engine.py:1567
cvar_forecast / -sigma_1d = 2.06000000   <- hardcoded, analytics_engine.py:1568
exact normal ES factor at 95% = phi(1.6449)/0.05 = 2.062700  (the hardcode is 0.13% off)
cvar/var = 1.252280  -> CONSTANT for every possible input
```
**`cvar_forecast` is `var_forecast` × 1.25228 by construction.** It is not a computed expected shortfall; it cannot be, for any input. Consequences:
- **Confidence level undeclared.** 1.645 and 2.06 are nominal 95% one-sided Gaussian factors, but nothing in the section says 95%. Compare `risk_studio.tail_dependence`, which *does* publish `confidence_level: 0.99` and a `pot_threshold_basis` block. Here there is no level, no units key, and no sign convention (the values are negative = loss, but the field name does not say so).
- **No distributional content.** The fit is `dist='normal'` (`analytics_engine.py:1546`). The sample's own excess kurtosis is 2.62 (raw 5.62). The parametric tail is Gaussian while the historical tail is not — precisely the case where a parametric VaR understates.
- **No convergence disclosure.** I refit: `arch` gives `omega=0.036179, alpha1=0.104634, beta1=0.862109, convergence_flag=0` and 1-day annualized σ = 0.13767283 (Δ = 5.95e-10 vs published — the fit reproduces perfectly). **None of ω, α, β, α+β = 0.9667, or the convergence flag is in the export.** The GARCH is therefore unverifiable from the artifact; I could only check it by refitting from the cache.
- **Silent data modification.** `analytics_engine.py:1540` `clean_returns.clip(lower=-0.20, upper=0.20)` — returns are winsorized at ±20% before fitting, undisclosed. No return in this sample hits the bound, so the effect here is nil, but the transformation is invisible.
- **Undisclosed clamps.** `vol_final = np.clip(raw_vol_final, 0.05, 1.20)` (line 1565) and `var_forecast = np.clip(..., -0.99, -0.001)` (line 1567). The `raw_volatility_forecast` that would reveal the clamp is computed and then dropped by the route. The −0.001 floor means a VaR can never be reported below 0.1% — a silent floor.
- Monotonicity **is** satisfied: |CVaR| 1.7866% ≥ |VaR| 1.4266%. And the sign is correct (a loss at 95%, not a gain) — the specific bug the brief asked about is not present.

**Root cause:** `analytics_engine.py:1567-1568` (`-return_space_vol * 1.645`, `-return_space_vol * 2.06`), `1540` (clip), `1546` (dist='normal'), `1548` (`maxiter=100`, result discarded), `1565` (vol clamp).
**Confidence:** high.

---

### QM-9 — P1 — Stress `max_drawdown` is a number × 1.15, and the "sector elasticity table" is neither static nor calibrated
**JSON path:** `sections.stress_testing.data.scenarios.*.max_drawdown`, `.shock_inputs.sector_elasticity_basis`, `.shock_inputs.volatility_adjustment.basis`
**Observed:** `Market Crash.max_drawdown: -0.5453`; `sector_elasticity_basis: "static_configured_table"`; `volatility_adjustment.basis: "measured_annualized_volatility_over_reference"`
**Expected:** a `max_drawdown` that is a drawdown; a basis label that is true.

**(a) `max_drawdown = portfolio_impact × 1.15`.** Verified on all four scenarios: −0.4742 × 1.15 = −0.5453, −0.1942 × 1.15 = −0.2233, −0.2877 × 1.15 = −0.3309, −0.1349 × 1.15 = −0.1551. `STRESS_DRAWDOWN_UPLIFT = 1.15` (`analytics_engine.py:148`), applied at line 786. The 15% uplift has no basis — it is not a recovery path, not a vol-of-drawdown adjustment, nothing. It IS disclosed (`max_drawdown_basis: "derived_from_shock_proxy"`, `max_drawdown_formula: "portfolio_impact * 1.15"`), which is why this is P1 and not P0. But a reader scanning for "what is my worst case" reads −54.53% and has no reason to know 15% of it is a constant.

**(b) `sector_elasticity_basis: "static_configured_table"` is false.** The table is a per-scenario parameter block (`analytics_engine.py:615-655`) — 7 sectors × 4 scenarios = **28 free numbers** with no published calibration:

| sector | Market Crash (−0.35) | Rate Shock (−0.15) | Vol Spike (−0.22) | Tech Correction (−0.18) |
|---|---|---|---|---|
| Healthcare | 0.55 | 0.50 | 0.40 | 0.25 |
| Utilities | 0.50 | 0.70 | 0.55 | **0.20** |
| Technology | 1.10 | 1.10 | 0.95 | 1.80 |
| Financial Services | 1.45 | 1.50 | 1.30 | **0.50** |
| Consumer Cyclical | 1.55 | 1.35 | 1.50 | 0.60 |
| Industrials | 1.40 | 1.40 | 1.45 | 0.45 |
| Exchange Traded Fund | 1.00 | 1.00 | 1.05 | 0.60 |

The same sector gets a 2.5× different elasticity (Utilities 0.50 → 0.20) in two scenarios of the same direction. "Static" is the wrong word and the label is the only place a reader would look for justification. Separately, `analytics_engine.py:739-741` hardcodes a bespoke override:
```python
if ticker == "MAFANG.NS" and sc_name == "tech_sector_correction":
    sec_mult = 2.0
    elasticity_basis = "instrument_override_mafang_tech_correction"
```
MAFANG.NS is a broad Midcap/Smallcap ETF (its sector is recorded as `Exchange Treted Fund` / default), and this line assigns it a 2.0 elasticity in one scenario only, producing `position_impacts.MAFANG.NS = -0.45` on a −0.18 market shock — a 2.5× beta, from a hand-plugged constant. The `basis` string is published, so the plug is visible; the number is still doing real work in `portfolio_impact`.

**(c) `volatility_adjustment.basis: "measured_…"`, but 12 of 14 legs are at a clamp.** `vol_adj = clip(σ_i/0.22, 0.85, 1.25)` (`analytics_engine.py:764-767`) means any σ > 27.5% gets exactly 1.25 and any σ < 18.7% gets exactly 0.85. Counted: **8 legs at the 1.25 ceiling, 4 at the 0.85 floor, 2 genuinely interior.** For 86% of the book the "measured" factor is a constant.

**(d) The stress-test volatilities are a *third* portfolio-specific volatility set, distinct from `volatility_sizing`'s EWMA.** `analytics_engine.py:761-763` uses a plain sample std of non-zero clipped returns × √252. CIPLA's factor 1.0058 implies σ = 0.2213; `volatility_sizing.volatilities.CIPLA.NS` publishes 0.1455. Same ticker, same export, 52% apart, no cross-reference.

**What *is* clean here:** shocks are applied multiplicatively and consistently (`impact = shock × elasticity × vol_factor`, clipped to [−0.75, −0.02]); `portfolio_impact = Σ w_i·impact_i` reconciles to 1e-5 on all four scenarios; weights sum to 1.000000 and the post-shock book re-normalises to 1.0000000000; units and sign conventions are published in a `units` block; `recovery_time` and `confidence_level` are honestly labelled as configured labels. I back-solved all 14 implied elasticities per scenario and every one resolves to a published table value or a named override. **The only gap is that the per-leg sector label is not published**, so `position_impacts` can only be derived by inversion, not forward-computation.
**Root cause:** `analytics_engine.py:148, 615-655, 739-741, 764-767, 786, 796`.
**Confidence:** high.

---

### QM-10 — P1 — `correlation_stability` calls a 2nd-percentile correlation "NORMAL"
**JSON path:** `sections.risk_studio.data.components.correlation_stability.data.*`
**Observed:** `current_avg_correlation: 0.1404`, `historical_median: 0.3408`, `historical_threshold_90th: 0.459`, `historical_threshold_75th: 0.4129`, `is_regime_break: false`, `alert_level: "NORMAL"`, `message: "Average pairwise correlation (0.140) is within normal historical bounds (median 0.341)."`
**Expected:** a two-sided stability verdict, or a percentile rank for the current value.

I rebuilt the 60-day rolling average of all 91 pairwise correlations over the 518-observation window and reproduced `current_avg_correlation = 0.1404` **exactly**, and the last 12 published series points to 4 dp:

```
current mine=0.1404  export=0.1404
p90     mine=0.4592  export=0.4590
p75     mine=0.4151  export=0.4129
median  mine=0.3490  export=0.3408
```
(small residual differences are the 471 vs 489 series length, a window artefact, not an error). But:
```
percentile rank of the current value in its own history: 2.3%
retained 60-point series: first 0.2731, last 0.1404  -> a 48.6% collapse
last 12 published points: 0.1286 0.1274 0.1179 0.1330 0.1328 0.1398 0.1391 0.1426 0.1431 0.1406 0.1404 0.1404
```
The regime test is **one-sided, upper only** (`correlation_service.py:100` `is_regime_break = bool(current_avg_corr >= threshold_90th)`; lines 102-119 branch CRITICAL / ELEVATED / NORMAL with no lower branch). Any value below p75 is "NORMAL". So a book whose average pairwise correlation has *halved* — a structural change in the diversification structure — is reported as `NORMAL`, in a message that quotes the median (0.341) next to the current value (0.140) as reassurance. The `percentile_rank` field exists in the sibling `volatility_cone` component and is **absent here**, so nothing tells the reader the value is a 2nd-percentile outlier. And `components.correlation_stability.data.series` is in the export's `omitted_fields` (only the last 60 of 489 points are retained), so the reader cannot see the decline's shape either.

**Root cause:** `backend/app/services/correlation_service.py:100-119`.
**Confidence:** high (current value reproduced exactly; the one-sided logic is read directly from source).

---

### QM-11 — P1 — `expected_shortfall_vs_target` is conditional; the unconditional number is 38.5% of the portfolio and is not published
**JSON path:** `sections.monte_carlo.data.expected_shortfall_vs_target`, `.prob_success`
**Observed:** `expected_shortfall_vs_target: -26732.4`, `prob_success: 0.3715`
**Expected:** either a conditional label, or both figures.

`monte_carlo_service.py:379-383`:
```python
prob_success = float(np.mean(terminal >= target_value))
failing = terminal[terminal < target_value]
expected_shortfall = round(float(failing.mean() - target_value), 2) if len(failing) else 0.0
```
`expected_shortfall` is the mean shortfall **over failing paths only**. The unconditional expected loss against the INR 87,217.34 target is `0.6285 × 26,732.40 = INR 16,801`, i.e. **38.5% of the INR 43,608.67 starting value** — and it is not in the export. `success_definition_detail` carefully explains that `prob_success` is terminal rather than path-touching, but says nothing about the conditionality of the shortfall sitting directly beside it. A reader multiplying the two gets the honest number; a reader not multiplying gets a 61% understatement. The field name contains no "conditional".

The Monte Carlo itself is sound and reproduces from the published seed:
```
seed=42, num_paths=2000, method=student_t, chunk_size_paths=793 (exact), steps=1260
mu_annual   mine=0.127831  export=0.1297      (499 vs 500 obs in my rebuild)
sigma_annual mine=0.197396  export=0.1972
student_t df mine=4.536189  export=4.51
terminal p5/p25/p50/p75/p95  mine 37587.83 / 55353.82 / 74252.72 / 98917.16 / 155014.71
                            export 37374.15 / 56315.70 / 75279.57 / 100222.47 / 158099.82
prob_success  mine=0.3720  export=0.3715
expected_shortfall  mine=-27380.33  export=-26732.40
```
Seed, path count, chunk size, method, df, terminal parameters, the success definition, and the units are all published. Percentiles are monotone and the target sits at the 62.85th percentile of the published terminal grid, consistent with `prob_success = 0.3715`.
**Root cause:** `backend/app/services/monte_carlo_service.py:381-383` (no `*_conditional` in the field name; no unconditional companion emitted).
**Confidence:** high.

---

### QM-12 — P1 — 13 of 14 legs are flagged `status: "executable"` on a trade list the same section declares unexecutable
**JSON path:** `sections.volatility_sizing.data.trades.*.status` vs `.execution.execution_eligible`
**Observed:** 13 legs `"status": "executable"`; `execution.execution_eligible: false`, `execution.block_reasons: ["financing_required"]`, `execution.financing_requirement: 12878.08`, `methodology: "...not executable as a normal rebalance..."`
**Expected:** a consumer reading `trades` must not be able to emit 13 executable orders for a net purchase the section itself says is unfunded.

I reconciled the whole trade list to the paisa and it is internally perfect:
```
amount_i        = round((rec_w_i - cur_w_i) * 43608.66981063843, 2)      <- all 14 exact
shares_delta_i  = half_up_away_from_zero(amount_i / sizing_price_i)      <- all 14 exact
rounding_residual_i = amount_i - shares_delta_i * sizing_price_i         <- all 14 exact
sum(amount)     = 12878.08  ==  execution.financing_requirement  (delta -0.00)
```
The per-leg `status` is nonetheless `"executable"` on 13 legs (the 14th, MCX.NS, is correctly `"below_minimum_notional"` with a reason). The block-level refusal lives in a sibling key. A consumer that iterates `trades` and honours `status` produces a net buy of INR 12,878.08 that the section says cannot be funded. This is the exact inverse of the good behaviour elsewhere in the export (MCX's notional refusal is named and reasoned; the block-level refusal is not propagated down).
**Root cause:** `analytics_engine.py:1061-1071` (`build_trade_instructions` receives the per-leg deltas only; `execution` is computed separately at 1042-1048 and never fed back into the per-leg status).
**Confidence:** high.

---

### QM-13 — P1 — The aggregate trade-rounding residual (INR −1,553.52) is not published
**JSON path:** `sections.volatility_sizing.data.trade_reconciliation`
**Observed:** `max_abs_rounding_residual: 1109.62`, `max_abs_rounding_residual_ticker: "MCX.NS"`, `reconciled: true`, `aggregate_note: "Aggregates are recomputed from the delivered trades…"`
**Expected:** the book-level residual between the funded requirement and what the rounded share counts actually trade.

```
sum(trades.amount)            = 12878.08    <- equals financing_requirement
sum(shares_delta * price)     = 14431.60
sum(rounding_residual)        = -1553.52    <- NOT published anywhere
```
Because whole-share rounding is per-leg and unsigned, the aggregate does not cancel: the rounded book buys **INR 1,553.52 more** than the target deltas sum to, on a INR 43,608.67 portfolio (3.6%). The export publishes per-leg residuals with a per-leg tolerance rule and an explicit defence of why a single maximum does not certify a single maximum — good — but the one number that reconciles the *book* is absent, and `financing_requirement: 12878.08` is stated as if it were the cash the trade list requires. It is not; the trade list requires 14,431.60 of gross purchase against 12,878.08 of net financing.
**Root cause:** `backend/app/utils/allocations.py:563` `build_trade_instructions` — per-trade residuals and per-trade tolerances only; no book-level roll-up emitted.
**Confidence:** high.

---

### QM-14 — P1 — `tail_dependence_matrix` publishes a copula λ_L with no statement of what it is
**JSON path:** `sections.risk_studio.data.components.tail_dependence.data.tail_dependence_matrix`
**Observed:** a 14×14 symmetric matrix with unit diagonal, off-diagonals 0.0216–0.3784, published under `tickers` + `matrix`. The `tail_dependence` component has **no `methodology` key**.
**Expected:** a measure name and a basis string.

The values are bivariate Student-t copula lower-tail dependence coefficients λ_L = 2·t_{ν+1}(−√((ν+1)(1−ρ)/(1+ρ))), `tail_risk_service.py:272, 332-333` — **not** correlations, and the component name does not say so. A reader will read a 0.12 as "CIPLA and ELECTCAST correlate 12%". They do not:

| candidate identity | max abs difference vs the published matrix |
|---|---|
| plain Pearson correlation of 251-day returns | **0.4029** |
| Spearman rank correlation | 0.3293 |
| 5% co-exceedance probability | 0.8619 |

λ_L is a monotone transform of ρ, so the matrix is ρ-shaped and reads exactly like a correlation matrix while meaning something else. The docstring at `tail_risk_service.py:290-296` is honest that ν is "an approximation, not a joint copula fit", but that text never reaches the artifact.

The rest of `tail_dependence` is well built and I want to say so: `gpd_shape_xi: -0.7068` (raw MLE) vs `gpd_shape_xi_used: -0.5` (the clip that actually produced the reported risk), with `gpd_shape_xi_basis: "constrained_clip"`, `constraint_reason: "gpd_shape_clipped"`, `gpd_shape_xi_raw_equals_published_headline: true`, and the `pot_threshold_basis` block distinguishing the 95% fitting threshold from the 99% reported level. The `ξ ∈ [-0.5, 0.95]` clip is *conservative* (heavier tail than the −0.7068 fit), and `ES ≥ VaR` holds (`evt_pot_es` −0.041074 vs `evt_pot_var` −0.036708, ratio 1.119, not the hardcoded 1.25 of QM-8). My independent refit on the same window tracked it to ~3% (the only gap is 500 vs 518 observations in my rebuild of the cache). The remaining weakness is statistical, not arithmetic: a 2-parameter GPD MLE on **26 exceedances out of ~518** with `metrics_valid: true` and no standard error on ξ, β, VaR or ES. `gpd_shape_xi` (the headline) is also the parameter that was *not* used — a reader who takes it and computes moments gets the wrong answer (`evt_pot_var_unconstrained: -0.034584` vs the reported `-0.036708`).
**Root cause:** `backend/app/services/tail_risk_service.py:262-336` (measure), `:339+` (matrix), `:122` (`np.clip(xi_raw, -0.5, 0.95)`); the component emits no `methodology`.
**Confidence:** high.

---

### QM-15 — P1 — `full_history` is a 10-year series whose basket changes; its metrics sit unlabelled beside the holding-truthed ones
**JSON path:** `sections.tear_sheet.data.full_history.metrics.*`, `.relative_vs_nifty`
**Observed:** `total_return 6.092394` (+609%), `cagr 0.219672`, `sharpe 0.969056`, `max_drawdown -0.603319`, `observation_count 2486`, `beta_vs_nifty 0.9229`, `alpha_annualized 0.116`
**Expected:** the composition of the synthetic series to be visible where the metrics are.

The arithmetic is exact — I reproduced all seven metrics to |Δ| < 5e-7 from a frame starting 2016-09-09, and the −60.33% max drawdown trough (2020-03-23) and its recovery are correct. The problem is what the series *is*:

```
legs present by year:  2017-2019: 10/14   2020: 11/14   2022: 12/14   2024: 13/14   2025: 14/14
absent in 2017-2019: NIFTYIETF.NS, MIDCAPIETF.NS, MAFANG.NS, SELECTIPO.NS
rows where the ACTIVE weight is < 1: 2179 of 2485 (87.7%)
```
`aggregate_active_returns` renormalises, so the "10-year portfolio" is a 10-name book in 2017, 11-name in 2020, 14-name from 2025, continuously re-weighted to *today's* weights. The disclosure is present but structurally weak: `calculation_basis.full_history = "hypothetical_current_weights"`, `full_history.basis = "full_exchange_history_current_weights"`, `holding_context_note: "Holding context is ancillary: it never shortens, lengthens or annualizes this model window."` — all correct, all placed in *sibling* keys, while `full_history.metrics` carries the same field names as `tear_sheet.metrics`. And the export publishes `sharpe 3.487604` and `sharpe 0.969056` for the same book with no note reconciling a 3.6× discrepancy. `per_ticker_return_observations` (612 for NIFTYIETF, 380 for SELECTIPO) is the only place the composition shift is quantified, and it is per-ticker totals, not per-year.
**Root cause:** `analytics.py:5411-5426` (the second `_build_wide_returns` call omits `holdings=` by design) combined with `allocations.aggregate_active_returns`.
**Confidence:** high.

---

### QM-16 — P1 — The leg with the least data gets the largest size increase
**JSON path:** `sections.volatility_sizing.data.recommended_weights.NIFTYIETF.NS`, `.trades.NIFTYIETF.NS`, `.sizing_history`
**Observed:** `recommended_weights.NIFTYIETF.NS = 0.183595` (from `current_weights 0.024093`, a **7.62× increase**), `trades.NIFTYIETF.NS.shares_delta: 26`, `amount: 6955.65` (2nd-largest trade), `sizing_history.per_ticker_return_observations.NIFTYIETF.NS: 102` of 174, `min_return_observations: 102`, `minimum_observations_required: 30`, `meets_minimum_sample: true`
**Expected:** the sizing section to apply the same refusal discipline `realized_risk` applies to the same leg.

Inverse-volatility parity mechanically buys whatever has the lowest published volatility, and NIFTYIETF has the lowest (0.09354) because its return series is 41% empty (102 of 174 days). `realized_risk` handles this leg correctly — `annual_return/annual_volatility/sharpe_ratio` are `null`, `annualized: false`, `is_limited_history: true`, plus a prose `history_warning` and a section-level warning. `volatility_sizing` publishes a full weight and a full trade for the same leg, with the observation count present in the section but **not adjacent to the volatility**: `volatilities.NIFTYIETF.NS = 0.09353700069431281` carries no sample size, and `volatility_sources` says only `"EWMA"`. A consumer reading `volatilities` alone sizes a 18.4% position off 102 observations. Note also `sizing_price_as_of: 2026-09-22` is 3 calendar days behind the section's `latest_observation_date: 2026-09-25` (disclosed, with per-ticker gaps up to 3.47%).
**Root cause:** `analytics_engine.py:917-959` (per-leg vol with no per-leg sample-size publication) vs the `position_limited_history` gate at `utils/holdings.py:233-247` that `realized_risk` uses and this path does not.
**Confidence:** high.

---

### QM-17 — P2 — Tail statistics in `tear_sheet` / `realized_risk` are 2-observation estimates, published bare
**JSON path:** `sections.realized_risk.data.portfolio.var_95`, `.cvar_95`; `sections.tear_sheet.data.metrics.tail_ratio`, `.omega`
**Observed:** `var_95: -0.007779716667611284`, `cvar_95: -0.015381334680204901`, `tail_ratio: 1.172416`, `omega: 1.916946`
**Expected:** an indication that a 95% tail metric on 39 points is 2 points.

Both are **exactly right**:
```
np.percentile(port, 5)                  = -0.0077797166676112093  -> var_95  ✓ (Δ 7e-17)
count(port <= var_95) = 2  -> [-0.01877266, -0.01199001]
mean of that tail      = -0.0153813346802048 -> cvar_95 ✓ (Δ 1e-16)
```
`cvar_95` is the mean of **2 of 39** returns. `var_95` is a linearly interpolated 5th percentile that happens to fall between them. And the tail ratio's cutoff is undisclosed and load-bearing:

```
tail_ratio 95/5 (quantstats default cutoff=0.95) = 1.172416  -> published
tail_ratio 99/1                                  = 0.881529  -> the OPPOSITE sign
with n=39, the 95th percentile interpolates order stats 37 and 38; the 99th interpolates 38 and 39
```
The reported 1.17 ("right tail fatter than left") becomes 0.88 ("left tail fatter than right") under a stricter cutoff. The cutoff is a library default that never reaches the artifact, and it flips the qualitative conclusion. Similarly `omega`'s threshold is 0 (`required_return=0.0` default, `monte_carlo_service`/`quantstats`), undeclared, while `risk_studio.tail_dependence` publishes its threshold explicitly — the two sections do not agree on disclosure standards.
**Root cause:** `analytics_engine.py:1386-1394`; `analytics.py:5394-5395` (`qs.stats.omega`, `qs.stats.tail_ratio` with library defaults).
**Confidence:** high.

---

### QM-18 — P2 — No drawdown duration or recovery is published
**JSON path:** `sections.tear_sheet.data` (absent), `sections.realized_risk.data.portfolio` (absent)
**Observed:** no `*_duration`, `*_recovery`, `*_underwater_days` field anywhere in either section. `underwater` is a 39-point drawdown *series* with no duration summary.
**Expected:** peak date, trough date, recovery date, and time-under-water for the reported `max_drawdown`.

Derived from the published `underwater` series (which reproduces exactly):
```
peak    2026-09-08  equity 1.058524
trough  2026-09-15  drawdown -0.021283, entered by a single -1.8773% day
recovery 2026-09-18  (3 trading days, 7 calendar days)
terminal drawdown 2026-09-25 = -0.013475 -> a NEW drawdown, unrecovered at the export date
time under water: 20 of 39 rows (51.3%), in 7 distinct episodes
```
The reported `max_drawdown` recovers within three trading days and the book ends in a fresh, unrecovered drawdown. Both facts materially change how −2.13% should be read, and neither is derivable without reconstructing the series.
**Root cause:** absent feature; `analytics.py:5497-5503` builds the `underwater` series but no duration aggregation is computed or emitted.
**Confidence:** high.

---

### QM-19 — P2 — The `annualization_factor`, `ddof` and per-metric sample sizes are absent from the artifact
**JSON path:** `sections.tear_sheet.data` (absent), `sections.realized_risk.data` (absent), `sections.forecast_risk.data` (absent)
**Observed:** the strings `annualization_factor`, `periods` and `ddof` appear **0 times** in the 876 KB file. `observation_count` is a single section-level integer; no metric carries its own sample size.
**Expected:** `periods: 252`, `ddof: 1`, and per-metric `n` — or at minimum one `methodology` block naming them.

`methodology` is the string `"quantstats metric suite over cached OHLCV adj-close returns"` — it names the library, not the parameters. The annualization factor is 252, the ddof is 1, the downside deviation uses the full sample at a MAR of `0.02/252`, the omega threshold is 0, the tail-ratio cutoff is 95/5. **None of this is in the export.** Every one of those choices moves the answer (see QM-5's sensitivity table: Sharpe 3.4876 / 3.5312 / 3.6892 / 4.2708 across the plausible variants). I could only recover them by reading `quantstats/stats.py` and `analytics_engine.py`. `monte_carlo` publishes `annualization_basis: "trading_days_per_year_252"` and `annualized_fields`; `volatility_sizing` publishes `annualization_trading_days: 252` inside the stress block. The two most-read sections publish nothing. This is the finding that makes the other undeclared-input findings unverifiable *from the artifact alone*.
**Root cause:** `analytics.py:5527-5558` (tear_sheet response has no annualization block); `analytics_engine.py:254-262` (no per-metric counts).
**Confidence:** high.

---

### QM-20 — P2 — Monte Carlo percentiles carry no simulation error; `historical_mu_annual` is a different estimand from the fan
**JSON path:** `sections.monte_carlo.data.terminal_percentiles`, `.prob_success`, `.historical_mu_annual`
**Observed:** `prob_success: 0.3715`, `historical_mu_annual: 0.1297`, `historical_sigma_annual: 0.1972`, `num_paths: 2000`
**Expected:** a Monte Carlo standard error on `prob_success` and on each percentile.

```
binomial SE at n=2000, p=0.3715 = 0.0108  ->  95% interval ±0.0212 (34.9% .. 39.3%)
```
So the published "37.15% chance of doubling in 5 years" carries ±2.1pp of pure simulation noise, unstated. Each of the five percentiles is the ~100th order statistic of 2000 draws with a comparable unstated error. The terminal p5 of INR 37,374 — "a 5% chance of ending 14% below today in nominal rupees" — is a 5th-percentile estimate from 100 paths.

Separately, `historical_mu_annual: 0.1297` is `mean(r)·252`, the *arithmetic* annual mean, while the fan's central tendency is the *log* median:
```
mean(r)*252                 = 12.97%     <- published as historical_mu_annual
mean(log1p(r))*252          = 10.83%
median terminal 75279.57 / 43608.67 -> (.)^(1/5)-1 = 11.23% CAGR  <- the actual modelled median
```
A reader who takes 12.97% as "the expected return" and compounds it for 5 years gets 87,245 — essentially the target value 87,217.34 — and concludes `prob_success ≈ 50%`. The published answer is 37.15%. The 1.74pp gap between the arithmetic mean and the log median is the Jensen/compounding term, which is real, but the export puts the arithmetic figure next to the fan with no `estimand` label. Note this cuts the *other* way from the usual bias: the arithmetic mean overstates the modelled median here, and the Student-t's fat left tail (df 4.51) takes 13pp off the success probability.
**Root cause:** `monte_carlo_service.py:76` (`mu_annual = float(r.mean() * TRADING_DAYS)`), `:393, :420-426` (no SE emitted).
**Confidence:** high.

---

### QM-21 — P2 — Undisclosed simulation modification: t-innovations winsorized at ±8σ; df floored at 2.1
**JSON path:** `sections.monte_carlo.data.student_t_df`, `.terminal_percentiles`
**Observed:** `student_t_df: 4.51`, `method: "student_t"`, `disclaimer: "Probabilities are model estimates from historical data; not investment advice."`
**Expected:** disclosure of the tail truncation in a fat-tailed model.

`monte_carlo_service.py:156-162`:
```python
df_fit = float(max(df_, 2.1))                                  # variance undefined at df <= 2
innov = student_t.rvs(df_fit, ...)
z = np.clip((innov - loc_) / analytic_std, -8.0, 8.0)            # tail truncation
daily_sim = daily_returns.mean() + daily_returns.std(ddof=1) * z
daily_sim = np.clip(daily_sim, -0.95, None)                     # return floor
```
A Student-t with df = 4.51 has raw excess kurtosis 6/(ν−4) = 11.8 (raw kurtosis 14.8). Truncating the standardised innovation at ±8 removes exactly the draws that make the t interesting, and the export does not say so. I estimate ~20 of 2.52M draws are clipped in this run, so the effect here is small — but the mechanism is undisclosed, and it is precisely the parameter a tail-sensitive reader needs. The ±8σ clip and the df floor are in the docstring, not in the payload. The `disclaimer` covers "model estimates", not "the model's tails are truncated at 8σ".
**Root cause:** `monte_carlo_service.py:156-162`.
**Confidence:** high.

---

### QM-22 — P2 — Latent fabricated zeros in the engine (not triggered by this export)
**JSON path:** `sections.realized_risk.data.portfolio.sharpe_ratio` (would be `0.0`), `sections.monte_carlo.data.expected_shortfall_vs_target` (would be `0.0`)
**Observed:** not triggered here (39 ≥ 10 observations; 743 of 2000 paths fail).
**Expected:** `null` plus a reason, never `0.0`.

`analytics_engine.py:1345-1350`:
```python
if len(returns) < 10:
    annual_return = float(returns.sum())
    annual_volatility = float(returns.std() * np.sqrt(252)) if len(returns) > 1 else 0.0
    sharpe_ratio = 0.0
    sortino_ratio = 0.0
```
A portfolio with fewer than 10 return observations would publish `sharpe_ratio: 0.0` and `sortino_ratio: 0.0` — indistinguishable from a measured zero Sharpe, and materially different from "not computable". The same pattern at `monte_carlo_service.py:381-383` (`expected_shortfall = ... if len(failing) else 0.0`) publishes `0.0` when every path succeeds, which reads as "no shortfall risk" rather than "no shortfall observed". Both are P2 here because neither fires, but both are one short sample away from shipping a hard zero as a measurement. Contrast the correct handling two functions away (`analytics_engine.py:950-956`, which skips a leg with no finite volatility rather than substituting a floor) and `realized_risk`'s NIFTYIETF refusal.
**Root cause:** `analytics_engine.py:1349-1350`; `monte_carlo_service.py:381-383`.
**Confidence:** high.

---

### QM-23 — P2 — `stress_testing` has no valuation date while applying a measured volatility adjustment
**JSON path:** `sections.stress_testing.as_of`, `sections.stress_testing.as_of_semantics`
**Observed:** both `null`. Every other section in the export carries a date.
**Expected:** the date of the price window behind `volatility_adjustment.by_ticker`.

The section is the only one of the seven with `as_of: null`, yet it is the only one that consumes a *measured* annualized volatility per ticker (`basis: "measured_annualized_volatility_over_reference"`, 12 of 14 legs clamped, per QM-9c). Those volatilities are computed from a price window that is not identified anywhere in the section. The `units` block is otherwise exemplary.
**Root cause:** the `ai_context_service.py` collector for `stress_testing` does not populate `as_of` (compare the `volatility_sizing` / `monte_carlo` collectors, which do).
**Confidence:** medium — the omission is certain; the collector is the presumed site but I did not trace it line-by-line.

---

### QM-24 — P2 — `volatility_cone` percentiles are built from overlapping windows; `percentile_rank` has no inferential meaning
**JSON path:** `sections.risk_studio.data.components.volatility_cone.data.windows[*]`
**Observed:** five windows (10/21/63/126/252d) with `min/p25/median/p75/max`, `current_realized`, `percentile_rank`; `current_forecast: {model: "GARCH(1,1)", annualized_vol: 0.1519, horizon_days: 21, percentile_rank: 45, valuation: "normal"}`
**Expected:** either non-overlapping windows, or a statement that the bands are a path-dependency description rather than a sampling distribution.

Reproduced within ~2% on all five windows (e.g. 252d: mine min 0.1776 / p25 0.1818 / med 0.1841 / p75 0.1980 / max 0.2143 / cur 0.1779 / rank 1.6%; export 0.1776 / 0.1819 / 0.1858 / 0.1992 / 0.2143 / 0.1779 / rank 1.9%; the residual is the 471-vs-489 series length). The construction is sound. The issue is interpretive: the 252-day band comes from **249 overlapping** 252-day estimates, which are ~99.6% common with each other, so min and max span only 0.1776–0.2143 (a 1.21× range where a genuine sampling distribution would span 2–3×) and `percentile_rank: 1.9` means "near the bottom of a highly autocorrelated path", not "1.9% of independent observations". The `insufficient_data: false` flag on the 252d window with only 249 effective degrees of freedom is worth surfacing. The 63d and 252d windows both report a `percentile_rank` below 3 — the book is simultaneously at the 2.9th and 1.9th percentile of its own recent vol history — which is genuinely informative and honestly reported.
**Root cause:** `backend/app/services/volatility_service.py:196+` `calculate_volatility_cone` (rolling windows, `expanding`-style quantiles).
**Confidence:** high.

---

## WHAT IS CLEAN — stated plainly, no problems invented

- **`tear_sheet` arithmetic: exact.** All 11 metrics reproduce to |Δ| < 5e-7 from an independent rebuild of the 39-day return series. `ddof=1`; annualization √252; `rf = 1.02^(1/252) − 1 = 7.72469e-05` (geometric — correct, and better than the engine's simple division); Sortino's downside deviation is over the **full** sample at a MAR of `0.02/252` (the `sortino` docstring's own recommendation, correctly implemented — 3 tail statistics that misuse the downside-only denominator are avoided); Omega's threshold is 0; tail_ratio is 95/5; `max_drawdown` is on the equity curve with a phantom 1.0 baseline prepended, so the first-day loss is correctly counted (confirmed: `underwater[0].drawdown = -0.000178 = r_0` exactly); the trough date 2026-09-15 is the true minimum; `monthly_returns` compounds correctly as `(1+r).groupby([year,month]).prod()-1` ((1+0.050395)(1+0.006173)−1 = 0.056879 ✓).
- **`tear_sheet.full_history` arithmetic: exact.** All 7 metrics reproduce to |Δ| < 5e-7 on the 2,486-observation frame; the −60.33% COVID trough (2020-03-23) and its recovery are correct. The composition drift is real but disclosed.
- **`realized_risk`: exact, every field.** Portfolio and all 14 per-position metrics reproduce to |Δ| < 1e-12. `annual_return = mean·252`, `sharpe = (annual_return − 0.02)/annual_volatility` (implied rf recovers to 0.02000000), `sortino` uses `min(0, r − 0.02/252)` over the full sample (the Sortino & Price construction, correctly done), `hit_ratio = 0.6153846 = 24/39`, `max_drawdown` uses a baseline-aware implementation that agrees with quantstats to 2e-16, `var_95 = np.percentile(r, 5)`, `cvar_95` = mean of the ≤ VaR set. **And `NIFTYIETF.NS` is refused, not defaulted** — `null` ratios, `annualized: false`, `is_limited_history: true`, a prose `history_warning`, plus a section-level warning naming the 20 observations and stating the annualized ratios are withheld. This is the right behaviour and `tear_sheet` should copy it.
- **`risk_studio.risk_contribution`: exact.** All 14 Euler risk contributions reproduce to |Δ| = 0.000000 using `RC_i = w_i(Σw)_i / σ_p` on the pairwise-deletion covariance, and the implied `σ_p = 0.178878` matches the published `portfolio_volatility_annualized = 0.178900` to 2.2e-5. `portfolio_var_95_daily −0.018244` and `portfolio_cvar_95_daily −0.025175` both reproduce exactly. The `contribution_basis` block publishes the unit, the normalization, the rounding residual, and the leg count per model; `excluded_assets` is empty and honest; the shares sum to 0.999998 with the residual named. Best disclosure hygiene of the seven sections.
- **`risk_studio.correlation_stability`: exact.** `current_avg_correlation = 0.1404` and all 12 retained series points reproduce to 4 dp. Only the *interpretation* is one-sided (QM-10).
- **`risk_studio.volatility_cone`: exact** within ~2% (QM-24). `valuation: "normal"` is published — good.
- **`risk_studio.tail_dependence`: sound and the best-disclosed component in the export.** Raw vs constrained vs used GPD shape, the constraint reason, the 95%-threshold-vs-99%-reported distinction, the exceedance count (26/518 = 0.050193 ✓), `ES ≥ VaR` verified, and the clip is conservative. Only the matrix measure is unlabelled (QM-14).
- **`forecast_risk` GARCH: exact.** An independent `arch` GARCH(1,1) refit on the 174-observation portfolio series gives a 1-day annualized σ of 0.13767283 against a published 0.13767283 (Δ = 5.95e-10), `convergence_flag = 0`. `term_structure` has exactly 1 element for `horizon: 1` ✓. The VaR is negative (a loss) — the specific "positive VaR at 99%" bug is **not** present. All the defects are in labelling (QM-3, QM-8).
- **`monte_carlo`: exact and fully seeded.** `prob_success` 0.3720 vs 0.3715, `expected_shortfall` −27,380 vs −26,732, all 5 terminal percentiles and all 11 fan points within 2%, `chunk_size_paths` 793 exact, `student_t_df` 4.536 vs 4.51, `mu/sigma` within 0.15%. `seed`, `num_paths`, `method`, `horizon_years`, `initial_value`, `target_value`, `target_policy`, `annualization_basis`, `model_observations`, `model_window_start`, `model_as_of`, `success_definition` + `success_definition_detail` + `prob_success_units` are all published. `target_value` is exactly `2 × initial_value` ✓. Percentiles are monotone and `prob_success` is consistent with the target's position in the published terminal grid. This is the best-instrumented section in the export.
- **`volatility_sizing` sizing math: exact.** All 14 EWMA volatilities reproduce to |Δ| = 0.0 from the documented RiskMetrics recursion (seed `np.var`, then 60 single passes at λ=0.94, ×√252). `w_i = scale_factor · (1/σ_i) / Σ_j(1/σ_j)` reproduces every recommended weight to 3e-7 (the 6-dp publication rounding). All 14 `shares_delta` are exact `half_up_away_from_zero`; all 14 `rounding_residual` values are exact; `sum(amount) = 12878.08 = financing_requirement` to the paisa. `MCX.NS` is correctly refused as `below_minimum_notional` with a prose reason rather than rounded to a fractional share. The gross-exposure check works: `gross_exposure 1.29531 > 1.0` → `financing_required: true` → `execution_eligible: false` with a stated `block_reason` and an INR amount. **No leg is missing a volatility** — all 14 have `volatility_sources: "EWMA"`, so the "default a missing leg" failure mode is not present. (The two real defects are the target-vol tautology/mismatch in QM-4 and the per-leg `status` in QM-12.)
- **`stress_testing` reconciliation: exact.** All 4 scenarios × 14 legs: `impact = market_shock × sector_elasticity × vol_factor`, clipped to [−0.75, −0.02]. `portfolio_impact = Σ w_i·impact_i` reconciles to 1.2e-5 on all four. Weights sum to 1.000000; the post-shock book (multiplicative `w_i(1+impact_i)`, re-normalised) sums to 1.0000000000 with the largest weight moving 0.136798 → 0.166573 in the Market Crash. A `units` block declares every quantity's unit and sign convention. `methodology` states the full formula chain in plain English and names every input as configured rather than measured. This section is a model of disclosure; its problems are the *inputs* (QM-9), not the arithmetic.

---

## SUMMARY TABLE

| ID | Sev | Section | One-line finding | Confidence |
|---|---|---|---|---|
| QM-1 | **P0** | tear_sheet, realized_risk | 39-day series is a changing basket; the final day is 1 stock at 30.14× renormalization | high |
| QM-2 | **P0** | tear_sheet | `benchmark_*` on 244 days sits beside 39-day portfolio metrics; 36-day beta gate admits noise | high |
| QM-3 | **P0** | forecast_risk | `confidence_interval` is exactly `[0.8σ, 1.2σ]` — a hardcoded band | high |
| QM-4 | **P0** | volatility_sizing | `achieved_volatility` ≡ target (tautology); real vol of the target book is 22.5%; contradicts realized_risk by 36% | high |
| QM-5 | **P0** | tear_sheet, realized_risk | 30-obs annualization gate; Sharpe 95% CI [−1.36, 8.74], mean p = 0.155 | high |
| QM-6 | P1 | tear_sheet | Calmar annualizes the numerator only; denominator is a one-day dip (20.19 vs 7.94) | high |
| QM-7 | P1 | tear_sheet, realized_risk | rf = 0.02 never published, computed two ways → two Sharpes (3.4876 / 3.4856) | high |
| QM-8 | P1 | forecast_risk | VaR/CVaR are hardcoded 1.645σ / 2.06σ; CVaR ≡ 1.25228×VaR; no level/units/params/convergence | high |
| QM-9 | P1 | stress_testing | `max_drawdown` = impact × 1.15; "static" elasticity table is 28 per-scenario constants; 12/14 vol factors clamped | high |
| QM-10 | P1 | risk_studio | One-sided correlation regime test: 2.3rd-percentile value labelled `NORMAL` | high |
| QM-11 | P1 | monte_carlo | `expected_shortfall_vs_target` is conditional; unconditional is 38.5% of the book, unpublished | high |
| QM-12 | P1 | volatility_sizing | 13 legs `status: "executable"` on a section that declares itself unexecutable | high |
| QM-13 | P1 | volatility_sizing | Aggregate trade-rounding residual −INR 1,553.52 (3.6%) not published | high |
| QM-14 | P1 | risk_studio | `tail_dependence_matrix` is a copula λ_L, unlabelled, reads as a correlation matrix | high |
| QM-15 | P1 | tear_sheet | `full_history` basket changes 10→14 names; 87.7% of days partial; 3.6× Sharpe gap unremarked | high |
| QM-16 | P1 | volatility_sizing | Leg with 102/174 obs and the lowest vol gets the largest size increase (7.6×) | high |
| QM-17 | P2 | realized_risk, tear_sheet | `cvar_95` is a 2-of-39 mean; tail_ratio cutoff flips sign (1.17 vs 0.88) and is undeclared | high |
| QM-18 | P2 | tear_sheet | No drawdown duration/recovery published (trough recovers in 3 trading days) | high |
| QM-19 | P2 | all | `annualization_factor`, `ddof`, per-metric `n` absent — inputs unverifiable from the artifact | high |
| QM-20 | P2 | monte_carlo | No simulation error (±2.1pp on prob_success); arithmetic μ vs log-median estimand gap | high |
| QM-21 | P2 | monte_carlo | t-innovations winsorized at ±8σ and df floored at 2.1, undisclosed | high |
| QM-22 | P2 | realized_risk, monte_carlo | Latent hard zeros: `sharpe_ratio = 0.0` for n < 10; `expected_shortfall = 0.0` if none fail | high |
| QM-23 | P2 | stress_testing | `as_of: null` on the only section that uses measured per-ticker vols | medium |
| QM-24 | P2 | risk_studio | Vol-cone bands from 249 overlapping windows; `percentile_rank` not inferential | high |

**Bottom line for the caller:** fix QM-1 through QM-5 before this artifact is shown to anyone. QM-1 and QM-2 are wrong *objects*, not wrong arithmetic; QM-3 and QM-4 are numbers that cannot be derived from anything published; QM-5 is correct arithmetic with a 30-observation gate and no uncertainty. The remaining 19 findings are disclosure and interpretation defects — real, worth fixing, but none of them means a published number is false.
