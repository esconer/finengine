"""NEW-1 + NEW-7: the market-model frame is aligned by DATE, and the block says
which sample its metrics were measured on.

Two defects, both in ``app/api/analytics.py``, both about a number sitting next
to a window that did not produce it.

**NEW-1 — the resampling frame was built by POSITION.** ``_tear_sheet_relative_uncertainty``
took the 2-column block ``np.column_stack([p[:n], b[:n]])``, ``n = min(len(p), len(b))``.
In the reviewed export that paired the 307-session portfolio series
(2025-03-11 -> 2026-09-23) with the OLDEST 307 sessions of a 2476-row NIFTY
series (2016-09-12 -> 2017-12-06) — about eight and a half years apart. The
published point was never wrong: it is fitted by the route on the date
intersection, and re-derived here from the same cache it equals 1.1037. What was
wrong was the BAND, which described a different decade, so the reproduction guard
in ``measure_estimate_uncertainty`` refused it and the payload carried two
``not_computed`` reasons pointing at the estimator. Withholding the point would
delete a right number to hide a left one, so the alignment is fixed instead.

**NEW-7 — the block described one frame and measured another.** ``full_history``
was handed the WIDE per-ticker return frame (2486 rows) while its ``metrics``
were measured on the coverage-gated portfolio series (307 rows). The block
therefore declared a 2486-day window over a CAGR annualised on 307 days:
``(1 + total_return) ** (252 / 307) - 1 = 0.300514`` against
``(1 + total_return) ** (252 / 2486) - 1 = 0.03298``, a 9.11x recompute error for
anyone who trusted the declared window. The disclosure that explains the whole
shortfall — how many dates the book could not cover at 100% weight and why they
were refused rather than renormalised — was already computed and thrown away.

The tests are weighted against the two ways this could be faked:

  * a test with two series of DIFFERENT lengths, asserting the estimator's own
    point equals the published point, so a positional frame cannot pass by
    truncating to a length that happens to match, and
  * the CAGR identity asserted against ``metrics_observation_count`` and NOT
    against ``observation_count``, plus the two being different populations.

Nothing here runs the audit CLI: it reads a frozen export, so a green gate would
say nothing about the code. The database is mocked, not the shared file-backed
``test.db``, so this file is order-independent.
"""

import json
from unittest.mock import AsyncMock, MagicMock, Mock

import numpy as np
import pandas as pd
import pytest

from app.api.analytics import (
    RELATIVE_MARKET_MODEL_FIELDS,
    get_tear_sheet,
    _full_history_evidence,
    _paired_return_columns,
    _tear_sheet_relative_uncertainty,
)
from app.models.database import PortfolioPosition
from app.services.analytics_engine import (
    POINT_NOT_REPRODUCED_BY_ANY_WITNESS,
    POINT_REPRODUCED_BY_WITNESS_ONLY,
    POINT_UNVERIFIED,
    POINT_VERIFIED_BY_WITNESS,
    market_model_statistics,
    market_model_witness,
    measure_estimate_uncertainty,
)

END = "2026-09-07"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _business_days(count: int, end: str = END) -> pd.DatetimeIndex:
    return pd.date_range(end=end, periods=count, freq="B")


def _ohlcv(dates: pd.DatetimeIndex, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.010, len(dates))))
    return pd.DataFrame(
        {"date": dates, "adj_close": close, "volume": np.full(len(dates), 1e6)}
    )


def _bench_returns(dates: pd.DatetimeIndex, seed: int = 4) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0005, 0.010, len(dates)), index=dates)


def _pos(ticker: str, added_on, weight: float = 0.5) -> PortfolioPosition:
    return PortfolioPosition(
        id=1, ticker=ticker, weight=weight, quantity=10.0, buy_price=None,
        last_price=100.0, market_value=10000.0, region="IN",
        sector="X", industry="Y", added_on=added_on,
    )


def _mock_db(positions) -> MagicMock:
    res = MagicMock()
    res.scalars.return_value.all.return_value = positions
    db = AsyncMock()
    db.execute = AsyncMock(return_value=res)
    return db


