# 05 — Component & Design-System Audit (FinEngine Frontend)

Wave-2 status: fixed=34 · verified-open=0 · refuted=0 · skipped=4 · total=38

- **Report ID:** 05
- **Date:** 2026-09-23
- **Scope:** Component/design-system layer — `frontend/src/components/` (layout, ui, portfolio, charts), `frontend/src/app/globals.css`, design-token discipline sampled across pages, component tests in `frontend/src/test/components/`.
- **Method:** Line-by-line read of every file listed below; read-only. Supporting reads (not in scope for line review): `lib/store.ts`, `hooks/useRealTime.ts`, `app/portfolio/manage/page.tsx`, sample page call-sites of `MetricCard`, all 4 component tests, `package.json`.
- **Mode:** READ-ONLY except this file. No product code touched, no commits.

## File set & line counts (actual, `Get-Content | Count`)

| File | Lines |
|---|---|
| layout/DashboardLayout.tsx | 176 |
| layout/Sidebar.tsx | 270 |
| layout/Header.tsx | 196 |
| ui/MetricCard.tsx | 131 |
| ui/DataTable.tsx | 254 |
| ui/LoadingState.tsx | 271 |
| ui/NotificationSystem.tsx | 273 |
| ui/ExportPanel.tsx | 304 |
| ui/dialog.tsx | 95 |
| ui/select.tsx | 83 |
| portfolio/AddPositionModalSimple.tsx | 352 |
| portfolio/EditPositionModal.tsx | 344 |
| portfolio/PortfolioDropzone.tsx | 309 |
| portfolio/PortfolioTable.tsx | 269 |
| portfolio/PortfolioStats.tsx | 223 |
| portfolio/PortfolioFilters.tsx | 116 |
| portfolio/CurrencySelector.tsx | 54 |
| charts/RiskMetricsDisplay.tsx | 218 |
| charts/PerformanceChart.tsx | 194 |
| charts/SectorAllocationChart.tsx | 179 |
| app/globals.css | 26 |
| **Components total** | **4,337** |
| Tests: MetricCard(404), DataTable(50), AddPositionModalSimple(105), Sidebar(19) | 578 |

Note: actual counts differ slightly from the line counts in the brief (e.g. DashboardLayout 176 vs 162); actuals are used throughout.

**Severity legend:** P0 = crash/security/serious a11y blocker · P1 = real bug or misleading UI (wrong value, broken keyboard flow, contrast fail on key metric) · P2 = design-system/UX improvement · P3 = nit/polish. Each finding is tagged **[wrong]** (incorrect behavior) or **[ugly]** (correct but poor design).

**Headline counts:** P0: 0 · P1: 13 · P2: 20 · P3: 5 · Total: 38 (18 bugs, 14 improvements, 6 optimizations).

---

## 1. Bugs

### 05-B1 — [P1] [wrong] Class-based dark mode is a no-op: no `@custom-variant dark` in Tailwind v4
- **Where:** `frontend/src/app/globals.css:15-20` (only `@media (prefers-color-scheme: dark)` block; file has no `@custom-variant`); `frontend/src/lib/store.ts:240-248` toggles `document.documentElement.classList.toggle('dark', …)`; `package.json` = `tailwindcss ^4.3.3`.
- **What's wrong:** Tailwind v4's `dark:` variant defaults to `prefers-color-scheme`, not the `.dark` class. The whole app drives dark mode via a class (store, Settings page, Header icon), so **toggling the app switch changes nothing** in `dark:` utilities; styling follows the OS instead. Two extra failures: (a) `globals.css` body colors key off OS while components key off… also OS → persisted `darkMode: true` (`store.ts:266`) is never re-applied to the DOM on hydration (only `toggleDarkMode` writes the class), so even after fixing the variant, first paint ignores the persisted preference; (b) system-dark + `darkMode:false` gives a dark `body` behind light cards.
- **Fix:** one line in `globals.css`: `@custom-variant dark (&:where(.dark, .dark *));` — plus re-apply the class on rehydrate (e.g. an effect in `DashboardLayout` reading `useUIStore`), and switch the `:root` dark block to `.dark` selectors.
- **Why it matters:** the repo invariant "dark mode (class-based)" is currently only skin-deep (icon + class, no styles).

Status: fixed — @custom-variant dark (&:where(.dark, .dark *)) added to globals.css; the :root dark block converted to .dark selectors; DashboardLayout effect toggles the documentElement class from useUIStore.darkMode, re-applying the persisted preference on mount (hydration).

### 05-B2 — [P1] [wrong] All three portfolio modals are hand-rolled: no focus trap, no Escape, no `role="dialog"`, labels not associated
- **Where:** `AddPositionModalSimple.tsx:166-174` (overlay div, `onClick` close only), `EditPositionModal.tsx:126-135`, `PortfolioDropzone.tsx:176-177`. Grep across `src` for `role="dialog" | aria-modal | aria-labelledby | Escape` → **zero hits anywhere**. Labels lack `htmlFor`/`id` at `AddPositionModalSimple.tsx:194,216,238,261,286,298` and `EditPositionModal.tsx:194,220,245,270,287`. Close buttons unnamed: `Add:182-187`, `Edit:146-151`, `Dropzone:184-189`. Body scroll not locked in any of the three.
- **What's wrong:** these modals perform money actions (add/edit/import positions). Keyboard focus can Tab behind the overlay onto the page, Escape does nothing, screen readers don't announce a dialog or its title, and inputs aren't labelled. The repo already ships a working Radix wrapper (`ui/dialog.tsx:40-56` — Portal + Overlay + focus trap + Escape for free) with **zero importers** (grep `ui/dialog` matches only its own exports).
- **Severity call:** brief says "modal without focus trap used for money actions = P1/P0 call" → graded **P1** (serious a11y blocker, but not crash/security).
- **Fix:** rebuild all three overlays on `ui/dialog.tsx` (add `DialogClose`, scroll lock, `aria-describedby` wiring — see 05-I1), or minimally add `role="dialog" aria-modal="true" aria-labelledby`, an Escape handler, a focus trap, `htmlFor`/`id` pairs, and `aria-label="Close"`.

Status: fixed — dialog.tsx rebuilt (DialogClose/DialogHeader/DialogTitle/DialogDescription exports, body scroll-lock effect, closeOnOutsideClick prop guarding onPointerDownOutside, twMerge helpers); all three modals rebuilt on Radix Dialog with labelled inputs (htmlFor/id), aria-label="Close" buttons, title/description, closeOnOutsideClick={false}.

