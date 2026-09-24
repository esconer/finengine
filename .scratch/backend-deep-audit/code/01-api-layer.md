# API Layer Line-by-Line Audit

## 1. Scope and methodology

**Scope.** Static, independent review of every line in the first-party API layer and backend entrypoint, limited to cash equities and portfolio analytics:

- `backend/app/api/__init__.py`
- `backend/app/api/analytics.py`
- `backend/app/api/data.py`
- `backend/app/api/equity_research.py`
- `backend/app/api/portfolio.py`
- `backend/app/api/websocket.py`
- `backend/main.py`

**Lines inspected:** 4,678 across 7 files.

**Method.** Each in-scope line was read directly. Imported first-party contracts were traced where needed, including request/response schemas, ORM models, database session behavior, data/cache/currency services, analytics and tail-risk services, screener/cointegration services, configuration, logging, and relevant tests. Tests were inspected only to identify regression coverage. No application code was changed and no tests were run.

Prior-audit material was not inspected. Findings are limited to the API/entrypoint and their direct contracts. Inventory counts assign each finding to one **primary file**; supporting files do not increment the inventory count.

**Severity.** P0 = security/crash/data loss; P1 = major correctness/security/availability; P2 = meaningful bounded issue; P3 = minor improvement. No P0 issue was evidenced.

## 2. File inventory

| File | Lines inspected | Clean files | Findings | Notes |
|---|---:|---:|---:|---|
| `backend/app/api/__init__.py` | 3 | 1 | 0 | **Fully clean.** Documentation-only package marker. |
| `backend/app/api/websocket.py` | 358 | 0 | 2 | Fabricated zero analytics and serial unbounded sends. Also supports API-002. |
| `backend/app/api/portfolio.py` | 1,118 | 0 | 8 | Monetary, uniqueness, transaction, export, and diagnostics findings. |
| `backend/app/api/equity_research.py` | 257 | 1 | 0 | **Fully clean.** Error mappings and response models were consistent within this file. |
| `backend/app/api/data.py` | 506 | 0 | 6 | Cache configuration, provenance, validation, refresh, transaction, and fan-out findings. |
| `backend/app/api/analytics.py` | 2,255 | 0 | 8 | Cache correctness, event-loop blocking, allocation, validation, status, and scanner findings. |
| `backend/main.py` | 181 | 0 | 2 | WebSocket trust boundary and shutdown sequencing. |
| **Total** | **4,678** | **2 fully clean files** | **26 unique findings** | Counts reconcile to API-001 through API-026. |

**Reconciliation:** P0 0, P1 7, P2 17, P3 2. Categories: Bug 17, Improvement 4, Optimization 3, Recommended change 2.

## 3. Detailed findings

### API-001 — Portfolio monetary values have no coherent currency contract

- **Category / severity:** Bug / P1
- **Evidence:** `backend/app/api/portfolio.py:67` advertises INR, USD, EUR, GBP, JPY, and AED; `backend/app/api/portfolio.py:92` sums every position's numeric value as one unit; `backend/app/api/portfolio.py:103-120` leaves nested prices and values unconverted while only the top-level total is converted at `backend/app/api/portfolio.py:123-127`; `backend/app/api/portfolio.py:161` accepts a currency on add but never uses it. The quote service exposes currency at `backend/app/services/data_service.py:493`, but `PortfolioPosition` has no currency column at `backend/app/models/database.py:11-30`. The direct conversion service supports only USD/INR at `backend/app/services/currency_service.py:156-194`.
- **Affected flow / callers:** Portfolio add/list, dashboard totals, rebalance valuation at `backend/app/api/portfolio.py:872-880`, and analytics summary valuation at `backend/app/api/analytics.py:1094-1100`. A mixed AAPL/USD + Indian-equity/INR book is numerically summed as if both were INR.
- **Why wrong:** Monetary totals can be materially wrong. For `currency=USD`, the top-level total is converted while position values remain INR-shaped. For EUR/GBP/JPY/AED, the route advertises support but conversion raises `ValueError`, which the route maps to 400.
- **Smallest recommended change:** Establish one explicit position/base-currency contract, convert each position before aggregation, return the response currency, and either remove the unused add currency parameter or honor it. Until all advertised currencies are backed by rates, narrow the whitelist.
- **Existing test gap:** `backend/tests/test_coverage_portfolio_api.py:145-191` mixes US and Indian positions but only asserts `total_value > 0`; it does not verify units, nested values, or advertised non-USD currencies.

