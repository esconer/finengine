# Agent D — foundation/database/deployment remediation

**Date:** 2026-09-24  
**Scope:** D-01 through D-13 only  
**Database safety:** no command opened, queried, backed up, or mutated `backend/data/daisy.db`; all DB fixtures used pytest temp directories.  
**Docker/network safety:** no image/container/volume operation was run. Docker is not installed on this host. No vendor/live network call was made.

## Outcome summary

D-01, D-03, D-04, D-06, D-08, D-09, D-10, and D-13 are implemented with isolated regression evidence. D-02, D-05, D-07, D-11, and D-12 are implemented and statically verified, but an actual image build/runtime is unavailable on this host. D-13 shutdown integration was not edited here; the current concurrent C-owned `backend/main.py` already contains the requested cancel-and-await sequence.

The deterministic pre/post fixture changed from **0 passed / 16 failed** to **16 passed / 0 failed**:

- Before: `evidence/agent-d-foundation-preflight-before.txt`
- Fixture: `evidence/agent-d-foundation-preflight.py`
- After: `evidence/agent-d-foundation-preflight.txt`

## Files changed

### Runtime/schema

- `backend/app/config.py`
- `backend/app/db/database.py`
- `backend/app/models/database.py`
- `backend/migrations/__init__.py`
- `backend/migrations/schema_version.py` (new)
- `backend/migrations/sqlite_backup.py` (new)
- `backend/migrations/add_portfolio_columns.py`
- `backend/migrations/cleanup_duplicates_and_add_constraints.py`

`backend/app/models/schemas.py` was subsequently tightened by the final finite-request validation gate; `backend/app/utils/` required no edit.

### Container/deployment/CI

- `backend/Dockerfile`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `.github/workflows/ci-cd.yml`
- `scripts/deploy.sh`

### Tests/evidence

- `backend/tests/test_agent_d_migrations.py` (new)
- `backend/tests/test_agent_d_deployment_contract.py` (new)
- `backend/tests/test_bugfix_cache_index_selfheal.py` (updated to safe non-destructive semantics)
- `backend/tests/integration/test_compose_services.py` (new; CI target, not run locally)
- `evidence/agent-d-*` fixtures/results

No dependency or lockfile was added or changed.

## Issue-by-issue implementation

### D-01 — Compose async URL and mounted path: implemented

- `docker-compose.yml:6,13,18-19` and `docker-compose.prod.yml:7,14,19` use backend context and `sqlite+aiosqlite:////app/backend/data/daisy.db`; that URL resolves exactly to the mounted `/app/backend/data/daisy.db` in the Linux container.
- `backend/app/config.py:26-43` rejects a sync SQLite URL before engine construction.
- `backend/app/db/database.py:52-75` resolves the configured file path, runs versioned migration, then uses `create_all` only for missing tables.
- `backend/tests/test_agent_d_deployment_contract.py:28-59` checks both rendered Compose files and Settings path/driver behavior.

### D-02 — Docker layout/dependencies/import root: implemented statically

- `backend/Dockerfile:2-17` standardizes a `backend/` context, Bookworm Python 3.12 builder/production stages, frozen lock install, and pinned UV `0.12.17`.
- `backend/Dockerfile:24-44` installs the runtime virtualenv under `/app`, uses `/app/backend` as the working/import root, copies only Python runtime source/migrations, and installs `libgomp1` for scientific runtime wheels.
- `backend/Dockerfile:54` starts `uvicorn main:app`; this matches `backend/main.py` imports.
- `backend/tests/test_agent_d_deployment_contract.py:62-89` statically verifies layout, runtime, and COPY safety.
- YAML and import smoke checks passed; see verification below.
- **Runtime limitation:** Docker/Compose binaries are absent, so `docker build`, `docker compose config`, image startup, and container health execution remain unverified.

### D-03 — no destructive deployment cleanup: implemented

- `scripts/deploy.sh` contains no `docker volume prune`, container/image prune, `compose down`, or `down -v` path.
- Deployment recreates only the two named services with `compose up --no-build --force-recreate` (`scripts/deploy.sh:163,232`).
- `backend/tests/test_agent_d_deployment_contract.py:91-116` is a destructive-command sentinel.

### D-04 — verified SQLite backup/restore: implemented

