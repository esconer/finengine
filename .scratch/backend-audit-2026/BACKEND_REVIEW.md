# FinEngine Backend — Comprehensive Line-by-Line Audit
**Date:** 2026-09-03 | **Scope:** `backend/app/**` + `backend/main.py` (read-only, no code changed)
**Method:** 5 parallel subagent reviewers, each reading assigned files fully. This doc synthesizes their reports verbatim into one action plan.
**Goal under test:** bug-free, financially/mathematically/logically sound backend; efficient code; path to Bloomberg / Jane Street / JPMorgan-grade terminal.

**Prior context consulted:** `CONTEXT.md`, `PROJECT.md`, `.scratch/` (advanced-analytics t01-t32, bfinance-integration, browser-verification BVA-01..08, bug-sweep BS-01..06, portfolio-audit PA-01..03, quality-hardening QH-01..13, terminal-ux UA-01..06, page_5..10 audits, session logs).

---

## 0. Executive verdict

**The backend is not yet bug-free, nor uniformly financially sound. Do not call it Bloomberg-grade yet.**

| Category | Count | Meaning |
|---|---|---|
| **P0 (wrong numbers / crash / data loss)** | **9** | Must fix before any institutional claim: HRP allocation, regime price/return confusion, coint cache collision, `/liquidity` NameError, empty-portfolio crash, mock-200 envelopes hiding outages, US-ticker forcing, analytics blind-insert cache, screener universe/cache + debt-free mislabel |
| P1 (material bias / misleading / DoS / performance-killer) | ~45 | Fix in next 2 sprints (Sortino, EWMA, CVaR VaR, target-vol, risk-score R², backtest cost/Sharpe, HMM priors/lookahead, EVT mock, copula df, ticker length/unique, WS auth, Alembic drift, etc.) |
| P2 (hygiene / contract drift / efficiency) | ~40+ | Backlog with fix snippets below |

**What is genuinely SOUND (keep):** GBM drift `(mu-0.5σ²)dt`, Student-t moment-match, StationaryBootstrap chaining, Parkinson estimator, GARCH ×100 rescale + Normal VaR/ES `1.645/2.06·sqrt(h/252)`, EVT-POT GPD VaR/ES formulas, t-copula `λ` formula, OU `θ/half-life` main branch, Johansen trace test structure, HHI/`N_eff`/Gini, max-drawdown `cumpeak` math, CAGR geometric compounding, walk-forward train/test split (no lookahead), bulk_add 8-step pipeline, sem-5 concurrent fetch pattern, FX single-flight lock pattern, SQLite `ON CONFLICT(ticker,date)` upsert for timeseries.

**What is systematically UNSOUND:** HRP bisection, EWMA implementation, Sortino denominator, CVaR VaR constraint, `target_volatility` ignored, risk-score factor leg, backtest turnover/Sharpe, HMM feature/prior/lookahead chain, EVT mock fallback, copula df averaging, Piotroski F6/F8 proxies + leverage proxy, EV missing cash, screener strategy definitions + universe handling, AI dossier grounding. Plus cross-cutting: mock-200 error envelopes, ticker validation/DB length drift, shared-session concurrency, cache stampede, WS auth, Alembic bypass.

> No files were changed in this audit. All line numbers are `backend/app/...` unless noted as `backend/main.py`.

---

## 1. Inventory (what was reviewed)

### 1.1 Quant core — `services/analytics_engine.py` (1375 LOC), `optimization_service.py` (281), `backtest_service.py` (163)

`analytics_engine.py`: `__init__` 38-39, `calculate_portfolio_metrics` 41-94, `forecast_volatility` 96-130, `factor_exposure_analysis` 132-194, `concentration_analysis` 196-258, `liquidity_analysis` 260-387, `stress_test` 389-563, `volatility_sizing` 565-677, `risk_scoring` 679-787, `_calculate_portfolio_returns` 791-805, `_calculate_basic_metrics` 807-843, `_calculate_risk_metrics` 845-862, `_calculate_drawdown_metrics` 864-880, `_calculate_return_distribution` 882-893, `_calculate_position_metrics` 895-934, `_garch_forecast` 936-974, `_egarch_forecast` 976-1014, `_ewma_forecast` 1016-1055, `_calculate_factor_exposures` 1057-1144, `_calculate_r_squared` 1146-1167, `_calculate_adjusted_r_squared` 1169-1190, `_calculate_max_drawdown` 1192-1202 (dead), `_simulate_stress_drawdown` 1204-1223 (dead), `_estimate_recovery_time` 1225-1242 (dead), `_empty_*` 1246-1364, `GlobalAnalyticsEngine` 1368-1375. Deps: numpy/pandas/scipy.stats/sklearn.PCA(unused)/quantstats(unused)/arch/statsmodels. Global `warnings.filterwarnings('ignore')` + bare `except:` throughout.

`optimization_service.py`: `_as_matrices` 39-43 (`mu=mean×252`, `cov×252`), `_hrp_weights` 46-100, `_min_vol` 103-113 (CLARABEL + psd_wrap, long-only sum-to-1), `_max_sharpe` 116-131 (homogenized tangency), `_min_cvar` 134-149 (Rockafellar-Uryasev β=0.95), `_black_litterman` 152-234 (`π=δΣw`, `Ω=diag(PτΣPᵀ)`, posterior), `optimize` 237-281 (dispatch, clip+renorm, ex-post diagnostics).

`backtest_service.py`: `run_walk_forward_backtest` 18-163 (anchored walk-forward, `train=[t-lookback:t)`, `test=[t:next)`, turnover cost day-0, cumprod equity, CAGR/vol/Sharpe/MDD/Calmar, daily-rebalanced equal-weight benchmark).

### 1.2 Quant suite — `regime_service.py` (260), `monte_carlo_service.py` (217), `volatility_service.py` (330), `tail_risk_service.py` (332), `correlation_service.py` (169), `cointegration_service.py` (378)

`regime_service.py`: `_label_states_by_risk` 24-43, `classify` 46-208 (bench price → ret21/vol21 → StandardScaler → GaussianHMM k=3 → predict/proba → stats), `detect_regime` 211-259 (async, `to_thread`), consts `REGIME_LABELS_WORST_TO_BEST`, `MIN_OBSERVATIONS=200` 20-21.
`monte_carlo_service.py`: `_calibrate` 39-48, `_simulate_gbm` 51-68, `_simulate_student_t` 71-98, `_simulate_bootstrap` 101-126 (StationaryBootstrap BLOCK=21), `_fan_from_paths` 129-149, `simulate_goal` 152-217, consts 31-36 (`TRADING_DAYS=252`, `BLOCK_LENGTH=21`, `DEFAULT_PATHS=2000`, `MAX_PATHS=20000`, `MIN_HIST_OBS=60`).
`volatility_service.py`: `calculate_rolling_realized_volatility` 25-63, `calculate_ewma_volatility` 65-108, `forecast_garch_volatility` 110-183, `calculate_volatility_cone` 185-330 (windows 10/21/63/126/252).
`tail_risk_service.py`: `calculate_evt_pot_var_es` 24-138 (95% threshold, genpareto floc=0), `calculate_bivariate_tail_dependence` 140-195, `calculate_tail_dependence_matrix` 197-277, `calculate_full_tail_risk_suite` 279-332.
`correlation_service.py`: `compute_rolling_avg_correlation` 18-68 (rolling 60 corr, `2/N(N-1)` avg), `analyze_correlation_stability` 71-149 (90th/75th/median, break logic), thin wrappers 156-169.
`cointegration_service.py`: `compute_ou_parameters` 28-82, `test_johansen_cointegration` 85-101 (det_order=0, k_ar_diff=1, trace r=0 95%), `analyze_pair_cointegration` 104-215 (sync/dropna, <30→None, coint default trend=c autolag=aic, polyfit hedge β, spread z ±1.5), `_get_cached_pair` 231-262 / `_set_cached_pair` 264-289 / `scan_pairs` 291-378 (O(N²), sequential await).

### 1.3 Data layer — `data_service.py` (922), `benchmark_service.py` (108), `alpha_vantage_service.py` (340), `company_data_service.py` (332), `india_data_service.py` (302), `currency_service.py` (286), `cache_service.py` (194), `indicators_service.py` (228)

Full function maps in §4 table; key contracts: 3-tier cascade bfinance→yfinance→AV; `canonical_ticker` 37-55; `_normalize_indian_ticker` 71-81; `_normalize_yfinance_data` 547-606 (TitleCase→lowercase); `_get_cached_data` 608-675; `_store_timeseries_data` 677-739 (`ON CONFLICT(ticker,date)` ✅); `BenchmarkService.ensure_history/get_benchmark_df/get_returns` 50-91; AV `to_av_symbol` 44-54, `KeyPool.acquire` 141-149, `_make_request` 197-251, `fetch_daily_ohlcv` 255-291; company `get_fundamentals` 93-200 / `get_financial_statements` 210-294 / `get_insider_transactions` 298-322; india `compute_amihud` 29-45 / `compute_days_to_liquidate` 48-55 / `ingest_bhavcopy` 65-106 / `ingest_flow` 108-141 / `get_flows` 143-168 / `get_delivery_anomalies` 170-217 / `calculate_portfolio_liquidity_limits` 219-302; currency `get_exchange_rate` 29-63 (single-flight lock ✅ pattern) / `_fetch_exchange_rate` 157-201 / `format_currency_indian` 107-129; cache `get/set_cached_analytics` 24-84 / `log_fetch_attempt` 86-111 / `clear_expired_cache` 113-137 / `get_cache_stats` 139-183; indicators `_ensure_date_column` 68-78 / `_clean_dataframe` 81-91 / `_compute_sync` 114-135 (SMA/EMA/MACD/RSI/Boll/ATR/VWMA/MFI trailing-only) / `compute_window` 149-196 / `verified_snapshot` 198-228.

