# Fix session report — backend audit

Date: 2026-09-23
Scope: working tree vs HEAD (`13d89ed`); adversarial review of the uncommitted fix session covering `.scratch/backend-audit/` reports 01–06 (~208 severity-tagged findings). Review-only pass: no product code edited by this review; `frontend/`, `backend/pyproject.toml`, `backend/uv.lock` untouched (verified: no content diff / no new deps / no ruff-scope widening).

## Counts

Strict per-line annotations (`Status: …`), reports 01–04 + 06 (report 05 uses a "Fix status" table — counted separately):

| Status | 01 | 02 | 03 | 04 | 06 | Total |
|---|---|---|---|---|---|---|
| fixed | 21 | 27 | 0 | 49 | 23 | **120** |
| already-fixed | 0 | 1 | 32 | 0 | 0 | **33** |
| skipped | 11 | 21 | 1 | 2 | 12 | **47** |
| partially | 0 | 0 | 0 | 0 | 2 | **2** |
| n/a | 0 | 1 | 0 | 0 | 1 | **2** |
| handoff-only | 0 | 0 | 0 | 1 | 0 | **1** |
| **total** | 32 | 50 | 33 | 52 | 38 | **205** |

Report 05 (table format), 42 verified findings: **7 fixed** (+1 handoff fixed from 06), **13 already fixed**, **2 refuted**, **15 skipped**, **5 verified-clean**.

Combined: **~127 fixed this session**, 46 already fixed earlier in the session, 62 skipped/refuted backlog, 2 partial.

**Wave 4 (2026-09-23, closing review findings)** added 7 more fixes: identity-check regression (`data_service.py` + `company_data_service.py` unification), `RuntimeError`→503 in all 10 `equity_research.py` vendor routes, legacy-DB `analytics_cache` unique-index self-heal in `init_db` (empirically confirmed: real DB had no `(ticker, metric_name)` unique index → upsert raised `ON CONFLICT clause does not match`), flaky `TestOffEventLoopWork` threshold (`>=10`→`>=3`), `risk_free_rate` wired to `Settings` (`config.py:32`, default 0.02), `datetime.utcnow()` deprecation sweep (screener/portfolio/websocket/currency, naive-vs-aware matched to storage convention), mojibake `ΓÇö` **refuted** (zero matches). New permanent tests: `test_bugfix_equity_research_503.py` (1), `test_bugfix_cache_index_selfheal.py` (3).

**Wave 3 adversarial diff review (post-Wave-4)** initially **FAILED** with 2 P1s + 1 P2; all fixed in the follow-up pass:
1. **[P1] Test suite mutated production `daisy.db`** — the `client` fixture entered `TestClient` lifespan → `init_db()` on the module-level real engine, so the Wave-4 self-heal `DELETE`+`CREATE INDEX` ran against the real DB during full-suite runs (empirically: mtime changed mid-run; heal index now present on prod — benign, 0 dupes, intended end-state, but the isolation gap was real). **FIXED**: `tests/conftest.py:233-259` `client` fixture now monkeypatches `db_mod.engine`/`SessionLocal`/`ws_mod.SessionLocal`/`settings.database_url` to a `tmp_path` sqlite engine before lifespan (option (a): all `client` consumers verified to seed their own data — no prod-data dependency); duplicate un-isolated local `client` fixture deleted from `tests/test_websocket.py:99-110`. **Acceptance**: `daisy.db` SHA256+mtime byte-identical before/after full-suite runs.
2. **[P1] False claim in this report** — "real daisy.db hash/mtime verified unchanged" was retracted above; the copy-only verification applied to the self-heal unit tests, not the full-suite side effect. Corrected in §Remaining-issues #3.
3. **[P2] `validate_ticker` missing identity-skip** — `data_service.py:692-707` could reach real `bfinance.Ticker` from a yf-only-patched unit test (live network). **FIXED**: same `is_yf_mocked and not is_bf_mocked → continue` guard as quote/download; grep confirmed it was the only unguarded vendor method; regression test `test_bugfix_core_services.py:266-305`.
4. **[P3] Residual `datetime.utcnow()`** in `cache_service` (6), `data_service` (6), `india_data_service` (2) — Wave-4 sweep had only covered 4 files. **FIXED** (all naive-UTC DB semantics → `now(timezone.utc).replace(tzinfo=None)`); product code now has zero `utcnow` calls.
5. Nits accepted, not changed: line-ref drift in this report (`config.py:31`→`:32`, `portfolio.py:309`→`:33`, `:1259`→`:1260-1261`, `:582-589`→`:582-590`, `:783-788`→`:783-789` — corrected at point of use below where it matters); `AGENTS.md` also dirty (pre-existing, out of audit scope); untracked `.zcode.lnk` junk; file-scoped `_quote_memo` clears tolerated (P3); `create_tables()` doesn't self-heal (startup-only, acceptable); `run_custom_screen` lacks ValueError→400 (pre-existing, unclaimed).

