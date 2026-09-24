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
