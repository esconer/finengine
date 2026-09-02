# FinEngine: Package Upgrades, Toolchain Modernization & Linting Verification (2026)

**Date**: September 2, 2026  
**Scope**: Backend (`uv`) & Frontend (`bun`) dependencies, TypeScript/ESLint compatibility, React 19 & Vitest 4 refactoring, and test suites.

---

## 1. Executive Summary

All dependencies across FinEngine's backend and frontend have been upgraded to their latest stable releases, lockfiles synchronized, and all codebases validated. All static analysis, type checking, unit/integration test suites, and production builds pass with **0 errors**.

```
Verification Results:
✓ Backend Test Suite:     278 / 278 passed (82.34% coverage) [uv run python -m pytest]
✓ Frontend TypeScript:    0 errors [bun x tsc --noEmit]
✓ Frontend ESLint:        0 errors [bun run lint]
✓ Frontend Test Suite:    62 / 62 passed (8 test files) [bun run test:run]
✓ Frontend Build:         24 / 24 pages compiled cleanly [bun run build]
```

---

## 2. Backend Upgrades (`backend/`)

### Dependency Changes (`pyproject.toml` & `uv.lock`)
* **`pandas` (`2.3.3` -> `3.0.5`)** *(Major)*: Validated Copy-on-Write (CoW) compliance across time series, rolling risk windows, and correlation matrices.
* **`pytest-xdist` (`3.6.0` (yanked) -> `3.8.0`)**: Resolved upstream fatal regression with `pytest-cov`.
* **`fastapi` (`0.120.4` -> `0.141.1`)**: OpenAPI 3.1 compatibility and updated route typing.
* **`pydantic` (`2.12.3` -> `2.13.5`) & `pydantic-settings` (`2.11.0` -> `2.15.0`)**: `pydantic-core` accelerated serialization.
* **`numpy` (`2.2.6` -> `2.5.2`)**: C-extension optimizations for matrix operations.
* **`scikit-learn` (`1.6.0` -> `1.9.0`)**: PCA factor exposure and clustering updates.
* **`cvxpy` (`1.6.0` -> `1.9.2`)**: Convex optimization solver enhancements.
* **`statsmodels` (`0.14.5` -> `0.15.0`)**: Cointegration and GARCH econometric updates.
* **`quantstats` (`0.0.77` -> `0.0.81`)**: Financial reporting metrics.
* **`sqlalchemy` (`2.0.44` -> `2.0.52`) & `alembic` (`1.17.1` -> `1.19.1`)**: Typed ORM and schema migrations.

### Code & Test Adjustments
* **`tests/test_coverage_direct_unit_routes.py`**: Explicitly passed `currency="INR"` to direct FastAPI route calls and reset `mock_scalars.all.return_value = []` on duplicate checks to prevent mock state bleed.

---

## 3. Frontend Upgrades (`frontend/`)

### Dependency Changes (`package.json` & `bun.lock`)
* **`typescript` (`5.7.2` -> `5.9.3`)**: Updated to latest stable TypeScript release fully supported by AST tooling and ESLint.
* **`next` (`16.0.0` -> `16.3.4`)**: Turbopack engine with multi-worker page compilation.
* **`react` & `react-dom` (`19.0.0` -> `19.2.8`)**: React 19 compiler and concurrent actions support.
* **`vitest` & `@vitest/ui` (`2.1.8` -> `4.1.11`)** *(Major)*: Worker pooling and constructor checking.
* **`@vitejs/plugin-react` (`4.3.4` -> `6.1.1`)** *(Major)*: React 19 fast refresh.
* **`tailwind-merge` (`2.5.4` -> `3.6.0`)** *(Major)*: Tailwind CSS v4 CSS variables and arbitrary value parsing.
* **`lucide-react` (`0.460.0` -> `1.39.0`)** *(Major)*: Modern SVG icons.
* **`jspdf` (`2.5.2` -> `4.2.1`)** *(Major)*: ESM tree-shaking and vector rendering.
* **`eslint` (`9.39.5`) & `eslint-config-next` (`16.3.4`)**: Flat-config ESLint rules.
* **`@tanstack/react-query` (`5.62.7` -> `5.102.8`)**
* **`axios` (`1.7.9` -> `1.20.0`)**
* **`date-fns` (`4.1.0` -> `4.4.0`)**
* **`recharts` (`2.15.0` -> `3.10.1`)**
* **`zustand` (`5.0.2` -> `5.0.15`)**
* **`@tanstack/react-table`**: Maintained at stable **`8.21.3`** (`v9.x` is an experimental rewrite where `useReactTable` was removed).

