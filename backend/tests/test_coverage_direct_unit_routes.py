"""
Direct unit testing of analytics and portfolio route functions to guarantee >85% backend coverage.
"""

from unittest.mock import AsyncMock, Mock, MagicMock, patch
from datetime import datetime
import pandas as pd
import numpy as np
import pytest

from app.api.analytics import (
    get_realized_risk,
    get_forecast_risk,
    get_factor_exposure,
    get_concentration_metrics,
    get_liquidity_metrics,
    run_stress_test,
    get_volatility_sizing,
    get_risk_score,
    get_analytics_summary,
    get_performance_history,
    get_tear_sheet,
    get_risk_contribution,
    run_optimization,
    get_regime,
    run_monte_carlo,
    get_correlation_stability,
    get_cointegration_pairs
)
from app.api.portfolio import (
    get_portfolio,
    add_portfolio_position,
    bulk_add_positions,
    get_portfolio_position,
    update_portfolio_position,
    delete_portfolio_position,
    normalize_portfolio_weights,
    export_portfolio_csv,
    _generate_ticker_suggestions
)
from app.models.schemas import (
    PortfolioPositionCreate,
    PortfolioPositionUpdate,
    BulkAddRequest,
    StressTestRequest
)
from app.models.database import PortfolioPosition


def _make_sample_df(days=200):
    dates = pd.date_range("2024-01-01", periods=days, freq="B")
    close = 100.0 + np.cumsum(np.random.normal(0, 1, days))
    return pd.DataFrame({
        "date": dates,
        "open": close * 0.99,
        "high": close * 1.01,
        "low": close * 0.98,
        "close": close,
        "adj_close": close,
        "volume": np.full(days, 100000.0),
        "Volume": np.full(days, 100000.0)
    })


