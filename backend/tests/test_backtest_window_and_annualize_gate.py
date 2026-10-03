"""The walk-forward backtest's window and its annualization gate.

Two silent-substitution defects in `run_walk_forward_backtest`, same function,
same class: a quantity the caller asked for is replaced by a smaller one, or a
per-year figure is extrapolated from a window too short to support one, and
nothing in the payload says so.

DEFECT 1 (SVC-6) -- the shortened window was invisible. When the frame is
shorter than `lookback_days + rebalance_freq_days`, the function silently
rewrote the request to `max(20, 40% of the frame)` / `max(5, 10% of the
frame)`. A caller asking for a 756-day lookback got a 48-day backtest under
the same key, with the same equity curve, and no indication that the request
had been reduced. The route compounds it: it published
`history_days_analyzed = len(returns_df)`, which is the INPUT frame's length,
not the number of days actually simulated -- so the disclosure named a
quantity the run never measured.

The fix publishes the effective window beside the requested one, the
simulated-day count, and a boolean saying whether the request was honoured.

DEFECT 2 (SVC-7) -- CAGR annualized without the gate the codebase already
defines. `MIN_ANNUALIZE_DAYS = 30` (`app/utils/holdings.py`) exists precisely
because "annualizing a week of history fabricates triple-digit percentages",
and the route applies it to the INPUT frame (`analytics.py:10587`). It was
never applied to `n_days`, the post-loop count of simulated days. A frame of
30 rows shortens to a 20-day lookback and a 5-day rebalance, which simulates
10 days, and the published CAGR was `cum ** 25.2`.

The formula is standard and correct; this is a missing gate, not bad math, so
a sufficient window must still publish the same number it always did. Below the
gate the payload publishes `None`, matching the shape the same function
already uses for an unusable Sharpe denominator (a zero volatility) and an
unusable Calmar (a zero drawdown). `strat_calmar = strat_cagr / abs(strat_mdd)`
divides by the CAGR, so nulling the CAGR cascades into that line: it takes the
same guard in the same change, or the short run raises `TypeError` instead of
refusing to publish.

No DB, no network: seeded RNG only.
"""

import numpy as np
import pandas as pd
import pytest

from app.services.backtest_service import TRADING_DAYS, run_walk_forward_backtest
from app.utils.holdings import MIN_ANNUALIZE_DAYS


def _frame(rows: int, seed: int = 4242):
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        rng.normal(0.0006, 0.011, (rows, 2)),
        index=pd.bdate_range("2024-01-01", periods=rows),
        columns=["A", "B"],
    )


def _run(rows: int, lookback_days: int, rebalance_freq_days: int, **kw):
    return run_walk_forward_backtest(
        _frame(rows),
        strategy="equal_weight",
        lookback_days=lookback_days,
        rebalance_freq_days=rebalance_freq_days,
        transaction_cost_bps=10.0,
        **kw,
    )


#: Every published key the annualization gate withholds below MIN_ANNUALIZE_DAYS.
#: Seven, not three: MIN_ANNUALIZE_DAYS' own docstring names "CAGR, Sharpe,
#: Sortino, Calmar, annualized vol", and a 10-day run publishing
#: `sharpe_ratio = 3.0169` is the same fabrication B2 removed from `cagr`.
GATED_KEYS = (
    "cagr",
    "benchmark_cagr",
    "calmar_ratio",
    "annualized_volatility",
    "benchmark_volatility",
    "sharpe_ratio",
    "benchmark_sharpe",
)

#: Published values captured from the code BEFORE the gate was widened to the
#: volatility and Sharpe keys, for the two fixtures whose windows clear it. They
#: are pinned rather than recomputed because neither the volatility nor the
#: Sharpe is recoverable from the payload: `equity_curve` carries the compounded
#: curve at 4dp, and differencing it to recover daily returns destroys the
#: precision a standard deviation needs. The CAGR pair IS recomputed, off the
#: curve, below -- that proof is available for those two and not for these.
PRE_WIDENING = {
    (120, 40, 20): {
        "simulated_days": 80,
        "cagr": 0.1203,
        "benchmark_cagr": 0.1193,
        "calmar_ratio": 1.8385,
        "annualized_volatility": 0.1265,
        "benchmark_volatility": 0.1264,
        "sharpe_ratio": 0.8023,
        "benchmark_sharpe": 0.7959,
        "max_drawdown": -0.0654,
        "annualized_excess": 0.1215,
        "benchmark_annualized_excess": 0.1206,
    },
    (300, 100, 21): {
        "simulated_days": 200,
        "cagr": 0.3314,
        "benchmark_cagr": 0.316,
        "calmar_ratio": 6.9024,
        "annualized_volatility": 0.1092,
        "benchmark_volatility": 0.11,
        "sharpe_ratio": 2.4944,
        "benchmark_sharpe": 2.3707,
        "max_drawdown": -0.048,
        "annualized_excess": 0.2924,
        "benchmark_annualized_excess": 0.2808,
    },
}

