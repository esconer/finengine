# FinEngine — Finance Library Adoption Report

**Date:** 2026-09-27
**Scope:** 12 candidate libraries evaluated against FinEngine ("Daisy Risk Engine")
**Method:** Each library was installed into a throwaway `uv` environment pinned to FinEngine's exact stack (py3.12.9 / pandas 3.0.6 / numpy 2.5.3 / scipy 1.18.1) and exercised. No claim below rests on docs alone.
**Companion reports:** `portfolio-optimization-libraries.md`, `data-and-indicator-libraries.md`, `performance-and-backtesting-libraries.md`, `institutional-libraries.md`, `current-codebase-quant-inventory.md`

---

## 1. Verdict matrix

| # | Library | Verdict | License | Compat blocker? | New deps | ROI |
|---|---------|---------|---------|-----------------|----------|-----|
| 1 | **quantstats** (installed) | **ADOPT — upgrade now** | Apache-2.0 | No — but pinned version is broken | 0 | **Highest** |
| 2 | **PyPortfolioOpt** | **ADOPT_PARTIAL** | MIT | `HRPOpt` dead on scipy 1.18 | 1 (`scikit-base`) | High |
| 3 | **FinanceToolkit** | **ADOPT_PARTIAL** | MIT | No — pandas-3 native | 0 in scope | Medium |
| 4 | **skfolio** | **ADOPT_PARTIAL** | BSD-3 | No — pandas 3.0 PR merged 2026-08-23 | 1 (`plotly` ~40 MB) | Medium |
| 5 | **FinanceDatabase** | **ADOPT_PARTIAL** (data only) | MIT | No | 0 | Medium |
| 6 | **QuantLib** (installed) | **ADOPT_PARTIAL — decide keep-or-drop** | BSD-3 | 0 imports; not thread-safe | 0 | Conditional |
| 7 | **Riskfolio-Lib** | **EVALUATE_LATER** | BSD-3 | 2 headline features broken on numpy 2.x | **+52 packages** | Low |
| 8 | **FinQuant** | **AVOID** | MIT | **Fatal on numpy 2.5.3** | — | None |
| 9 | **backtrader** | **AVOID** | **GPL-3.0-or-later** | Abandoned 2023-04-19 | — | None |
| 10 | **backtesting.py** | **AVOID** | **AGPL-3.0** | No multi-asset rebalancing | — | None |
| 11 | **gs-quant** | **AVOID** | Apache-2.0 | `numpy<2.4.0` vs our 2.5.3 | — | None |
| 12 | **shashankvemuri/Finance** | **AVOID** | MIT | Destroys every Indian ticker | — | None |

**Already a dependency, no action needed:** `arch`, `statsmodels`, `cvxpy`, `scipy`, `scikit-learn`, `hmmlearn`, `stockstats`, `bfinance`, `yfinance`, `matplotlib`, `seaborn`.
**Already a dependency but unused:** `quantlib` (declared `pyproject.toml:37`, **zero imports** in `backend/app/`).
**Already a dependency and under-used:** `quantstats` (12 of 84 `qs.stats` functions; 0 of `qs.plots`/`qs.reports`/`qs.utils`).

---

## 2. The five AVOIDs, and why each is disqualifying

### FinQuant — unusable on your numpy (empirically proven)
`finquant/type_utilities.py:117` validates dataframes with `all(df.dtypes == np.floating)`.
NumPy silently removed that coercion: `np.dtype('float64') == np.floating` is **True on 2.1.0, False on 2.5.3**.
Proven on a 2×2 matrix — fails on pandas 2.2.3 + numpy 2.5.3, *and* on pandas 3.0.6 + numpy 2.1.0
(a second, independent bug). Passes only on pandas 2.2.3 + numpy 2.1.0. Abandoned ~3 years; hard-depends
on `quandl` (last release 2021).

### backtrader — GPL-3.0-or-later
§5(c): *"You must license the entire work, as a whole."* Forces your entire backend to GPLv3.
Maintenance is also dead: last master commit **2023-04-19**, 0 open issues with creation **disabled**,
63 untriaged PRs, classifiers stopping at Python 3.7. It *does* still run on py3.12 + pandas 3.0.6 —
the blocker is purely legal plus abandonment.

### backtesting.py — AGPL-3.0
§13 attaches on **network use**, which is exactly FinAPI's delivery model. Independently disqualified
architecturally: its own docs say *"It does not support multi-asset portfolio rebalancing"*, and
`Backtest.__init__` takes a single DataFrame (verified at runtime).

