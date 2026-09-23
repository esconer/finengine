# 06 — Config, Build, Tests & Cross-Cutting Audit

Wave-2 status: fixed=12 · verified-open=17 · partial=1 · skipped=1 · total=31

| Field | Value |
|---|---|
| **ID** | 06 |
| **Date** | 2026-09-23 |
| **Scope** | `frontend/package.json`, `next.config.ts`, `vitest.config.mts`, `tsconfig.json`, `eslint.config.mjs`, `postcss.config.mjs`, `.env.local`, ALL of `frontend/src/test/**`, cross-cutting sweeps across `frontend/src` (locale, invariants, error UX, security, i18n, a11y, perf/config) |
| **Mode** | READ-ONLY — this report is the only file written |
| **Commands run** | `bunx tsc --noEmit` → **exit 0, clean** · `bun run test:run` → **16 files / 88 tests, all pass, 34.06 s** (transform 24.03 s dominant; bun wrote a NativeCommandError wrapper on stderr — noise only, EXIT=0) · `bun run lint` → **exit 1, 317 problems (1 error, 316 warnings)**; first attempt produced no output within 180 s timeout, full run completed only at a 420 s budget |
| **Invariant baseline** | Root `AGENTS.md` "Quantitative & Terminal UI Invariants" (lines 31–41) |

Severity: **P0** = crash/security/data loss · **P1** = real bug or invariant violation · **P2** = improvement worth doing · **P3** = nit.

---

## 1. Bugs

### Invariant sweep — verdict summary (evidence first)

| Invariant (AGENTS.md) | Result | Evidence |
|---|---|---|
| `en-IN` for ₹/Cr/L money | ❌ **4 product violations** | 06-B1 |
| Zero-state weight = 100.00% | ✅ compliant | `AddPositionModalSimple.tsx:77-79` sets `weight: 1.0` when `existingCount === 0 \|\| totalPortfolioValue <= 0` (but see 06-B6) |
| HHI diversification, N≤1 → 0% | ✅ compliant | `dashboard/page.tsx:106` `if (positions.length <= 1) return 0;`; HHI at `:113`, N_eff at `:114`; test `DashboardPhase4.test.tsx:109` |
| Inverse-vol risk parity (frontend) | ✅ n/a — computed backend-side | no frontend weight math for vol sizing |
| TanStack `row.original \|\| row` | ✅ compliant | 51 cell callbacks across 9 pages all use `const data = row.original || row;` (grep `row.original` = 51 hits, `accessorKey` cell pages: realized-risk, dashboard, concentration, liquidity, volatility-sizing, factor-exposure, stress-testing, forecast-risk, screener-studio) |
| Ticker regex hyphen support | ✅ compliant | `AddPositionModalSimple.tsx:94` `/^[A-Za-z0-9\-\&\.]{1,20}$/` — hyphen, dot, `&` all pass (`BAJAJ-AUTO.NS`, `500112.BO`) |
| No fabricated constants / mock deltas in product | ❌ **1 violation** | 06-B2; `0.12/0.22/0.45`, `0.679/1.083`, `-41.9` etc. appear **only in tests** (grep confirmed) — good |
| Metric card hygiene (no placeholder deltas) | ⚠️ mostly ✅ | only `dashboard/page.tsx:340` passes `change=` at all — no mock deltas shipped; but 06-B2 fabricates whole card values on error |
| `Mock`/`faker` in product code | ✅ none | grep `faker|Mock[A-Z]` → 0 hits outside `src/test/**` |
| `dangerouslySetInnerHTML`/`eval`/`new Function` | ✅ none | grep → 0 hits |
| External links `rel`/`target` | ✅ compliant | all 3 `target="_blank"` sites carry `rel="noreferrer"` (`equity-research/page.tsx:311,892,903`) |
| Secrets in `NEXT_PUBLIC_*` / `.env.local` | ✅ clean | `.env.local` = telemetry flag + `NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1` only |
| Error boundaries in `src/app/` | ❌ absent | glob `{error,not-found,global-error,loading,template}.tsx` → **0 files** → 06-B7 |

**Wave-1 sweep re-verification:** all 14 row verdicts stand against current code; evidence corrections needed: (a) fabricated-constants row: -41.9/-17.3/-28.8/-23.4 exist in product source at stress-testing/page.tsx:362,371,380,389 (default scenario metadata, never rendered; cards/badges show only live result.portfolio_impact) so the only-in-tests wording is false, though the ❌ 1-violation verdict still rests solely on 06-B2; (b) TanStack row: 52 cell: callbacks exist across the 9 pages; 51 use `const data = row.original || row;`, the 52nd (screener-studio/page.tsx:189) is an index-only cell reading info.row.index (still compliant), so the count needs a footnote; (c) correct en-IN site count is 31 lines (28 toLocaleString en-IN + 3 Intl.NumberFormat en-IN), not 27; (d) HHI test citation DashboardPhase4.test.tsx:109 asserts 1-decimal rendering (100.0%), not the N<=1 -> 0% branch; that branch (dashboard/page.tsx:106) is the real evidence and is compliant; (e) no row exists for the AGENTS.md Deterministic Return Compounding invariant (frontend does no monthly-return grouping; backend-side, N/A).

