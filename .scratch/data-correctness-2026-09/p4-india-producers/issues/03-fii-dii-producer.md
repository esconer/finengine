# 03 — FII/DII daily net flow producer

Status: needs-info
Type: task
Phase: 4
Blocked by: Phase 1 issue 17
Repo: `backend/`
Severity: **HIGH**

## What

Write a producer for `nse_institutional_flows` (`models/database.py:218`).

The table, the reader (`india_data_service.py:302`), the route (`analytics.py:7283`), and the
AI-context composite component (`ai_context_india.py:40`) all exist. **Only the producer is
missing.**

## Why

FII/DII flow is one of the highest-signal Indian market indicators, and it is the FII leg of
`/dashboard/india-flows` — a page that currently renders against an empty table.

It also has a second consumer: `ai_context_india.py` uses it as composite component 1 of 3, so
this unblocks part of the AI-context export too.

## Source

`nseindia.com/api/fiidiiTradeReact` returns JSON with `category`, `date`, `buyValue`, `sellValue`,
`netValue`.

| Property | Value |
|---|---|
| Auth | Session cookie, **no API key** |
| Cadence | Intraday, revised same-day |
| Data quality | Same-day values are **provisional** until close |

bfinance's `fii_dii_activity()` (Phase 1 issue 17) does the fetch and parse. This ticket is the
scheduling, persistence, and provisional-marking.

## Change

- Schedule once daily after close, at the time Phase 0 issue 03 establishes.
- Mark same-day values `provisional`. This matters: an intraday revision means a value read at
  15:30 may differ at 18:00, and the app should say so rather than silently changing history.
- Upsert by `(category, date)` so a same-day re-fetch updates the row and a re-run is idempotent.
- Preserve the fetch's `as_of` so the freshness caption is server-published — the pattern
  `india-flows/page.tsx:75-80` already uses correctly.

## Proof of done

- [ ] A day's rows land in `nse_institutional_flows` and the reader returns them. **This is the
      round-trip test that does not exist today.**
- [ ] Both categories (FII and DII) are stored and distinguishable.
- [ ] Same-day values carry a `provisional` marker. A test asserts it.
- [ ] Re-running the producer for the same date is idempotent — no duplicate rows.
- [ ] A same-day re-fetch **updates** the provisional value rather than inserting a second row.
- [ ] A non-trading day produces no row and does not raise.
- [ ] The route at `analytics.py:7283` returns real values, and the page's existing failure
      semantics are preserved — a missing leg renders as an em-dash, never `0`.
- [ ] A cookie failure is distinguishable from "no flows today", and the page says which.
- [ ] The test uses a recorded fixture, not the network.

## Notes

A session cookie is required. The Akamai posture is per-endpoint, and this endpoint is
cookie-friendly (unlike `/api/quote-equity`, which is not). Reuse the session-management and
pacing design from `screener/client.py:100-121`, and implement non-JSON content-type detection —
Akamai returns an HTML block page rather than a 403 JSON body, so a naive `response.json()` raises
a confusing parse error instead of surfacing the block.

Refs: `../spec.md`, `backend/app/models/database.py:218`, `backend/app/services/india_data_service.py:211,302`, `backend/app/api/analytics.py:7283,7318`, `backend/app/services/ai_context_india.py:40`, Phase 1 issue 17