### gs-quant — hard `numpy<2.4.0` cap
`uv lock` fails outright against your numpy 2.5.3:
> `gs-quant==2.1.17` + `numpy==2.5.3` ⇒ *"No solution found… your project's requirements are unsatisfiable."*

Drop the pin and uv backtracks to **gs-quant 1.4.67 (2022)**. Both outcomes are unacceptable. Additionally,
all subpackages (`gs-quant-reports`, `-risk`, `-bond`, `-equities`, `-commodity`, `-strategies`, `-databases`)
are **404 on PyPI** — it is a single monorepo package now. The tearsheet framework
(`Teaser`, `ScenarioReport`, `BacktestPerformanceTeardown`) has **0 hits across all 424 wheel entries** —
it no longer ships. Requires GS-institutional credentials.

### shashankvemuri/Finance — destroys Indian tickers
`normalize_ticker` does `.replace(".", "-")` ⇒ `RELIANCE.NS` → `RELIANCE-NS`. Every Indian ticker dies at
the boundary; this project is Indian-market-first. `version = "0.0.0"`, never released on PyPI. Its 4.3k
stars are inherited from deleted code after a full rewrite in one commit (2026-09-07) following 16 months
of silence. **Onboarding footgun:** `pip install finance` installs a *different* 2014 Python-2 package by
another author.

> **Keep your existing 199-line `backtest_service.run_walk_forward_backtest`.** It already implements
> one-way turnover `0.5·Σ|Δw|`, self-financing weight drift `w_{t+1} = w_t(1+r_t)/(1+w_tᵀr_t)`, and
> cvxpy `STRATEGY_OBJECTIVES` routing. Neither GPL/AGPL library can do all three.

---

## 3. Licensing summary

| License | Libraries | Impact |
|---------|-----------|--------|
| MIT | FinQuant, FinanceToolkit, FinanceDatabase, PyPortfolioOpt | No restriction. Commercial use permitted. |
| BSD-3-Clause | skfolio, QuantLib, Riskfolio-Lib | No restriction. Riskfolio's **no-endorsement** clause only — do not put it in product marketing copy. |
| Apache-2.0 | quantstats, gs-quant | No restriction. |
| **GPL-3.0-or-later** | backtrader | **§5(c) viral on the whole work.** Blocker. |
| **AGPL-3.0** | backtesting.py | **§13 attaches on network use.** Blocker for an API product. |

> ⚠️ **Escalate to counsel.** The GPL §5(c) and AGPL §13 conclusions are a *technical reading of licence
> text, not legal advice*, before any commercial deployment.

---

## 4. Recommended adoption order

### ① `quantstats>=0.0.85` — highest ROI, zero new dependencies
Your pin is **four versions / eight months stale** with verified pandas 3.0.6 breakage:

| Broken in 0.0.81 | Symptom | Fixed in |
|---|---|---|
| `aggregate_returns("weekly")` | `DatetimeIndex has no attribute 'week'` | 0.0.82 |
| `rar(rf=0.05)` | returns **−100%** | 0.0.85 |

```toml
# backend/pyproject.toml
"quantstats>=0.0.85",
```
Then `uv sync --extra dev --group dev` and `pytest`.

