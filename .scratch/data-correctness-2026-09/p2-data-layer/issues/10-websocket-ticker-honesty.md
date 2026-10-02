# 10 — WebSocket ticker honesty

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: —
Repo: `backend/`
Severity: **CRITICAL**

## What

`websocket.py:444-492`:
```python
price = p.last_price or 0.0      # :472
change = 0.0                      # :473
volume = 0                        # :474
if ts_rows:
    price = ts_rows[0].close      # :476  ← 'close', not 'adj_close'
    volume = ts_rows[0].volume
    if len(ts_rows) > 1 and ts_rows[1].close:
        change = (ts_rows[0].close - ts_rows[1].close) / ts_rows[1].close * 100.0
...
"timestamp": datetime.now(timezone.utc).isoformat()   # :489
```

## Four distinct defects

### a) Reads only SQLite, never a vendor

`:456-464`. After a vendor outage the rows go stale and this keeps broadcasting indefinitely.

### b) `change` and `volume` are published as measurements, not as "unavailable"

`change = 0.0` and `volume = 0` are indistinguishable from a genuinely flat, zero-volume session.

### c) Uses `close` while all analytics use `adj_close`

```
websocket.py:401           r.adj_close or r.close
websocket.py:476           price = ts_rows[0].close          ← unadjusted
analytics.py:514           ("adj_close", "close", "Adj Close", "Close")   ← adj_close FIRST
benchmark_service.py:24    ("adj_close", "close", "Adj Close", "Close")   ← adj_close FIRST
```

On an ex-split or ex-dividend date, **the live ticker strip and the analytics on the same page
disagree by the adjustment factor.** A user comparing the two sees two different prices for the
same stock at the same moment.

### d) A weeks-old close is stamped `datetime.now()`

`:489`. The timestamp says the data is live. It is not.

### e) Frames are dropped whole on any error, with no staleness signal

`:347-348`, `:365-367`, `:441-442`, `:493-494`:
```python
except Exception:
    logger.error("Portfolio update failed")
...
except ProviderError:
    logger.error("Analytics currency conversion unavailable")
    return                       # no frame at all
```

`background_updates` (`:292-294`) swallows the cycle error and sleeps 5s. No "stale frame" marker
is ever broadcast, so a client **cannot distinguish live data from a 10-minute-old frame**.

## Proof of done

- [ ] `price` uses `adj_close`, consistent with `analytics.py:514` and `benchmark_service.py:24`.
      A test with a split in the window asserts the two agree.
- [ ] `change` and `volume` are `None`/absent when unavailable, never `0.0`. The client renders
      an em-dash, not "0.00%".
- [ ] The frame carries a `data_as_of` derived from the **data**, separate from the send
      `timestamp`. A test asserts a stale frame reports a stale `data_as_of`.
- [ ] The vendor's observation date is used where available, matching the pattern already
      established in `india-flows/page.tsx:75-80` (server-published observation dates only).
- [ ] A frame explicitly carries a `stale: true` marker when the data is older than a threshold.
- [ ] A dropped frame sends an explicit staleness or error frame rather than nothing.
- [ ] `background_updates` records the cycle error with the reason, and the failure count is
      exposed.
- [ ] The "Live Data Active" pill in the frontend is driven by this real connection state rather
      than a local boolean (Phase 3 issue 06).
- [ ] A test forces a vendor outage and asserts the client can tell the data went stale.

## Notes

The `india-flows` page is the best failure-semantics reference in this codebase — it only claims
"no flows" when the component declares full coverage, renders missing legs as an em-dash rather
than `0`, and badges each row by its own `data_status`. Apply that discipline here.

Refs: `../spec.md`, `app/api/websocket.py:72,292-294,347-348,365-367,401,441-442,444-492,472-489,493-494`, `app/api/analytics.py:514`, `app/services/benchmark_service.py:24`
