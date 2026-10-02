"""The stationarity gate on the WIRE: a verdict the route does not publish is not enforced.

`tests/test_p03_coint_stationarity_gate.py` proves the engine measures both legs
of a pair and withholds a spread when it must. `tests/test_p03_coint_directive_gate.py`
proves the SI-1/AD-1 family gate still stands. Neither asserts that
`GET /analytics/coint` PUBLISHES any of it, and that is the whole failure mode
this file exists for: the defect class is "correct in the database, absent from
the API", and a suite with no assertion on the published payload stays green if
the wiring is deleted tomorrow.

Five things are guarded, all on the serialised response - what the AI-context
exporter reads, via `model_dump_json()`:

  1. every directive restates the gate (`stationarity_gate`) and both legs
     (`stationarity_leg_a` / `stationarity_leg_b`) next to
     `johansen_agrees_with_decision`, and the verdict on a directive is
     INVARIANTLY `both_legs_i1` - a directive cannot exist without a passed
     gate, so any other verdict on a directive is a contradiction, not a state,
  2. `extras["signal_policy"]` states the gate's rule, its lag rule, its alpha
     and its two withholding heads, and `gate_rule` names the stationarity rung.
     A verdict with an unstated rule is worse than no gate: a reader cannot
     tell whether I(1) was established on a defensible lag structure or an
     arbitrary one, so the published rule is checked against the resolved
     lags/bandwidth the legs actually carry - not merely against itself,
  3. `spurious_regression_rejected_count` and
     `stationarity_undetermined_count` sit beside `contested_pair_count`,
  4. `data_status` is demoted to `partial` when either count is non-zero, and
     stays `available` when both are zero. The negative half is the half nobody
     writes, and a demotion that fires on clean scans is noise,
  5. `multiple_testing` separates `surviving_pairs` (a p-value measurement) from
     `actionable_pairs_count` (that set intersected with rows whose recorded
     gate passed), and the two differ by EXACTLY the number of gate-rejected
     survivors. A pair can clear Bonferroni and still be untradeable because
     its legs are not I(1); conflating the two is what the field exists to
     kill.

The divergence case is therefore not optional: every assertion about item 5 is
built on a scan where a spurious pair SURVIVES the family correction. On a
clean scan `surviving_pairs == actionable_pairs` and a pre-wiring payload would
pass every one of those tests, which is exactly the trap.

And the mirror image, because a wiring task that quietly moved a number would be
the same defect class in reverse: the whole pre-wiring `multiple_testing` block
is re-derived from `multiplicity_report` and required to be byte-identical key
for key, the new keys are pinned to the exact set that may be added, and every
`pairs[i]` leaf outside the three stationarity keys is compared to the row the
fixture handed the scan.

No DB, no network, no clock literals: the route derives its window from
`datetime.now()`, so the fake price index is anchored to the current business
day rather than to a hard date that three tests in this project have already
been broken by.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest

from app.api import analytics as analytics_mod
from app.api.analytics import get_cointegration_pairs
from app.models.schemas import CointPairResult
from app.services import cointegration_service as coint
from app.services.cointegration_service import (
    MULTIPLICITY_CORRECTION,
    SIGNAL_DIAGNOSTIC_UNAVAILABLE,
    SIGNAL_SPURIOUS,
    SIGNAL_STATIONARITY_UNDETERMINED,
    STATIONARITY_ALPHA,
    STATIONARITY_GATE_PASSED,
    STATIONARITY_GATE_SPURIOUS,
    STATIONARITY_GATE_UNRESOLVED,
    STATIONARITY_LAG_RULE,
    CointegrationService,
    _IN_MEMORY_COINT_CACHE,
    build_pair_signal,
    kpss_bandwidth,
    multiplicity_report,
)

# Aligned observations per leg. Large enough for ADF/KPSS on log price to be
# estimable at all (the engine's floor is 30) and identical across the universe
# so the per-pair depth reference is 1.0 and depth cannot demote a scan on its
# own - the demotion under test has to be the gate's, not a shallow-history
# artefact.
N = 174

# Head tokens that make a signal an ORDER. Asserted on these rather than on
# prose, so a rewording of an explanation cannot quietly pass.
_ACTION_TOKENS = ("LONG_SPREAD", "SHORT_SPREAD")

# The three keys the wiring is allowed to add to a directive, and the four it
# is allowed to add to `signal_policy`, spelled out so "a key is present" and
# "the key set is exactly these" are different assertions.
_DIRECTIVE_GATE_KEYS = (
    "stationarity_gate",
    "stationarity_leg_a",
    "stationarity_leg_b",
)
_SIGNAL_POLICY_GATE_KEYS = (
    "stationarity_gate_rule",
    "stationarity_lag_rule",
    "stationarity_alpha",
    "stationarity_withholding_heads",
)

# Row leaves that existed before the stationarity gate. The no-regression claim
# is byte-identity, so it is enumerated rather than spot-checked; the same list
# guards the engine in test_p03_coint_stationarity_gate.py, and it is repeated
# here rather than imported so this file fails on its own evidence. It is
# deliberately NOT the full schema: the pair's own tickers, the spread series and
# the scan-owned fields below complete the accounting.
_PRE_GATE_LEAVES = (
    "engle_granger_pvalue",
    "engle_granger_tstat",
    "is_cointegrated",
    "hedge_ratio_beta",
    "intercept_alpha",
    "hedge_ratio_beta_std_error",
    "intercept_alpha_std_error",
    "hedge_regression_observations",
    "hedge_regression_std_error_basis",
    "ou_half_life_days",
    "ou_reversion_speed_theta",
    "current_spread_zscore",
    "johansen_cointegrated",
    "last_price_a",
    "last_price_b",
    "observation_date_a",
    "observation_date_b",
    "overlap_start",
    "overlap_end",
    "overlap_observations",
    "price_basis",
    "decision_test",
    "johansen_role",
    "johansen_agrees_with_decision",
)

# Every leaf of a delivered row that the SCAN is entitled to rewrite: the signal
# string (re-derived with the family attached) and the two depth fields it
# computes per pair. Everything else must survive the scan untouched.
_SCAN_OWNED_LEAVES = ("signal", "depth_ratio", "depth_status")

# The rest of the row: the two tickers that identify the pair and the spread
# series, which this scan does not produce (`include_spread_series=False`) and
# therefore must deliver as it was handed them.
_IDENTITY_LEAVES = ("ticker_a", "ticker_b", "spread_series")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _head(signal: Optional[str]) -> str:
    text = str(signal or "").strip()
    return text.split(" ", 1)[0] if text else ""


def _names_an_action(signal: Optional[str]) -> bool:
    return _head(signal) in _ACTION_TOKENS


def _business_index(periods: int = N) -> pd.DatetimeIndex:
    """`periods` business days ending on the last business day at or before now.

    The route derives `start`/`end` from `datetime.now()` and the scan derives
    its cache key from the last observation date, so a hard-dated index is a
    fixture that rots. Anchored to the clock instead: the newest bar is never in
    the future, and never drifts a year out of the requested window.
    """
    today = pd.Timestamp(datetime.now()).normalize()
    if today.weekday() >= 5:  # Saturday/Sunday: the last session is Friday.
        today = today - pd.offsets.BDay(1)
    return pd.bdate_range(end=today, periods=periods)


def _frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    """A strictly positive, non-degenerate price frame.

    The per-pair measurement is replaced in most tests below, so these prices
    are never analysed - they only have to give every ticker the same usable
    depth, which is what keeps `depth_status` at `available`.
    """
    steps = 100.0 + np.arange(len(index), dtype=float) * 0.5
    return pd.DataFrame({"close": steps}, index=index)


class _FakeMarket:
    """Serves one fixed frame per ticker; the requested window is ignored, so a
    test's price depth does not depend on the day the suite happens to run."""

    def __init__(self, frames: Dict[str, pd.DataFrame]):
        self.frames = dict(frames)

    async def fetch_historical_data(self, ticker: str, start: str, end: str):
        return self.frames.get(ticker, pd.DataFrame())


