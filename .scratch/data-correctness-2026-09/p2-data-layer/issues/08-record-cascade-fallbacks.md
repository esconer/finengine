# 08 — Record cascade fallbacks in `fetch_logs`

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: 04
Repo: `backend/`
Severity: **HIGH**

## What

The cascade's decisions are structurally unrecordable. Four separate defects.

### a) A fallback can never be flagged as a fallback

`data_service.py:719-721`:
```python
await self.cache.log_fetch_attempt(
    ticker=normalized_ticker, status="success", source_used=actual_source
)
```

`log_fetch_attempt` defaults are `primary_attempt=True, fallback_attempt=False`
(`cache_service.py:366-367`). So when bfinance fails and yfinance succeeds, the row says
`status=success, primary_attempt=True, fallback_attempt=False, source_used=yfinance`.

The `FetchLog` model has **dedicated** `primary_attempt` and `fallback_attempt` columns
(`models/database.py:170-171`). They are never set.

### b) Every failure is mislabeled

`data_service.py:816-822`:
```python
await self.cache.log_fetch_attempt(
    ticker=normalized_ticker, status="failed",
    error_message=errors[-1].safe_message,
    source_used="alphavantage",          # ← always "alphavantage"
)
```

The vendor is hardcoded regardless of which tier actually failed, and only **one** row is written
for the whole cascade.

### c) Per-tier rejections never reach `fetch_logs` at all

Inside `download()` (`:1225-1260`): `accept_vendor_frame` failures go to `logger.info` (`:1251-1253`)
and exceptions to `errors.append` (`:1256-1259`). Neither reaches the table.

### d) `fetch_quote` writes no row for the primary cascade

Only the Alpha Vantage fallback path logs (`:1390-1394`).

Plus: `CompanyDataService.get_fundamentals`, `get_financial_statements`, and `ScreenerService`
never call `log_fetch_attempt` at all.

## Why

Downstream, `CacheService.get_cache_stats` computes `success_rate` from this table
(`cache_service.py:449-457`) and surfaces it at `data.py:331`.

**The operator cannot distinguish "yfinance is down, bfinance is carrying the product" from
"yfinance is fine."** That is the single most important operational question this app's data layer
should be able to answer, and the table designed to answer it cannot.

Issue 12 compounds it: Tier-3 is dead, so "alphavantage" in a failure row is almost always a lie.

## Change

- One `fetch_logs` row **per vendor attempt**, not per cascade.
- `primary_attempt` / `fallback_attempt` set correctly from the tier's position in the resolved
  order.
- `source_used` is the vendor that actually served or actually failed.
- `fetch_quote`, fundamentals, statements, and screens all log.
- A per-ticker aggregated outcome row (or a view) for the existing `success_rate` computation, so
  the stats query does not have to change semantics.
- Log the resolved source order itself, so a log row records which cascade was in effect.

## Proof of done

- [ ] A test forces Tier-1 to fail and Tier-2 to succeed. Two rows exist: Tier-1
      `status=failed, primary_attempt=True`, Tier-2 `status=success, fallback_attempt=True`.
- [ ] A test forces all tiers to fail. Every tier has a row with its own `source_used` and error.
- [ ] No row ever has `source_used="alphavantage"` unless Alpha Vantage was actually attempted.
- [ ] `fetch_quote`, `get_fundamentals`, `get_financial_statements`, and the screener paths all
      produce rows.
- [ ] `success_rate_24h` (issue a) is no longer `0.0%` on a fully-cached healthy system. Today no
      row is written on a cache hit, so `recent_total == 0` and the rate is `0`
      (`cache_service.py:449-457`). Either log cache hits as a distinct status, or compute the rate
      over attempts only and label it as such.
- [ ] The settings page or a health endpoint can answer "which vendor served this ticker" and
      "what is the current per-vendor success rate".
- [ ] `data.py:331`'s `get_cache_stats` response is updated to expose the per-vendor breakdown.

## Notes

This is a prerequisite for issue 12 — you cannot responsibly remove Tier-3 while every failure row
claims Tier-3 was the one that ran.

Refs: `../spec.md`, `app/services/data_service.py:719-721,816-822,1225-1260,1390-1394`, `app/services/cache_service.py:366-367,449-457`, `app/models/database.py:170-171`, `app/api/data.py:331`
