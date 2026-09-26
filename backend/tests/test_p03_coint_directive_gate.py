"""SI-1 / AD-1 gate: the pairs scanner must not trade on noise, and must say so.

The v5 export (876 KB, `portfolio-4b78905b588c`) shipped two spread directives
derived from a scan whose statistics are indistinguishable from the null:

    91 Engle-Granger p-values vs Uniform(0,1)   KS D=0.131101  p=0.079886
    declared positives 4  expected by chance 4.55  Poisson P(X=4)=0.188710
    Bonferroni 0.05/91 = 0.00054945 -> 0 survivors
    "LONG_SPREAD (Long ELECTCAST.NS, Short MCX.NS)"    hedge_ratio_beta 0.008606
    "SHORT_SPREAD (Short JUNIORBEES.NS, Long MIDCAPIETF.NS)"  beta 33.6396

All four decision-positive pairs carried `johansen_agrees_with_decision: false`
- the diagnostic contradicted the decision on every one of them and the
`signal` field did not care. The +/-1.5 z-threshold that triggered the
directive appeared zero times in the export, and neither directive published
the hedge ratio, so "Long A, Short B" read 1:1 mis-sized by ~116x and ~34x.

Four gates, all measured here:

  1. a pair whose diagnostic disagrees names no action,
  2. the payload publishes comparisons-made, the correction, the corrected
     threshold and the survivor count - including "0 survive",
  3. every action-naming string carries the threshold and the size ratio,
  4. nothing regresses: `is_cointegrated` is still the uncorrected
     Engle-Granger verdict, the p-value is still the same test's p-value, and
     the depth/universe/currency disclosure still ships.

No DB, no network. Where a p-value or a test verdict has to be exact, the
engine function that produced it is patched rather than re-derived, so a test
asserts the GATE and not a statsmodels sample.
"""

import json
from typing import Optional
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
    SIGNAL_ZSCORE_THRESHOLD,
    CointegrationService,
    _IN_MEMORY_COINT_CACHE,
    analyze_pair_cointegration,
    apply_signal_directives,
    benjamini_hochberg_threshold,
    bonferroni_threshold,
    build_pair_signal,
    multiplicity_report,
)

# The 91 published Engle-Granger p-values, in the payload's own order, from
# export portfolio-4b78905b588c `sections.pairs.data.pairs`. Embedded rather
# than read from the 876 KB artifact so the regression gate is self-contained.
AUDITED_91_PVALUES = [
    0.002609, 0.020638, 0.042007, 0.04853, 0.051769, 0.054711, 0.054794, 0.109122,
    0.113303, 0.12074, 0.122268, 0.133228, 0.134169, 0.134213, 0.137563, 0.142516,
    0.158, 0.158754, 0.159886, 0.172363, 0.176576, 0.18136, 0.186716, 0.188949,
    0.189077, 0.194987, 0.198475, 0.20599, 0.212375, 0.222138, 0.231719, 0.232779,
    0.241742, 0.245023, 0.259404, 0.278894, 0.283326, 0.286481, 0.303731, 0.332672,
    0.337125, 0.345507, 0.354607, 0.373655, 0.388475, 0.388986, 0.422262, 0.431167,
    0.493704, 0.494562, 0.55347, 0.575527, 0.594134, 0.603324, 0.607111, 0.613348,
    0.632064, 0.64731, 0.655868, 0.656722, 0.660555, 0.662567, 0.666982, 0.671958,
    0.672346, 0.672975, 0.694429, 0.72806, 0.750528, 0.764813, 0.804989, 0.806136,
    0.810337, 0.815895, 0.820842, 0.823838, 0.832077, 0.833858, 0.837657, 0.846564,
    0.868799, 0.869392, 0.911351, 0.918963, 0.92653, 0.927684, 0.941565, 0.968209,
    0.971446, 0.988505, 0.990682,
]

# The two pairs the audit named, with the numbers it measured off the payload.
AUDITED_DIRECTIVE_PAIRS = {
    "ELECTCAST.NS/MCX.NS": 0.042007,
    "JUNIORBEES.NS/MIDCAPIETF.NS": 0.04853,
}

# Tokens that make a signal an ORDER. A gate test asserts on these, not on the
# prose, so a rewording of the explanation cannot quietly pass.
_ACTION_TOKENS = ("LONG_SPREAD", "SHORT_SPREAD")


def _head(signal: Optional[str]) -> str:
    text = str(signal or "").strip()
    return text.split(" ", 1)[0] if text else ""


def _names_an_action(signal: Optional[str]) -> bool:
    return _head(signal) in _ACTION_TOKENS


def _payload(response) -> dict:
    """What the AI-context exporter actually serialises."""
    return json.loads(response.model_dump_json())