### API-002 — WebSocket handshakes have no Origin/Host trust check

- **Category / severity:** Bug / P1
- **Evidence:** CORS is configured as HTTP middleware at `backend/main.py:89-96`; `TrustedHostMiddleware` is production-only at `backend/main.py:81-87`. The WebSocket connection is accepted before any header validation at `backend/app/api/websocket.py:30-31`, and the endpoint performs no Origin check at `backend/app/api/websocket.py:272-278`. The HTTP broadcast endpoint is likewise unauthenticated at `backend/app/api/websocket.py:340-352`. Loopback binding at `backend/main.py:173-180` limits remote-network reach but does not prevent a malicious web page from connecting to a user's local service.
- **Affected flow / callers:** Any browser page can attempt a cross-origin WebSocket to `/api/v1/ws/ws/{client_id}` and receive portfolio, analytics, and market-data broadcasts; it can also target the query-parameter broadcast endpoint. Browser WebSocket handshakes are not protected by the HTTP CORS response policy.
- **Why wrong:** Localhost is not a browser trust boundary. Portfolio holdings and analytics can be exposed cross-origin, and a connected page can consume server resources. This is especially material because the first connection starts the recurring analytics worker at `backend/app/api/websocket.py:280-283`.
- **Smallest recommended change:** Validate `Origin` and `Host` before `accept()` against explicit local frontend origins, and apply the same trust check to broadcast. A per-install socket token is appropriate if non-browser clients are expected.
- **Existing test gap:** `backend/tests/test_websocket.py:113-187` opens sockets without Origin/Host assertions; there is no rejected-origin regression test.

### API-003 — Tail-risk cache key omits portfolio weights

- **Category / severity:** Bug / P1
- **Evidence:** The response cache lives for 900 seconds at `backend/app/api/analytics.py:2185-2192`. Allocation is resolved before lookup at `backend/app/api/analytics.py:2215-2218`, but the key at `backend/app/api/analytics.py:2222` contains only sorted tickers, dates, and model parameters. The cached calculations are then built from current weights at `backend/app/api/analytics.py:2226` and stored at `backend/app/api/analytics.py:2243`.
- **Affected flow / callers:** `/tail-dependence` and `/tails` after any quantity, price-driven market-value, or weight change. The explicit market-cache purge clears this memo at `backend/app/api/data.py:262-264`, but ordinary portfolio mutations do not.
- **Why wrong:** The same ticker set with a different allocation returns the prior portfolio VaR/ES for up to 15 minutes. The matrix is ticker-only, but the EVT portfolio statistics are weight-dependent.
- **Smallest recommended change:** Partition the memo by canonical weights (and retain TTL), or invalidate it on every portfolio allocation mutation. Do not use a ticker-only key for weight-dependent results.
- **Existing test gap:** No API-level tails cache test exists. `backend/tests/test_bugfix_api_layer.py:183-196` tests only the explicit cache-clear hook, not a weight change between identical requests.

### API-004 — CPU-heavy analytics execute on the event-loop thread

- **Category / severity:** Optimization / P1
- **Evidence:** The async tear-sheet route calls synchronous quantstats metrics repeatedly at `backend/app/api/analytics.py:1422-1456`; optimization is called synchronously at `backend/app/api/analytics.py:1702`; walk-forward backtest at `backend/app/api/analytics.py:1768`; Monte Carlo at `backend/app/api/analytics.py:1890`; volatility cone at `backend/app/api/analytics.py:2173-2175`; and tail calculations at `backend/app/api/analytics.py:2231-2235`. The source itself records the pairwise copula fit as approximately 12 seconds at `backend/app/api/analytics.py:2185-2187`. The called optimization, backtest, simulation, cone, and tail functions are synchronous (`backend/app/services/optimization_service.py:286`, `backend/app/services/backtest_service.py:18`, `backend/app/services/monte_carlo_service.py:163`, `backend/app/services/volatility_service.py:188`, `backend/app/services/tail_risk_service.py:25`).
- **Affected flow / callers:** Tear-sheet, optimize, backtest, Monte Carlo, volatility cone, and first-cache-miss tail requests; while they run, ordinary REST requests and the WebSocket update loop cannot make progress.
- **Why wrong:** Declaring a route `async` does not make synchronous CPU work non-blocking. A first tails request can stall the single-process local server for many seconds; backtest can repeat optimization across windows.
- **Smallest recommended change:** Move the heavy pure computations off the event-loop worker and apply bounded per-process concurrency. Preserve the existing tails memo.
- **Existing test gap:** Tests validate numerical outputs but none run a heartbeat REST/WebSocket operation concurrently with a heavy analytics call.

