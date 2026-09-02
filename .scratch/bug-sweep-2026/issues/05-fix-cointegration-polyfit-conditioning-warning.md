# Issue 05: Fix Cointegration Polyfit Conditioning RankWarning in Backend

Status: resolved
Type: task

## Description
In `backend/app/services/cointegration_service.py:57`:
`gamma, _ = np.polyfit(z_lag, dz, 1)` emitted `RankWarning: Polyfit may be poorly conditioned` when `z_lag` had degenerate or zero variance.

## Resolution
- Checked `if float(np.var(z_lag)) < 1e-12: return None, None` before calling `np.polyfit`.
- Added unit regression test `test_compute_ou_parameters_zero_variance_no_warning` in `tests/test_bug_sweep_2026_09.py`.

## Verification
- Full pytest suite (279 tests) passed with 82.33% coverage and zero RankWarnings.

## Comments
Resolved and verified on 2026-09-02. Numerical safeguard verified.
