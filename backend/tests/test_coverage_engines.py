"""
Comprehensive engine-level unit tests for AnalyticsEngine, IndicatorsService,
OptimizationService, RegimeService, and AlphaVantageService.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch
import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import AnalyticsEngine
from app.services.indicators_service import IndicatorsService, _compute_sync
from app.services.optimization_service import optimize
from app.services.regime_service import classify, detect_regime


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

    for strat in ["hrp", "min_vol", "max_sharpe", "min_cvar"]:
        res = optimize(returns, strat)
        assert "weights" in res
        assert "expected_annual_return" in res
        assert "expected_annual_volatility" in res
        assert abs(sum(res["weights"].values()) - 1.0) < 1e-4


def test_regime_classification():
    dates = pd.date_range("2023-01-01", periods=300, freq="B")
    rets = pd.Series(np.random.normal(0.0005, 0.012, 300), index=dates)
    res = classify(rets)
    assert res is not None
    assert "current_regime" in res
    assert "stability_pct" in res
    assert len(res["states"]) == 3
