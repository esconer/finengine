# 07 — Real retry backoff

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: —
Repo: `backend/`
Severity: **HIGH**

## What

`data_service.py:661-674` and `:751-752`:
```python
max_retries = 3
for attempt in range(max_retries):
    ...
    if raw is None or raw.empty:
        if attempt < max_retries - 1:
            await asyncio.sleep(0)      # yields, does NOT delay
        continue
```

`asyncio.sleep(0)` yields control to the event loop. It is not a backoff.

## Why

A single fetch issues **3 attempts × 2 tiers = 6 vendor calls with no wall-clock delay**, all inside
`asyncio.wait_for(..., timeout=self.yfinance_timeout)` (`:1263-1264`, `yfinance_timeout=30` from
`config.py:49`).

With `_fetch_price_series_dict`'s `Semaphore(5)` (`analytics.py:549`), a 5-ticker request can
issue up to **30 vendor calls in a burst** and block for minutes.

So a yfinance rate limit gets amplified 3× by the very retry loop meant to absorb it. If the
vendor is rate-limiting because it is already under pressure, this makes it worse and guarantees
the retries also fail.

There is precedent for doing it right in the same codebase: `company_data_service._yf_retry:45-60`
does real exponential backoff. The two paths are simply inconsistent.

## Change

- Exponential backoff with jitter, capped.
- The retry budget must be a **total** time budget, not a per-attempt timeout. A request should
  not be able to occupy a worker for `3 × 30s`.
- Do not retry a non-retryable error. `ProviderInvalidInputError` and `UnknownTickerError` should
  fail immediately (see issue 03) — retrying them just burns quota.
- Do retry `ProviderRateLimitError` and `ProviderUnavailableError`, honouring any `Retry-After`
  the vendor supplies.
- Extract one shared retry helper used by both `data_service` and `company_data_service`, so the
  policy lives in one place.

## Proof of done

- [ ] Backoff delays are real and increasing, with a documented cap. A test with a mocked clock
      asserts the delay sequence.
- [ ] Jitter is present, so concurrent workers do not resynchronise on each retry.
- [ ] A total time budget bounds the whole cascade, not just each attempt. A test asserts a
      request cannot exceed it.
- [ ] `ProviderInvalidInputError` and `UnknownTickerError` are not retried. A test asserts exactly
      one vendor call.
- [ ] `ProviderRateLimitError` honours `Retry-After` when present.
- [ ] One shared retry helper exists and both `data_service` and `company_data_service` use it.
- [ ] A concurrency test confirms a 5-ticker request does not burst 30 simultaneous vendor calls.
- [ ] The retry and budget constants are named module-level constants with a comment explaining
      the policy, not magic numbers inline.

## Notes

The `Semaphore(5)` at `analytics.py:549` is the other half of this problem. Backoff without
lowering concurrency still allows a burst. Consider whether 5 is the right number once backoff
exists.

Refs: `../spec.md`, `app/services/data_service.py:661-674,751-752,1263-1264`, `app/api/analytics.py:549`, `app/services/company_data_service.py:45-60`, `app/config.py:49`
