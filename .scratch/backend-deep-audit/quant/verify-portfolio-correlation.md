# Independent Quant Verification: Portfolio and Correlation Models

Audit date: 2026-09-24  
Scope: cash-equity portfolio construction, portfolio analytics, risk models, rolling correlation, and pairs statistics. Out-of-scope instruments and investment recommendations are not included.

## 1. Read-only statement and installed-library inventory

This was a documentation/evidence-only audit. No backend source, test, configuration, database, dependency, lockfile, or Git state was modified. The only written artifacts are:

- `quant/verify-portfolio-correlation.md` — this report
- `quant/evidence/verify-portfolio-correlation.py` — deterministic evidence runner
- `quant/outputs/verify-portfolio-correlation.txt` — runner-generated numeric evidence

The runner uses seed `20260923`, no network calls, and no backend writes (`quant/outputs/verify-portfolio-correlation.txt:1-2`). It completed successfully with 92 comparison cases: **81 MATCHES, 2 DIVERGES (magnitude), 9 BUG (wrong math)** (`quant/outputs/verify-portfolio-correlation.txt:200-204`).

### 1.1 Declared dependencies

`backend/pyproject.toml:11-42` declares NumPy, pandas, SciPy, arch, quantstats, statsmodels, scikit-learn, cvxpy, QuantLib, hmmlearn, and related runtime dependencies. The lockfile pins the quant stack as follows:

| Library | Lock evidence | Runtime evidence | Audit role |
|---|---:|---:|---|
| NumPy | `backend/uv.lock:2174-2176` | `2.5.3` (`quant/outputs/verify-portfolio-correlation.txt:7`) | Linear algebra, quantiles, RNG, covariance identities |
| pandas | `backend/uv.lock:2303-2305` | `3.0.6` (`quant/outputs/verify-portfolio-correlation.txt:8`) | Return alignment, rolling statistics, groupby compounding |
| SciPy | `backend/uv.lock:3304-3309` | `1.18.1` (`quant/outputs/verify-portfolio-correlation.txt:9`) | Optimization, distributions, GPD, Student-t |
| statsmodels | `backend/uv.lock:3574-3584` | `0.15.0` (`quant/outputs/verify-portfolio-correlation.txt:10`) | Engle-Granger, Johansen, OLS factor reference |
| quantstats | `backend/uv.lock:3049-3061` | `0.0.81` (`quant/outputs/verify-portfolio-correlation.txt:11`) | Tear-sheet metrics and drawdown series |
| arch | `backend/uv.lock:202-211` | `8.0.0` (`quant/outputs/verify-portfolio-correlation.txt:12`) | GARCH/EGARCH and stationary bootstrap |
| cvxpy | `backend/uv.lock:862-874` | `1.9.3` (`quant/outputs/verify-portfolio-correlation.txt:13`) | Minimum variance, tangency, CVaR, Black-Litterman |
| scikit-learn | `backend/uv.lock:3253-3262` | `1.9.1` (`quant/outputs/verify-portfolio-correlation.txt:17`) | Installed; not needed as a portfolio reference here |
| hmmlearn | `backend/uv.lock:1446-1453` | `0.3.3` (`quant/outputs/verify-portfolio-correlation.txt:18`) | Installed; standalone market-regime HMM is outside this portfolio/correlation partition |
| QuantLib | `backend/uv.lock:3022-3024` | `1.43` (`quant/outputs/verify-portfolio-correlation.txt:19`) | Installed; not used by the reviewed portfolio formulas |
| Clarabel | `backend/uv.lock:605-612` | `0.11.1` (`quant/outputs/verify-portfolio-correlation.txt:14`) | Backend CVXPY solver |
| OSQP | `backend/uv.lock:2259-2267` | `1.1.3` (`quant/outputs/verify-portfolio-correlation.txt:15`) | Installed CVXPY solver |
| SCS | `backend/uv.lock:3375-3382` | `3.3.1` (`quant/outputs/verify-portfolio-correlation.txt:16`) | Installed CVXPY solver |

CVXPY reports `CLARABEL,SCS,SCIPY,HIGHS,OSQP` as installed solvers (`quant/outputs/verify-portfolio-correlation.txt:22`).

### 1.2 Dedicated portfolio libraries absent

Neither `riskfolio-lib` nor `PyPortfolioOpt` is installed (`quant/outputs/verify-portfolio-correlation.txt:20-21`); neither appears in the declared quant dependencies at `backend/pyproject.toml:11-42`. The optimization service explicitly implements its own HRP/CVXPY stack (`backend/app/services/optimization_service.py:4-13`).

No model received `REPLACE-WITH-LIBRARY`: there is no installed dedicated portfolio library available as a runnable reference, and this audit used the installed NumPy/SciPy/cvxpy/statsmodels/quantstats/arch stack plus transparent independent formulas. No package was installed.

## 2. Exact model inventory and implementation lines

| Model family | Exact implementation |
|---|---|
| Price cleaning, returns, portfolio returns | `backend/app/services/analytics_engine.py:57-75`, `backend/app/services/analytics_engine.py:837-844`, `backend/app/api/analytics.py:1329-1335` |
| Annual return, volatility, Sharpe, Sortino, hit ratio | `backend/app/services/analytics_engine.py:846-883` |
| Historical VaR/CVaR and drawdown | `backend/app/services/analytics_engine.py:887-902`, `backend/app/services/analytics_engine.py:906-920` |
| quantstats tear-sheet suite | `backend/app/api/analytics.py:1422-1437` |
| Benchmark beta/alpha | `backend/app/api/analytics.py:1466-1478`, `backend/app/api/analytics.py:1491-1509` |
| Active-history factor OLS | `backend/app/services/analytics_engine.py:1098-1216` |
| Geometric monthly compounding | `backend/app/api/analytics.py:1511-1520` |
| Rolling average pairwise correlation and thresholds | `backend/app/services/correlation_service.py:17-67`, `backend/app/services/correlation_service.py:86-118` |
| Pairs alignment, Engle-Granger, OLS hedge ratio, spread z-score | `backend/app/services/cointegration_service.py:175-218` |
| OU speed/half-life | `backend/app/services/cointegration_service.py:75-131` |
| Johansen rank test | `backend/app/services/cointegration_service.py:134-150` |
| HHI, effective N, diversification, Gini | `backend/app/services/analytics_engine.py:205-250` |
| Weight trust boundaries and zero-state handling | `backend/app/models/schemas.py:11-35`, `backend/app/api/portfolio.py:87-100`, `backend/app/api/portfolio.py:220-225`, `backend/app/api/portfolio.py:412-427`, `backend/app/api/portfolio.py:882-897` |
| Single-holding optimizer allocation | `backend/app/api/analytics.py:1672-1695` |
| Inverse-volatility risk parity and target scaling | `backend/app/services/analytics_engine.py:593-656` |
| Moment/covariance annualization | `backend/app/services/optimization_service.py:39-43` |
| HRP | `backend/app/services/optimization_service.py:55-143` |
| Minimum variance | `backend/app/services/optimization_service.py:146-156` |
| Maximum Sharpe/tangency | `backend/app/services/optimization_service.py:159-176` |
| Minimum CVaR | `backend/app/services/optimization_service.py:179-194` |
| Black-Litterman | `backend/app/services/optimization_service.py:197-283` |
| Euler volatility and tail risk contribution | `backend/app/api/analytics.py:1591-1610` |
| Rolling realized volatility and EWMA service | `backend/app/services/volatility_service.py:26-110` |
| Volatility cone | `backend/app/services/volatility_service.py:187-323` |
| Analytics-engine EWMA recursion | `backend/app/services/analytics_engine.py:1062-1093` |
| Analytics-engine GARCH/EGARCH horizon VaR/CVaR | `backend/app/services/analytics_engine.py:978-1015`, `backend/app/services/analytics_engine.py:1020-1057` |
| Volatility-service GARCH | `backend/app/services/volatility_service.py:113-175` |
| EVT-POT VaR/ES | `backend/app/services/tail_risk_service.py:25-155` |
| Student-t lower-tail dependence | `backend/app/services/tail_risk_service.py:157-232` |
| Walk-forward backtest mechanics | `backend/app/services/backtest_service.py:18-195` |
| Monte Carlo GBM/Student-t/bootstrap | `backend/app/services/monte_carlo_service.py:43-137`, `backend/app/services/monte_carlo_service.py:163-230` |
| Performance history and benchmark rebasing | `backend/app/api/analytics.py:1182-1296` |
| Portfolio risk-score heuristic | `backend/app/services/analytics_engine.py:703-829` |
| Stress-test heuristic | `backend/app/services/analytics_engine.py:385-557` |
| Amihud and liquidation-days formulas | `backend/app/services/india_data_service.py:26-52`, `backend/app/services/india_data_service.py:249-334` |
| Conditional regime portfolio CAGR/volatility | `backend/app/utils/holdings.py:216-239` |

