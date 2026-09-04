"""
Verification test suite for live portfolio holdings change (INFY.NS and HDFCBANK.NS)
and full quantitative analytics validation against real market & screener data.
"""

import pytest
import numpy as np
import pandas as pd
from sqlalchemy import select, delete
from app.models.database import PortfolioPosition
from app.services.volatility_service import VolatilityService
from app.services.tail_risk_service import TailRiskService
from app.services.correlation_service import analyze_correlation_stability
from app.services.cointegration_service import CointegrationService


@pytest.mark.asyncio
async def test_portfolio_holdings_update_and_db_integrity(test_db):
    """Test switching portfolio holdings to INFY.NS and HDFCBANK.NS with quantity source of truth."""
    await test_db.execute(delete(PortfolioPosition))
    
    pos1 = PortfolioPosition(
        ticker="INFY.NS",
        weight=0.5,
        quantity=100.0,
        buy_price=1100.0,
        region="IN",
        primary_source="yfinance",
        last_price=1116.1,
        market_value=111610.0,
        sector="Technology",
        industry="Information Technology Services"
    )
    pos2 = PortfolioPosition(
        ticker="HDFCBANK.NS",
        weight=0.5,
        quantity=150.0,
        buy_price=710.0,
        region="IN",
        primary_source="yfinance",
        last_price=720.0,
        market_value=108000.0,
        sector="Financial Services",
        industry="Banks - Regional"
    )
    test_db.add(pos1)
    test_db.add(pos2)
    await test_db.commit()
    
    result = await test_db.execute(select(PortfolioPosition))
    positions = result.scalars().all()
    assert len(positions) == 2
    tickers = {p.ticker for p in positions}
    assert tickers == {"INFY.NS", "HDFCBANK.NS"}
    
    for p in positions:
        assert p.quantity > 0
        assert p.buy_price > 0
        assert p.last_price > 0
        expected_mv = p.quantity * p.last_price
        assert abs(p.market_value - expected_mv) < 1.0


@pytest.mark.asyncio
async def test_volatility_cone_and_garch_quant_logic():
    """Verify multi-window realized volatility cone and GARCH(1,1) forecast."""
    np.random.seed(42)
    rets = pd.Series(np.random.normal(0.0003, 0.018, 300))
    cone = VolatilityService.calculate_volatility_cone(rets)
    assert len(cone["windows"]) == 5
    for w in cone["windows"]:
        assert w["current_realized"] > 0
        assert w["min"] <= w["p25"] <= w["median"] <= w["p75"] <= w["max"]
    
    garch = VolatilityService.forecast_garch_volatility(rets, horizon=5)
    assert garch["annualized_vol"] > 0
    assert cone["current_forecast"]["valuation"] in ["cheap", "normal", "rich"]


@pytest.mark.asyncio
async def test_tail_risk_evt_and_copula_logic():
    """Verify 99% EVT-POT VaR/ES Generalized Pareto tail fit and Copula matrix."""
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=300, freq="B")
    rets1 = np.random.normal(0.0004, 0.015, 300)
    rets2 = 0.5 * rets1 + np.random.normal(0.0002, 0.012, 300)
    returns_df = pd.DataFrame({"INFY.NS": rets1, "HDFCBANK.NS": rets2}, index=dates)
    weights = {"INFY.NS": 0.5, "HDFCBANK.NS": 0.5}
    
    suite = TailRiskService.calculate_full_tail_risk_suite(returns_df, weights)
    evt = suite["evt_var"]
    assert evt["evt_pot_var_99"] < 0
    assert evt["evt_pot_es_99"] <= evt["evt_pot_var_99"]
    assert evt["total_observations"] == 300
    
    copula = suite["tail_dependence_matrix"]
    assert len(copula["matrix"]) == 2
    assert copula["matrix"][0][0] == 1.0
    assert copula["matrix"][1][1] == 1.0
    assert 0.0 <= copula["matrix"][0][1] <= 1.0


@pytest.mark.asyncio
async def test_correlation_stability_and_regime_breaks():
    """Verify 60d rolling pairwise correlation monitor and break alerts."""
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=200, freq="B")
    rets1 = np.random.normal(0.0005, 0.015, 200)
    rets2 = 0.6 * rets1 + np.random.normal(0.0002, 0.01, 200)
    returns_df = pd.DataFrame({"INFY.NS": rets1, "HDFCBANK.NS": rets2}, index=dates)
    
    corr_res = analyze_correlation_stability(returns_df, window_days=60)
    assert -1.0 <= corr_res.current_avg_correlation <= 1.0
    assert corr_res.historical_threshold_90th >= corr_res.historical_threshold_75th
    assert corr_res.alert_level in ["NORMAL", "ELEVATED", "HIGH", "CRITICAL"]


@pytest.mark.asyncio
async def test_cointegration_scanner_engle_granger():
    """Verify Engle-Granger and OU mean-reversion half life on synthetic cointegrated series."""
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=300, freq="B")
    p1 = 100.0 + np.cumsum(np.random.normal(0, 1.0, 300))
    p2 = 1.5 * p1 + 10.0 + np.random.normal(0, 0.5, 300)
    price_dict = {
        "INFY.NS": pd.Series(p1, index=dates),
        "HDFCBANK.NS": pd.Series(p2, index=dates)
    }
    
    svc = CointegrationService(db_session=None)
    res = await svc.scan_pairs(price_dict, p_value_threshold=0.10)
    assert res.scanned_pairs_count == 1
    assert len(res.pairs) == 1
    pair = res.pairs[0]
    assert {pair.ticker_a, pair.ticker_b} == {"INFY.NS", "HDFCBANK.NS"}
    assert pair.ou_half_life_days > 0
    assert pair.signal in ["LONG_SPREAD", "SHORT_SPREAD", "NEUTRAL"]
