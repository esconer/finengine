"""Three assertions the engine makes that it should not, or that misinform.

1. **The stress table's "Exchange Traded Fund" bucket is the route's
   UNCLASSIFIED sector.**  `app/api/analytics.py` fills `sectors` from
   `PortfolioPosition.sector` and every holding whose stored sector is NULL
   lands in one bucket, whatever the instrument is.  On the live book that
   bucket holds a domestic broad index tracker, two domestic midcap trackers, an
   Indian IPO/small-cap fund and a US-listed mega-cap technology fund, and the
   scenario table gave all of them one flat index sensitivity (1.00-1.05).  That
   asserts a co-movement that is false for at least one of them, and the engine
   publishes no per-holding market, index or currency exposure anywhere, so a
   reader cannot tell.

   The fix here is disclosure, not a number, and the tests below pin WHY a
   number was not invented:

     * no ticker-keyed map exists in the engine (a hand-written bucket per
       instrument is the same defect in a new place),
     * the bucket's membership, the single elasticity applied to it and the
       per-holding elasticity basis are published,
     * a measured co-movement per holding is published so the flat entry is
       checkable rather than asserted -- and is NOT applied to any shock,
       because on a book of mutually uncorrelated holdings that coefficient is
       0.13, 0.02, 0.04 and -0.07, and applying it to a -10% market shock would
       publish a ~0% loss on a market crash and a GAIN on one holding.  That is
       book diversification, not a market beta, and a benchmark series is not an
       input to `stress_test`.

2. **A `correlation` sub-score of exactly 0.0 is reachable from a measured
   negative average correlation.**  The 0-30 scale has no negative risk points,
   so `max(0, avg)` floors it -- which is a scale bound, and a scale bound that
   was not declared.  A clamped 0.0 is indistinguishable from a measured zero
   correlation.  The floor stays (removing it moves `overall_score` and can flip
   `risk_level`, a product decision); what changes is that the bound, the input
   at which it binds, whether it bound, and the points it added are published.

3. **`components` values are numpy scalars (and `concentration` is an int)
   before JSON.**  Harmless to today's serialiser, but anything added later
   inherits it.

No network, no DB, seeded RNG only.  The audit CLI is deliberately not run: it
reads a frozen export, so it could say nothing about this code.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
from typing import Any, Dict

import numpy as np
import pandas as pd
import pytest

from app.services import analytics_engine as engine_module
from app.services.analytics_engine import (
    RISK_CORRELATION_POINTS_PER_UNIT,
    RISK_SCORE_CAP,
    RISK_SCORE_FLOOR,
    RISK_SCORE_LEG_SPECS,
    STRESS_CO_MOVEMENT_MIN_OBSERVATIONS,
    STRESS_CO_MOVEMENT_MIN_REFERENCE_LEGS,
    STRESS_UNCLASSIFIED_SECTOR,
    AnalyticsEngine,
    _stress_holding_co_movement,
)

# The five tickers the v5 review found sharing the unclassified bucket.  Their
# classification is NOT restated here as a fact about the instruments: this file
# only uses them as names that must be treated identically by the code, and
# asserts that the engine learns nothing about them.
BUCKET_MEMBERS = (
    "NIFTYIETF.NS",
    "MIDCAPIETF.NS",
    "JUNIORBEES.NS",
    "SELECTIPO.NS",
    "MAFANG.NS",
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def _prices_from_returns(returns: Dict[str, np.ndarray], index) -> pd.DataFrame:
    """A price frame whose `pct_change` IS the return series passed in."""
    return pd.DataFrame(
        {name: 100.0 * np.cumprod(1.0 + values) for name, values in returns.items()},
        index=index,
    )


def _bucket_book(n: int = 320, seed: int = 3, include_overridden: bool = True):
    """A book shaped like the live one: one market factor, five bucket members.

    Three of the bucket members track the market, one is half-loaded, and one
    (standing in for the US-listed mega-cap technology fund) has NO market
    loading at all.  Nothing in the engine knows which is which; the frame is
    the only thing that distinguishes them.

    `include_overridden=False` drops the two members that carry a named
    `instrument_override_*` in the scenario table, which is how a test can look
    at the bucket's own flat row without an override perturbing it.
    """
    rng = np.random.default_rng(seed)
    market = rng.normal(0.0, 0.010, n)
    returns = {
        "CIPLA.NS": market + rng.normal(0.0, 0.008, n),
        "NTPC.NS": market + rng.normal(0.0, 0.008, n),
        "MCX.NS": market + rng.normal(0.0, 0.008, n),
        "NIFTYIETF.NS": market + rng.normal(0.0, 0.001, n),
        "MIDCAPIETF.NS": 1.1 * market + rng.normal(0.0, 0.004, n),
        "JUNIORBEES.NS": 1.0 * market + rng.normal(0.0, 0.003, n),
        "SELECTIPO.NS": 0.5 * market + rng.normal(0.0, 0.012, n),
        "MAFANG.NS": rng.normal(0.0, 0.018, n),
    }
    if not include_overridden:
        for name in ("MIDCAPIETF.NS", "SELECTIPO.NS"):
            returns.pop(name)
    index = pd.bdate_range("2025-01-01", periods=n)
    weights = {name: 1.0 / len(returns) for name in returns}
    return _prices_from_returns(returns, index), weights


def _uncorrelated_book(n: int = 252, seed: int = 42):
    """Four holdings with no shared factor -- the shape of `mock_price_dataframe`.

    This is the fixture that decides whether a book-relative coefficient can be
    used as a market-shock elasticity.  It cannot, and the test that uses it
    says so with the arithmetic instead of asserting it.
    """
    rng = np.random.default_rng(seed)
    names = ("AAPL", "MSFT", "GOOGL", "AMZN")
    returns = {name: rng.normal(0.0, 0.02, n) for name in names}
    index = pd.bdate_range("2023-01-01", periods=n, freq="B")
    weights = {name: 0.25 for name in names}
    return _prices_from_returns(returns, index), weights


def _negatively_correlated_book(n: int = 200, seed: int = 5):
    """Two holdings whose realised correlation is strongly negative."""
    rng = np.random.default_rng(seed)
    a = rng.normal(0.0, 0.01, n)
    b = -0.8 * a + rng.normal(0.0, 0.004, n)
    index = pd.bdate_range("2025-01-01", periods=n)
    return (
        _prices_from_returns({"AAA.NS": a, "BBB.NS": b}, index),
        {"AAA.NS": 0.5, "BBB.NS": 0.5},
    )


def _positively_correlated_book(n: int = 200, seed: int = 9):
    """Two holdings that co-move, so the floor must NOT bind."""
    rng = np.random.default_rng(seed)
    a = rng.normal(0.0, 0.01, n)
    b = 0.7 * a + rng.normal(0.0, 0.004, n)
    index = pd.bdate_range("2025-01-01", periods=n)
    return (
        _prices_from_returns({"AAA.NS": a, "BBB.NS": b}, index),
        {"AAA.NS": 0.5, "BBB.NS": 0.5},
    )


def _shock_inputs(result: Dict[str, Any]) -> Dict[str, Any]:
    assert result.get("shock_inputs"), "the shock inputs must be published"
    return result["shock_inputs"]


# ---------------------------------------------------------------------------
# 1a. the bucket is disclosed as the unclassified bucket it is
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestUnclassifiedBucketDisclosure:
    @pytest.mark.asyncio
    async def test_the_bucket_publishes_its_members_and_says_it_is_unclassified(self):
        """The defect: one number for a bucket whose name describes none of it."""
        engine = AnalyticsEngine()
        frame, weights = _bucket_book()
        result = await engine.stress_test(frame, weights, "market_crash")
        shock = _shock_inputs(result)

        assert shock["default_sector"] == STRESS_UNCLASSIFIED_SECTOR
        assert "default_sector_meaning" in shock
        assert "an asset-class label" in shock["default_sector_meaning"]
        # The members are NAMED. Before this, nothing in the payload said which
        # holdings the flat sensitivity was applied to.
        assert set(BUCKET_MEMBERS) <= set(
            shock["unclassified_bucket_members"]
        )
        assert shock["unclassified_bucket_member_count"] == len(
            shock["unclassified_bucket_members"]
        )
        disclosure = shock["bucket_disclosure"]
        assert "UNCLASSIFIED sector" in disclosure
        assert "not a classification" in disclosure
        # And it says the two things a reader cannot otherwise know.
        assert "no per-holding market, index or currency exposure" in disclosure
        assert "nothing in this payload says which market a member tracks" in (
            disclosure
        )

    @pytest.mark.asyncio
    async def test_the_single_flat_elasticity_is_published_not_left_implicit(self):
        """The finding restated as a checkable claim: one number, whole bucket."""
        engine = AnalyticsEngine()
        frame, weights = _bucket_book(include_overridden=False)
        result = await engine.stress_test(frame, weights, "market_crash")
        shock = _shock_inputs(result)

        # No sectors supplied -> every holding is in the unclassified bucket, and
        # none of the three overridden tickers is in this fixture, so the bucket
        # really is shocked by one number.
        for ticker in ("NIFTYIETF.NS", "JUNIORBEES.NS", "MAFANG.NS"):
            entry = shock["co_movement"]["by_ticker"][ticker]
            assert entry["sector"] == STRESS_UNCLASSIFIED_SECTOR
            assert entry["sector_is_unclassified_bucket"] is True
            assert entry["applied_elasticity"] == 1.0
            assert entry["applied_elasticity_basis"] == "scenario_sector_table"
            assert entry["applied_elasticity_is_per_instrument"] is False
        assert shock["sector_elasticity_is_one_number_for_the_bucket"] is True
        assert shock["unclassified_bucket_applied_elasticities"] == [1.0]
        assert "Every one of them is shocked by the same 1 elasticity" in (
            shock["bucket_disclosure"]
        )

    @pytest.mark.asyncio
    async def test_the_published_elasticity_reproduces_every_published_impact(self):
        """The whole chain is recomputable: shock x elasticity x volatility."""
        engine = AnalyticsEngine()
        frame, weights = _bucket_book()
        result = await engine.stress_test(frame, weights, "market_crash")
        shock = _shock_inputs(result)
        shock_value = shock["market_shock"]
        factors = shock["volatility_adjustment"]["by_ticker"]

        for ticker, entry in shock["co_movement"]["by_ticker"].items():
            expected = (
                shock_value * entry["applied_elasticity"] * factors[ticker]["factor"]
            )
            assert result["position_impacts"][ticker] == pytest.approx(
                round(expected, 4), abs=1e-4
            ), ticker

    @pytest.mark.asyncio
    async def test_a_named_instrument_override_is_flagged_as_per_instrument(self):
        """The pre-existing overrides stay, and are now visibly not bucket-wide."""
        engine = AnalyticsEngine()
        frame, weights = _bucket_book()
        result = await engine.stress_test(frame, weights, "market_crash")
        shock = _shock_inputs(result)
        entry = shock["co_movement"]["by_ticker"]["MIDCAPIETF.NS"]

        assert entry["applied_elasticity"] == 1.30
        assert entry["applied_elasticity_basis"] == "instrument_override_midcap_etf"
        assert entry["applied_elasticity_is_per_instrument"] is True
        # So the bucket is no longer one number, and the payload says so rather
        # than letting a reader infer homogeneity from the bucket name.
        assert shock["sector_elasticity_is_one_number_for_the_bucket"] is False
        assert shock["unclassified_bucket_applied_elasticities"] == [1.0, 1.15, 1.30]
        assert "not one number" in shock["bucket_disclosure"]


# ---------------------------------------------------------------------------
# 1b. the measured co-movement, and why it is not the elasticity
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCoMovementIsMeasuredAndNotApplied:
    @pytest.mark.asyncio
    async def test_co_movement_is_measured_per_holding_and_spreads_widely(self):
        """The measurement that makes the flat entry checkable."""
        engine = AnalyticsEngine()
        frame, weights = _bucket_book()
        result = await engine.stress_test(frame, weights, "market_crash")
        shock = _shock_inputs(result)
        by_ticker = shock["co_movement"]["by_ticker"]

        assert shock["co_movement"]["basis"].endswith("not_a_market_beta")
        assert shock["co_movement"]["is_applied_to_the_shock"] is False
        measured = {
            name: entry["co_movement_with_rest_of_book"]
            for name, entry in by_ticker.items()
        }
        for name, value in measured.items():
            assert isinstance(value, float), name
            assert by_ticker[name]["co_movement_is_used_as_elasticity"] is False
        # The three index trackers co-move with the book; the fund with no
        # market loading does not.  A single 1.00 for all of them is falsified
        # by the payload's own measurement.
        assert measured["NIFTYIETF.NS"] > 0.9
        assert measured["JUNIORBEES.NS"] > 0.9
        assert abs(measured["MAFANG.NS"] - 1.0) > 0.5
        assert max(measured.values()) - min(measured.values()) > 1.0

    @pytest.mark.asyncio
    async def test_an_uncorrelated_book_is_never_given_a_market_elasticity(self):
        """THE CAUSE. Why the cheap substitute was refused, in arithmetic.

        Four uncorrelated holdings give a book-relative coefficient of 0.13,
        0.02, 0.04 and -0.07.  Using that as the elasticity would publish a
        ~0% loss on a -10% market crash and a gain on one holding, which is
        diversification within the book dressed up as market sensitivity.  The
        engine must publish the coefficient and keep the table's 1.00.
        """
        engine = AnalyticsEngine()
        frame, weights = _uncorrelated_book()
        result = await engine.stress_test(frame, weights, "crash -10%")
        shock = _shock_inputs(result)
        by_ticker = shock["co_movement"]["by_ticker"]

        coefficients = [
            entry["co_movement_with_rest_of_book"]
            for entry in by_ticker.values()
        ]
        assert min(coefficients) < 0.0, coefficients
        assert max(abs(c) for c in coefficients) < 0.5, coefficients

        # The shock is still the table's 1.00 scaled by the measured volatility,
        # and NOT the coefficient: this is the number the refused substitution
        # would have produced.
        factors = shock["volatility_adjustment"]["by_ticker"]
        factor = factors["AAPL"]["factor"]
        assert result["portfolio_impact"] == pytest.approx(
            round(-0.10 * 1.0 * factor, 4), abs=1e-4
        )
        refused = round(-0.10 * max(coefficients) * factor, 4)
        assert abs(result["portfolio_impact"] - refused) > 0.05, (
            "if these agree, the co-movement IS being applied as the elasticity"
        )
        assert shock["co_movement"]["is_applied_to_the_shock"] is False

    @pytest.mark.asyncio
    async def test_a_two_holding_book_publishes_no_co_movement_rather_than_a_fake(self):
        """On a two-name book the coefficient is 1.0 by construction."""
        engine = AnalyticsEngine()
        rng = np.random.default_rng(2)
        n = 120
        index = pd.bdate_range("2025-01-01", periods=n)
        frame = _prices_from_returns(
            {
                "AAA.NS": rng.normal(0.0, 0.01, n),
                "BBB.NS": rng.normal(0.0, 0.01, n),
            },
            index,
        )
        result = await engine.stress_test(frame, {"AAA.NS": 0.5, "BBB.NS": 0.5}, "market_crash")
        by_ticker = _shock_inputs(result)["co_movement"]["by_ticker"]

        for name, entry in by_ticker.items():
            assert entry["co_movement_with_rest_of_book"] is None, name
            reason = entry["co_movement_unavailable_reason"]
            assert reason and "1.0 by construction" in reason, name
            assert entry["co_movement_reference_leg_count"] < (
                STRESS_CO_MOVEMENT_MIN_REFERENCE_LEGS
            )

    def test_too_few_paired_rows_is_an_absence_with_a_reason(self):
        """Never a coefficient out of a handful of rows."""
        n = STRESS_CO_MOVEMENT_MIN_OBSERVATIONS - 5
        rng = np.random.default_rng(1)
        index = pd.bdate_range("2025-01-01", periods=n)
        frame = _prices_from_returns(
            {f"L{i}": rng.normal(0.0, 0.01, n) for i in range(4)}, index
        )
        returns = frame.pct_change(fill_method=None).iloc[1:]
        measured = _stress_holding_co_movement(returns)

        assert set(measured) == set(returns.columns)
        for name, entry in measured.items():
            assert entry["co_movement"] is None, name
            assert "paired daily returns" in entry["co_movement_unavailable_reason"]
            assert entry["co_movement_basis"] is None

    @pytest.mark.asyncio
    async def test_the_co_movement_block_declares_what_it_is_not(self):
        engine = AnalyticsEngine()
        frame, weights = _bucket_book()
        shock = _shock_inputs(await engine.stress_test(frame, weights, "market_crash"))
        block = shock["co_movement"]

        assert "diversification WITHIN this book" in block[
            "co_movement_is_not_a_market_beta"
        ]
        assert "benchmark series delivered to this function" in block[
            "why_no_per_holding_elasticity_is_published"
        ]
        assert "A per-ticker sensitivity table would be the same defect" in block[
            "why_no_per_holding_elasticity_is_published"
        ]
        assert block["min_reference_legs"] == STRESS_CO_MOVEMENT_MIN_REFERENCE_LEGS
        assert (
            block["min_paired_observations"] == STRESS_CO_MOVEMENT_MIN_OBSERVATIONS
        )

    @pytest.mark.asyncio
    async def test_the_payload_is_strict_json_with_finite_numbers(self):
        engine = AnalyticsEngine()
        frame, weights = _bucket_book()
        result = await engine.stress_test(frame, weights, "market_crash")
        json.dumps(result, allow_nan=False)


# ---------------------------------------------------------------------------
# 1c. no hardcoded ticker-to-bucket map
# ---------------------------------------------------------------------------
TICKER_SHAPED = re.compile(r"^[A-Z][A-Z0-9&.-]*\.(NS|BO)$")


@pytest.mark.unit
class TestNoHardcodedTickerMap:
    def test_the_engine_source_has_no_ticker_keyed_mapping(self):
        """A guard, and the reason the bucket was not split by hand.

        A dict or set literal keyed by ticker would be the same defect in a new
        place: five hand-assigned buckets instead of five hand-assigned
        sensitivities, and just as wrong the day a sixth fund is bought.  The
        three `instrument_override_*` comparisons in the scenario loop are
        per-ticker judgements that are PUBLISHED BY NAME under
        `instrument_overrides`; they are not a bucket map, and this test does not
        pretend otherwise.
        """
        source = inspect.getsource(engine_module)
        tree = ast.parse(source)
        offenders: list[str] = []

        for node in ast.walk(tree):
            keys: list[Any] = []
            if isinstance(node, ast.Dict):
                keys = [
                    k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                ]
            elif isinstance(node, (ast.Set, ast.List, ast.Tuple)):
                keys = [
                    e.value for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
            tickers = [k for k in keys if TICKER_SHAPED.match(k)]
            if len(tickers) >= 2:
                offenders.append(f"{sorted(tickers)} at line {node.lineno}")

        assert offenders == [], (
            "ticker-keyed literals in analytics_engine.py: " + "; ".join(offenders)
        )

    def test_the_bucket_string_is_not_a_classification_of_the_members(self):
        """The bucket constant is a DEFAULT, and says which default it is."""
        assert STRESS_UNCLASSIFIED_SECTOR == "Exchange Traded Fund"
        assert engine_module.STRESS_CO_MOVEMENT_BASIS.endswith(
            "not_a_market_beta"
        )


# ---------------------------------------------------------------------------
# 2. the correlation floor is declared
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCorrelationFloorIsDeclared:
    @pytest.mark.asyncio
    async def test_a_measured_negative_correlation_declares_its_clamp(self):
        """The defect: a measured -0.89 average correlation published as 0.0."""
        engine = AnalyticsEngine()
        frame, weights = _negatively_correlated_book()
        result = await engine.risk_scoring(frame, weights)
        audit = result["score_audit"]
        leg = audit["components"]["correlation"]

        # The measurement is preserved with its sign ...
        assert result["avg_pairwise_correlation"] < -0.5
        assert leg["input_statistic_value"] == pytest.approx(
            result["avg_pairwise_correlation"], abs=1e-4
        )
        assert leg["input_statistic_provenance"] == "measured"
        # ... and the clamp is declared rather than looking like a measurement.
        assert result["components"]["correlation"] == 0.0
        assert leg["clamped_at_floor"] is True
        assert leg["floor"] == RISK_SCORE_FLOOR
        # The clamp is measured from the UNROUNDED average, which the leg
        # publishes at 6 decimals; recompute it from that, not from the 4-decimal
        # `avg_pairwise_correlation`.
        assert leg["floor_clamp_points"] == pytest.approx(
            -leg["input_statistic_value"] * RISK_CORRELATION_POINTS_PER_UNIT,
            abs=1e-4,
        )
        assert leg["floor_binding_input"] == 0.0
        assert "<= 0.00" in leg["floor_binds_when_input_is"]
        assert leg["floor_reason"]
        # At the audit level, beside the cap it mirrors.
        assert audit["floor"] == RISK_SCORE_FLOOR
        assert audit["floor_clamped_components"] == ["correlation"]
        detail = audit["floor_clamp_detail"][0]
        assert detail["component"] == "correlation"
        assert detail["clamp_points"] == leg["floor_clamp_points"]
        # And it is never silent: a reader sees it in the alerts.
        assert any(
            "correlation is clamped at the 0-point floor" in alert
            and "-0.8" in alert
            for alert in result["alerts"]
        ), result["alerts"]

    @pytest.mark.asyncio
    async def test_a_leg_that_misses_the_floor_does_not_claim_it(self):
        """The block must be able to say nothing is wrong here as well."""
        engine = AnalyticsEngine()
        frame, weights = _positively_correlated_book()
        result = await engine.risk_scoring(frame, weights)
        leg = result["score_audit"]["components"]["correlation"]

        assert result["avg_pairwise_correlation"] > 0.5
        assert leg["sub_score"] > 0.0
        assert leg["clamped_at_floor"] is False
        assert leg["floor_clamp_points"] == 0.0
        assert result["score_audit"]["floor_clamped_components"] == []
        assert not any(
            "clamped at the" in alert for alert in result["alerts"]
        ), result["alerts"]

    @pytest.mark.asyncio
    async def test_an_unmeasured_leg_publishes_no_floor_claim(self):
        """No input, no clamp: a null sub-score claims nothing about the floor."""
        engine = AnalyticsEngine()
        frame, _ = _negatively_correlated_book()
        result = await engine.risk_scoring(
            frame[["AAA.NS"]], {"AAA.NS": 1.0}
        )
        leg = result["score_audit"]["components"]["correlation"]

        assert "correlation" in result["excluded_components"]
        assert leg["sub_score"] is None
        assert leg["clamped_at_floor"] is False
        assert leg["floor_clamp_points"] is None
        assert leg["floor"] == RISK_SCORE_FLOOR

    def test_the_floor_is_a_declared_bound_on_every_leg(self):
        """The cap is declared per leg; the floor is now declared the same way."""
        assert RISK_SCORE_FLOOR == 0.0
        assert RISK_SCORE_CAP == 30.0
        spec = RISK_SCORE_LEG_SPECS["correlation"]
        assert spec["floor_binding_input"] == RISK_SCORE_FLOOR
        assert spec["floor_binds_when_input_is"]
        assert "no negative risk points" in spec["floor_reason"]
        # The formula still shows the clamp, so the declared bound and the
        # published arithmetic cannot disagree.
        assert "max(0, avg_pairwise_correlation)" in spec["formula"]
        # Every other leg's expression cannot go below zero, so it declares no
        # binding input rather than a false one.
        for name, leg_spec in RISK_SCORE_LEG_SPECS.items():
            if name == "correlation":
                continue
            assert "floor_binding_input" not in leg_spec, name


# ---------------------------------------------------------------------------
# 3. published numbers are plain floats
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestPublishedNumbersArePlainFloats:
    @pytest.mark.asyncio
    async def test_every_sub_score_and_the_headline_are_plain_floats(self):
        """`type(...) is float`, not isinstance: a numpy scalar IS a float.

        `portfolio_returns.std()` returns a numpy scalar, so `min(30, that *
        100)` and `round()` both stay numpy, and `min(30, 50.0)` is an int when
        the cap binds.  Neither breaks today's serialiser; both make a payload
        that is not plain JSON numbers, and anything added later inherits it.
        """
        engine = AnalyticsEngine()
        # Two 50/50 holdings: the concentration leg's expression is 50, so the
        # cap binds and that is where the int came from.
        frame, weights = _negatively_correlated_book()
        result = await engine.risk_scoring(frame, weights)

        assert type(result["overall_score"]) is float
        for name, value in result["components"].items():
            if value is None:
                continue
            assert type(value) is float, (name, type(value))
        # And the saturated leg, which is where the int came from.
        saturated = result["saturated_components"]
        assert saturated, "fixture must pin a leg at the cap"
        for name in saturated:
            assert type(result["components"][name]) is float, name

    @pytest.mark.asyncio
    async def test_the_whole_payload_is_strict_json(self):
        engine = AnalyticsEngine()
        frame, weights = _negatively_correlated_book()
        result = await engine.risk_scoring(frame, weights)
        json.dumps(result, allow_nan=False)