The standalone Gaussian HMM market-regime classifier at `backend/app/services/regime_service.py:105-296` is not a portfolio/correlation model and is not assigned a portfolio-model verdict. Its conditional **portfolio** CAGR/volatility summary is included above.

### 2.1 Evidence conventions

- The runner compares unrounded backend intermediates where available and uses response precision where the route is the only executable backend path.
- Absolute tolerance is driven by observed backend rounding: `5.1e-7` for six-decimal outputs and `5.1e-5` for four-decimal outputs.
- Numerical methods use solver tolerances around `1e-6` to `1e-12`.
- For each case, the output prints backend, reference, maximum absolute difference, maximum relative difference, `atol`, `rtol`, verdict, severity, and reference name (`quant/outputs/verify-portfolio-correlation.txt:106-198`).
- A `MATCHES` assertion fails the script if the values do not satisfy the stated tolerance. The final script completed with Ruff clean and all expected matches passing.

## 3. Evidence by model

### 3.1 Portfolio return construction and covariance annualization

**Formula.** Prices are sorted, non-finite values are removed, then `ffill().bfill()` is applied; percentage returns replace non-finite values with zero, and the first row is dropped (`backend/app/services/analytics_engine.py:57-62`). Portfolio return is `Σ_t w_t r_t` (`backend/app/services/analytics_engine.py:837-842`). The shared analytics builder repeats `ffill().bfill()` and `fillna(0.0)` (`backend/app/api/analytics.py:1329-1334`). Optimizer moments are `μ̂=252·mean(r)` and `Σ̂=252·cov(r)` (`backend/app/services/optimization_service.py:39-43`).

**Assumptions.** Aligned finite daily observations; sample covariance uses `ddof=1`; 252 trading days/year; weights are normalized where specified.

**Numeric evidence.**

- Identically aligned portfolio returns matched the direct dot product within `1e-14` (`quant/outputs/verify-portfolio-correlation.txt:107`).
- Annualized covariance matched `numpy.cov(ddof=1) × 252` exactly: absolute and relative differences `0` (`quant/outputs/verify-portfolio-correlation.txt:108`).
- With 120 pre-listing NaN rows for one asset, backend annual return was `-0.0836199642` versus active-history reference `-0.0718506354`: absolute `0.0117693288`, relative `16.3803%` (`quant/outputs/verify-portfolio-correlation.txt:109`).
- The same input produced backend volatility `0.0817826983` versus `0.0897741081`: absolute `0.0079914098`, relative `8.9017%` (`quant/outputs/verify-portfolio-correlation.txt:110`).

**Verdict:** `BUG (wrong math)`, **high severity**, for staggered listings/pre-listing NaNs. The active period should not be filled with a future first observed price followed by zero returns. This preprocessing feeds realized, tear-sheet, contribution, optimization, correlation, Monte Carlo, and vol-cone builders through `backend/app/api/analytics.py:1329-1335`.

**Clean control:** Fully synchronized finite input matches.

### 3.2 Annual return, volatility, Sharpe, Sortino, and hit ratio

**Formula.** For at least ten observations, annual return is `252·mean(r)`, volatility is `sqrt(252)·std(r,ddof=1)`, Sharpe is `(annual_return-rf)/annual_volatility`, and Sortino uses downside `min(0,r-rf_daily)` over the full sample (`backend/app/services/analytics_engine.py:852-872`). Hit ratio is the fraction of positive returns (`backend/app/services/analytics_engine.py:874-875`).

**Numeric evidence.** On a 300-observation first-loss case, annual return, volatility, Sharpe, Sortino, and hit ratio all had absolute and relative differences `0` against the transparent annualized/MAR formulas (`quant/outputs/verify-portfolio-correlation.txt:111-115`). Tolerances were `1e-12` absolute and `1e-12` relative.

**Assumptions/limitations.** Annual return is arithmetic, not CAGR; the tear-sheet CAGR is separately library-backed. The risk-free rate defaults to 2% (`backend/app/config.py:31-32`).

**Verdict:** `MATCHES`, **no severity**.

### 3.3 Historical VaR and CVaR

**Formula.** Historical VaR is the fifth return percentile; CVaR is the mean of observations at or below that percentile (`backend/app/services/analytics_engine.py:893-902`).

**Numeric evidence.** Backend VaR `0.0200` and CVaR `0.0196` exactly matched NumPy percentile and conditional empirical mean; both absolute/relative differences were `0` (`quant/outputs/verify-portfolio-correlation.txt:116-117`).

**Assumptions/limitations.** One-sided historical 95% loss threshold; quantile ties are all included in the tail.

**Verdict:** `MATCHES`, **no severity**.

### 3.4 Drawdown baseline

**Formula.** The engine computes `(1+r).cumprod()` and an expanding maximum without prepending initial wealth `1.0` (`backend/app/services/analytics_engine.py:912-916`). The backtest similarly starts cumulative wealth at `1+r[0]` (`backend/app/services/backtest_service.py:136-143`).

