"""Regression gate for the two open defects closed in fix-wave 2.

**D-04 — `risk_score.components.correlation` was a hard zero.**
``risk_scoring`` scored correlation as ``clip((avg - 0.3) * 50, 0, 30)``. That
floor collapsed every measured average correlation at or below 0.3 onto exactly
``0`` — the same value an *unmeasured* leg publishes — and a one-asset book, which
has no cross-asset correlation at all, published ``0`` as well. Both were
indistinguishable from "not computed" (``excluded_components: []``) and both
dragged ``overall_score`` down, while Risk Studio measured 0.1404 over its own
window. ``NUM-018`` is the rule that catches it.

**D-07 — pairs ``currency`` / ``warnings`` were stripped from the HTTP wire.**
The route returns an ``extra="allow"`` subclass so the in-process AI-context
exporter sees the disclosures, but the decorator declares
``response_model=CointScannerResponse`` and FastAPI re-serializes against the
DECLARED model, so every extra field was dropped for a direct HTTP consumer. The
AI path was audited; the API path was not.

These assert the behaviour directly rather than re-running the audit CLI, which
only ever reads a SAVED export.
"""

import json
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api import analytics as analytics_mod
from app.api.analytics import get_cointegration_pairs
from app.debugging.context_audit import num_018_no_hard_zero_sub_scores
from app.models.schemas import CointPairResult, CointScannerResponse
from app.services.ai_context_service import _jsonable
from app.services.analytics_engine import (
    RISK_CORRELATION_POINTS_PER_UNIT,
    AnalyticsEngine,
)
from app.services.cointegration_service import (
    CointegrationService,
    _IN_MEMORY_COINT_CACHE,
)

# --------------------------------------------------------------------------
# helpers


