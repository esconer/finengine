# India Market Microstructure & Data Pipelines Survey Report

**Author**: Explorer 2 (India Market Microstructure & Data Pipelines Survey)  
**Date**: 2026-08-26  
**Status**: Complete (Hard Handoff)  
**Scope**: Ingestion architecture, NSE data pipelines (bhavcopy, delivery %, FII/DII flows, bulk/block deals, promoter shareholding/pledge deltas), raw file caching (`data/nse/`), SQLite database models/schema, liquidity analytics (ADV, days-to-liquidate @ 10%/20%, Amihud illiquidity metric), and risk limits.

---

## 1. Observation

### 1.1 Existing Data Services & Codebase Status
Direct inspection of `backend/app/services/` and `backend/app/api/` revealed:
- `backend/app/services/india_data_service.py` does **NOT** exist.
- `data/nse/` directory does **NOT** exist.
- Existing services:
  - `data_service.py`: yfinance OHLCV fetcher with ticker suffix normalization (`.NS` / `.BO`), retry loop, Alpha Vantage fallback, and SQLite persistence in `stock_timeseries`.
  - `alpha_vantage_service.py`: Multi-key rotation pool with daily rate-budget tracking for daily OHLCV and global quotes.
  - `benchmark_service.py`: Pulls and caches `^NSEI` (NIFTY 50) returns via `data_service.py`.
  - `company_data_service.py`: Fundamentals snapshot, financial statements (balance sheet, cash flow, income statement), and insider transactions via yfinance.
  - `indicators_service.py`: stockstats calculation of 13 technical indicators on cached OHLCV data.
  - `optimization_service.py`: HRP, Min Vol, Max Sharpe, Min CVaR via `cvxpy` and `scipy`.
  - `regime_service.py`: 3-state Gaussian HMM on NIFTY returns and 21d realized vol.
  - `monte_carlo_service.py`: Politis-Romano Stationary Bootstrap and Student-t 10k goal simulations.
  - `currency_service.py`: USD/INR live conversion and Indian number system formatting (Crores / Lakhs).
  - `cache_service.py`: Manages `analytics_cache` and `fetch_logs` tables in SQLite.

### 1.2 Current Liquidity Implementation Deficiencies
In `backend/app/services/analytics_engine.py` (lines 248–340 and 1063–1086):
```python
# Lines 276-285 in analytics_engine.py:
if volume > 1e6 and price > 10:
    score = min(10, 8 + (volume / 1e6) * 0.2)
    category = "High"
elif volume > 100000:
    score = min(8, 6 + (volume / 1e6) * 0.3)
    category = "Medium"
else:
    score = max(1, (volume / 10000) * 0.5)
    category = "Low"

# Lines 1063-1070 in analytics_engine.py:
def _calculate_liquidation_days(self, score: float) -> str:
    if score >= 8:
        return "1-2"
    elif score >= 6:
        return "2-5"
    else:
        return "5-10"
```
Observations:
- The calculation is an ungrounded volume-bin heuristic.
- Position size (`quantity`, `market_value`) is completely ignored.
- There is no calculation of Average Daily Volume (ADV) or Average Daily Turnover (ADTV) in INR.
- There is no participation-based days-to-liquidate (e.g. @ 10% or 20% ADV).
- There is no Amihud (2002) illiquidity metric.
- There are no position capacity / sanity limits.

### 1.3 Database Setup & Schema State
In `backend/app/models/database.py`:
- Existing tables: `portfolio_positions`, `stock_timeseries`, `analytics_cache`, `fetch_logs`.
- Database initialization: `app/db/database.py` runs `Base.metadata.create_all` dynamically on application startup during `init_db()`.
- No Alembic migrations directory exists; adding SQLAlchemy declarative models to `app/models/database.py` automatically generates the tables in both `backend/data/daisy.db` and pytest `test.db`.

### 1.4 Mock Data in Frontend
In `frontend/src/components/portfolio/PortfolioCharts.tsx` (lines 66–79):
- Hardcoded array `const performanceData = [{ date: '2024-01', value: 100000 }, ...]` is present instead of binding to the live `usePerformanceData` hook.
- `MetricCard` deltas and `usePerformanceData` are partially wired, but some pages retain static fallback values.

---

## 2. Logic Chain & Architecture Synthesis

### 2.1 Daily NSE Ingestion Pipeline (`india_data_service.py`)

To deliver institutional-grade Indian market microstructure without third-party API dependencies, the system should fetch directly from official NSE archives and APIs using a dedicated browser-like HTTP client with session warmup and local filesystem caching.

