# E2E Test Infra: FinEngine (Daisy Risk Engine)

## Test Philosophy
- Opaque-box, requirement-driven, zero mocking of domain math.
- Complete coverage of all inventoried features F1 through F15.
- Methodology: Category-Partition + Boundary Value Analysis (BVA) + Pairwise Combinatorial + Real-World Workload Testing.

## Feature Inventory & Test Mapping
| # | Feature | Source (Requirement) | Tier 1 (Coverage) | Tier 2 (BVA/Corner) | Tier 3 (Pairwise) | Tier 4 (Workloads) |
|---|---------|----------------------|:-----------------:|:-------------------:|:-----------------:|:------------------:|
| F1 | Volatility Term Structure & Quantile Cone | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| F2 | EVT Peaks-Over-Threshold 99% VaR/ES | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| F3 | Copula Lower-Tail Dependence Matrix | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| F4 | Rolling 60d Correlation & Regime Breaks | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| F5 | Cointegration Scanner & OU Half-Life | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| F6 | NSE Bhavcopy & Delivery Ingestion | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| F7 | Institutional Flows & Pledges | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| F8 | Liquidity Limits & Sizing Engine | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| F9 | Cointegration Pairs UI (`/pairs`) | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| F10 | India Flows Dashboard (`/india-flows`) | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| F11 | Vol Cone & Copula Panels | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| F12 | Client-Side PDF Portfolio Review | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| F13 | Zero-Mock & Fake Data Purge | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| F14 | Backend 80%+ Test Coverage Gate | ORIGINAL_REQUEST §R5 | 5 | 5 | ✓ | ✓ |
| F15 | Frontend TypeScript & Vitest | ORIGINAL_REQUEST §R5 | 5 | 5 | ✓ | ✓ |

## Test Architecture
- **Backend Test Runner**: `pytest` inside `backend/` executing with coverage tracking:
  `uv run pytest --cov=app --cov-report=term-missing --cov-fail-under=80`
- **Database Fixtures**: Isolated in-memory SQLite schema per test function (`sqlite+aiosqlite:///:memory:`).
- **Frontend Test Runner**: `vitest` inside `frontend/`:
  `bun run test:run`
- **TypeScript Typecheck**:
  `bun x tsc --noEmit`

## Coverage Thresholds
- **Tier 1 (Feature Coverage)**: ≥ 75 test cases (≥5 per feature).
- **Tier 2 (Boundary & Corner)**: ≥ 75 test cases (empty portfolios, singular matrices, $\xi \ge 1$, $\gamma \ge 0$, zero volume, division by zero guards).
- **Tier 3 (Cross-Feature)**: ≥ 15 tests (vol cone + regime breaks, EVT VaR + HMM regimes, cointegration + liquidity sizing).
- **Tier 4 (Real-World Scenarios)**: ≥ 8 comprehensive end-to-end integration scenarios (10-stock NIFTY portfolio full analysis pipeline).
