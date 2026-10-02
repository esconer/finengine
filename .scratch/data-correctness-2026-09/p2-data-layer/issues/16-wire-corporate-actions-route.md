# 16 — Wire `get_corporate_actions` to a route

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: Phase 1 issue 05
Repo: `backend/`
Severity: **MEDIUM**

## What

`DataService.get_corporate_actions` (`data_service.py:1158-1190`) exists and returns splits and
dividends. It is **exposed on no route** — grep finds it only in tests.

## Why

Two reasons this matters more than a missing endpoint usually would.

**a) Split-adjusted returns are unreconstructable without it.** With Phase 1 issue 05 landing
(equity-capital heuristic deleted in favour of real corporate actions), the app has a source of
truth for splits and dividends and no way to expose or consume it. A position's quantity should
change on a 1:2 bonus issue; today nothing tells it to.

**b) It is the only place adjustment provenance is checkable.** `data_service.py:1174` carries the
note *"yfinance adj_close is already adjusted for splits and dividends"*. With Phase 1 issue 04's
concern — a vendor whose `Adj Close == Close` is not adjusting at all — this endpoint is how a
consumer verifies the adjustment claim rather than taking it on faith.

## Change

- Add the route under `/api/v1/data/`.
- Fix the source-preference violation while here: `:1164` hardcodes `yf.Ticker` with no bfinance
  tier and no `app_settings` read. Corporate actions should honour the configured cascade.
- Return a structured payload: per-action `{date, type, ratio | amount, side}` plus the
  adjustment convention actually applied by each vendor.
- Record provenance so a consumer can see which vendor supplied the actions.

## Proof of done

- [ ] `GET /api/v1/data/{ticker}/corporate-actions` returns splits and dividends.
- [ ] The endpoint honours the configured data-source preference. A test sets the preference to
      bfinance and asserts the bfinance tier is used.
- [ ] The response names the vendor and the adjustment convention for each.
- [ ] The equity-capital-ratio heuristic's output is **not** present. A test asserts
      `IDEA.NS` returns zero splits, matching Phase 1 issue 05.
- [ ] Dividend **ex-dates** are real ex-dates, not fiscal year-end. At least 3 known cases pinned.
- [ ] A test asserts that for a symbol with a known split, the ratio matches the corporate-action
      record.
- [ ] The payload can be fed into the Phase 5 issue 12 lot ledger, which is the real consumer.

## Notes

`CONTEXT.md` §3 lists `company_data_service` as exposing "fundamentals/financials/insider trades"
but the corporate-actions capability is not mentioned anywhere in the documented API surface. Add
it to the API documentation and the AI-context export.

Refs: `../spec.md`, `app/services/data_service.py:1158-1190,1164,1174`
