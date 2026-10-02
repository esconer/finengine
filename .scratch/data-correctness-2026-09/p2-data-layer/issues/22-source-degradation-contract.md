# 22 — Source degradation contract

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: 08, 09, 19
Repo: `backend/` + `frontend/`
Severity: **HIGH — this is the control system, and it does not exist**

## What

Define and implement **what the product does when a market-data source becomes unavailable**,
per capability, and make it visible.

Today there is no such contract. Each capability degrades differently, most of them silently, and
none of it is recorded. The concrete failure this ticket exists to prevent:

> screener.in IP-blocks the host. `/dashboard` renders **completely normally** — yfinance quietly
> carrying every price and fundamental — while concalls, shareholding, and all five screener
> strategies return empty. The only production evidence is a `logger.debug` line, which emits
> nothing at the default `log_level=INFO`. Nobody notices for days.

## The measured current state

Traced 2026-09-27 through `download.py:217`, `screener/client.py:148-171,257-258,331-332`,
`data_service.py:1245`, `company_data_service.py:211-215,284-295`.

A 403 is **not retried** by bfinance — only 429 and 5xx are
(`screener/client.py:148-171`). The 403 raises `UpstreamServiceError`, which
`download.py:217`'s blanket `except Exception: return pd.DataFrame()` swallows into an **empty
DataFrame**. That emptiness is what makes the cascade fall through — by accident, not by design
(`data_service.py:1245`: `if frame is None or frame.empty: continue`).

| Capability | Sources | On screener.in block | Loud? |
|---|---|---|---|
| OHLCV / timeseries | bfinance → yfinance → AV | yfinance serves | **No** |
| Quotes, validation | bfinance → yfinance | yfinance serves | **No** |
| Fundamentals, statements | bfinance → yfinance (thinner) | yfinance serves, degraded | **No** |
| Insider trades | yfinance only | unaffected | n/a |
| USD/INR FX | yfinance only | unaffected | n/a |
| **Equity research profile** | bfinance only | **503** | **Yes** |
| **Shareholding (12Q/11Y)** | bfinance only | **503** | **Yes** |
| **Concall transcripts** | bfinance only | **503** | **Yes** |
| **Screener Studio (×5 + custom)** | bfinance only | **HTTP 200, short list** | **No** |
| **AI dossier / memos** | bfinance only | 503 | **Yes** |
| Portfolio refresh | cascade | **stale `last_price` served as live** | **No** |
| WebSocket ticker | SQLite only | **`change: 0.00`, weeks-old close** | **No** |
| All analytics | cascade | computed on partial data, `data_status` varies | Partly |

Two structural problems behind the table:

1. **The fallback is structurally unrecordable.** `log_fetch_attempt` defaults
   `primary_attempt=True, fallback_attempt=False`, so a bfinance 403 serving via yfinance writes
   `status=success, primary_attempt=True, source_used=yfinance`. You cannot tell from the data
   that Tier-1 was dead. That is issue 08.
2. **A fundamentals outage is invisible.** `company_data_service.py:214` logs at `logger.debug`,
   which emits **nothing** at the default `log_level=INFO` (`config.py:68`). And `had_outage` is
   only consulted when *every* tier fails (`:295`). That is issue 19.

**There is no health endpoint.** `api/data.py` exposes `/config` (GET/PUT), `/cache/clear`, and
data routes — nothing that reports vendor liveness or per-capability source coverage.

## The contract

Organise by **capability class**, not by vendor. Whether a source failure is survivable is a
property of the capability (does an alternative exist?), not of which vendor died.

### Class A — multi-source, degrades gracefully

OHLCV, quotes, ticker validation, fundamentals, corporate actions.

| Rule | Detail |
|---|---|
| Fall back | Yes, in resolved `source_order` |
| Return | `200` with the serving source named |
| `data_status` | `"degraded"` — a **new** value, distinct from both `available` and `unavailable` |
| Record | One `fetch_logs` row per tier attempted, with the tier's real outcome (issue 08) |
| Surface | A non-blocking banner naming the failed vendor |

`"degraded"` is the point of this ticket. The current binary — `200` or `503` — cannot express
*"yfinance served this and the number is fine, but Tier-1 is dead and that matters to you"*.

### Class B — single-source with an identified alternative

Shareholding pattern, concalls, promoter pledge, bulk/block deals, FPI ownership.

| Rule | Detail |
|---|---|
| Fall back | **No alternative exists today.** Fail loudly |
| Return | `503` with the vendor named and the capability named |
| Surface | A persistent per-tab state, not a transient toast |
| Path forward | NSE CDSL/NSDL shareholding XMLs, NSE corporate-filings XBRL, NSE concall disclosures (Phase 1 issue 19 covers pledge/FPI/bulk, not the full pattern) |

`equity_research.py` already returns 503 on all 10 routes, so Class B is **largely correct
already**. What it lacks is *which* vendor died and *what* is unavailable, and a durable UI state.

### Class C — single-source with no realistic alternative

Screener Studio's five institutional strategies and the custom screen. Building a second Indian
equity screener is not in scope and is not worth it.

| Rule | Detail |
|---|---|
| Fail | **Loudly and completely** |
| Return | `503` on total failure. On partial, `200` with `data_status: "partial"`, the attempted count, the returned count, and the failed symbols with reasons |
| Never | A short list presented as a complete screen result |

`screener_service.py:261-268` currently returns `200` with `count: M-N` and **no `data_status` at
all**. That is issue 17. This ticket makes it a contract rather than a fix.

### Class D — derived and computed

Every analytics endpoint. The rule is that an upstream `data_status` **propagates** rather than
being recomputed or dropped.

