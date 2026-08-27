# Spec: Quality Hardening — audit-driven fixes & improvements

Status: active · Owner: sukanta · Created: 2026-08-27
Depends on: `.scratch/project-state/current-state.md`, improvement plan audit (2026-08-27)

---

## 0. Goal

Fix correctness bugs, performance bottlenecks, type safety gaps, and testing/CI holes
surfaced by a deep three-way code audit (backend, frontend, test/devops). Every fix must
either prevent silent data corruption, measurably improve latency, or close a testing gap.

**Non-goals:** new features, UI redesign, new analytics endpoints. Those stay in
`.scratch/advanced-analytics/`.

## 1. Tiers (by severity)

| Tier | Scope | Tickets |
|---|---|---|
| 🔴 Correctness | Failing tests, weight corruption on delete, GARCH convergence, silent error masking | QH-01, QH-02, QH-03, QH-04 |
| 🟡 Performance | WebSocket unbounded queries, sequential batch fetching, cache stampede, missing memoization | QH-05, QH-06, QH-07, QH-08 |
| 🟠 Code Quality | Frontend type safety, SQLite upsert fragility, unused deps | QH-09, QH-10 |
| 🔵 Testing & CI | Backend coverage, frontend test foundation, CI pipeline fixes | QH-11, QH-12, QH-13 |

## 2. Execution order

Week 1: QH-01 → QH-02 → QH-03 → QH-05 (correctness + memory leak)
Week 2: QH-09 → QH-10 → QH-06 → QH-07 (type safety + perf)
Week 3: QH-04 → QH-11 (error envelopes + backend coverage)
Week 4: QH-13 → QH-12 → QH-08 (CI + frontend tests + memoization)

## 3. Notes on prior work

Some of these findings may overlap with work done in prior sessions. The 2026-08-26/27
session log indicates backend coverage reached 85.36% (243 tests) and many new services
shipped. However, the current working tree (as tested 2026-08-27) shows 148 tests with
2 failures, indicating the test suite state may have diverged. Each ticket should be
re-evaluated against the current working tree before implementation.

## 4. Acceptance

- Zero failing tests in `uv run pytest --no-cov`
- Backend coverage ≥ 80%
- Frontend has ≥ 1 test per page route
- CI pipeline runs green end-to-end (no dead k8s references)
- No `Promise<any>` in `api.ts`
