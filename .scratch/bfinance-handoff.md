# 🚀 Master Handoff Instructions for Next LLM Session: Integrating `bfinance` into `finengine`

> **Status**: Ready for Immediate Execution  
> **Target Repository**: `c:\sukanta\coding\finengine` (Daisy Risk Engine)  
> **Upstream Library**: `bfinance` v0.1.0 (Live on PyPI: `pip install bfinance` | GitHub: `https://github.com/esconer/bfinance`)  
> **Test Baseline**: 250/250 backend tests passing (83.45% coverage), 60/60 frontend tests passing.

---

## 1. Executive Context & What Was Built

In the previous session, we built, tested (55/55 tests passing), legally shielded, documented, and published **`bfinance` v0.1.0** live on PyPI and GitHub as an independent, high-performance Python SDK designed for Indian Equities (NSE & BSE).

### What `bfinance` Delivers:
1. **1:1 `yfinance 1.7.0+` API Parity**: `fast_info`, `info` (180+ keys), `history()`, `valuation_measures`, `options`, `Tickers`, `Sector`, `Industry`, `download()`.
2. **10–13 Years Audited Ind AS Statements**: Full 10+ years annual P&L, Balance Sheet, Cash Flow, and 12–16 historical quarters (replacing Yahoo Finance's 4-year limit).
3. **Dual Institutional Shareholding**: 12Q quarterly + 11Y annual trends (% Promoter, FII, DII, Government, Public).
4. **40+ Conference Calls with Direct Audio MP3s**: Direct BSE PDF transcripts, PPT investor presentations, and streamable audio MP3 links.
5. **Custom Forensic Ratios & Scoring**: Piotroski 9-Point F-Score (0-9), Benjamin Graham Number ($\sqrt{22.5 \times \text{EPS} \times \text{BV}}$), Enterprise Value in ₹ Cr, EV/EBITDA, Interest Coverage, and CFO/PAT Quality of Earnings ratio.
6. **Institutional Screeners Registry (`bf.screens`)**: Pre-built Coffee Can Screen, Magic Formula, Debt-Free Compounders, High Dividend Yield, and Undervalued Growth.
7. **Native AI / LLM Context Engine (`bfinance.ai`)**: Token-dense Markdown/JSON financial dossiers and ready-to-run initiation coverage memos.
8. **1-Click 8-Tab Excel Financial Model Generator**: `stock.to_excel("model.xlsx")`.
9. **Anti-Blocking SQLite Cache**: Persistent local cache (`~/.cache/bfinance/cache.db`) with 24h TTL, 150ms request pacing with Gaussian jitter, and rotating User-Agents (serving 99% of queries in `<1ms`).

---

## 2. Architectural Mandate: 3-Tier Smart Fallback Cascade

To guarantee **100% data reliability, zero latency overhead, and global asset support**, the user has chosen the **Smart Hierarchical Fallback Cascade**:

```
                         Incoming Request for Asset
                                     │
                                     ▼
                      1. bfinance Engine (Primary)
                      • Instant <1ms SQLite cache
                      • 10-Year Audited Statements & Concalls
                      • Custom Piotroski & Graham Ratios
                                     │
                     ┌───────────────┴───────────────┐
                     ▼ (Success - 99% of time)       ▼ (If error / US stock)
              Return Response                2. yfinance Engine (Fallback)
                                             • Standard Yahoo OHLCV
                                             • Global Asset Coverage
                                                     │
                                                     ▼ (If 401 Crumb / 429)
                                             3. Alpha Vantage Pool
                                             • Rotating Multi-Key Backup Pool
```

---

## 3. Step-by-Step Execution Plan for Next LLM Session

### Phase 1: Backend Dependencies & Core Data Layer
1. **Update `backend/pyproject.toml`**:
   - Add `bfinance>=0.1.0` and `openpyxl>=3.1.0`.
   - Run `uv sync` in `backend/`.
2. **Upgrade `backend/app/services/data_service.py`**:
   - Integrate `bfinance.Ticker` as primary fetcher in `DataService._fetch_yfinance_with_retry()`, falling back to `yfinance` on errors.
   - Preserve existing SQLite timeseries caching and normalization logic.
3. **Upgrade `backend/app/services/company_data_service.py`**:
   - Replace 4-year yfinance statements with 10–13 years audited statements and 12–16 quarters from `bfinance.Ticker`.
   - Add 4-level sector hierarchy (`sector`, `industry_group`, `industry`, `sub_industry`, `indices`).

---

### Phase 2: New Backend Services & REST APIs
1. **Create `backend/app/services/equity_research_service.py`**:
   - Methods: `get_full_profile(ticker)`, `get_shareholding(ticker)`, `get_concalls(ticker)`, `get_custom_ratios(ticker)`, `export_excel_model(ticker)`.
2. **Create `backend/app/services/screener_service.py`**:
   - Methods: `run_screen(strategy: str, max_stocks: int)`, `run_custom_screen(filter_criteria)`.
3. **Create `backend/app/services/ai_dossier_service.py`**:
   - Methods: `get_ai_dossier(ticker, format)`, `get_investment_memo_prompt(ticker)`, `get_forensic_audit_prompt(ticker)`.
4. **Update `backend/app/api/data.py` & `backend/app/models/schemas.py`**:
   - Expose endpoints:
     - `GET /api/v1/company/{ticker}/full-profile`
     - `GET /api/v1/company/{ticker}/shareholding`
     - `GET /api/v1/company/{ticker}/concalls`
     - `GET /api/v1/company/{ticker}/custom-ratios`
     - `GET /api/v1/company/{ticker}/export-excel` (Streaming `.xlsx` file response)
     - `GET /api/v1/company/{ticker}/ai-memo-prompt`
     - `GET /api/v1/screens/{strategy}`

---

### Phase 3: Frontend Next.js 16 Terminal UI Layer
1. **Create `/dashboard/equity-research` (`frontend/src/app/dashboard/equity-research/page.tsx`)**:
   - Symbol Search Bar with autocomplete.
   - **Header Card**: Live CMP, Market Cap in ₹ Cr, 52W High/Low, 4-Level Sector Hierarchy, Index Badges.
   - **Forensic Card Matrix**: Piotroski 9-Point Score badge, Graham Number with % upside, EV/EBITDA, Interest Coverage, CFO/PAT ratio.
   - **Tabbed Financial Model**:
     - *Tab 1: Income Statement & Quarters* (10-13 years annual + 12-16 quarters).
     - *Tab 2: Balance Sheet & Cash Flow* (10-13 years).
     - *Tab 3: Institutional Shareholding* (Stacked Recharts of FII/DII/Promoter trends).
     - *Tab 4: Earnings Concalls & Audio Player* (40+ concalls with embedded HTML5 audio MP3 player and PDF transcript links).
     - *Tab 5: Peer Matrix* (Live peer group comparison table).
   - **Action Buttons**: 📥 "Export 8-Tab Excel Model" and 🤖 "Copy AI Memo Prompt".
2. **Create `/dashboard/screener-studio` (`frontend/src/app/dashboard/screener-studio/page.tsx`)**:
   - Pre-built strategy selector (Coffee Can, Magic Formula, Debt-Free Compounders, High Yield).
   - Interactive TanStack Table of filtered stocks with 1-click **"Add to Portfolio"** action.
3. **Update Navigation (`frontend/src/components/layout/Sidebar.tsx`)**:
   - Add **"Equity Research"** and **"Screener Studio"** with Lucide icons.

---

### Phase 4: Verification & Quality Gates
1. Run backend pytest suite:
   ```bash
   uv run pytest
   ```
   *Gate: All 250+ backend tests must pass with 84%+ coverage.*
2. Run frontend Vitest suite:
   ```bash
   bun run test:run
   ```
   *Gate: All 60+ frontend tests passing with 0 TypeScript errors.*

---

## 4. Key Developer Invariants (Must Follow)
* **Zero Breaking Changes to Existing Risk Analytics**: Euler Risk Contribution, HMM Regimes, Monte Carlo, and HRP Optimizer must continue working without regression.
* **TanStack Table Accessors**: Table renderers must always read row data through `const data = row.original || row;` to prevent unrendered/NaN values.
* **Indian Equities Localization**: Format currency in Indian Rupee notation (`₹`, `Cr`, `L`) using `en-IN` localization.
