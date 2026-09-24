# Frontend code audit — consolidated index

Status: **fix session complete** — 3-wave verify/fix/adversarial-review done; see [`FIX-REPORT.md`](FIX-REPORT.md) and [`WAVE3-REVIEW.md`](WAVE3-REVIEW.md) (PASS). No commits.
Date: 2026-09-23
Method: 6 parallel subagents (audit) → verify wave → fix wave → adversarial review. Product code edited only under `frontend/**`; this directory holds audit reports + fix annotations. Backend audit parallel: see `../backend-audit/00-INDEX.md`.
Gates (final): `bunx tsc --noEmit` exit 0 · `bun run test:run` **167/167** (25 files) · `bun run lint` **0 errors, 281 warnings, exit 0** (baseline was exit 1, 317 problems / 1 error).

## Coverage

| Report | Area | Files (approx lines) |
|---|---|---|
| [01-dashboard-pages-a.md](01-dashboard-pages-a.md) | Dashboard pages set A | volatility-sizing, forecast-risk, stress-testing, tear-sheet, concentration, liquidity (5,989) |
| [02-dashboard-pages-b.md](02-dashboard-pages-b.md) | Dashboard pages set B | factor-exposure, regime, risk-studio, risk-contribution, dashboard main, realized-risk, optimize |
| [03-tools-pages-c.md](03-tools-pages-c.md) | Research/tools pages | equity-research, portfolio/manage, screener-studio, settings, monte-carlo, india-flows, pairs, app layouts |
| [04-system-layer.md](04-system-layer.md) | Data/state/system layer | api.ts, store.ts, websocket.ts, export.ts, utils.ts, useRealTime.ts, useAnalytics.ts, types/index.ts |
| [05-components-design-system.md](05-components-design-system.md) | Component/design-system layer | layout/, ui/, portfolio/, charts/ components + token discipline |
| [06-config-tests-crosscutting.md](06-config-tests-crosscutting.md) | Config, tests, cross-cutting sweeps | package.json, next/vitest/ts/eslint configs, all tests, invariant/a11y/security/error sweeps |

## Totals (unique finding IDs)

| Report | Bugs | Improvements | Optimizations | Total |
|---|---:|---:|---:|---:|
| 01 | 35 | 9 | 5 | **49** |
| 02 | 24 | 16 | 7 | **47** |
| 03 | 34 | 18 | 9 | **61** |
| 04 | 23 | 10 | 7 | **40** |
| 05 | 18 | 14 | 6 | **38** |
| 06 | 13 | 9 | 9 | **31** |
| **All** | **147** | **76** | **43** | **266** |

