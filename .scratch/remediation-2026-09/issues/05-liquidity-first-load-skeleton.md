# 05 — Liquidity first-load skeleton

Status: closed (2026-09-07, verified: null-aware score + skeleton, vitest green)

## Problem (verified 2026-09-07)

`liquidity/page.tsx:402,559`: header computes `overall_score||0`, so first load
shows "Overall Score: 0.0/10" while `:603,656` (`!loading&&`) hide the cards/body
with no skeleton import — contradictory blank body under a zero score.

## Fix

- Null-aware score (`overall_score ?? null` → skeleton/`N/A` until loaded, never `0.0`).
- Add a loading skeleton for the body (reuse existing skeleton pattern if one
  exists in the codebase, else minimal pulse blocks — check `LoadingState.tsx` first).
