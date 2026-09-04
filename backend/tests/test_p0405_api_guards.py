"""P0-4/P0-5 contract tests: API crash guards.

Regression gates for BACKEND_REVIEW P0-4 (inspect NameError dropped all
liquidity price data) and P0-5 (empty-portfolio AttributeError,
market_value-only monte-carlo fallback, uncapped num_paths DoS).
Direct route-function calls with mocks; no DB, no network.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pandas as pd
import pytest

from app.api.analytics import (
    get_delivery_anomalies,
    get_liquidity_metrics,
    run_monte_carlo,
)
from app.models.database import PortfolioPosition


def _pos(ticker="TCS.NS", market_value=10000.0, quantity=100.0, last_price=100.0):
    return PortfolioPosition(
        ticker=ticker, weight=1.0, quantity=quantity, buy_price=100.0,
        last_price=last_price, market_value=market_value,
        sector="IT", industry="Software",
    )


def _mock_db(positions):
    db = AsyncMock()
    res = MagicMock()
    res.scalars.return_value.all.return_value = positions
    db.execute.return_value = res
    return db


def _liq_df(rows=40):
    dates = pd.date_range("2026-01-01", periods=rows, freq="B")
    close = 100.0 + __import__("numpy").cumsum(__import__("numpy").random.normal(0, 1, rows))
    return pd.DataFrame({"adj_close": close, "volume": [500000.0] * rows}, index=dates)


async def test_liquidity_consumes_async_fetch():
    df = _liq_df()
    mock_ds = Mock()
    mock_ds.fetch_historical_data = AsyncMock(return_value=df)
    mock_ds.fetch_quote = AsyncMock(return_value={"market_cap": 1e9})
    mock_engine = Mock()
    mock_engine.liquidity_analysis = AsyncMock(return_value={
        "overall_score": 8.0, "liquidation_time_days": "1-2",
        "risk_level": "Low", "by_position": {"TCS.NS": {}}, "volume_stats": {},
    })
    res = await get_liquidity_metrics(
        db=_mock_db([_pos()]), data_service=mock_ds, analytics_engine=mock_engine
    )
    assert res["overall_score"] == 8.0
    assert "TCS.NS" in res["by_position"]
    mock_engine.liquidity_analysis.assert_awaited_once()


async def test_delivery_anomalies_empty_portfolio_no_crash():
    res = await get_delivery_anomalies(
        tickers=None, lookback_days=20, sigma_threshold=2.0, db=_mock_db([])
    )
    assert res["count"] == 0
    assert res["anomalies"] == []


async def test_monte_carlo_initial_value_qty_price_fallback():
    rets = pd.Series([0.001] * 100)
    with patch("app.api.analytics._build_wide_returns", new=AsyncMock(return_value=(None, rets, {}))), \
         patch("app.api.analytics.simulate_goal", return_value={"ok": True}) as sim:
        await run_monte_carlo(
            body={"target_value": 20000.0, "horizon_years": 3},
            tickers="TCS.NS",
            db=_mock_db([_pos(market_value=0.0, quantity=100.0, last_price=50.0)]),
            data_service=Mock(),
        )
    assert sim.call_args.kwargs["initial_value"] == pytest.approx(5000.0)


async def test_monte_carlo_num_paths_clamped():
    rets = pd.Series([0.001] * 100)
    seen = []

    def _fake_sim(**kwargs):
        seen.append(kwargs["num_paths"])
        return {"ok": True}

    async def _run(n):
        body = {"target_value": 20000.0, "horizon_years": 3, "initial_value": 10000.0}
        if n is not None:
            body["num_paths"] = n
        with patch("app.api.analytics._build_wide_returns", new=AsyncMock(return_value=(None, rets, {}))), \
             patch("app.api.analytics.simulate_goal", side_effect=_fake_sim):
            await run_monte_carlo(body=body, tickers="TCS.NS", db=_mock_db([_pos()]), data_service=Mock())

    await _run(1000000)
    await _run(5)
    await _run(None)
    assert seen == [20000, 100, 2000]
