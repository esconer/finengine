# Independent Quant Methodologist Verification — Risk and Time-Series Models

**Date:** 2026-09-24  
**Scope:** Cash equities and portfolio analytics only; out-of-scope asset classes and instruments are not analyzed.  
**Artifacts:** [evidence runner](evidence/verify-risk-timeseries.py) · [printed evidence](outputs/verify-risk-timeseries.txt)

## Executive result

Nineteen model families were adjudicated: **13 MATCHES, 2 DIVERGES, 4 BUG, 0 REPLACE-WITH-LIBRARY** (`outputs/verify-risk-timeseries.txt:212-237`). The runner completed successfully (`outputs/verify-risk-timeseries.txt:237`).

### Top three findings

1. **High — multi-step GARCH/EGARCH risk path is wrong.** The GARCH path uses a terminal volatility that already contains the `sqrt(horizon)` accumulation and then applies `sqrt(horizon/252)` again. At `h=5`, backend/reference VaR is `-0.0492743493 / -0.0220682005` (123.28% relative difference), and CVaR is `-0.0617052642 / -0.0276744137` (122.97%) (`outputs/verify-risk-timeseries.txt:63-71`). EGARCH is independently unavailable for every `h>1`: backend returns nulls although direct `arch` simulation gives an `h=5` volatility of `0.220720188989` (`outputs/verify-risk-timeseries.txt:78-89`).
2. **Medium — EVT reports a clipped shape as the fitted GPD shape and uses it for VaR/ES.** In the boundary fixture, SciPy fits `xi=-2.01301977674`; backend reports `-0.5`, changing VaR from `-0.0301336751` to `-0.069798` and ES from `-0.0309544261` to `-0.088620` (`outputs/verify-risk-timeseries.txt:90-102`).
3. **Medium — MFI is scaled incorrectly.** Backend returns `0.524678528716`; the canonical 0–100 MFI is `52.4678528716`, a 51.9432-point / 99.00% error. The backend itself documents MFI thresholds as `>80/<20` (`backend/app/services/indicators_service.py:45-47`), while the delegated formula returns a fraction (`backend/.venv/Lib/site-packages/stockstats.py:1454-1479`; `outputs/verify-risk-timeseries.txt:147-179`).

## 1. Independence, read-only boundary, and installed-library inventory

### Independence and read-only statement

- This review was independent of implementation changes: no backend source, tests, configuration, lockfile, database, or git state was modified. The runner sets bytecode writes off, resolves the repository root, imports production functions, prints results, and writes only the contracted output (`evidence/verify-risk-timeseries.py:14-19`, `evidence/verify-risk-timeseries.py:62-63`, `evidence/verify-risk-timeseries.py:1128-1165`). The output records the read-only/no-DB/no-network declaration and successful completion (`outputs/verify-risk-timeseries.txt:1-4`, `outputs/verify-risk-timeseries.txt:237`).
- No prohibited `.scratch/backend-audit/` material was read, globbed, grepped, or inspected. No unrelated `.scratch` content was used.
- No package was installed. The live environment was queried with `importlib.metadata`; the runner parses `backend/pyproject.toml` and `backend/uv.lock` and compares those declarations with installed distributions (`evidence/verify-risk-timeseries.py:145-190`).
- Production functions are called directly. DB/API seams use read-only in-memory fake dependency objects; no production file is monkeypatched. Examples: tear-sheet and performance-history fixtures (`evidence/verify-risk-timeseries.py:920-1008`) and the delivery-anomaly fake DB (`evidence/verify-risk-timeseries.py:1075-1095`).
- No live network or market-data request is made. The final successful runner and no-cache Ruff gate are the executed verification gates.
- This verifier created no extra evidence/output files. The shared directories also contain `verify-portfolio-correlation.py` and `verify-portfolio-correlation.txt` from the other assigned partition; their names were observed only in the directory listing, and their contents were not read or modified.

### Declared, locked, and installed libraries

The project declares NumPy, pandas, SciPy, `arch`, QuantStats, statsmodels, scikit-learn, CVXPY, QuantLib, `stockstats`, and `hmmlearn` (`backend/pyproject.toml:11-42`). Live/locked evidence is:

| Library | `uv.lock` | Installed | Role in this review |
|---|---:|---:|---|
| NumPy | 2.5.3 | 2.5.3 | Arrays, RNG, quantiles, linear algebra |
| pandas | 3.0.6 | 3.0.6 | Returns, rolling statistics, OLS inputs |
| SciPy | 1.18.1 | 1.18.1 | GPD, Student-t, normal-tail and shape references |
| arch | 8.0.0 | 8.0.0 | GARCH/EGARCH and stationary-bootstrap reference |
| statsmodels | 0.15.0 | 0.15.0 | HAC OLS factor reference |
| QuantStats | 0.0.81 | 0.0.81 | Tear-sheet metric reference |
| hmmlearn | 0.3.3 | 0.3.3 | Gaussian HMM reference |
| stockstats | 0.6.8 | 0.6.8 | Backend indicator engine; independent canonical formulas used instead of treating it as an independent oracle |
| scikit-learn | 1.9.1 | 1.9.1 | `StandardScaler` in HMM features |
| CVXPY | 1.9.3 | 1.9.3 | Backtest weight-oracle dependency only; optimizer math assigned elsewhere |
| QuantLib | 1.43 | 1.43 | Inventoried only; outside this cash-equity partition |

Evidence: `backend/uv.lock:202-211`, `backend/uv.lock:1446-1453`, `backend/uv.lock:2174-2177`, `backend/uv.lock:2303-2306`, `backend/uv.lock:3049-3052`, `backend/uv.lock:3253-3255`, `backend/uv.lock:3304-3306`, `backend/uv.lock:3574-3577`, `backend/uv.lock:3632-3638`, and `outputs/verify-risk-timeseries.txt:5-22`.

TA-Lib, pandas-ta, VectorBT, Empyrical, and Pyfolio are not declared, locked, or installed (`outputs/verify-risk-timeseries.txt:17-21`). No suitable independent installed technical-indicator oracle exists, so the evidence uses explicit canonical formulas. If a future external parity suite is desired, **TA-Lib (new dependency)** is the recommended oracle; it was not added here.

### Evidence and tolerance policy