def _pair(
    a: str = "AAA.NS",
    b: str = "BBB.NS",
    pvalue: float = 0.01,
    *,
    is_coint: bool = True,
    johansen: bool = True,
    beta: float = 1.0,
    zscore: Optional[float] = 0.1,
) -> CointPairResult:
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
        johansen_cointegrated=johansen,
        last_price_a=100.0,
        last_price_b=200.0,
        signal="NEUTRAL",
        decision_test="engle_granger",
        johansen_role="diagnostic_only",
        johansen_agrees_with_decision=johansen == is_coint,
    )


# ---------------------------------------------------------------------------
# Gate 1: a pair whose diagnostic disagrees names no action
# ---------------------------------------------------------------------------


class TestDiagnosticDisagreementSuppressesTheDirective:
    """`johansen_agrees_with_decision: false` beside a `LONG_SPREAD` string is
    the defect. The gate is that the decision test alone can no longer name a
    position."""

    @pytest.mark.parametrize("zscore", [-3.0, -1.5, 1.5, 3.0])
    @pytest.mark.parametrize("beta", [0.008606, 33.6396, 1.0])
    def test_disagreeing_pair_never_names_an_action(self, zscore, beta):
        pair = _pair(pvalue=0.042007, is_coint=True, johansen=False,
                     beta=beta, zscore=zscore)
        assert pair.johansen_agrees_with_decision is False
        signal = build_pair_signal(pair, family_alpha=0.05, comparisons_made=1)
        assert not _names_an_action(signal), (
            f"a pair the Johansen diagnostic rejects must not be tradable: {signal!r}"
        )
        assert _head(signal) == "CONTESTED_TESTS_DISAGREE"
        # It still says which test conflicted and why no direction follows.
        assert "johansen" in signal
        assert "no direction is published" in signal

    def test_disagreement_is_gated_before_the_z_threshold(self):
        """The z-score is irrelevant once the tests conflict - a 6-sigma
        spread on a pair two tests disagree about is still not a trade."""
        wide = _pair(pvalue=0.001, johansen=False, zscore=-6.0)
        narrow = _pair(pvalue=0.001, johansen=False, zscore=-0.01)
        assert build_pair_signal(wide, comparisons_made=1) == build_pair_signal(
            narrow, comparisons_made=1
        )

    def test_negative_beta_is_not_a_directional_spread(self):
        """`hedge_ratio_beta <= 0` means 'Long A, Short B' is the wrong SIGN of
        position, not merely the wrong size. No ratio fixes that."""
        pair = _pair(pvalue=0.0001, johansen=True, beta=-0.4, zscore=-2.0)
        signal = build_pair_signal(pair, comparisons_made=1)
        assert not _names_an_action(signal)
        assert _head(signal) == "NON_DIRECTIONAL_HEDGE_RATIO"

    def test_single_pair_analysis_stops_at_the_withheld_state(self):
        """`analyze_pair_cointegration` cannot see the family size, so it must
        not pretend it can apply the correction - and must not name a trade
        either. `scan_pairs` re-derives the string."""
        index = pd.bdate_range("2026-01-01", periods=300)
        rng = np.random.default_rng(11)
        p1 = pd.Series(100.0 + np.cumsum(rng.normal(0, 1.0, 300)), index=index)
        p2 = 1.5 * p1 + 10.0 + pd.Series(rng.normal(0.0, 0.4, 300), index=index)

        with patch.object(coint, "test_johansen_cointegration", lambda *_a, **_k: False):
            contested = analyze_pair_cointegration("AAA.NS", "BBB.NS", p1, p2)
        assert contested is not None
        assert contested.is_cointegrated is True
        assert contested.johansen_agrees_with_decision is False
        assert not _names_an_action(contested.signal)
        assert _head(contested.signal) == "CONTESTED_TESTS_DISAGREE"

        # Even with the diagnostic in agreement, a lone pair has no family, so
        # the honest state is "withheld pending correction" - not a position.
        with patch.object(coint, "test_johansen_cointegration", lambda *_a, **_k: True):
            agreeing = analyze_pair_cointegration("AAA.NS", "BBB.NS", p1, p2)
        assert agreeing.johansen_agrees_with_decision is True
        assert not _names_an_action(agreeing.signal)
        assert _head(agreeing.signal) in (
            "NEUTRAL",
            "DIRECTIVE_WITHHELD_PENDING_MULTIPLE_TESTING_CORRECTION",
        )

    def test_non_cointegrated_signal_is_unchanged(self):
        """The pre-existing `NOT_COINTEGRATED` head is load-bearing for the
        coverage suite; the gate adds heads, it does not rename this one."""
        pair = _pair(pvalue=0.42, is_coint=False, johansen=False, zscore=-4.0)
        assert build_pair_signal(pair, comparisons_made=1) == "NOT_COINTEGRATED"

    def test_withheld_strings_carry_no_position_token_at_all(self):
        """A consumer that greps for a position name - rather than parsing the
        head - must not find one in a withheld string. Every withheld head
        says so in words, so none of them may also name a direction."""
        withheld = [
            _pair(pvalue=0.042007, johansen=False, zscore=-3.0),
            _pair(pvalue=1e-6, johansen=True, beta=-0.4, zscore=-2.0),
            _pair(pvalue=1e-6, johansen=True, zscore=0.2),
            _pair(pvalue=0.42, is_coint=False, johansen=False, zscore=-4.0),
        ]
        for pair in withheld:
            for comparisons in (1, 91):
                signal = build_pair_signal(
                    pair, family_alpha=0.05, comparisons_made=comparisons
                )
                assert not _names_an_action(signal), signal
                assert "LONG_SPREAD" not in signal, signal
                assert "SHORT_SPREAD" not in signal, signal
                assert " Long " not in signal, signal
                assert " Short " not in signal, signal
                # `NOT_COINTEGRATED` and `NEUTRAL` are pre-existing bare heads
                # this fix deliberately leaves byte-identical; the three heads
                # it introduces must each say inline why they withhold.
                if _head(signal) in (
                    "CONTESTED_TESTS_DISAGREE",
                    "NON_DIRECTIONAL_HEDGE_RATIO",
                    "UNCONFIRMED_AFTER_MULTIPLE_TESTING_CORRECTION",
                ):
                    assert "no direction is published" in signal, signal

        # The same p-value that is withheld at m=91 is a real directive at m=1,
        # because a one-test family has no multiplicity to correct. The gate is
        # the family, not a blanket refusal to publish.
        borderline = _pair(pvalue=0.042007, johansen=True, beta=0.008606, zscore=-2.0)
        assert _names_an_action(
            build_pair_signal(borderline, family_alpha=0.05, comparisons_made=1)
        )
        assert not _names_an_action(
            build_pair_signal(borderline, family_alpha=0.05, comparisons_made=91)
        )


