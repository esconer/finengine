# Backend/API Bugs

Status: complete with explicit contract/verification limitations; direct API capture and offline replay are finished.

## BE-001 — Portfolio response mixes converted total with native position values

- **Severity:** P1
- **Owner:** backend contract ambiguity; frontend rendering is the primary visible owner
- **Endpoints:** `GET /api/v1/portfolio?currency=INR|USD`
- **Observed:** The backend correctly converts the envelope total and weights and supplies `position_currencies`, but position monetary fields remain native without explicit native/base field names. The frontend discards that provenance and formats them as USD. Dashboard then subtracts mixed-native cost from converted current value, producing ₹190,377.31 / +320.23%. A same-current-FX reference is ₹5,234.56 / approximately +2.14%; true historical-FX P&L remains unavailable without acquisition-date FX, and the reference remains conditional on the bad AAPL quote.
- **Expected:** Either return explicitly converted per-position fields for the selected base currency or expose an unambiguous native/base dual-value contract that the frontend must follow.
- **Evidence:** `evidence/network/pages/desktop/states/portfolio-usd-api.json` and browser row evidence.

## BE-002 — AAPL quote/value is materially wrong

- **Severity:** P1
- **Owner:** backend quote-acceptance/data-service path; exact upstream provider not proven
- **Endpoint:** `POST /api/v1/portfolio/add`, then `GET /api/v1/portfolio`
- **Observed:** FinEngine returned AAPL at `$4.89` with Unknown sector/industry and a five-share value of `$24.45`. Multiple secondary market observations on 2026-09-24 place AAPL near `$336–$337`; official numeric exchange/issuer pages were unavailable to the fetcher.
- **Difference:** Approximately `$331.27` per share, about 98.5% low.
- **Evidence:** `evidence/network/pages/desktop/states/us-reseed.json`, `evidence/calculations/inputs/external-market-crosscheck.md`.
- **Expected:** A successful quote should be sanity-checked against currency/scale and a second current source or provider response before being persisted as a position valuation.

## BE-003 — Portfolio position response omits region/currency provenance

- **Severity:** P2
- **Owner:** backend schema/provider integration
- **Endpoint:** `GET /api/v1/portfolio`
- **Observed:** Top-level `position_currencies` identifies AAPL/MSFT as USD, but position objects omit `currency` and `region`; AAPL is returned as Unknown with no explicit provider identity.
- **Expected:** Position records should expose the resolved currency/region and provider identity used for price/value calculation.

## BE-004 — Weak OpenAPI response contracts

- **Severity:** P2
- **Owner:** backend
- **Observed:** Only 18 of 63 HTTP operations declare a response model. Multiple frontend wrappers disagree with actual backend shapes.
- **Examples:** Stock history wrapper claims an array while the backend returns an object; refresh counts and config response shapes differ; analytics/company wrappers are stale.
- **Evidence:** `evidence/network/openapi/openapi.json` and frontend `src/lib/api.ts` cross-check.

## BE-005 — Environment variable conventions conflict

- **Severity:** P2
- **Owner:** backend/frontend configuration
- **Observed:** Axios requires `NEXT_PUBLIC_API_URL` to include `/api/v1`; the WebSocket client expects an origin and appends the path. `NEXT_PUBLIC_WS_URL` is configured but ignored.
- **Impact:** Alternate local stacks and deployments can send HTTP or WebSocket traffic to the wrong port/path.

## BE-006 — Portfolio GET endpoints perform writes

- **Severity:** P2
- **Owner:** backend API contract
- **Endpoints:** `GET /api/v1/portfolio`, `GET /api/v1/portfolio/{ticker}`
- **Observed:** Both refresh quotes and commit position values. This violates the usual safety expectation for GET and makes strict read-only audits impossible.
- **Evidence:** Current source and isolated behavior; classification remains documentation/operational rather than data loss.

## BE-007 — Measured liquidity mixes native position currencies

