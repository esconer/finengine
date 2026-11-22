# Verified backlog — wave 3 — 2026-10-09

Follows `plans/2026-10-06-verified-backlog-fixes.md` (13 tasks, all shipped and verified
by the root agent). Full backend suite after T17: **1 failed, 2952 passed, 87.94%
coverage, 8:18** at `--dist loadfile -n 4`. Frontend: **64 files / 657 tests / 0
failures, 87.37s**.

Everything below was verified against the working tree by six `explore` slices before
being written here. Cited line numbers come from those passes and **may have drifted** —
the file is authoritative, not this document.

## Constraints binding every worker (unchanged)

- **No commits.** Never `git stash`/`checkout`/`restore`.
- **Never** set `OPENBLAS_NUM_THREADS` — it flips BLAS reduction order and six
  bit-pinned tests fail at `1`.
- `C:\es\coding\bfinance` is **OFF LIMITS.**
- `--no-cov` on scoped pytest runs (`--cov` was removed from `addopts`; `--cov-fail-under=80`
  now lives only on the CI command line at `ci-cd.yml:119`).
- `ruff` is not on PATH — **use `uv run ruff`**.
- **Do not run the full backend suite.** Scoped files only. The root agent runs it once,
  alone, at the end. A concurrent suite produces spurious
  `OpenBLAS error: Memory allocation still failed after 10 retries` in
  `tests/test_seed_determinism_invariants.py` — that is contention, not a regression.
- PowerShell 5.1: `||` is not a separator; `@{u}` parses as a hash literal; in `-like`,
  `?` is a wildcard; `Select-String -SimpleMatch` takes the pattern **literally** —
  never escape it, and remember `-SimpleMatch` on `'\.get\('` matches nothing.
- Before editing any already-dirty file, record
  `git diff -- <file> > C:\Users\Sayanti\AppData\Local\Temp\opencode\before-<task>.patch`.
- **Do not weaken a refusal to make a test pass.** `pyproject.toml` documents five tests
  that legitimately assert a refusal. A failed measurement must refuse, never publish a
  plausible number.

## File ownership — no two wave-A tasks share a file

| file | task |
|---|---|
| `tests/test_coverage_api_branches.py`, `tests/test_coverage_deep_analytics_routes.py`, `tests/test_coverage_analytics_all_routes.py` | A1 |
| `app/services/analytics_engine.py` | A2 |
| `app/api/analytics.py` | A3 |
| `app/services/data_service.py`, `app/services/alpha_vantage_service.py`, `app/services/company_data_service.py`, `app/services/indicators_service.py` | A4 |
| `app/models/schemas.py`, `app/services/currency_service.py`, `app/api/portfolio.py` | A5 |

Deferred to wave B, because both need `app/models/database.py` **and** `data_service.py`,
which wave A owns: **B1** `p2/05` cache-key source dimension, **B2** `p4/07` shareholding
restatement key.

---

## A1 — test-fixture honesty: three latent flakes and one live vendor call
**status: open**

Four defects, three files, one root cause class: **a fixture that lies to the engine.**

### (a) Three zero-mean fixtures, each a latent ~1-in-4 flake

`POST /optimize/run` refuses with 400 when
`app/services/optimization_service.py:966-969` finds
`(excess <= 0).all()` — i.e. every expected return at or below the risk-free rate.
`risk_free_rate = 0.02` (`config.py:53`).

The three fixtures build their universe with **exactly zero drift**, so the max-Sharpe leg
fails whenever the sample mean lands under 2% annualised:

| file:line | drift | expected flake |
|---|---|---|
| `tests/test_coverage_api_branches.py:18` | `normal(0, 3, days)` — **exactly zero** | ~1 in 4 |
| `tests/test_coverage_deep_analytics_routes.py:18` | `normal(0, 15, days)` — **exactly zero** | ~1 in 4 |
| `tests/test_coverage_analytics_all_routes.py:19` | `normal(0.0005, 15, days)` on 3500 → ≈0.05%/yr | ~1 in 4 |

