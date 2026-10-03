"""
Tail Risk Analytics & Extreme Value Theory (EVT) Service
Peaks-Over-Threshold (POT) Generalized Pareto Distribution modeling for 99% VaR/ES,
and Bivariate Student-t / Empirical Copula Lower-Tail Dependence Matrix.
"""

from typing import Any, Dict, Optional, Tuple, Union
import numpy as np
import pandas as pd
from scipy import stats

from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# --------------------------------------------------------------------------- #
# Fat-tail verdict: thresholds, sign convention, and the published rule.
# --------------------------------------------------------------------------- #
#
# `is_fat_tailed` used to be a bare disjunction of three heterogeneous
# measurements with nothing published saying which one fired:
#
#     xi_raw > 0.05  OR  excess_kurtosis > 0.5  OR  var_evt_loss > hist_var_loss
#
# A reader therefore saw `is_fat_tailed: true` published directly beside a
# NEGATIVE `gpd_shape_xi` and had no way to tell that the third clause - a
# comparison between two fitted loss numbers - was the one that had fired. A
# confidently wrong boolean is a worse outcome than an absent one, so the
# verdict is now derived under a stated rule, published with the basis that
# produced it, and WITHHELD whenever the fitted shape contradicts it.
#
# Sign convention, stated explicitly because GPD shape signs are NOT universal
# across parameterisations. This service fits the POT exceedances with
# `scipy.stats.genpareto`, whose pdf is f(x, c) = (1 + c*x)**(-1 - 1/c) with
# support "x >= 0 if c >= 0, and 0 <= x <= -1/c if c < 0", and for which
# c = 0 reduces to the exponential and c = -1 to the uniform on [0, 1]
# (SciPy 1.18 reference, scipy.stats.genpareto). Therefore in THIS
# parameterisation:
#
#     c < 0  ->  the support is bounded above at x = -1/c: a FINITE right
#                endpoint, so the tail is bounded and cannot be a fat tail
#     c = 0  ->  exponential tail
#     c > 0  ->  unbounded support with a power-law tail: a fat tail
#
# The same convention is corroborated from inside this service, not inferred
# from the distribution name: `pot_moments` treats the first moment as
# undefined at `shape >= 1.0`, which is only true of the standard
# Pickands-Balkema-de Haan xi convention that genpareto's c already is.
FAT_TAIL_SHAPE_THRESHOLD = 0.05
FAT_TAIL_EXCESS_KURTOSIS_THRESHOLD = 0.5

#: The shape clip the metrics are computed from. Its bounds straddle zero but
#: neither can be reached from the far side, so `clip` never changes the sign
#: of a fitted shape. A verdict therefore never has to guess whether the clip
#: turned a thin fit into a fat one, and a clipped shape is never read as if it
#: were the fitted value: the verdict reads `gpd_shape_xi_raw`.
GPD_SHAPE_CLIP_LOW = -0.5
GPD_SHAPE_CLIP_HIGH = 0.95

GPD_SHAPE_SIGN_RULE = (
    "sign convention is scipy.stats.genpareto, whose pdf is "
    "f(x, c) = (1 + c*x)**(-1 - 1/c) with support x >= 0 for c >= 0 and "
    "0 <= x <= -1/c for c < 0 (SciPy 1.18 reference, scipy.stats.genpareto). "
    "In that parameterisation a negative shape c < 0 places a FINITE upper "
    "endpoint -1/c on the tail, so a negative fitted shape is a BOUNDED tail "
    "and is the opposite of a fat tail; c = 0 is exponential; c > 0 is a "
    "power-law fat tail. The verdict below is read against that convention"
)
FAT_TAIL_VERDICT_RULE = (
    "is_fat_tailed is published so that it can never contradict the "
    "gpd_shape_xi_raw published beside it. Signals, each measured separately "
    "and each published with its own value: (1) gpd_shape_xi_raw > 0.05 -> "
    "fat, read from the RAW maximum-likelihood fit and never from the clipped "
    "gpd_shape_xi_used that the moments were computed from; (2) "
    "excess_kurtosis > 0.5 -> fat, a whole-sample central moment; (3) evt VaR "
    "loss > historical VaR loss -> fat, a comparison of a fitted quantile "
    "against an empirical one. These three measure different things (tail "
    "shape above the POT threshold, whole-sample kurtosis, fitted-vs-empirical "
    "quantile), so is_fat_tailed is: true when (1) or (2) fires and the shape "
    "does not contradict it; false when nothing fired; and null when the "
    "fitted shape is NEGATIVE and something else fired, because a bounded tail "
    "cannot be a fat tail and the other signals cannot settle it. "
    "is_fat_tailed_basis.fired_signals always names which signal or signals "
    "produced the verdict, and is withheld only alongside the measured values "
    "that made it uninformative. A shape inside +/-0.05 is recorded as "
    "'unclassifiable_near_exponential' rather than counted as evidence. "
    "Fewer verdicts is the correct answer here, not a substitute number"
)


