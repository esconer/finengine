# Line-by-line audit: market-data/provider services

## 1. Scope and method

This is a documentation-only, static audit of cash-equity market-data, company-reference, research, screener, India-microstructure, FX, benchmark, and cache services. Out-of-scope instruments and trading recommendations are not analyzed. I read every line of all first-party files under `backend/app/services/`; the inventory below reconciles to 22 files and 7,924 lines. The report does not re-audit the core analytics/quant algorithms: those files were checked only for provider-boundary, cache, input, freshness, and contract defects.

For contracts, I read the provider callers and dependency boundaries in `backend/app/api/data.py:1-506`, `backend/app/api/equity_research.py:1-257`, `backend/app/api/portfolio.py:1-1118`, `backend/app/api/analytics.py:1-2255`, `backend/app/api/websocket.py:1-358`, `backend/main.py:1-181`, `backend/app/config.py:1-79`, `backend/app/models/database.py:1-227`, `backend/app/models/schemas.py:1-581`, `backend/app/db/database.py:1-130`, and `backend/app/utils/logger.py:1-55`. Provider-focused tests were read for coverage and gaps, including `backend/tests/test_alpha_vantage.py:1-130`, `backend/tests/test_coverage_alpha_vantage.py:1-317`, `backend/tests/test_bugfix_providers_05.py:1-356`, `backend/tests/test_coverage_data_service.py:1-476`, `backend/tests/test_data_services.py:1-176`, `backend/tests/test_source_preference_and_cache.py:1-483`, `backend/tests/test_screener_cache.py:1-145`, `backend/tests/test_p09_screener.py:1-125`, `backend/tests/test_equity_research_and_screens.py:1-356`, `backend/tests/test_bugfix_equity_research_503.py:1-23`, `backend/tests/test_coverage_india_data.py:1-154`, `backend/tests/test_coverage_services_and_api.py:1-340`, `backend/tests/test_contract_p1_batch.py:1-320`, `backend/tests/test_bugfix_core_services.py:1-449`, `backend/tests/test_wave2_transition.py:1-195`, `backend/tests/test_api_endpoints.py:1-464`, `backend/tests/test_p07_ticker.py:1-58`, and `backend/tests/test_deep_cache.py:1-275`.

Severity is applied to the observed contract consequence: P0 means an immediately demonstrated destructive or secret-exposure event; P1 means silent wrong market data, a core fallback failure, or a materially false API result; P2 means degraded availability, edge-case correctness, observability, or an exposed-but-unwired contract; P3 means a low-impact input-validation/documentation defect. No P0 finding was confirmed. The read-only lint pass over the inspected provider/API/model scope passed: `uv run ruff check app/services app/api/data.py app/api/equity_research.py app/config.py app/models/database.py app/models/schemas.py` reported `All checks passed!`.

## 2. Exhaustive service inventory

| File | Lines / count | Provider-audit status | Findings or clean evidence |
|---|---:|---|---|
| `backend/app/services/alpha_vantage_service.py` | 1-358 (358) | Reviewed | `DATA-005`, `DATA-017`, `DATA-024`; the symbol bridge is explicit at `backend/app/services/alpha_vantage_service.py:45-55`, and HTTP errors are handled at `backend/app/services/alpha_vantage_service.py:227-266`. |
| `backend/app/services/ai_dossier_service.py` | 1-120 (120) | Reviewed | `DATA-023`, `DATA-027`; all dossier/prompt paths are single-source bfinance calls at `backend/app/services/ai_dossier_service.py:32-110`, with runtime format input coming from the API at `backend/app/api/equity_research.py:173-193`. |
| `backend/app/services/analytics_engine.py` | 1-1345 (1345) | Clean for provider scope | It accepts supplied price/returns frames and has no vendor/cache/API boundary at `backend/app/services/analytics_engine.py:29-91,129-190`; quant algorithm findings are intentionally out of scope. |
| `backend/app/services/benchmark_service.py` | 1-96 (96) | Clean for provider scope | It delegates `^NSEI` to `DataService` and slices cached close data at `backend/app/services/benchmark_service.py:45-96`; the default-date issue is tracked under `DATA-026` rather than duplicated. |
| `backend/app/services/cache_service.py` | 1-287 (287) | Reviewed | `DATA-006`, `DATA-014`; atomic analytics upsert/rollback is present at `backend/app/services/cache_service.py:54-95`, while the purge path is at `backend/app/services/cache_service.py:211-287`. |
| `backend/app/services/company_data_service.py` | 1-389 (389) | Reviewed | `DATA-011`, `DATA-012`, `DATA-013`, `DATA-014`, `DATA-015`; fundamentals/statements/insider paths are at `backend/app/services/company_data_service.py:104-256`, `266-351`, and `353-379`. |
| `backend/app/services/correlation_service.py` | 1-150 (150) | Clean for provider scope | It accepts an already-built returns frame and has no vendor, cache, or external I/O boundary at `backend/app/services/correlation_service.py:17-67`. |
| `backend/app/services/cointegration_service.py` | 1-467 (467) | Clean for provider scope | It accepts price series and owns only analytics caching at `backend/app/services/cointegration_service.py:153-268` and `271-467`; quant algorithm findings are intentionally out of scope. |
| `backend/app/services/currency_service.py` | 1-260 (260) | Reviewed | `DATA-018`, `DATA-019`; rate caching/fallback is at `backend/app/services/currency_service.py:19-68` and `148-194`, formatting at `88-124`. |
| `backend/app/services/data_service.py` | 1-1293 (1293) | Reviewed | `DATA-001`, `DATA-002`, `DATA-003`, `DATA-006`, `DATA-007`, `DATA-008`, `DATA-009`, `DATA-010`, `DATA-011`, `DATA-015`, `DATA-016`, `DATA-025`, `DATA-026`; the vendor/cache/quote contract is at `backend/app/services/data_service.py:320-909`, normalization/storage at `911-1174`. |
| `backend/app/services/equity_research_service.py` | 1-302 (302) | Reviewed | `DATA-023`; all five research operations use `bf.Ticker` and thread offload at `backend/app/services/equity_research_service.py:35-292`. |
| `backend/app/services/india_data_service.py` | 1-335 (335) | Reviewed | `DATA-004`, `DATA-020`, `DATA-021`; ingestion is at `backend/app/services/india_data_service.py:55-171`, read/anomaly/liquidity paths at `173-335`. |
| `backend/app/services/indicators_service.py` | 1-242 (242) | Clean for provider scope | It consumes `DataService` data, normalizes it, and rejects stale frames at `backend/app/services/indicators_service.py:141-202`; upstream provider defects remain in `DATA-001`/`DATA-002`. |
| `backend/app/services/monte_carlo_service.py` | 1-231 (231) | Clean for provider scope | It accepts a portfolio return series and performs simulation only at `backend/app/services/monte_carlo_service.py:43-230`; no vendor/cache/API boundary is present. |
| `backend/app/services/optimization_service.py` | 1-330 (330) | Clean for provider scope | It accepts a returns frame and solves from that input at `backend/app/services/optimization_service.py:286-330`; quant implementation is excluded. |
| `backend/app/services/regime_service.py` | 1-353 (353) | Clean for provider scope | Its provider boundary is the `BenchmarkService` adapter at `backend/app/services/regime_service.py:18-22` and `299-320`; classification logic is not re-audited here. |
| `backend/app/services/screener_service.py` | 1-364 (364) | Reviewed | `DATA-022`, `DATA-023`; symbol/cache/debt paths are at `backend/app/services/screener_service.py:34-53`, `112-175`, `176-275`, and `276-351`. |
| `backend/app/services/source_preference_service.py` | 1-85 (85) | Reviewed; store itself clean | Validation/default/upsert/order logic is sound at `backend/app/services/source_preference_service.py:24-85`; the unwired runtime effect is `DATA-006`/`DATA-007`. |
| `backend/app/services/tail_risk_service.py` | 1-389 (389) | Clean for provider scope | It consumes a returns frame and returns analytics at `backend/app/services/tail_risk_service.py:234-389`; no market-data provider boundary is present. |
| `backend/app/services/volatility_service.py` | 1-330 (330) | Clean for provider scope | It accepts a returns series and has no external I/O at `backend/app/services/volatility_service.py:19-330`; quant implementation is excluded. |
| `backend/app/services/backtest_service.py` | 1-195 (195) | Clean for provider scope | It accepts a wide returns frame and has no vendor/cache boundary at `backend/app/services/backtest_service.py:18-195`; quant implementation is excluded. |
| `backend/app/services/__init__.py` | 1-3 (3) | Clean | Package docstring only at `backend/app/services/__init__.py:1-3`. |

