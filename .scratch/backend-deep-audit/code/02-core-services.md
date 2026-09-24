# Wave 1 — Core Backend Services Line-by-Line Audit

## 1. Scope and method

- **Scope:** cash-equity portfolio analytics, core market-data retrieval, persistent/in-memory caching, and their direct backend contracts. Out-of-scope asset classes and unrelated recommendation services were excluded from findings. The analytics API was read only to trace cash-equity callers and contracts (`backend/app/api/analytics.py:68-207`, `backend/app/api/analytics.py:210-1181`, `backend/app/api/analytics.py:2030-2146`).
- **Primary files:** every line of `backend/app/services/analytics_engine.py:1-1345`, `backend/app/services/data_service.py:1-1293`, and the actual cache filename `backend/app/services/cache_service.py:1-287` was inspected. No split analytics engine or `cache.py` exists; the related first-party service files listed in section 2 were also read line-by-line.
- **Method:** static caller tracing from service to API/schema/model/database contracts; query-pattern comparison against declared indexes; cache key, expiry, invalidation, and concurrency review; test inspection for risk-specific gaps. No prior-audit or unrelated `.scratch` content was read.
- **Verification:** 178 focused tests passed across 12 test files, and the configured Ruff gate passed with no cache. Three no-network reproductions confirmed that the quote model drops `52_week_*`, a missing priced column dilutes portfolio volatility, and an unknown forecast model executes as GARCH; the corresponding source paths are `backend/app/models/schemas.py:139-150`, `backend/app/services/analytics_engine.py:64-85`, and `backend/app/services/analytics_engine.py:112-127`.
- **Live schema check:** read-only `PRAGMA index_list` metadata confirmed that the current `backend/data/daisy.db` has `idx_stock_timeseries_unique_ticker_date`, `uq_analytics_cache_ticker_metric`, the two StockTimeseries range indexes, and no standalone `analytics_cache(expires_at)` or `fetch_logs(timestamp)` index. No portfolio or market-data rows were inspected.

## 2. Exhaustive file inventory

Finding counts below assign each finding to one **primary** file, so the primary counts reconcile exactly to 23. “Referenced” means the file is part of another finding's flow but is not counted twice.

### 2.1 Primary service scope

| File | Lines inspected | Primary findings | Clean status |
|---|---:|---:|---|
| `backend/app/services/analytics_engine.py` | 1-1345 (1,345) | 8 — CORE-001/004/005/006/013/014/016/023 | Not clean |
| `backend/app/services/data_service.py` | 1-1293 (1,293) | 7 — CORE-002/003/009/010/011/018/022 | Not clean |
| `backend/app/services/cache_service.py` | 1-287 (287) | 3 — CORE-007/008/019 | Not clean |
| `backend/app/services/alpha_vantage_service.py` | 1-358 (358) | 0; referenced by CORE-002/022 | No standalone defect |
| `backend/app/services/company_data_service.py` | 1-389 (389) | 0; referenced by CORE-007 | No standalone defect |
| `backend/app/services/india_data_service.py` | 1-335 (335) | 2 — CORE-012/020 | Not clean |
| `backend/app/services/source_preference_service.py` | 1-85 (85) | 0 | Clean |
| `backend/app/services/cointegration_service.py` | 1-467 (467) | 0; referenced by CORE-007 | Cache mechanics implicated by CORE-007 |
| `backend/app/services/screener_service.py` | 1-364 (364) | 0 | Clean; its L1 cache is explicitly cleared by the purge (`backend/app/services/cache_service.py:268-269`) |
| `backend/app/services/benchmark_service.py` | 1-96 (96) | 0 | Clean |
| `backend/app/services/indicators_service.py` | 1-242 (242) | 0 | Clean |
| `backend/app/services/__init__.py` | 1-3 (3) | 0 | Clean |

**Primary service subtotal: 20 findings.**

### 2.2 Direct contracts and supporting first-party files

| File | Lines inspected | Primary findings / use | Clean status |
|---|---:|---|---|
| `backend/app/api/analytics.py` | 1-2255 (2,255) | 1 — CORE-015; caller for CORE-001/004-006/013/014/016 | Not clean |
| `backend/app/api/data.py` | 1-506 (506) | 1 — CORE-021; contract for CORE-003/007-010 | Not clean |
| `backend/app/api/portfolio.py` | 1-619 and 1040-1118 (698 of 1,118) | 1 — CORE-017; contract for CORE-003/015 | Not clean |
| `backend/app/api/websocket.py` | 1-358 (358) | Referenced by CORE-015/016 | Not clean as a caller |
| `backend/app/api/equity_research.py` | 1-257 (257) | Screener/cache caller | Clean |
| `backend/app/models/database.py` | 1-227 (227) | Schema contract for CORE-002/003/007/010/017/019 | Not clean |
| `backend/app/models/schemas.py` | 1-581 (581) | Contract for CORE-003/009 | Not clean |
| `backend/app/db/database.py` | 1-130 (130) | Startup/index contract for CORE-010/018/019 | Not clean |
| `backend/app/config.py` | 1-79 (79) | Direct settings contract | Clean |
| `backend/app/utils/holdings.py` | 1-260 (260) | Holding-window and annualization contract | Clean |
| `backend/app/utils/logger.py` | 1-55 (55) | Logging contract | Clean |
| `backend/main.py` | 1-181 (181) | Startup contract for CORE-018 | Referenced |
| `backend/migrations/cleanup_duplicates_and_add_constraints.py` | 1-292 (292) | One-off schema repair for CORE-018 | Referenced |
| `backend/migrations/add_portfolio_columns.py` | 1-104 (104) | Portfolio migration context | Clean |
| `backend/pyproject.toml` | 1-120 (120) | Test/lint contract | Clean |

**Direct-contract subtotal: 3 findings. Grand total: 23.**

### 2.3 Tests inspected for gaps only

