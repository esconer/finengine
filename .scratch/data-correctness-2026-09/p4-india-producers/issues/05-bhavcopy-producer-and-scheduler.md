# 05 — CM bhavcopy producer and post-market scheduler

Status: needs-info
Type: task
Phase: 4
Blocked by: Phase 0 issue 03
Repo: `backend/`
Severity: **HIGH**

## What

Write a producer for `nse_bhavcopy` (`models/database.py:186`) and a scheduler to run it.

The table exists, the service has validation and upsert at `india_data_service.py:132`, and
`india_data_service.py:29-32`'s field contract **already matches the NSE CM bhavcopy schema
exactly**. Only the producer is missing.

## Why

This is the EOD foundation for the India market-context layer: trade counts, ₹ turnover, series
membership, and the previous close that issue 10's circuit-band derivation needs.

## Schedule — read Phase 0 issue 03 first

Existing ticket `t28` specifies **18:30 IST**. Community-observed CM bhavcopy EOD availability is
**~23:00–01:00 IST**.

An 18:30 cron would read **yesterday's** file and store it with today's date — a corruption that is
invisible until someone checks. Do not implement 18:30.

Phase 0 issue 03 establishes the real time. Also confirm the **host timezone**; if it is not IST,
the scheduler must pin the timezone explicitly or the schedule will drift with DST rules it does
not intend to follow.

## Source

`nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip`

| Property | Value |
|---|---|
| Auth | **None.** Static ZIP, no cookie, no key |
| Cadence | EOD, ~23:00–01:00 IST |
| Columns | `TradDt, SctySrs, TckrSymb, ISIN, OpnPric, HghPric, LwPric, ClsPric, LastPric, PrvsClsgPric, AvgPrcPric, TtlTradgVol, TtlTrfVal, TtlNbOfTxsExctd` |
| Schemas | Two. UDiFF from 08-Jul-2024; legacy before. See Phase 0 issue 01 |

The legacy path was **discontinued 08-Jul-2024** (NSE Circular 62424).

## Change

- A `NSEBhavcopyClient` following bfinance's pacing design, fetching the static ZIP.
- Schedule it after the confirmed EOD time, with the timezone pinned.
- **A non-trading day yields no file.** That absence is the signal — skip silently rather than
  alerting. Do not fabricate an empty row.
- Backfill mode for populating history, with progress reporting and resumability.
- Idempotent upsert by `(symbol, date)`.
- Store `series` (`SctySrs`) — the table should not mix EQ, BE, MF, and other series without
  recording which is which.

## Proof of done

- [ ] A trading day lands rows in `nse_bhavcopy` and the reader returns them. **This round-trip
      does not exist today.**
- [ ] Both schemas parse. A fixture for each is committed, including a pre-2024-08-07 date.
- [ ] A non-trading day produces no row and does not raise.
- [ ] Re-running for the same date is idempotent.
- [ ] Backfill over a multi-month window completes with the correct trading-day count, and is
      resumable after interruption.
- [ ] `series` is stored and queryable. A test asserts EQ and a non-EQ series are distinguishable.
- [ ] `TtlNbOfTxsExctd` and `TtlTrfVal` are populated (feeds issue 09).
- [ ] `PrvsClsgPric` is stored (feeds issue 10).
- [ ] The schedule time matches Phase 0 issue 03, is pinned to a timezone, and survives a host
      timezone change. A test asserts the computed next-run time.
- [ ] The test uses a recorded fixture, not the network.

## Notes

The scheduler should be idempotent and safe to run twice. A partially-completed run on a
yesterday-deployed deploy should be resumable.

`ai_context_india.py` likely consumes this table for a composite component — check and wire it.

Refs: `../spec.md`, `backend/app/models/database.py:186`, `backend/app/services/india_data_service.py:29-32,132`, `backend/app/services/ai_context_india.py`, Phase 0 issue 03, `.scratch/advanced-analytics/` ticket `t28`
