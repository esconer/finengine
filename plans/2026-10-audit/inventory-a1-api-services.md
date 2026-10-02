# Inventory slice A1 — Backend API + Services

Source: Phase 1 read-only explorers. **Every item below was re-verified against source by the
orchestrator for the top items** (marked ✓). All others are explorer-asserted and the writer MUST
re-verify before emitting a ledger row.

Tooling: **`rg -F` does NOT fix the quote trap** — a single `"` in a pattern silently returns zero
on this machine. Use `Select-String` (verified working) or a quote-free pattern. Any "no matches"
claim needs a control search that matches. Default `rg` respects `.gitignore`.

---

## API layer — `backend/app/api/` (`analytics.py` 13,422 lines, 651 KB, 143 top-level fns, 1 router, 25 decorator lines → 24 handlers, 25 paths)

### API-1 — `bulk_add`: uncapped, sequential, live-vendor fan-out
- **Class** bug · **Sev** high · **Conf** confirmed
- **Loc** `backend/app/models/schemas.py:374` (no cap) + `backend/app/api/portfolio.py:1335-1338`
- **Symptom** A bulk-add body with thousands of entries hangs past any gateway timeout; the provider
  absorbs thousands of validation calls and rate-limits, breaking the *next* legitimate request.
- **Evidence**
```python
# schemas.py:372-375
class BulkAddRequest(BaseModel):
    positions: List[PortfolioPositionBase]      # no max_length
    auto_normalize: bool = True
# portfolio.py:1335-1338  -- await inside a list comprehension is strictly serial
invalid_tickers = [
    pos_data.ticker for pos_data in validated_positions
    if not await data_service.validate_ticker(pos_data.ticker, strict_errors=True)
]
```
- **Contrast (proves the pattern exists elsewhere)** `analytics.py:133` `max_length=_MAX_TICKERS`(50),
  `analytics.py:955` `max_length=50`, `data.py:44` `_MAX_COLLECTION_SIZE = 50`.

### API-2 — `GET /analytics/tear-sheet` blocks the event loop
- **Class** bug · **Sev** high · **Conf** confirmed (structure) / needs-runtime (wall-clock)
- **Loc** `analytics.py:9340, 9411-9423, 9431, 9657, 9668, 9714`; helper `analytics.py:205`
- **Symptom** While the tear sheet computes, unrelated endpoints queue behind it and the websocket
  broadcast stops. Worst on first call after worker boot (lazy import on the loop).
- **Evidence**
```python
# analytics.py:9340 — lazy import inside the coroutine
        import quantstats as qs
# analytics.py:205 — the helper that exists for exactly this
async def _run_cpu(...):   # per-loop semaphore of 2
```
- **Contrast** `_run_cpu` is used by `/optimize`, `/backtest`, `/regime`,
  `/correlation-stability`, `/vol-cone`, `/tails` (call sites 10325, 10482, 10828, 10923, 12330,
  12541). `/tear-sheet` is the heaviest endpoint and skips it.
- **Amplifier** `_tear_sheet_uncertainty` runs 3× per request and calls
  `measure_estimate_uncertainty` (`analytics_engine.py:1428`) — a **synchronous** function with
  `UNCERTAINTY_BOOTSTRAP_RESAMPLES = 1000` (`analytics_engine.py:921`). `/tails` has a 900 s
  response cache (`:12359`); `/tear-sheet` has none.

### API-3 — Fabricated `as_of` on the no-data branch, still ungated  ✓ ORCHESTRATOR-VERIFIED
- **Class** bug · **Sev** medium · **Conf** confirmed
- **Loc** `analytics.py:10891` and `:11919-11922`; honest contrast at `:11952`
- **Symptom** A single-holding book renders a fresh "as of today" stamp beside an empty chart with
  `data_status: "unavailable"`. On `/coint` the payload asserts `as_of = today`,
  `as_of_semantics = "latest_available_observation"` AND `latest_observation_date = null`.
- **Evidence**
```python
# analytics.py:10890-10892
            return CorrelationStabilityResponse(
                as_of=datetime.now().strftime("%Y-%m-%d"),
                current_avg_correlation=None,
# analytics.py:11919-11922
            response = CointScannerResponse(
                as_of=datetime.now().strftime("%Y-%m-%d"),
                latest_observation_date=None,
                as_of_semantics="latest_available_observation",
# analytics.py:11952 — the OTHER no-data branch, honest token
                as_of_semantics="request_end_no_usable_price_data",
```
- **Compounding** `CorrelationStabilityResponse` (`schemas.py:403-428`) has **no** `as_of_semantics`
  field at all, so that endpoint's consumer cannot detect the fabrication.

