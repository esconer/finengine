# Wave 4 — Frontend defect sweep

**Request:** "improve and modernize the frontend."
**Response:** the request is reframed. Recon found the stack already current (Next 16.3.6,
React 19.3, Tailwind 4 CSS-first, recharts 3, TS 6) and no migration to perform. What exists is a
list of concrete defects, several of which are this project's own core sin — a null rendered as a
confident number. This wave fixes those and nothing else.

## The hunk test (every task must pass all four)

1. Name the **production symptom**.
2. Name the **pre-existing code path** that produces it.
3. A test **fails before and passes after** — pasted output required.
4. **No published figure changes.** Any diff that moves a number fails and is reverted.

**Budget:** if the wave touches more than ~12 files and produces no user-observable or
correctness change, it has failed regardless of how good it looks.

---

## Baseline (verified by the orchestrator, not inherited)

```
bun x tsc --noEmit   -> exit 0
bun x vitest run     -> 43 files / 463 tests, 0 failures
bun x eslint src/    -> 0 errors, 271 warnings
```

**The 271/0 figure is NOT a gate.** `.github/workflows/ci-cd.yml` runs `tsc` (:85) and `pytest`
(:54) and **never runs eslint**. `package.json:9` is bare `eslint` with no `--max-warnings`.
Treat 0 errors as the only lint invariant; do not pad a diff to hold a warning count.

**Backend suite is currently unreliable** — it hits yfinance/bfinance live, so the failure count
drifts with network and load (5 → 26 observed under contention). The 57-rule audit gate *is*
hermetic. Do not treat a backend pytest count as a gate this wave.

## Do not touch

- `lib/pdfFont.ts`, `public/fonts/` — the zero-bundle-cost + U+20B9 glyph contract.
- `utils.ts` absent-value guards — the `null/undefined/NaN` triplet is deliberate duplication.
- `format-invariants.test.tsx` the exact 5-name `toEqual` — do not relax it.
- `AbsentValueRendering.test.tsx` / `FabricatedFallbacks.test.tsx` — never edit an expected value
  to match new output. If they go red, the change is wrong, not the test.
- `next.config.ts:5` `reactCompiler: false`.
- `MarginalImpactPanel.tsx` colour refusal.
- `backend/tests/test_audit_rule_coverage.py` and the 57 rules.
- `AGENTS.md` — no new invariant added while working inside it.
- `C:\es\coding\bfinance` — out of scope.
- Route structure, the 17 section pages' composition, `DashboardLayout`/`Sidebar`/`Header` chrome.

---

## Hunk-test exemptions (declared, after review)

Two tasks cannot satisfy clause 3 and are exempt by decision, not by oversight:

- **T4 (Geist/Arial)** — there is no test that goes red on `body { font-family: Arial }` and
  green on `var(--font-sans)`. The task has no visual regression net, and the plan is not going to
  pretend otherwise. **Substitute gate:** a unit assertion that no `font-family: Arial` remains
  in `globals.css` and that the `--font-sans → --font-geist-sans → layout.tsx` chain resolves. The
  task changes every glyph on screen; that is stated, not hidden.
- **T7 (CI lint gate)** — the repo is at **0 errors**, so an errors-only lint step **passes
  vacuously on its first run** and never demonstrates it can fail. Its entire value is
  prospective. The plan does not claim otherwise, and no task may cite T7 as evidence of anything
  about the current tree.

## Corrected counts

- **19** section directories carry a `page.tsx` under `src/app/dashboard/` (20 total, including
  the dashboard home). Earlier drafts said 17.
- **5** unnamed icon-only buttons exist at the cited lines, not 6.
- `export.ts:1052` is `String(p.quantity || 0)` → `"0"`, **not** a percentage. Only `:1058` is the
  percentage fabrication. Both sit in the **jsPDF** writer (`new jsPDF()` at :942), not the CSV
  builder.
- `cn()` has **37 call sites**; most are single-argument or template-literal, so the expected
  churn from T3 is near zero and the enumeration is bounded.
