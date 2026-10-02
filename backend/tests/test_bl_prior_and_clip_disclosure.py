"""Black-Litterman: the equilibrium prior and the pre-publication clip are disclosed.

Two defects, both of the same shape: a number reached the user that the payload
did not describe. Neither is repaired here -- both are *named*.

EL-1 -- the equilibrium prior is a synthetic equal-weight portfolio
--------------------------------------------------------------------
`_black_litterman` builds `pi = delta * (cov_ann @ w_mkt)` with

    w_mkt = np.ones(n) / n

an equal-weight vector over whatever legs the caller supplied. It is not a
market portfolio, and it is not a fallback that better input would displace:
`_black_litterman`, `_black_litterman_solved` and `optimize()` take no market
caps, `OptimizeRequest` sends none, and the only other caller
(`backtest_service.optimize`) passes only `returns` and `strategy`.

The consequence is sharp and checkable: with no views the tangency of this
prior is equal weight EXACTLY (`Sigma^-1 pi = delta * 1/n`), so the no-views
payload is equal weight to the last published decimal (`_REF_NO_VIEWS` below).
An equal-weight assumption presented as a market equilibrium is not a
quantitative error -- it is an undisclosed one.

Sourcing a genuine cap-weighted market portfolio is a DATA dependency (market
caps per ticker, with their own provenance question), not something that can be
fixed inside this function, so the honest scope is to publish
`w_mkt_basis: "equal_weight_synthetic"`. A cap-weighted prior must NOT be
synthesised to make the disclosure unnecessary: fabricating a weight is the
exact defect under repair. `test_the_prior_is_still_exactly_equal_weight` and
`test_no_market_cap_input_exists` hold that line.

EL-2 -- the clip silently rewrote the solver's answer
-----------------------------------------------------
`_black_litterman` ended

    raw = np.clip(raw, 0.0, None)
    ...
    return raw / raw.sum()

with no marker. `y >= 0` is already a constraint of the QP, so a negative weight
in the solver's answer is its own residual tolerance -- but the payload could
not distinguish that from a constraint the solver failed to satisfy, and the
renormalisation afterwards gave no hint either. Now `long_only_clip` reports
whether a clip fired, on which legs, by how much, and which branch produced the
record.

The clip-vs-constraint interaction (QM-1 made this WORSE)
----------------------------------------------------------
The already-landed covariance fix removed a `1 + tau` coefficient, so `cov_bl`
is ~30x smaller than the one it replaced. `y` therefore comes back larger in
magnitude (it scales as `1/(m'C^-1 m)`), and a solver's absolute tolerance dust
is larger RELATIVE to the weights. The long-only constraint also now BINDS on
books where it previously did not -- and a bound leg is exactly where dust
appears. A sweep of 3076 books found the clip firing on 2, one of them ONLY
under the corrected covariance. `_CLIP_BOOK` below is that book: it reproduces
deterministically (verified over 8 consecutive solves), and the clip fires on
it with magnitude ~2.4e-12, i.e. ~3.6e-14 on a published weight. So the clip is
reachable, it is newly reachable, and it was invisible.

The `-inf` trap
---------------
`np.clip(-inf, 0.0, None)` is `0.0`. The shipped guard was
`np.isnan(y.value).any()`, which lets `-inf` through, so a diverged solver would
have had its answer quietly converted into a zero weight at exactly the line
this file is about. The guard is now `np.isfinite(...).all()`, which preserves
the NaN behaviour identically and adds the infinities.

Nothing here changes a published number. `_REF_*` are the weights the
PRE-disclosure code published, pinned here so that claim is checked rather than
asserted.

Pure tests: no DB, no network, seeded RNG only.
"""

import numpy as np
import pandas as pd
import pytest

from app.services.optimization_service import (
    BL_PATH_NOT_APPLICABLE,
    BL_PATH_TANGENCY,
    W_MKT_BASIS_EQUAL_WEIGHT,
    _black_litterman,
    _black_litterman_solved,
    _clip_record,
    _long_only_clip_block,
    optimize,
)

RF = 0.02
ALL_STRATEGIES = ("hrp", "min_vol", "max_sharpe", "min_cvar", "black_litterman")


def _book(seed: int = 7, n: int = 8, n_obs: int = 400, scale: float = 0.01,
          drift: float = 0.0):
    """Correlated book: 3 factors + idiosyncratic noise (never diagonal)."""
    rng = np.random.default_rng(seed)
    beta = rng.uniform(0.3, 1.4, size=(n, 3))
    factors = rng.normal(scale=scale * 2, size=(n_obs, 3))
    idio = rng.normal(scale=scale, size=(n_obs, n))
    return pd.DataFrame(
        factors @ beta.T + idio + drift,
        columns=[f"A{i:02d}" for i in range(n)],
    )


