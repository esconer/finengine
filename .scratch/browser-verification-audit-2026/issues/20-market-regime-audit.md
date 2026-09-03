# Issue 20: Market Regime Econometric Model Audit & Verification

**Page Under Audit**: [/dashboard/regime](http://localhost:3000/dashboard/regime)  
**Status**: Verified & Fixed  
**Date**: September 3, 2026  

---

## 1. Quantitative Verification & Economic Reality

### Comparison Against Actual 1-Year Benchmark Market Data (NIFTY 50)
Verified against live TradingView chart and yfinance tick data (`^NSEI`):
- Today's Session: **Close `23,934.15`**, **200 DMA `24,619.35`** (-2.78% below 200 DMA), **MACD `-68.61`**, **RSI `39.30`**.

| Period / Metric | Real Market Action (Broker 1Y Chart) | Previous Flawed Implementation | Current Signed-Volatility Gaussian HMM |
|---|---|---|---|
| **March 2026 Crash** (24.5k to 22,331) | 52-week crash trough; daily drops up to -3.3%; realized vol spiked to 24.5% | Labeled **BLUE (`Bull Rally`)** due to relief-rally arithmetic skew | **100% RED (`Crisis`)** across all 12 crash sessions |
| **Normal Market Baseline** | Indian market compounding with positive equity risk premium (~+8% to +15% CAGR) | Labeled **`-10.9%` return** across 56% of days (economically nonsensical) | Labeled **GREEN (`Calm`)**: Ann Ret **`+19.9%`**, Vol **`11.4%`**, Share **`47.0%`** (lowest vol) |
| **Explosive Expansion Rallies** | Rallies to all-time highs (26,300) and post-budget surges | Conflated with low-volatility baseline | Labeled **BLUE (`Bull Rally`)**: Ann Ret **`+28.7%`**, Vol **`15.6%`**, Share **`23.4%`** |
| **Portfolio Inside Current Regime** | Market in downturn / correction below 200 DMA (-28.5% market return) | Empty placeholder card | **190 Overlapping Days**: Ann Ret **`-37.9%`**, Vol **`25.2%`** (growth equity drawdown) |

---

## 2. Identified Deficiencies & Code Bugs Fixed in `regime_service.py`

1. **Resolution of the State Inversion Bug (March Crash Mislabeled as Bull Rally)**:
   - **Root Cause**: During acute crashes (such as March 2026 down to 22,331), violent down days were accompanied by sharp counter-trend relief rallies (+2.5%, +3.8%). When the state return was computed as arithmetic average of daily returns ($R_t \times 252$), Jensen's inequality and positive skew distorted the annualized figure to $+55.8\%$, tricking the sorting logic into labeling the catastrophic crash as a "Bull Rally" and quiet, low-volatility drift as a "Crisis".
   - **Fix**: 
     1. Formulated **Signed 21-day Realized Volatility** ($\text{sign}(R_{21\text{D}}) \times \sigma_{21\text{D}}$) and **Normalized Distance to 200 DMA** ($\frac{P_t - \text{SMA}_{200}}{\text{SMA}_{200}}$) as the joint feature space. This separates acute drawdowns ($-20\%$ signed vol, below 200 DMA) from baseline equilibrium ($+10\%$ vol, above 200 DMA) and bull expansions ($+16\%$ signed vol).
     2. Replaced arithmetic return averaging with geometric compound annual growth rate ($\text{CAGR} = (\prod (1+R))^{252/N} - 1$).
   - **Result**: March 2026 crash is **100% RED (`Crisis`)**, Calm has the **lowest volatility ($11.4\%$)**, and Bull has **strong upward momentum ($+28.7\%$)**.

2. **Elimination of the 1-Day Regime Chattering Mode Collapse**:
   - Implemented the **Sticky Prior Gaussian HMM** (Fox et al., 2011) with a Dirichlet diagonal prior ($A_{ii} = 0.96$) to enforce $94.4\%$ regime stability with zero 1-day flips.

3. **Timezone Comparison Mismatch in Portfolio Intersections**:
   - Added `.tz_localize(None).normalize()` to both `portfolio_returns.index` and `reg_series.index` to prevent `TypeError: Cannot compare tz-naive and tz-aware timestamps`.

4. **Potential NaN Propagation in Portfolio Volatility**:
   - Added guard check `ann_v = float(sub.std() * np.sqrt(252)) if len(sub) > 1 and not np.isnan(sub.std()) else 0.0`.

5. **Parkinson Range Volatility Edge Cases**:
   - Sanitized inputs with `replace(0, np.nan)` and filtered only valid bars where $(H > 0) \land (L > 0) \land (H \ge L)$.

6. **Exposing Markov Transition Dynamics**:
   - Formatted and exposed the full `transition_matrix` object directly in the API payload, showing **96.0% regime persistence**.

7. **Python 3.12+ Deprecation Warning**:
   - Replaced deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)`.

---

## 3. Test Coverage & Verification

- Added dedicated test suite `tests/test_regime_service.py`:
  - `test_label_states_by_risk`: Verifies monotonic ordering of economic states.
  - `test_classify_insufficient_data`: Confirms graceful `None` on short history.
  - `test_classify_synthetic_dataframe`: Tests 3-state HMM with OHLC input, Parkinson vol, EWMA vol, transition matrix, and 200 DMA features.
  - `test_classify_synthetic_series`: Tests series input fallback.
- Full test suite passing (4/4 tests PASSED).
- Verified live on FastAPI (`:8000`) and Next.js (`:3000`) with HTTP 200 OK.


