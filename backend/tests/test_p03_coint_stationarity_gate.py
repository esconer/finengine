"""The stationarity gate: a low cointegration p-value is not evidence of a spread.

`analyze_pair_cointegration` ran two tests - Engle-Granger on the pair,
Johansen on the pair - and never tested either LEG. Cointegration is a
statement about the relationship between two I(1) series. Regress a stationary
A on a stationary B and the residuals are small whatever the two have to do
with each other, so Engle-Granger returns a low p-value: textbook spurious
regression. This scanner published that as a pair to trade, carrying a p-value
that read as evidence, and the payload had nowhere to say the legs were never
checked.

The gate, measured here:

  1. both legs are tested on log(price) - ADF and KPSS - and the pair is
     published as `SPURIOUS_REGRESSION_REJECTED` when they agree a leg is
     already stationary,
  2. the ADF p-value, the KPSS p-value, the resolved lags and the lag RULE
     travel with the verdict, because an ADF p-value with an unstated lag is
     worse than no test,
  3. a leg that cannot be measured is `undetermined` with a reason, never
     `stationary`, and it withholds too,
  4. nothing else moves. The Engle-Granger p-value, the t-statistic, the hedge
     ratio, the OU half-life, the Johansen rank and the family arithmetic are
     byte-identical for a pair that passes the gate.

The proof pair is two INDEPENDENT stationary AR(1) series. They are genuinely
related by construction (leg B is a positive multiple of leg A plus its own
stationary noise), which is exactly why Engle-Granger is confident - and a
linear combination of stationary processes is stationary, so both legs still
test I(0). That is the shape that ships a trade signal built on nothing.

No DB, no network. The preconditions the gate depends on (p-value, beta, z) are
asserted in each test, so a numerical drift upstream fails on the precondition
loudly instead of passing for the wrong reason.
"""

from typing import Any, Dict, Optional
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest

from app.api import analytics as analytics_mod
from app.api.analytics import get_cointegration_pairs
from app.models.schemas import CointPairResult
from app.services import cointegration_service as coint
from app.services.cointegration_service import (
    SIGNAL_SPURIOUS,
    SIGNAL_STATIONARITY_UNDETERMINED,
    SIGNAL_ZSCORE_THRESHOLD,
    STATIONARITY_GATE_PASSED,
    STATIONARITY_GATE_SPURIOUS,
    STATIONARITY_GATE_UNRESOLVED,
    STATIONARITY_KPSS_BANDWIDTH_RULE,
    STATIONARITY_LAG_RULE,
    CointegrationService,
    _IN_MEMORY_COINT_CACHE,
    analyze_pair_cointegration,
    apply_signal_directives,
    assess_leg_stationarity,
    assess_pair_stationarity,
    build_pair_signal,
    kpss_bandwidth,
)

N = 174
# Head tokens that make a signal an ORDER. The gate tests assert on these, not
# on prose, so a rewording of the explanation cannot quietly pass.
_ACTION_TOKENS = ("LONG_SPREAD", "SHORT_SPREAD")

# Leaves that existed before the stationarity gate. Byte-identity across the
# change is the whole no-regression claim, so they are enumerated rather than
# spot-checked.
_PRE_GATE_LEAVES = (
    "engle_granger_pvalue",
    "engle_granger_tstat",
    "is_cointegrated",
    "hedge_ratio_beta",
    "intercept_alpha",
    "hedge_ratio_beta_std_error",
    "intercept_alpha_std_error",
    "hedge_regression_observations",
    "hedge_regression_std_error_basis",
    "ou_half_life_days",
    "ou_reversion_speed_theta",
    "current_spread_zscore",
    "johansen_cointegrated",
    "last_price_a",
    "last_price_b",
    "observation_date_a",
    "observation_date_b",
    "overlap_start",
    "overlap_end",
    "overlap_observations",
    "price_basis",
    "decision_test",
    "johansen_role",
    "johansen_agrees_with_decision",
)


def _head(signal: Optional[str]) -> str:
    text = str(signal or "").strip()
    return text.split(" ", 1)[0] if text else ""


def _names_an_action(signal: Optional[str]) -> bool:
    return _head(signal) in _ACTION_TOKENS


