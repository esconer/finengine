# Verified audit: 03-core-services
Counts: 33 findings — confirmed: 33, refuted: 0, already-fixed: 0
Scope: backend/app/services/analytics_engine.py, data_service.py, cache_service.py (re-read in full/parts; cited tests + callers re-checked). No finding was refuted or already fixed; all cited line numbers still match HEAD.

## Bugs

### P1

- P1 / factor-exposure-placeholder-overwrite | P1 | confirmed | Line 1170-1178 loop overwrites `positions_exp` with `{alpha:0, market:1}` whenever the real-regression block is skipped (guards 1098/1100 false) or portfolio OLS fails and `except Exception: pass` at 1167-1168 falls through; placeholders self-contradictory (`data_points:0`, `is_limited_history:False`). Reachable: `app/api/analytics.py:652-663` sets `benchmark_returns=None` on exception and calls engine unguarded; engine 160-161 turns None into empty Series. Tests: `test_quant_math_p1_batch.py:249` covers risk_scoring exclusion only; `test_analytics_engine.py:140` always passes a benchmark. | analytics_engine.py:1170 | analytics_engine.py:1167-1182 (+ optional guard in app/api/analytics.py:658) | `factor_exposure_analysis(prices, benchmark_data=None)` must not return `market:1.0` unflagged; assert positions carry `market is None` or an error flag.

- P1 / is-indian-bse-suffix-canonical | P1 | confirmed | Line 840 `q.setdefault("is_indian", ".BSE" in normalized_ticker.upper())` tests a suffix canonical tickers never have (`canonical_ticker` 40-65 emits `.NS`/`.BO`/bare; `.BSE` only exists inside `to_av_symbol`). Callers 561/565 pass canonical/uppercase forms, so `.NS` → False. AV `fetch_global_quote` (alpha_vantage_service.py:309-326) returns no `is_indian` key, so setdefault always fires. Test masks it: `test_coverage_data_service.py:336` passes non-canonical `"RELIANCE.BSE"`. | data_service.py:840 | data_service.py:840, tests/test_coverage_data_service.py:336 | `_fallback_quote("RELIANCE.NS", "RELIANCE.NS")` must yield `is_indian is True` (use `_is_indian_ticker`).

### P2

- P2 / beta-drops-genuine-zero-days | P2 | confirmed | Line 143 `fillna(0.0)` converts missing days to 0 before line 1115 `s[s != 0.0]` builds the active mask, so true 0% days are indistinguishable from pre-listing fills and get excluded, biasing beta. | analytics_engine.py:143, 1115 | analytics_engine.py:143 (carry raw-NaN mask into regression path) | Construct a series with one genuine 0-return day while benchmark moves; beta must include that day (active count +1).

- P2 / weight-sum-zero-silent-skip | P2 | confirmed | Lines 62-64 only normalize `if weight_sum > 0`, with no else (factor path at 155-157 does fall back to equal weights). All-zero weights → `_calculate_portfolio_returns` yields all-0 series → metrics computed anyway (`_calculate_basic_metrics` hits the `<10` branch or mean=0 path; Sortino downside = annualized daily rf → very negative, not success-flagged). Only no-crash test: `test_wave1_regressions.py:90`. | analytics_engine.py:62-64 | analytics_engine.py:62-64 (add `else: equal-weight` or return error) | Zero-weight portfolio must not return fabricated Sharpe/Sortino/hit-ratio without an `error` flag.

- P2 / empty-forecast-hardcodes-garch | P2 | confirmed | `_empty_forecast` (1303-1317) hardcodes `"model": "GARCH"` / `model_params type GARCH`; returned for failed EGARCH (1048) and for short-data EWMA/EGARCH requests via `forecast_volatility` line 106 (no model arg). | analytics_engine.py:1308, 1315 | analytics_engine.py:106, 119, 1303-1317 (thread `model` through) | `forecast_volatility(returns_len<30, model="EGARCH")` must echo `model == "EGARCH"` in the empty payload.

- P2 / fabricated-empty-metrics | P2 | confirmed | `_empty_metrics` returns `annual_volatility:0.20, hit_ratio:0.5, kurtosis:3` (1287-1301); `_empty_stress_test` returns `max_drawdown:-0.20, portfolio_impact:-0.17, recovery_time:30` (1371-1379); `_empty_risk_score` returns `overall_score:25.0` + invented components (1391-1405). Router returns them as-is. Test enshrines it: `test_analytics_engine.py:35` asserts `== 0.20`. | analytics_engine.py:1287, 1371, 1391 | analytics_engine.py:1287/1371/1391 + tests/test_analytics_engine.py:35 | Empty-data responses must be nulls + `error` flag; update the asserting test.

