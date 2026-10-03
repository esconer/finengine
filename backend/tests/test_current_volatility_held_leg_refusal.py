"""A HELD leg with no estimable volatility must not leave the current book.

THE DEFECT.  `volatility_sizing` builds the current book's measurement twice and
only guards one of the two entry conditions.  A leg entered the correlation
matrix only if

    weight > 0 and isfinite(weight) and isfinite(vol) and vol >= 0

so a leg the book HELD at positive weight but whose volatility could not be
estimated was silently absent from `current_tickers` -- and therefore from
`returns[current_tickers].corr()`.  The refusal d2085fc added reads
`current_corr` to decide whether a pair is measurable, and that matrix is
BUILT FROM the survivors, so a pair involving the missing leg never appeared in
`current_unmeasurable` at all.  With an empty pair list the guard fell through
to the quadratic form, which used `current_weight_values` -- still the full
weight vector -- against a covariance matrix one leg short:

    current_volatility = sqrt(w' Sigma_sub w) * sqrt(252) = w_survivor * sigma_survivor

Measured on the pre-fix engine, {FLAT 0.1, VAR 0.9}:

    volatilities                       {'VAR': 0.11257949516354557}
    current_volatility                  0.10132154564719102   <- 0.9 * 0.11257949516354557
    current_volatility_basis            'correlation_x_ewma_volatility'
    current_volatility_reason           None
    current_volatility_unmeasurable_pairs  []

`0.1013` is not round-off and not a configured default.  It is this book's own
sigma computed from 90 % of its own risk: the figure describes a portfolio with
one holding that the caller does not hold, published under the key that claims
to describe the book, with an empty reason and an empty pair list, so a reader
cannot distinguish it from a fully measured book.  That is the whole defect
class -- a refusal was detected, then something published a plausible number in
its place.

Note what is NOT the defect.  The EWMA refusal worked: FLAT's returns are
exactly 0.0, `_measures_dispersion` is False, `_ewma_forecast` refused, and
FLAT is absent from `volatilities` and from `recommended_weights`.  Detection
was correct end to end.  Only the reporting downstream of it was not.

THE SHAPE, and why it is this one.  `test_a13_short_ewma_sizing_requires_two_
observations` already fixed the family's answer for a leg that cannot be
measured: refuse rather than substitute, `None` plus a reason.  This adopts that
answer for the current book instead of inventing a third: the figure is absent,
the reason names the leg AND the pair, and the measurable alternative
(`current_volatility_sample_covariance`, the same book on the sample
covariance) stays published beside it.  The SIZE is not renounced: FLAT was
already excluded from `recommended_weights` and still is, and the scale is still
built from the book that can be measured, because a leg that cannot be sized is
a different question from a leg whose volatility cannot be stated.

The alternative shape -- keep a fallback sigma and rename it, per the
`sector_elasticity_basis` / `w_mkt_basis` pattern -- is deliberately NOT taken
here, and the reason is arithmetic rather than taste.  A cross-sectional
fallback (a sibling leg's sigma, or the book's own) is not what the old code
did and cannot be made honest by disclosure: `w' Sigma w` with one row of `w`
removed is not a disclosed cross-sectional reading, it is a DIFFERENT BOOK's
sigma.  Naming it `*_basis` would make it a well-documented wrong answer.

NO TOLERANCE, NO FABRICATED ZERO.  `_measures_dispersion` is `nunique() >= 2`,
exactly `max != min`, so "this series measures no dispersion" is a structural
fact about the data.  Nothing here introduces an epsilon to make a flat series
count as varying, and nothing fills the missing marginal with 0.0: a zero
marginal is a claim that the leg cannot move, which is the strongest possible
statement and the one this family exists to stop publishing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import (
    UNMEASURABLE_LEG_VOLATILITY_REASON,
    AnalyticsEngine,
    _measures_dispersion,
)

ENGINE = AnalyticsEngine()
DAYS = 80


def _book() -> tuple[pd.DataFrame, dict[str, float]]:
    """FLAT: returns of exactly 0.0. VAR: a measurable random walk."""
    idx = pd.bdate_range("2024-01-01", periods=DAYS)
    rng = np.random.default_rng(42)
    prices = pd.DataFrame(
        {
            "FLAT": np.full(DAYS, 100.0),
            "VAR": 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, DAYS))),
        },
        index=idx,
    )
    return prices, {"FLAT": 0.1, "VAR": 0.9}


def _measurable_book(
    unheld_flat: str | None = None
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Two measurable legs, optionally plus a flat leg the book does NOT hold."""
    idx = pd.bdate_range("2024-01-01", periods=DAYS)
    rng = np.random.default_rng(7)
    frame = {
        "A": 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, DAYS))),
        "B": 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, DAYS))),
    }
    weights = {"A": 0.6, "B": 0.4}
    if unheld_flat is not None:
        frame[unheld_flat] = np.full(DAYS, 100.0)
        weights[unheld_flat] = 0.0
    return pd.DataFrame(frame, index=idx), weights


