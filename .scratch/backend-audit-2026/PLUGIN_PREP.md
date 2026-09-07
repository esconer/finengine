# Plugin-Ready Prep — What To Do Now (Without Building Plugins Yet)
**Date:** 2026-09-03 | **Mode:** doc-only, no code changed
**Reads:** `.scratch/plugin-architecture/01..05` + `BACKEND_REVIEW.md` + `LIBRARY_FIXES.md`
**Decision:** Do NOT build the dynamic plugin loader now. Prepare seams so extraction later is <30 min per plugin.

---

## 1. What the plugin architecture proposes (summary)

- **01 Blueprint:** Open Core + Pluggable Extensions. Kernel = FastAPI gateway + route registry, async SQLite + cache, Next.js shell + theme/auth, lifecycle manager. 4 plugin types: Data Provider (`BaseDataProvider`), Quant Analytics (`BaseQuantModel`), Studio/View (dedicated `/api/v1/plugins/{id}/*` + Sidebar slot), Report/Export (`BaseReportSection`). Backend contract `app/sdk/plugin.py` (`PluginManifest` + `FinEnginePlugin.get_router/on_startup/on_shutdown`); loader `app/core/loader.py` (`pkgutil.iter_modules` + `importlib` + `include_router`); frontend `PluginSlot.tsx` + registry + dynamic Sidebar via `GET /api/v1/plugins`.
- **02 Adapters:** Borrow-don't-reimplement. Riskfolio-Lib / skfolio (quant), QuantStats (tear-sheet), TradingView Lightweight Charts + FINOS Perspective (UI), CCXT (crypto), jugaad-data/NSE (India), OpenBB (universal, AGPL), VectorBT (backtest, Commons Clause). Concrete Riskfolio + QuantStats adapter sketches included.
- **03 Licensing firewall:** Green (MIT/BSD/Apache: Riskfolio, QuantStats, PyPortfolioOpt, skfolio, CCXT, Lightweight Charts) = in-process OK. Yellow (LGPL: NautilusTrader, TA-Lib) = dynamic import only. Red (AGPL OpenBB, Commons Clause VectorBT) = out-of-process sidecar/RPC or BYOK/BYOL only. Plugin boundary = legal firewall.
- **04 Mapping:** 9 services map 1-to-1 to future plugins (`optimization→quant-optimization`, `regime→quant-regime`, `volatility→quant-volatility`, `cointegration→quant-cointegration`, `tail-risk→quant-tail-risk`, `india_data→data-india-flows`, `indicators→indicators-technical`, `ai_dossier→research-ai-dossier`, `export.ts→report-pdf`). Unbundled layout sketched (`app/core`, `app/sdk`, `plugins/*/plugin.py + math.py`, `src/plugins/*`).
- **05 Core-first guide:** Finish core first; 4-step workflow (Math Service → Pydantic DTO → FastAPI route → Props-driven UI); 3 golden rules (pure math, strict schemas, decoupled UI); 7 invariants (100% zero-state weight, HHI/0% single, inv-vol, geometric compounding, `row.original||row`, NSE/BSE+₹/Cr/L/en-IN, zero-mock); M1-M4 checklist; transition trigger (E2E works → cov>80% → tsc clean → extract first plugin).

**Agreement:** 05 is correct. Building `app/sdk/plugin.py` + `app/core/loader.py` + `PluginSlot` + registry now would stall velocity while P0/P1 audit bugs are still open. This doc is the minimal prep layer on top of 05.

---

## 2. What NOT to build now (explicit no-build list)

1. No `app/sdk/`, `app/core/loader.py`, `plugins/` directory, or `get_plugin()` entrypoints.
2. No `GET /api/v1/plugins`, dynamic Sidebar, `PluginSlot`, or `pluginRegistry`.
3. No sidecar Docker for OpenBB/VectorBT, no CCXT/crypto, no Perspective grid, no Lightweight-Charts migration.
4. No plugin manifest/versioning/dependency-resolution system.
5. No multi-seat entitlements (`fastapi-users`) beyond documenting the seam (see §5.6).

If a task PR contains any of the above, reject it as premature.

---

## 3. What to do now — 10 plugin-ready seams (small, reversible)

These are coding disciplines, not framework. Each makes future extraction mechanical.

### 3.1 Keep math pure (strengthen 05 Rule 1)
- Services take DataFrames/arrays/primitives, return dicts/dataclasses. No `Request`, `Response`, `AsyncSession`, `settings`, or HTTP clients inside math functions.
- Current violations to fix as part of P0/P1 anyway: GARCH/HMM `arch`/`hmmlearn` fits inside `async def` (move to `to_thread` at route layer, keep math sync); bhavcopy/FII-DII DB reads mixed with math in `india_data_service.py`; screener `Ticker(...).info` network inside filter loop (hoist fetch → pure filter).
- Test: every math function unit-testable with hand-built frames, no DB/network mocks.

