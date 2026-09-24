"""Agent C API/portfolio/request-contract regressions (C-01..C-14).

All tests use isolated in-memory/temp DB seams and mocked providers.  No live
vendor or application portfolio database is touched.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pandas as pd
import numpy as np
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.api import analytics as analytics_mod
from app.api import data as data_mod
from app.api import portfolio as portfolio_mod
from app.api import websocket as websocket_mod
from app.api.analytics import (
    get_cointegration_pairs,
    get_forecast_risk,
    get_performance_history,
    get_liquidity_limits,
    get_liquidity_metrics,
    get_concentration_metrics,
    get_risk_contribution,
    get_tail_risk_and_copula,
    get_volatility_sizing,
    run_optimization,
    _build_wide_returns,
    _load_portfolio_allocation,
)
from app.api.data import get_batch_stock_data
from app.services.cache_service import ProviderUnavailableError
from app.services.currency_service import FXRate
from app.api.portfolio import (
    add_portfolio_position,
    bulk_add_positions,
    export_portfolio_csv,
    rebalance_portfolio,
    RebalancePayload,
)
from app.api.websocket import ConnectionManager
from app.models.database import PortfolioPosition
from app.models.schemas import (
    BulkAddRequest,
    BatchStockDataRequest,
    PortfolioPositionBase,
    PortfolioPositionCreate,
    EVTPOTVarMetrics,
)


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None


class _DB:
    def __init__(self, rows=None, *, commit_error=None, refresh_error=None):
        self.rows = list(rows or [])
        self.commits = 0
        self.rollbacks = 0
        self.commit_error = commit_error
        self.refresh_error = refresh_error
        self.executed = 0

    async def execute(self, _statement):
        self.executed += 1
        return _Rows(self.rows)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1
        if self.commit_error:
            raise self.commit_error

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, obj):
        if self.refresh_error:
            raise self.refresh_error
        return obj

    def add(self, obj):
        self.rows.append(obj)

    async def delete(self, obj):
        if obj in self.rows:
            self.rows.remove(obj)


class _FX:
    async def get_exchange_rate(self, source, target):
        rate = 80.0 if (source, target) == ("USD", "INR") else 1 / 80
        return FXRate(rate, provenance="live", source="mock-fx")

    async def convert_amount_with_provenance(self, amount, source, target):
        rate = 80.0 if (source, target) == ("USD", "INR") else 1 / 80
        return {
            "amount": amount * rate,
            "rate": {
                "rate": rate,
                "provenance": "live",
                "source": "mock-fx",
                "is_fallback": False,
            },
        }

    async def convert_amount(self, amount, source, target):
        return amount * (80.0 if (source, target) == ("USD", "INR") else 1 / 80)


class _FallbackFX(_FX):
    async def get_exchange_rate(self, source, target):
        rate = 83.0 if (source, target) == ("USD", "INR") else 1 / 83
        return FXRate(rate, provenance="fallback", source="fallback_constant")

    async def convert_amount_with_provenance(self, amount, source, target):
        rate = 83.0 if (source, target) == ("USD", "INR") else 1 / 83
        return {
            "amount": amount * rate,
            "rate": {
                "rate": rate,
                "provenance": "fallback",
                "source": "fallback_constant",
                "is_fallback": True,
            },
        }

    async def convert_amount(self, amount, source, target):
        rate = 83.0 if (source, target) == ("USD", "INR") else 1 / 83
        return amount * rate


class _Market:
    def __init__(self):
        self.validate_ticker = AsyncMock(return_value=True)
        self.fetch_quote = AsyncMock(return_value={
            "current_price": 100.0,
            "sector": "Technology",
            "industry": "Software",
        })


def test_c01_position_currency_uses_ticker_identity_over_stale_region():
    from app.api.portfolio import _position_currency

    position = SimpleNamespace(ticker="AAPL", region="IN")
    assert _position_currency(position) == "USD"
    with pytest.raises(HTTPException) as exc_info:
        _position_currency(SimpleNamespace(ticker="AAPL", currency="INR"))
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_c01_mixed_currency_aggregation_and_provenance(async_client, test_db):
    await test_db.execute(delete(PortfolioPosition))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    test_db.add_all([
        PortfolioPosition(
            ticker="AAPL", region="US", weight=.5, quantity=1, buy_price=90,
            last_price=100, market_value=100, sector="Technology", industry="Software",
            added_on=now, updated_on=now,
        ),
        PortfolioPosition(
            ticker="TCS.NS", region="IN", weight=.5, quantity=1, buy_price=80,
            last_price=80, market_value=80, sector="Technology", industry="Software",
            added_on=now, updated_on=now,
        ),
    ])
    await test_db.commit()
    market = _Market()
    with patch("app.api.portfolio.GlobalDataService", return_value=SimpleNamespace(get_service=lambda: market)), \
         patch("app.api.portfolio.get_currency_service", return_value=_FX()):
        response = await async_client.get("/api/v1/portfolio?currency=INR")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_value"] == pytest.approx(8080.0, abs=1e-6)
    assert body["currency"] == body["base_currency"] == "INR"
    assert body["position_currencies"] == {"AAPL": "USD", "TCS.NS": "INR"}
    assert body["currency_provenance"]["aggregation"] == "per_position_conversion"

    aapl = next(row for row in body["positions"] if row["ticker"] == "AAPL")
    assert aapl["native_currency"] == "USD"
    assert aapl["region"] == "US"
    assert aapl["value_currency"] == "INR"
    assert aapl["fx_rate"] == pytest.approx(80.0)
    assert aapl["current_value"] == pytest.approx(100.0)
    assert aapl["buy_price_base"] == pytest.approx(7200.0)
    assert aapl["last_price_base"] == pytest.approx(8000.0)
    assert aapl["total_cost"] == pytest.approx(90.0)
    assert aapl["current_value_base"] == pytest.approx(8000.0)
    assert aapl["total_cost_base"] == pytest.approx(7200.0)
    assert aapl["unrealized_gain_loss_base"] == pytest.approx(800.0)

    with patch("app.api.portfolio.GlobalDataService", return_value=SimpleNamespace(get_service=lambda: market)), \
         patch("app.api.portfolio.get_currency_service", return_value=_FX()):
        usd_response = await async_client.get("/api/v1/portfolio?currency=USD")
    assert usd_response.status_code == 200, usd_response.text
    usd_body = usd_response.json()
    usd_aapl = next(row for row in usd_body["positions"] if row["ticker"] == "AAPL")
    assert usd_aapl["native_currency"] == "USD"
    assert usd_aapl["value_currency"] == "USD"
    assert usd_aapl["current_value_base"] == pytest.approx(100.0)
    assert usd_aapl["total_cost_base"] == pytest.approx(90.0)
    assert usd_aapl["unrealized_gain_loss_base"] == pytest.approx(10.0)
    assert usd_body["total_value"] == pytest.approx(101.0)


@pytest.mark.asyncio
async def test_c01_portfolio_rejects_marked_fallback_fx_with_503(async_client, test_db):
    await test_db.execute(delete(PortfolioPosition))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    test_db.add(PortfolioPosition(
        ticker="AAPL", region="US", weight=1.0, quantity=1.0, buy_price=100.0,
        last_price=100.0, market_value=100.0, sector="Technology",
        industry="Software", added_on=now, updated_on=now,
    ))
    await test_db.commit()
    market = _Market()
    with patch("app.api.portfolio.GlobalDataService", return_value=SimpleNamespace(get_service=lambda: market)), \
         patch("app.api.portfolio.get_currency_service", return_value=_FallbackFX()):
        response = await async_client.get("/api/v1/portfolio?currency=INR")

    assert response.status_code == 503
    assert response.json()["detail"] == "Live FX unavailable"
    assert "8300" not in response.text


@pytest.mark.asyncio
async def test_c01_analytics_allocation_converts_mixed_currency_before_weights():
    positions = [
        SimpleNamespace(
            ticker="AAPL", region="US", quantity=1.0, last_price=100.0,
            market_value=100.0, weight=0.5,
        ),
        SimpleNamespace(
            ticker="TCS.NS", region="IN", quantity=1.0, last_price=80.0,
            market_value=80.0, weight=0.5,
        ),
    ]
    with patch("app.api.analytics.get_currency_service", return_value=_FX()):
        weights = await _load_portfolio_allocation(_DB(positions))
    assert weights["AAPL"] == pytest.approx(100.0 * 80.0 / 8080.0)
    assert weights["TCS.NS"] == pytest.approx(80.0 / 8080.0)
    assert sum(weights.values()) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_c01_uniform_usd_values_are_not_mislabelled_as_inr():
    positions = [
        SimpleNamespace(
            ticker="AAPL", region="US", quantity=1.0, last_price=100.0,
            market_value=100.0, weight=1.0,
        )
    ]
    with patch("app.api.analytics.get_currency_service", return_value=_FX()):
        values, provenance = await analytics_mod._convert_analytics_positions(positions)

    assert values == {"AAPL": pytest.approx(8000.0)}
    assert provenance["base_currency"] == "INR"
    assert provenance["aggregation"] == "per_position_conversion"
    assert provenance["pairs"]["USD->INR"] == {
        "rate": pytest.approx(80.0),
        "provenance": "live",
        "source": "mock-fx",
        "is_fallback": False,
    }


@pytest.mark.asyncio
async def test_c01_performance_history_uses_converted_mixed_currency_values():
    dates = pd.bdate_range(end=pd.Timestamp.utcnow().normalize(), periods=12)
    positions = [
        SimpleNamespace(
            ticker="AAPL", region="US", quantity=1.0, last_price=100.0,
            market_value=100.0, buy_price=None, added_on=dates[0] - pd.Timedelta(days=1),
        ),
        SimpleNamespace(
            ticker="TCS.NS", region="IN", quantity=1.0, last_price=80.0,
            market_value=80.0, buy_price=None, added_on=dates[0] - pd.Timedelta(days=1),
        ),
    ]

    class Market:
        async def fetch_historical_data(self, ticker, start, end):
            price = 100.0 if ticker == "AAPL" else 80.0
            return pd.DataFrame({"close": np.full(len(dates), price)}, index=dates)

    benchmark = SimpleNamespace(
        get_returns=AsyncMock(return_value=pd.Series(dtype=float))
    )
    with patch("app.api.analytics.get_currency_service", return_value=_FX()):
        result = await get_performance_history(
            days=30, tickers="AAPL,TCS.NS", db=_DB(positions),
            data_service=Market(), benchmark_service=benchmark,
        )
    assert result
    assert result[-1]["portfolio_value"] == pytest.approx(8080.0)
    assert result[-1]["portfolio_value_currency"] == "INR"
    assert result[-1]["currency"] == result[-1]["base_currency"] == "INR"
    assert result[-1]["currency_provenance"]["pairs"]["USD->INR"]["provenance"] == "live"


@pytest.mark.asyncio
async def test_c01_performance_history_uses_inr_for_uniform_usd_book():
    dates = pd.bdate_range(end=pd.Timestamp.utcnow().normalize(), periods=12)
    position = SimpleNamespace(
        ticker="AAPL", region="US", quantity=1.0, last_price=100.0,
        market_value=100.0, buy_price=None, added_on=dates[0] - pd.Timedelta(days=1),
    )

    class Market:
        async def fetch_historical_data(self, *_args):
            return pd.DataFrame({"close": np.full(len(dates), 100.0)}, index=dates)

    with patch("app.api.analytics.get_currency_service", return_value=_FX()):
        result = await get_performance_history(
            days=30, tickers="AAPL", db=_DB([position]),
            data_service=Market(),
            benchmark_service=SimpleNamespace(
                get_returns=AsyncMock(return_value=pd.Series(dtype=float))
            ),
        )

    assert result[-1]["portfolio_value"] == pytest.approx(8000.0)
    assert result[-1]["currency"] == result[-1]["base_currency"] == "INR"
    assert result[-1]["currency_provenance"]["aggregation"] == "per_position_conversion"


@pytest.mark.asyncio
async def test_c01_coverage_counts_active_return_observations():
    dates = pd.bdate_range("2025-01-01", periods=30)
    values = np.linspace(100.0, 120.0, len(dates))
    values[15] = np.nan
    position = PortfolioPosition(
        ticker="A", region="US", weight=1.0, quantity=1.0, buy_price=100.0,
        last_price=110.0, market_value=110.0, sector="Tech", industry="Software",
        added_on=datetime(2020, 1, 1),
    )

    class Market:
        async def fetch_historical_data(self, *_args):
            return pd.DataFrame({"close": values}, index=dates)

    result = await analytics_mod.get_realized_risk(
        tickers="A", start="2025-01-01", end="2025-02-15",
        db=_DB([position]), data_service=Market(),
        analytics_engine=analytics_mod.AnalyticsEngine(),
    )
    assert result["history_coverage"]["covered_days"] == 27
    assert result["history_coverage"]["annualized"] is False


@pytest.mark.asyncio
async def test_c01_mixed_fx_outage_maps_to_503_for_analytics_routes():
    positions = [
        SimpleNamespace(
            ticker="AAPL", region="US", quantity=1.0, last_price=100.0,
            market_value=100.0, weight=0.5, buy_price=None, added_on=None,
        ),
        SimpleNamespace(
            ticker="TCS.NS", region="IN", quantity=1.0, last_price=80.0,
            market_value=80.0, weight=0.5, buy_price=None, added_on=None,
        ),
    ]

    class UnavailableFX:
        async def convert_amount_with_provenance(self, *_args):
            raise ProviderUnavailableError("offline", provider="currency")

        async def get_exchange_rate(self, *_args):
            raise ProviderUnavailableError("offline", provider="currency")

    with patch("app.api.analytics.get_currency_service", return_value=UnavailableFX()):
        with pytest.raises(HTTPException) as summary_error:
            await analytics_mod.get_analytics_summary(
                db=_DB(positions), data_service=Mock(),
                analytics_engine=analytics_mod.AnalyticsEngine(),
            )
    assert summary_error.value.status_code == 503

    dates = pd.bdate_range(end=pd.Timestamp.utcnow().normalize(), periods=10)

    class Market:
        async def fetch_historical_data(self, *_args):
            return pd.DataFrame({"close": [100.0] * len(dates)}, index=dates)

    with patch("app.api.analytics.get_currency_service", return_value=UnavailableFX()):
        with pytest.raises(HTTPException) as history_error:
            await get_performance_history(
                days=30, tickers="AAPL,TCS.NS", db=_DB(positions),
                data_service=Market(),
                benchmark_service=SimpleNamespace(
                    get_returns=AsyncMock(return_value=pd.Series(dtype=float))
                ),
            )
    assert history_error.value.status_code == 503


@pytest.mark.asyncio
async def test_c01_concentration_maps_fallback_fx_to_503():
    positions = [
        SimpleNamespace(
            ticker="AAPL", region="US", quantity=1.0, last_price=100.0,
            market_value=100.0, weight=1.0,
        )
    ]
    with patch("app.api.analytics.get_currency_service", return_value=_FallbackFX()):
        with pytest.raises(HTTPException) as raised:
            await analytics_mod.get_concentration_metrics(
                db=_DB(positions), data_service=Mock(), analytics_engine=Mock()
            )
    assert raised.value.status_code == 503
    assert raised.value.detail == "Live FX unavailable"


@pytest.mark.asyncio
async def test_c01_liquidity_route_uses_declared_inr_base_currency():
    dates = pd.bdate_range("2025-01-02", periods=5)
    positions = [
        SimpleNamespace(
            ticker="AAPL", region="US", quantity=1.0, last_price=100.0,
            market_value=100.0, buy_price=90.0, weight=.5,
        ),
        SimpleNamespace(
            ticker="TCS.NS", region="IN", quantity=1.0, last_price=80.0,
            market_value=80.0, buy_price=80.0, weight=.5,
        ),
    ]

    class Market:
        async def fetch_historical_data(self, ticker, _start, _end):
            price = 100.0 if ticker == "AAPL" else 80.0
            return pd.DataFrame(
                {"close": [price] * len(dates), "volume": [1000.0] * len(dates)},
                index=dates,
            )

    with patch("app.api.analytics.get_currency_service", return_value=_FX()):
        result = await get_liquidity_limits(
            tickers=None,
            db=_DB(positions),
            data_service=Market(),
        )

    assert result["portfolio_value"] == pytest.approx(8080.0)
    assert result["currency"] == result["base_currency"] == "INR"
    rows = {row["ticker"]: row for row in result["positions"]}
    assert rows["AAPL"]["position_value"] == pytest.approx(8000.0)
    assert rows["AAPL"]["position_value_native"] == pytest.approx(100.0)
    assert rows["AAPL"]["adv_30d_rupees"] == pytest.approx(8_000_000.0)


@pytest.mark.asyncio
async def test_c01_empty_analytics_responses_are_explicitly_unavailable():
    concentration = await get_concentration_metrics(
        db=_DB([]), data_service=Mock(), analytics_engine=Mock()
    )
    liquidity = await get_liquidity_metrics(
        db=_DB([]), data_service=Mock(), analytics_engine=Mock()
    )
    assert concentration["zero_metrics"] is True
    assert concentration["error"] == "No portfolio positions found"
    assert liquidity["zero_metrics"] is True
    assert liquidity["error"] == "No portfolio positions found"


@pytest.mark.asyncio
async def test_c01_rebalance_converts_mixed_currency_values_before_targets():
    positions = [
        SimpleNamespace(
            ticker="AAPL", region="US", quantity=1.0, last_price=100.0,
            # Deliberately stale: valuation and targets share the live price.
            market_value=999_999.0, weight=0.5,
        ),
        SimpleNamespace(
            ticker="TCS.NS", region="IN", quantity=1.0, last_price=80.0,
            market_value=1.0, weight=0.5,
        ),
    ]
    with patch("app.api.portfolio.get_currency_service", return_value=_FX()):
        result = await rebalance_portfolio(
            RebalancePayload(new_weights={"AAPL": 0.5, "TCS.NS": 0.5}, dry_run=True),
            db=_DB(positions),
        )
    assert result["total_portfolio_value"] == pytest.approx(8080.0)
    assert result["currency"] == result["base_currency"] == "INR"
    assert result["total_portfolio_value_currency"] == "INR"
    assert result["currency_provenance"]["pairs"]["USD->INR"]["provenance"] == "live"
    orders = {row["ticker"]: row for row in result["orders"]}
    assert orders["AAPL"]["value_currency"] == "INR"
    assert orders["AAPL"]["cash_delta_currency"] == "INR"
    assert orders["AAPL"]["target_quantity"] == pytest.approx(4040.0 / 8000.0, abs=1e-4)
    assert orders["TCS.NS"]["target_quantity"] == pytest.approx(50.5, abs=1e-4)


@pytest.mark.asyncio
async def test_c01_rebalance_rejects_marked_fallback_fx_with_503():
    positions = [
        SimpleNamespace(
            ticker="AAPL", region="US", quantity=1.0, last_price=100.0,
            market_value=100.0, weight=0.5,
        ),
        SimpleNamespace(
            ticker="TCS.NS", region="IN", quantity=1.0, last_price=80.0,
            market_value=80.0, weight=0.5,
        ),
    ]
    db = _DB(positions)
    with patch("app.api.portfolio.get_currency_service", return_value=_FallbackFX()):
        with pytest.raises(HTTPException) as raised:
            await rebalance_portfolio(
                RebalancePayload(
                    new_weights={"AAPL": 0.5, "TCS.NS": 0.5}, dry_run=True
                ),
                db=db,
            )

    assert raised.value.status_code == 503
    assert raised.value.detail == "Live FX unavailable"
    assert db.commits == 0 and db.rollbacks == 1


@pytest.mark.asyncio
async def test_c01_volatility_sizing_uses_converted_portfolio_value():
    dates = pd.bdate_range(end=pd.Timestamp.utcnow().normalize(), periods=40)
    positions = [
        SimpleNamespace(
            ticker="AAPL", region="US", quantity=1.0, last_price=100.0,
            market_value=100.0, weight=0.5,
        ),
        SimpleNamespace(
            ticker="TCS.NS", region="IN", quantity=1.0, last_price=80.0,
            market_value=80.0, weight=0.5,
        ),
    ]

    class Market:
        async def fetch_historical_data(self, ticker, start, end):
            price = np.linspace(100.0, 110.0, len(dates)) if ticker == "AAPL" else np.linspace(80.0, 88.0, len(dates))
            return pd.DataFrame({"adj_close": price}, index=dates)

    sizing = AsyncMock(return_value={"recommended_weights": {"AAPL": 0.5, "TCS.NS": 0.5}})
    with patch("app.api.analytics.get_currency_service", return_value=_FX()):
        result = await get_volatility_sizing(
            model="EWMA", target_volatility=0.1, db=_DB(positions),
            data_service=Market(), analytics_engine=SimpleNamespace(volatility_sizing=sizing),
            portfolio_value=None,
        )
    assert sizing.await_args.kwargs["portfolio_value"] == pytest.approx(8080.0)
    assert result["portfolio_value"] == pytest.approx(8080.0)
    assert result["currency"] == result["base_currency"] == "INR"
    assert result["currency_provenance"]["pairs"]["USD->INR"]["provenance"] == "live"


@pytest.mark.asyncio
async def test_c01_volatility_sizing_rejects_marked_fallback_fx_with_503():
    positions = [
        SimpleNamespace(
            ticker="AAPL", region="US", quantity=1.0, last_price=100.0,
            market_value=100.0, weight=1.0,
        )
    ]
    sizing = AsyncMock(return_value={"recommended_weights": {"AAPL": 1.0}})
    with patch("app.api.analytics.get_currency_service", return_value=_FallbackFX()):
        with pytest.raises(HTTPException) as raised:
            await get_volatility_sizing(
                model="EWMA", target_volatility=0.1, db=_DB(positions),
                data_service=Mock(), analytics_engine=SimpleNamespace(
                    volatility_sizing=sizing
                ),
                portfolio_value=None,
            )

    assert raised.value.status_code == 503
    assert raised.value.detail == "Live FX unavailable"
    sizing.assert_not_awaited()


@pytest.mark.asyncio
async def test_c04_websocket_mixed_currency_total_and_weights():
    positions = [
        SimpleNamespace(
            ticker="AAPL", region="US", quantity=1.0, last_price=100.0,
            market_value=100.0, weight=0.5,
        ),
        SimpleNamespace(
            ticker="TCS.NS", region="IN", quantity=1.0, last_price=80.0,
            market_value=80.0, weight=0.5,
        ),
    ]

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, _statement):
            return _Rows(positions)

    with patch.object(websocket_mod, "SessionLocal", Session), \
         patch.object(websocket_mod, "get_currency_service", return_value=_FX()), \
         patch.object(websocket_mod.manager, "broadcast", new=AsyncMock()) as broadcast:
        await websocket_mod.send_portfolio_update()

    broadcast.assert_awaited_once()
    payload = broadcast.await_args.args[0]["data"]
    assert payload["total_value"] == pytest.approx(8080.0)
    rows = {row["ticker"]: row for row in payload["positions"]}
    assert rows["AAPL"]["weight"] == pytest.approx(8000.0 / 8080.0, abs=1e-4)
    assert rows["TCS.NS"]["weight"] == pytest.approx(80.0 / 8080.0, abs=1e-4)
    assert rows["AAPL"]["currency"] == "INR"
    assert rows["AAPL"]["value_currency"] == "INR"
    assert rows["AAPL"]["native_currency"] == "USD"
    assert rows["TCS.NS"]["native_currency"] == "INR"


@pytest.mark.asyncio
async def test_c02_forecast_preserves_interior_price_gap():
    dates = pd.bdate_range("2025-01-01", periods=40)
    prices = pd.Series(np.linspace(100.0, 120.0, len(dates)), index=dates)
    prices.iloc[20] = np.nan

    class Market:
        async def fetch_historical_data(self, ticker, start, end):
            return pd.DataFrame({"close": prices}, index=dates)

    captured = []

    async def allocation(_tickers, _db):
        return ["A"], {"A": 1.0}

    async def forecast(series, model, horizon):
        captured.append(series.copy())
        return {
            "volatility_forecast": 0.1,
            "var_forecast": -0.01,
            "cvar_forecast": -0.02,
            "confidence_interval": [0.08, 0.12],
            "term_structure": [0.1],
            "model_params": {"type": model},
        }

    engine = SimpleNamespace(forecast_volatility=forecast)
    with patch.object(analytics_mod, "resolve_allocation", side_effect=allocation):
        await get_forecast_risk(
            model="EWMA", horizon=1, tickers="A",
            start=str(dates[0].date()), end=str(dates[-1].date()),
            db=Mock(), data_service=Market(), analytics_engine=engine,
        )

    assert captured
    ticker_returns = captured[-1]
    assert dates[20] not in ticker_returns.index
    assert dates[21] not in ticker_returns.index
    assert np.isfinite(ticker_returns.to_numpy()).all()


@pytest.mark.asyncio
async def test_c02_single_holding_optimizer_preserves_price_gap():
    dates = pd.bdate_range("2025-01-01", periods=4)
    prices = pd.Series([100.0, 110.0, np.nan, 121.0], index=dates)

    class Market:
        async def fetch_historical_data(self, *_args):
            return pd.DataFrame({"close": prices}, index=dates)

    async def allocation(_tickers, _db):
        return ["A"], {"A": 1.0}

    with patch.object(analytics_mod, "resolve_allocation", side_effect=allocation):
        result = await run_optimization(
            body={"strategy": "hrp"}, db=Mock(), data_service=Market()
        )
    assert result["weights"] == {"A": 1.0}
    assert result["expected_annual_return"] == pytest.approx(0.10 * 252.0)
    assert result["expected_annual_volatility"] is None


@pytest.mark.asyncio
async def test_c02_single_holding_correlation_is_undefined():
    async def allocation(_tickers, _db):
        return ["A"], {"A": 1.0}

    with patch.object(analytics_mod, "resolve_allocation", side_effect=allocation):
        result = await analytics_mod.get_correlation_stability(
            tickers="A", db=Mock(), data_service=Mock()
        )
    assert result.current_avg_correlation is None
    assert result.historical_threshold_90th is None
    assert result.historical_median is None
    assert result.series == []


@pytest.mark.asyncio
async def test_c02_risk_contribution_does_not_impute_missing_tail_leg():
    dates = pd.bdate_range("2025-01-01", periods=20)
    returns = pd.DataFrame(
        {
            "A": [0.01] * 19 + [-0.10],
            "B": [0.01] * 19 + [np.nan],
        },
        index=dates,
    )
    portfolio = returns["A"].copy()
    positions = [
        PortfolioPosition(ticker="A", sector="Tech", weight=0.5),
        PortfolioPosition(ticker="B", sector="Other", weight=0.5),
    ]

    async def allocation(_tickers, _db):
        return ["A", "B"], {"A": 0.5, "B": 0.5}

    async def holdings(*_args):
        return {}

    async def build(*_args, **_kwargs):
        return returns, portfolio, {"covered_days": len(portfolio)}

    with patch.object(analytics_mod, "resolve_allocation", side_effect=allocation), \
         patch.object(analytics_mod, "resolve_holdings", side_effect=holdings), \
         patch.object(analytics_mod, "_build_wide_returns", side_effect=build):
        result = await get_risk_contribution(
            tickers="A,B", db=_DB(positions), data_service=Mock()
        )

    assert "A" in result["positions"]["cvar_tail"]
    assert "B" not in result["positions"]["cvar_tail"]
    assert "B" in result["excluded_assets"]["cvar_tail"]


@pytest.mark.asyncio
async def test_c02_risk_contribution_excludes_underdetermined_leg():
    dates = pd.bdate_range("2025-01-01", periods=40)
    returns = pd.DataFrame(
        {
            "A": np.linspace(-0.01, 0.01, len(dates)),
            "B": [np.nan] * (len(dates) - 1) + [0.01],
        },
        index=dates,
    )
    portfolio = returns["A"].copy()
    positions = [
        PortfolioPosition(ticker="A", sector="Tech", weight=0.5),
        PortfolioPosition(ticker="B", sector="Other", weight=0.5),
    ]

    async def allocation(_tickers, _db):
        return ["A", "B"], {"A": 0.5, "B": 0.5}

    async def holdings(*_args):
        return {}

    async def build(*_args, **_kwargs):
        return returns, portfolio, {"covered_days": len(portfolio)}

    with patch.object(analytics_mod, "resolve_allocation", side_effect=allocation), \
         patch.object(analytics_mod, "resolve_holdings", side_effect=holdings), \
         patch.object(analytics_mod, "_build_wide_returns", side_effect=build):
        result = await get_risk_contribution(
            tickers="A,B", db=_DB(positions), data_service=Mock()
        )

    assert result["excluded_assets"]["volatility"] == ["B"]
    assert result["excluded_assets"]["cvar_tail"] == ["B"]
    assert "B" not in result["positions"]["volatility"]
    assert "B" not in result["positions"]["cvar_tail"]


@pytest.mark.asyncio
async def test_c02_risk_contribution_disjoint_history_disclosures_are_model_scoped():
    dates = pd.bdate_range("2025-01-01", periods=40)
    returns = pd.DataFrame(
        {
            "A": np.r_[np.linspace(-0.02, -0.001, 20), np.full(20, np.nan)],
            "B": np.r_[np.full(20, np.nan), np.linspace(0.001, 0.02, 20)],
        },
        index=dates,
    )
    # The portfolio tail is driven by A; B has no observation on those days.
    portfolio = returns["A"].fillna(0.0)
    positions = [
        PortfolioPosition(ticker="A", sector="Tech", weight=0.5),
        PortfolioPosition(ticker="B", sector="Other", weight=0.5),
    ]

    async def allocation(_tickers, _db):
        return ["A", "B"], {"A": 0.5, "B": 0.5}

    async def holdings(*_args):
        return {}

    async def build(*_args, **_kwargs):
        return returns, portfolio, {"covered_days": len(portfolio)}

    with patch.object(analytics_mod, "resolve_allocation", side_effect=allocation), \
         patch.object(analytics_mod, "resolve_holdings", side_effect=holdings), \
         patch.object(analytics_mod, "_build_wide_returns", side_effect=build):
        result = await get_risk_contribution(
            tickers="A,B", db=_DB(positions), data_service=Mock()
        )

    # B is the only covariance-supported leg, while A is the only tail-supported
    # leg.  A flat exclusion list would incorrectly describe both models at once.
    assert result["positions"]["volatility"] == {"B": 1.0}
    assert result["positions"]["cvar_tail"] == {"A": 1.0}
    assert result["excluded_assets"] == {
        "volatility": ["A"],
        "cvar_tail": ["B"],
    }


@pytest.mark.asyncio
async def test_c02_rejects_region_currency_conflict(async_client, test_db):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    market = _Market()
    with patch("app.api.portfolio.GlobalDataService", return_value=SimpleNamespace(get_service=lambda: market)):
        response = await async_client.post("/api/v1/portfolio/add", json={
            "ticker": "AAPL", "region": "IN", "weight": 1,
            "quantity": 1, "buy_price": 100,
        })
    assert response.status_code == 400, response.text
    assert (await test_db.execute(select(PortfolioPosition))).scalars().all() == []


@pytest.mark.asyncio
async def test_c02_infers_region_for_bare_indian_ticker(async_client, test_db):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    market = _Market()
    with patch("app.api.portfolio.GlobalDataService", return_value=SimpleNamespace(get_service=lambda: market)):
        response = await async_client.post("/api/v1/portfolio/add", json={
            "ticker": "RELIANCE", "weight": 1, "quantity": 1, "buy_price": 100,
        })
    assert response.status_code == 200, response.text
    assert response.json()["region"] == "IN"
    stored = (await test_db.execute(select(PortfolioPosition))).scalars().first()
    assert stored.ticker == "RELIANCE.NS"
    assert stored.region == "IN"


@pytest.mark.asyncio
async def test_c02_zero_state_first_position_is_exactly_one(async_client, test_db):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    market = _Market()
    with patch("app.api.portfolio.GlobalDataService", return_value=SimpleNamespace(get_service=lambda: market)):
        response = await async_client.post("/api/v1/portfolio/add", json={
            "ticker": "AAPL", "weight": .2, "quantity": 1, "buy_price": 100,
        })
    assert response.status_code == 200, response.text
    assert response.json()["weight"] == 1.0
    stored = (await test_db.execute(select(PortfolioPosition))).scalars().first()
    assert stored.weight == 1.0


def test_c02_position_request_rejects_non_finite_money():
    with pytest.raises(ValidationError):
        PortfolioPositionCreate(
            ticker="AAPL", weight=0.5, quantity=float("inf"), buy_price=100.0
        )
    with pytest.raises(ValidationError):
        PortfolioPositionCreate(
            ticker="AAPL", weight=0.5, quantity=1.0, buy_price=float("inf")
        )



@pytest.mark.asyncio
async def test_c03_integrity_error_maps_to_409_without_leaking():
    db = _DB(commit_error=IntegrityError("INSERT", {}, Exception("UNIQUE ticker secret")))
    market = _Market()
    with patch("app.api.portfolio.GlobalDataService", return_value=SimpleNamespace(get_service=lambda: market)):
        with pytest.raises(HTTPException) as raised:
            await add_portfolio_position(
                PortfolioPositionCreate(ticker="AAPL", weight=.2, quantity=1, buy_price=10),
                db=db, data_service=market,
            )
    assert raised.value.status_code == 409
    assert "secret" not in str(raised.value.detail)
    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_c04_websocket_and_broadcast_reject_untrusted_origin():
    ws = AsyncMock()
    ws.headers = {"host": "evil.example", "origin": "https://evil.example"}
    manager = ConnectionManager()
    assert await manager.connect(ws, "bad") is False
    ws.accept.assert_not_awaited()
    ws.close.assert_awaited_once_with(code=1008)

    from main import app
    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ws/broadcast",
            params={"topic": "portfolio"},
            json={"hello": "world"},
            headers={"host": "testserver", "origin": "https://evil.example"},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_c05_tail_memo_key_includes_normalized_weights():
    analytics_mod._TAILS_RESPONSE_CACHE.clear()
    ret = pd.DataFrame({"A": [0.01, -0.02] * 40, "B": [-0.01, 0.02] * 40})
    calls = []

    async def allocation(_tickers, _db):
        return ["A", "B"], ({"A": .8, "B": .2} if not calls else {"A": .2, "B": .8})

    def evt(*_args, **_kwargs):
        calls.append("evt")
        return {"evt": 1}

    def copula(*_args, **_kwargs):
        calls.append("copula")
        return {"A": {"A": 1}, "B": {"B": 1}}

    with patch.object(analytics_mod, "resolve_allocation", side_effect=allocation), \
         patch.object(analytics_mod, "_build_wide_returns", new=AsyncMock(return_value=(ret, ret["A"] * 0 + .01, {}))), \
         patch("app.services.tail_risk_service.TailRiskService.calculate_evt_pot_var_es", side_effect=evt), \
         patch("app.services.tail_risk_service.TailRiskService.calculate_tail_dependence_matrix", side_effect=copula):
        await get_tail_risk_and_copula(
            tickers="A,B", lookback_days=756, confidence_level=.99,
            threshold_quantile=.95, db=Mock(), data_service=Mock(),
        )
        await get_tail_risk_and_copula(
            tickers="A,B", lookback_days=756, confidence_level=.99,
            threshold_quantile=.95, db=Mock(), data_service=Mock(),
        )
    assert calls == ["evt", "copula", "evt", "copula"]
    assert len(analytics_mod._TAILS_RESPONSE_CACHE) == 2
    analytics_mod._TAILS_RESPONSE_CACHE.clear()


@pytest.mark.asyncio
async def test_c06_heavy_route_yields_event_loop():
    returns = pd.DataFrame({"A": [0.01, -0.01] * 40, "B": [-0.01, 0.01] * 40})

    async def resolve(*_args):
        return ["A", "B"], {"A": .5, "B": .5}

    async def build(*_args, **_kwargs):
        return returns, returns.mean(axis=1), {}

    def slow_optimize(*_args, **_kwargs):
        time.sleep(.12)
        return {"weights": {"A": .5, "B": .5}}

    with patch.object(analytics_mod, "resolve_allocation", side_effect=resolve), \
         patch.object(analytics_mod, "_build_wide_returns", side_effect=build), \
         patch.object(analytics_mod, "optimize", side_effect=slow_optimize):
        task = asyncio.create_task(run_optimization(
            body={"strategy": "hrp"}, db=Mock(), data_service=Mock(),
        ))
        await asyncio.sleep(.025)
        assert not task.done(), "CPU work blocked the event loop"
        await task


@pytest.mark.asyncio
async def test_c07_invalid_numeric_and_model_inputs_fail_before_vendor(async_client):
    market = _Market()
    with patch("app.api.analytics.GlobalDataService", return_value=SimpleNamespace(get_service=lambda: market)):
        invalid_bodies = [
            ("/api/v1/analytics/optimize/run", {"risk_free_rate": "NaN"}),
            ("/api/v1/analytics/backtest", {"transaction_cost_bps": -1}),
            ("/api/v1/analytics/monte-carlo", {"target_value": 1, "horizon_years": 41}),
        ]
        for path, body in invalid_bodies:
            response = await async_client.post(path, json=body)
            assert response.status_code == 422, (path, response.text)
        assert market.fetch_quote.await_count == 0
        invalid_model = await async_client.get("/api/v1/analytics/forecast-risk?model=NOT_A_MODEL")
        assert invalid_model.status_code == 422
        assert market.fetch_quote.await_count == 0


@pytest.mark.asyncio
async def test_c08_config_update_uses_one_commit_boundary():
    db = _DB()
    result = await data_mod.update_api_config(
        primary_source="yfinance", cache_ttl_minutes=90, enable_cache=True,
        db=db, cache_service=Mock(),
    )
    assert result["settings"] == {
        "primary_source": "yfinance", "cache_ttl_minutes": 90, "enable_cache": True,
    }
    assert db.commits == 1 and db.rollbacks == 0

    class FailingConfigDB(_DB):
        async def execute(self, statement):
            result = await super().execute(statement)
            if self.executed == 2:
                raise RuntimeError("second setting failed")
            return result

    failed_db = FailingConfigDB()
    with pytest.raises(HTTPException) as raised:
        await data_mod.update_api_config(
            primary_source="yfinance", cache_ttl_minutes=90, enable_cache=True,
            db=failed_db, cache_service=Mock(),
        )
    assert raised.value.status_code == 500
    assert failed_db.commits == 0 and failed_db.rollbacks == 1


@pytest.mark.asyncio
async def test_c09_post_commit_refresh_failure_does_not_rollback():
    db = _DB(refresh_error=RuntimeError("private/path"))
    market = _Market()
    with patch("app.api.portfolio.GlobalDataService", return_value=SimpleNamespace(get_service=lambda: market)):
        with pytest.raises(HTTPException) as raised:
            await add_portfolio_position(
                PortfolioPositionCreate(ticker="AAPL", weight=.2, quantity=1, buy_price=10),
                db=db, data_service=market,
            )
    assert raised.value.status_code == 500
    assert "committed" in str(raised.value.detail).lower()
    assert db.commits == 1 and db.rollbacks == 0


@pytest.mark.asyncio
async def test_c10_bulk_duplicates_are_explicitly_reconciled():
    db = _DB(["AAPL"])
    market = _Market()
    result = await bulk_add_positions(
        BulkAddRequest(
            positions=[PortfolioPositionBase(ticker="AAPL", weight=.2, quantity=1, buy_price=10)],
            auto_normalize=False,
        ),
        db=db, data_service=market,
    )
    assert result.submitted == 1
    assert result.added + result.failed + result.skipped == result.submitted
    assert result.skipped == 1
    assert result.duplicates == ["AAPL"]


@pytest.mark.asyncio
async def test_c11_internal_error_text_is_not_returned_or_logged(caplog):
    db = _DB(commit_error=RuntimeError("provider=https://secret.example?api_key=NO"))
    with caplog.at_level("ERROR"):
        with pytest.raises(HTTPException) as raised:
            await data_mod.update_api_config(
                primary_source=None, cache_ttl_minutes=10, enable_cache=True,
                db=db, cache_service=Mock(),
            )
    assert raised.value.status_code == 500
    assert "secret.example" not in str(raised.value.detail)
    assert "NO" not in caplog.text


@pytest.mark.asyncio
async def test_c12_csv_neutralizes_formula_cells():
    now = datetime.now()
    position = SimpleNamespace(
        ticker="AAPL", weight=1, region="US", last_price=1, market_value=1,
        sector="=1+1", industry="+cmd", custom_name="@SUM(1,1)",
        added_on=now, updated_on=now,
    )
    response = await export_portfolio_csv(db=_DB([position]))
    text = response.body.decode()
    assert response.media_type == "text/csv"
    assert "'=1+1" in text and "'+cmd" in text and "'@SUM(1,1)" in text


@pytest.mark.asyncio
async def test_c13_dates_and_collections_are_bounded_before_vendor():
    market = _Market()
    market.fetch_ohlcv_batch = AsyncMock(return_value={"data": {}, "failed_tickers": []})
    invalid = [
        BatchStockDataRequest(tickers=["AAPL"], start="2025-02-30", end="2025-03-01"),
        BatchStockDataRequest(tickers=["AAPL"], start="2025-03-02", end="2025-03-01"),
        BatchStockDataRequest(tickers=[f"T{i}" for i in range(51)]),
    ]
    for request in invalid:
        with pytest.raises(HTTPException) as raised:
            await get_batch_stock_data(request, data_service=market)
        assert raised.value.status_code == 422
    market.fetch_ohlcv_batch.assert_not_awaited()


def test_c14_localhost_posture_is_retained():
    from app.config import settings
    source = Path(portfolio_mod.__file__).resolve().parents[2] / "main.py"
    # The source assertion is intentionally narrow: no enterprise auth was
    # introduced, and the executable default remains loopback.
    main_source = source.read_text(encoding="utf-8")
    assert 'host="127.0.0.1"' in main_source
    assert "AuthenticationMiddleware" not in main_source
    assert settings.api_host == "127.0.0.1"


@pytest.mark.asyncio
async def test_c05_source_switch_invalidates_weighted_tail_memo(async_client, test_db):
    analytics_mod._TAILS_RESPONSE_CACHE.clear()
    analytics_mod._TAILS_RESPONSE_CACHE[("synthetic",)] = (0.0, {"cached": True})
    response = await async_client.put(
        "/api/v1/data/config", params={"primary_source": "yfinance"}
    )
    assert response.status_code == 200
    assert analytics_mod._TAILS_RESPONSE_CACHE == {}


@pytest.mark.asyncio
async def test_c02_wide_return_builder_preserves_prelisting_mask():
    """A newly listed asset is absent, not backfilled with flat prices."""
    dates = pd.date_range("2025-01-01", periods=4, freq="D")
    service = SimpleNamespace()

    async def fetch(ticker, start, end):
        if ticker == "A":
            return pd.DataFrame({"close": [100.0, 110.0, 120.0, 121.0]}, index=dates)
        return pd.DataFrame({"close": [50.0, 55.0]}, index=dates[2:])

    service.fetch_historical_data = fetch
    returns_df, portfolio, coverage = await _build_wide_returns(
        ["A", "B"], {"A": 0.5, "B": 0.5}, "2025-01-01", "2025-01-04", service
    )
    assert pd.isna(returns_df.loc[dates[1], "B"])
    assert not np.isclose(returns_df.loc[dates[1], "A"], 0.0)
    expected = [0.10, 120.0 / 110.0 - 1.0, (0.5 * (121.0 / 120.0 - 1.0) + 0.5 * 0.10)]
    assert portfolio.tolist() == pytest.approx(expected)
    assert coverage["covered_days"] == len(portfolio)


def test_c11_tail_schema_accepts_confidence_neutral_fields():
    metrics = EVTPOTVarMetrics(
        confidence_level=0.95,
        evt_pot_var=-0.02,
        evt_pot_es=-0.03,
        historical_var=-0.015,
        historical_es=-0.02,
        threshold_u=-0.01,
        exceedances_count=5,
        total_observations=100,
        is_fat_tailed=True,
    )
    assert metrics.evt_pot_var == -0.02
    assert metrics.evt_pot_var_99 is None


@pytest.mark.asyncio
async def test_b13_data_route_maps_provider_outage_and_keeps_canonical_ticker(async_client):
    market = _Market()
    market._get_cached_data = AsyncMock(return_value=None)
    market.fetch_historical_data = AsyncMock(
        side_effect=ProviderUnavailableError("vendor timeout with secret token", provider="yfinance")
    )
    from main import app
    app.dependency_overrides[data_mod.get_data_service] = lambda: market
    try:
        response = await async_client.get("/api/v1/data/RELIANCE?start=2025-01-01&end=2025-01-02")
        assert response.status_code == 503
        assert "secret token" not in response.text
    finally:
        app.dependency_overrides.pop(data_mod.get_data_service, None)


@pytest.mark.asyncio
async def test_c13_coint_route_threads_requested_lookback_identity():
    dates = pd.date_range("2025-01-01", periods=80, freq="B")
    market = SimpleNamespace()

    async def fetch(ticker, start, end):
        return pd.DataFrame({"close": np.linspace(100.0, 120.0, len(dates))}, index=dates)

    market.fetch_historical_data = fetch
    captured = {}

    class FakeCoint:
        def __init__(self, **_kwargs):
            pass

        async def scan_pairs(self, **kwargs):
            captured.update(kwargs)
            return analytics_mod.CointScannerResponse(
                as_of="2025-04-01", universe_size=2, scanned_pairs_count=1,
                cointegrated_pairs_count=0, pairs=[],
            )

    with patch.object(analytics_mod, "CointegrationService", FakeCoint):
        await get_cointegration_pairs(
            tickers="A,B", lookback_days=60, p_value_threshold=0.05,
            max_half_life=None, include_spread_series=False,
            db=Mock(), data_service=market, cache_service=Mock(),
        )
    assert captured["lookback_days"] == 60

