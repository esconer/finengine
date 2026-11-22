# Verified backlog fixes — 2026-10-06 (rev 2, post-momus)

Source: 141 open tickets in `.scratch/**/issues/*.md` + ~248 un-ticketed rows in
`.scratch/backend-audit/verified-0*.md`, re-verified 2026-10-06. Six verification
passes, then adversarial review by momus. Rev 2 incorporates all 12 blocking findings.

**`status:` line is the tracker. Update as tasks land.**

## Rev-2 changes (from momus's blocking findings)

1. **Every scoped pytest now carries `--no-cov`.** `addopts` puts
   `--cov-fail-under=80` in global config, so a subset run measures `app` at ~15-17%
   and exits 1 even with 100% tests passing. `--no-cov` removes that from every
   worker's gate. This also removes T1's ordering dependency entirely.
2. **`uv run ruff`** everywhere — bare `ruff` is not on PATH, only in the venv.
3. **T1 must also run `uv lock`.** `ci-cd.yml:81` runs `uv sync --locked`; editing
   `pyproject.toml` without re-locking fails CI. `backend/uv.lock` added to ownership.
4. **T13 must also run `bun install`.** `ci-cd.yml:150` and `frontend/Dockerfile:15`
   both use `--frozen-lockfile`; adding a devDependency without regenerating the lock
   breaks CI *and* the production image. `frontend/bun.lock` added to ownership.
5. **T13's React Compiler is only observable via `bun run build`** — `tsc --noEmit`
   reads tsconfig, vitest reads `vite.config`, neither consults `next.config.ts`.
   `bun run build` is what produces the Docker image.
6. **T12's "coupling" was phantom.** `test_agent_d_deployment_contract.py:215`
   asserts the integration-file target path, **not** the pytest command. No test in
   the repo pins the pytest command. Coupling paragraph deleted.
7. **T9 has eight fabricated defaults, not five** — `:7480 top_3` and `:7481 top_5`
   were omitted. And the empty-portfolio branch at `:7413` is separate committed code
   that T9 must not touch; T9 owns only the measured path `:7479-7509`.
