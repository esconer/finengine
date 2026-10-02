# 01 — Fix the never-emitting delivery-row guard

Status: ready-for-agent
Type: task
Phase: 4
Blocked by: —
Repo: `backend/`
Severity: **HIGH — blocks issue 04**

## What

`india_data_service.py:395`
```python
if len(rows) < 3:
    ...
```

## Why

With this guard, the security-wise delivery reader **can never emit a row** for any input,
including a full trading day of data. So issue 04's producer would write rows that no reader can
ever return.

This is a pre-existing bug in the read path that makes the whole delivery feature untestable. It
should be fixed before the producer exists, not after.

## Change

- Establish what the guard was protecting against. Most likely a partially-fetched or truncated
  upstream payload, or a paginated response that has not finished loading.
- If it is a truncation guard, check for the **shape** of the response (all expected symbols
  present, or a stated total count) rather than a raw row count.
- If it is a minimum-sample guard, three rows is far too aggressive for a per-symbol feed — one
  symbol on one day is one legitimate row.
- Whatever the guard becomes, it must **not** silently return an empty list. A partial day should
  be returned as partial, consistent with the app's `data_status` convention.

## Proof of done

- [ ] A single day's delivery data for a set of symbols returns rows.
- [ ] A test asserts rows come back for a realistic one-day fixture. **This test must fail against
      the current code** — that is the proof the bug was real.
- [ ] The guard's purpose is documented in a comment explaining what it protects against.
- [ ] A genuinely truncated or malformed response is still rejected, and the rejection is
      distinguishable from "no data today".
- [ ] A partial day returns partial results with a status, not an empty list.

## Notes

Check whether the same guard pattern appears in the other readers in this file
(`:302` institutional flows, `:372` shareholding, `:445`). If so, those readers may be silently
empty too.

Refs: `../spec.md`, `backend/app/services/india_data_service.py:29-32,302,372,395,397,445`
