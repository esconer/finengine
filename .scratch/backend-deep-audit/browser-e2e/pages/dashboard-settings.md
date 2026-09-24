# Settings

**Status:** PARTIAL — source save/restore, cache purge, section evidence, and runtime checks are complete; failure paths/manual a11y remain untested.

## Route, fixture, and source identity

- **Route:** `/dashboard/settings`
- **Captured:** 2026-09-24 on the isolated testing frontend/backend (`127.0.0.1:3001` / `127.0.0.1:8001`).
- **Frontend build:** `hghBG-hlr8-XxzAq9sTq3`; the dirty working tree means this build is not claimed to be exactly Git HEAD.
- **Fixtures:** empty (0 positions), seeded (5 positions), and desktop historical (same 5 positions with normalized purchase dates). Mobile historical was not captured.
- Settings content and selected source were identical across captured fixtures; the shared header position count was fixture-dependent.
- **Viewports:** desktop `1440×900`; mobile `390×844`.
- Evidence root: `.scratch/backend-deep-audit/browser-e2e/`.

## Coverage and controls

Captured states:

- Desktop empty, seeded, and historical.
- Mobile empty and seeded.

Visible controls:

- Primary source cards: **bfinance (Recommended)** and **yfinance**.
- **Clear Market Data Cache**.
- **Save Data Source Preference**, disabled while unchanged.
- Shared header: live-data toggle, PDF export, portfolio refresh, and dark-mode toggle.

Visible copy describes:

- A bfinance-first or yfinance-first fallback chain with Alpha Vantage last.
- Application to price history, quotes, and fundamentals.
- bfinance-only concalls, audited statements, and screeners; yfinance-only USD/INR FX.
- Static descriptions for market price, Screener.in, and NSE bhavcopy/microstructure feeds.
- Portfolio holdings as unaffected by cache clearing.

The UI showed bfinance as Primary and Save disabled in the captured states. Desktop showed the complete form and actions. Mobile showed the title, source cards, fallback chain, and the start of the feed cards; the action buttons were below the captured viewport. Final internal-scroll set is now present.

Primary evidence:

- `evidence/screenshots/desktop/{empty,seeded,historical}/dashboard-settings.png`
- `evidence/screenshots/mobile/{empty,seeded}/dashboard-settings.png`
- `evidence/network/pages/{desktop,mobile}/{empty,seeded,historical}/dashboard-settings.txt`
- `evidence/network/pages/{desktop,mobile}/{empty,seeded,historical}/dashboard-settings.snapshot.txt`

## API, console, and network evidence

Every captured state issued one initial GET, all HTTP 200:

- `GET /api/v1/data/config`

| State | API requests | Bad/missing status | Console messages | Page errors |
|---|---:|---:|---:|---:|
| Desktop empty | 1 | 0 | 0 | 0 |
| Desktop seeded | 1 | 0 | 0 | 0 |
| Desktop historical | 1 | 0 | 0 | 0 |
| Mobile empty | 1 | 0 | 0 | 0 |
| Mobile seeded | 1 | 0 | 0 | 0 |

Interaction follow-up captured:

- `PUT /api/v1/data/config?primary_source=yfinance` and restoration to `bfinance` (200).
- `POST /api/v1/data/cache/clear` (200) and the subsequent portfolio refresh (200).

The original baseline lacked direct raw config bodies; the follow-up captured the two PUTs and cache-clear POST, while TTL/cache-enable details remain outside this UI contract.

Evidence:

- `evidence/network/pages/{desktop,mobile}/{empty,seeded,historical}/dashboard-settings.network.json`
- `evidence/network/console/{desktop,mobile}/{empty,seeded,historical}/dashboard-settings.console.json`
- `evidence/network/console/{desktop,mobile}/{empty,seeded,historical}/dashboard-settings.errors.json`

## Source and freshness review

