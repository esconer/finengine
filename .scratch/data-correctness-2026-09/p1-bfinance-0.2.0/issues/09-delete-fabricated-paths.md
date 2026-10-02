# 09 — Delete the fabricated data paths

Status: needs-info
Type: task
Phase: 1
Blocked by: —
Repo: `C:\es\coding\bfinance`
Severity: **HIGH**

## What

Three places return invented or structurally-wrong values where they should return nothing.

### a) `Sector.top_companies` is 40 lines of hardcoded literals

`src/bfinance/sector.py:9-54` (`INDIAN_SECTOR_MAP`), surfaced at `:78-82`

The entire "live" sector explorer is literals. Verified:
```
bf row0: {'symbol':'TCS','name':'Tata Consultancy Services','cmp':3950.0,'market_cap_cr':1420000}
yf row0: {'name':'NVIDIA Corporation','rating':'Strong Buy','market weight':0.174}
```

`bf.Sector('technology').top_companies` returns TCS at a fixed price and market cap forever. This
is fabricated market data in a drop-in replacement, and it directly contradicts the "never
fabricate" principle the rest of the codebase advertises.

Related: `Industry.top_companies` delegates to `Sector` (`sector.py:102-105`) and is empty for any
key outside the 4-entry map, so ~95% of industries return `(0,0)`. And the column names differ
from yfinance's (`[symbol, name, cmp, market_cap_cr, pe]` vs `[name, rating, market weight]`).

### b) Failed resolution yields `currentPrice = 0.0`

`src/bfinance/ticker.py:82-86` (empty `CompanyProfile` fallback) + `market/quotes.py:112`
```python
cmp = r.current_price or latest_price or 0.0
```

A 404 or blocked symbol produces a full-looking `info` dict with `currentPrice: 0.0`,
`quoteType: 'EQUITY'`, `exchange: 'NSE'`. A portfolio aggregator sums market caps and gets a
silent `0.0` contribution rather than an error. yfinance either raises or omits the key.

### c) `history_metadata` contains fabricated constants

`src/bfinance/ticker.py:556,562-563`
- `firstTradeDate` hardcoded to `1112328000`
- `chartPreviousClose = previousClose = cmp * 0.995` — a fabricated constant that happens to sit
  inside the 0.9954 dividend factor measured in issue 03
- `range` hardcoded `"1y"` regardless of the actual `history()` call
- `tradingPeriods: []`

`market/quotes.py:289` has an honest `build_history_metadata()` that computes `firstTradeDate`
from the actual history — but `Ticker.history_metadata` **does not call it**, so the correct
implementation is dead code.

## Why

This is the library's most direct violation of its own stated principle. In a risk terminal, a
hardcoded price that never moves is worse than an error, because nothing downstream can detect it.

## Proof of done

- [ ] No hardcoded price or market-cap literal remains in `sector.py`. Grep confirms.
- [ ] `Sector.top_companies` is either sourced live from the screener.in sector/index pages (the
      same `/market/` taxonomy `parser.py:156` already walks) or the module is explicitly
      documented as a static sample and its output is labelled as such in the return type.
- [ ] Column names match yfinance's, or the divergence is documented in the capability matrix.
- [ ] `Industry.top_companies` returns a diagnosable empty state rather than `(0,0)` for an
      unknown key.
- [ ] An unresolved symbol yields `currentPrice = None` plus a `_resolution_failed` flag, never
      `0.0`. A test asserts this for a known-dead symbol.
- [ ] `history_metadata` is computed by `quotes.build_history_metadata()` from the actual history.
      `firstTradeDate`, `range`, and `chartPreviousClose` are all real values.
- [ ] The dead `build_history_metadata()` implementation is now live, and its coverage reflects
      that.
- [ ] `history_metadata['range']` matches the requested period. A test asserts it for at least
      three different periods.

## Notes

Decision needed from the owner on `sector.py`: **delete it, or make it live.** The master spec's
Open Questions #2 flags this. Deleting is cleaner; making it live is more useful. Do not extend it
as-is either way.

Refs: `../spec.md`, `sector.py:9-54,78-82,102-105`, `ticker.py:82-86,556,562-563`, `market/quotes.py:112,289`

## Verification correction (2026-09-28)

**CONFIRMED, with one dead-code residue.** Verified at `98463d9` by execution, using an AST sweep
rather than grep.

`sector.py` is gone: `importlib.import_module("bfinance.sector")` and `"bfinance.sectors"` both
raise `ModuleNotFoundError`, and `git log -- "*sector.py"` shows the removal at `481d17d`
("delete invented data rather than ship it as real"). The only `sector*.py` in the tree is
`trendlyne/sectors.py`, a different and real module added at `98463d9`.

`generate_option_chain` raises unconditionally (`market/derivatives.py:131-135`) with a message
naming the prior fabrication, and **no test asserts it returns data** - both call sites assert the
raise: `tests/test_dropin_actions.py:175-176` and
`tests/test_exhaustive_screener_and_yfinance.py:373-374`, the latter commented "The fabricator must
stay deleted".

**Fabrication sweep over `src/bfinance/` (AST, not grep): 0** large hardcoded financial numbers in
any assign/return/dict value. The 38 company-ticker string literals are all in
`screens.py:53-62` `DEFAULT_UNIVERSE` - a 50-symbol scan list carrying no financial values, so not
a fabrication. Sentinels: `*1.002 / *0.998` only at `ohlcv.py:965-966` (the flagged opt-in
synthetic path); `*0.995` only inside a docstring at `ticker.py:610` describing the fixed defect;
0 `np.random.seed`; 0 hardcoded `100000` portfolio totals. All 19 RNG hits are User-Agent rotation,
pacing jitter and backoff.

**Residue:** `derivatives.py:68-71` `_contract_rng` - the seeded generator that used to produce
`volume`/`openInterest` - **still exists** as a classmethod with **zero callers** in `src/` and
`tests/`. It cannot fabricate anything today, but the engine was left in the tree while its only
caller was removed, and `hashlib`/`random` exist solely to serve it. Filed as
`bfinance .scratch/verification-2026-09-28/issues/05-derivatives-dead-fabricator-and-false-docstring.md`,
together with a module docstring at `derivatives.py:6-9` that still advertises the deleted
fabrication as live and cites a resolved `NEEDS-MAIN`.
