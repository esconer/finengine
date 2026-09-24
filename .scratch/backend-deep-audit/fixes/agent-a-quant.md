# Agent A — quant mathematics implementation report

**Scope:** implemented and verified A-01 through A-13 in the assigned quant services and backend tests. No API, schema, database, configuration, deployment, or Git-history files were edited. No network or real `backend/data/daisy.db` access was used.

## Status

All thirteen deterministic Agent-A evidence fixtures have retained before and after artifacts under:

`.scratch/backend-deep-audit/fixes/evidence/agent_a_*.{py,before.txt,after.txt}`

Every `agent_a_*.after.txt` check is `PASS`. The focused quant/service gate is green: **164 passed**. Ruff is clean for all changed source and test files.

## Evidence method

Each fixture imports the production seam, builds a deterministic synthetic input, computes an independent/reference result, and prints backend/reference values, absolute and relative differences, tolerances, and `PASS`/`FAIL`. The `.before.txt` files were captured before the production edits. The `.after.txt` files were regenerated after the final edits.

Representative commands:

```text
$env:PYTHONDONTWRITEBYTECODE='1'
uv run --project backend python .scratch/backend-deep-audit/fixes/evidence/agent_a_a01_garch_egarch.py
# repeat for agent_a_a02... through agent_a_a13...
```

The long-horizon memory fixture uses `numpy.broadcast_to` as a zero-copy test double; it never allocates the requested multi-gigabyte path matrix.

## Before → after evidence

| ID | Before symptom | After result |
|---|---|---|
| A-01 | GARCH h=5 VaR `-0.0492743493` vs arch return-space reference `-0.0220341981` (abs `0.0272401512`, rel `1.2363`, FAIL); EGARCH h=5 returned `None` although arch simulation was available. | GARCH and EGARCH h=1/5/21 match independent per-period `arch` variance-sum oracles within the documented fit/simulation tolerances; all horizon paths are finite. See `agent_a_a01_garch_egarch.after.txt`. |
| A-02 | Staggered-listing annual return `-0.1875726076` vs active reference `-0.2219336864`; volatility `0.1067931274` vs `0.1418719625`. | Both values match the active-mask/renormalized reference exactly; 239 active observations retained. See `agent_a_a02_active_returns.after.txt`. |
| A-03 | First `-10%` loss reported analytics and backtest drawdown `0`. | Both report `-0.10` using initial wealth `1.0`. See `agent_a_a03_drawdown_baseline.after.txt`. |
| A-04 | Boundary fit reported clipped `xi=-0.5` as the fit; reported constrained VaR/ES materially differed from the raw POT moments. | Raw fit `xi=-2.01301978`, constrained `xi=-0.5`, raw/constrained validity and reason fields are explicit; ordinary default outputs remain compatible. See `agent_a_a04_evt_raw_fit.after.txt`. |
| A-05 | MFI `0.5246785287` vs documented 0–100 reference `52.4678528716`; indicator cleaning could also drop an interior missing close and compress dates. | MFI `52.4678528716`; adapter scales the installed stockstats fraction by 100, and `_clean_dataframe` preserves the original missing-price time axis. See `agent_a_a05_mfi_scale.after.txt` and the A-13 evidence. |
| A-06 | Negative, NaN, and infinite costs were accepted; NaN risk-free input was accepted. | All invalid cases raise `ValueError` before optimizer/simulation work. See `agent_a_a06_backtest_cost_validation.after.txt`. |
| A-07 | Fixed weights were reused between boundaries; the second boundary had zero turnover despite different asset returns. | Self-financing drift gives second-boundary turnover `0.0073` in the deterministic fixture; total turnover `0.31`; costs occur only at scheduled boundaries. See `agent_a_a07_backtest_drift.after.txt`. |
| A-08 | 40-year request estimated `249,984,000` live path elements from 4,960 paths, exceeding the 50,000,000 aggregate budget. | Bounded 99-path chunks and checkpoint retention estimate `4,989,600` live elements; no large test allocation. See `agent_a_a08_mc_memory.after.txt`. |
| A-09 | Cache-key fixture received `TypeError` because lookback was not part of the key contract; same pair/date/threshold could share coverage; a late pair result could repopulate a purged memo. | Memory and durable keys differ for lookback 60 vs 2,520 and explicit coverage fingerprints, and a captured cache generation drops late writes after a purge. See `agent_a_a09_coint_cache_identity.after.txt` and the A-09 regression. |
| A-10 | Historical request for end `2020-02-01` fetched through `2026-09-24`. | Fetch call is exactly `('^NSEI', '2020-01-01', '2020-02-01')`. See `agent_a_a10_benchmark_anchor.after.txt`. |
| A-11 | A `0.95` request was returned under four `*_99` fields. | Neutral `evt_pot_var/es` and `historical_var/es` fields are returned; `*_99` compatibility aliases exist only for the actual default `0.99` contract. See `agent_a_a11_tail_field_names.after.txt`. |
| A-12 | One return `[0.05]` reported EWMA volatility `0.7937253933` (`abs(return)*annualization`). | One observation returns explicit `0.0`; empty input still raises. See `agent_a_a12_ewma_one_observation.after.txt`. |
| A-13 | HHI/N_eff/single-holding/inverse-vol/geometric-monthly guard values were independently checked; a zero-variance leg could contaminate sizing and a short model history could fabricate a fallback. | Active HHI/N_eff and geometric checks pass; raw low-vol inverse-vol sizing has no 5% floor, excluded zero-variance legs cannot poison the covariance, and insufficient model history returns an explicit error. See `agent_a_a13_quant_invariants.after.txt`. |