**Numeric evidence.**

- Analytics engine: first return `-10%`; backend max drawdown `0.0`, baseline-aware reference `-0.10`; absolute `0.10`, relative `100%` (`quant/outputs/verify-portfolio-correlation.txt:118`).
- Walk-forward backtest: backend `-0.0662`, independent baseline-aware replay `-0.0734319956`; absolute `0.0072319956`, relative `9.8486%` (`quant/outputs/verify-portfolio-correlation.txt:186`).

**Verdict:** `BUG (wrong math)`, **high severity**, in both paths. This is independent of the quantstats tear sheet, whose own drawdown path matched and handles the initial baseline (`quant/outputs/verify-portfolio-correlation.txt:127`).

### 3.5 quantstats-backed tear-sheet suite

**Formula.** The route delegates total return, CAGR, Sharpe, Sortino, Calmar, Omega, tail ratio, volatility, max drawdown, skew, and kurtosis to quantstats (`backend/app/api/analytics.py:1422-1434`). The installed package is `0.0.81` (`backend/uv.lock:3049-3051`).

**Numeric evidence.** All eleven metrics matched installed quantstats/transparent source formulas within six-decimal rounding. Largest absolute difference was Sortino `3.1241e-7`; largest relative difference was tail ratio `0.000436%` (`quant/outputs/verify-portfolio-correlation.txt:119-129`). Tolerance was `5.1e-7` absolute and `1e-10` relative.

Selected values: Sharpe backend/reference `-1.477255/-1.4772551182`; max drawdown `-0.150694/-0.1506942625`; Omega `0.819067/0.8190667906`.

**Assumptions/limitations.** Quantstats annualizes at 252 periods and de-annualizes the supplied 2% risk-free rate geometrically. The installed version is the definition under test, not an external universal standard.

**Verdict:** `MATCHES`, **no severity**.

### 3.6 Benchmark beta/alpha and factor OLS

**Formula.** Tear-sheet beta is `cov(p,b)/var(b)` and daily alpha is annualized by 252 (`backend/app/api/analytics.py:1471-1477`, `backend/app/api/analytics.py:1503-1508`). Factor exposure uses active non-NaN dates and statsmodels OLS with an intercept and HAC covariance (`backend/app/services/analytics_engine.py:1120-1145`, `backend/app/services/analytics_engine.py:1166-1192`).

**Numeric evidence.**

- Tear-sheet beta: `0.7378` vs `0.7378274307`; absolute `2.7431e-5`, relative `0.00372%` (`quant/outputs/verify-portfolio-correlation.txt:130`).
- Annualized alpha: `-0.0611` vs `-0.0610912710`; absolute `8.7290e-6`, relative `0.01429%` (`quant/outputs/verify-portfolio-correlation.txt:131`).
- Active position beta: `1.4325` vs statsmodels OLS `1.4324751073`; absolute `2.4893e-5` (`quant/outputs/verify-portfolio-correlation.txt:132`).
- Position alpha: `-0.000447` vs `-0.0004473110`; absolute `3.1101e-7` (`quant/outputs/verify-portfolio-correlation.txt:133`).
- Portfolio R²: `0.7189` vs `0.7189138973`; absolute `1.3897e-5` (`quant/outputs/verify-portfolio-correlation.txt:134`).

**Assumptions/limitations.** Arithmetic alpha annualization; HAC affects inference, not OLS point estimates.

**Verdict:** `MATCHES`, **no severity**.

### 3.7 Geometric monthly compounding

**Formula.** The implemented expression is exactly `(1 + port_ret).groupby([year, month]).prod() - 1` (`backend/app/api/analytics.py:1511-1520`).

**Numeric evidence.** Across 17 chronological months, the maximum absolute difference was `4.9792e-7`, below the `5.1e-7` six-decimal tolerance; the largest relative difference was `0.0436%` near a near-zero month (`quant/outputs/verify-portfolio-correlation.txt:135`).

**Verdict:** `MATCHES`, **no severity**. The mandatory geometric-compounding invariant passes.

### 3.8 Rolling pairwise correlation and regime thresholds

**Formula.** Every unique pair uses `Series.rolling(...).corr(other)`, then pairs are averaged with skip-NaN semantics (`backend/app/services/correlation_service.py:52-67`). Percentile thresholds and current-value comparisons are at `backend/app/services/correlation_service.py:92-100`.

**Numeric evidence.** A 150-row, three-asset frame with two missing values in one pair matched an independent NumPy pairwise Pearson loop within `1e-13`. P90 threshold was `0.262` vs `0.2619914329`: absolute `8.5671e-6`, relative `0.00327%` (`quant/outputs/verify-portfolio-correlation.txt:136-137`). Current correlation was `0.2937` after response rounding versus `0.2936833731` (`quant/outputs/verify-portfolio-correlation.txt:44-50`).

**Edge evidence.** One asset and an all-constant pair each raised `ValueError`, as required by `backend/app/services/correlation_service.py:41-47` and `backend/app/services/correlation_service.py:64-65` (`quant/outputs/verify-portfolio-correlation.txt:44-50`).

**Verdict:** `MATCHES`, **no severity**.

### 3.9 Cointegration, OLS hedge ratio, spread z-score, OU, and Johansen

**Formula.** Series are inner-aligned and `dropna()` before testing (`backend/app/services/cointegration_service.py:175-181`). Engle-Granger uses statsmodels `coint`; hedge ratio/intercept use `np.polyfit`; spread is `p_a-(alpha+beta·p_b)`; z-score is full-sample mean/std (`backend/app/services/cointegration_service.py:183-218`). OU regresses `Δz` on `z[t-1]`, with `θ=-ln(1+γ)` and half-life `ln(2)/θ` (`backend/app/services/cointegration_service.py:98-122`). Johansen compares rank-zero trace statistic to the 95% critical value (`backend/app/services/cointegration_service.py:134-147`).

**Numeric evidence.** After one explicit missing value and dropped dates, 404 aligned rows remained (`quant/outputs/verify-portfolio-correlation.txt:52-57`).

| Metric | Backend | Reference | Absolute difference | Verdict |
|---|---:|---:|---:|---|
| Engle-Granger t | `-10.7398` | `-10.7397715840` | `2.8416e-5` | `MATCHES` |
| Engle-Granger p | `0.0` | `3.5784e-18` | `3.5784e-18` | `MATCHES` |
| Hedge beta | `0.584544` | `0.5845438980` | `1.0201e-7` | `MATCHES` |
| Intercept | `-1.6624` | `-1.6624395086` | `3.9509e-5` | `MATCHES` |
| Current z-score | `-0.2376` | `-0.2375647849` | `3.5215e-5` | `MATCHES` |
| OU theta | `0.589982` | `0.5899824635` | `4.6345e-7` | `MATCHES` |
| OU half-life | `1.17` | `1.1748606501` | `0.00486065` | `MATCHES` |
| Johansen boolean | `1` | `1` | `0` | `MATCHES` |