def _ar1(phi: float, sigma: float, start: float, seed: int, n: int) -> np.ndarray:
    """A stationary AR(1) around `start` - I(0) by construction, not by luck.

    Two independent stationary legs are the proof shape for the gate: a linear
    combination of stationary processes is stationary, so both legs still test
    I(0) however confident Engle-Granger is about the pair.
    """
    rng = np.random.default_rng(seed)
    shocks = rng.normal(0.0, sigma, n)
    out = np.empty(n, dtype=float)
    out[0] = start
    for i in range(1, n):
        out[i] = start + phi * (out[i - 1] - start) + shocks[i]
    return out


def _leg(ticker: str, verdict: str) -> Dict[str, Any]:
    """One leg dict in the shape the engine publishes, in the same vocabulary.

    The leg BLOCK is a fixture here (the ADF/KPSS arithmetic is guarded where
    the prices are, in test_p03_coint_stationarity_gate.py) but the numbers are
    kept mutually consistent - lags inside the ceiling the rule names, bandwidth
    equal to the rule applied to the observation count - so the wiring can be
    checked against a rule that could actually have produced them.
    """
    return {
        "ticker": ticker,
        "observations": N,
        "transform": "log_price",
        "alpha": STATIONARITY_ALPHA,
        "lag_rule": STATIONARITY_LAG_RULE,
        "adf_pvalue": 0.61,
        "adf_lags": 0,
        "kpss_pvalue": 0.0001,
        "kpss_bandwidth": kpss_bandwidth(N),
        "verdict": verdict,
        "reason": f"fixture leg measured {verdict}",
    }


# leg verdicts behind each pair-level gate, so a fixture pair is never an
# incoherent combination (a `both_legs_i1` gate with a stationary leg would be
# a state the engine cannot emit).
_GATE_LEG_VERDICTS = {
    STATIONARITY_GATE_PASSED: ("i1", "i1"),
    STATIONARITY_GATE_SPURIOUS: ("stationary", "i1"),
    STATIONARITY_GATE_UNRESOLVED: ("undetermined", "i1"),
}


def _pair(
    a: str = "AAA.NS",
    b: str = "BBB.NS",
    pvalue: float = 1e-9,
    *,
    is_coint: bool = True,
    johansen: bool = True,
    beta: float = 1.0,
    zscore: Optional[float] = -2.0,
    stationarity: str = STATIONARITY_GATE_PASSED,
) -> CointPairResult:
    leg_a_verdict, leg_b_verdict = _GATE_LEG_VERDICTS[stationarity]
    return CointPairResult(
        ticker_a=a,
        ticker_b=b,
        engle_granger_pvalue=pvalue,
        engle_granger_tstat=-3.5,
        is_cointegrated=is_coint,
        hedge_ratio_beta=beta,
        intercept_alpha=0.0,
        ou_half_life_days=10.0,
        ou_reversion_speed_theta=0.07,
        current_spread_zscore=zscore,
        hedge_ratio_beta_std_error=0.04,
        intercept_alpha_std_error=1.2,
        hedge_regression_observations=N,
        hedge_regression_std_error_basis=(
            "ols_standard_error_from_polyfit_covariance_df_n_minus_2"
        ),
        johansen_cointegrated=johansen,
        last_price_a=100.0,
        last_price_b=200.0,
        observation_date_a="2026-01-01",
        observation_date_b="2026-01-01",
        overlap_start="2026-01-01",
        overlap_end="2026-08-31",
        overlap_observations=N,
        signal="NEUTRAL",
        decision_test="engle_granger",
        johansen_role="diagnostic_only",
        johansen_agrees_with_decision=johansen == is_coint,
        stationarity_leg_a=_leg(a, leg_a_verdict),
        stationarity_leg_b=_leg(b, leg_b_verdict),
        stationarity_gate={
            "verdict": stationarity,
            "leg_a_verdict": leg_a_verdict,
            "leg_b_verdict": leg_b_verdict,
            "reason": f"fixture gate measured {stationarity}",
        },
    )


def _payload(response) -> Dict[str, Any]:
    """Exactly what the AI-context exporter serialises."""
    return json.loads(response.model_dump_json())


async def _route(
    tickers: str,
    frames: Dict[str, pd.DataFrame],
    *,
    rows: Optional[List[CointPairResult]] = None,
    p_value_threshold: float = 0.05,
) -> Dict[str, Any]:
    """Drive the real route and return its serialised payload.

    `rows` replaces the per-pair measurement with an ordered queue, so the
    family arithmetic is a property of the fixture rather than of sampled
    prices. The queue is popped in the service's own `combinations(sorted(...))`
    order and its length must equal the number of tests the scan ran, so a
    mis-sized universe fails loudly instead of silently reusing a row.
    """
    queue: List[CointPairResult] = list(rows or [])
    _IN_MEMORY_COINT_CACHE.clear()
    stack = []
    try:
        if rows is not None:
            expected = len(tickers.split(",")) * (len(tickers.split(",")) - 1) // 2
            assert len(queue) == expected, (
                f"the scan will run {expected} tests but the fixture supplies "
                f"{len(queue)} rows; the family size is the number of tests RUN"
            )

            def _next_row(**_kwargs) -> CointPairResult:
                return queue.pop(0)

            stack.append(patch.object(coint, "analyze_pair_cointegration", _next_row))
        for item in stack:
            item.start()
        with patch.object(analytics_mod, "CointegrationService", CointegrationService):
            response = await get_cointegration_pairs(
                tickers=tickers,
                lookback_days=252,
                p_value_threshold=p_value_threshold,
                max_half_life=None,
                include_spread_series=False,
                db=Mock(),
                data_service=_FakeMarket(frames),
                cache_service=None,
            )
        return _payload(response)
    finally:
        for item in reversed(stack):
            item.stop()
        _IN_MEMORY_COINT_CACHE.clear()


async def _scan(
    tickers: List[str], rows: List[CointPairResult]
) -> Dict[str, Any]:
    """A scan whose every pair is a fixture row, over equal-depth prices."""
    index = _business_index()
    frames = {ticker: _frame(index) for ticker in tickers}
    return await _route(",".join(tickers), frames, rows=rows)


# The two scans every divergence assertion is built on. Four tickers is the
# smallest universe where a declared positive can sit between alpha/m and alpha
# and still fail the correction, which is what keeps the family arithmetic
# load-bearing rather than accidental.
DIVERGENCE_TICKERS = ["A.NS", "B.NS", "C.NS", "D.NS"]
CLEAN_TICKERS = ["A.NS", "B.NS", "C.NS"]


def _divergence_rows() -> List[CointPairResult]:
    """Two gate-passed survivors, one spurious survivor, one undetermined
    survivor, and two declared positives that fail the correction.

    Every p-value that reaches `surviving_pairs` is 1e-9, so the survivor set is
    a property of the FIXTURE: two pairs the gate opened and two it did not, at
    the same confidence, from the same family.
    """
    return [
        _pair("A.NS", "B.NS", 1e-9, zscore=-2.0),
        _pair("A.NS", "C.NS", 1e-9, zscore=2.0),
        _pair(
            "A.NS", "D.NS", 1e-9, zscore=-2.5, stationarity=STATIONARITY_GATE_SPURIOUS
        ),
        _pair(
            "B.NS", "D.NS", 1e-9, zscore=2.5, stationarity=STATIONARITY_GATE_UNRESOLVED
        ),
        # 0.042007 is the audited ELECTCAST.NS/MCX.NS p-value: declared positive
        # at alpha=0.05, and nowhere near 0.05/6, so it fails the correction.
        _pair("B.NS", "C.NS", 0.042007, zscore=0.2),
        _pair("C.NS", "D.NS", 0.042007, zscore=-0.2),
    ]


