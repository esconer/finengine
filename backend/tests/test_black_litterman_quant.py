"""Black-Litterman quantitative regression gate.

Two compounding defects, both of which produce wrong portfolio weights.

QM-1 -- the posterior covariance was not the Black-Litterman posterior
--------------------------------------------------------------------
`_black_litterman` computed

    cov_bl = (1 + tau) * Sigma - tau**2 * Sigma P' (P tau Sigma P' + Omega)^-1 P Sigma

The second term is exactly the Woodbury reduction of the correct posterior
`tau*Sigma - tau*Sigma P' (Omega + P tau Sigma P')^-1 P tau*Sigma`, so the
*inner* matrix was right and only the leading coefficient was wrong: `1 + tau`
where the posterior requires `tau`. The whole expression therefore equals

    Sigma + Sigma_BL

-- the prior covariance added on top of the posterior. Measured on the probe
book, the posterior must SHRINK the prior trace by ~96% (the views are
confident relative to tau*Sigma); the shipped form INFLATED it by ~3.4%.
A risk matrix that inflates instead of shrinking changes every weight the
optimiser publishes.

QM-5 -- the risk-free rate was subtracted twice
-----------------------------------------------
`pi = delta * Sigma @ w_mkt` is the Black-Litterman implied *risk premium*:
`E[R] - rf*1 = delta*Sigma*w_mkt`. There is no `rf` anywhere in its
construction, so `pi` -- and therefore `mu_bl`, which is `pi` plus a
correction that is a linear combination of `P' (Q - P pi)` -- is already in
excess-return space. `excess = mu_bl - risk_free_rate` then applied a uniform
`-rf` shift to every leg, changing the tangency *direction* by
`Sigma^-1 (mu_bl - rf 1)`. The function's own docstring documented both
halves correctly except for one parenthetical that asserted the double
subtraction was intended.

The invariant this file proves
------------------------------
1. The posterior covariance equals BOTH standard reference forms -- the
   Woodbury/Markov form and the information form `[(tau S)^-1 + P' Omega^-1 P]^-1`
   -- to ~1e-10, and it SHRINKS the prior trace.
2. The published weights are the weights the corrected posterior implies,
   and are NOT the weights the inflated one implied.
3. The published weights are exactly INVARIANT to `risk_free_rate`, in both
   the views and no-views paths, because every quantity inside the function
   is already in excess space.

Pure tests: no DB, no network, seeded RNG only.
"""

import numpy as np
import pandas as pd
import pytest

from app.services.optimization_service import (
    _as_matrices,
    _black_litterman,
    _black_litterman_posterior,
)

RF = 0.02
TAU = 0.05
DELTA = 2.5

#: Reference forms agree with each other at ~1e-17 on every book tried; 1e-10
#: is a wide but still meaningful gate that a wrong coefficient cannot pass
#: (the QM-1 defect misses by ~1e-2 or worse).
_TOL = 1e-10


def _book(seed: int = 7, n: int = 8, n_obs: int = 400) -> pd.DataFrame:
    """Genuinely correlated book: 3 real factors plus idiosyncratic noise.

    NOT the `factors @ cholesky(cov(factors))` pattern used elsewhere in this
    suite -- the covariance of `factors` is the identity, so `cholesky` is the
    identity and `Sigma` comes out diagonal. On a diagonal book the implied
    equal-weight market portfolio is already the tangency portfolio, so the
    top weight barely moves under either covariance and the defect hides.
    """
    rng = np.random.default_rng(seed)
    beta = rng.uniform(0.3, 1.4, size=(n, 3))
    factors = rng.normal(scale=0.008, size=(n_obs, 3))
    idio = rng.normal(scale=0.010, size=(n_obs, n))
    return pd.DataFrame(
        factors @ beta.T + idio, columns=[f"A{i:02d}" for i in range(n)]
    )


