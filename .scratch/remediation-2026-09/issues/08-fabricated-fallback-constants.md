# 08 — Fabricated fallback constants served/rendered as real data

Status: closed (2026-09-07, verified: endpoint nulls + 5 pages N/A-aware, 383 pytest + 81 vitest green)

## Problem (verified 2026-09-07 by code scan; same class as the P0 β=+1.000 bug)

Plausible-looking hardcoded statistics are served or rendered where data is
missing, indistinguishable from real measurements:

Backend (`backend/app/api/analytics.py`, all carry or lack honest flags):
- `forecast_volatility: 0.22` / `var -0.028` / `cvar -0.041` / `CI [0.18,0.26]`
  in forecast error branches (:441-453, :463-475) — dashboard renders the
  0.22 via `dashboard/page.tsx:443` (`|| null` doesn't catch it).
- Summary happy path: `forecast_volatility: 0.22` (:1094),
  `liquidity_score: 7.8` (:1099) — no error key at all.
- Per-ticker forecast exception: `volatility_forecast: 0.25` with
  `is_limited_history: False, data_points: 0` (:533-541).
- `forecast_result.get("volatility_forecast", 0.22)` (:547) and siblings.

Frontend (render fake values when API is null):
- `factor-exposure`: `r_squared ?? 0.679`, `market ?? 1.083`, `alpha ?? 0.0016`
  (:482-488); per-position `market ?? 1.0` (:364, :410, :461).
- `forecast-risk`: projection curves `|| 0.20 / -0.035 / -0.045` (:350-352);
  positions `?? 0.20` (:413); `error` field (:334) never rendered as banner.
- `volatility-sizing`: per-ticker `?? 0.20` (:283).
- `risk-studio`: `(q.realized * 100 || 18.08)` (:291);
  `|| 0.382` / `|| 0.158` correlation fallbacks (:631-654).
- `concentration`: largest holding `|| 0.139` (:876).

Out of scope (documented residuals, verified 2026-09-07):
- Engine-internal `0.22` defaults in `analytics_engine.py`
  (`forecast_volatility` insufficient-data path, pinned by
  `test_analytics_engine.py:107`) — endpoint nulls + frontend N/A make them
  unreachable in the served contract; engine cleanup is a separate ticket.
- `volatility_sizing` engine (`analytics_engine.py:589-623`): per-ticker vol
  defaults/clamps to `0.20` in `[0.05, 1.20]`, `current_price … else 100.0`
  (:641, unreachable — tickers come from price columns),
  `portfolio_volatility = 0.165` (:623, all-zero-weights edge). Engine never
  emits null vol, so served weights always match displayed vols; per-ticker
  provenance flags would need an engine→endpoint→frontend contract change.
- Liquidity (`analytics.py:799-818`) and stress-test (`:839-859`) and
  risk-score (`:971-998`) error branches still serve plausible constants
  (`5.0`/`Medium`, `-0.20`/`-0.17`, `25.0`/`MEDIUM`) — all carry `error` keys;
  frontend error-banner pass is a follow-up (forecast page pattern exists).

## Fix

- Backend: error branches + summary uncomputables → `None` (keep `error` keys);
  per-ticker exception → `volatility_forecast/var_forecast: None`,
  `is_limited_history: True`, warning text. Update the two pinning tests
  (`test_coverage_analytics_extended.py:165`, plus any summary assertions).
- Frontend: null-aware rendering (`N/A` / hide section / skeleton); render the
  `error` banner on forecast-risk; guard the whole projection-curve block on
  non-null base values.

## Ownership

- Backend: main-thread. Frontend (5 page files + tests): delegated agent.