def _clean_rows() -> List[CointPairResult]:
    return [
        _pair("A.NS", "B.NS", 1e-9, zscore=-2.0),
        _pair("A.NS", "C.NS", 1e-9, zscore=2.0),
        _pair("B.NS", "C.NS", 1e-9, zscore=-1.5),
    ]


def _sparse_family_rows() -> List[CointPairResult]:
    """Six tests, two declared positives, two survivors, two directives.

    `comparisons_made` (6) and `declared_positive_count` (2) are different
    numbers here, which is the only way a directive's `comparisons_made` can be
    distinguished from a mis-wired `declared_positive_count`: on a scan where
    every row is a declared positive the two coincide and a wrong field reads
    right. The family is the number of tests RUN, and the four negatives are
    what make it larger than the declared positives.
    """
    negative = _pair(is_coint=False, johansen=False, pvalue=0.5, zscore=0.1)
    return [
        _pair("A.NS", "B.NS", 1e-9, zscore=-2.0),
        _pair("A.NS", "C.NS", 1e-9, zscore=2.0),
        negative.model_copy(update={"ticker_a": "A.NS", "ticker_b": "D.NS"}),
        negative.model_copy(update={"ticker_a": "B.NS", "ticker_b": "C.NS"}),
        negative.model_copy(update={"ticker_a": "B.NS", "ticker_b": "D.NS"}),
        negative.model_copy(update={"ticker_a": "C.NS", "ticker_b": "D.NS"}),
    ]


# ---------------------------------------------------------------------------
# 1. The directive restates the gate
# ---------------------------------------------------------------------------


class TestTheDirectiveCarriesTheGate:
    async def test_the_three_keys_sit_next_to_johansen_agrees_with_decision(self):
        payload = await _scan(CLEAN_TICKERS, _clean_rows())
        assert payload["directive_count"] == 3
        for entry in payload["directives"]:
            assert "johansen_agrees_with_decision" in entry
            for key in _DIRECTIVE_GATE_KEYS:
                assert key in entry, (key, sorted(entry))
                assert entry[key] is not None, key

    async def test_a_directives_gate_verdict_is_always_both_legs_i1(self):
        """The invariant the placement exists to express.

        A directive is an instruction to trade, and it can only be reached when
        the gate passed. So a directive's `stationarity_gate.verdict` is not one
        value among three - it is `both_legs_i1` or the payload is
        self-contradicting. Asserted over a scan that contains all three gate
        verdicts at once, so a regression that lets a rejected pair publish a
        directive cannot hide among the passing ones.
        """
        payload = await _scan(DIVERGENCE_TICKERS, _divergence_rows())
        verdicts = [
            d["stationarity_gate"]["verdict"] for d in payload["directives"]
        ]
        assert verdicts, "the scan must publish at least one directive"
        assert set(verdicts) == {STATIONARITY_GATE_PASSED}
        assert STATIONARITY_GATE_PASSED == "both_legs_i1"
        # The same pair of legs, the same verdict, stated twice: once at the
        # pair level and once per leg. A reader that checks only one of them is
        # checking the same claim.
        for entry in payload["directives"]:
            gate = entry["stationarity_gate"]
            assert gate["leg_a_verdict"] == entry["stationarity_leg_a"]["verdict"]
            assert gate["leg_b_verdict"] == entry["stationarity_leg_b"]["verdict"]
            assert gate["leg_a_verdict"] == "i1"
            assert gate["leg_b_verdict"] == "i1"

    async def test_each_leg_carries_its_evidence_and_its_own_ticker(self):
        payload = await _scan(CLEAN_TICKERS, _clean_rows())
        for entry in payload["directives"]:
            for side, ticker in (
                ("stationarity_leg_a", entry["ticker_a"]),
                ("stationarity_leg_b", entry["ticker_b"]),
            ):
                leg = entry[side]
                for key in (
                    "adf_pvalue",
                    "kpss_pvalue",
                    "adf_lags",
                    "kpss_bandwidth",
                    "lag_rule",
                    "verdict",
                    "reason",
                ):
                    assert key in leg, (side, key, sorted(leg))
                assert leg["ticker"] == ticker
                assert isinstance(leg["adf_pvalue"], float)
                assert isinstance(leg["kpss_pvalue"], float)
                assert isinstance(leg["adf_lags"], int)
                assert isinstance(leg["kpss_bandwidth"], int)
                assert leg["verdict"] == "i1"
                assert leg["reason"]

    async def test_a_gate_rejected_survivor_publishes_no_directive(self):
        """The other half of the invariant: the withheld pair is delivered,
        counted and published - just not as an order. Asserted so the test above
        cannot pass by a route that simply stopped publishing directives.
        """
        payload = await _scan(DIVERGENCE_TICKERS, _divergence_rows())
        named = {(d["ticker_a"], d["ticker_b"]) for d in payload["directives"]}
        assert ("A.NS", "D.NS") not in named  # spurious
        assert ("B.NS", "D.NS") not in named  # undetermined
        assert len(payload["directives"]) == 2
        delivered = {(p["ticker_a"], p["ticker_b"]): p for p in payload["pairs"]}
        assert delivered[("A.NS", "D.NS")]["stationarity_gate"]["verdict"] == (
            STATIONARITY_GATE_SPURIOUS
        )
        assert delivered[("B.NS", "D.NS")]["stationarity_gate"]["verdict"] == (
            STATIONARITY_GATE_UNRESOLVED
        )


# ---------------------------------------------------------------------------
# 2. The rule is stated, and it is the rule that was used
# ---------------------------------------------------------------------------


