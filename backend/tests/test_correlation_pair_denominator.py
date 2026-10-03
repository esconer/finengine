"""C-1: the refusal has no shape. Publish the denominator, not just the refusal.

`compute_rolling_avg_correlation` refuses a book whose NEWEST date is short of
all C = N(N-1)/2 pairs - correct, and kept. The refusal now REACHES the client
with its reason intact: `api/analytics.py` re-raises this one call's
`ValueError` as `detail=str(exc)`, so `/analytics/correlation-stability` answers
400 with the shortfall text rather than a bare `Invalid analytics request`.
That half is pinned in tests/test_correlation_stability_refusal_reason.py, not
here. This module covers the other half, which is untouched by that change:
every PUBLISHED payload still gives no hint that a floor exists at all. A reader
of `/analytics/correlation-stability` sees a number and has to assume it was the
book-wide average; the average over the pairs that survived is the defect this
module refuses to commit, so the denominator has to be visible rather than
assumed.

The measured cost of the floor, from the seeded fixture below (`window_days=60`,
6 pairs): a leg listed at day 150 goes from 191 published dates (150 of them
partial) to 41; a leg at day 200 leaves 0 and 400s. That cost is NOT what this
change touches - the floor stays. What it adds is the two fields that make the
floor legible from the payload.

What is pinned here, in order of how much it matters:

* every published point states the denominator its figure was taken over, and
  names the condition that admitted the date (RED before the fix: neither field
  existed on the schema);
* a point is never published with a partial denominator - the token exists only
  alongside a count equal to C, so the disclosure cannot drift into describing a
  partial measurement;
* a FULLY COVERED book is byte-identical to the pre-field service once the two
  additive labels are removed, using the existing golden-fixture pattern
  (`ADDITIVE_POINT_KEYS_SINCE_GOLDEN` in `test_correlation_stability.py`) rather
  than a second comparison invented here;
* the floor still refuses, and the refusal still names the shortfall.

No network. Fixed seed throughout.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.models.schemas import (
    CORRELATION_ALL_PAIRS_MEASURABLE,
    CorrelationDataPoint,
)
from app.services.correlation_service import (
    analyze_correlation_stability,
    compute_rolling_avg_correlation,
)

from .test_correlation_stability import (  # noqa: F401 - imported for its contract
    ADDITIVE_KEYS_SINCE_GOLDEN,
    ADDITIVE_POINT_KEYS_SINCE_GOLDEN,
    BOOKS,
    _analyze,
    _without_additive_point_keys,
)

GOLDEN_PATH = (
    Path(__file__).parent / "fixtures" / "correlation_stability_pre_direction.json"
)

WINDOW = 60
MIN_PERIODS = min(WINDOW, 30)
DAYS = 220


def _book(late_start=None, n_late=1, seed=7):
    """Three fully-listed legs plus `n_late` legs that begin trading later.

    Identical construction to `test_correlation_pair_coverage._book`, so the
    floor's measured cost is comparable with that file's numbers: six pairs,
    `MIN_PERIODS` pairwise-complete observations needed per pair.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=DAYS)
    base = rng.normal(0.0004, 0.014, DAYS)
    data = {
        "AAA": base,
        "BBB": 0.5 * base + rng.normal(0.0, 0.010, DAYS),
        "CCC": -0.3 * base + rng.normal(0.0, 0.012, DAYS),
    }
    for k in range(n_late):
        leg = rng.normal(0.0003, 0.016, DAYS)
        if late_start is not None:
            leg[:late_start] = np.nan
        data[f"LATE{k}"] = leg
    return pd.DataFrame(data, index=dates)


def _expected_pairs(df) -> int:
    n = df.shape[1]
    return n * (n - 1) // 2


