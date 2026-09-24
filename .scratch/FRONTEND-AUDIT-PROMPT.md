# Frontend audit + UI/UX revamp session prompt (paste into a fresh session)

```
You are running an INDEPENDENT, DOCUMENTATION-ONLY deep audit of the FinEngine frontend and a
UI/UX design plan for it. Working dir: C:\es\coding\finengine. You produce reports — you change NO code.

STACK (already installed — reuse, never recommend a parallel tool): Next.js 16 (App Router) · React 19 ·
TypeScript 6 · Tailwind CSS 4 · TanStack Query 5 · TanStack Table 9 · Recharts 3 · Zustand 5 ·
Radix UI primitives (dialog, dropdown-menu, select, tabs, tooltip, slot) · lucide-react · axios · date-fns ·
papaparse · xlsx · file-saver · jspdf · Vitest + Testing Library · eslint-config-next.
Backend: FastAPI at http://localhost:8000 (SQLite, yfinance/Alpha Vantage/NSE-BSE data, Indian .NS/.BO + US equities).
Domain is from CONTEXT.md and AGENTS.md (read both first).

READ-ONLY CONTRACT (highest priority):
- Never edit, create, or delete anything outside .scratch/. No frontend/, no backend/, no config, no git.
- Write reports and any evidence files ONLY under .scratch/frontend-audit/.
- You MAY run read-only commands: bun run lint, bun run test:run, bunx tsc --noEmit, bun run build
  (build only if it does not write outside .scratch — otherwise skip and note it).
- Visual evidence: you MAY use the agent-browser skill against the local dev server (bun run dev) to take
  screenshots / inspect real pages; save them ONLY under .scratch/frontend-audit/shots/. No code edits.
- No futures or options product content: cash equities + portfolio analytics only. If a design idea is
  derivatives-shaped, cut it.

OUTPUT DIRECTORY: .scratch/frontend-audit/
  00-INDEX.md            — master index: coverage, counts, priorities, links
  audit/01..0N-*.md      — per-area line-by-line audit
  ux/00-audit.md         — heuristic + task-flow evaluation
  ux/01-design-system.md — target visual system (tokens, type scale, chart palette, spacing)
  ux/02-page-maps.md     — current vs target IA and per-page layout specs
  ux/03-capability-ui.md — backend capability → screen/widget/state coverage matrix
  ux/04-stock-add-journey.md — full “research a stock → add it” flow spec
  ux/05-wireframes.md    — text wireframes for the redesigned pages
  ux/06-revamp-plan.md   — phased plan, impact, effort, dependencies, skipped items with reasons
  evidence/              — screenshots, a11y/perf logs

TASK A — LINE-BY-LINE CODE AUDIT (read every first-party file fully: src/app/**, src/components/**,
src/hooks/**, src/lib/**, src/types/**, src/test/**, configs: next.config.ts, eslint.config.mjs,
tailwind/postcss, vitest.config.mts, Dockerfile, .env.local keys — no values). Categories per finding:
Bug / Improvement / Optimization / Revamp-needed. Severity P0 (data corruption/security/crash) / P1
(wrong data shown, broken flow) / P2 / P3.
Check specifically:
  - TanStack Table rule: every cell renderer must read `row.original || row` (NaN/unrendered-value bug class).
  - Bivariate matrix parsing: endpoints returning { tickers, matrix } must bind tickers as headers and index
    matrix[i][j] — never Object.keys() on the outer response.
  - Currency/market formatting: Indian equities (.NS/.BO) must use en-IN notation (₹, Cr, L) via one shared
    formatter; flag any duplicated or inconsistent number/percent/date formatting.
  - API layer (src/lib/api.ts): axios timeouts, error normalization, query-param bugs, missing loading/error
    states, response-shape drift vs backend schemas, silent catch blocks, N+1 client request patterns.
  - React Query: staleTime/cacheKey correctness per data volatility (prices vs financials vs static metadata),
    invalidation after mutations, refetch storms, missing stale-while-revalidate UX.
  - Zustand store: derived state duplicated, selector re-render bugs, state not reset on portfolio change.
  - Websocket client (src/lib/websocket.ts): reconnect/backoff, unmount cleanup, stale subscription leaks,
    optimistic vs server reconciliation.
  - Forms: client validation, error surfacing, double-submit, destructive-action confirmation.
  - Export paths (src/lib/export.ts): CSV must be raw text/plain (backend export bug) — flag any client-side
    assumption that contradicts backend content types; PDF via jspdf and XLSX via xlsx/xlsx naming collisions.
  - Accessibility basics: keyboard traps, focus management, aria on Radix usage, color-only signals, contrast.
  - Performance: bundle imports, chart re-render cost, large-client components that should be server,
    missing dynamic imports for heavy charts/export libs.
  - Hygiene: dead code, duplicated components, prop drilling, `any`, missing error.tsx/not-found coverage,
    test gaps (Vitest coverage of lib/ and components), Dockerfile correctness.

TASK B — UI/UX AUDIT (evaluate, don’t guess): run the app (bun run dev) and use agent-browser at desktop
(1440×900) AND mobile (390×844) widths. Screenshot every route into evidence/ and cite the shot filename
for every claim. Evaluate: information architecture, page inventory vs backend capabilities, visual hierarchy,
density (this is a data-heavy quant tool — Bloomberg density is a feature, but only if structured), data
table ergonomics (sort/filter/column control/CSV export), chart choice per question (line vs area vs bar vs
distribution vs correlation heatmap), color semantics in market context (green/red = up/down IN vs US, and
color-blind safety), empty/loading/error/partial-data states, number formatting consistency, freshness
timestamps on data, responsive behavior, keyboard/screen-reader basics, first-run and destructive flows.

TASK C — CAPABILITY → UI COVERAGE MATRIX (the core deliverable): inventory every backend endpoint
(backend/app/api/*.py: read the actual routes) and every backend service capability, then map each to:
screen or widget that exposes it (file:line) | not exposed → recommended screen/widget | not useful to expose
→ why. No backend capability should be unreachable from the UI; no UI widget should be unsupported by the API.
This matrix is the source of truth for ux/03-capability-ui.md.

TASK D — THE “RESEARCH A STOCK → DECIDE → ADD” JOURNEY: design the flagship user flow end-to-end:
  1. Discover/search a ticker (existing screener, equity research endpoints).
  2. Research view: fundamentals, valuation, price history, technicals, risk, ownership — group by question
     the user asks, not by API.
  3. “What if I add this?” — portfolio impact at decision time: marginal Δ vol / VaR / drawdown, Δ HHI and
     effective N, correlation to current holdings, sector/region exposure drift, concentration, tracking
     error, expected-return model used (name it), liquidity check. State which backend services already
     compute each piece (cite) and which need new endpoints.
  4. Verdict block: IMPROVES / NEUTRAL / DISADVANTAGES the portfolio, driven only by live API values —
     never placeholder or mock deltas; every metric card driven by a real response field; missing data shown
     as unavailable, never fabricated.
  5. Add-to-portfolio step with size input, review of resulting weights, and a real confirmation that the
     result came from the server.
Also specify states: no result, stale price, provider degraded, insufficient history, unsupported currency.

TASK E — VISUAL SYSTEM + REVAMP PLAN: define the target design language as tokens (color roles incl. a
checked color-blind-safe up/down pair, type scale, spacing, radius, elevation — flat and restrained, no
template gradients/shadows), a chart palette, and table/chart component specs. Then write per-page target
layouts (text wireframes in ux/05-wireframes.md) and a phased plan (ux/06-revamp-plan.md) with: phase, goal,
files touched, user-visible impact, effort (S/M/L), dependencies on backend gaps from
.scratch/backend-audit/ and .scratch/backend-deep-audit/, risk, and what is explicitly SKIPPED (one line each).
Include a migration map for the existing components (keep/replace/delete).

LIBRARY / ASSET RULE (don’t reinvent the wheel): before recommending any new dependency, component, chart
engine, icon set, or template, (1) verify whether an installed package already covers it; (2) if new, cite
its official docs URL (verified with web search/fetch — never guess URLs), license, bundle-size/maintenance
note, and one alternative; (3) prefer free. Recommendation only — this session adds nothing. Templates and
boilerplate are NOT a recommendation; note them only to rule them out.

WORKFLOW — parallel subagent waves with personas (all read-only on code; each writes only its assigned paths):

WAVE 1 (parallel):
- “Frontend Code Auditor” ×4: (1) app router + layout + error/loading states; (2) components/charts +
  components/ui + layout; (3) components/portfolio + hooks; (4) lib (api, store, websocket, export, utils)
  + types + tests + configs. → audit/0N-*.md
- “UX Auditor” (evidence-driven, runs the app, screenshots, no code) → ux/00-audit.md.
- “Capability Mapper” (backend routes × UI) → ux/03-capability-ui.md.
- “Stock-Journey Designer” → ux/04-stock-add-journey.md.
- “Design-System Architect” → ux/01-design-system.md + ux/02-page-maps.md + ux/05-wireframes.md +
  ux/06-revamp-plan.md (consumes ux/00 and ux/03 if present; if not, state the assumption).
Each returns: output path, finding counts by severity, top 3 findings, and for design outputs the top
3 highest-leverage changes.

WAVE 2 — “Cross-Reviewer”: read all Wave-1 outputs, re-verify every P0/P1 against the code (cite lines),
deduplicate, and flag design proposals that contradict backend reality (unsupported data, mocked values,
non-existent endpoints). Append corrections to ux/06-revamp-plan.md.

WAVE 3 — “Chief Editor”: write 00-INDEX.md: coverage table, severity counts, top-10 revamp priorities
(effort vs user-decision value), capability→UI coverage summary, the final “no-fabricated-metrics” rule
list, and a short “what we deliberately did not redesign and why”.

FINAL REPORT TO ME: counts by category, the 5 highest-impact UI/UX changes with effort, the biggest
backend-capability gaps the UI cannot fill (one line each, with the backend file:line), the confirmed
frontend bugs (P0/P1 list), and confirmation that nothing outside .scratch/frontend-audit/ was modified.
```
