# Backend foundation deep audit — code (`05-foundation`)

**Audit date:** 2026-09-24  
**Context:** personal, single-user localhost cash-equity and portfolio-analytics application  
**Scope:** backend models, settings, database/session layer, schemas, utilities/logging, migrations, operational scripts/configuration, Docker/CI, dependency metadata, and tests only for coverage gaps. Frontend, `.venv`, out-of-scope recommendations, and application/config mutation are excluded.

## 1. Scope, method, and actual file inventory

### 1.1 Method

- Read each in-scope source/operations file line-by-line. Large service/API files were read in full when they own a persistence flow; `analytics.py`, `regime_service.py`, and `uv.lock` were read only in the exact query/dependency ranges needed to establish schema, async, and version evidence.
- Traced every model reference and every `select`/upsert/delete/commit/rollback path in `backend/app/` to its caller before assigning a finding.
- Queried `backend/data/daisy.db` through SQLite `mode=ro`: schema, indexes, duplicate counts, invalid-data counts, query plans, `quick_check`, and `foreign_key_check`. No row values were printed.
- Ran controlled environment probes for `CORS_ORIGINS`, the async SQLAlchemy driver, and redaction of a fake API key. The local `backend/.env` was **not opened**.
- Ran `bash -n` for both shell scripts, `ruff check --no-cache main.py app migrations`, and 59 focused tests with bytecode, pytest cache, and coverage disabled. All 59 tests passed.
- Docker is not installed on this host, so no image build or Compose render was possible. Docker findings are grounded in path resolution, official Python 3.12 slim/Debian package metadata, and current file references.
- No prior-audit content is used as evidence. Every finding below was independently re-read from current source or read-only runtime state.

### 1.2 Actual file inventory

Per-file “findings” is the number of **unique global IDs touching that file**. A cross-file finding therefore appears in several rows but is counted once in the global totals. “Clean” means no issue in the inspected foundation/trace scope, not a claim that the whole application is correct.

#### Core backend and operational source

| # | File | Lines inspected | Findings | IDs | Clean? |
|---:|---|---:|---:|---|---|
| 1 | `.gitignore` | 1-67 | 1 | FOUND-007 | No |
| 2 | `.githooks/pre-commit` | 1-19 | 0 | — | Yes |
| 3 | `.github/workflows/ci-cd.yml` | 1-272 | 2 | FOUND-001, FOUND-016 | No |
| 4 | `README.md` | 1-90 | 1 | FOUND-023 | No |
| 5 | `TEST_INFRA.md` | 1-40 | 0 | — | Yes |
| 6 | `backend/.gitignore` | 1-15 | 1 | FOUND-007 | No |
| 7 | `backend/.python-version` | 1 | 0 | — | Yes |
| 8 | `backend/Dockerfile` | 1-71 | 4 | FOUND-001, FOUND-007, FOUND-015, FOUND-020 | No |
| 9 | `backend/README.md` | 0 | 1 | FOUND-023 | No |
| 10 | `backend/pyproject.toml` | 1-120 | 2 | FOUND-009, FOUND-020 | No |
| 11 | `backend/uv.lock` | 1-346 plus direct dependency/package records through 4169 | 1 | FOUND-020 | No |
| 12 | `backend/main.py` | 1-181 | 4 | FOUND-001, FOUND-002, FOUND-015, FOUND-022 | No |
| 13 | `backend/app/__init__.py` | 1-3 | 0 | — | Yes |
| 14 | `backend/app/api/__init__.py` | 1-3 | 0 | — | Yes |
| 15 | `backend/app/api/analytics.py` | 170-209, 1335-1379, 2080-2129 | 0 | — | Yes |
| 16 | `backend/app/api/data.py` | 1-506 | 1 | FOUND-019 | No |
| 17 | `backend/app/api/portfolio.py` | 1-1118 | 3 | FOUND-006, FOUND-010, FOUND-018 | No |
| 18 | `backend/app/api/websocket.py` | 1-358 | 0 | — | Yes |
| 19 | `backend/app/config.py` | 1-79 | 2 | FOUND-013, FOUND-023 | No |
| 20 | `backend/app/db/database.py` | 1-130 | 4 | FOUND-001, FOUND-002, FOUND-009, FOUND-021 | No |
| 21 | `backend/app/models/__init__.py` | 1-3 | 0 | — | Yes |
| 22 | `backend/app/models/database.py` | 1-227 | 4 | FOUND-009, FOUND-010, FOUND-011, FOUND-021 | No |
| 23 | `backend/app/models/schemas.py` | 1-581 | 0 | — | Yes |
| 24 | `backend/app/services/alpha_vantage_service.py` | 1-358 | 2 | FOUND-008, FOUND-012 | No |
| 25 | `backend/app/services/cache_service.py` | 1-287 | 1 | FOUND-009 | No |
| 26 | `backend/app/services/cointegration_service.py` | 1-467 | 0 | — | Yes |
| 27 | `backend/app/services/data_service.py` | 1-1293 | 1 | FOUND-011 | No |
| 28 | `backend/app/services/india_data_service.py` | 1-335 | 1 | FOUND-009 | No |
| 29 | `backend/app/services/indicators_service.py` | 1-242 | 0 | — | Yes |
| 30 | `backend/app/services/regime_service.py` | 100-353 | 0 | — | Yes |
| 31 | `backend/app/services/screener_service.py` | 1-364 | 0 | — | Yes |
| 32 | `backend/app/services/source_preference_service.py` | 1-85 | 1 | FOUND-019 | No |
| 33 | `backend/app/utils/holdings.py` | 1-260 | 0 | — | Yes |
| 34 | `backend/app/utils/logger.py` | 1-55 | 1 | FOUND-018 | No |
| 35 | `backend/migrations/add_portfolio_columns.py` | 1-104 | 1 | FOUND-009 | No |
| 36 | `backend/migrations/cleanup_duplicates_and_add_constraints.py` | 1-292 | 3 | FOUND-009, FOUND-014, FOUND-021 | No |
| 37 | `docker-compose.yml` | 1-100 | 7 | FOUND-001, FOUND-002, FOUND-007, FOUND-015, FOUND-017, FOUND-020, FOUND-023 | No |
| 38 | `docker-compose.prod.yml` | 1-246 | 9 | FOUND-001, FOUND-002, FOUND-005, FOUND-007, FOUND-015, FOUND-017, FOUND-018, FOUND-020, FOUND-023 | No |
| 39 | `scripts/deploy.sh` | 1-273 | 4 | FOUND-003, FOUND-004, FOUND-005, FOUND-023 | No |
| 40 | `backend/test_integrity_api.sh` | 1-200 | 1 | FOUND-006 | No |