class TestTheSignalPolicyStatesTheRule:
    async def test_the_four_keys_are_published(self):
        payload = await _scan(CLEAN_TICKERS, _clean_rows())
        policy = payload["signal_policy"]
        for key in _SIGNAL_POLICY_GATE_KEYS:
            assert key in policy, (key, sorted(policy))
        assert policy["stationarity_gate_rule"]
        assert policy["stationarity_lag_rule"] == STATIONARITY_LAG_RULE
        assert policy["stationarity_alpha"] == STATIONARITY_ALPHA == 0.05
        assert set(policy["stationarity_withholding_heads"]) == {
            SIGNAL_SPURIOUS,
            SIGNAL_STATIONARITY_UNDETERMINED,
        }

    async def test_gate_rule_names_the_stationarity_rung(self):
        """`gate_rule` is the sentence that says what a signal has to clear. A
        verdict beside a rule that does not mention the stationarity rung is a
        verdict with no stated criterion, which is the thing this item exists to
        prevent."""
        payload = await _scan(CLEAN_TICKERS, _clean_rows())
        gate_rule = payload["signal_policy"]["gate_rule"].lower()
        assert "stationarity" in gate_rule
        assert "both legs" in gate_rule
        # And the rule still names the pre-existing rungs: extending it must not
        # have replaced it.
        assert MULTIPLICITY_CORRECTION in gate_rule
        assert payload["signal_policy"]["gate"] == MULTIPLICITY_CORRECTION

    async def test_the_published_lag_rule_is_the_one_the_legs_were_produced_under(
        self,
    ):
        """Not "the string is present" - the resolved numbers must be
        consistent with the rule, so a reader can re-derive the test rather than
        trust it. `arch`'s own default here is Schwert's ceil(12*(n/100)**0.25)
        = 14 candidate lags at n=174, derived for monthly macro series; a
        payload that published 14-lag p-values under a `max_lags=1` rule would
        be exactly the unstateable gate this item rules out.
        """
        payload = await _scan(CLEAN_TICKERS, _clean_rows())
        policy = payload["signal_policy"]
        rule = policy["stationarity_lag_rule"]
        assert "adf:max_lags=1" in rule
        assert "lag_selection=aic" in rule
        assert "trend=c" in rule
        assert "transform=log_price" in rule
        # The ceiling the rule names, and the ceiling every published leg obeys.
        assert 12.0 * (N / 100.0) ** 0.25 > 1.0
        for entry in payload["directives"]:
            for side in ("stationarity_leg_a", "stationarity_leg_b"):
                leg = entry[side]
                assert leg["lag_rule"] == rule, side
                assert leg["adf_lags"] <= 1, side
                assert leg["kpss_bandwidth"] == kpss_bandwidth(leg["observations"])
                assert leg["transform"] == "log_price"
                assert leg["alpha"] == policy["stationarity_alpha"]

    async def test_a_measured_scan_publishes_the_same_rule_on_every_leg(self):
        """The same invariant with real ADF/KPSS output rather than a fixture:
        the leg p-values on the wire were produced under the rule the policy
        publishes."""
        index = _business_index()
        rng = np.random.default_rng(11)
        steps = np.cumsum(rng.normal(0.0004, 0.011, len(index)))
        leg_a = 100.0 * np.exp(steps)
        leg_b = 1.4 * leg_a + np.cumsum(rng.normal(0.0, 0.30, len(index))) + 8.0
        frames = {
            "AAA.NS": pd.DataFrame({"close": leg_a}, index=index),
            "BBB.NS": pd.DataFrame({"close": leg_b}, index=index),
        }
        payload = await _route("AAA.NS,BBB.NS", frames)
        policy = payload["signal_policy"]
        assert policy["stationarity_lag_rule"] == STATIONARITY_LAG_RULE
        row = payload["pairs"][0]
        assert row["stationarity_gate"]["verdict"] == STATIONARITY_GATE_PASSED
        for side in ("stationarity_leg_a", "stationarity_leg_b"):
            leg = row[side]
            assert leg["lag_rule"] == policy["stationarity_lag_rule"], side
            assert leg["adf_lags"] in (0, 1), side
            assert leg["kpss_bandwidth"] == kpss_bandwidth(leg["observations"])
            assert leg["adf_pvalue"] is not None and leg["kpss_pvalue"] is not None
            assert 0.0 <= leg["adf_pvalue"] <= 1.0
            assert 0.0 <= leg["kpss_pvalue"] <= 1.0

    async def test_the_withholding_heads_are_the_heads_the_rows_actually_carry(
        self,
    ):
        """The policy must name the tokens the payload emits, not a near-miss
        spelling of them. Run on the divergence scan, where BOTH heads are
        actually published, so this is a statement about the emitted vocabulary
        rather than about a declared one."""
        payload = await _scan(DIVERGENCE_TICKERS, _divergence_rows())
        declared = set(
            payload["signal_policy"]["stationarity_withholding_heads"]
        )
        assert declared == {SIGNAL_SPURIOUS, SIGNAL_STATIONARITY_UNDETERMINED}
        emitted = {_head(row["signal"]) for row in payload["pairs"]}
        assert declared <= emitted


# ---------------------------------------------------------------------------
# 3. The two withholding counts
# ---------------------------------------------------------------------------


class TestTheWithholdingCountsArePublished:
    async def test_both_counts_sit_beside_contested_pair_count(self):
        payload = await _scan(DIVERGENCE_TICKERS, _divergence_rows())
        assert payload["contested_pair_count"] == 0
        assert payload["spurious_regression_rejected_count"] == 1
        assert payload["stationarity_undetermined_count"] == 1

    async def test_the_counts_are_counted_off_the_published_signal_heads(self):
        """Re-derived from the payload's own rows, so a count that drifted from
        the signals it describes fails here rather than being self-consistent
        with a second derivation that drifted too."""
        payload = await _scan(DIVERGENCE_TICKERS, _divergence_rows())
        heads = [_head(row["signal"]) for row in payload["pairs"]]
        assert heads.count(SIGNAL_SPURIOUS) == payload[
            "spurious_regression_rejected_count"
        ]
        assert heads.count(SIGNAL_STATIONARITY_UNDETERMINED) == payload[
            "stationarity_undetermined_count"
        ]
        # And the two gate counts plus the pre-existing contested count account
        # for the withheld rows the gate did not cause; the rest failed the
        # family correction, which has its own head and its own count
        # (`survivor_count`). The two new counts are additive, not a rewrite of
        # `directive_withheld_count`.
        assert payload["directive_withheld_count"] == 4
        assert (
            payload["contested_pair_count"]
            + payload["spurious_regression_rejected_count"]
            + payload["stationarity_undetermined_count"]
            + heads.count("UNCONFIRMED_AFTER_MULTIPLE_TESTING_CORRECTION")
        ) == payload["directive_withheld_count"]

    async def test_a_clean_scan_publishes_two_zeroes_not_absent_keys(self):
        payload = await _scan(CLEAN_TICKERS, _clean_rows())
        assert payload["spurious_regression_rejected_count"] == 0
        assert payload["stationarity_undetermined_count"] == 0
        assert payload["directive_withheld_count"] == 0
        # The negative half of the THIRD count too. A counter that only exists
        # when it fires is a counter nobody can read the absence of.
        assert payload["diagnostic_unavailable_count"] == 0

    async def test_a_measured_spurious_pair_is_counted_on_the_wire(self):
        """The counts are not a fixture artefact: a real scan of two stationary
        legs that Engle-Granger calls cointegrated reports exactly one spurious
        rejection and publishes no directive."""
        index = _business_index()
        leg_a = _ar1(0.30, 1.0, 100.0, 22, len(index))
        leg_b = 1.5 * leg_a + 12.0 + _ar1(0.30, 0.6, 0.0, 22 + 90000, len(index))
        frames = {
            "STAT_A.NS": pd.DataFrame({"close": leg_a}, index=index),
            "STAT_B.NS": pd.DataFrame({"close": leg_b}, index=index),
        }
        payload = await _route("STAT_A.NS,STAT_B.NS", frames)
        row = payload["pairs"][0]
        assert row["is_cointegrated"] is True
        assert row["engle_granger_pvalue"] < 0.05
        assert _head(row["signal"]) == SIGNAL_SPURIOUS
        assert payload["spurious_regression_rejected_count"] == 1
        assert payload["stationarity_undetermined_count"] == 0
        assert payload["directive_count"] == 0
        assert payload["directives"] == []


# ---------------------------------------------------------------------------
# 4. data_status: demoted on a withholding, NOT demoted without one
# ---------------------------------------------------------------------------


class TestDataStatusDemotion:
    @pytest.mark.parametrize(
        "gate,expected_count",
        [
            (STATIONARITY_GATE_SPURIOUS, "spurious_regression_rejected_count"),
            (STATIONARITY_GATE_UNRESOLVED, "stationarity_undetermined_count"),
        ],
    )
    async def test_a_single_withholding_demotes_the_scan(self, gate, expected_count):
        """One withheld pair, one test in the family. No shallow history, no
        missing ticker, no unpairable ticker: if the scan is not `partial` here
        then nothing demoted it, because there was nothing else to."""
        payload = await _scan(
            ["A.NS", "B.NS"], [_pair("A.NS", "B.NS", 1e-9, stationarity=gate)]
        )
        # The negative half's preconditions, asserted so a `partial` from some
        # OTHER cause cannot be mistaken for the gate's.
        assert payload["shallow_tickers"] == []
        assert payload["depth_status"] == "available"
        assert payload["unpairable_tickers"] == []
        assert payload["universe_coverage"]["status"] == "complete"
        assert payload["multiple_testing"]["survivor_count"] == 1
        assert payload[expected_count] == 1
        assert payload["data_status"] == "partial"

    async def test_a_scan_that_withheld_nothing_is_available(self):
        """The half nobody writes. A demotion that fires on clean scans is
        noise, and noise trains a reader to ignore the field - which is how the
        real degradation goes unread."""
        payload = await _scan(CLEAN_TICKERS, _clean_rows())
        assert payload["spurious_regression_rejected_count"] == 0
        assert payload["stationarity_undetermined_count"] == 0
        assert payload["shallow_tickers"] == []
        assert payload["depth_status"] == "available"
        assert payload["unpairable_tickers"] == []
        assert payload["universe_coverage"]["status"] == "complete"
        assert payload["directive_count"] == 3
        assert payload["multiple_testing"]["survivor_count"] == 3
        assert payload["data_status"] == "available"

    async def test_a_surviving_negative_family_is_not_untouched_by_the_gate(self):
        """A scan of three negatives withholds nothing, and the pre-existing
        multiplicity demotion - declared positives that survive nothing - is the
        only thing that may make it `partial`. It is not the gate's doing, and
        this asserts the gate stays out of it."""
        payload = await _scan(
            CLEAN_TICKERS,
            [
                _pair("A.NS", "B.NS", 0.42, is_coint=False, johansen=False, zscore=0.1),
                _pair("A.NS", "C.NS", 0.55, is_coint=False, johansen=False, zscore=0.1),
                _pair("B.NS", "C.NS", 0.61, is_coint=False, johansen=False, zscore=0.1),
            ],
        )
        assert payload["spurious_regression_rejected_count"] == 0
        assert payload["stationarity_undetermined_count"] == 0
        assert payload["multiple_testing"]["declared_positive_count"] == 0
        assert payload["data_status"] == "available"


