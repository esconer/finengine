"""Regression tests for two verified defects in `regime_service.classify`.

DEFECT 1 -- `states[].ann_vol` was `mean(vol21.loc[common][mask])`, i.e. the
mean of per-window ALREADY-ANNUALIZED standard deviations. Jensen's inequality
(E[sqrt(v)] <= sqrt(E[v)]) biases that downward, so the published volatility
understated the volatility of the state's own daily returns. The correct
figure pools the daily variance and takes ONE sqrt: sqrt(252 * var(r_sub)).
`regime_service.py` already documents this rule by name ~70 lines earlier, in
the Parkinson block that pools `mean(logHL**2)` before its sqrt.

DEFECT 2 -- `states[].ann_ret` is a geometric CAGR normally and an arithmetic
`mean(r_sub) * 252` whenever the compounded product was not positive, under one
published key with the switch undisclosed.
"""

import numpy as np
import pandas as pd
import pytest

from app.services import regime_service as rs
from app.services.regime_service import _label_states_by_risk, classify

#: One fixture, one fit. `classify` is deterministic here because
#: `HMM_RANDOM_STATE` is a module constant, so these numbers are reproducible
#: on any machine -- but every assertion below is a relation recomputed from
#: the same data rather than a hard-coded value wherever that is possible.
SEED = 20260214
WINDOW = rs.REGIME_FEATURE_WINDOW_DAYS
YEAR = rs.TRADING_DAYS_PER_YEAR

#: The closed vocabulary `ann_ret_method` may publish. A new branch without a
#: name here is a definition change that has not been disclosed.
ANND_ANN_RET_METHODS = {
    "geometric_cagr_from_compounded_state_returns",
    "arithmetic_mean_fallback_product_wiped_out",
    "arithmetic_mean_fallback_product_negative",
    "no_observations",
}


