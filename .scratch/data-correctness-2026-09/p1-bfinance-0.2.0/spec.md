# Phase 1 — bfinance 0.2.0 (breaking)

Status: ready-for-agent
Repo: `C:\es\coding\bfinance`
Tickets: 20 | Release: breaking, 0.1.3 → 0.2.0
Gate: **issue 01 lands first.** The current suite certifies issues 06, 07, and 08 as correct.

## Release policy

Locked decision: **breaking release, 1:1 yfinance parity as the contract.** The native Indian
statement shape is removed from the yfinance-named accessors and preserved under explicitly
different names.

```python
bf.Ticker("RELIANCE.NS").income_stmt        # → to_yfinance() shape. BREAKING
bf.Ticker("RELIANCE.NS").get_income_stmt() # → same
bf.Ticker("RELIANCE.NS").income_stmt_indian()  # → native ₹ Cr / Indian labels. NEW
```

The pre-0.2.0 behaviour is not silently dropped; it is renamed. Anyone who depended on the native
shape has a one-token migration, which is the whole point of a breaking release done properly.

## What bfinance is today

A single-source Screener.in HTML/API scraper with a yfinance-compatible surface. The entire SDK
has exactly two upstream URLs:

- `https://www.screener.in` — `src/bfinance/screener/client.py:62`
- `https://www.screener.in/api/ratio/search/` — `src/bfinance/market/ratios.py:79`

There is no NSE, BSE, CDSL/NSDL, SEBI, RBI, AMFI, or NSE Indices code in the package. The
"Indian market superpowers" the README advertises are parsed out of one company's profile page.

## Ticket map

### Correctness — ship before anything else

| # | Ticket | Severity | Finding |
|---|---|---|---|
| 01 | Repair the test suite | **GATE** | The suite asserts `isinstance(c, str)` on statement columns and locks in the inverted period order as the contract |
| 02 | Record pre-flight results | — | Consolidates Phase 0's four answers into the master spec |
| 03 | Real OHLCV from NSE bhavcopy | CRITICAL | `Open=prev_close`, `High/Low=±0.2%` envelope. 0.4–0.6% mean error. Structurally incapable of representing an intraday range |
| 04 | Statement shape → yfinance | CRITICAL | Columns ascending vs yfinance descending. `iloc[:,0]` silently returns a 10-year-old period as current |
| 05 | Real corporate actions | CRITICAL | Splits inferred from the equity-capital ratio. **Vodafone Idea reports 4 fabricated splits** despite never having had one |
| 06 | Cache overhaul | CRITICAL | Per-call connection leak; unvalidated writes; 24h TTL on price data; no public refresh. A price can be up to 24h stale with no way to bust it |
| 07 | `resolve_company_id` exact match | CRITICAL | A typo returns **a different company's price history, cached under the right key** |
| 08 | Unit fixes | HIGH | ROCE is percent while ROE/ROA are fractions in the same dict; `Screen` dividend yield is 100× high and its threshold filter is a no-op; `or`-chains turn a genuine `0.00` into `None` so INFY/HDFCBANK/TCS report `debtToEquity=None`; `.BO` tickers report the wrong exchange |
| 09 | Delete fabricated paths | HIGH | `Sector.top_companies` is 40 hardcoded literals; an unresolved symbol yields `currentPrice=0.0`; `history_metadata` contains fabricated constants |
| 10 | Eliminate silent no-ops | HIGH | Unknown `period` silently returns 5 years; `session=`/`timeout=`/`ignore_tz=` accepted and discarded; `download` swallows every kwarg; a blanket `except` makes the error path dead code |
| 11 | Ragged-row padding | MED | A footnote cell in a screener table raises `ValueError` across 7 public properties |
| 12 | AI context markdown | MED | Blank lines are stripped, so **every table in every AI dossier renders as run-on pipes** |
| 13 | Screener error surfacing | MED | 403/429/5xx return `[]` instead of raising. The whole retry/backoff layer is untested |

### Parity surface and new capability