- T1's `PortfolioTable.tsx` is **deleted, not fixed** — zero importers, no test references it.
  Fixing a fabrication in a file nothing renders produces no user-observable change.

## Wave 1 — independent, disjoint files. Dispatch all in parallel.

### T1 · Close the 8 live data fabrications
**Symptom:** a null is published as a confident number. Six are twins of bugs this repo already
paid to fix elsewhere.
**Sites:** `PerformanceChart.tsx:124-126` (`+0.00%` in green) · `liquidity/page.tsx:780` (0%-wide
bar) · `export.ts:1052,1058` (`"0.0%"` into the CSV/PDF deliverable) ·
`volatility-sizing/page.tsx:1134` (null net cash → healthy green) · `:1075` (gross turnover
absorbs a dropped leg) · `concentration/page.tsx:404` (null weight → "Low" in CSV) ·
`useAnalytics.ts:329-336` (null market value → 0% sector share) · `PortfolioTable.tsx:192`.
**Note:** `PortfolioTable.tsx` is a *dead* component. Fix or delete — do not spend effort on a file
nothing imports.
**Verify:** `bun x vitest run` — count must not drop below 463, failures 0.

### T2 · Hold the `row.original` invariant for real (migration folded in)
**Symptom:** `AGENTS.md` forbids `row.original || row`; the fallback is **live in 8 files / 46
sites**, and **no test fails if someone reverts it**. The most heavily documented invariant in the
repo is enforced by nothing.
**Corrected after review — the original task was unenforceable.** `DataTable.tsx` contains no
`row.original` at all; its only row access is `row.getAllCells()` at `DataTable.tsx:197`. All 46
sites are column defs **local to the 8 page files** and are not exported. A test in
`DataTable.test.tsx` authors its own columns and would assert TanStack's contract, not this repo's
— it would pass forever no matter what production code does. That is the exact gap T2 exists to
close, so a test there would have shipped a green checkmark over an unenforced invariant.
**The migration is NOT deferred, and this is the reason:** `Row.original` is a non-optional
`TData` and is always truthy for a real row, so the `|| row` right-hand side **never fires**. The
46 sites are correct code carrying a dead branch. Removing it is a mechanical
`const data = row.original;` that `tsc` validates under the existing row types. Leaving it while
adding a test would convert "unfinished" into "signed off" — strictly worse than either honest
extreme.
**Do:** (a) migrate all 46 sites to `const data = row.original;` across the 8 files, dropping the
fallback and the accompanying `any`; (b) add the regression test **in a page suite that renders a
real column def** — `test/pages/LiquiditySkeleton.test.tsx` (7 sites) or
`test/pages/ScreenerStudio.test.tsx` (8 sites) — asserting on **rendered ticker text**, not on
TanStack internals.
**Verify:** 7 page suites already render the affected pages (`AbsentValueRendering`,
`FabricatedFallbacks`, `LiquiditySkeleton`, `ScreenerStudio`, `VolatilitySizingExecution`,
`SectionProvenance`, `AnalyticsUnavailableContracts`) and are the regression net. The new test
must go **red** when one of that page's own sites is reverted to the wrapper form, and green
restored. Paste both.

**T10 is deleted.** Leaving a documented invariant violated in 46 places is not an acceptable end
state, and "leave both in place, documented" is only acceptable if the documentation says the
invariant is *unenforced and violated* — which is not a state worth shipping.

### T3 · `cn()` never merges
**Symptom:** `cn()` calls `clsx` only (`utils.ts:13-15`). `tailwind-merge@3.7.0` is a direct
dependency used by exactly one file. Every `cn(...)` call in the app resolves conflicting Tailwind
utilities **last-wins instead of merge-wins**. The docblock still claims it "is a simplified
version of the popular 'clsx' library", which is now false.
**Do:** `twMerge(clsx(inputs))`; correct the docblock; add a unit test proving a conflicting pair
resolves by merge, not by position.
**Mandatory:** enumerate and report every existing `cn()` call site whose rendered class string
**changes** as a result. This is a visible change with no visual test net — it must be auditable,
not silent. If the enumeration is large, report it and defer the fix rather than shipping an
unreviewed visual change.
**Verify:** `bun x tsc --noEmit`, `bun x vitest run`, plus the enumeration.

