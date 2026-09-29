"""RL-3: the composition of a risk score has to be auditable.

`overall_score` is a weighted average of five 0-30 sub-scores. The arithmetic was
never wrong. What the payload did not say is **how much of the headline is
evidence**, and on the v13 export two of the five legs are not independent
measurements and a third cannot move:

  * ``market_risk`` is ``min(30, portfolio_returns.tail(60).std() * sqrt(252) *
    100)`` and ``volatility`` is ``min(30, portfolio_returns.std() * sqrt(252) *
    100)``. The delivered series is 39 return rows, so ``tail(60)`` IS the whole
    series, the two legs are the same statistic, and the export published 9.8
    for both. Combined weight 0.35.
  * ``factor_risk`` is ``min(30, (1 - R^2) * 100)``, which is 30 for **every**
    R^2 <= 0.70. On the export it contributed 7.5 of 13.71 and could not move no
    matter what the data did.

The fix here is disclosure, deliberately and only disclosure. Re-weighting,
widening the cap or excluding a leg would move ``overall_score`` and could flip
``risk_level``; that is a product decision, not an engineering one, so the tests
below assert that the existing composition is **legible** and that the published
numbers are recomputable -- and nothing else about the score changes.

Two properties are asserted as CAUSES rather than values:

  * the ``market_risk`` duplication is *sample dependent*. It exists because the
    delivered series is shorter than ``tail(60)``, and it must clear itself as
    history grows. A hard-coded "these two are the same" would be wrong the
    moment the book is older than the window, so the test drives the sample
    length across the boundary.
  * saturation is judged on the UNROUNDED sub-score. A leg near the ceiling has
    headroom and must never be described as pinned.

No network, no DB, seeded RNG only. The audit CLI is deliberately not run: it
reads a frozen export, so it could say nothing about this code.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import (
    RISK_CORRELATION_POINTS_PER_UNIT,
    RISK_FACTOR_UNPIN_R_SQUARED,
    RISK_MARKET_WINDOW_ROWS,
    RISK_SCORE_CAP,
    RISK_SCORE_LEG_SPECS,
    RISK_SCORE_WEIGHTS,
    AnalyticsEngine,
    _leg_series_relation,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

WEIGHTS = {"A": 0.4, "B": 0.3, "C": 0.3}


def _prices_from_returns(returns: Dict[str, np.ndarray], index=None) -> pd.DataFrame:
    """A price frame whose `pct_change` IS the return series that was passed in."""
    n = len(next(iter(returns.values())))
    index = index if index is not None else pd.bdate_range("2026-01-01", periods=n)
    return pd.DataFrame(
        {name: 100.0 * np.cumprod(1.0 + values) for name, values in returns.items()},
        index=index,
    )


def _correlated_frame(
    n: int = 200, seed: int = 11, columns: tuple[str, ...] = ("A", "B", "C")
) -> pd.DataFrame:
    """One common factor, so every leg is measurable and the book is a book."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2026-01-01", periods=n)
    base = pd.Series(100.0 + np.cumsum(rng.normal(0.0, 1.0, n)), index=index)
    return pd.DataFrame(
        {name: base * (1.0 + 0.1 * i) + rng.normal(0.0, 0.3, n)
         for i, name in enumerate(columns)},
        index=index,
    )


def _benchmark_driven_book(
    n: int = 300, seed: int = 21
) -> tuple[pd.DataFrame, pd.Series]:
    """A book whose return IS the benchmark, plus a little idiosyncratic noise.

    This is the fixture that has to unpin the factor leg: the same code path,
    with a benchmark that explains most of the portfolio's variance, so R^2
    clears 0.70 and the sub-score can leave the ceiling.
    """
    rng = np.random.default_rng(seed)
    common = rng.normal(0.0, 0.010, n)
    returns = {
        "A": common,
        "B": common + rng.normal(0.0, 0.001, n),
        "C": common + rng.normal(0.0, 0.001, n),
    }
    frame = _prices_from_returns(returns)
    return frame, pd.Series(common, index=frame.index)


def _noise_benchmark(frame: pd.DataFrame, seed: int = 17) -> pd.Series:
    """A benchmark unrelated to the book, so the factor leg pins at its cap."""
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0, 0.01, len(frame)), index=frame.index)


def _diversified_book(
    n: int = 300, seed: int = 31, names: int = 6, rho: float = 0.5
) -> tuple[pd.DataFrame, pd.Series, Dict[str, float]]:
    """A book on which NO leg reaches its ceiling, and a benchmark that fits it.

    Enough names that the Herfindahl index stays under the 0.30 cap input, a
    moderate common loading so the average pairwise correlation stays under 0.60,
    and enough idiosyncratic spread that the portfolio's annualized volatility
    stays under 0.30. The benchmark IS the common factor, so the factor leg
    unpins too. This is the fixture for the negative case: a score whose
    composition has nothing wrong with it.
    """
    rng = np.random.default_rng(seed)
    factor = rng.normal(0.0, 1.0, n)
    loading = 0.010
    common = loading * factor
    # corr(A_i, A_j) = loading^2 / (loading^2 + idio^2) = rho by construction.
    idio = loading * np.sqrt((1.0 - rho) / rho)
    returns = {
        f"N{i}": common + idio * rng.normal(0.0, 1.0, n)
        for i in range(names)
    }
    frame = _prices_from_returns(returns)
    weight = 1.0 / names
    return (
        frame,
        pd.Series(common, index=frame.index),
        {name: weight for name in returns},
    )


def _audit(result: Dict[str, Any]) -> Dict[str, Any]:
    assert result.get("score_audit") is not None, "the composition must be published"
    return result["score_audit"]


def _legs(audit: Dict[str, Any]) -> Dict[str, Any]:
    return audit["components"]