**The precedent for the fix is already in this repo and must be copied, not reinvented.**
A session already fixed this exact defect class in
`tests/test_coverage_deep_api_endpoints.py` and `tests/test_coverage_massive_api_sweep.py`:
add drift so the premise is true **and** seed per ticker for reproducibility, using
`default_rng(zlib.crc32(ticker))` — the `conftest.py:535` idiom. `crc32`, **not**
`hash()`, which `PYTHONHASHSEED` salts. Distinct tickers must get distinct series: two legs
on one seed make the covariance exactly singular, which is a worse bug.

Do **not** simply seed. Seeding alone freezes whichever side of the 2% hurdle the draw
happened to land on — either a reliably-failing test or a masked question. **Drift is the
fix; the seed is reproducibility.** Verify the margin is not luck: confirm `z > 0` holds
at step means from 1.0 to 3.5, not just at the seed you chose.

Note `test_coverage_deep_analytics_routes.py` uses `strategy="hrp"`, which reads only the
correlation matrix and never `mu` — so it is likely benign. **Determine that rather than
assuming**, and say which.

### (b) One live vendor call — this is the suite's remaining red test

```
FAILED tests/test_coverage_analytics_all_routes.py::TestAnalyticsAllRoutesWithData::
        test_analytics_routes_populated
```
Traceback at `:175`, `assert res_opt.status_code == 200` → **400**. The failing endpoint
is **`POST /api/v1/analytics/optimize/run`**, not `/concentration`. Logged cause:
`"Liquidity quote fetch failed for TCS.NS / INFY.NS"` — an unmocked `^NSEI` benchmark.

It **passes in isolation**; it fails only under full-suite load, because the live vendor
either rate-limits or misses. That is a test one network blip from failing CI.

A sibling fix already landed this session for a different instance of the same class: five
files were patched at both seams — `app.api.analytics.BenchmarkService` **and**
`app.services.regime_service.BenchmarkService`, because `regime_service.py:537`
constructs one directly and bypasses FastAPI DI. **Find whether this optimize-path fetch
has the same shape**, and copy the working pattern from
`tests/test_advanced_analytics.py:52-53` (`patch_market`), which is the file that already
gets both seams right.

The durable proof is a **socket-blocking guard**. A previous agent used a scratch pytest
plugin under `C:\Users\Sayanti\AppData\Local\Temp\opencode\` (outside the repo) reporting
`zero non-loopback socket attempts`. **Its known blind spot: yfinance routes through
`curl_cffi`, which bypasses `socket.getaddrinfo`.** So a clean socket report does not prove
zero vendor traffic — say so, and use a vendor-call counter where the socket layer cannot
see.

**Do not** add `skip`, `xfail`, or `@pytest.mark.slow`.

`Verify:`
```
cd C:\es\coding\finengine\backend
uv run ruff check --select E9,F tests/test_coverage_api_branches.py tests/test_coverage_deep_analytics_routes.py tests/test_coverage_analytics_all_routes.py
uv run pytest -q --no-cov --no-header -p no:cacheprovider tests/test_coverage_api_branches.py
uv run pytest -q --no-cov --no-header -p no:cacheprovider tests/test_coverage_deep_analytics_routes.py
uv run pytest -q --no-cov --no-header -p no:cacheprovider tests/test_coverage_analytics_all_routes.py
```
**Run each of the three at least 8 times, sequentially**, and show 8/8. A single green run
proves nothing about a 1-in-4 flake — that is the entire point of (a). Quote all run IDs.
Vendor-call count for `test_coverage_analytics_all_routes.py`: before vs after.

`tests/test_coverage_analytics_all_routes.py` is dirty from an earlier in-flight mock
change — record its diff before editing and preserve it.

---

## A2 — `_empty_concentration`: four fabricated readings left on the no-book shape
**status: open**

`backend/app/services/analytics_engine.py:7076-7077` publishes
`largest_position: 0.0` and `top_3: 0.0`; `:7039-7042` publishes
`effective_positions: 0.0`, `diversification_score: 0.0`,
`diversification_ratio: 1.0`, `gini_coefficient: 0.0`.

`herfindahl_index` on the same shape is already `None` — the WM-6 fix, with a 17-line
comment explaining that `HHI = Σw² ≥ 1/n > 0` for every non-empty book, so `0.0` is not a
reachable *measurement*, it is a third value. **That asymmetry is the tell: the same shape
was corrected for one key and left for the others.**

Wave 2's route subscripts (`analytics.py:7521-7551`) made the gap **sharper**: a reader
who receives `diversification_ratio: 1.0` beside `n_holdings: 0` cannot distinguish
"one holding" from "no book" — and `1.0` is exactly what a single-holding book measures.

**The trap, which the code's own comment at `:7032-7037` already flags:**
`diversification_score: 0.0` is **correct at one holding** and is a documented invariant.
Only the **no-book** shape may change. Do not blanket-convert these to `None`.

Apply the same treatment as `herfindahl_index`: `None` on the no-book shape, with the
reason recorded in a comment. Keep the key present — a key holding `None` is what
`.get(key, 0.0)` was returning `None` from, not `0.0`.

**Add a test pinning `{n == 0 → None, n == 1 → 0.0}` side by side.** A test that asserts
only the `n == 0` case will pass while the one-holding invariant silently breaks.

`Verify:`
```
cd C:\es\coding\finengine\backend
uv run ruff check --select E9,F app/services/analytics_engine.py
uv run pytest -q --no-cov --no-header -p no:cacheprovider \
  tests/test_concentration_empty_hhi_absent.py tests/test_concentration_hhi_no_fabricated_default.py \
  tests/test_v3_routes_concentration_liquidity.py tests/test_coverage_direct_unit_routes.py \
  tests/test_quantitative_invariants.py