### 05-B3 — [P1] [wrong] Dropzone: no keyboard path, no file type/size validation, copy promises Excel it can't parse
- **Where:** `PortfolioDropzone.tsx:200-210` (drop area is a plain `div` with `onClick` — no `tabIndex`, `role="button"`, or key handler); `:211-215` (hidden `<input type="file">`, `accept=".csv,.txt"` — unreachable by keyboard and bypassed by drag); `:121-134` `handleFile` reads whatever `File` arrives with no extension/size check; `:182` header says "Import Portfolio (CSV / Excel)".
- **What's wrong:** (1) keyboard-only users **cannot import at all** (explicit invariant in brief); (2) dropping `holdings.xlsx` or a 500 MB file silently `readAsText`s it → garbled parse → generic "Could not parse any valid position rows" error with no mention of wrong type/size (brief requires an error state for wrong type/size); (3) title advertises Excel while `accept` and the parser only handle CSV → misleading UI.
- **Fix:** make the drop area a real `<button>`/focusable region wired to `fileInputRef.click()` (keyboard alternative exists at `:204` but is unreachable); in `handleFile`, reject non-`.csv/.txt` and >2 MB with a specific inline error (reuse the `parseError` banner at `:234-239`); retitle to "Import Portfolio (CSV)".

Status: fixed — drop area is a focusable control (role="button" tabIndex aria-label + Enter/Space handlers); handleFile rejects non-.csv/.txt extensions and >5MB files before reading, with a specific error; header retitled "Import Portfolio (CSV)".

### 05-B4 — [P1] [wrong] RiskMetricsDisplay fabricates zero-valued metrics when no data
- **Where:** `RiskMetricsDisplay.tsx:43-53` — `defaultData` fills `annual_volatility: 0, sharpe_ratio: 0, max_drawdown: 0, var_95: 0, cvar_95: 0`; `const metrics = data || defaultData`. Then `:150` Sharpe null-check passes for `0` → renders **"0.00"**; `:163-168` renders **VaR "0.00%" in red with a green "Low Risk" badge**.
- **What's wrong:** violates the repo invariant that metric cards are strictly live-data-driven with no placeholder mock values. A missing backend response reads as "portfolio has zero risk."
- **Fix:** make `data` required-when-not-loading, or default all fields to `null` and route through the existing `N/A` branches (`:81-86`, `:129`, `:150` already handle null).

Status: fixed — defaultData fields are all null (comment: "never fabricate zeros (05-B4)"); nulls route through the existing N/A branches; max_drawdown typed number | null; component wrapped in React.memo. Caller note: dashboard/page.tsx:453-454 still coerces var_95/cvar_95 with || 0 — page call-site, handoff to batch C.

### 05-B5 — [P1] [wrong] MetricCard renders placeholder/NaN deltas and defaults to `$` formatting
- **Where:** `MetricCard.tsx:119-124` renders the delta whenever `change !== undefined` — no `Number.isFinite` guard, so `NaN` prints **"NaN%"** (`formatChange :57-60`: `NaN.toFixed(2)` = `"NaN"`). Call-site evidence: `app/dashboard/page.tsx:340` passes `change={portfolioMetrics.totalGainLossPct}` unguarded — `0` (e.g. empty portfolio, no data) renders **"+0.00%"**, implying a measured flat month. `changeType` color (`:62-82`) trusts the caller and can disagree with the sign. Also `:36` — `prefix !== undefined ? prefix : '$'`: any numeric value without an explicit `prefix` renders **US `$` + K/M suffixes** on an en-IN product (`MetricCard.test.tsx:111,120` lock `$1.2K`/`$1.2M` in), contradicting the ₹/Cr/L invariant; only `dashboard/page.tsx:333` passes `prefix="₹"`. Negative INR values miss the Cr/L branches (`:38-41` use `>=`) and fall through to `₹-1234567.00`.
- **What's wrong:** delta contract ("no placeholder ±x% when data missing") is enforced nowhere; currency default is wrong for the market.
- **Fix:** hide the chip unless `Number.isFinite(change)`; default `prefix` to `''` (or `'₹'`) and derive `changeType` from sign inside the component; use `Intl.NumberFormat('en-IN')` with abs-value before Cr/L bucketing.

Status: fixed — formatValue rewritten: no-prefix values format via en-IN (no $ default), explicit ₹ uses Cr/L with abs-value + preserved sign, other prefixes use K/M, non-finite → "N/A"; delta chip renders only when Number.isFinite(change) with color derived from sign (changeType kept in the interface but ignored); dashboard:330 passes change={totalCost > 0 ? ... : undefined}; MetricCard tests updated plus a new B5 guard block.

### 05-B6 — [P1] [wrong] EditPositionModal never closes after a successful save
- **Where:** `EditPositionModal.tsx:74-107` — `handleSubmit` awaits `onUpdate(...)` then only clears `isSubmitting`; **no `onClose()`**. Parent `app/portfolio/manage/page.tsx:206-219` (`handleUpdatePosition`) also doesn't clear `showEditModal` (it only refetches). Compare Add modal which closes at `AddPositionModalSimple.tsx:134`.
- **What's wrong:** after "Update Position" succeeds the modal stays open with the **stale** "Current Position" snapshot (`selectedPosition` object isn't refreshed — `:119-188` still shows old quantity/price), and there's no success feedback. User must hit Cancel, which reads like the save failed.
- **Fix:** call `onClose()` after successful `onUpdate` (or show a success toast + refresh the selected position).

Status: fixed — handleSubmit awaits onUpdate then calls onClose() (EditPositionModal:102); EditPositionModal.test covers close-on-success, error-stays-open, Escape, and outside-click no-close.

### 05-B7 — [P1] [wrong] Add modal submits `weight = 1.0` for a partial add when the portfolio fetch fails
- **Where:** `AddPositionModalSimple.tsx:43-47` — on fetch error: `setTotalPortfolioValue(0); setExistingCount(0)`. Auto-calc `:74-86` then sees `existingCount === 0 || totalPortfolioValue <= 0` → `weight: 1.0`. Validation `:107` (`weight > 1` only) passes → submitted.
- **What's wrong:** the zero-state invariant ("first asset in an **empty** portfolio ⇒ 100.00%") is applied to a *failed* fetch. Adding one stock to an existing 20-position book during an API blip records that position at **100% weight** — wrong value, wrong money data. (The happy path `:77-84` value-share math is correct.)
- **Fix:** on fetch failure keep the form but block weight auto-calc/submission (show "couldn't load portfolio total — retry"); only set `weight: 1.0` when the fetch **succeeds** with `positions.length === 0`.