| Test file | Range inspected |
|---|---:|
| `backend/tests/test_analytics_engine.py` | 1-509 (full) |
| `backend/tests/test_advanced_analytics.py` | 1-188 (full) |
| `backend/tests/test_coverage_analytics_extended.py` | 1-241 (full) |
| `backend/tests/test_coverage_data_service.py` | 1-476 (full) |
| `backend/tests/test_data_services.py` | 1-176 (full) |
| `backend/tests/test_deep_cache.py` | 1-275 (full) |
| `backend/tests/test_source_preference_and_cache.py` | 1-483 (full) |
| `backend/tests/test_screener_cache.py` | 1-145 (full) |
| `backend/tests/test_coverage_analytics_all_routes.py` | 1-232 (full) |
| `backend/tests/test_coverage_deep_analytics_routes.py` | 1-147 (full) |
| `backend/tests/test_p08_cache.py` | 1-65 (full) |
| `backend/tests/test_bugfix_cache_index_selfheal.py` | 1-150 (full) |
| `backend/tests/test_coverage_services_and_api.py` | 1-340 (full) |
| `backend/tests/test_coverage_india_data.py` | 1-154 (full) |
| `backend/tests/test_bugfix_providers_05.py` | 250-356 (107 of 356) |
| `backend/tests/test_contract_p1_batch.py` | 150-320 (171 of 320) |
| `backend/tests/test_quant_math_p1_batch.py` | 1-313 (full) |
| `backend/tests/test_bugfix_core_services.py` | 1-449 (full) |
| `backend/tests/test_bugfix_quant_services.py` | 1-300 (300 of 530) |
| `backend/tests/test_alpha_vantage.py` | 1-130 (full) |
| `backend/tests/test_coverage_alpha_vantage.py` | 1-220 (220 of 317) |
| `backend/tests/test_wave1_regressions.py` | 1-163 (full) |
| `backend/tests/test_bugfix_api_layer.py` | 280-379 (100 of 461) |
| `backend/tests/test_api_endpoints.py` | 1-180 and 220-279 (240 of 464) |
| `backend/tests/test_bugfix_foundation.py` | 70-249 (180 of 306) |
| `backend/tests/test_coverage_portfolio_api.py` | 60-109 (50 of 738) |
| `backend/tests/test_bug_sweep_2026_09.py` | 90-129 (40 of 342) |

No test file is a primary finding location; test gaps are cited inside each finding.

**Total unique files inspected: 54 (12 service-scope, 15 direct/supporting, 27 test-gap files).**

## 3. Findings

### P0 — none

No P0 security, crash, or data-loss condition was found in the localhost single-user cash-equity scope.

| Severity | Count |
|---|---:|
| P0 | 0 |
| P1 | 4 |
| P2 | 13 |
| P3 | 6 |
| **Total** | **23** |

| Category | Count |
|---|---:|
| Bug | 17 |
| Improvement | 2 |
| Optimization | 2 |
| Recommended change | 2 |
| **Total** | **23** |

### P1

#### CORE-001 — Missing priced columns dilute portfolio risk instead of renormalizing active weights

- **Category / severity:** Bug / P1.
- **Location:** `backend/app/services/analytics_engine.py:64-75`, `backend/app/services/analytics_engine.py:837-844`.
- **Flow / caller trace:** analytics callers retain weights for the requested/portfolio universe (`backend/app/api/analytics.py:68-97`, `backend/app/api/analytics.py:178-207`) but build price data only from successful fetches (`backend/app/api/analytics.py:148-175`). The engine normalizes across every supplied weight, then maps only columns present in the return frame; an absent ticker is silently assigned zero rather than redistributing its weight. The same helper feeds realized metrics, factor exposure, volatility sizing, and risk scoring (`backend/app/services/analytics_engine.py:74-85`, `backend/app/services/analytics_engine.py:1166-1183`, `backend/app/services/analytics_engine.py:621-630`, `backend/app/services/analytics_engine.py:732-795`).
- **Grounded impact:** with two 50% holdings and one fetch failure, annual return, volatility, VaR/CVaR, and Sharpe are computed on a half-capital return series. The missing weight becomes an implicit cash/residual weight, not a normalized active holding.
- **Minimum recommendation:** intersect weights with priced columns immediately before portfolio aggregation, renormalize that active set, and return explicit missing-ticker coverage; do not alter concentration, which should still describe the full requested book.
- **Test gap:** the direct helper test supplies every weight/column (`backend/tests/test_analytics_engine.py:296-305`), and populated-route tests make every mocked ticker succeed (`backend/tests/test_coverage_analytics_all_routes.py:65-86`). Add a two-holder/one-price numerical scaling test.

#### CORE-002 — Alpha Vantage's unadjusted fallback overwrites adjusted Yahoo/bfinance history

- **Category / severity:** Bug / P1.
- **Location:** `backend/app/services/alpha_vantage_service.py:270-308`, `backend/app/services/data_service.py:848-881`, `backend/app/services/data_service.py:1060-1110`.
- **Flow / caller trace:** Alpha Vantage explicitly mirrors unadjusted `close` into `adj_close` (`backend/app/services/alpha_vantage_service.py:270-297`). When the primary cascade fails, DataService stores that frame (`backend/app/services/data_service.py:868-877`) through an unconditional conflict update of every OHLCV/adj-close field (`backend/app/services/data_service.py:1093-1107`). Analytics consumes `adj_close` first (`backend/app/api/analytics.py:115-139`).
- **Grounded impact:** an existing adjusted series can be replaced by unadjusted rows after a fallback event. Splits and dividends then become artificial return jumps, distorting volatility, drawdown, factor beta, VaR/CVaR, and cash-equity performance history.
- **Minimum recommendation:** keep adjusted and unadjusted semantics distinct; do not overwrite adjusted rows with an unadjusted vendor merely because it is a later fetch.
- **Test gap:** the AV tests assert only that unadjusted close is mirrored (`backend/tests/test_alpha_vantage.py:73-77`), and the fallback cascade uses a frame whose `adj_close` already equals `close` (`backend/tests/test_source_preference_and_cache.py:213-235`). Add an adjusted-row → AV-fallback → analytics-return regression.

#### CORE-003 — Valid quotes with null sector/industry can make position creation fail at commit

- **Category / severity:** Bug / P1.
- **Location:** `backend/app/services/data_service.py:474-497`, `backend/app/services/data_service.py:555-570`, `backend/app/models/database.py:24-30`, `backend/app/api/portfolio.py:220-240`, `backend/app/api/portfolio.py:379-395`.
- **Flow / caller trace:** both primary quote implementations return `sector` and `industry` keys whose values may be `None`. The public quote schema explicitly permits null metadata (`backend/app/models/schemas.py:139-150`). Portfolio add/bulk paths persist `quote_data.get(...)` without an `"Unknown"` fallback, while the database columns are `nullable=False`; the subsequent commit then fails.
- **Grounded impact:** a valid ticker with incomplete vendor metadata can pass ticker/price validation and still return HTTP 500 instead of creating the position. The same incompatible values are used in single and bulk add paths.
- **Minimum recommendation:** normalize nullable quote metadata to the database contract before constructing the ORM entity and add a response-model integration case.
- **Test gap:** portfolio quote doubles always provide non-null sector and industry (`backend/tests/test_api_endpoints.py:135-143`), so the nullable-vendor branch is absent.

