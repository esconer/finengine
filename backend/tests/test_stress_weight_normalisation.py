"""`stress_test` normalises the weights it is handed, and publishes the total.

THE DEFECT.  `stress_test` accumulated

    weighted_impact += ticker_impact * weight
    portfolio_impact = round(weighted_impact, 4)

over whatever weights arrived, with no normalisation anywhere in the function -
no `weight_sum`, no `weights_total_used`, nothing published that says what the
book weighed.  `portfolio_impact` is documented as "fraction_of_portfolio_value"
in the payload's own units block, so it is only that if the weights sum to 1.

Every sibling entry point already normalises, which is what makes this an
invariant rather than a live wrong number:

  * `calculate_portfolio_metrics`  - filters to finite positive, renormalises
  * `factor_exposure_analysis`     - same contract via the shared aggregation
  * `concentration_analysis`       - filters to finite positive, renormalises,
                                     and refuses on a non-positive total
  * `risk_scoring`                 - renormalises through `concentration_analysis`

The only live caller normalises before it gets here, so no published figure is
wrong today.  That is exactly why it needs pinning: an invariant held only by a
caller's discipline is one refactor away from being wrong, and nothing on the
payload would let a reader detect it.

WHAT CHANGED.  The delivered weights are renormalised at the top, and the total
they arrived with is published as `weights_total_used` so `portfolio_impact`
can be read for the book that was delivered rather than assumed.  Two deliberate
choices inside the normalisation:

  * A SIGN is preserved.  Dropping non-positive weights would change the
    published impact, and this is a normalisation, not a filter.
    `concentration_analysis` drops them for a different measurement - active
    holdings, not a shock weighting - and copying that would move a number.
  * A non-positive or non-finite TOTAL is refused with the existing empty shape
    rather than scored off whatever arrived.  There is no book to normalise on
    to, and the alternative is a shock weighted by fractions of nothing.
"""

import asyncio

import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import AnalyticsEngine

ENGINE = AnalyticsEngine()

DAYS = 90
SEED = 3


def _prices() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    index = pd.bdate_range("2024-01-02", periods=DAYS)
    return pd.DataFrame(
        {
            "AAA.NS": 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, DAYS))),
            "BBB.NS": 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.015, DAYS))),
        },
        index=index,
    )


def _stress(weights, scenario="market_crash"):
    return asyncio.run(ENGINE.stress_test(_prices(), weights, scenario))


# ---------------------------------------------------------------------------
# The invariance.  This is the test that cannot pass before the fix.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "scale,expected_total",
    [(1.0, 1.0), (0.6, 0.6), (0.25, 0.25), (2.0, 2.0), (10.0, 10.0)],
)
def test_the_impact_is_the_same_book_however_the_caller_scaled_it(scale, expected_total):
    """The same book, delivered at five different totals, one impact.

    `portfolio_impact` is published as `fraction_of_portfolio_value`, so it can
    only be that if the weights were normalised onto the book first.  Pre-fix
    each of these produced a different number, scaled exactly by `scale`.
    """
    base = {"AAA.NS": 0.6, "BBB.NS": 0.4}
    scaled = {ticker: weight * scale for ticker, weight in base.items()}

    reference = _stress(base)
    result = _stress(scaled)

    assert result["portfolio_impact"] == pytest.approx(reference["portfolio_impact"])
    assert result["max_drawdown"] == pytest.approx(reference["max_drawdown"])
    # And what the caller actually delivered is on the payload, so the
    # normalisation is visible rather than inferred.
    assert result["weights_total_used"] == pytest.approx(expected_total)


def test_a_zero_scaled_book_reproduces_the_impact_exactly_not_approximately():
    """The tightest case, because the pre-fix error was largest here."""
    base = {"AAA.NS": 0.6, "BBB.NS": 0.4}
    reference = _stress(base)
    halved = _stress({t: w / 2.0 for t, w in base.items()})

    assert reference["portfolio_impact"] == -0.3476
    assert halved["portfolio_impact"] == reference["portfolio_impact"]
    assert halved["max_drawdown"] == reference["max_drawdown"]


def test_the_per_position_impacts_are_unaffected_by_the_total():
    """They are per-position, so they must not depend on the book's weight."""
    base = _stress({"AAA.NS": 0.6, "BBB.NS": 0.4})
    doubled = _stress({"AAA.NS": 1.2, "BBB.NS": 0.8})
    assert doubled["position_impacts"] == base["position_impacts"]
    assert base["position_impacts"] == {
        "AAA.NS": pytest.approx(-0.3256),
        "BBB.NS": pytest.approx(-0.3805),
    }


def test_the_published_total_is_the_delivered_one_not_the_normalised_one():
    """`weights_total_used` has to say what ARRIVED, or it is always 1.0.

    Publishing the post-normalisation total would be true and useless: the
    normalisation makes it 1.0 by construction, so it could never reveal a
    caller drifting.
    """
    result = _stress({"AAA.NS": 0.36, "BBB.NS": 0.24})
    assert result["weights_total_used"] == pytest.approx(0.6)
    assert result["weights_total_used"] != pytest.approx(1.0)


def test_weights_that_already_sum_to_one_are_untouched():
    """The live caller's shape, so the fix cannot move what is published today."""
    normalised = _stress({"AAA.NS": 0.6, "BBB.NS": 0.4})
    assert normalised["weights_total_used"] == pytest.approx(1.0)
    assert normalised["portfolio_impact"] == pytest.approx(-0.3476)


def test_non_finite_weights_are_dropped_rather_than_poisoning_the_total():
    """They cannot be renormalised against each other.

    The dropped leg leaves the book entirely - no weight, and no
    `position_impacts` entry either, because the impact table is built over the
    weights the book was normalised onto.  That is the honest reading: the
    engine was not handed a weight for that holding.
    """
    result = _stress({"AAA.NS": 0.6, "BBB.NS": float("nan")})
    assert result["weights_total_used"] == pytest.approx(0.6)
    assert set(result["position_impacts"]) == {"AAA.NS"}
    # The surviving leg carries the whole book, and the impact is the same as a
    # single-holding book delivered with a normalised 1.0 weight.
    assert result["portfolio_impact"] == pytest.approx(
        _stress({"AAA.NS": 1.0})["portfolio_impact"]
    )


def test_a_book_whose_weights_do_not_sum_to_anything_positive_is_refused():
    """There is no book to normalise onto, so nothing is scored off it."""
    for weights in (
        {"AAA.NS": 0.0, "BBB.NS": 0.0},
        {"AAA.NS": 0.5, "BBB.NS": -0.5},
        {"AAA.NS": -0.6, "BBB.NS": -0.4},
    ):
        result = _stress(weights)
        assert result["error"], weights
        assert result["portfolio_impact"] is None
        assert result["weights_total_used"] is None


def test_the_empty_shape_mirrors_the_key():
    """`_empty_stress_test` mirrors the success payload key-for-key.

    A consumer reading `weights_total_used` must not have to branch on whether
    the call succeeded, so the refusal carries the key with the same meaning:
    nothing was delivered, so nothing was used.
    """
    assert "weights_total_used" in ENGINE._empty_stress_test()
    assert ENGINE._empty_stress_test()["weights_total_used"] is None
    assert "weights_total_used" in _stress({"AAA.NS": 0.6, "BBB.NS": 0.4})
