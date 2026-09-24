# Backend remediation fix index

**Audit date:** 2026-09-24  
**Scope:** verified cash-equity/portfolio-analytics findings in the deep backend audit; backend/deployment/test/audit-fix paths only.  
**Safety:** no frontend edits, dependency/lockfile edits, commits, resets, checkouts, cleans, stashes, history rewrites, live-provider verification, or intentional access to `backend/data/daisy.db`.

## Executive result

The selected A-01..A-13, B-01..B-15, C-01..C-14, and D-01..D-13 remediation matrix is implemented and hermetically verified through the coordinator gates. The fresh independent residual review initially found three issues (production health ASGI exemption, quote-cache startup fencing, and ambiguous risk-exclusion disclosure); all three were fixed, regression-tested, and the final read-only rerun returned **PASS — 8/8**. The coordinator also closed cross-owner seams: API active-return construction and coverage accounting, explicit coint lookback identity and late-write fencing, confidence-neutral tail schema, returned-window source provenance, typed provider status mapping, atomic source-switch cache invalidation, mixed-currency analytics/performance/WebSocket units, unavailable WebSocket metrics, truthful single-holding correlation, and bounded WebSocket sends.

The implementation is **not** a claim that the product has no remaining backlog items. Docker image build/runtime, live vendor behavior, public ingress, and several explicitly out-of-scope product/research gaps remain unresolved and are listed below.

## Status matrix

| Workstream | IDs | Result | Severity movement | Primary proof |
|---|---|---|---|---|
| A — quant | A-01..A-13 | **Implemented; independent verifier PASS** | P1 horizon/return/drawdown/MC/backtest defects closed; inverse-vol zero-variance and short-history edges closed; indicator time-axis gaps preserved; late coint writes fenced; residual EWMA/MFI edges covered | `agent-a-quant.md`; 166-test gate; 21-test A audit file |
| B — data/cache/provider | B-01..B-15 | **Implemented; independent verifier PASS** | P1 cache/coverage/date/identity/outage/ingestion/liquidity/FX defects closed; P2 provenance/schema/precedence defects closed; historical/direct timeseries and quote memo generation fences covered | `agent-b-data.md`; 137-test broad B gate / 24-test B audit file |
| C — API/portfolio | C-01..C-14 | **Implemented; independent verifier PASS** | P1 currency/weight/uniqueness/WebSocket/tail/event-loop/input defects closed; mixed-FX 503, base/value currency labels, active coverage, null correlation, rebalance/sizing valuation, and model-scoped risk disclosure covered | `agent-c-api.md`; 39-test C gate; 78-test API/C gate; 115-test C/API/WebSocket/portfolio gate |
| D — foundation/deployment | D-01..D-13 | **Implemented with runtime limitation; independent verifier PASS** | P1 deployment/data-loss/migration defects closed statically and in isolated SQLite; backup-permission and production health ASGI edges covered; image execution unverified because Docker is absent | `agent-d-foundation.md`; 19-test D contract gate; 16/16 preflight |

## Before → after evidence

