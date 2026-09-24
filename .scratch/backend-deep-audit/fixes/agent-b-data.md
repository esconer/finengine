# Agent B — data/provider/cache implementation report

**Date:** 2026-09-24
**Scope:** B-01 through B-15 from `.scratch/backend-deep-audit/fixes/00-ISSUE-MATRIX.md`.

**Implementation boundary:** Agent B changed the assigned data, provider, cache,
currency, India-ingestion, company-data, source-preference, screener, and
equity-research services; the focused B regression/evidence tests; and this
report. API, models, schemas, database, migrations, configuration, deployment,
and quant-service files were not edited by Agent B. No production database,
vendor network, Docker operation, commit, reset, checkout, clean, stash, or
history rewrite was performed.

## Status

All fifteen B findings have a deterministic service-level regression gate and
current mocked evidence. The combined B gate is green:

- **137 passed** across the B audit tests, P08 cache tests, provider/cache/
  source-preference/India tests, data-service tests, and deep-cache tests; the
  B-owned audit file itself is **24 passed**.
- Ruff is clean for every changed owned service/test file.
- All fifteen `agent-b-*` evidence scripts run without a live vendor call and
  print the current contract result.

The service contract is intentionally conservative: unsupported exchange
identity is unavailable, missing liquidity is `None`, malformed provider rows
are quarantined, and an FX fallback is marked rather than presented as live.

## Evidence method

The executable fixtures are under
`.scratch/backend-deep-audit/fixes/evidence/agent-b-b01-*.py` through
`agent-b-b15-*.py`. Each uses synthetic frames, mocked provider seams, and an
isolated async SQLite database where persistence is involved. The `test_db`
fixture uses `StaticPool` and an isolated database; the evidence scripts do not
open `backend/data/daisy.db`.

Representative command:

```text
$env:PYTHONDONTWRITEBYTECODE='1'
uv run --project backend python .scratch/backend-deep-audit/fixes/evidence/agent-b-b01-cache-controls.py
# repeat for agent-b-b02... through agent-b-b15...
```

The current outputs are summarized below. Baseline symptoms are the recorded
pre-change failures from the audit matrix and the original service audit; the
scripts are rerunnable and do not require a live baseline database.

## Before → after evidence