def _correlated_frame(
    n: int = 200, seed: int = 11, columns: tuple[str, ...] = ("A", "B", "C")
) -> pd.DataFrame:
    """A frame whose legs share one common factor, so correlation is measurable."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2025-01-01", periods=n)
    base = pd.Series(100.0 + np.cumsum(rng.normal(0.0, 1.0, n)), index=index)
    data: Dict[str, Any] = {}
    for i, name in enumerate(columns):
        data[name] = base * (1.0 + 0.1 * i) + rng.normal(0.0, 0.3, n)
    return pd.DataFrame(data, index=index)


def _num018(payload: Dict[str, Any]) -> list:
    """Run the real NUM-018 rule over a synthetic single-section export."""
    from app.debugging.context_audit import EXPECTED_SCHEMA_VERSION, Export

    section = {
        "key": "dashboard",
        "title": "Dashboard",
        "route": "/dashboard",
        "status": "available",
        "detail": "summary",
        "generated_at": "2026-09-26T05:57:43.164091Z",
        "inputs": {},
        "coverage": None,
        "data": payload,
        "as_of": "2026-09-25",
        "as_of_semantics": "latest_observation_date",
        "currency": None,
        "warnings": [],
    }
    doc = {
        "schema_version": EXPECTED_SCHEMA_VERSION,
        "export_id": "portfolio-synthetic",
        "generated_at": "2026-09-26T05:57:43.164091Z",
        "completed_at": "2026-09-26T05:58:16.698733Z",
        "snapshot_consistency": "best_effort",
        "base_currency": "INR",
        "detail": "summary",
        "scope": ["dashboard"],
        "sections": {"dashboard": section},
        "warnings": [],
    }
    return num_018_no_hard_zero_sub_scores(Export(doc=doc, raw=json.dumps(doc)))


# --------------------------------------------------------------------------
# D-04: an unmeasured sub-score is null, never a hard zero


class TestRiskCorrelationSubScoreIsNeverAHardZero:
    @pytest.mark.asyncio
    async def test_single_asset_book_reports_correlation_unmeasured(self):
        """A one-asset book has no cross-asset correlation to measure.

        It used to publish ``correlation: 0`` with ``excluded_components: []``,
        which is a fabricated "no correlation risk" reading for a quantity that
        was never computed.
        """
        engine = AnalyticsEngine()
        frame = _correlated_frame(columns=("A",))
        result = await engine.risk_scoring(frame, {"A": 1.0})

        assert result["components"]["correlation"] is None
        assert "correlation" in result["excluded_components"]
        assert result["avg_pairwise_correlation"] is None
        # And it is a null, not a zero, on the wire.
        assert not any(
            isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0
            for v in result["components"].values()
        )

    @pytest.mark.asyncio
    async def test_suppressing_the_leg_renormalizes_over_the_rest(self):
        """The scoring code already handles a missing component.

        Excluding the leg must drop its 0.20 weight and renormalize the
        remainder, NOT substitute 0 for it — the substitution is the fabrication
        D-04 is about.
        """
        engine = AnalyticsEngine()
        result = await engine.risk_scoring(_correlated_frame(columns=("A",)), {"A": 1.0})

        assert "correlation" in result["excluded_components"]
        components = result["components"]
        active = [name for name in components if components[name] is not None]
        weights = {
            "concentration": 0.20,
            "volatility": 0.25,
            "correlation": 0.20,
            "factor_risk": 0.25,
            "market_risk": 0.10,
        }
        total = sum(weights[name] for name in active)
        expected = sum(components[name] * weights[name] / total for name in active)
        assert result["overall_score"] == pytest.approx(round(expected, 1), abs=0.15)

    @pytest.mark.asyncio
    async def test_measured_correlation_is_published_beside_its_sub_score(self):
        """The measurement is what makes a low sub-score explicable."""
        engine = AnalyticsEngine()
        result = await engine.risk_scoring(
            _correlated_frame(), {"A": 0.4, "B": 0.3, "C": 0.3}
        )

        measured = result["avg_pairwise_correlation"]
        assert measured is not None
        assert 0.0 < measured <= 1.0
        assert result["components"]["correlation"] == pytest.approx(
            min(30.0, measured * RISK_CORRELATION_POINTS_PER_UNIT), abs=0.05
        )

    @pytest.mark.asyncio
    async def test_a_below_baseline_measurement_is_not_flattened_to_zero(self):
        """The regression itself: a measured correlation below 0.3.

        ``clip((avg - 0.3) * 50, 0, 30)`` returned exactly 0 here, identical to
        an unmeasured leg. A real measurement of low co-movement must carry a
        real reading.
        """
        engine = AnalyticsEngine()
        index = pd.bdate_range("2025-01-01", periods=600)
        rng = np.random.default_rng(1)
        # Both legs load on one common factor, so their returns are positively
        # correlated at ~0.12: positive, and far under the old 0.3 "free"
        # baseline that used to flatten the sub-score to exactly 0.
        common = rng.normal(0.0, 1.0, 600)
        a = pd.Series(100.0 + np.cumsum(0.42 * common + rng.normal(0, 1.0, 600)), index=index)
        b = pd.Series(100.0 + np.cumsum(0.42 * common + rng.normal(0, 1.0, 600)), index=index)
        frame = pd.DataFrame({"A": a, "B": b}, index=index)

        result = await engine.risk_scoring(frame, {"A": 0.5, "B": 0.5})

        measured = result["avg_pairwise_correlation"]
        assert measured is not None and 0.0 < measured < 0.3, (
            f"fixture must be low but positive, got {measured}"
        )
        assert result["components"]["correlation"] is not None
        assert result["components"]["correlation"] > 0
        assert "correlation" not in result["excluded_components"]

    @pytest.mark.asyncio
    async def test_measured_correlation_satisfies_num_018(self):
        """The real rule, run over the real engine output."""
        engine = AnalyticsEngine()
        result = await engine.risk_scoring(
            _correlated_frame(), {"A": 0.4, "B": 0.3, "C": 0.3}
        )
        assert _num018(result) == []

    @pytest.mark.asyncio
    async def test_unmeasured_correlation_satisfies_num_018(self):
        engine = AnalyticsEngine()
        result = await engine.risk_scoring(_correlated_frame(columns=("A",)), {"A": 1.0})
        assert _num018(result) == []

    @pytest.mark.asyncio
    async def test_preserved_invariants(self):
        """Everything the wave said must not move."""
        engine = AnalyticsEngine()
        frame = _correlated_frame()
        weights = {"A": 0.4, "B": 0.3, "C": 0.3}
        # With a benchmark every leg is measurable, so all five carry a reading.
        bench = pd.Series(
            frame["A"].pct_change(fill_method=None).fillna(0.0).to_numpy()
            + np.random.default_rng(5).normal(0.0, 0.002, len(frame)),
            index=frame.index,
        )
        result = await engine.risk_scoring(frame, weights, benchmark_data=bench)

        assert result["risk_level"] in {"LOW", "MEDIUM", "HIGH"}
        assert result["excluded_components"] == []
        assert set(result["components"]) == {
            "concentration",
            "volatility",
            "correlation",
            "factor_risk",
            "market_risk",
        }
        for name, score in result["components"].items():
            assert score is not None, name
            assert 0 <= score <= 30, name
        assert result["methodology"]
        # Stateless: no prior score is persisted, so no genuine delta exists.
        assert result["change"] is None
        assert result["change_status"] == "unavailable"
        assert result["change_reason"] == "no_persisted_prior_score"
        assert not hasattr(engine, "_previous_risk_score")

    @pytest.mark.asyncio
    async def test_scoring_is_stateless_and_repeatable(self):
        engine = AnalyticsEngine()
        frame = _correlated_frame()
        weights = {"A": 0.5, "B": 0.5, "C": 0.0}
        first = await engine.risk_scoring(frame, weights)
        second = await engine.risk_scoring(frame, weights)
        assert first["overall_score"] == second["overall_score"]
        assert first["components"] == second["components"]

    @pytest.mark.asyncio
    async def test_exclusion_alert_names_the_leg_and_its_reason(self):
        """A dropped leg must say which one and why, not a canned factor-only line."""
        engine = AnalyticsEngine()
        result = await engine.risk_scoring(_correlated_frame(columns=("A",)), {"A": 1.0})
        joined = " ".join(result["alerts"])
        assert "correlation" in joined
        assert "factor_risk" in joined
        assert "renormalized" in joined

    @pytest.mark.asyncio
    async def test_high_correlation_still_raises_its_alert(self):
        engine = AnalyticsEngine()
        index = pd.bdate_range("2025-01-01", periods=200)
        base = pd.Series(100.0 + np.cumsum(np.random.default_rng(4).normal(0, 1.0, 200)), index=index)
        frame = pd.DataFrame(
            {"A": base, "B": base * 1.5 + 2.0, "C": base * 0.8 - 1.0}, index=index
        )
        result = await engine.risk_scoring(frame, {"A": 0.4, "B": 0.3, "C": 0.3})
        assert result["components"]["correlation"] == 30.0
        assert any("High correlation risk" in a for a in result["alerts"])


# --------------------------------------------------------------------------
# D-07: the declared disclosure survives FastAPI's re-serialization


def _disclosure_app() -> FastAPI:
    """A route that reproduces `get_cointegration_pairs._publish` verbatim.

    The route's own `_publish` is not importable (it is a closure), so the merge
    is copied byte for byte from `app/api/analytics.py`. If that merge ever stops
    being safe with a declared field, this app is what notices.
    """

    class _PairsDisclosure(CointScannerResponse):
        model_config = {"extra": "allow"}

    def _publish(response: CointScannerResponse, extras: Dict[str, Any]):
        error = getattr(response, "error", None)
        if not (isinstance(error, str) and error.strip()):
            error = None
        payload = response.model_dump()
        if error is None:
            payload.pop("error", None)
        published = _PairsDisclosure(**payload, **dict(extras or {}))
        if error is None:
            published.__dict__.pop("error", None)
        return published

    app = FastAPI()

    def _base() -> CointScannerResponse:
        return CointScannerResponse(
            as_of="2026-09-22",
            universe_size=3,
            scanned_pairs_count=3,
            cointegrated_pairs_count=1,
            pairs=[],
        )

    @app.get("/declared", response_model=CointScannerResponse)
    async def declared() -> CointScannerResponse:
        return _publish(
            _base(),
            {
                "currency": "INR",
                "currency_provenance": "derived",
                "currency_basis": "the delivered prices are rupee quoted",
                "warnings": ["Depth-limited pairs: 1 of 3 delivered pairs ran on less"],
            },
        )

    @app.get("/undeclared", response_model=CointScannerResponse)
    async def undeclared() -> CointScannerResponse:
        return _publish(
            _base(),
            {
                "currency_provenance": "unavailable",
                "currency_basis": "No pair row was delivered",
            },
        )

    return app


class TestPairsDisclosureReachesTheHttpWire:
    def test_declared_disclosure_is_not_stripped(self):
        body = TestClient(_disclosure_app()).get("/declared").json()
        assert body["currency"] == "INR"
        assert body["currency_provenance"] == "derived"
        assert "rupee quoted" in body["currency_basis"]
        assert body["warnings"] and "Depth-limited pairs" in body["warnings"][0]

    def test_a_field_the_route_never_declares_is_absent_not_null(self):
        """Absent means absent.

        Promoting the field must not make every scan start publishing
        `currency: null` / `warnings: []`; the clean scan's shape is unchanged.
        """
        body = TestClient(_disclosure_app()).get("/undeclared").json()
        assert "currency" not in body
        assert "warnings" not in body
        assert body["currency_provenance"] == "unavailable"
        # `error` keeps its existing route-owned handling.
        assert "error" not in body

    def test_fastapi_really_would_have_dropped_an_undeclared_field(self):
        """Control: the D-07 shape, reproduced without the declaration.

        ``response_model`` is the closed base; the route hands back an
        ``extra="allow"`` subclass. FastAPI re-serializes against the declared
        model, so the runtime-only field never reaches the wire. This pins the
        premise, so a future pydantic/FastAPI upgrade that starts preserving
        extras cannot silently make the tests above vacuous.
        """

        class _ClosedBase(BaseModel):
            as_of: str

        class _OpenSub(_ClosedBase):
            model_config = {"extra": "allow"}

        app = FastAPI()

        @app.get("/x", response_model=_ClosedBase)
        async def x() -> _ClosedBase:
            model = _OpenSub(as_of="2026-09-22")
            model.currency = "INR"
            return model

        assert "currency" not in TestClient(app).get("/x").json()

    def test_every_disclosure_field_is_declared_with_a_safe_default(self):
        fields = CointScannerResponse.model_fields
        for name in ("currency", "currency_provenance", "currency_basis"):
            assert fields[name].annotation is Optional[str]
            assert fields[name].default is None
        assert fields["warnings"].annotation == List[str]
        assert fields["warnings"].get_default(call_default_factory=True) == []

    def test_early_return_branches_construct_the_model_directly(self):
        """`get_cointegration_pairs` builds a bare `CointScannerResponse` on the
        short-universe branches, so the promoted defaults have to be usable
        without the route passing anything."""
        response = CointScannerResponse(
            as_of="2026-09-22",
            universe_size=1,
            scanned_pairs_count=0,
            cointegrated_pairs_count=0,
            pairs=[],
        )
        payload = json.loads(response.model_dump_json())
        assert "currency" not in payload
        assert "warnings" not in payload

    def test_cached_pair_rows_still_load(self):
        """`CointPairResult(**cached_row)` must keep working: every field added
        to the pair model is `Optional[...] = None`. This fix adds none."""
        row = {
            "ticker_a": "A.NS",
            "ticker_b": "B.NS",
            "engle_granger_pvalue": 0.01,
            "engle_granger_tstat": -3.0,
            "is_cointegrated": True,
            "hedge_ratio_beta": 1.0,
            "intercept_alpha": 0.0,
            "johansen_cointegrated": True,
            "last_price_a": 1.0,
            "last_price_b": 2.0,
            "signal": "NEUTRAL",
        }
        pair = CointPairResult(**row)
        assert pair.ticker_a == "A.NS"
        assert pair.ou_half_life_days is None
        for name, field in CointPairResult.model_fields.items():
            if name in row:
                continue
            assert field.default is None or name == "price_basis", name


class TestRealPairsRouteOverHttp:
    """End to end: the audited route, over the wire, not through the exporter."""

    def _frames(self) -> Dict[str, pd.DataFrame]:
        rng = np.random.default_rng(41)
        index = pd.bdate_range("2026-01-01", periods=174)
        base = pd.Series(100.0 + np.cumsum(rng.normal(0.05, 1.0, 174)), index=index)
        peer = 1.5 * base + 10.0 + pd.Series(rng.normal(0.0, 0.4, 174), index=index)
        return {
            "INFY.NS": pd.DataFrame({"close": base.to_numpy()}, index=index),
            "TCS.NS": pd.DataFrame({"close": peer.to_numpy()}, index=index),
        }

    @pytest.mark.asyncio
    async def test_route_publishes_the_disclosure_in_process(self):
        class _FakeMarket:
            def __init__(self, frames):
                self.frames = frames

            async def fetch_historical_data(self, ticker, start, end):
                frame = self.frames.get(ticker)
                return pd.DataFrame() if frame is None else frame

        _IN_MEMORY_COINT_CACHE.clear()
        try:
            with patch.object(analytics_mod, "CointegrationService", CointegrationService):
                result = await get_cointegration_pairs(
                    tickers="INFY.NS,TCS.NS",
                    lookback_days=252,
                    p_value_threshold=0.05,
                    max_half_life=None,
                    include_spread_series=False,
                    db=Mock(),
                    data_service=_FakeMarket(self._frames()),
                    cache_service=None,
                )
        finally:
            _IN_MEMORY_COINT_CACHE.clear()

        exported = _jsonable(result)
        assert exported["currency"] == "INR"
        assert exported["currency_provenance"] == "derived"
        # The declarations are on the base model, so FastAPI keeps them.
        for name in ("currency", "currency_provenance", "currency_basis"):
            assert name in CointScannerResponse.model_fields
