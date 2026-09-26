"""Wave-2 open defects D-03 (liquidity estimate) and D-05 (benchmark series).

Both defects were the same shape: the per-record facts were already correct and
the SECTION HEADLINE did not aggregate them.

D-03  `overall_score: 8.0`, `data_status: available`, zero warnings, while 5 of
      14 market caps were annualised from turnover or sat on the fixed INR 1bn
      floor.  A score banded partly on a hard-coded floor was published as a
      clean measurement.  The section now counts the non-measured legs, names
      them, demotes itself to `partial` and says why - which is also what makes
      the linked dashboard `summary.data.liquidity_score` withdraw the claim
      instead of silently inheriting it.

D-05  The benchmark series was wrong at both ends: row 0's `benchmark_value` was
      bit-identical to its own `portfolio_value` and flagged as nothing, row 0
      published a `return` measured against a portfolio value the response
      never delivered, and the NEWEST row carried no benchmark at all.  The
      warm-up row is now labelled and its return is null; a session the
      benchmark was not measured on is withheld from the comparison and named,
      never invented.

Each section drives the real audit rules (`NUM-006`, `NUM-019`) over the
payload the route actually returns, and then re-runs them over the pre-fix
shape: a fix that makes a rule green by deleting what the rule reads has to
fail these mutations.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import numpy as np
import pandas as pd
import pytest

from app.api import analytics as analytics_mod
from app.api.analytics import (
    get_liquidity_metrics,
    get_performance_history,
)
from app.debugging import context_audit as ca
from app.models.database import PortfolioPosition

ENVELOPE_KEYS = {
    "data", "data_status", "as_of", "as_of_semantics", "history_coverage", "warnings",
    # QM-1 breadth disclosure. These four are ADDITIVE: the default bare-array
    # response is untouched, and the six original keys keep their names, types
    # and positions. Breadth sits beside `data` because it qualifies the series
    # rather than the window.
    "constituent_count", "constituent_count_basis", "partial_basket_policy",
    "refused_partial_coverage_rows",
}
COVERAGE_KEYS = {
    "requested_start", "requested_end", "requested_days", "delivered_start",
    "delivered_end", "observation_count", "expected_observation_count",
    "first_observation", "last_observation", "coverage_ratio", "truncated",
    "stale", "status",
    # QM-1: a portfolio value is only emitted where every priced position has a
    # price, so a partial basket is refused rather than renormalised. That
    # refusal was correct but invisible, so a short series read like a thin one.
    "constituent_count", "constituent_count_basis", "partial_basket_policy",
    "measurable_price_rows", "complete_coverage_price_rows",
    "refused_partial_coverage_price_rows",
}


# ---------------------------------------------------------------------------
# audit harness - the real rules, over the real payload
# ---------------------------------------------------------------------------
def _section(key: str, data: Any, **overrides: Any) -> dict:
    section = {
        "key": key,
        "title": key.replace("_", " ").title(),
        "route": f"/{key}",
        "status": "available",
        "detail": "summary",
        "generated_at": "2026-09-26T05:57:43.164091Z",
        "inputs": {},
        "coverage": None,
        "data": data,
        "as_of": "2026-09-25",
        "as_of_semantics": "latest_observation_date",
        "currency": "INR",
        "warnings": [],
    }
    section.update(overrides)
    return section


def _export(sections: dict) -> dict:
    return {
        "schema_version": ca.EXPECTED_SCHEMA_VERSION,
        "export_id": "portfolio-open-defect",
        "generated_at": "2026-09-26T05:57:43.164091Z",
        "completed_at": "2026-09-26T05:58:16.698733Z",
        "snapshot_consistency": "best_effort",
        "base_currency": "INR",
        "detail": "summary",
        "scope": list(sections),
        "sections": sections,
        "warnings": [],
    }


def _findings(export: dict, rule_id: str) -> list:
    findings = ca.run_rules(ca.Export(doc=export, raw=json.dumps(export)))[0]
    return [finding for finding in findings if finding.rule_id == rule_id]


# ---------------------------------------------------------------------------
# liquidity seams
# ---------------------------------------------------------------------------
def _rows(rows):
    scalars = Mock()
    scalars.all.return_value = list(rows)
    scalars.first.return_value = rows[0] if rows else None
    result = Mock()
    result.scalars.return_value = scalars
    result.scalar_one_or_none.return_value = rows[0] if rows else None
    return result


def _db(rows):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=lambda *_a, **_k: _rows(rows))
    return db


def _pos(ticker, *, market_value=100_000.0, sector="Energy"):
    return PortfolioPosition(
        id=1, ticker=ticker, weight=None, quantity=1.0, buy_price=None,
        last_price=market_value, market_value=market_value, region="IN",
        sector=sector, industry="Y", added_on=None,
    )


class _QuoteMarket:
    """Quote caps are supplied per ticker; an absent cap stays absent."""

    def __init__(self, frames, caps=None):
        self.frames = frames
        self.caps = caps or {}
        self.fetch_historical_data = AsyncMock(side_effect=self._history)
        self.fetch_quote = AsyncMock(side_effect=self._quote)

    async def _history(self, ticker, start, end):
        frame = self.frames.get(ticker)
        if frame is None:
            return pd.DataFrame()
        window = frame.loc[
            (frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))
        ]
        return window.copy()

    async def _quote(self, ticker):
        return {"market_cap": self.caps.get(ticker)}


def _ohlcv(dates, *, price=100.0, volume=1_000_000.0):
    return pd.DataFrame(
        {"Close": np.full(len(dates), price), "Volume": np.full(len(dates), volume)},
        index=dates,
    )


_LIQ_DATES = pd.bdate_range(end=pd.Timestamp("2026-09-22"), periods=20)


async def _liquidity(caps, *, frames=None, positions=None):
    frames = frames if frames is not None else {
        ticker: _ohlcv(_LIQ_DATES) for ticker in caps
    }
    tickers = positions if positions is not None else list(caps)
    return await get_liquidity_metrics(
        db=_db([_pos(ticker) for ticker in tickers]),
        data_service=_QuoteMarket(frames, caps),
        analytics_engine=analytics_mod.AnalyticsEngine(),
    )


# A quote cap of None/0 falls through to the annualised-turnover estimate, and a
# book too thin to imply one lands on the INR 1bn floor: the three provenances
# in one response.
_MIXED_CAPS = {
    "MEASURED.NS": 2.0e11,
    "ETF.NS": None,
    "IPO.NS": None,
}
_MIXED_FRAMES = {
    "MEASURED.NS": _ohlcv(_LIQ_DATES, price=100.0, volume=2_000_000.0),
    # 1,000,000 x INR 100 = INR 1e8/day, so the implied cap (x250) clears the
    # floor: an estimate, not a measurement.
    "ETF.NS": _ohlcv(_LIQ_DATES, price=100.0, volume=1_000_000.0),
    # 1,000 x INR 10 = INR 10,000/day, so even the implied cap is below the
    # floor: the floor itself.
    "IPO.NS": _ohlcv(_LIQ_DATES, price=10.0, volume=1_000.0),
}


# ---------------------------------------------------------------------------
# D-03: the section discloses the estimate
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_liquidity_counts_every_non_measured_market_cap():
    """D-03: 5 of 14 caps non-measured, and the headline aggregated none."""
    result = await _liquidity(_MIXED_CAPS, frames=_MIXED_FRAMES)

    provenance = {
        ticker: row["market_cap_provenance"]
        for ticker, row in result["by_position"].items()
    }
    assert provenance == {
        "MEASURED.NS": "measured",
        "ETF.NS": "estimated",
        "IPO.NS": "fallback",
    }
    assert result["estimated_market_cap_count"] == 2
    assert result["measured_market_cap_count"] == 1
    assert result["market_cap_count"] == 3
    assert result["non_measured_market_caps"] == ["ETF.NS", "IPO.NS"]
    assert result["non_measured_by_provenance"] == {
        "estimated": ["ETF.NS"],
        "fallback": ["IPO.NS"],
    }
    assert result["fallback_market_cap_count"] == 1
    # The scoring block counts the same legs, so the two disclosures agree.
    assert result["scoring"]["market_cap_provenance"] == {
        "estimated": 1,
        "fallback": 1,
        "measured": 1,
    }


@pytest.mark.asyncio
async def test_an_estimated_leg_demotes_the_section_and_warns():
    """A fallback-derived score is not a clean measurement of the book."""
    result = await _liquidity(_MIXED_CAPS, frames=_MIXED_FRAMES)

    assert result["data_status"] == "partial"
    warnings = result["warnings"]
    assert len(warnings) == 1 and isinstance(warnings[0], str)
    joined = warnings[0]
    assert "2 of 3" in joined
    assert "ETF.NS" in joined and "IPO.NS" in joined
    # The floor is named as the substitute it is, with the published value.
    assert "1,000,000,000" in joined
    assert "substitute for a measurement" in joined
    # Each leg still carries its OWN provenance and flag.
    assert result["by_position"]["IPO.NS"]["is_estimate"] is True
    assert result["by_position"]["ETF.NS"]["is_estimate"] is True
    assert result["by_position"]["MEASURED.NS"]["is_estimate"] is False


@pytest.mark.asyncio
async def test_a_fully_measured_book_stays_available_and_unwarned():
    """No estimate, no demotion: the disclosure never invents a degradation."""
    result = await _liquidity(
        {"AAA.NS": 2.0e11, "BBB.NS": 4.0e11},
        frames={"AAA.NS": _ohlcv(_LIQ_DATES), "BBB.NS": _ohlcv(_LIQ_DATES, price=50.0)},
    )

    assert result["estimated_market_cap_count"] == 0
    assert result["non_measured_market_caps"] == []
    assert result["data_status"] == "available"
    assert "warnings" not in result


@pytest.mark.asyncio
async def test_the_disclosure_does_not_move_the_score_band_or_the_counts():
    """The one score-keyed band rule is untouched by the disclosure.

    `score` rounds once and `category`, `liquidation_days` and the high/medium/
    low counts all derive from that same rounded value, so the section reports
    the score the engine banded - estimated leg or not.
    """
    result = await _liquidity(_MIXED_CAPS, frames=_MIXED_FRAMES)
    bands = {b["band"]: b for b in result["scoring"]["bands"]}

    def _band(score):
        return next(
            band
            for band in ("High", "Medium", "Low")
            if bands[band]["min_published_score"] is None
            or score >= bands[band]["min_published_score"]
        )

    for ticker, row in result["by_position"].items():
        assert row["score"] == round(row["score_raw"], 1), ticker
        band = _band(row["score"])
        assert row["category"] == band, ticker
        assert row["liquidation_days"] == bands[band]["liquidation_days"], ticker

    scores = [row["score"] for row in result["by_position"].values()]
    assert result["overall_score"] == round(float(np.mean(scores)), 1)
    assert result["overall_band"] == _band(result["overall_score"])
    assert result["risk_level"] == {
        "High": "Low", "Medium": "Medium", "Low": "High"
    }[result["overall_band"]]
    stats = result["volume_stats"]
    assert sum(
        stats[f"{name.lower()}_volume_pct"] for name in ("High", "Medium", "Low")
    ) == pytest.approx(100.0, abs=0.2)
    counted = stats["volume_band_position_counts"]
    assert counted["High"] == sum(1 for r in result["by_position"].values() if r["category"] == "High")
    assert sum(counted.values()) == result["market_cap_count"]


@pytest.mark.asyncio
async def test_num006_passes_on_the_route_payload_and_fails_on_the_old_headline():
    """The rule, not a comment: the fix closes NUM-006 and the mutation reopens it."""
    result = await _liquidity(_MIXED_CAPS, frames=_MIXED_FRAMES)

    fixed = _export({"liquidity": _section("liquidity", result)})
    assert _findings(fixed, "NUM-006") == []

    # The pre-fix headline: the same per-position rows, no section-level count,
    # no demotion, no warning.
    regressed = json.loads(json.dumps(result))
    for key in (
        "estimated_market_cap_count",
        "measured_market_cap_count",
        "market_cap_count",
        "non_measured_market_caps",
        "non_measured_by_provenance",
        "fallback_market_cap_count",
        "estimated_market_cap_basis",
        "warnings",
    ):
        regressed.pop(key, None)
    regressed["data_status"] = "available"
    before = _export({"liquidity": _section("liquidity", regressed)})
    findings = _findings(before, "NUM-006")
    assert findings, "the pre-fix headline must still fail NUM-006"
    assert "2 of 3" in findings[0].message


@pytest.mark.asyncio
async def test_a_partial_liquidity_section_withdraws_the_linked_summary_score():
    """`summary.data.liquidity_score` must not inherit the withdrawn claim.

    The link already refuses to promote a `partial` sibling into a summary
    headline; the section status is the only thing that triggers it, so a
    warn-only fix would have left the headline at 8.0 with no trace of the
    estimate.
    """
    from app.services.ai_context_service import _link_dashboard_summary

    result = await _liquidity(_MIXED_CAPS, frames=_MIXED_FRAMES)
    assert result["data_status"] == "partial"

    components = {
        "liquidity": {"status": result["data_status"], "data": result},
        "forecast_risk": {"status": "available", "data": {"portfolio": {}}},
        "summary": {"status": "available", "data": {"liquidity_score": None}},
    }
    warnings = _link_dashboard_summary(components)

    assert components["summary"]["data"]["liquidity_score"] is None
    field = components["summary"]["field_status"]["liquidity_score"]
    assert field["value"] is None
    assert field["source_section"] == "liquidity"
    assert field["source_status"] == "partial"
    assert "partial" in field["reason"]
    assert any("liquidity_score" in text and "partial" in text for text in warnings)

    # A warn-only fix (status left `available`) is exactly the silent inherit.
    available = json.loads(json.dumps(components))
    available["liquidity"]["status"] = "available"
    _link_dashboard_summary(available)
    assert available["summary"]["data"]["liquidity_score"] == result["overall_score"]


@pytest.mark.asyncio
async def test_unavailable_liquidity_still_publishes_no_score_and_no_estimate_count():
    """Nothing measured means nothing counted: the null stays null."""
    result = await get_liquidity_metrics(
        db=_db([_pos("AAA.NS")]), data_service=_QuoteMarket({}),
        analytics_engine=analytics_mod.AnalyticsEngine(),
    )

    assert result["data_status"] == "unavailable"
    assert result["overall_score"] is None
    assert result["overall_score_raw"] is None
    assert result["by_position"] == {}
    # A count would be a claim about a result that does not exist.
    assert "estimated_market_cap_count" not in result
    assert "warnings" not in result


# ---------------------------------------------------------------------------
# performance seams
# ---------------------------------------------------------------------------
_END = pd.Timestamp.now().normalize() - pd.Timedelta(days=1)


def _bdays(periods, end=None):
    return pd.bdate_range(end=end or _END, periods=periods)


def _position(ticker, *, quantity=1.0, last_price=100.0, added_on=None):
    return SimpleNamespace(
        ticker=ticker, region="IN", quantity=quantity, last_price=last_price,
        market_value=quantity * last_price, buy_price=None, added_on=added_on,
    )


# The book rises 0.1% a session and the benchmark 0.2%, so the two legs never
# coincide and an accidental copy of one into the other cannot hide behind equal
# numbers.
_BOOK_RETURN = 0.001
_BENCH_RETURN = 0.002


class _Market:
    """One ticker, a dated close series rising 0.1% a session."""

    def __init__(self, dates):
        self.dates = dates
        self.fetch_historical_data = AsyncMock(side_effect=self._fetch)

    async def _fetch(self, _ticker, start, end):
        window = self.dates[
            (self.dates >= pd.Timestamp(start)) & (self.dates <= pd.Timestamp(end))
        ]
        values = 100.0 * np.exp(np.arange(len(window)) * _BOOK_RETURN)
        return pd.DataFrame({"close": values}, index=window)


def _benchmark(returns_index, *, value=_BENCH_RETURN):
    """A benchmark whose RETURNS stop at `returns_index[-1]`.

    A return needs a prior price, so a real benchmark's newest price date never
    appears in its own return series.  That is the whole defect: the newest
    session of the book is where the two series part company.
    """
    return SimpleNamespace(
        get_returns=AsyncMock(return_value=pd.Series(value, index=returns_index))
    )


def _no_benchmark():
    return SimpleNamespace(get_returns=AsyncMock(return_value=pd.Series(dtype=float)))


async def _history(benchmark, dates, *, metadata=False):
    return await get_performance_history(
        days=90, tickers="AAA.NS", include_metadata=metadata,
        db=_db([_position("AAA.NS")]), data_service=_Market(dates),
        benchmark_service=benchmark,
    )


# ---------------------------------------------------------------------------
# D-05: the benchmark series is right at both ends
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_every_delivered_row_carries_a_measured_benchmark():
    """D-05: the newest row had no benchmark at all (19 of 20 rows had one)."""
    dates = _bdays(20)
    # The benchmark's newest RETURN is the second-to-last session.
    rows = await _history(_benchmark(dates[:-1]), dates)

    assert rows
    assert all("benchmark_value" in row for row in rows)
    # The trailing session has no benchmark, so it is not delivered as a
    # half-measured comparison row.
    assert [row["date"] for row in rows] == [str(day.date()) for day in dates[1:-1]]
    assert str(dates[-1].date()) not in {row["date"] for row in rows}


@pytest.mark.asyncio
async def test_the_first_row_publishes_no_return_against_an_undelivered_value():
    """D-05: row 0's return was measured against a value never delivered."""
    dates = _bdays(20)
    rows = await _history(_benchmark(dates), dates)

    first = rows[0]
    assert "return" in first, "the key stays, so every row keeps one shape"
    assert first["return"] is None
    assert first["warm_up"] is True
    assert "no prior portfolio value" in first["warm_up_reason"]
    # The pre-fix number on this row: the move off the undelivered first
    # observation.  It is a real, measured move - it is just measured against a
    # value this response never published.
    undelivered_prior = 100.0
    assert first["portfolio_value"] == pytest.approx(
        undelivered_prior * (1.0 + _BOOK_RETURN), abs=0.01
    )
    pre_fix = round(first["portfolio_value"] / undelivered_prior - 1.0, 6)
    assert first["return"] != pre_fix
    assert all(row["return"] is not None for row in rows[1:])
    assert all(row["warm_up"] is False for row in rows[1:])