# ---------------------------------------------------------------------------
# 1. every leg is recomputable from a published input
# ---------------------------------------------------------------------------
class TestEveryLegPublishesItsInputAndFormula:
    @pytest.mark.asyncio
    async def test_each_measured_leg_recomputes_from_its_published_input(self):
        """The disclosure is not a description -- it is the arithmetic.

        If a leg's published input could not reproduce the published sub-score,
        the leg would be presenting a number whose provenance nobody can check.
        """
        engine = AnalyticsEngine()
        frame = _correlated_frame(n=120)
        result = await engine.risk_scoring(
            frame, WEIGHTS, benchmark_data=_noise_benchmark(frame)
        )
        legs = _legs(_audit(result))
        recomputed = {
            "concentration": lambda v: min(RISK_SCORE_CAP, v * 100),
            "volatility": lambda v: min(RISK_SCORE_CAP, v * 100),
            "correlation": lambda v: min(
                RISK_SCORE_CAP, max(0.0, v) * RISK_CORRELATION_POINTS_PER_UNIT
            ),
            "factor_risk": lambda v: min(RISK_SCORE_CAP, (1 - v) * 100),
            "market_risk": lambda v: min(RISK_SCORE_CAP, v * 100),
        }
        for name, formula in recomputed.items():
            leg = legs[name]
            assert leg["status"] != "unmeasured", name
            assert leg["input_statistic_provenance"] == "measured", name
            value = leg["input_statistic_value"]
            assert isinstance(value, float), name
            assert leg["sub_score"] == pytest.approx(
                round(formula(value), 1), abs=0.05
            ), f"{name}: {leg['formula']} on {value} != {leg['sub_score']}"
            assert leg["cap"] == RISK_SCORE_CAP
            assert leg["nominal_weight"] == RISK_SCORE_WEIGHTS[name]
            assert leg["effective_weight"] == pytest.approx(
                leg["nominal_weight"], abs=1e-9
            )
            assert leg["formula"] and leg["input_statistic"]
            assert leg["input_statistic_units"] and leg["input_sample"]

    @pytest.mark.asyncio
    async def test_the_published_weight_is_the_weight_that_was_applied(self):
        """Renormalization is disclosed per leg, and it is the applied weight."""
        engine = AnalyticsEngine()
        result = await engine.risk_scoring(
            _correlated_frame(columns=("A",)), {"A": 1.0}
        )
        audit = _audit(result)
        assert "correlation" in result["excluded_components"]
        assert "factor_risk" in result["excluded_components"]
        assert audit["nominal_weights"] == RISK_SCORE_WEIGHTS
        assert audit["nominal_weight_total"] == pytest.approx(1.0)
        for name, leg in _legs(audit).items():
            if name in result["excluded_components"]:
                assert leg["effective_weight"] is None
                assert leg["exclusion_reason"]
            else:
                assert leg["effective_weight"] == pytest.approx(
                    leg["nominal_weight"] / sum(
                        RISK_SCORE_WEIGHTS[k]
                        for k in RISK_SCORE_WEIGHTS
                        if k not in result["excluded_components"]
                    ),
                    abs=1e-6,
                )
        # And the applied weights reproduce the headline exactly.
        legs = _legs(audit)
        total = sum(
            legs[name]["effective_weight"] * legs[name]["sub_score"]
            for name in legs
            if legs[name]["effective_weight"] is not None
        )
        assert total == pytest.approx(result["overall_score"], abs=0.05)

    def test_the_spec_table_declares_all_five_legs_and_nothing_else(self):
        """The published table cannot be a partial view of the score."""
        assert set(RISK_SCORE_LEG_SPECS) == set(RISK_SCORE_WEIGHTS) == {
            "concentration",
            "volatility",
            "correlation",
            "factor_risk",
            "market_risk",
        }
        assert sum(RISK_SCORE_WEIGHTS.values()) == pytest.approx(1.0)
        for name, spec in RISK_SCORE_LEG_SPECS.items():
            assert spec["formula"].startswith("min(30, "), name
            assert isinstance(spec["cap_binding_input"], float), name
            assert spec["unpin_condition"], name


