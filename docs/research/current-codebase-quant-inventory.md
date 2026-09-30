# FinEngine — Codebase Quantitative Inventory

**Date:** 2026-09-27
**Scope:** every hand-rolled quantitative capability in `backend/app/`
**Method:** read-only sweep; symbol lists built by grepping definitions, then targeted reads of the substantive ones
**Companion:** `00-CONSOLIDATED-ADOPTION-REPORT.md`

> Produced by a read-only audit agent that could not write files; reconstructed here from its findings.
> Two line counts in `PROJECT.md` are stale: `analytics_engine.py` is **4,119** (not 3,867),
> `cointegration_service.py` is **~1,330** (not 1,190).

---

## 1. Executive summary

- **47 distinct quantitative capabilities** implemented in-house. **~3,600 LOC of real quant computation**
  inside **~14,000 lines** of quant + disclosure code. That 4:1 disclosure-to-compute ratio is the
  defining characteristic of this codebase and should be preserved through any replacement.
- The project has **already delegated 8 of 13 categories** to libraries (indicators → `stockstats`,
  fundamentals/screens → `bfinance`, cointegration → `statsmodels`, GARCH/EGARCH → `arch`, regimes →
  `hmmlearn`, bootstrap → `arch.bootstrap`, OLS → `statsmodels`, optimisation → `cvxpy`).
- The remaining hand-rolled work is largely **PRODUCTION_GRADE** — the vol cone, EVT-POT fit, OU
  half-life, portfolio-return coverage contract, and allocation rounding are more careful than most
  off-the-shelf equivalents.
- `quantlib` is declared (`pyproject.toml:37`) and **never imported** — a verified dead dependency.
- The dominant pattern is not *missing* libraries but **duplication and drift**: two EWMA
  implementations, two liquidity ladders, and 9 quantstats ratios reimplemented so they can be vectorised.
- Zero-mock discipline is otherwise strong — ~60 sites carry explicit `not_computed` / `reason` / `basis`
  disclosures. The violations are enumerated in §5 and cross-referenced in the consolidated report.

---

## 2. Capability inventory

`LOC` = approximate lines of the implementation. **Verdict** ∈ PRODUCTION_GRADE / WORKING_BUT_FRAGILE /
NAIVE_OR_BUGGY / HARDCODED_OR_MOCK.

### 2.1 Returns & risk metrics

| Capability | Location | Impl | LOC | Verdict | Better library? |
|---|---|---|---|---|---|
| Return construction (wide + per-position) | `analytics_engine.py:1700,1820,2208,2452,2778,3338`; `analytics.py:5282,5677,5742` | `pct_change(fill_method=None)` | ~10 | PRODUCTION_GRADE | no |
| Portfolio return aggregation + coverage gate | `analytics_engine.py:63-293` | pandas + drop-not-renormalise | ~180 | PRODUCTION_GRADE | no — models the "declared book must have traded" contract |
| Annualised return | `analytics_engine.py:3153` | `mean*252` | 2 | WORKING_BUT_FRAGILE | `empyrical.annual_return` |
| **Annualised return, short-sample branch** | `analytics_engine.py:3145-3150` | returns a **period sum** under key `annual_return`; forces `sharpe=0.0`, `sortino=0.0` | 6 | **NAIVE_OR_BUGGY** | should be `None` + reason, per `utils/holdings.py:356-367` |
| Annualised volatility (ddof=1) | `analytics_engine.py:3154,1210,2473,2252,2534` | `std*sqrt(252)` | ~2 ea | PRODUCTION_GRADE | `empyrical.annual_volatility` |
| Sharpe (engine + vectorised twin) | `analytics_engine.py:3156-3157, 1212-1218` | numpy | 6 | PRODUCTION_GRADE | `empyrical.sharpe_ratio` |
| Sharpe/Sortino/Calmar/Omega/tail (tear sheet) | `analytics.py:6096-6106, 6141-6147` | **quantstats** | 0 | PRODUCTION_GRADE | already delegated |
| Vectorised restatement of the same 9 ratios | `analytics_engine.py:1053-1152` | hand-written numpy, verified 1e-6 | 100 | PRODUCTION_GRADE **— keep, see §4** | not a free deletion |
| Restatement of engine's own metrics | `analytics_engine.py:1190-1264` | numpy | 75 | PRODUCTION_GRADE (duplication) | — |
| Market-model beta/alpha | `analytics_engine.py:1155-1187`; `analytics.py:6183-6184,6264-6265` | `cov/var` + Jensen | 33 | PRODUCTION_GRADE | `empyrical.beta/alpha` |
| Sortino | `analytics_engine.py:3159-3165, 1220-1227` | downside dev | 7 | PRODUCTION_GRADE | `empyrical.sortino_ratio` |
| Calmar | `analytics_engine.py:1129-1131` | `cagr/|maxDD|` | 3 | WORKING_BUT_FRAGILE | `empyrical.calmar_ratio` |
| Max drawdown (baseline-aware) | `analytics_engine.py:3199-3221`; twins `1113-1127,1247-1253`; `backtest_service.py:178-183` | `cumprod`+`cummax` | ~20 | PRODUCTION_GRADE | `empyrical.max_drawdown` |
| Drawdown series (underwater) | `analytics.py:6315-6317` | **quantstats** | 0 | PRODUCTION_GRADE | already delegated |
| Historical VaR/CVaR 95 | `analytics_engine.py:3180-3197`; twins `1232-1245` | `np.percentile(r,5)` | ~18 | WORKING_BUT_FRAGILE | **no horizon declared** — sits beside a dated 21-day forecast |
| Skew / excess kurtosis | `analytics_engine.py:3223-3234`; `analytics.py:6105-6106` | `pandas.skew/kurtosis` | 12 | PRODUCTION_GRADE | identical in scipy |
| Hit ratio | `analytics_engine.py:3168` | `(r>0).mean()` | 2 | PRODUCTION_GRADE | no |
| Monthly compounding | `analytics.py:6303` | `groupby([y,m]).prod()-1` | 1 | PRODUCTION_GRADE | **keep** — matches AGENTS.md invariant |
| Beta w/ HAC SEs | `analytics_engine.py:3744-3936` | **statsmodels `OLS(cov_type="HAC")`** | ~160 | PRODUCTION_GRADE | delegated |
| Alpha (Jensen, annualised) | `analytics_engine.py:3826,3886,3895` | params × 252 | ~3 | WORKING_BUT_FRAGILE | raw ×252, no Newey-West on alpha itself |
| Tracking error / Information ratio / Treynor / Ulcer | — | **not implemented** | 0 | — | `qs.reports.metrics(mode="full")` — 67 unexposed metrics available today |
| AR(1) autocorrelation | `analytics_engine.py:587-605` | OLS slope | 19 | PRODUCTION_GRADE | `statsmodels.acf` (full ACF) |
| Effective sample size (Quenouille) | `analytics_engine.py:608-625` | `n(1-ρ)/(1+ρ)` | 50 | PRODUCTION_GRADE | no equivalent |
| Circular moving-block bootstrap | `analytics_engine.py:661-1018` | hand-rolled Politis–Romano | 340 | **PRODUCTION_GRADE — best block in repo** | `arch.bootstrap.CircularBlockBootstrap` for indices only; the gating logic has no equivalent |

