# Frontend Audit — Report 01: Dashboard Pages (Set A)

> Wave-1 status: fixed=39 · verified-open=9 · refuted=1 · total=49

- **Report ID:** 01
- **Date:** 2026-09-23
- **Scope:** line-by-line audit of six dashboard pages (read-only); this file is the only artifact written.
- **File set (actual line counts):**

| File | Lines |
|------|------:|
| `frontend/src/app/dashboard/volatility-sizing/page.tsx` | 1156 |
| `frontend/src/app/dashboard/forecast-risk/page.tsx` | 1061 |
| `frontend/src/app/dashboard/stress-testing/page.tsx` | 1033 |
| `frontend/src/app/dashboard/tear-sheet/page.tsx` | 951 |
| `frontend/src/app/dashboard/concentration/page.tsx` | 917 |
| `frontend/src/app/dashboard/liquidity/page.tsx` | 871 |
| **Total** | **5989** |

- **Severity:** P0 crash/data-loss/security · P1 wrong or misleading value shown · P2 UX/system-design · P3 nit.
- **Supporting reads (not audited, evidence only):** `components/ui/MetricCard.tsx`, `DataTable.tsx`, `LoadingState.tsx`, `lib/api.ts`, `lib/store.ts`, `lib/export.ts`, `types/index.ts`, `test/pages/FabricatedFallbacks.test.tsx`, `backend/app/services/analytics_engine.py`, `backend/app/api/analytics.py`, `backend/app/models/schemas.py`.

---

## 1. Bugs

### P1 — wrong or misleading values shown

| ID | Location | Finding | Status |
|----|----------|---------|----------|
| 01-B1 | `liquidity/page.tsx:294-312` | On fetch failure the catch block fabricates an entire success-shaped response — `overall_score: 7.8`, `liquidation_time_days: '1-2'`, `risk_level: 'Low'`, `volume_stats: {avg_volume: 5000000, total: 25000000, high/med/low: 60/30/10}` — while also setting `error`. UI shows fabricated score cards next to an error banner. Violates "metrics null + flag, never invented numbers". | fixed |
| 01-B2 | `liquidity/page.tsx:276-278` | `market_cap` fallback hardcodes `5000000000` (₹500 Cr) when backend omits it. Fabricated market cap rendered as a real position metric (col at :489-494). | fixed |
| 01-B3 | `liquidity/page.tsx:288` | Bid-ask spread fabricated from score tiers (`0.0004`/`0.0012`/`0.0035`) whenever `posData.spread` is missing/0. Backend always computes spread (`analytics_engine.py:307-335`); fallback invents microstructure data. | fixed |
| 01-B4 | `liquidity/page.tsx:831-832` | Risk badge hardcodes `LOW RISK` while the adjacent heading is score-derived (`:829`). A portfolio with score < 6 still shows a green "LOW RISK" pill. | fixed |
| 01-B5 | `concentration/page.tsx:820` | Insight sentence falls back to hardcoded `HHI = '0.09'` when `herfindahl_index` is null — invents a specific concentration number in narrative copy. | fixed |
| 01-B6 | `concentration/page.tsx:600` | Hero "Effective Positions" falls back to fabricated `'1.0'` whenever `positions.length > 0` but API data is absent (loading/error) — displays a fake Neff of 1.0. | fixed |
| 01-B7 | `concentration/page.tsx:570-572` | `divScore` final fallback is `0.0`; during load/error with N>1 the hero renders `Diversification Score: 0.0%` as if measured. Backend returns 0–100 units (`analytics_engine.py:232-246`); empty state must not masquerade as a computed 0. | fixed |
| 01-B8 | `stress-testing/page.tsx:399-404, 456-493` | Custom scenario collects `market_shock` and `duration` but the API call (`:465-468`) sends only `scenario: "Custom: <name>"` + tickers — shock/duration never reach the backend. Backend custom path parses `%` from the scenario string or falls back to fixed **-20%** (`analytics_engine.py:490-499`); recovery is fixed 12 months (`:496`). Card description still claims `"<user shock>% shock over <duration> days"` (`:478`) — user inputs silently ignored. | fixed |
| 01-B9 | `stress-testing/page.tsx:995` | Worst-case insight always attributes the loss to "the Market Crash scenario" even when `worstCase` (`:638-639`) comes from another scenario (Volatility Spike, custom, etc.). | fixed |
| 01-B10 | `stress-testing/page.tsx:1010` | Average recovery uses `sum + (r.recovery_time \|\| 0)` — null recovery (backend `recovery_time: Optional[int]`, `schemas.py:262`) counts as 0 months, deflating the stated average; empty list divides by `\|\| 1` and prints a confident `0.0 months`. | fixed |
| 01-B11 | `forecast-risk/page.tsx:441-443` | Fetch failure clears `positionData` but leaves stale `forecastData` — headline forecast cards keep showing the previous successful model/horizon while the table empties, with no error surfaced. | fixed |
| 01-B12 | `forecast-risk/page.tsx:385-386, 889-890` | Chart CI band is a synthetic ±20% multiplier (`termVol * 1.2` / `* 0.8`) but the tooltip labels it **"Upper/Lower 90% CI"**. No backend series feeds these lines; the explainer (`:90-100`) reinforces a statistical claim the data does not support. | fixed |
| 01-B13 | `volatility-sizing/page.tsx:368-374, 545, 633, 1131-1137` | `formatPercentage` heuristic (`Math.abs(value) <= 1.0 → ×100`) breaks for `totalWeightChange` > 1 (sum of \|Δw\| across a full re-weigh can exceed 1.0): a 1.5 total change renders as `1.5%` instead of `150%`, and `1.0` renders as `1.0%` instead of `100%`. Used in the metric card and the rebalance warning copy. | fixed — finding's `1.0 -> 1.0%` example is wrong (`Math.abs(value) <= 1.0` maps 1.0 -> 100.0%); only values >1.0 break (1.5 -> "1.5%") — used at volatility-sizing:545, :633, :1137 |

