# 14 — Close the yfinance parity surface gaps

Status: needs-info
Type: task
Phase: 1
Blocked by: 04
Repo: `C:\es\coding\bfinance`
Severity: **MEDIUM** — the 1:1 claim is the product's core promise

## What

yfinance 1.7.0 exposes **98** public `Ticker` members. bfinance has **33**. 65 are missing.
`info` carries 86 keys against yfinance's 163 — **102 missing**.

The README/docstring claim "180+ key metrics dictionary". That claim is currently false.

## Priority gaps, by consumer impact

### Tier 1 — trivially derivable, commonly used

| Surface | Note |
|---|---|
| `isin` | Trivially derivable (`IN000000…` or the exchange pattern). Used for de-duplication in most portfolio apps, including the consuming one |
| `shares`, `shares_full`, `get_shares*` | Derivable from the statements bfinance already parses |
| `get_*` explicit-accessor aliases (16) | `get_info`, `get_fast_info`, `get_dividends`, `get_splits`, `get_actions`, `get_incomestmt`, `get_balancesheet`, … A consumer using the accessor style `AttributeError`s. yfinance deprecates these in favour of properties, so priority is low-medium — but they are public API |

### Tier 2 — currently a hard crash

| Surface | Current | Should be |
|---|---|---|
| `ttm_income_stmt`, `ttm_cash_flow` | `raise NotImplementedError` (`ticker.py:285,320`) | empty DataFrame |
| quarterly `balance_sheet`, `cash_flow` | `raise NotImplementedError` (`:295,311`) | empty DataFrame |

A consumer doing `t.quarterly_balance_sheet` gets an exception on a path yfinance serves. An
exception is worse than an empty frame, because the caller has no way to distinguish "not
supported" from "no data".

### Tier 3 — `info` keys most likely to be read

`grossMargins`, `profitMargins`, `operatingMargins`, `ebitdaMargins`, `totalRevenue`,
`grossProfits`, `ebitda`, `totalCash`, `totalDebt`, `enterpriseValue`, `enterpriseToEbitda`,
`lastDividendValue`/`Date`, `lastSplitDate`/`Factor`, `exDividendDate`, `dividendRate`,
`trailingAnnualDividendYield`, `payoutRatio`, `52WeekChange`, `fiftyTwoWeekRange`,
`allTimeHigh`/`Low`, `averageVolume`, `averageVolume10days`, `averageDailyVolume3Month`, `bid`,
`ask`, `bidSize`, `askSize`, `marketState`, `regularMarketTime`, `regularMarketChange(Percent)`,
`regularMarketDayRange`, `epsTrailingTwelveMonths`, `epsForward`, `priceEpsCurrentYear`,
`targetHigh`/`Low`/`Mean`/`MedianPrice`, `recommendationKey`, `recommendationMean`,
`numberOfAnalystOpinions`, `averageAnalystRating`, `executiveTeam`, `companyOfficers`,
`mostRecentQuarter`, `lastFiscalYearEnd`, `nextFiscalYearEnd`, `sectorDisp`, `industryDisp`,
`typeDisp`, `region`, `firstTradeDateMilliseconds`, `exchangeDataDelayedBy`, `corporateActions`.

Most are derivable from the tables bfinance already parses.

### Tier 4 — module-level functions

Missing: `yf.fundamentals_timeseries` (a real gap for anyone building factor tables), `yf.Search`,
`yf.Lookup`/`lookup`/`search`, `yf.calendars`/`Calendars`, `yf.Market`/`MarketRegion`.

`ScreenerClient.search()` exists but is **not exported at module level**.

### Out of scope, state explicitly

`yf.screen`/`EquityQuery`/`ETFQuery`/`FundQuery`/`PREDEFINED_SCREENER_QUERIES` — bfinance ships
`bf.Screen`/`bf.screens`, a completely different concept (fixed 50-symbol universe, 5 hardcoded
predicates, no query DSL). A consumer using `yf.EquityQuery` must rewrite, not swap. Document
this as a known divergence rather than pretending parity.

`yf.live`/`WebSocket`/`AsyncWebSocket` — streaming parity out of scope. Say so.

## Proof of done

- [ ] A parity test walks yfinance's public `Ticker` members and asserts bfinance's coverage,
      reporting any remaining gap. The test is **informational for known-divergent members** (a
      documented allowlist) and **fatal for regressions** (a member that used to exist and no
      longer does).
- [ ] `isin`, `shares`, `shares_full` are present and correct for at least 5 tickers, including
      one `.BO` ticker.