### API-4 — Unbounded response lists, no pagination anywhere
- **Class** risk · **Sev** medium · **Conf** confirmed
- **Loc** `backend/app/api/data.py:44,46,556-566,636-650`
- **Symptom** 50 tickers × 3650 days ≈ 125,000 `StockDataResponse` objects in one body.
- **Evidence**
```python
# data.py:44-46
_MAX_COLLECTION_SIZE = 50
_MAX_DATE_RANGE_DAYS = 3650
# data.py:639 — materialised row by row
                for _, row in df.iterrows():
```
- **Proof of absence** no endpoint in `backend/app/api/` accepts `limit` or `offset`.

### API-5 — `/analytics/liquidity-limits` fetches sequentially; its sibling fans out 5-wide
- **Class** optimisation · **Sev** medium · **Conf** confirmed
- **Loc** `analytics.py:12241-12249` (sequential) vs `:7475-7491` (5-wide gather)
- **Symptom** For a 40-position book the endpoint takes ~40 sequential vendor round-trips while
  `/analytics/liquidity` over the same book returns in seconds. Both cards are on one dashboard.
- **Amplifier** the DB branch at `:12202` applies no `_MAX_TICKERS` cap, unlike `:8814` which 422s.

### API-6 — `analytics.py` is 13,422 lines / ~13 concerns on one router
- **Class** maintainability · **Sev** low · **Conf** confirmed
- **Loc** whole file
- **Symptom** none user-visible. Largest functions: `get_cointegration_pairs` 805,
  `get_realized_risk` 715, `_forecast_precision_block` 704, `get_tear_sheet` 491,
  `get_performance_history` 426, `get_volatility_sizing` 380.
- **Why it matters** this size is *why API-2 was missable* — 24 endpoints share one module, so a
  reader of endpoint #11 has no structural reason to check whether it used `_run_cpu`.

### API-7 — Dead duplicate `except HTTPException: raise` in `/vol-cone`
- **Class** maintainability · **Sev** nit · **Conf** confirmed · **Loc** `analytics.py:12343,12347`

### API-8 — `holding_provenance`'s `frames` param has zero call sites; 5 callers double-fetch
- **Class** improvement · **Sev** low · **Conf** confirmed (dead param) / needs-measurement (cost)
- **Loc** `analytics.py:2317` (param), callers `:7009, :8902, :9354, :9858, :10685`, dup at `:2345`

### API-9 — `/tail-dependence` and `/tails` are stacked decorators on one handler
- **Class** maintainability · **Sev** nit · **Conf** confirmed · **Loc** `analytics.py:12496-12497`

### API-10 — Tear-sheet metric failures logged at `debug`, become `null` silently
- **Class** bug · **Sev** low · **Conf** confirmed · **Loc** `analytics.py:526-538, 9709-9710, 9717-9718`
- **Evidence** `logger.debug("quantstats metric unavailable")` — no `type(exc).__name__`, no metric
  name. Every other handler logs at `error`/`warning` with the exception type (`:1164, :7481`).

---

## Services — `backend/app/services/`

### SVC-1 — `liquidity_analysis` publishes a measured worst-case score from a NaN volume  ✓ VERIFIED
- **Class** bug · **Sev** high · **Conf** confirmed (path deterministic) / needs-measurement (frequency)
- **Loc** `analytics_engine.py:3945-3947, 3971-3973`; caller `analytics.py:7557`
- **Symptom** When `Volume` is entirely unparseable, `mean()` is NaN, every `nan >= X` tier test is
  False, control reaches the Tier-4 `else`, and the position publishes `score = 3.0`,
  `category = "Low"`, `liquidation_days = "5-10"`, `risk_level = "High"` — a confident worst-case
  verdict derived from no data.
- **Evidence**
```python
3945:                volume = float(df[vol_col].mean())
3946:                price = float(df[close_col].iloc[-1]) if close_col and not df.empty else 0.0
3971:                else:
3972:                    score_raw = max(2.5, min(5.9, 3.0 + (daily_turnover / 2e7) * 2.9))
```
- **Inconsistency proof** the same function guards the analogous case at `:4002`
  (`... if volume_stats['volumes'] else 0.0`). `_market_cap_provenance` also takes its INR 1bn floor.

### SVC-2 — `sharpe_ratio` / `sortino_ratio` publish `0.0` on a zero denominator  ✓ VERIFIED
- **Class** bug · **Sev** high · **Conf** confirmed
- **Loc** `analytics_engine.py:5468` and `:5476`; docstring `:5439-5447`; `<10` branch fixed to `None`
- **Symptom** Every realized-risk block publishes `sharpe_ratio: 0.0` for a zero-dispersion series —
  a single-ticker flat window, or a stale frame surviving the 10-day gate.