### API-005 — Cache TTL and enable/disable controls are persisted no-ops

- **Category / severity:** Bug / P1
- **Evidence:** The API presents both settings as live configuration at `backend/app/api/data.py:157-185` and persists them at `backend/app/api/data.py:221-240`. Runtime `DataService` instead constructs its cache with the static process setting at `backend/app/services/data_service.py:73-76`. A repository-wide first-party search finds `cache_ttl_minutes` and `enable_cache` consumers only in `backend/app/api/data.py`; no fetch/cache path consults either persisted key. The prebuilt screener also receives a fixed TTL at `backend/app/api/equity_research.py:223-227`.
- **Affected flow / callers:** Every quote/historical fetch, analytics cache, and screener cache despite a successful `PUT /api/v1/data/config` response.
- **Why wrong:** The API reports that caching was reconfigured, but changing TTL or disabling cache has no behavioral effect. This is a direct false-success contract.
- **Smallest recommended change:** Remove the unsupported controls from the API, or resolve persisted settings when constructing request-scoped cache services and make every cache read/write honor `enable_cache`.
- **Existing test gap:** `backend/tests/test_contract_p1_batch.py:176-183` and `backend/tests/test_contract_p1_batch.py:299-308` assert persistence only; no test changes the setting and observes a cache hit/miss or expiration behavior.

### API-006 — First position does not receive the required 100% weight

- **Category / severity:** Bug / P1
- **Evidence:** Add queries existing tickers at `backend/app/api/portfolio.py:203-205` but never checks whether the portfolio is empty. It stores the client weight unchanged at `backend/app/api/portfolio.py:222-225` and returns it at `backend/app/api/portfolio.py:250-254`. This violates the repository's zero-state invariant.
- **Affected flow / callers:** The first `/portfolio/add` call, subsequent list/update/rebalance responses, and stored target-weight calculations.
- **Why wrong:** A valid first request with `weight=0.5` creates a one-holding portfolio stored as 50%, contradicting the required 100.00% zero-state result.
- **Smallest recommended change:** In the same transaction that establishes the first holding, set its effective weight to `1.0` regardless of the client-supplied initial allocation.
- **Existing test gap:** `backend/tests/test_api_endpoints.py:157-170` starts with an empty portfolio and submits weight `0.5`, but asserts only status/ticker/price and never the required `1.0` weight.

### API-007 — Duplicate prevention is not concurrency-safe or schema-enforced

- **Category / severity:** Recommended change / P1
- **Evidence:** Single add performs select-then-insert at `backend/app/api/portfolio.py:203-205` and `backend/app/api/portfolio.py:238-240`; bulk add does the same at `backend/app/api/portfolio.py:332-350` and `backend/app/api/portfolio.py:451-460`. The source comment acknowledges that no unique constraint is load-bearing at `backend/app/api/portfolio.py:332-335`. `PortfolioPosition` defines only an index on ticker at `backend/app/models/database.py:15-17` and has no unique table constraint.
- **Affected flow / callers:** Concurrent single/bulk adds and any other database writer. Two requests can both observe an absent ticker and both insert it.
- **Why wrong:** Duplicate canonical holdings collapse in dictionary-based analytics, make `.first()` CRUD routes ambiguous, and corrupt allocation/rebalance calculations.
- **Smallest recommended change:** Enforce uniqueness at the database boundary for the canonical stored ticker, map integrity conflicts to 409, and keep the API check only as a friendly early rejection.
- **Existing test gap:** Duplicate tests are sequential only: `backend/tests/test_api_endpoints.py:240-245` and `backend/tests/test_coverage_portfolio_api.py:310-333`. No concurrent-add/schema-constraint test exists.

### API-008 — Ad-hoc performance history fabricates one-share, price-weighted quantities

- **Category / severity:** Bug / P2
- **Evidence:** The endpoint accepts an optional custom ticker list at `backend/app/api/analytics.py:1184-1189`. Any requested ticker absent from the database is assigned quantity `1.0` at `backend/app/api/analytics.py:1219-1220`; those quantities are then used to sum absolute prices at `backend/app/api/analytics.py:1257-1259`.
- **Affected flow / callers:** `/performance-history?tickers=...` for watchlist/ad-hoc symbols.
- **Why wrong:** The result depends on each stock's nominal price rather than portfolio weights, and `portfolio_value` is an undisclosed synthetic notional. A ₹10 stock receives the same notional as a ₹10,000 stock.
- **Smallest recommended change:** Require explicit quantities/weights for custom symbols, or return a normalized/indexed custom-universe series and label its valuation basis explicitly.
- **Existing test gap:** Performance-history tests use real DB positions only (`backend/tests/test_bugfix_api_layer.py:202-217` and `backend/tests/test_bugfix_api_layer.py:225-260`); none exercises custom tickers.

