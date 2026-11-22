"""T8: the published `expected_sharpe` claim must be true, and `min_cvar` must
not promise a beta the API cannot send.

The defect
----------
`optimization_service` published

    objective.expected_sharpe_was_the_optimised_objective = True
    strategy                                        = "black_litterman"

while the number sitting next to it was not the objective that was maximised.
`_black_litterman_solved` maximises the POSTERIOR Sharpe
`(mu_bl @ w) / sqrt(w @ cov_bl @ w)`, on the Black-Litterman posterior mean and
covariance. `optimize()` never rebinds `mu`/`cov` to that posterior - they come
from `_as_matrices(returns)`, the SAMPLE moments - so the published
`expected_sharpe` is the sample Sharpe `(mu_annual @ w - rf) / sqrt(w @ cov_annual @ w)`.
Two different functions of the same weights, on a record that said they were
one.

This is not a rounding gap. Measured on the books below, the two figures sit
2.5-5.5 Sharpe units apart and DISAGREE IN SIGN: seed 0 publishes -1.8306 as
`expected_sharpe` on a record claiming that number was the maximised objective,
where the maximised objective was +3.6074.

Why the numbers are not changed here
------------------------------------
Making the published `expected_sharpe` the posterior Sharpe would mean
publishing a return of +0.28 and a volatility of 0.071 next to the 0.560 /
0.326 the same book scores today, and dropping the SI-5 bootstrap
(`optimizer_estimate_uncertainty` refits `mu`/`cov` from the sample rows, so it
could no longer reproduce its own published point and every field would go to
`not_computed`), and silently making `black_litterman` the only strategy whose
moments are not comparable with `current_portfolio`'s. That is a modelling
change to a published record, not a correction of a false claim, and it belongs
in its own reviewed change. This file removes the false claim and records what
the objective actually was.

The invariant this file proves
------------------------------
1. No record publishes `expected_sharpe_was_the_optimised_objective: True`
   unless the published number IS the maximised objective - checked against an
   independent re-derivation of the objective, not against the module's own
   claim about itself.
2. For `black_litterman` the two figures are provably different, so the claim
   cannot be reinstated by accident.
3. `min_cvar` names the level it actually solved at, and does not describe a
   level as "requested" - `OptimizeRequest` has no beta field, so no API caller
   can request one.

Pure tests: no DB, no network, seeded RNG only.
"""

import numpy as np
import pandas as pd
import pytest

from app.services.optimization_service import (
    EXPECTED_SHARPE_SCORED_ON_BL_POSTERIOR,
    EXPECTED_SHARPE_SCORED_ON_SAMPLE,
    SHARPE_OBJECTIVE_STRATEGIES,
    _as_matrices,
    _black_litterman_posterior,
    optimize,
)

RF = 0.02
TAU = 0.05
DELTA = 2.5

#: `moments_basis` publishes moments at 4 decimals and weights at 6, so a
#: reader recomputing from the PUBLISHED pair lands within one display step of
#: the internal value. Anything larger than that is a different quantity, not
#: rounding - and the sample-vs-posterior gap measured here is 2.5-5.5.
_DISPLAY_STEP = 1e-4
_WEIGHT_ROUNDING_STEP = 5e-7


def _book(seed: int, n: int = 14, n_obs: int = 170) -> pd.DataFrame:
    """Factor-correlated 14-asset daily return frame; the PA-1 fixture."""
    rng = np.random.default_rng(seed)
    factors = rng.normal(size=(n_obs, n))
    loadings = np.linalg.cholesky(np.cov(factors, rowvar=False))
    vols = rng.uniform(0.10, 0.42, n)
    return pd.DataFrame(
        factors @ loadings * vols / np.sqrt(n),
        columns=[f"A{i:02d}" for i in range(n)],
    )


_VIEWS = {"A03": 0.18, "A05": -0.05}


def _posterior_sharpe(rets: pd.DataFrame, w: np.ndarray, views) -> float:
    """`(mu_bl @ w) / sqrt(w @ cov_bl @ w)` - the quantity BL actually maximised.

    Rebuilt from `returns`, the view payload and the module's own posterior
    helper, independently of `optimize()`'s moment triple. `mu_bl` is in
    EXCESS-return space (QM-5: `pi` is the risk premium and carries no `rf`), so
    no `rf` is subtracted here - the same convention `_black_litterman_solved`
    uses, and the reason the two conventions are separable rather than equal.
    """
    mu, cov, assets = _as_matrices(rets)
    n = len(assets)
    idx = {a: i for i, a in enumerate(assets)}
    pi = DELTA * (cov @ (np.ones(n) / n))
    rows, qs = [], []
    for ticker, value in views.items():
        row = np.zeros(n)
        row[idx[ticker]] = 1.0
        rows.append(row)
        qs.append(float(value))
    mu_bl, cov_bl = _black_litterman_posterior(cov, pi, np.array(rows), np.array(qs), TAU)
    return float(mu_bl @ w) / float(np.sqrt(w @ cov_bl @ w))