#: `max_sharpe` raises on a book whose every expected return sits below rf.
#: A drift alone does not fix that -- on a 0.01-scale book the sample mean has
#: a standard error of ~0.0017/day, which swamps any plausible drift -- so this
#: book is also picked for a realised mean that clears rf on all five legs.
_ALL_STRATEGY_BOOK = _book(9, 5, drift=0.0005)


#: The book on which the clip demonstrably fires. Four relative views of 0.20
#: over a 6-leg book at low return scale: the tangent direction collapses onto
#: A00, the long-only bound binds on the other five, and the bound legs come
#: back with solver dust on the wrong side of zero.
_CLIP_BOOK = _book(16, 6, scale=0.002)
_CLIP_VIEWS = [
    {"long": f"A{i:02d}", "short": f"A{j:02d}", "diff": 0.20}
    for i in range(6)
    for j in range(i + 1, 6)
][:4]

#: Weights published by the code BEFORE this disclosure landed (git HEAD).
#: Pinned so "disclose, do not change the number" is verified, not claimed.
_REF_VIEWS = {
    "A00": 0.442331, "A01": 0.151231, "A02": 0.103978,
    "A03": 0.151231, "A04": 0.151231,
}
_REF_NO_VIEWS = {
    "A00": 0.2, "A01": 0.2, "A02": 0.2, "A03": 0.2, "A04": 0.2,
}
_REF_RELATIVE = {
    "A00": 0.281682, "A01": 0.051656, "A02": 0.166666,
    "A03": 0.166667, "A04": 0.166666, "A05": 0.166664,
}
_REF_BEARISH = {
    "A00": 0.298069, "A01": 0.249928, "A02": 0.267299, "A03": 0.184704,
}


def _bl(frame, **kw):
    return optimize(frame, "black_litterman", risk_free_rate=RF, **kw)


# --------------------------------------------------------------------------
# EL-1: the prior is published, and published as what it is
# --------------------------------------------------------------------------

def test_black_litterman_publishes_the_synthetic_prior_basis():
    """EL-1 red/green: the payload names the prior it actually used."""
    result = _bl(_book(0, 5), views={"A00": 0.18, "A02": -0.05})
    assert result["w_mkt_basis"] == "equal_weight_synthetic"
    assert result["w_mkt_basis"] == W_MKT_BASIS_EQUAL_WEIGHT


def test_the_basis_reason_says_it_is_not_a_market_portfolio():
    """A bare enum value would not stop a reader trusting the number."""
    reason = _bl(_book(0, 5))["w_mkt_basis_reason"]
    assert "NOT a market portfolio" in reason
    assert "equal-weight" in reason
    assert "does not fabricate" in reason, (
        "the disclosure must say the real prior was not synthesised either"
    )


@pytest.mark.parametrize("strategy", ALL_STRATEGIES)
def test_w_mkt_basis_is_published_for_every_strategy(strategy):
    """Published unconditionally, so absence never has to be interpreted."""
    frame = _ALL_STRATEGY_BOOK
    result = optimize(frame, strategy, risk_free_rate=RF)
    assert "w_mkt_basis" in result
    assert result["w_mkt_basis_reason"]
    if strategy == "black_litterman":
        assert result["w_mkt_basis"] == W_MKT_BASIS_EQUAL_WEIGHT
    else:
        assert result["w_mkt_basis"] == BL_PATH_NOT_APPLICABLE
        assert strategy in result["w_mkt_basis_reason"]


def test_the_prior_is_still_exactly_equal_weight():
    """The disclosure must be TRUE, not a label over a changed construction.

    No views => `mu_bl = pi = delta * Sigma @ (1/n)` => the unconstrained
    tangency direction is `Sigma^-1 pi = delta * 1/n`, i.e. equal weight. If a
    future change makes `w_mkt` anything else, this fails and the disclosure has
    to be revisited.
    """
    weights = _bl(_book(0, 5))["weights"]
    assert weights == _REF_NO_VIEWS
    assert set(weights.values()) == {round(1 / 5, 6)}


def test_no_market_cap_input_exists():
    """Documents the verified fact that (b) was the only honest scope.

    Sourcing a real market portfolio needs a data dependency this service does
    not have. The test pins the absence so nobody can conclude a cap-weighted
    path already exists and merely went unused.
    """
    import inspect

    for fn in (_black_litterman, _black_litterman_solved, optimize):
        params = set(inspect.signature(fn).parameters)
        assert not params & {"market_caps", "market_cap", "w_mkt", "caps"}, (
            f"{fn.__name__} now takes a market-cap input; if it is plumbed "
            "through, w_mkt_basis must report the real basis instead"
        )