def _fat_tail_shape_sign(xi_raw: Optional[float]) -> str:
    """Classify a fitted GPD shape under :data:`GPD_SHAPE_SIGN_RULE`."""
    if xi_raw is None:
        return "not_fitted"
    if xi_raw > FAT_TAIL_SHAPE_THRESHOLD:
        return "positive_heavy_tail"
    if xi_raw < -FAT_TAIL_SHAPE_THRESHOLD:
        return "negative_bounded_tail"
    return "unclassifiable_near_exponential"


def _fat_tail_verdict(
    *,
    xi_raw: Optional[float],
    xi_constrained: Optional[float],
    excess_kurt: float,
    var_evt_loss: float,
    hist_var_loss: float,
) -> Tuple[Optional[bool], Dict[str, Any]]:
    """Return ``(verdict, basis)`` for the fat-tail flag.

    ``verdict`` is ``None`` when the measurement does not support one, which is
    the same contract the vol-cone uses for a percentile rank it cannot
    resolve. ``basis`` is always populated - including when the verdict is
    withheld - so a reader can see how uninformative the withheld verdict was
    rather than seeing only an absence.
    """
    shape_sign = _fat_tail_shape_sign(xi_raw)
    shape_fired = shape_sign == "positive_heavy_tail"
    shape_contradicts = shape_sign == "negative_bounded_tail"
    kurt_fired = bool(excess_kurt > FAT_TAIL_EXCESS_KURTOSIS_THRESHOLD)
    var_fired = bool(var_evt_loss > hist_var_loss)
    shape_clipped = bool(
        xi_raw is not None
        and xi_constrained is not None
        and not np.isclose(xi_raw, xi_constrained)
    )

    fired: list[str] = []
    if shape_fired:
        fired.append("gpd_shape_xi_raw_above_threshold")
    if kurt_fired:
        fired.append("excess_kurtosis_above_threshold")
    if var_fired:
        fired.append("evt_var_exceeds_historical_var")

    withheld_reason: Optional[str] = None
    if shape_contradicts and fired:
        # The parameter sitting beside the flag says the tail is bounded, and
        # something else in the block says otherwise. Those signals measure
        # different things and this block cannot resolve which is right, so
        # withhold rather than assert either.
        withheld_reason = (
            f"withheld: the fitted GPD shape is negative "
            f"(gpd_shape_xi_raw = {float(xi_raw):.8f}), which under the "
            f"published scipy.stats.genpareto sign convention bounds the tail "
            f"at a finite endpoint and so contradicts a fat-tail verdict, yet "
            f"the other fat-tail signal(s) {', '.join(fired)} did fire. They "
            f"measure different things - fitted tail shape above the POT "
            f"threshold, whole-sample kurtosis, and fitted-vs-empirical "
            f"quantile - and this block does not resolve the disagreement, so "
            f"no verdict is published"
        )
        verdict: Optional[bool] = None
    elif shape_fired or kurt_fired:
        # Reached only when the shape is fat, or when it is unclassifiable near
        # the exponential / absent entirely, so nothing published beside the
        # flag contradicts it. `fired_signals` names which signal won.
        verdict = True
    else:
        # Measured, and nothing fired. A False here rests on real numbers -
        # the shape band and the kurtosis were both computed - and agrees with
        # the shape published beside it, so it is not a stand-in for
        # "not computed". Unfitness publishes shape_sign="not_fitted" so a
        # reader can see the verdict rested on kurtosis alone.
        verdict = False

    basis: Dict[str, Any] = {
        "rule": FAT_TAIL_VERDICT_RULE,
        "sign_convention": GPD_SHAPE_SIGN_RULE,
        "gpd_shape_xi_fitted": None if xi_raw is None else round(float(xi_raw), 8),
        "gpd_shape_xi_fitted_field": "gpd_shape_xi_raw",
        "gpd_shape_xi_used_for_metrics": (
            None if xi_constrained is None else round(float(xi_constrained), 8)
        ),
        "gpd_shape_xi_was_clipped": shape_clipped,
        "gpd_shape_sign": shape_sign,
        "gpd_shape_xi_threshold": FAT_TAIL_SHAPE_THRESHOLD,
        "excess_kurtosis": round(float(excess_kurt), 6),
        "excess_kurtosis_threshold": FAT_TAIL_EXCESS_KURTOSIS_THRESHOLD,
        "evt_var_exceeds_historical_var": var_fired,
        "fired_signals": fired,
        "verdict": verdict,
        "withheld_reason": withheld_reason,
    }
    return verdict, basis