#### CORE-004 — GARCH/EGARCH multi-day VaR applies horizon scaling twice

- **Category / severity:** Bug / P1.
- **Location:** `backend/app/services/analytics_engine.py:978-1015`, `backend/app/services/analytics_engine.py:1020-1057`.
- **Flow / caller trace:** both models request `forecast(horizon=h)`, take the final value from the h-step variance path, and annualize that already h-step volatility (`backend/app/services/analytics_engine.py:994-1001`, `backend/app/services/analytics_engine.py:1036-1043`). They then multiply the final volatility by `sqrt(h/252)` before producing VaR/CVaR (`backend/app/services/analytics_engine.py:1001-1008`, `backend/app/services/analytics_engine.py:1043-1050`). The public route accepts horizons through 30 days (`backend/app/api/analytics.py:452-461`).
- **Grounded impact:** the final GARCH/EGARCH variance already represents the requested horizon, so the additional factor understates h-day tail loss increasingly with horizon; at h=30, the multiplier is `sqrt(30/252)`, approximately 0.345, rather than 1.0. EWMA has a flat one-step multi-horizon path and legitimately needs horizon scaling, so the three model paths are not mathematically equivalent.
- **Minimum recommendation:** use model-appropriate horizon semantics: the final h-step GARCH/EGARCH forecast directly, or a separately identified one-step volatility before square-root-of-time scaling.
- **Test gap:** the GARCH test asserts only response keys at horizon 5 (`backend/tests/test_analytics_engine.py:72-95`); the EWMA regression checks only EWMA's flat one-step forecast path (`backend/tests/test_quant_math_p1_batch.py:48-61`). Add a hand-calculated h>1 GARCH/EGARCH VaR test.

### P2

#### CORE-005 — The risk score's factor leg silently uses equal weights

- **Category / severity:** Bug / P2.
- **Location:** `backend/app/services/analytics_engine.py:757-773`, `backend/app/services/analytics_engine.py:1166-1183`.
- **Flow / caller trace:** `risk_scoring` receives current portfolio weights but calls `factor_exposure_analysis` without them (`backend/app/services/analytics_engine.py:761-763`). The omitted argument defaults to equal weights (`backend/app/services/analytics_engine.py:157-160`), and the resulting portfolio R² is used for the 25% factor-risk leg.
- **Grounded impact:** two risk scores for the same returns can differ solely because allocation changed, even though the factor leg is documented as the portfolio's unexplained risk. Concentrated current books are scored using a synthetic equal-weight portfolio.
- **Minimum recommendation:** pass the current weights into the factor calculation and keep concentration/full-book semantics separate.
- **Test gap:** the benchmark regression asserts only that the factor leg is present/non-null (`backend/tests/test_quant_math_p1_batch.py:269-282`); an equal-weight implementation satisfies it.

#### CORE-006 — Liquidity classification can call a zero-turnover mega-cap “High,” and liquidation days are not holding-specific

- **Category / severity:** Bug / P2.
- **Location:** `backend/app/services/analytics_engine.py:256-260`, `backend/app/services/analytics_engine.py:288-326`, `backend/app/services/analytics_engine.py:341-376`, `backend/app/api/analytics.py:786-838`.
- **Flow / caller trace:** every tier uses turnover **OR** market cap. A large-cap stock with zero/near-zero turnover enters the High branch solely on market cap. The method receives only prices, volumes, and market caps—no position value or participation rate—yet emits categorical `liquidation_time_days`. The separate ADV service demonstrates the position-size formula (`backend/app/services/india_data_service.py:299-327`).
- **Grounded impact:** a non-trading mega-cap can be labelled High liquidity, and the reported 1-2/2-5/5-10 day label is an instrument category rather than the current holding's liquidation duration. Portfolio size therefore does not affect the output.
- **Minimum recommendation:** require a minimum turnover/executability gate; keep instrument score separate from position-size days-to-liquidate.
- **Test gap:** liquidity tests use large random positive volumes and assert only ranges/keys (`backend/tests/test_analytics_engine.py:167-193`); no zero-turnover/mega-cap or position-size boundary exists.

#### CORE-007 — Cache purge has no complete in-process invalidation boundary

- **Category / severity:** Bug / P2.
- **Location:** `backend/app/services/cache_service.py:211-287`, `backend/app/services/data_service.py:292-318`, `backend/app/services/cointegration_service.py:24-26`, `backend/app/services/cointegration_service.py:284-346`, `backend/app/services/company_data_service.py:59-70`.
- **Flow / caller trace:** the purge commits DB deletion before clearing selected process caches (`backend/app/services/cache_service.py:243-278`). It clears DataService, screener, and currency caches, but not the 24-hour cointegration L1 cache or CompanyDataService's 24-hour fundamentals cache. DataService can also repopulate L1 after the DB wipe from an in-flight fetch because cache write occurs after the purge commit boundary.
- **Grounded impact:** `/data/cache/clear` can leave analytics/fundamentals results alive for up to 24 hours, and a concurrent fetch can reintroduce pre-purge L1 data after the clear response. The endpoint's “wipe every cached market-data store” contract is therefore false (`backend/app/services/cache_service.py:211-219`).
- **Minimum recommendation:** centralize invalidation ownership and use a generation/version or shared gate so DB purge and every dependent L1 cache are invalidated as one logical operation.
- **Test gap:** the purge test seeds only database tables (`backend/tests/test_source_preference_and_cache.py:441-483`); cointegration tests manually clear their private cache rather than exercising the endpoint (`backend/tests/test_bugfix_quant_services.py:160-177`).

#### CORE-008 — User cache settings persist but do not control cache behavior

