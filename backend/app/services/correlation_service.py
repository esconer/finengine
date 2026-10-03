"""
Correlation Stability and Regime Break Monitor Service
Calculates rolling 60-day average pairwise correlation and detects diversification breakdown.
"""

from itertools import combinations
from typing import List, Optional
import numpy as np
import pandas as pd

from app.models.schemas import (
    CORRELATION_ALL_PAIRS_MEASURABLE,
    CorrelationDataPoint,
    CorrelationStabilityResponse,
)
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

    The prefactor is 1/C for C = N*(N-1)/2, so this is the average over ALL
    pairs and is only defined on a date where every one of them is measurable.
    That floor is enforced, not assumed: a date with a short leg (a holding
    listed part-way through the lookback) is refused rather than reported from
    the pairs that survived, and if the NEWEST measurable date is short the
    whole series is refused, because a stale window labelled "current" is the
    same defect one row later.

    Args:
        returns_df: Wide DataFrame of asset daily returns (index=Date, columns=tickers)
        window_days: Rolling window size (default 60 trading days)
        min_periods: Minimum number of observations in window (default min(window_days, 30))

    Returns:
        pd.Series indexed by Date with rolling average pairwise correlation values,
        carrying only the dates on which all N*(N-1)/2 pairs were measurable.
        The DENOMINATOR travels with it in `Series.attrs["pairs_expected"]` so a
        caller can publish how many pairs the figure was taken over instead of
        re-deriving C and hoping it agrees.

    Raises:
        ValueError: If no date clears the floor, or if the newest measurable date
            does not - in which case no number is published for this book.
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

    # Average across all N*(N-1)/2 pairs.
    #
    # The prefactor 2/(N*(N-1)) in the docstring is 1/C, so the formula is the
    # book's average pairwise correlation ONLY when all C pairs contributed on
    # that date. `min_periods` leaves a pair unmeasurable whenever either leg is
    # short - a holding listed part-way through the lookback - and `mean(axis=1)`
    # skips those, which published the mean of whatever survived under the label
    # "average pairwise correlation". That number then set the 75th/90th
    # percentiles and therefore `alert_level` / `is_regime_break`: a book-wide
    # diversification break read off a 2-pair mean. So the floor is all C pairs
    # and a date below it is not a measurement of rho_bar at all.
    pairs_df = pd.concat(pair_corrs, axis=1)
    expected_pairs = len(pair_corrs)
    measured_pairs = pairs_df.notna().sum(axis=1)

    # The newest measurable date is the one the caller will read as CURRENT, so
    # a short one refuses the whole series rather than being dropped: dropping it
    # would leave `current_avg_correlation` reporting a stale window under
    # today's label, which is the same defect one row earlier.
    newest = measured_pairs.index[-1]
    newest_measured = int(measured_pairs.iloc[-1])
    if newest_measured < expected_pairs:
        newest_label = (
            newest.strftime("%Y-%m-%d") if hasattr(newest, "strftime") else str(newest)[:10]
        )
        raise ValueError(
            f"Cannot report average pairwise correlation for {newest_label}: only "
            f"{newest_measured} of {expected_pairs} pairs have {min_periods} "
            f"pairwise-complete observations in the trailing {window_days}-day window. "
            f"An average over the remaining {newest_measured} pair(s) is not the "
            f"book-wide figure, so none is published."
        )

    fully_measured = measured_pairs.eq(expected_pairs)
    avg_corr_series = pairs_df.mean(axis=1).where(fully_measured).dropna()

    if avg_corr_series.empty:
        raise ValueError(
            f"Unable to compute rolling correlation: insufficient overlapping data points "
            f"(no date has all {expected_pairs} pairs measurable at {min_periods} "
            f"pairwise-complete observations in a {window_days}-day window)"
        )

    # The denominator rides with the series, so `analyze_correlation_stability`
    # publishes it without re-deriving C from the column count - a second
    # derivation of the same number is a second thing that can disagree with the
    # floor this series was actually gated by.
    #
    # A per-date measured count is deliberately NOT carried: on the published
    # index every count equals `expected_pairs` by construction, so it would be
    # a second copy of one number on every row.
    #
    # `attrs` is SET here rather than relied on to propagate: `mean(axis=1)`,
    # `where` and `dropna` do not all pass it through unchanged, so a silent
    # propagation loss would leave the disclosure null on every point.
    avg_corr_series.attrs["pairs_expected"] = int(expected_pairs)

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

    Every published point also carries ``pairs_contributing`` - the denominator
    the figure was taken over - and ``measurement_status`` naming the condition
    that admitted the date. Without them the floor is invisible in the payload:
    a reader sees a number and has to assume it was the book-wide average.

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

    # Read, not assumed. `compute_rolling_avg_correlation` is the only thing that
    # knows what floor it applied, so it carries the denominator on `attrs`. A
    # stubbed or third-party series has no `attrs`, and then the count stays
    # `None` - "not recorded" - rather than being back-filled with a C derived
    # from a column count that may not be the one the series was gated on.
    pairs_expected = avg_corr_series.attrs.get("pairs_expected")
    pairs_expected = (
        int(pairs_expected) if isinstance(pairs_expected, (int, np.integer)) else None
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
    #
    # `pairs_contributing` is published on EVERY point, not just the newest,
    # because the floor bites on interior dates too: a book with a late-listed
    # leg carries a run of short dates before the tail resumes, and a reader
    # comparing two points of that series has to be able to see that each was
    # taken over the same denominator.
    #
    # Both new fields move together and are None together: a point with no
    # recorded denominator cannot claim the all-pairs condition, since that
    # claim IS the denominator. A one-sided pair (a count without the token, or
    # the token without the count) would assert coverage it cannot show.
    series_points: List[CorrelationDataPoint] = []
    for dt, val in avg_corr_series.items():
        date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
        series_points.append(
            CorrelationDataPoint(
                date=date_str,
                avg_correlation=round(float(val), 4),
                threshold_90th=round(threshold_90th, 4),
                threshold_75th=round(threshold_75th, 4),
                pairs_contributing=pairs_expected,
                measurement_status=(
                    CORRELATION_ALL_PAIRS_MEASURABLE
                    if pairs_expected is not None
                    else None
                ),
            )
        )

    as_of_date = (
        avg_corr_series.index[-1].strftime("%Y-%m-%d")
        if hasattr(avg_corr_series.index[-1], "strftime")
        else str(avg_corr_series.index[-1])[:10]
    )

    # `as_of_date` is a DELIVERED BAR, not a request end. It is the last index
    # of the series above, and that series' index is the returns frame's own date
    # index; `compute_rolling_avg_correlation` refuses the entire series unless
    # that LAST date has all C pairs pairwise-complete, so the date published
    # beside the measurement is a date the measurement was actually taken on -
    # never an interior date left behind by a refused tail. This function holds
    # no clock (it imports none), so a request end is not even available to it.
    #
    # So the honest label is `latest_available_observation`: the token the
    # schema's own vocabulary reserves for "a real, newest delivered bar", and
    # the default on `CointScannerResponse`. It is REUSED rather than invented -
    # a fifth token meaning the same thing would hand a consumer two names for
    # one meaning, which is the defect the vocabulary exists to prevent.
    return CorrelationStabilityResponse(
        as_of=as_of_date,
        as_of_semantics="latest_available_observation",
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