Source: `quant/outputs/verify-portfolio-correlation.txt:138-145`. Tols followed output precision; half-life tolerance was `0.0051`.

**Edge evidence.** An independent random walk produced p-value `0.447136`; a constant spread returned `theta=None` (`quant/outputs/verify-portfolio-correlation.txt:52-57`).

**Assumptions/limitations.** Price levels are tested directly; p-value uses 0.05; OU `dt=1`; global z-score includes the full aligned sample.

**Verdict:** `MATCHES`, **no severity**.

### 3.10 HHI, effective N, diversification, and Gini

**Formula.** HHI is `sum(w²)`; effective N is `1/HHI`; normalized diversification is `(1-HHI)/(1-1/N)·100`, with zero for `N<=1`; Gini is the sorted-weight finite-sum formula (`backend/app/services/analytics_engine.py:216-237`).

**Numeric evidence for `[0.6,0.3,0.1]`:**

- HHI backend/reference `0.46/0.46`; absolute `5.55e-17` (`quant/outputs/verify-portfolio-correlation.txt:146`).
- Effective N `2.17/2.1739130435`; absolute `0.0039130` due two-decimal output (`quant/outputs/verify-portfolio-correlation.txt:147`).
- Diversification `81.0/81.0`; absolute `0` (`quant/outputs/verify-portfolio-correlation.txt:148`).
- Gini `0.333/0.3333333333`; absolute `0.0003333` due three-decimal output (`quant/outputs/verify-portfolio-correlation.txt:149`).
- One holding returned exactly `0.0` diversification, absolute/relative difference `0` (`quant/outputs/verify-portfolio-correlation.txt:150`).

**Zero-weight edge.** Four equal active weights plus one accepted zero-weight row rendered `93.8%` instead of the active-holdings reference `100%`; absolute `6.2` percentage points, relative `6.2%` (`quant/outputs/verify-portfolio-correlation.txt:151`). The code includes the zero row in `N` through `len(weights)` at `backend/app/services/analytics_engine.py:231-233`.

**Verdict:** `MATCHES` for positive normalized weights and the mandatory single-holding invariant; `DIVERGES (magnitude)`, **no severity**, for an accepted zero-weight row under the active-holdings reference.

### 3.11 Weight trust boundaries and zero-state portfolio weight

**Formula/validation.** Create/update weights require `0 < w <= 1` (`backend/app/models/schemas.py:13-15`, `backend/app/models/schemas.py:61-64`). Rebalance rejects only `v < 0`, so zero targets are accepted (`backend/app/api/portfolio.py:882-897`). Single-position add stores the submitted weight directly (`backend/app/api/portfolio.py:220-225`). Portfolio summary falls back to the stored weight when total market value is zero (`backend/app/api/portfolio.py:92-100`). The API optimizer special-cases one holding to 100% (`backend/app/api/analytics.py:1672-1695`).

**Numeric evidence.**

- Negative create weight was rejected (`1/1`, difference `0`) (`quant/outputs/verify-portfolio-correlation.txt:152`).
- Zero rebalance target was accepted (`1/1`, difference `0`) (`quant/outputs/verify-portfolio-correlation.txt:153`).
- Empty-book initial add with client weight `0.20` returned `0.20`; mandatory reference `1.0`; absolute and relative `0.80/80%` (`quant/outputs/verify-portfolio-correlation.txt:154`).
- One persisted position with total value zero also returned `0.20`; reference `1.0`; absolute/relative `0.80/80%` (`quant/outputs/verify-portfolio-correlation.txt:155`).
- Supported one-asset minimum-variance path returned weight `1.0` exactly (`quant/outputs/verify-portfolio-correlation.txt:156`).

**Verdict:** `BUG (wrong math)`, **high severity**, for both zero-state entry paths. Negative trust-boundary handling and the one-asset optimizer control `MATCHES`.

### 3.12 Inverse-volatility risk parity and target-volatility scaling

**Formula.** After modeled annual volatilities are clamped to `[0.05,1.20]`, weights use `1/max(v,1e-4)` and normalize; target scaling multiplies all weights by `target/σ_p`, with the unlevered remainder assigned to cash (`backend/app/services/analytics_engine.py:593-656`). Portfolio covariance is rebuilt as `D R D` (`backend/app/services/analytics_engine.py:618-630`, `backend/app/services/analytics_engine.py:646-652`).

**Numeric evidence for positive volatilities.**

- Normalized inverse-vol weights: `[0.2639445984,0.3959568223,0.3400985793]` vs `[0.2639443156,0.3959571242,0.3400985602]`; maximum absolute `3.0190e-7`, relative `0.000107%` (`quant/outputs/verify-portfolio-correlation.txt:157`).
- Achieved target volatility: `0.10/0.10`, difference `0` (`quant/outputs/verify-portfolio-correlation.txt:158`).
- Current portfolio volatility: `0.10112307203405946/0.10112307203405944`; absolute `1.39e-17` (`quant/outputs/verify-portfolio-correlation.txt:159`).

**Zero-volatility edge.** A truly constant-price asset was assigned backend normalized weight `0.68554`; the transparent `ε=1e-12` inverse-vol reference was `0.9999999999908`; absolute `0.31446` (`quant/outputs/verify-portfolio-correlation.txt:160`). The 5% floor at `backend/app/services/analytics_engine.py:614` regularizes zero volatility away from literal `1/σ`.

**Verdict:** `MATCHES` for strictly positive sigma; `DIVERGES (magnitude)`, **no severity**, at the documented zero-volatility regularization edge. The implementation is inverse-volatility, not full Euler ERC, as its own methodology states at `backend/app/services/analytics_engine.py:678-684`.

### 3.13 HRP

**Formula.** Pearson correlation is converted to `sqrt((1-r)/2)`, clustered by single linkage, recursively bisected, and cluster variance uses inverse-variance weights; sibling allocation is inverse to cluster variance (`backend/app/services/optimization_service.py:55-85`, `backend/app/services/optimization_service.py:107-143`).

**Numeric evidence.** Backend and canonical independent HRP/SciPy weights were `[0.5355949260,0.1931308830,0.2712741909]`; absolute/relative difference `0` (`quant/outputs/verify-portfolio-correlation.txt:161`).

**Assumptions/limitations.** Zero covariance variances are replaced by the mean valid variance (`backend/app/services/optimization_service.py:110-116`).

**Verdict:** `MATCHES`, **no severity**.

### 3.14 Minimum variance

**Formula.** Long-only, fully invested CVXPY quadratic program minimizing `w'Σw` (`backend/app/services/optimization_service.py:146-156`).

**Numeric evidence.** Backend `[0.0703927515,0.3940780474,0.5355292010]` vs independent SciPy SLSQP `[0.0703926608,0.3940781008,0.5355292384]`; maximum absolute `9.0712e-8`, relative `0.000129%` (`quant/outputs/verify-portfolio-correlation.txt:162`). A zero-variance one-asset program remained feasible and summed to `1.0` (`quant/outputs/verify-portfolio-correlation.txt:67-69`).

