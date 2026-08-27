"""
Unit tests for IndiaDataService, ADV liquidity limits, and India microstructure endpoints.
"""

from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete

from app.models.database import (
    NSEBhavcopy,
    NSEInstitutionalFlow,
    PortfolioPosition
)
from app.services.india_data_service import (
    IndiaDataService,
    compute_amihud_illiquidity,
    compute_days_to_liquidate
)


@pytest.mark.asyncio
class TestIndiaDataService:
    def test_math_primitives(self):
        # 1. Amihud illiquidity
        returns = pd.Series([0.01, -0.02, 0.015, -0.005])
        rupee_vol = pd.Series([1e7, 2e7, 1.5e7, 3e7])
        amihud = compute_amihud_illiquidity(returns, rupee_vol)
        assert amihud > 0.0

        # Empty fallback
        assert compute_amihud_illiquidity(pd.Series([]), pd.Series([])) == 0.0

        # 2. Days to liquidate
        # ₹5L position in ₹1Cr ADV stock @ 10% participation = 0.5d (500000 / 1000000 = 0.5)
        # ₹50L position in ₹1Cr ADV stock @ 10% participation = 5.0d
        days = compute_days_to_liquidate(5000000.0, 10000000.0, 0.10)
        assert abs(days - 5.0) < 1e-4

        # Zero fallback
        assert compute_days_to_liquidate(0.0, 1000.0, 0.10) == 0.0
        assert compute_days_to_liquidate(1000.0, 0.0, 0.10) == 0.0

    async def test_india_data_service_db_lifecycle(self, test_db: AsyncSession):
        service = IndiaDataService(db=test_db)
        today = datetime.utcnow()

        # Ingest bhavcopy
        bhav_records = [
            {
                "symbol": "SBIN",
                "open": 800.0, "high": 815.0, "low": 795.0, "close": 810.0,
                "prev_close": 800.0, "avg_price": 805.0, "ttl_trd_qnty": 1000000,
                "turnover_lacs": 8050.0, "no_of_trades": 50000,
                "deliv_qty": 500000, "deliv_per": 50.0
            },
            {
                "symbol": "TCS",
                "open": 3200.0, "high": 3250.0, "low": 3180.0, "close": 3240.0,
                "prev_close": 3200.0, "avg_price": 3220.0, "ttl_trd_qnty": 200000,
                "turnover_lacs": 6440.0, "no_of_trades": 30000,
                "deliv_qty": 140000, "deliv_per": 70.0
            }
        ]

        count = await service.ingest_bhavcopy_records(bhav_records, today)
        assert count == 2

        # Idempotent re-run
        count_again = await service.ingest_bhavcopy_records(bhav_records, today)
        assert count_again == 0

        # Institutional flows
        await service.ingest_institutional_flow(today, "FII", 8500.0, 7200.0)
        await service.ingest_institutional_flow(today, "DII", 6000.0, 5000.0)

        flows = await service.get_institutional_flows(lookback_days=10)
        assert len(flows) >= 1
        assert flows[0]["fii_net_crores"] == 1300.0
        assert flows[0]["dii_net_crores"] == 1000.0

        # Add historical bhavcopy for anomaly test
        for i in range(1, 10):
            d = today - timedelta(days=i)
            await service.ingest_bhavcopy_records([
                {
                    "symbol": "SBIN", "open": 800.0, "high": 810.0, "low": 795.0,
                    "close": 800.0, "prev_close": 800.0, "avg_price": 800.0,
                    "ttl_trd_qnty": 800000, "turnover_lacs": 6400.0,
                    "deliv_qty": 200000, "deliv_per": 25.0
                }
            ], d)

        anomalies = await service.get_delivery_anomalies(["SBIN.NS"], lookback_days=10, sigma_threshold=1.5)
        assert len(anomalies) == 1
        assert anomalies[0]["symbol"] == "SBIN"
        assert anomalies[0]["current_delivery_pct"] == 50.0
        assert anomalies[0]["is_anomaly"] is True

        # Portfolio liquidity limits
        p1 = PortfolioPosition(ticker="SBIN.NS", quantity=1000.0, buy_price=800.0, last_price=810.0, market_value=810000.0, weight=1.0)
        dates = pd.date_range("2024-01-01", periods=60, freq="B")
        df_sbin = pd.DataFrame({
            "close": np.full(60, 810.0),
            "volume": np.full(60, 1000000.0)
        }, index=dates)

        limits = await service.calculate_portfolio_liquidity_limits(
            positions=[p1],
            price_history={"SBIN.NS": df_sbin}
        )
        assert limits["portfolio_value"] == 810000.0
        assert limits["positions"][0]["liquidity_tier"] == "HIGHLY_LIQUID"
        assert limits["positions"][0]["days_to_liquidate_10pct_adv"] < 1.0


@pytest.mark.api
class TestIndiaAnalyticsEndpoints:
    @pytest.mark.asyncio
    async def test_india_endpoints(self, async_client, test_db: AsyncSession):
        today = datetime.utcnow()
        f1 = NSEInstitutionalFlow(date=today, category="FII", buy_value_crores=5000.0, sell_value_crores=4000.0, net_value_crores=1000.0)
        f2 = NSEInstitutionalFlow(date=today, category="DII", buy_value_crores=3000.0, sell_value_crores=2000.0, net_value_crores=1000.0)
        b1 = NSEBhavcopy(
            symbol="INFY", date=today, series="EQ", open=1500.0, high=1520.0,
            low=1490.0, close=1510.0, prev_close=1500.0, avg_price=1505.0,
            ttl_trd_qnty=500000, turnover_lacs=7525.0, deliv_qty=350000, deliv_per=70.0
        )
        p1 = PortfolioPosition(ticker="INFY.NS", quantity=100.0, buy_price=1500.0, last_price=1510.0, market_value=151000.0, weight=1.0)
        test_db.add_all([f1, f2, b1, p1])
        await test_db.commit()

        try:
            # 1. India flows
            res_flows = await async_client.get("/api/v1/analytics/india-flows?lookback_days=15")
            assert res_flows.status_code == 200
            assert "flows" in res_flows.json()

            # 2. Delivery anomalies
            res_deliv = await async_client.get("/api/v1/analytics/delivery-anomalies?tickers=INFY.NS")
            assert res_deliv.status_code == 200
            assert "anomalies" in res_deliv.json()

            # 3. Liquidity limits
            res_liq = await async_client.get("/api/v1/analytics/liquidity-limits?tickers=INFY.NS")
            assert res_liq.status_code == 200
            assert "positions" in res_liq.json()
        finally:
            await test_db.execute(delete(NSEInstitutionalFlow))
            await test_db.execute(delete(NSEBhavcopy))
            await test_db.execute(delete(PortfolioPosition))
            await test_db.commit()
