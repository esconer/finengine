"""PA-1 regression gate: the optimizer's published moments are the moments of
the weights it publishes beside them.

The defect this locks down
--------------------------
`_hrp_weights` returns its Series in scipy-linkage LEAF order. `optimize()`
rebound only `assets` to that order and left `mu`/`cov` in `returns.columns`
order, so `mu @ w_vec` and `w_vec @ cov @ w_vec` were dot products of two
differently-ordered vectors. On the live book this printed
`expected_sharpe = +1.356` for a portfolio whose true Sharpe was **-0.3745** -
a sign inversion, on a field an agent acts on. Leaf order equalled column
order in 0/400 synthetic 14-asset books, so it was the normal case, not an
edge case. `tests/test_p01_hrp.py:38` did `raw.loc[w.index]` before comparing;
the test author knew the order differed and the production path did not.

The invariant this file proves
------------------------------
`mu`, `cov` and `w` are always in `returns.columns` order, established once by
`_as_matrices` and enforced by the single funnel `_weight_vector`. So
`expected_annual_return == mu_annual @ w` and
`expected_annual_volatility == sqrt(w @ cov_annual @ w)` for the published
weights - for every strategy, and under any column order of the input.

Pure tests: no DB, no network, seeded RNG only.
"""

import numpy as np
import pandas as pd
import pytest

from app.services.optimization_service import (
    SHARPE_OBJECTIVE_STRATEGIES,
    _as_matrices,
    _hrp_weights,
    _moments,
    _weight_vector,
    optimize,
)

RF = 0.02

#: The payload rounds weights to 6 decimals and moments to 4, so a reader
#: recomputing from the PUBLISHED weights can land half a display step away
#: from the PUBLISHED moment. The exact identity is checked at 1e-9 in
#: `test_published_moments_exact_to_1e_9_against_unrounded_weights`; here the
#: budget is one 4-decimal display step plus the 6-decimal weight rounding,
#: propagated across the universe. A permuted weight vector misses this by
#: 3-4 orders of magnitude (see the anti-permutation test below).
_DISPLAY_STEP = 1e-4
_WEIGHT_ROUNDING_STEP = 5e-7


def _book(seed: int, n: int = 14, n_obs: int = 170) -> pd.DataFrame:
    """A realistic 14-asset daily return frame: factor-correlated, heteroskedastic."""
    rng = np.random.default_rng(seed)
    factors = rng.normal(size=(n_obs, n))
    loadings = np.linalg.cholesky(np.cov(factors, rowvar=False))
    vols = rng.uniform(0.10, 0.42, n)
    cols = [f"A{i:02d}" for i in range(n)]
    return pd.DataFrame(factors @ loadings * vols / np.sqrt(n), columns=cols)


def _recompute(result, rets: pd.DataFrame):
    """Recompute the moments from the PUBLISHED weights and the same mu/cov."""
    mu, cov, assets = _as_matrices(rets)
    w = np.array([result["weights"][a] for a in assets], dtype=float)
    ret = float(mu @ w)
    vol = float(np.sqrt(max(0.0, float(w @ cov @ w))))
    sharpe = (ret - RF) / vol if vol > 0 else None
    return ret, vol, sharpe


