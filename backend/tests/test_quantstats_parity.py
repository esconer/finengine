"""Parity between the vectorised quantstats restatements and quantstats itself.

`quantstats_ratio_statistics` exists so `measure_estimate_uncertainty` can
prove the resampling distribution belongs to the *published* statistic. That
proof only holds while each closure reproduces `quantstats.stats.<name>` on the
same series, so these tests pin the parity directly.

The cases below are deliberately adversarial. A dense, small-magnitude fixture
agrees with almost any implementation of max drawdown, which is why the
superseded phantom-baseline heuristic survived in `analytics_engine.py`
untested: it only diverges once the first cumulative price clears 10.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import quantstats as qs

from app.services.analytics_engine import (
    quantstats_ratio_statistics,
    quantstats_returns_look_like_prices,
)

PERIODS = 252
RF = 0.02
TOLERANCE = 1e-9


def _index(n: int = 504) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=n, freq="B")


def _returns(n: int = 504, seed: int = 3, first: float | None = None) -> pd.Series:
    rng = np.random.default_rng(seed)
    values = rng.normal(0.0004, 0.011, n)
    if first is not None:
        values[0] = first
    return pd.Series(values, index=_index(n), dtype=float)


def _block(series: pd.Series) -> np.ndarray:
    """Shape the closures expect: (n, 1)."""
    return series.to_numpy(dtype=float)[None, :].T


@pytest.mark.parametrize(
    "label, series",
    [
        ("dense", _returns()),
        ("first_day_gain_1.2x", _returns(first=0.20)),
        ("first_day_gain_31x", _returns(first=30.0)),
        ("first_day_gain_1501x", _returns(first=1500.0)),
        ("monotone_decline", pd.Series(np.linspace(-0.01, -0.004, 504), index=_index(504))),
    ],
)
def test_max_drawdown_restatement_matches_quantstats(label, series):
    """Phantom baseline must come from `from_returns`, not the price level.

    quantstats >= 0.0.82 replaced a `>1000 -> 1e5, >10 -> 100.0` heuristic that
    invented a peak the portfolio never reached: it reported -70% drawdown where
    quantstats reports -9.6% once the first cumulative price clears 10.
    """
    stat = quantstats_ratio_statistics(RF, PERIODS)["max_drawdown"]

    restated = float(np.atleast_1d(stat(_block(series)))[0])
    expected = float(qs.stats.max_drawdown(series))

    assert np.isclose(restated, expected, rtol=1e-6, atol=TOLERANCE), (
        f"{label}: restated {restated!r} != quantstats {expected!r}"
    )


@pytest.mark.parametrize(
    "label, series",
    [
        ("dense", _returns()),
        ("first_day_gain_31x", _returns(first=30.0)),
        ("near_wipeout", _returns(first=-0.99)),
    ],
)
def test_other_ratios_match_quantstats(label, series):
    """cagr, comp, volatility and the ratio family must stay in lockstep."""
    suite = quantstats_ratio_statistics(RF, PERIODS)
    block = _block(series)

    expected = {
        "cagr": float(qs.stats.cagr(series)),
        "total_return": float(qs.stats.comp(series)),
        "volatility": float(qs.stats.volatility(series)),
        "sharpe": float(qs.stats.sharpe(series, rf=RF)),
        "sortino": float(qs.stats.sortino(series, rf=RF)),
        "calmar": float(qs.stats.calmar(series)),
        "omega": float(qs.stats.omega(series)),
        "tail_ratio": float(qs.stats.tail_ratio(series)),
    }

    for name, reference in expected.items():
        got = float(np.atleast_1d(suite[name](block))[0])
        assert np.isclose(got, reference, rtol=1e-6, atol=TOLERANCE), (
            f"{label}/{name}: restated {got!r} != quantstats {reference!r}"
        )


def test_restatements_agree_on_a_multi_asset_block():
    """Each asset of a multi-asset book must match quantstats on its own column.

    The closures read column 0 of an ``(n, draws, k)`` block via
    `_statistic_column`, so a per-asset check drives the real production path
    once per column. The first asset is pushed past the old ``>1000`` phantom
    baseline threshold so this cannot pass on a dense fixture alone.
    """
    rng = np.random.default_rng(19)
    frame = pd.DataFrame(
        rng.normal(0.0004, 0.011, (504, 4)), index=_index(504), columns=list("ABCD")
    )
    frame.iloc[0, 0] = 30.0  # cumulative price 31.0 -> superseded baseline was 100.0

    suite = quantstats_ratio_statistics(RF, PERIODS)

    for column in frame.columns:
        series = frame[column]
        # (n=504, k=1) -- the shape `_block()` uses; ndim==2 passes through
        # `_statistic_column` untouched.
        block = _block(series)
        assert block.shape == (504, 1)
        for name in ("max_drawdown", "cagr", "volatility", "sharpe", "tail_ratio"):
            reference = (
                float(qs.stats.sharpe(series, rf=RF)) if name == "sharpe"
                else float(getattr(qs.stats, name)(series))
            )
            got = float(np.atleast_1d(suite[name](block))[0])
            assert np.isclose(got, reference, rtol=1e-6, atol=TOLERANCE), (
                f"{name} on {column}: restated {got!r} != quantstats {reference!r}"
            )


def test_looks_like_prices_mirrors_quantstats_classifier():
    """The gate that decides whether a band publishes at all.

    quantstats reads a series as returns when `min < 0 or max < 1`, so the
    negation is `min >= 0 and max >= 1`. A flat zero-return window and a
    price-like window must both classify the way quantstats classifies them.
    """
    prices_like = pd.Series([100.0, 101.0, 99.0, 102.0], index=_index(4))
    flat_returns = pd.Series([0.0, 0.0, 0.0, 0.0], index=_index(4))
    real_returns = _returns()

    assert quantstats_returns_look_like_prices(prices_like) is True
    assert quantstats_returns_look_like_prices(flat_returns) is False
    assert quantstats_returns_look_like_prices(real_returns) is False
    # And the band actually degrades rather than publishing a neighbour.
    assert quantstats_returns_look_like_prices(np.array([])) is False