### 1.4 API + DB — `api/analytics.py` (1819, 22 routes), `api/portfolio.py` (1091, 9 routes), `api/data.py` (423, 12 routes), `api/websocket.py` (346), `api/equity_research.py` (215, 11 routes), `models/database.py` (204, 8 tables), `models/schemas.py` (550, 30+ schemas), `db/database.py` (93), `config.py` (58), `main.py` (180)

Router prefixes (`main.py:119-147`): `portfolio→/api/v1/portfolio`, `data→/api/v1/data`, `analytics→/api/v1/analytics`, `websocket→/api/v1/ws`, `equity_research→/api/v1`. Helpers: `analytics.resolve_allocation:61`, `_load_portfolio_allocation:160`, `_fetch_price_series_dict:130` (sem-5 ✅), `_price_series:97`, `_q:85` (quantstats guard), `_build_wide_returns:1073`. Portfolio: `router:35`, `_TICKER_PATTERN:32`, `add:150`, `bulk_add:269` (best-structured 8-step flow), `_validate:507`, `get:540`, `update:604`, `delete:695` (renorm ✅), `export_csv:747`, `normalize:800`, `rebalance:846`, `_suggestions:952`, `_update_prices:1057` (stale 15m sem-5). Models: `PortfolioPosition:12` (`ticker String(10)` ⚠️, no unique ⚠️), `StockTimeseries:40` (UQ(ticker,date) ✅), `AnalyticsCache:71`, `FetchLog:93`, NSE ×4. Config defaults: `sqlite+aiosqlite:///./data/daisy.db`, `debug=true` ⚠️, origins localhost only.

### 1.5 Research terminal — `equity_research_service.py` (295), `screener_service.py` (207), `ai_dossier_service.py` (112)

`equity_research`: `_normalize` 22-24 (`DataService(None)` hack ⚠️), `get_full_profile` 37-123, `get_shareholding` 125-188, `get_concalls` 190-207, `get_custom_ratios` 209-251, `export_excel_model` 253-285. Proxies `bf.Ticker._ensure_profile()` (private API ⚠️) + `custom_ratios/piotroski/graham`. Upstream audited: `bfinance/market/ratios.py`, `ticker.py`, `screens.py`, `market/quotes.py`, `market/derivatives.py`, `ai/context.py`, `ai/prompts.py`, `utils/excel.py`.
`screener`: `_cache` 25 + TTL 300 26, `STRATEGIES` 28-54 (5 lambdas), `get_available_strategies` 56-65, `run_screen` 67-124, `run_custom_screen` 126-197. Upstream `DEFAULT_UNIVERSE` 50 large-caps.
`ai_dossier`: `_normalize` 17-19, `get_ai_dossier` 32-50, `get_investment_memo_prompt` 52-70 (`custom_instructions` verbatim ⚠️), `get_forensic_audit_prompt` 72-86, `get_concall_prompt` 88-102 (no route — dead), singleton 105-112.

---

## 2. Financial / mathematical soundness — verdict per function

### 2.1 Analytics engine + optimization + backtest

| Function | Verdict | Reason |
|---|---|---|
| `calculate_portfolio_metrics` | FLAWED | Fixed-weight daily-rebalanced returns undocumented; leading-NaN `ffill+bfill+fillna(0)` 62-66 injects 0-returns pre-listing (inception/survivorship bias); extra-ticker weights become cash via `.get(col,0)` 796 without renormalizing |
| `_calculate_basic_metrics` annualization/Sharpe | SOUND (arithmetic) | `mean×252`, `std×sqrt(252)`, Sharpe correct; note geometric CAGR differs under vol drag (Lo 2002) |
| Sortino 828-830 | FLAWED | Uses `std(negatives)×sqrt(252)` MAR=0 while numerator uses rf. Correct: `sqrt(mean(min(0,r-target)²))×sqrt(252)` (Sortino & Price 1994). Inflates ratio |
| Historical VaR/CVaR 852-855 | SOUND w/ caveat | `VaR=p5`, `ES=mean(r≤VaR)` correct sign (negative=loss); horizon (daily) unlabeled |
| Drawdown 870-874 | SOUND | Textbook cumpeak |
| Return distribution | FLAWED contract | Live `kurtosis` excess (Normal 0) vs `_empty_metrics:1253` Pearson `3` — mixed conventions |
| `_calculate_position_metrics` 909-914 | SOUND w/ caveat | Active-history via `raw_prices` correctly avoids zero-dilution (good); inherits Sortino flaw; creates portfolio≠sum(positions) inconsistency |
| `_garch/_egarch_forecast` | SOUND w/ caveats | ×100 + `rescale=False` + `sqrt(var×252)/100` correct arch idiom; `VaR=-σ·1.645·sqrt(h/252)`, `CVaR=-σ·2.06·sqrt(h/252)` correct Normal 95%; caveats: `clip(±20%)` biases σ↓, `clip σ [0.05,1.20]` hides extremes, Normal ignores skew/kurtosis (use `dist='t'` or filtered HS) |
| `_ewma_forecast` 1025-1026,1034 | FLAWED | Double-smooths (`rolling(30).std().ewm().mean()²`); adds spurious mean-reversion. RiskMetrics 1996: `σ²_t=λσ²_{t-1}+(1-λ)r²_{t-1}`, flat h-step forecast. `λ=0.94` itself sound |
| Factor OLS `r=α+β·bench` | FLAWED | OLS sound CAPM; flaws: price/return detector `(abs>1).any()` 174 misclassifies sub-₹1 prices; regression includes zero-filled pre-listing rows (β→0 attenuation) while `data_pts` counts non-zero only; no robust SEs/t-stats; 3 separate OLS fits wasteful |
| adj-R² `max(0,·)` 1187 | FLAWED minor | Hides worse-than-mean fit |
| `concentration_analysis` HHI 229, N_eff 232 | SOUND w/ naming caveat | `HHI=Σw²`, `N_eff=1/HHI`, normalized `((1-HHI)/(1-1/N))×100` 236 satisfies single-holding→0% ✅; misnomer: `diversification_ratio=N_eff/N` 237 is not Choueifaty & Coignard `w′σ/σ_p` — rename `effective_share` |
| `liquidity_analysis` | FLAWED methodology | `Volume×Close` + mcap tiers, invented spreads/buckets, `max(1e9,turnover×250)` cap, equal-mean score are ad-hoc, not Amihud/Hui-Heubel/empirical spread; docstring "empirical spreads" false; equal-weight ignores position size |
| `stress_test` 541-548 | FLAWED | `shock×sector×vol_adj[0.85,1.25]`, clamp `[-0.75,-0.02]`, `MDD=1.15×impact`, hardcoded `MAFANG/MIDCAPIETF/SELECTIPO` 525-530, historical labels without replay, `recovery_months` config lookup. Helpers `_calculate_max_drawdown/_simulate_stress_drawdown/_estimate_recovery_time` dead |
| `volatility_sizing` inverse-vol 637-641 | SOUND formula, CRITICAL omission | `w∝1/σ` sound risk-parity-lite; `portfolio_value=None→0` trades 655 correctly avoids fabricating totals; cov-based vol sound. BUT `target_volatility` 570 never used — weights always sum to 1 despite "with target volatility scaling" 672 (false). Not full ERC (no `RC_i=w_i(Σw)_i/σ_p`, Tasche 2000) though `corr` computed; `round(4)` can break Σw=1; `int(shares)` truncates; vol clip hides tails |
| `risk_scoring` | FLAWED | Scale compression (`(1-R²)×100` cap 30 maxes for R²<0.7; `vol×100` maxes >30%); thresholds 15/25 arbitrary; **calls `factor_exposure_analysis(price_data)` without benchmark 728 → R²=0 always → factor_score=30 always**; stateful `self._previous_risk_score` 754-763 on shared singleton = cross-user bleed + async race; Euler `RC_i` never computed despite risk-parity claims |
| `_hrp_weights` | FLAWED (P0) | `dist=sqrt(0.5(1-r))` + single linkage sound (López de Prado 2016); allocation UNSOUND: weight-sum rescale 93-98 not cluster variance `w′Σw`; chunking `[i[k:k+len//2]]` 87 only bisects powers of 2 (N=3 → no bisection, raw IVP stays); init `1/diag(Σ)` conflates inverse-variance with inverse-vol; no NaN guard for flat series |
| `_min_vol` | SOUND | Long-only fully-invested GMV, psd_wrap + CLARABEL sound (Markowitz 1952); no caps documented as limitation |
| `_max_sharpe` | SOUND w/ gap | Homogenization `min y′Σy s.t. (μ-rf)′y=1` sound (Cornuejols & Tütüncü); all-excess≤0 guard correct; missing `raw.sum()≤0` guard → divide-by-zero |
| `_min_cvar` | FLAWED | Rockafellar-Uryasev LP structure sound; `alpha=cp.Variable(neg=True)` 139 FLAWED — VaR must be free (positive-loss VaR cut off → suboptimal/infeasible); β=0.95 hardcoded, never forwarded |
| `_black_litterman` | SOUND w/ caveats | `π=δΣw`, `Ω=diag(PτΣPᵀ)` (He-Litterman), posterior `μ_bl/Σ_bl` sound (BL 1992); τ=0.05, δ=2.5 standard; long-only tangency + min-vol fallback defensible; caveats: Q units (annualized excess) undocumented, no Idzorek confidence, pinv symmetry |
| `optimize` dispatch | SOUND w/ nits | clip+renorm enforces long-only/sum-to-1; `round(6)` can drift Σ≠1 by N·5e-7 |
| `run_walk_forward_backtest` | FLAWED (cost+Sharpe) | Walk-forward indexing sound (no lookahead); geometric cumprod + CAGR + peak drawdown sound; benchmark is daily-rebalanced EW (unlabeled). Flaws: turnover `Σ|Δw|` 78 double-counts one-way (10% A→B = 0.2) → cost ~2×; Sharpe from geometric CAGR 129-130 (standard: `mean×252`, Sharpe 1966; Lo 2002) + `np.std ddof=0` vs pandas ddof=1; cost lumped additively day-0 (use `(1-c)(1+r)-1`); `equal_weight` branch 63 absent from STRATEGIES |