# ---------------------------------------------------------------------------
# Gate 2: the family is measured, corrected and published
# ---------------------------------------------------------------------------


class TestMultiplicityIsMeasured:
    def test_audited_family_of_91_survives_nothing(self):
        """The audit's own numbers, re-derived: 4 declared positives against
        4.55 expected by chance, 0 Bonferroni survivors, 0 BH-FDR survivors."""
        pairs = [
            _pair(a=f"T{i:02d}.NS", b=f"U{i:02d}.NS", pvalue=p,
                  is_coint=p < 0.05, johansen=False)
            for i, p in enumerate(AUDITED_91_PVALUES)
        ]
        report = multiplicity_report(pairs, family_alpha=0.05, comparisons_made=91)

        assert report["comparisons_made"] == 91
        assert report["family_alpha"] == 0.05
        assert report["corrected_threshold"] == pytest.approx(0.05 / 91, rel=1e-9)
        assert report["declared_positive_count"] == 4
        assert report["expected_false_positives_uncorrected"] == pytest.approx(4.55)
        # 4 found against 4.55 expected: the null expectation, not a finding.
        assert report["survivor_count"] == 0
        assert report["surviving_pairs"] == []
        assert report["benjamini_hochberg_fdr"]["survivor_count"] == 0
        # The correction is named, and it is the gate.
        assert report["gate"] == MULTIPLICITY_CORRECTION
        assert "bonferroni" in report["note"].lower()
        assert "4.55" in report["note"]

    def test_audited_pvalues_are_not_below_the_corrected_threshold(self):
        """Independent of the report's own arithmetic: no audited p-value is
        under 0.05/91, so nothing can be published as a discovery."""
        corrected = bonferroni_threshold(0.05, 91)
        assert min(AUDITED_91_PVALUES) > corrected
        assert sorted(AUDITED_91_PVALUES)[:4] == [
            0.002609, 0.020638, 0.042007, 0.04853
        ]

    def test_the_two_audited_directives_are_declared_but_unsurvived(self):
        """Ties the family report back to the exact rows the audit named. Both
        were `LONG_SPREAD`/`SHORT_SPREAD` in the export; under the gate they
        are declared positives that survive nothing."""
        noise = [
            _pair(a=f"Z{i:02d}.NS", b=f"Y{i:02d}.NS", pvalue=p, is_coint=p < 0.05,
                  johansen=False)
            for i, p in enumerate(AUDITED_91_PVALUES)
        ]
        named = []
        for key, pvalue in AUDITED_DIRECTIVE_PAIRS.items():
            a, b = key.split("/")
            named.append(_pair(a=a, b=b, pvalue=pvalue, is_coint=True, johansen=False))
        report = multiplicity_report(
            noise + named, family_alpha=0.05, comparisons_made=93
        )
        for key, pvalue in AUDITED_DIRECTIVE_PAIRS.items():
            # The audit measured this p-value off the export, and it is the
            # one that put a position on.
            assert pvalue < 0.05
            # Declared positive ...
            assert key in report["declared_positive_pairs"]
            # ... and not a discovery.
            assert key not in report["surviving_pairs"]
        assert report["survivor_count"] == 0

    def test_family_size_is_the_number_of_tests_not_the_number_of_rows(self):
        """`max_half_life` drops rows AFTER the test. Correcting over the
        survivors would loosen the threshold as rows disappear, so the family
        is the test count even when it exceeds the delivered row count."""
        pairs = [_pair(pvalue=0.02, is_coint=True, johansen=True)]
        over_tests = multiplicity_report(pairs, family_alpha=0.05, comparisons_made=91)
        over_rows = multiplicity_report(pairs, family_alpha=0.05)
        assert over_tests["corrected_threshold"] == pytest.approx(0.05 / 91)
        assert over_rows["corrected_threshold"] == pytest.approx(0.05)
        assert over_tests["delivered_pvalue_count"] == 1
        assert "loosen the threshold" in over_tests["note"]

    def test_survivor_is_published_when_something_survives(self):
        pairs = [
            _pair(a="A.NS", b="B.NS", pvalue=1e-9, is_coint=True, johansen=True),
            _pair(a="C.NS", b="D.NS", pvalue=0.5, is_coint=False, johansen=False),
        ]
        report = multiplicity_report(pairs, family_alpha=0.05, comparisons_made=2)
        assert report["declared_positive_count"] == 1
        assert report["survivor_count"] == 1
        assert report["surviving_pairs"] == ["A.NS/B.NS"]

    def test_empty_family_has_no_threshold_invented_for_it(self):
        """Zero tests means no corrected threshold exists. Publishing 0.0 would
        read as an infinitely strict gate and 1.0 as no gate at all."""
        report = multiplicity_report([], family_alpha=0.05, comparisons_made=0)
        assert report["comparisons_made"] == 0
        assert report["corrected_threshold"] is None
        assert report["survivor_count"] == 0
        assert bonferroni_threshold(0.05, 0) is None
        assert benjamini_hochberg_threshold([], 0.05) is None

    def test_bonferroni_is_alpha_over_m(self):
        assert bonferroni_threshold(0.05, 91) == pytest.approx(0.0005494505494505494)
        assert bonferroni_threshold(0.10, 1) == pytest.approx(0.10)

    def test_benjamini_hochberg_is_the_step_up_rule(self):
        # 3 p-values at q=0.05: sorted, 0.001 <= 1*0.05/3, 0.02 <= 2*0.05/3,
        # 0.9 does not clear 3*0.05/3 -> the threshold is 2*q/m.
        threshold = benjamini_hochberg_threshold([0.001, 0.02, 0.9], 0.05)
        assert threshold == pytest.approx(2 * 0.05 / 3)
        assert benjamini_hochberg_threshold([0.9, 0.8, 0.7], 0.05) is None

    def test_pair_that_fails_correction_publishes_no_direction(self):
        pair = _pair(pvalue=0.042007, johansen=True, beta=0.008606, zscore=-1.6827)
        signal = build_pair_signal(
            pair, family_alpha=0.05, comparisons_made=91
        )
        assert not _names_an_action(signal)
        assert _head(signal) == "UNCONFIRMED_AFTER_MULTIPLE_TESTING_CORRECTION"
        assert "0.000549" in signal
        assert "0.05/91" in signal

    def test_apply_signal_directives_rewrites_every_row(self):
        rows = [
            _pair(pvalue=0.042007, johansen=True, beta=0.008606, zscore=-1.6827),
            _pair(pvalue=0.5, is_coint=False, johansen=False),
        ]
        out = apply_signal_directives(rows, family_alpha=0.05, comparisons_made=91)
        assert [p.signal for p in out] == [
            build_pair_signal(p, family_alpha=0.05, comparisons_made=91)
            for p in rows
        ]
        assert not any(_names_an_action(p.signal) for p in out)