### 2.2 Portfolio construction & optimisation

| Capability | Location | Impl | LOC | Verdict | Better library? |
|---|---|---|---|---|---|
| HRP (Lopez de Prado bisection) | `optimization_service.py:528-616` | `scipy.cluster.hierarchy` + bisection | 70 | PRODUCTION_GRADE | **No — `HRPOpt` is dead on scipy 1.18** (private `_LINKAGE_METHODS` removed) |
| Global minimum variance | `optimization_service.py:619-629` | **cvxpy** + Clarabel | 11 | PRODUCTION_GRADE | `pypfopt.min_volatility` |
| Tangency / max-Sharpe | `optimization_service.py:632-649` | **cvxpy** | 18 | PRODUCTION_GRADE | `pypfopt.max_sharpe` |
| Min-CVaR (Rockafellar-Uryasev) | `optimization_service.py:652-667` | **cvxpy** LP | 16 | PRODUCTION_GRADE | textbook-exact already; `pypfopt.EfficientCVaR` adds `transaction_cost` |
| Black-Litterman | `optimization_service.py:670-756` | `pinv` BL + cvxpy | 87 | WORKING_BUT_FRAGILE | `pypfopt.BlackLittermanModel(market_caps=)`. **3 defects:** `w_mkt=ones/n` (`:695`), He-Litterman Ω only, silent `clip`+renorm (`:752`) |
| Weight normalisation | `utils/allocations.py:201-352` | python + `Decimal` | 150 | PRODUCTION_GRADE | **keep** — no library equivalent |
| Order-invariance funnel | `optimization_service.py:91-105` | reindex + universe assert | 15 | PRODUCTION_GRADE | **keep** — a real bug-class fix |
| Optimiser uncertainty (bootstrap μ/Σ) | `optimization_service.py:183-283` | vectorised resample | 100 | PRODUCTION_GRADE | `arch.bootstrap` |
| Efficient frontier | — | **not implemented** (point solutions only) | 0 | — | `pypfopt.EfficientFrontier`, riskfolio |
| Risk parity via CCD | — | **not implemented** | 0 | — | `skfolio.RiskBudgeting`; `analytics_engine.py:2685` admits *"not full ERC"* |
| Inverse-volatility sizing | `analytics_engine.py:2550-2595` | `w∝1/σ` | 45 | PRODUCTION_GRADE | **keep** — matches AGENTS.md invariant |
| CVaR w/ turnover/TC penalty | — | **not implemented** (no cost term) | 0 | — | `pypfopt.EfficientCVaR(transaction_cost=)`, `L2_reg` |
| Sector caps in optimiser | — | **not implemented** (map exists only for stress/risk rollup) | 0 | — | `pypfopt.add_sector_constraints` |
| Turnover + trade instructions | `analytics.py:6700-6965`; `utils/allocations.py:563-728` | weight-delta → half-up shares | ~200 | PRODUCTION_GRADE | **keep**; `pypfopt.DiscreteAllocation` is the candidate |

