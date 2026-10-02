# Detail — Infra / CI / Tests / Deps (`INF-1`..`INF-22`)

**Writer:** A3. **Source inventory:** `plans/2026-10-audit/inventory-a2fe-a3infra.md` Part 2.
**Overrides applied:** `ORCHESTRATOR-CORRECTIONS.md`. No COR-1..COR-8 touched an `INF-*` row
(COR-1..COR-4 are `FE-*`, COR-5 `OE-13`, COR-6 heading level, COR-7 inventory filenames,
COR-8 `SVC-1`); COR-7 is applied here as a rule — **every filename in an inventory table was
re-derived from source, not trusted.**

**Verification method.** Every `path:line` below was opened by me. Absences are proved with a
control search that *does* match, named inline. `Select-String -SimpleMatch` throughout, per the
plan's tooling note. `Get-ChildItem -Force -Recurse` used for directory claims.

**Summary:** 22 rows. 5 BLOCKER · 2 DEFECT · 14 RISK · 1 NIT. Confidence: 19 VERIFIED ·
3 DERIVED · 0 NEEDS-RUNTIME. Six sub-claims from the inventory **failed** re-verification and are
corrected in `## Rejected on re-verification`.

---

### INF-1 — Frontend Docker build cannot succeed: `.next/standalone` is copied but never emitted
- **Class**: bug
- **Severity**: BLOCKER
- **Confidence**: VERIFIED
- **Location**: `frontend/Dockerfile:45`; `frontend/next.config.ts` (absence of `output`)
- **Symptom**: `docker build -f frontend/Dockerfile` fails at the `COPY --from=builder … /app/.next/standalone` layer. Next.js only emits that directory when `output: 'standalone'` is configured. Nobody notices because the job that would reveal it sits behind failures that pre-empt it (INF-3), and the compose files use a locally-built image that is never pushed.
- **Evidence**:
  ```dockerfile
  # frontend/Dockerfile:44-46
  COPY --from=builder /app/public ./public
  COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
  COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
  ```
- **Proof of absence**: `Select-String -Path frontend\next.config.ts -Pattern 'output' -SimpleMatch` → **ZERO MATCHES**. Control in the same file: `reactCompiler` → 1 match at `:5` (`reactCompiler: false, // Disabled for stability`). The file is 41 lines and its `nextConfig` object (`:3-39`) contains `compress`, `poweredByHeader`, `productionBrowserSourceMaps`, `onDemandEntries`, `experimental`, `rewrites`, `env` — and no `output`.
- **Mechanism**: (1) build emits `.next/standalone` only under `output: 'standalone'`; (2) `Dockerfile:45` copies that path unconditionally; (3) `COPY` of a non-existent source fails, aborting the image build.
- **Impact**: the `frontend` CI job goes red at its `docker build` step (`.github/workflows/ci-cd.yml:109`), so the ghcr push at `:111-115` never executes, `integration` (`needs: [backend, frontend]`) never runs, and `production-images` never runs. **No frontend container image is ever produced by CI.** This is independent of INF-3.
- **Suggested fix**: add `output: 'standalone'` to `nextConfig`. **Blast radius:** small but *not* cosmetic — standalone output changes the runtime layout (`server.js` at the image root is the standalone layout, which is what `Dockerfile:62` already assumes), so the image must be rebuilt and re-verified end to end before the fix is believed. It does not weaken any test.

### INF-2 — Base image `node:18-alpine` is below Next 16.3.6's declared Node engine floor
- **Class**: bug
- **Severity**: BLOCKER
- **Confidence**: VERIFIED
- **Location**: `frontend/Dockerfile:2`; `frontend/package.json:35`
- **Symptom**: even with INF-1 fixed, `bun run build` (i.e. `next build`) executes on Node 18 inside the image while the pinned Next release declares `node >= 20.9.0`. Nothing warns locally because `package.json` carries no `engines` field, so the floor is invisible outside the registry.
- **Evidence**:
  ```dockerfile
  # frontend/Dockerfile:2
  FROM node:18-alpine AS base
  ```
  ```json
  // frontend/package.json:35
      "next": "^16.3.6",
  ```
  Primary source, `registry.npmjs.org/next/16.3.6`: `"engines":{"node":">=20.9.0"}`.
- **Mechanism**: (1) `base` is Node 18; (2) every stage (`deps`, `builder`, `runner`) inherits it; (3) `next build` runs on a runtime below its own declared floor — the failure is either a hard refusal or, worse, an unsupported-and-silent path, and either way the image cannot be trusted.
- **Impact**: a second, independent cause of `docker build` failure at `ci-cd.yml:109`. Two co-located fatal errors in one 62-line Dockerfile is strong evidence the file has never been executed in anger.
- **Suggested fix**: bump `base` to `node:20-alpine` (or `22`). **Blast radius:** the `bun` install at `Dockerfile:10` and `:23` uses `npm install -g bun`; a Node major bump can change that binary's resolution, so the build must be re-run. Do **not** add an `engines` field to `package.json` as a "fix" — that only converts a build-time refusal into a local install warning and does not move the image off Node 18.

### INF-3 — The `backend` CI job cannot pass: a localhost-only smoke test is collected by the unit run
- **Class**: bug
- **Severity**: BLOCKER
- **Confidence**: VERIFIED
- **Location**: `.github/workflows/ci-cd.yml:51-54`; `backend/pyproject.toml:83`; `backend/tests/integration/test_compose_services.py:19-27`
- **Symptom**: `pytest … tests/` collects the Compose smoke test, which calls `urlopen("http://127.0.0.1:8000/health")` on an `ubuntu-latest` runner with nothing listening. The job is red on every push. Everything downstream of it is skipped.
- **Evidence**:
  ```yaml
  # .github/workflows/ci-cd.yml:51-54
      - name: Run backend tests with 80% coverage gate
        working-directory: backend
        run: |
          uv run pytest -p no:cacheprovider tests/ --cov=app --cov-fail-under=80 --cov-report=xml --cov-report=term
  ```
  ```python
  # backend/tests/integration/test_compose_services.py:19-20
  def test_published_backend_and_frontend() -> None:
      backend_status, backend_body = _read("http://127.0.0.1:8000/health")
  ```
- **Proof of absence**: `backend/tests/integration/` contains exactly two entries — `test_compose_services.py` and `__pycache__` (`Get-ChildItem -Force`). There is **no `conftest.py`** in that directory, hence no skip guard. And `pyproject.toml:83` `testpaths = ["tests"]` makes `tests/integration/` in scope for the `tests/` argument.
- **Mechanism**: (1) `testpaths = ["tests"]` and the CLI arg `tests/` both include `tests/integration/`; (2) the file defines a `test_`-prefixed function with no skip marker; (3) collection executes it, `urlopen` raises `URLError`, the run goes red.
- **Impact**: `backend` red ⇒ `integration` skipped (`needs: [backend, frontend]`) ⇒ `production-images` skipped (`needs: [backend, frontend, security, integration]`) ⇒ `notify-failure` fires. **This is the load-bearing finding: CI has never been green**, so there is no automated evidence that any image in ECR or ghcr exists.
- **Note — the declared-but-unused marker is systemic, not a single stray.** `pyproject.toml:87-93` declares six markers. Applying each across `backend/tests`:
  `unit` → 13 · `api` → 41 · `websocket` → 1 · **`integration` → 0** · **`database` → 0** · **`slow` → 0**.
  Control: `pytestmark` → 1 match (`backend/tests/conftest.py:431`), proving the enumeration is live.
- **Suggested fix**: move the smoke test out of `tests/` (it is *designed* to be run directly — `test_compose_services.py:3-5` documents `python backend/tests/integration/test_compose_services.py` and has a `__main__` block at `:30-31`), or mark it `@pytest.mark.integration` **and** add `-m "not integration"` to the CI invocation. **Blast radius:** the second option touches `addopts`/`ci-cd.yml` and must not be allowed to silently deselect any currently-unmarked test — assert the collected count. Do not "fix" it by widening the coverage gate or by deleting the test.

### INF-4 — The 57-rule audit gate is bound to one developer's `%TEMP%` and hard-fails without it
- **Class**: bug
- **Severity**: BLOCKER
- **Confidence**: VERIFIED
- **Location**: `backend/tests/test_audit_rule_coverage.py:77`, `:1055-1063`
- **Symptom**: on any machine that is not the original author's, the only mechanism that measures whether the export's rules can *fail* calls `pytest.fail`. It is a second, independent reason the `backend` job is red — and the failure message is about a missing file, so it reads as infrastructure noise rather than "the audit gate did not run".
- **Evidence**:
  ```python
  # backend/tests/test_audit_rule_coverage.py:77
  BASE_EXPORT = Path(r"C:\Users\Sayanti\AppData\Local\Temp\opencode\v27.json")
  ```
  ```python
  # backend/tests/test_audit_rule_coverage.py:1055-1063
  def _base_document() -> dict[str, Any]:
      if not BASE_EXPORT.is_file():
          pytest.fail(
              f"the reference export is missing: {BASE_EXPORT}. This harness "
              f"measures rule coverage against a real export; skipping would "
              f"leave the gate reporting nothing while exiting 0, which is the "
              f"exact failure mode it exists to detect."
          )
      return json.loads(BASE_EXPORT.read_text(encoding="utf-8"))
  ```
- **Mechanism**: (1) the fixture path is an absolute path into one user's temp directory, outside the repo; (2) on any other machine (including every `ubuntu-latest` runner) `is_file()` is False; (3) `pytest.fail` turns a missing input into a red suite rather than a distinguishable "gate not run".
- **Impact**: the audit coverage gate has never executed in CI. Its `KNOWN_UNCOVERED`/`KNOWN_COLLATERAL` assertions (`:1324`, `:1337`) — the part that makes the gate trustworthy in the *improving* direction — are equally unexercised. The file's own failure text names the exact anti-pattern it is guarding against, which makes the placement the defect.
- **Suggested fix**: vendorise the export to `backend/tests/fixtures/` (scrubbed) and resolve the path relative to `__file__`, with `BASE_EXPORT` overridable by an env var for local use. **Blast radius: the fixture must be sanitised before committing** — the repo's own `.gitignore:81-85` rationale is explicit that generated exports contain live holdings, quantities, cost basis and P&L. **This is the stated constraint and it is load-bearing: do not commit the raw `v27.json`.** Preserve the `pytest.fail` (not `skip`) — it is the correct semantic; only the *location* is wrong. NUM-014 and the frozen-set assertions must survive intact.