**Inventory reconciliation:** 22 files, 7,924 lines. The inventory includes 12 provider/research/cache/data-consumer files, 9 analytics/quant files, and `__init__.py`.

## 3. Deduplicated findings

### Severity/category totals

| Severity | Count |
|---|---:|
| P0 | 0 |
| P1 | 9 |
| P2 | 17 |
| P3 | 1 |
| **Total** | **27** |

| Primary category | Count | Finding IDs |
|---|---:|---|
| Fallback/source precedence | 7 | `DATA-001`, `DATA-007`, `DATA-009`, `DATA-012`, `DATA-013`, `DATA-017`, `DATA-023` |
| Symbol mapping | 2 | `DATA-005`, `DATA-008` |
| Time/calendar/timezone | 3 | `DATA-002`, `DATA-021`, `DATA-026` |
| Data quality/partial data | 4 | `DATA-003`, `DATA-004`, `DATA-019`, `DATA-020` |
| Cache/config | 2 | `DATA-006`, `DATA-014` |
| API schema/error contract | 4 | `DATA-010`, `DATA-011`, `DATA-022`, `DATA-027` |
| Retry/async/rate-limit behavior | 2 | `DATA-015`, `DATA-016` |
| Currency/normalization | 1 | `DATA-018` |
| Security/redaction | 1 | `DATA-024` |
| Observability/provenance | 1 | `DATA-025` |
| **Total** | **27** | |

### DATA-001 — P1 — Fallback accepts incomplete or stale frames

- **Evidence:** `_download_with_timeout` returns the first non-empty vendor frame without checking the requested window at `backend/app/services/data_service.py:799-827`. `fetch_historical_data` only rejects an empty normalized frame, stores it, writes a backfill marker, and returns the slice at `backend/app/services/data_service.py:390-420`. `_serve_backfilled_slice` can return an empty or partial slice rather than continuing the cascade at `backend/app/services/data_service.py:302-318`. The L1 path checks bounds but not row density at `backend/app/services/data_service.py:205-214`; the SQLite path applies its sparse-data check only when the requested span exceeds 60 days at `backend/app/services/data_service.py:992-1025`.
- **Affected flow/callers:** historical data is consumed by `/api/v1/data/{ticker}` at `backend/app/api/data.py:271-303`, batch consumers at `backend/app/services/data_service.py:610-673`, and analytics liquidity/risk consumers at `backend/app/api/analytics.py:2126-2134` and `backend/app/api/analytics.py:1013-1021`.
- **Grounded impact:** a non-empty frame outside the requested interval suppresses the secondary vendor and Alpha Vantage, while a short sparse cache can be returned as a successful response. The cache marker is written after that acceptance path at `backend/app/services/data_service.py:406-415` and `1176-1195`.
- **Minimum recommendation:** make requested-window coverage/freshness an acceptance predicate; continue the vendor cascade when the resulting slice is empty or materially sparse, and return an explicit partial-coverage status.
- **Test gap:** existing tests cover all-vendor failure, malformed columns, and a deliberately late cache start at `backend/tests/test_coverage_data_service.py:113-140`, `backend/tests/test_bugfix_core_services.py:333-370`, and `backend/tests/test_deep_cache.py:159-178`; none asserts that a non-empty out-of-window or sparse short-window frame rejects the vendor and reaches the next source.

### DATA-002 — P1 — End-date boundary handling is inconsistent and excludes the SQLite end date

- **Evidence:** the SQLite cache query compares the `DateTime` column directly with caller strings at `backend/app/services/data_service.py:980-984`. The test suite explicitly records the resulting end-exclusive behavior at `backend/tests/test_deep_cache.py:167-178`. Alpha Vantage applies an inclusive `day_dt <= end_dt` filter at `backend/app/services/alpha_vantage_service.py:284-288`, while both primary vendors receive the raw `end` string at `backend/app/services/data_service.py:805-818`.
- **Affected flow/callers:** every cached historical read at `backend/app/services/data_service.py:356-375`, every vendor download at `backend/app/services/data_service.py:381-420`, and the data API response at `backend/app/api/data.py:302-360`.
- **Grounded impact:** the same requested end date can be present in an Alpha result, absent from a SQLite cache result, and interpreted according to each vendor's endpoint semantics; the cache path can omit the final requested trading date.
- **Minimum recommendation:** normalize all start/end bounds to typed timestamps and choose one documented interval convention across SQLite, bfinance, yfinance, and Alpha Vantage.
- **Test gap:** the current deep-cache tests only assert `max <= end` at `backend/tests/test_deep_cache.py:82-85`; no test seeds and requires the exact end-date row through every tier.

### DATA-003 — P1 — OHLCV validation is advisory, so invalid rows can be persisted

- **Evidence:** `_store_timeseries_data` logs `validation_errors` but proceeds to build records and execute the upsert at `backend/app/services/data_service.py:1066-1110`. `_validate_timeseries_data` identifies negative values, invalid OHLC relationships, extreme moves, duplicate dates, and nulls at `backend/app/services/data_service.py:1120-1174`; the database model declares only non-null columns and no corresponding check constraints at `backend/app/models/database.py:39-64`.
- **Affected flow/callers:** all primary and Alpha Vantage historical writes at `backend/app/services/data_service.py:406-415` and `868-877`, and subsequent analytics reads at `backend/app/api/analytics.py:148-175`.
- **Grounded impact:** a non-null but invalid row can be written and later returned as fresh market data; the validation warning is not an enforcement boundary.
- **Minimum recommendation:** reject or quarantine invalid rows before upsert, and add database constraints for the invariants that must hold at rest.
- **Test gap:** tests call `_validate_timeseries_data` directly and verify warning strings at `backend/tests/test_coverage_data_service.py:424-448`, but the storage tests use only valid frames at `backend/tests/test_coverage_data_service.py:380-414`; no test proves invalid rows are not persisted.

### DATA-004 — P1 — NSE bhavcopy ingestion turns missing data into zero and loses corrections/whole batches on conflict

