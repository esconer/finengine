"""P0-2 contract tests: regime price-vs-return input routing.

Regression gate for BACKEND_REVIEW P0-2 (`detect_regime`'s return-Series
fallback was fed into `classify`'s price path, i.e. pct_change of returns).
No DB, no network; seeded RNG only (async fallback test uses AsyncMock).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd

from app.services.regime_service import _looks_like_returns, classify, detect_regime

LABELS = {"crisis", "calm", "bull"}


def _walk(n=300, seed=0):
    rng = np.random.default_rng(seed)
    rets = pd.Series(
        rng.normal(0.0005, 0.012, n),
        index=pd.date_range("2023-01-01", periods=n, freq="B"),
    )
    prices = (1.0 + rets).cumprod() * 100.0
    return prices, rets


def _assert_shape(res):
    assert res is not None
    assert res["current_regime"] in LABELS
    assert len(res["states"]) == 3
    assert set(res["regime_probabilities"].keys()) == LABELS


def test_price_series_classifies():
    prices, _ = _walk()
    _assert_shape(classify(prices))


def test_returns_series_explicit_flag():
    _, rets = _walk()
    _assert_shape(classify(rets, is_returns=True))


def test_returns_series_autodetected():
    _, rets = _walk()
    assert _looks_like_returns(rets) is True
    _assert_shape(classify(rets))  # no flag: heuristic routes correctly


def test_prices_not_detected_as_returns():
    prices, _ = _walk()
    assert _looks_like_returns(prices) is False


def test_returns_path_matches_explicit_flag():
    _, rets = _walk()
    auto = classify(rets)
    explicit = classify(rets, is_returns=True)
    assert auto is not None and explicit is not None
    assert auto["current_regime"] == explicit["current_regime"]
    assert auto["observations"] == explicit["observations"]


async def test_detect_regime_returns_fallback():
    _, rets = _walk(n=300, seed=3)
    with patch("app.services.regime_service.BenchmarkService") as cls:
        inst = cls.return_value
        inst.get_benchmark_df = AsyncMock(return_value=None)
        inst.get_returns = AsyncMock(return_value=rets)
        res = await detect_regime(MagicMock(), lookback_days=1100)
    assert res["current_regime"] in LABELS
    assert len(res["states"]) == 3
