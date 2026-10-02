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

# A rolling-L realized-volatility series over T observations yields T-L+1
# OVERLAPPING windows, consecutive ones sharing (L-1)/L of their data. The
# count that therefore drives a percentile rank is (T-L+1)/L under iid
# returns, not T-L+1. A 252-day cone built on 2486 daily returns is 2235
# windows but only ~8.9 independent observations, and the 95% Wald half-width
# on a percentile rank at that effective count is ~33 percentage points: a
# published "1.9th percentile" off it is not distinguishable from 17, or 35.
#
# 30 is the threshold used by SI-7's fix direction. At effective_n = 30 the
# worst-case half-width is ~18pp; below it the rank cannot separate the
# middle of its own distribution from either tail, so no rank is published.
# Fewer verdicts is the correct answer here, not a substitute number.
MIN_EFFECTIVE_OBSERVATIONS_FOR_PERCENTILE = 30.0

#: Two-sided 95% Wald half-width on a percentile rank at the WORST case rank
#: (p = 0.5): 1.96 * 100 * sqrt(0.25 / effective_n).
PERCENTILE_RANK_HALF_WIDTH_Z = 1.96
PERCENTILE_RANK_HALF_WIDTH_RULE = (
    "worst-case 95% Wald half-width on a percentile rank: "
    "1.96 * 100 * sqrt(0.25 / effective_n) percentage points, taken at p=0.5 "
    "because the variance of a proportion is maximal there; a rank observed "
    "near either tail is measured more precisely than this bound"
)
EFFECTIVE_N_RULE = (
    "rolling windows are overlapping: consecutive windows of length L share "
    "(L-1)/L of their returns, so effective_n = n_windows / window_days is the "
    "count that supports a percentile rank, and n_windows is the raw count"
)

#: Payloads `_percentile_rank_basis` may be merged into. They do not carry the
#: same fields, so the withheld-reason clause is subject-specific: see
#: `_percentile_rank_basis`.
_PERCENTILE_RANK_SUBJECTS = frozenset({"row", "forecast"})

# ---------------------------------------------------------------------------
# `current_forecast.horizon_days`: one field name, two quantities.
# ---------------------------------------------------------------------------
# An EWMA (RiskMetrics) estimate is a one-step conditional variance: it is a
# weighted average of squared returns ending at the last observation and is not
# a function of any horizon. The GARCH branch really does forecast
# `forecast_horizon` steps ahead. So `horizon_days: 21` published beside an
# `"EWMA"` label claimed a 21-day quantity for a 1-day number, and a reader
# comparing an EWMA row against a GARCH row on the same field was comparing two
# different things without being able to tell.
#
# The label "EWMA" reaches the overlay two ways - the direct
# `forecast_model="EWMA"` branch, and `forecast_garch_volatility`'s own EWMA
# fallback (too few returns, or a failed GARCH fit) - so the horizon is withheld
# on the LABEL, not on the branch the caller asked for.
EWMA_HORIZON_NOTE = (
    "horizon_days is null because the forecast named in model above is an EWMA "
    "(RiskMetrics) estimate, which is a one-step conditional volatility: it is "
    "a decayed weighted average of squared returns ending at the last "
    "observation and is not a function of any horizon, so no number of days can "
    "be published for it. A GARCH(1,1) row publishes the real multi-step "
    "horizon it was fitted for, and the two rows therefore cannot be compared "
    "on this field - compare annualized_vol instead, and note that "
    "ranked_against_window_days names the realized distribution the rank was "
    "taken against."
)

#: Published beside `annualized_vol: null`. The level is withheld, not replaced:
#: a caller that invents a number here invents a verdict with it, because the
#: valuation branch reads this field.
FORECAST_VOL_WITHHELD_REASON = (
    "withheld: no dispersion estimate is measurable from this return series - "
    "an EWMA volatility needs at least two observations and the series has one, "
    "so annualized_vol, percentile_rank and valuation are all withheld rather "
    "than filled with a stand-in. An earlier version published 0.0 here, which "
    "is not a missing measurement but the strongest claim available ('this "
    "book does not move'), and 0.0 sits at or below every non-negative p25 of "
    "the realized-vol distribution, so it ranked as the CHEAP band."
)


def _effective_window_count(n_windows: int, window_days: int) -> float:
    """Independent-observation count behind `n_windows` overlapping windows."""
    if window_days <= 0 or n_windows <= 0:
        return 0.0
    return float(n_windows) / float(window_days)


