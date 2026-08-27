# BRIEFING — 2026-08-26T16:08:41Z

## Mission
Build Indian Market Microstructure ingestion pipeline, SQLite models, ADV/ADTV participation-based liquidity analytics, and `/api/v1/india/*` API endpoints with zero fake mocks and comprehensive test suite.

## 🔒 My Identity
- Archetype: implementer / qa / specialist
- Roles: implementer, qa, specialist
- Working directory: c:\sukanta\coding\finengine\.agents\worker_m3_india_data
- Original parent: 77fe704f-bff4-421c-9df9-edfa6b1790ad
- Milestone: Worker M3 (Backend Developer: India Market Microstructure & ADV Liquidity Limits)

## 🔒 Key Constraints
- Exclusively owned files:
  - `backend/app/services/india_data_service.py` [NEW]
  - `backend/app/models/database.py` (add NSEBhavcopy, NSEInstitutionalFlow, NSEBulkBlockDeal, NSEShareholdingPattern models)
  - `backend/app/api/india.py` [NEW]
  - `backend/app/services/analytics_engine.py` (refactor calculate_liquidity_metrics)
  - `backend/main.py` (mount india.router under /api/v1/india)
  - `backend/tests/test_india_microstructure.py` [NEW]
- Integrity Mandate: No hardcoding test results, no dummy implementations. Real calculations, real state, genuine math.

## Current Parent
- Conversation ID: 77fe704f-bff4-421c-9df9-edfa6b1790ad
- Updated: not yet

## Task Summary
- **What to build**:
  1. `india_data_service.py`: Browser warmup session, local raw cache `data/nse/YYYY-MM-DD/`, bhavcopy ingestion & delivery % 20d MA / >2σ anomaly detection, FII/DII flow ingestion, bulk/block deal ingestion, promoter shareholding/pledge delta ingestion, idempotent local cache checks.
  2. Database models in `models/database.py`: `NSEBhavcopy`, `NSEInstitutionalFlow`, `NSEBulkBlockDeal`, `NSEShareholdingPattern`.
  3. Liquidity calculation refactor in `analytics_engine.py`: 20-day ADV (shares), ADTV (INR), Days-to-liquidate @ 10% and 20% ADV ($DTL = \text{Position Value} / (\text{Rate} \times \text{ADTV})$), Amihud (2002) illiquidity metric ($|R| / (P \times V)$), Max sane position size ($1.0 \times \text{ADTV}$), Capacity utilization %, Portfolio weighted DTL.
  4. API routes in `backend/app/api/india.py` (`/flows/fii-dii`, `/delivery-anomalies`, `/deals/bulk-block`, `/shareholding`, `/sync`) and mount in `backend/main.py`.
  5. Comprehensive tests in `backend/tests/test_india_microstructure.py`.
- **Success criteria**: All tests pass, 0 NaN/zero-division, genuine math, clean endpoints.

## Change Tracker
- **Files modified**: None yet
- **Build status**: Pending
- **Pending issues**: None

## Quality Status
- **Build/test result**: Pending
- **Lint status**: Pending
- **Tests added/modified**: Pending

## Loaded Skills
- None
