"""Agent A pre-fix evidence: AnalyticsEngine GARCH/EGARCH horizon semantics."""
from __future__ import annotations
import asyncio
import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from arch import arch_model
from scipy import stats

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
sys.dont_write_bytecode = True
from app.services.analytics_engine import AnalyticsEngine


def check(name: str, backend: object, reference: object, atol: float, rtol: float) -> None:
    try:
        b = float(backend)
        r = float(reference)
        finite = math.isfinite(b) and math.isfinite(r)
        abs_diff = abs(b - r) if finite else math.inf
        rel_diff = abs_diff / max(abs(r), 1e-15) if finite else math.inf
        passed = finite and abs_diff <= atol + rtol * abs(r)
        print(f"CHECK|{name}|backend={b:.12g}|reference={r:.12g}|abs_diff={abs_diff:.12g}|rel_diff={rel_diff:.12g}|tolerance=atol:{atol:g},rtol:{rtol:g}|{'PASS' if passed else 'FAIL'}")
    except (TypeError, ValueError):
        print(f"CHECK|{name}|backend={backend!r}|reference={reference!r}|abs_diff=inf|rel_diff=inf|tolerance=atol:{atol:g},rtol:{rtol:g}|FAIL")


def arch_reference(returns: pd.Series, model_name: str, horizon: int) -> tuple[float, float, float]:
    scaled = returns.to_numpy(dtype=float) * 100.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fitted = arch_model(scaled, vol=model_name, p=1, q=1, dist="normal", rescale=False).fit(
            disp="off", show_warning=False, options={"maxiter": 100}
        )
        if model_name.upper() == "EGARCH" and horizon > 1:
            forecast = fitted.forecast(
                horizon=horizon, method="simulation", simulations=2000, random_state=100
            )
            raw = np.asarray(forecast.variance.values[-1])
            variance = raw.mean(axis=1) if raw.ndim > 1 else raw
        else:
            variance = fitted.forecast(horizon=horizon, method="analytic").variance.values[-1]
    variance = np.asarray(variance, dtype=float)
    cumulative_variance = float(np.sum(variance))
    horizon = len(variance)
    terminal_annualized = float(np.sqrt(max(0.0, cumulative_variance * 252.0 / horizon)) / 100.0)
    return_space = float(np.sqrt(max(0.0, cumulative_variance)) / 100.0)
    z = float(stats.norm.ppf(0.95))
    es = float(stats.norm.pdf(z) / 0.05)
    return terminal_annualized, -return_space * z, -return_space * es


def main() -> None:
    rng = np.random.default_rng(20260923)
    values = 0.00035 + 0.0105 * rng.standard_t(df=8, size=600)
    values[170:181] *= 3.0
    values[390:404] *= -4.0
    values = np.clip(values, -0.18, 0.18)
    returns = pd.Series(values, index=pd.bdate_range("2022-01-03", periods=600))
    engine = AnalyticsEngine()

    for horizon in (1, 5, 21):
        g = asyncio.run(engine._garch_forecast(returns, horizon))
        e = asyncio.run(engine._egarch_forecast(returns, horizon))
        g_ref, g_var_ref, g_cvar_ref = arch_reference(returns, "GARCH", horizon)
        e_ref, e_var_ref, e_cvar_ref = arch_reference(returns, "EGARCH", horizon)
        check(f"garch_h{horizon}_volatility", g["volatility_forecast"], g_ref, 1e-3, 5e-3)
        check(f"garch_h{horizon}_var", g["var_forecast"], g_var_ref, 6e-4, 1e-4)
        check(f"garch_h{horizon}_cvar", g["cvar_forecast"], g_cvar_ref, 6e-4, 1e-4)
        check(f"egarch_h{horizon}_volatility", e["volatility_forecast"], e_ref, 5e-3, 2e-2)
        check(f"egarch_h{horizon}_var", e["var_forecast"], e_var_ref, 1e-3, 5e-3)
        check(
            f"egarch_h{horizon}_finite",
            float(e["volatility_forecast"] is not None and e["var_forecast"] is not None),
            1.0,
            0.0,
            0.0,
        )
        print(
            f"OUTPUT|garch_h{horizon}|backend_var={g['var_forecast']}|reference_var={g_var_ref}"
        )
        print(
            f"OUTPUT|egarch_h{horizon}|backend={e['volatility_forecast']}|reference={e_ref}"
        )



if __name__ == "__main__":
    main()
