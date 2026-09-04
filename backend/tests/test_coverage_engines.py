"""
Comprehensive engine-level unit tests for AnalyticsEngine, IndicatorsService,
OptimizationService, RegimeService, and AlphaVantageService.
"""

import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import AnalyticsEngine
from app.services.indicators_service import _compute_sync
from app.services.optimization_service import optimize
from app.services.regime_service import classify


def _synth_df(days=252, n_assets=3):
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=days, freq="B")
    data = {}
    for i in range(n_assets):
        ticker = f"STOCK_{i}"
        price = 100.0 * np.exp(np.cumsum(np.random.normal(0.001, 0.012, days)))
        data[ticker] = price
    return pd.DataFrame(data, index=dates)


def _single_stock_df(days=100):
    dates = pd.date_range("2024-01-01", periods=days, freq="B")
    close = 100.0 * np.exp(np.cumsum(np.random.normal(0.0005, 0.015, days)))
    return pd.DataFrame({
        "Date": dates,
        "Open": close * 0.99,
        "High": close * 1.02,
        "Low": close * 0.98,
        "Close": close,
        "Volume": np.random.uniform(100000, 500000, days)
    })


@pytest.mark.asyncio
async def test_analytics_engine_deep_metrics():
    engine = AnalyticsEngine()
    df = _synth_df(252, 3)
    weights = {"STOCK_0": 0.4, "STOCK_1": 0.3, "STOCK_2": 0.3}

    # Concentration analysis
    conc = await engine.concentration_analysis(weights)
    assert "herfindahl_index" in conc
    assert "top_3" in conc

    # Risk scoring
    risk = await engine.risk_scoring(df, weights)
    assert "overall_score" in risk
    assert "components" in risk

    # Stress test
    st = await engine.stress_test(df, weights, "covid_crash_2020")
    assert "portfolio_impact" in st
    assert "max_drawdown" in st


def test_indicators_service_sync_compute():
    df = _single_stock_df(100)
    res = _compute_sync(df, ["rsi", "macd", "atr", "close_50_sma"])
    assert "rsi" in res.columns
    assert "macd" in res.columns
    assert "atr" in res.columns
    assert "close_50_sma" in res.columns


def test_optimization_service_all_strategies():
    df = _synth_df(252, 3)
    returns = df.pct_change().dropna()

    for strat in ["hrp", "min_vol", "max_sharpe", "min_cvar", "black_litterman"]:
        res = optimize(returns, strat)
        assert "weights" in res
        assert "expected_annual_return" in res
        assert "expected_annual_volatility" in res
        assert abs(sum(res["weights"].values()) - 1.0) < 1e-4

    # Test Black-Litterman with explicit views
    first_ticker = list(returns.columns)[0]
    second_ticker = list(returns.columns)[1]
    res_bl = optimize(
        returns,
        "black_litterman",
        views={first_ticker: 0.25},
        relative_views=[{"long": first_ticker, "short": second_ticker, "diff": 0.05}],
    )
    assert "weights" in res_bl
    assert abs(sum(res_bl["weights"].values()) - 1.0) < 1e-4
    assert res_bl["weights"][first_ticker] > 0


def test_regime_classification():
    dates = pd.date_range("2023-01-01", periods=300, freq="B")
    rets = pd.Series(np.random.normal(0.0005, 0.012, 300), index=dates)
    res = classify(rets)
    assert res is not None
    assert "current_regime" in res
    assert "stability_pct" in res
    assert len(res["states"]) == 3


def test_walk_forward_backtest():
    from app.services.backtest_service import run_walk_forward_backtest
    df = _synth_df(400, 3)
    returns = df.pct_change().dropna()
    res = run_walk_forward_backtest(
        returns=returns,
        strategy="hrp",
        rebalance_freq_days=21,
        lookback_days=100,
        transaction_cost_bps=10.0,
    )
    assert "cagr" in res
    assert "annualized_volatility" in res
    assert "equity_curve" in res
    assert len(res["equity_curve"]) > 0
    assert "rebalance_events" in res
    assert len(res["rebalance_events"]) > 0
    assert "drawdowns" in res