Severity (headline counts as stated by each report; report 01's severity tags cover its 35 bugs — its 14 improvement/optimization entries are severity-graded inline):

| Severity | 01 | 02 | 03 | 04 | 05 | 06 | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| P0 | 0 | 0 | 1 | 1 | 0 | 0 | **2** |
| P1 | 13 | 15 | 17 | 12 | 13 | 4 | **74** |
| P2 | 16* | 19 | 27 | 19 | 20 | 13 | **~114** |
| P3 | 6* | 13 | 16 | 8 | 5 | 14 | **~62** |

(*01 P2/P3 bug-severity split as reported; +14 unsummed I/O findings from 01 — treat table as ±14 on P2/P3.)

## P0s (fix first)

1. **03-B1 — page crash**: `portfolio/manage/page.tsx:683-705` — `null.toFixed(2)` when forecast-risk returns null vol/VaR (guard checks `!== undefined`, backend now sends `null`).
2. **04-B6 — CSV formula injection**: `lib/export.ts:196-216` + `lib/store.ts:384-403` — no `=+-@` escaping; user-controlled `custom_name` executes when the exported CSV is opened in Excel.

## Top findings per report

- **01 pages A** — liquidity catch fabricates a full success payload (score 7.8, fake volume stats) beside the error banner (`liquidity:294-312`); stress-test custom `market_shock`/`duration` never sent → backend silently uses −20% while UI claims user's shock (`stress-testing:465-478`); forecast chart CI is synthetic ±20% labeled "90% CI" (`forecast-risk:385-386,889`); concentration fabricates HHI `0.09`/Neff `1.0`/`0.0%` during load-error (`concentration:570-604,820`); `formatPercentage` renders `1.5%` for 150% (`volatility-sizing:368-374`).
- **02 pages B** — optimize fabricates frontier/current points (`optimize`); main dashboard `var_95 || 0` renders missing VaR as **0.00% "Low Risk"** (`dashboard/page.tsx`); risk-studio binds `breakdown_alert` but backend sends `is_regime_break` → badge stuck (`risk-studio:627`); factor-exposure forces `+` on negative alpha → `"+-3.20%"` + always-green bar (`factor-exposure:593,680-694,809`); risk-contribution `Math.abs(diff)` inverts deviation sign (`risk-contribution`).
- **03 tools C** — **P0** `null.toFixed` crash on manage (above); settings has 5 placebo preference controls (only `primary_source` saves) while banner claims all applied (`settings:42-46,146`); screener "Add to Portfolio" sends `weight: 0` → backend `gt=0` 422 + breaks zero-state 100% invariant, error shown via bare `alert` (`screener-studio:160`); manage fabricates `risk_level: 'Low'` on error (`manage:112-134`); dead `reason?.response?.data?.detail` drops 503 vendor-outage detail (`equity-research:91`, same `pairs:20-21`).
- **04 system layer** — **P0** CSV injection (above); `api.ts:86-92` never reads `detail` for 503 → all vendor outages surface as "HTTP 503"; websocket reuses `clientId` across reconnects → backend closes duplicates 1008 → 5-attempt death spiral (`websocket.ts:37,143`); `connect()` while connecting never settles → StrictMode double-mount can end with zero sockets (`websocket.ts:68-70`); percent/fraction clash: `utils.ts:52` ×100 on already-percent backend field → **+6.67% renders as 667%** (`PortfolioTable.tsx:235`).
- **05 components/design-system** — dark-mode class toggle is a no-op under Tailwind v4 (needs `@custom-variant dark`) so `.dark` store writes do nothing (`globals.css:15-20`, `store.ts:245`); Add/Edit/Dropzone modals hand-rolled with no focus trap/Escape/`role="dialog"`/keyboard path while working Radix `ui/dialog.tsx has zero importers`; `RiskMetricsDisplay:43-53` defaults missing data to zeros → "VaR 0.00%, Low Risk"; `MetricCard` shows `NaN%`/`+0.00%` placeholder deltas and defaults to US `$`/K-M instead of ₹/Cr/L (`MetricCard.tsx:36,119`); Add modal treats failed portfolio fetch as empty → submits `weight: 1.0` into a populated book (`AddPositionModalSimple:43-47,77-79`).
- **06 config/tests/cross-cutting** — ₹ money formatted `en-US` in 4 files (`PortfolioTable:43`, `PortfolioStats:80`, `manage:335`, `EditPositionModal:173`) — AGENTS.md invariant violation; liquidity fabrication reconfirmed; silent `console.error`-only catches on 7+ pages swallow outages into empty tables (india-flows etc.); **zero CI** while AGENTS.md defers tsc/vitest to CI and lint is red (317 problems, 1 error at `PortfolioDropzone:85`); `next.config.ts:31-33` rewrites hardcode `localhost:8000` vs `NEXT_PUBLIC_API_URL` → CSV export breaks off-localhost.

## Cross-cutting themes

1. **Fabricated fallbacks still alive on the frontend** (01, 02, 03, 05) — same class the backend audit killed: catch blocks and `|| 0`/`?? 0.0` chains invent scores, VaR, HHI, risk levels, CI bands, frontier points. Backend now truthfully sends `null` + flags; frontend keeps re-fabricating zeros/defaults. One shared rule needed: **null → N/A/—, never coerce to 0 or a "safe" constant** (the `FabricatedFallbacks.test.tsx` contract, applied everywhere).
2. **Error taxonomy is broken end-to-end** (03, 04, 06) — 503 `detail` never read, silent `console.error` catches, bare `alert()`, dead `reason?.response?.data?.detail` paths. Needs one typed `AppError` in `api.ts` (status → human message, reads FastAPI `detail` for 422/503) + toast via existing NotificationSystem.
3. **Percent/fraction and locale discipline** (04, 05, 06) — ×100 on already-percent fields (667% bug), en-US formatting of ₹ money, MetricCard US-$ defaults. Fix at `utils.ts`/`MetricCard` seam: one `formatINR`/`formatPct` used everywhere, en-IN mandatory.
4. **Hand-rolled primitives bypass working shared ones** (05) — modals ignore `ui/dialog.tsx` (focus trap/Escape debt), page-local loading/error blocks ignore `LoadingState`, ad-hoc colors/spacing vs tokens.
5. **WebSocket lifecycle fragile** (04) — clientId reuse, unsettled connect promise, no single-owner connection manager.
6. **QA/CI vacuum** (06) — tsc/vitest green but no CI config, eslint red (317), coverage gaps: table of untested pages/components in 06; heavy pages (equity-research 1057, volatility-sizing 1093) largely untested.
7. **AGENTS.md invariant violations found**: zero-state weight (screener `weight:0`), en-US ₹ locale (4 files), metric hygiene (multiple), HHI/Neff fabrication (concentration), `row.original || row` spot-checks (see 06).

## Fix-session outcome (per-finding Status)

| Report | Total | fixed | refuted | verified-open | skipped | partial |
|---|---:|---:|---:|---:|---:|---:|
| 01 | 49 | 39 | 1 | 9 | 0 | 0 |
| 02 | 47 | 42 | 0 | 5 | 0 | 0 |
| 03 | 61 | 54 | 0 | 0 | 7 | 0 |
| 04 | 40 | 18 | 1 | 21 | 0 | 0 |
| 05 | 38 | 34 | 0 | 0 | 4 | 0 |
| 06 | 31 | 12 | 0 | 17 | 1 | 1 |
| **All** | **266** | **199** | **2** | **52** | **12** | **1** |

Open P1 handoff: **04-B14** (FX symbol-swap only). Full open list + gate evidence: [`FIX-REPORT.md`](FIX-REPORT.md).

## Recommended fix order (original audit plan — largely executed)

1. **P0**: 03-B1 null-crash guard; 04-B6 CSV formula-injection escaping (export + store CSV paths).
2. **P1 batch A — wrong numbers**: 04-B9 ×100 clash (667%); `|| 0` VaR/Low-Risk (02-B12, 05-B4); fabricated catch payloads (01-B1 family, 03-B11); stress-test params not sent (01-B8); factor-exposure `+-` sign (02-B10); risk-contribution sign (02-B15); en-US locale sweep (06-B1); MetricCard delta/locale guards (05-B5).
3. **P1 batch B — error/flow**: typed 503/422 `detail` handling in `api.ts` + page dead paths (04-B1, 03-B3); websocket clientId/connect fixes (04-B3/B4); Add-modal empty-vs-error distinction (05-B7); screener weight `gt=0` + no `alert` (03-B2); settings placebo controls (03-B15); silent-catch sweep → toasts (06-B3).
4. **P1/P2 a11y + dark mode**: Tailwind v4 `@custom-variant dark`; migrate hand-rolled modals to `ui/dialog.tsx` + Dropzone keyboard/file-validation (05-B2/B3).
5. **P2 systemic**: shared null-render helpers; token discipline; CI workflow (tsc + vitest + eslint gate, fix 317 lint problems); `NEXT_PUBLIC_API_URL` in rewrites; test coverage for untested pages.
6. **P3 polish**: copy consistency (N/A vs —), ad-hoc styling, micro-optimizations listed per report.

## Explicit non-actions this pass

- **No commits / no staging** — working tree left dirty on purpose.
- Backend untouched (`git diff HEAD -- backend/` = 0 files).
- CI workflow (06-I1), full lint-warning cleanup, and FX module (04-B14) deferred to follow-up tickets.
- `.next/`, `node_modules/`, and other `.scratch/` areas untouched by this session.