# --------------------------------------------------------------------------
# (a) the published moments equal a recomputation from the published weights
# --------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [0, 1, 2, 3, 7, 11])
@pytest.mark.parametrize("strategy", ["hrp", "min_vol", "max_sharpe", "min_cvar"])
def test_published_moments_reproduce_from_published_weights(seed, strategy):
    """The moment identity holds, and the HRP leaf order is genuinely not the
    column order on this input - so this test would have failed before PA-1."""
    rets = _book(seed)
    result = optimize(rets, strategy, risk_free_rate=RF)

    if strategy == "hrp":
        assert list(_hrp_weights(rets).index) != list(rets.columns), (
            "HRP leaf order coincided with column order; use a different seed"
        )

    ret, vol, sharpe = _recompute(result, rets)
    budget = _DISPLAY_STEP + _WEIGHT_ROUNDING_STEP * len(rets.columns)
    assert abs(result["expected_annual_return"] - ret) <= budget
    assert abs(result["expected_annual_volatility"] - vol) <= budget
    if sharpe is None:
        assert result["expected_sharpe"] is None
    else:
        assert abs(result["expected_sharpe"] - sharpe) <= budget


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 7, 11])
def test_published_moments_exact_to_1e_9_against_unrounded_weights(seed):
    """1e-9 gate on the alignment itself.

    The payload rounds weights to 6 decimals and moments to 4, so the *displayed*
    pair can only agree to ~5e-7*n. This test closes that gap by using the
    unrounded weight vector the same funnel produces, and asserts the moment
    identity at 1e-9 - i.e. the published triple is the moment of that vector,
    not of some other permutation of it.
    """
    rets = _book(seed)
    mu, cov, assets = _as_matrices(rets)
    w = _weight_vector(_hrp_weights(rets), assets)  # the single funnel

    moments = _moments(mu, cov, w, RF)
    assert moments["expected_annual_return"] == pytest.approx(float(mu @ w), abs=1e-9)
    assert moments["expected_annual_volatility"] == pytest.approx(
        float(np.sqrt(w @ cov @ w)), abs=1e-9
    )
    assert moments["expected_sharpe"] == pytest.approx(
        (float(mu @ w) - RF) / float(np.sqrt(w @ cov @ w)), abs=1e-9
    )

    result = optimize(rets, "hrp", risk_free_rate=RF)
    assert result["expected_annual_return"] == round(float(mu @ w), 4)
    assert result["expected_annual_volatility"] == round(float(np.sqrt(w @ cov @ w)), 4)


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 7, 11])
def test_moments_are_not_a_permutation_of_the_moments(seed):
    """Explicit anti-regression: the old misalignment is large, not rounding."""
    rets = _book(seed)
    result = optimize(rets, "hrp", risk_free_rate=RF)
    mu, cov, _assets = _as_matrices(rets)

    # The old code's numbers: leaf-order w against column-order mu/cov.
    leaf = _hrp_weights(rets)
    old_ret = float(mu @ leaf.values)
    old_vol = float(np.sqrt(max(0.0, leaf.values @ cov @ leaf.values)))
    old_sharpe = (old_ret - RF) / old_vol

    assert abs(old_ret - result["expected_annual_return"]) > 1e-3
    assert abs(old_vol - result["expected_annual_volatility"]) > 1e-3
    assert abs(old_sharpe - result["expected_sharpe"]) > 1e-3


def test_sharpe_of_published_weights_is_never_sign_inverted():
    """The failure mode that matters: a negative-Sharpe book published as positive."""
    flipped = 0
    for seed in range(25):
        rets = _book(seed)
        result = optimize(rets, "hrp", risk_free_rate=RF)
        _, _, sharpe = _recompute(result, rets)
        assert result["expected_sharpe"] == round(sharpe, 4)
        if sharpe is not None and sharpe < 0 and result["expected_sharpe"] > 0:
            flipped += 1
    assert flipped == 0


# --------------------------------------------------------------------------
# (b) a shuffled mu/cov column order does not change the published moments
# --------------------------------------------------------------------------

