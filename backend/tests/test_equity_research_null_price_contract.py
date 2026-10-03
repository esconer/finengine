"""E1: `current_price` is a measurement. When it cannot be measured it must be
None -- never a fabricated 0.0 that reads as "this stock trades at zero".

Both producers chained to a literal:
    equity_research_service.py:57  `cmp = r.current_price or info.get("currentPrice") or 0.0`
    equity_research_service.py:231 `cmp = profile.ratios.current_price or 0.0`

`or 0.0` is the defect: `r.current_price` is None precisely when the provider
did not return a price, and the trailing `or 0.0` converts "not measured" into
"measured as zero" -- a number the UI will happily format as Rs 0.

TWO BLOCKS, and this file is split around them:

1. `_declares_null_current_price` -- the service-layer contract. Always runs.
   Green once the producer stops inventing 0.0, independent of any schema.

2. `_NULL_REJECTED` -- the transport-layer contract. SKIPPED today, because the
   four `current_price: float` declarations have not landed yet. The skip
   reason is computed live from pydantic, so it carries the proof: the exact
   error type and field each rejecting model reports. When the declarations
   become Optional the gate opens by itself and the route tests start guarding
   the wire format with no edit here.

Required to open the gate (none of these files are owned by the producer fix):

    app/models/schemas.py  EquityResearchProfileResponse.current_price: float
        -> current_price: Optional[float] = None
    app/models/schemas.py  CustomRatiosResponse.current_price: float
        -> current_price: Optional[float] = None
    frontend/src/types/index.ts:980  current_price: number  -> number | null
    frontend/src/types/index.ts:1061  current_price: number  -> number | null

DO NOT also widen schemas.py:210 (`StockQuoteResponse.current_price: float`,
surfaced by frontend/src/api.ts:569). That is a different producer on a
different route; widening it there would weaken a declaration that is correct.

All upstream I/O faked.
"""

from typing import Any, Dict, List, Optional

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from unittest.mock import AsyncMock, Mock, patch

from app.api import equity_research as er_mod
from app.models.schemas import CustomRatiosResponse, EquityResearchProfileResponse
from app.services.equity_research_service import EquityResearchService


# --------------------------------------------------------------------------
# Doubles: a real profile shape with one switchable price, so the only
# variable across the two producers is "was a price measured?".
# --------------------------------------------------------------------------

class _FakeRatios:
    def __init__(self, current_price: Optional[float]):
        self.current_price = current_price
        self.market_cap = None
        self.high_52w = None
        self.low_52w = None
        self.stock_pe = None
        self.book_value = None
        self.dividend_yield = None
        self.roce = None
        self.roe = None
        self.face_value = None
        self.debt_to_equity = None
        self.peg_ratio = None
        self.eps_ttm = None
        self.promoter_holding = None
        self.promoter_pledged = None


class _FakeTable:
    def __init__(self):
        self.rows: Dict[str, Any] = {}

    def to_dataframe(self, orient="columns") -> pd.DataFrame:
        return pd.DataFrame()


class _FakeProfile:
    def __init__(self, current_price: Optional[float]):
        self.symbol = "GLITCH"
        self.name = "Glitch Industries"
        self.about = None
        self.website = None
        self.bse_code = None
        self.nse_symbol = "GLITCH"
        self.sector = None
        self.industry_group = None
        self.industry = None
        self.sub_industry = None
        self.indices = []
        self.ratios = _FakeRatios(current_price)
        self.ratios_history = _FakeTable()
        self.analysis = None
        self.cagrs = {}
        self.peers = None
        self.concalls: List[Any] = []
        self.annual_reports = []
        self.credit_ratings = []


class _FakeTicker:
    """`info` is non-empty but carries no price and no fundamentals: the exact
    shape bfinance returns for a symbol whose fundamentals do not resolve."""

    def __init__(self, current_price: Optional[float], symbol="GLITCH"):
        self.symbol = symbol
        self.custom_ratios = {
            "piotroski_score": 7,
            "graham_number": 3250.0,
            "enterprise_value_cr": 100.0,
        }
        self._profile = _FakeProfile(current_price)

    @property
    def info(self) -> Dict[str, Any]:
        return {}

    def _ensure_profile(self):
        return self._profile


def _patched(svc):
    return patch("bfinance.Ticker", return_value=svc)


# --------------------------------------------------------------------------
# 1. Producer contract -- always runs.
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_profile_reports_unmeasured_price_as_none():
    """r.current_price is None and info has no currentPrice -> None, not 0.0."""
    with _patched(_FakeTicker(current_price=None)):
        out = await EquityResearchService().get_full_profile("GLITCH")

    assert out["current_price"] is None, (
        "an unmeasured price must stay None; 0.0 is a fabricated reading"
    )


@pytest.mark.asyncio
async def test_full_profile_keeps_a_real_price():
    with _patched(_FakeTicker(current_price=123.5)):
        out = await EquityResearchService().get_full_profile("GLITCH")

    assert out["current_price"] == 123.5


@pytest.mark.asyncio
async def test_full_profile_graham_upside_stays_none_without_a_price():
    """Graham number is present but the price is not: no upside can be
    computed, so the derived figure must be refused rather than divided."""
    with _patched(_FakeTicker(current_price=None)):
        out = await EquityResearchService().get_full_profile("GLITCH")

    assert out["custom_ratios"]["graham_number"] == 3250.0  # real
    assert out["custom_ratios"]["graham_upside_pct"] is None  # refused


