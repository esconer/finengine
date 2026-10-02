"""QM-4: a verdict the test itself declines to stand behind was published as one.

`statsmodels.tsa.stattools.coint` does not raise on collinear legs. It warns
and returns, on the SAME branch:

    if res_co.rsquared < 1 - 100 * SQRTEPS:
        res_adf = adfuller(...)
    else:
        warnings.warn("y0 and y1 are (almost) perfectly colinear."
                      "Cointegration test is not reliable in this case.",
                      CollinearityWarning)
        res_adf = (-np.inf,)          # <- hardcoded, by construction

so the warning and a non-finite t-statistic are not two symptoms of one
condition - they are one condition, read off two different channels. `p` is
then `cdf(-inf)` = 0.0, which is the strongest possible reading of "strongly
cointegrated" and the exact opposite of the truth: the regression residual is
identically zero, so there is no sampling distribution to compare against and
the test has no answer.

`analyze_pair_cointegration` guarded that call with `except Exception`, which
a warning can never reach, so the pair was published as cointegrated on a
statistic its own author called unreliable. Two defects, one root cause - a
degenerate input was accepted and published rather than refused:

  1. the VERDICT. `bool(0.0 < 0.05)` is True, so `is_cointegrated=True` and
     the pair entered the scan carrying a p-value that reads as evidence;
  2. the PAYLOAD. `engle_granger_tstat` was `-inf`, and a bare `-Infinity` is
     not valid JSON (RFC 8259), so one pair's statistic could take down a
     strict parser for the whole response rather than one field.

The rule this file pins is the module's own: *a refusal is a valid answer; a
fabricated number is the defect.* So the statistic is refused, never repaired -
not clipped to a large finite number, not rounded to 0.0, and the
`CollinearityWarning` is NOT suppressed: it still reaches the caller, because a
warning that nobody can see is how this hid the first time.

`CointPairResult.is_cointegrated` is a required `bool`, so a pair with no valid
verdict has no representable payload at all: the refusal is therefore the
module's existing `None` return - the same one `MIN_PAIR_OBSERVATIONS` uses -
rather than a new signal head. Nothing is said about the pair, which is the
strongest form of "this cannot be read as a data conclusion".

Nothing else moves. A non-degenerate pair keeps every published figure,
byte-identical.

No DB, no network.
"""

import json
import warnings

import numpy as np
import pandas as pd
import pytest
from statsmodels.tools.sm_exceptions import CollinearityWarning
from statsmodels.tsa.stattools import coint

from app.services.cointegration_service import (
    MIN_PAIR_OBSERVATIONS,
    CointegrationService,
    analyze_pair_cointegration,
)

N = 174


def _walk(prices: np.ndarray) -> pd.Series:
    return pd.Series(prices, index=pd.bdate_range("2026-01-01", periods=len(prices)))


def _random_walk(seed: int, n: int = N) -> np.ndarray:
    """An I(1)-shaped leg: a random walk on price."""
    rng = np.random.default_rng(seed)
    return 100.0 + np.cumsum(rng.normal(0.0, 1.0, n))


def _cointegrated_pair(seed: int = 2, n: int = N) -> tuple:
    """Two I(1) legs with a real, non-degenerate shared relationship.

    `leg_b = 1.4 * leg_a + iid noise`: the residual is genuinely stochastic, so
    the regression R-squared sits clear of the `1 - 100 * SQRTEPS` boundary,
    Engle-Granger has a sampling distribution to work with, and `statsmodels`
    does not warn. This is the pair the guard must leave alone. Seed 2 is the
    one used because it exercises every published float, OU parameters
    included, rather than the None cases several other seeds land on.
    """
    rng = np.random.default_rng(seed)
    leg_a = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.011, n)))
    leg_b = 1.4 * leg_a + rng.normal(0.0, 0.30, n) + 8.0
    return leg_a, leg_b