- `backend/migrations/sqlite_backup.py:24-102` implements SQLite `Connection.backup`, `PRAGMA quick_check`, exact per-table count comparison, and restore-to-new-file using the backup API.
- `scripts/deploy.sh:70-118` resolves the actual configured DB inside a one-off backend service, creates a backup beside the mounted DB, copies it to `backups/production/`, and verifies the host artifact through the same image.
- No raw SQL/`iterdump`, automatic backup deletion, or guessed hard-coded DB path remains.
- `backend/tests/test_agent_d_migrations.py:209-232` backs up, restores, and verifies temp SQLite counts/rows.

### D-05 — probes target published services and test DB readiness: implemented

- Backend is published on 8000 and frontend on 3000 in both Compose files; production binds them to loopback because no tracked ingress config exists.
- Backend Docker/Compose probes use Python stdlib HTTP plus SQLite `quick_check` (`backend/Dockerfile:51-52`; Compose health blocks beginning at `docker-compose.yml:21` and `docker-compose.prod.yml:35`).
- Frontend Compose probes use Node's built-in `fetch`, not absent `curl`/`wget`.
- `scripts/deploy.sh:166-205` polls the published URLs and then verifies the running DB.
- `/health` remains a safe liveness endpoint. Meaningful DB readiness is enforced outside the endpoint in the probe, so no C-owned `main.py` edit was required.

### D-06 — rollback selects recorded image identity: implemented

- `scripts/deploy.sh:117-159` resolves/pins the selected images to `sha256:*` IDs and records the currently running pre-deploy pair in `.deploy/production.previous.env` using mode `077` creation semantics; rollback prefers that file and falls back to the last successful `.deploy/production.env`.
- `scripts/deploy.sh:199-240` validates recorded IDs, tags those exact local images as unique rollback tags, exports those image variables, recreates services, and requires readiness.
- `scripts/deploy.sh:260-294` explicitly invokes rollback on a failed deployment stage; it never falls back to same-config restart.
- Docker-free fixture `evidence/agent-d-deploy-dry-run.sh` (result: `evidence/agent-d-deploy-dry-run.txt`) stubs Docker/Compose and proves the selected recorded IDs/tags and forced recreation.

### D-07 — absent bind trees: implemented by removal

- Development retains only existing `backend/data`, `frontend/src`, and `frontend/public` bind sources.
- Production has no host bind mounts. Unsupported absent `nginx/`, `ssl/`, and `monitoring/` trees and their unused services were removed rather than replaced with invented config.
- Consequence: production currently exposes backend/frontend only on `127.0.0.1:8000`/`:3000`; public TLS/ingress is explicitly unsupported until tracked configuration is supplied in a separately approved scope.
- `backend/tests/test_agent_d_deployment_contract.py:43-46` asserts every remaining bind source exists.

### D-08/D-09 — versioned convergence and constraints: implemented safely

- `backend/migrations/schema_version.py:37,47-56,232-289` defines schema version 1, a blocking migration error, and backup API support.
- `backend/migrations/schema_version.py:291-579` preflights duplicate natural keys, invalid values, and missing required columns before mutation. Conflicts are returned with row/key details; nothing is deleted.
- `backend/migrations/schema_version.py:687-782` validates the resulting contract; `backend/migrations/schema_version.py:784-858` applies/backups/commits it; `:932-973` provides a data-preserving v1-to-v0 downgrade for the owned portfolio/OHLCV integrity layer.
- Startup invokes it at `backend/app/db/database.py:52-75`. `create_all` is no longer an evolution mechanism for existing tables.
- `backend/app/models/database.py:31-73` adds case-insensitive canonical portfolio ticker uniqueness, non-null metadata, and compatibility-safe numeric checks. The weight check permits zero because C's full-exit rebalance uses zero as a transitional persisted sentinel before row removal.
- `backend/app/models/database.py:100-132` adds finite/non-negative OHLCV and envelope checks.
- Existing null sector/industry values map to the historical `Unknown` sentinel; absent legacy quantity/buy price map to `0.0` unknown-cost sentinel. No holding identity or market datum is deleted.
- Duplicate portfolio/stock/cache/NSE keys block startup, create a backup, leave DB bytes/version unchanged, and require operator reconciliation. This is the required safe mapping behavior.
- Fresh-vs-migrated semantic parity is tested at `backend/tests/test_agent_d_migrations.py:139-150`.

### D-10 — persistence invalid-data/nullability boundary: implemented; B integration present