def _ar1(phi: float, sigma: float, start: float, seed: int, n: int = N) -> np.ndarray:
    """A stationary AR(1) around `start` - I(0) by construction, not by luck."""
    rng = np.random.default_rng(seed)
    shocks = rng.normal(0.0, sigma, n)
    out = np.empty(n, dtype=float)
    out[0] = start
    for i in range(1, n):
        out[i] = start + phi * (out[i - 1] - start) + shocks[i]
    return out


def _spurious_pair() -> tuple:
    """Two independent stationary legs that Engle-Granger calls cointegrated.

    Leg B is `1.5 * leg A + stationary noise`, so the relationship is real
    enough for the pair test to be confident and both legs are still I(0). Seed
    22 was chosen because both KPSS p-values sit far from alpha (0.880, 0.916)
    rather than beside it, so the verdict does not hinge on a marginal draw.
    """
    leg_a = _ar1(0.30, 1.0, 100.0, 22)
    leg_b = 1.5 * leg_a + 12.0 + _ar1(0.30, 0.6, 0.0, 22 + 90000)
    return leg_a, leg_b


def _genuine_pair(seed: int = 0) -> tuple:
    """Two I(1) legs with a shared stochastic trend: real cointegration."""
    rng = np.random.default_rng(seed)
    leg_a = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.011, N)))
    leg_b = 1.4 * leg_a + np.cumsum(rng.normal(0.0, 0.30, N)) + 8.0
    return leg_a, leg_b


def _series(values: np.ndarray) -> pd.Series:
    return pd.Series(values, index=pd.bdate_range("2026-01-01", periods=len(values)))


# ---------------------------------------------------------------------------
# The proof: a spurious pair is not a trade
# ---------------------------------------------------------------------------


