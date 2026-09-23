# Frontend audit fix session — FIX-REPORT

Date: 2026-09-23 · Mode: 3-wave (verify → fix → adversarial review) · Commits: **none** (uncommitted working tree, per instruction)

## Gates (final, `frontend/`)

| Gate | Baseline (audit) | Final |
|---|---|---|
| `bunx tsc --noEmit` | exit 0 | **exit 0** |
| `bun run test:run` | 88/88 (16 files) | **167/167 (25 files)** |
| `bun run lint` | exit 1, 317 problems (1 error) | **exit 0, 281 problems (0 errors, 281 warnings)** |

Scope guard: HEAD `860a527` unchanged · `git diff HEAD -- backend/` = **0 files** · `frontend/package.json` + `bun.lock` unchanged (**no new deps**) · content changes limited to `frontend/**` + `.scratch/frontend-audit/**` (+ pre-existing AGENTS.md/`select.tsx` notes).

Adversarial review: [`WAVE3-REVIEW.md`](WAVE3-REVIEW.md) — **PASS** (0 false-fixed on ≥17 samples).

## Per-report Status tallies (per-finding Status lines)

| Report | Total | fixed | refuted | verified-open | skipped | partial | handoff |
|--------|------:|------:|--------:|--------------:|--------:|--------:|--------:|
| 01 dashboard-a | 49 | 39 | 1 | 9 (I/O) | 0 | 0 | 0 |
| 02 dashboard-b | 47 | 42 | 0 | 5 (I/O) | 0 | 0 | 0 |
| 03 tools-c | 61 | 54 | 0 | 0 | 7 | 0 | 0 |
| 04 system | 40 | 18 | 1 | 21 (1×P1 B14 + 3×P3 B + 17 I/O) | 0 | 0 | 0 |
| 05 components | 38 | 34 | 0 | 0 | 4 | 0 | 0 |
| 06 config/tests | 31 | 12 | 0 | 17 | 1 | 1 | 0 |
| **All** | **266** | **199** | **2** | **52** | **12** | **1** | **0** |

Header tallies in each report match these (01–06 updated this session). Wave-1 meta line (verified=N = "reviewed") is superseded by Wave-2/3 per-finding Statuses.

## What was fixed (highlights)

### P0
- **03-B1** — `manage/page.tsx` null `.toFixed` crash → `!= null` guards + `risk_level: undefined` on error · test `FabricatedFallbacks`.
- **04-B6** — CSV formula injection → shared `escapeCsvCell` (`lib/utils.ts`) wired into `export.ts` + `store.ts` · test `csv-escape`.

### P1 wrong numbers / fabricated data
- Fabricated catch payloads (01-B1 family, 03-B11, 06-B2) → null state + error banners.
- `|| 0` VaR / Low-Risk (02-B12, 05-B4) → `?? null` + N/A.
- Stress-test custom shock/duration now sent (01-B8); factor-exposure sign (02-B10); risk-contribution sign (02-B15).
- en-US ₹ locale sweep (06-B1 + 04-B8) → shared `formatCurrency` / `en-IN`.
- MetricCard locale/NaN/delta guards (05-B5/B10).
- **04-B7** (Wave-3 follow-up) — institutional PDF page-break: holdings loop, risk section, disclaimer all call `checkBreak`; disclaimer y clamped to `pageBottom() - 4`.

### P1 error / flow
- Typed `AppError` + `buildApiErrorMessage` reads FastAPI `detail` (04-B1/B2) · tests `api-errors`.
- WebSocket clientId regen, 1008 handling, settle-connect (04-B3/B4/B17/B18) · tests `websocket`.
- Add-modal fetch-failure no longer fabricates weight 1.0 (05-B7/06-B6); screener weight `gt=0` + inline error (03-B2).
- Route error boundaries `error.tsx` / `not-found.tsx` / `global-error.tsx` (06-B7) · tests `ErrorSurface`.

### P1/P2 a11y + dark mode
- Tailwind v4 `@custom-variant dark` (05 dark-mode); modals migrated to `ui/dialog.tsx` (05-B2); Dropzone keyboard/file validation (05-B3); `select.tsx` deleted (zero importers).

### Wave-3 residual follow-ups (this pass)
- **04-B7** PDF page-break (above).
- Display-path `|| 0` → null/N/A: `dashboard/page.tsx:146` (max_drawdown), `liquidity/page.tsx:296,299` (score/volume; null-safe sort + count filters + CSV), `PortfolioStats.tsx:118,136` (`formatPercent` accepts null).
- Stale 06 annotations re-anchored: **06-B1/B2/B6/B8/B10** → `fixed`; **06-B3** → `partial-fixed` (factor-exposure/stress-testing residual).
- Header tallies for reports 02–06 → fixed/verified-open/skipped vocabulary.
- `liquidity` `PositionLiquidity.score` typed `number | null` end-to-end (tsc was red mid-pass; fixed before final gates).

## Refuted (2)

- **01-B34** — heatmap contrast: composites over hardcoded `bg-slate-900`, not near-white.
- **04-B9** — 667% percent/fraction clash: cited consumers use local `toFixed` formatters, not `utils.formatPercentage` ×100 on pct fields.

## Skipped (12) — deliberate, with rationale

- **03** (7): monolith component extraction; full error-taxonomy refactor; NotificationSystem batch-E ownership; theme-token migration; optimistic single-row patch; `next/dynamic` chart split; formatCr vs formatCurrency contract decision.
- **05** (4): shared PositionForm extraction; token/chart-palette sweep; DESIGN-scale docs/YAGNI; next/dynamic chart loading (page files unowned).
- **06** (1 + 1 partial): **06-I1 CI workflow** deferred to separate PR (AGENTS.md:27 — tsc/vitest manual + CI, too slow for commit time); **06-B3** partial (factor-exposure/stress-testing residual silent catches).

## Open handoffs (verified-open B findings)

| ID | Severity | Summary |
|---|---|---|
| **04-B14** | P1 | FX is symbol-swap only — position rows/P&L show INR magnitude with `$` prefix; summary totals convert server-side; full FX module = dedicated ticket. |
| 04-B21/B22/B23 | P3 | WS double-subscribe; dead hot-path code; notification auto-hide timers never cancelled. |
| 06-B11 | P3 | DataTable residual `-` empty token vs app-standard `N/A` (USD default already gone). |
| 06-B13 | P3 | `PortfolioDropzone` non-string parse error → `JSON.stringify` fallback. |
| 06-B3 residual | P2 | factor-exposure / stress-testing remaining silent `console.error` catches (partial). |

Plus **46 I/O** improvements/optimizations left as `verified-open` (52 total verified-open minus the 6 open B findings listed above: refactor/system-design tickets — react-query adoption, typed generation, WS re-cut, coverage map, etc.).

## Tests added/extended this session (25 files / 167 tests green)

New or grown: `api-errors`, `csv-escape`, `websocket`, `store`, `utils`, `format-invariants`, `AddPositionZeroState`, `DiversificationN1`, `ErrorSurface`, plus expanded `FabricatedFallbacks`, `MetricCard`, `DataTable`, `EditPositionModal`, `PortfolioDropzone`, `AddPositionModalSimple`, `Settings`, `ScreenerStudio`, `EquityResearch`, `LiquiditySkeleton`, `DashboardPhase4`, etc.

## Non-actions

- No commits, no staging, no backend edits, no new dependencies.
- Root `README.md` / `.scratch/backend-audit/` / `.zcode.lnk` are out-of-scope parallel-session artifacts (see WAVE3).
