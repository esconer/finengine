"""
Correlation Stability and Regime Break Monitor Service
Calculates rolling 60-day average pairwise correlation and detects diversification breakdown.
"""

from itertools import combinations
from typing import List, Optional
import numpy as np
import pandas as pd

from app.models.schemas import CorrelationDataPoint, CorrelationStabilityResponse
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def compute_rolling_avg_correlation(
    returns_df: pd.DataFrame,
    window_days: int = 60,
    min_periods: Optional[int] = None,
) -> pd.Series:
    """
    Compute rolling average pairwise correlation series:
    rho_bar_t = (2 / (N * (N - 1))) * sum_{i < j} rho_{i, j, t}

    Args:
        returns_df: Wide DataFrame of asset daily returns (index=Date, columns=tickers)
        window_days: Rolling window size (default 60 trading days)
        min_periods: Minimum number of observations in window (default min(window_days, 30))

    Returns:
        pd.Series indexed by Date with rolling average pairwise correlation values
    """
    if returns_df is None or returns_df.empty:
        raise ValueError("Returns DataFrame is empty or None")

    clean_returns = returns_df.dropna(how="all")
    tickers = list(clean_returns.columns)
    n = len(tickers)

    if n < 2:
        raise ValueError("At least 2 distinct assets are required for pairwise correlation analysis")

    if len(clean_returns) < 30:
        raise ValueError(
            f"Insufficient return observations ({len(clean_returns)}). Minimum 30 observations required."
        )

    if min_periods is None:
        min_periods = min(window_days, 30)

    # Compute pairwise rolling correlation for all unique pairs i < j
    pair_corrs = []
    for t1, t2 in combinations(tickers, 2):
        s1 = clean_returns[t1]
        s2 = clean_returns[t2]
        pair_corr = s1.rolling(window=window_days, min_periods=min_periods).corr(s2)
        pair_corrs.append(pair_corr)

    # Average across all N*(N-1)/2 pairs
    pairs_df = pd.concat(pair_corrs, axis=1)
    avg_corr_series = pairs_df.mean(axis=1).dropna()

    if avg_corr_series.empty:
        raise ValueError("Unable to compute rolling correlation: insufficient overlapping data points")

    return avg_corr_series


