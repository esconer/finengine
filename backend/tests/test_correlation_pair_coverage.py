"""A date where only SOME pairs are measurable is not a measurement of rho_bar.

`correlation_service.compute_rolling_avg_correlation` documented

    rho_bar_t = (2 / (N * (N - 1))) * sum_{i < j} rho_{i,j,t}

which is the plain mean over ALL C = N(N-1)/2 pairs - the prefactor 2/(N(N-1))
is 1/C, so the formula silently assumes every pair contributed on that date.
It did not. `min_periods = min(window_days, 30)` leaves a pair unmeasurable
whenever a leg has fewer than that many valid observations in the window, and
`pairs_df.mean(axis=1)` skips NaN. So a date with a late-listed leg published
the mean of whatever pairs happened to survive, under the label "average
pairwise correlation", and that number then set the 75th/90th percentiles and
therefore `alert_level` / `is_regime_break`.

Both oracles here are computed from the raw returns frame, not from the
service, so they fail if the service drifts: `_measured_pairs` counts pairs by
pairwise-complete observations, and `_rho_bar_as_documented` re-derives the
docstring's formula with `np.corrcoef`.

Fixed seed throughout; the assertion messages name the pair counts so a failure
states the shortfall rather than just a mismatch.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd
import pytest

from app.services.correlation_service import (
    analyze_correlation_stability,
    compute_rolling_avg_correlation,
)

WINDOW = 60
MIN_PERIODS = min(WINDOW, 30)
DAYS = 220


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------
def _book(late_start, n_late=1, seed=7):
    """Three fully-listed legs plus `n_late` legs that begin trading later.

    `late_start` is the first business day on which the late leg has a return;
    before that it is NaN, which is what a leg listed part-way through the
    lookback looks like to the service.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=DAYS)
    base = rng.normal(0.0004, 0.014, DAYS)
    data = {
        "AAA": base,
        "BBB": 0.5 * base + rng.normal(0.0, 0.010, DAYS),
        "CCC": -0.3 * base + rng.normal(0.0, 0.012, DAYS),
    }
    for k in range(n_late):
        leg = rng.normal(0.0003, 0.016, DAYS)
        if late_start is not None:
            leg[:late_start] = np.nan
        data[f"LATE{k}"] = leg
    return pd.DataFrame(data, index=dates)


def _expected_pair_count(df):
    n = df.shape[1]
    return n * (n - 1) // 2


# ---------------------------------------------------------------------------
# Oracles (independent of the service)
# ---------------------------------------------------------------------------
def _measured_pairs(df, window_days=WINDOW, min_periods=MIN_PERIODS):
    """Per-date count of measurable pairs, counted from the raw returns.

    A pair is measurable at date t iff the two legs share at least
    `min_periods` pairwise-complete observations in the trailing window, which
    is exactly what `Series.rolling(...).corr(other)` needs and what
    dropna-then-count reproduces without using any service code.
    """
    flags = []
    for left, right in combinations(df.columns, 2):
        pair = pd.concat([df[left], df[right]], axis=1).dropna()
        counts = pair.iloc[:, 0].rolling(
            window=window_days, min_periods=min_periods
        ).count()
        flags.append(counts.ge(min_periods))
    return pd.concat(flags, axis=1).sum(axis=1).astype(int)


def _rho_bar_as_documented(df, date, window_days=WINDOW, min_periods=MIN_PERIODS):
    """rho_bar exactly as the docstring defines it, recomputed from raw returns.

    Raises if any pair is unmeasurable at `date`, because the formula is only
    defined when all C pairs contributed.
    """
    n = df.shape[1]
    trailing = df.loc[:date].tail(window_days)
    total = 0.0
    for left, right in combinations(df.columns, 2):
        pair = trailing[[left, right]].dropna()
        if len(pair) < min_periods:
            raise AssertionError(
                f"{date.date()}: pair ({left}, {right}) has {len(pair)} "
                f"pairwise-complete observations, floor is {min_periods}"
            )
        total += float(np.corrcoef(pair.iloc[:, 0], pair.iloc[:, 1])[0, 1])
    return (2.0 / (n * (n - 1))) * total