### 2.3 Risk decomposition

| Capability | Location | Verdict | Better library? |
|---|---|---|---|
| Marginal risk contribution | `analytics.py:6572` | PRODUCTION_GRADE | `pypfopt` risk_models |
| Component (Euler) RC | `analytics.py:6573-6576` | PRODUCTION_GRADE | `pypfopt` |
| Under-determined covariance pruning | `analytics.py:6550-6558` | PRODUCTION_GRADE | no — careful and correct |
| CVaR tail risk contribution | `analytics.py:6582-6611` | PRODUCTION_GRADE | legitimate custom extension; keep |
| HHI | `analytics_engine.py:1903` | PRODUCTION_GRADE | riskfolio `ConcentrationMeasure` |
| Effective N of bets `1/HHI` | `analytics_engine.py:1906` | PRODUCTION_GRADE | riskfolio |
| Diversification ratio | `analytics_engine.py:1911` | PRODUCTION_GRADE | riskfolio |
| Diversification score (N≤1 → 0) | `analytics_engine.py:1910` | PRODUCTION_GRADE | **keep** — matches AGENTS.md invariant |
| Gini | `analytics_engine.py:1914-1915` | PRODUCTION_GRADE | riskfolio |
| CVaR-at-risk / CDaR | — | **not implemented** | **skfolio** — only library in the set that provides it |
| Factor exposure beyond market beta | — | **not implemented** (beta only) | `pypfopt` `FactorModel`, riskfolio `FactorStats` |

### 2.4 Volatility models

| Capability | Location | Impl | LOC | Verdict | Better library? |
|---|---|---|---|---|---|
| GARCH(1,1) multi-step | `analytics_engine.py:3485-3567` | **arch** | 83 | PRODUCTION_GRADE | delegated |
| EGARCH multi-step | `analytics_engine.py:3569-3667` | **arch** (simulation, seed 100) | 99 | PRODUCTION_GRADE | delegated |
| **GJR-GARCH** | — | **not implemented** | 0 | — | `arch_model(r, p=1, o=1, q=1)` — **free**, sibling call already at `:3501` |
| EWMA (RiskMetrics recursion) | `analytics_engine.py:3669-3742` | hand-rolled | 74 | **WORKING_BUT_FRAGILE** | seeded from full-sample `var` but iterated over 60 rows — inconsistent hybrid |
| EWMA (weighted-moment) | `volatility_service.py:150-200` | vectorised | 51 | PRODUCTION_GRADE | **the better of the two**; de-dup target |
| Realized volatility (rolling) | `volatility_service.py:109-147` | `rolling.std*sqrt(252)` | 39 | PRODUCTION_GRADE | `arch` `realized_volatility` for RV-from-HL |
| HAR / HAR-RV | — | **not implemented** | 0 | — | no maintained stdlib option |
| Vol cone + overlap correction | `volatility_service.py:48-99, 278-457` | rolling percentiles | 180 | **PRODUCTION_GRADE** | **keep** — `effective_n = n_windows/window_days` is more rigorous than any library |
| Parkinson estimator | `regime_service.py:263-277` | pooled HL | 15 | PRODUCTION_GRADE | `arch.roll_volatility.parkinson` — free |
| Implied vol / IV surface / term structure | — | **not implemented** | 0 | — | **QuantLib** — and QuantLib is already a dead dependency here |
| Parametric VaR/ES from fitted vol | `analytics_engine.py:3522-3527, 3618-3631, 3693-3706` | hardcoded normal z-multipliers | ~20 | WORKING_BUT_FRAGILE | `arch` `res.distribution.ppf` — use the fitted distribution, not normal constants |
| Winsorisation | `analytics_engine.py:3495,3574,3674` | `clip(±0.20)` | 3 | WORKING_BUT_FRAGILE | `scipy.stats.mstats.winsorize` |

### 2.5 Tail & dependence

| Capability | Location | Verdict | Note |
|---|---|---|---|
| EVT-POT VaR/ES via GPD | `tail_risk_service.py:24-259` | **PRODUCTION_GRADE** | `genpareto.fit(floc=0)`, correct POT moments (`:79-94`), raw+constrained published, refuses to fabricate on failed fit (`:151-164`). **Keep.** |
| GPD shape clip + VaR floor | `tail_risk_service.py:122-142` | HARDCODED_OR_MOCK | exemplary disclosure (`:212-241`) |
| **Bivariate "Student-t copula" λ_L** | `tail_risk_service.py:261-336` | **NAIVE_OR_BUGGY as a copula fit** | closed-form t-λ_L from two *marginal* univariate MLEs + raw Pearson ρ. Not a copula family fit; cannot extend past n=2. **Replace with `copulas`** (Gaussian/Archimedean/Vine) — drop-in, schema unchanged |
| Tail dependence N×N matrix | `tail_risk_service.py:338-438` | PRODUCTION_GRADE | caching fix at `:376-379` is a real perf win; added because the matrix was ~12s for 14 assets |
| Hill estimator / Drawdown-at-Risk | — | **not implemented** | `copulas` / skfolio CDaR |

