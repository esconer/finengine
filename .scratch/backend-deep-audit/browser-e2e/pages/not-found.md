# 404 Boundary

**Status:** COMPLETE — boundary route captured at desktop/mobile with section evidence; no mutation path applies.

## Route, fixture, and source identity

- **Route exercised:** `/audit-missing-route-404`
- **Boundary:** Next.js `not-found.tsx`, rather than one of the 20 product routes.
- **Captured:** 2026-09-24 on the isolated testing frontend (`127.0.0.1:3001`).
- **Frontend build:** `hghBG-hlr8-XxzAq9sTq3`; the dirty working tree means this build is not claimed to be exactly Git HEAD.
- **Fixtures:** empty (0 positions), seeded (5 positions), and desktop historical (same 5 positions with normalized purchase dates). Mobile historical was not captured.
- **Viewports:** desktop `1440×900`; mobile `390×844`.
- Evidence root: `.scratch/backend-deep-audit/browser-e2e/`.

## Coverage and controls

Captured states:

- Desktop empty, seeded, and historical.
- Mobile empty and seeded.

Visible content was identical in all five states:

- Heading: “404 — Page not found”.
- Explanation: “The page you are looking for does not exist or has been moved.”
- **Back to dashboard** link to `/dashboard`.

There are no page inputs, sidebar links, shared header controls, or API-backed panels on this boundary. Desktop and mobile screenshots show the content centered with no visible clipping in the captured viewport.

Primary evidence:

- `evidence/screenshots/desktop/{empty,seeded,historical}/not-found.png`
- `evidence/screenshots/mobile/{empty,seeded}/not-found.png`
- `evidence/network/pages/{desktop,mobile}/{empty,seeded,historical}/not-found.txt`
- `evidence/network/pages/{desktop,mobile}/{empty,seeded,historical}/not-found.snapshot.txt`

## API, console, and network evidence

Every captured direct navigation returned the expected document status:

- `GET http://127.0.0.1:3001/audit-missing-route-404` → HTTP 404.

| State | API requests | Document status | Bad/missing status | Console messages | Page errors |
|---|---:|---:|---:|---:|---:|
| Desktop empty | 0 | 404 | 1 expected document | 0 | 0 |
| Desktop seeded | 0 | 404 | 1 expected document | 0 | 0 |
| Desktop historical | 0 | 404 | 1 expected document | 0 | 0 |
| Mobile empty | 0 | 404 | 1 expected document | 0 | 0 |
| Mobile seeded | 0 | 404 | 1 expected document | 0 | 0 |

The single 4xx request is the intended unknown-route document response, not a backend API failure. No calls to `127.0.0.1:8001/api/v1` were captured.

Evidence:

- `evidence/network/pages/{desktop,mobile}/{empty,seeded,historical}/not-found.network.json`
- `evidence/network/console/{desktop,mobile}/{empty,seeded,historical}/not-found.console.json`
- `evidence/network/console/{desktop,mobile}/{empty,seeded,historical}/not-found.errors.json`

## Source and freshness review

- `frontend/src/app/not-found.tsx:3-19` renders a standalone `<div>`, an `<h2>`, explanatory text, and a Next `<Link href="/dashboard">`.
- The page has no client-side data fetch, timestamp, provider source, or portfolio dependency. Fixture changes do not alter its visible content.
- The unknown URL and HTTP 404 document status were directly captured. The destination of **Back to dashboard** was not followed in this evidence set.

## Financial verdicts

- **Overall:** `NOT APPLICABLE` — the boundary contains no financial values, calculations, or data-freshness claim.
- Portfolio fixture has no effect on the 404 content or document status.

## Findings

### NF-001 — 404 page lacks H1, main landmark, and contained region semantics

- **Severity:** P2
- **Owner:** frontend
- **Evidence:** desktop seeded, desktop historical, and mobile seeded axe each recorded 3 moderate violations: `page-has-heading-one`, `landmark-one-main`, and `region`, one node each. The semantic tree has only an `<h2>` inside a plain `<div>` (`frontend/src/app/not-found.tsx:5-18`).
- **Expected:** use a page-level `<h1>` and a `<main>` landmark containing the content.

### NF-002 — “Back to dashboard” destination is not interaction-proven

- **Severity:** P3
- **Owner:** audit coverage
- **Evidence:** the link is visible and source points to `/dashboard`, but no click/network capture confirms navigation in this evidence set.
- **Next proof:** activate the link with keyboard and pointer and capture the resulting route/document.

## Pending / not tested

- Mobile historical capture.
- Pointer and keyboard activation of **Back to dashboard**, focus destination, browser back/forward behavior, and direct reload of `/dashboard` after navigation.
- Empty-state axe.
- Manual screen-reader announcement, landmark navigation, heading navigation, focus order, zoom/reflow, and contrast review.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 1 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/not-found-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/not-found-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/not-found-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 1 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/not-found-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/not-found-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/not-found-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

No additional mutation or provider-control workflow was required for this boundary route; settled desktop/mobile section evidence is the interaction coverage.
