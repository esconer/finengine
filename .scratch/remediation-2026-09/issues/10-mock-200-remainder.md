# 10 — Mock-200 remainder (P0-6 tail)

Status: closed (2026-09-07, verified: endpoint nulls + N/A rendering + error banners, 418 pytest + 83 vitest green)

## Follow-up (done)

- Risk-score empty branches nulled; `GET /config` reads back persisted
  ttl/enable_cache; benchmark threaded into `/risk-score` factor leg.
- Frontend: stress N/A summary/severity/CSV + error banners; RiskMetricsDisplay
  nullable score; dashboard `?? null`; liquidity N/A fallbacks + error banner.

## Problem (verified 2026-09-07; issue 08 fixed forecast/summary only)

Still serving plausible constants with HTTP 200:
- realized-risk error branches `analytics.py:222-259` (`0.20/-0.032/-0.047` class)
- stress-test branches `:839-862` (`-0.20/-0.17/30`)
- risk-score branches `:1032-1045` (`0.20/0.22/25.0/MEDIUM` class)
- liquidity happy-path fallback `:812` (`overall_score 7.8`)

## Fix (backend)

Null the uncomputables, keep `error` keys (issue-08 pattern). Update pinned
backend tests. Ruff E9+F clean.

## Fix (frontend, main-thread after)

N/A-aware rendering + error banners on realized-risk / stress-test /
risk-score / liquidity pages (forecast-risk pattern from issue 08 exists to copy).