#### A. Data Streams & Endpoints
1. **Daily Bhavcopy & Security-Wise Delivery Positions**:
   - **Source URL**: `https://archives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv`
   - **Key Columns**: `SYMBOL`, `SERIES` (filter for `'EQ'`), `DATE1`, `PREV_CLOSE`, `OPEN_PRICE`, `HIGH_PRICE`, `LOW_PRICE`, `CLOSE_PRICE`, `AVG_PRICE`, `TTL_TRD_QNTY`, `TURNOVER_LACS`, `DELIV_QTY`, `DELIV_PER`.
   - **Analytical Processing**:
     - Extract daily traded volume and delivery percentage for all NSE symbols.
     - Compute rolling 20-day delivery % moving average ($\mu_{20}$) and standard deviation ($\sigma_{20}$).
     - Flag delivery anomalies where $z = \frac{\text{deliv\_per} - \mu_{20}}{\sigma_{20}} \ge 2.0$, indicating smart-money accumulation.
2. **FII / DII Net Institutional Flows**:
   - **Source URL**: `https://www.nseindia.com/api/fiidiiTradeReact` or daily archives `https://archives.nseindia.com/content/equities/fii_dii_daily_DDMMYYYY.csv`
   - **Key Fields**: `category` (`FII/FPI`, `DII`), `date`, `buyValue` (₹ Crores), `sellValue` (₹ Crores), `netValue` (₹ Crores).
   - **Analytical Processing**:
     - Maintain daily historical series of institutional buy/sell/net in cash equities.
     - Compute 30-day cumulative net flow and institutional momentum indicator.
3. **Bulk and Block Deals**:
   - **Source URL**: `https://archives.nseindia.com/content/equities/bulk.csv` and `https://archives.nseindia.com/content/equities/block.csv`
   - **Key Fields**: `date`, `symbol`, `client_name`, `buy_sell`, `quantity`, `trade_price`, `remarks`.
   - **Analytical Processing**:
     - Filter deals against portfolio positions and watchlist symbols.
     - Flag institutional entries (e.g., marquee funds) or promoter exits.
4. **Quarterly Promoter Shareholding & Pledge Deltas**:
   - **Source URL**: `https://www.nseindia.com/api/corporate-share-holdings-equities?symbol={symbol}`
   - **Key Fields**: `symbol`, `period_ended`, `promoter_pct`, `promoter_pledged_pct` (shares pledged as % of promoter holding), `fii_pct`, `dii_pct`, `public_pct`.
   - **Analytical Processing**:
     - Detect quarter-over-quarter pledge increases.
     - Issue high-risk warnings if promoter pledge > 20% or if pledge increased by > 5% in the latest quarter.

#### B. Anti-Blocking, Session Warmup & Storage Strategy
- **Warmup Protocol**: NSE blocks standard Python requests. `httpx.AsyncClient` must first execute a GET to `https://www.nseindia.com/` with browser headers (`User-Agent`, `Referer`, `Accept-Language`, `Accept-Encoding`) to capture session cookies (`nsit`, `nseappid`).
- **Disk Cache Hierarchy**: Save raw downloads to `data/nse/YYYY-MM-DD/` (e.g. `data/nse/2026-08-26/sec_bhavdata_full.csv`).
- **Idempotency**: Before initiating any network fetch, verify if local raw file exists for `date`. If present, parse from disk directly.
- **Execution Lifecycle**: Ingestion runs via CLI (`scripts/fetch_nse_data.py`) or scheduled background task after market close (~18:30 IST), never blocking interactive API request handlers.

---

### 2.2 Microstructure Database Models (SQLAlchemy / SQLite)

Four new models should be defined in `backend/app/models/database.py`:

```python
class NSEBhavcopy(Base):
    """Daily NSE equity bhavcopy with delivery metrics"""
    __tablename__ = "nse_bhavcopy"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(DateTime, nullable=False, index=True)
    series = Column(String(10), default="EQ")
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    prev_close = Column(Float, nullable=False)
    avg_price = Column(Float, nullable=False)
    ttl_trd_qnty = Column(Integer, nullable=False)
    turnover_lacs = Column(Float, nullable=False)
    no_of_trades = Column(Integer, nullable=False)
    deliv_qty = Column(Integer, nullable=True)
    deliv_per = Column(Float, nullable=True)
    
    __table_args__ = (
        Index("ix_bhav_symbol_date", "symbol", "date"),
    )


class NSEInstitutionalFlow(Base):
    """Daily FII / DII equity cash market flows"""
    __tablename__ = "nse_institutional_flows"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, nullable=False, index=True)
    category = Column(String(20), nullable=False)  # "FII" or "DII"
    buy_value_crores = Column(Float, nullable=False)
    sell_value_crores = Column(Float, nullable=False)
    net_value_crores = Column(Float, nullable=False)
    
    __table_args__ = (
        Index("ix_flow_date_cat", "date", "category"),
    )


class NSEBulkBlockDeal(Base):
    """NSE bulk and block deal transactions"""
    __tablename__ = "nse_bulk_block_deals"
    
    id = Column(Integer, primary_key=True, index=True)
    deal_type = Column(String(10), nullable=False)  # "BULK" or "BLOCK"
    date = Column(DateTime, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    client_name = Column(String(200), nullable=False)
    buy_sell = Column(String(10), nullable=False)  # "BUY" or "SELL"
    quantity = Column(Integer, nullable=False)
    trade_price = Column(Float, nullable=False)
    remarks = Column(String(200), nullable=True)
    
    __table_args__ = (
        Index("ix_deal_symbol_date", "symbol", "date"),
    )


class NSEShareholdingPattern(Base):
    """Quarterly shareholding patterns and promoter pledge deltas"""
    __tablename__ = "nse_shareholding_patterns"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    period_ended = Column(String(20), nullable=False)  # e.g., "2024-12-31"
    promoter_pct = Column(Float, nullable=False)
    promoter_pledged_pct = Column(Float, default=0.0)
    fii_pct = Column(Float, default=0.0)
    dii_pct = Column(Float, default=0.0)
    public_pct = Column(Float, default=0.0)
    updated_on = Column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        Index("ix_shp_symbol_period", "symbol", "period_ended"),
    )
```

---

### 2.3 Mathematical Specification: Liquidity Limits & Sizing Engine

Replace heuristic logic in `analytics_engine.py` with participation-based microstructure calculations:

1. **Average Daily Volume (ADV) & Average Daily Turnover (ADTV)**:
   - Window: 20 trading days (standard institutional liquidation horizon).
   $$\text{ADV}_{20d} = \frac{1}{N} \sum_{t=1}^N \text{Volume}_t$$
   $$\text{ADTV}_{20d} = \frac{1}{N} \sum_{t=1}^N (\text{Close}_t \times \text{Volume}_t)$$

2. **Days-to-Liquidate (DTL) @ Participation Rate $k \in \{10\%, 20\%\}$**:
   - For a holding with quantity $Q_i$ shares and market value $V_i = Q_i \times P_i$:
   $$\text{DTL}_{i, 10\%} = \frac{Q_i}{0.10 \times \text{ADV}_{i, 20d}} = \frac{V_i}{0.10 \times \text{ADTV}_{i, 20d}}$$
   $$\text{DTL}_{i, 20\%} = \frac{Q_i}{0.20 \times \text{ADV}_{i, 20d}} = \frac{V_i}{0.20 \times \text{ADTV}_{i, 20d}}$$
   - **Portfolio-Weighted Days-to-Liquidate**:
   $$\text{DTL}_{\text{portfolio}, 20\%} = \sum_{i=1}^M w_i \times \text{DTL}_{i, 20\%}$$
   - **Guards**: If $\text{ADV} \le 0$ or volume missing, return a safe ceiling ($999.0$ days) with an `illiquid_flag: true`. If $Q_i = 0$, return $0.0$.

3. **Amihud (2002) Illiquidity Metric**:
   - Measures price impact per unit of rupee volume over $D$ days:
   $$\text{ILLIQ}_i = \frac{1}{D} \sum_{t=1}^D \frac{|R_{i,t}|}{\text{Close}_{i,t} \times \text{Volume}_{i,t}}$$
   - Scaled for presentation ($\times 10^6$) and log-normalized for cross-sectional ranking. Higher values signify steeper price impact / lower depth.

4. **Max Sane Position Size & Sizing Constraints**:
   - Constraint rule: Max position size allowed such that liquidation takes $\le 5$ days at $20\%$ ADV participation:
   $$\text{Max Sane Shares}_i = 5 \times (0.20 \times \text{ADV}_{i, 20d}) = 1.0 \times \text{ADV}_{i, 20d}$$
   $$\text{Max Sane Value}_i = \text{Max Sane Shares}_i \times P_i = \text{ADTV}_{i, 20d}$$
   - **Capacity Utilization**:
   $$\text{Capacity Utilization}_i = \left( \frac{V_i}{\text{Max Sane Value}_i} \right) \times 100\%$$
   - **Risk Classification**:
     - *Low Risk*: $\text{DTL}_{20\%} \le 1.0$ day and $\text{Capacity Utilization} \le 50\%$.
     - *Medium Risk*: $1.0 < \text{DTL}_{20\%} \le 3.0$ days.
     - *High Risk*: $\text{DTL}_{20\%} > 3.0$ days or $\text{Capacity Utilization} > 100\%$ (oversized illiquid smallcap).

