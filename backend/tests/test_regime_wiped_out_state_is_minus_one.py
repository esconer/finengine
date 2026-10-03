"""A wiped-out state's annualized return is -100%/yr, not the average of its days.

`classify` computed each state's `ann_ret` as the geometric CAGR of its
compounded returns, and fell back to an ARITHMETIC mean times 252 whenever the
compounded product was not positive. `cum_prod == 0` was one of those two cases
and the fallback is arithmetically wrong for it:

    0 ** positive == 0    so   (0 ** (252/n)) - 1 == -1.0

The geometric extrapolation IS defined, it is the SAME formula as the branch
above it, and the state lost everything. The arithmetic mean instead throws the
wipeout away: 29 days of +5% and one -100% averages +1.5%/day, which annualizes
to **+378%**. `_label_states_by_risk` sorts on this figure, so such a state was
crowned `bull`.

Nothing here needs a threshold or a tolerance - `0 ** (positive)` is arithmetic,
not a judgement call - so the branch is decidable and fixed rather than
documented and deferred.

**The reachability caveat is measured, not assumed.** Through `classify` the
branch cannot run today: the day that zeroes the product also zeroes the
reconstructed `close`, so `ret21 = log(0 / close.shift(21))` is `-inf`, which
survives `dropna()` (which drops NaN, not -inf) and reaches the `StandardScaler`,
which refuses the matrix. `TestTheBranchIsStillUnreachableThroughClassify` pins
that with a seeded fixture, so this fix is latent rather than observable: no
payload `classify` can currently return changes, and no state label changes in
any reachable classification. What changes is the line: a knowingly-wrong
arithmetic, published with a comment saying so, is its own defect.

The classification consequence is pinned separately, through the real
`_label_states_by_risk`, because that is the function that consumes `cagr`:
`TestAWipedOutStateCannotBeLabelledBull` runs the SAME table through the label
mapper with the old arithmetic figure and with -1.0.

No DB, no network: seeded RNG only.
"""

import inspect

import numpy as np
import pandas as pd
import pytest

from app.services import regime_service as rs
from app.services.regime_service import _label_states_by_risk, classify

SEED = 20260214
WINDOW = rs.REGIME_FEATURE_WINDOW_DAYS
YEAR = rs.TRADING_DAYS_PER_YEAR

#: A state that earned +5% a day for 29 days and then lost everything on the
#: 30th. Its compounded product is exactly 0.
WIPED_OUT_RETURNS = np.concatenate([np.full(29, 0.05), [-1.0]])


def _wiped_out(n_sub: int = 30) -> np.ndarray:
    """`n_sub` daily returns whose compounded product is exactly zero."""
    return np.concatenate([np.full(n_sub - 1, 0.05), [-1.0]])


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------
class TestAZeroProductIsAGeometricTotalLoss:
    @pytest.mark.parametrize("n_sub", [1, 30, 90, 300, 800])
    def test_the_geometric_annualization_of_a_wipeout_is_minus_one(self, n_sub):
        r_sub = _wiped_out(n_sub)
        cum_prod = np.prod(1.0 + r_sub)
        # the premise: this is the branch, and it is the one that was wrong
        assert cum_prod == 0.0
        assert not cum_prod > 0
        # the fix, evaluated exactly as the source evaluates it
        assert float((cum_prod ** (YEAR / n_sub)) - 1.0) == -1.0

    def test_the_source_branch_is_the_geometric_one(self):
        """The branch is unreachable through `classify`, so this is the binding.

        `inspect.getsource` on the estimator is this repo's idiom for pinning a
        line that no fixture can execute (see test_evt_es_clamp_has_no_cosmetic_
        five_pct_gap in test_bugfix_quant_services.py).
        """
        branch = (
            inspect.getsource(classify)
            .split("elif cum_prod == 0:")[1]
            .split("\n            else:")[0]
        )
        assert "cum_prod ** (TRADING_DAYS_PER_YEAR / n_sub)" in branch
        assert "r_sub.mean()" not in branch, "the arithmetic fallback is still there"
        assert (
            "geometric_cagr_from_compounded_state_returns" in branch
        ), "a zero product must report the geometric definition it actually used"
        assert "arithmetic_mean_fallback_product_wiped_out" not in branch

    def test_it_reports_the_same_method_token_as_every_other_measured_state(self):
        """One formula, one token. A second token would be a second definition."""
        branch = (
            inspect.getsource(classify)
            .split("elif cum_prod == 0:")[1]
            .split("\n            else:")[0]
        )
        positive = (
            inspect.getsource(classify)
            .split("if cum_prod > 0:")[1]
            .split("\n            elif")[0]
        )
        assert 'ann_ret_method = "geometric_cagr_from_compounded_state_returns"' in branch
        assert branch.count("ann_ret_method = ") == 1
        assert positive.count("ann_ret_method = ") == 1


