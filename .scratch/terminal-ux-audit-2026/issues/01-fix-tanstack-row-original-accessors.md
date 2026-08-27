# Issue 01: Fix TanStack Table row.original Accessor Bug Across 7 Dashboard Pages

Status: ready-for-agent
Type: bug
Priority: P1
Blocked by: —

## Description
In 7 dashboard analytics tables, custom column cell renderers read `row.<field>` instead of `row.original.<field>`. Since `row.<field>` evaluates to `undefined`, mathematical operations like `(undefined * 100).toFixed(2)` render as `NaN%`, tickers render as empty strings, and metrics render as blank cells.

## Affected Pages
1. `src/app/dashboard/realized-risk/page.tsx`
2. `src/app/dashboard/forecast-risk/page.tsx`
3. `src/app/dashboard/factor-exposure/page.tsx`
4. `src/app/dashboard/stress-testing/page.tsx`
5. `src/app/dashboard/concentration/page.tsx`
6. `src/app/dashboard/liquidity/page.tsx`
7. `src/app/dashboard/volatility-sizing/page.tsx`

## Proposed Fix
Standardize all column cell render functions:
```tsx
cell: ({ row }: any) => {
  const data = row.original || row;
  return <div>{data.ticker}</div>;
}
```

## Proof of Done
- [ ] No `NaN%`, `N/A`, or empty ticker names appear in the position tables of all 7 affected pages.
- [ ] `bun x tsc --noEmit` and `bun x vitest run` pass.
