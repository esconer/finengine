# 07 — Screener persistent screen cache

Status: closed (2026-09-07, verified: L2 + prod wiring (issue 09), L2 tests green)

## Problem (verified 2026-09-07)

`screener_service.py:47-48,108-111,152`: `_cache: Dict[str, Tuple[float, Dict]]`
is an in-memory class dict (`CACHE_TTL_SECONDS=300`, L1 only). Every backend
restart wipes it, so the first screen recomputes per-stock enrichment (>60s cold).

## Fix

- Add L2 persistence following the cointegration precedent (`cointegration_service.py`
  `_db_cache_keys` / `COINT_DB_TICKER` + `CacheService`/`AnalyticsCache`): namespace
  ticker (e.g. `SCREENER`), metric `screen_{strategy}_{universe-hash}_{date}`, TTL ~24h.
- Preserve the P0-9 universe isolation in the cache key (read the current key
  construction first — do not regress it).
- Keep L1 memory as-is; L2 only on L1 miss; write-through on compute.
- Screening math itself must not change.
- Tests: run screen twice with cleared L1 (fresh instance) → second served from
  DB (assert enrichment not recomputed, e.g. via call-count or timing-independent flag).