# --------------------------------------------------------------------------- #
# Tail dependence: the two quantities that must never be substituted.
# --------------------------------------------------------------------------- #
# `rho` is Pearson correlation of the paired raw legs, and `lambda_L` is a
# function of it. Both are undefined - not zero - in two situations, and both
# used to be filled with a number that passed every downstream check:
#
# 1. A CONSTANT leg. Pearson correlation there is 0/0: there is no measurement.
#    The code published rho = 0.0, which is the strongest claim available -
#    "no relationship whatsoever" - the exact opposite of unknown. It then fed
#    `lambda_L` through the copula formula into a published N x N matrix and
#    into the LOW risk band. A frozen leg looked like an independent one.
#
#    The dispersion guard is `np.ptp(...) > 0`, not `np.std(...) > 0`. The
#    latter is not a test: `np.full(300, 0.004)` is a constant series whose
#    sample std is 8.67e-19 (0.004 is not exactly representable), so the noise
#    passed the guard and a frozen leg was published as rho ~ 0. Peak-to-peak
#    range is exactly 0.0 for a constant series whatever the level's
#    representation, and needs no tolerance.
#
# 2. A FAILED Student-t fit. The code substituted nu = 4.0, and 4.0 sits INSIDE
#    the [2.1, 30.0] clip range the successful path is clamped to, so the
#    stand-in was indistinguishable from a fit and was published as
#    degrees_of_freedom: 4.0 with nothing marking it.
#
# 3. A NON-FINITE leg. This one was only half-fixed: the dispersion guard moved
#    from `np.std(...) > 0` to `np.ptp(...) > 0` (above) but the missing
#    `np.isfinite(rho)` half never landed. A +/-inf passes `ptp > 0` with
#    ptp == inf -- and such a leg is real: `dropna()` drops NaN, not -inf, and
#    `prices.pct_change(fill_method=None)` emits inf from a zero denominator.
#    Pearson over it is NaN, `np.clip` propagates NaN unchanged, and every
#    comparison against NaN is False -- so the band chain fell through to LOW
#    and the pair was never named in `unmeasurable_pairs`. A pair nobody could
#    measure was published under a risk band. The computation is now contained
#    in `np.errstate` too, so the arithmetic runs to completion and the
#    finiteness tests below are the decision point. The suite does NOT promote
#    RuntimeWarning to an error -- that was tried and reverted (see
#    pyproject.toml) -- so this is not here to satisfy a filter. It is here so
#    that a caller which DOES elevate RuntimeWarning still gets the refusal
#    rather than a 500, which is the same substitution by way of an exception
#    instead of a LOW band.
#    It is withheld under its OWN reason, `non_finite_leg`, because the whole
#    point of `unmeasurable_pairs` is to say WHICH pair and WHY: told
#    `zero_dispersion_leg`, a reader goes looking for a frozen series that is
#    not there while the actual defect is a non-finite number upstream.
#
# The idiom is the GPD fit's own, in `calculate_evt_pot_var_es`: withhold the
# value, and publish why. A `0.0` or a `4.0` standing where no measurement
# exists is worse than an absence, because a reader cannot tell it apart from
# one.
TAIL_DEPENDENCE_ZERO_DISPERSION = "zero_dispersion_leg"
TAIL_DEPENDENCE_T_FIT_FAILED = "marginal_t_fit_failed"
TAIL_DEPENDENCE_NON_FINITE_LEG = "non_finite_leg"

TAIL_DEPENDENCE_RULE = (
    "linear_correlation is Pearson rho of the paired raw legs and "
    "lower_tail_lambda is the Student-t copula lower-tail coefficient "
    "lambda_L = 2 * t_{nu+1}( -sqrt( (nu+1)(1-rho)/(1+rho) ) ), which is a "
    "function of rho and of the marginal Student-t degrees of freedom nu. Both "
    "are published only when measured. A leg with no dispersion (constant "
    "series: peak-to-peak range exactly 0) has an undefined correlation, so "
    "rho is null rather than 0.0 - 0.0 would be the strongest available claim, "
    "'no relationship whatsoever', and it is the opposite of unknown - and "
    "lambda_L is null with it. A failed or non-finite marginal Student-t fit "
    "leaves nu null rather than a stand-in inside the [2.1, 30.0] clip range, "
    "and lambda_L is null with it because the formula needs nu. A leg carrying "
    "a non-finite observation also leaves rho null, under its OWN reason: the "
    "dispersion guard only tests the peak-to-peak range, which such a leg "
    "satisfies with an infinite range, and Pearson correlation over it is NaN "
    "rather than a number - NaN is not a measurement and every comparison "
    "against it is False. That pair is named non_finite_leg, never "
    "zero_dispersion_leg: the two are different defects with different fixes, "
    "and a reader told to look for a frozen series would not find one. Where a "
    "pair fails both tests, non_finite_leg is published, because it names the "
    "input defect that has to be fixed before anything else is measurable. "
    "unmeasurable_pairs[].reason is one of exactly three tokens, named here so "
    "a reader holding a payload can match it to its cause: "
    "'zero_dispersion_leg' (a leg with no dispersion), "
    "'marginal_t_fit_failed' (the marginal Student-t fit produced no usable df), "
    "'non_finite_leg' (a leg carried a non-finite observation, or the pair's "
    "correlation arithmetic did not produce a finite number). A reason outside "
    "that set is a bug in the service, not a new cause. "
    "unmeasurable_pairs names every pair that was withheld and why; the "
    "corresponding matrix cell is null, which cannot be confused with a "
    "measured 0.0. Withheld pairs are excluded from high_tail_risk_pairs "
    "because that list filters on lower_tail_lambda >= 0.20, so a pair with no "
    "lambda cannot be a member. Fewer numbers is the correct answer here, not "
    "a substitute"
)