def _percentile_rank_basis(
    n_windows: int, window_days: int, subject: str = "row"
) -> Dict[str, Any]:
    """The counts and precision a percentile rank on this window rests on.

    Returns `effective_n` (see :data:`EFFECTIVE_N_RULE`), the worst-case 95%
    half-width on a rank at that count, and whether the count clears
    :data:`MIN_EFFECTIVE_OBSERVATIONS_FOR_PERCENTILE`. The half-width is
    published even when the rank is withheld, so a reader can see how
    uninformative the withheld verdict was rather than only seeing an absence.

    `subject` names the payload the block is being merged into: `"row"` for a
    vol-cone window row, `"forecast"` for the `current_forecast` overlay. It
    exists because the two objects do not carry the same fields. A row publishes
    quantiles and `current_realized`; the forecast publishes neither — only
    `annualized_vol` and `model` — so a trailing clause borrowed from the row
    told a reader to trust a field the forecast does not have. The clause names
    only fields the named subject actually publishes; it does not name the model,
    which is payload data (`model` is "GARCH(1,1)" or the "EWMA" fallback) and
    is not knowable here.
    """
    if subject not in _PERCENTILE_RANK_SUBJECTS:
        raise ValueError(
            f"unknown subject {subject!r}; expected one of "
            f"{sorted(_PERCENTILE_RANK_SUBJECTS)}"
        )
    effective_n = _effective_window_count(n_windows, window_days)
    sufficient = effective_n >= MIN_EFFECTIVE_OBSERVATIONS_FOR_PERCENTILE
    half_width = (
        float(PERCENTILE_RANK_HALF_WIDTH_Z * 100.0 * np.sqrt(0.25 / effective_n))
        if effective_n > 0
        else None
    )
    # Only fields the named subject publishes may be named in its clause.
    if subject == "forecast":
        no_windows_clause = (
            "annualized_vol above is the forecast of the model named in this "
            "object's model field, not a measurement of realized volatility, and "
            "there is no observed distribution here to rank it against."
        )
        too_thin_clause = (
            "annualized_vol above is the forecast of the model named in this "
            "object's model field, not a measurement of realized volatility. It "
            "is ranked against the same observed overlapping-window distribution "
            f"the {int(window_days)}d row uses."
        )
    else:
        no_windows_clause = (
            "The quantiles in this row are null for the same reason; "
            "current_realized is measured when the window produced a value."
        )
        too_thin_clause = (
            "The quantiles in this row still describe the observed "
            "overlapping-window sample; current_realized is measured."
        )
    if sufficient:
        withheld_reason = None
    elif half_width is None:
        withheld_reason = (
            f"withheld: no overlapping windows at all over {int(window_days)}d, "
            f"so there is no distribution to rank against. {no_windows_clause}"
        )
    else:
        withheld_reason = (
            f"withheld: effective_n {effective_n:.2f} < "
            f"{MIN_EFFECTIVE_OBSERVATIONS_FOR_PERCENTILE:.0f} overlapping-window "
            f"observations over {int(window_days)}d; the worst-case 95% half-width "
            f"on a rank here is {half_width:.1f}pp, so the rank carries no usable "
            f"information. {too_thin_clause}"
        )

    return {
        "n_windows": int(n_windows),
        "effective_n": round(effective_n, 2) if effective_n > 0 else None,
        "effective_n_rule": EFFECTIVE_N_RULE,
        "minimum_effective_n_for_percentile_rank": MIN_EFFECTIVE_OBSERVATIONS_FOR_PERCENTILE,
        "percentile_rank_95pct_half_width_pct": round(half_width, 1) if half_width is not None else None,
        "percentile_rank_half_width_rule": PERCENTILE_RANK_HALF_WIDTH_RULE,
        "percentile_rank_sufficient_data": bool(sufficient),
        "percentile_rank_withheld_reason": withheld_reason,
    }


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

        clean_returns = returns.replace([np.inf, -np.inf], np.nan)
        finite_count = int(clean_returns.notna().sum())
        if finite_count == 0:
            return pd.Series(dtype=float)

        if min_periods is None:
            min_periods = max(5, min(window, finite_count))

        rolling_std = clean_returns.rolling(window=window, min_periods=min_periods).std(ddof=1)
        rolling_vol = rolling_std * annualization_factor
        return rolling_vol.dropna()

    @staticmethod
    def calculate_ewma_volatility(
        returns: Union[pd.Series, np.ndarray],
        decay: float = 0.94,
        annualization_factor: float = np.sqrt(252.0),
    ) -> Optional[float]:
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
        Optional[float]
            Annualized EWMA volatility, or ``None`` when there is no
            dispersion estimate to publish.  Empty input raises; a single
            observation returns ``None`` because a one-observation sample has
            no dispersion.  It previously returned ``0.0``, which is not a
            missing measurement but the strongest possible claim - "this book
            does not move" - and it was rankable against the realized-vol
            distribution, where any non-negative p25 puts it in the CHEAP band.
            A book with no measurable volatility is not cheap.
        """
        if isinstance(returns, pd.Series):
            r = returns.replace([np.inf, -np.inf], np.nan).dropna().values
        else:
            values = np.asarray(returns)
            r = values[np.isfinite(values)]

        n = len(r)
        if n == 0:
            # No fabrication: an EWMA forecast cannot be computed from
            # nothing (route/garch callers guard non-empty inputs).
            raise ValueError("Cannot compute EWMA volatility on empty returns")
        if n == 1:
            # A single return contains no dispersion estimate. Returning its
            # absolute value conflates return level with volatility, and
            # returning 0.0 states as a measurement the one thing we cannot
            # know. Withhold, and let the caller publish its own reason.
            return None

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
            Dictionary with annualized volatility forecast and fitted model
            parameters. ``horizon`` is the number of days the returned number was
            actually forecast for, and is ``None`` when the answer came from the
            EWMA fallback: that fallback is a one-step spot estimate that ignores
            ``horizon`` entirely, so publishing the requested horizon beside it
            claimed coverage the number does not have.
        """
        if isinstance(returns, pd.Series):
            r = returns.replace([np.inf, -np.inf], np.nan).dropna().values
        else:
            values = np.asarray(returns)
            r = values[np.isfinite(values)]

        if len(r) < 30:
            # Insufficient observations for stable GARCH convergence -> fallback to EWMA
            ewma_vol = VolatilityService.calculate_ewma_volatility(r, annualization_factor=annualization_factor)
            return {
                "annualized_vol": ewma_vol,
                "model": "EWMA",
                "horizon": None,
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
                # Same reason as the too-few-returns fallback above: the EWMA
                # number is a spot estimate, so the requested horizon does not
                # describe it.
                "horizon": None,
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

        The rolling windows OVERLAP, so every row publishes the raw
        ``n_windows``, the ``effective_n`` behind it, the worst-case 95%
        half-width on a percentile rank, and — below
        :data:`MIN_EFFECTIVE_OBSERVATIONS_FOR_PERCENTILE` effective
        observations — withholds ``percentile_rank`` with a reason instead of
        emitting a number the sample cannot support. The quantile bounds are
        descriptions of the observed overlapping sample and are still
        published; only the rank is a verdict.

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
        if not windows:
            # None or [] both mean "use defaults" — windows[0] / window_results[0]
            # below would IndexError on an empty list.
            windows = DEFAULT_CONE_WINDOWS

        if not isinstance(returns, pd.Series):
            returns = pd.Series(returns)

        clean_returns = returns.replace([np.inf, -np.inf], np.nan)

        if as_of is None:
            if isinstance(clean_returns.index, pd.DatetimeIndex) and clean_returns.notna().any():
                as_of = str(clean_returns.last_valid_index())[:10]
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
                # Quantile ranking of current realized vol (0 to 100). The
                # windows overlap, so the rank is only published when the
                # EFFECTIVE count behind it is large enough to support a
                # verdict; below that it is withheld, not estimated.
                rank_basis = _percentile_rank_basis(len(rolling_vol), int(w))
                if rank_basis["percentile_rank_sufficient_data"]:
                    rank = float(
                        np.sum(vol_values <= curr_v) / len(vol_values) * 100.0
                    )
                else:
                    rank = None
                insufficient = False
            elif len(rolling_vol) == 1:
                # Single observation: quantile bounds would be fabricated
                # multiples — report nulls + flag, keep the observed value only.
                curr_v = float(rolling_vol.iloc[-1])
                min_v = p25_v = med_v = p75_v = max_v = None
                rank = None
                insufficient = True
                rank_basis = _percentile_rank_basis(len(rolling_vol), int(w))
            else:
                # Window exceeds observations: no realized vol at all — nulls +
                # flag, never synthetic multiples of an arbitrary baseline.
                curr_v = None
                min_v = p25_v = med_v = p75_v = max_v = None
                rank = None
                insufficient = True
                rank_basis = _percentile_rank_basis(len(rolling_vol), int(w))

            # min <= p25 <= median <= p75 <= max holds by construction
            # (percentiles of the same array); no re-sorting needed.

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
                **rank_basis,
            })

        # Calculate forecast overlay
        if forecast_model.upper() == "EWMA":
            ann_vol_forecast = cls.calculate_ewma_volatility(clean_returns)
            model_label = "EWMA"
            # An EWMA spot estimate takes no horizon (see EWMA_HORIZON_NOTE).
            forecast_horizon_days: Optional[int] = None
        else:
            garch_res = cls.forecast_garch_volatility(clean_returns, horizon=forecast_horizon)
            ann_vol_forecast = garch_res["annualized_vol"]
            model_label = garch_res["model"]
            # `forecast_garch_volatility` answers "EWMA" itself when it cannot
            # fit GARCH - too few returns, or a failed fit - and that answer is
            # the same horizon-free spot estimate. The horizon is therefore a
            # property of the LABEL that actually produced the number, not of
            # the branch the caller asked for.
            forecast_horizon_days = (
                int(forecast_horizon) if model_label == "GARCH(1,1)" else None
            )

        # Positioning valuation against 21-day benchmark window (or closest available window)
        target_w = 21 if 21 in realized_vols_by_window else windows[0]
        benchmark_vol_series = realized_vols_by_window.get(target_w, pd.Series(dtype=float))
        matching_window_stat = next((w_stat for w_stat in window_results if w_stat["window_days"] == target_w), window_results[0])

        p25_bench = matching_window_stat["p25"]
        p75_bench = matching_window_stat["p75"]

        # Same overlap correction on the forecast's own rank: it is ranked
        # against the benchmark window's overlapping realized series, so it
        # inherits that window's effective count and its gate.
        forecast_rank_basis = _percentile_rank_basis(
            len(benchmark_vol_series), int(target_w), subject="forecast"
        )
        forecast_rank_basis["ranked_against_window_days"] = int(target_w)
        if (
            ann_vol_forecast is not None
            and len(benchmark_vol_series) >= 2
            and forecast_rank_basis["percentile_rank_sufficient_data"]
        ):
            forecast_rank: float | None = float(
                np.sum(benchmark_vol_series.values <= ann_vol_forecast)
                / len(benchmark_vol_series)
                * 100.0
            )
        else:
            forecast_rank = None

        if ann_vol_forecast is None:
            # A withheld rank still ships with a reason, and here the count
            # basis is not the whole story: there is no level to place on the
            # distribution at all. Keep whatever `_percentile_rank_basis`
            # measured - it is still true - as the trailing clause.
            forecast_rank_basis["percentile_rank_withheld_reason"] = (
                "withheld: annualized_vol is null, so there is no forecast level "
                "to place on the observed overlapping-window distribution. "
                + (forecast_rank_basis["percentile_rank_withheld_reason"] or "")
            ).strip()

        if ann_vol_forecast is None or p25_bench is None or p75_bench is None:
            # Either the benchmark window has no realized distribution, or there
            # is no forecast to judge against it. No honest valuation either
            # way; the branches below would otherwise compare None with a
            # quantile, or publish CHEAP for a book whose volatility could not
            # be measured.
            valuation = "unknown"
        elif ann_vol_forecast <= p25_bench:
            valuation = "cheap"
        elif ann_vol_forecast > p75_bench:
            valuation = "rich"
        else:
            valuation = "normal"

        forecast_overlay = {
            "model": model_label,
            "annualized_vol": (
                round(ann_vol_forecast, 4) if ann_vol_forecast is not None else None
            ),
            "horizon_days": forecast_horizon_days,
            "percentile_rank": round(forecast_rank, 1) if forecast_rank is not None else None,
            "valuation": valuation,
            **forecast_rank_basis,
        }
        # These two are published ONLY where the value they explain is absent.
        # They are not always-present keys on purpose: a GARCH(1,1) row's
        # horizon is a measurement and needs no excuse, and its level is always
        # measured. An always-present null would be indistinguishable from a
        # key that was simply forgotten.
        if forecast_horizon_days is None:
            forecast_overlay["horizon_note"] = EWMA_HORIZON_NOTE
        if ann_vol_forecast is None:
            forecast_overlay["annualized_vol_withheld_reason"] = (
                FORECAST_VOL_WITHHELD_REASON
            )

        return {
            "symbol": symbol,
            "as_of": as_of,
            "windows": window_results,
            "current_forecast": forecast_overlay,
        }