8. **T9's grep bullet was vacuous** — `'\.get\('` with `-SimpleMatch` matches nothing.
9. **T10 named a test file that does not exist** — `tests/test_backtest_service.py`.
   Correct file is `tests/test_backtest_window_and_annualize_gate.py`.
10. **`621/621` removed from all frontend gates** — T6 adds a test, so the total
    moves. Root agent records the baseline in Phase 5.

## Constraints binding every worker

- **No commits.** Leave changes in the working tree.
- **Never** `git stash` / `checkout` / `restore`. Read-only git only.
- **Never** set `OPENBLAS_NUM_THREADS` — it flips BLAS reduction order and six
  bit-pinned tests fail at `1`.
- `C:\es\coding\bfinance` is **OFF LIMITS**.
- **Scoped pytest only** (`--no-cov`, named test files). Never the full suite — the
  root agent runs it once, alone, at the end.
- Do not touch the ~24 sanitisation files, the network-mocking files
  (`test_coverage_*`, `test_api_endpoints.py`, `test_wave2_transition.py`), or
  `frontend/vitest.config.mts` unless the task names it.
- **Before editing any already-dirty file, run
  `git diff -- <file> > C:\Users\Sayanti\AppData\Local\Temp\opencode\before-<task>.patch`.**
  Dirty files: `backend/app/api/analytics.py` (uncommitted work occupies lines
  7483-7501 — **`:7501` only**, not `:7413`, is the pre-existing change),
  `.github/workflows/ci-cd.yml` (uncommitted block is `@@ -95,6 +95,28 @@`),
  `backend/tests/test_stress_bucket_and_score_floor.py`,
  `frontend/src/test/pages/HoldingProvenanceDisclosure.test.tsx`.
- PowerShell 5.1: `||` is not a separator; `@{u}` parses as a hash literal; in `-like`,
  `?` is a wildcard; `rg` with a quoted `"` silently matches nothing.
  `Select-String -SimpleMatch` takes the pattern **literally** — never escape it.
- BOM files: read with
  `[System.IO.File]::ReadAllLines($p, [System.Text.Encoding]::UTF8)`.
- **The frontend suite is mildly flaky under load** — a 5s timeout in
  `PageControlAccessibleNames.test.tsx:211` fired once under concurrent load and
  passed on re-run. **Re-run once before reporting it as a regression.**

## File ownership (no two tasks in a wave share a file)

| file | task | wave |
|---|---|---|
| `backend/pyproject.toml`, `backend/uv.lock` | T1 | 0 |
| `backend/tests/conftest.py` | T5 | 0 |
| `frontend/package.json`, `frontend/bun.lock`, `frontend/next.config.ts` | T13 | 0 |
| `backend/app/services/data_service.py` | T2 | 1 |
| `backend/app/services/cointegration_service.py` | T3 | 1 |
| `backend/app/services/regime_service.py` | T4 | 1 |
| `backend/app/services/optimization_service.py` | T8 | 1 |
| frontend `tear-sheet`,`risk-studio`,`risk-contribution`,`regime`,`liquidity` | T6 | 1 |
| frontend `stress-testing` | T7 | 1 |
| `backend/app/api/analytics.py`, `backend/app/services/backtest_service.py` | T9+T10 | 2 |
| `backend/app/services/analytics_engine.py` | T11 | 2 |
| `.github/workflows/ci-cd.yml` | T12 | 2 |

T5 is wave 0 because every other worker's pytest imports `conftest.py` at collection.

---

# Wave 0

### T1 — bound bfinance; stop paying coverage by default
**status: SOLVE**

Two changes, one file each — `pyproject.toml` and `uv.lock`.

1. **`pyproject.toml:40`** `"bfinance>=0.1.0"` is fail-open, no upper bound.
   `uv.lock` resolves `0.1.3` from PyPI; 100% of the test suite mocks bfinance, so a
   breaking change would not fail any test. Screener, Equity Research and AI Dossier
   route through it with no fallback (`data-source-preference/spec.md:40`, rule D4).
   When 0.2.0 publishes, a routine `uv lock --upgrade-package bfinance` pulls it in
   silently. **Add an upper bound that admits the currently-resolved version.**
2. **`pyproject.toml:84`** `addopts` carries `--cov=app --cov-report=html
   --cov-report=term-missing --cov-fail-under=80`, but `ci-cd.yml:96` already passes
   `--cov=app --cov-fail-under=80` explicitly. Remove all four coverage flags from
   `addopts`. Consequences of the duplicate: coverage tracing multiplies runtime
   **1.55-8.2x** (`test_audit_rule_coverage.py` 399.6s traced vs 48.8s bare), and every
   subset run exits 1 against a floor of 80 it cannot reach. CI is unaffected.

**Then run `uv lock`** so `uv.lock`'s `requires-dist` matches the new specifier.
`ci-cd.yml:81` runs `uv sync --locked` and fails otherwise.

Do NOT touch `filterwarnings` (`:95-113` records five tests that legitimately assert
a refusal), `[tool.coverage.run]`/`[tool.coverage.report]`, or `pytest-xdist`.

`Verify:`
```
Select-String -Path backend/pyproject.toml -Pattern 'addopts'   # no --cov
Select-String -Path backend/pyproject.toml -Pattern 'bfinance'  # shows upper bound
git diff -- backend/pyproject.toml                              # <= 6 changed lines
git diff --stat -- backend/uv.lock                               # bfinance specifier line only
uv lock --check                                                 # exit 0, in sync
uv run pytest -q --no-cov --no-header -p no:cacheprovider tests/test_vol_cone_forecast_disclosure.py
   -> 27 passed, exit 0   (pre-T1 this exits 1 with "FAIL Required test coverage of 80%")
Select-String -Path backend/pyproject.toml -Pattern 'filterwarnings'   # byte-identical
```

---

### T5 — `conftest.py`: `dependency_overrides` must not leak on an exception
**status: SOLVE**

`backend/tests/conftest.py:310-312`:
```
async with AsyncClient(transport=transport, base_url="http://test") as client:
    yield client
app.dependency_overrides.pop(get_db_session, None)
```
**No `try/finally`**, so `:312` is unreachable when a test body raises. Currently
harmless only because `:308` unconditionally reassigns
`app.dependency_overrides[get_db_session]` on every setup rather than relying on the
pop. That is luck.

Wrap the yield in `try/finally`. Do not change the override's value, the transport,
the base URL, or the fixture's scope.

`Verify:`
```
# add a test that makes a client request then raises, and proves no override survives
# teardown. It MUST fail against the pre-change code — prove that.
uv run ruff check --select E9,F tests/conftest.py
uv run pytest -q --no-cov --no-header -p no:cacheprovider \
  tests/test_websocket.py tests/test_test_isolation_invariants.py \
  tests/test_client_db_isolation_invariants.py tests/test_session_db_gate_scope.py
   -> all pass
```

---

### T13 — frontend config: make the coverage gate real; enable the React Compiler
**status: SOLVE (with an open finding — see below)**

**1. `@vitest/coverage-v8` is missing.** `vitest.config.mts:13-32` declares
`coverage.provider: 'v8'` and `thresholds.global` branches/functions/lines/statements
all 80. `package.json:13` has `"test:coverage": "vitest run --coverage"` but
devDependencies has `@vitest/ui` and **no coverage provider**. CI runs
`bun run test:run` with no `--coverage`. **Four of four thresholds are decoration.**

Add the provider, then run `bun run coverage` and **report the real four numbers.**
If red, that is a finding to report — **do not lower the 80 thresholds.**

**Then run `bun install`** so `frontend/bun.lock` is regenerated.
`ci-cd.yml:150` and `frontend/Dockerfile:15` both use `--frozen-lockfile` and fail
on a stale lock. The lockfile is git-tracked.

**2. `next.config.ts:5`** `reactCompiler: false, // Disabled for stability`.
`babel-plugin-react-compiler` 1.0.0 is already installed (`package.json:52`).
This is the one lever that would cover every missing memo in the tree.

**Only `bun run build` exercises `reactCompiler`** — `tsc --noEmit` reads
`tsconfig.json`, and vitest reads `vite.config` via `@vitejs/plugin-react`, neither of
which consults `next.config.ts`. `bun run build` is also what the Dockerfile runs.
**If `bun run build` fails, revert the toggle and report the failure. Do not adjust
tests to force a risky build-time compiler through.**

`Verify:`
```
cd frontend
bun install                     # regenerates bun.lock; commit-ready
bun run coverage                # quote all four numbers verbatim
bun x tsc --noEmit              # 0 errors
bun run test:run                # all pass
bun x eslint src/               # 0 errors
bun run build                   # exit 0 -- the ONLY command that sees reactCompiler
git diff --stat -- frontend/bun.lock frontend/package.json frontend/next.config.ts
```
Report plainly: did coverage meet 80? Did the compiler stay on or did you revert it?

---

# Wave 1

### T2 — bound `_in_memory_df_cache`
**status: SOLVE (verified: 900 keys -> 256 plateau, 30.59->8.74 MiB heap; 3-file gate green)**

`backend/app/services/data_service.py:371` `_in_memory_df_cache: Dict[str, Any] = {}`.
Writes at `:628` and `:724`. The TTL check at `:699-700` gates **reads** only, so a
ticker written once and never read again is never reclaimed — RSS grows linearly with
distinct tickers screened since boot.
`.scratch/caching-architecture-sqlite-wal-optimization.md` Phase 2 specifies the fix;
its acceptance criterion is "RSS bounded under 250MB".

Mirror the bounded pattern already in this repo: `analytics.py:12677`
`_TAILS_CACHE_MAX_ENTRIES = 32` with `:12879`
`while len(_TAILS_RESPONSE_CACHE) > _TAILS_CACHE_MAX_ENTRIES:`.
(**Read-only reference** — `analytics.py` is dirty and owned by T9+T10 in wave 2.)

Do not change the cache's key, TTL, or semantics. Pick a cap and say why in a comment.

`Verify:`
```
# a script importing 1,000 distinct tickers through DataService shows len() plateauing
# at the cap and sampled process RSS plateauing rather than growing. Paste both curves.
uv run ruff check --select E9,F app/services/data_service.py
uv run pytest -q --no-cov --no-header -p no:cacheprovider \
  tests/test_source_preference_and_cache.py tests/test_bugfix_cache_index_selfheal.py \
  tests/test_bugfix_foundation.py
   -> all pass
```

---

### T3 — bound `_IN_MEMORY_COINT_CACHE`; stop the dispersionless z-score publishing `0.0`
**status: SOLVE (verified: LRU cap 256; na_position correct; 11+129 tests green)**

1. **`:31`** `_IN_MEMORY_COINT_CACHE: Dict[str, Tuple[datetime, Dict[str, Any]]] = {}`
   has a TTL sweep at `:1941-1944` and **no size bound**. `_mem_cache_key` at
   `:924-938` folds in `p_value_threshold` and `lookback_days` — **both
   caller-controlled query parameters** — so a correct fix for a different bug
   multiplied the reachable key space of an unbounded cache. Bound it as in T2.
2. **`:1658`** `z_val = round(float((s_val - spread_mean) / spread_std), 4) if
   spread_std > 1e-8 else 0.0` — a dispersionless spread publishes `zscore: 0.0` in
   the series while the headline at `:1562-1564` correctly publishes `None`.
   **Make the series withhold, matching the headline.**

Do not touch the collinearity block at `:1442-1487` — correct and well documented.
No `test_failed_pairs` counter (out of scope).

`zscore: None` is safe: `schemas.py:584` types the series `List[Dict[str, Any]]`,
`:427 _carries_non_finite` passes non-numeric leaves through by design, and the
frontend has zero `zscore` readers.

`Verify:`
```
# sweeping p_value_threshold x lookback_days leaves len(_IN_MEMORY_COINT_CACHE) bounded
# a NEW test proves a zero-variance spread yields None/absent in the series matching the
#   headline -- and MUST fail against the pre-change code
uv run ruff check --select E9,F app/services/cointegration_service.py
uv run pytest -q --no-cov --no-header -p no:cacheprovider \
  tests/test_p03_coint_directive_gate.py tests/test_p03_coint_collinear_refusal.py \
  tests/test_p03_coint_stationarity_wire.py tests/test_pa1_optimizer_moments.py
   -> all pass
```

---

### T4 — an unoccupied HMM state must not be crowned `bull`
**status: SOLVE (verified: cagr=None; na_position="first"; 3-label vocab untouched; 17+23 green)**

`backend/app/services/regime_service.py:403` sets `cagr = 0.0` for an unoccupied
state, and `_label_states_by_risk` at `:59-60` sorts on `cagr` with **no
None-handling**. An unoccupied state therefore receives a fabricated `0.0`, competes
in `sort_values`, and can be labelled `calm` or `bull` with `historical_days_pct: 0.0`.

Make the fabricated `0.0` unreachable **in the ordering**. An unoccupied state must
not be ranked on a number that was never measured. Exclude it from the label
ordering, or withhold and rank last with an explicit marker. Do not invent a
substitute CAGR.

Preserve: `:373-391` (the correct -1.0 geometric result for a wiped-out state),
`:404` `ann_ret_method`, and `:709-725` the units explanation.

**`tests/test_regime_ann_vol_and_ann_ret_method.py:211-217` calls
`_label_states_by_risk` directly** and asserts the exact map
`{0: "crisis", 1: "bull", 2: "calm"}` plus order-invariance under `table.iloc[::-1]`.
Any approach that changes the ordering will hit it. Run it.

`Verify:`
```
# a NEW test proves an unoccupied state is never labelled bull/calm on a fabricated
#   value, and MUST fail against the pre-change code
uv run ruff check --select E9,F app/services/regime_service.py
uv run pytest -q --no-cov --no-header -p no:cacheprovider \
  tests/test_regime_ann_vol_and_ann_ret_method.py tests/test_regime_service.py \
  tests/test_regime_posterior_precision.py tests/test_regime_wiped_out_state_is_minus_one.py \
  tests/test_bug_sweep_2026_09.py
   -> all pass
```

---

### T8 — Black-Litterman: publish the Sharpe you actually optimised
**status: SOLVE (verified: BL out of SHARPE_OBJECTIVE_STRATEGIES; 112+139 tests green; 1 expectation flipped, disclosed)**

`optimization_service.py` is half-built and publishes a false claim:

- `_black_litterman_posterior` returns `(mu_bl, cov_bl)` at `:1034`.
- The solve genuinely maximises the posterior Sharpe `(mu_bl - r_f)/sqrt(w' Sigma_BL w)`
  at `:1142-1180`, correctly in excess space.
- But `optimize()` establishes `mu, cov` from **sample** moments at `:1296` and never
  rebinds them to the posterior, so the published `expected_sharpe` at `:1353`
  `_moments(mu, cov, w_vec, risk_free_rate)` is the **sample-moment** Sharpe.
- Meanwhile `:71` keeps `black_litterman` in `SHARPE_OBJECTIVE_STRATEGIES` and `:355`
  publishes `expected_sharpe_was_the_optimised_objective: True`.

**Either** plumb the posterior through so the published Sharpe is the one maximised,
**or** stop publishing `expected_sharpe_was_the_optimised_objective: True` and record
the real objective. Leaving the false claim is not acceptable.

Adjacent, same file: `min_cvar` claims "at the requested beta" at `:68`, but
`OptimizeRequest` (`analytics.py:135-172`) has no beta field, so `:1344` always passes
`0.95` (default at `:1263`). **Do not edit `analytics.py`** — owned by T9+T10 in
wave 2. If the field must be added there, report it instead.

`Verify:`
```
# assert the published expected_sharpe equals the objective that was maximised
# assert expected_sharpe_was_the_optimised_objective is either accurate or absent:
#   no path where it is True while the published number came from sample moments
uv run ruff check --select E9,F app/services/optimization_service.py
uv run pytest -q --no-cov --no-header -p no:cacheprovider \
  tests/test_black_litterman_quant.py tests/test_pa1_optimizer_moments.py \
  tests/test_coverage_quant_services.py
   -> all pass
```

---

### T6 — delete the fabricated EXPLAINERS prose
**status: SOLVE (verified: 5 pages clean, 20/20 red-proof, 629 tests; incl. forwarded regime-null work)**

The widest-spread honesty defect left, top-ranked confirmed defect in the p3 slice.
Static prose naming **real holdings with invented numbers**:

- `frontend/src/app/dashboard/tear-sheet/page.tsx:82` —
  `benchmark: 'Current Portfolio: 1.26 vs NIFTY 50: -0.20.'` (its "Quantitative
  Benchmark" heading is at `:248`)
- same file `:105` names MCX, Motherson, Redington with a 28.51% alpha; `:175`
  names Motherson 13.6%, JuniorBees 12.8%, Midcap ETF 10.5%.
- the same heading survives at `risk-studio:202`, `risk-contribution:182`,
  `regime:175`. On `liquidity` the string at `:192` is `Target Benchmark:` — same
  defect, different label.

`risk-studio` was partly de-fabricated already — its strings carry `e.g.`. Use that
as the pattern.

**Delete the invented figures and the named holdings.** Render from the response
where a real number exists; say so where none does. Do not replace a fabricated figure
with a different fabricated figure, and do not soften the wording instead of deleting
it — that is what `remediation-09` did and it is why the finding keeps recurring.

`Verify:`
```
# repo-wide: no "Quantitative Benchmark"/"Target Benchmark" string paired with a
#   hardcoded numeric return, and no hardcoded ticker+alpha pair
# add a test asserting the rendered output changes when the underlying metric changes
cd frontend
bun x tsc --noEmit     # 0 errors
bun run test:run       # all pass, including the test you added
bun x eslint src/      # 0 errors
```
Report exactly which strings you deleted and which you rewrote.

---

### T7 — stop calling a deterministic proxy a simulation
**status: SOLVE (verified: 307 ins; all 7 overclaims gone; basisOf has no fallback; 8 tests green)**

`frontend/src/app/dashboard/stress-testing/page.tsx`:
- `:63` declares `methodology?: string;` — **read nowhere in the file.**
- `:721` "Multi-Factor Simulation Engine", `:635` "Simulated Impact", `:829`
  "Run Simulation", `:115` "across all executed stress testing simulations".
- **Zero matches in `stress-testing/page.tsx`** for `max_drawdown_basis`,
  `impact_basis`, `recovery_time_basis`, `confidence_basis`, `shock_inputs`
  (these DO appear elsewhere in the frontend — the claim is scoped to this page).
- The backend publishes all of them: `analytics_engine.py:4736`
  `max_drawdown_basis: "derived_from_shock_proxy"`, `:4739`
  `impact_basis: "deterministic_factor_proxy"`, `:4742`
  `recovery_time_basis: "configured_recovery_estimate_not_simulated"`, `:4744`
  `confidence_basis: "nominal_label_not_simulated"`, `:4745 shock_inputs`,
  `:4751 methodology`.
- `:513` binds `scenario_description` only for the custom branch; built-in
  descriptions at `:394` remain hardcoded.

**Render what the backend already publishes** and stop describing a derived-from-shock
proxy as a simulation.

`Verify:`
```
# `methodology` is read; the *_basis fields are rendered; no "Simulation Engine" or
#   "Run Simulation" string remains where the result is a proxy
cd frontend
bun x tsc --noEmit     # 0 errors
bun run test:run       # all pass
bun x eslint src/      # 0 errors
```

---

# Wave 2

### T9 + T10 — one worker, `analytics.py` + `backtest_service.py`
**status: SOLVE (verified: 8 subscripts; bps 10.0 -> 11.1 ONE-WAY, corrected the brief's 2x claim; 11 tests)**

Both tasks are in `backend/app/api/analytics.py`, which is **dirty**. Run
`git diff -- backend/app/api/analytics.py > ...\before-T9T10.patch` first.
**The pre-existing uncommitted change occupies lines 7483-7501; `:7501` is the
subscript you must not disturb. `:7413` is committed code — leave it alone.**

**T9 — remove the fabricated defaults on the concentration route.** Eight sites,
all `.get(<key>, <plausible number>)`, on the **measured** path:
`:7479 largest_position`, `:7480 top_3`, `:7481 top_5`, `:7482 top_10`,
`:7502 effective_positions`, `:7503 diversification_score`,
`:7508 diversification_ratio (1.0)`, `:7509 gini_coefficient`.

Two are already correct and are your model: `:7279-7286` is a bare `.get(key)` with a
9-line comment explaining that an unreachable default is still the wrong shape, and
`:7501` is a subscript.

**Scope judgement.** `analytics_engine.py:7039-7042` (`_empty_concentration`) still
ships `0.0`/`1.0` for four of these, and the in-code comment at `:7048-7051` concedes
it deliberately — *"they are the same class of ambiguity, but they are a SEPARATE
disclosure and `risk_scoring` does not read either."* `risk_scoring` excludes the leg
with a reason at `:5396-5405`. So the remaining harm is a **disclosure gap, not a
scoring defect.** `analytics_engine.py` is owned by T11 — **report, do not edit.**

**T10 — `transaction_cost_bps` understates real friction ~2x.**
`analytics.py:181` `Field(default=10.0, ge=0.0, le=1000.0)` and
`backtest_service.py:25` `transaction_cost_bps: float = 10.0` -> `:81`
`cost_factor = transaction_cost_bps / 10000.0`. One flat, symmetric, undated constant
on both entry points against a real NSE delivery round trip of ~22-23bps — roughly
**2x understated** — and **asymmetric by construction**, since stamp duty is buy-only.
It cannot be correct across the 01-Apr-2026 Finance Act STT boundary.

This is the one finengine-side defect in a dependency-blocked cluster, fixable today.
**Scope it as a defect fix, not a modelling project:** stop publishing a symmetric
undated constant as if it were the true cost. Either default it to a defensible
measured figure **with the basis documented in a comment**, or make the date
dependence explicit. Do not build a full date-keyed schedule — say plainly which you
did. `backtest_service.py:40` rejects negative bps already; do not regress it.

Note: tests that import `backtest_service` will go red when the default changes. That
is the Verify working — update the assertion, do not revert the default.

`Verify:`
```
Select-String -Path backend/app/api/analytics.py -Pattern 'get\(.+,\s*(0\.0|1\.0)\)' -NotMatch:$false
   # regex form, NOT -SimpleMatch: report every remaining hit with its line
# on the MEASURED path no .get(<key>, <numeric default>) survives; a key the engine
#   fails to publish raises into the route's except Exception and returns 500 rather
#   than a zero. Confirm the n==0 branch at :7413 is UNCHANGED and still returns the
#   same keys.
# a NEW test pins the bps default and proves a round-trip cost is no longer ~2x below
#   the documented NSE round trip -- MUST fail against the pre-change value
uv run ruff check --select E9,F app/api/analytics.py app/services/backtest_service.py
uv run pytest -q --no-cov --no-header -p no:cacheprovider \
  tests/test_concentration_empty_hhi_absent.py tests/test_concentration_hhi_no_fabricated_default.py \
  tests/test_v3_routes_concentration_liquidity.py tests/test_backtest_window_and_annualize_gate.py \
  tests/test_agent_a_quant_fixes.py tests/test_contract_p1_batch.py
   -> all pass
```

---

### T11 — `analytics_engine.py`: two statistical fabrications
**status: SOLVE (verified: dropna replaces outcome filter; both tail keys withheld; 11+42 green)**

1. **`:5976`** `cvar_95 = ... else var_95` — for an empty tail the app publishes **two
   identical numbers** under different names. Withhold, or label.
2. **`:4527`** `non_zero = s[s != 0.0].clip(...)` — stress volatility filters on the
   **outcome variable** before computing dispersion, inflating every stress loss on
   exactly the targeted population (Indian small/mid-caps with flat sessions).
   `:4532` derives `ticker_vol` from the zero-filtered returns; `:4548` multiplies
   every `ticker_impact`.

**The repo documents the opposite rule and violates it.** `:6780-6781` says *"dropna,
not `!= 0.0`: keeps genuine 0% days, drops pre-listing/no-trade NaN gaps"* — ~2,000
lines earlier, no shared helper. Converge on the documented rule.

Also: `:4549` `min(-0.02, ticker_impact)` survives, disclosed at `:4642` as
`position_impact_clip: [-0.75, -0.02]`, so a user-requested "-1%" scenario still
publishes -2.00%. **Report whether you changed it; do not change the clip band without
saying so explicitly.**

Expect `tests/test_stress_bucket_and_score_floor.py` and
`test_analytics_engine.py:424` (`metrics["cvar_95"] < metrics["var_95"]`) and
`test_logic_sweep_properties.py:105` to be the exposed tests.
**`test_stress_bucket_and_score_floor.py` is dirty** (in-flight ticker renames) — its
baseline is not clean. Note that if you edit it, you are mixing with unrelated work.

`Verify:`
```
# a NEW test proves a series with genuine zero-return days now contributes to stress
#   volatility AND that pre-listing NaN gaps are still dropped.
#   MUST fail against the pre-change code -- this is the whole point.
uv run ruff check --select E9,F app/services/analytics_engine.py
uv run pytest -q --no-cov --no-header -p no:cacheprovider \
  tests/test_v3_semantics_liquidity_stress.py tests/test_stress_bucket_and_score_floor.py \
  tests/test_zero_dispersion_ratio_refusal.py tests/test_zero_dispersion_ratio_refusal_roundoff.py \
  tests/test_p03_coint_collinear_refusal.py tests/test_analytics_engine.py \
  tests/test_logic_sweep_properties.py
   -> all pass
```

---

### T12 — CI: `--dist loadfile -n 4`
**status: SOLVE (verified: --dist loadfile -n 4 at :119; advisory step preserved; contract test 10 passed unedited)**

`.github/workflows/ci-cd.yml:96` runs the backend suite **serially** while
`pytest-xdist>=3.6.1` is declared (`pyproject.toml:50`). The suite is compute-bound —
16 of 2868 tests carry 66.5% of call time — so this is the largest CI wall-clock win
available.

**`--dist loadfile` is mandatory, not stylistic.** Measured: under plain `-n 4` an
18-test file went 10.5s -> 20.6s, because each worker pays a fresh `import main`
(7.65s measured). `loadfile` keeps each expensive file whole on one worker.

**Cap at `-n 4`, not `-n auto`** — 7.2 GB RAM and each worker holds a full
pandas/numpy/scipy/statsmodels/arch/cvxpy graph.

Hazard audit returned **safe, zero exclusions**: `tmp_path` gives per-worker SQLite
files; `:memory:` + `StaticPool` is per-process; all 15 `os.environ` sites are
monkeypatch-scoped; all 7 module-global singletons are per-process; the autouse
`reset_service_memos` fixture clears all seven class-level memo dicts around every test.

**No test in the repo pins the pytest command.** `test_agent_d_deployment_contract.py`
reads `ci-cd.yml` at `:212` but asserts only the integration-file target at `:215` —
nothing about the pytest invocation. Re-run it unchanged; do not edit it.

`ci-cd.yml` is **dirty** — run
`git diff -- .github/workflows/ci-cd.yml > ...\before-T12.patch` first. The
uncommitted block is `@@ -95,6 +95,28 @@` (the advisory `check_test_assertions.py`
step with `|| true`). **Preserve it.**

`Verify:`
```
Select-String -Path .github/workflows/ci-cd.yml -Pattern 'pytest'   # shows --dist loadfile -n 4
Select-String -Path .github/workflows/ci-cd.yml -Pattern 'check_test_assertions'  # still present
uv run pytest -q --no-cov --no-header -p no:cacheprovider tests/test_agent_d_deployment_contract.py
   -> all pass, UNCHANGED file
```
Do **not** run the full suite. Root agent runs it once, alone, at the end.

---

## Explicitly NOT in this campaign (re-verified by momus, all hold)

- **`p3/08`** — `analytics_engine.py:3985` is byte-identical to what the ticket read,
  but `CONCENTRATION_DIVERSIFICATION_RATIO_FORMULA` (`:482-503`) states the two
  figures run on different scales and the ratio's minimum is `1/n` at one holding.
  **The prescribed `N<=1` guard would contradict a published formula.**
  → **unsolve**: close as SUPERSEDED.
- **`p4/01`** — `india_data_service.py:449`/`:452` guard a z-score computed at `:461`.
  Emitting from one observation publishes a z-score with no denominator.
  → **unsolve**: the prescription is the defect.
- **`p4/02`** — `database.py:240-252` `NSEBulkBlockDeal` declares neither `close` nor
  `close_price`. → **unsolve**: the target does not exist.
- **`p5-capability`** (21 files) — roadmap, not defects. → **unsolve**.
- **`p2-02` purge-and-refetch** — **DO NOT RUN.** 4 contaminated rows of 31,334
  legitimate ones. `StockTimeseries` has no provenance column; the rows are
  identifiable only by the `42.4 x 1.002 = 42.4848` arithmetic fingerprint. Needs a
  human decision.
- **History purge, force-push, the sanitise commit** — no mandate.
- **A full backend suite run** — root agent only, once, alone, at the end.

## Root-agent verification (Phase 5)

1. Record the frontend suite baseline **before** any worker adds a test.
2. Read every changed file's actual diff; confirm each `Verify:` output myself.
3. One full backend suite run, alone, on an idle box.
4. One full frontend suite run.
5. Update every `status:` line.

## Open decisions carried forward

1. **bfinance**: publish-then-bump, or pin and forget. T1's upper bound is a safe
   interim, not an answer. 22 tickets hang on it.
2. **The purge**: targeted 4-row delete, or leave it.
3. **Cron**: `CONTEXT.md t28` records it as deliberately deferred. Every `nse_*` table
   is permanently empty until revisited, and no producer exists for any of them.
4. **The sanitise commit.** Also load-bearing for durability: several "already fixed"
   verdicts rest on `analytics.py`, which is dirty.
---

## T14 — OPEN: the coverage thresholds are structurally inert
**status: open — needs an owner decision**

Found while implementing T13. **Not T13's file** (itest.config.mts is dirty with the
in-flight pool: 'threads' change), so it was reported rather than fixed.

itest.config.mts:24-31 uses the removed Vitest-1/2 nesting:
`js
thresholds: { global: { branches: 80, functions: 80, lines: 80, statements: 80 } }
`
In Vitest 5 the Thresholds shape is flat. Measured, same config, same suite:

`
bun run test:coverage                       -> exit 0, zero threshold errors
  Statements 71.89%  Branches 75.11%  Functions 65.04%  Lines 73.2%
--coverage.thresholds.lines=80 (flat)       -> exit 1
  ERROR: Coverage for lines (73.2%) does not meet global threshold (80%)
  ERROR: Coverage for functions (65.04%) does not meet global threshold (80%)
  ERROR: Coverage for statements (71.89%) does not meet global threshold (80%)
  ERROR: Coverage for branches (75.11%) does not meet global threshold (80%)
`

So the gate was fake **twice over**: the provider was absent (T13 fixed that), and the
global: key is inert (this). Un-nesting the four keys is a 2-line change that turns
	est:coverage red.

**Why it is not simply done:** it makes a command fail. CI does not run
	est:coverage (ci-cd.yml:168 runs un run test:run), so nothing breaks either way —
but turning a gate on and leaving it red is the owner's call, not a silent side effect
of a performance task. Worst-covered, if a coverage effort follows:
lib/api.ts 5.35% functions, ui/NotificationSystem.tsx 7.69%,
hooks/useRealTime.ts 11.42%.
---

## T15 — residual fabricated explainers (emerged during execution) — SOLVE
**status: SOLVE**

Found by T6 **after** five pages had already shipped: the same carrier under a
**third** label. olatility-sizing/page.tsx:48 carried the identical
enchmark?: string field rendered under Quantitative Guideline: at :232-234,
and :122 named four real holdings (NIFTYIETF, CIPLA, ELECTCAST, ARROWGREEN) plus
two more invented values (Standard equity risk budget: 15.0% annualized
volatility, Ideally aligned within ±1.0%).

Also found in T7's **already-shipped** work: stress-testing:315
Defensive utility and pharmaceutical stocks (NTPC, CIPLA) limit drawdowns to
-18% to -25%. T7 consciously left the howToInterpret array alone, judging
numeric bands to be interpretation thresholds — defensible for a band, wrong for
**named holdings**.

Fixed both following the pattern the five shipped pages established: field
deleted from the type, render block replaced by the data-driven
data-testid="explainer-measured" box with per-key not-measured reasons, formula
constants kept (tier boundaries the page's own code implements).

:314's -40% to -50% band was removed with a computation rather than a
judgement: worst case is -35% × 1.55 × 1.25 = -67.8% against a configured clip
of [-0.75, -0.02], so the band matched nothing the engine computes.

Question to the owner: **five pages shipped each the e.g. softening
emediation-09 used. Is the tier-band / benchmark-rule convention wanted back,
or does the educational core of these explainers go with it?** It is a deliberate
judgement call, not an oversight.

Verify: un x tsc --noEmit 0 errors; un run test:run 64 files / 657 tests /
0 failures (baseline 63/649 + 8 new); eslint 0 errors / 232 warnings (exact
baseline). Red proofs verified by SHA-256 with cmd /c redirection (PowerShell's
> writes UTF-16 and corrupts the proof). T7's 307-line change preserved
byte-exactly: numstat 307/32 -> 310/35, confirmed by Compare-Object on two
saved diffs.

## T16 — follow-up raised by T9+T10, NOT done
**status: open**

nalytics_engine.py:7016-7063 _empty_concentration still publishes four
fabricated readings on the no-book shape: effective_positions 0.0,
diversification_score 0.0, diversification_ratio 1.0, gini_coefficient 0.0.

T9's route subscripts make the gap **sharper**, not looser: a reader who gets
diversification_ratio: 1.0 with 
_holdings: 0 beside it cannot distinguish
"one holding" from "no book", and 1.0 is exactly what a single-holding book
measures. The asymmetry with herfindahl_index — already None (WM-6) on the
same shape — is the tell.

Needs: None for the four on the **no-book shape only**, with
diversification_score's legitimate  .0-at-one-holding invariant preserved
(the same trap the :7032-7037 comment already flags), plus a test pinning
{n==0 -> None, n==1 -> 0.0} side by side. Estimated four lines plus a test.
The engine owner has nalytics_engine.py; this ticket exists so the finding is
not lost.

## Final verification (root agent, Phase 5) — see chat
Full frontend suite: **64 files / 657 tests / 0 failures, 87.37s, exit 0**;
un x tsc --noEmit 0 errors; un x eslint src/ 0 errors / 232 warnings.
Full backend suite run **exactly as CI will run it** (--dist loadfile -n 4,
--cov=app --cov-fail-under=80) — result in chat; that invocation is the thing
T12 shipped, so the run doubles as its proof.