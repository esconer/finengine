# 28 — Remove the fabricated API defaults and drift-guard the globals

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `backend/`
Severity: **MEDIUM**

## What

Two small defects that are traps for future work.

### a) Fabricated `0.0` defaults in the API layer

```
analytics.py:3499-3500   "r_squared": factor_result.get("r_squared", 0.0)
                          "adjusted_r_squared": factor_result.get("adjusted_r_squared", 0.0)
analytics.py:3592-3600   the concentration route defaults every metric to 0.0
                          and diversification_ratio to 1.0
analytics_engine.py:2523-2536   _empty_concentration
```

These are currently masked because `_empty_factor_exposure` (`analytics_engine.py:2511-2521`)
**always** sets the key to `None`, so the `, 0.0` default is never reached.

That is luck, not design. The moment any future engine path omits the key, the default fires and
publishes a fabricated `0.0` — exactly the bug that `_empty_factor_exposure` exists to prevent.

`CONTEXT.md` §9.23 records the precedent: `_empty_factor_exposure`'s `{alpha:0, market:1}` showed
as *"β +1.000 Market-Like"* for every position. The same failure would recur through a different
door.

### b) Mutable process globals

`source_preference_service.py:99-101` — `_ACTIVE_SOURCE_ORDER` is a process-global mutable cascade
used by `CompanyDataService` when `source_order is None` (`company_data_service.py:146-147,323-324`).

Every live route passes `source_order` explicitly (`data.py:263`, `:290`), so it is unreachable
today — but it is a request-race waiting to happen, and a process-global mutable is the wrong
default for a per-request setting.

`analytics_engine.py:663` — `top_10 = 1.0` when `n < 10`, which is a **"100% in top 10"** reading
for a 3-stock book. Undocumented and misleading at small `n`.

## Change

- Delete the `, 0.0` and `, 1.0` defaults. A missing key should be a loud `KeyError` or an explicit
  `None`, never a plausible number.
- Make `source_order` a required parameter. Remove the global.
- Document or fix the `top_10` small-`n` behaviour.

## Proof of done

- [ ] No `.get(<key>, 0.0)` or `.get(<key>, 1.0)` default remains for a metric field. Grep
      confirms.
- [ ] A test constructs a factor result **omitting** `r_squared` and asserts the response is
      `None` or an error — not `0.0`. This is the regression test for the latent trap.
- [ ] `_ACTIVE_SOURCE_ORDER` is gone and `source_order` is required.
- [ ] The `top_10` small-`n` behaviour is either corrected or documented in the response contract.
- [ ] The concentration route's metric defaults are `None`.

## Notes

`analytics_engine.py:663` also has a nearby comment drift worth fixing:
`screener_service.py:33` says `AnalyticsCache.ticker` is `String(10)` while the model is
`String(20)`. Small, but the comment will mislead the next person who hits a truncation.

Refs: `../spec.md`, `backend/app/api/analytics.py:3499-3500,3592-3600`, `backend/app/services/analytics_engine.py:663,2511-2521,2523-2536`, `backend/app/services/source_preference_service.py:99-101`, `backend/app/services/company_data_service.py:146-147,323-324`, `backend/app/services/screener_service.py:33`, `CONTEXT.md` §9.23