## Implemented fixes and exact current locations

### A-01 — AnalyticsEngine GARCH/EGARCH horizon semantics

- `backend/app/services/analytics_engine.py:1115-1121` normalizes the `arch` per-period variance path; the simulation ensemble is averaged before the time axis is retained.
- `backend/app/services/analytics_engine.py:1146-1162` sums per-period variances and converts the cumulative path once to return-space VaR/CVaR; the public annualized volatility and raw fields remain available.
- `backend/app/services/analytics_engine.py:1164-1227` uses analytic GARCH and analytic EGARCH h=1; `backend/app/services/analytics_engine.py:1229-1301` uses seeded installed-arch simulation for EGARCH h>1.
- The evidence script independently fits the same installed `arch` model and checks h=1/5/21; EGARCH simulation tolerances are widened only for fit/seed variation, while availability/finiteness is checked separately.

### A-02 — Active return construction

- `backend/app/services/analytics_engine.py:57-100` removes price backfill/zero-fill from portfolio metrics and exposes active observation counts.
- `backend/app/services/analytics_engine.py:884-915` implements the service-owned aggregation contract: finite positive weights only, per-date active mask, renormalization over available positive weights, and dropping dates with no active exposure.
- `backend/app/services/analytics_engine.py:524-545` and `:606-616` preserve missing observations in stress/volatility-sizing preprocessing rather than manufacturing zero returns.
- `backend/app/services/analytics_engine.py:771-777` applies the same no-fill contract to risk scoring; the factor leg now receives the actual portfolio weights at `:804-806`.
- Position-level history at `backend/app/services/analytics_engine.py:1000-1006` retains the original index while calculating returns, so an interior gap is not silently bridged.
- `backend/app/services/tail_risk_service.py:461-481` applies the same active positive-weight renormalization to its full-suite portfolio leg instead of `fillna(0.0)` aggregation.

### A-03 — Initial wealth drawdown baseline

- `backend/app/services/analytics_engine.py:977-1000` prepends wealth `1.0` before the running maximum/drawdown calculation.
- `backend/app/services/backtest_service.py:171-183` prepends initial wealth for both strategy and benchmark drawdown paths; `:204-205` computes MDD from the baseline-aware arrays.

### A-04 — EVT raw/constrained disclosure

- `backend/app/services/tail_risk_service.py:25-235` now retains the raw GPD fit and applies stability constraints only to a separately named constrained estimate.
- The result includes `gpd_shape_xi_raw`, `gpd_shape_xi_constrained`, raw/constrained scale fields, `gpd_shape_constrained`, `constraint_applied`, `metrics_constrained`, `metrics_valid`, `raw_fit_valid`, `constrained_metrics_valid`, and `constraint_reason`.
- `gpd_shape_xi` is the raw fit (rounded for the legacy field); the clipped value is never presented as the raw fit. Unconstrained raw VaR/ES moments are also exposed. Default 99% aliases remain for compatibility; insufficient exceedances still report historical-only values and `model_fitted=False`.

### A-05 — MFI scale

- `backend/app/services/indicators_service.py:117-146` converts the installed stockstats MFI fraction at the adapter boundary to the documented 0–100 scale, leaving the public `>80/<20` description truthful.

### A-06 — Backtest input validation