# ---------------------------------------------------------------------------
# Gate 3: an action-naming string carries its threshold and its size
# ---------------------------------------------------------------------------


class TestDirectiveCarriesItsEvidence:
    """A directive that does not publish the trigger and the size is worse than
    no directive: it looks actionable and is unexecutable."""

    def _directive(self, beta: float, zscore: float, m: int = 1):
        pair = _pair(pvalue=1e-6, johansen=True, beta=beta, zscore=zscore)
        signal = build_pair_signal(
            pair, family_alpha=0.05, comparisons_made=m
        )
        assert _names_an_action(signal), signal
        return signal

    @pytest.mark.parametrize("beta,zscore", [(1.0, -1.5), (1.0, 1.5), (0.008606, -2.0),
                                            (33.6396, 2.0), (-0.0 + 0.5, 9.0)])
    def test_directive_names_threshold_ratio_and_notional(self, beta, zscore):
        signal = self._directive(beta, zscore)
        # threshold, with its sign convention
        assert f"threshold +/-{SIGNAL_ZSCORE_THRESHOLD:g}" in signal
        # the size ratio, and the notional convention that gives it a size
        assert f"hedge_ratio_beta={beta:.6f}" in signal
        assert "units of BBB.NS per 1 unit of AAA.NS" in signal
        assert "currency notional" in signal
        # the family: comparisons, correction, corrected threshold, agreement
        assert "= 0.05/1" in signal
        assert MULTIPLICITY_CORRECTION in signal
        assert "johansen_agrees_with_decision=true" in signal

    def test_directive_reports_how_wrong_a_1to1_read_is(self):
        """"Long A, Short B" without this number is how a 0.0086-beta spread
        gets sized 1:1 and is wrong by ~116x."""
        small = self._directive(0.008606, -2.0)
        assert "mis-sizes by 116.2x" in small
        big = self._directive(33.6396, 2.0)
        assert "mis-sizes by 33.6x" in big
        # beta == 1 needs no warning number but still carries the ratio.
        unit = self._directive(1.0, -2.0)
        assert "mis-sizes by 1.0x" in unit

    def test_direction_matches_the_sign_of_the_zscore(self):
        assert self._directive(1.0, -2.0).startswith("LONG_SPREAD (Long AAA.NS")
        assert self._directive(1.0, 2.0).startswith("SHORT_SPREAD (Short AAA.NS")

    def test_zscore_exactly_on_the_threshold_is_an_extreme(self):
        """The comparison is inclusive, matching the pre-existing
        `>= 1.5` / `<= -1.5` rule - this fix does not move the trigger."""
        assert _names_an_action(self._directive(1.0, SIGNAL_ZSCORE_THRESHOLD))
        assert _names_an_action(self._directive(1.0, -SIGNAL_ZSCORE_THRESHOLD))
        just_inside = build_pair_signal(
            _pair(pvalue=1e-6, johansen=True, zscore=SIGNAL_ZSCORE_THRESHOLD - 1e-9),
            family_alpha=0.05,
            comparisons_made=1,
        )
        assert not _names_an_action(just_inside)
        assert just_inside == "NEUTRAL"