def _services(prices_by_ticker, bench, *, cached_start=None):
    data_service = Mock()
    data_service.fetch_historical_data = AsyncMock(
        side_effect=lambda ticker, start, end: prices_by_ticker[ticker]
    )
    if cached_start is None:
        data_service.get_coverage = AsyncMock(return_value={})
    else:
        data_service.get_coverage = AsyncMock(
            return_value={"cached_start": cached_start}
        )
    benchmark = Mock()
    benchmark.get_returns = AsyncMock(return_value=bench)
    return data_service, benchmark


async def _sheet(
    bench,
    *,
    tickers=("AAA.NS", "AAA2.NS", "BBB.NS"),
    total_days: int = 300,
    late_listing: int = 0,
    bench_extra_days: int = 0,
    seed: int = 5,
):
    """A tear sheet whose legs and benchmark have INDEPENDENT depths.

    `late_listing` makes the LAST ticker list only that many sessions before the
    end while the others keep the whole history — which is what makes the wide
    per-ticker return frame and the coverage-gated portfolio series different
    lengths, the NEW-7 shape, at route level rather than in the export. A book
    where every leg is late would not do it: the whole book would be short, the
    coverage gate would pass everywhere, and both lengths would agree.

    `bench_extra_days` gives the benchmark a deeper history than the book, which
    is what makes the two legs of the market-model frame different lengths — the
    NEW-1 shape.
    """
    dates = _business_days(total_days)
    added_on = dates[0].to_pydatetime()
    db = _mock_db([_pos(t, added_on, 1.0 / len(tickers)) for t in tickers])

    listed = dates[-late_listing:] if late_listing else dates
    prices_by_ticker = {
        t: _ohlcv(listed if t is tickers[-1] else dates, seed + i)
        for i, t in enumerate(tickers)
    }
    bench_dates = _business_days(total_days + bench_extra_days)
    data_service, benchmark = _services(
        prices_by_ticker, _bench_returns(bench_dates), cached_start=None
    )
    result = await get_tear_sheet(
        tickers=",".join(tickers),
        start=dates[0].strftime("%Y-%m-%d"),
        end=END,
        db=db,
        data_service=data_service,
        benchmark=benchmark,
    )
    return result, dates


def _estimator_own_point(frame: np.ndarray) -> float:
    """beta as `market_model_statistics` computes it on one sample.

    The joint non-finite drop is `measure_estimate_uncertainty`'s own
    (`_finite_observation_block` keeps a row only when BOTH columns are finite),
    so it is applied here first — the statistics callable itself does not do it.
    """
    clean = frame[np.isfinite(frame).all(axis=1)]
    suite = market_model_statistics(252)
    return float(np.asarray(suite["beta"](clean.reshape(-1, 1, 2))).ravel()[0])


# ---------------------------------------------------------------------------
# A. the market-model frame is paired on DATE, never on position
# ---------------------------------------------------------------------------


def test_paired_columns_intersect_the_index_of_different_length_series():
    """The regression shape: 307 rows on one calendar, 2620 on another.

    A positional frame would take the portfolio's 307 values and the benchmark's
    FIRST 307 — a window roughly nine years earlier — and produce a block whose
    band describes that window. The helper must intersect instead.
    """
    bench_index = pd.bdate_range("2016-09-12", "2026-09-25")
    port_index = bench_index[-307:]
    rng = np.random.default_rng(11)
    benchmark = pd.Series(rng.normal(0.0004, 0.010, len(bench_index)), index=bench_index)
    portfolio = pd.Series(rng.normal(0.0006, 0.011, 307), index=port_index)

    frame = _paired_return_columns(portfolio, benchmark)
    assert frame.shape == (307, 2)
    # The pair really is the shared DATES, so row 0 is bench_index[-307] for both
    # columns — the portfolio's first session, not the benchmark's first.
    np.testing.assert_allclose(frame[:, 0], portfolio.to_numpy())
    np.testing.assert_allclose(frame[:, 1], benchmark.loc[port_index].to_numpy())
    # The date-aligned beta and the position-aligned beta are different numbers.
    common = port_index
    aligned = float(portfolio.cov(benchmark.loc[common]) / benchmark.loc[common].var())
    head = benchmark.to_numpy()[:307]
    positional = float(
        np.cov(portfolio.to_numpy(), head, ddof=1)[0, 1] / np.var(head, ddof=1)
    )
    assert abs(aligned - positional) > 0.1, "the two must differ for this to bite"


