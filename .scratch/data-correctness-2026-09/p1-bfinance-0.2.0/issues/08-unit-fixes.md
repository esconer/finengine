# 08 — Unit fixes: ROCE, dividend yield, `or`-chains, BSE exchange

Status: ready-for-agent
Type: task
Phase: 1
Blocked by: —
Repo: `C:\es\coding\bfinance`
Severity: **HIGH** — four 100×-class errors, all mechanical

## What

Four independent unit/identity defects, all of which produce 100× errors or silently wrong
identity in data a consumer reads directly.

### a) Three conventions in one dict

`src/bfinance/market/quotes.py:246` sets `returnOnCapitalEmployed = r.roce` (raw, percent) while
`:244` sets `returnOnEquity = r.roe / 100.0` and `:245` sets `returnOnAssets` as a fraction.

Measured on one dict:
```
info[returnOnEquity]            = 0.0891     (fraction)
info[returnOnAssets]            = 0.0405     (fraction)
info[returnOnCapitalEmployed]   = 10.3       (PERCENT — 100x off)
```

yfinance's convention is fractions throughout (verified: `yf.Ticker('AAPL').info['returnOnEquity']
== 1.4875`). A consumer charting ROE against ROCE gets a 100× discontinuity.

Same class of error in `Ticker.enterprise_value` (`ticker.py:498`, `enterprise_value_cr` is in
₹ Cr while yfinance's `info['enterpriseValue']` is in ₹).

### b) `or`-chains convert a genuine `0.00` into `None`

`src/bfinance/screener/parser.py:203,209,211`
```python
raw_ratios.get("Stock P/E") or raw_ratios.get("P/E")
```

When screener.in legitimately reports `0.00`, `0.0` is falsy so the chain falls through to a
non-existent key and yields `None`. Same for `Debt to equity` and `Price to book value`.

Verified consequence: **INFY, HDFCBANK, and TCS all report `info['debtToEquity'] = None`** — they
are the canonical zero-debt names. `screens.debt_free_compounders` has to carry a `custom_ratios`
fallback (`screens.py:178-182`) to work around the symptom.

Worse, the raw `0.0` survives in `custom_ratios` and is then injected into `info` at
`quotes.py:282-284`, so **the same dict reports the same metric twice with contradictory values**.

### c) `Screen` output column and filter threshold both off by 100×

`src/bfinance/screens.py:115` — `DivYield_% = dividendYield * 100`
`src/bfinance/screens.py:216-218` — `dy >= 0.025`

`info['dividendYield']` is already percent (0.49 = 0.49%), matching yfinance 1.7.0. But
`screens.py:7-8` documents the contract as *"info holds decimals (0.15 -> 15.0)"* — **the contract
is false**. So `DivYield_%` reports **49.0% for a 0.49% yield**.

And `high_dividend_yield` compares a percent value against a decimal threshold, so its real
cut-off is 0.025% — **the filter is a no-op that passes every dividend payer** in
`DEFAULT_UNIVERSE`.

ROE is handled correctly (`×100` on a fraction), which is why the bug is invisible in casual use.

### d) BSE tickers report NSE identity

`src/bfinance/ticker.py:43` strips the suffix into `self.exchange`/`self.symbol`, then
`market/quotes.py:199` and `:203` re-derive both **from the already-bare `profile.symbol`**, so
the exchange is lost.

```
Ticker('RELIANCE.BO').info['symbol']   -> 'RELIANCE.NS'   (yfinance: 'RELIANCE.BO')
Ticker('RELIANCE.BO').info['exchange'] -> 'NSE'          (yfinance: 'BSE')
```

A consumer that round-trips `info['symbol']` — re-fetch, persist, dedupe, log — silently relabels
every BSE holding as NSE. Same defect in `FastInfo.exchange` (`fast_info.py:31`).

## Proof of done

- [ ] All three RO* keys in one `info` dict use the same convention (fractions, matching
      yfinance). A test asserts the three are mutually consistent.
- [ ] `enterprise_value` is in ₹, matching yfinance. The `_cr` variant keeps the ₹ Cr name.
- [ ] `INFY`, `HDFCBANK`, and `TCS` report `debtToEquity == 0.0`, not `None`.
- [ ] `info` does not report the same metric twice with contradictory values. A test asserts
      `info` and `custom_ratios` agree wherever both carry a key.
- [ ] `Screen` `DivYield_%` reports 0.49 for a 0.49% yield.
- [ ] `high_dividend_yield` **actually filters** — a test asserts a known non-dividend payer is
      excluded and a known high-yield name is included.
- [ ] `Ticker('RELIANCE.BO').info['symbol'] == 'RELIANCE.BO'` and `['exchange'] == 'BSE'`.
- [ ] `Ticker('RELIANCE.NS').info['exchange'] == 'NSE'`.
- [ ] The false contract comment at `screens.py:7-8` is corrected to state the real convention.
- [ ] A `_first_not_none(*values)` helper is used throughout rather than `or`-chains on numeric
      fields. Grep confirms no `or` chain remains on a ratio/price/percentage lookup.

## Notes

All four are cheap and independent. Safe to split into four PRs if that ships faster.

Refs: `../spec.md`, `market/quotes.py:199,203,244-246,282-284`, `screener/parser.py:203,209,211`, `screens.py:7-8,115,178-182,216-218`, `ticker.py:43,498`, `fast_info.py:31`

## Verification correction (2026-09-28)

**PARTIALLY satisfied, and the ROCE/ROE attribution in this ticket is backwards.** Verified at
`98463d9` by execution.

### ROCE/ROE - the ticket has the wrong key

The ticket says ROCE is a percent while ROE/ROA are fractions in the same dict. Measured:

- **`roa` is not a `TopRatios` field at all.** It is computed in a different function,
  `quotes.py:155`, as `_np / _ta` - a true fraction, never in `TopRatios`.
- **Both `roce` and `roe` in `TopRatios` are percents**, and both descriptions say so correctly
  (`'Return on Capital Employed (ROCE %)'`, `'Return on Equity (ROE %)'`). Fixture check: ITC
  `roce=38.9 roe=29.3`; TCS `roce=63.0 roe=51.8`.
- Therefore `quotes.py:244` `(r.roe / 100.0)` is a **correct** percent-to-fraction conversion, not
  a bug - and it is what makes `screens.py:114` (`"ROE_%": r.get("returnOnEquity") * 100`) round-trip.
- **The unconverted key is `returnOnCapitalEmployed` at `quotes.py:246`:**

```python
244:  "returnOnEquity":          (r.roe / 100.0) if r.roe else None,   # fraction
245:  "returnOnAssets":          _roa,                                 # fraction
246:  "returnOnCapitalEmployed": r.roce,                               # RAW PERCENT
```

So the mixed-unit contract the ticket describes is real, but it is **ROCE that is unconverted** -
the opposite of the ticket's claim - and it is *knowingly* documented at `screens.py:6` ("ROCE_% is
raw percent") and `screens.py:94`, then consumed at `:113-114`. Fixing it is a contract decision
with a downstream consumer, not a bug hunt.

**Real residual bug on that line:** `if r.roe` maps a genuine ROE of `0.00` to `None`.

### The `0.00`-orphaned `or` chains - CONFIRMED, and there are three, not one

`screener/parser.py:244` is verbatim as the ticket says. Proved by running the real parser on a
constructed `#top-ratios` fragment:

```
A genuine 0.00, no alias key       -> None     raw['Debt to equity']=0.0
B non-zero 7.77                    -> 7.77
C genuinely ABSENT (li removed)    -> None     raw['Debt to equity']=0.0
D genuine 0.00, alias = 7.77       -> None
A vs C identical? True
```

A genuine `0.00` and a genuinely absent value are **byte-identical to the consumer**. Note row D:
with the alias key present a real `0.00` is overridden by the alias's `7.77`, so it does not merely
vanish - it becomes a **different wrong number**. `custom_ratios` retains the `0.0`; only the typed
field is lost.

**Two more, same class, same function, not in the ticket:**
- `parser.py:238` `stock_pe=...get("Stock P/E") or ...get("P/E")` - `Stock P/E = 0.00` -> `None`
- `parser.py:246` `price_to_book=...get("Price to book value") or ...get("P/B")` - `0.00` -> `None`

The remaining `TopRatios` fields use a plain `.get()` and correctly preserve zero - measured
`dividend_yield=0.0, roe=0.0, peg_ratio=0.0, promoter_holding=0.0, promoter_pledged=0.0`.

Elsewhere: `quotes.py:239` is the same class but book values are never `0.00` in practice;
`quotes.py:241` uses `is not None` correctly; `parser.py:479` `int(rank_val) if rank_val else ...`
is safe because rank 0 is not a real rank.

### Already fixed

The screen threshold is corrected - `screens.py:216-223` was `0.025%` (which passed every dividend
payer) and the comment now records that.
