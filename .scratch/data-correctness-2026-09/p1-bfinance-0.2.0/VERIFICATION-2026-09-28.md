# Verification record - bfinance 0.2.0 tickets, 2026-09-28

Status: verification-in-progress
Type: record
Phase: 1
Repo: `C:\es\coding\bfinance`
Verified against: commit `98463d9` (16 unpushed commits on top of `5d42e68`)

Covers: tickets **01, 04, 06, 12, 13**. Tickets 03, 05, 07, 08, 09, 10, 14-22 are being verified
in parallel and are **not** addressed here. Do not read the absence of a ticket from this file as
"no correction pending".

## Why this file exists

A status pass over all 22 tickets was produced by reading the repo with `grep` and `Select-String`.
That table was reported as a reconciliation. **It was wrong in seven places**, and in each case the
error was a known failure mode of grep-based reading. This file records what execution actually
measured, so the ticket statuses are re-derivable rather than asserted.

The short version: the first pass reported ticket 06 as a critical open defect and ticket 13 as
done. Both are wrong. Ticket 06's headline claim - a per-call connection leak - does not reproduce.

## Method

Every claim below was tested by executing code or reading a function body in full. A grep that
returns nothing is not evidence of absence, and that mistake produced five of the seven errors.
All measurements are offline; no network request was made.

One methodological note worth keeping: the first measurement proposed for the connection leak -
count `sqlite3.connect` calls against `close()` calls - returns `connects=6000, closes=0` for 6000
operations and looks damning. **It is a false positive.** `sqlite3.Connection` has no Python-level
`close()` call in this code; CPython refcounting reclaims the object at function exit. Counting
live objects via `gc.get_objects()` is the measurement that settles it.

---

## Corrected status

| # | Ticket | First pass said | Measured | Correct status |
|---|---|---|---|---|
| 01 | Repair the test suite | half done | PARTIAL | 2 of 4 cited lines are docstring prose, not assertions |
| 04 | Statement shape parity | open by design | PARTIAL | open by design; alarm count is 7, not 8 |
| 06 | Cache overhaul | **open, critical** | PARTIAL | **headline claim does not reproduce**; three of four sub-defects survive in narrower form |
| 12 | AI dossier markdown | open | **CONFIRMED, worse** | 7 of 7 tables affected, measured via the public API |
| 13 | Screener error surfacing | **done** | PARTIAL | classification done; **retry layer is still untested** |

---

## Ticket 06 - cache overhaul

`Status: ready-for-agent` -> **needs re-scoping.** Not because the work is unnecessary, but
because the ticket's own `Verified:` block contains a claim that does not reproduce, and two of its
four sub-defects are wrong as written.

### a) "Connection + file-handle leak on every operation" - NOT REPRODUCED

The ticket asserts:

> Verified: 200 sequential `with _connect(db)` blocks left **200/200 connections open** afterwards,
> and the database file then could not even be deleted (`WinError 32`).

Measured (`sqlite_cache.py`, 146 lines read in full):

| thing | count | lines |
|---|---|---|
| `_connect(...)` call sites | 4 | 52, 77, 117, 138 |
| explicit `conn.close()` | 0 | - |
| `finally` | 0 | - |
| `with ... as conn:` | 4 | 52, 77, 117, 138 |

The `with` blocks the ticket quotes **are present at all four sites**. `sqlite3.Connection.__exit__`
commits or rolls back; it does not close. So the ticket's *code reading* is right about
`__exit__` and its *conclusion* is wrong about the consequence.

Counting live `sqlite3.Connection` objects:

```
ops so far   live connections
      100                    0
      500                    0
     2100                    0
     8500                    0
```

**8500 cache operations leave 0 live connections.** There is no unbounded leak on the normal path.

**The one real path.** `sqlite_cache.py:92-93` calls `logger.exception(...)` on a corrupt read.
The log record holds the traceback, the traceback holds the frame, the frame holds the local
`conn`. With a handler that retains records: 50 corrupt `get()` calls leave **51** live connections,
falling to 1 once the records are dropped. So retention is real but **handler-dependent**, not
unconditional.

