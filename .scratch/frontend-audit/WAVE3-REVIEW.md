# WAVE 3 — Adversarial Review of the Wave-2 Frontend Fix Session

**VERDICT: PASS**

Gates (re-run this session, `frontend/`): `bunx tsc --noEmit` → **exit 0** · `bun run test:run` → **167/167 pass (25 files)** · `bun run lint` → **281 problems (0 errors, 281 warnings), exit 0** — claim exact (baseline: tsc 0, vitest 88, lint 317 problems / 1 error).

## Scope guard

- HEAD = `860a52737fe6e6314dbf0879f68455da7b6bdbc1` ✓ (= required `860a527`).
- `git diff HEAD -- backend/` → **0 files** ✓ · `git diff --cached` → **0 staged** ✓.
- Content changes vs HEAD: **65 files = `M AGENTS.md` + 64 `frontend/**`** (incl. `D frontend/src/components/ui/select.tsx`, zero importers ✓). All other ` M` porcelain entries (`.agents/**`, `.scratch/**`, `instructions/**`, `RELEASE_NOTES.md`, docker ymls, …) are absent from `git diff HEAD` → pre-existing EOL/refresh noise, untouched by this session ✓.
- `AGENTS.md` diff is the Core Philosophy block, mtime 2026-09-08 → pre-session ✓.
- `frontend/package.json` + `frontend/bun.lock` unchanged vs HEAD → **no new deps** ✓.
- Out-of-scope artifacts created today (see P2-4): root `README.md` (untracked, 03:11:50), `.scratch/backend-audit/` (parallel backend session), `.zcode.lnk`.

## P0 checks — all green

1. **03-B1 null `.toFixed()` crash (the one P0 finding):** `manage/page.tsx` forecast guards `!= null ? …toFixed(2) : 'N/A'` (:731/:746/:766); error paths write `risk_level: undefined`, never `'Low'` (:129-131, :143-145) ✓ test `FabricatedFallbacks` manage case passes.
2. **04-B6 CSV formula injection:** `escapeCsvCell` in `lib/utils.ts:66` (`/^[=+\-@\r\t]/` → `'` prefix), wired at `export.ts:8,202,204` and `store.ts:5,404,406`; `src/test/unit/csv-escape.test.ts` covers `=+-@` ✓.
3. **No fabricated metrics in product code:** grep `7.8|0.09|5000000000` over non-test `src` → **1 hit = SVG icon path digits in `LoadingState.tsx:253`, non-metric**. No `risk_level: 'Low'` literal in product (only `'Unknown'` default, `RiskMetricsDisplay.tsx:45`; `'Low'` appears only in test fixtures) ✓.
4. **No bare `alert(` anywhere in product src** (only `window.confirm` at `settings/page.tsx:101`, deliberate + test-backed) ✓.
5. **Zero-state & HHI invariants:** `AddPositionZeroState` and `DiversificationN1` tests pass; first-position weight path gated on `portfolioLoaded` (`AddPositionModalSimple.tsx:81-93`) ✓.
6. **en-US on ₹ money paths: zero.** Only remaining `en-US` uses are dates (`PerformanceChart.tsx:42,93`) and times (`NotificationSystem.tsx:193`) — acceptable. All four 06-B1 sites now route through shared `formatCurrency` (`PortfolioTable.tsx:41-42`, `PortfolioStats.tsx:78-79`, `EditPositionModal.tsx:163,169,179`, `manage:364-365` wraps it); `export.ts` all `en-IN` ✓.
7. **False-fixed hunt (dangerous direction):** ≥17 `Status: fixed` claims re-verified against current code with file:line — **0 false-fixed found.** Samples: 01-B1 liquidity catch nulls state (no 7.8), 01-B8 embedded `Custom: name (N%)`, 01-B12 `Upper +20% (illustrative)`, 02-B2 `?? 'N/A'`, 02-B3 `is_regime_break`, 02-B12 `?? null`, 03-B1/B2/B11/B15, 04-B4 fresh clientId per attempt, 04-B9 refuted correctly, 05 dark `@custom-variant`, 05-B7 fetchError gate, 06-B4 rewrite origin from `NEXT_PUBLIC_API_URL`, optimize `frontierPoints` synthetic points deleted.

## Issues found by this review

### P1 — genuinely open, honestly annotated (`Status: verified` = confirmed still present)
1. **04-B7 · Institutional PDF silently truncates holdings** (no page-break logic — data loss in the artifact). **Fixed in Wave-3 follow-up:** local `checkBreak`/`pageBottom` in `exportInstitutionalReviewPDF`; holdings loop, risk section, and disclaimer all page-break; disclaimer y clamped to `pageBottom() - 4`.

2. **04-B14 · FX is symbol-swap only** — position rows/P&L show INR magnitude with `$` prefix when currency toggled; phantom FX types in `types/index.ts:206-219`; summary totals do convert server-side (status correction accurate). Status: verified, code unfixed — open handoff (full FX module = dedicated ticket).

(No P0 issues. Both P1s were claimed as open, not fixed — claims accurate.)

