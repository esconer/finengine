"""Which side of a failed identity test is the liar (ENV-020 follow-on).

`measure_estimate_uncertainty` refuses to attach a band unless the resampling
estimator's own point value reproduces the published one. That is a test between
TWO numbers, and for most of its life it behaved as if it were a test of the
published number: on failure it withheld the band, kept the point, and wrote a
reason that read as an accusation against the point.

The live case it produced is the reason this file exists.  The published
`beta_vs_nifty` was independently re-derived, date-aligned, to
1.1036934406857877 - CORRECT.  The guard's own point value was -0.227490896001,
because the frame handed to the resampler paired the 307-row portfolio series
with the OLDEST 307 rows of a 2476-row benchmark series: misaligned by ~8.5
years.  The guard noticed a real contradiction and then guessed wrong about
which side was wrong, leaving a correct number published beside a sentence
saying it was wrong.

So the guard now takes a third number - an independent re-derivation of the
published value by a different code path, on the frame the point was actually
published from - and adjudicates.  The cases below are ordered by the
asymmetry that matters most: a witness that CANNOT deliver a verdict must never
cost a reader a correct number, because the failure mode being fixed is
publishing a number nobody checked, and trading that for hiding a number that
was right would have replaced one defect with a worse one.

Nothing here runs the audit CLI: it reads a frozen export, so a green gate would
say nothing about the code.
"""

import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import (
    POINT_ESTIMATOR_DECLINED,
    POINT_NOT_REPRODUCED_BY_ANY_WITNESS,
    POINT_REPRODUCED_BY_ESTIMATOR,
    POINT_REPRODUCED_BY_WITNESS_ONLY,
    POINT_STATUS_VALUES,
    POINT_UNVERIFIED,
    POINT_VERIFIED_BY_WITNESS,
    market_model_statistics,
    market_model_witness,
    measure_estimate_uncertainty,
)


# ---------------------------------------------------------------------------
# fixtures: a correctly aligned sample, and the mis-pairing the live case had
# ---------------------------------------------------------------------------

def _returns(n: int, seed: int, mu: float = 0.0004) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return mu + 0.010 * rng.standard_t(5, n)


def _closed_form_beta(frame: np.ndarray) -> float:
    """The tear sheet's own closed form - what the payload publishes.

    `pandas.Series.cov` / `.var`, both ddof=1, exactly as the route computes it.
    """
    portfolio = pd.Series(frame[:, 0])
    benchmark = pd.Series(frame[:, 1])
    return float(portfolio.cov(benchmark) / benchmark.var())


def _closed_form_alpha(frame: np.ndarray) -> float:
    """The published alpha: `(p.mean() - beta * b.mean()) * 252`."""
    return float(
        (pd.Series(frame[:, 0]).mean()
         - _closed_form_beta(frame) * pd.Series(frame[:, 1]).mean()) * 252
    )


BENCHMARK_ROWS = 2400
WINDOW = 320


def _portfolio(n: int = WINDOW) -> np.ndarray:
    return _returns(n, 5)


def _benchmark_history(rows: int = BENCHMARK_ROWS) -> np.ndarray:
    """A long benchmark history. Only one window of it is the holding window."""
    return _returns(rows, 11, mu=0.0003)


def _aligned_pair(n: int = WINDOW) -> np.ndarray:
    """The sample the point value is published from.

    The holding window is the MOST RECENT `n` rows of the benchmark, paired with
    the portfolio over the same dates.
    """
    history = _benchmark_history()
    return np.column_stack([_portfolio(n), history[-n:]])


def _mispaired_estimator_frame(
    n: int = WINDOW, start: int = 0
) -> np.ndarray:
    """What the live case actually handed the guard.

    Same portfolio, but the benchmark is a slice of the SAME history taken by
    position rather than by date - the oldest `n` rows by default, ~8.5 years
    before the rows the point was published from. Every element of the pair is
    real data and both series are the right length; only the PAIRING is wrong,
    and a reproduction test cannot see that. It just produces a different,
    confidently wrong beta.
    """
    history = _benchmark_history()
    return np.column_stack([_portfolio(n), history[start:start + n]])


def _block(frame, published, **kwargs):
    kwargs.setdefault("statistic_names", {"beta_vs_nifty": "beta"})
    return measure_estimate_uncertainty(
        frame,
        market_model_statistics(252),
        published,
        scope="unit test",
        point_tolerance=1e-4,
        **kwargs,
    )