# ---------------------------------------------------------------------------
# 2. market_risk is the same statistic as volatility on a short sample
# ---------------------------------------------------------------------------
class TestMarketRiskDuplication:
    @pytest.mark.asyncio
    async def test_a_short_sample_declares_market_risk_a_duplicate(self):
        """The defect itself: two legs, one measurement, published side by side."""
        engine = AnalyticsEngine()
        frame = _correlated_frame(n=40)
        result = await engine.risk_scoring(frame, WEIGHTS)
        audit = _audit(result)
        rows = _legs(audit)["volatility"]["input_sample"]["rows"]

        assert rows < RISK_MARKET_WINDOW_ROWS, "fixture must be a short sample"
        assert result["duplicate_components"] == [
            {
                "component": "market_risk",
                "duplicate_of": "volatility",
                "relation": "identical",
                "sample_dependent": True,
                "clears_when": audit["duplicate_components"][0]["clears_when"],
            }
        ]
        # The reason is the arithmetic, stated with the row count that causes it.
        reason = _legs(audit)["market_risk"]["duplicate_reason"]
        assert f"tail({RISK_MARKET_WINDOW_ROWS})" in reason
        assert f"{rows}-row" in reason
        # And the two legs really are the same number.
        assert result["components"]["volatility"] == result["components"]["market_risk"]
        assert _legs(audit)["market_risk"]["counts_as_independent_evidence"] is False
        assert _legs(audit)["volatility"]["counts_as_independent_evidence"] is True

    @pytest.mark.asyncio
    async def test_a_sample_longer_than_the_window_clears_the_identical_claim(self):
        """The duplication is a property of the SAMPLE, so the sample decides.

        This is the cause-pinning test. A declaration that did not move with the
        sample length would be a standing claim about the code, and it would be
        wrong in both directions: false today, and false again once the book is
        older than the window.
        """
        engine = AnalyticsEngine()
        short = await engine.risk_scoring(_correlated_frame(n=40), WEIGHTS)
        long = await engine.risk_scoring(_correlated_frame(n=200), WEIGHTS)

        short_leg = _legs(_audit(short))["market_risk"]
        long_leg = _legs(_audit(long))["market_risk"]
        short_rows = _legs(_audit(short))["volatility"]["input_sample"]["rows"]
        long_rows = _legs(_audit(long))["volatility"]["input_sample"]["rows"]

        assert short_rows < RISK_MARKET_WINDOW_ROWS < long_rows
        assert short_leg["duplicate_relation"] == "identical"
        assert short_leg["duplicate_is_sample_dependent"] is True
        assert str(RISK_MARKET_WINDOW_ROWS) in short_leg["duplicate_clears_when"]

        # Past the window the legs stop publishing the same number ...
        assert long["components"]["volatility"] != long["components"]["market_risk"]
        assert long_leg["input_statistic_value"] != _legs(_audit(long))["volatility"][
            "input_statistic_value"
        ]
        # ... and the IDENTICAL duplication is gone, with the reason for it gone
        # too. It is still a second window on the same series, and says so.
        assert long_leg["duplicate_relation"] == "strict_subset"
        assert long_leg["duplicate_is_sample_dependent"] is False
        assert "not shorter than" not in long_leg["duplicate_reason"]
        assert "SAME portfolio" in long_leg["duplicate_reason"]

    @pytest.mark.asyncio
    async def test_the_boundary_is_the_window_length_and_not_a_constant(self):
        """Walk the sample across the boundary; the declaration must track it."""
        engine = AnalyticsEngine()
        seen = []
        for n in (40, 61, 62, 63, 200):
            result = await engine.risk_scoring(_correlated_frame(n=n), WEIGHTS)
            leg = _legs(_audit(result))["market_risk"]
            rows = _legs(_audit(result))["volatility"]["input_sample"]["rows"]
            seen.append((rows, leg["duplicate_relation"]))
            # Whatever the relation is, it follows the measured row count.
            expected = (
                "identical" if rows <= RISK_MARKET_WINDOW_ROWS else "strict_subset"
            )
            assert leg["duplicate_relation"] == expected, (rows, n)
        assert [relation for _rows, relation in seen][:2] == ["identical", "identical"]
        assert seen[-1][1] == "strict_subset"

    def test_series_relation_distinguishes_identical_from_subset_from_other(self):
        index = pd.bdate_range("2026-01-01", periods=100)
        whole = pd.Series(np.arange(100.0), index=index)
        assert _leg_series_relation(whole, whole) == "identical"
        assert _leg_series_relation(whole.tail(60), whole) == "strict_subset"
        assert _leg_series_relation(whole.head(60), whole) is None
        assert _leg_series_relation(pd.Series(dtype=float), whole) is None
        assert _leg_series_relation(None, whole) is None

    @pytest.mark.asyncio
    async def test_a_duplicated_leg_is_never_silent_in_the_alerts(self):
        """`components` is read as five measurements; the payload has to say so."""
        engine = AnalyticsEngine()
        frame = _correlated_frame(n=40)
        result = await engine.risk_scoring(
            frame, WEIGHTS, benchmark_data=_noise_benchmark(frame)
        )
        joined = " ".join(result["alerts"])
        assert "market_risk is not independent evidence" in joined
        assert "volatility" in joined
        assert result["independent_component_count"] == 4
        assert result["independent_component_count"] < len(result["components"])


