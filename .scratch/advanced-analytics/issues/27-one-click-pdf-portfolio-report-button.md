# 27 — One-Click PDF Portfolio Report Header Trigger

Status: ready-for-agent
Type: feature
Blocked by: 19

## What
Add a dedicated "Export PDF Tear-Sheet" button in the global dashboard header and portfolio summary page:
- Bundles current portfolio summary, holdings weights, tear-sheet performance, market regime state, liquidity limits, and Monte Carlo probability.
- Triggers client-side multi-page PDF generation via `ExportService` and `jsPDF`.
- Applies dark/light aware clean styling with Daisy Risk Engine branded headers and timestamp disclaimers.

## Why
Enables one-click physical or PDF archiving for portfolio reviews.

## Proof of done
- [ ] Clicking the header export button downloads a formatted multi-page PDF in under 3 seconds.