Refs: Sharpe 1966; Sortino & Price 1994; RiskMetrics 1996; Bollerslev 1986; Nelson 1991; López de Prado 2016; Markowitz 1952; Rockafellar-Uryasev 2000; Black-Litterman 1992 / He-Litterman 1999 / Idzorek 2007; Tasche 2000; Maillard et al. 2010; Amihud 2002 (missing).

### 2.2 Regime / Monte Carlo / Vol / Tail / Correlation / Coint

| Function | Verdict |
|---|---|
| `_label_states_by_risk` 24-43 | FLAWED fragile + dead branch: `signed_vol` 32-33 never created (classify makes `ann_ret/cagr/ann_vol/days_pct`); falls to `cagr` sort — mislabels low-vol grind vs high-vol rally; assumes exactly 3 (`[2]` IndexError if n≠3) |
| `classify` 46-208 | NEEDS FIX: features `ret21=log(close/close.shift(21))` + `vol21=rolling(21).std·sqrt252` — docstring claims signed-vol + 200DMA (false); overlapping 21d induces MA(20) autocorr violating HMM independence; vol level non-stationary; `StandardScaler` full-sample = lookahead; `init 0.96` + `params="mc"` = fake sticky prior (re-estimated by EM, no `transmat_prior`; not Fox et al.); single restart seed 100 local optimum; `covariance_type="full"` no `min_covar` near-singular; CAGR `prod(1+r)^(252/n)-1` correct; `ann_v` = mean of rolling vols (double-smoothed; correct: `std(1d in state)·sqrt252`); `predict/predict_proba` smoothed → lookahead in `recent_history/current_probs` (use filtered `_forward_lattice` for last bar); Parkinson `sqrt((log(H/L)²)/(4ln2))·sqrt252` + clip/guard correct; EWMA span-10 overlay OK |
| `detect_regime` 211-259 | FLAWED Series path: fallback passes return Series 218-228, `classify` treats as price (`pct_change` of returns = nonsense). `to_thread` works non-idiomatic; `tz_localize(None)` fragile; portfolio CAGR geometric correct |
| `_calibrate` MC 39-48 | SOUND w/ caveat: `mean×252`, `std(ddof=1)·sqrt252` correct simple; GBM log-drift overstates by ~0.5σ² — fit on `log1p(r)` ideally |
| `_simulate_gbm` 51-68 | SOUND: `drift=(mu-0.5σ²)dt`, `diffusion=σ√dt`, cumsum+exp textbook. Bug: `steps=horizon×252` float → TypeError |
| `_simulate_student_t` 71-98 | SOUND w/ caveats: `t.fit` MLE df, floor 2.1 (variance undefined ≤2), `analytic_std=scale·sqrt(df/(df-2))` correct (avoids poisoning), `clip ±8z` + `clip -0.95` + log1p/cumsum/exp correct; caveats: loc/scale from unfloored fit but sampling floored; ±8 truncates the tail t is for; reported `df_` unfloored (document) |
| `_simulate_bootstrap` 101-126 | MATH SOUND, API FRAGILE: StationaryBootstrap(21) = Politis-Romano p=1/21 geometric, preserves autocorr/tails ✅; chaining `ceil(steps/n)` + `concatenate[:steps]` + cumprod correct; fixed 21 not Politis-White optimal (defensible); `seed=rng Generator` may TypeError on older arch (pass int) |
| `_fan_from_paths` / `simulate_goal` | SOUND w/ caveats: half-year checkpoints, p5/25/50/75/95, `prob_success=mean(terminal≥target)` correct; `expected_shortfall=mean(failing)-target` (document negative-vs-target); silent `num_paths` clamp; no fees/inflation (out of scope) |
| `calculate_rolling_realized_volatility` | SOUND: `rolling.std(ddof=1)·sqrt252` |
| `calculate_ewma_volatility` | SOUND w/ caveat: `(1-λ)λ^{N-1-t}` normalized, `Σw·r²` correct zero-mean RiskMetrics λ=0.94; renormalization deviates slightly from recursive; n=0→0.20 / n=1→|r|√252 arbitrary |
| `forecast_garch_volatility` | SOUND w/ GAPS: `r×100`, `arch_model(Garch p=q=1, mean=Zero, dist=normal, rescale=False)` + `sqrt(mean(var)×252)/100` correct; gaps: `dist=normal` misses fat tails (use `t`/`skewt` for India); **no ±20% winsorization** (circuit-breaker breaks/inflates); no `α+β<1` stationarity check; <30→EWMA fallback good |
| `calculate_volatility_cone` | SOUND w/ caveats: windows standard; quantiles correct; `sorted()` monotonicity guard masks bugs; single-obs `0.8/0.9/1.1/1.2×` + empty `0.85-1.15×baseline` synthetic (flag `insufficient_data`, don't fabricate); baseline `0.20` arbitrary; `target_w=windows[0]` unsorted-input bug |
| `calculate_evt_pot_var_es` | SOUND formulas, mocked fallback: losses `-r`, `hist_var=p99`, `hist_es=mean(≥VaR)`, `u=p95`, excesses, `genpareto.fit(floc=0)`, `ξ∈[-0.5,0.95]` clip (log it), `VaR=u+(β/ξ)(ratio^{-ξ}-1)`, exp limit, `ES=(VaR+β-ξu)/(1-ξ)` (McNeil) ✅, floors `VaR≥max(u,0.9·hist)`, `ES≥1.05·VaR` (5% wedge), sign `-(loss)` consistent, `is_fat_tailed` reasonable. **P1: n<20 returns hardcoded `-0.0385/-0.0492/0.0185/0.18/0.0075`** — violates live-only hygiene |
| `calculate_bivariate_tail_dependence` | FORMULA SOUND, ESTIMATION APPROXIMATE: `λ=2·t_{ν+1}(-√((ν+1)(1-ρ)/(1+ρ)))` correct; `ν=mean(marginal dfs)` heuristic — true copula ν needs PIT-uniform MLE or Kendall inversion, not marginal平均; `ρ≥0.999→1.0` discontinuous after `±0.9999` clip |
| `calculate_tail_dependence_matrix` | SOUND w/ caveat: symmetric fill, diag 1.0 (display), buckets 0.50/0.35/0.20 arbitrary-reasonable; fallback top5 labels LOW pairs as `high_tail_risk_pairs` — misleading (return `[]` + separate `top_pairs`) |
| `compute_rolling_avg_correlation` | SOUND w/ caveats: `ρ̄=(2/N(N-1))Σρ` via `rolling(60).corr` + mean correct EW avg; `min_periods=30` noisy early; no Fisher-z (`atanh`→mean→`tanh`) — biased when heterogeneous |
| `analyze_correlation_stability` | SOUND w/ caveat: 90th/75th/median + break/alert logic correct diversification-breakdown; in-sample threshold (current in distribution — use leave-one-out); `>` vs `>=` off-by-one at exactly 90th |
| `compute_ou_parameters` | SOUND w/ ONE WRONG BRANCH: `dz/z_lag`, `var<1e-12→None` RankWarning guard ✅ (prompt invariant met), `polyfit→γ`, `γ≥0→None` ✅, `-1<γ<0: θ=-ln(1+γ)`, `t½=ln2/θ` ✅. **Branch `-2<γ≤-1` wrong: `θ=-ln(2+γ)` typo + hardcoded `half_life=1.0` (undefined for oscillatory overshoot) — return `(None,None)` + `oscillatory` flag** |
| `test_johansen_cointegration` | SOUND w/ gaps: `coint_johansen(det_order=0,k_ar_diff=1)`, `lr1[0]>cvt[0,1]` trace r=0 95% ✅; gaps: fixed lag (AIC-select), det_order undocumented, no I(1) ADF pre-test (two stationary series pass r=0 rejection → false positive) |
| `analyze_pair_cointegration` | SOUND w/ caveats: sync+dropna, `<30→None` (low power, prefer 100+), `coint(trend=c,autolag=aic)` correct EG, `polyfit(p_b,p_a)` hedge β correct (spurious if not coint — fine to report), spread + in-sample `z=(last-mean)/std` (live: rolling ex-current), signals ±1.5 standard |
| Coint cache `_get/_set/scan` | FUNCTIONAL BUT P0 COLLISION + PERF: key `coint_{a}_{b}_{date}` order-sensitive; **DB `ticker=f"{a[:4]}_{b[:4]}"` + `metric=coint_{date}` collides (`RELIANCE`/`RELCAP`→`RELI`), last-write-wins evicts pairs**; `utcnow()` naive-deprecated; sequential await O(N²) EG+Johansen slow |

### 2.3 Data / infra correctness

| Check | Verdict |
|---|---|
| 3-tier cascade | Mostly correct, inconsistent: `fetch_historical_data` 129-169 + `fetch_quote._sync_fetch` 197-256 + company fundamentals/statements implement bfinance→yfinance→AV; `validate_ticker` 379-380 + `get_corporate_actions` 402-406 + `get_insider_transactions` skip tiers entirely |
| Ticker normalization | Buggy: `canonical_ticker` 43-55 passes `^NSEI`/`=X` ✅ but L51 substring (`in` not suffix), forces `.NS` on every bare symbol (`AAPL`→`AAPL.NS` wrong, currency INR/NSE wrong); no regex for `3MINDIA.NS`/`MOTHERSON.NS`/`BAJAJ-AUTO.NS`/`500112.BO`; `.BO` numeric works by accident |
| TitleCase vs lowercase OHLCV | Split-brain, defensively handled: fresh yfinance TitleCase normalized 577-585; cache lowercase 653-668; AV lowercase 273-281; indicators maps back for stockstats 62-78; benchmark accepts both 26-29. Fragile — raw `hist['Close']` 250 breaks on MultiIndex |
| ffill/bfill vs dropna | Inconsistent: `data_service` 599 `dropna()` correct; `indicators._clean_dataframe` 90 `ffill().bfill()` fabricates leading prices/volume; `india_data` 253-254 `ffill/fillna(0)` safe-ish but leading-NaN ADV bug remains |
| Zero-padding vs active-history (Sharpe) | Not in these 8 files (verify analytics layer); `verified_snapshot/compute_window` correctly emit `None` not 0 for warmup 186-187 — good precedent |
| Date alignment inner-join | Not implemented here: single-ticker fetchers, `fetch_ohlcv_batch` 348-354 returns uneven frames unaligned; `benchmark._close_series` 33-40 no sort/dedupe — downstream must `concat(join=inner).dropna()` |
| SQLite cache/upsert/TTL/stampede | Mixed: `StockTimeseries ON CONFLICT(ticker,date)` 712-727 atomic ✅; `AnalyticsCache` 68-78 blind-insert (dup→`MultipleResultsFound`→perpetual miss); NSE read-then-write races; 4 clocks (300s hardcode vs `settings.cache_ttl_minutes` vs 30-min FX vs 60-min analytics); stampede: only FX has single-flight 50; df/analytics none; `fetch_ohlcv_batch` shares one `AsyncSession` across 5 coroutines (unsafe) |
| FX single-flight | Correct pattern (`_refresh_lock` + double-check 50-53); bugs inside fetch (history skipped, stale `83.0` cached as live, unknown pairs →`1.0`) |
| AV rotation pool | Design correct (round-robin, demotion, budgeting); races (no lock, `drop_invalid` mid-iteration, local-today vs AV ET midnight, rejects not `spend()`-ed) |
| NSE bhavcopy/delivery/FII-DII | Fragile: `float()/int()` on `"-"/""/None` 88-98 aborts whole batch; dedupe ignores `series` (EQ vs BE); delivery population-std + one-sided z + N+1 selects; FII/DII read-modify-write no upsert |
| stockstats lookahead | No shift — correctly causal for display; backtest consumers must `shift(1)` (undocumented); SMA200 warmup under-provisioned |
| Corporate actions | Not adjusted, only warned: `auto_adjust=False` preserves Adj Close ✅; AV mirrors `close→adj_close` unadjusted; `>50%` flag 773-778 still stores unadjusted (splits false-positive); no split detection/winsorization |

### 2.4 API / DB contracts

Holdings-truth: PASS with 2 exceptions (`stress-test:713-714` ignores `request.tickers`; `liquidity-limits:1697-1702` dummy `price=100` for ad-hoc). Weight renorm: partial (`resolve_allocation:74-75`, `_load:181-189`, `forecast:376-380`, `delete:722-729`, `normalize:822-824`, `rebalance:875` ✅; `add:215-228` no global renorm; `bulk_add:410-416` renorms new batch only; `rebalance:875` no keys⊆holdings check). Zero-state 100%: partial (`optimize/run:1296-1309` `{t:1.0}` ✅, correlation/coint single guards ✅; `add:150` persists `0.2` on empty, no `→1.0` branch). `total_weight` NameError class: no live NameError in `portfolio.py` (all defined); **live NameError in `analytics.py:639,647` (`inspect` unimported) — every `/liquidity` with data → 500**. Error envelopes: FAIL — 9 analytics routes return `200` + mock constants (`0.20/0.22/-0.032/-0.047/25/7.8`) + `error` key instead of 404/503/500; later routes (`tear-sheet:1116`, `risk-contribution:1211`) correctly 404; no Yahoo crumb-401 mapping (surfaces 500 except `fundamentals→503`); `PUT /config` lies `updated:true` unpersisted (should be 501). Ticker validation: split — `portfolio._TICKER_PATTERN:32` `^[A-Z0-9\-\&\.]{1,20}$` accepts all required formats + `bulk_add:308` enforces ✅; BUT `ValidateTickerRequest max_length=10` rejects 12-char `BAJAJ-AUTO.NS`/`MOTHERSON.NS` 422, DB `String(10)` truncates on Postgres, `add:150` never applies regex, analytics/data/equity/update/get/delete no regex. Pagination: mostly absent (portfolio GET, performance-history ≤1825 rows, correlation 756pts, coint O(n²), concalls 40+, export_csv full table, batch/refresh unbounded; underwater cap 250 ✅, screens cap 100 ✅). Auth: absent (single-user implicit; `WS ?token` ignored, `POST /broadcast` open spam, config/rebalance/delete unguarded — safe only on localhost, undocumented). WS tick: redundant (3 sessions + 3 scans per 30s + 1-yr scan + fresh engine per tick; stored vs live weight inconsistency; no diff/heartbeat; client_id collision; check-then-act race). CORS/middleware: pass dev, fragile prod (localhost origins, `health:158` hardcodes `development`, `reload:true`). Alembic vs init_db: FAIL — `lifespan:60` only `create_all`, never `alembic upgrade head` though `migrations/` exists; relative `./data/daisy.db` + `makedirs("data")` CWD-dependent; `echo=debug` default true logs all SQL. Pydantic v2: legacy compat (`validator`, `.dict()`, `min_items`, `Field(env=)`, `class Config` — works via shims, breaks on v3). Rounding: partial (6dp good in `_q`, risk-contribution, performance; 4dp/2dp/unrounded elsewhere; `bulk_add:412` `1e-9` vs spec `1e-4`; no rounding-residual re-correction). NaN/Inf: FAIL — only `_build:1085` + `forecast:371` sanitize; `Inf` from zero-price never replaced; `round(float(nan))` emits illegal JSON NaN; `int(volume)` on NaN→500; `alpha` can be NaN.

### 2.5 Research terminal (first audit of this surface — no prior `.scratch/` coverage)

Piotroski: F1/F3/F4 correct; F5 leverage `Borrowings_curr<=prev` WRONG proxy (paper: Δ(LTD/AvgAssets)<0; `<=` awards flat; ignores balance-sheet growth); F6 `OtherAssets/OtherLiab` WRONG proxy (should be CurrentAssets/CurrentLiabilities; `>=` lenient); F7 `EquityCapital<=prev` partial (ignores premium/buybacks/splits — use shares outstanding); F8 `(Sales-Expenses)/Sales` WRONG proxy (uses total incl. interest/tax, not COGS/GrossProfit; conflates financing); F9 direction correct, denominator fragile; TTM `columns[-2] if last==TTM` fragile string match; `empty/len<2 → score 0` indistinguishable from genuine worst (return `None` + `insufficient_data`). Service drops `piotroski_breakdown` (frontend "9-point modal" has no data).
Graham `sqrt(22.5·EPS·BVPS)` formula + `eps/bv≤0→None` guard correct; issues: upside recompute no `None/0` guard, no banks/NBFC/high-growth warning, EPS fallback `cmp/trailingPE` circular (compresses upside to zero, undisclosed), EPS TTM vs BV annual period mismatch.
EV/EBITDA: upstream `EV=mcap+Borrowings` **missing `-Cash`** (docstring claims "−Cash" — code omits → systematically overstated EV/EBITDA); ignores minority interest/Ind AS 116 leases; EBITDA proxy `Operating Profit` ambiguous (if EBIT post-depr, denominator too small; same field reused as EBIT for interest coverage — cannot be both); `>0` guard ✅; service falsy-`or` treats `0.0` as missing.
ROE/ROCE: pass-through of Screener values (definitions sound) + 2 unit bugs: `dividendYield/returnOnEquity` decimal vs `returnOnCapitalEmployed` percent fork (fallback path 100× error); falsy-`or` maps genuine `0.0` to fallback (`:93` ROCE vs `:94` ROE `is not None` inconsistent; same for PE/BV/D-E/PEG). `returnOnAssets: 0.08` hardcoded mock in `quotes.py`.
P/E TTM ✅ no forward disclosure; `forwardPE=stock_pe×0.85` fabricated; D/E recompute never exposed; yield same 100× fork (screener multiplies correctly, equity does not normalize).
Shareholding "12Q/11Y" unasserted (returns whatever scraped); `str(col)[:10]` truncation inconsistent (Timestamp vs `Mar 2025`); key normalization collides (`Promoters+` vs `Promoter`); `float(val) else 0.0` conflates missing with 0% (emit `None`); no sort guarantee; no QoQ/YoY deltas though t29 needs them; `rows` raw without periods metadata.
Concalls: zero URL reachability/content-type/expiry validation; "40+ streamable MP3" upstream marketing; `except→[]` outage masquerades as "no concalls" (should be 503 like Yahoo-crumb); no pagination though dossier uses 5; no duration/size; no transcript text yet `get_concall_prompt` demands Q&A extraction (forces hallucination).
Screener strategies vs canonical: Coffee Can drops persistence/growth/moat (cyclical peak passes); Magic Formula uses P/E + Screener ROCE thresholds, not Greenblatt EBIT/EV + ROC ranks, no financials/utilities exclusion, sorts by mcap not factor-rank; Debt-Free **never checks debt** (leveraged NBFC passes — false label); High Dividend no sustainability (payout/FCF/streak; unit fork decimal vs % across layers); Undervalued Growth **no growth input** (value mislabeled growth). Universe: 50 hard-coded large-caps (survivorship-biased, no SMID, `M&M` ampersand risk, BSE numerics forced `.NS` nonexistent — violates `.BO` invariant); **`max_stocks` truncates universe before filtering, not results**; route never exposes `universe`; `cache_key` omits universe (stale-wrong 5 min); per-ticker swallow (`continue`) understates coverage; `BookValue` absent in custom output; `price/mcap 0.0` fabricates (use `None`); `max_stocks or 25` maps `0→25` silently.
AI dossier: `custom_instructions` verbatim into `<INSTRUCTIONS>` (prompt-injection sink, no cap/sanitize; query param passthrough); no ticker confirmation (`resolve_company_id` first-hit — typo returns wrong company labeled correctly); `format` unvalidated end-to-end (`?format=xml` returns markdown labeled XML); token blowup (30-60k, no section/window caps, estimate, streaming; re-renders per call, no cache); Q&A + forensic items 6 demand facts never in context (must hallucinate); 1-10 scores no rubric/citations/`insufficient data` option; no as-of/source-URLs/SEBI disclaimer; tests only assert `"<INSTRUCTIONS>" in prompt`.

---

## 3. Bug catalog (consolidated — fix in this order)

### P0 — fix before any institutional claim

| ID | Location | Evidence | Fix |
|---|---|---|---|
| P0-1 HRP allocation | `optimization_service.py:84-98` | Weight-sum rescale not cluster variance; chunking drops singletons (N=3 → no bisection) | Recursive bisection on ordered cov with `_cluster_var` (`ivp=1/diag; ivp@sub@ivp`), `α=1-vL/(vL+vR)`; guard flat-series `corr.fillna(0)`, diag 1 |
| P0-2 Regime price/return confusion | `regime_service.py:96-97,218-228` | `detect_regime` fallback passes return Series; `classify` does `pct_change` of returns | `is_returns` flag or median/abs heuristic → reconstruct level via cumprod or separate path |
| P0-3 Coint cache collision | `cointegration_service.py:235,250,272,282` | `ticker=f"{a[:4]}_{b[:4]}"`, `metric=coint_{date}` — last-write-wins evicts pairs | Full-ticker key (`{a}__{b}` sanitized ≤64 or `sha1(a\|b)[:16]`); migrate rows |
| P0-4 `/liquidity` NameError | `api/analytics.py:639,647` | `inspect.isawaitable` without `import inspect` — every call with data → 500 | `import inspect` (or `asyncio.iscoroutine` like :143) |
| P0-5 Empty-portfolio crash | `api/analytics.py:1662-1663` | `allocation=None` → `list(allocation.keys())` AttributeError → 500 | `allocation = await _load_portfolio_allocation(db) or {}` |
| P0-6 Mock-200 envelopes | `api/analytics.py:216,237,330,352,471,490,620,676,716,732,775,793,808,848,868,903,933,961,966,1301-1303` + `tail_risk_service.py:53-67` | Empty/no-data → `200` + hardcoded `0.20/0.22/-0.032/-0.047/25/7.8/0.12/0.45` + `error` string; EVT n<20 hardcoded `-0.0385/...` | Empty→404, upstream fail→503, unexpected→500; EVT: raise/`insufficient_data` with nulls, never hardcode |
| P0-7 US tickers forced NSE | `services/data_service.py:37-55,83-85,189,289` + `company_data_service.py:31-33` | `canonical_ticker("AAPL")`→`"AAPL.NS"`, INR/NSE wrong | Pass bare non-Indian through; `_is_indian_ticker` via known list; `company_data` import `canonical_ticker` directly (drop `DataService(None)`) |
| P0-8 Analytics blind-insert | `services/cache_service.py:55-84` | No upsert; dup → `MultipleResultsFound` → caught → perpetual miss | `sqlite_insert(...).on_conflict_do_update(index_elements=["ticker","metric_name"], ...)` + commit |
| P0-9 Screener wrong-results | `services/screener_service.py:83,92,99,174` | `cache_key` omits universe; `max_stocks` slices universe pre-filter; `.BO` forced `.NS`; debt-free never checks debt | Key includes `hash(universe)`; slice results post-rank; map `.BO→.BSE` + `.NS→.BSE` for AV / keep `.BO` for yfinance; add `D/E≤0.2 and NetDebt/EBITDA≤0.5` |

### P1 — material bias / misleading / DoS (next sprint)

- **Quant:** CVaR `alpha=cp.Variable(neg=True)` 139 → free `cp.Variable()` (R-U 2000); Sortino → `sqrt(mean(min(0,r-target)²))·sqrt252` (Sortino & Price 1994); EWMA → single-pass `σ²=λσ²+(1-λ)r²`, flat term structure (RiskMetrics 1996); `target_volatility` unused 570-673 → scale `w·(σ_target/σ_p)` with cash/leverage flag or drop param + rename methodology (true ERC needs `RC_i=w_i(Σw)_i/σ_p`, Tasche 2000); `risk_scoring` benchmark-less R²=0→30 728 → thread benchmark or exclude+renormalize; `risk_scoring` singleton state 754-763 → caller-supplied prior or drop `change`; backtest turnover 78-80 → `one_way=0.5·Σ|Δw|`; backtest Sharpe 129-130 → `(mean×252-rf)/(std(ddof=1)·sqrt252)`; factor OLS zero-fill 1083-1085 → active-index filter + HAC SEs; inception `ffill+bfill+fillna(0)` 62-66 → forward-fill only + intersection/active-renorm + document daily-rebalanced assumption; `_max_sharpe` missing `raw.sum()≤0` guard (BL 231-233 has it); β fixed 0.95 never forwarded → `beta` param; HRP flat-series NaN guard; `equal_weight` backtest-vs-STRATEGIES mismatch.
- **Regime/MC/Vol/Tail/Corr/Coint:** `_label_states_by_risk` n≠3 guard + Sharpe-lexicographic labeling; dead `signed_vol`/200DMA docstring vs code; overlapping-21d MA(20) + non-stationary vol21 (use 1d log-rets or non-overlapping; ADF-test); full-sample `StandardScaler` lookahead (expanding/train-split); fake sticky prior (`params="mc"` re-estimates; pass `transmat_prior`/`startprob_prior` pseudo-counts or freeze `params="m"`; not Fox et al.); single restart (multi-seed `n_init`, `min_covar=1e-3`); smoothed `predict/proba` lookahead (filtered `_forward_lattice` for last bar); MC float-horizon crash (`steps=int(round(h*252))`); bootstrap `Generator` seed (`int(rng.integers(...))`); GARCH no winsorization (clip `±20%`, log rate) + `dist="t"` + `α+β<1` guard; delivery `close_col` StopIteration (default None + estimated branch); NaN ADV `float(mean) or fallback` no-op (`pd.isna` check); bhavcopy `float()/int()` on `"-"` (safe coercers); N+1 selects (single `IN` + groupby); delivery population-std one-sided (ddof=1, `abs(z)`); OU oscillatory branch (return None+flag); hedge `polyfit` RankWarning (var guard + `catch_warnings→error`); Johansen/EG no ADF pre-test + fixed lags (ADF both legs, expose trend/autolag, AIC-select); copula `ν=mean(marginals)` → PIT pseudo-MLE or Kendall inversion; `ρ≥0.999→1.0` discontinuity (remove); `top5` LOW-as-high (return `[]` + `top_pairs`); `fillna(0.0)` portfolio dampening (pairwise-complete/dropna); correlation in-sample threshold (leave-one-out) + Fisher-z averaging; V4 synthetic cone bounds (null + `insufficient_data` flag); benchmark `ensure_history` ignores range (add `ensure_range` + warmup); `_close_series` sort/dedupe; `id(db_session)` registry (WeakKeyDictionary/request DI + lock).
- **Data/infra:** substring suffix (`endswith((".NS",".BO"))`); shared mutable class-level df cache (instance `TTLCache` + lock); fresh/cached/AV schema divergence (normalize AV through same path, set canonical ticker, memory-cache it); `_source` attr loss (`df.attrs`); fallback quote `is_indian` always False + `.BSE` vs `.NS` mismatch; MultiIndex `hist['Close']` flatten; blocking sync in async (`to_thread`); `validate_ticker`/`corporate_actions` bypass cascade+cache; `Adj Close` required rejects bfinance lowercase (case-insensitive map first); `reset_index` assumes `Date` name (case-insensitive resolve); weekend stale false-positive (trading-day count or ≥5); **shared `AsyncSession` across 5 concurrent coroutines** (per-task sessions or serialize writes + lock); `_log_storage_metrics` hardcodes source + never commits; `utcnow`/`get_event_loop` deprecated; AV `.BO→.BSE` mapping; pool races (lock acquire/spend/drop + double-checked singleton); rejects not budgeted; `company_data._to_thread` drops `*args`; private `t._ensure_profile()` (public API + None guard); `price_to_book` ZeroDivision + `len>2` threshold; insider frame drops non-scalars; indicators `bfill` + SMA200 warmup (`max(420, lookback*2+300)` cal days) + `ticker.upper()` not canonical; bhavcopy dedupe ignores `series` (check `(symbol,series)` + UQ); placeholder ADV/Amihud without `estimated` flag (add flag or omit); FX `fast_info` skips history (nested try), stale `83.0` cached as live (short TTL + `stale:true`), unknown pairs `1.0` (raise); analytics keys unnormalized (`canonical_ticker().upper()`); no stampede guard (per-key lock); `GlobalCacheService` drops TTL.
- **API/DB:** monte-carlo `initial_value` sums only `market_value` (mirror qty×price fallback); `num_paths` uncapped (clamp 100..20000); concentration `by_sector` stored- vs live-weight mismatch (group live `weights` by sector_map); correlation extra field `historical_avg_correlation` not in schema (remove or add Optional); stress-test ignores `request.tickers` (honor or drop from contract); single-ticker routes raw `ticker.upper()` vs stored `canonical_ticker()` (canonicalize lookup + quote); `ValidateTickerRequest max_length=10` + DB `String(10)` (→20 + pattern + migration); `add` no global renorm + `bulk_add` batch-only renorm (renormalize all or 400 unless auto_normalize); rebalance `price or 100.0` + `int()` truncation + 4dp (400 if price≤0, float qty, 6dp); export_csv `str` lossy (StreamingResponse + quantity/buy_price cols); `GET /{ticker}` private `_get_cached_data` extra query + `strftime`/`int(NaN)` crashes (return `(df,from_cache)`, `pd.to_datetime`, NaN guard); `PUT /config` unpersisted (persist or 501), insider/concalls/ai bad-ticker 500→404, free-string enums → `Literal` (422); batch/refresh unbounded serial (cap 50, dedupe, gather sem-5, ISO dates); WS token/broadcast/client_id/status/task-race (JWT/dev-token, restrict broadcast, 409 dup, lock spawn, real status); DB no `Unique(ticker)`/`CheckConstraints`, `position_id` FK orphans (`unique String(20)`, checks, `ondelete=CASCADE` or drop); `init_db.create_all` bypasses Alembic + relative path + `echo=debug` + `raise e` (upgrade head in lifespan, absolute Path, debug=false default, bare raise); health hardcodes `development`, `reload:true` unconditional; liquidity `price_col` misses `Close`, `Inf` never replaced.

### P2 — hygiene / contracts (backlog; all have snippets below or in sub-reports)

Price/return heuristic `(abs>1).any()` (explicit `is_prices` flag); kurtosis excess-vs-3; `max(0,adj-R²)`; risk caps saturate + thresholds arbitrary; `<10 obs sum` arithmetic; `round(w,4/6)` breaks Σ=1 (renorm after rounding, display-only rounding); `datetime.utcnow`/`pd.Timestamp.utcnow` (timezone-aware); `V5 target_w` unsorted; `T2 losses>u` strict (≥); `T3 ξ` silent clip + 5% wedge (log + `xi_clipped`); C1 `>` vs `>=`; C2 simple mean (Fisher-z); K5 `<30` power + in-sample z (≥100, rolling ex-current); `data._source`/`_fetch` extras; `Adj Close`/`date`-name assumptions; `replacement_ratio` dead; `BM` sort/dedupe; `AV` date/ET; `COMP` book-zero/len threshold; `FX` aiohttp unused + Western commas (en-IN `1,00,000`); cache TTL forwarding; Pydantic v1 shims (`.dict()`→`model_dump()`, `validator`→`field_validator`, `min_items`→`min_length`, `Field(env=)`→`SettingsConfigDict`); WS/rebalance/normalize/summary rounding mix; `alpha` NaN; export/screener/concall pagination; GZip 1000→5000; CORS wildcard+credentials; HSTS dev confusion; `added_on` TZ-aware vs `date` naive (standardize `DateTime(timezone=True)`); dead imports (`quantstats/PCA/ARIMA/StressTest*`, `aiohttp`); `warnings.ignore` global + bare `except` (scope + `exc_info`); `int(shares)`/`current_price or 100.0` fallbacks; Excel sheet-name mismatch + temp-leak + no cap/auth; tests mock away reality (CFO key, units, Piotroski proxies, universe bias — add contract tests).

---

## 4. Optimisation + efficiency (do after P0, with P1)

| # | Location | Issue | Fix (gain) |
|---|---|---|---|
| O1 | `analytics_engine 936-1014,565-618` | `async def` GARCH blocks loop; per-ticker sequential fits | `asyncio.to_thread` + cache `(ticker,window)` + default EWMA for sizing; lazy-import arch/statsmodels/sklearn/quantstats |
| O2 | `backtest 92-102` | Per-day `iterrows` loop | Vectorize `chunk_rets=test.values@w; chunk[0]=(1-c)(1+chunk[0])-1` |
| O3 | `analytics 1068-1190` | 3 OLS fits same X/y | Single portfolio OLS + reuse; `lstsq` batch if N large |
| O4 | `optimization 67-76` in backtest | `mu/cov` recomputed twice per rebalance; no warm-start | Return/cache `(mu,cov)`; CLARABEL warm-start / turnover-penalized |
| O5 | `analytics 1025` | `rolling(30).std+ewm` O(T·W) | Single-pass EWMA variance |
| O6 | `monte_carlo 64,90-96,116-125` | `(20000,10080)` ≈1.6GB; bootstrap Python `next(gen)` ~800k calls | Chunk paths (batch 2000), cap `paths·steps≤5e7`, pre-draw geometric-block index matrix with NumPy + axis-1 cumprod |
| O7 | `volatility 242-286,293-295` | Cone recomputes rolling per window + GARCH per request (~100ms-1s) | Rolling sums/sumsq once → all windows; memoize GARCH `(hash(returns),horizon)` TTL; early-exit `len<max(windows)` |
| O8 | `tail_risk 178-181,235-243` | `t.fit` per leg per pair (20 names → 380 fits, 4-20s) | Pooled/global ν or Kendall-tau + 1-d ν MLE on uniforms; cache `(hash(a),hash(b))` |
| O9 | `correlation 55-63` | N=50 → 1225 `rolling(60).corr` O(N²·T·W) | Sliding-window `np.corrcoef` view + upper-triangle avg; downsample payload (weekly) |
| O10 | `cointegration 335-357` | O(N²) EG+Johansen + sequential DB awaits | Batch cache mget/pipeline; `gather` + semaphore + `to_thread`/ProcessPool; ADF/correlation pre-filter; cap universe (≤25) + paginate pairs |
| O11 | `regime 133,230` | DB + HMM fit per request, no cache | Cache `(as_of,n)` TTL 24h |
| O12 | `data_service 692-739,797-822` | `iterrows` dict build + extra FetchLog insert w/o commit per ticker | `to_dict("records")` + list-comp; bulk FetchLog or drop per-store log |
| O13 | `data fetch_ohlcv_batch 336-348` | No dedupe (`RELIANCE`+`reliance.ns` fetch twice) | Dedupe canonical keys pre-fanout; per-task sessions |
| O14 | `cache clear/stats 113-183` | Full-table loads, N+1 deletes, 3× scans + 24h logs in RAM | `delete(...) where expires_at<=...`, `func.count()` ×3, index `(expires_at,timestamp)` |
| O15 | `india delivery 180-186` + ingest 73-76 | N+1 selects; `func.date()` SQLite-only; full-symbol load | Single `IN` query + Python groupby (or gather); `func.count()` existence / bulk upsert; portable date-trunc |
| O16 | `company _yf_retry 36-51` | Blocking `time.sleep` holds worker ~14s; statements sequential | Async sleep at async layer; `gather` multi-statement |
| O17 | `analytics 862-865,1721-1724` + WS 75-89 | Serial per-ticker fetches; 3 sessions + 3 scans per 30s tick + fresh engine + 1-yr recompute | `_fetch_price_series_dict` sem-5 (N/5 wall); WS single session/scan per tick + `gather` sends + skip recompute if `max(updated_on)` unchanged + singleton engine + live weights everywhere |
| O18 | `data GET /{ticker} 244` | Fetch + extra `_get_cached_data` query | Return `(df,from_cache)`; drop 2nd query (½ DB) |
| O19 | `analytics 1523+,1590+,979-1061` + data batch/refresh + portfolio refresh | Unbounded series/pairs/arrays; refresh serial | `?limit/offset`, coint `max_universe`, `?resolution=daily/weekly`, cap 50 + dedupe + gather sem-5 |
| O20 | `equity/screener/dossier` | `Ticker→ScreenerClient→SQLiteCache` per request; full-profile for single ratio; screener **serial 25-100s** (docs claim "multi-threaded" — false); per-process unbounded `_cache` (mutation-poison, not shared); Excel sync write+read in thread | Pooled `httpx.AsyncClient`, section/field params, semaphore fan-out + shared client, SQLite/Redis persist, `202 Accepted` + poll for screener/Excel, per-request client reuse |
| O21 | `indicators` | Recomputes all indicators per call | stockstats lazy per-column already minimal; optionally cache `stock_df` per (ticker,end) |
| O22 | `db` | Missing `(ticker,expires_at)` / NSE UQ indexes | Add UQ `(symbol,date)` bhavcopy, `(date,category)` flows, TTL index `expires_at`; `VACUUM`/batch upserts |
| O23 | `main 98` | GZip 1000 compresses tiny health/status | `minimum_size=5000` or exclude `/health`, `/status` |

Currency note: hoist `get_exchange_rate` to one call per valuation, not per position (N lock acquisitions otherwise fine).

---

## 5. How to fix — drop-in snippets (highest leverage first)

```python
# F1 HRP correct bisection (optimization_service.py:46-100) — Lopez 2016
def _cluster_var(cov, items):
    sub = cov[np.ix_(items, items)]
    ivp = 1.0 / np.diag(sub); ivp /= ivp.sum()
    return float(ivp @ sub @ ivp)
# order cov by quasi-diag labels -> cov_ord; then:
w = pd.Series(1.0, index=labels); pairs = [list(range(len(labels)))]
while pairs:
    nxt = []
    for c in pairs:
        if len(c) < 2: continue
        m = len(c)//2; l, r = c[:m], c[m:]
        vl, vr = _cluster_var(cov_ord, l), _cluster_var(cov_ord, r)
        alpha = 1.0 - vl/(vl+vr) if (vl+vr) > 0 else 0.5
        w.iloc[l] *= alpha; w.iloc[r] *= (1-alpha); nxt.extend([l, r])
    pairs = [c for c in nxt if len(c) > 1]
w = w / w.sum()
# + guard: corr = returns.corr().fillna(0.0); np.fill_diagonal(corr.values, 1.0)

# F2 R-U free VaR (optimization_service.py:139)
alpha = cp.Variable()  # never neg=True; VaR of loss can be >0

# F3 Sortino (analytics_engine.py:828-830) — Sortino & Price 1994
target = 0.0  # or self.risk_free_rate/252 to match numerator
down = np.minimum(0.0, returns - target)
downside_dev = float(np.sqrt((down**2).mean()) * np.sqrt(252))
sortino = float((annual_return - self.risk_free_rate)/downside_dev) if downside_dev > 0 else 0.0

# F4 EWMA (analytics_engine.py:1016-1055) — RiskMetrics 1996
lam = 0.94; r = clean_returns.values; var = np.var(r) if len(r) else 0.0
for x in r[-min(len(r),60):]: var = lam*var + (1-lam)*x*x
forecast_vol = float(np.clip(np.sqrt(var*252), 0.05, 1.20))
term_structure = [forecast_vol]*h  # flat — no mean reversion

# F5 target_volatility (analytics_engine.py:636-643)
scale = target_volatility / portfolio_volatility if portfolio_volatility > 0 else 1.0
levered = {k: v*scale for k,v in recommended_weights.items()}
cash = max(0.0, 1.0 - scale)  # unlevered; or document leverage
# OR remove param + rename "inverse-volatility (long-only, fully invested; ignores correlations)"
# True ERC: RC_i = w_i*(Sigma@w)_i/sigma_p; sum(RC)==sigma_p (Tasche 2000)

# F6 backtest cost+Sharpe (backtest_service.py:78-80,126-130)
turnover = float(np.sum(np.abs(new_weights - current_weights)))
cost_penalty = (0.5*turnover) * cost_factor  # one-way
chunk = test_chunk.values @ current_weights
chunk[0] = (1.0-cost_penalty)*(1.0+chunk[0]) - 1.0
mu_d, sd_d = float(np.mean(strat_rets)), float(np.std(strat_rets, ddof=1))
strat_vol = sd_d*np.sqrt(TRADING_DAYS)
strat_sharpe = (mu_d*TRADING_DAYS - risk_free_rate)/strat_vol if strat_vol > 0 else None

# F7 active-history OLS (analytics_engine.py:1075-1088)
active = s[s != 0.0].index.intersection(aligned_benchmark.index)
if len(active) >= 10:
    X = sm.add_constant(aligned_benchmark.loc[active]); y = s.loc[active]
    model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 5})

# F8 regime robust labeling + price/return guard + honest priors
def _label_states_by_risk(state_stats):
    if len(state_stats) != 3: return {int(s): f"state_{int(s)}" for s in state_stats.index}
    df = state_stats.copy()
    key = df["signed_vol"] if "signed_vol" in df else (df["cagr"]/df["ann_vol"].replace(0,float("nan"))).fillna(df["cagr"])
    order = key.sort_values().index.tolist()
    return {int(order[0]): "crisis", int(order[1]): "calm", int(order[2]): "bull"}
# price vs returns:
_probe = pd.Series(bench_data.iloc[:,0] if isinstance(bench_data,pd.DataFrame) else bench_data).dropna()
if len(_probe) and float(_probe.median()) < 0.5 and float((_probe<0).mean()) > 0.25:
    close = (1.0 + _probe.astype(float)).cumprod(); ret_1d = _probe.astype(float)  # skip pct_change
# HMM:
hmm = GaussianHMM(n_components=n_components, covariance_type="full", min_covar=1e-3,
    random_state=100, n_iter=200, tol=1e-4,
    startprob_prior=10.0*np.ones(n_components), transmat_prior=100.0*sticky_trans)
# multi-restart keep max score() over seeds (100,7,42)
# MC:
steps = int(round(float(horizon_years)*TRADING_DAYS))
bs = StationaryBootstrap(BLOCK_LENGTH, data, seed=int(rng.integers(0, 2**32-1)))
# GARCH:
r_w = np.clip(r, -0.20, 0.20)
# after fit: if persistence>=1 or not finite: EWMA fallback + warn  (use dist="t")

# F9 data/infra quick wins
import re
_INDIA_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-&]*(\.NS|\.BO)$")
def canonical_ticker(ticker: str) -> str:
    t = ticker.upper().strip()
    if t.startswith("^") or t.endswith("=X"): return t
    if t.endswith(".NS") or t.endswith(".BO"): return t
    return t  # never force .NS; _is_indian_ticker via known list
# benchmark range: ensure_range(start,end,warmup=30) -> fetch(s-warmup, end)
# close series: sort_index + ~duplicated(keep=last) + dropna
# indicators clean: dropna(Close) -> sort/dedupe -> ffill O/H/L/C only -> Volume fillna(0) -> dropna leading (never bfill)
# warmup: max(420, lookback*2+300) calendar days (covers SMA200)
# ADV: adv = float(m) if pd.notna(m) and m>0 else fallback
# NSE coerce: _f/_i helpers mapping "-"/""/None/NaN -> default
# delivery: std ddof=1, abs(z)>=thr
# FX: nested try fast_info -> history; stale 83.0 short-TTL + stale:true; unknown pair raise
# analytics cache: sqlite_insert(...).on_conflict_do_update(["ticker","metric_name"], ...)
# coint key: ticker=re.sub(r'[^A-Z0-9_-]','-',f"{a}__{b}")[:64] or sha1(a|b)[:16]
# OU: var<1e-12 -> None,None; -2<gamma<=-1 -> None,None + oscillatory flag (no half-life)
# hedge: var(p_b)<1e-12 -> None; catch RankWarning as error
# ADF pre-test both legs before Johansen; expose trend/autolag/k_ar_diff; AIC-select lags
# copula nu: rank/(n+1) PIT + Kendall tau inversion + 1-d MLE on (u,v), bounds [2.1,30]
# correlation: thresholds on corr_values[:-1]; >= unify; Fisher-z avg

# F10 API/DB quick wins
import inspect  # analytics.py top
allocation = await _load_portfolio_allocation(db) or {}
initial_value = sum((p.market_value if (p.market_value or 0)>0 else (p.quantity or 0)*(p.last_price or 0)) for p in positions)
num_paths = min(max(int(body.get("num_paths",2000)),100),20000)
# mock-200 -> proper codes:
try: ticker_list, weights = await resolve_allocation(tickers, db)
except ValueError as e: raise HTTPException(status_code=404, detail=str(e))
if not price_data_dict: raise HTTPException(status_code=503, detail="Upstream price feed unavailable")
# by_sector from live weights:
sector_map = {p.ticker: (p.sector or "Unknown") for p in sector_rows}
by_sector = {}
for t,w in weights.items():
    k = sector_map.get(t,"Unknown"); by_sector[k] = round(by_sector.get(k,0.0)+w/(sum(weights.values()) or 1.0),4)
# canonical lookup:
from app.services.data_service import canonical_ticker
position = (await db.execute(select(PortfolioPosition).where(PortfolioPosition.ticker == canonical_ticker(ticker)))).scalar_one_or_none()
# schemas/models: max_length=20 + pattern ^[A-Z0-9\-\&\.] + String(20) unique + migration
# rebalance: if price<=0: 400; qty float 4dp; w round 6dp
# returns hygiene everywhere: prices.pct_change(fill_method=None).replace([np.inf,-np.inf],0.0).fillna(0.0)
# WS: single SessionLocal + single scan per tick + gather sends + singleton engine
# lifespan: alembic upgrade head; DB absolute Path(__file__).parent; debug=false default; bare raise
```

BL units doc: `views`/`relative_views["diff"]` are **annualized excess returns** (same units as `mu_ann`), `tau∈[0.01,0.05]`, `Ω=diag(PτΣPᵀ)` He-Litterman; see Black-Litterman 1992 / He-Litterman 1999 / Idzorek 2007.

---

## 6. Missing for Bloomberg / Jane Street / JPMorgan — gap analysis + how to implement

Today: delayed scraped fundamentals + point-in-time screens + static prompt strings + single-user localhost trust. An institutional desk requires the following. Suggested build order respects open tickets (t28 cron deferred, t29 pledge `needs-info`, t30 BL `ready-for-agent`, t31 Greeks `needs-info`, t32 backtester `ready-for-agent`, QH-04 errors / QH-05 WS / QH-07 FX open):

| # | Missing | Why (desk view) | Implement in finengine (service / tables / endpoints / libs / vendors) |
|---|---|---|---|
| G1 | Order Management / EMS + paper trading | Bloomberg EMSX / Athena: staged orders, algos (VWAP/POV), fills, kill-switch. Today `+ Add to Portfolio` writes holdings directly, no lifecycle | `services/execution_service.py` + `orders/fills/order_events` (SQLite→Postgres later). `POST /api/v1/orders {ticker,side,qty,type,limit,tif}` → PENDING→ACK→PARTIAL/FILLED/CXL; paper sim on NSE ticks; pre-trade calls G6. Adapter later via Zerodha/Upstox API |
| G2 | Real-time tick streaming | B-PIPE / FPGA feed sub-second L1. Today delayed scrape + 5-min caches; WS re-queries DB | `services/marketdata_service.py` over NSE quote-api / Upstox WS / TrueData / GFDL; Redis pub/sub → existing `api/websocket.py`; `intraday_bars` table. Libs: `websockets`, `redis`, `pyarrow`. Vendors: authorized (GFDL/TrueData/GlobalDataFeeds) ₹15-40k/yr — scraping NSE without license violates ToS |
| G3 | Options Greeks + IV surface | Desk needs delta/gamma/vega, smile, term structure. Today `DerivativesEngine` outputs **random** OI/volume + toy prices — unusable/dangerous, never wire to Greeks | `services/derivatives_service.py`: NSE option-chain CSV/bhavcopy (`option-chain-indices?symbol=NIFTY`), Black-Scholes + Binomial via `pyvollib`/`QuantLib`, SVI smile per expiry. Tables `option_chains(expiry,strike,ce_oi,pe_oi,iv)`, `iv_surface`. `GET /api/v1/derivatives/{underlying}/surface`. Portfolio net-Greeks (t31) only after real chain lands |
| G4 | Fixed income (G-Sec/SDL/corps) | Duration/convexity/YTM, CCIL curves. Today equities-only | `services/fixed_income_service.py`: CCIL FBIL MIBOR/OIS + NDS-OM G-Sec, CRISIL/ICRA master via NSE debt. Tables `bonds(isin,coupon,maturity,ytm,duration)`, `yield_curve`. `QuantLib` FixedRateBond + FittedBondDiscountCurve. `GET /api/v1/fixed-income/curve` |
| G5 | FX forwards | INR P&L, FII linkage. Today spot-only, stampede-prone (QH-07) | Extend `currency_service`: RBI reference + NSE currency-derivative forwards; single-flight lock; `fx_rates(pair,spot,forward_1m)`; vendors RBI FBIL + NSE CD |
| G6 | Risk limits + pre-trade checks | Hard blocks: single-name %, ADV participation, leverage, restricted list. Today post-hoc optimizer constraints only | `services/risk_limits_service.py` in order path (G1): `max_weight 10%`, `DTL≤5 @20% ADV` (reuse ADV), NetDebt/EBITDA veto, SEBI ASM/GSM. Tables `risk_limits`, `limit_breaches`. `POST /api/v1/orders/validate` dry-run |
| G7 | Barra-style factor model | PORT: Size/Value/Momentum/Vol/Beta + idiosyncratic VaR. Today single-factor CAPM OLS only | `services/factor_service.py`: cross-sectional z-scores (log-mcap, B/P, 12-1m mom, 60d vol, beta vs ^NSEI) over NSE-500 (CMIE Prowess / NSE indices master), OLS/`sklearn` PCA covariance. Tables `factor_exposures`, `factor_returns`. `GET /api/v1/analytics/factors` |
| G8 | Scenario + stress engine | Athena: 2008/2020 replay, +200bps, crude +50%. Today univariate vol-scaled drawdowns, no factor shocks | `services/scenario_service.py`: `r_shock=β·f_shock` + full-revaluation for options (G3). Table `scenarios(id,shocks_json)`. `POST /api/v1/analytics/scenarios/run`. Seed NSE event library (demonetization, COVID, Adani Jan-23) |
| G9 | Performance attribution (Brinson) | Allocation vs selection vs interaction. Today QuantStats tear-sheet only | `services/attribution_service.py`: Brinson-Fachler vs NIFTY sector weights (NSE sector indices). `GET /api/v1/analytics/attribution?benchmark=NIFTY50`. Needs `portfolio_snapshots` (today live-only) |
| G10 | Compliance / audit trail | SEBI RA: every recommendation logged + rationale retained. Today prompts generated, nothing logged | Middleware log dossier/memo → `research_audit(ticker,prompt_hash,dossier_hash,user,ts)`; order audit in G1; PDF hash-chain; SEBI disclaimer in every memo prompt + API footer |
| G11 | Entitlements / RBAC + metering | Terminal licenses; role-based books. Today single-user no keys | Keep single-user default; add `X-API-Key` + per-route budget (screener=expensive) via `slowapi`; scaffold `users/roles` for multi-seat; prevents screener DoS |
| G12 | Low-latency infra (cache/queue) | Pragmatic step: Redis + task queue (not colocation) | Redis (quotes, screener 24h), Celery/`arq` for screener fan-out + Excel (`202 Accepted` + poll); pooled `httpx.AsyncClient`; replace per-request `ScreenerClient` |
| G13 | Event news/sentiment | RavenPack/Bloomberg News → signals. Today announcements unparsed; concall MP3 untranscribed | `services/events_service.py`: BSE announcements RSS + filings → dedup → FinBERT (`ProsusAI/finbert`, `transformers`). Table `news_events(ticker,ts,headline,sentiment)`. `GET /api/v1/events/{ticker}`. Transcribe MP3 with `faster-whisper` before Q&A prompts (fixes hallucination) |
| G14 | Transaction-cost model | t32 exists but STREET costs missing: STT 0.1%, stamp 0.015%, SEBI ₹10/Cr, GST 18% on brokerage, impact `σ·√(Q/ADV)` | Extend `backtest_service.py` with `costs.py` from NSE/BSE circulars + Zerodha charge list; report net vs gross CAGR |
| G15 | Corporate-action-adjusted series | Splits/bonus unadjusted → vol/GARCH explosions (gotchas #13-14). Screener P/E cross-check unadjusted | `services/corporate_actions_service.py`: NSE master + bfinance splits/dividends; adjust OHLCV at ingestion boundary with `corp_actions(ticker,ex_date,factor)` |
| G16 | Reference-data / symbology master | FIGI/ISIN entity resolution. Today string tickers, `M&M`/`BAJAJ-AUTO`/numeric ad-hoc, first-hit misfires | Table `securities(isin,nse_symbol,bse_code,yf_ticker,lot_size,asm_flag)` seeded from NSE `EQUITY_L.csv` + BSE `Equity.csv` daily; all services resolve via master; kills `.NS`-hardcode |
| G17 | Estimates / consensus | Initiation needs consensus EPS/targets. Today `forwardPE` fabricated, no estimates | Licensed feed (Trendlyne/Tickertape/Stable/Refinitiv); until then **delete** `forwardPE`/price-target synthesis, label valuation "trailing only". Never synthesize |
| G18 | Short interest / SLB + FII positioning | Crowding signal. FII/DII flows + delivery partial, no stock-level short | Ingest NSE SLB + F&O ban + short-sale disclosures → `short_interest`; surface in liquidity + screener veto (`in_FnO_ban→exclude`) |

**Build order:** G16 master → G2 ticks → G15 actions → G6 limits + G1 paper-EMS → G3 derivatives → G7 factors → G8 scenarios → G9 attribution → G13 events/whisper → G14 costs → G4/G5 income/FX → G10/G11 compliance/entitlements → G12 infra → G17 licensed estimates. Assumes P0/P1 fixed first; G3/G17 explicitly quarantine existing synthetics (`forwardPE/returnOnAssets/option_chain/analyst_targets`) behind flag until real feeds land.

---

## 7. Prioritized action plan (no code changed yet — next agent sessions)

**Sprint 1 — stop wrong numbers/crashes (P0):** F1 HRP, regime Series guard, coint key migration, `import inspect`, `or {}` allocation, mock-200 → 404/503 (+EVT), ticker passthrough, analytics upsert, screener key/universe/`.BO`/debt filter. Add contract tests: HRP variance-allocation (N=3,5), Sortino hand-check, EWMA vs RiskMetrics, R-U positive-loss VaR, turnover one-way, Sharpe mean-based, regime Series path, coint collision pair, `/liquidity` with data, empty-portfolio delivery, `AAPL` passthrough, duplicate-cache hit, screener universe isolation, CFO key, unit fork, Piotroski F6/F8 fixtures.
**Sprint 2 — remove bias (P1 quant+data):** Sortino/EWMA/CVaR/target-vol/risk-score-benchmark/backtest-cost-Sharpe/factor-active-history/inception-fill; HMM scaler/prior/restarts/filtered probs; GARCH winsorize + `t` + persistence; delivery/ADV/bhavcopy/N+1; benchmark range/sort; AV lock; FX nested-try/stale/unknown; indicators bfill/warmup/canonical; cache TTL/stampede; ticker regex + String(20) + canonical lookups + global renorm + rebalance guards + proper envelopes + WS single-scan + Alembic path.
**Sprint 3 — efficiency (O-table):** to_thread GARCH/HMM, vectorize backtest/correlation/bootstrap, cache GARCH/cone/HMM/copula, batch coint, chunk MC, pooled screener fan-out + persist, Redis/queue scaffold (G12-lite).
**Sprint 4 — terminal truth (research):** CFO key, EV−cash, F6/F8 proxies, breakdown return, %/decimal boundary, `is not None`, canonical ticker, 404-vs-503, concall 503, shareholding None-gaps + counts, screener rank/universe/parallel, dossier sanitize/validate/confirm-symbol/caps/citations/disclaimer/cache, route-or-delete concall prompt, quarantine synthetics, pin bfinance + contract tests.
**Then G16→G2→G15→G6+G1→G3→G7→G8→G9→G13→G14→G4/G5→G10/G11→G12→G17.**

---

## 8. Appendix — references + test gaps

López de Prado 2016 HRP; Markowitz 1952; Sharpe 1966 + Lo 2002; Sortino & Price 1994; Rockafellar-Uryasev 2000; Black-Litterman 1992 / He-Litterman 1999 / Idzorek 2007; RiskMetrics 1996 λ=0.94; Bollerslev 1986 / Nelson 1991; Tasche 2000 Euler + Maillard et al. 2010; Amihud 2002; Cornuejols-Tütüncü tangency; McNeil EVT; Politis-Romano stationary bootstrap (+Politis-White optimal block); Piotroski 2000; Graham; Greenblatt Magic Formula; Mukherjea Coffee Can; Brinson-Fachler attribution.
Test gaps to close for 80%+ gate permanence: quantitative invariants already started (`test_quantitative_invariants.py` — extend to HRP odd-N, Euler `ΣRC=σ_p`, HHI single→0, inv-vol `1/σ`, OU oscillatory, EVT no-mock, MC float-horizon, compounding `(1+r).groupby([y,m]).prod()-1` on stable `date` col, inner-join alignment, active-history Sharpe, Fisher-z, ADF pre-test, copula PIT, GARCH persistence, FX stale flag, cache upsert-hit, ticker regex `3MINDIA.NS/MOTHERSON.NS/BAJAJ-AUTO.NS/500112.BO`, WS auth, Alembic head, Pydantic v2, rounding residual, NaN/Inf JSON, screener universe/key/units, dossier injection/format/symbol-confirm, concall error-503, Excel content + sheet names.
Missing coverage note: **Euler risk contribution is never implemented** — add `RC_i` block if risk-parity claims persist; `diversification_ratio` 237 must be renamed; monthly compounding, Sharpe active-history, inner-join alignment live in analytics/portfolio layer (verify there — not in the 8 data files).

*End of review. No source files modified. Next step: approve Sprint 1 scope, then implement with tests.*
