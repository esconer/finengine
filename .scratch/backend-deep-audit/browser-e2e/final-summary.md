# Final Summary

**Status:** COMPLETE — 2026-09-25  
**Audit window:** 2026-09-24–25 UTC  
**Scope:** isolated synthetic-data browser, runtime, API, accessibility, interaction, and financial-reconciliation audit.

## Guardrails and environment

- All browser/API mutation work used the isolated stack only: frontend `127.0.0.1:3001`, backend `127.0.0.1:8001`, disposable SQLite under `evidence/runtime/`.
- The five-position fixture is `RELIANCE.NS`, `HDFCBANK.NS`, `TCS.BO`, `AAPL`, and `MSFT`, with synthetic/provider values; it is `MOCK/DEMO` evidence, not a real-market certification.
- No source, configuration, test, or Git-history edits were intentionally made. Audit artifacts are confined to this `browser-e2e` output tree.
- The existing `3000/8000` stack was treated as protected/live. One earlier read-only-by-intent portfolio GET on port `8000` timed out; because the endpoint refreshes and commits, that request is conservatively disclosed as a possible live-cache/value change.
- Final isolated state: five canonical positions, `bfinance` restored, HTTP 200, and no temporary import/add rows. Evidence: `evidence/runtime/final-isolated-state.json`.

## Coverage completed

- **20/20 product pages**, plus `/` and the 404 boundary.
- **60 OpenAPI paths / 63 HTTP operations**, plus the WebSocket route.
- **44 empty** and **44 seeded/historical baseline** desktop/mobile captures.
- **572 final internal-scroll screenshots**: 13 positions per route × 22 route states × desktop/mobile.
- **39 interaction screenshots**, including import, controls, simulations, failures, settings, and WebSocket probes.
- **732 total screenshots** under `evidence/screenshots/`.
- **22/22 page reports** under `pages/`.
- Axe captured on 65/110 applicable states: 148 rule-occurrence records, 11 unique rule IDs. Empty-state axe, manual keyboard, focus-order, touch-target, and screen-reader passes remain `NOT TESTED`.

## Direct API and independent replay

- Direct API capture: **79/79 calls returned 2xx**; no HTTP or transport errors. Latency: 2.6 ms minimum, 82.3 ms median, 21,704.4 ms maximum.
- Core replay: **253 checks — 153 VERIFIED/MATCH, 73 DISCREPANCY, 27 UNVERIFIABLE/UNDERDETERMINED**.
- Advanced replay: **248 checks — 187 VERIFIED/PASS, 5 DISCREPANCY/FAIL, 56 UNVERIFIABLE/UNDERDETERMINED**.
- Explicit financial ledger: **535 non-deduplicated check events** (34 named portfolio/quote assertions plus 253 core and 248 advanced checks): **358 VERIFIED/MATCH, 88 DISCREPANCY/FAIL, 3 STALE, 86 UNVERIFIABLE/UNDERDETERMINED**. See `evidence/calculations/outputs/financial-verdict-ledger.md`.
- Advanced replay highlights: POT VaR `0.034130` / ES `0.048014`; 10 pairs scanned and 0 selected; optimizer and rounded-backtest invariants pass; exact stochastic/solver/fit paths remain `UNVERIFIABLE`.
- Full ledgers: `evidence/calculations/outputs/independent-core-models.{md,json}` and `independent-advanced-models.{md,json}`.

## Highest-priority confirmed findings

