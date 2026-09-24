# Portfolio Management — Page Report

**Status:** PARTIAL — CRUD, currency, CSV, section evidence, and runtime checks are complete; independent risk-column replay/manual a11y remain partial.
**Route:** `/portfolio/manage`  
**Audit date:** 2026-09-24  
**Evidence stack:** isolated production frontend on `127.0.0.1:3001` and testing backend on `127.0.0.1:8001`.

> Evidence paths beginning `../evidence/` are relative to this report. This report uses existing evidence only; no new browser/API/network call was made.

## Route and fixture

- **Empty:** zero positions.
- **Seeded:** five synthetic cash equities across INR/USD: RELIANCE.NS, HDFCBANK.NS, TCS.BO, AAPL, and MSFT. Quantities and buy prices are listed in `dashboard.md` and `../evidence/runtime/synthetic-fixture.json`.
- **Historical:** the same five holdings with `added_on=2025-01-01`; earlier seeded captures show `2026-09-24`.
- **Single holding:** RELIANCE.NS was added first and then used to verify the 100% weight invariant.
- **Viewports:** desktop `1440×900`; mobile `390×844`.
- The captured build came from a dirty tree; current source explains behavior but is not claimed to be identical to the captured build.

## Coverage

| State/behavior | Desktop | Mobile | Status |
|---|---|---|---|
| Empty | `../evidence/screenshots/desktop/empty/portfolio-manage.png` | `../evidence/screenshots/mobile/empty/portfolio-manage.png` | Captured |
| Five-position seeded | `../evidence/screenshots/desktop/seeded/portfolio-manage.png` | `../evidence/screenshots/mobile/seeded/portfolio-manage.png` | Captured |
| Historical holding dates | `../evidence/screenshots/desktop/historical/portfolio-manage.png` | Not captured | Desktop only |
| USD selected | `../evidence/screenshots/states/portfolio-manage-usd.png` | Not captured | Desktop state evidence |
| Add/validation/duplicate/malformed | State/issue captures under `../evidence/screenshots/issues/` and `../evidence/network/pages/desktop/` | Not captured | Desktop exercised |
| Edit, delete, persistence/revert | `../evidence/screenshots/states/desktop-hdfc-edit.png`, `../evidence/screenshots/states/desktop-aapl-deleted.png` | Not captured | Exercised and reverted per audit todo |
| CSV import | `../evidence/screenshots/states/desktop-csv-import-complete.png` | Unsupported-file desktop evidence | INFY.NS imported then removed; `.xlsx` rejection captured |
| Final internal-scroll sections | 13 desktop captures | 13 mobile captures | See **Final internal-scroll evidence** |

## Executive verdict

- Route-specific edit/delete persistence and INR/USD switching were exercised on desktop. The shared Add Position/validation flow was exercised from Dashboard/root; it was not independently repeated from this route.
- Financial presentation is not reliable for a mixed-currency portfolio: envelope totals are converted correctly, but row values and summary P&L remain native/mixed-native and are relabeled as the selected currency.
- AAPL is materially mispriced, and the shared Add Position component can submit a US ticker as region `IN` in INR mode.
- Local page state and the global header can disagree after CRUD: edit evidence shows header `4 positions` while the page shows 5; delete evidence shows header 4 while the page shows 3.
- The mobile action row visibly clips “Import CSV” at the right edge and does not show “Add Position” in the first viewport.

## Visible behavior

### Empty state

- Shows Total Value ₹0.00, Total Gain/Loss +₹0.00, Positions 0, Avg Weight 0%.
- Provides USD/INR, Refresh, Import CSV, and Add Position controls.
- Body says “No positions” and provides a second Add Position action.
- Text: `../evidence/network/pages/desktop/empty/portfolio-manage.txt` and `../evidence/network/pages/mobile/empty/portfolio-manage.txt`.

### Five-position seeded state