# ---------------------------------------------------------------------------
# 3. a saturated leg says so, and says what would unpins it
# ---------------------------------------------------------------------------
class TestSaturation:
    @pytest.mark.asyncio
    async def test_factor_risk_publishes_its_ceiling_and_the_threshold_below_it(self):
        """The pinned leg must state the cap AND the input that would free it."""
        engine = AnalyticsEngine()
        frame = _correlated_frame(n=120)
        result = await engine.risk_scoring(
            frame, WEIGHTS, benchmark_data=_noise_benchmark(frame)
        )
        r_squared = result["factor_r_squared"]
        assert r_squared is not None and r_squared <= RISK_FACTOR_UNPIN_R_SQUARED
        assert result["components"]["factor_risk"] == RISK_SCORE_CAP

        leg = _legs(_audit(result))["factor_risk"]
        assert leg["status"] == "saturated_at_cap"
        assert leg["saturated"] is True
        assert leg["headroom_to_cap"] == 0.0
        assert leg["cap"] == RISK_SCORE_CAP
        assert leg["input_statistic_value"] == pytest.approx(r_squared, abs=1e-6)
        assert leg["cap_binding_input"] == pytest.approx(0.70)
        assert leg["cap_binds_when_input_is"] == "<= 0.70"
        assert leg["unpin_condition"] == "R-squared > 0.70"
        assert "factor_risk" in result["saturated_components"]
        assert any(
            "factor_risk is pinned" in alert
            and "R-squared > 0.70" in alert
            for alert in result["alerts"]
        ), result["alerts"]

    @pytest.mark.asyncio
    async def test_a_saturated_leg_reports_the_share_of_the_headline_it_carries(self):
        """The pinned leg is a CONSTANT, so the reader needs its weight."""
        engine = AnalyticsEngine()
        frame = _correlated_frame(n=120)
        result = await engine.risk_scoring(
            frame, WEIGHTS, benchmark_data=_noise_benchmark(frame)
        )
        audit = _audit(result)
        information = audit["effective_information"]
        leg = _legs(audit)["factor_risk"]
        assert leg["headline_contribution"] == pytest.approx(
            RISK_SCORE_CAP * leg["effective_weight"], abs=1e-6
        )
        # The denominator is the PUBLISHED headline, so the share is checkable.
        # It used to be asserted == the ROUNDED `overall_score`, which pinned
        # the defect: the contribution is unrounded, so dividing it by a rounded
        # total is what made the five shares sum to 1.001419. The unrounded
        # total is published instead, and this is the same number at 1 dp.
        assert information["headline_basis_score"] == pytest.approx(
            result["overall_score"], abs=0.05
        )
        assert information["headline_basis_score_rounded"] == result["overall_score"]
        assert information["pinned_share_of_headline"] == pytest.approx(
            information["pinned_weight"] * RISK_SCORE_CAP
            / information["headline_basis_score"],
            abs=1e-6,
        )
        assert "factor_risk" in information["pinned_legs"]
        assert "factor_risk" in result["saturated_components"]

    @pytest.mark.asyncio
    async def test_the_factor_leg_unpins_when_the_benchmark_explains_enough(self):
        """A pinned leg must be able to move. If it cannot, the flag is a bug.

        Here the same code path sees a benchmark that explains most of the book,
        so R^2 clears 0.70 and the sub-score has to come off the ceiling.
        """
        engine = AnalyticsEngine()
        frame, benchmark = _benchmark_driven_book(n=300, seed=21)
        result = await engine.risk_scoring(frame, WEIGHTS, benchmark_data=benchmark)
        r_squared = result["factor_r_squared"]
        assert r_squared is not None and r_squared > RISK_FACTOR_UNPIN_R_SQUARED, (
            f"fixture must clear the unpin threshold, got {r_squared}"
        )
        assert result["components"]["factor_risk"] < RISK_SCORE_CAP
        leg = _legs(_audit(result))["factor_risk"]
        assert leg["saturated"] is False
        assert leg["status"] == "measured"
        assert leg["headroom_to_cap"] > 0
        assert "factor_risk" not in result["saturated_components"]

    @pytest.mark.asyncio
    async def test_a_leg_near_but_not_at_its_cap_is_not_declared_pinned(self):
        """The failure mode this rule exists to prevent: 'nearly 30' read as 30.

        A near-cap leg has headroom and the data can still move it, so calling it
        saturated would be a false statement about how much of the headline is
        evidence. The fixture is SEARCHED for rather than assumed, so the
        assertion cannot pass by accident on a leg that was never near.
        """
        engine = AnalyticsEngine()
        found: Optional[Dict[str, Any]] = None
        for seed in range(80):
            rng = np.random.default_rng(seed)
            n = 400
            common = rng.normal(0.0, 1.0, n)
            # Two assets whose returns share one factor: the average pairwise
            # correlation is then that single correlation, which is directly
            # steerable toward -- but not onto -- the 0.60 cap input.
            idio_a = rng.normal(0.0, 1.0, n)
            idio_b = rng.normal(0.0, 1.0, n)
            frame = _prices_from_returns(
                {
                    "A": 0.010 * common + 0.008 * idio_a,
                    "B": 0.010 * common + 0.008 * idio_b,
                }
            )
            result = await engine.risk_scoring(frame, {"A": 0.5, "B": 0.5})
            leg = _legs(_audit(result))["correlation"]
            score = leg["sub_score"]
            if score is not None and 0 < RISK_SCORE_CAP - score <= 2.0:
                found = {"seed": seed, "result": result, "leg": leg}
                break
        assert found is not None, "no fixture landed within 2 points of the cap"
        leg, result = found["leg"], found["result"]
        assert leg["saturated"] is False
        assert leg["status"] == "measured"
        assert leg["headroom_to_cap"] > 0
        assert "correlation" not in result["saturated_components"]
        assert not any("correlation is pinned" in a for a in result["alerts"])
        # It is still offered the same threshold, so a reader can see how close
        # it is to being pinned rather than only that it is not.
        assert leg["cap_binding_input"] == pytest.approx(0.60)
        assert leg["unpin_condition"] == "avg pairwise correlation < 0.60"

    @pytest.mark.asyncio
    async def test_saturation_is_judged_on_the_unrounded_sub_score(self):
        """Rounding a 29.98 to 30.0 must not manufacture a pinned leg."""
        engine = AnalyticsEngine()
        for seed in range(12):
            result = await engine.risk_scoring(
                _correlated_frame(n=90, seed=seed), WEIGHTS
            )
            audit = _audit(result)
            for name, leg in _legs(audit).items():
                if leg["sub_score"] is None:
                    continue
                assert leg["saturated"] == (leg["headroom_to_cap"] == 0.0), name
                assert leg["status"] == (
                    "saturated_at_cap" if leg["saturated"] else "measured"
                ), name

    @pytest.mark.asyncio
    async def test_sub_score_and_headroom_are_one_quantity_at_two_roundings(self):
        """`headroom_to_cap` is not `cap - sub_score`, and the payload says so.

        On the v26 book four of the five legs disagreed: concentration published
        `sub_score` 8.6 beside `headroom_to_cap` 21.44, which is 30 - 8.56. Both
        numbers are correct -- `sub_score` is rounded to 1 dp for display and the
        headroom is taken from the unrounded value -- but the payload published
        them side by side with no precision basis, so a reader checking
        `cap - sub_score == headroom_to_cap` read four legs as inconsistent.
        Nothing moves here: the fix is that the payload now names both
        roundings and which one answers which question.
        """
        engine = AnalyticsEngine()
        frame = _correlated_frame(n=120)
        result = await engine.risk_scoring(
            frame, WEIGHTS, benchmark_data=_noise_benchmark(frame)
        )
        audit = _audit(result)
        disagreeing = 0
        for name, leg in _legs(audit).items():
            if leg["sub_score"] is None:
                continue
            # The published note has to be present AND has to describe the two
            # roundings by name, or it does not discharge the disclosure.
            note = leg["sub_score_precision_note"]
            assert "1 decimal" in note, (name, note)
            assert "UNROUNDED" in note, (name, note)
            assert "headroom_to_cap" in note and "sub_score" in note, (name, note)

            # The reconciliation: cap - headroom is the unrounded sub-score, and
            # the displayed sub_score is that value at 1 dp.  This is what a
            # reader does, so it has to hold exactly.
            unrounded = RISK_SCORE_CAP - leg["headroom_to_cap"]
            assert leg["sub_score"] == round(unrounded, 1), name
            assert abs(leg["sub_score"] - unrounded) <= 0.05 + 1e-9, name
            # And the reconstruction is the value the rest of the leg was built
            # from, so the share reconciles through it.
            assert leg["headline_contribution"] == pytest.approx(
                unrounded * leg["effective_weight"], abs=1e-5
            ), name
            if leg["headroom_to_cap"] != pytest.approx(
                RISK_SCORE_CAP - leg["sub_score"], abs=1e-9
            ):
                disagreeing += 1
        # The fixture must actually exercise the case, or this test proves
        # nothing: at least one leg has to disagree at 1 dp.
        assert disagreeing > 0, "no leg disagreed; the rounding never bit"

    @pytest.mark.asyncio
    async def test_the_note_reconstructs_the_leg_from_its_published_input(self):
        """`headroom_to_cap` is what reconciles a leg to its input statistic.

        concentration on the v26 book: `sub_score` 8.6, `headroom_to_cap` 21.44,
        and 30 - 21.44 = 8.56 = `input_statistic_value` 0.0856 x 100. So the
        published input reproduces the UNROUNDED sub-score, and that is the
        number `headline_contribution` was multiplied -- which is the point the
        note makes about which figure to use for what.

        The fixture is the six-name book, where the concentration leg is NOT at
        its cap: with WEIGHTS = {0.4, 0.3, 0.3} the input is 0.34 and the leg
        publishes 30.0, which reconciles against the cap rather than the input.
        """
        engine = AnalyticsEngine()
        frame, benchmark, weights = _diversified_book()
        result = await engine.risk_scoring(frame, weights, benchmark_data=benchmark)
        leg = _legs(_audit(result))["concentration"]
        assert not leg["saturated"]
        unrounded = RISK_SCORE_CAP - leg["headroom_to_cap"]
        assert unrounded == pytest.approx(leg["input_statistic_value"] * 100, abs=1e-6)
        assert leg["sub_score"] == round(unrounded, 1)
        assert leg["headline_contribution"] == pytest.approx(
            unrounded * leg["effective_weight"], abs=1e-6
        )