- P2 / empty-frame-aborts-cascade | P2 | confirmed | Lines 377-378 `if df.empty: return df` runs inside the retry loop (365) and returns from `fetch_historical_data`, skipping remaining retries and the AV tier at 409-414. `_normalize_yfinance_data` returns empty on missing `Adj Close` (867). | data_service.py:377-378 | data_service.py:377-378 (`continue` instead of `return`) | Vendor frame missing `Adj Close` must still reach remaining retries/AV; only return None after all tiers fail.

- P2 / partial-history-perpetual-refetch | P2 | confirmed | Lines 931-938: for a ticker whose earliest row starts >30d after `req_start`, `(earliest_cached - req_start).days > 30` stays true forever; after the 1h `fetched_on` grace, every later request misses, re-downloads the 10y deep window, upserts (refreshing `fetched_on`), and repeats. `test_deep_cache.py` covers stale-tail/deep-start but not this start-gap. | data_service.py:931-938 | data_service.py:924-938 (persist coverage/backfill-done marker) | Seed DB with history starting 60d after `req_start` + old `fetched_on`; second fetch must be a cache hit, not a vendor download.

- P2 / exception-path-raw-ticker | P2 | confirmed | Line 565 `return await self._fallback_quote(ticker, ticker.upper().strip())` skips `normalized_ticker` computed at 434 (compare correct call at 561). Input `"reliance"` → AV queried as `"RELIANCE"` not `"RELIANCE.NS"`. Test `test_coverage_data_service.py:186-192` only checks price, not args. | data_service.py:565 | data_service.py:565 (pass `normalized_ticker`) | Patch `_fallback_quote` and assert second arg equals `canonical_ticker(input)` on the exception path.

- P2 / sync-yfinance-in-async | P2 | confirmed | `validate_ticker` calls `stock.history(period="5d")` inline at 661 (bfinance branch correctly uses `asyncio.to_thread` at 658); `get_corporate_actions` calls `stock.splits`/`stock.dividends` inline at 690-691. Awaited from `app/api/data.py:438` and `app/api/portfolio.py:170/327`. Tests mock yfinance so blocking is invisible (`test_coverage_data_service.py:194-231`). | data_service.py:661, 690-691 | data_service.py:660-662, 687-691 (wrap in `asyncio.to_thread`) | While a slow `history` blocks, a concurrent no-op coroutine must still progress (or at least: code review — calls off-loop like line 658).

- P2 / cache-delete-insert-race | P2 | confirmed | `set_cached_analytics` does DELETE (74-79) then INSERT (80-90) non-atomically; `AnalyticsCache` has only non-unique `Index("ix_ticker_metric")` (models/database.py:84-86), no UQ. Concurrent writers → two rows → `scalar_one_or_none` at line 36 raises `MultipleResultsFound` → caught at 49-51 → returns None → perpetual miss. Docstring 61-68 admits the missing UQ as "P1 follow-up"; `test_p08_cache.py` only proves sequential replace. | cache_service.py:74-90 | cache_service.py:74-90, app/models/database.py:84-86 (add `UniqueConstraint` + `on_conflict_do_update`) | Two concurrent `set_cached_analytics` on same key must leave exactly one row; subsequent `get` must hit.

### P3

- P3 / empty-scenario-matches-first-key | P3 | confirmed | Line 479 `if k in scenario_key or scenario_key in k` — with `scenario_key == ""` (from `scenario=""`/None at 401), `"" in "market_crash"` is True, so the first config key (`market_crash`, -35%) matches instead of falling through to the custom branch at 483. | analytics_engine.py:479 | analytics_engine.py:479 (`if scenario_key and (...)`) | `stress_test(..., scenario="")` must not return the market_crash scenario name/shock.

- P3 / custom-shock-comment-lie | P3 | confirmed | Comment at 484 promises "Custom shock if present in scenario string" but the branch (485-490) hardcodes `market_shock: -0.20` regardless of any number in `scenario`. | analytics_engine.py:484-486 | analytics_engine.py:484-490 (parse signed % or reword comment) | `stress_test(..., scenario="crash -10%")` should either parse -0.10 or the comment must stop claiming parsing.

## Improvements

- P2 / global-warnings-filter | P2 | confirmed | Line 11 `warnings.filterwarnings('ignore')` at module import suppresses all warnings process-wide for every subsequently imported module (arch convergence, pandas deprecation, numpy runtime). | analytics_engine.py:11 | analytics_engine.py:11 (scope to `category=` or use `catch_warnings` around arch fits) | Emit a warnings filter check: `warnings.filters` must not contain a bare ignore-all entry after import.