### INF-5 — Backend container healthcheck parses `DATABASE_URL` with `rsplit`, yielding a **relative** path
- **Class**: bug
- **Severity**: BLOCKER
- **Confidence**: VERIFIED
- **Location**: `backend/Dockerfile:52`; `docker-compose.yml:29-34`, `:58-60`; `docker-compose.prod.yml:43-48`, `:70-72`
- **Symptom**: the backend container never reports healthy, so `depends_on: {condition: service_healthy}` is never satisfied and the frontend never starts under **either** compose file. In CI this is a second, independent blocker of the `integration` job's `docker compose … --wait`.
- **Evidence**:
  ```dockerfile
  # backend/Dockerfile:52 (WORKDIR is /app/backend, :24)
  CMD ["python", "-c", "import os,sqlite3,urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3).close(); p=os.environ['DATABASE_URL'].rsplit('///',1)[1]; c=sqlite3.connect(p,timeout=3); ok=c.execute('PRAGMA quick_check').fetchone()[0]; c.close(); assert ok == 'ok', ok"]
  ```
  ```yaml
  # docker-compose.yml:13  and  docker-compose.prod.yml:14
      DATABASE_URL: sqlite+aiosqlite:////app/backend/data/daisy.db
  # docker-compose.yml:29-30
          url = os.environ['DATABASE_URL'];
          path = url.rsplit('///', 1)[1];
  ```
