# 02 — `stress-testing` is not a simulation

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `frontend/` + `backend/` (presentation only)
Severity: **HIGH**

## What

The backend explicitly publishes, for every scenario:

```python
# analytics_engine.py:1072-1085
"methodology": "Deterministic factor shock proxy; no path sampling and no simulation…"

# :1091
"max_drawdown_basis": "derived_from_shock_proxy"
# :1094
"impact_basis": "deterministic_factor_proxy"
# :1097
"recovery_time_basis": "configured_recovery_estimate_not_simulated"
# :1099
"confidence_basis": "nominal_label_not_simulated"
```

The frontend **declares `methodology?: string` at `stress-testing/page.tsx:42` and never renders
it.** Nor does it render `shock_inputs` or `units`. Instead it ships:

| Line | Text |
|---|---|
| 684 | `"Multi-Factor Simulation Engine"` |
| 691 | `"Simulate historical liquidity freezes…"` |
| 598 | column header `"Simulated Impact"` |
| 773 | button `"Simulating…"` |
| 941 | button `"Run Simulation"` |
| 83 | explainer: `"across all executed stress testing simulations"` |

## Why

A user reading this page believes a Monte-Carlo or structural stress engine ran. None did. The
backend authors added the four `*_basis` fields and a `methodology` string **precisely to prevent
this misreading**, and the frontend ignores all five.

The impact is compounded by `CONTEXT.md` §9.13, which documents that the sector elasticities are
hand-tuned multipliers (Healthcare 0.25–0.55×, Tech 1.10–1.80×) — unsourced and unbounded. A
scenario grid whose sector betas were invented, labelled as a simulation, is the definition of fake
precision.

## Change

- Render `methodology` prominently — it is the backend's own plain-language description of what ran.
- Render all four `*_basis` fields. They are short strings; render them as a methodology disclosure
  block or a tooltip.
- Retitle: "Multi-Factor Simulation Engine" → "Deterministic Shock Proxy" (or similar). "Simulated
  Impact" → "Modeled Impact". "Run Simulation" → "Run Scenario". "Simulating…" → "Computing…".
- Fix the explainer at `:83`.
- Render `shock_inputs` and `units` when present.
- Separately, bind `result.scenario_description` for **all** scenarios, not just custom ones. The
  backend returns it at `analytics.py:1089`; the page only reads it for custom scenarios (`:493`)
  and hardcodes the rest at `:371-399` — e.g.
  `"Recession scenario based on 2008 financial crisis (-35% NIFTY shock)"`.
- Long term, Phase 5 issue 08 replaces the invented elasticities with estimated sector betas or
  parameter-free historical replay. Until then, the disclosure is the mitigation.

## Proof of done

- [ ] `methodology` is rendered on every scenario result.
- [ ] All four `*_basis` fields are rendered and legible.
- [ ] No occurrence of "simulation" remains where a deterministic proxy is meant, except where
      quoting the backend's own `methodology` text.
- [ ] Every scenario's description comes from `result.scenario_description`. A test asserts the
      page renders the API's string, not a local copy.
- [ ] `shock_inputs` and `units` render when present.
- [ ] A test asserts the string "Simulation" does not appear in the page's static copy.
- [ ] The page still communicates what the tool *does* do, so it does not read as
      under-powered. The disclosure should read as precision, not as an apology.

## Notes

The backend work here is already done. This is purely a frontend presentation fix, and it is the
cheapest large honesty win in the phase.

Refs: `../spec.md`, `frontend/src/app/dashboard/stress-testing/page.tsx:42,83,371-399,493,598,684,691,773,941`, `backend/app/services/analytics_engine.py:1072-1102`, `backend/app/api/analytics.py:1089`, `CONTEXT.md` §9.13
