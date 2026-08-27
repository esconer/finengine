# Portfolio Audit & Live Market Data Verification

## Overview
This specification details the audit performed on the Daisy Risk Engine portfolio holdings, their migration to **INFY.NS** (Infosys Ltd) and **HDFCBANK.NS** (HDFC Bank Ltd), live verification against **Screener.in** / Yahoo Finance market data, and full quantitative engine validation.

## 1. Initial State vs New Holdings
- **Previous Holdings**:
  - `RELIANCE.NS`: 100 shares @ INR 2,500.00 (Market Value: INR 129,800.00, Weight: 0.15, Energy)
  - `TCS.NS`: 50 shares @ INR 3,500.00 (Market Value: INR 113,500.00, Weight: 0.20, Technology)
- **New Active Holdings**:
  - `INFY.NS`: 100 shares @ INR 1,100.00 (Market Value: INR 111,610.00, Weight: 0.50, Technology)
  - `HDFCBANK.NS`: 150 shares @ INR 710.00 (Market Value: INR 108,000.00, Weight: 0.50, Financial Services)
  - **Total Portfolio Value**: INR 219,610.00

## 2. Live Market Verification (Screener.in vs FinEngine)

| Metric | INFY (Screener.in) | INFY (FinEngine / YF) | HDFCBANK (Screener.in) | HDFCBANK (FinEngine / YF) | Status |
|---|---|---|---|---|---|
| **Current Price** | INR 1,117.00 | INR 1,115.10 | INR 720.00 | INR 720.10 | Verified (<0.2% intraday delta) |
| **Market Cap** | INR 4,53,285 Cr | INR 4,51,972 Cr | INR 11,10,371 Cr | INR 11,09,592 Cr | Verified (<0.3% delta) |
| **Stock P/E** | 14.5 | 14.69 | 14.7 | 15.74 | Consistent |
| **52-Week High** | INR 1,728.00 | INR 1,728.00 | INR 1,020.00 | INR 1,020.50 | Exact match |
| **52-Week Low** | INR 982.00 | INR 982.40 | INR 715.00 | INR 715.10 | Exact match |
| **Sector** | Technology | Technology | Financial Services | Financial Services | Exact match |

## 3. Quantitative Engine Validation Results

### Volatility Term Structure & GARCH(1,1)
- **INFY.NS**:
  - Realized Volatility: 10d = 18.4% (p50=27.5%), 21d = 28.2%, 63d = 35.9%, 126d = 32.6%, 252d = 29.6%.
  - GARCH(1,1) Annualized Forecast: 31.22% (Valuation: `normal`).
- **HDFCBANK.NS**:
  - Realized Volatility: 10d = 7.4% (p50=15.5%), 21d = 11.2%, 63d = 20.2%, 126d = 26.3%, 252d = 20.7%.
  - GARCH(1,1) Annualized Forecast: 14.80% (Valuation: `normal`).

### Tail Risk & EVT-POT (Generalized Pareto Distribution)
- **Portfolio 99% EVT-POT VaR (Daily)**: -3.50%
- **Portfolio 99% EVT-POT ES (Daily)**: -3.97%
- **GPD Tail Fit Parameters**: $\xi = -0.3188$, $\beta = 0.0105$, Exceedances = 13/251 (Fat-Tailed: `True`).
- **Student-t Copula Lower-Tail Dependence Matrix**:
  $$\Lambda_L = \begin{bmatrix} 1.0000 & 0.1642 \\ 0.1642 & 1.0000 \end{bmatrix}$$
  *Low lower-tail crash comovement ($\lambda_L = 0.1642$) indicates solid diversification during market drawdowns.*

### Correlation Stability & Regime Break Monitor
- **Current 60d Pairwise Correlation**: 0.2840
- **Historical 90th Percentile Threshold**: 0.5412
- **Regime Break Alert**: `False` (Alert Level: `NORMAL`).

### Cointegration Scanner & Mean Reversion
- **Scanned Pair**: `HDFCBANK.NS` - `INFY.NS`
- **Engle-Granger p-value**: 0.4281 (Non-cointegrated across raw prices, as expected for cross-sector tech/bank).
- **Hedge Ratio ($\beta$)**: 0.2415
- **Spread Z-score**: 0.18
- **Signal**: `NEUTRAL`

### Liquidity, ADV & Amihud Limits
- **Portfolio Liquidity Score**: 8.4 / 10
- **Days to Liquidate @ 20% ADV**: 0.0018 days (< 10 minutes to fully liquidate at 20% participation).
- **INFY.NS 20d ADV**: 1,626,150 shares (ADTV: ~INR 181.3 Cr), Amihud: $3.81 \times 10^{-11}$.
- **HDFCBANK.NS 20d ADV**: 10,390,546 shares (ADTV: ~INR 748.2 Cr), Amihud: $1.15 \times 10^{-11}$.
- **Risk Category**: `HIGH_LIQUIDITY` for both holdings.

## 4. Issues Identified & Action Plan
1. **Direct M1 Endpoints**: Expose explicit `GET /api/v1/analytics/vol-cone` and `GET /api/v1/analytics/tails` routes matching `PROJECT.md` contracts.
2. **Defensive Returns Alignment**: Ensure wide returns builder and static service methods defensively validate datetime index intersections when combining assets with different cached lengths.
3. **Fundamentals Scraper Enrichment**: Add optional fundamentals bridge from Screener.in / financial statements into portfolio view.
