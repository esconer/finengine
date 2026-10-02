# LEDGER — consolidated audit, 2026-10-02

**This file fixes nothing.** It ranks, caps and deduplicates five writers' verified output into one
ledger. Every row is a finding re-derived by the writer who owns its namespace and re-opened at the
cited line; none was reproduced at runtime. Row ids are the writers' own stable ids, so a row here
traces to exactly one place in `detail/`.

**Severity** = `BLOCKER` (wrong number reaches the user, money, or availability) · `DEFECT` (real bug,
bounded blast radius, workaround exists) · `RISK` (will bite later, or developer-facing) · `NIT`.
**Confidence** = `VERIFIED` (mechanism traced in source) · `DERIVED` (logical, nothing executed) ·
`NEEDS-RUNTIME`. **The two axes are orthogonal and are never collapsed into one priority number** — a
`DERIVED` BLOCKER and a `VERIFIED` RISK are different kinds of statement. Rows are ranked by severity,
then confidence; within equal confidence the tiebreak is blast radius (user-visible wrong number, then
crash, then contract, then developer-facing) and finally the id, so the order is stable.

**Ranking tiebreak, stated because it is a choice:** §1 lists the two wrong-number findings first, then
the five CI defects in pipeline order, then the availability finding. §2 lists fabrications first.
§3 lists fabrications, then integrity/concurrency, then test-harness, then supply chain, `VERIFIED`
before `DERIVED`.

---

## §0 Verdict

**Not ship-blocking in the narrow sense, but two of the eight blockers publish a wrong figure on every
load of a page a portfolio owner reads before sizing a position** — `SVC-2` hands out `sharpe_ratio: 0.0`
for any flat, frozen or all-NaN series, and `OE-02` renders volatility 100x low with a green "Low" badge
on every row. The larger structural fact is that **this repository has never produced a green CI run**:
three independent fatal defects, each verified against current source — `INF-3` and `INF-4` red the
`backend` job, `INF-1` and `INF-2` red the `frontend` job at its `docker build` step, and `INF-5` makes
the `integration` job's `docker compose --wait` permanently unsatisfiable. Because `production-images`
sits behind all of them via `needs:` (`ci-cd.yml:143`, `:165`, `:224`), **no container image has ever
been published by CI** — and a permanently-red pipeline reads as "no news" rather than "structurally
broken". Pre-cap counts, before any cap was applied: **BLOCKER 8 (cap 10) · DEFECT 21 (cap 25) · RISK 30
(cap 40) · NIT 8 (cap 30) — 67 rows. No band reached its cap and nothing was deferred or truncated.**
10 further items could not be settled by reading and are quarantined in `unverified.md`, each with the
exact command that would close it. Nothing in this audit was reproduced at runtime; every row is
source-verified and every "how often" and "how expensive" claim is explicitly disclaimed in its detail file.

**What matters most:**

- **CI has never been green.** `INF-3` + `INF-4` red `backend`; `INF-1` + `INF-2` red `frontend`; `INF-5`
  makes `integration` unrunnable. `production-images` needs all four plus `security`, so it has never
  run. There is therefore **no automated evidence that any image in ghcr or ECR has ever been built** —
  which is a different and much worse claim than "CI is flaky". Nothing in the pipeline is merely
  un-green; three separate fatal defects sit on a chain that must be entirely green.
- **The anti-fabrication culture is real, deliberate, and working.** Roughly 20 sites deliberately
  preserve a missing value instead of substituting one, several with comment blocks explaining why a
  `fillna(0.0)` was removed; `analytics_engine.py:5439-5447` states in the authors' own words that "a
  hard zero on an unmeasured quantity is the one number a reader must never be handed"; and this run
  **retired 22 prior findings as verified-closed with current-code proof** plus 692 lines of dead code
  already deleted. The defects below are the residual where that discipline lapsed, not evidence that
  the discipline is absent. §1-§4 should not be read as a description of this codebase.
- **The dominant defect class is "uncomputed statistic published as computed", with 16 live instances
  across the layer boundary.** 15 are ledger rows and 1 is quarantined (`FE-2`, un-rejected by COR-1):
  `SVC-1`, `SVC-2`, `SVC-4`, `SVC-6`, `SVC-9`, `SVC-10`, `API-3`, `API-10`, `FE-1`, `FE-3`, `FE-4`,
  `FE-7`, `OE-01`, `OE-02`, `OE-09`, and `FE-2`. Each crosses a boundary — service to API, API to store,
  store to component — and at each crossing the absence is converted into a value that is then
  indistinguishable from a measurement. That single mechanism, not any one file, is the codebase's
  main risk.
- **The recurring author-side hazard is a guard that exists, reads as correct, and is structurally
  unreachable.** Three frontend findings are exactly this: `FE-1`'s `Number.isFinite(...)` is always
  true because its helper returns `number` and absorbs `NaN` at the terminal `return 0`; `FE-7`'s
  `?? 'N/A'` is dead because the store laundered the absence into `0` one layer upstream; `COR-3` shows
  the mirror image, where `:203` substitutes `[]` and `:206` still throws on it. The audit question is
  not "is there a guard?" but **"can this guard observe the value it tests?"** (COR-4.)
- **Two documented author-side hazards recur**: a `max_length` cap is applied everywhere *except* the
  one list that reaches a vendor (`API-1`, against `analytics.py:133/135/168/184` and `data.py:44`); and
  a fabrication guard is applied to the short-sample branch but not the equivalent degenerate-value
  branch (`SVC-2` mirrors the `< 10` fix at `:5460-5461` without the zero-variance fix at `:5468`).
