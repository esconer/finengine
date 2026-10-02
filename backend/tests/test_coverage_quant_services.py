"""
Comprehensive test suite for TailRiskService, VolatilityService, CointegrationService, and CorrelationService.
"""

import warnings

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from statsmodels.tsa.vector_ar.vecm import coint_johansen

from app.services.tail_risk_service import TailRiskService
from app.services.volatility_service import VolatilityService
from app.services.cointegration_service import (
    CointegrationService,
    compute_ou_parameters,
    analyze_pair_cointegration,
    test_johansen_cointegration as _run_johansen
)
from app.services.correlation_service import (
    compute_rolling_avg_correlation,
    analyze_correlation_stability,
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
        # Empty input must not fabricate a forecast (was: hardcoded 0.20)
        with pytest.raises(ValueError, match="empty"):
            VolatilityService.calculate_ewma_volatility(pd.Series(dtype=float))
        # One observation has no sample dispersion, so the level is REFUSED,
        # not zeroed. This line previously pinned `== 0.0` and called it the
        # "explicit insufficient/zero contract"; that zero was not inert — the
        # volatility cone ranks the forecast against the realized-vol
        # distribution, and 0.0 sits at or below every non-negative p25, so it
        # shipped `valuation: "cheap"` for a book that could not be measured.
        # A refusal is a valid answer; a stand-in number is the defect.
        #
        # Kept here (corrected, not deleted) because this file is where a reader
        # auditing `VolatilityService` lands, and deleting it would leave this
        # surface silent about the one-observation rule. The consequence that
        # actually matters — that the withheld level withholds the verdict
        # instead of scoring it cheap — is pinned once, in
        # test_agent_a_quant_fixes.py::test_a12_one_observation_ewma_is_withheld_never_ranked_as_cheap.
        # Do not re-pin the cone linkage here; that duplicate would drift.
        assert VolatilityService.calculate_ewma_volatility(pd.Series([0.05])) is None

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
        """The rung returns a REAL verdict on a well-conditioned pair.

        The previous assertion here was `isinstance(res, bool)`, which is
        satisfied by True, by False, AND by the exception fallback's False
        alike - it could not tell a measurement from a refusal, so it passed
        no matter what the function did. `res is True or res is False` uses
        identity, so `None` (a refusal) now fails it.
        """
        df = _sample_prices(200)
        res = _run_johansen(df["STOCK_A"].values, df["STOCK_B"].values)
        assert res is True or res is False, (
            f"a well-conditioned pair must yield a measured verdict, not a "
            f"refusal: {res!r}"
        )

    def test_johansen_refuses_when_the_statistic_is_degraded(self):
        """A dropped imaginary part is a refusal, not a number.

        statsmodels allocates `lr1` as float64 (vecm.py:709) and then assigns
        `-t * sum(log(1 - a))` into it (vecm.py:717). When an eigenvalue sits
        at or outside the unit circle, `1 - a` is non-positive and numpy's log
        of it - taken in complex dtype - carries an imaginary part of
        `-pi` per offending eigenvalue. The float64 store discards it, so the
        published statistic is the real part of a complex number that has no
        real value: it is fabricated, and the ComplexWarning is the only
        trace of it.

        Before the fix this returned `False`, a boolean indistinguishable
        from a measurement. It must return `None`.
        """
        # A near-collinear short pair: the residual covariance `skk` is close
        # to singular, which drives an eigenvalue outside the unit circle.
        rng = np.random.default_rng(5)
        n = 35
        base = np.cumsum(rng.normal(size=n)) + 100.0
        near = base + 1e-6 * rng.normal(size=n)

        # Prove the fixture really does hit the degraded branch, so this test
        # cannot silently stop testing anything if statsmodels changes.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            probe = coint_johansen(
                np.column_stack([near, base]), det_order=0, k_ar_diff=1
            )
        eigenvalues = np.asarray(probe.eig)
        assert np.any(np.real(eigenvalues) >= 1.0), (
            f"fixture no longer exercises the degraded branch: "
            f"eig={eigenvalues!r}"
        )

        res = _run_johansen(near, base)
        assert res is None, (
            f"a degraded Johansen computation must be a refusal (None), not the "
            f"boolean {res!r} carved out of a complex statistic"
        )

    def test_johansen_agrees_with_the_raw_statsmodels_verdict_when_clean(self):
        """The refusal is a degradation report, not a maths change.

        A clean pair must produce exactly the boolean the unguarded `float()`
        read produced - same input, same verdict - or the fix has silently
        altered a published figure.
        """
        df = _sample_prices(200)
        a, b = df["STOCK_A"].values, df["STOCK_B"].values
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            probe = coint_johansen(np.column_stack([a, b]), det_order=0, k_ar_diff=1)
        assert np.all(np.real(np.asarray(probe.eig)) < 1.0), "fixture must be clean"
        expected = bool(float(probe.lr1[0]) > float(probe.cvt[0, 1]))
        assert _run_johansen(a, b) is expected

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
        assert res.observation_date_a == res.overlap_end
        assert res.observation_date_b == res.overlap_end
        assert res.overlap_observations == 250
        assert res.price_basis == "adjusted_close_when_available"

    def test_non_cointegrated_pair_signal_gated(self):
        # Independent random walks: high EG p-value -> no trade signal.
        rng = np.random.default_rng(7)
        dates = pd.date_range("2024-01-01", periods=250, freq="B")
        p1 = pd.Series(100.0 + np.cumsum(rng.normal(0, 1, 250)), index=dates)
        p2 = pd.Series(50.0 + np.cumsum(rng.normal(0, 1, 250)), index=dates)
        res = analyze_pair_cointegration("STOCK_A", "STOCK_C", p1, p2)
        assert res is not None
        assert res.engle_granger_pvalue >= 0.05
        assert res.is_cointegrated is False
        assert res.signal == "NOT_COINTEGRATED"

    @pytest.mark.asyncio
    async def test_scan_portfolio_pairs(self, test_db: AsyncSession):
        service = CointegrationService(test_db)
        df_prices = _sample_prices(200)
        price_dict = {col: df_prices[col] for col in df_prices.columns}

        res = await service.scan_pairs(price_data=price_dict)
        assert res.scanned_pairs_count >= 1
        assert res.analyzed_pairs_count == res.scanned_pairs_count
        assert res.returned_pairs_count == len(res.pairs)
        assert res.returned_cointegrated_pairs_count + res.returned_non_cointegrated_pairs_count == len(res.pairs)
        assert len(res.pairs) >= 1


class TestCorrelationService:
    def test_rolling_pairwise_correlation(self):
        df = _sample_returns(150, 3)
        res = analyze_correlation_stability(df, window_days=60)
        assert res.current_avg_correlation is not None
        assert res.historical_threshold_90th is not None
        assert res.alert_level in ["NORMAL", "ELEVATED", "CRITICAL"]
        assert len(res.series) > 0

    def test_compute_rolling_correlation(self):
        df = _sample_returns(100, 2)
        s = compute_rolling_avg_correlation(df, window_days=30)
        assert not s.empty
        assert len(s) > 0