- **Evidence:** missing OHLC/trade fields are converted to `0.0`/`0` at `backend/app/services/india_data_service.py:81-98`. Existing symbols are skipped rather than updated at `backend/app/services/india_data_service.py:69-79`. Any `IntegrityError` rolls back the entire `new_entities` batch and returns `0` at `backend/app/services/india_data_service.py:101-114`. The natural key is `(symbol, date)` at `backend/app/models/database.py:116-145`. The institutional-flow conflict recovery queries exact `date_dt`, although the initial lookup uses `func.date`, at `backend/app/services/india_data_service.py:123-171`.
- **Affected flow/callers:** bhavcopy/flow writers use these methods at `backend/app/services/india_data_service.py:62-171`; the read-side India endpoints consume the resulting tables at `backend/app/api/analytics.py:2030-2087`.
- **Grounded impact:** a null provider field becomes a valid-looking zero row, a corrected same-day record is not applied, and one duplicate/conflict can discard all otherwise new rows in that commit.
- **Minimum recommendation:** reject missing OHLC fields, upsert corrections on the natural key, normalize all dates to one date-only key, and make conflict recovery preserve the non-conflicting rows.
- **Test gap:** current tests cover idempotent insertion, a single simulated race, and that a null record does not raise at `backend/tests/test_coverage_india_data.py:46-73` and `backend/tests/test_bugfix_providers_05.py:297-333`; they do not cover correction, duplicate symbols within one payload, mixed conflict batches, or the resulting stored zero values.

### DATA-005 — P1 — Alpha Vantage bridges every NSE symbol to BSE without identity verification

- **Evidence:** the service documentation states that `.NS` and `.BO` both map to `.BSE` and explicitly notes that exchange ticker letters can differ at `backend/app/services/alpha_vantage_service.py:18-21`; the implementation performs that unconditional mapping at `backend/app/services/alpha_vantage_service.py:45-55`. A successful Alpha frame is then stored under the caller's normalized ticker by the DataService at `backend/app/services/data_service.py:848-881`.
- **Affected flow/callers:** historical and quote fallback invoked at `backend/app/services/data_service.py:436-441` and `883-909`, which feed `/api/v1/data/{ticker}` and `/api/v1/data/quote/{ticker}` at `backend/app/api/data.py:302-387`.
- **Grounded impact:** when the BSE symbol is not the same listing identity as the requested NSE symbol, a successful fallback is stored and presented under the requested `.NS` identity without a mapping/identity check.
- **Minimum recommendation:** maintain an explicit symbol mapping or only accept a BSE fallback after identity validation; otherwise leave the requested NSE symbol unavailable.
- **Test gap:** the existing tests assert only simple string conversions at `backend/tests/test_alpha_vantage.py:61-65` and `backend/tests/test_coverage_alpha_vantage.py:31-36`; they do not test a symbol whose NSE/BSE identifiers differ or verify the identity of the returned instrument.

### DATA-006 — P1 — Persisted cache controls are not connected to the DataService runtime

- **Evidence:** the API reads and reports `cache_ttl_minutes` and `enable_cache` at `backend/app/api/data.py:157-185` and persists both at `backend/app/api/data.py:194-240`. `DataService` constructs `CacheService` from process settings at `backend/app/services/data_service.py:70-76`, then unconditionally checks L1 and SQLite caches at `backend/app/services/data_service.py:347-376`; that path contains no read of the persisted `enable_cache` or TTL setting.
- **Affected flow/callers:** configuration is changed through `/api/v1/data/config` at `backend/app/api/data.py:194-246`, but historical and quote fetches use the runtime settings at `backend/app/services/data_service.py:320-376` and `449-604`.
- **Grounded impact:** the API can report `enable_cache=false` or a changed TTL while the fetch path continues to use the cache and the environment-derived TTL.
- **Minimum recommendation:** either wire the persisted settings into each request-scoped `DataService`/cache instance or remove the exposed controls; clear memo caches when the setting changes.
- **Test gap:** tests verify only API persistence/round-trip at `backend/tests/test_source_preference_and_cache.py:419-438` and `backend/tests/test_contract_p1_batch.py:177-183,300-308`; they do not assert that a subsequent fetch bypasses or changes cache behavior.

### DATA-007 — P2 — Source preference is bypassed by cache hits

- **Evidence:** the ticker-keyed L1 lookup occurs before source-order resolution at `backend/app/services/data_service.py:347-352`, while source order is resolved only after the L1 and SQLite paths at `backend/app/services/data_service.py:356-379`. The L1 key is ticker identity only and has no primary-source value at `backend/app/services/data_service.py:119-135,191-205`; quote memoization likewise precedes source resolution at `backend/app/services/data_service.py:465-472`. The API permits switching the primary source at `backend/app/api/data.py:214-219`.
- **Affected flow/callers:** historical and quote requests after a source switch at `backend/app/api/data.py:302-333,370-387`; batch requests resolve one order at `backend/app/services/data_service.py:637-640` but can still hit pre-existing L1/DB data.
- **Grounded impact:** a request made after changing the preference can receive the previous vendor's data until L1/DB freshness rules expire; the preference is honored only on a cache miss.
- **Minimum recommendation:** invalidate or version caches on preference changes, or include the resolved source order in cache identity.
- **Test gap:** the cascade tests force refresh or start with a cold cache at `backend/tests/test_source_preference_and_cache.py:166-235`; no test changes the preference after a warm fetch and asserts the new source is consulted.

### DATA-008 — P2 — Canonical symbol coverage is narrower than the accepted ticker contract

- **Evidence:** `canonical_ticker` adds `.NS` only for the 20-name `_BARE_INDIAN_SCRIPS` set at `backend/app/services/data_service.py:31-67`; numeric BSE input is therefore not canonicalized to `.BO`. The screener explicitly maps numeric symbols to `.BO` and other bare symbols to `.NS` at `backend/app/services/screener_service.py:39-46`. The portfolio schema accepts digits and punctuation at `backend/app/models/schemas.py:11-29`, and the portfolio API documents numeric BSE codes as valid at `backend/app/api/portfolio.py:30-33,300-305`.
- **Affected flow/callers:** validation, quote, historical, research, and portfolio storage all consume the DataService canonical form at `backend/app/services/data_service.py:90-112` and `backend/app/api/portfolio.py:176-213`.
- **Grounded impact:** an accepted bare symbol outside the allowlist remains bare, and a bare numeric BSE code remains numeric; the same logical symbol can therefore be requested through different vendor paths or rejected by validation.
- **Minimum recommendation:** require an explicit exchange for ambiguous input or add a region-aware numeric/BSE and broader Indian-symbol mapping shared by all services.
- **Test gap:** the existing regression test explicitly locks unknown bare symbols to pass-through and only tests already suffixed BSE codes at `backend/tests/test_p07_ticker.py:17-34`; no end-to-end test uses a valid non-popular Indian symbol or bare numeric BSE code.

### DATA-009 — P2 — Ticker validation omits the configured Alpha Vantage fallback

