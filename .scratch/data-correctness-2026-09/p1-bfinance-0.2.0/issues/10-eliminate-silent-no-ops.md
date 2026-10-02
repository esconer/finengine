# 10 — Eliminate the silent no-ops

Status: needs-info
Type: task
Phase: 1
Blocked by: —
Repo: `C:\es\coding\bfinance`
Severity: **HIGH**

## What

Seven places where bfinance accepts an argument, ignores it, or silently substitutes a default,
where yfinance would raise or honour it.

### a) An unrecognised `period` silently returns 5 years of data

`src/bfinance/market/ohlcv.py:135-137` — `days = 1825` default, overwritten only on a map hit.

Verified:
```
period='1mo'        -> 21 rows
period='bogusperiod' -> 261 rows, no error
```

yfinance raises `ValueError: Period 'bogusperiod' is invalid`. A typo costs 100× the API latency
and 12× the rows, silently.

### b) `period='1d'` returns 2 bars

`src/bfinance/market/ohlcv.py:57` — `"1d": 2` calendar days.

Verified: `bf period=1d` → 2 rows (2026-09-24, 2026-09-25) vs `yf period=1d` → 1 row. The consumer
asking for "today's bar" gets two.

### c) `download()`'s blanket `except` makes its error path dead code

`src/bfinance/download.py:217`; the unreachable re-raise is at `:95`

`_download_batch_async` deliberately re-raises `NotImplementedError`/`ValueError` (`:94-95`), then
`download()` catches everything and returns an empty frame. So `Ticker.history(interval='5m')`
raises but `bf.download(interval='5m')` returns `(0,0)` silently — **the two entry points
disagree**. Verified.

Same class: a 403/429 from screener.in during a 200-ticker batch yields an empty DataFrame that
looks like "no data for these tickers".

### d) `session=` is accepted and silently discarded

`src/bfinance/ticker.py:37`, `tickers.py:55,69`, `download.py:153`

Grep for `self.session` returns **zero hits** — the parameter is never stored or used. A consumer
wiring a custom session (the standard yfinance proxy/cookie pattern) gets it ignored with no
warning.

### e) `download(timeout=…)` is accepted and never passed down

`src/bfinance/download.py:151`

### f) `download(**kwargs)` swallows consumer typos

`src/bfinance/download.py:155` + `:217`

Verified: `bf.download('RELIANCE.NS', period='5d', totlly_bogus_kwarg=123)` → `(5, 5)`, no error.
yfinance raises `TypeError`. Every misspelled yfinance kwarg becomes a silent no-op.

### g) `download(ignore_tz=…)` is accepted and ignored

`src/bfinance/download.py:106-112` — tz is always stripped. `ignore_tz=False` silently does
nothing.

## Why

Each of these converts a loud error into a silent wrong answer. Together they mean a consumer
cannot trust that a successful return means what they asked for was actually returned.

## Proof of done

- [ ] `period='bogus'` raises `ValueError` listing the supported values.
- [ ] `period='1d'` returns exactly 1 row; `period='5d'` returns exactly 5 trading days.
- [ ] `download(interval='5m')` and `Ticker.history(interval='5m')` **both** raise, and with the
      same exception type.
- [ ] A 403/429 during a batch `download` raises a typed error rather than returning an empty
      frame.
- [ ] `session=` is either honoured (verified by asserting a custom transport is actually used) or
      rejected with `TypeError`. Same for `timeout` and `ignore_tz`.
- [ ] `download(totlly_bogus_kwarg=123)` raises `TypeError`.
- [ ] `Ticker(multi_level_index=…)` (`tickers.py:29-38`) either stores it where something reads
      it, or rejects it. It currently stores it on the instance where nothing does.
- [ ] Each of the seven has a test asserting the loud failure.

## Notes

Behaviour change: consumers relying on a silent default will now get an exception. That is the
intent, and it belongs in the 0.2.0 release notes.

Refs: `../spec.md`, `download.py:94-95,106-112,151,153,155,217`, `market/ohlcv.py:57,135-137`, `ticker.py:37`, `tickers.py:29-38,55,69`

## Verification correction (2026-09-28)

**LESS satisfied than a first pass claimed. Two sub-items are open, one of them newly discovered to be
worse than described.** Verified at `98463d9` by execution.

### (a) `download()` does NOT reject unknown kwargs - it only warns

Reported as fixed. It is not. `src/bfinance/download.py:219`:

```python
logger.warning("download() ignoring unsupported keyword argument(s): %s", ", ".join(sorted(kwargs)))
```

Executed with a stubbed ticker: `download(["RELIANCE","TCS"], bogus_kwarg=1)` **returned a normal
(2, 5) frame with no exception**, and the warning fired. The argument is still silently ignored -
only the silence was reduced to a log line. The `download.py:210-215` docstring is about making
`raise_errors` an explicit parameter (true, and a real fix), not about general rejection.

This ticket's own framing - "download swallows every kwarg" - is therefore still accurate.

### (b) Unknown `period` silently becomes 5 years - CONFIRMED

`ohlcv.py:559-561` defaults `days = 1825` and only overrides on a `PERIOD_DAYS_MAP` hit, with no
raise and no warning. Measured request windows:

```
period='1mo'   -> 2026-08-29     period='1d'      -> 2026-09-26
period='BANANA'-> 2024-01-01     period='2w'      -> 2024-01-01
period=''      -> 2024-01-01     period='1M'      -> 2024-01-01
```

Note `'1M'`: a plausible yfinance period is silently mishandled, because the map key is `'1m'`. A
user asking for one month of monthly bars gets the archive floor.

### (c) The bare `except Exception:` set - 5 sites, and the location matters

`src/bfinance/ticker.py` **139, 157, 631, 635, 646** (the other handlers are typed). The others are
`except RuntimeError:` at `:68` and `(TickerNotFoundError, UpstreamServiceError, BFinanceError)` at
`:86` and `:110`.

**Correction to a first-pass claim:** 631/635/646 were described as CAGR handlers. They are not -
they are in `valuation_measures` (property at `ticker.py:622`). `cagrs` (`:569-573`) has **no**
`try`/`except` at all.

| line | member | caller receives |
|---|---|---|
| 139 | `fast_info` | missing 52w / prev-close fields |
| 157 | `info` | missing values |
| 631 | `valuation_measures` | **wrong number, unflagged** |
| 635 | `valuation_measures` | **wrong number, unflagged** |
| 646 | `_latest` | `None` (contained) |

**Two of them produce a confident wrong answer, and this is new.** `to_dataframe()` raises
`ParsingError` (a `BFinanceError` - the typed error its own docstring says escapes the typed
handlers) on a ragged row; the bare handler substitutes an empty frame and computation continues.
Measured: `EnterpriseValue 5,000,000,000 -> 1,000,000,000`, an 80% understatement, returned as a
real number with no flag. The other three degrade to a missing value, which is defensible.

Filed as new work, because the worst part is not a silent no-op at all -
`bfinance .scratch/verification-2026-09-28/issues/06-enterprise-value-silently-wrong.md`:
`ticker.py:651` `cash_cr = 0.0` is unconditional, so **EV is overstated by the full cash balance
for every net-cash company, always**, exception or no exception. `borrow_cr = ... or 0.0` at `:649`
has the mirror problem: a debt-free company and a failed debt parse are indistinguishable.
