# QH-06 — Concurrent batch fetching (data_service + portfolio bulk_add)

Status: closed
Type: task
Blocked by: —

## What

Two hot paths use sequential loops with artificial delays for external API calls:

1. **`data_service.py` `fetch_ohlcv_batch`** (~lines 249-264): Processes tickers in a
   sequential loop with `await asyncio.sleep(0.5)` between each. For 50 tickers, this
   adds 25 seconds of artificial delay on top of network latency.

2. **`portfolio.py` `POST /bulk_add`** (~lines 339-344): Loops through validated positions
   and calls `await data_service.fetch_quote(ticker)` sequentially. A 20-position CSV
   import makes 20 sequential network calls.

## Fix

Replace both with `asyncio.gather()` gated by `asyncio.Semaphore(5)` for controlled
concurrent fetching. This respects yfinance rate limits while being ~10x faster.

```python
sem = asyncio.Semaphore(5)
async def fetch_one(ticker):
    async with sem:
        return await data_service.fetch_quote(ticker)
results = await asyncio.gather(*[fetch_one(t) for t in tickers])
```

## Why

Portfolio import of 20 tickers currently takes 10+ seconds of pure wait time. Concurrent
fetching reduces this to ~2 seconds.

## Proof of done
- [ ] `fetch_ohlcv_batch` uses `asyncio.gather` + semaphore
- [ ] `bulk_add` validates/quotes concurrently
- [ ] Batch of 10 tickers completes in < 5s (vs ~5s+ sequential)
