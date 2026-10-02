# 03 — Confirm bhavcopy EOD publish time vs the proposed cron

Status: ready-for-agent
Type: research
Phase: 0
Blocked by: 01

## What

Determine when the NSE CM bhavcopy actually becomes available, and therefore whether the
18:30 IST post-market schedule proposed in ticket `t28` is correct.

## Why

Existing ticket `t28` in `.scratch/advanced-analytics/` specifies a background scheduler at
**18:30 IST** pulling the daily bhavcopy, delivery %, and FII/DII net flows.

Community-observed EOD availability for the CM bhavcopy is **~23:00–01:00 IST**, not 18:30. An
18:30 cron would therefore read *yesterday's* file and silently store stale rows with today's
date — a corruption that is invisible until someone checks.

The three feeds in t28 also have different cadences and should not share one schedule:

| Feed | Availability |
|---|---|
| CM bhavcopy | EOD, ~23:00–01:00 IST |
| Security-wise delivery % | Later than the bhavcopy; separate report |
| FII/DII (`fiidiiTradeReact`) | Intraday, revised same-day, provisional until close |

## Proof of done

- [ ] The actual publish time is established from an authoritative NSE circular or notice, and
      cited under `## Comments`. A community observation is acceptable if labelled as such.
- [ ] A recommended cron time is stated for each of the three feeds, with timezone stated
      explicitly (IST, not the host's local time).
- [ ] Whether the host's timezone is IST is confirmed. If it is not, the scheduler must pin the
      timezone explicitly or the schedule will drift.
- [ ] Whether the existing `t28` ticket needs its stated time corrected is stated explicitly, so
      the change can be made when that ticket is picked up.
- [ ] Behaviour on a non-trading day is specified: skip silently (a holiday produces no file, and
      that absence is itself the signal), versus raising an alert.

## Notes

Read-only research. Do not implement the scheduler here — that is Phase 4 issue 05.

Refs: `../spec.md`, Phase 4 issue 05, `.scratch/advanced-analytics/` ticket `t28`