**Expect one failure first:** `test_uncertainty_disclosure.py:296` on `max_drawdown` — 0.0.82 changed the
phantom-baseline heuristic (`1e5`/`100`/`1.0` chosen by the first price's magnitude) that
`analytics_engine.py:1113-1127` faithfully reimplements. Re-baseline deliberately, don't paper over it.

**Then close the capability gap.** You use 12 of 84 `qs.stats` functions; **zero** of `qs.plots` (25),
`qs.reports` (5), `qs.utils` (14). `qs.reports.metrics(display=False, mode="full")` returns an
**81-row DataFrame (verified)** — 67 metrics unexposed: MTD/3M/6M/YTD/1Y/3Y/5Y/All-time, Prob. Sharpe Ratio,
Ulcer Index, Serenity Index, Recovery Factor, EVaR, Information/Treynor, R², drawdown periods.
Wire them through the existing `_tear_sheet_relative_uncertainty` block (`analytics.py:616-661`).
Note: **`qs.stats.turnover` does not exist** in 0.0.81 or 0.0.85.

### ② PyPortfolioOpt — covariance shrinkage only (correctness fix)
You run a convex optimiser on a **plain sample covariance** (`analytics_engine.py::_sample_covariance_volatility`,
L2347). For an N-asset Indian book with a short history, that is unstable. This is a correctness fix, not a feature.

```toml
"PyPortfolioOpt>=1.6.0",
```
```python
from pypfopt import risk_models
# cache this — measured 7.0 s per call
cov = risk_models.CovarianceShrinkage(returns).ledoit_wolf()
# or .oracle_approximating() when you want the empirical covariance to survive near-singularity
```
Costs one pure-Python dep (`scikit-base`). **No blockers.**

⚠️ **Silent API break to design around:** pypfopt 1.6.0 changed `portfolio_performance()` from
**dict → tuple** (verified at runtime and via Context7). This will not fail at import.

🚨 **Do NOT migrate HRP to `HRPOpt`.** `hierarchical_portfolio.py:152` reads the *private*
`scipy.cluster.hierarchy._LINKAGE_METHODS`, **removed in scipy 1.18.0** (bisected: True 1.11.4→1.17.0,
False 1.18.0). Your own `_hrp_weights()` (`optimization_service.py:549-616`) works — keep it. This also
invalidates the codebase audit's original rank-9 recommendation.

### ③ Fix the PDF tearsheet — zero dependencies, highest user-visible impact
Your institutional PDF contains **zero charts**, and the reason is structural, not a broken call:

- `addChart` (`export.ts:89-98`) *is* a stub — it draws a grey rect and writes `"Chart Image"` — but it is
  **never called anywhere in the codebase**.
- The live path is `exportInstitutionalReviewPDF` (`export.ts:319`, called from `Header.tsx:61`). It has
  **no** `addChart`/`addImage`/`toDataURL`/canvas call in its body, accepts `riskMetrics?: any` and never
  uses it, and emits three **hardcoded prose strings** at L428-432 that are identical for every portfolio.
- That violates your own `AGENTS.md` rule: *"Metric Card Hygiene: ...strictly driven by live API responses."*
- Meanwhile `ChartExporter.exportChart` (`export.ts:222-277`) is a **working** SVG→canvas→blob implementation.

**Fix:** call `ChartExporter` from the institutional path, and drive the L428-432 bullets from
`riskMetrics`. `exportChart` already accepts a Blob and `pdf.addImage` takes one.

### ④ FinanceToolkit — breadth, key-free
Runs key-free via `enforce_source="YahooFinance"`, so **no new credential dependency**. Only one of the
three data libraries with a pandas-3 native floor (`pandas>=3.0`).
🚨 **Landmine:** `risk_free_rate` defaults to the **US 10-year Treasury** in both `Toolkit.__init__` and
`FinanceFrame.to_toolkit`. On an INR book this silently produces wrong Sharpe/Sortino/CVaR. Pin it to an
Indian instrument on day one.
🚨 **Regression risk:** its `risk`/`performance`/`portfolio` (97 methods) duplicate `analytics_engine.py`
(4,119 lines, adds bootstrap CIs, moving-block resampling, effective-N that the toolkit lacks),
`optimization_service.py` (correct Rockafellar-Uryasev CVaR), `tail_risk_service.py` and
`volatility_service.py`. **Adopt for breadth only. Do not migrate the risk engine onto it.**
Keep the officially-documented "data-agnostic" seam (`historical=`/`income=`/`balance=`/`cash=`) so your
data layer stays yours. Exclude the credential-locked modules: `Discovery` (FMP-only, no fallback),
`ratios.get_forward_price_earnings_ratio()`, `..._growth_ratio()` (FMP Premium).

### ⑤ FinanceDatabase — offline enrichment only
MIT, ACTIVE, **weekly bot data refresh**, no key. 14.58 MB `equities.bz2` → ~1 MB in SQLite.
🚨 **Measured Indian coverage is bad:** ISIN **2.4% populated for India** (137 of 5,680) ⇒ unusable as a
join key; `industry` 33%. NSE is **asymmetric and partial** — 1,716 `.NS` vs 3,793 `.BO`, only 1,508
companies on both. Use `mic` (`XNSE`/`XBOM`, 100%) and `delisted` (100%).
**Enrichment, never the universe of record.**

### ⑥ QuantLib — decide keep-or-drop, then use narrowly
A 37 MB **dead dependency**: zero first-party imports. `derivatives_service.py` and
`fixed_income_service.py` were never written. Either land options on it or remove the pin.
🚨 **Not thread-safe** — its own METADATA warns about globals, *"most notably, the evaluation date"*.
Under FastAPI + anyio threadpool this must be serialised behind a lock.
🚨 **The 1.4.x API break** is severe: `BlackScholesMertonEngine`→`AnalyticEuropeanEngine`,
`PiecewiseLinearZeroCurve`→`PiecewiseLinearZero`, `BusinessDay` class→`ql.Following`.
🚨 **The spectral risk measures everyone cites are NOT in the Python binding** (0 hits for
Spectral/Shortfall/Entropic). Only `ql.RiskStatistics` — descriptive VaR/ES, matches numpy to 1.39e-17, and
**numpy is already faster**, so use it as a *test oracle*, not production code.
**Highest-value narrow use:** `ql.India(ql.India.NSE)` calendar + `Business252`, which retires 12+
hardcoded `np.sqrt(252)` annualisation sites. Roll out behind a golden-value sweep.

### ⑦ skfolio — if you want full ERC + CVaR/CDaR frontiers
BSD-3, ACTIVE, pandas 3.0 compat PR **#216 closed 2026-08-23**. Verified installing and running
`MeanRisk(CVaR/VAR/CDAR)`, `HRP`, `RiskBudgeting`, `MaxDiv` on your exact stack. `cvxpy-base` resolves to
your 1.9.3. Only new dep is `plotly` (~40 MB).
Fills two genuine gaps: **full Euler risk-parity decomposition** (`analytics_engine.py:2685` explicitly
declares *"not full ERC: no Euler RC_i decomposition"*) and **CDaR**, which nothing else here provides.

### ⑧ Riskfolio-Lib — defer
Two headline features are broken on your stack (measured 12/12 param combos):
- `HERC`/`HERC2` — `HCPortfolio.py:1095` passes `linkage`/`upper_bound`/`lower_bound` to a method whose
  signature at L522 is `(self, Z, rm, rf, model)`.
- `linkage="DBHT"` — `DBHT.py:491` fails on numpy 2.x.
**Dependency bloat is the decisive drawback:** it hard-pins `vectorbt` — which **none of its 12
`riskfolio/src/` modules import** — dragging in `numba`, `plotly`, `ipywidgets`, `anywidget`, `dill`.
**Measured 86 packages installed vs 34 for pypfopt.** Override it or use `--no-deps`.
Performance is uneven: core scales fine (0.036 s @10 → 0.366 s @200) but `owa_optimization` = **202 s**
and `rm="TG"` = **36-63 s** for 8 assets.
🚨 MOSEK is *"highly recommended"* for several risk measures — that would silently create a **paid licence**
dependency. Re-check before considering.

---

## 5. Zero-mock violations found (fix regardless of libraries)

| Severity | Location | Issue |
|---|---|---|
| **HIGH** | `analytics.py:8398-8402` | Fabricated `market_value=10000.0` per ad-hoc position. `IndiaDataService.calculate_portfolio_liquidity_limits` reads `position.market_value` (L466-470), so `position_value`, `days_to_liquidate_10pct_adv` and all rollups compute against an **invented ₹10,000 base**. Route nulls only the top-level `portfolio_value`. |
| MEDIUM | `analytics_engine.py:3145-3150` | Below 10 obs, returns a **period sum** under the key `annual_return` and forces `sharpe_ratio = 0.0`, `sortino_ratio = 0.0`. Directly violates your own audit rule `num_018_no_hard_zero_sub_scores` (`context_audit.py:3033-3100`). Should be `None` + reason, per `apply_annualization_gate` (`utils/holdings.py:356-367`). |
| MEDIUM | `analytics_engine.py:2275` | `max_drawdown = portfolio_impact * 1.15` published as a drawdown. Disclosed via `max_drawdown_basis: "derived_from_shock_proxy"`, but the field name misleads. |
| MEDIUM | `optimization_service.py:695` | `w_mkt = np.ones(n)/n` used as the Black-Litterman "market portfolio". Silently biases the prior to equal weight. Undisclosed. |
| MEDIUM | `optimization_service.py:752` | `np.clip(raw, 0, None)` + renormalise after the BL tangency solve ⇒ returned weights are **not** the solution of the stated program. Undisclosed. |
| MEDIUM | `regime_service.py:307-311` | `init_params="mc"` means Baum-Welch **never re-estimates `transmat_`**; the `0.96` diagonal is what `transition_matrix` publishes. Self-disclosed at L222-227. |
| MEDIUM | `analytics_engine.py:2228-2236` | Three hardcoded per-ticker stress elasticities (`MAFANG.NS`, `MIDCAPIETF.NS`, `SELECTIPO.NS`). Disclosed, but a ticker rename silently drops them. |
| MEDIUM | `analytics_engine.py:2104-2175` | 7×7 hand-typed sector-elasticity table, all literal floats. Disclosed as `static_configured_table`. |
| LOW | `tail_risk_service.py:261-336` | The "Student-t copula" is **not a copula fit** — two *marginal* univariate MLEs averaged, pushed through the closed-form t-λ_L formula. Cannot extend past n=2. Use `copulas` (Gaussian/Archimedean/Vine) for a real joint fit. Response schema is unchanged, so this is a drop-in. |
| LOW | `analytics.py:8535` | Unreachable duplicate `except HTTPException`. |
| LOW | `analytics.py:8492-8530` | `/vol-cone` validates `lookback_days` (60-2520) but never passes it to `calculate_volatility_cone` — the parameter is **inert**. |
| LOW | `india_data_service.py:403` | `np.std` with `ddof=0` while every other dispersion in the repo is `ddof=1`. |
| LOW | `analytics_engine.py:3679-3681` | EWMA recursion seeded from **full-sample** `np.var(r)` but iterated over only the trailing 60 rows — inconsistent hybrid. |
| LOW | `pyproject.toml:37` | `quantlib>=1.40` declared, **never imported**. |

---

## 6. Corrections to the codebase audit

The audit's replacement table contained two recommendations that later evidence **overturned**. Both are
recorded here so they are not re-derived from the audit:

1. **Do NOT delete `analytics_engine.py:1053-1152` (`quantstats_ratio_statistics`).** The audit called it
   "~210 LOC of formulas duplicated from quantstats/empyrical, delete." It is not duplication — it is the
   **vectorised `(n, draws, k)` restatement that verifies the circular-block bootstrap resamples the
   *published* statistic**. Load-bearing for the `point_tolerance` identity check at L793-824. Swapping in
   `empyrical` means `np.apply_along_axis` over every draw — a rewrite, effort S/M not S/S. It is correct
   and self-verified; **leave it alone**.
2. **Do NOT migrate HRP to `PyPortfolioOpt.HRPOpt`.** Broken on scipy 1.18 (private `_LINKAGE_METHODS`
   removed). See §4②.

The audit's §5 "already well-built" list was the more reliable section and should be read as a **regression
suite**, not a refactor queue. In particular, do not touch: the `point_tolerance` gating mechanism, the
"unmeasured ≠ zero" discipline in `risk_scoring` + `_risk_score_audit` (300 lines), the portfolio-return
coverage contract, `utils/allocations.py` in its entirety, the EVT-POT GPD fit, the OU half-life estimator,
the vol-cone overlap correction, and `currency_service.FXRate` (the provenance template every other
hardcoded constant should follow).

---

## 7. What FinEngine already delegates (do not reimplement)

| Category | Delegated to | Where |
|---|---|---|
| All technical indicators | `stockstats` | `indicators_service.py:126-132` (incl. a real MFI 0-1 vs 0-100 scale fix) |
| P/E, P/B, market cap, sector, EV/EBITDA, Piotroski, Graham | `bfinance` | `equity_research_service.py:36-260` |
| Screeners (Coffee Can, Magic Formula, Debt-Free…) | `bfinance.screens` | `screener_service.py:79-349` |
| Engle-Granger, Johansen | `statsmodels.coint` / `coint_johansen` | `cointegration_service.py:778, 735` |
| GARCH, EGARCH | `arch` | `analytics_engine.py:3501, 3579` |
| Regime HMM | `hmmlearn` | `regime_service.py:235` |
| Stationary bootstrap | `arch.bootstrap.StationaryBootstrap` | `monte_carlo_service.py:182` |
| Beta/alpha w/ HAC SEs | `statsmodels.OLS(cov_type="HAC")` | `analytics_engine.py:3756` |
| min-vol, max-Sharpe, min-CVaR | `cvxpy` | `optimization_service.py:619-667` |
| Sharpe/Sortino/Calmar/Omega/tail, drawdown series | `quantstats` | `analytics.py:6096-6147` |

**Free capability additions you are missing** (no new dependencies):
- **GJR-GARCH** — you have GARCH and EGARCH but not the asymmetric standard. `arch` gives it as
  `arch_model(returns, p=1, o=1, q=1)`. `analytics_engine.py:3501` already does the sibling call.
- **ADF / KPSS / Granger causality** — `arch.unitroot` and `statsmodels.tsa.stattools`; you already depend on both.
- **Bonferroni / BH multiplicity** — `statsmodels.stats.multitest.multipletests` (you hand-rolled it at
  `cointegration_service.py:297-336`), or `arch.bootstrap.MCS`, which is better because it handles
  dependence between tests.
- **Parkinson estimator** — `arch.roll_volatility.parkinson`; you hand-rolled it at `regime_service.py:263-277`.
- **HAC-consistent alpha annualisation** — your alpha at `analytics_engine.py:3826` is a raw ×252.
- **Unlabelled VaR horizon** — `var_95`/`cvar_95` (`analytics_engine.py:3186-3194`) are daily percentiles
  published with no horizon, beside a dated 21-day forecast. Add a horizon field.

**Duplicate implementations to consolidate (pure de-dup, no library needed):**
- **EWMA** — `analytics_engine._ewma_forecast` (L3669-3742, recursion) vs
  `volatility_service.calculate_ewma_volatility` (L150-200, weighted-moment). Same model, **two different numbers**.
- **Liquidity tier ladder** — `analytics_engine.py:1986-2007` and `analytics.py:2052-2075` are two
  independent copies of the same four formulas; the route's re-derivation block (L2078-2201) exists
  *because* they can drift.

---

## 8. Documentation corrections

- `analytics_engine.py` is **4,119** lines (`PROJECT.md`/`CONTEXT.md` say 3,867).
- `cointegration_service.py` is **~1,330** lines (docs say 1,190).
- `quantstats` pin is unpinned; newest is 0.0.85. `quantlib` 1.43 is already the newest available.

---

## 9. Recommended sequence

| Step | Action | Effort | Risk | New deps |
|---|---|---|---|---|
| 1 | `quantstats>=0.0.85`, resync, re-baseline the `max_drawdown` test | S | S | 0 |
| 2 | Fix `exportInstitutionalReviewPDF` — wire `ChartExporter`, drive bullets from `riskMetrics` | S | S | 0 |
| 3 | Fix the `market_value=10000.0` fabrication + mislabelled `annual_return`/zero Sharpe | S | S | 0 |
| 4 | De-dup EWMA + liquidity ladder | S | S | 0 |
| 5 | PyPortfolioOpt `ledoit_wolf` covariance shrinkage | S | S | `scikit-base` |
| 6 | Decide QuantLib keep-or-drop; NSE calendar + `Business252` behind a golden-value sweep | S→M | S→M | 0 |
| 7 | Add GJR-GARCH, ADF/KPSS, `multipletests`, Parkinson | S | S | 0 |
| 8 | FinanceDatabase offline enrichment (SQLite, `mic`/`delisted` only) | M | S | 0 |
| 9 | FinanceToolkit breadth, key-free, `risk_free_rate` pinned to an Indian instrument | M | M | 0 in scope |
| 10 | skfolio for full ERC + CDaR if the gap still matters | M | M | `plotly` |
| 11 | Real copula fit via `copulas` | M | M | `copulas` |
| — | **Escalate GPL/AGPL question to counsel** | — | — | — |

Steps 1-4 require no new dependencies and fix real user-visible and correctness defects. **Do them first.**

---

## 10. Evidence quality notes

- All library verdicts were produced by **installing and exercising** each library on FinEngine's exact
  pinned stack, not by reading documentation. The FinQuant numpy failure, the PyPortfolioOpt/scipy 1.18
  HRP failure, and the Riskfolio HERC failures are all first-hand reproductions with source citations.
- Context7 was available to the analysis agents and used for API surface. Its **absences** were treated as
  findings: no spectral risk measures in the QuantLib Python binding, no gs-quant tearsheet subpackages,
  no Context7 entry for shashankvemuri/Finance, no Context7 docs for `RiskModel.marginal_risk_contribution`.
- **Marked UNVERIFIED** (could not confirm): the two Riskfolio bugs could not be cross-referenced against
  upstream issue trackers (GitHub API rate limit + JS-gated search) — reproductions are first-hand but not
  triaged by maintainers. `quantlib` ↔ `riskfolio` coexistence is reasoned from import graphs, not co-installed.
- **Retracted during verification:** `empyrical.treynor_ratio` / `.tracking_error` / `.ulcer_index`
  (not in the exported function lists); `PyPortfolioOpt.RiskModel.marginal_risk_contribution` (class
  verified, method name not). Do not use these names in code.
- **Not attempted:** migration of `monte_carlo_service.py` (measured: vectorised numpy is **5.6× faster**
  than a QuantLib loop), `tail_risk_service.py` (no QuantLib EVT/copula equivalent), or `var_95`/`cvar_95`.