Status: fixed — portfolioLoaded/fetchError gate added: the catch no longer zeroes the counters; weight 1.0 only when the fetch succeeds with positions.length === 0; fetchError disables submit and shows a retry banner ("Couldn't load portfolio total — retry"); tests cover the failure path (retry, no 1.0 submit).

### 05-B8 — [P1] [wrong] en-US currency formatting in portfolio components (repo invariant: en-IN for ₹)
- **Where:** `PortfolioTable.tsx:43` `toLocaleString('en-US', …)` with `₹`; `PortfolioStats.tsx:80-83` same; `EditPositionModal.tsx:173` same for Current Value. `DataTable.tsx:72-77` hardcodes `currency: 'USD'` in its currency formatter. Contrast: `PortfolioDropzone.tsx:249,267,269` correctly uses `en-IN`.
- **What's wrong:** western grouping for rupees (`₹1,234,567` instead of `₹12,34,567`) and no Cr/L abbreviation, per the invariant "Indian equities must format … en-IN localization." Inconsistent with the Dropzone in the same feature. DataTable's USD default will print `$` if any caller uses the currency formatter.
- **Fix:** one shared `formatINR/formatCurrency(currency)` util using `Intl.NumberFormat(currency==='INR'?'en-IN':'en-US')` + optional Cr/L compaction; use it in all three + DataTable.

Status: fixed — PortfolioTable, PortfolioStats, and EditPositionModal all import the shared formatCurrency from lib/utils (en-IN grouping, Cr/L for ₹); DataTable's hardcoded-USD formatter was deleted along with defaultFormatters (05-I14).

### 05-B9 — [P1] [wrong] DataTable shows "Showing 1 to 0 of 0 results" on empty data; title count ignores filtering
- **Where:** `DataTable.tsx:216-221` — first index computed as `pageIndex * pageSize + 1` unconditionally → with 0 rows renders "Showing 1 to 0 of 0 results". Title at `:138` uses raw `data.length` while pagination uses `getFilteredRowModel().rows.length` → after typing in search the header count stays stale.
- **What's wrong:** visibly wrong numbers on an empty/filtering quant table (also covered by the empty-state gap: no "No results" message is ever rendered — `DataTable.test.tsx:26-31` even pins the header-only behavior).
- **Fix:** short-circuit to an empty-state row when `rows.length === 0`; base the title count on the filtered model (or label it "total").

Status: fixed — title count uses filteredCount ("Title (N)"); an empty result renders "No results" instead of "Showing 1 to 0 of 0"; DataTable tests added for both behaviors.

### 05-B10 — [P1] [wrong] Header notification bell: always-on fake unread badge + dead, unnamed button
- **Where:** `Header.tsx:168-172` — button has no `onClick`, no `aria-label`, and a hardcoded `<span class="w-2 h-2 bg-red-500">` badge rendered unconditionally.
- **What's wrong:** every user, always, has "1 unread notification" that does nothing — placeholder mock state (same spirit as the banned mock deltas), and the icon-only control has no accessible name. The real notification system lives in `NotificationSystem.tsx` and isn't wired here.
- **Fix:** bind badge to `useNotifications().notifications.length` (render only when >0), add `aria-label="Notifications"` (and `aria-live` count), and either wire a popover or remove the button.

Status: fixed — bell button and hardcoded badge (plus the dead user menu) removed from Header; real toasts announce through NotificationSystem's role="status" aria-live="polite" container.

### 05-B11 — [P1] [wrong] ExportPanel progress bar is stuck at 0% for every single-format export
- **Where:** `ExportPanel.tsx:27` local `exportProgress` state; `:40-52` pdf/excel/csv branches update only the **store** job (`updateExportProgress`) and never `setExportProgress` → the visible bar (`:153-165`) shows 0% until `finally` resets it. The `'all'` branch updates local progress only at each format *completion* (`:77`), and the parent `exportId` from `:37` never gets progress updates. Errors surface only via `console.error` (`:97`).
- **What's wrong:** misleading async feedback on a user-triggered action; user can't tell exporting from hung (double-disable via `isExporting` is the only signal).
- **Fix:** drive the bar from the store job (`getActiveExports().find(id)`), or `setExportProgress` alongside every `updateExportProgress` call; show a terminal success/error state instead of vanishing.

Status: fixed — ExportProgressView child subscribes to useExportProgress().exports[exportId] and renders role="progressbar" with aria-valuenow plus terminal success/error lines; single-format branches call updateExportProgress(exportId, …); the 'all' branch updates the parent exportId progress per completed format.

### 05-B12 — [P1] [wrong] Sortable headers in both tables are mouse-only (WCAG 2.1.1)
- **Where:** `DataTable.tsx:177-192` — `<th onClick={…}>` with no `tabIndex`, no `<button>`, no `aria-sort`; `PortfolioTable.tsx:99-179` — eight `<th onClick>` in the same pattern (sort icon at `:59-66`).
- **What's wrong:** keyboard and screen-reader users cannot sort either table — a core interaction on a dense data grid. (Hyphenated NSE tickers themselves render fine — `whitespace-nowrap` cells + `overflow-x-auto` — no bug found there; test evidence `DataTable.test.tsx:35-42` covers `INFY.NS`/`HDFCBANK.NS`.)
- **Fix:** wrap header label in `<button>` with `aria-label={`Sort by ${header}`}`, set `aria-sort={direction|none}` on the `<th>`.

Status: fixed — DataTable th wrapped in a <button aria-label="Sort by X"> with aria-sort on the th; PortfolioTable's sortableTh helper does the same for all nine sortable columns; sort toggle covered by a new DataTable aria-sort test.

### 05-B13 — [P2] [wrong] Route-title map has drifted from the nav — three routes render generic "Dashboard"
- **Where:** `DashboardLayout.tsx:22-91` `routeTitles` lacks `/dashboard/equity-research`, `/dashboard/screener-studio` (both in `Sidebar.tsx:48-58`) and `/portfolio/manage` (`Sidebar.tsx:150-153`); fallback `:127` → title "Dashboard", no subtitle.
- **What's wrong:** header shows the wrong page name on three live nav routes — the two maps are duplicated config that drift. **[wrong]**
- **Fix:** single shared nav/route config consumed by Sidebar (name, icon, href) and DashboardLayout (title, subtitle) — see 05-I11.