### P2 — system-design / silent failure

| ID | Location | Finding | Status |
|----|----------|---------|----------|
| 01-B14 | `stress-testing/page.tsx:424-425, 442-444, 494-495` | All three run paths swallow errors to `console.error` only; `runError` is set only for the in-band `data.error` branch (`:470-472`). Network/API throw ⇒ spinner stops, nothing happens, no message. | fixed |
| 01-B15 | `stress-testing/page.tsx:889` | Confidence falls back to `95` when `confidence_level` absent — fabricates a statistical confidence on partial/errored results (backend always sends `0.95` on success, `analytics_engine.py:555`). | fixed — `: 95` fallback at stress-testing:889; backend `_empty_stress_test` (analytics_engine.py:1300-1308) omits `confidence_level` |
| 01-B16 | `stress-testing/page.tsx:566` | "Limited history" badge hardcoded to ticker `=== 'NIFTYIETF.NS'` instead of backend `is_limited_history` / `history_warning` flags (forecast already maps those at `forecast-risk:432-433`). | fixed |
| 01-B17 | `stress-testing/page.tsx:447-448` | `runAllScenarios` sets `activeScenarioName` to `scenarios[0]` even if that scenario's request failed — detail pane binds to a missing result. | fixed |
| 01-B18 | `stress-testing/page.tsx:631` | CSV filename regex is `/\\s+/g` (matches literal `\s`, not whitespace) — spaces in scenario names never replaced (`stress-impact-market crash.csv`). | fixed |
| 01-B19 | `concentration/page.tsx:402-403, 456-483` | Catch only logs; no error UI. Metric cards coerce with `\|\| 0` (`largest_position`, `top_3`, `herfindahl_index`, `effective_positions`) so load/error renders `0` with live-looking status thresholds (`getConcentrationStatus`) — e.g. "good diversification" from a zero. | fixed — error banner on catch + null-aware `ConcentrationMetric` status union; assessment cards gate on `concentrationData == null` (no `\|\| 0` coercions) |
| 01-B20 | `liquidity/page.tsx:283-284` | `category` / `liquidation_days` derived client-side from score when backend omits them — second source of truth for fields the backend already owns (`analytics_engine.py:308-335`). | fixed |
| 01-B21 | `liquidity/page.tsx:351-366, 829` | `formatVolume(null) → '0'`, `formatPercentage(null) → '0.00%'`, and `(overallScore ?? 0)` all coerce null to zero — absent data renders as measured zero. Contrast: vol-sizing correctly returns `'N/A'` (`volatility-sizing:369-370`). | fixed |
| 01-B22 | `liquidity/page.tsx:318-327`, `concentration/page.tsx:409-416`, `forecast-risk/page.tsx:449-451`, `volatility-sizing/page.tsx:305-315`, `stress-testing/page.tsx:501-509` | Double-trigger fetch patterns (mount effect + `positions`/param effect) with no `AbortController` / sequence guard — out-of-order responses can leave stale data; stress auto-runs all four scenarios from an effect without unmount cancel. | fixed — request-sequence guards (`fetchSeq`/`runSeq` refs + effect-cleanup bump) on all five pages; stress auto-run invalidated on unmount (no `AbortController`, see 01-O5) |
| 01-B23 | `forecast-risk/page.tsx:378-379` | When `term_structure` is empty the curve falls back to `baseVol * (1 + 0.01 * Math.log(day))` — a fabricated shape still plotted inside a chart guarded only by base forecasts (`hasCurveBase`, `:349-354`). | fixed — fabricated log branch at forecast-risk:379; `hasCurveBase` (:349-354) only checks base forecasts |
| 01-B24 | `tear-sheet/page.tsx:685, 696` vs `:42-160` | Help buttons open `portfolio_volatility` / `benchmark_volatility` keys that do not exist in `EXPLAINERS`; modal's `if (!info) return null` (`:164`) makes both buttons silent no-ops. | fixed — `portfolio_volatility` / `benchmark_volatility` absent from EXPLAINERS (:42-160); HelpBtns :685/:696 hit `if (!info) return null` (:164) |
| 01-B25 | `tear-sheet/page.tsx:888` | Underwater SVG `x = i / (drawdownPoints.length - 1)` divides by zero when exactly one point survives the `length > 0` guard (`:853`) → `NaN` path. | fixed — div-by-zero at tear-sheet:888 behind `length > 0` guard (:853) |
| 01-B26 | `tear-sheet/page.tsx:309` | Headline falls back `full_history.metrics ?? data.metrics` with no caption change — holding-window metrics can appear under the "full-history asset characteristics" label (`:342`). | fixed — fallback at tear-sheet:309; unconditional "full-history asset characteristics" CSV label at :342 |
| 01-B27 | `volatility-sizing/page.tsx:376-378` | `formatCurrency(null)` returns `'₹0'` — fabricated zero on a money metric (should be `N/A`). | fixed |
| 01-B28 | `forecast-risk/page.tsx:763-770`, `stress-testing/page.tsx:828-841` | Scenario/model cards are clickable `<div>`s with no `role="button"`, `tabIndex`, or key handler — keyboard/screen-reader users cannot select. | fixed |
| 01-B29 | all six modals (e.g. `liquidity:138-143+204`, `forecast-risk:220-225`, `stress-testing:340-353`) | No `role="dialog"` / `aria-modal` / Escape / focus trap; backdrop `stopPropagation` (`liquidity:204`) makes outside-click inert while looking dismissible; forecast/stress/tear-sheet close buttons lack `aria-label` (vol-sizing has it at `:145`). | fixed — outside-click inert (backdrops have no closer; stopPropagation on inner panels at concentration:208 / forecast:201 / stress:233; liquidity:204 citation drifted to HelpBtn); forecast:220-225 and stress:250-255 closes lack aria-label though tear-sheet:172 now has one — core finding stands |

