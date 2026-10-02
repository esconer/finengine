"""Two fabrications on the analytics layer, and one that never fired.

Defect 2 - `/analytics/coint` labelled a date it never measured.
    The fewer-than-two-tickers branch published `as_of = today` with
    `as_of_semantics = "latest_available_observation"` and
    `latest_observation_date = None` in the same object: the label claimed a
    measurement that the field beside it denied. Thirty lines down, the
    sibling branch that DID fetch prices and found none usable uses
    `request_end_no_usable_price_data` - so the token never predicted
    trustworthiness. This file pins the honest label and pins that the date
    itself did not move, because moving a published figure is not the fix.

    `/analytics/correlation-stability` had the same shape and COULD NOT be
    fixed from the route: `CorrelationStabilityResponse` declared `as_of: str`
    and no `as_of_semantics` field at all, and FastAPI re-serializes against the
    declared model, so an undeclared key never reaches the wire. The
    `CorrelationStabilityResponse` class below was that blocker's PROOF, not a
    wish: it failed the day someone added the field, which was the signal that
    the schemas.py follow-up was done. That signal FIRED, and the follow-up
    landed, so the tripwire is re-armed in the only direction still worth
    watching - it now fails if the field goes back OFF the schema, or if the
    branch that sets it publishes a token that does not describe what it
    measured. `as_of` itself did not move on that branch, and neither do these
    assertions: relabelling a figure is not the fix.

Defect 3 - `/analytics/factor-exposure` carried a dead fabrication default.
    `factor_result.get("adjusted_r_squared", 0.0)` was unreachable:
    `factor_exposure_analysis` publishes the key on every exit path it can
    take, so `.get` never saw an absent key and the `0.0` never fired. An
    unreachable default is still the wrong shape - it is exactly what a
    future edit that drops the key would silently publish as a measured zero.
    Removing it changes nothing today, and `test_the_default_was_and_is_
    unreachable` is what makes that claim checkable rather than asserted.

No network: seeded frames and stub services only.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, Mock

import numpy as np
import pandas as pd
import pytest

from app.api import analytics as analytics_mod
from app.models.database import PortfolioPosition
from app.models.schemas import CorrelationStabilityResponse
from app.services.analytics_engine import AnalyticsEngine

VOL_CONE_GOLDEN = (
    Path(__file__).parent / "fixtures" / "vol_cone_pre_lookback_publication.json"
)

#: The routes derive `start`/`end` from `datetime.now()`, so the fixture
#: frame must straddle the real clock or the requested window intersects it
#: in zero rows and the route takes its "no price data" early return. These
#: bounds clear the widest accepted lookback (756d) on either side.
BARS_BEFORE = 500
BARS_AFTER = 400


def _bdate_span() -> pd.DatetimeIndex:
    """Business days from well before to well after `datetime.now()`."""
    today = pd.Timestamp(datetime.now()).normalize()
    return pd.bdate_range(
        end=today + pd.Timedelta(days=BARS_AFTER), periods=BARS_BEFORE + BARS_AFTER
    )


def _held_ago() -> datetime:
    """A holding date inside the canonical evidence window."""
    span = _bdate_span()
    return span[BARS_BEFORE // 2].to_pydatetime()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _rows(rows):
    result = Mock()
    result.scalars.return_value.all.return_value = rows
    return result


def _db(rows):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=lambda *_a, **_k: _rows(rows))
    return db


def _pos(ticker, *, added_on, weight=0.5):
    return PortfolioPosition(
        id=1, ticker=ticker, weight=weight, quantity=10.0, buy_price=100.0,
        last_price=100.0, market_value=10000.0, region="IN",
        sector="Tech", industry="Y", added_on=added_on,
    )


class _WindowedMarket:
    """Price frames served for the REQUESTED window only."""

    def __init__(self, frames):
        self.frames = frames
        self.fetch_historical_data = AsyncMock(side_effect=self._fetch)

    async def _fetch(self, ticker, start, end):
        frame = self.frames.get(ticker)
        if frame is None or frame.empty:
            return pd.DataFrame()
        low = pd.Timestamp(start).normalize() if start else frame.index[0]
        high = pd.Timestamp(end).normalize() if end else frame.index[-1]
        return frame.loc[(frame.index >= low) & (frame.index <= high)].copy()


def _frame(ticker: str, seed: int) -> pd.DataFrame:
    dates = _bdate_span()
    rng = np.random.default_rng(seed)
    walk = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.011, len(dates))))
    return pd.DataFrame({"adj_close": pd.Series(walk, index=dates)})


def _book(one_ticker: bool = True):
    """A position row, and the mock DB that serves it to every query."""
    if one_ticker:
        return _db([_pos("A.NS", added_on=_held_ago())])
    return _db([_pos("A.NS", added_on=_held_ago()),
                 _pos("B.NS", added_on=_held_ago())])


def _stub_engine(**result_overrides):
    """A stand-in for `AnalyticsEngine` whose `factor_exposure_analysis` is fixed."""
    base = {
        "portfolio": {"alpha": 0.01, "market": 0.02, "beta": 0.9, "r_squared": 0.4},
        "positions": {
            "A.NS": {
                "alpha": 0.01, "beta": 0.9, "market": 0.02, "r_squared": 0.4,
                "data_points": 250, "is_limited_history": False,
            }
        },
        "r_squared": 0.4,
        "adjusted_r_squared": 0.3,
        "error": None,
    }
    base.update(result_overrides)
    return SimpleNamespace(
        factor_exposure_analysis=AsyncMock(return_value=base),
    )


# ===========================================================================
# Defect 2a - /coint: a label that asserted a measurement that never happened
# ===========================================================================
class TestCointAsOfSemanticsIsNotFabricated:
    """The single-ticker scan publishes a date; it must not claim to be a
    measurement. `as_of` stays the request end - only the LABEL moves."""

    @pytest.mark.asyncio
    async def test_the_no_pair_branch_does_not_claim_an_observation(self, async_client):
        response = await async_client.get(
            "/api/v1/analytics/coint",
            params={"tickers": "ALPHA.NS", "lookback_days": 180},
        )
        assert response.status_code == 200, response.text
        payload = response.json()

        assert payload["latest_observation_date"] is None, payload
        assert payload["data_status"] == "unavailable"
        assert payload["scanned_pairs_count"] == 0
        assert payload["pairs"] == []

        semantics = payload["as_of_semantics"]
        # RED on the old code, which published "latest_available_observation".
        assert semantics != "latest_available_observation", (
            "a scan that measured no observation is labelled as though it did; "
            "latest_observation_date beside it is None"
        )
        assert semantics == analytics_mod.COINT_NO_PAIR_UNIVERSE_AS_OF_SEMANTICS
        # The token says what actually stopped the scan: the universe, not the
        # price data. Borrowing the sibling branch's token would report a data
        # problem where none was measured.
        assert semantics != "request_end_no_usable_price_data"
        assert "universe" in semantics

    @pytest.mark.asyncio
    async def test_the_date_is_unchanged_and_still_the_request_end(self, async_client):
        """Only the LABEL may move. A published figure must not."""
        from datetime import datetime as _dt
        response = await async_client.get(
            "/api/v1/analytics/coint",
            params={"tickers": "ALPHA.NS", "lookback_days": 180},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["as_of"] == _dt.now().strftime("%Y-%m-%d"), (
            "as_of is still the request end on this branch, exactly as before "
            "the fix; only as_of_semantics changed"
        )

    def test_the_two_no_data_branches_no_longer_share_one_meaning(self):
        """The sibling branch fetches prices and gets none usable; this one
        never fetches. Same failure shape, different cause, different token."""
        source = inspect.getsource(analytics_mod.get_cointegration_pairs)
        assert source.count('as_of_semantics="request_end_no_usable_price_data"') == 1
        assert source.count("as_of_semantics=COINT_NO_PAIR_UNIVERSE_AS_OF_SEMANTICS") == 1
        # The token is a published module constant, not an inline literal, so a
        # reader (and the frontend) has one name for it.
        assert (
            analytics_mod.COINT_NO_PAIR_UNIVERSE_AS_OF_SEMANTICS
            == "request_end_universe_too_small_for_pairs"
        )

    def test_the_backend_has_no_closed_vocabulary_this_extends(self):
        """`as_of_semantics` is a free-form `str`, so an accurate third token
        is a label and not a schema change. Proven from the schema itself."""
        from app.models.schemas import CointScannerResponse

        field = CointScannerResponse.model_fields["as_of_semantics"]
        assert field.annotation is str
        # Not an enum, not a Literal: no closed set to extend.
        assert "Literal" not in str(field.annotation)
        assert "Enum" not in type(field.annotation).__name__


# ===========================================================================
# Defect 2b - /correlation-stability: was BLOCKED on schemas.py, and the tests
# below were the proof of it. They fired the day the field landed; they now
# watch that it stays landed AND that it carries the honest token.
# ===========================================================================
class TestCorrelationStabilityAsOfIsLabelledOnTheWire:
    @pytest.mark.asyncio
    async def test_the_wire_shape_today(self, async_client, test_db):
        from sqlalchemy import delete

        await test_db.execute(delete(PortfolioPosition))
        test_db.add(_pos("ALPHA.NS", added_on=datetime(2024, 1, 2), weight=1.0))
        await test_db.commit()

        response = await async_client.get("/api/v1/analytics/correlation-stability")
        assert response.status_code == 200, response.text
        payload = response.json()

        assert payload["current_avg_correlation"] is None
        assert payload["data_status"] == "unavailable"
        assert payload["as_of"], "as_of is a required `str` on the declared schema"
        # There IS now a label to read, and what it says is the cause of this
        # branch: fewer than two holdings, so no pair was ever correlated. The
        # token is asserted through the route's own constant, so a rename that
        # moved the constant and the route together still fails here.
        assert payload["as_of_semantics"] == (
            analytics_mod.CORRELATION_NO_PAIR_UNIVERSE_AS_OF_SEMANTICS
        )
        # ...and it must NOT claim an observation. This is the same fabrication
        # Defect 2a was opened for, so a regression to the measurement token on
        # this branch fails here exactly as it does on /coint.
        assert payload["as_of_semantics"] != "latest_available_observation", (
            "a branch that measured no observation is labelled as though it did"
        )
        # The schema has to keep declaring it, or FastAPI strips the token on the
        # way out and this payload is back to being unlabelled.
        assert "as_of_semantics" in CorrelationStabilityResponse.model_fields

    def test_the_declared_key_reaches_the_wire_and_the_undeclared_one_does_not(self):
        """The same probe, run in the direction that is now true.

        `response_model` re-serializes against the DECLARED model, so exactly the
        fields schemas.py names survive: `as_of_semantics` is declared, so its
        token now arrives on the wire, and `latest_observation_date` is not, so
        it is still stripped. The second half is the guard on the first - it is
        what a reverted schemas.py field would look like again.
        """
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        app = FastAPI()

        @app.get("/probe", response_model=CorrelationStabilityResponse)
        async def probe():
            return CorrelationStabilityResponse(
                as_of="2026-01-02",
                is_regime_break=False,
                alert_level="NORMAL",
                message="probe",
                series=[],
                as_of_semantics="request_end_no_usable_price_data",
                latest_observation_date=None,
            )

        with TestClient(app) as client:
            body = client.get("/probe").json()

        assert body["as_of"] == "2026-01-02"
        # Declared, so the token crosses verbatim rather than being dropped.
        assert body["as_of_semantics"] == "request_end_no_usable_price_data"
        # Never declared, so still stripped. `extra` is not "allow" on this
        # model, which is the trap this whole section exists to document.
        assert "latest_observation_date" not in body

    def test_the_schemas_py_field_exists_and_left_as_of_alone(self):
        """The change this file was blocked on HAS landed, and it landed as one
        additive optional beside the date rather than as a change to it.

        `as_of` is still REQUIRED and non-nullable: widening it to `Optional[str]`
        was the rejected alternative, because this route is a `risk-studio`
        `componentDates` leg filtered by `typeof value === 'string'`. The new
        field is `Optional[str] = None` because it describes the date beside it,
        it is not the date.
        """
        fields = CorrelationStabilityResponse.model_fields

        assert "as_of_semantics" in fields, (
            "the disclosure field was reverted in schemas.py; undeclared, "
            "FastAPI strips the token and /correlation-stability is unlabelled "
            "again"
        )
        assert fields["as_of_semantics"].annotation == Optional[str]
        assert fields["as_of_semantics"].default is None
        # The rejected alternative must stay rejected.
        assert fields["as_of"].is_required()
        assert fields["as_of"].annotation is str


# ===========================================================================
# Defect 3 - the dead fabrication default on /factor-exposure
# ===========================================================================
class TestFactorExposurePublishesWhatWasMeasured:
    @pytest.mark.asyncio
    async def test_a_missing_fit_publishes_none_not_zero(self):
        """RED on the old code. With no default, a key the engine did not
        publish reads None ("not measured"); with `, 0.0` it read 0.0, which is
        indistinguishable from a measured zero."""
        frame = _frame("A.NS", seed=5)
        market = _WindowedMarket({"A.NS": frame})
        bench = SimpleNamespace(get_returns=AsyncMock(return_value=None))
        engine = SimpleNamespace(
            factor_exposure_analysis=AsyncMock(return_value={
                "portfolio": {"alpha": None, "market": None},
                "positions": {},
                "r_squared": None,
                # `adjusted_r_squared` deliberately ABSENT.
                "error": "insufficient data for factor regression",
            })
        )

        result = await analytics_mod.get_factor_exposure(
            tickers="A.NS", lookback_days=252, db=_book(),
            data_service=market, benchmark_service=bench,
            analytics_engine=engine,
        )

        assert result["adjusted_r_squared"] is None, (
            "a key the engine never published must read as not measured, not as "
            f"a fabricated zero (got {result['adjusted_r_squared']!r})"
        )
        # Its sibling, published as None, is the control: the two must agree.
        assert result["r_squared"] is None

    @pytest.mark.asyncio
    async def test_a_measured_zero_stays_zero(self):
        """The other half of the contract, and the reason the default was
        harmful: 0.0 and None must not be the same token."""
        frame = _frame("A.NS", seed=5)
        market = _WindowedMarket({"A.NS": frame})
        bench = SimpleNamespace(get_returns=AsyncMock(return_value=None))
        engine = _stub_engine(r_squared=0.0, adjusted_r_squared=0.0)

        result = await analytics_mod.get_factor_exposure(
            tickers="A.NS", lookback_days=252, db=_book(),
            data_service=market, benchmark_service=bench,
            analytics_engine=engine,
        )

        assert result["r_squared"] == 0.0
        assert result["adjusted_r_squared"] == 0.0

    @pytest.mark.asyncio
    async def test_the_default_was_and_is_unreachable(self):
        """Why removing it changed nothing observable.

        `factor_exposure_analysis` publishes BOTH keys on every exit path it
        can take, so `.get(key, 0.0)` never saw an absent key and the `0.0`
        never fired. Each case below reaches a different one of those exits:

        * empty input, and one row (pct_change leaves nothing), both land in
          `_empty_factor_exposure`;
        * no benchmark lands in the not-fitted dict inside
          `_calculate_factor_exposures`;
        * a real fit lands in the dict that carries real numbers.
        """
        frame = _frame("A.NS", seed=3)
        engine = AnalyticsEngine()
        bench = pd.Series(
            np.random.default_rng(4).normal(0.0, 0.01, len(frame)),
            index=frame.index,
        )
        # The frame has ONE column and it is named `adj_close`, so that is
        # the weight key; a key the frame does not have fits nothing.
        weights = {"adj_close": 1.0}

        cases = {
            "empty_price_data": (pd.DataFrame(), None, None),
            "one_row": (frame.iloc[:1], None, None),
            "no_benchmark": (frame, None, weights),
            "fitted": (frame, bench, weights),
        }
        published = {}
        for name, (data, benchmark_data, book) in cases.items():
            result = await engine.factor_exposure_analysis(
                data, benchmark_data=benchmark_data, weights=book
            )
            assert "r_squared" in result, (name, sorted(result))
            assert "adjusted_r_squared" in result, (name, sorted(result))
            published[name] = (
                result["r_squared"],
                result["adjusted_r_squared"],
            )

        # Non-vacuity: the four cases really are four different exits, and the
        # fitted one really carries a measurement rather than a null.
        assert published["fitted"][0] is not None, published
        assert published["no_benchmark"][0] is None, published
        assert published["empty_price_data"][0] is None, published

    def test_the_route_no_longer_names_a_default_for_either_field(self):
        source = inspect.getsource(analytics_mod.get_factor_exposure)
        assert 'factor_result.get("r_squared", ' not in source
        assert 'factor_result.get("adjusted_r_squared", ' not in source
        assert '"adjusted_r_squared": factor_result.get("adjusted_r_squared"),' in source

    @pytest.mark.asyncio
    async def test_a_fitted_fit_is_published_untouched(self):
        """The no-figure-changed control: a real fit passes through verbatim."""
        frame = _frame("A.NS", seed=5)
        market = _WindowedMarket({"A.NS": frame})
        bench = SimpleNamespace(get_returns=AsyncMock(return_value=None))
        engine = _stub_engine()

        result = await analytics_mod.get_factor_exposure(
            tickers="A.NS", lookback_days=252, db=_book(),
            data_service=market, benchmark_service=bench,
            analytics_engine=engine,
        )

        assert result["r_squared"] == 0.4
        assert result["adjusted_r_squared"] == 0.3


# ===========================================================================
# /vol-cone - Defect 4 was REJECTED, so this pins the rejection instead of
# patching around it. See `test_lookback_days_has_no_parameter_to_pass`.
# ===========================================================================
class TestVolConeLookbackIsNotDiscarded:
    def test_lookback_days_has_no_parameter_to_pass(self):
        """The service signature has no `lookback_days`, so there is nothing to
        forward, and the route already bounds the returns window with it."""
        from app.services.volatility_service import VolatilityService

        parameters = list(
            inspect.signature(VolatilityService.calculate_volatility_cone).parameters
        )
        assert parameters == [
            "returns", "symbol", "windows",
            "forecast_horizon", "forecast_model", "as_of",
        ]
        assert "lookback_days" not in parameters

    def test_the_route_bounds_the_window_with_it(self):
        source = inspect.getsource(analytics_mod.get_volatility_cone)
        assert 'timedelta(days=lookback_days)' in source
        assert "start, end, data_service" in source
        assert "VolatilityService.calculate_volatility_cone, port_ret" in source

    def test_no_lookback_field_was_added_to_the_cone_payload(self):
        """The rejected fix would have published `lookback_days` here. It is
        not published, and this is the golden of the untouched payload."""
        golden = json.loads(VOL_CONE_GOLDEN.read_text(encoding="utf-8"))
        assert "lookback_days" not in golden
        assert "history_window" not in golden
        assert golden["as_of"] == "2025-12-29"
        assert golden["latest_observation_date"] == "2025-12-29"
        assert golden["windows"], "non-vacuity: a real cone"