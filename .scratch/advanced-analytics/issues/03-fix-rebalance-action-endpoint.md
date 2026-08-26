# 03 — Point dashboard Rebalance at /portfolio/normalize

Status: resolved (2026-08-25) - Rebalance now calls portfolioApi.normalizeWeights(); dead /portfolio/rebalance call deleted.
Type: task
Blocked by: —

## What
`frontend/src/app/dashboard/page.tsx:393` POSTs to `/portfolio/rebalance`, which does not exist.
The backend endpoint is `POST /portfolio/normalize?method=proportional`
(`backend/app/api/portfolio.py:731`). Also switch this call to `portfolioApi.normalizeWeights()`.

## Why
Quick-action button always fails today. One-line fix.

## Proof of done
- [ ] Clicking Rebalance on `/dashboard` succeeds and weights sum to 1.0 afterwards.