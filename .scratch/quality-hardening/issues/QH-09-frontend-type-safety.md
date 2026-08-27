# QH-09 — Frontend type safety pass (api.ts + stores + hooks)

Status: closed
Type: task
Blocked by: —

## What

Pervasive `any` typing defeats TypeScript's value across the frontend data layer:

| Location | Issue |
|---|---|
| `api.ts` — all 20+ API functions | Return `Promise<any>` instead of typed responses |
| `store.ts` — `AnalyticsStore` | `cache: Map<string, any>`, `realTimeData: {any, any, any}` |
| `websocket.ts` — `WebSocketMessage` | `data?: any` with no runtime validation |
| `dashboard/page.tsx` — table columns | `cell: ({ row }: any)` |
| `manage/page.tsx` — transforms | `(pos: any)` |
| `tear-sheet/page.tsx` — monthly returns | `(data.monthly_returns[year] as any)?.[mi + 1]` |
| `types/index.ts` — interfaces | `Record<string, any>` for known backend shapes |

## Fix

1. Add proper return types to every function in `api.ts` using existing `types/index.ts`.
2. Extend `types/index.ts` with interfaces for new analytics endpoints (tear-sheet,
   risk-contribution, optimize, regime, monte-carlo).
3. Replace `any` in stores and hooks with the typed interfaces.
4. Add runtime validation (type guard or zod) on WebSocket message parsing.

## Why

`any` types hide bugs that would be caught at compile time. The tear-sheet monthly returns
`as any` casting is particularly fragile — a backend schema change will silently break the
heatmap with no compile error.

## Proof of done
- [ ] `grep -r "Promise<any>" frontend/src/lib/api.ts` returns 0 matches
- [ ] `tsc --noEmit` passes with no new errors
- [ ] WebSocket messages validated before dispatch
