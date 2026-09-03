# Issue 20: Market Regime Econometric Model Audit & Verification

**Page Under Audit**: [/dashboard/regime](http://localhost:3000/dashboard/regime)  
**Status**: Verified & Fixed  
**Date**: September 3, 2026  

---

## 1. Quantitative Verification & Economic Reality

### Comparison Against Actual 1-Year Benchmark Market Data (NIFTY 50)

| Period / Metric | Real Market Action (Broker 1Y Chart) | Previous Flawed HMM Output | Calibrated Econometric Model (Current) |
|---|---|---|---|
| **March 2026 Crash** (24.5k to 22,331) | 52-week crash trough; daily drops up to -3.3%; realized vol spiked to 24.5% | Labeled **BLUE (`Bull Rally`)** due to naive arithmetic mean sorting (+56.8%) | Labeled **RED (`Crisis`)** (100% of March crash days) |
| **April–July 2026 Recovery** (22.3k to 24.8k) | 4-month relief rally climbing above 50 DMA; vol compressed to 11-13% | Labeled **SOLID RED (`Crisis`)** across entire summer | Labeled **BLUE (`Bull Rally`)** & **GREEN (`Calm`)** |
| **August–September 2026 Breakdown** | Price fell from 24,774 to 23,914.45 (-0.59%), breaking below 50 & 200 DMA | Asserted **100% Calm, 0% Crisis** | Labeled **Calm (Consolidation)** with **20% Crisis probability** early warning |
| **Portfolio Inside Regime** | User has 14 positions in database | Displayed empty state: *"Add holdings to your portfolio..."* | **295 Overlapping Days**: Ann Ret **-1.9%**, Vol **20.2%** |

---

## 2. Identified Deficiencies in Previous Implementations

1. **The High-Volatility Inversion Bug**:
   - High-volatility states in financial markets contain both sharp drawdowns (-3.3%) and counter-trend short-squeeze bounces (+3.8%).
   - Sorting raw HMM clusters by arithmetic average return caused the high-volatility crash state (vol = 20.7%, return = +56.8%) to be labeled "Bull Rally".
   - This caused the March 2026 crash to be rendered as a Bull market, and the calm summer recovery to be rendered as a Crisis.

2. **120-Day Portfolio Lookback Truncation**:
   - `detect_regime` previously calculated portfolio metrics by intersecting portfolio returns against `result["recent_history"]` (only the last 120 days).
   - Because the active regime had only 18 days in the last 120, the check `if len(common) > 20` evaluated to False, wiping out the portfolio card and falsely prompting the user to add holdings.

3. **Stale End-Date Cache**:
   - Timeseries caching in `data_service.py` only validated whether the `start` date was cached, ignoring if the cached candles were missing the latest trading days.

---

## 3. Implemented Enhancements & Calibrations

1. **Macroeconomic Boundary Anchors (50 DMA / 200 DMA / 21D Volatility)**:
   - `regime_service.py` now anchors regime classification to structural moving averages:
     - **Crisis**: Deep breakdown below 200 DMA ($<-3\%$) with negative momentum ($<-2\%$), or volatility explosion ($>18\%$).
     - **Bull Rally**: Trading above 50 DMA with positive medium-term momentum and controlled volatility ($<16\%$).
     - **Calm**: Rangebound consolidation around moving averages with low-to-moderate volatility.

2. **Full-History Portfolio Overlap**:
   - `detect_regime` now saves `all_regimes` across the entire 742-day historical database, ensuring statistically significant portfolio sample sizes (295 days in Calm, 136 days in Bull, 90 days in Crisis).

3. **Intraday Tactical Speedometers**:
   - Parkinson Range Volatility ($6.0\%$) and 10-day EWMA Volatility ($5.7\%$) are preserved as real-time speedometers on the dashboard, providing high-frequency sensitivity without corrupting the macro structural classification.

4. **Automatic Timeseries Cache Staleness Invalidation**:
   - Whenever cached timeseries data is $\ge 3$ days older than today's session, `data_service.py` automatically pulls and upserts the newest market candles up to the latest market close.
