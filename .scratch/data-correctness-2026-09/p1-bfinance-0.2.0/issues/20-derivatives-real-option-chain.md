# 20 — `bfinance.derivatives`: real option chain, FO bhavcopy, roll yield

Status: ready-for-agent
Type: task
Phase: 1
Blocked by: 03
Repo: `C:\es\coding\bfinance`
Effort: M

## What

New module replacing `market/derivatives.py`, which is currently unreachable dead code
containing synthetic data.

```python
def fo_bhavcopy(date: str | date) -> pd.DataFrame     # free static zip
def futures_chain(symbol: str = "NIFTY", *, as_of=None) -> FuturesChain
def roll_yield(symbol: str = "NIFTY", *, start, end) -> pd.DataFrame
def option_chain(symbol: str, expiry: str | None = None, *,
                 with_greeks: bool = True,
                 risk_free_rate: float | None = None) -> OptionChain
def iv_surface(symbol: str, *, as_of=None) -> pd.DataFrame
def put_call_ratio(symbol: str, expiry=None) -> float
def max_pain(symbol: str, expiry: str) -> float
```

## Why

The existing derivatives code is broken in two independent ways.

**a) It is unreachable.** `ticker.py:365` calls `DerivativesEngine.resolve_options(self.ticker)`
without the `fo_symbols` argument the method requires (`market/derivatives.py:44-59`). So
`Ticker.options` is **always** `()` and `option_chain()` always returns the empty chain.
`generate_option_chain` (78 statements, 67% covered) is dead code.

To be clear about what is *not* a bug: `()` matches real yfinance 1.7.0 for NSE tickers — that was
verified. The parity is correct; the code behind it is simply never reached.

**b) The data is synthetic.** `derivatives.py:68-72` and `:157-158` seed volume and open interest
with a **SHA-256 hash of the symbol**, and `:143` computes IV with a closed-form fake. Even if the
reachability bug were fixed, the output would be fabricated.

The real thing: FO UDiFF bhavcopy is a **free static zip with no session** (same family as issue
03's CM route), carrying `OpnIntrst`, `ChngInOpnIntrst`, `SttlmPric`, `UndrlygPric`, `XpryDt`,
`NewBrdLotQty`. Only the **live** option chain needs a cookie.

Spot-vs-futures basis gives cost-of-carry and roll yield, which is index-level funding cost, plus
expiry-week volatility and crash seasonality, plus lot sizes and the expiry calendar. All of that
is a prerequisite for the greeks to be worth anything.

## Scope note

Existing ticket `t31` ("Options Greeks & IV Surface Tracking") **understates this work.** The
correct framing is "build the real thing", not "add greeks". A t31 implementation on top of the
current module would ship fabricated Greeks.

## Sources

| Data | Route | Auth |
|---|---|---|
| FO EOD | `archives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip` (legacy `.../content/historical/DERIVATIVES/{YYYY}/{MON}/foDDMMYYYYbhav.csv.zip`) | **none** |
| Live index chain | `nseindia.com/api/option-chain-indices?symbol=NIFTY` (also BANKNIFTY, FINNIFTY, MIDCPNIFTY) | cookie, ~90s observed lifetime |
| Live equity chain | `nseindia.com/api/option-chain-equities?symbol=RELIANCE` | cookie |
| Historical chain | `nseindia.com/api/historicalOR/foCPV?from=&to=&instrumentType=&symbol=&year=&expiryDate=` (dates `DD-MMM-YYYY`) | cookie |

## Proof of done

- [ ] `Ticker("NIFTY").options` returns real expiries. `option_chain()` returns a populated chain.
- [ ] `fo_bhavcopy()` covers both the post- and pre-2024 schemas, with a fixture for each.
- [ ] Open interest in the output matches the bhavcopy exactly. A test asserts a known value for a
      known date. **No SHA-256 seeding survives anywhere in the module.**
- [ ] IV in the output is computed from real prices via a stated model (Black-76 or equivalent),
      with the model, the risk-free rate, and the dividend yield all recorded in the output.
- [ ] `risk_free_rate=None` pulls from the RBI reference rate (issue 15) rather than defaulting to
      a magic number. A hardcoded rate would reintroduce exactly the bug the consuming app has.
- [ ] `roll_yield()` returns a spot-vs-futures basis series; a test asserts the sign convention is
      documented and stable.
- [ ] `max_pain()` is verified against a hand-computed example.
- [ ] `put_call_ratio()` is computed from the chain, **not** from the licensed FTP file
      `fo_ddmmyyyy.csv.gz`.
- [ ] Live-chain cookie expiry is handled: the module re-seeds and falls back to the last good
      chain, labelled with its `as_of`, rather than raising or returning empty.
- [ ] Exported from the package root.

## Notes

The live chain is intraday-only. Historical reconstruction needs the FO bhavcopy or the
`historicalOR` endpoint, and the pre-2024 layout differs — so a dual parser is required, as in
issue 03.

Refs: `../spec.md`, `market/derivatives.py:44-59,68-72,143,157-158`, `ticker.py:365`, `.scratch/advanced-analytics/` ticket `t31`

## Verification correction (2026-09-28)

**The fabrication is genuinely removed - the ticket's own goal is met. Three residuals remain, and
they are filed as new work rather than here.** Verified at `98463d9` by execution.

Confirmed: `generate_option_chain` raises unconditionally (`derivatives.py:131-135`) with a message
naming the prior fabrication, and **no test asserts it returns data** - both call sites assert the
raise (`tests/test_dropin_actions.py:175-176`,
`tests/test_exhaustive_screener_and_yfinance.py:373-374`, the latter commented "The fabricator must
stay deleted").

`empty_option_chain()` survives but returns a **zero-row** `(0, 13)` frame with 0 non-null cells -
**not** "zeros". Nothing is fabricated either way, but "returns zeros" would invite a future
non-empty default. Pinned at `tests/test_dropin_actions.py:170`.

**Residuals, filed as a new ticket because they are not this ticket's job** -
`bfinance .scratch/verification-2026-09-28/issues/05-derivatives-dead-fabricator-and-false-docstring.md`:

- **`_contract_rng` (`derivatives.py:68-71`) is unreachable dead code** - zero `src/` and zero
  `test/` references, confirmed by AST walk. The SHA-256 seeded open-interest generator this project
  deleted on correctness grounds **is still physically in the file**, and `import hashlib` /
  `import random` (`:12-13`) exist solely to serve it.
- **The module docstring (`derivatives.py:6-9`) still advertises the deleted fabrication as live**:
  *"all volumes/OI are deterministic placeholders seeded by contract symbol"*, plus `NEEDS-MAIN`.
  Every clause is now false - the gating was actioned (`ticker.py:420` passes no `fo_symbols`, so
  `Ticker.options == ()`), and nothing generates volumes or OI. This is the only `"placeholder"`
  hit in `src/bfinance`.
- **`:111` misdescribes the old code as a seeded `numpy` generator.** It was stdlib `random`;
  `numpy` is not imported in the file at all. The correction introduced a new false claim.
- `get_upcoming_expiries()` returns real last-Thursday calendar dates with no symbol input - correct -
  but returned **3** (`2026-10-29, 2026-11-26, 2026-12-31`, all genuine Thursdays) against a
  docstring promising 4, because the filter at `:97` drops the current month once its Thursday passes.

**Note for the build half:** `resolve_options("RELIANCE", ["RELIANCE"])` already returns those real
dates, so the moment someone supplies `fo_symbols` the honest empty chain becomes a populated expiry
list. Still no fabricated prices, but know that before wiring it.