- **One duplicate was merged, not two rows filed.** `OE-14` (prior art, BLOCKER) and `FE-5` (fresh,
  DEFECT) are one defect: `.toFixed()` on `Optional[float] current_spread_zscore` at
  `dashboard/pairs/page.tsx:145`. Precedence is the fresh row (`FE-5`), per plan §4; `OE-14` survives as
  an `also found by` note on it. The two writers did **not** share a lineage — `FE-5` came from a fresh
  survey of `frontend/src`, `OE-14` descends from `data-correctness-2026-09` — so the merge is two
  independent surveys agreeing on a still-live defect, not one finding counted twice. The severity
  disagreement is disclosed, not silently resolved: see the `FE-5` row.
- **A sixth slice arrived after this ledger was assembled and its live findings are deliberately NOT
  ranked here.** `detail/research-doc-accuracy.md` (written 21:35, `docs/research/` fact-check) landed
  after assembly began. It is **documentation-accuracy only**: it assigns **no id namespace and no
  severity or confidence**, so ranking it would mean inventing band assignments, which this ledger does
  not do. It is enumerated in `STATUS.md` §4.5 instead — briefly: it confirms six live defects that
  carry **no row below** (Black-Litterman `w_mkt = np.ones(n)/n` and silent clip+renorm at
  `optimization_service.py:791`/`:848`; a published HMM transition matrix that is a prior and was never
  fitted at `regime_service.py:307-323`; hardcoded per-ticker and 7x7 sector stress elasticities at
  `analytics_engine.py:374`/`:388`; `/vol-cone` validating `lookback_days` at `analytics.py:12330`
  without passing it; the EWMA seed/iterate window mismatch at `analytics_engine.py:5996`; and a
  `quantlib` pin at `pyproject.toml:37` that is imported nowhere). **Those six are unranked here and a
  reader must not read §1-§4 as a complete defect census.** It also overlaps this ledger twice: its
  unreachable-`except HTTPException` finding is already `API-7`, and its `quantlib` finding is already
  the QH-10 half of `OE-15`. What it retires is as valuable as what it finds: the corpus' #1-ranked
  recommendation (a `quantstats` pin upgrade) is **already shipped** at `pyproject.toml:21`, and
  ADF/KPSS stationarity is **already implemented** at `cointegration_service.py:15` despite a
  capability table reading "not implemented".

---

## §1 BLOCKER (cap 10) — 8 found, 8 shown, 0 deferred

Every BLOCKER carries a reproduction in its detail file, per plan §3.