class TestSpuriousPairIsNotPublishedAsTradeable:
    def test_the_pair_looks_tradable_to_every_test_the_scanner_ran(self):
        """Fix the premise first. If any of this stopped holding, the gate test
        below would be passing for a reason that has nothing to do with the
        gate - so it is asserted, not assumed."""
        leg_a, leg_b = _spurious_pair()
        pair = analyze_pair_cointegration("STAT_A.NS", "STAT_B.NS", _series(leg_a), _series(leg_b))
        assert pair is not None
        # Engle-Granger is confident, and the payload says so.
        assert pair.engle_granger_pvalue < 0.05
        assert pair.is_cointegrated is True
        # The Johansen diagnostic AGREES, so the SI-1 contested rung does not
        # fire and the pair reaches the deeper rungs.
        assert pair.johansen_cointegrated is True
        assert pair.johansen_agrees_with_decision is True
        # The hedge ratio is positive, so the non-directional rung does not fire.
        assert pair.hedge_ratio_beta > 0.0
        # The spread is past the published z threshold.
        assert abs(pair.current_spread_zscore) >= SIGNAL_ZSCORE_THRESHOLD
        # And with a one-test family the multiplicity correction is the alpha
        # itself, so the correction rung does not fire either.
        assert _names_an_action(
            build_pair_signal(pair, family_alpha=0.05, comparisons_made=1)
        ) is False, "the gate must be what withholds this, not an earlier rung"

    def test_both_legs_are_measured_stationary(self):
        leg_a, leg_b = _spurious_pair()
        pair = analyze_pair_cointegration("STAT_A.NS", "STAT_B.NS", _series(leg_a), _series(leg_b))
        for leg, ticker in ((pair.stationarity_leg_a, "STAT_A.NS"), (pair.stationarity_leg_b, "STAT_B.NS")):
            assert leg["verdict"] == "stationary", leg
            assert leg["ticker"] == ticker
            # ADF rejects the unit root, KPSS does not reject stationarity:
            # both tests agree the leg is already I(0).
            assert leg["adf_pvalue"] < 0.05
            assert leg["kpss_pvalue"] >= 0.05
            # The object of the test is the log price, and the numbers that
            # produced the p-value travel with it.
            assert leg["transform"] == "log_price"
            assert leg["lag_rule"] == STATIONARITY_LAG_RULE
            assert leg["adf_lags"] is not None and leg["kpss_bandwidth"] is not None
            assert leg["reason"]

        assert pair.stationarity_gate["verdict"] == STATIONARITY_GATE_SPURIOUS
        assert pair.stationarity_gate["leg_a_verdict"] == "stationary"
        assert pair.stationarity_gate["leg_b_verdict"] == "stationary"
        assert "STAT_A.NS" in pair.stationarity_gate["reason"]
        assert "stationary" in pair.stationarity_gate["reason"]

    def test_the_published_signal_is_a_rejection_not_a_p_value(self):
        leg_a, leg_b = _spurious_pair()
        pair = analyze_pair_cointegration("STAT_A.NS", "STAT_B.NS", _series(leg_a), _series(leg_b))
        signal = build_pair_signal(pair, family_alpha=0.05, comparisons_made=1)

        assert _head(signal) == SIGNAL_SPURIOUS
        assert not _names_an_action(signal)
        # No rung may name a position in a string whose whole point is that it
        # withholds, so a consumer that greps rather than parses finds nothing.
        for token in (*_ACTION_TOKENS, " Long ", " Short "):
            assert token not in signal, signal
        # It still reports the p-value it measured - the test result is true -
        # and says why that number is not a spread.
        assert f"{pair.engle_granger_pvalue:.6f}" in signal
        assert "cointegration is defined between two I(1) series" in signal
        assert "no direction is published" in signal
        # The rule the p-values were produced under is published with them.
        assert STATIONARITY_LAG_RULE in signal

    def test_without_the_gate_this_pair_is_a_directive(self):
        """The teeth: with the gate read as absent, the SAME pair is an order.

        `build_pair_signal` reads the gate through one function, so patching it
        to report "not recorded" reproduces what this scanner published before
        the fix. If this test ever stops finding a directive, the gate is no
        longer load-bearing and the test above is passing vacuously.
        """
        leg_a, leg_b = _spurious_pair()
        pair = analyze_pair_cointegration("STAT_A.NS", "STAT_B.NS", _series(leg_a), _series(leg_b))
        with patch.object(coint, "stationarity_gate_of", lambda _pair: None):
            ungated = build_pair_signal(pair, family_alpha=0.05, comparisons_made=1)
        assert _names_an_action(ungated), ungated
        assert _ACTION_TOKENS[0] in ungated or _ACTION_TOKENS[1] in ungated

    async def test_the_scan_never_delivers_the_pair_as_a_directive(self):
        """End to end over the real route: the pair is delivered, counted, and
        published - as a rejection with its stationarity on the payload."""
        leg_a, leg_b = _spurious_pair()
        frames = {
            "STAT_A.NS": pd.DataFrame({"close": leg_a}, index=_series(leg_a).index),
            "STAT_B.NS": pd.DataFrame({"close": leg_b}, index=_series(leg_b).index),
        }
        payload = await _scan_payload("STAT_A.NS,STAT_B.NS", frames)
        row = payload["pairs"][0]
        assert row["is_cointegrated"] is True
        assert row["engle_granger_pvalue"] < 0.05
        assert _head(row["signal"]) == SIGNAL_SPURIOUS
        assert payload["directive_count"] == 0
        assert payload["directives"] == []

    def test_one_stationary_leg_is_enough(self):
        """The gate is not "both legs stationary". A single I(0) leg makes the
        pair's p-value a regression of stationarity on stationarity just as
        much, and a random walk traded against it is the same defect."""
        rng = np.random.default_rng(70000 + 853)
        walk = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.010, N)))
        still = _ar1(0.30, 1.2, 250.0, 80000 + 853)
        pair = analyze_pair_cointegration("WALK.NS", "STILL.NS", _series(walk), _series(still))
        assert pair.engle_granger_pvalue < 0.05
        assert pair.is_cointegrated is True
        assert pair.stationarity_leg_a["verdict"] == "i1"
        assert pair.stationarity_leg_b["verdict"] == "stationary"
        assert pair.stationarity_gate["verdict"] == STATIONARITY_GATE_SPURIOUS
        assert _head(pair.signal) == SIGNAL_SPURIOUS
        assert not _names_an_action(pair.signal)


# ---------------------------------------------------------------------------
# The lag rule is stated, and the reasons are attached
# ---------------------------------------------------------------------------


