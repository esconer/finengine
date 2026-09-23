# 02 — Dashboard Pages Audit (B)

Wave-2 status: fixed=42 · verified-open=5 · refuted=0 · skipped=0 · total=47

- **ID:** 02-dashboard-pages-b
- **Date:** 2026-09-23
- **Lens:** Frontend code auditor (UI/UX + system design); read-only on product code
- **File set (actual line counts from files):**

| # | File | Lines |
|---|------|-------|
| 1 | frontend/src/app/dashboard/factor-exposure/page.tsx | 847 |
| 2 | frontend/src/app/dashboard/regime/page.tsx | 780 |
| 3 | frontend/src/app/dashboard/risk-studio/page.tsx | 673 |
| 4 | frontend/src/app/dashboard/risk-contribution/page.tsx | 610 |
| 5 | frontend/src/app/dashboard/page.tsx (main) | 604 |
| 6 | frontend/src/app/dashboard/realized-risk/page.tsx | 568 |
| 7 | frontend/src/app/dashboard/optimize/page.tsx | 464 |
| | **Total** | **4546** |

- **Imports skimmed for integration judgment:** `components/ui/MetricCard.tsx`, `components/ui/DataTable.tsx`, `components/charts/RiskMetricsDisplay.tsx`, `lib/api.ts`, `lib/store.ts`, `hooks/useAnalytics.ts`, `next.config.ts`, `types/index.ts`, `src/test/pages/FabricatedFallbacks.test.tsx`, plus backend route/service shapes in `backend/app/api/analytics.py`, `backend/app/services/{correlation,regime,volatility,tail_risk}_service.py`, `backend/app/models/schemas.py` (to verify API contracts).
- **Severity counts:** P0 = **0** · P1 = **15** · P2 = **19** · P3 = **13** · **Total 47 findings** (Bugs 24, Improvements 16, Optimizations 7).
- **Recently-fixed items not re-reported:** factor-exposure null alpha/beta/R² → N/A (works for `null`; B9 is a *different* path — backend sends `r_squared: 0.0` + `error`, which bypasses the fix); risk-studio GPD ξ/β `!= null` → '—' (lines 559–560 comply; B8 is the adjacent "Fat Tailed" readout).

---

## 1. Bugs (wrong math/formatting, fabricated values, races, contract mismatches)

### P1

**02-B1 · P1 · risk-studio/page.tsx:209–228 — `Promise.allSettled` swallows every API failure; error UI is dead code.**
All four endpoints are fetched with `allSettled`, so no rejection ever reaches the surrounding `try/catch`; `setError` (line 224) is effectively unreachable for network/HTTP errors. When all four endpoints fail, the page renders "successfully" with empty panels, a Correlation Regime card reading fabricated `NORMAL` (B2), and a "Fat Tailed: No" conclusion (B8). *Fix:* count `rejected` results (as `hooks/useAnalytics.ts:60–67` already does) and set an error state when all/any critical requests reject; surface per-panel errors.
Status: fixed - allSettled rejections counted; all-fail → setError, partial fail → console.warn (risk-studio fetch block); test: FabricatedFallbacks risk-studio nulls case.

**02-B2 · P1 · risk-studio/page.tsx:436 (also CSV line 310) — fabricates a healthy "NORMAL" correlation regime.**
`value={correlation?.alert_level || 'NORMAL'}` renders "NORMAL" when the correlation-stability request failed or returned no `alert_level`. This is a fabricated all-clear, violating the AGENTS invariant "fabricated metrics must be null + explicit flag, never invented numbers." *Fix:* `correlation?.alert_level ?? 'N/A'` (and same at line 310 in the CSV).
Status: fixed - `?? 'N/A'` at card (444) and CSV (318); test asserts queryByText('NORMAL') null.

**02-B3 · P1 · risk-studio/page.tsx:627–631 — wrong field name: regime-break badge can never fire.**
The badge reads `correlation?.breakdown_alert`, but the backend sends `is_regime_break` (`schemas.py:335`, `correlation_service.py:146`). The field is always `undefined`, so the UI shows **"Diversified Regime" even when `alert_level === "CRITICAL"`** — the exact moment the badge exists to warn about. *Fix:* bind to `correlation?.is_regime_break`; when correlation data is absent show a neutral/unknown chip, not "Diversified Regime".
Status: fixed - chip binds `correlation.is_regime_break`; `== null` → neutral N/A chip; test asserts no 'Diversified Regime'.

**02-B4 · P1 · risk-studio/page.tsx:257 — CVaR tail shares fabricated from volatility shares.**
`cvar_contrib: +(((riskContribution.positions.cvar_tail?.[ticker] ?? volShare ?? 0)) * 100)` — when `cvar_tail` is empty (backend returns `{}` whenever there are no tail observations, `analytics.py:1602–1610`), every "CVaR Share" bar silently equals the vol share. The sibling risk-contribution page correctly shows "Not enough tail observations" (`risk-contribution/page.tsx:215–220`); risk-studio invents data instead. *Fix:* `cvar_tail?.[ticker] ?? null` and omit/gray the CVaR bar (or the pair) when null.
Status: fixed - `cvar_contrib ?? null`; CVaR bar conditional (hasCvarTail), 'Not enough tail observations' empty state, CSV writes N/A.

