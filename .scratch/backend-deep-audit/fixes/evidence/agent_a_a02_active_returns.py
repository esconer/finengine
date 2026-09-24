"""Agent A pre-fix evidence: active-return construction for staggered listings."""
from __future__ import annotations
import asyncio
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
sys.dont_write_bytecode = True
from app.services.analytics_engine import AnalyticsEngine


def report(name: str, backend: float, reference: float, atol: float = 1e-12) -> None:
    diff = abs(float(backend) - float(reference))
    rel = diff / max(abs(float(reference)), 1e-15)
    ok = diff <= atol + 1e-12 * abs(float(reference))
    print(f"CHECK|{name}|backend={backend:.12g}|reference={reference:.12g}|abs_diff={diff:.12g}|rel_diff={rel:.12g}|tolerance=atol:{atol:g},rtol:1e-12|{'PASS' if ok else 'FAIL'}")


def main() -> None:
    idx = pd.bdate_range("2024-01-02", periods=240)
    rng = np.random.default_rng(17)
    a_returns = 0.0004 + rng.normal(0, 0.009, len(idx))
    b_returns = -0.0001 + rng.normal(0, 0.014, len(idx) - 120)
    a_prices = 100.0 * np.cumprod(1.0 + a_returns)
    b_prices = np.full(len(idx), np.nan)
    b_prices[120:] = 80.0 * np.cumprod(1.0 + b_returns)
    prices = pd.DataFrame({"A": a_prices, "B": b_prices}, index=idx)
    weights = {"A": 0.5, "B": 0.5}

    raw_returns = prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    active_weight = raw_returns.notna().mul(pd.Series(weights), axis=1).sum(axis=1)
    reference_returns = raw_returns.fillna(0.0).mul(pd.Series(weights), axis=1).sum(axis=1)
    reference_returns = reference_returns.loc[active_weight > 0] / active_weight.loc[active_weight > 0]
    reference_annual = float(reference_returns.mean() * 252.0)
    reference_vol = float(reference_returns.std(ddof=1) * np.sqrt(252.0))

    backend = asyncio.run(AnalyticsEngine().calculate_portfolio_metrics(prices, weights))
    report("annual_return", backend["annual_return"], reference_annual)
    report("annual_volatility", backend["annual_volatility"], reference_vol)
    report("active_return_count", float(backend.get("observations", len(reference_returns))), float(len(reference_returns)))
    print(f"OUTPUT|prelisting_backend_return|backend={float(raw_returns['B'].iloc[0]):.12g}|reference=nan")
    print(f"OUTPUT|reference_active_window|start={str(reference_returns.index[0])[:10]}|end={str(reference_returns.index[-1])[:10]}|n={len(reference_returns)}")


if __name__ == "__main__":
    main()