class TestTheLagRuleIsPublished:
    def test_both_legs_publish_the_rule_and_the_resolved_numbers(self):
        leg_a, leg_b = _spurious_pair()
        pair = analyze_pair_cointegration("STAT_A.NS", "STAT_B.NS", _series(leg_a), _series(leg_b))
        for leg in (pair.stationarity_leg_a, pair.stationarity_leg_b):
            rule = leg["lag_rule"]
            # The parameters, not a promise to choose some later.
            assert "max_lags=1" in rule
            assert "lag_selection=aic" in rule
            assert "trend=c" in rule
            assert "transform=log_price" in rule
            # And the number each test actually used, so the p-value is not a
            # bare number floating free of the specification behind it.
            assert leg["adf_lags"] in (0, 1)
            assert leg["kpss_bandwidth"] == kpss_bandwidth(N)
            assert leg["observations"] == N

    def test_kpss_bandwidth_is_the_newey_west_rule_not_archs_default(self):
        """`arch` would otherwise pick a data-dependent bandwidth and warn that
        it had changed. The rule is named, so the number in the payload is
        re-derivable from the observation count alone."""
        assert kpss_bandwidth(30) == 3
        assert kpss_bandwidth(107) == 4
        assert kpss_bandwidth(174) == 4
        # Never zero: a bandwidth of 0 leaves the long-run variance undefined.
        assert kpss_bandwidth(1) >= 1
        assert "newey_west" in STATIONARITY_KPSS_BANDWIDTH_RULE

    def test_the_adf_ceiling_is_not_archs_macro_default(self):
        """`arch`'s default is Schwert's ceil(12*(n/100)**0.25): 14 candidate
        lags at this scanner's real sample sizes, derived for MONTHLY macro
        series. The explicit ceiling is the choice, and it is published."""
        import math

        assert STATIONARITY_LAG_RULE.startswith("adf:max_lags=1,")
        assert math.ceil(12.0 * (174 / 100.0) ** 0.25) == 14


class TestUndeterminedIsNotStationary:
    def test_a_leg_below_the_floor_is_undetermined_with_a_reason(self):
        short = _ar1(0.3, 1.0, 100.0, 5, n=29)
        leg = assess_leg_stationarity(short, "SHORT.NS")
        assert leg["verdict"] == "undetermined"
        assert leg["adf_pvalue"] is None
        assert leg["kpss_pvalue"] is None
        assert "29" in leg["reason"] and "30" in leg["reason"]

    def test_a_non_positive_print_is_undetermined_not_dropped(self):
        """Dropping the bad rows would make the verdict about a DIFFERENT
        window than the cointegration test it is gating."""
        values = _ar1(0.3, 1.0, 100.0, 9)
        values[10] = 0.0
        leg = assess_leg_stationarity(values, "ZERO.NS")
        assert leg["verdict"] == "undetermined"
        assert leg["adf_pvalue"] is None
        assert "not strictly positive" in leg["reason"]

    def test_a_leg_arch_cannot_estimate_is_undetermined(self):
        """`arch` raises InfeasibleTestException on a locally constant leg
        rather than declining to answer. A raise is not a verdict."""
        leg = assess_leg_stationarity(np.full(N, 77.0), "FLAT.NS")
        assert leg["verdict"] == "undetermined"
        assert leg["adf_pvalue"] is None
        assert "could not be estimated" in leg["reason"]

    def test_tests_that_contradict_each_other_are_undetermined(self):
        """Each test is wrong in the opposite direction, so a leg where they
        disagree has no stationarity verdict - and must not be handed the one
        the louder test implies."""
        leg_a, leg_b = _spurious_pair()
        # phi=0.7 on a short window puts KPSS just under alpha while ADF is
        # emphatic; the disagreement is the answer, not a cointegration result.
        noisy = _ar1(0.7, 1.2, 100.0, 101)
        verdict = assess_leg_stationarity(noisy, "MIXED.NS")
        assert verdict["verdict"] in ("i1", "stationary", "undetermined")
        assert verdict["verdict"] == "undetermined", verdict
        assert "disagree" in verdict["reason"]
        assert leg_a is not None and leg_b is not None

    def test_an_unresolved_leg_withholds_under_its_own_head(self):
        """An absent measurement is not a stationary one - but it is also not a
        pass, and it must not be published as a spurious-regression FINDING."""
        pair = _pair(stationarity="i1_not_established_on_both_legs")
        signal = build_pair_signal(pair, comparisons_made=1)
        assert _head(signal) == SIGNAL_STATIONARITY_UNDETERMINED
        assert not _names_an_action(signal)
        assert "no direction is published" in signal