def _strictly_serializable(payload: dict) -> None:
    """Assert the payload is valid JSON under RFC 8259.

    `allow_nan=False` is the assertion mechanism, not a helper: `json.dumps`
    emits bare `NaN` / `Infinity` / `-Infinity` by default and raises only when
    told not to. Both are rejected by a strict parser (`JSON.parse` throws,
    taking the whole response down rather than one field), so raising here is
    exactly the failure the brief describes.
    """
    json.dumps(payload, allow_nan=False)


# ---------------------------------------------------------------------------
# The premise: what statsmodels actually does on collinear legs
# ---------------------------------------------------------------------------


class TestCollinearInputIsThePremise:
    def test_coint_warns_and_returns_minus_infinity(self):
        """Fix the premise. The warning and the non-finite statistic are the
        same branch of `coint` (`res_adf = (-np.inf,)` is hardcoded on it), so
        if either stopped holding the guard below would be testing for
        something the library no longer does."""
        leg = _random_walk(3)

        with pytest.warns(CollinearityWarning):
            t_stat, p_value, _ = coint((2.5 * leg).astype(float), leg.astype(float))

        assert not np.isfinite(t_stat), (
            "coint is expected to return a non-finite t-statistic on collinear "
            "legs; if it now returns a finite one, the guard under test is "
            "chasing a condition this statsmodels build no longer produces"
        )
        assert p_value == 0.0, (
            "coint is expected to report p=0.0 alongside the non-finite "
            "statistic - this is the value that reads as decisive evidence"
        )

    def test_the_warning_is_not_an_exception(self):
        """The reason `except Exception` at the call site could never catch it."""
        leg = _random_walk(3)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", CollinearityWarning)
            coint((2.5 * leg).astype(float), leg.astype(float))  # must not raise


# ---------------------------------------------------------------------------
# The refusal: a degenerate pair is refused, not repaired
# ---------------------------------------------------------------------------


class TestCollinearPairIsRefused:
    @pytest.mark.parametrize(
        "name, build_legs",
        [
            ("exactly collinear (y = 2.5x)", lambda x: (2.5 * x, x)),
            ("exactly collinear (y = x)", lambda x: (x, x)),
            ("exactly collinear through zero (y = 0*x)", lambda x: (0.0 * x, x)),
            ("almost collinear (y = 2.5x + 1e-13 noise)", lambda x: (2.5 * x + 1e-13, x)),
        ],
    )
    def test_collinear_legs_produce_no_pair(self, name, build_legs):
        leg_a, leg_b = build_legs(_random_walk(3))
        assert len(leg_a) >= MIN_PAIR_OBSERVATIONS, "the premise needs enough history"

        assert analyze_pair_cointegration(
            "COL_A.NS", "COL_B.NS", _walk(leg_a), _walk(leg_b)
        ) is None, (
            f"{name}: a pair whose Engle-Granger statistic is not a number "
            "must not be published at all. Publishing it means shipping a "
            "verdict built on a statistic statsmodels says is not reliable."
        )

    def test_no_repaired_statistic_is_published_instead(self):
        """Refused, not repaired.

        The tempting repairs are all fabrications: clipping `-inf` to a large
        finite number publishes a t-statistic the test never computed, and
        writing `0.0` publishes a finite one that reads as an ordinary
        measured result. There is no payload to inspect, which is the point -
        so this pins the ABSENCE of a row rather than the content of one.
        """
        leg = _random_walk(3)
        pair = analyze_pair_cointegration(
            "COL_A.NS", "COL_B.NS", _walk(2.5 * leg), _walk(leg)
        )
        assert pair is None, "expected a refusal, not a repaired statistic"


# ---------------------------------------------------------------------------
# The second defect: nothing non-finite reaches the wire
# ---------------------------------------------------------------------------


