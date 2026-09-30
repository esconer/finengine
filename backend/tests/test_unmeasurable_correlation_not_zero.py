"""An unmeasurable correlation is UNKNOWN, and must never be published as 0.0.

`.corr()` is PAIRWISE COMPLETE and its floor is two shared finite rows. A pair
below that floor is NaN -- pandas' own "not measurable" answer -- and the three
production paths below used to turn that NaN into a confident `0.0`, which in a
correlation matrix is the strongest possible claim: *no relationship
whatsoever*.

    analytics_engine.volatility_sizing   current_corr  -> current_volatility
    analytics_engine.volatility_sizing   rec_corr      -> sizing_volatility -> scale -> weights
    optimization_service._hrp_weights    corr          -> distance -> linkage -> weights

So a late-listed leg with almost no overlap read as perfectly uncorrelated, the
book looked more diversified than it is, and HRP placed the pair at the MAXIMUM
possible distance, `sqrt(0.5 * (1 - 0.0)) = 0.7071`.

This is the same defect the risk-score correlation leg already refuses
(`analytics_engine.risk_scoring`: `finite_pairs` only, and `correlation_score =
None` + `excluded` when empty). These three sites had not been given the same
treatment. They are given it here, with the same vocabulary: null plus a
reason, and the excluded names published.

The pairwise-complete semantics are preserved. Nothing here switches to a
complete-case matrix -- that is a different statistic with a different meaning
(see `pairwise_average_correlation_statistics`).
"""

from __future__ import annotations

import asyncio

import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import AnalyticsEngine
from app.services.optimization_service import _hrp_weights, optimize


DAYS = 300


def _quoted(path: np.ndarray, quote_bars) -> np.ndarray:
    """Prices finite only on `quote_bars`; every other bar is an unquoted NaN.

    A return exists only where two CONSECUTIVE bars are both quoted, so a leg
    quoted on {9,10,19,20} has returns on bars 10 and 20.
    """
    mask = np.zeros(DAYS, dtype=bool)
    mask[list(quote_bars)] = True
    return np.where(mask, path, np.nan)


def _thin_pair_frame() -> tuple[pd.DataFrame, list[str]]:
    """A, B, C where B and C share EXACTLY ONE return row.

    B is quoted on {9,10,19,20} -> returns on bars 10 and 20.
    C is quoted on {19,20,29,30} -> returns on bars 20 and 30.
    B and C therefore overlap on bar 20 alone: one shared row, one short of the
    two that Pearson correlation needs. A is quoted throughout, so A/B and A/C
    are both measurable and the book is otherwise healthy.
    """
    dates = pd.bdate_range("2025-01-01", periods=DAYS)
    rng = np.random.default_rng(3)
    prices = pd.DataFrame(index=dates)
    prices["A"] = 100.0 * np.cumprod(1.0 + rng.normal(0.0004, 0.010, DAYS))
    prices["B"] = _quoted(
        100.0 * np.cumprod(1.0 + rng.normal(0.0002, 0.012, DAYS)), {9, 10, 19, 20}
    )
    prices["C"] = _quoted(
        100.0 * np.cumprod(1.0 + rng.normal(0.0003, 0.014, DAYS)), {19, 20, 29, 30}
    )
    return prices, ["B", "C"]


def _measured_frame() -> pd.DataFrame:
    """Three fully quoted legs: every pair is measurable. The control book."""
    dates = pd.bdate_range("2025-01-01", periods=DAYS)
    rng = np.random.default_rng(3)
    prices = pd.DataFrame(index=dates)
    for offset, (ticker, vol) in enumerate(
        (("A", 0.010), ("B", 0.012), ("C", 0.014))
    ):
        shocks = rng.normal(0.0004 - offset * 0.0001, vol, DAYS)
        prices[ticker] = 100.0 * np.cumprod(1.0 + shocks)
    return prices


def _returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change(fill_method=None).iloc[1:]


def _sizing(prices: pd.DataFrame, weights: dict) -> dict:
    return asyncio.run(
        AnalyticsEngine().volatility_sizing(
            prices, weights, model="EWMA", target_volatility=0.15,
            portfolio_value=1_000_000.0, price_currency="INR",
        )
    )


# ---------------------------------------------------------------------------
# the fixture really is unmeasurable (otherwise the tests below prove nothing)
# ---------------------------------------------------------------------------
def test_the_fixture_has_exactly_one_unmeasurable_pair():
    returns = _returns(_thin_pair_frame()[0])
    shared = returns.notna().to_numpy()
    counts = {
        f"{a}/{b}": int((shared[:, i] & shared[:, j]).sum())
        for i, a in enumerate(returns.columns)
        for j, b in enumerate(returns.columns)
        if i < j
    }
    assert counts == {"A/B": 2, "A/C": 2, "B/C": 1}
    # And pandas says so, rather than guessing.
    assert np.isnan(returns.corr().loc["B", "C"])


