"""Agent A pre-fix evidence: raw versus constrained EVT GPD fit disclosure."""
from __future__ import annotations
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
sys.dont_write_bytecode = True
from app.services.tail_risk_service import TailRiskService


def report(name: str, backend: object, reference: object, atol: float = 1e-6) -> None:
    try:
        b = float(backend)
        r = float(reference)
        diff = abs(b - r)
        rel = diff / max(abs(r), 1e-15)
        ok = math.isfinite(b) and diff <= atol + 1e-6 * abs(r)
        print(f"CHECK|{name}|backend={b:.12g}|reference={r:.12g}|abs_diff={diff:.12g}|rel_diff={rel:.12g}|tolerance=atol:{atol:g},rtol:1e-6|{'PASS' if ok else 'FAIL'}")
    except (TypeError, ValueError):
        print(f"CHECK|{name}|backend={backend!r}|reference={reference!r}|abs_diff=inf|rel_diff=inf|tolerance=atol:{atol:g},rtol:1e-6|FAIL")


def main() -> None:
    xi = -0.8
    beta = 0.01
    probabilities = (np.arange(10) + 0.5) / 10.0
    excess = beta / xi * ((1.0 - probabilities) ** (-xi) - 1.0)
    losses = np.concatenate([np.zeros(190), 0.02 + excess])
    returns = pd.Series(-losses)
    result = TailRiskService.calculate_evt_pot_var_es(
        returns, confidence_level=0.99, threshold_quantile=0.90
    )

    u = float(np.percentile(losses, 90.0))
    exceed = losses[losses > u] - u
    raw_xi, _, raw_beta = stats.genpareto.fit(exceed, floc=0.0)
    ratio = (len(losses) / len(exceed)) * 0.01
    if abs(raw_xi) > 1e-6:
        raw_var_loss = u + (float(raw_beta) / raw_xi) * (ratio ** (-raw_xi) - 1.0)
    else:
        raw_var_loss = u - float(raw_beta) * np.log(ratio)
    raw_es_loss = (raw_var_loss + float(raw_beta) - raw_xi * u) / (1.0 - raw_xi)

    report("raw_fitted_xi", result.get("gpd_shape_xi_raw", result.get("gpd_shape_xi")), float(raw_xi), atol=1e-6)
    report("raw_evt_var", result.get("evt_pot_var_unconstrained", result.get("evt_pot_var_99")), -float(raw_var_loss), atol=1e-6)
    report("raw_evt_es", result.get("evt_pot_es_unconstrained", result.get("evt_pot_es_99")), -float(raw_es_loss), atol=1e-6)
    for field in ("gpd_shape_xi_raw", "gpd_shape_xi_constrained", "metrics_constrained", "metrics_valid"):
        print(f"CHECK|field_{field}|backend={result.get(field, '<missing>')!r}|reference='present'|abs_diff=0|rel_diff=0|tolerance=atol:0,rtol:0|{'PASS' if field in result else 'FAIL'}")
    print(f"OUTPUT|backend|{result}")
    print(f"OUTPUT|reference|xi={float(raw_xi):.12g},beta={float(raw_beta):.12g},var={-float(raw_var_loss):.12g},es={-float(raw_es_loss):.12g}")


if __name__ == "__main__":
    main()