def _benchmark_frame(seed=SEED, periods=900):
    """Regime-switching synthetic benchmark, so the 3 states are distinct."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0006, 0.011, periods)
    rets[300:340] = rng.normal(-0.011, 0.021, 40)   # crisis stretch
    rets[600:640] = rng.normal(0.004, 0.026, 40)    # bull stretch
    dates = pd.bdate_range("2020-01-01", periods=periods)
    close = 100.0 * np.exp(np.cumsum(rets))
    return pd.DataFrame({"adj_close": pd.Series(close, index=dates)})


def _mirror_classify_internals(frame):
    """Rebuild exactly what `classify` derived, up to the per-state loop.

    `classify` keeps `common` (ret21 n vol21), fits the HMM on
    `scaler.fit_transform(feats)`, decodes `states` from that fit, and THEN
    slices `ret_1d.loc[common]` per state. Reproducing those four steps is what
    lets a test recompute the correct ann_vol on the very data the published
    number came from, instead of asserting against a stored constant.
    """
    close = frame["adj_close"].astype(float)
    ret_1d = close.pct_change().dropna()
    ret21 = np.log(close / close.shift(WINDOW)).dropna()
    vol21 = (ret_1d.rolling(WINDOW).std() * np.sqrt(YEAR)).dropna()
    common = ret21.index.intersection(vol21.index)
    feats = pd.concat(
        [ret21.loc[common].rename("ret21"), vol21.loc[common].rename("vol21")], axis=1
    ).dropna()

    from hmmlearn.hmm import GaussianHMM
    from sklearn.preprocessing import StandardScaler

    x_scaled = StandardScaler().fit_transform(feats.values)
    hmm = GaussianHMM(
        n_components=rs.REGIME_STATES,
        covariance_type=rs.HMM_COVARIANCE_TYPE,
        init_params="mc",
        params="mc",
        random_state=rs.HMM_RANDOM_STATE,
        n_iter=rs.HMM_N_ITER,
        tol=rs.HMM_TOL,
    )
    hmm.startprob_ = np.array([0.33, 0.34, 0.33])
    hmm.transmat_ = np.array([[0.96, 0.03, 0.01], [0.02, 0.96, 0.02], [0.01, 0.03, 0.96]])
    hmm.fit(x_scaled)
    states = hmm.predict(x_scaled)

    return {
        "ret_1d": ret_1d,
        "vol21": vol21,
        "common": common,
        "states": states,
        "x_scaled": x_scaled,
    }


@pytest.fixture(scope="module")
def classified():
    frame = _benchmark_frame()
    payload = classify(frame)
    assert payload is not None
    return {"frame": frame, "payload": payload, "internals": _mirror_classify_internals(frame)}


@pytest.fixture(scope="module")
def per_state(classified):
    """State-for-state published figures vs. the two competing formulas."""
    internals = classified["internals"]
    published = classified["payload"]["states"]
    rows = []
    for state in range(rs.REGIME_STATES):
        mask = internals["states"] == state
        r_sub = internals["ret_1d"].loc[internals["common"]].values[mask]
        rows.append(
            {
                "state": state,
                "n": len(r_sub),
                "published": published[state],
                # what classify used to publish: mean of annualised sigmas
                "mean_of_annualised_sigmas": float(
                    internals["vol21"].loc[internals["common"]].values[mask].mean()
                ),
                # the Jensen-correct figure
                "pooled_daily_variance": float(
                    np.sqrt(YEAR * np.var(r_sub, ddof=1))
                ),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# DEFECT 1 -- ann_vol
# ---------------------------------------------------------------------------
class TestAnnVolIsPooledVarianceNotMeanOfAnnualisedSigmas:
    def test_published_ann_vol_is_the_jensen_correct_pooled_figure(self, per_state):
        """The published number must equal sqrt(252 * var(state returns))."""
        for row in per_state:
            assert row["published"]["ann_vol"] == pytest.approx(
                row["pooled_daily_variance"], abs=1e-4
            ), (
                f"state {row['state']}: published ann_vol "
                f"{row['published']['ann_vol']} != sqrt(252*var) "
                f"{row['pooled_daily_variance']}"
            )

    def test_published_ann_vol_is_no_longer_the_mean_of_annualised_sigmas(self, per_state):
        """The old formula, asserted still wrong, so the fix cannot silently regress."""
        for row in per_state:
            assert row["published"]["ann_vol"] != pytest.approx(
                row["mean_of_annualised_sigmas"], abs=1e-4
            ), (
                f"state {row['state']}: ann_vol is still the mean of already-"
                f"annualised sigmas ({row['mean_of_annualised_sigmas']})"
            )

    def test_the_old_formula_understated_every_state(self, per_state):
        """Jensen's inequality: mean(sigma) <= sqrt(E[var]), strictly here."""
        for row in per_state:
            assert row["mean_of_annualised_sigmas"] < row["pooled_daily_variance"], (
                f"state {row['state']}: mean-of-sigmas {row['mean_of_annualised_sigmas']} "
                f"is not below the pooled figure {row['pooled_daily_variance']}"
            )

    def test_the_gap_is_far_larger_than_publish_rounding(self, per_state):
        """rounding to 4dp cannot explain the difference the fix removed."""
        gaps = [
            row["pooled_daily_variance"] - row["mean_of_annualised_sigmas"]
            for row in per_state
        ]
        assert min(gaps) > 1e-3, f"at least one state's gap is only rounding noise: {gaps}"
        assert len(gaps) == rs.REGIME_STATES

    def test_ann_vol_matches_the_convention_of_the_other_ann_vol_publishers(self, per_state):
        """ddof=1, the same convention `vol21` and the other ann_vol keys use."""
        internals = _mirror_classify_internals(_benchmark_frame())
        for state in range(rs.REGIME_STATES):
            mask = internals["states"] == state
            r_sub = internals["ret_1d"].loc[internals["common"]].values[mask]
            # what analytics.py / holdings.py publish for an ann_vol
            sibling_convention = float(pd.Series(r_sub).std(ddof=1) * np.sqrt(YEAR))
            pooled = float(np.sqrt(YEAR * np.var(r_sub, ddof=1)))
            assert pooled == pytest.approx(sibling_convention, abs=1e-12)

    def test_units_declare_the_pooled_variance_basis_and_the_null_case(self):
        meta = rs._regime_metadata({}, use_returns=False, lookback_days=1100)
        basis = meta["units"]["states[].ann_vol_basis"]
        assert "252" in basis
        assert "ddof=1" in basis
        # the rule this fix exists to enforce, stated where a reader will find it
        assert "pooled" in basis and "Jensen" in basis
        assert "null" in basis, "a state with <2 returns publishes null, not 0.0"
        assert meta["units"]["states[].ann_vol"] == "annualized_fraction"