- `backend/app/services/backtest_service.py:33-42` converts and validates `transaction_cost_bps` and `risk_free_rate` before strategy, data, or optimizer work. Negative/non-finite costs and non-finite risk-free values raise `ValueError`.
- `:55-63` also rejects empty/non-finite return frames before simulation.

### A-07 — Self-financing drift and explicit benchmark

- `backend/app/services/backtest_service.py:83-90` documents and initializes separate strategy and benchmark holdings.
- `:115-162` computes turnover from drifted pre-boundary weights, applies the multiplicative cost only at each scheduled boundary, and updates weights with `w[t+1] = w[t] * (1+r[t]) / (1 + w[t]ᵀr[t])`.
- `:228-229` makes the accounting contract explicit: `benchmark_method="equal_weight_buy_and_hold"` and `strategy_accounting="self_financing_weight_drift"`. Existing metric keys remain present.

### A-08 — Monte Carlo aggregate budget/chunking

- `backend/app/services/monte_carlo_service.py:35-47` separates retained workload, aggregate live-element, and per-chunk budgets.
- `:57-65` prevents direct low-level helpers from allocating an unbounded matrix.
- `:172-260` creates half-year checkpoints, chooses a chunk bounded by both budgets, simulates/discards each chunk, and retains only terminal/checkpoint columns.
- `:300-381` keeps deterministic seeded behavior and reports `memory_budget_elements`, `chunk_size_paths`, and `checkpoint_count`.

### A-09 — Cointegration cache identity

- `backend/app/services/cointegration_service.py:44-83` includes requested lookback and effective coverage in both memory and durable key inputs.
- `:86-99` derives a deterministic overlap length/start/end fingerprint.
- `:307-410` threads the identity through L1 and durable cache reads/writes.
- `:419-505` accepts optional `lookback_days` and fingerprints each actual pair history. Existing callers remain compatible; actual coverage protects the current API even before its explicit argument is threaded.

### A-10 — Historical benchmark anchor

- `backend/app/services/benchmark_service.py:52-75` adds explicit `start`/`end` support to `ensure_history`.
- `:89-144` derives the default start from the requested end and fetches the exact requested window. A compatibility path still supports older `ensure_history(days=...)` test doubles.

### A-11 — Honest configurable tail names

- `backend/app/services/tail_risk_service.py:183-235` always emits neutral confidence-independent field names. Legacy `*_99` fields are emitted only when `confidence_level` is actually 0.99, preserving existing default consumers without mislabeling 0.95/0.999 results.

### A-12 — EWMA one-observation contract

- `backend/app/services/volatility_service.py:89-115` filters non-finite inputs and retains its scalar-helper `0.0` compatibility result for one observation; portfolio `AnalyticsEngine.volatility_sizing` now rejects a one-return EWMA request with an explicit insufficient-data result. Empty input retains the existing `ValueError` contract.

### A-13 — Existing quantitative invariants

- `backend/app/services/analytics_engine.py:241-309` retains HHI=`sum(w²)`, N_eff=`1/HHI`, and exact single-holding diversification `0%`; zero/non-positive rows are excluded from the active holding set.
- `backend/app/services/analytics_engine.py:623-828` uses raw model volatility for inverse-volatility sizing, discloses sample fallbacks, excludes zero-variance legs from the recommendation covariance, and returns an explicit insufficient-data result when no finite model estimate exists.
- The existing API monthly formula remains unchanged at `backend/app/api/analytics.py:1877`; the Agent-A fixture independently confirms geometric compounding. The coordinator's shared helper and API masks are covered by the A/B/C integration gate.

## Tests and commands

### Changed/added tests

- Added `backend/tests/test_agent_a_quant_fixes.py` with deterministic regressions for A-01..A-13 plus the inverse-volatility zero-variance/short-history edges, indicator gap preservation, rolling-gap axis, and late cointegration cache-write fencing.
- Updated `backend/tests/test_bugfix_quant_services.py` MC test to assert bounded chunks/checkpoints without a large allocation.
- Updated `backend/tests/test_quant_math_p1_batch.py` backtest oracle to self-financing drift and boundary-only costs.
- Updated `backend/tests/test_coverage_quant_services.py` one-observation EWMA assertion to the explicit zero contract.
- Updated `backend/tests/test_bug_sweep_2026_09.py` comment to describe active-mask behavior rather than the historical fill.

### Passing focused gate

Command (run from `backend/`, with bytecode disabled and no cache/coverage):