| # | Ticket | Effort | Note |
|---|---|---|---|
| 14 | yfinance parity gaps | M | 65 missing `Ticker` members, 102 missing `info` keys. `ttm_*`/quarterly BS-CF raise `NotImplementedError` instead of returning empty frames |
| 15 | `bfinance.nse.macro` | S | India VIX, index TRI/valuation, RBI reference rate. All key-free |
| 16 | `bfinance.costs` | S | Date-keyed statutory cost schedule. Replaces a 10bps constant where the real NSE delivery round-trip is ~22–23bps |
| 17 | `bfinance.flows` | S | FII/DII + AMFI. AMFI has no key, no cookie, no anti-bot |
| 18 | `bfinance.universe` | S/M | Nifty constituents + rebalance events. Kills survivorship bias |
| 19 | `bfinance.ownership` | M | Pledge history, FPI ownership, bulk/block deals. Keyed `(symbol, as_of, revision_date)` because NSE restates |
| 20 | `bfinance.derivatives` | M | Real option chain. Replaces SHA-256-seeded pseudo-random open interest |
| 21 | Licensing & provenance docs | S | bfinance is MIT and cannot grant rights it does not have |
| 22 | `bfinance.nse.marketlens` | S | **SHIPPED 2026-09-27.** NSE-official, zero auth, 30Y deep, close+volume exact. Close/volume only — *not* an OHLC substitute for issue 03 |

### Data-source division of labour

Three official NSE routes, verified live 2026-09-26. Complementary, **not** interchangeable.

| Source | Auth | Depth | Gives | Does **not** give |
|---|---|---|---|---|
| CM bhavcopy (03) | none, static ZIP | UDiFF from 2008-07-08 | **real O/H/L/C/V** | — |
| MarketLens (22) | **none at all** | **30Y, from 1996** | close + volume, **exact** | **no O/H/L** |
| `/api/*` (17, 19) | session cookie | varies | FII/DII, deals, filings | close — and `quote-equity` **403s from datacenter IPs** |

MarketLens is the only source in the entire spec with **zero anti-bot exposure**, which is why issue
21's provenance table records it as a distinct row.

**The invariant:** a close-only frame must never be coerced into an OHLCV shape. Issue 22 sets
`attrs["bfinance_marketlens_partial_coverage"] = True` so the mistake is detectable rather than silent —
making it would recreate the exact RC1 bug that issue 03 exists to fix.

## Recommended API shapes

```python
# nse/bhavcopy.py — issue 06
def bhavcopy(date: str | date, *, series: str = "EQ",
             exchange: Literal["CM", "FO"] = "CM",
             raise_errors: bool = False) -> pd.DataFrame
    """Truthful EOD bars. Sets attrs['bfinance_synthetic_ohlc'] = False.
    Dispatches on the pre/post 08-Jul-2024 UDiFF vs legacy schema."""

def bhavcopy_range(start: str, end: str, *, exchange: Literal["CM", "FO"] = "CM",
                   on_missing: Literal["skip", "raise"] = "skip",
                   progress: bool = False) -> pd.DataFrame
    """Weekend and holiday days yield no row. That absence IS the signal."""

# nse/macro.py — issue 18
def india_vix(start=None, end=None) -> pd.DataFrame
def index_valuation(index="NIFTY 50", *, metric="pe") -> pd.DataFrame
def index_total_return(index="NIFTY 50", *, net=False) -> pd.DataFrame
def usd_inr_reference_rate(start=None, end=None) -> pd.Series

# costs.py — issue 19
@dataclass(frozen=True)
class CostSchedule:
    effective_from: date
    stt_buy_delivery: float; stt_sell_delivery: float
    stamp_duty_buy: float;   stamp_duty_sell: float
    txn_charge_nse: float;   txn_charge_bse: float
    sebi_turnover_bps: float; gst_rate: float
    brokerage_bps: float;    brokerage_cap_inr: float | None

def cost_schedule(on: date | str) -> CostSchedule      # Finance-Act-versioned lookup
def round_trip_cost(notional_inr, side, on, *, exchange="NSE", broker="discount") -> CostBreakdown
def cost_drag(turnover: pd.Series, notional_inr: float, on) -> pd.Series

# ownership.py — issue 22. All keyed (symbol, as_of, revision_date)
def shareholding_pattern(symbol, *, consolidated=True, years=12) -> pd.DataFrame
def promoter_pledge(symbol, *, years=6) -> pd.DataFrame
def pledge_delta(symbol) -> PledgeDelta
def bulk_block_deals(*, start, end, symbols=None) -> pd.DataFrame

# universe.py — issue 18
def index_universe(index="NIFTY 50") -> pd.DataFrame
def universe_history(index, *, start, end) -> pd.DataFrame
def index_rebalance_events(index, *, start, end) -> pd.DataFrame   # derived by diffing

# nse/marketlens.py — issue 22.  UPPERCASE periods only, validated client-side.
PERIODS = ("1D","1W","1M","3M","6M","1Y","5Y","10Y","15Y","20Y","25Y","30Y")
def price_history(symbol, *, period="1Y", raise_errors=False) -> pd.DataFrame
    """Authoritative NSE close + volume, 30Y deep, zero auth.
    Sets attrs['bfinance_marketlens_partial_coverage'] = True — NOT an OHLCV source.
    Raises NotAnNseSymbolError for .BO / scrip-code forms; raises on an empty
    result rather than returning an empty frame."""
def intraday(symbol, *, raise_errors=False) -> pd.DataFrame
    """1-min bars, current session only, 09:15-15:59 IST, epoch-ms index.
    Per-bar volume is unreliable — do not consume it."""
```

