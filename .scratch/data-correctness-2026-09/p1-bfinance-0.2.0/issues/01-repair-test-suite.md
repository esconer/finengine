# 01 — Repair the test suite (GATE)

Status: ready-for-agent
Type: task
Phase: 1
Blocked by: —
Repo: `C:\es\coding\bfinance`

## What

The bfinance test suite currently **certifies the bugs as correct**. Repair it before any
correctness fix, or those fixes will be reported as regressions.

Specific defects:

### a) It locks in the wrong statement shape

`tests/test_parity_statements.py:93`
```python
assert all(isinstance(c, str) for c in df.columns)   # asserts the WRONG shape is correct
```

Real yfinance 1.7.0 returns a descending `DatetimeIndex`. This line is why the inverted period
order shipped.

### b) The "yfinance parity" suite does not compare against yfinance

Only 5 of 18 test files import yfinance. Two of the most heavily implied files never import it:

- `tests/test_ticker_yfinance_compat.py` (12 tests) — asserts bfinance's **own** declared shapes
- `tests/test_exhaustive_screener_and_yfinance.py` (18 tests) — same; the filename is misleading

`tests/test_live_yfinance_parity.py:65-103` checks only `isinstance(x, pd.DataFrame)`, `x.equals(y)`
self-consistency, and `pytest.raises(NotImplementedError)`. That is exactly why the statement
inversion shipped.

### c) The `:memory:` cache fixture is a no-op

`tests/conftest.py:13` + `src/bfinance/cache/sqlite_cache.py:20`

`_connect()` opens a **new** connection per call, and each `:memory:` connection is a separate
throwaway database. `_init_db` creates the table in a database that is immediately discarded, so
every later `get`/`set` hits a schema-less database. Verified: `set` then `get` raises
`no such table: bfinance_cache` twice and returns `None`.

The `temp_cache` fixture — and the `screener_client` fixture built on it, used by
`test_valuation_charts.py`, `test_screener_depth.py`, `test_exhaustive_screener_and_yfinance.py`
— is functionally a cache that never caches, while emitting an ERROR log per call.

### d) A test constructs an impossible production scenario

`tests/test_parity_info.py:42` builds `build_info_dict(_profile("500112.BO"))["exchange"] == "BSE"`
by putting a suffixed ticker into `profile.symbol`. `ticker.py:43` always stores the **bare**
symbol, so this cannot occur in production. The test passes while the real BSE exchange bug is
live.

### e) The `live` marker gates nothing

50 tests carry `@pytest.mark.live` and **all 50 run in CI** — `.github/workflows/ci.yml` never
passes `-m "not live"`. Meanwhile the 30 unmarked network tests in (b) would be silently dropped
if anyone added the flag to speed up CI. CI runs 4 Python versions × full network × 163 tests,
four times per push.

### f) The suite is a coin flip

163/163 pass on a clean cache. On a second run under `--cov` (slower, so the screener.in pacer
engages), 5 fail — including `test_capital_gains_empty_parity`, which does not even involve
bfinance. These tests make hard assertions against **live yfinance data** (last-4 dividend
amounts within 5%, `y.index[-1]` on yfinance's splits).

## Why

Issues 06, 07, 08, 13 all change behaviour this suite currently pins. Without this ticket, a
correct fix looks like a regression and gets reverted.

## Proof of done

- [ ] `test_parity_statements.py:93` is deleted and replaced with a real yfinance comparison:
      column dtype, column order (descending), and label set.
- [ ] A new test asserts the **period-order invariant** that issue 07 depends on: for both
      bfinance and yfinance, `df.columns[0]` is the most recent period. This test must exist
      *before* issue 07 lands, and must fail against 0.1.3.
- [ ] `test_ticker_yfinance_compat.py` and `test_exhaustive_screener_and_yfinance.py` import
      yfinance and compare against it. Where a live comparison is inappropriate, the test is
      marked `live` and excluded from the default run.
- [ ] The `:memory:` fixture is replaced with `file::memory:?cache=shared` plus a held-open
      keeper connection, or a `tmp_path` file-backed database. A test asserts a `set` followed by
      a `get` returns the value.
- [ ] `test_parity_info.py:42` is rewritten to construct the production scenario
      (`Ticker("500112.BO")`), not a hand-built profile with a suffixed symbol.
- [ ] CI passes `-m "not live"`, and **every** network-dependent test is correctly marked. Verify
      by confirming the default CI run performs zero network requests.
- [ ] Network-dependent tests use tolerant assertions (shape and sign, not exact live values) or
      are marked `live`. Two consecutive full runs pass.
- [ ] `pytest` runs 4 consecutive times clean, including once under `--cov`.

## Notes

This ticket changes no `src/` code. It changes only tests and CI config. It should be merged
first and separately so the correctness fixes land on a clean, honest baseline.

Refs: `../spec.md`, issues 06, 07, 08, 13

## Verification correction (2026-09-28)

The first-pass status report cited four live `assert all(isinstance(c, str) for c in df.columns)`
lines on statement columns. **Two of the four are not assertions.**

- `test_parity_statements.py:90` is inside the docstring of a `@pytest.mark.live` test, quoted
  under "The previous version of this test asserted::". Already defanged.
- `test_stmt_accessor_contract.py:15` is inside the **module docstring**, quoted as an example of
  the removed defect - that is where the `# locks in the wrong shape` comment lives. Already
  defanged.
- `test_parity_statements.py:35` and `test_stmt_accessor_contract.py:102` are live and un-xfailed.

Both live lines target `FinancialStatement.to_dataframe()` - the **native** Indian Rs-Cr method,
not `to_yfinance()`. The real residual defect is about *signalling*, not shape: both sit in a file
named `test_parity_statements.py`, implying yfinance parity, and neither is xfailed, so the 0.2.0
break lands as a red suite rather than a signalled break.

**New, uncovered:** `test_stmt_accessor_contract.py:103` is
`assert df.columns.is_monotonic_increasing is False or True` - true for every possible value of the
expression. A live offline assertion that asserts nothing. Needs its own ticket.
