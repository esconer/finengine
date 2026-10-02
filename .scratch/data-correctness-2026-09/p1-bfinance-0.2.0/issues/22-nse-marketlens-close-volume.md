# 22 — `bfinance.nse.marketlens`: NSE-official close and volume

Status: resolved (2026-09-27)
Type: task
Phase: 1
Blocked by: — (built first, ahead of the phase gate; safe because this is a NEW module that
              touches no existing code, so the "fix looks like a regression" risk does not apply)
Repo: `C:\es\coding\bfinance`
Effort: S | **Shipped** — `src/bfinance/nse/marketlens.py` (479 lines), 61 offline tests, all green

## Resolution

Implemented and verified live. `uv run pytest` → **224/224 passing**; ruff clean under the default
`E4,E7,E9,F` set. bfinance CI runs pytest only, so that is the gate.

**Delivered**

| File | Purpose |
|---|---|
| `src/bfinance/nse/marketlens.py` | `MarketLensClient`, `validate_period`, `validate_nse_symbol`, `PERIODS`, module shortcuts |
| `src/bfinance/nse/__init__.py` | Package surface |
| `src/bfinance/utils/exceptions.py` | Added `NotAnNseSymbolError` |
| `src/bfinance/__init__.py` | Exports `marketlens`, `NotAnNseSymbolError` |
| `tests/test_nse_marketlens.py` | 61 tests, fully offline |
| `tests/fixtures/marketlens/*.json` | 8 recorded fixtures, live-captured 2026-09-26 |

**Live verification** — all 12 periods, plus the error paths, run against the real endpoint:
`1W` 4 · `1M` 19 · `3M` 63 · `6M` 122 · `1Y` 245 · `5Y` 1239 · `10Y` 2477 · `15Y` 3715 ·
`20Y` 4953 · `25Y` 6210 · `30Y` 8069 (from 1996-09-30). `RELIANCE.NS` correctly normalised to 4
rows. `RELIANCE.BO` / `500112` / `^NIFTY` all raise `NotAnNseSymbolError`; `RELIANCEEQ` raises
`TickerNotFoundError`; `bogus` / `MAX` raise `ValueError` before any request; `search("reliance")`
returns RELIANCE / RPOWER / RIIL with match scores.

### Three things the build changed versus this ticket

**1. Attr renamed for library consistency.** The ticket specified
`attrs["marketlens_partial_coverage"]`. Shipped as
**`attrs["bfinance_marketlens_partial_coverage"]`**, matching the existing
`bfinance_synthetic_ohlc` prefix so a consumer can enumerate every bfinance provenance marker with
one prefix. Two more attrs were added on the same principle:
`bfinance_provenance`, `bfinance_negative_volume_bars`, `bfinance_nonpositive_close_bars`.

**2. Lowercase periods are normalised, not rejected.** The ticket's Change section says *"uppercase
then validate"*, which auto-corrects; its proof-of-done said "raise". The implementation follows
the Change section because it is strictly safer — a typo in a config value or UI dropdown gets
data instead of an exception, and the silent-zero-row mode is closed either way.
`validate_period("30y") == "30Y"`; `validate_period("30yy")` raises.

**3. A defect the fixtures alone would have hidden — intraday negative volume.**
Live probing found **100 of 372 intraday bars carry a NEGATIVE volume** (−1 to −4), plus 75 zeros.
That is 47% of bars with an unusable volume; the session sums to 439 against an EOD volume in the
millions. The **daily** series is clean on the same ticker (0 negative, 0 zero, min 2,066,169).

Negatives are clamped to 0, logged, and counted in
`attrs["bfinance_negative_volume_bars"]`; bar count and timestamps are preserved rather than
dropping the rows. The docstring now states intraday volume is **unusable** and redirects callers
to `price_history_async`.

**A second live-only correction:** intraday bars are *nominally* 1-minute, not uniformly so. Median
spacing 60s and p95 66s, but two gaps of ~18 min after 15:15 and 15:32 as the closing session thins
out. The original "1-minute bars" claim and a flat-60s test assertion were both wrong and were
corrected rather than papered over; `test_intraday_sparse_bars_are_confined_to_the_closing_session`
now pins the gaps to the 15:00 hour so a shape change is noticed.

### A real bug the test suite caught in the new code

