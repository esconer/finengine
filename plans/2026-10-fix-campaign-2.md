# Fix campaign 2 — 2026-10-03

Continues `plans/2026-10-fix-campaign.md`. Campaign 1 closed every wrong-number row
(`SVC-1..11`, `QM-1..6/15/24/26`) and committed. This campaign works what is left.

## Ground truth

- Campaign 1: 12 commits. Backend `2536 passed / 0 failed / 87.78%`.
  Frontend `571 passed`, 2 flaky timeouts that pass in isolation.
- Recon (3 agents, ~94 ledger rows): **31 FIXED · 6 PARTIAL · ~53 OPEN**.
- **Every wrong-number row is closed.** What remains is naming, declaration, gating,
  and two statistical-design decisions.

## Non-negotiable rule for every task

**Never fabricate.** A refusal is a valid answer; a substituted number is the defect.
Where a fix needs a threshold, tolerance or boundary, do **not** invent one — prefer a
*structural* test (e.g. `nunique() < 2` means no variation exists, so any positive
`.std()` is round-off, not measurement).

## Ordering

`WM-4` and `WM-5` (below) are **one shared predicate** and must land together.
`B2`+`B3` must land together — nulling CAGR nulls Calmar at `backtest_service.py:207`.

---

## Wave 1 — backend (disjoint files, parallel)

### T1 · `backend/app/services/analytics_engine.py`
Highest concentration of live wrong numbers. All share one file; one owner.

| id | defect | site |
|---|---|---|
| WM-1 | NaN volume → `min(5.9, nan)` → `5.9` → band "Low" → **risk "High"** | `:3945-3977`, `:3995`, `:4000` |
| WM-2 | `sharpe=9.0e16` + CI; guard catches only *exact* zero | `:5496`, `:5511`, `_zero_dispersion_reason` |
| WM-3 | constant window publishes `volatility_forecast: 0.05` (**clip floor**) beside `var_forecast: -8.2e-19` | `:6717`, `:6738` |
| WM-4/5 | `min(30, hhi*100)` → `min(30, 0.0)` = **best possible** score, keeps 0.20 weight | `:5027-5031` |
| OE-03 | turnover is `mean(vol)×last_close`, not `mean(vol×close)` | `:3947` |
| QM-20 | empty-book refusal publishes `herfindahl_index: 0.0` | `:6469-6488` |
| QM-25 | ±20% winsorisation undisclosed (sibling declares it at `:4424`) | `:6680-6681` |
| QM-28 | failure block publishes `data_points: 0` — two false statements | `:6308-6313` |
| QM-11/12/13 | units keys: `kurtosis`, `var_95`, `var_forecast` | `:5579`, `:5534`, `:5986` |
| FE-side | `stress_test` consumes un-normalised weights | `:4285` |

**WM-1 coupling**: publishing `score: None` breaks `_liquidity_band`, `:3995`
`volume_stats`, `:4000` `overall_score` (mean over list), and four
`analytics.py:7566-7600` disclosure helpers.
**Verify**: `uv run --extra dev pytest tests/test_liquidity*.py tests/test_zero_dispersion_ratio_refusal.py tests/test_quantitative_invariants.py tests/test_risk_scoring*.py -q --no-cov`

### T2 · `backend/app/api/analytics.py`
- QM-18: two `risk_free_rate = 0.02` literals (`:555` + `config.py:53`) → read settings.
- Optimisation: `get_forecast_risk` (`:6596`) is the **last heavy quant route not behind
  `_run_cpu`**; `:5518` re-fits GARCH on every one of 1000 draws (~18 s, per the repo's
  own note at `analytics_engine.py:6904`).
- OE-10: `/screens/custom` uses the module-global screener singleton (`:210`, `:252`).
**Verify**: `bun`-free; `uv run --extra dev pytest tests/test_coverage_analytics_all_routes.py tests/test_tear_sheet_cpu_offload.py tests/test_analytics_fabricated_fields.py -q --no-cov`