### API-009 — Rebalance order deltas use stale stored weights

- **Category / severity:** Bug / P2
- **Evidence:** Total portfolio value is derived from current quantities/prices at `backend/app/api/portfolio.py:872-875`, but each order's `current_weight` is read from the stored weight column at `backend/app/api/portfolio.py:904-908`. That stale value drives weight delta, buy/sell totals, action, and turnover at `backend/app/api/portfolio.py:920-938`.
- **Affected flow / callers:** Dry-run and live rebalance after market drift or a partial weight update.
- **Why wrong:** Target quantities use live value, while the reported current allocation and cash deltas use a different denominator/state. The response can therefore recommend internally inconsistent trades.
- **Smallest recommended change:** Derive current weight from the same live position value used for `total_pv`; keep stored target weight only as a separate disclosed field if needed.
- **Existing test gap:** Rebalance tests seed stored weights equal to market-value weights (`backend/tests/test_coverage_portfolio_api.py:618-655`), so drift is never tested.

### API-010 — Invalid risk model names silently run a different model

- **Category / severity:** Bug / P2
- **Evidence:** `/forecast-risk` accepts any string at `backend/app/api/analytics.py:452-461`; the engine defaults every unknown model to GARCH at `backend/app/services/analytics_engine.py:116-123`, while the route echoes the original requested model at `backend/app/api/analytics.py:575-589`. `/volatility-sizing` similarly accepts any string at `backend/app/api/analytics.py:914-921`; its engine takes the EWMA branch for unknown values at `backend/app/services/analytics_engine.py:596-610` but reports the supplied model in methodology at `backend/app/services/analytics_engine.py:678-683`.
- **Affected flow / callers:** Forecast and volatility-sizing clients sending a typo or unsupported model.
- **Why wrong:** A request labeled `BOGUS` can return 200 with GARCH/EWMA calculations and a false model label instead of a validation error.
- **Smallest recommended change:** Constrain model parameters to the supported enum and return 422 for unsupported values.
- **Existing test gap:** Existing API tests cover only valid EWMA/GARCH values (`backend/tests/test_api_endpoints.py:370` and `backend/tests/test_coverage_deep_analytics_routes.py:88-92`); no invalid-model test exists.

### API-011 — Empty liquidity states fabricate a neutral-looking score

- **Category / severity:** Bug / P2
- **Evidence:** With no portfolio, the route returns `overall_score=5.0`, `liquidation_time_days="5-10"`, and `risk_level="Medium"` at `backend/app/api/analytics.py:773-783`. With no price data, it repeats the same fabricated metrics at `backend/app/api/analytics.py:819-827`. Both responses also carry an `error` field.
- **Affected flow / callers:** `/analytics/liquidity` dashboard cards and any consumer reading the metric fields without branching on `error`.
- **Why wrong:** Missing data is rendered as a computed mid-range result, directly violating the project's no-placeholder metric-card rule.
- **Smallest recommended change:** Return null metrics for unavailable data with a machine-readable reason; use an appropriate non-success status if the client contract expects one.
- **Existing test gap:** `backend/tests/test_contract_p1_batch.py:150-160` tests an empty engine result, but not the route's no-portfolio or no-price branches that manufacture values before the engine is called.

### API-012 — Date query parameters cross the API boundary as unvalidated strings

- **Category / severity:** Improvement / P2
- **Evidence:** Historical data accepts `start` and `end` as optional strings at `backend/app/api/data.py:271-280`; analytics routes do the same, including `backend/app/api/analytics.py:210-218` and `backend/app/api/analytics.py:1360-1368`. The data service catches parsing/fetch errors and returns `None` at `backend/app/services/data_service.py:342-447`, after which the API commonly reports 404 or an in-body error.
- **Affected flow / callers:** All historical-data and date-window analytics routes.
- **Why wrong:** Malformed dates or `start > end` are client errors but become vendor work, 404s, in-body 200 errors, or 500s depending on the route. Error behavior is inconsistent for the same invalid input class.
- **Smallest recommended change:** Use typed date query parameters and validate ordering at the API boundary so FastAPI returns 422 consistently.
- **Existing test gap:** No API test supplies malformed, reversed, or impossible dates.

