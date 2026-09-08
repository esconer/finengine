"""
Volatility Term Structure & Volatility Cone Service
Multi-window rolling realized volatility quantiles, GARCH(1,1)/EWMA volatility forecasts,
and term structure positioning (cheap / normal / rich).
"""

from typing import Any, Dict, List, Optional, Union
import numpy as np
import pandas as pd
from arch import arch_model

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

DEFAULT_CONE_WINDOWS = [10, 21, 63, 126, 252]


class VolatilityService:
    """
    Service for calculating realized volatility term structure cones,
    rolling quantile distributions, and multi-step volatility forecasts.
    """

    @staticmethod
    def calculate_rolling_realized_volatility(
        returns: Union[pd.Series, np.ndarray],
        window: int,
        annualization_factor: float = np.sqrt(252.0),
        min_periods: Optional[int] = None,
    ) -> pd.Series:
        """
        Calculate annualized rolling realized volatility for a given window.

        Parameters
        ----------
        returns : pd.Series or np.ndarray
            Daily return series.
        window : int
            Rolling window size in trading days.
        annualization_factor : float
            Factor to annualize daily volatility (default sqrt(252)).
        min_periods : Optional[int]
            Minimum number of observations in window required to have a value.

        Returns
        -------
        pd.Series
            Series of annualized realized volatility.
        """
        if not isinstance(returns, pd.Series):
            returns = pd.Series(returns)

        clean_returns = returns.dropna()
        if len(clean_returns) == 0:
            return pd.Series(dtype=float)

        if min_periods is None:
            min_periods = max(5, min(window, len(clean_returns)))

        rolling_std = clean_returns.rolling(window=window, min_periods=min_periods).std(ddof=1)
        rolling_vol = rolling_std * annualization_factor
        return rolling_vol.dropna()

    @staticmethod
    def calculate_ewma_volatility(
        returns: Union[pd.Series, np.ndarray],
        decay: float = 0.94,
        annualization_factor: float = np.sqrt(252.0),
    ) -> float:
        """
        Calculate EWMA (RiskMetrics) annualized volatility.

        Parameters
        ----------
        returns : pd.Series or np.ndarray
            Daily return series.
        decay : float
            Decay parameter lambda (default 0.94 for daily data).
        annualization_factor : float
            Factor to annualize daily volatility (default sqrt(252)).

        Returns
        -------
        float
            Annualized EWMA volatility.
        """
        if isinstance(returns, pd.Series):
            r = returns.dropna().values
        else:
            r = np.asarray(returns)[~np.isnan(returns)]

        n = len(r)
        if n == 0:
            return 0.20
        if n == 1:
            return float(abs(r[0]) * annualization_factor)

        # Vectorized exponential weights: (1 - lambda) * lambda^(N-1-t)
        weights = (1.0 - decay) * (decay ** np.arange(n)[::-1])
        weights_sum = weights.sum()
        if weights_sum > 0:
            weights = weights / weights_sum
        else:
            weights = np.ones(n) / n

        weighted_variance = np.sum(weights * (r ** 2))
        return float(np.sqrt(max(0.0, weighted_variance)) * annualization_factor)

    @staticmethod
    def forecast_garch_volatility(
        returns: Union[pd.Series, np.ndarray],
        horizon: int = 21,
        annualization_factor: float = np.sqrt(252.0),
    ) -> Dict[str, Any]:
        """
        Fit GARCH(1,1) model on returns and compute annualized multi-step volatility forecast.

        Parameters
        ----------
        returns : pd.Series or np.ndarray
            Daily return series.
        horizon : int
            Forecast horizon in trading days.
        annualization_factor : float
            Annualization factor (default sqrt(252)).

        Returns
        -------
        Dict[str, Any]
            Dictionary with annualized volatility forecast and fitted model parameters.
        """
        if isinstance(returns, pd.Series):
            r = returns.dropna().values
        else:
            r = np.asarray(returns)[~np.isnan(returns)]

        if len(r) < 30:
            # Insufficient observations for stable GARCH convergence -> fallback to EWMA
            ewma_vol = VolatilityService.calculate_ewma_volatility(r, annualization_factor=annualization_factor)
            return {
                "annualized_vol": ewma_vol,
                "model": "EWMA",
                "horizon": horizon,
                "params": {"decay": 0.94, "fallback": True},
            }

        try:
            # Scale by 100 for numerical stability in arch package
            scaled_r = r * 100.0
            am = arch_model(scaled_r, vol="Garch", p=1, q=1, mean="Zero", dist="normal", rescale=False)
            res = am.fit(disp="off", show_warning=False)

            forecasts = res.forecast(horizon=horizon, reindex=False)
            var_steps = forecasts.variance.iloc[-1].values  # Variance of 100 * returns

            # Average daily variance over the forecast horizon
            mean_daily_variance = float(np.mean(var_steps))
            # Rescale back and annualize: sqrt(mean_daily_variance * 252) / 100
            ann_vol = float(np.sqrt(max(0.0, mean_daily_variance * 252.0)) / 100.0)

            params = {
                "omega": float(res.params.get("omega", 0.0)),
                "alpha": float(res.params.get("alpha[1]", 0.0)),
                "beta": float(res.params.get("beta[1]", 0.0)),
                "persistence": float(res.params.get("alpha[1]", 0.0) + res.params.get("beta[1]", 0.0)),
            }

            return {
                "annualized_vol": ann_vol,
                "model": "GARCH(1,1)",
                "horizon": horizon,
                "params": params,
            }
        except Exception as e:
            logger.warning(f"GARCH(1,1) fitting failed ({e}), falling back to EWMA")
            ewma_vol = VolatilityService.calculate_ewma_volatility(r, annualization_factor=annualization_factor)
            return {
                "annualized_vol": ewma_vol,
                "model": "EWMA",
                "horizon": horizon,
                "params": {"decay": 0.94, "fallback": True, "error": str(e)},
            }

    @classmethod
    def calculate_volatility_cone(
        cls,
        returns: Union[pd.Series, np.ndarray],
        symbol: str = "PORTFOLIO",
        windows: Optional[List[int]] = None,
        forecast_horizon: int = 21,
        forecast_model: str = "GARCH",
        as_of: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Compute multi-window realized volatility quantiles (min, p25, median, p75, max, current)
        and overlay GARCH/EWMA volatility forecasts with valuation positioning ("cheap", "normal", "rich").

        Parameters
        ----------
        returns : pd.Series or np.ndarray
            Daily return series across lookback period.
        symbol : str
            Identifier for symbol or portfolio.
        windows : Optional[List[int]]
            List of window lengths in trading days (default: [10, 21, 63, 126, 252]).
        forecast_horizon : int
            Forecast horizon in days (default: 21).
        forecast_model : str
            Model type ("GARCH" or "EWMA").
        as_of : Optional[str]
            As-of date string (YYYY-MM-DD).

        Returns
        -------
        Dict[str, Any]
            Structure compliant with VolConeResponse schema.
        """
        if windows is None:
            windows = DEFAULT_CONE_WINDOWS

        if not isinstance(returns, pd.Series):
            returns = pd.Series(returns)

        clean_returns = returns.dropna()

        if as_of is None:
            if isinstance(clean_returns.index, pd.DatetimeIndex) and len(clean_returns.index) > 0:
                as_of = str(clean_returns.index[-1])[:10]
            else:
                as_of = pd.Timestamp.now().strftime("%Y-%m-%d")

        window_results: List[Dict[str, Any]] = []
        realized_vols_by_window: Dict[int, pd.Series] = {}

        for w in sorted(windows):
            rolling_vol = cls.calculate_rolling_realized_volatility(clean_returns, window=w)
            realized_vols_by_window[w] = rolling_vol

            if len(rolling_vol) >= 2:
                vol_values = rolling_vol.values
                min_v = float(np.min(vol_values))
                p25_v = float(np.percentile(vol_values, 25))
                med_v = float(np.median(vol_values))
                p75_v = float(np.percentile(vol_values, 75))
                max_v = float(np.max(vol_values))
                curr_v = float(vol_values[-1])
                # Quantile ranking of current realized vol (0 to 100)
                rank = float(np.sum(vol_values <= curr_v) / len(vol_values) * 100.0)
                insufficient = False
            elif len(rolling_vol) == 1:
                # Single observation: quantile bounds would be fabricated
                # multiples — report nulls + flag, keep the observed value only.
                curr_v = float(rolling_vol.iloc[-1])
                min_v = p25_v = med_v = p75_v = max_v = None
                rank = None
                insufficient = True
            else:
                # Window exceeds observations: no realized vol at all — nulls +
                # flag, never synthetic multiples of an arbitrary baseline.
                curr_v = None
                min_v = p25_v = med_v = p75_v = max_v = None
                rank = None
                insufficient = True

            # Ensure strict mathematical monotonicity: min <= p25 <= median <= p75 <= max
            if not insufficient:
                min_v, p25_v, med_v, p75_v, max_v = sorted([min_v, p25_v, med_v, p75_v, max_v])

            window_results.append({
                "window_days": int(w),
                "min": round(min_v, 4) if min_v is not None else None,
                "p25": round(p25_v, 4) if p25_v is not None else None,
                "median": round(med_v, 4) if med_v is not None else None,
                "p75": round(p75_v, 4) if p75_v is not None else None,
                "max": round(max_v, 4) if max_v is not None else None,
                "current_realized": round(curr_v, 4) if curr_v is not None else None,
                "percentile_rank": round(rank, 1) if rank is not None else None,
                "insufficient_data": insufficient,
            })

        # Calculate forecast overlay
        if forecast_model.upper() == "EWMA":
            ann_vol_forecast = cls.calculate_ewma_volatility(clean_returns)
            model_label = "EWMA"
        else:
            garch_res = cls.forecast_garch_volatility(clean_returns, horizon=forecast_horizon)
            ann_vol_forecast = garch_res["annualized_vol"]
            model_label = garch_res["model"]

        # Positioning valuation against 21-day benchmark window (or closest available window)
        target_w = 21 if 21 in realized_vols_by_window else windows[0]
        benchmark_vol_series = realized_vols_by_window.get(target_w, pd.Series(dtype=float))
        matching_window_stat = next((w_stat for w_stat in window_results if w_stat["window_days"] == target_w), window_results[0])

        p25_bench = matching_window_stat["p25"]
        p75_bench = matching_window_stat["p75"]

        if len(benchmark_vol_series) >= 2:
            forecast_rank: float | None = float(np.sum(benchmark_vol_series.values <= ann_vol_forecast) / len(benchmark_vol_series) * 100.0)
        else:
            forecast_rank = None

        if p25_bench is None or p75_bench is None:
            # Benchmark window has no realized distribution — no honest valuation
            valuation = "unknown"
        elif ann_vol_forecast <= p25_bench:
            valuation = "cheap"
        elif ann_vol_forecast > p75_bench:
            valuation = "rich"
        else:
            valuation = "normal"

        forecast_overlay = {
            "model": model_label,
            "annualized_vol": round(ann_vol_forecast, 4),
            "horizon_days": int(forecast_horizon),
            "percentile_rank": round(forecast_rank, 1) if forecast_rank is not None else None,
            "valuation": valuation,
        }

        return {
            "symbol": symbol,
            "as_of": as_of,
            "windows": window_results,
            "current_forecast": forecast_overlay,
        }