def test_relative_uncertainty_own_point_matches_published_on_different_lengths():
    """The falsifiable form: the estimator's own point must REPRODUCE the published one.

    With two unequal-length series, the published beta is fitted on the date
    intersection. If the frame were built by position the estimator's own point
    would be a different statistic, the reproduction guard would withhold the
    band, and this test fails on `status` — the exact symptom in the export.
    """
    bench_index = pd.bdate_range("2016-09-12", "2026-09-25")
    port_index = bench_index[-307:]
    rng = np.random.default_rng(11)
    bench_values = rng.normal(0.0004, 0.010, len(bench_index))
    # the portfolio is genuinely a function of the benchmark on the SHARED dates
    port_values = 1.1037 * bench_values[-307:] + rng.normal(0.0002, 0.004, 307)
    benchmark = pd.Series(bench_values, index=bench_index)
    portfolio = pd.Series(port_values, index=port_index)

    overlap = benchmark.loc[port_index]
    beta = float(portfolio.cov(overlap) / overlap.var())
    alpha = float((portfolio.mean() - beta * overlap.mean()) * 252)
    published = {
        "beta_vs_nifty": round(beta, 4),
        "alpha_annualized": round(alpha, 4),
    }

    block = _tear_sheet_relative_uncertainty(
        portfolio, benchmark, published, scope="unit test",
    )

    # The estimator's own point, on the frame the block was actually given,
    # reproduces the published point: that identity is what earns the band.
    own = _estimator_own_point(_paired_return_columns(portfolio, benchmark))
    assert own == pytest.approx(published["beta_vs_nifty"], abs=1e-4)
    assert block["status"] == "computed", block["estimates"]
    for field in RELATIVE_MARKET_MODEL_FIELDS:
        entry = block["estimates"][field]
        assert entry["status"] == "computed", (field, entry["reason"])
        assert entry["reason"] is None, field
        assert entry["conf_int"] is not None, field
        assert entry["point"] == published[field]
    # 307 measured observations, not 2620 and not 0.
    assert block["observations"] == 307
    assert block["observation_columns"] == 2


def test_relative_uncertainty_refuses_to_pair_unindexed_blocks_of_unequal_length():
    """No index, no alignment, and lengths disagree: publish an absence.

    The alternative would be exactly the positional pairing that was the defect,
    so the two unlabelled arrays yield no frame and the block says the sample was
    not measured rather than inventing one.
    """
    rng = np.random.default_rng(3)
    short = rng.normal(0.0, 0.01, 120)
    long = rng.normal(0.0, 0.01, 400)
    assert _paired_return_columns(short, long).shape == (0, 2)
    # equal lengths are still fine: nothing has to be re-paired
    assert _paired_return_columns(short, short.copy()).shape == (120, 2)