### API-013 — Bare Indian ticker cache provenance is misreported

- **Category / severity:** Bug / P2
- **Evidence:** The pre-fetch cache probe uses the raw ticker at `backend/app/api/data.py:296-303`. `fetch_historical_data` canonicalizes known bare Indian symbols before its cache access at `backend/app/services/data_service.py:342-359`, while `_get_cached_data` queries the exact uppercase key at `backend/app/services/data_service.py:972-984`. `from_cache` is derived solely from the pre-probe at `backend/app/api/data.py:311`.
- **Affected flow / callers:** `/api/v1/data/RELIANCE` when cached rows are stored under `RELIANCE.NS`, and equivalent bare Indian symbols.
- **Why wrong:** The data can be served from cache while the API returns `from_cache=false`, breaking provenance and invalidating client/UI cache decisions.
- **Smallest recommended change:** Canonicalize the ticker once at route entry and use that same form for the pre-probe and fetch.
- **Existing test gap:** `backend/tests/test_bugfix_api_layer.py:407-441` mocks `_get_cached_data` directly and never tests canonicalization.

### API-014 — Heavy analytics POST contracts are untyped dictionaries

- **Category / severity:** Recommended change / P2
- **Evidence:** Optimize, backtest, and Monte Carlo accept raw `Dict` bodies at `backend/app/api/analytics.py:1645-1650`, `backend/app/api/analytics.py:1738-1744`, and `backend/app/api/analytics.py:1834-1840`. Optimization casts unconstrained values at `backend/app/api/analytics.py:1660-1663`; backtest permits arbitrary numeric ranges and `history_days` at `backend/app/api/analytics.py:1749-1765`; Monte Carlo manually casts body values at `backend/app/api/analytics.py:1853-1897`.
- **Affected flow / callers:** All three compute-heavy endpoints.
- **Why wrong:** Non-finite values, negative costs/lookbacks, and arbitrarily large history/path requests are not rejected consistently before expensive processing. Some values become 500s deep in computation; others can consume excessive resources.
- **Smallest recommended change:** Define bounded request contracts with finite floats, enums, and sensible min/max values so invalid requests fail as 422 before data fetching or solving.
- **Existing test gap:** Tests cover an unknown optimizer strategy (`backend/tests/test_advanced_analytics.py:137-145`) but not numeric finiteness/ranges or oversized history.

### API-015 — Cointegration input has no universe bound despite quadratic work

- **Category / severity:** Improvement / P2
- **Evidence:** `/coint` accepts a comma-separated ticker string with no count/format bound at `backend/app/api/analytics.py:1968-1978` and passes it directly at `backend/app/api/analytics.py:1985-2006`. The service materializes every pair with `combinations(tickers, 2)` at `backend/app/services/cointegration_service.py:383-408` and retains results/spread series through `backend/app/services/cointegration_service.py:433-466`.
- **Affected flow / callers:** `/analytics/coint`, especially with `include_spread_series=true`.
- **Why wrong:** Work and response size grow quadratically. A large accidental list can monopolize a worker and produce a very large response; duplicates also waste pair work.
- **Smallest recommended change:** Canonicalize/deduplicate and enforce a documented maximum universe before pair expansion; return 422 when exceeded.
- **Existing test gap:** `backend/tests/test_p03_coint.py:54-83` tests cache-key collisions only; no route-level universe cap, duplicate, or workload bound test exists.

### API-016 — Refresh counts an empty frame as success

- **Category / severity:** Bug / P2
- **Evidence:** `/data/refresh` increments `refreshed_count` whenever the service returns any non-`None` object at `backend/app/api/data.py:485-491`; it does not require a nonempty frame. It then reports success at `backend/app/api/data.py:496-500`.
- **Affected flow / callers:** Explicit refresh requests for a valid ticker/date window containing no trading rows or an empty result frame.
- **Why wrong:** `refreshed` and the success message can claim data was refreshed when no records were obtained.
- **Smallest recommended change:** Count success only for a nonempty frame and include a stable reason for empty/failed results.
- **Existing test gap:** `backend/tests/test_api_endpoints.py:113-119` covers only nonempty frames; empty-frame refresh is untested.

### API-017 — Multi-setting config update spans two transactions

