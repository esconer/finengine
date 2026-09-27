"""
RL-2: the fat-tail verdict contradicted the GPD shape published beside it.

`risk_studio.tail_dependence` published `is_fat_tailed: true` directly beside

    gpd_shape_xi_raw  = -0.54850111
    gpd_shape_xi_used = -0.5     (basis: constrained_clip)

A negative GPD shape is a BOUNDED tail under the parameterisation this service
uses, so the flag and the parameter asserted opposite things in the same block
and nothing said which of the three underlying signals had produced the flag.

The old rule, preserved here verbatim in `OLD_FAT_TAIL_RULE` so each test can
demonstrate that it would have published the contradicting verdict, was a bare
disjunction with no published basis:

    xi_raw > 0.05  or  excess_kurt > 0.5  or  var_evt_loss > hist_var_loss

Three things are pinned here:

1. A negative published shape can never sit beside an asserted
   `is_fat_tailed: True` without a stated reason. Where the shape contradicts
   the flag, the verdict is withheld (null) with the reason published.
2. A genuinely fat-tailed fixture still reports the fat-tail verdict.
3. A shape too weak to classify is recorded as unclassifiable rather than
   silently counted as evidence either way.
4. The clipped shape (`gpd_shape_xi_used`) is never read as if it were the
   fitted value (`gpd_shape_xi_raw`) when deriving the verdict.

Sign convention, verified rather than assumed: this service fits with
`scipy.stats.genpareto`, whose documented pdf is f(x, c) = (1 + c*x)**(-1 - 1/c)
with support "x >= 0 if c >= 0, and 0 <= x <= -1/c if c < 0", c = 0 exponential
and c = -1 uniform on [0, 1] (SciPy 1.18 reference, scipy.stats.genpareto). So
c < 0 gives the tail a FINITE right endpoint at -1/c, i.e. a bounded tail.
"""

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from app.services.tail_risk_service import (
    FAT_TAIL_EXCESS_KURTOSIS_THRESHOLD,
    FAT_TAIL_SHAPE_THRESHOLD,
    GPD_SHAPE_CLIP_HIGH,
    GPD_SHAPE_CLIP_LOW,
    GPD_SHAPE_SIGN_RULE,
    TailRiskService,
    _fat_tail_shape_sign,
    _fat_tail_verdict,
)

#: The pre-fix rule, reproduced so each test can prove it fails here. This is
#: the code that published `is_fat_tailed: true` beside a negative shape.
OLD_FAT_TAIL_RULE = "xi_raw>0.05 OR excess_kurt>0.5 OR var_evt_loss>hist_var_loss"


def _old_rule(xi_raw, excess_kurt, var_evt_loss, hist_var_loss):
    """The removed disjunction, verbatim, for cause-pinning."""
    return bool(
        (xi_raw is not None and xi_raw > 0.05)
        or excess_kurt > 0.5
        or var_evt_loss > hist_var_loss
    )


def _evt(returns, **kwargs):
    return TailRiskService.calculate_evt_pot_var_es(
        pd.Series(returns), confidence_level=0.99, threshold_quantile=0.95, **kwargs
    )


# --------------------------------------------------------------------------- #
# Criterion 1 - a negative published shape never sits beside an asserted True.
# --------------------------------------------------------------------------- #

#: Exactly the shape of the reviewed artifact: negative fitted GPD shape, the
#: fitted VaR slightly worse than the empirical one, and nothing else firing.
V17_PUBLISHED = {
    "gpd_shape_xi_raw": -0.54850111,
    "gpd_shape_xi_used": -0.5,
    "evt_pot_var": -0.033705,
    "historical_var": -0.030462,
}


def test_v17_published_numbers_would_have_asserted_a_fat_tail():
    """Pin the cause: the old disjunction fires on the artifact's own numbers."""
    # The published values are in return space, so the loss-space comparison the
    # code performs is the negation of each.
    assert _old_rule(
        xi_raw=V17_PUBLISHED["gpd_shape_xi_raw"],
        excess_kurt=0.30,  # not published in the artifact; cannot fire
        var_evt_loss=-V17_PUBLISHED["evt_pot_var"],
        hist_var_loss=-V17_PUBLISHED["historical_var"],
    ) is True