| id | title | sev | conf | location | symptom | detail |
|---|---|---|---|---|---|---|
| SVC-2 | `sharpe_ratio` and `sortino_ratio` publish a hard `0.0` on a zero or NaN denominator | BLOCKER | VERIFIED | `backend/app/services/analytics_engine.py:5468` | Every realized-risk block reports `sharpe_ratio: 0.0` for a flat, frozen or all-NaN series — directionally wrong, not merely unmeasured. | [SVC-2](detail/services.md#svc-2--sharpe_ratio-and-sortino_ratio-publish-a-hard-00-on-a-zero-or-nan-denominator) |
| OE-02 | `/portfolio/manage` renders return-space volatility 100x low and always badges "Low" | BLOCKER | VERIFIED | `frontend/src/app/portfolio/manage/page.tsx:799` | A real 25.4% volatility renders `0.25%`; every row badges green "Low" because `0.25 < 20` is always true. | [OE-02](detail/prior-art.md#oe-02--portfoliomanage-renders-return-space-volatility-100-low-and-always-badges-low) |
| INF-3 | The `backend` CI job cannot pass: a localhost-only smoke test is collected by the unit run | BLOCKER | VERIFIED | `.github/workflows/ci-cd.yml:51` | `pytest tests/` collects `test_compose_services.py`, which `urlopen`s `127.0.0.1:8000` on a runner with nothing listening; job is red on every push. | [INF-3](detail/infra-tests.md#inf-3--the-backend-ci-job-cannot-pass-a-localhost-only-smoke-test-is-collected-by-the-unit-run) |
| INF-4 | The 57-rule audit gate is bound to one developer's `%TEMP%` and hard-fails without it | BLOCKER | VERIFIED | `backend/tests/test_audit_rule_coverage.py:77` | `BASE_EXPORT` is an absolute path outside the repo; `_base_document` calls `pytest.fail` when it is missing, so the gate has never executed in CI. | [INF-4](detail/infra-tests.md#inf-4--the-57-rule-audit-gate-is-bound-to-one-developers-temp-and-hard-fails-without-it) |
| INF-1 | Frontend Docker build cannot succeed: `.next/standalone` is copied but never emitted | BLOCKER | VERIFIED | `frontend/Dockerfile:45` | `COPY --from=builder /app/.next/standalone ./` aborts the build — `next.config.ts` has no `output` key, so Next never emits that directory. | [INF-1](detail/infra-tests.md#inf-1--frontend-docker-build-cannot-succeed-nextstandalone-is-copied-but-never-emitted) |
| INF-2 | Base image `node:18-alpine` is below Next 16.3.6's declared Node engine floor | BLOCKER | VERIFIED | `frontend/Dockerfile:2` | `next build` runs on Node 18 while `next@16.3.6` declares `node >= 20.9.0`; no `engines` field exists to warn locally. | [INF-2](detail/infra-tests.md#inf-2--base-image-node18-alpine-is-below-next-1636s-declared-node-engine-floor) |
| INF-5 | Backend container healthcheck parses `DATABASE_URL` with `rsplit`, yielding a relative path | BLOCKER | VERIFIED | `backend/Dockerfile:52` | With the shipped four-slash URL, `rsplit('///',1)[1]` returns the relative `app/backend/data/daisy.db`; the parent directory was never created, so the container never reports healthy. | [INF-5](detail/infra-tests.md#inf-5--backend-container-healthcheck-parses-database_url-with-rsplit-yielding-a-relative-path) |
| API-2 | `GET /analytics/tear-sheet` runs unbounded synchronous work on the event loop, skipping the module's own `_run_cpu` gate | BLOCKER | VERIFIED | `backend/app/api/analytics.py:9411` | Eleven inline quantstats calls plus five 1000-resample uncertainty blocks run on the loop; every other route on that worker stalls and the websocket broadcast pauses. | [API-2](detail/api.md#api-2--get-analyticstear-sheet-runs-unbounded-synchronous-work-on-the-event-loop-skipping-the-modules-own-_run_cpu-gate) |

## §2 DEFECT (cap 25) — 21 found, 21 shown, 0 deferred

| id | title | sev | conf | location | symptom | detail |
|---|---|---|---|---|---|---|
| SVC-1 | A NaN mean volume is not caught before the tier ladder and publishes a measured-looking score | DEFECT | VERIFIED | `backend/app/services/analytics_engine.py:3945` | Python's `min(5.9, nan)` returns `5.9`, so a NaN volume publishes `score 5.9` / `Low` / `High risk` with nothing marking it fabricated. | [SVC-1](detail/services.md#svc-1--a-nan-mean-volume-is-not-caught-before-the-tier-ladder-and-publishes-a-measured-looking-score) |
| SVC-9 | `equity_research_service` publishes `current_price: 0.0` as a real price | DEFECT | VERIFIED | `backend/app/services/equity_research_service.py:57` | A card shows Rs 0 for a ticker whose provider returned no quote; the four adjacent fields correctly end as `None`. | [SVC-9](detail/services.md#svc-9--equity_research_service-publishes-current_price-00-as-a-real-price) |
| SVC-10 | A failed t-fit substitutes `nu = 4.0`, which is indistinguishable from a fitted value | DEFECT | VERIFIED | `backend/app/services/tail_risk_service.py:503` | The bare `except` substitutes a literal inside the success-path clip range, so `lambda_l` consumes it as a fit; the GPD path discloses `fit_failed`, this one does not. | [SVC-10](detail/services.md#svc-10--a-failed-t-fit-substitutes-nu--40-which-is-indistinguishable-from-a-fitted-value) |
| SVC-4 | `screener_service._filter` turns absent fundamentals into `0.0` against lower bounds, while `pe` is excluded | DEFECT | VERIFIED | `backend/app/services/screener_service.py:317` | `None or 0.0` admits an unmeasured company through ROCE/ROE/market-cap lower bounds, and the absence is disclosed nowhere; line 319 takes the opposite position on the same question. | [SVC-4](detail/services.md#svc-4--screener_service_filter-turns-absent-fundamentals-into-00-against-lower-bounds-while-pe-is-excluded) |
| SVC-6 | `backtest_service` silently shortens `lookback_days`, and the payload discloses the wrong quantity | DEFECT | VERIFIED | `backend/app/services/backtest_service.py:65` | A requested 252-day lookback can become `max(20, 0.4*n)`, and `history_days_analyzed` reports the *input* frame length, not the simulated sample. | [SVC-6](detail/services.md#svc-6--backtest_service-silently-shortens-lookback_days-and-the-payload-discloses-the-wrong-quantity) |
| SVC-7 | The backtest annualises without the `MIN_ANNUALIZE_DAYS` gate the codebase already defines | DEFECT | VERIFIED | `backend/app/services/backtest_service.py:185` | About 10 simulated days yields `years = 0.0397`, so `cum[-1] ** 25.2` is published as a CAGR; the gate exists and is applied to the input frame instead. | [SVC-7](detail/services.md#svc-7--the-backtest-annualises-without-the-min_annualize_days-gate-the-codebase-already-defines) |
| SVC-8 | `compute_rolling_avg_correlation` averages over a shrinking pair denominator | DEFECT | VERIFIED | `backend/app/services/correlation_service.py:62` | `DataFrame.mean(axis=1)` skips NaN, so a date with 2 of 990 measurable pairs publishes their mean and sets `alert_level` / `is_regime_break`. | [SVC-8](detail/services.md#svc-8--compute_rolling_avg_correlation-averages-over-a-shrinking-pair-denominator) |
| OE-05 | A 2% risk-free rate is hardcoded twice and never justified for an Indian book | DEFECT | VERIFIED | `backend/app/config.py:53` | `config.py:53` and `analytics.py:555` are two sources of truth; Sharpe, Sortino, alpha, beta's excess leg and the optimiser objective all deduct it. The response discloses the rate, never that it is a placeholder. | [OE-05](detail/prior-art.md#oe-05--a-2--risk-free-rate-is-hardcoded-twice-and-never-justified-for-an-indian-book) |
| OE-04 | Benchmark is `^NSEI`, a price index, with no published provenance | DEFECT | VERIFIED | `backend/app/services/benchmark_service.py:20` | `_CLOSE_CANDIDATES` prefers `adj_close` then `close`, so whether the two legs share a basis is decided silently by vendor output and published nowhere. | [OE-04](detail/prior-art.md#oe-04--benchmark-is-nsei-a-price-index-with-no-published-provenance) |
| OE-03 | Liquidity turnover uses `mean(volume) x last_close` instead of `mean(volume x close)` | DEFECT | VERIFIED | `backend/app/services/analytics_engine.py:3947` | Two independent aggregates multiplied together is not `E[V*P]`; the error is exactly the covariance term plus a terminal price in place of the mean, and it feeds all four tiers. | [OE-03](detail/prior-art.md#oe-03--liquidity-turnover-uses-meanvolume--last_close-instead-of-meanvolume--close) |
| OE-01 | Scale-sniffing percent formatter on three dashboard pages | DEFECT | VERIFIED | `frontend/src/app/dashboard/stress-testing/page.tsx:557` | A fraction over 1.0 passes through unscaled, so a real 250% volatility renders `2.5%` and the stress severity ladder grades it "Low". | [OE-01](detail/prior-art.md#oe-01--scale-sniffing-percent-formatter-on-three-dashboard-pages) |
| API-3 | Two no-data branches stamp `as_of` with today and one labels a non-existent observation "latest available" | DEFECT | VERIFIED | `backend/app/api/analytics.py:11920` | `/coint` asserts `as_of = today`, `as_of_semantics = "latest_available_observation"` and `latest_observation_date = null` simultaneously; `CorrelationStabilityResponse` has no semantics field at all. | [API-3](detail/api.md#api-3--two-no-data-branches-stamp-as_of-with-today-and-one-of-them-labels-a-non-existent-observation-latest-available) |
| API-1 | `bulk_add` accepts an uncapped position list and validates it one vendor round-trip at a time | DEFECT | VERIFIED | `backend/app/models/schemas.py:374` | `positions` has no `max_length` and the validation comprehension `await`s serially into `yf.Ticker(...).history()`, while the same route later gathers 5-wide. | [API-1](detail/api.md#api-1--bulk_add-accepts-an-uncapped-position-list-and-validates-it-one-vendor-round-trip-at-a-time) |
| OE-10 | `/screens/custom` uses the module-global screener singleton its own docstring forbids | DEFECT | VERIFIED | `backend/app/api/equity_research.py:252` | `get_screener_service()` memoises a service holding a session-scoped `CacheService`, so custom screens can read another request's transaction state; `ValueError` also surfaces as 500. | [OE-10](detail/prior-art.md#oe-10--screenscustom-uses-the-module-global-screener-singleton-its-own-docstring-forbids) |
| FE-5 | Pairs page calls `.toFixed()` on a field the backend publishes as `Optional[float] = None`; the throw blanks the whole route *(also found by `OE-14`; prior art rated it BLOCKER — severity disagreement disclosed)* | DEFECT | VERIFIED | `frontend/src/app/dashboard/pairs/page.tsx:145` | `current_spread_zscore` is `Optional` by design; through `useState<any[]>` the `.toFixed(2)` throws during render and `app/error.tsx` replaces the entire route with `Cannot read properties of null`. | [FE-5](detail/frontend.md#fe-5--pairs-page-calls-tofixed-on-a-field-the-backend-publishes-as-optionalfloat--none-the-throw-blanks-the-whole-route) |
| COR-3 | `setPortfolioSnapshot` substitutes `[]` on the line above the field it then reads `.length` on *(promoted by `ORCHESTRATOR-CORRECTIONS.md` COR-3)* | DEFECT | VERIFIED | `frontend/src/lib/store.ts:206` | If `snapshot.positions` is absent, `:203` substitutes `[]` and `:206` throws on `undefined.length` — the substitution does not protect the line below it. Promoted by COR-3. | [COR-3](ORCHESTRATOR-CORRECTIONS.md#cor-3--the-adjacent-bug-a2-found-but-did-not-emit-is-real) |
| FE-1 | The unrealized-P/L `%` guard on `/portfolio/manage` is unreachable; the `N/A` branch is dead code | DEFECT | VERIFIED | `frontend/src/app/portfolio/manage/page.tsx:786` | `monetaryValue` returns `number` and its terminal `return 0` absorbs `NaN`, so `Number.isFinite` is always true and an uncostable holding renders green `+0.00%`. | [FE-1](detail/frontend.md#fe-1--the-unrealized-pl--guard-on-portfoliomanage-is-unreachable-the-na-branch-is-dead-code) |
| FE-4 | "Add to portfolio" from the screener fabricates `buy_price: 0`, which the backend rejects as an opaque 422 | DEFECT | VERIFIED | `frontend/src/app/dashboard/screener-studio/page.tsx:177` | `stock.price or 0` posts 0; `schemas.py:17` carries `gt=0` so nothing is persisted — the user gets `buy_price: Input should be greater than 0` for a row rendering `Rs undefined`. | [FE-4](detail/frontend.md#fe-4--add-to-portfolio-from-the-screener-fabricates-buy_price-0-which-the-backend-rejects-as-an-opaque-422) |
| FE-6 | The live-connection chip has only two states, so it asserts "connecting" forever after the user turns Live off | DEFECT | VERIFIED | `frontend/src/components/layout/RealtimeStatus.tsx:41` | With `liveDataMode` false the socket is actively disconnected and the effect returns early, but the chip has no "off" state to render. | [FE-6](detail/frontend.md#fe-6--the-live-connection-chip-has-only-two-states-so-it-asserts-connecting-forever-after-the-user-turns-live-off) |
| INF-9 | `test_coverage_direct_unit_routes.py`: 24 assertions that cannot fail | DEFECT | VERIFIED | `backend/tests/test_coverage_direct_unit_routes.py:115` | `assert <result> is not None` on FastAPI handlers is unfalsifiable by contract; 311 such assertions exist across 77 files, and this file contributes to a real 80% gate. | [INF-9](detail/infra-tests.md#inf-9--test_coverage_direct_unit_routespy-24-assertions-that-cannot-fail) |
| INF-6 | Frontend prod-image healthcheck calls `curl`, which alpine does not ship | DEFECT | VERIFIED | `frontend/Dockerfile:58` | `node:*-alpine` ships BusyBox `wget`; the probe exits 127 forever. Both compose files override it with a working `node -e fetch`, so the blast radius is the pushed image. | [INF-6](detail/infra-tests.md#inf-6--frontend-prod-image-healthcheck-calls-curl-which-alpine-does-not-ship) |

## §3 RISK (cap 40) — 30 found, 30 shown, 0 deferred

| id | title | sev | conf | location | symptom | detail |
|---|---|---|---|---|---|---|
| FE-7 | The portfolio store launders an absent `total_value` into a measured `0`, at two sites, before any consumer can see it was absent | RISK | VERIFIED | `frontend/src/lib/store.ts:171` | `or-zero` converts absent and `NaN` to a confident Rs 0 that is indistinguishable from a genuinely empty book; `dashboard/page.tsx:423`'s `?? 'N/A'` is therefore dead. | [FE-7](detail/frontend.md#fe-7--the-portfolio-store-launders-an-absent-total_value-into-a-measured-0-at-two-sites-before-any-consumer-can-see-it-was-absent) |
| FE-8 | Header's PDF export total silently drops every holding with no measured value | RISK | VERIFIED | `frontend/src/components/layout/Header.tsx:96` | `?? 0` folds an unmeasured holding into the printed `Total Portfolio Value`, producing a PDF lower than the sum of its own table with no exclusion count. | [FE-8](detail/frontend.md#fe-8--headers-pdf-export-total-silently-drops-every-holding-with-no-measured-value) |
| OE-09 | `_empty_concentration` publishes `diversification_score 0.0` — and says so in the source | RISK | VERIFIED | `backend/app/services/analytics_engine.py:6324` | An empty book returns the same pair as a measured single-holding book; the sibling `_empty_liquidity` was corrected to `None` for exactly this reason. | [OE-09](detail/prior-art.md#oe-09--_empty_concentration-publishes-diversification_score-00--and-says-so-in-the-source) |
| API-10 | Tear-sheet metric failures are logged at `debug` with no metric name and no exception type | RISK | VERIFIED | `backend/app/api/analytics.py:537` | Any of eleven metrics can become `null` with nothing above debug level and no way to tell which one failed; the same file logs every other failure at error/warning with the type. | [API-10](detail/api.md#api-10--tear-sheet-metric-failures-are-logged-at-debug-with-no-metric-name-and-no-exception-type) |
| SVC-3 | `_store_timeseries_data` executes DB writes outside the lock the file's own comment says is required | RISK | VERIFIED | `backend/app/services/data_service.py:1700` | Three call sites, two inside `async with self._db_lock:` and one (`:1339`) not, contradicting the invariant stated at `:238-243`. Not observed to collide; the source fact is verified. | [SVC-3](detail/services.md#svc-3--_store_timeseries_data-executes-db-writes-outside-the-lock-the-files-own-comment-says-is-required) |
| SVC-5 | `IndiaDataService` has no lock at all, so the exclusion `data_service.py` was written to guarantee does not hold across the two services | RISK | VERIFIED | `backend/app/services/india_data_service.py:105` | `__init__` stores the session and nothing else; 23 unguarded `db.execute`/`commit`/`rollback` sites, sharing the session with `DataService` at three construction sites. | [SVC-5](detail/services.md#svc-5--indiadataservice-has-no-lock-at-all-so-the-exclusion-data_servicepy-was-written-to-guarantee-does-not-hold-across-the-two-services) |
| OE-11 | WebSocket `background_updates()` cannot exit while a send cycle raises | RISK | VERIFIED | `backend/app/api/websocket.py:270` | The liveness `break` sits inside the `try` after three awaits and a 30s sleep, so a persistently failing send retries every 5 seconds forever on an idle backend. | [OE-11](detail/prior-art.md#oe-11--websocket-background_updates-cannot-exit-while-a-send-cycle-raises) |
| API-5 | `/analytics/liquidity-limits` fetches one position at a time while its sibling on the same dashboard fans out 5-wide | RISK | VERIFIED | `backend/app/api/analytics.py:12241` | The `await` sits in a plain `for`; the sibling at `:7475` gathers the identical work under `Semaphore(5)`. Contrast is inside one file, so this is shape, not policy. | [API-5](detail/api.md#api-5--analyticsliquidity-limits-fetches-one-position-at-a-time-while-its-sibling-on-the-same-dashboard-fans-out-5-wide) |
| API-4 | No endpoint paginates; the response bodies are materialised row by row up to ~125,000 objects | RISK | VERIFIED | `backend/app/api/data.py:44` | The request is capped at 50 tickers and 3650 days; nothing caps the response, and `df.iterrows()` builds one Pydantic model per row before serialisation. | [API-4](detail/api.md#api-4--no-endpoint-paginates-the-response-bodies-are-materialised-row-by-row-up-to-125000-objects) |
| FE-10 | Three components subscribe to an entire Zustand store rather than a slice | RISK | VERIFIED | `frontend/src/components/layout/Header.tsx:74` | A `(state) => state` selector yields a fresh reference on every write and fails `Object.is`, so the header and the socket-owning hook re-render on every `lastUpdated` tick. | [FE-10](detail/frontend.md#fe-10--three-components-subscribe-to-an-entire-zustand-store-rather-than-a-slice) |
| FE-9 | ~500 lines of unreachable code, including the app's only HTTP interval and its only `/health` request | RISK | VERIFIED | `frontend/src/hooks/useRealTime.ts:11` | `useAutoRefresh` and `healthApi.check` have zero callers; two of the dead `NotificationSystem` exports open their own `WebSocketClient`, so re-mounting either doubles the socket count. | [FE-9](detail/frontend.md#fe-9--500-lines-of-unreachable-code-including-the-apps-only-http-interval-and-its-only-health-request) |
| INF-11 | `conftest.py`'s module-level `pytestmark` is inert; `cleanup_test_data` cleans nothing | RISK | VERIFIED | `backend/tests/conftest.py:420` | pytest reads `pytestmark` only from objects it collects and registers a conftest as a plugin, so 2254 tests run believing each is marked `unit` and cleaned, when neither holds. | [INF-11](detail/infra-tests.md#inf-11--conftestpys-module-level-pytestmark-is-inert-cleanup_test_data-cleans-nothing) |
| INF-12 | `create_test_price_data` seeds from `hash(ticker)`, which is randomised per process | RISK | VERIFIED | `backend/tests/conftest.py:448` | `str.__hash__` is salted by `PYTHONHASHSEED`, so every run produces a different series; the inline comment asserts the opposite of the behaviour. | [INF-12](detail/infra-tests.md#inf-12--create_test_price_data-seeds-from-hashticker-which-is-randomised-per-process) |
| INF-13 | 19 of 57 audit rules are never named in the gate; the file's own prose header miscounts its frozen set | RISK | VERIFIED | `backend/tests/test_audit_rule_coverage.py:115` | Real catch rate is 50 of 82 injected defects; the header sums its own frozen set to 25 against a counted 29, and the pass condition is per-section, not per-class. | [INF-13](detail/infra-tests.md#inf-13--19-of-57-audit-rules-are-never-named-in-the-gate-the-files-own-prose-header-miscounts-its-frozen-set) |
| INF-14 | The audit harness never runs against an export produced by the running application | RISK | VERIFIED | `backend/tests/test_audit_rule_coverage.py:1063` | `_fire` builds `ca.Export` from a frozen JSON file, so any divergence between the app's real export and `v27.json` is outside the gate by construction. | [INF-14](detail/infra-tests.md#inf-14--the-audit-harness-never-runs-against-an-export-produced-by-the-running-application) |
| INF-20 | `filterwarnings` ignores only `UserWarning`/`DeprecationWarning`, with no `error::` entry | RISK | VERIFIED | `backend/pyproject.toml:95` | `ComplexWarning` and `SAWarning` subclass `RuntimeWarning` and pass unelevated, so a numerically-invalid operation can leave a NaN in a payload with a green suite. | [INF-20](detail/infra-tests.md#inf-20--filterwarnings-ignores-only-userwarningdeprecationwarning-with-no-error-entry) |
| INF-7 | `restoreMocks`/`unstubGlobals` absent while `setup.ts` mutates globals at module scope | RISK | VERIFIED | `frontend/vitest.config.mts:8` | Process-wide `vi.fn()` replacements for fetch/WebSocket/localStorage/observers persist across cases in a file, so "not called" can read another test's consumption — or pass for the wrong reason. | [INF-7](detail/infra-tests.md#inf-7--restoremocksunstubglobals-absent-while-setupts-mutates-globals-at-module-scope) |
| INF-16 | `uv sync --frozen` cannot detect pyproject/lock drift | RISK | VERIFIED | `.github/workflows/ci-cd.yml:44` | `--frozen` installs the lock without asserting it matches the manifest; currently in sync, so the gate that would catch drift is disabled in the two places it matters. | [INF-16](detail/infra-tests.md#inf-16--uv-sync---frozen-cannot-detect-pyprojectlock-drift) |
| INF-15 | Deprecated and mutable GitHub Actions pinned in CI; the dependency cache guards the wrong directory | RISK | VERIFIED | `.github/workflows/ci-cd.yml:36` | `@master` resolves at run time, `upload-sarif@v2` is a retired major, and `path: ~/.cache/pip` is read by nothing because `uv sync` reads `~/.cache/uv`. | [INF-15](detail/infra-tests.md#inf-15--deprecated-and-mutable-github-actions-pinned-in-ci-the-dependency-cache-guards-the-wrong-directory) |
| INF-17 | Dev-only tooling shipped as runtime dependencies | RISK | VERIFIED | `frontend/package.json:16` | `vitest`, `@testing-library/*`, `@types/file-saver` sit inside `dependencies`; `ipython` has zero imports across `backend/**`; `pytest-xdist` is installed but `addopts` never passes `-n`. | [INF-17](detail/infra-tests.md#inf-17--dev-only-tooling-shipped-as-runtime-dependencies) |
| INF-22 | Two sources of truth for host policy; one is invisible in every config file | RISK | VERIFIED | `backend/main.py:102` | `CORSMiddleware` honours `ALLOWED_ORIGINS` but `TrustedHostMiddleware` compares `Host` against a hardcoded literal, so an operator following the documented interface gets an unexplained 403. | [INF-22](detail/infra-tests.md#inf-22--two-sources-of-truth-for-host-policy-one-is-invisible-in-every-config-file) |
| OE-06 | CI still authenticates to AWS with long-lived static keys | RISK | VERIFIED | `.github/workflows/ci-cd.yml:178` | QH-13 specified OIDC `role-to-assume` and was closed; zero matches for `oidc`/`role-to-assume` across `.github/**`. Credential hygiene, not an open exposure. | [OE-06](detail/prior-art.md#oe-06--ci-still-authenticates-to-aws-with-long-lived-static-keys) |
| OE-07 | Four NSE India tables have no producer, no fetcher and no caller | RISK | VERIFIED | `backend/app/services/india_data_service.py:149` | Zero production callers of either ingest function, no scheduler library installed, zero network-client hits in the file — yet `cache_service.py:502-505` registers the tables for stats. | [OE-07](detail/prior-art.md#oe-07--four-nse-india-tables-have-no-producer-no-fetcher-and-no-caller) |
| OE-08 | The `bfinance_synthetic_ohlc` provenance flag is never read — and is also set too often | RISK | VERIFIED | `backend/app/services/data_service.py:296` | The flag rides in `DataFrame.attrs` (dropped by concat/merge/groupby), is set unconditionally on every resampled frame, and `_source_of_df` is dead by construction because bfinance never sets `_source`. | [OE-08](detail/prior-art.md#oe-08--the-bfinance_synthetic_ohlc-provenance-flag-is-never-read--and-is-also-set-too-often) |
| API-8 | `holding_provenance`'s `frames` parameter has zero call sites, so all five callers re-fetch the window they already hold | RISK | DERIVED | `backend/app/api/analytics.py:2318` | Zero `frames=` call sites against six `holding_provenance(` hits; whether the fallback read is a cache hit or a live vendor round-trip needs a runtime trace, so the cost is DERIVED. | [API-8](detail/api.md#api-8--holding_provenances-frames-parameter-has-zero-call-sites-so-all-five-callers-re-fetch-the-window-they-already-hold) |
| INF-8 | `async_client` does not rebind the global engine; `websocket.py` binds `SessionLocal` at import | RISK | DERIVED | `backend/tests/conftest.py:223` | It overrides one DI dependency and rebinds neither `engine` nor `SessionLocal` nor the `ws_mod` alias; the sibling `client` fixture rebinds all three and documents this exact hazard. | [INF-8](detail/infra-tests.md#inf-8--async_client-does-not-rebind-the-global-engine-websocketpy-binds-sessionlocal-at-import) |
| FE-3 | `PortfolioStats` calls `.toFixed(1)` on an unguarded largest-position weight | RISK | DERIVED | `frontend/src/components/portfolio/PortfolioStats.tsx:83` | `Math.max` propagates one non-finite weight across every holding and `.toFixed(1)` renders `NaN%`. Firing it needs a payload that violates the declared contract in all three layers. | [FE-3](detail/frontend.md#fe-3--portfoliostats-calls-tofixed1-on-an-unguarded-largest-position-weight) |
| INF-19 | `scripts/deploy.sh` is never invoked, and its default `PUBLIC_BASE_URL` probes the wrong port | RISK | DERIVED | `scripts/deploy.sh:22` | The default is port 80 while prod compose publishes 3000, so the readiness probe burns its full 60s window on a dead address; `production-images` declares `environment: production` and a live URL for a job that pushes and stops. | [INF-19](detail/infra-tests.md#inf-19--scriptsdeploysh-is-never-invoked-and-its-default-public_base_url-probes-the-wrong-port) |
| INF-10 | `conftest.py::test_env_vars` cannot do what it claims | RISK | DERIVED | `backend/tests/conftest.py:364` | `from main import app` at `:21` constructs settings at import time; the fixture mutates `os.environ` after that, and its correct teardown is what makes it read as effective. | [INF-10](detail/infra-tests.md#inf-10--conftestpytest_env_vars-cannot-do-what-it-claims) |
| INF-18 | Root `.gitignore` omits `.ruff_cache/`; bare `*.db` protection lives one file deep | RISK | DERIVED | `.gitignore:76` | The root file carries only `*.db-wal`/`*.db-shm`; `Test-Path .ruff_cache` is True and `git check-ignore` returns nothing, so `git add -A` from the root stages it. | [INF-18](detail/infra-tests.md#inf-18--root-gitignore-omits-ruff_cache-bare-db-protection-lives-one-file-deep) |

## §4 NIT (cap 30) — 8 found, 8 shown, 0 deferred

| id | title | sev | conf | location | symptom | detail |
|---|---|---|---|---|---|---|
| SVC-11 | Dead `_l1_ttl` / `_L1_TTL_SECONDS` sit beside a comment asserting the live TTL as fact | NIT | VERIFIED | `backend/app/services/data_service.py:313` | The comment says "L1 keeps a 5-min TTL" but the enforced value is `_l1_ttl_seconds(config)`, which reads a runtime setting; the two constants have zero readers. | [SVC-11](detail/services.md#svc-11--dead-_l1_ttl--_l1_ttl_seconds-sit-beside-a-comment-asserting-the-live-ttl-as-fact) |
| OE-12 | The L1 in-memory DataFrame cache is a class attribute with no eviction | NIT | VERIFIED | `backend/app/services/data_service.py:298` | TTL is evaluated on read only, so expired entries are never deleted and `:555`/`:651` key the same instrument two ways; growth is bounded by the ticker universe, not by TTL. | [OE-12](detail/prior-art.md#oe-12--the-l1-in-memory-dataframe-cache-is-a-class-attribute-with-no-eviction) |
| OE-15 | Four quality-hardening tickets closed without their criterion being met | NIT | VERIFIED | `frontend/next.config.ts:5` | QH-04/08/09/13 status lines advanced on work done rather than criterion met; QH-10's wording is unsatisfiable because `scikit-learn` is genuinely imported. | [OE-15](detail/prior-art.md#oe-15--four-quality-hardening-tickets-closed-without-their-criterion-being-met) |
| API-6 | `analytics.py` is 13,422 lines and 651.6 KB with 143 top-level functions on one router | NIT | VERIFIED | `backend/app/api/analytics.py:9327` | 24 handlers share one namespace; `API-2` was missable precisely because a reader of endpoint #11 has no signal that #1-#10 used `_run_cpu`. | [API-6](detail/api.md#api-6--analyticspy-is-13422-lines-and-6516-kb-with-143-top-level-functions-on-one-router) |
| API-7 | Unreachable duplicate `except HTTPException: raise` in `/vol-cone` | NIT | VERIFIED | `backend/app/api/analytics.py:12347` | The first `except HTTPException` at `:12343` already matches that type, so the clause at `:12347` can never be selected. | [API-7](detail/api.md#api-7--unreachable-duplicate-except-httpexception-raise-in-vol-cone) |
| API-9 | `/tail-dependence` and `/tails` are stacked decorators on a single handler | NIT | VERIFIED | `backend/app/api/analytics.py:12496` | Two `router.get` decorators register one function under two paths; the shared 900s cache is genuinely correct — the finding is the decorator shape only. | [API-9](detail/api.md#api-9--tail-dependence-and-tails-are-stacked-decorators-on-a-single-handler) |
| INF-21 | No `concurrency` group; CI burns runners on superseded commits | NIT | VERIFIED | `.github/workflows/ci-cd.yml:1` | Zero `concurrency` matches in the only workflow file in the repository, so a superseding push starts a second full matrix including the 12-minute backend job. | [INF-21](detail/infra-tests.md#inf-21--no-concurrency-group-ci-burns-runners-on-superseded-commits) |
| FE-11 | Volatility-sizing rebuilds its table column model on every render, unlike its sibling page | NIT | DERIVED | `frontend/src/app/dashboard/volatility-sizing/page.tsx:883` | One of nine `DataTable` consumers memoises its columns; this page does not. The cost is a call-site count and a render-frequency argument, not a measurement. | [FE-11](detail/frontend.md#fe-11--volatility-sizing-rebuilds-its-table-column-model-on-every-render-unlike-its-sibling-page) |

---

## §5 Pointers

| file | what it is | when to open it |
|---|---|---|
| [`features.md`](features.md) | Non-defects: features, class items and deferred design decisions. **Excluded from every band total above.** Every row is labelled `non-defect`. | Someone asks "should we build this?" |
| [`rejected.md`](rejected.md) | The retirement deliverable: 22 prior findings proven closed in current code, 4 refuted claims, 11 stale entries, 21 directory verdicts, 10 coverage gaps. Unbounded and load-bearing. | Someone proposes re-reporting something an earlier audit already found. |
| [`unverified.md`](unverified.md) | **10 entries.** Claims that cannot be settled by reading, each with the exact command or observation that would settle it. | Before quoting any magnitude, frequency or runtime behaviour from this audit. |
| [`ORCHESTRATOR-CORRECTIONS.md`](ORCHESTRATOR-CORRECTIONS.md) | The authoritative override layer (COR-1..COR-8). Where it contradicts a detail file, it wins. COR-1 un-rejects `FE-2`; COR-3 created the `COR-3` row; COR-8 corrects `SVC-1`'s published score from 3.0 to 5.9. | Any time a detail row's verdict is questioned. |
| [`detail/api.md`](detail/api.md) · [`detail/services.md`](detail/services.md) · [`detail/frontend.md`](detail/frontend.md) · [`detail/infra-tests.md`](detail/infra-tests.md) · [`detail/prior-art.md`](detail/prior-art.md) | The five writers' full evidence, mechanism traces, fix shapes and their own "Rejected on re-verification" sections. | Before acting on a row. Every row above links its own section. |
| [`detail/research-doc-accuracy.md`](detail/research-doc-accuracy.md) | **Not ranked in this ledger.** A documentation-accuracy slice with no id namespace and no severity/confidence. Read it for six live defects that carry no row above (see §0, last bullet). | When deciding whether §1-§4 is a complete defect census. It is not. |
| [`../plans/2026-10-consolidated-audit.md`](../../plans/2026-10-consolidated-audit.md) | The governing plan: structure, caps, evidence floor, merge policy. | To check whether a row met the bar. |

---

## Mechanical checks run against this file

1. Row count == sum of per-band counts in §0 == length of open.json. **67 == 67 == 67.**
2. No two rows cite the same location: **67 distinct locations for 67 rows.**
3. Every `file:line` in this file resolves AND carries the cited construct: **67/67 primary locations opened mechanically (0 missing files, 0 out of range), and the cited line re-read at every one of them.** A further 61 secondary citations inherited from the writers were checked the same way, plus the `needs:` chain in `ci-cd.yml:143/165/224` and the `output`-absent proof in `next.config.ts` (0 matches, control `reactCompiler` 1 match).
4. `unverified.md` has exactly 10 entries, each with a settle-command.
5. Pre-cap counts appear in both §0 and `STATUS.md`; no band hit its cap.
6. `features.md` rows are all labelled `non-defect` and none appear here.

### Where two rows share an enclosing function (dedup disclosure)

One duplicate defect was merged (`OE-14` ≡ `FE-5`). Four pairs of rows sit in the *same enclosing
function* without being duplicates — distinct lines, distinct mechanisms, distinct symptoms, distinct
fixes. They are listed rather than hidden, because "no two rows share a function" would be false and a
false check result is worse than a disclosed exception:

| rows | shared unit | why they are not duplicates |
|---|---|---|
| `SVC-1` (`:3945`) + `OE-03` (`:3947`) | `analytics_engine.py::AnalyticsEngine.liquidity_analysis` | `SVC-1` is the **missing NaN guard** on absent data; `OE-03` is the **wrong estimator** on good data. Fixing one does not fix the other; the fixtures differ (a finiteness test vs a changed formula). |
| `SVC-6` (`:65`) + `SVC-7` (`:185`) | `backtest_service.py::run_walk_forward_backtest` | Coupling, not identity: one silently shortens the window and mislabels the disclosure, the other annualises without the gate. The writer states they must be fixed together — that is a shared remediation, not one defect. |
| `FE-1` (`:786`) + `OE-02` (`:799`) | `manage/page.tsx::PortfolioManagePage` | `FE-1` is an unreachable finiteness guard producing `+0.00%`; `OE-02` is a 100x unit error plus constant "Low" badge. Adjacent lines, unrelated mechanisms. |
| `FE-8` (`:96`) + `FE-10` (`:74`) | `Header.tsx::Header` | `FE-8` fabricates an export total; `FE-10` is a whole-store subscription causing excess re-render. Unrelated. |

Additionally `FE-11` and `OE-01` both sit in `volatility-sizing/page.tsx::VolatilitySizingPage`
(`:883` and `:814`): one is an unmemoised column model, the other a scale-sniffing formatter. `SVC-11`
and `OE-12` both sit in the `DataService` class body (`:313` and `:298`): dead TTL constants with a
wrong comment, versus an unbounded class-level cache. All distinct lines, distinct mechanisms.

`FE-7` (`:171`, in `fetchPortfolio`) and `COR-3` (`:206`, in `setPortfolioSnapshot`) are in **different**
named functions, but note that FE-7's *second* site is `:204` — inside `setPortfolioSnapshot`, three
lines above `COR-3`. Same function, different lines, and different mechanisms by COR-3's own words:
FE-7 launders the absence into `0`, `COR-3` throws on it.
