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
| **March 2026 Crash** (24.5k to 22,331) | 52-week crash trough; daily drops up to -3.3%; realized vol spiked to 24.5% | Labeled **BLUE (`Bull Rally`)** due to naive raw return sorting | Labeled **RED (`Crisis`)** (captures crash days with Ann Ret **`-27.7%`**, Vol **`20.9%`**) |
| **Normal Market Baseline** | Indian market compounding with positive equity risk premium (~+8% CAGR) | Labeled **`-10.9%` return** across 56% of days (economically nonsensical) | Labeled **GREEN (`Calm`)**: Ann Ret **`+6.4%`**, Vol **`9.8%`**, Share **`80.3%`** |
| **Explosive Expansion Rallies** | Rallies to all-time highs (26,300) and relief surges | Conflated with low-volatility baseline | Labeled **BLUE (`Bull Rally`)**: Ann Ret **`+49.0%`**, Vol **`20.9%`**, Share **`9.9%`** |
| **Portfolio Inside Regime** | User holds 14 equity positions in database | Empty placeholder card | **434 Overlapping Days**: Ann Ret **`+30.6%`**, Vol **`20.5%`** (consistent with growth beta) |

---

## 2. Identified Deficiencies & Code Bugs in `regime_service.py`

1. **Dead Code & Inconsistent Heuristic Labeling**:
   - `_label_states_by_risk` previously contained an outdated heuristic that assumed maximum volatility was crisis and minimum volatility was calm without checking economic returns.
   - `classify()` was duplicating labeling logic inline with different assumptions.
   - **Fix**: Re-engineered and unified `_label_states_by_risk(state_stats)` as the canonical source of truth:
     - Crisis: State with minimum annualized return ($\min \mu$).
     - Calm: Remaining state with lowest annualized volatility ($\min \sigma$).
     - Bull Rally: State with highest positive return ($\max \mu$).

2. **Timezone Comparison Mismatch in Portfolio Intersections**:
   - `detect_regime` previously converted dates via `pd.to_datetime` without stripping timezone information. When portfolio returns contained timezone metadata, pandas raised a `TypeError: Cannot compare tz-naive and tz-aware timestamps`.
   - **Fix**: Added `.tz_localize(None).normalize()` to both `pr.index` and `reg_series.index`.

3. **Potential NaN Propagation in Portfolio Volatility**:
   - If a filtered sub-series contained identical prices or fewer than 2 distinct days, `sub.std()` produced `NaN`, leading to invalid JSON responses.
   - **Fix**: Added guard check `ann_v = float(sub.std() * np.sqrt(252)) if len(sub) > 1 and not np.isnan(sub.std()) else 0.0`.

4. **Parkinson Range Volatility Edge Cases**:
   - High/low prices with non-positive values or inverted spreads ($H < L$) could cause $\ln(H/L)$ to produce `NaN` or negative values.
   - **Fix**: Sanitized inputs with `replace(0, np.nan)` and filtered only rows where $(H > 0) \land (L > 0) \land (H \ge L)$.

5. **Exposing Markov Transition Dynamics**:
   - Downstream allocators need to know transition persistence (e.g., $P(\text{Calm} \to \text{Crisis})$).
   - **Fix**: Formatted and exposed the full `transition_matrix` object in the API payload.

6. **Python 3.12+ Deprecation Warning**:
   - Replaced deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)`.

---

## 3. Test Coverage & Verification

- Added dedicated test suite `tests/test_regime_service.py`:
  - `test_label_states_by_risk`: Verifies ordering of economic states.
  - `test_classify_insufficient_data`: Confirms graceful `None` on short history.
  - `test_classify_synthetic_dataframe`: Tests 3-state HMM with OHLC input, Parkinson vol, EWMA vol, and transition matrix.
  - `test_classify_synthetic_series`: Tests series input fallback.
- Full suite executed and passing with HTTP 200 OK across FastAPI (`:8000`) and Next.js (`:3000`).