---

**06-B1 — P1 — Indian money formatted with `en-US` locale (invariant violation)**
Four product files render `₹` + `Math/amount.toLocaleString('en-US', …)` → US grouping (`₹1,250,000` instead of `₹12,50,000`) on core portfolio screens:
- `components/portfolio/PortfolioTable.tsx:43` — `symbol = currency === 'INR' ? '₹' : '$'` then `.toLocaleString('en-US', …)`
- `components/portfolio/PortfolioStats.tsx:80` — same pattern
- `app/portfolio/manage/page.tsx:335` — same pattern
- `components/portfolio/EditPositionModal.tsx:173` — `{currency === 'INR' ? '₹' : '$'}{currentValue.toLocaleString('en-US', …)}`

Cross-ref (other auditor's file): `lib/export.ts:121,462,473` also hardcode `en-US` (and `formatCurrency(value, currency='USD')` at `:472-477`).
Correct pattern already exists in-repo: `lib/utils.ts:26` (`Intl.NumberFormat('en-IN', …)`), used correctly by `dashboard/page.tsx:192,339`, `liquidity/page.tsx:346-348`, `equity-research/page.tsx:201,362`, etc. — 27 correct `en-IN` sites vs 4+3 wrong.
**Fix:** replace local formatters with `formatCurrency`/`en-IN`; one helper, four call sites.

Status: fixed — end-of-work re-grep `toLocaleString('en-US'` in portfolio components = 0 product money sites; PortfolioTable/PortfolioStats/EditPositionModal all route through `formatCurrency` (en-IN); manage:335 site gone; export.ts formatters fixed by 2A (04-B8).

**06-B2 — P1 — Liquidity page fabricates fallback metrics on API failure and shows them as live (invariant violation)**
`app/dashboard/liquidity/page.tsx:298-310`: the `catch` sets `liquidityData` to a **hardcoded mock** — `overall_score: 7.8`, `risk_level: 'Low'`, `liquidation_time_days: '1-2'`, `volume_stats: {avg_volume: 5000000, high/medium/low 60/30/10}`. The hero badge (`:565` `formatScore(overallScore)`) and the 4 metric cards (`:618-667`, gated only by `!loading`, **not** by `error`) then render `7.8/10`, `Low`, `1-2 days` alongside/behind an error banner (`:593`). An error state must render N/A, never invented numbers. Additional fabricated fallbacks in the same file: per-row `liquidation_days`/`category`/`spread` defaults at `:283-288`, and `formatCurrency(null) → '₹0'` at `:343`.
`LiquiditySkeleton.test.tsx` covers the *loading* path but **not** the error path — coverage gap that let this ship.
**Fix:** on error keep `liquidityData = null`, show the error banner only; cards render `N/A` (they already do when `liquidityData` is null — `:635,:647`).

Status: fixed — catch liquidity/page.tsx:308-313 sets `setLiquidityData(null)` + `setPositionData([])` + error banner (no 7.8 mock); per-row defaults use `?? null` with N/A formatters; formatCurrency(null) → N/A; error-path covered by FabricatedFallbacks/01-B1.

**06-B3 — P1 — Silent `catch` blocks hide data failures from the user (≥7 pages)**
Pattern: `console.error(...)` only, no `setError`, no notification, stale/empty state rendered as if valid:
- `app/dashboard/factor-exposure/page.tsx:298-302` — factor data fetch fails → page shows previous/empty state, no banner (compare: same file has no `error` state at all)
- `app/dashboard/concentration/page.tsx:402-406` — same
- `app/dashboard/forecast-risk/page.tsx:441-446` — `setPositionData([])` + silent; metric cards fall to N/A with no error banner
- `app/dashboard/stress-testing/page.tsx:424-428` and `:442-444` — single-scenario failure silent; `runAllScenarios` **drops failed scenarios and then activates `scenarios[0]` anyway** (`:447-449`), so UI shows partial results with no indication any scenario failed
- `app/dashboard/page.tsx:266-268` — CSV export fails → button does nothing, no message
- `app/dashboard/equity-research/page.tsx:173-176,185-187` — AI Memo/Forensic buttons dead-end on error (`console.error(err)` only)
- `app/dashboard/india-flows/page.tsx:17-19` — each request `.catch(() => ({ data: { flows: [] } }))` → API outage renders as a valid **empty** flows/anomalies table; user cannot distinguish "no flows" from "backend down"

A toast system already exists (`components/ui/NotificationSystem.tsx` + `hooks/useRealTime.ts:209-305 useNotifications`) but is wired **only** to websocket connection events (`NotificationSystem.tsx:136-144`). No page calls it for fetch errors (grep `useNotifications` in `src/app` → 0).
**Fix:** every fetch `catch` sets an `error` state or pushes `addNotification`; india-flows must not swallow into empty arrays.

Status: partial-fixed — per-page catches in reports 01–03 now set error states/banners (factor-exposure still console.error-only at :309 when no error state exists; stress-testing partial-fail still drops scenarios). india-flows no longer swallows into empty arrays. Residual handoff: remaining silent catches in factor-exposure/stress-testing sweep.

**06-B4 — P2 — Lint is red: `bun run lint` exits 1**
1 error: `components/portfolio/PortfolioDropzone.tsx:85` — `'dateIdx' is never reassigned. Use 'const' instead` (`prefer-const`). Plus 316 warnings (mostly `no-explicit-any`, `no-unused-vars` — e.g. unused imports in `test/setup.ts:2`, `EquityResearch.test.tsx:5`, stale eslint-disables in `DashboardPhase4.test.tsx:13`, `DashboardVolTimestamp.test.tsx:14`). Any future CI gate would fail on day one. Evidence: command output `✖ 317 problems (1 error, 316 warnings) … script "lint" exited with code 1`.

Status: fixed — `PortfolioDropzone.tsx:85` `let dateIdx` → `const dateIdx`; scoped `bunx eslint` on the file = 0 errors; full `bun run lint` = **0 errors, 291 warnings, exit 0** (baseline was 1 error/316 warnings/exit 1). Warnings out of scope (setup.ts unused imports fixed as part of 06-B9).

**06-B5 — P2 — API rewrite hardcodes `localhost:8000`, diverges from `NEXT_PUBLIC_API_URL`**
`next.config.ts:31-33` rewrites `/api/v1/* → http://localhost:8000/api/v1/*`, while axios uses `process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'` (`lib/api.ts:37`, `.env.local:3`). The rewrite is exercised by `app/dashboard/page.tsx:254` (`fetch('/api/v1/portfolio/export/csv')`). If the backend ever runs on another host/port (docker, staging, prod), axios follows the env var but the CSV export still hits localhost → silent export failure (compounds 06-B3).
**Fix:** rewrite destination = `process.env.BACKEND_URL ?? 'http://localhost:8000'`.

Status: fixed — `next.config.ts` `rewrites()` now derives `backendOrigin` from `process.env.NEXT_PUBLIC_API_URL` (strip `/api\/v1`, fallback `http://localhost:8000`), so the rewrite follows the same env axios uses; behavior unchanged under `.env.local` default.

**06-B6 — P2 — Add-position weight can silently become 100% on a non-empty portfolio**
`components/portfolio/AddPositionModalSimple.tsx:43-47`: if `getPortfolio` fails, catch sets `existingCount = 0, totalPortfolioValue = 0`. The auto-weight effect (`:77-79`) then takes the "first position in an empty portfolio" branch and sets `weight: 1.0` — even when the portfolio actually has holdings. Validation `:107` passes (`weight <= 1`), submit proceeds; user has just created a position claiming 100% of the book. Zero-state invariant is honored *literally* (100%) but under a false premise.
**Fix:** on summary-fetch failure, disable submit or leave weight unset and flag an error instead of defaulting to `1.0`.

Status: fixed — catch sets `fetchError=true` and leaves `portfolioLoaded=false`; auto-weight effect early-returns until a successful fetch; `handleSubmit` rejects when `fetchError` (AddPositionModalSimple.tsx:133-135), so weight cannot silently become 1.0 on a non-empty book.

**06-B7 — P2 — No route-level error boundaries; the one ErrorBoundary in the codebase is dead**
Glob `src/app/**/{error,not-found,global-error}.tsx` → **0 files**. `components/ui/LoadingState.tsx:229` exports a working `ErrorBoundary`, but grep `<ErrorBoundary` across `src` → **0 usages**. Any render-time throw on a dashboard page falls to Next's built-in default error page (unstyled, no recovery UI, no reporting hook). No `not-found.tsx` either → 404s get the bare Next default.
**Fix:** add `app/error.tsx`, `app/not-found.tsx`, `app/global-error.tsx`; or wrap page content with the existing `ErrorBoundary` (ladder rung 2 — it's already written).

Status: fixed — created `src/app/error.tsx`, `src/app/not-found.tsx`, `src/app/global-error.tsx`; regression tests in `src/test/crosscutting/ErrorSurface.test.tsx` (message + reset, generic fallback, 404 link). `LoadingState.tsx:229` ErrorBoundary export left untouched (mount/delete decision deferred to 06-I4, batch E owns that file).

**06-B8 — P2 — Native `alert()`/`confirm()` scattered across the app**
6 sites: `equity-research/page.tsx:160`, `volatility-sizing/page.tsx:340,361`, `screener-studio/page.tsx:169`, `stress-testing/page.tsx:458`, `settings/page.tsx:96` (`window.confirm` for cache purge — destructive action behind a blocking dialog). Blocking, unstyleable, inconsistent with the toast system that already exists. Tests paper over this (`Settings.test.tsx:38,91` mock `window.confirm`).
**Fix:** route through `useNotifications` / a confirm dialog built on the existing Radix `dialog.tsx`.

Status: fixed — all product `alert()` sites removed; only `window.confirm` remains at settings:101 for the destructive cache purge (accepted as intentional blocking confirm for that path).

**06-B9 — P2 — Test setup globally silences `console.error`/`warn`**
`src/test/setup.ts:69-73`: `global.console = { ...console, warn: vi.fn(), error: vi.fn() }`. Every React warning, act() violation, and unhandled-rejection log across all 88 tests is swallowed — so warning regressions (including ones that would surface the exact invariant issues in this report) are invisible. Also makes "did the code log an error?" unassertable.
**Fix:** remove the override; if noise is the concern, assert-and-silence per test.

Status: fixed — removed the `global.console` warn/error override from `src/test/setup.ts` and trimmed unused vitest imports (`expect, describe, it, beforeEach`); console noise now visible in test output (confirmed in the post-fix `bun run test:run` run).

**06-B10 — P3 — `MetricCard` defaults currency to `$` and the test suite enshrines it**
`components/ui/MetricCard.tsx:36`: `const sym = prefix !== undefined ? prefix : '$'` — any numeric `value ≥ 1000` passed without `prefix` renders `$1.2K`. Only `app/dashboard/page.tsx:333` passes `prefix="₹"` (grep `prefix=` → 1 hit). `MetricCard.test.tsx:111,120,374` assert `'$1.2K'`/`'$1.2M'`, locking the USD default into a ₹-first product; `MetricCard.test.tsx:301` further locks the ugly `'$1000000.0M'` (no trillion tier). Current call sites mostly pass pre-formatted strings, so this is **latent**, not yet shipped on-screen.
**Fix:** default prefix to `''` (no symbol) and format per `currency` prop; update the tests.

Status: fixed — `prefix === undefined` now renders bare `en-IN` number (MetricCard.tsx:35-36); `$`/K/M path only when an explicit non-₹ prefix is passed; N/A for non-finite values (:32-33).

**06-B11 — P3 — `DataTable` default formatters are USD/`-` while the app standard is N/A/`en-IN`**
`components/ui/DataTable.tsx:72-77` default `formatCurrency` = `Intl.NumberFormat('en-US', currency:'USD')`; empty token is `'-'` (`:81,90,94,98,100`) whereas MetricCard and every dashboard page use `'N/A'`. Two empty-state tokens and two currency conventions in one design system. (Ugly, not yet wrong — current pages pass their own cell renderers.)

Status: verified — DataTable.tsx:72-77 default formatCurrency is en-US/USD; empty token - at :81,:90,:94,:98,:100.

**06-B12 — P3 — Dead no-op string replaces**
`lib/utils.ts:34`: `return formatted.replace('₹', '₹').replace(',', ',');` — replaces each string with itself (and only the *first* comma anyway). Misleading comment implies normalization work.

Status: fixed — removed the no-op `.replace('₹','₹').replace(',',',')` and misleading comment from `lib/utils.ts` `formatCurrency`; widened signature to `number | null | undefined` with a null/undefined/NaN → `'N/A'` guard (valid `0` still renders a real zero). Regression tests in `src/test/unit/format-invariants.test.tsx` (INR grouping + N/A + MetricCard NaN/null).

**06-B13 — P3 — Parse error can surface to the user as raw JSON**
`components/portfolio/PortfolioDropzone.tsx:167`: `setParseError(typeof msg === 'string' ? msg : JSON.stringify(msg))` — non-string errors dump `JSON.stringify` into the visible error text.

Status: verified — PortfolioDropzone.tsx:167 falls back to JSON.stringify(msg) for non-string parse errors.

---

## 2. Improvements (system design + QA strategy)

**06-I1 — P1 — There is no CI at all**
Glob `.github/workflows/*`, `.gitlab-ci.yml`, `azure-pipelines.yml`, `Jenkinsfile`, `bitbucket-pipelines.yml`, `.circleci/**` → **0 files**. Root `AGENTS.md:27` explicitly defers `tsc`/`vitest` to "manual + CI (too slow for commit time)" — but the CI half doesn't exist, so today the gates are whatever a human remembers. Combined with 06-B4 (lint red), nothing prevents the next invariant regression.
**Recommended gates (in order, each a separate job):** `bunx tsc --noEmit` (~30 s, currently green) → `bun run test:run` (~34 s, currently green) → `bun run lint` (fix the 1 error first) → `bun run test:coverage` once thresholds are made realistic (06-I3).

Status: skipped — CI workflow deferred to a separate PR per root AGENTS.md:27 (`tsc`/`vitest` stay manual + CI, too slow for commit time). Pre-commit hook already runs scoped `ruff` for backend; frontend CI not in this batch's owned files.

**06-I2 — P2 — Test coverage map (this is the QA-strategy picture)**
16 test files / 88 tests. Good: invariant-focused suites (`FabricatedFallbacks` 9 tests, `LiquiditySkeleton`, `DashboardPhase4`, `TearSheetPhase3`) directly encode AGENTS.md invariants — exactly the right strategy; keep adding these.

*Pages (21 route pages + 2 layouts):*

| Page | Test file(s) |
|---|---|
| `dashboard/page` | DashboardPhase4, DashboardVolTimestamp |
| `dashboard/volatility-sizing`, `forecast-risk`, `risk-studio`, `concentration`, `factor-exposure`, `stress-testing` | FabricatedFallbacks (negative-path only) |
| `dashboard/tear-sheet` | TearSheetPhase3 |
| `dashboard/realized-risk` | RealizedRiskBanner |
| `dashboard/liquidity` | LiquiditySkeleton (loading only — miss = 06-B2) |
| `dashboard/equity-research` | EquityResearch (1 smoke test) |
| `dashboard/screener-studio` | ScreenerStudio (1 smoke test) |
| `dashboard/monte-carlo` | MonteCarloCopy (copy only) |
| `dashboard/settings` | Settings (4) |
| **`dashboard/optimize`** | **none** |
| **`dashboard/risk-contribution`** | **none** |
| **`dashboard/regime`** | **none** |
| **`dashboard/pairs`** | **none** |
| **`dashboard/india-flows`** | **none** (and it has the swallow-into-empty bug, 06-B3) |
| **`portfolio/manage`** | **none** (847 lines, add/edit/delete + en-US money bug) |
| `app/page` (redirect) | none — trivial, fine |
| `dashboard/layout`, `layout` | none |

*Components:* tested = `Sidebar`, `MetricCard`, `DataTable`, `AddPositionModalSimple` (4). **Zero tests:** `Header`, `DashboardLayout`, `PortfolioTable`, `PortfolioStats`, `PortfolioDropzone`, `EditPositionModal`, `CurrencySelector`, `PortfolioFilters`, `ExportPanel`, `NotificationSystem`, `LoadingState`/`ErrorBoundary`, `dialog`, `select`, `PerformanceChart`, `SectorAllocationChart`, `RiskMetricsDisplay` (1 incidental case inside FabricatedFallbacks).

*Logic:* tested = `lib/utils` (9), `lib/store` (9). **Zero tests:** `lib/api.ts`, `lib/export.ts` (CSV/PDF/Excel — the file another auditor owns, includes formula-injection surface), `lib/websocket.ts`, `hooks/useRealTime.ts`, `hooks/useAnalytics.ts`, all page-local fetch/format logic (locale formatters of 06-B1 live in untested per-page helpers).

Status: verified — 16 test files (14 tsx + 2 ts) / 88 tests (baseline); no test file exists for optimize, risk-contribution, regime, pairs, india-flows, or portfolio/manage; FabricatedFallbacks has 9 it() blocks; Settings has 4; components tests limited to Sidebar/MetricCard/DataTable/AddPositionModalSimple; manage/page.tsx is 847 lines; zero-test component/logic lists match the file inventory.

**06-I3 — P2 — Coverage thresholds exist but are unenforced and almost certainly unmeetable today**
`vitest.config.mts:23-30` sets global 80% branches/functions/lines/statements — good instinct — but thresholds only apply to `test:coverage`, which nothing runs (no CI, 06-I1). With 4/18 components and 6 pages at zero coverage, a first `bun run test:coverage` will very likely fail the 80% bar. Either (a) run coverage once, set the bar at the measured floor, and ratchet up per PR, or (b) keep 80% aspirational but gate changed-files coverage instead.

Status: verified — vitest.config.mts:23-30 sets 80% global thresholds, only the test:coverage script runs them, and nothing runs coverage (no CI, 06-I1).

**06-I4 — P2 — Error-boundary architecture (design recommendation)**
Three layers, currently 1/3 built: (1) route boundaries `app/error.tsx` + `not-found.tsx` + `global-error.tsx` — **missing** (06-B7); (2) page-level fetch errors — inconsistent (good exemplars: `dashboard/page.tsx:276-284`, `liquidity/page.tsx:593-607`, `tear-sheet/page.tsx:454`; anti-exemplars in 06-B3); (3) component `ErrorBoundary` — **written but never mounted** (`LoadingState.tsx:229`). Converge on: every page owns an `error` state rendered as the standard red banner + Try Again (the liquidity/tear-sheet pattern), route boundaries as backstop, and either mount the existing `ErrorBoundary` around chart/table subtrees or delete it (YAGNI).

Status: verified — exemplars dashboard/page.tsx:276-288, liquidity:593-607, tear-sheet:454-469 confirmed; ErrorBoundary (LoadingState.tsx:229) has 0 usages; route boundaries absent (06-B7).

**06-I5 — P2 — Centralize user-facing failure messaging**
06-B3's fix is architectural, not a 12-line patch per page: pick one channel — `useNotifications().addNotification` (exists, `useRealTime.ts:227`) or a small `useErrorBanner(pageKey)` — and require it in review for every `catch`. `alert()` removal (06-B8) falls out of the same change.

Status: verified — addNotification at useRealTime.ts:227; useNotifications imported only by NotificationSystem (0 hits in src/app); the alert/confirm sites (06-B8) are unserved by it.

**06-I6 — P3 — i18n / copy assessment (assessed, not demanded)**
- All copy is hardcoded English — fine for now; i18n would be a large refactor, not flagged as a defect.
- Real inconsistencies worth fixing *pre-i18n*: empty token `N/A` (MetricCard, all pages) vs `'-'` (DataTable defaults) vs `'₹0'` (liquidity `formatCurrency(null)`) vs silent empty array (india-flows) — 4 different answers to "no data". Pick `N/A`.
- Money formatting is reimplemented in ≥8 local `formatCurrency` helpers (PortfolioTable, PortfolioStats, manage, liquidity, equity-research, screener, volatility-sizing, export) instead of `lib/utils.ts:23` — consolidation is prerequisite to any i18n work and fixes 06-B1 in one place.
- Dates: `toLocaleDateString('en-US')` in `PerformanceChart.tsx:42,93` — acceptable (display dates, not money).

Status: verified — enumeration correction: the 4 empty tokens are confirmed (MetricCard N/A, DataTable -, liquidity ₹0 at :343, india-flows silent empty arrays) and PerformanceChart.tsx:42,93 use toLocaleDateString en-US, but the equity-research/screener local helpers are named formatCr (:196/:175), while DataTable:72 and PerformanceChart:82 also define local formatCurrency helpers missing from the list; substance (>=8 local money helpers) holds.

**06-I7 — P3 — Duplicate `<h1>` on every dashboard page**
`components/layout/Header.tsx:81` renders the app title as `<h1>` inside `DashboardLayout` (`DashboardLayout.tsx:156`), and every page then renders its own `<h1>` (grep: 21 page-level `<h1>`s — e.g. `dashboard/page.tsx:299`, `liquidity/page.tsx:551`). Two `h1`s per screen. Landmarks themselves are fine: `<header>` (`Header.tsx:62`), `<main>` (`DashboardLayout.tsx:163`), `<nav>` (`Sidebar.tsx:210`). Images: no `<img>` tags and no `next/image` anywhere — alt-text risk currently zero by absence. Root `app/page.tsx` is a pure redirect — no `h1` needed.

Status: verified — count correction: Header.tsx:81 h1 inside DashboardLayout (:156), main :163, nav Sidebar:210 all confirmed, but there are 20 page-level h1s (21 total including Header), not 21 page-level; the duplicate-h1 finding holds for all 20 layout pages.

**06-I8 — P3 — Hand-rolled modal duplicates existing Radix dialog**
`AddPositionModalSimple.tsx:167-174`: fixed overlay div with no `role="dialog"`, no `aria-modal`, no Escape handling, no focus trap; close-on-overlay-click only. `components/ui/dialog.tsx` (Radix) already exists in the codebase — AGENTS.md rung 2 says reuse it.

Status: verified — AddPositionModalSimple.tsx:167-174 is a fixed overlay with close-on-click only (no role, no aria-modal, no Escape, no focus trap); Radix dialog.tsx exists at components/ui/dialog.tsx.

**06-I9 — P3 — Color-only status encoding: currently acceptable, keep it that way**
`text-red`/`text-green` appear widely, but spot-checks show non-color signal present: P&L carries `+`/`-` (`EditPositionModal.tsx:182`, `MetricCard.tsx:58`), risk levels are text labels (`High/Medium/Low/N/A`), change pills carry signed percentages. No current WCAG 1.4.1 violation found in sampled surfaces — record as an invariant for future badges (dot-only indicators would be a regression).

Status: verified — spot checks hold: signed P&L at EditPositionModal.tsx:182-184, signed change at MetricCard.tsx:58-59, text risk labels; no dot-only status indicators found.

---

## 3. Optimizations

**06-O1 — P2 — Dead dependencies in `package.json` (grep = zero imports in `src`)**
| Dep | Evidence |
|---|---|
| `class-variance-authority` (deps) | no import anywhere; `cn` = clsx only (`utils.ts:13`) |
| `tailwind-merge` (deps) | no import; also listed in `optimizePackageImports` (`next.config.ts:21`) despite never being imported |
| `date-fns` (deps) | no import anywhere; listed in `optimizePackageImports` (`next.config.ts:17`) |
| `papaparse` (deps) | no import anywhere; listed in `optimizePackageImports` (`next.config.ts:23`) |
| `@radix-ui/react-dropdown-menu`, `react-tabs`, `react-tooltip`, `react-slot` (deps) | only `react-dialog` (`dialog.tsx:6`) and `react-select` (`select.tsx:6`) are imported |
| `babel-plugin-react-compiler` (devDeps) | `next.config.ts:5` sets `reactCompiler: false // Disabled for stability` — plugin installed but inert |

Status: verified — grep for class-variance-authority, tailwind-merge, date-fns, papaparse, react-dropdown-menu, react-tabs, react-tooltip, react-slot in src yields 0 hits; only @radix-ui/react-dialog (dialog.tsx:6) and @radix-ui/react-select (select.tsx:6) are imported; next.config.ts:5 sets reactCompiler false with babel-plugin-react-compiler 1.0.0 at package.json:52; line-note: papaparse sits at next.config.ts:22 (report cites 23, off by one).

**06-O2 — P2 — Test tooling lives in production `dependencies`**
`package.json:25-27,41`: `@testing-library/jest-dom`, `@testing-library/react`, `@types/file-saver`, and **`vitest` itself** are in `dependencies` (lines 25,26,27,41) instead of `devDependencies`. `vitest` alone pulls a large tree into any `npm/bun install --prod`-adjacent artifact. (`@vitejs/plugin-react`, `jsdom`, `@vitest/ui` are correctly dev-only.) Move the four.

Status: verified — package.json:25,26,27,41 put jest-dom, @testing-library/react, @types/file-saver, and vitest in dependencies; @vitejs/plugin-react (:50), jsdom (:54), @vitest/ui (:51) are correctly dev-only.

**06-O3 — P2 — Test runtime: 34 s wall, transform-dominated**
Command output: `Duration 34.06s (transform 24.03s, … tests 18.32s)` — 71% of wall clock is babel-based transform from `@vitejs/plugin-react` (no Babel plugins are configured anywhere, so esbuild/SWC-only transform would collapse this). Also `reporters: ['default', 'html']` (`vitest.config.mts:34`) writes a full HTML report on **every** run (bun output: "HTML Report is generated") — make `html` reporter CI-only or add `--reporter=default` to `test:run`.

Status: verified — vitest.config.mts:34 includes the html reporter on every run; :35 outputFile test-results.xml mismatches it; no Babel plugins are configured (reactCompiler false); the duration split is audit-run command evidence (baseline confirms 88/88 green).

**06-O4 — P3 — Recharts is statically imported in 8 modules**
`from 'recharts'` in `SectorAllocationChart`, `PerformanceChart`, `risk-studio`, `forecast-risk`, `equity-research`, `concentration`, `realized-risk`, `optimize` (8 files). `next.config.ts:14-26` `optimizePackageImports: ['recharts', …]` mitigates barrel cost, but chart-heavy pages still pay the graph at first paint. `next/dynamic` per chart section (pattern already proven: tests stub these exact components, `DashboardPhase4.test.tsx:82-90`) would defer them. Do this only after a bundle report says it matters — optimizePackageImports may already cover the bulk.

Status: verified — exactly 8 files import recharts (SectorAllocationChart, PerformanceChart, risk-studio, forecast-risk, equity-research, concentration, realized-risk, optimize); stub pattern at DashboardPhase4.test.tsx:82-90 confirmed; recharts is in optimizePackageImports (next.config.ts:16).

**06-O5 — P3 — Vitest config loose ends**
- `vitest.config.mts:34-35`: `reporters: ['default','html']` with `outputFile: 'test-results.xml'` — filename says JUnit XML, reporter says HTML; per-reporter output config is implied but wrong.
- `vitest.config.mts:32`: `includeSource: ['src/**/*.{js,ts,tsx}']` enables in-source test instrumentation, but grep `import.meta.vitest` → **0 hits** — dead config, costs coverage instrumentation.
- Coverage `exclude` (`:15-22`) doesn't exclude `src/app/**/layout.tsx` or `next.config.ts` — harmless, but layouts are untestable glue that will drag the 80% threshold.

Status: fixed — dropped dead `includeSource`, set `reporters: ['default']` (removed html + mismatched `outputFile: 'test-results.xml'`), added `src/**/layout.tsx` to coverage exclude; thresholds untouched (06-I3 unenforced either way, no CI).

**06-O6 — P3 — `optimizePackageImports` list is stale**
`next.config.ts:14-25` optimizes `date-fns`, `papaparse`, `clsx`, `tailwind-merge` — first two are never imported (06-O1), last two are ~1 KB each. Prune to `lucide-react`, `recharts`, `@tanstack/react-table`, `@tanstack/react-query`, `jspdf`, `xlsx`.

Status: fixed — `next.config.ts` `optimizePackageImports` pruned to `lucide-react`, `recharts`, `@tanstack/react-table`, `@tanstack/react-query`, `jspdf`, `xlsx` (dropped `date-fns`, `papaparse`, `clsx`, `tailwind-merge`).

**06-O7 — P3 — `.env.local` caps Node heap at 512 MB**
`.env.local:1`: `NODE_OPTIONS="--max-old-space-size=512"` — that's a *ceiling* of 512 MB (default heap is ~2–4 GB on 64-bit). For a Next 16 build/dev over 21 routes this invites `JavaScript heap out of memory` and silently throttles Turbopack/webpack caches. Intent unclear (likely a old workaround); verify the build still succeeds under it or remove.

Status: verified — .env.local:1 sets NODE_OPTIONS=--max-old-space-size=512.

**06-O8 — P3 — `xlsx@0.18.5` is a stale npm release**
`package.json:42`. SheetJS froze npm publishing after 0.18.5; known issues after that line (incl. CVE-2024-22363 ReDoS) are only fixed on the CDN build. It processes user-adjacent spreadsheet data via `lib/export.ts:6`. Worth a migration decision (CDN tarball or alternative), tracked not urgent.

Status: verified — package.json:42 pins xlsx ^0.18.5; lib/export.ts:6 imports it and writes .xlsx at :178-190.

**06-O9 — P3 — Lint script is slow and unbounded**
`package.json:9` `"lint": "eslint"` with no path/glob — first invocation exceeded 180 s wall clock with zero output (command evidence above); full pass runs into minutes and emits 317 problems. Scope it (`eslint src`) and consider a cache; once the single error is fixed this becomes a usable gate.

Status: verified — package.json:9 lint script is bare eslint with no path/glob; baseline lint = 317 problems, exit 1.

---

## 4. Recommended changes (prioritized, P0 → P3)

| # | Finding | file:line | Note |
|---|---|---|---|
| 1 | **06-B1** P1 | `components/portfolio/PortfolioTable.tsx:43`, `PortfolioStats.tsx:80`, `app/portfolio/manage/page.tsx:335`, `EditPositionModal.tsx:173` | ₹ + `en-US` violates the currency invariant; route all four through `lib/utils.ts:23 formatCurrency` (`en-IN`). |
| 2 | **06-B2** P1 | `app/dashboard/liquidity/page.tsx:298-310` (+ render gates `:565,:618`) | Error path fabricates 7.8/Low/60-30-10 and shows it as live; keep `liquidityData=null` on error, add a test for the error path (the loading-path test already exists). |
| 3 | **06-B3** P1 | `factor-exposure:298`, `concentration:402`, `forecast-risk:441`, `stress-testing:424,442`, `dashboard/page:266`, `equity-research:173,185`, `india-flows:17-19` | Silent catches hide failures; give every fetch an `error` state or `addNotification` (exemplars already exist: `dashboard/page.tsx:276`, `liquidity/page.tsx:593`). |
| 4 | **06-I1** P1 | no `.github/workflows/*` (glob empty) | No CI despite AGENTS.md:27 deferring gates to it; add tsc → vitest → eslint jobs (30 s + 34 s + lint once red-fixed). |
| 5 | **06-B5** P2 | `next.config.ts:31-33` vs `.env.local:3` / `lib/api.ts:37` | Rewrite hardcodes localhost while axios uses env — CSV export (`dashboard/page.tsx:254`) breaks off-localhost; derive rewrite target from env. |
| 6 | **06-B6** P2 | `AddPositionModalSimple.tsx:43-47` + `:77-79` | Failed portfolio-summary fetch → weight auto-set to 1.0 on a non-empty book; block submit on fetch failure instead. |
| 7 | **06-B7** P2 | missing `src/app/{error,not-found,global-error}.tsx`; dead `LoadingState.tsx:229` | Add the three route files and/or mount the existing `ErrorBoundary`; today render errors show Next's bare default. |
| 8 | **06-B4 + 06-I3** P2 | `PortfolioDropzone.tsx:85` (`prefer-const` = the 1 lint error); `vitest.config.mts:23-30` | Fix the error so the future CI lint job can go green; re-baseline coverage thresholds by running `test:coverage` once before enforcing. |
| 9 | **06-O1 + 06-O2** P2 | `package.json:17-44` | Drop 7 dead deps (cva, tailwind-merge, date-fns, papaparse, 3 radix, babel-plugin-react-compiler) and move `vitest` + `@testing-library/*` + `@types/file-saver` to devDependencies. |
| 10 | **06-B8 / 06-I5 / 06-I2** P2–P3 | 6 `alert/`confirm` sites; untested `portfolio/manage`, `optimize`, `regime`, `pairs`, `risk-contribution`, `india-flows`, `export.ts` | Replace native dialogs with the existing notification system; then start filling the page/component/`export.ts` coverage holes with invariant-style tests like `FabricatedFallbacks`. |

Lower priority (P3, listed for completeness): 06-B10 `$` default in MetricCard + test lock · 06-B11 DataTable USD/`-` defaults · 06-B12 no-op replaces · 06-B13 JSON dump · 06-I7 duplicate h1 · 06-I8 hand-rolled modal vs `dialog.tsx` · 06-O3 HTML reporter every run · 06-O4 recharts `next/dynamic` · 06-O5 vitest outputFile/`includeSource` · 06-O6 prune optimizePackageImports · 06-O7 512 MB heap cap · 06-O8 xlsx stale · 06-O9 slow lint script.

---

### Command results (as run)

```
bunx tsc --noEmit            → EXIT=0 (clean)
bun run test:run              → EXIT=0 · Test Files 16 passed · Tests 88 passed · Duration 34.06s
                                 (transform 24.03s; bun stderr NativeCommandError wrapper = PowerShell noise only)
bun run lint                  → EXIT=1 · ✖ 317 problems (1 error, 316 warnings)
                                 1 error: PortfolioDropzone.tsx:85 prefer-const
                                 (first run: no output within 180s → lint script unbounded, 06-O9)
bun run test:coverage         → not run (would need baseline for 06-I3; thresholds 80% at vitest.config.mts:23-30)
```

**Files touched: exactly one — `.scratch/frontend-audit/06-config-tests-crosscutting.md` (this file). No product code, no configs, no commits.**