- **Category / severity:** Recommended change / P2.
- **Location:** `backend/app/api/data.py:157-185`, `backend/app/api/data.py:194-240`, `backend/app/services/data_service.py:73-76`, `backend/app/services/data_service.py:119-135`, `backend/app/services/cache_service.py:16-21`, `backend/app/services/cache_service.py:198-206`.
- **Flow / caller trace:** the API reads/writes `cache_ttl_minutes` and `enable_cache`; DataService instead constructs CacheService from process settings and uses fixed L1/quote TTLs. `GlobalCacheService` uses CacheService's hard-coded 60-minute default. Screener injects a fixed 1,440-minute TTL, while cointegration's route uses the 60-minute default even though its L1 uses 24 hours (`backend/app/api/equity_research.py:220-227`, `backend/app/api/analytics.py:53-55`, `backend/app/api/analytics.py:1968-2015`, `backend/app/services/cointegration_service.py:24-26`). No runtime branch consumes `enable_cache`.
- **Grounded impact:** the UI can persist `enable_cache=false` and a custom TTL while all enabled cache paths continue operating with fixed TTLs. The config endpoint reports settings that do not describe runtime behavior.
- **Minimum recommendation:** either remove unsupported settings from the contract or make one persisted/effective configuration the source for every cache owner.
- **Test gap:** tests assert only GET/PUT persistence (`backend/tests/test_contract_p1_batch.py:176-183`, `backend/tests/test_contract_p1_batch.py:297-308`), not changed expiry/bypass behavior.

#### CORE-009 — The quote response schema silently drops the quote service's fields

- **Category / severity:** Bug / P2.
- **Location:** `backend/app/services/data_service.py:482-497`, `backend/app/services/data_service.py:555-570`, `backend/app/services/alpha_vantage_service.py:326-344`, `backend/app/models/schemas.py:139-150`, `backend/app/api/data.py:370-393`.
- **Flow / caller trace:** DataService emits `52_week_high`/`52_week_low`, currency, exchange, and `is_indian`; Alpha Vantage additionally emits previous close and change percent. The API constructs `StockQuoteResponse(**quote_data)`, but that model names `week_52_high`/`week_52_low` and has no fields for the other extras. Pydantic therefore defaults the 52-week values to null and ignores the extras.
- **Grounded impact:** `/data/quote/{ticker}` loses valid 52-week and market metadata; Alpha Vantage's change fields never reach clients. The service and public response contracts disagree despite the endpoint returning HTTP 200.
- **Minimum recommendation:** use one quote schema or explicit alias mapping for all supported fields.
- **Test gap:** the endpoint test provides mismatched 52-week keys but asserts only `current_price` (`backend/tests/test_api_endpoints.py:68-80`).

#### CORE-010 — Timeseries persistence failure is subsequently recorded as fetch success

- **Category / severity:** Bug / P2.
- **Location:** `backend/app/services/data_service.py:406-420`, `backend/app/services/data_service.py:1060-1118`, `backend/app/services/data_service.py:848-881`.
- **Flow / caller trace:** `_store_timeseries_data` catches every exception, rolls back, and returns `None` on both success and failure. Its caller cannot distinguish the outcomes, then writes the deep-backfill marker and a `success` FetchLog before serving the in-memory fallback. Alpha Vantage logs success before invoking the same swallowing store.
- **Grounded impact:** disk, constraint, or binding failures produce a successful HTTP response, a false success metric, and a backfill marker despite no durable rows. Later requests refetch and can repeatedly report successful persistence that never occurred.
- **Minimum recommendation:** make persistence success observable to the caller and emit success/fetch markers only after the durable write is confirmed.
- **Test gap:** the storage-failure test patches `execute` and only verifies that no exception escapes (`backend/tests/test_coverage_data_service.py:416-422`); it does not assert the subsequent marker/log state or retry behavior.

#### CORE-011 — Older in-flight fetches can overwrite newer L1/quote memo entries

- **Category / severity:** Bug / P2.
- **Location:** `backend/app/services/data_service.py:137-145`, `backend/app/services/data_service.py:292-318`, `backend/app/services/data_service.py:343-352`, `backend/app/services/data_service.py:418-420`, `backend/app/services/data_service.py:465-469`, `backend/app/services/data_service.py:598-602`.
- **Flow / caller trace:** the timestamp is captured before network work, while the class-level cache is written after completion. Two same-ticker requests can finish out of order; the slower older request overwrites the newer frame/quote and receives the older pre-fetch timestamp, so it is considered fresh for the full TTL. There is no per-ticker single-flight or compare-and-set.
- **Grounded impact:** concurrent portfolio/dashboard refreshes can serve stale OHLCV for five minutes or a stale quote for 30 seconds despite a newer successful request.
- **Minimum recommendation:** make writes monotonic by completion generation/version or serialize same-ticker cache publication.
- **Test gap:** L1 sharing is tested sequentially (`backend/tests/test_deep_cache.py:142-157`); no out-of-order completion test exists.

#### CORE-012 — Missing price history becomes undisclosed hard-coded liquidity data

- **Category / severity:** Improvement / P2.
- **Location:** `backend/app/api/analytics.py:2123-2143`, `backend/app/services/india_data_service.py:268-327`.
- **Flow / caller trace:** the API silently omits failed price frames and still calls the liquidity service. When close/volume columns are unavailable, that service invents 50,000 shares of ADV, derives rupee ADV from `last_price`, and assigns Amihud `0.05`; the returned row has no estimate/fallback flag.
- **Grounded impact:** a holding with no usable market history receives apparently measured `adv_30d_*`, days-to-liquidate, and Amihud values. Consumers cannot distinguish an estimate from observed market data.
- **Minimum recommendation:** return null/unknown for unavailable ADV metrics or attach explicit per-position data-quality provenance.
- **Test gap:** the regression suite explicitly expects the 50,000-share default without asserting disclosure (`backend/tests/test_bugfix_providers_05.py:278-292`).

#### CORE-013 — Factor-exposure error routes still encode R² as a real 0.0

- **Category / severity:** Bug / P2.
- **Location:** `backend/app/api/analytics.py:610-623`, `backend/app/api/analytics.py:629-642`, `backend/app/services/analytics_engine.py:1257-1267`.
- **Flow / caller trace:** when allocation or price data is unavailable, the API returns `r_squared: 0.0` and `adjusted_r_squared: 0.0`; the engine's honest empty contract returns `None`. The same route comments identify R² 0 as a misleading market-like outcome (`backend/app/api/analytics.py:644-650`).
- **Grounded impact:** clients cannot distinguish “not computed” from a perfect zero fit, and presentation logic may classify the holding as market-like solely from an error payload.
- **Minimum recommendation:** use null for unavailable R² consistently with the engine and keep the explicit error field.
- **Test gap:** the empty-portfolio test checks only that a `portfolio` object exists (`backend/tests/test_coverage_analytics_extended.py:175-179`).