- **Category / severity:** Bug / P2
- **Evidence:** The route calls `set_primary_source` at `backend/app/api/data.py:214-219`; that helper commits independently at `backend/app/services/source_preference_service.py:64-77`. The route then executes cache-setting writes and commits later at `backend/app/api/data.py:221-240`.
- **Affected flow / callers:** A single `PUT /api/v1/data/config` containing `primary_source` plus either cache setting.
- **Why wrong:** If a later write/commit fails, the primary source remains changed while the request returns 500, violating the apparent all-settings update contract.
- **Smallest recommended change:** Let the route own one transaction for all settings, with one commit/rollback boundary.
- **Existing test gap:** Config tests cover successful roundtrips and invalid source values only; no failure-injection test verifies all-or-nothing behavior.

### API-018 — Post-commit failures are reported as rollbackable failures

- **Category / severity:** Bug / P2
- **Evidence:** Single add commits at `backend/app/api/portfolio.py:238-240` and constructs the response afterward at `backend/app/api/portfolio.py:242-267`; its generic handler then calls rollback and returns 500 at `backend/app/api/portfolio.py:269-274`. Bulk add places both commit and post-commit refresh in one `try` at `backend/app/api/portfolio.py:450-470`, so a refresh failure reports “Database commit failed” and rolls back after the commit is already durable.
- **Affected flow / callers:** Add and bulk-add clients when response construction or post-commit refresh fails.
- **Why wrong:** Stored data can be committed while the client receives 500 and a message implying rollback. Retrying can create confusing duplicate/conflict behavior.
- **Smallest recommended change:** Separate pre-commit validation, commit, and post-commit response phases; never describe or roll back a durable commit as an uncommitted database failure.
- **Existing test gap:** No test injects a refresh or response-construction failure after commit and checks persisted state plus response semantics.

### API-019 — Bulk duplicate holdings are silently discarded from the response

- **Category / severity:** Bug / P2
- **Evidence:** Duplicate canonical tickers are collected and skipped at `backend/app/api/portfolio.py:341-354` without incrementing `failed_count`. The response contains only added, failed, normalized, and added positions at `backend/app/api/portfolio.py:500-509`; `BulkAddResponse` has no duplicate field at `backend/app/models/schemas.py:303-308`.
- **Affected flow / callers:** Bulk import containing existing or repeated tickers.
- **Why wrong:** A request row can disappear with a 200 response and no machine-readable explanation; `added + failed` does not reconcile to the submitted count.
- **Smallest recommended change:** Return explicit duplicate details/count, or reject the entire conflicting request with 409. Do not silently omit holdings.
- **Existing test gap:** `backend/tests/test_coverage_portfolio_api.py:310-333` verifies one database row but not that the duplicate is disclosed to the caller.

### API-020 — WebSocket analytics publishes zero as if measured

- **Category / severity:** Bug / P2
- **Evidence:** Realized volatility, Sharpe, and drawdown initialize to `0.0` at `backend/app/api/websocket.py:180-182`. Metrics are replaced only when there are rows, more than five aligned dates, and positive covered weight at `backend/app/api/websocket.py:184-204`; the values are broadcast unconditionally afterward at `backend/app/api/websocket.py:206-216`.
- **Affected flow / callers:** WebSocket subscribers when one or more holdings lack sufficient cached timeseries or covered allocation.
- **Why wrong:** Missing/insufficient data is presented as measured zero volatility, zero Sharpe, and zero drawdown, which is materially different from unavailable metrics.
- **Smallest recommended change:** Use null for unavailable metrics and include data-quality status; avoid publishing computed-looking zeros without a valid sample.
- **Existing test gap:** `backend/tests/test_bug_sweep_2026_09.py:265-312` covers a mixed-inception case with enough aligned history and asserts volatility is positive; no missing/too-short analytics broadcast test exists.

### API-021 — One slow WebSocket blocks broadcasts to every client

- **Category / severity:** Optimization / P2
- **Evidence:** `broadcast` awaits each client serially at `backend/app/api/websocket.py:56-61`. `send_personal_message` has exception handling but no send timeout at `backend/app/api/websocket.py:48-54`.
- **Affected flow / callers:** Portfolio, analytics, market-data, and manual broadcasts whenever one connected client applies backpressure or hangs.
- **Why wrong:** A single slow socket delays every later client and the background update task. The existing exception cleanup only helps after a failure occurs.
- **Smallest recommended change:** Bound each send with a timeout and dispatch independent clients concurrently with a small concurrency cap.
- **Existing test gap:** `backend/tests/test_websocket.py:81-95` covers an immediately failing socket, not a blocked/slow send or multi-client latency isolation.