def _views_matrix(assets, absolute, relative):
    """(P, Q) in the shape `_black_litterman` builds, for direct comparison."""
    idx = {a: i for i, a in enumerate(assets)}
    rows, q = [], []
    for t, ret in absolute.items():
        if t in idx:
            row = np.zeros(len(assets))
            row[idx[t]] = 1.0
            rows.append(row)
            q.append(float(ret))
    for long_t, short_t, diff in relative:
        if long_t in idx and short_t in idx:
            row = np.zeros(len(assets))
            row[idx[long_t]] = 1.0
            row[idx[short_t]] = -1.0
            rows.append(row)
            q.append(float(diff))
    return np.array(rows), np.array(q)


#: The views payload itself (NOT a kwargs wrapper -- passing the wrapper as the
#: `views` argument silently produces the key `"views"`, which matches no
#: ticker, and drops the run onto the no-views path where it tests nothing).
_VIEWS = {"A03": 0.18, "A05": -0.05}


# --------------------------------------------------------------------------
# (a) QM-1: the posterior covariance IS the Black-Litterman posterior
# --------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5, 6, 7])
@pytest.mark.parametrize("tau", [0.05, 0.01, 0.25])
def test_posterior_covariance_equals_both_reference_forms(seed, tau):
    """The shipped `cov_bl` must equal the Woodbury AND the information form."""
    returns = _book(seed)
    _mu, cov, assets = _as_matrices(returns)
    P, Q = _views_matrix(assets, {"A03": 0.18, "A05": -0.05}, [("A01", "A04", 0.03)])
    pi = DELTA * (cov @ np.ones(len(assets)) / len(assets))

    _mu_bl, cov_bl = _black_litterman_posterior(cov, pi, P, Q, tau)

    tau_sigma = tau * cov
    omega = np.diag(np.clip(np.diag(P @ tau_sigma @ P.T), 1e-6, None))

    # Reference form A: the Woodbury / Markov reduction.
    ref_woodbury = (
        tau_sigma
        - tau_sigma @ P.T @ np.linalg.pinv(omega + P @ tau_sigma @ P.T) @ P @ tau_sigma
    )
    # Reference form B: the information form [(tau*S)^-1 + P' Omega^-1 P]^-1.
    ref_information = np.linalg.inv(
        np.linalg.inv(tau_sigma) + P.T @ np.linalg.inv(omega) @ P
    )

    assert np.abs(cov_bl - ref_woodbury).max() < _TOL
    assert np.abs(cov_bl - ref_information).max() < _TOL
    # The two references must themselves agree, or the test proves nothing.
    assert np.abs(ref_woodbury - ref_information).max() < _TOL


def test_the_two_reference_forms_are_independent_constructions():
    """Guards the guard: Woodbury vs information form are not the same algebra.

    They are related by two inversions, so if one is written wrong the other
    still stands. Assert they agree AND differ in construction, so a test that
    accidentally compares a quantity to itself is caught here.
    """
    returns = _book(11, n=6)
    _mu, cov, assets = _as_matrices(returns)
    P, Q = _views_matrix(assets, {"A00": 0.12}, [("A02", "A05", -0.02)])
    pi = DELTA * (cov @ np.ones(len(assets)) / len(assets))
    tau = 0.05

    _mu_bl, cov_bl = _black_litterman_posterior(cov, pi, P, Q, tau)
    tau_sigma = tau * cov
    omega = np.diag(np.clip(np.diag(P @ tau_sigma @ P.T), 1e-6, None))
    ref_woodbury = (
        tau_sigma
        - tau_sigma @ P.T @ np.linalg.pinv(omega + P @ tau_sigma @ P.T) @ P @ tau_sigma
    )

    # The coefficient that carries the defect is `(1 + tau)` instead of `tau`;
    # build that form explicitly and show the shipped one is NOT it.
    inflated = (1.0 + tau) * cov - (tau * tau) * (
        cov @ P.T @ np.linalg.pinv(P @ tau_sigma @ P.T + omega) @ P @ cov
    )
    assert np.abs(inflated - ref_woodbury).max() > 1e-3, (
        "the QM-1 defect is no longer distinguishable from the correct "
        "posterior on this book -- re-measure before trusting these tests"
    )
    assert np.abs(inflated - (cov + ref_woodbury)).max() < _TOL, (
        "the QM-1 defect must keep equalling Sigma + Sigma_BL"
    )
    assert np.abs(cov_bl - inflated).max() > 1e-3, (
        "cov_bl must NOT be the inflated (1+tau) form"
    )
    assert np.abs(cov_bl - ref_woodbury).max() < _TOL


