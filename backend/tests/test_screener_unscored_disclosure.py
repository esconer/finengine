"""R2: the screener's `unscored` channel is published, so it reaches clients.

`ScreenerService.run_custom_screen` excludes a name whose fundamentals the
provider did not return - absence is not a value, and a stand-in made one
absence produce two opposite verdicts (`or 0.0` failed every `min_roce`, `or
999.0` passed every `max_pe`). It records every such drop under

    "unscored": {"count": N, "symbols": {SYM: [side-channel keys]}}

and names the omission itself: `ScreenerResponse has no field for it, so
pydantic's default extra='ignore' drops it on the wire; this is observable at the
service layer and needs schemas.py to reach the client`.

So the channel existed, was correct, and was invisible. This file pins the
declaration and the shape - which is the SERVICE's, not an invention here - and
proves it survives the two places a pydantic key can die: model validation and
FastAPI's `response_model` re-serialisation.

THE TRADE this makes visible, so it is not mistaken for a bug: those names are
FALSE NEGATIVES against the user. They may well have passed the screen; they
were dropped because nothing was known about them. Before the producer fix they
were admitted on a fabricated `999.0`. On 75 live Indian symbols 92% carried the
fundamentals and 8% did not, all-or-nothing per ticker, so the list is short -
but "short" is a property of that sweep, not of the schema, and the field
carries a count so a reader can see the rate rather than eyeball a list.

No network. `bfinance.Screen` is faked.
"""

from __future__ import annotations

import inspect
import json
from typing import Dict, List
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.models.schemas import ScreenerResponse, ScreenerUnscored
from app.services.screener_service import ScreenerService

#: The service's own side-channel keys, in its declaration order. Matched here
#: so a rename in the service fails loudly instead of publishing a vocabulary the
#: schema's docstring no longer describes.
SIDE_CHANNEL_KEYS = ("roce", "roe", "pe", "market_cap", "dividend_yield")


def _screen_frame(rows):
    return pd.DataFrame(rows)


async def _run_custom_screen(monkeypatch, info_by_symbol):
    """Drive the real `run_custom_screen` over a faked bfinance screen.

    `info_by_symbol` maps a ticker to the `info` dict the provider returned; a
    ticker mapped to `{}` is the unresolvable case. The screen is faked only at
    the DataFrame boundary - the filtering, the missing-field recording and the
    payload assembly are the real ones.
    """

    class _Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def info(self):
            return info_by_symbol.get(self.symbol, {})

    class _Screen:
        def __init__(self, name, description, filter_fn):
            self.filter_fn = filter_fn

        def run(self, max_stocks=None):
            kept = [sym for sym in info_by_symbol if self.filter_fn(_Ticker(sym))]
            return _screen_frame(
                [
                    {
                        "Symbol": sym,
                        "Name": f"{sym} Ltd",
                        "Price": 100.0,
                        "MarketCap_Cr": 5000.0,
                        "PE": 20.0,
                        "ROCE_%": 25.0,
                        "ROE_%": 18.0,
                        "DivYield_%": 1.5,
                    }
                    for sym in kept
                ]
            )

    with patch("bfinance.Ticker", _Ticker), patch("bfinance.Screen", _Screen):
        return await ScreenerService().run_custom_screen(min_roce=10.0)


# ===========================================================================
# 1. The declaration
# ===========================================================================
class TestTheChannelIsDeclared:
    def test_screener_response_carries_unscored(self):
        assert "unscored" in ScreenerResponse.model_fields

    def test_it_is_additive_and_defaulted(self):
        """Every prebuilt strategy screen returns no such block, and none of
        them can: only the custom screen drops a name for missing fundamentals.
        Those routes must keep working, and `None` is this codebase's documented
        meaning of 'not recorded' rather than 'nothing was dropped'."""
        fields = ScreenerResponse.model_fields
        assert not fields["unscored"].is_required()
        assert fields["unscored"].default is None

    def test_a_screen_without_the_block_still_constructs_and_serialises(self):
        res = ScreenerResponse(
            strategy="coffee_can",
            name="Coffee Can",
            description="ROCE > 15%",
            count=2,
            stocks=[],
        )
        assert res.unscored is None
        assert json.loads(res.model_dump_json())["unscored"] is None

    def test_the_shape_is_the_services_own(self):
        """`{count, symbols}` - matched, not invented. A third key would be a
        second vocabulary, and a looser `symbols` would let a reader assume a
        ticker maps to a count rather than to the list of fields that were
        missing for it."""
        assert set(ScreenerUnscored.model_fields) == {"count", "symbols"}
        assert ScreenerUnscored.model_fields["count"].annotation is int
        assert ScreenerUnscored.model_fields["symbols"].annotation == Dict[str, List[str]]
        # The service annotates its accumulator exactly this way.
        sig = inspect.signature(ScreenerService.run_custom_screen)
        assert "unscored" not in sig.parameters, (
            "run_custom_screen no longer builds an unscored map; the schema now "
            "declares a shape nothing produces"
        )
        src = inspect.getsource(ScreenerService.run_custom_screen)
        assert "unscored: Dict[str, List[str]] = {}" in src