- The main fixture has 600 deterministic daily returns, seed `20260923` (`outputs/verify-risk-timeseries.txt:23`). Backend and reference receive identical arrays or the same read-only OHLCV/portfolio fixture.
- Closed-form and library-delegated identities use `atol=rtol=1e-12`; displayed rounded outputs are compared at the same tolerance only after the reference is rounded identically.
- GARCH/EGARCH fits use `atol=1e-3`, `rtol=5e-3` for fitted volatility because two optimizer runs on the same 600 returns differed by up to 0.339% in the multi-horizon forecast path (`outputs/verify-risk-timeseries.txt:64-65`). Parametric normal VaR/CVaR use `atol=6e-4` to accommodate the implemented rounded constants `1.645` and `2.06` versus exact SciPy quantiles.
- HMM labels, transition values, probabilities, and state statistics are exact; rounded diagnostics use `atol=1e-4`, `rtol=1e-3` because the backend rounds Parkinson volatility to four decimals (`backend/app/services/regime_service.py:282-283`).
- Monte Carlo uses identical seeds and streams. It verifies implementation orchestration, not the real-world adequacy of 400 simulated paths.
- The EVT stress fixture intentionally exercises the lower shape boundary with 200 observations and 10 exceedances. It proves what clipping changes; it is not a claim that every fitted GPD is unstable. The ordinary 500-observation t(5) fixture matches exactly (`outputs/verify-risk-timeseries.txt:91-96`).
- These tolerances establish numerical agreement for these fixtures. They do not eliminate sampling, regime, liquidity, or parameter-estimation uncertainty.

## 2. Model inventory and classification

| Model family | Implemented location and classification |
|---|---|
| Realized annual return, volatility, Sharpe, Sortino, hit ratio | Hand-rolled, `backend/app/services/analytics_engine.py:846-883` |
| Historical 95% VaR/CVaR | Hand-rolled empirical tail estimator, `backend/app/services/analytics_engine.py:887-902` |
| Maximum drawdown, skew, excess kurtosis | Library primitives assembled by backend, `backend/app/services/analytics_engine.py:906-934` |
| Static normalized EWMA | Hand-rolled finite-sample weighted variance, `backend/app/services/volatility_service.py:66-110` |
| Recursive EWMA and normal parametric VaR/CVaR | Hand-rolled recursion, `backend/app/services/analytics_engine.py:1062-1093` |
| Rolling realized volatility and volatility cone | Hand-rolled rolling/quantile layer, `backend/app/services/volatility_service.py:26-63`, `backend/app/services/volatility_service.py:188-323` |
| AnalyticsEngine GARCH(1,1) | `arch` fit plus hand-rolled forecast/horizon/tail transformations, `backend/app/services/analytics_engine.py:978-1015` |
| VolatilityService GARCH(1,1) | `arch` fit plus hand-rolled horizon-RMS annualization, `backend/app/services/volatility_service.py:113-185` |
| AnalyticsEngine EGARCH(1,1) | `arch` fit plus hand-rolled tail transformations/error fallback, `backend/app/services/analytics_engine.py:1020-1060` |
| EVT-POT GPD VaR/ES | SciPy fit plus hand-rolled POT moments, clipping, and guards, `backend/app/services/tail_risk_service.py:25-155` |
| Student-t lower-tail dependence | Hand-rolled copula closed form and df approximation, `backend/app/services/tail_risk_service.py:158-232` |
| Gaussian HMM regime model and downstream regime summary | Backend feature/label/veto layer over `hmmlearn` plus hand-rolled regime compounding, `backend/app/services/regime_service.py:37-296`, `backend/app/utils/holdings.py:216-239` |
| Monte Carlo GBM, Student-t, stationary bootstrap | Hand-rolled orchestration over NumPy/SciPy/`arch`, `backend/app/services/monte_carlo_service.py:43-230` |
| Walk-forward backtest | Hand-rolled schedule, turnover, friction, equity, and metrics, `backend/app/services/backtest_service.py:18-193` |
| Technical indicators | Backend delegates to installed `stockstats`, `backend/app/services/indicators_service.py:32-53`, `backend/app/services/indicators_service.py:117-138` |
| Benchmark OLS beta/alpha/R² | statsmodels OLS/HAC assembly, `backend/app/services/analytics_engine.py:1098-1193` |
| QuantStats tear-sheet, performance history, monthly return, underwater, relative metrics | Library-delegated plus hand-rolled alignment/rebasing/compounding, `backend/app/api/analytics.py:1182-1296`, `backend/app/api/analytics.py:1360-1546` |
| Delivery-percentage anomaly z-score | Hand-rolled rolling z-score, `backend/app/services/india_data_service.py:200-247` |
| Cash-equity Amihud/ADV diagnostics | Hand-rolled liquidity formulas, `backend/app/services/india_data_service.py:26-52`, `backend/app/services/india_data_service.py:249-334` |

The regime-conditioned performance formulas are included with the HMM family in the evidence because they are the downstream regime summary (`backend/app/services/regime_service.py:324-347`).

## 3. Model-by-model verification

### 3.1 Realized annual return, volatility, Sharpe, Sortino, and hit ratio

**Implemented formula** (`backend/app/services/analytics_engine.py:858-882`):

```python
annual_return = returns.mean() * 252
annual_volatility = returns.std() * np.sqrt(252)
sharpe_ratio = (annual_return - risk_free_rate) / annual_volatility
target = risk_free_rate / 252
downside = np.minimum(0.0, returns.to_numpy() - target)
downside_deviation = np.sqrt(np.mean(downside ** 2)) * np.sqrt(252)
sortino_ratio = (annual_return - risk_free_rate) / downside_deviation
hit_ratio = (returns > 0).mean()
```

**Assumptions:** arithmetic annual mean, 252 sessions/year, sample standard deviation, zero risk-free rate for hit ratio, and full-sample denominator for target downside deviation. These are exactly the conventions in the cited lines.

**Reference and evidence:** independent NumPy/Pandas closed forms in `evidence/verify-risk-timeseries.py:221-243`; output `outputs/verify-risk-timeseries.txt:24-28`.

| Metric | Backend | Reference | Abs diff | Rel diff |
|---|---:|---:|---:|---:|
| Annual return | 0.114438204670 | 0.114438204670 | 0 | 0 |
| Annual volatility | 0.233553657687 | 0.233553657687 | 0 | 0 |
| Sharpe | 0.404353353337 | 0.404353353337 | 0 | 0 |
| Sortino | 0.592000975578 | 0.592000975578 | 0 | 0 |
| Hit ratio | 0.511666666667 | 0.511666666667 | 0 | 0 |