# ---------------------------------------------------------------------------
# 4. effective independent information, as a measurement
# ---------------------------------------------------------------------------
class TestEffectiveInformation:
    @pytest.mark.asyncio
    async def test_the_headline_weight_partitions_into_three_disjoint_buckets(self):
        """A slogan would be worthless here, so the numbers must add up.

        The buckets are disjoint on purpose: a leg that is both a duplicate and
        at its cap must not be counted in both shares.
        """
        engine = AnalyticsEngine()
        frame = _correlated_frame(n=40)
        result = await engine.risk_scoring(
            frame, WEIGHTS, benchmark_data=_noise_benchmark(frame)
        )
        audit = _audit(result)
        legs = _legs(audit)
        information = audit["effective_information"]

        buckets = [leg["headline_bucket"] for leg in legs.values()]
        assert set(buckets) <= {"responsive", "pinned", "duplicate", "excluded"}
        assert len(buckets) == len(set(legs))
        assert information["measured_leg_count"] == 5
        assert information["independent_leg_count"] == 4
        assert information["duplicate_weight"] == pytest.approx(0.10)
        assert "factor_risk" in information["pinned_legs"]
        assert information["pinned_nominal_weight"] >= 0.25
        assert (
            information["responsive_weight"]
            + information["pinned_weight"]
            + information["duplicate_weight"]
        ) == pytest.approx(1.0, abs=1e-6)
        assert information["headline_weight_total"] == pytest.approx(1.0, abs=1e-6)
        # The three buckets, on the NOMINAL table, are the whole table too.
        assert (
            information["responsive_nominal_weight"]
            + information["pinned_nominal_weight"]
            + information["duplicate_nominal_weight"]
            + information["unmeasured_nominal_weight"]
        ) == pytest.approx(1.0, abs=1e-6)
        # The contributions attribute every point of the headline.
        assert sum(information["headline_attribution"].values()) == pytest.approx(
            result["overall_score"], abs=0.05
        )
        # `headline_basis_score` used to be asserted == the ROUNDED
        # `overall_score`, and the two bucket shares were reconstructed against
        # it.  That pinned the defect rather than the property: the shares are
        # built from UNROUNDED contributions, so dividing them by a rounded
        # denominator made the five published shares sum to 1.001419 on the v26
        # book -- 13.118601 of contribution over a 13.1 denominator.  The shares
        # are now divided by the unrounded total, which is published, so the
        # property to assert is the sum and the reconciliation against THAT
        # number -- both of which are wrong under the old code.
        assert information["headline_basis_score"] == pytest.approx(
            result["overall_score"], abs=0.05
        )
        assert information["headline_basis_score_rounded"] == result["overall_score"]
        assert information["pinned_share_of_headline"] == pytest.approx(
            sum(
                information["headline_attribution"][leg]
                for leg in information["pinned_legs"]
            )
            / information["headline_basis_score"],
            abs=1e-6,
        )
        # `duplicate_share_of_headline` is the duplicate leg's CONTRIBUTION over
        # the basis, not its rounded `sub_score` over the basis: the duplicate
        # leg's sub-score is 7.6 published / 7.615353 measured on the v26 book, a
        # 1.6e-4 gap in the share. `components.<leg>.headroom_to_cap` recovers
        # the unrounded value exactly (cap - headroom), so that is the number
        # the share is checked against.
        duplicate = information["duplicate_legs"][0]
        unrounded = (
            RISK_SCORE_CAP - _legs(audit)["market_risk"]["headroom_to_cap"]
        )
        assert information["duplicate_share_of_headline"] == pytest.approx(
            information["headline_attribution"][duplicate]
            / information["headline_basis_score"],
            abs=1e-6,
        )
        assert information["duplicate_share_of_headline"] == pytest.approx(
            information["duplicate_weight"] * unrounded
            / information["headline_basis_score"],
            abs=1e-6,
        )

    @pytest.mark.asyncio
    async def test_the_published_shares_partition_the_headline(self):
        """A share column that does not sum to 1 is not a share column.

        The property was violated on every real book, not just the export one:
        each `headline_share` divided an UNROUNDED contribution by the ROUNDED
        `overall_score`, so the five shares summed to 1.001419 on the v26 book
        (13.118601 / 13.1). Rounding a share to 6 dp can move the sum by at most
        5 x 2.5e-6, so the assertion below is two orders of magnitude tighter
        than the defect it pins and cannot be satisfied by a rounding artefact.
        """
        engine = AnalyticsEngine()
        frame, benchmark, weights = _diversified_book()
        result = await engine.risk_scoring(frame, weights, benchmark_data=benchmark)
        audit = _audit(result)
        information = audit["effective_information"]
        shares = {
            name: leg["headline_share"]
            for name, leg in _legs(audit).items()
            if leg["headline_share"] is not None
        }
        assert len(shares) == information["measured_leg_count"]
        assert sum(shares.values()) == pytest.approx(1.0, abs=1e-5)
        # And each one reconciles against the PUBLISHED unrounded basis, which
        # is what makes the sum checkable by a reader rather than by this file.
        for name, share in shares.items():
            assert share == pytest.approx(
                _legs(audit)[name]["headline_contribution"]
                / information["headline_basis_score"],
                abs=1e-6,
            ), name

    @pytest.mark.asyncio
    async def test_the_unrounded_headline_is_published_beside_the_rounded_one(self):
        """`overall_score_raw` did not exist on risk_score at all -- not null,
        ABSENT -- while `liquidity` had published exactly that pair since an
        earlier wave. `headline_basis_score` is the same number under the name
        the shares are divided by, so a reader can reconcile them against each
        other instead of against a rounded value.
        """
        engine = AnalyticsEngine()
        frame, benchmark, weights = _diversified_book()
        result = await engine.risk_scoring(frame, weights, benchmark_data=benchmark)
        information = _audit(result)["effective_information"]
        assert information["overall_score_raw"] is not None
        assert information["headline_basis_score"] == information["overall_score_raw"]
        # `overall_score` is the same number at the display precision, and is
        # what `risk_level` was decided on. Neither moved.
        assert result["overall_score"] == information["headline_basis_score_rounded"]
        assert information["overall_score_raw"] == pytest.approx(
            result["overall_score"], abs=0.05
        )
        assert sum(information["headline_attribution"].values()) == pytest.approx(
            information["overall_score_raw"], abs=1e-5
        )

    @pytest.mark.asyncio
    async def test_a_sum_claim_in_a_published_sentence_is_backed_by_the_numbers(self):
        """The general form of the defect this wave fixed.

        `headline_weight_basis` used to read "...and the first three sum to 1 --
        the whole headline" with no noun, in a block whose three preceding keys
        are `*_share_of_headline`. A reader had one reading available and it was
        false: the three SHARES summed to 1.001419. The sentence now names both
        quantities, and this test pins the claim rather than the wording -- if it
        asserts a sum, the published numbers it names must deliver that sum.
        """
        engine = AnalyticsEngine()
        frame, benchmark, weights = _diversified_book()
        result = await engine.risk_scoring(frame, weights, benchmark_data=benchmark)
        audit = _audit(result)
        information = audit["effective_information"]
        basis = information["headline_weight_basis"]

        weight_sum = (
            information["responsive_weight"]
            + information["pinned_weight"]
            + information["duplicate_weight"]
        )
        share_sum = (
            information["responsive_share_of_headline"]
            + information["pinned_share_of_headline"]
            + information["duplicate_share_of_headline"]
        )
        if "sum to 1" in basis:
            assert "WEIGHTS" in basis, basis
            assert weight_sum == pytest.approx(1.0, abs=1e-6)
            assert share_sum == pytest.approx(1.0, abs=1e-5)
        # Unconditionally, because a reword that simply dropped the claim would
        # otherwise let the sums rot unnoticed: both sums are properties of the
        # payload, not of the sentence.
        assert weight_sum == pytest.approx(1.0, abs=1e-6)
        assert share_sum == pytest.approx(1.0, abs=1e-5)

    @pytest.mark.asyncio
    async def test_an_unmeasured_leg_is_counted_as_unmeasured_not_as_pinned(self):
        engine = AnalyticsEngine()
        result = await engine.risk_scoring(
            _correlated_frame(columns=("A",)), {"A": 1.0}
        )
        information = _audit(result)["effective_information"]
        legs = _legs(_audit(result))
        assert information["measured_leg_count"] == 3
        assert information["unmeasured_leg_count"] == 2
        assert information["unmeasured_nominal_weight"] == pytest.approx(0.45)
        assert legs["correlation"]["headline_bucket"] == "excluded"
        assert legs["factor_risk"]["headline_bucket"] == "excluded"
        # The survivors are renormalized, so they are still the whole headline.
        assert (
            information["responsive_weight"]
            + information["pinned_weight"]
            + information["duplicate_weight"]
        ) == pytest.approx(1.0, abs=1e-6)
        assert "factor_risk" not in information["pinned_legs"]
        assert "correlation" not in information["pinned_legs"]

    @pytest.mark.asyncio
    async def test_a_fully_measured_score_with_nothing_wrong_says_so(self):
        """The disclosure has to be able to say 'nothing is wrong here' as well.

        Without this the block could pass every test above by declaring a
        duplication and a pinned leg unconditionally.
        """
        engine = AnalyticsEngine()
        frame, benchmark, weights = _diversified_book()
        result = await engine.risk_scoring(frame, weights, benchmark_data=benchmark)
        audit = _audit(result)
        information = audit["effective_information"]
        assert result["excluded_components"] == []
        assert result["saturated_components"] == [], result["components"]
        assert information["pinned_weight"] == 0.0
        assert information["pinned_legs"] == []
        # The market leg is a shorter window on the volatility leg's series; that
        # is the only non-independent leg here, and it is declared as such.
        assert information["duplicate_weight"] == pytest.approx(0.10)
        assert information["independent_leg_count"] == 4
        assert information["responsive_weight"] == pytest.approx(0.90)
        assert audit["components"]["volatility"]["headline_bucket"] == "responsive"
        assert audit["components"]["market_risk"]["headline_bucket"] == "duplicate"
        assert not any(
            f"{leg} is pinned at the" in alert
            for leg in RISK_SCORE_WEIGHTS
            for alert in result["alerts"]
        ), result["alerts"]


