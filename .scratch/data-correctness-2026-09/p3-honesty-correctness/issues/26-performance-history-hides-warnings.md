# 26 — `/performance-history` hides its own warnings by default

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `backend/`
Severity: **HIGH**

## What

`analytics.py:4974-4987`
```python
def _deliver(rows, extra=None, coverage=None):
    if not include_metadata:
        return rows                                    # ← `extra` warnings are DISCARDED
    return _performance_history_envelope(rows, ..., warnings=extra, ...)
```

`include_metadata` **defaults to `False`** (`:4920-4927`).

So at `:4990-4992`, `:5011-5013`, and `:5018-5019`:
```python
if not price_data_dict:
    return _deliver([], extra=["No price data was delivered for the requested window."])
```

…returns a **bare `[]`**. No `error`, no `data_status`, no warning.

## Why

**The default production response for a total vendor failure is HTTP 200 with an empty array.**

**User-visible symptom:** the performance chart renders an empty grid. No toast, no banner, no
explanation. This is the literal "empty chart, no error" case, and it is the **default** path, not
an edge case.

The `/dashboard` main page calls this endpoint, so this is the first thing a user sees when
something is wrong.

The fix is almost free — the warning is already constructed. It is only discarded because the
default omits the envelope.

## Change

- When the delivered set is empty or partial, return the envelope **regardless** of
  `include_metadata`. The metadata flag should control *extra* detail, not whether errors are
  visible.
- Alternatively, make `include_metadata` default to `True` and let callers opt out. The frontend
  already handles the envelope shape on `/dashboard/ai-context` and `/dashboard/india-flows`, so
  the pattern is established.
- Apply the same reasoning to the sibling swallow at `:5139-5140` (currently `logger.debug`).

## Proof of done

- [ ] A total vendor failure returns a non-200, or a 200 carrying an explicit `data_status` and a
      warning naming the failure. **Never a bare `[]`.**
- [ ] The **default** call (no `include_metadata`) behaves correctly. This is the key test — a fix
      that only works when the flag is set does not fix the bug.
- [ ] A partial delivery reports which tickers are missing.
- [ ] The dashboard renders a visible state rather than an empty grid. A component test asserts
      it.
- [ ] The same reasoning is applied at `:4990-4992` and `:5011-5013`.
- [ ] A consumer that genuinely wants the bare array can still request it explicitly, and the
      option is documented.
- [ ] The `india-flows` page's failure semantics are used as the reference implementation — it
      never claims "no flows" unless the component declares full coverage.

## Notes

`/dashboard/india-flows` is the best failure-semantics reference in the codebase. It uses a
deliberate `Promise.all` so a single failed fetch surfaces as a page-level error, and it badges
each row by its own `data_status`. Apply that discipline here.

Refs: `../spec.md`, `backend/app/api/analytics.py:4920-4927,4974-4987,4990-4992,5011-5013,5018-5019,5139-5140`, `frontend/src/app/dashboard/india-flows/page.tsx:103-109,145,147-148,394-405`