class TestNothingNonFiniteIsPublished:
    def test_the_assertion_mechanism_actually_bites(self):
        """Guard the guard.

        `json.dumps` emits bare `NaN` / `Infinity` by DEFAULT and only refuses
        when told to, so a broken helper here would make every serialization
        assertion in this file pass vacuously. This proves it is not broken.
        """
        assert json.dumps({"x": float("-inf")}) == '{"x": -Infinity}'
        with pytest.raises(ValueError):
            _strictly_serializable({"x": float("-inf")})
        with pytest.raises(ValueError):
            _strictly_serializable({"x": float("nan")})

    def test_it_bites_inside_nested_structures_too(self):
        """The payload nests dicts (`stationarity_leg_a`) and lists
        (`spread_series`), so a top-level check would pass while the figure
        that actually reaches the wire is the degenerate one."""
        with pytest.raises(ValueError):
            _strictly_serializable({"spread_series": [{"date": "2026-01-01", "zscore": float("inf")}]})
        with pytest.raises(ValueError):
            _strictly_serializable({"stationarity_gate": {"leg": {"adf_pvalue": float("nan")}}})

    @pytest.mark.parametrize("include_spread_series", [False, True])
    def test_published_payload_is_strictly_serializable(self, include_spread_series):
        """`json.dumps(..., allow_nan=False)` raises on both NaN and inf.

        The default `json.dumps` happily emits bare `-Infinity`, which RFC 8259
        does not allow, so `JSON.parse` throws and the whole response dies
        rather than one field.
        """
        leg = _random_walk(3)
        pair = analyze_pair_cointegration(
            "COL_A.NS",
            "COL_B.NS",
            _walk(2.5 * leg),
            _walk(leg),
            include_spread_series=include_spread_series,
        )
        assert pair is None, "expected a refusal before the payload is even built"

    def test_no_collinear_or_constant_input_reaches_a_non_finite_field(self):
        """Every degenerate shape this path can be handed.

        The `allow_nan=False` dump is the assertion: it walks the WHOLE payload,
        including the nested per-leg stationarity records and `spread_series`,
        which a top-level field check would miss.
        """
        leg = _random_walk(3)
        cases = {
            "collinear y = 2.5x": (2.5 * leg, leg),
            "collinear y = x": (leg, leg),
            "constant leg A": (np.full(N, 100.0), leg),
            "both constant": (np.full(N, 100.0), np.full(N, 50.0)),
        }
        for name, (leg_a, leg_b) in cases.items():
            pair = analyze_pair_cointegration(
                "BAD_A.NS", "BAD_B.NS", _walk(leg_a), _walk(leg_b),
                include_spread_series=True,
            )
            # The invariant is about the WIRE, not about which of these happen
            # to be refused: nothing this path can be handed may produce a
            # payload a strict JSON parser rejects. A degenerate input that is
            # refused trivially satisfies it; one that yields an ordinary finite
            # measurement (a constant leg is NOT degenerate - `coint` returns a
            # perfectly finite p=0.98 for it, which is a real answer about a
            # flat series, not a fabrication) has to survive the dump.
            if pair is not None:
                _strictly_serializable(pair.model_dump())

    def test_the_collinear_cases_are_the_ones_refused(self):
        """Pin which of those inputs are refused, so the invariant above cannot
        be satisfied by refusing everything.

        A constant leg is published: `coint` measures it (p ~ 0.98) and refuses
        to invent a problem with it. A collinear pair is refused, because
        `coint` disowns its own statistic there.
        """
        leg = _random_walk(3)
        assert analyze_pair_cointegration(
            "C_A.NS", "C_B.NS", _walk(2.5 * leg), _walk(leg)
        ) is None
        constant_pair = analyze_pair_cointegration(
            "C_A.NS", "C_B.NS", _walk(np.full(N, 100.0)), _walk(leg)
        )
        assert constant_pair is not None, (
            "a constant leg yields a finite, ordinary Engle-Granger result; "
            "refusing it would be refusing a real measurement"
        )
        assert constant_pair.is_cointegrated is False

    def test_a_healthy_pair_serializes_strictly_too(self):
        """The guard must not become a licence to publish junk."""
        leg_a, leg_b = _cointegrated_pair(seed=2)
        pair = analyze_pair_cointegration(
            "OK_A.NS", "OK_B.NS", _walk(leg_a), _walk(leg_b), include_spread_series=True
        )
        assert pair is not None
        _strictly_serializable(pair.model_dump())


# ---------------------------------------------------------------------------
# The warning is not silenced
# ---------------------------------------------------------------------------


