# Inventory slice A2 (frontend) + A3 (infra/tests/deps)

Source: Phase 1 read-only explorers. Items marked ✓ were **re-verified by the orchestrator against
source**. All others are explorer-asserted; the writer MUST re-verify before emitting a ledger row.

Tooling: **`rg -F` does NOT fix the quote trap** — a single `"` in a pattern silently returns zero
here. Use `Select-String` (verified working) or a quote-free pattern. Any "no matches" claim needs
a control search that matches. Default `rg` respects `.gitignore`.

Baseline for this layer: `tsc --noEmit` exit 0 · `vitest run` 50 files / 537 tests / 0 failures ·
`eslint src/` 0 errors / 223 warnings · `next build` 25 static routes. Backend: 5 failed / 2254
passed (stable failure set, network-dependent).

---

## PART 1 — FRONTEND (`frontend/src/{app,components,lib,hooks}`)

### FE-1 — The unrealized-P/L `%` guard on `/portfolio/manage` is unreachable  ✓ VERIFIED
- **Class** bug · **Sev** medium · **Conf** confirmed
- **Loc** `frontend/src/app/portfolio/manage/page.tsx:786` (guard), `:45` (helper), `:200` (producer)
- **Symptom** A holding the engine could not cost (`baseCost === 0`) renders a green **"+0.00%"**
  instead of `N/A`. The `N/A` branch is dead code that *looks* like the fix.
- **Evidence**
```tsx
// :45 — this helper can only ever return a FINITE number
const monetaryValue = (base, native): number => {
    if (typeof base === 'number' && Number.isFinite(base)) return base;
    if (typeof native === 'number' && Number.isFinite(native)) return native;
    return 0;                      // NaN and undefined both land here
};
// :200 — the unmeasurable case is deliberately built as NaN
unrealized_gain_loss_pct_base: monetaryValue(
    pos.unrealized_gain_loss_pct_base,
    baseCost > 0 ? ((baseCurrent - baseCost) / baseCost) * 100 : NaN),
// :786 — guard is therefore always true
{Number.isFinite(monetaryValue(position.unrealized_gain_loss_pct_base, position.unrealized_gain_loss_pct))
```
- **Also** `PortfolioStats.tsx` re-applies the same helper, so its P/L average inherits the fabrication.

### FE-2 — Copula tail-dependence matrix invents `1.000`/`0.000` for unmeasured pairs
- **Class** bug · **Sev** medium · **Conf** suspected (fires when `tickers.length > matrix[r].length`
  or a cell is null; backend payload not seen)
- **Loc** `frontend/src/app/dashboard/risk-studio/page.tsx:621` (table), `:377` (CSV)
- **Symptom** An unestimated pair renders `λL = 0.000` on a **green** "no crash dependence"
  background; the CSV prints `0.0000`. The colour band is a risk verdict.
- **Evidence**
```tsx
const num = copulaMatrix[rowIdx]?.[colIdx] ?? (rowIdx === colIdx ? 1.0 : 0.0);
const intensity = isSelf ? '...' : num > 0.25 ? 'bg-rose-500/20 ...' : 'bg-emerald-500/10 text-emerald-300';
// :377 CSV — same fallback
rowVals.push((copulaMatrix[r]?.[c] ?? (r === c ? 1.0 : 0.0)).toFixed(4));
```

### FE-3 — `PortfolioStats` prints `NaN%` for "Largest Position" when a holding lacks a weight
- **Class** bug · **Sev** medium · **Conf** suspected (`PortfolioPosition.weight` is typed `number`,
  so TypeScript cannot catch it)
- **Loc** `frontend/src/components/portfolio/PortfolioStats.tsx:83`, rendered `:194`
- **Evidence**
```tsx
const portfolioConcentration = Math.max(...positions.map(pos => pos.weight * 100));
{stats.portfolioConcentration.toFixed(1)}%
```
- **The tell** the sibling card at `:179` *is* protected by the `positions.length === 0` early
  return at `:112`, so the file reads as guarded; this one value is not.

### FE-4 — "Add to portfolio" from the screener commits `buy_price: 0` at 100% weight  ✓ VERIFIED
- **Class** bug · **Sev** medium · **Conf** confirmed (the code path is unconditional)
- **Loc** `frontend/src/app/dashboard/screener-studio/page.tsx:177`
- **Symptom** A screener row whose price the backend could not measure can still be clicked into the
  portfolio. The row is **persisted** with `buy_price: 0`, and at 100% weight if the book was empty.
  The page reports success.
