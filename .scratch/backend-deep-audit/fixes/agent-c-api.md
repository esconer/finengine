# Agent C — API / portfolio / request-contract implementation report

**Scope:** C-01 through C-14 from `.scratch/backend-deep-audit/fixes/00-ISSUE-MATRIX.md`.

**Implementation boundary:** Agent C changed only the assigned API/main files,
one focused test file, and this report/evidence directory. I did not edit
services, models, schemas, migrations, config, deployment, or frontend files.
No network or real portfolio DB was used. No commit/reset/checkout/clean/stash
was performed.

## Outcome summary

| ID | Status | Implementation / proof |
|---|---|---|
| C-01 | **implemented at API seam** | `portfolio.py` now has an explicit INR/USD response contract, converts each position through the currency seam, exposes response/base currency and provenance, and rejects unsupported currencies. |
| C-02 | **implemented + tested** | Empty/zero-value books persist the first position at exactly `1.0` before commit. |
| C-03 | **implemented + tested** | Duplicate precheck, per-loop commit lock, `flush`/commit `IntegrityError` → 409, safe rollback, with the D-owned case-insensitive ticker constraint and canonical API spelling now present. |
| C-04 | **implemented + tested** | WebSocket and HTTP broadcast paths validate Host and explicit local/frontend Origin before accept/send. |
| C-05 | **implemented + tested** | Tail memo key contains normalized weights; portfolio commits and cache purge invalidate it; generation fence drops in-flight stale writes. |
| C-06 | **implemented + tested** | Optimization, backtest, Monte Carlo, volatility cone, and tail calculations use bounded `asyncio.to_thread` offload (semaphore capacity 2). |
| C-07 | **implemented + tested** | Local bounded Pydantic request models reject non-finite/out-of-range values before fetch/solve; invalid model names never fall through to another model. |
| C-08 | **implemented + tested** | Config route owns all setting upserts and one commit/rollback boundary; it does not call the committing source helper. |
| C-09 | **implemented + tested** | Commit, refresh, and response phases are separated; durable post-commit errors do not roll back or claim rollback. |
| C-10 | **implemented + tested** | Local compatible response extension discloses `submitted`, `skipped`, `duplicates`, and safe failure rows; reconciliation is exact. |
| C-11 | **implemented in owned API/main files** | Catch-all responses and logs are stable/redacted; portfolio request payload dumps and raw exception text were removed. |
| C-12 | **implemented + tested** | Formula-capable text cells are apostrophe-prefixed while `csv.writer` structure remains valid. |
| C-13 | **implemented + tested** | Typed/bounded date windows and collection caps reject impossible/reversed dates and oversized universes before vendor work. |
| C-14 | **preserved** | Loopback bind/default localhost CORS posture remains; no enterprise auth feature was added. |

## Exact implementation anchors

Line numbers below are current-tree anchors after the final integration edits;
audit citations were re-opened rather than trusted.

### Portfolio and currency

- `backend/app/api/portfolio.py:43-57` — supported INR/USD set and local
  `PortfolioSummaryEnvelope` response contract.
- `backend/app/api/portfolio.py:74-123` — currency validation and position
  currency precedence: explicit/future ORM metadata, quote metadata, then
  NSE/BSE/region convention.
- `backend/app/api/portfolio.py:126-197` — B-owned currency seam adapter. It
  prefers `convert_amount_with_provenance`, then the existing numeric seam, and
  carries only bounded provenance fields.
- `backend/app/api/portfolio.py:200-208` — weight-dependent tail memo
  invalidation; mutation call sites invoke it after durable changes.
- `backend/app/api/portfolio.py:211-215` — formula-cell neutralizer.
- `backend/app/api/portfolio.py:236-397` — per-position conversion before
  summation; `currency`, `base_currency`, `currency_provenance`, and
  `position_currencies` are returned. EUR/GBP/JPY/AED are not advertised.
- `backend/app/api/portfolio.py:400-554` — first-position effective weight,
  duplicate precheck, commit lock, integrity mapping, and post-commit phase.
- `backend/app/api/portfolio.py:558-795` — bulk duplicate/skip accounting,
  race recheck, atomic commit, and post-commit refresh separation.
- `backend/app/api/portfolio.py:1042-1091` — CSV serialization using the
  neutralizer.

### Analytics and request contracts

- `backend/app/api/analytics.py:53-181` — local bounded request models,
  finite/range validators, and typed provider-status translation.
- `backend/app/api/analytics.py:386-473` — mixed-currency conversion before
  allocation/aggregation.
- `backend/app/api/analytics.py:739-847` — forecast active-mask handling and
  interior-gap preservation.
