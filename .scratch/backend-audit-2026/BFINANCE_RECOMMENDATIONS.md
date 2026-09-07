# bfinance Recommendations Log (upstream, log-only)
**Date:** 2026-09-03 | **Policy:** finengine never edits `backend/.venv/.../bfinance/`; all items below are worked around + quarantined in finengine and queued here for the bfinance repo. bfinance is a yfinance drop-in for the Indian market — every fix must preserve that parity.
**Discovered during:** Sprint 1 P0 fixes (one PR per P0, all pushed, integration verified 328 passed / 2 pre-existing failures).

## B-01 Piotroski F-score proxies are wrong (F5/F6/F8)
**File:** `bfinance/market/ratios.py` (`CustomRatiosCalculator.calculate_piotroski_score`)
- F5 uses absolute `Borrowings_curr <= Borrowings_prev`; paper uses Δ(LongTermDebt/AvgAssets) < 0 with strict decrease. Growing balance sheets mis-scored.
- F6 uses `OtherAssets/OtherLiab` as current ratio; should be CurrentAssets/CurrentLiabilities.
- F8 uses `(Sales-Expenses)/Sales` (total incl. interest/tax) instead of GrossProfit/Sales.
- `>=` awards flat periods; paper requires strict improvement on most criteria.
- `empty/len<2 → score 0` indistinguishable from genuine worst; return `None` + `insufficient_data`.
- Service drops the computed `piotroski_breakdown` — expose it.
**Finengine workaround:** none in Sprint 1 (scores pass through); do not gate any filter on Piotroski ≥ 7 until fixed. **Recommend:** fix proxies, strict comparisons, breakdown in payload.

## B-02 EV omits cash (overstates EV/EBITDA)
**File:** `bfinance/market/ratios.py` (`calculate_all_custom_ratios`, ~line 191: `ev = mcap + latest_debt`)
- Docstring/`ticker.py` claim "Market Cap + Debt − Cash" but code omits cash; ignores minority interest and Ind AS 116 leases.
- Same `Operating Profit` reused as both EBITDA and EBIT (interest coverage) — cannot be both; no D&A add-back.
**Finengine workaround:** none in Sprint 1; treat EV/EBITDA as overstated. **Recommend:** subtract cash & equivalents, add D&A add-back path, disclose proxy.

## B-03 Synthesized fields must go (never synthesize)
- `forwardPE = stock_pe * 0.85`, `returnOnAssets = 0.08`, `regularMarketOpen/DayHigh/DayLow/PreviousClose = cmp * markup`, `firstTradeDate = 1112328000`, `analyst_price_targets` markups, `DerivativesEngine` random OI/volume/IV/prices.
**Finengine workaround (done):** never surface these; valuation labeled trailing-only. **Recommend:** delete or gate behind explicit `synthetic: true` flag; derivatives engine must not exist until real NSE chain lands (G3).

## B-04 Unit + key contract (the 100× fork)
- `TopRatios` % vs `info` decimals (`dividendYield`, `returnOnEquity` decimal vs `returnOnCapitalEmployed` percent); `cfo_to_pat` vs `cfo_to_pat_ratio` key miss (CFO/PAT always None in finengine).
**Finengine workaround (done where touched):** `is not None` checks, alias-tolerant reads. **Recommend:** lock one convention (document units per field), fix key spelling, add contract test on `custom_ratios` keys/units per release.

## B-05 Screener definitions + semantics
- `debt_free_compounders` never checks debt (finengine now post-filters D/E ≤ 0.2 fail-closed; proper fix belongs here + NetDebt/EBITDA).
- `max_stocks` slices universe pre-filter (`symbols[:max_stocks]`); finengine passes `None` and caps results — consider making result-cap the native semantic.
- Magic Formula uses P/E + Screener ROCE thresholds, not Greenblatt EBIT/EV + ROC ranks; Undervalued Growth has no growth input; Coffee Can drops persistence.
- `Screen.run` swallows per-ticker exceptions (coverage understated); sorts by mcap not factor rank; forces no suffix itself (good) — finengine maps numeric→`.BO`.
- `resolve_company_id` first-hit fallback misfires typos (finengine needs ISIN/symbol confirmation; see G16).
**Recommend:** real debt filter, rank-based Magic Formula, growth inputs, `scanned` vs `matched` counts, log-and-count skips.

## B-06 Resolver + symbol normalization parity
- `normalize_symbol` strips `-EQ/-BE` series suffixes; finengine `canonical_ticker` does not — align or document the split.
- Numeric → BSE mapping exists; keep `.BO` intact end-to-end (finengine P0-7/P0-9 now preserve it).
**Recommend:** shared test vectors (`3MINDIA.NS`, `MOTHERSON.NS`, `BAJAJ-AUTO.NS`, `500112.BO`, `M&M`, `^NSEI`, `USDINR=X`).

## B-07 Version discipline
- finengine pins `bfinance>=0.1.0` today; will pin exact `==x.y.z` once these land, with contract tests on keys/units.
**Recommend:** changelog per release; never rename `custom_ratios` keys without major bump.

*End of log. Finengine-side status: all P0 workarounds in place; no bfinance source touched.*