def _live_case():
    """The traced end-to-end case: correct point, mis-paired estimator frame."""
    aligned = _aligned_pair(320)
    estimator_frame = _mispaired_estimator_frame(320)
    published = {
        "beta_vs_nifty": round(_closed_form_beta(aligned), 4),
        "alpha_annualized": round(_closed_form_alpha(aligned), 4),
    }
    return aligned, estimator_frame, published


# ---------------------------------------------------------------------------
# the two frames really are different frames - otherwise nothing below is a test
# ---------------------------------------------------------------------------

def test_the_mis_paired_frame_really_is_a_different_sample():
    """Guards the fixture, and with it every case built on it.

    If the truncation did not actually move the beta, the adjudication tests
    would pass for the wrong reason: the estimator would agree with the witness
    and the identity test would never fire.
    """
    aligned = _aligned_pair(320)
    estimator_frame = _mispaired_estimator_frame(320)
    assert estimator_frame.shape == aligned.shape
    assert _closed_form_beta(estimator_frame) != pytest.approx(
        _closed_form_beta(aligned), abs=1e-3
    )
    # and the closed form on the mis-paired frame is the value the guard saw
    assert _closed_form_beta(estimator_frame) < 0.0
    suite = market_model_statistics(252)
    block = estimator_frame.reshape(-1, 1, 2)
    got = float(np.asarray(suite["beta"](block)).ravel()[0])
    assert got == pytest.approx(_closed_form_beta(estimator_frame), abs=1e-12)


# ---------------------------------------------------------------------------
# 1. witness reproduces the published point, estimator does not
# ---------------------------------------------------------------------------

def test_witness_reproduces_the_published_point_so_the_ESTIMATOR_is_the_failing_side():
    """Today's live case, end to end. The correct point must survive.

    The point is the one that was independently re-derived and found correct.
    The guard's own value is the one that was wrong, and the reason has to name
    the ESTIMATOR as the failing side - not merely fail to blame the point.
    """
    aligned, estimator_frame, published = _live_case()
    block = _block(
        estimator_frame,
        published,
        witness=market_model_witness(252),
        witness_observations=aligned,
    )
    entry = block["estimates"]["beta_vs_nifty"]
    # the point is RETAINED, at its published value
    assert entry["point"] == published["beta_vs_nifty"]
    # the band is still withheld: it describes the mis-aligned frame
    assert entry["status"] == "not_computed"
    assert entry["conf_int"] is None
    assert entry["standard_error"] is None
    # and the verdict names the estimator, not the point
    assert entry["point_status"] == POINT_REPRODUCED_BY_WITNESS_ONLY
    assert entry["point_status"] == (
        "published_point_reproduced_by_independent_witness"
    )
    reason = entry["reason"]
    assert "ESTIMATOR is the failing side" in reason
    assert "is not that sample" in reason
    assert "RETAINED as published" in reason
    # the numbers that decided it are both in the reason
    assert f"{published['beta_vs_nifty']:.12g}" in reason
    # alpha took the same path
    assert block["estimates"]["alpha_annualized"]["point_status"] == (
        POINT_REPRODUCED_BY_WITNESS_ONLY
    )
    assert block["estimates"]["alpha_annualized"]["point"] == (
        published["alpha_annualized"]
    )
    # the two frames are different, and the payload says so
    assert block["observation_columns"] == 2
    assert block["witness_status"] == "witness_ran"
    assert f"{len(aligned)} observation(s), 2 column(s)" in (
        block["witness_status_basis"]
    )


def test_the_reason_no_longer_asserts_the_published_point_is_wrong():
    """The wording is the defect, not just the branching.

    With a point retained, a reason that calls the point the wrong one is a
    payload telling the reader to disbelieve a number that is correct. The
    unguarded default (no witness at all) must not accuse either side.
    """
    _, estimator_frame, published = _live_case()
    block = _block(estimator_frame, published)
    reason = block["estimates"]["beta_vs_nifty"]["reason"]
    assert block["estimates"]["beta_vs_nifty"]["point"] == published["beta_vs_nifty"]
    assert "no independent witness was supplied" in reason
    assert "RETAINED and flagged unverified" in reason
    # the old text implied the published number was the faulty side
    assert "The band would describe a different statistic" in reason
    assert "identity tolerance" not in reason


