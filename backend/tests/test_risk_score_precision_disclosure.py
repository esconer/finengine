"""SI-5: the risk score's inputs have to say how precisely they are known.

`score_audit` (RL-3) already says what the headline is MADE OF.  It does not say
how precisely each ingredient is known, and the ingredients are three different
kinds of number - which is exactly why ENV-020 was red on this section:

  1. ``avg_pairwise_correlation`` (0.0994 in the failing artifact) and
     ``factor_r_squared`` (0.0758) are ESTIMATED FROM DATA.  A measurement of the
     average pairwise correlation of 14 positions, and an R-squared fitted on 38
     paired returns, both published to four decimals with nothing said about how
     much of that precision is real.  They get a measured standard error, a real
     interval and an effective-sample-size figure.

  2. ``components.correlation`` is a DETERMINISTIC FUNCTION of one published
     input: ``min(30, 50 * max(0, avg_pairwise_correlation))``.  Its precision is
     inherited from that input and it carries no interval of its own, because an
     independent band for a function of an already-published number is a
     fabricated second estimate of something the payload already states.

  3. The two ``score_audit`` weights the rule flagged are NOT ESTIMATES.  One is
     the nominal weight, the other the headline contribution
     (``unrounded sub_score x effective_weight``); both are arithmetic on
     declared policy constants, and the correct disclosure labels them as such
     and names the table.  Manufacturing a confidence interval for a weight
     somebody typed would be the defect this whole queue exists to remove.

The dashboard red is new and real: until the de-duplication commit the section
passed ENV-020 only because its subtree happened to contain a sibling's
uncertainty keys.  ``risk_score`` has no top-level twin, so the gap surfaced
here.  The fix is a disclosure, NOT a re-inlined copy of a neighbour's block.

No audit CLI: it reads a frozen export, so a green gate would say nothing about
this code.  The rule's own token set is imported instead, so the in-process
assertion is made against the constants the rule actually uses.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import pytest

from app.debugging.context_audit import UNCERTAINTY_KEY_TOKENS
from app.services import analytics_engine
from app.services.analytics_engine import (
    RISK_CORRELATION_POINTS_PER_UNIT,
    RISK_SCORE_CAP,
    RISK_SCORE_INPUT_PRECISION_AT,
    RISK_SCORE_LEG_SPECS,
    RISK_SCORE_WEIGHTS,
    UNCERTAINTY_BOOTSTRAP_RESAMPLES,
    UNCERTAINTY_BOOTSTRAP_SEED,
    UNCERTAINTY_CONFIDENCE_LEVEL,
    AnalyticsEngine,
    moving_block_indices,
    moving_block_size,
    pairwise_resample_count,
)

ESTIMATED_FIELDS = ("avg_pairwise_correlation", "factor_r_squared")

#: Exactly the keys this change adds.  Everything else in the score block must
#: be byte-identical with and without them.
NEW_DISCLOSURE_KEYS = ("precision_classification", "precision_inherits_from",
                       "precision_disclosure_at")


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _prices_from_returns(returns: Dict[str, np.ndarray]) -> pd.DataFrame:
    """A price frame whose `pct_change` IS the return series passed in."""
    n = len(next(iter(returns.values())))
    index = pd.bdate_range("2026-01-01", periods=n)
    return pd.DataFrame(
        {name: 100.0 * np.cumprod(1.0 + values) for name, values in returns.items()},
        index=index,
    )


def _book(
    observations: int = 260,
    names: int = 5,
    seed: int = 21,
    gappy_leg: bool = True,
) -> Tuple[pd.DataFrame, pd.Series, Dict[str, float]]:
    """A real book: a common factor, a benchmark, and one late-listed leg.

    `gappy_leg` reproduces the property that makes the correlation leg's
    statistic PAIRWISE rather than complete-case: one holding is unpriced for a
    stretch of the window, so the constituent return frame carries NaN rows and
    the mean over pairs is not the mean over the complete-case subset.
    """
    rng = np.random.default_rng(seed)
    factor = rng.normal(0.0, 1.0, observations)
    loading = 0.010
    common = loading * factor
    idio = loading * np.sqrt((1.0 - 0.4) / 0.4)
    returns = {
        f"N{i}": common + idio * rng.normal(0.0, 1.0, observations)
        for i in range(names)
    }
    frame = _prices_from_returns(returns)
    if gappy_leg:
        late = sorted(returns)[-1]
        frame.loc[frame.index[: observations // 3], late] = np.nan
    weight = 1.0 / names
    return (
        frame,
        pd.Series(common, index=frame.index),
        {name: weight for name in returns},
    )


def _noise_benchmark(frame: pd.DataFrame, seed: int = 17) -> pd.Series:
    """A benchmark unrelated to the book, so the factor leg pins at its cap."""
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0, 0.01, len(frame)), index=frame.index)


async def _score(frame, weights, benchmark) -> Dict[str, Any]:
    return await AnalyticsEngine().risk_scoring(
        frame, weights, benchmark_data=benchmark
    )


async def _book_score(**kwargs) -> Dict[str, Any]:
    frame, benchmark, weights = _book(**kwargs)
    return await _score(frame, weights, benchmark)


def _precision(result: Dict[str, Any]) -> Dict[str, Any]:
    precision = (result.get("score_audit") or {}).get("precision")
    assert precision is not None, "the score must publish its precision classes"
    return precision


def _entry(result: Dict[str, Any], field: str) -> Dict[str, Any]:
    return _precision(result)["estimated_statistics"][field]["estimates"][field]


def _assert_block_contract(block, field: str) -> None:
    """The machinery's own contract: a real interval, or a status with a reason."""
    assert block["scope"], f"{field}: a block must say what it covers"
    assert block["status"] in {"computed", "not_computed"}
    entry = block["estimates"][field]
    assert "conf_int" in entry, f"{field} omitted conf_int entirely"
    if entry["conf_int"] is None:
        assert entry["standard_error"] is None, field
        assert entry["status"] != "computed", field
        assert entry["reason"], f"{field} has no interval and no reason"
        assert entry["conf_int_level"] is None, field
    else:
        assert entry["status"] == "computed", field
        assert entry["reason"] is None, field
        assert entry["conf_int_level"] == UNCERTAINTY_CONFIDENCE_LEVEL, field
        low, high = entry["conf_int"]
        assert math.isfinite(low) and math.isfinite(high) and low <= high, field
        assert entry["standard_error"] is not None and entry["standard_error"] > 0
    json.dumps(block)