#### Test files inspected for coverage only

| # | File | Lines inspected / execution | Findings | IDs | Clean? |
|---:|---|---:|---:|---|---|
| 41 | `backend/tests/conftest.py` | 1-497 | 1 | FOUND-009 | No |
| 42 | `backend/tests/test_bugfix_foundation.py` | 1-306 | 2 | FOUND-009, FOUND-013 | No |
| 43 | `backend/tests/test_bugfix_cache_index_selfheal.py` | 1-150 | 1 | FOUND-009 | No |
| 44 | `backend/tests/test_bugfix_providers_05.py` | 300-356 | 1 | FOUND-009 | No |
| 45 | `backend/tests/test_alpha_vantage.py` | 1-130 | 2 | FOUND-008, FOUND-012 | No |
| 46 | `backend/tests/test_coverage_alpha_vantage.py` | 1-317 | 2 | FOUND-008, FOUND-012 | No |
| 47 | `backend/tests/test_api_endpoints.py` | 140-464 | 2 | FOUND-006, FOUND-010 | No |
| 48 | `backend/tests/test_contract_p1_batch.py` | 150-320 | 1 | FOUND-009 | No |
| 49 | `backend/tests/test_coverage_data_service.py` | 370-469 | 1 | FOUND-011 | No |
| 50 | `backend/tests/test_db_gate_concurrency.py` | 1-198; 3 tests executed | 1 | FOUND-009 | No |

**Actual inspection total:** 50 files (40 source/operations/documentation files and 10 test files), plus one SQLite database inspected read-only. The local `backend/.env` was intentionally not opened. No frontend or `.venv` source file was inspected.

## 2. Finding count reconciliation

### Severity

| Severity | Count |
|---|---:|
| P0 | 0 |
| P1 | 8 |
| P2 | 9 |
| P3 | 6 |
| **Total** | **23** |

### Primary category

| Category | IDs | Count |
|---|---|---:|
| Docker / CI / deployment | FOUND-001, FOUND-003, FOUND-004, FOUND-005, FOUND-015, FOUND-016, FOUND-017 | 7 |
| Database / configuration / startup | FOUND-002, FOUND-009, FOUND-013, FOUND-019, FOUND-023 | 5 |
| Secrets / logging / observability | FOUND-007, FOUND-008, FOUND-018 | 3 |
| Data integrity / transactions / script safety | FOUND-006, FOUND-010, FOUND-011, FOUND-014 | 4 |
| Async correctness | FOUND-012 | 1 |
| Dependency / build reproducibility | FOUND-020 | 1 |
| Schema / dead-code hygiene | FOUND-021 | 1 |
| Lifecycle / shutdown | FOUND-022 | 1 |
| **Total** |  | **23** |

## 3. Deduplicated findings

### FOUND-001 — P1 — Docker/CI build and runtime layout are nonfunctional

- **Exact evidence:** Compose supplies repository-root context at `docker-compose.yml:6-8` and `docker-compose.prod.yml:6-9`, but the first dependency copy expects root `pyproject.toml`/`uv.lock` at `backend/Dockerfile:24`; neither root file exists. CI instead supplies `backend/` as context at `.github/workflows/ci-cd.yml:58` and `.github/workflows/ci-cd.yml:209`, where `backend/Dockerfile:25` expects a nonexistent nested `backend/backend/`. The production stage also requests Debian Bookworm-incompatible `libssl1.1` at `backend/Dockerfile:38-41`; the current `python:3.12-slim` lineage is Bookworm/OpenSSL 3. Finally, the image uses `/app` as CWD at `backend/Dockerfile:47`, copies code to `/app/backend` at `backend/Dockerfile:57`, but starts `backend.main:app` at `backend/Dockerfile:71`; `backend.main` imports top-level `app.*` at `backend/main.py:19-22`, while the image does not create `/app/app` or set `WORKDIR`/`PYTHONPATH` to `/app/backend`.
- **Affected flow:** local Compose build, CI backend build, ECR build, and container startup.
- **Grounded impact:** every configured build context fails a `COPY`; after correcting context, the production `apt-get` step fails; after correcting that, the stated runtime import layout is inconsistent. No backend container can be built and started by the checked-in configuration.
- **Minimum recommendation:** standardize on `context: ./backend`, use `COPY pyproject.toml uv.lock ./` plus `COPY . .`, install only the locked runtime dependencies, use a Bookworm-compatible base without `libssl1.1`, and run from `/app/backend` with `main:app`. Add one image smoke command that imports the app and calls `/health`.
- **Test gap:** CI builds at `.github/workflows/ci-cd.yml:56-58` but never runs the image; Docker was unavailable for a local build. There is no import/entrypoint smoke test.

### FOUND-002 — P1 — Compose overrides the async engine with an invalid sync URL and points outside the mounted data volume

- **Exact evidence:** both Compose files set `DATABASE_URL=sqlite:///./data/daisy.db` at `docker-compose.yml:13` and `docker-compose.prod.yml:13`. `backend/app/db/database.py:20-24` passes that value to `create_async_engine`; a read-only probe produced `InvalidRequestError: The asyncio extension requires an async driver ... loaded 'pysqlite' is not async`. The configured default is correctly async at `backend/app/config.py:21`. Separately, container CWD is `/app` at `backend/Dockerfile:47`, so `./data/daisy.db` resolves to `/app/data/daisy.db`, while both files mount persistence at `/app/backend/data` (`docker-compose.yml:17-19`, `docker-compose.prod.yml:22-24`). `ensure_sqlite_dir` intentionally follows the relative URL at `backend/app/db/database.py:41-47`.
- **Affected flow:** importing `app.db.database`, FastAPI lifespan startup, and every database-backed portfolio/analytics route.
- **Grounded impact:** the backend fails before startup. If only the driver is corrected, portfolio data is written to an unpersisted container path while the declared volume remains empty.
- **Minimum recommendation:** set both Compose files to `sqlite+aiosqlite:///./backend/data/daisy.db`, or set CWD to `/app/backend` and mount `/app/backend/data` consistently. Reject non-async database URLs during settings validation/startup.
- **Test gap:** `backend/tests/test_bugfix_foundation.py:170-175` tests a correct async environment value, but no test renders Compose and imports the application with its environment.

