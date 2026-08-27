# QH-04 — Structured error envelopes for analytics engine

Status: closed
Type: task
Blocked by: —

## What

Nearly every method in `AnalyticsEngine` wraps its body in `try...except Exception` and
returns `_empty_*()` dictionaries with zeroed data. The API layer returns `200 OK` for both
"computed successfully" and "calculation crashed." Users see plausible-looking zeros instead
of error messages. The frontend's `Promise.allSettled` in `useAnalytics.ts` maps partial
failures to `null` silently — no toast, no banner, no indication.

## Fix

1. **Backend**: Introduce a response envelope: `{"status": "ok"|"partial"|"error", "errors": [...], "data": {...}}`.
   Let specific exceptions (`LinAlgError`, `ConvergenceWarning`, insufficient data) bubble up
   as named failures in the `errors` array rather than silently zeroing out.
2. **Frontend**: Surface partial failures via the existing `NotificationSystem` toasts.

## Why

Silent zeros are worse than errors. A user seeing `VaR: 0.00%` might think their portfolio
is risk-free when in reality the calculation crashed.

## Open question

Breaking change: should we migrate all analytics endpoints at once, or gate behind `/api/v2/`?
Recommend: migrate in-place since this is a single-user app with no external consumers.

## Proof of done
- [ ] Endpoint with insufficient data returns `{"status": "partial", "errors": [...]}`
- [ ] Frontend toast appears when analytics partially fail
- [ ] Full success still returns `{"status": "ok", "data": {...}}`