### 3.2 Single cleaned-returns boundary (new — highest leverage)
- All quant plugins will need the same input: inner-joined, drop-NaN active-history returns, no zero-fill, documented daily-rebalanced assumption + 252 annualization.
- Create the convention now (function, not framework): one helper `build_returns_matrix(prices: dict[str, DataFrame]) -> DataFrame` used by optimization/regime/MC/vol/tail/corr/coint/backtest. Fixes inception/survivorship + β→0 + Sharpe-dilution bugs once, benefits all future plugins.
- `pandera` OHLCV schema at ingestion (`LIBRARY_FIXES.md` §4.4) is the entry gate to this boundary.

### 3.3 Schemas as plugin API contracts (strengthen 05 Rule 2)
- Every service I/O already has/will get a Pydantic model in `models/schemas.py`. Treat model names/fields as frozen once shipped (additive-only changes). This is the future `BaseQuantModel` I/O for free.
- Fix now: correlation extra-field drift, `String(10)` vs 20-char tickers, `Literal` enums for statement/freq/format, `None`-vs-`0.0` discipline, `xi_clipped`/`estimated`/`truncated` flags.

### 3.4 Thin routers, fat services (strengthen 05 Step 3)
- Routers do: validate → load positions (holdings-truth) → fetch/cache prices → call pure math → return. No math constants in routers (kill mock-200 `0.20/0.22/25/7.8` as part of P0-6; honest 404/503).
- Future `get_router()` per plugin becomes a cut-paste of the thin router.

### 3.5 Canonical seams: ticker, currency, costs, calendar (new)
- `canonical_ticker()` + G16 securities master (ISIN/NSE/BSE/yf-ticker) in one module; all services import it (kills `.NS`-hardcode, `M&M`/`BAJAJ-AUTO`/numeric drift, first-hit misfires).
- One FX entry (`get_exchange_rate` hoisted per valuation) + en-IN formatting helper; one `costs.py` (STT/stamp/SEBI/GST/impact) for backtest + future EMS (G1/G14); one NSE calendar helper (weekends/holidays/listing-gaps) for annualization/resampling.
- Each seam is a future `core/` kernel service without building `core/` today.

### 3.6 Cache/error/observability conventions (new)
- Single TTL from `settings`; per-key `asyncio.Lock` single-flight; SQLite upsert (not blind-insert); per-task `AsyncSession` (never shared); `tenacity` retry + `aiolimiter` gate; `structlog` JSON + `exc_info` + request-id.
- Future `PluginLifecycleManager.on_startup/on_shutdown` (cache warmup/preload) maps directly to these conventions.

### 3.7 Props-driven UI (strengthen 05 Rule 3 + Step 4)
- Charts/tables take props, read `row.original || row`, bind `{tickers,matrix}` as headers + `matrix[i][j]`, format ₹/Cr/L en-IN, handle `null` + `insufficient_data` (never fabricate single-obs cone bounds).
- Future `PluginSlot` is then just a prop-passing wrapper.

### 3.8 Library hygiene through plugin lens (from 02 + 03 + LIBRARY_FIXES)
- Green in-process now or later: `skfolio` **or** `riskfolio-lib` (one, not both), `arch`, `statsmodels`, `quantstats` (selective), `cachetools`/`async-lru`, `pandera`, `structlog`, `tenacity`/`aiolimiter`/`slowapi` (HTTP), `joserfc`, `tiktoken`, `yahooquery` complement, `ta` only if needed, `ruptures` complement, `pyextremes` diagnostics last.
- Red stays out-of-process forever: OpenBB AGPL sidecar/RPC or not at all; VectorBT Commons Clause BYOL or not at all. Never `copulas` (BUSL), `cvxportfolio` (GPL), `backtesting.py` (AGPL), `finta`/tulind-backend (LGPL + accuracy/build).
- NSE data behind `MarketDataProvider` adapter interface now (bfinance→yfinance→AV primary; `jugaad-data` **or** `nsepython` stopgap, never both direct-imported). Budget authorized vendor G2.

### 3.9 Test seams = extraction safety net
- Contract tests per future plugin boundary: HRP odd-N, CVaR positive-loss VaR, Sortino hand-check, EWMA vs RiskMetrics, turnover one-way, Sharpe mean-based, regime Series path, coint collision pair, EVT no-mock, copula PIT, GARCH persistence, ticker regex (`3MINDIA.NS`/`MOTHERSON.NS`/`BAJAJ-AUTO.NS`/`500112.BO`), cache upsert-hit, screener universe isolation, dossier injection/format/symbol-confirm.
- Coverage gate (>80%) + `tsc --noEmit` clean stay as transition triggers (05 §6).

