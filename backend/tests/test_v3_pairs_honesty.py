"""Pairs-scanner honesty gate for the v4 export audit (DEFECT 1/2/3).

The v4 export showed the `pairs` section shipping three defects that a reader
could not see from the payload:

- DEFECT 1  `data.error` was a literal `null` on a fully successful scan. The
  route fed the model's `None` default back through `model_copy(update=...)`,
  so a clean result advertised a "failure" with no message. Absent must mean
  absent; only a real failure earns the key.
- DEFECT 2  `pairs.currency` was `null` although the payload publishes 273
  monetary values (`last_price_a`, `last_price_b`, price-space
  `intercept_alpha`). The exporter resolves a unit by key name only, so it was
  blind to price-space fields. The route now declares the unit it actually
  fitted in, with provenance and a basis.
- DEFECT 3  the section reported `status: "partial"` with `warnings: []`. The
  reason was in the payload (`depth_status: "partial"`, `shallow_tickers`,
  per-ticker observation counts) but nothing surfaced it, so a degraded result
  shipped with no stated reason.

No DB, no network: seeded price frames plus the real `CointegrationService`
(the route's only seam is patched away in the tests that need a canned scan).
"""

import json
from typing import List, Optional
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from app.api import analytics as analytics_mod
from app.api.analytics import get_cointegration_pairs
from app.models.schemas import CointPairResult, CointScannerResponse
from app.services.ai_context_service import _infer_currency, _jsonable
from app.services.cointegration_service import (
    MIN_PAIR_DEPTH_RATIO,
    CointegrationService,
    _IN_MEMORY_COINT_CACHE,
)

# --------------------------------------------------------------------- fakes


class _FakeMarket:
    """Price frames per ticker; missing tickers simply come back empty."""

    def __init__(self, frames):
        self.frames = dict(frames)

    async def fetch_historical_data(self, ticker, start, end):
        frame = self.frames.get(ticker)
        if frame is None:
            return pd.DataFrame()
        return frame


def _frame(values, index):
    return pd.DataFrame({"close": np.asarray(values, dtype=float)}, index=index)


def _universe(deep=174, young=108, extra=None, seed=41):
    """Deep peers plus one young ETF - the NIFTYIETF shape from the audit."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2026-01-01", periods=deep)
    base = pd.Series(100.0 + np.cumsum(rng.normal(0.05, 1.0, deep)), index=index)
    peer = 1.5 * base + 10.0 + pd.Series(rng.normal(0.0, 0.4, deep), index=index)
    etf_index = index[deep - young:]
    etf = pd.Series(
        50.0 + np.cumsum(rng.normal(0.02, 0.3, young)), index=etf_index
    )
    frames = {
        "INFY.NS": _frame(base.to_numpy(), base.index),
        "TCS.NS": _frame(peer.to_numpy(), peer.index),
        "NIFTYIETF.NS": _frame(etf.to_numpy(), etf.index),
    }
    frames.update(extra or {})
    return frames


def _market(frames):
    return _FakeMarket(frames)


async def _scan(tickers, frames, **kwargs):
    """Run the route over `frames` with the real coint service underneath."""
    _IN_MEMORY_COINT_CACHE.clear()
    try:
        with patch.object(analytics_mod, "CointegrationService", CointegrationService):
            return await get_cointegration_pairs(
                tickers=tickers,
                lookback_days=kwargs.pop("lookback_days", 252),
                p_value_threshold=0.05,
                max_half_life=None,
                include_spread_series=False,
                db=Mock(),
                data_service=_market(frames),
                cache_service=None,
                **kwargs,
            )
    finally:
        _IN_MEMORY_COINT_CACHE.clear()


def _payload(response):
    """What the AI-context exporter actually serialises."""
    return json.loads(response.model_dump_json())


def _all_payload_keys(node):
    """Every mapping key anywhere in a decoded payload, at any depth."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _all_payload_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _all_payload_keys(item)


def _depth_warning(payload):
    return next(
        (
            text
            for text in payload.get("warnings", [])
            if text.startswith("Depth-limited pairs:")
        ),
        None,
    )


# ------------------------------------------------------- DEFECT 1: no error:null


