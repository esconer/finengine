"""Agent A pre-fix evidence: configurable tail confidence field names."""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
sys.dont_write_bytecode = True
from app.services.tail_risk_service import TailRiskService


def main() -> None:
    returns = pd.Series(np.random.default_rng(811).standard_t(df=5, size=500) * 0.015 + 0.0002)
    confidence = 0.95
    threshold_q = 0.90
    result = TailRiskService.calculate_evt_pot_var_es(
        returns, confidence_level=confidence, threshold_quantile=threshold_q
    )

    losses = -returns.to_numpy(dtype=float)
    hist_var = float(np.percentile(losses, confidence * 100.0))
    hist_tail = losses[losses >= hist_var]
    hist_es = float(hist_tail.mean()) if len(hist_tail) else hist_var
    threshold = float(np.percentile(losses, threshold_q * 100.0))
    exceed = losses[losses > threshold] - threshold
    xi, _, beta = stats.genpareto.fit(exceed, floc=0.0)
    beta = float(max(beta, 1e-6))
    xi_used = float(np.clip(xi, -0.5, 0.95))
    ratio = (len(losses) / len(exceed)) * (1.0 - confidence)
    if abs(xi_used) > 1e-6:
        var_loss = threshold + beta / xi_used * (ratio ** (-xi_used) - 1.0)
    else:
        var_loss = threshold - beta * np.log(ratio)
    es_loss = (var_loss + beta - xi_used * threshold) / (1.0 - xi_used)
    var_loss = max(var_loss, threshold, hist_var * 0.9)
    es_loss = max(es_loss, var_loss)
    reference = {
        "evt_pot_var": -float(var_loss),
        "evt_pot_es": -float(es_loss),
        "historical_var": -float(hist_var),
        "historical_es": -float(hist_es),
    }
    neutral = {key: result.get(key, float("nan")) for key in reference}
    for key in neutral:
        b = neutral[key]
        r = reference[key]
        try:
            diff = abs(float(b) - float(r))
            rel = diff / max(abs(float(r)), 1e-15)
            ok = diff <= 1e-6 + 1e-6 * abs(float(r))
        except (TypeError, ValueError):
            diff, rel, ok = float("inf"), float("inf"), False
        print(f"CHECK|{key}|backend={b}|reference={r}|abs_diff={diff}|rel_diff={rel}|tolerance=atol:1e-6,rtol:1e-6|{'PASS' if ok else 'FAIL'}")
    misleading = [key for key in ("evt_pot_var_99", "evt_pot_es_99", "historical_var_99", "historical_es_99") if key in result]
    print(f"CHECK|no_hardcoded_99_fields_for_95|backend={misleading}|reference=[]|abs_diff={len(misleading)}|rel_diff=0|tolerance=atol:0,rtol:0|{'PASS' if not misleading else 'FAIL'}")
    print(f"OUTPUT|confidence|requested=0.95|returned={result.get('confidence_level')}")


if __name__ == "__main__":
    main()