### FOUND-003 — P1 — Deployment EXIT trap can delete the portfolio volume

- **Exact evidence:** `scripts/deploy.sh:242-243` installs `cleanup` as an unconditional EXIT trap. That function globally runs `docker volume prune -f` at `scripts/deploy.sh:173-185`. Production stores the portfolio database in the named `app_data` volume declared at `docker-compose.prod.yml:22-24` and `docker-compose.prod.yml:234-238`.
- **Affected flow:** any deployment-script exit, including dependency/environment/preflight failure before the backend attaches the volume.
- **Grounded impact:** an unused `app_data` volume is eligible for global volume pruning, deleting the local portfolio database. The trap runs on success and failure; it is not limited to this Compose project.
- **Minimum recommendation:** remove `docker volume prune` from this script. If cleanup is needed, prune only known stopped containers/images belonging to this project; never prune data volumes.
- **Test gap:** no shell test creates a sentinel volume, fails before startup, and asserts it remains.

### FOUND-004 — P1 — Deployment “backup” writes to an unshared path and can target the wrong database

- **Exact evidence:** the host creates `backups/<timestamp>` at `scripts/deploy.sh:74-79`, but the Python process runs **inside** the container and opens that same relative path at `scripts/deploy.sh:81-90`; production mounts only `app_data` and `app_logs` at `docker-compose.prod.yml:22-24`, not `/app/backups`. The script later opens `/app/backend/data/daisy.db` at `scripts/deploy.sh:84` and `scripts/deploy.sh:153-159`, while FOUND-002 shows the application resolves its configured DB under `/app/data`. The raw `database.sql` directory is never removed; retention deletes only tar files at `scripts/deploy.sh:97-103`.
- **Affected flow:** pre-deployment backup and database connectivity checks.
- **Grounded impact:** backup normally fails because the host-created directory is not visible in the container. If the directory happens to exist, `sqlite3.connect` can create an empty DB and dump no portfolio rows while the command reports success. A corrected path would still leave raw SQL dumps indefinitely.
- **Minimum recommendation:** use SQLite's backup API from the actual application DB and stream/copy the resulting file to the host backup directory; run `PRAGMA quick_check` and compare row counts before proceeding; delete the raw SQL after verified compression.
- **Test gap:** no test executes backup against a sentinel DB and restores it into a fresh SQLite database.

### FOUND-005 — P1 — Deployment health, artifact selection, and rollback do not form a valid flow

- **Exact evidence:** the script checks host URLs `localhost:8000` and `localhost:3000` at `scripts/deploy.sh:133-150`, but production publishes only Nginx ports 80/443 at `docker-compose.prod.yml:83-94`; backend and frontend have no host port mappings at `docker-compose.prod.yml:5-46` and `docker-compose.prod.yml:47-81`. The script pulls images at `scripts/deploy.sh:108-113`, but backend/frontend define `build` without an `image` at `docker-compose.prod.yml:5-9` and `docker-compose.prod.yml:47-52`, so the pushed artifact is not selected by Compose. Rollback runs the same `down` then `up` with the same compose file at `scripts/deploy.sh:188-198`; no previous image ID/tag is captured or used.
- **Affected flow:** production deploy, health gate, and failure recovery.
- **Grounded impact:** health checks target unpublished ports and fail the deployment. Rollback recreates the same configuration/current build rather than a known-good image, so it is not a rollback.
- **Minimum recommendation:** health-check the published Nginx URL, deploy immutable image tags/digests, record the current image digest before replacement, and roll back by explicitly setting that prior digest.
- **Test gap:** no dry-run test verifies published URLs, selected image digests, or rollback identity.

### FOUND-006 — P1 — Integrity shell script writes test holdings into the live portfolio and exits green

- **Exact evidence:** the script POSTs synthetic MSFT/GOOGL positions at `backend/test_integrity_api.sh:13-39`, another request at `backend/test_integrity_api.sh:60-78`, a zero-quantity request at `backend/test_integrity_api.sh:96-114`, and NVDA at `backend/test_integrity_api.sh:146-159`. It has no `set -e`; failed cases only print messages at `backend/test_integrity_api.sh:47-54` and `backend/test_integrity_api.sh:167-171`. Cleanup is explicitly left manual at `backend/test_integrity_api.sh:173-179`, followed by unconditional success claims at `backend/test_integrity_api.sh:180-200`.
- **Affected flow:** manual execution against the documented localhost API.
- **Grounded impact:** test rows become indistinguishable from user holdings, successful holdings are never removed, and the shell's final status does not prove any assertion passed.
- **Minimum recommendation:** delete this script and keep the hermetic pytest coverage, or require an explicit test database URL, a cleanup trap, unique sentinels, and a nonzero exit on any failed assertion.
- **Test gap:** existing API tests use an isolated in-memory DB at `backend/tests/conftest.py:145-167` and `backend/tests/conftest.py:223-230`; no gate prevents or validates this live script.

### FOUND-007 — P1 — Docker's broad copy can bake ignored secrets, portfolio data, and logs into images

- **Exact evidence:** `backend/Dockerfile:32` and `backend/Dockerfile:57` copy the entire `backend/` tree. No `.dockerignore` exists at either supported context root. Git ignores env files at `.gitignore:46-48`, local databases at `backend/.gitignore:12-14`, and logs/coverage at `.gitignore:56-59`; Docker build context rules do not use `.gitignore`. The local inventory contains `backend/.env`, `backend/data/daisy.db`, and backend logs, but their contents were not opened.
- **Affected flow:** any successful local backend image build after FOUND-001 is fixed.
- **Grounded impact:** API keys, the local portfolio database, logs, test DBs, and coverage artifacts can become image layers and remain available in the image even if later deleted.
- **Minimum recommendation:** add `.dockerignore` entries for `.env*`, `data/`, `backups/`, `*.db`, `*.log`, `.coverage`, `htmlcov/`, caches, and tests before fixing the build context. Keep an allowlist of runtime source files.
- **Test gap:** no image-content/secret scan exists; the current Docker build fails before reaching the broad copy (FOUND-001).

### FOUND-008 — P1 — Alpha Vantage key is logged in full on HTTP errors

