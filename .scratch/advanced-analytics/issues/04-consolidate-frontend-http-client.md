# 04 — Consolidate frontend HTTP through lib/api.ts

Status: resolved (2026-08-25) - all raw fetch('http://localhost:8000/...') removed from dashboard + manage pages; routed through lib/api.ts; updatePosition extended with quantity/buy_price.
Type: task
Blocked by: —

## What
Raw `fetch('http://localhost:8000/...')` bypasses the axios client in:
- `frontend/src/app/dashboard/page.tsx:156` (add position)
- `frontend/src/app/portfolio/manage/page.tsx:147,195,222,246` (fetch/add/update/delete)

Replace with `portfolioApi.*` calls. Keep the relative `/api/v1/...` export fetch OR move to
`portfolioApi.exportCSV()` — either works via next.config rewrites, pick one and be consistent.

## Why
Hardcoded host breaks non-local deployment and duplicates error handling already solved in
`lib/api.ts`.

## Proof of done
- [ ] `grep -r "localhost:8000" frontend/src` returns zero hits.
- [ ] Portfolio manage page CRUD works end-to-end against local backend.