# ---------------------------------------------------------------------------
# Route: the whole payload, over a real scan
# ---------------------------------------------------------------------------


class _FakeMarket:
    def __init__(self, frames):
        self.frames = dict(frames)

    async def fetch_historical_data(self, ticker, start, end):
        frame = self.frames.get(ticker)
        return pd.DataFrame() if frame is None else frame


def _frame(values, index):
    return pd.DataFrame({"close": np.asarray(values, dtype=float)}, index=index)


def _universe(deep: int = 200, seed: int = 41):
    """Deep peers plus one young ETF: the audited NIFTYIETF shape.

    The ETF covers `deep - 60` of `deep` sessions (0.70 at deep=200), which is
    under `MIN_PAIR_DEPTH_RATIO`, so the scan really does report
    `depth_status: "partial"` and `shallow_tickers: ["NIFTYIETF.NS"]` and the
    no-regression assertions are testing the disclosure, not a coincidence.
    """
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2026-01-01", periods=deep)
    base = pd.Series(100.0 + np.cumsum(rng.normal(0.05, 1.0, deep)), index=index)
    peer = 1.5 * base + 10.0 + pd.Series(rng.normal(0.0, 0.4, deep), index=index)
    etf = pd.Series(
        50.0 + np.cumsum(rng.normal(0.02, 0.3, deep - 60)), index=index[60:]
    )
    return {
        "INFY.NS": _frame(base.to_numpy(), base.index),
        "TCS.NS": _frame(peer.to_numpy(), peer.index),
        "NIFTYIETF.NS": _frame(etf.to_numpy(), etf.index),
    }


async def _scan(tickers, frames, *, p_value_threshold: float = 0.05, johansen=None):
    """Run the real route over `frames`.

    `johansen` forces the diagnostic verdict so the disagreement case is
    deterministic instead of a property of the sampled prices.
    """
    _IN_MEMORY_COINT_CACHE.clear()
    stack = []
    try:
        if johansen is not None:
            stack.append(
                patch.object(coint, "test_johansen_cointegration", lambda *_a, **_k: johansen)
            )
        for item in stack:
            item.start()
        with patch.object(analytics_mod, "CointegrationService", CointegrationService):
            return await get_cointegration_pairs(
                tickers=tickers,
                lookback_days=252,
                p_value_threshold=p_value_threshold,
                max_half_life=None,
                include_spread_series=False,
                db=Mock(),
                data_service=_FakeMarket(frames),
                cache_service=None,
            )
    finally:
        for item in reversed(stack):
            item.stop()
        _IN_MEMORY_COINT_CACHE.clear()


