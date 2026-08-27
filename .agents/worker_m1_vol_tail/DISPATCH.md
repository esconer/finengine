## 2026-08-26T16:08:41Z
You are Worker M1 (Quantitative Developer: Volatility Term Structure & Tail Risk Suite).
Working directory: c:\sukanta\coding\finengine\.agents\worker_m1_vol_tail
Original Request: c:\sukanta\coding\finengine\.agents\ORIGINAL_REQUEST.md
Master Project Blueprint: c:\sukanta\coding\finengine\PROJECT.md
Explorer 1 Survey: c:\sukanta\coding\finengine\.agents\explorer_survey_backend\handoff.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Exclusively Owned Files:
- `backend/app/services/volatility_service.py` [NEW]
- `backend/app/services/tail_risk_service.py` [NEW]
- `backend/app/models/schemas.py` (add VolConeResponse, TailRiskResponse schemas)
- `backend/app/api/analytics.py` (implement GET /vol-cone and GET /tails endpoints)
- `backend/tests/test_volatility_cone.py` [NEW]
- `backend/tests/test_tail_risk.py` [NEW]

Your mission:
1. Implement `volatility_service.py`: Multi-window (10, 21, 63, 126, 252d) rolling realized volatility quantiles (min, p25, median, p75, max, current_realized) + GARCH(1,1)/EWMA volatility forecast overlay and positioning ("cheap", "normal", "rich").
2. Implement `tail_risk_service.py`:
   - 99% EVT-POT (Peaks-Over-Threshold) VaR and Expected Shortfall using `scipy.stats.genpareto.fit` on 95th percentile excess losses. Compare against 99% historical VaR/ES.
   - Bivariate Student-t / empirical copula lower-tail dependence coefficient matrix ($N \times N$) for portfolio holdings ($\lambda_L = 2 t_{\nu+1}(-\sqrt{(\nu+1)(1-\rho)/(1+\rho)})$) and identify high tail-risk pairs.
3. Expose `GET /api/v1/analytics/vol-cone` and `GET /api/v1/analytics/tails` in `backend/app/api/analytics.py`.
4. Write thorough unit and integration tests in `backend/tests/test_volatility_cone.py` and `backend/tests/test_tail_risk.py`. Run `uv run pytest backend/tests/test_volatility_cone.py backend/tests/test_tail_risk.py` to verify passing results.
5. Write your handoff report to `c:\sukanta\coding\finengine\.agents\worker_m1_vol_tail\handoff.md` and send a message to parent when done.