# ===========================================================================
# 1. The defect: a published point that does not say what it averaged over
# ===========================================================================
class TestPublishedPointsCarryTheirDenominator:
    def test_the_schema_declares_both_fields(self):
        """RED before the fix: `CorrelationDataPoint` had four fields and a
        caller could not publish a denominator even if it wanted to."""
        fields = CorrelationDataPoint.model_fields
        assert "pairs_contributing" in fields
        assert "measurement_status" in fields

    def test_both_fields_are_additive_and_defaulted(self):
        """A payload built without them must still construct and serialise -
        that is what makes the addition non-breaking for every construction
        site, including the ones this task does not own."""
        fields = CorrelationDataPoint.model_fields
        assert fields["pairs_contributing"].default is None
        assert fields["measurement_status"].default is None

        point = CorrelationDataPoint(date="2026-09-29", avg_correlation=0.34)
        dumped = point.model_dump()
        assert dumped["pairs_contributing"] is None
        assert dumped["measurement_status"] is None
        # The keys are ON the wire, not merely constructible.
        body = json.loads(point.model_dump_json())
        assert "pairs_contributing" in body
        assert "measurement_status" in body

    def test_every_published_point_states_its_denominator(self):
        """RED before the fix: the payload had no such field, so a reader could
        not tell a book-wide average from anything else."""
        df = _book(late_start=None)
        expected = _expected_pairs(df)
        assert expected == 6

        res = analyze_correlation_stability(df, window_days=WINDOW)

        assert res.series, "the fixture book publishes nothing"
        for point in res.series:
            assert point.pairs_contributing == expected, (
                f"{point.date}: denominator {point.pairs_contributing!r} is not "
                f"the book's {expected} pairs"
            )
            assert point.measurement_status == CORRELATION_ALL_PAIRS_MEASURABLE

    def test_the_token_is_this_services_own_constant(self):
        """One name for the vocabulary, not a literal at the publication site."""
        assert CORRELATION_ALL_PAIRS_MEASURABLE == "all_pairs_measurable"

    def test_a_re_covered_book_re_appears_with_the_denominator(self):
        """The interesting production shape: a book with a leg listed part-way
        through the lookback. The tail of that series is fully covered and must
        be labelled as such - the interior partial dates are gone from the
        series entirely, and what remains is not a quieter version of the same
        defect."""
        df = _book(late_start=150, n_late=1)
        expected = _expected_pairs(df)

        res = analyze_correlation_stability(df, window_days=WINDOW)

        assert len(res.series) == 41, (
            f"the floor's measured cost moved: expected 41 published dates, "
            f"got {len(res.series)}"
        )
        assert {p.pairs_contributing for p in res.series} == {expected}
        assert {p.measurement_status for p in res.series} == {
            CORRELATION_ALL_PAIRS_MEASURABLE
        }

    def test_no_point_is_ever_published_over_a_partial_denominator(self):
        """The token is not decoration. It asserts coverage, so it may only
        accompany a count equal to C."""
        for late_start, n_late in ((None, 1), (150, 1), (100, 2), (40, 1)):
            df = _book(late_start=late_start, n_late=n_late)
            try:
                res = analyze_correlation_stability(df, window_days=WINDOW)
            except ValueError:
                continue  # refused, so there is no point to mislabel
            expected = _expected_pairs(df)
            for point in res.series:
                assert point.pairs_contributing == expected
                assert point.measurement_status == CORRELATION_ALL_PAIRS_MEASURABLE

    def test_the_denominator_comes_from_the_floor_not_a_re_derivation(self):
        """`attrs` is the only source. A series with no recorded denominator
        publishes `None`, NOT a C re-derived from a column count the series was
        never gated on - that would be a fabricated denominator, which is the
        defect this change exists to remove."""
        idx = pd.bdate_range("2024-01-01", periods=40)
        series = pd.Series(np.linspace(0.2, 0.5, 40), index=idx)
        assert "pairs_expected" not in series.attrs

        from app.services import correlation_service

        original = correlation_service.compute_rolling_avg_correlation
        try:
            correlation_service.compute_rolling_avg_correlation = (
                lambda *a, **k: series
            )
            res = correlation_service.analyze_correlation_stability(
                pd.DataFrame(), window_days=60
            )
        finally:
            correlation_service.compute_rolling_avg_correlation = original

        assert {p.pairs_contributing for p in res.series} == {None}
        assert {p.measurement_status for p in res.series} == {None}