### 2.6 Time-series & regime

| Capability | Location | Impl | Verdict | Note |
|---|---|---|---|---|
| Gaussian HMM regimes (3-state) | `regime_service.py:204-429` | **hmmlearn** + sklearn scaler | PRODUCTION_GRADE | `params="mc"` ⇒ **transition matrix never re-estimated**; published `transition_matrix` is the hand-set prior (`:307-311`). Disclosed `:222-227` |
| Crash veto | `regime_service.py:90-113` | deterministic relabel | HARDCODED_OR_MOCK | business rule, disclosed as `label_overrides` |
| HMM convergence disclosure | `regime_service.py:116-201` | reads `hmm.monitor_` | PRODUCTION_GRADE | no library gives this |
| Rolling avg pairwise correlation + regime break | `correlation_service.py:17-193` | pandas rolling | PRODUCTION_GRADE | two-sided fix at `:117-119` is important |
| Engle-Granger / Johansen | `cointegration_service.py:778, 727-743` | **statsmodels** | PRODUCTION_GRADE | delegated |
| OLS hedge ratio | `cointegration_service.py:790, 810-818` | `np.polyfit(cov=True)` | WORKING_BUT_FRAGILE | the only OLS in the repo not using statsmodels; `coint().hedge_ratio` returns it directly |
| **OU speed θ & half-life** | `cointegration_service.py:668-724` | AR(1)-on-differences | **PRODUCTION_GRADE** | correctly refuses to fabricate in the oscillatory `γ≤-1` branch (`:717-722`). **Keep** |
| Bonferroni / BH multiplicity | `cointegration_service.py:297-336` | hand-rolled | PRODUCTION_GRADE | `statsmodels.stats.multitest.multipletests`; or `arch.bootstrap.MCS` (better — handles test dependence) |
| Pairs directive gate | `cointegration_service.py:467-598` | 5-rung gate | PRODUCTION_GRADE | fixed a real 1:1 mis-sizing defect up to 116× |
| ADF / KPSS / Granger causality | — | **not implemented** | 0 | `arch.unitroot` + `statsmodels.tsa.stattools` — both already dependencies |
| ARCH-LM / Hurst / changepoint | — | **not implemented** | 0 | `statsmodels.stats.diagnostic`, `ruptures` |

### 2.7 Monte Carlo & simulation

| Capability | Location | Verdict | Note |
|---|---|---|---|
| GBM paths | `monte_carlo_service.py:107-125` | PRODUCTION_GRADE | 10 lines; **do not replace** — measured 5.6× faster than a QuantLib loop |
| Student-t innovation GBM | `monte_carlo_service.py:128-165` | PRODUCTION_GRADE | analytic t moments at `:159-161` avoid single-extreme-draw poisoning |
| Stationary bootstrap | `monte_carlo_service.py:168-196` | PRODUCTION_GRADE | **arch** |
| Chunked / bounded path materialisation | `monte_carlo_service.py:199-301` | PRODUCTION_GRADE | real OOM fix, no library equivalent — **keep** |
| Terminal fan / goal probability | `monte_carlo_service.py:304-435` | PRODUCTION_GRADE | excellently disclosed `terminal_wealth_above_target` vs path-touch (`:394-409`) |
| Correlated multivariate paths | — | **not implemented** | univariate on an aggregated series by design |

### 2.8 Technical indicators — fully delegated

`indicators_service.py` (282 LOC) delegates **all** indicators to `stockstats` (`:126-132`): SMA/EMA, MACD,
RSI, Bollinger, ATR, VWMA, MFI. Includes a real fix for the MFI 0–1 vs 0–100 scale mismatch at the adapter
boundary (`:158-159`), plus a staleness guard (`:99-116`, `MAX_STALE_DAYS = 10`).
**Zero hand-rolled indicators exist.** This is the cleanest area and the model for the rest.
Gap: ADX, Stochastic, OBV, CCI, Williams %R, Ichimoku, SuperTrend, Donchian, pivots — all available in `stockstats`/`ta`.

### 2.9 Backtesting — keep as-is

`backtest_service.py` (237 LOC), `run_walk_forward_backtest`. **PRODUCTION_GRADE**, verified correct:
- trailing-only training windows (no look-ahead), `:98`
- one-way turnover `0.5·Σ|Δw|` × bps, `:118` — textbook
- self-financing weight drift `w_{t+1}=w_t(1+r_t)/(1+w_tᵀr_t)`, `:156-158`
- benchmark equal-weight buy&hold with drift, `:89`
- equity curve + drawdown, `:173-217`
**Both candidate replacements are licence-blocked (GPL/AGPL) and neither does all three of the above.**
`rebalance_events` (`:124-129`) is a rebalance log, not a trade log — no fills, prices, or per-trade P&L.