- **Exact evidence:** the API key is inserted into the request query at `backend/app/services/alpha_vantage_service.py:227-230`. `raise_for_status()` creates an exception containing the request URL at `backend/app/services/alpha_vantage_service.py:232-235`, and that exception is logged directly at `backend/app/services/alpha_vantage_service.py:240`. A fake-key probe produced a message containing `?apikey=FAKE_KEY_1234`.
- **Affected flow:** any Alpha Vantage non-2xx response.
- **Grounded impact:** the complete API key enters stdout and any Docker/log aggregation sink.
- **Minimum recommendation:** log only function name, status code, and a sanitized URL without query parameters; never log the `HTTPError` object from a request carrying `apikey`.
- **Test gap:** `backend/tests/test_alpha_vantage.py:31-39` and `backend/tests/test_coverage_alpha_vantage.py:105-152` mock successful/status-notice responses, not an HTTP error with a query-bearing URL.

### FOUND-009 — P2 — Schema evolution is not versioned or applied to existing databases

- **Exact evidence:** startup calls only `Base.metadata.create_all` at `backend/app/db/database.py:50-71`; SQLAlchemy `create_all` does not add missing columns/constraints to existing tables. The only startup repair is a hard-coded analytics-cache dedupe/index at `backend/app/db/database.py:63-71`. Alembic is installed at `backend/pyproject.toml:25` but no Alembic environment/config is present. The portfolio migration adds nullable SQLite columns at `backend/migrations/add_portfolio_columns.py:58-70`, while the ORM declares them non-null at `backend/app/models/database.py:18-19`. The ORM declares NSE bhavcopy uniqueness at `backend/app/models/database.py:136-142`, and concurrency handling relies on it at `backend/app/services/india_data_service.py:101-112`; read-only `PRAGMA` on the current DB found `quantity`/`buy_price` nullable and only a non-unique `ix_bhav_symbol_date` index. The deploy flow never invokes either migration at `scripts/deploy.sh:245-251`.
- **Affected flow:** upgrades of an existing local DB, fresh-vs-existing schema parity, and NSE natural-key race handling.
- **Grounded impact:** fresh test DBs and existing DBs have different constraints; declared uniqueness is not guaranteed on the existing database; future model changes can leave production routes querying missing columns.
- **Minimum recommendation:** use the already-installed Alembic as the single schema owner, create one baseline migration that reconciles the current DB, record a schema version, and run `upgrade head` before application startup/deploy. Do not add more ad hoc startup DDL.
- **Test gap:** `backend/tests/conftest.py:145-167` creates each test DB from current metadata, while `backend/tests/test_bugfix_foundation.py:191-224` tests only fresh metadata constraints; there is no old-schema-to-current parity test. `backend/tests/test_bugfix_cache_index_selfheal.py:55-149` covers only the analytics special case.

### FOUND-010 — P2 — Portfolio ticker uniqueness is a race-prone application precheck

- **Exact evidence:** `PortfolioPosition.ticker` is merely indexed at `backend/app/models/database.py:15-17`; there is no unique constraint. Single add selects all tickers and compares canonical forms before insert at `backend/app/api/portfolio.py:198-239`. Bulk add repeats the precheck at `backend/app/api/portfolio.py:332-350` before inserting at `backend/app/api/portfolio.py:450-459`.
- **Affected flow:** concurrent single/bulk position additions from multiple tabs or requests.
- **Grounded impact:** two requests can both observe no ticker and then insert duplicate canonical holdings. Later `.first()` reads at `backend/app/api/portfolio.py:561-566`, `backend/app/api/portfolio.py:628-633`, and `backend/app/api/portfolio.py:704-709` make behavior dependent on insertion order.
- **Minimum recommendation:** add a unique index on stored canonical `ticker` after reconciling existing duplicates, and translate `IntegrityError` to HTTP 409.
- **Test gap:** duplicate tests are sequential (`backend/tests/test_api_endpoints.py:239-245`); there is no two-session concurrent add test. Read-only current DB counts show zero duplicate tickers, so this is preventive rather than current corruption.

### FOUND-011 — P2 — Structurally invalid OHLCV rows are warned about but still persisted

- **Exact evidence:** `_store_timeseries_data` computes validation errors and only logs warnings at `backend/app/services/data_service.py:1060-1069`; it then builds and upserts every supplied record at `backend/app/services/data_service.py:1071-1110`. The validator itself detects negative values and invalid OHLC relationships at `backend/app/services/data_service.py:1131-1149`, but has no rejection path.
- **Affected flow:** upstream frames containing negative prices, `high < low`, or prices outside the OHLC envelope.
- **Grounded impact:** structurally invalid vendor rows enter the canonical SQLite cache and can propagate into returns, volatility, and portfolio analytics. The write-side model has no checks at `backend/app/models/database.py:43-54`.
- **Minimum recommendation:** reject structural errors (negative/non-finite values and invalid OHLC ordering) before constructing the upsert; keep “large daily move” as a warning because splits/listing gaps can be legitimate.
- **Test gap:** `backend/tests/test_coverage_data_service.py:424-448` verifies warning strings only; it never asserts that an invalid frame is not stored.

### FOUND-012 — P2 — Alpha Vantage rate-limit budget is consumed after an await, allowing concurrent overrun

- **Exact evidence:** `_make_request` acquires a key at `backend/app/services/alpha_vantage_service.py:222-225`, then awaits the threaded HTTP request at `backend/app/services/alpha_vantage_service.py:229-232`, and only calls `budget.spend()` after a successful response at `backend/app/services/alpha_vantage_service.py:243-251`. The key pool is process-wide at `backend/app/services/alpha_vantage_service.py:350-358`, while batch fetching permits five concurrent ticker tasks at `backend/app/services/data_service.py:645-660`.
- **Affected flow:** concurrent Alpha Vantage fallback requests.
- **Grounded impact:** multiple tasks can pass `available()` against the same unreported minute/day budget and all contact the vendor, exceeding configured 5/minute or 25/day limits and causing avoidable 429/rate-limit failures.
- **Minimum recommendation:** reserve quota synchronously before the first `await`; release the reservation only for a request that demonstrably did not consume vendor quota.
- **Test gap:** Alpha tests are sequential (`backend/tests/test_alpha_vantage.py:67-125`); there is no concurrent acquire-before-spend test.

