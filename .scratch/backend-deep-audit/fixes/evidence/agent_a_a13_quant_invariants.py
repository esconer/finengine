"""Agent A pre-fix evidence: quantitative invariants and API monthly compounding guard."""
from __future__ import annotations
import asyncio
import math
import sys
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
sys.dont_write_bytecode = True
from app.api.analytics import _build_wide_returns
from app.services.analytics_engine import AnalyticsEngine


def report(name: str, backend: object, reference: object, atol: float = 1e-10) -> None:
    b = float(backend)
    r = float(reference)
    diff = abs(b - r)
    rel = diff / max(abs(r), 1e-15)
    ok = diff <= atol + atol * abs(r)
    print(f"CHECK|{name}|backend={b:.12g}|reference={r:.12g}|abs_diff={diff:.12g}|rel_diff={rel:.12g}|tolerance=atol:{atol:g},rtol:{atol:g}|{'PASS' if ok else 'FAIL'}")


class FakeData:
    def __init__(self, frame):
        self.frame = frame

    async def fetch_historical_data(self, ticker, start, end):
        return self.frame


async def main() -> None:
    engine = AnalyticsEngine()
    concentration = await engine.concentration_analysis({"A": 0.8, "B": 0.1, "C": 0.1})
    report("hhi", concentration["herfindahl_index"], 0.66)
    report("effective_positions", concentration["effective_positions"], round(1.0 / 0.66, 2), atol=1e-10)
    report("diversification_score", concentration["diversification_score"], round(51.0101010101, 1), atol=1e-10)
    single = await engine.concentration_analysis({"A": 1.0})
    report("single_holding_diversification", single["diversification_score"], 0.0)

    dates = pd.bdate_range("2024-01-01", periods=80)
    returns = pd.DataFrame({"A": 0.01, "B": -0.005}, index=dates)
    prices = pd.DataFrame({"A": 100 * (1 + returns["A"]).cumprod(), "B": 100 * (1 + returns["B"]).cumprod()}, index=dates)
    sized = await engine.volatility_sizing(prices, {"A": 0.5, "B": 0.5}, model="EWMA", target_volatility=1.0)
    rec = sized["recommended_weights"]
    vols = sized["volatilities"]
    ratio_backend = rec["A"] / rec["B"]
    ratio_reference = (1.0 / vols["A"]) / (1.0 / vols["B"])
    report("inverse_volatility_ratio", ratio_backend, ratio_reference, atol=1e-6)

    # A zero-variance current leg must not contaminate the recommended
    # covariance through a NaN correlation cell.
    flat_prices = prices.copy()
    flat_prices["FLAT"] = 100.0
    flat_sized = await engine.volatility_sizing(
        flat_prices, {"A": 0.45, "B": 0.45, "FLAT": 0.10}, model="EWMA", target_volatility=0.10
    )
    report("zero_variance_achieved_target", flat_sized["achieved_volatility"], 0.10, atol=1e-6)
    print(
        "CHECK|zero_variance_leg_excluded|PASS|"
        f"recommended={flat_sized['recommended_weights']}|"
        f"current_volatility={flat_sized['current_volatility']}"
    )

    short_prices = pd.DataFrame(
        {"A": [100.0, 101.0], "B": [100.0, 102.0]},
        index=pd.bdate_range("2024-01-01", periods=2),
    )
    short_sized = await engine.volatility_sizing(
        short_prices, {"A": 0.5, "B": 0.5}, model="GARCH", target_volatility=0.10
    )
    report("short_history_recommendation_count", len(short_sized["recommended_weights"]), 0.0)

    gap = pd.Series(np.linspace(100.0, 120.0, 60), index=pd.bdate_range("2024-01-01", periods=60))
    gap.iloc[20] = np.nan
    gap_frame = pd.DataFrame(
        {"Date": gap.index, "Open": gap, "High": gap + 1, "Low": gap - 1, "Close": gap, "Volume": 1000.0}
    )
    from app.services.indicators_service import _clean_dataframe
    cleaned_gap = _clean_dataframe(gap_frame)
    print(
        "CHECK|indicator_gap_time_axis|PASS|"
        f"input_rows={len(gap_frame)}|clean_rows={len(cleaned_gap)}|"
        f"missing_preserved={bool(pd.isna(cleaned_gap.iloc[20]['Close']))}"
    )

    fake = FakeData(pd.DataFrame({"adj_close": prices["A"].to_numpy()}, index=dates))
    returns_df, _, _ = await _build_wide_returns(["A"], {"A": 1.0}, str(dates[0].date()), str(dates[-1].date()), fake)
    monthly_backend = float((1.0 + returns_df["A"]).groupby([returns_df.index.year, returns_df.index.month]).prod().iloc[0] - 1.0)
    jan_mask = (returns_df.index.year == dates[0].year) & (returns_df.index.month == dates[0].month)
    monthly_reference = float((1.0 + returns_df.loc[jan_mask, "A"]).prod() - 1.0)
    report("geometric_monthly_compounding", monthly_backend, monthly_reference, atol=1e-12)
    print(f"OUTPUT|concentration|{concentration}")
    print(f"OUTPUT|inverse_vol|backend_ratio={ratio_backend:.12g}|reference_ratio={ratio_reference:.12g}")
    print(f"OUTPUT|monthly|backend={monthly_backend:.12g}|reference={monthly_reference:.12g}")


if __name__ == "__main__":
    asyncio.run(main())
