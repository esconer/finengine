# Ponytail Audit — over-engineering only (2026-09-05)

Scope: whole tree, not a diff. Correctness/security/perf out of scope. Read-only audit, nothing deleted.
Tags: delete (dead/speculative), stdlib (reinvented stdlib), native (platform does it), yagni (one-impl abstraction), shrink (same logic, fewer lines).

## Findings (biggest cut first)

delete tests/test_coverage_* (14 files, ~3000 lines) identical GlobalDataService mock frames. Keep 1 spec per route. [backend/tests/test_coverage_*]
delete .agents/skills 60+ unreferenced dirs (12 UI-taste + 13 caveman/cavecrew + neon x2 + wrappers). Keep issue-tracker/triage-labels/domain + caveman. [.agents/skills/]
delete instructions/ (project_details.md 1896 lines + doc/*_REPORT.md x28 closed logs). Keep CONTEXT.md only. [instructions/]
delete frontend/src/lib/export.ts 470-line PDF/Excel/CSV/Chart/Progress framework (ChartExporter draws placeholder rect). Use papaparse/XLSX direct + URL.createObjectURL. [frontend/src/lib/export.ts:30-500]
delete frontend NotificationSystem (271 lines) + ExportPanel (304 lines) zero app imports, dead flags/defaultChecked. Delete both. [frontend/src/components/ui/NotificationSystem.tsx, ExportPanel.tsx]
delete frontend dead variants PortfolioTable/PortfolioCharts/PortfolioFilters/CurrencySelector (manage/page inlines all). Delete 4 files. [frontend/src/components/portfolio/]
delete backend dead/heavy runtime deps quantlib/ipython/alembic/aiohttp/openpyxl/python-multipart/python-dotenv + dev faker/factory-boy/freezegun/responses/pytest-mock/pytest-xdist (zero imports). Delete lines. [backend/pyproject.toml:25,27,30-32,35,37,41,50-55]
delete docker-compose.prod.yml prometheus/grafana/elasticsearch/logstash/kibana (105 lines, mounts ./monitoring ./ssl ./nginx missing). Use docker logs. [docker-compose.prod.yml:121-226]
delete frontend/src/hooks/useRealTime.ts 6-hook file (useAutoRefresh/useDashboardPreferences/useDateRangeSelection zero callers, global jobs/notifications reinvent zustand). Keep 1 hook. [frontend/src/hooks/useRealTime.ts]
shrink frontend/src/lib/websocket.ts WebSocketClient + useWebSocket + useRealTimeAnalytics (hand reconnect/heartbeat/clientId). Use native WebSocket + 30-line hook. [frontend/src/lib/websocket.ts:25-385]
delete backend/app/api/websocket.py ConnectionManager + 30s full-pull + unread token + /status + /broadcast dict-mutate. Poll REST. [backend/app/api/websocket.py + main.py:136-140]
delete backend migrations/* (365 lines, fabricates quantity=100) + root test_api_integrity.py/test_bulk_operations_integrity.py/test_integrity_api.sh/_diag_rc.py (live hitters, np-before-import). Seeded create_all covers fresh DBs. [backend/migrations/ + backend/*.py,*.sh]
delete frontend unused/heavy deps papaparse/date-fns/react-query/cva/tailwind-merge/radix-dropdown/tabs/tooltip/slot/axios/file-saver/jspdf/xlsx (zero imports). Use fetch + URL.createObjectURL + Intl. [frontend/package.json:16-42]
shrink backend/app/services/currency_service.py class+singleton+noop-context+4 async wrappers + 90% duplicate formatters. Use 2 functions + lru_cache. [backend/app/services/currency_service.py:16-282]
delete backend Global* double-wrap (GlobalDataService/GlobalCacheService/GlobalAnalyticsEngine + FastAPI deps re-wrap). Instantiate DataService(db) directly. [backend/app/services/data_service.py:923-930, cache_service.py:199-206, analytics_engine.py:1357-1364]
shrink backend scikit-learn (StandardScaler 1 use) + stockstats (wrap 1 use) + quantstats (tearsheet 1 use, already null-guarded). Use numpy/pandas ~20 lines. [backend/pyproject.toml:34 + regime_service.py:124, indicators_service.py:121, api/analytics.py:1225]
delete backend triple HTTP stack requests vs aiohttp vs httpx (fastapi[standard] already bundles httpx). Standardize httpx. [backend/pyproject.toml:31-32 + services/alpha_vantage_service.py:34]
yagni backend dead columns/ingest region/primary_source/fallback_source + ingest_bhavcopy/institutional_flow (DATA_NSE_DIR never read) + dual alpha_vantage_api_key(s). Delete fields. [backend/app/models/database.py:20-23, services/india_data_service.py:61-137, config.py:28-32]
delete backend FetchLog write-only audit + 3 full-scan stats (loads all rows, Python success_rate loop) + duplicate inline write. Use single DELETE WHERE expires_at<=now. [backend/app/models/database.py:92-112, services/cache_service.py:98-195, services/data_service.py:808-819]
shrink backend ticker-normalizer x6 (.NS/.BO copies) + _to_thread x4 copies. Import canonical_ticker + asyncio.to_thread. [backend/app/services/data_service.py:39-64, screener_service.py:24-31, alpha_vantage_service.py:44-54, ai_dossier/company/equity/screener _to_thread]
shrink backend close-price triplication _close_series vs _price_series vs _ensure_date_column+_clean_dataframe. One helper in app/utils. [backend/app/services/benchmark_service.py:22-41, api/analytics.py:101-120, services/indicators_service.py:68-91]
shrink backend dual GARCH/EWMA stacks (engine forecast_volatility vs VolatilityService same arch_model+fallback). Keep VolatilityService. [backend/app/services/analytics_engine.py:85-119, services/volatility_service.py:26-330]
stdlib backend hand TTL caches x4 + hand LRU x1 (dict+time.time/timedelta/Lock/id(db) len>64 pop). Use functools.lru_cache. [backend/app/services/data_service.py:97, screener_service.py:47, cointegration_service.py:23, currency_service.py:20, benchmark_service.py:94-108]
delete backend CorrelationService 2 staticmethods forwarding to same-file functions. Keep functions. [backend/app/services/correlation_service.py:151-168]
delete backend benchmark_service thin wrapper+registry (ensure_history/get_benchmark_df/get_returns fetch ^NSEI then slice). Use fetch_benchmark_returns(db,days). [backend/app/services/benchmark_service.py:44-108]
shrink backend bfinance pass-throughs AIDossierService/Screener run_screen vs run_custom_screen dup loops/equity quarterly-yearly dup + graham_upside recompute. Call bfinance from routes + _row(). [backend/app/services/ai_dossier_service.py:26-112, screener_service.py:113-250, equity_research_service.py:35-249]
yagni backend SecurityHeadersMiddleware 6 hand headers + prod-only HTTPS/TrustedHost hardcoded daisy-risk-engine.com + dup /health + trivial /. Use fastapi defaults + single /health. [backend/main.py:30-100,149-168]
shrink backend schemas.py Field(gt/le) + @validator re-checking same bounds + single-use Create/Update subclasses. Use Field only. [backend/app/models/schemas.py:20-55]
yagni backend tests/conftest.py dead fixtures mock_yfinance/mock_portfolio/performance 1000x10/error_config/noop-cleanup/AsyncContextManager/__all__ + mocks of deleted methods. Delete. [backend/tests/conftest.py:37-338,366-475]
stdlib frontend/src/lib/utils.ts cn/generateId(Math.random)/debounce/sleep/isNotNull/capitalize/camelToTitle/truncate/stringToColor + dup formatters (zero app callers). Use crypto.randomUUID/Intl. [frontend/src/lib/utils.ts:6-182]
shrink frontend 10+ duplicate currency/percent formatters + 20x inline toLocaleString(en-IN/en-US) + formatLastUpdated x3. Single formatCurrency/formatPercent/formatRelativeTime. [frontend/src/lib/utils.ts:23, lib/export.ts:472, DataTable.tsx:72, PortfolioTable.tsx:41, Header.tsx:44, LoadingState.tsx:193]
native frontend pass-through Radix dialog/select wrappers zero callers (createElement re-exports). Use primitives directly or native dialog/select. [frontend/src/components/ui/dialog.tsx:14-95, select.tsx:14-83]
shrink frontend LoadingState 7-exports file (dup skeletons in DataTable/MetricCard/PerformanceChart + dead DashboardLoading + hand ErrorBoundary). Use Next loading.tsx + animate-pulse. [frontend/src/components/ui/LoadingState.tsx:14-271]
shrink frontend lib/store.ts AnalyticsStore hand Map 5-min TTL + zero-caller setWebSocketConnection + useCSVExport 3rd CSV impl (vs CSVExporter vs Papa). Use react-query cache. [frontend/src/lib/store.ts:74-418]
yagni frontend types/index.ts 597-line twins APIResponse/MetricCardProps/DataTable*/StoreStale + speculative CurrencyContext/ChartData/VolCone/TailRisk/Coint single-use. Co-locate. [frontend/src/types/index.ts:144-463]
yagni frontend next.config reactCompiler/compress/sourceMaps/onDemandEntries/env re-export + vitest thresholds/reporters/define.global + layout default metadata + Geist vs Arial. Delete blocks. [frontend/next.config.ts:5-40, vitest.config.mts:8-44, app/layout.tsx:5-18]
native frontend DashboardLayout isMobile+resize listener + Header hardcoded Bell/User/admin@ + Sidebar dup icons/descriptions. Use CSS lg: + server component. [frontend/src/components/layout/DashboardLayout.tsx:22-119, Header.tsx:124-189, Sidebar.tsx:33-155]
shrink frontend lib/api.ts 7 namespaces + no-op request.use + hand 422/409 string builder + one-line getConfig/updateConfig/getAiMemoPrompt. Use generic get<T>/post<T> + useQuery. [frontend/src/lib/api.ts:35-526]
delete docker-compose.yml database (sqlite image on 3306)/redis(zero imports)/nginx(missing ./nginx). Keep backend+frontend. [docker-compose.yml:51-93]
yagni .github/workflows/ci-cd.yml 7 jobs (perf needs missing lighthouserc, integration needs missing dir + v1 syntax + missing test:e2e, deploy needs missing k8s/AWS/Slack). Keep backend+frontend. [.github/workflows/ci-cd.yml]
delete scripts/deploy.sh 273-line docker-compose pull/down/up + curl /health (already healthcheck) + prune wrapper, v1 syntax + placeholder registry. Use docker compose up -d --pull always. [scripts/deploy.sh]
delete root doc forks PROJECT.md/ORIGINAL_REQUEST.md/TEST_INFRA.md/RELEASE_NOTES.md (PLANNED vs shipped, frozen R1-R5, dup --cov-fail-under=80). Keep CONTEXT.md. [PROJECT.md, ORIGINAL_REQUEST.md, TEST_INFRA.md, RELEASE_NOTES.md]
delete frontend/assets/index-*.{js,css} committed Vite dist, zero src refs. Gitignore build output. [frontend/assets/]
yagni docs/agents/triage-labels.md 5-row identity map + domain.md refs to missing CONTEXT-MAP/adr/src/<context>. Inline to AGENTS.md + 5-line read-CONTEXT.md. [docs/agents/triage-labels.md, docs/agents/domain.md]
yagni wrapper skills grill-me/grill-with-docs/implement/wait-what/surgical-patch/investigate-first (1-line delegates). Call target directly. [.agents/skills/grill-me, grill-with-docs, implement, wait-what, surgical-patch, investigate-first]
delete .agents/skills/setup-pre-commit (91-line Husky/npm vs 19-line .githooks ruff E9+F). Keep .githooks. [.agents/skills/setup-pre-commit/]
shrink AGENTS.md:21 dual dev tables (optional-deps + dependency-groups needs double sync or tools vanish). Single dev group. [AGENTS.md:21 + backend/pyproject.toml:44-68]

## Net

net: -8000 lines app+infra, -6000 lines docs/reports, -60 skill dirs, -25 deps, -8 compose services possible.

## Sources verified

- backend/pyproject.toml:11-56 (deps), docker-compose.prod.yml:121-226, docker-compose.yml:51-93, frontend/package.json:16-44
- Subagent sweeps: backend/app + tests, frontend/src, root scripts/docs/.agents/skills (read-only, no edits per request)
