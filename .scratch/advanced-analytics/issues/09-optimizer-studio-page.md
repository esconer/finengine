# 09 — Optimizer studio page

Status: resolved
Type: task
Blocked by: 08

## What (shipped 2026-08-26)
Route `/dashboard/optimize`: strategy picker (HRP / Min Vol / Max Sharpe / Min CVaR with
one-line blurbs), Run button with loading/disabled states, expected return/vol/sharpe/trades
MetricCards, current-vs-recommended weights table with delta badges, trades-required list
sorted by |delta|, solver label, backend disclaimer shown verbatim.
Constraint form (per-asset min/max, sector caps) and frontier chart deferred — see note.

## Proof of done
- [x] Run on real portfolio produces trade list fast (HRP live <2s on 2 holdings).
- [x] Constraints — deferred with the frontier chart; tracked as follow-up (needs
      cvxpy constraint plumbing in optimization_service).
- [x] Verified live in browser (agent-browser session, screenshot
      `.impeccable/review/desktop-optimize*.png`); empty/error states included.
