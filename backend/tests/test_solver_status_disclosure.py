"""C-2: nothing read `Problem.status`. Publish it, and refuse what it should.

`optimization_service._solve` was

    def _solve(prob): prob.solve(solver=cp.CLARABEL)

with no read of the outcome and no exception mapping, and the Black-Litterman
tangency solve did not even go through it - it called `prob.solve` directly and
checked only `y.value is None or not np.isfinite(y.value).all()`. A status such
as `optimal_inaccurate` therefore published its vector under a `solver` key that
said `cvxpy/clarabel`, and a `SolverError` on that one path escaped as a 500
while every other strategy's mapped to 400.

THE POLICY, and it is a tolerance policy rather than a formula:
`optimal_inaccurate` is REFUSED, not published with a caveat - see
`SOLVER_STATUS_ACCEPTED`, whose comment records the measurement the decision
rests on (52 solves over well-posed and deliberately ill-posed books: 51
`optimal`, 1 `infeasible`, 0 `optimal_inaccurate`). The implicit tolerance is
Clarabel's own defaults, neither tightened nor overridden, so "optimal" means
"optimal to the solver's defaults" and a problem needing a tighter solve is
refused rather than served.

No test here asserts an exact magnitude. The tangency QP's residual is
BLAS-thread sensitive (3.9e-11 at default threads, 2.4e-12 at
`OPENBLAS_NUM_THREADS=1`), so pinning a number across thread settings would test
the thread count. What is pinned is the DECISION, which is thread-stable.

No network. Fixed seed throughout.
"""

from __future__ import annotations

import inspect

import cvxpy as cp
import numpy as np
import pandas as pd
import pytest

from app.services import optimization_service as opt
from app.services.optimization_service import (
    BL_PATH_SOLVER_FAILURE,
    SOLVER_STATUS_ACCEPTED,
    _black_litterman_solved,
    _min_vol,
    _solve,
    optimize,
)


def _book(n=5, days=260, seed=17, drift=0.0005):
    """A well-posed book: enough legs, enough days, positive drift so
    `max_sharpe` is defined."""
    r = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=days)
    base = r.normal(drift, 0.014, days)
    return pd.DataFrame(
        {
            f"A{i:02d}": 0.4 * base + r.normal(0.0, 0.012, days)
            for i in range(n)
        },
        index=idx,
    )


