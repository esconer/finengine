# 11 — Ragged-row padding in `to_dataframe()`

Status: ready-for-agent
Type: task
Phase: 1
Blocked by: —
Repo: `C:\es\coding\bfinance`
Severity: **MEDIUM**

## What

`src/bfinance/models/statements.py:73`
```python
pd.DataFrame(self.rows, index=self.headers).T
```

Any row whose cell count differs from the header count raises `ValueError`.

## Why

Reachable via a screener.in table containing a footnote cell, a detail/expand row, or a blank
`<th>` that was filtered out at `parser.py:247`/`:251`. Verified:
```
FinancialStatement(headers=['Mar 2023','Mar 2024','Mar 2025'], rows={'Sales':[1.0,2.0]}).to_dataframe()
-> ValueError: Length of values (2) does not match length of index (3)
```

The exception propagates to **nine** public properties, taking all of them down:
`Ticker.financials`, `.balance_sheet`, `.cash_flow`, `.shareholding`, `.shareholding_yearly`,
`.ratios_history`, `.quarterly_financials`, `.custom_ratios`, `.piotroski_score`.

A single malformed cell on one company breaks the entire equity-research profile for that ticker.

## Proof of done

- [ ] Each row is padded or truncated to `len(headers)` before the DataFrame is constructed.
- [ ] A mismatch logs a warning naming the statement and the row label, so the defect is visible
      upstream rather than papered over.
- [ ] A test constructs a statement with a short row, a long row, and an empty row, and all
      three produce a valid DataFrame.
- [ ] A test confirms a footnote cell in a realistic screener.in fragment does not raise through
      any of the nine properties.
- [ ] A partially-parsed statement is marked as partial (row coverage below some threshold) so a
      consumer can distinguish a sparse real statement from a parse failure.

## Notes

The "mark as partial" part is not in the original defect but matters: silent padding can turn a
parse failure into a plausible-looking sparse statement, which is the same class of defect as
issue 09.

Refs: `../spec.md`, `models/statements.py:73,75,103,114`, `screener/parser.py:247,251`
