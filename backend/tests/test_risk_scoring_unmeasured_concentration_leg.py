"""An unmeasured concentration leg is scored 0.0 and keeps its weight.

THE DEFECT.  `risk_scoring`'s concentration leg was three lines:

    concentration_unavailable = bool(concentration_result.get("error"))
    hhi = concentration_result.get('herfindahl_index', 0.1)
    concentration_score = min(30, hhi * 100)
    scores['concentration'] = concentration_score

`concentration_analysis` returns `_empty_concentration()` when it measured
nothing, and that shape published `herfindahl_index: 0.0`.  So on the refusal
path the leg was scored:

    min(30, 0.0 * 100) == 0.0

On a 0-30 scale where HIGHER IS RISKIER and 30 is the most concentrated book
there is, 0.0 is the BEST POSSIBLE value - and it was then not listed in
`excluded`, so it kept its 0.20 nominal weight and dragged `overall_score` down
by up to 6 points on a book whose concentration nobody measured.  The leg
declared its own input unmeasured in `inputs` and in `input_reasons`, and
scored the unmeasured input as the safest reading on the scale.

`min(30, hhi * 100)` could not raise on this path - and that is what made it
silent.  `.get(key, default)` returns a STORED None when the key is present,
so once `herfindahl_index` became `None` (the sibling fix, WM-6) the same
expression would be `min(30, None * 100)`, a TypeError, which the enclosing
handler would swallow into `_empty_risk_score` and cost the reader every OTHER
leg's measurement.  The two changes therefore had to land together, and this
file pins both halves: the refusal AND the guard that makes the pair safe.

THE PATTERN IS NOT NEW.  The volatility, correlation, factor and market legs in
the same function already refuse this way - `scores[...] = None` plus
`excluded.append(...)` - and the block's own header comment states the rule:
"a null sub-score that was still counted would be a fabricated 0".  The
concentration leg was the one that had not been converted.

WHAT DID NOT MOVE.  The sub-score expression is byte-for-byte the old one, so
every measured book publishes exactly the number it did before, and the 0.20
nominal weight is still what the leg carries when it IS measured.
"""

import asyncio

import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import RISK_SCORE_WEIGHTS, AnalyticsEngine

ENGINE = AnalyticsEngine()

DAYS = 90


def _prices(seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2024-01-02", periods=DAYS)
    return pd.DataFrame(
        {
            "AAA.NS": 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, DAYS))),
            "BBB.NS": 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.015, DAYS))),
        },
        index=index,
    )


# ---------------------------------------------------------------------------
# The arithmetic of the defect, so a reader can check it without running it.
# ---------------------------------------------------------------------------

def test_a_zero_herfindahl_scores_the_best_possible_value_on_the_scale():
    """0 out of 30, higher-is-riskier.  That is the SAFEST book on the scale."""
    assert min(30, 0.0 * 100) == 0.0
    # And 0.0 is not a reachable Herfindahl for a non-empty book:
    # sum(w^2) >= 1/n > 0 for every n >= 1.
    for n in (1, 2, 5, 14):
        equal = [1.0 / n] * n
        assert sum(w * w for w in equal) >= 1.0 / n > 0.0
    # The one holding that measures it, for contrast.
    assert min(30, 1.0 * 100) == 30.0