@pytest.mark.parametrize("strategy", ["min_vol", "max_sharpe", "min_cvar"])
@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5])
def test_column_shuffle_does_not_change_moments_for_positional_solvers(strategy, seed):
    """The literal form of the regression test.

    min_vol / max_sharpe / min_cvar optimise a convex problem whose solution is
    a function of the sample, not of the column order, so reversing the columns
    must leave the published weights AND all three moments bit-identical. Before
    the fix this only held by accident - the HRP-shaped misalignment was the
    only reason any strategy looked order-safe.
    """
    rets = _book(seed)
    shuffled = rets[list(rets.columns)[::-1]]

    base = optimize(rets, strategy, risk_free_rate=RF)
    other = optimize(shuffled, strategy, risk_free_rate=RF)

    assert other["weights"] == base["weights"]
    for key in ("expected_annual_return", "expected_annual_volatility", "expected_sharpe"):
        assert other[key] == base[key], f"{key} moved under a column shuffle"


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5])
def test_hrp_moments_track_the_published_weights_under_a_column_shuffle(seed):
    """HRP cannot be order-invariant: `scipy.cluster.hierarchy.linkage` consumes
    the condensed distance *vector*, which squareform emits in column order, so
    a column permutation can genuinely change the clustering (and the weights).
    What must hold under any permutation is the invariant: the published
    moments are the moments of the weights published in the same record.
    """
    rets = _book(seed)
    shuffled = rets[list(rets.columns)[::-1]]

    result = optimize(shuffled, "hrp", risk_free_rate=RF)
    ret, vol, sharpe = _recompute(result, shuffled)
    budget = _DISPLAY_STEP + _WEIGHT_ROUNDING_STEP * len(rets.columns)
    assert abs(result["expected_annual_return"] - ret) <= budget
    assert abs(result["expected_annual_volatility"] - vol) <= budget
    if sharpe is None:
        assert result["expected_sharpe"] is None
    else:
        assert abs(result["expected_sharpe"] - sharpe) <= budget


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5])
def test_alignment_layer_is_permutation_exact(seed):
    """Holds one weight vector fixed and permutes the sample around it.

    This isolates the alignment layer from the clustering: for the same
    per-ticker weights, mu/cov may be built from any column order and the
    moments must come out equal to 1e-12. Pre-fix, `optimize()` could not
    express this at all - the HRP weights arrived keyed in leaf order and
    nothing re-aligned them.
    """
    rets = _book(seed)
    shuffled = rets[list(rets.columns)[::-1]]

    mu_a, cov_a, assets_a = _as_matrices(rets)
    mu_b, cov_b, assets_b = _as_matrices(shuffled)
    assert assets_a == assets_b[::-1]

    weights = pd.Series(_weight_vector(_hrp_weights(rets), assets_a), index=assets_a)
    w_a = _weight_vector(weights, assets_a)
    w_b = _weight_vector(weights, assets_b)

    m_a = _moments(mu_a, cov_a, w_a, RF)
    m_b = _moments(mu_b, cov_b, w_b, RF)
    for key in ("expected_annual_return", "expected_annual_volatility", "expected_sharpe"):
        assert m_b[key] == pytest.approx(m_a[key], abs=1e-12)


def test_weight_funnel_rejects_a_foreign_universe():
    rets = _book(0)
    _, _, assets = _as_matrices(rets)
    with pytest.raises(ValueError, match="different universe"):
        _weight_vector(pd.Series(1.0, index=assets[:-1]), assets)


# --------------------------------------------------------------------------
# (c) the current-book objective is published on the same sample
# --------------------------------------------------------------------------

def test_current_portfolio_is_scored_on_the_same_mu_cov_and_sample():
    rets = _book(0)
    current = {a: 1.0 / len(rets.columns) for a in rets.columns}
    result = optimize(rets, "hrp", risk_free_rate=RF, current_weights=current)

    block = result["current_portfolio"]
    assert block["available"] is True
    assert block["same_sample"] is True

    mu, cov, assets = _as_matrices(rets)
    w = np.array([current[a] for a in assets], dtype=float)
    ret = float(mu @ w)
    vol = float(np.sqrt(w @ cov @ w))
    assert block["expected_annual_return"] == round(ret, 4)
    assert block["expected_annual_volatility"] == round(vol, 4)
    assert block["expected_sharpe"] == round((ret - RF) / vol, 4)

    # Same sample, same order: the deltas close against the two published levels.
    deltas = block["recommended_minus_current"]
    assert deltas["expected_annual_return"] == round(
        result["expected_annual_return"] - block["expected_annual_return"], 4
    )
    assert deltas["expected_sharpe"] == round(
        result["expected_sharpe"] - block["expected_sharpe"], 4
    )
    assert result["moments_basis"]["return_observations"] == len(rets)


def test_current_portfolio_is_reproducible_from_published_weights():
    rets = _book(1)
    current = {a: 0.5 if i < 7 else 0.5 / 7 for i, a in enumerate(rets.columns)}
    block = optimize(rets, "min_vol", risk_free_rate=RF, current_weights=current)[
        "current_portfolio"
    ]
    mu, cov, assets = _as_matrices(rets)
    w = np.array([current[a] for a in assets], dtype=float)
    assert block["expected_annual_return"] == round(float(mu @ w), 4)
    assert block["expected_annual_volatility"] == round(float(np.sqrt(w @ cov @ w)), 4)
    assert block["published_weight_total"] == round(float(w.sum()), 6)