`_parse` initially passed **Series** values alongside an explicit `DatetimeIndex`. pandas reindexed
the Series' `RangeIndex` against the dates, producing an **all-NaN frame that still "succeeded"** —
precisely the class of defect `CONTEXT.md` §9.22 documents. Fixed with `.to_numpy()` per the repo's
own rule, with a comment citing §9.22 and a test asserting real values.

### Two client-behaviour notes

- **`.NS` suffix is stripped, not rejected.** The endpoint does not understand it either —
  `RELIANCE.NS` returns 0 rows. Stripping it is strictly more useful than failing, and it is
  verified working.
- **`L&T` returns 0 rows** because NSE's actual symbol is `LT`. Not a URL-encoding problem:
  `M&M` and `BAJAJ-AUTO` both resolve fine, since `&` in the *path* is safe.

## Architectural decision (2026-09-27): MarketLens is NOT a cascade tier

**Owner decision: MarketLens stays a separate, opt-in module. It is never added to the vendor
cascade, and `Ticker.history()` never falls back to it.**

The reasoning, recorded because it is not obvious:

| | Full OHLCV frame | Close + volume only |
|---|---|---|
| bhavcopy (issue 03) | real O/H/L/C/V, cookie-free | also real |
| bfinance / screener | **synthesized** O/H/L, real C/V | real |
| yfinance | real O/H/L/C/V, thin India fundamentals | real |
| **MarketLens (this issue)** | **cannot** — 2 columns only | real, exact, 30Y, zero auth |

bfinance *can* stand in for yfinance because the chart API's real close+volume, plus the
synthesized O/H/L, produce a complete yfinance-shaped frame. That structural substitutability is
exactly what makes it a drop-in — and exactly the RC1 defect that issue 03 exists to fix.

MarketLens **cannot** fill an OHLCV frame. Putting it in the cascade would force the adapter to
invent O/H/L to satisfy the frame contract, which rebuilds the RC1 bug inside the fallback path.
So it is not a tier.

**It is an authority source.** A tier answers *"give me data"*. An authority answers *"is this data
right?"* Different role — which justifies staying architecturally separate rather than merely
unwired.

### Consequence: the module is currently inert, deliberately

`marketlens` is reachable only via `bfinance.nse.marketlens.*`; nothing inside bfinance imports it.
It has two committed consumers, and both must actually be built or this is dead code carrying 61
tests and eight fixtures:

1. **Phase 2 issue 21 — close/volume reconciliation.** MarketLens is the third opinion that makes
   a bfinance↔yfinance disagreement *resolvable* rather than a coin flip. **Primary use.**
2. **A 30Y backfill.** screener.in gives ~5 years, yfinance varies, MarketLens gives 30 years from
   1996 with zero auth. Useful for long-horizon analytics and for Phase 5 issue 18
   (point-in-time fundamentals), which is otherwise limited by history depth.

Deliberately **not** a use: a fallback for when screener.in is blocked. Price continuity is already
covered by yfinance in finengine's cascade. The gap that genuinely needs filling is Phase 2 issue
22 — shareholding, concalls, and the screener having no alternative at all.

## Follow-ups (not blocking)

- [ ] **A genuinely-live test is still absent.** All 61 tests run offline against fixtures, so a
      silent upstream schema change would not be caught until a consumer runs. Recommend one
      `@pytest.mark.live` test asserting `30Y` returns >8000 rows for `RELIANCE`, so the existing
      `live` marker finally has a purpose (Phase 1 issue 01 notes all 50 current `live`-marked
      tests run in CI anyway — that needs resolving too).
- [ ] The 30Y fixture is trimmed to head+tail with the true row count recorded in
      `_fixture_full_row_count`, to keep the repo small. A full 432 KB fixture is available if the
      depth assertion ever needs real rows.
- [ ] Wire into `Ticker` as a fallback source once Phase 1 issue 04 (statement shape) and the
      finengine cascade work land. **Not** as a drop-in OHLCV tier — see the invariant below.

## The invariant this module must never violate

A close-only frame must **never** be coerced into an OHLCV shape. Filling `open`/`high`/`low` from
this frame fabricates an intraday range the source never provided — the exact defect
`bfinance_synthetic_ohlc` marks on the screener.in feed.

Enforced by `test_parsed_frame_has_no_ohlc_columns` and
`test_module_exposes_no_ohlc_builder`. If O/H/L is needed, the source is the bhavcopy (issue 03).

