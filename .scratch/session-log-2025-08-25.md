# Session Map & Complete History — 2026-08-25 workstream

Purpose: self-contained record of this entire conversation so the chat can be
compressed/discarded. A fresh agent reading only this file can continue without loss.

---

## 1. Project identity

- **Daisy Risk Engine** — personal financial risk analytics platform, Indian-market focus (NSE).
- Stack: FastAPI + async SQLAlchemy + SQLite (`backend/`, Python 3.12, uv) · Next.js 16 + React 19
  + Bun (`frontend/`). Backend :8000, frontend dev :3000.
- Origin guide: `instructions/project_details.md` (~30 historical fix reports in `instructions/doc/`).
- Full codebase audit: `.scratch/project-state/current-state.md`.
- Roadmap: `.scratch/advanced-analytics/spec.md` (+ tickets in `issues/`).
- This session's changelog: root `RELEASE_NOTES.md`.

## 2. User goals (in order given)

1. Set up agent tooling → done (AGENTS.md, docs/agents/*, local-markdown tracker).
2. Learn the project → audit produced current-state.md.
3. Build a **Bloomberg-like terminal**: only capabilities free sites lack; library-first (no wheel
   rebuilding); detailed plan first.
4. Adopt TradingAgents `dataflows` module.
5. Alpha Vantage as automatic fallback, **multiple keys rotating** on rate limits.
6. Keep working autonomously until concrete deliverables; plan every step.
7. Privacy: commit email must be noreply.
8. Detailed release notes / docs for tracking; now this session map.

## 3. Chronology

### A. Tooling setup
Choices: tracker = local markdown under `.scratch/<feature>/`; default triage labels;
created **AGENTS.md** (not CLAUDE.md) + `docs/agents/{issue-tracker,triage-labels,domain}.md`.

### B. Audit findings (why much of the work happened)
- All 9 analytics endpoints used a **hardcoded demo portfolio** (AAPL/MSFT/GOOGL/AMZN @25%),
  ignoring DB holdings.
- Test suite was rotten: 35 failures, httpx API removed, tests hitting the REAL daisy.db,
  wrong URLs/methods, mocks of methods never called.
- WebSocket background worker crash-looped (`GlobalDataService()` missing arg) and broadcast
  mock/hash data. Factor exposures 8/11 hardcoded. FX fixed at 83.0. Dead ~700-line
  AddPositionModal. Details: current-state.md §7.

### C. Spec produced
Filter test formalized (skip anything Yahoo/TradingView/Screener.in shows). Library-first map:
riskfolio-lib / PyPortfolioOpt / quantstats / QuantLib already in deps but unused. Features F1–F14,
phases P0–P6. Tickets 01–22 created (t23 = portfolio importer, added later).

### D. Wave 1: truth pass + test rebuild (t01/t02)
- `_load_portfolio_allocation(db)` feeds all analytics endpoints (explicit tickers still override).
- conftest rebuilt: httpx `ASGITransport`, isolated per-test SQLite via dependency overrides
  (previously tests wrote to real daisy.db), fixtures `ohlcv_frame_factory`/`seeded_positions`,
  four endpoint suites rewritten to current contracts.
- Product bugs fixed en route (full table in RELEASE_NOTES.md): volatility_sizing quadratic form,
  stress-test date-index crash (`_price_series` helpers), `/data/config` route shadowing,
  single-position response schema gap, CSV NULL timestamp, metadata None sector, websocket worker
  arg bug, bulk_add validator signature, liquidity lowercase volume, async DATABASE_URL default.

### E. TradingAgents adoption (t21, Apache-2.0 attributed)
- `indicators_service.py`: stockstats engine (13 indicators), >10-day stale-frame rejection;
  endpoints `/data/indicators/{ticker}` + `/data/verified-snapshot/{ticker}`.
- `company_data_service.py`: fundamentals (28 fields, stub-info guard, 404-vs-503 semantics),
  statements JSON (look-ahead filter), insider feed; endpoints `/data/fundamentals|financials|insider/{ticker}`.
- Integration bugs: cache stores lowercase columns vs yfinance Title-case (bridge map);
  stockstats `wrap()` lowercases post-compute (read indicator columns positionally).
- Skipped deliberately: crypto/forex mapping, reddit/polymarket sentiment, their alpha_vantage
  suite (superseded by t22), FRED.

### F. Alpha Vantage fallback (t22)
`alpha_vantage_service.py`: multi-key rotation pool (`ALPHA_VANTAGE_API_KEYS=k1,k2,…` — each free
key adds 25 req/day + 5 req/min). Per-key in-process budgets; daily-limit notice retires a key
until midnight, frequency notice = 60 s cooldown, invalid keys dropped from pool; exhausted pool
raises locally with ZERO network calls. Error taxonomy per TradingAgents #991 (rate-limit phrasing
classified before api-key phrasing). Symbol bridge `.NS → .BSE` (AV has no NSE). Wired as automatic
fallback in `DataService.fetch_historical_data` (after 3 yfinance retries) + `_fallback_quote`.
Rows stored `source_used='alphavantage'`. Template: `backend/.env.example`.
**Still needs user's real keys in backend/.env to go live.**

### G. Dependency war → bypass decision
- riskfolio-lib 7.0.1 crashes on scipy≥1.16 inside `scipy.linalg.sqrtm` (scalar branch on NxN cov).
- Upgrading riskfolio drags vectorbt + multi-minute resolver churn (aborted twice).
- PyPortfolioOpt 1.5.6 uses scipy private `hierarchy._LINKAGE_METHODS`, removed in scipy 1.18.
- **Decision:** optimizer written directly on numpy/cvxpy(Clarabel)/public scipy APIs →
  `optimization_service.py`, strategies `hrp | min_vol | max_sharpe | min_cvar`. HRP uses canonical
  iterative quasi-diag (first attempt had an expansion bug, fixed via leaf/cluster index rule:
  leaves 0..N-1, clusters N..2N-2).
- Env settled: numpy 2.2.6 / scipy 1.18.1 / hmmlearn added. Gotcha: bare `uv add <pkg>` re-resolves
  the whole unpinned graph; expect long syncs and prefer targeted pins.

### H. Phase-1/2 endpoints (all live-verified against real NSE data)
- `benchmark_service.py`: ^NSEI through shared cache (492 days). `_normalize_indian_ticker` now
  passes Yahoo-native symbols (`^…`, `…=X`) untouched.
- `GET /analytics/tear-sheet`: quantstats suite with per-metric null degradation vs NIFTY;
  beta=0.9888 live; monthly heatmap data + underwater series.
- `GET /analytics/risk-contribution`: exact Euler vol decomposition + CVaR tail attribution
  (sign bug found: shares normalized as positive loss-shares) + sector rollups. Live: TCS = 68%
  vol share at equal weights.
- `POST /analytics/optimize/run`: four strategies + current-vs-recommended trade diff.
- `regime_service.py` + `GET /analytics/regime`: hmmlearn 3-state Gaussian HMM on ^NSEI
  returns+21d-vol (seeded, StandardScaler); labels ordered by mean-variance composite
  `ret − 0.5·vol` so boom states aren't mislabeled crisis; stability % reported (97.4% live).
- Tests in `tests/test_advanced_analytics.py`; seams patched at
  `app.api.analytics.GlobalDataService` / `.BenchmarkService`, and for regime specifically at
  `app.services.regime_service.BenchmarkService`.

### I. Event-loop contamination (subtle)
Engine tests failed ONLY in full suite. Cause: some tests called `asyncio.run()` (closes and
unsets the thread's current loop) while conftest had a deprecated **session-scoped event_loop**
fixture that pytest-asyncio then couldn't find. Fixes: deleted the session fixture entirely;
converted alpha-vantage tests to native async. Rule: never call `asyncio.run()` inside tests.

### J. Frontend repairs
- t03: Rebalance button now calls `portfolioApi.normalizeWeights()` (old code POSTed to a
  nonexistent `/portfolio/rebalance`).
- t04: all raw `fetch('http://localhost:8000/…')` removed from dashboard + manage pages; routed
  through `lib/api.ts`; `updatePosition` extended with quantity/buy_price.
- Vitest had NEVER run on this machine: config CJS-loaded but plugin is ESM-only → renamed to
  `vitest.config.mts`; missing deps installed: `@vitejs/plugin-react@4.3.4` (latest incompatible
  with vitest 2.1's bundled vite), `@vitest/ui@2.1.4`, `jsdom` (declared env but absent).
- MetricCard aligned to its own test contract: `data-testid="metric-card"` on BOTH branches,
  zero-change renders `+0.00%`, empty-string value renders `N/A`; bogus assertion
  `getAllByText('1')` inside skeleton replaced with `.animate-pulse` query.

### K. CORS root cause (user-visible console error "API Error: {}")
`main.py` read CORS origins via `os.getenv("CORS_ORIGINS", "http://localhost:3000")` — bypassing
config.py entirely, so port 3001 stayed blocked even after adding it to settings. Fixed: main.py
now uses `settings.allowed_origins` (3000+3001 both listed). Verified via response header
`access-control-allow-origin: http://localhost:3001` and dashboard rendering positions.

## 4. Live deployment state (this machine)

- Backend :8000 — uvicorn detached (Start-Process), logs `backend/_server.log|.err.log`. Restart =
  kill PID on port 8000 then relaunch same command. Health: GET /health.
- Frontends — :3000 is the USER's own dev server (same repo, hot-reloads); :3001 is a second
  detached instance (`bun run dev --port 3001`, logs `frontend/_dev.log|.err.log`).
- daisy.db currently holds 2 positions: RELIANCE.NS (w .15, q100) and TCS.NS (w .20, q50);
  stock_timeseries cache holds RELIANCE/TCS/INFY/^NSEI history.
- Browser testing done via agent-browser session **daisy-test**; screenshots saved at repo root
  `_shot_dashboard.png`, `_shot_manage.png`.

## 5. Git & privacy

- Repo-local identity: `esconer <83386859+esconer@users.noreply.github.com>` (ID from public API).
- Pushed to origin/master: `181c13c` chore(agents) tooling/docs/tracker+privacy guide ·
  `9a20be5` docs RELEASE_NOTES.md · `37456a8` feat(analytics) big backend wave.
- AFTER push (uncommitted): Phase-1/2 endpoints, optimizer/regime/benchmark services,
  advanced-analytics tests, frontend t03/t04 edits, vitest fixes, CORS fix, ticket status updates,
  this file. **Commit + push still pending — ask user or do on request.**
- Privacy doc: `docs/github-commit-privacy.md` (kept published deliberately — contains nothing
  non-public).

## 6. Test & quality status

- Backend: **97 passed** (~7 s). Frontend: **35 passed** (MetricCard suite; first time it ever ran).
- Known pre-existing noise: ~42 tsc lines about test-setup globals/vitest types (environmental),
  fundamentals endpoint 503 while Yahoo crumb-auth rejects `.info` (transient upstream).
- CI exists (.github/workflows/ci-cd.yml): ruff/mypy/pytest backend; not yet exercised locally.

## 7. File map (new this session)

Backend services: indicators_service · company_data_service · alpha_vantage_service ·
benchmark_service · optimization_service · regime_service.
API additions: analytics.py (+tear-sheet/+risk-contribution/+optimize/run/+regime, allocation
helpers `_load_portfolio_allocation`, `_price_series`, `_assign_price`, `resolve_allocation`);
data.py (+indicators/+verified-snapshot/+fundamentals/+financials/+insider, route order fix);
portfolio.py (validator fix, single-position schema fix, CSV None-guard); websocket.py (worker fix);
main.py (CORS via settings); config.py (async DB default, AV keys, extra origins).
Tests: test_alpha_vantage.py · test_advanced_analytics.py · rewritten test_api_endpoints/test_websocket/conftest.
Root/docs: AGENTS.md · docs/agents/* · docs/github-commit-privacy.md · RELEASE_NOTES.md ·
.scratch/project-state/current-state.md · .scratch/advanced-analytics/{spec.md, issues/01–23} ·
this file.

## 8. Gotchas learned (future-agent notes)

1. PowerShell: no heredocs, no `&&`; multiline python → write a temp script file, don't `-c`.
2. `uv add` on unpinned graphs can churn minutes / drag heavy deps; pin surgically, smoke-test
   imports before building features.
3. Patch targets must match the importing namespace (from-imports bind originals).
4. AsyncMock side_effect returning value X ⇒ awaited result is X; un-set attrs return Mock — set
   every awaited seam explicitly.
5. Our cache schema = lowercase OHLCV columns; yfinance raw = Title-case; normalize at boundaries.
6. pandas pct_change FutureWarnings + stockstats wrap() lowercase behavior (see §3.E).
7. NSE `.info` intermittently 401s ("Invalid Crumb") → map to 503 upstream-outage semantics.
8. Never `asyncio.run()` inside pytest tests.

## 9. Open roadmap (next actions)

- t23 portfolio importer CSV/XLSX (spec F14) — designed, ready to build (deprioritized by owner).
- t12 vol cone; t13–15 tails/correlation/pairs; t16–18 NSE ingestion + flows dashboard
  (t16 needs-info on scope); t19 PDF report; t20 mock purge.
- Optimizer constraints + efficient-frontier chart (deferred slice of t09).
- Coverage gate: backend at ~62% vs 80% gate — remaining gap is data_service vendor paths +
  portfolio API bodies; local gate is `pytest --no-cov` until closed.
- Add AV keys to backend/.env (user action) to activate fallback live.

---

## 10. Wave 2026-08-26 — UI surfacing (t09) + Monte Carlo (t11) + audit

### Built
- **5 dashboard pages** (impeccable skill, Operate mode, established-world extension):
  tear-sheet (monthly heatmap + underwater SVG), risk-contribution (Euler/CVaR bars +
  sector rollup + divergence insight), optimize (4-strategy studio + trade list),
  regime (state table + 120-day timeline), monte-carlo (goal form + SVG fan chart).
- Sidebar + DashboardLayout routeTitles + home widgets (regime strip, risk drivers —
  silent-degrading). `analyticsApi` extended with 5 methods.
- **monte_carlo_service.py** + `POST /analytics/monte-carlo` + `/dashboard/monte-carlo`.
  Library-first after user challenge: arch.bootstrap.StationaryBootstrap (NOT hand-rolled
  blocks), scipy Student-t with ANALYTIC moments + winsorized z + return floor (NaN bug
  found via RuntimeWarning), fitted df shipped as `student_t_df`. GBM stays numpy.
- Tests: test_monte_carlo_service.py (16), test_data_services.py (15 — indicators 23→90%,
  company_data 18→69%). Backend 128 passed. Frontend 35 passed.
- Logic property audit (temp script, all pass): optimizer weights/long-only/dominance,
  Euler identity, MC monotonicity, GBM median vs Itō-corrected closed form
  (S0·exp((μ−σ²/2)T) — first check omitted the correction, engine was right).

### Bugs fixed this wave
- main.py CORS STILL bypassed settings (summary previously claimed fixed — it wasn't);
  now `settings.allowed_origins`, header-verified for 3001.
- risk-contribution crash: `Activity` used but not imported (found via agent-browser
  window error hook + pushstate SPA nav — console buffer was stale).
- Tear-sheet missing % on fraction fields (6 call sites).
- pyproject coverage regex double-escaping → ConfigError → TOML literal strings.
- Optimizer violet → slate/zinc (impeccable detector AI-palette finding).

### Verification artifacts
- Screenshots: `.impeccable/review/desktop-{tear-sheet,risk-contribution,optimize,
  optimize-results,regime,home-widgets,monte-carlo,monte-carlo-results}.png`.
- Browser: agent-browser CLI (`--session daisy-verify`); MCP tools were wedged, CLI works.
  Inner scroll: layout scrolls `<main>`, not window — set `main.scrollTop` via eval.
- Servers die between shell sessions; relaunch pattern in §4 (both died twice this wave).

### Gotchas added
9. lucide icons: audit `icon={X}` vs imports per page (two pages had the same miss).
10. `arch.bootstrap`: iterate via `bs.bootstrap(n)` generator (`pos[0]` = resample), NOT
    `for x in bs` (not iterable); seed= accepts np Generator.
11. Moment-matching t innovations by SAMPLE std of draws is outlier-poisoned — use analytic
    scale·sqrt(df/(df−2)), floor df at 2.1, winsorize ±8.
12. Payload rounding (6dp) ⇒ sum-to-1 checks need ~1e-4 tolerance, not 1e-6.

### Uncommitted (since 374a… push)
PUSHED 2026-08-26 as: `b015e6e` feat(analytics) MC engine + services + CORS + 128 tests ·
`bb92155` feat(dashboard) 5 pages + widgets · `34254d6` docs release notes/tickets/session log/
impeccable skill. Working tree clean except pre-existing untracked frontend assets
(assets/, bg.png, favicon.*, html.meta.json.gz) left alone deliberately.
.gitignore now also excludes: *.log, .coverage, htmlcov/, .impeccable/, _shot_*.png,
test-results.xml, _diag_rc.py.

