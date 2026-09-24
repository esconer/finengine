# Backend audit: quant/risk services
Status: complete
Files: regime_service.py (343), volatility_service.py (327), tail_risk_service.py (325), optimization_service.py (316), monte_carlo_service.py (224), cointegration_service.py (400), correlation_service.py (168), backtest_service.py (173), indicators_service.py (228), benchmark_service.py (108)

Scope note: only these 10 files are in review scope; `app/api/analytics.py`, `app/api/data.py`, `app/models/schemas.py` and `backend/tests/*` were read only to verify contracts, reachability, and existing coverage.

## Bugs

### P1

- [P1] `cointegration_service.py:255` — pair cache key ignores `p_value_threshold` and `include_spread_series`, so a second request with different query params is served stale results (route passes both: `analytics.py:1984-1986`). Same omission in the DB key at `cointegration_service.py:36-39` (`sha1(f"{ticker_a}|{ticker_b}")` — no threshold), so staleness survives restarts for the whole day (key includes `last_date` only). A scan at p=0.05 then p=0.10 returns the first scan's `is_cointegrated`/`signal`; a scan with `include_spread_series=True` after `False` returns `spread_series=None` forever that day. — quoted: `cache_key = f"coint_{ticker_a}_{ticker_b}_{last_date}"` — fix: add `p_value_threshold` (and `include_spread_series`) to both cache keys, or bypass cache when threshold ≠ route default. Tests: `test_p03_coint.py` covers key collisions only; no test for param-keyed staleness.

- [P1] `cointegration_service.py:389-392` — `max_half_life` filters `cointegrated_pairs_count` but is never applied to the returned `pairs` list, so count ≠ `sum(p.is_cointegrated for p in pairs)`; pairs with `ou_half_life_days is None` (oscillatory OU, correctly `(None, None)` per CONTEXT gotcha 24) or > max are listed as cointegrated yet uncounted. Docstring at line 326 says "Optional maximum OU half-life filter"; comment at 388 says "filter cointegrated pairs or flag them" — neither happens. — quoted: `if p.is_cointegrated and (max_half_life is None or (p.ou_half_life_days is not None and p.ou_half_life_days <= max_half_life))` — fix: either filter `pairs` with the same predicate (and/or add a `half_life_filter_passed` flag per pair), or rename/document the count as "actionable pairs". Tests: none for `max_half_life`.

- [P1] `backtest_service.py:74-76` — an unknown `strategy` string makes `optimize()` raise `ValueError` on every rebalance, which this broad `except` swallows into "retain previous weights", so the whole backtest silently runs equal-weight while the payload is labeled with the bogus strategy (`"strategy": strategy` at line 158). Route does no validation either (`analytics.py:1716` `strategy = str(body.get("strategy", "hrp")).lower()`). — quoted: `logger.warning(f"Optimization failed on day {t_start} for {strategy}: {e}. Retaining previous weights.")` — fix: validate `strategy in STRATEGIES ∪ {"equal_weight"}` at function entry and raise; keep the per-window fallback only for solver failures. Tests: `test_advanced_analytics.py:138` asserts 400 for `/optimize/run` only; no backtest unknown-strategy test.

- [P1] `tail_risk_service.py:76-81` — when the 95% threshold yields <5 exceedances (any history of ~30–99 days, which the route explicitly allows: guard is `len(port_ret) < 30` at `analytics.py:2178`), the function fabricates GPD parameters and multiplies historical numbers by arbitrary factors, yet returns them under `gpd_shape_xi`, `gpd_scale_beta`, `evt_pot_var_99`, `evt_pot_es_99` with no fallback flag — the same fabrication class as the already-fixed P0-6 (n<20 now raises, `test_p06_evt.py`). `is_fat_tailed` is then always True (line 117 includes `var_evt_loss > hist_var_loss`, true by construction here since `var = hist*1.15`). Root cause: `EVTPOTVarMetrics.gpd_shape_xi/gpd_scale_beta` are non-optional floats (`schemas.py:405-406`), so the fallback invents values to satisfy the schema. — quoted: `xi = 0.15` / `var_evt_loss = hist_var_loss * 1.15` / `es_evt_loss = hist_es_loss * 1.20` — fix: make `gpd_shape_xi`/`gpd_scale_beta`/`gpd_scale_beta` `Optional[float]` + add `model_fitted: bool`, and return `xi=None` with honest historical-only VaR/ES (or raise like n<20). Tests: `test_p06_evt.py:22` (n=20) exercises this path but only asserts `es <= var`; no fabrication-flag test.

- [P1] `indicators_service.py:146` — fetch buffer `int(lookback_days * 1.6) + 120` conflates calendar and trading days, so at the default `lookback_days=90` (route `data.py:57`) only ~264 calendar ≈ 175 trading days are fetched (verified: 189 weekdays − ~14 NSE holidays ≈ 175) — fewer than the 200 rows `close_200_sma` needs, and `close_200_sma` is in `DEFAULT_INDICATORS` (line 50). Result: `close_200_sma` is structurally `null` for every default `/indicators/{ticker}` call and for any lookback ≲ 118 (route `ge=5`). Same root cause nulls it in `verified_snapshot` (lookback=5 → ~89 trading rows). — quoted: `start = end - timedelta(days=int(lookback_days * 1.6) + 120)` — fix: fetch `max(lookback_days, 300)` calendar days (≥210 trading) as warmup, or drop `close_200_sma` from defaults for short windows. Tests: no test requests `close_200_sma` (tests use `close_10_ema`/`close_13_ema`).

