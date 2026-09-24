# 01 — Establish currency provenance and correct mixed-currency P&L

Status: ready-for-human
Type: bug
Priority: P1
Owner: main thread
Blocked by: —

## Problem

Portfolio responses expose native position values alongside a converted envelope total. Frontend aggregation subtracts mixed-native cost from converted current value, and USD rows are formatted as dollars without conversion.

## Acceptance criteria

- Every position value has explicit native/base semantics or an unambiguous equivalent.
- Dashboard and Portfolio Management calculate P&L/cost/current values in one declared base currency.
- USD view never labels unconverted INR values as USD.
- Existing FX provenance and first-position/single-holding invariants remain intact.
- Regression tests cover mixed INR/USD totals, cost, P&L, and USD rendering.

## Confirmed test seams

- Public API: `GET /api/v1/portfolio?currency=INR` and `?currency=USD` with a deterministic mixed-currency fixture.
- Rendered UI: Dashboard and Portfolio Management output using the API response, without asserting private component state.


- `.scratch/backend-deep-audit/browser-e2e/financial-reconciliation.md`
- `.scratch/backend-deep-audit/browser-e2e/frontend-bugs.md`
- `.scratch/backend-deep-audit/browser-e2e/evidence/calculations/outputs/portfolio-reconciliation.json`

## Comments

Claimed by the main thread after the completed browser audit. Read current dirty-tree code before editing; do not overwrite unrelated user changes.

### Progress

- `GET /portfolio` now returns native/base currency fields, per-position FX rate/provenance, and converts cost/current/P&L with one FX snapshot.
- Dashboard and Portfolio Management use `*_base` values for visible monetary values; current-FX labeling is explicit.
- Added mixed INR/USD API and rendered-UI regression coverage; focused backend/frontend tests and TypeScript pass.
- Isolated browser/API verification confirms INR and USD P&L/cost/current values and five-position reconciliation.
