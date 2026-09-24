# FinEngine End-to-End Browser Audit

**Status:** COMPLETE — 2026-09-25  
**Audit window:** 2026-09-24–25 UTC  
**Mode:** Isolated synthetic-data browser/runtime/financial audit; no intentional source/config/test/Git edits.

## Coverage completed

- Product routes discovered and captured: **20/20**.
- Root redirect and 404 boundary: captured at desktop/mobile.
- OpenAPI: **60 paths / 63 HTTP operations**, plus `WS /api/v1/ws/ws/{client_id}`.
- Empty-state desktop/mobile baseline: **44**.
- Seeded/historical desktop/mobile baseline: **44**.
- Final internal-scroll sections: **572 screenshots** (13 positions × 22 routes × 2 viewports).
- Interaction screenshots: **39**.
- Total screenshots: **732** under `evidence/screenshots/`.
- Page reports: **22/22** under `pages/`.
- Synthetic portfolio: five canonical positions across INR/USD; temporary import/add rows removed.
- CRUD, duplicate/malformed/negative validation, currency switch, CSV import/rejection, controls, simulations, settings, controlled failures, and WebSocket runtime checks captured.
- Axe: 65/110 applicable captures, 148 rule-occurrence records, 11 unique rule IDs.
- Direct API capture: **79/79 2xx**, no HTTP/transport errors.
- Independent replay: core **253 checks**; advanced **248 checks**.
- Financial verdict ledger: **535 non-deduplicated check events** with explicit labels in `evidence/calculations/outputs/financial-verdict-ledger.md`.

## Confirmed high-priority findings

1. **P1:** USD view discards native/base provenance and labels mixed-native row values as dollars.
2. **P1:** AAPL is returned as `$4.89` versus same-date history/independent observations near `$336`.
3. **P1:** Dashboard subtracts mixed-native cost from converted current value (`+₹190,377.31 / +320.23%` observed versus ~`+₹5,234.56 / +2.14%` same-current-FX reference).
4. **P1:** Dashboard's undocumented diversification heuristic displays `18.7%` versus ~`50.5%` concentration arithmetic.
5. **P1/P2:** Add Position submits AAPL as `region: IN`; measured liquidity also mixes native currencies.
6. **P1/P2:** EGARCH exposes flat fallback values where independent fits are non-flat.
7. **P2:** Empty portfolio displays false safety/diversification verdicts instead of unavailable.
8. **P2:** Stale shell state, duplicate stress/analytics requests, and unmounted frontend WebSocket integration.
9. **P2/P3:** Broad axe violations, mobile clipping/sticky-header obstruction, truncation, and contrast issues.

See `final-summary.md`, `frontend-bugs.md`, `backend-bugs.md`, `financial-reconciliation.md`, and `ux-improvements.md`.

## Evidence map

- Environment/integrity: `environment.md`, `evidence/runtime/final-isolated-state.json`, `evidence/runtime/final-integrity.json`.
- Routes/APIs: `route-inventory.md`.
- Screenshots: `evidence/screenshots/`.
- Console/network/page text: `evidence/network/`.
- Raw API payloads: `evidence/network/api-final/`.
- Independent calculations: `evidence/calculations/`.
- Page reports: `pages/`.
- WebSocket runtime: `evidence/runtime/websocket-audit.json` and `evidence/calculations/outputs/websocket-audit.md`.
- Completion snapshot: `evidence/runtime/audit-completion.json` (732 screenshots, 22 reports, zero Chrome processes/listeners).

## Completion statement

The audit is complete with explicit `UNVERIFIABLE` and `NOT TESTED` items documented in the financial ledger and page reports. Audit-only listeners on ports `3001` and `8001` were stopped. The pre-existing `3000/8000` services were not stopped. Agent-browser Chrome process count is zero.