# ---------------------------------------------------------------------------
# No regression: a pair that passes the gate is untouched
# ---------------------------------------------------------------------------


def _pair(
    a: str = "AAA.NS",
    b: str = "BBB.NS",
    pvalue: float = 0.01,
    *,
    is_coint: bool = True,
    johansen: bool = True,
    beta: float = 1.0,
    zscore: Optional[float] = -2.0,
    stationarity: Optional[str] = STATIONARITY_GATE_PASSED,
) -> CointPairResult:
    verdicts = {
        STATIONARITY_GATE_PASSED: ("i1", "i1"),
        STATIONARITY_GATE_SPURIOUS: ("stationary", "i1"),
        STATIONARITY_GATE_UNRESOLVED: ("undetermined", "i1"),
    }[stationarity]
    leg = lambda t, v: {  # noqa: E731 - a fixture, not a measurement
        "ticker": t,
        "observations": N,
        "transform": "log_price",
        "alpha": 0.05,
        "lag_rule": STATIONARITY_LAG_RULE,
        "adf_pvalue": 0.61,
        "adf_lags": 0,
        "kpss_pvalue": 0.0001,
        "kpss_bandwidth": 4,
        "verdict": v,
        "reason": "fixture",
    }
    return CointPairResult(
        ticker_a=a,
        ticker_b=b,
        engle_granger_pvalue=pvalue,
        engle_granger_tstat=-3.5,
        is_cointegrated=is_coint,
        hedge_ratio_beta=beta,
        intercept_alpha=0.0,
        ou_half_life_days=10.0,
        ou_reversion_speed_theta=0.07,
        current_spread_zscore=zscore,
        hedge_ratio_beta_std_error=0.04,
        intercept_alpha_std_error=1.2,
        hedge_regression_observations=N,
        johansen_cointegrated=johansen,
        last_price_a=100.0,
        last_price_b=200.0,
        signal="NEUTRAL",
        decision_test="engle_granger",
        johansen_role="diagnostic_only",
        johansen_agrees_with_decision=johansen == is_coint,
        stationarity_leg_a=leg(a, verdicts[0]),
        stationarity_leg_b=leg(b, verdicts[1]),
        stationarity_gate={
            "verdict": stationarity,
            "leg_a_verdict": verdicts[0],
            "leg_b_verdict": verdicts[1],
            "reason": "fixture",
        },
    )


def _without_stationarity(pair: CointPairResult) -> CointPairResult:
    return pair.model_copy(
        update={
            "stationarity_leg_a": None,
            "stationarity_leg_b": None,
            "stationarity_gate": None,
        }
    )