def test_holding_leg_drops_gaps_jointly_not_per_leg():
    """The holding-window leg CAN mis-fire, and not for the reason expected.

    The brief suspected length truncation there. That is impossible: the route
    hands the helper `aligned_p`/`aligned_b`, both sliced with the same
    `.loc[common]`, so they are always equal length.

    The reachable mechanism is different and worse in kind. The old helper ran
    `_finite_return_values` on each leg SEPARATELY, so a NaN in the benchmark at
    row 5 and none at row 17 removed row 5 from the benchmark column and row 17
    from the portfolio column — leaving 37 rows in each column that are no longer
    the same 37 dates. A gap in one leg silently re-dates every row after it.

    Here the portfolio is gap-free and the benchmark has three gaps, which is
    the ordinary shape: the portfolio series is coverage-gated and cannot have
    interior gaps, while a cached benchmark series can. pandas `.cov()` skips
    NaN pairwise, so the route's own beta uses the 37 shared dates; the old
    frame used a different 37.
    """
    index = pd.bdate_range("2024-01-01", periods=40)
    rng = np.random.default_rng(7)
    benchmark = pd.Series(rng.normal(0.0, 0.01, 40), index=index)
    benchmark.iloc[[5, 17, 28]] = np.nan
    portfolio = pd.Series(rng.normal(0.0, 0.012, 40), index=index)

    shared = portfolio.notna() & benchmark.notna()
    route_beta = round(
        float(portfolio[shared].cov(benchmark[shared]) / benchmark[shared].var()), 4
    )
    frame = _paired_return_columns(portfolio, benchmark)

    # one index in, one frame out: the gaps are NOT dropped here, so the two
    # columns can never be re-dated relative to each other.
    assert frame.shape == (40, 2)
    assert int(np.isfinite(frame).all(axis=1).sum()) == int(shared.sum()) == 37

    # and the estimator's own point on that frame is the route's beta, not the
    # value the per-leg filter produced
    own = _estimator_own_point(frame)
    assert own == pytest.approx(route_beta, abs=1e-4)
    # the old per-leg pairing demonstrably disagreed: it truncated each leg to
    # its OWN finite length, so the portfolio's first 37 rows were paired with
    # the benchmark's first 37 — the benchmark's rows 0-4 and 6-17, not the
    # 37 dates the two actually share.
    old_p = portfolio[np.isfinite(portfolio)].to_numpy()
    old_b = benchmark[np.isfinite(benchmark)].to_numpy()
    n = min(old_p.size, old_b.size)
    mispaired = round(
        float(
            np.cov(old_p[:n], old_b[:n], ddof=1)[0, 1] / np.var(old_b[:n], ddof=1)
        ),
        4,
    )
    assert abs(mispaired - route_beta) > 1e-3, "the two must differ for this to bite"


async def test_route_publishes_a_band_for_the_full_depth_market_model():
    """End to end: a benchmark DEEPER than the book still gets a real interval.
    This is the export's shape at route level — 300 sessions of book against a
    benchmark with 200 more — and the assertion is that the band is present and
    was measured on the overlap, not on a truncated head.
    """
    result, dates = await _sheet(
        _bench_returns(_business_days(500)), total_days=300, bench_extra_days=200
    )
    full = result["full_history"]
    block = full["estimate_uncertainty"]["relative_vs_nifty"]
    estimates = block["estimates"]
    for field in RELATIVE_MARKET_MODEL_FIELDS:
        entry = estimates[field]
        assert entry["status"] == "computed", (field, entry["reason"])
        assert entry["conf_int"] is not None, field
        assert entry["point"] == full["relative_vs_nifty"][field]
    # The interval belongs to the joint overlap, and the block says how long it is.
    assert block["observations"] == full["relative_vs_nifty"]["overlap_days"]
    assert block["observations"] >= 30
    json.dumps(block)


# ---------------------------------------------------------------------------
# A2. the independent witness, and the trap in its default
# ---------------------------------------------------------------------------


def _live_case():
    """The export's case: a 307-session book against a 2620-session benchmark."""
    bench_index = pd.bdate_range("2016-09-12", "2026-09-25")
    port_index = bench_index[-307:]
    rng = np.random.default_rng(11)
    bench_values = rng.normal(0.0004, 0.010, len(bench_index))
    port_values = 1.1037 * bench_values[-307:] + rng.normal(0.0002, 0.004, 307)
    benchmark = pd.Series(bench_values, index=bench_index)
    portfolio = pd.Series(port_values, index=port_index)
    overlap = benchmark.loc[port_index]
    beta = float(portfolio.cov(overlap) / overlap.var())
    alpha = float((portfolio.mean() - beta * overlap.mean()) * 252)
    published = {
        "beta_vs_nifty": round(beta, 4),
        "alpha_annualized": round(alpha, 4),
    }
    aligned = np.column_stack([portfolio.to_numpy(), overlap.to_numpy()])
    # what the positional truncation built: the book against the OLDEST 307
    # sessions of the benchmark
    mispaired = np.column_stack(
        [portfolio.to_numpy(), benchmark.to_numpy()[:307]]
    )
    return published, aligned, mispaired


