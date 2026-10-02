# Detail — API layer (`backend/app/api/`)

**Scope of this file:** `analytics.py` (13,422 lines / 651.6 KB / 143 top-level functions),
`data.py`, `portfolio.py`. Findings `API-1` … `API-10`.

**How these were produced.** The inventory
(`plans/2026-10-audit/inventory-a1-api-services.md`) is another agent's assertion. Every citation
below was **personally opened** at the cited line by the writer of this file before emission.
Three items (`API-3`) carried `✓ ORCHESTRATOR-VERIFIED`; those were re-opened anyway. Citations
from the inventory that did **not** survive are listed in
`## Rejected on re-verification` at the end of this file — they are not silently corrected in place.

**Type discipline (plan §3.5).** Where a mechanism turns on a type or a runtime value, the resolved
type is named in the Mechanism field. Nothing here is reproduced at runtime; the two places where
arithmetic was checked (NaN propagation through Python's `min`/`max`) say so explicitly and name the
interpreter.

---

## Findings

### API-2 — `GET /analytics/tear-sheet` runs unbounded synchronous work on the event loop, skipping the module's own `_run_cpu` gate
- **Class**: bug
- **Severity**: BLOCKER
- **Confidence**: VERIFIED
- **Location**: `backend/app/api/analytics.py:9411` (quoted below); also `:9340`, `:9431`, `:9469`, `:9602`, `:9657`, `:9668`, and the skipped helper at `:205`
- **Symptom**: While one tear sheet computes, unrelated endpoints on the same worker stop responding and the websocket broadcast stops. Worst on the first call after boot, because `quantstats` is imported lazily inside the coroutine (`analytics.py:9340`) and the import itself runs on the loop.
- **Evidence**:
  ```python
  9411:        metrics = {
  9412:            "total_return": _q(qs.stats.comp, port_ret),
  9413:            "cagr": _q(qs.stats.cagr, port_ret),
  9414:            "sharpe": _q(qs.stats.sharpe, port_ret, rf=0.02),
  9415:            "sortino": _q(qs.stats.sortino, port_ret, rf=0.02),
  9416:            "calmar": _q(qs.stats.calmar, port_ret),
  9417:            "omega": _q(qs.stats.omega, port_ret),
  9418:            "tail_ratio": _q(qs.stats.tail_ratio, port_ret),
  9419:            "volatility": _q(qs.stats.volatility, port_ret),
  9420:            "max_drawdown": _q(qs.stats.max_drawdown, port_ret),
  ```
- **Mechanism**: (1) `_q` (`analytics.py:526`) is a plain `def` that calls the `quantstats` statistic inline, and the `metrics` dict at 9411 invokes it eleven times on the loop. (2) The same handler then runs **five** uncertainty blocks — `_tear_sheet_uncertainty` at 9431, 9469, 9602 and 9668 plus `_tear_sheet_relative_uncertainty` at 9657 — each a plain sync `def` (`:594`) that calls `measure_estimate_uncertainty` (`analytics_engine.py:1428`), whose `resamples` parameter defaults to `UNCERTAINTY_BOOTSTRAP_RESAMPLES` = **1000** (`analytics_engine.py:921`, bound at `:1436`). (3) `_run_cpu` (`analytics.py:205`) exists for exactly this and is acquired at only six call sites in the whole file — 10325, 10482, 10828, 10923, 12330, 12541 — none of them in this handler.
- **Impact**: Availability of every other route on the worker, not a published figure. `/tear-sheet` is also the **only** heavy analytics route with no response cache: `analytics.py:9327` declares the route and the file's only `_RESPONSE_CACHE` is `_TAILS_RESPONSE_CACHE` (`:12359`, TTL 900 s at `:12357`). A control search for `TEAR_SHEET_CACHE|TEARSHEET_CACHE` returns zero while `_RESPONSE_CACHE` returns six. Wall-clock duration is **not measured** — severity rests on the structural fact that synchronous CPU work runs on the loop, which is verifiable in source.
- **Suggested fix**: Shape only — wrap the `metrics` dict construction and the five uncertainty blocks in `await _run_cpu(...)`, and move `import quantstats` to module scope or into the worker thread. Blast radius is one handler. **Ordering hazard**: the five uncertainty blocks read `metrics` and `relative`, so they must be moved as a unit or the metrics will be bound before it is computed. `_run_cpu` uses a per-loop `asyncio.Semaphore(2)` (`:196-202`), so tear-sheet CPU work will queue behind `/tails` and `/vol-cone` rather than starving them — that is the intent, but it converts a loop stall into request latency and the 900 s `/tails` cache means the queue position becomes user-visible.

### API-1 — `bulk_add` accepts an uncapped position list and validates it one vendor round-trip at a time
- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `backend/app/models/schemas.py:374` (no cap) and `backend/app/api/portfolio.py:1335` (serial fan-out)
- **Symptom**: A bulk-add body with thousands of positions takes thousands of sequential vendor round-trips and does not return; whatever gateway timeout fronts the service fires first.
- **Evidence**:
  ```python
  1335:        invalid_tickers = [
  1336:            pos_data.ticker for pos_data in validated_positions
  1337:            if not await data_service.validate_ticker(pos_data.ticker, strict_errors=True)
  1338:        ]
  ```
- **Mechanism**: (1) `BulkAddRequest.positions` is a bare `List[PortfolioPositionBase]` with no `max_length`, so Pydantic admits any length. (2) `await` inside a list comprehension is strictly serial — there is no `gather` and no semaphore, unlike the same route's own later `sem = asyncio.Semaphore(5)` at `portfolio.py:1363`. (3) `DataService.validate_ticker` (`data_service.py:1117`) is a live cascade: `await self._resolve_source_order()` (a DB read) then, per source, `asyncio.to_thread(_bf_validate)` / `_yf_validate`, the latter doing `yf.Ticker(stock).history(period="5d")` — a network fetch.
- **Impact**: Request latency and upstream vendor quota consumption. **Not measured**: the wall-clock and whether upstream rate-limiting actually spills onto other callers. Three sibling schemas in the same codebase do cap, which is what makes this an omission rather than a policy: `analytics.py:133`, `:135`, `:168`, `:184` all carry `max_length=_MAX_TICKERS` (50, defined at `:119`) and `data.py:77-78` caps a ticker list at `_MAX_COLLECTION_SIZE = 50` (`:44`).
- **Suggested fix**: Shape only — add `Field(..., max_length=50)` to `BulkAddRequest.positions`, and if bulk semantics genuinely need more, replace the comprehension with `asyncio.gather` under a bounded semaphore rather than removing the cap. Blast radius is one request schema plus one loop. **Ordering hazard**: `invalid_tickers` must be collected *before* the existing duplicate pass at `portfolio.py:1345`, which reads the DB under `_portfolio_lock()`; gathering without preserving that ordering deadlocks against the lock held at 1347.

### API-3 — Two no-data branches stamp `as_of` with today and one of them labels a non-existent observation "latest available"
- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `backend/app/api/analytics.py:11920` (worst case) and `:10891`; honest sibling at `:11952-11953`
- **Symptom**: A book with fewer than two usable names renders a fresh "as of today" stamp beside an empty chart. On `/coint` the same payload simultaneously asserts `as_of = today`, `as_of_semantics = "latest_available_observation"` and `latest_observation_date = null` — three fields that cannot all be true.
- **Evidence**:
  ```python
  11919:            response = CointScannerResponse(
  11920:                as_of=datetime.now().strftime("%Y-%m-%d"),
  11921:                latest_observation_date=None,
  11922:                as_of_semantics="latest_available_observation",
  ```
- **Mechanism**: (1) The `< 2 tickers` branch at `:11917` builds the response before any price fetch has happened, so there is no observation for `as_of` to name. (2) `datetime.now()` supplies a request-time stamp that reads as a data timestamp. (3) The token at 11922 asserts an observation exists; the sibling no-data branch 30 lines later does it correctly — `as_of=end` with `as_of_semantics="request_end_no_usable_price_data"` (`:11952-11953`) — and the honesty there comes from the **token**, not from a different date value.
- **Impact**: `as_of` on `CointScannerResponse` and `as_of` on `CorrelationStabilityResponse` (`:10891`). No financial figure is affected — both payloads also carry `data_status: "unavailable"`, which is the mitigating disclosure. Compounding: `CorrelationStabilityResponse` (`schemas.py:403-461`) has **no** `as_of_semantics` field at all (fields run `as_of` … `universe_coverage` at `:461`), so that endpoint's consumer has no machine-readable way to detect the stamp's provenance, unlike the coint consumer.
- **Suggested fix**: Shape only — on both no-data branches publish a token that names the request end and say no observation exists (mirror `:11952`), and add an `as_of_semantics` field to `CorrelationStabilityResponse` with the same closed vocabulary `CointScannerResponse` already uses. Blast radius is two branches plus one schema; no numeric value moves. **Ordering hazard**: none — neither branch has awaited a fetch at that point.

### API-5 — `/analytics/liquidity-limits` fetches one position at a time while its sibling on the same dashboard fans out 5-wide
- **Class**: optimisation
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `backend/app/api/analytics.py:12241` (sequential) versus `:7475` (5-wide gather on the sibling)
- **Symptom**: On the same book, the liquidity-limits card takes one vendor round-trip per position back to back while the liquidity card beside it returns in seconds.
- **Evidence**:
  ```python
  12241:        for p in positions:
  12242:            try:
  12243:                df = await data_service.fetch_historical_data(p.ticker, start, end)
  12244:            except Exception as exc:
  12245:                fetch_failures[p.ticker] = type(exc).__name__
  12246:                logger.warning("Liquidity history unavailable for %s: %s", p.ticker, type(exc).__name__)
  12247:                continue
  12248:            if df is not None and not df.empty:
  12249:                price_dfs[p.ticker] = df
  ```
- **Mechanism**: (1) The `await` at 12243 is inside a plain `for`, so the P fetches serialise: wall-clock ≈ P × per-fetch latency. (2) The sibling `/analytics/liquidity` at `:7475-7491` builds the identical work under `asyncio.Semaphore(5)` + `asyncio.gather`, giving ≈ P/5 × per-fetch latency. (3) The contrast is *within one file*, which is what makes this a defect of shape rather than a policy: the same author wrote both.
- **Impact**: Response time of `GET /analytics/liquidity-limits`. **Cited cost, not measured**: the call-site count is `len(positions)` serial `fetch_historical_data` awaits versus a 5-wide gather over the same list. Per-fetch latency is unmeasured, so no wall-clock figure is claimed — which is why this is capped at RISK rather than a defect. Amplifier: the DB branch at `:12202` (`select(PortfolioPosition)`) applies no `_MAX_TICKERS` cap, unlike `:8814-8815`, which 422s above 50 — so the serial loop's length is bounded only by the user's own book size.
- **Suggested fix**: Shape only — lift the `sem = asyncio.Semaphore(5)` + `asyncio.gather` shape from `:7475-7491` into the limits loop, preserving the `fetch_failures` dict keyed by ticker. Blast radius is one loop. **Ordering hazard**: `fetch_failures` is read at `:12263` (`sorted(fetch_failures)`) for the coverage disclosure, so results must be reassembled after the gather, not appended to during it, or the failed-ticker list races the response.

### API-4 — No endpoint paginates; the response bodies are materialised row by row up to ~125,000 objects
- **Class**: risk
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `backend/app/api/data.py:44`, `:46`, `:556`, `:639`
- **Symptom**: A legal batch request at the maximum permitted ticker count and date range returns a single response body holding on the order of 125,000 price objects.
- **Evidence**:
  ```python
  636:        for ticker, df in results["data"].items():
  637:            if not df.empty:
  638:                stock_responses = []
  639:                for _, row in df.iterrows():
  640:                    stock_responses.append(StockDataResponse(
  641:                        ticker=ticker,
  642:                        date=row['date'],
  643:                        open=float(row['open']),
  ```
- **Mechanism**: (1) `_MAX_COLLECTION_SIZE = 50` (`:44`) and `_MAX_DATE_RANGE_DAYS = 3650` (`:46`) cap the *request* — `_bounded_tickers` rejects above 50 at `:77-78` and `_date_window` rejects above 3650 days at `:69-70`. (2) Nothing caps the *response*. (3) `df.iterrows()` at 639 yields one row at a time and constructs a Pydantic model per row, so the whole result set is resident as Python objects before serialisation. 50 tickers × 3650 calendar days ≈ 2520 trading days each ≈ 126,000 rows.
- **Impact**: Response size, serialisation time and client memory on `GET /data/stocks/batch` and `GET /data/stocks/{ticker}/timeseries`. **Proof of absence**: `Select-String` for `offset` across `backend/app/api/*.py` returns one hit, and it is a comment (`portfolio.py:283`); `limit` returns many hits, every one of them the substring inside `limited_history`, `rate_limit` or `depth_limited`. Same cmdlet, same file set, so the search is live.
- **Suggested fix**: Shape only — add optional `limit`/`offset` query parameters to the two timeseries routes with sane defaults, and consider `df.to_dict("records")` or a vectorised construction instead of `iterrows()`. Blast radius is two routes plus any client that relies on receiving the full array. **Ordering hazard**: none, but the default must remain "no limit" until clients are cut over, or existing dashboards silently truncate.

### API-10 — Tear-sheet metric failures are logged at `debug` with no metric name and no exception type
- **Class**: bug
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `backend/app/api/analytics.py:537` (root), `:9710`, `:9718`
- **Symptom**: Every metric on the tear sheet can silently become `null` and the operator's log shows nothing above debug level, with no way to tell which metric failed or why.
- **Evidence**:
  ```python
  526: def _q(metric_fn, *args, **kwargs):
  527:     """Guard a single quantstats metric call; API drift must not kill the sheet."""
  528:     try:
  529:         val = metric_fn(*args, **kwargs)
  536:     except Exception:  # noqa: BLE001
  537:         logger.debug("quantstats metric unavailable")
  538:         return None
  ```
- **Mechanism**: (1) `_q` catches bare `Exception` at 536 and calls `logger.debug` at 537 with a fixed string — no `type(exc).__name__`, no `exc_info`, and no reference to `metric_fn`, so the eleven call sites at `:9412-9422` are indistinguishable in the log. (2) The `except` swallows the failure and returns `None`, which is indistinguishable in the payload from a genuinely undefined metric. (3) The same handler does it twice more — `logger.debug("Monthly returns unavailable")` at 9710 and `logger.debug("Drawdown series unavailable")` at 9718.
- **Impact**: Diagnostics for a null-valued tear sheet, not a wrong number. The contrast is inside the same file: `Select-String` for `logger.debug` returns exactly five hits (537, 9016, 9710, 9718, 10715) and every other handler logs its failure at `error`/`warning` with the exception type (e.g. `:7481`, `:12246`).
- **Suggested fix**: Shape only — log at `warning` with `exc_info=True` and include `getattr(metric_fn, "__name__", repr(metric_fn))` plus `type(exc).__name__`. Blast radius is one log call. **Do not** change the `return None` — degrading to null is the documented behaviour and is correct; only the observability is wrong.

### API-8 — `holding_provenance`'s `frames` parameter has zero call sites, so all five callers re-fetch the window they already hold
- **Class**: improvement
- **Severity**: RISK
- **Confidence**: DERIVED
- **Location**: `backend/app/api/analytics.py:2318` (parameter), duplicate fetch at `:2345`, five callers at `:7009`, `:8902`, `:9354`, `:9858`, `:10685`
- **Symptom**: None user-visible — developer-facing.
- **Evidence**:
  ```python
  2316:    *,
  2317:    end: Any,
  2318:    frames: Optional[Dict[str, pd.Series]] = None,
  2319: ) -> Dict[str, Any]:
  2320:     """THE holding-window start rule, for every section that publishes one.
  ```
- **Mechanism**: (1) `frames` is declared to accept "price frames the caller already holds" (docstring `:2326`) so the canonical slice can be taken without a second read. (2) `Select-String` for `frames=` across `analytics.py` returns **zero** hits; `holding_provenance(` returns six (the def plus five callers) — same cmdlet, same file, so the negative is live. (3) Every caller therefore falls into the branch at `:2340` and re-fetches via `_fetch_price_series_dict` at `:2345`.
- **Impact**: Potential extra `fetch_historical_data` calls per request across five endpoints. **The cost is DERIVED, not measured**: the docstring at `:2329-2331` asserts the read "is served from the cache that leg populated rather than from the vendor", and the ranges differ (the leg uses the requested window, provenance uses the canonical `window["start"]`), so whether this is a cache hit or a live vendor round-trip per position needs a runtime trace. Confidence is DERIVED for that reason; the dead parameter itself is verified.
- **Suggested fix**: Shape only — pass each caller's already-fetched frames through `frames=`, then delete the fallback fetch at 2340-2354 **only after** all five call sites are converted. Blast radius is five call sites. **Ordering hazard**: the fallback at 2345 has an `except` that deliberately degrades to stored dates with a `provenance_divergence_reason` disclosure; removing it before every caller supplies frames would drop that disclosure on the paths that still need it.

### API-7 — Unreachable duplicate `except HTTPException: raise` in `/vol-cone`
- **Class**: maintainability
- **Severity**: NIT
- **Confidence**: VERIFIED
- **Location**: `backend/app/api/analytics.py:12347`
- **Symptom**: None — developer-facing.
- **Evidence**:
  ```python
  12343:    except HTTPException:
  12344:        raise
  12345:    except ValueError:
  12346:        raise HTTPException(status_code=400, detail="Invalid analytics request")
  12347:    except HTTPException:
  12348:        raise
  12349:    except Exception:
  ```
- **Mechanism**: (1) Python matches `except` clauses top to bottom and the first `except HTTPException` at 12343 already handles that type. (2) The clause at 12347 is therefore dead: it can never be selected for an `HTTPException`. (3) A reader editing 12345-12346 to change the 400 path has to reason about a handler that cannot fire.
- **Impact**: None — developer-facing, no user-visible effect. No wrong number, no latency.
- **Suggested fix**: Delete lines 12347-1248's duplicate pair. Blast radius is nil; nothing reads the removed branch.

### API-9 — `/tail-dependence` and `/tails` are stacked decorators on a single handler
- **Class**: maintainability
- **Severity**: NIT
- **Confidence**: VERIFIED
- **Location**: `backend/app/api/analytics.py:12496-12497`
- **Symptom**: None — developer-facing.
- **Evidence**:
  ```python
  12496: @router.get("/tail-dependence")
  12497: @router.get("/tails")
  12498: async def get_tail_risk_and_copula(
  12499:     tickers: Optional[str] = Query(default=None, description="Comma-separated tickers or portfolio"),
  ```
- **Mechanism**: (1) Two `router.get` decorators register the same function under two paths, so a route reader scanning for `/tails` finds it only by reading the stacked pair. (2) Both paths share one 900 s response cache (`:12357`, `:12524`) keyed on `cache_key`, which is correct — this is a legibility item, not a caching defect.
- **Impact**: None — developer-facing. Worth noting the cache is genuinely shared and correct; the finding is the decorator shape only.
- **Suggested fix**: If the alias must stay, add a one-line comment naming which path is canonical. If it need not, register the alias explicitly in the router setup. Blast radius is nil either way — do **not** split the handler, since both paths intentionally share the O(n²) copula fit and its cache.

### API-6 — `analytics.py` is 13,422 lines and 651.6 KB with 143 top-level functions on one router
- **Class**: maintainability
- **Severity**: NIT
- **Confidence**: VERIFIED
- **Location**: `backend/app/api/analytics.py` (whole file); measured 13,422 lines, 651.6 KB, 143 top-level `def`/`async def`
- **Symptom**: None — developer-facing.
- **Evidence**:
  ```python
  9327: @router.get("/tear-sheet")
  9328: async def get_tear_sheet(
  ```
- **Mechanism**: (1) One module carries every analytics concern, so 24 handlers share one namespace. (2) The concrete cost is already realised: `API-2` was missable precisely because a reader of endpoint #11 has no structural signal that endpoints #1-#10 used `_run_cpu`. (3) The file's own largest functions span 300-800 lines each (`get_cointegration_pairs`, `get_realized_risk`, `_forecast_precision_block`, `get_tear_sheet`).
- **Impact**: None — developer-facing, no user-visible effect. Reported at NIT for that reason; the defect it enabled is `API-2` above, which carries its own row.
- **Suggested fix**: Shape only — split by concern (portfolio-risk, distribution/tails, forecasting, diagnostics) along the existing `# --- Section ---` comment boundaries. Blast radius is import-path churn across the app and the test suite; this is a multi-PR change and should not be bundled with any of the fixes above.

---

## Rejected on re-verification

Every entry below is an assertion from `plans/2026-10-audit/inventory-a1-api-services.md` that did
**not** survive opening the file. The parent findings above were re-derived from source and stand on
their own citations; only the listed sub-claims were rejected.

### 1. `API-1` contrast citation `analytics.py:955` with `max_length=50` — **REJECTED (wrong line)**
`analytics.py:955` reads `metrics_observations = int(metrics_record["observations"])`. There is no
`max_length` on that line. `Select-String` for `max_length` across `analytics.py` returns exactly
four hits — `:133`, `:135`, `:168`, `:184` — all `Field(default=None, max_length=_MAX_TICKERS)`.
**The contrast survives**; the citation does not. `API-1` cites the corrected lines.

### 2. `API-2` endpoint labels `/optimize` and `/regime` — **REJECTED (misidentified routes)**
Resolving each `_run_cpu` call site to its nearest preceding `@router` decorator gives:
`:10325` → `POST /optimize/run` (declared at `:10176`), `:10482` → `POST /backtest` (`:10443`),
`:10828` → `POST /monte-carlo` (`:10759`), `:10923` → `GET /correlation-stability` (`:10870`),
`:12330` → `GET /vol-cone` (`:12303`), `:12541` → `GET /tails` (`:12497`).
The inventory named `/optimize` (actually `/optimize/run`) and `/regime` (actually `/monte-carlo`).
**The load-bearing claim survives intact**: all six `_run_cpu` call sites are outside
`get_tear_sheet`.

### 3. `API-2` "`_tear_sheet_uncertainty` runs 3× per request" — **REJECTED UNDERCOUNT (it is 5)**
`Select-String` for `_tear_sheet_uncertainty` returns the definition at `:594` and **five** call sites
inside the tear sheet: `:9431`, `:9469`, `:9602`, `:9668`, plus `_tear_sheet_relative_uncertainty` at
`:9657`. The finding above states 5.

### 4. `API-2` `/tails` response cache cited at `:12359` — **REJECTED (line drift, substance holds)**
`_TAILS_CACHE_TTL_SECONDS = 900` is at `:12357`. `:12359` is
`_TAILS_RESPONSE_CACHE: Dict[Tuple, Tuple[float, Dict[str, Any]]] = {}`. Both now cited.

### 5. `API-8` `frames` parameter cited at `:2317` — **REJECTED (off by one)**
`:2317` is `end: Any,`. `frames` is declared at `:2318`.

### 6. `API-2` and `API-1` unmeasured claims — **NOT VERIFIABLE BY READING, SCOPED OUT**
Two assertions in the inventory are runtime claims, not source facts, and are **not** carried into
the findings: (a) "hangs past any gateway timeout" and (b) "the provider … rate-limits, breaking the
*next* legitimate request". `API-1`'s finding is scoped to the two verified constructs (no schema cap,
serial live-vendor fan-out) and its Impact field says so. Neither claim is asserted anywhere in
these files.

---

## Notes for the assembler

- **Ordering:** 1 BLOCKER, 2 DEFECT, 4 RISK, 3 NIT = 10 findings — all below the §1-§4 caps.
- **No `path:line` in this file is duplicated** across these findings, and none collides with a
  `services.md` citation except where the same line is genuinely load-bearing for two different
  claims (noted inline where it occurs).
- **Cross-file pointer:** `SVC-2` and `SVC-1` (`services.md`) are the same class of defect as
  `API-3` — a value published where the honest value is "unmeasured". They are separate defects at
  separate locations and must not be deduped against each other or against `API-3`.
- **Not emitted as findings:** the services cache inventory from the same input file is a *positive*
  claim (the layer is in good shape) and has no place in a defect ledger. It is addressed in
  `services.md` under `## Reviewed, not emitted as findings`, including the fact that **every one of
  its citations names the wrong source file**.