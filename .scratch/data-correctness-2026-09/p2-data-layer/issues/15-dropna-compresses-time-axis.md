# 15 — `dropna()` compresses the time axis

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: 04
Repo: `backend/`
Severity: **MEDIUM**

## What

`data_service.py:1449` — the normalizer drops any row with a `NaN` in **any** column, including
`adj_close`.

## Why

The repo already identifies this as a defect elsewhere. `indicators_service.py:93-96` says so
explicitly:

> *"would compress the time axis and make the next observation look adjacent"*

The consequence: a sparse vendor response silently produces a **wrong daily-return series**. A
missing `adj_close` on one day removes that row, and the next row's `pct_change()` is then
computed across a two-day gap but reported as a one-day return. That single error propagates into
realized vol, VaR, GARCH, EVT thresholds, cointegration spreads, and drawdowns.

It also interacts badly with `CONTEXT.md` §9.7, which warns against dropping rows when combining
assets with different inception dates.

## Change

- Decide per column what "missing" means. A missing `adj_close` on a day with a real `close` is a
  vendor defect, not a missing observation — the day should be kept and the defect recorded.
- A genuinely absent **trading day** is different: it is a real gap in the calendar, and
  `pct_change()` must span it correctly. That is a calendar-alignment concern, not a `dropna`
  concern.
- Record dropped rows with their reason, so a sparse response is visible rather than silently
  shortened.
- Reuse the existing `indicators_service.py:93-96` rule so there is one policy, not two.

## Proof of done

- [ ] A frame with a `NaN` in `adj_close` but a valid `close` keeps that row, and the defect is
      recorded.
- [ ] A frame with a genuine non-trading day produces a correctly-spanning return. A test asserts
      a 2-day gap yields a 2-day return, not two 1-day returns.
- [ ] The number of dropped rows and the reason for each is exposed in the fetch diagnostics.
- [ ] The `indicators_service.py:93-96` policy and the normalizer policy are the same policy, in
      one shared helper. A test asserts they agree.
- [ ] A sparse-response fixture is committed so this stays covered.
- [ ] Multi-asset alignment (issue 15's sibling concern in `CONTEXT.md` §9.7) still uses
      `.ffill().bfill().fillna(0.0)` rather than `dropna`.

## Notes

This is a small change with a large blast radius on correctness, because it affects the input to
every quantitative service in the app. Add it to `test_quantitative_invariants.py`.

Refs: `../spec.md`, `app/services/data_service.py:1449`, `app/services/indicators_service.py:93-96`, `CONTEXT.md` §9.7