# ---------------------------------------------------------------------------
# The fixture has to be the defect, or these tests prove nothing.
# ---------------------------------------------------------------------------

def test_the_flat_leg_is_exactly_flat_and_measures_no_dispersion():
    prices, weights = _book()
    flat = prices["FLAT"].pct_change(fill_method=None).dropna()
    assert (flat.to_numpy(dtype=float) == 0.0).all()
    # The structural predicate, so the refusal has no threshold in it to tune.
    assert _measures_dispersion(flat) is False
    assert _measures_dispersion(prices["VAR"].pct_change(fill_method=None).dropna()) is True
    assert weights["FLAT"] > 0.0, "the book must HOLD the flat leg"


# ---------------------------------------------------------------------------
# The provenance of 0.10132154564719102, established rather than assumed.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_published_figure_was_this_books_sigma_minus_the_flat_sleeve():
    """It was `weight_survivor * sigma_survivor`, not a default and not noise.

    Restated from the engine's own numbers so the arithmetic is the module's,
    not my transcription of it, and compared by `repr` because only that
    distinguishes "this exact float" from "close to it".
    """
    prices, weights = _book()
    result = await _size(prices, weights)

    survivor_sigma = result["volatilities"]["VAR"]
    assert "FLAT" not in result["volatilities"], (
        "the flat leg must already be out of `volatilities`; this test is "
        "about what is published BESIDE that, so if it has a sigma here there "
        "is a different defect to chase first"
    )
    survivor_weight = weights["VAR"]
    # Re-derived the way the engine derives it: DAILY marginals into the
    # quadratic form, annualised on the way out.  `w * sigma` is the same
    # quantity to within one float reassociation, which is why the comparison
    # below is `approx` and not `repr`: the point being established is WHERE
    # the number comes from, and 1 ulp of `sqrt` ordering does not change that.
    daily_sigma = survivor_sigma / np.sqrt(252)
    daily_cov = np.outer([daily_sigma], [daily_sigma])
    variance = float(
        np.asarray([survivor_weight]) @ daily_cov @ np.asarray([survivor_weight])
    )
    substituted = float(np.sqrt(max(0.0, variance)) * np.sqrt(252))
    assert substituted == pytest.approx(0.9 * survivor_sigma, rel=1e-12)
    assert substituted == pytest.approx(0.10132154564719102, rel=1e-12), (
        "if this stops being the figure the pre-fix engine published, the tests "
        "below are no longer pinning the same defect and the mutation notes in "
        "this file's history need revisiting"
    )
    # A default would not move with the survivor's own sigma, so the two
    # derivations are checked to be the SAME number rather than merely similar.
    assert substituted != pytest.approx(0.112579, rel=1e-9)
    assert substituted != pytest.approx(0.1, rel=1e-9)


async def _size(prices: pd.DataFrame, weights: dict[str, float]) -> dict:
    return await ENGINE.volatility_sizing(
        prices, weights, model="EWMA", target_volatility=0.1
    )


# ---------------------------------------------------------------------------
# The refusal.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_held_leg_with_no_measurable_volatility_refuses_the_figure():
    prices, weights = _book()
    result = await _size(prices, weights)

    assert result["current_volatility"] is None, (
        f"published {result['current_volatility']!r} for a book that holds "
        "FLAT at 10 %: that is the survivors' sigma, and it reads as though "
        "it described the book"
    )
    # A refused figure must lose its basis too, or `None` and a number are
    # published with identical labels.
    assert result["current_volatility_basis"] is None
    assert result["volatilities"] == {"VAR": pytest.approx(0.11257949516354557)}


@pytest.mark.asyncio
async def test_the_refusal_names_the_leg_and_the_pair_it_cannot_measure():
    prices, weights = _book()
    result = await _size(prices, weights)

    assert result["current_volatility_unmeasurable_pairs"] == ["FLAT/VAR"], (
        "the pair the missing leg took out of the matrix has to appear in the "
        "list; an empty list beside a None is the shape that made this "
        "indistinguishable from a clean measurement"
    )
    reason = result["current_volatility_reason"] or ""
    assert UNMEASURABLE_LEG_VOLATILITY_REASON in reason
    assert "FLAT" in reason
    assert "FLAT/VAR" in reason


@pytest.mark.asyncio
async def test_the_measurable_alternative_is_still_published_beside_the_refusal():
    """Refusing one convention must not delete the other one."""
    prices, weights = _book()
    result = await _size(prices, weights)

    assert result["current_volatility_sample_covariance"] is not None
    assert np.isfinite(result["current_volatility_sample_covariance"])


