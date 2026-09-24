# 05 — Synchronize shell state, empty states, and request lifecycles

Status: ready-for-human
Type: bug
Priority: P2
Owner: main thread
Blocked by: 01-currency-contract-and-pnl, 03-canonical-diversification-and-liquidity

## Problem

Header counts/freshness disagree with page state; empty analytics show false safety verdicts; stress/analytics requests duplicate; frontend WebSocket client is not mounted by product pages.

## Acceptance criteria

- Shared portfolio state drives header count and freshness.
- Empty/unavailable states are honest across dashboard analytics.
- Duplicate in-flight requests are prevented without changing valid response handling.
- WebSocket integration is either mounted with visible lifecycle state or explicitly removed from the product surface.
- Focused frontend tests cover each changed state.

## Evidence

- `.scratch/backend-deep-audit/browser-e2e/frontend-bugs.md`
- `.scratch/backend-deep-audit/browser-e2e/ux-improvements.md`
- `.scratch/backend-deep-audit/browser-e2e/evidence/runtime/websocket-audit.json`

## Comments

Keep this separate from financial arithmetic; do not bundle broad responsive redesign into the patch.

### Progress

- Shared analytics hook and concentration/liquidity pages now coalesce in-flight requests and suppress false verdicts for HTTP-200 unavailable payloads.
- Manage-page snapshots now synchronize the shared portfolio store; successful refreshes stamp the shared freshness clock.
- DashboardLayout mounts a visible WebSocket-backed `RealtimeStatus` indicator; focused lifecycle/store tests pass.
- Existing jsdom warnings remain for Recharts zero-size containers, nested explainer buttons, and `act()` in legacy tests; they do not fail the 181-test frontend gate.
