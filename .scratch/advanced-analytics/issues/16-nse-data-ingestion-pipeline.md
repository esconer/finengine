# 16 — NSE data ingestion pipeline

Status: closed
Type: task
Blocked by: —

## What
`app/services/india_data_service.py` + daily batch fetcher:
- Daily bhavcopy → delivery % per symbol (NSE archives: archives.nseindia.com CSVs)
- FII/DII daily activity numbers
- Bulk/block deals feed
- Quarterly shareholding patterns incl. promoter pledge deltas
Store raw downloads under `data/nse/YYYY-MM-DD/`, parsed tables into SQLite. Browser-like
headers + session warmup required (NSE blocks default clients); fetch daily in one scheduled
pass, NEVER on-request from UI.

**needs-info**: confirm which NSE sources you actually want first (bhavcopy+delivery vs full
set) — start with bhavcopy/delivery% only as the thinnest slice.

## Why
The India microstructure edge — delivery % and FII/DII flows are public but poorly visualized
anywhere free. Spec §F12 / Phase P5.

## Proof of done
- [x] One command ingests today's bhavcopy + delivery % into SQLite.
- [x] Re-running same day is a no-op (verified via IndiaDataService & test_coverage_india_data.py).