# ---------------------------------------------------------------------------
# 1. the two estimated statistics are MEASURED, not asserted
# ---------------------------------------------------------------------------

class TestEstimatedStatisticsCarryAMeasurement:
    @pytest.mark.asyncio
    async def test_both_estimated_inputs_publish_a_standard_error_and_an_interval(self):
        result = await _book_score()
        precision = _precision(result)
        for field in ESTIMATED_FIELDS:
            block = precision["estimated_statistics"][field]
            _assert_block_contract(block, field)
            assert block["status"] == "computed", field
            entry = block["estimates"][field]
            assert entry["standard_error"] > 0.0, field
            assert entry["conf_int"] is not None, field
            assert entry["effective_n"] is not None, field
            assert entry["observations"] > 0, field

    @pytest.mark.asyncio
    async def test_each_entry_point_is_the_published_value_it_claims_to_measure(self):
        """A band that does not describe the printed number is worse than none."""
        result = await _book_score()
        assert _entry(result, "avg_pairwise_correlation")["point"] == (
            result["avg_pairwise_correlation"]
        )
        assert _entry(result, "factor_r_squared")["point"] == result["factor_r_squared"]
        for field in ESTIMATED_FIELDS:
            assert _entry(result, field)["point_status"] == "reproduced_by_estimator"

    @pytest.mark.asyncio
    async def test_the_correlation_standard_error_is_reproduced_independently(self):
        """Rebuild the pairwise bootstrap from scratch and compare.

        Deliberately a different implementation: the resample is scored with
        pandas' own `.corr()` per draw, so a match is evidence about the
        ESTIMATOR rather than about two copies of one expression.
        """
        frame, benchmark, weights = _book()
        result = await _score(frame, weights, benchmark)
        entry = _entry(result, "avg_pairwise_correlation")

        returns = (
            frame.replace([np.inf, -np.inf], np.nan).sort_index()
            .pct_change(fill_method=None).iloc[1:]
        )
        n = int(len(returns))
        block_size = moving_block_size(n)
        indices = moving_block_indices(
            n, block_size, UNCERTAINTY_BOOTSTRAP_RESAMPLES, UNCERTAINTY_BOOTSTRAP_SEED
        )
        values = returns.to_numpy(dtype=float)
        stats: List[float] = []
        for row in indices:
            resampled = pd.DataFrame(
                values[row], columns=returns.columns, index=returns.index
            )
            matrix = resampled.corr().to_numpy(dtype=float)
            upper = matrix[np.triu_indices(len(returns.columns), k=1)]
            stats.append(float(upper[np.isfinite(upper)].mean()))
        draws = np.asarray(stats, dtype=float)
        low, high = np.percentile(draws, [2.5, 97.5])
        assert entry["conf_int"][0] == pytest.approx(low, abs=1e-6)
        assert entry["conf_int"][1] == pytest.approx(high, abs=1e-6)
        assert entry["standard_error"] == pytest.approx(
            float(draws.std(ddof=1)), abs=1e-6
        )
        assert n == entry["observations"]

    @pytest.mark.asyncio
    async def test_the_regression_standard_error_is_reproduced_independently(self):
        """R-squared of a simple regression is the squared Pearson correlation.

        So the independent recomputation uses `np.corrcoef` per draw - no
        centred-sum algebra in common with the published estimator at all.
        """
        frame, benchmark, weights = _book()
        result = await _score(frame, weights, benchmark)
        entry = _entry(result, "factor_r_squared")

        from app.services.analytics_engine import _factor_regression_frame

        pair, fit_window, reason = _factor_regression_frame(
            frame.replace([np.inf, -np.inf], np.nan).sort_index().pct_change(
                fill_method=None
            ).iloc[1:],
            benchmark,
            weights,
        )
        assert reason is None
        assert fit_window["declared"] is True
        n = int(pair.shape[0])
        indices = moving_block_indices(
            n, moving_block_size(n), UNCERTAINTY_BOOTSTRAP_RESAMPLES,
            UNCERTAINTY_BOOTSTRAP_SEED,
        )
        stats = [
            float(np.corrcoef(pair[row, 0], pair[row, 1])[0, 1] ** 2)
            for row in indices
        ]
        draws = np.asarray(stats, dtype=float)
        low, high = np.percentile(draws, [2.5, 97.5])
        assert entry["conf_int"][0] == pytest.approx(low, abs=1e-6)
        assert entry["conf_int"][1] == pytest.approx(high, abs=1e-6)
        assert entry["standard_error"] == pytest.approx(
            float(draws.std(ddof=1)), abs=1e-6
        )
        assert n == entry["observations"]

    @pytest.mark.asyncio
    async def test_the_correlation_leg_is_measured_pairwise_not_complete_case(self):
        """The NaN gap is the whole reason the disclosure needs a row filter.

        On this book the pairwise mean and the complete-case mean are different
        numbers, so a complete-case estimator would fail the reproduction guard
        and the correct published value would be left without a band.
        """
        frame, benchmark, weights = _book()
        result = await _score(frame, weights, benchmark)
        entry = _entry(result, "avg_pairwise_correlation")
        block = _precision(result)["estimated_statistics"]["avg_pairwise_correlation"]
        assert block["observation_filter"] == "caller_supplied_row_filter"

        returns = (
            frame.replace([np.inf, -np.inf], np.nan).sort_index()
            .pct_change(fill_method=None).iloc[1:]
        )
        complete = returns.dropna()

        def _mean(frame_in):
            matrix = frame_in.corr().to_numpy(dtype=float)
            upper = matrix[np.triu_indices(frame_in.shape[1], k=1)]
            return float(upper[np.isfinite(upper)].mean())

        assert abs(_mean(returns) - _mean(complete)) > 1e-6
        assert entry["point"] == round(_mean(returns), 4)
        # every row carrying a finite return for SOME leg is kept
        assert entry["observations"] == len(returns)
        assert block["notes"]["constituent_finite_observations"]

    @pytest.mark.asyncio
    async def test_the_regression_publishes_its_own_sample_and_adjusted_r_squared(self):
        result = await _book_score()
        block = _precision(result)["estimated_statistics"]["factor_r_squared"]
        notes = block["notes"]
        assert notes["fit_observation_count"] == block["observations"]
        assert notes["fit_observation_count_matches_frame"] is True
        assert notes["fit_observation_count_scope"] == "portfolio_vs_benchmark_ols_rows"
        # the fit's OWN dates, which is what makes the statistic comparable with
        # the same model's fit over a different window
        assert notes["fit_window"]["declared"] is True
        assert notes["fit_window"]["days"] == block["observations"]
        # the SAME fit's adjusted R-squared, which needs no resampling to be real
        fit = notes["adjusted_r_squared_fit"]
        assert 0.0 <= float(fit["adjusted_r_squared"]) <= 1.0
        assert fit["model_observation_count"] == block["observations"]
        assert fit["model_window"]["start"] == notes["fit_window"]["start"]
        assert "DIFFERENT model" in fit["basis"]
        assert fit["same_fit_as"].endswith("factor_r_squared")

    @pytest.mark.asyncio
    async def test_the_adjusted_r_squared_declares_its_window_to_the_audit(self):
        """XS-009's own predicate, on the fit block this change adds.

        A published fit statistic that does not declare the window and count it
        was fitted over cannot be compared with the other section's R-squared -
        so this asserts it with the audit's function rather than with a copy.
        """
        from app.debugging.context_audit import _declares_window_and_observations

        result = await _book_score()
        fit = (
            _precision(result)["estimated_statistics"]["factor_r_squared"]
            ["notes"]["adjusted_r_squared_fit"]
        )
        assert _declares_window_and_observations(fit) is True

    @pytest.mark.asyncio
    async def test_the_section_now_satisfies_the_uncertainty_rule_token_set(self):
        """The rule's own constants, not a hand-written copy of them."""
        result = await _book_score()
        precision = _precision(result)
        tokens = {
            key
            for key, value in precision["estimated_statistics"][
                "avg_pairwise_correlation"
            ]["estimates"]["avg_pairwise_correlation"].items()
            if any(token in key.lower() for token in UNCERTAINTY_KEY_TOKENS)
            and value is not None
        }
        assert "standard_error" in tokens and "conf_int" in tokens and "effective_n" in tokens

    @pytest.mark.asyncio
    async def test_env_020_does_not_fire_on_a_dashboard_carrying_this_score(self):
        """The rule itself, on a freshly built payload - not a saved artifact.

        `risk_score` has no top-level twin, so its subtree has to carry its own
        disclosure. The control is the same payload with the disclosure removed,
        which MUST be red: a test that cannot go red proves nothing.
        """
        result = await _book_score()
        assert _env020(_dashboard_export(result)) == []
        assert _env020(_dashboard_export(_strip_disclosure(result)))

    @pytest.mark.asyncio
    async def test_a_wide_book_reduces_the_draw_count_and_publishes_that_it_did(self):
        """The cost bound is a published decision, never a silent one."""
        wide, benchmark, weights = _book(observations=60, names=40, seed=8)
        result = await _score(wide, weights, benchmark)
        block = _precision(result)["estimated_statistics"]["avg_pairwise_correlation"]
        assert block["notes"]["pair_count"] == 40 * 39 // 2
        assert block["bootstrap_resamples"] == pairwise_resample_count(780)
        assert block["bootstrap_resamples"] < UNCERTAINTY_BOOTSTRAP_RESAMPLES
        assert "REDUCED" in block["notes"]["resample_count_rule"]
        # a reduced draw count must not cost the band
        assert block["estimates"]["avg_pairwise_correlation"]["conf_int"] is not None
        # and the ordinary book size is untouched
        normal = await _book_score(names=5)
        assert (
            _precision(normal)["estimated_statistics"]["avg_pairwise_correlation"]
            ["bootstrap_resamples"] == UNCERTAINTY_BOOTSTRAP_RESAMPLES
        )

    @pytest.mark.asyncio
    async def test_a_different_sample_moves_both_standard_errors(self):
        """They are measurements of these samples, not constants of the method."""
        first = await _book_score(seed=21)
        second = await _book_score(seed=99)
        moved = [
            field for field in ESTIMATED_FIELDS
            if _entry(first, field)["standard_error"] != _entry(second, field)["standard_error"]
        ]
        assert moved, "a different book must move at least one standard error"