**02-B5 · P1 · risk-studio/page.tsx:275–298 — null vol-cone quantiles coerced to 0%; failed fetch draws a full 0% cone.**
Backend explicitly returns `null` quantiles + `insufficient_data: true` for thin windows (`volatility_service.py:255–266, 275–282`), and the page maps them via `+(w.min * 100 || 0)` — `null * 100 = 0` — plotting fabricated **0.0%** P-bands and a fabricated `realized: 0%` (line 283; tooltip line 596 then shows "Realized: 0%" because `0 != null`). Worse, when the `/vol-cone` request *failed* (`volCone === null`), the fallback branch (286–298) still builds five all-zero rows, so the chart renders flat 0% ceiling/floor lines as if real. The `insufficient_data` flag is never read. *Fix:* `w.min != null ? +(w.min * 100).toFixed(1) : undefined` (same for all bands; keep `realized` null-aware like line 295 already does), honor `insufficient_data`, and render an explicit empty state when `volCone` is null.
Status: fixed - null-preserving `pct()` (→undefined), `insufficient_data` honored, vol-cone-empty / vol-cone-insufficient empty states; test: vol-cone-empty.

**02-B6 · P1 · risk-studio/page.tsx:284, 296 — GARCH forecast key mismatch: the promised GARCH line never renders.**
Page reads `volCone?.garch_forecast_vol`; the backend `/vol-cone` route returns `current_forecast: { model, annualized_vol, … }` (`volatility_service.py:317–329`, `analytics.py:2149–2175`). The key exists in neither the payload nor `types/index.ts` (`garch_forecast`), so `garch` is always `undefined`: the "Realized vs GARCH" chip (line 576), legend entry (611), and copy "alongside forward GARCH forecast" (581) advertise a series that can never appear. *Fix:* `volCone?.current_forecast?.annualized_vol` (and decide whether it is a single scalar overlay, not a per-window point).
Status: fixed - GARCH chip reads `current_forecast.annualized_vol` as a single scalar overlay.

**02-B7 · P1 · risk-studio/page.tsx:278–282, 597–599, 608–610 (copy 96–101) — true min/max relabeled as "P10"/"P90".**
Backend computes `min = np.min(...)` and `max = np.max(...)` of the rolling vol series (`volatility_service.py:246, 250`) — not the 10th/90th percentiles. The page maps them to `p10`/`p90` and labels them "P10 (Min)" / "P90 (Max)" / "P90 (Ceiling)" / "P10 (Floor)", and the explainer claims "historical percentiles (P10 to P90)". A user reading "P90" is shown a percentile statistic that was never computed. *Fix:* either label honestly as "Min/Max envelope" everywhere, or ask the backend for true P10/P90 and keep the labels.
Status: fixed - band keys renamed min/max; labels/explainer say Min/Max envelope (no P10/P90 claims).

**02-B8 · P1 · risk-studio/page.tsx:562 — "Fat Tailed: No" rendered when the metric is unknown.**
`(tailRisk?.is_fat_tailed !== undefined ? … : tailRisk?.gpd_parameters?.is_fat_tailed) ? 'Yes' : 'No'` — when the tail-dependence request failed (`tailRisk === null`) both reads are `undefined`, falsy → **"Fat Tailed: No"** — a statistical conclusion fabricated from missing data, sitting next to honest "—" ξ/β readouts (559–560). *Fix:* `const ft = …; <strong>{ft == null ? '—' : ft ? 'Yes' : 'No'}</strong>`.
Status: fixed - `fatTailed` hoisted const, null → '—'; test asserts em dash, not Yes/No.

**02-B9 · P1 · factor-exposure/page.tsx:499–506, 605, 617–624, 716–741, 823–829 — backend `error` payload ignored; R²=0.0 rendered as live "Weak" model fit.**
On empty portfolio / no price data the backend returns `r_squared: 0.0` **plus** an `error` string (`analytics.py:614–623, 632–642`). The page never reads `factorData.error`, and because `0.0 != null`, it renders: R-Squared card **"0.000"**, Model Fit **"Weak"**, Systematic **0.0%** / Idiosyncratic **100.0%** progress bars, ρ=0%, and the insight "0.0% of return swings are dictated by…". The intentional null→N/A fix (and `FabricatedFallbacks.test.tsx:53–80`, which mocks `r_squared: null`) does not cover this contract. This also flashes on every mount while positions hydrate, because of B11's empty-tickers fetch. *Fix:* if `data.error` present (or `positions` empty), show the error and N/A all R²-derived values regardless of `r_squared === 0.0`.
Status: fixed - `FactorData.error` gates rSquared to null; factor-error-banner + Try Again; test: error payload → banner, no '0.000'/'Weak'.

