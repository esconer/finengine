# Page 9: Tear-Sheet Audit & Verification Report

## 1. Page Overview
- **Path**: frontend/src/app/dashboard/tear-sheet/page.tsx
- **Route**: http://localhost:3000/dashboard/tear-sheet
- **Backend API**: GET /api/v1/analytics/tear-sheet

## 2. Live Quantitative & UX Verification
- **Mount Behavior**: Fetches QuantStats statistics and NIFTY 50 benchmark comparison on mount.
- **Top Metric Cards**:
  - Total Return: +49.73%
  - CAGR: +59.46%
  - Sharpe Ratio: 1.85
  - Max Drawdown: -15.61%
- **Against NIFTY 50 Benchmark Analysis**:
  - Beta vs NIFTY 50: 1.22
  - Alpha (Annualized): 51.87%
  - Portfolio Sharpe: 1.85 vs Benchmark Sharpe: -0.20
  - Portfolio Volatility: 26.01% vs Benchmark Volatility: 13.78%
- **Monthly Returns Heatmap**:
  - 12-month geometric return grid with dynamic heat-color intensity mapping.
- **Underwater Drawdown Curve**:
  - Historical drawdown series with worst drawdown highlight (-15.61%).
- **Holdings Breakdown**:
  - Live portfolio weights: MOTHERSON.NS 64.4%, NTPC.NS 35.6%.

## 3. Status
- **Audit Verdict**: PASSED & VERIFIED
