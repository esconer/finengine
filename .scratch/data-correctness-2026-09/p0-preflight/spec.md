# Phase 0 — Pre-flight verification

Status: ready-for-agent
Tickets: 4 | Effort: S each | Gate: **all four answered in writing before Phase 1 is scoped**

## Why this phase exists

Two load-bearing assumptions in the spec are unverified, and both would invalidate downstream
scoping if wrong:

1. The NSE CM bhavcopy **legacy path was discontinued 08-Jul-2024** (NSE Circular 62424). The
   current UDiFF path is presumed to work. If it does not resolve from this host, issue 06 is not
   an S — it is a different design entirely.
2. `stock_timeseries` is assumed to hold months of synthetic bfinance bars. The purge-and-refetch
   decision in issue 02 sizes entirely off how much data is actually there.

A third assumption — that bfinance is installed from PyPI — determines whether Phase 1 ships as
one coordinated change or two sequenced publishes.

## Tickets

| # | Ticket | Answers |
|---|---|---|
| 01 | Verify the NSE CM bhavcopy endpoint | Does the UDiFF URL resolve from this IP? What is the exact header row? |
| 02 | Audit `stock_timeseries` for synthetic contamination | Row count, date range, breakdown by `source_used` |
| 03 | Confirm bhavcopy EOD publish time | Is an 18:30 IST cron (per ticket t28) reading yesterday's file? |
| 04 | Confirm how bfinance is installed in the backend venv | PyPI pin or local path? Determines release sequencing |

## Expected outcome

A short written addendum appended to the master `spec.md` under `## Pre-flight results`, with the
four answers and any resulting change to the Phase 1 / Phase 2 scoping.
