# 06 — Monte-carlo copy drift

Status: closed (2026-09-07, verified: honest copy, vitest green)

## Problem (verified 2026-09-07)

`monte-carlo/page.tsx:195-196` claims "two years of cached closes" but the cache
holds ~174d (`analytics.py:1754` requests `timedelta(days=730)`, served from
available history; `monte_carlo_service.py:35` `MIN_HIST_OBS=60`).

## Fix

Honest copy: "up to two years of cached closes (limited by cache depth)" or
equivalent; if the API response carries an observation count, render it
dynamically. Static-string fix preferred — no backend change.