# ---------------------------------------------------------------------------
# 5. the invariant: a components map never presents a duplicate as independent
# ---------------------------------------------------------------------------
class TestNoUndeclaredNonEvidence:
    @pytest.mark.asyncio
    async def test_every_declared_status_is_backed_by_the_measurement(self):
        """Sweep the sample length and re-derive both claims independently.

        The test does not trust the payload's own labels: it recomputes the row
        counts, the series relation and the cap from the values the payload
        published and requires the labels to agree.
        """
        engine = AnalyticsEngine()
        for n in (30, 40, 61, 62, 90, 200):
            frame = _correlated_frame(n=n)
            result = await engine.risk_scoring(
                frame, WEIGHTS, benchmark_data=_noise_benchmark(frame)
            )
            audit = _audit(result)
            legs = _legs(audit)

            # (a) saturation, re-derived from the published headroom.
            for name, leg in legs.items():
                if leg["sub_score"] is None:
                    assert leg["saturated"] is False, name
                    continue
                expected = leg["headroom_to_cap"] == 0.0
                assert leg["saturated"] is expected, (n, name, leg)
                assert (
                    name in result["saturated_components"]
                ) is expected, (n, name)

            # (b) duplication, re-derived from the published row counts.
            vol_rows = legs["volatility"]["input_sample"]["rows"]
            market_rows = legs["market_risk"]["input_sample"]["rows"]
            same_rows = vol_rows == market_rows
            if same_rows:
                assert legs["market_risk"]["duplicate_of"] == "volatility", n
                assert legs["market_risk"]["duplicate_relation"] == "identical", n
                assert result["components"]["volatility"] == pytest.approx(
                    result["components"]["market_risk"], abs=0.05
                ), n
                assert legs["market_risk"]["counts_as_independent_evidence"] is False
            elif market_rows < vol_rows:
                assert legs["market_risk"]["duplicate_of"] == "volatility", n
                assert legs["market_risk"]["duplicate_relation"] == "strict_subset"
                assert legs["market_risk"]["counts_as_independent_evidence"] is False
            else:  # pragma: no cover - tail() can only shorten the series
                pytest.fail(f"market leg read MORE rows ({market_rows}) than volatility ({vol_rows})")

            # (c) a leg that is not independent evidence is never silent about it.
            non_independent = [
                name
                for name, leg in legs.items()
                if leg["status"] != "unmeasured"
                and not leg["counts_as_independent_evidence"]
            ]
            declared = {entry["component"] for entry in result["duplicate_components"]}
            assert set(non_independent) == declared, n
            assert result["independent_component_count"] == len(
                [name for name, leg in legs.items() if leg["status"] != "unmeasured"]
            ) - len(declared), n
            for name in declared:
                assert any(name in alert for alert in result["alerts"]), (n, name)

    @pytest.mark.asyncio
    async def test_an_unmeasured_input_is_published_unknown_with_a_reason(self):
        """Never infer an input. Publish it absent, and say why."""
        engine = AnalyticsEngine()
        result = await engine.risk_scoring(
            _correlated_frame(columns=("A",)), {"A": 1.0}
        )
        legs = _legs(_audit(result))
        for name in ("correlation", "factor_risk"):
            leg = legs[name]
            assert leg["status"] == "unmeasured"
            assert leg["input_statistic_value"] is None
            assert leg["input_statistic_provenance"] == "unavailable"
            assert leg["input_statistic_unavailable_reason"]

    @pytest.mark.asyncio
    async def test_a_leg_whose_row_count_the_engine_cannot_see_says_so(self):
        """The factor leg's sample is measured by the route, not here.

        The engine fits the regression but never counts the rows the fit kept, so
        the honest publication is `rows: null` plus the reason -- not the
        constituent frame's length wearing the regression's name.
        """
        engine = AnalyticsEngine()
        frame = _correlated_frame(n=120)
        result = await engine.risk_scoring(
            frame, WEIGHTS, benchmark_data=_noise_benchmark(frame)
        )
        sample = _legs(_audit(result))["factor_risk"]["input_sample"]
        assert sample["row_kind"] == "regression_rows"
        assert sample["rows"] is None
        assert "model_observation_count" in sample["rows_reason"]
        # The legs whose rows the engine DOES see publish them.
        for name in ("volatility", "market_risk", "correlation"):
            assert _legs(_audit(result))[name]["input_sample"]["rows"] > 0, name

    def test_an_unmeasured_score_declares_the_absence_of_the_block(self):
        engine = AnalyticsEngine()
        empty = engine._empty_risk_score()
        assert empty["score_audit"] is None
        assert empty["score_audit_reason"]
        assert empty["saturated_components"] == []
        assert empty["duplicate_components"] == []


