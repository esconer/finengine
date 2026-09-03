"""P0-3 contract tests: collision-free coint DB cache keys.

Regression gate for BACKEND_REVIEW P0-3 (ticker f"{a[:4]}_{b[:4]}" collided
and metric coint_{date} was shared, so each pair write evicted all other
pairs of the day). Dict-backed fake stands in for CacheService; no DB.
"""

import pytest

from app.services.cointegration_service import (
    _db_cache_keys,
    CointegrationService,
)
from app.models.schemas import CointPairResult


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
