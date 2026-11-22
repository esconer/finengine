"""An unoccupied HMM state must not be ranked on a CAGR that was never measured.

`classify` builds one row per HMM state from the trading days the fit assigned
to it. A state that captured NO days has no compounded product, so there is no
annualized return to compute -- and the code used to publish `cagr = 0.0`
anyway:

    regime_service.py, the `n_sub == 0` branch -> `cagr = 0.0`

`_label_states_by_risk` sorts the three states on exactly that column (worst ->
crisis, best -> bull), so the fabricated `0.0` was a plausible-looking number
sitting in the middle of the real distribution. The empty bucket therefore
competed for a real label and could be crowned `calm` or `bull`, published
next to `historical_days_pct: 0.0` -- the user was told an empty bucket was a
calm market, from a figure nothing ever measured.

The fix withholds the number instead of inventing one: the row publishes
`ann_ret: None` with `ann_ret_method: "no_observations"`, and the ordering puts
a state with no measured annualized return at the worst end rather than inside
the measured range. The state is NOT dropped -- it still appears with
`observations: 0` and `historical_days_pct: 0.0`, so a reader can see the model
found a state with no history.

Measured states are untouched: with every `cagr` present the sort is the same
ascending sort of the same numbers, which is what the bit-pinned
`test_regime_ann_vol_and_ann_ret_method.py` and
`test_regime_wiped_out_state_is_minus_one.py` assert.

No DB, no network: seeded RNG plus a patched `GaussianHMM.predict` that
decides which state a day lands in, so the unoccupied state is reachable here
rather than merely unreachable through `classify`.
"""

import inspect
import json

import numpy as np
import pandas as pd
import pytest

from app.services import regime_service as rs
from app.services.regime_service import _label_states_by_risk, classify

SEED = 20260214

#: worst -> best, so `REGIME_RANK[label] > REGIME_RANK[other]` means better.
REGIME_RANK = {"crisis": 0, "calm": 1, "bull": 2}

#: Length of the drawdown block at the head of the series. It has to outlast
#: the 21-day ret21 / vol21 warm-up, so that every day the unoccupied-state
#: fixture assigns to the losing state is a real drawdown day.
DRAWDOWN_DAYS = 60
#: Days handed to the losing state by the patched `predict`. Fewer than
#: `DRAWDOWN_DAYS`, and inside the warm-up, so all of them are drawdown days.
LOSING_STATE_DAYS = 30
#: The state the patched `predict` never emits in the `classify` fixture.
EMPTY_STATE = 2
LOSING_STATE = 1
#: The row that carries no observations in the direct-call tables below.
EMPTY_ROW = 1


# ---------------------------------------------------------------------------
# The ordering, through the real label mapper
# ---------------------------------------------------------------------------
class TestAnUnmeasuredStateIsNotRankedInTheMeasuredRange:
    """The `cagr` cell for a state with no days is null, not 0.0.

    Table shape mirrors what `classify` publishes: state 0 measured and
    negative, state 1 the EMPTY one (null), state 2 measured and positive. On
    the pre-change fabricated `0.0` the empty state sorts between the two real
    figures and takes `calm` -- the published claim that an empty bucket was a
    calm market.
    """

    @staticmethod
    def _table():
        """The three rows `classify` would publish, one of them unoccupied."""
        return pd.DataFrame(
            {"cagr": [-0.42, None, 0.31], "ann_vol": [0.25, None, 0.18]},
            index=[0, 1, 2],
        )

    def test_the_empty_state_is_not_labelled_calm_or_bull(self):
        labels = _label_states_by_risk(self._table())
        assert labels[EMPTY_ROW] not in {"bull", "calm"}, (
            f"a state with no trading days took {labels[EMPTY_ROW]!r} on a "
            f"figure that was never measured: {labels}"
        )

    def test_the_measured_states_keep_their_order_around_the_unmeasured_one(self):
        """Withholding one value must not reorder the two real ones."""
        labels = _label_states_by_risk(self._table())
        # 0.31 > -0.42, so state 2 is the better of the two measured states and
        # must outrank state 0.
        assert REGIME_RANK[labels[2]] > REGIME_RANK[labels[0]]

    def test_every_state_is_still_labelled_exactly_once(self):
        """The unoccupied state is withheld a FIGURE, never dropped."""
        labels = _label_states_by_risk(self._table())
        assert sorted(labels) == [0, 1, 2]
        assert sorted(labels.values()) == ["bull", "calm", "crisis"]

    def test_the_ordering_is_invariant_to_row_order(self):
        table = self._table()
        assert _label_states_by_risk(table.iloc[::-1]) == _label_states_by_risk(table)
        assert _label_states_by_risk(table.iloc[[2, 0, 1]]) == _label_states_by_risk(table)

    def test_the_ann_ret_fallback_column_is_ordered_the_same_way(self):
        """`_label_states_by_risk` falls back to `ann_ret` when `cagr` is absent."""
        table = pd.DataFrame(
            {"ann_ret": [-0.42, None, 0.31], "ann_vol": [0.25, None, 0.18]},
            index=[0, 1, 2],
        )
        labels = _label_states_by_risk(table)
        assert labels[EMPTY_ROW] not in {"bull", "calm"}

    def test_a_fully_measured_table_orders_exactly_as_before(self):
        """The guard must not move a single label when every cagr is measured."""
        table = pd.DataFrame(
            {"cagr": [-0.42, 0.02, 0.31], "ann_vol": [0.25, 0.20, 0.18]},
            index=[0, 1, 2],
        )
        assert _label_states_by_risk(table) == {0: "crisis", 1: "calm", 2: "bull"}

    def test_a_measured_zero_is_still_ranked_on_its_merits(self):
        """0.0 is a real reading when a state actually held days.

        The defect is the FABRICATED zero, not the number zero: a state whose
        compounded product genuinely annualizes to 0.0% must keep ranking
        between the negative and the positive state.
        """
        table = pd.DataFrame(
            {"cagr": [-0.42, 0.0, 0.31], "ann_vol": [0.25, 0.20, 0.18]},
            index=[0, 1, 2],
        )
        assert _label_states_by_risk(table) == {0: "crisis", 1: "calm", 2: "bull"}


