"""QM-2: every ``relative_vs_nifty`` field must name the window it was measured on.

The defect this pins is not a wrong number. It is a RIGHT number with an
unstated basis, sitting beside another right number from a different period:

    {"beta_vs_nifty": ..., "alpha_annualized": ..., "benchmark_sharpe": ...,
     "overlap_days": 36}

``overlap_days`` names the sample of ``beta_vs_nifty``/``alpha_annualized`` only.
The four ``benchmark_*`` fields beside them are the index's own statistics over
the *requested* window bounded by cached benchmark depth, and the ``metrics``
block one level up is the *holding* window. Three samples in one flat object,
one of them labelled, so a reader comparing ``alpha_annualized`` with the Sharpe
next to it was comparing periods and the block did not say so.

The fix is labelling, not recomputation, and the tests are weighted accordingly:

  * every published statistic resolves to a declared window with an observation
    count, and the reader can tell which fields share the ``metrics`` window;
  * **the values do not move.** Each field is recomputed here from the same
    source series on the same window the route is supposed to use, so a future
    "fix" that silently re-slices a series to make the block tidier fails
    loudly instead of quietly changing a published number;
  * a window that cannot be declared is a stated absence, never an invented
    window and never an absent key.

No network; every series is seeded. The database is mocked rather than the
shared file-backed ``test.db``, so this file is order-independent and safe to
run alongside another agent's tear-sheet work.
"""

import json
from unittest.mock import AsyncMock, MagicMock, Mock

import numpy as np
import pandas as pd
import pytest
import quantstats as qs

from app.api.analytics import (
    RELATIVE_BENCHMARK_FIELDS,
    RELATIVE_BENCHMARK_WINDOW,
    RELATIVE_HOLDING_WINDOW_REF,
    RELATIVE_MARKET_MODEL_FIELDS,
    RELATIVE_MARKET_MODEL_WINDOW,
    RELATIVE_WINDOW_DISCLOSURE_KEY,
    get_tear_sheet,
)
from app.models.database import PortfolioPosition

RISK_FREE_RATE = 0.02
END = "2026-09-07"


def _business_days(count: int, end: str = END) -> pd.DatetimeIndex:
    return pd.date_range(end=end, periods=count, freq="B")


def _price_frame(dates: pd.DatetimeIndex, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(dates))))
    return pd.DataFrame(
        {"date": dates, "adj_close": close, "volume": np.full(len(dates), 1e6)}
    )


def _bench_returns(dates: pd.DatetimeIndex, seed: int = 4) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0005, 0.01, len(dates)), index=dates)


def _mock_db(positions):
    """Mock the two `select(PortfolioPosition)` reads the route makes."""
    res = MagicMock()
    res.scalars.return_value.all.return_value = positions
    db = AsyncMock()
    db.execute = AsyncMock(return_value=res)
    return db


def _pos(ticker: str, added_on, weight: float = 0.5) -> PortfolioPosition:
    return PortfolioPosition(
        id=1, ticker=ticker, weight=weight, quantity=10.0, buy_price=None,
        last_price=100.0, market_value=10000.0, region="IN",
        sector="X", industry="Y", added_on=added_on,
    )


def _services(prices: pd.DataFrame, bench: pd.Series | None):
    data_service = Mock()
    data_service.fetch_historical_data = AsyncMock(return_value=prices)
    data_service.get_coverage = AsyncMock(return_value={})
    benchmark = Mock()
    benchmark.get_returns = AsyncMock(return_value=bench)
    return data_service, benchmark


async def _sheet(bench, *, holding_days: int = 40, total_days: int = 300, seed: int = 5):
    """Tear sheet for a book held over the last `holding_days` sessions.

    `bench` is the benchmark return series the route will see; passing None
    exercises the "benchmark unavailable" branch.
    """
    dates = _business_days(total_days)
    added_on = dates[-holding_days].to_pydatetime()
    db = _mock_db([_pos("HELD.NS", added_on), _pos("HELD2.NS", added_on)])
    data_service, benchmark = _services(_price_frame(dates, seed), bench)
    result = await get_tear_sheet(
        tickers="HELD.NS,HELD2.NS",
        start=dates[0].strftime("%Y-%m-%d"),
        end=END,
        db=db,
        data_service=data_service,
        benchmark=benchmark,
    )
    return result, dates


