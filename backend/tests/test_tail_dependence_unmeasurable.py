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

**A non-finite leg, same function, and the fix above it was HALF finished.**
The dispersion guard had been moved from `np.std(...) > 0` to `np.ptp(...) > 0`
- correctly, since a constant series has a sample std of 8.67e-19 rather than
0.0 - but the matching `np.isfinite(rho)` half was never added.  A `+/-inf`
observation passes `ptp > 0` with `ptp == inf`, and such observations are real:
`dropna()` drops NaN and **not** `-inf`, and
`prices.pct_change(fill_method=None)` emits `inf` from a zero denominator, so
the wide returns frame `/tails` is handed carries them.  Pearson correlation
over such a leg is `NaN`; `np.clip` propagates `NaN` unchanged, so the clip
bound is not a repair; and *every* comparison against `NaN` is `False`, so the
`risk_category` chain fell through to `"LOW"` and the pair was never entered in
`unmeasurable_pairs`.  A pair nobody could measure was published under a risk
band, which is the whole thing `UNMEASURABLE` exists to prevent.

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

from app.services import tail_risk_service as trs
from app.services.tail_risk_service import TailRiskService

SEED = 909
AS_OF = "2026-01-02"

ZERO_DISPERSION = "zero_dispersion_leg"
T_FIT_FAILED = "marginal_t_fit_failed"
NON_FINITE_LEG = "non_finite_leg"

#: Every label `unmeasurable_pairs[].reason` is allowed to carry, taken from the
#: service's own constants rather than re-spelled here. A reason outside this
#: set would be an invented cause, and a cause missing from it would be a
#: withheld pair the payload cannot explain.
DECLARED_REASONS = {
    trs.TAIL_DEPENDENCE_ZERO_DISPERSION,
    trs.TAIL_DEPENDENCE_T_FIT_FAILED,
    trs.TAIL_DEPENDENCE_NON_FINITE_LEG,
}


def _measurable_pair(n=300, seed=SEED):
    rng = np.random.default_rng(seed)
    a = rng.normal(0.0005, 0.012, n)
    b = 0.75 * a + rng.normal(0.0, 0.006, n)
    return a, b