- **Evidence:** `validate_ticker` iterates only the two-source order returned by `source_order_for` at `backend/app/services/data_service.py:675-731`. Alpha Vantage fallback is implemented separately for historical data and quotes at `backend/app/services/data_service.py:848-909`, but is not called by validation. Portfolio creation invokes validation before quote retrieval at `backend/app/api/portfolio.py:176-218`.
- **Affected flow/callers:** `/api/v1/portfolio/add` and bulk-add at `backend/app/api/portfolio.py:176-185,320-330`, plus `/api/v1/data/validate` at `backend/app/api/data.py:448-466`.
- **Grounded impact:** when bfinance and yfinance are unavailable but Alpha is configured and can return a quote/history, validation returns false and portfolio creation rejects the symbol before the working fallback is reached.
- **Minimum recommendation:** add a bounded Alpha validation probe or explicitly define validation as a two-vendor contract in the API and UI.
- **Test gap:** validation tests mock only bfinance/yfinance at `backend/tests/test_coverage_data_service.py:199-216`; no test enables Alpha and verifies the validation result after both primary sources fail.

### DATA-010 — P2 — Quote and historical response identity/schema drift

- **Evidence:** DataService and Alpha return `52_week_high`/`52_week_low` at `backend/app/services/data_service.py:482-496,555-570` and `backend/app/services/alpha_vantage_service.py:327-344`; `StockQuoteResponse` declares `week_52_high`/`week_52_low` at `backend/app/models/schemas.py:139-151`, and the route constructs that model at `backend/app/api/data.py:370-387`. Historical responses use the raw request ticker at `backend/app/api/data.py:341-360`, while DataService normalizes the frame and stored ticker at `backend/app/services/data_service.py:343-375,951-960`.
- **Affected flow/callers:** `/api/v1/data/quote/{ticker}` and `/api/v1/data/{ticker}` at `backend/app/api/data.py:271-393`; downstream analytics and portfolio code consumes normalized DataService results at `backend/app/api/analytics.py:148-175` and `backend/app/api/portfolio.py:574-579`.
- **Grounded impact:** the quote provider's 52-week keys do not match the declared response fields, and a bare known-Indian request can return a response identity different from the normalized series stored and fetched.
- **Minimum recommendation:** define one canonical field-name set and construct response records with the same canonical ticker used for cache/vendor operations.
- **Test gap:** the quote API test supplies 52-week keys but asserts only `current_price` at `backend/tests/test_api_endpoints.py:69-80`; no exact 52-week or bare-known-Indian response identity assertion exists.

### DATA-011 — P1 — Provider outages are collapsed into not-found or client-error responses

- **Evidence:** `fetch_historical_data` catches all exceptions and returns `None` at `backend/app/services/data_service.py:422-447`; `/api/v1/data/{ticker}` maps any `None` to 404 at `backend/app/api/data.py:302-309`. Financial-statement vendor errors are caught and converted to a generic `ValueError` at `backend/app/services/company_data_service.py:312-327`, which the route maps to 400 at `backend/app/api/data.py:125-143`. Quote failure follows the same `None`/404 path at `backend/app/services/data_service.py:598-608` and `backend/app/api/data.py:379-385`.
- **Affected flow/callers:** historical, quote, and financial-statement clients at `backend/app/api/data.py:102-154,271-393`; portfolio add treats quote failure as an invalid/unavailable ticker at `backend/app/api/portfolio.py:212-218`.
- **Grounded impact:** a rate limit, timeout, authentication failure, or database/network outage is indistinguishable from an unknown ticker or bad request, preventing callers from applying retry/backoff semantics.
- **Minimum recommendation:** preserve a typed unavailable/outage error through the service boundary and map it to 503/504, reserving 404 for a verified missing instrument and 400 for verified input errors.
- **Test gap:** existing tests assert the collapsed `None`/404 and statement/400 behavior at `backend/tests/test_coverage_data_service.py:127-140`, `backend/tests/test_api_endpoints.py:48-53`, and `backend/tests/test_coverage_services_and_api.py:259-271`; no test drives a real service exception through the route and asserts a 503/504 distinction.

### DATA-012 — P2 — Partial bfinance responses are accepted without completing the fallback

- **Evidence:** bfinance fundamentals are returned whenever more than two fields survive filtering at `backend/app/services/company_data_service.py:138-187`; the yfinance tier is reached only when no bfinance result exists at `backend/app/services/company_data_service.py:236-256`. Statement fallback is selected only when bfinance returns `None` or an empty frame at `backend/app/services/company_data_service.py:293-327`.
- **Affected flow/callers:** `/api/v1/data/fundamentals/{ticker}` and `/api/v1/data/financials/{ticker}` at `backend/app/api/data.py:102-143`; bfinance is the default primary source at `backend/app/services/source_preference_service.py:26-48`.
- **Grounded impact:** a syntactically non-empty but materially incomplete bfinance payload is returned as success, so the secondary vendor cannot fill missing fields or prove that the requested statement period is present.
- **Minimum recommendation:** define required fields/periods per response and treat a partial bfinance result as a miss or merge it explicitly with the next tier.
- **Test gap:** tests cover full bfinance results and wholly empty yfinance results at `backend/tests/test_coverage_alpha_vantage.py:220-292` and `backend/tests/test_data_services.py:121-176`; no test supplies a partial non-empty bfinance payload.

### DATA-013 — P2 — Financial statements do not honor the persisted source preference

- **Evidence:** the public configuration contract describes primary-source swapping for the data cascade at `backend/app/api/data.py:203-207`, and `source_order_for` produces the user-selected bfinance/yfinance order at `backend/app/services/source_preference_service.py:81-85`. The financials route passes only ticker/statement/frequency at `backend/app/api/data.py:125-138`, while the service hard-codes bfinance then yfinance at `backend/app/services/company_data_service.py:293-324`.
- **Affected flow/callers:** `/api/v1/data/financials/{ticker}` at `backend/app/api/data.py:125-143`; it does not read `get_primary_source` or accept `source_order`.
- **Grounded impact:** changing the primary source affects OHLCV, quotes, and fundamentals but not statements; the endpoint has no exposed contract explaining that exception.
- **Minimum recommendation:** pass the resolved source order into statements or explicitly document and test statements as a fixed-tier endpoint.
- **Test gap:** source-preference tests cover OHLCV, quotes, and fundamentals at `backend/tests/test_source_preference_and_cache.py:157-414`; no statement test changes the preference and records vendor order.

### DATA-014 — P2 — The explicit market-data cache purge does not clear the fundamentals cache

- **Evidence:** `CompanyDataService` keeps a process-local 24-hour fundamentals cache at `backend/app/services/company_data_service.py:59-71` and reads/writes it at `backend/app/services/company_data_service.py:189-234`; the global service accessor preserves that instance at `backend/app/services/company_data_service.py:382-389`. The purge function clears database market stores plus DataService, screener, and currency in-process caches at `backend/app/services/cache_service.py:221-280`; it does not include `CompanyDataService` or its cache.
- **Affected flow/callers:** `/api/v1/data/cache/clear` at `backend/app/api/data.py:249-268` and subsequent `/fundamentals/{ticker}` requests at `backend/app/api/data.py:102-122`.
- **Grounded impact:** after an explicit purge, the fundamentals endpoint can still return the previous process-local payload for up to the configured 24-hour TTL.
- **Minimum recommendation:** clear the company fundamentals cache as part of purge, or make purge invalidate the singleton explicitly.
- **Test gap:** the purge test seeds only timeseries, analytics, fetch logs, and positions at `backend/tests/test_source_preference_and_cache.py:441-482`; it does not seed or verify company fundamentals cache invalidation.

### DATA-015 — P2 — yfinance retry handling covers only one exception class

