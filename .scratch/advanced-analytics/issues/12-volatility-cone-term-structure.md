# 12 — Volatility cone & term structure

Status: ready-for-agent
Type: task
Blocked by: 05

## What
`GET /api/v1/analytics/vol-cone`: realized vol at 10/21/63/126/252d windows (current + historical
min/max/quartile bands per window) vs current GARCH/EWMA forecast plotted against them.
Frontend: add panel to forecast-risk page — cone chart with today's forecast dot.

## Why
Cheap to build, instantly reads as professional; answers "is vol cheap or rich right now".
Spec §F9 / Phase P3.

## Proof of done
- [ ] Cone renders for real portfolio; forecast dot sits inside historical bands.
