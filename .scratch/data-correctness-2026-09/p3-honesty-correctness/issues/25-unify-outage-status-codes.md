# 25 — One vendor outage produces six different status codes

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: Phase 2 issue 03
Repo: `backend/`
Severity: **MEDIUM**

## What

`_build_wide_returns` raises a bare `ValueError` for "no price data"
(`analytics.py:5288,5303,5321,5325`). Routes map that to whatever their except clause happens to
say:

| Route | Line | Status |
|---|---|---|
| tear-sheet | 5681-5682 | **404** |
| vol-cone | 7505-7506 | **400** |
| correlation-stability | 6656-6657 | **404** |
| backtest | 6221-6222 | **422** |
| risk-contribution | 5956 | **500** |
| optimize/run | 6180 | **500** |

## Why

A total bfinance + yfinance outage shows the user *"Requested resource not found"* on one page and
an unhandled server error on another. Both are wrong: the resource exists, the upstream is down.

The user cannot act on either message, and an operator reading logs sees six different failure
signatures for one root cause.

## Change

- `_build_wide_returns` raises a typed `ProviderError` (specifically `ProviderUnavailableError`),
  not a bare `ValueError`.
- A shared exception handler maps `ProviderError` to a **single** status code with a consistent
  body, rather than each route choosing.
- Audit every `raise ValueError` / `HTTPException` in `analytics.py` that is triggered by missing
  vendor data rather than a malformed request, and convert it.

There is already a helper for this — `_raise_provider_http_error` — used at
`analytics.py:3617,3864,4289,4612,7375,7475`. Route the new errors through it. Note that those
clauses are currently **unreachable for vendor failures** because
`_fetch_price_series_dict` (`analytics.py:554-562`) swallows the error first — see Phase 2
issue 03. Fix that first.

## Proof of done

- [ ] A total vendor outage returns the **same** status code from all six routes.
- [ ] That status code is a provider error (502/503), not 400, 404, 422, or 500.
- [ ] A genuinely missing or malformed **request** still returns 400/404/422 as appropriate. The
      distinction between "your request is wrong" and "the upstream is unavailable" must survive.
- [ ] The response body names the vendor and the failure mode consistently across routes.
- [ ] The `_raise_provider_http_error` clauses at `3617,3864,4289,4612,7375,7475` are now
      **reachable**, and a test proves a vendor failure reaches them.
- [ ] A test asserts all six routes return an identical status for the same simulated outage.
- [ ] Every route has a `ProviderError` clause. `/realized-risk` (`:3024`), `/forecast-risk`
      (`:3257`), `/factor-exposure` (`:3512`), `/stress-test` (`:3942`), and `/tear-sheet` (`:5683`)
      currently have **none**, so a failure that escaped would be a 500.

## Notes

Do this after Phase 2 issue 03, which is what makes the provider errors reachable in the first
place. Together they turn "six different wrong answers to one question" into "one right answer".

Refs: `../spec.md`, `backend/app/api/analytics.py:554-562,3024,3257,3512,3617,3864,3942,4289,4612,5288,5303,5321,5325,5681-5682,5956,6180,6221-6222,6656-6657,7375,7475,7505-7506`
