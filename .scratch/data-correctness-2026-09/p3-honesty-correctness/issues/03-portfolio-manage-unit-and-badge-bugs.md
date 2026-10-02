# 03 — `portfolio/manage` unit and risk-badge bugs

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `frontend/`
Severity: **CRITICAL — the highest user-visible impact in the phase**

## What

Four defects in one page, three of which mean every row displays a wrong number.

### a) Volatility forecast rendered as a raw fraction

`portfolio/manage/page.tsx:786`
```tsx
<span>{position.volatility_forecast.toFixed(2)}%</span>
```

`volatility_forecast` is a **fraction**. The sibling page gets this right —
`forecast-risk/page.tsx:503` does `value * 100`.

A genuine 25.4% volatility renders as **"0.25%"**. Off by 100×.

### b) VaR forecast has the same bug

`:805` — `{position.var_forecast.toFixed(2)}%`

### c) Risk Level is hardcoded "Low" for every position

`:163-167`, called at `:133`
```tsx
const getRiskLevel = (volatility: number) => {
    if (volatility < 20) return 'Low';
    if (volatility < 40) return 'Medium';
    return 'High';
};
```

Called with the same **fraction**. `0.25 < 20` is always true, so **every row shows a green "Low"
risk badge regardless of actual risk.**

`forecast-risk/page.tsx:443` has the correct fraction-based version:
```tsx
volValue > 0.35 ? 'High' : …
```

So this is a stale pre-fraction copy that was never updated.

### d) The "% Return" N/A branch is dead code

`:773-775`
```tsx
{Number.isFinite(monetaryValue(position.unrealized_gain_loss_pct_base, position.unrealized_gain_loss_pct))
    ? `+${monetaryValue(...).toFixed(2)}%`
    : <span className="text-gray-500">N/A</span>}
```

`monetaryValue` (`:44-48`) returns the literal `0` for any non-finite input, so
`Number.isFinite(...)` is **always true** and the `N/A` branch is unreachable.

A position with `nativeCost === 0` computes `NaN` at `:190`/`:201` and displays **"+0.00%"** instead
of N/A. Same root cause in `PortfolioStats.tsx:25-29`.

### e) Minor

`:525` renders a `DollarSign` glyph on the "Total Value" card even when `currency === 'INR'`, next
to an `en-IN` `₹` value.

## Why

Issue (c) is the worst: a risk badge that is always green is worse than no badge, because it
actively misinforms. Issues (a) and (b) mean the two forecast columns are off by 100×, which is
the kind of error that survives a casual look because the number still looks plausible.

## Change

- Multiply both forecast fields by 100 before formatting, matching `forecast-risk/page.tsx:503`.
- Port the correct fraction-based `getRiskLevel` from `forecast-risk/page.tsx:443`. Better: extract
  it to a shared helper so the two pages cannot drift again.
- Change `monetaryValue` to return `null` for a non-finite input, or add a `pctOrNull` helper, and
  tighten the guard. Audit every `monetaryValue` caller.
- Fix the `PortfolioStats.tsx:25-29` instance.
- Use the correct currency glyph for the selected currency.

## Proof of done

- [ ] A position with `volatility_forecast = 0.254` renders **"25.40%"**, not "0.25%".
- [ ] A position with `var_forecast = 0.031` renders the correct percentage.
- [ ] A position with 25% volatility renders a "Medium" or "High" badge. A test asserts the badge
      varies with volatility — **the key regression test**, since a constant-passing test would not
      catch this.
- [ ] A position with `nativeCost === 0` renders "N/A" for % return, not "+0.00%".
- [ ] The `N/A` branch is reachable. A test covers it.
- [ ] `getRiskLevel` exists in exactly one place, shared by both pages. Grep confirms.
- [ ] The Total Value card glyph matches the selected currency.
- [ ] Spot-check three real positions end to end against the raw API response and confirm every
      rendered number matches.

## Notes

The root cause is that no unit contract exists, so each page guesses. Issue 23 fixes that
systemically; this ticket is the immediate fix for the worst instance.

Refs: `../spec.md`, `frontend/src/app/portfolio/manage/page.tsx:44-48,125-135,163-167,190,201,525,773-775,786,805`, `frontend/src/app/dashboard/forecast-risk/page.tsx:443,503`, `frontend/src/components/PortfolioStats.tsx:25-29`
