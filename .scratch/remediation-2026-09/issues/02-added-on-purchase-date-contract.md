# 02 — `added_on` purchase-date contract (backend + frontend)

Status: closed (2026-09-07, verified: 4 backend pytest + 3 frontend vitest, suites green)

## Problem (verified 2026-09-07)

`added_on` is output-only end to end. Consequence: every position's holding
start equals its import timestamp, so backdated buys get a truncated
holding window (`holding_window` masks to `max(effective_starts)`, only
partially repaired backwards by `implied_start_from_price`, never forward).

- Backend: `schemas.py:11-18` (`PortfolioPositionBase`), `:45-47` (Create),
  `:50-55` (Update), `:274-277` (bulk) accept no date; `portfolio.py:150-156`
  (add), `:269-274` (bulk), `:604-611` (update) never pass it — the
  `PortfolioPosition` constructor calls (:215-228, :378-391) omit it, so the
  DB column (`models/database.py:29`, `server_default=func.now()`) always
  stamps import time. Only `schemas.py:70` exposes it (response-only).
  Extra JSON keys are silently ignored (no `extra=forbid`).
- Frontend: `types/index.ts:156-175` request types lack it; `AddPositionModalSimple`
  (:22-65, :187-284) and `EditPositionModal` (:22-85, :184-270) render
  ticker/qty/price/weight/name only; `lib/api.ts:139-171` sends no date;
  `PortfolioDropzone` (:7-13, :54-62) drops any date column on CSV import
  (while export `portfolio.py:766-784` emits `added_on` — asymmetric).
- Holding derivation reads the DB row directly (`holdings.py`, `resolve_holdings`
  at `analytics.py:1275`), so once the API accepts + stores the date, all
  analytics follow with no further changes.

## Fix

1. Backend `schemas.py`: `added_on?: date` on Base + Update (create inherits).
   Validate `<= today`, else 400. Pass through in add / bulk-add / update.
2. Frontend `types/index.ts`: `added_on?: string` (ISO `YYYY-MM-DD`) on create/update/bulk types.
3. `AddPositionModalSimple` + `EditPositionModal`: `<input type="date">`
   (default today for add, row value for edit) + payload.
4. `PortfolioDropzone`: detect `date|purchase_date|added_on` header, map through.
5. Tests: backend add/bulk/update with explicit past `added_on` → persisted +
   holding window honors it; frontend modal test date passthrough.

## Verification

New pytest + vitest; full suites green; ruff + tsc clean.
