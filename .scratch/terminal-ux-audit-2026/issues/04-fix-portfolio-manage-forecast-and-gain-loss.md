# Issue 04: Fix API Response Unwrapping & Negative Sign in Portfolio Management

Status: ready-for-agent
Type: bug
Priority: P1
Blocked by: —

## Description
Two issues exist on `/portfolio/manage`:
1. `fetchForecastRisk` fails silently when extracting `response.data.positions` (since `analyticsApi.getForecastRisk` already unwraps `response.data`), leaving Volatility Forecast, VaR Forecast, and Risk Level as `N/A`.
2. `formatCurrency` uses `Math.abs(amount)`, which strips the negative sign from negative P&L values, showing losses of `-₹38,840` as `₹38,840`.

## Proposed Fix
1. In `src/app/portfolio/manage/page.tsx`, handle both direct and nested response payloads:
   ```ts
   const data = response?.data || response;
   const tickerData = data?.positions?.[position.ticker];
   ```
2. Update `formatCurrency` to retain algebraic negative signs:
   ```ts
   const formatCurrency = (amount: number) => {
     const symbol = currency === 'INR' ? '₹' : '$';
     const sign = amount < 0 ? '-' : '';
     return `${sign}${symbol}${Math.abs(amount).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
   };
   ```

## Proof of Done
- [ ] Volatility Forecast (ann.), VaR Forecast, and Risk Level badges populate with real quantitative numbers for all portfolio holdings.
- [ ] Negative P&L values display with explicit `-` signs in red.
