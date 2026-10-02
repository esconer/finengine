"""A ratio whose own denominator measured nothing is `None`, never `0.0`.

The engine's own audit rule is `num_018_no_hard_zero_sub_scores`
(`app/debugging/context_audit.py`). Its docstring states the principle
directly: a sub-score of exactly zero is a defect when nothing measured it,
because "an unmeasured component" published as 0 is the one thing a reader
cannot distinguish from a real zero - and it adds that silencing such a finding
with an epsilon floor is "strictly worse than the ambiguity this rule was
written to catch".

`_calculate_basic_metrics` already obeyed that on one branch. Below
`SHORT_SAMPLE_MIN_OBSERVATIONS` it withholds `annual_return`, `sharpe_ratio`
and `sortino_ratio` instead of annualizing a handful of observations, and the
comment on that branch calls a hard zero on an unmeasured ratio "the one number
a reader must never be handed". That branch was the FIX for this defect.

The two ratios have a second, unrelated way to have no value, and the ternary
on the annualizing branch still published `0.0` there:

    sharpe_ratio = ... if annual_volatility > 0 else 0.0
    sortino_ratio = ... if downside_deviation > 0 else 0.0

`annual_volatility` measures zero on a window whose every return is the same
number - one ticker that never moved, or a stale-price frame that clears the
ten-day `assert_not_stale` gate the route applies. `downside_deviation`
measures zero on a window that never undershot the risk-free target. Neither is
a low Sharpe or a low Sortino; both are ratios with no value at all, and `0.0`
for either tells a reader "no measurable risk" where the truth is "nothing was
computed" - on precisely the frame shape that produces it.

The fix publishes `None` with a stated reason, matching the sibling branch's
idiom. It substitutes no floor, no epsilon and no small number: each of those
is a value the engine did not measure, and `num_018`'s own docstring names a
floor as the worse failure.

`annual_return`, `annual_volatility` and `hit_ratio` are NOT withheld on these
windows - over a flat series a zero mean, a zero dispersion and a zero hit rate
are genuine measurements over the observations that exist. The tests pin that,
so the refusal cannot drift into nulling a real measurement or into stealing the
interval a measured window earned.
"""

import asyncio

import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import AnalyticsEngine

#: Declared on the class next to the block that publishes them; both are the
#: block's contract rather than free-floating module constants.
REALIZED_RISK_ESTIMATE_FIELDS = AnalyticsEngine.REALIZED_RISK_ESTIMATE_FIELDS
SHORT_SAMPLE_MIN_OBSERVATIONS = AnalyticsEngine.SHORT_SAMPLE_MIN_OBSERVATIONS

#: Fixed, so a failure is reproducible rather than a property of the draw.
SEED = 20260903

#: The two fields whose value is a ratio of a measurement over a measurement.
RATIO_FIELDS = ("sharpe_ratio", "sortino_ratio")

#: Long enough that `SHORT_SAMPLE_MIN_OBSERVATIONS` never fires: these tests
#: are about the OTHER withholding path, not the one that branch already had.
DAYS = 60


def _flat_frame(days: int = DAYS) -> pd.DataFrame:
    """A window whose every return is exactly 0.0 - the price never moves."""
    idx = pd.bdate_range("2024-01-02", periods=days)
    return pd.DataFrame({"AAA.NS": np.full(days, 100.0)}, index=idx)


def _never_undershoots_frame(days: int = DAYS, rate: float = 0.001) -> pd.DataFrame:
    """A window that never falls to the Sortino target.

    Every return is the same positive number and well above `risk_free_rate /
    252` (7.9e-5 at the default 2%), so the downside deviation is exactly zero
    while the window is long enough to annualize.
    """
    idx = pd.bdate_range("2024-01-02", periods=days)
    return pd.DataFrame({"AAA.NS": 100.0 * np.exp(np.arange(days) * rate)}, index=idx)


def _measured_frame(days: int = 120, seed: int = SEED) -> pd.DataFrame:
    """A window with a real dispersion, so both ratios ARE computable."""
    idx = pd.bdate_range("2024-01-02", periods=days)
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.010, days)))
    return pd.DataFrame({"AAA.NS": close}, index=idx)