def test_witness_frame_differs_from_the_estimator_frame_in_the_mispaired_case():
    """The trap, stated as a test: a default-derived witness would null the point.

    `witness_observations` defaults to `observations`. Handing the engine the
    mis-paired estimator frame as BOTH makes the witness agree with the liar
    rather than with the published value, and the guard's documented outcome is
    `point: null` — a correct number deleted. So the two frames must be able to
    differ, and the call site must be the reason they do.
    """
    published, aligned, mispaired = _live_case()
    kwargs = dict(
        scope="unit test",
        point_tolerance=1e-4,
        statistic_names={"beta_vs_nifty": "beta"},
        witness=market_model_witness(252),
    )
    # witness derived from the SAME mis-paired frame -> point deleted
    trapped = measure_estimate_uncertainty(
        mispaired, market_model_statistics(252), published,
        witness_observations=mispaired, **kwargs,
    )["estimates"]["beta_vs_nifty"]
    assert trapped["point"] is None
    assert trapped["point_status"] == POINT_NOT_REPRODUCED_BY_ANY_WITNESS

    # witness derived from the frame the point was PUBLISHED on -> point kept,
    # and the guard names the ESTIMATOR as the failing side
    rescued = measure_estimate_uncertainty(
        mispaired, market_model_statistics(252), published,
        witness_observations=aligned, **kwargs,
    )["estimates"]["beta_vs_nifty"]
    assert rescued["point"] == published["beta_vs_nifty"]
    assert rescued["point_status"] == POINT_REPRODUCED_BY_WITNESS_ONLY
    assert "ESTIMATOR is the failing side" in rescued["reason"]
    # ...and the band is still withheld: a disagreement means the frame is not
    # the sample, whatever the witness says about the point.
    assert rescued["conf_int"] is None


def test_witness_cannot_delete_a_right_number_when_it_cannot_run():
    """The false-positive-safe default, reached through the real call shape.

    The brief asked for a test showing a shared mis-pairing does NOT null the
    point. That is not the engine's contract and asserting it would be asserting
    a defect: `point: null` is reachable precisely when a witness RUNS and
    contradicts the payload, by design (analytics_engine.py:1327). The safety
    property that IS true, and that a caller can rely on, is that a witness
    which cannot deliver a verdict — absent, raising, or handed an empty frame —
    never costs a correct number.
    """
    published, _, mispaired = _live_case()
    kwargs = dict(
        scope="unit test",
        point_tolerance=1e-4,
        statistic_names={"beta_vs_nifty": "beta"},
        witness=market_model_witness(252),
    )
    for label, wo in (
        ("empty frame", np.zeros((0, 2))),
        ("no witness_observations", None),
    ):
        block = measure_estimate_uncertainty(
            mispaired, market_model_statistics(252), published,
            witness_observations=wo, **kwargs,
        )
        entry = block["estimates"]["beta_vs_nifty"]
        assert entry["point"] == published["beta_vs_nifty"], label
        assert entry["point_status"] == POINT_UNVERIFIED, label
        assert block["witness_status"] in {"witness_failed", "not_supplied"}, label

    # and the helper never reaches that state on a real sample, because it
    # passes the aligned frame explicitly
    block = _tear_sheet_relative_uncertainty(
        *_live_series(), published, scope="unit test",
    )
    assert block["status"] == "computed"
    assert block["witness_status"] == "witness_ran"


def _live_series():
    bench_index = pd.bdate_range("2016-09-12", "2026-09-25")
    port_index = bench_index[-307:]
    rng = np.random.default_rng(11)
    bench_values = rng.normal(0.0004, 0.010, len(bench_index))
    return (
        pd.Series(1.1037 * bench_values[-307:] + rng.normal(0.0002, 0.004, 307),
                  index=port_index),
        pd.Series(bench_values, index=bench_index),
    )


