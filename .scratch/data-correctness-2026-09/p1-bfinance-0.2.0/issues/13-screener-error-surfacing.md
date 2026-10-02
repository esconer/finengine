# 13 — Screener error surfacing and retry coverage

Status: ready-for-agent
Type: task
Phase: 1
Blocked by: 01
Repo: `C:\es\coding\bfinance`
Severity: **MEDIUM**

## What

`src/bfinance/screener/client.py:123-185` — the entire resilience layer is untested (0% covered
on those lines), and `:202,209-210` swallows non-200 responses by returning `[]`.

## Why

This is the code that decides whether a rate-limit is surfaced or swallowed. Its coverage is:

| Lines | Behaviour | Coverage |
|---|---|---|
| 149-159 | 429 backoff | **0%** |
| 161-170 | 5xx retry | **0%** |
| 172-181 | network-error retry | **0%** |
| 184 | `RateLimitExceededError` | **0%** |
| 202, 209-210 | `search` returns `[]` on any non-200 — the 403/429 swallowing | **0%** |

A 403 or 429 during a batch screen returns an empty result that is indistinguishable from
"no companies matched". Combined with issue 06's cache poisoning, a soft-block can be cached for
24h and served as truth.

This is also the module the consuming app depends on for its entire Screener Studio feature —
`screener_service.py:83,88,93,98,103,286,340-345`.

## Proof of done

- [ ] A 403 raises a typed error. A 429 raises `RateLimitExceededError` after exhausting backoff.
      A 5xx retries then raises. A connection error retries then raises.
- [ ] None of these return `[]` or an empty DataFrame.
- [ ] Every path in `:123-185` has a test using `responses` or an equivalent HTTP mock. No
      network access required to run them.
- [ ] Backoff delays are asserted (with a mocked clock or a patched `sleep`), not just that a
      retry happened.
- [ ] The 429/5xx retry counts and the backoff ceiling are documented as constants, not magic
      numbers inline.
- [ ] A batch screen that hits a rate limit surfaces the partial result **and** an explicit
      degraded flag, rather than silently returning a short list.
- [ ] `RateLimitExceededError` is exported from the package root so a consumer can catch it
      without importing the private module.

## Notes

Do this after issue 06 — the cache fix depends on the client raising rather than returning
partial data.

Refs: `../spec.md`, `screener/client.py:123-185,202,209-210`, `screens.py`

## Verification correction (2026-09-28)

**Partially satisfied. The retry clause of this ticket is still open** - it was wrongly reported as
done, which was the most damaging error in the first pass, because retry coverage is the point.

**Satisfied:** measured with `max_retries=3` by instrumenting `httpx.AsyncClient.get` and
`asyncio.sleep`. Retried: 429 (`client.py:194`, backoff `(2**attempt)*2.0`, measured 2.76/5.10/9.49),
500-599 (`:206`, `(attempt+1)`), and `TimeoutException`/`NetworkError`/`RemoteProtocolError` (`:218`).
Raise immediately with zero retries: 204, 301, 400, 401, 403, 404, 418. `RateLimitExceededError` is
a verified subclass of `UpstreamServiceError`, and `Retry-After` is honoured, capped at 30s. So
"none of these return `[]`" and the typing requirement are met.

**Not satisfied - the retry layer is still untested for this client:**

    tests/test_upstream_errors.py:82                max_retries=1
    tests/test_screener_market_offline.py:463,485   max_retries=1
    tests/test_screener_offline.py:221              max_retries=1

With `max_retries=1` the loop runs once, hits `continue`, and exits. **No screener test ever
observes a second attempt.** `test_search_5xx_is_an_upstream_error_not_an_empty_result` (`:133`,
503) and `test_rate_limit_keeps_its_own_error_type` (`:140`, 429) are single-shot - the latter also
burns a wasted 3.49s backoff sleep on its only attempt.

The harness records a `calls` list *specifically so retry can be asserted*
(`test_upstream_errors.py:45-64`); it is used only for Ticker-refetch tests (`:188-203`), never for
retry. The instrument exists and is unused for the claim it exists for.

23 offline error tests pass, 16 driving a non-200. Covered: 403 (x11), 429, 503, 200. Not covered:
400, 401, 404, 418, 204, 3xx, 500, 502, 504, 599, 600, network errors.

**The pattern is already established in this repo** - `test_nse_bhavcopy.py:607-649` and
`test_nse_corporate_actions.py:788-815` use `max_retries=2/3` and assert
`match="failed after 2 attempts"`; `test_trendlyne_core.py` uses 2/3 throughout. It is simply
missing for the client this ticket names.

**Addition:** HTTP 600 is outside `500..599`, so it is neither retried nor classified and falls
through to the caller's generic error. Not a real HTTP status, so low impact, but the range is a
magic number.