### P2

3. **Six stale Status annotations in `06-config-tests-crosscutting.md` under-claim fixes** (code fixed by other batches, annotation never updated): **06-B1** says `handoff-to-batch` / 3 en-US sites remain — all three now use shared `formatCurrency` (verified above); **06-B2** says liquidity 7.8-mock still present — fixed by 01-B1 (no 7.8 in page); **06-B3** says handoff — all 7 cited sites now have error states (concentration 01-B19, factor-exposure 02-B13, forecast-risk `setFetchError` :459-464, stress-testing `setRunError` :430-432/:464, dashboard error banner :266-274 + `exportError` :257, equity-research 03-B5/6/7, india-flows setError :30-32); **06-B6** says add-modal catch still zeroes counters — catch now only sets `fetchError` (:48-51), weight gated on `portfolioLoaded` (:81); **06-B8** says 6 alert/confirm sites — zero `alert(` remain, only deliberate settings `window.confirm`; **06-B10** says MetricCard defaults `$` — `formatValue` now `en-IN` / no-prefix (`MetricCard.tsx:35-36`). Direction is safe (under-claim), but the report now misstates current code.
4. **Root `README.md`** created 03:11:50, untracked, outside the allowed paths (`frontend/**` + `.scratch/frontend-audit/**`). Plausible separate-session artifact; not part of the fix wave.
5. **Residual display-path `|| 0` coercions** (inconsistent with the wave's own `?? null` doctrine; not covered by Wave-1 Statuses):
   - `dashboard/page.tsx:146` — `analyticsData.summary?.max_drawdown || 0` while siblings at :143-145 use `?? null`.
   - `liquidity/page.tsx:296,299` — per-row `score || 0`, `avg_volume || 0` (success-path null → 0; category/liquidation/spread were null-fixed, these were missed).
   - `PortfolioStats.tsx:118,136` — `bestPerformer/worstPerformer …pct || 0` → `+0.00%` on null.
6. **Header tally vocabulary inconsistent across reports:** `01` breaks out `fixed=39 · verified-open=9 · refuted=1` (accurate); `02–06` headers say `verified=N` as a meta-count of "reviewed", masking per-finding reality (e.g. 06 is really fixed=7 / verified=21 / handoff=2 / skipped=1). Per-finding Status lines themselves are 100% present (all 266 finding headers have a Status).

### P3

7. `risk-studio/page.tsx:267` — `vol_contrib: +((volShare || 0) * 100)` null → 0% bar.
8. `dashboard/page.tsx:180` — weight fallback `data.weight || 0`.
9. **06-B13 open (accurate):** `PortfolioDropzone.tsx:186` still falls back to `JSON.stringify(msg)` for non-string parse errors.
10. **06-B11 partially open:** USD default gone (no `en-US`/`formatCurrency` left in current `DataTable.tsx`); any residual `-` empty tokens vs app-standard `N/A` are cosmetic.
11. **04-B21/B22/B23 open (accurate, P3):** WS double-subscribe, dead hot-path code, notification auto-hide timers never cancelled.
12. Settings `window.confirm` retained deliberately (test-backed) — acceptable, listed for completeness.

## Residual Status counts per report (from per-finding Status lines)

| Report | Total | fixed | refuted | verified (open) | skipped | handoff |
|--------|------:|------:|--------:|----------------:|--------:|--------:|
| 01 dashboard-a | 49 | 39 | 1 | 9 (all I/O deferrals) | 0 | 0 |
| 02 dashboard-b | 47 | 42 | 0 | 5 (all I/O) | 0 | 0 |
| 03 tools-c | 61 | 54 | 0 | 0 | 7 (deliberate) | 0 |
| 04 system | 40 | 17 | 1 | **22 (2×P1 B + 3×P3 B + 17 I/O)** | 0 | 0 |
| 05 components | 38 | 34 | 0 | 0 | 4 (deliberate) | 0 |
| 06 config/tests | 31 | 7 | 0 | 21 (**6 stale B** + 15 I/O) | 1 | 2 (**both stale**) |

- Header tallies: every report's unique finding IDs = header total (49/47/61/40/38/31 ✓); all 266 IDs carry a Status ✓.
- Genuinely open **B** findings after adjudication: **04-B7 (P1), 04-B14 (P1), 04-B21/22/23 (P3), 06-B13 (P3), 06-B11 partial (P3)** = 7. Stale-annotation B findings (code actually fixed): **6** (06-B1/B2/B3/B6/B8/B10).
- Skipped = explicitly deferred with rationale (refactor tickets, CI-per-AGENTS rule, cross-batch ownership) — not silent.

## Follow-ups

1. Re-annotate the six stale 06 statuses (and the 06 header tally) against current code.
2. Fix or ticket 04-B7 (PDF page-break) and 04-B14 (real FX conversion) — the only open P1s.
3. Sweep the five display-path `|| 0` sites (P2-5) to `?? null` + N/A.
4. Break out per-finding status categories in reports 02–06 headers to match report 01's format.

*Review mode: read-only on product code; this file is the only artifact written.*