- Envelope Total Value: ₹249,827.31.
- Page-computed Total Gain/Loss: +₹752.21 / +1.27%.
- Portfolio Statistics: MSFT best +64.40%, AAPL worst -96.74%, 3 winners / 2 losers, largest position 75.8%.
- Statistics cards: Total Investment ₹59,450.00, Current Value ₹60,202.21, Average Return +3.98%.
- The table renders all position values with the selected currency symbol even though AAPL/MSFT monetary fields remain native.
- Full text: `../evidence/network/pages/desktop/seeded/portfolio-manage.txt` and `../evidence/network/pages/desktop/historical/portfolio-manage.txt`.

### USD state

- Envelope Total Value: $2,603.86.
- Gain/Loss remains +$752.21 / +1.27%; statistics remain $59,450.00 investment and $60,202.21 current value.
- Indian rows are shown as `$31,335.00`, `$14,600.00`, and `$12,270.00`; these are native INR values with a dollar prefix, not converted USD.
- Evidence: `../evidence/screenshots/states/portfolio-manage-usd.png`, `../evidence/network/pages/desktop/states/portfolio-manage-usd.txt`, and `../evidence/network/pages/desktop/states/portfolio-usd-api.json`.

## Controls and exercised behavior

| Control | Runtime evidence | Verdict/notes |
|---|---|---|
| USD / INR toggle | **Exercised** | Envelope switches correctly; rows/summary do not convert (`FE-001`) |
| Refresh | Present | **Not exercised**; backend GET itself can refresh/commit quotes |
| Import CSV | Present | **Exercised**; valid INFY.NS import and unsupported `.xlsx` rejection captured; temporary row removed |
| Add Position | Shared modal exercised elsewhere; not independently repeated here | Dashboard/root evidence covers empty, malformed, non-positive, duplicate, and AAPL/MSFT attempts |
| Ticker/quantity/buy-price/date validation | Shared modal exercised elsewhere; not independently repeated here | Dashboard/root captures show required, format, positive-value, weight, and duplicate messages |
| Search by ticker/name/sector | Present | **Not exercised** |
| Sortable table headers | Present | **Not exercised** |
| Inline edit: name, quantity, buy price, date, weight | **Exercised** | HDFC row changed to quantity 21, buy ₹510, edited name; fixture was subsequently reverted |
| Save/cancel edit controls | Save exercised; cancel not evidenced | Positive-number/date validation exists in source |
| Delete confirmation and persistence | **Exercised** | AAPL deletion reduced body count; state was subsequently restored |
| Row edit/delete icon buttons | Present | Both are unnamed to assistive technology |
| Volatility/VaR/Risk Level columns | Populate in captures | Financial replay **not tested** |
| Header PDF/Live/refresh/dark-mode/menu | Present | **Not exercised** |

Primary control source: `frontend/src/app/portfolio/manage/page.tsx:43-365` and `frontend/src/app/portfolio/manage/page.tsx:377-900`.

## Financial verdicts

| Value/behavior | Verdict | Evidence/qualification |
|---|---|---|
| First position weight | `VERIFIED` | Empty portfolio → first holding renders 100.00% / `1.0` |
| First position value, cost, P&L | `VERIFIED` | ₹12,270 value; ₹10,000 cost; +₹2,270 P&L |
| Native position arithmetic | `VERIFIED` for returned quantities/prices | All five `quantity × last_price` values reconcile internally |
| INR envelope total | `VERIFIED` | ₹249,827.31377746275; replay error ≈ `1.8e-11` |
| USD envelope total | `VERIFIED` | $2,603.8596547198676; replay error ≈ `2.5e-13` USD |
| Five-position page Gain/Loss | `DISCREPANCY` | +₹752.21 / +1.27% is a mixed-native subtraction; same-current-FX reference is ≈ +₹5,234.56 / +2.14% |
| Portfolio Statistics totals | `DISCREPANCY` | ₹59,450 cost and ₹60,202.21 current value are mixed-native sums, not INR totals |
| INR row values for AAPL/MSFT | `DISCREPANCY` | $24.45 and $1,972.7600 are rendered with ₹; envelope uses converted INR |
| USD row values | `DISCREPANCY` | Native INR rows are rendered with `$`; row sum $60,202.21 contradicts the $2,603.86 envelope |
| USD Gain/Loss and percentage | `DISCREPANCY` | Expected consistent same-snapshot USD reference is about $54.558 / 2.14%, not $752.21 / 1.27% |
| Largest position 75.8% | `VERIFIED` for returned base-currency weights | Conditional on bad AAPL quote and current FX |
| AAPL quote and row return | `DISCREPANCY` | $4.89 quote; -96.74% row return follows that quote but is not externally valid |
| MSFT quote | `STALE` / timing-sensitive | $493.19 versus $495.07 observation |
| RELIANCE.NS quote | `STALE` | ₹1,227 versus ~₹1,238.40 observation |
| HDFCBANK.NS / TCS.BO quotes | `VERIFIED` within intraday tolerance | See `../financial-reconciliation.md` |
| Per-row GARCH volatility/VaR/risk label | `PARTIAL` | Values rendered; direct raw response/model replay completed where exposed, with documented discrepancies |
| True acquisition-date mixed-currency P&L | `UNVERIFIABLE` | No dated USD/INR acquisition FX or transaction/cash ledger |