# ---------------------------------------------------------------------------
# 2 + 3. false-positive safety: a witness that cannot deliver a verdict
# ---------------------------------------------------------------------------

def test_a_witness_given_an_empty_frame_leaves_the_point_retained():
    """A frame the witness cannot measure must not cost the reader the point.

    This is the false-positive guard. The point here is CORRECT, the only
    problem is that the witness was handed no data, and the expected outcome is
    a retained point with no interval - never a null.
    """
    _, estimator_frame, published = _live_case()
    block = _block(
        estimator_frame,
        published,
        witness=market_model_witness(252),
        witness_observations=np.zeros((0, 2)),
    )
    entry = block["estimates"]["beta_vs_nifty"]
    assert entry["point"] == published["beta_vs_nifty"]
    assert entry["point"] is not None
    assert entry["conf_int"] is None
    assert entry["status"] == "not_computed"
    assert entry["point_status"] == POINT_UNVERIFIED
    assert entry["point_status"] == "unverified"
    assert "no finite observation of the published sample" in entry["reason"]
    assert block["witness_status"] == "witness_failed"


def test_a_witness_that_raises_leaves_the_point_retained():
    """The exception path, exercised directly.

    A test that only ever runs a well-behaved witness does not prove the
    false-positive guard - it proves the happy path of a guard that has no
    failure handling at all. Here the witness callable itself raises, and the
    published point must still be there.
    """
    _, estimator_frame, published = _live_case()

    def exploding_witness(block):
        raise ValueError("witness cannot solve this design")

    block = _block(
        estimator_frame,
        published,
        witness={"beta_vs_nifty": exploding_witness},
        witness_observations=_aligned_pair(320),
    )
    entry = block["estimates"]["beta_vs_nifty"]
    assert entry["point"] == published["beta_vs_nifty"]
    assert entry["point_status"] == POINT_UNVERIFIED
    assert entry["conf_int"] is None
    assert "ValueError: witness cannot solve this design" in entry["reason"]
    assert "RETAINED and flagged unverified" in entry["reason"]


def test_a_witness_returning_a_non_finite_value_leaves_the_point_retained():
    """`None` is a failure, not a verdict: nothing was re-derived."""
    _, estimator_frame, published = _live_case()
    block = _block(
        estimator_frame,
        published,
        witness={"beta_vs_nifty": lambda block: np.full((1,), np.nan)},
        witness_observations=_aligned_pair(320),
    )
    entry = block["estimates"]["beta_vs_nifty"]
    assert entry["point"] == published["beta_vs_nifty"]
    assert entry["point_status"] == POINT_UNVERIFIED
    assert entry["conf_int"] is None


# ---------------------------------------------------------------------------
# 4. the witness is a DIFFERENT code path, not a second copy
# ---------------------------------------------------------------------------

