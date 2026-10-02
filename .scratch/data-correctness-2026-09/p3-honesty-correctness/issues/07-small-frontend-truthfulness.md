# 07 — Small frontend truthfulness fixes

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `frontend/`
Severity: **LOW / MEDIUM**

## What

Six small fabrication and mis-binding defects. Each is a few lines.

### a) Fabricated `0.0%` on the liquidity page

`liquidity/page.tsx:688-690`
```tsx
: `${highVolumeCount} (${positionData.length > 0 ? formatPercentage(highVolumeCount / positionData.length, 1) : '0.0%'})`
```

When the API measured **zero** positions, this renders `"0 (0.0%)"` — a measured-looking success
claim where the truth is "unavailable".

### b) `₹undefined` on the equity-research peer table

`:700` — `₹{peer.cmp?.toLocaleString('en-IN', …)}` renders the literal string `"₹undefined"` when
`cmp` is null. The sibling columns correctly use `'-'`.

### c) Truthiness instead of nullishness on legitimate zeros

`dashboard/page.tsx:531-533` — `forecast_volatility || null`
`RiskMetricsDisplay.tsx:139,146` — `metrics.forecast_volatility ? … : 'N/A'`

A measured `0.0` forecast vol or VaR renders `N/A`. Use `??` and an explicit null check.

### d) A second, drifting copy of the diversification formula

`concentration/page.tsx:626-628` — when `diversification_score` is absent, the page recomputes
`((1-HHI)/(1-1/N))*100` locally with its own `.toFixed(1)` rounding.

That is a duplicate of the engine's formula with different rounding, so the two will disagree.
Prefer rendering `N/A`.

### e) An arbitrary landing ticker

`equity-research/page.tsx:45` — `searchParams.get('ticker') || 'RELIANCE'`

The page silently loads one large-cap on mount with no user action. It **is** a live fetch, so
nothing is fabricated, but the landing state is arbitrary rather than portfolio-derived. Better:
require an explicit ticker, or default to the first portfolio holding.

### f) `STRATEGY_ICONS` hardcoded map

`screener-studio/page.tsx:32-38` — a hardcoded icon map with a safe fallback at `:505`. Cosmetic
only; no action needed unless a cleanup pass is nearby.

## Proof of done

- [ ] (a) Zero measured positions renders "N/A", not "0 (0.0%)".
- [ ] (b) A null `cmp` renders `'-'`, not `₹undefined`.
- [ ] (c) A measured `0.0` renders `0.00%`, not `N/A`. A test covers the zero case specifically —
      this is the regression test.
- [ ] (d) The concentration page never recomputes the score. It renders the engine's value or
      `N/A`.
- [ ] (e) The equity-research landing state is either an explicit user choice or the first
      portfolio holding. A test asserts no silent default to a hardcoded ticker.
- [ ] (f) Either left as-is with a comment, or cleaned up. No behaviour change.

## Notes

These are the residue after the four high-severity frontend tickets. Group them into one PR.

Refs: `../spec.md`, `frontend/src/app/dashboard/liquidity/page.tsx:688-690`, `frontend/src/app/dashboard/equity-research/page.tsx:45,700`, `frontend/src/app/dashboard/page.tsx:531-533`, `frontend/src/components/RiskMetricsDisplay.tsx:139,146`, `frontend/src/app/dashboard/concentration/page.tsx:626-628`, `frontend/src/app/dashboard/screener-studio/page.tsx:32-38,505`