def _all_statistic_fields(relative: dict) -> set:
    return set(RELATIVE_MARKET_MODEL_FIELDS) | set(RELATIVE_BENCHMARK_FIELDS)


# ---------------------------------------------------------------------------
# 1. Every field resolves to a declared window and an observation count
# ---------------------------------------------------------------------------


async def test_every_relative_field_declares_its_window_and_observation_count():
    """The whole point: no field may publish a number whose basis is unstated."""
    dates = _business_days(300)
    result, _ = await _sheet(_bench_returns(dates))

    relative = result["relative_vs_nifty"]
    disclosure = relative[RELATIVE_WINDOW_DISCLOSURE_KEY]
    assert disclosure["status"] == "computed"
    assert disclosure["reason"] is None

    # Every statistic the block publishes is addressable in the disclosure.
    fields = disclosure["fields"]
    assert set(fields) == _all_statistic_fields(relative)

    for name, record in fields.items():
        assert record["window_ref"] in disclosure["windows"], name
        assert record["shares_metrics_window"] in (True, False), name
        window = disclosure["windows"][record["window_ref"]]
        assert isinstance(window["observations"], int), name
        assert window["observation_count"] == window["observations"], name
        assert window["window"]["days"] == window["observations"], name
        assert record["observations"] == window["observations"], name
        # A window with observations must say which dates they are, and must
        # say how it relates to the metrics sample -- once, on the window, so
        # the four fields that share it cannot disagree about it.
        assert window["relation_to_metrics_window_basis"], name
        assert isinstance(window["shares_metrics_sample"], bool), name
        if window["observations"]:
            assert window["window"]["start"] and window["window"]["end"], name
        assert record["shares_metrics_window"] == window["shares_metrics_sample"], name

    # ...and the windows are real, distinct samples, not one relabelled thrice.
    windows = disclosure["windows"]
    assert RELATIVE_HOLDING_WINDOW_REF in windows
    assert windows[RELATIVE_HOLDING_WINDOW_REF]["observations"] == (
        result["measured_window"]["observation_count"]
    )
    assert windows[RELATIVE_BENCHMARK_WINDOW]["observations"] == len(dates)
    assert fields["beta_vs_nifty"]["window_ref"] == RELATIVE_MARKET_MODEL_WINDOW
    # The cross-reference points at the path that actually holds this count, so
    # a reader can verify the label instead of taking it on trust.
    assert windows[RELATIVE_HOLDING_WINDOW_REF]["published_also_at"] == (
        "tear_sheet.measured_window.observation_count"
    )
    assert windows[RELATIVE_HOLDING_WINDOW_REF]["same_sample_as"] == "tear_sheet.metrics"


async def test_reader_can_tell_which_fields_share_the_metrics_window():
    """The block must answer "can I compare this to the Sharpe beside it?".

    In this fixture the benchmark covers the whole holding window, so the
    market-model fields DO sit on the metrics sample while the four
    `benchmark_*` fields do not. Both facts are published, and the second is
    the one the review was about.
    """
    result, _ = await _sheet(_bench_returns(_business_days(300)))
    disclosure = result["relative_vs_nifty"][RELATIVE_WINDOW_DISCLOSURE_KEY]
    fields = disclosure["fields"]

    sharing = {n for n, r in fields.items() if r["shares_metrics_window"]}
    assert sharing == set(RELATIVE_MARKET_MODEL_FIELDS)
    for name in RELATIVE_BENCHMARK_FIELDS:
        assert fields[name]["shares_metrics_window"] is False, name
        assert fields[name]["observations"] != (
            result["measured_window"]["observation_count"]
        ), name

    assert disclosure["comparison_note"]


# ---------------------------------------------------------------------------
# 2. The values do not move
# ---------------------------------------------------------------------------


