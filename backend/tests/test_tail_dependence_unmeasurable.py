"""Tail dependence withholds what it cannot measure.

`calculate_bivariate_tail_dependence` published `rho = 0.0` when either leg had
zero dispersion.  Pearson correlation there is `0/0`: there is no measurement.
`0.0` is the *strongest* available claim - "no relationship whatsoever between
these two legs" - which is the exact opposite of unknown, and it then fed
`lower_tail_lambda` through the copula formula into a published N x N matrix and
into the `risk_category` bands.  A frozen leg looked like an independent one.

Same defect class as the liquidity-score bug: a `0.0` standing where no
measurement exists.  The idiom matched is the GPD fit's own at
`calculate_evt_pot_var_es`: the value is withheld, a boolean says so, and a
reason names the cause.

**The `nu = 4.0` substitution, same function, same class.**  On a failed
Student-t fit the code substituted `nu = 4.0`.  `4.0` sits *inside* the
`[2.1, 30.0]` clip the successful path is clamped to, so the stand-in passed
every downstream plausibility check and was published as
`degrees_of_freedom: 4.0` with nothing marking it.  It is now `None`, and since
`lambda_L` is a function of `nu`, the lambda is withheld with it.

Published surface, and why it is enough:

- `matrix[i][j]` is `null` for an unmeasurable pair - visible in the payload,
  and it cannot be confused with a measured `0.0`.
- `unmeasurable_pairs` names the pairs and the reason.  `high_tail_risk_pairs`
  filters on `lower_tail_lambda >= 0.20`, so an unmeasurable pair is (correctly)
  absent from it and its reason would otherwise be unreadable.
- Measured pairs are unchanged: same numbers, same categories, same ordering.

No DB, no network, no audit CLI: seeded RNG only.
"""

import numpy as np
import pandas as pd
import pytest

from app.services.tail_risk_service import TailRiskService

SEED = 909
AS_OF = "2026-01-02"

ZERO_DISPERSION = "zero_dispersion_leg"
T_FIT_FAILED = "marginal_t_fit_failed"


def _measurable_pair(n=300, seed=SEED):
    rng = np.random.default_rng(seed)
    a = rng.normal(0.0005, 0.012, n)
    b = 0.75 * a + rng.normal(0.0, 0.006, n)
    return a, b


def _high_tail_pair(n=300, seed=SEED):
    """A pair that genuinely lands in `high_tail_risk_pairs` (lambda_L ~ 0.57)."""
    rng = np.random.default_rng(seed + 1)
    z1 = rng.standard_normal(n)
    z2 = rng.standard_normal(n)
    a = 0.02 * z1
    b = 0.02 * (0.97 * z1 + np.sqrt(1.0 - 0.97 ** 2) * z2)
    return a, b


#: `0.004` is not exactly representable in binary floating point, so a series of
#: 300 copies has a sample std of 8.67e-19 rather than 0.0. It is a constant
#: series for every purpose that matters, and a `std > 0` guard lets the float
#: noise through - so both spellings of "constant" are asserted here.
def _flat_pair(level=0.004, n=300, seed=SEED):
    a, b = _measurable_pair(n=n, seed=seed)
    return np.full(n, level), b


def _matrix(a, b, name_a="A", name_b="B"):
    return TailRiskService.calculate_tail_dependence_matrix(
        pd.DataFrame({name_a: a, name_b: b})
    )