**One measurement from the ticket is still outstanding.** The ticket's claim is a *file-handle*
claim - the database could not be deleted, `WinError 32`. The verification measured live Python
objects, not file handles, and did **not** attempt the deletion. That specific assertion is neither
confirmed nor refuted here. See "Measurements still missing".

Corrected statement: *4 `_connect()` sites with 0 `close()` and 0 `finally`; `with conn:` is
transaction-only. Connections are reclaimed by refcounting, so the normal path does not leak
(8500 ops -> 0 live). Retention occurs only via `logger.exception` tracebacks in `get()` when a
handler keeps records.*

### b) "Unvalidated write" - REFUTED as a `SQLiteCache` claim, and untested as a client claim

These are two different layers and the first pass conflated them.

`SQLiteCache.set()` **does** validate. `sqlite_cache.py:110-114`:

```python
try:
    payload_str = json.dumps(payload)
except (TypeError, ValueError):
    logger.warning("Skipping cache set: unserializable payload for key %s", cache_key)
    return
```

Executed: `cache.set("k", {"x": object()})` leaves **0 rows** in the table. The write is refused.

Corrupt stored rows fail **loudly**, not silently:

```
corrupt row                  get() returns   log
truncated JSON ('{"a": 1')   None            ERROR:Cache get failed for key k
garbage bytes                None            ERROR:Cache get failed for key k
empty string                 None            ERROR:Cache get failed for key k
JSON null                    None            (none)
valid JSON, wrong type       ['a','b','c']   (none)
```

`json.loads` raises, line 92 catches, `logger.exception` fires at ERROR with a traceback, and the
caller gets a cache *miss* - which is safe, because both callers re-fetch.

**However the ticket's actual defect is a different claim and remains untested.** The ticket's
`(b)` is about `screener/client.py:303-304` writing whatever `parse_full_profile` returned, and
`:236-238` reading back with a gate that only checks
`current_price is not None or market_cap is not None` - so a semantically empty profile is served
for 24h. That is a claim about the **client's** write and read gate, not about `SQLiteCache`'s
serialisability. It was not tested. Do not read the refutation of serialisability as a refutation
of this.

Residual, real and not in the ticket: `json.dumps` accepts `NaN` and `Infinity`, so
strict-JSON-invalid text is stored and returned with no log; and a stored JSON `null` is
indistinguishable from a miss.

### c) "24-hour TTL on price-bearing data" - CONFIRMED, and the ticket missed a row

`sqlite_cache.py:38` `default_ttl_hours = 24.0`. `screener/client.py:108`
`cache_ttl_hours = 24.0`. Both exact.

Complete per-category table, every `self.cache.set` in `screener/client.py`:

| category | TTL | line | note |
|---|---|---|---|
| `search` | 168.0h (7d) | 277 | |
| `profile` | **24.0h implicit** | 401 | **no `ttl_hours` argument - falls through to the default** |
| `chart` | 6.0h | 445 | |
| `market` (`/market/`) | 24.0h | 528 | |
| `market` (leaf industry) | 12.0h | 655 | |

The `profile` row is the one that makes the ticket's claim true, and it is true **by omission**
rather than by decision. Worth fixing explicitly either way.

### d) "No public way to bust the cache" - REFUTED as written, but a real narrower gap survives

`force_refresh` exists and **does cover the cache**, not just the in-process profile:

- `screener/client.py:315` `get_company_profile(ticker, force_refresh=False)`; line 322 skips the
  **cache read** when set; the cache **write** at line 401 is unconditional, so a forced fetch
  overwrites the stored row.
- Also on `get_chart_timeseries` (:406), `get_market_industries` (:456), industry constituents (:576).
- `ticker.py:102` `async def get_profile_async(self, force_refresh: bool = False)` - **public**.
- `sqlite_cache.py:135` `def clear(self, category: Optional[str] = None)` - **public purge**.