class TestNoNullErrorSentinel:
    async def test_successful_scan_publishes_no_error_key(self):
        frames = _universe(deep=174, young=174)
        result = await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", frames)

        payload = _payload(result)
        assert "error" not in payload, (
            "a clean scan must not publish `error: null`; absent means no failure"
        )
        # The pre-existing Python-level read stays safe and falsy.
        assert getattr(result, "error", None) is None
        # DEFECT 1 is about the KEY, so the belt-and-braces check is about
        # keys too. It used to be `"error" not in json.dumps(payload)`, which
        # also banned the word from every value - and the payload now has to
        # name the multiplicity correction it applied
        # (`bonferroni_family_wise_error`), whose canonical name contains that
        # word. A key-wise sweep is the same invariant stated precisely, and it
        # is strictly broader: it also catches the key at any nesting depth,
        # which the substring check on a flat dump could not distinguish from
        # prose.
        assert "error" not in set(_all_payload_keys(payload)), (
            "a clean scan must publish no `error` key at any depth; absent means "
            "no failure"
        )

    async def test_depth_limited_scan_also_publishes_no_error_key(self):
        result = await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", _universe())
        payload = _payload(result)
        assert payload["depth_status"] == "partial"
        assert "error" not in payload

    async def test_single_ticker_universe_publishes_no_error_key(self):
        result = await _scan("INFY.NS", _universe())
        payload = _payload(result)
        assert result.data_status == "unavailable"
        assert "error" not in payload

    async def test_genuine_failure_keeps_its_error(self):
        frames = _universe()
        market = _FakeMarket({"INFY.NS": frames["INFY.NS"]})  # TCS.NS missing
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
                    data_service=market,
                    cache_service=None,
                )
        finally:
            _IN_MEMORY_COINT_CACHE.clear()

        payload = _payload(result)
        assert payload["error"] == (
            "Insufficient price data available for at least 2 tickers"
        )
        assert payload["missing_tickers"] == ["TCS.NS"]
        assert getattr(result, "error", None)

    async def test_service_reported_error_survives_the_copy(self):
        """A real error on the scan result is kept, not silently dropped."""
        failing = CointScannerResponse(
            as_of="2026-04-01",
            universe_size=2,
            scanned_pairs_count=0,
            cointegrated_pairs_count=0,
            pairs=[],
            error="scan aborted: provider outage",
        )

        class _FailingCoint:
            def __init__(self, **_kwargs):
                pass

            async def scan_pairs(self, **_kwargs):
                return failing

        _IN_MEMORY_COINT_CACHE.clear()
        try:
            with patch.object(analytics_mod, "CointegrationService", _FailingCoint):
                result = await get_cointegration_pairs(
                    tickers="INFY.NS,TCS.NS",
                    lookback_days=252,
                    p_value_threshold=0.05,
                    max_half_life=None,
                    include_spread_series=False,
                    db=Mock(),
                    data_service=_market(_universe()),
                    cache_service=None,
                )
        finally:
            _IN_MEMORY_COINT_CACHE.clear()

        assert _payload(result)["error"] == "scan aborted: provider outage"

    async def test_blank_error_string_is_not_a_failure(self):
        blank = CointScannerResponse(
            as_of="2026-04-01",
            universe_size=2,
            scanned_pairs_count=0,
            cointegrated_pairs_count=0,
            pairs=[],
            error="   ",
        )

        class _BlankCoint:
            def __init__(self, **_kwargs):
                pass

            async def scan_pairs(self, **_kwargs):
                return blank

        _IN_MEMORY_COINT_CACHE.clear()
        try:
            with patch.object(analytics_mod, "CointegrationService", _BlankCoint):
                result = await get_cointegration_pairs(
                    tickers="INFY.NS,TCS.NS",
                    lookback_days=252,
                    p_value_threshold=0.05,
                    max_half_life=None,
                    include_spread_series=False,
                    db=Mock(),
                    data_service=_market(_universe()),
                    cache_service=None,
                )
        finally:
            _IN_MEMORY_COINT_CACHE.clear()

        # An empty message is not a failure worth a key.
        assert "error" not in _payload(result)