def test_negative_shape_with_a_firing_var_comparison_withholds():
    verdict, basis = _fat_tail_verdict(
        xi_raw=V17_PUBLISHED["gpd_shape_xi_raw"],
        xi_constrained=V17_PUBLISHED["gpd_shape_xi_used"],
        excess_kurt=0.30,
        var_evt_loss=-V17_PUBLISHED["evt_pot_var"],
        hist_var_loss=-V17_PUBLISHED["historical_var"],
    )
    assert verdict is None
    assert basis["gpd_shape_sign"] == "negative_bounded_tail"
    # The measured values that made the verdict uninformative are published
    # even though the verdict is withheld, so this is not a bare absence.
    assert basis["fired_signals"] == ["evt_var_exceeds_historical_var"]
    assert basis["withheld_reason"]


def test_withheld_reason_names_the_shape_value_and_the_firing_signals():
    verdict, basis = _fat_tail_verdict(
        xi_raw=-0.54850111, xi_constrained=-0.5, excess_kurt=3.0,
        var_evt_loss=0.033705, hist_var_loss=0.030462,
    )
    assert verdict is None
    reason = basis["withheld_reason"]
    assert "-0.54850111" in reason            # the contradicting parameter
    assert "excess_kurtosis_above_threshold" in reason   # the signal that fired
    assert "evt_var_exceeds_historical_var" in reason
    assert "negative" in reason and "bounds the tail" in reason


def test_no_fitted_negative_shape_can_ever_yield_true():
    """The invariant, swept across the plausible fitted-shape range."""
    for xi in (-0.05, -0.2, -0.5, -0.55, -1.1, -3.0, -1e-9):
        for kurt in (0.0, 0.5, 5.0, 500.0):
            for var_fired in (False, True):
                verdict, basis = _fat_tail_verdict(
                    xi_raw=xi,
                    xi_constrained=xi,
                    excess_kurt=kurt,
                    var_evt_loss=0.03 if var_fired else 0.01,
                    hist_var_loss=0.02,
                )
                if basis["gpd_shape_sign"] == "negative_bounded_tail":
                    assert verdict is not True, (
                        f"negative shape {xi} published an asserted "
                        f"is_fat_tailed: true (kurt={kurt}, var_fired={var_fired})"
                    )


def test_true_verdict_never_coincides_with_a_bounded_tail_classification():
    """Published end to end, over a sweep of seeded fat and thin samples."""
    generators = {
        "gaussian": lambda g, n: g.normal(0.0005, 0.02, n),
        "t_3": lambda g, n: g.standard_t(3, size=n) * 0.02,
        "t_1.5": lambda g, n: g.standard_t(1.5, size=n) * 0.02,
        "t_1.1": lambda g, n: g.standard_t(1.1, size=n) * 0.02,
        "pareto_0.8": lambda g, n: (g.pareto(0.8, size=n) - 1) * 0.02,
        "uniform": lambda g, n: g.uniform(-0.05, 0.05, n),
    }
    checked = 0
    for gen in generators.values():
        for seed in range(1, 10):
            res = _evt(gen(np.random.default_rng(seed), 520))
            basis = res["is_fat_tailed_basis"]
            if basis["gpd_shape_sign"] == "negative_bounded_tail":
                assert res["is_fat_tailed"] is not True, (
                    f"bounded-tail shape {basis['gpd_shape_xi_fitted']} published "
                    f"is_fat_tailed: true"
                )
            checked += 1
    assert checked == 54


def test_every_verdict_publishes_a_basis():
    """No verdict, withheld or not, is ever published without its basis."""
    res = _evt(np.random.default_rng(3).standard_t(1.5, size=520) * 0.02)
    basis = res["is_fat_tailed_basis"]
    assert basis["rule"] and basis["sign_convention"] == GPD_SHAPE_SIGN_RULE
    assert basis["verdict"] == res["is_fat_tailed"]
    assert basis["fired_signals"]
    assert res["is_fat_tailed_withheld_reason"] == basis["withheld_reason"]


def test_withheld_verdict_is_none_not_false():
    """`None` means 'not computed'; `False` means 'measured, and not fat'."""
    res = _evt(np.random.default_rng(2).normal(0.0005, 0.02, 520))
    basis = res["is_fat_tailed_basis"]
    assert res["is_fat_tailed"] is None
    assert res["is_fat_tailed"] is not False
    assert basis["withheld_reason"]