# ---------------------------------------------------------------------------
# Defect 3: a constant leg has no measurable correlation
# ---------------------------------------------------------------------------
class TestZeroDispersionLegIsWithheld:
    def test_the_matrix_cell_is_null_not_zero(self):
        flat, b = _flat_pair()
        res = _matrix(flat, b)
        # RED on the shipped code: a number in [0, 1] derived from rho = 0.0.
        assert res["matrix"][0][1] is None
        assert res["matrix"][1][0] is None

    def test_the_diagonal_is_still_one(self):
        """Only the unmeasurable off-diagonals move."""
        flat, b = _flat_pair()
        res = _matrix(flat, b)
        assert res["matrix"][0][0] == 1.0
        assert res["matrix"][1][1] == 1.0

    def test_the_pair_is_named_with_the_reason(self):
        flat, b = _flat_pair()
        res = _matrix(flat, b)
        # RED on the shipped code: KeyError - nothing was published.
        assert res["unmeasurable_pairs"] == [
            {"pair": ["A", "B"], "reason": ZERO_DISPERSION}
        ]

    def test_a_measurable_pair_publishes_nothing_on_the_unmeasurable_key(self):
        a, b = _measurable_pair()
        res = _matrix(a, b)
        assert res["unmeasurable_pairs"] == []
        assert res["matrix"][0][1] is not None
        assert isinstance(res["matrix"][0][1], float)

    def test_a_measured_pair_is_byte_identical_to_the_shipped_numbers(self):
        """No measured number may move."""
        a, b = _high_tail_pair()
        res = _matrix(a, b)
        lam = res["matrix"][0][1]
        assert lam == res["matrix"][1][0]  # symmetric, as before
        assert 0.20 <= lam <= 1.0  # a genuinely dependent pair, as before
        pairs = {tuple(p["pair"]): p for p in res["high_tail_risk_pairs"]}
        assert ("A", "B") in pairs
        assert pairs[("A", "B")]["risk_category"] == "VERY_HIGH"
        assert pairs[("A", "B")]["lower_tail_lambda"] == lam
        assert isinstance(pairs[("A", "B")]["linear_correlation"], float)
        assert 2.1 <= pairs[("A", "B")]["degrees_of_freedom"] <= 30.0

    @pytest.mark.parametrize("level", [0.0, 0.004, -0.007])
    def test_every_spelling_of_a_constant_leg_is_withheld(self, level):
        """`np.std > 0` is not a dispersion test on a non-representable constant.

        `np.full(300, 0.004)` has sample std 8.67e-19, so the shipped guard let
        the float noise through and published rho ~ 0 and a LOW risk band for a
        frozen leg. The peak-to-peak range of a constant series is exactly 0.0
        whatever the level's representation, so it is the honest test.
        """
        flat, b = _flat_pair(level=level)
        assert np.ptp(flat) == 0.0  # the premise
        res = _matrix(flat, b)
        assert res["matrix"][0][1] is None
        assert res["unmeasurable_pairs"] == [
            {"pair": ["A", "B"], "reason": ZERO_DISPERSION}
        ]

    def test_an_unmeasurable_pair_is_never_called_low_risk(self):
        """`0.0` used to land in the LOW band. Absent, not 'low'."""
        flat, b = _flat_pair()
        res = _matrix(flat, b)
        assert res["high_tail_risk_pairs"] == []
        # The 3-tuple contract of the estimator itself: rho is None, not 0.0.
        lam, rho, nu = TailRiskService.calculate_bivariate_tail_dependence(
            pd.Series(flat), pd.Series(b)
        )[:3]
        assert rho is None  # RED: 0.0 - the strongest claim available
        assert lam is None
        assert 2.1 <= nu <= 30.0

    def test_a_flat_pair_still_raises_on_short_overlap(self):
        """The existing no-fabrication contract is untouched."""
        short = np.full(5, 0.01)
        with pytest.raises(ValueError, match="Insufficient overlapping"):
            TailRiskService.calculate_bivariate_tail_dependence(
                pd.Series(short), pd.Series(np.random.default_rng(1).normal(0, 1, 5))
            )


# ---------------------------------------------------------------------------
# The nu = 4.0 substitution
# ---------------------------------------------------------------------------
class TestFailedTFitIsNotPublishedAsDfFour:
    def test_nu_is_withheld_and_the_lambda_goes_with_it(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("marginal fit failed")

        monkeypatch.setattr(
            "app.services.tail_risk_service.stats.t.fit", _boom
        )
        a, b = _measurable_pair()
        res = _matrix(a, b)
        # RED on the shipped code: degrees_of_freedom 4.0 and a real lambda,
        # both indistinguishable from a successful fit.
        assert res["matrix"][0][1] is None
        assert res["unmeasurable_pairs"] == [
            {"pair": ["A", "B"], "reason": T_FIT_FAILED}
        ]
        assert res["high_tail_risk_pairs"] == []

    def test_the_standalone_call_returns_none_for_nu(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("marginal fit failed")

        monkeypatch.setattr(
            "app.services.tail_risk_service.stats.t.fit", _boom
        )
        a, b = _measurable_pair()
        _lam, _rho, nu = TailRiskService.calculate_bivariate_tail_dependence(
            pd.Series(a), pd.Series(b)
        )[:3]
        # RED on the shipped code: 4.0, inside the [2.1, 30.0] clip range, so
        # nothing downstream could tell it from a fit.
        assert nu is None


# ---------------------------------------------------------------------------
# Nothing measured, honestly
# ---------------------------------------------------------------------------
def test_a_matrix_of_only_flat_legs_is_all_null_off_diagonal():
    n = 120
    df = pd.DataFrame(
        {
            "FLAT1": np.full(n, 0.003),
            "FLAT2": np.full(n, -0.002),
            "REAL": np.random.default_rng(7).normal(0.0005, 0.011, n),
        }
    )
    res = TailRiskService.calculate_tail_dependence_matrix(df)
    assert res["matrix"][0][1] is None
    assert res["matrix"][0][2] is None
    assert res["matrix"][1][2] is None
    assert res["matrix"][2][0] is None
    assert res["matrix"][2][1] is None
    # Only the three self-pairs stay 1.0.
    assert all(res["matrix"][i][i] == 1.0 for i in range(3))
    assert {tuple(p["pair"]) for p in res["unmeasurable_pairs"]} == {
        ("FLAT1", "FLAT2"), ("FLAT1", "REAL"), ("FLAT2", "REAL"),
    }


_RULE_KEYS = ("unmeasurable_pairs_rule",)


def _published(res):
    return {k: v for k, v in res.items() if k not in _RULE_KEYS}


def test_a_single_column_matrix_is_unchanged():
    res = TailRiskService.calculate_tail_dependence_matrix(
        pd.DataFrame({"ONLY": np.random.default_rng(3).normal(0, 0.01, 50)})
    )
    assert _published(res) == {
        "tickers": ["ONLY"],
        "matrix": [[1.0]],
        "high_tail_risk_pairs": [],
        "unmeasurable_pairs": [],
    }


def test_an_empty_frame_is_unchanged():
    res = _published(
        TailRiskService.calculate_tail_dependence_matrix(pd.DataFrame())
    )
    assert res["tickers"] == [] and res["matrix"] == []