@pytest.mark.asyncio
async def test_the_anchor_row_is_labelled_because_the_rebasing_makes_them_equal():
    """`benchmark_value == portfolio_value` on row 0 is the declared anchor."""
    dates = _bdays(20)
    rows = await _history(_benchmark(dates), dates)

    first = rows[0]
    assert first["benchmark_value"] == first["portfolio_value"]
    assert "anchors the benchmark rebasing" in first["warm_up_reason"]
    # Only the anchor shares a value with its own portfolio leg.
    for row in rows[1:]:
        assert row["benchmark_value"] != row["portfolio_value"], row["date"]


@pytest.mark.asyncio
async def test_the_withheld_session_is_named_not_invented():
    """Nothing is backfilled for a session the benchmark never measured."""
    dates = _bdays(20)
    rows = await _history(_benchmark(dates[:-1]), dates)

    last = rows[-1]
    assert last["withheld_portfolio_observation_count"] == 1
    assert last["withheld_portfolio_observations"] == [str(dates[-1].date())]
    assert "benchmark was not measured" in last["series_end_reason"]
    # The withheld session's portfolio value is nowhere in the response: it is
    # not delivered and not smuggled in as a benchmark.
    withheld_value = 100.0 * float(np.exp((len(dates) - 1) * _BOOK_RETURN))
    assert all(
        row["portfolio_value"] != pytest.approx(round(withheld_value, 2))
        for row in rows
    )
    # The last delivered benchmark is the rebased benchmark on ITS OWN date, not
    # the previous level carried forward: it is the anchor compounded over the
    # benchmark returns of every delivered session after the anchor.
    expected = rows[0]["portfolio_value"] * (
        (1.0 + _BENCH_RETURN) ** (len(rows) - 1)
    )
    assert last["benchmark_value"] == pytest.approx(round(expected, 2))
    assert last["benchmark_value"] != pytest.approx(rows[-2]["benchmark_value"])