# ---------------------------------------------------------------------------
# 6. nothing about the score itself moved
# ---------------------------------------------------------------------------
class TestTheScoreIsUnchanged:
    @pytest.mark.asyncio
    async def test_overall_score_and_risk_level_are_still_the_weighted_average(self):
        """This is a disclosure fix. The arithmetic must be bit-identical."""
        engine = AnalyticsEngine()
        result = await engine.risk_scoring(
            _correlated_frame(n=120), WEIGHTS, benchmark_data=_noise_benchmark(
                _correlated_frame(n=120)
            )
        )
        components = result["components"]
        expected = sum(
            components[name] * RISK_SCORE_WEIGHTS[name] for name in RISK_SCORE_WEIGHTS
        )
        assert result["overall_score"] == pytest.approx(round(expected, 1), abs=0.15)
        assert result["risk_level"] in {"LOW", "MEDIUM", "HIGH"}
        if result["overall_score"] < 15:
            assert result["risk_level"] == "LOW"
        elif result["overall_score"] < 25:
            assert result["risk_level"] == "MEDIUM"
        else:
            assert result["risk_level"] == "HIGH"

    @pytest.mark.asyncio
    async def test_the_weight_table_is_the_one_that_was_always_applied(self):
        assert RISK_SCORE_WEIGHTS == {
            "concentration": 0.20,
            "volatility": 0.25,
            "correlation": 0.20,
            "factor_risk": 0.25,
            "market_risk": 0.10,
        }
        assert RISK_MARKET_WINDOW_ROWS == 60
        assert RISK_SCORE_CAP == 30.0
        assert RISK_FACTOR_UNPIN_R_SQUARED == pytest.approx(0.70)

    @pytest.mark.asyncio
    async def test_a_leg_that_cannot_be_measured_is_still_excluded_not_zeroed(self):
        """D-04 and the NaN-to-max guard, unchanged by the disclosure."""
        engine = AnalyticsEngine()
        result = await engine.risk_scoring(pd.DataFrame(), {})
        assert result["overall_score"] is None
        assert result["score_audit"] is None

        single = await engine.risk_scoring(_correlated_frame(columns=("A",)), {"A": 1.0})
        assert single["components"]["correlation"] is None
        assert "correlation" in single["excluded_components"]
        assert not any(
            isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0
            for v in single["components"].values()
            if v is not None
        )
        # An empty portfolio return series must not become a maximum risk score.
        flat = pd.DataFrame({"A": [100.0, 100.0, 100.0, 100.0, 100.0]}, columns=["A"])
        degenerate = await engine.risk_scoring(flat, {"A": 1.0})
        assert degenerate["components"]["volatility"] in (None, 0.0)
        assert degenerate["components"]["volatility"] != RISK_SCORE_CAP