The same-current-FX references are conditional on the erroneous AAPL quote and are not a substitute for historical-FX cost basis.

## API, network, and console

- Empty desktop/mobile: one completed `GET /portfolio?currency=INR`, HTTP 200.
- Seeded/historical desktop and seeded mobile: portfolio GET plus one GARCH forecast-risk GET, both HTTP 200.
- No console errors or warnings were recorded for baseline empty/seeded/historical captures.
- CSV import evidence: `../evidence/network/console/desktop/states/import-csv-parsed.txt`, `../evidence/network/console/desktop/states/import-csv-submit.txt`, and `../evidence/network/console/desktop/states/import-csv-unsupported.txt`.
- CRUD evidence is split across `../evidence/network/pages/desktop/states/` and `../evidence/network/pages/desktop/issues/`.
- `GET /portfolio` and `GET /portfolio/{ticker}` refresh and commit quote values despite being GETs; see `../backend-bugs.md` (`BE-006`).

## Accessibility and responsive evidence

### Axe

- Seeded desktop: `button-name` critical (10 nodes) and `heading-order` moderate (1).
- Seeded mobile: the same 10 unnamed buttons, plus `color-contrast` serious (1), and `heading-order` moderate (1).
- Historical desktop repeats the two desktop rules.
- The ten nodes are five edit buttons plus five delete buttons. Source: `frontend/src/app/portfolio/manage/page.tsx:780-812`.
- No empty-state axe run exists.

Evidence: `../evidence/network/desktop/seeded/portfolio-manage.a11y.json`, `../evidence/network/mobile/seeded/portfolio-manage.a11y.json`, and `../evidence/network/desktop/historical/portfolio-manage.a11y.json`.

### Responsive

- Desktop table is wider than the content area and is placed in `overflow-x-auto`; the first viewport shows only the left portion.
- At 390px, the header title and controls are crowded. The action row visibly clips “Import CSV” at the right edge; “Add Position” is outside the captured viewport because the source action container does not wrap.
- Whether clipped actions remain reachable by horizontal scrolling and whether the table has acceptable touch scrolling are **not tested**.

## Findings

### PM-01 — Selected-currency view relabels native position values

- **Severity:** P1
- **Owner:** frontend primary; backend contract ambiguity contributes
- **Observed:** Envelope total is converted, but all position monetary fields are formatted as the selected currency. INR native values get `$`; USD native values get `₹`.
- **Expected:** Return converted position values for the selected base or expose explicit native/base dual fields and preserve provenance in the UI.
- **Reproduction:** Seed mixed INR/USD holdings, open `/portfolio/manage`, select USD, and compare the $2,603.86 envelope with row/card totals.

### PM-02 — Gain/loss and statistics subtract mixed-native monetary values

- **Severity:** P1
- **Owner:** frontend primary; backend native/base contract contributes
- **Observed:** Cost and current values are summed directly across INR/USD and then formatted as one selected currency.
- **Expected:** Aggregate both sides in a declared base currency with explicit FX provenance.

### PM-03 — Header count diverges from page state after CRUD