---

### 2.4 API Surface & Endpoint Mapping

| Method | Endpoint | Description | Query / Body Params | Response DTO |
|---|---|---|---|---|
| `GET` | `/api/v1/analytics/liquidity` | Full portfolio & per-position ADV, DTL @ 10%/20%, Amihud scores, max sane size, capacity utilization | None (reads DB positions) | `LiquidityMetricsResponse` |
| `GET` | `/api/v1/india/flows/fii-dii` | Daily FII/DII net flows history (last 30–90d), cumulative flows, net trend | `days: int = 30` | `FIIDIISummaryResponse` |
| `GET` | `/api/v1/india/delivery-anomalies` | Delivery % anomalies (>2σ) for held tickers and watchlist | `tickers: Optional[str] = None` | `DeliveryAnomaliesResponse` |
| `GET` | `/api/v1/india/deals/bulk-block` | Recent bulk/block deals filtered by portfolio holdings | `days: int = 7` | `BulkDealsResponse` |
| `GET` | `/api/v1/india/shareholding` | Latest promoter holding, pledge % and quarterly deltas | `tickers: Optional[str] = None` | `ShareholdingResponse` |
| `POST` | `/api/v1/india/sync` | Trigger daily bhavcopy/flows batch sync (idempotent) | `date: Optional[str] = None` | `SyncStatusResponse` |

---

## 3. Caveats

1. **NSE Upstream Availability & Rate Limits**:
   - NSE archives are updated after market close (~18:30 IST on trading days).
   - NSE occasionally changes endpoint headers or IP-blocks cloud server ranges. The engine must fall back gracefully to existing cached SQLite data without throwing 500 errors on dashboard pages.
2. **Weekend & Trading Holiday Handling**:
   - On Saturdays, Sundays, and NSE trading holidays, the fetcher must recognize the non-trading day and retain the previous trading day's bhavcopy rather than logging false failure alerts.
3. **Historical Backfill Scope**:
   - Bhavcopy archive backfills can be bandwidth-heavy. Recommend seeding the last 60–90 trading days for delivery moving averages and FII/DII history, rather than multi-year historical archives.

---

## 4. Conclusion

1. **Implementation Blueprint**:
   - Create `backend/app/services/india_data_service.py` to handle session warmup, raw file persistence in `data/nse/`, CSV/JSON parsing, and SQLite upserts.
   - Add models `NSEBhavcopy`, `NSEInstitutionalFlow`, `NSEBulkBlockDeal`, `NSEShareholdingPattern` to `backend/app/models/database.py`.
   - Implement quantitative liquidity math (ADV, ADTV, DTL @ 10%/20%, Amihud ILLIQ, Max Sane Position Size) in `backend/app/services/analytics_engine.py`.
   - Expose endpoints via `backend/app/api/india.py` (registered in `backend/main.py`) and update `/api/v1/analytics/liquidity`.
   - Build frontend `/india-flows` dashboard page and update `/dashboard/liquidity` view to display real ADV and days-to-liquidate metrics.
   - Purge static mock arrays in `PortfolioCharts.tsx`.

---

## 5. Verification Method

To verify the architecture and implementation independently:

1. **Database Schema Verification**:
   ```bash
   uv run python -c "from app.db.database import init_db; import asyncio; asyncio.run(init_db())"
   ```
2. **Liquidity Calculation Unit Tests**:
   - Test that ₹5L position in ₹1Cr ADTV stock yields exactly `500,000 / (0.10 * 10,000,000) = 0.5` days @ 10% ADV and `0.25` days @ 20% ADV.
   - Test Amihud score calculation on zero-return days and non-zero volume without division by zero.
   - Run unit test suite:
   ```bash
   uv run pytest tests/test_analytics_engine.py -k "liquidity"
   ```
3. **Idempotent Ingestion Test**:
   - Run ingestion script twice on the same test date; verify second run reads from `data/nse/` without re-requesting upstream network.
4. **Frontend Verification**:
   ```bash
   bun x tsc --noEmit
   bun run test:run
   ```