### T4 · Geist is loaded, paid for, and overridden
**Symptom:** the app downloads Geist via `next/font` and renders **Arial**. `globals.css:13`
defines `--font-sans: var(--font-geist-sans)`; `globals.css:25` sets
`body { font-family: Arial, Helvetica, sans-serif }`. A type selector on `body` beats inheritance,
so the body and every descendant without its own font declaration renders Arial.
**Caution:** this changes every glyph on screen. It cannot ride along inside another refactor, and
there is no visual regression net. Report the blast radius.
**Verify:** `bun x tsc --noEmit`, `bun x vitest run` (463 must not drop).

### T5 · The shared layout downloads the PDF and spreadsheet libraries
**Symptom:** `Header.tsx:18` statically imports `ExportService`, which statically imports
`jspdf` + `xlsx` + `recharts` + `file-saver` (`export.ts:8-11`). `Header` renders inside
`DashboardLayout` → `dashboard/layout.tsx:7`, so **all 17 sections download them on first paint to
render an export button.**
**Do:** `await import('@/lib/export')` inside the export handler. The correct pattern already
exists at `forecast-risk/page.tsx:507` — copy it, do not invent one.
**Verify:** `bun x tsc --noEmit`, `bun x vitest run` (463 must not drop; 3 tests assert PDF output).

### T6 · Nine modals claim accessibility they do not implement
**Corrected after review — the original task rested on two false premises.**
1. `components/ui/dialog.tsx` is **NOT unused.** It is imported and used by
   `PortfolioDropzone.tsx:6` (`DialogContent` at :195), `AddPositionModalSimple.tsx:13` (:180)
   and `EditPositionModal.tsx:12` (:128) — three live components reached from `manage/page.tsx`,
   `dashboard/page.tsx` and `screener-studio/page.tsx`, covered by 4 test files. **A wrapper
   already proven in production beats 10 hand-rolled traps.**
2. **Escape is already bound on 9 of the 10.** `forecast-risk:199` · `concentration:223` ·
   `volatility-sizing:180` (→:199) and `:776` (→:1234) · `liquidity:144` · `stress-testing:241` ·
   `tear-sheet:194` · `equity-research:155` (→:1161) · `manage:912` (→:909). **Only
   `optimize:841` lacks it.**

**The real, remaining symptom:** these hand-rolled `<div role="dialog" aria-modal="true">`
modals have **no focus trap, no initial focus, and no focus restore**, while `aria-modal="true"`
promises all of it.
**Sites (9 modals + 1 inline panel):** `forecast-risk:213` · `concentration:238` ·
`volatility-sizing:199,1234` · `liquidity:159` · `stress-testing:256` · `tear-sheet:208` ·
`equity-research:1161` · `manage:909` — plus **`optimize:841`, which is NOT a modal**: it has no
`fixed inset-0` backdrop and no X, it is an inline panel closed programmatically at `optimize:406`.
Treat it separately — it needs an Escape handler, not a dialog conversion.
**Do:** convert the 9 to the existing `components/ui/dialog.tsx` primitives. Do **not** edit
`AbsentValueRendering.test.tsx` or `FabricatedFallbacks.test.tsx` to accommodate — if they go red,
the change is wrong, not the test.
**Verify:** `bun x vitest run` at >= 463 with 0 failures, plus a test per modal proving **focus is
trapped and restored**, and an Escape test **only for `optimize:841`**. The other nine already
have Escape — writing those tests would demand green-before-green and fail the hunk test.

### T7 · The lint baseline I have been quoting is not enforced
**Symptom:** CI runs `tsc` and `pytest` and **never runs eslint**. There is no `--max-warnings`.
The "271 warnings / 0 errors" figure this session has been treated as a held invariant is a local
observation enforced by nothing.
**Do:** add a lint step to `.github/workflows/ci-cd.yml` that fails on **errors only** — not on
warnings, or the 271 become a blocker nobody can clear.
**Verify:** the workflow file is valid YAML and the step's command is the repo's own (`bun x eslint`).

