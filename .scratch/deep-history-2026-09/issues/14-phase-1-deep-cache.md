# 14 — Phase 1 deep OHLCV cache

Status: pending | Pri: P1 | Blocked by: 13

## Change (`backend/app/services/data_service.py`)

- On miss/stale tail, download vendor-max (cap 10y) regardless of requested
  `[start,end]`; upsert the union; serve the requested slice from SQLite.
- L1: ticker-keyed full-depth frame (replace `(ticker,start,end)` keys), slice
  per request; keep 5-min TTL + DB gate + source-order rules untouched.
- Coverage: per-ticker `{cached_start, cached_end, trading_days}` aggregate —
  surfaced in `history_coverage` (no new route unless needed).
- Lazy tail-refresh via the existing 3-day staleness rule; no scheduler.
- Vendor cascade + preference order unchanged; AV stays last.

## Tests (`backend/tests/`)

Union accumulation across windows; slice correctness; single vendor-max
call per ticker (mock-count, no timing); no-duplicate upsert; stale-tail
refresh; unrelated windows share one L1 entry.

## Acceptance

Empty-cache cold fetch for 14 tickers then `daisy.db` census shows ~10y
spans; second request serves from DB (vendor seam untouched).
