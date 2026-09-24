# Equity Research

**Status:** PARTIAL — route states, ticker/tab/AI controls, and section evidence are complete; concall playback/shareholding deep validation and manual a11y remain partial.

## Route, fixture, and source identity

- **Route:** `/dashboard/equity-research`
- **Captured:** 2026-09-24 on the isolated testing frontend/backend (`127.0.0.1:3001` / `127.0.0.1:8001`).
- **Frontend build:** `hghBG-hlr8-XxzAq9sTq3`; the dirty working tree means this is not claimed to be exactly Git HEAD.
- **Fixtures:** empty (0 positions), seeded (5 mixed INR/USD positions), and desktop historical (same 5 positions with normalized purchase dates). Mobile historical was not captured.
- **Default research ticker:** `RELIANCE`, independent of the portfolio fixture.
- **Viewports:** desktop `1440×900`; mobile `390×844`.
- Evidence root: `.scratch/backend-deep-audit/browser-e2e/`.

## Coverage and controls

Captured states:

- Desktop empty, seeded, and historical.
- Mobile empty and seeded.

The visible research output is the same across all five captures: Reliance profile data, the same metrics, and the same overview/peer content. The only fixture-dependent text is the shared header position count.

Visible controls:

- Ticker input and **Search**.
- **8-Tab Excel Model**.
- **AI Memo** and **Forensic Audit**.
- Five research tabs: Overview & Analysis, Shareholding, Concalls & Audio, 10-Year Audited Statements, and AI Dossier & Prompts.
- Within the overview: company website and peer-company buttons.
- Shared header: live-data toggle, PDF export, portfolio refresh, and dark-mode toggle.

Desktop capture shows the action bar, profile/ratios, tabs, and the top of the overview. Mobile capture shows the action bar and profile header; the lower tabs and sections are below the captured viewport. Final internal-scroll section set is now present.

Primary evidence:

- `evidence/screenshots/desktop/{empty,seeded,historical}/dashboard-equity-research.png`
- `evidence/screenshots/mobile/{empty,seeded}/dashboard-equity-research.png`
- `evidence/network/pages/{desktop,mobile}/{empty,seeded,historical}/dashboard-equity-research.txt`
- `evidence/network/pages/{desktop,mobile}/{empty,seeded,historical}/dashboard-equity-research.snapshot.txt`

## API, console, and network evidence

Every captured state issued three initial GETs, all HTTP 200:

1. `GET /api/v1/company/RELIANCE/full-profile`
2. `GET /api/v1/company/RELIANCE/shareholding`
3. `GET /api/v1/company/RELIANCE/concalls`

| State | API requests | Bad/missing status | Console messages | Page errors |
|---|---:|---:|---:|---:|
| Desktop empty | 3 | 0 | 0 | 0 |
| Desktop seeded | 3 | 0 | 0 | 0 |
| Desktop historical | 3 | 0 | 0 | 0 |
| Mobile empty | 3 | 0 | 0 | 0 |
| Mobile seeded | 3 | 0 | 0 | 0 |

Not requested in the initial captures:

- `GET /api/v1/data/financials/{ticker}` (lazy financial-statement tab).
- `GET /api/v1/company/{ticker}/export-excel`.
- `GET /api/v1/company/{ticker}/ai-memo-prompt`.
- `GET /api/v1/company/{ticker}/ai-forensic-prompt`.
- `GET /api/v1/company/{ticker}/ai-dossier`.

The network capture records metadata but not direct raw response bodies. No ticker search, tab switch, download, prompt modal, or peer navigation was exercised.

Evidence:

- `evidence/network/pages/{desktop,mobile}/{empty,seeded,historical}/dashboard-equity-research.network.json`
- `evidence/network/console/{desktop,mobile}/{empty,seeded,historical}/dashboard-equity-research.console.json`
- `evidence/network/console/{desktop,mobile}/{empty,seeded,historical}/dashboard-equity-research.errors.json`

## Source and freshness review

