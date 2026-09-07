# FinEngine Backend — Published-Library Fix Map
**Date:** 2026-09-03 | **Mode:** read-only research, no source files changed
**Companion:** `.scratch/backend-audit-2026/BACKEND_REVIEW.md` (P0/P1/P2 + Sprint plan)
**Method:** 4 parallel researchers, each verified PyPI name + version + license + maintenance via PyPI JSON / GitHub / Context7 / websearch on 2026-09-03. Re-pin at install time (`pip index versions <pkg>`).

> Rule used throughout: **no library fixes bad data boundaries.** Active-history filter, inner-join alignment, no zero-fill, 252-day annualization docs, weight renorm after rounding, winsorization, and honest 404/503 envelopes stay custom regardless of library.

---

## 0. Executive answer — adopt / keep / reject

**Minimal high-value install (if you install anything):**
`skfolio==1.0.3` (or `riskfolio-lib==7.3.0`) + `tenacity` + `aiolimiter` + `cachetools` + `async-lru` + `pandera` + `structlog` + `slowapi` + `joserfc` + `tiktoken` + `yahooquery` (complement) + `ta` (only if stockstats gaps proven) + `ruptures` (regime complement) + `pyextremes==2.5.0` (threshold diagnostics only). Promote `httpx==0.28.x` dev→main.

**Keep & use more (already in `backend/pyproject.toml`):** `scipy 1.18.1`, `scikit-learn>=1.7.2` (LedoitWolf), `cvxpy 1.9.2 + clarabel 0.11.1`, `arch 8.0.0`, `statsmodels 0.15.0`, `quantstats 0.0.81`, `stockstats>=0.6.8`, `SQLAlchemy 2.0.52 + alembic 1.19.1 + aiosqlite`, `httpx`, `aiohttp` (consolidate new code on httpx).

**Explicitly reject:** `cvxportfolio 1.5.1` (GPLv3), `backtesting.py 0.6.6` (AGPL-3.0), `vectorbt 1.1.0` (Apache-2.0 + Commons Clause — commercial block), `copulas 0.14.1` (BUSL-1.1 + wrong problem), `finta 1.3` (archived + LGPL + inaccurate), `pandas-ta` original (dead/closed-source), `tulind/tulipy` as backend (LGPL + Windows C build), `python-jose 3.5.0` (dead — use `joserfc`), `aiocache` (stale), `fastapi-cache2 0.2.2` pre-G12 (masks mock-200), `pyfolio 0.9.2` / `empyrical 0.5.5` (dead/stale), `zipline-reloaded` / `sktime` / `pomegranate` (weight without P1 payoff), `openturns 1.27` (80MB C++ for one GPD fit), `pyvinecopulib 0.7.6` (100x overkill), `scikit-extremes` (dead original + 2026 squat fork), `nsepy`/`nsetools` (deprecated/unmaintained), `forex-python 1.9.2` (stale rates). No `pip install pot` exists.

---

## 1. Portfolio optimization — replace hand-rolled estimators