def _metrics(prices: pd.DataFrame) -> dict:
    return asyncio.run(
        AnalyticsEngine().calculate_portfolio_metrics(prices, {"AAA.NS": 1.0})
    )


def _published_ratios(node, path: str = "metrics"):
    """Every ratio value on the payload, the disclosure entries included.

    `estimates.<field>` is the same field again as a precision entry, so its
    `point` is compared with the payload's own value: a disclosure that agrees
    with a hard zero is still a hard zero.
    """
    found = {}
    if isinstance(node, dict):
        for key, value in node.items():
            if key in RATIO_FIELDS:
                found[f"{path}.{key}"] = (
                    value.get("point") if isinstance(value, dict) else value
                )
            found.update(_published_ratios(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.update(_published_ratios(value, f"{path}[{index}]"))
    return found


@pytest.mark.parametrize(
    "frame_name", ["flat", "never_undershoots"], ids=["flat", "never-undershoots"]
)
def test_the_window_is_long_enough_to_annualize(frame_name):
    """Guard: these tests must exercise the annualizing branch, not the short one."""
    prices = _flat_frame() if frame_name == "flat" else _never_undershoots_frame()
    metrics = _metrics(prices)
    assert metrics["observations"] >= SHORT_SAMPLE_MIN_OBSERVATIONS
    assert "annual_return" in metrics


def test_a_flat_window_publishes_no_sharpe_rather_than_a_hard_zero():
    metrics = _metrics(_flat_frame())
    # The real measurement beside the ratio: a genuinely zero dispersion.
    assert metrics["annual_volatility"] == 0.0
    assert metrics["sharpe_ratio"] is None

    entry = metrics["estimate_uncertainty"]["estimates"]["sharpe_ratio"]
    assert entry["point"] is None
    assert entry["status"] == "not_computed"
    assert entry["conf_int"] is None
    # The reason names the denominator AND quotes what it measured on THIS
    # window, so it cannot describe a different one.
    assert "annualized volatility" in entry["reason"]
    assert "which measured 0.0" in entry["reason"]


def test_a_window_that_never_undershoots_the_target_publishes_no_sortino():
    metrics = _metrics(_never_undershoots_frame())
    assert metrics["sortino_ratio"] is None

    entry = metrics["estimate_uncertainty"]["estimates"]["sortino_ratio"]
    assert entry["point"] is None
    assert entry["status"] == "not_computed"
    assert entry["conf_int"] is None
    assert "downside deviation" in entry["reason"]


@pytest.mark.parametrize(
    "frame_name", ["flat", "never_undershoots"], ids=["flat", "never-undershoots"]
)
def test_no_ratio_anywhere_on_a_degenerate_payload_is_a_hard_zero(frame_name):
    """No substituted zero survives anywhere on the payload.

    Which ratio is absent depends on which denominator measured nothing, and
    that is deliberate: a flat window has no dispersion, so Sharpe has no value,
    but every one of its returns sits BELOW the risk-free target, so its
    downside deviation is real and its Sortino is computable. What must not
    happen - on the book, on a leg, or in the disclosure entry that restates
    the payload - is a 0.0 standing in for a ratio nobody computed.
    """
    prices = _flat_frame() if frame_name == "flat" else _never_undershoots_frame()
    metrics = _metrics(prices)
    published = _published_ratios(metrics)
    assert published, "the payload published no ratio field at all"
    for path, value in published.items():
        assert value != 0.0, f"{path} published a hard 0.0 for an unmeasured ratio"
    # The payload's value and the precision entry's restatement of it are one
    # number, so a disclosure cannot quietly report a ratio the payload lacks.
    estimates = metrics["estimate_uncertainty"]["estimates"]
    for field in RATIO_FIELDS:
        assert metrics[field] == estimates[field]["point"], field


def test_the_absent_ratio_is_absent_from_the_book_and_from_its_own_leg():
    """The refusal is the same on both blocks, not just the portfolio one."""
    metrics = _metrics(_flat_frame())
    assert metrics["sharpe_ratio"] is None
    assert metrics["positions"]["AAA.NS"]["sharpe_ratio"] is None
    for block in (metrics, metrics["positions"]["AAA.NS"]):
        entry = block["estimate_uncertainty"]["estimates"]["sharpe_ratio"]
        assert entry["point"] is None
        assert entry["status"] == "not_computed"
        assert entry["conf_int"] is None


def test_the_real_measurements_beside_the_absent_ratio_still_ship():
    """The refusal covers the two ratios and nothing else on this window."""
    metrics = _metrics(_flat_frame())
    # All three are measurements over the observations that exist: 0.0 of 59
    # positive days, a zero mean, a zero dispersion.  Withholding them would be
    # the opposite defect - hiding a number that was measured.
    assert metrics["annual_return"] == 0.0
    assert metrics["annual_volatility"] == 0.0
    assert metrics["hit_ratio"] == 0.0

    estimates = metrics["estimate_uncertainty"]["estimates"]
    for field in ("annual_return", "annual_volatility", "hit_ratio"):
        assert estimates[field]["point"] == 0.0, field
    # And the refusal does not cost them their intervals either.
    assert estimates["annual_return"]["status"] == "computed"
    assert estimates["annual_volatility"]["status"] == "computed"


def test_a_withheld_ratio_does_not_suppress_its_measured_sibling():
    """One absence must not cost the other ratio the band it earned.

    A flat window has no dispersion, so Sharpe has no value - but its downside
    deviation against the risk-free target is real and Sortino is computable.
    The reason map is filtered to the fields that are actually absent, so the
    Sortino interval still ships.
    """
    metrics = _metrics(_flat_frame())
    assert metrics["sharpe_ratio"] is None
    assert isinstance(metrics["sortino_ratio"], float)

    entry = metrics["estimate_uncertainty"]["estimates"]["sortino_ratio"]
    assert entry["status"] == "computed"
    assert entry["conf_int"] is not None


def test_a_measured_window_keeps_both_ratios_and_both_intervals():
    """The other side of the same guard: no measured window is disturbed."""
    metrics = _metrics(_measured_frame())
    for field in RATIO_FIELDS:
        assert isinstance(metrics[field], float), field
        entry = metrics["estimate_uncertainty"]["estimates"][field]
        assert entry["status"] == "computed", field
        assert entry["reason"] is None, field
        assert entry["conf_int"][0] <= entry["point"] <= entry["conf_int"][1], field


def test_a_position_leg_on_a_flat_window_publishes_no_sharpe():
    """The per-leg block withholds on the leg's OWN window, same as the book."""
    metrics = _metrics(_flat_frame())
    position = metrics["positions"]["AAA.NS"]
    assert position["sharpe_ratio"] is None

    entry = position["estimate_uncertainty"]["estimates"]["sharpe_ratio"]
    assert entry["point"] is None
    assert entry["status"] == "not_computed"
    assert "annualized volatility" in entry["reason"]


def test_the_short_window_branch_is_untouched_by_the_zero_dispersion_reason():
    """The two reasons must not be interchangeable.

    Below the sample floor the reason says the window is SHORT; on a
    zero-dispersion window it says the DENOMINATOR is nothing. Sending a reader
    on a flat window off to widen history that is already wide enough is the
    wrong instruction, and vice versa.
    """
    short = _metrics(_measured_frame(days=SHORT_SAMPLE_MIN_OBSERVATIONS))
    entry = short["estimate_uncertainty"]["estimates"]["sharpe_ratio"]
    assert entry["point"] is None
    assert "fewer than" in entry["reason"]
    assert "annualized volatility" not in entry["reason"]

    flat = _metrics(_flat_frame())
    entry = flat["estimate_uncertainty"]["estimates"]["sharpe_ratio"]
    assert "fewer than" not in entry["reason"]
    assert "annualized volatility" in entry["reason"]


def test_every_declared_field_still_appears_on_a_refused_block():
    """A refused block is the same SHAPE as a measured one.

    `REALIZED_RISK_ESTIMATE_FIELDS` is the block's contract: a null interval is
    a stated absence on a present key, never a silently missing one.
    """
    metrics = _metrics(_flat_frame())
    for scope in (metrics, metrics["positions"]["AAA.NS"]):
        estimates = scope["estimate_uncertainty"]["estimates"]
        for field in REALIZED_RISK_ESTIMATE_FIELDS:
            assert field in estimates, field