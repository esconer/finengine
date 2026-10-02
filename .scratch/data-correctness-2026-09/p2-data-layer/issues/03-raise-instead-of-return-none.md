# 03 — `fetch_historical_data` must raise, not return `None`

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: —
Repo: `backend/`
Severity: **CRITICAL**

## What

`data_service.py:661-837`. Every structurally-invalid OHLCV row is quarantined by
`_sanitize_timeseries_data` (`:1577-1608`) and the frame is rejected at `:696-698` with
`ProviderInvalidInputError`.

The terminal dispatch at `:823-837` handles only `ProviderUnavailableError` and
`UnknownTickerError`. A `ProviderInvalidInputError`-only outcome falls through to a bare
`return None` at `:838`.

## Why

The `return None` becomes an HTTP 404 at `data.py:523-527`:
```python
if df is None or df.empty:
    raise HTTPException(404, f"No data found for ticker {canonical}")
```

And `_fetch_price_series_dict` (`analytics.py:554-562`) simply omits the ticker.

**A vendor that returns structurally bad rows — zero prices, `high < open`, or a column rename
that makes `pd.to_numeric` coerce everything to NaN — produces "ticker not found" for a ticker
that exists and traded yesterday.**

The only persisted evidence is a `failed` fetch_log row, and that row is **mislabeled
`source_used="alphavantage"`** regardless of which tier actually failed (see issue 08).

## The three distinct outcomes

Currently conflated:

| Situation | Correct response | Current |
|---|---|---|
| Vendor unreachable / network failure | `ProviderUnavailableError` → 503 | correct |
| Ticker genuinely does not exist | `UnknownTickerError` → 404 | correct |
| Vendor returned data that is structurally invalid | **A distinct provider error** — the vendor is broken, not the ticker | bare `return None` → 404 |

The third case is a **vendor bug being reported as a user error.**

## Proof of done

- [ ] `ProviderInvalidInputError` is handled in the terminal dispatch and **raised**, not fallen
      through.
- [ ] It maps to a distinct HTTP status from `UnknownTickerError` — 502 or 503, not 404. The
      response body names the vendor.
- [ ] A test forces a structurally-invalid frame (zero prices; `high < open`; all-NaN after
      coercion) and asserts a provider error, not a 404.
- [ ] A test forces a genuinely nonexistent ticker and asserts 404 still works.
- [ ] A test forces a network failure and asserts 503 still works.
- [ ] All three cases are distinguishable in the response body and in `fetch_logs`.
- [ ] `_fetch_price_series_dict` handles the new error type — currently it catches bare
      `Exception` and returns `(ticker, None)`, which means a vendor bug still silently drops a
      ticker from analytics universes. It should distinguish "no data for this ticker" from
      "the vendor is broken".
- [ ] The `*_basis` / `methodology` provenance fields already in the codebase are extended to
      name the failure mode.

## Notes

The downstream consequence matters: the `except ProviderError -> _raise_provider_http_error`
clauses at `analytics.py:3617,3864,4289,4612,7375,7475` are currently **unreachable for vendor
failures**, because `_fetch_price_series_dict` has already swallowed the error. And
`/realized-risk` (`:3024`), `/forecast-risk` (`:3257`), `/factor-exposure` (`:3512`),
`/stress-test` (`:3942`) and `/tear-sheet` (`:5683`) have **no** `ProviderError` clause at all, so
a failure that did escape would be a 500.

Refs: `../spec.md`, `app/services/data_service.py:661-837,838,1577-1608`, `app/api/data.py:523-527`, `app/api/analytics.py:554-562`
