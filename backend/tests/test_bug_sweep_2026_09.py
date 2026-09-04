"""
Bug-sweep 2026-09 regression tests: each test went red against the buggy code
before its fix.

1. bulk_add rejected valid NSE tickers longer than 10 chars (MOTHERSON.NS)
2. RELIANCE vs RELIANCE.NS stored as two positions (no canonicalization)
3. rebalance fabricated a 100000.0 portfolio when market values were zero
4. rebalance could not fully exit a position (target_qty floored at 1 share)
5. _empty_concentration returned fabricated HHI/N_eff instead of zeros
6. /concentration empty state omitted diversification_score / gini_coefficient
7. volatility-sizing fabricated a 100000.0 portfolio value for trade sizing
8. auto_normalize only fired when weights summed above 1.0
9. websocket analytics truncated mixed-inception histories via dropna()
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import PortfolioPosition, StockTimeseries
from app.services.analytics_engine import AnalyticsEngine
from app.services.data_service import canonical_ticker


# ---------------------------------------------------------------------------
# canonical_ticker
# ---------------------------------------------------------------------------

def test_canonical_ticker_normalization():
    assert canonical_ticker("RELIANCE") == "RELIANCE.NS"
    assert canonical_ticker("RELIANCE.NS") == "RELIANCE.NS"
    assert canonical_ticker("500112.BO") == "500112.BO"
    assert canonical_ticker("infy.ns") == "INFY.NS"
    assert canonical_ticker("^NSEI") == "^NSEI"
    assert canonical_ticker("USDINR=X") == "USDINR=X"


# ---------------------------------------------------------------------------
# B2: bulk_add ticker format validation
# ---------------------------------------------------------------------------

def _bulk_market(quote_price=200.0):
    service = Mock()
    ds = service.get_service.return_value
    ds.validate_ticker = AsyncMock(return_value=True)
    ds.fetch_quote = AsyncMock(return_value={
        "current_price": quote_price, "sector": "Auto", "industry": "Components"
    })
    return patch("app.api.portfolio.GlobalDataService", return_value=service)


@pytest.mark.asyncio
async def test_bulk_add_accepts_long_nse_ticker(async_client: AsyncClient, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()

    with _bulk_market():
        resp = await async_client.post("/api/v1/portfolio/bulk_add", json={
            "positions": [
                {"ticker": "MOTHERSON.NS", "weight": 0.5, "quantity": 10.0, "buy_price": 100.0},
                {"ticker": "BAJAJ-AUTO.NS", "weight": 0.5, "quantity": 5.0, "buy_price": 100.0},
            ]
        })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["added"] == 2
    assert data["failed"] == 0

    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()


@pytest.mark.asyncio
async def test_bulk_add_rejects_malformed_ticker(async_client: AsyncClient, test_db: AsyncSession):
    resp = await async_client.post("/api/v1/portfolio/bulk_add", json={
        "positions": [
            {"ticker": "BAD TICKER!", "weight": 0.5, "quantity": 10.0, "buy_price": 100.0}
        ]
    })
    assert resp.status_code in [400, 422]
    assert "invalid ticker format" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# B3: canonical duplicate detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_position_canonical_duplicate_409(async_client: AsyncClient, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()

    test_db.add(PortfolioPosition(
        ticker="RELIANCE.NS", weight=1.0, quantity=10.0,
        buy_price=2500.0, last_price=2600.0, market_value=26000.0,
    ))
    await test_db.commit()

    service = Mock()
    service.get_service.return_value.validate_ticker = AsyncMock(return_value=True)
    with patch("app.api.portfolio.GlobalDataService", return_value=service):
        resp = await async_client.post("/api/v1/portfolio/add", json={
            "ticker": "RELIANCE", "weight": 0.5, "quantity": 5.0, "buy_price": 2500.0,
        })
    assert resp.status_code == 409
    assert "RELIANCE.NS" in resp.json()["detail"]

    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()


# ---------------------------------------------------------------------------
# B1 + B5: rebalance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rebalance_rejects_zero_portfolio_value(async_client: AsyncClient, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()

    test_db.add(PortfolioPosition(
        ticker="ZEROPV.NS", weight=1.0, quantity=10.0,
        buy_price=100.0, last_price=0.0, market_value=0.0,
    ))
    await test_db.commit()

    resp = await async_client.post("/api/v1/portfolio/rebalance", json={
        "new_weights": {"ZEROPV.NS": 1.0}, "dry_run": True
    })
    assert resp.status_code == 400
    assert "market value" in resp.json()["detail"].lower()

    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()


@pytest.mark.asyncio
async def test_rebalance_allows_full_exit(async_client: AsyncClient, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()

    test_db.add(PortfolioPosition(
        ticker="EXITME.NS", weight=1.0, quantity=100.0,
        buy_price=100.0, last_price=100.0, market_value=10000.0,
    ))
    await test_db.commit()

    resp = await async_client.post("/api/v1/portfolio/rebalance", json={
        "new_weights": {"EXITME.NS": 0.0}, "dry_run": True
    })
    assert resp.status_code == 200
    order = resp.json()["orders"][0]
    assert order["target_quantity"] == 0.0
    assert order["shares_delta"] == -100

    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()


# ---------------------------------------------------------------------------
# B6 + B7: truthful empty concentration
# ---------------------------------------------------------------------------

def test_empty_concentration_truthful():
    result = AnalyticsEngine()._empty_concentration()
    assert result["error"]
    for key in ("largest_position", "top_3", "top_5", "top_10",
                "herfindahl_index", "effective_positions",
                "diversification_score", "gini_coefficient"):
        assert key in result, f"missing key: {key}"
        assert result[key] == 0.0, f"{key} must be 0.0, got {result[key]}"


@pytest.mark.asyncio
async def test_concentration_endpoint_empty_state_keys(async_client: AsyncClient, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()

    resp = await async_client.get("/api/v1/analytics/concentration")
    assert resp.status_code == 200
    data = resp.json()
    assert data["diversification_score"] == 0.0
    assert data["gini_coefficient"] == 0.0
    assert data["herfindahl_index"] == 0.0


# ---------------------------------------------------------------------------
# B1: volatility-sizing must not fabricate a portfolio value
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_volatility_sizing_zero_pv_returns_error(async_client: AsyncClient, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()

    test_db.add(PortfolioPosition(
        ticker="NOPV.NS", weight=1.0, quantity=10.0,
        buy_price=100.0, last_price=0.0, market_value=0.0,
    ))
    await test_db.commit()

    resp = await async_client.get("/api/v1/analytics/volatility-sizing")
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    assert data["trades"] == {"NOPV.NS": {"shares_delta": 0, "amount": 0.0}}

    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()


# ---------------------------------------------------------------------------
# B9: auto_normalize below 1.0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_add_auto_normalize_below_one(async_client: AsyncClient, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()

    with _bulk_market():
        resp = await async_client.post("/api/v1/portfolio/bulk_add", json={
            "positions": [
                {"ticker": "AAAA.NS", "weight": 0.3, "quantity": 10.0, "buy_price": 100.0},
                {"ticker": "BBBB.NS", "weight": 0.3, "quantity": 10.0, "buy_price": 100.0},
            ],
            "auto_normalize": True
        })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["normalized"] is True
    assert abs(sum(p["weight"] for p in data["positions"]) - 1.0) < 1e-6

    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()


# ---------------------------------------------------------------------------
# B4: websocket analytics must not truncate mixed-inception histories
# ---------------------------------------------------------------------------

class _SessionCtx:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *args):
        pass


@pytest.mark.asyncio
async def test_websocket_analytics_mixed_inception(test_db: AsyncSession):
    from app.api.websocket import send_analytics_update, manager

    await test_db.execute(delete(PortfolioPosition))
    await test_db.execute(delete(StockTimeseries))
    await test_db.commit()

    end = datetime.utcnow().date()
    # AAA has 30 days of history; BBB was listed 4 days ago
    rng = np.random.default_rng(11)
    aaa_close = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, 30)))
    bbb_close = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, 4)))
    for i in range(30):
        test_db.add(StockTimeseries(
            ticker="AAA.NS", date=end - timedelta(days=29 - i),
            close=float(aaa_close[i]), adj_close=float(aaa_close[i]),
            open=float(aaa_close[i]), high=float(aaa_close[i]), low=float(aaa_close[i]),
            volume=1000, source_used="test", fetch_status="fresh",
        ))
    for i in range(4):
        test_db.add(StockTimeseries(
            ticker="BBB.NS", date=end - timedelta(days=3 - i),
            close=float(bbb_close[i]), adj_close=float(bbb_close[i]),
            open=float(bbb_close[i]), high=float(bbb_close[i]), low=float(bbb_close[i]),
            volume=1000, source_used="test", fetch_status="fresh",
        ))
    test_db.add(PortfolioPosition(
        ticker="AAA.NS", weight=0.5, quantity=10.0,
        buy_price=100.0, last_price=float(aaa_close[-1]), market_value=float(aaa_close[-1]) * 10,
    ))
    test_db.add(PortfolioPosition(
        ticker="BBB.NS", weight=0.5, quantity=10.0,
        buy_price=100.0, last_price=float(bbb_close[-1]), market_value=float(bbb_close[-1]) * 10,
    ))
    await test_db.commit()

    broadcast_mock = AsyncMock()
    with patch("app.api.websocket.SessionLocal", lambda: _SessionCtx(test_db)), \
         patch.object(manager, "broadcast", broadcast_mock):
        await send_analytics_update()

    assert broadcast_mock.call_args_list, "expected an analytics_update broadcast"
    payload = broadcast_mock.call_args_list[0].args[0]["data"]
    assert payload["positions_count"] == 2
    # With the old dropna() the shared frame collapsed to 4 rows (< 6),
    # leaving realized volatility at exactly 0. The ffill fix keeps all 30 days.
    assert payload["realized_volatility"] > 0.0

    await test_db.execute(delete(PortfolioPosition))
    await test_db.execute(delete(StockTimeseries))
    await test_db.commit()


# ---------------------------------------------------------------------------
# 10. Cointegration OU parameter estimation zero-variance guard
# ---------------------------------------------------------------------------

def test_compute_ou_parameters_zero_variance_no_warning():
    from app.services.cointegration_service import compute_ou_parameters
    # Degenerate constant series
    constant_spread = np.full(50, 100.0)
    theta, half_life = compute_ou_parameters(constant_spread)
    assert theta is None
    assert half_life is None

    # Normal mean-reverting series
    np.random.seed(42)
    # Ornstein-Uhlenbeck process simulation
    ou_series = np.zeros(100)
    for t in range(1, 100):
        ou_series[t] = ou_series[t-1] - 0.2 * ou_series[t-1] + np.random.normal(0, 1)
    theta_mr, hl_mr = compute_ou_parameters(ou_series)
    assert theta_mr is not None
    assert hl_mr is not None
    assert theta_mr > 0
    assert hl_mr > 0