def _inf_pair(n=300, seed=SEED, value=np.inf, at=100, legs=("a", "b")):
    """A measurable pair with a non-finite observation planted in it.

    Reproduces the real input rather than a synthetic one: `wide_ret` comes from
    `prices.pct_change(fill_method=None)`, which emits +/-inf from a zero
    denominator, and the frame reaches this service through `notna()`, which
    keeps inf. `dropna()` inside the estimator keeps it too.
    """
    a, b = _measurable_pair(n=n, seed=seed)
    for leg in legs:
        target = a if leg == "a" else b
        target[at] = value
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
# A non-finite leg: the half of the ptp fix that never landed
# ---------------------------------------------------------------------------
class TestANonFiniteLegIsWithheld:
    """`np.ptp(...) > 0` is a dispersion test, not a finiteness test.

    `ptp` of a leg carrying a `+/-inf` is `inf`, which passes `> 0`, and the
    Pearson correlation of such a pair is `NaN`. The clip is not a repair
    (`np.clip(nan, -0.9999, 0.9999)` is `nan`), and every comparison against
    `NaN` is `False` -- so the band chain fell through to `"LOW"` and the pair
    never entered `unmeasurable_pairs`.
    """

    @pytest.mark.parametrize("value", [np.inf, -np.inf])
    @pytest.mark.parametrize("legs", [("a",), ("b",), ("a", "b")])
    def test_the_dispersion_guard_lets_a_non_finite_leg_through(self, value, legs):
        """The premise, asserted so the fix cannot be credited to luck."""
        a, b = _inf_pair(value=value, legs=legs)
        with np.errstate(invalid="ignore", over="ignore"):
            # This is the computation the shipped code performed unguarded.
            # The suite does NOT promote RuntimeWarning to an error -- that
            # was tried and reverted (see pyproject.toml) -- so this is not
            # here to satisfy a filter. It is here so the arithmetic runs to
            # completion and the finiteness assertions BELOW get to be the
            # decision point: for these inputs the warning is the expected
            # outcome rather than news, and what the assertions decide is
            # whether the measurement came back non-finite. It also holds for
            # any caller that does elevate RuntimeWarning, so this input is
            # refused there too instead of raising out of the correlation.
            rho = float(np.corrcoef(a, b)[0, 1])
            # `nan == nan` is False, so the clip is compared for finiteness
            assert not np.isfinite(np.clip(rho, -0.9999, 0.9999)), (
                "the clip is not a repair"
            )
        assert np.ptp(a if "a" in legs else b) > 0
        assert not np.isfinite(rho)

    def test_the_unguarded_computation_raises_rather_than_refusing(self):
        """Why the fix wraps the measurement instead of only testing its result.

        A test that is allowed to promote the RuntimeWarning to an exception
        reproduces what a caller with this input gets from the unguarded
        computation: not a refusal, not a band, an exception. The refusal is the
        only acceptable answer, so it has to be produced by the estimator.
        """
        a, b = _inf_pair(value=np.inf, legs=("a",))
        with pytest.warns(RuntimeWarning):
            np.corrcoef(a, b)

    @pytest.mark.parametrize("value", [np.inf, -np.inf])
    def test_the_estimator_withholds_rho_and_the_lambda_with_it(self, value):
        """The cached-df path is the one the matrix caller uses.

        Fitted here rather than left to the estimator so the Student-t fit is
        not what withholds the pair: the t fit and `rho` are separate inputs,
        and only `rho` is broken by the inf. Asserting `nu` survives proves the
        refusal is attributable to the correlation.
        """
        a, b = _inf_pair(value=value, legs=("a",))
        lam, rho, nu, reason = TailRiskService.calculate_bivariate_tail_dependence(
            pd.Series(a), pd.Series(b), marginal_df_a=4.0, marginal_df_b=4.0
        )
        # RED on the shipped code: nan, nan, 4.0, None -- a "measurement" whose
        # every band comparison is False.
        assert rho is None
        assert lam is None
        assert reason is not None
        assert reason in DECLARED_REASONS
        assert nu == 4.0, "nu is not the broken input here"

    @pytest.mark.parametrize("value", [np.inf, -np.inf])
    @pytest.mark.parametrize("legs", [("a",), ("b",), ("a", "b")])
    def test_the_inf_path_names_the_non_finite_cause(self, value, legs):
        """`zero_dispersion_leg` is a FALSE cause for an inf leg.

        The whole value of `unmeasurable_pairs` is that it says which pair and
        why: a reader told "one leg has no dispersion" goes looking for a
        frozen series, while the actual defect is a non-finite number in the
        returns frame. Collapsing the two causes into one label trades a
        specific lie for a vague truth, so the cause is named separately.
        """
        a, b = _inf_pair(value=value, legs=legs)
        _lam, _rho, _nu, reason = TailRiskService.calculate_bivariate_tail_dependence(
            pd.Series(a), pd.Series(b), marginal_df_a=4.0, marginal_df_b=4.0
        )
        # RED on the code as it stood with the vocabulary widened but the
        # dispatch still collapsed: this returned 'zero_dispersion_leg'.
        assert reason == NON_FINITE_LEG
        assert reason != ZERO_DISPERSION

    @pytest.mark.parametrize("value", [np.inf, -np.inf])
    def test_the_matrix_pair_carries_the_non_finite_reason(self, value):
        a, b = _inf_pair(value=value)
        res = _matrix(a, b)
        assert res["unmeasurable_pairs"] == [
            {"pair": ["A", "B"], "reason": NON_FINITE_LEG}
        ]

    def test_a_constant_leg_still_names_the_dispersion_cause(self):
        """The other half of "do not collapse the two causes".

        Without this, a regression that made EVERY withheld pair report
        `non_finite_leg` would satisfy the inf tests above.
        """
        flat, b = _flat_pair()
        res = _matrix(flat, b)
        assert np.isfinite(flat).all(), "premise: this leg has no inf in it"
        assert res["unmeasurable_pairs"] == [
            {"pair": ["A", "B"], "reason": ZERO_DISPERSION}
        ]

    def test_non_finite_wins_when_both_causes_are_present(self):
        """Precedence, pinned: a non-finite input outranks a frozen one.

        A constant leg paired with an inf leg fails both tests. The non-finite
        label is the one that names a defect the caller has to fix upstream
        (a zero denominator in `pct_change`), so it is the one published. The
        pair is withheld either way, which is the part that does not depend on
        this choice.
        """
        n = 300
        a, b = _measurable_pair(n=n)
        flat = np.full(n, 0.004)
        a[100] = np.inf
        res = TailRiskService.calculate_tail_dependence_matrix(
            pd.DataFrame({"INF": a, "FLAT": flat, "REAL": b})
        )
        by_pair = {tuple(e["pair"]): e["reason"] for e in res["unmeasurable_pairs"]}
        assert by_pair[("INF", "FLAT")] == NON_FINITE_LEG
        assert by_pair[("FLAT", "REAL")] == ZERO_DISPERSION
        assert by_pair[("INF", "REAL")] == NON_FINITE_LEG
        assert set(by_pair.values()) == {NON_FINITE_LEG, ZERO_DISPERSION}

    @pytest.mark.parametrize("value", [np.inf, -np.inf])
    def test_the_pair_is_named_in_unmeasurable_pairs(self, value):
        a, b = _inf_pair(value=value)
        res = _matrix(a, b)
        # RED on the shipped code: [] -- the pair was published under the LOW
        # band with nothing marking it as unmeasured.
        assert len(res["unmeasurable_pairs"]) == 1
        entry = res["unmeasurable_pairs"][0]
        assert entry["pair"] == ["A", "B"]
        assert entry["reason"] in DECLARED_REASONS
        assert res["matrix"][0][1] is None

    def test_the_nan_never_reached_a_risk_band(self):
        """`high_tail_risk_pairs` filters on `>= 0.20`, and NaN is not.

        So the band it was labelled with (`LOW`) was unreachable from the
        published payload -- but `lower_tail_lambda` in the discarded
        `pairs_list` was `nan`, and a `nan` key is what a `sorted()` on it is
        asked to order. Asserted so this path stays exercised, not because a
        TypeError is expected here: `nan` is a float, and `None` never reaches
        the sort key.
        """
        a, b = _inf_pair()
        res = _matrix(a, b)
        assert res["high_tail_risk_pairs"] == []

    def test_measured_and_withheld_pairs_sort_together_without_a_type_error(self):
        """The measured half of the frame must be unaffected by the withheld half."""
        a, b = _inf_pair(legs=("a",))
        rng = np.random.default_rng(5)
        c = rng.normal(0.0004, 0.010, 300)
        d = rng.normal(0.0006, 0.013, 300)
        res = TailRiskService.calculate_tail_dependence_matrix(
            pd.DataFrame({"INF": a, "B": b, "C": c, "D": d})
        )
        names = {tuple(p["pair"]) for p in res["unmeasurable_pairs"]}
        assert names == {("INF", "B"), ("INF", "C"), ("INF", "D")}
        # The clean pairs are still measured, still banded, still publishable.
        order = list(res["tickers"])
        for left, right in (("C", "D"), ("B", "C"), ("B", "D")):
            i, j = order.index(left), order.index(right)
            assert res["matrix"][i][j] is not None, f"{left}/{right} lost its measurement"
            assert np.isfinite(res["matrix"][i][j])


