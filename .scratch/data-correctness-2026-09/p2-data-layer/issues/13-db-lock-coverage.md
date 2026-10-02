# 13 — `_db_lock` coverage and the instance-vs-session mismatch

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: —
Repo: `backend/`
Severity: **MEDIUM**

## What

`self._db_lock` is created **per `DataService` instance** (`:243`), while the `AsyncSession` is
**request-scoped and shared across three `DataService` instances**:

```
benchmark_service.py:50   BenchmarkService.__init__  -> DataService(db_session)
indicators_service.py:184 IndicatorsService.__init__ -> DataService(db_session)
DI wiring:                analytics.py:413,428   data.py:167,177
```

A lock keyed on the instance cannot serialize a session keyed on the request.

## Why

`CONTEXT.md` §9.21 documents a hard-won bug: `AsyncSession` is not concurrency-safe, and parallel
commits/rollbacks on a shared session fail with `commit() can't be called here`, `transaction is
closed`, or `session is provisioning a new connection` — observed as **321 errors / 145 dropped
stores in one 20-second portfolio refresh**.

The `_db_lock` fixed the instance-local case. The cross-instance case is latent: every call site
happens to be sequential today, so it is a trap for the next concurrent caller rather than a live
bug.

## Unguarded session uses

| Line | Method | Reached from | Risk |
|---|---|---|---|
| 450 | `get_coverage` | `analytics.py:5460-5467` (sequential loop) | **Public method, no gate** |
| 488 | `_get_full_cached_frame` | guarded internally; `data.py:517` calls the sibling `_get_cached_data` **directly from the route** | Route-level call is sequential |
| 1477, 1501 | `_get_cached_data` | `data.py:517` — direct route call, no lock | Sequential today |
| 1664, 1700-1704, 1709 | `_store_timeseries_data` | guarded from `fetch_historical_data`; **unguarded from `_fetch_from_alpha_vantage` `:1339`** | Dead in production (`fetch_historical_data` passes `persist=False` at `:757`), but the signature default is the unsafe one |
| 1766-1773 | `_set_backfill_marker` | guarded callers only | correct |
| 1797-1832 | `check_data_integrity` | **no caller** | dead code, see issue 20 |

## Change

- Key the lock on the **session**, not the service instance. A session-scoped lock registry, or
  pass the lock in.
- Gate **every** public method that touches `self.db`, including `get_coverage`.
- Eliminate the route-level direct `_get_cached_data` calls at `data.py:517` — the route should go
  through a public, gated `DataService` method.
- Change `_store_timeseries_data`'s `persist` default to the safe value.
- Keep the existing regression guard working: `tests/test_db_gate_concurrency.py`
  (`OverlapGuardSession` flags any overlapping DB operation). Extend it to cover the
  cross-instance case by constructing two `DataService` instances over one session and asserting
  the guard fires.

## Proof of done

- [ ] Two `DataService` instances sharing one `AsyncSession` cannot overlap a DB operation. A test
      asserts this using the existing `OverlapGuardSession` pattern.
- [ ] `get_coverage` is gated. A test asserts it.
- [ ] No route calls a private `DataService` method. Grep for `_get_cached_data` and
      `_get_full_cached_frame` in `app/api/` returns nothing.
- [ ] `_store_timeseries_data`'s unsafe default is removed.
- [ ] `_fetch_from_alpha_vantage`'s unguarded persist path is either gated or removed (depends on
      issue 12's outcome).
- [ ] `tests/test_db_gate_concurrency.py` still passes and now covers the cross-instance case.
- [ ] The existing vendor-parallelism property is preserved: **network calls must stay parallel**.
      Only DB sections serialise. A test asserts concurrency is still achieved for vendor I/O.

## Notes

The existing design decision is right — serialise DB, parallelise vendor. Do not regress
`fetch_ohlcv_batch` (`:1102`, 5 workers) and `_fetch_price_series_dict` (`analytics.py:564`,
5 workers), which correctly share one `DataService` and therefore one lock today.

Refs: `../spec.md`, `app/services/data_service.py:243,450,488,757,1102,1339,1477,1501,1664,1700-1704,1709,1766-1773`, `app/api/data.py:517`, `app/services/benchmark_service.py:50`, `app/services/indicators_service.py:184`, `app/api/analytics.py:413,428,5460-5467,564`, `tests/test_db_gate_concurrency.py`