### P3 — nits

| ID | Location | Finding | Status |
|----|----------|---------|----------|
| 01-B30 | `stress-testing/page.tsx:357-394` | Seed `scenarios` carry fabricated `impact`/`recovery_time` (`-41.9`, `'24 months'`, …). Currently unrendered (cards bind `result.*`, `:851-884`), but dead demo data one refactor from leaking. | fixed |
| 01-B31 | `stress-testing/page.tsx:458`, `volatility-sizing/page.tsx:340, 361` | Native `alert()` for validation/failure — blocks paint, inconsistent with in-page `runError` pattern used elsewhere on stress. | fixed |
| 01-B32 | `concentration/page.tsx:563` | `sector.replace('_', ' ')` replaces only the first underscore — multi-word sector codes leave `_` behind. | fixed |
| 01-B33 | `concentration/page.tsx:398` | Missing sector fabricates `'General'` instead of null/`N/A` — masks enrichment gaps as a real sector bucket. | fixed |
| 01-B34 | `tear-sheet/page.tsx:301-305, 823` | Heatmap cells use `rgba(..., 0.20)` floor with `text-white` — near-zero returns give white-on-near-white contrast. | refuted — heatmap composites over hardcoded `bg-slate-900` (tear-sheet:778), so 0.20-alpha rgba stays dark; `text-white` (:823) legible; no near-white background exists |
| 01-B35 | `volatility-sizing/page.tsx:354-358` | Post-rebalance `setTimeout` not cleared on unmount — can `setState` after unmount. | fixed |

---

## 2. Improvements