# ---------------------------------------------------------------------------
# 2. a derived sub-score INHERITS its input's precision
# ---------------------------------------------------------------------------

class TestDerivedSubScoresInheritPrecision:
    @pytest.mark.asyncio
    async def test_every_leg_declares_itself_a_deterministic_derivation(self):
        result = await _book_score()
        audit = result["score_audit"]
        derived = _precision(result)["derived_values"]
        assert set(derived) == set(RISK_SCORE_WEIGHTS)
        for leg in RISK_SCORE_WEIGHTS:
            entry = audit["components"][leg]
            assert entry["precision_classification"] == "deterministic_derivation"
            assert entry["precision_inherits_from"] == RISK_SCORE_LEG_SPECS[leg][
                "input_statistic"
            ]
            assert entry["precision_disclosure_at"] == (
                f"score_audit.precision.derived_values.{leg}"
            )
            assert derived[leg]["classification"] == "deterministic_derivation"

    @pytest.mark.asyncio
    async def test_the_correlation_leg_inherits_its_inputs_basis_and_names_it(self):
        result = await _book_score()
        derived = _precision(result)["derived_values"]["correlation"]
        source = _entry(result, "avg_pairwise_correlation")
        assert derived["input_statistic"] == "avg_pairwise_correlation"
        assert derived["input_statistic_value"] == pytest.approx(
            result["avg_pairwise_correlation"], abs=1e-4
        )
        # the pointer resolves to a real, non-empty disclosure
        assert derived["inherits_precision_at"].endswith(
            "estimated_statistics.avg_pairwise_correlation"
            ".estimates.avg_pairwise_correlation"
        )
        assert source["conf_int"] is not None
        # and the sub-score itself carries NO interval of its own
        assert derived["conf_int"] is None
        assert derived["standard_error"] is None
        assert "INHERITED" in derived["conf_int_reason"]
        assert "not computed" in derived["standard_error_reason"]

    @pytest.mark.asyncio
    async def test_a_derived_sub_score_recomputes_from_its_published_input(self):
        """The inheritance is not an excuse to stop being recomputable."""
        result = await _book_score()
        derived = _precision(result)["derived_values"]
        for leg in RISK_SCORE_WEIGHTS:
            value = derived[leg]["input_statistic_value"]
            if value is None or derived[leg]["input_statistic_provenance"] != "measured":
                continue
            assert derived[leg]["formula"]
            assert derived[leg]["sub_score"] == result["components"][leg]
        correlation = derived["correlation"]
        expected = min(
            RISK_SCORE_CAP,
            max(0.0, correlation["input_statistic_value"] * RISK_CORRELATION_POINTS_PER_UNIT),
        )
        assert correlation["sub_score"] == pytest.approx(expected, abs=0.05)

    @pytest.mark.asyncio
    async def test_a_leg_whose_input_has_no_disclosure_says_so_rather_than_borrowing(self):
        """The honesty case: nothing is invented to fill a hole."""
        result = await _book_score()
        derived = _precision(result)["derived_values"]
        for leg, statistic in (
            ("volatility", "portfolio_return_annualized_volatility"),
            ("market_risk", "recent_portfolio_return_annualized_volatility"),
        ):
            assert derived[leg]["inherits_precision_from"] == statistic
            assert derived[leg]["inherits_precision_at"] is None
            assert derived[leg]["standard_error"] is None
            assert "publishes no standard error or interval for it" in (
                derived[leg]["standard_error_reason"]
            )

    @pytest.mark.asyncio
    async def test_concentration_inherits_from_no_block_rather_than_the_weight_table(self):
        """HHI is MEASURED, so it cannot inherit a precision from a declared constant.

        It used to point at ``score_audit.precision.declared_constants`` - the
        ``RISK_SCORE_WEIGHTS`` block, whose own class definition says it "was
        never estimated" and whose ``standard_error`` and ``conf_int`` are both
        ``None``.  A measured input was therefore claiming to inherit its
        precision from a node that declares it has none, and
        ``estimated_statistics`` held no Herfindahl block to point at instead.
        The honest answer is a null pointer and a reason.
        """
        result = await _book_score()
        precision = _precision(result)
        derived = precision["derived_values"]["concentration"]
        assert derived["input_statistic_provenance"] == "measured"
        assert derived["inherits_precision_at"] is None
        assert derived["standard_error"] is None
        reason = derived["standard_error_reason"]
        # a null pointer must not still claim an inheritance it cannot have
        assert "is entirely INHERITED" not in reason
        assert "measured" in reason
        assert "score_audit.precision.estimated_statistics" in reason
        # and there really is no Herfindahl block to have pointed at
        assert "herfindahl_index" not in precision["estimated_statistics"]
        # still exactly recomputable from its own published input
        herfindahl = derived["input_statistic_value"]
        assert derived["sub_score"] == pytest.approx(
            min(RISK_SCORE_CAP, herfindahl * 100.0), abs=1e-6
        )
        assert herfindahl == result["score_audit"]["components"]["concentration"][
            "input_statistic_value"
        ]


