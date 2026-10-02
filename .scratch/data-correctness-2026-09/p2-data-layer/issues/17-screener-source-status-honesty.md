# 17 — Screener source and status honesty

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: 08
Repo: `backend/`
Severity: **HIGH**

## What

Four defects in `screener_service.py`, all producing a confident-looking wrong answer.

### a) The debt-free screen silently shrinks its result set

`:280-298`
```python
def _check():
    kept = []
    for r in results:
        try:
            info = bf.Ticker(r.get("symbol", "")).info or {}
            de = info.get("debtToEquity")
            if de is not None and float(de) <= DEBT_FREE_MAX_DE_RATIO:
                kept.append(r)
        except Exception:
            continue                    # ← symbol silently dropped
    return kept
```

Then `:261-268` builds the success payload with **no `data_status` key at all** — only the
generation-fence branch at `:270` adds one.

A bfinance outage on N of M symbols returns HTTP 200 with `count: M-N` and
`"source": "bfinance"`. The user reads it as a genuine screen result.

### b) Vendor `NaN` becomes `0.0`

`:243-244` and `:354-355` publish `price: 0.0` and `market_cap_cr: 0.0` when the vendor `NaN`s
those columns. Same class as issue 11.

### c) The source string is hardcoded and the preference is ignored

`:265` and `:370` hardcode `"source": "bfinance"`. `ScreenerService` **never reads
`app_settings.primary_data_source`**.

Setting `primary_source=yfinance` has zero effect on `/screens/*`.

### d) The `or` fallback pattern in the D/E check

`info.get("debtToEquity")` returning `None` for a genuine `0.0` is the bfinance-side bug from
Phase 1 issue 08. `float(de)` on a `None`-skipped symbol means the filter **drops** the canonical
zero-debt names — INFY, HDFCBANK, TCS — from a screen whose entire purpose is to find them.

## Why

Screener Studio is one of the app's two flagship differentiator pages. A screen that silently
returns a partial universe as a complete one is worse than one that fails, because the user has no
way to know.

## Change

- Report partial results **as partial**: `data_status`, the count attempted vs returned, and the
  list of symbols that failed with their reason.
- `0.0` for a `NaN` price becomes `None`.
- Either honour `primary_data_source` or state clearly that screening is bfinance-exclusive.
  `CONTEXT.md` §5 says screener/equity-research/AI-dossier stay **bfinance-exclusive** by design —
  so the correct fix is likely to make the response *say* that, and to stop implying the
  preference applies. Confirm with the owner.
- Fix the D/E check to use an `is not None` test and to work with Phase 1 issue 08's fix.
- Add the `data_status` key to every screen response, not just the generation-fence branch.

## Proof of done

- [ ] A bfinance error on 3 of 50 symbols returns `data_status: "partial"`, with the attempted
      count, the returned count, and the failed symbols.
- [ ] A complete failure returns a provider error, not an empty `200`.
- [ ] A `NaN` vendor price returns `null`, not `0.0`.
- [ ] The response states the screen's source explicitly and whether the source preference applies.
      A test asserts the statement matches the implementation.
- [ ] `INFY`, `HDFCBANK`, and `TCS` **appear** in `debt_free_compounders` output once Phase 1
      issue 08 lands. This is the regression test for the combined bug.
- [ ] Every screen response has a `data_status` key. A test iterates all five strategies plus
      custom.
- [ ] The screener logs its fetches (depends on issue 08).

## Notes

`CONTEXT.md` §5 already documents the bfinance-exclusive design. Align the code and the
documentation rather than adding a fallback path that does not exist.

Refs: `../spec.md`, `app/services/screener_service.py:243-244,261-268,270,280-298,354-355,370`, `CONTEXT.md` §5