async def test_route_publishes_a_witness_verified_point_and_keeps_it():
    """End to end: the point is verified by TWO independent paths, not one.

    The point the payload carries is unchanged — it was always right — and now
    two separate code paths re-derive it from the frame it was measured on. The
    band is published because the estimator now agrees, so `point_status` is the
    SUCCESS value `verified_against_independent_witness`, not the
    failure-branch `published_point_reproduced_by_independent_witness`; see
    `test_witness_failure_status_is_unreachable_once_the_frame_is_aligned`.
    """
    result, _ = await _sheet(
        _bench_returns(_business_days(500)), total_days=300, bench_extra_days=200
    )
    full = result["full_history"]
    block = full["estimate_uncertainty"]["relative_vs_nifty"]
    assert block["witness_status"] == "witness_ran"
    for field in RELATIVE_MARKET_MODEL_FIELDS:
        entry = block["estimates"][field]
        assert entry["status"] == "computed", (field, entry["reason"])
        assert entry["conf_int"] is not None, field
        assert entry["point"] == full["relative_vs_nifty"][field]
        assert entry["point"] is not None, field
        assert entry["point_status"] == POINT_VERIFIED_BY_WITNESS, field
        # the point is retained whatever happens; it is never nulled here
        assert entry["point"] is not None


def test_witness_failure_status_is_unreachable_once_the_frame_is_aligned():
    """`published_point_reproduced_by_independent_witness` needs a BAD frame.

    The brief's updated criterion asked for that status on both estimates. It is
    reachable only inside `_adjudicated_entry`, which runs only when the
    estimator's own point MISSES the published one — so it can never coexist
    with `status == "computed"`, which requires the identity test to have
    passed. This test pins the real post-fix state and documents why the two
    requirements are mutually exclusive rather than quietly asserting the
    weaker one.
    """
    published, aligned, _ = _live_case()
    block = _tear_sheet_relative_uncertainty(
        *_live_series(), published, scope="unit test",
    )
    for field in RELATIVE_MARKET_MODEL_FIELDS:
        entry = block["estimates"][field]
        assert entry["status"] == "computed", field
        assert entry["point_status"] == POINT_VERIFIED_BY_WITNESS, field
        assert entry["point_status"] != POINT_REPRODUCED_BY_WITNESS_ONLY, field
    # The estimator's own point does reproduce the published one, which is the
    # only reason a band exists at all.
    assert _estimator_own_point(aligned) == pytest.approx(
        published["beta_vs_nifty"], abs=1e-4
    )



# ---------------------------------------------------------------------------
# B. `full_history` states the sample its metrics were measured on
# ---------------------------------------------------------------------------


def test_full_history_evidence_publishes_both_populations_separately():
    """A wide frame and a metrics series are two samples, and it says so."""
    index = pd.bdate_range("2016-09-12", periods=2486)
    wide = pd.DataFrame(
        {
            "A.NS": np.r_[np.full(2100, np.nan), np.linspace(-0.01, 0.01, 386)],
            "B.NS": np.linspace(-0.01, 0.01, 2486),
        },
        index=index,
    )
    metrics_series = pd.Series(
        np.linspace(-0.01, 0.01, 307),
        index=pd.bdate_range("2025-03-11", periods=307),
    )
    evidence = _full_history_evidence(
        wide,
        requested_start="2016-09-12",
        requested_end="2026-09-25",
        metrics_series=metrics_series,
    )

    assert evidence["observation_count"] == 2486
    assert evidence["metrics_observation_count"] == 307
    assert evidence["metrics_window"] == {
        "start": "2025-03-11",
        "end": metrics_series.index[-1].strftime("%Y-%m-%d"),
        "days": 307,
    }
    # the two are different windows, and the block refuses to blur them
    assert evidence["window"]["start"] == "2016-09-12"
    assert evidence["window"]["days"] != evidence["metrics_window"]["days"]
    assert evidence["metrics_observation_count_basis"]


