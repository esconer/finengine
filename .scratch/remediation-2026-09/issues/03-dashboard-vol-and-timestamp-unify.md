# 03 — Dashboard vol N/A + "Last updated" unification

Status: closed (2026-09-07, verified: N/A+caption kept — no full-history vol in summary; store timestamp; vitest green)

## Problem (verified 2026-09-07)

- `dashboard/page.tsx:313`: Annual Volatility card renders `N/A` via
  `summary.realized_volatility` (backend `analytics.py:1105`
  `apply_annualization_gate` on the young holding window).
- `dashboard/page.tsx:274-276` shows `summary.last_updated.toLocaleTimeString()`
  while `Header.tsx:102` uses store `lastUpdated` (`Never`/`Just now`,
  `Header.tsx:45,52`, `store.ts:259-261`) — per-page inconsistency.

## Fix

- Vol: check the summary response (read-only) for any full-history/instrument
  vol field — if present, display it with a "full-history" caption (same
  two-window language as realized-risk); else keep `N/A` + one-line caption
  naming model + window (no fabricated numbers, AGENTS.md invariant).
- Timestamp: switch the dashboard header to the store `lastUpdated`
  (`updateLastUpdated()` on fetch), matching other pages. No `store.ts` changes.
