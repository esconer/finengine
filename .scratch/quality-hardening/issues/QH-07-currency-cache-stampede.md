# QH-07 — Currency service cache stampede fix

Status: closed
Type: task
Blocked by: —

## What

`currency_service.py` `get_exchange_rate` (~lines 28-55) checks if the 30-minute cache is
valid, and if not, calls `_fetch_exchange_rate` (which spawns a thread to hit yfinance).
Under concurrent load, when the cache expires, multiple requests simultaneously bypass the
cache check and spawn redundant yfinance threads, causing rate-limiting and wasted resources.

## Fix

Add an `asyncio.Lock` around the cache refresh path:

```python
_refresh_lock = asyncio.Lock()

async def get_exchange_rate(self, ...):
    if self._cache_valid():
        return self._cached_rate
    async with self._refresh_lock:
        if self._cache_valid():  # double-check after acquiring lock
            return self._cached_rate
        rate = await self._fetch_exchange_rate(...)
        self._update_cache(rate)
        return rate
```

## Why

Prevents redundant API calls and potential yfinance rate-limiting on cache expiry.

## Proof of done
- [ ] Concurrent requests during cache expiry result in exactly 1 yfinance call
- [ ] Test: 10 concurrent `get_exchange_rate` calls → single fetch
