# 24 — Delete every scale-sniffing formatter

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: 23
Repo: `frontend/`
Severity: **HIGH**

## What

Four places guess whether a value is a fraction or a percentage using a magnitude heuristic:

```
liquidity/page.tsx:391            Math.abs(value) <= 1.0 && value !== 0 ? value * 100 : value
stress-testing/page.tsx:537,543,552,561
volatility-sizing/page.tsx:809
```

## Why

The heuristic mis-renders any legitimate value in `(-1, 1]`.

A genuine **−1.0%** daily return has `|−1.0| <= 1.0`, so it renders as **−100.00%**. A genuine
**0.5%** VaR renders as **50.00%**. A genuine **1.0%** move is the boundary and renders correctly
by accident.

The intent is understandable — the codebase has no unit contract, so the frontend sniffs. But the
sniff is wrong at the boundary and it is **unfixable from the frontend**, because the frontend
cannot know the true unit.

## Change

Delete all four. Bind each field's unit explicitly from the API's `units` block (issue 23) or from
the field name.

Where a field genuinely arrives in mixed units, the **backend** must normalise it, not the
frontend. A field that sometimes means a fraction and sometimes a percent is a backend contract
defect.

## Change inventory

| Location | Fields affected |
|---|---|
| `liquidity/page.tsx:387-393` | spread, and the liquidity distribution percentages |
| `stress-testing/page.tsx:537,543,552,561` | scenario impact percentages |
| `volatility-sizing/page.tsx:809` | per-leg volatility |

## Proof of done

- [ ] No `Math.abs(...) <= 1.0` scale heuristic remains. Grep confirms.
- [ ] A field that legitimately arrives as `−0.01` renders as `−1.00%`, not `−100.00%`. A test
      covers the negative case specifically — that is the failure this heuristic produces.
- [ ] A field that arrives as `0.5` renders as `0.50%`, not `50.00%`.
- [ ] A field that arrives as `25.4` renders as `25.40%`.
- [ ] Each of the four formatters reads its unit from the `units` block or the field name.
- [ ] Spot-check the stress-testing page against the raw API response for all four scenarios.
- [ ] The `?? 0` bar-geometry fallbacks at `volatility-sizing:1666,1681` are reviewed — an unknown
      weight currently draws a 0-width bar. The label correctly says N/A, so this may be
      acceptable, but confirm.

## Notes

This ticket is only possible after issue 23. Until the backend declares units, deleting the
heuristic leaves those fields unrendered — which is arguably better than mis-rendered, but the
right sequence is 23 then 24.

Refs: `../spec.md`, `frontend/src/app/dashboard/liquidity/page.tsx:387-393`, `frontend/src/app/dashboard/stress-testing/page.tsx:537,543,552,561`, `frontend/src/app/dashboard/volatility-sizing/page.tsx:809,1666,1681`