class TestTheWarningIsNotSuppressed:
    def test_a_refused_collinear_pair_still_raises_the_collinearity_warning(self):
        """Detect the condition; do not hide it.

        Silencing the warning would let this regress unnoticed: the refusal
        would still be correct, but nothing would ever say WHY a perfectly
        ordinary-looking pair vanished from the scan.
        """
        leg = _random_walk(3)
        with pytest.warns(CollinearityWarning):
            analyze_pair_cointegration("COL_A.NS", "COL_B.NS", _walk(2.5 * leg), _walk(leg))


# ---------------------------------------------------------------------------
# Nothing else moves
# ---------------------------------------------------------------------------


class TestNonDegeneratePairsAreUntouched:
    def test_every_published_figure_is_unchanged_for_a_real_pair(self):
        """The guard must fire only on degenerate input.

        These are the exact values the payload carries today, and they are
        asserted rather than recomputed so that a change to the published
        numbers fails here instead of passing for a reason that has nothing to
        do with the guard. Seed 2 of the fixture, which exercises every
        published float including the OU parameters.
        """
        leg_a, leg_b = _cointegrated_pair(seed=2)
        pair = analyze_pair_cointegration(
            "OK_A.NS", "OK_B.NS", _walk(leg_a), _walk(leg_b), include_spread_series=True
        )

        assert pair is not None
        assert pair.is_cointegrated is True, "the premise: a real pair is still found"
        assert pair.engle_granger_tstat == -12.651
        assert pair.engle_granger_pvalue == 0.0
        assert pair.hedge_ratio_beta == pytest.approx(0.714799, abs=1e-6)
        assert pair.intercept_alpha == pytest.approx(-5.7785, abs=1e-4)
        assert pair.current_spread_zscore == pytest.approx(-0.4904, abs=1e-4)
        assert pair.ou_reversion_speed_theta == pytest.approx(3.262635, abs=1e-6)
        assert pair.ou_half_life_days == pytest.approx(0.21, abs=1e-9)
        assert pair.johansen_cointegrated is True
        assert pair.johansen_agrees_with_decision is True
        assert pair.overlap_observations == N
        assert pair.last_price_a == round(float(leg_a[-1]), 2)
        assert pair.last_price_b == round(float(leg_b[-1]), 2)
        assert len(pair.spread_series) == N

    def test_a_non_cointegrated_pair_is_still_published(self):
        """The refusal must not swallow ordinary negatives.

        Two independent random walks are a legitimate `NOT_COINTEGRATED` result
        and must still reach the reader; only the degenerate input is refused.
        """
        pair = analyze_pair_cointegration(
            "IND_A.NS",
            "IND_B.NS",
            _walk(_random_walk(11)),
            _walk(_random_walk(22)),
        )
        assert pair is not None, "an ordinary negative pair must still be published"
        assert pair.is_cointegrated is False
        _strictly_serializable(pair.model_dump())


# ---------------------------------------------------------------------------
# The refusal must not loosen anything else
# ---------------------------------------------------------------------------