| Candidate | PyPI / verified ver. / license / signal | Fixes | Replace vs custom |
|---|---|---|---|
| `skfolio==1.0.3` BSD-3, release 2026-08-31, 2336★, freshest — **recommended primary** | HRP P0-1, CVaR free-alpha P1, ERC missing, BL caveats, Euler RC gap, frontier | Replaces `_hrp_weights`, `_min_cvar`, ERC sizing, BL posterior block. Stays custom: data prep, Q units (annualized excess), τ∈[0.01,0.05], long-only+caps, clip+renorm, 252 docs |
| `riskfolio-lib==7.3.0` BSD-3, 2026-05-31, 4479★ — alternative | Same + `port.alpha` (β forwarded), `model='RP'` (CVaR/CDaR/EVaR budgets), only capped-HRP via `hrp_constraints()` | Same boundary as skfolio. Heavier API. Pick if NSE weight-capped HRP required |
| `pyportfolioopt==1.6.0` MIT, 2026-02-26, 6005★ — lightweight fallback | HRP (`HRPOpt`), CVaR (`EfficientCVaR(beta=)`), min-vol/max-sharpe, BL (`BlackLittermanModel` He-Litterman), `efficient_risk(target_vol)` partial, `DiscreteAllocation` beats `int()` truncation | Replaces same estimators. No ERC, no factor models, HRP uncapped. `clean_weights()` → renorm after |
| `cvxportfolio==1.5.1` GPLv3 — **reject** | Could fix turnover/Sharpe/cost ledger technically | GPL blocks proprietary backend. Own Yahoo/US simulator fights 3-tier cascade. Fix turnover in-house (~5 lines F6); borrow Boyd et al. 2017 cost math for G14 only |
| `cvxpy==1.9.2` + `clarabel==0.11.1` Apache-2.0 (incumbent) — keep, narrow | `_min_vol`/`_max_sharpe`/BL-tangency sound; only bug is `cp.Variable(neg=True)→cp.Variable()` | Keep as escape hatch for bespoke NSE constraints (turnover/sector/ASM veto/tracking-error). Stop hand-rolling textbook HRP/CVaR/ERC/BL on top |
| `scipy==1.18.1` BSD-3 (incumbent) — keep | `linkage` + quasi-diag ordering sound half of HRP | Keep for linkage/dendrogram display if skfolio/riskfolio takes over HRP |

Sketches (proposals, not applied):
```python
import riskfolio as rp
port = rp.Portfolio(returns=daily_rets)  # cleaned in-house: active-history, inner-join, no zero-fill
port.assets_stats(method_mu='hist', method_cov='hist')
w_hrp = port.optimization(model='HRP', codependence='pearson', rm='MV', linkage='single')
port.alpha = 0.05  # beta forwarded — P1 fix
w_cvar = port.optimization(model='Classic', rm='CVaR', obj='MinRisk')
w_erc = port.optimization(model='RP', rm='MV')
```
```python
from skfolio.optimization import HierarchicalRiskParity, MeanRisk, RiskBudgeting
from skfolio.prior import BlackLitterman
from skfolio import RiskMeasure
hrp = HierarchicalRiskParity().fit(X_train)
cvar = MeanRisk(risk_measure=RiskMeasure.CVAR).fit(X_train)
erc = RiskBudgeting(risk_measure=RiskMeasure.VARIANCE).fit(X_train)
bl = MeanRisk(prior_estimator=BlackLitterman(views=["RELIANCE - TCS == 0.03"])).fit(X_train)
rc = bl.predict(X_test).contribution(measure=RiskMeasure.VARIANCE)  # Euler RC_i
```
Caveats: pin versions; feed from single cleaned-returns boundary; document 252 annualization at `_as_matrices`; renorm after rounding; long-only+caps explicit (NSE short-sale rules); skfolio estimator names move 0.x→1.x — re-verify `min/max_weights`, `model_selection` splitters at integration.

---

## 2. Backtest + time-series stats — mostly keep custom, delegate selectively

