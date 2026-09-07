# Regime Final Hardening — Research Log & Decisions
**Date:** 2026-09-03 | **Branch:** `fix/regime-final-hardening` | **Result:** 337/337 backend tests pass (baseline was 288 passed / 3 failed)
**Data:** saved `^NSEI` 4y sample (987 rows, 966 obs), seed-pinned HMM fits

## 1. Fixed (with tests)

| # | Bug | Fix | Test |
|---|---|---|---|
| F1 | `TestRegime` 2 failures: `bench = Mock()` left `get_benchmark_df` sync → `await Mock` TypeError → 500 instead of 200/409 | `get_benchmark_df = AsyncMock(None)` (+ `get_returns` default None) in fixture; same in 409 test | `test_advanced_analytics.py` 9/9 |
| F2 | `_label_states_by_risk` `IndexError` for `n_components != 3` (`sorted_indices[2]`) | Generic `state_N` labels when `len != 3` | `test_label_states_non_three_state_no_crash` |
| F3 | Dead `signed_vol` branch (stats never carry it post-#9) + stale docstrings (signed-vol mapping, "calm/volatile/crisis", Fox-et-al sticky claims) | Simplified to cagr/ann_ret + honest docstrings (init values, EM re-estimates, fitted diag ≈0.96) | existing label test unchanged, passes |
| F4 | `__import__("asyncio")` wart | Top-level `import asyncio` | behavior-neutral, covered by p02 detect test |
| F5 | `tz_localize(None)` raises on naive indexes (pandas 2.x) in `detect_regime` portfolio path | Strip tz only when `idx.tz is not None`, both frames | `test_detect_regime_naive_tz_portfolio` |

## 2. Researched and DELIBERATELY SKIPPED (measured, not assumed)

| Audit claim | Measurement on real data | Decision |
|---|---|---|
| Fake sticky prior (init washed out by EM) | `transmat_prior`/`startprob_prior` vs init-only: identical score (−1629.7), stability (97.7%), transmat diag (0.96). Data overwhelms prior at 966 obs | Skip: zero behavioral effect; would be cargo-cult |
| Single restart → local-optimum risk | 5 seeds: scores −1629.7/−1640.9 (0.7% spread), identical stability and diag | Skip: 5× fit cost for ~0 gain |
| Missing `min_covar` guard | hmmlearn 0.3.3 default IS `min_covar=1e-3` (verified via signature); explicit 1e-3/1e-6/None all identical | Skip: already covered by library default; audit claim was wrong |
| Full-sample scaler lookahead | Expanding (leave-last-out) vs full scaler: 100.0% label agreement, same stability | Skip: behaviorally nil |
| Smoothed last-bar probs lookahead | No public filtered API in hmmlearn 0.3.3 (`_forward_lattice`/`_do_forward_pass` both absent; verified); reaching into Cython privates is fragile | Skip: UI already shows full posterior + stability; revisit only with newer hmmlearn |

Scripts (Temp, outside repo): `regime_research.py` (E-a..E-e), `regime_exp*.py`, `regime_m1a.py`, `regime_blind.py`, `regime_server.py`, `regime_diag*.py`, `regime_tune.py`, `regime_verify.py`, `cache_inspect.py`, saved `nsei_4y.pkl`.

## 3. Known remaining limitations (P1 research, not this PR)

- **Early-crash lag** (trailing 21d blind ~2-4 weeks): measured responsive-feature variant dropped stability 97.7% → 85.4% for −1 bull-day gain. Responsiveness/chatter tradeoff needs real prior work first (transmat priors only matter at short windows).
- **Repo-wide `ruff check` red**: 92 hits in 2 untouched files alone; no ruff config in repo. Pre-existing, out of scope (would be its own PR).
- **`GET /regime` has no `response_model`** (bare Dict): additive keys safe, but contract is implicit. P1: add explicit response schema.
- **Mock-200 envelopes** on other analytics routes: P1 (needs frontend coordination), unchanged here.

## 4. Verification

- New/updated: `test_regime_service.py` (+2), `test_advanced_analytics.py` fixture (2 fixed).
- Full suite on branch: **337 passed, 0 failed** (baseline 288/3 on master).
- Neighbor suites re-run green; regime combo with #1 verified earlier (16/16).