**02-B10 · P1 · factor-exposure/page.tsx:593, 680–694, 809–812 — negative alpha renders as "+-X%", always-green bar, and "Positive Alpha"/"outperformance" copy.**
- Line 593: `` `+${(portAlphaAnn * 100).toFixed(2)}%` `` → for α = −3.2% the card shows **"+-3.20%"** (MetricCard passes strings through, `MetricCard.tsx:51–54`).
- Lines 681–682: same forced `+` on daily and annualized values; line 680 hardcodes green text; line 690 forces `Math.max(portAlphaDaily * 20000, 10)` → a **negative alpha still shows a 10%-wide green bar**; line 694 labels it **"Positive Alpha"** whenever alpha is non-null.
- Lines 809/812: insight header forces `+`, and the body unconditionally claims "strong active outperformance (+…)" even when the numbers are negative.
*Fix:* sign-aware formatting (no forced prefix; `>= 0 ? green : red`), label from sign, drop the `max(..., 10)` floor, and gate the narrative on `portAlphaAnn > 0` vs `< 0` vs neutral.
Status: fixed - sign-aware alpha everywhere (card/loading/interpretation/insight): no forced `+`, red/green from sign, 10% floor dropped, positive/negative/neutral copy + N/A.

**02-B11 · P1 · factor-exposure/page.tsx:305–314 with 282–303 — double fetch on every mount + out-of-order response race (stale data under a fresh lookback label).**
Effect A (305–308) always calls `fetchFactorData()` with whatever `positions`/`lookbackDays` the closure captured (initially empty → `tickers=''` → B9 error payload), and effect B (310–314) runs on mount too when positions are already hydrated — two requests minimum. Neither request is aborted or sequenced, so changing lookback 756d→126d can land responses out of order: the slower 756d response overwrites state while the hero chip (line 531) and CSV filename (375) say "126 days". *Fix:* one effect keyed on `[positions, lookbackDays]` with an `AbortController`/request-id guard, and skip fetching while `tickers === ''`.
Status: fixed - single effect `[positions, lookbackDays]` + `reqIdRef` stale-response guard (cleanup bumps), empty-tickers skip; mount fetchPortfolio kept on `[]`.

**02-B12 · P1 · dashboard/page.tsx:453–454 — `|| 0` fabricates 0.00% VaR/CVaR and a green "Low Risk" verdict.**
`var_95: analyticsData.realizedRisk?.portfolio?.var_95 || 0, cvar_95: … || 0` — when realized-risk is still loading under a finished `analyticsLoading` pass or its `allSettled` slot rejected (partial failure is only `console.warn`ed, `useAnalytics.ts:65–67`), `RiskMetricsDisplay` receives `0`, formats **"0.00%"** and `getVaRInterpretation(0)` → green **"Low Risk"** (`RiskMetricsDisplay.tsx:88–93, 163–168`). Coerced-zero risk numbers are exactly the fabrication class AGENTS forbids (the adjacent forecast fields at 456–457 correctly pass `null`). *Fix:* pass `?? null` and widen `RiskMetricsDisplay` var/cvar props to `number | null` so it renders N/A.
Status: fixed - dashboard passes `?? null`; RiskMetricsDisplay props/defaults widened to `number | null`, `getVaRInterpretation(null)` → N/A; test: null var_95 path.

**02-B13 · P1 · optimize/page.tsx:107–139 (rendered 328–419) — the "Markowitz Efficient Frontier" and "Current Portfolio" points are synthetic numbers.**
- `frontierPoints` (109–119): 21 points fabricated as `vol*0.82 + vol*0.7*f` and `ret*0.7 + ret*0.8*√f` around the *single* optimized result — mathematically unrelated to any efficient frontier.
- `currentPoint` (132–139): "Current Portfolio (Pre-Rebalance)" is `optimal_vol * 1.08` and `optimal_ret * 0.92` — the current portfolio's actual risk/return is never fetched.
The section is titled "Markowitz Efficient Frontier & Portfolio Positioning" (334) with a legend implying real positioning (340–353); the only hint is an internal comment "Simulated Frontier Points" (397). This is fabricated analytics shown to the user. *Fix:* remove the synthetic curve/current point (show only the real optimal point + a real current-portfolio point computed from `current_weights` and the covariance matrix, or fetched from the API), or clearly label the curve "illustrative".
Status: fixed - synthetic `frontierPoints`/`currentPoint` deleted; chart shows only the real optimal point (legend trimmed, retitled Optimal Portfolio Risk/Return); test asserts no Markowitz/Current-Portfolio points.

**02-B14 · P1 · optimize/page.tsx:111–112, 124–126, 135–136 — null expected return/vol coerced to 0 → points plotted at fabricated (0%, 0%).**
Backend single-holding path can return `expected_annual_return: null` and `expected_annual_volatility: null` (`analytics.py:1677–1690`). JS arithmetic on `null` yields `0` (`null * 100 → 0`), so `optimalPoint`/`currentPoint`/`frontierPoints` all collapse to the origin while the MetricCards honestly show "N/A" (102–105, 248–253) — chart and cards contradict each other. *Fix:* if either expected value is null, render an explicit "frontier unavailable" empty state instead of points.
Status: fixed - `hasFrontierCoords` guard → frontier-empty empty state on null `expected_annual_*`; test: no fabricated (0,0) points.