- **Evidence:** `_yf_retry` catches only `YFRateLimitError` at `backend/app/services/company_data_service.py:37-52`. Fundamentals, statements, and insider-transactions call it for `info`, statement properties, and `insider_transactions` at `backend/app/services/company_data_service.py:194-203`, `316-324`, and `358-364`; other exceptions are converted directly to `RuntimeError` or logged/converted to empty data.
- **Affected flow/callers:** fundamentals/statements/insider API routes at `backend/app/api/data.py:102-154`.
- **Grounded impact:** transient yfinance network, timeout, or HTTP failures do not receive the same bounded retry behavior that rate-limit failures receive.
- **Minimum recommendation:** classify retryable transport/status errors separately, use bounded backoff, and preserve non-retryable authentication errors as outages.
- **Test gap:** the retry test exercises only `YFRateLimitError` at `backend/tests/test_coverage_alpha_vantage.py:202-218`; no test covers a non-rate-limit transient exception or a retry exhaustion response.

### DATA-016 — P2 — Timeout workers survive cancellation and the entire vendor cascade is repeated three times

- **Evidence:** `_download_with_timeout` documents that `wait_for` cannot cancel its executor worker and can leave three stacked downloads per ticker at `backend/app/services/data_service.py:829-837`. The caller wraps `_download_with_timeout` in a three-attempt loop at `backend/app/services/data_service.py:386-434`; each attempt internally iterates the source order at `backend/app/services/data_service.py:799-827`.
- **Affected flow/callers:** batch fetching runs up to five workers at `backend/app/services/data_service.py:645-660`; analytics repeatedly calls historical fetches at `backend/app/api/analytics.py:786-802`.
- **Grounded impact:** a timeout can leave network work running while subsequent retries repeat both vendors, multiplying requests during an outage and increasing rate-limit pressure.
- **Minimum recommendation:** use a cancellable/vendor-specific timeout boundary and a per-ticker single-flight; retry only the failed vendor, not the whole ordered cascade.
- **Test gap:** timeout tests mock `asyncio.wait_for` and assert `None` at `backend/tests/test_coverage_data_service.py:271-287`; they do not observe worker lifetime, call counts after timeout, or concurrent batch amplification.

### DATA-017 — P2 — Alpha Vantage treats every HTTP error as a frequency limit

- **Evidence:** every `requests.HTTPError` is passed to `mark_frequency_limited` at `backend/app/services/alpha_vantage_service.py:233-241`; there is no status-code distinction before the cooldown. The only test response double has `raise_for_status()` as a no-op at `backend/tests/test_alpha_vantage.py:31-39`.
- **Affected flow/callers:** historical and quote fallback at `backend/app/services/data_service.py:848-909`.
- **Grounded impact:** authentication, server, and other HTTP failures demote a key for the frequency cooldown even when the vendor did not report a per-minute limit, reducing available fallback capacity.
- **Minimum recommendation:** classify 429/frequency notices separately from authentication and server errors; cool down only the condition the vendor actually reported.
- **Test gap:** no test supplies HTTP 401, 429, or 500 and asserts the key-pool state and next-vendor selection.

### DATA-018 — P2 — The portfolio currency API exposes currencies the FX service cannot convert

- **Evidence:** the portfolio route accepts `EUR`, `GBP`, `JPY`, and `AED` in addition to INR/USD at `backend/app/api/portfolio.py:45-68`, but the FX service only handles USD/INR and inverse USD/INR at `backend/app/services/currency_service.py:148-194`; an unsupported pair raises `ValueError` at `backend/app/services/currency_service.py:191-194`. `format_currency` treats every non-INR code as USD at `backend/app/services/currency_service.py:88-110`.
- **Affected flow/callers:** portfolio summary conversion at `backend/app/api/portfolio.py:123-127` and currency convenience/formatting callers at `backend/app/services/currency_service.py:209-260`.
- **Grounded impact:** for a non-empty portfolio, a request for an accepted EUR/GBP/JPY/AED target reaches conversion and receives a 400 unsupported-rate error rather than a supported conversion; the formatter can label non-USD values with `$`.
- **Minimum recommendation:** align the route allowlist with implemented pairs and make currency formatting explicit for every accepted code.
- **Test gap:** tests cover an unknown service pair at `backend/tests/test_contract_p1_batch.py:311-320`, but no portfolio request exercises the four currencies that the route advertises.

### DATA-019 — P1 — The hardcoded FX fallback is silently used for portfolio values

- **Evidence:** `FALLBACK_USD_INR = 83.0` is served when yfinance fails at `backend/app/services/currency_service.py:15-17,180-190`; the service deliberately avoids caching it at `backend/app/services/currency_service.py:55-68`. Portfolio totals are then converted and returned as ordinary values at `backend/app/api/portfolio.py:123-147`, while the only metadata helper reports no cached rate when fallback was served at `backend/app/services/currency_service.py:126-138`.
- **Affected flow/callers:** `/api/v1/portfolio` at `backend/app/api/portfolio.py:45-155` and any conversion through the global service at `backend/app/services/currency_service.py:197-260`.
- **Grounded impact:** callers receive a portfolio total calculated at an unverified fixed rate with no response-level `is_fallback`, rate age, or warning.
- **Minimum recommendation:** expose fallback provenance and age in the response, or fail/mark the conversion rather than presenting the constant as an ordinary live conversion.
- **Test gap:** tests assert the constant is returned and not cached at `backend/tests/test_bugfix_providers_05.py:131-148` and `backend/tests/test_coverage_services_and_api.py:71-89`; none verifies that a portfolio consumer can detect the fallback.

### DATA-020 — P1 — India liquidity limits fabricate ADV/price defaults when provider history is missing

- **Evidence:** when a matching frame has no usable close/volume columns, the service substitutes `adv_shares = 50000`, `adv_rupees` based on a fallback price, and `amihud = 0.05` at `backend/app/services/india_data_service.py:274-297`. The API builds `price_dfs` only for non-empty frames at `backend/app/api/analytics.py:2126-2134`, so absent holdings reach that default branch; the returned payload has no missing-data flag at `backend/app/services/india_data_service.py:315-334`.
- **Affected flow/callers:** `/api/v1/analytics/liquidity-limits` at `backend/app/api/analytics.py:2090-2146` and portfolio holdings without usable history.
- **Grounded impact:** a missing provider response is rendered as a measured-looking liquidity tier, liquidation duration, and Amihud score rather than an unavailable measurement.
- **Minimum recommendation:** return `None`/an explicit unavailable status for missing ADV inputs; do not synthesize a price, ADV, or Amihud value.
- **Test gap:** the regression test only proves that a volume-only frame does not raise and expects the hardcoded ADV at `backend/tests/test_bugfix_providers_05.py:278-293`; no test asserts that a missing frame is marked unavailable.

### DATA-021 — P2 — India institutional-flow lookback is calendar days despite a trading-session contract

- **Evidence:** the method is documented as the last N trading sessions at `backend/app/services/india_data_service.py:173-176`, but its cutoff subtracts `timedelta(days=lookback_days)` at `backend/app/services/india_data_service.py:177-181`. The API repeats the “trading sessions” contract at `backend/app/api/analytics.py:2030-2041`.
- **Affected flow/callers:** `/api/v1/analytics/india-flows` at `backend/app/api/analytics.py:2030-2049`.
- **Grounded impact:** weekends and exchange holidays consume lookback budget, so the number of returned sessions is not the requested session count.
- **Minimum recommendation:** derive the cutoff from the stored trading-session rows or use the project's NSE calendar rather than elapsed calendar days.
- **Test gap:** coverage seeds ordinary calendar-offset dates and checks only that flows are present at `backend/tests/test_coverage_india_data.py:75-82,122-149`; no weekend/holiday boundary test exists.