- **Evidence**
```python
5468:                sharpe_ratio = float((annual_return - self.risk_free_rate) / annual_volatility) if annual_volatility > 0 else 0.0
5476:                sortino_ratio = float((annual_return - self.risk_free_rate) / downside_deviation) if downside_deviation > 0 else 0.0
```
- **The damning part** the method's own docstring says "a 0.0 Sharpe is indistinguishable from a
  measured zero, which is what makes a hard zero on an unmeasured quantity the one number a reader
  must never be handed" — and the `<10` branch was fixed to publish `None` for exactly this reason.
  The fix was applied to the short-sample path and **not** the zero-variance path.
- **Amplifier** `_estimate_uncertainty_block` bootstraps around the published value → the band is
  computed around a fabricated centre.

### SVC-3 — `_store_timeseries_data` / `check_data_integrity` execute outside `_db_lock`
- **Class** risk · **Sev** medium · **Conf** confirmed (unlocked) / needs-measurement (collision)
- **Loc** `data_service.py:1664, 1700-1704, 1797-1832`; caller without lock at `:1339`
- **Evidence**
```python
1700:            await self.db.execute(stmt)
1701:            if not cache_generation_is_current(write_generation):
1702:                await self.db.rollback()
1704:            await self.db.commit()
```
- **Invariant being broken** `data_service.py:238-243` states in the authors' own words that
  SQLAlchemy sessions are not concurrency-safe. Two of three callers honour it (`:704, :771`); the
  Alpha Vantage path at `:1339` does not, and the function itself takes no lock.
- **Fix-shape warning** a naive wrap **deadlocks** — `asyncio.Lock` is not re-entrant and callers at
  `:704`/`:771` already hold it.

### SVC-4 — `screener_service._filter` converts absent fundamentals into `0.0`
- **Class** bug · **Sev** medium · **Conf** suspected (substitution confirmed; prevalence unmeasured)
- **Loc** `screener_service.py:317-335`
- **Evidence**
```python
317:            roce = info.get("returnOnCapitalEmployed") or 0.0
318:            roe = (info.get("returnOnEquity") or 0.0) * 100
319:            pe = info.get("trailingPE") or 999.0
326:            if min_roce is not None and roce < min_roce:
```
- **The asymmetry** `pe` gets `999.0` (excludes); `roce`/`roe`/`mcap` get `0.0` which, against a
  *lower* bound, **admits**. The same file gets this right at `:354-359` (`pd.notna(...) else None`).
- **Scale question** `:317` reads ROCE raw while `:318` scales ROE `* 100` — worth checking against
  bfinance's `info` schema, which this run could not read.

### SVC-5 — `IndiaDataService` shares the request session and has **no lock at all**
- **Class** risk · **Sev** medium · **Conf** confirmed
- **Loc** `india_data_service.py:105-106, 164-226, 259-316`; constructed at
  `analytics.py:12095/12147/12252`, `portfolio.py:107`
- **Evidence**
```python
105:    def __init__(self, db: AsyncSession):
106:        self.db = db
```
- **Proof of absence** `Select-String` for `_db_lock|Lock` in that file → **0 matches**. Ten
  `db.execute`/`commit` sites, none guarded. So the mutual exclusion `data_service.py:238-243` was
  written to guarantee **does not hold across the two services**.
- **Fix-shape warning** two independent per-instance locks would still not exclude each other; the
  lock must be session-scoped.

### SVC-6 — `backtest_service` silently shortens `lookback_days`, publishes no disclosure
- **Class** bug · **Sev** medium · **Conf** confirmed
- **Loc** `backtest_service.py:65-67`; route `analytics.py:10479` (422s below 30 rows), `:10495`
- **Evidence**
```python
65:    if len(returns) < lookback_days + rebalance_freq_days:
66:        lookback_days = max(20, int(len(returns) * 0.4))
67:        rebalance_freq_days = max(5, int(len(returns) * 0.1))
```
- **Symptom** a caller who asked for 252 days and got a 24-row run cannot tell from the payload.
  `rebalance_events[].weights` are the most misleading artifact.

### SVC-7 — `backtest_service` annualises with no `MIN_ANNUALIZE_DAYS` gate
- **Class** bug · **Sev** medium · **Conf** confirmed (gate absent)
- **Loc** `backtest_service.py:185-207`
- **Evidence**
```python
185:    n_days = len(strat_rets)
186:    years = n_days / TRADING_DAYS
188:    strat_cagr = float((strat_cum[-1]) ** (1.0 / years) - 1.0) if years > 0 else 0.0
```
- **The rule being skipped** `app/utils/holdings.py:32-35`: below 30 covered days, annualized ratios
  are not reported — "annualizing a week of history fabricates triple-digit percentages". The `years
  > 0` guard is true for `n_days == 1`, yielding `(1+r) ** 252`.