### 2.10 Liquidity & microstructure

| Capability | Location | Verdict | Note |
|---|---|---|---|
| ADV (shares + rupees) | `india_data_service.py:529-530` | PRODUCTION_GRADE | 30-session lookback (`:37`) |
| Amihud illiquidity | `india_data_service.py:40-56` | PRODUCTION_GRADE | textbook, correctly guarded |
| Days-to-liquidate @10%/20% | `india_data_service.py:59-68` | PRODUCTION_GRADE | |
| Max sane position (5% ADV) | `india_data_service.py:556` | HARDCODED_OR_MOCK | threshold **not disclosed** in payload |
| Liquidity tier 1d/5d thresholds | `india_data_service.py:555` | HARDCODED_OR_MOCK | the only undisclosed constant in the codebase |
| **Liquidity score 0-10 (4-tier)** | `analytics_engine.py:1986-2007` **and** `analytics.py:2052-2075` | HARDCODED_OR_MOCK | **two independent copies of the same 4 formulas**; the route's re-derivation block (`:2078-2201`) exists *because* they can drift. **De-dup target.** |
| "Bid-ask spread" from turnover | `analytics_engine.py:1990-2002` | HARDCODED_OR_MOCK | honestly named `assumed_bid_ask_spread_from_turnover_tier_formula` (`:1996`) but it is a curve fit, not a spread |
| Market-cap provenance + ₹1bn floor | `analytics_engine.py:1276-1296, 353` | HARDCODED_OR_MOCK | correctly labelled `is_estimate: True` (`:2014-2017`) |
| NSE bhavcopy + delivery % | `india_data_service.py:92-209` | PRODUCTION_GRADE | |
| FII/DII flows | `india_data_service.py:302-370` | PRODUCTION_GRADE | correctly reports `partial` when a category is missing |
| Delivery-% anomaly z-score | `india_data_service.py:372-435` | WORKING_BUT_FRAGILE | uses `ddof=0` at `:403`; every other dispersion in repo is `ddof=1` |

### 2.11 Valuation & fundamentals — fully delegated

Piotroski, Graham number, EV/EBITDA, interest coverage, CFO/PAT → **`bfinance`**
(`equity_research_service.py:215-260`). P/E, market cap, sector → `bfinance` (`:36-124`).
Fundamental screens (Coffee Can, Magic Formula, Debt-Free, High Dividend, Undervalued Growth) →
**`bfinance.screens`** (`screener_service.py:79-349`, with one finengine-side D/E ≤ 0.2 post-filter).
Financial statements → yfinance/bfinance (`company_data_service.py:309-397`).
**No hand-rolled valuation. Gap: P/B, DCF, DDM, FCF yield, ROE/ROA are exposed by `bfinance` but unwired.**

### 2.12 Currency / FX

| Capability | Location | Verdict |
|---|---|---|
| FX fetch (USDINR=X) | `currency_service.py:325-363` | PRODUCTION_GRADE — yfinance is the right pragmatic choice |
| Cross/inverse rate | `currency_service.py:203-211` | PRODUCTION_GRADE |
| `FXRate` float subclass + provenance | `currency_service.py:38-124` | **PRODUCTION_GRADE — the template every other hardcoded constant should follow** |
| `FALLBACK_USD_INR = 83.0` | `currency_service.py:27` | HARDCODED_OR_MOCK but **handled exemplarily**: fallback is never cached, is refused by `coerce_live_fx_rate`, and `convert_amount` refuses it without `allow_fallback=True` |
| INR formatting (Cr/L, `en-IN`) | `currency_service.py:271-289` | PRODUCTION_GRADE |

### 2.13 Data plumbing

Two-tier cache (L1 memory TTL + L2 SQLite, `data_service.py` + `cache_service.py`, ~500 LOC),
cache generation fencing, vendor retry/rate limiting with an Alpha Vantage key budget
(`alpha_vantage_service.py:126-234`), `.NS`/`.BO` ticker normalisation (`data_service.py:199-226`),
vendor frame validation (`:76-160`), CPU offload semaphore (`analytics.py:163-184`), and
**`context_audit.py` (3,936 lines, ~50 machine-checked payload rules)** — treat the latter as a
regression suite for any refactor; several §5 violations are codified rules being re-violated at the edges.

---

## 3. Free capability additions (no new dependencies)