# ---------------------------------------------------------------------------
# 5. surviving_pairs vs actionable_pairs
# ---------------------------------------------------------------------------


class TestSurvivingIsNotTheSameAsActionable:
    async def test_a_gate_rejected_survivor_splits_the_two_counts(self):
        """The case that makes item 5 carry any information at all.

        Four pairs clear the family correction at the same confidence; the gate
        opens two of them. `surviving_pairs` is a p-value measurement and keeps
        all four; `actionable_pairs_count` is that set intersected with the rows
        whose recorded gate passed, and is two.
        """
        payload = await _scan(DIVERGENCE_TICKERS, _divergence_rows())
        family = payload["multiple_testing"]
        assert family["survivor_count"] == 4
        assert family["actionable_pairs_count"] == 2
        assert family["surviving_pairs"] == [
            "A.NS/B.NS",
            "A.NS/C.NS",
            "A.NS/D.NS",
            "B.NS/D.NS",
        ]
        # Strictly less, and the gap is exactly the gate-rejected survivors.
        assert family["actionable_pairs_count"] < family["survivor_count"]
        rejected = {
            key
            for key, row in zip(family["surviving_pairs"], _divergence_rows())
            if row.stationarity_gate["verdict"] != STATIONARITY_GATE_PASSED
        }
        assert rejected == {"A.NS/D.NS", "B.NS/D.NS"}
        assert (
            family["survivor_count"] - family["actionable_pairs_count"]
            == len(rejected)
            == payload["spurious_regression_rejected_count"]
            + payload["stationarity_undetermined_count"]
        )

    async def test_actionable_never_exceeds_surviving(self):
        payload = await _scan(DIVERGENCE_TICKERS, _divergence_rows())
        family = payload["multiple_testing"]
        assert family["actionable_pairs_count"] <= family["survivor_count"]
        assert family["actionable_pairs_count"] == payload["directive_count"]
        assert family["actionable_pairs_count"] <= len(payload["directives"])

    async def test_the_counts_are_equal_when_the_gate_passes_everything(self):
        payload = await _scan(CLEAN_TICKERS, _clean_rows())
        family = payload["multiple_testing"]
        assert family["survivor_count"] == 3
        assert family["actionable_pairs_count"] == family["survivor_count"]
        assert family["actionable_pairs_basis"]

    @pytest.mark.parametrize(
        "rejected,expected_survivors,expected_actionable",
        [
            # Nothing rejected: the counts are equal, and the fixture is not the
            # only thing that could make them so (see the two cases below).
            ([], 2, 2),
            ([("A.NS", "B.NS", STATIONARITY_GATE_SPURIOUS)], 2, 1),
            ([("A.NS", "B.NS", STATIONARITY_GATE_UNRESOLVED)], 2, 1),
            (
                [
                    ("A.NS", "B.NS", STATIONARITY_GATE_SPURIOUS),
                    ("B.NS", "C.NS", STATIONARITY_GATE_UNRESOLVED),
                ],
                2,
                0,
            ),
        ],
    )
    async def test_the_gap_equals_the_gate_rejected_survivors_exactly(
        self, rejected, expected_survivors, expected_actionable
    ):
        """Each withholding head moves the gap on its own, and a scan in which
        the gate rejects EVERY survivor lands on zero rather than on a negative
        or an invented value.

        A three-ticker universe where two rows clear a corrected threshold of
        0.05/3 and a third fails it, so the survivor set is a property of the
        FIXTURE and the only thing that can move the gap here is the gate - which
        is the claim.
        """
        gated = {f"{a}/{b}": gate for a, b, gate in rejected}
        rows = [
            _pair("A.NS", "B.NS", 1e-9, stationarity=gated.get("A.NS/B.NS", STATIONARITY_GATE_PASSED)),
            _pair("B.NS", "C.NS", 1e-9, stationarity=gated.get("B.NS/C.NS", STATIONARITY_GATE_PASSED)),
            _pair("A.NS", "C.NS", 0.042007, zscore=0.1),
        ]
        payload = await _scan(["A.NS", "B.NS", "C.NS"], rows)
        family = payload["multiple_testing"]
        assert family["comparisons_made"] == 3
        assert family["corrected_threshold"] == pytest.approx(0.05 / 3)
        assert family["survivor_count"] == expected_survivors
        assert family["actionable_pairs_count"] == expected_actionable
        assert family["survivor_count"] - family["actionable_pairs_count"] == (
            expected_survivors - expected_actionable
        )
        assert family["actionable_pairs_count"] == payload["directive_count"]

    async def test_actionable_pairs_basis_names_both_measurements(self):
        payload = await _scan(DIVERGENCE_TICKERS, _divergence_rows())
        basis = payload["multiple_testing"]["actionable_pairs_basis"]
        assert "surviving_pairs" in basis
        assert STATIONARITY_GATE_PASSED in basis

    async def test_the_count_fails_closed_when_the_route_cannot_read_the_gate(self):
        """A gate the route cannot see yields NO actionable pairs, never all of
        them. `stationarity_gate_of` is the one seam between the engine's
        verdict and this count, so it is where a silent break would land - and
        the safe direction for that break is zero.

        This is also the teeth of the guard: with the same patch the pre-wiring
        payload had no `actionable_pairs_count` at all, so a reader counting
        survivors would have counted the spurious pair as tradeable.
        """
        _IN_MEMORY_COINT_CACHE.clear()
        try:
            with patch.object(coint, "stationarity_gate_of", lambda _pair: None):
                payload = await _scan(DIVERGENCE_TICKERS, _divergence_rows())
        finally:
            _IN_MEMORY_COINT_CACHE.clear()
        family = payload["multiple_testing"]
        assert family["survivor_count"] == 4
        assert family["actionable_pairs_count"] == 0
        assert family["actionable_pairs_count"] < family["survivor_count"]


# ---------------------------------------------------------------------------
# Nothing else moved
# ---------------------------------------------------------------------------


