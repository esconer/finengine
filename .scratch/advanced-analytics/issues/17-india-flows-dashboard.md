# 17 — India flows dashboard

Status: closed
Type: task
Blocked by: 16

## What
Route `/india-flows`: FII/DII daily net bars (30d), delivery-% anomaly table for held tickers
(today vs 20d avg, flagged >2σ), bulk/block deals feed filtered to holdings, and (quarterly)
shareholding delta cards with promoter-pledge changes highlighted.

## Why
Makes the ingested NSE data decision-visible: "what is smart money doing in MY names".
Spec §F12 / Phase P5.

## Proof of done
- [x] Page renders from cached NSE tables without live fetches.
- [x] Held-ticker delivery anomalies visibly flagged (verified via /dashboard/india-flows).
