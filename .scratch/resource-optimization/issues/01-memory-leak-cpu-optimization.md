# Issue 01: Memory Leak and Continuous CPU Burn Investigation and Fix

Status: resolved
Type: task

## Problem Description
- Task Manager showed `Bun (3)` process group taking >1,041 MB RAM.
- Python backend consumed ~30% CPU continuously on idle.

## Root Causes
1. **Frontend Infinite Re-render Loop**: `useEnhancedRealTimeAnalytics` in `src/hooks/useRealTime.ts` synced `{ ...portfolioData }` to Zustand store inside a `useEffect`. Since `{ ... }` created new references on every render, the effect re-triggered continuously.
2. **Backend WebSocket Runaway Background Loop**: `background_updates()` in `backend/app/api/websocket.py` ran an un-terminated `while True` loop that calculated heavy portfolio risk metrics every 30s regardless of whether any clients were connected.
3. **Next.js Dev Server Unbounded Compilation Cache**: Dev server kept all route trees in memory indefinitely without `onDemandEntries` eviction.

## Changes Made
- `frontend/src/hooks/useRealTime.ts`: Replaced per-component notification/export `useState` with shared pub-sub module stores. Memoized all hook return values with `useMemo`.
- `frontend/src/components/ui/NotificationSystem.tsx`: Added `prevConnectedRef` to trigger connection status notifications only on actual state transitions.
- `frontend/src/lib/websocket.ts`: Added `updateOptions` to `WebSocketClient` and memoized hook callbacks.
- `frontend/next.config.ts`: Added `onDemandEntries: { maxInactiveAge: 15000, pagesBufferLength: 2 }` and heavy libraries to `optimizePackageImports`.
- `frontend/src/lib/utils.ts`: Exported `formatPercent` and `formatIndianRupees`.
- `frontend/src/app/dashboard/screener-studio/page.tsx`: Fixed `PortfolioCreateRequest` parameters.
- `backend/app/api/websocket.py`: Bounded `background_updates()` with active connection checks and task cancellation on disconnect.

## Verification
- `pytest tests/test_websocket.py`: 15/15 passed.
- `bun run build`: 24/24 static pages compiled with 0 errors.
- Python CPU idle: 0.0%.
- Python RAM: ~102 MB.
- Frontend RAM (production): ~24 MB Bun / ~156 MB Node.
