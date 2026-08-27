# Issue 01: Wire Explicit /vol-cone and /tails API Endpoints

Status: closed

## Description
`PROJECT.md` (Milestone 1 contract) defines:
- `GET /api/v1/analytics/vol-cone?tickers={tickers}&lookback_days=756` -> `VolConeResponse`
- `GET /api/v1/analytics/tails?tickers={tickers}&lookback_days=756` -> `TailRiskResponse`

While `VolatilityService` and `TailRiskService` are implemented in `app/services/`, mounting the explicit routes in `app/api/analytics.py` will guarantee full API contract compliance for external consumers and automated test clients.

## Proposed Fix
1. Add `@router.get("/vol-cone", response_model=VolConeResponse)` to `backend/app/api/analytics.py`.
2. Add `@router.get("/tails", response_model=TailRiskResponse)` to `backend/app/api/analytics.py`.
3. Add corresponding endpoint tests.
