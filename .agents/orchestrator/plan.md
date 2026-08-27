# Master Execution Plan: FinEngine Quantitative & Production Hardening

## Overview
Decompose the implementation and verification of FinEngine (Daisy Risk Engine) into two tracks:
1. **Implementation Track**: Modular milestone execution (M1 through M4, then M5 hardening).
2. **E2E Testing Track**: Requirement-driven opaque-box test harness and comprehensive test suites (Tiers 1-4).

## Phases

### Phase 0: Survey & Scoping (Current)
- Spawn 3 parallel Explorers:
  - Explorer 1: Backend architecture, analytics endpoints, quantitative modules (GARCH, EVT, Copula, Cointegration).
  - Explorer 2: Data ingestion, India market microstructure (NSE data service, bhavcopy, FII/DII, bulk deals, liquidity metrics).
  - Explorer 3: Frontend components, pages, visual studio, PDF export, mock purge targets, test suite configuration.
- Aggregate findings into `PROJECT.md` and `TEST_INFRA.md`.

### Phase 1: Dual Track Launch
- **E2E Testing Track Orchestrator**: Build test runner, fixtures, and Tiers 1-4 test cases -> Publish `TEST_READY.md`.
- **Implementation Sub-Orchestrators**:
  - M1: Advanced Volatility & Tail Risk Suite (`GET /api/v1/analytics/vol-cone`, 99% EVT-POT VaR/ES, copula tail-dependence matrix).
  - M2: Correlation Stability & Cointegration Pairs Scanner (rolling 60d correlation, `GET /api/v1/analytics/coint` Engle-Granger/Johansen/OU half-life, caching).
  - M3: India Market Microstructure & ADV Liquidity Limits (`app/services/india_data_service.py`, SQLite/cache, ADV days-to-liquidate, Amihud illiquidity).
  - M4: Frontend Visual Studio, PDF Export & Zero-Mock Purge (`/pairs`, `/india-flows`, vol cone panel, copula heatmap, jsPDF portfolio review, zero-mock purge).

### Phase 2: Final Milestone (M5) & Verification
- Pass 100% of E2E test suite (Tiers 1-4).
- Adversarial coverage hardening (Tier 5) with Challengers & Critics to enforce `pytest --cov=app --cov-fail-under=80`, `bun x tsc --noEmit`, and `bun x vitest run`.
- Forensic Audit verification for zero cheating/hardcoding/mocking.