- On mount, the page calls `dataApi.getConfig()` and adopts the returned `primary_source` (`frontend/src/app/dashboard/settings/page.tsx:54-68`).
- If that GET fails, the catch is intentionally empty: the page keeps its bfinance default and gives no visible load-error state (`frontend/src/app/dashboard/settings/page.tsx:54-66`).
- Save issues `PUT /data/config?primary_source=...` and then marks the local selection saved (`frontend/src/app/dashboard/settings/page.tsx:75-98`; `frontend/src/lib/api.ts:283-291`).
- Backend source change handling deletes all `StockTimeseries` and `AnalyticsCache` rows, advances the cache generation, and clears service memos before committing the new preference (`backend/app/api/data.py:383-435`). The current UI does not warn that changing the primary source broadly invalidates cached time series and analytics.
- Cache clear calls `POST /data/cache/clear` and then refreshes the portfolio (`frontend/src/app/dashboard/settings/page.tsx:100-129`). Backend source states that holdings are preserved while timeseries, analytics, fetch logs, and NSE microstructure caches are purged (`backend/app/api/data.py:467-488`).
- The frontend wrapper's `updateConfig` return type claims a flat config, while the backend returns `{updated, settings, message}` (`frontend/src/lib/api.ts:288-290`; `backend/app/api/data.py:443-454`). The page currently ignores the response body, so this mismatch was not visibly exercised.
- No provider-health endpoint backs the feed descriptions; the page intentionally contains static feed copy rather than live status.

## Financial verdicts

- **Overall:** `NOT APPLICABLE` — this route does not calculate or display portfolio financial values.
- The source-preference/cache actions can affect data used by financial pages. This audit restored bfinance and preserved the five-position portfolio after the cache purge; no before/after market-accuracy verdict is inferred.
- No data-as-of claim is made by this page; the shared header's `Last updated: Never` is portfolio-shell state, not a Settings configuration timestamp.

## Findings

### SET-001 — Source change performs broad cache invalidation without a UI warning

- **Severity:** P2
- **Owner:** frontend and backend configuration contract
- **Evidence:** backend deletes all stock time series and analytics cache rows when the primary source changes; the Save UI only says it is saving a preference.
- **Expected:** disclose the invalidation scope and impact before saving, or make the backend change narrowly scoped and observable.

### SET-002 — Config read failure is silently converted into an unverified default

- **Severity:** P2
- **Owner:** frontend
- **Evidence:** `frontend/src/app/dashboard/settings/page.tsx:54-66` catches and discards the config GET error, leaving the bfinance card selectable/visibly primary without proving backend truth.
- **Expected:** show “configuration unavailable,” prevent a false Primary state, and distinguish default from persisted preference.

### SET-003 — Seeded color-contrast violations

- **Severity:** P2
- **Owner:** frontend
- **Evidence:** desktop seeded/historical axe recorded one serious `color-contrast` rule with 7 nodes; mobile seeded recorded the same rule with 4 nodes. Targets include source blurbs, scope/fallback copy, feed descriptions, and the cache-clear button text.
- **Files:** `evidence/network/desktop/{seeded,historical}/dashboard-settings.a11y.json`, `evidence/network/mobile/seeded/dashboard-settings.a11y.json`.

## Pending / not tested

- Mobile historical capture.
- Selecting yfinance, Save success, and restoration to bfinance were exercised; persistence after a separate reload was not rechecked.
- Save validation/backend failure and config-GET failure behavior.
- Clear-cache confirmation accept, row-summary response, portfolio preservation, and post-clear refresh were exercised; cancel/failure handling remains untested.
- Direct raw config/save/cache-clear responses and database before/after proof.
- Empty-state axe, manual keyboard/focus order and selected-state announcement for the custom source selector, screen-reader testing, and mobile reachability of the bottom actions.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-settings-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-settings-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-settings-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-settings-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-settings-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-settings-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Source preference | yfinance saved then bfinance restored; both PUTs returned 200. | `../evidence/network/console/desktop/interactions/settings-source2.txt` |
| Cache purge | Cache-clear POST returned 200 and portfolio refresh completed. | `../evidence/network/console/desktop/interactions/settings-cache.txt` |
