# Route and API Inventory

## Scope summary

- Next App Router: **21 `page.tsx` files** = root redirect + 20 product pages.
- Product navigation: **20 sidebar entries**, exactly matching the 20 rendered product pages.
- HTTP API: **60 unique paths / 63 operations** = 46 GET, 14 POST, 2 PUT, 1 DELETE.
- Additional transport: `WS /api/v1/ws/ws/{client_id}` (not represented in OpenAPI).
- Only 18 of 63 HTTP operations declare an OpenAPI `response_model`; most analytics/data contracts are weakly typed.

## Product route crosswalk

| Route | Main APIs/capabilities | Browser status |
|---|---|---|
| `/` | Redirect to `/dashboard` | Captured |
| `/dashboard` | Portfolio summary; shared analytics; performance/regime/risk contribution; add/export | Empty + seeded captured; final scroll sections in progress |
| `/portfolio/manage` | Portfolio GET, forecast GET, add/bulk-add/update/delete, import | Empty + seeded captured; CRUD evidence captured |
| `/dashboard/realized-risk` | Shared seven-analytics hook, realized risk, performance history | Empty + seeded captured; final sections and direct API/replay evidence captured where applicable |
| `/dashboard/forecast-risk` | EWMA/GARCH/EGARCH, horizon, term/confidence outputs | Empty + seeded captured; final sections and direct API/replay evidence captured where applicable |
| `/dashboard/factor-exposure` | Portfolio + factor regression | Empty + seeded captured; final sections and direct API/replay evidence captured where applicable |
| `/dashboard/stress-testing` | Portfolio + preset/custom stress POSTs | Empty + seeded captured; final sections and direct API/replay evidence captured where applicable |
| `/dashboard/concentration` | Portfolio + concentration analytics | Empty + seeded captured; final sections and direct API/replay evidence captured where applicable |
| `/dashboard/liquidity` | Portfolio + liquidity analytics | Empty + seeded captured; final sections and direct API/replay evidence captured where applicable |
| `/dashboard/volatility-sizing` | Portfolio + sizing; rebalance dry-run/live | Empty + seeded captured; final sections and direct API/replay evidence captured where applicable |
| `/dashboard/tear-sheet` | Tear-sheet GET | Empty + seeded captured; early seeded 404 was history/date-dependent, while historical desktop returned 200 |
| `/dashboard/risk-contribution` | Euler/CVaR contribution GET | Empty + seeded captured; final sections and direct API/replay evidence captured where applicable |
| `/dashboard/risk-studio` | Risk contribution, tail dependence, vol cone, correlation stability | Empty + seeded captured; final sections and direct API/replay evidence captured where applicable |
| `/dashboard/optimize` | HRP/min-vol/max-Sharpe/min-CVaR/Black-Litterman POST | Empty + seeded captured; final sections and direct API/replay evidence captured where applicable |
| `/dashboard/regime` | NIFTY HMM regime GET | Empty + seeded captured; final sections and direct API/replay evidence captured where applicable |
| `/dashboard/monte-carlo` | GBM/Student-t/bootstrap POST | Empty + seeded captured; final sections and direct API/replay evidence captured where applicable |
| `/dashboard/pairs` | Cointegration GET | Empty + seeded captured; final sections and direct API/replay evidence captured where applicable |
| `/dashboard/india-flows` | India flows, delivery anomalies, liquidity limits | Empty + seeded captured; final sections and direct API/replay evidence captured where applicable |
| `/dashboard/equity-research` | Profile, shareholding, concalls, statements, Excel, AI memo/forensic | Empty + seeded captured; final sections and direct API/replay evidence captured where applicable |
| `/dashboard/screener-studio` | Strategy discovery/runs/custom screen, add-to-portfolio | Empty + seeded captured; final sections and direct API/replay evidence captured where applicable |
| `/dashboard/settings` | Data config GET/PUT and cache purge POST | Empty + seeded captured; final sections and direct API/replay evidence captured where applicable |
| Unknown route | Next 404 boundary | Desktop/mobile evidence captured |

## API-only/dormant production capabilities

These endpoints are not called by the rendered production UI and require direct API coverage or a coverage-gap classification:

- `GET /api/v1/portfolio/{ticker}`.
- `POST /api/v1/portfolio/normalize`.
- `GET /api/v1/data/{ticker}`.
- `GET /api/v1/data/quote/{ticker}`.
- `GET /api/v1/data/indicators/{ticker}`.
- `GET /api/v1/data/verified-snapshot/{ticker}`.
- `GET /api/v1/data/fundamentals/{ticker}`.
- `GET /api/v1/data/insider/{ticker}`.
- `POST /api/v1/data/batch`.
- `POST /api/v1/data/validate`.
- `POST /api/v1/data/refresh` (mutating/provider refresh; isolated stack only).
- `POST /api/v1/analytics/backtest`.
- `GET /api/v1/analytics/tails` (alias; UI uses `/tail-dependence`).
- `GET /api/v1/company/{ticker}/custom-ratios`.
- `GET /api/v1/company/{ticker}/ai-dossier`.
- `GET /api/v1/ws/status`.
- `POST /api/v1/ws/broadcast` (test stack only).
- `GET /api/v1/health`, `/health`, `/v1/models`, backend `/`.

## Confirmed route/contract mismatches

1. The prior 18-page audit is stale: Equity Research and Screener Studio are current product pages.
2. Current Settings exposes source selection and cache purge only, not valuation currency, benchmark, or lookback controls described by the old audit.
3. Equity Research exposes AI memo/forensic actions but does not call the available AI-dossier API.
4. Sidebar copy says Optimizer has four strategies; the page/backend expose five including Black-Litterman.
5. Risk Studio uses `/tail-dependence`; `/tails` is a real but unused alias.
6. The header's live-data hook is not visibly mounted by the active notification shell; live-mode wiring requires runtime proof.
7. Direct deep links can depend on persisted Zustand portfolio state even when the backend contains positions.
8. Axios expects `NEXT_PUBLIC_API_URL` to include `/api/v1`; the WebSocket client expects an origin; `NEXT_PUBLIC_WS_URL` is ignored by current source.
9. Frontend wrapper types are not OpenAPI-derived and disagree with several backend payload shapes.
10. `GET /portfolio` and `GET /portfolio/{ticker}` refresh and commit prices; “GET” is not a strict read-only operation.

## Source citations

- Navigation: `frontend/src/components/layout/Sidebar.tsx:43-187`.
- Root redirect: `frontend/src/app/page.tsx:5-9`.
- Dashboard layout: `frontend/src/app/dashboard/layout.tsx:17-25`.
- API registration: `backend/main.py:140-169`.
- Frontend API wrappers: `frontend/src/lib/api.ts:129-550`.
- Page-specific calls: the page files under `frontend/src/app/dashboard/` and `frontend/src/app/portfolio/manage/page.tsx`.