| ID | Baseline symptom | Current result |
|---|---|---|
| B-01 | Persisted `enable_cache=false` was ignored by the runtime fetch/cache path. | The runtime reads the persisted controls. The fixture makes one vendor call and leaves the seeded row's `fetched_on` unchanged; `test_b01_runtime_controls_bypass_and_ttl` proves no new row is written and that a TTL change invalidates L1. |
| B-02 | Purge left data/company/coint memos and allowed an in-flight fetch to repopulate them. | `data_memo=0`, `coint_memo=0`, `company_memo=0`; the delayed fetch returns empty and leaves `inflight_rows=0`, `inflight_l1=0`. Portfolio rows remain preserved. |
| B-03 | A source switch could serve the previous vendor's warm ticker cache. | After switching to yfinance, the old cache is not served; the source cascade is consulted and the returned frame is sourced from yfinance. |
| B-04 | The first non-empty frame was accepted even when it was outside the requested interval. | The bfinance frame is rejected as `outside_requested_window`; yfinance is called and the accepted dates are exactly the requested dates. |
| B-05 | SQLite excluded the requested end date while Alpha included it. | The boundary fixture reports `sqlite_rows=1` and `boundary_included=True`; vendor requests use an exclusive vendor bound one day beyond the public inclusive end. |
| B-06 | Invalid negative/OHLCV rows were warned about and then persisted; Alpha fallback could overwrite an adjusted primary row. | Two input rows become one valid persisted row; `invalid_persisted=0`. Large-move warnings remain warnings rather than destructive persistence failures, and an existing adjusted yfinance/bfinance row is preserved when an unadjusted Alpha row is offered. |
| B-07 | Null quote sector/industry values could reach non-null ORM fields. | Quote normalization returns `Unknown` for both fields and marks the payload persistence-safe. |
| B-08 | Alpha Vantage silently translated `RELIANCE.NS` to `RELIANCE.BSE`. | `to_av_symbol` returns `None` for unverified `.NS`, `.BO`, and `.BSE` identities; a mismatched returned Alpha symbol raises `AlphaVantageIdentityError`. |
| B-09 | Provider HTTP/auth/rate-limit failures collapsed into generic/raw errors. | HTTP 401 produces `AlphaVantageNotConfiguredError`; 429 produces `ProviderRateLimitError`; exception/log checks contain neither the fake secret nor `apikey=`. |
| B-10 | Null bhavcopy fields became zeros, corrections were skipped, and a conflict could discard a batch. | Incomplete rows are quarantined; duplicate symbols collapse to one row; a correction updates the existing row; FII correction net value is `70.0`. |
| B-11 | Missing history became synthetic ADV/liquidation/Amihud values, and flow lookback consumed calendar days. | Missing history returns `None` for ADV, Amihud, and liquidation days. A measured two-row history returns ADV `1000.0`, positive liquidation time, and a positive Amihud value. Institutional-flow lookback now selects the latest N stored sessions (`lookback_days=2` returns Jan 2 and Jan 5, not Jan 1). |
| B-12 | The fixed FX fallback looked like an ordinary live rate. | The float-compatible rate is `83.0` with `provenance='fallback'`, `is_fallback=True`, and age metadata; strict `convert_amount` raises `CurrencyUnavailableError`; unsupported EUR is rejected. |
| B-13 | Quote field aliases and source identity were incomplete, and mixed returned rows could be mislabeled. | Both `52_week_high` and `week_52_high` aliases are present, quote `source` is present, a mixed returned window is explicitly labeled `source='mixed'`, and adjusted primary rows survive an unadjusted Alpha fallback. Canonical batch keys are used for `RELIANCE` → `RELIANCE.NS`. |
| B-14 | A query-bearing Alpha HTTP exception could put the key in logs. | The current log check reports `log_contains_secret=False` and `log_contains_query=False`. |
| B-15 | Fundamentals/statements lacked a trustworthy source/preference contract. | The yfinance-first historical cascade does not touch bfinance before success, and fundamentals/statements return the actual vendor source. Alpha remains last and is not a selectable primary source. |

## Implemented fixes and current anchors

### B-01/B-02/B-03 — Runtime controls, purge boundary, and source identity

- `backend/app/services/cache_service.py:100-115` defines the effective
  `RuntimeCacheConfig`; `:228-263` reads `app_settings` on every operation and
  fingerprints TTL/enable changes. The durable `expires_at` written at
  `:306-345` remains authoritative, preserving the P08 expiry contract.
- `backend/app/services/cache_service.py:117-134` provides the process-local
  generation fence. Cache writes, fetch logs, and L1 publication check the
  captured generation before commit/publication.
- `backend/app/services/cache_service.py:137-201` clears DataService, quote,
  screener, FX, company, and cointegration memos without deleting portfolio
  truth. `:476-527` purges market tables, advances the generation, and returns
  `portfolio_preserved=True`.
- `backend/app/services/data_service.py:238-255` refreshes runtime settings;
  `:354-395` fences L1 reads by generation/source order; `:485-525` fences
  backfill serving and publication.
- `backend/app/services/source_preference_service.py:25-32,67-101` keeps the
  active bfinance/yfinance cascade, clears market data on a changed preference,
  and exposes the active order to services without a DB handle.
- `backend/app/services/company_data_service.py:75-89,217-272` applies the
  same runtime/generation controls to its 24-hour fundamentals memo.
- `backend/app/services/screener_service.py:118-180,202-227,269-278` makes L1/L2
  screen caches configuration- and generation-aware.

### B-04/B-05/B-06/B-07 — Historical truth, dates, and quote normalization

- `backend/app/services/data_service.py:65-147` parses typed normalized bounds,
  exposes the inclusive `end_exclusive` SQLite bound, and implements the
  conservative `FrameAcceptance` predicate. Non-empty is not sufficient: a
  frame must have rows in the requested window and pass edge/density checks.
