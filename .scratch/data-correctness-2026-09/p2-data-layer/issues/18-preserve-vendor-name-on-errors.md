# 18 — Preserve the vendor name on the error path

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: 04
Repo: `backend/`
Severity: **MEDIUM**

## What

`data_service.py:746`:
```python
raise _provider_error(exc, "market data")
```

The provider is hardcoded to the string `"market data"`.

## Why

A yfinance rate limit is therefore recorded and reported as a generic outage. `ProviderRateLimitError`
is raised with `provider="market data"`, so:

- the rate-limit branch at `:184-185` cannot distinguish vendors
- `fetch_logs` (once issue 08 lands) cannot attribute the failure
- the operator cannot tell "yfinance is throttling us" from "yfinance is down"

The acceptance-rejection paths at `:682,691,697,701` **already** do this correctly, using
`provider=actual_source`. So the codebase knows the right pattern and does not apply it
consistently.

## Change

- Thread the actual vendor name through every `_provider_error` call.
- Where the failing vendor is genuinely unknown (e.g. a network failure before a vendor is
  selected), use `None` or `"unknown"` — not a generic label that implies a specific source.
- The `ProviderUnavailableError` / `ProviderRateLimitError` / `ProviderInvalidInputError` /
  `UnknownTickerError` types should carry the vendor as structured data, not a display string.

## Proof of done

- [ ] Every `ProviderError` raised from `data_service.py` carries the actual vendor name, or
      `None` when genuinely unknown.
- [ ] A test forces a yfinance failure and asserts `provider == "yfinance"`.
- [ ] A test forces a bfinance failure and asserts `provider == "bfinance"`.
- [ ] A test forces a network failure before vendor selection and asserts the provider is not a
      misleading label.
- [ ] The `fetch_logs` row (issue 08) carries the same vendor name.
- [ ] The API error response body names the vendor, so the frontend can show it.
- [ ] Grep confirms no remaining hardcoded provider string in an error path.

## Notes

Small, mechanical, and a prerequisite for issue 08's per-vendor statistics to mean anything.

Refs: `../spec.md`, `app/services/data_service.py:184-185,682,691,697,701,746`
