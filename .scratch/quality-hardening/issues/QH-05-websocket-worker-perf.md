# QH-05 — WebSocket background worker performance

Status: closed
Type: task
Blocked by: —

## What

The 30-second WebSocket background worker has two critical performance issues:

1. **Unbounded timeseries query** (`send_analytics_update`, ~line 144): Fetches the ENTIRE
   `stock_timeseries` table for all portfolio tickers with no date filter. For a modest
   portfolio with a few years of data, this loads tens of thousands of rows into memory
   every 30 seconds, causing memory bloat and CPU spikes.

2. **N+1 query pattern** (`send_market_data_update`, ~line 191): Loops over each position
   sequentially, executing a separate `SELECT ... LIMIT 2` query per position to get the
   latest 2 prices. For N positions, this is N database queries every 30 seconds.

## Fix

1. Add `WHERE date >= (NOW - 252 trading days)` filter on the timeseries query.
2. Batch the market data query: single SQL with `ROW_NUMBER() OVER (PARTITION BY ticker
   ORDER BY date DESC)` or equivalent, filtered to top 2 per ticker.

## Why

Memory leak in long-running deployment. The unbounded query grows linearly with history
and will eventually OOM the backend process.

## Proof of done
- [ ] `send_analytics_update` query includes date filter
- [ ] `send_market_data_update` uses single batched query
- [ ] Memory usage stable over 10-minute WebSocket session
