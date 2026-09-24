# 04 — Replace forecast fallback constants with explicit unavailable states

Status: ready-for-human
Type: bug
Priority: P1/P2
Owner: main thread
Blocked by: —

## Problem

EGARCH responses expose literal fallback values such as 0.05 / -0.001 when a fit is unavailable, while the UI presents them as model output.

## Acceptance criteria

- Failed/insufficient model fits return null/typed unavailable fields with an explicit error or warning.
- Frontend never renders fallback constants as measured forecasts.
- Existing valid EWMA/GARCH behavior remains covered.
- Regression tests pin unavailable and valid forecast branches.

## Evidence

- `.scratch/backend-deep-audit/browser-e2e/backend-bugs.md`
- `.scratch/backend-deep-audit/browser-e2e/evidence/calculations/outputs/independent-core-models.md`
- `.scratch/backend-deep-audit/browser-e2e/evidence/network/api-final/forecast_egarch_h30.200.json`

## Comments

Exact EGARCH initialization/distribution is an underdetermined follow-up; do not fabricate a replacement fit in this issue.

### Progress

- Removed valid-path EGARCH volatility/VaR/CVaR floors that produced literal fallback-looking values.
- Propagated fit errors through the forecast-risk response.
- Added low-variance and unavailable-error regression tests; focused analytics tests and ruff pass.