```
Prove the new test **fails against the pre-change code** — hand-revert in-file, run,
capture, restore. No `git stash`/`checkout`.
Confirm `test_quantitative_invariants.py:243-253` (which pins both ends and the
`CONCENTRATION_DIVERSIFICATION_RATIO_FORMULA` orientation text) is **unchanged and green** —
it is the test that forbids an `N<=1` guard here.

---

## A3 — CVaR contribution shares: a real hedge is published as 1e-12 of float noise
**status: open**

`backend/app/api/analytics.py:10295` normalises contribution shares by
`total = sum(abs(c) for c in comp)` — the sum of **magnitudes**.

The sibling volatility leg at `:10247` normalises by the **signed** sum
(`contrib = contrib / contrib.sum()`).

So a genuine hedge — a gold ETF, a low-beta leg, routine — makes the CVaR shares sum
**below 1**, and the shortfall is then published as `rounding_residual` (`:1749`, `:1760`)
at 1e-12 magnitude. The app frames a real offset as float noise. The sector rollup at
`:10303-10317` inherits the same non-unit total.

All three proposed remedies — `hedge_offset`, `gross_contribution`, `net_contribution` —
have **zero** matches in the backend.

### The test that does not pin the defect

`tests/test_advanced_analytics.py:106`:
```python
assert abs(sum(cvar_rc.values()) - 1.0) < 1e-6 or cvar_rc == {}
```
The `or cvar_rc == {}` means it **passes against the bug** — it is satisfied by the
no-hedge case and by an empty dict alike. Fixing the assertion is part of the task.

**Decide and justify** whether the fix is a signed normalisation, a published
`hedge_offset`, or both. Do not silently renumber existing consumers: state who reads these
fields. Keep the shares summing to 1 **on the no-hedge case** so nothing that reads the
total breaks.

`Verify:`
```
cd C:\es\coding\finengine\backend
uv run ruff check --select E9,F app/api/analytics.py tests/test_advanced_analytics.py
uv run pytest -q --no-cov --no-header -p no:cacheprovider \
  tests/test_advanced_analytics.py tests/test_risk_contribution_frame_alignment.py \
  tests/test_v3_routes_concentration_liquidity.py tests/test_quantitative_invariants.py
