# 19 — PDF portfolio review report

Status: closed
Type: task
Blocked by: 06, 10, 11

## What
One-click "Portfolio Review" PDF: holdings snapshot, tear-sheet metrics, regime statement,
Monte Carlo goal probability, top risk contributors, India-flow flags. Generate client-side
with jsPDF (`frontend/src/lib/export.ts` already has the dependency) pulling from existing
endpoints — no new backend surface.

## Why
Turns the terminal into a review ritual artifact. Spec §F13 / Phase P6.

## Proof of done
- [ ] Generated PDF contains live numbers matching the dashboard.