### T3 · `equity_research_service.py` + `screener_service.py`
- SVC-9: `current_price: 0.0` (`:57`, `:231`). **Four declarations must change together or it
  500s**: `schemas.py:816`, `schemas.py:865`, `types/index.ts:980`, `types/index.ts:1061`.
- SVC-4: screener `None → 0.0` on ROCE/ROE/mcap while `pe = 999.0` is excluded.
  **Decision:** `bfinance`'s `filter_fn` is boolean-only — no "unscored" channel. Default to
  **exclude on absence** (matches the `pe` precedent and the repo-wide convention), and record
  the skip. `_filter` runs on a worker thread (`_to_thread`, `:364`), so the side channel must
  be thread-safe.
**Verify**: `uv run --extra dev pytest tests/test_equity_research*.py tests/test_screener*.py -q --no-cov`

### T4 · `backtest_service.py`
- SVC-6 + SVC-7 **together**: `lookback_days` silently shortened (`:65-67`), and CAGR
  annualises without `MIN_ANNUALIZE_DAYS` (`:185-189`).
- **Cascade:** `:207 strat_calmar = strat_cagr / abs(strat_mdd)` — nulling CAGR nulls Calmar.
**Verify**: `uv run --extra dev pytest tests/test_backtest*.py -q --no-cov`

### T5 · `tail_risk_service.py` + `optimization_service.py`
- QM-22 residue: `np.ptp` added but no `np.isfinite(rho)` guard → ±inf leg gives
  `rho=nan` → category `"LOW"`, bypassing `unmeasurable_pairs`.
- QM-21: no cvxpy solve checks `Problem.status`; `optimal_inaccurate` publishes as `optimal`.
  Publish `problem_status`; **refuse** non-optimal.
**Verify**: `uv run --extra dev pytest tests/test_tail_dependence_unmeasurable.py tests/test_wave7_fat_tail_verdict.py tests/test_bl_prior_and_clip_disclosure.py -q --no-cov`

### T6 · `cointegration_service.py` + `benchmark_service.py`
- QM-8: `k_ar_diff=1` hardcoded (`:1095`) yet gates a trade directive. Publish the resolved
  value + `k_ar_diff_basis`.
- QM-9: stationarity gate on **log** prices (`:1240`), decision test on **levels** (`:1435`).
  Minimum honest fix: publish `"eg_transform": "level_prices"`. Do **not** move the decision
  transform — the spread convention at `:1426` is verified correct and depends on it.
- QM-10: publish `benchmark.return_basis: "price_index"`.
**Verify**: `uv run --extra dev pytest tests/test_p03_coint*.py tests/test_cointegration*.py -q --no-cov`

### T7 · `regime_service.py`
- `cum_prod == 0` arm (`:358-371`) routes to an arithmetic mean that **can come out
  POSITIVE** for a state that lost everything. Correct form is `cum_prod ** (252/n) - 1`
  ≡ `-1.0` — one token, no threshold, decidable from arithmetic alone.
  Leave the `cum_prod < 0` arm alone: its fallback is a disclosed definition switch.
**Verify**: `uv run --extra dev pytest tests/test_regime*.py -q --no-cov`

### T8 · `websocket.py` + `tests/conftest.py`
- OE-11: `break` sits **inside** the `try`, so a failing send starves the liveness exit.
- Optimisation: `:413` runs `calculate_portfolio_metrics` **inline on the event loop**;
  `Select-String` for `to_thread|_run_cpu|run_in_executor` in that file returns **nothing**,
  and `Dockerfile:54` has no `--workers`.
- **INF-12: the cheapest determinism win in the repo** — `conftest.py:560`
  `np.random.seed(hash(ticker) % 2**32)`; `str.__hash__` is salted by `PYTHONHASHSEED`, so every
  run produces a different series and the comment claims the opposite.
- INF-11: delete `cleanup_test_data` (a no-op reading as a guarantee) and the conftest-level
  `pytestmark` (inert — pytest never collects it from a plugin).