### FOUND-013 — P2 — Compose uses the wrong CORS environment variable

- **Exact evidence:** the settings field is `allowed_origins` at `backend/app/config.py:49-58`, so pydantic-settings reads `ALLOWED_ORIGINS`, as tested at `backend/tests/test_bugfix_foundation.py:156-167`. Both Compose files instead inject `CORS_ORIGINS` at `docker-compose.yml:16` and `docker-compose.prod.yml:16`. A controlled probe with `CORS_ORIGINS=https://custom.invalid` left the four localhost defaults unchanged.
- **Affected flow:** browser CORS configuration for any non-default frontend origin.
- **Grounded impact:** operator changes are silently ignored; a non-localhost frontend is denied while configuration appears applied.
- **Minimum recommendation:** rename the Compose variable to `ALLOWED_ORIGINS` (or add an explicit Pydantic validation alias) and render-test the resulting middleware origins.
- **Test gap:** tests validate `ALLOWED_ORIGINS` but never validate the deployed Compose variable name.

### FOUND-014 — P2 — Cleanup migration can report failure while returning shell success

- **Exact evidence:** `main()` prints failure but returns a result dictionary at `backend/migrations/cleanup_duplicates_and_add_constraints.py:272-288`; the `__main__` block discards that return without `sys.exit` at `backend/migrations/cleanup_duplicates_and_add_constraints.py:291-292`.
- **Affected flow:** manual or automated invocation of the cleanup migration.
- **Grounded impact:** a failed cleanup/validation can leave process exit status 0, allowing a deployment job to continue as if schema repair succeeded.
- **Minimum recommendation:** raise/SystemExit nonzero when `result["success"]` is false; add a one-line `raise SystemExit(0 if result["success"] else 1)` at the entry point.
- **Test gap:** foundation tests cover missing-path behavior at `backend/tests/test_bugfix_foundation.py:97-116` but not a failed full-cleanup exit status.

### FOUND-015 — P2 — Container health checks use a binary absent from the runtime image and test only static liveness

- **Exact evidence:** the production stage installs only `libssl1.1` at `backend/Dockerfile:37-41`, but Dockerfile and Compose health checks invoke `curl` at `backend/Dockerfile:63-65`, `docker-compose.yml:22-27`, and `docker-compose.prod.yml:40-45`. The endpoint itself returns a constant response without querying the DB at `backend/main.py:150-160`.
- **Affected flow:** container health state and dependent-service readiness.
- **Grounded impact:** even after the build blockers are fixed, health checks fail because `curl` is not installed. Conversely, when run, the endpoint cannot detect a post-start DB failure.
- **Minimum recommendation:** use Python's stdlib for the image health probe or explicitly install the probe binary; keep `/health` as liveness and add a small readiness endpoint executing `SELECT 1` if Compose should gate traffic on DB availability.
- **Test gap:** `backend/tests/test_api_endpoints.py:444-460` asserts only that health returns 200; no container probe or DB-failure readiness test exists.

### FOUND-016 — P2 — CI integration and deployment jobs do not exercise a real integration/deploy flow

- **Exact evidence:** the required integration job runs `pytest tests/integration/` at `.github/workflows/ci-cd.yml:162-169`, but no `backend/tests/integration/` directory exists; backend pytest is configured to discover `tests` at `backend/pyproject.toml:82-85`. Deployment is gated on that job at `.github/workflows/ci-cd.yml:176-180`, but the EKS rollout is commented out at `.github/workflows/ci-cd.yml:223-228`; the job then curls fixed external URLs at `.github/workflows/ci-cd.yml:230-244` without applying the newly built image.
- **Affected flow:** CI merge gate and production deployment signal.
- **Grounded impact:** the integration job cannot run its stated test target, and even a green deploy job can test an old externally hosted version because no rollout occurred.
- **Minimum recommendation:** point integration at real tests or remove the job, set explicit job outputs from image builds, and make deployment conditional on a successful rollout of those exact digests.
- **Test gap:** no meta-test asserts that CI-referenced test directories, compose files, and deployment commands exist.

### FOUND-017 — P2 — Production Compose depends on absent bind-mounted configuration trees

- **Exact evidence:** development mounts `./nginx/...` and `./ssl` at `docker-compose.yml:77-87`. Production mounts `./nginx/prod`, `./ssl`, Prometheus configuration, Grafana provisioning/dashboards, and Logstash pipeline files at `docker-compose.prod.yml:91-95`, `docker-compose.prod.yml:128-130`, `docker-compose.prod.yml:161-165`, and `docker-compose.prod.yml:200-206`. None of `nginx/`, `monitoring/`, or `ssl/` exists in the actual repository-root inventory.
- **Affected flow:** `docker compose up`, integration CI, Nginx startup, and monitoring ingestion.
- **Grounded impact:** Compose can create empty host paths or start services with unusable configuration, making the stack fail or silently disable expected proxy/monitoring behavior.
- **Minimum recommendation:** for this personal app, delete unused monitoring services and mount only an existing minimal Nginx config; add a tracked config directory before retaining any bind mount.
- **Test gap:** no Compose render/start test; Docker is unavailable on the audit host.

### FOUND-018 — P3 — Raw portfolio payloads are logged while configured file-log volumes stay empty

- **Exact evidence:** every position add logs the full Pydantic request, including ticker, quantity, cost basis, region, and custom name, at `backend/app/api/portfolio.py:169-174`. The logger writes to stdout at `backend/app/utils/logger.py:42-53`. Production mounts an `app_logs` volume at `docker-compose.prod.yml:22-24` and Logstash reads it at `docker-compose.prod.yml:200-207`, but no foundation logger writes files there.
- **Affected flow:** development request logs and production log aggregation.
- **Grounded impact:** holdings/cost-basis data is duplicated into logs at INFO, while the declared persistent log volume receives no application log files.
- **Minimum recommendation:** remove the raw payload log or reduce it to non-sensitive request metadata; use Docker stdout collection instead of a fake file-log volume, or add an explicit rotating file handler if file persistence is truly required.
- **Test gap:** logger tests cover level fallback at `backend/tests/test_bugfix_foundation.py:284-296`, not sensitive-field redaction or log routing.

### FOUND-019 — P3 — Combined configuration updates are not atomic

