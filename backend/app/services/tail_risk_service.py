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
                xi_constrained = float(np.clip(xi_raw, -0.5, 0.95))
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
        if model_fitted:
            is_fat_tailed = bool(
                (xi_raw is not None and xi_raw > 0.05)
                or excess_kurt > 0.5
                or var_evt_loss > hist_var_loss
            )
        else:
            is_fat_tailed = bool(excess_kurt > 0.5)

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
            # This field is intentionally the raw MLE fit, never the clipped
            # stability estimate.
            "gpd_shape_xi": round(float(xi_raw), 4) if xi_raw is not None else None,
            "gpd_shape_xi_raw": round(float(xi_raw), 8) if xi_raw is not None else None,
            "gpd_shape_xi_constrained": (
                round(float(xi_constrained), 8) if xi_constrained is not None else None
            ),
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
    ) -> Tuple[float, float, float]:
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
        Tuple[float, float, float]
            (lambda_L, linear_correlation, degrees_of_freedom)

        Notes
        -----
        nu is a univariate Student-t MLE on each raw return series (the t
        scale absorbs location/scale, so no standardization is needed), then
        averaged across the pair and used as the copula dependence df — an
        approximation, not a joint copula fit. rho is Pearson correlation of
        the raw pair, used directly in the copula formula.
        """
        df_paired = pd.DataFrame({"a": returns_a, "b": returns_b}).dropna()
        if len(df_paired) < 10:
            raise ValueError(
                "Insufficient overlapping observations for tail dependence "
                f"(need >= 10, got {len(df_paired)})"
            )

        r_a = df_paired["a"].values
        r_b = df_paired["b"].values

        # Linear correlation rho
        if np.std(r_a) > 0 and np.std(r_b) > 0:
            rho = float(np.corrcoef(r_a, r_b)[0, 1])
        else:
            rho = 0.0
        rho = float(np.clip(rho, -0.9999, 0.9999))

        # Degrees of freedom: caller-cached marginal fits, else fit here.
        if marginal_df_a is not None and marginal_df_b is not None:
            nu = float(np.clip((marginal_df_a + marginal_df_b) / 2.0, 2.1, 30.0))
        else:
            try:
                df_a, _, _ = stats.t.fit(r_a)
                df_b, _, _ = stats.t.fit(r_b)
                nu = float(np.clip((df_a + df_b) / 2.0, 2.1, 30.0))
            except Exception:
                nu = 4.0

        # Copula lower-tail dependence formula
        if rho <= -0.999:
            lambda_l = 0.0
        elif rho >= 0.999:
            lambda_l = 1.0
        else:
            arg = -np.sqrt(((nu + 1.0) * (1.0 - rho)) / (1.0 + rho))
            lambda_l = float(2.0 * stats.t.cdf(arg, df=nu + 1.0))

        lambda_l = float(np.clip(lambda_l, 0.0, 1.0))
        return lambda_l, rho, nu

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
            Dictionary compliant with TailDependenceMatrix schema.
        """
        tickers = list(returns_df.columns)
        n = len(tickers)

        if n == 0:
            return {
                "tickers": [],
                "matrix": [],
                "high_tail_risk_pairs": [],
            }

        if n == 1:
            return {
                "tickers": tickers,
                "matrix": [[1.0]],
                "high_tail_risk_pairs": [],
            }

        matrix = np.eye(n, dtype=float)
        pairs_list = []

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
                lambda_l, rho, nu = cls.calculate_bivariate_tail_dependence(
                    returns_df[t_i],
                    returns_df[t_j],
                    marginal_df_a=marginal_dfs[t_i],
                    marginal_df_b=marginal_dfs[t_j],
                )

                matrix[i, j] = lambda_l
                matrix[j, i] = lambda_l

                # Determine risk category
                if lambda_l >= 0.50:
                    category = "VERY_HIGH"
                elif lambda_l >= 0.35:
                    category = "HIGH"
                elif lambda_l >= 0.20:
                    category = "MODERATE"
                else:
                    category = "LOW"

                pairs_list.append({
                    "pair": [t_i, t_j],
                    "lower_tail_lambda": round(lambda_l, 4),
                    "linear_correlation": round(rho, 4),
                    "degrees_of_freedom": round(nu, 2),
                    "risk_category": category,
                })

        # Sort pairs by lower_tail_lambda descending
        pairs_list.sort(key=lambda p: p["lower_tail_lambda"], reverse=True)

        # High tail risk pairs: lambda >= 0.20 only. Never backfill with
        # lower-risk pairs — an empty list honestly means "none found".
        high_risk_pairs = [p for p in pairs_list if p["lower_tail_lambda"] >= 0.20]

        # Convert matrix to rounded list of lists
        matrix_list = [[round(float(matrix[r, c]), 4) for c in range(n)] for r in range(n)]

        return {
            "tickers": tickers,
            "matrix": matrix_list,
            "high_tail_risk_pairs": high_risk_pairs,
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
