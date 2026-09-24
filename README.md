# Daisy Risk Engine (finengine)

Personal, single-user, Bloomberg-style risk analytics terminal for Indian equity portfolios (NSE/BSE). Library-first quant stack (scipy, cvxpy, hmmlearn, arch, quantstats) behind a FastAPI backend and a Next.js dashboard: portfolio risk/factor decomposition, optimization (HRP, Min Vol, Max Sharpe, Min CVaR), regime detection (HMM on `^NSEI`), fat-tailed Monte Carlo goals, EVT tail risk, copula dependence, and Indian microstructure (delivery %, FII/DII flows, bulk/block deals).

**Architecture:** two apps + SQLite. Vendor cascade per fetch: `bfinance` ↔ `yfinance` (user-selectable primary/fallback) → Alpha Vantage (rotating key pool) as last tier, cached in SQLite (`backend/data/daisy.db`, auto-created).

| | |
|---|---|
| Backend | Python 3.12, FastAPI, `uv`, async SQLAlchemy + aiosqlite → `http://127.0.0.1:8000/api/v1` |
| Frontend | Bun, Next.js 16 (App Router), React 19, Tailwind, Zustand, TanStack, Recharts → `http://localhost:3000` |
| Data flow | Frontend proxies `/api/v1/*` → backend (Next rewrites, `frontend/next.config.ts`) |

Localhost-only by design (no auth — do not expose past `127.0.0.1`).

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (backend)
- [Bun](https://bun.sh/) (frontend; `bun.lock`)
- Optional: Alpha Vantage key(s) for the fallback tier

## Run (dev)

Terminal 1 — backend:

```bash
cd backend
uv sync
uv run uvicorn main:app --reload    # http://127.0.0.1:8000
```

Terminal 2 — frontend:

```bash
cd frontend
bun install
bun dev                             # http://localhost:3000
```

Open `http://localhost:3000`. First load fetches live quotes (network required); everything else caches to SQLite.

### Configuration (optional)

Drop a `backend/.env` (or export env vars) — all optional, sane defaults:

```bash
# DATABASE_URL=sqlite+aiosqlite:///./data/daisy.db
# ALPHA_VANTAGE_API_KEY=yourkey            # or ALPHA_VANTAGE_API_KEYS="k1,k2,k3"
# DEBUG=false
# RISK_FREE_RATE=0.02
```

### Docker (alternative)

```bash
docker compose up    # backend :8000, frontend :3000 (+ optional redis/nginx)
```

Prod variant: `docker-compose.prod.yml`.

## Tests & checks

```bash
# backend (workdir: backend/)
uv run --group dev ruff check main.py app/
uv run --extra dev pytest -q

# frontend (workdir: frontend/)
bunx tsc --noEmit
bun run test:run
bun run lint          # currently noisy — see .scratch/frontend-audit
```

Pre-commit runs `ruff check` (E9+F) on staged backend Python only (`git config core.hooksPath .githooks`).

## Repo layout

```
backend/    FastAPI app (app/api, app/services, app/models), main.py, migrations/
frontend/   Next.js app (src/app, src/components, src/lib, src/hooks)
docs/       ADRs, agent docs
.scratch/   audits (backend-audit/, frontend-audit/) and working notes
AGENTS.md   agent rules + domain invariants (read before editing)
CONTEXT.md  full system documentation
```

## Docs

- `CONTEXT.md` — system design, data flow, value proposition
- `PROJECT.md` — project overview
- `.scratch/backend-audit/00-INDEX.md` / `.scratch/frontend-audit/00-INDEX.md` — code audit findings