- **Exact evidence:** `PUT /config` calls `set_primary_source` first at `backend/app/api/data.py:214-219`; that helper commits immediately at `backend/app/services/source_preference_service.py:64-77`. Remaining cache settings are written and committed later at `backend/app/api/data.py:221-240`.
- **Affected flow:** a request updating primary source plus TTL/enabled-cache values.
- **Grounded impact:** if a later cache-setting write fails, the primary source remains changed even though the overall request fails.
- **Minimum recommendation:** keep all AppSetting upserts in the endpoint/session and issue one commit/rollback boundary.
- **Test gap:** configuration tests verify persistence for individual settings (`backend/tests/test_contract_p1_batch.py:297-308`), not failure atomicity across multiple settings.

### FOUND-020 — P3 — Build inputs and runtime dependencies are not reproducible; several direct runtime packages are unused

- **Exact evidence:** mutable base tags are used at `backend/Dockerfile:2` and `backend/Dockerfile:35`, and unpinned `pip install uv` at `backend/Dockerfile:28` and `backend/Dockerfile:50`. Prometheus/Grafana use `latest` at `docker-compose.prod.yml:121-124` and `docker-compose.prod.yml:149-152`. Direct runtime dependencies include `aiohttp`, IPython, and QuantLib at `backend/pyproject.toml:31-38`, but no first-party import exists under `backend/app`, `backend/main.py`, or `backend/migrations`; the lock records them as production dependencies at `backend/uv.lock:253-283`.
- **Affected flow:** image rebuilds, dependency resolution, image size, and vulnerability surface.
- **Grounded impact:** equivalent source revisions can produce different images; unused packages enlarge install/build time and attack surface.
- **Minimum recommendation:** pin the Python base by digest and a tested UV version; pin monitoring images by digest/tag. Remove unused direct runtime packages after confirming they are not transitive requirements, and keep the existing `uv.lock` hashes for what remains.
- **Test gap:** CI has a dependency review at `.github/workflows/ci-cd.yml:127-128`, but no unused-direct-dependency or image reproducibility check.

### FOUND-021 — P3 — Dead schema surfaces and redundant indexes remain in the persistence model

- **Exact evidence:** `StockTimeseries.position_id`/relationship are declared at `backend/app/models/database.py:56-58` and `backend/app/models/database.py:33`, but no first-party writer sets `position_id`. `NSEBulkBlockDeal` and `NSEShareholdingPattern` are declared at `backend/app/models/database.py:170-215`; outside the model, they are referenced only by cache purge imports/table mapping at `backend/app/services/cache_service.py:221-247`, with no production query or ingest caller. Several tables declare an index on integer primary key and also single/composite indexes covering the same leading columns, e.g. `backend/app/models/database.py:43-64` and `backend/app/models/database.py:74-87`; read-only current-DB inspection shows three analytics indexes over `(ticker, metric_name)` variants.
- **Affected flow:** schema creation, cache purges, and every write to affected tables.
- **Grounded impact:** unused FK/tables expand maintenance and migration scope; duplicate indexes add write/storage overhead without improving observed query plans.
- **Minimum recommendation:** delete unused models/FK/relationship if not planned, or add the missing persistence flow; consolidate indexes after comparing ORM, migration, and query plans.
- **Test gap:** tests assert some model metadata at `backend/tests/test_contract_p1_batch.py:250-256`, but no fresh-vs-migrated index-set parity test exists.

### FOUND-022 — P3 — Shutdown cancels the background task without awaiting it

- **Exact evidence:** lifespan calls `websocket.update_task.cancel()` and then immediately disposes DB connections at `backend/main.py:63-67`; it never awaits the cancelled task or suppresses `CancelledError`.
- **Affected flow:** FastAPI/Uvicorn shutdown while the WebSocket updater is in a DB operation.
- **Grounded impact:** cancellation is only requested; DB disposal can race the task's final cleanup/error path.
- **Minimum recommendation:** after `cancel()`, `await` the task with `contextlib.suppress(asyncio.CancelledError)`, then dispose the engine.
- **Test gap:** no lifespan test starts the updater, cancels it, and asserts clean completion before engine disposal.

### FOUND-023 — P3 — Operational configuration/documentation is internally inconsistent

- **Exact evidence:** the deploy script requires `.env.example` at `scripts/deploy.sh:55-61`, but no root/backend example file exists; the only local configuration snippet is documentation at `README.md:41-50`. The script rejects only `your-secret-key-here-change-in-production` at `scripts/deploy.sh:63-69`, while production defaults to a different placeholder at `docker-compose.prod.yml:16-20`; `Settings` has no `secret_key` field (`backend/app/config.py:17-76`). The script accepts `staging` at `scripts/deploy.sh:214-227` but always fixes `COMPOSE_FILE` to production at `scripts/deploy.sh:14-19`. Production also injects `DATABASE_POOL_SIZE`, `MAX_OVERFLOW`, `POOL_TIMEOUT`, and `DATABASE_ECHO` at `docker-compose.prod.yml:18-21`, none of which exists in `Settings`.
- **Affected flow:** operator setup, staging selection, and production environment expectations.
- **Grounded impact:** setup instructions cannot be followed literally, placeholder validation is bypassable, staging is mislabeled, and operators can believe unsupported variables are active.
- **Minimum recommendation:** ship a secret-free `.env.example`; remove unused variables/secret checks; either support staging with a distinct compose file or reject that argument.
- **Test gap:** tests instantiate `Settings` directly but do not lint Compose/script environment keys against the settings model.

## 4. DB schema, indexes, query patterns, and migration table

The “current DB” column comes from read-only SQLite PRAGMAs and `EXPLAIN QUERY PLAN`; it is runtime evidence, not a source-line claim. Source anchors are shown for every declared/query behavior.