So "no supported way to get a fresh price from a long-lived Ticker" is **false**: a caller can use
`await ticker.get_profile_async(force_refresh=True)` or `client.cache.clear()`.

The gap that does survive:

- The **sync** `Ticker` property surface (`info`, `fast_info`, `get_income_stmt`, `history`, ...)
  calls `self._ensure_profile()` with **no argument** (`ticker.py:79`, private), so it always gets
  `force_refresh=False`. The ticket's own probe is still true:
  `'force_refresh' in signature(Ticker.info.fget).parameters` -> `False`.
- `search()` (`screener/client.py:233`) has **no `force_refresh` parameter at all**, so the 168h
  search cache cannot be refreshed through that method.

### Surviving "proof of done" items

Still valid, restated: the sync surface needs a refresh path; `profile` should carry an explicit
short TTL; the bare `except Exception` at `:92` should not turn an infrastructure failure into a
silent miss. Items (a) and the serialisability half of (b) should be struck.

---

## Ticket 13 - screener error surfacing

`Status: ready-for-agent` -> **partially satisfied; the retry clause is still open.** The first
pass marked this done. That was the single worst error in the table, because the ticket's whole
point is retry coverage.

### What is genuinely built

Measured by instrumenting `httpx.AsyncClient.get` and `asyncio.sleep`, `max_retries=3`:

| status | attempts | outcome | backoffs |
|---|---|---|---|
| 200 | 1 | returned `[]` | - |
| 204, 301, 400, 401, 403, 404, 418 | 1 | `UpstreamServiceError` | none |
| 429 | 3 | `RateLimitExceededError` | 2.76, 5.10, 9.49 |
| 500, 502, 503, 504, 599 | 3 | `UpstreamServiceError` | exponential/linear |
| 600 | 1 | `UpstreamServiceError` | none - **unhandled** |
| `ConnectTimeout` | 3 | `UpstreamServiceError` | - |

Retried: 429 (`client.py:194`), 500-599 (`:206`), and
`TimeoutException / NetworkError / RemoteProtocolError` (`:218`). 429 backs off `(2**attempt)*2.0`
and 5xx `(attempt+1)`, both honouring `Retry-After` capped at 30s. `RateLimitExceededError` is a
verified subclass of `UpstreamServiceError`. So the ticket's "None of these return `[]`" is
**satisfied**, and the typing requirement is **satisfied**.

### What is not: the retry layer is still untested for Screener

> Every screener test builds the client with `max_retries=1`.

```
tests/test_upstream_errors.py:82              ScreenerClient(..., max_retries=1, ...)
tests/test_screener_market_offline.py:463,485 max_retries=1
tests/test_screener_offline.py:221            max_retries=1
```

With `max_retries=1` the loop body runs once, hits `continue`, and exits. **No screener test ever
observes a second attempt.** Both retry-named tests are single-shot:
`test_search_5xx_is_an_upstream_error_not_an_empty_result` (`:133`, 503, 1 attempt) and
`test_rate_limit_keeps_its_own_error_type` (`:140`, 429, 1 attempt **plus a wasted 3.49s backoff
sleep on the final attempt**).

The harness already records a `calls` list *specifically* so retry can be asserted
(`test_upstream_errors.py:45-64`). It is used only for the Ticker-refetch tests (`:188-203`),
never for retry. The instrument to prove the claim exists and is unused for the claim it exists for.

Coverage: 23 offline error tests exist in `test_upstream_errors.py`, all passing, 16 driving a
non-200 status. Statuses covered: **403 (x11), 429 (x1), 503 (x1), 200 (x1)**. Not covered: 400,
401, 404, 418, 204, 3xx, 500, 502, 504, 599, 600, or the network-error branch.

**The asymmetry worth acting on:** the same discipline *is* tested for the other two clients -
`test_nse_bhavcopy.py:607-649` and `test_nse_corporate_actions.py:788-815` use `max_retries=2/3`
and assert `match="failed after 2 attempts"`, and `test_trendlyne_core.py` uses 2/3 throughout. The
pattern is established in this repo. It is simply missing for the client this ticket is about.