#### CORE-014 — Unknown volatility model names execute a different model than the response advertises

- **Category / severity:** Bug / P2.
- **Location:** `backend/app/api/analytics.py:452-461`, `backend/app/api/analytics.py:575-589`, `backend/app/services/analytics_engine.py:112-127`, `backend/app/services/analytics_engine.py:593-612`.
- **Flow / caller trace:** the route accepts any string. Forecast silently routes unknown names to GARCH; volatility sizing routes unknown names to EWMA. The forecast route then echoes the user-supplied model in top-level `model` and methodology.
- **Grounded impact:** a request for an unsupported model can return a successful response labelled with the unsupported name while calculations use GARCH or EWMA.
- **Minimum recommendation:** validate against the declared model set and return 4xx for unsupported values, or return and label the effective model consistently.
- **Test gap:** inspected forecast tests use GARCH/EWMA only (`backend/tests/test_analytics_engine.py:72-121`, `backend/tests/test_coverage_analytics_all_routes.py:83-89`).

#### CORE-015 — “Live” allocation weights come from persisted, potentially stale position prices

- **Category / severity:** Bug / P2.
- **Location:** `backend/app/api/analytics.py:178-207`, `backend/app/api/analytics.py:700-760`, `backend/app/api/analytics.py:914-987`, `backend/app/api/analytics.py:990-1057`, `backend/app/api/portfolio.py:83-85`, `backend/app/api/portfolio.py:551-580`, `backend/app/api/portfolio.py:1084-1118`, `backend/app/api/websocket.py:105-133`.
- **Flow / caller trace:** portfolio-backed analytics routes load market values from persisted `market_value` or `quantity * last_price` and do not refresh them. Price refresh occurs only when portfolio read paths run their stale checks; websocket broadcasts read the same persisted values and do not update them.
- **Grounded impact:** direct analytics/stress/sizing/risk requests can use weights from an arbitrarily old portfolio snapshot. Concentration, risk, and sizing then change with when the portfolio page was last opened, not with current cash-equity prices.
- **Minimum recommendation:** either refresh/derive weights as part of the analytics request or explicitly label allocation as a persisted as-of snapshot.
- **Test gap:** allocation tests seed static market values and verify normalization only (`backend/tests/test_coverage_analytics_extended.py:103-149`); no stale-price transition is covered.

#### CORE-016 — Backfilling pre-listing prices creates artificial zero-risk history

- **Category / severity:** Bug / P2.
- **Location:** `backend/app/services/analytics_engine.py:57-62`, `backend/app/services/analytics_engine.py:74-85`, `backend/app/services/analytics_engine.py:937-972`, `backend/app/api/websocket.py:184-204`.
- **Flow / caller trace:** portfolio metrics forward-fill and back-fill every asset, then replace remaining return gaps with 0. A recently listed asset is backfilled to its first observed price before listing, so it contributes zero returns during that interval. Websocket analytics intentionally follows the same fill pattern. Position metrics separately preserve active raw history, but portfolio-level volatility/correlation/drawdown do not.
- **Grounded impact:** pre-listing zero returns understate portfolio variance, covariance, tail risk, and drawdown for current books containing newer listings.
- **Minimum recommendation:** construct portfolio returns from active holdings and explicitly define pre-listing capital (excluded/renormalized/cash) rather than synthetic flat prices.
- **Test gap:** populated analytics fixtures give all assets identical full start dates (`backend/tests/test_coverage_analytics_all_routes.py:17-31`); no mixed-inception portfolio test exists.

#### CORE-017 — Portfolio ticker uniqueness is enforced only by a racy API pre-read

- **Category / severity:** Bug / P2.
- **Location:** `backend/app/models/database.py:11-33`, `backend/app/api/portfolio.py:198-240`, `backend/app/api/portfolio.py:332-350`, `backend/app/api/portfolio.py:450-470`.
- **Flow / caller trace:** the model has a non-unique ticker index but no unique constraint. Single and bulk add perform SELECT-before-INSERT without a database uniqueness guarantee. Two requests can both pass the pre-read and commit the same canonical ticker.
- **Grounded impact:** concurrent adds can persist duplicate positions. Analytics allocation dictionaries overwrite duplicate ticker keys (`backend/app/api/analytics.py:190-200`), so quantities/market values become ambiguous and portfolio totals diverge from allocation.
- **Minimum recommendation:** enforce canonical ticker uniqueness in the database and translate the integrity race into the existing 409 contract.
- **Test gap:** duplicate tests are sequential pre-read scenarios (`backend/tests/test_api_endpoints.py:239-245`, `backend/tests/test_bug_sweep_2026_09.py:100-118`); no concurrent insert test exists.

### P3

#### CORE-018 — Startup does not guarantee the StockTimeseries upsert prerequisite

- **Category / severity:** Recommended change / P3.
- **Location:** `backend/app/models/database.py:39-64`, `backend/app/db/database.py:50-71`, `backend/main.py:52-59`, `backend/migrations/cleanup_duplicates_and_add_constraints.py:126-164`.
- **Flow / caller trace:** new databases receive `UNIQUE(ticker,date)`, but startup `init_db` self-heals only `analytics_cache`. StockTimeseries repair exists only in a manually run migration script. The current live DB already has the required unique index, so this is deployment/restoration robustness rather than a current live-schema failure.
- **Grounded impact:** a legacy or restored database that has not run the one-off script makes every DataService upsert fail its conflict target; CORE-010 then records the fetch as successful despite no durable write.
- **Minimum recommendation:** make schema prerequisites part of an explicit, tested startup/migration contract.
- **Test gap:** the legacy self-heal test covers only analytics cache (`backend/tests/test_bugfix_cache_index_selfheal.py:74-149`), not a legacy StockTimeseries schema.

#### CORE-019 — Expiry/timestamp and exact-date cleanup queries lack matching indexes