## What

New module wrapping NSE's own MarketLens price-history endpoint.

```
https://marketlens.nseindia.com/api/stocks/{SYMBOL}/price-history?period={PERIOD}
```

```python
# nse/marketlens.py

PERIODS = ("1D", "1W", "1M", "3M", "6M", "1Y",
           "5Y", "10Y", "15Y", "20Y", "25Y", "30Y")   # UPPERCASE ONLY

def price_history(symbol: str, *, period: str = "1Y",
                  raise_errors: bool = False) -> pd.DataFrame
    """Authoritative NSE close + volume. NSE symbols only.
    Sets attrs['bfinance_marketlens_partial_coverage'] = True — this is NOT an OHLC source."""

def intraday(symbol: str, *, raise_errors: bool = False) -> pd.DataFrame
    """1-minute bars for the current session only. 09:15-15:59 IST, epoch-ms index."""
```

## Why

This is the redundancy the cascade currently lacks, and it was verified end to end on 2026-09-26.

**It has no anti-bot at all.** No cookie, no session, no API key, no Referer required — a bare
request returns `200`. This is materially different from the rest of NSE, where
`/api/quote-equities` returns **403 from datacenter IPs** while `/api/marketStatus` returns 200.
MarketLens sits on the permissive side of that per-endpoint Akamai policy, permanently and without
credentials.

**It is NSE-official and goes back 30 years.** `period=30Y` returned **8,069 rows from
1996-09-30** for `RELIANCE`. bfinance's screener.in-backed history is roughly 5 years. That is a
7× depth increase from an official source.

**The data is verified exact.** Cross-checked against yfinance on `RELIANCE.NS` over the last 8
sessions:

```
date         ML_close   yf_Close     ML_vol      yf_Volume   close  volume
2026-09-17     1243.9    1243.90    7,752,895    7,752,895    ✓        ✓
2026-09-18     1226.4    1226.40   15,122,715   15,122,715    ✓        ✓
2026-09-21     1247.4    1247.40   10,007,218   10,007,218    ✓        ✓
2026-09-22     1240.4    1240.40   10,684,376   10,684,376    ✓        ✓
2026-09-23      1248.0    1248.00    8,352,048    8,352,048    ✓        ✓
2026-09-24     1219.2    1219.20   13,923,795   13,923,795    ✓        ✓
```

**close 8/8 exact, volume 8/8 exact.** `price` is unambiguously the close — it matched yfinance
`Close` 6/6 and `Open` only 2/6.

It also gives a **third independent opinion on close**, which makes a bfinance↔yfinance
disagreement *resolvable* rather than a coin flip. That is what Phase 2 issue 21 consumes.

### Measured period matrix

| period | rows | bytes | latency | range |
|---|---|---|---|---|
| `1D` | 372 | 19 KB | 7.4 s | **intraday**, see below |
| `1W` | 4 | — | 1.7 s | 5 sessions |
| `1M` | 19 | — | 1.1 s | ~1 month |
| `3M` | 63 | — | 1.0 s | ~1 quarter |
| `6M` | 122 | — | 1.5 s | ~2 quarters |
| `1Y` | 245 | 13 KB | 2.6 s | 1 year |
| `5Y` | 1,239 | 68 KB | 2.1 s | 2021-09-28 .. |
| `10Y` | 2,477 | 135 KB | 5.1 s | 2016-09-28 .. |
| `15Y` | 3,715 | — | 1.2 s | — |
| `20Y` | 4,953 | 268 KB | 4.5 s | 2006-09-28 .. |
| `25Y` | 6,210 | — | 2.2 s | — |
| `30Y` | **8,069** | 432 KB | 5.5 s | **1996-09-30** .. |

All periods are **daily** except `1D`. Weekend and holiday gaps of 3–4 calendar days are normal and
correct, not missing data.

### `1D` is intraday — and that is a genuine surprise

`period=1D` returns **372 one-minute bars** covering **09:15 → 15:59 IST**, with an **epoch-ms**
timestamp column instead of an ISO date. The full trading session at 1-minute granularity.

Caveats, all measured:

- **Current session only.** No historical intraday is available. This is a live capability, not a
  backfill source.