# ---------------------------------------------------------------------------
# site 1: current_volatility  (the current book)
# ---------------------------------------------------------------------------
def test_current_volatility_is_null_when_a_pair_is_unmeasurable():
    """`fillna(0.0)` published a model-basis volatility off a fabricated pair."""
    prices, unmeasurable = _thin_pair_frame()
    result = _sizing(prices, {"A": 0.4, "B": 0.3, "C": 0.3})

    assert result["current_volatility"] is None, (
        "a correlation matrix with a fabricated 0.0 entry is not a measurement; "
        "current_volatility must be absent, not a number"
    )
    assert result["current_volatility_basis"] is None
    assert result["current_volatility_unmeasurable_pairs"] == ["B/C"]
    reason = result["current_volatility_reason"]
    assert reason and "fewer than two shared return rows" in reason
    for ticker in unmeasurable:
        assert ticker in reason


# ---------------------------------------------------------------------------
# site 2: sizing_volatility -> scale -> the published weights
# ---------------------------------------------------------------------------
def test_the_scale_is_refused_when_a_recommended_pair_is_unmeasurable():
    """The scale was `target / rec_vol_ann` off a matrix with a fabricated 0.0."""
    prices, _ = _thin_pair_frame()
    result = _sizing(prices, {"A": 0.4, "B": 0.3, "C": 0.3})

    assert result["sizing_volatility"] is None
    assert result["sizing_volatility_basis"] is None
    assert result["sizing_volatility_unmeasurable_pairs"] == ["B/C"]
    reason = result["sizing_volatility_reason"]
    assert reason and "fewer than two shared return rows" in reason
    # Refusing is the point: an unscaled weight vector published under a 15%
    # volatility target would be a different target wearing this one's label.
    assert result["recommended_weights"] == {}
    assert result["trades"] == {}
    # And no trade may be manufactured for a leg that is merely unmeasurable.
    assert result["error"]


# ---------------------------------------------------------------------------
# site 3: HRP
# ---------------------------------------------------------------------------
def test_hrp_never_places_an_unmeasurable_pair_at_maximum_distance():
    """`corr.fillna(0.0)` -> `sqrt(0.5*(1-0))` == the largest distance there is."""
    returns = _returns(_thin_pair_frame()[0])
    weights = _hrp_weights(returns)

    # The dropped leg is gone from the clustering universe, not silently kept.
    assert set(weights.index) == {"A", "C"}
    assert abs(weights.sum() - 1.0) < 1e-9
    assert np.isfinite(weights.to_numpy()).all()


def test_optimize_publishes_which_holdings_hrp_dropped_and_why():
    returns = _returns(_thin_pair_frame()[0])
    result = optimize(returns, "hrp", current_weights={"A": 0.4, "B": 0.3, "C": 0.3})

    assert result["excluded"] == ["B"]
    reasons = result["excluded_reasons"]
    assert "B" in reasons and "fewer than two shared return rows" in reasons["B"]
    # The holding is still in the published universe, at a published weight of
    # zero: the reader sees that the optimizer declined to size it.
    assert set(result["weights"]) == {"A", "B", "C"}
    assert result["weights"]["B"] == 0.0
    assert result["weights"]["A"] > 0.0 and result["weights"]["C"] > 0.0


# ---------------------------------------------------------------------------
# the control: a book where every pair IS measurable must not move
# ---------------------------------------------------------------------------
def test_a_fully_measured_book_is_unaffected():
    prices = _measured_frame()
    result = _sizing(prices, {"A": 0.4, "B": 0.3, "C": 0.3})

    assert result["current_volatility_unmeasurable_pairs"] == []
    assert result["sizing_volatility_unmeasurable_pairs"] == []
    assert result["current_volatility_reason"] is None
    assert result["sizing_volatility_reason"] is None
    assert isinstance(result["current_volatility"], float)
    assert isinstance(result["sizing_volatility"], float)
    assert result["sizing_volatility_basis"] == "correlation_x_ewma_volatility"
    assert result["recommended_weights"]

    returns = _returns(prices)
    weights = _hrp_weights(returns)
    assert set(weights.index) == {"A", "B", "C"}
    assert abs(weights.sum() - 1.0) < 1e-9

    optimised = optimize(returns, "hrp", current_weights={"A": 0.4, "B": 0.3, "C": 0.3})
    assert optimised["excluded"] == []
    assert optimised["excluded_reasons"] == {}


# ---------------------------------------------------------------------------
# the empty/refusal payload keeps its shape
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_empty_payload_still_declares_both_reasons():
    result = await AnalyticsEngine().volatility_sizing(
        pd.DataFrame(), {"A": 1.0}, model="EWMA", target_volatility=0.15
    )
    assert result["error"] == "Insufficient data for volatility sizing"
    for key in (
        "current_volatility_reason", "current_volatility_unmeasurable_pairs",
        "sizing_volatility_reason", "sizing_volatility_unmeasurable_pairs",
    ):
        assert key in result
    assert result["current_volatility_unmeasurable_pairs"] == []
    assert result["sizing_volatility_unmeasurable_pairs"] == []
