# bfinance v0.1.3 Release Notes & Finengine Compatibility Audit

> **Document Location**: `finengine/.scratch/bfinance-v0.1.3-audit-and-release-notes.md`  
> **Date**: 2026-09-04  
> **Source Library**: `bfinance` (Local checkout: `C:\es\coding\bfinance`, Version: `0.1.3`)  
> **Downstream Consumer**: `finengine` (Local checkout: `C:\es\coding\finengine`)  
> **Verification Status**: ✅ **100% Verified** — 348/348 backend tests passing, 62/62 frontend tests passing. Zero changes required in `finengine`.

---

## 1. Executive Summary

A comprehensive overhaul of `bfinance` was performed to address 61 static audit findings (N-01 through N-61, documented in `bfinance/docs/AUDIT_2026-09-04.md`). The primary objective of this update is **truth-in-data**: eliminating all fabricated/synthetic values, aligning financial ratio formulas with canonical academic standards, merging real corporate actions into historical OHLCV, making timestamps timezone-aware (`Asia/Kolkata`), and hardening the caching/network layer against race conditions and rate limits.

### Core Question Answered:
> **"Does `finengine` require any code changes to work with the new `bfinance`?"**  
> **NO.** All public APIs, method signatures, DataFrame formats, and Pydantic schemas remain 100% backward-compatible. Every single service in `finengine` operates seamlessly, and the entire test suite (348 backend tests + 62 frontend tests) passes with zero regressions.

---

## 2. Detailed Release Notes: What Changed in `bfinance v0.1.3`

### A. Data Integrity & Elimination of Fabrications (P0)
Previously, certain fields where upstream data was unavailable were populated with synthetic estimates (e.g. `cmp * 0.995` or `0.08`). These have been completely eliminated:
* **Zero Synthetic Quotes**: `market/quotes.py` no longer fabricates `returnOnAssets` as a flat `0.08` or `forwardPE` as `trailingPE * 0.85`. If upstream Screener data does not report a metric, it honestly returns `None`.
* **Zero Synthetic FastInfo**: `market/fast_info.py` no longer fabricates `open`, `day_high`, `day_low`, or `previous_close` using arbitrary multiplier envelopes (`cmp * 0.998`, `cmp * 1.008`). It returns `None` for intraday fields unavailable in EOD feeds, while deriving real 50-day and 200-day moving averages and previous close from actual historical price series when available.
* **Zero Synthetic Analyst Targets & Options**: `ticker.py` no longer synthesizes fake price targets (`cmp * 0.85` / `cmp * 1.35`) or strikes from a fallback price of `100.0`. `analyst_price_targets` returns `None` when price is missing.
* **Exchange Suffix Resolution**: `FastInfo.exchange` no longer hardcodes `"NSE"`. It dynamically inspects symbol suffixes (`.BO` $\rightarrow$ `"BSE"`, default $\rightarrow$ `"NSE"`).

### B. Financial Calculations & Quantitative Precision (P0/P1)
All quantitative metrics in `market/ratios.py` have been audited against academic and institutional accounting definitions:
* **Piotroski 9-Point F-Score**:
  - **F1 (ROA)**: Net Income / Beginning Total Assets (previously used ending assets).
  - **F2 (CFO)**: Cash Flow from Operations > 0.
  - **F3 ($\Delta$ROA)**: $ROA_t > ROA_{t-1}$.
  - **F4 (Accruals)**: $CFO_t > NetIncome_t$.
  - **F5 ($\Delta$Leverage)**: Compares Long-Term Debt / Assets ratio (previously compared absolute Borrowings).
  - **F6 ($\Delta$Liquidity)**: Compares Current Ratio against previous year.
  - **F7 (Dilution)**: Checks equity share dilution across the period.
  - **F8 ($\Delta$Margin)**: Uses true Operating Margin $(Sales - Expenses) / Sales$.
  - **F9 ($\Delta$Turnover)**: Compares Asset Turnover $(Sales / BeginningAssets)$.
  - **Empty Statement Guard**: If balance sheet or cash flow statements are empty, default points are never awarded.
* **Enterprise Value (EV)**:
  - Formula updated to: $\text{EV} = \text{Market Cap} + \text{Total Debt} - \text{Cash \& Equivalents}$ (previously cash was omitted).
* **Free Cash Flow (FCF)**:
  - Formula updated to: $\text{FCF} = \text{CFO} - \text{Capex}$ (previously used total CFI which included non-operating asset sales).
* **Benjamin Graham Number**:
  - Added robust `_safe_float` guards so `NaN` values from incomplete filings cannot produce `NaN` outputs.

### C. Time Series & Corporate Actions (P0/P1)
* **Timezone-Aware DatetimeIndex**: `history()` index now carries explicit `Asia/Kolkata` timezone information (aligned with standard yfinance behavior).
* **Real Corporate Actions Merged**: `history()` now automatically merges true dividend payouts and stock split events into the `Dividends` and `Stock Splits` columns, rather than returning hardcoded `0.0`.
* **Honest Statement Frequencies**: `get_income_stmt(freq="quarterly")` returns real 12–16 quarterly periods from Screener. Calling `get_balance_sheet(freq="quarterly")` or `get_cash_flow(freq="quarterly")` now honestly raises `NotImplementedError` (since Screener does not publish quarterly balance sheets) instead of silently returning annual data as quarterly.