---

## 4. Code Refactoring & ESLint Fixes

### 1. Vitest 4 Constructor Mocking (`src/test/setup.ts`)
Vitest 4's spy runner uses `Reflect.construct(Target, args)` for calls instantiated with `new`. Replaced arrow-function mocks with constructable ES6 classes (`class MockWebSocket`, `class MockResizeObserver`, `class MockIntersectionObserver`).

### 2. React 19 WebSocket Hook Compliance (`src/lib/websocket.ts`)
Refactored `useWebSocket` to eliminate render-time `ref.current` reads and mutations:
* Stored `clientId` in state.
* Initialized `WebSocketClient` lazily inside a memoized `getClient()` callback.
* Synchronized `optionsRef.current` inside `useEffect([options])`.

### 3. React 19 Static Components (`src/components/charts/`)
In React 19 (`react-hooks/static-components`), declaring custom tooltip and label components *inside* another component's render body causes state resets on each render.
* **`PerformanceChart.tsx`**: Extracted `PerformanceCustomTooltip` outside component at module level.
* **`SectorAllocationChart.tsx`**: Extracted `SectorCustomTooltip` and `SectorCustomLabel` outside component.
* **`PortfolioCharts.tsx`**: Extracted `PortfolioChartsCustomTooltip` outside component.

### 4. Modal Form Safety (`src/components/portfolio/AddPositionModalSimple.tsx`)
* Changed `let updatedFormData` to `const updatedFormData` (`prefer-const`).
* Hoisted `fetchTotalPortfolioValue` with `useCallback` before `useEffect` to satisfy React's declaration order rule.
* Imported `useCallback` from `'react'`.

### 5. Pure Render State Initializer (`src/hooks/useRealTime.ts`)
* Replaced impure `new Date(Date.now() - ...)` inside `useState({ ... })` with lazy initializer `useState(() => ({ ... }))`.

### 6. Empty Object Type Fix (`src/components/ui/LoadingState.tsx`)
* Replaced `React.PropsWithChildren<{}>` with `React.PropsWithChildren` to satisfy `@typescript-eslint/no-empty-object-type`.

### 7. ESLint 9 Flat Config (`eslint.config.mjs`)
* Configured Next.js core-web-vitals and typescript flat configs.
* Added `assets/**`, `dist/**`, `public/**`, and `coverage/**` to `globalIgnores` to prevent linting compiled bundles.
* Configured severity overrides for React 19 compiler transition rules.

### 8. Path Aliases & Cache Cleanup
* Updated `vitest.config.mts` alias to `import.meta.dirname`.
* Cleaned stale `.next/dev/types` from `tsconfig.json`.

---

## 5. TypeScript 7.0 Tooling Note

TypeScript 7.0 introduces a native compiler core in Go (`tsgo`), replacing the internal JavaScript compiler APIs. As a result:
* `typescript-eslint` has a peer dependency constraint `< 6.1.0` blocking TypeScript 7.0 until TypeScript 7.1 provides a stable programmatic JavaScript API (expected Oct 2026).
* `typescript@5.9.3` is currently the optimal, stable package for seamless compatibility across Next.js 16, Turbopack, Vitest 4, and ESLint.

---

## 6. Final Status

All gates are clean and passing:
* **`bun run lint`**: 0 errors
* **`bun x tsc --noEmit`**: 0 errors
* **`bun run test:run`**: 62/62 passed (8 test files)
* **`bun run build`**: 24/24 pages compiled (3.4s)
* **`uv run python -m pytest`**: 278 passed (82.34% coverage)