def _sample_sharpe(rets: pd.DataFrame, w: np.ndarray) -> float:
    """What `moments_basis` says `expected_sharpe` is."""
    mu, cov, _assets = _as_matrices(rets)
    return (float(mu @ w) - RF) / float(np.sqrt(w @ cov @ w))


def _weights(result, rets: pd.DataFrame) -> np.ndarray:
    return np.array(
        [result["weights"][a] for a in rets.columns], dtype=float
    )


# --------------------------------------------------------------------------
# (a) no record claims a Sharpe it did not maximise
# --------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_black_litterman_no_longer_claims_the_sharpe_it_did_not_maximise(seed):
    """RED against the pre-change module: it published `True`.

    The assertion is on the CLAIM, and it is only reached if the fixture is one
    where the claim would have been false - proved in the next two tests. A
    fixture where the two figures happened to agree would let this pass while
    the false claim stood, which is why the separation is pinned separately
    rather than assumed.
    """
    result = optimize(_book(seed), "black_litterman", risk_free_rate=RF, views=_VIEWS)
    assert result["objective"]["expected_sharpe_was_the_optimised_objective"] is False
    assert "black_litterman" not in SHARPE_OBJECTIVE_STRATEGIES
    assert "max_sharpe" in SHARPE_OBJECTIVE_STRATEGIES, (
        "max_sharpe's claim IS true - it maximises the published moment "
        "triple's own Sharpe - so removing it would be the next false claim"
    )


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_the_two_bl_sharpes_are_different_functions_of_the_same_weights(seed):
    """The fixture separator. Without this, test (a) proves nothing.

    Re-derives both scorings independently and shows the published number is
    the sample one and is NOT the maximised objective. The gap is asserted well
    above the display step, and the SIGN disagreement is asserted on seed 0
    specifically because a gap alone could still be a units difference.
    """
    rets = _book(seed)
    result = optimize(rets, "black_litterman", risk_free_rate=RF, views=_VIEWS)
    w = _weights(result, rets)

    published = result["expected_sharpe"]
    sample = _sample_sharpe(rets, w)
    posterior = _posterior_sharpe(rets, w, _VIEWS)
    budget = _DISPLAY_STEP + _WEIGHT_ROUNDING_STEP * len(rets.columns)

    assert abs(published - sample) <= budget, (
        "expected_sharpe must remain the SAMPLE-moment Sharpe that "
        "moments_basis documents; if this moved, the payload's own formula "
        f"block is wrong. published={published} sample={sample}"
    )
    assert abs(published - posterior) > 1.0, (
        "the maximised objective and the published Sharpe now agree to within "
        f"{abs(published - posterior):.4f} on this book - if that is a real "
        "change rather than a broken fixture, the claim could be reinstated "
        "and this test must be re-measured, not relaxed"
    )
    if seed == 0:
        assert published < 0.0 < posterior, (
            f"seed 0 must show the sign disagreement: published {published}, "
            f"maximised {posterior}"
        )


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_the_published_bl_sharpe_matches_the_sample_recomputation(seed):
    """Ties the claim to the number: the record says "not the objective" AND
    publishes the sample Sharpe. A fix that flipped the claim to True without
    rebinding mu/cov would fail the previous test, not this one - so this is the
    anchor that says which number is on the wire."""
    rets = _book(seed)
    result = optimize(rets, "black_litterman", risk_free_rate=RF, views=_VIEWS)
    w = _weights(result, rets)
    assert result["expected_sharpe"] == pytest.approx(
        _sample_sharpe(rets, w),
        abs=_DISPLAY_STEP + _WEIGHT_ROUNDING_STEP * len(rets.columns),
    )


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_max_sharpe_still_genuinely_maximises_the_published_sharpe(seed):
    """The inverse guard: a false claim and a deleted true one are the same
    defect. `max_sharpe` solves on the sample mu/cov, and `_moments` scores on
    the sample mu/cov, so its `True` is accurate and must survive."""
    rets = _book(seed)
    result = optimize(rets, "max_sharpe", risk_free_rate=RF)
    w = _weights(result, rets)

    assert result["objective"]["expected_sharpe_was_the_optimised_objective"] is True
    assert result["expected_sharpe"] == pytest.approx(
        _sample_sharpe(rets, w), abs=1e-3
    ), (
        "max_sharpe claims its published Sharpe IS the objective; if the "
        "objective moved off the published mu/cov, that claim is false too"
    )


