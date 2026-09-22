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
    1. EVT-POT (Peaks-Over-Threshold) 99% VaR and Expected Shortfall via Generalized Pareto Distribution (GPD).
    2. Bivariate Student-t Copula Lower-Tail Dependence Coefficient matrix (lambda_L).
    """

    @staticmethod
    def calculate_evt_pot_var_es(
        returns: Union[pd.Series, np.ndarray],
        confidence_level: float = 0.99,
        threshold_quantile: float = 0.95,
    ) -> Dict[str, Any]:
        """
        Calculate 99% EVT-POT Value-at-Risk and Expected Shortfall using scipy.stats.genpareto.

        Parameters
        ----------
        returns : pd.Series or np.ndarray
            Daily portfolio returns series.
        confidence_level : float
            Confidence level for VaR/ES (default 0.99).
        threshold_quantile : float
            Quantile for POT threshold selection (default 0.95).

        Returns
        -------
        Dict[str, Any]
            EVT POT VaR/ES, historical VaR/ES, GPD parameters (xi, beta), and diagnostics.
        """
        if isinstance(returns, pd.Series):
            r = returns.dropna().values
        else:
            r = np.asarray(returns)[~np.isnan(returns)]

        n_total = len(r)
        if n_total < 20:
            # Never fabricate tail numbers: EVT-POT needs enough data to
            # clear the 95% threshold with fittable exceedances. Callers map
            # this to 400/insufficient-data (the /tails route already guards
            # len(port_ret) < 30 and translates ValueError to 400).
            raise ValueError(
                f"Insufficient observations for EVT-POT (need >= 20, got {n_total})"
            )

        if threshold_quantile >= confidence_level:
            # Fitting GPD above the reported confidence level would make the
            # threshold clamp systematically overstate VaR/ES for that level.
            raise ValueError(
                f"threshold_quantile ({threshold_quantile}) must be < "
                f"confidence_level ({confidence_level})"
            )

        # Daily loss series: positive values are losses
        losses = -r
        alpha = 1.0 - confidence_level  # 0.01 for 99%

        # 1. Historical empirical VaR and ES
        hist_var_loss = float(np.percentile(losses, confidence_level * 100.0))
        tail_losses = losses[losses >= hist_var_loss]
        hist_es_loss = float(np.mean(tail_losses)) if len(tail_losses) > 0 else hist_var_loss

        # 2. EVT Peaks-Over-Threshold (POT)
        threshold_u = float(np.percentile(losses, threshold_quantile * 100.0))
        exceedances = losses[losses > threshold_u] - threshold_u
        n_u = len(exceedances)

        if n_u < 5:
            # Not enough exceedances to fit GPD reliably: report honest
            # historical-only VaR/ES with model_fitted=False and no GPD
            # parameters — never invent xi/beta or scale history by
            # arbitrary factors (fabrication class as the fixed P0-6).
            xi = None
            beta = None
            model_fitted = False
            var_evt_loss = hist_var_loss
            es_evt_loss = hist_es_loss
        else:
            try:
                # Fit GPD with location fixed at 0: y ~ GPD(xi, beta)
                # scipy.stats.genpareto: c is shape parameter (xi), scale is beta
                c_est, loc_est, scale_est = stats.genpareto.fit(exceedances, floc=0.0)
                xi = float(c_est)
                beta = float(max(scale_est, 1e-6))
                model_fitted = True

                # Numerical stability constraint: clip xi in [-0.5, 0.95]
                # If xi >= 1.0, theoretical mean (ES) does not exist
                xi = float(np.clip(xi, -0.5, 0.95))

                # Analytical EVT VaR formula
                ratio = (n_total / n_u) * alpha
                if abs(xi) > 1e-6:
                    var_evt_loss = threshold_u + (beta / xi) * ((ratio ** (-xi)) - 1.0)
                else:
                    var_evt_loss = threshold_u - beta * np.log(ratio)

                # Analytical EVT Expected Shortfall formula: ES = (VaR + beta - xi * u) / (1 - xi)
                es_evt_loss = (var_evt_loss + beta - xi * threshold_u) / (1.0 - xi)

                # Monotonicity & conservative sanity check: ES >= VaR >= threshold_u.
                # No cosmetic VaR->ES gap: a thin tail with ES ~ VaR stays honest.
                var_evt_loss = max(var_evt_loss, threshold_u, hist_var_loss * 0.9)
                es_evt_loss = max(es_evt_loss, var_evt_loss)

            except Exception as e:
                logger.warning(
                    f"GPD fit failed ({e}); reporting historical-only tail metrics "
                    f"(model_fitted=False)"
                )
                xi = None
                beta = None
                model_fitted = False
                var_evt_loss = hist_var_loss
                es_evt_loss = hist_es_loss

        # Check kurtosis for fat tails
        excess_kurt = float(stats.kurtosis(r)) if n_total > 4 else 0.0
        if model_fitted:
            is_fat_tailed = bool(xi > 0.05 or excess_kurt > 0.5 or (var_evt_loss > hist_var_loss))
        else:
            # No GPD fit: fatness comes from the empirical tail only —
            # never forced True by a fabricated inflation factor.
            is_fat_tailed = bool(excess_kurt > 0.5)

        return {
            "confidence_level": round(confidence_level, 2),
            "evt_pot_var_99": round(-float(var_evt_loss), 6),
            "evt_pot_es_99": round(-float(es_evt_loss), 6),
            "historical_var_99": round(-float(hist_var_loss), 6),
            "historical_es_99": round(-float(hist_es_loss), 6),
            "threshold_u": round(float(threshold_u), 6),
            "gpd_shape_xi": round(float(xi), 4) if xi is not None else None,
            "gpd_scale_beta": round(float(beta), 6) if beta is not None else None,
            "model_fitted": model_fitted,
            "exceedances_count": int(n_u),
            "total_observations": int(n_total),
            "is_fat_tailed": is_fat_tailed,
        }

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

        # Compute weighted portfolio returns
        if weights is not None and len(weights) > 0:
            norm_weights = pd.Series(weights)
            matched_cols = [c for c in norm_weights.index if c in returns_df.columns]
            if matched_cols:
                w_subset = norm_weights[matched_cols]
                w_subset = w_subset / w_subset.sum()
                portfolio_returns = (returns_df[matched_cols].fillna(0.0) * w_subset).sum(axis=1)
            else:
                portfolio_returns = returns_df.mean(axis=1)
        else:
            portfolio_returns = returns_df.mean(axis=1)

        # 1. EVT POT VaR/ES
        evt_var_metrics = cls.calculate_evt_pot_var_es(portfolio_returns, confidence_level=0.99, threshold_quantile=0.95)

        # 2. Copula Lower-Tail Dependence Matrix
        tail_dep_matrix = cls.calculate_tail_dependence_matrix(returns_df)

        return {
            "as_of": as_of,
            "evt_var": evt_var_metrics,
            "tail_dependence_matrix": tail_dep_matrix,
        }