- **Derivation of the split (stated explicitly because it was disputed upstream).** The shipped URL has **four** slashes. Python's `rsplit('///', 1)` splits from the **right**, so the rightmost `///` is the *last three* of the four slashes and one slash is left on the left side:
  `left = 'sqlite+aiosqlite:/'`, `right = 'app/backend/data/daisy.db'` — **relative**. Resolved against `WORKDIR /app/backend` (`Dockerfile:24`) that is `/app/backend/app/backend/data/daisy.db`, whose parent directory is never created (only `/app/backend/data` is, at `Dockerfile:30-31`); `sqlite3.connect` then raises `OperationalError: unable to open database file`. *(The orchestrator's earlier note that `url.split('///',1)[1]` yields the correct absolute `/app/backend/data/daisy.db` is true — but that is `split`, not the `rsplit` the code actually calls. The two differ precisely because there are four slashes.)*
- **Mechanism**: (1) SQLAlchemy reads four slashes as an absolute path, so the app serves traffic correctly from `/app/backend/data/daisy.db`; (2) the healthcheck re-parses the same string with `rsplit`, yielding the *relative* `app/backend/data/daisy.db`; (3) resolved against `WORKDIR /app/backend` that path's parent directory was never created and the container runs as non-root `appuser`, so `sqlite3.connect` raises `OperationalError` and the healthcheck exits non-zero. The one component that decides health disagrees with the component that actually serves traffic.
- **Impact**: `integration` job (`ci-cd.yml:157`) runs `docker compose … up -d --build --wait`; `--wait` blocks on health, so the job can never proceed even if INF-3 and INF-1 are fixed. Locally, neither `docker-compose.yml` nor `docker-compose.prod.yml` ever brings up a working frontend.
- **Suggested fix**: stop string-parsing the URL in the healthcheck — assert the file exists via a path the compose file passes explicitly (e.g. a `DATABASE_PATH` env var), or drop the `PRAGMA quick_check` half and keep the `urlopen` liveness probe that already works. **Blast radius:** three copies of the same expression (`Dockerfile:52`, `docker-compose.yml:30`, `docker-compose.prod.yml:44`) must change together or the fix lands on only one path. Note the fix must not weaken the check into a no-op — the `quick_check` is a genuine readiness signal and the non-root `USER appuser` (`Dockerfile:46`) means a missing directory cannot be silently created.

### INF-6 — Frontend prod-image healthcheck calls `curl`, which alpine does not ship
- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `frontend/Dockerfile:58-59`; the only `apk add` is `frontend/Dockerfile:6`
- **Symptom**: the built frontend image is permanently unhealthy: `curl` is not on PATH in a `node:*-alpine` base (BusyBox ships `wget`), so the probe exits 127 on every attempt.
- **Evidence**:
  ```dockerfile
  # frontend/Dockerfile:58-59
  HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
      CMD curl -f http://localhost:3000 || exit 1
  # frontend/Dockerfile:6  — the only package installed in the whole image
  RUN apk add --no-cache libc6-compat
  ```
- **Mechanism**: (1) `node:18-alpine` has no `curl`; (2) the only `apk add` is `libc6-compat`, a libc shim; (3) `CMD curl -f …` resolves to nothing, shell exit 127, `HEALTHCHECK` fails.
- **Impact**: no user-visible outage *in this repo*, because both compose files **override** the image healthcheck with a working probe: `docker-compose.yml:62` and `docker-compose.prod.yml:87` both use `["CMD", "node", "-e", "fetch('http://127.0.0.1:3000')…"]`. The defect bites whoever consumes the pushed ECR/ghcr image, where no override exists. Bounded blast radius → DEFECT, with a workaround already in-tree.
- **Suggested fix**: use the same `node -e fetch(...)` probe the compose files already prove works, so image and compose agree. **Blast radius:** one line; strictly reduces false-unhealthy reports. Do not `apk add curl` — that adds a package to the runtime image to satisfy a probe the codebase has already written correctly elsewhere.

### INF-7 — `restoreMocks`/`unstubGlobals` absent while `setup.ts` mutates globals at module scope
- **Class**: bug (test infrastructure)
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `frontend/vitest.config.mts:8-14` (absence); `frontend/src/test/setup.ts:23`, `:26`, `:35`, `:58`, `:66`; workaround sites at `store.test.ts:125`, `useAnalytics.test.tsx:35`, `HeaderRiskMetricsWiring.test.tsx:48`, `AnalyticsUnavailableContracts.test.tsx:119`
- **Symptom**: `setup.ts` installs process-wide `vi.fn()` replacements for `fetch`, `WebSocket`, `localStorage`, `ResizeObserver` and `IntersectionObserver` at module scope. Without `restoreMocks`, mock **call history and return values** persist across test cases in a file. A test that asserts "not called" after another test consumed the mock fails, or passes for the wrong reason. Latent flake — no failing test is reproduced.
- **Evidence**:
  ```ts
  // frontend/vitest.config.mts:8-11
      test: {
          globals: true,
          environment: 'jsdom',
          setupFiles: ['./src/test/setup.ts'],
  ```
  ```ts
  // frontend/src/test/setup.ts  — all at module scope, no beforeEach wrapper
  23: global.WebSocket = MockWebSocket as any
  26: global.fetch = vi.fn()
  35: vi.stubGlobal('localStorage', localStorageMock)
  58: global.ResizeObserver = MockResizeObserver as any
  66: global.IntersectionObserver = MockIntersectionObserver as any
  ```
- **Proof of absence**: in `vitest.config.mts`, `restoreMocks` → **ZERO MATCHES**; `unstubGlobals` → 0; `clearMocks` → 0; `mockReset` → 0; `pool` → 0; `threads` → 0; `singleThread` → 0; `fileParallelism` → 0; `isolate` → 0; `maxWorkers` → 0. Control in the same file: `coverage` → 2 matches (`:12`, `:20`), proving the searches are live.
- **Mechanism**: (1) `setup.ts` executes at module scope and assigns process-wide `vi.fn()` replacements; (2) with `restoreMocks` unset, vitest does not reset call history or implementations between test cases in a file; (3) state set by one test is visible to the next, so an assertion reads another test's consumption.
- **The fingerprint**: the four test files already hand-roll `mockReset()` loops — confirmed at all four cited lines, **7 `mockReset` calls total across `frontend/src`** (control: same search over the tree returns 7).
- **Impact**: developer-facing; no user-visible effect. Caps at RISK per plan §3. The silent-failure direction is the concerning one: a leaked `mockReturnValue` makes a subsequent assertion pass for the wrong reason.
- **Suggested fix**: set `restoreMocks: true` (and `unstubGlobals: true`) in `vitest.config.mts` `test:`. **Blast radius: this is the one fix in this section that could turn green tests red** — the 7 hand-rolled `mockReset` calls would become redundant, and any test that *depends* on a leaked mock will start failing. That is the correct outcome (it surfaces real coupling), but it needs to land as a visible change, not silently. It must not be combined with any relaxation of the coverage thresholds at `vitest.config.mts:24-31` (`branches/functions/lines/statements` all 80) — that gate is load-bearing.

### INF-8 — `async_client` does not rebind the global engine; `websocket.py` binds `SessionLocal` at import
- **Class**: risk
- **Severity**: RISK
- **Confidence**: DERIVED
- **Location**: `backend/tests/conftest.py:223-230` vs `:245-257`; `backend/app/api/websocket.py:19`
- **Symptom**: a green test run can write to — or mutate — the developer's real `backend/data/daisy.db`. Holdings, cost basis and P&L are exactly what the repo's own `.gitignore:81-85` says must never leak. Not reproduced; no test is shown here to actually reach a direct-`SessionLocal` path through this fixture.
- **Evidence**:
  ```python
  # backend/tests/conftest.py:223-230
  @pytest_asyncio.fixture
  async def async_client(test_db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
      """Async test client bound to the ISOLATED test database (never daisy.db)."""
      app.dependency_overrides[get_db_session] = _override_get_db(test_db)
      transport = ASGITransport(app=app)
      async with AsyncClient(transport=transport, base_url="http://test") as client:
          yield client
      app.dependency_overrides.pop(get_db_session, None)
  ```
  ```python
  # backend/tests/conftest.py:250-256  (the `client` fixture — the comparison)
      monkeypatch.setattr(db_mod, "engine", tmp_engine)
      monkeypatch.setattr(db_mod, "SessionLocal", async_sessionmaker(tmp_engine, ...))
      monkeypatch.setattr(ws_mod, "SessionLocal", db_mod.SessionLocal)
  ```
- **Mechanism**: (1) `async_client` overrides exactly one FastAPI DI dependency (`get_db_session`); (2) it rebinds neither `db_mod.engine` nor `db_mod.SessionLocal` nor the `ws_mod.SessionLocal` alias; (3) any route, background task or WS path that opens its own session uses the real engine. The docstring's "never daisy.db" is an **unbacked guarantee**, and the sibling `client` fixture's docstring (`:235-244`) documents this exact hazard in detail — it was fixed for one fixture and not the other.
- **Mitigating factor, stated because it matters**: `async_client` uses `ASGITransport(app=app)` **without** lifespan, so the `init_db()` self-heal that the `client` docstring warns about does **not** run on this path. The residual exposure is confined to code reached *inside* a request, not to import/startup. That is why this is DERIVED and not VERIFIED.
- **Impact**: if any test using `async_client` reaches a direct-session path, it writes to real user data. Developer-facing; destructive if realised. `backend/data/daisy.db` (with `-wal`/`-shm`) is present on disk.
- **Suggested fix**: give `async_client` the same three-way rebind as `client` (`:250-256`), ideally by extracting one shared fixture so the two cannot drift again. **Blast radius:** rebinding `SessionLocal` for `async_client` will break any test that currently *relies* on the real engine — which is the point, but it must be a deliberate change with the test count asserted, not a drive-by. Do not weaken the `client` docstring's existing protections.

### INF-9 — `test_coverage_direct_unit_routes.py`: 24 assertions that cannot fail
- **Class**: bug (test quality)
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `backend/tests/test_coverage_direct_unit_routes.py` — 24 instances across `:115-224`; mocks `:70-112`; patched-out units `:192`, `:200`, `:208`
- **Symptom**: 24 of the file's assertions are `assert <result> is not None` against FastAPI route functions. A handler that returns `{}`, `{"error": …}`, all-NaN metrics, or a canned dict from a mock passes identically. The file contributes real `app` coverage to a real 80% gate while asserting nothing about any computed value.
- **Evidence**:
  ```python
  # backend/tests/test_coverage_direct_unit_routes.py:115-119
          res_rr = await get_realized_risk(
              tickers="TCS.NS,INFY.NS", db=mock_db,
              data_service=mock_ds, analytics_engine=mock_engine
          )
          assert res_rr is not None
  ```
  ```python
  # :192, :200, :208 — the three units replaced wholesale by canned returns
          with patch("app.api.analytics.simulate_goal", return_value={"prob_reach_target": 0.88, "fan": []}):
          with patch("app.api.analytics.optimize", return_value={"weights": {"TCS.NS": 0.6, ...}, ...}):
          with patch("app.api.analytics.detect_regime", return_value={"current_regime": "calm", ...}):
  ```
- **Mechanism**: (1) the route functions return a dict (or raise) — they have no code path returning `None`; (2) their analytics dependencies are `AsyncMock(return_value=<canned dict>)`; (3) the assertion is satisfied by the return *type* alone, so it is unfalsifiable regardless of the payload.
- **Impact**: the `--cov-fail-under=80` gate (`pyproject.toml:84`, `ci-cd.yml:54`) can be satisfied in part by tests that cannot fail. This is not a test-coverage gap — it is a **gate-strength** gap, which is why it is DEFECT rather than RISK.
- **Systemic, and much larger than first reported**: `Select-String 'is not None' -SimpleMatch` across `backend/tests` → **311 occurrences across 77 files** (control: same search returns 0 outside this tree; within the file itself, 24). See `## Rejected on re-verification` for the corrected figure and for a correction to the stated mechanism.
- **Suggested fix**: replace each `is not None` with an assertion on the actual payload — key presence, sign, magnitude, and identity relations (e.g. `effective_positions ≈ 1/Herfindahl`, `cvar_95 ≤ var_95`). **Blast radius: this is the highest-effort item in this section — 24 assertions here, 311 repo-wide.** It must be done incrementally, and the correct order is: fix the three `patch(...)`-wrapped units first (`:192`, `:200`, `:208`), because there the assertion is *doubly* vacuous — the unit under test never ran. Do not simply delete the assertions: that would reduce measured coverage and could break the 80% gate, which is the opposite of the fix.

### INF-10 — `conftest.py::test_env_vars` cannot do what it claims
- **Class**: maintainability
- **Severity**: RISK
- **Confidence**: DERIVED
- **Location**: `backend/tests/conftest.py:364-385`; the import that freezes settings is `backend/tests/conftest.py:21`
- **Symptom**: the fixture sets `os.environ` entries that the application has already read. It yields a dict that looks authoritative and restores correctly on teardown — the correctness of the teardown is what makes the fixture read as effective.
- **Evidence**:
  ```python
  # backend/tests/conftest.py:20-21  — settings is constructed at import time
  # Application imports
  from main import app
  ```
  ```python
  # backend/tests/conftest.py:364-378
  @pytest.fixture
  def test_env_vars():
      """Set up test environment variables"""
      test_vars = {"DATABASE_URL": TEST_DATABASE_URL, "TESTING": "True", "LOG_LEVEL": "DEBUG"}
      original_vars = {}
      for key, value in test_vars.items():
          original_vars[key] = os.environ.get(key)
          os.environ[key] = value
      yield test_vars
  ```
- **Mechanism**: (1) `conftest.py:21` imports the app, which constructs `settings` (pydantic-settings reads the environment at construction); (2) the fixture then mutates `os.environ` *after* that; (3) `settings` is unchanged, so any code reading `settings.*` sees production/default values while the test believes it has configured them. The `yield` + restore block at `:378-385` is correct and does clean up — it simply cannot undo the ordering.
- *Why DERIVED:* the decisive fact — that no test consumes this fixture — was not established by execution. The fixture *is* exported at `conftest.py:494` (`"test_env_vars"` in `__all__`), so absence of consumers is a search result I did not exhaustively complete. Marked RISK accordingly.
- **Impact**: developer-facing. No current user-visible effect. The hazard is a *false* test: a future test that adopts this fixture to configure the environment will silently not be configured.
- **Suggested fix**: either delete the fixture, or make it honest — `monkeypatch.setenv` **plus** an explicit `settings` rebuild/reload if the point is to test configuration. **Blast radius:** removing it from `__all__` (`:494`) is safe only if the consumer search is completed first; do not delete it on the strength of an unexhausted search.

### INF-11 — `conftest.py`'s module-level `pytestmark` is inert; `cleanup_test_data` cleans nothing
- **Class**: maintainability
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `backend/tests/conftest.py:420-427` (`cleanup_test_data`), `:431-434` (`pytestmark`); cache declarations at `backend/app/services/data_service.py:298`, `:301`, `:303`; the file-local reset at `backend/tests/test_agent_b_data_audit.py:85-91`
- **Symptom**: two pieces of test infrastructure are inert, and both read as if they were doing something. The `pytestmark` says every test is a unit test; it says nothing. The autouse cleanup fixture runs after every test and removes nothing.
- **Evidence**:
  ```python
  # backend/tests/conftest.py:420-427
  @pytest.fixture(autouse=True)
  def cleanup_test_data():
      """Automatically clean up test data after each test"""
      yield
      # Clean up any temporary files, database records, etc.
      # This runs after each test
      pass
  ```
  ```python
  # backend/tests/conftest.py:431-434
  pytestmark = [
      pytest.mark.unit,
      pytest.mark.asyncio
  ]
  ```
- **The `pytestmark` half, proved from pytest's own source** (read from the project's `backend/.venv`, `pytest==8.3.4` — no execution, no install):
  - `_pytest/mark/structures.py:361-391` `get_unpacked_marks(obj)` reads `pytestmark` off the **object** being collected (`obj.__dict__` for classes, `getattr(obj, "pytestmark", [])` otherwise).
  - Its only two callers are `_pytest/python.py:288` (`PyCollectorMixin.collect` — `self.obj` is a collected **module or class**) and `_pytest/python.py:1555`.
  - `_pytest/python.py`'s `pytest_collect_file` guard creates a `Module` item only when `file_path.suffix == ".py"` **and** `path_matches_patterns(file_path, config.getini("python_files"))` holds (default `test_*.py`, `*_test.py`). `conftest.py` matches neither, so a conftest is **never** collected as a `Module`.
  - `_pytest/config/__init__.py:735` registers conftest as a **plugin** (`consider_conftest`), not a test module.
  - Control: the token `conftest` appears **ZERO** times across `_pytest/mark/*.py` — the mark machinery has no conftest code path at all.
  - Conclusion: a `pytestmark` in `conftest.py` never reaches any test. It is inert.
- **The `cleanup_test_data` half**: `yield` then `pass` (`:427`) — verified, it cleans nothing.
- **Mechanism**: (1) `pytestmark` in a `conftest.py` is read by nothing, because pytest only consults `pytestmark` on objects it *collects* (`_pytest/python.py:288`, `:1555`) and a conftest is registered as a plugin, never collected as a module; (2) `cleanup_test_data` is `autouse=True` but its body after `yield` is `pass`; (3) the suite therefore runs 2254 tests believing each is marked `unit` and cleaned, when neither holds — and the caches that *should* have been cleared are cleared by one file-local fixture.
- **The real leak it was supposed to prevent**: `DataService._quote_memo`, `._in_memory_df_cache` and `._l1_sources` are **class-level** dicts (`data_service.py:298`, `:301`, `:303` — `_quote_memo: Dict[str, Any] = {}` in the class body), so they are shared across the whole session. They are cleared by exactly one **file-local** fixture at `test_agent_b_data_audit.py:85-91`, confirmed at `:87` (`._in_memory_df_cache.clear()`), `:88` (`._quote_memo.clear()`), `:89` (`._l1_sources.clear()`), `:91` (`cointegration_service._IN_MEMORY_COINT_CACHE.clear()`). Nothing clears them for the other test files.
- **Impact**: developer-facing. Tests can observe another test's cached vendor response — order-dependent results with no failing test named. Also: the inert `pytest.mark.unit` means the 13 explicitly-marked `unit` tests and 41 `api` tests are the *only* marked tests, which is why INF-3's marker picture looks the way it does.
- **Suggested fix**: move `pytestmark` into the test modules that should carry it (or replace it with an autouse fixture that applies marks), and promote the `test_agent_b_data_audit.py` cache reset into `conftest.py` as autouse. **Blast radius:** making the `unit` mark real changes marker-based selection — if `-m` selectors are added to CI later, they will suddenly deselect most of the suite. Do the mark move and the cache reset as two separate changes.