def analyze_correlation_stability(
    returns_df: pd.DataFrame,
    window_days: int = 60,
    min_periods: Optional[int] = None,
) -> CorrelationStabilityResponse:
    """
    Analyze rolling correlation stability and evaluate regime breaks against the
    rolling series' own historical distribution.

    The break test is TWO-SIDED: the upper tail is a diversification breakdown
    (CRITICAL) and the lower tail is a collapse in co-movement (ELEVATED). Both
    tails set ``is_regime_break``. A monitor that tests only the upper tail
    calls a correlation collapse "normal", which is the failure mode this
    function exists to prevent.

    Because both non-critical tails share the string "ELEVATED", the response
    also carries ``alert_direction``: which of the four arms fired, in words as
    well as in token, so the reader is not left inferring sign from a severity.

    Args:
        returns_df: Wide DataFrame of daily returns for assets
        window_days: Rolling window size (default 60 days)
        min_periods: Minimum observations for rolling calculation

    Returns:
        CorrelationStabilityResponse object
    """
    avg_corr_series = compute_rolling_avg_correlation(
        returns_df=returns_df,
        window_days=window_days,
        min_periods=min_periods,
    )

    corr_values = avg_corr_series.values
    threshold_90th = float(np.percentile(corr_values, 90))
    threshold_75th = float(np.percentile(corr_values, 75))
    threshold_10th = float(np.percentile(corr_values, 10))
    historical_median = float(np.median(corr_values))

    current_avg_corr = float(corr_values[-1])
    # TWO-SIDED test, from the same two comparisons that pick the alert:
    # `is_regime_break` and `alert_level` can therefore never contradict on a
    # flat series where current == p90 exactly (and, symmetrically, == p10).
    #
    # Only the upper tail was tested before, so ANY collapse in co-movement
    # reached the ELSE branch and its reassuring message. A book whose average
    # pairwise correlation sits at a fraction of its own historical median was
    # reported as "within normal historical bounds", which is the one direction
    # a diversification monitor must never call normal: a low-correlation
    # reading means the historical diversification benefit may not be
    # available in the current regime at all.
    upper_break = bool(current_avg_corr >= threshold_90th)
    lower_break = bool(current_avg_corr <= threshold_10th)
    is_regime_break = upper_break or lower_break

    # The distribution being ranked against is a series of OVERLAPPING rolling
    # windows, so publish its size inside the message the consumer will quote.
    tested_basis = (
        f"tested two-sided against its own history of {len(corr_values)} "
        f"overlapping {int(window_days)}-day rolling windows"
    )

    # `alert_level` is a severity and says nothing about SIGN: the two ELEVATED
    # arms below mean opposite things. The upper one is co-movement rising, the
    # lower one is co-movement collapsed - a reading that removes the very
    # diversification benefit this section scores, and the one direction a
    # diversification monitor must never let a consumer mistake for the other.
    # The direction is set in each arm from the comparison that arm already
    # used, so level and direction cannot disagree. It is a required assignment
    # at every arm rather than a computed default: `null` on this schema means
    # "no comparison ran" (see the single-holding path), not "the service forgot".
    if upper_break:
        alert_level = "CRITICAL"
        alert_direction = "upper_tail_critical"
        message = (
            f"Average pairwise correlation ({current_avg_corr:.3f}) meets or exceeds 90th percentile "
            f"({threshold_90th:.3f}). Diversification breakdown detected."
        )
    elif current_avg_corr >= threshold_75th:
        alert_level = "ELEVATED"
        alert_direction = "upper_tail_elevation"
        message = (
            f"Average pairwise correlation ({current_avg_corr:.3f}) exceeds 75th percentile "
            f"({threshold_75th:.3f}). Pairwise correlation is elevated."
        )
    elif lower_break:
        alert_level = "ELEVATED"
        alert_direction = "lower_tail_collapse"
        message = (
            f"Average pairwise correlation ({current_avg_corr:.3f}) is at or below the 10th "
            f"percentile ({threshold_10th:.3f}) of its own history "
            f"(median {historical_median:.3f}). Co-movement has collapsed: this is a change of "
            f"correlation regime, not a reassurance. Positions that diversified historically may "
            f"not diversify against each other in this regime, so historical risk estimates that "
            f"assumed the median correlation no longer describe this book. ({tested_basis}.)"
        )
    else:
        alert_level = "NORMAL"
        alert_direction = "within_band"
        # "Normal" is only meaningful as a bounded claim, so the bounds are
        # named: inside the 10th-90th percentile band, and nothing more.
        message = (
            f"Average pairwise correlation ({current_avg_corr:.3f}) is inside the "
            f"10th-90th percentile band of its own history "
            f"(10th {threshold_10th:.3f}, median {historical_median:.3f}, "
            f"90th {threshold_90th:.3f}); no correlation regime break on either tail. "
            f"This is an in-sample rank, not a significance test "
            f"({tested_basis})."
        )

    # Format series
    series_points: List[CorrelationDataPoint] = []
    for dt, val in avg_corr_series.items():
        date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
        series_points.append(
            CorrelationDataPoint(
                date=date_str,
                avg_correlation=round(float(val), 4),
                threshold_90th=round(threshold_90th, 4),
                threshold_75th=round(threshold_75th, 4),
            )
        )

    as_of_date = (
        avg_corr_series.index[-1].strftime("%Y-%m-%d")
        if hasattr(avg_corr_series.index[-1], "strftime")
        else str(avg_corr_series.index[-1])[:10]
    )

    return CorrelationStabilityResponse(
        as_of=as_of_date,
        current_avg_correlation=round(current_avg_corr, 4),
        historical_threshold_90th=round(threshold_90th, 4),
        historical_threshold_75th=round(threshold_75th, 4),
        historical_threshold_10th=round(threshold_10th, 4),
        historical_median=round(historical_median, 4),
        is_regime_break=is_regime_break,
        alert_level=alert_level,
        alert_direction=alert_direction,
        message=message,
        series=series_points,
    )
