# 02 — Audit `stock_timeseries` for synthetic contamination

Status: ready-for-agent
Type: research
Phase: 0
Blocked by: —

## What

Measure what is actually in the SQLite market-data cache, to size the purge-and-refetch in Phase 2
issue 02 and confirm the contamination assumption.

Against `backend/data/daisy.db` (use a **copy**; do not mutate the live database):

```sql
SELECT source_used, COUNT(*) AS rows, MIN(date) AS earliest, MAX(date) AS latest
FROM stock_timeseries
GROUP BY source_used;

SELECT COUNT(DISTINCT ticker) AS tickers, COUNT(*) AS rows FROM stock_timeseries;

SELECT ticker, COUNT(*) AS rows, MIN(date), MAX(date)
FROM stock_timeseries GROUP BY ticker ORDER BY rows DESC LIMIT 20;
```

## Why

bfinance has been the default Tier-1 vendor and has been fabricating OHLC since it was
integrated. Every cached row sourced from bfinance before Phase 1 issue 06 lands carries a
synthetic Open/High/Low and an unadjusted `Adj Close`.

This ticket decides between two migration strategies:

- **Bulk purge + refetch** — one `DELETE`, then a single backfill run. Simple, and the locked
  decision assumes this.
- **Lazy per-ticker refetch with a provenance column** — safer if the volume is small or the
  backfill window is long, but leaves mixed-vintage data in the table.

It also reveals whether Alpha Vantage rows are already present, which bears on Phase 2 issue 12
(Tier-3 is currently dead for every `.NS`/`.BO` ticker).

## Proof of done

- [ ] Row count, distinct ticker count, and per-`source_used` breakdown recorded under
      `## Comments`.
- [ ] Date range per source recorded. Note whether any row predates the portfolio's first
      purchase — irrelevant rows can be dropped rather than refetched.
- [ ] A spot-check of 3 tickers is performed: compare the cached `close` against a live yfinance
      `close` for the same date. Record the per-field discrepancy for `open`/`high`/`low`.
      Expect `close` to match and `open`/`high`/`low` to be off by roughly 0.4–0.6%.
- [ ] Database file size on disk recorded, to estimate the refetch cost.
- [ ] A **file-level backup** of `daisy.db` is taken and its path recorded. Phase 2 issue 02 is
      the only irreversible step in this whole spec and needs a restore point.
- [ ] The chosen migration strategy (bulk vs lazy) is stated explicitly, with the row count that
      justifies it.

## Notes

Read-only against the live database. Copy the file first. Do not run the purge here.

Refs: `../spec.md`, Phase 2 issue 02