**Verdict:** `MATCHES`, **no severity**.

### 3.15 Maximum Sharpe

**Formula.** Minimize `y'Σy` subject to `(μ-rf)'y=1`, `y>=0`, then normalize (`backend/app/services/optimization_service.py:159-176`). It explicitly rejects all non-positive expected excess returns (`backend/app/services/optimization_service.py:163-165`).

**Numeric evidence.** Backend `[0.3348127970,6.06e-9,0.6651871969]` vs normalized SciPy tangency `[0.3348127871,~0,0.6651872129]`; maximum absolute `1.5957e-8` (`quant/outputs/verify-portfolio-correlation.txt:163`). The all-negative-excess guard fired (`quant/outputs/verify-portfolio-correlation.txt:67-69`).

**Verdict:** `MATCHES`, **no severity**.

### 3.16 Minimum CVaR

**Formula.** Rockafellar–Uryasev scenario LP minimizes `alpha + 1/((1-beta)T)·sum(z)` subject to `z >= loss-alpha`, `z>=0`, `sum(w)=1`, `w>=0`; alpha is free (`backend/app/services/optimization_service.py:179-194`).

**Numeric evidence.** Backend `[0.0975707143,0.2834940037,0.6189352820]` vs independent SciPy HiGHS `[0.0975707148,0.2834940043,0.6189352809]`; maximum absolute `1.0847e-9` (`quant/outputs/verify-portfolio-correlation.txt:164`). Optimized CVaR was `0.0100288398070` vs `0.0100288398062`; absolute `8.3275e-13` (`quant/outputs/verify-portfolio-correlation.txt:165`).

**Verdict:** `MATCHES`, **no severity**.

### 3.17 Black-Litterman

**Formula.** Equal-weight market prior; `Pi=delta·Σw_mkt`; He-Litterman diagonal `Omega=diag(P·tauΣ·P')`; posterior mean and predictive covariance are at `backend/app/services/optimization_service.py:217-263`; long-only tangency is solved at `backend/app/services/optimization_service.py:265-283`.

**Numeric evidence.** Backend `[0.791037,0.208963,0.0]` vs independent posterior/tangency `[0.7910369639,0.2089630361,~0]`; maximum absolute `3.6053e-8`, relative `0.02417%` (`quant/outputs/verify-portfolio-correlation.txt:166`).

**Assumptions/limitations.** Equal-weight market portfolio, `delta=2.5`, `tau=0.05`, views interpreted as excess returns, and He-Litterman diagonal uncertainty (`backend/app/services/optimization_service.py:197-215`).

**Verdict:** `MATCHES`, **no severity**.

### 3.18 Volatility and CVaR risk contribution

**Formula.** Daily covariance is annualized by 252; volatility contribution is `w_i(Σw)_i/σ_p`, normalized; tail contribution is weighted conditional asset return over the portfolio's worst-5% dates, normalized to positive loss shares (`backend/app/api/analytics.py:1591-1610`).

**Numeric evidence.**

- Volatility shares: backend `[0.509276,0.348836,0.141887]` vs Euler reference `[0.5092762121,0.3488364987,0.1418872892]`; maximum absolute `4.9874e-7` (`quant/outputs/verify-portfolio-correlation.txt:167`).
- CVaR shares: backend `[0.540359,0.425050,0.034591]` vs reference `[0.5403589690,0.4250502549,0.0345907761]`; maximum absolute `2.5488e-7` (`quant/outputs/verify-portfolio-correlation.txt:168`).
- Annualized portfolio volatility: `0.0881/0.0880802220`; absolute `1.9778e-5` (`quant/outputs/verify-portfolio-correlation.txt:169`).

**Verdict:** `MATCHES`, **no severity**.

### 3.19 Rolling realized volatility, EWMA variants, and volatility cone

**Formula.** Rolling realized volatility uses sample rolling `std(ddof=1) × sqrt(252)` (`backend/app/services/volatility_service.py:54-63`). Volatility-service EWMA uses normalized exponential weights over all observations (`backend/app/services/volatility_service.py:88-110`). Analytics-engine EWMA instead seeds with full-sample population variance and performs 60 recursions with lambda `0.94` (`backend/app/services/analytics_engine.py:1062-1076`). Cone bands are quantiles of the rolling volatility series (`backend/app/services/volatility_service.py:240-281`).

**Numeric evidence.**

- Rolling series matched the sample rolling reference within `1e-14` (`quant/outputs/verify-portfolio-correlation.txt:170`).
- Volatility-service EWMA: `0.08708822262098562/0.08708822262098562`, difference `0` (`quant/outputs/verify-portfolio-correlation.txt:171`).
- Analytics-engine EWMA: `0.08688173673085094/0.08688173673085090`, absolute `4.16e-17` (`quant/outputs/verify-portfolio-correlation.txt:172`).
- 21-day cone median: `0.087/0.0869504779`, absolute `4.9522e-5`, relative `0.05695%` under four-decimal output tolerance (`quant/outputs/verify-portfolio-correlation.txt:173`).

**Edge evidence.** Empty EWMA input raises; a single return is handled; a window beyond available history returns null median (`quant/outputs/verify-portfolio-correlation.txt:73-77`).

**Verdict:** `MATCHES`, **no severity**. The two EWMA implementations intentionally define different estimators.

### 3.20 Analytics-engine GARCH horizon VaR/CVaR

**Formula.** `arch.forecast` supplies cumulative h-step variance. The backend computes `vol_final=sqrt(variance_h·252)/100`, then computes VaR/CVaR as `-vol_final·z·sqrt(h/252)` (`backend/app/services/analytics_engine.py:994-1008`, `backend/app/services/analytics_engine.py:1037-1051`). The variance already accumulates h daily steps.

**Numeric evidence.**

- Five-day GARCH VaR: backend `-0.0203115855`, installed-arch reference `-0.0090836172`; absolute `0.0112279683`, relative magnitude `123.6068%` (`quant/outputs/verify-portfolio-correlation.txt:174`).
- Five-day CVaR: backend `-0.0254357849`, reference `-0.0113752288`; absolute `0.0140605561`, relative `123.6068%` (`quant/outputs/verify-portfolio-correlation.txt:175`).
- One-day VaR control: backend/reference `-0.0090836172`; absolute and relative difference `0`; **MATCHES** (`quant/outputs/verify-portfolio-correlation.txt:176`).

**Verdict:** `BUG (wrong math)`, **high severity**. The cumulative horizon variance is annualized and then horizon-scaled a second time.

### 3.21 Analytics-engine EGARCH multi-day availability

**Formula/behavior.** The route calls `arch_model(...).forecast(horizon=h)` without a supported simulation method (`backend/app/services/analytics_engine.py:1031-1037`) and returns the empty/error payload on exception (`backend/app/services/analytics_engine.py:1058-1060`).