class TestTheRefusalDoesNotLoosenTheFamilyCorrection:
    """A refused pair disappears from the rows but must stay in the FAMILY.

    `scan_pairs` increments `scanned_count` per COMBINATION, before any
    analysis, and that count is what the Bonferroni correction is computed
    over. If a refused pair were also dropped from the count, every remaining
    pair would get a laxer corrected threshold - a refactor of one defect into
    a silent loosening of another. It is not dropped, and this pins that.
    """

    @pytest.mark.asyncio
    async def test_a_refused_pair_is_still_counted_in_the_family(self):
        # Seed 7 rather than 2: it is the fixture whose spread z-score sits past
        # the directive threshold, so the surviving pair's signal string quotes
        # the corrected threshold it was allowed by, and the family size is
        # visible in the published payload instead of only in a counter.
        leg_a, leg_b = _cointegrated_pair(seed=7)
        leg_c = 2.5 * leg_a  # exactly collinear with A

        service = CointegrationService()
        response = await service.scan_pairs(
            price_data={
                "A.NS": _walk(leg_a),
                "B.NS": _walk(leg_b),
                "C.NS": _walk(leg_c),
            },
            p_value_threshold=0.05,
            max_half_life=None,
        )

        # Three combinations scanned, three tests in the family, but only two
        # rows out: the refused pair is absent from the rows and PRESENT in the
        # family. Those two facts together are the invariant.
        assert response.scanned_pairs_count == 3
        assert response.analyzed_pairs_count == 3
        assert response.returned_pairs_count == 2

        published = {(p.ticker_a, p.ticker_b) for p in response.pairs}
        assert ("A.NS", "C.NS") not in published, (
            "the collinear pair must not be published"
        )
        assert ("A.NS", "B.NS") in published, (
            "the genuine pair must still be published"
        )

        # The decisive assertion: the correction is still over all THREE tests,
        # not the two that survived. `alpha / 3`, not `alpha / 2`.
        genuine = next(p for p in response.pairs if p.ticker_a == "A.NS")
        assert "0.05/3" in genuine.signal, (
            f"expected the family correction to remain alpha/3; got: "
            f"{genuine.signal!r}"
        )

        # And nothing in the whole response is unparseable.
        _strictly_serializable(response.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# The cache must not launder a row written before the guard existed
# ---------------------------------------------------------------------------


class TestACachedRowFromBeforeTheGuardIsNotServed:
    def test_a_row_carrying_a_non_finite_statistic_is_a_cache_miss(self):
        """A build before the guard wrote exactly this row.

        Before the refusal, a collinear pair was cached with
        `engle_granger_tstat = -inf` and `is_cointegrated = True`. Serving it
        would republish the exact verdict the guard exists to stop, for up to
        `CACHE_TTL_HOURS` in memory and until `last_date` rolls over in the DB.
        """
        stale_row = {
            "ticker_a": "COL_A.NS",
            "ticker_b": "COL_B.NS",
            "engle_granger_pvalue": 0.0,
            "engle_granger_tstat": float("-inf"),
            "is_cointegrated": True,
            "hedge_ratio_beta": 2.5,
            "intercept_alpha": 0.0,
            "hedge_ratio_beta_std_error": 0.01,
            "intercept_alpha_std_error": 0.02,
            "hedge_regression_observations": N,
            "hedge_regression_std_error_basis": "ols_standard_error_from_polyfit_covariance_df_n_minus_2",
            "johansen_cointegrated": None,
            "last_price_a": 250.0,
            "last_price_b": 100.0,
            "signal": "NEUTRAL",
            "stationarity_gate": {"verdict": "both_legs_i1"},
            "stationarity_leg_a": {"verdict": "i1"},
            "stationarity_leg_b": {"verdict": "i1"},
        }

        assert CointegrationService._cached_pair_satisfies_contract(stale_row) is False

    def test_a_finite_row_of_the_same_shape_is_still_served(self):
        """Same row, one field repaired - it must pass.

        Without this the gate could be made to pass by refusing everything,
        which is a different defect and would look like a pass here.
        """
        healthy = {
            "ticker_a": "OK_A.NS",
            "ticker_b": "OK_B.NS",
            "engle_granger_pvalue": 0.0,
            "engle_granger_tstat": -7.1,
            "is_cointegrated": True,
            "hedge_ratio_beta": 1.4,
            "intercept_alpha": 8.0,
            "hedge_ratio_beta_std_error": 0.01,
            "intercept_alpha_std_error": 0.02,
            "hedge_regression_observations": N,
            "hedge_regression_std_error_basis": "ols_standard_error_from_polyfit_covariance_df_n_minus_2",
            "johansen_cointegrated": True,
            "last_price_a": 250.0,
            "last_price_b": 100.0,
            "signal": "NEUTRAL",
            "stationarity_gate": {"verdict": "both_legs_i1"},
            "stationarity_leg_a": {"verdict": "i1"},
            "stationarity_leg_b": {"verdict": "i1"},
        }

        assert CointegrationService._cached_pair_satisfies_contract(healthy) is True