- [P1] `indicators_service.py:209` — `verified_snapshot` hardcodes `lookback_days=5` into `compute_window`, so `records` holds only the last 5 calendar days (~3–5 rows) and line 216 `records[-look_back_days:]` can never return the up-to-30 recent closes the route documents/accepts (`data.py:83` `look_back_days: int = Query(default=30, ge=5, le=30, ... "Recent closes to include")`). The `look_back_days` parameter is effectively dead. — quoted: `result = await self.compute_window(ticker, list(DEFAULT_INDICATORS), lookback_days=5, end_date=end)` — fix: pass `lookback_days=max(look_back_days, ...)` (plus SMA warmup) into `compute_window`. Tests: `test_data_services.py:109` asserts `len(out["recent_closes"]) <= 10` — a `<=` assertion that passes precisely because of this bug.

- [P1] `monte_carlo_service.py:69` — memory is `num_paths × round(horizon×252)` with no product cap: route/service allow `num_paths=20000` (`MAX_PATHS`, line 34) × `horizon_years=40` (line 177) → 201.6M doubles ≈ 1.6 GB for `shocks` alone; `log_increments`, `cumprod`/`cumsum` results and the final `hstack` push peak allocation toward ~5 GB → `MemoryError`/process crash from a single legitimate API call (same order for `student_t` line 95–101 and `bootstrap` line 121). — quoted: `shocks = rng.standard_normal((num_paths, steps))` — fix: cap `num_paths * steps` (e.g. ≤ 5e7 elements, scaling `num_paths` down) or chunk the simulation. Tests: none for the product bound.

### P2

- [P2] `backtest_service.py:45` — off-by-one: the final segment ends at `len(returns) - 1` exclusive (`test_chunk = returns.iloc[t_start:t_end]`, line 93), so the LAST day of the returns frame is never simulated — every backtest silently drops one OOS day. Only the final appended index is affected: if the schedule's last point is `< len-1` it appends `len-1`, not `len`. — quoted: `rebalance_indices.append(len(returns) - 1)` — fix: append `len(returns)` (only used as a slice bound; `rebalance_date` uses `t_start` only). Tests: `test_quant_math_p1_batch.py:139` **pins the bug** (`base = rets.iloc[60:199]` for a 200-row frame, excluding index 199) — update both.

- [P2] `backtest_service.py:43` — no validation of `lookback_days` / `rebalance_freq_days`; route forwards raw body ints with no `ge/le` (`analytics.py:1717-1718`). `rebalance_freq_days=0` → `range()` step-0 `ValueError` (maps to an opaque 400); negative `lookback_days` yields negative indices in `range(...)` → silently wrapped/sliced `iloc` garbage and plausible-looking wrong metrics. `lookback_days=5` (≥ the len-check at line 35 only when `len < lookback+freq`) optimizes on 5 rows. — quoted: `rebalance_indices = list(range(lookback_days, len(returns), rebalance_freq_days))` — fix: `if lookback_days < 20 or rebalance_freq_days < 1: raise ValueError(...)`.

- [P2] `tail_risk_service.py:72` — service never enforces `threshold_quantile < confidence_level`; the route allows the combo `confidence_level=0.90, threshold_quantile=0.98` (`analytics.py:2155-2156`). GPD is then fitted above the reported confidence level, and the clamp at line 105 (`var_evt_loss = max(var_evt_loss, threshold_u, ...)`) forces the "90% VaR" up to at least the 98%-loss quantile → systematically overstated VaR/ES. Related: output keys hardcode `evt_pot_var_99`/`historical_var_99` (lines 121-124) regardless of `confidence_level`. — quoted: `threshold_u = float(np.percentile(losses, threshold_quantile * 100.0))` — fix: `if threshold_quantile >= confidence_level: raise ValueError(...)`; consider parameterized key names. Tests: all EVT tests use 0.99/0.95 only.

- [P2] `tail_risk_service.py:106` — `es_evt_loss = max(es_evt_loss, var_evt_loss * 1.05)` fabricates a strict ≥5% VaR→ES gap; a legitimately thin tail (ES ≈ VaR) is inflated to satisfy a cosmetic monotonicity rule beyond the real `ES ≥ VaR` bound. — fix: `max(es_evt_loss, var_evt_loss)` (or fix ordering only when the analytic ES < VaR, which signals a fit problem worth logging).

- [P2] `optimization_service.py:220` vs `209`/`250` — Black-Litterman mixes return conventions: `pi = delta * (cov_ann @ w_mkt)` is the classic *excess*-return prior, user views are appended raw (`q_vals.append(float(ret))`, docstring example `{'INFY.NS': 0.15}` reads as an absolute expected return), and the final tangency does `excess = mu_bl - risk_free_rate`. If a view is absolute it is overweighted by ~rf in `Q - P @ pi` (line 244). Nothing documents that views must be excess returns. — quoted: `q_vals.append(float(ret))` — fix: document views as excess (or subtract `risk_free_rate` from absolute views on ingest). Tests: `test_coverage_engines.py:85-93` only asserts weights sum and sign — convention bug invisible to it.