def test_false_verdict_is_a_measurement_not_a_default():
    """Nothing fired, so `False` is published - and it agrees with the shape."""
    res = _evt(np.random.default_rng(1).normal(0.0005, 0.02, 520))
    basis = res["is_fat_tailed_basis"]
    assert res["is_fat_tailed"] is False
    assert basis["fired_signals"] == []
    assert basis["gpd_shape_sign"] == "negative_bounded_tail"
    assert basis["withheld_reason"] is None
    # And it was actually measured rather than defaulted.
    assert basis["excess_kurtosis"] <= FAT_TAIL_EXCESS_KURTOSIS_THRESHOLD
    assert basis["gpd_shape_xi_fitted"] < -FAT_TAIL_SHAPE_THRESHOLD


# --------------------------------------------------------------------------- #
# Criterion 2 - a genuinely fat-tailed fixture still reports the verdict.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6, 7, 8, 9])
def test_student_t_heavy_tails_report_fat_tailed(seed):
    """A Student-t(1.1) sample is fat-tailed by construction and says so."""
    res = _evt(np.random.default_rng(seed).standard_t(1.1, size=520) * 0.02)
    assert res["is_fat_tailed"] is True
    assert "gpd_shape_xi_raw_above_threshold" in res["is_fat_tailed_basis"][
        "fired_signals"
    ]
    assert res["gpd_shape_xi_raw"] > FAT_TAIL_SHAPE_THRESHOLD


def test_very_heavy_tails_report_fat_tailed():
    for seed in (1, 2, 3, 4, 5, 7, 8, 9):
        res = _evt(np.random.default_rng(seed).standard_t(1.5, size=520) * 0.02)
        assert res["is_fat_tailed"] is True


def test_a_fat_sample_whose_fit_says_bounded_is_withheld_not_asserted():
    """The honest, and load-bearing, case.

    A Student-t(1.5) sample IS fat-tailed by construction, but the GPD fitted to
    its top 5% (26 exceedances) can land negative, which under the published
    sign convention means a BOUNDED tail. Asserting `is_fat_tailed: true` here
    would recreate the reviewed defect on a different sample, so the verdict is
    withheld - and the basis still publishes the kurtosis that fired, so the
    disagreement is visible rather than hidden.
    """
    res = _evt(np.random.default_rng(6).standard_t(1.5, size=520) * 0.02)
    basis = res["is_fat_tailed_basis"]
    assert res["gpd_shape_xi_raw"] < -FAT_TAIL_SHAPE_THRESHOLD
    assert basis["gpd_shape_sign"] == "negative_bounded_tail"
    assert "excess_kurtosis_above_threshold" in basis["fired_signals"]
    assert basis["excess_kurtosis"] > FAT_TAIL_EXCESS_KURTOSIS_THRESHOLD
    assert res["is_fat_tailed"] is None
    assert basis["withheld_reason"]
    # The old disjunction would have published True on exactly these numbers.
    assert _old_rule(
        res["gpd_shape_xi_raw"], basis["excess_kurtosis"], 0.03, 0.02
    ) is True


def test_fat_tail_from_kurtosis_alone_names_that_basis():
    """When the fitted shape is unusable, the basis names what did fire."""
    verdict, basis = _fat_tail_verdict(
        xi_raw=None, xi_constrained=None,
        excess_kurt=25.0, var_evt_loss=0.01, hist_var_loss=0.02,
    )
    assert verdict is True
    assert basis["fired_signals"] == ["excess_kurtosis_above_threshold"]
    assert basis["gpd_shape_sign"] == "not_fitted"
    assert basis["gpd_shape_xi_fitted"] is None
    assert basis["gpd_shape_xi_fitted_field"] == "gpd_shape_xi_raw"


# --------------------------------------------------------------------------- #
# Criterion 3 - a shape too weak to classify is not silently counted.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("xi", [0.0, 0.01, -0.01, 0.049, -0.049])
def test_shape_inside_the_unclassifiable_band_is_labelled_not_guessed(xi):
    assert _fat_tail_shape_sign(xi) == "unclassifiable_near_exponential"