# --------------------------------------------------- DEFECT 2: declare the unit


class TestDeclaredMonetaryUnit:
    async def test_nse_universe_declares_inr(self):
        result = await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", _universe(deep=174, young=174))
        payload = _payload(result)

        assert payload["currency"] == "INR"
        assert payload["currency_provenance"] == "derived"
        basis = payload["currency_basis"]
        # The basis must name the fields whose unit is being declared and say
        # the unit is a property of the calculation, not read off a quote.
        assert "last_price_a" in basis and "last_price_b" in basis
        assert "intercept_alpha" in basis
        assert "INR" in basis

    async def test_us_universe_declares_usd(self):
        """The unit is verified from the data used, not hardcoded to INR."""
        index = pd.bdate_range("2026-01-01", periods=174)
        rng = np.random.default_rng(7)
        a = pd.Series(100.0 + np.cumsum(rng.normal(0.1, 1.0, 174)), index=index)
        b = 1.4 * a + 5.0 + pd.Series(rng.normal(0.0, 0.3, 174), index=index)
        frames = {"AAPL": _frame(a.to_numpy(), a.index), "MSFT": _frame(b.to_numpy(), b.index)}

        payload = _payload(await _scan("AAPL,MSFT", frames))
        assert payload["currency"] == "USD"
        assert payload["currency_provenance"] == "derived"

    async def test_exporter_now_resolves_the_pairs_currency(self):
        result = await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", _universe(deep=174, young=174))
        exported = _jsonable(result)
        assert _infer_currency(exported, {}) == "INR"
        assert exported["currency_provenance"] == "derived"

    async def test_mixed_currency_universe_declares_no_single_unit(self):
        index = pd.bdate_range("2026-01-01", periods=174)
        rng = np.random.default_rng(11)
        a = pd.Series(100.0 + np.cumsum(rng.normal(0.05, 1.0, 174)), index=index)
        b = 1.2 * a + 4.0 + pd.Series(rng.normal(0.0, 0.3, 174), index=index)
        us = pd.Series(150.0 + np.cumsum(rng.normal(0.2, 1.2, 174)), index=index)
        frames = _universe(
            extra={
                "AAPL": _frame(us.to_numpy(), us.index),
                "500112.BO": _frame(b.to_numpy(), b.index),
            }
        )

        payload = _payload(await _scan("INFY.NS,TCS.NS,500112.BO,AAPL", frames))
        assert "currency" not in payload
        assert payload["currency_provenance"] == "mixed"
        assert "INR" in payload["currency_basis"] and "USD" in payload["currency_basis"]
        assert any("no single monetary unit" in w for w in payload["warnings"])
        # A mixed scan must not be labelled with one arbitrary component.
        assert _infer_currency(_jsonable(payload), {}) is None

    async def test_no_pairs_means_no_declared_unit(self):
        """Nothing monetary is published, so nothing monetary is claimed."""
        payload = _payload(await _scan("INFY.NS", _universe()))
        assert "currency" not in payload
        assert payload["currency_provenance"] == "unavailable"
        assert _infer_currency(payload, {}) is None

    async def test_declared_unit_matches_the_prices_actually_delivered(self):
        frames = _universe(deep=174, young=174)
        result = await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", frames)
        payload = _payload(result)
        delivered = {
            ticker
            for pair in payload["pairs"]
            for ticker in (pair["ticker_a"], pair["ticker_b"])
        }
        assert delivered == {"INFY.NS", "TCS.NS", "NIFTYIETF.NS"}
        assert all(ticker.endswith((".NS", ".BO")) for ticker in delivered)
        assert payload["currency"] == "INR"


# --------------------------------------------- DEFECT 3: say why it is partial


