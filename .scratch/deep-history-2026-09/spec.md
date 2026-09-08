# Deep History — cache-max OHLCV, truthful disclosure, full-history headlines

Status: completed | Owner: agent | Created: 2026-09-08 | Completed: 2026-09-08 | Decisions: all phases, vendor-max (~10y) backfill

## Verification

- Backend 435/435 pytest, ruff E9+F clean; frontend tsc clean, 88/88 vitest (16 files).
- Diversification "100%": investigated, formula-correct (11.6 effective
  positions ≥ 10-stock cap × 4+ sectors = 100.0); display now 1-decimal.

## Diagnosis (verified in code + live screenshots, 2026-09-08)

1. "24–25 trading days" warnings are holding-window **intersection**
   (`holding_window` masks to `max(effective_starts)`, `holdings.py:101-142`),
   but copy blames "exchange feeds": `holding_coverage.truncated` compares
   the OLDEST holding to requested start (`holdings.py:166`), so staggered
   buys → `truncated=False` → wrong else-branch (`analytics.py:359-362`).
2. Cache is shallow by design: miss re-downloads exactly the requested
   window (`data_service.py:119-214`); endpoints request ≤1Y, so depth ≈
   max requested window. Union/upsert machinery already exists — only a
   depth policy is missing.
3. Tear-sheet headline = intersection-truthed (~25d) N/As while the answered
   `full_history` block (CAGR 26.48%, β 1.07) hides below. Full-history
   spans disagree per endpoint (251 vs 175d) — undisclosed request windows.
4. Dashboard Ann Vol N/A: summary uses masked vol + 30d gate. Diversification
   "100%" needs a rounding check.

## Phases (issues/13–17)

- 13: Phase 0 evidence — cache census, intersection proof, vendor-max check.
- 14: Phase 1 deep cache — vendor-max backfill on miss/stale, serve slices,
  ticker-keyed L1, per-ticker coverage API.
- 15: Phase 2 disclosure — `truncated` redefined, `intersection_start` +
  per-ticker raw/masked days, three-case warning copy, collapsed banner.
- 16: Phase 3 tear-sheet — full_history headlines + full_relative β/α,
  holding window demoted to "Current book" section, cache-depth standard.
- 17: Phase 4 dashboard — `summary.instrument_volatility`, 1-decimal
  diversification.

## Hard constraints

- Intersection semantics stay for realized P&L (never attribute
  pre-purchase action — phantom-history bug must not return).
- No fabricated numbers: nulls + flags; headline changes labeled
  unmistakably (5.48% → 26.36% will confuse without labels).
- Backend 418+ pytest, ruff E9+F; frontend tsc + vitest; live pass on the
  14-position book with screenshots before commit.