### 3.10 Docs seam: plugin mapping stays alive
- Keep `04-current-codebase-plugin-mapping.md` updated as services change (new services → new rows). This doc + that mapping = extraction backlog. No code needed.

---

## 4. Per-service extraction readiness (from 04 mapping + audit state)

| Future plugin | Current source | Ready? | Prep task (no loader) |
|---|---|---|---|
| `quant-optimization` | `optimization_service.py` + `backtest_service.py` | No (P0-1 HRP, P1 CVaR/Sortino/EWMA/target-vol/turnover/Sharpe) | Fix math P0/P1 → adopt skfolio **or** riskfolio → `costs.py` seam → schemas frozen |
| `quant-regime` | `regime_service.py` | No (price/return P0, HMM priors/lookahead/scaling) | 1d features + expanding scaler + honest priors + filtered last-bar + `ruptures` complement |
| `quant-volatility` | `volatility_service.py` + engine GARCH/EWMA | Partial (formulas sound, winsorize/dist/persistence gaps) | `clip(±20%)` + `dist='t'` + `α+β<1` + memo + `to_thread` |
| `quant-cointegration` | `cointegration_service.py` | No (P0 cache collision, OU branch, ADF gaps) | Full-ticker key migration → OU/RankWarning → ADF gate → pooled-ν → LedoitWolf |
| `quant-tail-risk` | `tail_risk_service.py` | Partial (McNeil formulas sound, mock fallback) | `insufficient_data` + ξ flag → Kendall-ρ + ν-MLE → `pyextremes` diagnostics last |
| `data-india-flows` | `india_data_service.py` + `currency_service.py` | No (coercers, series-dedupe, N+1, ADV-NaN, FX stale) | Safe coercers + `(symbol,series)` UQ + single-`IN` + `pd.isna` ADV + FX nested-try/stale/raise + provider adapter |
| `indicators-technical` | `indicators_service.py` | Partial (causal confirmed) | No-bfill clean + SMA200 warmup + canonical ticker + `shift(1)` discipline |
| `research-ai-dossier` | `equity_research/screener/ai_dossier` + bfinance | No (CFO key, EV-cash, F6/F8 proxies, units, universe/cache, injection) | Key/unit fixes → real debt filter + rank + universe/cache → sanitize/cap/confirm-symbol/citations/disclaimer/cache; quarantine synthetics |
| `report-pdf` | `export.ts` + tear-sheet | Partial | Live-data binding + sheet-name/content fix + temp/cap/rate-limit |

Do these prep tasks in Sprint 1-4 order (`BACKEND_REVIEW.md` §7). Extraction order later: cointegration or volatility first (smallest, per 05 §6), optimization last (largest).

---

## 5. Transition trigger — when to actually build the loader (unchanged + quantified)

Build `app/sdk/plugin.py` + `app/core/loader.py` + `PluginSlot` only when ALL hold:
1. E2E runs: add holdings → risk metrics → optimization → PDF export (05 §6.1).
2. `pytest` passes with total coverage >80% (`--cov-fail-under=80`).
3. `bun x tsc --noEmit` zero errors + Vitest green.
4. P0 zero open; P1 zero in quant paths (envelopes honest, no mocks).
5. One service passes the "30-minute extraction test": copy `math.py` + schemas + thin router into `plugins/<id>/` shape without edits to math.

At that point follow `01-blueprint` verbatim for `plugins/quant-cointegration/` first.

---

## 6. Checklist for every new feature PR (plugin-ready gate, no framework)

- [ ] Math pure (no Request/DB/HTTP/settings inside)? Unit-testable with hand frames?
- [ ] Returns via cleaned-returns boundary (inner-join, active-history, no zero-fill)? 252 documented?
- [ ] Pydantic I/O added, additive-only, `None`-vs-`0` honest, `Literal` enums, flags (`estimated`/`xi_clipped`/`insufficient_data`)?
- [ ] Router thin (validate → holdings-truth → fetch/cache → math)? Honest 404/503/429, no mock constants?
- [ ] Ticker via `canonical_ticker`/master, ₹/Cr/L en-IN, `3MINDIA.NS`/`500112.BO` covered?
- [ ] Cache: upsert + per-key lock + single TTL + per-task session? No shared session, no blind-insert?
- [ ] UI props-driven, `row.original\|\|row`, `{tickers,matrix[i][j]}`, null-safe, no `Math.random`?
- [ ] Green-zone libs only in-process; red-zone libs absent or behind adapter/sidecar note?
- [ ] Contract test added mapping to future plugin row in 04-mapping?
- [ ] No `plugins/`, `app/sdk`, loader, registry, sidecar, or manifest in this PR?

---

*No source files modified. Next: execute BACKEND_REVIEW Sprint 1-4 with this gate on every PR; keep 04-mapping updated; build the loader only on §5 trigger.*