| Table | Declared schema/indexes | Actual query patterns | Current DB / query-plan result | Assessment |
|---|---|---|---|---|
| `portfolio_positions` | Ticker index; all business columns nullable only at DB level for several fields; no unique/check constraints (`backend/app/models/database.py:11-33`) | Ticker equality/in list (`backend/app/api/portfolio.py:561-566`, `backend/app/api/portfolio.py:628-633`, `backend/app/api/portfolio.py:704-709`); full portfolio scans (`backend/app/api/portfolio.py:58-72`); region/sector filters (`backend/app/api/portfolio.py:61-65`) | Ticker lookup uses `ix_portfolio_positions_ticker`; zero duplicate tickers and zero non-positive quantity/buy-price rows. `quantity` and `buy_price` are nullable in the current DB, despite `backend/app/models/database.py:18-19`. | Lookup index is adequate for personal holdings. FOUND-009 and FOUND-010 apply. Unindexed region/sector filters are acceptable at this scale. |
| `stock_timeseries` | Unique `(ticker,date)` plus non-unique `(ticker,date)` and single-column indexes (`backend/app/models/database.py:39-64`) | Ticker/date windows (`backend/app/services/data_service.py:972-987`), ticker min/max/count (`backend/app/services/data_service.py:218-231`), source lookup ordered by date (`backend/app/api/data.py:313-323`), multi-ticker windows (`backend/app/api/websocket.py:170-178`) | Window uses `idx_stock_timeseries_unique_ticker_date`; zero duplicate keys and zero structurally invalid OHLC rows. | Query coverage is good. FOUND-011 permits invalid writes; FOUND-021 notes redundant index metadata. |
| `analytics_cache` | Unique `(ticker,metric_name)` plus non-unique same-column index (`backend/app/models/database.py:70-87`) | Point lookup with expiry (`backend/app/services/cache_service.py:23-37`), upsert on ticker+metric (`backend/app/services/cache_service.py:72-89`), expiry/range counts (`backend/app/services/cache_service.py:124-191`) | Lookup uses `uq_analytics_cache_ticker_metric`; zero duplicate logical keys. Three overlapping same-key indexes exist in the current DB. Startup self-heal is atomic in `engine.begin()` at `backend/app/db/database.py:60-71`. | Correctness is good; index set is redundant (FOUND-021). The ad hoc self-heal illustrates but does not solve FOUND-009. |
| `fetch_logs` | Ticker, `(ticker,timestamp)`, `(status,timestamp)` indexes (`backend/app/models/database.py:93-110`) | Timestamp count and timestamp+status count (`backend/app/services/cache_service.py:166-181`) | Uses covering `ix_status_timestamp`; current DB passes integrity checks. | Adequate for a personal app; no retention finding added. |
| `nse_bhavcopy` | Unique `(symbol,date)` (`backend/app/models/database.py:116-145`) | Date existence select (`backend/app/services/india_data_service.py:69-79`) and symbol/date history (`backend/app/services/india_data_service.py:210-217`) | Current composite index is **non-unique**, contradicting `backend/app/models/database.py:140-142`; table currently has zero rows. Symbol/date query uses the index. | FOUND-009 directly applies. The `func.date(...)` existence predicate at `backend/app/services/india_data_service.py:70-72` cannot use a normal date index efficiently; low priority while this ingest path has no production caller. |
| `nse_institutional_flows` | Unique `(date,category)` and date index (`backend/app/models/database.py:148-167`) | Date/category point read and date-window ordering (`backend/app/services/india_data_service.py:123-181`) | Date-window query uses the date index; current DB has the unique index and zero rows. | Schema/query match is clean. The service has no first-party production caller. |
| `nse_bulk_block_deals` | Non-unique `(symbol,date)` (`backend/app/models/database.py:170-192`) | No production query; only cache purge at `backend/app/services/cache_service.py:221-247` | Table has zero rows. | Dead persistence surface; FOUND-021. |
| `nse_shareholding_patterns` | Unique `(symbol,period_ended)` (`backend/app/models/database.py:195-215`) | No production query; only cache purge at `backend/app/services/cache_service.py:221-247` | Table has zero rows. | Dead persistence surface; FOUND-021. |
| `app_settings` | String primary key (`backend/app/models/database.py:218-227`) | Key point reads/upserts (`backend/app/services/source_preference_service.py:51-73`, `backend/app/api/data.py:221-236`, `backend/app/services/data_service.py:1007-1012`) | Primary key serves all key lookups. | Indexing is correct. Transaction atomicity is FOUND-019. |
| Foreign key | Nullable `stock_timeseries.position_id -> portfolio_positions.id` (`backend/app/models/database.py:56-58`) | No production writer sets it | PRAGMA enforcement is enabled at `backend/app/db/database.py:88-111`; current `foreign_key_check` returns zero violations. | Enforcement is clean, but the relationship is dead (FOUND-021). |

### Runtime integrity snapshot

- `PRAGMA quick_check`: `ok`.
- `PRAGMA user_version`: `0`, reinforcing FOUND-009.
- Foreign-key violations: `0`.
- Duplicate logical keys: `0` for portfolio ticker, stock ticker/date, analytics ticker/metric, and populated NSE natural-key groups.
- Structurally invalid OHLC rows: `0`.
- Non-positive portfolio quantity/buy-price rows: `0`.
- The database contains real local rows, so findings are based on schema/query metadata and aggregate counts only.

## 5. Config, secrets, Docker, CI, and root-script hygiene