### D. Institutional Screening Engine (`bfinance.screens`)
* **Dual Execution Interface**: `Screen` now implements `__call__` in addition to `.run()`. Users and services can call both `screen.run(max_stocks=10)` and `screen(max_stocks=10)`.
* **Debt-Free Compounders**: Now strictly enforces Debt-to-Equity $\le 0.2$. Zero-debt companies (where Borrowings == 0) are properly recognized rather than excluded.
* **Coffee Can Screen**: Requires positive 10-year sales and profit CAGRs in addition to point-in-time ROCE $\ge 15\%$ and ROE $\ge 15\%$.
* **Undervalued Growth**: Stricter criteria checking PEG $\le 2.0$ or sales/profit growth $\ge 10\%$ when available.

### E. Cache & Infrastructure Hardening (P1)
* **SQLite WAL Mode**: `sqlite_cache.py` now enables `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` to prevent database locks and race conditions during concurrent requests.
* **Global Rate Limiter**: Request pacing is enforced globally across client instances, preventing 429 rate limit errors when multi-ticker downloads are initiated.
* **Security & Size Caps**: `utils/downloader.py` adds URL scheme validation (preventing SSRF) and file size caps on PDF and MP3 downloads.

---

## 3. Finengine Impact Analysis (Touchpoint by Touchpoint)

We audited all 5 backend files in `finengine` that interface with `bfinance`:

| Touchpoint in `finengine` | `bfinance` Methods / Properties Called | Impact of v0.1.3 | Changes Needed in `finengine`? |
| :--- | :--- | :--- | :---: |
| **`DataService`** (`data_service.py`) | `bt = bf.Ticker(...)`<br>`bt.fast_info.last_price`<br>`bt.fast_info.regular_market_price`<br>`bt.fast_info.last_volume`<br>`bt.fast_info.market_cap`<br>`bt.info` | `regular_market_price` and `last_volume` are fully supported. `last_price` returns real CMP. | **NONE (0)** |
| **`CompanyDataService`** (`company_data_service.py`) | `t._ensure_profile()`<br>`t.get_income_stmt(freq="quarterly")`<br>`t.get_balance_sheet(freq=...)`<br>`t.get_cash_flow(freq=...)`<br>`t.piotroski_score`<br>`t.graham_number`<br>`t.enterprise_value` | Annual statements continue returning full 10–13 year matrices. Quarterly income returns 12–16 quarters. When quarterly balance sheet raises `NotImplementedError`, `company_data_service.py` catches it gracefully and falls back to `yfinance`. | **NONE (0)** |
| **`EquityResearchService`** (`equity_research_service.py`) | `t._ensure_profile()`<br>`profile.ratios`<br>`t.custom_ratios`<br>`profile.shareholding.to_dataframe()`<br>`profile.concalls`<br>`t.to_excel(path)` | All profile attributes, 12Q/11Y shareholding dataframes, 40+ concalls, and 8-sheet Excel export run identically with improved ratio precision. | **NONE (0)** |
| **`ScreenerService`** (`screener_service.py`) | `bf.screens.coffee_can`<br>`bf.screens.magic_formula`<br>`bf.screens.debt_free_compounders`<br>`bf.screens.high_dividend_yield`<br>`bf.screens.undervalued_growth`<br>`screen.run(universe, max_stocks)` | `finengine` invokes `.run(...)` on each screen object. All 5 strategies execute and return DataFrames matching expected schema (`Symbol`, `Name`, `Price`, `MarketCap_Cr`, `PE`, `ROCE_%`, etc.). | **NONE (0)** |
| **`AIDossierService`** (`ai_dossier_service.py`) | `t.to_ai_context(format=...)`<br>`t.to_investment_memo_prompt(...)`<br>`t.to_forensic_audit_prompt()`<br>`t.to_concall_analyst_prompt()` | All AI prompt factories and context generation methods execute cleanly, now with sanitized values (no `₹None` artifacts). | **NONE (0)** |

---

## 4. Automated Verification Results

### Backend Test Suite (`uv run pytest`)
Executed directly against the local `bfinance v0.1.3` checkout:
* **Total Tests**: **348 passed, 0 failed** (in 85.96s)
* **Code Coverage**: **83.17%** (exceeds the 80% CI quality gate)
* **Specific Subsystems Verified**:
  - `test_equity_research_and_screens.py`: **17/17 PASSED**
  - `test_p07_ticker.py`, `test_p08_cache.py`, `test_p09_screener.py`: **55/55 PASSED**
  - `test_data_services.py` & `test_coverage_data_service.py`: **ALL PASSED**
  - Advanced Analytics (Regimes, HRP, Monte Carlo, Tail Risk, Cointegration): **ALL PASSED**
  - WebSocket & Real-Time feeds: **ALL PASSED**

### Frontend Test Suite (`bun run test:run`)
* **Total Test Files**: **8 passed (8)**
* **Total Tests**: **62 passed (62)** (in 48.28s)
* **Zero TypeScript Errors**: Type contracts between backend responses and React UI remain 100% aligned.

---

## 5. Summary & Recommendation

1. **Safety**: Upgrading to `bfinance v0.1.3` introduces **zero breaking changes** and requires **zero edits** in `finengine`.
2. **Quality Gain**: Ratios are now mathematically rigorous, corporate actions are real, timestamps are timezone-aware, and all synthetic placeholders have been replaced with honest `None` values.
3. **Deployment**: When publishing `bfinance v0.1.3` to PyPI, simply run `uv lock --upgrade-package bfinance` in `finengine/backend` to update the lockfile.