def test_current_portfolio_reports_unmeasured_legs_instead_of_dropping_them():
    rets = _book(0)
    current = {a: 1.0 / len(rets.columns) for a in rets.columns}
    current["NOTSAMPLED.NS"] = 0.25
    block = optimize(rets, "hrp", risk_free_rate=RF, current_weights=current)[
        "current_portfolio"
    ]
    assert block["tickers_without_sample"] == ["NOTSAMPLED.NS"]
    # The scored vector covers exactly the sampled universe, un-renormalised.
    assert block["published_weight_total"] == round(1.0, 6)


def test_current_portfolio_is_null_with_a_reason_when_not_supplied():
    block = optimize(_book(0), "hrp", risk_free_rate=RF)["current_portfolio"]
    assert block["available"] is False
    assert "no current weights" in block["unavailable_reason"]
    assert "expected_sharpe" not in block  # never a substitute number


def test_current_portfolio_refuses_a_book_with_no_positive_gross_exposure():
    rets = _book(0)
    zero = {a: 0.0 for a in rets.columns}
    block = optimize(rets, "hrp", risk_free_rate=RF, current_weights=zero)[
        "current_portfolio"
    ]
    assert block["available"] is False
    assert "positive gross exposure" in block["unavailable_reason"]


# --------------------------------------------------------------------------
# (d) expected_sharpe carries a basis, or is absent
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "strategy,is_objective",
    [
        ("hrp", False),
        ("min_vol", False),
        ("min_cvar", False),
        ("max_sharpe", True),
        ("black_litterman", True),
    ],
)
def test_expected_sharpe_carries_a_basis_for_every_strategy(strategy, is_objective):
    result = optimize(_book(0), strategy, risk_free_rate=RF)
    objective = result["objective"]
    assert objective["expected_sharpe_was_the_optimised_objective"] is is_objective
    assert result["expected_sharpe"] is not None, (
        "expected_sharpe is present, so it must be labelled"
    )
    if not is_objective:
        assert "DESCRIPTIVE" in objective["expected_sharpe_basis"]
        assert "not the quantity that was maximised" in objective["expected_sharpe_basis"]
    else:
        assert "maximised" in objective["expected_sharpe_basis"]
    assert strategy in SHARPE_OBJECTIVE_STRATEGIES or "optimises" in objective[
        "expected_sharpe_basis"
    ]


def test_hrp_objective_never_claims_sharpe_was_maximised():
    """PA-2: `hrp` clusters and allocates; it does not maximise Sharpe."""
    for seed in range(5):
        result = optimize(_book(seed), "hrp", risk_free_rate=RF)
        assert result["objective"]["expected_sharpe_was_the_optimised_objective"] is False
        assert "hierarchical risk parity" in result["objective"]["what_was_optimised"]


# --------------------------------------------------------------------------
# no regression: determinism, statelessness, weight contract
# --------------------------------------------------------------------------

@pytest.mark.parametrize("strategy", ["hrp", "min_vol", "min_cvar"])
def test_optimize_is_deterministic_and_does_not_mutate_its_input(strategy):
    rets = _book(4)
    snapshot = rets.copy(deep=True)
    first = optimize(rets, strategy, risk_free_rate=RF)
    second = optimize(rets, strategy, risk_free_rate=RF)
    assert first == second
    pd.testing.assert_frame_equal(rets, snapshot)


def test_weights_are_published_in_column_order_and_still_normalized():
    rets = _book(0)
    result = optimize(rets, "hrp", risk_free_rate=RF)
    assert list(result["weights"]) == list(rets.columns)
    assert all(v >= 0 for v in result["weights"].values())
    assert abs(sum(result["weights"].values()) - 1.0) < 1e-4


def test_zero_variance_leg_publishes_null_sharpe_with_a_reason_not_a_number():
    rets = _book(0)
    flat = rets.copy()
    flat.iloc[:, 0] = 0.0
    result = optimize(flat, "hrp", risk_free_rate=RF)
    if result["expected_sharpe"] is None:
        assert result["moments_basis"]["unavailable_reason"]
    else:
        _, vol, sharpe = _recompute(result, flat)
        budget = _DISPLAY_STEP + _WEIGHT_ROUNDING_STEP * len(flat.columns)
        assert abs(result["expected_sharpe"] - sharpe) <= budget
        assert abs(result["expected_annual_volatility"] - vol) <= budget


def test_unknown_strategy_still_raises():
    with pytest.raises(ValueError, match="Unknown strategy"):
        optimize(_book(0), "not_a_strategy")