def _force_status(monkeypatch, status: str):
    """Make every subsequent cvxpy solve report `status`, keeping the real solve.

    The solver's own ANSWER is left untouched - only the label changes. That
    matters: it makes the red proof a test of the status CHECK rather than of
    arithmetic, and it keeps every assertion thread-independent.
    """
    original = cp.Problem.solve

    def patched(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self._status = status

    monkeypatch.setattr(cp.Problem, "solve", patched)


# ===========================================================================
# 1. The defect: a refused status was published as a solution
# ===========================================================================
def _refuse_first_solve_only(monkeypatch, status: str):
    """Refuse the FIRST solve (the tangency one) and let later ones through.

    This is what distinguishes "the record publishes the status of the solve its
    weights ARE" from "the record publishes `optimal` because that is the only
    string the code knows".
    """
    original = cp.Problem.solve
    state = {"n": 0}

    def patched(self, *args, **kwargs):
        original(self, *args, **kwargs)
        state["n"] += 1
        self._status = status if state["n"] == 1 else cp.OPTIMAL

    monkeypatch.setattr(cp.Problem, "solve", patched)
    return state


class TestTheStatusIsChecked:
    def test_an_inaccurate_min_vol_is_refused_not_published(self, monkeypatch):
        """RED before the fix: this published a full recommendation whose
        weights came from a solve the solver declined to certify."""
        _force_status(monkeypatch, cp.OPTIMAL_INACCURATE)

        with pytest.raises(ValueError) as excinfo:
            optimize(_book(), "min_vol")

        detail = str(excinfo.value)
        assert "optimal_inaccurate" in detail
        assert "No weights are published" in detail

    def test_an_inaccurate_max_sharpe_is_refused(self, monkeypatch):
        _force_status(monkeypatch, cp.OPTIMAL_INACCURATE)
        with pytest.raises(ValueError, match="optimal_inaccurate"):
            optimize(_book(), "max_sharpe")

    def test_an_inaccurate_min_cvar_is_refused(self, monkeypatch):
        _force_status(monkeypatch, cp.OPTIMAL_INACCURATE)
        with pytest.raises(ValueError, match="optimal_inaccurate"):
            optimize(_book(), "min_cvar")

    def test_every_non_optimal_status_is_refused(self, monkeypatch):
        """Not just `optimal_inaccurate`. The whole point of reading the status
        is that cvxpy can say the problem was unsolvable while still handing
        back a vector."""
        for status in (
            cp.INFEASIBLE,
            cp.INFEASIBLE_INACCURATE,
            cp.UNBOUNDED,
            cp.UNBOUNDED_INACCURATE,
            cp.OPTIMAL_INACCURATE,
        ):
            _force_status(monkeypatch, status)
            with pytest.raises(ValueError, match=status):
                _min_vol(np.eye(3) * 0.04)

    def test_an_unset_status_is_refused(self, monkeypatch):
        """`prob.status` is None when solve never ran. Treating that as success
        would be the same defect with a null instead of a string."""
        original = cp.Problem.solve

        def patched(self, *args, **kwargs):
            original(self, *args, **kwargs)
            self._status = None

        monkeypatch.setattr(cp.Problem, "solve", patched)
        with pytest.raises(ValueError, match="None"):
            _min_vol(np.eye(3) * 0.04)

    def test_a_solver_error_still_maps_to_value_error(self, monkeypatch):
        """The pre-existing contract, kept: `SolverError` is not a `ValueError`
        subclass, so letting it through made a solver failure a 500 here and a
        400 everywhere else."""
        def boom(*args, **kwargs):
            raise cp.error.SolverError("CLARABEL failed")

        monkeypatch.setattr(cp.Problem, "solve", boom)
        with pytest.raises(ValueError, match="solver failed"):
            _min_vol(np.eye(3) * 0.04)

    def test_the_black_litterman_path_no_longer_bypasses_the_check(self):
        """It called `prob.solve` directly. Pinned on the source, because a
        bypass is invisible to a behavioural test until the one path that uses
        it happens to fail."""
        src = inspect.getsource(_black_litterman_solved)
        assert "prob.solve(" not in src, (
            "_black_litterman_solved bypasses the checked helper again"
        )
        assert src.count("_solve(prob, log)") == 1

    def test_the_black_litterman_refusal_is_labelled_not_published(self, monkeypatch):
        """The tangency weights are refused; the record publishes the `_min_vol`
        fallback under a path name that says the tangency answer was not used."""
        _refuse_first_solve_only(monkeypatch, cp.OPTIMAL_INACCURATE)

        record = optimize(_book(), "black_litterman")

        assert record["long_only_clip"]["solution_path"] == BL_PATH_SOLVER_FAILURE
        assert record["long_only_clip"]["applied"] is False
        # The status published is the one whose answer the weights ARE: the
        # fallback solve, which came back `optimal`. The refused status is in the
        # solve log, not here - so `problem_status` cannot be confused with "the
        # tangency solve was fine".
        assert record["problem_status"] == cp.OPTIMAL
        assert sum(record["weights"].values()) == pytest.approx(1.0, abs=1e-4)

    def test_the_solve_log_is_a_full_census_in_order(self, monkeypatch):
        """Both solves are recorded, refused one FIRST. This is the fact the
        single `problem_status` key rests on: the last entry is the published
        one because every fallback solves after the answer it replaces."""
        _refuse_first_solve_only(monkeypatch, cp.OPTIMAL_INACCURATE)
        log: list[str] = []

        _black_litterman_solved(_book(), log=log)

        assert log == [cp.OPTIMAL_INACCURATE, cp.OPTIMAL]
        assert log[-1] == cp.OPTIMAL

    def test_a_refused_tangency_falls_back_rather_than_raising(self, monkeypatch):
        """The distinction that matters: `_black_litterman_solved` already owns a
        labelled fallback for a tangency answer it cannot use, so a refused
        status uses that vocabulary rather than inventing a new failure."""
        only_tangency_refused = {"done": False}
        original = cp.Problem.solve

        def patched(self, *args, **kwargs):
            original(self, *args, **kwargs)
            if only_tangency_refused["done"]:
                return
            only_tangency_refused["done"] = True
            self._status = cp.OPTIMAL_INACCURATE

        monkeypatch.setattr(cp.Problem, "solve", patched)
        weights, clip = _black_litterman_solved(_book())

        assert clip["solution_path"] == BL_PATH_SOLVER_FAILURE
        assert clip["applied"] is False
        assert np.isfinite(weights).all()
        assert (weights >= 0).all()

    def test_the_non_finite_value_guard_is_still_there(self, monkeypatch):
        """A status check is not a replacement for the value check. `-inf` is
        finite-looking to a status, and `np.clip(-inf, 0, None)` is 0.0."""
        src = inspect.getsource(_black_litterman_solved)
        assert "np.isfinite(y.value).all()" in src
        assert "np.isnan(y.value)" not in src


# ===========================================================================
# 2. `problem_status` is published on every record
# ===========================================================================
class TestProblemStatusIsPublished:
    @pytest.mark.parametrize("strategy", ["min_vol", "max_sharpe", "min_cvar",
                                          "black_litterman", "hrp"])
    def test_the_key_is_present_on_every_record(self, strategy):
        record = optimize(_book(), strategy)
        assert "problem_status" in record

    def test_a_real_solve_reports_the_solver_own_status(self):
        """Not a hard-coded `optimal`: it is whatever cvxpy said."""
        record = optimize(_book(), "min_vol")
        assert record["problem_status"] == cp.OPTIMAL

    def test_the_published_status_tracks_the_solve_the_weights_come_from(
        self, monkeypatch
    ):
        """The disclosure is real, not decorative. Forcing only the tangency
        solve to `optimal_inaccurate` and letting the fallback through publishes
        `optimal` - because `optimal` is the status of the solve the weights
        ARE. A hard-coded `optimal` would pass the tautological version of this
        assertion; this one fails if the record ever publishes a status that was
        not the last solve."""
        _refuse_first_solve_only(monkeypatch, cp.OPTIMAL_INACCURATE)
        record = optimize(_book(), "black_litterman")

        assert record["long_only_clip"]["solution_path"] == BL_PATH_SOLVER_FAILURE
        assert record["problem_status"] == cp.OPTIMAL
        assert record["problem_status"] != cp.OPTIMAL_INACCURATE

    def test_a_forced_optimal_still_reports_optimal(self, monkeypatch):
        _force_status(monkeypatch, cp.OPTIMAL)
        assert optimize(_book(), "min_vol")["problem_status"] == cp.OPTIMAL

    def test_hrp_publishes_null_because_no_solver_ran(self):
        """`None` is "no cvxpy solve ran", never "the solver did fine". The
        published status and the `solver` string agree: `hrp` says
        `hierarchical-bisection`, and its status is null."""
        record = optimize(_book(), "hrp")
        assert record["solver"] == "hierarchical-bisection"
        assert record["problem_status"] is None

    def test_a_refused_status_can_never_appear_on_a_record(self, monkeypatch):
        """The load-bearing guarantee: `_solve` raises on anything outside
        `SOLVER_STATUS_ACCEPTED`, so a record can only ever carry an accepted
        one - unless someone bypasses the helper again."""
        _force_status(monkeypatch, cp.OPTIMAL_INACCURATE)
        for strategy in ("min_vol", "max_sharpe", "min_cvar"):
            with pytest.raises(ValueError):
                optimize(_book(), strategy)

    def test_the_accepted_set_is_named_and_minimal(self):
        assert SOLVER_STATUS_ACCEPTED == (cp.OPTIMAL,)
        assert cp.OPTIMAL_INACCURATE not in SOLVER_STATUS_ACCEPTED

    def test_the_log_records_every_solve_in_order(self):
        """`problem_status` is the LAST entry because every fallback solves
        after the answer it replaces. Pinned, because that is the whole reason a
        single key is enough to identify the published solve."""
        log: list[str] = []
        _solve(
            cp.Problem(cp.Minimize(cp.sum_squares(cp.Variable(2)))), log
        )
        assert log == [cp.OPTIMAL]

    def test_a_refused_status_is_still_logged(self, monkeypatch):
        """So the census is complete even on a refusal - the record publishes
        the published solve's status, and the log holds the rest."""
        _force_status(monkeypatch, cp.OPTIMAL_INACCURATE)
        log: list[str] = []
        with pytest.raises(ValueError):
            _min_vol(np.eye(3) * 0.04, log=log)
        assert log == [cp.OPTIMAL_INACCURATE]

    def test_the_log_is_per_call_not_module_state(self):
        """`optimize` runs in a threadpool, so a module-level log would
        interleave statuses between concurrent books. Proven by two calls
        leaving nothing behind: each starts empty."""
        first: list[str] = []
        _min_vol(np.eye(3) * 0.04, log=first)
        second: list[str] = []
        _min_vol(np.eye(3) * 0.05, log=second)
        assert first == second == [cp.OPTIMAL]


# ===========================================================================
# 3. Nothing measured moved
# ===========================================================================
class TestNothingMeasuredMoved:
    """The checked helper must not perturb a single published weight. The
    comparison is against the pre-fix module, loaded from a COPY under a private
    name so the real source is never swapped out for a red proof."""

    def test_the_weights_are_identical_to_the_pre_fix_module(self):
        import importlib.util
        import sys
        from pathlib import Path

        prefix_path = Path(
            r"C:\Users\Sayanti\AppData\Local\Temp\opencode"
        ) / "prefix_optimization_service.py"
        if not prefix_path.exists():
            pytest.skip("pre-fix copy not available; run the red-proof script first")

        book = _book()
        spec = importlib.util.spec_from_file_location("prefix_opt", prefix_path)
        prefix = importlib.util.module_from_spec(spec)
        sys.modules["prefix_opt"] = prefix
        try:
            spec.loader.exec_module(prefix)
            for strategy in ("min_vol", "min_cvar", "black_litterman", "hrp"):
                before = prefix.optimize(book, strategy)["weights"]
                after = optimize(book, strategy)["weights"]
                assert after == before, strategy
        finally:
            del sys.modules["prefix_opt"]

    def test_the_log_argument_is_keyword_only_on_every_solver(self):
        """Existing callers pass positionally (`_min_vol(cov)`,
        `_max_sharpe(mu, cov, rf)`, `_min_cvar(rets, beta=0.95)`); widening any
        of those positionally would let a fifth argument arrive by accident."""
        for fn, arity in ((opt._min_vol, 1), (opt._max_sharpe, 3), (opt._min_cvar, 2)):
            params = inspect.signature(fn).parameters
            positional = [
                name
                for name, p in params.items()
                if p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
            ]
            assert positional == list(params)[:arity], fn.__name__
            assert params["log"].kind is inspect.Parameter.KEYWORD_ONLY