# --------------------------------------------------------------------------
# EL-2a: the clip record is measured off the PRE-clip answer
# --------------------------------------------------------------------------

def test_the_clip_record_reports_the_negative_weight_the_clip_removed():
    """Deterministic core of the disclosure: a known negative must surface."""
    record = _clip_record(
        BL_PATH_TANGENCY, np.array([1.0, -0.25, 0.5]), ["A", "B", "C"]
    )
    assert record["applied"] is True
    assert record["clipped_legs"] == ["B"]
    assert record["max_clipped_weight"] == pytest.approx(0.25)
    # The gross the clip is measured against is the sum of the CLIPPED vector,
    # 1.0 + 0 + 0.5 = 1.5, so 0.25 of removed weight could have moved a
    # published weight by at most 0.25/1.5 = 1/6.
    assert record["max_effect_on_published_weight"] == pytest.approx(1 / 6)


def test_the_clip_record_reports_the_WORST_negative_not_the_smallest():
    """`max_clipped_weight` means the largest magnitude removed.

    `negatives` holds negative numbers, so its `.max()` is the one closest to
    zero. Reporting that would under-state the repair whenever two legs go
    negative -- which is exactly what the real clip-firing book does
    (-2.4e-12 on one leg, -3.9e-11 on another).
    """
    record = _clip_record(
        BL_PATH_TANGENCY, np.array([1.0, -2.4e-12, 0.5, -3.9e-11]),
        ["A", "B", "C", "D"],
    )
    assert record["applied"] is True
    assert record["clipped_legs"] == ["B", "D"]
    assert record["max_clipped_weight"] == pytest.approx(3.9e-11)
    assert record["max_clipped_weight"] != pytest.approx(2.4e-12)


def test_the_clip_record_does_not_claim_a_clip_that_did_nothing():
    record = _clip_record(
        BL_PATH_TANGENCY, np.array([0.5, 0.0, 0.25]), ["A", "B", "C"]
    )
    assert record["applied"] is False
    assert record["clipped_legs"] == []
    assert record["max_clipped_weight"] is None
    assert record["max_effect_on_published_weight"] is None


def test_a_zero_weight_is_a_binding_constraint_not_a_clip():
    """`y >= 0` holds AT zero; a leg the solver placed exactly there was not
    repaired, and reporting it as clipped would invent an event."""
    record = _clip_record(BL_PATH_TANGENCY, np.array([0.5, 0.0]), ["A", "B"])
    assert record["applied"] is False
    assert record["clipped_legs"] == []


@pytest.mark.parametrize(
    "path",
    ["min_vol_fallback_no_positive_excess", "min_vol_fallback_solver_failure",
     "min_vol_fallback_nonpositive_gross"],
)
def test_a_fallback_branch_is_never_reported_as_a_clip(path):
    """Truthfulness guard.

    On a `_min_vol` fallback there is no tangency answer at all, so `applied:
    True` would be asserting something about a solver answer that does not
    exist. `solution_path` is what makes the substitution readable instead.
    """
    record = _clip_record(path, None, ["A", "B"])
    assert record["applied"] is False
    assert record["solution_path"] == path


def test_the_block_names_the_solution_path_that_produced_the_record():
    """A fallback publishes a different portfolio's weights; that must show."""
    block = _long_only_clip_block("black_litterman", _clip_record(
        "min_vol_fallback_solver_failure", None, ["A"]
    ))
    assert block["solution_path"] == "min_vol_fallback_solver_failure"
    assert block["applied"] is False


def test_a_fallback_never_claims_the_tangency_answer_was_clean():
    """The other direction of the same honesty rule.

    On a fallback there is no tangency answer, so "every leg of the solver's
    answer was already non-negative" would describe an answer that was never
    computed. The prose must point at solution_path instead.
    """
    for path in ("min_vol_fallback_no_positive_excess",
                 "min_vol_fallback_solver_failure",
                 "min_vol_fallback_nonpositive_gross"):
        block = _long_only_clip_block(
            "black_litterman", _clip_record(path, None, ["A"])
        )
        assert block["applied"] is False
        assert "already non-negative" not in block["basis"], (
            f"{path} claims a clean tangency answer that does not exist"
        )
        assert path in block["basis"]