### INF-12 — `create_test_price_data` seeds from `hash(ticker)`, which is randomised per process
- **Class**: bug (test quality)
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `backend/tests/conftest.py:448`
- **Symptom**: every call to `create_test_price_data(ticker)` produces a different price series on every process run, so any test asserting an exact value derived from it is flaky-by-construction. The inline comment asserts the opposite of the behaviour.
- **Evidence**:
  ```python
  # backend/tests/conftest.py:448
      np.random.seed(hash(ticker) % 2**32)  # Seed based on ticker for consistency
  ```
- **Mechanism**: (1) `str.__hash__` is salted by `PYTHONHASHSEED`, which Python randomises **per process** by default; (2) the seed therefore differs on every run; (3) `np.random.randn(num_days)` at `:450` yields a different series each run. The comment says "for consistency"; the code guarantees the *opposite* of consistency.
- **Proof of outlier-ness** — every other seed in the file is an integer literal:
  ```
  conftest.py:42  np.random.seed(42)
  conftest.py:70  np.random.seed(42)
  conftest.py:85  np.random.seed(42)
  conftest.py:397 np.random.seed(42)
  conftest.py:448 np.random.seed(hash(ticker) % 2**32)   <-- the only non-literal
  ```
  *(Correction: the inventory said "the other five". There are **four** others; five total.)*
- **Impact**: developer-facing. Realised only by a test that asserts exact figures from this helper; none is named here, so the impact is derived from the construct, not from an observed failure.
- **Suggested fix**: seed from a stable digest of the ticker, e.g. `int(hashlib.sha256(ticker.encode()).hexdigest()[:8], 16)`. **Blast radius:** this **changes the generated data** for every caller, so any test currently pinning a value derived from the old (accidentally run-varying) series will change. That is a true-positive fix, not a regression — but land it with the affected assertions identified in the same change. Do not "fix" it by setting `PYTHONHASHSEED=0` globally in CI: that makes the suite depend on an environment variable it does not currently declare.

### INF-13 — 19 of 57 audit rules are never named in the gate; the file's own prose header miscounts its frozen set
- **Class**: maintainability
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `backend/tests/test_audit_rule_coverage.py` — `MUTATIONS` from `:115`, `KNOWN_UNCOVERED` `:872-936`, prose header `:848-871`, `KNOWN_COLLATERAL` `:948-961`, pass condition `:1234`
- **Symptom**: the file's name and docstring promise `57/57`. Nineteen of the 57 rules appear **nowhere** in the gate — never in an `expects` tuple, never in a comment. The measurement of "how many wrong numbers does this gate catch" is therefore taken over a rule subset that was never chosen as a subset; it is simply what the author happened to write down. The prose header additionally sums its own frozen set wrong.
- **Evidence** — the arithmetic, both sides counted from source:
  ```text
  context_audit.py rule inventory (by rule_id token, whole file):
      ENV-001 .. ENV-021   = 21 rules
      NUM-001 .. NUM-026   = 26 rules
      XS-001  .. XS-010    = 10 rules
      TOTAL                 = 57 rules          <-- the "57" is real and verified
  ```
  ```text
  Rules NAMED anywhere in test_audit_rule_coverage.py:
      ENV family : ENV-016, ENV-019, ENV-021 only        -> 21 - 3 = 18 never named
      XS  family : XS-001..007, XS-009, XS-010 (XS-008 absent) -> 10 - 9 = 1 never named
      18 + 1 = 19 of 57 never named
  ```
- **Mechanism**: (1) `Mutation.expects` defaults to `()` and `:100-103` documents that as *"a claim that no rule targets the class"* — so a class with no rule is a legitimate, non-failing entry; (2) of those, 29 land in `KNOWN_UNCOVERED`; (3) the pass condition at `:1234` `test_every_catalog_section_has_a_caught_mutation` computes `caught = {section for (section, _cls), fired in ledger.items() if fired}` — **per section, not per class** — so a section passes on a single firing mutation no matter how many of its classes go uncovered.
- **Counted, verified**: `KNOWN_UNCOVERED` (`:872-936`) contains **29** entries — counted line by line: `:874,875,876` (3) · `:897` (1) · `:899-903` (5) · `:905,906` (2) · `:908-913` (6) · `:917,919,923,926,928,929,930,931,932,933,934,935` (12) = **29**. `KNOWN_COLLATERAL` (`:948-961`) contains **3** — `:949`, `:959`, `:960`. Real catch rate **50 / 82 = 61%** of injected defects caught by the rule the author declared correct.
- **The arithmetic defect in the file itself**: the prose header at `:851-871` labels the six families `(3) (6) (5) (2) (4) (5)`, summing to **25**. The set it describes holds **29**. The per-family breakdown shows where the header drifted: family 2 is labelled `(6)` but holds 1 (seven were closed deliberately — see the note at `:877-896`); family 5 is labelled `(4)` but holds 6; family 6 is labelled `(5)` but holds 12. The header undercounts its own frozen set by **four**.
- **Impact**: developer-facing, and the failure direction is the reassuring one — the gate reports green while a third of injected defects are known uncovered, and the prose that a reviewer reads first is quantitatively wrong. The frozen sets *are* asserted in both directions (`:1324`, `:1337`), so an *improvement* cannot pass unnoticed. **The gap is scope, not rigour**, and that distinction must survive into the ledger.
- **Suggested fix**: (a) correct the `:848-871` header to the counted values, or better, compute it; (b) add `expects` entries naming the 19 uncovered rules so the file states what it is not measuring; (c) optionally tighten the pass condition from per-section to per-class. **Blast radius: (a) is comment-only and safe. (b) is documentation of scope, not a weakening of any assertion. (c) would make the gate red today and is a deliberate policy decision, not a cleanup** — it must not be done as a drive-by, and it must not be resolved by moving entries out of `KNOWN_UNCOVERED` to make the gate green. That would be exactly the anti-pattern this file exists to detect.

### INF-14 — The audit harness never runs against an export produced by the running application
- **Class**: risk
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `backend/tests/test_audit_rule_coverage.py:1063` and `:1085-1096`; absence across `.github/workflows/ci-cd.yml`
- **Symptom**: the harness proves the *rules* work on a document. Nothing anywhere proves the rules are pointed at the *right* document. A lost ORM write, or a statistic published as computed that was never computed, is invisible to this gate — because the document it measures against is a frozen JSON file, not the app's output.
- **Evidence**:
  ```python
  # backend/tests/test_audit_rule_coverage.py:1063  — where the document comes from
      return json.loads(BASE_EXPORT.read_text(encoding="utf-8"))
  ```
  ```python
  # :1081-1086
  def _fire(
      document: dict[str, Any],
  ) -> tuple[dict[str, list[str]], list[str], set[tuple[str, str]]]:
      """Every rule that fires on this document, keyed by rule id, plus rule errors."""
      export = ca.Export(doc=document, raw=json.dumps(document))
      findings, errors = ca.run_rules(export)
  ```
- **Proof of absence**: I read `.github/workflows/ci-cd.yml` in full (234 lines). It contains no reference to `context_audit`, `context_audit.py`, `Export(`, or any export-generation step. Control: `docker build` → 6 matches in the same file, proving the file was read and searched live.
- **Mechanism**: (1) the only document source is `BASE_EXPORT.read_text()`; (2) `_fire` constructs `ca.Export` from that in-memory dict, never from app output; (3) therefore any divergence between the app's real export and `v27.json` is, by construction, outside the gate.
- **The gap is easy to miss** because the harness's own docstring (`:3`) says *"`57/57` is a consistency signal, not a correctness one."* That sentence is accurate and load-bearing — the risk is a reader taking the gate as the second half of that sentence.
- **Impact**: no user-visible effect today; developer-facing. It bounds how much assurance INF-13's 61% figure can be given: 61% of injected defects, on a frozen document.
- **Suggested fix**: add a job (or a marked test) that drives the real export path and runs `ca.run_rules` over the result, asserting only that the run completes and that the findings are explainable. **Blast radius:** a live export is *not* deterministic — it will carry real findings on real data, so the test must assert shape, not emptiness, or it will be red on day one and get deleted. Do not fold this into the existing gate; it is a different claim.