- [ ] `t.quarterly_balance_sheet` and `t.ttm_income_stmt` return empty DataFrames, not exceptions.
- [ ] The 16 `get_*` aliases exist and delegate to their properties.
- [ ] The Tier 3 `info` keys are present, or each omission is listed with the reason.
- [ ] `ScreenerClient.search` is exported at module level.
- [ ] The README and the `Ticker` docstring state the **actual** coverage, and the divergence
      list (query DSL, streaming, analyst estimates) is published rather than glossed.
- [ ] `fast_info` implements the Mapping protocol (`keys`/`values`/`items`/`get`/`toJSON`) and
      gains `regular_market_previous_close`, `ten_day_average_volume`,
      `three_month_average_volume`, `year_change`. Currently `dict(t.fast_info)` and
      `t.fast_info.keys()` both break.
- [ ] `Tickers.tickers` dict keys: decide whether to match yfinance's verbatim (`"RELIANCE.NS"`) or
      keep normalization (`"RELIANCE"`), document the choice, and make `Tickers.__getitem__` work
      either way.

## Notes

This is the "1:1 drop-in replacement" promise. Either honour it or state precisely where it does
not hold. The current README overstates it.

Refs: `../spec.md`, issue 04, `ticker.py:285,295,311,320,360,365`, `fast_info.py`, `tickers.py`

## Verification correction (2026-09-28)

**PARTIALLY satisfied, and the framing needs correcting on two points.** Verified by execution at
commit `98463d9`; no network call was made, so anything requiring a live yfinance read is marked.

**The `NotImplementedError` sites are real but are not five equal gaps.** Five raises confirmed at
`src/bfinance/ticker.py` lines 283, 294, 306, 340, 375 - line numbers exact.

| line | member | kind | measured behaviour |
|---|---|---|---|
| 283 | `get_income_stmt` | **conditional** fallback | **returned a DataFrame (12, 2)** - does not raise |
| 294 | `get_balance_sheet` | unconditional on `freq != "yearly"` | raises |
| 306 | `get_cash_flow` | unconditional on `freq != "yearly"` | raises |
| 340 | `ttm_income_stmt` (**property**) | unconditional | raises |
| 375 | `ttm_cash_flow` (**property**) | unconditional | raises |

**Present-but-unwired, and cheaper than this ticket assumes.** `_parse_table_section(soup,
"quarters")` (`screener/parser.py:303`, called at `:86`) already populates `CompanyProfile.quarters`,
and the same field is **already shipped through two other doors** - `ai/context.py:146` and
`utils/excel.py:57` both read `profile.quarters`. So quarterly income data is parsed, exported to
Excel and fed to the AI context, while `get_income_stmt(freq="quarterly")` and the
`quarterly_income_stmt` / `quarterly_financials` properties *also* work. The raise at 283 fires only
when the section is absent from the page.

**Lines 340/375 are TTM, not quarterly, and their message is factually wrong.** Both say
`"quarterly statements not supported"`, which is false about them. The TTM data **is** present:
`profit_loss.headers == ['Mar 2026', 'TTM']` on the recorded page, pinned at
`tests/test_screener_offline.py:482`.

**Genuinely absent:** lines 294/306 have no model field and no parser branch. Whether screener.in
*publishes* quarterly balance sheet / cash flow **cannot be established offline** - the fixture is
trimmed (`META.json`: "columns cut to the trailing 2 period columns") and the retained tails are
`['Mar 2025','Mar 2026']`, the **annual** fiscal-year tail. Suggestive, not dispositive. Probe
before scoping that half.

**The "so" in the parity argument is a non-sequitur - drop it.** The claim was that 65 missing
`Ticker` members cannot be added by copying yfinance's semantics *because* of the demerger divisor.
The 65 is exact (yfinance 1.7.0 `TickerBase` + `Ticker` public members, minus bfinance's), but an
AST walk of `ticker.py` shows:

```
bfinance Ticker members that raise NotImplementedError:
  ['get_balance_sheet','get_cash_flow','get_income_stmt','ttm_cash_flow','ttm_income_stmt']
...of which yfinance also has  : all 5
...which are in the 65-missing set: []      <- EMPTY
```

The 65 are **absent-name** members (`earnings_dates`, `get_analyst_price_targets`,
`insider_transactions`, `get_institutional_holders`, `recommendations`, `get_news`, ...). They are
missing because bfinance has **no upstream source** for them - Yahoo quoteSummary, news, analyst
feeds. The demerger divisor constrains `Ticker.history()`, which is **already present**. Do not
present the 65 as a consequence of the demerger finding; they are a separate sourcing problem.

**So ticket 14 splits in two:** an unwiring job for income-statement-quarterly and TTM (the data is
already there), and a genuine build for balance-sheet/cash-flow-quarterly (needs a live probe
first).