# ---------------------------------------------------------------------------
# 1. The defect: partial dates published as the average
# ---------------------------------------------------------------------------
class TestNoPartialDateIsPublishedAsTheAverage:
    def test_every_published_date_has_all_pairs_measurable(self):
        """The defect itself. The old service published ~150 dates whose
        'average pairwise correlation' was the mean of 3 of the book's 6 pairs."""
        df = _book(late_start=150, n_late=1)
        measured = _measured_pairs(df)
        expected = _expected_pair_count(df)
        assert expected == 6

        series = compute_rolling_avg_correlation(df, window_days=WINDOW)

        published = measured.reindex(series.index)
        short = published[published < expected]
        assert short.empty, (
            f"{len(short)} of {len(series)} published dates averaged a subset of "
            f"the book's {expected} pairs (e.g. {short.iloc[0]} of {expected} on "
            f"{short.index[0].date()})"
        )

    def test_published_value_equals_the_documented_formula(self):
        """The published number must match the formula the module documents."""
        df = _book(late_start=150, n_late=1)
        series = compute_rolling_avg_correlation(df, window_days=WINDOW)

        assert not series.empty
        for date, value in series.items():
            expected = _rho_bar_as_documented(df, date)
            assert value == pytest.approx(expected, abs=1e-9), (
                f"{date.date()}: published {value!r}, documented formula "
                f"{expected!r} over all {_expected_pair_count(df)} pairs"
            )

    def test_the_partial_dates_are_gone_from_the_series(self):
        df = _book(late_start=150, n_late=1)
        measured = _measured_pairs(df)
        partial_dates = measured.index[measured < _expected_pair_count(df)]

        series = compute_rolling_avg_correlation(df, window_days=WINDOW)

        assert not partial_dates.empty  # the book really is partial for a while
        assert series.index.intersection(partial_dates).empty

    def test_the_baseline_is_ranked_against_fully_covered_dates_only(self):
        """The re-baselining the floor forces, pinned: the 75th/90th thresholds
        and the median are percentiles of the PUBLISHED series, so the partial
        dates cannot reach them."""
        df = _book(late_start=150, n_late=1)
        measured = _measured_pairs(df)
        expected = _expected_pair_count(df)
        full = measured.index[measured >= expected]

        res = analyze_correlation_stability(df, window_days=WINDOW)

        assert [p.date for p in res.series] == [
            d.strftime("%Y-%m-%d") for d in full
        ]
        values = np.array([p.avg_correlation for p in res.series])
        assert res.historical_threshold_90th == pytest.approx(
            np.percentile(values, 90), abs=5e-4
        )
        assert res.historical_threshold_75th == pytest.approx(
            np.percentile(values, 75), abs=5e-4
        )
        assert res.historical_median == pytest.approx(
            np.median(values), abs=5e-4
        )


# ---------------------------------------------------------------------------
# 2. The refusal: a late-listed leg on the NEWEST date
# ---------------------------------------------------------------------------
class TestTheNewestDateIsRefusedRatherThanGuessed:
    def test_it_refuses_instead_of_publishing_the_surviving_pairs(self):
        """A leg 20 days old has fewer than `min_periods` observations, so the
        three pairs containing it are unmeasurable on the newest date. The old
        service published the mean of the other three and called it the book's
        average pairwise correlation."""
        df = _book(late_start=DAYS - 20, n_late=1)
        measured = _measured_pairs(df)
        assert measured.iloc[-1] == 3 < _expected_pair_count(df)

        with pytest.raises(ValueError):
            compute_rolling_avg_correlation(df, window_days=WINDOW)

    def test_the_refusal_names_the_shortfall(self):
        df = _book(late_start=DAYS - 20, n_late=1)
        with pytest.raises(ValueError) as excinfo:
            compute_rolling_avg_correlation(df, window_days=WINDOW)

        detail = str(excinfo.value)
        assert "3" in detail and "6" in detail, (
            f"the refusal must state how many of how many pairs were measurable: {detail!r}"
        )

    def test_the_route_facing_call_refuses_too(self):
        """`GET /analytics/correlation-stability` turns this ValueError into a
        400; it must not be handed a number."""
        df = _book(late_start=DAYS - 20, n_late=1)
        with pytest.raises(ValueError):
            analyze_correlation_stability(df, window_days=WINDOW)

    def test_two_late_legs_leave_three_pairs_and_are_refused(self):
        df = _book(late_start=DAYS - 20, n_late=2)
        measured = _measured_pairs(df)
        # 5 tickers -> 10 pairs; only the 3 among the fully-listed legs measure.
        assert _expected_pair_count(df) == 10
        assert measured.iloc[-1] == 3 < _expected_pair_count(df)
        with pytest.raises(ValueError):
            compute_rolling_avg_correlation(df, window_days=WINDOW)


# ---------------------------------------------------------------------------
# 3. No change for a book that is fully covered
# ---------------------------------------------------------------------------
class TestFullyListedBooksAreUntouched:
    def test_every_measurable_date_is_published(self):
        df = _book(late_start=None)
        measured = _measured_pairs(df)
        expected = _expected_pair_count(df)

        series = compute_rolling_avg_correlation(df, window_days=WINDOW)

        measurable = measured.index[measured >= expected]
        assert list(series.index) == list(measurable)
        # The first window that can carry MIN_PERIODS paired observations ends
        # on the MIN_PERIODS-th row, so that date is the first publishable one.
        assert series.index[0] == df.index[MIN_PERIODS - 1]

    def test_the_values_are_unchanged_for_a_fully_covered_book(self):
        """No-NaN input: the floor admits every date the old code admitted, and
        `mean(axis=1)` over an all-measured row is the documented formula."""
        df = _book(late_start=None)
        series = compute_rolling_avg_correlation(df, window_days=WINDOW)

        assert series.index[-1] == df.index[-1]
        assert series.iloc[-1] == pytest.approx(
            _rho_bar_as_documented(df, df.index[-1]), abs=1e-9
        )
        assert series.between(-1.0, 1.0).all()

    def test_the_monitor_still_answers(self):
        df = _book(late_start=None)
        series = compute_rolling_avg_correlation(df, window_days=WINDOW)
        res = analyze_correlation_stability(df, window_days=WINDOW)

        assert res.current_avg_correlation is not None
        assert res.alert_level in {"NORMAL", "ELEVATED", "CRITICAL"}
        assert res.alert_direction in {
            "within_band",
            "upper_tail_elevation",
            "upper_tail_critical",
            "lower_tail_collapse",
        }
        assert len(res.series) == len(series)
        assert res.as_of == df.index[-1].strftime("%Y-%m-%d")