| Finding family | Before evidence | After evidence |
|---|---|---|
| A-01 GARCH/EGARCH horizon | h=5 GARCH VaR `-0.0492743493` vs reference `-0.0220341981`; EGARCH h=5 unavailable | GARCH/EGARCH h=1/5/21 match independent per-period `arch` variance-sum references; finite seeded EGARCH simulation paths |
| A-02 active returns | staggered-listing annual return/volatility materially differed because pre-listing values were filled | service/API active-mask oracles retain measured observations; API fixture returns `[0.10, 0.09090909, 0.05416667]`; interior forecast/risk-contribution gaps are not imputed |
| A-03 drawdown | first `-10%` loss reported `0` drawdown | initial wealth baseline reports `-0.10` in analytics/backtest |
| A-04 EVT | clipped shape `-0.5` was presented as fit | raw `-2.01301978`, constrained estimate and validity/reason fields are distinct |
| A-05 MFI/indicator gaps | `0.5246785287` on a documented 0–100 contract; an interior missing close could be dropped and compress the time axis; invalid-price MFI could remain numeric | `52.4678528716`; missing/non-positive/non-finite required-price rows remain present with null indicators and no synthetic price |
| A-06 costs | negative/non-finite costs could increase wealth | invalid inputs raise before simulation |
| A-07 backtest | fixed weights between rebalances | self-financing drift; boundary turnover `0.0073`, total `0.31` in fixture |
| A-08 Monte Carlo | 40-year request estimated `249,984,000` live elements | bounded chunks/checkpoints; `4,989,600` estimated retained live elements |
| A-09 coint cache | lookback/coverage omitted from identity | distinct keys for lookback `60` vs `2520`; API threads `60` explicitly |
| A-10 benchmark | historical end `2020-02-01` fetched through 2026 | exact `('^NSEI','2020-01-01','2020-02-01')` fetch call |
| A-11 tail names | confidence `0.95` appeared under `*_99` | neutral fields primary; `*_99` aliases only at actual `0.99` |
| A-12 EWMA | one return `[0.05]` produced a fabricated portfolio-volatility estimate | portfolio EWMA sizing now returns an explicit insufficient-data result; the separate scalar helper retains its documented zero-variance compatibility contract |
| A-13 invariants | HHI/N_eff/single-holding/inverse-vol/geometric checks were vulnerable to route drift; zero-variance excluded legs poisoned sizing and short model history fabricated 20%; underdetermined covariance legs could receive zero risk contribution | active HHI/N_eff and geometric checks pass; raw low-vol inverse-vol sizing has no 5% floor, zero-variance legs are excluded safely, insufficient history is explicit, and underdetermined risk legs are disclosed |
| B cache/provider | persisted controls/purge/source/coverage/date/provenance/typed errors had silent or false-success paths; a late coint or timeseries write could repopulate a purged cache; fallback FX was not strict at API seams | focused B regressions, pre-await/direct-helper generation fences, strict live-FX provenance, provider compatibility suite, and coordinator oracle pass |
| C API/portfolio | mixed currencies summed before conversion, rebalance and volatility sizing used native totals/target quantities, WebSocket value units conflicted with native currency, FX outage returned 500, first weight could remain `0.2`, tail cache omitted weights, heavy work blocked loop, unsafe errors/CSV | exact INR/USD totals/provenance, converted live-price target quantities, explicit `value_currency`/`native_currency`, FX outage 503 across concentration/portfolio/sizing/history, first weight `1.0`, active coverage, null single-holding correlation, weight-aware memo, offload, safe statuses/CSV, bounded requests |
| D foundation/deployment | sync URL/path, destructive prune, unsafe late backup permissions, production health redirecting an HTTP container probe, non-converging migrations, no readiness | async mounted path, atomic private backup creation, health-path HTTP exemption with normal-route HTTPS redirects, safe restore, image identity rollback, versioned constraints, static health/CI contracts |

All numeric before values above are retained from the original audit/agent evidence; all after values are regenerated by the named hermetic fixtures. No live database or provider was used to produce them.

## Cross-owner integration changes

- `backend/app/services/analytics_engine.py:29-60` exposes the shared active positive-weight return aggregator; `:645-828` rejects one-return EWMA sizing, uses raw inverse-volatility inputs, and handles safe covariance scaling; `:1115-1301` implements cumulative h=1/5/21 GARCH/EGARCH semantics.
- `backend/app/services/currency_service.py:76-124` provides the strict live-FX provenance validator; portfolio/analytics/WebSocket adapters use it before monetary aggregation, and `backend/app/api/portfolio.py:1148-1333` uses one converted INR price basis for rebalance valuation and target quantities.
- `backend/app/services/data_service.py:543-687,812-967,1526-1618` captures the cache generation before historical/quote startup and persistence awaits, passes it through every provider write, and rejects stale direct-helper upserts.
- `backend/app/services/indicators_service.py:134-176` masks invalid required-price MFI rows; `backend/app/api/analytics.py:2092-2207` provides model-scoped underdetermined covariance/tail exclusions.
- `backend/main.py:30-42,99-106` exempts only health probes from the production HTTPS redirect; `scripts/deploy.sh:10-12,72-118` secures container and host backup artifacts before content writes.
- `backend/app/api/analytics.py:169-181,386-473,739-847,1356-1657,1665-1701,1920-2008,2023-2090,2306-2335` preserves active masks, counts active coverage, maps provider failures to 503, handles mixed FX, nulls undefined correlation, and avoids single-holding fills.
- `backend/app/api/data.py:92-163,356-465,477-564` maps safe provider statuses, scopes source lookup to returned dates, canonicalizes response identity, and fences source switches in the settings transaction.
- `backend/app/api/websocket.py:34-85,180-218,271-407` bounds sends, labels base/value/native currencies, publishes unavailable analytics as null, and uses active weights.
- `backend/app/models/schemas.py:139-160,335-349,416-451` retains quote provenance, truthful null correlation, and confidence-neutral EVT fields while preserving optional legacy aliases.
- `backend/app/services/india_data_service.py:297-318` returns the latest stored trading sessions for flow lookback.
- `backend/app/services/cointegration_service.py:368-428,475-529` fences late coint cache writes with the current purge generation.
- `backend/app/services/volatility_service.py:51-63,236-249` preserves the original return index for rolling realized-volatility windows.