# ---------------------------------------------------------------------------
# The publication, through `classify` with an actually-unoccupied state
# ---------------------------------------------------------------------------
def _frame_with_a_leading_drawdown(seed=SEED, periods=900):
    """Drawdown first, quiet positive drift for the rest of the window."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0006, 0.011, periods)
    rets[:DRAWDOWN_DAYS] = -0.05
    dates = pd.bdate_range("2020-01-01", periods=periods)
    close = 100.0 * np.cumprod(1.0 + rets)
    return pd.DataFrame({"adj_close": pd.Series(close, index=dates)})


@pytest.fixture(scope="module")
def payload_with_an_unoccupied_state():
    """`classify` on a fit in which one of the three states captures no days.

    `GaussianHMM.predict` is patched rather than engineered through the input
    data: the fit itself is untouched (means, covariances, transition prior and
    posteriors are the real ones) and only the DECODED path is dictated, which
    is what decides a state's occupancy.
    """
    from hmmlearn.hmm import GaussianHMM

    original = GaussianHMM.predict

    def only_two_states(self, X, *args, **kwargs):
        states = np.zeros(len(X), dtype=int)
        states[:LOSING_STATE_DAYS] = LOSING_STATE
        assert EMPTY_STATE not in set(states.tolist()), "fixture must leave a state empty"
        return states

    GaussianHMM.predict = only_two_states
    try:
        payload = classify(_frame_with_a_leading_drawdown())
    finally:
        GaussianHMM.predict = original
    assert payload is not None
    return payload


class TestAnUnoccupiedStateIsPublishedWithoutAFabricatedFigure:
    def test_exactly_one_state_captured_no_days(self, payload_with_an_unoccupied_state):
        rows = payload_with_an_unoccupied_state["states"]
        unoccupied = [r for r in rows if r["observations"] == 0]
        assert len(unoccupied) == 1, f"fixture must leave one state empty: {rows}"
        assert unoccupied[0]["historical_days_pct"] == 0.0

    def test_an_unoccupied_state_publishes_no_annualized_return(self, payload_with_an_unoccupied_state):
        """`ann_ret` is null, and the method token names the reason."""
        row = next(
            r for r in payload_with_an_unoccupied_state["states"] if r["observations"] == 0
        )
        assert row["ann_ret"] is None, (
            f"an unoccupied state published ann_ret {row['ann_ret']!r}: no "
            f"annualized return was measured for it"
        )
        assert row["ann_ret_method"] == "no_observations"
        assert row["annualization_factor"] is None
        assert row["ann_vol"] is None

    def test_an_unoccupied_state_is_never_labelled_calm_or_bull(self, payload_with_an_unoccupied_state):
        """The end-to-end claim: no empty bucket is published as a market view."""
        row = next(
            r for r in payload_with_an_unoccupied_state["states"] if r["observations"] == 0
        )
        assert row["regime"] not in {"bull", "calm"}, (
            f"a state with 0 of {payload_with_an_unoccupied_state['observations']} "
            f"trading days was published as {row['regime']!r}"
        )

    def test_the_state_is_still_visible_rather_than_dropped(self, payload_with_an_unoccupied_state):
        """Three states in, three states out, including the empty one."""
        rows = payload_with_an_unoccupied_state["states"]
        assert len(rows) == rs.REGIME_STATES
        assert {r["regime"] for r in rows} == set(REGIME_RANK)

    def test_the_measured_states_are_unaffected_by_the_empty_one(self, payload_with_an_unoccupied_state):
        """Both measured states keep a figure and rank in their own order."""
        rows = payload_with_an_unoccupied_state["states"]
        measured = {r["regime"]: r for r in rows if r["observations"] > 0}
        assert len(measured) == 2
        for row in measured.values():
            assert row["ann_ret"] is not None
            assert row["ann_ret_method"] == "geometric_cagr_from_compounded_state_returns"
        ranked = sorted(measured.values(), key=lambda r: r["ann_ret"])
        assert REGIME_RANK[ranked[1]["regime"]] > REGIME_RANK[ranked[0]["regime"]]

    def test_the_withheld_state_is_publishable_as_json(self, payload_with_an_unoccupied_state):
        """`None` travels; a bare NaN would serialize as invalid JSON."""
        states = payload_with_an_unoccupied_state["states"]
        dumped = json.dumps(states, allow_nan=False)  # raises on NaN/Infinity
        assert json.loads(dumped)[0]["observations"] is not None


# ---------------------------------------------------------------------------
# The line, and the disclosure beside the number
# ---------------------------------------------------------------------------
def _unoccupied_branch():
    """The `n_sub == 0` else-branch of `classify`, verbatim.

    `inspect.getsource` on the estimator is this repo's idiom for pinning a
    branch (see test_the_source_branch_is_the_geometric_one in
    test_regime_wiped_out_state_is_minus_one.py): no fixture can be relied on
    to reach a branch through a stochastic fit, so the line itself is the
    assertion. The slice is bounded at the next 8-space comment so it cannot
    silently absorb the `ann_vol` block below it, and the assertions below
    anchor it positively on `"no_observations"` so a refactor that moves the
    branch fails loudly rather than passing vacuously.
    """
    branch = inspect.getsource(classify).split("\n        else:")[-1]
    return branch.split("\n        # ")[0]


class TestTheFabricatedZeroIsUnreachableInTheSource:
    def test_the_no_observations_branch_publishes_null_not_zero(self):
        branch = _unoccupied_branch()
        assert '"no_observations"' in branch, "the wrong else-branch was sliced"
        assert "cagr = None" in branch
        assert "cagr = 0.0" not in branch, "the unoccupied state is fabricating 0.0 again"
        # and no substitute figure was invented for it either
        for invented in ("r_sub.mean()", "TRADING_DAYS_PER_YEAR", "cum_prod"):
            assert invented not in branch

    def test_the_method_token_is_still_published(self):
        branch = _unoccupied_branch()
        assert 'ann_ret_method = "no_observations"' in branch
        assert branch.count("ann_ret_method = ") == 1

    def test_the_ordering_refuses_to_rank_a_withheld_value(self):
        """The label mapper must place an unmeasured state, not sort it."""
        source = inspect.getsource(_label_states_by_risk)
        assert 'sort_values("cagr", na_position="first")' in source, (
            "a null annualized return would sort to the BEST end by default, "
            "which is exactly the fabricated-0.0 defect it replaced"
        )
        # both the cagr and the ann_ret fallback path, since either can carry
        # the withheld value
        assert 'sort_values("ann_ret", na_position="first")' in source

    def test_the_units_block_no_longer_advertises_a_zero(self):
        qualifier = rs._regime_metadata({}, use_returns=False, lookback_days=1100)["units"][
            "states[].ann_ret_method"
        ]
        no_obs = qualifier.split("'no_observations'")[1]
        assert "NULL" in no_obs
        assert "ann_ret is 0.0" not in no_obs, (
            "the disclosure still tells a reader the unoccupied state's ann_ret "
            "is 0.0, which is the fabrication itself"
        )
        # the label consequence is named, so the ordering is not implicit
        lowered = no_obs.lower()
        assert "crisis" in lowered and "not ranked" in lowered