- **Severity:** P2
- **Owner:** frontend
- **Observed:** After HDFC edit, header says `4 positions` while the page summary says 5. After AAPL deletion, header says 4 while the page says 3. After a successful INFY CSV import, the header says `0 positions` / `Last updated: Never` while the table shows six.
- **Cause:** Manage owns local `positions`; Header reads persisted Zustand `usePortfolioStore.positions`.
- **Evidence:** `../evidence/network/pages/desktop/states/hdfc-edit.txt` and `../evidence/network/pages/desktop/states/aapl-deleted.txt`.
- **Expected:** Use one authoritative portfolio state or synchronize the global store after every successful CRUD/refresh.

### PM-04 — US ticker can be submitted as India region in INR mode

- **Severity:** P1
- **Owner:** frontend
- **Observed at Dashboard route:** AAPL submitted with `region: "IN"`. Manage uses the same `AddPositionModalSimple`; current source maps non-suffix tickers to `IN` when currency is INR.
- **Route-specific limitation:** AAPL submission from `/portfolio/manage` was not separately runtime-captured.
- **Source:** `frontend/src/components/portfolio/AddPositionModalSimple.tsx:153-171`.

### PM-05 — CSV importer hard-codes India region

- **Severity:** P1/P2 confirmed by browser/API evidence
- **Owner:** frontend
- **Source-confirmed:** Every imported row is submitted with `region: 'IN'` at `frontend/src/components/portfolio/PortfolioDropzone.tsx:161-179`.
- **Expected:** Infer/import region and currency per ticker.
- **Runtime status:** Valid INFY.NS import and unsupported `.xlsx` rejection were exercised. A US-row import remains untested.

### PM-06 — Ten row-action buttons have no accessible names

- **Severity:** P2
- **Owner:** frontend
- **Expected:** Provide ticker-specific names such as “Edit RELIANCE.NS” and “Delete RELIANCE.NS,” or visible text/tooltips tied to accessible names.

### PM-07 — Mobile action controls overflow the first viewport

- **Severity:** P2 provisional
- **Owner:** frontend
- **Observed:** At 390×844, “Import CSV” is cut at the right edge and Add Position is not visible. Source uses a non-wrapping flex action row.
- **Limitation:** Final scrolled-state evidence is present; horizontal reachability/touch behavior remains untested.

### PM-08 — Freshness/status labels are stale or ambiguous

- **Severity:** P2/P3
- **Owner:** frontend for display synchronization; backend for quote as-of provenance
- **Observed:** Baseline header remains `Last updated: Never` despite loaded data; CRUD also leaves header position count stale. “Live” does not expose quote provider/as-of state.
- **Expected:** Synchronize the UI clock after successful portfolio/CRUD loads and distinguish fetch time from market-data as-of time.

## Reproduction summary

1. Use only the documented isolated testing stack and synthetic SQLite fixture.
2. Empty-state: open `/portfolio/manage`; verify the zero summary and available controls.
3. First-position invariant: add RELIANCE.NS to an empty book; verify 100.00% and the values in `../evidence/network/pages/desktop/states/single-holding-after-add.txt`.
4. CRUD: exercise edit and delete using the preserved state captures; confirm persistence and restoration.
5. Currency: select USD and compare the envelope, row values, statistics totals, and gain/loss with `../evidence/calculations/outputs/portfolio-reconciliation.md`.
6. Accessibility: run axe at 1440×900 and 390×844; inspect edit/delete button names.

## Pending / not tested

- Oversized and formula-like CSV inputs.
- Search, every sortable column, pagination, forecast-column sorting, and horizontal table scrolling.
- Route-specific AAPL/MSFT add from Manage, US CSV row, delete-cancel/Escape/focus trap, and concurrent-refresh behavior.
- Direct raw forecast response and independent per-position GARCH replay.
- Controlled provider, database-unavailable, and WebSocket states.
- Manual keyboard, focus order, zoom, and screen-reader validation.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/portfolio-manage-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/portfolio-manage-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/portfolio-manage-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/portfolio-manage-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/portfolio-manage-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/portfolio-manage-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| CSV import | Valid INFY.NS import and unsupported .xlsx rejection captured; temporary row removed. | `../evidence/network/console/desktop/interactions/import-csv-submit.txt` |
| Header synchronization | Successful import exposed stale 0 positions / Last updated: Never. | `../evidence/screenshots/states/desktop-csv-import-complete.png` |