| Addition | How | Effort/Risk |
|---|---|---|
| **GJR-GARCH** | `arch_model(r, p=1, o=1, q=1)` — sibling call already at `analytics_engine.py:3501` | S / S |
| **ADF / KPSS stationarity** | `arch.unitroot`, `statsmodels.tsa.stattools.adfuller` | S / S |
| **Granger causality** | `statsmodels.tsa.stattools.grangercausalitytests` | S / S |
| **Bonferroni / BH** | `statsmodels.stats.multitest.multipletests` (or `arch.bootstrap.MCS`, better) | S / S |
| **Parkinson estimator** | `arch.roll_volatility.parkinson` | S / S |
| **Market-model alpha w/ Newey-West** | `statsmodels.OLS(cov_type="HAC")` already used at `:3756`; apply to alpha | S / S |
| **Covariance shrinkage** | `pypfopt.risk_models.CovarianceShrinkage(...).ledoit_wolf()` → `analytics_engine.py:2347` | S / S |
| **VaR horizon label** | add a horizon field beside `analytics_engine.py:3186-3194` | S / S |
| **67 unexposed quantstats metrics** | `qs.reports.metrics(mode="full")` → 81-row DataFrame; wire via `analytics.py:616-661` | S / S |

---

## 4. Two recommendations that were overturned

The audit's replacement table contained two items later evidence disproved. Recorded so they are not
re-derived from §2:

1. **Do NOT delete `analytics_engine.py:1053-1152` (`quantstats_ratio_statistics`).** It is not
   duplication — it is the **vectorised `(n, draws, k)` restatement that verifies the circular-block
   bootstrap resamples the *published* statistic**, load-bearing for the `point_tolerance` identity check
   at `:793-824`. Swapping in `empyrical` means `np.apply_along_axis` over every draw: a rewrite, not a
   deletion. Correct and self-verified — **leave it**.
2. **Do NOT migrate HRP to `PyPortfolioOpt.HRPOpt`.** `hierarchical_portfolio.py:152` reads the private
   `scipy.cluster.hierarchy._LINKAGE_METHODS`, removed in **scipy 1.18.0** (bisected: True 1.11.4→1.17.0,
   False 1.18.0). The existing `_hrp_weights()` works — keep it.

---

## 5. Zero-mock / correctness violations

Full table with remediation in `00-CONSOLIDATED-ADOPTION-REPORT.md` §5. Highest severity:

| Severity | Location | Issue |
|---|---|---|
| **HIGH** | `analytics.py:8398-8402` | Fabricated `market_value=10000.0` per ad-hoc position; feeds `position_value`, `days_to_liquidate_10pct_adv` and all rollups against an invented ₹10,000 base |
| MEDIUM | `analytics_engine.py:3145-3150` | Period sum published as `annual_return`; hard `sharpe=0.0`/`sortino=0.0` — violates the repo's own `num_018_no_hard_zero_sub_scores` |
| MEDIUM | `analytics_engine.py:2275` | `max_drawdown = impact × 1.15` |
| MEDIUM | `optimization_service.py:695, 752` | Equal-weight "market portfolio" in BL; silent clip+renormalise decouples result from stated program |
| MEDIUM | `regime_service.py:307-311` | Transition matrix published is a prior, never fitted |
| MEDIUM | `analytics_engine.py:2228-2236, 2104-2175` | Hardcoded per-ticker and 7×7 sector stress elasticities |
| MEDIUM | `tail_risk_service.py:261-336` | "Student-t copula" is not a copula fit |
| LOW | `analytics.py:8535` | Unreachable duplicate `except HTTPException` |
| LOW | `analytics.py:8492-8530` | `/vol-cone` validates `lookback_days` but never passes it — parameter is inert |
| LOW | `india_data_service.py:403` | `ddof=0` inconsistency |
| LOW | `analytics_engine.py:3679-3681` | EWMA seed/iterate window mismatch |
| LOW | `pyproject.toml:37` | `quantlib` declared, never imported |

---

## 6. Already well-built — regression suite, not refactor queue

1. **`measure_estimate_uncertainty` gating** (`analytics_engine.py:793-1018`) — publish an interval only
   if the resampling estimator reproduces the published point value within `point_tolerance`. No library
   does this. It is the strongest correctness mechanism in the codebase.
2. **"Unmeasured ≠ zero" discipline** — `risk_scoring` (`:2857-2900`), `_risk_score_audit` (`:1319-1619`),
   `_risk_score_composition_alerts` (`:1622-1664`). 300 lines making a heuristic score self-auditing.
3. **Portfolio-return coverage contract** (`:47-293`) — drop partial-basket dates rather than renormalise,
   and publish the `renormalization_uplift` that used to ship.
4. **Holding-window provenance** (`utils/holdings.py:52-353`) — buy-price-implied start dates, per-ticker
   source disclosure, fail-loud drop.
5. **`utils/allocations.py` in its entirety** — one normalisation rule, `Decimal` half-up, auditable
   `amount = shares×price + residual`, and *rejection* rather than silent renormalisation.
6. **EVT-POT GPD fit** (`tail_risk_service.py:24-259`).
7. **OU half-life estimator** (`cointegration_service.py:668-724`).
8. **Pairs directive gate** (`cointegration_service.py:467-598`).
9. **Vol cone overlap correction + rank-withholding** (`volatility_service.py:18-99, 278-457`) — more
   statistically careful than any library.