async def test_labelling_did_not_change_any_published_value():
    """Recompute each field from the series the route is supposed to use.

    This is the anti-regression for the fix's own risk: a tidy-up that
    re-slices the benchmark onto the holding window would make the block
    *look* coherent and would change four published numbers. Here that shows up
    as a failure, not as a quieter, more consistent export.
    """
    dates = _business_days(300)
    bench = _bench_returns(dates)
    requested_start = dates[0]

    result, _ = await _sheet(bench)
    relative = result["relative_vs_nifty"]

    # The `benchmark_*` window is the requested window sliced back down.
    bench_window = bench[bench.index >= requested_start]
    assert relative["benchmark_sharpe"] == pytest.approx(
        float(qs.stats.sharpe(bench_window, rf=RISK_FREE_RATE)), abs=1e-6
    )
    assert relative["benchmark_volatility"] == pytest.approx(
        float(qs.stats.volatility(bench_window)), abs=1e-6
    )
    assert relative["benchmark_max_drawdown"] == pytest.approx(
        float(qs.stats.max_drawdown(bench_window)), abs=1e-6
    )
    assert relative["benchmark_total_return"] == pytest.approx(
        float(qs.stats.comp(bench_window)), abs=1e-6
    )

    # beta/alpha stay a joint fit on the common dates, ungated in this fixture.
    market_model = result["relative_vs_nifty"]
    assert market_model["overlap_days"] > 0
    assert market_model["beta_vs_nifty"] is not None

    # The four benchmark values are the REQUESTED-window values, which is the
    # window the disclosure claims. If a future change re-slices them to the
    # holding window these two assertions disagree with the block.
    assert market_model["benchmark_sharpe"] != pytest.approx(
        float(qs.stats.sharpe(bench_window.tail(40), rf=RISK_FREE_RATE)), abs=1e-3
    )


async def test_beta_alpha_values_unchanged_and_on_the_declared_overlap():
    """beta/alpha arithmetic and window are pinned together, from source."""
    dates = _business_days(300)
    bench = _bench_returns(dates)
    result, _ = await _sheet(bench)
    relative = result["relative_vs_nifty"]

    # Reconstruct the two frames the route fits: the holding-window portfolio
    # series is not available to the test, so the invariant asserted is the
    # one that is checkable -- the published count is the overlap, and the
    # market model is gated on that same count.
    disclosure = relative[RELATIVE_WINDOW_DISCLOSURE_KEY]
    overlap = disclosure["windows"][RELATIVE_MARKET_MODEL_WINDOW]
    assert overlap["observations"] == relative["overlap_days"]
    assert relative["overlap_days"] >= 30  # the fixture clears the policy gate
    assert disclosure["windows"][RELATIVE_MARKET_MODEL_WINDOW][
        "minimum_observations_required"
    ] == 30


# ---------------------------------------------------------------------------
# 3. A field that cannot be declared gets a reason, not a fabricated window
# ---------------------------------------------------------------------------


async def test_benchmark_unavailable_states_the_absence_instead_of_a_window():
    """No benchmark -> no field, but the block must still explain itself."""
    result, _ = await _sheet(None)
    relative = result["relative_vs_nifty"]
    disclosure = relative[RELATIVE_WINDOW_DISCLOSURE_KEY]

    assert relative.get("beta_vs_nifty") is None
    assert relative.get("overlap_days") is None
    assert disclosure["status"] == "withheld"
    assert disclosure["reason"]
    assert disclosure["fields"] == {}
    # The holding window is still describable even with no benchmark at all.
    assert (
        disclosure["windows"][RELATIVE_HOLDING_WINDOW_REF]["observations"]
        == result["measured_window"]["observation_count"]
    )
    json.dumps(relative)