class TailRiskService:
    """
    Institutional tail-risk suite implementing:
    1. EVT-POT (Peaks-Over-Threshold) confidence-level VaR and Expected Shortfall via Generalized Pareto Distribution (GPD).
    2. Bivariate Student-t Copula Lower-Tail Dependence Coefficient matrix (lambda_L).
    """

    @staticmethod
    def calculate_evt_pot_var_es(
        returns: Union[pd.Series, np.ndarray],
        confidence_level: float = 0.99,
        threshold_quantile: float = 0.95,
    ) -> Dict[str, Any]:
        """Calculate configurable EVT-POT VaR/ES with fit disclosure.

        The raw fitted GPD shape and scale are retained.  Numerical guards are
        applied only to a separately named constrained estimate used for the
        reported risk metrics, so a clipped value is never mislabeled as the
        raw MLE fit.
        """
        if isinstance(returns, pd.Series):
            r = returns.to_numpy(dtype=float)
        else:
            r = np.asarray(returns, dtype=float)
        r = r[np.isfinite(r)]

        try:
            confidence_level = float(confidence_level)
            threshold_quantile = float(threshold_quantile)
        except (TypeError, ValueError) as exc:
            raise ValueError("confidence_level and threshold_quantile must be finite") from exc
        if not np.isfinite(confidence_level) or not 0.0 < confidence_level < 1.0:
            raise ValueError("confidence_level must be finite and between 0 and 1")
        if not np.isfinite(threshold_quantile) or not 0.0 < threshold_quantile < 1.0:
            raise ValueError("threshold_quantile must be finite and between 0 and 1")

        n_total = len(r)
        if n_total < 20:
            # Never fabricate tail numbers: EVT-POT needs enough data to clear
            # the threshold with fittable exceedances.
            raise ValueError(
                f"Insufficient observations for EVT-POT (need >= 20, got {n_total})"
            )

        if threshold_quantile >= confidence_level:
            raise ValueError(
                f"threshold_quantile ({threshold_quantile}) must be < "
                f"confidence_level ({confidence_level})"
            )

        # Daily loss series: positive values are losses.
        losses = -r
        alpha = 1.0 - confidence_level

        hist_var_loss = float(np.percentile(losses, confidence_level * 100.0))
        tail_losses = losses[losses >= hist_var_loss]
        hist_es_loss = float(np.mean(tail_losses)) if len(tail_losses) > 0 else hist_var_loss

        threshold_u = float(np.percentile(losses, threshold_quantile * 100.0))
        exceedances = losses[losses > threshold_u] - threshold_u
        n_u = len(exceedances)

        def pot_moments(shape: float, scale: float) -> Tuple[float, float]:
            """Return finite POT first/second moments, or NaN when undefined."""
            try:
                if not np.isfinite(shape) or not np.isfinite(scale) or scale <= 0.0 or shape >= 1.0:
                    return float("nan"), float("nan")
                ratio = (n_total / n_u) * alpha
                if abs(shape) > 1e-6:
                    var_loss = threshold_u + (scale / shape) * (ratio ** (-shape) - 1.0)
                else:
                    var_loss = threshold_u - scale * np.log(ratio)
                es_loss = (var_loss + scale - shape * threshold_u) / (1.0 - shape)
                if not np.isfinite(var_loss) or not np.isfinite(es_loss):
                    return float("nan"), float("nan")
                return float(var_loss), float(es_loss)
            except (ArithmeticError, FloatingPointError, ValueError):
                return float("nan"), float("nan")

        xi_raw: Optional[float] = None
        beta_raw: Optional[float] = None
        xi_constrained: Optional[float] = None
        beta_constrained: Optional[float] = None
        raw_var_loss: Optional[float] = None
        raw_es_loss: Optional[float] = None
        var_evt_loss = hist_var_loss
        es_evt_loss = hist_es_loss
        model_fitted = False
        metrics_valid = False
        constraint_reasons: list[str] = []

        if n_u < 5:
            constraint_reasons.append("insufficient_exceedances")
        else:
            try:
                # scipy.stats.genpareto: c is the raw shape (xi), scale is beta.
                c_est, _loc_est, scale_est = stats.genpareto.fit(exceedances, floc=0.0)
                xi_raw = float(c_est)
                beta_raw = float(scale_est)
                model_fitted = True
                metrics_valid = bool(np.isfinite(xi_raw) and np.isfinite(beta_raw) and beta_raw > 0.0)

                # A finite ES requires xi < 1.  The lower bound is a
                # stability guard for extreme heavy-tail extrapolation; it is
                # deliberately separate from the raw fit and is disclosed.
                xi_constrained = float(
                    np.clip(xi_raw, GPD_SHAPE_CLIP_LOW, GPD_SHAPE_CLIP_HIGH)
                )
                beta_constrained = float(max(beta_raw, 1e-6))
                if not np.isclose(xi_constrained, xi_raw):
                    constraint_reasons.append("gpd_shape_clipped")
                if beta_constrained != beta_raw:
                    constraint_reasons.append("gpd_scale_floor")

                raw_var_loss, raw_es_loss = pot_moments(xi_raw, beta_raw)
                constrained_var_loss, constrained_es_loss = pot_moments(
                    xi_constrained, beta_constrained
                )
                if not np.isfinite(constrained_var_loss) or not np.isfinite(constrained_es_loss):
                    raise ValueError("constrained GPD moments are not finite")

                # Preserve the existing conservative monotonicity/floor
                # behavior, but expose the unconstrained moments alongside it.
                var_evt_loss = max(
                    constrained_var_loss,
                    threshold_u,
                    hist_var_loss * 0.9,
                )
                es_evt_loss = constrained_es_loss
                if var_evt_loss > constrained_var_loss + 1e-15:
                    constraint_reasons.append("var_floor")
                # Keep this exact guard visible in the source: no cosmetic
                # five-percent ES gap is introduced here.
                es_evt_loss = max(es_evt_loss, var_evt_loss)
                if es_evt_loss > constrained_es_loss + 1e-15:
                    constraint_reasons.append("es_monotonicity")
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"GPD fit failed ({e}); reporting historical-only tail metrics "
                    f"(model_fitted=False)"
                )
                xi_raw = None
                beta_raw = None
                xi_constrained = None
                beta_constrained = None
                model_fitted = False
                metrics_valid = False
                var_evt_loss = hist_var_loss
                es_evt_loss = hist_es_loss
                constraint_reasons = ["fit_failed"]

        # A fitted raw shape is still not a valid first-moment EVT estimate when
        # xi >= 1.  Keep the constrained metrics available, but disclose that
        # validity rather than silently calling the extrapolation valid.
        if xi_raw is not None and xi_raw >= 1.0:
            metrics_valid = False
            constraint_reasons.append("raw_first_moment_undefined")

        excess_kurt = float(stats.kurtosis(r)) if n_total > 4 else 0.0
        is_fat_tailed, fat_tail_basis = _fat_tail_verdict(
            xi_raw=xi_raw if model_fitted else None,
            xi_constrained=xi_constrained,
            excess_kurt=excess_kurt,
            var_evt_loss=var_evt_loss,
            hist_var_loss=hist_var_loss,
        )

        neutral = {
            "evt_pot_var": round(-float(var_evt_loss), 6),
            "evt_pot_es": round(-float(es_evt_loss), 6),
            "historical_var": round(-float(hist_var_loss), 6),
            "historical_es": round(-float(hist_es_loss), 6),
        }
        constraint_applied = any(
            reason in {
                "gpd_shape_clipped",
                "gpd_scale_floor",
                "var_floor",
                "es_monotonicity",
                "raw_first_moment_undefined",
            }
            for reason in constraint_reasons
        )
        result: Dict[str, Any] = {
            "confidence_level": round(confidence_level, 4),
            **neutral,
            "evt_pot_var_unconstrained": (
                round(-float(raw_var_loss), 6) if raw_var_loss is not None else None
            ),
            "evt_pot_es_unconstrained": (
                round(-float(raw_es_loss), 6) if raw_es_loss is not None else None
            ),
            "threshold_u": round(float(threshold_u), 6),
            # Headline shape is the raw MLE fit, never the clipped stability
            # estimate. The two are published side by side so a reader can see
            # which one the EVT metrics used, and which one was clipped.
            "gpd_shape_xi": round(float(xi_raw), 4) if xi_raw is not None else None,
            "gpd_shape_xi_used": (
                round(float(xi_constrained), 4) if xi_constrained is not None else None
            ),
            "gpd_shape_xi_basis": (
                "constrained_clip" if xi_constrained is not None else "raw_mle"
            ),
            "gpd_shape_xi_raw": round(float(xi_raw), 8) if xi_raw is not None else None,
            "gpd_shape_xi_constrained": (
                round(float(xi_constrained), 8) if xi_constrained is not None else None
            ),
            # Scale is symmetric with the shape above: the headline is the value
            # the EVT metrics actually used.
            "gpd_scale_beta": round(float(beta_constrained), 6) if beta_constrained is not None else None,
            "gpd_scale_beta_raw": round(float(beta_raw), 6) if beta_raw is not None else None,
            "gpd_scale_beta_constrained": (
                round(float(beta_constrained), 6) if beta_constrained is not None else None
            ),
            "gpd_shape_constrained": bool(
                xi_raw is not None and xi_constrained is not None
                and not np.isclose(xi_raw, xi_constrained)
            ),
            "constraint_applied": constraint_applied,
            "metrics_constrained": constraint_applied,
            "metrics_valid": bool(metrics_valid),
            "raw_fit_valid": bool(metrics_valid),
            "constrained_metrics_valid": bool(
                np.isfinite(var_evt_loss) and np.isfinite(es_evt_loss)
            ),
            "constraint_reason": ",".join(constraint_reasons) if constraint_reasons else None,
            "model_fitted": model_fitted,
            "exceedances_count": int(n_u),
            "total_observations": int(n_total),
            "is_fat_tailed": is_fat_tailed,
            # The flag is a verdict, so it ships with the measurement it was
            # derived from. A reader can now check it against the shape beside
            # it instead of having to guess which of three signals fired.
            "is_fat_tailed_basis": fat_tail_basis,
            "is_fat_tailed_withheld_reason": fat_tail_basis["withheld_reason"],
        }

        # Preserve the established 99%-named contract only for the actual 99%
        # default.  Arbitrary configurable levels use neutral names exclusively.
        if confidence_level == 0.99:
            result.update(
                {
                    "evt_pot_var_99": neutral["evt_pot_var"],
                    "evt_pot_es_99": neutral["evt_pot_es"],
                    "historical_var_99": neutral["historical_var"],
                    "historical_es_99": neutral["historical_es"],
                }
            )
        return result

    @staticmethod
    def calculate_bivariate_tail_dependence(
        returns_a: Union[pd.Series, np.ndarray],
        returns_b: Union[pd.Series, np.ndarray],
        marginal_df_a: Optional[float] = None,
        marginal_df_b: Optional[float] = None,
    ) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[str]]:
        """
        Calculate Bivariate Student-t Copula Lower Tail Dependence Coefficient (lambda_L).

        Formula:
            lambda_L = 2 * t_{nu + 1}( - sqrt( (nu + 1) * (1 - rho) / (1 + rho) ) )

        Parameters
        ----------
        returns_a : pd.Series or np.ndarray
            Returns series of asset A.
        returns_b : pd.Series or np.ndarray
            Returns series of asset B.
        marginal_df_a, marginal_df_b : Optional[float]
            Pre-fitted marginal Student-t degrees of freedom for A and B
            (fit once per ticker by the matrix caller). When omitted, each
            series is fitted here (two fits per call).

        Returns
        -------
        Tuple[Optional[float], Optional[float], Optional[float], Optional[str]]
            (lambda_L, linear_correlation, degrees_of_freedom,
            unmeasurable_reason)

            Any of the first three is ``None`` when it was not measured, and
            ``unmeasurable_reason`` then names which input was missing -
            ``"zero_dispersion_leg"``, ``"marginal_t_fit_failed"`` or
            ``"non_finite_leg"`` - or is ``None`` when everything was measured.
            This is the tuple form of the same contract the GPD fit publishes
            as ``model_fitted=False`` plus a ``constraint_reason``.

        Notes
        -----
        nu is a univariate Student-t MLE on each raw return series (the t
        scale absorbs location/scale, so no standardization is needed), then
        averaged across the pair and used as the copula dependence df — an
        approximation, not a joint copula fit. rho is Pearson correlation of
        the raw pair, used directly in the copula formula. A failed t fit
        publishes ``nu = None``, not a stand-in df: lambda_L is a function of
        nu, so it is withheld with it. A constant leg publishes ``rho = None``,
        not 0.0, for the reason set out in :data:`TAIL_DEPENDENCE_RULE`, and so
        does a leg carrying a non-finite observation: Pearson correlation over
        such a leg is NaN, which is not a measurement and which every
        comparison would silently pass as "no relationship".
        """
        df_paired = pd.DataFrame({"a": returns_a, "b": returns_b}).dropna()
        if len(df_paired) < 10:
            raise ValueError(
                "Insufficient overlapping observations for tail dependence "
                f"(need >= 10, got {len(df_paired)})"
            )

        r_a = df_paired["a"].values
        r_b = df_paired["b"].values

        # Linear correlation rho, and WHICH failure withheld it if it did.
        #
        # The two causes are named separately because they are different defects
        # with different fixes, and `unmeasurable_pairs` exists to say which:
        # `zero_dispersion_leg` sends a reader looking for a frozen series, and
        # `non_finite_leg` sends them looking for a zero denominator upstream in
        # `pct_change`. Collapsing them would publish a cause the code never
        # checked for. Where both apply, the non-finite label wins: it names the
        # input defect that has to be fixed before anything else is measurable.
        #
        # The measurement is wrapped in np.errstate because a leg carrying a
        # non-finite or an overflowing observation makes numpy warn
        # mid-computation. The suite does NOT promote RuntimeWarning to an
        # error -- that was tried and reverted (see pyproject.toml) -- so this
        # is not here to satisfy a filter. It is here so the arithmetic runs to
        # completion and the finiteness tests BELOW get to be the decision
        # point: for these inputs the warning is the expected outcome rather
        # than news, and it would otherwise be emitted for a pair the function
        # is built to refuse. It also holds for any caller that does elevate
        # RuntimeWarning, so a legitimately REFUSABLE pair stays a refusal
        # there instead of becoming a 500. The finiteness tests below are the
        # decision point; the warning is not.
        rho: Optional[float] = None
        rho_withheld_reason: Optional[str] = None
        with np.errstate(invalid="ignore", over="ignore"):
            if not (np.isfinite(r_a).all() and np.isfinite(r_b).all()):
                # A leg carrying a +/-inf -- which `dropna()` keeps, and which
                # `prices.pct_change(fill_method=None)` really does emit from a
                # zero denominator -- has no measurable correlation. It is not
                # caught by the dispersion guard either: `np.ptp` of such a leg
                # is `inf`, which passes `> 0`.
                rho_withheld_reason = TAIL_DEPENDENCE_NON_FINITE_LEG
            elif np.ptp(r_a) > 0 and np.ptp(r_b) > 0:
                # Peak-to-peak range, not std: see the module note on
                # TAIL_DEPENDENCE_RULE.
                measured = float(np.clip(np.corrcoef(r_a, r_b)[0, 1], -0.9999, 0.9999))
                if np.isfinite(measured):
                    rho = measured
                else:
                    # Finite legs whose correlation arithmetic still overflowed:
                    # np.clip propagates NaN, so a non-finite result arrives here
                    # as NaN rather than as the clip bound, and the clip is not a
                    # repair. NaN is not a measurement -- every comparison against
                    # it is False, so it used to fall through the band chain into
                    # LOW and out of `unmeasurable_pairs`.
                    rho_withheld_reason = TAIL_DEPENDENCE_NON_FINITE_LEG
            else:
                rho_withheld_reason = TAIL_DEPENDENCE_ZERO_DISPERSION

        # Degrees of freedom: caller-cached marginal fits, else fit here.
        nu: Optional[float]
        if marginal_df_a is not None and marginal_df_b is not None:
            nu = float(np.clip((marginal_df_a + marginal_df_b) / 2.0, 2.1, 30.0))
        else:
            try:
                df_a, _, _ = stats.t.fit(r_a)
                df_b, _, _ = stats.t.fit(r_b)
                nu = float(np.clip((df_a + df_b) / 2.0, 2.1, 30.0))
            except Exception:
                # No substitution. nu = 4.0 sat inside the [2.1, 30.0] clip the
                # successful path is clamped to, so it cleared every downstream
                # plausibility check and was published as if it had been fitted.
                nu = None
        if nu is not None and not np.isfinite(nu):
            # np.clip propagates NaN, so a non-finite marginal df arrives here
            # as NaN rather than as the clip bound. A NaN df is not a measurement.
            nu = None

        # Copula lower-tail dependence formula
        lambda_l: Optional[float]
        unmeasurable_reason: Optional[str]
        if rho is None:
            lambda_l = None
            # Whatever the rho block above found, not a single answer for every
            # way the correlation can fail to exist.
            unmeasurable_reason = rho_withheld_reason
        elif nu is None:
            lambda_l = None
            unmeasurable_reason = TAIL_DEPENDENCE_T_FIT_FAILED
        elif rho <= -0.999:
            lambda_l = 0.0
            unmeasurable_reason = None
        elif rho >= 0.999:
            lambda_l = 1.0
            unmeasurable_reason = None
        else:
            arg = -np.sqrt(((nu + 1.0) * (1.0 - rho)) / (1.0 + rho))
            lambda_l = float(2.0 * stats.t.cdf(arg, df=nu + 1.0))
            unmeasurable_reason = None

        if lambda_l is not None:
            lambda_l = float(np.clip(lambda_l, 0.0, 1.0))
        return lambda_l, rho, nu, unmeasurable_reason

    @classmethod
    def calculate_tail_dependence_matrix(
        cls,
        returns_df: pd.DataFrame,
    ) -> Dict[str, Any]:
        """
        Compute symmetric N x N Lower-Tail Dependence Matrix and identify high tail-risk pairs.

        Parameters
        ----------
        returns_df : pd.DataFrame
            DataFrame of asset returns (columns are ticker symbols).

        Returns
        -------
        Dict[str, Any]
            Dictionary compliant with TailDependenceMatrix schema, plus
            ``unmeasurable_pairs``: the pairs whose correlation could not be
            measured, each with the reason. A withheld pair publishes a ``null``
            matrix cell, is excluded from ``high_tail_risk_pairs`` (which
            filters on ``lower_tail_lambda >= 0.20``, and there is no lambda to
            compare), and is named in ``unmeasurable_pairs`` so its absence is
            readable rather than looking like a zero. See
            :data:`TAIL_DEPENDENCE_RULE`.
        """
        tickers = list(returns_df.columns)
        n = len(tickers)

        if n == 0:
            return {
                "tickers": [],
                "matrix": [],
                "high_tail_risk_pairs": [],
                "unmeasurable_pairs": [],
            }

        if n == 1:
            return {
                "tickers": tickers,
                "matrix": [[1.0]],
                "high_tail_risk_pairs": [],
                "unmeasurable_pairs": [],
            }

        matrix = np.eye(n, dtype=float)
        pairs_list = []
        unmeasurable_pairs = []

        # Fit marginal t df once per ticker (O(n) fits instead of O(n²) —
        # each scipy t-fit is tens of hundreds of ms, previously the source
        # of the multi-second first /tails call). On NaN-free frames this is
        # bit-identical to the old per-pair fit.
        marginal_dfs: Dict[str, Optional[float]] = {}
        for t in tickers:
            col = returns_df[t].dropna().to_numpy(dtype=float)
            col = col[np.isfinite(col)]
            if col.size >= 10:
                try:
                    marginal_dfs[t] = float(stats.t.fit(col)[0])
                except Exception:
                    marginal_dfs[t] = None
            else:
                marginal_dfs[t] = None

        for i in range(n):
            for j in range(i + 1, n):
                t_i = tickers[i]
                t_j = tickers[j]
                lambda_l, rho, nu, unmeasurable_reason = (
                    cls.calculate_bivariate_tail_dependence(
                        returns_df[t_i],
                        returns_df[t_j],
                        marginal_df_a=marginal_dfs[t_i],
                        marginal_df_b=marginal_dfs[t_j],
                    )
                )

                # NaN, deliberately: the matrix is a float array and the cell
                # has to stay "no measurement" all the way through to the JSON
                # conversion below. A builtin min/max would swallow it.
                cell = np.nan if lambda_l is None else lambda_l
                matrix[i, j] = cell
                matrix[j, i] = cell

                if lambda_l is None:
                    # An unmeasurable pair has no band. "LOW" would be a
                    # verdict on a quantity nobody measured.
                    category = "UNMEASURABLE"
                    unmeasurable_pairs.append({
                        "pair": [t_i, t_j],
                        "reason": unmeasurable_reason,
                    })
                elif lambda_l >= 0.50:
                    category = "VERY_HIGH"
                elif lambda_l >= 0.35:
                    category = "HIGH"
                elif lambda_l >= 0.20:
                    category = "MODERATE"
                else:
                    category = "LOW"

                pairs_list.append({
                    "pair": [t_i, t_j],
                    "lower_tail_lambda": round(lambda_l, 4) if lambda_l is not None else None,
                    "linear_correlation": round(rho, 4) if rho is not None else None,
                    "degrees_of_freedom": round(nu, 2) if nu is not None else None,
                    "risk_category": category,
                })

        # Sort pairs by lower_tail_lambda descending, measured pairs first and
        # withheld ones after them in discovery order. Comparing None with a
        # float is a TypeError, and flattening them onto one scale would put a
        # missing measurement in a position that reads as a rank.
        pairs_list = sorted(
            (p for p in pairs_list if p["lower_tail_lambda"] is not None),
            key=lambda p: p["lower_tail_lambda"],
            reverse=True,
        ) + [p for p in pairs_list if p["lower_tail_lambda"] is None]

        # High tail risk pairs: lambda >= 0.20 only. Never backfill with
        # lower-risk pairs — an empty list honestly means "none found".
        high_risk_pairs = [
            p for p in pairs_list
            if p["lower_tail_lambda"] is not None and p["lower_tail_lambda"] >= 0.20
        ]

        # Convert matrix to rounded list of lists. NaN is the withheld cell and
        # must survive to the wire as null: round(nan, 4) is nan, and a bare
        # nan would serialise as a JSON-invalid NaN rather than as an absence.
        matrix_list = [
            [
                None if np.isnan(matrix[r, c]) else round(float(matrix[r, c]), 4)
                for c in range(n)
            ]
            for r in range(n)
        ]

        return {
            "tickers": tickers,
            "matrix": matrix_list,
            "high_tail_risk_pairs": high_risk_pairs,
            "unmeasurable_pairs": unmeasurable_pairs,
            "unmeasurable_pairs_rule": TAIL_DEPENDENCE_RULE,
        }

    @classmethod
    def calculate_full_tail_risk_suite(
        cls,
        returns_df: pd.DataFrame,
        weights: Optional[Dict[str, float]] = None,
        as_of: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute full tail risk analysis: EVT-POT VaR/ES on portfolio return and Copula Tail Dependence.

        Parameters
        ----------
        returns_df : pd.DataFrame
            DataFrame of asset returns.
        weights : Optional[Dict[str, float]]
            Portfolio allocation weights.
        as_of : Optional[str]
            As-of date string (YYYY-MM-DD).

        Returns
        -------
        Dict[str, Any]
            Full TailRiskResponse payload.
        """
        if as_of is None:
            if isinstance(returns_df.index, pd.DatetimeIndex) and len(returns_df.index) > 0:
                as_of = str(returns_df.index[-1])[:10]
            else:
                as_of = pd.Timestamp.now().strftime("%Y-%m-%d")

        # Compute weighted portfolio returns with the same active-mask rule as
        # AnalyticsEngine.  Missing/pre-listing observations are not economic
        # zeroes; available positive weights are renormalised per date.
        clean_returns = returns_df.replace([np.inf, -np.inf], np.nan)
        if weights is None or len(weights) == 0:
            candidate_weights = pd.Series(1.0, index=clean_returns.columns)
        else:
            candidate_weights = pd.Series(weights, dtype=float)
            candidate_weights = candidate_weights[
                [c for c in candidate_weights.index if c in clean_returns.columns]
            ]
            candidate_weights = candidate_weights[
                np.isfinite(candidate_weights) & (candidate_weights > 0.0)
            ]
        weight_frame = candidate_weights.reindex(clean_returns.columns, fill_value=0.0)
        active = clean_returns.notna() & (weight_frame > 0.0)
        active_weight = active.mul(weight_frame, axis=1).sum(axis=1)
        numerator = clean_returns.where(active, 0.0).mul(weight_frame, axis=1).sum(axis=1)
        portfolio_returns = numerator.loc[active_weight > 0.0] / active_weight.loc[active_weight > 0.0]

        # 1. EVT POT VaR/ES
        evt_var_metrics = cls.calculate_evt_pot_var_es(portfolio_returns, confidence_level=0.99, threshold_quantile=0.95)

        # 2. Copula Lower-Tail Dependence Matrix
        tail_dep_matrix = cls.calculate_tail_dependence_matrix(returns_df)

        return {
            "as_of": as_of,
            "evt_var": evt_var_metrics,
            "tail_dependence_matrix": tail_dep_matrix,
        }