- **Severity:** P1
- **Owner:** backend liquidity contract
- **Endpoints:** `GET /api/v1/analytics/liquidity`, `GET /api/v1/analytics/liquidity-limits`
- **Observed:** The liquidity-limits response reports a portfolio value of `60,209.28` while the INR portfolio response reports `250,555.75` for the same five-position fixture. The limits response has no currency field, and the value is consistent with summing native INR and USD amounts.
- **Independent replay:** `evidence/calculations/outputs/independent-advanced-models.json` marks `liquidity.cross_endpoint_portfolio_value` as `FAIL`; the core replay independently reaches the same conclusion.
- **Expected:** Position value aggregation must declare and apply one base currency before calculating portfolio-level liquidity limits.
- **Evidence:** `evidence/network/api-final/liquidity_limits.200.json`, `evidence/network/api-final/portfolio_inr.200.json`, and the independent replay outputs.

## BE-008 — EGARCH forecast endpoint exposes flat fallback values

- **Severity:** P1/P2
- **Owner:** backend forecast service/model contract
- **Endpoint:** `GET /api/v1/analytics/forecast-risk?model=EGARCH&...`
- **Observed:** The captured EGARCH response uses literal `0.05` / `-0.001` fallback values for the portfolio and RELIANCE.NS in fields where the independent fit produces non-flat, materially different estimates. The exact GARCH/EGARCH initialization and distribution contract is not returned.
- **Expected:** Return an explicit unavailable/error state when a fit cannot be produced; do not present fallback constants as model forecasts, and expose the fit contract needed for reproduction.
- **Evidence:** `evidence/network/api-final/forecast_egarch_h30.200.json`, `evidence/calculations/outputs/independent-core-models.md`, and the browser EGARCH/10-day capture.

## BE-009 — Several analytics response families do not reproduce under documented raw inputs

- **Severity:** P2 analytical-contract discrepancy
- **Owner:** analytics service owners
- **Observed:** The independent core replay checked 253 assertions: 153 matched, 73 discrepant, and 27 underdetermined. The largest affected families were realized risk (33 discrepancies), factor exposure (19), risk contribution (9), forecast GARCH/EGARCH (7 combined), and volatility-sizing endpoint consistency (3). These are not all asserted as implementation errors: several depend on alignment, annualization, tail attribution, or benchmark conventions absent from the response.
- **Expected:** Return sample counts, alignment, annualization, benchmark, tail, and model-parameter metadata; then make independently reproducible claims testable.
- **Evidence:** `evidence/calculations/outputs/independent-core-models.json` and `.md`.

## BE-010 — Analytics unavailable/error contracts are inconsistent

- **Severity:** P2
- **Owner:** backend API error schema/frontend orchestration
- **Observed:** Empty states produce a mix of HTTP 404s, HTTP-200 payloads containing an `error`, and visible “N/A” or “no data” states. Examples include empty Risk Studio/Risk Contribution/Pairs calls and Forecast's 200 error payload. The UI sometimes advances freshness text despite unavailable data.
- **Expected:** Use one typed unavailable contract and ensure freshness/status labels cannot advance when the required payload is unavailable.
- **Evidence:** Empty-state page/network captures, `evidence/calculations/outputs/browser-baseline-summary.md`, and `evidence/network/api-final/` bodies.

## BE-011 — Direct API capture is healthy, but model response contracts remain incomplete

- **Severity:** P2 verification limitation
- **Owner:** API contract/documentation
- **Observed:** All 79 isolated direct API calls returned 2xx with no transport errors. Despite that transport success, exact replay remains underdetermined for cointegration, correlation windows, volatility-cone frames, stochastic Monte Carlo paths, optimizer solver conventions, regime state fitting, and parts of India/delivery data because the responses omit the required raw fit/sample metadata.
- **Expected:** Publish reproducible request/response contracts or return the raw sample and method metadata needed to audit each model.
- **Evidence:** `evidence/network/api-final/api-capture-summary.md`, `evidence/calculations/outputs/independent-advanced-models.md`, and `.json`.

## Pending direct verification

- Historical acquisition-date FX and transaction/cash-flow ledger remain unavailable.
- Exact provider identity, quote as-of timestamp, and delayed/live status remain unavailable for the bad AAPL quote.
- Manual keyboard/screen-reader and mobile horizontal-reachability checks remain outside the automated evidence set.