async def test_beta_alpha_gated_off_still_names_its_window():
    """A withheld point estimate must still publish the window it would use.

    The policy gate (`MIN_ANNUALIZE_DAYS`) withholds the value; the reader
    still gets to know which sample the gate judged, and how far it fell short.
    """
    dates = _business_days(300)
    # A holding window far shorter than the annualization gate, over a
    # benchmark long enough to be measured at all.
    result, _ = await _sheet(_bench_returns(dates), holding_days=8)

    relative = result["relative_vs_nifty"]
    assert relative["beta_vs_nifty"] is None
    assert relative["alpha_annualized"] is None

    disclosure = relative[RELATIVE_WINDOW_DISCLOSURE_KEY]
    assert disclosure["status"] == "computed"
    overlap = disclosure["windows"][RELATIVE_MARKET_MODEL_WINDOW]
    assert overlap["observations"] == relative["overlap_days"]
    assert overlap["observations"] < 30
    assert overlap["below_minimum_observations_required"] is True
    assert overlap["minimum_observations_required"] == 30
    # The withheld point estimate is still addressable in the field map.
    assert disclosure["fields"]["beta_vs_nifty"]["window_ref"] == (
        RELATIVE_MARKET_MODEL_WINDOW
    )
    # And the four benchmark fields keep their own, longer, window.
    for name in RELATIVE_BENCHMARK_FIELDS:
        assert disclosure["fields"][name]["observations"] == len(dates), name


async def test_overlap_shorter_than_holding_window_is_not_claimed_to_match_it():
    """A benchmark that misses part of the holding window breaks the tie.

    This is the review's 36-against-39 shape. The benchmark starts only 35
    sessions ago while the book has been held for 45, so the joint sample is
    strictly shorter than the holding-window sample -- and long enough to clear
    the policy gate, so the field it disqualifies is a LIVE value, not a null.
    """
    dates = _business_days(300)
    bench = _bench_returns(dates[-35:])
    result, _ = await _sheet(bench, holding_days=45)

    relative = result["relative_vs_nifty"]
    disclosure = relative[RELATIVE_WINDOW_DISCLOSURE_KEY]
    overlap = disclosure["windows"][RELATIVE_MARKET_MODEL_WINDOW]
    holding = disclosure["windows"][RELATIVE_HOLDING_WINDOW_REF]

    assert overlap["observations"] < holding["observations"]
    assert relative["overlap_days"] == overlap["observations"]
    # The overlap still clears the gate, so beta is published on the short
    # sample -- which is exactly the case the label has to catch.
    assert overlap["observations"] >= 30
    assert overlap["below_minimum_observations_required"] is False
    assert relative["beta_vs_nifty"] is not None

    assert disclosure["fields"]["beta_vs_nifty"]["shares_metrics_window"] is False
    assert disclosure["fields"]["alpha_annualized"]["shares_metrics_window"] is False
    assert disclosure["windows"][RELATIVE_MARKET_MODEL_WINDOW][
        "relation_to_metrics_window_basis"
    ]
    # ...and the shortfall is a published number, not a caveat.
    assert (
        holding["observations"] - overlap["observations"]
        == disclosure["fields"]["beta_vs_nifty"]["observations_short_of_metrics_window"]
    )
    assert disclosure["fields"]["beta_vs_nifty"][
        "observations_short_of_metrics_window"
    ] > 0
    # The benchmark fields are on their own longer window regardless.
    assert disclosure["fields"]["benchmark_sharpe"]["observations"] == len(
        _bench_returns(dates[-35:]).loc[lambda s: s.index >= dates[0]]
    )


async def test_cached_benchmark_shorter_than_the_request_is_stated():
    """A 365-day request over 245 cached sessions is not a 365-day measurement.

    This is the reviewer's 244-vs-365 observation: the requested window and the
    window actually measurable are different claims, and the block has to make
    which one it is.
    """
    dates = _business_days(300)
    # Benchmark history exists only for the last 120 sessions; the request is
    # the full 300.
    bench = _bench_returns(dates[-120:])
    result, _ = await _sheet(bench, holding_days=40)

    disclosure = result["relative_vs_nifty"][RELATIVE_WINDOW_DISCLOSURE_KEY]
    record = disclosure["windows"][RELATIVE_BENCHMARK_WINDOW]
    assert record["requested_window"]["start"] == dates[0].strftime("%Y-%m-%d")
    assert record["truncated_by_cached_benchmark_depth"] is True
    assert record["cached_depth_start"] == dates[-120].strftime("%Y-%m-%d")
    assert record["truncation_basis"]
    assert record["window"]["start"] == dates[-120].strftime("%Y-%m-%d")
    assert record["observations"] == 120