**Tolerance/verdict:** `atol=rtol=1e-12`, all PASS. **Final: MATCHES.**

**Limitations:** the short `<10` branch reports period return and zero ratios rather than annualized values (`backend/app/services/analytics_engine.py:852-857`); API-level annualization gates are outside this pure-function comparison (`backend/app/api/analytics.py:416-425`).

### 3.2 Historical 95% VaR and CVaR

**Implemented formula** (`backend/app/services/analytics_engine.py:887-902`):

```python
var_95 = np.percentile(returns, 5)
cvar_95 = returns[returns <= var_95].mean()
```

**Assumptions:** historical 5th-percentile return as loss VaR; interpolated NumPy percentile; tail defined inclusively as observations at or below VaR; no horizon scaling or parametric distribution.

**Reference/evidence:** exact independent percentile and conditional mean (`evidence/verify-risk-timeseries.py:244-256`), output `outputs/verify-risk-timeseries.txt:29-34`.

- VaR: backend/reference `-0.021381693265`; abs/rel difference `0/0`.
- CVaR: backend/reference `-0.0321308711441`; abs/rel difference `0/0`.

**Tolerance/verdict:** VaR `atol=1e-15, rtol=1e-12`; CVaR same; PASS. **Final: MATCHES.**

**Limitations:** this verifies the implemented empirical convention, not estimation error or tail dependence. Discrete samples and tied observations can change the inclusive tail count.

### 3.3 Maximum drawdown, skewness, and excess kurtosis

**Implemented formula** (`backend/app/services/analytics_engine.py:906-932`):

```python
cumulative_returns = (1 + returns).cumprod()
running_max = cumulative_returns.expanding().max()
drawdown = (cumulative_returns - running_max) / running_max
max_drawdown = drawdown.min()
skewness = returns.skew()
kurtosis = returns.kurtosis()
```

**Assumptions:** wealth starts at 1 immediately before the supplied return vector; pandas sample skew/Fisher excess kurtosis; peak includes the current observation.

**Reference/evidence:** Pandas wealth identity and SciPy `skew(..., bias=False)` / `kurtosis(..., fisher=True, bias=False)` (`evidence/verify-risk-timeseries.py:257-271`), output `outputs/verify-risk-timeseries.txt:35-40`.

- Max drawdown: `-0.314742563071` vs `-0.314742563071`; `0/0`.
- Shape vector maximum abs/rel difference: `5.55e-17 / 2.44e-16`.

**Tolerance/verdict:** `atol=rtol=1e-12`, PASS. **Final: MATCHES.**

**Limitations:** the evidence does not inject an initial pre-sample peak; that is the implemented definition.

### 3.4 Static normalized EWMA volatility

**Implemented formula** (`backend/app/services/volatility_service.py:101-110`):

```python
weights = (1.0 - decay) * (decay ** np.arange(n)[::-1])
weights = weights / weights.sum()
weighted_variance = np.sum(weights * (r ** 2))
return np.sqrt(weighted_variance) * annualization_factor
```

**Assumptions:** `lambda=0.94`, newest observation receives `(1-lambda)`, and finite-sample weights are renormalized to sum exactly to one.

**Reference/evidence:** normalized identity and unnormalized exponential-weight identity (`evidence/verify-risk-timeseries.py:272-288`), output `outputs/verify-risk-timeseries.txt:41-47`.

- Normalized reference: `0.184095753073`, abs/rel difference `2.78e-17 / 1.51e-16`, PASS.
- Unnormalized reference: `0.155110232506`; abs difference `0.0289855205662`, rel difference `0.186870460432`, FAIL against `1e-12`.

**Tolerance/verdict:** exact implementation matches; unnormalized convention differs materially on the 20-observation boundary fixture. **Final: DIVERGES (magnitude). No severity.**

**Limitations:** as history length grows, the raw weight sum approaches one and this convention difference decays. The evidence establishes the finite-sample distinction, not which business horizon is preferable.

### 3.5 Recursive EWMA and parametric normal VaR/CVaR

**Implemented formula** (`backend/app/services/analytics_engine.py:1062-1092`):

```python
var = np.var(r)
for x in r[-min(len(r), 60):]:
    var = lambda_val * var + (1.0 - lambda_val) * x * x
forecast_volatility = np.clip(np.sqrt(var * 252), 0.05, 1.20)
h_factor = np.sqrt(h / 252.0)
var_forecast = -forecast_volatility * 1.645 * h_factor
cvar_forecast = -forecast_volatility * 2.06 * h_factor
```

**Assumptions:** full-sample population variance initializes the recursion; only the last 60 observations are recursively updated; mean reversion is absent; annualization uses 252; normal tails use rounded constants 1.645 and 2.06; volatility is clipped to `[0.05,1.20]`.

**Reference/evidence:** independent initialized recursion plus exact SciPy normal tail factors (`evidence/verify-risk-timeseries.py:289-312`), output `outputs/verify-risk-timeseries.txt:48-56`.

- One-day volatility: `0.174139772184` vs `0.174139772184`; abs/rel `8.33e-17 / 4.78e-16`.
- Five-day VaR: `-0.0403504707714` vs `-0.0403468803633`; abs/rel `3.59e-6 / 8.90e-5`.
- Five-day CVaR: `-0.0505300728202` vs `-0.0505966157138`; abs/rel `6.65e-5 / 0.001315`.

**Tolerance/verdict:** volatility `1e-12`; tails `atol=6e-4, rtol=1e-4`; all PASS. **Final: MATCHES.**

**Limitations:** the 60-observation recursion window and full-sample seed are methodological choices, not consequences of the reference. The normal-tail approximation ignores skew/kurtosis.

### 3.6 Rolling realized volatility and volatility cone

**Implemented formula** (`backend/app/services/volatility_service.py:58-63`, `backend/app/services/volatility_service.py:240-281`):

```python
rolling_std = clean_returns.rolling(window, min_periods=min_periods).std(ddof=1)
rolling_vol = rolling_std * np.sqrt(252)
rank = np.sum(vol_values <= current) / len(vol_values) * 100
```