### DATA-022 — P2 — Custom-screener vendor failure is not mapped to the same outage status as prebuilt screens

- **Evidence:** `run_custom_screen` catches every exception and raises `ValueError` at `backend/app/services/screener_service.py:339-351`. The custom route catches `RuntimeError` as 503 and all other exceptions as 500 at `backend/app/api/equity_research.py:238-257`.
- **Affected flow/callers:** `/api/v1/screens/custom` at `backend/app/api/equity_research.py:238-257`; the prebuilt path separately maps vendor failure to `RuntimeError` at `backend/app/services/screener_service.py:232-254` and 503 at `backend/app/api/equity_research.py:206-235`.
- **Grounded impact:** a bfinance/vendor outage on the custom screen becomes a generic 500 rather than the established 503 retryable-outage response.
- **Minimum recommendation:** use the same typed vendor-outage exception and route mapping for custom screens.
- **Test gap:** outage taxonomy is tested for the prebuilt route at `backend/tests/test_bugfix_providers_05.py:212-241`; no custom-screener outage route test exists.

### DATA-023 — P2 — Research and AI paths have a single bfinance provider contract

- **Evidence:** every equity-research operation constructs only `bf.Ticker` at `backend/app/services/equity_research_service.py:42-44,132-134,198-203,219-221,264-266`; every AI operation does the same at `backend/app/services/ai_dossier_service.py:42-44,64-66,82-84,100-102`. Their routes map failures to 503/500 but provide no second provider path at `backend/app/api/equity_research.py:37-130,133-193`.
- **Affected flow/callers:** full profile, shareholding, concalls, ratios, Excel export, and all AI prompt/dossier routes at `backend/app/api/equity_research.py:37-193`.
- **Grounded impact:** any bfinance outage makes all research/AI operations unavailable even when another configured market-data vendor is available; unlike historical/quote paths, there is no source cascade.
- **Minimum recommendation:** either document bfinance as the required research provider and expose that dependency clearly, or add an explicit fallback with the same error taxonomy.
- **Test gap:** tests cover bfinance success and bfinance failure at `backend/tests/test_equity_research_and_screens.py:147-245` and `backend/tests/test_bugfix_providers_05.py:151-210`; no alternate-provider path is tested.

### DATA-024 — P2 — Raw provider exceptions can expose the Alpha Vantage key in logs

- **Evidence:** the API key is placed in the request query at `backend/app/services/alpha_vantage_service.py:227-230`; the raw `HTTPError` object is logged at `backend/app/services/alpha_vantage_service.py:233-241`. The global exception handler also logs raw exception text at `backend/main.py:104-110` without a provider-specific redaction filter.
- **Affected flow/callers:** Alpha HTTP errors and any uncaught provider exception reaching the application handler at `backend/app/services/data_service.py:858-863` and `backend/main.py:104-110`.
- **Grounded impact:** the code has no redaction boundary between a key-bearing request URL/exception and the logger, so a URL-bearing HTTP error can place the key in application logs.
- **Minimum recommendation:** redact query parameters and provider credentials before logging, and use structured exception fields rather than raw exception text.
- **Test gap:** no test captures logger output for a key-bearing HTTP error; the Alpha test doubles never exercise `raise_for_status` at `backend/tests/test_alpha_vantage.py:31-39`.

### DATA-025 — P2 — Fetch provenance is reported from the wrong row and collapsed across attempts

- **Evidence:** the historical API labels the entire response with the latest source row for the ticker, without restricting the query to the returned date window, at `backend/app/api/data.py:313-329`. Failed historical attempts log `source_order[0]` at `backend/app/services/data_service.py:422-432`, while Alpha success is logged separately only after a successful fallback at `backend/app/services/data_service.py:868-880`.
- **Affected flow/callers:** `/api/v1/data/{ticker}` response metadata and `fetch_logs` at `backend/app/api/data.py:341-360` and `backend/app/services/data_service.py:406-432,868-880`.
- **Grounded impact:** after source changes or mixed-source union upserts, the response can report a source from a row outside the requested slice; a cascade that tried multiple vendors is represented as one primary-source failure or one success rather than per-attempt provenance.
- **Minimum recommendation:** record one provenance entry per vendor attempt and derive response source from the rows actually returned.
- **Test gap:** source tests assert homogeneous row provenance after isolated successes at `backend/tests/test_source_preference_and_cache.py:166-211`; no test uses mixed-source rows or checks failed-attempt source fields.

### DATA-026 — P2 — Default market windows use server-local naive time rather than the Indian market clock

- **Evidence:** historical defaults use naive `datetime.now()` at `backend/app/api/data.py:290-294,405-407,481-483` and `backend/app/services/data_service.py:631-635`; benchmark defaults do the same at `backend/app/services/benchmark_service.py:51-56,79-82`. Quote timestamps explicitly use `Asia/Kolkata` at `backend/app/services/data_service.py:493-496,565-570`.
- **Affected flow/cash callers:** data API, batch API, refresh API, and benchmark/analytics requests at `backend/app/api/data.py:271-303,396-418,469-504` and `backend/app/services/benchmark_service.py:45-96`.
- **Grounded impact:** the default requested end date follows the process timezone rather than the exchange timezone; near the IST date boundary the provider request can end on the previous calendar day.
- **Minimum recommendation:** inject one market-clock helper using `Asia/Kolkata` for Indian defaults and keep UTC only for persistence timestamps.
- **Test gap:** tests use `datetime.utcnow()`/current-date fixtures rather than a controlled IST/UTC boundary at `backend/tests/test_deep_cache.py:200-224` and `backend/tests/test_coverage_india_data.py:46-49`.

### DATA-027 — P3 — AI dossier format is not validated at the API boundary

- **Evidence:** the service annotates `format` as a `Literal` at `backend/app/services/ai_dossier_service.py:32-36`, but the API accepts an unconstrained string and passes it directly to the service at `backend/app/api/equity_research.py:173-186`. The route maps 404/503 and otherwise returns 500 at `backend/app/api/equity_research.py:187-193`.
- **Affected flow/callers:** `/api/v1/company/{ticker}/ai-dossier` at `backend/app/api/equity_research.py:173-193`.
- **Grounded impact:** an unsupported format is delegated to bfinance instead of being rejected as a client input error, so the route has no explicit 400 contract for that parameter.
- **Minimum recommendation:** validate `format` as an enum at the route boundary and return 400 for unsupported values.
- **Test gap:** dossier tests cover markdown success and service failure at `backend/tests/test_equity_research_and_screens.py:232-245,301-315`; no invalid-format test exists.

## 4. Provider/source matrix