| Candidate | Verdict |
|---|---|
| Walk-forward splitter (audit: sound) | Keep custom. Optional `sktime==1.1.0` BSD-3 splitter later |
| Turnover 2x + day-0 lump + geometric Sharpe | Custom F6: `one_way=0.5·Σ\|Δw\|`, `chunk[0]=(1-c)(1+chunk[0])-1`, `(mean×252-rf)/(std(ddof=1)·√252)`. `vectorbt`/`bt` only as ledger reference |
| `vectorbt==1.1.0` fair-code (Commons Clause) | Fixes same P1s + O2 vectorization, but commercial block vetoes framework adoption. `fees/slippage` flat can't express asymmetric STT/stamp/SEBI/GST. NSE holidays break `freq='D'` annualization. Unshifted `from_signals` = lookahead |
| `bt==1.2.0` MIT | Same P1s at small scale; `commissions=` fn pattern worth borrowing; algo-tree slow, no anchored walk-forward primitive |
| `backtesting.py==0.6.6` AGPL-3.0 | Reject for backend (SaaS copyleft + single-asset `Strategy/next()` ≠ multi-asset optimizer) |
| `zipline-reloaded==3.1.1` Apache-2.0 | Reject — bundle/calendar weight for zero P1 gain |
| `quantstats==0.0.81` Apache-2.0 (incumbent) | Selective delegate + verify. Extend `_q` guard. Verify Sortino downside == `sqrt(mean(min(0,r-t)²))`, `periods`/`rf` units. Doesn't fix active-history/zero-fill — filter first |
| `pyfolio==0.9.2` / `empyrical==0.5.5` Apache-2.0 | Do not add (dead 2019 / stale 2020). Copy formulas into tested custom code |
| `ffn==1.1.5` MIT | Lightweight stats-only alternative; `infer_nperiods` fragile on NSE gaps — pass explicit 252; `to_monthly` NSE-fragile vs hand `(1+r).groupby([y,m]).prod()-1` |
| `arch==8.0.0` NCSA (incumbent) | Expand: `EWMAVariance(lam=0.94)` / `RiskMetrics2006` replaces double-smooth F4; `arch_model(...,dist='t')` + `α+β<1` + finite check; pre-winsorize `clip(±20%)` still custom; `StationaryBootstrap` seed cast `int(rng.integers(...))`; `to_thread` + `(hash(r),horizon)` memo |
| `statsmodels==0.15.0` BSD-3 (incumbent) | Replace hand OLS now: `sm.OLS(y,X).fit(cov_type='HAC', cov_kwds={'maxlags':5,'use_correction':True})` + active-index filter kills β→0. `MarkovRegression(k=3, switching_variance)` is the honest HMM migration (filtered last-bar probs = causal; smoothed only for history) |
| `linearmodels==7.0` NCSA | Defer to G7 Barra (panel/Fama-MacBeth/GMM). Needs NSE-500 master (G16) first |
| `ruptures==1.1.10` BSD-2 — **new, tiny, adopt as complement** | `Pelt(model='l2',min_size=21,jump=5)` on 1d log-rets validates HMM without MA(20) violation; `n<200` fallback; vol-cone break annotation. Offline by construction — expanding window, only `bkps<as_of` |
| `pomegranate==1.1.2` MIT | Pass (torch weight, v1 API break, no Viterbi) unless GPU/Bayesian need |
| `sktime==1.1.0` BSD-3 | Defer (largest dep tree, no cost/Sharpe benefit) |

Cross-cutting: lookahead (`from_signals` shift-1, ruptures full-sample fit, HMM scaler+smoothed probs, quantstats alignment, resample defaults) → causal features + expanding stats + filtered probs. NSE fit: no backtester models asymmetric STT/stamp/SEBI/GST or `σ√(Q/ADV)` — custom `costs.py` (G14) required. Resampling: pass explicit 252, active-history filter, document daily-rebalanced assumption.

---

## 3. Tail / copula / coint / correlation — one new dep max, rest custom