- [P2] `volatility_service.py:292` — `calculate_volatility_cone(windows=[])` crashes: `windows[0]` (and, as a `next()` default, the eagerly-evaluated `window_results[0]` at line 294 — Python evaluates `next`'s default before the call) both `IndexError`. Unreachable from the current route (always default windows) but a latent crash in a public static API. — quoted: `target_w = 21 if 21 in realized_vols_by_window else windows[0]` — fix: `if not windows: windows = DEFAULT_CONE_WINDOWS` (merge with the `is None` check).

- [P2] `cointegration_service.py:24` — `_IN_MEMORY_COINT_CACHE` is only TTL-checked on hit (lines 258-264) and never evicted: every new `as_of` date × every pair inserts a new key that lives forever, growing unbounded across days (DB cache below it is durable; this dict is pure RAM). Contrast `benchmark_service.py:105-107`, which does bound its registry. — quoted: `_IN_MEMORY_COINT_CACHE: Dict[str, Tuple[datetime, Dict[str, Any]]] = {}` — fix: purge expired keys on write, or cap size (LRU), same pattern as the benchmark registry.

- [P2] `monte_carlo_service.py:159` / `backtest_service.py:18` / `tail_risk_service.py:228` / `cointegration_service.py:368` / `volatility_service.py:151` — CPU-bound work runs synchronously inside async route handlers with no `asyncio.to_thread`, blocking the event loop: `simulate_goal` (up to seconds at 20k paths), `run_walk_forward_backtest` (an `optimize()` CLARABEL solve per rebalance), the O(n²) copula matrix (the code's own comment at `analytics.py:2143` says ~12 s for 14 assets — first `/tails` call stalls **all** requests that long; only then does the 900 s memo help), `scan_pairs`' per-pair `coint`+Johansen inside `async def` (line 368), and the GARCH fit on `/vol-cone`. `regime_service.py:310` shows the correct pattern: `await asyncio.to_thread(partial(classify, ...))`. — quoted (worst offender): `for i in range(n): for j in range(i + 1, n): ... cls.calculate_bivariate_tail_dependence(...)` — fix: wrap the heavy call sites in `asyncio.to_thread` exactly as `detect_regime` does.

- [P2] `correlation_service.py:98` vs `100` — `is_regime_break = current > threshold_90th` (strict) but `alert_level = "CRITICAL"` fires on `>=`, and the message claims the value "exceeds" the threshold. On a flat series (`current == p90` exactly) the payload simultaneously says CRITICAL and `is_regime_break: false`. — quoted: `is_regime_break = bool(current_avg_corr > threshold_90th)` — fix: use `>=` in both (or `>` in both) and adjust the wording.

- [P2] `benchmark_service.py:82` — `get_returns(start=..., end=...)` ignores `start` for the fetch window: it always fetches `ensure_history(days=days)` with `days` defaulting to 756, then filters. Any caller passing `start` older than 756 days without also passing `days` gets a silently truncated benchmark. Current callers happen to be safe (`lookback le=756` at `analytics.py:593`; risk-score uses 252; two call sites pass `days` explicitly), so this is a footgun, not yet a live defect. — quoted: `df = await self.ensure_history(days=days)` — fix: derive fetch `days` from `start` when provided.

### P3

- [P3] `regime_service.py:106`/`182-197` — `n_components` is a public parameter but the sticky `transmat_` (3×3) and `startprob_` (length 3) are hardcoded; any value ≠ 3 fails in hmmlearn at fit time (verified: setters accept the wrong shape, fit rejects it). `_label_states_by_risk` (line 45) defensively handles non-3 fits it can never receive. — quoted: `hmm.startprob_ = np.array([0.33, 0.34, 0.33])` — fix: build `sticky_trans`/`startprob` from `n_components` or delete the parameter (only caller passes 3).

- [P3] `regime_service.py:149-150` — Parkinson variance is annualized per observation then *averaged as a vol* (`rolling(10).mean()` of annualized σ) instead of pooling `mean(logHL²)` over the window and taking one sqrt — Jensen bias, and the rolling window spans 10 *valid* rows even across gaps. Diagnostic overlay only. — quoted: `parkinson_vol = float(parkinson_daily.rolling(10, min_periods=3).mean().iloc[-1])` — fix: `np.sqrt((log_hl**2).rolling(10, min_periods=3).mean() / (4*np.log(2))) * np.sqrt(252)`.

- [P3] `regime_service.py:4` vs `47-50` — docstring says states are "ordered by risk (return/vol profile)" but `_label_states_by_risk` sorts by `cagr`/`ann_ret` only; `ann_vol` never enters the ordering (a high-vol/high-return state is labeled "bull"). — fix: correct the docstring (or include vol in the score).

- [P3] `volatility_service.py:95` — empty input returns fabricated `0.20` presented as an EWMA forecast (contract is pinned by `test_coverage_quant_services.py:86`, and the route guards `len < 30`, so unreachable in prod) — inconsistent with the repo's no-fabrication policy. — quoted: `return 0.20` — fix: return `None` + flag and update the test, or keep and document why vol cone is exempt.

- [P3] `volatility_service.py:268` — dead code: `sorted([min_v, p25_v, med_v, p75_v, max_v])` is a no-op; min/percentiles of the same array are monotone by construction. — quoted: `min_v, p25_v, med_v, p75_v, max_v = sorted([min_v, p25_v, med_v, p75_v, max_v])` — fix: delete (keep the comment).

- [P3] `volatility_service.py:272-278` — returns `None` for `min`/`p25`/… on insufficient data (correct, tested), but `VolConeWindow` schema declares them non-optional `float` (`schemas.py:370`); the route has no `response_model` so it doesn't crash today — contract drift waiting for someone to add validation. — fix: mark those fields `Optional[float]`.

- [P3] `tail_risk_service.py:79` vs `111` — the two fabrication fallbacks define `beta` inconsistently (`std(losses)*0.5` vs `std(exceedances)`) — moot once the P1 fabrication is removed; otherwise unify.

- [P3] `tail_risk_service.py:158` — a pair with <10 overlapping observations returns `(0.0, 0.0, 4.0)` as if computed ("no tail dependence, df=4") with no insufficient-data flag. Largely unreachable via `/tails` (route guarantees ≥30 aligned rows), but it is a fabricated triple in a public method. — quoted: `return 0.0, 0.0, 4.0` — fix: raise/return `None`s + flag.

- [P3] `tail_risk_service.py:260-261` — when no pair reaches λ ≥ 0.20 the "high tail risk pairs" list is backfilled with the top 5 (possibly all `LOW` category), so the section is never honest about "none found". `risk_category` at least stays truthful. — quoted: `high_risk_pairs = pairs_list[:min(5, len(pairs_list))]` — fix: return `[]` and let the UI show an empty state, or rename the field to `top_pairs`.

- [P3] `tail_risk_service.py:170-174` — docstring says "Student-t MLE fit on standardized marginals" but the fit runs on raw returns (standardization is absorbed by `scale_`, so df is unaffected) and ν is a *marginal* fit used as the *copula* dependence df; ρ is Pearson rather than a rank-based copula estimate. A reasonable approximation, but the docstring overstates the method. — fix: reword, or estimate ν/ρ jointly once per matrix (see Optimizations).

- [P3] `monte_carlo_service.py:137` — `_fan_from_paths(paths, horizon_years, ...)` never reads `horizon_years` (checkpoints derive from `paths.shape[1]`); also annotated `int` while callers pass `float` (2.5 works only because it's unused). — quoted: `def _fan_from_paths(paths: np.ndarray, horizon_years: int, checkpoints_per_year: int = 2)` — fix: drop the parameter.

- [P3] `optimization_service.py:292` + `305` — `_as_matrices(returns)` runs twice per non-HRP `optimize()` call (mu/cov of the full frame recomputed purely for diagnostics). — quoted: `mu, cov, _ = _as_matrices(returns)` — fix: reuse the earlier `mu, cov` (hoist before the strategy branch).

- [P3] `optimization_service.py:142`/`159`/`180` — a hard `cvxpy` `SolverError` propagates as-is (not `ValueError`), so `/optimize/run` maps it to 500 instead of 400 (`analytics.py:1700-1702`). Backtest catches it. — fix: `except cp.error.SolverError as e: raise ValueError(...)`.

- [P3] `cointegration_service.py:260`/`278`/`297`/`307` — `datetime.utcnow()` is deprecated in Python 3.12 (repo targets 3.12) and returns naive datetimes; `regime_service.py:341` already uses `datetime.now(timezone.utc)`. — quoted: `if datetime.utcnow() - ts < timedelta(hours=CACHE_TTL_HOURS):` — fix: `datetime.now(timezone.utc)`.

- [P3] `cointegration_service.py:255` + `293` — the in-memory key string is built by hand in two places (and diverged once already from `_db_cache_keys`); extract `_mem_cache_key(...)`. Related duplication: `benchmark_service.py:97-108` `get_benchmark_service` registry is dead in the app — `analytics.py:62` defines its own DI that constructs `BenchmarkService(db)` directly; only tests import the registry (which also pins up to 64 live sessions via strong refs). — fix: delete the registry or use it in the route DI.

- [P3] `benchmark_service.py:68` — `out.dropna(subset=["close"] if "close" in out.columns else [])`: with TitleCase columns the `subset=[]` branch is a verified no-op (`dropna(subset=[])` drops 0 rows), and only `"close"` is recognized while `_close_series` (line 26-28) knows four variants. Harmless today (DataService normalizes to lowercase; downstream `pct_change().dropna()` cleans), but the guard is illusory. — quoted: `return out.dropna(subset=["close"] if "close" in out.columns else [])` — fix: reuse `_close_series`'s column tuple (or drop the row-drop entirely and rely on `_close_series`).

- [P3] `indicators_service.py:75-78` — `_ensure_date_column` renames only exact candidates `("date", "index", "Datetime")`; a frame whose index is named e.g. `timestamp` falls through, and `_clean_dataframe`'s `data["Date"]` then `KeyError`s → 500. Unverified whether DataService can produce such an index; cheap to harden (`else: out.rename_axis("Date")` or take `out.columns[0]` when it parses as dates).

- [P3] `correlation_service.py:151-168` — `CorrelationService` is a pure pass-through wrapper over the module functions (used only by tests); fine to keep for the tests, but it is duplication surface.

## Improvements

- Error handling: `tail_risk_service.calculate_evt_pot_var_es` mixes three strategies — hard raise (n<20), fabricated GPD (n_u<5), clamped fit — with no machine-readable indicator of which path ran; adding `model_fitted: bool` + `Optional` params would make the contract honest (root-cause note for the P1 above; forced today by non-optional `EVTPOTVarMetrics` fields, `schemas.py:405-406`).
- Error handling: `backtest_service` should distinguish *invalid input* (unknown strategy, bad windows — fail fast) from *per-window solver failure* (fallback is correct); one `except Exception` currently conflates them (`backtest_service.py:74`).
- Error handling: `optimization_service` should convert `cp.error.SolverError` to `ValueError` at the three `prob.solve` sites so API mapping stays 400 not 500.
- Typing/contracts: `volatility_service` insufficient-data `None`s vs non-optional `VolConeWindow` floats; `tail_risk` `evt_pot_var_99` keys named for 99% while `confidence_level` is free 0.90–0.999.
- Naming: `backtest_service.py:51` `current_weights` vs `bench_weights` are both mutable but `bench_weights` never changes — rename to `bench_bh_weights` to make buy-and-hold explicit.
- Dead code: `_fan_from_paths.horizon_years`, vol-cone `sorted(...)` no-op, `benchmark_service._service_registry` (unused by app), `_label_states_by_risk`'s non-3 branch (unreachable while `n_components` is effectively fixed at 3).
- Duplication: `_as_matrices` called twice in `optimize`; in-memory cache-key string built twice in `CointegrationService`; two inconsistent fabrication-fallback formulas in `tail_risk_service`.
- Deprecated stdlib: `datetime.utcnow()` (4 call sites in `cointegration_service.py`).
- Doc/impl drift: regime "risk (return/vol profile)" ordering; BL view convention (excess vs absolute); tail copula "standardized marginals"; coint `max_half_life` "filter" that only filters the count.
- Tests to add (currently absent, per grep of `backend/tests/`): coint cache keyed by threshold/spread flag; `max_half_life` count-vs-list invariant; backtest unknown strategy raises + final-day inclusion; `close_200_sma` non-null at default lookback; `verified_snapshot` honors `look_back_days`; EVT n_u<5 honesty flag; `threshold_quantile < confidence_level` guard; `num_paths × steps` cap.

## Optimizations

- [P2] `tail_risk_service.py:172-174` — `stats.t.fit(r_a)` is recomputed for every pair inside the O(n²) loop (`calculate_tail_dependence_matrix`, line 232), but `df_a` depends only on ticker `i`: hoist to a per-column cache (n fits instead of n(n−1) fits; each scipy t-fit is tens–hundreds of ms — this alone explains the "~12s for 14 assets" comment at `analytics.py:2143`). Identical output, ~O(n) instead of O(n²) fits. Also consider replacing `np.corrcoef` per pair with one vectorized correlation pass.
- [P2] `cointegration_service.py:363`/`378` — serial `await` of a DB read + DB write per pair inside the loop (n(n−1)/2 round-trips); batch the reads before the loop and the writes after (respecting the single-`AsyncSession` gate of CONTEXT gotcha 21 — serialize through one lock or one gathered writer).
- [P2] Event-loop blocking: see Bugs/P2 "CPU-bound work in async routes" — wrap `simulate_goal`, `run_walk_forward_backtest`, `calculate_tail_dependence_matrix`, `scan_pairs`' inner analysis, and the GARCH/cone computation in `asyncio.to_thread`; follow `regime_service.py:310`.
- [P2] `monte_carlo_service.py:69`/`95`/`121` — cap or chunk `num_paths × steps` (also the P1 crash fix): at minimum derive an effective `num_paths = min(num_paths, budget // steps)`.
- [P3] `optimization_service.py:305` — reuse the `mu, cov` already computed at line 292 instead of a second `_as_matrices` pass over the full frame.
- [P3] `correlation_service.py:54-58` — O(N²) `rolling().corr()` calls; fine at personal-portfolio scale, but all pairwise rolling corrs can be computed from a single expanding panel if N ever grows (do not do this preemptively — YAGNI).
- [P3] `backtest_service.py:94` — `test_chunk.iterrows()` row-at-a-time; `test_chunk.to_numpy() @ current_weights` vectorizes the whole chunk in one shot (P&L math unchanged, keeps the day-0 cost branch).

## Recommended changes (ordered)

1. **Coint cache correctness (P1)** — include `p_value_threshold` + `include_spread_series` in `_mem`/`_db_cache_keys` (`cointegration_service.py:36-39, 255, 293`); add a regression test that two thresholds produce two entries.
2. **Coint count/list contract (P1)** — apply the `max_half_life` predicate to `pairs` (or add a per-pair flag and document the count as "actionable"); test `count == [p for p in pairs if <predicate>]`.
3. **Backtest honesty (P1)** — validate `strategy` upfront against `STRATEGIES ∪ {"equal_weight"}`; fix the final-day off-by-one (`append(len(returns))`) and update the pinning assertion `test_quant_math_p1_batch.py:139`; validate `lookback_days ≥ 20`, `rebalance_freq_days ≥ 1`.
4. **EVT fabrication (P1)** — make `gpd_shape_xi`/`gpd_scale_beta` Optional + `model_fitted` flag; return honest historical VaR/ES when `n_u < 5` (or raise, consistent with n<20); add `threshold_quantile < confidence_level` guard.
5. **Indicators warmup (P1)** — fix `_resolve_dates` to fetch ≥ ~300 calendar days of warmup regardless of lookback; pass real `look_back_days` through `verified_snapshot`; add tests asserting `close_200_sma is not None` at default lookback and `len(recent_closes) == look_back_days` when history exists.
6. **Monte Carlo memory + async (P1/P2)** — cap `num_paths × steps`; run `simulate_goal`/backtest/copula/scan/GARCH off the event loop via `asyncio.to_thread` (mirror `regime_service.py:310`).
7. **Copula speed (P2)** — fit marginal t dfs once per ticker; this removes most of the `/tails` 12s first-call stall without changing numbers.
8. **Small cleanups (P2/P3)** — coint in-memory cache eviction; correlation `>`/`>=` consistency; BL view-convention doc; delete dead params/branches (`horizon_years`, vol-cone `sorted`, `_service_registry`); `utcnow` → `now(timezone.utc)`; `SolverError` → `ValueError`.

### Verified clean (no findings)

- **HRP** (`optimization_service.py:46-132`): correct Lopez de Prado recursive bisection on inverse-variance cluster variance, single-linkage quasi-diagonalization, zero-variance guards; covered by `test_p01_hrp.py` (incl. N=3 bisection and flat-series).
- **Min-CVaR** (`optimization_service.py:168-183`): Rockafellar–Uryasev LP with free `alpha` — matches CONTEXT gotcha 24; source-pinned by `test_quant_math_p1_batch.py:74-79`.
- **Max-Sharpe homogenization** (`optimization_service.py:148-165`) and **Black-Litterman posterior** (`244-245`, Woodbury form `(1+τ)Σ − τ²ΣP'(PτΣP' + Ω)⁻¹PΣ`): algebra verified correct.
- **OU estimator** (`cointegration_service.py:42-98`): `θ = −ln(1+γ)`, half-life `ln2/θ`, oscillatory `-2 < γ ≤ -1 → (None, None)`, zero-variance guard — matches gotcha 24; recovery + explosive tests in `test_quantitative_invariants.py:150-175`.
- **EVT formulas on the fitted path** (`tail_risk_service.py:95-102`): POT VaR `u + (β/ξ)((n/n_u·α)^{-ξ} − 1)` and ES `(VaR + β − ξu)/(1 − ξ)` are correct; `ES ≤ VaR` invariant tested (`test_quantitative_invariants.py:177-190`).
- **Student-t copula λ_L formula** (`tail_risk_service.py:184-185`): `2·t_{ν+1}(−√((ν+1)(1−ρ)/(1+ρ)))` is correct given (ρ, ν).
- **GARCH rescaling** (`volatility_service.py:150-160`): ×100 fit / ÷100 on √(var·252) verified algebraically; EWMA weights are the closed-form RiskMetrics recursion.
- **Backtest mechanics other than the final-day off-by-one**: no look-ahead (train window ends at `t_start-1`, weights applied from `t_start`), one-way turnover `0.5·Σ|Δw|`, multiplicative day-0 cost, mean-based Sharpe with `ddof=1` — all match gotcha 24 and are pinned by `TestBacktestOneWayTurnover`.
- **Monte Carlo math**: GBM drift `(μ − σ²/2)dt` off the arithmetic mean, Student-t analytic-moment standardization + winsorization (±8z, −95% floor), stationary-bootstrap chaining, quantile fan monotonicity — all covered by `test_monte_carlo_service.py` / invariants.
- **Regime engine**: `classify` runs in `asyncio.to_thread`; crash veto is display-only with tests (`test_regime_crash_veto.py`); return-vs-price routing heuristic tested (`test_p02_regime.py`); tz-naive portfolio intersection handled (`test_regime_service.py:67`).
- **AGENTS.md invariants in scope**: no HHI/diversification, inverse-vol risk-parity, or monthly-compounding code lives in these 10 files (those are `analytics_engine`/frontend) — no violations found here; single-holding paths are guarded at the route layer (correlation single-holding special case, backtest `len(assets)==1`, optimize single-holding shortcut).

## Fix-pass status (Surgical Fixer — Quant, 2026-09-22)

Totals across all 52 findings: **fixed 49 · refuted 0 · skipped 2 · handoff-only 1**.
Regression tests: `backend/tests/test_bugfix_quant_services.py` (21 new tests, one per nontrivial fix) + pin updates in `test_quant_math_p1_batch.py` / `test_data_services.py` / `test_coverage_quant_services.py`.

### Bugs

- [P1] coint cache key ignores query params — **Status: fixed** (`_mem_cache_key`/`_db_cache_keys` include `p_value_threshold` + `include_spread_series`; test: `test_coint_cache_keys_include_query_params` — two thresholds → two DB rows, stale-threshold read returns None).
- [P1] `max_half_life` filters count but not pairs list — **Status: fixed** (same predicate now filters `pairs`; test: `test_max_half_life_filters_pairs_matching_count` — `count == len(listed cointegrated)` with hl=None and hl>max excluded, non-cointegrated retained).
- [P1] backtest unknown strategy swallowed into equal-weight — **Status: fixed** (entry validation raises; test: `test_backtest_unknown_strategy_raises_before_running`; `equal_weight` alias still accepted).
- [P1] EVT n_u<5 fabricates xi/beta and inflates VaR/ES — **Status: fixed** (`model_fitted=False`, xi/beta=None, historical-only numbers, `is_fat_tailed` from kurtosis only; schemas Optional + `model_fitted`; test: `test_evt_insufficient_exceedances_reports_unfitted`).
- [P1] indicators warmup cannot cover `close_200_sma` — **Status: fixed** (`_resolve_dates` floor 365 calendar days; test: `test_indicator_warmup_yields_200sma_at_default_lookback` — fetch span ≥300d AND SMA non-null at default lookback).
- [P1] `verified_snapshot` hardcodes lookback=5 — **Status: fixed** (`lookback_days=max(look_back_days*2, 60)` into `compute_window`; pin updated: `test_data_services.py:111` `len(...) == 10`).
- [P1] MC `num_paths × steps` unbounded — **Status: fixed** (`MAX_PATH_ELEMENTS=50_000_000`, `num_paths = max(100, min(...))`; test: `test_mc_caps_paths_by_element_budget` — 40y×20000 caps to budget, small requests pass through).
- [P2] backtest final-day off-by-one — **Status: fixed** (`append(len(returns))`; pin updated: `test_quant_math_p1_batch.py` `base = rets.iloc[60:200]`).
- [P2] backtest no window validation — **Status: fixed** (`lookback_days >= 20`, `rebalance_freq_days >= 1`; test: `test_backtest_rejects_bad_windows`).
- [P2] EVT `threshold_quantile >= confidence_level` allowed — **Status: fixed** (raises at entry; test: `test_evt_rejects_threshold_at_or_above_confidence`; valid combo unchanged).
- [P2] EVT `* 1.05` cosmetic ES gap — **Status: fixed** (`max(es_evt_loss, var_evt_loss)`; source-pinned test: `test_evt_es_clamp_has_no_cosmetic_five_pct_gap`).
- [P2] BL view excess/absolute convention undocumented — **Status: fixed** (docstring now states excess-return convention with absolute-view conversion example; doc-only, no behavior change → no test).
- [P2] vol-cone `windows=[]` IndexError — **Status: fixed** (`if not windows: windows = DEFAULT_CONE_WINDOWS`; test: `test_vol_cone_empty_windows_falls_back_to_defaults`).
- [P2] coint mem-cache never evicted — **Status: fixed** (expired keys purged on every write; test: `test_mem_cache_purges_expired_entries_on_write`).
- [P2] CPU-bound work blocks event loop — **Status: fixed (service layer) + HANDOFF (API layer)**: `scan_pairs` inner analysis wrapped in `asyncio.to_thread` at `cointegration_service.py:423`; remaining sync call sites live in out-of-scope `app/api/analytics.py` — see HANDOFF 1.
- [P2] correlation `>` vs `>=` flag/alert disagreement — **Status: fixed** (single `>=` comparison for both; test: `test_correlation_flat_series_flag_agrees_with_alert` — flat series → flag True + CRITICAL agree; fixture patches rolling series for bit-exact equality).
- [P2] benchmark `start` ignored for fetch window — **Status: fixed** (`ensure_history(days=max(days, span_days))`; test: `test_benchmark_get_returns_derives_fetch_span_from_start` — start=1000d ago fetches ≥1000d).
- [P3] regime `n_components` ≠ 3 fails deep in hmmlearn — **Status: fixed** (fail-fast `ValueError` at entry; test: `test_regime_n_components_rejects_non_three`).
- [P3] Parkinson annualize-then-average (Jensen bias) — **Status: fixed** (pooled `sqrt(mean(logHL²)/(4ln2))·√252`; test: `test_parkinson_vol_pools_before_annualizing` — matches pooled formula, differs from old mean-of-sqrt by >1e-3).
- [P3] regime docstring claims vol enters ordering — **Status: fixed** (docstring states CAGR-only ordering; doc-only → no test).
- [P3] EWMA empty returns fabricated 0.20 — **Status: fixed** (raises `ValueError`; pin updated: `test_coverage_quant_services.py:87` `pytest.raises(..., match="empty")`).
- [P3] vol-cone `sorted(...)` no-op — **Status: fixed** (deleted, comment retained; trivial → no test).
- [P3] `VolConeWindow` non-optional floats vs None payload — **Status: fixed (quantiles) + HANDOFF (residual)**: min/p25/median/p75/max/percentile_rank now `Optional[float]`; `current_realized` and `VolForecastOverlay.percentile_rank` still non-Optional while service can return None — see HANDOFF 4.
- [P3] tail fallback beta formulas inconsistent — **Status: fixed** (moot: both fabrication fallbacks removed with the P1).
- [P3] copula <10 overlap returns fabricated `(0,0,4)` — **Status: fixed** (raises; test: `test_tail_dependence_raises_on_short_overlap`).
- [P3] `high_tail_risk_pairs` backfilled when none qualify — **Status: fixed** (list comprehension on λ≥0.20 only; test: `test_high_tail_risk_pairs_stays_empty_when_none_qualify` — anti-correlated pair → `[]`).
- [P3] copula docstring overstates method — **Status: fixed** (rewritten: univariate t MLE per raw series, averaged, Pearson ρ, explicitly an approximation; doc-only → no test).
- [P3] `_fan_from_paths` dead `horizon_years` param — **Status: fixed** (param dropped; call site `_fan_from_paths(paths)`).
- [P3] `_as_matrices` runs twice per optimize — **Status: fixed** (single call reused; test: `test_optimize_computes_moments_once` — spy count == 1 for min_vol).
- [P3] `SolverError` propagates as 500 — **Status: fixed** (`_solve` wrapper maps to `ValueError` at all 3 sites; test: `test_solver_error_becomes_value_error`).
- [P3] `datetime.utcnow()` deprecated — **Status: fixed** (`_utcnow()` = `now(timezone.utc)` naive; test: `test_cache_timestamps_use_non_deprecated_utc` — DeprecationWarning-as-error roundtrip).
- [P3] mem cache-key string built twice + dead benchmark registry — **Status: fixed** (`_mem_cache_key` extracted; `_service_registry` deleted — only tests imported it; trivial → no dedicated test).
- [P3] benchmark `dropna(subset=...)` illusory guard — **Status: fixed** (reuses `_close_series` column tuple → `close_col`; trivial → no test).
- [P3] `_ensure_date_column` unknown index name KeyError — **Status: fixed** (fallback renames first column after reset_index; test: `test_clean_dataframe_tolerates_unknown_index_name` — index named "timestamp" → "Date" present).
- [P3] `CorrelationService` pass-through wrapper — **Status: fixed** (class deleted; module functions remain for tests).

### Improvements

- EVT `model_fitted` + Optional params — **Status: fixed** (see P1 EVT).
- backtest fail-fast vs per-window solver fallback distinction — **Status: fixed** (entry validation; fallback retained only for solver failures).
- `SolverError` → `ValueError` at 3 `prob.solve` sites — **Status: fixed** (via `_solve`).
- Typing/contracts: `VolConeWindow` Optionals + `evt_pot_var_99` key naming — **Status: handoff-only** (quantiles/xi already Optional; residual `current_realized`/overlay `percentile_rank` Optionals and confidence-parameterized EVT keys need `app/models/schemas.py` — see HANDOFF 2 and 4).
- `bench_weights` → `bench_bh_weights` rename — **Status: fixed** (`backtest_service.py:67`).
- Dead code (`_fan_from_paths.horizon_years`, vol-cone `sorted`, `_service_registry`) — **Status: fixed**; `_label_states_by_risk` non-3 branch kept intentionally (returns `state_N` labels instead of IndexError).
- Duplication (double `_as_matrices`, double cache-key string, two fallback betas) — **Status: fixed** (all three).
- `datetime.utcnow()` in cointegration (4 sites) — **Status: fixed** (all route through `_utcnow()`; utcnow elsewhere is out of scope).
- Doc/impl drift (regime ordering, BL views, copula method, `max_half_life` "filter") — **Status: fixed** (all four docstrings corrected).
- Tests to add (8 listed gaps) — **Status: fixed** (`test_bugfix_quant_services.py` covers all 8 + extras).

### Optimizations

- [P2] O(n²) `stats.t.fit` inside copula loop — **Status: fixed** (`marginal_dfs` fit once per ticker, passed as `marginal_df_a/b`; O(n) fits).
- [P2] serial per-pair DB reads/writes in `scan_pairs` — **Status: skipped + HANDOFF**: requires a bulk get/set API on out-of-scope `cache_service.py` and must respect the single-`AsyncSession` gate — see HANDOFF 3.
- [P2] event-loop offload (`simulate_goal`/backtest/copula/GARCH) — **Status: fixed (scan_pairs) + HANDOFF (API call sites)** — see HANDOFF 1.
- [P2] MC `num_paths × steps` cap — **Status: fixed** (same change as P1 MC crash; test above).
- [P3] reuse `mu, cov` from first `_as_matrices` — **Status: fixed** (test above).
- [P3] O(N²) rolling `.corr()` — **Status: skipped**: report itself says YAGNI at personal-portfolio scale; revisit only if N grows.
- [P3] backtest `iterrows` → vectorized chunk — **Status: fixed** (`test_chunk.to_numpy() @ weights`; day-0 friction branch kept; pin `TestBacktestOneWayTurnover` green).

### HANDOFFS (cross-area, not editable by this fixer)

1. **API layer `asyncio.to_thread` wraps** — `app/api/analytics.py` calls these sync CPU-bound functions directly inside async handlers: `:1768` `run_walk_forward_backtest` (CLARABEL solve per rebalance), `:1890` `simulate_goal` (up to ~seconds at 20k paths), `:2174` `VolatilityService.calculate_volatility_cone` (GARCH fit), `:2232` `TailRiskService.calculate_evt_pot_var_es`, `:2235` `TailRiskService.calculate_tail_dependence_matrix` (~12 s first call for 14 assets — stalls all requests). Wrap each in `asyncio.to_thread` following `regime_service.py:320`. The in-scope service-side piece (`scan_pairs` inner) is already done.
2. **EVT key naming** — `EVTPOTVarMetrics` (`app/models/schemas.py:405-415`) hardcodes `evt_pot_var_99`/`evt_pot_es_99`/`historical_var_99`/`historical_es_99` while `confidence_level` is free 0.90–0.999; parameterize keys (or add confidence-suffixed aliases) + update consumers.
3. **CacheService bulk API** — add multi-key `get_cached_analytics_many`/`set_cached_analytics_many` (single round-trip each) so `CointegrationService.scan_pairs` can batch the per-pair DB read/write instead of n(n−1)/2 serial awaits; serialize writes through one lock per the single-`AsyncSession` gate (CONTEXT gotcha 21).
4. **Residual Optional schema gaps** — `VolConeWindow.current_realized: float` (`schemas.py:383`) and `VolForecastOverlay.percentile_rank: float` (`schemas.py:392`) accept None from the service (vol-cone short-window path returns `curr_v=None`; overlay rank can be None) but are declared non-Optional. Route has no `response_model` so it does not crash today — contract drift waiting for validation. Mark both `Optional[float] = None`.
