"""Contract P1 batch regressions (issues 10-remainder + 12).

Issue-08 null pattern: uncomputables are None, `error` keys kept, never
another plausible constant.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pandas as pd
import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import get_liquidity_metrics
from app.models.database import (
    AnalyticsCache,
    AppSetting,
    FetchLog,
    PortfolioPosition,
    StockTimeseries,
)
from app.models.schemas import ValidateTickerRequest
from app.services.currency_service import CurrencyConversionService


def _frame(days=120, seed=11):
    import numpy as np

    dates = pd.date_range("2024-01-01", periods=days, freq="B")
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(rng.normal(0.0004, 0.015, days).cumsum())
    return pd.DataFrame({
        "date": dates,
        "open": close * 0.99,
        "high": close * 1.01,
        "low": close * 0.98,
        "close": close,
        "adj_close": close,
        "volume": [500000.0] * days,
    })


def _mock_db(positions):
    db = AsyncMock()
    res = MagicMock()
    res.scalars.return_value.all.return_value = positions
    db.execute.return_value = res
    return db


def _pos(ticker, weight=1.0, quantity=10.0, last_price=100.0, market_value=1000.0):
    return PortfolioPosition(
        ticker=ticker, weight=weight, quantity=quantity, buy_price=90.0,
        last_price=last_price, market_value=market_value,
        sector="IT", industry="Software", added_on=datetime(2020, 1, 1),
    )


# --- (1) mock-200 remainder nulls -------------------------------------------

@pytest.mark.asyncio
async def test_realized_risk_empty_portfolio_nulls(async_client: AsyncClient, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    res = await async_client.get("/api/v1/analytics/realized-risk")
    assert res.status_code == 200
    body = res.json()
    assert "error" in body
    for key in ("annual_return", "annual_volatility", "sharpe_ratio", "sortino_ratio",
                "skewness", "kurtosis", "max_drawdown", "var_95", "cvar_95", "hit_ratio"):
        assert body["portfolio"][key] is None, key


@pytest.mark.asyncio
async def test_realized_risk_no_price_data_nulls(async_client: AsyncClient, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    test_db.add(_pos("NOPRICE.NS"))
    await test_db.commit()
    mock_ds = Mock()
    mock_ds.fetch_historical_data = AsyncMock(return_value=pd.DataFrame())
    with patch("app.api.analytics.GlobalDataService") as mock_gds:
        mock_gds.return_value.get_service.return_value = mock_ds
        res = await async_client.get("/api/v1/analytics/realized-risk")
    assert res.status_code == 200
    body = res.json()
    assert "error" in body
    assert body["portfolio"]["annual_volatility"] is None
    assert body["portfolio"]["var_95"] is None
    assert body["portfolio"]["cvar_95"] is None
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()


@pytest.mark.asyncio
async def test_stress_empty_portfolio_nulls(async_client: AsyncClient, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    res = await async_client.post("/api/v1/analytics/stress-test", json={"scenario": "covid_crash_2020"})
    assert res.status_code == 200
    body = res.json()
    assert body["max_drawdown"] is None
    assert body["portfolio_impact"] is None
    assert body["position_impacts"] == {}
    assert body["recovery_time"] is None
    assert "error" in body


@pytest.mark.asyncio
async def test_stress_no_price_data_nulls(async_client: AsyncClient, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    test_db.add(_pos("NOPRICE.NS"))
    await test_db.commit()
    mock_ds = Mock()
    mock_ds.fetch_historical_data = AsyncMock(return_value=pd.DataFrame())
    with patch("app.api.analytics.GlobalDataService") as mock_gds:
        mock_gds.return_value.get_service.return_value = mock_ds
        res = await async_client.post("/api/v1/analytics/stress-test", json={"scenario": "covid_crash_2020"})
    assert res.status_code == 200
    body = res.json()
    assert body["max_drawdown"] is None
    assert body["portfolio_impact"] is None
    assert body["position_impacts"] == {}
    assert body["recovery_time"] is None
    assert "error" in body
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()


@pytest.mark.asyncio
async def test_summary_empty_portfolio_nulls(async_client: AsyncClient, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    res = await async_client.get("/api/v1/analytics/summary")
    assert res.status_code == 200
    body = res.json()
    assert body["portfolio_value"] == 0.0
    assert body["total_positions"] == 0
    for key in ("realized_volatility", "forecast_volatility", "sharpe_ratio",
                "max_drawdown", "risk_score", "risk_level",
                "liquidity_score", "concentration_score"):
        assert body[key] is None, key
    assert "error" in body


@pytest.mark.asyncio
async def test_liquidity_missing_score_is_none():
    mock_ds = Mock()
    mock_ds.fetch_historical_data = AsyncMock(return_value=_frame(40))
    mock_ds.fetch_quote = AsyncMock(return_value={"market_cap": 1e9})
    mock_engine = Mock()
    mock_engine.liquidity_analysis = AsyncMock(return_value={})
    res = await get_liquidity_metrics(
        db=_mock_db([_pos("TCS.NS")]), data_service=mock_ds, analytics_engine=mock_engine
    )
    assert res["overall_score"] is None


@pytest.mark.asyncio
async def test_risk_score_empty_portfolio_nulls(async_client: AsyncClient, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    res = await async_client.get("/api/v1/analytics/risk-score")
    assert res.status_code == 200
    body = res.json()
    assert body["overall_score"] is None
    assert body["risk_level"] is None
    assert body["components"] == {}
    assert "error" in body


@pytest.mark.asyncio
async def test_config_get_reads_persisted_cache_settings(async_client: AsyncClient, test_db: AsyncSession):
    await async_client.put("/api/v1/data/config?cache_ttl_minutes=180&enable_cache=false")
    res = await async_client.get("/api/v1/data/config")
    assert res.status_code == 200
    body = res.json()
    assert body["cache_ttl_minutes"] == 180
    assert body["enable_cache"] is False


# --- (4) stress honors request.tickers --------------------------------------

@pytest.mark.asyncio
async def test_stress_honors_request_tickers(async_client: AsyncClient, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    test_db.add_all([_pos("AAAA.NS", weight=0.5, market_value=5000.0),
                     _pos("BBBB.NS", weight=0.5, market_value=5000.0)])
    await test_db.commit()
    mock_ds = Mock()

    async def _fetch(ticker, start, end, force_refresh=False):
        return _frame(200, seed=hash(ticker) % 1000)

    mock_ds.fetch_historical_data = AsyncMock(side_effect=_fetch)
    with patch("app.api.analytics.GlobalDataService") as mock_gds:
        mock_gds.return_value.get_service.return_value = mock_ds
        res = await async_client.post("/api/v1/analytics/stress-test", json={
            "scenario": "covid_crash_2020", "tickers": ["AAAA.NS"],
        })
    assert res.status_code == 200
    body = res.json()
    assert "error" not in body
    assert set(body["position_impacts"]) == {"AAAA.NS"}
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()


# --- (2) ticker validation ---------------------------------------------------

def test_validate_ticker_accepts_long_nse():
    assert ValidateTickerRequest(ticker="MOTHERSON.NS").ticker == "MOTHERSON.NS"
    assert ValidateTickerRequest(ticker="BAJAJ-AUTO.NS").ticker == "BAJAJ-AUTO.NS"
    assert ValidateTickerRequest(ticker="500112.BO").ticker == "500112.BO"
    assert ValidateTickerRequest(ticker="infy.ns").ticker == "INFY.NS"


def test_validate_ticker_rejects_bad_format():
    with pytest.raises(ValidationError):
        ValidateTickerRequest(ticker="BAD TICKER!")
    with pytest.raises(ValidationError):
        ValidateTickerRequest(ticker="A" * 21)


# --- (3) DB ticker widths -----------------------------------------------------

def test_db_ticker_columns_width_20():
    assert PortfolioPosition.__table__.c.ticker.type.length == 20
    assert StockTimeseries.__table__.c.ticker.type.length == 20
    assert AnalyticsCache.__table__.c.ticker.type.length == 20
    assert FetchLog.__table__.c.ticker.type.length == 20


# --- (5) rebalance ------------------------------------------------------------

@pytest.mark.asyncio
async def test_rebalance_missing_price_400(async_client: AsyncClient, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    # market_value > 0 keeps total_pv alive; last_price 0 must 400, not fabricate 100.0
    test_db.add(_pos("NOPRICE.NS", last_price=0.0, market_value=5000.0))
    await test_db.commit()
    res = await async_client.post("/api/v1/portfolio/rebalance", json={
        "new_weights": {"NOPRICE.NS": 1.0}, "dry_run": True,
    })
    assert res.status_code == 400
    assert "NOPRICE.NS" in res.json()["detail"]
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()


@pytest.mark.asyncio
async def test_rebalance_float_qty(async_client: AsyncClient, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    test_db.add_all([
        _pos("AAA.NS", weight=0.5, quantity=10.0, last_price=100.0, market_value=1000.0),
        _pos("BBB.NS", weight=0.5, quantity=10.0, last_price=300.0, market_value=3000.0),
    ])
    await test_db.commit()
    res = await async_client.post("/api/v1/portfolio/rebalance", json={
        "new_weights": {"AAA.NS": 0.3333, "BBB.NS": 0.6667}, "dry_run": True,
    })
    assert res.status_code == 200
    order = next(o for o in res.json()["orders"] if o["ticker"] == "AAA.NS")
    assert isinstance(order["shares_delta"], float)
    assert order["shares_delta"] != int(order["shares_delta"])
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()


# --- (6) PUT /config -----------------------------------------------------------

@pytest.mark.asyncio
async def test_put_config_persists_cache_settings(async_client: AsyncClient, test_db: AsyncSession):
    res = await async_client.put("/api/v1/data/config?cache_ttl_minutes=120&enable_cache=false")
    assert res.status_code == 200
    assert res.json()["settings"]["cache_ttl_minutes"] == 120
    assert res.json()["settings"]["enable_cache"] is False
    rows = (await test_db.execute(select(AppSetting))).scalars().all()
    stored = {r.key: r.value for r in rows}
    assert stored["cache_ttl_minutes"] == "120"
    assert stored["enable_cache"] == "False"


# --- (7) FX ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fx_unknown_pair_raises():
    svc = CurrencyConversionService()
    with pytest.raises(ValueError, match="No exchange rate configured"):
        await svc.get_exchange_rate("EUR", "JPY")
    with pytest.raises(ValueError, match="No exchange rate configured"):
        await svc.convert_amount(100.0, "EUR", "JPY")
    assert await svc.get_exchange_rate("USD", "USD") == 1.0