# ---------------------------------------------------------------------------
# What must NOT move.  A refusal that fires on every book is not a fix.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_fully_measured_book_still_publishes_its_figure_and_no_pairs():
    prices, weights = _measurable_book()
    result = await ENGINE.volatility_sizing(
        prices, weights, model="EWMA", target_volatility=0.1
    )

    assert result["current_volatility"] is not None
    assert result["current_volatility_basis"] == "correlation_x_ewma_volatility"
    assert result["current_volatility_reason"] is None
    assert result["current_volatility_unmeasurable_pairs"] == []
    # And it is this book's own sigma, not the survivors' of some other book.
    a, b = result["volatilities"]["A"], result["volatilities"]["B"]
    assert 0.0 < result["current_volatility"] < 2.0 * max(a, b)


@pytest.mark.asyncio
async def test_a_flat_leg_the_book_does_not_hold_does_not_refuse_anything():
    """Zero weight is no weight: its absence from the measurement is not a hole.

    Over-refusal is the same defect wearing a different hat -- a book that is
    perfectly measurable would publish nothing at all.  The unheld flat leg is
    carried in the frame here, so it is genuinely in `returns.columns` and the
    measurement must be bit-identical to the same book without it.
    """
    prices, weights = _measurable_book(unheld_flat="IDLE")
    result = await ENGINE.volatility_sizing(
        prices, weights, model="EWMA", target_volatility=0.1
    )

    assert result["current_weights"]["IDLE"] == 0.0, (
        "the fixture must actually hand the engine an unheld flat leg, or this "
        "proves nothing about the zero-weight path"
    )
    assert "IDLE" in prices.columns
    assert result["current_volatility"] is not None
    assert result["current_volatility_unmeasurable_pairs"] == []
    assert result["current_volatility_reason"] is None
    # Same book, same float as the two-leg version: an unheld leg is not risk.
    baseline_prices, baseline_weights = _measurable_book()
    baseline = await ENGINE.volatility_sizing(
        baseline_prices, baseline_weights, model="EWMA", target_volatility=0.1
    )
    assert repr(result["current_volatility"]) == repr(baseline["current_volatility"])


@pytest.mark.asyncio
async def test_every_unmeasurable_pair_of_a_three_leg_book_is_reported():
    """Both flat legs must be named, not just the first one found.

    The list is asserted as an exact ordered sequence rather than a set,
    because the order is the convention the pre-existing correlation refusal
    already used: pairs enumerated over the return frame in column order.
    """
    idx = pd.bdate_range("2024-01-01", periods=DAYS)
    rng = np.random.default_rng(3)
    prices = pd.DataFrame(
        {
            "FLAT_A": np.full(DAYS, 100.0),
            "VAR": 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, DAYS))),
            "FLAT_B": np.full(DAYS, 100.0),
        },
        index=idx,
    )
    result = await ENGINE.volatility_sizing(
        prices, {"FLAT_A": 0.2, "VAR": 0.6, "FLAT_B": 0.2},
        model="EWMA",
        target_volatility=0.1,
    )

    assert result["current_volatility"] is None
    assert result["current_volatility_unmeasurable_pairs"] == [
        "FLAT_A/VAR",
        "FLAT_A/FLAT_B",
        "VAR/FLAT_B",
    ]


# ---------------------------------------------------------------------------
# What must NOT move, part two: the SIZE is a different question.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refusing_the_current_figure_does_not_refuse_the_recommendation():
    """The leg is still unsizeable, so it is still out of the recommended book.

    This is the boundary of the fix.  `current_volatility` is a MODEL quantity
    and is refused; `recommended_weights` is the allocation, and a leg with no
    volatility was already correctly absent from it.  Widening the refusal to
    the whole payload would order no trade at all, which is a different
    decision from publishing an unstateable number -- and the sibling test
    `test_a13_short_ewma_sizing_requires_two_observations` shows what a
    genuine all-or-nothing refusal looks like: an empty `recommended_weights`
    with an `error`.  That shape is NOT reachable here, and asserting it is not
    is what keeps the two refusures distinct.
    """
    prices, weights = _book()
    result = await _size(prices, weights)

    assert "error" not in result
    assert "FLAT" not in result["recommended_weights"]
    assert set(result["recommended_weights"]) == {"VAR"}
    assert result["sizing_volatility"] is not None
    assert np.isfinite(result["scale_factor"])
    # Every sizing figure bit-identical to the pre-fix engine on this book.
    assert result["sizing_volatility"] == pytest.approx(0.112579, rel=1e-6)
    assert result["scale_factor"] == pytest.approx(0.888261, rel=1e-6)
    assert result["cash_weight"] == pytest.approx(0.111739, rel=1e-6)
    assert result["achieved_volatility"] == pytest.approx(0.109769, rel=1e-4)
    assert result["current_volatility_sample_covariance"] == pytest.approx(
        0.11122, rel=1e-6
    )