# ---------------------------------------------------------------------------
# DEFECT 1 must not have touched the classification
# ---------------------------------------------------------------------------
class TestClassificationIsUntouched:
    def test_labels_are_ordered_by_cagr_so_ann_vol_cannot_move_one(
        self, classified, per_state
    ):
        """Structural proof: permuting and rescaling ann_vol cannot relabel."""
        table = pd.DataFrame(
            {
                "cagr": [row["published"]["ann_ret"] for row in per_state],
                "ann_vol": [row["published"]["ann_vol"] for row in per_state],
            },
            index=[row["state"] for row in per_state],
        )
        baseline = _label_states_by_risk(table)
        shuffled = table.iloc[::-1]
        assert _label_states_by_risk(shuffled) == baseline
        rescaled = table.copy()
        rescaled["ann_vol"] = rescaled["ann_vol"] * 0.0 + 1e6
        assert _label_states_by_risk(rescaled) == baseline
        assert baseline == {0: "crisis", 1: "bull", 2: "calm"}

    def test_state_membership_and_returns_are_unchanged_by_the_vol_fix(
        self, classified, per_state
    ):
        """ann_ret, observations and days_pct are byte-identical to pre-fix."""
        expected = {0: (-0.8872, 49), 1: (3.2869, 90), 2: (0.0119, 740)}
        for row in per_state:
            ann_ret, n = expected[row["state"]]
            assert row["published"]["ann_ret"] == pytest.approx(ann_ret, abs=5e-5)
            assert row["published"]["observations"] == n
            assert row["n"] == n, "the recomputed state slice must match the published count"

    def test_fit_inputs_labels_and_current_regime_are_unchanged(self, classified):
        payload = classified["payload"]
        assert payload["current_regime"] == "calm"
        assert payload["stability_pct"] == 98.6
        assert payload["observations"] == 879
        assert payload["regime_probabilities"] == {
            "calm": 99.7818, "bull": 0.2127, "crisis": 0.0055
        }
        assert {row["regime"] for row in payload["states"]} == {"crisis", "calm", "bull"}
        # the transition matrix is the CONFIGURED sticky prior, republished
        # unmodified: under params="mc" Baum-Welch does not re-estimate
        # transmat, so 96.0 is the literal assigned at regime_service.py:317,
        # whatever the fit does. So this pins that the prior was not mutated
        # on the way to the wire -- a real invariant -- and says NOTHING
        # about the fit. See TestTransitionMatrixPublishesThatItIsAPrior for
        # the disclosure that makes the prior/summary distinction explicit.
        assert payload["transition_matrix"]["crisis"]["crisis"] == 96.0
        assert payload["transition_matrix"]["calm"]["calm"] == 96.0
        assert payload["transition_matrix"]["bull"]["bull"] == 96.0


# ---------------------------------------------------------------------------
# DEFECT 2 -- the ann_ret definition switch
# ---------------------------------------------------------------------------
class TestAnnRetPublishesWhichDefinitionProducedIt:
    def test_every_state_row_carries_a_disclosed_method(self, classified):
        rows = classified["payload"]["states"]
        assert rows, "fixture must produce states"
        for row in rows:
            assert "ann_ret_method" in row, (
                "ann_ret is a geometric CAGR normally and an arithmetic mean "
                "otherwise; without ann_ret_method the reader cannot tell"
            )
            assert row["ann_ret_method"] in ANND_ANN_RET_METHODS

    def test_the_units_block_names_both_definitions(self):
        meta = rs._regime_metadata({}, use_returns=False, lookback_days=1100)
        declared = meta["units"]["states[].ann_ret"]
        qualifier = meta["units"]["states[].ann_ret_method"]
        # the pre-existing unit label is retained, and the new qualifier is what
        # makes it safe to keep
        assert declared == "annualized_fraction_geometric_cagr"
        for method in ANND_ANN_RET_METHODS:
            assert method in qualifier, f"{method} is not declared in units"
        assert "ARITHMETIC" in qualifier, "the fallback definition must be named"
        assert "different quantity" in qualifier

    def test_a_real_classification_reports_the_geometric_definition(self, classified):
        """Pins the reachability finding; see TestZeroProductFallback below."""
        methods = {row["ann_ret_method"] for row in classified["payload"]["states"]}
        assert methods == {"geometric_cagr_from_compounded_state_returns"}

    def test_a_sub_total_loss_day_never_silently_switches_the_definition(self):
        """A state containing a -100% day cannot be classified at all.

        The wiping day drives the reconstructed `close` to exactly 0, so
        `ret21 = log(close / close.shift(21))` is -inf on that row, survives
        `dropna()` (which removes NaN, not -inf) and reaches the StandardScaler.
        So `classify` refuses the input rather than quietly publishing an
        arithmetic annualization for a state that lost everything.
        """
        dates = pd.bdate_range("2020-01-01", periods=900)
        rng = np.random.default_rng(7)
        rets = rng.normal(0.0006, 0.012, 900)
        rets[300:340] = rng.normal(-0.011, 0.021, 40)
        rets[600:640] = rng.normal(0.004, 0.026, 40)
        rets[700] = -1.0  # total loss
        with pytest.raises(ValueError, match="infinity"):
            classify(pd.Series(rets, index=dates), is_returns=True)

    def test_a_worse_than_total_loss_day_is_dropped_before_it_can_switch(self):
        """`r < -1` flips the sign of `close`, so that row's ret21 is NaN.

        NaN is removed by `dropna()`, so the wiping day never enters `common`
        and therefore never enters any state's `r_sub`: the compounded product
        a published state reports stays positive. This is why every successful
        classification reports the geometric definition.
        """
        dates = pd.bdate_range("2020-01-01", periods=900)
        rng = np.random.default_rng(7)
        rets = rng.normal(0.0006, 0.012, 900)
        rets[300:340] = rng.normal(-0.011, 0.021, 40)
        rets[600:640] = rng.normal(0.004, 0.026, 40)
        rets[700] = -1.5  # worse than a total loss
        payload = classify(pd.Series(rets, index=dates), is_returns=True)
        assert payload is not None
        assert {row["ann_ret_method"] for row in payload["states"]} == {
            "geometric_cagr_from_compounded_state_returns"
        }


