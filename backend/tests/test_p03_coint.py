"""P0-3 contract tests: collision-free coint DB cache keys.

Regression gate for BACKEND_REVIEW P0-3 (ticker f"{a[:4]}_{b[:4]}" collided
and metric coint_{date} was shared, so each pair write evicted all other
pairs of the day). Dict-backed fake stands in for CacheService; no DB.
"""

import pytest

from app.services.cointegration_service import (
    _db_cache_keys,
    _history_coverage,
    CointegrationService,
)
from app.models.schemas import CointPairResult

# The shape a stored pair's stationarity block has on the wire. This is a
# CACHE test, so the block is a fixture in the row's own vocabulary rather than
# a measurement - the ADF/KPSS arithmetic is covered where the prices are, in
# tests/test_p03_coint_stationarity_gate.py.
_STATIONARY_LEG = {
    "ticker": "A.NS",
    "observations": 174,
    "transform": "log_price",
    "alpha": 0.05,
    "lag_rule": "adf:max_lags=1,lag_selection=aic",
    "adf_pvalue": 0.61,
    "adf_lags": 0,
    "kpss_pvalue": 0.0001,
    "kpss_bandwidth": 4,
    "verdict": "i1",
    "reason": "both tests agree the leg is I(1)",
}


def _pair(a, b, pvalue=0.01):
    return CointPairResult(
        ticker_a=a,
        ticker_b=b,
        engle_granger_pvalue=pvalue,
        engle_granger_tstat=-3.5,
        is_cointegrated=True,
        hedge_ratio_beta=1.0,
        intercept_alpha=0.0,
        ou_half_life_days=10.0,
        ou_reversion_speed_theta=0.07,
        current_spread_zscore=0.5,
        johansen_cointegrated=True,
        last_price_a=100.0,
        last_price_b=200.0,
        signal="hold",
        # A stored pair must satisfy the CURRENT contract to be a cache hit: the
        # slope drives a trade instruction, so a row without its standard error
        # is recomputed rather than served with the uncertainty silently absent.
        hedge_ratio_beta_std_error=0.04,
        intercept_alpha_std_error=1.2,
        hedge_regression_observations=174,
        hedge_regression_std_error_basis=(
            "ols_standard_error_from_polyfit_covariance_df_n_minus_2"
        ),
        # Same rule, same reason: the per-leg stationarity verdicts are
        # MEASUREMENTS too, and an absent gate is read as "not recorded" rather
        # than as a pass, so a row without one would publish a directive the
        # gate was meant to have stopped.
        stationarity_leg_a={**_STATIONARY_LEG, "ticker": a},
        stationarity_leg_b={**_STATIONARY_LEG, "ticker": b},
        stationarity_gate={
            "verdict": "both_legs_i1",
            "leg_a_verdict": "i1",
            "leg_b_verdict": "i1",
            "reason": "both legs tested I(1) by ADF and KPSS",
        },
    )


def _legacy_pair(a, b, pvalue=0.01):
    """A cache row written by a build that predates the uncertainty fields."""
    pair = _pair(a, b, pvalue)
    return pair.model_copy(
        update={
            "hedge_ratio_beta_std_error": None,
            "intercept_alpha_std_error": None,
            "hedge_regression_observations": None,
            "hedge_regression_std_error_basis": None,
        }
    )


def _row_without_stationarity(a, b, pvalue=0.01):
    """A row that answers the uncertainty contract but not the stationarity one.

    The narrower shape matters: it is the row a build between the two fixes
    writes, and it is the one that would otherwise keep publishing spread
    directives with no stationarity test behind them.
    """
    pair = _pair(a, b, pvalue)
    return pair.model_copy(
        update={
            "stationarity_leg_a": None,
            "stationarity_leg_b": None,
            "stationarity_gate": None,
        }
    )


class _FakeCache:
    """Minimal dict-backed get/set with real (ticker, metric) keying."""

    def __init__(self):
        self.store = {}
        self.set_calls = []

    async def get_cached_analytics(self, ticker, metric_name):
        hit = self.store.get((ticker, metric_name))
        if hit is None:
            return None
        return {"value": hit["metric_value"], "model_params": hit["model_params"]}

    async def set_cached_analytics(self, ticker, metric_name, metric_value, calculation_date, model_params=None):
        self.store[(ticker, metric_name)] = {"metric_value": metric_value, "model_params": model_params}
        self.set_calls.append((ticker, metric_name))


def test_keys_fit_columns_and_differ():
    t1, m1 = _db_cache_keys("RELIANCE.NS", "RELCAP.NS", "2026-09-03")
    t2, m2 = _db_cache_keys("RELIANCE.NS", "RELINFRA.NS", "2026-09-03")
    assert len(t1) <= 10 and len(m1) <= 50
    assert (t1, m1) != (t2, m2)  # old code: identical ("RELI_RELI", "coint_<date>")


