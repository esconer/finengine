# Page 10: Risk Contribution Audit & Verification Report

## 1. Page Overview
- **Path**: frontend/src/app/dashboard/risk-contribution/page.tsx
- **Route**: http://localhost:3000/dashboard/risk-contribution
- **Backend API**: GET /api/v1/analytics/risk-contribution

## 2. Live Quantitative & UX Verification
- **Mount Behavior**: Auto-fetches Euler volatility decomposition and CVaR tail attributions.
- **Top Metric Cards**:
  - Portfolio Volatility (Annualized): 26.01%
  - Daily VaR 95%: -2.45%
  - Daily CVaR 95%: -3.18%
  - Top Risk Driver: MOTHERSON.NS (88% share)
- **Position Risk Contribution Bars**:
  - Euler Volatility Shares: MOTHERSON.NS 87.6%, NTPC.NS 12.4% (Sum = 100.0%).
  - Tail Losses (CVaR) Shares: MOTHERSON.NS 83.7%, NTPC.NS 16.3% (Sum = 100.0%).
- **Sector Volatility Roll-up**:
  - Consumer Cyclical: 87.6%
  - Utilities: 12.4%
- **Mathematical Homogeneity**:
  - Verified Euler degree-1 homogeneity condition where sum of percentage contributions strictly equals 100%.

## 3. Status
- **Audit Verdict**: PASSED & VERIFIED