# ---------------------------------------------------------------------------
# 7. it survives the route, into the payload the review inspected
# ---------------------------------------------------------------------------
class _Book:
    """A short book: fewer delivered return rows than the market leg's window."""

    DAYS = 45

    def __init__(self) -> None:
        dates = pd.bdate_range(end="2026-09-25", periods=self.DAYS)
        self.frames = {
            name: pd.DataFrame(
                {
                    "date": dates,
                    "adj_close": 100.0
                    * np.exp(np.cumsum(np.random.default_rng(seed).normal(0.0004, 0.011, self.DAYS))),
                    "volume": np.full(self.DAYS, 1e6),
                }
            )
            for name, seed in (("AAA.NS", 41), ("BBB.NS", 43), ("CCC.NS", 47))
        }

    async def fetch_historical_data(self, ticker, start, end):
        frame = self.frames.get(ticker)
        if frame is None or frame.empty:
            return pd.DataFrame()
        low = pd.Timestamp(start).normalize() if start else frame["date"].min()
        high = pd.Timestamp(end).normalize() if end else frame["date"].max()
        return frame.loc[(frame["date"] >= low) & (frame["date"] <= high)].copy()


class _Rows:
    def __init__(self, rows: List[Any]) -> None:
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


@pytest.mark.asyncio
async def test_the_route_publishes_the_composition_with_the_score():
    """The defect was read off an export, so the fix has to reach the export.

    The route returns the engine's payload with its own keys merged in, so this
    asserts the disclosure survives that merge -- and, on a book shorter than
    `tail(60)`, that the route's own published sub-scores are the two equal
    numbers RL-3 was about.
    """
    from app.api.analytics import get_risk_score
    from app.models.database import PortfolioPosition

    book = _Book()
    dates = pd.bdate_range(end="2026-09-25", periods=_Book.DAYS)
    positions = [
        PortfolioPosition(
            id=index + 1, ticker=ticker, weight=weight, quantity=10.0,
            buy_price=None, last_price=100.0, market_value=10000.0,
            region="IN", sector="X", industry="Y", added_on=dates[0].to_pydatetime(),
        )
        for index, (ticker, weight) in enumerate(
            (("AAA.NS", 0.4), ("BBB.NS", 0.35), ("CCC.NS", 0.25))
        )
    ]
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=lambda *_a, **_k: _Rows(positions))
    benchmark = MagicMock(
        get_returns=AsyncMock(
            return_value=pd.Series(
                np.random.default_rng(3).normal(0.0004, 0.01, _Book.DAYS), index=dates
            )
        )
    )

    res = await get_risk_score(
        db=db, data_service=book, analytics_engine=AnalyticsEngine(),
        benchmark_service=benchmark,
    )

    assert res["overall_score"] is not None
    audit = _audit(res)
    legs = _legs(audit)
    rows = legs["volatility"]["input_sample"]["rows"]
    assert rows < RISK_MARKET_WINDOW_ROWS, "this book must be shorter than the window"
    assert legs["market_risk"]["duplicate_of"] == "volatility"
    assert legs["market_risk"]["duplicate_relation"] == "identical"
    assert res["components"]["volatility"] == res["components"]["market_risk"]
    assert res["independent_component_count"] == 4
    # The saturation block is present whatever the sample decided.
    assert "saturated_components" in res
    by_statistic = {
        "herfindahl_index": "concentration",
        "portfolio_return_annualized_volatility": "volatility",
        "avg_pairwise_correlation": "correlation",
        "benchmark_regression_r_squared": "factor_risk",
        "recent_portfolio_return_annualized_volatility": "market_risk",
    }
    for leg in legs.values():
        assert leg["cap"] == RISK_SCORE_CAP
        assert leg["formula"]
        assert leg["nominal_weight"] == RISK_SCORE_WEIGHTS[
            by_statistic[leg["input_statistic"]]
        ]