```text
$env:PYTHONDONTWRITEBYTECODE='1'
uv run pytest -p no:cacheprovider --no-cov tests/test_agent_a_quant_fixes.py tests/test_analytics_engine.py tests/test_bugfix_core_services.py tests/test_bugfix_quant_services.py tests/test_quant_math_p1_batch.py tests/test_quantitative_invariants.py tests/test_monte_carlo_service.py tests/test_coverage_quant_services.py tests/test_coverage_engines.py tests/test_data_services.py::TestIndicatorsPure tests/test_data_services.py::TestIndicatorsServiceWindow tests/test_p06_evt.py tests/test_p03_coint.py
```

Result: **164 passed, 12 warnings** (the warnings are existing statsmodels complex-casting warnings in Johansen coverage tests).

Ruff:

```text
uv run ruff check --no-cache app/services/analytics_engine.py app/services/volatility_service.py app/services/tail_risk_service.py app/services/indicators_service.py app/services/backtest_service.py app/services/monte_carlo_service.py app/services/cointegration_service.py app/services/benchmark_service.py tests/test_agent_a_quant_fixes.py tests/test_bugfix_quant_services.py tests/test_quant_math_p1_batch.py tests/test_coverage_quant_services.py
```

Result: **All checks passed**. `git diff --check` also produced no whitespace errors (only the repository's existing LF/CRLF warnings).

## Unresolved / coordinator handoff

1. `CONTEXT.md:267` still contains the pre-remediation `.ffill().bfill().fillna(0.0)` prescription. It is outside the allowed backend/deployment/test/fix-artifact write scope; the executable source and regression contracts use the active-mask rule instead.
2. Scalar EWMA/GARCH helpers in `volatility_service.py` still omit missing observations when fitting a model. The portfolio active-return, rolling-volatility, and indicator paths preserve the time axis; a future model-specific gap policy should be decided before changing those historical estimator conventions.
3. Cointegration cache identity includes requested lookback and effective coverage, while a provider revision with the same range/count is not value-hashed. This is a deliberate follow-up, not a demonstrated regression in the selected matrix.
4. Docker image/runtime proof and live-provider verification remain unavailable; see `00-FIX-INDEX.md`.

The previously open A-02 API seam, explicit coint lookback threading, EVT neutral schema, and late coint cache-write fence are closed in the current coordinator tree.

## Safety / Git

No commit, reset, checkout, clean, stash, or history rewrite was performed. Preexisting working-tree changes were left untouched.

## Coordinator integration addendum

The coordinator closed the A-02 API seam, the A-09 request identity and late-write fence, and the related source/tail invalidation seams:

- `backend/app/services/analytics_engine.py:29-60` exposes
  `aggregate_active_returns`, the same positive-weight active mask used by the
  engine method.
- `backend/app/api/analytics.py:739-847, 1665-1701, 2023-2070` preserves active
  masks in forecast, wide-return, and single-holding optimization paths.
- `backend/app/api/analytics.py:2385-2392` threads `lookback_days` into
  `CointegrationService.scan_pairs`; `backend/app/services/cointegration_service.py:368-428,475-529`
  fences late pair-cache writes with the purge generation.
- `backend/app/api/websocket.py:271-407` uses converted base-currency values,
  explicit native/value currencies, active weights, and null unavailable metrics.
- `backend/app/services/indicators_service.py:84-95, 184-210` preserves missing
  price rows and emits a null close rather than filling or dropping the date.
- `backend/app/services/volatility_service.py:51-63,236-249` keeps rolling
  volatility windows on the original return index; scalar EWMA/GARCH fitting
  remains a separately disclosed convention.

The current A-owned regression file has **21 passing tests**; the combined
A/B/C/D regression gate reports **103 passed** after the residual additions, the
coordinator integrated gate reports **224 passed**, and the cross-seam evidence
oracle reports **10 passed / 0 failed**. The A-owned service implementation and
its **166-test** focused gate remain green.

## Residual reviewer closure (2026-09-24)

The final residual review added two quantitative/data edges to the original A
slice. `AnalyticsEngine.volatility_sizing` now treats a positive-weight EWMA
leg with fewer than two valid returns as insufficient data rather than creating
an allocation. The indicator adapter masks MFI rows with missing, non-finite, or
non-positive required OHLC values. The focused A/B gate is **45 passed**, the
A broad gate is **166 passed**, and the coordinator oracle remains green. These
changes do not alter the separately documented scalar `VolatilityService`
one-observation zero-variance compatibility contract. The final independent
residual verifier marked these A/B quantitative edges **PASS**.