**Assumptions:** contiguous observations after `dropna`, sample standard deviation, 252 sessions/year, empirical distribution of rolling-vol values, inclusive percentile rank.

**Reference/evidence:** Pandas rolling `ddof=1` and NumPy quantiles (`evidence/verify-risk-timeseries.py:313-331`), output `outputs/verify-risk-timeseries.txt:57-62`. Rolling 21-day vectors and rounded cone vectors both have abs/rel difference `0/0`.

**Tolerance/verdict:** `atol=rtol=1e-12`, PASS. **Final: MATCHES.**

**Limitations:** `dropna()` compresses interior missing observations into the rolling window. The service explicitly returns null quantiles and `insufficient_data` when fewer than two rolling values exist (`backend/app/services/volatility_service.py:244-268`).

### 3.7 AnalyticsEngine GARCH(1,1) and parametric tail

**Implemented formula** (`backend/app/services/analytics_engine.py:987-1014`):

```python
scaled_returns = clean_returns * 100.0
model = arch_model(scaled_returns, vol='Garch', p=1, q=1,
                   mean='Zero', dist='normal', rescale=False)
forecast = fitted_model.forecast(horizon=h, method='analytic')
volatility_forecast = np.sqrt(variance_forecast * 252) / 100.0
vol_final = volatility_forecast[-1]
h_factor = np.sqrt(h / 252.0)
var_forecast = -vol_final * 1.645 * h_factor
cvar_forecast = -vol_final * 2.06 * h_factor
```

**Assumptions:** zero conditional mean, Gaussian innovations, 252-day annualization, percentage scaling for optimization, normal tails. The crucial units issue is that `vol_final` is already annualized cumulative `h`-step volatility.

**Reference/evidence:** direct `arch 8.0.0` GARCH forecast and exact SciPy normal tails (`evidence/verify-risk-timeseries.py:332-353`), output `outputs/verify-risk-timeseries.txt:63-71`.

- Terminal annualized volatility: `0.212652388020` vs `0.212980545081`; abs/rel `0.0003281571 / 0.0015407842`, PASS.
- Five-day VaR: `-0.0492743493324` vs `-0.0220682004756`; abs/rel `0.0272061489 / 1.232821357`, FAIL.
- Five-day CVaR: `-0.0617052642096` vs `-0.0276744137069`; abs/rel `0.0340308505 / 1.229686412`, FAIL.

**Tolerance/verdict:** fitted volatility `atol=1e-3, rtol=5e-3`; tails `atol=6e-4, rtol=1e-4`. **Final: BUG. Severity: High.**

**Why it is wrong:** the correct conversion from annualized `h`-step volatility to return-space `h`-day VaR is `vol_final / sqrt(252) * z`; the backend uses `vol_final * sqrt(h/252) * z`, double-counting `sqrt(h)` (`backend/app/services/analytics_engine.py:999-1008`). This is not a convention difference.

**Limitations:** returns are clipped to ±20% before fitting and output volatility to `[0.05,1.20]` (`backend/app/services/analytics_engine.py:982-1000`). The evidence uses a five-day horizon; the route permits horizons 1–30 (`backend/app/api/analytics.py:452-456`).

### 3.8 VolatilityService horizon-average GARCH(1,1)

**Implemented formula** (`backend/app/services/volatility_service.py:150-162`):

```python
var_steps = forecasts.variance.iloc[-1].values
mean_daily_variance = np.mean(var_steps)
ann_vol = np.sqrt(mean_daily_variance * 252.0) / 100.0
```

**Assumptions:** the reported horizon statistic is root-mean-square cumulative variance over the horizon, not terminal-step volatility.

**Reference/evidence:** direct `arch` horizon variance (`evidence/verify-risk-timeseries.py:354-370`), output `outputs/verify-risk-timeseries.txt:72-77`. Backend/reference annualized RMS: `0.217171400193 / 0.217171400193`; abs/rel `0/0`.

**Tolerance/verdict:** `atol=rtol=1e-12`, PASS. **Final: MATCHES.**

**Limitations:** this separate service path is clean; it does not repair the AnalyticsEngine parametric VaR path.

### 3.9 AnalyticsEngine EGARCH(1,1)

**Implemented formula/error path** (`backend/app/services/analytics_engine.py:1029-1060`):

```python
model = arch_model(scaled_returns, vol='EGARCH', p=1, q=1,
                   mean='Zero', dist='normal', rescale=False)
forecast = fitted_model.forecast(horizon=h)
...
except Exception:
    return self._empty_forecast(h, "EGARCH")
```

No simulation method is supplied. Installed `arch` explicitly rejects analytic EGARCH forecasting for `horizon>1` (`backend/.venv/Lib/site-packages/arch/univariate/volatility.py:2755-2759`) and supports simulation as a distinct method (`backend/.venv/Lib/site-packages/arch/univariate/volatility.py:749-780`).

**Assumptions:** one-step EGARCH works under the default analytic method; longer horizons require simulation, which the backend does not request.

**Reference/evidence:** direct analytic one-step plus 2,000-path simulation for five steps, seed 100 (`evidence/verify-risk-timeseries.py:371-421`), output `outputs/verify-risk-timeseries.txt:78-89`.

- One-step volatility: `0.195422141849` vs `0.196166891955`; abs/rel `0.0007447501 / 0.0037965127`, PASS.
- One-step VaR: `-0.0202506701970` vs `-0.0203260363367`; abs/rel `7.54e-5 / 0.0037078630`, PASS.
- Five-step backend volatility/VaR: `None/None`; direct simulation: `0.220720188989 / -0.0228701517209`; non-finite mismatch, FAIL.

**Tolerance/verdict:** one-step `atol=1e-3, rtol=5e-3` for volatility and `atol=6e-4` for tails; five-step nulls fail every finite-reference tolerance. **Final: BUG. Severity: High.**

**Why it is wrong:** the API accepts horizons through 30 (`backend/app/api/analytics.py:452-456`), while the implementation returns an “Insufficient data” payload for every multi-step request, despite installed `arch` providing simulation forecasts.

**Limitations:** simulation introduces Monte Carlo error; the evidence fixes simulations and seed. The null failure itself is deterministic.

### 3.10 EVT-POT GPD VaR and expected shortfall

**Implemented formula** (`backend/app/services/tail_risk_service.py:95-120`):