Status: fixed — Sidebar exports a single navigation array (with title/subtitle/description covering equity-research, screener-studio, portfolio/manage, and Settings as a footer entry); DashboardLayout derives routeTitles from it via Object.fromEntries — one source, drift impossible.

### 05-B14 — [P2] [wrong] Off-canvas mobile sidebar stays keyboard-focusable; active link has no `aria-current`
- **Where:** closed state is `-translate-x-full` only — `DashboardLayout.tsx:142-145`, `Sidebar.tsx:174-251` — no `hidden`/`inert`/`aria-hidden`, so Tab walks through invisible links; active item styling only (`:221-223`) with no `aria-current="page"` (`:216`).
- **What's wrong:** focus lands on invisible controls; active route is conveyed by color alone (fails SC 1.4.1 for AT users who get no state hint).
- **Fix:** add `inert`/`aria-hidden` (or `hidden`) when the drawer is closed on mobile; `aria-current={isActive ? 'page' : undefined}`.

Status: fixed — off-canvas sidebar wrapper uses inert={isMobile && !mobileSidebarOpen}; active Link renders aria-current="page".

### 05-B15 — [P2] [wrong] Export "settings" are decorative; selected-format highlight never activates
- **Where:** `ExportPanel.tsx:221-252` — three `defaultChecked` checkboxes, uncontrolled, never read by `handleExport` (`:31-103`) or passed to `ExportService`; `:26` `selectedFormat` state is never `setSelectedFormat` anywhere, so the `border-current` highlight at `:176` can never show.
- **What's wrong:** users believe metadata/compression/chart options apply — they don't. Fake controls are worse than absent controls.
- **Fix:** delete the settings block and `selectedFormat` (YAGNI) until `ExportService` accepts those flags.

Status: fixed — decorative settings checkboxes and the dead selectedFormat state deleted (YAGNI until ExportService accepts those flags).