| ID | Location | Finding | Status |
|----|----------|---------|----------|
| 01-I1 | all six pages | `HelpExplainerModal` + `HelpBtn` duplicated in every file with five different styling variants (slate/emerald, gray/indigo, white/purple, …). Extract one shared component + one content map import. | verified — skipped: cross-file shared-component extraction deferred to a dedicated pass |
| 01-I2 | vol-sizing/tear-sheet/liquidity vs forecast/stress/concentration | Theme split: three pages hardcode `bg-slate-900` card chrome (`volatility-sizing:852+`, `tear-sheet:708`, `liquidity:675+`) while the other three use `bg-white dark:bg-gray-800`. In light mode half the dashboard is permanently dark. | verified — skipped: coordinated theme-chrome convergence deferred |
| 01-I3 | `stress-testing:347`, `concentration:323` | `focus:outline-none` with no replacement focus ring — removes keyboard focus visibility entirely on Help buttons. | fixed |
| 01-I4 | `volatility-sizing:66`, `liquidity:41, 65, 81` | Explainer copy hardcodes portfolio size `"N = 14"` / `"all 14 active holdings"` — goes stale the moment a position is added/removed. Derive from `positions.length`. | fixed |
| 01-I5 | `volatility-sizing:803-845`, `forecast-risk:694-741` | Help buttons absolutely positioned `top-4 right-4` over MetricCards collide with the card's own icon slot — overlapping hit targets on four cards per page. | verified — skipped: needs MetricCard component change (system layer) |
| 01-I6 | `concentration:745` | Sector bars render `slice(0, 6)` with no overflow affordance — remaining sectors are silently dropped with no "+N more". | fixed |
| 01-I7 | error UX across set | Tear-sheet's loading/error states are exemplary (`:476-478` computed-state banner); concentration and forecast-risk swallow errors silently (01-B19, 01-B11). Standardize on one error/loading pattern (existing `LoadingState` component). | verified — partial: 01-B11/01-B19 error banners added; LoadingState standardization deferred |
| 01-I8 | `forecast-risk:220-225` | Icon-only close button has no accessible name — pairs with 01-B29 modal hardening. | fixed |
| 01-I9 | `stress-testing:955-958` | Scenario `<select>` embeds live impact numbers in option text — fine, but selected detail duplication with cards (`:872-884`) re-renders the same three rows twice; consider one source panel. | verified — skipped: detail-panel consolidation deferred (redesign) |

---

## 3. Optimizations

| ID | Location | Finding | Status |
|----|----------|---------|----------|
| 01-O1 | `forecast-risk:24` → `lib/export.ts:5-7` | Static `import { CSVExporter } from '@/lib/export'` pulls **jsPDF + xlsx + file-saver** into the forecast-risk chunk for a CSV button. Dynamic `import()` on click removes ~3 vendor libs from initial load. | fixed |
| 01-O2 | vol-sizing `:400`, stress `:618`, concentration `:362`, liquidity (`handleExportCSV`), tear-sheet `:336` | Five hand-rolled CSV builders (headers string + `join(',')`, no quoting) duplicate what `lib/export.ts` already offers. One shared exporter also fixes comma-injection on unquoted fields (custom scenario names with commas break stress CSV rows, `:624`). | verified — handoff: page-local `escapeCsvCell` applied to ticker cells (liq/conc/stress/vol); shared builder dedupe lives in `lib/export` (system layer); tear-sheet CSV has no free-text cells |
| 01-O3 | `volatility-sizing:313-315, 905-911`, `forecast-risk:449-451, 846-851` | Range sliders write state per `input` tick; each tick triggers a full analytics fetch (26-position steps, 30-day horizon steps). Debounce ~150-250ms or fetch on `change`/pointer-up. | verified — skipped: slider debounce deferred (per-tick fetch unchanged) |
| 01-O4 | `stress-testing:436-444` | `runAllScenarios` awaits four requests strictly sequentially — total wait is the sum. `Promise.allSettled` with the existing per-scenario try/catch semantics cuts wall time ~4× (mind backend concurrency; if serialized server-side, keep sequential and document it). | verified — kept sequential per the finding's own caveat; `Promise.allSettled` parallelization deferred |
| 01-O5 | mount effects listed in 01-B22 | The `AbortController` guard that fixes the race also prevents wasted responses from superseded model/horizon/positions changes — same diff serves correctness and cost. | verified — seq-guards added on all five fetch effects (01-B22); stale responses discarded after completion, `AbortController` cancel not added |

---

## 4. Recommended changes (priority order)