def test_annualized_flag_states_the_population_it_tested():
    """`annualized` certifies a sample; the block must name which one.

    It has always tested the WIDE frame: 2486 frame rows and a minimum per-ticker
    return count of 383. That is a true statement about the frame and a silent
    one about the 307-row series the metrics are annualised on, so the two counts
    it tested are published next to the boolean.
    """
    index = pd.bdate_range("2016-09-12", periods=2486)
    wide = pd.DataFrame(
        {
            "A.NS": np.r_[np.full(2100, np.nan), np.linspace(-0.01, 0.01, 386)],
            "B.NS": np.linspace(-0.01, 0.01, 2486),
        },
        index=index,
    )
    evidence = _full_history_evidence(
        wide,
        requested_start="2016-09-12",
        requested_end="2026-09-25",
        metrics_series=pd.Series(
            np.linspace(-0.01, 0.01, 307), index=pd.bdate_range("2025-03-11", periods=307)
        ),
    )
    minimum = min(evidence["per_ticker_return_observations"].values())
    assert evidence["annualized"] is True
    assert evidence["annualization_tested_frame_observations"] == 2486
    assert evidence["annualization_tested_minimum_ticker_return_observations"] == minimum
    assert minimum == 386
    assert "per-ticker return frame" in evidence["annualized_population"]
    # the metrics sample's own status is published separately, so a reader does
    # not have to infer it from a flag about a different population
    assert evidence["metrics_meet_minimum_observations"] is True


async def test_route_declares_the_window_its_metrics_were_measured_on():
    """The live shape, at route level: one late leg shortens the book only.

    Two of the three legs keep the whole history and the last lists late, so the
    wide per-ticker return frame covers the request while the coverage-gated
    portfolio series covers only the sessions where the whole book traded. Those
    are two different lengths, and the block has to publish both.

    On tolerance: the identity cannot be asserted to 1e-9 against the published
    numbers, and the reason is rounding, not alignment. `_q` rounds every metric
    to 6 dp, so `total_return` carries up to 5e-7 of display error and
    `(1 + t) ** (252 / days)` amplifies it by 252/days. In the export that is a
    5.03e-07 residual — a factor of ~500 above 1e-9, and `round(0.3005145033, 6)`
    is 0.300515 against a published 0.300514. So the payload-level assertion is
    made at one display step, the exact 1e-9 identity is asserted against
    UNROUNDED values, and the falsifiable part — that the exponent is
    `metrics_observation_count` and not `observation_count` — is asserted as a
    factor, not a decimal.
    """
    result, dates = await _sheet(
        _bench_returns(_business_days(300)), total_days=300, late_listing=120
    )
    full = result["full_history"]
    metrics = full["metrics"]

    # the metrics are measured on the shorter series
    assert full["metrics_observation_count"] == metrics["days"]
    assert full["metrics_observation_count"] < full["observation_count"]
    assert full["metrics_window"]["days"] == metrics["days"]
    # The first portfolio RETURN needs two price rows, so the metrics window
    # opens one session after the late leg's first price, not on it.
    assert full["metrics_window"]["start"] == dates[-119].strftime("%Y-%m-%d")
    assert full["metrics_window"]["end"] == dates[-1].strftime("%Y-%m-%d")
    assert full["metrics_observation_count_basis"]

    # the identity, at the precision the payload actually carries
    published_days = metrics["days"]
    expected = (1 + metrics["total_return"]) ** (252 / published_days) - 1
    assert metrics["cagr"] == pytest.approx(expected, abs=1e-6)

    # the same identity on the DECLARED frame window is wrong by a wide factor,
    # which is what makes publishing both counts necessary rather than tidy
    wrong = (1 + metrics["total_return"]) ** (
        252 / full["observation_count"]
    ) - 1
    assert abs(wrong / expected) < 0.5, "frame-window recompute must be visibly wrong"
    assert metrics["cagr"] != pytest.approx(wrong, abs=1e-6)