## Per-report one-liners

- **01 api-analytics** — `_q` NaN/inf guard, fabricated optimize/factor/ad-hoc-liquidity placeholders killed (API layer), `timezone.utc`, unused `Depends` pruned; leftover: mixed 200+error vs 4xx contract (QH-04) + sequential-fetch optimizations skipped.
- **02 api-rest-main** — CSV export returns real `text/csv`, global `auto_normalize` sums DB-wide to 1.0, intra-payload bulk dedup, `_source_of_df`/pre-fetch `from_cache` truth, bare-ticker CRUD, WS dup-id/mutation-safety; leftover: provenance + `fetch_historical_data` signature handoffs.
- **03 core-services** — verified-only report: 32 already-fixed confirmed against working tree (identity check, GARCH `to_thread`, `_quote_memo`, iterrows removal, scoped warning filter, dead helpers deleted); 1 skipped (`risk_free_rate` config wiring).
- **04 quant-services** — largest fix batch (49): cointegration cache keys now include `p_value_threshold`/`include_spread_series`, tail-risk GPD fallback returns `model_fitted=False` historical-only (no more `xi=0.15`/`hist*1.15`), indicator `look_back_days` honored, MC path cap, copula O(n) fits, `asyncio.to_thread` in `scan_pairs`; leftover: API-layer `to_thread` wraps, EVT key naming, cache bulk API.
- **05 market-data** — service-side `RuntimeError` taxonomy (upstream→503-ready, `ValueError`=not-found), ROE/dividend unit fixes, AV `outputsize=full`, bhavcopy/flow `IntegrityError` tests; **its HANDOFF #2 ("5 pre-existing failures, live AV premium") is refuted** — see below.
- **06 foundation** — NSE `UniqueConstraint`s + `ON CONFLICT`, schema prep delivered to 04/05 (Optional EVT/vol-cone fields, ticker `pattern=`, screen `Field` bounds), root trap scripts deleted, `quantity=100.0` migration clause removed, `db/database.py` makedirs-before-`create_all`; leftover: ORM/migration index reconciliation (untagged).

## Verification

- **Ruff** (`uv run --group dev ruff check main.py app/`): **All checks passed!**
- **Full pytest**: **537 passed, 0 failed** (final, post-review-fix; 536 + 1 new `validate_ticker` regression test; was 8 failed / 524 passed pre-Wave-4). Scope guard re-verified: HEAD still `13d89ed`, no commits, `frontend/` + `backend/pyproject.toml` + `backend/uv.lock` zero content diff, ruff `select=["E9","F"]` identical to HEAD.
  - **7 identity-check regressions FIXED** — root cause: mock detection (`yf.download is not DataService._YF_DOWNLOAD_REAL`) blanket-skipped the bfinance tier whenever yfinance was patched, even when tests also patched bfinance intentionally. Fix: skip real bfinance only when `yf_patched AND not bf_patched` (`data_service.py:582-589,783-788`, identities `_BF_TICKER_REAL`/`_BF_DOWNLOAD_REAL` at `:128-129`); unified `company_data_service.py` (`isinstance(…, Mock)` → same identity pattern, `:122-136,242,286-293`); memo-leak guard added to existing autouse fixture in `test_source_preference_and_cache.py:113-116`. 23/23 + 115-test regression sweep green. Also **refutes report 05 HANDOFF #2** ("pre-existing / live AV premium") — it was downstream of this skipped tier.
  - **1 flaky FIXED** — `TestOffEventLoopWork` tolerance `ticks >= 10` → `>= 3` (sentinel yields ~7 under coverage vs ~60 free); 3× consecutive runs green (14/14/14).
  - **daisy.db isolation** — `client` fixture now tmp-engine monkeypatched (Wave-3 review P1); suite runs leave prod DB hash+mtime identical.