## Verification commands and numeric results

All Python gates used `PYTHONDONTWRITEBYTECODE=1`, `uv run --frozen`, `pytest -p no:cacheprovider --no-cov`, and isolated in-memory/temp SQLite.

```text
A focused quant gate
  166 passed, 12 existing statsmodels warnings

B audit regression file
  24 passed

C focused contract gate
  39 passed

D migration/deployment contract gate
  19 passed

A+B+C+D combined regression files
  103 passed

API endpoints + C contracts
  78 passed

Coordinator integrated regression set (A/B/C/D contracts + API, WebSocket,
portfolio, data/cache compatibility)
  224 passed, 2 existing SQLAlchemy cleanup warnings, 44.26s
  Evidence: `evidence/final-integrated-gates.txt`

A/B/C/D Ruff gate (app + focused tests)
  All checks passed!

Provider/data/cache compatibility gate
  115 passed (prior hermetic compatibility run; current integrated set is green)

Hermetic coordinator evidence oracle
  10 passed, 0 failed
```

Additional adjacent gates recorded by the agents:

- Foundation/migration/deployment/cache: **39 passed** in the final hermetic foundation gate; current D contract subset is **19 passed**.
- C portfolio integration: **19 passed** in the prior focused run; current C audit is **39 passed**.
- A/B/C/D focused evidence scripts: all A after artifacts `PASS`; B/C hermetic fixtures pass.
- D static foundation preflight: **16 passed, 0 failed**; deploy dry-run `PASS`; shell syntax and YAML checks pass.
- Independent residual verifier: **PASS — 8/8** on the final integrated tree; the earlier FAIL capture remains historical evidence.

The coordinator oracle and its exact output are:
`.scratch/backend-deep-audit/fixes/evidence/agent-coordinator-integration.py` and
`final-coordinator-oracle.txt`. The latest integrated pytest capture is
`evidence/final-integrated-gates.txt`; the final independent residual verdict
is **PASS — 8/8** and is recorded in `evidence/independent-residual-review-pass.md`.

## Residual reviewer closure (2026-09-24)

| Residual finding | Current implementation/proof | Status |
|---|---|---|
| Production health probe | `backend/main.py` exempts exact health paths at the ASGI `__call__` boundary; actual production probe returns 200/200 and ordinary routes return 307. | **PASS — independently verified** |
| Mixed-currency rebalance/sizing | Portfolio rebalance values and target quantities use quantity × live price converted to INR; volatility sizing converts holdings before valuation; stale `market_value` is ignored. | **PASS — independently verified** |
| Timeseries generation fence | Historical and quote startup/direct-upsert fences pass; stale quote publication leaves `_quote_memo` empty. | **PASS — independently verified** |
| FX fallback/status policy | `coerce_live_fx_rate` rejects fallback/unlabelled/non-finite rates; portfolio, rebalance, concentration, performance history, and sizing map failures to HTTP 503. | **PASS — independently verified** |
| One-return EWMA | Portfolio sizing returns the explicit insufficient-data result; scalar helper compatibility remains separately tested. | **PASS — independently verified** |
| Indicator/risk missingness | Invalid-price MFI rows become null; risk exclusions are model-scoped under `excluded_assets.volatility` and `excluded_assets.cvar_tail`. | **PASS — independently verified** |
| Backup permissions | Container process uses `umask 077`; host artifact is atomically reserved `0600` before `compose cp`; shell regression passes. | **PASS — independently verified** |
| Finite request money | Create and update quantity/buy-price schemas reject positive infinity; regression tests pass. | **PASS — independently verified** |