def test_the_leg_carries_a_fifth_of_the_weight():
    """0.20 of the headline, so a fabricated 0.0 is worth up to 6 points."""
    assert RISK_SCORE_WEIGHTS["concentration"] == 0.2
    assert sum(RISK_SCORE_WEIGHTS.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# The refusal.
# ---------------------------------------------------------------------------

def test_an_unmeasured_concentration_leg_publishes_no_sub_score():
    result = asyncio.run(
        ENGINE.risk_scoring(_prices(), {"AAA.NS": 0.0, "BBB.NS": 0.0})
    )
    assert result["components"]["concentration"] is None
    # Not 0.0.  A 0.0 here is a measured zero on a scale where zero is the best
    # possible outcome, and it is the one number a reader cannot check.
    assert result["components"]["concentration"] != 0.0


def test_an_unmeasured_leg_releases_its_weight_instead_of_spending_it():
    """WM-5: the other half of the same defect.

    `excluded` and `scores[...] is None` are kept in agreement deliberately, so
    that the renormalisation below drops the weight and a null sub-score is
    never counted.  Without the `excluded` entry the leg keeps its 0.20 and
    `overall_score` is computed from a sub-score that does not exist.
    """
    result = asyncio.run(
        ENGINE.risk_scoring(_prices(), {"AAA.NS": 0.0, "BBB.NS": 0.0})
    )
    assert "concentration" in result["excluded_components"]

    audit = result["score_audit"]
    assert audit["excluded_components"] == result["excluded_components"]
    leg = audit["components"]["concentration"]
    assert leg["status"] == "unmeasured"
    assert leg["sub_score"] is None
    assert leg["headline_contribution"] == 0.0
    assert leg["headline_bucket"] == "excluded"
    # The weight that WAS applied is published as null - not as 0.0 and not as
    # the nominal 0.2.  A reader can see the leg carried nothing.
    assert leg["effective_weight"] is None
    assert leg["nominal_weight"] == 0.2


def test_the_audit_states_the_input_was_never_measured():
    result = asyncio.run(
        ENGINE.risk_scoring(_prices(), {"AAA.NS": 0.0, "BBB.NS": 0.0})
    )
    leg = result["score_audit"]["components"]["concentration"]
    assert leg["input_statistic"] == "herfindahl_index"
    assert leg["input_statistic_value"] is None
    assert leg["input_statistic_provenance"] == "unavailable"
    assert leg["input_statistic_unavailable_reason"]
    assert leg["input_sample"] == {"row_kind": "active_holdings", "rows": 0}
    # The headline attribution adds up to the published total without this leg,
    # because the leg contributes nothing rather than contributing a zero.
    attribution = result["score_audit"]["effective_information"][
        "headline_attribution"
    ]
    assert "concentration" not in attribution


def test_the_alert_says_the_leg_was_not_scored_not_that_it_was():
    """The pre-fix message described the defect it was living with."""
    result = asyncio.run(
        ENGINE.risk_scoring(_prices(), {"AAA.NS": 0.0, "BBB.NS": 0.0})
    )
    alerts = " ".join(result["alerts"])
    assert "Concentration leg not scored" in alerts
    assert "was scored from an unmeasured Herfindahl index" not in alerts


def test_refusing_this_leg_does_not_cost_the_others_their_measurements():
    """The coupling.  `if concentration_score > 20` raised on None.

    Without the guard added beside it, `None > 20` is a TypeError, the whole
    call falls into `except Exception`, and the payload becomes
    `_empty_risk_score` - every leg null.  A refusal that destroys the reader's
    other four measurements is worse than the defect it fixed.
    """
    result = asyncio.run(
        ENGINE.risk_scoring(_prices(), {"AAA.NS": 0.0, "BBB.NS": 0.0})
    )
    assert "error" not in result
    assert result["score_audit"] is not None
    # The correlation leg measures on this two-name book, so it is published.
    assert result["components"]["correlation"] is not None
    assert result["overall_score"] is not None


# ---------------------------------------------------------------------------
# What must not move.
# ---------------------------------------------------------------------------

def test_a_measured_leg_scores_exactly_as_before_and_keeps_its_weight():
    result = asyncio.run(
        ENGINE.risk_scoring(_prices(), {"AAA.NS": 0.6, "BBB.NS": 0.4})
    )
    # HHI = 0.6^2 + 0.4^2 = 0.52 -> min(30, 52) = 30, the cap.
    assert result["components"]["concentration"] == 30.0
    assert "concentration" not in result["excluded_components"]

    leg = result["score_audit"]["components"]["concentration"]
    # `saturated_at_cap`, not `unmeasured`: the distinction the whole fix turns
    # on.  A cap-bound measurement and an absent one must never share a status.
    assert leg["status"] == "saturated_at_cap"
    assert leg["input_statistic_value"] == pytest.approx(0.52, abs=1e-4)
    assert leg["nominal_weight"] == 0.2
    # Its effective weight is renormalised only by the factor leg's absence, so
    # the applied weight is the 0.2 rescaled over the 0.75 that remains - the
    # nominal weight is intact and the leg carries MORE than its nominal share.
    assert leg["effective_weight"] == pytest.approx(0.2 / 0.75, abs=1e-6)


def test_a_one_holding_book_still_saturates_the_leg():
    """A concentrated book measures a real HHI of 1.0 and keeps scoring 30."""
    result = asyncio.run(ENGINE.risk_scoring(_prices(), {"AAA.NS": 1.0}))
    assert result["components"]["concentration"] == 30.0
    audit = result["score_audit"]["components"]["concentration"]
    assert audit["input_statistic_value"] == pytest.approx(1.0, abs=1e-4)
    assert audit["status"] == "saturated_at_cap"
    assert audit["input_statistic_provenance"] == "measured"


def test_the_empty_risk_score_shape_still_declares_every_leg_null():
    """A whole-book refusal is a different thing and stays a different thing."""
    empty = ENGINE._empty_risk_score()
    assert empty["error"]
    assert set(empty["components"]) == set(RISK_SCORE_WEIGHTS)
    assert all(value is None for value in empty["components"].values())