## Ordering

```
01  test-suite repair                                  ← GATE
02  record pre-flight results
03  real OHLCV (bhavcopy) ─┐
04  statement shape        ├─ must all land before a 0.2.0 publish
05  corporate actions     ─┘
06  cache overhaul        ─┐
07  resolve_company_id     │
08  unit fixes             │
09  delete fabricated      │
10  silent no-ops          ├─ independent, parallelisable
11  ragged rows            │
12  AI markdown            │
13  screener errors       ─┘
14  parity surface
15  nse.macro   ─┐
16  costs        │
17  flows        │
18  universe     ├─ new modules, independent of the correctness block
19  ownership    │
20  derivatives  │
21  licensing    │
22  marketlens  ─┘   ← NSE-official, zero auth; feeds Phase 2 issue 21 (reconciliation)
```

Issues 03 and 04 are the two that unblock this app. Everything else can ship in any order.

Issue 22 is the only one with **no upstream dependency at all** — the endpoint needs no key, no
cookie, and no session, so it can be built and verified immediately without waiting on Phase 0 or
on the cascade work. **It was built first and shipped 2026-09-27**, ahead of the phase gate. That was
safe because it is a new module touching no existing code, so the "correctness fix looks like a
regression" risk that the gate exists to prevent does not apply.

Two things the build discovered that the recorded fixtures alone had missed:

- **100 of 372 intraday bars carry a NEGATIVE volume** (-1 to -4), plus 75 zeros. The daily series
  is clean on the same ticker (0 negative, 0 zero, min 2,066,169). Negatives are clamped to 0 and
  counted in `attrs["bfinance_negative_volume_bars"]`; intraday volume is documented as
  **unusable**, with callers redirected to the daily series.
- Intraday bars are *nominally* 1-minute, not uniformly so. Median spacing 60s and p95 66s, with
  two gaps of ~18 min after 15:15 and 15:32 as the closing session thins out. The original
  "1-minute bars" claim was overstated and was corrected rather than papered over.

A third finding was a bug in the new code itself: `_parse` initially passed Series values
alongside an explicit `DatetimeIndex`, so pandas reindexed the RangeIndex against the dates and
produced an all-NaN frame that still "succeeded" - the exact defect `CONTEXT.md` 9.22 documents.
Fixed with `.to_numpy()` per the repo's own rule.

## Do not regress

`analyst_price_targets` returns `None` (`ticker.py:351-360`). This is correct. Free India
consensus scraped from Moneycontrol, Trendlyne, or Tickertape is ToS-prohibited, slug-unstable,
and legally grey. Consensus EPS and target price are **not freely available in India at
acceptable reliability**. Keep returning `None`.

Likewise `institutional_holders`/`mutualfund_holders` return `(0,0)`, which was verified to match
real yfinance 1.7.0 for NSE tickers. Correct as-is.

## Verification

- The suite must **fail** if issue 04 regresses.
- Property test: a fresh bfinance `Ticker` and a fresh yfinance `Ticker` on the same symbol produce
  equal-shaped frames, and `iloc[:, 0]` is the newest period in both.
- 20 tickers × 1 year: bfinance mean absolute error vs yfinance ≤ 0.01% on O/H/L/C.
- 200 sequential cache operations leave zero open file handles.
- `IDEA` returns zero splits.
- `INFY`, `HDFCBANK`, `TCS` report `debtToEquity == 0.0`.
- `Ticker("X.BO").info["symbol"] == "X.BO"` and `["exchange"] == "BSE"`.
- A blank line precedes every pipe-table block in all four AI prompt builders.
- CI enforces `-m "not live"` and passes with no network access.
- **Issue 22:** all 12 uppercase periods return a fixture of the expected row count; every
  lowercase period raises client-side **before** any HTTP request; `.BO` and scrip-code forms raise
  `NotAnNseSymbolError`; close and volume match a recorded yfinance fixture **exactly** (8/8
  measured); and every frame has `bfinance_marketlens_partial_coverage = True` and **no** O/H/L columns.