1. **P1 — USD rows are mislabeled:** the backend returns a converted envelope total and native position values; the frontend discards provenance and prefixes mixed-native values with `$`.
2. **P1 — AAPL quote mismatch:** FinEngine returns `$4.89`; the same-date captured history ends near `$336.29`, with independent observations near `$336.16`. Exact provider identity/as-of remains `UNVERIFIABLE`.
3. **P1 — Dashboard P&L is currency-invalid:** observed `+₹190,377.31 / +320.23%` versus a same-current-FX reference near `+₹5,234.56 / +2.14%`; acquisition-date historical FX remains `UNVERIFIABLE`.
4. **P1 — Dashboard diversification is noncanonical:** displayed `18.7%`; returned-quote concentration arithmetic gives approximately `50.5%` (HHI `0.5956`, effective holdings `1.68`). The input quote defect prevents external truth certification.
5. **P1 — Add Position infers `region: IN` for AAPL:** US re-seeding does not correct the quote/provenance defect. The CSV importer also hard-codes India region; the US CSV branch remains untested.
6. **P1 — Measured liquidity mixes currencies:** liquidity-limits reports `60,209.28` native-mixed versus the INR portfolio total `250,555.75`, with no currency field.
7. **P1/P2 — EGARCH exposes flat fallback values:** captured portfolio/RELIANCE fields use `0.05` / `-0.001` fallback constants where independent fits are non-flat; exact fit metadata is absent.
8. **P2 — Empty states are falsely reassuring:** zero portfolios show `0%`/safe diversification and contradictory liquidity/risk verdicts instead of unavailable.
9. **P2 — State and request orchestration defects:** stale shell counts/freshness, duplicate Market Crash stress POST, duplicate analytics GETs, and no automatically mounted frontend WebSocket despite a functioning backend transport.
10. **P2 — Accessibility/responsive defects:** 11 unique axe rule IDs across the captured states, plus mobile sticky-header obstruction, clipped controls/tables, truncation, and low-contrast action labels.

See `frontend-bugs.md`, `backend-bugs.md`, `data-freshness-bugs.md`, `financial-reconciliation.md`, and `ux-improvements.md` for evidence and ownership.

## Financial verdicts

- `VERIFIED`: first-position 100% weight; single-holding 0% diversification; native row arithmetic; current FX conversion; concentration HHI/effective-holdings/Gini; most EWMA fields; ADV/position-limit arithmetic.
- `DISCREPANCY`: USD row labels; Dashboard P&L; AAPL quote; measured liquidity portfolio value; documented model-family fields whose independent replay differs under the captured convention.
- `STALE`: HDFCBANK/TCS/MSFT/RELIANCE current-price differences where only intraday timing is available.
- `UNVERIFIABLE`: historical mixed-currency returns, exact provider/as-of freshness, exact model fit/sample contracts, and unavailable stochastic/solver paths.
- `MOCK/DEMO`: all synthetic fixture values and provider stand-ins.
- `NOT TESTED`: manual keyboard/screen-reader behavior, full mobile horizontal reachability, some export/search/help controls, live rebalance commit, and a US-ticker CSV import.

## Browser/runtime workflow results

- CRUD, duplicate 409, malformed/negative validation, edit/delete, currency switch, valid/unsupported CSV import, and cleanup: `VERIFIED` as workflow coverage; financial correctness is separately reconciled above.
- Forecast EGARCH/10-day, factor 504-day, stress Run All/custom, five optimizer strategies, three Monte Carlo methods, Pairs/Regime/India refresh, Equity search/statements/AI, Screener custom/add, Settings source/cache, and volatility-sizing dry-run: `VERIFIED` as exercised paths.
- Controlled provider failure, portfolio/database abort, and WebSocket status/subscribe/ping/disconnect/reconnect: `VERIFIED`; frontend automatic WebSocket wiring remains a confirmed integration gap.
- Live database commit was deliberately not exercised.

## Integrity and cleanup

- Main protected database file `backend/data/daisy.db` still matches the baseline hash.
- Protected live WAL/SHM hashes differ from baseline; this is disclosed as an environment/integrity discrepancy, not attributed to the isolated audit.
- Git status/diff fingerprints differ from the pre-audit baseline while the repository remains heavily dirty; no intentional protected-file edit was made. Details: `evidence/runtime/final-integrity.json` and `evidence/calculations/outputs/final-integrity.md`.
- Completion snapshot: `evidence/runtime/audit-completion.json` records 732 screenshots, 22 reports, zero Chrome processes, and zero audit listeners. The pre-existing `3000/8000` services were not stopped.

## Recommended fix order

1. Establish an explicit per-position currency/base-value/provenance contract and fix all frontend aggregation/formatting.
2. Reject or quarantine the AAPL quote using symbol/scale/provider sanity checks; add quote as-of/source metadata.
3. Make Dashboard P&L, diversification, liquidity limits, and Monte Carlo initial value use one declared base currency and canonical HHI arithmetic.
4. Replace fallback constants with typed unavailable states; publish reproducible model windows/parameters/raw samples.
5. Synchronize portfolio shell state and deduplicate analytics/stress requests; mount or remove the WebSocket client.
6. Fix empty-state semantics, axe violations, mobile clipping/sticky-header behavior, and import-region inference.

For route-by-route details, start with `00-INDEX.md` and `pages/`.