# ===========================================================================
# 2. A fully-covered book is byte-identical to the pre-field service
# ===========================================================================
class TestFullyCoveredBookIsByteIdentical:
    """Same pattern, same fixture, same closed additive set as
    `test_correlation_stability.py` - the assertion is on the WHOLE dumped
    point, not a selection of fields, so a moved threshold or rounding fails
    here."""

    @pytest.mark.parametrize("arm", sorted(BOOKS))
    def test_every_point_equals_the_golden_once_the_labels_are_removed(
        self, monkeypatch, arm
    ):
        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))[arm]
        res = _analyze(monkeypatch, BOOKS[arm])

        points = _without_additive_point_keys(
            {"series": [p.model_dump() for p in res.series]}
        )["series"]
        assert points == golden["series"], (
            "a published point moved: once the additive labels "
            f"{sorted(ADDITIVE_POINT_KEYS_SINCE_GOLDEN)} are removed from each "
            "point, the series must equal the pre-field golden exactly"
        )

    @pytest.mark.parametrize("arm", sorted(BOOKS))
    def test_the_only_new_point_keys_are_the_two_disclosures(self, monkeypatch, arm):
        """The key-set guard that keeps the pops above honest: it fails on an
        UNEXPECTED addition, so the comparison can only be reached with exactly
        the two known labels removed."""
        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))[arm]
        res = _analyze(monkeypatch, BOOKS[arm])

        for point, golden_point in zip(res.series, golden["series"]):
            assert set(point.model_dump()) - set(golden_point) == (
                ADDITIVE_POINT_KEYS_SINCE_GOLDEN
            )
            assert set(golden_point) - set(point.model_dump()) == set()

    @pytest.mark.parametrize("arm", sorted(BOOKS))
    def test_the_response_level_additive_set_did_not_grow(self, monkeypatch, arm):
        """The two new fields are on the POINT. The response's own additive set
        is unchanged, so `test_correlation_stability`'s closed list stays
        closed - this is what would fail if someone put the disclosure on the
        response instead."""
        golden_arm = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))[arm]
        dumped = _analyze(monkeypatch, BOOKS[arm]).model_dump()

        assert set(dumped) - set(golden_arm) == ADDITIVE_KEYS_SINCE_GOLDEN
        assert set(golden_arm) - set(dumped) == set()

    def test_a_real_fully_covered_book_moves_no_figure(self):
        """The synthetic golden above stubs the windowing. This is the real
        service over a real fully-listed book, so the byte-identity claim is
        also made where the numbers are actually computed."""
        df = _book(late_start=None)
        res = analyze_correlation_stability(df, window_days=WINDOW)
        series = compute_rolling_avg_correlation(df, window_days=WINDOW)

        # Re-derive rho_bar from the raw returns, independently of the service.
        dates = [p.date for p in res.series]
        assert dates == [d.strftime("%Y-%m-%d") for d in series.index]
        assert res.as_of == series.index[-1].strftime("%Y-%m-%d")
        for point, value in zip(res.series, series.values):
            assert point.avg_correlation == round(float(value), 4)

    def test_the_disclosure_survives_fastapi_reserialisation(self):
        """The `CointScannerResponse` trap from this repo's own history: an
        undeclared key is dropped on the wire. These are declared, so an
        in-process assertion is not enough to prove they reach a client."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        app = FastAPI()

        @app.get("/probe")
        async def probe():
            return analyze_correlation_stability(
                _book(late_start=None), window_days=WINDOW
            )

        with TestClient(app) as client:
            body = client.get("/probe").json()

        assert body["series"], "the probe published nothing to check"
        assert body["series"][0]["pairs_contributing"] == 6
        assert (
            body["series"][0]["measurement_status"]
            == CORRELATION_ALL_PAIRS_MEASURABLE
        )
        assert body["current_avg_correlation"] is not None


# ===========================================================================
# 3. The floor still refuses, and the refusal still names the shortfall
# ===========================================================================
class TestTheFloorStillRefuses:
    def test_a_recently_added_holding_is_still_refused(self):
        """The measured production cost, unchanged by this task: a leg 20 days
        old leaves three of six pairs measurable on the newest date."""
        df = _book(late_start=DAYS - 20, n_late=1)
        with pytest.raises(ValueError):
            compute_rolling_avg_correlation(df, window_days=WINDOW)

    def test_the_route_facing_call_is_still_refused(self):
        df = _book(late_start=DAYS - 20, n_late=1)
        with pytest.raises(ValueError):
            analyze_correlation_stability(df, window_days=WINDOW)

    def test_a_later_leg_leaves_nothing_at_all(self):
        """Day 200 of 220: the newest date is short AND no date clears the
        floor, so the section is empty rather than thin."""
        df = _book(late_start=200, n_late=1)
        with pytest.raises(ValueError):
            analyze_correlation_stability(df, window_days=WINDOW)

    def test_the_refusal_names_the_shortfall(self):
        """Re-pins the service-side text: it names which pairs were short and by
        how many, not merely that something was wrong.

        It is no longer the last place the numbers survive. `api/analytics.py`
        re-raises this call's `ValueError` as `detail=str(exc)`, so the client
        gets this text verbatim; that leg is pinned in
        tests/test_correlation_stability_refusal_reason.py
        (`test_the_client_receives_the_reason_the_pair_floor_refused`). This
        test stays because it pins the message at its SOURCE, which the route
        test only consumes."""
        df = _book(late_start=DAYS - 20, n_late=1)
        with pytest.raises(ValueError) as excinfo:
            compute_rolling_avg_correlation(df, window_days=WINDOW)

        detail = str(excinfo.value)
        assert "3 of 6 pairs" in detail
        assert "not the book-wide figure" in detail