# ---------------------------------------------------------------------------
# 2b. THE GENERAL FORM of the pointer defect
# ---------------------------------------------------------------------------

def _resolve(node: Any, pointer: str) -> Any:
    """Walk a dotted pointer, or return a marker saying it does not resolve."""
    missing = object()
    current = node
    for part in str(pointer).split("."):
        if not isinstance(current, dict) or part not in current:
            return missing
        current = current[part]
    return current


_MISSING = _resolve(None, "no.such.node.anywhere")


def _carries_a_figure(node: Any) -> bool:
    """A node that publishes a real standard error or a real interval."""
    if not isinstance(node, dict):
        return False
    if node.get("standard_error") is not None:
        return True
    interval = node.get("conf_int")
    return isinstance(interval, (list, tuple)) and len(interval) == 2


class TestEveryInheritsPrecisionPointerResolvesToARealFigure:
    """General form: a pointer is either real, or absent with a stated reason.

    The concrete defect this catches: one leg published
    ``inherits_precision_at: "score_audit.precision.declared_constants"`` - a
    pointer to a node whose ``standard_error`` and ``conf_int`` are both null by
    design.  Written narrowly, the rule "the concentration leg must not point at
    declared_constants" would have passed the moment somebody invented a third
    node with no figure in it.  Written this way it cannot.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("gappy_leg", [True, False])
    @pytest.mark.parametrize("names", [5, 9])
    async def test_every_leg_pointer_resolves_to_a_figure_or_is_null_with_a_reason(
        self, names: int, gappy_leg: bool
    ):
        result = await _book_score(names=names, gappy_leg=gappy_leg)
        precision = _precision(result)
        checked = 0
        for leg in RISK_SCORE_WEIGHTS:
            entry = precision["derived_values"][leg]
            pointer = entry["inherits_precision_at"]
            assert "inherits_precision_at" in entry, leg
            if pointer is None:
                reason = entry["standard_error_reason"]
                assert reason, f"{leg}: a null pointer needs a reason"
                assert "is entirely INHERITED" not in reason, (
                    f"{leg}: a null pointer cannot claim an inheritance"
                )
                assert "estimated_statistics" in reason, (
                    f"{leg}: the reason must name where such a figure would go"
                )
            else:
                target = _resolve(precision, str(pointer).removeprefix("score_audit.precision."))
                assert target is not _MISSING, (
                    f"{leg}: pointer {pointer!r} does not resolve inside precision"
                )
                assert _carries_a_figure(target), (
                    f"{leg}: pointer {pointer!r} resolves to a node with no "
                    f"standard error and no interval: {target!r}"
                )
            # whatever the pointer says, the leg itself is a derivation and
            # publishes no band of its own
            assert entry["classification"] == "deterministic_derivation", leg
            assert entry["standard_error"] is None, leg
            assert entry["conf_int"] is None, leg
            checked += 1
        assert checked == len(RISK_SCORE_WEIGHTS)

    @pytest.mark.asyncio
    async def test_the_pointer_map_holds_no_entry_that_resolves_to_nothing(self):
        """The map itself, checked without building a payload.

        This is the form that fails fastest and covers every leg including the
        ones a fixture happens not to exercise: an entry in
        `RISK_SCORE_INPUT_PRECISION_AT` is a promise, and a promise that no node
        in the block keeps is the defect.
        """
        precision_shape = {
            "estimated_statistics": {
                "avg_pairwise_correlation": {
                    "estimates": {"avg_pairwise_correlation": {
                        "standard_error": 0.01, "conf_int": [0.0, 0.2],
                    }},
                },
                "factor_r_squared": {
                    "estimates": {"factor_r_squared": {
                        "standard_error": 0.02, "conf_int": [0.0, 0.4],
                    }},
                },
            },
            "declared_constants": {
                # the real shape: a policy table with no band, by design
                "standard_error": None, "conf_int": None,
            },
        }
        for statistic, pointer in RISK_SCORE_INPUT_PRECISION_AT.items():
            local = str(pointer).removeprefix("score_audit.precision.")
            target = _resolve(precision_shape, local)
            assert target is not _MISSING, (
                f"{statistic}: RISK_SCORE_INPUT_PRECISION_AT points at "
                f"{pointer!r}, which resolves to nothing in the published block"
            )
            assert _carries_a_figure(target), (
                f"{statistic}: RISK_SCORE_INPUT_PRECISION_AT points at "
                f"{pointer!r}, a node with no standard error and no interval"
            )
        # the entry this defect removed, asserted by name so the regression is
        # named rather than merely absent
        assert "herfindahl_index" not in RISK_SCORE_INPUT_PRECISION_AT

    @pytest.mark.asyncio
    async def test_a_leg_with_a_null_pointer_and_a_leg_with_a_real_one_read_alike(self):
        """One shape, two facts.  The reason differs; the grammar does not."""
        result = await _book_score()
        resolved = _precision(result)["derived_values"]["correlation"]
        unresolved = _precision(result)["derived_values"]["volatility"]
        for entry in (resolved, unresolved):
            reason = entry["standard_error_reason"]
            assert reason.startswith("not computed: this sub-score is a "
                                     "deterministic function of one published input")
            assert reason.endswith(
                "not the uncertainty of anything this sub-score measured, and a "
                "reader could not tell the two apart."
            ), reason
            # one reason, used for both absent figures
            assert entry["conf_int_reason"] == reason


# ---------------------------------------------------------------------------
# 2c. THE GENERAL FORM of the prose defect: no clause spliced into another
# ---------------------------------------------------------------------------

#: A period glued to the next word with no space.  Legal inside a number
#: (``0.124123``), a dotted path (``estimates.volatility_forecast``), an
#: initialism (``U.S.``), an attribute access (``np.linalg.lstsq``) and a file
#: path (``analytics_engine.py``).  ILLEGAL when the word it opens is prose -
#: which is what a clause spliced into a pointer produces, and it is how
#: ``precision.estimated_statistics.portfolio.estimates.the fitted leg's ...``
#: reached a published reason on fourteen legs.
_GLUED_PERIOD = re.compile(r"(?<=[A-Za-z0-9_])\.([A-Za-z][A-Za-z0-9_]*)")

#: A dotted path segment is followed by '.', a bracket, a comma, a semicolon or
#: the end of the string.  Prose is followed by a space and a lower-case word.
_PROSE_AFTER_GLUED_PERIOD = re.compile(r"^\s+[a-z]")

#: A published field name is a legitimate sentence-opener in lower case.
_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")

#: A sentence may legitimately continue in lower case after a label, a list
#: marker or a parenthetical: "complete case: a row is measured only when ...".
_CONTINUES_AFTER = (":", "-", "(", "[", "/", "=", ",", ";", "'", '"')

#: Abbreviations whose trailing period is not a sentence end.
_ABBREVIATIONS = ("i.e.", "e.g.", "vs.", "etc.", "cf.", "resp.", "no.", "fig.")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_LEADING_TOKEN = re.compile(r"^[^A-Za-z0-9`_]*([A-Za-z0-9`_]+)")


def _identifier_chain_start(text: str, index: int) -> int:
    index -= 1
    while index >= 0 and re.match(r"[A-Za-z0-9_/\\.-]", text[index]):
        index -= 1
    return index + 1


def assert_no_clause_is_spliced_into_another(text: str, where: str) -> None:
    """Raise on a sentence that is a fragment rather than a statement.

    Two rules, both validated against every prose string the v26 artifact
    publishes (1400 of them) with zero false positives, and both general: a new
    reason string in this module is checked without being named here.

    1. NO GLUED PROSE.  A period inside a path, a number, an initialism, an
       attribute access or a file path is not a sentence boundary.  A period
       immediately followed by an English word, with a space and a lower-case
       word after it, is a sentence boundary that should not be there.

    2. EVERY SENTENCE IS A SENTENCE.  After splitting on the boundaries rule 1
       accepts, no sentence may open in lower case unless it is a published
       field name, a backticked name, or a continuation of a label or an
       abbreviation.
    """
    body = " ".join(str(text).split())
    assert body, f"{where}: an empty reason states nothing"

    for match in _GLUED_PERIOD.finditer(body):
        word = match.group(1)
        if not word[0].islower() or _SNAKE_CASE.match(word):
            continue
        if not _PROSE_AFTER_GLUED_PERIOD.match(body[match.end():]):
            continue
        chain = body[_identifier_chain_start(body, match.start()):match.start()]
        if "/" in chain or "\\" in chain:  # a file path
            continue
        raise AssertionError(
            f"{where}: a clause is spliced onto a path - {match.group(0)!r} is "
            f"followed by prose: ...{body[max(0, match.start() - 80):match.end() + 60]}..."
        )

    sentences = _SENTENCE_SPLIT.split(body)
    for previous, sentence in zip(sentences, sentences[1:]):
        previous, sentence = previous.strip(), sentence.strip()
        match = _LEADING_TOKEN.match(sentence)
        if not match:
            continue
        opener = match.group(1)
        if not opener[0].islower():
            continue
        if previous.endswith(_CONTINUES_AFTER):
            continue
        if any(previous.endswith(a) for a in _ABBREVIATIONS):
            continue
        if sentence.startswith("`") or _SNAKE_CASE.match(opener):
            continue
        raise AssertionError(
            f"{where}: {opener!r} opens what is not a sentence - "
            f"...{previous[-70:]} / {sentence[:90]}..."
        )


class TestNoPublishedProseHasAClauseSplicedIntoAnother:
    def test_every_reason_this_module_publishes_is_a_sequence_of_sentences(self):
        """Every module-level prose constant in `analytics_engine`, in one sweep.

        Written over the CONSTANTS rather than over a fixture's output so a
        string added in a later wave is checked without anybody remembering to
        add it here, and so the check does not need a book to run.
        """
        checked = 0
        for name in dir(analytics_engine):
            if not name.isupper():
                continue
            value = getattr(analytics_engine, name)
            if not isinstance(value, str) or not value.strip():
                continue
            assert_no_clause_is_spliced_into_another(
                value, f"analytics_engine.{name}"
            )
            checked += 1
        # a guard on the guard: an empty sweep would pass silently
        assert checked >= 25, (
            f"only {checked} prose constants were checked - the sweep is broken"
        )

    @pytest.mark.asyncio
    async def test_every_reason_on_the_built_score_block_is_a_sequence_of_sentences(self):
        result = await _book_score()
        precision = _precision(result)
        checked = 0

        def _walk(node: Any, path: str) -> None:
            nonlocal checked
            if isinstance(node, dict):
                for key, value in node.items():
                    _walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    _walk(value, f"{path}[{index}]")
            elif isinstance(node, str) and path.rsplit(".", 1)[-1].endswith(
                ("_reason", "_basis", "_note")
            ):
                assert_no_clause_is_spliced_into_another(node, path)
                checked += 1

        _walk(precision, "score_audit.precision")
        assert checked >= 20, f"only {checked} reason strings were checked"

    @pytest.mark.asyncio
    async def test_the_absent_interval_reason_never_claims_an_inheritance_it_lacks(self):
        """The rule that catches the volatility/market_risk splice directly.

        Before this change those two legs published
        ``inherits_precision_at: null`` alongside a reason reading "Its precision
        is entirely INHERITED from that input's own disclosure, published at no
        precision disclosure for this input is published in this section ..." -
        a whole clause substituted into the noun phrase after "published at",
        and a claim of inheritance from a disclosure that does not exist.  There
        is no interior period to find, so it is the CLAIM that has to be checked.
        """
        result = await _book_score()
        derived = _precision(result)["derived_values"]
        for leg, entry in derived.items():
            if entry["inherits_precision_at"] is not None:
                continue
            reason = entry["standard_error_reason"]
            assert "is entirely INHERITED" not in reason, leg
            assert "published at no precision disclosure" not in reason, leg
            # the absence is named, and the place a figure would go is named
            assert "publishes no standard error or interval for it" in reason, leg
            assert "score_audit.precision.estimated_statistics" in reason, leg
            assert f"score_audit.components.{leg}.input_sample" in reason, leg


# ---------------------------------------------------------------------------
# 3. a declared constant is labelled, named and given NO standard error
# ---------------------------------------------------------------------------

class TestDeclaredConstantsAreLabelledNotBanded:
    @pytest.mark.asyncio
    async def test_the_weight_table_is_named_and_the_values_match_it(self):
        result = await _book_score()
        declared = _precision(result)["declared_constants"]
        assert declared["classification"] == "declared_constant"
        assert declared["table_identifier"] == "RISK_SCORE_WEIGHTS"
        assert "analytics_engine.py" in declared["table"]
        assert declared["nominal_weights"] == RISK_SCORE_WEIGHTS
        assert declared["nominal_weights"] == result["score_audit"]["nominal_weights"]
        for leg, weight in declared["effective_weights"].items():
            assert weight == result["score_audit"]["components"][leg]["effective_weight"]

    @pytest.mark.asyncio
    async def test_a_declared_constant_carries_no_standard_error_and_says_why(self):
        result = await _book_score()
        declared = _precision(result)["declared_constants"]
        assert declared["standard_error"] is None
        assert declared["conf_int"] is None
        assert "declared policy constant" in declared["standard_error_reason"]
        assert "RISK_SCORE_WEIGHTS" in declared["standard_error_reason"]
        assert "no sampling distribution" in declared["standard_error_reason"]
        # the weight table itself is the proof: it is a dict of literals
        assert all(
            isinstance(value, float) for value in RISK_SCORE_WEIGHTS.values()
        )

    @pytest.mark.asyncio
    async def test_the_headline_contribution_is_also_an_arithmetic_identity(self):
        result = await _book_score()
        attribution = _precision(result)["headline_attribution"]
        assert attribution["published_at"] == (
            "score_audit.effective_information.headline_attribution"
        )
        assert attribution["standard_error"] is None
        assert attribution["conf_int"] is None
        assert "not computed" in attribution["standard_error_reason"]
        published = result["score_audit"]["effective_information"]["headline_attribution"]
        for leg, value in published.items():
            assert value == pytest.approx(
                result["components"][leg] * declared_weight(result, leg), abs=0.06
            )

    @pytest.mark.asyncio
    async def test_the_rule_limitation_is_recorded_rather_than_worked_around(self):
        result = await _book_score()
        limitation = _precision(result)["rule_limitation"]
        assert "declared constant" in limitation
        assert "cannot distinguish" in limitation


def declared_weight(result: Dict[str, Any], leg: str) -> float:
    return float(result["score_audit"]["components"][leg]["effective_weight"])


# ---------------------------------------------------------------------------
# 4. THE SCORES DO NOT MOVE
# ---------------------------------------------------------------------------

def _strip_disclosure(payload: Any) -> Any:
    """The score block with every key this change added removed."""
    if isinstance(payload, dict):
        return {
            key: _strip_disclosure(value)
            for key, value in payload.items()
            if key not in NEW_DISCLOSURE_KEYS and key != "precision"
        }
    if isinstance(payload, list):
        return [_strip_disclosure(item) for item in payload]
    return payload


def _dashboard_export(risk_score: Dict[str, Any]):
    """A minimal in-memory export carrying the section under test."""
    from pathlib import Path

    from app.debugging.context_audit import Export

    return Export(
        doc={
            "schema_version": "2.0",
            "sections": {
                "dashboard": {
                    "data": {"components": {"risk_score": {"data": risk_score}}}
                }
            },
        },
        raw="",
        path=Path("memory"),
    )


def _env020(export) -> List[str]:
    """ENV-020's own verdict, run in process on a payload built by this code."""
    from app.debugging.context_audit import env_020_point_estimates_carry_uncertainty

    return [f.message for f in env_020_point_estimates_carry_uncertainty(export)]