10. **Monte Carlo chunking + goal disclosure** (`monte_carlo_service.py:199-301, 394-409`).
11. **`returns.columns`-order invariant (PA-1)** (`optimization_service.py:79-153`).
12. **Walk-forward backtester** (`backtest_service.py:92-158`).
13. **`context_audit.py`** — ~50 machine-checked payload rules.
14. **`FXRate` provenance** (`currency_service.py:38-124`).
15. **`indicators_service.py`** — thin, correct `stockstats` delegation with a genuine scale fix.

---

## 7. Symbol index (public surface)

<details>
<summary>Expand — every public function/class in <code>services/</code> and <code>utils/</code></summary>

**`analytics_engine.py` (4,119)** — consts: `PORTFOLIO_RETURN_MIN_COVERAGE:56`, `COVERAGE_TOLERANCE:60`,
`LIQUIDITY_SCORE_BANDS:308`, `LIQUIDITY_MARKET_CAP_FLOOR_INR:353`, `STRESS_DRAWDOWN_UPLIFT:363`,
`RISK_SCORE_WEIGHTS:407`, `UNCERTAINTY_BOOTSTRAP_RESAMPLES:556`, `UNCERTAINTY_POINT_TOLERANCE:565`,
`BOOTSTRAP_METHOD:570` · fns: `_active_weight_frame:63`, `active_return_coverage:82`,
`portfolio_return_coverage_block:163`, `aggregate_active_returns:255`, `ar1_autocorrelation:587`,
`effective_sample_size:608`, `moving_block_size:661`, `measure_estimate_uncertainty:793`,
`quantstats_ratio_statistics:1053`, `market_model_statistics:1155`, `engine_risk_statistics:1190`,
`_liquidity_band:1267`, `_market_cap_provenance:1276`, `_risk_score_audit:1319`,
`_risk_score_composition_alerts:1622` · class `AnalyticsEngine:1666` — `calculate_portfolio_metrics:1674`,
`forecast_volatility:1761`, `factor_exposure_analysis:1797`, `concentration_analysis:1860`,
`liquidity_analysis:1934`, `stress_test:2071`, `_sample_covariance_volatility:2346`,
`volatility_sizing:2387`, `risk_scoring:2754`, `_calculate_basic_metrics:3139`,
`_calculate_risk_metrics:3180`, `_calculate_drawdown_metrics:3199`, `_calculate_position_metrics:3318`,
`_garch_forecast:3485`, `_egarch_forecast:3569`, `_ewma_forecast:3669`, `_ols_with_published_se:3744`,
`_calculate_factor_exposures:3773` · class `GlobalAnalyticsEngine:4112`

**`optimization_service.py` (838)** — `STRATEGIES:53`, `TRADING_DAYS:54`, `STRATEGY_OBJECTIVES:62`,
`SHARPE_OBJECTIVE_STRATEGIES:69`, `MOMENT_KEYS:72`, `OPTIMIZER_POINT_TOLERANCE:180` · `_as_matrices:79`,
`_weight_vector:91`, `_moments:108`, `optimizer_estimate_uncertainty:213`, `no_estimate_uncertainty:286`,
`_objective_block:347`, `_current_portfolio_block:433`, `_solve:519`, `_cluster_var:528`,
`_hrp_weights:549`, `_min_vol:619`, `_max_sharpe:632`, `_min_cvar:652`, `_black_litterman:670`,
`optimize:759`

**`tail_risk_service.py` (500)** — class `TailRiskService:17` — `calculate_evt_pot_var_es:24`,
`calculate_bivariate_tail_dependence:261`, `calculate_tail_dependence_matrix:338`,
`calculate_full_tail_risk_suite:440`

**`monte_carlo_service.py` (436)** — `TRADING_DAYS:32`, `BLOCK_LENGTH:33`, `MAX_PATH_ELEMENTS:38`,
`MAX_AGGREGATE_ELEMENTS:42`, `MIN_HIST_OBS:49`, `METHODS:50` · `_calibrate:69`, `_model_window:81`,
`_simulate_gbm:107`, `_fit_student_t:128`, `_simulate_student_t:136`, `_simulate_bootstrap:168`,
`_checkpoint_steps:199`, `_chunk_path_count:208`, `_simulate_bounded_checkpoints:240`, `simulate_goal:327`

**`volatility_service.py` (457)** — `DEFAULT_CONE_WINDOWS:16`, `PERCENTILE_RANK_HALF_WIDTH_RULE:35`,
`EFFECTIVE_N_RULE:41` · `_effective_window_count:48` · class `VolatilityService:102` —
`calculate_rolling_realized_volatility:109`, `calculate_ewma_volatility:150`,
`forecast_garch_volatility:203`, `calculate_volatility_cone:279`