**02-B15 · P1 · risk-contribution/page.tsx:561–593 — divergence insight uses `Math.abs(diff)` with "…% MORE to your tail losses": sign can invert the claim.**
The code sorts by *signed* `diff = cvar − vol` (562–567) but only enters the symmetric branch when `|max diff| < 0.05` (568). If every asset's tail share is *below* its vol share (largest diff = −0.06), it still renders the rose "tail-heavier" card: "On the worst crash days, **X** contributes **+6.0% MORE** to your tail losses…" — the opposite of the data. *Fix:* use the max-diff asset only when `tailHeavier.diff > 0.05`; otherwise (including all-negative cases) show the symmetric message (or a "tail-lighter" variant).
Status: fixed - heavy branch only when `tailHeavier.diff > 0.05`, signed display (no Math.abs), all-negative → Symmetric; test covers all-negative case.

### P2

**02-B16 · P2 · risk-contribution/page.tsx:310 — CSV fabricates `0.00%` CVaR shares.**
`const cvarShare = data.positions.cvar_tail[ticker] ?? 0` — when tail attribution is unavailable (`cvar_tail === {}`, `analytics.py:1610`), the export still writes `0.00%` per ticker while the on-screen panel honestly says "Not enough tail observations". *Fix:* write `N/A` (or omit the column) when the map has no entry.
Status: fixed - CSV writes N/A for missing cvar_share (never 0.00%); ticker/sector/topDriver routed through escapeCsvCell.

**02-B17 · P2 · regime/page.tsx:513, 517, 521, 528–539 — `?? 0` fabricates 0% regime probabilities for missing keys.**
Backend keys come from `label_map` (`regime_service.py:248–251`): normally `crisis/calm/bull`, but with a non-3-state fit they become `state_0/state_1/…` (line 47). In that case all three UI reads miss, `?? 0` renders **"Calm: 0% Bull: 0% Crisis: 0%"** and an empty stacked bar — three invented zeros instead of the real probabilities hiding under `state_N`. *Fix:* iterate `Object.entries(data.regime_probabilities)` so every key renders; show "N/A" per label only when genuinely absent, never `?? 0`.
Status: fixed - label row + stacked segments iterate `Object.entries(regime_probabilities)`; unknown keys via regimeStyle fallback; test: state_N 62.5/37.5, no fabricated 0% buckets.

**02-B18 · P2 · dashboard/page.tsx:252–269 — CSV export bypasses the API client, has no `ok` check, and is tied to a hardcoded localhost rewrite.**
`fetch('/api/v1/portfolio/export/csv')` + unconditional `response.text()`: on a 4xx/5xx the JSON/HTML error body downloads silently as `portfolio-….csv` (only `console.error`, no user feedback). It also bypasses `portfolioApi.exportCSV` (`lib/api.ts:181`) and the axios interceptor's error mapping, and depends on `next.config.ts:31–32` rewriting to `http://localhost:8000` while `apiClient` uses `NEXT_PUBLIC_API_URL` — exports break the moment the API isn't local while every other call still works. *Fix:* route through `portfolioApi` (or axios with `responseType: 'text'`), check `response.ok`, and surface failures.
Status: fixed - routes through `portfolioApi.exportCSV`, validates empty body, exportError banner + dismiss above the positions table.

