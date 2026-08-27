# 23 — Portfolio importer (CSV/XLSX upload)

Status: closed
Type: task
Blocked by: —

## What
Users need to load their real book without typing tickers one-by-one.

**Backend** — `POST /api/v1/portfolio/import`
- Accepts multipart file upload (CSV or XLSX; parse server-side with pandas,
  already installed).
- Required column: `ticker`. Optional: `weight`, `quantity`, `buy_price`,
  `custom_name`, `region`.
- Validation rules:
  - missing `ticker` → 400
  - rows failing business rules (weight ∉ (0,1], quantity ≤ 0, buy_price ≤ 0) →
    reported per-row in response, valid rows still imported (partial success),
    unless `?strict=true` → any bad row aborts everything.
  - duplicate ticker inside file → last row wins, noted in response.
  - duplicate vs existing portfolio → skipped (409-style entry in response).
- Missing weight but quantity+buy_price present → derive weight from market value.
- Reuses the existing bulk-add pipeline internals (validate → quote fetch →
  atomic commit) rather than duplicating logic.

**Frontend** — manage page header gets an "Import" button beside "Add Position":
- file picker accepting `.csv,.xlsx` (papaparse/xlsx already dependencies —
  client-side preview table of parsed rows before submit is a stretch goal).
- On success: toast with imported/skipped counts + auto-refresh of the table.

**Flow**: import → Optimize button (`POST /analytics/optimize/run`) on the same page.

## Why
F14 / Phase P0 completion. The optimizer is only useful once the user's actual
book is loaded; manual entry is the current bottleneck.

## Proof of done
- [ ] Upload a 5-row CSV (one deliberately invalid) → 4 imported, 1 error row
      reported by line number.
- [ ] XLSX upload works identically.
- [ ] Imported portfolio immediately optimizable via `/analytics/optimize/run`.
