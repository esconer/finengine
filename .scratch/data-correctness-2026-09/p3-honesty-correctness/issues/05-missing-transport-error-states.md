# 05 — Missing transport-error states on two pages

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `frontend/`
Severity: **HIGH**

## What

Two pages swallow a transport failure and render a plausible-looking all-`N/A` page.

### `volatility-sizing/page.tsx:654-658`

```tsx
} catch (e) {
    console.error(e);
    setSizingData(null);
}
```

There is no transport-error state, and the banner at `:1075` is gated on `sizingData` being
non-null:
```tsx
{sizingData && sizingData.data_status === 'unavailable' && ( … )}
```

So a 500 or network failure sets `sizingData` to null, which **disables the very banner** meant to
communicate the problem. The user sees `Est. Portfolio Vol: N/A`, `Total Positions: N/A`, and zero
rows.

### `realized-risk/page.tsx:53`

`usePortfolioAnalytics()` returns an `error`, but it is **not destructured**. The page renders
eight `N/A` cards and an empty table with no message.

## Why

Every other page in the app has a real error banner. These two are the exceptions, and both fail
**silently** rather than loudly.

A page full of `N/A` is indistinguishable from a page where the analytics genuinely could not be
computed for a legitimate reason (insufficient history, degenerate series). The user cannot tell
"the server is down" from "your data is not enough", and those warrant different actions.

## Change

- Destructure `error` from `usePortfolioAnalytics()` on `realized-risk` and render the existing
  coverage-style banner.
- Change the `volatility-sizing` banner gate from `sizingData && …` to `error || (sizingData && …)`.
- Add a transport-error state distinct from a `data_status: "unavailable"` state. The two mean
  different things and should read differently:
  - transport error → "Could not reach the analytics service"
  - `unavailable` → "The analytics engine could not compute these metrics for your data"
- Apply the same audit to every page that calls `usePortfolioAnalytics`, since a missing `error`
  destructure is an easy omission to repeat.

## Proof of done

- [ ] `volatility-sizing` renders an error banner on a 500 and on a network failure. A test
      asserts the banner is present, which requires fixing the `:1075` gate.
- [ ] `realized-risk` renders an error banner on an analytics failure.
- [ ] The two states render distinguishable copy.
- [ ] Every page using `usePortfolioAnalytics` handles `error`. A grep-based test asserts no page
      calls the hook without referencing `error`.
- [ ] Loading, empty, and error states are visually distinct on both pages.
- [ ] No page renders a full grid of `N/A` with no accompanying explanation.

## Notes

The `data_status` / `universe_coverage` contract that already exists elsewhere in the app is the
right vocabulary for this. Reuse it rather than inventing a second convention.

Refs: `../spec.md`, `frontend/src/app/dashboard/volatility-sizing/page.tsx:654-658,1075-1089`, `frontend/src/app/dashboard/realized-risk/page.tsx:53`, `frontend/src/hooks/useAnalytics.ts`