The integrated evidence is **224 passed** with two existing SQLAlchemy cleanup
warnings, the A broad gate is **166 passed**, the A/B audit files are **45
passed**, the C audit file is **39 passed**, and the D contract file is **19
passed**. The final independent residual verdict is **PASS — 8/8**.

## Independent residual review history and closure (2026-09-24)

The first read-only verifier run returned **FAIL** and is preserved in
`evidence/independent-residual-review-fail.md`. It found the Starlette ASGI
health bypass, quote-memo startup race, and ambiguous global risk exclusions.

The follow-up fixes were independently re-verified after integration. The
final read-only rerun returned **PASS — 8/8**:

- Production health: `/health=200`, `/api/v1/health=200`, ordinary routes `307`.
- Mixed-currency rebalance/sizing: `8080 INR`, native target quantities, live FX.
- Historical and quote generation fences: stale writes rejected; `_quote_memo` remains empty.
- Fallback/unlabelled FX: rejected; affected APIs return `503`.
- One-return EWMA: explicit insufficient-data output.
- Invalid MFI/model-scoped risk disclosure: null/model-specific exclusions.
- Backup permissions and shell syntax: private/hermetic proof.
- Create/update finite money: `+inf` rejected.

Final gate results: focused residual files **103 passed**, integrated set
**224 passed**, A **166**, B **137**, C **39**, D **19**, API+C **78**,
C/API/WebSocket/portfolio **115**, foundation gate **39**, coordinator oracle
**10/10**, backup-specific test **1**, and `bash -n scripts/deploy.sh` **PASS**.
Docker/container runtime remains intentionally unverified.

## Current documentation basis

The final implementation was checked against current Context7 documentation for FastAPI/Starlette middleware (including the ASGI `__call__` path), Pydantic v2 finite-number validation, Docker Compose healthcheck semantics, and SQLAlchemy AsyncSession commit/rollback behavior. No dependency or lockfile changes were made.

## Latest `/v1/models` follow-up

The reported `GET /v1/models 404` was traced to no in-repo caller, no configured
LLM provider, and no model-serving route. Current OpenAI API documentation
defines model discovery as a list response. FinEngine now exposes an honest
compatibility response at `/v1/models`:

```json
{"object": "list", "data": []}
```

This prevents generic discovery probes from receiving a misleading 404 while
making no claim that FinEngine hosts chat models. The endpoint regression is in
`backend/tests/test_api_endpoints.py`; the isolated ASGI probe and focused API
suite are recorded in `evidence/models-endpoint.txt`; the independent endpoint
verifier returned **PASS**. The refreshed integrated capture is **224 passed**.

## Unresolved and intentionally unverified

1. `docker`, `docker compose`, and `docker-compose` are not installed. Image build, container startup, healthcheck execution, named-volume persistence, and Compose integration were not run. D's static contracts are not a substitute for runtime proof.
2. `.dockerignore`, public ingress/TLS, and a tracked rollout target remain outside the allowed write scope. Production Compose is intentionally loopback-only until those are supplied.
3. No live yfinance/bfinance/Alpha/NSE verification was performed. Alpha Indian exchange fallback remains unavailable without an operator-verified `AV_SYMBOL_MAP`; no blind `.BSE` substitution is restored.
4. `run_in_executor` vendor work cannot be forcibly cancelled after timeout; the service no longer reports that work as a successful durable fetch, but the platform-level worker lifetime limitation remains.
5. Position currency is still inferred from quote metadata/exchange convention because a persisted currency column was not added; portfolio responses expose `position_currencies`, and WebSocket position values now explicitly expose `currency`/`value_currency` plus `native_currency` and FX provenance.
6. `CONTEXT.md:267` still contains the pre-remediation `.ffill().bfill().fillna(0.0)` prescription. It was not edited because the allowed write scope excludes that file; executable code and tests use the active-mask contract.
7. Scalar EWMA/GARCH fitting in `volatility_service.py` still has its documented scalar compatibility behavior; portfolio `AnalyticsEngine.volatility_sizing` now rejects one-return EWMA input, and rolling volatility, active returns, forecasts, and indicator time-axis paths preserve gaps. A broader model-specific gap policy remains a follow-up.
8. Product/research gaps outside the selected audit matrix (point-in-time transaction ledger, full add-ticker impact workflow, field-level freshness UI, research-provider expansion, and public deployment rollout) remain backlog.
9. The C agent's recorded pre-coordination full-suite run was `492 passed, 18 failed, 87 skipped, 204 warnings`; those historical failures were triaged. The final index relies on the current focused/integration gates above rather than claiming an unverified all-suite green result.