- **Evidence**
```tsx
176:    try {
177:      const price = stock.price || 0;                 // absent price -> 0
180:      const portfolio = await portfolioApi.getPortfolio({ currency: 'INR' });
      const totalValue = portfolio.total_value || 0;
      const weight = posList.length === 0 || totalValue <= 0 ? 1.0 : positionValue / (totalValue + positionValue);
```
- **Why it is worse than a display bug** this is a **write**. The fabricated zero is persisted and
  surfaces as wrong total cost, wrong unrealized P/L and wrong risk weight on every dashboard.

### FE-5 — Pairs page calls `.toFixed()` on three unguarded fields; one absent field blanks the route
- **Class** bug · **Sev** medium · **Conf** suspected (response typed `any[]` at `:39`)
- **Loc** `frontend/src/app/dashboard/pairs/page.tsx:137,140,145`
- **Symptom** A render-time `TypeError` behind the error boundary takes out the **whole page**, not
  one cell.
- **Evidence**
```tsx
39: const [pairs, setPairs] = useState<any[]>([]);
137: {p.engle_granger_pvalue.toFixed(4)}
140: {p.hedge_ratio_beta.toFixed(4)}
145: {p.current_spread_zscore.toFixed(2)}σ
// the tell — one field two lines down IS guarded:
      {p.ou_half_life_days ? `${p.ou_half_life_days.toFixed(1)} days` : 'N/A'}
```
- **Corroborated independently** the scratch inventory's OE-14 lists the same
  `current_spread_zscore` call, typed `Optional[float]` at `backend/app/models/schemas.py:495`, and
  notes the field appears in **no** `.ts` type file — TypeScript structurally cannot catch it.

