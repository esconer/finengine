# Bug Sweep 2026 — Comprehensive Codebase Bug Sweep & Hardening

Status: resolved · Owner: agent · Created: 2026-09-02 · Completed: 2026-09-02

## Scope & Objective
Thorough codebase audit across frontend (Next.js 16 / TypeScript / Recharts / TanStack Table / Zustand) and backend (FastAPI / SQLAlchemy / CVXPY / SciPy / NumPy / pandas / statsmodels / arch), documenting identified defects, implementing fixes, and verifying quantitative mathematical invariants without artificial mocking.

---

## Issues Inventory

| # | Ticket | Area | Problem | Target Fix | Status |
|---|---|---|---|---|---|
| 01 | issues/01-fix-portfolio-charts-typescript-and-mock-data.md | Frontend (PortfolioCharts.tsx) | TypeScript compilation failure (TS2339/TS2322) and hardcoded 11-month mock performance data | Fix Pie label and Tooltip formatter type signatures; derive real portfolio performance | resolved |
| 02 | issues/02-fix-concentration-page-invariant-and-metric-fallbacks.md | Frontend (concentration/page.tsx) | Fallback 98.3 violating single-holding diversification bound (N <= 1 => 0%), and fake mock metric card fallbacks | Strictly enforce N <= 1 => 0% diversification score; replace mock fallbacks with 'N/A' or live calculations | resolved |
| 03 | issues/03-fix-liquidity-page-mock-fallbacks-and-position-counts.md | Frontend (liquidity/page.tsx) | Hardcoded position count fallback || 14 and hardcoded metric card fallbacks ('1-2', 'Medium', 'Low') | Replace with live positions.length and dynamic liquidityData values or 'N/A' | resolved |
| 04 | issues/04-fix-volatility-sizing-page-mock-fallbacks-and-position-counts.md | Frontend (volatility-sizing/page.tsx) | Hardcoded position count fallback || 14 and fake estimated portfolio vol fallback '16.5%' | Replace with dynamic positions.length and live current_volatility or 'N/A' | resolved |
| 05 | issues/05-fix-cointegration-polyfit-conditioning-warning.md | Backend (cointegration_service.py) | RankWarning: Polyfit may be poorly conditioned in compute_ou_parameters when z_lag has zero variance | Add numerical variance safeguard before np.polyfit | resolved |
| 06 | issues/06-quantitative-mathematical-test-suite-and-pytest-loop-scope.md | Backend (test_quantitative_invariants.py, pyproject.toml) | Missing closed-form mathematical invariant tests, PytestDeprecationWarning loop scope unset, and pandas nanops RuntimeWarning on inf prices | Add dedicated mathematical validation suite, set asyncio_default_fixture_loop_scope, and sanitize infinite inputs | resolved |

---

## Acceptance Criteria & Results
- [x] TypeScript typecheck bun x tsc --noEmit exits with 0 errors.
- [x] Frontend test suite bun run test:run passes 100% (62/62 tests passed).
- [x] Frontend build bun run build compiles 24/24 static pages in 1.7s.
- [x] Backend pytest suite uv run python -m pytest passes 100% (287/287 passed, 0 warnings) with >= 80% coverage (82.52%).
- [x] All Quantitative & Terminal UI invariants defined in AGENTS.md strictly verified.