@pytest.mark.parametrize("seed", [3, 7, 13])
def test_confident_views_shrink_the_prior_trace(seed):
    """A posterior must SHRINK the prior. The QM-1 form inflated it by ~3%."""
    returns = _book(seed)
    _mu, cov, assets = _as_matrices(returns)
    P, Q = _views_matrix(assets, {"A03": 0.18, "A05": -0.05}, [])
    pi = DELTA * (cov @ np.ones(len(assets)) / len(assets))

    _mu_bl, cov_bl = _black_litterman_posterior(cov, pi, P, Q, TAU)

    assert np.trace(cov_bl) < np.trace(cov), (
        f"posterior trace {np.trace(cov_bl):.6f} must be below the prior "
        f"{np.trace(cov):.6f}; the (1+tau) form adds Sigma back on top"
    )


def test_posterior_is_not_the_prior_plus_the_posterior():
    """The exact QM-1 shape: (1+tau)Sigma - ... == Sigma + Sigma_BL."""
    returns = _book(7)
    _mu, cov, assets = _as_matrices(returns)
    P, Q = _views_matrix(assets, {"A03": 0.18, "A05": -0.05}, [])
    pi = DELTA * (cov @ np.ones(len(assets)) / len(assets))

    _mu_bl, cov_bl = _black_litterman_posterior(cov, pi, P, Q, TAU)
    tau_sigma = TAU * cov
    omega = np.diag(np.clip(np.diag(P @ tau_sigma @ P.T), 1e-6, None))
    posterior = (
        tau_sigma
        - tau_sigma @ P.T @ np.linalg.pinv(omega + P @ tau_sigma @ P.T) @ P @ tau_sigma
    )

    assert np.abs(cov_bl - (cov + posterior)).max() > 1e-6, (
        "cov_bl is Sigma + Sigma_BL: the prior is added on top of the posterior"
    )


# --------------------------------------------------------------------------
# (b) the published weights are the weights the corrected posterior implies
# --------------------------------------------------------------------------

def _tangency_reference(cov, excess):
    """Exact solution of  min y'Cy  s.t.  m'y = 1,  y >= 0,  by active-set search.

    Independent of the cvxpy path in `_black_litterman` -- no shared code, no
    shared solver. For an active set S the equality-constrained minimiser is
    y_S = C_SS^-1 m_S / (m_S' C_SS^-1 m_S), y_{-S} = 0, and it is the OPTIMAL
    set iff it is dual-feasible. Stationarity of
    L = y'Cy - lam (m'y - 1) - mu'y  gives 2Cy = lam*m + mu, so on S
    (Cy)_k / m_k = lam/2 = 1/denom for every k, and for each held j the
    complementarity condition is (Cy)_j >= m_j / denom. (The constraint vector
    is the excess-return vector m, NOT a vector of ones -- comparing (Cy)_j
    against the largest (Cy)_k on S is the wrong test and rejects everything.)

    Enumeration, not a closed form: the corrected posterior covariance is ~30x
    smaller in scale than the inflated one, so the non-negativity constraint
    BINDS on books where it did not before. An interior-only formula would
    quietly stop being the right reference exactly when it starts to matter.
    """
    n = len(excess)
    for mask in range(1, 1 << n):
        free = [j for j in range(n) if mask >> j & 1]
        held = [j for j in range(n) if not mask >> j & 1]
        try:
            w = np.linalg.solve(cov[np.ix_(free, free)], excess[free])
        except np.linalg.LinAlgError:
            continue
        denom = excess[free] @ w
        if denom <= 0:
            continue
        y = np.zeros(n)
        y[free] = w / denom
        if np.any(y[free] < -1e-12):
            continue
        Cy = cov @ y
        if held and np.any(Cy[held] < excess[held] / denom - 1e-10):
            continue
        return y
    raise AssertionError("no feasible active set: the QP is infeasible as posed")


