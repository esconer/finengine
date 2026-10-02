# 04 — `pairs` z-score crash

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `frontend/`
Severity: **CRITICAL — a white screen**

## What

`pairs/page.tsx:100-101`
```tsx
<td className={... `${Math.abs(p.current_spread_zscore) > 2 ? …}`}>
    {p.current_spread_zscore.toFixed(2)}σ
</td>
```

`current_spread_zscore` is `Optional[float] = None` in the API contract
(`backend/app/models/schemas.py:449`), and the route uses
`getattr(pair, "current_spread_zscore", None)` (`analytics.py:6932`).

So `null` is reachable. `Math.abs(null)` → `0`, then `null.toFixed` → **TypeError → white screen.**

## Why

The sibling field `ou_half_life_days` **is** guarded, at `:98`. So this is an oversight, not a
deliberate policy — which makes it more likely to be reintroduced.

The backend produces `null` for a genuinely unmeasurable z-score (zero-dispersion spread, see
issue 21), so the null path is a **correct** backend behaviour being crashed on by the frontend.

## Change

Guard the optional, mirroring `:98`:
```tsx
{p.current_spread_zscore == null
    ? <span className="text-gray-500">N/A</span>
    : `${p.current_spread_zscore.toFixed(2)}σ`}
```

The `Math.abs(...) > 2` className condition must also handle `null` without producing a
false-positive highlight.

## Proof of done

- [ ] A pair with `current_spread_zscore = null` renders "N/A" and **does not throw**.
- [ ] A pair with a normal z-score renders the value with the σ suffix and the correct highlight
      class.
- [ ] A test covers the `null` case explicitly. This is the regression test.
- [ ] The highlight condition does not treat `null` as `0` and apply a "normal" style that implies
      a measurement.
- [ ] Audit the same page and the same route for other unguarded optionals. `schemas.py` marks
      several cointegration fields optional.

## Notes

Small, high value. A crash that blanks the whole page for a legitimately unmeasurable pair is a
bad failure mode for something that is *supposed* to be unmeasurable.

Refs: `../spec.md`, `frontend/src/app/dashboard/pairs/page.tsx:98,100-101`, `backend/app/models/schemas.py:449`, `backend/app/api/analytics.py:6932`