def test_cagr_identity_is_exact_on_the_unrounded_series_and_uses_days():
    """The 1e-9 form of the identity, against values `_q` never rounded.

    `measure_estimate_uncertainty`'s own reproduction guard already runs at
    1e-9, so this is the same standard applied to the annualisation count. It is
    stated on unrounded inputs because the published payload rounds to 6 dp.
    """
    import quantstats as qs

    rng = np.random.default_rng(21)
    days = 307
    series = pd.Series(
        rng.normal(0.0006, 0.011, days), index=pd.bdate_range("2025-03-11", periods=days)
    )
    total = float(qs.stats.comp(series))
    cagr = float(qs.stats.cagr(series))
    assert cagr == pytest.approx((1 + total) ** (252 / days) - 1, abs=1e-9)
    # and the frame count the block also publishes gives a materially different
    # number, so the exponent is not interchangeable between the two
    assert cagr != pytest.approx(
        (1 + total) ** (252 / 2486) - 1, abs=1e-9
    )


async def test_route_publishes_the_partial_coverage_disclosure_it_used_to_discard():
    """The refusal that shortened the series is now a published number.

    2179 of 2486 dates in the export failed the 100%-weight coverage gate and
    were refused rather than renormalised. That difference is exactly
    `observation_count - metrics_observation_count`, and the block states it
    instead of leaving a reader to find a 76-row unexplained shortfall.
    """
    result, _ = await _sheet(
        _bench_returns(_business_days(300)), total_days=300, late_listing=120
    )
    full = result["full_history"]
    assert full["partial_coverage_days"] == (
        full["observation_count"] - full["metrics_observation_count"]
    )
    assert full["partial_coverage_days"] > 0
    assert full["measurable_return_rows"] == full["observation_count"]
    assert "refused rather than renormalised" in full["partial_coverage_days_reason"]
    assert "partial_coverage_days" in full["measurement_frame_note"]


async def test_full_history_disclosure_survives_serialization():
    """Every added field is JSON-safe, and the block still has its audit keys."""
    result, _ = await _sheet(
        _bench_returns(_business_days(300)), total_days=300, late_listing=120
    )
    full = result["full_history"]
    for key in (
        "scope", "window", "observation_count", "metrics_observation_count",
        "metrics_window", "annualized", "annualized_population",
        "partial_coverage_days",
    ):
        assert key in full, key
    assert full["scope"] == "full_exchange_history"
    json.dumps(full)   # no NaN / numpy scalars leak into the payload


async def test_published_beta_is_the_date_aligned_one_not_the_truncated_head():
    """The published point is re-derived here from the seeded inputs, both ways.

    A "fix" that re-sliced a series to make the frame tidier would publish the
    head-truncated number instead. The test builds both candidates from the same
    seed the route used and asserts the payload carries the date-aligned one, to
    the last published digit. The disclosure is additive: no published value is a
    function of whether the frame was fixed.
    """
    result, dates = await _sheet(
        _bench_returns(_business_days(500)), total_days=300, bench_extra_days=200
    )
    published = result["full_history"]["relative_vs_nifty"]["beta_vs_nifty"]
    assert published is not None

    # Re-derive both candidates from the same seeded series the route consumed.
    prices = {t: _ohlcv(dates, 5 + i) for i, t in enumerate(("AAA.NS", "AAA2.NS", "BBB.NS"))}
    frame = pd.DataFrame(
        {t: _ohlcv(dates, 5 + i)["adj_close"].to_numpy() for i, t in enumerate(prices)},
        index=dates,
    ).pct_change(fill_method=None).iloc[1:]
    weight = 1.0 / 3.0
    book = sum(frame[t] * weight for t in prices)
    bench_all = _bench_returns(_business_days(500))

    overlap = book.index.intersection(bench_all.index)
    p, b = book.loc[overlap], bench_all.loc[overlap]
    aligned = round(float(p.cov(b) / b.var()), 4)

    head = bench_all.to_numpy()[: len(p)]
    positional = round(
        float(np.cov(p.to_numpy(), head, ddof=1)[0, 1] / np.var(head, ddof=1)), 4
    )
    assert aligned != positional, "the two must differ for this to bite"
    assert published == aligned
    assert published != positional
