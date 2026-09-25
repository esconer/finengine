---
title: "FinEngine remediation learnings"
tags: [project, frontend, testing, isolated-verification]
summary: Durable seams discovered while fixing portfolio contracts.
created: 2026-09-25
updated: 2026-09-25
importance: medium
---

# FinEngine remediation learnings

- Next dev reads `frontend/.env.local`; for isolated `3001`/`8001` browser verification, temporarily point `NEXT_PUBLIC_API_URL` at `8001` and restore the file afterward. Use `localhost` for both frontend and backend origins to avoid dev-origin blocks.
- A Manage-page USD response must update the shared position count, not the shared monetary snapshot used by Dashboard/Header. Keep the global snapshot canonical INR; otherwise a USD view contaminates later dashboard totals.
- `Ticker`-derived native currency is authoritative over stale `region` metadata. Explicit currency/region conflicts fail closed; bfinance is not a valid non-Indian quote source.
- Portfolio analytics requests should coalesce by the current ticker snapshot. In React StrictMode, an in-flight promise must remain shared while the second effect attaches its own mounted-state callback.
- A whole-portfolio AI export can reuse existing FastAPI route handlers, but must pass every dependency explicitly (`db`, data/cache/benchmark/analytics services) and isolate per-section failures. The portfolio handler may refresh cached quotes and commit, so describe the export as holding-safe rather than strictly side-effect-free. The frontend AI request needs a longer timeout than the default Axios 60s because the default scope runs many live analytics calculations.
- Portfolio analytics can intentionally renormalize active weights when a leg has no usable history; the safe contract is explicit `requested_tickers`/`available_tickers`/`missing_tickers`, `weight_basis`, and `partial` status—not a fabricated zero return or an unexplained optimizer sell.
- A newly listed ETF may legitimately begin after the requested window. Accept an end-anchored, nonempty late-listing frame as limited history, then let annualization/coverage gates disclose its short sample; never backfill pre-listing prices.
- AI dashboard export must defer dashboard assembly until standalone sections are collected, then reuse those section envelopes; otherwise the dashboard silently duplicates or omits visible analytics components.
- Tail-dependence parent tickers must equal the nested matrix ticker order; retain the requested superset separately. Cache keys need a response-contract version when the response shape changes.
- A domain response may contain a numeric `components` map (risk score) without being a nested status envelope; status detection must require child objects with explicit status fields.
- Per-position annualization gates must use that position's own `data_points`, not the portfolio's shared holding-window count; otherwise a 20-day ETF can publish annualized metrics beside `is_limited_history=true`.
- Coverage status must be `unavailable` when a requested universe has zero usable results; `partial` is only for a non-empty covered subset. Keep the full persisted roster in requested coverage while calculating only positive finite active weights.
- Route functions called from the AI exporter must receive injected benchmark/data dependencies explicitly; constructing a dependency inside the handler bypasses FastAPI overrides and test seams.
- Latest-observation metadata must inspect DataFrame mappings and date columns, not only Series indexes; otherwise a valid DataFrame price frame is reported as having no observation date.
- India flow availability must be category-aware: preserve missing FII/DII legs as null/partial metadata rather than zero-filling them; the UI must branch on `data_status` before showing an empty/no-anomaly result.
- Ordered request metadata belongs in response-cache identity; sorting ticker order in a cache key can return the previous request's `requested_tickers` order.
- Shared AsyncSession reads used by concurrent market-data fetches must be behind the service DB gate, including runtime-config reads before network I/O.
- Explicit `quantity=0` means exited even if a stale stored market value remains; zero rows must not trigger FX or become equal-weight fallback allocations.
- Mixed-currency Monte Carlo cannot use local-price returns with an INR/USD balance; fail explicitly until base-currency total-return history exists.
- Late-listing acceptance metadata must survive L1/L2 cache slicing; annotate every cache-hit frame, not only fresh vendor responses.
- Empty performance/analytics collections are unavailable, not available empty successes; unavailable payloads must not retain plausible fallback score/risk constants.
- Cointegration cache identity must include a digest of effective overlapping prices, not only dates/counts, or same-day corrections reuse stale diagnostics.