- `backend/app/services/data_service.py:543-773` owns the cache miss/vendor
  cascade. Rejected frames continue to the next source, structural warnings do
  not discard valid rows, and persistence failure is not reported as a
  successful fetch.
- `backend/app/services/data_service.py:1100-1180` applies the public inclusive
  end contract to bfinance/yfinance requests (the vendor end is advanced by
  one day) and classifies timeout/provider failures through the shared taxonomy.
- `backend/app/services/data_service.py:1181-1280` keeps the Alpha fallback
  seam identity-safe: returned historical `ticker` values and quote `ticker`
  values must match the requested canonical listing before persistence or
  relabeling.
- `backend/app/services/data_service.py:1347-1443` queries SQLite with
  `date < end + 1 day`, so the final requested calendar day is included.
- `backend/app/services/data_service.py:1445-1590` quarantines non-finite,
  non-positive, negative-volume, invalid-OHLC, and invalid-date rows, collapses
  duplicate dates, and atomically upserts only valid rows. Extreme-move warnings
  remain visible at `:1492-1496`. The Alpha-specific branch at `:1538-1561`
  preserves an existing adjusted primary row while allowing genuinely new dates
  to be stored with explicit Alpha provenance.
- `backend/app/services/data_service.py:767-790` preserves both quote field
  naming conventions, fills nullable metadata with `Unknown`, and records the
  actual source. `:792-937` resolves source order before quote memo use and
  memoizes successful primary/fallback quotes only when the generation remains
  current.

### B-08/B-09/B-14 — Alpha identity, typed errors, and redaction

- `backend/app/services/alpha_vantage_service.py:32-91` has an empty,
  explicit `AV_SYMBOL_MAP`; `.NS`/`.BO`/`.BSE` identities are not substituted
  merely by changing the exchange suffix. A verified operator mapping can be
  added explicitly.
- `backend/app/services/alpha_vantage_service.py:251-332` classifies timeout,
  network, 401/403, 429, 5xx, 400, 404, and vendor notices into the shared
  provider taxonomy. Authentication keys are dropped, frequency-limited keys
  are cooled, and server failures are retryable without a false quota action.
- `backend/app/services/alpha_vantage_service.py:334-385` requests full daily
  output, validates returned symbol metadata when present, filters the public
  inclusive interval, and drops malformed rows.
- `backend/app/services/alpha_vantage_service.py:387-426` preserves the
  requested listing identity in quote output and rejects a mismatched returned
  symbol.
- `backend/app/services/alpha_vantage_service.py:116-123` and
  `:299-330` redact API-key/query material and log status/type rather than raw
  HTTP exception text. The shared safe message helper is in
  `backend/app/services/cache_service.py:30-61`.
- `backend/app/services/company_data_service.py:122-299` and
  `backend/app/services/equity_research_service.py:36-296` preserve typed
  unavailable versus unknown-ticker behavior. Screener vendor failures are
  similarly wrapped at `backend/app/services/screener_service.py:253-278,363-376`.

### B-10/B-11/B-12 — India ingestion, measured liquidity, and FX provenance

- `backend/app/services/india_data_service.py:28-125` defines the required
  bhavcopy field contract and finite/positive/envelope validation. Incomplete
  rows are logged and quarantined rather than converted to zero.
- `backend/app/services/india_data_service.py:127-205` deduplicates within a
  payload (last row is the correction), upserts `(symbol,date)` corrections,
  and has per-row conflict recovery so one race does not erase unrelated valid
  rows. `:206-295` applies the same date-only correction behavior to FII/DII
  flow rows; `:297-318` now returns the latest N stored trading sessions and
  validates a positive integer lookback.
- `backend/app/services/india_data_service.py:35-63` returns `None` for missing
  Amihud/ADV inputs; `:367-454` computes ADV, rupee volume, liquidation days,
  Amihud, tier, and `data_status` only from measured valid history. Missing
  metrics remain `None` and the tier is `UNAVAILABLE`.
- `backend/app/services/currency_service.py:26-73` defines float-compatible
  `FXRate` with provenance/source/fetched-at metadata. `:89-177` validates only
  the currencies the service can actually quote, marks the emergency rate as a
  fallback, and never writes fallback data into the live-rate cache.
