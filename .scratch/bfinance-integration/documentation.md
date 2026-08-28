# bfinance Integration — Architecture, API & Implementation Spec

## 1. Overview & Objective

`bfinance` (v0.1.0 on PyPI, https://github.com/esconer/bfinance) has been integrated into `finengine` to provide pro-grade, institutional Indian equity analytics without paid Bloomberg/Refinitiv terminals.

This integration upgrades `finengine` from a portfolio risk analyzer into a full **Bloomberg-grade Equity Research & Screener Terminal**, delivering:
- 10–13 years of audited Ind AS statements and 12–16 quarters
- 4-level industry taxonomy (Sector, Industry Group, Industry, Sub-Industry) + 50+ index memberships
- 12Q / 11Y dual institutional shareholding patterns (Promoters, FIIs, DIIs, Government, Public)
- 40+ earnings concall transcripts (BSE PDF) with direct streaming audio MP3 player
- Quantitative custom ratios: Piotroski 9-Point F-Score, Graham Number Fair Value, EV/EBITDA, Interest Coverage, and CFO/PAT
- 8-Tab Automated Financial Model Excel Exporter (`openpyxl`)
- 5 Institutional Screener strategies (Coffee Can, Magic Formula, Debt-Free Compounders, High Dividend Champions, Undervalued Growth) + Dynamic Multi-Parameter Screener Builder
- Next.js 16 Bloomberg-grade UI workspaces (`/dashboard/equity-research` and `/dashboard/screener-studio`)

---

## 2. 3-Tier Fallback Cascade

The market data ingestion engine in `DataService` (`backend/app/services/data_service.py`) follows a 3-tier cascade:

- **Tier 1 (Primary)**: `bfinance` — fast quotes, live Screener.in ratios, 10–13Y Ind AS statements, and concall MP3 links.
- **Tier 2 (Fallback)**: `yfinance` — automatic `.NS`/`.BO` ticker suffix routing for historical timeseries.
- **Tier 3 (Fallback)**: `Alpha Vantage` — rotating multi-key API client pool with budget rate-limit tracking.

---

## 3. Backend Services & REST APIs

### 3.1 Services Implemented

1. **`EquityResearchService` (`backend/app/services/equity_research_service.py`)**:
   - `get_full_profile(ticker)`: 360° profile with CMP, Market Cap, 52W high/low, ROCE/ROE, P/E, Book Value, CAGRs (Sales, Profit, Stock Price, ROE over 10Y/5Y/3Y/TTM), qualitative pros/cons, peer comparison, and annual report links.
   - `get_shareholding(ticker)`: Quarterly (12Q) and annual (11Y) institutional holdings trends.
   - `get_concalls(ticker)`: Transcripts, PPTs, and streamable MP3 audio URLs.
   - `get_custom_ratios(ticker)`: Piotroski F-Score (9-point checklist), Graham number, EV/EBITDA, Interest Coverage, CFO/PAT.
   - `export_excel_model(ticker)`: 8-tab stylized Excel model (`Overview`, `Income_Statement`, `Balance_Sheet`, `Cash_Flow`, `Quarterly_Results`, `Ratios_CAGR`, `Shareholding`, `Peers_Comparison`).

2. **`ScreenerService` (`backend/app/services/screener_service.py`)**:
   - `get_available_strategies()`: Metadata for all supported institutional screening models.
   - `run_screen(strategy, universe, max_stocks)`: Fast execution with 5-minute TTL caching and multi-threaded parallel universe evaluation.
   - `run_custom_screen(min_roce, min_roe, max_pe, min_mcap_cr, min_div_yield)`: Dynamic parameter evaluation.

3. **`AIDossierService` (`backend/app/services/ai_dossier_service.py`)**:
   - `get_ai_dossier(ticker)`: Token-dense structured JSON for LLM context injection.
   - `get_investment_memo_prompt(ticker)`: Institutional initiation coverage memo prompt.
   - `get_forensic_audit_prompt(ticker)`: Forensic accounting red-flag audit prompt.

### 3.2 REST API Endpoints (`/api/v1`)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/company/{ticker}/full-profile` | Complete 360° equity research profile |
| `GET` | `/api/v1/company/{ticker}/shareholding` | 12Q & 11Y dual shareholding tables & trends |
| `GET` | `/api/v1/company/{ticker}/concalls` | Earnings call transcripts and streamable MP3 URLs |
| `GET` | `/api/v1/company/{ticker}/custom-ratios` | Piotroski score, Graham value, EV/EBITDA |
| `GET` | `/api/v1/company/{ticker}/export-excel` | Formatted 8-tab `.xlsx` financial model download |
| `GET` | `/api/v1/company/{ticker}/ai-dossier` | LLM-ready financial dossier |
| `GET` | `/api/v1/company/{ticker}/ai-prompts` | Ready-to-use Initiation Memo and Forensic Prompts |
| `GET` | `/api/v1/screens` | List of supported institutional screener strategies |
| `GET` | `/api/v1/screens/{strategy}` | Run quantitative screener (`coffee_can`, `magic_formula`, `debt_free`, `high_dividend`, `undervalued_growth`) |
| `POST` | `/api/v1/screens/custom` | Execute custom multi-parameter screener query |

---

## 4. Frontend Terminal UI Layer

1. **Equity Research Terminal (`frontend/src/app/dashboard/equity-research/page.tsx`)**:
   - Ticker search bar with auto-capitalization and quick search chips.
   - 4-level taxonomy breadcrumb (*Sector > Industry Group > Industry > Sub-Industry*) and Index badges.
   - Pro Metric Badges: Piotroski Score (with 9-point criteria modal), Graham Fair Value, EV/EBITDA, and CFO/PAT.
   - 5 Workspaces:
     - *Overview & Analysis*: Key ratios grid, Compounded CAGRs, Pros/Cons, and Peer Comparison table.
     - *Shareholding (12Q / 11Y)*: Dual stacked area chart with category toggles and granular data tables.
     - *Concalls & Audio*: Concall timeline with embedded HTML5 `<audio>` player for MP3 streaming and BSE transcript links.
     - *10-Year Audited Statements*: Annual and Quarterly Ind AS financial statements.
     - *AI Dossier & Prompts*: Initiation Coverage and Forensic red-flag prompt copy cards.
   - 1-Click "8-Tab Excel Model" export button.

2. **Screener Studio (`frontend/src/app/dashboard/screener-studio/page.tsx`)**:
   - Institutional strategy selector cards (*Coffee Can*, *Magic Formula*, *Debt-Free Compounders*, *High Dividend*, *Undervalued Growth*).
   - Custom Screener Builder with range sliders for ROCE, ROE, P/E, Market Cap, and Dividend Yield.
   - TanStack Table with multi-column sorting, pagination, and `+ Add to Portfolio` quick action.

---

## 5. Verification & Test Proof

- **Backend Pytest**: **267 / 267 tests passed (0 failures)**, **81.90% code coverage** (`uv run pytest`).
- **Frontend Vitest**: **62 / 62 tests passed (0 failures)** across 8 test suites (`bun run test:run`).
- **Live Endpoint Verification**: Live REST endpoints tested against `RELIANCE.NS`, `TCS.NS`, and `BHARTIARTL.NS` with 200 OK responses and zero data errors.
