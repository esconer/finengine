# Issue 20: Market Regime Econometric Model Audit & Verification

**Page Under Audit**: [/dashboard/regime](http://localhost:3000/dashboard/regime)  
**Status**: Verified & Fixed  
**Date**: September 3, 2026  

---

## 1. Quantitative Verification & Economic Reality

### Comparison Against Actual 1-Year Benchmark Market Data (NIFTY 50)
Verified against live TradingView chart and yfinance tick data (`^NSEI`):
- Today's Session: **Close `23,934.15`**, **200 DMA `24,619.35`** (-2.78% below 200 DMA), **MACD `-68.61`**, **RSI `39.30`**.

| Period / Metric | Real Market Action (Broker 1Y Chart) | Previous Flawed Implementation | Current Canonical Gaussian HMM |
|---|---|---|---|
| **March 2026 Crash** (24.5k to 22,331) | 52-week crash trough; daily drops up to -3.3%; realized vol spiked to 24.5% | Labeled **BLUE (`Bull Rally`)** due to naive raw return sorting | Correctly identified as **RED (`Crisis`)** with steady multi-week persistence |
| **Normal Market Baseline** | Indian market compounding with positive equity risk premium (~+8% CAGR) | Labeled **`-10.9%` return** across 56% of days (economically nonsensical) | Labeled **GREEN (`Calm`)**: Ann Ret **`+6.9%`**, Vol **`11.9%`**, Share **`38.5%`** |
| **Explosive Expansion Rallies** | Rallies to all-time highs (26,300) and post-budget surges | Conflated with low-volatility baseline | Labeled **BLUE (`Bull Rally`)**: Ann Ret **`+55.8%`**, Vol **`20.2%`**, Share **`17.2%`** |
| **Portfolio Inside Current Regime** | Market in downturn / correction below 200 DMA (-9.2% market return) | Empty placeholder card | **271 Overlapping Days**: Ann Ret **`+0.4%`**, Vol **`21.2%`** (capital successfully preserved) |

---

## 2. Identified Deficiencies & Code Bugs Fixed in `regime_service.py`

1. **Elimination of the 1-Day Regime Chattering Mode Collapse**:
   - In unconstrained maximum likelihood estimation, the Baum-Welch algorithm collapsed into an alternating local maximum where `Bull` and `Crisis` flipped every 24 hours with 0% diagonal persistence ($A_{00} = 0\%, A_{11} = 0\%, A_{01} = 100\%$).
   - **Fix**: Implemented the **Sticky Prior Gaussian HMM** (Fox et al., 2011) with a Dirichlet diagonal prior ($A_{ii} = 0.96$) over a 21-day macroeconomic holding period ($R_{21\text{D}}, \sigma_{21\text{D}}$).
   - **Result**: Regimes now possess an expected duration of **`18.5 to 31.0 trading days`** (~1 to 1.5 months), matching real-world macroeconomic cycles with zero 1-day chattering.

2. **Monotonic Economic State Ordering**:
   - Re-engineered `_label_states_by_risk(state_stats)` to order states strictly by annualized drift ($\mu_1 < \mu_2 < \mu_3$):
     - Lowest drift ($-9.2\%$) $\to$ **`Crisis`** (Downtrends, corrections, drawdowns).
     - Middle drift ($+6.9\%$) $\to$ **`Calm`** (Normal market equilibrium).
     - Highest drift ($+55.8\%$) $\to$ **`Bull Rally`** (Expansion breakouts).

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
  - `test_classify_synthetic_dataframe`: Tests 3-state HMM with OHLC input, Parkinson vol, EWMA vol, transition matrix, and 21D rolling features.
  - `test_classify_synthetic_series`: Tests series input fallback.
- Full test suite passing (4/4 tests PASSED).
- Verified live on FastAPI (`:8000`) and Next.js (`:3000`) with HTTP 200 OK.