- `backend/app/services/currency_service.py:179-211` makes ordinary conversion
  refuse an implicit fallback while retaining an explicit provenance-aware
  seam; `:233-259` exposes age and fallback markers to API consumers.

### B-13/B-15 — Canonical identity, provenance, and precedence

- `backend/app/services/data_service.py:187-212` centralizes canonical ticker
  handling; known bare Indian symbols become `.NS`, existing exchange suffixes
  are retained, and Yahoo-native symbols are not fabricated into Indian
  listings. Batch results use that canonical key at `:939-1005`.
- Historical frames carry `source` and `requested_ticker` attributes and
  `DataService.last_fetch_metadata` records cache/source state at
  `backend/app/services/data_service.py:566-614,670-746`. This gives the API a
  truthful seam without making the service guess from a row outside the
  returned interval; mixed source rows are labeled `mixed` rather than being
  attributed to whichever row happens to be first. The Alpha persistence branch
  at `:1538-1561` likewise preserves adjusted primary rows instead of silently
  replacing them with unadjusted fallback values.
- `backend/app/services/source_preference_service.py:27-32,92-101` keeps
  Alpha Vantage out of the selectable primary set and always appends it only in
  the DataService fallback path. `backend/app/services/data_service.py:694-745`
  preserves Alpha-last behavior after the primary/secondary cascade.
- `backend/app/services/company_data_service.py:122-149,245-272,309-395`
  records the actual fundamentals/statement vendor. The research service is
  intentionally still a bfinance-specific operation; it is not silently fed a
  different security or vendor.

## Tests changed and contract reconciliation

The new focused regression file is
`backend/tests/test_agent_b_data_audit.py:82-377`, with focused gates for
B-01 through B-15 (B-07/B-13 share quote normalization; B-13 also has separate
mixed-window and adjusted-fallback provenance gates; B-14 is covered in the
B-09 redaction test because it shares the provider error boundary).

The following legacy tests encoded contracts that directly contradicted the
new B-08/B-10/B-11/B-13 behavior and were updated to assert the safer contract:

- `backend/tests/test_alpha_vantage.py:61-92` and
  `backend/tests/test_coverage_alpha_vantage.py:32-35,155-196` now use a global
  symbol for ordinary rotation/quote tests and assert `.NS`/`.BO`/`.BSE`
  identity is unavailable rather than silently bridged.
- `backend/tests/test_bugfix_providers_05.py:280-355` now expects unavailable
  metrics for a volume-only frame, quarantines incomplete bhavcopy data, and
  tests real idempotent/corrected SQLite writes rather than obsolete mocked
  execution counts.
- `backend/tests/test_coverage_data_service.py:329-360` now supplies the
  requested NSE identity on a successful fallback and asserts that a mismatched
  BSE payload raises `AlphaVantageIdentityError` rather than being relabeled.
- `backend/tests/test_coverage_india_data.py:26-44,84-100` now expects `None`
  for empty Amihud/zero-ADV inputs and supplies the required trade-count field
  plus varied delivery history for the anomaly check.
- `backend/tests/test_deep_cache.py:159-179` no longer codifies the old
  end-exclusive behavior; an entirely uncovered requested window now raises a
  typed `ProviderUnavailableError` instead of returning an empty/mislabeled
  slice.
- `backend/tests/test_coverage_data_service.py:272-296` now blocks both provider
  seams around the mocked timeout branches; the executor is submitted before
  `wait_for`, so this prevents a test double from leaking a live request.

These are contract updates, not weakened coverage: each replacement checks
unavailability, identity, correction, or typed error behavior explicitly.

## Verification commands and results

All commands used `PYTHONDONTWRITEBYTECODE=1`, `uv run --project backend`,
`-p no:cacheprovider`, and `--no-cov`.

### Focused B/provider/cache gate