| Rule | Detail |
|---|---|
| Any input `"degraded"` | Output `data_status: "degraded"` with the upstream reason |
| Any input `"unavailable"` | Output `unavailable` + a flag — never a silent partial computation (issue 08 in Phase 3 covers `_empty_concentration`) |
| Never | Compute a headline metric on a partially-delivered universe without saying so |

## Implementation

### 1. A source-capability registry

One declarative map, so the answer is data rather than scattered conditionals:

```python
CAPABILITY_SOURCES: dict[str, CapabilitySpec] = {
    "ohlcv":          CapabilitySpec(class_=A, sources=["bfinance", "yfinance"], degrades=True),
    "quote":          CapabilitySpec(class_=A, sources=["bfinance", "yfinance"], degrades=True),
    "fundamentals":   CapabilitySpec(class_=A, sources=["bfinance", "yfinance"], degrades=True),
    "shareholding":   CapabilitySpec(class_=B, sources=["bfinance"], degrades=False),
    "concalls":       CapabilitySpec(class_=B, sources=["bfinance"], degrades=False),
    "screener":       CapabilitySpec(class_=C, sources=["bfinance"], degrades=False),
    "ai_dossier":     CapabilitySpec(class_=B, sources=["bfinance"], degrades=False),
    "fx":             CapabilitySpec(class_=A, sources=["yfinance"], degrades=True),
    "corporate_actions": CapabilitySpec(class_=A, sources=["bfinance", "yfinance"], degrades=True),
}
```

A test asserts every route's capability appears in the registry, so a new endpoint cannot ship
without declaring how it degrades.

### 2. `data_status` gains `"degraded"`

Currently binary. Add the third state, and make it additive — existing consumers keep working
because `"degraded"` is not `"unavailable"`. Extend the vocabulary, do not replace it:

```
available | degraded | partial | unavailable
```

### 3. A health surface

`GET /api/v1/data/health` — per-vendor and per-capability:

```json
{
  "generated_at": "2026-09-27T20:05:57Z",
  "vendors": {
    "bfinance":  {"reachable": false, "last_success": "2026-09-26T18:40:00Z",
                  "consecutive_failures": 412, "last_error": "HTTP 403"},
    "yfinance":  {"reachable": true,  "last_success": "2026-09-27T20:05:12Z"},
    "alphavantage": {"configured": true, "usable_for_universe": false}
  },
  "capabilities": {
    "ohlcv":        {"data_status": "degraded", "served_by": "yfinance", "lost": ["bfinance"]},
    "shareholding": {"data_status": "unavailable", "served_by": null, "class": "B"},
    "screener":     {"data_status": "unavailable", "served_by": null, "class": "C"}
  }
}
```

`consecutive_failures` is the field that would have made the scenario above visible on day one
rather than day four.

### 4. UI surface

A single **source health strip** on `/dashboard/settings`, plus a non-blocking banner on
`/dashboard` when any capability is `"degraded"`. It must not become the always-green pill of
Phase 3 issue 06 — it is driven by real state, not a local boolean.

Per-capability state on the pages that hard-depend: equity research already has per-tab errors,
so it needs a durable "unavailable, and here's why" rather than a toast.

## Proof of done

- [ ] `CAPABILITY_SOURCES` exists and a test asserts every route's capability is registered. **A new
      endpoint cannot ship without declaring its degradation behaviour.**
- [ ] `data_status` accepts `degraded` and `"degraded" != "unavailable"`, so existing `N/A`
      handling is unaffected.
- [ ] **The scenario test.** Force a bfinance 403 and assert, in one run:
      - `/data/{ticker}` returns `200` with `source_used: "yfinance"` and `data_status: "degraded"`
      - `/company/{t}/shareholding` returns `503` naming bfinance and `shareholding`
      - `/screens/{strategy}` returns `503` (total) or `partial` with the failed symbol list
      - `/data/health` reports `bfinance.reachable: false` with a non-zero failure count
      - `fetch_logs` contains a `failed, primary_attempt=True` row for bfinance
      - **no** `logger.debug`-only evidence; the failure is at `warning` or above
- [ ] Every analytics response carries the upstream `data_status` when an input was degraded or
      unavailable.
- [ ] The settings health strip shows the real state, and `/dashboard` banners on degradation.
      A test asserts the banner appears and clears.
- [ ] Class C never returns a short list as a complete result. A test forces 3 of 50 symbols to
      fail and asserts `data_status: "partial"` with the reasons.
- [ ] The health endpoint is cheap — cached, not a live probe per request. A test asserts the call
      count over N requests.
- [ ] `consecutive_failures` resets on success. A test covers the recovery transition, so a stale
      count cannot persist after the vendor returns.

## Notes

**This ticket is a prerequisite for trusting the redundancy work.** Phase 1 issue 22 (MarketLens)
and the bhavcopy add real redundancy, but redundancy you cannot detect is indistinguishable from
redundancy you do not have. A silent yfinance fallthrough is indistinguishable from a healthy
two-source system.

It also makes the Phase 2 issue 21 reconciliation output actionable: `close_divergence` already
detects a *wrong* close from a reachable vendor; this detects an *absent* vendor.

**Class C has no fix, and that is the honest answer.** Building a second Indian equity screener is
out of scope and not worth it for a single-user product. The contract for Class C is therefore
*"fail completely and visibly"*, not *"degrade"*. Recording that explicitly is more useful than
pretending a fallback exists.

Sequence this after issues 08 (recording) and 19 (logging) — both are prerequisites, since a
degradation contract that cannot be recorded or observed is documentation.

Refs: `../spec.md`, issues 08, 09, 17, 19; Phase 1 issues 03, 19, 22; Phase 3 issues 05, 06, 26; Phase 2 issue 21