```
Add a test with an **actual offsetting leg** asserting the published shares are honest
about the offset. **Prove it fails against the pre-change code.**
Report whether `test_advanced_analytics.py:106` was weakened, and if so show why the new
form is strictly stronger.

---

## A4 — three vendor-logic defects in the data layer
**status: open**

Three tickets, one owner (`data_service.py` is the single contested file this wave).

### (a) `p2/12` — Alpha Vantage Tier-3 is structurally dead, yet every failure row claims it ran

`app/services/alpha_vantage_service.py:34` `AV_SYMBOL_MAP: Dict[str, str] = {}` — empty.
`:85-88` `to_av_symbol` returns `None` for any ticker ending `.NS`/`.BO`/`.BSE`.

So the third cascade tier **can never run** for an Indian universe, and the 25 req/day
budget (`config.py:61`) can never be spent. But
`app/services/data_service.py:894` writes `source_used="alphavantage"` on total cascade
failure — **every failure row attributes the failure to a tier that was never attempted.**

Either stop claiming it, or record honestly that the tier was unreachable. Do not
fabricate a symbol map — the `:32-33` comment says mapping requires verified
identity-specific checking, which is a human task.

### (b) `p2/19` — a total vendor outage emits **no log line at all**

`app/services/company_data_service.py:214`
`logger.debug('bfinance fundamentals unavailable for %s: %s', ...)`. The configured
`log_level` defaults to **INFO** (`config.py:68`), so `logger.debug` produces nothing. A
full bfinance outage is therefore invisible in the logs.

`had_outage` is set but consulted only when every tier fails. The redaction helper
`_safe_provider_message` (`cache_service.py:30-33`) exists and is not used here.
`ai_dossier_service.py:51,73,91,109` interpolate raw `{e}`.

Raise to a level that is actually emitted, route the message through the redaction helper,
and name the provider. Do not log the upstream text verbatim.

### (c) `p2/15` — `dropna()` compresses the time axis, and the repo documents the opposite

`app/services/data_service.py:1521-1522` — a whole-frame `df = df.dropna()`. **Any** NaN in
**any** column drops the row, so the index loses real trading days. Every quantitative
service upstream inherits the compressed axis.

`app/services/indicators_service.py:93-96` carries the contradicting comment — *"Dropping
a missing Close row would compress the time axis"* — so **the repo documents the defect in
one file and commits it in another.** Converge on the documented rule.

Say whether this is a behaviour change (it is) and which consumers could notice. This is the
riskiest of the three; if you judge it needs its own review, **report that and stop** rather
than shipping it inside a bundle.

`Verify:`
```
cd C:\es\coding\finengine\backend
uv run ruff check --select E9,F app/services/data_service.py app/services/alpha_vantage_service.py app/services/company_data_service.py app/services/indicators_service.py
uv run pytest -q --no-cov --no-header -p no:cacheprovider \
  tests/test_source_preference_and_cache.py tests/test_agent_b_data_audit.py \
  tests/test_coverage_alpha_vantage.py tests/test_coverage_data_service.py \
  tests/test_coverage_engines.py tests/test_ai_context.py
```
For (a): a test proving a `.NS` cascade failure no longer attributes itself to the
unreachable tier. **Prove it fails against the pre-change code.**
For (b): a test proving an outage is visible at the configured default log level.
For (c): a test proving the index keeps its real trading days, **and** that NaN gaps are
still dropped. **Prove it fails against the pre-change code.**

---

## A5 — the position contract publishes no quote provenance, and FX has no history
**status: open**

### (a) `DF-001`/`DF-002`/`DF-006` — fetch time is the only timestamp available

`grep 'quote_source|price_as_of|is_delayed|delayed|market_time|quote_time'` over
`app/models/schemas.py` returns **zero** matches. The position contract carries no provider
market timestamp, no quote source, and no delayed/live flag.

So "fetch time is not a quote as-of time" is still true, and nothing timestamps a provider
response. `portfolio.py` already publishes `price_as_of` + `price_as_of_semantics` and
`snapshot_consistency.per_position_price_as_of` (wave-2 work), so the **barrel-date
discipline exists on the portfolio envelope** — this task extends it to the contract.

Start by reading what `portfolio.py` already publishes and **follow that shape** rather than
inventing a second vocabulary.

### (b) `DF-003` — no daily historical FX, so mixed-currency history is wrong

`app/services/currency_service.py` caches a **single 30-minute snapshot rate**. Any
historical return computed across a currency boundary uses today's rate. The service does
carry `coerce_live_fx_rate` and provenance tags — reuse them.

Scope honestly: a **dated FX series** is a real feature, not a defect fix. If it needs a new
table and a producer, **report it as a capability gap and do not fake it with the snapshot
rate.** What you may fix here: make the *absence* of a historical rate visible rather than
silently applying today's.

`Verify:`
```
cd C:\es\coding\finengine\backend
uv run ruff check --select E9,F app/models/schemas.py app/services/currency_service.py app/api/portfolio.py
uv run pytest -q --no-cov --no-header -p no:cacheprovider \
  tests/test_agent_c_api_contracts.py tests/test_p1_currency_contract.py tests/test_p1_quote_sanity.py