**Verify**: `uv run --extra dev pytest tests/test_test_isolation_invariants.py tests/test_client_db_isolation_invariants.py -q --no-cov`

---

## Wave 2 — frontend (disjoint files, parallel)

### T9 · `manage/page.tsx` + `pairs/page.tsx`
- **OE-02 [BLOCKER]**: `getRiskLevel` tests `volatility < 20` on a **fraction**, so every row
  badges green "Low". Correct sibling: `dashboard/forecast-risk/page.tsx:465` (`0.20`/`0.40`).
- `pairs/page.tsx:150` calls `.toFixed()` on `Optional[float] = None` → **throws, blanks the
  route**. `:39` is `useState<any[]>`, so `tsc` cannot see it. Replace with a real interface.
- `manage/page.tsx:583-595` `totalGainLossPct` fallback → `0 >= 0` → green `+0.00%`.
**Verify**: `bun x tsc --noEmit && bun x vitest run src/test/pages/AbsentValueRendering.test.tsx src/test/pages/FabricatedScaleAndZero.test.tsx`

### T10 · frontend remainder
- FE-4: gate `:419` button on absent price; `:281` renders `₹undefined` → `—`.
- FE-6: `RealtimeStatus` has two states, so it asserts "connecting" forever after Live is off.
- FE-11: wrap `volatility-sizing:895` column model in `useMemo`. **React Compiler is off**
  (`next.config.ts:5`) — do not enable it.
- FE-10: three `(state) => state` selectors.
- FE-9: ~500 lines unreachable, including the app's only HTTP interval.
**Verify**: `bun x tsc --noEmit && bun x vitest run src/test/pages src/test/unit`

### T11 · `types/index.ts` + Recharts dead import
- `CorrelationStabilityResponse` declares `rolling_60d_avg_corr`, `p90_historical_corr`,
  `regime_alert`, `history` — **none exist on the backend model** — and lacks `as_of_semantics`.
- Recharts is in `package.json` but **imported nowhere**; `dynamic` in `next.config.mts:1`.
**Verify**: `bun x tsc --noEmit && bun x vitest run`

---

## Wave 3 — infra

### T12 · CI + config + harness
- INF-16 `--frozen` → `--locked` in CI (keep `--frozen` in the Dockerfile).
- INF-15: 8 `uses:` still on floating tags; pin `bun-version: latest`.
- INF-21: add a `concurrency:` block.
- INF-18: `.ruff_cache/`, bare `*.db` in the **root** `.gitignore`.
- INF-22: `allowed_hosts` duplicated in `main.py:107` vs `settings.allowed_origins` at `:113`.
- INF-20: `filterwarnings` has no `error::` entry, so `ComplexWarning`/`SAWarning` pass
  unelevated and a NaN can ship under a green suite.
- INF-10: `test_env_vars` mutates the environment *after* `from main import app` read it.
- INF-7: `vitest.config.mts` has no `restoreMocks`/`unstubGlobals` while `setup.ts` stubs
  globals at module scope.
**Verify**: `uv run --extra dev ruff check && bun x tsc --noEmit` + workflow YAML parses

---

## Deferred with reasons

- **INF-9** (333 `assert x is not None` across 87 files) — needs a test-design policy on what a
  handler under test must publish when its engine is mocked. Not mechanical.
- **OE-15 / INF-19** — ticket bookkeeping and deleting an unexercised deploy path; human calls.
- **QM-10's TRI half** — data procurement; the `return_basis` declaration ships in T6.
- **Frontend bundle rows** — the repo has **no measured perf data**; a build is required.
- **Per-leg GARCH refit** — already refused by design at `analytics_engine.py:6891`. Optimising
  it would overturn a documented decision.
- **`correlation_service` rolling correlations** — 19,900 on a 200-name book is the right shape
  for a hot spot, but there is **no timing anywhere in the repo**. Measure before spending a day.