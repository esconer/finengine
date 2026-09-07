# Holding-Aware Fix — No More Phantom History
**Date:** 2026-09-04 | **Trigger:** user report — regime card showed −21.2% "annualized" crisis return on a book that actually made +13.4% since import
**Committed directly to master** (per user: no PR ceremony for single-user repo).

## 1. Root cause (verified against real `data/daisy.db`, read-only)

- All 14 positions bulk-imported **2026-08-27 within ~90 seconds** (CSV importer). True holding history: **7 days**. Ledger: cost ₹37,905 → value ₹42,990 = **+13.4% realized**.
- `_build_wide_returns` combined **current weights × full price history**; `added_on` existed on every row but **no returns computation read it**. The 273 "overlap" crisis days were ~266 days of pre-purchase phantom history.
- Replication: same book over ALL last-273d = +21.0%/yr; crisis-filtered = −21.2%/yr. Same book, same window — the filter selects down-days and 2×-vol amplifies them. Arithmetically consistent, economically hypothetical, presented as "YOUR annualized return" with zero disclosure.

## 2. Fix: holding-aware realized analytics

- New `backend/app/utils/holdings.py` (pure, tested): `MIN_ANNUALIZE_DAYS=30`, `effective_start` (intersection = latest import), `mask_to_holding` (drop pre-composition rows; DatetimeIndex only, else no-op), `holding_coverage` disclosure payload, `apply_annualization_gate` (nulls CAGR/Sharpe/Sortino/Calmar/ann-vol below 30 covered days, always flags `annualized`), `portfolio_regime_summary` (total + gated CAGR), `coerce_holding_date`.
- `_build_wide_returns(..., active_from=None)`: masks + `ValueError` on empty (→ existing 404 paths). Default None = unchanged.
- Wired (realized only): realized-risk, factor-exposure, risk-score, summary, performance-history (list truncates; shape preserved), tear-sheet, risk-contribution, regime portfolio path. Each gains additive `history_coverage` (+ `annualized` flags where ratios exist).
- Deliberately NOT wired (documented hypothetical): optimize, backtest, monte-carlo, stress-test, liquidity, volatility-sizing, correlation, coint, tails, screener.
- `detect_regime` portfolio block refactored onto the pure helper (same numbers ≥30d; <30d now reports total + `annualized:false` instead of triple-digit CAGR artefacts).
- Frontend (`regime/page.tsx` only): coverage footnote ("Based on N days of actual holding history since …"), Total-vs-Annualized label switch, null-safe colors/CSV. Tear-sheet/overview already null-safe (`N/A`, `|| 0`).

## 3. Test honesty fallout (expected, fixed)

- Fixtures represented impossible portfolios (2024-25 synthetic prices owned since "now"): `seeded_positions`, `portfolio_position_factory`, 3 direct-route positions, and 4 add-then-analyze suites now use `added_on=2020-01-01`.
- New `tests/test_holding_aware.py` (8 tests): truncation, ad-hoc passthrough, empty→ValueError, coverage shape, gate helper, regime-summary branches, tear-sheet short-history gating, starts resolution. Two of them caught real implementation bugs during development (rounding expectation, Query-default start/end).
- Full suite green; frontend tsc + 62/62 vitest green.

## 4. Known limitations (not in scope)

- Composition changes AFTER import (later buys/sells/rebalances) still use current weights backward — true time-weighting needs an events ledger (future).
- `added_on` edits via CSV re-import reset history; documented behavior.
- Mock-200 envelopes + repo-wide ruff red: unchanged, still P1.

## 5. Follow-up: buy-implied starts + benchmark gating + regime card (same week)

Investigation of live screenshots (4 subagents, read-only) found the first
version incomplete in four ways — all fixed and committed to master:

1. **`added_on` is itself untrustworthy.** Ledger forensics over
   `stock_timeseries` proved 10/14 positions are OLD holdings (cost basis
   last traded 22–507 days before the Aug-27 stamp; MOTHERSON +85% in
   "7 days" is impossible). The importer stamps `added_on` at insert and
   `bulk_add` skips duplicates, so rows were deleted+re-inserted with old
   cost re-typed. Fix: per-ticker effective start =
   `min(added_on, buy-implied-date)` (most recent pre-import close within
   2% of `buy_price`, raw unfilled frames, fallback `added_on`).
   New: `implied_start_from_price`, `effective_starts`, `holding_window`
   (shared intersection cutoff; dateless frames pass through);
   `resolve_holdings` replaces `resolve_holding_starts`;
   `_build_wide_returns(..., holdings=None)` now returns
   `(returns, series, coverage)`.
2. **Benchmark metrics annualized 3-day noise** (NIFTY SHARPE −13.41,
   VOL 4.74%, BETA −0.63 — reproduced to the digit). `benchmark_*`
   standalone stats now use the FULL window; `beta`/`alpha` gated on
   `len(common) ≥ 30` (+ `overlap_days`); the old `len(bench_ret)>20`
   gate checked the wrong length.
3. **Regime card vanished** (`>=5` overlap gate fails on young books;
   frontend couldn't distinguish from empty). The block is now always
   emitted (helper already handles <30d); top-level `history_coverage`
   distinguishes states; the swallowed `ValueError` is logged.
4. **Display fallout**: dashboard `|| 0` → `?? null` + N/A (vol/Sharpe +
   `RiskMetricsDisplay` props); realized-risk `formatRatio` null-safe +
   `!=null` guards; tear-sheet coverage chip + Holding Total + sign-aware
   alpha (`+-60.28%` was a hardcoded `+` on a negative); header clock
   writers added to risk-contribution/tear-sheet/concentration;
   "exchange feeds" copy → "analyzed window" (engine) + holding-period
   banner (route).
5. **`.values`-on-ndarray silent passthrough** caught mid-work (all masks
   no-op'd): fixed + hash-verified; ruff gate caught a missing `Tuple`
   import in the same pass.
- Full suite: **348 green** (11 holding-aware incl. implied-date,
  gating, young-book card tests); tsc + 62/62 vitest green.