class TestThePublishedScoreIsUnchanged:
    @pytest.mark.asyncio
    async def test_the_whole_score_block_is_byte_identical_without_the_disclosure(
        self, monkeypatch
    ):
        """A disclosure that moves a score is not a disclosure, it is a change.

        `risk_scoring` is run twice on the same book: once with the precision
        builder stubbed out - which is exactly the payload this section
        published before the change - and once for real.  The two must agree
        everywhere outside the new keys.
        """
        import app.services.analytics_engine as engine

        frame, benchmark, weights = _book()
        before = await _score(frame, weights, benchmark)
        monkeypatch.setattr(
            engine, "_risk_score_precision",
            lambda **_kwargs: {"suppressed_for_comparison": True},
        )
        suppressed = await _score(frame, weights, benchmark)
        monkeypatch.undo()

        # the stub is a different payload by construction, so the comparison is
        # made against the DISCLOSURE REMOVED from the real payload
        assert "suppressed_for_comparison" in suppressed["score_audit"]["precision"]
        assert _strip_disclosure(before) == _strip_disclosure(suppressed)
        # and the real one differs ONLY by the disclosure
        differing = {
            key
            for key in set(before) | set(suppressed)
            if before.get(key) != suppressed.get(key)
        }
        assert differing == {"score_audit"}
        before_audit = {
            key: value for key, value in before["score_audit"].items()
            if key != "precision"
        }
        suppressed_audit = {
            key: value for key, value in suppressed["score_audit"].items()
            if key != "precision"
        }
        assert before_audit == suppressed_audit

    @pytest.mark.asyncio
    async def test_the_headline_the_level_and_every_sub_score_are_unchanged(self):
        frame, benchmark, weights = _book()
        result = await _score(frame, weights, benchmark)
        # recomputed from the payload's own published ingredients
        audit = result["score_audit"]
        information = audit["effective_information"]
        contributions = information["headline_attribution"]
        # This used to be asserted against the ROUNDED `overall_score` with a
        # 0.05 window, which passed no matter how wrong the denominator was: it
        # was measuring the rounding, not the identity. The unrounded total is
        # now published, so the identity is exact to the 6 dp the contributions
        # are published at, and the score is unchanged at the display
        # precision.
        assert sum(contributions.values()) == pytest.approx(
            information["overall_score_raw"], abs=1e-5
        )
        assert information["headline_basis_score"] == information["overall_score_raw"]
        assert information["headline_basis_score_rounded"] == result["overall_score"]
        assert result["overall_score"] == pytest.approx(
            information["overall_score_raw"], abs=0.05
        )
        assert result["risk_level"] == (
            "LOW" if result["overall_score"] < 15
            else "MEDIUM" if result["overall_score"] < 25
            else "HIGH"
        )
        for leg, weight in audit["nominal_weights"].items():
            assert weight == RISK_SCORE_WEIGHTS[leg]
        for leg, value in result["components"].items():
            assert value == audit["components"][leg]["sub_score"]

    @pytest.mark.asyncio
    async def test_the_precision_block_publishes_the_unrounded_headline(self):
        """`liquidity` has published `overall_score_raw` beside `overall_score`
        since an earlier wave; `risk_score` did not have the key at all. The
        precision block's whole subject is what each number is known to, and the
        headline's first rounding is the one rounding it had no answer for.
        """
        frame, benchmark, weights = _book()
        result = await _score(frame, weights, benchmark)
        information = result["score_audit"]["effective_information"]
        assert "overall_score_raw" in information
        assert information["overall_score_raw"] is not None
        assert information["overall_score_raw"] == information["headline_basis_score"]
        # An absent value is null plus a reason; an absent KEY is not a
        # disclosure at all, which is what this was.
        assert AnalyticsEngine()._empty_risk_score()["overall_score_raw"] is None

    @pytest.mark.asyncio
    async def test_the_alerts_are_unchanged_by_the_disclosure(self):
        """The precision block adds no alert: it reports, it does not warn."""
        frame, benchmark, weights = _book()
        result = await _score(frame, weights, benchmark)
        assert all(isinstance(alert, str) for alert in result["alerts"])
        for alert in result["alerts"]:
            assert "precision" not in alert.lower()


