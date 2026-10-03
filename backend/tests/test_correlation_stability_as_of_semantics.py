"""`as_of_semantics` on `/analytics/correlation-stability` - the additive fix.

The fewer-than-two-holdings branch publishes `as_of = datetime.now()` beside
`current_avg_correlation: None`, `data_status: "unavailable"` and an empty
series: a date with no observation behind it. The `/analytics/coint` sibling
labels exactly this situation on its own fewer-than-two-tickers branch
(`COINT_NO_PAIR_UNIVERSE_AS_OF_SEMANTICS`), and correlation-stability had NO
field to carry a label at all - not because the route omitted one, but because
FastAPI re-serializes a route's response against the DECLARED `response_model`
and `CorrelationStabilityResponse` declared none. That is the trap documented in
`CointScannerResponse`'s own docstring ("the AI path is audited, the direct API
path is not"), and it is why every wire assertion here goes through an actual
HTTP response body rather than the returned model: a test that only inspected
the dict would have passed with the key silently stripped.

What is pinned here, in order of how much it matters:

* the single-holding branch labels the date it publishes (RED before the fix);
* only the label moved - `as_of` is byte-identical to the pre-fix body, and so
  is every other published key, because relabelling a figure is not the fix and
  moving one would be a second, unrequested change;
* `as_of` stays REQUIRED and non-nullable. Widening it to `Optional[str]` was
  the rejected alternative: this route is one of the `risk-studio` `componentDates`
  legs, which is filtered by `typeof value === 'string'`, so a null date would
  drop the correlation leg out of `oldestComponentDate` and decrement
  `legsReportingFreshness` on a page this change does not own;
* the field is ADDITIVE - a payload built without it still serialises, so no
  construction site HAD to change. `correlation_service` does set one now
  (`latest_available_observation`, because its `as_of` is a delivered bar), which
  is a label beside the figures rather than a change to any of them;
* the token is this route's own. The coint sibling labels the same cause for a
  different question - "no pair to TEST" against "no pair to CORRELATE" - so
  neither token is reused, and a consumer can tell which route said what.

No network: this branch returns before any price fetch.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.api import analytics as analytics_mod
from app.models.schemas import CorrelationStabilityResponse

#: Read-only: the payload the service published before `alert_direction`
#: existed, used below to prove this change moved no measured number.
GOLDEN_PATH = (
    Path(__file__).parent / "fixtures" / "correlation_stability_pre_direction.json"
)

#: One rolling series per alert arm, so a different comparison decides each.
_BOOKS: Dict[str, List[float]] = {
    # 0.1483 at/below p10 (0.1931) against a 0.34 median.
    "lower_tail_collapse": list(
        np.concatenate([np.linspace(0.16, 0.34, 50), np.linspace(0.34, 0.56, 50)])
    )
    + [0.1483],
    # 0.55 at/above p75 (0.30), below p90 (0.90).
    "upper_tail_elevation": [0.30] * 85 + [0.90] * 15 + [0.55],
    # p10 (0.2303) < 0.34 < p75 (0.4242).
    "within_band": list(np.linspace(0.20, 0.50, 100)) + [0.34],
    # 0.61 at/above p90.
    "upper_tail_critical": [0.30] * 100 + [0.61],
}

#: The single-holding body exactly as this route published it BEFORE
#: `as_of_semantics` existed, captured from the live HTTP response with
#: `as_of` removed. Every remaining value is fixed, so it must survive the fix
#: verbatim; `as_of` is asserted separately because it is the request end and
#: moves with the calendar.
PRE_FIX_SINGLE_HOLDING_BODY: Dict[str, Any] = {
    "current_avg_correlation": None,
    "historical_threshold_90th": None,
    "historical_threshold_75th": None,
    "historical_threshold_10th": None,
    "historical_median": None,
    "is_regime_break": False,
    "alert_level": "NORMAL",
    "alert_direction": None,
    "message": "Single holding portfolio: pairwise correlation is undefined.",
    "series": [],
    "requested_tickers": ["ALPHA.NS"],
    "available_tickers": [],
    "missing_tickers": ["ALPHA.NS"],
    "data_status": "unavailable",
    "universe_coverage": {
        "requested_tickers": ["ALPHA.NS"],
        "available_tickers": [],
        "covered_tickers": [],
        "missing_tickers": ["ALPHA.NS"],
        "requested_count": 1,
        "available_count": 0,
        "coverage_ratio": 0.0,
        "complete": False,
        "status": "unavailable",
    },
}


async def _single_holding_body(async_client) -> Dict[str, Any]:
    """The wire body of `GET /correlation-stability` on one explicit ticker."""
    response = await async_client.get(
        "/api/v1/analytics/correlation-stability",
        params={"tickers": "ALPHA.NS"},
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestTheSingleHoldingBranchPublishesWhatItsDateMeans:
    @pytest.mark.asyncio
    async def test_the_token_reaches_the_http_body(self, async_client):
        """RED before the fix: `CorrelationStabilityResponse` declared no such
        key, so FastAPI dropped it from the wire even if the route set it."""
        body = await _single_holding_body(async_client)

        assert "as_of_semantics" in body, sorted(body)
        assert (
            body["as_of_semantics"]
            == analytics_mod.CORRELATION_NO_PAIR_UNIVERSE_AS_OF_SEMANTICS
        )
        # The situation being labelled: no measurement, and the payload says so
        # beside the date.
        assert body["current_avg_correlation"] is None
        assert body["data_status"] == "unavailable"
        assert body["series"] == []

    @pytest.mark.asyncio
    async def test_the_token_does_not_claim_an_observation(self, async_client):
        body = await _single_holding_body(async_client)
        token = body["as_of_semantics"]

        assert token != "latest_available_observation", (
            "a branch that measured no observation cannot be labelled as though "
            "it did"
        )
        assert token != "request_end_no_usable_price_data", (
            "this branch never asked for a price series - there is no pair to "
            "correlate - so a no-price-data token reports a data problem where "
            "the cause is the universe"
        )
        assert "universe" in token

    def test_the_token_is_this_routes_own_constant(self):
        """A named module constant, not an inline literal, so a reader (and the
        frontend) has one name for it."""
        token = analytics_mod.CORRELATION_NO_PAIR_UNIVERSE_AS_OF_SEMANTICS
        assert token == "request_end_universe_too_small_for_pairwise_correlation"
        # Same shape as the sibling token it sits beside: `request_end_` + the
        # cause + what was missing.
        assert token.startswith("request_end_")
        # NOT reused: one false statement, one place.
        assert token != analytics_mod.COINT_NO_PAIR_UNIVERSE_AS_OF_SEMANTICS
        source = inspect.getsource(analytics_mod.get_correlation_stability)
        assert source.count(
            "as_of_semantics=CORRELATION_NO_PAIR_UNIVERSE_AS_OF_SEMANTICS"
        ) == 1
        assert "COINT_NO_PAIR_UNIVERSE_AS_OF_SEMANTICS" not in source

    def test_the_branch_relabels_without_moving_the_date(self):
        """The date expression is untouched: this is a relabelling, not a
        recomputation - the same trade the coint fix made."""
        source = inspect.getsource(analytics_mod.get_correlation_stability)
        assert source.count('as_of=datetime.now().strftime("%Y-%m-%d")') == 1


class TestNothingElseMoved:
    @pytest.mark.asyncio
    async def test_as_of_is_byte_identical_before_and_after(self, async_client):
        body = await _single_holding_body(async_client)

        as_of = body.pop("as_of")
        # The date is still the request end, exactly as before the fix: the
        # published figure did not move, only the claim about it did.
        assert as_of == datetime.now().strftime("%Y-%m-%d"), as_of

        body.pop("as_of_semantics", None)  # the one additive key
        assert body == PRE_FIX_SINGLE_HOLDING_BODY

    def test_as_of_is_still_required_and_non_nullable(self):
        """The rejected alternative was `as_of: Optional[str]`. This route is a
        `risk-studio` `componentDates` leg filtered by
        `typeof value === 'string'`, so a null date would drop the leg from
        `oldestComponentDate` and decrement `legsReportingFreshness`."""
        fields = CorrelationStabilityResponse.model_fields

        assert fields["as_of"].is_required()
        assert fields["as_of"].annotation is str
        assert fields["as_of_semantics"].annotation == Optional[str]
        assert fields["as_of_semantics"].default is None

    @pytest.mark.asyncio
    async def test_the_only_new_key_is_the_semantics_label(self, async_client):
        body = await _single_holding_body(async_client)
        pre_fix_keys = set(PRE_FIX_SINGLE_HOLDING_BODY) | {"as_of"}

        assert set(body) - pre_fix_keys == {"as_of_semantics"}
        assert pre_fix_keys - set(body) == set()

    @pytest.mark.parametrize("arm", sorted(_BOOKS))
    def test_the_measured_branch_moved_no_number(self, monkeypatch, arm):
        """The measured branch is the one this change is NOT allowed to touch,
        so it is compared against the captured pre-`alert_direction` golden: the
        whole dumped dict, minus the two labels added since, has to equal the
        payload the unmodified service produced for the same book. Both popped
        keys are labels rather than figures, so popping them cannot hide a moved
        number - the key-set assertion above is what keeps that honest.

        The measured branch's own label is `latest_available_observation`: its
        `as_of` is `avg_corr_series.index[-1]`, a real delivered bar, and
        `correlation_service` holds no clock to name anything else. `None` still
        means "not recorded" (see the model docstring), but this is no longer the
        site that demonstrates it - both production branches publish a token, so
        `None` is reachable only by building the model without one."""
        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))[arm]
        dumped = self._measure(monkeypatch, _BOOKS[arm]).model_dump()

        assert set(dumped) - set(golden) == {"alert_direction", "as_of_semantics"}
        assert set(golden) - set(dumped) == set()
        assert dumped.pop("alert_direction") == arm
        assert dumped.pop("as_of_semantics") == "latest_available_observation"
        # The golden's `series` entries predate the pair-denominator disclosure,
        # which is additive on the POINT (two labels beside each figure). Same
        # closed-set discipline as the response-level pops above: pop exactly
        # those two from every point, then compare the whole payload.
        for point in dumped["series"]:
            assert set(point) - set(
                golden["series"][0]
            ) == {"pairs_contributing", "measurement_status"}
            point.pop("pairs_contributing")
            point.pop("measurement_status")
        assert dumped == golden

    @staticmethod
    def _measure(monkeypatch, values: List[float]) -> CorrelationStabilityResponse:
        """Drive the real service; only the rolling window is stubbed."""
        from app.services import correlation_service

        idx = pd.bdate_range("2024-01-01", periods=len(values))
        series = pd.Series(values, index=idx)
        monkeypatch.setattr(
            correlation_service,
            "compute_rolling_avg_correlation",
            lambda *a, **k: series,
        )
        return correlation_service.analyze_correlation_stability(
            pd.DataFrame(), window_days=60
        )


class TestTheFieldIsAdditive:
    def test_a_payload_built_without_the_key_still_serialises(self):
        """The default is a WORKING one, not a required key: a model built
        without the label still constructs, dumps and serialises, and the key
        reads null rather than raising.

        Its justification used to be that no other construction site set the
        label. Both do now - the measured branch publishes
        `latest_available_observation` - so no production payload reaches this
        shape. What is pinned instead is the compatibility half: an older caller
        that predates the field cannot break by omitting it, which is why the
        field was declared `Optional[str] = None` rather than required."""
        res = CorrelationStabilityResponse(
            as_of="2026-09-29",
            current_avg_correlation=0.1483,
            is_regime_break=True,
            alert_level="ELEVATED",
            message="measured",
            series=[],
        )

        assert res.as_of_semantics is None
        assert res.model_dump()["as_of_semantics"] is None
        assert json.loads(res.model_dump_json())["as_of_semantics"] is None

    def test_the_label_survives_fastapi_reserialisation(self):
        """The round-trip trap from `CointScannerResponse`'s docstring, proven
        in the direction that matters now: declared, it reaches the wire. An
        in-process-only assertion cannot tell the two apart."""
        app = FastAPI()

        @app.get("/probe", response_model=CorrelationStabilityResponse)
        async def probe():
            return CorrelationStabilityResponse(
                as_of="2026-10-03",
                is_regime_break=False,
                alert_level="NORMAL",
                message="probe",
                series=[],
                as_of_semantics=(
                    analytics_mod.CORRELATION_NO_PAIR_UNIVERSE_AS_OF_SEMANTICS
                ),
            )

        with TestClient(app) as client:
            body = client.get("/probe").json()

        assert body["as_of"] == "2026-10-03"
        assert (
            body["as_of_semantics"]
            == analytics_mod.CORRELATION_NO_PAIR_UNIVERSE_AS_OF_SEMANTICS
        )


class TestTheVocabularyIsWrittenDownSomewhere:
    def test_the_model_docstring_names_every_token_in_the_vocabulary(self):
        """`as_of_semantics` is a free-form `str`: no enum, no Literal, so
        nothing machine-checks it and the only place the vocabulary exists is
        prose. If the prose goes stale, the contract silently rots."""
        doc = CorrelationStabilityResponse.__doc__ or ""

        for token in (
            "latest_available_observation",
            "request_end_no_usable_price_data",
            "request_end_universe_too_small_for_pairs",
            "request_end_universe_too_small_for_pairwise_correlation",
        ):
            assert token in doc, f"{token} must be documented on the model"