### FE-6 — Live-connection badge can never leave "connecting"; socket URL has a doubled segment
- **Class** bug · **Sev** medium · **Conf** suspected (backend route outside the frontend agent's area)
- **Loc** `frontend/src/components/layout/RealtimeStatus.tsx:26-32,41`; `frontend/src/lib/websocket.ts:60`
- **Evidence**
```ts
// websocket.ts:60 — 'ws/ws'
return `${protocol}//${urlHost}/api/v1/ws/ws/${this._clientId}`;
```
- **Two problems** the chip renders a false "connecting" claim the moment the user switches Live
  off (it has no third state), and `ws/ws` is **unpinned by any test** — `websocket.test.ts` contains
  zero assertions on the URL, which is exactly the shape that 404s silently.
- **Blast radius note** `liveDataMode` defaults `true` (`lib/store.ts:343`), so the socket
  auto-connects on all 24 dashboard routes.

### FE-7 — The store launders an absent `total_value` into a measured `₹0.00`
- **Class** bug · **Sev** medium · **Conf** suspected
- **Loc** `frontend/src/lib/store.ts:171`
- **Evidence**
```ts
    totalValue: data.total_value || 0,
```
- **The irony worth quoting** `app/dashboard/page.tsx:158-160` was hardened against exactly this, and
  its own comment reads *"NaN || 0 is 0, which turns a broken payload into a confident ₹0.00"* — but
  it can only harden what the store hands it, and `NaN || 0` fires at `:171` first.

### FE-8 — Header's PDF total silently drops holdings with no measured value
- **Class** bug · **Sev** low · **Conf** confirmed · **Loc** `frontend/src/components/layout/Header.tsx:96`
- **Evidence** `const totalVal = positions.reduce((sum, p) => sum + (p.market_value_base ?? p.market_value ?? 0), 0);`
- **The tell** the same file is scrupulous on its other two fetch routes (`allSettled`, `?? null`,
  *"a PDF that silently drops its risk section is recoverable, one that invents it is not"*). This
  one total is the exception.

### FE-9 — ~500 lines of unreachable code including the app's only HTTP interval
- **Class** maintainability · **Sev** low · **Conf** confirmed
- **Loc** `hooks/useRealTime.ts:11,338,439,501`; `components/ui/NotificationSystem.tsx:94,128,169,217`;
  `lib/api.ts:927`; `lib/store.ts:474`
- **Zero-caller inventory** `useAutoRefresh` (the only `setInterval` that issues HTTP),
  `useDashboardPreferences`, `useDateRangeSelection`, `ExportProgressIndicator`,
  `ConnectionStatus`, `LiveUpdateIndicator`, `RefreshButton`, `healthApi.check` (the only `/health`
  request in the repo — **never issued**), `dataApi.{getStockData,getBatchStockData,validateTicker,refreshData}`,
  `portfolioApi.{getPosition,normalizeWeights}`, `companyDataApi.{getFundamentals,getInsiderTransactions}`,
  `equityResearchApi.getAiDossier`, `store.{useCSVExport,convertToCSV,downloadCSV}`
- **Why it matters** `useAutoRefresh` is the thing the next auditor will assume is "the poller".
  Two dead components each call `useEnhancedRealTimeAnalytics()`, which opens its own
  `WebSocketClient` — mounting either would double the socket count.

### FE-10 — `Header` subscribes to the entire portfolio store
- **Class** optimisation · **Sev** low · **Conf** confirmed · **Loc** `components/layout/Header.tsx:74`
- **Evidence** `usePortfolioStore((state) => state)` — `isLoading` toggles twice per fetch.
  2 other whole-store subscriptions: `websocket.ts:283`, `RealtimeStatus.tsx:15`.

### FE-11 — Volatility-sizing declares its table columns unmemoized
- **Class** optimisation · **Sev** nit · **Conf** confirmed
- **Loc** `frontend/src/app/dashboard/volatility-sizing/page.tsx:883`
- **Contrast** `app/dashboard/page.tsx:249` wraps the equivalent in `useMemo`. `DataTable.tsx:70`
  passes `columns` straight into `useTable`, so the column model is rebuilt every render for the
  largest table on the largest page. Relevant because React Compiler is deliberately off.

### SETTLED: the `/v1/models` + `/health` request flood is **NOT** a frontend problem
- **Zero** occurrences of `v1/models` anywhere under `frontend/src`. Control (`v1/analytics`) matches.
- Every path the app issues is `/api/v1/*` — 34 axios methods read end to end (`api.ts:432-932`).
- `/health` exists at `api.ts:929` as `healthApi.check` and has **zero callers**, so it is never issued.
- The only `setInterval` issuing HTTP is `useAutoRefresh` — **zero callers, dead**.
- The three live timers are all non-HTTP: WS heartbeat ping 30 s (`websocket.ts:192`), a 30 s
  freshness clock (`useRealTime.ts:153`), a 60 s heartbeat timeout. All have cleanups.
- A full dashboard visit issues **11 HTTP GETs once and 0 per minute**.
- **Conclusion** if the paired lines are still being produced, the caller is outside
  `frontend/src/{app,components,lib,hooks}` — most likely an OpenAI-compatible SDK probing an LLM
  server, since `/v1/models` sits on the backend origin with no `/api` prefix. The app's own AI
  features only GET a prompt string and copy it; **no LLM client ships in this frontend**.

### Hardened and correct — do NOT re-report
`app/dashboard/page.tsx:129-222` · `dashboard/concentration/page.tsx:686-688,716` ·
`dashboard/volatility-sizing/page.tsx:1057-1074` · `hooks/useAnalytics.ts:338-359` ·
`components/portfolio/MarginalImpactPanel.tsx` · `dashboard/risk-contribution/page.tsx:338,352` ·
`risk-studio:361-369` · `lib/utils.ts:120-131` · `MetricCard.tsx` · `lib/export.ts:1082,1059-1060`.
The `|| 0`/`?? 0` sweep returns 75 hits; ~55 are comments *documenting already-fixed* fabrications.

### Bundle — heaviest remaining eager deps
`recharts` (~8 pages, largest eager dep; mitigated by `optimizePackageImports: ['recharts']`) ·
`@tanstack/react-table` (eager in `DataTable.tsx` + 8 pages) · `zustand` · `axios`.
`jspdf`/`xlsx`/`file-saver` are all reached only through the dynamic `await import('@/lib/export')`.
**The 715.6 KB export chunk is confirmed pulled by 0 of 24 prerendered routes** — every `/lib/export`
import outside `Header.tsx:20` is either `import type` or inside an `await import`.

---

## PART 2 — INFRA / CI / TESTS / DEPS

### INF-1 — Frontend Docker build cannot succeed: no `output: 'standalone'`  ✓ VERIFIED
- **Class** bug · **Sev** critical · **Conf** confirmed
- **Loc** `frontend/Dockerfile:45,62` vs `frontend/next.config.ts`
- **Symptom** `COPY --from=builder /app/.next/standalone ./` fails; Next only emits that directory
  when `output: 'standalone'` is configured. Blocks the CI `frontend` job, the `integration` job,
  and the prod ECR image.
- **Proof of absence** `Select-String -Pattern 'output' -SimpleMatch` over the whole file returns
  **zero matches**. (`next.config.ts` is 41 lines; `reactCompiler: false` is at `:5`.)
- **Blast radius** nobody notices because `production-images` is gated behind a permanently-failing
  `backend` job (INF-3).

### INF-2 — Base image `node:18-alpine` is below Next 16.3.6's engine requirement  ✓ VERIFIED
- **Class** bug · **Sev** critical · **Conf** confirmed
- **Loc** `frontend/Dockerfile:2` = `FROM node:18-alpine AS base`
- **Evidence** `registry.npmjs.org/next/16.3.6` declares `"engines":{"node":">=20.9.0"}`.
  `frontend/package.json` has **no `engines` field**, so nothing warns locally.
- **Signal** two co-located fatal errors in one file is strong evidence the Dockerfile has never
  been executed.

### INF-3 — The `backend` CI job can never pass  ✓ VERIFIED
- **Class** bug · **Sev** critical · **Conf** confirmed
- **Loc** `.github/workflows/ci-cd.yml:51-54` + `backend/tests/integration/test_compose_services.py:19-27`
- **Symptom** `pytest ... tests/` collects the localhost-only smoke test, which calls
  `urlopen("http://127.0.0.1:8000/health")`. On an `ubuntu-latest` runner with no services up that
  raises. `backend` goes red → `integration` is skipped via `needs:` → `production-images` skipped.
- **Evidence**
```yaml
51:     - name: Run backend tests with 80% coverage gate
54:       uv run pytest -p no:cacheprovider tests/ --cov=app --cov-fail-under=80 ...
```
- **Why this is the load-bearing finding** it means **CI has never been green**, so there is no
  automated evidence any image in ECR exists — and nobody noticed because the pipeline is
  structurally red rather than absent.
- **Already-declared fix** `pyproject.toml:89` declares an `integration` marker that **no test uses**
  (Select-String → 0 matches, control `pytest.mark.slow` → 2 matches).

### INF-4 — `test_audit_rule_coverage.py` hardcodes one developer's temp path and `pytest.fail`s  ✓ VERIFIED
- **Class** bug · **Sev** critical · **Conf** confirmed
- **Loc** `backend/tests/test_audit_rule_coverage.py:77` and `:1055-1063`
- **Evidence**
```python
77: BASE_EXPORT = Path(r"C:\Users\Sayanti\AppData\Local\Temp\opencode\v27.json")
1056:    if not BASE_EXPORT.is_file():
1057:        pytest.fail(
```
- **Why critical** the 57-rule audit gate is the only mechanism measuring whether the export's rules
  can *fail*. It is bound to one person's `%TEMP%`. Combined with INF-3, a second independent reason
  the backend job is red.
- **Constraint on any fix** the file's own `.gitignore` rationale forbids tracking live holdings /
  cost basis, so the fixture must be **sanitised** before committing.

### INF-5 — Backend container healthcheck computes a *relative* SQLite path  ✓ VERIFIED
- **Class** bug · **Sev** high · **Conf** confirmed
- **Loc** `backend/Dockerfile:52`; `docker-compose.yml:29,58-60`; `docker-compose.prod.yml:41-48`
- **Evidence**
```dockerfile
52: CMD ["python","-c","...p=os.environ['DATABASE_URL'].rsplit('///',1)[1]; c=sqlite3.connect(p,timeout=3)..."]
```
- **Orchestrator-tested**, after initially disputing it:
```
url  : sqlite+aiosqlite:////app/backend/data/daisy.db
left : 'sqlite+aiosqlite:/'
right: 'app/backend/data/daisy.db'          <- RELATIVE
joined with WORKDIR /app/backend -> \app\backend\app\backend\data\daisy.db
url.split('///',1)[1]             -> '/app/backend/data/daisy.db'   <- correct
```
With `WORKDIR /app/backend` (`:24`), the relative path resolves under a parent that does not exist →
`sqlite3.OperationalError` → healthcheck fails 3× → `depends_on: service_healthy` never satisfied →
the frontend never starts under either compose file.

### INF-6 — Frontend prod-image healthcheck calls `curl`, which alpine does not ship
- **Class** bug · **Sev** high · **Conf** confirmed · **Loc** `frontend/Dockerfile:58-59`
- **Evidence** `HEALTHCHECK ... CMD curl -f http://localhost:3000 || exit 1`; the only `apk add` is
  `libc6-compat` at `:6`. BusyBox ships `wget`, not `curl` → exit 127 → permanently unhealthy.
- **Why it survived** the compose files *override* it with a working `node -e fetch(...)` probe.

### INF-7 — `restoreMocks` / `unstubGlobals` absent while `setup.ts` mutates globals at module scope  ✓ VERIFIED
- **Class** bug · **Sev** high · **Conf** confirmed
- **Loc** `frontend/vitest.config.mts:8-14`; `frontend/src/test/setup.ts:23,26,35,58,66`
- **Evidence**
```ts
// vitest.config.mts:8-14 — no restoreMocks / unstubGlobals / clearMocks anywhere in the file
    test: { globals: true, environment: 'jsdom', setupFiles: ['./src/test/setup.ts'], coverage: {...} }
// setup.ts
23:   global.WebSocket = MockWebSocket as any
26:   global.fetch = vi.fn()
35:   vi.stubGlobal('localStorage', localStorageMock)
```
- **The fingerprint** four test files already hand-roll `mockReset()` loops as a workaround for the
  missing global config — `store.test.ts:125`, `useAnalytics.test.tsx:35`,
  `HeaderRiskMetricsWiring.test.tsx:48`, `AnalyticsUnavailableContracts.test.tsx:119`.
- **Status** latent flake, not a current failure — CI uses a single-fork pool so the leak is hidden.

### INF-8 — `async_client` does not rebind the global engine; `websocket.py` binds `SessionLocal` at import
- **Class** risk · **Sev** high · **Conf** suspected (mechanism confirmed; reachability unproven)
- **Loc** `backend/tests/conftest.py:223-230` vs `:245-257`; `backend/app/api/websocket.py:19`
- **Symptom** a green test run can silently mutate the developer's real portfolio database —
  holdings, cost basis, P&L. `backend/data/daisy.db` (+ `-wal`/`-shm`) is present on disk.
- **Evidence**
```python
226:    app.dependency_overrides[get_db_session] = _override_get_db(test_db)
227:    transport = ASGITransport(app=app)      # no engine/SessionLocal rebind
250:    monkeypatch.setattr(db_mod, "engine", tmp_engine)     # client fixture only
256:    monkeypatch.setattr(ws_mod, "SessionLocal", db_mod.SessionLocal)
```
- **The tell** the `client` docstring (`:235-244`) documents this exact hazard. It was fixed for one
  fixture and not the other.

### INF-9 — `test_coverage_direct_unit_routes.py`: 24 assertions that cannot fail
- **Class** bug (test quality) · **Sev** high · **Conf** confirmed
- **Loc** `backend/tests/test_coverage_direct_unit_routes.py:115-224` (24 instances),
  mocks `:88-112`, patched-out units `:192,200,208`
- **Evidence**
```python
115  res_rr = await get_realized_risk(tickers="TCS.NS,INFY.NS", db=mock_db, ...)
119  assert res_rr is not None
```
- **Why** a handler returning `{}`, `{"error": ...}` or all-NaN passes. Dependencies are unconfigured
  `AsyncMock()`s, so `mock_ds.get_ohlcv()` returns a `MagicMock` — the test exercises mock plumbing.
- **Systemic, not isolated** `Select-String 'assert .* is not None'` over `backend/tests` returns
  80+ matches across 15+ files.

### INF-10 — `conftest.py::test_env_vars` cannot do what it claims
- **Class** bug (test quality) · **Sev** medium · **Conf** confirmed · **Loc** `:364-385`, import `:21`
- **Why** `from main import app` at `:21` freezes `settings` at import time; mutating `os.environ`
  afterwards changes nothing. The teardown is *correct*, which is what makes it look effective.
  No consumer found in any test's parameter list.

### INF-11 — `conftest.py` module-level `pytestmark` is inert; `cleanup_test_data` cleans nothing
- **Class** maintainability · **Sev** medium · **Conf** confirmed · **Loc** `:420-434`
- **Evidence** `pytestmark` in a *conftest* does not apply marks to test modules.
  `cleanup_test_data` is `autouse=True`, yields, then `pass`.
- **The real leak** `DataService._quote_memo`, `._in_memory_df_cache`, `._l1_sources` are class-level
  dicts cleared only by a file-local fixture at `test_agent_b_data_audit.py:88-91`.

### INF-12 — `create_test_price_data` seeds from `hash(ticker)`  ✓ VERIFIED
- **Class** bug (test quality) · **Sev** medium · **Conf** confirmed · **Loc** `conftest.py:448`
- **Evidence** `np.random.seed(hash(ticker) % 2**32)  # Seed based on ticker for consistency`
- **The irony** `str.__hash__` is randomised per process, so the comment states the opposite of what
  the code does. The other five `np.random.seed(...)` calls in the same file all use integer
  literals — that is the control showing this is the outlier.

### INF-13 — 19 of 57 audit rules never exercised; the gate's pass condition is weaker than its name
- **Class** maintainability · **Sev** medium · **Conf** confirmed (static count) / needs-runtime (fires)
- **Loc** `test_audit_rule_coverage.py:122-842` (`MUTATIONS`), `:872-936` (`KNOWN_UNCOVERED`), `:1234`
- **Findings** independent count reproduces **19 of 57 never named** in any `expects` tuple — and 18
  of those 19 are **envelope rules** (`ENV-001..015,017,018,020` + `XS-008`), i.e. the ones whose job
  is guaranteeing the document is schema-valid so the mutation measurement is meaningful at all.
- **Arithmetic defect in the file itself** the prose header (`:851-871`) sums `3+6+5+2+4+5 = 25`;
  `KNOWN_UNCOVERED` contains **29** entries. It miscounts its own frozen set by four.
- **Real catch rate** `KNOWN_UNCOVERED` 29 + `KNOWN_COLLATERAL` 3 → only **50/82 (61%)** of injected
  defects are caught by the rule the author declared correct. The pass condition requires ≥1 firing
  rule per **section** (17 sections), so it stays green with 65 uncovered.
- **Credit where due** the frozen sets are asserted in both directions, so improvement cannot pass
  unnoticed. The gap is scope, not rigour.

### INF-14 — The audit harness never runs against a real export; nothing in CI does
- **Class** risk · **Sev** medium · **Conf** confirmed · **Loc** `test_audit_rule_coverage.py:1085-1096`
- **The answer to "is anything that would catch a lost ORM write / an uncomputed statistic published
  as computed?" — NO.** `_fire()` builds `ca.Export(doc=..., raw=json.dumps(document))` from a frozen
  JSON file on disk. No gate runs `context_audit` against an export generated by the running app.
- **The gap is easy to miss** the harness docstring says "`57/57` is a consistency signal, not a
  correctness one" — the gate proves the *rules* work, nothing proves they are *pointed at the right
  document*.

### INF-15 — Deprecated / mutable GitHub Actions pinned in CI
- **Class** risk · **Sev** high · **Conf** confirmed (versions) / needs-runtime (failure mode)
- **Loc** `ci-cd.yml:36-37` (`actions/cache@v3`), `:77` (`bun-version: latest`), `:125`
  (`aquasecurity/trivy-action@**master**` — mutable ref), `:133`
  (`codeql-action/upload-sarif@v2`, retired Jan 2025), `:187` (`amazon-ecr-login@v1`)
- **Bonus real defect** the cache at `:38` is `~/.cache/pip` while the installer is `uv` (`:44`) — it
  caches a directory nothing reads, so every run re-downloads and re-links the whole scientific
  stack. That is the real reason the backend job is slow.

### INF-16 — `uv sync --frozen` cannot detect pyproject/lock drift
- **Class** bug · **Sev** medium · **Conf** confirmed · **Loc** `ci-cd.yml:44`; `backend/Dockerfile:15`
- **Why** `--frozen` means "use the lockfile as-is"; `--locked` is what *asserts* the lock matches the
  manifest. So a new dependency without `uv lock` installs the old set and the tests run against
  something nobody declared — exactly the AGENTS.md "tools silently vanish" failure, at the CI layer.
- **Current state** both tables **are** in sync — verified in `uv.lock` (`extra == 'dev'` markers on
  all five pytest packages; `dev = [ruff]` for the group, `ruff-0.16.8` resolved).

### INF-17 — Dev-only tooling shipped as runtime dependencies
- **Class** maintainability · **Sev** medium · **Conf** confirmed
- **Loc** `frontend/package.json:16-44`; `backend/pyproject.toml:35,50,84`
- **Frontend in `dependencies` not `devDependencies`** `vitest`, `@testing-library/jest-dom`,
  `@testing-library/react`, `@types/file-saver`, `papaparse`
- **Backend** `ipython>=9.6.0` in `[project] dependencies` with **zero** imports anywhere (control:
  `import pandas as pd` matches `conftest.py:10`); `pytest-xdist>=3.6.1` installed but `addopts`
  never invokes `-n`, so **2254 tests run serially** — most of why the backend job is a 12-minute wall;
  `babel-plugin-react-compiler` pinned while `next.config.ts:5` sets `reactCompiler: false`.

### INF-18 — Root `.gitignore` omits `.ruff_cache/`; `*.db` protection lives only one file deep
- **Class** risk · **Sev** low · **Conf** confirmed
- **Loc** root `.gitignore:76-77` has `*.db-wal`/`*.db-shm` but no `*.db`; `backend/.gitignore:13-14`
  has both. `.ruff_cache/` exists at the repo root and is not ignored.
- **Why it matters** the root `.gitignore` goes to considerable length to keep live holdings and cost
  basis out of git, and the primary store of exactly that data is protected by a rule three
  directories down. **No tracked secret was found** — that is a statement about ignore rules, not
  about the index.

### INF-19 — `scripts/deploy.sh` is never invoked; its default `PUBLIC_BASE_URL` probes the wrong port
- **Class** risk · **Sev** medium · **Conf** confirmed
- **Loc** `scripts/deploy.sh:22,177-181`; `docker-compose.prod.yml:62`
- **Evidence** `PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-http://127.0.0.1}"` (port 80) while
  `docker-compose.prod.yml:62` binds the frontend to `127.0.0.1:3000`. `health_check()` polls for 60 s
  against nothing. The 234-line workflow contains zero references to `deploy.sh`.
- **The irony** the script correctly refuses `:latest` and pins by image digest — real care that no
  automated path exercises. Meanwhile `production-images` declares `environment: production` and a
  live URL for a job that deploys nothing.

### INF-20 — `filterwarnings` ignores only `UserWarning`/`DeprecationWarning`
- **Class** maintainability · **Sev** low · **Conf** confirmed · **Loc** `backend/pyproject.toml:95-98`
- **Why it matters** both `ComplexWarning` and `SAWarning` subclass `RuntimeWarning` and pass through.
  There is **no `error::` entry at all**, so a genuine `RuntimeWarning` — e.g. invalid value in a
  sqrt, producing NaN — passes silently. A suite that cannot fail on this cannot catch the NaN class.

### INF-21 — No `concurrency` group; CI burns runners on superseded commits
- **Class** optimisation · **Sev** nit · **Conf** confirmed · **Loc** `ci-cd.yml:1-12`
- **Proof of absence** `.github/workflows/` contains **exactly one file**; confirmed with `hidden:true`.

### INF-22 — Two sources of truth for host policy; one is invisible in every config file
- **Class** risk · **Sev** low · **Conf** confirmed
- **Loc** `docker-compose.prod.yml:17`; `backend/main.py:105-107`
- **Why** prod compose defaults `ALLOWED_ORIGINS` to `http://localhost:3000`, while `main.py:107`
  **hardcodes** `allowed_hosts=["daisy-risk-engine.com","*.daisy-risk-engine.com","localhost","127.0.0.1"]`
  independently of the env var. An operator who sets the env var correctly gets correct CORS but
  **403 from `TrustedHostMiddleware`**, unfixable without editing Python.
- **Credit where due** the backend Dockerfile runs non-root (`USER appuser`, `:46`) and the frontend
  does too (`USER nextjs`, `:49`). No secrets are hardcoded in either compose file.

### CI MATRIX — single workflow, 5 jobs
`backend` (checkout → python 3.12 → unversioned uv installer → **wrong** cache path → sync →
`ruff check` E9+F only → pytest → docker build → push ghcr on main) ·
`frontend` (checkout → `bun-version: latest` → install → **tsc --noEmit** ✓ → **eslint** ✓ →
vitest → **next build** ✓ → docker build → push) ·
`security` (trivy `@master` → codeql `@v2` retired → dependency-review) ·
`integration` (`needs: [backend, frontend]` → compose up --wait) ·
`production-images` (`needs: [backend, frontend, security, integration]` → ECR → notify-failure).
**Answers:** backend suite runs in CI but is unpassable (INF-3) · the 57-rule gate is unrunnable
(INF-4) · typecheck ✓ · `next build` ✓ · **nothing** would catch a lost ORM write or an uncomputed
statistic published as computed.

### HERMETICITY — the vendor seam is better mocked than expected
`test_coverage_data_service.py`, `test_alpha_vantage.py` (patches `avmod.requests.get`),
`test_source_preference_and_screens`, `test_data_services.py`, `test_agent_b_data_audit.py`,
`test_db_gate_concurrency.py`, `test_equity_research_and_screens.py`, `test_bugfix_providers_05.py`,
`test_bugfix_core_services.py` all patch `yfinance.Ticker`/`bfinance.*`;
`test_bugfix_core_services.py:266-302` installs a spy that **raises** if the real `Ticker` is built.
**The real non-hermetic inputs are these four, in order:**
1. `test_audit_rule_coverage.py:77` — machine-bound, outside the repo, **not a network issue at all**
2. `conftest.py:223-230` — `async_client` can write to the real `daisy.db` (**destructive**)
3. class-level service caches cleared in one file only
4. `conftest.py:448` — `hash()` seeding re-rolls every process
**No framework-level mitigation exists.** No cassette layer; `responses==0.25.0` is declared at
`pyproject.toml:55` and **never imported**; no `pytest-socket`; the `integration` marker is declared
and unused.
**Recommended mechanism (shape only):** (1) an autouse session fixture that makes
`socket.socket.connect` raise unless `ALLOW_NETWORK=1` — ~20 lines, converts a silent network
dependency into a named failure, **do this first**; (2) two autouse vendor fixtures defaulting to
raise, replacing ~76 per-file `patch()` sites across 11 files; (3) `vcrpy` cassettes for the residue,
scrubbed; (4) vendorise `v27.json` into `backend/tests/fixtures/` sanitised; (5) autouse
class-level cache reset in conftest.

### DOC / CONFIG DRIFT — verified contradictions
| Documented claim | Location | Reality |
|---|---|---|
| "249/249 Passed (0 failures) with 85% coverage" | `RELEASE_NOTES.md:181` | baseline is **5 failed / 2254 passed** |
| "Frontend Test Suite: 60/60 Passed" | `RELEASE_NOTES.md:182` | **50 files / 537 tests** |
| "TypeScript 5.7+" | `CONTEXT.md:24` | `"typescript": "6.0.3"` |
| Frontend on `:3001` | `CONTEXT.md:25` | no 3001 anywhere; compose binds 3000 |
| `uvicorn --host 0.0.0.0` | `CONTEXT.md:237` | `README.md:13` says localhost-only, **no auth** |
| "+ optional redis/nginx" | `README.md:55` | compose has **exactly two services**, no redis/nginx |
| Domain docs at `docs/adr/` | `AGENTS.md:20` | `docs/` has **no `adr/`** |
| "`uv sync --extra dev` completes cleanly" | `RELEASE_NOTES.md:74,184` | omits `--group dev` → **ruff stays uninstalled**, breaking the pre-commit hook |
| "0 errors / ~271 warnings" | `ci-cd.yml:89` | **223 warnings** — the comment justifying the errors-only gate is quantitatively stale |
| Three different coverage numbers (80/85/62%) | `TEST_INFRA.md`, `RELEASE_NOTES.md` | one metric, three docs |