### SVC-8 — `compute_rolling_avg_correlation` averages over a shrinking pair denominator
- **Class** bug · **Sev** medium · **Conf** confirmed
- **Loc** `correlation_service.py:54-62`; endpoint `analytics.py:10923-10927`
- **Evidence**
```python
57:            pair_corr = s1.rolling(window=window_days, min_periods=min_periods).corr(s2)
62:    avg_corr_series = pairs_df.mean(axis=1).dropna()
```
- **Symptom** a date where 2 of 45 pairs are measurable publishes the mean of those 2 under the label
  "average pairwise correlation". `min_periods = min(window_days, 30)` (`:50`) is what produces the
  NaNs. The docstring's own formula `(2/(N(N-1))) * sum rho_ij` silently assumes all pairs contributed.
- **Propagation** the result feeds the 75th/90th percentile thresholds → `alert_level`,
  `is_regime_break`.

### SVC-9 — `equity_research_service` publishes `current_price: 0.0`
- **Class** bug · **Sev** low · **Conf** suspected · **Loc** `equity_research_service.py:57, 231`
- **Evidence**
```python
57:            cmp = r.current_price or info.get("currentPrice") or 0.0
59:            if graham_num and cmp and cmp > 0:
```
- **Note** `graham_upside` is correctly guarded, so no derived figure is corrupted — but the raw
  field ships as ₹0. Sibling fields at `:87-98` correctly end as `None`.

### SVC-10 — `calculate_bivariate_tail_dependence` substitutes `nu = 4.0` on a failed t-fit
- **Class** bug · **Sev** low · **Conf** confirmed
- **Loc** `tail_risk_service.py:498-503`
- **Evidence**
```python
501:                nu = float(np.clip((df_a + df_b) / 2.0, 2.1, 30.0))
502:            except Exception:
503:                nu = 4.0
```
- **Why it matters** `4.0` sits *inside* the `[2.1, 30.0]` clip range, so it passes every downstream
  plausibility check with no marker distinguishing it from a fitted value. Contrast the GPD fit at
  `:326-339` in the same file, which correctly sets `model_fitted = False` and appends `"fit_failed"`.

### SVC-11 — `_l1_ttl` / `_L1_TTL_SECONDS` is dead code that misstates the live TTL
- **Class** maintainability · **Sev** nit · **Conf** confirmed · **Loc** `data_service.py:316-317`
- **Evidence** the adjacent comment asserts "L1 keeps a 5-min TTL" as fact, but the enforced value is
  `_l1_ttl_seconds(config)` reading persisted `cache_ttl_minutes` settings.

---

## CACHE INVENTORY (services layer) — the layer is in GOOD shape

Every cache has a TTL **enforced on the read path**, not only at write. Only the two cointegration
caches carry an explicit contract version — correct, since they are the only ones holding derived
analytics whose computation can change between deploys. `COINT_CONTRACT_VERSION` is present in both
key builders and `_cached_pair_satisfies_contract` (`:1720-1766`) now requires
`hedge_ratio_beta_std_error`, a recognised `stationarity_gate.verdict`, both leg verdicts from the
published vocabulary, and `observations > 2`.

| Cache | TTL on read? | Version token? | Contract covers fabricable fields? |
|---|---|---|---|
| `AnalyticsCache` (DB) | yes (`:291`) | caller-supplied | generic — caller's job |
| `_in_memory_df_cache` | yes (`:407`,`:627`) | yes (`generation`) | yes — also fences source/bounds/staleness |
| `_quote_memo` | yes (`:905`) | yes (`:900`,`:907`) | yes — also gates `_quote_sources` |
| `_IN_MEMORY_COINT_CACHE` | yes (`:1678`) | **yes** | yes |
| cointegration DB | via #1 | **yes** (`:886`) | yes |
| `_yf_fundamentals_cache` | yes (`:226`) | yes (generation) | payload is fundamentals, not derived |
| `ScreenerService._cache` | yes (`:215`) | no | cleared wholesale |
| `_exchange_rates` | yes (`:319-323`) | yes (`:191`,`:199`) | fallbacks deliberately never cached ✓ |

**The one forward-looking risk:** `AnalyticsCache` is generic and would re-serve a fabricated row
indefinitely if a *future* metric's writer omitted a contract check. The cointegration writer is the
only heavy user today and does supply one.