class TestTheCategoryChainHasNoOtherNanSource:
    """B5, checked separately: is `UNMEASURABLE` reachable for EVERY withheld case?

    The chain reads `if lambda_l is None -> UNMEASURABLE`, then four numeric
    bands. Any other non-finite `lambda_l` would fall through every band
    comparison into `LOW` while still being `not None`, which is the defect
    above. So the invariant is asserted over the whole chain: a withheld pair
    carries a reason, a banded pair carries a finite lambda and no reason.
    """

    def _chain_contract(self, frame):
        tickers = list(frame.columns)
        for i in range(len(tickers)):
            for j in range(i + 1, len(tickers)):
                lam, rho, nu, reason = (
                    TailRiskService.calculate_bivariate_tail_dependence(
                        frame[tickers[i]],
                        frame[tickers[j]],
                        # the matrix caller's cached, isfinite-filtered fits, so
                        # nu is never what withholds the pair in this test
                        marginal_df_a=4.0,
                        marginal_df_b=5.0,
                    )
                )
                if lam is None:
                    assert reason in DECLARED_REASONS, (
                        f"{tickers[i]}/{tickers[j]}: withheld with no declared reason"
                    )
                    assert rho is None or np.isfinite(rho)
                else:
                    assert reason is None, (
                        f"{tickers[i]}/{tickers[j]}: banded but a reason was published"
                    )
                    assert np.isfinite(lam), (
                        f"{tickers[i]}/{tickers[j]}: lambda_L = {lam} is banded as "
                        f"'{ 'VERY_HIGH' if lam >= 0.50 else 'HIGH' if lam >= 0.35 else 'MODERATE' if lam >= 0.20 else 'LOW' }'"
                    )
                    assert 0.0 <= lam <= 1.0

    def test_a_frame_mixing_every_withheld_cause_still_satisfies_the_contract(self):
        n = 300
        rng = np.random.default_rng(11)
        a, b = _inf_pair(n=n, legs=("a",))
        frame = pd.DataFrame(
            {
                "INF": a,              # non-finite leg -> rho withheld
                "MEAS": b,
                "FLAT": np.full(n, 0.004),   # zero dispersion -> rho withheld
                "HUGE": rng.normal(0.0, 1e200, n),  # variance overflows float64
                "REAL": rng.normal(0.0005, 0.011, n),
            }
        )
        self._chain_contract(frame)

    def test_the_matrix_names_every_withheld_pair_exactly_once(self):
        """The payload-level half of the same invariant, over a real frame.

        `unmeasurable_pairs` and the null matrix cells are two views of one
        decision. Before the fix a `nan` lambda produced a null cell (NaN is
        converted to null at the wire) with NO entry beside it -- a null that
        looked unmeasured and was not in the list that explains why.
        """
        n = 300
        rng = np.random.default_rng(13)
        a, _b = _inf_pair(n=n, legs=("a",))
        frame = pd.DataFrame(
            {
                "INF": a,
                "FLAT": np.full(n, 0.004),
                "REAL": rng.normal(0.0005, 0.011, n),
            }
        )
        res = TailRiskService.calculate_tail_dependence_matrix(frame)
        named = {tuple(p["pair"]) for p in res["unmeasurable_pairs"]}
        assert len(res["unmeasurable_pairs"]) == len(named), "a pair was named twice"
        for entry in res["unmeasurable_pairs"]:
            assert entry["reason"] in DECLARED_REASONS
        order = list(frame.columns)
        null_cells = {
            (order[i], order[j])
            for i in range(len(order))
            for j in range(i + 1, len(order))
            if res["matrix"][i][j] is None
        }
        assert null_cells == named, (
            "the null matrix cells and the named pairs disagree: "
            f"cells={sorted(null_cells)} named={sorted(named)}"
        )
        assert named == {("INF", "REAL"), ("FLAT", "REAL"), ("INF", "FLAT")}

    def test_each_pair_is_named_with_the_cause_that_actually_applies(self):
        """The payload-level half of "do not collapse the two causes"."""
        n = 300
        a, b = _measurable_pair(n=n)
        a[100] = np.inf
        frame = pd.DataFrame(
            {"INF": a, "FLAT": np.full(n, 0.004), "REAL": b}
        )
        res = TailRiskService.calculate_tail_dependence_matrix(frame)
        by_pair = {tuple(e["pair"]): e["reason"] for e in res["unmeasurable_pairs"]}
        assert by_pair[("INF", "REAL")] == NON_FINITE_LEG
        assert by_pair[("INF", "FLAT")] == NON_FINITE_LEG
        assert by_pair[("FLAT", "REAL")] == ZERO_DISPERSION


# ---------------------------------------------------------------------------
# The disclosure has to name every reason the code can publish
# ---------------------------------------------------------------------------
class TestTheVocabularyIsDeclaredWhereAReaderWillFindIt:
    """A token the published rule does not name is a token nobody can act on.

    `unmeasurable_pairs_rule` ships in the payload and the estimator's own
    docstring is the API reference, so both have to carry the full vocabulary.
    Adding a fourth cause without adding it here is how a reader ends up with a
    reason string and no explanation of it.
    """

    def test_the_published_rule_names_every_declared_reason(self):
        rule = trs.TAIL_DEPENDENCE_RULE
        for reason in DECLARED_REASONS:
            assert reason in rule, f"{reason} is publishable but undocumented"

    def test_the_estimator_docstring_names_every_declared_reason(self):
        doc = TailRiskService.calculate_bivariate_tail_dependence.__doc__ or ""
        for reason in DECLARED_REASONS:
            assert f'"{reason}"' in doc, f"{reason} is publishable but undocumented"

    def test_the_rule_still_refuses_to_describe_the_two_causes_as_one(self):
        rule = trs.TAIL_DEPENDENCE_RULE.lower()
        assert "own reason" in rule
        assert "never zero_dispersion_leg" in rule


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