# 06 — Cache overhaul: validation, TTL, refresh, and the connection leak

Status: ready-for-agent
Type: task
Phase: 1
Blocked by: 01
Repo: `C:\es\coding\bfinance`
Severity: **CRITICAL**

## What

Four defects in the caching layer, all of which cause a live consumer to receive stale or
wrong data with no way to detect it.

### a) Connection + file-handle leak on every operation

`src/bfinance/cache/sqlite_cache.py:52,77,117,138`
```python
with _CACHE_LOCK, _connect(self.db_path) as conn:
```

`sqlite3.Connection.__exit__` commits/rolls back; it does **not** close. Every `get`, `set`,
`clear`, and `_init_db` leaks an open connection and a file handle.

Verified: 200 sequential `with _connect(db)` blocks left **200/200 connections open** afterwards,
and the database file then could not even be deleted (`WinError 32`).

A 50-ticker scan with `actions=True` leaks >150 handles. On Windows this eventually yields
`PermissionError`, which the bare `except Exception` at `:132` and `:92` swallows into
`logger.exception` plus a silent cache miss — so the cache degrades invisibly under load.

Fix: `with contextlib.closing(_connect(...)) as conn, conn:` or one long-lived per-process
connection.

### b) Cache poisoning: unvalidated write + weak read gate

`src/bfinance/screener/client.py:303-304` (write) and `:236-238` (read gate)

The write path caches whatever `parse_full_profile` returned, with **no validation**. The read
path only checks `current_price is not None or market_cap is not None`. So one soft-block,
rate-limit, or HTML-layout change that yields a near-empty parse is served for the **full 24-hour
default TTL** with a perfectly valid-looking `currentPrice`.

Verified on an isolated temp cache: a profile with `cmp=1226.0, mcap=1659089.0` but **empty
profit_loss and balance_sheet** was returned from cache with no network, and the read gate
accepted it. Downstream: `dividends` empty, `splits` empty, `major_holders` `(0,0)`, `financials`
empty, `piotroski_score` 0, EV computed as bare market cap — and nothing distinguishes
"soft-blocked once" from "this company has no financials".

### c) 24-hour TTL on price-bearing data

Confirmed on disk: `screener_profile_MIDCAPIETF` had **23.88h TTL remaining**;
`screener_chart_*` had **5.88h**. So `info['currentPrice']` and the last bar of `history()` can
be up to 24h / 6h stale in a library marketed as live market microstructure.

### d) No public way to bust the cache

`src/bfinance/ticker.py:52-54,114,133`

`_info` / `_profile` / `_fast_info` are frozen for the process lifetime. Only the **private**
`_ensure_profile(force_refresh=True)` can bust it, and no public method exposes it. `info` and
`fast_info` have no `force_refresh` parameter. Verified: `'force_refresh' in
signature(Ticker.info.fget).parameters` → `False`.

Combined with (c), there is **no supported way to get a fresh price** from a long-lived `Ticker`.

## Proof of done

- [ ] 200 sequential cache operations leave **zero** open file handles, and the database file can
      be deleted afterwards.
- [ ] A write is rejected unless `profit_loss` is non-empty **and** a current price is present.
      A test writes a near-empty parse and confirms it is not cached.
- [ ] Entries containing a price have a TTL measured in **minutes**, not hours. A test asserts
      the TTL of a price-bearing entry.
- [ ] `Ticker.refresh()` exists, and `info` / `fast_info` / `history` accept `force_refresh=`.
      A test asserts two consecutive `info` reads return the updated value after a refresh.
- [ ] A `provenance` or `cached_at` field is exposed so a consumer can tell a cached price from a
      fresh one. (The consuming app needs this for Phase 2 issue 01.)
- [ ] The bare `except Exception` at `:92` and `:132` no longer converts an infrastructure
      failure into a silent cache miss. It raises or records a distinguishable state.
- [ ] The flaky CI failure in Phase 1 issue 01(f) is resolved as a side effect — those 5 tests
      fail because the pacer engages under `--cov`, which is a cache-timing symptom.

## Notes

This one ticket also explains the suite's flakiness. Do it early even though it is not a
correctness-of-numbers issue.

Refs: `../spec.md`, `cache/sqlite_cache.py:20,52,77,92,117,132,138`, `screener/client.py:236-238,303-304`, `ticker.py:52-54,114,133`

## Verification correction (2026-09-28)

**This ticket's own `Verified:` block for (a) does not reproduce, and the ticket needs re-scoping
before it is worked.** The two other sub-defects survive in narrower form.

**(a) "Connection + file-handle leak" - not reproduced.** The `with _connect(db)` blocks quoted in
the ticket **are present at all four sites** (52, 77, 117, 138); `sqlite3.Connection.__exit__`
commits/rolls back and does not close, so the code reading is right and the conclusion is wrong.
Counting live `sqlite3.Connection` objects via `gc.get_objects()`:

    8500 cache operations -> 0 live connections

There is no unbounded leak on the normal path. Note that counting `sqlite3.connect` against
`close()` returns `connects=6000, closes=0` and **looks damning - it is a false positive**;
refcounting reclaims the object with no Python-level `close()`.

Real but handler-dependent: `sqlite_cache.py:92-93` calls `logger.exception` on a corrupt read; the
record holds the traceback, which holds the frame, which holds `conn`. 50 corrupt `get()` calls
leave 51 live connections with a retaining handler, falling to 1 once records are dropped.

**Still outstanding:** the ticket's *file-handle* claim (database undeletable, `WinError 32`) was
not tested. Live object counts are a different question on Windows. Unresolved, do not assume.

**(b) "unvalidated write" - refuted for `SQLiteCache`, untested for the client.** `set()` validates
at `sqlite_cache.py:110-114` via a `json.dumps` guard; an unserialisable payload leaves 0 rows.
Corrupt rows fail **loudly** - `logger.exception` at ERROR, returning a cache miss, which is safe.
But the ticket's actual defect is the *client* gate at `screener/client.py:303-304` (write) and
`:236-238` (read checks only `current_price` or `market_cap`), serving a semantically empty profile
for 24h. That was **not tested**. Do not read the `SQLiteCache` refutation as refuting this.

**(c) TTL - confirmed, and the ticket missed a row.** There are five TTL sites, not four:
`search` 168h (:277), `profile` **24h implicit** (:401, no `ttl_hours` argument - falls through to
the default), `chart` 6h (:445), `market` 24h (:528), `market` leaf 12h (:655). The `profile` row is
the one that makes the ticket true, and it is true by omission rather than by decision.

**(d) "No public way to bust the cache" - refuted as written.** `force_refresh` exists and **does
cover the cache**: `client.py:315`, where line 322 skips the cache read and the write at :401 is
unconditional, so a forced fetch overwrites the row. Also on chart (:406) and both market routes
(:456, :576). `Ticker.get_profile_async(force_refresh=True)` is public (`ticker.py:102`) and
`SQLiteCache.clear()` is public (`:135`).

The gap that survives: the **sync** `Ticker` property surface calls `_ensure_profile()` with no
argument (`ticker.py:79`, private), so `force_refresh` is always `False` there - the ticket's own
probe is still true. And `search()` (`client.py:233`) has **no `force_refresh` parameter at all**, so
the 168h search cache cannot be refreshed through that method.

Strike (a) and the serialisability half of (b). Keep: the sync refresh path, an explicit short TTL
on `profile`, and the bare `except Exception` at `:92` turning infrastructure failure into a silent
miss.
