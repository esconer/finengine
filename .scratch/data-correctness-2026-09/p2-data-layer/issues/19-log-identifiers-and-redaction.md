# 19 — Log identifiers and redact upstream text

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: —
Repo: `backend/`
Severity: **MEDIUM**

## What

Two related observability defects.

### a) Vendor failures are unattributable in production logs

These messages carry no ticker, no vendor, and no error type:

```
portfolio.py:1676     "Portfolio price refresh failed"
websocket.py:72,293,348,442,494    "Portfolio update failed"
analytics.py:393      "Realized risk request failed"
analytics.py:3174
data.py:716
```

A production incident log reads "Realized risk request failed" with no way to tell which ticker,
which vendor, or whether it was a 404 or a timeout.

### b) One module logs raw upstream exception text

`ai_dossier_service.py:51,73,91,109`:
```python
logger.warning(f"...{e}")
```

This **contradicts the redaction policy enforced everywhere else** in the codebase:
`cache_service.py:30-33` and `alpha_vantage_service.py:116-123` both scrub upstream text before
logging. Raw upstream exception text can contain URLs, tokens, or internal hostnames.

## Why

Issue 08 makes `fetch_logs` the operational record. But logs remain the primary diagnostic when
something fails in a way that never reaches the table, and right now they say almost nothing.

The redaction inconsistency is a small security gap with a trivial fix, and inconsistency here is
worse than either extreme — a maintainer reading `ai_dossier_service.py` would reasonably assume
raw text is acceptable.

## Change

- Every vendor-related log line names the ticker, the vendor, and the error type. Use lazy `%s`
  formatting, not f-strings, so the cost is only paid when the level is enabled.
- Route all upstream exception text through the existing redaction helper. Extract it if it is
  duplicated; reuse it rather than adding a second implementation.
- Add a lint or test rule preventing raw `{e}` interpolation into a log call for vendor errors.

## Proof of done

- [ ] Every vendor-failure log line includes a ticker and a vendor.
- [ ] No log statement interpolates a raw exception into a message for a vendor error. Grep for
      `f"...{e}"` and `{exc}` in logging calls returns nothing outside the redaction helper.
- [ ] The redaction helper is the single implementation, imported wherever needed.
- [ ] A test feeds an exception containing a URL and a token and asserts neither appears in the
      captured log output.
- [ ] `portfolio.py:1676` names the ticker and the error type.
- [ ] The bfinance-fundamentals outage at `company_data_service.py:211-215` is raised to
      `logger.warning` or above. It is currently `logger.debug`, which produces **no log line at
      all** at the default `log_level=INFO` (`config.py:68`) — so a total bfinance fundamentals
      outage is invisible.

## Notes

The `company_data_service.py:211-215` case is the most important one. `had_outage` is set but only
consulted if *every* tier fails (`:295-296`), so a bfinance outage with a working yfinance
fallback produces a 200, no `fetch_logs` row, and a single `logger.debug` line. That is the
"bfinance is fully down for Indian fundamentals and nothing says so" scenario.

Refs: `../spec.md`, `app/api/portfolio.py:1676`, `app/api/websocket.py:72,293,348,442,494`, `app/api/analytics.py:393,3174`, `app/api/data.py:716`, `app/services/ai_dossier_service.py:51,73,91,109`, `app/services/cache_service.py:30-33`, `app/services/alpha_vantage_service.py:116-123`, `app/services/company_data_service.py:211-215,295-296`, `app/config.py:68`