class TestTheRetiredFallbackWasNotMerelyImprecise:
    """The line it replaced substituted a different quantity, and a positive one."""

    @pytest.mark.parametrize("n_sub", [30, 90, 300, 800])
    def test_the_arithmetic_mean_of_a_wiped_out_state_is_positive(self, n_sub):
        r_sub = _wiped_out(n_sub)
        arithmetic = float(r_sub.mean() * YEAR)
        geometric = -1.0
        assert arithmetic > 0.0, "a +5%-a-day state that lost everything"
        assert arithmetic != geometric
        # ... so it was not a small error on a rare input: the sign is wrong.
        assert (arithmetic > 0.0) != (geometric > 0.0)

    def test_the_published_annualization_factor_is_the_exponent_the_fix_applies(self):
        """`annualization_factor` publishes 252/n, the exponent on `cum_prod`."""
        payload = classify(_returns_frame(), is_returns=True)
        for row in payload["states"]:
            assert row["annualization_factor"] == pytest.approx(
                YEAR / row["observations"], abs=1e-4
            )


# ---------------------------------------------------------------------------
# The classification consequence, pinned through the real label mapper
# ---------------------------------------------------------------------------
class TestAWipedOutStateCannotBeLabelledBull:
    """`_label_states_by_risk` sorts on `cagr`, so the figure IS the label."""

    @staticmethod
    def _table(cagr_zero: float) -> pd.DataFrame:
        # Two ordinary states either side of the wiped-out one, so the sort has
        # something to move relative to.
        return pd.DataFrame(
            {"cagr": [cagr_zero, 0.05, 0.35], "ann_vol": [0.4, 0.2, 0.3]},
            index=[0, 1, 2],
        )

    def test_the_retired_fallback_crowned_a_wiped_out_state_bull(self):
        """BEFORE, pinned: the arithmetic figure is positive and sorts first."""
        old_cagr = float(WIPED_OUT_RETURNS.mean() * YEAR)
        assert old_cagr > 0.0
        assert _label_states_by_risk(self._table(old_cagr)) == {
            0: "bull", 1: "crisis", 2: "calm",
        }

    def test_the_geometric_wipeout_crowns_it_crisis(self):
        """AFTER, pinned: -1.0 is the lowest of the three, so it is `crisis`."""
        assert _label_states_by_risk(self._table(-1.0)) == {
            0: "crisis", 1: "calm", 2: "bull",
        }

    def test_the_wiped_out_state_moved_from_best_ranked_to_worst(self):
        old_cagr = float(WIPED_OUT_RETURNS.mean() * YEAR)
        before = _label_states_by_risk(self._table(old_cagr))
        after = _label_states_by_risk(self._table(-1.0))
        # The wiped-out state went from the best-ranked to the worst-ranked.
        assert before[0] == "bull" and after[0] == "crisis"
        # The other two kept their relative order and slid one place each, and
        # every state is still labelled exactly once.
        assert before[1] == "crisis" and before[2] == "calm"
        assert after[1] == "calm" and after[2] == "bull"
        assert set(before.values()) == set(after.values()) == {"crisis", "calm", "bull"}

    def test_the_fix_cannot_be_reached_by_a_ranking_change_in_ann_vol(self):
        """Structural: `cagr` is the only input the mapper reads."""
        table = self._table(-1.0)
        shuffled = table.iloc[::-1]
        assert _label_states_by_risk(shuffled) == _label_states_by_risk(table)
        rescaled = table.copy()
        rescaled["ann_vol"] = rescaled["ann_vol"] * 0.0 + 1e6
        assert _label_states_by_risk(rescaled) == _label_states_by_risk(table)


# ---------------------------------------------------------------------------
# The reachability caveat, measured
# ---------------------------------------------------------------------------
def _returns_frame(seed=SEED, periods=900, wipeout_at=None, wipeout_value=-1.0):
    dates = pd.bdate_range("2020-01-01", periods=periods)
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0006, 0.012, periods)
    rets[300:340] = rng.normal(-0.011, 0.021, 40)
    rets[600:640] = rng.normal(0.004, 0.026, 40)
    if wipeout_at is not None:
        rets[wipeout_at] = wipeout_value
    return pd.Series(rets, index=dates)