class TestNothingElseMoved:
    async def test_multiple_testing_is_the_pre_wiring_block_plus_two_keys(self):
        """The pre-wiring block, re-derived from the engine, byte for byte.

        `multiplicity_report` is the same function the route calls, on the same
        rows with the same family size, so anything the wiring did to the block
        beyond adding the two keys shows up as a diff.
        """
        rows = _divergence_rows()
        payload = await _scan(DIVERGENCE_TICKERS, rows)
        baseline = multiplicity_report(
            rows, family_alpha=0.05, comparisons_made=len(DIVERGENCE_TICKERS) * 3 // 2
        )
        family = payload["multiple_testing"]
        assert set(family) - set(baseline) == {
            "actionable_pairs_count",
            "actionable_pairs_basis",
        }
        assert not set(baseline) - set(family)
        for key, value in baseline.items():
            assert family[key] == value, key
        # And the two blocks the family arithmetic publishes most concretely.
        assert family["bonferroni"] == baseline["bonferroni"]
        assert family["benjamini_hochberg_fdr"] == baseline["benjamini_hochberg_fdr"]
        assert family["corrected_threshold"] == pytest.approx(0.05 / 6)
        assert family["gate"] == MULTIPLICITY_CORRECTION
        # Bonferroni keeps 4 of the 6 declared positives; BH-FDR, computed over
        # delivered rows only, keeps all 6. The two blocks are distinguishable
        # and the wiring changed neither.
        assert family["bonferroni"]["survivor_count"] == 4
        assert family["benjamini_hochberg_fdr"]["survivor_count"] == 6

    async def test_every_directive_key_outside_the_gate_is_unchanged(self):
        """Run on the sparse family (6 tests, 2 declared positives) so a
        directive's `comparisons_made` is 6 and a mis-wired
        `declared_positive_count` would read 2: on an all-positive scan the two
        numbers coincide and the assertion would pass for the wrong reason."""
        rows = _sparse_family_rows()
        payload = await _scan(DIVERGENCE_TICKERS, rows)
        by_key = {f"{r.ticker_a}/{r.ticker_b}": r for r in rows}
        family = payload["multiple_testing"]
        assert family["comparisons_made"] == 6
        assert family["declared_positive_count"] == 2
        assert payload["directive_count"] == 2
        for entry in payload["directives"]:
            fixture = by_key[f"{entry['ticker_a']}/{entry['ticker_b']}"]
            assert set(entry) - set(_DIRECTIVE_GATE_KEYS) == {
                "ticker_a",
                "ticker_b",
                "direction",
                "engle_granger_pvalue",
                "decision_test",
                "diagnostic_test",
                "johansen_agrees_with_decision",
                "comparisons_made",
                "correction_applied",
                "corrected_p_value_threshold",
                "survives_correction",
                "spread_zscore",
                "zscore_threshold",
                "hedge_ratio_beta",
                "notional_convention",
                "overlap_observations",
                "depth_status",
                "ou_half_life_days",
            }
            # The pre-existing chain, unchanged: the gate keys are additive.
            assert entry["engle_granger_pvalue"] == fixture.engle_granger_pvalue
            assert entry["johansen_agrees_with_decision"] is True
            assert entry["comparisons_made"] == 6
            assert entry["correction_applied"] == MULTIPLICITY_CORRECTION
            assert entry["corrected_p_value_threshold"] == pytest.approx(0.05 / 6)
            assert entry["survives_correction"] is True
            assert entry["hedge_ratio_beta"] == fixture.hedge_ratio_beta
            assert entry["spread_zscore"] == fixture.current_spread_zscore
            assert entry["overlap_observations"] == N
            assert entry["depth_status"] == "available"
            assert entry["ou_half_life_days"] == fixture.ou_half_life_days

    async def test_directive_and_contested_counts_are_the_pre_wiring_arithmetic(self):
        payload = await _scan(DIVERGENCE_TICKERS, _divergence_rows())
        assert payload["directive_count"] == 2
        assert payload["directive_withheld_count"] == 4
        assert payload["contested_pair_count"] == 0
        assert (
            payload["directive_count"] + payload["directive_withheld_count"]
            == payload["returned_pairs_count"]
        )
        # Four withheld: two stationarity, two that failed the correction.
        heads = [_head(row["signal"]) for row in payload["pairs"]]
        assert heads.count("UNCONFIRMED_AFTER_MULTIPLE_TESTING_CORRECTION") == 2

    async def test_contested_rung_still_fires_ahead_of_the_gate_count(self):
        payload = await _scan(
            CLEAN_TICKERS,
            [
                _pair("A.NS", "B.NS", 1e-9, johansen=False, zscore=-2.0),
                _pair("A.NS", "C.NS", 1e-9),
                _pair("B.NS", "C.NS", 1e-9),
            ],
        )
        assert payload["contested_pair_count"] == 1
        assert payload["spurious_regression_rejected_count"] == 0
        assert payload["stationarity_undetermined_count"] == 0
        assert payload["directive_count"] == 2
        assert payload["data_status"] == "available"

    async def test_no_pair_row_gained_or_lost_a_key(self):
        rows = _divergence_rows()
        payload = await _scan(DIVERGENCE_TICKERS, rows)
        by_key = {f"{r.ticker_a}/{r.ticker_b}": r for r in rows}
        for row in payload["pairs"]:
            fixture = by_key[f"{row['ticker_a']}/{row['ticker_b']}"]
            assert set(row) == set(fixture.model_dump())

    async def test_every_pair_leaf_outside_the_gate_is_byte_identical(self):
        rows = _divergence_rows()
        payload = await _scan(DIVERGENCE_TICKERS, rows)
        by_key = {f"{r.ticker_a}/{r.ticker_b}": r for r in rows}
        for row in payload["pairs"]:
            fixture = by_key[f"{row['ticker_a']}/{row['ticker_b']}"]
            # Every leaf is accounted for: the pre-gate ones byte-identical, the
            # three gate keys added, and the three the scan owns recomputed.
            # A key that falls into none of those three groups is unaccounted
            # for, and `test_no_pair_row_gained_or_lost_a_key` is what catches it.
            assert set(row) == set(_PRE_GATE_LEAVES) | set(
                _DIRECTIVE_GATE_KEYS
            ) | set(_SCAN_OWNED_LEAVES) | set(_IDENTITY_LEAVES)
            for name in _PRE_GATE_LEAVES:
                assert row[name] == getattr(fixture, name), (name, row[name])
            # The three gate keys ARE expected on the row; they are the point.
            for name in _DIRECTIVE_GATE_KEYS:
                assert row[name] is not None, name
            # And the scan's own two fields, plus a signal derived from the same
            # family the row was queued for.
            assert row["depth_ratio"] == 1.0
            assert row["depth_status"] == "available"
            assert row["signal"] == build_pair_signal(
                fixture, family_alpha=0.05, comparisons_made=6
            )

    async def test_a_measured_pair_row_keeps_every_pre_gate_leaf(self):
        """The same byte-identity claim on a real measurement rather than a
        fixture, so it cannot pass merely because the fixture was complete."""
        index = _business_index()
        rng = np.random.default_rng(11)
        leg_a = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.011, len(index))))
        leg_b = 1.4 * leg_a + np.cumsum(rng.normal(0.0, 0.30, len(index))) + 8.0
        frames = {
            "AAA.NS": pd.DataFrame({"close": leg_a}, index=index),
            "BBB.NS": pd.DataFrame({"close": leg_b}, index=index),
        }
        payload = await _route("AAA.NS,BBB.NS", frames)
        row = payload["pairs"][0]
        assert row["decision_test"] == "engle_granger"
        assert row["johansen_role"] == "diagnostic_only"
        assert row["is_cointegrated"] is (row["engle_granger_pvalue"] < 0.05)
        assert row["johansen_agrees_with_decision"] is (
            row["johansen_cointegrated"] == row["is_cointegrated"]
        )
        assert row["overlap_observations"] == len(index)
        assert row["hedge_regression_observations"] is not None
        for name in _PRE_GATE_LEAVES:
            assert name in row, name


# ---------------------------------------------------------------------------
# 6. The gate VERDICT total and the gate WITHHOLDING count are two facts
# ---------------------------------------------------------------------------


def _verdicts_off_the_rows(payload: Dict[str, Any]) -> Dict[str, int]:
    """Re-derived from the payload's own rows, so a published total that
    drifted from the verdicts it describes fails here rather than being
    self-consistent with a second derivation that drifted too."""
    counted: Dict[str, int] = {}
    for row in payload["pairs"]:
        verdict = (row.get("stationarity_gate") or {}).get("verdict")
        counted[verdict] = counted.get(verdict, 0) + 1
    return counted