def test_a_discarded_tangency_answer_is_not_reported_as_clean():
    """`applied: False` on the nonpositive-gross branch is not a clean bill.

    A gross of <= 0 with a negative leg means the tangency answer WAS
    infeasible and was thrown away; the block must not describe it as clean.
    """
    block = _long_only_clip_block("black_litterman", _clip_record(
        "min_vol_fallback_nonpositive_gross", None, ["A", "B"]
    ))
    assert block["applied"] is False
    assert "already non-negative" not in block["basis"]


# --------------------------------------------------------------------------
# EL-2b: the clip fires on a real book, and the payload says so
# --------------------------------------------------------------------------

def test_the_clip_actually_fires_on_a_book_and_is_disclosed():
    """RED/GREEN PROOF for EL-2, end to end through `optimize()`.

    Step 1 re-derives the pre-clip QP answer independently of the production
    path and shows it contains a negative weight -- i.e. `np.clip` really did
    rewrite this record. Step 2 shows the payload reports it.
    """
    import cvxpy as cp

    from app.services.optimization_service import _as_matrices

    _mu, cov, assets = _as_matrices(_CLIP_BOOK)
    n = len(assets)
    w_mkt = np.ones(n) / n
    pi = 2.5 * (cov @ w_mkt)
    idx = {a: i for i, a in enumerate(assets)}
    rows, qs = [], []
    for v in _CLIP_VIEWS:
        row = np.zeros(n)
        row[idx[v["long"]]] = 1.0
        row[idx[v["short"]]] = -1.0
        rows.append(row)
        qs.append(float(v["diff"]))
    P, Q = np.array(rows), np.array(qs)

    tau_sigma = 0.05 * cov
    omega = np.diag(np.clip(np.diag(P @ tau_sigma @ P.T), 1e-6, None))
    inv_inner = np.linalg.pinv(P @ tau_sigma @ P.T + omega)
    mu_bl = pi + (tau_sigma @ P.T @ inv_inner @ (Q - P @ pi))
    cov_bl = tau_sigma - (tau_sigma @ P.T @ inv_inner @ P @ tau_sigma)

    y = cp.Variable(n)
    cp.Problem(
        cp.Minimize(cp.quad_form(y, cp.psd_wrap(cov_bl))),
        [mu_bl @ y == 1, y >= 0],
    ).solve(solver=cp.CLARABEL)
    raw = np.asarray(y.value).flatten()

    # Step 1: the solver's own answer is genuinely negative somewhere, so the
    # clip is not decorative. `np.clip` changes this vector.
    assert raw.min() < 0.0, (
        "this book no longer produces a negative solver weight; the "
        "clip-firing fixture has gone stale and needs re-deriving"
    )
    assert not np.array_equal(raw, np.clip(raw, 0.0, None))

    # Step 2: the payload reports a clip on this book, naming legs, with a
    # strictly positive magnitude.
    #
    # The MAGNITUDE is deliberately not compared against `raw` above. Both are
    # solver tolerance dust on an identical QP, and the exact value moves with
    # BLAS thread blocking (3.9e-11 with default threads, 2.4e-12 with one), so
    # pinning equality across two numerically distinct runs would be a test of
    # the thread count, not of the disclosure. What is pinned is the claim: a
    # leg went negative, it was clipped, and it was reported.
    clip = _bl(_CLIP_BOOK, relative_views=_CLIP_VIEWS)["long_only_clip"]
    assert clip["solution_path"] == BL_PATH_TANGENCY
    assert clip["applied"] is True
    assert clip["clipped_legs"], "a clip fired but no leg was named"
    assert clip["max_clipped_weight"] > 0.0
    assert clip["max_effect_on_published_weight"] > 0.0
    # Dust, not a short position: a genuine long-only violation would be of
    # the order of the weights themselves, not 1e-12 smaller.
    assert clip["max_clipped_weight"] < 1e-6, (
        "the clipped magnitude is no longer tolerance dust -- if the solver is "
        "really returning shorts here, that is a constraint failure, not a "
        "clip, and the basis prose needs to say so"
    )
    for leg in clip["clipped_legs"]:
        assert leg in assets


def test_the_published_basis_says_the_weights_were_modified():
    """The brief's 'show the published basis afterwards'."""
    block = _bl(_CLIP_BOOK, relative_views=_CLIP_VIEWS)["long_only_clip"]
    basis = block["basis"]
    assert "are NOT the solver's unmodified answer" in basis
    for leg in block["clipped_legs"]:
        assert leg in basis
    assert "SCALE normalisation only" in basis
    assert "`y >= 0` is a constraint" in basis