### API-022 — Portfolio diagnostics expose holdings and internal exception text

- **Category / severity:** Bug / P2
- **Evidence:** Add logs the full validated position and request type at `backend/app/api/portfolio.py:169-174`; the default logger writes INFO directly to stdout at `backend/app/utils/logger.py:23-53`. Bulk add returns raw exception strings in per-position reasons at `backend/app/api/portfolio.py:371-376` and `backend/app/api/portfolio.py:407-410`, and returns the database exception text at `backend/app/api/portfolio.py:467-470`.
- **Affected flow / callers:** Portfolio add/bulk-add diagnostics, logs, and API clients.
- **Why wrong:** Quantities, buy prices, weights, purchase dates, and custom names are written to logs. Vendor/database exception details can disclose paths, SQL, or provider internals, unlike other portfolio routes that hide details.
- **Smallest recommended change:** Log only non-sensitive request metadata, retain full exceptions server-side with controlled redaction, and return stable safe error codes/messages to clients.
- **Existing test gap:** `backend/tests/test_coverage_portfolio_api.py:718-735` verifies a single-position exception is hidden, but there is no bulk error-leak or log-redaction test.

### API-023 — CSV export writes formula-capable user text verbatim

- **Category / severity:** Bug / P2
- **Evidence:** User/upstream strings, including `custom_name`, sector, and industry, are written directly with `csv.writer` at `backend/app/api/portfolio.py:773-786`. No cell neutralization is applied.
- **Affected flow / callers:** `/portfolio/export/csv` followed by opening the file in a spreadsheet.
- **Why wrong:** A `custom_name` beginning with `=`, `+`, `-`, or `@` can be interpreted as a formula by spreadsheet applications, enabling CSV-formula injection from user-controlled or upstream text.
- **Smallest recommended change:** Neutralize formula-capable text cells during CSV serialization while preserving safe display text.
- **Existing test gap:** `backend/tests/test_coverage_portfolio_api.py:484-532` checks only headers and normal values; no formula-like cell is tested.

### API-024 — Several data fan-out paths remain serial or unbounded

- **Category / severity:** Optimization / P3
- **Evidence:** Batch requests have only `min_length=1` at `backend/app/models/schemas.py:153-158`; the route passes the entire list at `backend/app/api/data.py:409-418`, and the service creates one task per ticker at `backend/app/services/data_service.py:645-660`. Refresh accepts a bare unbounded list and loops serially at `backend/app/api/data.py:469-495`. Other visible serial paths include bulk ticker validation at `backend/app/api/portfolio.py:320-330`, risk-score history fetches at `backend/app/api/analytics.py:1017-1021`, and liquidity-limit history fetches at `backend/app/api/analytics.py:2126-2130`.
- **Affected flow / callers:** Large batch/refresh imports and portfolios with many holdings.
- **Why wrong:** Latency grows linearly in several routes despite existing semaphore/gather patterns elsewhere. Large accepted lists also create large task sets.
- **Smallest recommended change:** Bound collection sizes at the request boundary and reuse the existing bounded-concurrency pattern for independent fetches.
- **Existing test gap:** No test asserts a maximum list size or verifies latency/concurrency bounds.

### API-025 — Shutdown cancels the WebSocket task without awaiting it

- **Category / severity:** Improvement / P3
- **Evidence:** Lifespan calls `cancel()` and immediately disposes database connections at `backend/main.py:63-67`. The WebSocket disconnect path likewise cancels without awaiting at `backend/app/api/websocket.py:319-327`.
- **Affected flow / callers:** Application shutdown/reload and last-client disconnect.
- **Why wrong:** Cancellation is delivered on a later event-loop turn. The background task can still be inside a database operation while the engine is disposed, producing shutdown-only DB errors or unclean task finalization.
- **Smallest recommended change:** Await task completion/cancellation handling before closing database resources.
- **Existing test gap:** Tests enter lifespan against a temp DB but contain no last-client/application-shutdown assertion for task completion (`backend/tests/conftest.py:235-237`).

### API-026 — Error envelope and status policy varies by route