| Area | Evidence | Status / linked finding |
|---|---|---|
| Settings env binding | Field-name binding documented and tested at `backend/app/config.py:4-8`, `backend/app/config.py:17-76`, `backend/tests/test_bugfix_foundation.py:148-175` | Correct for `DATABASE_URL`, `ALLOWED_ORIGINS`, `DEBUG`, and `LOG_LEVEL`; Compose breaks async DB/CORS (FOUND-002, FOUND-013). |
| Local `.env` secrecy | Env files are Git-ignored at `.gitignore:46-48`; `git ls-files` confirmed `backend/.env` is untracked | Git hygiene is clean. Docker context hygiene is not (FOUND-007). Contents were not inspected. |
| Env example | Script demands `.env.example` at `scripts/deploy.sh:55-61`; only README prose exists at `README.md:41-50` | Missing operator template (FOUND-023). |
| Alpha Vantage secrets | Key enters URL at `backend/app/services/alpha_vantage_service.py:227-230`; full HTTP error logged at `backend/app/services/alpha_vantage_service.py:232-240` | Redaction failure (FOUND-008). Last-four logging at `backend/app/services/alpha_vantage_service.py:158-169` is not the primary issue. |
| Logger behavior | Stdout handler and level validation at `backend/app/utils/logger.py:12-55`; level tests at `backend/tests/test_bugfix_foundation.py:284-296` | Level fallback/handler duplication guard are clean. Caller privacy/routing is FOUND-018. |
| Docker security | Runtime intends non-root user at `backend/Dockerfile:43-61` | Good intent, but image is nonfunctional and may embed secrets/data (FOUND-001, FOUND-007). |
| Docker health | Probe definitions at `backend/Dockerfile:63-65`, `docker-compose.yml:22-27`, `docker-compose.prod.yml:40-45`; endpoint at `backend/main.py:150-160` | Missing probe binary and shallow health contract (FOUND-015). |
| Docker DB persistence | URLs at `docker-compose.yml:13`, `docker-compose.prod.yml:13`; mounts at `docker-compose.yml:17-19`, `docker-compose.prod.yml:22-24` | Invalid async URL and wrong path (FOUND-002). |
| Production deployment | Compose definition at `docker-compose.prod.yml:1-246`; script flow at `scripts/deploy.sh:206-273` | Broken health/artifact/rollback path (FOUND-005), destructive trap (FOUND-003), invalid backup (FOUND-004). |
| Shell syntax | `bash -n` passed for `scripts/deploy.sh:1-273` and `backend/test_integrity_api.sh:1-200` | Syntax is valid; semantics/data safety are not (FOUND-003, FOUND-004, FOUND-006). |
| CI backend checks | Install/lint/test/build at `.github/workflows/ci-cd.yml:41-64` | Lint/test commands are explicit; Docker build context is wrong and no image run occurs (FOUND-001). |
| CI integration/deploy | Required job and post-build checks at `.github/workflows/ci-cd.yml:145-174`, `.github/workflows/ci-cd.yml:176-244` | Nonexistent test target and no rollout (FOUND-016). |
| Dependency lock | Project metadata at `backend/uv.lock:253-346`; package records include versions and hashes, e.g. SQLAlchemy at `backend/uv.lock:3506-3513` and Uvicorn at `backend/uv.lock:3726-3735` | Lock reproducibility is good. Docker installer/base and direct dependency hygiene are not (FOUND-020). |
| Pre-commit | Staged backend-only Ruff gate at `.githooks/pre-commit:7-19`; Ruff command executed successfully with `--no-cache` | Clean and intentionally narrow per `backend/pyproject.toml:70-77`. |

## 6. Test gaps, explicit clean areas, and limitations

### Consolidated test gaps

1. No successful image build, image import, entrypoint, or container health test (FOUND-001, FOUND-015).
2. No Compose-rendered environment test for async DB URL, CORS, volume target, or key parity (FOUND-002, FOUND-007, FOUND-013, FOUND-023).
3. No deploy-script sentinel-volume, backup/restore, published-port, immutable-image, or rollback test (FOUND-003, FOUND-004, FOUND-005).
4. No old-schema-to-current migration parity test beyond the analytics special case (FOUND-009).
5. No concurrent two-session portfolio add test (FOUND-010).
6. Invalid OHLC tests assert warnings rather than write rejection (FOUND-011).
7. No Alpha Vantage HTTP-error redaction or concurrent quota reservation test (FOUND-008, FOUND-012).
8. Cleanup migration success/failure shell status is untested (FOUND-014).
9. No CI-reference existence/meta-test and no real integration directory (FOUND-016).
10. No shutdown test proving the WebSocket task completes before DB disposal (FOUND-022).

### Explicit clean areas

- **Current SQLite integrity:** read-only `quick_check` is `ok`, `foreign_key_check` is empty, and aggregate duplicate/invalid-row checks are zero. SQLite pragmas enable foreign keys, WAL, and a 30-second busy timeout at `backend/app/db/database.py:88-111`.
- **Session ownership:** `get_db_session` rolls back on exceptions, rethrows, and closes in `finally` at `backend/app/db/database.py:74-85`. Focused tests preserve the shared-session DB lock design at `backend/tests/test_db_gate_concurrency.py:55-99` and `backend/tests/test_db_gate_concurrency.py:104-198`.
- **Fresh natural-key models:** fresh metadata declares unique stock/analytics/NSE flow/bhavcopy/shareholding keys at `backend/app/models/database.py:60-64`, `backend/app/models/database.py:83-87`, `backend/app/models/database.py:140-164`, and `backend/app/models/database.py:209-212`; FOUND-009 is specifically about existing-DB convergence.
- **Portfolio schema validation:** ticker format/length and positive weight/quantity/buy-price boundaries are enforced at `backend/app/models/schemas.py:11-53`; long NSE/BSE and invalid-format cases are tested at `backend/tests/test_contract_p1_batch.py:214-245`.
- **Holding helper:** holding-window calculations are pure/deterministic at `backend/app/utils/holdings.py:30-260`; no foundation defect was found.
- **Additive portfolio migration safety:** it takes a SQLite backup before mutation and no longer fabricates holdings at `backend/migrations/add_portfolio_columns.py:16-26`, `backend/migrations/add_portfolio_columns.py:43-80`; its legacy-default behavior is tested at `backend/tests/test_bugfix_foundation.py:48-94`.
- **Logger level handling:** invalid levels fall back to INFO and handlers are not duplicated at `backend/app/utils/logger.py:24-53`; tested at `backend/tests/test_bugfix_foundation.py:284-296`.
- **Lock integrity:** the checked-in lock contains exact package versions and artifact hashes, and focused frozen-environment tests ran successfully from the existing environment.
- **Pre-commit:** the hook is backend-only, no-sync, cache-free in intent, and correctly rejects Ruff failure at `.githooks/pre-commit:7-19`.
- **Local Git secret hygiene:** `backend/.env` is ignored and untracked. No local secret value was read or reported.

### Limitations

- Docker/Compose could not be executed because the `docker` executable is absent; runtime import/path findings were reproduced with a direct SQLAlchemy probe, and build-context existence was checked explicitly.
- No external vendor request was made. Alpha Vantage findings use mocked/fake credentials only.
- `uv.lock` was audited through project metadata and every direct package record, not all 4,169 wheel URL lines; this follows the “lock config only as needed” scope.
- `backend/main.py` was reviewed only for startup, DB lifecycle, health, logging, and entrypoint concerns. Endpoint business findings are left to the API auditor; no duplicate endpoint-logic finding is included.
- The full test suite was not run because the contract is documentation-only and many tests create temporary artifacts. The 59 focused foundation/provider/concurrency tests passed; Ruff and both shell syntax checks passed. No Python type-checker is configured in `backend/pyproject.toml:58-120`.
- Enterprise authentication/scale concerns are intentionally excluded for this personal localhost application.
- Cash-equity/portfolio scope only; no out-of-scope findings or recommendations are included.
