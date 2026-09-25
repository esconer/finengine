"""Route-layer gates for V3-08 and V3-09 (ticket 06, route half).

V3-08: the sector loop rounded a RUNNING PARTIAL SUM, so N positions each added
up to 5e-5 of error. v3 published `Industrials=0.0984` where the exact weight is
0.0983, and a displayed total of 1.0001. The fix accumulates raw, rounds once,
orders deterministically, and publishes the total plus the display-only
rounding residual instead of redistributing it.

V3-09: liquidity reported a score with no unit, no window and no observation
date, so the export's `currency` and `as_of` were guesses. The route now
publishes the monetary/volume/turnover units, the requested window beside the
ACTUAL delivered range, the newest delivered observation, and the scoring rule
(scale, band rule, thresholds, window) that produced the number.

The engine half of both findings is gated in `test_v3_semantics_liquidity_stress`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock

import numpy as np
import pandas as pd
import pytest

from app.api import analytics as analytics_mod
from app.api.analytics import (
    LIQUIDITY_SCORING_CURRENCY,
    get_concentration_metrics,
    get_liquidity_metrics,
)
from app.models.database import PortfolioPosition
from app.services.analytics_engine import LIQUIDITY_MARKET_CAP_FLOOR_INR


# ---------------------------------------------------------------------------
# seams
# ---------------------------------------------------------------------------
def _rows(rows):
    scalars = MagicMock()
    scalars.all.return_value = list(rows)
    scalars.first.return_value = rows[0] if rows else None
    result = MagicMock()
    result.scalars.return_value = scalars
    result.scalar_one_or_none.return_value = rows[0] if rows else None
    return result


def _db(rows):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=lambda *_a, **_k: _rows(rows))
    return db


def _pos(ticker, *, market_value, sector, region="IN"):
    # `last_price` is what the route values the book from, so it carries the
    # weight this test is about.
    return PortfolioPosition(
        id=1, ticker=ticker, weight=None, quantity=1.0, buy_price=None,
        last_price=market_value, market_value=market_value, region=region,
        sector=sector, industry="Y", added_on=None,
    )


class _Market:
    """OHLCV frames keyed by ticker, sliced to the requested window.

    Quotes carry the supplied market cap, and an absent cap stays absent so the
    engine's own provenance path is exercised.
    """

    def __init__(self, frames, caps=None):
        self.frames = frames
        self.caps = caps or {}
        self.fetch_historical_data = AsyncMock(side_effect=self._history)
        self.fetch_quote = AsyncMock(side_effect=self._quote)

    async def _history(self, ticker, start, end):
        frame = self.frames.get(ticker)
        if frame is None:
            return pd.DataFrame()
        window = frame.loc[(frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))]
        return window.copy()

    async def _quote(self, ticker):
        return {"market_cap": self.caps.get(ticker)}


def _ohlcv(dates, *, price=100.0, volume=1_000_000.0):
    return pd.DataFrame(
        {"Close": np.full(len(dates), price), "Volume": np.full(len(dates), volume)},
        index=dates,
    )


# ---------------------------------------------------------------------------
# V3-08: exact sector accumulation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sector_weights_are_rounded_once_from_the_exact_sum():
    """v3 evidence: a sector published 0.0984 where the exact weight is 0.0983.

    Rounding a running partial sum rounded the FIRST leg from 0.012345 to
    0.0123, and that 5e-5 loss survived into the sector total: the old loop
    published 0.0982 for a sector whose exact weight is 0.0983. Rounding once,
    at the end, is the fix.
    """
    values = [0.012345, 0.012345, 0.07361, 0.9017]
    sectors = ["Industrials", "Industrials", "Industrials", "Energy"]
    db = _db([
        _pos(f"P{i}.NS", market_value=values[i], sector=sectors[i])
        for i in range(4)
    ])

    result = await get_concentration_metrics(
        db=db, data_service=Mock(), analytics_engine=analytics_mod.AnalyticsEngine()
    )

    running = round(round(round(0.012345, 4) + 0.012345, 4) + 0.07361, 4)
    assert running == 0.0982, "the running-rounding drift this route used to publish"
    assert result["by_sector"]["Industrials"] == 0.0983
    assert result["by_sector"]["Industrials"] == round(0.012345 + 0.012345 + 0.07361, 4)


@pytest.mark.asyncio
async def test_published_sector_total_is_one_within_1e_9():
    """The test gate: the published total is 1.0 within 1e-9."""
    db = _db([
        _pos("A.NS", market_value=0.03, sector="Energy"),
        _pos("B.NS", market_value=0.04, sector="Energy"),
        _pos("C.NS", market_value=0.28, sector="Industrials"),
        _pos("D.NS", market_value=0.65, sector="Industrials"),
    ])

    result = await get_concentration_metrics(
        db=db, data_service=Mock(), analytics_engine=analytics_mod.AnalyticsEngine()
    )

    assert abs(result["by_sector_total"] - 1.0) <= 1e-9


@pytest.mark.asyncio
async def test_no_sector_is_renormalized_to_force_a_total_of_one():
    # Three sectors whose exact weights carry a 5th decimal, so the displayed
    # map sums to 0.9999. The gap is published, never redistributed.
    db = _db([
        _pos("A.NS", market_value=0.033333, sector="Alpha"),
        _pos("B.NS", market_value=0.033333, sector="Beta"),
        _pos("C.NS", market_value=0.933334, sector="Gamma"),
    ])

    result = await get_concentration_metrics(
        db=db, data_service=Mock(), analytics_engine=analytics_mod.AnalyticsEngine()
    )

    assert result["by_sector"] == {"Gamma": 0.9333, "Beta": 0.0333, "Alpha": 0.0333}
    assert result["by_sector_published_total"] == pytest.approx(0.9999, abs=1e-9)
    assert abs(result["by_sector_total"] - 1.0) <= 1e-9
    assert result["by_sector_rounding_residual"] == pytest.approx(0.0001, abs=1e-9)
    # No sector absorbed the residual to make the displayed map total 1.0.
    assert max(result["by_sector"].values()) == 0.9333


@pytest.mark.asyncio
async def test_sector_map_is_ordered_by_weight_descending():
    db = _db([
        _pos("A.NS", market_value=1.0, sector="Tiny"),
        _pos("B.NS", market_value=50.0, sector="Large"),
        _pos("C.NS", market_value=20.0, sector="Medium"),
        _pos("D.NS", market_value=29.0, sector="Second"),
    ])

    first = await get_concentration_metrics(
        db=db, data_service=Mock(), analytics_engine=analytics_mod.AnalyticsEngine()
    )
    db2 = _db([
        _pos("C.NS", market_value=20.0, sector="Medium"),
        _pos("D.NS", market_value=29.0, sector="Second"),
        _pos("A.NS", market_value=1.0, sector="Tiny"),
        _pos("B.NS", market_value=50.0, sector="Large"),
    ])
    second = await get_concentration_metrics(
        db=db2, data_service=Mock(), analytics_engine=analytics_mod.AnalyticsEngine()
    )

    weights = [first["by_sector"][name] for name in first["by_sector"]]
    assert weights == sorted(weights, reverse=True)
    # Row order in the DB must not change the published map.
    assert list(first["by_sector"]) == list(second["by_sector"])
    assert first["by_sector"] == second["by_sector"]


@pytest.mark.asyncio
async def test_sector_weight_basis_and_residual_are_published():
    db = _db([
        _pos("A.NS", market_value=60.0, sector="Energy"),
        _pos("B.NS", market_value=40.0, sector="Energy"),
    ])

    result = await get_concentration_metrics(
        db=db, data_service=Mock(), analytics_engine=analytics_mod.AnalyticsEngine()
    )

    assert result["sector_weight_basis"] == "market_value_weights_normalized_to_100_percent"
    assert result["by_sector_rounding_decimals"] == 4
    assert result["by_sector_rounding_residual"] == 0.0
    assert result["by_sector_total"] == result["by_sector_published_total"] == 1.0


@pytest.mark.asyncio
async def test_unmeasured_sector_total_claims_nothing():
    result = await get_concentration_metrics(
        db=_db([]), data_service=Mock(), analytics_engine=Mock()
    )

    assert result["by_sector_total"] == 0.0
    assert result["by_sector_rounding_residual"] is None
    assert result["sector_weight_basis"] is None
    assert result["data_status"] == "unavailable"


# ---------------------------------------------------------------------------
# V3-09: liquidity units, window and scoring disclosure
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_liquidity_publishes_currency_units_and_as_of():
    dates = pd.bdate_range(end=pd.Timestamp("2026-09-22"), periods=20)
    db = _db([_pos("AAA.NS", market_value=100000.0, sector="Energy")])

    result = await get_liquidity_metrics(
        db=db,
        data_service=_Market({"AAA.NS": _ohlcv(dates, price=100.0, volume=600_000.0)}),
        analytics_engine=analytics_mod.AnalyticsEngine(),
    )

    assert result["currency"] == result["base_currency"] == LIQUIDITY_SCORING_CURRENCY
    assert result["currency_provenance"] == "derived"
    assert result["monetary_unit"] == "rupees"
    assert result["volume_unit"] == "shares"
    assert result["turnover_unit"] == "rupees_per_session"
    # Freshness is the newest delivered bar, never the requested end.
    assert result["latest_observation_date"] == "2026-09-22"
    assert result["observation_window"]["end"] == "2026-09-22"
    assert result["data_range"]["end"] > result["latest_observation_date"]


@pytest.mark.asyncio
async def test_liquidity_requested_window_is_separate_from_the_delivered_one():
    """v3 evidence: a 30-day request whose newest bar was 3 days old."""
    dates = pd.bdate_range(end=pd.Timestamp("2026-09-22"), periods=20)
    db = _db([_pos("AAA.NS", market_value=100000.0, sector="Energy")])

    result = await get_liquidity_metrics(
        db=db,
        data_service=_Market({"AAA.NS": _ohlcv(dates)}),
        analytics_engine=analytics_mod.AnalyticsEngine(),
    )

    requested = result["data_range"]
    delivered = result["observation_window"]
    expected = int(len(pd.bdate_range(requested["start"], requested["end"])))
    # The request ends after the newest delivered bar: the gap is published
    # instead of being papered over with the requested end.
    assert requested["end"] > delivered["end"]
    assert delivered["start"] >= requested["start"]
    assert delivered["per_ticker"]["AAA.NS"]["observations"] < expected
    assert delivered["ticker_count"] == 1
    assert result["requested_days"] == int(
        (pd.Timestamp(requested["end"]) - pd.Timestamp(requested["start"])).days
    )


@pytest.mark.asyncio
async def test_liquidity_publishes_the_scoring_rule_and_thresholds():
    dates = pd.bdate_range(end=pd.Timestamp("2026-09-22"), periods=20)
    db = _db([_pos("AAA.NS", market_value=100000.0, sector="Energy")])

    result = await get_liquidity_metrics(
        db=db,
        data_service=_Market(
            {"AAA.NS": _ohlcv(dates)}, caps={"AAA.NS": 2.0e11}
        ),
        analytics_engine=analytics_mod.AnalyticsEngine(),
    )

    scoring = result["scoring"]
    assert scoring["scale"] == {
        "min": 2.5, "max": 10.0, "unit": "index_0_to_10"
    }
    assert scoring["raw_score_field"] == "score_raw"
    assert scoring["published_score_field"] == "score"
    assert scoring["band_source"] == "published_score"
    bands = scoring["thresholds"]
    assert [(b["band"], b["min_published_score"]) for b in bands] == [
        ("High", 8.0), ("Medium", 6.0), ("Low", None)
    ]
    assert scoring["requested_window"] == result["data_range"]
    assert scoring["observation_window"] == result["observation_window"]
    assert scoring["market_cap_floor"]["value"] == LIQUIDITY_MARKET_CAP_FLOOR_INR
    assert scoring["market_cap_floor"]["provenance"] == "fallback"
    assert scoring["unavailable_reason"] is None
    assert scoring["measured_positions"] == ["AAA.NS"]
    # The raw score, the rounded score and the band all travel together.
    row = result["by_position"]["AAA.NS"]
    assert row["score"] == round(row["score_raw"], 1)
    assert result["overall_band"] == row["category"]


@pytest.mark.asyncio
async def test_selectipo_market_cap_floor_is_never_silent():
    dates = pd.bdate_range(end=pd.Timestamp("2026-09-22"), periods=20)
    db = _db([_pos("SELECTIPO.NS", market_value=1000.0, sector="Energy")])

    result = await get_liquidity_metrics(
        db=db,
        data_service=_Market({"SELECTIPO.NS": _ohlcv(dates, price=10.0, volume=1_000.0)}),
        analytics_engine=analytics_mod.AnalyticsEngine(),
    )

    row = result["by_position"]["SELECTIPO.NS"]
    assert row["market_cap"] == LIQUIDITY_MARKET_CAP_FLOOR_INR
    assert row["market_cap_provenance"] == "fallback"
    assert row["is_estimate"] is True
    assert result["scoring"]["market_cap_floor"]["provenance"] == "fallback"


@pytest.mark.asyncio
async def test_unavailable_liquidity_claims_no_window_or_date():
    db = _db([_pos("AAA.NS", market_value=100000.0, sector="Energy")])

    result = await get_liquidity_metrics(
        db=db,
        data_service=_Market({}),
        analytics_engine=analytics_mod.AnalyticsEngine(),
    )

    assert result["data_status"] == "unavailable"
    assert result["latest_observation_date"] is None
    assert result["observation_window"]["start"] is None
    assert result["observation_window"]["end"] is None
    assert result["by_position"] == {}
    # The unit is still declared (it is a property of the rule, not the data).
    assert result["currency"] == LIQUIDITY_SCORING_CURRENCY
    assert result["overall_score"] is None
