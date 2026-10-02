# 01 — Verify the NSE CM bhavcopy endpoint

Status: ready-for-agent
Type: research
Phase: 0
Blocked by: —

## What

Confirm the current NSE CM bhavcopy download route resolves from this host and capture the exact
CSV header row, for both the current and legacy schemas.

Current (presumed):
```
https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip
```

Legacy (**discontinued 08-Jul-2024**, NSE Circular 62424):
```
https://nsearchives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MON}/cmDDMMYYYYbhav.csv.zip
```

## Why

Phase 1 issue 06 (real OHLCV) is sized **S** on the assumption that a static, cookie-free ZIP
exists and needs only a fetcher plus a dual-schema parser. If the route is unreachable from this
network, or requires a session, the estimate is wrong and the design changes.

This is also the single fix that repairs the most pages at once — every quantitative page in the
app currently computes on fabricated price bars.

## Proof of done

- [ ] One current-format bhavcopy ZIP downloads successfully from this host; the file is a valid
      ZIP containing one CSV.
- [ ] The exact header row is recorded verbatim in a `## Comments` addendum on this file,
      including the units of `TtlTrfVal` and whether `TtlNbOfTxsExctd` is present.
- [ ] One pre-2024-08-07 date is attempted. Whether it resolves or 404s is recorded — this
      determines whether historical backfill before that date is possible at all.
- [ ] The FO variant route is confirmed to exist for Phase 1 issue 19:
      `https://archives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip`
- [ ] A weekend/holiday date is attempted. The expected result is a 404 or an empty file, and this
      is confirmed so the parser can treat it as a non-trading day rather than an error.
- [ ] Whether the host needs a `User-Agent` or any cookie is recorded. (A bare request is expected
      to work; if not, that is a material finding for the parser design.)

## Notes

Do not build the fetcher in this ticket. Read-only verification only. Record findings under
`## Comments`.

Refs: `../spec.md`, Phase 1 issue 06