@pytest.mark.asyncio
async def test_num019_passes_on_the_route_envelope_and_fails_on_the_old_series():
    """The rule, not a comment: the fix closes NUM-019 and the mutation reopens it."""
    dates = _bdays(20)
    envelope = await _history(_benchmark(dates[:-1]), dates, metadata=True)

    component = {
        "status": envelope["data_status"],
        "data": envelope["data"],
        "as_of": envelope["as_of"],
        "as_of_semantics": envelope["as_of_semantics"],
        "history_coverage": envelope["history_coverage"],
        "warnings": envelope["warnings"],
    }
    fixed = _export(
        {"dashboard": _section("dashboard", {"components": {"performance_history": component}})}
    )
    assert _findings(fixed, "NUM-019") == []

    # The pre-fix series: a warm-up return, an unlabelled identical benchmark,
    # and a newest row with no benchmark at all.
    regressed = json.loads(json.dumps(envelope["data"]))
    regressed[0]["return"] = 0.0001
    regressed[0].pop("warm_up", None)
    regressed[0].pop("warm_up_reason", None)
    regressed.append(
        {
            "date": str(dates[-1].date()),
            "portfolio_value": 43542.75,
            "return": 0.006271,
            "warm_up": False,
        }
    )
    before = _export(
        {
            "dashboard": _section(
                "dashboard",
                {"components": {"performance_history": {**component, "data": regressed}}},
            )
        }
    )
    findings = _findings(before, "NUM-019")
    assert len(findings) == 3, [f.message for f in findings]
    assert any("return=" in f.message for f in findings)
    assert any("bit-identical" in f.message for f in findings)
    assert any("no benchmark value" in f.message for f in findings)