```
If those test files do not exist, **find the real ones** (`ls tests/`) and report what you
found — do not invent a path.
Add a test proving a mixed-currency historical response either carries a dated rate or says
the rate is unavailable. **Prove it fails against the pre-change code.**

---

## Deferred to wave B — reason: `data_service.py` and `models/database.py` contention

**B1 — `p2/05` cache-key source dimension.** `app/models/database.py:104`
`UniqueConstraint('ticker','date')` plus
`data_service.py:1776` `on_conflict_do_update(index_elements=["ticker","date"])` means two
vendors overwrite each other on `(ticker, date)`. **A mid-window fallback injects a seam
into every return series** — a spliced price discontinuity that no test currently detects.
Also still present: the Alpha Vantage special-case guard (`:1748-1771`) and
`int(row["volume"])` at `:1741`, which truncates fractional vendor volume.
Needs a schema migration — the highest-risk item in the backlog.

**B2 — `p4/07` shareholding restatement key.** `database.py:280-282`
`UniqueConstraint("symbol","period_ended")`, no `revision_date` column, and
`migrations/schema_version.py:175` records the same two-column key. A restatement
**silently overwrites history**. Currently harmless only because no producer exists and no
reader does; the corruption is live the moment anyone writes to that table.

---

## Explicitly NOT in wave 3

- **T14, the dead `thresholds.global` key** — `vitest.config.mts:24-31`. Un-nesting is 2
  lines and turns `test:coverage` red at the real numbers (statements 71.89%, lines 73.2%,
  branches 75.11%, functions 65.04%). CI does not run `test:coverage`, so nothing breaks
  either way. **Owner decision, not a side effect of a bug-fix task.**
- **`p3/08`** — the prescribed `N<=1` guard contradicts
  `CONCENTRATION_DIVERSIFICATION_RATIO_FORMULA` (`:482-503`). **unsolve.**
- **`p4/01`, `p4/02`, `p5-capability`** (21) — misdiagnosis, non-existent target, roadmap.
  **unsolve.**
- **`p2-02` purge-and-refetch** — **DO NOT RUN.** 4 contaminated rows of 31,334. Needs a
  human decision.
- **`isolate: false` for vitest** — ~26.32s available but breaks 64 tests on leaked globals.
- **History purge, force-push, the sanitise commit** — no mandate.
- **A full backend suite run** — root agent only, once, alone, at the end.

## Open decisions carried forward

1. **T14** — switch the frontend coverage gate on and leave it red, or leave it inert?
2. **bfinance**: publish-then-bump, or pin and forget. 22 tickets hang on it. Wave 1's
   upper bound (`>=0.1.0,<0.2.0`) is a safe interim, not an answer.
3. **The purge**: targeted 4-row delete, or leave it.
4. **Cron**: `CONTEXT.md t28` records it as deliberately deferred. Every `nse_*` table is
   permanently empty until revisited, and no producer exists for any of them.
5. **The sanitise commit.** Also load-bearing for durability: several "already fixed"
   verdicts rest on dirty files.
6. **The explainer tier bands** — six pages shipped with formula constants and tier bands
   deliberately kept, judged to be rules rather than measurements of this book. Reasonable,
   but a judgement call worth confirming.