```python
c_est, loc_est, scale_est = stats.genpareto.fit(exceedances, floc=0.0)
xi = np.clip(c_est, -0.5, 0.95)
ratio = (n_total / n_u) * alpha
var_evt_loss = threshold_u + (beta / xi) * (ratio ** (-xi) - 1)
es_evt_loss = (var_evt_loss + beta - xi * threshold_u) / (1.0 - xi)
```

**Assumptions:** independent GPD fit above the empirical POT threshold, location fixed at zero, threshold below confidence level, and finite first moment (`xi<1`). The code additionally imposes an undocumented fitted-shape interval and reports the clipped value as `gpd_shape_xi` (`backend/app/services/tail_risk_service.py:98-115`, `backend/app/services/tail_risk_service.py:142-151`).

**Reference/evidence:** SciPy fit and untruncated POT moments (`evidence/verify-risk-timeseries.py:422-449`), output `outputs/verify-risk-timeseries.txt:90-102`.

Ordinary fixture:

- Shape `0.3054/0.3054`, VaR `-0.048268/-0.048268`, ES `-0.072361/-0.072361`; all `0/0`, PASS.

Boundary fixture:

- Shape: `-0.5` vs `-2.01301977674`; abs/rel `1.51301977674 / 0.751616945955`, FAIL.
- VaR: `-0.069798` vs `-0.0301336751272`; abs/rel `0.0396643248728 / 1.31627903684`, FAIL.
- ES: `-0.088620` vs `-0.0309544261044`; abs/rel `0.0576655738956 / 1.86291852742`, FAIL.

**Tolerance/verdict:** ordinary rounded outputs `1e-12`, PASS; boundary fit/moments `atol=rtol=1e-6`, FAIL. **Final: BUG. Severity: Medium.**

**Why it is wrong:** the response labels the clipped shape as the fitted GPD parameter and uses that altered shape in both moments. The ordinary path proves the formulas are otherwise correct.

**Limitations:** the boundary fixture has only 10 exceedances, the minimum accepted by the service. The report does not claim the untruncated fit is reliable at that count; it shows that silently replacing it with a different fitted value is mathematically material.

### 3.11 Student-t lower-tail dependence

**Implemented formula** (`backend/app/services/tail_risk_service.py:204-231`):

```python
rho = np.corrcoef(r_a, r_b)[0, 1]
arg = -np.sqrt(((nu + 1.0) * (1.0 - rho)) / (1.0 + rho))
lambda_l = 2.0 * stats.t.cdf(arg, df=nu + 1.0)
```

**Assumptions:** Pearson correlation is the Gaussian dependence parameter; `nu` is the clipped average of independently fitted univariate Student-t dfs; returns are raw because fitted t location/scale absorb those moments.

**Reference/evidence:** direct SciPy t-CDF closed form with fixed `df=6` (`evidence/verify-risk-timeseries.py:450-462`), output `outputs/verify-risk-timeseries.txt:103-109`.

- `lambda_L`: `0.221765394253/0.221765394253`; abs/rel `0/0`.
- `rho`: `0.591167024508/0.591167024508`; abs/rel `0/0`.

**Tolerance/verdict:** `atol=rtol=1e-12`, PASS. **Final: MATCHES.**

**Limitations:** this verifies the stated approximation; it is not a joint t-copula fit. The backend explicitly documents that approximation (`backend/app/services/tail_risk_service.py:186-192`).

### 3.12 Gaussian HMM regime detection, labels, diagnostics, veto, and regime summary

**Implemented formula/assembly** (`backend/app/services/regime_service.py:178-245`):

```python
ret21 = np.log(close / close.shift(21)).dropna()
vol21 = (ret_1d.rolling(21).std() * np.sqrt(252)).dropna()
x_scaled = StandardScaler().fit_transform(feats.values)
hmm = GaussianHMM(n_components=3, covariance_type='full',
                  init_params='mc', params='mc',
                  random_state=100, n_iter=200, tol=1e-4)
...
states = hmm.predict(x_scaled)
display_states, veto_days = apply_crash_veto(states, label_map, ret21_values)
```

Labels are ordered by compound state CAGR (`backend/app/services/regime_service.py:37-57`); state CAGR and average realized volatility are computed at `backend/app/services/regime_service.py:214-233`; crash relabeling is a display override below `-0.10` over 21 days (`backend/app/services/regime_service.py:27-34`, `backend/app/services/regime_service.py:79-102`).

**Assumptions:** exactly three Gaussian states, 21-day log holding return and annualized sample volatility, standardized features, sticky EM initialization, economically sorted labels, and an explicit crash veto that does not refit the HMM.

**Reference/evidence:** independent feature construction and direct `hmmlearn 0.3.3` fit with identical settings (`evidence/verify-risk-timeseries.py:466-637`), output `outputs/verify-risk-timeseries.txt:110-122`.

- Current regime: `bull/bull`.
- Current probabilities and all nine transition values: exact `0/0`.
- State labels and nine state statistics: exact `0/0`.
- Rounded diagnostic vector max abs/rel: `2.10e-5 / 1.76e-4`, PASS.
- Six-value crash-veto fixture and regime-conditioned 80-day return/volatility summary: exact `0/0`.

**Tolerance/verdict:** exact identity for HMM outputs; rounded diagnostics `atol=1e-4, rtol=1e-3`; all PASS. **Final: MATCHES.**

**Limitations:** direct reference uses the same installed estimator, so it verifies backend feature/orchestration/label/veto math rather than an alternative HMM algorithm. The fixture has 400 price rows and 379 model observations. A single fixture cannot establish regime stability across market histories.

### 3.13 Monte Carlo goal probability: GBM, Student-t, stationary bootstrap

**Implemented formulas** (`backend/app/services/monte_carlo_service.py:48-137`, `backend/app/services/monte_carlo_service.py:202-226`):

```python
mu_annual = r.mean() * TRADING_DAYS
sigma_annual = r.std(ddof=1) * np.sqrt(TRADING_DAYS)
log_increments = (mu - 0.5 * sigma**2) / TRADING_DAYS + sigma / sqrt(252) * Z
...
innovations = student_t.rvs(...)
z = np.clip((innovations - loc) / analytic_std, -8, 8)
daily_sim = daily.mean() + daily.std(ddof=1) * z
...
StationaryBootstrap(BLOCK_LENGTH, data, seed=...)
prob_success = np.mean(terminal >= target)
```