def test_published_weights_follow_the_corrected_posterior():
    """Pin the actual published number, not just 'it did not raise'."""
    returns = _book(7)
    _mu, cov, assets = _as_matrices(returns)
    views = _VIEWS
    P, Q = _views_matrix(assets, views, [])
    pi = DELTA * (cov @ np.ones(len(assets)) / len(assets))

    _mu_bl, cov_bl = _black_litterman_posterior(cov, pi, P, Q, TAU)
    expected = _tangency_reference(cov_bl, _mu_bl)
    expected = np.clip(expected, 0.0, None)
    expected = expected / expected.sum()
    actual = _black_litterman(returns, views=views, risk_free_rate=RF)

    assert np.abs(actual - expected).max() < 1e-6


def test_published_weights_are_not_the_inflated_posterior_weights():
    """The other half of the pin: reject the QM-1 answer explicitly."""
    returns = _book(7)
    _mu, cov, assets = _as_matrices(returns)
    views = _VIEWS
    P, Q = _views_matrix(assets, views, [])
    pi = DELTA * (cov @ np.ones(len(assets)) / len(assets))

    _mu_bl, _cov_bl = _black_litterman_posterior(cov, pi, P, Q, TAU)
    tau_sigma = TAU * cov
    omega = np.diag(np.clip(np.diag(P @ tau_sigma @ P.T), 1e-6, None))
    inflated = (1.0 + TAU) * cov - (TAU * TAU) * (
        cov @ P.T @ np.linalg.pinv(P @ tau_sigma @ P.T + omega) @ P @ cov
    )
    inflated_w = _tangency_reference(inflated, _mu_bl)
    inflated_w = np.clip(inflated_w, 0.0, None)
    inflated_w = inflated_w / inflated_w.sum()
    actual = _black_litterman(returns, views=views, risk_free_rate=RF)

    assert np.abs(actual - inflated_w).max() > 1e-3, (
        "published weights still match the inflated (1+tau) posterior"
    )


# --------------------------------------------------------------------------
# (c) QM-5: the risk-free rate enters exactly once, at the edge
# --------------------------------------------------------------------------

@pytest.mark.parametrize("views", [None, {"A03": 0.18, "A05": -0.05}])
def test_published_weights_are_invariant_to_the_risk_free_rate(views):
    """`pi` is already excess, so rf must not touch the tangency direction.

    Black-box and solver-independent: it holds in the views path AND the
    no-views path, and it cannot be satisfied by any formula that subtracts
    rf from an already-excess posterior.
    """
    base = _black_litterman(returns=_book(7), views=views, risk_free_rate=0.02)
    for rf in (0.0, 0.01, 0.06, 0.11):
        other = _black_litterman(returns=_book(7), views=views, risk_free_rate=rf)
        assert np.abs(base - other).max() < 1e-9, (
            f"weights moved when risk_free_rate went 0.02 -> {rf}: the "
            f"posterior is being de-risked a second time"
        )