class TestNoRegressionForAPairThatPasses:
    def test_a_genuine_pair_clears_the_gate(self):
        leg_a, leg_b = _genuine_pair()
        pair = analyze_pair_cointegration("AAA.NS", "BBB.NS", _series(leg_a), _series(leg_b))
        assert pair.stationarity_gate["verdict"] == STATIONARITY_GATE_PASSED
        assert pair.stationarity_leg_a["verdict"] == "i1"
        assert pair.stationarity_leg_b["verdict"] == "i1"

    def test_every_pre_existing_leaf_is_byte_identical(self):
        """The strongest form of the no-regression claim, and it holds for any
        series: measuring the legs perturbs nothing the scanner published
        before, because the tests are separate calls on the same array with no
        shared state."""
        leg_a, leg_b = _spurious_pair()
        measured = analyze_pair_cointegration("A.NS", "B.NS", _series(leg_a), _series(leg_b))
        # Same input, stationarity measurement suppressed entirely.
        with patch.object(coint, "assess_leg_stationarity", lambda *_a, **_k: {}):
            suppressed = analyze_pair_cointegration("A.NS", "B.NS", _series(leg_a), _series(leg_b))
        for name in _PRE_GATE_LEAVES:
            assert getattr(measured, name) == getattr(suppressed, name), name

    def test_a_passing_pair_publishes_a_byte_identical_signal(self):
        pair = _pair()
        # One test, so the Bonferroni threshold IS the alpha and this pair is
        # a real directive: the gate is a precondition, not a blanket refusal
        # to publish.
        gated = build_pair_signal(pair, family_alpha=0.05, comparisons_made=1)
        ungated = build_pair_signal(
            _without_stationarity(pair), family_alpha=0.05, comparisons_made=1
        )
        assert gated == ungated
        assert _names_an_action(gated)
        assert SIGNAL_SPURIOUS not in gated
        assert STATIONARITY_LAG_RULE not in gated

    @pytest.mark.parametrize("zscore", [-3.0, -1.5, 1.5, 3.0])
    @pytest.mark.parametrize("beta", [0.008606, 1.0, 33.6396])
    def test_a_passing_pair_is_unaffected_by_the_gate_on_every_other_rung(
        self, zscore, beta
    ):
        pair = _pair(beta=beta, zscore=zscore)
        bare = _without_stationarity(pair)
        for comparisons in (1, 91):
            assert build_pair_signal(pair, comparisons_made=comparisons) == build_pair_signal(
                bare, comparisons_made=comparisons
            )

    def test_the_family_arithmetic_is_untouched(self):
        """`multiplicity_report` reads the Engle-Granger p-value, which the gate
        does not touch, so the Bonferroni threshold, the survivor list and the
        BH count are the same numbers they were before."""
        rows = [
            _pair(a=f"T{i}.NS", b=f"U{i}.NS", pvalue=p, stationarity=STATIONARITY_GATE_PASSED)
            for i, p in enumerate([0.002, 0.03, 0.2, 0.9, 0.5, 0.04])
        ]
        report = coint.multiplicity_report(rows, family_alpha=0.05, comparisons_made=6)
        bare = coint.multiplicity_report(
            [_without_stationarity(r) for r in rows], family_alpha=0.05, comparisons_made=6
        )
        assert report == bare
        assert report["comparisons_made"] == 6
        assert report["corrected_threshold"] == pytest.approx(0.05 / 6)

    def test_apply_signal_directives_agrees_with_the_single_pair_string(self):
        """`scan_pairs` re-derives every signal, so the two must not disagree
        about a pair that fails the gate."""
        leg_a, leg_b = _spurious_pair()
        pair = analyze_pair_cointegration("A.NS", "B.NS", _series(leg_a), _series(leg_b))
        rederived = apply_signal_directives([pair], family_alpha=0.05, comparisons_made=1)[0]
        assert rederived.signal == build_pair_signal(pair, family_alpha=0.05, comparisons_made=1)
        assert _head(rederived.signal) == SIGNAL_SPURIOUS


# ---------------------------------------------------------------------------
# The cache must not launder the gate away
# ---------------------------------------------------------------------------


class TestCacheCannotServeAnUngatedRow:
    def test_a_row_without_the_gate_is_a_miss(self):
        assert CointegrationService._cached_pair_satisfies_contract(
            _without_stationarity(_pair()).model_dump()
        ) is False
        assert CointegrationService._cached_pair_satisfies_contract(
            _pair().model_dump()
        ) is True

    async def test_the_scan_recomputes_rather_than_serving_a_legacy_row(self):
        """A row written before the gate existed has no ADF or KPSS verdict.
        `build_pair_signal` reads an absent gate as "not recorded", so serving
        it would keep publishing spread directives with nothing behind them."""
        legacy = _without_stationarity(_pair(a="AAA.NS", b="BBB.NS", zscore=-2.0))
        assert legacy.stationarity_gate is None
        assert (
            CointegrationService._cached_pair_satisfies_contract(legacy.model_dump())
            is False
        )
        leg_a, leg_b = _genuine_pair()
        index = pd.bdate_range("2026-01-01", periods=N)
        frames = {
            "AAA.NS": pd.DataFrame({"close": leg_a}, index=index),
            "BBB.NS": pd.DataFrame({"close": leg_b}, index=index),
        }
        # Plant the legacy row in the in-memory cache the scan reads first.
        _IN_MEMORY_COINT_CACHE.clear()
        as_of = index[-1].strftime("%Y-%m-%d")
        _IN_MEMORY_COINT_CACHE[
            coint._mem_cache_key("AAA.NS", "BBB.NS", as_of, 0.05, False)
        ] = (coint._utcnow(), legacy.model_dump())
        try:
            payload = await _scan_payload("AAA.NS,BBB.NS", frames)
        finally:
            _IN_MEMORY_COINT_CACHE.clear()
        # Recomputed, so the delivered row carries a real measurement.
        gate = payload["pairs"][0]["stationarity_gate"]
        assert gate is not None
        assert gate["verdict"] in (
            STATIONARITY_GATE_PASSED,
            STATIONARITY_GATE_SPURIOUS,
            STATIONARITY_GATE_UNRESOLVED,
        )


