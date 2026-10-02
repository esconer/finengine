"""`alert_direction`: which tail fired, stated in the payload.

On the live book (`portfolio-83c484b9eec5`, export `v25.json`)
`correlation_stability` publishes `current_avg_correlation = 0.1483` against
`historical_threshold_10th = 0.2179` and `historical_median = 0.3404`. Co-movement
has COLLAPSED. The section nevertheless says `alert_level: "ELEVATED"` - the same
string the 75th-percentile branch emits for co-movement RISING. The severity is
identical in both cases and means opposite things about diversification, so a
consumer reading the falling book cannot tell which branch fired without
recomputing the percentile comparison themselves.

`alert_level` is not changed: its string is consumed and test-visible, so
renaming it would be a breaking change dressed as a cleanup. The fix is additive
- one field beside it, set in every arm from the comparison that arm already
used.

What is pinned here, in order of how much it matters:

* the two ELEVATED arms are distinguishable, and were not before;
* every other published value in the section is byte-identical to the payload
  the unmodified service produced (`fixtures/correlation_stability_pre_direction.json`,
  captured before this field existed) - a new key, not a changed one;
* the token carries its meaning in words on the wire, not only in a comment;
* `null` is reserved for "no comparison ran", never used as a default.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.models.schemas import CorrelationStabilityResponse
from app.services.correlation_service import analyze_correlation_stability

GOLDEN_PATH = (
    Path(__file__).parent / "fixtures" / "correlation_stability_pre_direction.json"
)

# The keys this service publishes that the captured golden cannot have, because
# the golden was taken before either field existed. Both are ADDITIVE labels - a
# new key beside the figures, never a changed figure - and this list is
# deliberately CLOSED: a third entry means a published value moved without a
# label saying so, which is the failure
# `test_payload_is_byte_identical_to_the_pre_field_service` exists to catch. Do
# not append to it to turn a red run green.
#
#   * `alert_direction` predates this file's golden. It names which of the four
#     percentile comparisons fired, because `alert_level` cannot (see the module
#     docstring).
#   * `as_of_semantics` arrived with the disclosure field: `schemas.py` had to
#     declare it before FastAPI would carry it, so every measured payload now
#     carries the key, and the service sets it only where it can name the
#     observation (see `analyze_correlation_stability`).
ADDITIVE_KEYS_SINCE_GOLDEN = frozenset({"alert_direction", "as_of_semantics"})

# Each shape is chosen so a DIFFERENT comparison decides the alert, which is what
# makes the direction observable. `test_the_arm_each_shape_reaches` re-derives the
# arm from the published percentiles, so a drifted shape fails loudly instead of
# silently testing the wrong branch.
BOOKS = {
    # The live shape: 0.1483 at/below p10 (0.1931) against a 0.34 median.
    "lower_tail_collapse": list(
        np.concatenate([np.linspace(0.16, 0.34, 50), np.linspace(0.34, 0.56, 50)])
    )
    + [0.1483],
    # The arm that collides with it on string: 0.55 at/above p75 (0.30), below
    # p90 (0.90). `alert_level` is "ELEVATED" here too.
    "upper_tail_elevation": [0.30] * 85 + [0.90] * 15 + [0.55],
    # p10 (0.2303) < 0.34 < p75 (0.4242).
    "within_band": list(np.linspace(0.20, 0.50, 100)) + [0.34],
    # 0.61 at/above p90.
    "upper_tail_critical": [0.30] * 100 + [0.61],
}


@pytest.fixture
def golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _analyze(monkeypatch, values) -> CorrelationStabilityResponse:
    """Drive the real branch logic with a chosen rolling series.

    Only the windowing is stubbed; `analyze_correlation_stability` itself - the
    percentiles, the two comparisons and the four arms - is the code under test.
    """
    from app.services import correlation_service

    idx = pd.bdate_range("2024-01-01", periods=len(values))
    series = pd.Series(values, index=idx)
    monkeypatch.setattr(
        correlation_service,
        "compute_rolling_avg_correlation",
        lambda *a, **k: series,
    )
    return analyze_correlation_stability(pd.DataFrame(), window_days=60)


def _arm_that_fired(res: CorrelationStabilityResponse) -> str:
    """Re-derive the branch from the published percentiles, independently of the
    direction field. The two must agree, or the field is decorative."""
    cur = res.current_avg_correlation
    if cur >= res.historical_threshold_90th:
        return "upper_tail_critical"
    if cur >= res.historical_threshold_75th:
        return "upper_tail_elevation"
    if cur <= res.historical_threshold_10th:
        return "lower_tail_collapse"
    return "within_band"


# ===========================================================================
# 1. The two ELEVATED arms are now distinguishable - and were not before
# ===========================================================================
class TestTheTwoElevatedArms:
    def test_a_collapsed_book_says_so(self, monkeypatch):
        res = _analyze(monkeypatch, BOOKS["lower_tail_collapse"])

        assert res.alert_level == "ELEVATED"  # unchanged, and consumed
        assert res.alert_direction == "lower_tail_collapse"
        # The cause, not a memorised number: the published 10th percentile is
        # what the comparison actually used.
        assert res.current_avg_correlation <= res.historical_threshold_10th
        assert res.is_regime_break is True

    def test_a_rising_book_says_so(self, monkeypatch):
        res = _analyze(monkeypatch, BOOKS["upper_tail_elevation"])

        assert res.alert_level == "ELEVATED"  # THE SAME STRING as the collapse
        assert res.alert_direction == "upper_tail_elevation"
        assert res.historical_threshold_75th <= res.current_avg_correlation
        assert res.current_avg_correlation < res.historical_threshold_90th
        assert res.is_regime_break is False

    def test_the_two_elevated_arms_are_now_separable(self, monkeypatch):
        """The defect, stated as a test.

        Before this field these two responses agreed on `alert_level` and on
        almost everything else, and a reader had no way to tell "these positions
        are moving together more" from "these positions have stopped moving
        together". They differ only in the sign of the move, which is exactly
        what the new field names.
        """
        low = _analyze(monkeypatch, BOOKS["lower_tail_collapse"])
        high = _analyze(monkeypatch, BOOKS["upper_tail_elevation"])

        assert low.alert_level == high.alert_level == "ELEVATED"
        assert low.alert_direction != high.alert_direction
        # ...and the old field alone genuinely cannot separate them.
        assert (low.current_avg_correlation < high.current_avg_correlation) is True
        assert low.is_regime_break is not high.is_regime_break

    def test_a_critical_book_says_which_tail(self, monkeypatch):
        res = _analyze(monkeypatch, BOOKS["upper_tail_critical"])

        assert res.alert_level == "CRITICAL"
        assert res.alert_direction == "upper_tail_critical"
        assert res.current_avg_correlation >= res.historical_threshold_90th

    def test_a_within_band_book_says_so(self, monkeypatch):
        res = _analyze(monkeypatch, BOOKS["within_band"])

        assert res.alert_level == "NORMAL"
        assert res.alert_direction == "within_band"
        assert res.historical_threshold_10th < res.current_avg_correlation
        assert res.current_avg_correlation < res.historical_threshold_75th
        assert res.is_regime_break is False


class TestTheArmEachShapeReaches:
    @pytest.mark.parametrize("arm", sorted(BOOKS))
    def test_the_shape_reaches_the_arm_it_is_named_for(self, monkeypatch, arm):
        """Guards the guards. If a shape drifted into another branch, the
        assertions above would still hold - for the wrong book - so each shape
        re-derives its own branch from the percentiles it publishes."""
        res = _analyze(monkeypatch, BOOKS[arm])
        assert _arm_that_fired(res) == arm == res.alert_direction

    @pytest.mark.parametrize("arm", sorted(BOOKS))
    def test_direction_is_exactly_one_of_the_four_arms(self, monkeypatch, arm):
        res = _analyze(monkeypatch, BOOKS[arm])
        assert res.alert_direction in {
            "lower_tail_collapse",
            "upper_tail_elevation",
            "upper_tail_critical",
            "within_band",
        }


# ===========================================================================
# 2. Nothing published moved
# ===========================================================================
class TestNothingPublishedMoved:
    @pytest.mark.parametrize("arm", sorted(BOOKS))
    def test_payload_is_byte_identical_to_the_pre_field_service(
        self, monkeypatch, golden, arm
    ):
        """The whole payload, minus the two additive labels, equals the payload
        the unmodified service produced for the same book.

        The fixture was captured by running this same function before
        `alert_direction` existed, and before `as_of_semantics` was declared in
        schemas.py. A comparison of the full dumped dict (not a selection of
        fields) means a changed percentile, threshold, median, message or series
        row fails here. The key-set assertion above is what keeps the two pops
        honest: it fails on an UNEXPECTED addition, so the comparison below can
        only be reached with exactly the two known labels removed.
        """
        res = _analyze(monkeypatch, BOOKS[arm])
        dumped = res.model_dump()

        assert set(dumped) - set(golden[arm]) == ADDITIVE_KEYS_SINCE_GOLDEN
        assert set(golden[arm]) - set(dumped) == set()
        for additive in ADDITIVE_KEYS_SINCE_GOLDEN:
            dumped.pop(additive)
        assert dumped == golden[arm], (
            "a published figure moved: once the additive labels "
            f"{sorted(ADDITIVE_KEYS_SINCE_GOLDEN)} are removed, the payload "
            "must equal the pre-field golden exactly"
        )

    @pytest.mark.parametrize("arm", sorted(BOOKS))
    def test_the_new_key_is_the_only_addition(self, monkeypatch, golden, arm):
        res = _analyze(monkeypatch, BOOKS[arm])
        assert res.model_dump()["alert_direction"] == arm

    def test_alert_level_is_the_same_string_in_both_elevated_arms(
        self, monkeypatch, golden
    ):
        """What makes the new field necessary rather than decorative: the OLD
        field is one string across two opposite readings, and that is asserted
        against the captured pre-field payload, not just recomputed."""
        for arm in ("lower_tail_collapse", "upper_tail_elevation"):
            res = _analyze(monkeypatch, BOOKS[arm])
            assert res.alert_level == golden[arm]["alert_level"] == "ELEVATED"
        assert (
            golden["lower_tail_collapse"]["alert_level"]
            == golden["upper_tail_elevation"]["alert_level"]
        )

    def test_the_message_text_is_untouched_in_every_arm(self, monkeypatch, golden):
        for arm, book in BOOKS.items():
            assert _analyze(monkeypatch, book).message == golden[arm]["message"]

    def test_the_series_shape_is_untouched(self, monkeypatch, golden):
        for arm, book in BOOKS.items():
            series = _analyze(monkeypatch, book).series
            assert [p.model_dump() for p in series] == golden[arm]["series"]

    def test_the_live_books_published_numbers_are_untouched(self, golden):
        """The artifact values themselves, so a regression in the live shape
        cannot hide behind a synthetic book."""
        low = golden["lower_tail_collapse"]
        assert low["current_avg_correlation"] == 0.1483  # the live value
        assert low["historical_median"] == 0.34
        assert low["historical_threshold_10th"] == 0.1931
        assert low["historical_threshold_75th"] == 0.4478
        assert low["historical_threshold_90th"] == 0.5151
        assert low["is_regime_break"] is True


# ===========================================================================
# 3. The mapping is published in words, on the wire
# ===========================================================================
class TestTheMappingIsStatedInWords:
    def test_the_schema_carries_the_field(self):
        fields = CorrelationStabilityResponse.model_fields
        assert "alert_direction" in fields
        # Optional for the same reason the percentiles are: a single holding has
        # undefined pairwise correlation, so no comparison ran. It is NOT a
        # default the service can forget to set.
        assert fields["alert_direction"].default is None

    def test_the_field_survives_serialisation(self):
        """The schemas.py lesson: an undeclared key is dropped on the wire."""
        res = CorrelationStabilityResponse(
            as_of="2026-09-29",
            current_avg_correlation=0.1483,
            is_regime_break=True,
            alert_level="ELEVATED",
            alert_direction="lower_tail_collapse",
            message="x",
            series=[],
        )
        assert res.model_dump()["alert_direction"] == "lower_tail_collapse"
        assert "alert_direction" in res.model_dump_json()

    def test_the_token_to_meaning_mapping_is_published_not_just_commented(self):
        """A comment in the service is invisible to a consumer. The mapping has
        to be in the JSON Schema, which is what `/openapi.json` serves."""
        prop = CorrelationStabilityResponse.model_json_schema()["properties"][
            "alert_direction"
        ]
        description = prop["description"]

        for token in (
            "lower_tail_collapse",
            "upper_tail_elevation",
            "upper_tail_critical",
            "within_band",
        ):
            assert token in description, f"{token} must be documented on the wire"

        # The words, not just the token: what fired AND what it means for the
        # diversification benefit the score claims.
        lowered = description.lower()
        assert "collapsed" in lowered and "stopped moving" in lowered
        assert "diversification" in lowered
        assert "rising" in lowered
        assert "null" in lowered

    def test_the_live_collapse_reading_is_described_in_the_published_words(self):
        """The live book is the collapse arm. Its meaning - the historical
        diversification benefit may be gone - has to be in the words a consumer
        reads, not only in the service's own prose."""
        description = CorrelationStabilityResponse.model_json_schema()["properties"][
            "alert_direction"
        ]["description"]
        assert "may not be available in this regime" in description
        assert "regime change, not a reassurance" in description

    def test_a_service_with_no_comparison_publishes_null_not_a_default(self):
        """The single-holding path: pairwise correlation is undefined, so no
        percentile exists and no comparison ran. Direction is null, because
        nothing fired - not because a default filled in."""
        res = CorrelationStabilityResponse(
            as_of="2026-09-29",
            current_avg_correlation=None,
            historical_threshold_90th=None,
            historical_threshold_75th=None,
            historical_threshold_10th=None,
            historical_median=None,
            is_regime_break=False,
            alert_level="NORMAL",
            message="Single holding portfolio: pairwise correlation is undefined.",
            series=[],
            data_status="unavailable",
        )
        assert res.alert_direction is None
        assert res.model_dump()["alert_direction"] is None