### Small addition to the ticket

HTTP 600 is outside the `500..599` range, so it is neither retried nor specifically classified; it
falls through to the caller's generic `UpstreamServiceError`. Not a real HTTP status, so low
impact, but it is literally unhandled and the range is a magic number.

---

## Ticket 12 - AI dossier markdown

`Status: ready-for-agent` -> **CONFIRMED, and broader than the ticket states.**

`src/bfinance/ai/context.py:229`, exact:

```python
return "\n".join([line for line in lines if line.strip() != ""])
```

Measured through the **real public API**, `AIContextBuilder.build_markdown_context(...)`, on a real
`CompanyProfile` built by importing the repo's own `_synthetic_profile` from
`tests/test_ai_context_rendering.py`. Fully offline, no synthetic `lines` list.

```
total lines emitted: 64
blank lines surviving in output: 11
GFM tables found: 7
tables with NO blank line before them: 7 / 7
```

All seven, each immediately preceded by its own heading: Annual Income Statement, Quarterly
Financial Results, Annual Balance Sheet, Cash Flow Statement, Quarterly Trend, Historical Operating
Ratios, Industry Peer Comparison Matrix.

**Mechanism, now visible.** Sections append the heading as `f"\n## Heading"` (e.g. `context.py`
lines 139, 147, 155, 163, 171). That leading newline is *inside* the string, so it survives the
filter and produces the blank line *before* the heading. The gap *between heading and table* would
need a standalone `""` entry, which line 229 strips. That is why 11 blank lines survive while all 7
heading-to-table gaps vanish - the ticket's phrasing "renders as run-on pipes" understates it; the
tables are not joined together, they are orphaned from their headings.

**Honest limit.** The *precondition* markdown needs is verified absent, 7/7. The *rendered output*
is not verified: no GFM parser is installed in the environment and none may be fetched. "Tables do
not render" remains an inference, not a measurement.

---

## Ticket 01 - repair the test suite

`PARTIAL`. The first pass cited four live `assert all(isinstance(c, str) for c in df.columns)` lines
on statement columns. **Two of the four are not assertions.**

| cited line | enclosing construct | status |
|---|---|---|
| `test_parity_statements.py:35` | `test_native_shape_contract()` (def at :27), not xfailed, no `live` marker | **live** |
| `test_parity_statements.py:90` | inside the docstring of a `@pytest.mark.live` test (:83-84), quoted under "The previous version of this test asserted::" | **already defanged** |
| `test_stmt_accessor_contract.py:15` | inside the **module docstring** (:1-35), quoted as an example of the removed defect | **already defanged** |
| `test_stmt_accessor_contract.py:102` | `test_native_shape_is_still_reachable_and_unchanged()` (def at :92), not xfailed | **live**, deliberate |

The `# locks in the wrong shape` line cited in the first pass is
`test_stmt_accessor_contract.py:15` - which is prose in a module docstring describing a removed
assertion, not a test. Module docstring lines 17-18 say so explicitly: *"That assertion is the
defect, not the specification. It is corrected in `test_parity_statements.py`."*

Run: `tests/test_parity_statements.py` collects 7, deselects 2, **5 passed, 2 deselected** - so
`test_native_shape_contract` is in the offline selection and does pass today.

**The first pass also overstated the harm.** Both live assertions target
`FinancialStatement.to_dataframe()` - the **native** Indian Rs-Cr method - not `to_yfinance()`.
`test_stmt_accessor_contract.py:22-25` states the repo's position: the native shape is a real,
depended-upon contract that issue 04 must **preserve** under a new name, not quietly drop. The
genuine defect is narrower and is about signalling, not shape: both live lines sit in a file named
`test_parity_statements.py`, implying yfinance parity, and neither is xfailed - so the intended
0.2.0 break lands as a **red suite** rather than as a signalled break.

