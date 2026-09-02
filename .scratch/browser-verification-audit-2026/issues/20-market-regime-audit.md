# Issue 20: Market Regime HMM Classification Audit & Economic State Correction

**Page Under Audit**: [/dashboard/regime](http://localhost:3000/dashboard/regime)  
**Status**: Verified & Fixed  
**Date**: September 2, 2026  

---

## 1. Quantitative Verification & Economic Coherence

### Mathematical Verification of Displayed Numbers

| Metric | Displayed Value | Mathematical Formulation | Quantitative Verification |
|---|---|---|---|
| **Current Regime** | **Calm** (formerly mislabeled Volatile) | Viterbi State Decoding over NIFTY returns + 21D Vol | **Fixed** -- Assigned to the lowest-volatility equilibrium regime (10.3% vol). |
| **Stability** | **74.0%** | (1 - Transition_Frequency) * 100% | **Valid** -- Reflects strong day-over-day state persistence. |
| **Benchmark Vol (this regime)** | **10.3%** | std(R_{NIFTY} | State = Calm) * sqrt(252) | **Valid** -- Baseline market volatility during Calm conditions. |
| **Days in Regime (hist.)** | **75%** | Count(Days in Calm) / 717 Total Days | **Valid** -- Dominant equilibrium state of the Indian equity market. |
| **Crisis State** | Return **-28.8%**, Vol **19.3%**, Share **12%** | Gaussian Emission Mean & Variance | **Valid** -- Accurately isolates bear drawdowns and panic selloffs. |
| **Bull Rally State** | Return **+63.1%**, Vol **18.9%**, Share **13%** | Gaussian Emission Mean & Variance | **Valid** -- Captures explosive momentum rally phases. |
| **Calm State** | Return **+4.6%**, Vol **10.3%**, Share **75%** | Gaussian Emission Mean & Variance | **Valid** -- Steady, low-volatility normal market drift. |
| **Portfolio in Current Regime** | **72 Days**, Return **+45.3%**, Vol **13.2%** | Conditional Portfolio Return & Realized Vol | **Valid** -- Book delivered massive alpha (+45.3% vs NIFTY +4.6%) with low 13.2% volatility. |

---

## 2. Identified Deficiencies in Initial Build

1. **State Labeling Bug**:
   - The backend previously assigned labels using a simplistic mean-variance composite rank: score = ann_ret - 0.5 * ann_vol.
   - Because the high-return Bull state (+63.1%) had the highest score, it was mistakenly labeled calm (despite having 18.9% vol).
   - Meanwhile, the true low-volatility state (10.3% vol, +4.6% return, 75% of days) had the middle score and was labeled volatile.
   - This produced the confusing paradox in the UI where a 10.3% volatility regime was called Volatile, while an 18.9% volatility regime was called Calm.
2. **Missing Explainer System**:
   - Missing interactive educational explainer modals (? buttons) across headline metric cards, HMM state parameters, 120-day timeline strip, and portfolio conditional performance.
3. **Missing CSV Export**:
   - Missing one-click export for HMM regime history and state distributions.

---

## 3. Implemented Enhancements

1. **Economically Accurate HMM Classifier**:
   - Re-engineered _label_states_by_risk in backend/app/services/regime_service.py to classify states by economic fundamentals:
     - State with negative return & high vol -> Crisis
     - State with lowest annualized volatility (vol = 10.3%) -> Calm
     - State with high positive momentum (ret = +63.1%) -> Bull
2. **Interactive Educational Explainer System**:
   - Added modal engine with comprehensive descriptions for all 7 Market Regime concepts.
3. **Timeline Styling & Visual Polish**:
   - Added color-coded chip legends (Calm = Green, Bull = Blue, Crisis = Red) and interactive hover effects on the 120-day timeline.
4. **CSV Export**:
   - Added one-click export generating full regime classifications, HMM state parameters, and daily history.