- `backend/app/api/analytics.py:1356-1489` and `:1493-1657` — currency-aware
  summary/performance values, active coverage counts, and HTTP 503 mapping.
- `backend/app/api/analytics.py:1665-1701` and `:1920-2008` — shared wide-return
  builder and risk-contribution missingness handling.
- `backend/app/api/analytics.py:2023-2090` and `:2306-2335` — single-holding
  active-return optimization and null correlation semantics.
- `backend/app/api/websocket.py:180-218,271-407` — currency conversion,
  base/value/native currency labels, active weights, and bounded sends.

### Data/config

- `backend/app/api/data.py:44-95` — date, collection, and provider boundary
  helpers.
- `backend/app/api/data.py:98-151` — returned-window source provenance helper.
- `backend/app/api/data.py:341-446` — one API-owned config transaction,
  including B's source-switch cache fence in the same transaction.
- `backend/app/api/data.py:473-564` — typed dates, canonical ticker, and
  returned-window source provenance with service-frame fallback.
- `backend/app/api/data.py:595-645` — bounded batch collection/date validation.

### WebSocket/main

- `backend/app/api/websocket.py:30-45` — pre-accept trust check in
  `ConnectionManager.connect`.
- `backend/app/api/websocket.py:100-184` — explicit local Host and frontend
  Origin allowlists/safe host parsing.
- `backend/app/api/websocket.py:391-405` — endpoint precheck before manager
  accept.
- `backend/app/api/websocket.py:462-484` — same check on `/broadcast` before
  mutation or send.
- `backend/main.py:53-71` — awaited WebSocket task shutdown.
- `backend/main.py:93-100` — localhost CORS defaults retained.
- `backend/main.py:108-121` — generic global error response and generic log
  message (no exception/query text).

### Equity research

- `backend/app/api/equity_research.py:34-38` — stable not-found mapping that
  does not expose provider exception text.
- `backend/app/api/equity_research.py:45-265` — owned provider/error routes
  return stable 4xx/5xx responses and redacted logs.

## Before/after evidence

All executable fixtures are under
`.scratch/backend-deep-audit/fixes/evidence/` and have the `agent-c` prefix.
They import production seams, use mocks/in-memory or temporary SQLite, print
values/statuses, and state a tolerance or explicit contract assertion. The
transcription is in `agent-c-after-results.md`.

Representative deterministic results:

- C-01: `100 USD + 80 INR` converts to `8080 INR` at tolerance
  `1e-6`; mixed analytics/performance values and WebSocket totals/weights use
  the same conversion, and a provider outage maps to HTTP 503. EUR remains
  rejected with explicit provenance.
- C-02: first stored/returned weight changed from `0.2` to `1.0` (exact);
  forecast and single-holding optimization preserve interior gaps, and
  single-holding correlation returns null metrics rather than a placeholder.
- C-03: injected commit `IntegrityError` changed from 500 to 409, with one
  rollback and no raw exception text.
- C-04: evil Host/Origin changed from `accept_awaited=1` to
  `accept_awaited=0, close_awaited=1` with policy code 1008. Mixed WebSocket
  position values now carry `currency`/`value_currency=INR` plus
  `native_currency`, so converted values cannot be read as native units.
- C-05: same tickers/dates with changed weights changed from two total service
  calls to four (second EVT/coplanula pair recomputed).
- C-06: heartbeat completed before the deliberately slow optimizer while the
  route was still running.
- C-07: NaN/negative/over-horizon bodies returned 422 with zero allocation
  calls; invalid forecast model returned 422.
- C-08: combined source/cache settings had one commit; injected second-write
  failure had zero commits and one rollback.
- C-09: injected post-commit refresh failure had `commits=1, rollbacks=0` and
  a response saying the position was committed.
- C-10: duplicate row produced `skipped=1`, `duplicates=['AAPL']`, and
  `added+failed+skipped == submitted`.
- C-11: injected secret URL/API-key text was absent from response and captured
  API logs.
- C-12: `=`, `+`, and `@` cells were emitted with a leading apostrophe; CSV
  quoting/newlines remained valid.
- C-13: impossible date, reversed date, and 51-symbol collection each returned
  422 with zero vendor calls.
- C-14: `host="127.0.0.1"` remained and no authentication middleware was added.

## Tests and commands

All commands used `PYTHONDONTWRITEBYTECODE=1`, `uv run --project backend`,
`-p no:cacheprovider`, and `--no-cov` as requested.

### Passing focused gates