### 05-B16 — [P2] [wrong] NaN leaks into visible percent strings in PortfolioStats / PortfolioTable
- **Where:** `PortfolioStats.tsx:86-89` `formatPercent` — no NaN/undefined guard → `"NaN%"` if backend omits `unrealized_gain_loss_pct`; `PortfolioTable.tsx:47-49` same. (`MetricCard` guards NaN at `:51-52`; these don't.)
- **What's wrong:** a `NaN%` P&L on the holdings table is worse than a blank — it destroys trust in adjacent real numbers. **[wrong]**
- **Fix:** shared formatter: `Number.isFinite(v) ? … : '—'` (placeholder policy per 05-I5).

Status: fixed — shared guards: PortfolioTable money()/formatPercentage() and PortfolioStats money()/formatPercent() route non-finite values to "—"; EditPositionModal money cells go through formatCurrency ("NaN%" can no longer render).

### 05-B17 — [P2] [wrong] Bulk import assigns equal weights summing to 100% regardless of existing holdings
- **Where:** `PortfolioDropzone.tsx:155` `weight: 1.0 / parsedRows.length` for every imported row; contrast Add modal value-share math (`AddPositionModalSimple.tsx:74-86`) which correctly computes share of existing total.
- **What's wrong:** importing 10 rows into an already-populated portfolio gives the imported batch a **combined 100% weight** (unless the backend silently renormalizes — needs verification). At minimum the two create-paths disagree on what "weight" means (equal-split vs value-share) — inconsistent data entering the same field. The zero-state case (empty portfolio) does satisfy "sums to 100%," but not via the documented first-position rule.
- **Fix:** compute value-share against `total_value` like the Add modal (fetch total before submit), or explicitly send no weights and let backend normalize — document which.

Status: fixed — value-share weights (value / (existing + batch), equal split only when the denominator is 0) with auto_normalize: true; import is gated by an explicit weight-acknowledgement checkbox; tests cover the 1000/2400 and 500/2400 cases.

### 05-B18 — [P2] [wrong] Loading/skeleton components omit `dark:` variants — invisible or glaring in dark theme
- **Where:** `LoadingState.tsx:59` (`text-gray-600` message), `:80,:94` (`bg-gray-200` bars), `:114` (`bg-gray-50`), `:135-139` (`bg-white p-6` card), `:155-173` (all light), `:212-218` RefreshIndicator, `:249-264` ErrorBoundary (`text-gray-900` on dark page). Every other component carefully pairs `dark:` classes; these don't.
- **What's wrong:** skeleton whites flash on dark surfaces; error-boundary copy is dark-on-dark once B1 is fixed (today it depends on OS pref). Contrast/key-metric visibility fail in one of the two themes.
- **Fix:** add the standard `dark:bg-gray-700/800 dark:text-gray-300` pairs — or consume the shared card/surface classes from 05-I4 so this can't drift again.
Status: fixed — dark: pairs added throughout LoadingState: message text, table/card/chart skeleton bars, bg-white card shells, RefreshIndicator text + Auto pill, and ErrorBoundary heading/body.

---

## 2. Improvements (UI/UX + design system)

### 05-I1 — [P1] [ugly] Adopt (or delete) the Radix dialog/select primitives — they fix B2 in one place
- **Where:** `ui/dialog.tsx:40-56` (Portal + Overlay + Radix Content = focus trap, Escape, `aria-modal`, labelled-by enforcement), `ui/select.tsx:55-66` (typeahead, portal, `role="listbox"`) — **zero importers** in `src` (grep `ui/dialog|ui/select` → only their own files). Small debts even there: no scroll lock (Radix doesn't lock body scroll by default), no `DialogClose` export, `DialogDescription` optional so Radix logs missing-description warnings.
- **Recommendation:** wire all overlays (B2) and any custom dropdowns onto these; add `DialogClose`, a scroll-lock effect, and `aria-describedby`. If they'll never be used, delete them — an unused a11y layer that exists while every real modal is hand-rolled is the worst of both worlds. **Why:** one fix location beats patching three overlays.

Status: fixed — dialog.tsx adopted by all three modals (05-B2) with DialogClose, scroll-lock, and closeOnOutsideClick added; select.tsx deleted (zero importers confirmed before removal).

### 05-I2 — [P2] [ugly] Extract a shared `PositionForm` from Add/Edit modals (~200 duplicated lines, diverging UX)
- **Where:** field rows + error slots + `cn()` border-error pattern: `AddPositionModalSimple.tsx:191-346` vs `EditPositionModal.tsx:191-337`; validation: `Add:89-120` vs `Edit:47-71` (near-identical date/qty/price rules); submit+spinner button pair: `Add:333-344` vs `Edit:324-335`.
- **Divergence users feel:** Add auto-calculates weight and shows it read-only as % (`Add:259-281`) while Edit requires typing a decimal with helper text "0.15 = 15%" (`Edit:197-215`); Add validates ticker format, Edit can't edit ticker (fine) but nothing shares code. Error copy for future date is duplicated verbatim (`Add:114`, `Edit:65`).
- **Recommendation:** `PositionForm` with `mode: 'create' | 'edit'`, controlled `fields`, shared `validatePosition(fields, { requireTicker })`. **Why:** every validation/label fix then lands once (and 05-I12's tests target one surface).

Status: skipped — shared PositionForm extraction is a large cross-file refactor beyond this fix batch; both modals were independently fixed (B2/B6/B7) and covered by tests.

### 05-I3 — [P2] [ugly] Three copies of `formatLastUpdated` / relative-time logic
- **Where:** `Header.tsx:44-59`, `LoadingState.tsx:193-207` (`formatLastRefresh`), `NotificationSystem.tsx:229-243` (`formatLastRefresh`) — byte-for-byte the same Never/Just now/Nm/Nh/date ladder.
- **Recommendation:** `formatRelativeTime(date)` util beside the en-IN currency formatters (05-B8); then `RefreshIndicator` and Header show identical copy by construction. **Why:** "5m ago" vs "5 min ago" drift is a copy-consistency bug waiting to happen.

Status: fixed — shared formatRelativeTime(date: string | Date | null | undefined) exported from LoadingState; Header, RefreshIndicator, and the NotificationSystem RefreshButton all consume it (one ladder, one copy).

### 05-I4 — [P2] [ugly] Token discipline: 2 CSS variables for a 4,300-line component layer; 60+ ad-hoc hexes; card shell copy-pasted 6×
- **Evidence:**
  - Tokens: `globals.css:3-6` defines only `--background/--foreground`; `:25` hardcodes `font-family: Arial` over the configured `--font-sans` (Geist) at `:11` — typography token dead on arrival.
  - Hex grep (components): `PerformanceChart.tsx:162,170,180`; `SectorAllocationChart.tsx:29-39` (10-color palette), `:155` stray `#8884d8`. Pages sampled: `equity-research/page.tsx:710-764` (18 hexes incl. inline tooltip colors), `forecast-risk:896-964`, `risk-studio:466-611`, `optimize:359-418`, `realized-risk:465,494`, `concentration:710-719`, `monte-carlo:63,68` — no shared chart palette.
  - Repeated shell `bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border border-gray-200 dark:border-gray-700`: `MetricCard:105`, `DataTable:133`, `RiskMetricsDisplay:97,113`, `PerformanceChart:101,112,129`, `SectorAllocationChart:112,123,135`.
- **Recommendation:** (1) semantic tokens in `globals.css` (`--surface`, `--surface-2`, `--border`, `--text-muted`, accent/success/danger) mapped through `@theme`; (2) one exported `CHART_COLORS: string[]` + per-chart stroke tokens; (3) a `<Card>`/`cardCN` constant for the shell. **Why:** dark-mode (B1) and theme changes become one-line edits instead of 60-file hunts — currently every new component re-rolls the palette.

Status: skipped — token/chart-palette/card-shell sweep spans unowned chart internals and seven page files (dedicated cleanup batch, not this one).

### 05-I5 — [P2] [ugly] Missing-data copy is four different conventions
- **Evidence:** `N/A` — `MetricCard.tsx:34,52`, `RiskMetricsDisplay.tsx:83,136`, dashboard pages (`page.tsx:348`, `concentration:628-652`); `-` — `DataTable.tsx:81,90-100`; em-dash `—` — `PortfolioDropzone.tsx:268`; blank/nothing — `MetricCard` omits delta entirely when `change === undefined` (`:119`); literal `0` presented as data — `RiskMetricsDisplay:46-50` (see 05-B4); `Never` — `Header:45`.
- **Recommendation:** document and enforce: `—` = metric not available/not computed (tables & values), `N/A` = endpoint didn't return the metric (cards, keeps existing tests), never render `0` as a stand-in, never blank a cell. **Why:** in a quant UI, the difference between "0% VaR" and "—" is a trading decision.

Status: fixed — convention enforced in code: "N/A" for missing card metrics (MetricCard, RiskMetricsDisplay), "—" for missing table/stat values (PortfolioTable, PortfolioStats), zero stand-ins removed (05-B4), DataTable's dead "-" formatter deleted (05-I14); "Never" retained only for never-refreshed timestamps.

### 05-I6 — [P2] [ugly] A11y matrix — per-component gaps (roles, names, live regions)
| Component | Present | Missing |
|---|---|---|
| Add/Edit/Dropzone modals | overlay, Cancel button | see 05-B2 (dialog role, trap, Escape, labelled inputs, named close) |
| Header `Header.tsx:61-193` | menu/live/refresh/dark have `aria-label` | bell + user unnamed (`:168,:176`); Live toggle no `aria-pressed` and **no name on mobile** ("Live" text is `hidden sm:inline` `:120`); dark toggle no state (`:158`) |
| Sidebar `:173-267` | collapse `aria-label` (`:198`) | `aria-current` (B14); descriptions read only visually |
| DataTable `:174-196` | pagination buttons have text | sortable `th` keyboard (B12); search input placeholder-only name (`:143-151`) |
| PortfolioTable `:98-183` | — | `th` keyboard (B12); edit/delete icon-only, `title`-only names (`:245-258`) |
| PortfolioFilters `:35-49,:55-66` | — | search/select/chip-X/clear all lack labels/`aria-label`; native `<select>` unlabelled |
| CurrencySelector `:33-47` | `title` attr | no `role="radiogroup"`/`aria-pressed`; selection state is visual only |
| NotificationSystem `:60-97` | close button present | container no `role="status"`/`aria-live="polite"` — **toasts are never announced**; close button unnamed (`:71-76`) |
| ExportPanel `:168-187` | button text | progress bar no `role="progressbar"`/`aria-valuenow` (`:159-164`) |
- **Fix order:** live-region on toast container + dialog roles (B2) + `aria-current` + header names cover ~80% of user journeys.

Status: fixed — matrix resolved: dialog roles/labels (05-B2), aria-current (05-B14), sortable th buttons + search aria-label (05-B12/05-B9), PortfolioTable edit/delete aria-labels, PortfolioFilters search/sector/chip/clear-all labels, CurrencySelector role="group" + aria-pressed, toast container role="status" aria-live + close aria-label, ExportPanel progressbar role/aria-valuenow, Header Live/dark toggles with aria-label + aria-pressed (bell/user removed, 05-B10).

### 05-I7 — [P2] [ugly] Loading feedback policy is inconsistent: skeletons for content, but silent fire-and-forget for actions
- **Evidence:** good skeletons exist (`MetricCard:84-99`, `DataTable:103-130`, `RiskMetricsDisplay:95-108`, both charts) — keep these; but `LoadingState:46-62` defaults to a centered spinner (layout jump), `Header:36-42` refresh failure = `console.error` only (user gets no error, spinner just stops), `Header:124-139` Export PDF not awaited — no success/failure feedback at all, `QuickExportButtons` `ExportPanel:260-303` — no in-flight state, errors to console (`:280`), `PortfolioFilters`/tables have no "updating" affordance on refetch.
- **Recommendation (with why):** **skeletons for first-load page regions** (preserves layout, prevents CLS — already the dominant pattern); **button-level spinner + disabled for in-place async actions** (refresh/export already spin the icon — extend to QuickExport); **toast for terminal outcomes** (success/failure of export, refresh, import) via the existing notification system — console errors are invisible to users. 

Status: fixed — Header refresh/export awaited with success/error toasts and an isExportingPdf busy/disabled state; QuickExportButtons has a busy state and toasts both outcomes; terminal results go through useNotifications instead of console; first-load skeletons kept as-is.

### 05-I8 — [P2] [ugly] Destructive/import confirmation asymmetry; overlay-click discards form data
- **Evidence:** delete has a proper confirm (`manage/page.tsx:817-843` ✓) — but Dropzone import of N rows with 100%-combined weight (05-B17) gets only a preview count, no "this sets each position to X% weight" confirmation (`PortfolioDropzone.tsx:241-276,288-304`); Add modal closes on **any overlay click** (`AddPositionModalSimple.tsx:170`) — one stray click loses a filled form with no prompt (Edit's overlay `:129-132` does the same).
- **Recommendation:** keep Delete-style confirm for bulk import with a weight-summary line; make overlay-click close only when the form is pristine, or drop overlay-click entirely (Escape + Cancel is the standard pair — also required by B2).

Status: fixed — all three modals use closeOnOutsideClick={false} (Escape + Cancel only, no stray-click data loss); Dropzone import is gated by an explicit weight-acknowledgement checkbox before submit.

### 05-I9 — [P2] [ugly] Responsive gaps in dense chrome
- **Evidence:** Header right cluster packs 6 controls with `space-x-3` and no wrap/overflow handling (`Header.tsx:94-189`) — Live + Export PDF + Refresh + theme + bell + user overflows or clips between `sm` and `lg` (Export label only `hidden md:inline` `:138`, user block `hidden sm:block` `:180` — icons pile up); toast container fixed `w-96` (384 px) (`NotificationSystem.tsx:87`) overflows phones (use `w-[calc(100vw-2rem)] max-w-96`); table cells `px-6` (`DataTable:201`, `PortfolioTable:188+`) waste horizontal space on mobile — `px-3 sm:px-6`; metric grids correctly go `grid-cols-1 md:2 lg:4` (`RiskMetrics:126`, `PortfolioStats:110` ✓ keep this pattern).
- **Recommendation:** collapse Header to essential icons below `lg`, keep `title` tooltips; fluid toast width; tighter mobile cell padding.

Status: fixed (partial) — toast width fluid (w-96 max-w-[calc(100vw-2rem)]) and Header's cluster reduced to five controls (bell + user menu removed). Deferred: table cell px-6 → px-3 sm:px-6 and full below-lg header collapse (cosmetic, low risk).

### 05-I10 — [P3] [ugly] Copy consistency: product name, fake identity, Excel promise, scale-notation mix
- **Evidence:** `Sidebar.tsx:189` "Daisy Risk Engine" (file headers `DashboardLayout:2`, `Header:2` too) vs repo/product "FinEngine"; `Header.tsx:181-186` hardcoded "Portfolio Manager / admin@company.com" placeholder identity in the user menu (dead button `:176`); `PortfolioDropzone:182` "CSV / Excel" vs `accept=".csv,.txt"` `:214` (also 05-B3); same dashboard mixes `$1.2K` MetricCard notation (05-B5) with `₹…Cr/L` (`dashboard/page.tsx:333` path) and full-rupee table values (05-B8).
- **Recommendation:** one product name, real/no user menu (remove until auth exists), fix import title, one number-format helper (05-B8).

Status: fixed — FinEngine renames (Sidebar, Header, DashboardLayout); placeholder user menu + dead button removed; Dropzone retitled "(CSV)"; shared formatCurrency/formatValue helpers adopted (05-B8/05-B5) — one number-format helper now.

### 05-I11 — [P2] [ugly] Sidebar collapsed state hides Settings; nav config and route titles should be one source
- **Evidence:** footer Settings only renders when `!isCollapsed` (`Sidebar.tsx:255-265`) — collapsed (desktop) users lose Settings entirely (it's not in the `navigation` array `:40-155`); collapsed mode also drops descriptions (`:237-248`) so the nav is icon+tolltip only — acceptable, but Settings disappearing is a capability regression; the two-config drift is 05-B13.
- **Recommendation:** render Settings icon-only when collapsed (mirror `:194-206` toggle pattern); export a single `NAV = [{ name, href, icon, description, title, subtitle }]` consumed by Sidebar + DashboardLayout. **Why:** route-title bugs become impossible.

Status: fixed — navigation exported from Sidebar (including Settings as a footer entry rendered icon-only when collapsed, mirroring the toggle pattern); DashboardLayout consumes it for route titles — single source for both (also closes 05-B13).

### 05-I12 — [P2] [ugly] Test coverage: happy-path only; one mock targets the wrong method (masks 05-B7's code path)
- **Evidence (existing4):** `MetricCard.test.tsx` thorough (404 lines — but locks in the `$` default at `:111,:120` and doesn't test NaN delta); `DataTable.test.tsx` 3 cases (render/loading/empty-header — misses pagination-empty 05-B9, sorting, filtering counts); `AddPositionModalSimple.test.tsx` covers open/close/date only — **`vi.mock('@/lib/api')` mocks `getSummary` (`:8`) but the component calls `portfolioApi.getPortfolio` (`AddPositionModalSimple.tsx:39`)** → mock never intercepts, test runs through the catch path with `total=0`, and passes for the wrong reason (it would still "pass" if B7's fetch-failure branch were *always* taken); `Sidebar.test.tsx` 1 render assertion (no active/collapse/mobile cases).
- **Gaps to add:** `EditPositionModal` — close-on-success (would fail today, 05-B6), error path; `PortfolioTable` — zero-state 100% weight render, en-IN format, sort click; `PortfolioDropzone` — wrong file type/size error, keyboard activation, bad-header parse error; `dialog` — Escape closes + focus returns; `DataTable` — empty pagination copy (05-B9); `NotificationSystem` — `aria-live` presence; `MetricCard` — `change={NaN}` must hide chip (05-B5).
- **Fix:** correct the mock to `getPortfolio`, then add the above before/with the code fixes (tests-first would have caught B6/B9).

Status: fixed (partial) — mock corrected getSummary → getPortfolio; added/updated tests: EditPositionModal (close-on-success/error/Escape/outside-click), PortfolioDropzone (type/size/keyboard/value-share/ack), DataTable (empty copy/filter counts/aria-sort), MetricCard (B5 guards incl. NaN delta), Add modal B7 failure paths. Deferred: dedicated NotificationSystem aria-live test; PortfolioTable tests skipped (component has zero callers).

### 05-I13 — [P3] [ugly] Icon/typography scale is implicit — document3 sizes,1 spinner map, drop dead variants
- **Evidence:** icon sizes in active use:16 (`PortfolioTable:250`),20 (`MetricCard:110`, Header),24 (`ExportPanel:179`),32 (`PortfolioStats:125`, Dropzone:223) with no stated scale; `LoadingSpinner` color map (`LoadingState:26-32`) and size `xl` appear unused by callers in this set; font ladder `text-xs → text-2xl` in free use (Header title `text-xl` `:81` vs section `text-lg` `:115` is consistent enough — document, don't renumber).
- **Recommendation:** write the scale into a short DESIGN note (16 inline /20 control /24 section /32 stat); delete unused spinner colors (YAGNI) or wire them to tokens (05-I4).

Status: skipped — DESIGN scale note and dead spinner-variant deletion are documentation/YAGNI follow-ups outside this batch.

### 05-I14 — [P3] [ugly] DataTable ships dead API surface
- **Where:** `DataTable.tsx:87-101` `defaultFormatters` — defined, memoized, **never referenced** in the render; `:26,:67-70` `onSort` prop + `handleSort` — never called (headers use TanStack's `getToggleSortingHandler()` `:182`); `:163` export button label hardcoded "Export CSV" regardless of `onExport` behavior.
- **Recommendation:** delete `defaultFormatters` + `onSort` (or wire `onSort` for server-side sorting and label the button from a prop). Dead options mislead callers about what the component does.
Status: fixed — defaultFormatters, onSort/handleSort, and the dead formatCurrency/formatPercentage helpers deleted; export button label left as-is (cosmetic — it only renders when onExport is provided).

---

## 3. Optimizations

### 05-O1 — [P2] Zero `React.memo` in the component layer; table rows re-render on every keystroke
- **Where:** grep `React.memo|memo\(|next/dynamic|lazy\(` across `src` → **0 hits**. `PortfolioTable.tsx:186-262` maps all positions inline — typing in `PortfolioFilters` (`:35-41`, controlled by parent) re-renders **every row +9 sort handlers**; `DataTable.tsx:198-208` same per-filter (TanStack re-computes row models anyway, but cell components re-render unconditionally). `PortfolioStats` correctly uses `useMemo` (`:27-76`) ✓ — the only memo in the set.
- **Fix:** `memo` the row component (props: `position`, `sortConfig`, handlers) in PortfolioTable; `memo` the three chart components (props are data-in) so unrelated parent state (filters, modal open flags) doesn't re-render Recharts SVG. **Why:** filter-as-you-type on a 100+ holding book is the hot path.

Status: fixed (partial) — RiskMetricsDisplay, PerformanceChart, and SectorAllocationChart are now React.memo'd (named + default exports); PortfolioTable row extraction skipped because the component has zero importers (dead code — extract or delete separately); DataTable row memo unnecessary (TanStack recomputes row models each render anyway, no child components to isolate).

### 05-O2 — [P2] DashboardLayout resize listener fires setState per pixel
- **Where:** `DashboardLayout.tsx:105-119` — `window.addEventListener('resize', checkScreenSize)` calls `setIsMobile` on every resize event (window drag = hundreds of calls/s), each re-rendering layout + Header + children.
- **Fix:** `matchMedia('(min-width: 1024px)')` with `addEventListener('change')` — fires once per breakpoint cross (and matches the `lg` classes already used at `:143-144`), or rAF-debounce. **Why:** media query is the native platform feature for exactly this (ladder rung 4).

Status: fixed — matchMedia('(min-width: 1024px)') change listener replaces the per-pixel window-resize setState (fires once per breakpoint cross).

### 05-O3 — [P2] Notification queue: unbounded + double-timed
- **Where:** `hooks/useRealTime.ts:246` appends with **no cap** (removal only via per-item `setTimeout :251-254` or manual close); `NotificationSystem.tsx:28-35` schedules a **second** timer for the same dismissal, and the container renders all items (`:88-95`). `autoHide:false` variants (supported by the API `:231`) never expire → permanent stack. Risk alerts at10 s (`useRealTime:273`) + connection flaps can queue several simultaneously.
- **Fix:** cap at ~5 (drop oldest FIFO) in `addNotification`; keep exactly **one** timer (hook-side, since it already persists across unmounts) and delete the component-side `useEffect`; queue connection alerts (suppress duplicates while one is visible).

Status: fixed (partial) — component-side duplicate dismissal timer removed (single hook-side timer remains). Deferred handoff to hooks: queue cap (~5, drop-oldest) in useRealTime.ts addNotification and connection-alert dedup (useRealTime.ts is read-only for this batch).

### 05-O4 — [P2] Recharts ships eagerly on every dashboard route; chart JSX duplicated inline in pages
- **Where:** no `next/dynamic` anywhere; `recharts ^3.10.1` imported statically by `PerformanceChart`, `SectorAllocationChart`, and inline in pages — `risk-studio/page.tsx:466-611`, `forecast-risk:896-964`, `optimize:359-418`, `equity-research:710-764`, `realized-risk:465-494`, `concentration:710-719`, `monte-carlo:63-68` build charts **ad hoc** instead of reusing `components/charts/*`.
- **Fix:** `dynamic(() => import('@/components/charts/PerformanceChart'), { ssr:false })` per chart region (skeleton already exists as the loading fallback — 05-I7 policy); migrate inline page charts onto shared chart components with the tokenized palette (05-I4). **Why:** cuts initial JS on data-heavy routes and kills1-off hex drift in one move.

Status: skipped — next/dynamic chart loading and migrating six pages' inline chart JSX onto shared chart components are out of scope (page files unowned by this batch).

### 05-O5 — [P3] ExportPanel: progress ticks re-render the whole panel (buttons included)
- **Where:** `ExportPanel.tsx:29` `getActiveExports()` read during render subscribes the panel to the store; every progress % bump (`useExportProgress` updates) re-renders header, options grid, settings.
- **Fix:** isolate the progress/history list into a child component that subscribes; keep button grid in a `memo`ized parent with `isExporting` boolean only. **Why:** progress events are frequent; nothing visual besides the bar/percent changes.

Status: fixed — progress rendering isolated in an ExportProgressView child that subscribes via useExportProgress; the parent reads no exports during render (getActiveExports() render call removed), the options grid is React.memo'd, and handleExport is useCallback'd; full action/state split (useExportActions in useRealTime.ts) noted as an optional follow-up, not required for the re-render fix.

### 05-O6 — [P3] Zustand subscriptions without selectors — layout/header re-render on unrelated store fields
- **Where:** `DashboardLayout.tsx:100` `const { sidebarOpen, toggleSidebar, darkMode } = useUIStore()` (whole-store subscription → any `lastUpdated`/`liveDataMode` write re-renders layout + page children); `Header.tsx:33-34` same pattern for both stores (Header *needs* `lastUpdated`, but not `darkMode` re-renders on tick… it does re-render anyway — selector still shrinks update scope); `darkMode` destructured in DashboardLayout is **unused** (`:100`) — dead subscription.
- **Fix:** selector form `useUIStore(s => s.sidebarOpen)`; drop the unused `darkMode`. Low severity — listed because the pattern spreads: with no `memo` anywhere (05-O1), store churn reaches the full tree.
Status: fixed — DashboardLayout and Header use selector-form subscriptions (useUIStore(s => …)); Header's fields are all consumed; DashboardLayout's darkMode retained (read by the 05-B1 hydration effect).

---

## 4. Recommended changes (prioritized, top12)

| # | Sev | file:line | Change |
|---|---|---|---|
| 1 | **P1** | `globals.css:15-20` (+ `store.ts:240-248`) | Add `@custom-variant dark (&:where(.dark, .dark *));` and re-apply the `.dark` class on hydration — the class-based dark toggle currently does nothing (05-B1). One line + one effect. |
| 2 | **P1** | `AddPositionModalSimple.tsx:166-174`, `EditPositionModal.tsx:126-135`, `PortfolioDropzone.tsx:176-177` | Rebuild all overlays on the existing Radix `ui/dialog.tsx` (or add role/aria-modal/Escape/focus-trap/labelled inputs by hand); money actions must be keyboard-operable (05-B2, 05-I1). |
| 3 | **P1** | `PortfolioDropzone.tsx:121-134,200-215` | Keyboard-focusable upload target + validate file type/size with a specific error; retitle "CSV / Excel" → "CSV" (05-B3). |
| 4 | **P1** | `RiskMetricsDisplay.tsx:43-53` | Delete the zero-filled `defaultData`; default to `null` so cards render `N/A` — never "0.00% VaR, Low Risk" from missing data (05-B4). |
| 5 | **P1** | `MetricCard.tsx:36,57-60,119` | Hide delta unless `Number.isFinite(change)`; derive color from sign; drop `$` default (→ `''`/`₹` + `Intl en-IN`) (05-B5 — core metric-card invariant; tests at `MetricCard.test.tsx:111` must be updated with it). |
| 6 | **P1** | `EditPositionModal.tsx:74-107` | `await onUpdate(...); onClose();` — modal currently never closes on success and shows stale "Current Position" values (05-B6). |
| 7 | **P1** | `AddPositionModalSimple.tsx:43-47,74-86` | Don't treat a **failed** portfolio fetch as an empty portfolio — block auto-weight/submit instead of writing `weight: 1.0` into a populated book (05-B7). |
| 8 | **P1** | `PortfolioTable.tsx:43`, `PortfolioStats.tsx:80`, `EditPositionModal.tsx:173`, `DataTable.tsx:72-77` | One `formatCurrency` helper with `en-IN` for ₹ (grouping + Cr/L); remove DataTable's hardcoded USD default (05-B8 — en-IN invariant). |
| 9 | **P1** | `DataTable.tsx:177-192,216-221`, `PortfolioTable.tsx:99-179` | Sortable headers → real `<button>` + `aria-sort`; fix empty-state pagination copy and add a "no results" row (05-B12, 05-B9). |
| 10 | **P1** | `Header.tsx:168-172` | Bind the bell badge to the real notification count (hide at 0), add `aria-label`; also await export with feedback (`:124-139`) (05-B10, 05-I7). |
| 11 | **P1** | `ExportPanel.tsx:27,40-52` | Drive the progress bar from the store job so single-format exports don't sit at 0%; delete decorative settings checkboxes (`:221-252`) (05-B11, 05-B15). |
| 12 | **P2** | `NotificationSystem.tsx:87` + `useRealTime.ts:246` | `role="status"`/`aria-live="polite"` on the toast container, cap the queue at ~5, single auto-hide timer (05-I6, 05-O3); then batch 05-I2 (shared PositionForm), 05-I4 (tokens/chart palette/card shell), 05-I12 (fix `getSummary`→`getPortfolio` mock, add Edit/Dropzone/PortfolioTable tests). |

---

### Severity tally
- **P0:** 0
- **P1:** 13 (B1–B12, I1)
- **P2:** 20 (B13–B18, I2–I9, I11, I12, O1–O4)
- **P3:** 5 (I10, I13, I14, O5, O6)
- **Total findings:** 38 — Bugs 18 · Improvements 14 · Optimizations 6