- The page defaults to `RELIANCE` and concurrently requests full profile, shareholding, and concalls (`frontend/src/app/dashboard/equity-research/page.tsx:43-128`). It clears old-company data and uses a monotonic sequence to reject stale ticker-switch responses.
- Financial statements are intentionally lazy and load only when the statements tab is active (`frontend/src/app/dashboard/equity-research/page.tsx:130-149`).
- The backend identifies the profile source as `bfinance` and returns current price/ratios without a quote timestamp, delayed/live flag, or provider response identifier (`backend/app/services/equity_research_service.py:36-125`). The UI labels the terminal “bfinance 10-13Y Ind AS” but does not show data as-of metadata.
- The captured current price was `₹1,227.00`. `data-freshness-bugs.md` records the same app value against a secondary current observation near `₹1,238.40` and classifies it `STALE / DISCREPANCY`; no official exchange numeric page was available.
- Shareholding and statement periods are available only inside their respective tabs/payloads. The initial visible overview did not expose filing/publication timestamps.
- The `AI Dossier & Prompts` tab renders memo and forensic prompt actions only (`frontend/src/app/dashboard/equity-research/page.tsx:1105-1150`). The available `/company/{ticker}/ai-dossier` endpoint is not called by this page, even though `frontend/src/lib/api.ts:502-507` defines a wrapper.

## Financial verdicts

| Item | Verdict | Basis |
|---|---|---|
| Current price `₹1,227.00` | `STALE / DISCREPANCY` | Same value is classified against the audit's secondary current observation in `data-freshness-bugs.md`; timing/provider uncertainty remains. |
| Graham fair-value margin `-25.75%` from displayed `₹911` and `₹1,227` | `VERIFIED` (arithmetic only) | `(911 - 1227) / 1227` rounds to the displayed percentage; underlying inputs remain unverified. |
| Current price inside displayed 52-week range `₹1,226–₹1,612` | `VERIFIED` (presentation consistency only) | `1227` lies within the displayed bounds; range accuracy is not independently verified. |
| Market cap, P/E, ROCE, ROE, book value, dividend yield, peer metrics, CAGRs, strengths/risks | `UNVERIFIABLE` | No direct raw payload, filing periods, or primary-source reconciliation were captured. |
| Concalls count `47` and audio content | `PARTIAL` | Count text is visible; media playback was not exercised. |
| Shareholding and audited-statement values | `PARTIAL` | Audited-statement tab and raw request were exercised; shareholding deep validation remains partial. |

## Findings

### ER-001 — Current price and fundamental values lack as-of/provider provenance

- **Severity:** P2
- **Owner:** backend/provider contract and frontend presentation
- **Evidence:** profile response contains `source: bfinance` but no quote as-of/delayed/live metadata; visible `₹1,227.00` is stale/discrepant against the audit's secondary spot check.
- **Expected:** expose quote timestamp, provider, delayed/live status, and statement/fiscal-period metadata next to the values.

### ER-002 — “AI Dossier & Prompts” does not expose the available AI dossier API

- **Severity:** P2
- **Owner:** frontend
- **Evidence:** `route-inventory.md` records the route/contract mismatch; the tab only invokes memo/forensic prompt handlers, while `/company/{ticker}/ai-dossier` remains API-only.
- **Expected:** either expose the dossier action/result or rename the tab so it does not imply a dossier capability.

### ER-003 — Seeded desktop accessibility violation

- **Severity:** P2
- **Owner:** frontend shared sidebar
- **Evidence:** desktop seeded and historical axe each recorded one serious `color-contrast` node for the Equity Research sidebar description. Mobile seeded recorded 0 violations.
- **Files:** `evidence/network/desktop/{seeded,historical}/dashboard-equity-research.a11y.json`, `evidence/network/mobile/seeded/dashboard-equity-research.a11y.json`.

## Pending / not tested

- Mobile historical capture.
- Search with a second valid ticker, unknown ticker, empty input, and rapid-switch stale-response behavior.
- Shareholding quarterly/yearly controls, concall record/audio playback, all statement/frequency controls, and retry behavior.
- Excel workbook generation/content, AI memo/forensic modal and clipboard actions, and direct AI dossier behavior.
- Direct raw profile/shareholding/concall/financial payloads and primary-source financial-statement reconciliation.
- Empty-state axe, manual keyboard/focus order, screen-reader labels for dense peer/tab controls, and mobile touch-target measurement.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 12 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-equity-research-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-equity-research-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-equity-research-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-equity-research-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-equity-research-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-equity-research-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Ticker search | RELIANCE → TCS.BO; company requests returned 200. | `../evidence/network/console/desktop/interactions/equity-controls.txt` |
| Audited statements tab | Income/annual statement request captured. | `../evidence/screenshots/interactions/desktop-equity-financial-statements.png` |
| AI prompts | Memo and forensic prompt endpoints returned 200. | `../evidence/screenshots/interactions/desktop-equity-ai-forensic.png` |