- **Banned placeholder greps** (app/, main.py, migrations/, tests/): **all clean for the banned classes** — no `{alpha: 0.0`, `alpha": 0.0`, `market": 1.0`, fabricated single-holding `0.12/0.22/0.45` metrics, `xi = 0.15`, `hist_var_loss * 1.15`, `overall_score.*25.0`, `ΓÇö`, fabricated VaR/CVaR constants (exact-boundary regex, 0 hits). Raw `0.12|0.22|0.45` literals remain only in pre-existing stress-scenario tables (`analytics_engine.py:433,:537,:1000`, HEAD-identical), test fixtures, and assert-absence comments — out of the banned class. `FALLBACK_USD_INR = 83.0` (`currency_service.py:16`) exists but is documented/never cached as live — OK.
- **AGENTS.md invariants**: ticker regex supports hyphens/`&`/`.` (`schemas.py` `^[A-Z0-9\-\&\.]{1,20}$`), single-holding/diversification & zero-state weight spot-checks clean, no new deps, ruff scope unchanged.
- **Frontend**: zero content diff (line-ending warnings only).

## Remaining issues (ordered) — ALL CLOSED (Wave 4, 2026-09-23)

1. ~~**[P1] Identity-check regression**~~ **FIXED** — see Verification above; 7 tests green, unification done, report-05 HANDOFF #2 refuted.
2. ~~**[P1] `RuntimeError` → 503**~~ **FIXED** — `except RuntimeError → HTTPException(503, detail=str(e))` added to all 10 vendor routes in `app/api/equity_research.py` (profile :49, shareholding :66, concalls :82, custom-ratios :100, excel :126, memo :148, forensic :166, dossier :189, screener :231, custom-screen :253); `list_screener_strategies` skipped (static list, no vendor call). Regression test: `test_bugfix_equity_research_503.py` (503 + detail asserted); 56 neighboring tests green.
3. ~~**[P1] Legacy-DB upsert risk**~~ **FIXED (analytics_cache)** — empirical confirmation: real DB had only a 3-col UNIQUE `(ticker, metric_name, calculation_date)` + non-unique `ix_ticker_metric`, so `on_conflict_do_update(index_elements=["ticker","metric_name"])` raised `OperationalError`. `init_db` (`app/db/database.py:63-71`) now self-heals after `create_all` (sqlite-guarded): dedupe keeping `MAX(id)` per `(ticker, metric_name)` + `CREATE UNIQUE INDEX IF NOT EXISTS uq_analytics_cache_ticker_metric`. Red→green: 3 failed → 3 passed (`test_bugfix_cache_index_selfheal.py`, hermetic `tmp_path`). 58 cache tests green. **CORRECTION (Wave-3 review)**: the earlier "real daisy.db hash/mtime verified unchanged" claim is retracted — the self-heal *unit tests* were copy-only, but the full-suite `client` fixture lifespan ran `init_db()` against the real DB (benign: 0 dupes, index is the intended end-state, now present on prod). The isolation gap is fixed (`tests/conftest.py:233-259` tmp-engine monkeypatch); subsequent full-suite runs leave `daisy.db` byte-identical (SHA256+mtime verified). NSE/stock_timeseries constraints still require `migrations/cleanup_duplicates_and_add_constraints.py` on legacy DBs (untagged backlog).
4. ~~**[P2] Flaky**~~ **FIXED** — see Verification above.
5. ~~**[P2] Inconsistent mock detection**~~ **FIXED** — `company_data_service.py` unified with `data_service.py` identity pattern (part of fix #1).
6. ~~**[P2] `risk_free_rate` hardcoded**~~ **FIXED** — `Settings.risk_free_rate: float = Field(default=0.02)` (`config.py:31-32`); `analytics_engine.py:35` reads `settings.risk_free_rate`; test asserts `== settings.risk_free_rate` (default unchanged, 0.02).
7. Cosmetic: mojibake `ΓÇö` **REFUTED** (zero matches under `backend/`; comments already use proper `—`). `get_api_config` error path now raises 500 instead of returning defaults (contract change — intended); PUT position validation moved to pydantic → invalid input now **422** not 400 (tests accept both). `datetime.utcnow()` deprecation **FIXED** in all 7 product files (screener/portfolio/websocket/currency Wave-4; cache/data/india_data Wave-3-review follow-up; naive-vs-aware matched to each storage convention; zero `utcnow` calls remain in `app/`).

## Wave-3 review findings (new, not from reports 01–06) — ALL CLOSED

1. ~~**[P1] Tests mutate prod `daisy.db` via lifespan**~~ **FIXED** — `tests/conftest.py:233-259` `client` fixture tmp-engine monkeypatch; `tests/test_websocket.py` duplicate local fixture deleted; acceptance = byte-identical hash/mtime across full-suite runs.
2. ~~**[P1] False "daisy unchanged" claim in this report**~~ **CORRECTED** — see issue #3 above.
3. ~~**[P2] `validate_ticker` unguarded vendor call**~~ **FIXED** — identity-skip added (`data_service.py:692-707`); only unguarded method per grep; regression test `test_bugfix_core_services.py:266-305`.
4. ~~**[P3] utcnow residuals (cache/data/india)**~~ **FIXED** — 14 sites replaced, naive-UTC semantics preserved.
5. Nits (line-ref drift, `AGENTS.md` dirty, `.zcode.lnk`, file-scoped memo clears, `create_tables` no self-heal, `run_custom_screen` no 400): accepted as noted above, no code change.

## Handoffs left open (consolidated from reports 01–06)

- **database.py**: `UniqueConstraint("ticker")` on `portfolio_positions` (02).
- **schemas.py**: `BulkAddResponse.duplicates`; residual `VolConeWindow.current_realized` / `VolForecastOverlay.percentile_rank` → `Optional[float]`; EVT confidence-suffixed keys (02/04).
- ~~**analytics_engine.py**~~ — **both closed**: `_empty_factor_exposure` returns `alpha/market: None` (`analytics_engine.py:1259`), placeholder grep clean (02 handoff stale); `risk_free_rate` still hardcoded → moved to config handoff below (03).
- **data_service.py**: `fetch_historical_data` return `(df, source, from_cache)`; `fetch_quote` source/vendor key (removes portfolio provenance hardcode + double cache probe) (02).
- **api/analytics.py**: `asyncio.to_thread` around `run_walk_forward_backtest` / `simulate_goal` / vol-cone / tail-risk / copula call sites (04 HANDOFF 1).
- **cache_service.py**: bulk `get/set_cached_analytics_many` for `scan_pairs` (04 HANDOFF 3).
- ~~**api/equity_research.py**: `RuntimeError` → 503 mapping~~ — **closed** (Wave 4; 10 routes + `test_bugfix_equity_research_503.py`).
- ~~**config.py**: `risk_free_rate` setting~~ — **closed** (Wave 4; `config.py:31` default 0.02). `ALLOWED_ORIGINS` parsing still fragile (06).
- ~~**utcnow残留**~~ — **closed** (Wave 4 four files + Wave-3-review follow-up three files; zero `datetime.utcnow()` calls remain in `app/`, naive/aware matched to storage).
- **portfolio.py:309**: route `_TICKER_PATTERN` now redundant with schema `pattern=` (06 — keep or drop).
- ~~** india_data_service**~~ — **closed**: `IntegrityError` handlers at `india_data_service.py:105,150` (reselect pattern) + tests in `test_bugfix_providers_05.py`; root trap scripts (`test_bulk_operations_integrity.py`, `test_api_integrity.py`, `_diag_rc.py`) verified deleted (06 HANDOFF 1 / rec 1).
- **ORM/migration index reconciliation**: ~~unique-vs-nonunique drift on `analytics_cache`~~ — **closed by init_db self-heal** (Wave 4); duplicate unique index on stock_timeseries still untagged backlog; legacy NSE/stock_timeseries constraints still need `migrations/cleanup_duplicates_and_add_constraints.py`.
