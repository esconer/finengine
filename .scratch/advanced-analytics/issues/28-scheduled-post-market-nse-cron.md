# 28 — Scheduled Post-Market NSE Bhavcopy & Institutional Ingestion Cron

Status: deferred
Type: task
Blocked by: 16

## What
Implement a background cron scheduler (FastAPI BackgroundTasks or apscheduler) configured for post-market execution (18:30 IST / 13:00 UTC):
- Fetches daily NSE bhavcopy archive CSV and stores raw file in `data/nse/YYYY-MM-DD/`.
- Ingests delivery quantities and percentages into SQLite `nse_bhavcopy` table.
- Pulls daily FII / DII net cash market flows into `nse_institutional_flows`.
- Idempotent and fails gracefully if markets are closed (weekends, holidays).

## Why
Automates daily microstructure data ingestion without requiring manual UI triggers.

## Proof of done
- [ ] Scheduled runner executes daily at market close, storing archives and populating SQLite without user intervention.