**`cointegration_service.py` (~1,330)** — `CACHE_TTL_HOURS:30`, `DECISION_TEST:46`, `MIN_PAIR_OBSERVATIONS:53`,
`SIGNAL_ZSCORE_THRESHOLD:95`, `MULTIPLICITY_CORRECTION:119` · `usable_observations_by_ticker:150`,
`assess_pair_depth:187`, `bonferroni_threshold:297`, `benjamini_hochberg_threshold:314`,
`multiplicity_report:339`, `build_pair_signal:467`, `apply_signal_directives:565`,
`compute_ou_parameters:668`, `test_johansen_cointegration:727`, `analyze_pair_cointegration:746` ·
class `CointegrationService:948` — `_get_cached_pair:961`, `scan_pairs:1120`

**`regime_service.py` (624)** — `REGIME_STATES:30`, `HMM_COVARIANCE_TYPE:31`, `HMM_RANDOM_STATE:34`,
`REGIME_FEATURE_WINDOW_DAYS:35`, `CRASH_VETO_RET21:45` · `_label_states_by_risk:48`,
`apply_crash_veto:90`, `_fit_convergence_disclosure:116`, `classify:204`, `detect_regime:432`,
`_regime_metadata:497`

**`correlation_service.py` (193)** — `compute_rolling_avg_correlation:17`,
`analyze_correlation_stability:70`

**`backtest_service.py` (237)** — `TRADING_DAYS:16`, `run_walk_forward_backtest:19`

**`indicators_service.py` (282)** — `MAX_STALE_DAYS:31`, `SUPPORTED_INDICATORS:34`, `_COLUMN_MAP:63` ·
`assert_not_stale:99`, `_compute_sync:119` · class `StaleMarketDataError:57`,
class `IndicatorsService:180` — `compute_window:194`, `verified_snapshot:244`

**`india_data_service.py` (589)** — `DATA_NSE_DIR:26`, `LIQUIDITY_ADV_LOOKBACK_SESSIONS:37` ·
`compute_amihud_illiquidity:40`, `compute_days_to_liquidate:59` · class `IndiaDataService:85` —
`ingest_bhavcopy_records:132`, `ingest_institutional_flow:211`, `get_institutional_flows:302`,
`get_delivery_anomalies:372`, `calculate_portfolio_liquidity_limits:445`

**`currency_service.py` (398)** — `FALLBACK_USD_INR:27` · class `CurrencyUnavailableError:31`,
class `FXRate:38`, `coerce_live_fx_rate:76`, class `CurrencyConversionService:127` —
`get_exchange_rate:155`, `convert_amount:230`, `convert_amount_with_provenance:249`,
`format_currency_indian:282`, `get_exchange_rate_info:291`, `_fetch_exchange_rate:325` ·
`convert_portfolio_value:385`, `format_portfolio_value_indian:389`

**`screener_service.py` (350)** — `DEBT_FREE_MAX_DE_RATIO:29` · class `ScreenerService:65` —
`STRATEGIES:79`, `get_available_strategies:107`, `run_screen:182`, `_enforce_debt_free:280`,
`run_custom_screen:300`

**`equity_research_service.py` (305)** — class `EquityResearchService:30` — `get_full_profile:36`,
`get_shareholding:127`, `get_concalls:195`, `get_custom_ratios:215`, `export_excel_model:262`

**`company_data_service.py` (429)** — `_yf_retry:45` · class `CompanyDataService:72` —
`get_fundamentals:122`, `get_financial_statements:309`, `get_insider_transactions:399`

**`data_service.py` (~1,860)** — `_accept_vendor_frame:114`, `canonical_ticker:199` ·
class `DataService:227` — `get_coverage:431`, `fetch_historical_data:577`, `fetch_quote:886`,
`fetch_ohlcv_batch:1048`, `validate_ticker:1117`, `get_corporate_actions:1158`, `check_data_integrity:1789`

**`cache_service.py` (468)** — class `ProviderError:36` (+5 subclasses), `get_runtime_cache_snapshot:112`,
`get_cache_generation:117`, `advance_cache_generation:122`, `cache_generation_is_current:133`,
`clear_service_memos:137`, class `CacheService:231`, `clear_market_data_cache:487`,
`invalidate_market_data_for_source_change:536`

**`ai_context_service.py` (2,691)** — orchestration, **no quant**; class `PortfolioContextService:1644`

**`utils/holdings.py` (489)** — `MIN_ANNUALIZE_DAYS:35` · `effective_start:52`, `holding_window:217`,
`annualizable:250`, `apply_annualization_gate:356`, `coerce_holding_date:471`

**`utils/allocations.py` (728)** — `WEIGHT_NORMALIZATION_RULE:81`, `SHARE_ROUNDING_RULE:87`,
`TRADE_RECONCILIATION_RULE:90` · `half_up:174`, `gross_exposure:201`, `normalization_block:206`,
`normalize_rebalance_weights:286`, `build_sizing_basis:449`, `build_trade_instructions:563`

</details>