RISK_FREE_RATE = 0.02


# ---------------------------------------------------------------------------
# DEFECT 1 -- the shortened window, published
# ---------------------------------------------------------------------------
class TestTheEffectiveWindowIsPublishedBesideTheRequest:
    def test_a_shortened_lookback_is_reported_with_the_ask_it_displaced(self):
        res = _run(120, lookback_days=756, rebalance_freq_days=21)
        # RED on the shipped code: KeyError -- the request was rewritten and
        # the payload said nothing about it.
        assert res["lookback_days"] == 48  # max(20, int(120 * 0.4))
        assert res["lookback_days_requested"] == 756
        assert res["requested_windows_honoured"] is False

    def test_the_shortened_rebalance_frequency_is_published_too(self):
        res = _run(120, lookback_days=756, rebalance_freq_days=21)
        assert res["rebalance_freq_days"] == 12  # max(5, int(120 * 0.1))
        assert res["rebalance_freq_days_requested"] == 21
        assert res["requested_windows_honoured"] is False

    def test_an_honoured_request_publishes_the_same_number_on_both_keys(self):
        """No false alarm on the honest path: the flag means what it says."""
        res = _run(120, lookback_days=40, rebalance_freq_days=20)
        assert res["lookback_days"] == res["lookback_days_requested"] == 40
        assert res["rebalance_freq_days"] == res["rebalance_freq_days_requested"] == 20
        assert res["requested_windows_honoured"] is True

    def test_simulated_days_is_the_days_the_curve_was_built_from(self):
        """Structural: the count is not a re-derivation, it is the curve's own."""
        for rows, lookback in ((120, 756), (120, 40), (300, 100)):
            res = _run(rows, lookback_days=lookback, rebalance_freq_days=21)
            assert res["simulated_days"] == len(res["equity_curve"])
            assert res["simulated_days"] == len(res["drawdowns"])
            assert res["simulated_days"] == rows - res["lookback_days"]

    def test_the_input_length_is_published_separately_from_the_simulated_days(self):
        """The route published `len(returns_df)` as `history_days_analyzed`.

        That is the input frame, not the window the curve was measured over, so
        for a shortened run the two differ and the reader cannot tell which one
        the payload is talking about. Both are now named for what they are.
        """
        res = _run(120, lookback_days=756, rebalance_freq_days=21)
        assert res["input_days"] == 120
        assert res["input_days"] != res["simulated_days"]
        assert res["simulated_days"] == 120 - res["lookback_days"]
        # A run that consumed its whole input is the case where conflating them
        # is invisible -- which is why both keys exist rather than one.
        full = _run(120, lookback_days=20, rebalance_freq_days=1)
        assert full["simulated_days"] == full["input_days"] - full["lookback_days"]


