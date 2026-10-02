# 03 — Real OHLCV from the NSE CM bhavcopy

Status: ready-for-agent
Type: task
Phase: 1
Blocked by: 01, 02
Repo: `C:\es\coding\bfinance`
Severity: **CRITICAL — root cause RC1**

## What

Replace the fabricated OHLC with real bars from the NSE CM bhavcopy.

Current code, `src/bfinance/market/ohlcv.py:189-194`:
```python
Open = prev_close.shift(1).bfill()
High = max(O, C) * 1.002
Low  = min(O, C) * 0.998
```

`Adj Close == Close` unconditionally at `:186`. bfinance already flags this itself at
`:165` and `:249` with `df.attrs["bfinance_synthetic_ohlc"] = True`.

Measured against real yfinance on `RELIANCE.NS`, 1 year, default `auto_adjust=True`:

```
mean abs err % vs yfinance:  Open 0.563 | High 0.406 | Low 0.595 | Close 0.314 | Volume 7.087
```

## Why

This is not an approximation problem. A `max/min` envelope is **mathematically incapable** of
representing a real intraday range, so ATR, true range, gap detection, `(High-Low)/Close`,
candlestick logic, and Parkinson/Garman-Klass volatility all get synthetic numbers that cannot be
recovered by any downstream correction.

It is also the single fix that repairs the most pages in the consuming app at once. Every
quantitative page there — realized-risk, forecast-risk, risk-studio, volatility-sizing,
liquidity, stress-testing, pairs, tear-sheet — currently computes on this invented path, and the
app never reads the `bfinance_synthetic_ohlc` flag bfinance sets.

`auto_adjust=True` is a separate defect in the same area: it is a no-op column drop, not an
adjustment. yfinance's real rescale factor was measured at 0.9954; bfinance's frames are
byte-identical either way.

## Acceptance

```python
# src/bfinance/nse/bhavcopy.py
def bhavcopy(date: str | date, *, series: str = "EQ",
             exchange: Literal["CM", "FO"] = "CM",
             raise_errors: bool = False) -> pd.DataFrame
    """Truthful EOD bars. Sets attrs['bfinance_synthetic_ohlc'] = False.
    Dispatches on the pre/post 08-Jul-2024 UDiFF vs legacy schema."""

def bhavcopy_range(start: str, end: str, *, exchange: Literal["CM", "FO"] = "CM",
                   on_missing: Literal["skip", "raise"] = "skip",
                   progress: bool = False) -> pd.DataFrame
```

- The fetcher uses the static ZIP route confirmed in Phase 0 issue 01. It must require **no**
  cookie and no API key. Port bfinance's existing global pacing design from
  `screener/client.py:100-121`.
- The parser dispatches on schema, not on "works today". Two schemas exist.
- `Ticker.history()` returns the real frame and sets
  `attrs["bfinance_synthetic_ohlc"] = False`.
- The synthetic path is retained but gated behind an explicit `ohlc="synthetic"` opt-in, so a
  consumer depending on the old behaviour gets a loud signal rather than a silent shape change.
- `auto_adjust=True` is either implemented with real adjustment factors or **rejected**, and
  `auto_adjust=False` becomes the default. Rejecting is acceptable; silently mislabelling is not.
- `history_metadata['chartPreviousClose'] = cmp * 0.995` (`ticker.py:562`) is removed — it is a
  fabricated constant that happens to land inside the 0.9954 factor.

## Proof of done

- [ ] 20 tickers × 1 year: bfinance vs yfinance mean absolute error **≤ 0.01%** on
      open/high/low/close.
- [ ] ATR and Parkinson volatility computed from bfinance bars fall within 1% of the same
      computation on yfinance bars. (This is the test that proves the envelope problem is gone,
      not just the mean error.)
- [ ] `attrs["bfinance_synthetic_ohlc"]` is `False` on a real frame and `True` on a synthetic one.
- [ ] `ohlc="synthetic"` is required to get the old behaviour, and requesting the default without
      the bhavcopy available raises a typed error rather than silently fabricating.
- [ ] A pre-2024-08-07 date and a post date both parse, exercising both schema branches. A test
      fixture for each is committed.
- [ ] A weekend/holiday date yields no row without raising.
- [ ] `bhavcopy_range` over a 6-month window returns the correct trading-day count for the NSE
      calendar, verified against a known holiday list.
