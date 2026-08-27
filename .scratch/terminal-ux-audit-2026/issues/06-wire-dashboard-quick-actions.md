# Issue 06: Wire Dashboard Quick Action Navigation Buttons

Status: ready-for-agent
Type: bug
Priority: P2
Blocked by: —

## Description
On `/dashboard`, the "Quick Actions" panel has four buttons:
- "Add Position" (Opens add position modal - works)
- "Run Analysis" (Only re-fetches without navigation)
- "Rebalance" (Calls API without navigating to the optimizer page)
- "Stress Test" (Uses `window.location.href` causing full page reload instead of Next.js client router)

## Proposed Fix
Wire Next.js `useRouter` or `<Link>` transitions:
- "Run Analysis" -> routes to `/dashboard/realized-risk`
- "Rebalance" -> routes to `/dashboard/optimize`
- "Stress Test" -> routes to `/dashboard/stress-testing`

## Proof of Done
- [ ] Clicking Quick Action buttons provides instantaneous client-side navigation without full browser reload.