- **Category / severity:** Optimization / P3.
- **Location:** `backend/app/models/database.py:70-110`, `backend/app/services/cache_service.py:124-180`, `backend/app/services/india_data_service.py:69-73`, `backend/app/services/india_data_service.py:123-130`.
- **Flow / caller trace:** analytics-cache lookups/upserts match `(ticker,metric_name)`, but expiry delete/count filters only `expires_at`. Recent-total fetch-log stats filter only `timestamp`; existing fetch-log indexes lead with ticker or status. NSE exact-date ingestion wraps `date` in `func.date(...)`, preventing direct use of the natural-key date prefix.
- **Grounded impact:** expired-cache cleanup, one fetch-log statistic, and NSE exact-date existence checks become full scans as local history grows. Severity remains P3 for the current localhost data volume.
- **Minimum recommendation:** add only the missing query-aligned indexes and rewrite exact-date predicates as half-open ranges; remove redundant single-column indexes only after plan verification.
- **Test gap:** tests assert constraints/lifecycle, not `EXPLAIN QUERY PLAN` or growth behavior (`backend/tests/test_p08_cache.py:25-65`, `backend/tests/test_coverage_india_data.py:46-116`).

#### CORE-020 — Bhavcopy ingestion can persist missing values as zero and roll back an entire batch on one conflict

- **Category / severity:** Bug / P3.
- **Location:** `backend/app/services/india_data_service.py:62-114`.
- **Flow / caller trace:** required OHLC/trade fields use `or 0.0`, so explicit nulls become valid stored zeroes. Existing symbols are loaded once but not added to the set during the loop, so duplicate symbols in one input batch also survive to the batch insert. Any unique conflict rolls back every new row and returns zero.
- **Grounded impact:** malformed rows are indistinguishable from genuine zero values, while one duplicate/concurrent conflict discards unrelated valid symbols in the same batch. No production ingestion caller was found under `backend/app`; current read APIs instantiate this service only (`backend/app/api/analytics.py:2030-2087`), which limits current reachability.
- **Minimum recommendation:** reject/quarantine missing required fields, deduplicate the input key, and use conflict-safe per-row persistence.
- **Test gap:** the null-row test expects ingestion to succeed (`backend/tests/test_bugfix_providers_05.py:295-305`), and the concurrent test uses a single row (`backend/tests/test_bugfix_providers_05.py:317-333`), so mixed valid/invalid batches are not covered.

#### CORE-021 — Multi-setting config updates are not atomic

- **Category / severity:** Bug / P3.
- **Location:** `backend/app/api/data.py:194-240`, `backend/app/services/source_preference_service.py:64-78`.
- **Flow / caller trace:** `set_primary_source` commits immediately. The API then writes TTL/enable keys and commits later. A failure after the first helper can return HTTP 500 with `primary_source` already persisted while the remaining requested settings are absent.
- **Grounded impact:** clients cannot safely retry a multi-field update without first reading which settings committed; an HTTP 500 does not identify the partial persisted state.
- **Minimum recommendation:** commit all settings in one transaction or explicitly document and expose partial-update semantics.
- **Test gap:** tests cover successful persistence and validation only (`backend/tests/test_contract_p1_batch.py:297-308`, `backend/tests/test_source_preference_and_cache.py:419-438`).

#### CORE-022 — Successful Alpha Vantage quote fallbacks bypass the quote memo

- **Category / severity:** Optimization / P3.
- **Location:** `backend/app/services/data_service.py:465-469`, `backend/app/services/data_service.py:598-608`, `backend/app/services/alpha_vantage_service.py:204-266`.
- **Flow / caller trace:** only a successful primary/secondary quote is written to `_quote_memo`. A successful Alpha Vantage fallback is returned but not memoized, despite each fallback consuming a rate-limited request and writing a success log.
- **Grounded impact:** repeated dashboard/portfolio refreshes during a primary-vendor outage consume the free AV quota request-by-request and increase rate-limit pressure.
- **Minimum recommendation:** memoize any successful normalized quote, including fallback results, for the same short TTL.
- **Test gap:** the memo regression exercises only a successful yfinance path (`backend/tests/test_bugfix_core_services.py:417-436`).

#### CORE-023 — “Confidence interval” is a fixed ±20% band, not an inferred interval

- **Category / severity:** Improvement / P3.
- **Location:** `backend/app/services/analytics_engine.py:1003-1015`, `backend/app/services/analytics_engine.py:1045-1057`, `backend/app/services/analytics_engine.py:1081-1093`.
- **Flow / caller trace:** GARCH, EGARCH, and EWMA all emit exactly `[forecast * 0.8, forecast * 1.2]`; no residual variance, parameter uncertainty, confidence level, or simulation is used. The public forecast response exposes the field directly (`backend/app/api/analytics.py:575-587`).
- **Grounded impact:** consumers can interpret a fixed heuristic band as a statistical 95%/model interval, overstating available precision.
- **Minimum recommendation:** rename it as a heuristic band or calculate a model-appropriate interval with an explicit confidence contract.
- **Test gap:** tests assert only that the key exists (`backend/tests/test_analytics_engine.py:88-95`), not statistical meaning or level.

## 4. Cache, data, and analytics correctness