```text
$env:PYTHONDONTWRITEBYTECODE='1'
uv run --project backend pytest -p no:cacheprovider --no-cov -q `
  backend/tests/test_agent_b_data_audit.py `
  backend/tests/test_p08_cache.py `
  backend/tests/test_bugfix_providers_05.py `
  backend/tests/test_alpha_vantage.py `
  backend/tests/test_coverage_alpha_vantage.py `
  backend/tests/test_coverage_india_data.py `
  backend/tests/test_source_preference_and_cache.py `
  backend/tests/test_coverage_data_service.py `
  backend/tests/test_data_services.py `
  backend/tests/test_deep_cache.py
```

Result: **137 passed**.

Adjacent integration checks also pass on the current shared tree:

- `backend/tests/test_agent_c_api_contracts.py`: **39 passed**
- `backend/tests/test_coverage_portfolio_api.py`: **19 passed**
- `backend/tests/test_agent_d_migrations.py backend/tests/test_agent_d_deployment_contract.py`: **19 passed**
- C/API/WebSocket/portfolio compatibility: **115 passed**

These checks validate the API/schema/DB handoff around the B seams; they do
not change B ownership.

### Ruff

```text
$env:PYTHONDONTWRITEBYTECODE='1'
uv run --project backend ruff check --no-cache `
  backend/app/services/cache_service.py `
  backend/app/services/data_service.py `
  backend/app/services/alpha_vantage_service.py `
  backend/app/services/currency_service.py `
  backend/app/services/india_data_service.py `
  backend/app/services/company_data_service.py `
  backend/app/services/source_preference_service.py `
  backend/app/services/screener_service.py `
  backend/app/services/equity_research_service.py `
  backend/tests/test_agent_b_data_audit.py `
  backend/tests/test_bugfix_providers_05.py `
  backend/tests/test_alpha_vantage.py `
  backend/tests/test_coverage_alpha_vantage.py `
  backend/tests/test_coverage_india_data.py `
  backend/tests/test_coverage_data_service.py `
  backend/tests/test_deep_cache.py
```

Result: **All checks passed!** `git diff --check` produced no whitespace
errors; Git emitted only the repository's existing LF/CRLF conversion warnings.

The broader full-suite result belongs to the coordinator's cross-owner pass;
this B report does not claim that unrelated API/foundation/quant failures are
B-owned. The focused gate above is the acceptance gate for this service slice.

## Cross-owner handoff

### C — API boundaries

1. Use `DataService.last_fetch_metadata` and returned-frame `attrs["source"]`
   for historical `from_cache`/source fields. The current C-owned data route
   has a returned-window provenance helper around
   `backend/app/api/data.py:98-151,473-564`; preserve that behavior when
   integrating further API edits.
2. Map the shared `ProviderError.status_code` taxonomy from
   `backend/app/services/cache_service.py:36-97` to stable API responses
   (429/503/404/400/502) instead of converting every service exception to 404
   or an in-body 200. C's current API tests cover the adjacent route contracts.
3. The current C/D tree now retains quote source/currency/aliases and the
   previous-close/change fields in `StockQuoteResponse`; preserve that schema
   contract when changing the route. The B service emits both quote naming
   conventions so this remains backward-compatible.
4. The current C-owned config route writes the validated source and cache
   settings in one transaction and calls the B generation/memo fence directly;
   preserve that atomic path. A no-commit B helper such as `upsert_primary_source`
   is only needed if another caller must compose the source write into its own
   transaction; standalone `set_primary_source` intentionally retains its
   compatibility commit.

### D — persistence and schema

1. Preserve the D-owned case-insensitive ticker uniqueness, non-null metadata,
   and OHLCV/flow constraints as the final safety net, with C continuing to
   write canonical ticker spellings. If suffix variants must be rejected across
   processes, add the D-owned canonical-ticker column/index described in the
   audit; do not rely only on the API precheck. B's sanitizer is the provider
   boundary and must not be replaced by a model-only rejection that loses valid
   rows from a mixed batch.
2. Keep the unique `(ticker,date)`, `(date,category)`, and bhavcopy natural
   keys required by the B upsert paths. Existing duplicate-data migrations
   should remain blocking/operator-reconciled rather than silently deleting
   market truth.
3. If a persisted position-currency column is added, backfill and constrain it
   to the currencies actually supported by the B currency service; do not
   advertise EUR/GBP/JPY/AED as convertible unless the service is extended.