**Assumptions:** iid lognormal GBM; Student-t innovations winsorized at eight analytic standard deviations, moment-matched to sample mean/std, and simple returns floored at -95%; stationary bootstrap with block length 21; 252 sessions/year; 400 paths for this test.

**Reference/evidence:** independent NumPy/SciPy/`arch` implementations using identical seeds and full path comparison (`evidence/verify-risk-timeseries.py:578-725`), output `outputs/verify-risk-timeseries.txt:123-138`.

| Method | Full path max abs/rel | Goal output max abs/rel | Success probability |
|---|---:|---:|---:|
| GBM | `0/0` | `0/0` | 0.4225 |
| Student-t | `0/0` | `0/0` | 0.3725 |
| Stationary bootstrap | `0/0` | `0/0` | 0.4250 |

**Tolerance/verdict:** paths `atol=1e-9, rtol=1e-12`; rounded goal vectors `1e-12`; all PASS. **Final: MATCHES.**

**Limitations:** exact agreement verifies the backend's stated algorithms and seeded streams. It does not make 400 paths sufficient for production confidence intervals, and the three models embody materially different distributional assumptions (`backend/app/services/monte_carlo_service.py:8-17`).

### 3.14 Walk-forward backtest mechanics

**Implemented formula** (`backend/app/services/backtest_service.py:53-60`, `backend/app/services/backtest_service.py:93-123`, `backend/app/services/backtest_service.py:136-167`):

```python
rebalance_indices = list(range(lookback_days, len(returns), rebalance_freq_days))
rebalance_indices.append(len(returns))
turnover = 0.5 * np.sum(np.abs(new_weights - current_weights))
cost_penalty = turnover * cost_factor
day_strat_ret = (1.0 - cost_penalty) * (1.0 + day_strat_ret) - 1.0
strat_cum = np.cumprod(1.0 + strat_rets)
strat_sharpe = (strat_mu_d * 252 - risk_free_rate) / strat_vol
```

**Assumptions:** weights are fitted only on the preceding lookback, held static to the next rebalance, one-way turnover is half-L1, the stated bps rate is applied once at each rebalance, compounding is multiplicative, and the “benchmark” is equal weight over the same assets.

**Reference/evidence:** independent schedule/P&L/metric loop. `min_vol` is used only as the assigned optimizer dependency and is not adjudicated here (`evidence/verify-risk-timeseries.py:642-843`), output `outputs/verify-risk-timeseries.txt:139-146`.

- Ten reported metrics: abs/rel `0/0`.
- 120-point rounded equity curve: abs/rel `0/0`.
- First OOS date: `2022-03-28`; 120 OOS days.

**Tolerance/verdict:** `atol=rtol=1e-12`, all PASS. **Final: MATCHES.**

**Limitations:** taxes, market impact, capacity, borrow constraints, and cash are absent because they are absent from the implementation. Cost-rate side convention cannot be inferred beyond the code's half-L1/round-trip interpretation.

### 3.15 Technical indicators: SMA, EMA, RSI, MACD, Bollinger, ATR, VWMA, MFI

**Backend implementation:** the service normalizes OHLCV and delegates all supported indicators to `stockstats` (`backend/app/services/indicators_service.py:60-94`, `backend/app/services/indicators_service.py:117-138`). Exact delegated formulas include:

- SMA rolling mean: `backend/.venv/Lib/site-packages/stockstats.py:1042-1043`, `backend/.venv/Lib/site-packages/stockstats.py:1129-1130`.
- RSI/SMMA: `backend/.venv/Lib/site-packages/stockstats.py:517-531`, `backend/.venv/Lib/site-packages/stockstats.py:588-591`.
- MACD: `backend/.venv/Lib/site-packages/stockstats.py:1227-1245`.
- Bollinger: `backend/.venv/Lib/site-packages/stockstats.py:1207-1225`.
- ATR/TR: `backend/.venv/Lib/site-packages/stockstats.py:658-667`, `backend/.venv/Lib/site-packages/stockstats.py:817-829`.
- VWMA: `backend/.venv/Lib/site-packages/stockstats.py:1412-1422`.
- MFI: `backend/.venv/Lib/site-packages/stockstats.py:1454-1479`.

**Assumptions:** 260 valid OHLCV rows; default windows 10 EMA, 50/200 SMA, 14 RSI/ATR/MFI/VWMA, 20 Bollinger, 12/26/9 MACD. Canonical reference uses recursive EMA/Wilder seeds, full-window SMA readiness, and population standard deviation for Bollinger.

**Reference/evidence:** explicit independent formulas because TA-Lib/pandas-ta are absent (`evidence/verify-risk-timeseries.py:761-878`), output `outputs/verify-risk-timeseries.txt:147-179`.

| Indicator family | Backend vs reference | Abs diff | Rel diff | Check verdict |
|---|---:|---:|---:|---|
| EMA10 | 103.712213192 / 103.712213192 | 2.84e-14 | 2.74e-16 | MATCHES |
| SMA50 | 101.873530227 / 101.873530227 | 2.84e-14 | 2.79e-16 | MATCHES |
| SMA200 | 102.478455996 / 102.478455996 | 2.84e-14 | 2.77e-16 | MATCHES |
| RSI14 | 52.3443054097 / 52.3443054172 | 7.51e-9 | 1.43e-10 | MATCHES |
| Boll middle | 102.747014144 / 102.747014144 | 0 | 0 | MATCHES |
| Boll upper | 106.029686557 / 105.946567435 | 0.0831191219 | 0.0007845381 | DIVERGES |
| Boll lower | 99.4643417319 / 99.5474608538 | 0.0831191219 | 0.0008349698 | DIVERGES |
| MACD / signal / hist | see output | ≤8.66e-9 | ≤1.70e-8 | MATCHES |
| ATR14 | 2.62363804672 / 2.6236380447 | 2.02e-9 | 7.69e-10 | MATCHES |
| VWMA14 | 102.776789030 / 102.776789030 | 0 | 0 | MATCHES |
| MFI14 | 0.524678528716 / 52.4678528716 | 51.9431743428 | 0.99 | BUG |

**Tolerance/verdict:** exact formulas use `1e-10`; recursive-seed comparisons use `1e-7`. MFI fails by 51.94 points. **Final family: BUG. Severity: Medium.**