**Numeric evidence.** Installed arch 8.0 supports a five-day EGARCH simulation, while backend availability was `0` and reference availability `1`; absolute/relative difference `1/100%` (`quant/outputs/verify-portfolio-correlation.txt:177`).

**Verdict:** `BUG (wrong math)`, **medium severity**, for the public multi-day EGARCH path.

### 3.22 Volatility-service GARCH average-horizon volatility

**Formula.** This separate service fits zero-mean GARCH and averages the cumulative forecast variances before annualizing (`backend/app/services/volatility_service.py:150-162`).

**Numeric evidence.** Backend/reference `0.08790633743237197/0.08790633743237197`, absolute and relative differences `0` (`quant/outputs/verify-portfolio-correlation.txt:178`).

**Verdict:** `MATCHES`, **no severity**. This path is distinct from the analytics-engine h-day VaR scaling bug.

### 3.23 EVT-POT VaR/ES

**Formula.** Losses are `-r`; empirical VaR/ES use the 99th loss percentile and upper tail; exceedances above the 95th threshold fit a zero-location GPD; `ratio=(n/n_u)·alpha`; analytic POT VaR/ES are at `backend/app/services/tail_risk_service.py:70-120`.

**Numeric evidence.**

- POT VaR99: `-0.072684/-0.0726835975`; absolute `4.0254e-7`, relative `0.000554%` (`quant/outputs/verify-portfolio-correlation.txt:179`).
- ES99: `-0.101415/-0.1014145407`; absolute `4.5929e-7`, relative `0.000453%` (`quant/outputs/verify-portfolio-correlation.txt:180`).
- 1,200 observations yielded 60 exceedances and a successful GPD fit (`quant/outputs/verify-portfolio-correlation.txt:81-86`).

**Assumptions/limitations.** Shape is clipped to `[-0.5,0.95]`; at least five exceedances are required; empirical exceedance fraction normalizes the tail probability.

**Verdict:** `MATCHES`, **no severity**.

### 3.24 Student-t lower-tail dependence

**Formula.** `lambda_L=2·T_{nu+1}(-sqrt((nu+1)(1-rho)/(1+rho)))` with clipped rho and averaged marginal t degrees of freedom (`backend/app/services/tail_risk_service.py:194-232`).

**Numeric evidence.** Backend/reference `0.045445682726367065/0.045445682726367065`, absolute/relative difference `0`; pair overlap was 360 rows and single-asset matrix was `[[1.0]]` (`quant/outputs/verify-portfolio-correlation.txt:181`, `quant/outputs/verify-portfolio-correlation.txt:81-86`).

**Assumptions/limitations.** The code explicitly describes marginal-df averaging and raw Pearson rho as an approximation, not a joint copula fit (`backend/app/services/tail_risk_service.py:186-192`).

**Verdict:** `MATCHES`, **no severity**.

### 3.25 Walk-forward backtest mechanics

**Formula.** Train windows are prior to each rebalance; one-way turnover is `0.5·Σ|Δw|`; day-zero friction is `(1-c)(1+r)-1`; daily weights are fixed until rebalance (`backend/app/services/backtest_service.py:70-127`). Equity, CAGR, drawdown, mean-based Sharpe, and Calmar are at `backend/app/services/backtest_service.py:132-167`.

**Numeric evidence.**

- 120 OOS days and two rebalances were produced (`quant/outputs/verify-portfolio-correlation.txt:88-93`).
- CAGR: `2.1793/2.1793354450`; absolute `3.5445e-5` (`quant/outputs/verify-portfolio-correlation.txt:182`).
- Annualized volatility: `0.0876/0.0876477583`; absolute `4.7758e-5` (`quant/outputs/verify-portfolio-correlation.txt:183`).
- Sharpe: `13.0422/13.0422387460`; absolute `3.8746e-5` (`quant/outputs/verify-portfolio-correlation.txt:184`).
- First turnover: `0.3/0.3`; absolute `5.55e-17` (`quant/outputs/verify-portfolio-correlation.txt:185`).
- Max drawdown: backend `-0.0662`, baseline reference `-0.0734319956`; absolute `0.0072320`, relative `9.8486%` (`quant/outputs/verify-portfolio-correlation.txt:186`).

**Assumptions/limitations.** The “benchmark” is a fixed equal-weight basket because the service receives only asset returns (`backend/app/services/backtest_service.py:66-68`, `backend/app/services/backtest_service.py:113-114`).

**Verdict:** `BUG (wrong math)`, **high severity**, for drawdown only; all other tested mechanics `MATCH`.

### 3.26 Monte Carlo

**Formula.** Calibration uses `252·mean` and `sqrt(252)·std(ddof=1)` (`backend/app/services/monte_carlo_service.py:48-57`). GBM uses log drift `mu-0.5sigma²` (`backend/app/services/monte_carlo_service.py:60-77`); Student-t is winsorized and moment-matched (`backend/app/services/monte_carlo_service.py:80-107`); bootstrap uses arch stationary blocks (`backend/app/services/monte_carlo_service.py:110-137`).

**Numeric evidence.**

- GBM terminal median: `89992.84/89992.8426328`; absolute `0.0026328`, relative `2.93e-8%` (`quant/outputs/verify-portfolio-correlation.txt:187`).
- Student-t terminal median: `89095.74/89095.74`, difference `0` (`quant/outputs/verify-portfolio-correlation.txt:189`).
- Stationary-bootstrap terminal median: `88994.76/88994.76`, difference `0`; same-seed backend control also passed (`quant/outputs/verify-portfolio-correlation.txt:190`).

**Assumptions/limitations.** Historical i.i.d. GBM; Student-t innovations are clipped at 8z and simple returns at -95%; stationary bootstrap preserves block dependence. No risk-free cash return is modeled.

**Verdict:** `MATCHES`, **no severity**.

### 3.27 Performance history and benchmark rebasing

**Formula.** Portfolio value is `Σ price·quantity`, return is value `pct_change`, and benchmark cumulative return is normalized to the first common portfolio value (`backend/app/api/analytics.py:1257-1278`, `backend/app/api/analytics.py:1282-1294`).

**Numeric evidence.**

- Last portfolio value: `489.71/489.7058441`; absolute `0.0041559` under two-decimal tolerance (`quant/outputs/verify-portfolio-correlation.txt:191`).
- Last return: `0.005102/0.0051024731`; absolute `4.7312e-7` (`quant/outputs/verify-portfolio-correlation.txt:192`).
- Rebased benchmark: `438.75/438.7545095`; absolute `0.0045095` (`quant/outputs/verify-portfolio-correlation.txt:193`).

**Assumptions/limitations.** Current quantities are backcast after holding-window masking (`backend/app/api/analytics.py:1234-1253`); no transaction history is reconstructed.

**Verdict:** `MATCHES`, **no severity**.

### 3.28 Risk-score heuristic

**Formula.** Concentration, annual volatility, upper-triangular average correlation, factor `1-R²`, and 60-day volatility are clipped to 0–30; omitted factor risk is dropped and remaining weights renormalized (`backend/app/services/analytics_engine.py:737-795`).