- ORM/table checks above reject negative/non-finite prices, invalid volume, invalid open/close envelope, out-of-range portfolio weight, duplicate canonical ticker, and raw NULL metadata.
- Current B-owned normalization is now visible at `backend/app/services/data_service.py:1247-1322`: finite/positive/envelope-invalid rows are quarantined before persistence. `backend/tests/test_agent_b_data_audit.py` passes all 24 tests, including B-06.
- Current C-owned portfolio writes normalize missing sector/industry to `Unknown`; current C-owned exception mapping handles cross-session ticker `IntegrityError`. The focused duplicate API test passes.

### D-11 — image secret/data scope: implemented at image-layer boundary

- `backend/Dockerfile:14,33-44` is an explicit allowlist. Wildcards are limited to `*.py`; it does not copy `.env*`, `data/`, `logs/`, `backups/`, tests, coverage, or `__pycache__`.
- `backend/tests/test_agent_d_deployment_contract.py:62-89` rejects broad/secret/data COPY patterns.
- **Known boundary:** `.dockerignore` is outside the allowed edit set. A remote builder can therefore still receive ignored files in the *build context transfer* even though they are not copied into an image layer. Coordinator should add a backend-context `.dockerignore` when permitted.

### D-12 — real CI targets/services: implemented statically

- `.github/workflows/ci-cd.yml:44-64` uses the locked dev+group dependencies, Ruff no-cache, and the required pytest cache/coverage invocation; backend build context is `backend/`.
- `.github/workflows/ci-cd.yml:130-153` now references the existing executable `backend/tests/integration/test_compose_services.py` and uses `docker compose ... up --wait`; cleanup never removes volumes.
- The nonexistent Lighthouse config, nonexistent `tests/integration/` target, and nonexistent frontend `test:e2e` command were removed.
- The job that only pushed ECR artifacts but claimed deployment is now honestly named `production-images` (`:153-207`); it no longer curls unrelated external hosts. There is still no checked-in rollout target.
- `.github/workflows/ci-cd.yml` parses as YAML; static contract tests pass. The Compose integration test was not run locally because Docker and live service/network execution are prohibited/unavailable.

### D-13 — failure/shutdown safety: implemented for owned paths; C integration already present

- `backend/migrations/schema_version.py:975-1020` returns nonzero on migration failure.
- `backend/migrations/cleanup_duplicates_and_add_constraints.py:70-72,94-120,126-129` no longer deletes duplicate data and exits nonzero when migration/validation fails.
- `backend/tests/test_agent_d_migrations.py:172-176` proves CLI exit code 1 on blocked data.
- I did not edit C-owned `backend/main.py`. Current shared-tree lines `66-70` now cancel the WebSocket task and await it under `suppress(asyncio.CancelledError)` before DB disposal, so the original shutdown recommendation is already integrated by C.

## Verification

All Python test commands used `PYTHONDONTWRITEBYTECODE=1`, `uv run --project backend --frozen`, `pytest -p no:cacheprovider --no-cov`.

### Passing focused gates

1. Foundation/migration/deployment/cache regression:

```text
uv run --project backend --frozen pytest \
  backend/tests/test_agent_d_deployment_contract.py \
  backend/tests/test_agent_d_migrations.py \
  backend/tests/test_bugfix_foundation.py \
  backend/tests/test_bugfix_cache_index_selfheal.py \
  -p no:cacheprovider --no-cov -q
# 37 passed in 3.41s
```

2. C portfolio integration against the new DB boundary:

```text
uv run --project backend --frozen pytest \
  backend/tests/test_coverage_portfolio_api.py \
  -p no:cacheprovider --no-cov -q
# 19 passed in 3.88s
```

3. B persistence/OHLCV integration:

```text
uv run --project backend --frozen pytest \
  backend/tests/test_agent_b_data_audit.py \
  -p no:cacheprovider --no-cov -q
# 24 passed (current B audit gate)
```

4. Health/B-06/duplicate mapping seam:

```text
uv run --project backend --frozen pytest \
  backend/tests/test_bugfix_api_layer.py::test_health_reports_settings_environment \
  backend/tests/test_agent_b_data_audit.py::test_b06_invalid_ohlcv_quarantined_but_valid_and_large_move_kept \
  backend/tests/test_coverage_portfolio_api.py::TestPortfolioAPIEndpoints::test_add_position_duplicate_and_quote_fail \
  -p no:cacheprovider --no-cov -q
# 3 passed in 0.76s
```

5. Ruff:

```text
uv run --project backend --frozen ruff check --no-cache <all Agent D changed Python files>
# All checks passed!
```

6. Shell/static:

```text
bash -n scripts/deploy.sh
# exit 0

bash .scratch/backend-deep-audit/fixes/evidence/agent-d-deploy-dry-run.sh
# PASS rollback selected recorded image IDs and forced recreation without Docker

uv run --project backend --frozen python \
  .scratch/backend-deep-audit/fixes/evidence/agent-d-foundation-preflight.py
# 16 passed; 0 failed

git diff --check -- <Agent D changed tracked files>
# exit 0 (Git emitted only Windows LF/CRLF conversion warnings)
```

7. YAML/render and import smoke:

```text
uv run --project backend --frozen python -c "<safe_load Compose x2 + CI; assert exact async DB URL>"
# YAML_OK exact async DB URLs rendered

uv run --project backend --frozen python -c "import main; ..."
# Daisy Risk Engine API
```

The Compose live integration test was intentionally not run. The current coordinator integrated regression set is **224 passed**; D's own migration/deployment contract gate is **19 passed** and the final foundation/cache gate is **39 passed**.

## Docker availability

The following all failed because the executables are absent from PATH:

- `docker version`
- `docker compose version`
- `docker-compose version`

Therefore no claim is made that the image builds, starts, or passes an in-container probe. Static Dockerfile/CI/context checks and host import/YAML checks passed.

## Unresolved / intentionally unsupported

1. **Runtime image proof:** requires a Docker-capable host. CI must prove build, app import, container health, named-volume persistence, and integration test on first run.
2. **Build-context transfer:** image layers are allowlisted, but `.dockerignore` remains coordinator work because it was outside allowed writes.
3. **Public ingress/TLS:** absent Nginx/SSL/monitoring trees were removed. Production is loopback-only until tracked ingress is separately approved.
4. **Actual rollout:** CI publishes ECR images only; no Kubernetes/other rollout definition exists, so the workflow no longer falsely claims deployment.
5. **Existing duplicate data:** migration intentionally blocks rather than chooses winners. An operator must reconcile reported canonical keys and rerun; no live DB was inspected.
6. **Downgrade scope:** v1 downgrade removes the owned portfolio/OHLCV integrity layer while preserving rows/columns; unrelated pre-existing model constraints are intentionally retained.
7. **Future schema changes:** any later model change must add schema version 2 rather than relying on `create_all`.
8. **Base image digest:** UV is version-pinned and Python is minor-line/Bookworm-pinned, but a tested base-image digest was not added because Docker registry digest verification was unavailable.

## Cross-file recommendations

- **Optional app-level readiness (C-owned `backend/main.py`):** keep `/health` as liveness; if desired, add `/ready` using `engine.connect()` + `await conn.execute(text("SELECT 1"))`, return 503 on failure, and switch probes to `/ready`. Current probes already achieve readiness by checking DB directly, so this is not required for D-05.
- **Shutdown:** current C tree already has the exact requested cancel/await/suppress sequence. Preserve it during integration; do not restore the old cancel-then-dispose code.
- **B:** preserve the current finite/positive/envelope sanitizer and atomic no-partial-write behavior. DB checks are the final safety net, not a substitute for provider normalization.
- **C:** preserve the current `IntegrityError` → 409 mapping and `sector/industry or "Unknown"` normalization. The focused API test now passes with the database uniqueness boundary.
- **Coordinator:** add `.dockerignore` and tracked ingress/rollout configuration in separately owned scope; pin the Python base by verified digest when Docker/registry access is available.

## Residual runtime review closure (2026-09-24)

The final residual review identified that the production HTTPS redirect also intercepted the loopback container probe, and that host backup permissions were applied too late. The backup hardening is implemented and its focused regression passes. The health middleware now overrides the ASGI `__call__` path rather than `dispatch`; the actual production `main.app` probe returns HTTP 200 for `/health` and `/api/v1/health` with `follow_redirects=False`, while `/` remains HTTPS 307. `scripts/deploy.sh` sets the container backup process umask before SQLite creates the file and atomically reserves the host artifact with mode `0600` before `compose cp` writes it. The focused deployment/migration gate is **19 passed** and `bash -n scripts/deploy.sh` passes. The final independent residual review marked the backup and production health contracts **PASS**. Docker/Compose binaries remain absent, so image build and in-container health execution are still explicitly unverified.
