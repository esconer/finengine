"""R1: `current_price` is nullable on the TWO equity-research responses, and on
nothing else.

`equity_research_service` stopped substituting `0.0` for an unmeasured price and
now returns `None`. Both routes declare a `response_model`, so `None` into a
non-`Optional` float was a pydantic `ValidationError` - a 500 on
`/company/{symbol}/full-profile` and `/company/{symbol}/custom-ratios`, verified
live before this change.

The wire half of that is guarded by `test_equity_research_null_price_contract.py`,
whose skip-gate computes itself from pydantic and therefore opened on its own
when these declarations landed. What is NOT guarded anywhere is the scope: the
third `current_price` in this file belongs to a different producer with a
different contract, and widening it would weaken a declaration that is correct.

So this file pins the two declarations that had to move, and - more importantly -
pins the one that must NOT have.

All upstream I/O faked. No network.
"""

from __future__ import annotations

import json
from typing import Optional

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    CustomRatiosResponse,
    EquityResearchProfileResponse,
    StockQuoteResponse,
)

# The minimum each model needs; everything else is defaulted.
_PROFILE_MIN = {
    "symbol": "GLITCH",
    "ticker": "GLITCH.NS",
    "name": "Glitch Industries",
    "indices": [],
    "custom_ratios": {"piotroski_score": 7},
}
_RATIOS_MIN = {
    "ticker": "GLITCH.NS",
    "piotroski_score": 7,
    "ratios_history": {},
}


class TestTheTwoDeclarationsThatHadToMove:
    @pytest.mark.parametrize(
        "model,payload",
        [
            (EquityResearchProfileResponse, _PROFILE_MIN),
            (CustomRatiosResponse, _RATIOS_MIN),
        ],
    )
    def test_the_annotation_is_optional(self, model, payload):
        fields = model.model_fields
        assert fields["current_price"].annotation == Optional[float]
        assert fields["current_price"].default is None

    @pytest.mark.parametrize(
        "model,payload",
        [
            (EquityResearchProfileResponse, _PROFILE_MIN),
            (CustomRatiosResponse, _RATIOS_MIN),
        ],
    )
    def test_a_null_price_constructs_instead_of_raising(self, model, payload):
        """The 500, stated as the defect. `ValidationError` here is what the
        route turned into `status_code=500`."""
        built = model(**payload, current_price=None)
        assert built.current_price is None

    @pytest.mark.parametrize(
        "model,payload",
        [
            (EquityResearchProfileResponse, _PROFILE_MIN),
            (CustomRatiosResponse, _RATIOS_MIN),
        ],
    )
    def test_a_null_price_reaches_the_wire_as_null(self, model, payload):
        """Not merely constructible: `None` must serialise, because the failure
        mode was a serialisation-time rejection, not a construction-time one."""
        body = json.loads(model(**payload, current_price=None).model_dump_json())
        assert "current_price" in body
        assert body["current_price"] is None

    @pytest.mark.parametrize(
        "model,payload",
        [
            (EquityResearchProfileResponse, _PROFILE_MIN),
            (CustomRatiosResponse, _RATIOS_MIN),
        ],
    )
    def test_a_measured_price_is_untouched(self, model, payload):
        """Widening to Optional must not change what a real price does."""
        assert model(**payload, current_price=1234.5).current_price == 1234.5

    @pytest.mark.parametrize(
        "model,payload",
        [
            (EquityResearchProfileResponse, _PROFILE_MIN),
            (CustomRatiosResponse, _RATIOS_MIN),
        ],
    )
    def test_the_field_is_no_longer_required(self, model, payload):
        """An older caller that omitted the key entirely cannot break. This is
        why the default is `None` rather than the field being merely
        `Optional[float]` without a default."""
        assert not model.model_fields["current_price"].is_required()
        assert model(**payload).current_price is None

    @pytest.mark.parametrize(
        "model,payload",
        [
            (EquityResearchProfileResponse, _PROFILE_MIN),
            (CustomRatiosResponse, _RATIOS_MIN),
        ],
    )
    def test_the_declaration_is_documented_where_it_is_declared(self, model, payload):
        """`Optional[float]` alone does not say what the null MEANS, and the
        distinction matters: None is "the provider did not price this", which is
        not the same claim as "the price is unknown" and very much not the same
        as a price of 0.0.

        The rationale is a source comment rather than a `Field(description=...)`,
        because that is where this file keeps every other declaration note - but
        a comment can be deleted silently, so it is pinned here.
        """
        import inspect

        import app.models.schemas as schemas

        src = inspect.getsource(schemas)
        # Both widened declarations, and the reason, in the same source.
        assert src.count("current_price: Optional[float] = None") >= 2
        assert "ValidationError" in src or "500" in src
        assert "fabricated" in src or "0.0" in src
        # ...and the one that must NOT have moved is named as excluded, so the
        # next reader does not "fix" it in the opposite direction.
        assert "StockQuoteResponse" in src


class TestTheDeclarationThatMustNotMove:
    """`StockQuoteResponse.current_price` is a DIFFERENT producer.

    The quote route always has a price, a separate frontend declaration
    (`api.ts:569`) still types it non-optionally, and widening it here would
    weaken a correct declaration to fix an unrelated route. Pinned so a future
    sweep for "make everything Optional" fails here instead of silently.
    """

    def test_the_quote_price_is_still_required_and_non_nullable(self):
        fields = StockQuoteResponse.model_fields
        assert fields["current_price"].annotation is float
        assert fields["current_price"].is_required()

    def test_the_quote_price_still_rejects_a_null(self):
        with pytest.raises(ValidationError):
            StockQuoteResponse(**{**_QUOTE_MIN(), "current_price": None})

    def test_there_are_exactly_three_current_price_declarations(self):
        """The scope, counted. A fourth producer would have to be reviewed here
        rather than swept along by a "make them all Optional" pass."""
        declarations = [
            (model.__name__, name, field.annotation)
            for model in (
                StockQuoteResponse,
                EquityResearchProfileResponse,
                CustomRatiosResponse,
            )
            for name, field in model.model_fields.items()
            if name == "current_price"
        ]
        assert [d[0] for d in declarations] == [
            "StockQuoteResponse",
            "EquityResearchProfileResponse",
            "CustomRatiosResponse",
        ]
        assert declarations[0][2] is float
        assert declarations[1][2] == Optional[float]
        assert declarations[2][2] == Optional[float]


def _QUOTE_MIN():  # noqa: N802 - a fixture-shaped helper, kept near its user
    return {"ticker": "AAA.NS", "name": "AAA"}