"""
Comprehensive API test suite for app.api.portfolio endpoints to achieve 100% coverage.
Tests all endpoints: get_portfolio, add, bulk_add, get single, update, delete, normalize, export/csv,
including all validation paths, filters, currencies, error branches, and helper methods.
"""

from unittest.mock import AsyncMock, Mock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.models.database import PortfolioPosition
from app.api.portfolio import (
    _validate_portfolio_position,
    _generate_ticker_suggestions,
    _is_similar_ticker,
    _update_portfolio_prices
)


@pytest.mark.api
class TestPortfolioAPIEndpoints:
    @pytest.mark.asyncio
    async def test_get_portfolio_empty(self, async_client, test_db: AsyncSession):
        # Ensure database is clean
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

        resp = await async_client.get("/api/v1/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_positions"] == 0
        assert data["total_value"] == 0.0
        assert data["positions"] == []
        assert data["sectors"] == {}

    @pytest.mark.asyncio
    async def test_add_position_validation_and_suggestions(self, async_client, test_db: AsyncSession):
        mock_ds = Mock()
        mock_ds.validate_ticker = AsyncMock(return_value=False)

        with patch("app.api.portfolio.GlobalDataService") as mock_gds:
            mock_gds.return_value.get_service.return_value = mock_ds
            # Invalid ticker with suggestion
            resp = await async_client.post("/api/v1/portfolio/add", json={
                "ticker": "APPL",
                "weight": 0.5,
                "quantity": 10.0,
                "buy_price": 150.0,
                "region": "US"
            })
            assert resp.status_code == 400
            err = resp.json()["detail"]
            assert err["error"] == "INVALID_TICKER"
            assert "AAPL" in err["suggestions"]

    @pytest.mark.asyncio
    async def test_add_position_duplicate_and_quote_fail(self, async_client, test_db: AsyncSession):
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

        # Seed an existing position
        pos = PortfolioPosition(
            ticker="TCS.NS",
            weight=0.5,
            quantity=10.0,
            buy_price=3500.0,
            last_price=3600.0,
            market_value=36000.0,
            region="IN",
            sector="Technology"
        )
        test_db.add(pos)
        await test_db.commit()

        mock_ds = Mock()
        mock_ds.validate_ticker = AsyncMock(return_value=True)

        with patch("app.api.portfolio.GlobalDataService") as mock_gds:
            mock_gds.return_value.get_service.return_value = mock_ds
            # Duplicate ticker -> 409
            resp = await async_client.post("/api/v1/portfolio/add", json={
                "ticker": "TCS.NS",
                "weight": 0.5,
                "quantity": 10.0,
                "buy_price": 3500.0,
                "region": "IN"
            })
            assert resp.status_code == 409

            # Quote fetch returns None -> 400
            mock_ds.fetch_quote = AsyncMock(return_value=None)
            resp_quote_fail = await async_client.post("/api/v1/portfolio/add", json={
                "ticker": "NEWTICKER.NS",
                "weight": 0.5,
                "quantity": 10.0,
                "buy_price": 100.0,
                "region": "IN"
            })
            assert resp_quote_fail.status_code == 400

        # Clean up
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

    @pytest.mark.asyncio
    async def test_add_position_success_and_metrics(self, async_client, test_db: AsyncSession):
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

        quote = {
            "ticker": "INFY.NS",
            "current_price": 1600.0,
            "sector": "Technology",
            "industry": "IT Services"
        }
        mock_ds = Mock()
        mock_ds.validate_ticker = AsyncMock(return_value=True)
        mock_ds.fetch_quote = AsyncMock(return_value=quote)

        with patch("app.api.portfolio.GlobalDataService") as mock_gds:
            mock_gds.return_value.get_service.return_value = mock_ds
            resp = await async_client.post("/api/v1/portfolio/add", json={
                "ticker": "INFY.NS",
                "weight": 0.4,
                "quantity": 100.0,
                "buy_price": 1500.0,
                "region": "IN",
                "custom_name": "Infosys Ltd"
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["ticker"] == "INFY.NS"
            assert data["total_cost"] == 150000.0
            assert data["current_value"] == 160000.0
            assert data["unrealized_gain_loss"] == 10000.0
            assert round(data["unrealized_gain_loss_pct"], 2) == 6.67
            assert data["custom_name"] == "Infosys Ltd"

        # Clean up
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

    @pytest.mark.asyncio
    async def test_get_portfolio_with_filters_and_currencies(self, async_client, test_db: AsyncSession):
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

        pos1 = PortfolioPosition(
            ticker="RELIANCE.NS",
            weight=0.6,
            quantity=10.0,
            buy_price=2500.0,
            last_price=2600.0,
            market_value=26000.0,
            region="IN",
            sector="Energy"
        )
        pos2 = PortfolioPosition(
            ticker="AAPL",
            weight=0.4,
            quantity=5.0,
            buy_price=150.0,
            last_price=180.0,
            market_value=900.0,
            region="US",
            sector="Technology"
        )
        test_db.add_all([pos1, pos2])
        await test_db.commit()

        mock_ds = Mock()
        mock_ds.fetch_quote = AsyncMock(side_effect=lambda t: {"current_price": 2600.0 if "RELIANCE" in t else 180.0})

        with patch("app.api.portfolio.GlobalDataService") as mock_gds:
            mock_gds.return_value.get_service.return_value = mock_ds
            # Filter by region
            resp_in = await async_client.get("/api/v1/portfolio?region=IN")
            assert resp_in.status_code == 200
            assert resp_in.json()["total_positions"] == 1
            assert resp_in.json()["positions"][0]["ticker"] == "RELIANCE.NS"

            # Filter by sector
            resp_tech = await async_client.get("/api/v1/portfolio?sector=Technology")
            assert resp_tech.status_code == 200
            assert resp_tech.json()["total_positions"] == 1

            # Currency = USD
            resp_usd = await async_client.get("/api/v1/portfolio?currency=USD")
            assert resp_usd.status_code == 200
            assert resp_usd.json()["total_value"] > 0

        # Clean up
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

    @pytest.mark.asyncio
    async def test_get_portfolio_zero_weights_fallback(self, async_client, test_db: AsyncSession):
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

        pos = PortfolioPosition(
            ticker="HDFCBANK.NS",
            weight=0.0,
            quantity=10.0,
            buy_price=1500.0,
            last_price=1600.0,
            market_value=16000.0,
            region="IN",
            sector="Financials"
        )
        test_db.add(pos)
        await test_db.commit()

        mock_ds = Mock()
        mock_ds.fetch_quote = AsyncMock(return_value={"current_price": 1600.0})

        with patch("app.api.portfolio.GlobalDataService") as mock_gds:
            mock_gds.return_value.get_service.return_value = mock_ds
            resp = await async_client.get("/api/v1/portfolio")
            assert resp.status_code == 200
            data = resp.json()
            assert "Financials" in data["sectors"]
            assert data["sectors"]["Financials"] == 1.0
            assert "total_weight" in data
            assert data["total_weight"] > 0

        # Clean up
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

    @pytest.mark.asyncio
    async def test_bulk_add_positions_comprehensive(self, async_client, test_db: AsyncSession):
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

        # 1. Validation error: negative quantity or buy_price
        resp_bad_qty = await async_client.post("/api/v1/portfolio/bulk_add", json={
            "positions": [{"ticker": "TCS.NS", "weight": 0.5, "quantity": -5.0, "buy_price": 100.0}]
        })
        assert resp_bad_qty.status_code in [400, 422]

        resp_bad_price = await async_client.post("/api/v1/portfolio/bulk_add", json={
            "positions": [{"ticker": "TCS.NS", "weight": 0.5, "quantity": 5.0, "buy_price": -100.0}]
        })
        assert resp_bad_price.status_code in [400, 422]

        resp_bad_weight = await async_client.post("/api/v1/portfolio/bulk_add", json={
            "positions": [{"ticker": "TCS.NS", "weight": 1.5, "quantity": 5.0, "buy_price": 100.0}]
        })
        assert resp_bad_weight.status_code in [400, 422]

        resp_bad_ticker = await async_client.post("/api/v1/portfolio/bulk_add", json={
            "positions": [{"ticker": "", "weight": 0.5, "quantity": 5.0, "buy_price": 100.0}]
        })
        assert resp_bad_ticker.status_code in [400, 422]

        # 2. External ticker validation failure
        mock_ds = Mock()
        mock_ds.validate_ticker = AsyncMock(return_value=False)
        with patch("app.api.portfolio.GlobalDataService") as mock_gds:
            mock_gds.return_value.get_service.return_value = mock_ds
            resp_inv_ticker = await async_client.post("/api/v1/portfolio/bulk_add", json={
                "positions": [{"ticker": "BADTICK", "weight": 0.5, "quantity": 5.0, "buy_price": 100.0}]
            })
            assert resp_inv_ticker.status_code == 400
            assert "Invalid tickers" in resp_inv_ticker.json()["detail"]

        # 3. Duplicate filtering and auto-normalize
        pos_existing = PortfolioPosition(
            ticker="OLD.NS",
            weight=0.5,
            quantity=10.0,
            buy_price=100.0,
            last_price=110.0,
            market_value=1100.0
        )
        test_db.add(pos_existing)
        await test_db.commit()

        mock_ds.validate_ticker = AsyncMock(return_value=True)
        mock_ds.fetch_quote = AsyncMock(side_effect=lambda t: None if "FAIL" in t else {"current_price": 200.0, "sector": "Tech", "industry": "Software"})

        with patch("app.api.portfolio.GlobalDataService") as mock_gds:
            mock_gds.return_value.get_service.return_value = mock_ds
            payload = {
                "positions": [
                    {"ticker": "OLD.NS", "weight": 0.5, "quantity": 10.0, "buy_price": 100.0},
                    {"ticker": "VALID1.NS", "weight": 0.7, "quantity": 10.0, "buy_price": 100.0},
                    {"ticker": "VALID2.NS", "weight": 0.7, "quantity": 10.0, "buy_price": 100.0},
                    {"ticker": "FAIL.NS", "weight": 0.5, "quantity": 10.0, "buy_price": 100.0}
                ],
                "auto_normalize": True
            }
            resp_bulk = await async_client.post("/api/v1/portfolio/bulk_add", json=payload)
            assert resp_bulk.status_code in [200, 400]
            data = resp_bulk.json()
            assert "added" in data or "added_count" in data or "positions" in data
            assert data["failed"] == 1
            assert data["normalized"] is True
            # Weights should sum to 1.0 for added positions
            assert abs(sum(p["weight"] for p in data["positions"]) - 1.0) < 1e-4

        # Clean up
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

    @pytest.mark.asyncio
    async def test_get_update_delete_single_position(self, async_client, test_db: AsyncSession):
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

        pos = PortfolioPosition(
            ticker="MARUTI.NS",
            weight=0.5,
            quantity=10.0,
            buy_price=10000.0,
            last_price=10500.0,
            market_value=105000.0,
            region="IN",
            sector="Auto",
            industry="Automobiles"
        )
        test_db.add(pos)
        await test_db.commit()

        mock_ds = Mock()
        mock_ds.fetch_quote = AsyncMock(return_value={"current_price": 10800.0})

        with patch("app.api.portfolio.GlobalDataService") as mock_gds:
            mock_gds.return_value.get_service.return_value = mock_ds
            
            # GET single position
            resp_get = await async_client.get("/api/v1/portfolio/MARUTI.NS")
            assert resp_get.status_code == 200
            assert resp_get.json()["last_price"] == 10800.0

            # GET 404
            resp_404 = await async_client.get("/api/v1/portfolio/NONEXISTENT")
            assert resp_404.status_code == 404

            # PUT update validation errors
            resp_bad_w = await async_client.put("/api/v1/portfolio/MARUTI.NS", json={"weight": 1.5})
            assert resp_bad_w.status_code in [400, 422]

            resp_bad_q = await async_client.put("/api/v1/portfolio/MARUTI.NS", json={"quantity": -1.0})
            assert resp_bad_q.status_code in [400, 422]

            resp_bad_p = await async_client.put("/api/v1/portfolio/MARUTI.NS", json={"buy_price": 0.0})
            assert resp_bad_p.status_code in [400, 422]

            # PUT 404
            resp_put_404 = await async_client.put("/api/v1/portfolio/NONEXISTENT", json={"quantity": 20.0})
            assert resp_put_404.status_code == 404

            # PUT valid update
            resp_update = await async_client.put("/api/v1/portfolio/MARUTI.NS", json={
                "weight": 0.8,
                "quantity": 15.0,
                "buy_price": 10200.0,
                "custom_name": "Maruti Suzuki India"
            })
            assert resp_update.status_code == 200
            assert resp_update.json()["quantity"] == 15.0
            assert resp_update.json()["custom_name"] == "Maruti Suzuki India"

            # DELETE 404
            resp_del_404 = await async_client.delete("/api/v1/portfolio/NONEXISTENT")
            assert resp_del_404.status_code == 404

            # DELETE success
            resp_del = await async_client.delete("/api/v1/portfolio/MARUTI.NS")
            assert resp_del.status_code == 200
            assert resp_del.json()["success"] is True

        # Test QH-02: Auto-normalize remaining position weights on delete
        await test_db.execute(delete(PortfolioPosition))
        p1 = PortfolioPosition(ticker="P1.NS", weight=0.2, quantity=10.0, buy_price=100.0, last_price=100.0, market_value=1000.0)
        p2 = PortfolioPosition(ticker="P2.NS", weight=0.3, quantity=10.0, buy_price=100.0, last_price=100.0, market_value=1000.0)
        p3 = PortfolioPosition(ticker="P3.NS", weight=0.5, quantity=10.0, buy_price=100.0, last_price=100.0, market_value=1000.0)
        test_db.add_all([p1, p2, p3])
        await test_db.commit()

        # Delete P3 (0.5 weight)
        resp_del_p3 = await async_client.delete("/api/v1/portfolio/P3.NS")
        assert resp_del_p3.status_code == 200
        assert resp_del_p3.json()["data"]["weights_renormalized"] is True

        # Remaining P1 and P2 should sum to 1.0 (0.2/0.5 = 0.4, 0.3/0.5 = 0.6)
        rem_res = await test_db.execute(select(PortfolioPosition))
        remaining = rem_res.scalars().all()
        assert len(remaining) == 2
        assert abs(sum(p.weight for p in remaining) - 1.0) < 1e-4
        weights_by_ticker = {p.ticker: p.weight for p in remaining}
        assert abs(weights_by_ticker["P1.NS"] - 0.4) < 1e-4
        assert abs(weights_by_ticker["P2.NS"] - 0.6) < 1e-4

        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

    @pytest.mark.asyncio
    async def test_export_csv_and_normalize(self, async_client, test_db: AsyncSession):
        # Empty export -> 404
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

        resp_csv_empty = await async_client.get("/api/v1/portfolio/export/csv")
        assert resp_csv_empty.status_code == 404

        # Empty normalize -> 404
        resp_norm_empty = await async_client.post("/api/v1/portfolio/normalize")
        assert resp_norm_empty.status_code == 404

        # Add positions
        pos1 = PortfolioPosition(
            ticker="SBIN.NS",
            weight=0.3,
            quantity=100.0,
            buy_price=700.0,
            last_price=750.0,
            market_value=75000.0,
            region="IN",
            sector="Financial Services",
            industry="Banks"
        )
        pos2 = PortfolioPosition(
            ticker="LT.NS",
            weight=0.3,
            quantity=20.0,
            buy_price=3000.0,
            last_price=3200.0,
            market_value=64000.0,
            region="IN",
            sector="Industrials",
            industry="Engineering"
        )
        test_db.add_all([pos1, pos2])
        await test_db.commit()

        # Export CSV success
        resp_csv = await async_client.get("/api/v1/portfolio/export/csv")
        assert resp_csv.status_code == 200
        content = resp_csv.text
        assert "ticker,weight,region,last_price" in content
        assert "SBIN.NS" in content
        assert "LT.NS" in content

        # Normalize success
        resp_norm = await async_client.post("/api/v1/portfolio/normalize")
        assert resp_norm.status_code == 200
        assert "Portfolio weights normalized" in resp_norm.json()["message"]

        # Clean up
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()


class TestPortfolioHelpers:
    def test_validate_portfolio_position_rules(self):
        # Valid
        pos = PortfolioPosition(
            ticker="AAPL",
            weight=0.5,
            quantity=10.0,
            buy_price=150.0,
            last_price=160.0,
            market_value=1600.0
        )
        assert _validate_portfolio_position(pos) is True

        # Invalid ticker: disallowed characters
        pos.ticker = "BAD TICKER!"
        assert _validate_portfolio_position(pos) is False
        pos.ticker = "AAPL"

        # Invalid ticker: exceeds the 20-char NSE/BSE-compatible limit
        pos.ticker = "TOOLONGTICKERNAMEEXCEEDS20"
        assert _validate_portfolio_position(pos) is False
        pos.ticker = "AAPL"

        # Invalid weight
        pos.weight = 1.5
        assert _validate_portfolio_position(pos) is False
        pos.weight = 0.5

        # Invalid quantity
        pos.quantity = -1.0
        assert _validate_portfolio_position(pos) is False
        pos.quantity = 10.0

        # Invalid buy price
        pos.buy_price = 0.0
        assert _validate_portfolio_position(pos) is False
        pos.buy_price = 150.0

        # Invalid last price
        pos.last_price = 0.0
        assert _validate_portfolio_position(pos) is False
        pos.last_price = 160.0

        # Invalid market value mismatch
        pos.market_value = 5000.0
        assert _validate_portfolio_position(pos) is False
        pos.market_value = 1600.0

        # Exception
        assert _validate_portfolio_position(None) is False

    def test_ticker_suggestions_and_similarity(self):
        # Known corrections
        sug_appl = _generate_ticker_suggestions("APPL")
        assert "AAPL" in sug_appl

        sug_rel = _generate_ticker_suggestions("RELIANCE")
        assert "RELIANCE.NS" in sug_rel

        # Long ticker
        assert _is_similar_ticker("VERYLONGTICKER1", "VERYLONGTICKER2") is False

        # Close ticker
        assert _is_similar_ticker("AAP", "AAPL") is True

    @pytest.mark.asyncio
    async def test_update_portfolio_prices_exception_handling(self):
        pos = PortfolioPosition(ticker="FAIL", quantity=10, last_price=100.0, market_value=1000.0)
        mock_ds = Mock()
        mock_ds.fetch_quote = AsyncMock(side_effect=Exception("Quote error"))
        # Should not raise exception
        await _update_portfolio_prices([pos], mock_ds)

    @pytest.mark.asyncio
    async def test_rebalance_portfolio_success_and_errors(self, async_client, test_db: AsyncSession):
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

        # Seed two positions
        pos1 = PortfolioPosition(
            ticker="CIPLA.NS",
            weight=0.5,
            quantity=10.0,
            buy_price=1400.0,
            last_price=1400.0,
            market_value=14000.0,
            region="IN",
            sector="Healthcare"
        )
        pos2 = PortfolioPosition(
            ticker="NTPC.NS",
            weight=0.5,
            quantity=20.0,
            buy_price=300.0,
            last_price=300.0,
            market_value=6000.0,
            region="IN",
            sector="Utilities"
        )
        test_db.add_all([pos1, pos2])
        await test_db.commit()

        # 1. Success rebalance
        resp = await async_client.post(
            "/api/v1/portfolio/rebalance",
            json={"new_weights": {"CIPLA.NS": 0.7, "NTPC.NS": 0.3}}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["weights"]["CIPLA.NS"] == 0.7
        assert data["weights"]["NTPC.NS"] == 0.3

        # 2. Empty weights error
        resp_empty = await async_client.post(
            "/api/v1/portfolio/rebalance",
            json={"new_weights": {}}
        )
        assert resp_empty.status_code == 400

        # Clean up
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

        # 3. No positions in portfolio error
        resp_nopos = await async_client.post(
            "/api/v1/portfolio/rebalance",
            json={"new_weights": {"CIPLA.NS": 0.5}}
        )
        assert resp_nopos.status_code == 404
