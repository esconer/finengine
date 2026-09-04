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
    Analyze rolling correlation stability and evaluate regime breaks against historical distribution.

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
    historical_median = float(np.median(corr_values))

    current_avg_corr = float(corr_values[-1])
    is_regime_break = bool(current_avg_corr > threshold_90th)

    if current_avg_corr >= threshold_90th:
        alert_level = "CRITICAL"
        message = (
            f"Average pairwise correlation ({current_avg_corr:.3f}) exceeds 90th percentile "
            f"({threshold_90th:.3f}). Diversification breakdown detected."
        )
    elif current_avg_corr >= threshold_75th:
        alert_level = "ELEVATED"
        message = (
            f"Average pairwise correlation ({current_avg_corr:.3f}) exceeds 75th percentile "
            f"({threshold_75th:.3f}). Pairwise correlation is elevated."
        )
    else:
        alert_level = "NORMAL"
        message = (
            f"Average pairwise correlation ({current_avg_corr:.3f}) is within normal historical bounds "
            f"(median {historical_median:.3f})."
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
        historical_median=round(historical_median, 4),
        is_regime_break=is_regime_break,
        alert_level=alert_level,
        message=message,
        series=series_points,
    )


class CorrelationService:
    """Service wrapper for Correlation Stability calculations"""

    @staticmethod
    def compute_rolling_correlation(
        returns_df: pd.DataFrame,
        window_days: int = 60,
        min_periods: Optional[int] = None,
    ) -> pd.Series:
        return compute_rolling_avg_correlation(returns_df, window_days, min_periods)

    @staticmethod
    def analyze_stability(
        returns_df: pd.DataFrame,
        window_days: int = 60,
        min_periods: Optional[int] = None,
    ) -> CorrelationStabilityResponse:
        return analyze_correlation_stability(returns_df, window_days, min_periods)