| Issue | Library | Verdict | New dep? |
|---|---|---|---|
| EVT mock fallback + threshold choice | `pyextremes==2.5.0` MIT, active (273★, PR Feb 2026) — **adopt for diagnostics only** | Threshold diagnostics (MRL, stability, declustering `r` — set explicitly, not `24h` default), `EVA.fit_model(distribution="genpareto")` + CIs. Keep McNeil closed-form VaR/ES (audit SOUND). Raise `insufficient_data`, never hardcode; log + `xi_clipped` flag | Yes — small, MIT. Bare install (skip `[full]` emcee/corner extras). Stateful `EVA` → `to_thread` + cache |
| `scikit-extremes` / `POT` | Dead original + 2026 squat fork / nonexistent | Rejected | — |
| `openturns==1.27.post1` LGPL | Real GPD + small-sample PWM, but 80MB C++ for one fit | Rejected (revisit only if G8 scenario engine adopts OpenTURNS wholesale) | — |
| t-copula ρ | `statsmodels` `StudentTCopula.fit_corr_param` (Kendall-τ) — already installed | Adopt Kendall-τ ρ (`sin(πτ/2)`, robust to fat tails). Covers ρ half only; pin minor version (young submodule) | No |
| t-copula ν | Custom 1-d bounded MLE on PIT uniforms (McNeil-Frey-Embrechts §5.3 IFM) | Custom: `u=rank/(n+1)`, Kendall ρ, `minimize_scalar(nll,[2.1,30])`, pooled/global ν cached per `(hash(a),hash(b))` — fixes O8 (380 fits→1). No maintained lib covers ν | No |
| `copulas==0.14.1` BUSL-1.1 | Wrong license + wrong problem (synthetic-data vines, no λ/ν fitter) | Rejected | — |
| `pyvinecopulib==0.7.6` MIT | Correct license, 100x overkill (compiled vines for bivariate λ) | Rejected | — |
| ADF/KPSS pre-test + AIC lags | `arch==8.0.0` (`ADF`, `KPSS`, `engle_granger(lags=None)`) — already installed | Augment (don't replace `coint`/`coint_johansen`): ADF-both-legs gate kills stationary-pair false positives; expose `trend/autolag/k_ar_diff`; AIC-select Johansen lags; cheap ADF pre-filter before O(N²) scan | No |
| OU oscillatory + RankWarning | Custom branch + var guard | No lib exists: `-2<γ≤-1` → `(None,None)` + `oscillatory` flag; `var(p_b)<1e-12→None`; `catch_warnings(error)` around polyfit | No |
| Cov singularity (HRP/min-vol) | `scikit-learn` `LedoitWolf` (default; OAS opt-in) — already installed | Adopt: PD-guaranteed `((1-δ)S+δμI)`, kills `psd_wrap` band-aid, stabilizes IVP init. Use shrunk σ consistently with sizing; `assume_centered=False` for returns | No |
| Fisher-z + LOO threshold | Custom 5-liners | `arctanh(clip)→mean→tanh`; thresholds on `corr_values[:-1]`; `>=` unify | No |
| HHI/diversification | — | Confirmed trivial (`Σw²`, `1/HHI`, `((1-HHI)/(1-1/N))×100` → single 0%). Rename `diversification_ratio→effective_share` only | No |

Also fix in same edits: drop `ρ≥0.999→1.0` discontinuity; `top_pairs` separate key (LOW ≠ high-tail); `dropna` not `fillna(0.0)` in suite. Order (Sprint 2): insufficient-data + ξ flag → OU/RankWarning → Fisher-z/LOO → ADF gate → Kendall-ρ + ν-MLE + pooled cache → LedoitWolf → pyextremes diagnostics last.

---

## 4. Data + infra + API — least-infra wins, three layers for retry/limit

### 4.1 HTTP / retry / rate-limit / concurrency (no new infra)

- `httpx==0.28.1` BSD-3 (strong, 15.4k★; `1.0.dev5` prerelease — pin `<1`): promote dev→main. One pooled `AsyncClient` singleton (lifespan) replaces `requests` + ad-hoc sync in async paths (O16/O20/G12). Consolidate new code on httpx; keep `aiohttp==3.14.3` Apache-2.0 only where embedded (remove unused FX import).
- `tenacity==9.1.4` Apache-2.0 (8.7k★): replaces hand `_yf_retry` + AV retry loops. Limiter outside, retry inside (`AsyncRetrying`, `wait_exponential_jitter`, map crumb-401→503 at boundary).
- `aiolimiter==1.2.1` MIT (stable/finished, 775★): `AsyncLimiter(5,60)` per host replaces hand throttling; keep budget/demotion under `asyncio.Lock`. Defer `pyrate-limiter==4.4.0` MIT to Redis multi-bucket phase (v3→v4 churn, no need now).
- `anyio==4.14.2` MIT / stdlib `asyncio`: no new dep. `Semaphore(5)` fan-out + per-key `Lock` single-flight (generalize working FX pattern) + `to_thread` (GARCH/HMM/blocking yfinance) + per-task `AsyncSession` (never share across `gather()` — the shared-session P1 is correctness, not perf).

### 4.2 Cache — fix usage, not libs (defer Redis)

- `redis==8.1.0` MIT: defer to G12 (multi-worker/screener-persist/WS pub-sub). Biggest infra risk for single-user SQLite app.
- `aiocache` (BSD, 62 open issues, valkey migration stalled) / `fastapi-cache2==0.2.2` (thin fork, no proactive evict, masks mock-200): do not adopt pre-G12.
- `diskcache==5.6.3` Apache-2.0: optional later (serverless persistent memo; sync → `to_thread`). Prefer fixing SQLite `AnalyticsCache` (upsert+TTL) over second store.
- `cachetools==7.1.8` MIT (strong): **adopt** — instance `TTLCache(maxsize,ttl)` + lock replaces class-level unbounded df cache, screener mutation-poison (key includes `hash(universe)`), GARCH/cone/HMM memo keys.
- `async-lru==2.3.0` MIT (aio-libs): **adopt** for coroutine memo only (`@alru_cache` on hash/as-of keys; not wall-clock TTL).
- Least-infra prescription: per-task sessions → SQLite `on_conflict_do_update(["ticker","metric_name"])` (P0-8) → per-key single-flight → single TTL from `settings` (kill 300s/30m/60m clocks) → TTLCache + async-lru → `GlobalCacheService` forwards TTL.

### 4.3 Auth / metering — HTTP yes, WS hand-rolled

- `slowapi==0.1.10` MIT (2k★, alpha-quality, 96 issues): **adopt for HTTP only** — per-route budgets (screener=expensive), batch/refresh caps, broadcast cost. No WS support — WS tick needs hand token-bucket. Fix honest envelopes first so 429s are truthful.
- `fastapi-users` 13.x–15.x MIT: **defer** — officially maintenance-mode; HTTP-only; adopt only when multi-seat scoped (its `db-sqlalchemy` fits stack).
- `joserfc` 1.7.x / `authlib==1.8.0` BSD-3 (lepture, active): **adopt `joserfc`** — short-lived JWT verify on WS `?token` connect + broadcast guard. Import from `joserfc` (authlib deprecates `authlib.jose`).
- `python-jose==3.5.0` MIT: never (dead, backend-selection mess, CVE exposure). Migrate any usage to `joserfc`.

### 4.4 Validation / indicators / universe / FX / dossier / logging

- `pandera==0.33.1` MIT (Union.ai, 4.4k★): **adopt at one boundary** — `DataFrameModel` after `_normalize_*` (fixes TitleCase/lowercase split-brain structurally; `Adj Close`/`Date`-name assumptions; `"-"` coercers repair before validate rejects → 503/insufficient-data, never mock-200). Import via `pandera.pandas` (mandatory since 0.24). Never in hot loops.
- Indicators: **keep `stockstats`** (causal trailing-only confirmed; add `shift(1)` for backtests + `max(420,lookback*2+300)` warmup + canonical ticker). Selectively add `ta==0.11.0` MIT (stale-but-stable, pure pandas) only for missing variants. Never `pandas-ta` original (dead/closed) / `finta==1.3` (archived+LGPL+inaccurate) / `tulind` backend (LGPL + C build pain); `pandas-ta-classic` MIT fork only if 150+ surface with parity tests proven needed.
- Universe/NSE: no safe long-term lib (all scrape = ToS/ban risk). Stopgap behind `MarketDataProvider` adapter + G16 master CSV (`EQUITY_L.csv` + BSE `Equity.csv`): `jugaad-data` (new NSE site + cache + threading, history bulk) or `nsepython` (derivatives/VIX/RBI breadth) — pick one, never both. `nsepy` deprecated by author, `nsetools` unmaintained — remove if referenced. Budget authorized vendor G2 (GFDL/TrueData/Upstox ₹15–40k/yr).
- Quotes fallback: `yahooquery==2.4.1` MIT as **complement** (batch/async, keeps `.BO` intact, second source on crumb-401). Keep `yfinance==1.7.0` primary OHLCV. Same pandera boundary for both.
- FX: reject `forex-python==1.9.2` (stale free backend). G5 instead: RBI FBIL + NSE CD forwards in `currency_service`; keep single-flight; stale-`83.0` short-TTL + `stale:true`; unknown pair raise.
- Dossier: `tiktoken==0.14.0` MIT (18.9k★): **adopt** — exact counts per serving model, section/window caps + `truncated:true` + per-call cache before render; cap `custom_instructions` (injection sink).
- Logging: `structlog==26.1.0` MIT/Apache-2.0 (contextvars-native JSON, audit-trail fit) over `loguru==0.7.3` (24k★ but slow cadence). `exc_info` on every except; request-id bind across fan-out.
- DB: keep `SQLAlchemy==2.0.52` + `alembic==1.19.1` MIT; change usage (per-task `async_sessionmaker`, lifespan `upgrade head` not `create_all`, absolute DB path, `debug=false`, bare `raise`, `String(20)` + `Unique(ticker)` + checks + FK cascade, `(ticker,expires_at)`/NSE UQ indexes, `delete(where)` + `func.count()`, `datetime.now(timezone.utc)`).

---

## 5. Sequenced adoption (least-regret; re-pin versions at install)

1. **Zero-dep first (this sprint, no `uv add`):** per-task sessions, per-key locks, SQLite upsert, single TTL, `import inspect`, `or {}` allocation, honest 404/503 + EVT `insufficient_data`, ticker passthrough + regex + `String(20)`, coint full-ticker key, screener key/universe/`.BO`/debt, OU/RankWarning, Fisher-z/LOO, Sortino/EWMA/CVaR/target-vol/risk-benchmark/backtest-F6, HMM features/scaler/priors/filtered probs, GARCH winsorize + `t` + persistence, delivery/ADV/bhavcopy/N+1, `is_prices` flag, kurtosis/adj-R²/rounding conventions.
2. **One command (only after 1):** `skfolio` **or** `riskfolio-lib` (one, not both) + `tenacity` + `aiolimiter` + `cachetools` + `async-lru` + `pandera` + `structlog` + `ta` (if needed) + `yahooquery` + `tiktoken` + `slowapi` + `joserfc` + `ruptures` + `pyextremes` (diagnostics last) + promote `httpx` to main.
3. **Defer:** `redis` (G12), `pyrate-limiter` (distributed), `fastapi-users` (multi-seat), `pandas-ta-classic` (proven need), `diskcache` (SQLite-cache insufficient), full `authlib` OAuth (OAuth ships), `linearmodels` (G7), `sktime`/`pomegranate`/`zipline` (no P1 payoff).
4. **Never:** `cvxportfolio` (GPL), `backtesting.py` (AGPL), `vectorbt` (Commons Clause), `copulas` (BUSL), `finta`/`tulind`-backend (LGPL + accuracy/build), `pandas-ta` original (dead), `python-jose` (dead), `aiocache`/`fastapi-cache2` pre-G12, `pyfolio`/`empyrical`, `openturns`/`pyvinecopulib`/`scikit-extremes`, `nsepy`/`nsetools`/`forex-python`.

*No source files modified. Sketches are proposals. License flags (GPL/AGPL/BUSL/Commons-Clause/LGPL) reviewed 2026-09-03 — re-confirm at adoption; NSE scraping carries ToS risk regardless of library — prefer authorized vendor for G2/G3/G5.*
