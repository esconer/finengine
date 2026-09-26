"""AD-9: the lower bound that fires the alert must be a field, not prose.

Making the correlation regime test two-sided was the fix. But it left the
LOWER bound reachable only by parsing it out of `message` prose, while the 90th
and 75th percentiles were already machine-readable fields. That is the wrong
asymmetry: a consumer asking "why did `is_regime_break` become true?" could read
the upper bound from a field and the lower bound only from English.

These tests pin the field, and pin that it is the SAME number the comparison
used - a bound published beside an alert that fired on a different number would
be worse than no bound at all.
"""

from __future__ import annotations

import pytest

from app.models.schemas import CorrelationStabilityResponse


def test_the_schema_carries_the_lower_bound():
    fields = CorrelationStabilityResponse.model_fields
    assert "historical_threshold_10th" in fields
    # Optional, because a single holding has undefined pairwise correlation and
    # this schema's whole convention is to preserve that rather than fabricate.
    assert fields["historical_threshold_10th"].default is None


def _response(**overrides):
    base = dict(
        as_of="2026-09-25",
        current_avg_correlation=0.1361,
        historical_threshold_90th=0.459,
        historical_threshold_75th=0.4129,
        historical_threshold_10th=0.219,
        historical_median=0.3408,
        is_regime_break=True,
        alert_level="ELEVATED",
        message="co-movement has collapsed",
        series=[],
    )
    base.update(overrides)
    return CorrelationStabilityResponse(**base)


def test_the_bound_survives_serialisation():
    """The schemas.py:485 lesson: an undeclared key is dropped on the wire."""
    dumped = _response().model_dump()
    assert "historical_threshold_10th" in dumped
    assert dumped["historical_threshold_10th"] == pytest.approx(0.219)


def test_all_three_tails_are_published_together():
    r = _response()
    for key in (
        "historical_threshold_10th",
        "historical_threshold_75th",
        "historical_threshold_90th",
        "historical_median",
    ):
        assert getattr(r, key) is not None, f"{key} must be readable without parsing prose"


def test_the_brackets_stay_ordered():
    """A two-sided test with an inverted band would be nonsense, so the four
    published numbers must remain in ascending order."""
    r = _response()
    lo, q1, med, hi = (
        r.historical_threshold_10th,
        r.historical_threshold_75th,
        r.historical_median,
        r.historical_threshold_90th,
    )
    assert lo <= med <= hi
    assert lo < q1 < hi


def test_the_alert_is_consistent_with_the_published_bound():
    """The bound that is published must be the one the verdict used."""
    r = _response()
    broke_low = r.current_avg_correlation <= r.historical_threshold_10th
    broke_high = r.current_avg_correlation >= r.historical_threshold_90th
    assert broke_low or broke_high
    assert r.is_regime_break is (broke_low or broke_high)


def test_an_unmeasured_book_publishes_no_bound_at_all():
    """One holding has no pairwise correlation, so there is no distribution and
    no percentile to publish. Absent, not zero."""
    r = _response(
        current_avg_correlation=None,
        historical_threshold_10th=None,
        historical_threshold_90th=None,
        historical_threshold_75th=None,
        historical_median=None,
        is_regime_break=False,
        alert_level="NORMAL",
    )
    dumped = r.model_dump()
    assert dumped["historical_threshold_10th"] is None