| Concern | Observed contract | Assessment | Finding |
|---|---|---|---|
| Canonical vendor cascade | Source preference is validated/upserted and produces exactly two primary/secondary vendors (`backend/app/services/source_preference_service.py:24-85`); Alpha Vantage is appended after those vendors (`backend/app/services/data_service.py:377-390`, `backend/app/services/data_service.py:436-441`). | Correct and clean | — |
| Canonical ticker identity | Bare known Indian scrips gain `.NS`, Yahoo-native symbols pass through, and existing exchange suffixes are retained (`backend/app/services/data_service.py:38-67`). Portfolio canonicalization occurs before persistence (`backend/app/api/portfolio.py:198-205`). | Correct in single-request flow; DB uniqueness still missing | CORE-017 |
| OHLCV durable cache | New-schema upsert is atomic on `(ticker,date)` (`backend/app/models/database.py:60-64`, `backend/app/services/data_service.py:1093-1110`), and the current live DB has the required unique index. | Correct on current schema; failure reporting and legacy startup are not | CORE-010, CORE-018 |
| Vendor adjustment semantics | Yahoo/bfinance retain adjusted close; AV mirrors unadjusted close into the same field (`backend/app/services/data_service.py:805-819`, `backend/app/services/alpha_vantage_service.py:270-297`). | Incorrect cross-vendor overwrite | CORE-002 |
| L1 historical frame cache | Window slicing, deep-history coverage, stale-tail checks, and ticker keys are explicit (`backend/app/services/data_service.py:182-216`, `backend/app/services/data_service.py:347-375`). | Correct single-request behavior; out-of-order publication can overwrite | CORE-011 |
| Quote memo | Canonical ticker key and 30-second TTL are present (`backend/app/services/data_service.py:119-135`, `backend/app/services/data_service.py:465-469`). | Correct primary path; fallback bypasses memo | CORE-022 |
| Analytics-cache key/upsert | Unique `(ticker,metric_name)` plus ON CONFLICT prevents duplicate rows (`backend/app/models/database.py:83-87`, `backend/app/services/cache_service.py:62-89`). | Correct and clean | — |
| Cache purge | DB tables and selected L1 caches are cleared while portfolio truth is preserved (`backend/app/services/cache_service.py:211-287`). | Incomplete and racy across service-owned memos/in-flight fetches | CORE-007 |
| Cache configuration | Settings persist and round-trip (`backend/app/api/data.py:157-240`). | Persistence works; runtime behavior ignores values | CORE-008 |
| Portfolio return construction | Supplied weights normalize, but absent priced columns are not redistributed (`backend/app/services/analytics_engine.py:64-75`, `backend/app/services/analytics_engine.py:837-844`). | Incorrect under partial data | CORE-001 |
| Mixed-inception returns | Portfolio paths backfill/zero-fill; factor position regressions preserve active history (`backend/app/services/analytics_engine.py:57-62`, `backend/app/services/analytics_engine.py:1120-1158`). | Portfolio risk is biased low before listing | CORE-016 |
| Factor regression | Benchmark dates are intersected, active non-null returns are used, and genuine zero-return days remain (`backend/app/services/analytics_engine.py:1120-1158`). | Clean for position-level factor exposure | — |
| Risk-score factor leg | Benchmark regression runs, but without current portfolio weights (`backend/app/services/analytics_engine.py:761-763`, `backend/app/services/analytics_engine.py:1166-1183`). | Incorrect allocation basis | CORE-005 |
| GARCH/EGARCH horizon | Model forecast and square-root horizon adjustment are both applied (`backend/app/services/analytics_engine.py:994-1008`, `backend/app/services/analytics_engine.py:1036-1050`). | Incorrect h-day tail loss | CORE-004 |
| EWMA horizon | One-step volatility is flat and is scaled by `sqrt(h/252)` (`backend/app/services/analytics_engine.py:1062-1092`). | Correct and clean | — |
| Concentration | HHI, effective positions, diversification, and single-holding 0% are computed from normalized weights (`backend/app/services/analytics_engine.py:209-249`). | Correct and clean | — |
| Inverse-volatility sizing | Weights are proportional to `1/sigma`, with target-volatility cash/leverage scaling disclosed (`backend/app/services/analytics_engine.py:634-696`). | Correct and clean | — |
| Liquidity | Market cap can substitute for turnover, and instrument categories are labelled liquidation days (`backend/app/services/analytics_engine.py:302-326`, `backend/app/services/analytics_engine.py:354-368`). | Incorrect for execution/position-size interpretation | CORE-006, CORE-012 |
| Quote public schema | Service keys and response-model keys differ (`backend/app/services/data_service.py:489-490`, `backend/app/models/schemas.py:147-148`, `backend/app/api/data.py:379-387`). | Silent field loss | CORE-009 |
| Position metadata persistence | Quote sector/industry are nullable while ORM columns are not (`backend/app/services/data_service.py:487-488`, `backend/app/models/database.py:26-27`, `backend/app/api/portfolio.py:233-239`). | Valid quote can fail position commit | CORE-003 |

### 4.1 DB indexes vs observed query patterns

| Table / query | Declared or live index | Assessment |
|---|---|---|
| `stock_timeseries WHERE ticker=? AND date BETWEEN ... ORDER BY date` (`backend/app/services/data_service.py:972-987`) | `UNIQUE(ticker,date)` plus `ix_ticker_date` (`backend/app/models/database.py:60-64`); live index confirmed | Matched |
| Full ticker history ordered by date (`backend/app/services/data_service.py:256-266`) | `ix_ticker_date` (`backend/app/models/database.py:61-64`) | Matched |
| Coverage `min/max/count WHERE ticker=?` (`backend/app/services/data_service.py:218-246`) | Ticker index and composite prefix (`backend/app/models/database.py:43-45`, `backend/app/models/database.py:61-64`) | Matched |
| Latest source by ticker/date (`backend/app/api/data.py:313-323`) | `ix_ticker_date` can satisfy ticker and descending date | Matched |
| Integrity grouping by `(ticker,date)` (`backend/app/services/data_service.py:1234-1267`) | Unique natural key | Matched |
| Analytics cache lookup/upsert by `(ticker,metric_name)` (`backend/app/services/cache_service.py:23-89`) | Unique constraint and `ix_ticker_metric` (`backend/app/models/database.py:83-87`) | Matched |
| Analytics cache expiry delete/count (`backend/app/services/cache_service.py:124-164`) | No `expires_at` index; live metadata confirmed absence | Gap — CORE-019 |
| Recent total fetch logs by `timestamp` (`backend/app/services/cache_service.py:166-173`) | Indexes lead with ticker or status (`backend/app/models/database.py:106-110`); no timestamp-only index | Gap — CORE-019 |
| Recent success by `(status,timestamp)` (`backend/app/services/cache_service.py:174-181`) | `ix_status_timestamp` | Matched |
| Institutional flows date cutoff/order (`backend/app/services/india_data_service.py:173-183`) | Unique `(date,category)` (`backend/app/models/database.py:159-164`) | Matched |
| Exact-day bhavcopy/flow existence checks (`backend/app/services/india_data_service.py:69-73`, `backend/app/services/india_data_service.py:123-130`) | Natural-key date is second in bhavcopy unique key; both queries wrap date in `func.date` | Gap — CORE-019 |
| Delivery anomalies by symbol/date (`backend/app/services/india_data_service.py:210-217`) | `UNIQUE(symbol,date)` (`backend/app/models/database.py:136-142`) | Matched |
| App-setting key read/upsert (`backend/app/services/source_preference_service.py:51-76`) | Primary key `key` (`backend/app/models/database.py:218-224`) | Matched |
| Portfolio ticker existence/allocation (`backend/app/api/portfolio.py:203-205`, `backend/app/api/analytics.py:185-207`) | Non-unique ticker index only (`backend/app/models/database.py:15-17`) | Query matched; uniqueness gap — CORE-017 |

## 5. Test gaps tied to audited risks

