# Page 6: Concentration Audit & Verification Report

## 1. Page Overview
- **Path**: frontend/src/app/dashboard/concentration/page.tsx
- **Route**: http://localhost:3000/dashboard/concentration
- **Backend API**: GET /api/v1/analytics/concentration

## 2. Live Quantitative & UX Verification
- **Mount Behavior**: fetchPortfolio() loads active holdings on mount and triggers getConcentrationMetrics().
- **Top Metric Cards**:
  - Largest Position: 100.0%
  - Top 3 Holdings: 100.0%
  - Herfindahl Index (HHI): 1.00 (Exact theoretical value for N=1)
  - Effective Positions (N_eff): 1.00 (Exact 1/HHI value for N=1)
- **Lorenz Concentration Curve**:
  - Live SVG chart plotted via Recharts rendering Equal-Weight diagonal benchmark against Portfolio Concentration curve.
- **Sector Concentration**:
  - Sector roll-up reflects active holdings exposure (Consumer Cyclical: 100.0%).
- **Position Concentration Table**:
  - Columns: Ticker, Weight, Cumulative %, Sector, Concentration Risk.
  - Search filter and CSV Export functionality verified.
- **Insights & Risk Assessment**:
  - High Single Position Risk warning rendered when largest position > 40%.

## 3. Status
- **Audit Verdict**: PASSED & VERIFIED