**02-B19 · P2 · realized-risk/page.tsx:117–126, 300–302 — displayed date range is UTC-shifted and never applied to any request.**
`toISOString().split('T')[0]` yields UTC dates (in IST, morning sessions show yesterday's date for both endpoints), and `dateRange` is **only** rendered in the hero chip "Period: {start} to {end}" (301) — no fetch on this page (or the shared hooks) ever receives it; the API uses its own defaults. The chip implies the user is looking at a selected window that does not exist. *Fix:* build local dates (`toLocaleDateString('en-CA')`), and either wire `start/end` into `analyticsApi.getRealizedRisk` (params exist, `api.ts:330–337`) or relabel the chip to "Last 12 months (default)".
Status: fixed - fabricated Period chip removed entirely (dateRange state + derive-effect deleted; server resolves the window); real Data Span chip (data_range) kept.

**02-B20 · P2 · realized-risk/page.tsx:78–93 (esp. 79, 82–83) — "Rolling 21-Day Volatility" chart emits 10–20-observation points; `prev || 1` fabricates a ₹1 baseline.**
Points start as soon as `returns.length >= 10` but each point uses `slice(-21)` — the first ~11 points are 10–21-day vols under a chart titled "Rolling 21-Day Volatility (%)" (451). Line 79 `const prev = performanceData[i-1].portfolio_value || 1` treats a missing/zero previous value as ₹1, producing a one-period return of `(val − 1)/1` and a vol spike. *Fix:* require `returns.length >= 21` for the first point (or title it "up to 21-day"), and skip the iteration when `prev` is falsy instead of substituting 1.
Status: fixed - first point requires `returns.length >= 21`; falsy `prev` skipped (no ₹1 baseline).

**02-B21 · P2 · regime/page.tsx:434 and risk-contribution/page.tsx:428 — refresh blanks the entire page; refresh-error discards good data.**
Main content is gated on `!loading && !error && data`. Clicking the refresh buttons (regime:391–398, risk-contribution:382–389) sets `loading=true`, unmounting every metric/table/chart until the response lands (full-page flash); if the refresh then fails, previously-good `data` stays mounted but hidden behind the error banner. *Fix:* keep rendering `data` during refresh with only a subtle in-flight indicator (factor-exposure already does this pattern correctly via per-card `loading` props), and on refresh failure keep stale data + show the banner.
Status: fixed - main content gated on `data` (not `!loading`) on both pages; refresh keeps stale data mounted; MetricCard skeletons removed from the refresh path.

### P3

**02-B22 · P3 · dashboard/page.tsx:585 — "Weight Drift" hides under-allocation.**
`Math.max(0, (portfolioMetrics.totalWeight − 1) * 100)` clamps negatives: a portfolio invested at 60% shows **"0.0% Weight Drift"** — indistinguishable from perfectly allocated. *Fix:* show signed drift (or two-sided label "Over/Under-allocated").
Status: fixed - Math.max clamp removed; signed drift renders under- (and over-) allocation honestly.

**02-B23 · P3 · realized-risk/page.tsx:537 — insight hardcodes "over the 252-day lookback window".**
The sentence is shown whenever max drawdown < −5%, regardless of the actual `realizedRisk.data_range` the hero just displayed (303–307), which can be shorter/longer. *Fix:* interpolate `data_range.start → end` or drop the window claim.
Status: fixed - insight interpolates `data_range.start → end` (fallback "the available history window").

**02-B24 · P3 · risk-studio/page.tsx:241–245 (and `||` fallbacks at 403, 414, 425) — `fmtPct` unit heuristic and falsy fallbacks.**
`Math.abs(val) <= 1.0 && val !== 0 ? val * 100 : val` guesses the unit from magnitude: any genuine percent value in (0, 1] is double-scaled to 100×, and an exact `0` prints `"0.00%"` instead of N/A. Lines 403/414/425 use `||` where `??` is meant (`portfolio_volatility` at 403 is a key the backend never sends — dead fallback). *Fix:* standardize the API on fractions, format with `??`-null checks only, delete the dead key fallback.
Status: fixed - fmtPct fraction-only (magnitude heuristic deleted); card fallbacks `??` + 'N/A'; dead `portfolio_volatility` key removed.

---

## 2. Improvements (UI/UX + system design)

### P2

**02-I1 · P2 · factor-exposure:126–253, regime:111–188, risk-studio:119–196, risk-contribution:113–190 — ~900 lines of copy-pasted modal machinery.**
`HelpExplainerModal` + `HelpBtn` + `EXPLAINERS` dict are duplicated four times, differing only in accent color (teal/sky/indigo/rose) and content schema (`what/how/why/interpretation` vs `what/howInferred/…`). Any a11y fix (I2) must be applied four times. *Fix:* one shared `ExplainerModal`/`HelpBtn` in `components/ui/` with a `tone` prop and a single content type; keep per-page dictionaries.
Status: verified

**02-I2 · P2 · all four HelpExplainerModals (factor-exposure:138, regime:116, risk-studio:124, risk-contribution:118) + factor-exposure HelpBtn:247 — modal a11y gaps.**
No `role="dialog"`/`aria-modal`, no Escape-to-close, no focus trap or focus restore, overlay click doesn't dismiss. The factor-exposure `HelpBtn` uses `focus:outline-none` with no `focus-visible` ring (invisible keyboard focus) and has only `title`, no `aria-label`, unlike its three siblings (regime:183, risk-studio:191, risk-contribution:185). *Fix:* shared modal with keyboard/focus handling; give every HelpBtn `aria-label`.
Status: verified

**02-I3 · P2 · risk-studio:55–56, 79, 87; risk-contribution:49, 57, 65, 73, 109; regime:55, 63, 92 — explainer copy asserts fabricated portfolio-specific "facts".**
Static examples read as live statements about *this* portfolio: "18.08% indicates normal fluctuation…", "Motherson (19.9% risk share vs 13.6% capital weight) is the primary engine", "Redington (1.70x)…", "74.0% stability indicates…", "Your portfolio annualized +45.3%…". These are hardcoded constants presented in present tense — the same fabrication class as mock metric deltas, just relocated to help text. *Fix:* prefix with "e.g." / "for illustration", or interpolate live values.
Status: fixed - all cited explainers (risk-studio, risk-contribution, regime) prefixed with "e.g." so static examples no longer read as live portfolio facts.

**02-I4 · P2 · factor-exposure/page.tsx:298–299 — fetch failure is invisible.**
Errors go to `console.error` only; there is no error banner, retry affordance, or "stale data" marker anywhere on the page (regime:404–420 and risk-contribution:398–414 both have banners + Try Again). The user just sees a full grid of N/A. *Fix:* add the same error banner + retry pattern used on sibling pages.
Status: fixed - fetchError state → factor-error-banner amber banner + Try Again (handleRefresh) above the factor grid.

**02-I5 · P2 · dashboard/page.tsx:226–236 — dead Edit/Trash action buttons.**
Both buttons render with no `onClick`, implying position editing/deletion that does nothing from this table. *Fix:* wire them (delete already exists in the store, `store.ts:184`) or remove the Actions column until implemented.
Status: fixed - Actions column and dead Edit/Trash2 imports removed from positionColumns.

**02-I6 · P2 · dashboard/page.tsx:304–307 — static "Live Data Active" status.**
The green dot and label are unconditional copy; they ignore `useUIStore.liveDataMode` and any websocket connection state (`store.ts:80–81, 356`). Presented as a system status it is placeholder UI. *Fix:* drive from `liveDataMode`/connection state, or drop the claim.
Status: fixed - chip reads `useUIStore().liveDataMode`: 'Live Data Active' / 'Live Data Off'.

**02-I7 · P2 · dashboard/page.tsx:33–37 vs regime/page.tsx:223–248 — divergent, partially-wrong regime style maps.**
Dashboard `REGIME_CHIP` has `calm/volatile/crisis` but **no `bull`** → a bull regime falls back to a gray chip (387–389) while the regime page styles bull blue; conversely the regime map includes `volatile`, which the backend never emits (labels are only `crisis/calm/bull/state_N`, `regime_service.py:53–57`). Two maps, each wrong in opposite directions. *Fix:* export one shared `REGIME_STYLES` with exactly the backend's label set.
Status: fixed - maps aligned to backend labels (dashboard REGIME_CHIP volatile→bull, regime REGIME_STYLES volatile removed). HANDOFF: shared-module extraction blocked (lib/ is Wave 2A).

**02-I8 · P2 · five bespoke CSV builders — factor-exposure:359–378, regime:304–343, risk-studio:301–336, risk-contribution:295–335, dashboard:252–269 vs realized-risk's shared `CSVExporter` (realized-risk:12, 135–139).**
Five hand-rolled variants (two `Blob`, three `data:`+`encodeURI`) with no field quoting — any future value containing a comma (messages, custom names) silently corrupts columns. *Fix:* extend `lib/export` with a `rows: string[][]` API (header rows + metadata supported) and migrate all five; quote fields containing `,`.
Status: fixed - escapeCsvCell wired into risk-studio, risk-contribution, regime builders; dashboard routes through portfolioApi.exportCSV (B18). HANDOFF: factor-exposure builder (374–386) still hand-concatenated.

**02-I9 · P2 · risk-studio/page.tsx:463–488 vs 518–556 — inconsistent empty/error states across the 2×2 canvas.**
The copula panel has an explicit empty state (552–555); the Euler chart renders axes-only on empty data with no message; the vol cone draws the fabricated zero cone (B5); the correlation panel shows N/A values but still renders "Diversified Regime" chrome (B3). After B1's error fix, each panel needs a uniform empty/error treatment. *Fix:* one `<PanelState empty|error>` helper used by all four panels.
Status: fixed - per-panel empty states added (euler-empty, vol-cone-empty/insufficient, correlation N/A via B2/B3 fixes). HANDOFF: shared PanelState helper skipped — four one-off empty branches were smaller.

**02-I10 · P2 · optimize/page.tsx:169 — 5 strategy cards forced through `lg:grid-cols-4`.**
`STRATEGIES` has five entries (49–80) but the grid is `sm:2 / lg:4`, leaving an orphaned fifth card on its own row at lg. *Fix:* `lg:grid-cols-5` (or `grid-cols-3` at lg).
Status: fixed - grid is now `lg:grid-cols-5`.

### P3

**02-I11 · P3 · dashboard/page.tsx:394–396 + 585 — "Weight Drift" metric is confusing even when correct** (see B22): consider renaming to "Over-allocation" or showing signed drift with a caption.
Status: fixed - resolved with B22: signed drift replaces the clamped 0.0%, so under-allocation is no longer hidden.

**02-I12 · P3 · factor-exposure/page.tsx:664, 690 — progress-bar scales are arbitrary and undocumented.**
Beta bar = `|β| × 50` (β=1.0 fills half the track); alpha bar = `α × 20000` floored at 10%. No axis, tooltip, or caption explains either mapping, so bar lengths aren't interpretable (and the alpha floor is part of B10). *Fix:* anchor beta at a labeled midpoint (0 / 1.0 marker) and derive alpha width from a documented range, or drop the bars in favor of the numbers.
Status: verified

**02-I13 · P3 · regime/page.tsx:459–464, 475–480 — IIFEs run `data.states.find(...)` twice per render inside JSX.**
Hoist `const currentState = data.states.find(...)` once next to `current` (291) and reuse it for both cards (and the "now" row logic at 622–623).
Status: fixed - `currentState` hoisted to a single find; both IIFEs (Benchmark Vol, Days in Regime) replaced.

**02-I14 · P3 · dashboard/page.tsx:301 and optimize/page.tsx:157 — stale copy.**
"Real-time risk analysis" sits above a page whose timestamps are mount-time fetches; the optimizer hero says "**four** strategies, one click" while `STRATEGIES` lists five (49–80). *Fix:* update copy.
Status: fixed - dashboard subtitle → "Portfolio analytics and risk management"; optimizer hero → "five strategies".

**02-I15 · P3 · realized-risk/page.tsx:469–471, 498–500 — empty state conflated with loading.**
Charts show "Loading volatility history…" / "Loading drawdown history…" whenever `series.length === 0`, forever — including after a failed or legitimately empty fetch (`usePerformanceData`'s `loading` flag is never destructured, line 46). *Fix:* branch on hook `loading` vs empty → "No performance history yet".
Status: fixed - `perfLoading` destructured; loading → 'Loading...', settled-empty → 'No performance history yet' on both charts.

**02-I16 · P3 · risk-contribution/page.tsx:215–220 — CVaR-specific empty copy reused for volatility & sector panels.**
`ContributionBars` always says "Not enough tail observations to attribute this model." even when it's the *volatility* (498) or sector (547) panel that's empty — wrong explanation. *Fix:* accept an `emptyMessage` prop.
Status: fixed - ContributionBars gained `emptyMessage?`; vol and sector panels get their own copy (CVaR text no longer reused).

---

## 3. Optimizations

### P2

**02-O1 · P2 · dashboard/page.tsx:157–238 — `positionColumns` rebuilt every render.**
The column array is a plain per-render declaration closing over `totalValue`; each store tick hands `DataTable` a new `columns` identity, re-running `useReactTable` (`DataTable.tsx:47–65`) even when data is unchanged. The factor-exposure page already does this correctly with `useMemo` (factor-exposure:381–497). *Fix:* `useMemo(..., [totalValue])`.
Status: fixed - `positionColumns` wrapped in useMemo on `[totalValue]`.

**02-O2 · P2 · risk-studio/page.tsx:252–298 — `eulerPositions` and `coneChartData` computed every render without `useMemo`.**
Both rebuild on any state change (modal open at 202, refresh flag at 200) — pointless object churn feeding Recharts. *Fix:* wrap in `useMemo` with `[riskContribution]` / `[volCone]` deps (same memo boundary as `frontierPoints` already uses at 107).
Status: fixed - `eulerPositions` and `coneChartData` wrapped in useMemo on `[riskContribution]` / `[volCone]`.

**02-O3 · P2 · dashboard/page.tsx:75–88 — regime + risk-contribution fetches have no unmount guard.**
Both promises call `setRegimeInfo`/`setRiskDrivers` with no `isMounted`/AbortController — contrast `usePerformanceData` (`useAnalytics.ts:111–141`), which does it right. Fast navigating away and back can double-fire and set state on an unmounted tree. *Fix:* mirror the hook's mounted flag (or lift both widgets into a hook).
Status: fixed - isMounted flag guards both regime and risk-contribution setState paths.

### P3

**02-O4 · P3 · realized-risk:14–23, risk-studio:26–38 — static Recharts imports.**
Both pages import chart primitives eagerly; `next/dynamic` for the chart sections would trim route chunks. Low priority — the app router already code-splits per page and Recharts is a shared dependency.
Status: verified

**02-O5 · P3 · factor-exposure/page.tsx:508, 566–571 — `limitedHistoryCount` filter + ticker join re-run every render.**
Trivial, but it's derived state like `positionData`; hoist into a `useMemo` on `[positionData]` (banner and count share it).
Status: fixed - `limitedPositions` useMemo on `[positionData]`; banner and count both read it (hasError gated).

**02-O6 · P3 · dashboard/page.tsx:133–146 — `portfolioMetrics` object rebuilt each render.**
Neighbors `diversificationScore` (105) and `totalCost` (121) are memoized; this object feeding four MetricCards isn't. *Fix:* `useMemo` over the same deps for consistency.
Status: fixed - `portfolioMetrics` (incl. totalGainLoss/Pct) wrapped in useMemo alongside the neighboring memoized values.

**02-O7 · P3 · dashboard/page.tsx:75–88 vs regime:268–284 / risk-contribution:254–270 — identical endpoints refetched per navigation; existing cache unused.**
The dashboard quietly fetches `/analytics/regime` and `/analytics/risk-contribution` on every mount, and each destination page fetches them again on visit — while `useAnalyticsStore`'s 5-minute TTL cache (`store.ts:275–320`) sits unused by all of them. *Fix:* route these reads through the (or a) shared cache with explicit invalidation on refresh buttons.
Status: verified

---

## 4. Recommended changes (prioritized top 10)

| # | Sev | Finding | File:line | What to do |
|---|-----|---------|-----------|------------|
| 1 | P1 | 02-B12 | dashboard/page.tsx:453–454 | Pass `?? null` for `var_95`/`cvar_95` (widen `RiskMetricsDisplay` props to `number \| null`) so failed/absent realized-risk renders N/A instead of fabricated **0.00% "Low Risk"**. |
| 2 | P1 | 02-B13/B14 | optimize/page.tsx:107–139 | Delete the synthetic frontier curve and the `optimal×1.08/0.92` "current" point (or compute the current point from real `current_weights` + covariance); gate the chart when `expected_annual_*` are null instead of plotting (0,0). |
| 3 | P1 | 02-B3 + B2 | risk-studio/page.tsx:627–631, 436 | Bind the badge to backend `is_regime_break`; replace `alert_level \|\| 'NORMAL'` with `?? 'N/A'` so a failed correlation fetch can never advertise an all-clear. |
| 4 | P1 | 02-B10 | factor-exposure/page.tsx:593, 680–694, 809–812 | Sign-aware alpha everywhere: no forced `+` prefix, color/label from sign, remove the 10% green-bar floor, and gate the "strong outperformance" narrative on `portAlphaAnn > 0`. |
| 5 | P1 | 02-B9 | factor-exposure/page.tsx:499–506, 605, 617–624 | Read `factorData.error`: on the backend's `r_squared: 0.0 + error` payloads show an error/N/A state instead of R² 0.000 / "Weak" / 0%-100% bars (closes the gap the `r_squared: null` fix doesn't cover). |
| 6 | P1 | 02-B5/B6/B7 | risk-studio/page.tsx:275–298, 284, 596–610 | Null-preserving vol-cone mapping (`!= null ? ×100 : undefined`), honor `insufficient_data`, read `current_forecast.annualized_vol` for GARCH, and relabel min/max honestly (or fetch true P10/P90). |
| 7 | P1 | 02-B15 | risk-contribution/page.tsx:561–593 | Only show the "contributes +X% more" card when the max signed diff is actually `> 0.05`; all-negative diffs must take the symmetric branch. |
| 8 | P1 | 02-B1 + B21 | risk-studio/page.tsx:209–228; regime:434; risk-contribution:428 | Aggregate `allSettled` rejections into a real error state; stop gating page content on `!loading` — keep stale data visible during refresh (factor-exposure's per-card `loading` is the model). |
| 9 | P1 | 02-B11 | factor-exposure/page.tsx:305–314 | Collapse the two fetch effects into one keyed on `[positions, lookbackDays]` with an abort/sequence guard; never fetch with an empty ticker list. |
| 10 | P2 | 02-I1 + I2 | factor-exposure:126–253 + 3 siblings | Extract one `ExplainerModal`/`HelpBtn` with `role="dialog"`, Escape, focus trap, and `aria-label` — fixes a11y once instead of four times. |

---

### AGENTS.md invariant compliance (this file set)

- **Zero-state weight 100.00%** — **Compliant.** dashboard/page.tsx:175–181 derives `market_value / totalValue`, which is exactly 1.0 for the sole asset on an empty→first-asset portfolio; no hardcoded 100000-style fallbacks exist on these pages.
- **Diversification from true HHI, N≤1 → strictly 0%** — **Compliant.** dashboard/page.tsx:105–119: early-returns `0` for `positions.length <= 1` (line 106), computes `hhi = Σw²` (113) and `N_eff = 1/HHI` (114). Minor note: the `sectorMultiplier` (117) starts at its 0.25 floor until async `sectorData` lands, so the score can transiently under-report before sectors hydrate (card is only skeleton-gated by `analyticsLoading`).
- **Inverse-volatility weights (w∝1/σ)** — **Not applicable / no violation here.** optimize/page.tsx performs zero client-side allocation math: weights and trades are consumed verbatim from `POST /analytics/optimize/run` (page:92–93, 291–305; backend `analytics.py:1702–1726`). The offered strategies (page:49–80) are HRP/Min-Vol/Max-Sharpe/Min-CVaR/Black-Litterman — no risk-parity strategy is exposed on this page; true inverse-vol parity lives in the backend vol-sizing service (`analytics_engine.py:634`). The page's actual quantitative sin is fabricated chart geometry (B13/B14), not wrong weights.
- **True risk contributions** — **Compliant on data path.** risk-contribution/page.tsx renders backend Euler shares verbatim (`analytics.py:1594–1598`, CVaR shares 1602–1610); the only distortion is the display-level sign bug in the insight card (B15) and the CSV `?? 0` (B16).
- **Metric cards strictly live-API-driven (no mock deltas)** — **One violation:** risk-studio's Correlation Regime card fabricates `NORMAL` (B2). All other cards on these pages render API values or N/A; no placeholder delta chips found. Explainer *prose* still carries hardcoded "live-sounding" numbers (I3) — outside the metric-card rule but worth fixing.
- **Null + explicit flag, never invented numbers** — Violations: B4, B5, B8, B9, B14, B16, B17, B12 (coerced zeros / fabricated conclusions). The intentionally-fixed paths (factor-exposure `null` alpha/beta/R² → N/A; risk-studio ξ/β `!= null` → '—') were verified intact and are **not** re-reported.
- **TanStack cells read `row.original || row`** — **Compliant** in all three table-using pages: dashboard:162/174/189/201/213/225, factor-exposure:387/409/425/447/470, realized-risk:158/181/192/209/221/243/255. (optimize:291 and regime:620 are plain `<table>`s — invariant N/A.)
- **NSE/BSE ticker formats (hyphens)** — No ticker validation/regex on these pages; hyphenated tickers (e.g. `BAJAJ-AUTO.NS`) pass through untouched. Ticker suffix stripping in risk-studio (254, 525, 532) only removes `.NS`/`.BO` and preserves hyphens. **Compliant.**
- **en-IN / ₹ / Cr / L formatting** — Dashboard money cells use `en-IN` with `₹` (192, 339) and `MetricCard prefix="₹"` gets Cr/L handling in the shared component (`MetricCard.tsx:38–41`). Price cell (204) uses `₹toFixed(2)` without grouping — fine at share-price scale. **Compliant.**