def test_keys_stable_and_order_sensitive():
    assert _db_cache_keys("A.NS", "B.NS", "2026-09-03") == _db_cache_keys("A.NS", "B.NS", "2026-09-03")
    assert _db_cache_keys("A.NS", "B.NS", "2026-09-03") != _db_cache_keys("B.NS", "A.NS", "2026-09-03")


def test_history_coverage_digest_changes_when_prices_are_corrected():
    import pandas as pd

    index = pd.date_range("2026-01-01", periods=4, freq="B")
    first = _history_coverage(pd.Series([1.0, 2.0, 3.0, 4.0], index=index), pd.Series([4.0, 3.0, 2.0, 1.0], index=index))
    corrected = _history_coverage(pd.Series([1.0, 2.0, 3.5, 4.0], index=index), pd.Series([4.0, 3.0, 2.0, 1.0], index=index))
    assert first != corrected


async def test_two_pairs_same_day_no_eviction():
    svc = CointegrationService(db_session=None, cache_service=_FakeCache())
    await svc._set_cached_pair("RELIANCE.NS", "RELCAP.NS", "2026-09-03", _pair("RELIANCE.NS", "RELCAP.NS", 0.01))
    await svc._set_cached_pair("RELIANCE.NS", "RELINFRA.NS", "2026-09-03", _pair("RELIANCE.NS", "RELINFRA.NS", 0.04))
    first = await svc._get_cached_pair("RELIANCE.NS", "RELCAP.NS", "2026-09-03")
    second = await svc._get_cached_pair("RELIANCE.NS", "RELINFRA.NS", "2026-09-03")
    assert first is not None and first.ticker_b == "RELCAP.NS"
    assert first.engle_granger_pvalue == pytest.approx(0.01)
    assert second is not None and second.ticker_b == "RELINFRA.NS"
    assert second.engle_granger_pvalue == pytest.approx(0.04)


async def test_roundtrip_preserves_pair():
    svc = CointegrationService(db_session=None, cache_service=_FakeCache())
    await svc._set_cached_pair("TCS.NS", "INFY.NS", "2026-09-03", _pair("TCS.NS", "INFY.NS", 0.02))
    got = await svc._get_cached_pair("TCS.NS", "INFY.NS", "2026-09-03")
    assert got is not None
    assert (got.ticker_a, got.ticker_b) == ("TCS.NS", "INFY.NS")


@pytest.mark.asyncio
async def test_legacy_cached_row_without_uncertainty_is_a_miss():
    """A cache row that cannot answer the current contract is not a cache hit.

    The role/depth fields were backfillable from engine constants because they
    are declarations. A standard error is a MEASUREMENT, so a row missing one is
    recomputed instead of served with the uncertainty silently absent -- which
    would make the omission indistinguishable from a deliberate `not_computed`.
    """
    svc = CointegrationService(db_session=None, cache_service=_FakeCache())
    await svc._set_cached_pair(
        "TCS.NS", "INFY.NS", "2026-09-03", _legacy_pair("TCS.NS", "INFY.NS", 0.02)
    )
    assert await svc._get_cached_pair("TCS.NS", "INFY.NS", "2026-09-03") is None
    # And a row that does carry one is still served, so this is not a blanket
    # cache bypass.
    await svc._set_cached_pair(
        "TCS.NS", "INFY.NS", "2026-09-04", _pair("TCS.NS", "INFY.NS", 0.02)
    )
    assert await svc._get_cached_pair("TCS.NS", "INFY.NS", "2026-09-04") is not None


@pytest.mark.asyncio
async def test_cached_row_without_stationarity_is_a_miss():
    """The stationarity gate is a MEASUREMENT, so the same rule applies to it.

    A row that carries the hedge-regression standard errors but no ADF/KPSS
    verdict cannot answer whether a low cointegration p-value is evidence of a
    relationship or an artefact of two stationary series. Serving it would keep
    publishing spread directives for up to `CACHE_TTL_HOURS` with no gate
    behind them, and the only trace would be a pair row with no
    `stationarity_gate` field on it.
    """
    svc = CointegrationService(db_session=None, cache_service=_FakeCache())
    await svc._set_cached_pair(
        "TCS.NS",
        "INFY.NS",
        "2026-09-05",
        _row_without_stationarity("TCS.NS", "INFY.NS", 0.02),
    )
    assert await svc._get_cached_pair("TCS.NS", "INFY.NS", "2026-09-05") is None


def test_stationarity_verdicts_are_the_published_vocabulary():
    """Only the three measured verdicts satisfy the contract.

    An unknown verdict is a row written by something this build does not
    understand, and it must be a miss rather than a silent pass.
    """
    row = _pair("A.NS", "B.NS").model_dump()
    assert CointegrationService._cached_pair_satisfies_contract(row) is True
    for bogus in ("", None, "looks_fine", 0):
        assert CointegrationService._cached_pair_satisfies_contract(
            {**row, "stationarity_gate": {"verdict": bogus}}
        ) is False