- P3 / bare-except-clauses | P3 | confirmed | Exactly 9 bare `except:` at cited lines 835, 876, 895, 913, 926, 967, 1242, 1263, 1282 — swallow KeyboardInterrupt/SystemExit; e.g. 835-836 returns empty Series silently. | analytics_engine.py:835, 876, 895, 913, 926, 967, 1242, 1263, 1282 | analytics_engine.py (all 9 → `except Exception:`) | Grep `except:` in analytics_engine.py must return 0 matches.

- P3 / dead-four-helpers | P3 | confirmed | Grep: `_calculate_max_drawdown`/`_simulate_stress_drawdown`/`_estimate_recovery_time`/`_calculate_liquidation_days` are defined at 1233/1245/1266/1346 and referenced only by `tests/test_analytics_engine.py:369-416`. Production `stress_test` computes drawdown inline (537), `liquidity_analysis` uses tier logic inline (348-356). | analytics_engine.py:1233, 1245, 1266, 1346 | analytics_engine.py + tests/test_analytics_engine.py:369-416 | Delete helpers and their four unit tests (or route production through them); grep must find no production callers either way.

- P3 / triple-portfolio-ols | P3 | confirmed | Same portfolio-on-benchmark OLS runs at 1154 (`port_model`), 1204 (`_calculate_r_squared`), and 1227 (`_calculate_adjusted_r_squared`) — all called from `factor_exposure_analysis` 168-170. Adjusted R² is closed-form from raw R². | analytics_engine.py:1187, 1210, 1154, 1204, 1227 | analytics_engine.py:168-170 + 1187-1231 (one regression, derive adj) | Instrument/call-count: one `sm.OLS` fit per `factor_exposure_analysis` request for the portfolio leg.

- P3 / dead-weight-length-check | P3 | confirmed | Lines 825-829 build `weight_vector` by iterating `returns.columns`, so `len(weight_vector) != len(returns.columns)` at 830 can never be true. | analytics_engine.py:830-831 | analytics_engine.py:830-831 (delete branch) | No behavior change; branch removal only.

- P3 / liquidity-tier4-dead-medium-arm | P3 | confirmed | Line 316 clamps `score = max(2.5, min(5.9, ...))` so score ≤ 5.9; line 317 `category = "Low" if score < 6.0 else "Medium"` can never take `"Medium"`. | analytics_engine.py:317 | analytics_engine.py:317 (`category = "Low"`) | No output change; dead-arm removal only.

- P3 / hardcoded-risk-free-rate | P3 | confirmed | Line 28 `self.risk_free_rate = 0.02` hardcoded; no `risk_free_rate` key in `app/config.py` settings; used at 856/861/864. Other tunables live in `settings`. | analytics_engine.py:28 | analytics_engine.py:28, app/config.py (add `risk_free_rate` setting) | Override via env/config must change Sharpe/Sortino numerator.

- P3 / stale-data-service-docstring | P3 | confirmed | Lines 1-3 claim "yfinance as primary source" while the file implements user-selectable bfinance/yfinance cascade with AV last (354-356, 409). | data_service.py:1-3 | data_service.py:1-3 | Docstring matches cascade behavior.

- P3 / redundant-local-import | P3 | confirmed | Line 1140 `from sqlalchemy import func, select` re-imports what's already at line 12; line 1137 `ticker: str = None` should be `Optional[str]`. | data_service.py:1140, 1137 | data_service.py:1137, 1140 | No local import; annotation is `Optional[str]`.

- P3 / replaced-count-always-zero | P3 | confirmed | Line 1027 `_log_storage_metrics(ticker, len(records), 0)` always passes `replaced_count=0`, so `replacement_ratio` at 1101 is always 0 and the `>0.5` warning at 1104 is unreachable dead code. | data_service.py:1027, 1104 | data_service.py:1027 (count upsert conflicts or delete helper) | Conflict-count path must be able to trip the warning, or the warning/helper is removed.

- P3 / unittest-mock-sniffing | P3 | confirmed | Lines 540-547 and 733-740 `is_yf_mocked = isinstance(yf.Ticker/download, (unittest.mock.Mock, ...))` — production vendor branching coupled to the test framework. | data_service.py:543, 734 | data_service.py:539-554, 732-764 (inject vendor callables) | Runtime logic contains no `unittest.mock` import/reference.

## Optimizations

- P2 / arch-fit-blocks-event-loop | P2 | confirmed | `model.fit(...)` at 982 (GARCH) and 1022 (EGARCH) runs synchronously inside `async def`; `volatility_sizing` awaits once per ticker in a serial loop (589-601); forecast endpoint loops positions at `app/api/analytics.py:527-533`. CPU-bound scipy optimizer blocks the loop. | analytics_engine.py:982, 1022 | analytics_engine.py:982, 1022 (+ optional semaphore around 589-601) | During a 10-ticker GARCH sizing request, a concurrent lightweight endpoint must not stall for the sum of all fits (use `asyncio.to_thread`).