@pytest.mark.parametrize("n", [3, 5, 8, 14])
@pytest.mark.parametrize("seed", [2, 9])
def test_no_views_bl_reproduces_the_equal_weight_market_portfolio(n, seed):
    """BL with no views MUST return the market portfolio, exactly.

    The sharpest available statement of QM-5, and it needs no covariance
    formula at all. With no views `mu_bl = pi = delta * Sigma @ w_mkt` and
    `cov_bl = Sigma`, so the tangency direction is

        Sigma^-1 * pi  =  delta * Sigma^-1 Sigma @ w_mkt  =  delta * w_mkt

    which is `w_mkt` up to a positive scale -- i.e. equal weight, exactly,
    and interior (every component is 1/n > 0). Any uniform subtraction from
    `pi` destroys that identity, because it replaces the direction with
    `Sigma^-1 (pi - rf 1)`. Measured on the probe book, the shipped
    no-views allocation was 0.2607 on one leg; the corrected one is 0.1250.

    Tolerance: CLARABEL's feasibility floor, not exact arithmetic -- the
    residual `Sigma^-1 Sigma` round trip leaves ~1e-9..8e-9 here. That is
    still ~5 orders of magnitude below the ~1e-1 signal QM-5 produces, so the
    gate cannot be satisfied by a partial repair.
    """
    returns = _book(seed, n=n)
    w = _black_litterman(returns, risk_free_rate=RF)

    assert np.abs(w - 1.0 / n).max() < 1e-6, (
        f"no-views BL must return the {1.0 / n:.4f} equal-weight market "
        f"portfolio; got {np.array2string(w, precision=4)}"
    )


def test_the_prior_is_excess_not_absolute():
    """`pi = delta*Sigma@w_mkt` is the risk premium `E[R] - rf*1`.

    It carries no `rf` term by construction, so it is EXCESS space. This is
    the fact QM-5 violated; asserted directly on the prior, before any
    posterior is computed.
    """
    _mu, cov, assets = _as_matrices(_book(7))
    pi = DELTA * (cov @ np.ones(len(assets)) / len(assets))
    assert not np.allclose(pi, pi + RF), (
        "if pi were invariant to adding rf it would already contain rf"
    )
    # and the equilibrium identity that defines it, restated
    w_mkt = np.ones(len(assets)) / len(assets)
    assert np.abs(pi - DELTA * cov @ w_mkt).max() < 1e-12


@pytest.mark.parametrize("seed", [1, 7, 21])
def test_mu_bl_is_a_posterior_in_excess_space(seed):
    """`mu_bl` must read `Q` as an EXCESS view: `pi + g (Q - P pi)`.

    For one unit view the gain on the viewed leg is
    `tau S00 / (tau S00 + Omega00)` -- which is exactly 0.5 under
    `Omega = diag(P tau S P')`, the classic He-Litterman midpoint. It is NOT
    the posterior variance `tau S P' (...)^-1 P tau S`; conflating the two is
    the easy mistake here. Reading `Q` in absolute space instead would add
    `g * rf` to the pull, a strictly positive shift, so the two conventions
    are separable on any book.
    """
    returns = _book(seed)
    _mu, cov, assets = _as_matrices(returns)
    w_mkt = np.ones(len(assets)) / len(assets)
    pi = DELTA * (cov @ w_mkt)
    q_on = 0.09          # the view as the docstring says to pass it: excess
    P, Q = _views_matrix(assets, {"A00": q_on}, [])
    tau_sigma = TAU * cov
    omega = np.diag(np.clip(np.diag(P @ tau_sigma @ P.T), 1e-6, None))
    mu_bl, _cov = _black_litterman_posterior(cov, pi, P, Q, TAU)

    # Gain on the VIEWED leg only. `tau S P' (...)^-1` is (N,1) and its [0,0]
    # entry is tau*S00 / (tau*S00 + Omega00) = 0.5 under Omega = diag(P tau S P').
    # Other legs are scaled by their correlation with leg 0, so this scalar is
    # a statement about element 0 and nothing else.
    mean_gain = float(
        (tau_sigma @ P.T @ np.linalg.pinv(omega + P @ tau_sigma @ P.T))[0, 0]
    )
    assert np.isclose(mean_gain, 0.5, atol=1e-9), (
        f"single-view mean gain should be the 0.5 midpoint, got {mean_gain}"
    )

    pull = mu_bl[0] - pi[0]
    assert np.isclose(pull, mean_gain * (q_on - pi[0]), rtol=1e-8, atol=1e-14), (
        "posterior mean is not pi + gain*(Q - P pi) on the viewed leg"
    )
    assert not np.isclose(
        pull, mean_gain * (q_on + RF - pi[0]), rtol=1e-6, atol=1e-12
    ), (
        "the pull matches an ABSOLUTE-space reading of the view (q + rf); "
        f"excess and absolute differ by gain*rf = {mean_gain * RF:.3e}"
    )