@pytest.mark.asyncio
async def test_the_default_response_is_still_the_bare_array():
    """Six consumers assume an array; the shape and the key set are frozen."""
    dates = _bdays(20)
    rows = await _history(_benchmark(dates[:-1]), dates)

    assert isinstance(rows, list)
    assert rows and all(isinstance(row, dict) for row in rows)
    for row in rows:
        assert {"date", "portfolio_value", "return"} <= set(row)
    # Only two rows carry an extra disclosure: the warm-up row and the row the
    # series stops at.  Every other row has one identical shape.
    shapes = [frozenset(row) for row in rows]
    assert len(set(shapes)) == 3
    common = set(shapes[0]) & set(shapes[1]) & set(shapes[-1])
    assert {"date", "portfolio_value", "return", "benchmark_value"} <= common
    assert "withheld_portfolio_observations" in rows[-1]
    assert "warm_up_reason" in rows[0]


@pytest.mark.asyncio
async def test_the_envelope_shape_is_unchanged_and_names_the_withheld_session():
    dates = _bdays(20)
    envelope = await _history(_benchmark(dates[:-1]), dates, metadata=True)

    assert set(envelope) == ENVELOPE_KEYS
    assert set(envelope["history_coverage"]) == COVERAGE_KEYS
    # `as_of` is the last DELIVERED observation, never the requested end.
    assert envelope["as_of"] == envelope["data"][-1]["date"]
    assert envelope["as_of"] != envelope["history_coverage"]["requested_end"]
    assert envelope["history_coverage"]["delivered_end"] == envelope["as_of"]
    assert envelope["history_coverage"]["observation_count"] == len(envelope["data"])
    assert any(
        str(dates[-1].date()) in text and "no measured benchmark" in text
        for text in envelope["warnings"]
    ), envelope["warnings"]