def test_unclassifiable_shape_alone_does_not_assert_fat_tails():
    verdict, basis = _fat_tail_verdict(
        xi_raw=0.01, xi_constrained=0.01,
        excess_kurt=0.1, var_evt_loss=0.01, hist_var_loss=0.02,
    )
    assert verdict is False
    assert basis["gpd_shape_sign"] == "unclassifiable_near_exponential"
    assert basis["fired_signals"] == []


def test_unclassifiable_shape_defers_to_a_firing_kurtosis():
    verdict, basis = _fat_tail_verdict(
        xi_raw=-0.048, xi_constrained=-0.048,
        excess_kurt=119.0, var_evt_loss=0.03, hist_var_loss=0.02,
    )
    assert verdict is True
    assert "excess_kurtosis_above_threshold" in basis["fired_signals"]


def test_sign_classification_boundaries():
    assert _fat_tail_shape_sign(None) == "not_fitted"
    assert _fat_tail_shape_sign(FAT_TAIL_SHAPE_THRESHOLD) == (
        "unclassifiable_near_exponential"
    )
    assert _fat_tail_shape_sign(FAT_TAIL_SHAPE_THRESHOLD + 1e-6) == (
        "positive_heavy_tail"
    )
    assert _fat_tail_shape_sign(-FAT_TAIL_SHAPE_THRESHOLD) == (
        "unclassifiable_near_exponential"
    )
    assert _fat_tail_shape_sign(-FAT_TAIL_SHAPE_THRESHOLD - 1e-6) == (
        "negative_bounded_tail"
    )


# --------------------------------------------------------------------------- #
# Criterion 4 - the clipped shape is never read as the fitted value.
# --------------------------------------------------------------------------- #

def test_the_shape_clip_can_never_flip_the_sign_of_a_fitted_shape():
    """Provable, so the verdict never has to guess what the clip did."""
    for xi in np.linspace(-50.0, 50.0, 20001):
        clipped = float(np.clip(xi, GPD_SHAPE_CLIP_LOW, GPD_SHAPE_CLIP_HIGH))
        if xi == 0.0:
            assert clipped == 0.0
        else:
            assert np.sign(clipped) == np.sign(xi), f"clip flipped the sign of {xi}"


def test_the_service_clips_with_the_published_constants():
    """The documented bounds and the ones the fit actually uses are the same."""
    import inspect

    src = inspect.getsource(TailRiskService.calculate_evt_pot_var_es)
    assert "GPD_SHAPE_CLIP_LOW" in src
    assert "GPD_SHAPE_CLIP_HIGH" in src
    assert "np.clip(xi_raw, -0.5, 0.95)" not in src
    # And the bounds are where the rule text says they are.
    assert (GPD_SHAPE_CLIP_LOW, GPD_SHAPE_CLIP_HIGH) == (-0.5, 0.95)


def test_verdict_reads_the_raw_fit_never_the_clipped_value():
    """The basis names the field the verdict was read from."""
    verdict, basis = _fat_tail_verdict(
        xi_raw=-0.54850111, xi_constrained=-0.5,
        excess_kurt=0.3, var_evt_loss=0.033705, hist_var_loss=0.030462,
    )
    assert verdict is None
    assert basis["gpd_shape_xi_fitted"] == pytest.approx(-0.54850111)
    assert basis["gpd_shape_xi_used_for_metrics"] == pytest.approx(-0.5)
    assert basis["gpd_shape_xi_was_clipped"] is True
    assert basis["gpd_shape_xi_fitted_field"] == "gpd_shape_xi_raw"


def test_a_clipped_shape_is_disclosed_as_clipped_end_to_end():
    """A real fitted reproduction of the reviewed artifact's shape."""
    res = _evt(np.random.default_rng(20).normal(0.0005, 0.02, 520))
    basis = res["is_fat_tailed_basis"]
    # Fitted shape below the clip floor, exactly the reviewed pattern.
    assert res["gpd_shape_xi_raw"] < -0.5
    assert res["gpd_shape_constrained"] is True
    assert "gpd_shape_clipped" in res["constraint_reason"]
    assert res["gpd_shape_xi_used"] == pytest.approx(-0.5)
    assert basis["gpd_shape_xi_was_clipped"] is True
    # The clipped value is what the moments used, and is published as such.
    assert basis["gpd_shape_xi_used_for_metrics"] == pytest.approx(
        res["gpd_shape_xi_constrained"]
    )
    # The verdict's shape reading is the raw fit, not the clip.
    assert basis["gpd_shape_xi_fitted"] == pytest.approx(res["gpd_shape_xi_raw"])
    assert res["is_fat_tailed"] is None