| Source or store | Symbols/markets | Fields/operations | Fallback/precedence | Cache/freshness | Error/partial behavior |
|---|---|---|---|---|---|
| bfinance via `DataService` | Canonical DataService symbols; `.NS`/`.BO` pass through, known bare Indian names become `.NS` at `backend/app/services/data_service.py:31-67`. | OHLCV download and quote metadata at `backend/app/services/data_service.py:474-500,799-825`. | First/second according to persisted preference; `_download_with_timeout` tries each source in order at `backend/app/services/data_service.py:377-390,799-827`. | Shared SQLite plus ticker-keyed L1; 10-year backfill and 5-minute L1 at `backend/app/services/data_service.py:119-145,381-420`. | Non-empty frames can be accepted before window validation (`DATA-001`); exceptions are caught inside the cascade at `backend/app/services/data_service.py:821-827`. |
| yfinance via `DataService` | Same canonicalizer; Yahoo-native `^NSEI`/`=X` pass through at `backend/app/services/data_service.py:42-67`. | OHLCV, quote, corporate actions, and FX `USDINR=X` at `backend/app/services/data_service.py:502-570,737-764` and `backend/app/services/currency_service.py:148-190`. | Primary/secondary order follows source preference at `backend/app/services/data_service.py:377-390,471-604`; Alpha is appended by DataService, not by `source_order_for`, at `backend/app/services/data_service.py:436-441`. | DataService SQLite/L1; quote memo is 30 seconds at `backend/app/services/data_service.py:121-135,465-469`. | Rate-limit-only company retry at `backend/app/services/company_data_service.py:37-52`; historical errors collapse to `None` at `backend/app/services/data_service.py:422-447`. |
| Alpha Vantage | `.NS` and `.BO` are both rewritten to `.BSE`; plain symbols pass through at `backend/app/services/alpha_vantage_service.py:45-55`. | Daily OHLCV and `GLOBAL_QUOTE` only at `backend/app/services/alpha_vantage_service.py:204-308,312-347`. | Always last for DataService historical/quote fallback; not used by fundamentals, statements, screener, research, or AI at `backend/app/services/data_service.py:436-441,848-909` and `backend/app/services/source_preference_service.py:26-30`. | No response cache; in-process per-key daily/minute budgets at `backend/app/services/alpha_vantage_service.py:94-172`. | Daily/frequency/invalid-key notices are classified at `backend/app/services/alpha_vantage_service.py:248-266`; all HTTP errors currently receive a frequency cooldown (`DATA-017`). |
| bfinance research/screener/AI | Research normalizer is the same canonicalizer at `backend/app/services/equity_research_service.py:20-22` and `backend/app/services/ai_dossier_service.py:17-19`; screener maps numeric results to `.BO` and other bare results to `.NS` at `backend/app/services/screener_service.py:39-46`. | Profiles, shareholding, concalls, ratios, Excel, prompts, dossiers, and five predefined screens at `backend/app/services/equity_research_service.py:35-292`, `backend/app/services/ai_dossier_service.py:32-110`, and `backend/app/services/screener_service.py:73-99`. | No alternate provider is present in these methods; custom screener also has a different error path at `backend/app/services/screener_service.py:339-351`. | Prebuilt screener L1 is 300 seconds and L2 is 24 hours at `backend/app/services/screener_service.py:59-63,112-175`; research/AI have no service cache. | Prebuilt screens fail open on L2 read errors and raise `RuntimeError` on compute errors at `backend/app/services/screener_service.py:119-175,232-254`; research/AI wrap unexpected errors as `RuntimeError` at `backend/app/services/equity_research_service.py:117-123,184-210` and `backend/app/services/ai_dossier_service.py:46-52,68-74`. |
| SQLite `stock_timeseries` | Canonical ticker string stored by DataService at `backend/app/services/data_service.py:1060-1112`; model key is `(ticker,date)` at `backend/app/models/database.py:60-64`. | Open/high/low/close/adj_close/volume plus source/fetch timestamps at `backend/app/models/database.py:39-64`. | Cache is checked before the vendor cascade at `backend/app/services/data_service.py:347-379`; source preference is not part of the row key. | Deep backfill is capped at 10 years from requested end; SQLite rows are the union after upsert at `backend/app/services/data_service.py:131-145,381-420`. | Atomic upsert and rollback exist at `backend/app/services/data_service.py:1093-1118`; validation is advisory (`DATA-003`) and partial frames are accepted (`DATA-001`). |
| SQLite `analytics_cache` | Namespace/identity is supplied by the caller; screener uses `SCREENER` plus strategy/universe/date at `backend/app/services/screener_service.py:25-36,122-171`. | Metrics and JSON `model_params`; unique `(ticker,metric_name)` at `backend/app/models/database.py:70-90`. | L2 is best-effort; cache read failure falls through to computation at `backend/app/services/screener_service.py:119-146`. | `CacheService` computes expiry from its injected TTL at `backend/app/services/cache_service.py:54-87`; screener injects 24 hours at `backend/app/services/screener_service.py:25-31`. | `CacheService` logs and rolls back its own DB errors at `backend/app/services/cache_service.py:88-95`; runtime cache-control wiring is defective (`DATA-006`). |
| SQLite NSE tables | NSE symbols are stored without exchange suffix; delivery reads strip `.NS`/`.BO` at `backend/app/services/india_data_service.py:210-217`. | Bhavcopy OHLC/trade/delivery and FII/DII net flows at `backend/app/models/database.py:116-168`. | No first-party external vendor fetch is present in the inspected backend; the read API instantiates the service only to query the DB at `backend/app/api/analytics.py:2039-2045,2072-2080`. | No service TTL or freshness gate; lookback is calendar-based at `backend/app/services/india_data_service.py:177-181`. | Missing bhavcopy fields become zeros and liquidity defaults are synthesized (`DATA-004`, `DATA-020`); no ingestion scheduler is present in the inspected first-party call paths. |
| FX fallback | Only USD/INR and inverse are implemented at `backend/app/services/currency_service.py:148-194`. | One floating-point rate; fallback is 83.0 and is not cached at `backend/app/services/currency_service.py:15-17,55-68,180-190`. | No second FX provider; the hardcoded value is the terminal fallback. | Live rates cache for 30 minutes at `backend/app/services/currency_service.py:19-26,44-68`. | Fallback is silent to portfolio consumers (`DATA-019`); unsupported route currencies fail or format as USD (`DATA-018`). |

## 5. Test gaps