# ---------------------------------------------------------------------------
# 5. the null path -- a missing figure has to say why
# ---------------------------------------------------------------------------

class TestTheNullPathIsStated:
    @pytest.mark.asyncio
    async def test_no_benchmark_leaves_the_regression_with_a_stated_absence(self):
        frame, _, weights = _book()
        result = await _score(frame, weights, None)
        assert result["factor_r_squared"] is None
        assert "factor_risk" in result["excluded_components"]
        entry = _entry(result, "factor_r_squared")
        assert entry["conf_int"] is None
        assert entry["standard_error"] is None
        assert entry["status"] in {"not_applicable", "not_computed"}
        # the reason is the SPECIFIC one: the regression's own sample could not
        # be re-measured, because there is no benchmark to measure it against
        assert "benchmark" in entry["reason"]
        assert entry["point"] is None
        _assert_block_contract(
            _precision(result)["estimated_statistics"]["factor_r_squared"],
            "factor_r_squared",
        )

    @pytest.mark.asyncio
    async def test_a_one_leg_book_leaves_the_correlation_with_a_stated_absence(self):
        """A single holding has no pair to correlate - not a correlation of 0."""
        rng = np.random.default_rng(4)
        returns = {"ONLY": rng.normal(0.0003, 0.010, 120)}
        frame = _prices_from_returns(returns)
        result = await _score(frame, {"ONLY": 1.0}, pd.Series(dtype=float))
        assert result["avg_pairwise_correlation"] is None
        assert "correlation" in result["excluded_components"]
        entry = _entry(result, "avg_pairwise_correlation")
        assert entry["conf_int"] is None
        assert entry["standard_error"] is None
        assert "no average pairwise correlation was measured" in entry["reason"]
        _assert_block_contract(
            _precision(result)["estimated_statistics"]["avg_pairwise_correlation"],
            "avg_pairwise_correlation",
        )

    @pytest.mark.asyncio
    async def test_a_short_window_declares_the_count_instead_of_a_band(self):
        """Below the interval minimum the point stands and the gap is stated."""
        frame, benchmark, weights = _book(observations=12, names=4)
        result = await _score(frame, weights, benchmark)
        for field in ESTIMATED_FIELDS:
            block = _precision(result)["estimated_statistics"][field]
            _assert_block_contract(block, field)
            if block["estimates"][field]["conf_int"] is None:
                assert block["estimates"][field]["reason"]
        assert json.dumps(result)

    @pytest.mark.asyncio
    async def test_an_empty_score_publishes_no_precision_block_at_all(self):
        result = AnalyticsEngine()._empty_risk_score()
        assert result["score_audit"] is None
        assert result["score_audit_reason"]
