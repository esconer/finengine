# 05 — Add `source` to the `stock_timeseries` natural key

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: 04
Repo: `backend/`
Severity: **HIGH**

## What

The cache's natural key is `UniqueConstraint("ticker", "date")` (`models/database.py:104`).
There is no source dimension, so a bfinance row and a yfinance row for the same `(ticker, date)`
collide and the last writer wins.

```python
# data_service.py:1686-1698
.on_conflict_do_update(index_elements=["ticker", "date"])
```

Only the Alpha Vantage path has a guard (`:1659-1682`).

## Why

The two vendors are **not adjustment-equivalent**, and nothing verifies it. Both are called with
`auto_adjust=False` (`:1232-1242`) and `Adj Close` becomes the single price column for all
analytics. If a vendor disagrees on adjustment — or on a restated close — the winning row depends
on **which tier happened to respond last**, not on which is correct.

The result is a **discontinuity at the seam** in every return series: a single day where the
series jumps because the cache was repopulated by a different vendor. That discontinuity then
propagates into realized vol, GARCH fits, EVT thresholds, cointegration spreads, and drawdowns.

Today this is invisible because the app only ever stores one vendor's row. The moment a fallback
occurs mid-window, the seam appears.

## Change

```python
UniqueConstraint("ticker", "date", "source_used", name="uq_stock_timeseries_ticker_date_source")
```

- Reads specify which source to prefer, or take the most recent.
- Add an explicit source-preference-aware read order rather than relying on insertion order.
- A migration must be reversible. **Keep the old unique index name** in the migration so the
  downgrade is mechanical.
- The Alpha Vantage special-case guard at `:1659-1682` can then be removed — the key handles it.

## Proof of done

- [ ] A bfinance row and a yfinance row for the same `(ticker, date)` can coexist. A test writes
      both and confirms neither mutates the other.
- [ ] A read with an explicit source preference returns that source's row. A read with no
      preference returns the configured primary's row, deterministically.
- [ ] The read order is explicit in code, not emergent from insertion order.
- [ ] The migration is reversible and the reversal is tested.
- [ ] The Alpha Vantage guard special case is deleted, with a test confirming AV rows are now
      handled by the same path.
- [ ] `data_service.py:1652` — `int(row["volume"])` truncates a fractional vendor volume. Fixed
      while in this area, since a truncated volume is a silent data corruption of the same class.
- [ ] Cache-hit accounting distinguishes which source served the hit, so issue 08's `fetch_logs`
      work has the data it needs.

## Notes

This is a schema migration. It should land with or immediately after issue 04, before the refetch
in issue 02 — otherwise the refetch populates a table that is about to change shape.

Refs: `../spec.md`, `app/models/database.py:104`, `app/services/data_service.py:1652,1659-1682,1686-1698`
