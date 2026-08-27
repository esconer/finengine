# QH-14: Memory & CPU Usage Optimization

## Status: Resolved
**Triage**: `ready-for-agent` -> Closed

## Problem Description
- When Next.js dev server starts, Bun/Node.js memory usage climbs to ~1GB.
- During simultaneous quant computations (10+ endpoints calculating GARCH, EWMA, correlations, PCA), CPU usage spikes significantly.

## Root Causes Identified
1. **Unbounded V8 Heap Limits**: On 64-bit Windows, Node/V8 allocates up to 4GB before triggering major garbage collection, accumulating Turbopack ASTs, sourcemap trees, and module caches in memory.
2. **Missing Barrel Import Optimizations**: Large UI icon/chart libraries (`lucide-react`, `recharts`, `date-fns`, `@tanstack/react-table`) were being parsed completely into memory without tree-shaking barrel imports.
3. **Simultaneous Monte Carlo Simulations in GARCH**: `analytics_engine.py` was running a 1,000-path Monte Carlo simulation (`method='simulation', simulations=1000`) for every single position across multiple simultaneous endpoints, creating massive CPU thread spikes.
4. **WebSocket Background Worker Polling**: `websocket.py` background update worker was running heavy DB queries and `AnalyticsEngine` computations every 30s even with 0 connected clients.
5. **Redundant SQLite Hits on Concurrent Mounts**: 10 simultaneous dashboard endpoints were independently loading the exact same timeseries data from SQLite.
6. **Object Identity Re-fetching in React Hooks**: `usePortfolioAnalytics`, `usePerformanceData`, and `useSectorAllocation` used object-reference dependencies (`[positions]`) rather than memoized primitive keys (`tickerKey`).

## Solutions Implemented
1. **Configured V8 Heap Ceiling & Telemetry Disable**:
   - Added `NODE_OPTIONS="--max-old-space-size=512"` and `NEXT_TELEMETRY_DISABLED=1` in `frontend/.env.local`.
2. **Enabled Turbopack Import Optimization**:
   - Added `experimental.optimizePackageImports` in `frontend/next.config.ts` for `lucide-react`, `recharts`, `date-fns`, `@tanstack/react-table`, `@tanstack/react-query`, `clsx`, `tailwind-merge`.
3. **Switched GARCH to Exact Analytical Forecasting**:
   - Updated `_garch_forecast` in `analytics_engine.py` to use `method='analytic'` and `options={'maxiter': 100}` for deterministic $O(1)$ computation instead of 1,000 simulation loops.
4. **Added Idle Gate to WebSocket Background Worker**:
   - `send_analytics_update` and worker cycles in `websocket.py` now bypass heavy processing when `len(manager.active_connections) == 0`.
5. **Added In-Memory TTL Cache for DataService**:
   - Implemented `_in_memory_df_cache` in `DataService` with a 5-minute TTL to return parsed price DataFrames in `<0.001ms` across concurrent endpoint requests.
6. **Memoized Primitive Ticker Keys in Frontend Hooks**:
   - Replaced array-reference dependencies with stringified `tickerKey` in `useAnalytics.ts` to prevent redundant network waterfalls.

## Verification
- Backend tests: `249 / 249 passed`
- Frontend tests: `60 / 60 passed`
- All 11 simultaneous dashboard endpoints complete in under 5 seconds with minimal CPU footprint.
