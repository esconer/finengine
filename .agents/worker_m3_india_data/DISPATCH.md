## 2026-08-26T16:08:41Z

You are Worker M3 (Backend Developer: India Market Microstructure & ADV Liquidity Limits).
Working directory: c:\sukanta\coding\finengine\.agents\worker_m3_india_data
Original Request: c:\sukanta\coding\finengine\.agents\ORIGINAL_REQUEST.md
Master Project Blueprint: c:\sukanta\coding\finengine\PROJECT.md
Explorer 2 Survey: c:\sukanta\coding\finengine\.agents\explorer_survey_india_data\handoff.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Exclusively Owned Files:
- `backend/app/services/india_data_service.py` [NEW]
- `backend/app/models/database.py` (add NSEBhavcopy, NSEInstitutionalFlow, NSEBulkBlockDeal, NSEShareholdingPattern models)
- `backend/app/api/india.py` [NEW]
- `backend/app/services/analytics_engine.py` (refactor calculate_liquidity_metrics to use ADV, ADTV, DTL @ 10%/20%, Amihud ILLIQ, and max sane position limits)
- `backend/main.py` (mount india.router under /api/v1/india)
- `backend/tests/test_india_microstructure.py` [NEW]

Your mission:
1. Implement `india_data_service.py`:
   - Browser session warmup (GET https://www.nseindia.com/ to capture cookies/headers).
   - Local raw archive storage under `data/nse/YYYY-MM-DD/`.
   - Ingestion and SQLite persistence of daily bhavcopy (`sec_bhavdata_full_DDMMYYYY.csv`), delivery % 20d moving averages and >2σ smart money accumulation anomalies.
   - Ingestion of FII/DII net flows (`fiidiiTradeReact`), bulk/block deals, and quarterly promoter shareholding & pledge deltas.
   - Idempotent execution (check local disk cache before fetching upstream).
2. Refactor liquidity calculation in `analytics_engine.py`:
   - Compute 20-day ADV (shares) and ADTV (INR).
   - Days-to-liquidate @ 10% and 20% participation ($DTL = \text{Position Value} / (\text{Rate} \times \text{ADTV})$).
   - Amihud (2002) illiquidity metric ($|R| / (P \times V)$).
   - Max sane position size (5 days @ 20% ADV = $1.0 \times \text{ADTV}$) and capacity utilization percentage.
3. Expose `/api/v1/india/*` routes (`/flows/fii-dii`, `/delivery-anomalies`, `/deals/bulk-block`, `/shareholding`, `/sync`) and update `/api/v1/analytics/liquidity`.
4. Write thorough unit and integration tests in `backend/tests/test_india_microstructure.py`. Run `uv run pytest backend/tests/test_india_microstructure.py` to verify passing results.
5. Write your handoff report to `c:\sukanta\coding\finengine\.agents\worker_m3_india_data\handoff.md` and send a message to parent when done.