def _never_candidate_rows() -> List[CointPairResult]:
    """The 12-vs-1 shape, built rather than narrated.

    A real export (v28, 91 rows, alpha=0.05) published
    `spurious_regression_rejected_count: 1` while twelve delivered rows carried
    the `spurious_regression_rejected` verdict - ELECTCAST.NS measures
    stationary, so it forms eleven pairs the gate also rejects, and eleven of
    those twelve had p >= 0.10 and were never cointegrated at all.

    So the aggregate counted something real and different from what its own key
    name said, and a reader could count the rows to a different number with no
    way to reconcile the two. This fixture reproduces the shape: four rows carry
    the spurious verdict, and exactly one of them was decision-positive.
    """
    never_candidate = _pair(
        pvalue=0.5, is_coint=False, johansen=False, stationarity=STATIONARITY_GATE_SPURIOUS
    )
    # Labelled in the scan's own `combinations(sorted(...))` order, so each
    # fixture row lands in the slot its tickers name.
    return [
        _pair("A.NS", "B.NS", 1e-9, zscore=-2.0),
        _pair("A.NS", "C.NS", 1e-9, zscore=2.0),
        _pair(
            "A.NS", "D.NS", 1e-9, zscore=-2.5, stationarity=STATIONARITY_GATE_SPURIOUS
        ),
        never_candidate.model_copy(update={"ticker_a": "B.NS", "ticker_b": "C.NS"}),
        never_candidate.model_copy(update={"ticker_a": "B.NS", "ticker_b": "D.NS"}),
        never_candidate.model_copy(update={"ticker_a": "C.NS", "ticker_b": "D.NS"}),
    ]


class TestTheVerdictTotalAndTheWithholdingCountAreTwoFacts:
    async def test_both_numbers_are_published_and_they_disagree_without_contradicting(self):
        payload = await _scan(DIVERGENCE_TICKERS, _never_candidate_rows())
        counts = payload["stationarity_gate_verdict_counts"]
        # What a reader counts off the rows...
        assert counts[STATIONARITY_GATE_SPURIOUS] == 4
        assert _verdicts_off_the_rows(payload)[STATIONARITY_GATE_SPURIOUS] == 4
        # ...and what the gate actually withheld from a candidate.
        assert payload["spurious_regression_rejected_count"] == 1
        assert payload["spurious_regression_rejected_count"] < counts[
            STATIONARITY_GATE_SPURIOUS
        ]
        # The gap is exactly the rows that were never cointegrated, so the two
        # numbers reconcile without either being wrong.
        assert counts[STATIONARITY_GATE_SPURIOUS] - payload[
            "spurious_regression_rejected_count"
        ] == sum(1 for row in payload["pairs"] if row["signal"].startswith("NOT_COINTEGRATED"))

    async def test_the_verdict_totals_are_countable_and_sum_to_the_delivered_rows(self):
        payload = await _scan(DIVERGENCE_TICKERS, _never_candidate_rows())
        counts = payload["stationarity_gate_verdict_counts"]
        counted = _verdicts_off_the_rows(payload)
        assert set(counts) == {
            STATIONARITY_GATE_PASSED,
            STATIONARITY_GATE_SPURIOUS,
            STATIONARITY_GATE_UNRESOLVED,
            "not_recorded",
        }
        for token, total in counts.items():
            assert total == counted.get(token, 0), token
        assert sum(counts.values()) == payload["returned_pairs_count"]

    async def test_each_basis_names_its_own_scope(self):
        """A number whose scope is unstated is a number a reader has to guess
        at, and the guess that is wrong here is the one the key name invites."""
        payload = await _scan(DIVERGENCE_TICKERS, _never_candidate_rows())
        spurious_basis = payload["spurious_regression_rejected_count_basis"]
        assert SIGNAL_SPURIOUS in spurious_basis
        assert "NOT_COINTEGRATED" in spurious_basis
        assert STATIONARITY_GATE_SPURIOUS in spurious_basis
        undetermined_basis = payload["stationarity_undetermined_count_basis"]
        assert SIGNAL_STATIONARITY_UNDETERMINED in undetermined_basis
        assert "NOT_COINTEGRATED" in undetermined_basis
        # And the total says what it is a total OF, and how the two relate.
        total_basis = payload["stationarity_gate_verdict_counts_basis"]
        assert "all delivered rows" in total_basis
        assert "spurious_regression_rejected_count" in total_basis
        assert "stationarity_undetermined_count" in total_basis

    async def test_the_withholding_count_is_unchanged_and_still_the_survivor_gap(self):
        """The count keeps its meaning. It is the term in
        `survivor_count - actionable_pairs_count == withheld`, and
        `surviving_pairs` is a subset of the declared positives, so the identity
        only holds for a decision-positive count. Republishing it as the row
        total would have made this false on every real scan that withholds
        nothing."""
        rows = _never_candidate_rows()
        payload = await _scan(DIVERGENCE_TICKERS, rows)
        family = payload["multiple_testing"]
        rejected_survivors = {
            f"{row['ticker_a']}/{row['ticker_b']}"
            for row in payload["pairs"]
            if row["stationarity_gate"]["verdict"] != STATIONARITY_GATE_PASSED
            and f"{row['ticker_a']}/{row['ticker_b']}" in family["surviving_pairs"]
        }
        assert rejected_survivors == {"A.NS/D.NS"}
        assert family["survivor_count"] - family["actionable_pairs_count"] == len(
            rejected_survivors
        ) == payload["spurious_regression_rejected_count"] + payload[
            "stationarity_undetermined_count"
        ]

    async def test_a_clean_scan_publishes_four_zeroes_not_absent_keys(self):
        payload = await _scan(CLEAN_TICKERS, _clean_rows())
        counts = payload["stationarity_gate_verdict_counts"]
        assert counts == {
            STATIONARITY_GATE_PASSED: 3,
            STATIONARITY_GATE_SPURIOUS: 0,
            STATIONARITY_GATE_UNRESOLVED: 0,
            "not_recorded": 0,
        }
        assert payload["spurious_regression_rejected_count"] == 0
        assert payload["stationarity_undetermined_count"] == 0
        assert payload["data_status"] == "available"

    async def test_the_demotion_fires_on_the_withholding_not_the_verdict_total(self):
        """The sharp half. Here the gate rejected four rows' legs and withheld
        nothing, because none of the four was ever a candidate - and the scan is
        still `available`. A demotion moved onto the verdict total would have
        fired here, and would then have fired on every scan containing one
        stationary series in the universe, which is a universe fact and not a
        statement about this scan's conclusions."""
        rows = [
            _pair(
                "A.NS",
                "B.NS",
                0.5,
                is_coint=False,
                johansen=False,
                stationarity=STATIONARITY_GATE_SPURIOUS,
            ),
            _pair("A.NS", "C.NS", 0.5, is_coint=False, johansen=False),
            _pair(
                "B.NS",
                "C.NS",
                0.5,
                is_coint=False,
                johansen=False,
                stationarity=STATIONARITY_GATE_UNRESOLVED,
            ),
        ]
        payload = await _scan(CLEAN_TICKERS, rows)
        counts = payload["stationarity_gate_verdict_counts"]
        assert counts[STATIONARITY_GATE_SPURIOUS] == 1
        assert counts[STATIONARITY_GATE_UNRESOLVED] == 1
        assert payload["spurious_regression_rejected_count"] == 0
        assert payload["stationarity_undetermined_count"] == 0
        # The preconditions, so an `available` cannot be mistaken for one that
        # simply was not reached.
        assert payload["shallow_tickers"] == []
        assert payload["depth_status"] == "available"
        assert payload["unpairable_tickers"] == []
        assert payload["universe_coverage"]["status"] == "complete"
        assert payload["multiple_testing"]["declared_positive_count"] == 0
        assert payload["data_status"] == "available"

    async def test_no_pair_row_gained_a_verdict_count_of_its_own(self):
        """The totals are an aggregate. Publishing them per row would put a
        second, differently-scoped number on the very rows whose verdict the
        aggregate counts - which is the contradiction this section exists to
        close, rebuilt one level down."""
        rows = _never_candidate_rows()
        payload = await _scan(DIVERGENCE_TICKERS, rows)
        by_key = {f"{r.ticker_a}/{r.ticker_b}": r for r in rows}
        for row in payload["pairs"]:
            assert set(row) == set(by_key[f"{row['ticker_a']}/{row['ticker_b']}"].model_dump())