@pytest.mark.asyncio
async def test_a_missing_benchmark_delivers_the_portfolio_series_and_says_so():
    """No benchmark is a disclosed degradation, never a silently bare chart."""
    dates = _bdays(20)
    rows = await _history(_no_benchmark(), dates)

    # Nothing is withheld: the portfolio leg is real and is delivered whole.
    assert [row["date"] for row in rows] == [str(day.date()) for day in dates[1:]]
    assert all("benchmark_value" not in row for row in rows)
    assert rows[0]["benchmark_series_status"] == "unavailable"
    assert "no row carries a benchmark value" in rows[0]["benchmark_unavailable_reason"]

    envelope = await _history(_no_benchmark(), dates, metadata=True)
    assert any("No benchmark was measured" in text for text in envelope["warnings"])
    assert envelope["as_of"] == rows[-1]["date"]


@pytest.mark.asyncio
async def test_a_benchmark_sharing_no_session_never_empties_the_series():
    """Degenerate alignment keeps the book; it does not deliver nothing."""
    dates = _bdays(20)
    rows = await _history(_benchmark(pd.DatetimeIndex(["1999-01-04"])), dates)

    assert rows, "a portfolio series was measured and must be delivered"
    assert all("benchmark_value" not in row for row in rows)
    assert rows[0]["benchmark_series_status"] == "unavailable"