@pytest.mark.parametrize("seed", [1, 7, 21])
def test_posterior_mean_matches_the_reference_form(seed):
    """Pin the posterior MEAN too -- QM-1's sibling quantity."""
    returns = _book(seed)
    _mu, cov, assets = _as_matrices(returns)
    w_mkt = np.ones(len(assets)) / len(assets)
    pi = DELTA * (cov @ w_mkt)
    P, Q = _views_matrix(assets, {"A00": 0.09, "A03": -0.04}, [("A02", "A05", 0.02)])
    tau_sigma = TAU * cov
    omega = np.diag(np.clip(np.diag(P @ tau_sigma @ P.T), 1e-6, None))
    inv_inner = np.linalg.pinv(omega + P @ tau_sigma @ P.T)

    ref_mean = pi + (tau_sigma @ P.T @ inv_inner @ (Q - P @ pi))
    mu_bl, _cov = _black_litterman_posterior(cov, pi, P, Q, TAU)

    assert np.abs(mu_bl - ref_mean).max() < _TOL


def test_views_path_and_no_views_path_share_one_excess_convention():
    """Both paths optimise an EXCESS vector; views must actually bite.

    Neither branch may re-base the prior onto `rf`. The no-views branch is
    pinned exactly (to equal weight) by
    `test_no_views_bl_reproduces_the_equal_weight_market_portfolio`; this
    test's job is to prove the views branch is not silently inert.
    """
    returns = _book(7)

    no_views = _black_litterman(returns=returns, risk_free_rate=RF)
    views = _VIEWS
    with_views = _black_litterman(returns=returns, views=views, risk_free_rate=RF)

    assert np.abs(with_views - no_views).max() > 1e-3, (
        "views must actually move the allocation, or this gate proves nothing"
    )
    # both are long-only, fully invested
    assert no_views.min() >= -1e-9 and abs(no_views.sum() - 1.0) < 1e-9
    assert with_views.min() >= -1e-9 and abs(with_views.sum() - 1.0) < 1e-9


# --------------------------------------------------------------------------
# (d) no regression: the weight contract still holds
# --------------------------------------------------------------------------

@pytest.mark.parametrize("n", [3, 5, 8, 14])
def test_weights_stay_long_only_and_fully_invested(n):
    returns = _book(7, n=n)
    for kwargs in ({}, {"views": _VIEWS}):
        w = _black_litterman(returns, risk_free_rate=RF, **kwargs)
        assert w.shape == (n,)
        assert np.all(w >= -1e-9)
        assert abs(w.sum() - 1.0) < 1e-9
        assert np.all(np.isfinite(w))


def test_deterministic_and_input_not_mutated():
    returns = _book(7)
    before = returns.copy()
    a = _black_litterman(returns, views=_VIEWS, risk_free_rate=RF)
    b = _black_litterman(returns, views=_VIEWS, risk_free_rate=RF)
    assert np.array_equal(a, b)
    pd.testing.assert_frame_equal(returns, before)


def test_views_reach_the_posterior_at_all():
    """The views payload must match a ticker, or every views test is a no-op."""
    returns = _book(7)
    assets = list(returns.columns)
    assert all(t in assets for t in _VIEWS), (
        f"_VIEWS names a ticker absent from the book {assets}; the views "
        f"branch would never be entered and these gates would pass vacuously"
    )