def test_a_shape_clipped_at_the_ceiling_still_reports_fat_tailed_end_to_end():
    res = _evt(np.random.default_rng(5).standard_t(1.5, size=520) * 0.02)
    assert res["gpd_shape_xi_raw"] > 1.0        # above the 0.95 ceiling
    assert res["gpd_shape_xi_used"] == pytest.approx(0.95)
    assert res["gpd_shape_constrained"] is True
    assert res["is_fat_tailed"] is True
    assert (
        res["is_fat_tailed_basis"]["gpd_shape_xi_fitted_field"]
        == "gpd_shape_xi_raw"
    )


def test_a_positive_fit_above_the_clip_ceiling_still_reads_fat():
    """Clipping 1.67 down to 0.95 must not demote a fat fit to a withheld one."""
    verdict, basis = _fat_tail_verdict(
        xi_raw=1.671216, xi_constrained=GPD_SHAPE_CLIP_HIGH,
        excess_kurt=514.0, var_evt_loss=0.01, hist_var_loss=0.02,
    )
    assert verdict is True
    assert basis["gpd_shape_sign"] == "positive_heavy_tail"
    assert basis["gpd_shape_xi_was_clipped"] is True
    assert basis["gpd_shape_xi_fitted"] == pytest.approx(1.671216)
    assert basis["gpd_shape_xi_used_for_metrics"] == pytest.approx(0.95)


# --------------------------------------------------------------------------- #
# Preserved earlier contracts in the same payload.
# --------------------------------------------------------------------------- #

def test_unfitted_path_still_derives_fatness_from_kurtosis_alone():
    """The <5-exceedances path has no shape, so kurtosis is the whole basis."""
    r = pd.Series(np.random.default_rng(2).normal(0.0005, 0.02, 60))
    res = TailRiskService.calculate_evt_pot_var_es(
        r, confidence_level=0.99, threshold_quantile=0.95
    )
    assert res["model_fitted"] is False
    assert res["gpd_shape_xi"] is None
    kurt = float(stats.kurtosis(r.values))
    assert res["is_fat_tailed"] == bool(kurt > FAT_TAIL_EXCESS_KURTOSIS_THRESHOLD)
    basis = res["is_fat_tailed_basis"]
    assert basis["gpd_shape_sign"] == "not_fitted"
    assert basis["gpd_shape_xi_fitted"] is None


def test_the_existing_raw_constrained_used_triple_is_untouched():
    res = _evt(np.random.default_rng(2).normal(0.0005, 0.02, 520))
    # `gpd_shape_xi` stays the raw MLE headline; `gpd_shape_xi_used` stays the
    # 4dp rounded clipped value the moments came from.
    assert res["gpd_shape_xi"] == pytest.approx(
        round(res["gpd_shape_xi_raw"], 4)
    )
    assert res["gpd_shape_xi_used"] == pytest.approx(
        res["gpd_shape_xi_constrained"], abs=1e-4
    )
    assert res["gpd_shape_xi_basis"] in {"constrained_clip", "raw_mle"}
    assert res["model_fitted"] is True
    assert res["metrics_valid"] is True
    # constraint_reason is None when the fit needed no constraint, which is a
    # legitimate state, so it is only asserted to be present-or-absent rather
    # than forced.
    assert res["constraint_reason"] is None or isinstance(
        res["constraint_reason"], str
    )


def test_basis_and_withheld_reason_are_json_serialisable():
    """The block is exported to JSON, so a null verdict must survive encoding."""
    import json

    res = _evt(np.random.default_rng(2).normal(0.0005, 0.02, 520))
    encoded = json.dumps(res)
    decoded = json.loads(encoded)
    assert decoded["is_fat_tailed"] is None
    assert decoded["is_fat_tailed_basis"]["withheld_reason"]