- [ ] `auto_adjust=True` either produces a frame whose close differs from `auto_adjust=False` by
      the true dividend/split factor, or raises. It is never a silent no-op.
- [ ] `Ticker("IDEA").history()` carries the real `Stock Splits` column, not the fabricated values
      from issue 04.

## Notes

Phase 0 issue 01 determines whether this is S or a different design. If the bhavcopy route turns
out to be unreachable, stop and re-scope.

### MarketLens is not a substitute for this — verified, and it matters

NSE also operates a second official frontend API, MarketLens, which was probed on 2026-09-26 and
added as issue 22:

```
https://marketlens.nseindia.com/api/stocks/{SYMBOL}/price-history?period={PERIOD}
```

It is **30 years deep** (`30Y` = 8,069 rows from 1996-09-30), **needs no auth at all**, and its
close and volume are **exact** — verified 8/8 against yfinance on both fields.

**It returns no O/H/L.** Row keys are exactly `['date', 'price', 'volume']`, the same shape
limitation as screener.in charts. So it cannot satisfy this ticket, and the bhavcopy remains the
only free source of real `OpnPric / HghPric / LwPric`.

The division of labour is:

| Need | Source |
|---|---|
| Real O/H/L/C/V daily | **bhavcopy (this ticket)** |
| Authoritative close + volume, 30Y, zero anti-bot | issue 22, MarketLens |
| Detect a vendor returning a wrong close | Phase 2 issue 21, reconciliation |

**Do not let a MarketLens frame be coerced into the OHLCV shape.** Filling `open`/`high`/`low` from
a close-only frame to satisfy an existing contract recreates the exact bug this ticket exists to
fix. Issue 22 sets `attrs["bfinance_marketlens_partial_coverage"] = True` on every frame so that mistake is
detectable rather than silent.

One useful side effect if this ticket lands first: the bhavcopy's `ClsPric` and `TtlTradgVol` can
be validated directly against MarketLens `price` and `volume`, which is a strong correctness check
on the CSV parser across both the pre- and post-2024-08-07 schemas.

Refs: `../spec.md`, Phase 0 issue 01, Phase 1 issue 22, Phase 2 issues 01, 02, 21, bfinance `ohlcv.py:50-53,165,186,189-194,249`

## Verification correction (2026-09-28)

**CONFIRMED - this ticket's goal is met.** Verified at `98463d9` by execution.

`src/bfinance/market/ohlcv.py:445` - `ohlc: Literal["bhavcopy", "synthetic"] = "bhavcopy"`, with
`OHLC_SOURCES = ("bhavcopy", "synthetic")` and anything else raising `ValueError` at `:520-521`.
The same default is confirmed on all three public surfaces: `OHLCVEngine.fetch_history`,
`Ticker.history`, `Ticker.history_async`.

**The verification test is a real check, not a tautology.** The legacy envelope was reconstructed
over the same closes and its maximum attainable High is `117.735`; the test asserts `118.0`. An
`Open = prev_close`, `High/Low = max/min(O,C) +/- 0.2%` construction is arithmetically incapable of
producing that, so the assertion discriminates. Corroborated by
`test_default_path_never_touches_the_close_only_screener`, which asserts
`screener.chart_calls == []`. `uv run pytest tests/test_nse_bhavcopy_wiring.py -q` -> 29 passed.

**One thing the ticket does not say, worth knowing.** The fabricator is not removed, it is
**retained behind an explicit opt-in**: `ohlcv.py:965-966` still computes `*1.002` / `*0.998`, and
`test_synthetic_path_is_retained_behind_explicit_opt_in` asserts the envelope is exactly
`[100.2, 102.204]`. Every frame carries `bfinance_synthetic_ohlc`, so this is honest - but anyone
auditing the repo for the +/-0.2% envelope will find it in the tree, and a test pins it.

**Residual, filed as new work** -
`bfinance .scratch/verification-2026-09-28/issues/07-bhavcopy-helper-returns-unflagged-frame.md`:
`ohlcv.py:1055` *strips* `bfinance_synthetic_ohlc` from the private `_fetch_bhavcopy_bars` return
value. Latent only - the helper has one caller, `:574`, which re-stamps at `:791-794`, and the
invariant "present on every frame a caller can obtain" was verified across 15 public paths. But the
contract finengine `p2-01` depends on currently holds by re-stamping, not by construction.
