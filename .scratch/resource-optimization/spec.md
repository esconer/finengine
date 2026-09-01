# Spec: Memory & Resource Optimization (Frontend & Backend)

## Context
High resource usage was reported where Bun/Next.js dev server consumed >1,000 MB RAM and the FastAPI backend consumed ~30% continuous CPU during idle periods.

## Goals
1. Prevent memory runaway in Next.js development and production runtimes.
2. Eliminate infinite React re-render loops caused by un-memoized object dependencies and per-component notification state.
3. Stop unconstrained backend WebSocket background polling when zero clients are connected.
4. Bound process resource usage and ensure instant idle CPU recovery (~0%).

## Architecture & Design
- **Frontend Real-time Layer**: Centralized pub-sub stores for UI notifications and export jobs, avoiding independent component state re-render cascades. Memoized return objects in `useEnhancedRealTimeAnalytics`.
- **Frontend Server Layer**: Configured `onDemandEntries` with `maxInactiveAge: 15000` and `pagesBufferLength: 2` in `next.config.ts` to actively evict inactive route ASTs/caches from RAM in dev mode.
- **Backend WebSocket Layer**: Bounded `background_updates()` to check `if not manager.active_connections: break` and cleanly cancel `update_task` when the last client disconnects.
