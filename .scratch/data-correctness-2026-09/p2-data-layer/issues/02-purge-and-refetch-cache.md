# 02 — Purge `stock_timeseries` and refetch from real OHLCV

Status: needs-info
Type: task
Phase: 2
Blocked by: 01, Phase 0 issue 02
Repo: `backend/`
Severity: **CRITICAL — the only irreversible step in this spec**

## What

Delete every cached market-data row and rebuild it from real bhavcopy-sourced OHLCV.

```sql
DELETE FROM stock_timeseries;
-- also clear the analytics layer, which was computed on synthetic bars
DELETE FROM analytics_cache;
```

**Never touch `portfolio_positions`** — that is holdings truth, and the app already gets this
right in its own cache-clear path (`data.py:420-427` preserves positions).

Also delete the stale `deep_backfill:{ticker}` `AppSetting` markers, which survive a
`clear_market_data_cache` today because that function deletes 7 tables but not `AppSetting`
(`cache_service.py:498-506`).

## Why

bfinance has been the default Tier-1 vendor and has been fabricating OHLC since it was integrated.
Every cached row sourced from bfinance carries a synthetic Open/High/Low and an unadjusted
`Adj Close`. The cache therefore holds months — possibly a year — of derived metrics that are all
subtly wrong:

- realized vol, VaR, CVaR, Sharpe, Sortino, MDD
- GARCH/EWMA conditional variance forecasts
- EVT-POT tail shape parameters
- copula tail-dependence coefficients
- vol-cone quantile bands
- stress-test volatility scalars
- cointegration spread z-scores and OU half-lives

Purging is cleaner than a provenance column here because the existing rows are not merely
unlabelled — they are wrong, and there is no correct subset to preserve.

## Preconditions

1. **A verified file-level backup of `daisy.db` exists.** Phase 0 issue 02 produces it. This step
   is irreversible.
2. Phase 1 issue 03 (real OHLCV) has landed. Otherwise the refetch just re-fabricates.
3. Phase 2 issue 01 (the `attrs` guard) has landed, so any regression is caught rather than
   silently re-cached.

## Proof of done

- [ ] A verified backup file exists and its path is recorded in this ticket's `## Comments`.
- [ ] A restore has been **tested** — the backup was opened and a row count confirmed. An
      untested backup is not a backup.
- [ ] `stock_timeseries` and `analytics_cache` are empty.
- [ ] `portfolio_positions` row count is **unchanged** and verified explicitly.
- [ ] `deep_backfill:*` markers are gone from `app_settings`.
- [ ] A full backfill runs and the resulting row count, ticker count, and date range are recorded.
- [ ] **No row carries a synthetic-OHLC marker.** Assert this directly, do not infer it.
- [ ] A spot-check of 3 tickers against yfinance matches O/H/L/C within 0.01%.
- [ ] Splits and dividends in the refetched data come from the real corporate-action source
      (Phase 1 issue 05), not the equity-capital heuristic.
- [ ] Every analytics page renders from the refetched data with no `data_status` regression.
- [ ] The purge+refetch is wrapped in a script or documented command that can be re-run, since a
      future bfinance data correction will need the same operation.

## Notes

Do this **with the app stopped**. A purge racing an in-flight request is exactly the failure mode
described in Phase 2 issue 05.

The backfill cost is bounded by the Phase 0 issue 02 row count. If that number is very large,
Phase 2 issue 05's lazy-refetch-with-provenance approach is the alternative — but the locked
decision is bulk purge.

Refs: `../spec.md`, `app/services/data_service.py`, `app/services/cache_service.py:498-506`, `app/api/data.py:420-427`, Phase 0 issue 02
