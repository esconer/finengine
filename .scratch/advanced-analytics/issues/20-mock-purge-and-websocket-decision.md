# 20 — Mock purge + WebSocket worker decision

Status: ready-for-agent
Type: task
Blocked by: 06, 09, 17

## What
Final cleanup pass:
- Delete/replace mock websocket broadcasts (`backend/app/api/websocket.py:94-165`) — either wire
  the background worker to REAL portfolio/analytics payloads (fix `GlobalDataService()` missing
  db_session at line 73) or hide live-mode toggle until it's real. Pick one, document in this file.
- Remove fake MetricCard change deltas (`dashboard/page.tsx:259,267,275,283`) — compute real
  day-over-day or drop the arrows.
- Replace mock `usePerformanceData` (`hooks/useAnalytics.ts:99-133`) with a real
  portfolio-timeseries endpoint (reconstruct value history from cached prices × quantity).
- Delete dead code: unused `AddPositionModal` (~700 lines), placeholder `useAutoRefresh` in
  `store.ts`, legacy `PortfolioManagement` chart if unreferenced.

## Why
Zero fake numbers reachable in normal use — the acceptance bar for the whole spec.

## Proof of done
- [ ] `grep -rn "hash(" backend/app/api/websocket.py` → no mock generators left.
- [ ] `grep -rn "Math.random" frontend/src/hooks frontend/src/app` → no fabricated data.
- [ ] Every page renders from real endpoints with an empty→populated DB transition test.