class TestRoutePayload:
    async def test_disagreeing_scan_publishes_no_directive(self):
        result = await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", _universe(), johansen=False)
        payload = _payload(result)

        assert payload["test_agreement"]["disagreement_count"] == payload["test_agreement"]["decision_positive_count"]
        assert payload["contested_pair_count"] == payload["test_agreement"]["decision_positive_count"]
        assert payload["directive_count"] == 0
        assert payload["directives"] == []
        for pair in payload["pairs"]:
            if not pair["is_cointegrated"]:
                assert pair["signal"] == "NOT_COINTEGRATED"
                continue
            assert not _names_an_action(pair["signal"]), pair["signal"]
            # The structural disclosure is still there, row by row.
            assert pair["johansen_agrees_with_decision"] is False
            assert _head(pair["signal"]) == "CONTESTED_TESTS_DISAGREE"

    async def test_payload_publishes_the_family_and_the_correction(self):
        frames = _universe()
        n = 3  # C(3,2) = 3 pair tests
        result = await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", frames)
        payload = _payload(result)
        family = payload["multiple_testing"]

        assert family["comparisons_made"] == n
        assert family["family_alpha"] == 0.05
        assert family["corrected_threshold"] == pytest.approx(0.05 / n)
        assert family["gate"] == MULTIPLICITY_CORRECTION
        assert family["bonferroni"]["survivor_count"] == family["survivor_count"]
        assert "bonferroni" in family["gate_basis"].lower()
        assert family["delivered_pvalue_count"] == family["comparisons_made"]
        # The reader is told the null expectation, not left to compute it.
        assert family["expected_false_positives_uncorrected"] == pytest.approx(0.15)
        assert "expected" in family["note"]

    async def test_zero_survivors_is_published_not_hidden(self):
        """The honest result on this family, stated as such: 0 pairs survive
        correction beats 3 uncorrected positives a reader cannot weigh."""
        result = await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", _universe())
        payload = _payload(result)
        family = payload["multiple_testing"]

        if family["declared_positive_count"] and not family["survivor_count"]:
            note = next(
                text for text in payload["warnings"]
                if text.startswith("Multiple testing:")
            )
            assert str(family["comparisons_made"]) in note
            assert MULTIPLICITY_CORRECTION in note
            assert "0 survive" in note
            assert payload["directive_count"] == 0
            # Declared positives that do not survive are not a clean result.
            assert payload["data_status"] == "partial"
        else:
            # If this seeded family happens to be clean, the correction still
            # has to be published and no directive may exceed it.
            assert family["survivor_count"] <= family["declared_positive_count"]

    async def test_payload_publishes_the_zscore_threshold_and_its_basis(self):
        result = await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", _universe())
        policy = _payload(result)["signal_policy"]

        assert policy["zscore_threshold"] == SIGNAL_ZSCORE_THRESHOLD
        assert policy["zscore_threshold_provenance"] == "fixed_engine_constant_not_calibrated"
        # A basis, not a number: the reader must be able to see what it means
        # and that it is not a calibrated significance level.
        assert "unitless" in policy["zscore_threshold_basis"]
        assert "not" in policy["zscore_threshold_basis"]
        assert "ddof=1" in policy["zscore_threshold_basis"]
        assert policy["notional_convention"]
        assert policy["gate"] == MULTIPLICITY_CORRECTION
        assert set(policy["action_naming_heads"]) == set(_ACTION_TOKENS)

    async def test_directive_entry_carries_the_whole_chain(self):
        """One pair, everything passing, so a directive actually exists to
        inspect. m=1 makes the Bonferroni threshold the alpha itself."""
        pair = _pair(pvalue=1e-6, johansen=True, beta=0.008606, zscore=-1.6827)
        _IN_MEMORY_COINT_CACHE.clear()
        try:
            with patch.object(
                coint, "analyze_pair_cointegration", lambda **_kw: pair
            ), patch.object(analytics_mod, "CointegrationService", CointegrationService):
                result = await get_cointegration_pairs(
                    tickers="AAA.NS,BBB.NS",
                    lookback_days=252,
                    p_value_threshold=0.05,
                    max_half_life=None,
                    include_spread_series=False,
                    db=Mock(),
                    data_service=_FakeMarket(
                        {
                            "AAA.NS": _frame([1.0, 2.0], pd.bdate_range("2026-01-01", periods=2)),
                            "BBB.NS": _frame([1.0, 2.0], pd.bdate_range("2026-01-01", periods=2)),
                        }
                    ),
                    cache_service=None,
                )
        finally:
            _IN_MEMORY_COINT_CACHE.clear()

        payload = _payload(result)
        assert payload["directive_count"] == 1
        entry = payload["directives"][0]
        assert entry["direction"] == "LONG_SPREAD"
        assert entry["johansen_agrees_with_decision"] is True
        assert entry["comparisons_made"] == 1
        assert entry["correction_applied"] == MULTIPLICITY_CORRECTION
        assert entry["corrected_p_value_threshold"] == pytest.approx(0.05)
        assert entry["survives_correction"] is True
        assert entry["zscore_threshold"] == SIGNAL_ZSCORE_THRESHOLD
        assert entry["hedge_ratio_beta"] == 0.008606
        assert "1 unit of currency notional in AAA.NS against 0.008606 units in BBB.NS" in entry["notional_convention"]
        # And the string itself is self-contained, for a reader who only has it.
        signal = payload["pairs"][0]["signal"]
        assert "hedge_ratio_beta=0.008606" in signal
        assert f"threshold +/-{SIGNAL_ZSCORE_THRESHOLD:g}" in signal
        assert "mis-sizes by 116.2x" in signal

    async def test_surviving_uncorrected_positive_ships_no_action_string(self):
        """The exact audited shape: EG flags the pair, the diagnostic refutes
        it, and a wide z-score must still produce no position."""
        pair = _pair(
            a="ELECTCAST.NS", b="MCX.NS", pvalue=0.042007, is_coint=True,
            johansen=False, beta=0.008606, zscore=-1.6827,
        )
        assert pair.johansen_agrees_with_decision is False
        _IN_MEMORY_COINT_CACHE.clear()
        try:
            with patch.object(
                coint, "analyze_pair_cointegration", lambda **_kw: pair
            ), patch.object(analytics_mod, "CointegrationService", CointegrationService):
                result = await get_cointegration_pairs(
                    tickers="ELECTCAST.NS,MCX.NS",
                    lookback_days=252,
                    p_value_threshold=0.05,
                    max_half_life=None,
                    include_spread_series=False,
                    db=Mock(),
                    data_service=_FakeMarket(
                        {
                            "ELECTCAST.NS": _frame([1.0, 2.0], pd.bdate_range("2026-01-01", periods=2)),
                            "MCX.NS": _frame([1.0, 2.0], pd.bdate_range("2026-01-01", periods=2)),
                        }
                    ),
                    cache_service=None,
                )
        finally:
            _IN_MEMORY_COINT_CACHE.clear()

        payload = _payload(result)
        assert payload["pairs"][0]["is_cointegrated"] is True
        assert payload["pairs"][0]["signal"].startswith("CONTESTED_TESTS_DISAGREE")
        assert "LONG_SPREAD" not in payload["pairs"][0]["signal"]
        assert payload["directive_count"] == 0
        assert payload["contested_pair_count"] == 1
        assert payload["test_agreement"]["decision_positive_only_count"] == 1
        assert any(
            text.startswith("Contested pairs:") for text in payload["warnings"]
        )