1. **Partial-data portfolio math:** no test removes a priced column while retaining its weight or introduces a mid-sample listing into portfolio-level risk (`backend/tests/test_analytics_engine.py:296-305`, `backend/tests/test_coverage_analytics_all_routes.py:17-31`). Covers CORE-001/016.
2. **Adjusted/unadjusted persistence:** no test starts with adjusted rows, invokes AV fallback, and asserts the adjusted series is not overwritten (`backend/tests/test_alpha_vantage.py:73-77`, `backend/tests/test_source_preference_and_cache.py:213-235`). Covers CORE-002.
3. **Nullable quote metadata:** all position-add quote doubles provide sector/industry (`backend/tests/test_api_endpoints.py:135-143`). Covers CORE-003.
4. **Forecast math and model identity:** GARCH tests check key presence, not h-day VaR arithmetic or unsupported model names (`backend/tests/test_analytics_engine.py:72-121`). Covers CORE-004/014/023.
5. **Actual allocation in factor risk:** the benchmark test only proves the factor leg is populated (`backend/tests/test_quant_math_p1_batch.py:269-282`). Covers CORE-005.
6. **Liquidity boundaries:** no zero-turnover mega-cap, tiny holding, or missing-history disclosure test exists (`backend/tests/test_analytics_engine.py:167-193`, `backend/tests/test_bugfix_providers_05.py:278-292`). Covers CORE-006/012.
7. **Cache invalidation/configuration:** purge tests cover DB rows, not service-owned memos or in-flight fetch publication; config tests cover persistence, not behavior (`backend/tests/test_source_preference_and_cache.py:419-483`, `backend/tests/test_contract_p1_batch.py:176-183`, `backend/tests/test_contract_p1_batch.py:297-308`). Covers CORE-007/008/011/022.
8. **Persistence truth and schema prerequisites:** storage failure tests do not assert caller-visible success/marker state, and legacy self-heal covers only analytics cache (`backend/tests/test_coverage_data_service.py:416-422`, `backend/tests/test_bugfix_cache_index_selfheal.py:74-149`). Covers CORE-010/018.
9. **Public contract nullability/model identity:** the quote test asserts only price, and factor empty-state tests do not assert R² null (`backend/tests/test_api_endpoints.py:68-80`, `backend/tests/test_coverage_analytics_extended.py:175-179`). Covers CORE-009/013.
10. **Price/weight freshness and portfolio uniqueness:** allocation tests use static values, and duplicate tests are sequential (`backend/tests/test_coverage_analytics_extended.py:103-149`, `backend/tests/test_api_endpoints.py:239-245`). Covers CORE-015/017.
11. **Index/query plans and NSE mixed batches:** no query-plan assertions or mixed valid/duplicate/null bhavcopy batch exists (`backend/tests/test_p08_cache.py:25-65`, `backend/tests/test_bugfix_providers_05.py:295-333`). Covers CORE-019/020.
12. **Multi-setting rollback and fixed confidence bands:** no injected failure between config commits and no statistical/label contract test exists (`backend/tests/test_contract_p1_batch.py:297-308`, `backend/tests/test_analytics_engine.py:88-95`). Covers CORE-021/023.

The focused suite's 178 passing tests demonstrate current happy-path and prior-regression coverage; they do not exercise the adversarial cases above.

## 6. Explicit clean areas and limitations

### Clean areas

- Source preference is constrained to bfinance/yfinance, normalized, persisted atomically on one key, and converted to a deterministic two-vendor order (`backend/app/services/source_preference_service.py:24-85`).
- Vendor network I/O is consistently moved off the event loop for historical downloads, quote access, validation, corporate actions, arch fitting, Alpha Vantage requests, and cointegration statistics (`backend/app/services/data_service.py:598-608`, `backend/app/services/data_service.py:715-721`, `backend/app/services/data_service.py:748-752`, `backend/app/services/data_service.py:829-837`, `backend/app/services/analytics_engine.py:987-992`, `backend/app/services/alpha_vantage_service.py:227-232`, `backend/app/services/cointegration_service.py:421-431`).
- Batch historical fetches serialize database work sharing one AsyncSession while network calls remain concurrent (`backend/app/services/data_service.py:78-83`, `backend/app/services/data_service.py:356-369`, `backend/app/services/data_service.py:406-415`).
- Concentration uses true HHI and `N_eff = 1/HHI`; a single holding renders 0% diversification (`backend/app/services/analytics_engine.py:216-248`).
- Inverse-volatility sizing uses true `1/sigma` relative weights and explicitly reports cash or leverage (`backend/app/services/analytics_engine.py:634-696`).
- Analytics-cache writes use an atomic unique-key upsert, and startup repairs legacy duplicate analytics keys (`backend/app/services/cache_service.py:62-89`, `backend/app/db/database.py:63-71`).
- Cache purge preserves portfolio-position truth while deleting only market-data tables (`backend/app/services/cache_service.py:211-255`).
- Factor position regressions preserve genuine 0% return days and use active trading dates rather than NaN-filled pre-listing observations (`backend/app/services/analytics_engine.py:1120-1158`).
- API-level annualization gates suppress unstable annualized outputs below 30 covered trading days (`backend/app/utils/holdings.py:24-27`, `backend/app/utils/holdings.py:202-213`).
- Alpha Vantage logs expose only the final four key characters, not complete credentials (`backend/app/services/alpha_vantage_service.py:158-169`).
- No missing localhost authentication or horizontal-scale issue was promoted to a finding, consistent with the configured loopback host (`backend/app/config.py:23-25`, `backend/main.py:173-180`).

### Limitations

- No live vendor request was made; provider behavior is bounded by the mocked seams and source contracts (`backend/app/services/data_service.py:779-846`, `backend/app/services/alpha_vantage_service.py:204-347`).
- No frontend, broker integration, scheduled ingestion worker, or deployment orchestration outside the inspected backend files was reviewed. The absence of a production bhavcopy ingestion caller is therefore limited to `backend/app` and the inspected backend migrations/tests.
- `backend/app/api/portfolio.py` was traced only over lines 1-619 and 1040-1118; unrelated CRUD operations in lines 620-1039 were not assigned findings.
- The live SQLite database was queried for index metadata only; row contents, duplication state, and portfolio truth were not inspected.
- The live database already has the StockTimeseries unique index, so CORE-018 is a startup/restoration robustness recommendation, not a claim that the current database is broken.
- No P0 issue was found; that is not a guarantee that uninspected callers cannot create one.
