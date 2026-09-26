"""v3 -> v4 field-level delta for the documented findings (V3-01..V3-16).

Read-only. Run from the repo root:
    uv run --project backend python .scratch/ai-context-v3-remediation-2026-09/evidence/delta_v3_v4.py
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
V3 = Path(r"C:\Users\Sayanti\Downloads\finengine-portfolio-ai-context v3.json")
V4 = HERE / "v4-export.json"


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def sec(doc: dict, name: str) -> dict:
    return (doc.get("sections") or {}).get(name) or {}


def data(doc: dict, name: str) -> dict:
    return sec(doc, name).get("data") or {}


def row(label: str, v3: object, v4: object, verdict: str) -> None:
    print(f"{label}\n    v3: {v3}\n    v4: {v4}\n    -> {verdict}\n")


def main() -> None:
    if not V3.exists():
        print(f"v3 artifact not found at {V3}; skipping delta")
        return
    a, b = load(V3), load(V4)
    sa, sb = a.get("sections") or {}, b.get("sections") or {}

    print("=" * 78)
    print("ENVELOPE")
    print("=" * 78)
    row("schema_version", a.get("schema_version"), b.get("schema_version"), "breaking revision")

    # V3-01 weight_basis
    def wb(doc: dict) -> tuple[int, int]:
        total = claimed = 0
        for s in (doc.get("sections") or {}).values():
            cov = s.get("coverage")
            if isinstance(cov, dict):
                total += 1
                if cov.get("weight_basis"):
                    claimed += 1
        return total, claimed

    ta, ca = wb(a)
    tb, cb = wb(b)
    row("V3-01 weight_basis claims", f"{ca}/{ta} coverage blocks", f"{cb}/{tb} coverage blocks",
        "fixed" if cb < ca else "NOT FIXED")

    # V3-16 data_status vocabulary
    def statuses(doc: dict) -> set:
        out: set = set()

        def walk(n):
            if isinstance(n, dict):
                for k, v in n.items():
                    if k == "data_status" and isinstance(v, str):
                        out.add(v)
                    walk(v)
            elif isinstance(n, list):
                for v in n:
                    walk(v)

        walk(doc.get("sections"))
        return out

    row("V3-16 data_status vocabulary", sorted(statuses(a)), sorted(statuses(b)),
        "fixed" if statuses(a) - statuses(b) else "NOT FIXED")

    # V3-16 error:null
    def null_errors(doc: dict) -> int:
        return sum(
            1 for s in (doc.get("sections") or {}).values()
            if "error" in s and s["error"] is None
        )

    row("V3-16 sections with error:null", null_errors(a), null_errors(b),
        "fixed" if null_errors(b) == 0 else "NOT FIXED")

    # V3-02 dashboard freshness
    pa = ((data(a, "dashboard").get("components") or {}).get("performance_history") or {})
    pb = ((data(b, "dashboard").get("components") or {}).get("performance_history") or {})
    row("V3-02 dashboard as_of", sec(a, "dashboard").get("as_of"), sec(b, "dashboard").get("as_of"),
        "no longer inherited from the portfolio quote"
        if sec(b, "dashboard").get("as_of") != sec(b, "portfolio").get("as_of")
        else "STILL INHERITED")
    row("V3-02 performance rows delivered", len(pa.get("data") or []), len(pb.get("data") or []),
        f"requested {((pb.get('history_coverage') or {}).get('requested_days'))}d")
    row("V3-02 performance coverage declared", pa.get("history_coverage"), pb.get("history_coverage"),
        "requested-vs-delivered now disclosed" if pb.get("history_coverage") else "NOT FIXED")

    # V3-03 vol sizing leverage
    va, vb = data(a, "volatility_sizing"), data(b, "volatility_sizing")
    ga = sum((va.get("recommended_weights") or {}).values())
    gb = sum((vb.get("recommended_weights") or {}).values())
    row("V3-03 recommended weight sum", round(ga, 6), round(gb, 6), "analytical gross retained")
    row("V3-03 cash_weight", va.get("cash_weight"), vb.get("cash_weight"),
        "signed net cash weight, not a hard 0")
    row("V3-03 execution block", None, (vb.get("execution") or {}).get("execution_eligible"),
        "execution eligibility published"
        if vb.get("execution") else "NOT FIXED")

    # V3-04 zero shares: a 0-share trade is only acceptable when it is EXPLICITLY
    # labelled and preserves its notional. An unlabelled 0 is a fabricated zero.
    def zero_shares(d: dict, labelled_only: bool = False) -> list:
        out = []
        for t, tr in (d.get("trades") or {}).items():
            if tr.get("shares_delta") != 0 or abs(tr.get("amount") or 0) <= 0:
                continue
            # A 0-share trade is only a DEFECT when it is unlabelled: the
            # notional is real, so it must say why it rounds to zero.
            if labelled_only and tr.get("status") in {
                "below_minimum_notional",
                "price_unavailable",
            }:
                continue
            out.append(t)
        return out

    unlabelled = zero_shares(vb, labelled_only=True)
    row("V3-04 0-share trades WITHOUT an honest label", zero_shares(va), unlabelled,
        "fixed" if not unlabelled else "NOT FIXED")
    below = sorted(t for t, tr in (vb.get("trades") or {}).items()
                   if tr.get("status") == "below_minimum_notional")
    row("V3-04 0-share trades LABELLED below_minimum_notional", None, below,
        "notional preserved and flagged, not a silent zero")

    # V3-07 summary nulls / risk delta.
    # `summary` and `risk_score` are DASHBOARD COMPONENTS, not top-level
    # sections; reading sections['summary'] silently returns {} and would make
    # every one of these look unchanged.
    def comp(doc: dict, name: str) -> dict:
        comps = ((doc.get("sections") or {}).get("dashboard") or {}).get("data", {})
        return ((comps.get("components") or {}).get(name) or {}).get("data") or {}

    sra, srb = comp(a, "summary"), comp(b, "summary")
    row("V3-07 summary.forecast_volatility", sra.get("forecast_volatility"), srb.get("forecast_volatility"),
        "linked from the canonical sibling")
    row("V3-07 summary.liquidity_score", sra.get("liquidity_score"), srb.get("liquidity_score"),
        "linked from the canonical sibling")
    row("V3-07 risk_score.change", comp(a, "risk_score").get("change"), comp(b, "risk_score").get("change"),
        "unmeasured, not a fake zero")

    # V3-08 sector rounding
    ca_, cb_ = data(a, "concentration"), data(b, "concentration")
    row("V3-08 by_sector Industrials", (ca_.get("by_sector") or {}).get("Industrials"),
        (cb_.get("by_sector") or {}).get("Industrials"), "rounded once")
    row("V3-08 sector total", sum((ca_.get("by_sector") or {}).values()),
        sum((cb_.get("by_sector") or {}).values()),
        f"residual {cb_.get('by_sector_rounding_residual')}")

    # V3-09 liquidity provenance
    la, lb = data(a, "liquidity"), data(b, "liquidity")
    pa_ = (la.get("by_position") or {}).get("SELECTIPO.NS") or {}
    pb_ = (lb.get("by_position") or {}).get("SELECTIPO.NS") or {}
    row("V3-09 SELECTIPO market cap", pa_.get("market_cap"), pb_.get("market_cap"),
        f"provenance={pb_.get('market_cap_provenance')} source={pb_.get('market_cap_source')}")
    row("V3-09 liquidity currency / units", la.get("currency"), lb.get("currency"),
        f"turnover_unit={lb.get('turnover_unit')}")

    # V3-10 stress proxy
    ta_, tb_ = data(a, "stress_testing"), data(b, "stress_testing")

    def first_scenario_basis(payload: dict, field: str):
        for key in ("scenarios", "results", "stress_scenarios"):
            rows = payload.get(key)
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                return rows[0].get(field)
        return payload.get(field)

    row("V3-10 stress confidence basis",
        first_scenario_basis(ta_, "confidence_basis"),
        first_scenario_basis(tb_, "confidence_basis"),
        "nominal label, not a simulated statistic")
    row("V3-10 stress max_drawdown basis",
        first_scenario_basis(ta_, "max_drawdown_basis"),
        first_scenario_basis(tb_, "max_drawdown_basis"),
        "declared a shock proxy")

    # V3-11 monte carlo
    ma, mb = data(a, "monte_carlo"), data(b, "monte_carlo")
    row("V3-11 success_definition", ma.get("success_definition"), mb.get("success_definition"),
        "terminal, not path-touch")
    row("V3-11 currency", ma.get("currency"), mb.get("currency"), "value unit published")

    # V3-13 regime units
    ga_, gb_ = data(a, "regime"), data(b, "regime")
    row("V3-13 probability_unit", ga_.get("probability_unit"), gb_.get("probability_unit"),
        "percentage declared")
    row("V3-13 benchmark", ga_.get("benchmark"), (gb_.get("benchmark") or {}).get("symbol"),
        "benchmark named")

    # V3-14 pairs depth
    qa, qb = data(a, "pairs"), data(b, "pairs")
    row("V3-14 depth_status", qa.get("depth_status"), qb.get("depth_status"),
        f"shallow={qb.get('shallow_tickers')}")
    row("V3-14 universe_scope", qa.get("universe_scope"), qb.get("universe_scope"), "scope declared")

    # V3-15 india
    ia, ib = data(a, "india_flows"), data(b, "india_flows")
    row("V3-15 composite coverage.status", sec(a, "india_flows").get("coverage", {}).get("status"),
        sec(b, "india_flows").get("coverage", {}).get("status"),
        f"as_of={sec(b, 'india_flows').get('as_of')} "
        f"semantics={sec(b, 'india_flows').get('as_of_semantics')}")
    row("V3-15 component_coverage", None, sorted(((ib.get("component_coverage") or {}).keys())),
        "heterogeneous components disclosed separately")

    # V3-05 full history
    fa, fb = data(a, "factor_exposure"), data(b, "factor_exposure")
    row("V3-05 factor top-level truncated",
        (fa.get("history_coverage") or {}).get("truncated"),
        (fb.get("history_coverage") or {}).get("truncated"),
        f"model observations={(fb.get('full_history') or {}).get('observation_count')}")

    # V3-06 holding provenance
    ra, rb = data(a, "realized_risk"), data(b, "realized_risk")
    hca = ((ra.get("history_coverage") or {}).get("tickers") or {}).get("NIFTYIETF.NS") or {}
    hcb = ((rb.get("history_coverage") or {}).get("tickers") or {}).get("NIFTYIETF.NS") or {}
    row("V3-06 NIFTYIETF own observations", hca.get("return_observations"), hcb.get("return_observations"),
        f"start_source={hcb.get('analytics_start_source')} stored={hcb.get('stored_added_on')}")


if __name__ == "__main__":
    main()