@pytest.mark.asyncio
async def test_custom_ratios_reports_unmeasured_price_as_none():
    with _patched(_FakeTicker(current_price=None)):
        out = await EquityResearchService().get_custom_ratios("GLITCH")

    assert out["current_price"] is None


@pytest.mark.asyncio
async def test_custom_ratios_keeps_a_real_price():
    with _patched(_FakeTicker(current_price=123.5)):
        out = await EquityResearchService().get_custom_ratios("GLITCH")

    assert out["current_price"] == 123.5


@pytest.mark.asyncio
async def test_custom_ratios_graham_upside_survives_a_null_price():
    """Regression guard for the :234 guard.

    `if graham and cmp > 0:` raises TypeError the moment cmp is None, and the
    outer `except Exception` turns that into ProviderUnavailableError -> 503.
    The :59 guard is safe (`... and cmp and cmp > 0` short-circuits); this one
    needed an explicit `cmp is not None`.
    """
    with _patched(_FakeTicker(current_price=None)):
        out = await EquityResearchService().get_custom_ratios("GLITCH")

    assert out["graham_number"] == 3250.0
    assert out["graham_upside_pct"] is None


@pytest.mark.asyncio
async def test_custom_ratios_graham_upside_computed_with_a_real_price():
    with _patched(_FakeTicker(current_price=2000.0)):
        out = await EquityResearchService().get_custom_ratios("GLITCH")

    assert out["graham_upside_pct"] == round(((3250.0 - 2000.0) / 2000.0) * 100, 2)


# --------------------------------------------------------------------------
# 2. Transport contract -- gated on the four declarations.
# --------------------------------------------------------------------------

_PROFILE_MIN = {
    "symbol": "GLITCH", "ticker": "GLITCH.NS", "name": "Glitch Industries",
    # `custom_ratios` cannot be `{}`: `CustomRatiosSchema.piotroski_score` is a
    # required int, so an empty dict raised `missing` BEFORE `current_price` was
    # ever reached. That error was masked while `current_price` was still
    # non-nullable (field order put it first), so this fixture looked fine; once
    # `current_price` became Optional the next complaint surfaced and kept the
    # gate below shut for a reason unrelated to the thing it gates. Real route
    # payloads always carry a piotroski_score.
    "indices": [], "custom_ratios": {"piotroski_score": 7}, "source": "bfinance",
}
_RATIOS_MIN = {
    "ticker": "GLITCH.NS", "piotroski_score": 7,
    "ratios_history": {}, "source": "bfinance",
}


def _rejection(model, payload: Dict[str, Any]) -> Optional[str]:
    """None if the model accepts a null price, else the pydantic complaint."""
    try:
        model(**payload)
    except ValidationError as exc:
        err = exc.errors()[0]
        return f"{model.__name__} {err['type']} {err['loc']}"
    return None


_NULL_REJECTED = [
    complaint
    for complaint in (
        _rejection(EquityResearchProfileResponse, {**_PROFILE_MIN, "current_price": None}),
        _rejection(CustomRatiosResponse, {**_RATIOS_MIN, "current_price": None}),
    )
    if complaint
]

_SKIP_REASON = (
    "E1 half-landed: these declarations still reject a null current_price, so "
    "the route 500s on pydantic float_type instead of serialising None. "
    "Open the gate by making all four Optional: "
    "app/models/schemas.py EquityResearchProfileResponse.current_price, "
    "app/models/schemas.py CustomRatiosResponse.current_price, "
    "frontend/src/types/index.ts:980 current_price, "
    "frontend/src/types/index.ts:1061 current_price. "
    f"Observed -> {'; '.join(_NULL_REJECTED)}"
)

requires_null_capable_declarations = pytest.mark.skipif(
    bool(_NULL_REJECTED), reason=_SKIP_REASON
)


@requires_null_capable_declarations
@pytest.mark.asyncio
async def test_profile_route_returns_200_with_a_null_price():
    """End to end: producer emits None -> response_model must carry it."""
    payload = {**_PROFILE_MIN, "current_price": None}
    svc = Mock()
    svc.get_full_profile = AsyncMock(return_value=payload)
    transport = ASGITransport(app=app_for())
    with patch.object(er_mod, "get_equity_research_service", return_value=svc):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/company/GLITCH/full-profile")

    assert resp.status_code == 200, resp.text
    assert resp.json()["current_price"] is None


@requires_null_capable_declarations
@pytest.mark.asyncio
async def test_custom_ratios_route_returns_200_with_a_null_price():
    payload = {**_RATIOS_MIN, "current_price": None}
    svc = Mock()
    svc.get_custom_ratios = AsyncMock(return_value=payload)
    transport = ASGITransport(app=app_for())
    with patch.object(er_mod, "get_equity_research_service", return_value=svc):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/company/GLITCH/custom-ratios")

    assert resp.status_code == 200, resp.text
    assert resp.json()["current_price"] is None


def app_for():
    """The live app, re-read per call (conftest's `_current_app` rule:
    `main.app` is rebuilt by a reload elsewhere in the suite)."""
    import main as main_module

    return main_module.app