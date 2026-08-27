# QH-12 — Frontend test foundation

Status: closed
Type: task
Blocked by: —

## What

Only `MetricCard.test.tsx` exists (35 tests). **Zero coverage** for:
- All 13 dashboard pages (tear-sheet, risk-contribution, optimize, regime, monte-carlo, etc.)
- All hooks (`useAnalytics`, `useRealTime`, `usePortfolioAnalytics`)
- All stores (`usePortfolioStore`, `useAnalyticsStore`, `useUIStore`)
- Complex components (`AddPositionModalSimple`, `DataTable`, `PortfolioTable`, `Sidebar`)
- API client error handling (`api.ts` interceptors)
- WebSocket client (`websocket.ts`)

## Fix

Build a layered test foundation:

**Layer 1 — Unit tests (no network, no DOM):**
- `api.ts`: mock axios, test error interceptor classifies 422/409/timeout correctly
- `store.ts`: test Zustand store actions in isolation (add/remove/update position state)
- `utils.ts`: test INR formatting, `cn()`, debounce

**Layer 2 — Component tests (render + interaction):**
- `AddPositionModalSimple`: open → fill form → submit → assert API called with correct payload
- `Sidebar`: render → assert all 9+ nav links → click → assert route change
- `DataTable`: render with mock data → assert column headers + row count + sort

**Layer 3 — Page smoke tests (render without crash):**
- Each dashboard page: mock API responses → render → assert no error boundary triggered
- Manage page: render → assert table renders → search filter works

## Why

Frontend ships with zero regression safety. Any refactor or dependency upgrade risks
breaking pages with no automated detection.

## Proof of done
- [ ] ≥ 1 test file per page route under `src/test/`
- [ ] `bun run test:run` passes with ≥ 60 total tests
- [ ] Store actions have unit tests