---

## Ticket 04 - statement shape parity

`PARTIAL`. Alarm count is **7, not 8**; `reason=_ISSUE_04` count is **6, not 7**.

`xfail(strict=True)` decorator lines: 180, 226, 239, 252, 266, 278, 290.
Line 180 carries an inline reason - `"issue 04: to_yfinance() must de-duplicate aliased rows"` -
which is issue-04 by text but a distinct de-duplication contract, not a shape contract. That single
line is the entire 7-vs-8 discrepancy.

Run of the file: `5 passed, 7 xfailed`, **0 xpassed**, 0 failed. Six reasons are
`"issue 04: get_*_stmt must return the yfinance shape, not the native shape"`; one is the
de-duplication reason above.

The substantive claim **holds**. `test_yfinance_columns_are_newest_first` (def at :240) asserts
`df.columns.is_monotonic_decreasing` at :249 and reports XFAIL - so the statement order really is
ascending today. And 0 XPASS suite-wide means nothing is silently starting to pass, so the
"cannot land silently" property the file docstring claims is currently holding.

---

## New defects found that no ticket covers

1. **`tests/test_stmt_accessor_contract.py:103` is a tautology.**
   `assert df.columns.is_monotonic_increasing is False or True` - this is true for every possible
   value of the expression, asserts nothing, and passes unconditionally. It is a live offline
   assertion, not a docstring. This should be its own ticket; it is the third instance in this repo
   of a test that certifies nothing while appearing to check an invariant.

2. **`600` is unhandled** in the Screener retry classification (see ticket 13).

3. **`json.dumps` accepts `NaN`/`Infinity`**, so the cache stores strict-JSON-invalid text and
   returns it with no log; a stored JSON `null` is indistinguishable from a miss.

4. **The `profile` cache TTL is implicit** - `client.py:401` passes no `ttl_hours`, so the
   price-bearing 24h TTL is a default fallthrough rather than a decision.

---

## Measurements still missing

Stated rather than glossed, because each one is currently unresolved and would otherwise be
assumed settled:

- **Ticket 06(a) file-deletion.** The ticket claims 200 operations make the database file
  undeletable (`WinError 32`). Live object counts were measured; file handles were not, and the
  deletion was not attempted. On Windows this is a materially different question from Python
  object lifetime, and refcounting closes a connection without necessarily releasing the
  underlying handle before the next one opens. **Unresolved.**
- **Ticket 06(b) client read gate.** `screener/client.py:236-238` and `:303-304` were not
  exercised. The `SQLiteCache` serialisability result does not speak to them.
- **Ticket 12 rendered output.** Precondition verified 7/7; actual GFM rendering unverified for
  lack of a parser.

---

## Tracker integrity (finengine side, noted in passing)

Not blocking, but found while reading:

- `spec.md` header says `Tickets: 20`; the `issues/` directory holds **22** files.
- `spec.md` and several tickets contain mojibake where `->` and the rupee sign should be
  (e.g. `0.1.3 ?+' 0.2.0`, `??" `). This is UTF-8 read through cp1252 and re-encoded - a
  known `edit`-tool failure mode in this workspace, reported independently by another agent
  during the same session. Any automated reader of these files is reading corrupted bytes.
  Recommend an encoding pass before these tickets are worked.

## Complete final status (all 22 tickets, all three verification passes)

Verified by execution across three adversarial passes, all read-only, all offline, at commit
`98463d9`. "Measured" means a script ran and its output is recorded on the ticket.