# ---------------------------------------------------------------------------
# The route
# ---------------------------------------------------------------------------


class _FakeMarket:
    def __init__(self, frames):
        self.frames = dict(frames)

    async def fetch_historical_data(self, ticker, start, end):
        return self.frames.get(ticker, pd.DataFrame())


async def _scan_payload(tickers: str, frames: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    import json

    _IN_MEMORY_COINT_CACHE.clear()
    try:
        with patch.object(analytics_mod, "CointegrationService", CointegrationService):
            response = await get_cointegration_pairs(
                tickers=tickers,
                lookback_days=252,
                p_value_threshold=0.05,
                max_half_life=None,
                include_spread_series=False,
                db=Mock(),
                data_service=_FakeMarket(frames),
                cache_service=None,
            )
        return json.loads(response.model_dump_json())
    finally:
        _IN_MEMORY_COINT_CACHE.clear()


class TestThePayloadCarriesTheGate:
    async def test_every_delivered_row_carries_both_leg_verdicts(self):
        leg_a, leg_b = _spurious_pair()
        frames = {
            "STAT_A.NS": pd.DataFrame({"close": leg_a}, index=_series(leg_a).index),
            "STAT_B.NS": pd.DataFrame({"close": leg_b}, index=_series(leg_b).index),
        }
        payload = await _scan_payload("STAT_A.NS,STAT_B.NS", frames)
        row = payload["pairs"][0]
        # The four keys the brief names, on both legs, on the wire.
        for key in ("stationarity_leg_a", "stationarity_leg_b"):
            leg = row[key]
            assert leg["adf_pvalue"] is not None
            assert leg["kpss_pvalue"] is not None
            assert leg["lag_rule"] == STATIONARITY_LAG_RULE
            assert leg["verdict"] in ("i1", "stationary", "undetermined")
            assert leg["reason"]
        assert row["stationarity_gate"]["verdict"] == STATIONARITY_GATE_SPURIOUS
        assert row["stationarity_gate"]["reason"]

    async def test_a_negative_pair_still_publishes_its_legs(self):
        """The measurement runs whatever Engle-Granger said, so a reader is
        never left assuming a negative pair's legs were checked when they
        were not."""
        leg_a, leg_b = _genuine_pair(seed=3)
        frames = {
            "AAA.NS": pd.DataFrame({"close": leg_a}, index=_series(leg_a).index),
            "BBB.NS": pd.DataFrame({"close": leg_b}, index=_series(leg_b).index),
        }
        payload = await _scan_payload("AAA.NS,BBB.NS", frames)
        row = payload["pairs"][0]
        assert row["is_cointegrated"] is False
        assert row["signal"] == "NOT_COINTEGRATED"
        assert row["stationarity_leg_a"]["verdict"] is not None
        assert row["stationarity_leg_b"]["verdict"] is not None

    def test_the_new_schema_fields_are_all_optional(self):
        """`CointPairResult(**cached_row)` must keep working for a row written
        by an older build; every field added here is `Optional[...] = None`."""
        for name in (
            "stationarity_leg_a",
            "stationarity_leg_b",
            "stationarity_gate",
        ):
            assert CointPairResult.model_fields[name].default is None, name

    def test_assess_pair_stationarity_never_invents_a_verdict(self):
        assert assess_pair_stationarity({}, {})["verdict"] == STATIONARITY_GATE_UNRESOLVED
        assert (
            assess_pair_stationarity({"verdict": "i1"}, {"verdict": "stationary"})["verdict"]
            == STATIONARITY_GATE_SPURIOUS
        )
        assert (
            assess_pair_stationarity({"verdict": "i1"}, {"verdict": "i1"})["verdict"]
            == STATIONARITY_GATE_PASSED
        )