### INF-15 — Deprecated and mutable GitHub Actions pinned in CI; the dependency cache guards the wrong directory
- **Class**: risk
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `.github/workflows/ci-cd.yml:36` (`actions/cache@v3`), `:77` (`bun-version: latest`), `:125` (`aquasecurity/trivy-action@master`), `:133` (`github/codeql-action/upload-sarif@v2`), `:187` (`amazon-ecr-login@v1`), and the cache/installer mismatch at `:38` vs `:32`/`:44`
- **Symptom**: the supply-chain posture of the pipeline rests on a mutable branch ref and on two retired action majors; and the one caching step caches a directory the build never reads, so every run re-downloads and re-links the entire scientific stack.
- **Evidence**:
  ```yaml
  # .github/workflows/ci-cd.yml:35-39
      - name: Cache dependencies
        uses: actions/cache@v3
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('**/pyproject.toml', '**/uv.lock') }}
  ```
  ```yaml
  # :124-125 and :132-133
      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@master
      - name: Upload Trivy scan results
        uses: github/codeql-action/upload-sarif@v2
  ```
  ```yaml
  # :30-33 — the installer is uv; the cache above is pip's
      - name: Install UV
        run: |
          curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Mechanism** — two independent chains: (1) `@master` resolves to whatever that branch points at **at run time**, so the scanner's code is not pinned by the repository; (2) `path: ~/.cache/pip` is read by nothing, because `uv sync` (`:44`) reads `~/.cache/uv`. Every run therefore pays the full install cost. `:44` (`uv sync --frozen --extra dev --group dev`) re-links ~25 pinned packages including the whole scientific stack (`scipy`, `cvxpy`, `quantlib`, `hmmlearn`, `arch`, `statsmodels`, `quantstats`).
- **Confidence**: VERIFIED
- *Confidence split, stated honestly:* the **versions are VERIFIED** - I opened `:36`, `:77`, `:125`, `:133`, `:187` and each matches. The **failure mode is not reproduced**: whether `codeql-action/upload-sarif@v2` hard-fails a current runner is a runtime fact this run did not observe, and `@master` is a standing risk rather than a demonstrated break. No external retirement dates are asserted here beyond what the ref strings themselves show.
- **Impact**: (1) `security` (`:118`) is one of the four `needs:` for `production-images` (`:165`) — a scanner outage blocks image publishing; (2) the cache miss is a direct, certain contributor to the 12-minute backend job wall.
- **Suggested fix**: pin Trivy to a released tag or a commit SHA; move the retired `upload-sarif` to `v3`; point the cache at `~/.cache/uv` (or `~/.local/share/uv`) and key it on `backend/uv.lock`. **Blast radius:** the `security` job's action versions must move together with the CodeQL major, and the cache path change alters the cache key — expect one cold run. Do not remove the `security` job to "fix" `production-images`; that would trade a supply-chain gate for a build speedup.

### INF-16 — `uv sync --frozen` cannot detect pyproject/lock drift
- **Class**: bug
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `.github/workflows/ci-cd.yml:44`; `backend/Dockerfile:15`
- **Symptom**: `--frozen` means "install exactly what the lockfile says, do not update it". `--locked` is the flag that **asserts** the lock matches the manifest. So a dependency added to `pyproject.toml` without a re-lock installs the *old* set, and the tests run against an environment nobody declared.
- **Evidence**:
  ```yaml
  # .github/workflows/ci-cd.yml:44
          uv sync --frozen --extra dev --group dev
  ```
  ```dockerfile
  # backend/Dockerfile:15
  RUN uv sync --frozen --no-dev --no-install-project
  ```
- **Mechanism**: (1) `pyproject.toml` gains a dependency; (2) `uv.lock` is unchanged; (3) `--frozen` installs the lock's set without complaint; (4) CI and the image both ship a dependency set that differs from the manifest. This is precisely the failure mode `AGENTS.md` already documents as *"After editing either, resync with `uv sync --extra dev --group dev` or tools silently vanish"* — reproduced at the CI and image layers instead of the local one.
- **Current state — verified in sync, so the finding is latent, not active**: `backend/uv.lock:346` `dev = [{ name = "ruff", specifier = ">=0.16.6" }]`; `:301` `{ name = "ruff" }` in the resolved group; `:3228-3229` `name = "ruff"` / `version = "0.16.8"`; `:324` `{ name = "pytest", marker = "extra == 'dev'", specifier = "==8.3.4" }`; and **10** `extra == 'dev'` markers in the lock. Both dependency tables — `[project.optional-dependencies] dev` and `[dependency-groups] dev` — are correctly represented.
- **Impact**: developer-facing. The gate that would catch a lock/manifest mismatch is disabled in the two places it matters most. Because the tables are currently in sync, nothing is wrong today.
- **Suggested fix**: use `--locked` at `ci-cd.yml:44` so drift fails the build, and in `Dockerfile:15` so a stale image cannot be produced. **Blast radius:** switching to `--locked` will turn the build red on the next lock/manifest mismatch — which is the intent. Note the backend `pyproject.toml` deliberately carries **two** tool tables (`[project.optional-dependencies] dev` for pytest, `[dependency-groups] dev` for ruff) and CI must keep both flags (`--extra dev --group dev`); do not "simplify" to one.

### INF-17 — Dev-only tooling shipped as runtime dependencies
- **Class**: maintainability
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `frontend/package.json:16-44` (`dependencies`), `:45+` (`devDependencies`); `backend/pyproject.toml:35`, `:50`, `:84`
- **Symptom**: test tooling ships to production images and is installed into the runtime venv, growing every artefact and every `uv sync` — while `addopts` leaves a parallelism package installed and unused.
- **Evidence** — test tooling inside frontend `dependencies`:
  ```json
  // frontend/package.json — inside "dependencies" (opened :16, closed :44)
  25:    "@testing-library/jest-dom": "^7.0.1",
  26:    "@testing-library/react": "^16.3.3",
  27:    "@types/file-saver": "^2.0.7",
  36:    "papaparse": "^5.7.0",
  41:    "vitest": "^5.0.1",
  45:  "devDependencies": {          <-- the boundary these five are on the wrong side of
  ```
- **Backend side, with controls**:
  ```toml
  # backend/pyproject.toml
  35:    "ipython>=9.6.0",     # inside [project] dependencies (:11-42)
  50:    "pytest-xdist>=3.6.1", # inside [project.optional-dependencies] dev (:44-56)
  84:  addopts = "-v --tb=short --cov=app --cov-report=html --cov-report=term-missing --cov-fail-under=80"
  ```
  - `ipython`: `Select-String 'import IPython'` → **ZERO MATCHES**; `'import ipython'` → **ZERO MATCHES**; bare token `IPython` → **ZERO MATCHES**; bare token `ipython` → **ZERO MATCHES** across every `backend/**/*.py` outside `.venv`. Control on the identical file set: `'import pandas as pd'` → 1 match at `conftest.py:10`, and `'responses'` → 10+ matches in app code. **Zero imports.**
  - `pytest-xdist` is installed but `addopts` (`:84`) never passes `-n`, so **the suite runs serially**. This is a direct, certain contributor to the backend job's wall time.
  - `babel-plugin-react-compiler` is pinned as a peer while `next.config.ts:5` sets `reactCompiler: false`.
- **Mechanism**: (1) a package is placed in `dependencies` / `[project] dependencies` and is therefore installed into every image and every `uv sync`; (2) the runtime never imports it, so the cost is pure; (3) `pytest-xdist` is installed but `addopts` never passes `-n`, so the parallelism benefit that would have paid for its presence is never collected either.
- **Note on `@types/file-saver`**: it is in `dependencies`, not `devDependencies` — a type-only package that has no runtime role at all, which makes the misplacement unambiguous rather than debatable.
- **Impact**: no user-visible effect. Developer-facing: larger images, slower installs, and a dependency surface that does not match what the code imports. `papaparse` is the one entry where the classification is arguable — it may be imported at runtime by a component, so it should be checked before moving.
- **Suggested fix**: move the four unambiguous test packages (`vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `@types/file-saver`) to `devDependencies`; drop `ipython`; either configure `-n auto` in `addopts` or drop `pytest-xdist`. **Blast radius: this is the one item here that can change what CI installs and therefore what is tested** — dropping `xdist` is safe (nothing uses it), but *enabling* `-n auto` would serialise-independent tests into parallel workers and can surface order dependencies (see INF-11's shared class-level caches). Do both halves separately, and do not touch the 80% coverage flag while doing it.

### INF-18 — Root `.gitignore` omits `.ruff_cache/`; bare `*.db` protection lives one file deep
- **Class**: risk
- **Severity**: RISK
- **Confidence**: DERIVED
- **Location**: `.gitignore:76-78`; `backend/.gitignore:13-14`; `.ruff_cache/` at the repo root
- **Symptom**: the root ignore file goes to real length keeping live holdings and cost basis out of git, yet the rule protecting the primary store of exactly that data is three directories down — so a `daisy.db` created anywhere else in the tree is unprotected. Separately, `.ruff_cache/` exists at the root and is not ignored.
- **Evidence**:
  ```gitignore
  # .gitignore:76-78  (file is 99 lines)
  *.db-wal
  *.db-shm
  *.sqlite
  ```
  ```gitignore
  # backend/.gitignore:12-14
  # Local databases
  data/*.db
  *.db
  ```
- **Proof of absence**: `Select-String -Path .gitignore -Pattern '*.db' -SimpleMatch` → **2 matches, `:76` and `:77`, and both are the `-wal`/`-shm` variants.** There is no bare `*.db` line. Control: the same search on `backend/.gitignore` returns `:13` `data/*.db` and `:14` `*.db` — a live search that matches. Separately, `'ruff_cache'` in the root `.gitignore` → **ZERO MATCHES**, with `'coverage'`/`.pytest_cache` present at `:71`/`:73` as controls.
- **Mechanism**: (1) the root `.gitignore` was written for `backend/`, so its database rules are scoped to WAL/SHM sidecars; (2) a `.db` file created anywhere else in the tree — a scratch dir, a new service, a tool run from the root — matches no rule; (3) `.ruff_cache/` sits at the root with no rule at all, so `git add -A` stages it.
- **Runtime confirmation**: `Test-Path .ruff_cache` → **True** (the directory exists), and `git check-ignore -v .ruff_cache` → **no output**, i.e. no rule matches it: **not ignored**.
- *Why DERIVED (security half):* because the impact depends on where a `.db` file can be created, and **no tracked secret or database file was found in the index**. That is a statement about ignore *rules*, not a clean bill for the index — I did not enumerate the index.
- **Impact**: developer-facing. `.ruff_cache/` would appear as untracked noise, and an `add -A` from the root would commit it. The `*.db` gap is a latent exposure on a repository whose own comments treat live portfolio data as sensitive.
- **Suggested fix**: add bare `*.db` and `.ruff_cache/` to the root `.gitignore`. **Blast radius:** adding a broad `*.db` at the root can untrack a file someone deliberately committed; check the index for `*.db` first. This is additive-only — it cannot weaken any gate.

### INF-19 — `scripts/deploy.sh` is never invoked, and its default `PUBLIC_BASE_URL` probes the wrong port
- **Class**: risk
- **Severity**: RISK
- **Confidence**: DERIFIED
- **Location**: `scripts/deploy.sh:22`, `:51-52`, `:175-186`; `docker-compose.prod.yml:62`
- **Symptom**: the only deployment script in the repository is not called by any automated path, and if a human runs it unmodified its readiness probe polls a port nothing is bound to — so it burns its full 60-second window against a dead address and reports failure.
- **Evidence**:
  ```bash
  # scripts/deploy.sh:22
  PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-http://127.0.0.1}"     # -> port 80
  ```
  ```bash
  # scripts/deploy.sh:177-182
      local backend_url="${PUBLIC_BASE_URL%/}/health"
      local frontend_url="$PUBLIC_BASE_URL"
      local attempt ready=false
      for attempt in $(seq 1 30); do
          if curl -fsS --max-time 5 "$backend_url" >/dev/null 2>&1 \
              && curl -fsS --max-time 5 "$frontend_url" >/dev/null 2>&1; then
  ```
  ```yaml
  # docker-compose.prod.yml:62   — the frontend is published on :3000
        - "127.0.0.1:3000:3000"
  ```
- **Proof of absence**: `Select-String 'deploy.sh' -SimpleMatch` over `.github/workflows/ci-cd.yml` → **ZERO MATCHES**. Controls on the same file: `'docker build'` → **6 matches**; `docker-compose.prod.yml` → referenced at `:20`. The workflow is 234 lines and I read all of it. The `production-images` job (`:163-207`) builds and pushes to ECR and **deploys nothing** — it contains no `deploy.sh`, no `ssh`, no compose-up step.
- **Mechanism**: (1) `PUBLIC_BASE_URL` defaults to `http://127.0.0.1`, which is port 80; (2) the prod compose publishes the frontend on `127.0.0.1:3000`, so nothing answers on 80; (3) `health_check` polls both URLs 30 times at 2-second intervals and never becomes ready, so the script fails after burning its full window.
- **The irony, verified**: the script is the most careful artefact in the deployment surface. `deploy.sh:51-52` refuses a mutable tag outright —
  ```bash
  if [[ -z "$value" || "$value" == *:latest ]]; then
      log_error "$name must be a non-empty, non-latest tag or digest."
  ```
  and `:5-6` documents `BACKEND_IMAGE` / `FRONTEND_IMAGE` as "non-latest image tag or digest built by CI". That discipline is exercised by nothing, while `production-images` declares `environment: production` and `url: https://daisy-risk-engine.com` (`ci-cd.yml:167-169`) for a job that pushes images and stops.
- *Why DERIVED (wrong-port half):* it follows from `:22` defaulting to port 80 while `:62` publishes 3000, which is solid — but the inventory's stronger framing ("never invoked") is verified while the *runtime* consequence for any operator is not observed here.
- **Impact**: developer/operator-facing. No user-visible effect. The risk is the false signal: a green `production-images` job with a `production` environment and a live URL attached reads as "deployed" when it means "pushed to a registry".
- **Suggested fix**: default `PUBLIC_BASE_URL` to `http://127.0.0.1:3000`; then either wire `deploy.sh` into a job or remove the `environment:`/`url:` block from `production-images` so it stops implying a rollout. **Blast radius:** the second half is a **semantic** change to what the pipeline claims to do — it will change how the Slack notification at `:209-219` is read by humans. Do not delete `deploy.sh`; the refusal logic at `:51-52` is the correct pattern and is worth keeping as the reference implementation.

### INF-20 — `filterwarnings` ignores only `UserWarning`/`DeprecationWarning`, with no `error::` entry
- **Class**: maintainability
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `backend/pyproject.toml:95-98`
- **Symptom**: `ComplexWarning` and `SAWarning` both subclass `RuntimeWarning` and pass through unfiltered. With no `error::` entry anywhere, a genuine `RuntimeWarning` — an invalid value in a sqrt, a NumPy cast producing NaN — passes silently. A suite that cannot fail on this cannot catch the NaN class, which is this project's dominant numerical failure mode.
- **Evidence**:
  ```toml
  # backend/pyproject.toml:95-98
  filterwarnings = [
      "ignore::UserWarning",
      "ignore::DeprecationWarning",
  ]
  ```
- **Mechanism**: (1) the filter list contains only two `ignore::` entries and **no** `error::` entry; (2) warnings outside that list are emitted but never elevated; (3) a numerically-invalid operation that warns rather than raises leaves the suite green with a NaN in a payload.
- **Proof of absence**: the block at `:95-98` is the entire `filterwarnings` list — it is bounded by `[tool.coverage.run]` at `:100`, so nothing follows it. Control: `pytest.ini_options` demonstrably contains other keys in the same table (`:83` `testpaths`, `:84` `addopts`, `:85-86` asyncio keys, `:87` `markers`), so the table was read in full.
- **Impact**: developer-facing, no user-visible effect — but it is a **detection** gap, not a style gap: this is the mechanism by which a wrong number reaches the user unflagged. It is the same class as INF-14 (nothing would catch an uncomputed statistic published as computed).
- **Suggested fix**: add `"error::RuntimeWarning"` (or scope it to the two named libraries) as a separate, staged change. **Blast radius: this will turn the suite red** wherever a RuntimeWarning is currently tolerated — that is the intended discovery, but it must land as its own commit with the resulting failures triaged, not folded into another change. Do **not** fix it by extending the `ignore::` list.

### INF-21 — No `concurrency` group; CI burns runners on superseded commits
- **Class**: optimisation
- **Severity**: NIT
- **Confidence**: VERIFIED
- **Location**: `.github/workflows/ci-cd.yml:1-12` (absence of `concurrency`)
- **Symptom**: a push that supersedes an in-flight run does not cancel it. Five of the six jobs continue to completion — including the 12-minute backend job with its broken dependency cache (INF-15) — consuming runner minutes to produce a result nobody will read.
- **Evidence**:
  ```yaml
  # .github/workflows/ci-cd.yml:1-12  — no `concurrency` key anywhere in the file
  name: CI/CD Pipeline

  on:
    push:
      branches: [ main, develop ]
    pull_request:
      branches: [ main ]

  env:
    REGISTRY: ghcr.io
    IMAGE_NAME: ${{ github.repository }}
  ```
- **Proof of absence**: `Select-String 'concurrency' -SimpleMatch` over `ci-cd.yml` → **ZERO MATCHES**. Control on the same file: `'needs:'` → **3 matches** (`:143`, `:165`, `:224`), so the search is live.
- **Mechanism**: (1) no `concurrency` key exists, so GitHub has no instruction to cancel superseded runs; (2) a second push starts a second full matrix while the first is still running; (3) both consume runners to completion, including the 12-minute `backend` job whose dependency cache is misdirected (INF-15) — cost spent on results nobody reads.
- **Proof that this is the *only* place a group could live**: `Get-ChildItem 'C:\es\coding\finengine\.github' -Force -Recurse` returns exactly **two** entries — `.github\workflows\` and `.github\workflows\ci-cd.yml` (7,264 bytes). **There is exactly one workflow file in this repository**, and it declares no concurrency group. (Re-confirmed with `-Force`, per the plan's warning: `Get-ChildItem -Recurse` without `-Force` is what previously lost this directory.)
- **Impact**: developer-facing cost only; no effect on any gate's verdict.
- **Suggested fix**: add a `concurrency:` group keyed on `${{ github.workflow }}-${{ github.ref }}` with `cancel-in-progress: true`. **Blast radius: none to correctness — but `cancel-in-progress: true` on a branch that pushes tags or on `production-images` would cancel an in-flight image publish.** Scope the group per-job or exclude the publish job; do not add a blanket workflow-level cancel without checking `:163-207`.

### INF-22 — Two sources of truth for host policy; one is invisible in every config file
- **Class**: risk
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `docker-compose.prod.yml:17`; `backend/main.py:102-108`
- **Symptom**: prod compose exposes `ALLOWED_ORIGINS` as an operator-settable variable, but the *host* allowlist is hardcoded in Python and ignores it. An operator who sets `ALLOWED_ORIGINS` correctly gets correct CORS and a **403 from `TrustedHostMiddleware`** — with no error message pointing at the cause, and no configuration file that can fix it.
- **Evidence**:
  ```yaml
  # docker-compose.prod.yml:17
        ALLOWED_ORIGINS: ${ALLOWED_ORIGINS:-http://localhost:3000}
  ```
  ```python
  # backend/main.py:102-108
  if settings.environment == "production":
      # Security middleware for production
      app.add_middleware(_HealthExemptHTTPSRedirectMiddleware)
      app.add_middleware(
          TrustedHostMiddleware,
          allowed_hosts=["daisy-risk-engine.com", "*.daisy-risk-engine.com", "localhost", "127.0.0.1"]
      )
  ```
- **Mechanism**: (1) an operator sets `ALLOWED_ORIGINS=https://daisy-risk-engine.com`; (2) `CORSMiddleware` (`:111-115`) reads `settings.allowed_origins` and honours it; (3) `TrustedHostMiddleware` at `:105-107` compares `Host` against a **literal list** that ignores the environment entirely; (4) a request for any other hostname is rejected 403 before CORS is ever consulted. The two policies are configured by different mechanisms at the same layer, and only one of them is discoverable.
- **Scope correction, verified**: the middleware is added only under `if settings.environment == "production"` (`:102`), so development is unaffected. `docker-compose.yml:14` sets `ENVIRONMENT: development`; `docker-compose.prod.yml:15` sets `production`. The exposure is production-only — which is the correct place for it to be, and why this is RISK rather than DEFECT.
- **Credit where due**: the backend Dockerfile runs non-root (`USER appuser`, `backend/Dockerfile:46`) and the frontend does too (`USER nextjs`, `frontend/Dockerfile:49`); both compose files bind host ports to `127.0.0.1` (`docker-compose.prod.yml:12`, `:62`); no secret is hardcoded in either compose file.
- **Impact**: an operator following the documented interface exactly gets an unexplained 403 in production. No current user is affected, because the hardcoded list happens to match the domain in `production-images`' `url:` (`ci-cd.yml:169`).
- **Suggested fix**: read `allowed_hosts` from settings (an `ALLOWED_HOSTS` env var) with the current literal as the default, so the two policies have one source. **Blast radius:** widening a host allowlist is a security-relevant change — the default must stay exactly as narrow as it is today, and the change should not also touch CORS. Do not simply delete the middleware.

---

## CI matrix

**One workflow. Six jobs — not five.** `Get-ChildItem 'C:\es\coding\finengine\.github' -Force -Recurse` returns exactly two entries: the `workflows\` directory and `ci-cd.yml` (7,264 bytes, 234 lines). There is no second workflow file anywhere, so the entire automated gate for this repository is the matrix below.

| # | Job | `needs:` | Steps that matter | Can go red on |
|---|---|---|---|---|
| 1 | `backend` (`:15`) | — | checkout@v4 → setup-python@v4 3.12 → `curl … uv/install.sh` (unversioned) → cache `~/.cache/pip` → `uv sync --frozen --extra dev --group dev` → `ruff check --no-cache .` → `pytest … tests/ --cov-fail-under=80` → `docker build -f backend/Dockerfile` → push ghcr (main only) | **INF-3** (localhost smoke test collected), **INF-4** (`pytest.fail` on missing `v27.json`), `--cov-fail-under=80`, plus any of 2254 tests |
| 2 | `frontend` (`:67`) | — | checkout@v4 → setup-bun@v2 `bun-version: latest` → `bun install --frozen-lockfile` → `tsc --noEmit` → `eslint src/` → `vitest run` → `bun run build` → `docker build -f frontend/Dockerfile` → push ghcr (main only) | **INF-1** and **INF-2**, both at the `docker build` step (`:109`) |
| 3 | `security` (`:118`) | — | `trivy-action@master` → `codeql-action/upload-sarif@v2` → `dependency-review-action@v3` | **INF-15** (retired major / mutable ref) — not reproduced |
| 4 | `integration` (`:141`) | `[backend, frontend]` | checkout → buildx → `docker compose up -d --build --wait` → `python backend/tests/integration/test_compose_services.py` | **INF-5** (`--wait` never satisfied), plus INF-1/INF-2 via `--build` |
| 5 | `production-images` (`:163`) | `[backend, frontend, security, integration]` | gated on `github.ref == 'refs/heads/main'`; AWS creds → ECR login → build+push **both** images by `github.sha` → Slack | only INF-1..INF-5, all upstream; **deploys nothing** (INF-19) |
| 6 | `notify-failure` (`:222`) | `[production-images]` | `if: failure()` → Slack `#alerts` | never blocks; **this is the job that actually runs on every push to `main`** |

**What can block a merge.** The workflow triggers on `push: [main, develop]` and `pull_request: [main]` (`:4-7`). Branch-protection settings are not in the repository, so what *technically* blocks a merge is unobservable from here — but only jobs 1 and 2 carry real gates (tests, typecheck, lint, coverage), and both are structurally red. Jobs 3–6 are downstream or advisory. The practical answer: **no green signal has ever been produced that a human could require.**

**CI has never been green, and the reason is structural rather than incidental.** Job 1 cannot pass because `pytest tests/` (`ci-cd.yml:54`, with `testpaths = ["tests"]` at `pyproject.toml:83`) collects `tests/integration/test_compose_services.py`, which calls `urlopen("http://127.0.0.1:8000/health")` against nothing — and, independently, because the 57-rule audit gate is bound to one developer's `%TEMP%` and calls `pytest.fail`. Job 2 cannot pass because its `docker build` copies a `.next/standalone` directory that Next never emits, on a Node base below Next's own declared engine floor. Every downstream job is therefore skipped, and `notify-failure` fires on every push to `main`.

The consequence that matters: **there is no automated evidence that any image has ever been built or published** — neither ghcr (pushed from inside the two red jobs) nor ECR (job 5, never reached). The repository's protection here is not a green pipeline but its *permanence in red*: a permanently-failing pipeline is easy to ignore, which is why this reads as "no CI" rather than "CI is broken".

**What does pass.** Inside job 2, `tsc --noEmit` (`:85`), `eslint src/` (`:95`) and `next build` (`:103`) are real gates and are structurally sound — `eslint` exits on errors alone because `package.json:9` defines `"lint": "eslint"` with no `--max-warnings`, which is what the comment at `:87-92` claims and what I confirmed. Job 2's failure is confined to its last step.

**What nothing would catch.** No job runs `context_audit` against an export produced by the running app (**INF-14**); no job binds a network-denying fixture (**see Hermeticity**); and the audit gate itself measures only a frozen document over 50 of 82 injected defects (**INF-13**). A lost ORM write, or a statistic published as computed that was never computed, passes every gate in this file.

---

## Hermeticity

**The vendor seam is better mocked than expected — verified, and it changes what can be concluded.**

`backend/tests/test_bugfix_core_services.py:266-302` contains a spy that is specifically designed to fail if the network is touched:

```python
# backend/tests/test_bugfix_core_services.py:278-282
        bf_calls = []

        def _bf_spy(symbol):
            bf_calls.append(symbol)
            raise AssertionError("real bfinance.Ticker must not be constructed")
```

under the test name `test_validate_ticker_identity_skips_real_bfinance` (`:266`), whose docstring (`:269-275`) states the intent explicitly: *"default source order puts bfinance first, so without the skip this unit test would open a live network call via bfinance.Ticker."* Nine further test files patch `yfinance.Ticker` / `bfinance.*` at the module level. **The vendor boundary is guarded, not merely mocked.**

**Therefore: the 5 → 26 failure swing reported elsewhere in this audit has an UNIDENTIFIED source. I am not attributing it to the vendor seam, to network access, or to any other cause — I did not prove one.** The swing may equally be a collection-count change, a fixture-ordering effect, or the `hash()`-seeded data in INF-12 producing values that no longer match; none of those is established here. It must stay unattributed until someone runs the suite, which this audit was not permitted to do.

**The four real non-hermetic inputs, in impact order:**

1. **`backend/tests/test_audit_rule_coverage.py:77` — machine-bound, outside the repo, and *not a network issue at all*.** `BASE_EXPORT = Path(r"C:\Users\Sayanti\AppData\Local\Temp\opencode\v27.json")`. It is `pytest.fail` (`:1057`), not `skip`, so on any other machine the gate is red rather than silently absent. Listed first because it is the only one that is currently, deterministically, breaking the build — the other three are latent. Its non-hermeticity is *environmental*, not *network*, and conflating the two would misdirect the fix.
2. **`backend/tests/conftest.py:223-230` — `async_client` can reach the real `daisy.db` (destructive).** It overrides one DI dependency and rebinds neither `engine` nor `SessionLocal` nor the `ws_mod.SessionLocal` alias, while the sibling `client` fixture rebinds all three at `:250-256` and documents the hazard at `:235-244`. Second because the failure mode is *data loss in the developer's real portfolio*, and `backend/data/daisy.db` (with `-wal`/`-shm`) is present on disk. Partially mitigated: `ASGITransport` runs without lifespan, so the `init_db()` self-heal does not fire on this path.
3. **Class-level service caches cleared in one file only.** `DataService._quote_memo`, `._in_memory_df_cache` and `._l1_sources` are class-body dicts (`backend/app/services/data_service.py:301`, `:298`, `:303`), so they are session-global. The only reset in the suite is the file-local fixture at `backend/tests/test_agent_b_data_audit.py:85-91`. Third because the exposure is order-dependent results rather than data loss.
4. **`backend/tests/conftest.py:448` — `hash()` seeding re-rolls every process.** `np.random.seed(hash(ticker) % 2**32)`. Fourth because it produces *deterministic-looking but non-reproducing* data, the most seductive failure mode of the four: a test can pass on the run that was recorded and fail on the next.

**No framework-level mitigation exists at any layer.**

- `responses==0.25.0` is declared at `backend/pyproject.toml:55` and **never imported**. Proof: `Select-String 'import responses' -SimpleMatch` across every `backend/**/*.py` outside `.venv` → **ZERO MATCHES**. Controls on the identical file set: `'import pandas as pd'` → 1 match (`conftest.py:10`); the bare token `'responses'` → 10+ matches in app code (`main.py:13` `from fastapi.responses import JSONResponse`, `data.py:638` `stock_responses`, `portfolio.py:931`, …). The search is live; the library is unused.
- **No `pytest-socket`**, no `pytest-vcr`, no cassette layer, no autouse network guard. Nothing in `conftest.py` (497 lines, read in the cited windows) denies socket access.
- The `integration` marker is declared (`pyproject.toml:89`) and **used by no test** — 0 occurrences. Controls on the same enumeration: `pytest.mark.api` → 41, `pytest.mark.unit` → 13, `pytest.mark.websocket` → 1, and the token `pytestmark` → 1 (`conftest.py:431`). The declared-but-unused set is `integration`, `database`, `slow`.

**Recommended mechanism — shape only, per the plan; ordering is the useful part.**

1. **An autouse session fixture that makes `socket.socket.connect` raise unless `ALLOW_NETWORK=1`.** Roughly 20 lines. Do this **first**: it converts every silent network dependency into a named, attributable failure, and — given that the vendor seam is already guarded by the `bfinance.Ticker` spy — it is the only place remaining where a silent network call could still hide. It also gives the unidentified 5→26 swing somewhere to land when it is finally reproduced.
2. **Two autouse vendor fixtures defaulting to raise**, replacing the per-file `patch()` sites (76 sites across 11 files per the inventory; the one I verified is `test_bugfix_core_services.py:266-302`). This *generalises an existing good pattern* rather than inventing one — the repository has already written the right thing once.
3. **`vcrpy` cassettes for the residue**, scrubbed of anything resembling holdings.
4. **Vendorise `v27.json`** into `backend/tests/fixtures/`, **sanitised** — `backend/tests/test_audit_rule_coverage.py` and `.gitignore:81-85` both make clear the raw export contains live holdings, quantities, cost basis and P&L and must not be committed.
5. **An autouse class-level cache reset in `conftest.py`**, promoting `test_agent_b_data_audit.py:85-91` to a suite-wide guarantee.

Note the dependency: step 5 should land **before** any step that introduces parallelism (`pytest-xdist` is installed at `pyproject.toml:50` but never invoked), because parallel workers make shared class-level caches a correctness problem rather than an ordering nuisance.

---

## Doc / config drift

Both sides cited, every row opened by me.

| # | Documented claim | Where | What the code actually says | Where | Status |
|---|---|---|---|---|---|
| 1 | "**Backend Test Suite**: **249 / 249 Passed** (0 failures, 100% green) with **85% total line coverage**" | `RELEASE_NOTES.md:181` | CI cannot pass at all (INF-3, INF-4); the gate is `--cov-fail-under=80`, not 85 | `ci-cd.yml:54`, `pyproject.toml:84` | **CONFIRMED** (also internally inconsistent — 85% claimed against an 80% gate) |
| 2 | "**Frontend Test Suite**: **60 / 60 Passed** … across unit and component test suites" | `RELEASE_NOTES.md:182` | **50 test files** under `frontend/src` | counted with `Get-ChildItem -Recurse -Force -Include *.test.ts,*.test.tsx,*.spec.ts,*.spec.tsx` | File count **VERIFIED (50)**; the "537 tests" case count is **DERIVED** — counting cases requires running vitest, which is forbidden here |
| 3 | "TypeScript 5.7+" | `CONTEXT.md:**25**` — **not `:24`**; line 24 is the *Backend* row | `"typescript": "6.0.3"` | `frontend/package.json` | **CONFIRMED, citation corrected.** The inventory's `:24` is off by one; the drift itself is real |
| 4 | Frontend served on "`http://localhost:3000` (Dev) / `:3001` (Verify)" | `CONTEXT.md:25` | `:3001` appears **nowhere else in the repository**; both compose files publish 3000 | control: `Select-String '3001'` over `CONTEXT.md` → 1 match, that line. `docker-compose.yml:48`, `docker-compose.prod.yml:62` | **CONFIRMED** |
| 5 | "uv run uvicorn main:app **--host 0.0.0.0** --port 8000 --reload" | `CONTEXT.md:237` | "Localhost-only by design (no auth — do not expose past `127.0.0.1`)" | `README.md:13` | **CONFIRMED** — the two documents give directly opposite binding instructions, and one of them is a security instruction |
| 6 | "`docker compose up  # backend :8000, frontend :3000 (+ optional redis/nginx)`" | `README.md:55` | compose defines **exactly two services**: `backend`, `frontend` | `docker-compose.yml:3-67`, `:69-71` | **CONFIRMED** — no `redis`, no `nginx`, no profiles |
| 7 | "Single-context: root `CONTEXT.md` + `docs/adr/`" | `AGENTS.md:20` | `docs/` contains exactly two subdirectories — `agents` and `research`. `Test-Path docs\adr` → **False** | `Get-ChildItem docs -Force -Directory` | **CONFIRMED** — the agent-facing instructions point at a directory that does not exist |
| 8 | "`uv sync --extra dev` now completes cleanly on Windows" / "modernized with `uv sync --extra dev`" | `RELEASE_NOTES.md:74`, `:184` | omits `--group dev`, which is where **ruff** lives; CI uses **both** flags | `backend/pyproject.toml:65-68` (ruff in `[dependency-groups] dev`), `ci-cd.yml:44` (`--extra dev --group dev`), `.githooks` pre-commit runs `ruff` | **CONFIRMED** — following the release notes verbatim leaves ruff uninstalled and breaks the pre-commit hook, exactly as `AGENTS.md` warns |
| 9 | "The tree currently stands at 0 errors / **~271 warnings**, and that warning backlog is not clearable in one commit" | `ci-cd.yml:89` | the inventory reports 223 | — | **NOT VERIFIABLE.** The comment is a *rationale* for the errors-only lint gate. Counting warnings requires running `eslint`, which is forbidden. The claim's substance (**the gate is errors-only by design, and that is deliberate**) is **CONFIRMED** from `package.json:9` `"lint": "eslint"` and the `:87-92` comment block |
| 10 | Three different coverage thresholds — 80 / 85 / 62 | `TEST_INFRA.md`, `RELEASE_NOTES.md` | **80** in `TEST_INFRA.md:24` ("F14 · Backend 80%+ Test Coverage Gate") and **85** in `RELEASE_NOTES.md:181` | both opened | **PARTIALLY CONFIRMED.** Two of the three figures are verified and genuinely disagree. **The third figure, 62%, was not found** in `TEST_INFRA.md` — my `%` search there returned only `:24` (the 80% gate) and an unrelated 99% VaR/ES figure. The "three numbers" claim is **not reproduced** |

**The pattern across rows 3, 5, 6, 7 and 8 is worth naming for the assembler.** These are not stale numbers — they are **instructions that a reader will follow and that the code contradicts**, in four cases (5, 6, 7, 8) pointing at infrastructure that does not exist: a domain-doc directory, a redis/nginx profile, a port nobody binds, a `--group dev` flag that carries the linter the pre-commit hook needs. A drift table of prose figures understates the problem; the majority of these are **actionable falsehoods in the onboarding path**, which is why they belong in the ledger as RISK rows rather than as NITs.

**One thing that is NOT drift, and should not be recorded as such:** `AGENTS.md`'s description of the two-tool-table layout (`[project.optional-dependencies] dev` for pytest, `[dependency-groups] dev` for ruff) is **accurate** — I verified both tables exist at `pyproject.toml:44-56` and `:65-68` and both are correctly represented in `uv.lock` (`:324` `extra == 'dev'`, `:346` the group). It is `RELEASE_NOTES.md:74` that is wrong, not `AGENTS.md`.

---

## Rejected on re-verification

Six sub-claims from `inventory-a2fe-a3infra.md` did not survive. The parent findings all hold and are emitted above; these are corrections to their supporting evidence.

1. **INF-3's control search is false.** The inventory cited `Select-String → 0 matches, control pytest.mark.slow → 2 matches`. I ran it: **`pytest.mark.slow` → 0 matches.** The control does not reproduce, which means the original absence claim was not properly evidenced. Re-derived with a *working* control set (`pytest.mark.api` → 41, `pytest.mark.unit` → 13, `pytest.mark.websocket` → 1, `pytestmark` → 1): **three of the six declared markers are unused** (`integration`, `database`, `slow`). The finding is **stronger** than reported — it is systemic, not a single stray — but the stated control was wrong.

2. **INF-9's systemic count is wrong by ~4×.** "80+ matches across 15+ files" → actual **`is not None`: 311 occurrences across 77 files** in `backend/tests`. The per-file figure (24 in `test_coverage_direct_unit_routes.py`) is exactly right.

3. **INF-9's stated mechanism is wrong in detail.** "Dependencies are unconfigured `AsyncMock()`s, so `mock_ds.get_ohlcv()` returns a `MagicMock`" — `mock_ds` **is** configured, at `:70-72` (`Mock()` with `fetch_historical_data` and `fetch_quote` as `AsyncMock`s). The real weakness is different and stronger: `assert <route_return> is not None` is unfalsifiable **by contract**, because a FastAPI handler returns a dict or raises and has no `None` path — independent of how well its dependencies are configured. The loose mock is `mock_db = AsyncMock()` at `:101`.

4. **INF-7's stated mitigation does not exist.** "CI uses a single-fork pool so the leak is hidden." There is **no** pool configuration anywhere: `vitest.config.mts` has zero matches for `pool`, `threads`, `singleThread`, `fileParallelism`, `isolate` and `maxWorkers`, and `package.json:12` defines `"test:run": "vitest run"` with no flags. Vitest's default pool is parallel-per-file, so the cited mitigation is not merely unsupported — if anything the configuration makes leakage *more* likely, and the only real mitigation is vitest's default `isolate`. I have removed the claim rather than restate it.

5. **Doc-drift row 3 is off by one line.** "TypeScript 5.7+" is at **`CONTEXT.md:25`**, not `:24` — line 24 is the Backend row of the same table. The drift is real; the citation is not. Per **COR-7** I treated every inventory *table* cell as unverified, and this one was.

6. **Doc-drift row 10 does not reproduce.** "Three different coverage numbers (80/85/62%)" — 80 (`TEST_INFRA.md:24`) and 85 (`RELEASE_NOTES.md:181`) are both confirmed and do disagree. **62% was not found.** Emitted as a two-way disagreement, not a three-way.

**Two further claims I could not settle, and did not emit as findings:**

- **`RELEASE_NOTES.md:181`'s "5 failed / 2254 passed" baseline.** This is the anchor of row 1 and of the **unidentified 5→26 swing**. It requires running `pytest` (~12 min, network) — forbidden. The drift is proven from the *documented* side alone (`249/249 passed` is contradicted by a structurally red pipeline, and by its own `85%`-vs-`--cov-fail-under=80` inconsistency), but the corrected figure is inherited, not measured.
- **`RELEASE_NOTES.md:182`'s "537 tests".** I verified the **50 test files** by enumeration. Counting individual test *cases* requires running vitest — forbidden. Marked DERIVED.

**One finding was upgraded rather than rejected.** **INF-5** (relative SQLite path) was disputed upstream; the orchestrator's parenthetical `url.split('///',1)[1] -> '/app/backend/data/daisy.db' <- correct` is a true statement about **`split`**, but `backend/Dockerfile:52`, `docker-compose.yml:30` and `docker-compose.prod.yml:44` all call **`rsplit`**. With the shipped four-slash URL, `rsplit('///',1)[1]` splits at the *last three* of the four slashes and returns the **relative** `app/backend/data/daisy.db`. The finding **holds**, at BLOCKER, and the full derivation is written out under INF-5 so the next reader does not have to re-litigate the split.
