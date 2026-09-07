# 09 — Screener L2 cache prod wiring

Status: closed (2026-09-07, verified: per-request service with 24h-TLL CacheService on /screens/{strategy})

## Problem (verified 2026-09-07)

Builder A added L2 DB persistence to `ScreenerService` (optional
`cache_service`, fails open to `None`), but all three routes in
`equity_research.py:171,189,204` call `get_screener_service()` bare, and the
module-global singleton caches the first instance — so L2 is dead in prod and
every restart still cold-runs >60s. `CacheService` holds a request-scoped
session, so it must NOT be stuffed into the global singleton (stale-session reuse).

## Fix

In the two screen-run routes (`/screens/{strategy}`, `/screens/custom`):
inject `db` + `CacheService = Depends(get_cache_service)` (same 3-line dep
pattern as `analytics.py:52`), construct a per-request
`ScreenerService(db_session=db, cache_service=CacheService(db, ttl_minutes=SCREENER_DB_TTL_MINUTES))`.
Keep the singleton for the no-DB list route. Verify with the L2 tests +
a route-level test asserting the second identical request recomputes zero times.
