# 13 — Phase 0 evidence

Status: in-progress | Pri: P1

## Queries (read-only, `backend/data/daisy.db`)

1. Per-ticker cache census: `SELECT ticker, MIN(date), MAX(date), COUNT(*) FROM stock_timeseries GROUP BY ticker` — separates intersection truncation from genuine feed gaps (NIFTYIETF ~10d?).
2. Holdings: `SELECT ticker, added_on, buy_price FROM portfolio_positions` — confirm newest effective start ≈ 2026-08-03 (25 trading days to 09-08).
3. Confirm `history_coverage.truncated=False` live (`GET /analytics/realized-risk` → `history_coverage`) while bullets show feed-blame copy.

## Code checks

- Vendor-max horizon for `.NS`: yfinance `period="max"` vs bfinance equivalent (see `_download_with_timeout` + `_fetch_from_alpha_vantage` bounds).
- Diversification display rounding (dashboard `100%` vs computed ~98.x).

## Exit criteria

Census numbers recorded here; intersection start identified; vendor-max path chosen. Phases 1–4 stay blocked until then.

## Results (2026-09-08, live `daisy.db`)

Cache is already ~2y deep for 13/14 holdings (2024-08-12 → 2026-09-07,
~518 rows each); SELECTIPO genuinely starts 2025-03-10 (372 rows);
^NSEI spans 3y (2023-09-04, 742 rows). Tails to 09-04 on some tickers =
weekend staleness (Fri→Tue), covered by the 3-day refresh rule.

Newest holding = REDINGTON.NS @ 2026-08-04 → intersection ≈ 25 trading
days to 09-08. CONFIRMED: the "24–25 trading days" warnings are the
masked intersection window, not feed depth — the feed-blame copy is wrong
for 13/14 tickers. NIFTYIETF (450 rows since 2024-08-12) is thin/gappy,
not 10-days-new; per-ticker raw-vs-masked reporting (Phase 2) will show it.

Consequence for Phase 1: depth largely exists; work becomes guarantee +
backfill-on-miss + slice-serving + coverage API (not a from-zero backfill).
