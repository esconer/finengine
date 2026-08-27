# Page 8: Volatility Sizing Audit & Verification Report

## 1. Page Overview
- **Path**: frontend/src/app/dashboard/volatility-sizing/page.tsx
- **Route**: http://localhost:3000/dashboard/volatility-sizing
- **Backend API**: GET /api/v1/analytics/volatility-sizing

## 2. Live Quantitative & UX Verification
- **Mount Behavior**: fetchPortfolio() extracts active holdings and triggers fetchSizingData() on mount.
- **Top Metric Cards**:
  - Target Volatility: 15.0%
  - Estimated Portfolio Vol: 20.8%
  - Active Model: GARCH / EWMA / EGARCH selector
  - Total Positions: 2 (Integer count verified)
- **Model Toggles & Target Sizing**:
  - Interactive selection between EWMA, GARCH, EGARCH.
  - Interactive Target Volatility slider (5% to 30%) and quick presets (10%, 15%, 20%).
- **Volatility Forecast & Parity Targets**:
  - Live Volatility calibration panel replacing placeholder box.
  - Ticker volatility bars against target threshold with status indicators.
- **Position-Level Table & Recommendations**:
  - Inverse-volatility risk parity calculations: MOTHERSON.NS (higher vol) scaled down, NTPC.NS (lower vol) scaled up.
  - Weights sum strictly to 100.0%, net trade delta sums to 0.0%.

## 3. Status
- **Audit Verdict**: PASSED & VERIFIED