### T8 · Unnamed controls
**Symptom:** 6 icon-only buttons with no accessible name (`manage/page.tsx:841-846,850-855,
856-861` · `factor-exposure:158-163` · `stress-testing:760-765`) — one of which is the app's
smallest hit target with no focus ring. 5 `<label>` elements with no `htmlFor` and no `id` on their
control (`forecast-risk:914` · `settings:189` · `volatility-sizing:1650` ·
`stress-testing:769,781`).
**Note:** `factor-exposure:250` uses `outline-none` with no `focus-visible` replacement. Fix it.
**Verify:** `bun x vitest run`; plus a test asserting each named control has an accessible name.

---

## Wave 2 — depends on Wave 1 landing and being verified.

### T9 · Give the fabrication detector a source sweep
**Why:** `FabricatedFallbacks.test.tsx` is a **per-page** suite importing 10 pages. It has no
source-scanning counterpart, so a `?? 0` introduced anywhere else is invisible to it *by
construction*. The `format*` net solved exactly this problem by sweeping the module namespace.
**Do:** add a source sweep in the same spirit — read the tree, find `?? 0` / `|| 0` / `parseFloat(…) || 0`
in a value position, and require each hit to be either fixed or on an explicit allow-list with a
reason. It must be **proven red** on the current tree.
**Verify:** red before, green after; the allow-list cites file:line and a justification per entry.

### T10 · Resolve the documented-vs-actual contradiction on `row.original`
`AGENTS.md:37` forbids `row.original || row`. It is live in 46 places. Either the rule is
aspirational or the file drifted. T2 pins it; this task decides whether the 8 files are migrated to
the clean form or the rule is amended. **Do not amend `AGENTS.md` as a side effect** — if the
migration is too large for this wave, report the contradiction and leave both in place, documented.

---

## Explicitly DEFERRED, with reasons

| Deferred | Why |
|---|---|
| **react-query** adopt **or** remove | Installed, 0 call sites. Adopting is a net-new async architecture across 17 pages and would break all 43 test files' `vi.mock('@/lib/api')` pattern. Not a defect; it is tidiness. Removal is a 1-line `package.json` edit but has no user-observable effect. |
| **`cva`** removal | 0 imports, 0 call sites. Dead dependency. Same reasoning — no symptom. |
| **Dark-mode unification** | 8 of 20 pages are hardcoded dark, 12 themable. This is a genuine ~10k-line inconsistency and probably the single largest *visual* win — but it has no symptom, no failing test, and no user complaint behind it. It is Wave 5 material. |
| **Chart palette module** | Zero theming; `#3b82f6` redeclared in 6 files. Highest value for *perceived* quality and independent of everything else — but purely cosmetic, and it fails hunk test (1). |
| **`<Card>` / `<PageHeader>` extraction** | The `bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 border` string appears 18 times, byte-identical to `MetricCard.tsx:112`. Real duplication, refactor not defect. |
| **10 verbatim `HelpExplainer` copies** | ~40% of `tear-sheet` and `volatility-sizing` is this duplicated component. Largest mechanical win in the codebase and low risk — but no symptom. |
| **React Compiler** | `next.config.ts:5` disables it on purpose. 57 hand-written memo sites are doing real work. Enabling it rewrites render semantics app-wide. Not without a perf measurement. |
| **Radix dialog conversion** | Follow-up to T6. The smaller fix satisfies the defect. |
| **75 remaining `?? 0` / `|| 0` triaged as honest** | ~15 are legitimate empty-state zeros (count fallbacks inside null guards, form-input parsing). T9's allow-list is where that judgement gets recorded. |

## Verification, run by the orchestrator

```
cd frontend
bun x tsc --noEmit
bun x vitest run          # must be >= 43 files / 463 tests, 0 failures
bun x eslint src/         # must be 0 errors; warnings are not a gate
```