```text
uv run --project backend pytest -p no:cacheprovider --no-cov backend/tests/test_agent_c_api_contracts.py -q
39 passed

uv run --project backend pytest -p no:cacheprovider --no-cov backend/tests/test_api_endpoints.py backend/tests/test_agent_c_api_contracts.py -q
78 passed

uv run --project backend pytest -p no:cacheprovider --no-cov backend/tests/test_advanced_analytics.py backend/tests/test_p0405_api_guards.py backend/tests/test_bugfix_api_layer.py backend/tests/test_coverage_direct_unit_routes.py -q
32 passed

uv run --project backend pytest -p no:cacheprovider --no-cov backend/tests/test_websocket.py -q
18 passed

uv run --project backend --group dev ruff check --no-cache backend/app/api/analytics.py backend/app/api/portfolio.py backend/app/api/data.py backend/app/api/websocket.py backend/app/api/equity_research.py backend/main.py backend/tests/test_agent_c_api_contracts.py
All checks passed!
```

The focused test file contains the C-01..C-14 regressions plus mixed-currency
analytics/WebSocket/503, active-coverage, interior-gap, risk-contribution,
single-holding-correlation, and single-holding-optimizer cases. It also covers
heartbeat/event-loop behavior, atomic-config failure injection, post-commit
refresh injection, safe-log capture, and exact row reconciliation.

### Full-suite result

A historical pre-coordination no-coverage full-suite run was executed after the
last C-only edits. It reported **492 passed, 18 failed, 87 skipped, 204
warnings** in about 247 seconds. Those failures were triaged as cross-owner or
legacy-contract issues and are not used as the current acceptance claim; the
current coordinator gates are listed below.

- B currency-service legacy error wording versus the new unsupported-currency
  wording.
- Alpha Vantage/data-service/India-service and DB-gate tests affected by
  concurrent B/D service and persistence changes.
- Compose integration (Docker/other-owner state).
- One remaining equity-research 503/provider expectation outside this pass.

The focused C gate remains green after the final integration edits and is the
acceptance gate for this agent. The adjacent API/analytics/websocket gates and
Ruff gate were also green as recorded above.

## Cross-file patch recommendations (not edited)

### D — canonical uniqueness and currency persistence (C-01/C-03)

Do not add only `UniqueConstraint("ticker")`: legacy bare Indian names and
`.NS` forms can bypass that boundary. The exact model/migration direction is:

```python
# app/models/database.py (D-owned)
canonical_ticker = Column(String(20), nullable=False)
__table_args__ = (
    UniqueConstraint("canonical_ticker", name="uq_portfolio_positions_canonical_ticker"),
)
```

Backfill `canonical_ticker` before creating the constraint, deduplicate legacy
rows deterministically, and have the API write the same canonical value. If D
prefers a generated/expression index, use the equivalent unique index on the
normalized ticker. This is the remaining cross-process race authority; the C
route already serializes same-loop check/commit and maps resulting
`IntegrityError` to 409.

For C-01, add a D/B-owned persisted position currency column (or equivalent
metadata table) with a migration backfill:

```sql
-- illustrative migration direction; D owns the migration
UPDATE portfolio_positions
SET currency = CASE
  WHEN ticker LIKE '%.NS' OR ticker LIKE '%.BO' OR region IN ('IN','IND','INDIA')
  THEN 'INR' ELSE 'USD' END;
```

Then make it non-null/check-constrained to `INR`/`USD`. Until that migration,
C uses quote metadata plus the current exchange convention and returns the
provenance explicitly; it does not fabricate persistence.

### B — transaction-friendly source helper (C-08)

The current B helper commits internally. Add a no-commit primitive and retain
the existing wrapper for compatibility:

```python
async def upsert_primary_source(db, source: str) -> str:
    validated = validate_source(source)
    # execute the same upsert, but do not commit/expire here
    return validated

async def set_primary_source(db, source: str) -> str:
    saved = await upsert_primary_source(db, source)
    await db.commit()
    db.expire_all()
    return saved
```

Then the API can call `upsert_primary_source` and own the one transaction with
cache settings. C currently writes the validated upsert directly to avoid a
second commit; no service file was changed by Agent C.

### D — permanent bulk response fields (C-10)

C uses a local compatible subclass so `schemas.py` remains untouched. D may
make the extension permanent:

```python
class BulkAddResponse(BaseModel):
    # existing fields...
    submitted: int
    skipped: int
    duplicates: List[str]
    failures: List[Dict[str, str]]
```

Keep `failed` as processing failures and use `skipped` for duplicate rows so
`added + failed + skipped == submitted` remains explicit.