1. **01-B1 / 01-B2 / 01-B3 (P1)** — Delete liquidity's fabricated catch payload and market-cap/spread/score fallbacks; on error keep `error` and render nulls + flag (pattern already tested in `FabricatedFallbacks.test.tsx`). *File:* `liquidity/page.tsx:276-312`.
2. **01-B8 (P1)** — Send `market_shock`/`duration` to the API (extend `StressTestRequest`) or stop collecting them; until backend supports them, show computed shock from the response, not the form. *Files:* `stress-testing/page.tsx:465-478`, `schemas.py:250-253`.
3. **01-B11 + 01-B12 (P1)** — Clear `forecastData` on fetch failure (or keep table+cards consistent with an error state); replace the ±20% pseudo-CI with backend `confidence_interval` or remove the "90% CI" label. *File:* `forecast-risk/page.tsx:385-386, 441-443, 889-890`.
4. **01-B5 / 01-B6 / 01-B7 (P1)** — Concentration: remove `'0.09'` and `'1.0'` fallbacks; render `N/A`/loading skeleton instead of coercing `divScore` to `0.0` while `concentrationData` is null. *File:* `concentration/page.tsx:570-604, 820`.
5. **01-B9 / 01-B10 (P1)** — Derive the worst-case scenario's actual name from `stressResults`; compute average recovery over non-null values only (and state `n` tested). *File:* `stress-testing/page.tsx:638-639, 995, 1010`.
6. **01-B13 (P1)** — Fix `formatPercentage` contract: either always take fractions and scale only `< 1` non-zero **plus** document it, or split into `formatFractionPct` / `formatPctPoints` and pass the right one to `totalWeightChange` (values > 1 are legitimate). *File:* `volatility-sizing/page.tsx:368-374`.
7. **01-B4 + 01-B21 (P1/P2)** — Bind the risk badge to the same score thresholds as the heading; make null formatters return `N/A` (copy vol-sizing `:369-370`). *File:* `liquidity/page.tsx:283-284, 351-366, 831-832`.
8. **01-B14 / 01-B19 (P2)** — Surface `catch` as `runError` / page-level error banner on stress and concentration; stop `\|\| 0` coercions on metric values (pass `undefined`, let MetricCard show placeholder). *Files:* `stress-testing:424-495`, `concentration:402-483`.
9. **01-B22 + 01-O5 (P2)** — Add one `AbortController` (or request-sequence ref) per fetch effect across the six pages; cancel stress auto-run on unmount. *Files:* mount/param effects listed in 01-B22.
10. **01-B29 + 01-B28 + 01-I3 (P2)** — Modal hardening (dialog roles, Escape, focus return, labeled close) and convert clickable divs to `<button>`/`role="button"` + keyboard; replace `focus:outline-none` with `focus-visible:ring-*`. *Files:* all six modals; `forecast-risk:763-770`; `stress-testing:828-841`.
11. **01-O1 (P2 perf)** — `await import('@/lib/export')` inside `handleExport` on forecast-risk. *File:* `forecast-risk/page.tsx:24`.
12. **01-I1 / 01-I2 (P2)** — Extract shared `HelpExplainerModal`/`HelpBtn`; converge card chrome on the theme-aware `bg-white dark:bg-gray-800` variant. Lowest urgency but removes the largest cross-file duplication in the set.

---

## 5. AGENTS.md invariant check

| Invariant | Result |
|-----------|--------|
| Metric cards strictly live-API; fabricated metrics null + flag | **Violated** — 01-B1, 01-B2, 01-B3, 01-B5, 01-B6, 01-B7, 01-B15, 01-B21, 01-B27. |
| Zero-state portfolio weight = 100.00%, no 100000 fallbacks | **N/A** — no zero-state weight computation in this file set. |
| Diversification from true HHI; N≤1 ⇒ strictly 0% | **Partial** — N≤1 guard correct (`concentration:570`); null-data path fabricates `0.0%` (01-B7) and narrative HHI `0.09` (01-B5). |
| Inverse-vol weights w∝1/σ | **OK** — vol-sizing surfaces backend weights; explainer states the formula (`:73`). |
| en-IN / ₹ / Cr / L formatting | **Mostly OK** — liquidity `formatCurrency` fully en-IN (`:341-348`); vol-sizing missing `L` tier but uses `en-IN` locale for the base branch (`:376-383`); null→`₹0` violates honesty (01-B27). |
| TanStack cells read `row.original \|\| row` | **OK** — all audited columns comply (e.g. `liquidity:420+`, `concentration:497+`, `stress:565`). |
| Monthly returns geometric compounding | **OK** — `tear-sheet:324-332` uses `∏(1+r) − 1`. |
| No invented URLs | **OK** — none found in the six files. |
| NSE/BSE ticker formats (hyphens etc.) | **OK** — no client-side ticker regexes in this set. |

---

*End of report 01. Audit itself modified no product code; a subsequent surgical-fix pass applied the fixes recorded in the Status column above.*
