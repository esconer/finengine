"""
Wave-1 regression tests: critical correctness bugs found in the 2026-08-26 audit.

Each test went red against the buggy code before its fix:
1. market_value corruption (100000 x weight committed on GET/{ticker} + /normalize)
2. global exception handler returned a plain dict instead of a JSONResponse
3. GET /portfolio crashed (ZeroDivisionError -> 500) when every weight was zero
4. /forecast-risk ignored DB weights (equal-mean of asset returns)
"""

from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import pandas as pd
import pytest
from starlette.responses import JSONResponse

from main import global_exception_handler


def _frame(days=260, seed=7, ticker="TEST", closes=None):
    dates = pd.date_range("2025-01-01", periods=days, freq="B")
    rng = np.random.default_rng(seed)
    if closes is None:
        close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, days))), index=dates)
    else:
        close = pd.Series(closes, index=dates)
    return pd.DataFrame({
        "date": dates, "open": close * 0.995, "high": close * 1.008,
        "low": close * 0.992, "close": close, "adj_close": close,
        "volume": np.full(days, 250_000.0), "ticker": ticker,
    })


def _patch_portfolio_market(quote=None):
    service = Mock()
    service.get_service.return_value.fetch_quote = AsyncMock(return_value=quote)
    return patch("app.api.portfolio.GlobalDataService", return_value=service)


@pytest.mark.api
class TestMarketValueIntegrity:
    """market_value must always equal quantity x last_price."""

    @pytest.mark.asyncio
    async def test_get_position_recomputes_mv_from_quantity(self, async_client, seeded_positions):
        """GET /{ticker} refreshes price and recomputes mv = quantity * new_price."""
        quote = {"ticker": "AAPL", "current_price": 200.0}
        with _patch_portfolio_market(quote=quote):
            resp = await async_client.get("/api/v1/portfolio/AAPL")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # BUG was: market_value = 100000 * 0.4 = 40000
        assert body["market_value"] == pytest.approx(100 * 200.0)

    @pytest.mark.asyncio
    async def test_get_position_persists_corrected_mv(self, async_client, seeded_positions, test_db):
        """The correction is committed: reloaded row carries quantity x price."""
        from sqlalchemy import select
        from app.models.database import PortfolioPosition

        quote = {"ticker": "AAPL", "current_price": 200.0}
        with _patch_portfolio_market(quote=quote):
            resp = await async_client.get("/api/v1/portfolio/AAPL")
        assert resp.status_code == 200, resp.text

        result = await test_db.execute(
            select(PortfolioPosition).where(PortfolioPosition.ticker == "AAPL")
        )
        row = result.scalar_one()
        assert row.market_value == pytest.approx(20_000.0)

    @pytest.mark.asyncio
    async def test_normalize_keeps_market_values(self, async_client, seeded_positions):
        """Renormalizing weights must not touch stored market values."""
        seeded_positions[0].weight = 0.2  # totals 0.8 -> real renormalization happens
        seeded_positions[1].weight = 0.6
        from app.db.database import get_db_session  # noqa: F401  (session shared via fixture)

        resp = await async_client.post("/api/v1/portfolio/normalize")
        assert resp.status_code == 200, resp.text
        # BUG was: mv overwritten to 100000 * normalized_weight (25000 / 75000)
        assert seeded_positions[0].market_value == pytest.approx(18_000.0)
        assert seeded_positions[1].market_value == pytest.approx(21_000.0)


@pytest.mark.api
class TestZeroWeightGuard:
    @pytest.mark.asyncio
    async def test_all_zero_weights_do_not_crash(self, async_client, test_db):
        from app.models.database import PortfolioPosition

        test_db.add_all([
            PortfolioPosition(ticker="ZEROA", weight=0.0, quantity=10, buy_price=50.0,
                              last_price=60.0, market_value=600.0),
            PortfolioPosition(ticker="ZEROB", weight=0.0, quantity=20, buy_price=25.0,
                              last_price=30.0, market_value=600.0),
        ])
        await test_db.commit()

        with _patch_portfolio_market(quote=None):
            resp = await async_client.get("/api/v1/portfolio")
        # Clean up: test.db is file-backed and shared across tests.
        await test_db.execute(PortfolioPosition.__table__.delete())
        await test_db.commit()
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Weights carry no information; sector shares fall back to market-value split.
        assert abs(sum(body["sectors"].values()) - 1.0) < 1e-9


class TestExceptionHandlerContract:
    @pytest.mark.asyncio
    async def test_returns_json_response(self):
        request = Mock()
        resp = await global_exception_handler(request, RuntimeError("boom"))
        assert isinstance(resp, JSONResponse)
        assert resp.status_code == 500


@pytest.mark.api
class TestForecastRiskWeights:
    @pytest.mark.asyncio
    async def test_portfolio_series_is_weighted(self, async_client, seeded_positions):
        """The series handed to forecast_volatility must weight by DB allocation,
        not be the equal-weight mean of asset returns."""
        flat = _frame(closes=[100.0] * 260, ticker="AAPL")          # returns all 0
        osc = _frame(
            closes=[100.0 if i % 2 == 0 else 102.0 for i in range(260)], ticker="MSFT"
        )                                                            # returns +/-0.02

        service = Mock()
        def _fetch(ticker, start, end, force_refresh=False):
            return {"AAPL": flat, "MSFT": osc}[ticker]
        service.get_service.return_value.fetch_historical_data = AsyncMock(side_effect=_fetch)

        captured = {}

        async def _capture(series, model, horizon):
            if "portfolio_series" not in captured:   # first call == portfolio series
                captured["portfolio_series"] = series
            return {"volatility_forecast": 0.12, "var_forecast": -0.02}

        engine = Mock()
        engine.get_engine.return_value.forecast_volatility = AsyncMock(side_effect=_capture)

        bench = Mock()
        with patch("app.api.analytics.GlobalDataService", return_value=service), \
             patch("app.api.analytics.BenchmarkService", return_value=bench), \
             patch("app.api.analytics.GlobalAnalyticsEngine", return_value=engine):
            resp = await async_client.get("/api/v1/analytics/forecast-risk")

        assert resp.status_code == 200, resp.text

        r_microsoft = pd.Series(osc["close"]).pct_change().dropna().reset_index(drop=True)
        total_mv = 18_000.0 + 21_000.0
        w_msft = 21_000.0 / total_mv                              # 0.5384... from DB rows
        expected = (w_msft * r_microsoft).reset_index(drop=True)

        got = pd.Series(captured["portfolio_series"]).reset_index(drop=True)
        assert len(got) == len(expected)
        # BUG was: equal-weight mean -> 0.5 * r_msft (plus zero AAPL col averaged in)
        np.testing.assert_allclose(got.to_numpy(), expected.to_numpy(), atol=1e-12)