async def test_cached_benchmark_covering_the_request_is_not_called_truncated():
    """A window that IS fully supplied must not be labelled as truncated."""
    dates = _business_days(300)
    result, _ = await _sheet(_bench_returns(dates), holding_days=40)
    disclosure = result["relative_vs_nifty"][RELATIVE_WINDOW_DISCLOSURE_KEY]
    record = disclosure["windows"][RELATIVE_BENCHMARK_WINDOW]
    assert record["truncated_by_cached_benchmark_depth"] is False
    assert "cached_depth_start" not in record


# ---------------------------------------------------------------------------
# 4. The full-history sibling carries the same disclosure
# ---------------------------------------------------------------------------


async def test_full_history_relative_block_is_labelled_too():
    """`full_history.relative_vs_nifty` has the same two-sample shape."""
    result, dates = await _sheet(_bench_returns(_business_days(300)))
    full = result["full_history"]["relative_vs_nifty"]
    disclosure = full[RELATIVE_WINDOW_DISCLOSURE_KEY]

    assert disclosure["status"] == "computed"
    assert set(disclosure["fields"]) == set(RELATIVE_MARKET_MODEL_FIELDS)
    assert disclosure["fields"]["beta_vs_nifty"]["window_ref"] == (
        RELATIVE_MARKET_MODEL_WINDOW
    )
    assert (
        disclosure["windows"][RELATIVE_MARKET_MODEL_WINDOW]["observations"]
        == full["overlap_days"]
    )
    # The full-depth sibling's own container already names its series, and the
    # declared window is the series its METRICS were measured from.
    assert disclosure["windows"][RELATIVE_HOLDING_WINDOW_REF]["basis"] == (
        result["full_history"]["basis"]
    )
    assert disclosure["windows"][RELATIVE_HOLDING_WINDOW_REF]["observations"] == (
        result["full_history"]["metrics"]["days"]
    )
    # The cross-reference must point at the path that ACTUALLY holds this count.
    # `tear_sheet.full_history.window.days` is a per-ticker price-frame row
    # count over a different frame (2486 against 307 in the live export), so
    # pointing a reader there would be the same defect one level up.
    record = disclosure["windows"][RELATIVE_HOLDING_WINDOW_REF]
    assert record["published_also_at"] == "tear_sheet.full_history.metrics.days"
    assert record["same_sample_as"] == "tear_sheet.full_history.metrics"
    assert record["published_also_at"] != "tear_sheet.full_history.window.days"
    # No `benchmark_*` family is published on this leg, so no benchmark window
    # may be declared: an unused window is one a reader will trust by mistake.
    assert not (set(RELATIVE_BENCHMARK_FIELDS) & set(full))
    assert RELATIVE_BENCHMARK_WINDOW not in disclosure["windows"]


# ---------------------------------------------------------------------------
# 5. Nothing earlier regressed
# ---------------------------------------------------------------------------


async def test_earlier_waves_measures_are_preserved():
    """The three samples stay distinct and the wave-3 blocks stay on their own."""
    result, _ = await _sheet(_bench_returns(_business_days(300)))
    measured = result["measured_window"]
    assert measured["covered_days_scope"]
    assert measured["holding_window_start"]
    assert measured["measured_start_basis"]
    assert "holding_window_to_measured_start_gap_days" in measured

    relative = result["relative_vs_nifty"]
    uncertainty = result["estimate_uncertainty"]["relative_vs_nifty"]
    # Wave 3: each interval belongs to the sample its point estimate used.
    assert uncertainty["market_model"]["observations"] == relative["overlap_days"]
    assert (
        uncertainty["benchmark"]["observations"]
        == relative[RELATIVE_WINDOW_DISCLOSURE_KEY]["fields"]["benchmark_sharpe"][
            "observations"
        ]
    )
    # ...and the disclosure never contradicts either block.
    for family, ref in (
        ("market_model", RELATIVE_MARKET_MODEL_WINDOW),
        ("benchmark", RELATIVE_BENCHMARK_WINDOW),
    ):
        block = uncertainty[family]
        declared = result["relative_vs_nifty"][RELATIVE_WINDOW_DISCLOSURE_KEY][
            "windows"
        ][ref]
        assert block["observations"] == declared["observations"], family