- P2 / cache-stats-materializes-table | P2 | confirmed | `get_cache_stats` does `select(AnalyticsCache)` full-row loads at 155, 160, 167 plus all FetchLogs from 24h at 174, then Python-filters at 181. Served by GET in `app/api/data.py:173`. | cache_service.py:155-182 | cache_service.py:155-182 (`func.count()` aggregates) | Seed N cache rows; endpoint must issue COUNT queries, not fetch N model instances (or assert SQL shape).

- P3 / clear-expired-row-by-row | P3 | confirmed | Lines 135-136 issue one `await self.db.delete(entry)` per expired row instead of a set-based DELETE. Grep: no production caller — only `tests/test_coverage_services_and_api.py:132,163`. | cache_service.py:135-136 | cache_service.py:125-144 (`delete(AnalyticsCache).where(...)`) | Seed M expired rows; clear must be a single DELETE statement.

- P3 / full-frame-load-on-cache-hit | P3 | confirmed | Line 347 `full_frame = await self._get_full_cached_frame(...)` loads the ticker's full-depth history on every SQLite cache hit, inside the global `_db_lock` (81), solely to populate L1. | data_service.py:347 | data_service.py:344-352 (skip when L1 already live, or lazy-populate) | Second hit within L1 TTL must not re-query full history.

- P3 / partial-history-redownload-opt | P3 | confirmed | Same path as Bugs P2 `data_service.py:932`: full 10y vendor download where existing DB rows suffice — repeated network IO per ticker per hour for partial-history tickers. | data_service.py:931-938 | (same as P2 #8 fix) | See partial-history regression test above; vendor call count must stay 0 on repeat.

- P3 / corr-computed-twice | P3 | confirmed | Line 740 evaluates `returns.corr()` twice in one expression (once for `triu_indices_from`, once for the gather). | analytics_engine.py:740 | analytics_engine.py:740 (bind `c = returns.corr().values` once) | No numeric change; one `.corr()` call per invocation.

- P3 / wait-for-cannot-cancel-thread | P3 | confirmed | Lines 767-770 `asyncio.wait_for(loop.run_in_executor(None, download), timeout=...)` times out the await but leaves the worker thread running; retries stack up to 3 downloads per ticker × 5 batch workers, then AV may run. | data_service.py:767-770 | data_service.py:766-770 (comment the limitation, or cancellable pool + per-ticker single-flight) | Timeout path: document known ceiling, or dedupe concurrent identical fetches.

- P3 / fetch-quote-no-cache | P3 | confirmed | `fetch_quote` (422) has no L1, no SQLite quote table, no memo — every dashboard/WS/portfolio refresh hits live vendors (`app/api/portfolio.py:361,1089`, `analytics.py:794`). OHLCV has a 3-tier cache; quotes have none. | data_service.py:422 | data_service.py:422 (short-TTL in-process memo keyed by canonical ticker) | Two quote calls within TTL must hit vendor once.

- P3 / iterrows-upsert | P3 | confirmed | Line 986 `for _, row in df.iterrows():` builds upsert dicts row-by-row for ~2500-row deep windows — slowest part of the store path. | data_service.py:986-1000 | data_service.py:985-1000 (`df.to_dict("records")` + shared stamping) | Store path uses `to_dict("records")`; outputs unchanged.

## What's clean (spot-checked, not findings)

- `_db_lock` serialization (data_service.py:81 etc) + `tests/test_db_gate_concurrency.py` exist.
- Native SQLite upsert for `StockTimeseries` (1006-1020) against `UniqueConstraint` (database.py:62); covered by `test_coverage_data_service.py:375` and `test_deep_cache.py`.
- `canonical_ticker` (40-65) suffix checks correct; tests `test_p07_ticker.py` exist.
- risk_scoring no-benchmark exclusion (746-777) correct and tested (`test_quant_math_p1_batch.py:249-259`).
- `clear_market_data_cache` (cache_service.py:211-284) one transaction, preserves `portfolio_positions`.

## Summary

33 findings verified: **confirmed 33, refuted 0, already-fixed 0**. Both P1s stand: factor-exposure placeholder overwrite (analytics_engine.py:1170, reachable via analytics.py:652-663 with no guard) and AV-quote `is_indian` tested against `.BSE` on canonical tickers (data_service.py:840, masked by test_coverage_data_service.py:336). Highest-leverage fixes remain: P1 pair, arch-fit offload (982/1022), fabricated empty metrics (1287/1371/1391), analytics-cache UNIQUE+ON CONFLICT (cache_service.py:74), partial-history perpetual refetch (932), and the three small data-service correctness fixes (377, 565, 660/687).