# ---------------------------------------------------------------------------
# Must not regress: the decision rule, the disclosure, the currency
# ---------------------------------------------------------------------------


class TestNoRegression:
    async def test_decision_rule_is_still_engle_granger_at_alpha(self):
        """Gating the DIRECTIVE must not gate the DECISION. `is_cointegrated`
        is still `engle_granger_pvalue < 0.05`, strictly, on a pair the
        diagnostic refutes - otherwise the fix would have quietly changed
        which test decides."""
        pair = _pair(pvalue=0.042007, is_coint=True, johansen=False)
        assert pair.engle_granger_pvalue < 0.05
        assert pair.is_cointegrated is True
        assert pair.decision_test == "engle_granger"
        assert pair.johansen_role == "diagnostic_only"

    async def test_pvalue_is_unchanged_by_the_gate(self):
        index = pd.bdate_range("2026-01-01", periods=300)
        rng = np.random.default_rng(11)
        p1 = pd.Series(100.0 + np.cumsum(rng.normal(0, 1.0, 300)), index=index)
        p2 = 1.5 * p1 + 10.0 + pd.Series(rng.normal(0.0, 0.4, 300), index=index)
        with patch.object(coint, "test_johansen_cointegration", lambda *_a, **_k: False):
            result = analyze_pair_cointegration("AAA.NS", "BBB.NS", p1, p2)
        # The gate rewrites `signal` and nothing else measurable.
        assert result.engle_granger_pvalue == pytest.approx(
            analyze_pair_cointegration("AAA.NS", "BBB.NS", p1, p2).engle_granger_pvalue
        )
        assert 0.0 <= result.engle_granger_pvalue <= 1.0

    async def test_depth_currency_and_test_agreement_still_ship(self):
        """The pre-existing disclosure is extended, not replaced."""
        result = await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", _universe())
        payload = _payload(result)

        assert payload["minimum_pair_observations"] == 30
        assert payload["minimum_depth_ratio"] == 0.75
        assert payload["shallow_tickers"] == ["NIFTYIETF.NS"]
        assert payload["depth_status"] == "partial"
        assert payload["usable_observations_by_ticker"]
        assert payload["reference_pair_observations"]
        assert any(
            text.startswith("Depth-limited pairs:") for text in payload["warnings"]
        )
        assert payload["currency"] == "INR"
        assert payload["currency_provenance"] == "derived"
        assert "error" not in payload
        agreement = payload["test_agreement"]
        assert agreement["decision_test"] == "engle_granger"
        assert agreement["diagnostic_test"] == "johansen"
        assert agreement["test_roles"]["johansen"] == "diagnostic_only"
        assert agreement["counted_pairs"] == len(payload["pairs"])
        assert "must " in agreement["summed_count_note"]

    async def test_unavailable_scan_publishes_a_multiplicity_block_honestly(self):
        """Fewer than two tickers: no test ran, so no corrected threshold
        exists - and none is invented."""
        result = await _scan("INFY.NS", _universe())
        payload = _payload(result)
        assert payload["data_status"] == "unavailable"
        assert payload["multiple_testing"]["comparisons_made"] == 0
        assert payload["multiple_testing"]["corrected_threshold"] is None
        assert payload["multiple_testing"]["survivor_count"] == 0
        assert payload["directive_count"] == 0
        assert payload["directives"] == []
        # The threshold policy is still published: it is a property of the
        # scanner, not of the sample.
        assert payload["signal_policy"]["zscore_threshold"] == SIGNAL_ZSCORE_THRESHOLD

    @pytest.mark.parametrize(
        "count,verb", [(0, "0 survive"), (1, "1 survives"), (2, "2 survive")]
    )
    async def test_multiplicity_warning_is_grammatical_about_its_own_count(self, count, verb):
        """A disclosure sentence that reads wrong is a sentence a reader
        discounts, and this one carries the number the fix turns on."""
        # A universe of `count + 3` tickers: always at least C(3,2) = 3 tests,
        # so the noise pair's p-value can sit between alpha/m and alpha (the
        # band where a test is declared positive and still fails the
        # correction) rather than accidentally surviving a one-test family.
        universe = [f"U{i}.NS" for i in range(count + 3)]
        family_size = len(universe) * (len(universe) - 1) // 2
        survivor = _pair(pvalue=1e-9, johansen=True, zscore=-2.0)
        noise = _pair(pvalue=0.042007, johansen=True, zscore=0.0)
        queue = [survivor] * count + [noise] * (family_size - count)
        assert len(queue) == family_size
        assert noise.engle_granger_pvalue >= 0.05 / family_size
        assert survivor.engle_granger_pvalue < 0.05 / family_size

        _IN_MEMORY_COINT_CACHE.clear()
        try:
            with patch.object(
                coint, "analyze_pair_cointegration", lambda **_kw: queue.pop(0)
            ), patch.object(analytics_mod, "CointegrationService", CointegrationService):
                result = await get_cointegration_pairs(
                    tickers=",".join(universe),
                    lookback_days=252,
                    p_value_threshold=0.05,
                    max_half_life=None,
                    include_spread_series=False,
                    db=Mock(),
                    data_service=_FakeMarket(
                        {
                            t: _frame([1.0, 2.0], pd.bdate_range("2026-01-01", periods=2))
                            for t in universe
                        }
                    ),
                    cache_service=None,
                )
        finally:
            _IN_MEMORY_COINT_CACHE.clear()

        payload = _payload(result)
        assert payload["multiple_testing"]["comparisons_made"] == family_size
        assert payload["multiple_testing"]["survivor_count"] == count
        assert payload["multiple_testing"]["corrected_threshold"] == pytest.approx(
            0.05 / family_size
        )
        note = next(
            text for text in payload["warnings"] if text.startswith("Multiple testing:")
        )
        assert f"and {verb} {MULTIPLICITY_CORRECTION}" in note, note
        assert payload["directive_count"] == count
        # A survivor must be a real directive, and it must be self-contained.
        for entry in payload["directives"]:
            assert entry["survives_correction"] is True
            assert entry["johansen_agrees_with_decision"] is True
            assert entry["correction_applied"] == MULTIPLICITY_CORRECTION
            assert entry["comparisons_made"] == family_size
