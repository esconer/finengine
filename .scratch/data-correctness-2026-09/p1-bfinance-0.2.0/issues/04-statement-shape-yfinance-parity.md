# 04 — Statement shape → yfinance parity

Status: needs-info
Type: task
Phase: 1
Blocked by: 01
Repo: `C:\es\coding\bfinance`
Severity: **CRITICAL — root cause RC2. Breaking change.**

## What

`Ticker.get_income_stmt` / `get_balance_sheet` / `get_cash_flow` currently return
`to_dataframe(orient="columns")` and never call `to_yfinance()`. Return the yfinance shape
instead. Preserve the native shape under an explicitly different name.

`src/bfinance/ticker.py:229,241,253`

## Why

Four simultaneous breaks, one of which is dangerous:

| | bfinance 0.1.3 | yfinance 1.7.0 (measured) |
|---|---|---|
| Columns | `['Mar 2015', …, 'Mar 2026', 'TTM']`, dtype `str` | `DatetimeIndex`, `2026-03-31 …` |
| **Column order** | **ascending (oldest first)** | **descending (newest first)** |
| Row labels | `'Sales'`, `'Borrowings'` | `'Total Revenue'`, `'Total Debt'` |
| Units | ₹ Cr (`899041.0`) | absolute ₹ (`9.01064e12`) |

**The inverted period order is the dangerous one.** `df.iloc[:, 0]` or `.iloc[:, -1]` silently
returns the *oldest* year from bfinance and the *newest* from yfinance. No exception, no warning —
a 10-year-old number rendered as the current period.

`FinancialStatement.to_yfinance()` at `models/statements.py:88` already fixes all four axes and
is **dead code on the public path**. The tests call it directly instead of going through `Ticker`,
which is why it was never wired up.

The consuming app calls these methods directly
(`finengine/backend/app/services/company_data_service.py:347-352`), so this bug is live on its
`/dashboard/equity-research` financial-statements tab and its 8-tab Excel export.

## Breaking change shape

```python
bf.Ticker("RELIANCE.NS").income_stmt          # → to_yfinance() shape. BREAKING.
bf.Ticker("RELIANCE.NS").get_income_stmt()   # → same
bf.Ticker("RELIANCE.NS").income_stmt_indian() # → native ₹ Cr / Indian labels. NEW.
```

Same for `balance_sheet` and `cash_flow`, plus their `quarterly_*` variants where they exist.

## Proof of done

- [ ] `bf.Ticker("RELIANCE.NS").income_stmt.columns` is a **descending** `DatetimeIndex`.
- [ ] `.iloc[:, 0]` is the most recent period in **both** bfinance and yfinance.
- [ ] Row labels use the yfinance set (`total_revenue`, `total_debt`, …), not the Indian set.
- [ ] Units are absolute ₹, not ₹ Cr. A spot check ties to yfinance within 0.1%.
- [ ] `income_stmt_indian()` (and siblings) return the pre-0.2.0 shape, so a consumer depending
      on it has a one-token migration rather than a broken import.
- [ ] `to_yfinance()` is no longer dead code — it is on the public path, and its coverage reflects
      that.
- [ ] The test added in Phase 1 issue 01 (period-order invariant, which must fail against 0.1.3)
      now passes.
- [ ] `ticker.py:285,295,311,320` — `ttm_income_stmt`, `ttm_cash_flow`, quarterly balance sheet,
      and quarterly cash flow return **empty DataFrames**, not `NotImplementedError`. A consumer
      doing `t.quarterly_balance_sheet` currently gets a hard crash on a path yfinance serves.
- [ ] The release notes state the breaking change prominently, with the migration table.

## Notes

The `to_yfinance()` implementation already exists and is tested. This ticket is wiring plus
correcting the test suite's incorrect assertion.

Refs: `../spec.md`, Phase 1 issue 01, `models/statements.py:88`, `ticker.py:229,241,253,285,295,311,320`

## Verification correction (2026-09-28)

Alarm count is **7, not 8**; `reason=_ISSUE_04` count is **6, not 7**. `xfail(strict=True)`
decorators sit at 180, 226, 239, 252, 266, 278, 290 - line 180 carries an inline reason about
`to_yfinance()` de-duplicating aliased rows, which is issue-04 by text but a distinct contract.

The substantive claim holds. `test_yfinance_columns_are_newest_first` (def :240) asserts
`df.columns.is_monotonic_decreasing` at :249 and reports XFAIL, so the order really is ascending
today. The file reports `5 passed, 7 xfailed`, **0 xpassed** - nothing is silently starting to pass.
