# 02 — Fix the `nse_bulk_block_deals` column mismatch

Status: ready-for-agent
Type: task
Phase: 4
Blocked by: —
Repo: `backend/`
Severity: **HIGH — a silent insert failure**

## What

`models/database.py:248` declares the column as `close`. The writer in `india_data_service.py`
uses `close_price`.

## Why

A name mismatch between the model and the writer. Depending on the SQLAlchemy configuration this
is either:

- an `INSERT` that references a non-existent column and raises, or
- silently ignored, and the row is written with `close = NULL`

The second case is worse: the insert "succeeds", the row lands, and every downstream consumer of
the deal's close price gets `None` — with no error anywhere. Bulk-deal price versus market close
is the entire analytical point of the feed, so a null close makes the rows useless while appearing
to work.

Either way this is a latent failure that issue 06's producer will hit immediately.

## Change

- Reconcile the name. Pick one (`close_price` is clearer, since the table also has `trade_price`
  and conflating the two is confusing) and update the model, the writer, and any reader.
- Add a check that every declared column is either written or explicitly nullable-with-reason.
  A mapping test that instantiates the writer with a full fixture and asserts no field is
  accidentally dropped catches this whole class.
- Audit the other three India tables for the same mismatch: `nse_bhavcopy`,
  `nse_institutional_flows`, `nse_shareholding_patterns`. Compare each model's column names
  against its writer's dict keys.

## Proof of done

- [ ] A full deal fixture round-trips: write, read back, every field populated. A test asserts
      `close` (or `close_price`) is non-null.
- [ ] A mapping test compares model columns against writer keys for **all four** India tables and
      fails on any unmatched name. This is the durable fix.
- [ ] No `IntegrityError` or silently-dropped field occurs on insert.
- [ ] The audit result for the other three tables is recorded in this ticket's `## Comments`, even
      if they are clean.

## Notes

The `india_data_service.py:29-32` field contract already matches the NSE CM bhavcopy schema
exactly, so `nse_bhavcopy` is probably clean. Verify rather than assume.

Refs: `../spec.md`, `backend/app/models/database.py:186,203-204,218,240-264,248,265`, `backend/app/services/india_data_service.py:29-32,132,211,302,372,445`