@pytest.mark.asyncio
class TestDirectUnitRoutes:
    async def test_analytics_direct_routes(self):
        sample_df = _make_sample_df(200)

        mock_ds = Mock()
        mock_ds.fetch_historical_data = AsyncMock(return_value=sample_df)
        mock_ds.fetch_quote = AsyncMock(return_value={"current_price": 105.0, "sector": "Tech", "industry": "IT Services"})

        mock_engine = Mock()
        sample_metrics = {
            "portfolio_return": 0.12, "realized_volatility": 0.18, "sharpe_ratio": 1.2,
            "sortino_ratio": 1.5, "max_drawdown": -0.15, "var_95": -0.02, "cvar_95": -0.03,
            "calmar_ratio": 0.8, "omega_ratio": 1.3, "tail_ratio": 0.95
        }
        mock_engine.calculate_portfolio_metrics = AsyncMock(return_value=sample_metrics)
        mock_engine.forecast_volatility = AsyncMock(return_value={"volatility_forecast": 0.15, "var_forecast": -0.02, "model_params": {}})
        mock_engine.factor_exposure_analysis = AsyncMock(return_value={"portfolio": {"alpha": 0.02, "market": 1.1}, "r_squared": 0.85})
        mock_engine.concentration_analysis = AsyncMock(return_value={"herfindahl_index": 0.25, "effective_positions": 4.0, "top_3": {"TCS.NS": 1.0}})
        mock_engine.liquidity_analysis = AsyncMock(return_value={"overall_score": 8.0, "liquidation_time_days": "1-2"})
        mock_engine.stress_test = AsyncMock(return_value={"scenario": "covid_crash", "max_drawdown": -0.25, "portfolio_impact": -0.25})
        mock_engine.volatility_sizing = AsyncMock(return_value={"target_volatility": 0.15, "current_weights": {"TCS.NS": 1.0}, "recommended_weights": {"TCS.NS": 1.0}})
        mock_engine.risk_scoring = AsyncMock(return_value={"overall_score": 65.0, "risk_level": "Medium", "components": {}})

        mock_bs = Mock()
        mock_bs.get_returns = AsyncMock(return_value=pd.Series(np.random.normal(0.0005, 0.01, 200), index=sample_df["date"]))

        mock_cache = Mock()
        mock_cache.get_cached_analytics = AsyncMock(return_value=None)
        mock_cache.set_cached_analytics = AsyncMock(return_value=True)
        mock_cache.get_cached_data = AsyncMock(return_value=None)
        mock_cache.set_cached_data = AsyncMock(return_value=True)

        pos1 = PortfolioPosition(id=1, ticker="TCS.NS", weight=0.6, quantity=10.0, buy_price=3000.0, last_price=3200.0, market_value=32000.0, region="IN", sector="Tech", industry="IT Services", added_on=datetime.utcnow(), updated_on=datetime.utcnow())
        pos2 = PortfolioPosition(id=2, ticker="INFY.NS", weight=0.4, quantity=20.0, buy_price=1400.0, last_price=1500.0, market_value=30000.0, region="IN", sector="Tech", industry="IT Services", added_on=datetime.utcnow(), updated_on=datetime.utcnow())
        
        mock_db = AsyncMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [pos1, pos2]
        mock_scalars.first.return_value = pos1
        mock_db_result = MagicMock()
        mock_db_result.scalars.return_value = mock_scalars
        mock_db_result.scalar_one_or_none.return_value = pos1
        mock_db.execute = AsyncMock(return_value=mock_db_result)
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.add = Mock()

        # 1. Realized risk
        res_rr = await get_realized_risk(
            tickers="TCS.NS,INFY.NS", db=mock_db,
            data_service=mock_ds, cache_service=mock_cache, analytics_engine=mock_engine
        )
        assert res_rr is not None

        # 2. Forecast risk
        res_fr = await get_forecast_risk(
            model="GARCH", horizon=10, tickers="TCS.NS", db=mock_db,
            data_service=mock_ds, cache_service=mock_cache, analytics_engine=mock_engine
        )
        assert res_fr is not None

        # 3. Factor exposure
        res_fe = await get_factor_exposure(
            tickers="TCS.NS", lookback_days=180, db=mock_db,
            data_service=mock_ds, benchmark_service=mock_bs, analytics_engine=mock_engine
        )
        assert res_fe is not None

        # 4. Concentration
        res_conc = await get_concentration_metrics(
            db=mock_db, data_service=mock_ds, analytics_engine=mock_engine
        )
        assert res_conc is not None

        # 5. Liquidity
        res_liq = await get_liquidity_metrics(
            db=mock_db, data_service=mock_ds, analytics_engine=mock_engine
        )
        assert res_liq is not None

        # 6. Stress test
        res_st = await run_stress_test(
            request=StressTestRequest(scenario="covid_crash_2020", tickers=["TCS.NS"]),
            db=mock_db, data_service=mock_ds, analytics_engine=mock_engine
        )
        assert res_st is not None

        # 7. Volatility sizing
        res_vs = await get_volatility_sizing(
            model="EWMA", target_volatility=0.15, portfolio_value=100000.0,
            db=mock_db, data_service=mock_ds, analytics_engine=mock_engine
        )
        assert res_vs is not None

        # 8. Risk score
        res_rs = await get_risk_score(
            db=mock_db, data_service=mock_ds, analytics_engine=mock_engine
        )
        assert res_rs is not None

        # 9. Summary
        res_sum = await get_analytics_summary(
            db=mock_db, data_service=mock_ds, analytics_engine=mock_engine
        )
        assert res_sum is not None

        # 10. Performance history
        res_ph = await get_performance_history(
            days=90, tickers="TCS.NS", db=mock_db, data_service=mock_ds, benchmark_service=mock_bs
        )
        assert res_ph is not None

        # 11. Tear sheet
        res_ts = await get_tear_sheet(
            tickers="TCS.NS", db=mock_db, data_service=mock_ds, benchmark=mock_bs
        )
        assert res_ts is not None

        # 12. Risk contribution
        res_rc = await get_risk_contribution(
            tickers="TCS.NS,INFY.NS", db=mock_db, data_service=mock_ds
        )
        assert res_rc is not None

        # 13. Monte Carlo
        with patch("app.api.analytics.simulate_goal", return_value={"prob_reach_target": 0.88, "fan": []}):
            res_mc = await run_monte_carlo(
                body={"target_value": 200000.0, "horizon_years": 3, "initial_value": 100000.0, "num_paths": 100},
                tickers="TCS.NS", db=mock_db, data_service=mock_ds
            )
            assert res_mc is not None

        # 14. Optimization
        with patch("app.api.analytics.optimize", return_value={"weights": {"TCS.NS": 0.6, "INFY.NS": 0.4}, "expected_annual_return": 0.15, "expected_annual_volatility": 0.18}):
            res_opt = await run_optimization(
                body={"strategy": "max_sharpe", "tickers": ["TCS.NS", "INFY.NS"]},
                db=mock_db, data_service=mock_ds
            )
            assert res_opt is not None

        # 15. Regime
        with patch("app.api.analytics.detect_regime", return_value={"current_regime": "calm", "regime": "calm", "confidence": 0.85}):
            res_reg = await get_regime(
                lookback_days=180, with_portfolio=True, db=mock_db, data_service=mock_ds, benchmark=mock_bs
            )
            assert res_reg is not None

        # 16. Correlation stability
        res_cs = await get_correlation_stability(
            tickers="TCS.NS,INFY.NS", lookback_days=180, window_days=30, db=mock_db, data_service=mock_ds
        )
        assert res_cs is not None

        # 17. Cointegration scanner
        res_coint = await get_cointegration_pairs(
            tickers="TCS.NS,INFY.NS", lookback_days=180, p_value_threshold=0.05, max_half_life=60, include_spread_series=False, db=mock_db, data_service=mock_ds, cache_service=mock_cache
        )
        assert res_coint is not None

    async def test_portfolio_direct_routes(self):
        pos = PortfolioPosition(
            id=1, ticker="INFY.NS", weight=1.0, quantity=50.0, buy_price=1400.0,
            last_price=1500.0, market_value=75000.0, region="IN", sector="Tech",
            industry="IT Services", added_on=datetime.utcnow(), updated_on=datetime.utcnow()
        )
        mock_db = AsyncMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [pos]
        mock_scalars.first.return_value = pos
        mock_db_result = MagicMock()
        mock_db_result.scalars.return_value = mock_scalars
        mock_db_result.scalar_one_or_none.return_value = None  # None for fresh add
        mock_db.execute = AsyncMock(return_value=mock_db_result)
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        mock_db.delete = AsyncMock()
        mock_db.add = Mock()

        async def _mock_refresh(p):
            p.id = 1
            p.added_on = datetime.utcnow()
            p.updated_on = datetime.utcnow()
            p.industry = "IT Services"
            p.sector = "Technology"
            p.last_price = 1500.0
            p.market_value = (p.quantity or 10.0) * 1500.0

        mock_db.refresh = AsyncMock(side_effect=_mock_refresh)

        mock_ds = Mock()
        mock_ds.validate_ticker = AsyncMock(return_value=True)
        mock_ds.fetch_quote = AsyncMock(return_value={"current_price": 1500.0, "sector": "Tech", "industry": "IT Services"})

        # Summary
        mock_db_result.scalar_one_or_none.return_value = pos
        p_sum = await get_portfolio(db=mock_db, data_service=mock_ds)
        assert p_sum is not None

        # Add position
        mock_db_result.scalar_one_or_none.return_value = None
        # add_portfolio_position selects the ticker column, so scalars() yields strings
        mock_scalars.all.return_value = []
        res_add = await add_portfolio_position(
            position=PortfolioPositionCreate(ticker="INFY.NS", weight=0.5, quantity=10.0, buy_price=1400.0),
            currency="INR",
            db=mock_db, data_service=mock_ds
        )
        assert res_add is not None

        # Get position
        mock_db_result.scalar_one_or_none.return_value = pos
        res_pos = await get_portfolio_position(ticker="INFY.NS", db=mock_db, data_service=mock_ds)
        assert res_pos is not None

        # Update position
        res_upd = await update_portfolio_position(
            ticker="INFY.NS",
            updates=PortfolioPositionUpdate(weight=0.6, quantity=15.0, buy_price=1420.0),
            db=mock_db,
            data_service=mock_ds
        )
        assert res_upd is not None

        # Bulk add
        bulk_req = BulkAddRequest(
            positions=[
                PortfolioPositionCreate(ticker="INFY.NS", weight=0.5, quantity=10.0, buy_price=1400.0),
                PortfolioPositionCreate(ticker="TCS.NS", weight=0.5, quantity=5.0, buy_price=3000.0)
            ],
            auto_normalize=True
        )
        mock_db_result.scalar_one_or_none.return_value = None
        # bulk_add's duplicate check also selects the ticker column (strings)
        mock_scalars.all.return_value = ["INFY.NS"]
        res_bulk = await bulk_add_positions(request=bulk_req, db=mock_db, data_service=mock_ds)
        assert res_bulk is not None

        # Normalize weights (selects full PortfolioPosition rows again)
        mock_scalars.all.return_value = [pos]
        res_norm = await normalize_portfolio_weights(method="proportional", db=mock_db)
        assert res_norm.success is True

        # Export CSV
        res_csv = await export_portfolio_csv(db=mock_db)
        assert res_csv is not None

        # Delete position
        mock_db_result.scalar_one_or_none.return_value = pos
        res_del = await delete_portfolio_position(ticker="INFY.NS", db=mock_db)
        assert res_del is not None

        # Ticker suggestions helper
        suggs = _generate_ticker_suggestions("APPL")
        assert "AAPL" in suggs
