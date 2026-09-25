"""Independent v4 export audit.

Recomputes the invariants from the artifact itself rather than trusting the
backend. Run from the repo root:

    uv run --project backend python .scratch/ai-context-v3-remediation-2026-09/evidence/audit_v4.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARTIFACT = HERE / "v4-export.json"

fail: list[str] = []
warn: list[str] = []
ok: list[str] = []


def check(cond: bool, msg: str, hard: bool = True) -> bool:
    if cond:
        ok.append(msg)
    elif hard:
        fail.append(msg)
    else:
        warn.append(msg)
    return cond


def finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def main() -> int:
    raw = ARTIFACT.read_text(encoding="utf-8")
    doc = json.loads(raw)
    sections = doc.get("sections", {})

    # ---- envelope -------------------------------------------------------
    check(doc.get("schema_version") == "2.0", f"schema_version is 2.0 (got {doc.get('schema_version')!r})")
    check(doc.get("generated_at") and doc.get("completed_at"), "envelope carries generated_at and completed_at")
    check(
        str(doc.get("generated_at")) <= str(doc.get("completed_at")),
        "generated_at <= completed_at",
    )
    check(doc.get("snapshot_consistency") in {"best_effort", "frozen"}, "snapshot_consistency is a known value")
    check(len(doc.get("scope", [])) == len(sections), "scope and sections have equal length")

    for name, sec in sections.items():
        # ---- status vocabulary ------------------------------------------
        st = sec.get("status")
        check(st in {"available", "partial", "unavailable"}, f"[{name}] status {st!r} is in the public vocabulary")
        check("not_requested" not in sec, f"[{name}] does not use the removed not_requested status")

        # ---- error omission ---------------------------------------------
        if st == "available":
            check("error" not in sec or sec.get("error") is None,
                  f"[{name}] available section carries no error key", hard=False)

        # ---- coverage ----------------------------------------------------
        cov = sec.get("coverage")
        if isinstance(cov, dict):
            cs = cov.get("status")
            check(cs in {"complete", "partial", "unavailable", "unknown"},
                  f"[{name}] coverage.status {cs!r} is in the coverage vocabulary")
            if "weight_basis" in cov:
                wb = cov["weight_basis"]
                check(wb == "active_weights_renormalized_to_100_percent",
                      f"[{name}] weight_basis is the single canonical literal")
                missing = cov.get("missing_tickers") or []
                check(bool(missing),
                      f"[{name}] weight_basis only present with missing_tickers")
            if cs == "complete":
                check(not (cov.get("missing_tickers") or []),
                      f"[{name}] complete coverage has no missing tickers")

        # ---- no NaN/Infinity anywhere -----------------------------------
        def walk(node, path=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")
            elif isinstance(node, float) and not math.isfinite(node):
                fail.append(f"[{name}] non-finite number at {path}: {node!r}")

        walk(sec.get("data"), "data")

    # ---- portfolio arithmetic -------------------------------------------
    pf = sections.get("portfolio", {}).get("data", {})
    positions = pf.get("positions") or []
    if positions:
        total = pf.get("total_value")
        mv_sum = sum(p.get("market_value") or 0 for p in positions)
        if finite(total):
            check(abs(mv_sum - total) <= max(1e-6, abs(total) * 1e-9),
                  f"portfolio market values sum to total_value ({mv_sum} vs {total})")
        w_sum = sum(p.get("weight") or 0 for p in positions)
        check(abs(w_sum - 1.0) <= 1e-6, f"portfolio weights sum to 1.0 (got {w_sum})")
        covered = sections.get("portfolio", {}).get("coverage") or {}
        req = covered.get("requested_tickers") or []
        got = [p.get("ticker") for p in positions]
        check(len(got) == len(req), f"portfolio delivers all {len(req)} requested positions (got {len(got)})")

    # ---- sector rounding ------------------------------------------------
    conc = sections.get("concentration", {}).get("data", {})
    by_sector = conc.get("by_sector") or {}
    if by_sector:
        pub = conc.get("by_sector_published_total")
        if finite(pub):
            check(abs(sum(by_sector.values()) - pub) <= 1e-9,
                  "published sector total equals the sum of published sector weights")
        res = conc.get("by_sector_rounding_residual")
        if finite(res) and finite(pub):
            check(abs(res - (1.0 - pub)) <= 1e-9, "rounding residual equals 1.0 - published total")
        check(conc.get("data_status") != "complete",
              "concentration data_status is not a coverage word", hard=False)

    # ---- volatility sizing ----------------------------------------------
    vs = sections.get("volatility_sizing", {}).get("data", {})
    if vs and vs.get("recommended_weights"):
        gross = sum(vs["recommended_weights"].values())
        ex = vs.get("execution") or {}
        if finite(ex.get("gross_exposure")):
            check(abs(ex["gross_exposure"] - gross) <= 1e-6,
                  f"execution.gross_exposure matches the recommended weights sum ({ex['gross_exposure']} vs {gross})")
        if ex.get("execution_eligible") is False:
            check("executable_weights" not in vs,
                  "a non-executable target publishes no executable_weights", hard=False)
        trades = vs.get("trades") or {}
        price = (vs.get("sizing_basis") or {}).get("sizing_price") or {}
        zero_amount_nonzero_shares = 0
        for t, tr in trades.items():
            amt, sh = tr.get("amount"), tr.get("shares_delta")
            px = price.get(t)
            if amt == 0 and sh not in (None, 0):
                zero_amount_nonzero_shares += 1
            if finite(amt) and finite(px) and px and sh not in (None, 0):
                resid = tr.get("rounding_residual")
                if finite(resid):
                    check(abs(amt - (sh * px + resid)) <= 0.01,
                          f"[vol_sizing] {t} amount == shares*price + residual")
            # A notional smaller than one share is a real outcome, not a bug --
            # but it must never be published as a silent `0 shares`. It has to
            # carry an explicit status and keep its notional.
            if sh == 0 and finite(amt) and abs(amt) > 0:
                check(tr.get("status") in {"below_minimum_notional", "price_unavailable"},
                      f"[vol_sizing] {t} has 0 shares with a material amount and an explicit status")
                check(abs(amt) > 0, f"[vol_sizing] {t} preserves its notional alongside 0 shares")
        check(zero_amount_nonzero_shares == 0, "no trade with zero amount carries non-zero shares")

    # ---- pairs ----------------------------------------------------------
    pr = sections.get("pairs", {}).get("data", {})
    if pr:
        check(pr.get("test_roles") is not None, "pairs publish dual-test roles")
        check(pr.get("universe_scope") is not None, "pairs publish universe_scope")
        if pr.get("depth_status") == "partial":
            check(pr.get("data_status") == "partial",
                  "a depth-limited pairs scan reports data_status=partial")

    # ---- monte carlo ----------------------------------------------------
    mc = sections.get("monte_carlo", {}).get("data", {})
    if mc and finite(mc.get("prob_success")):
        check(mc.get("success_definition") == "terminal_wealth_above_target",
              "monte carlo declares terminal success semantics")
        check(0.0 <= mc["prob_success"] <= 1.0, "prob_success in [0,1]")
        check(mc.get("currency") is not None, "monte carlo declares a currency", hard=False)

    # ---- regime ---------------------------------------------------------
    rg = sections.get("regime", {}).get("data", {})
    if rg and rg.get("regime_probabilities"):
        check(rg.get("probability_unit") == "percent_0_to_100", "regime declares percentage units")
        probs = rg["regime_probabilities"]
        if isinstance(probs, dict):
            total = sum(v for v in probs.values() if finite(v))
            check(abs(total - 100.0) <= 0.5, f"regime probabilities sum to ~100 (got {total})")
        check(rg.get("benchmark", {}).get("symbol") is not None, "regime names its benchmark", hard=False)

    # ---- india ----------------------------------------------------------
    ind = sections.get("india_flows", {}).get("data", {})
    if ind:
        cc = ind.get("component_coverage") or {}
        flows = cc.get("institutional_flows") or {}
        if flows:
            check("weight_basis" not in flows,
                  "market-wide institutional flows claim no weight basis")
            check(flows.get("scope") == "market_wide", "institutional flows are market_wide scope")
        check(ind.get("as_of_semantics") is not None, "india composite declares as_of semantics", hard=False)

    # ---- dashboard ------------------------------------------------------
    dash_sec = sections.get("dashboard", {})
    dash = dash_sec.get("data", {})
    if dash:
        comps = dash.get("components") or {}
        perf = comps.get("performance_history") or {}
        hc = perf.get("history_coverage") or {}
        if hc:
            check(hc.get("requested_days") is not None and hc.get("observation_count") is not None,
                  "performance history discloses requested vs delivered counts")
            ratio = hc.get("coverage_ratio")
            if finite(ratio) and ratio < 0.9:
                # The authoritative status is the SECTION's, not a payload field.
                check(perf.get("status") in {"partial", "unavailable"},
                      f"a {ratio:.0%}-covered performance window is not reported as complete")
                check(dash_sec.get("status") in {"partial", "unavailable"},
                      f"the dashboard section reflects its {ratio:.0%}-covered performance leg")
                check(bool(perf.get("warnings")),
                      "a short/stale performance window raises an explicit warning")
        comp_as_of = dash.get("component_as_of") or {}
        if comp_as_of:
            vals = [v.get("as_of") for v in comp_as_of.values() if v and v.get("as_of")]
            if vals and dash_sec.get("as_of"):
                check(str(dash_sec["as_of"]) == min(vals),
                      "dashboard as_of equals the oldest component observation")

    # ---- report ---------------------------------------------------------
    print(f"sections: {len(sections)}")
    print(f"PASS {len(ok)}   WARN {len(warn)}   FAIL {len(fail)}")
    for f in fail:
        print("  FAIL:", f)
    for w in warn:
        print("  warn:", w)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