## Changed-file inventory

### Task-touched backend/runtime files

`backend/Dockerfile`; `backend/app/api/analytics.py`; `backend/app/api/data.py`; `backend/app/api/equity_research.py`; `backend/app/api/portfolio.py`; `backend/app/api/websocket.py`; `backend/app/config.py`; `backend/app/db/database.py`; `backend/app/models/database.py`; `backend/app/models/schemas.py`; `backend/app/services/alpha_vantage_service.py`; `backend/app/services/analytics_engine.py`; `backend/app/services/backtest_service.py`; `backend/app/services/benchmark_service.py`; `backend/app/services/cache_service.py`; `backend/app/services/cointegration_service.py`; `backend/app/services/company_data_service.py`; `backend/app/services/currency_service.py`; `backend/app/services/data_service.py`; `backend/app/services/equity_research_service.py`; `backend/app/services/india_data_service.py`; `backend/app/services/indicators_service.py`; `backend/app/services/monte_carlo_service.py`; `backend/app/services/screener_service.py`; `backend/app/services/source_preference_service.py`; `backend/app/services/tail_risk_service.py`; `backend/app/services/volatility_service.py`; `backend/main.py`; `backend/migrations/__init__.py`; `backend/migrations/add_portfolio_columns.py`; `backend/migrations/cleanup_duplicates_and_add_constraints.py`; `backend/migrations/schema_version.py`; `backend/migrations/sqlite_backup.py`.

### Task-touched deployment/CI files

`.github/workflows/ci-cd.yml`; `docker-compose.yml`; `docker-compose.prod.yml`; `scripts/deploy.sh`.

### Task-touched tests

`backend/tests/test_agent_a_quant_fixes.py`; `backend/tests/test_agent_b_data_audit.py`; `backend/tests/test_agent_c_api_contracts.py`; `backend/tests/test_agent_d_deployment_contract.py`; `backend/tests/test_agent_d_migrations.py`; `backend/tests/test_api_endpoints.py`; `backend/tests/test_bug_sweep_2026_09.py`; `backend/tests/test_bugfix_cache_index_selfheal.py`; `backend/tests/test_bugfix_quant_services.py`; `backend/tests/test_coverage_quant_services.py`; `backend/tests/test_quant_math_p1_batch.py`; `backend/tests/integration/test_compose_services.py`; plus provider/India/contract compatibility tests listed in `agent-b-data.md`.

### Audit-fix artifacts

`.scratch/backend-deep-audit/fixes/00-ISSUE-MATRIX.md`; `agent-a-quant.md`; `agent-b-data.md`; `agent-c-api.md`; `agent-d-foundation.md`; `00-FIX-INDEX.md`; `todo.md`; all `agent_*` evidence scripts/results under `fixes/evidence/`; current integrated capture `evidence/final-integrated-gates.txt`; failed independent residual capture `evidence/independent-residual-review-fail.md`; final PASS capture `evidence/independent-residual-review-pass.md`; endpoint follow-up `evidence/models-endpoint.txt`.

## Pre-existing dirty-tree and generated-file statement

The baseline was already extensively dirty before remediation, including `.agents/`, `.scratch/`, `AGENTS.md`, CI/Compose/deploy files, and unrelated documentation. Those paths were not reverted wholesale. The untracked `backend/data/daisy.db-shm` and `backend/data/daisy.db-wal` files were left untouched; no database file was intentionally opened or mutated.

Generated artifacts from this remediation are limited to the new/updated regression tests, hermetic evidence scripts and their `.txt`/`.md` results under `.scratch/backend-deep-audit/fixes/`, and the task-touched source/deployment files listed above. No frontend, lockfile, external documentation, or Git history file was generated or edited.

## Git and runtime safety

No commit, reset, checkout, clean, stash, or history rewrite was performed. All changes remain uncommitted for coordinator/user review.