# ---------------------------------------------------------------------------
# DEFECT 2 -- the annualization gate
# ---------------------------------------------------------------------------
class TestAShortSimulatedWindowPublishesNoCagr:
    def test_a_ten_simulated_day_run_publishes_none_not_a_number(self):
        # 30 rows shorten to a 20-day lookback and a 5-day rebalance, which
        # simulates 10 days: years = 10/252, so the shipped code raised the
        # final compounded wealth to the power 25.2 and called it a CAGR.
        res = _run(30, lookback_days=756, rebalance_freq_days=21)
        assert res["simulated_days"] == 10
        # RED on the shipped code: a float, from cum ** 25.2 - 1.
        assert res["cagr"] is None
        assert res["benchmark_cagr"] is None

    def test_the_gate_is_off_the_simulated_window_not_the_input_frame(self):
        """An HONEST short request is the sharpest case.

        Nothing is shortened here, so the input-frame check the route already
        performs cannot help: 40 input rows pass the route's own
        `len(returns_df) >= MIN_ANNUALIZE_DAYS`, and only the 20 simulated days
        fall short of the gate.
        """
        res = _run(40, lookback_days=20, rebalance_freq_days=20)
        assert res["requested_windows_honoured"] is True
        assert res["input_days"] == 40 >= MIN_ANNUALIZE_DAYS
        assert res["simulated_days"] == 20 < MIN_ANNUALIZE_DAYS
        assert res["cagr"] is None
        assert res["benchmark_cagr"] is None
        assert res["annualized"] is False

    def test_the_gate_publishes_its_own_threshold_and_its_own_day_count(self):
        res = _run(40, lookback_days=20, rebalance_freq_days=20)
        assert res["minimum_observations_required"] == MIN_ANNUALIZE_DAYS
        assert res["minimum_observations_required"] == 30
        assert res["annualized"] is False

    def test_the_calmar_cascade_refuses_instead_of_dividing_a_none(self):
        """`strat_calmar = strat_cagr / abs(strat_mdd)` consumed the CAGR.

        Nulling the CAGR without guarding this line raises TypeError, so the
        short run would 500 rather than publish a refusal. The drawdown is
        asserted non-zero so a None here cannot be credited to the mdd guard.
        """
        res = _run(40, lookback_days=20, rebalance_freq_days=20)
        assert res["max_drawdown"] < 0.0, "premise: the mdd guard cannot explain the None"
        assert res["cagr"] is None
        assert res["calmar_ratio"] is None

    def test_the_non_annualized_keys_are_never_a_number(self):
        res = _run(30, lookback_days=756, rebalance_freq_days=21)
        for key in GATED_KEYS:
            assert res[key] is None, f"{key} published a figure for 10 simulated days"

    @pytest.mark.parametrize(
        "rows,lookback,rebalance,expected_days",
        [(30, 756, 21, 10), (40, 20, 20, 20)],
    )
    def test_every_annualized_key_is_null_on_both_short_runs(
        self, rows, lookback, rebalance, expected_days
    ):
        """The gate is one predicate, applied to the whole annualization.

        Volatility and Sharpe are annualized figures in exactly the sense
        `MIN_ANNUALIZE_DAYS` names them: a standard deviation of 10 daily
        returns scaled by sqrt(252), and a mean of the same 10 returns scaled by
        252. Leaving them published while `cagr` is withheld would mean the
        payload still tells a reader how a fortnight of noise behaved per year.
        """
        res = _run(rows, lookback_days=lookback, rebalance_freq_days=rebalance)
        assert res["simulated_days"] == expected_days < MIN_ANNUALIZE_DAYS
        assert res["annualized"] is False
        for key in GATED_KEYS:
            # RED on the code as it stood with only three keys gated: the four
            # volatility/Sharpe keys still carried a number.
            assert res[key] is None, f"{key} survived the gate"

    def test_the_gate_does_not_swallow_a_figure_that_is_not_annualized(self):
        """The gate is scoped to the annualization and to nothing else.

        A maximum drawdown, a turnover, a curve and a day count are all
        measured directly on the simulated window; withholding them would be
        refusing a measurement that exists.
        """
        res = _run(30, lookback_days=756, rebalance_freq_days=21)
        assert res["max_drawdown"] < 0.0
        assert res["benchmark_max_drawdown"] < 0.0
        assert res["total_turnover"] > 0.0
        assert res["total_rebalances"] >= 1
        assert len(res["equity_curve"]) == res["simulated_days"]
        assert len(res["drawdowns"]) == res["simulated_days"]
        assert res["input_days"] == 30
        assert res["requested_windows_honoured"] is False
        assert res["benchmark_method"] == "equal_weight_buy_and_hold"


# ---------------------------------------------------------------------------
# The gate must not move a number that was always allowed
# ---------------------------------------------------------------------------
class TestASufficientWindowPublishesExactlyTheSameCagr:
    @pytest.mark.parametrize("rows,lookback,rebalance", [(120, 40, 20), (300, 100, 21)])
    def test_the_formula_is_unchanged_where_it_applies(self, rows, lookback, rebalance):
        res = _run(rows, lookback_days=lookback, rebalance_freq_days=rebalance)
        assert res["simulated_days"] >= MIN_ANNUALIZE_DAYS
        assert res["annualized"] is True
        assert isinstance(res["cagr"], float)
        # Recompute the standard CAGR off the published curve: the fix adds a
        # gate, it does not touch the estimator.
        final_wealth = res["equity_curve"][-1]["strategy"]
        years = res["simulated_days"] / TRADING_DAYS
        # equity_curve rounds to 4dp, so compare at that resolution
        assert res["cagr"] == pytest.approx(final_wealth ** (1.0 / years) - 1.0, abs=1e-3)
        assert res["benchmark_cagr"] == pytest.approx(
            res["equity_curve"][-1]["benchmark"] ** (1.0 / years) - 1.0, abs=1e-3
        )

    def test_the_calmar_is_unchanged_where_the_cagr_applies(self):
        res = _run(120, lookback_days=40, rebalance_freq_days=20)
        assert res["cagr"] is not None
        assert res["max_drawdown"] < 0.0
        assert res["calmar_ratio"] == pytest.approx(
            res["cagr"] / abs(res["max_drawdown"]), abs=1e-3
        )