class TestTheBranchIsStillUnreachableThroughClassify:
    """A total-loss day zeroes `close`, and `-inf` survives `dropna()`.

    So the mechanism is asserted here rather than quoted from a comment: the
    wiping day drives the reconstructed close to exactly 0, `ret21` is `-inf` on
    that row, `dropna()` keeps it (it drops NaN, not -inf), and the
    StandardScaler refuses the matrix. Nothing below therefore reaches any
    state's `r_sub`.
    """

    def test_the_wiping_day_does_reach_the_scaler_as_minus_infinity(self):
        """The mechanism itself, asserted without going through the estimator."""
        rets = _returns_frame(wipeout_at=700, wipeout_value=-1.0)
        close = (1.0 + rets).cumprod()
        with np.errstate(divide="ignore", invalid="ignore"):
            # as `classify` computes it, under the same containment
            ret21 = np.log(close / close.shift(WINDOW)).dropna()
        vol21 = (rets.rolling(WINDOW).std() * np.sqrt(YEAR)).dropna()
        common = ret21.index.intersection(vol21.index)
        feats = pd.concat(
            [ret21.loc[common].rename("ret21"), vol21.loc[common].rename("vol21")],
            axis=1,
        ).dropna()
        assert close.iloc[700] == 0.0
        assert np.isneginf(ret21.loc[rets.index[700]]), "dropna() keeps -inf"
        assert not np.isfinite(feats["ret21"]).all()
        with pytest.raises(ValueError, match="infinity"):
            classify(rets, is_returns=True)

    def test_a_total_loss_day_is_refused_rather_than_published(self):
        with pytest.raises(ValueError, match="infinity"):
            classify(_returns_frame(wipeout_at=700, wipeout_value=-1.0), is_returns=True)

    def test_a_worse_than_total_loss_day_is_dropped_before_any_state(self):
        """`r < -1` flips the sign of `close`, so that row's ret21 is NaN and
        `dropna()` removes the wiping day before it can reach any `r_sub`."""
        payload = classify(_returns_frame(wipeout_at=700, wipeout_value=-1.5), is_returns=True)
        assert payload is not None
        assert {row["ann_ret_method"] for row in payload["states"]} == {
            "geometric_cagr_from_compounded_state_returns"
        }

    def test_no_reachable_classification_reports_a_wipeout(self):
        """Seeded fixture, so the whole payload is pinned as unaffected.

        Every state is on the geometric definition and none of them is a total
        loss, so no label in this payload could have moved. Combined with the
        refusal above, that is the honest statement of what the fix changed: a
        line, not an output.
        """
        payload = classify(_returns_frame(), is_returns=True)
        assert payload is not None
        rows = payload["states"]
        assert len(rows) == rs.REGIME_STATES
        for row in rows:
            assert row["ann_ret_method"] == "geometric_cagr_from_compounded_state_returns"
            assert row["ann_ret"] > -1.0, "no state lost everything in this fixture"
            assert row["regime"] in {"crisis", "calm", "bull"}
        assert {row["regime"] for row in rows} == {"crisis", "calm", "bull"}
        assert {row["observations"] for row in rows} == {112, 718, 49}
        # the label ordering the published cagrs imply, read off the payload
        by_regime = {row["regime"]: row["ann_ret"] for row in rows}
        assert by_regime["crisis"] < by_regime["calm"] < by_regime["bull"]


# ---------------------------------------------------------------------------
# The disclosure has to match the code
# ---------------------------------------------------------------------------
class TestTheUnitsBlockRetiresTheTokenInsteadOfDescribingIt:
    def test_the_qualifier_says_the_wiped_out_fallback_is_retired(self):
        meta = rs._regime_metadata({}, use_returns=False, lookback_days=1100)
        qualifier = meta["units"]["states[].ann_ret_method"]
        assert meta["units"]["states[].ann_ret"] == "annualized_fraction_geometric_cagr"
        assert "arithmetic_mean_fallback_product_wiped_out" in qualifier
        assert "RETIRED" in qualifier
        # The retired token must not still be described as producing a figure.
        retired_clause = qualifier.split("arithmetic_mean_fallback_product_wiped_out")[1]
        assert "no longer published" in retired_clause
        assert "-1.0" in retired_clause
        # the surviving fallback is still declared as the definition switch it is
        assert "arithmetic_mean_fallback_product_negative" in qualifier
        assert "NEGATIVE" in qualifier
        assert "ARITHMETIC" in qualifier
        assert "different quantity" in qualifier