# ---------------------------------------------------------------------------
# both sections still clear every other audit rule they touch
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_fixed_liquidity_payload_is_clean_for_the_whole_rule_set():
    result = await _liquidity(_MIXED_CAPS, frames=_MIXED_FRAMES)
    export = _export(
        {"liquidity": _section("liquidity", result, status="partial", warnings=result["warnings"])}
    )
    assert ca.run_rules(ca.Export(doc=export, raw=json.dumps(export)))[0] == []


@pytest.mark.asyncio
async def test_the_fixed_performance_payload_is_clean_for_the_whole_rule_set():
    dates = _bdays(20)
    envelope = await _history(_benchmark(dates[:-1]), dates, metadata=True)
    component = {
        "status": envelope["data_status"],
        "data": envelope["data"],
        "as_of": envelope["as_of"],
        "as_of_semantics": envelope["as_of_semantics"],
        "history_coverage": envelope["history_coverage"],
        "warnings": envelope["warnings"],
        # Breadth travels with the series, not only inside history_coverage, so
        # the component mirrors the envelope rather than cherry-picking keys.
        "constituent_count": envelope["constituent_count"],
        "constituent_count_basis": envelope["constituent_count_basis"],
        "partial_basket_policy": envelope["partial_basket_policy"],
        "refused_partial_coverage_rows": envelope["refused_partial_coverage_rows"],
    }
    export = _export(
        {
            "dashboard": _section(
                "dashboard",
                {"components": {"performance_history": component}},
                status="partial",
                warnings=envelope["warnings"],
            )
        }
    )
    assert ca.run_rules(ca.Export(doc=export, raw=json.dumps(export)))[0] == []