**Numeric evidence.** Backend `12.2` vs independent declared-rule replay `12.20390346`; absolute `0.0039035`, relative `0.03199%` under one-decimal output tolerance (`quant/outputs/verify-portfolio-correlation.txt:194`). Without a benchmark, `factor_risk` was excluded (`quant/outputs/verify-portfolio-correlation.txt:99-104`).

**Assumptions/limitations.** This verifies implementation of the declared scoring heuristic; it is not evidence of empirical calibration.

**Verdict:** `MATCHES`, **no severity**.

### 3.29 Stress-test heuristic

**Formula.** Custom shock is parsed; each position impact is shock × sector multiplier × bounded volatility adjustment, then weighted and clipped (`backend/app/services/analytics_engine.py:491-545`).

**Numeric evidence.** For custom `-10%`, backend/reference impact was `-0.085/-0.085`, absolute/relative difference `0` (`quant/outputs/verify-portfolio-correlation.txt:195`).

**Assumptions/limitations.** Scenario and sector tables are hand-specified, and volatility is clipped to `[0.85,1.25]`; this is a rule replay, not a calibrated stress model.

**Verdict:** `MATCHES`, **no severity**.

### 3.30 Amihud illiquidity and liquidation days

**Formula.** Amihud is the positive-rupee-volume mean of `|r|/rupee_volume·10^6`; days-to-liquidate is `position_value/(participation·ADV)` (`backend/app/services/india_data_service.py:26-52`).

**Numeric evidence.**

- Amihud: `0.0007083333333333334/0.0007083333333333334`, difference `0`; the zero-volume observation was excluded (`quant/outputs/verify-portfolio-correlation.txt:196`, `quant/outputs/verify-portfolio-correlation.txt:99-104`).
- Ten-percent ADV liquidation: `5.0/5.0` days, difference `0` (`quant/outputs/verify-portfolio-correlation.txt:197`).

**Verdict:** `MATCHES`, **no severity**.

### 3.31 Conditional regime portfolio summary

**Formula.** Total return is `prod(1+r)-1`; annualized volatility is `std·sqrt(252)`; annualized return is `prod(1+r)^(252/n)-1` only at/above 30 days (`backend/app/utils/holdings.py:223-239`).

**Numeric evidence.** Backend/reference CAGR `8.6603/8.6603200514`; absolute `2.0051e-5`, relative `0.000232%` (`quant/outputs/verify-portfolio-correlation.txt:198`).

**Verdict:** `MATCHES`, **no severity**.

### 3.32 Tracking error and information ratio

No implementation was found. The executed tear-sheet function contains zero occurrences of `tracking_error` and zero of `information_ratio`; the script records both counts as `0` (`quant/outputs/verify-portfolio-correlation.txt:39-42`). The implemented relative block contains beta, alpha, overlap, and benchmark return/volatility/drawdown/Sharpe fields only (`backend/app/api/analytics.py:1474-1508`).

**Verdict:** Not present; no model verdict or recommendation is assigned.

## 4. Mandatory AGENTS.md invariant checks

| Mandatory invariant | Exact backend code | Numeric evidence | Verdict |
|---|---|---|---|
| True HHI `sum(w²)` | `backend/app/services/analytics_engine.py:224-225` | `[0.6,0.3,0.1]`: `0.46/0.46`, abs `5.55e-17` (`outputs:146`) | `MATCHES` |
| `N_eff=1/HHI` | `backend/app/services/analytics_engine.py:227-228` | `2.17/2.1739130435`, abs `0.0039130` after two-decimal response (`outputs:147`) | `MATCHES` |
| One holding diversification exactly 0% | `backend/app/services/analytics_engine.py:230-233` | `0.0/0.0`, abs/rel `0` (`outputs:150`) | `MATCHES` |
| Inverse-vol `w_i ∝ 1/σ_i` | `backend/app/services/analytics_engine.py:634-640` | Positive sigma max abs `3.019e-7`; zero sigma `0.68554/0.9999999999908` (`outputs:157,160`) | `MATCHES` positive; `DIVERGES (magnitude)` zero-vol edge |
| Geometric monthly compounding | `backend/app/api/analytics.py:1511-1520` | 17 months max abs `4.9792e-7` (`outputs:135`) | `MATCHES` |
| Empty/zero-value initial portfolio weight 100% | `backend/app/api/portfolio.py:92-100`, `backend/app/api/portfolio.py:220-225` | `0.20/1.0` on both add and zero-total-value paths (`outputs:154-155`) | `BUG (wrong math)`, high |
| Single-holding optimizer weight 100% | `backend/app/api/analytics.py:1672-1695` | `1.0/1.0`, abs/rel `0` (`outputs:156`) | `MATCHES` |

### 4.1 Required edge cases

| Edge | Backend behavior/evidence | Verdict |
|---|---|---|
| Negative weights | Create/update schemas reject `w<=0`; rebalance rejects `v<0` (`backend/app/models/schemas.py:13-15`, `backend/app/api/portfolio.py:882-888`) | `MATCHES` trust boundary |
| Zero weights | Rebalance accepts zero (`backend/app/api/portfolio.py:883-897`); concentration with a zero row is 93.8% vs active-N 100% | `DIVERGES (magnitude)` |
| One asset | Correlation service rejects `<2` assets (`backend/app/services/correlation_service.py:41-42`); supported one-asset min-vol weight is 1.0 | `MATCHES` |
| Zero volatility | 5% floor changes literal inverse-vol allocation (`backend/app/services/analytics_engine.py:614`) | `DIVERGES (magnitude)`, no severity |
| Missing/NaN prices | 120-row staggered listing changes annual return 16.38% and volatility 8.90% | `BUG`, high |
| Misaligned dates | Pairs inner-aligned 404 rows and matched all tested stats; rolling correlation skipped two missing pair observations | `MATCHES` |
| First negative return | Analytics drawdown omitted 100% initial loss; backtest understated by 9.85% | `BUG`, high |
| Non-cointegrated pair | Independent random walk p=`0.447136`; constant spread OU theta=`None` | `MATCHES` expected guards |
| Empty volatility input | Volatility-service EWMA raises rather than fabricating (`backend/app/services/volatility_service.py:93-99`) | `MATCHES` |

## 5. Model → verdict → reference → magnitude summary