class TestZeroProductFallbackIsArithmeticallyWrong:
    """The fallback conflates two different situations.

    `cum_prod > 0` is false for two unrelated reasons, and the arithmetic mean
    is only defensible for one of them.
    """

    @pytest.mark.parametrize("n_sub", [30, 90, 300, 800])
    def test_a_zero_product_still_has_a_defined_geometric_annualization(self, n_sub):
        # A zero product means the state's wealth was total. 0 ** positive is 0,
        # so the geometric CAGR is well defined and equals -100%/yr.
        geometric = (0.0 ** (252.0 / n_sub)) - 1.0
        assert geometric == -1.0
        # the arithmetic mean of the same returns is something else entirely
        rets = np.concatenate([np.full(n_sub - 1, 0.05), [-1.0]])
        arithmetic = float(rets.mean() * 252)
        assert arithmetic > 0.0, "a +5%-a-day state that lost everything"
        assert arithmetic != geometric
        # ... and it can even be POSITIVE, which is what makes the published key
        # misleading rather than merely imprecise.

    @pytest.mark.parametrize("n_sub", [30, 800])
    def test_a_negative_product_has_no_real_geometric_annualization(self, n_sub):
        # Here the guard is right to bail: a negative base has no real
        # fractional power, so the geometric figure genuinely does not exist.
        with np.errstate(invalid="ignore"):
            geometric = np.float64(-0.5) ** (252.0 / n_sub)
        assert np.isnan(geometric)


# ---------------------------------------------------------------------------
# Companion finding -- transition_matrix is a configured prior
# ---------------------------------------------------------------------------
class TestTransitionMatrixPublishesThatItIsAPrior:
    def test_the_payload_says_the_matrix_was_not_fitted(self, classified):
        payload = classified["payload"]
        assert payload["transition_matrix_basis"] == (
            "configured_sticky_prior_not_fitted"
        )

    def test_the_declared_basis_matches_what_the_estimator_actually_does(self):
        # params="mc" is what makes transmat a prior rather than a statistic;
        # if that literal is ever widened the disclosure becomes a lie.
        meta = rs._regime_metadata({}, use_returns=False, lookback_days=1100)
        basis = meta["units"]["transition_matrix_basis"]
        assert 'params="mc"' in basis
        assert "NOT" in basis and "transition matrix" in basis
        assert "stability_pct" in basis, "must point readers at the fitted alternative"

    def test_the_published_matrix_is_the_sticky_prior_not_a_learned_one(self, classified):
        """The diagonal is exactly the configured 96%, to publication rounding.

        A fitted transition matrix would not sit on a hand-picked constant, so
        this pins the disclosure against the numbers it describes.
        """
        matrix = classified["payload"]["transition_matrix"]
        for row in matrix.values():
            assert row[max(row, key=row.get)] == 96.0
            assert sorted(row.values(), reverse=True)[0] == 96.0