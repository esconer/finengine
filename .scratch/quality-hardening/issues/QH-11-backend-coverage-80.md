# QH-11 — Backend test coverage push to 80% gate

Status: closed
Type: task
Blocked by: 24

## What

Current backend coverage is ~62% vs the 80% gate in `pyproject.toml`. Major untested areas:

| Untested Area | Risk |
|---|---|
| `data_service.py` vendor paths (yfinance retry, AV fallback, cache miss/hit) | Core data pipeline |
| `portfolio.py` response bodies (full CRUD cycle, edge cases) | Schema regressions |
| Data endpoints (`/fundamentals`, `/financials`, `/insider`) | Live vendor integration |
| Advanced analytics placeholders (`/vol-cone`, `/tail-dependence`, `/coint`) | Future endpoints |
| `currency_service.py` (conversion, formatting, cache behavior) | Currency display bugs |

## Fix

Write focused test suites for each gap. Priority order:
1. `data_service.py` — mock yfinance, test retry logic, cache upsert, AV fallback chain
2. `portfolio.py` — full CRUD cycle: add → get → update → delete → verify normalization
3. Data endpoints — mock yfinance `.info`/`.financials`, test 404 vs 503 semantics
4. Currency service — test conversion, cache expiry, Indian formatting

## Why

The 80% gate exists in `pyproject.toml` but is bypassed with `--no-cov`. Closing this gap
enables confident feature development for the remaining advanced-analytics tickets.

## Proof of done
- [ ] `uv run pytest` (WITH coverage) passes the 80% gate
- [ ] No `--no-cov` needed to get green CI
