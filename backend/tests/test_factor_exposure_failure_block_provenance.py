"""A failed factor regression publishes the window it failed on.

THE DEFECT.  `factor_exposure_analysis` fits a per-position OLS with a
Newey-West covariance inside a `try`, and its `except` published:

    positions_exp[ticker] = {
        ...
        'is_limited_history': False, 'history_warning': None,
        'data_points': 0, 'error': 'factor regression failed'
    }

Both of those keys are hard-coded, and both are false statements about the
window.  `data_pts` and `is_limited` are computed a few lines ABOVE, from the
ticker and the benchmark, and are already in scope - they are the measured
active row count and the measured short-history flag, and the success path three
keys above publishes exactly those.  So a ticker with 180 usable rows that
failed on the HAC fit published `data_points: 0` and
`is_limited_history: False`.

Nothing measured was wrong.  The diagnostic surface was, and that is the same
defect class as publishing a substituted number: a reader who is diagnosing the
null `alpha` reads `data_points: 0` and concludes there is no data here, when
the truth is that there were 180 rows and the regression failed on them.  Both
readings send them to the same place - widen the history - and one of them is
wrong.  A number that is a lie about the window is not better than a number
that is missing.

`history_warning` is the window's, not the fit's, so it moves on the same
condition the success path uses.  The `error` string is the one thing that
really did happen and is kept.
"""

import asyncio

import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import AnalyticsEngine

ENGINE = AnalyticsEngine()

DAYS = 180


def _prices(active_days: int = DAYS) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    index = pd.bdate_range("2024-01-02", periods=DAYS)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, DAYS)))
    # Ticker B only traded on the trailing `active_days` rows; the rest are the
    # pre-listing NaN gap the engine's active-history filter is designed for.
    traded = np.full(DAYS, np.nan)
    traded[-active_days:] = close[-active_days:]
    return pd.DataFrame({"AAA.NS": close, "BBB.NS": traded}, index=index)


def _benchmark(days: int = DAYS) -> pd.Series:
    rng = np.random.default_rng(12)
    return pd.Series(
        rng.normal(0.0002, 0.008, days), index=pd.bdate_range("2024-01-02", periods=days)
    )


def _exposures(prices, benchmark=None, monkeypatch=None):
    """The production call, with the HAC fit optionally forced to fail."""
    if monkeypatch is not None:
        def _explode(*args, **kwargs):
            raise RuntimeError("simulated HAC fit failure")

        monkeypatch.setattr(
            AnalyticsEngine, "_ols_with_published_se", staticmethod(_explode)
        )
    return asyncio.run(
        ENGINE.factor_exposure_analysis(prices, benchmark_data=benchmark or _benchmark())
    )


# ---------------------------------------------------------------------------
# The diagnostic surface.
# ---------------------------------------------------------------------------

def test_a_failed_fit_publishes_the_row_count_it_actually_had(monkeypatch):
    result = _exposures(_prices(), monkeypatch=monkeypatch)
    leg = result["positions"]["AAA.NS"]

    assert leg["error"] == "factor regression failed"
    assert leg["alpha"] is None
    assert leg["market"] is None
    # Pre-fix this was 0, which is a claim that nothing was measured.
    assert leg["data_points"] > 0
    assert leg["data_points"] == pytest.approx(DAYS, abs=2)
    assert leg["data_points"] != 0


def test_a_failed_fit_does_not_claim_the_history_was_adequate(monkeypatch):
    """180 usable rows is not limited history, and saying so was a second lie."""
    result = _exposures(_prices(), monkeypatch=monkeypatch)
    leg = result["positions"]["AAA.NS"]

    assert leg["data_points"] >= 30
    assert leg["is_limited_history"] is False
    assert leg["history_warning"] is None


def test_a_failed_fit_on_a_short_window_still_reports_the_short_window(monkeypatch):
    """The other side: the flag is measured, so it must survive a failure too.

    A ticker with only a short tail of active rows is genuinely limited, and the
    failure must not overwrite that with `False` - that would send a reader who
    IS short of data off to look for a regression bug instead.
    """
    result = _exposures(_prices(active_days=20), monkeypatch=monkeypatch)
    leg = result["positions"]["BBB.NS"]

    assert leg["error"] == "factor regression failed"
    assert leg["data_points"] < 30
    assert leg["is_limited_history"] is True
    # The warning quotes the SAME number the field publishes, which is the
    # invariant the pre-fix block broke by publishing 0 and no warning.
    assert str(leg["data_points"]) in leg["history_warning"]
    assert "active trading days" in leg["history_warning"]


def test_the_failure_and_success_blocks_publish_the_same_window_facts(monkeypatch):
    """The strongest form: the two blocks must AGREE about the window.

    The only difference between them is what happened to the fit, so anything
    they disagree on is a claim about the data - and that is exactly the defect.
    """
    prices = _prices()
    good = _exposures(prices)
    bad = _exposures(prices, monkeypatch=monkeypatch)

    for ticker, leg in good["positions"].items():
        failed = bad["positions"][ticker]
        assert failed["data_points"] == leg["data_points"], ticker
        assert failed["is_limited_history"] == leg["is_limited_history"], ticker
        assert failed["history_warning"] == leg["history_warning"], ticker
        # And the fit's own output is the only thing that differs.
        assert "error" not in leg
        assert failed["error"] == "factor regression failed"


def test_a_failure_still_names_what_actually_failed(monkeypatch):
    """The absence is explained; it is not left to be read as missing data."""
    result = _exposures(_prices(), monkeypatch=monkeypatch)
    leg = result["positions"]["AAA.NS"]
    assert leg["error"] == "factor regression failed"
    assert leg["std_error_basis"] is None
    assert leg["std_error_robust"] is None
    assert leg["alpha_std_error"] is None
    assert leg["market_std_error"] is None


def test_an_unfitted_short_window_is_still_distinguishable_from_a_failure(monkeypatch):
    """A ticker's own null `alpha` has two causes and the payload says which.

    Fewer than ten active rows produces `error: insufficient history for factor
    regression`; a failed fit on a long window produces `error: factor
    regression failed`.  Collapsing them would lose the diagnosis WM-10 is about.
    """
    result = _exposures(_prices(active_days=8))
    leg = result["positions"]["BBB.NS"]
    assert leg["error"] == "insufficient history for factor regression"
    assert leg["data_points"] == pytest.approx(8, abs=1)
    assert leg["is_limited_history"] is True


# ---------------------------------------------------------------------------
# The fixture has to be able to discriminate.
# ---------------------------------------------------------------------------

def test_the_success_path_measures_a_beta_and_a_real_row_count():
    """Without this the tests above would also pass on an always-empty result."""
    result = _exposures(_prices())
    leg = result["positions"]["AAA.NS"]
    assert "error" not in leg
    assert leg["market"] is not None
    assert isinstance(leg["data_points"], int)
    assert leg["data_points"] > 30
    assert leg["is_limited_history"] is False
