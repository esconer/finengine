# 24 — Portfolio CSV/XLSX Drag-and-Drop Importer UI

Status: ready-for-agent
Type: feature
Blocked by: —

## What
Add a drag-and-drop file upload dropzone component on `/portfolio/manage` with preset parser templates:
- Zerodha Kite tradebook / holdings CSV
- Groww portfolio statement XLSX
- AngelOne / Upstox holdings CSV
- Generic (`ticker, quantity, buy_price, weight`) template

Parsed rows preview in a modal table before submitting atomically to `POST /api/v1/portfolio/bulk_add`.

## Why
Reduces friction for users onboarding their real portfolios without manual data entry.

## Proof of done
- [ ] Dropping a Zerodha / Groww export CSV parses all tickers and pre-fills the bulk add modal cleanly.