1. **Window completeness:** no test covers a non-empty vendor frame outside the requested interval, a sparse frame shorter than 60 days, or an empty L1 slice causing secondary/Alpha continuation. Existing coverage only exercises all-vendor failure and malformed frames at `backend/tests/test_coverage_data_service.py:113-140` and `backend/tests/test_bugfix_core_services.py:333-370`.
2. **Exact date boundaries:** no test requires the requested end-date row through SQLite, bfinance, yfinance, and Alpha; the current test only asserts an upper bound at `backend/tests/test_deep_cache.py:82-85`, while the known end-exclusive behavior is recorded at `backend/tests/test_deep_cache.py:167-178`.
3. **Cache controls:** no test changes `enable_cache`/TTL and then proves the next `fetch_historical_data` behavior; current tests only persist and read the settings at `backend/tests/test_contract_p1_batch.py:177-183,300-308`.
4. **Source-switch cache behavior:** no test performs a warm fetch, changes `primary_data_source`, and verifies vendor order without `force_refresh`; current cascade tests force refresh or use a cold cache at `backend/tests/test_source_preference_and_cache.py:166-235`.
5. **Symbol edge cases:** no end-to-end test covers a non-popular valid Indian symbol, bare numeric BSE code, lowercase exchange code, or an Alpha symbol whose NSE/BSE identity differs. Current tests explicitly lock unknown bare pass-through and suffixed BSE behavior at `backend/tests/test_p07_ticker.py:17-34`.
6. **Validation fallback:** no test enables Alpha and drives bfinance/yfinance failure through `validate_ticker`; validation coverage mocks only the two primary vendors at `backend/tests/test_coverage_data_service.py:199-216`.
7. **Response schema:** no test asserts 52-week fields survive `StockQuoteResponse`, or that a bare known-Indian request returns the canonical ticker in every historical row/response at `backend/tests/test_api_endpoints.py:69-80` and `backend/app/models/schemas.py:139-151`.
8. **Error taxonomy:** no route test drives a real historical timeout/rate-limit, statement upstream exception, or quote provider exception into 503/504 versus 404/400/500; current tests assert the collapsed results at `backend/tests/test_api_endpoints.py:48-53` and `backend/tests/test_coverage_services_and_api.py:259-271`.
9. **Company partial/cache behavior:** no test supplies a partial non-empty bfinance fundamentals/statement frame, changes source preference for statements, or verifies that cache purge clears the 24-hour company cache. Existing tests use full frames and database-only purge rows at `backend/tests/test_coverage_alpha_vantage.py:220-317` and `backend/tests/test_source_preference_and_cache.py:441-482`.
10. **Retry/rate resilience:** no test covers non-rate yfinance exceptions, Alpha HTTP 401/429/500 classification, worker lifetime after timeout, or retry call-count amplification at `backend/app/services/company_data_service.py:37-52` and `backend/app/services/data_service.py:386-434,829-837`.
11. **NSE ingestion:** no test verifies missing fields are rejected, same-day corrections update, duplicate symbols in one payload preserve other rows, or a mixed conflict preserves the non-conflicting rows. Current tests cover only no-raise/idempotence/single-race paths at `backend/tests/test_coverage_india_data.py:46-73` and `backend/tests/test_bugfix_providers_05.py:297-333`.
12. **India liquidity/calendar:** no test asserts missing history produces an unavailable result rather than ADV/Amihud defaults, and no weekend/holiday test distinguishes calendar lookback from trading-session lookback at `backend/app/services/india_data_service.py:173-181,274-334`.
13. **Currency:** no test exercises the route-advertised EUR/GBP/JPY/AED targets or fallback disclosure to the portfolio response. Current tests cover only USD/INR, the constant, and marker presence at `backend/tests/test_coverage_services_and_api.py:24-100` and `backend/tests/test_bugfix_providers_05.py:131-148`.
14. **Research/AI availability and input contracts:** no test supplies an alternate research provider, drives custom-screener outage status, or sends an invalid AI dossier format. Current tests cover bfinance success/outage and markdown only at `backend/tests/test_equity_research_and_screens.py:147-245,301-315` and `backend/tests/test_bugfix_providers_05.py:151-241`.
15. **Logging/provenance:** no caplog test checks key redaction, no mixed-source response test exists, and no fetch-log test checks one row per vendor attempt at `backend/app/services/alpha_vantage_service.py:227-241` and `backend/app/api/data.py:313-329`.

## 6. Explicit clean areas and limitations

### Clean areas

- The Alpha Vantage key-budget primitives correctly roll the quota day, enforce daily/minute local budgets, rotate positions, retire daily-exhausted keys, and cool frequency-limited keys at `backend/app/services/alpha_vantage_service.py:94-172`. The corresponding mocked tests cover rotation, local exhaustion, cooldown, and no-key behavior at `backend/tests/test_alpha_vantage.py:67-130` and `backend/tests/test_coverage_alpha_vantage.py:45-153`.
- Source-preference validation, defaulting, single-row upsert, and two-vendor ordering are implemented at `backend/app/services/source_preference_service.py:24-85` and tested for round-trip/isolation at `backend/tests/test_source_preference_and_cache.py:122-152`.
- Company fundamentals normalize the two documented cross-tier units: bfinance market cap is converted from crore to absolute rupees and yfinance ROE is converted to percent at `backend/app/services/company_data_service.py:157-169,225-229`; the cross-tier magnitude test is at `backend/tests/test_bugfix_providers_05.py:66-91`.
- Equity research preserves genuine `ValueError` not-found semantics and converts other provider failures to `RuntimeError` at `backend/app/services/equity_research_service.py:117-123,184-190,205-210`; the route 404/503 tests are at `backend/tests/test_bugfix_equity_research_503.py:11-23` and `backend/tests/test_equity_research_and_screens.py:325-342`.
- Prebuilt screener cache identity includes strategy, universe token, date, and result cap; L2 read failures fail open to computation, and universe/max-stock/debt behavior is tested at `backend/app/services/screener_service.py:34-53,112-175,208-275` and `backend/tests/test_screener_cache.py:91-145` plus `backend/tests/test_p09_screener.py:42-107`.
- Atomic analytics-cache upsert and rollback are implemented at `backend/app/services/cache_service.py:54-95`; the database unique key and initialization self-heal are at `backend/app/models/database.py:70-90` and `backend/app/db/database.py:60-71`.
- Provider/CPU-bound calls in Alpha Vantage, DataService, company data, currency, screener, equity research, and AI dossier are generally moved off the event loop through `to_thread`/executor calls at `backend/app/services/alpha_vantage_service.py:229-232`, `backend/app/services/data_service.py:598,715-721,751-752,829-837`, `backend/app/services/company_data_service.py:194-199,310-324`, `backend/app/services/currency_service.py:157-175`, `backend/app/services/screener_service.py:232-233,270-271`, `backend/app/services/equity_research_service.py:117-118,184-185,205-206,286-287`, and `backend/app/services/ai_dossier_service.py:46-47,68-69,86-87,104-105`. The timeout caveat is the explicit `DATA-016` exception, not a claim that all async work is cancellable.
- The deep-cache union/upsert path, requested-slice re-read, and L1 ticker key are implemented at `backend/app/services/data_service.py:131-145,292-318,381-420` and covered at `backend/tests/test_deep_cache.py:67-158`; the remaining defects are completeness/date-boundary defects, not a missing SQLite cache mechanism.

### Limitations

- This was a static source audit; no live Alpha Vantage, yfinance, bfinance, NSE, or FX request was made, so vendor behavior outside the cited first-party seams is not asserted.
- The quant/analytics algorithms in `backend/app/services/analytics_engine.py:1-1345`, `backend/app/services/correlation_service.py:1-150`, `backend/app/services/cointegration_service.py:1-467`, `backend/app/services/regime_service.py:1-353`, `backend/app/services/volatility_service.py:1-330`, `backend/app/services/tail_risk_service.py:1-389`, `backend/app/services/optimization_service.py:1-330`, `backend/app/services/backtest_service.py:1-195`, and `backend/app/services/monte_carlo_service.py:1-231` were intentionally not duplicated; only their provider/cache input boundaries were checked.
- No first-party production caller of `IndiaDataService.ingest_bhavcopy_records` or `ingest_institutional_flow` was found in the inspected backend call paths; the visible India API creates the service for reads at `backend/app/api/analytics.py:2039-2045,2072-2080,2132-2134`. An external ingestion job could therefore change the freshness conclusion, but none was assumed.
- The application is configured for localhost defaults at `backend/app/config.py:23-25` and `backend/main.py:173-180`; this lowers scale/security severity for the log-redaction issue but does not change the P1 data-integrity findings.
- No application files or tests were changed; this report is the only intended write.