### A — cache and quant seams

1. Keep cointegration's cache identity generation/lookback work in the
   A-owned service. B's purge intentionally clears the cointegration L1 memo;
   the coordinator now also fences late pair writes with the captured cache
   generation in `backend/app/services/cointegration_service.py:368-428,475-529`.
2. The API active-mask seam is closed: forecast, wide-return, and
   single-holding optimization paths preserve missing prices rather than
   pre-filling them.

## Known limitations / explicit follow-ups

- The generation fence and process-local memos are intentionally process-local.
  They prevent stale in-process publication in the current single-process
  deployment; a multi-worker deployment needs a shared invalidation mechanism.
  DataService, company, screener, currency, and cointegration writes now honor
  the current generation where those paths are process-local.
- Alpha Vantage Indian exchange fallback is unavailable until an operator adds
  a verified, security-specific `AV_SYMBOL_MAP` entry. Returning `None` is the
  safe result; it is not a request to reintroduce a blind `.BSE` bridge.
- The delivery-anomaly helper still derives its historical cutoff from calendar
  days (`:320-357`); if that endpoint is required to promise exchange-session
  semantics too, it needs a separate NSE-calendar decision. The institutional
  flow endpoint itself now uses stored-session lookback.
- `validate_ticker` still probes only the selectable bfinance/yfinance tiers.
  If an Alpha-only listing must pass validation before the fallback path, add a
  bounded identity-safe Alpha probe and an explicit API contract.
- Executor cancellation after a vendor timeout remains a platform limitation
  (DATA-016). B now classifies the timeout and avoids false success logging,
  but cannot make an already-running `run_in_executor` worker disappear.
- Equity research/AI operations remain bfinance-specific by design. If a
  second research provider is required, add an explicit identity-aware cascade
  and tests rather than reusing the market-data symbol substitution rules.
- A full no-network deployment run was not performed in this B pass. The
  hermetic service gates, isolated SQLite fixtures, and mocked evidence are the
  acceptance evidence for B-owned behavior.

## Handoff status

The B-owned data/provider/cache slice is ready for coordinator integration.
The exact remaining work is cross-owner contract wiring and explicit product
decisions listed above; the focused B-owned service gates have no unresolved
B-01..B-15 regression, with the cointegration in-flight fence explicitly handed
to A.

## Coordinator addendum

After the B handoff, the coordinator closed the remaining cross-owner seams:

- `backend/app/api/data.py` now derives provenance from the returned date
  window, canonicalizes the response ticker, maps typed provider failures to
  stable statuses, threads source order into statements, and invalidates old
  source rows in the same config transaction.
- `backend/app/models/schemas.py` retains quote source/currency/aliases and
  makes confidence-neutral EVT fields primary.
- `backend/app/api/analytics.py` now passes explicit `lookback_days` to the
  coint scanner, uses the shared active-return helper, and maps mixed-FX
  provider outages to HTTP 503.
- `backend/app/services/cointegration_service.py` now captures the cache
  generation before pair analysis and drops late writes after a purge/source
  switch.
- The institutional-flow lookback regression was extended to prove the latest
  stored-session contract; `test_agent_b_data_audit.py` now has 24 passing
  tests.

The coordinator evidence oracle is
`.scratch/backend-deep-audit/fixes/evidence/agent-coordinator-integration.py`
with result `.after.txt`: **10 passed, 0 failed**. The legacy provider
compatibility set currently reports **115 passed** in the hermetic focused run.

## Residual reviewer closure (2026-09-24)

The final residual review added a startup-generation regression and a direct helper-generation fence in `data_service.py`; stale historical fetches now return no frame and cannot leave rows after a purge advances the token. The quote-purge race is now fenced as well: the B audit file is **24 passed**, the B/provider/cache gate is **137 passed**, and the focused A/B gate is **45 passed**. The currency service now exposes explicit fallback provenance and the API adapters require verified live provenance; fallback rates are refused by default. The integrated coordinator gate is **224 passed** after the final quote follow-up. Live vendor and production-database verification remain intentionally unperformed. The final independent residual
review marked the generation and strict-FX seams **PASS**.
