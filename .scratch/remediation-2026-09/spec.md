# Remediation 2026-09 — Confirmed-Issue Fix Batch

Status: completed | Owner: agent | Created: 2026-09-07 | Completed: 2026-09-07

## Verification

- Backend: `uv run --extra dev pytest --no-cov -q` → **383 passed**; `ruff check` clean on all touched files.
- Frontend: `bunx tsc --noEmit` exit 0; `bun run test:run` → **81 passed** (13 files).

## Source

Verification sweep 2026-09-07 (three read-only subagents vs current code):
bug-sweep B1–B9 plan (`.zcode/plans/`), `added_on` contract trace, and the
5 open follow-ups in `.scratch/page-audit-2026-09/audit.md`.

## Findings

B1–B7 + B9 already FIXED in code (verified, no action). Everything below
was confirmed STILL-OPEN with file:line evidence on 2026-09-07.

| # | Ticket | Pri | Problem |
|---|---|---|---|
| 01 | issues/01-delete-portfolio-charts-dead-file.md | P2 | `PortfolioCharts.tsx` still exists (B8 never executed); zero imports |
| 02 | issues/02-added-on-purchase-date-contract.md | P1 | `added_on` output-only: backend ignores it, frontend can't send it — backdating via API impossible |
| 03 | issues/03-dashboard-vol-and-timestamp-unify.md | P2 | Dashboard Ann Vol N/A + `summary.last_updated` vs store `lastUpdated` inconsistency |
| 04 | issues/04-regime-posterior-precision.md | P2 | Posteriors rounded to 1dp server-side (`0.04%` → `0.0%`); saturation unhandled |
| 05 | issues/05-liquidity-first-load-skeleton.md | P2 | `overall_score\|\|0` header + blank body on first load, no skeleton |
| 06 | issues/06-monte-carlo-copy-drift.md | P2 | "two years of cached closes" vs ~174d actual cache |
| 07 | issues/07-screener-persistent-cache.md | P2 | In-memory-only `_cache` (300s TTL); cold run >60s after every restart |
| 08 | issues/08-fabricated-fallback-constants.md | P1 | Plausible-looking hardcoded stats (0.22/0.20/7.8/1.083/…) served or rendered as real data |
| 09 | issues/09-screener-l2-prod-wiring.md | P1 | L2 cache built but routes call `get_screener_service()` bare → dead in prod |

## Ownership (no shared files)

- Builder A (backend): 04 (backend part), 07. Owns `screener_service.py`, `regime_service.py` + backend tests.
- Builder B (frontend): 01, 03, 05, 06. Owns those page files + `Header.tsx` (read) + frontend tests. Must NOT touch `lib/api.ts`, `lib/store.ts`, modals, `types/`, dropzone, manage page.
- Main thread: 02 (cross-cutting: `schemas.py`, `portfolio.py`, `types/`, modals, dropzone, `lib/api.ts` additive only).

## Verification

- Backend: `uv run --extra dev pytest --no-cov -q` green + `ruff check` on touched files.
- Frontend: `bunx tsc --noEmit` + `bun run test:run` green.