class TestPartialScanStatesItsReason:
    async def test_depth_limited_scan_warns_with_measured_counts(self):
        result = await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", _universe())
        payload = _payload(result)

        assert payload["data_status"] == "partial"
        assert payload["depth_status"] == "partial"
        warning = _depth_warning(payload)
        assert warning is not None, "a partial scan must state its reason"

        # Every number in the warning is a value the payload actually measured.
        assert payload["shallow_tickers"] == ["NIFTYIETF.NS"]
        counts = payload["usable_observations_by_ticker"]
        assert "NIFTYIETF.NS" in warning
        assert str(counts["NIFTYIETF.NS"]) in warning
        assert str(max(counts.values())) in warning
        assert f"{MIN_PAIR_DEPTH_RATIO:.0%}" in warning
        assert str(payload["minimum_depth_ratio"]) in warning
        assert str(payload["depth_limited_pair_count"]) in warning
        assert str(len(payload["pairs"])) in warning
        # ...and it says what the degradation means.
        assert "weaker evidence" in warning
        assert "partial" in warning

    async def test_warning_follows_the_data_not_a_hardcoded_string(self):
        shallow = _universe(deep=200, young=90)
        first = _depth_warning(_payload(await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", shallow)))
        deep = _universe(deep=200, young=200)
        assert _depth_warning(_payload(await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", deep))) is None

        counts = _payload(await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", shallow))
        assert "90 of 200" in first
        assert counts["usable_observations_by_ticker"]["NIFTYIETF.NS"] == 90

    async def test_warning_is_stable_across_runs(self):
        frames = _universe()
        first = _depth_warning(_payload(await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", frames)))
        second = _depth_warning(_payload(await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", frames)))
        # Cache hits on the second run must not change a single character.
        assert first == second

    async def test_shallow_tickers_are_sorted_not_ordered_by_input(self):
        rng = np.random.default_rng(3)
        index = pd.bdate_range("2026-01-01", periods=180)
        deep_a = pd.Series(100.0 + np.cumsum(rng.normal(0.05, 1.0, 180)), index=index)
        deep_b = 1.2 * deep_a + pd.Series(rng.normal(0.0, 0.3, 180), index=index)
        young_z = pd.Series(
            50.0 + np.cumsum(rng.normal(0.02, 0.3, 90)), index=index[90:]
        )
        young_a = pd.Series(
            70.0 + np.cumsum(rng.normal(0.02, 0.3, 92)), index=index[88:]
        )
        frames = {
            "DEEP1.NS": _frame(deep_a.to_numpy(), deep_a.index),
            "DEEP2.NS": _frame(deep_b.to_numpy(), deep_b.index),
            "YOUNGZ.NS": _frame(young_z.to_numpy(), young_z.index),
            "YOUNGA.NS": _frame(young_a.to_numpy(), young_a.index),
        }

        payload = _payload(
            await _scan("DEEP1.NS,DEEP2.NS,YOUNGZ.NS,YOUNGA.NS", frames)
        )
        assert payload["shallow_tickers"] == sorted(payload["shallow_tickers"])
        warning = _depth_warning(payload)
        # Request order was YOUNGZ before YOUNGA; the warning is sorted.
        assert warning.index("YOUNGA.NS") < warning.index("YOUNGZ.NS")

    async def test_no_warning_when_the_scan_is_not_partial(self):
        payload = _payload(
            await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", _universe(deep=174, young=174))
        )
        assert payload["depth_status"] == "available"
        assert payload["data_status"] == "available"
        assert "warnings" not in payload or _depth_warning(payload) is None

    async def test_pair_level_shortfall_without_a_shallow_ticker_still_warns(self):
        """Depth can be limited by a short overlap with no thin ticker."""
        rng = np.random.default_rng(19)
        index = pd.bdate_range("2026-01-01", periods=280)
        # Two peers share the first 180 sessions (the deepest pair, and the
        # reference every other pair is measured against).
        left_a = pd.Series(100.0 + np.cumsum(rng.normal(0.05, 1.0, 180)), index=index[:180])
        left_b = 1.3 * left_a + pd.Series(rng.normal(0.0, 0.3, 180), index=index[:180])
        # The third scrip is just as deep on its own, but on a shifted
        # calendar, so every pair it enters only overlaps for 80 sessions.
        shifted = pd.Series(
            80.0 + np.cumsum(rng.normal(0.04, 0.9, 180)), index=index[100:]
        )
        frames = {
            "LEFT1.NS": _frame(left_a.to_numpy(), left_a.index),
            "LEFT2.NS": _frame(left_b.to_numpy(), left_b.index),
            "SHIFTED.NS": _frame(shifted.to_numpy(), shifted.index),
        }

        result = await _scan("LEFT1.NS,LEFT2.NS,SHIFTED.NS", frames)
        payload = _payload(result)
        assert set(payload["usable_observations_by_ticker"].values()) == {180}
        assert payload["shallow_tickers"] == []
        assert payload["depth_status"] == "partial"
        warning = _depth_warning(payload)
        assert warning is not None
        assert "no single ticker is individually below the threshold" in warning
        assert f"{payload['depth_limited_pair_count']} of {len(payload['pairs'])}" in warning

    async def test_depth_warning_counts_rows_not_a_literal(self):
        payload = _payload(await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", _universe()))
        limited = sum(
            1 for pair in payload["pairs"] if pair["depth_status"] == "partial"
        )
        assert limited == payload["depth_limited_pair_count"]
        assert f"{limited} of {len(payload['pairs'])} delivered pairs" in _depth_warning(
            payload
        )


# ------------------------------------------------- invariants that must not move


class TestPreservedInvariants:
    async def test_combinatorial_counts_still_hold(self):
        result = await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", _universe())
        payload = _payload(result)

        assert payload["returned_pairs_count"] == len(payload["pairs"])
        assert (
            payload["returned_cointegrated_pairs_count"]
            + payload["returned_non_cointegrated_pairs_count"]
            == len(payload["pairs"])
        )
        assert payload["returned_cointegrated_pairs_count"] == sum(
            1 for pair in payload["pairs"] if pair["is_cointegrated"]
        )
        assert payload["requested_universe_size"] == 3

    async def test_data_status_and_universe_scope_are_unchanged(self):
        result = await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", _universe())
        payload = _payload(result)

        # Ticket 01/03/07: route-owned scope, weightless coverage, ordering.
        assert payload["universe_scope"] == "holdings_and_watchlist"
        assert "weight_basis" not in payload["universe_coverage"]
        assert payload["universe_coverage"]["depth_status"] == payload["depth_status"]
        assert payload["universe_coverage"]["shallow_tickers"] == payload["shallow_tickers"]
        assert payload["requested_tickers"] == ["INFY.NS", "TCS.NS", "NIFTYIETF.NS"]
        assert payload["available_tickers"] == ["INFY.NS", "TCS.NS", "NIFTYIETF.NS"]
        assert payload["test_roles"] == {
            "engle_granger": "published_decision",
            "johansen": "diagnostic_only",
        }

    async def test_response_is_still_a_coint_scanner_response(self):
        result = await _scan("INFY.NS,TCS.NS,NIFTYIETF.NS", _universe())
        assert isinstance(result, CointScannerResponse)
        assert isinstance(result.pairs[0], CointPairResult)
        # D-07: the disclosures are DECLARED on the foundation-owned schema, not
        # smuggled in as `extra="allow"` extras. FastAPI re-serializes a route
        # response against the declared `response_model`, so a field only the
        # route adds at runtime is dropped from the HTTP wire even though the
        # in-process exporter can see it: the AI path was audited and the direct
        # API path was not. Declaring them is what makes the two agree.
        for name in ("currency", "currency_provenance", "currency_basis", "warnings"):
            assert name in CointScannerResponse.model_fields
        assert set(CointScannerResponse.model_fields).issuperset(
            {
                "as_of",
                "universe_size",
                "scanned_pairs_count",
                "cointegrated_pairs_count",
                "pairs",
                "error",
                "depth_status",
                "shallow_tickers",
            }
        )
        # Every declared field keeps its own type, default and validation.
        fields = CointScannerResponse.model_fields
        for name in ("currency", "currency_provenance", "currency_basis"):
            assert fields[name].annotation is Optional[str]
            assert fields[name].default is None
        assert fields["warnings"].annotation == List[str]
        assert fields["warnings"].get_default(call_default_factory=True) == []

    async def test_cached_pair_rows_still_load_from_the_unchanged_pair_schema(self):
        """`CointPairResult(**cached_row)` must keep working unchanged."""
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