def test_the_objective_block_names_what_the_sharpe_was_scored_on():
    """Machine-readable, not just prose. A reader cannot recover the basis of a
    number from a sentence that says 'see moments_basis'."""
    for strategy in ("hrp", "min_vol", "max_sharpe", "min_cvar"):
        block = optimize(_book(0), strategy, risk_free_rate=RF)["objective"]
        assert block["expected_sharpe_scored_on"] == EXPECTED_SHARPE_SCORED_ON_SAMPLE
    bl = optimize(_book(0), "black_litterman", risk_free_rate=RF, views=_VIEWS)[
        "objective"
    ]
    assert bl["expected_sharpe_scored_on"] == EXPECTED_SHARPE_SCORED_ON_BL_POSTERIOR
    assert bl["expected_sharpe_scored_on"] != EXPECTED_SHARPE_SCORED_ON_SAMPLE


def test_the_bl_basis_names_the_objective_it_actually_ran():
    """The record must say what WAS maximised, not merely deny the claim.

    A bare `False` leaves the reader unable to tell whether the objective was
    undisclosed or simply different.
    """
    basis = optimize(_book(0), "black_litterman", risk_free_rate=RF, views=_VIEWS)[
        "objective"
    ]["expected_sharpe_basis"]

    assert "black_litterman optimises" in basis
    assert "NOT the number published as expected_sharpe" in basis
    assert "mu_bl @ w" in basis and "cov_bl @ w" in basis, (
        "the basis must name the posterior objective's actual formula"
    )
    assert "SAMPLE-moment" in basis
    assert "DESCRIPTIVE" in basis
    assert "not the quantity that was maximised" in basis
    assert "solution_path" in basis, (
        "on a min_vol_fallback_* path the objective that ran was not a Sharpe "
        "at all; the basis must send the reader to the path that says which"
    )


def test_every_strategy_publishes_the_two_objective_keys():
    """Shape, on every record: a consumer must never infer either fact from an
    absent key."""
    for strategy in ("hrp", "min_vol", "max_sharpe", "min_cvar", "black_litterman"):
        block = optimize(_book(0), strategy, risk_free_rate=RF)["objective"]
        assert "expected_sharpe_scored_on" in block
        assert "cvar_beta" in block


# --------------------------------------------------------------------------
# (b) min_cvar does not promise a beta no caller can send
# --------------------------------------------------------------------------

def test_min_cvar_no_longer_describes_its_level_as_requested():
    """RED against the pre-change module: it read "at the requested beta".

    `OptimizeRequest` (`app/api/analytics.py:135-172`) carries `strategy`,
    `risk_free_rate`, `tickers`, `views` and `relative_views` and no beta, so
    "requested" is a parameter the API does not accept - a reader would believe
    a level they chose drove the result.
    """
    objective = optimize(_book(0), "min_cvar", risk_free_rate=RF)["objective"]
    assert "requested beta" not in objective["what_was_optimised"]
    assert "cvar_beta" in objective["what_was_optimised"], (
        "the objective must point at the published level rather than name a "
        "bare 'requested' one"
    )


def test_min_cvar_publishes_the_level_it_actually_solved_at():
    """The number, not a string about the number. Defaults to 0.95 on every
    API request because no caller passes one."""
    assert optimize(_book(0), "min_cvar", risk_free_rate=RF)["objective"][
        "cvar_beta"
    ] == pytest.approx(0.95)


def test_min_cvar_publishes_a_level_the_caller_actually_chose():
    """`optimize(beta=...)` is a real argument, so a hardcoded level in the
    objective string would be its own false claim. Pin that the published value
    TRACKS the argument rather than repeating the default."""
    assert optimize(_book(0), "min_cvar", risk_free_rate=RF, beta=0.90)["objective"][
        "cvar_beta"
    ] == pytest.approx(0.90)


@pytest.mark.parametrize("strategy", ["hrp", "min_vol", "max_sharpe", "black_litterman"])
def test_cvar_beta_is_null_for_every_strategy_that_has_no_cvar_level(strategy):
    """`None` means 'this objective has no such level', not 'unset'."""
    assert optimize(_book(0), strategy, risk_free_rate=RF)["objective"]["cvar_beta"] is None


def test_the_min_cvar_basis_says_the_level_is_not_requested():
    basis = optimize(_book(0), "min_cvar", risk_free_rate=RF, beta=0.90)["objective"][
        "expected_sharpe_basis"
    ]
    assert "CHOSEN by this service, not REQUESTED by the caller" in basis
    assert "cvar_beta = 0.9" in basis, (
        "the level this run solved at must appear in the basis, so the prose "
        "cannot drift from the published number"
    )
    assert "no beta" in basis, (
        "the reason the level is not requestable must be published: "
        "OptimizeRequest carries no beta field"
    )
    assert "not the quantity that was maximised" in basis, (
        "min_cvar minimises a tail risk; the basis must still tell a reader the "
        "published Sharpe is descriptive and that a HIGHER one is not better"
    )
