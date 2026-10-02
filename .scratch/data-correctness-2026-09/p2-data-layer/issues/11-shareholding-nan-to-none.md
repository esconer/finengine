# 11 — Shareholding `NaN` must become `None`, not `0.0`

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: —
Repo: `backend/`
Severity: **CRITICAL**

## What

`equity_research_service.py:150-153` and `:165-168`:
```python
try:
    entry[key] = float(val) if pd.notna(val) else 0.0
except (ValueError, TypeError):
    entry[key] = 0.0
```

A missing promoter/FII/DII/public holding value for a quarter becomes a **0.0**, which renders as a
`0.00%` bar in the stacked-area chart.

## Why

A genuine 0% holding and a **missing** holding are indistinguishable in the output. So the
12-quarter shareholding chart can show a promoter at 0% — and the pie rebalancing accordingly —
with no error, no gap, and no missing marker.

The chart is a decision input: a promoter dropping to zero is a major governance event, and a
promoter *not reported* for a quarter is a data gap. Conflating them is exactly the failure mode
`CONTEXT.md` §9.23 forbids.

This is also compounded by Phase 1 issue 19: shareholding patterns get **restated**, and NSE
publishes an explicit revision date. A restated or missing quarter must be representable as such,
not coerced to zero.

## Change

- `pd.notna` failure → `None`, not `0.0`.
- Type errors → `None`, plus a recorded parse warning naming the row and field.
- The response schema must allow `None` for these fields. If it does not today, widen it — this is
  a **breaking contract change** and belongs in the Phase 3 schema snapshot diff.
- The chart component must render a **gap** for `None`, distinct from a 0% bar. This is a
  frontend change and belongs in the same PR.
- The response should carry a per-quarter completeness flag so a consumer can tell "reported" from
  "not reported".

## Proof of done

- [ ] A `NaN` holding value returns `null` in the response, not `0.0`.
- [ ] A non-numeric value returns `null` and records a parse warning naming the field and row.
- [ ] The stacked-area chart renders a gap for `null` and a zero-height bar for `0.0`. A
      component test asserts the two are visually distinct.
- [ ] The pie chart excludes `null` categories and labels the quarter as incomplete rather than
      renormalising silently.
- [ ] A per-quarter completeness flag is present.
- [ ] The four chart styles built from this data (12Q, 11Y, stacked area, breakdown) all handle
      `None`.
- [ ] A test with a genuinely 0% quarter still renders `0.0` and a visible zero bar — the
      distinction is the whole point.
- [ ] The API schema change appears in the OpenAPI diff, deliberately.

## Notes

Check whether the same `float(val) if pd.notna(val) else 0.0` pattern appears elsewhere in the
file or in `company_data_service.py`. It is a common defensive idiom that silently converts
missing to zero, and this codebase's stated principle is that it must not.

Refs: `../spec.md`, `app/services/equity_research_service.py:150-153,165-168`, `CONTEXT.md` §9.23
