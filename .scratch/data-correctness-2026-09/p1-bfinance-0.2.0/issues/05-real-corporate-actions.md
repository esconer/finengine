# 05 — Real corporate actions; delete the equity-capital heuristic

Status: needs-info
Type: task
Phase: 1
Blocked by: 03
Repo: `C:\es\coding\bfinance`
Severity: **CRITICAL**

## What

`src/bfinance/market/corporate.py:106-119` infers splits from the **ratio of Equity Capital**
between fiscal years. Any ≥1.5× rise is recorded as a split at `ratio = capital_ratio`, dated at
fiscal year-end.

Delete the heuristic. Parse real corporate actions.

## Why

The heuristic fires on rights issues, QIPs, preferential allotments, and share-swap mergers — not
just bonus issues. And the "ratio" is a money amount, not a split ratio.

Verified live against real companies:

```
IDEA     SPLITS -> {'2019-03-31': 2.0,  '2020-03-31': 3.29, '2023-03-31': 1.52, '2026-03-31': 1.52}
YESBANK  SPLITS -> {'2020-03-31': 5.42, '2021-03-31': 2.0}
SUZLON   SPLITS -> {'2021-03-31': 1.6}
```

**Vodafone Idea has never had a single split or bonus issue.** All four are share-issuance
artifacts. These land in `Ticker.actions` and as non-zero `Stock Splits` cells in `history()`, so
any consumer filtering `actions != 0` — or computing split-adjusted returns — gets fabricated
corporate actions.

Second defect in the same area: dividend **amounts** are derived as `payout% × EPS` and dated at
**fiscal year-end** rather than the real ex-date (`:80`, self-documented at `:5-8`). A 4–5 month
ex-date lag drops dividend accrual from the return path, understating return and volatility and
corrupting drawdown and compounding in the consuming app's tear-sheet and Monte Carlo.

## Proof of done

- [ ] `bf.Ticker("IDEA").splits` returns an **empty** series.
- [ ] `bf.Ticker("YESBANK").splits` contains no fabricated entries.
- [ ] `get_splits()`, `get_actions()`, and `history()["Stock Splits"]` all agree with each other
      and with the real corporate-action record.
- [ ] Dividend ex-dates match the real ex-date, not fiscal year-end. At least 3 known cases
      verified against NSE.
- [ ] The equity-capital-ratio code is deleted, not merely bypassed. No dead heuristic remains.
- [ ] A test asserts a rights-issue or QIP event does **not** produce a split row.
- [ ] `ohlcv.py:210-213` — the `except` that silently substitutes `Dividends=0.0, Stock Splits=0.0`
      when corporate actions are unavailable is either removed or covered by a test. It is
      currently the blast radius of this bug and is explicitly untested.
- [ ] A new `Ticker.corporate_actions()` (or equivalent) exposes the real action stream with
      ex-dates, so the consuming app can build a proper corporate-action ledger
      (Phase 5 issue 12).

## Notes

Source options, in order of preference: NSE's corporate-announcements JSON
(`nseindia.com/api/corporate-announcements?index=equities&symbol=X`, verified HTTP 200 without
special handling), or the `Bonus` and `Split` rows in screener.in's quarters/documents sections.
NSE's per-scrip `PR.zip` bhavcopy has no fixed schema and is a weaker option.

Refs: `../spec.md`, issue 03, `market/corporate.py:5-8,80,106-119`, `market/ohlcv.py:210-213`

## Verification correction (2026-09-28)

**PARTIALLY satisfied. bfinance can still fabricate splits, and it is reachable from the default
`history()` path.** This ticket was reported as done. It is not, and this is the most consequential
correction in the verification pass.

### What was fixed, and is confirmed

The NSE corporate-filings feed supplies real splits. `_BONUS_RE` (`nse/corporate_actions.py:360`),
`_SPLIT_KEYWORD_RE` (`:380-383`) and the from/to amount regexes (`:384-387`) are in place;
`uv run pytest tests/test_nse_corporate_actions.py -q` -> 130 passed. Splits arrive as
`Bonus a:b` and `Face Value Split (Sub-Division)`, never as a bare "Split".

**And the demerger cannot leak into the split column** (this was the worry, and it is refuted
structurally, not just empirically):

1. `split_ratio()` (`corporate_actions.py:772-796`) calls only `parse_bonus_ratio` and
   `parse_subdivision_ratio`; it never consults `structural_action_kinds`.
2. `actions_frame` gates at `:942` on `PRICE_AFFECTING_ACTIONS = ('bonus','subdivision')` (`:255`);
   `Demerger` parses to `OTHER_ACTION`.
3. Audit of 207 distinct fixture subjects: **0** are both structural and carry a `SplitRatio`.
   `"Demerger"` -> `kinds=('demerger',)`, `ratio=None`, `action=other`, `Stock Splits == 0.0`.

### What is still broken

`market/corporate.py:141-163`, `CorporateActionsEngine.extract_splits`:

```python
151:  equity_map = bs.get_metric("Equity Capital")
157:  if curr_cap and prev_cap and prev_cap > 0:
158:      ratio = curr_cap / prev_cap
160:      if ratio >= 1.5:
163:          splits_records[dt] = round(ratio, 2)
```

Equity-capital growth is still converted into a "split" with **no split filing required** - a
capital raise reads as a bonus issue. Executed on a balance sheet whose equity rose 4505 -> 23700 Cr:
`{2026-03-31: 5.26}`.

**It is reachable from the default path.** `ohlcv.py:626` calls `resolve_actions_async(...)` with
**no `fallback=` argument**; the parameter default is `"screener"` (`corporate.py:380`); and
`:459` is `splits = cls.extract_splits(profile)`. So when the NSE feed returns no rows for a symbol
- the documented containment at `corporate.py:447-450` - the default `ohlc="bhavcopy"` path falls
through to the fabrication.

**End to end, executed.** Fabricated `Stock Splits` of `5.26` written into the user-visible column,
**and** every prior bar silently rescaled by 1/5.26 (`10.0` -> `1.901141`), while the frame reports:

```
attrs['bfinance_actions_source']            = screener_fy_end_approximation
attrs['bfinance_corporate_actions_applied']  = True
attrs['bfinance_synthetic_ohlc']            = False
```

i.e. "real bars, complete adjustment". A `logger.warning` does fire, but the frame's own provenance
flags claim completeness. And when the fabricated month-end date falls outside the bar window the
column reads `0.0` while **the price rescaling still happens** - verified separately.

**This is the ticket's own finding, still live.** "Vodafone Idea reports 4 fabricated splits, never
having had one" describes exactly this code path. The fix went into the NSE feed; the screener
fallback was not touched. Ticket 05 should be **re-opened**, not closed.

Also confirmed: no price-jump inference. `unexplained_price_jumps` (`corporate_actions.py:985`) is a
pure reporter with zero `src/` callers.
