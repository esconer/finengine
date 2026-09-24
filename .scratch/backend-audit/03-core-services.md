# Backend audit: core services
Status: complete
Files: backend/app/services/analytics_engine.py (1416 lines), backend/app/services/data_service.py (1209 lines), backend/app/services/cache_service.py (284 lines)

Scope note: findings verified by reading these three files plus contracts in models/database.py, app/api/analytics.py, app/api/data.py, app/api/websocket.py, app/services/{benchmark_service,alpha_vantage_service,source_preference_service}.py and backend/tests/. Only assigned files are in review scope; callers cited solely to prove reachability.

## Bugs

### P1

- [P1] `analytics_engine.py:1170` — When the benchmark leg is missing/short OR the portfolio-level OLS fails, the function **overwrites already-computed per-position regressions with the banned `{alpha:0, market:1}` placeholder** and returns it as real data (CONTEXT gotcha #23 explicitly forbids this — it rendered as "β +1.000 Market-Like" for every position). Two triggers verified: (a) `benchmark_returns` empty or ≤10 rows (line 1098/1100 conditions false) skips the real-regression block entirely; (b) portfolio OLS failure at line 1151/1154 (`raise ValueError("insufficient active portfolio history")` / OLS exception) is swallowed by `except Exception: pass` at line 1167-1168, falls out of the block, and the line-1170 loop clobbers the correct `positions_exp` built at lines 1104-1144. The placeholders are additionally self-contradictory: `'is_limited_history': False, 'data_points': 0, 'history_warning': None`. Reachable in production: `app/api/analytics.py:652-663` passes `benchmark_returns=None` whenever `benchmark_service.get_returns` fails, with no guard before calling `factor_exposure_analysis`. No test covers this path (only `risk_scoring`'s no-benchmark exclusion is tested at `tests/test_quant_math_p1_batch.py:249`; `tests/test_analytics_engine.py:140` always passes a benchmark).
  Quote: `positions_exp[ticker] = {'alpha': 0.0, 'annualized_alpha': 0.0, 'market': 1.0, 'is_limited_history': False, ...}`
  Fix: on missing/short benchmark or portfolio-OLS failure, return positions with `market: None`/N/A plus a flag (or keep the valid per-position results and only null the portfolio leg); never emit `market: 1.0` unflagged; do not let line 1167's `pass` fall through to the placeholder loop.

- [P1] `data_service.py:840` — Alpha-Vantage quote fallback sets `is_indian` by testing the `.BSE` suffix against a **canonical** ticker, which is never `.BSE` (canonical forms are `.NS`/`.BO`/bare, per `canonical_ticker` at lines 40-65; `.BSE` only exists inside `to_av_symbol`'s AV-specific conversion). Production callers pass canonical tickers: line 561 `self._fallback_quote(ticker, normalized_ticker)` and line 565. Therefore `".BSE" in "RELIANCE.NS"` → False and `".BSE" in "500112.BO"` → False, so **every** AV-fallback Indian quote gets `is_indian=False` (`fetch_global_quote` in alpha_vantage_service.py:309-326 returns no `is_indian` key, so the setdefault always fires). The existing test masks this by passing a non-canonical arg: `tests/test_coverage_data_service.py:336` — `q = await service._fallback_quote("RELIANCE.NS", "RELIANCE.BSE")`.
  Quote: `q.setdefault("is_indian", ".BSE" in normalized_ticker.upper())`
  Fix: `q.setdefault("is_indian", self._is_indian_ticker(normalized_ticker))` (checks `.NS`/`.BO`), and fix the test to pass the canonical ticker the production path actually passes.

### P2

- [P2] `analytics_engine.py:143` + `analytics_engine.py:1115` — Beta/alpha regressions drop **genuine 0% return days** because inactivity is detected via `s != 0.0` *after* line 143 already converted every missing day to 0.0 (`fillna(0.0)`). Days where the stock truly did not move (illiquid/limit-flat days) are informative (benchmark moved, stock didn't) and excluding them biases beta upward; the correct inactive mask is the pre-fillna NaN mask.
  Quote: `active = s[s != 0.0].index.intersection(aligned_benchmark.index)`
  Fix: build the returns frame without `fillna(0.0)` for the regression path (or carry a boolean active mask from the raw prices) and regress on `notna()` days.

- [P2] `analytics_engine.py:62` — `calculate_portfolio_metrics` silently skips normalization when `weight_sum <= 0` (all-zero or negative weights), unlike the factor path which falls back to equal weights (lines 155-157). Portfolio returns become an all-zero series and metrics are computed anyway: Sharpe 0, VaR 0, hit ratio 0, and Sortino = `(0 - rf) / rf = -1.0` (downside deviation equals daily rf when every return is 0). Meaningless numbers returned as success, no error flag. Only a no-crash test exists (`tests/test_wave1_regressions.py:90`).
  Quote: `if weight_sum > 0: weights = {k: v/weight_sum for k, v in weights.items()}`
  Fix: mirror the factor-path behavior — `else:` equal-weight (or return `_empty_metrics()` with error).

- [P2] `analytics_engine.py:1303` — `_empty_forecast` hardcodes `"model": "GARCH"` (line 1308) and `model_params type GARCH`, but is returned for failed EGARCH and EWMA requests too: `forecast_volatility` line 106 returns `self._empty_forecast()` (no model arg) whenever `len(returns) < 30`, and `_egarch_forecast`'s `except` at line 1048 also returns it. API consumers receive `model: "GARCH"` for an EGARCH/EWMA request (the `error` key is present, but the model label is wrong).
  Quote: `"model": "GARCH",`
  Fix: pass the requested model into `_empty_forecast(model=...)` and echo it in `model`/`model_params`.

- [P2] `analytics_engine.py:1287` (and 1371, 1391) — Empty/error results fabricate realistic-looking metrics: `_empty_metrics` returns `annual_volatility: 0.20, hit_ratio: 0.5, kurtosis: 3`; `_empty_stress_test` returns `max_drawdown: -0.20, portfolio_impact: -0.17, recovery_time: 30`; `_empty_risk_score` returns `overall_score: 25.0, risk_level: "MEDIUM"` with invented component scores `{15,15,10,20,10}`. This is exactly the placeholder pattern banned by CONTEXT gotcha #23 ("return N/A + a flag"). The router returns these dicts as-is. Tests **enshrine** the placeholder: `tests/test_analytics_engine.py:35` asserts `result["annual_volatility"] == 0.20`.
  Quote: `"annual_volatility": 0.20,`
  Fix: return nulls/`None` components + `error` flag only; update the two asserting tests.

- [P2] `data_service.py:377` — If a vendor frame fails normalization (e.g. missing `Adj Close`), the function returns the empty frame immediately, **aborting the remaining retry attempts AND the Alpha Vantage tier**: `if df.empty: return df` executes inside the retry loop before the loop can continue or reach line 410's AV fallback. A single vendor returning an unnormalizable frame defeats the whole 3-tier cascade.
  Quote: `if df.empty: return df`
  Fix: `continue` (treat as failed attempt) so retries/AV still run; only return empty after all tiers are exhausted.

- [P2] `data_service.py:932` — Partial-history tickers never reach a stable cache state: for a ticker whose real history starts >30 days after `req_start` (IPO, new ETF), `(earliest_cached - req_start).days > 30` stays permanently true, so after the 1-hour `fetched_on` grace expires (line 934), **every subsequent request is a cache miss and re-downloads the full 10-year deep window from the vendor**, even though the row set cannot change. Verified flow: miss → vendor download → upsert (same rows, `fetched_on` refreshed) → serve; repeat on every request >1h later. `tests/test_deep_cache.py` covers stale-tail and deep-start but not this start-gap condition.
  Quote: `if (earliest_cached - req_start).days > 30 or len(records) < min(30, int(req_days * 0.3)):`
  Fix: treat a successful deep backfill (`fetched_on` updated with `dl_start` reached) as authoritative coverage instead of a wall-clock grace; e.g. persist a `coverage_start`/backfill-done marker per ticker.

- [P2] `data_service.py:565` — The exception path of `fetch_quote` passes the **raw** uppercased ticker as the `normalized_ticker` argument to `_fallback_quote`, skipping `canonical_ticker`: input `"reliance"` → AV queried for `"RELIANCE"` instead of `"RELIANCE.NS"` (compare correct call at line 561). Test coverage exists but does not assert the args (`tests/test_coverage_data_service.py:186-192` only checks the returned price).
  Quote: `return await self._fallback_quote(ticker, ticker.upper().strip())`
  Fix: `return await self._fallback_quote(ticker, normalized_ticker)` (variable already computed at line 434).

- [P2] `data_service.py:660` and `data_service.py:687` — Synchronous yfinance network calls executed directly inside `async def`, blocking the event loop for the duration of the HTTP round-trip: `validate_ticker` calls `stock.history(period="5d")` inline (the bfinance branch at line 658 correctly uses `asyncio.to_thread` — the yfinance branch does not), and `get_corporate_actions` calls `stock.splits` / `stock.dividends` inline. Both are awaited from request handlers (`app/api/data.py:438`, `app/api/portfolio.py:170/327`). Existing tests mock yfinance so the blocking is invisible (`tests/test_coverage_data_service.py:194-231`).
  Quote: `hist = stock.history(period="5d")`
  Fix: wrap the yfinance calls in `asyncio.to_thread` like the bfinance branch; same for `splits`/`dividends`.

- [P2] `cache_service.py:74` — `set_cached_analytics` delete-then-insert is **not race-safe**: two concurrent writers (separate sessions, e.g. parallel screener/cointegration requests computing the same key) can interleave `DELETE` → both `INSERT` → two rows. `AnalyticsCache` has only a non-unique `Index("ix_ticker_metric")` (models/database.py:84-86), so nothing prevents the dupe; the next `get_cached_analytics` raises `MultipleResultsFound` inside `scalar_one_or_none`, caught at line 49-51 → returns None → **perpetual cache miss** until another `set` happens to delete both rows. The docstring (lines 61-68) claims this is fixed and admits the missing UQ as a "P1 follow-up"; `tests/test_p08_cache.py` only proves the sequential case.
  Quote: `delete(AnalyticsCache).where(AnalyticsCache.ticker == ticker, AnalyticsCache.metric_name == metric_name,)`
  Fix: add `UniqueConstraint("ticker", "metric_name")` and use `sqlite_insert(...).on_conflict_do_update(...)` (same pattern already used for `StockTimeseries` and `AppSetting`).

### P3

- [P3] `analytics_engine.py:479` — Scenario matching treats an empty/None scenario as a match for the **first** config key: `scenario_key = ""` makes `scenario_key in k` true for `"market_crash"` (`"" in "market_crash"` → True), so `stress_test(..., scenario="")` silently runs the -35% market crash instead of falling through to the custom/default branch.
  Quote: `if k in scenario_key or scenario_key in k:`
  Fix: `if scenario_key and (k in scenario_key or scenario_key in k):`.

- [P3] `analytics_engine.py:484` — Comment promises custom shock parsing that does not exist: the "custom" branch hardcodes `market_shock: -0.20` regardless of any number in the scenario string (e.g. `"crash -10%"` matches no key and still yields -20%).
  Quote: `# Custom shock if present in scenario string`
  Fix: either parse a signed percentage from `scenario` or reword the comment to "fixed -20% default".

## Improvements

- [P2] `analytics_engine.py:11` — Module-level `warnings.filterwarnings('ignore')` suppresses **all** warnings process-wide for every module imported afterwards (arch convergence warnings, pandas deprecation notices, numpy runtime warnings disappear app-wide), contradicting gotcha #14's intent to observe GARCH convergence issues.
  Quote: `warnings.filterwarnings('ignore')`
  Fix: scope it (`category=ConvergenceWarning` etc.) or use `warnings.catch_warnings()` around the arch fits.

- [P3] `analytics_engine.py:835` (also 876, 895, 913, 926, 967, 1242, 1263, 1282) — Nine bare `except:` clauses swallow `KeyboardInterrupt`/`SystemExit` and hide real defects (e.g. `except: return pd.Series(dtype=float)` in `_calculate_portfolio_returns`).
  Quote: `except:`
  Fix: `except Exception:` at minimum; log in the metric helpers instead of returning `{}` silently.

- [P3] `analytics_engine.py:1233`, `1245`, `1266`, `1346` — Dead production code: `_calculate_max_drawdown`, `_simulate_stress_drawdown`, `_estimate_recovery_time`, `_calculate_liquidation_days` are referenced only by `tests/test_analytics_engine.py` (369-416); `stress_test`/`liquidity_analysis` compute their own values inline (lines 537, 348-356).
  Quote: `def _simulate_stress_drawdown(self, weights: Dict[str, float]) -> float:`
  Fix: delete the four helpers and their unit tests (or route `stress_test`/`liquidity_analysis` through them).

- [P3] `analytics_engine.py:1187` / `1210` — `_calculate_r_squared` and `_calculate_adjusted_r_squared` are near-identical copies, and together with `_calculate_factor_exposures`'s portfolio regression (line 1154) the **same portfolio-on-benchmark OLS runs three times** per request. Adjusted R² is closed-form from raw R².
  Quote: `model = sm.OLS(portfolio_returns, X).fit()` (lines 1204 and 1227)
  Fix: one regression in `factor_exposure_analysis`; derive `rsquared_adj` from `model.rsquared`.

- [P3] `analytics_engine.py:830` — Dead defensive check: `weight_vector` is built by iterating `returns.columns`, so `len(weight_vector) != len(returns.columns)` can never be true.
  Quote: `if len(weight_vector) != len(returns.columns):`
  Fix: delete the branch.

- [P3] `analytics_engine.py:317` — Dead branch in liquidity tier 4: score is clamped `min(5.9, ...)` at line 316, so `category = "Low" if score < 6.0 else "Medium"` can never take the `"Medium"` arm.
  Quote: `category = "Low" if score < 6.0 else "Medium"`
  Fix: `category = "Low"`.

- [P3] `analytics_engine.py:28` — `risk_free_rate = 0.02` hardcoded in `__init__` while every other tunable lives in `app/config.py` `settings`; not overridable per environment.
  Quote: `self.risk_free_rate = 0.02  # 2% annual risk-free rate`
  Fix: `self.risk_free_rate = settings.risk_free_rate`.

- [P3] `data_service.py:1` — Docstring is stale: claims "yfinance as primary source" while the file implements a user-selectable bfinance/yfinance cascade with AV last (lines 354-356, 409).
  Quote: `Data service for fetching market data using yfinance as primary source`
  Fix: rewrite to describe the 3-tier cascade.

- [P3] `data_service.py:1140` — `from sqlalchemy import func, select` re-imported inside `check_data_integrity` though already imported at module top (line 12); also `ticker: str = None` should be `Optional[str]` (line 1137).
  Quote: `from sqlalchemy import func, select`
  Fix: drop the local import, annotate `ticker: Optional[str] = None`.

- [P3] `data_service.py:1027` + `1104` — `_log_storage_metrics(ticker, len(records), 0)` always passes `replaced_count=0`, so `replacement_ratio` is always 0 and the high-replacement warning at line 1104 is unreachable dead code.
  Quote: `await self._log_storage_metrics(ticker, len(records), 0)`
  Fix: count conflicts from the upsert result (`result.rowcount` deltas) or delete the metric helper.

- [P3] `data_service.py:543` / `734` — Production code sniffs for `unittest.mock` to decide vendor behavior (`is_yf_mocked = isinstance(yf.Ticker, ...)`), coupling runtime logic to the test framework; any test that uses a different mocking style silently hits real vendors.
  Quote: `is_yf_mocked = isinstance(yf.Ticker, (unittest.mock.Mock, unittest.mock.MagicMock))`
  Fix: inject the vendor callables (constructor args / DI) and let tests pass fakes.

## Optimizations

- [P2] `analytics_engine.py:982` (also 1022) — `arch_model(...).fit(...)` is CPU-bound (scipy optimizer) yet runs synchronously inside `async def _garch_forecast`/`_egarch_forecast`, **blocking the event loop** for every fit. `volatility_sizing` awaits it once per ticker in a serial loop (lines 589-601) and the forecast endpoint does the same (`app/api/analytics.py:527-533`): a 10-position portfolio with `model=GARCH` stalls all concurrent requests for seconds. The `async def` signature implies off-loop execution it does not deliver.
  Quote: `fitted_model = model.fit(disp='off', show_warning=False, options={'maxiter': 100})`
  Fix: `await asyncio.to_thread(model.fit, ...)` (and/or parallelize the per-ticker loop with a semaphore).

- [P2] `cache_service.py:155` — `get_cache_stats` materializes the **entire** `analytics_cache` table three times (`total`, `active`, `expired` selects at lines 155, 160, 167) plus every `FetchLog` from the last 24h (line 174) just to count them, then filters in Python (line 181). Served by `GET` in `app/api/data.py:173`; grows unboundedly with cache size.
  Quote: `total_query = select(AnalyticsCache)`
  Fix: `select(func.count()).select_from(AnalyticsCache)` (+ `WHERE expires_at > ...`), and compute success rate with a filtered `func.count()`/`func.sum(case(...))`.

- [P3] `cache_service.py:135` — `clear_expired_cache` issues one `await self.db.delete(entry)` per expired row instead of a single set-based DELETE.
  Quote: `for entry in expired_entries: await self.db.delete(entry)`
  Fix: `await db.execute(delete(AnalyticsCache).where(AnalyticsCache.expires_at <= datetime.utcnow()))`. (Also: no production caller — only tests — so expired rows otherwise live until a full cache purge.)

- [P3] `data_service.py:347` — Every SQLite cache **hit** additionally loads the ticker's full-depth history (`_get_full_cached_frame`, all ~2500 rows for 10y) solely to populate L1 — while holding the global `_db_lock` that serializes all DB access for the instance (line 81).
  Quote: `full_frame = await self._get_full_cached_frame(normalized_ticker) if cached_data is not None else None`
  Fix: skip the full-frame load when L1 already has a live entry, or populate L1 lazily on first full-window request.

- [P3] `data_service.py:931` — (see Bugs P2 `data_service.py:932`) the same path causes a full 10y vendor download where serving existing DB rows would suffice — repeated network IO on a per-ticker, per-hour cycle for all partial-history tickers.

- [P3] `analytics_engine.py:740` — `returns.corr()` is computed **twice** in one expression (`returns.corr().values[...]` appears for both the index selector and the gather).
  Quote: `avg_correlation = returns.corr().values[np.triu_indices_from(returns.corr().values, k=1)].mean()`
  Fix: `c = returns.corr().values` once, then index it.

- [P3] `data_service.py:767` — `asyncio.wait_for` around `loop.run_in_executor` cannot cancel the worker thread on timeout: each timed-out attempt leaves a zombie `download()` thread running while the retry spawns another (up to 3 stacked downloads per ticker × 5 concurrent batch workers), then AV fallback may run on top.
  Quote: `df = await asyncio.wait_for(loop.run_in_executor(None, download), timeout=self.yfinance_timeout)`
  Fix: accept the limitation with a comment, or run downloads in a cancellable thread pool with per-ticker single-flight (dedupe concurrent identical fetches too — two simultaneous `fetch_historical_data` calls both miss and both download).

- [P3] `data_service.py:422` — `fetch_quote` has **no caching layer** (no L1, no SQLite quote table): every dashboard/WS/portfolio refresh loops through live vendor calls (`app/api/portfolio.py:361, 1089`, `analytics.py:794`). OHLCV has a sophisticated 3-tier cache; quotes have none.
  Quote: `async def fetch_quote(self, ticker: str) -> Optional[Dict[str, Any]]:`
  Fix: short-TTL (e.g. 15-60s) in-process quote memo keyed by canonical ticker, cleared by `clear_market_data_cache`.

- [P3] `data_service.py:986` — Row-by-row `df.iterrows()` dict construction for upsert (fine at ~2500 rows, but the slowest part of the store path).
  Quote: `for _, row in df.iterrows():`
  Fix: `records = df.to_dict("records")` + shared `ticker/source_used/fetched_on` stamping.

## What's clean (verified)

- DB concurrency gate (`_db_lock`, data_service.py:81, 108, 289, 345, 382, 801) correctly serializes all session use while keeping vendor calls parallel — regression-guarded by `tests/test_db_gate_concurrency.py`.
- Native SQLite upsert for timeseries (data_service.py:1006-1020) against the real `UniqueConstraint("ticker","date")` (models/database.py:62) — correct `on_conflict_do_update` shape; covered by `tests/test_coverage_data_service.py:375` and `tests/test_deep_cache.py:115`.
- Canonical ticker logic (data_service.py:40-65) — suffix-not-substring checks, `^`/`=X` passthrough, bare-scrip allowlist; tests `test_p07_ticker.py`, `test_contract_p1_batch.py:216`.
- Sortino (analytics_engine.py:861-864), EWMA RiskMetrics recursion (1058-1066), √t VaR/CVaR scaling (991-998), inverse-vol risk parity (625-647), diversification-score `N≤1 → 0` guard (225) all match CONTEXT gotchas #11/#17/#24 and are covered by `tests/test_quant_math_p1_batch.py` and `tests/test_logic_sweep_properties.py`.
- `risk_scoring` factor-leg exclusion + weight renormalization (analytics_engine.py:746-777) is correct and tested (`test_quant_math_p1_batch.py:249-259`).
- Benchmark price-vs-returns heuristic (analytics_engine.py:163) matches `BenchmarkService.get_returns`, which always returns pct-change series (benchmark_service.py:89) — heuristic takes the correct branch.
- Stale-tail/coverage heuristics (data_service.py:924-946) and L1 slice mirroring (169-203) are coherent; covered by `tests/test_deep_cache.py`.
- `clear_market_data_cache` (cache_service.py:211-284): one transaction, per-store counts, never touches `portfolio_positions`, resets all three in-process memo caches — matches the documented contract in CONTEXT §5.

## Recommended changes (ordered)

1. **Fix the factor-exposure placeholder/overwrite (analytics_engine.py:1170-1182)** — return N/A + flag on missing benchmark or portfolio-OLS failure; stop `except: pass` from clobbering valid per-position results. Add a test for `factor_exposure_analysis(..., benchmark_data=None)`.
2. **Fix `is_indian` in AV quote fallback (data_service.py:840)** — use `_is_indian_ticker`, and correct `tests/test_coverage_data_service.py:336` to pass the canonical ticker.
3. **Offload arch fits from the event loop (analytics_engine.py:982/1022)** — `asyncio.to_thread` for `model.fit`; this is the single biggest latency/throughput lever under concurrent dashboard load.
4. **Stop returning fabricated metrics on empty data (analytics_engine.py:1287/1303/1371/1391)** — nulls + error flag only; update `tests/test_analytics_engine.py:35`.
5. **Make the analytics-cache upsert race-safe (cache_service.py:74)** — `UNIQUE(ticker, metric_name)` + native `ON CONFLICT DO UPDATE`, mirroring `StockTimeseries`/`AppSetting`.
6. **Fix the partial-history perpetual-refetch (data_service.py:931-938)** — persist backfill coverage instead of a 1-hour wall-clock grace; fixes repeated 10y vendor downloads for IPOs/ETFs.
7. **Unblock sync yfinance calls (data_service.py:660, 687)** and **fix the cascade bypass on unnormalizable frames (data_service.py:377)** and **the exception-path ticker normalization (data_service.py:565)** — three small, independent data-service correctness fixes.
8. **Hygiene pass**: replace 9 bare `except:` with `except Exception`, delete the 4 dead helper methods, collapse the triple portfolio OLS into one, `func.count()` in `get_cache_stats`, scope the global `warnings.filterwarnings('ignore')`.

## Status updates (surgical-fixer, 2026-09-23)

All 33 findings verified against the working tree. 32 already-fixed, 0 refuted, 1 skipped (cross-area → HANDOFF). Evidence cites current line numbers.

### Bugs

- [P1] `analytics_engine.py:1170` — Status: already-fixed (verified: `:1104-1215` err_portfolio None+error; OLS-failure branch `:1193-1200` keeps `positions_exp`; missing-benchmark fill `:1202-1209` only fills absent tickers; test: `test_bugfix_core_services.py::TestFactorExposurePlaceholders` — both triggers)
- [P1] `data_service.py:840` — Status: already-fixed (verified: `:883` `q.setdefault("is_indian", self._is_indian_ticker(normalized_ticker))`; test: `test_coverage_data_service.py::test_fallback_quote_branches` passes canonical `"RELIANCE.NS"`)
- [P2] `analytics_engine.py:143`/`1115` — Status: already-fixed (verified: `:1127-1129` active mask = `s.dropna()` with comment keeping genuine 0% days; test: `test_quant_math_p1_batch.py`)
- [P2] `analytics_engine.py:62` — Status: already-fixed (verified: `:69-70` `weight_sum <= 0` → `_empty_metrics()`; test: `test_bugfix_core_services.py::TestFabricatedValueContracts::test_zero_weight_portfolio_error_flagged_nulls`)
- [P2] `analytics_engine.py:1303` — Status: already-fixed (verified: `:113`/`:126` `_empty_forecast(model=model.upper())`, `_empty_forecast` `:1242` echoes model; test: `test_bugfix_core_services.py::test_empty_forecast_echoes_requested_model`)
- [P2] `analytics_engine.py:1287`/`1371`/`1391` — Status: already-fixed (verified: `_empty_metrics` `:1226` annual_volatility/hit_ratio/kurtosis None; `_empty_stress_test` `:1299` max_drawdown/portfolio_impact/recovery_time None; `_empty_risk_score` `:1319` overall/risk_level/components None; tests updated: `test_analytics_engine.py:35` asserts None; new: `test_bugfix_core_services.py::TestFabricatedValueContracts`)
- [P2] `data_service.py:377` — Status: already-fixed (verified: `:397-401` empty-after-normalize → `continue` with comment; test: `test_bugfix_core_services.py::test_unnormalizable_frame_still_reaches_alpha_vantage` — 3 retries then AV)
- [P2] `data_service.py:932` — Status: already-fixed (verified: `_get_cached_data` `:978-999` accepts `deep_backfill:{ticker}` AppSetting marker ≥ earliest_cached; `_set_backfill_marker` `:1151`; test: `test_bugfix_core_services.py::test_partial_history_start_gap_served_after_backfill_marker` — vendor.await_count == 0)
- [P2] `data_service.py:565` — Status: already-fixed (verified: `:599` `return await self._fallback_quote(ticker, normalized_ticker)`; test: `test_coverage_data_service.py::test_fetch_quote_exception_fallback` now asserts `awaited_with("reliance", "RELIANCE.NS")`)
- [P2] `data_service.py:660`/`687` — Status: already-fixed (verified: `:694-698` `_yf_validate` in `asyncio.to_thread`, `:729` `_fetch_actions` in `asyncio.to_thread`; tests: `test_bugfix_core_services.py::TestOffEventLoopWork::test_validate_ticker_history_runs_off_event_loop` + `::test_corporate_actions_runs_off_event_loop` — sentinel ticks ≥ 10)
- [P2] `cache_service.py:74` — Status: already-fixed (verified: `models/database.py:85` `UniqueConstraint("ticker","metric_name")` + `cache_service.py:79-87` `on_conflict_do_update`; test: `test_p08_cache.py` single-row upsert + IntegrityError)

### Bugs P3

- [P3] `analytics_engine.py:479` — Status: already-fixed (verified: `:485` `if scenario_key and (k in scenario_key or scenario_key in k)`; test: `test_bugfix_core_services.py::test_empty_scenario_does_not_match_market_crash`)
- [P3] `analytics_engine.py:484` — Status: already-fixed (verified: `:490-492` signed-% regex `([+-]?\d+(?:\.\d+)?)\s*%` parsed, comment reworded; test: `test_bugfix_core_services.py::test_custom_scenario_parses_signed_percent` — impact in [-0.14,-0.08], not -0.20)

### Improvements

- [P2] `analytics_engine.py:11` — Status: already-fixed (verified: `:16-20` filter scoped `category=ConvergenceWarning` inside try/ImportError guard; runtime `warnings.filters` has no bare `(ignore,None,None)` entry; test: `test_bugfix_core_services.py::test_warning_filter_is_scoped_not_bare_ignore`)
- [P3] `analytics_engine.py:835`+ — Status: already-fixed (verified: `grep except:\s*$` → 0 matches in analytics_engine.py; all handlers are `except Exception` / `except Exception as e`)
- [P3] `analytics_engine.py:1233`+ (dead helpers) — Status: already-fixed (verified: `_calculate_max_drawdown`/`_simulate_stress_drawdown`/`_estimate_recovery_time`/`_calculate_liquidation_days` deleted — 0 matches in analytics_engine.py and tests/test_analytics_engine.py)
- [P3] `analytics_engine.py:1187`/`1210` — Status: already-fixed (verified: single portfolio OLS at `:1176`, `adjusted_r_squared` from `port_model.rsquared_adj` `:1182`; no second/third portfolio fit)
- [P3] `analytics_engine.py:830` — Status: already-fixed (verified: length-mismatch branch deleted; `:839-840` is the whole weight_vector path)
- [P3] `analytics_engine.py:317` — Status: already-fixed (verified: `:323` `category = "Low"` unconditional in tier 4)
- [P3] `analytics_engine.py:28` — Status: **skipped** (cross-area: fix requires adding `risk_free_rate` to `app/config.py` Settings — forbidden file for this agent; `analytics_engine.py:34` still `self.risk_free_rate = 0.02`) → see HANDOFF
- [P3] `data_service.py:1` — Status: already-fixed (verified: `:2-4` docstring describes user-selectable 3-tier cascade)
- [P3] `data_service.py:1140` — Status: already-fixed (verified: local `from sqlalchemy import func, select` inside `check_data_integrity` removed (module top `:13` only); `:1198` `ticker: Optional[str] = None`)
- [P3] `data_service.py:1027`/`1104` — Status: already-fixed (verified: `_log_storage_metrics` deleted — 0 matches; dead replacement-ratio warning gone with it)
- [P3] `data_service.py:543`/`734` — Status: already-fixed (verified: identity check `:573-576` `yf.Ticker is not DataService._YF_TICKER_REAL` (and download twin `:772`); no `unittest.mock` import in data_service.py). NOTE: `company_data_service.py:133/286` still uses the isinstance sniff — out of this report's file scope, see HANDOFF.

### Optimizations

- [P2] `analytics_engine.py:982`/`1022` — Status: already-fixed (verified: `:989` and `:1031` `await asyncio.to_thread(lambda: model.fit(...))`; test: `test_bugfix_core_services.py::test_garch_fit_runs_off_event_loop` — 300ms fit, sentinel ≥ 10 ticks)
- [P2] `cache_service.py:155` — Status: already-fixed (verified: `:149-181` all five stats via `select(func.count())...scalar()`; success rate from counts, no row materialization)
- [P3] `cache_service.py:135` — Status: already-fixed (verified: `:127-131` single `delete(AnalyticsCache).where(expires_at <= ...)`, returns `rowcount`)
- [P3] `data_service.py:347` — Status: already-fixed (verified: `:358-366` `l1_live` short-circuits `_get_full_cached_frame`)
- [P3] `data_service.py:931` — Status: already-fixed (same fix as Bugs P2 `data_service.py:932` — backfill marker stops the refetch/download cycle; test: same partial-history test)
- [P3] `analytics_engine.py:740` — Status: already-fixed (verified: `:748-749` `corr_values = returns.corr().values` computed once, indexed once)
- [P3] `data_service.py:767` — Status: already-fixed (verified: `:804-808` `ponytail:` comment documents the wait_for-cannot-cancel ceiling + upgrade path (cancellable pool + per-ticker single-flight))
- [P3] `data_service.py:422` — Status: already-fixed (verified: `_quote_memo` `:121-122` (30s TTL), read `:464-466`, write `:592`, cleared by `clear_market_data_cache` (`cache_service.py:261-262`); test: `test_bugfix_core_services.py::test_quote_memo_serves_repeat_within_ttl` — 2 calls, yf.Ticker call_count == 1)
- [P3] `data_service.py:986` — Status: already-fixed (verified: `:1046-1062` `df.to_dict("records")` + shared stamping; iterrows gone)

## HANDOFF

- **[P3] risk_free_rate config wiring (skipped above).** `AnalyticsEngine.__init__` still hardcodes `self.risk_free_rate = 0.02` (`analytics_engine.py:34`). The fix is `self.risk_free_rate = settings.risk_free_rate` after adding a `risk_free_rate: float = 0.02` field to `app/config.py` Settings — `app/config.py` is outside this agent's edit scope. Owner: foundation/config agent. Consumers already read the instance attr (`:863`, `:868`, `:871`), so the wiring is a two-line change once the setting exists.
- **[info] company_data_service mock sniff (out of scope).** `company_data_service.py:133`/`:286` still uses `isinstance(yf.Ticker, (unittest.mock.Mock, MagicMock))`; the identity-check pattern to copy is `data_service.py:573-576`. Owner: providers agent.
