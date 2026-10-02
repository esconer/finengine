# Project memory — finengine

Durable, non-obvious findings. Durable = still useful in 6 months. Not status reports.

## DO NOT pin `OPENBLAS_NUM_THREADS=1` for pytest in this repo

**This cost a 6-failure false alarm and nearly a bad commit.** It is a trap, not a workaround.

Under memory pressure (many concurrent agents, free RAM < 1 GB) OpenBLAS/uvicorn fail to spawn with
*"Memory allocation still failed after 10 retries"*. The obvious response is
`$env:OPENBLAS_NUM_THREADS=1`. **Do not.** It changes BLAS reduction order, and this suite has
bit-pinned numerical literals that were captured on the multi-threaded path.

Measured 2026-10-03 on `backend/tests/test_forecast_precision_disclosure.py`, same machine, same
commit, `arch 8.0.0` / `numpy 2.5.3`:

| `OPENBLAS_NUM_THREADS` | pre-campaign worktree @ HEAD | campaign working tree |
|---|---|---|
| `1` | **6 failed** | **6 failed** |
| 2,3,4,5,6,8 or unset | **6 passed** | **6 passed** |

Deterministic *within* a thread count — not an FMA race, not run-to-run flake. Two concrete examples:

- `volatility_forecast` GARCH h=1: `0.1520577940669673` (threads=1) vs `0.15205779663036714`
  (threads=4) — a **2.5e-9** difference. The test pins `repr(round(x, 10)) == "0.1520577966"`.
- One EGARCH resample draw (draw 27, keep=31) fits `beta=0.370, gamma=-2.376` at threads=1 and
  `beta=0.915, gamma=-1915.1` at threads=4. **A ~1e-16 perturbation flips the MLE between a
  contractive basin and an explosive one.**

If OpenBLAS cannot spawn, the fix is **free memory** (stop the agents competing), not a thread pin.

**Corollary — bit-pinned floats are a latent hazard.** Any test asserting an exact
`repr(round(x, 10))` on a fitted or resampled quantity is machine-specific: SIMD width drives
reduction order, so the literal may not even reproduce on a different CPU. Prefer
`pytest.approx` with an absolute tolerance, or assert an invariant rather than a literal.

## Tooling traps on THIS machine (Windows)

- **`rg` with a quoted pattern containing `"` silently matches nothing.** A single `"` breaks it.
  **`-F` does NOT rescue it** — verified: `rg -F 'foo("'` returns zero on a file where
  `Select-String` and `rg -F 'foo'` both match. **Use `Select-String`**, or a quote-free pattern.
- **`Get-ChildItem -Recurse` misses dotfiles and hidden dirs** without `-Force`. An agent concluded
  `backend/.venv` "does not exist" because of this; it does, and `uv run` resolves packages from it.
  `.github/` and `.githooks/` are invisible without the flag.
- **Default `rg` respects `.gitignore`.** Under `.scratch/`, it sees **384 of 1849** `.md` files.
  Use `--no-ignore`. `backend-deep-audit/` alone is 1523 files / ~1.1 GB (mostly `.next` webpack
  packs and `node_modules`) — never read it wholesale.
- Runner is **`bun`**. `node`/`npm`/`npx` are NOT on PATH.
- Full backend suite is ~18 min and **hits `yfinance`/`bfinance` live**, so the pass count drifts
  with network and machine load. Concurrent agents running it produce meaningless interleaved
  baselines — subagents test only their own files; the root agent runs the full suite once.

## Python numeric traps that have produced wrong findings here

- **Python's builtin `min`/`max` silently swallow NaN; numpy propagates it.**
  `min(5.9, nan)` → `5.9`. `np.minimum(5.9, nan)` → `nan`.
  `min(30, nan*100)` → `30`; `np.minimum(30, nan)` → `nan`.
  **A clamp built on the builtin silently passes NaN through.**
- **`np.clip(-inf, 0, None)` is `0.0`.** A diverged solver's answer becomes a zero weight.
- **`float(np.complex128(...))` silently discards the imaginary part** and warns.
  `float(python_complex)` raises `TypeError`. Testing the wrong type inverts the conclusion.
- **`.get(key, default)` returns the stored value when the key is present** — including `None`.
  So publishing `None` to fix a fabricated default can poison a downstream `.get(key, 0.x)` into
  `TypeError`. Changing a *producer* to publish `None` requires auditing every *consumer* first.
- **`dropna()` drops NaN, not `-inf`.** A `-inf` survives and poisons a `StandardScaler`
  (`ValueError: Input X contains infinity`) instead of being filtered.

## Financial/quantitative conventions settled in this repo

- **Annualised volatility uses `ddof=1`** (pandas convention), matching `utils/holdings.py:452`
  and `api/analytics.py:10223`. `ddof=0` would shift figures ~0.2% at n=300.
- **Volatility published for display may be clipped; derived risk measures must not be.**
  The rule is written at `analytics_engine.py:4628-4631`: *"Use the un-floored model estimate…
  a 1% asset must not become a 5% peer."*
- **`MIN_ANNUALIZE_DAYS = 30`** (`utils/holdings.py:35`): below that, CAGR/Sharpe/Sortino/Calmar are
  `None`, not numbers — annualising a week of history fabricates triple-digit percentages.
- **Mean of annualised sigmas ≠ annualised volatility.** `mean(sqrt(252·v_t))` understates
  `sqrt(252·mean(v_t))` by a second-order Jensen term that tracks the **within-state dispersion**
  of the series — not the average level. A persistently calm series has a *small* gap.
  Measured in `regime_service.py`: crisis 6.08%, bull 5.70%, calm 2.26%.

## Durably unreachable code (verified, do not re-open without new evidence)

- **`regime_service.py`'s arithmetic `ann_ret` fallback is unreachable** — proven four ways:
  `cum_prod == 0` produces `-inf` that survives `dropna()` and crashes the scaler;
  `cum_prod < 0` needs `r < -1`, which yields NaN and is dropped before entering any state;
  underflow needs ~-0.93 log-return/day (≈60% loss daily). It is *also* arithmetically wrong in
  the `== 0` case — `0**(252/n) - 1 == -1.0` is well defined, so the guard discards a correct
  answer, and with n-1 days at +5% plus one at -100% it publishes a **positive** `ann_ret` for a
  state that lost everything. Fixing it would change `cagr`, which orders the state labels.
- **`cointegration_service.py`'s `det_order=0` is correct.** `coint_johansen`'s `det_order` is
  `{-1, 0, 1}` only — **not** `0..5`. Out-of-range values only *warn* and return **all-NaN
  critical values**, which makes every `stat > crit` False and reports "no cointegration, always".

## Project rule (the reason this repo exists)

**Never fabricate. Preserve missing values. A refusal is a valid answer; a fabricated number is the
defect.** Recurring manifestations, all previously real here:
- `0.0` published where nothing was measured (`sharpe`, liquidity score, correlation, EWMA vol)
- `datetime.now()` stamped as an `as_of` on a branch where no computation ran
- a `0`/`[]` substitution on one line silently failing to protect the line below it
- a `max_length` cap applied everywhere **except** the one list that reaches a vendor
- a fabrication guard applied to the short-sample branch but not the degenerate-value branch
- a guard that exists, reads as correct, and **cannot observe the value it tests**

**The recurring author-side question is not "is there a guard?" but "can this guard observe the
value it tests?"** Three separate real defects were guards of exactly that shape.