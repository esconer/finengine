"""
Comprehensive test suite for TailRiskService, VolatilityService, CointegrationService, and CorrelationService.
"""

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.tail_risk_service import TailRiskService
from app.services.volatility_service import VolatilityService
from app.services.cointegration_service import (
    CointegrationService,
    compute_ou_parameters,
    analyze_pair_cointegration,
    test_johansen_cointegration as _run_johansen
)
from app.services.correlation_service import (
    CorrelationService,
    compute_rolling_avg_correlation
)


def _sample_returns(days=300, n_assets=3):
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=days, freq="B")
    rets = np.random.normal(0.0005, 0.015, (days, n_assets))
    rets[10:15, 0] = -0.06
    cols = [f"ASSET_{i}" for i in range(n_assets)]
    return pd.DataFrame(rets, index=dates, columns=cols)


def _sample_prices(days=300):
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=days, freq="B")
    p1 = 100.0 + np.cumsum(np.random.normal(0, 1, days))
    noise = np.random.normal(0, 0.5, days)
    p2 = 2.0 * p1 + 5.0 + noise
    p3 = 50.0 + np.cumsum(np.random.normal(0, 1.5, days))
    return pd.DataFrame({"STOCK_A": p1, "STOCK_B": p2, "STOCK_C": p3}, index=dates)


class TestTailRiskService:
    def test_evt_pot_var_es_basic_and_fallback(self):
        short_series = pd.Series([0.01, -0.02, 0.005])
        with pytest.raises(ValueError, match="Insufficient observations"):
            TailRiskService.calculate_evt_pot_var_es(short_series)

        rets = pd.Series(np.random.normal(0.0002, 0.02, 300))
        res = TailRiskService.calculate_evt_pot_var_es(rets, confidence_level=0.99, threshold_quantile=0.95)
        assert res["total_observations"] == 300
        assert res["evt_pot_var_99"] < 0
        assert res["evt_pot_es_99"] < res["evt_pot_var_99"]
        assert "gpd_shape_xi" in res

    def test_tail_dependence_matrix(self):
        df = _sample_returns(250, 3)
        res = TailRiskService.calculate_tail_dependence_matrix(df)
        assert "tickers" in res
        assert len(res["tickers"]) == 3
        assert "matrix" in res
        assert len(res["matrix"]) == 3

    def test_calculate_full_tail_risk_suite(self):
        df = _sample_returns(250, 2)
        weights = {"ASSET_0": 0.6, "ASSET_1": 0.4}
        res = TailRiskService.calculate_full_tail_risk_suite(df, weights)
        assert "evt_var" in res
        assert "tail_dependence_matrix" in res


class TestVolatilityService:
    def test_rolling_realized_volatility(self):
        s = pd.Series(np.random.normal(0, 0.01, 100))
        vol = VolatilityService.calculate_rolling_realized_volatility(s, window=21)
        assert not vol.empty
        assert (vol > 0).all()

        empty_vol = VolatilityService.calculate_rolling_realized_volatility(pd.Series(dtype=float), window=21)
        assert empty_vol.empty

    def test_ewma_volatility(self):
        s = pd.Series(np.random.normal(0, 0.01, 100))
        ewma_vol = VolatilityService.calculate_ewma_volatility(s)
        assert ewma_vol > 0
        assert VolatilityService.calculate_ewma_volatility(pd.Series(dtype=float)) == 0.20
        assert VolatilityService.calculate_ewma_volatility(pd.Series([0.05])) > 0

    def test_forecast_garch_volatility(self):
        s = pd.Series(np.random.normal(0, 0.015, 200))
        res = VolatilityService.forecast_garch_volatility(s, horizon=5)
        assert "annualized_vol" in res
        assert res["annualized_vol"] > 0
        assert "params" in res

    def test_calculate_volatility_cone(self):
        s = pd.Series(np.random.normal(0, 0.015, 300))
        cone = VolatilityService.calculate_volatility_cone(s, windows=[10, 21, 63])
        assert len(cone["windows"]) == 3
        assert "current_forecast" in cone
        assert "symbol" in cone


class TestCointegrationService:
    def test_ou_parameters(self):
        np.random.seed(42)
        z = np.zeros(200)
        for i in range(1, 200):
            z[i] = 0.8 * z[i-1] + np.random.normal(0, 0.5)
        theta, hl = compute_ou_parameters(z)
        assert theta is not None
        assert theta > 0
        assert hl is not None
        assert hl > 0

        assert compute_ou_parameters(np.array([1.0, 2.0])) == (None, None)
        assert compute_ou_parameters(np.cumsum(np.ones(100))) == (None, None)

    def test_johansen_method(self):
        df = _sample_prices(200)
        res = _run_johansen(df["STOCK_A"].values, df["STOCK_B"].values)
        assert isinstance(res, bool)

    def test_analyze_pair_cointegration(self):
        df = _sample_prices(250)
        p1 = df["STOCK_A"]
        p2 = df["STOCK_B"]
        res = analyze_pair_cointegration("STOCK_A", "STOCK_B", p1, p2)
        assert res is not None
        assert res.ticker_a == "STOCK_A"
        assert res.ticker_b == "STOCK_B"
        assert res.hedge_ratio_beta > 0
        assert res.is_cointegrated is True
        assert res.current_spread_zscore is not None

    @pytest.mark.asyncio
    async def test_scan_portfolio_pairs(self, test_db: AsyncSession):
        service = CointegrationService(test_db)
        df_prices = _sample_prices(200)
        price_dict = {col: df_prices[col] for col in df_prices.columns}

        res = await service.scan_pairs(price_data=price_dict)
        assert res.scanned_pairs_count >= 1
        assert len(res.pairs) >= 1


class TestCorrelationService:
    def test_rolling_pairwise_correlation(self):
        df = _sample_returns(150, 3)
        res = CorrelationService.analyze_stability(df, window_days=60)
        assert res.current_avg_correlation is not None
        assert res.historical_threshold_90th is not None
        assert res.alert_level in ["NORMAL", "ELEVATED", "CRITICAL"]
        assert len(res.series) > 0

    def test_compute_rolling_correlation(self):
        df = _sample_returns(100, 2)
        s = compute_rolling_avg_correlation(df, window_days=30)
        assert not s.empty
        assert len(s) > 0