- **Per-bar volume is unreliable intraday.** 75 of 372 bars carried `volume: 0` (the opening
  auction window) and the whole session summed to 439. EOD volume is exact; intraday is not.
  **Do not use the intraday volume field.**

### Economics

10 tickers × `30Y` = **3.5 MB in 100 s** (~3–7 s per ticker, dominated by latency not bandwidth).
A 25-ticker portfolio 30Y backfill is ~10 MB and ~4 minutes. Entirely viable.

## The three traps, all of which will bite a naive client

### 1. Periods are UPPERCASE ONLY, and lowercase fails silently

Every lowercase variant returns `success: true, data: [], error: null` — **byte-identical to a
nonexistent ticker**. Verified across all 12:

```
lower  rows  |  upper  rows   same?
    1d      0  |      1D    372   NO  <-- differs (0 vs 372)
    1y      0  |      1Y    245   NO  <-- differs (0 vs 245)
   30y      0  |     30Y   8069   NO  <-- differs (0 vs 8069)
```

The client must uppercase the period and **validate it against `PERIODS` before the request**.
Relying on the server to reject a bad period is what produces a silent zero-row result.

### 2. A bad symbol is also a silent empty

```
RELIANCEEQ  (nonsense)      -> 200, rows=0, error=None
ZZZZZZ      (nonsense)      -> 200, rows=0, error=None
VODAFONEIDEA (renamed)      -> 200, rows=0, error=None
```

An empty `data` list is **not** evidence of anything. Distinguish "no data because the symbol is
wrong" from "no data because the window is wrong" by validating the symbol against
`/api/search?q=` first, which **is** verified working and returns
`{ticker, name, description, matchScore, marketCap}`.

### 3. NSE only — every BSE form returns zero

```
RELIANCE.BO  -> 0 rows
RELIANCE-BO  -> 0 rows
500112       -> 0 rows      (BSE scrip code)
500325       -> 0 rows
RELIANCE     -> 245 rows
```

Validate the symbol as NSE-shaped and **raise a typed `NotAnNseSymbolError` rather than returning
an empty frame.** A `.BO` ticker reaching this module must fail loudly, because a silent zero-row
return would be indistinguishable from a vendor outage.

### Also measured

- **Pagination is ignored.** `limit=100`, `page=2`, `from=`, `to=` all return the identical full
  432 KB payload. Do not build a paginated client; there is nothing to paginate.
- **EOD lag is ~1 trading day.** Last bar was 2026-09-24 (Thu) with Friday 2026-09-25 absent as of
  Saturday 2026-09-26. Consistent with the ~23:00–01:00 IST CM bhavcopy window, so the same
  scheduling constraint as Phase 4 issue 05 applies.
- `GET /api/stocks/{SYMBOL}` returns ~2.9 KB of additional per-symbol payload. Undocumented
  shape — inspect before depending on it.
- `GET /api/index/NIFTY50` → **404**. No index data here.
- The MarketLens **web page** `/stocks/{SYMBOL}` loads fine (200, Next.js) and is a usable manual
  fallback.

## Change

- Strict uppercase period validation against `PERIODS`, before the request.
- NSE symbol validation with a typed error for BSE and scrip-code forms.
- Empty `data` → typed `ProviderUnavailableError` or a distinct "symbol unresolvable" error, never
  a bare empty frame.
- Normalise the `1D` epoch-ms index to a tz-aware IST `DatetimeIndex`; keep daily periods as
  `YYYY-MM-DD`.
- Set `attrs["bfinance_marketlens_partial_coverage"] = True` on every frame. **This is the important
  contract** — see below.
- `provenance = "nse_marketlens"` on every return, per the Phase 1 issue 21 convention.
- Reuse the pacing design from `screener/client.py:100-121` even though no session is needed — the
  endpoint is fast but the 30Y payloads are large.

### The contract that must not be violated

**MarketLens is a close-and-volume source, not an OHLCV source.** Row keys are exactly
`['date', 'price', 'volume']`.

A consumer must never fill `open`/`high`/`low` from this frame to satisfy an OHLCV-shaped contract.
Doing so recreates precisely the RC1 bug that Phase 1 issue 03 exists to fix — a fabricated
inability to represent an intraday range. If a caller needs O/H/L, the bhavcopy is the source;
MarketLens is the cross-check.

The `bfinance_marketlens_partial_coverage` attribute exists so that mistake is detectable rather than
silent.