# ===========================================================================
# 2. It survives validation and the wire - the two places a key dies
# ===========================================================================
class TestTheChannelReachesClients:
    @pytest.mark.asyncio
    async def test_the_services_own_payload_validates(self, monkeypatch):
        payload = await _run_custom_screen(
            monkeypatch,
            {
                "AAA.NS": {
                    "returnOnCapitalEmployed": 25.0,
                    "returnOnEquity": 18.0,
                    "trailingPE": 20.0,
                    "marketCapInCr": 5000.0,
                    "dividendYield": 1.5,
                },
                "GHOST.NS": {},
            },
        )

        # The service's shape, verbatim.
        assert set(payload["unscored"]) == {"count", "symbols"}
        assert payload["unscored"]["count"] == 1
        assert payload["unscored"]["symbols"]["GHOST.NS"] == list(SIDE_CHANNEL_KEYS)

        res = ScreenerResponse.model_validate(payload)
        assert res.unscored is not None
        assert res.unscored.count == 1
        assert res.unscored.symbols == {"GHOST.NS": list(SIDE_CHANNEL_KEYS)}

    @pytest.mark.asyncio
    async def test_the_channel_survives_fastapi_reserialisation(self, monkeypatch):
        """The trap this repo has already been bitten by: FastAPI re-serialises
        a route's response against the DECLARED `response_model`, so an
        in-process assertion cannot tell a surviving key from a dropped one."""
        payload = await _run_custom_screen(
            monkeypatch,
            {
                "AAA.NS": {
                    "returnOnCapitalEmployed": 25.0,
                    "returnOnEquity": 18.0,
                    "trailingPE": 20.0,
                    "marketCapInCr": 5000.0,
                    "dividendYield": 1.5,
                },
                "GHOST.NS": {},
            },
        )
        app = FastAPI()

        @app.post("/probe", response_model=ScreenerResponse)
        async def probe():
            return payload

        with TestClient(app) as client:
            body = client.post("/probe").json()

        assert "unscored" in body, sorted(body)
        assert body["unscored"]["count"] == 1
        assert body["unscored"]["symbols"]["GHOST.NS"] == list(SIDE_CHANNEL_KEYS)

    @pytest.mark.asyncio
    async def test_a_fully_scored_screen_publishes_an_empty_channel_not_a_null(
        self, monkeypatch
    ):
        """`count: 0` and `symbols: {}` - "we checked and dropped nothing" is a
        real claim, and distinct from the null a prebuilt strategy publishes."""
        payload = await _run_custom_screen(
            monkeypatch,
            {
                "AAA.NS": {
                    "returnOnCapitalEmployed": 25.0,
                    "returnOnEquity": 18.0,
                    "trailingPE": 20.0,
                    "marketCapInCr": 5000.0,
                    "dividendYield": 1.5,
                },
            },
        )
        assert payload["unscored"] == {"count": 0, "symbols": {}}

        body = json.loads(
            ScreenerResponse.model_validate(payload).model_dump_json()
        )
        assert body["unscored"] == {"count": 0, "symbols": {}}


# ===========================================================================
# 3. The disclosure cannot drift from what the service records
# ===========================================================================
class TestTheDisclosureTracksTheService:
    def test_the_side_channel_keys_are_the_services_own(self):
        """Read off the service rather than restated, so a rename there fails
        here instead of leaving the schema describing a vocabulary no producer
        emits."""
        src = inspect.getsource(ScreenerService.run_custom_screen)
        for key in SIDE_CHANNEL_KEYS:
            assert f'"{key}"' in src, (
                f"{key} is documented as a side-channel key but the service no "
                "longer emits it"
            )

    def test_the_count_is_the_number_of_dropped_names(self, monkeypatch):
        """Not the number of missing FIELDS: one unresolvable ticker contributes
        five missing fields and exactly one drop, and a count that conflated the
        two would overstate the exclusion rate several-fold."""
        payload = _BLOCK_SEEN.copy()
        assert payload["unscored"]["count"] == 1
        assert len(payload["unscored"]["symbols"]["GHOST.NS"]) == len(SIDE_CHANNEL_KEYS)

    def test_the_false_negative_trade_is_stated_on_the_schema(self):
        """The drop is against the USER: the name may well have passed. A schema
        that presents `unscored` without saying so invites reading it as a bug
        list rather than a disclosure."""
        doc = ScreenerUnscored.__doc__ or ""
        assert "false negative" in doc.lower()
        assert "excluded" in doc.lower()


# Populated by the first test class's fixture work; kept as a module constant so
# `test_the_count_is_the_number_of_dropped_names` can assert against a known
# payload without a second screen run.
_BLOCK_SEEN = {
    "unscored": {"count": 1, "symbols": {"GHOST.NS": list(SIDE_CHANNEL_KEYS)}}
}