- **Category / severity:** Improvement / P3
- **Evidence:** The global handler returns `{error, message, status_code}` at `backend/main.py:104-117`; `HTTPException` routes return FastAPI's `{detail: ...}`, for example `backend/app/api/portfolio.py:67-68` and `backend/app/api/data.py:211-218`. Analytics domain failures are commonly returned as HTTP 200 with an `error` body at `backend/app/api/analytics.py:230-248` and `backend/app/api/analytics.py:468-483`; performance-history returns an empty 200 list at `backend/app/api/analytics.py:1203-1205`.
- **Affected flow / callers:** Generic clients, frontend error handling, monitoring, and retry logic.
- **Why wrong:** Clients need route-specific parsing and cannot reliably use HTTP status to distinguish no data, invalid input, upstream failure, and success.
- **Smallest recommended change:** Document and enforce one error envelope plus a deliberate status policy, retaining 200-with-empty-data only where explicitly part of the contract.
- **Existing test gap:** No cross-route contract test exists; `backend/tests/test_contract_p1_batch.py:164-173` explicitly codifies 200-with-error for one analytics route, while portfolio tests assert `detail`.

## 4. Test-coverage gaps

1. **Money and portfolio invariants:** no exact mixed-currency total, zero-state 100%, concurrent duplicate insert, or post-commit failure test. Existing tests either align weights with values or assert only positivity/counts (`backend/tests/test_coverage_portfolio_api.py:145-191`, `backend/tests/test_api_endpoints.py:157-170`, `backend/tests/test_coverage_portfolio_api.py:310-333`).
2. **Cache behavior:** no test proves persisted cache settings alter runtime behavior, and no tails test changes weights under an identical ticker/date key (`backend/tests/test_contract_p1_batch.py:176-183`, `backend/tests/test_bugfix_api_layer.py:183-196`).
3. **Security boundary:** no rejected WebSocket Origin/Host, malicious-origin data-read, CSV-formula, or log-redaction test (`backend/tests/test_websocket.py:113-187`).
4. **Async availability:** no heartbeat/concurrency test proves heavy analytics leave the event loop responsive; no bounded-universe/load test exists for coint or bulk fetch routes.
5. **Boundary validation:** no malformed/reversed dates, non-finite rebalance/body values, oversized body/list inputs, invalid risk model, empty refresh frame, or empty custom-ticker liquidity request.
6. **WebSocket data quality/latency:** no insufficient-history analytics assertion and no slow-client broadcast timeout/isolation test (`backend/tests/test_bug_sweep_2026_09.py:265-312`, `backend/tests/test_websocket.py:81-95`).

## 5. API contract, observability, and security summary

- **Contracts:** Portfolio/data/equity-research routes use Pydantic response models in several high-value areas, but analytics mostly returns untyped dictionaries. Currency units, duplicate reporting, error envelopes, and empty-data semantics are not consistent.
- **Transactions:** Portfolio writes generally have explicit commit/rollback paths and bulk successful inserts use one commit. However, config updates are split across transactions, post-commit errors are presented as rollbackable failures, and ticker uniqueness is not database-enforced.
- **Caching:** Explicit market-data purge clears DB and in-process stores, and the tails memo is bounded. The persisted cache controls are not wired to runtime behavior; tails caching is bounded but not allocation-aware; bare ticker cache provenance can be false.
- **Async/optimization:** Vendor I/O is generally offloaded in imported services, and several fetch paths use bounded concurrency. Quantstats, optimization, backtest, Monte Carlo, cone, and tail CPU work still blocks the event loop. Several other fan-outs remain serial.
- **Observability:** Internal exceptions are generally hidden on 500 responses and the global handler records tracebacks. Portfolio add logs full holdings, bulk errors leak raw exception text, and analytics errors are embedded in 200 responses, reducing monitoring and client reliability.
- **Security:** Loopback binding and the default localhost-only CORS origins are appropriate for a local REST application. Security headers, HTTPS redirect, and production TrustedHost are present. The WebSocket Origin/Host gap remains a material browser-origin boundary failure; CSV export and diagnostic logging add bounded exposure.

## 6. Clean areas and limitations

**Clean areas.** `backend/app/api/__init__.py` and `backend/app/api/equity_research.py` are fully clean. Equity-research routes consistently map genuine lookup failures to 404, upstream/runtime failures to 503, and unexpected failures to a generic 500; imported research work is moved to threads. Explicit market-cache purge preserves portfolio truth. Basic security headers, default localhost CORS origins, router registration, successful bulk commit structure, and several bounded semaphore/gather fetch patterns were reviewed and found sound.

**Limitations.** This was a static audit. No live vendor, production database, frontend, deployed proxy, or external browser was exercised, and no performance benchmark was run. The duplicate race, cross-origin WebSocket exposure, event-loop blocking, and cache-key behavior follow directly from the cited control flow and framework contracts. Findings reflect the current working tree only and are restricted to cash equities and portfolio analytics.