# ---------------------------------------------------------------------------
# ...and the four newly gated keys must not move either
# ---------------------------------------------------------------------------
class TestWideningTheGateMovedNoFigure:
    """Byte identity for the gate-passing path, pinned against the pre-widening run.

    Widening a gate is only safe if it is inert where the gate does not apply.
    These are the exact published values captured from the code before
    `annualized_volatility`, `benchmark_volatility`, `sharpe_ratio` and
    `benchmark_sharpe` joined `cagr`, `benchmark_cagr` and `calmar_ratio`
    under it.
    """

    @pytest.mark.parametrize("rows,lookback,rebalance", list(PRE_WIDENING))
    def test_every_published_figure_is_unchanged(self, rows, lookback, rebalance):
        expected = PRE_WIDENING[(rows, lookback, rebalance)]
        res = _run(rows, lookback_days=lookback, rebalance_freq_days=rebalance)
        assert res["simulated_days"] == expected["simulated_days"]
        for key in GATED_KEYS:
            # RED until the widened gate is inert above the threshold: a
            # published float must still be that float.
            assert res[key] == expected[key], f"{key} moved: {res[key]} != {expected[key]}"

    @pytest.mark.parametrize("rows,lookback,rebalance", list(PRE_WIDENING))
    def test_the_drawdown_is_unchanged(self, rows, lookback, rebalance):
        """The drawdown is not gated, so it is the control on the whole set."""
        expected = PRE_WIDENING[(rows, lookback, rebalance)]
        res = _run(rows, lookback_days=lookback, rebalance_freq_days=rebalance)
        assert res["max_drawdown"] == expected["max_drawdown"]

    @pytest.mark.parametrize("rows,lookback,rebalance", list(PRE_WIDENING))
    def test_the_sharpe_identity_still_holds_across_the_published_keys(
        self, rows, lookback, rebalance
    ):
        """Lo (2002): sharpe = (mu_d * 252 - rf) / (sd_d * sqrt(252)).

        That rearranges to `mu_d * 252 = sharpe * vol + rf`, which is the only
        way to check the Sharpe against something computed independently once
        the daily returns themselves are no longer published: the identity
        spans three published keys and one known input.
        """
        expected = PRE_WIDENING[(rows, lookback, rebalance)]
        res = _run(
            rows,
            lookback_days=lookback,
            rebalance_freq_days=rebalance,
            risk_free_rate=RISK_FREE_RATE,
        )
        excess = res["sharpe_ratio"] * res["annualized_volatility"] + RISK_FREE_RATE
        assert round(excess, 4) == expected["annualized_excess"]
        bench_excess = (
            res["benchmark_sharpe"] * res["benchmark_volatility"] + RISK_FREE_RATE
        )
        assert round(bench_excess, 4) == expected["benchmark_annualized_excess"]
        # and the identity is the estimator's, not a coincidence of the fixture
        assert excess > RISK_FREE_RATE

    def test_a_zero_volatility_still_withholds_the_sharpe_without_the_gate(self):
        """The pre-existing guard, unchanged: a flat simulated curve has no Sharpe.

        A window whose every daily return is identical has a zero denominator,
        so the Sharpe is None while the volatility publishes 0.0 -- an ungated
        fixture, so the old guard is what is under test rather than the new one.
        """
        rows = 120
        flat = pd.DataFrame(
            0.0, index=pd.bdate_range("2024-01-01", periods=rows), columns=["A", "B"]
        )
        res = run_walk_forward_backtest(
            flat,
            strategy="equal_weight",
            lookback_days=40,
            rebalance_freq_days=20,
            transaction_cost_bps=0.0,
        )
        assert res["simulated_days"] >= MIN_ANNUALIZE_DAYS
        assert res["annualized"] is True
        assert res["annualized_volatility"] == 0.0
        assert res["sharpe_ratio"] is None
        assert res["benchmark_sharpe"] is None