def test_the_published_basis_does_not_claim_a_clip_on_a_clean_book():
    """The inverse failure: a false accusation is as wrong as a silent repair."""
    block = _bl(_book(0, 5), views={"A00": 0.18, "A02": -0.05})["long_only_clip"]
    assert block["applied"] is False
    assert block["clipped_legs"] == []
    assert "No clip was applied" in block["basis"]
    assert "already non-negative" in block["basis"]


# --------------------------------------------------------------------------
# EL-2c: no weight is ever manufactured
# --------------------------------------------------------------------------

def test_a_negative_weight_becomes_exactly_zero_never_its_magnitude():
    """No `np.abs`, no 'fix by construction'.

    A repaired infeasibility must read as a flat zero, which is what a reader
    can audit. `abs` would publish the magnitude of the short as a long and
    the disclosure could never catch it.
    """
    weights, clip = _black_litterman_solved(
        _CLIP_BOOK, relative_views=_CLIP_VIEWS
    )
    assert clip["applied"] is True
    for leg in clip["clipped_legs"]:
        assert weights[list(_CLIP_BOOK.columns).index(leg)] == 0.0
    assert (weights >= 0).all(), "a negative weight was published"
    assert weights.sum() == pytest.approx(1.0)


def test_an_infinite_solver_answer_would_be_clipped_into_a_zero_weight():
    """Why the guard is `isfinite` and not `isnan`.

    `np.clip(-inf, 0.0, None)` is `0.0`: a diverged solver would have had its
    answer silently converted into a zero weight by the very line under repair.
    Pinned so the guard is not quietly relaxed back to `isnan`.
    """
    assert np.clip(np.array([-np.inf, 1.0]), 0.0, None).tolist() == [0.0, 1.0]

    import inspect

    src = inspect.getsource(_black_litterman_solved)
    assert "np.isfinite(y.value).all()" in src, (
        "the non-finite solver guard was relaxed; -inf would be clipped to 0"
    )
    assert "np.isnan(y.value)" not in src


# --------------------------------------------------------------------------
# The payload tells the truth for every strategy
# --------------------------------------------------------------------------

@pytest.mark.parametrize("strategy", ALL_STRATEGIES)
def test_long_only_clip_is_published_for_every_strategy(strategy):
    frame = _ALL_STRATEGY_BOOK
    result = optimize(frame, strategy, risk_free_rate=RF)
    block = result["long_only_clip"]
    assert set(block) == {
        "solution_path", "applied", "clipped_legs",
        "max_clipped_weight", "max_effect_on_published_weight", "basis",
    }
    assert isinstance(block["applied"], bool)
    assert isinstance(block["clipped_legs"], list)
    assert block["basis"]


@pytest.mark.parametrize("strategy", ("hrp", "min_vol", "max_sharpe", "min_cvar"))
def test_non_bl_strategies_declare_that_they_never_clip_afterwards(strategy):
    """Those solvers carry `w >= 0` inside their own constraints."""
    block = optimize(
        _ALL_STRATEGY_BOOK, strategy, risk_free_rate=RF
    )["long_only_clip"]
    assert block["solution_path"] == BL_PATH_NOT_APPLICABLE
    assert block["applied"] is False
    assert block["clipped_legs"] == []
    assert strategy in block["basis"]


# --------------------------------------------------------------------------
# Nothing published moved
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "case,kwargs,frame,reference",
    [
        ("views", {"views": {"A00": 0.18, "A02": -0.05}},
         _book(0, 5), _REF_VIEWS),
        ("no_views", {}, _book(0, 5), _REF_NO_VIEWS),
        ("relative", {"relative_views": [
            {"long": "A00", "short": "A01", "diff": 0.03}]}, _book(3, 6),
         _REF_RELATIVE),
        ("bearish", {"views": {f"A0{i}": -0.05 for i in range(4)}}, _book(7, 4),
         _REF_BEARISH),
    ],
)
def test_disclosure_changed_no_published_weight(case, kwargs, frame, reference):
    """'Disclose, do not silently repair' -- verified, not asserted.

    A correct book's published allocation must be untouched by this change; the
    references are what the pre-disclosure code published.
    """
    assert _bl(frame, **kwargs)["weights"] == reference, (
        f"the {case} allocation moved; this change was supposed to add "
        "disclosure only"
    )


def test_the_clip_firing_book_still_publishes_its_pre_disclosure_weights():
    """The clip fired here, so this is the case where a silent repair would
    most plausibly have changed the number. It did not: only the marker is new.
    """
    assert _bl(_CLIP_BOOK, relative_views=_CLIP_VIEWS)["weights"] == {
        "A00": 1.0, "A01": 0.0, "A02": 0.0,
        "A03": 0.0, "A04": 0.0, "A05": 0.0,
    }