**Why it is wrong:** `stockstats` computes `pos_sum / (pos_sum + neg_sum)` without multiplying by 100 (`backend/.venv/Lib/site-packages/stockstats.py:1471-1479`), while the backend description promises 80/20 MFI thresholds (`backend/app/services/indicators_service.py:45-47`).

**Additional convention findings:** Bollinger uses pandas rolling sample standard deviation (`ddof=1`) through `mov_std` (`backend/.venv/Lib/site-packages/stockstats.py:1396-1398`) while the canonical reference uses population sigma; this is DIVERGES, not wrong arithmetic. `min_periods=1` produces 49 extra 50-SMA and 199 extra 200-SMA warmup values (`outputs/verify-risk-timeseries.txt:174-175`), but the API fetches a warmup window and filters output afterward (`backend/app/services/indicators_service.py:147-153`, `backend/app/services/indicators_service.py:180-183`).

**Limitations:** the test validates mature final values on a 260-row fixture, not every historical row. A future external oracle may use different EMA/Wilder seed or Bollinger sigma conventions; those are explicitly classified rather than hidden.

### 3.16 Benchmark-relative OLS beta, alpha, and R²

**Implemented formula** (`backend/app/services/analytics_engine.py:1125-1145`, `backend/app/services/analytics_engine.py:1166-1188`):

```python
X = sm.add_constant(aligned_benchmark.loc[active])
model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
alpha = model.params.iloc[0]
beta = model.params.iloc[1]
r_squared = model.rsquared
```

**Assumptions:** active asset/benchmark overlap, intercept plus market factor, HAC(5) covariance, raw daily intercept annualized by 252, and no risk-free adjustment in alpha.

**Reference/evidence:** direct statsmodels OLS/HAC on identical 260-day returns (`evidence/verify-risk-timeseries.py:880-919`), output `outputs/verify-risk-timeseries.txt:180-185`.

- Backend/reference: alpha `0.000181/0.000181`; annualized alpha `0.0457/0.0457`; beta `1.0243/1.0243`; R² `0.9303/0.9303`; adjusted R² `0.93/0.93`; all `0/0`.

**Tolerance/verdict:** `atol=rtol=1e-12`, PASS. **Final: MATCHES.**

**Limitations:** this verifies coefficient/orchestration math. Missing-return portfolio construction is portfolio-layer behavior and is assigned to the other verifier.

### 3.17 QuantStats tear-sheet, performance history, monthly compounding, underwater curve, and relative metrics

**Implemented formulas** (`backend/app/api/analytics.py:1422-1433`, `backend/app/api/analytics.py:1466-1528`, `backend/app/api/analytics.py:1257-1278`):

```python
metrics = {
    "total_return": qs.stats.comp(port_ret),
    "cagr": qs.stats.cagr(port_ret),
    "sharpe": qs.stats.sharpe(port_ret, rf=0.02),
    ...
}
beta = p.cov(b) / b.var()
alpha_ann = (p.mean() - beta * b.mean()) * 252
m_series = (1.0 + port_ret).groupby([year, month]).prod() - 1.0
cum_bench = (1.0 + bench_ret.loc[common_dates]).cumprod()
cum_bench = cum_bench / cum_bench.iloc[0]
bench_val_series = initial_val * cum_bench
```

**Assumptions:** simple close-to-close returns, QuantStats conventions, overlap by index, 30-day minimum for annualized relative metrics, and benchmark rebasing to the first common portfolio value.

**Reference/evidence:** direct QuantStats 0.0.81 calls, NumPy/Pandas beta/alpha, compounding, drawdown, and performance-history rebase identities (`evidence/verify-risk-timeseries.py:920-1072`), output `outputs/verify-risk-timeseries.txt:186-197`.

- Eleven tear-sheet metrics: abs/rel `0/0`.
- Beta/alpha: `-0.0099/0.0012` vs the same; `0/0`.
- Nine monthly compounded returns: `0/0`.
- 179-point underwater curve: `0/0`.
- 540 flattened performance-history fields (portfolio value, return, rebased benchmark value): `0/0`.

**Tolerance/verdict:** `atol=rtol=1e-12`, all PASS. **Final: MATCHES.**

**Limitations:** QuantStats itself supplies the metric definitions. This proves direct delegation and the backend's alignment/compounding/rebasing wrappers, not a second independent implementation of every QuantStats convention.

### 3.18 Delivery-percentage rolling z-score anomaly

**Implemented formula** (`backend/app/services/india_data_service.py:221-240`):

```python
current_deliv = deliv_series[0]
historical_deliv = deliv_series[1:lookback_days + 1]
mean_deliv = np.mean(historical_deliv)
std_deliv = np.std(historical_deliv) or 1.0
z_score = (current_deliv - mean_deliv) / std_deliv
is_anomaly = z_score >= sigma_threshold
```

**Assumptions:** newest observation excluded from its baseline, positive-only spike detection, population standard deviation (`ddof=0`), and a zero standard deviation replaced by one percentage point.

**Reference/evidence:** SciPy sample-standard-deviation z-score on the same six values (`evidence/verify-risk-timeseries.py:1075-1097`), output `outputs/verify-risk-timeseries.txt:198-203`.

- Backend z: `3.53`, anomaly `True`.
- Sample-z reference: `1.68`, anomaly `False`.
- Abs/rel difference: `1.85 / 1.10119047619`.

**Tolerance/verdict:** displayed-value tolerance `atol=0.0051`, FAIL. **Final: DIVERGES (magnitude). No severity.**

**Limitations:** the difference changes the fixture's threshold decision, but `ddof=0` versus `ddof=1` is a declared convention difference rather than an independently provable backend error. The zero-variance fallback is outside that taxonomy distinction.

### 3.19 Cash-equity Amihud illiquidity and ADV liquidation diagnostics

**Implemented formula** (`backend/app/services/india_data_service.py:26-52`, `backend/app/services/india_data_service.py:285-301`):

```python
ratio = (abs(returns) / rupee_volume) * 1e6
amihud = np.nanmean(ratio)
days = position_value / (participation_rate * adv_value)
adv_shares = volume.tail(30).mean()
adv_rupees = (close * volume).tail(30).mean()
```

**Assumptions:** rupee-volume scaling, 30-session simple mean ADV, fixed participation rates, and positive-price/volume observations.