| Model | Verdict | Reference | Maximum material magnitude |
|---|---|---|---|
| Aligned portfolio returns/covariance | `MATCHES` | NumPy dot/cov | `0` for covariance |
| Staggered/pre-listing return construction | `BUG (wrong math)` | Active common start | 16.38% annual-return error |
| Annual metrics, VaR/CVaR | `MATCHES` | Transparent formulas | `0` |
| Analytics drawdown | `BUG (wrong math)` | Initial wealth `1` | 100% first-loss omission |
| quantstats suite | `MATCHES` | quantstats 0.0.81 | max abs `3.124e-7` |
| Beta/alpha/factor OLS | `MATCHES` | statsmodels OLS | max abs `2.743e-5` |
| Monthly compounding | `MATCHES` | groupby geometric product | max abs `4.979e-7` |
| Rolling correlation | `MATCHES` | Independent NumPy Pearson loop | max abs `<1e-13`; P90 abs `8.567e-6` |
| Pairs statistics/OU/Johansen | `MATCHES` | statsmodels 0.15.0 | max abs `0.004861` days after output rounding |
| HHI/N_eff/Gini/single holding | `MATCHES` | Concentration identities | max abs `0.003913` due output rounding |
| Concentration with zero row | `DIVERGES (magnitude)` | Active holdings N | 6.2 percentage points |
| Negative/zero validation | `MATCHES` | Trust-boundary rules | `0` |
| Zero-state first position | `BUG (wrong math)` | Mandatory 100% invariant | 80 percentage points |
| Positive inverse-vol risk parity | `MATCHES` | `1/σ` weights | max abs `3.019e-7` |
| Zero-volatility inverse-vol edge | `DIVERGES (magnitude)` | Literal `1/σ`, ε=`1e-12` | 31.446 percentage points |
| HRP | `MATCHES` | Canonical SciPy HRP | `0` |
| Minimum variance | `MATCHES` | SciPy SLSQP | max abs `9.071e-8` |
| Maximum Sharpe | `MATCHES` | SciPy tangency | max abs `1.596e-8` |
| Minimum CVaR | `MATCHES` | SciPy HiGHS RU LP | max abs `1.085e-9`; objective `8.328e-13` |
| Black-Litterman | `MATCHES` | Independent posterior/tangency | max abs `3.605e-8` |
| Volatility/CVaR risk contribution | `MATCHES` | Euler/conditional-tail formulas | max abs `4.987e-7` |
| Rolling vol/EWMA/cone | `MATCHES` | pandas/independent recursion | max abs `4.952e-5` at 4dp output |
| Analytics GARCH horizon risk | `BUG (wrong math)` | arch cumulative variance | 123.61% relative error at five days; one-day control matches |
| Analytics EGARCH h>1 | `BUG (wrong math)` | arch simulation availability | 100% unavailable |
| Volatility-service GARCH average | `MATCHES` | arch zero-mean GARCH | `0` |
| EVT-POT VaR/ES | `MATCHES` | SciPy GPD | max abs `4.593e-7` |
| Student-t tail dependence | `MATCHES` | t-copula formula | `0` |
| Backtest return/turnover mechanics | `MATCHES` | Daily replay | max abs `4.776e-5` at 4dp output |
| Backtest drawdown | `BUG (wrong math)` | Baseline-aware replay | 9.85% relative |
| Monte Carlo GBM/t/bootstrap | `MATCHES` | Independent seeded replays | median max abs `0.00264` unrounded; rounded t/bootstrap `0` |
| Performance history/rebasing | `MATCHES` | Value/return replay | max abs `0.00451` at 2dp output |
| Risk score/stress heuristics | `MATCHES` | Independent rule replay | max abs `0.00391` at 1dp output |
| Amihud/liquidation days | `MATCHES` | Transparent formulas | `0` |
| Regime portfolio summary | `MATCHES` | Geometric CAGR | max abs `2.005e-5` |

**Case verdict count:** `MATCHES=81`, `DIVERGES (magnitude)=2`, `BUG (wrong math)=9` (`quant/outputs/verify-portfolio-correlation.txt:200-204`).

## 6. Clean areas, limitations, reproduction, and artifacts

### 6.1 Clean areas

- Aligned returns and sample covariance annualization match exactly.
- Basic annual risk metrics, empirical VaR/CVaR, quantstats suite, beta/alpha, OLS factor estimates, and geometric monthly compounding match.
- Rolling correlation handles pairwise missing data and thresholds correctly for the tested frame.
- Engle-Granger/Johansen/OLS/OU/z-score calculations match statsmodels and independent formulas.
- HHI, effective N, Gini, and mandatory single-holding diversification match for positive normalized weights.
- Positive-volatility inverse-vol parity, target scaling, and modeled covariance match.
- HRP, minimum variance, maximum Sharpe, minimum CVaR, and Black-Litterman match independent references.
- Euler volatility and empirical tail contributions match.
- EVT-POT and Student-t tail-dependence formulas match.
- Backtest schedule, turnover, cost application, CAGR, volatility, and Sharpe match; only drawdown is wrong.
- Seeded Monte Carlo and performance-history mechanics match.

### 6.2 Material limitations exposed

- Full-history and builder paths use backfill for staggered listings, which changes moments and correlations (`backend/app/services/analytics_engine.py:57-59`, `backend/app/api/analytics.py:1329-1330`).
- Risk-parity zero volatility is regularized by a 5% floor, so it is not literal inverse volatility (`backend/app/services/analytics_engine.py:614`).
- The Student-t tail-dependence model is an explicit marginal-fit approximation, not a joint copula fit (`backend/app/services/tail_risk_service.py:186-192`).
- The backtest “benchmark” is equal weight, not an external equity benchmark (`backend/app/services/backtest_service.py:66-68`).
- Risk-score and stress outputs match their declared heuristic rules but are not externally calibrated models.

### 6.3 Top three findings

1. **GARCH horizon VaR/CVaR is materially under-scaled at multi-day horizons:** 123.61% relative magnitude error at five days because cumulative h-day variance is annualized and horizon-scaled again; the one-day control matches (`quant/outputs/verify-portfolio-correlation.txt:174-176`).
2. **Pre-listing backfill changes portfolio moments:** 16.38% annual-return and 8.90% volatility differences from an active-history reference on the same prices (`quant/outputs/verify-portfolio-correlation.txt:109-110`).
3. **Drawdown omits the initial loss:** analytics drawdown misses the full first 10% loss, and backtest drawdown understates by 9.85% (`quant/outputs/verify-portfolio-correlation.txt:118,186`).

The zero-state portfolio-weight invariant is an additional high-severity finding: both first-position paths return `20%` where the mandatory invariant is `100%` (`quant/outputs/verify-portfolio-correlation.txt:154-155`).

### 6.4 Reproduction commands

From `C:\es\coding\finengine\backend`:

```powershell
uv run --no-sync python "..\.scratch\backend-deep-audit\quant\evidence\verify-portfolio-correlation.py"
uv run --no-sync ruff check --no-cache "..\.scratch\backend-deep-audit\quant\evidence\verify-portfolio-correlation.py"
```

Expected runner summary:

```text
cases=92
verdicts={"BUG (wrong math)": 10, "DIVERGES (magnitude)": 2, "MATCHES": 80}
```

### 6.5 Artifact links

- [Report](verify-portfolio-correlation.md)
- [Deterministic evidence script](evidence/verify-portfolio-correlation.py)
- [Generated numeric evidence](outputs/verify-portfolio-correlation.txt)