# ---------------------------------------------------------------------------
# 3b. The THIRD withholding: a diagnostic that produced no verdict
# ---------------------------------------------------------------------------
# `build_pair_signal` emits `JOHANSEN_DIAGNOSTIC_UNAVAILABLE` for a pair whose
# Johansen statistic was not computable, and that head is in none of the counts
# above. `contested_pair_count` counts the contested head and must keep counting
# only pairs where two tests RAN and returned opposite verdicts; the two
# stationarity counts are about legs. So the refusal was withheld from every
# counter on the wire while still counting towards `directive_withheld_count`, and
# a reader reconciling those four numbers had no field that held it.


def _refusal(a: str, b: str, **overrides) -> CointPairResult:
    """A decision-positive, gate-passed pair whose diagnostic produced no verdict.

    `johansen_agrees_with_decision` is None, not False: `None == False` is True in
    Python, so the naive comparison would publish "the two tests agree" for a pair
    whose second test never ran.
    """
    fields = dict(
        ticker_a=a,
        ticker_b=b,
        engle_granger_pvalue=1e-9,
        engle_granger_tstat=-3.5,
        is_cointegrated=True,
        hedge_ratio_beta=1.0,
        intercept_alpha=0.0,
        ou_half_life_days=10.0,
        ou_reversion_speed_theta=0.07,
        current_spread_zscore=-2.0,
        hedge_ratio_beta_std_error=0.04,
        intercept_alpha_std_error=1.2,
        hedge_regression_observations=N,
        hedge_regression_std_error_basis=(
            "ols_standard_error_from_polyfit_covariance_df_n_minus_2"
        ),
        johansen_cointegrated=None,
        last_price_a=100.0,
        last_price_b=200.0,
        observation_date_a="2026-01-01",
        observation_date_b="2026-01-01",
        overlap_start="2026-01-01",
        overlap_end="2026-08-31",
        overlap_observations=N,
        signal="NEUTRAL",
        decision_test="engle_granger",
        johansen_role="diagnostic_only",
        johansen_agrees_with_decision=None,
        stationarity_leg_a=_leg(a, "i1"),
        stationarity_leg_b=_leg(b, "i1"),
        stationarity_gate={
            "verdict": STATIONARITY_GATE_PASSED,
            "leg_a_verdict": "i1",
            "leg_b_verdict": "i1",
            "reason": "fixture gate passed",
        },
    )
    fields.update(overrides)
    return CointPairResult(**fields)


def _mixed_rows() -> List[CointPairResult]:
    """Six rows: one refusal, one measured conflict, one directive, one negative,
    and two that fail the family correction.

    Each withholding head this section counts has its own row, so no count can be
    satisfied by another head's total, and the scan carries a `LONG_SPREAD`
    alongside the withheld rows so `directive_withheld_count` is not the whole
    delivered set.
    """
    return [
        _refusal("A.NS", "B.NS"),
        _pair("A.NS", "C.NS", 1e-9, johansen=False, zscore=2.0),
        _pair("B.NS", "C.NS", 1e-9, zscore=-1.5),
        _pair("A.NS", "D.NS", 0.5, is_coint=False, johansen=False, zscore=0.1),
        _pair("B.NS", "D.NS", 0.042007, zscore=0.2),
        _pair("C.NS", "D.NS", 0.042007, zscore=-0.2),
    ]


class TestTheDiagnosticRefusalIsCountedOnTheWire:
    async def test_the_refusal_is_counted_and_not_as_a_contested_pair(self):
        payload = await _scan(DIVERGENCE_TICKERS, _mixed_rows())

        assert _head(payload["pairs"][0]["signal"]) == SIGNAL_DIAGNOSTIC_UNAVAILABLE
        assert payload["diagnostic_unavailable_count"] == 1
        # The sharp half: a refusal is NOT a conflict. One pair here ran both
        # tests and they opposed each other, so this counter stays at 1 and
        # cannot be doing the refusal's job.
        assert payload["contested_pair_count"] == 1
        assert payload["spurious_regression_rejected_count"] == 0
        assert payload["stationarity_undetermined_count"] == 0

    async def test_the_count_is_read_off_the_published_signal_heads(self):
        payload = await _scan(DIVERGENCE_TICKERS, _mixed_rows())
        heads = [_head(row["signal"]) for row in payload["pairs"]]

        assert heads.count(SIGNAL_DIAGNOSTIC_UNAVAILABLE) == payload[
            "diagnostic_unavailable_count"
        ]
        # And it accounts for the withheld row the other three counters do not,
        # so the four of them still close over `directive_withheld_count`. The
        # two remaining heads are `LONG_SPREAD` (a directive, not withheld) and
        # `NOT_COINTEGRATED`, which is withheld but is not a gate withholding.
        assert (
            payload["contested_pair_count"]
            + payload["spurious_regression_rejected_count"]
            + payload["stationarity_undetermined_count"]
            + payload["diagnostic_unavailable_count"]
            + heads.count("UNCONFIRMED_AFTER_MULTIPLE_TESTING_CORRECTION")
            + heads.count("NOT_COINTEGRATED")
        ) == payload["directive_withheld_count"]

    async def test_it_agrees_with_the_test_agreement_block_on_the_same_rows(self):
        """Two counters over the same population, derived from two different
        fields (the signal head and the diagnostic itself), so a mismatch means
        one of them is lying about the book."""
        payload = await _scan(DIVERGENCE_TICKERS, _mixed_rows())

        assert payload["test_agreement"]["unavailable_count"] == 1
        assert payload["diagnostic_unavailable_count"] == 1
        assert payload["test_agreement"]["unavailable_pairs"] == [
            f"{payload['pairs'][0]['ticker_a']}/{payload['pairs'][0]['ticker_b']}"
        ]

    async def test_the_basis_does_not_read_as_a_data_conflict(self):
        """The wording matters as much as the number: a basis sentence that says
        "conflict" or "disagree" next to this count restates a refused
        computation as a finding about the pair, whatever the count is called."""
        payload = await _scan(DIVERGENCE_TICKERS, _mixed_rows())
        basis = payload["diagnostic_unavailable_count_basis"]

        assert SIGNAL_DIAGNOSTIC_UNAVAILABLE in basis
        assert "NOT a subset of contested_pair_count" in basis
        assert "claim about the computation" in basis
        for forbidden in ("the two tests disagree", "tests conflict"):
            assert forbidden not in basis, forbidden

    async def test_the_warning_names_the_refusal_without_reading_as_a_conflict(self):
        payload = await _scan(DIVERGENCE_TICKERS, _mixed_rows())
        warnings = [w for w in payload["warnings"] if w.startswith("Diagnostic unavailable:")]

        assert len(warnings) == 1
        warning = warnings[0]
        assert "1 pair is cointegrated under engle_granger" in warning
        assert "not computable" in warning
        # The distinction is stated in the sentence a consumer reads first, and
        # the line is separate from the contested one so the two cannot merge.
        assert "This is a statement about the computation, not about the pair" in warning
        assert "the two tests did not conflict, because only one of them answered" in warning
        for forbidden in ("the two tests disagree", "tests conflict"):
            assert forbidden not in warning, forbidden
        contested = [w for w in payload["warnings"] if w.startswith("Contested pairs:")]
        assert len(contested) == 1
        assert warning is not contested[0]

    async def test_a_scan_with_no_refusal_publishes_no_such_warning(self):
        """The half nobody writes. A warning that fires on clean scans is noise,
        and noise is how a real degradation goes unread."""
        payload = await _scan(CLEAN_TICKERS, _clean_rows())

        assert payload["diagnostic_unavailable_count"] == 0
        assert not [
            w for w in payload["warnings"] if w.startswith("Diagnostic unavailable:")
        ]