| # | Ticket | Final status | The load-bearing finding |
|---|---|---|---|
| 01 | Repair the test suite | **PARTIAL** | 2 of 4 cited lines are docstring prose; the residual is signalling (un-xfailed live lines in a parity-named file), not shape |
| 02 | Record pre-flight results | **SUPERSEDED** | `docs/UPSTREAM_SOURCES.md`, 41 KB of measured upstream facts |
| 03 | Real OHLCV from bhavcopy | **DONE** | default `"bhavcopy"`, and the envelope cannot produce the asserted High - a real check. Fabricator retained behind a flagged opt-in |
| 04 | Statement shape parity | **OPEN BY DESIGN** | 7 strict xfails (not 8), 0 XPASS, order confirmed ascending |
| 05 | Real corporate actions | **HALF DONE - RE-OPEN** | NSE feed fixed and verified, but `market/corporate.py:151-163` still infers a split from equity-capital growth, reachable from the default `history()` path. Fabricates a `Stock Splits` entry *and* rescales every prior bar, while `attrs` claim `applied=True, synthetic_ohlc=False` |
| 06 | Cache overhaul | **NEEDS RE-SCOPING** | the ticket's own leak claim does not reproduce (8500 ops -> 0 live connections); unvalidated-write claim refuted; no-public-refresh claim refuted |
| 07 | resolve_company_id exact | **DONE, latent caveat** | one route, attribute-only. But first-match regex over whole HTML: two `data-company-id` attrs returned the wrong one |
| 08 | Unit fixes | **HALF DONE, ticket partly backwards** | 3 orphaned `or` chains not 1, and `0.00` can be overridden by an alias to a *different* wrong number. The unconverted key is **ROCE at `quotes.py:246`**, not ROE - `roa` is not even a `TopRatios` field |
| 09 | Delete fabricated paths | **DONE, dead residue** | 0 hardcoded financial numbers by AST sweep; dead `_contract_rng` fabricator still in the file |
| 10 | Eliminate silent no-ops | **OPEN, worse than described** | `download()` does **not** reject unknown kwargs - it only warns. `valuation_measures` yields a confident wrong `EnterpriseValue`; `cash_cr = 0.0` biases EV for every net-cash company |
| 11 | Ragged-row padding | **DONE** | defensive indexing, tests present |
| 12 | AI dossier markdown | **CONFIRMED, worse** | 7/7 tables orphaned from their headings, via the real public API |
| 13 | Screener error surfacing | **HALF DONE** | classification is correct; every test uses `max_retries=1`, so no second attempt is ever observed |
| 14 | yfinance parity surface | **NEEDS RE-SCOPING** | 5 raises are not 5 equal gaps: 1 is a dead conditional, 2 are TTM with a factually wrong message and *present* data. And the "65 missing members" are a non-sequitur - 0 of them raise |
| 15-19 | macro / costs / flows / universe / ownership | **NOT STARTED** | `find_spec` -> `None` x5; zero partial implementations, stubs or TODOs anywhere in the repo |
| 20 | Derivatives real chain | **GOAL MET, residual open** | generator raises, both tests assert the raise. But the seeded RNG is still in the file, unreachable, and the docstring still advertises the deleted fabrication as live |
| 21 | Licensing and provenance | **PARTIAL** | provenance is carried inside `UPSTREAM_SOURCES.md`; no standalone licensing document |
| 22 | nse.marketlens | **DONE** | exactly `['Close','Volume']`; structurally cannot be OHLCV. Not unreferenced - the symbol validator is load-bearing |

## The error pattern across all three passes

Seven of the original status claims were wrong, and they fail in one direction: **each credited a
fix that had been made somewhere else, or that had not been made at all.**

- Ticket 05 "done" - the NSE feed was fixed, the screener fallback was not.
- Ticket 08 "ROCE is the unconverted one" - it is the opposite; ROE's `/100.0` is correct.
- Ticket 10 "`download` now rejects kwargs" - it only warns.
- Ticket 14 "65 members cannot be added *because* of the demerger" - 0 of the 65 raise.
- The cache "connection leak" - measured, and it does not leak.
- The demerger 4.52% attributed to yfinance - it is bfinance's; the repo's own docs said so.

A grep-based pass cannot catch any of these, because in every case the *documented* intent and the
*executed* behaviour differ. Six of the seven were found by running the code and looking at the
output. Recommend that no future status of this kind be recorded without a script behind it.
