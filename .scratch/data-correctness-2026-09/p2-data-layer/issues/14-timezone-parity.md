# 14 — Timezone parity on the persisted date column

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: —
Repo: `backend/`
Severity: **MEDIUM**

## What

The write and read paths disagree about timezones.

**Write path** — `_sanitize_timeseries_data` does `pd.to_datetime(..., errors="coerce")` with **no**
utc normalisation (`:1592`), and `_store_timeseries_data` writes `row["date"]` into a naive
`DateTime` column (`:1646`).

**Read path** — `_slice_window`, `_frame_bounds`, and `_get_cached_data` all do `utc=True` +
`tz_localize(None)` (`:361`, `:347`, `:1470`).

## Why

A tz-aware vendor index is persisted **with its offset** into a naive column. Subsequent
`>= bounds.start` comparisons are string-ordered against a mixed format, which is
lexicographically wrong across offset boundaries.

For NSE this is not hypothetical: the IST offset is a fixed `+05:30` with no DST, so a naive
`+05:30` string will not compare correctly against a naive bound computed from a UTC-normalised
timestamp. The failure mode is a silently truncated or over-extended window — which then feeds
every metric computed over that window.

## Change

Pick one canonical form and enforce it at both boundaries:

- **Recommended:** normalise to UTC on write (`utc=True`), store naive UTC, and keep the existing
  read-side `tz_localize(None)`. The read path is already correct and is used by more call sites,
  so aligning the write path to it is lower risk.
- Add a column-level comment or a migration note recording the convention.
- Add an assertion at the ingestion boundary: a datetime with a non-UTC offset is rejected or
  converted, never silently stored.

## Proof of done

- [ ] A round-trip test writes a tz-aware vendor frame and reads it back, asserting identical
      dates and correct window slicing.
- [ ] A frame with a `+05:30` index and one with a UTC index produce the same stored dates for the
      same trading days. This is the actual regression test.
- [ ] Window slicing at a boundary returns the correct rows. A test slices a window whose bound
      falls mid-day in IST.
- [ ] No stored date string carries an offset.
- [ ] The convention is documented on the model and in the ingestion path.
- [ ] An existing vendor fixture that is tz-aware is added to the test suite so this stays covered.

## Notes

Related: `CONTEXT.md` §9.7 warns against `.dropna().ffill().bfill().fillna(0.0)` on multi-asset
frames, and issue 15 addresses the `dropna` part of that family. Read the two together — the
combination of a compressed time axis and a tz mismatch is worse than either alone.

Refs: `../spec.md`, `app/services/data_service.py:347,361,1470,1592,1646`, `CONTEXT.md` §9.7