**Reference/evidence:** direct NumPy identities and the production async method with a read-only position/frame fixture (`evidence/verify-risk-timeseries.py:1099-1125`), output `outputs/verify-risk-timeseries.txt:204-211`.

- Amihud: `9.3879369435e-05 / 9.3879369435e-05`; `0/0`.
- Ten-percent ADV days: `0.01/0.01`; `0/0`.
- Displayed ADV shares/rupees/20%-days: `104760/105372544.47/0.0`; `0/0`.

**Tolerance/verdict:** `atol=rtol=1e-12`, all PASS. **Final: MATCHES.**

**Limitations:** this verifies the formulas only. The fixture's very liquid position rounds 20%-ADV liquidation to `0.0`; nonzero fixtures use the same identity.

## 4. Summary table

| Model | Verdict | Severity | Reference | Max abs | Max rel |
|---|---|---|---|---:|---:|
| Realized annual return/volatility/Sharpe/Sortino/hit ratio | MATCHES | — | NumPy/Pandas | 0 | 0 |
| Historical 95% VaR/CVaR | MATCHES | — | NumPy percentile/tail mean | 0 | 0 |
| Drawdown/skew/excess kurtosis | MATCHES | — | Pandas/SciPy | 5.55e-17 | 2.44e-16 |
| Static normalized EWMA | DIVERGES | — | Exponential-weight identity | 0.0289855 | 0.186870 |
| Recursive EWMA + normal tails | MATCHES | — | Independent recursion/SciPy | 6.65e-5 | 0.001315 |
| Rolling realized volatility/cone | MATCHES | — | Pandas/NumPy | 0 | 0 |
| AnalyticsEngine GARCH + tails | BUG | High | arch/SciPy | 0.0340309 | 1.232821 |
| VolatilityService horizon GARCH | MATCHES | — | arch | 0 | 0 |
| AnalyticsEngine EGARCH + tails | BUG | High | arch analytic/simulation | ∞ | ∞ |
| EVT-POT GPD VaR/ES | BUG | Medium | SciPy/untruncated POT | 1.513020 | 1.862919 |
| Student-t lower-tail dependence | MATCHES | — | SciPy t-CDF | 0 | 0 |
| HMM regime/veto/summary | MATCHES | — | Independent features/hmmlearn | 2.10e-5 | 1.76e-4 |
| Monte Carlo GBM/t/bootstrap | MATCHES | — | NumPy/SciPy/arch same seed | 0 | 0 |
| Walk-forward backtest | MATCHES | — | Independent P&L loop | 0 | 0 |
| Technical indicators | BUG | Medium | Independent canonical formulas | 51.9432 | 0.99 |
| OLS beta/alpha/R² | MATCHES | — | statsmodels | 0 | 0 |
| Tear-sheet/performance/relative metrics | MATCHES | — | QuantStats/NumPy/Pandas | 0 | 0 |
| Delivery z-score | DIVERGES | — | SciPy sample z | 1.85 | 1.101190 |
| Amihud/ADV diagnostics | MATCHES | — | NumPy | 0 | 0 |

Source: `outputs/verify-risk-timeseries.txt:212-237`.

## 5. Models checked and found clean

The following 13 family-level models are clean: realized performance ratios; historical VaR/CVaR; drawdown and return shape; recursive EWMA; rolling realized volatility/cone; VolatilityService GARCH; Student-t tail dependence; Gaussian HMM regime detection; all three Monte Carlo engines; walk-forward backtest; benchmark OLS; QuantStats/performance/relative metrics; and Amihud/ADV diagnostics. The exact list and counts are emitted at `outputs/verify-risk-timeseries.txt:212-237`.

Within the technical-indicator family, the following mature values are clean: EMA10, SMA50, SMA200, RSI14, Bollinger middle, MACD/signal/histogram, ATR14, and VWMA14 (`outputs/verify-risk-timeseries.txt:147-179`). Bollinger outer bands are DIVERGES by the sample/population-sigma convention; MFI is BUG.

No model was omitted because a reference was unavailable. The only area without a second installed technical-indicator package used explicit independent formulas and is marked as such.

## 6. Partition boundaries and traced dependencies

The following were inventoried but deliberately not adjudicated here to avoid duplication with the assigned portfolio/correlation verifier:

- HRP, min-vol, max-Sharpe, min-CVaR, and Black-Litterman: `backend/app/services/optimization_service.py:35-36`, `backend/app/services/optimization_service.py:76-194`, `backend/app/services/optimization_service.py:197-330`.
- Euler volatility and historical-CVaR risk contribution: `backend/app/api/analytics.py:1556-1637`.
- Inverse-volatility sizing and target-volatility scaling: `backend/app/services/analytics_engine.py:634-656`.
- HHI/effective positions/diversification and correlation-heavy risk-score legs: `backend/app/services/analytics_engine.py:216-237`, `backend/app/services/analytics_engine.py:737-795`.
- Rolling pairwise-correlation regime-break monitor: `backend/app/services/correlation_service.py:17-146`.
- Cointegration, Johansen, OU half-life, and spread z-score: `backend/app/services/cointegration_service.py:75-147`, `backend/app/services/cointegration_service.py:153-268`.

The backtest evidence used min-vol only as a fixed weight oracle; it did not audit that optimizer (`evidence/verify-risk-timeseries.py:727-843`).

## 7. Reproduction

Run from the repository root. No shell redirection is used; the Python script itself writes and prints the output.

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:MPLBACKEND = 'Agg'
uv run --project backend ruff check --no-cache ".scratch/backend-deep-audit/quant/evidence/verify-risk-timeseries.py"
uv run --project backend python ".scratch/backend-deep-audit/quant/evidence/verify-risk-timeseries.py"
```

Expected terminal tail:

```text
VERDICT_COUNT|MATCHES|13
VERDICT_COUNT|DIVERGES|2
VERDICT_COUNT|BUG|4
VERDICT_COUNT|REPLACE-WITH-LIBRARY|0
SUMMARY_END
SCRIPT_STATUS|SUCCESS
```

Pytest was not run because the configured pytest command writes coverage data and HTML coverage (`backend/pyproject.toml:82-88`), which would violate this audit's strict write allowlist. The required evidence runner completed successfully and its no-cache Ruff gate passed.