def test_the_witness_is_a_different_algorithm_not_a_restatement():
    """The falsifying test for the witness.

    Two implementations of the same OLS fit agree everywhere both are defined,
    so agreement cannot distinguish "second derivation" from "copy". What
    separates them is where they are NOT both defined: on a rank-deficient
    design the closed form divides by a zero variance and returns a non-finite
    value, while `np.linalg.lstsq` returns the minimum-norm solution. If the
    witness were a copy of `market_model_statistics` it would return non-finite
    here too, and this test would fail.
    """
    witness = market_model_witness(252)
    suite = market_model_statistics(252)
    # (a) a well-conditioned frame: both agree, so agreement is evidence
    frame = _aligned_pair(320)
    block = frame.reshape(-1, 1, 2)
    assert float(np.asarray(witness["beta"](block)).ravel()[0]) == pytest.approx(
        _closed_form_beta(frame), abs=1e-12
    )
    # (b) a rank-deficient design: a constant benchmark column
    degenerate = np.column_stack(
        [frame[:, 0], np.full(frame.shape[0], 0.0003)]
    )
    degenerate_block = degenerate.reshape(-1, 1, 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        closed = float(
            np.asarray(suite["beta"](degenerate_block)).ravel()[0]
        )
    solved = float(np.asarray(witness["beta"](degenerate_block)).ravel()[0])
    assert not np.isfinite(closed), "the closed form should divide by a zero variance"
    assert np.isfinite(solved), "lstsq must return the minimum-norm solution"
    # and the alpha paths differ structurally too: the witness reads the
    # intercept out of the solve, the estimator subtracts beta * mean(b)
    assert float(np.asarray(witness["alpha_annualized"](block)).ravel()[0]) == (
        pytest.approx(_closed_form_alpha(frame), abs=1e-10)
    )
    assert float(
        np.asarray(witness["alpha_annualized"](degenerate_block)).ravel()[0]
    ) != float(np.asarray(suite["alpha_annualized"](degenerate_block)).ravel()[0])


def test_the_witness_agrees_with_the_closed_form_on_a_well_conditioned_frame():
    """A witness that is merely WRONG would adjudicate nothing."""
    for seed_p, seed_b in ((5, 11), (2, 3), (8, 9)):
        frame = np.column_stack([_returns(300, seed_p), _returns(300, seed_b)])
        block = frame.reshape(-1, 1, 2)
        got = float(np.asarray(market_model_witness(252)["beta"](block)).ravel()[0])
        assert got == pytest.approx(_closed_form_beta(frame), abs=1e-10)


# ---------------------------------------------------------------------------
# the two-sided branch, and the band-provenance pass
# ---------------------------------------------------------------------------

def test_a_witness_that_also_misses_the_published_point_withholds_it():
    """The guard must not be one-sided.

    Unreachable on today's data - no live case has both sides wrong - and it
    exists precisely so that "retain the point" is a DECISION with a stated
    reason rather than a reflex. Two independent derivations contradicting the
    payload is the one case where `point: null` is the honest answer.
    """
    _, estimator_frame, published = _live_case()
    # a third, differently-wrong alignment: a middle slice of the same history,
    # so the witness produces a FINITE verdict that also misses the point
    other = _mispaired_estimator_frame(start=1040)
    block = _block(
        estimator_frame,
        published,
        witness=market_model_witness(252),
        witness_observations=other,
    )
    entry = block["estimates"]["beta_vs_nifty"]
    assert entry["point"] is None
    assert entry["point_status"] == POINT_NOT_REPRODUCED_BY_ANY_WITNESS
    assert entry["point_status"] == (
        "published_point_not_reproduced_by_independent_witness"
    )
    assert entry["conf_int"] is None
    assert "ALSO not" in entry["reason"]
    assert "withheld rather than published" in entry["reason"]


def test_a_correctly_aligned_frame_still_publishes_its_band():
    """The fix must not cost anyone an interval."""
    aligned = _aligned_pair(320)
    beta = _closed_form_beta(aligned)
    block = _block(
        aligned,
        {"beta_vs_nifty": round(beta, 4)},
        witness=market_model_witness(252),
        witness_observations=aligned,
    )
    entry = block["estimates"]["beta_vs_nifty"]
    assert entry["status"] == "computed"
    assert entry["point"] == round(beta, 4)
    assert entry["conf_int"] is not None
    low, high = entry["conf_int"]
    assert low <= entry["point"] <= high
    assert entry["point_status"] == POINT_VERIFIED_BY_WITNESS
    assert entry["point_status"] == "verified_against_independent_witness"
    assert block["status"] == "computed"


def test_every_point_status_is_in_the_published_vocabulary():
    """A closed vocabulary, so a consumer can switch on it."""
    aligned = _aligned_pair(320)
    beta = _closed_form_beta(aligned)
    _, estimator_frame, live = _live_case()
    blocks = [
        _block(estimator_frame, live),
        _block(estimator_frame, live, witness=market_model_witness(252),
               witness_observations=aligned),
        _block(estimator_frame, live, witness=market_model_witness(252),
               witness_observations=np.zeros((0, 2))),
        _block(aligned, {"beta_vs_nifty": round(beta, 4)},
               witness=market_model_witness(252), witness_observations=aligned),
        measure_estimate_uncertainty(
            np.zeros(0), market_model_statistics(252), {"beta_vs_nifty": 1.0},
            scope="unit test",
        ),
    ]
    seen = set()
    for block in blocks:
        for field, entry in block["estimates"].items():
            assert entry["point_status"] in POINT_STATUS_VALUES, (field, block["scope"])
            seen.add(entry["point_status"])
    # the identity-failure path must publish the unverified label by default
    assert POINT_UNVERIFIED in seen
    assert POINT_REPRODUCED_BY_WITNESS_ONLY in seen


# ---------------------------------------------------------------------------
# 5. the sixth route: the estimator was never invoked
# ---------------------------------------------------------------------------
# `unverified` is the false-positive-safe default of a guard that WAS asked and
# could not conclude.  A caller that declares `estimator_withheld` never runs
# the resampler at all, publishes the reason, sets `bootstrap_resamples` to 0,
# and keeps the point.  Before `estimator_declined` existed that state was
# published as `unverified`, which made a deliberate, costed, DISCLOSED refusal
# indistinguishable from a check that ran and failed - and, on the live export,
# made fourteen declined legs read as more doubtful than the measured portfolio
# leg sitting on the same payload under the same word.
#
# The word matters only if the refusal is distinguishable, so the first test
# below proves the estimator really is never called (a statistic that raises if
# it is evaluated), not merely that a flag was set.

WITHHELD_REASON = (
    "not measured: this leg's re-fit estimator was declared too expensive to "
    "run, so it was never evaluated rather than having run and failed."
)


def _declining_statistics(calls):
    """The real estimator, wrapped so a call is recorded - and assertable."""

    def suite(block):
        calls["n"] += 1
        return market_model_statistics(252)(block)

    return suite


def test_a_declined_estimator_publishes_the_declined_state_not_unverified():
    """The test that fails on the pre-fix code.

    Everything else here is false-positive safety, which is the reason this
    change is safe to make.  This is the positive claim: a block whose estimator
    was declared too expensive publishes `estimator_declined`, publishes the
    reason, publishes 0 draws, and keeps the point.  It must NOT publish
    `unverified`, which is a different sentence about a different event.
    """
    aligned = _aligned_pair(320)
    published = {"beta_vs_nifty": round(_closed_form_beta(aligned), 4)}
    calls = {"n": 0}
    block = measure_estimate_uncertainty(
        aligned,
        _declining_statistics(calls),
        published,
        scope="unit test: declined estimator",
        statistic_names={"beta_vs_nifty": "beta"},
        estimator_withheld=WITHHELD_REASON,
    )
    entry = block["estimates"]["beta_vs_nifty"]

    # the third word, and explicitly NOT the one it replaced
    assert entry["point_status"] == POINT_ESTIMATOR_DECLINED
    assert entry["point_status"] == "estimator_declined"
    assert entry["point_status"] != POINT_UNVERIFIED
    assert entry["point_status"] != "unverified"

    # the point is retained at its published value: declining a BAND is not a
    # licence to withdraw the number the reader already had
    assert entry["point"] == published["beta_vs_nifty"]
    assert entry["point"] is not None
    assert entry["status"] == "not_computed"
    assert entry["reason"] == WITHHELD_REASON

    # and the decline is real, not a flag: the estimator was never invoked
    assert calls["n"] == 0
    assert block["bootstrap_resamples"] == 0
    assert block["estimator_withheld"] == WITHHELD_REASON
    assert block["point_tolerance"] is None
    # `effective_n` is still measured and still published - the part of this
    # leg's precision that IS known costs nothing
    assert block["autocorrelation"]["effective_n"] is not None
    # the block's own basis must not contradict the label it publishes. The
    # string names `unverified` once, to explain why this route is NOT that
    # one, so the assertion is on the assignment sentence rather than on the
    # word being absent - a basis that had to avoid the word would be a basis
    # that could not make the contrast.
    basis = block["estimator_withheld_basis"]
    assert "retained with point_status estimator_declined" in basis
    assert "retained with point_status unverified" not in basis


def test_a_declined_measurement_is_distinguishable_from_an_inconclusive_one():
    """The requirement itself, stated as a contrast between two live-shaped runs.

    Both publish `not_computed` with no band and a retained point.  The
    difference is that in the first the estimator ran and a witness could not
    conclude; in the second the estimator was never asked.  If a consumer
    cannot tell those apart from `point_status`, the vocabulary is still
    incomplete however correct either string is on its own.
    """
    aligned = _aligned_pair(320)
    published = {"beta_vs_nifty": round(_closed_form_beta(aligned), 4)}
    inconclusive = _block(
        aligned,
        published,
        witness={"beta_vs_nifty": lambda b: np.full((1,), np.nan)},
        witness_observations=aligned,
        # force the identity test to fail so the adjudication branch is the one
        # under test, on a point the witness then cannot adjudicate
    )
    # a frame the estimator will disagree with, and a witness that cannot say
    _, estimator_frame, live = _live_case()
    inconclusive = _block(
        estimator_frame,
        live,
        witness={"beta_vs_nifty": lambda b: np.full((1,), np.nan)},
        witness_observations=aligned,
    )
    declined = _block(
        aligned,
        published,
        estimator_withheld=WITHHELD_REASON,
    )

    inconclusive_entry = inconclusive["estimates"]["beta_vs_nifty"]
    declined_entry = declined["estimates"]["beta_vs_nifty"]

    # identical on every axis a naive consumer would read
    assert inconclusive_entry["status"] == declined_entry["status"]
    assert inconclusive_entry["conf_int"] is None
    assert declined_entry["conf_int"] is None
    assert inconclusive_entry["point"] == live["beta_vs_nifty"]
    assert declined_entry["point"] == published["beta_vs_nifty"]
    # and different on the one that matters
    assert inconclusive_entry["point_status"] == POINT_UNVERIFIED
    assert declined_entry["point_status"] == POINT_ESTIMATOR_DECLINED
    assert inconclusive_entry["point_status"] != declined_entry["point_status"]


def test_the_false_positive_safe_default_did_not_move():
    """Every way a witness can fail to deliver a verdict, in one place.

    A witness that raises, that is absent, that returns a non-finite value, or
    that is handed an empty frame: all four must still publish `unverified` with
    the point retained.  Adding a word for the declined case is only legitimate
    if the default it was carved out of is provably untouched, and 'provably'
    means enumerated rather than asserted in a comment.
    """
    _, estimator_frame, published = _live_case()

    def exploding(_block):
        raise ValueError("witness cannot solve this design")

    cases = {
        "no witness supplied": {},
        "witness raises": {
            "witness": {"beta_vs_nifty": exploding},
            "witness_observations": _aligned_pair(320),
        },
        "witness returns a non-finite value": {
            "witness": {"beta_vs_nifty": lambda b: np.full((1,), np.nan)},
            "witness_observations": _aligned_pair(320),
        },
        "witness handed an empty frame": {
            "witness": market_model_witness(252),
            "witness_observations": np.zeros((0, 2)),
        },
    }
    for label, kwargs in cases.items():
        entry = _block(estimator_frame, published, **kwargs)[
            "estimates"
        ]["beta_vs_nifty"]
        assert entry["point_status"] == POINT_UNVERIFIED, label
        assert entry["point_status"] == "unverified", label
        # the point survives every one of them, at its published value
        assert entry["point"] == published["beta_vs_nifty"], label
        assert entry["conf_int"] is None, label
        assert entry["standard_error"] is None, label


def test_the_measured_routes_are_unchanged():
    """The two states a passing measurement reaches, still reaching them.

    A regression guard on the other side of the change: a vocabulary widened at
    the declined end must not have narrowed or re-routed the measured end, and
    the distinction between "the estimator reproduced it" and "a second path
    did too" is the whole point of the witness.
    """
    aligned = _aligned_pair(320)
    beta = round(_closed_form_beta(aligned), 4)

    # estimator ran, no witness: the point was reproduced by the estimator
    alone = _block(aligned, {"beta_vs_nifty": beta})
    alone_entry = alone["estimates"]["beta_vs_nifty"]
    assert alone_entry["status"] == "computed"
    assert alone_entry["point_status"] == POINT_REPRODUCED_BY_ESTIMATOR
    assert alone_entry["point_status"] == "reproduced_by_estimator"
    assert alone_entry["point"] == beta
    assert alone_entry["conf_int"] is not None

    # estimator ran AND a second path agreed: the same band, better provenance
    both = _block(
        aligned,
        {"beta_vs_nifty": beta},
        witness=market_model_witness(252),
        witness_observations=aligned,
    )
    both_entry = both["estimates"]["beta_vs_nifty"]
    assert both_entry["status"] == "computed"
    assert both_entry["point_status"] == POINT_VERIFIED_BY_WITNESS
    assert both_entry["point_status"] == "verified_against_independent_witness"
    assert both_entry["point"] == beta
    # the band itself is untouched by the provenance upgrade
    assert both_entry["conf_int"] == alone_entry["conf_int"]
    assert both_entry["standard_error"] == alone_entry["standard_error"]


def test_every_route_a_point_can_take_has_a_word_and_keeps_the_point():
    """Exhaustive, so a fifth situation cannot arrive without a word for it.

    Six routes, six words, asserted in both directions: each route reaches its
    own label (so no route is dead code and no label is unreachable) and the
    published vocabulary is EXACTLY those six (so a seventh cannot be added
    without this failing).  `point` is asserted present and unchanged on every
    route that retains it.
    """
    aligned = _aligned_pair(320)
    beta = round(_closed_form_beta(aligned), 4)
    published = {"beta_vs_nifty": beta}
    _, estimator_frame, live = _live_case()

    def exploding(_block):
        raise ValueError("witness cannot solve this design")

    #: route -> (block, field, published point the entry must still carry)
    routes = {
        "estimator reproduced the point": (
            _block(aligned, published), "beta_vs_nifty", beta,
        ),
        "a second path also reproduced it": (
            _block(aligned, published, witness=market_model_witness(252),
                   witness_observations=aligned), "beta_vs_nifty", beta,
        ),
        "witness reproduced it, the ESTIMATOR did not": (
            _block(estimator_frame, live, witness=market_model_witness(252),
                   witness_observations=aligned),
            "beta_vs_nifty", live["beta_vs_nifty"],
        ),
        "witness could not deliver a verdict": (
            _block(estimator_frame, live, witness={"beta_vs_nifty": exploding},
                   witness_observations=aligned),
            "beta_vs_nifty", live["beta_vs_nifty"],
        ),
        "the estimator was never invoked": (
            _block(aligned, published, estimator_withheld=WITHHELD_REASON),
            "beta_vs_nifty", beta,
        ),
        "no finite observation was measured at all": (
            measure_estimate_uncertainty(
                np.zeros(0), market_model_statistics(252),
                {"beta_vs_nifty": beta}, scope="unit test: empty sample",
            ),
            "beta_vs_nifty", beta,
        ),
    }
    seen = {}
    for label, (block, field, point) in routes.items():
        entry = block["estimates"][field]
        assert entry["point_status"] in POINT_STATUS_VALUES, label
        seen[label] = entry["point_status"]
        # the point is present and unchanged on every route that retains it.
        # The one documented exception is the two-derivations-disagree route,
        # which is not in this table: `point: null` is reachable ONLY there.
        assert entry["point"] == point, (label, entry["point_status"])
        assert entry["point"] is not None, label

    assert seen["estimator reproduced the point"] == POINT_REPRODUCED_BY_ESTIMATOR
    assert seen["a second path also reproduced it"] == POINT_VERIFIED_BY_WITNESS
    assert seen["witness reproduced it, the ESTIMATOR did not"] == (
        POINT_REPRODUCED_BY_WITNESS_ONLY
    )
    assert seen["witness could not deliver a verdict"] == POINT_UNVERIFIED
    assert seen["the estimator was never invoked"] == POINT_ESTIMATOR_DECLINED
    assert seen["no finite observation was measured at all"] == POINT_UNVERIFIED

    # every route above lands on a DISTINCT word per situation, and the one
    # place two routes share a word (`unverified`) is deliberate: both are
    # "an estimator or a sample that was measured and could not conclude"
    # rather than "nothing was asked".
    assert POINT_ESTIMATOR_DECLINED not in (
        POINT_UNVERIFIED, POINT_REPRODUCED_BY_ESTIMATOR,
        POINT_VERIFIED_BY_WITNESS, POINT_REPRODUCED_BY_WITNESS_ONLY,
    )

    # and the vocabulary is closed at exactly the words this module can produce
    assert POINT_STATUS_VALUES == frozenset({
        POINT_REPRODUCED_BY_ESTIMATOR,
        POINT_VERIFIED_BY_WITNESS,
        POINT_REPRODUCED_BY_WITNESS_ONLY,
        POINT_NOT_REPRODUCED_BY_ANY_WITNESS,
        POINT_UNVERIFIED,
        POINT_ESTIMATOR_DECLINED,
    })
    # six routes are not all six words: the both-sides-disagree route is the
    # documented null and has its own test, so it is reachable, not implied
    disagree = _block(
        estimator_frame, live, witness=market_model_witness(252),
        witness_observations=_mispaired_estimator_frame(start=1040),
    )["estimates"]["beta_vs_nifty"]
    assert disagree["point_status"] == POINT_NOT_REPRODUCED_BY_ANY_WITNESS
    assert disagree["point"] is None