### B/D — integration follow-ups observed during the full run

- Preserve a stable legacy currency error message or update the B-owned test;
  do not weaken API redaction.
- Keep provider exception logs limited to exception type/status. C's owned
  routes no longer log raw exception text.
- The concurrent B data API edit briefly introduced an `await` in synchronous
  `_frame_source_for_window`; C repaired that API-file syntax/integration seam
  and added the missing `delete` import. B should review the shared handoff
  before integration.

## Unresolved / handoff items

1. **Persisted position currency remains a product migration decision.** The
   response now exposes explicit conversion provenance and native/value
   currencies, but the ORM still has no durable currency column.
2. **Permanent bulk response schema promotion is optional.** The local
   compatible response subclass keeps `submitted + skipped + failed` exact;
   a future schema cleanup can promote those fields without changing behavior.
3. **The historical full-suite result is not a current acceptance gate.** The
   current focused/integrated gates are green; a fresh all-suite run remains
   optional and was not used to broaden this remediation.
4. `CONTEXT.md` still contains the old fill prescription, but it is outside the
   allowed write scope for this pass.

## Handoff status

Agent C implementation is integrated and verified. The current focused
contract gate is **39 passed**, API endpoints + C contracts are **78 passed**,
the C/API/WebSocket/portfolio compatibility set is **115 passed**, Ruff reports
**All checks passed!**, and the coordinator integrated gate is **224 passed**.
The historical full-suite figures above are retained for traceability only.

## Coordinator reconciliation after handoff

The coordinator closed the cross-owner seams called out above without changing
the C contract:

- `backend/app/api/analytics.py` uses the shared active positive-weight helper
  in forecast, wide-return, and single-holding optimization paths, omits the
  first unmeasured performance-history return, cleans only complete samples
  for optimizer/backtest finite-matrix inputs, offloads correlation stability,
  maps provider outages to 503, counts active coverage, and threads
  `lookback_days` into `scan_pairs`.
- `backend/app/services/analytics_engine.py` exposes the shared
  `aggregate_active_returns` helper and raw inverse-volatility sizing fields.
- `backend/app/api/data.py` derives source from the returned date window,
  canonicalizes the response ticker, maps typed provider failures to stable
  statuses, threads source order into financial statements, and fences source
  switches in the config transaction.
- `backend/app/api/websocket.py` publishes null (not zero) analytics when the
  sample is unavailable, labels converted value/native currency explicitly,
  sends clients concurrently with a timeout, and awaits cancelled background
  work on last disconnect.
- `backend/app/models/schemas.py` preserves quote provenance, makes neutral
  EVT fields primary, and permits truthful null single-holding correlation.

Post-reconciliation focused results are **103 passed** for the A/B/C/D
regression files, **78 passed** for API endpoints + C contracts (the C audit
file is **39 passed**), **115 passed** for the C/API/WebSocket/portfolio gate,
**115 passed** for the provider/data compatibility set, **224 passed** for the
integrated regression set, and the coordinator evidence oracle reports **10
passed / 0 failed**. The C-owned historical full-suite figures remain
traceability only.

## Residual reviewer closure (2026-09-24)

The final residual review specifically exercised rebalance, volatility sizing,
portfolio aggregation, concentration, performance history, and WebSocket FX
failure paths. The current implementation verifies live FX provenance before
using a rate, converts each native holding into one declared INR value basis,
uses converted prices for target quantities, ignores stale stored market values
for rebalance valuation, and maps marked/unlabelled FX failures to typed HTTP
503 errors. Risk-contribution exclusions are now model-scoped under
`excluded_assets.volatility` and `excluded_assets.cvar_tail`, so a leg that is
underdetermined for covariance is not incorrectly hidden from tail attribution
or vice versa. The C audit file is **39 passed** and the focused C gate plus
API endpoints is **78 passed**; the integrated coordinator gate is **223
passed**. The separate residual quantitative gate covers one-return EWMA and
MFI masking; its evidence is recorded in the A report and final evidence
capture. A compatibility check also confirmed that direct route calls with
omitted date parameters use the validated default window rather than FastAPI
`Query` sentinels. The final independent residual review marked the C/FX/risk
contracts **PASS**.

## `/v1/models` compatibility follow-up

The reported `/v1/models` 404 was traced to an external discovery probe: no
in-repo caller, configured LLM provider, or model-serving route exists. The
backend now returns the OpenAI-shaped `{"object":"list","data":[]}` response
without fabricating model IDs. The focused API suite is **39 passed** and the
refreshed integrated set is **224 passed**. An independent read-only endpoint
verifier also returned **PASS**.