## Proof of done

- [ ] `period` is uppercased and validated against `PERIODS` client-side. A test asserts
      `period="1d"` and `period="bogus"` raise **before** any HTTP request is made.
- [ ] All 12 periods are tested against a recorded fixture, and each fixture's row count and date
      range are asserted. `30Y` for `RELIANCE` must be 8,069 rows from 1996-09-30.
- [ ] `RELIANCE.BO`, `RELIANCE-BO`, `500112`, and `500325` each raise `NotAnNseSymbolError`. A test
      covers all four — **none may return an empty frame.**
- [ ] `RELIANCEEQ` and `ZZZZZZ` raise a distinguishable "unresolvable symbol" error, not a
      provider-unavailable error and not an empty frame.
- [ ] `attrs["bfinance_marketlens_partial_coverage"] is True` on every returned frame.
- [ ] The frame has **no** `open`/`high`/`low` columns, and a test asserts their absence. This is
      the RC1 guard.
- [ ] `1D` returns a tz-aware IST index at 1-minute granularity, ~372 bars, 09:15–15:59 IST. A test
      asserts the bar spacing and the session window.
- [ ] The intraday volume unreliability is documented in the function docstring, and no code path
      consumes intraday volume.
- [ ] `provenance == "nse_marketlens"` on all returns.
- [ ] Close and volume are asserted **exact** against a recorded yfinance fixture — not within a
      tolerance. They matched 8/8 exactly.
- [ ] Pacing: a 10-ticker `30Y` sweep completes in under 150 s and issues no burst.
- [ ] The endpoint is documented in the Phase 1 issue 21 provenance table with its no-auth status,
      its NSE-only scope, and its ~1-trading-day lag.

## Notes

This closes the redundancy gap the owner raised. It is the **first source in the whole spec with
zero anti-bot exposure and 30 years of official history** — every other NSE route needs a session
and is exposed to per-endpoint Akamai policy.

It does **not** replace Phase 1 issue 03. That remains required for real O/H/L. The two are
complementary: bhavcopy for the OHLC frame, MarketLens for authoritative close and volume plus
reconciliation.

Also verified working: `GET /api/search?q={query}` — returns `ticker`, `name`, `description`,
`matchScore`, `marketCap`. Use it for symbol resolution and validation. Note it requires a
non-empty query (`{"success": false, "error": "Search query is required"}`) and returned zero
results for `q=nifty`, so it may be equities-only.

Refs: `../spec.md`, issue 03 (bhavcopy, not a substitute), issue 21 (provenance), Phase 2 issue 21 (reconciliation), `nse/bhavcopy.py`

## Verification correction (2026-09-28)

**CONFIRMED, with one framing correction.** Verified at `98463d9` by execution against the recorded
fixtures.

Exactly two columns, no O/H/L: daily `['Close', 'Volume']` shape (245, 2) tz-naive; intraday
`['Close', 'Volume']` indexed `Asia/Kolkata`. Upstream returns only `date`/`price`/`volume` and
`marketlens.py:301` **hard-requires that set**, raising `UpstreamServiceError` otherwise - so an
OHLCV frame is structurally impossible. NSE-official (`marketlens.nseindia.com`, no auth), and it
stamps `bfinance_marketlens_partial_coverage = True`. `bhavcopy.py:17-18` contrasts against it
explicitly. Not an OHLC substitute, and not used as one.

**Correction: the module is not unreferenced.** `src/bfinance/nse/corporate_actions.py:206` imports
`validate_nse_symbol` from it and calls it at `:472` and `:1208`, pinned by
`tests/test_nse_corporate_actions.py:642-645` ("marketlens is imported for its symbol validator only;
that is a pure function").

What **is** unreferenced from `src/` is the *data* client - AST sweep:

| symbol | src refs | test refs |
|---|---|---|
| `validate_nse_symbol` | `corporate_actions.py:206,472,1208` | 5 |
| `MarketLensClient` | only the `nse/__init__.py:50` re-export | 24 |
| `price_history` | only the re-export | 0 |
| `intraday` / `intraday_async` | only re-exports | 0 / 1 |

So it is public API (re-exported at `bfinance/__init__.py:40`) and an on-demand authority source, not
a cascade tier. Worth being precise about, because "unreferenced" would suggest dead code and the
validator import shows it is load-bearing.
