"""Cross-section holding-window provenance: one rule, one answer (V3-08).

The v4 export let one portfolio carry three different holding dates:

* `regime` resolved JUNIORBEES.NS to 2024-03-28 against a stored `added_on` of
  2025-02-14, because the buy-price inference was fed the price frames THAT
  SECTION happened to fetch: its 1100-day HMM window reaches bars the 252-day
  realized-risk window never sees, so the "most recent match before the import
  stamp" moved 10.7 months. It was published as a bare `effective_start`, with
  no source, so it read as a holding date nobody had stored;
* `risk_contribution` called `effective_start_detail(holdings, None)` - no price
  frames, so no inference - and answered with the stored import date, moving
  its window start from 2026-08-03 to 2026-08-04 and re-asserting the "stored
  holding date" claim the remediation removed;
* the counts were measured in different units (masked price rows, aligned
  return rows, model observations) under one name, so 39 and 40 were both "the
  holding window", and `tear_sheet` labelled a 39-day result with a 365-day
  `window`.

These tests pin the replacement: one canonical evidence window, one start per
position, one count unit, provenance on every published start, and a request
window that is labelled as a request beside the window that was measured.

The market seam is WINDOW-AWARE on purpose. A route asking for 1100 days is
really handed every bar the fixture has; a route asking for 252 is handed only
the tail. A section that lets its own request decide a holding date therefore
fails here instead of passing by coincidence.

No network, no DB, seeded RNG only.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import numpy as np
import pandas as pd
import pytest

from app.api import analytics as analytics_mod
from app.api.analytics import (
    HOLDING_COVERED_DAYS_SCOPE,
    HOLDING_EVIDENCE_CANONICAL,
    HOLDING_PROVENANCE_LOOKBACK_DAYS,
    HOLDING_PROVENANCE_RULE,
    HOLDING_WIDE_FRAME_COVERED_DAYS_SCOPE,
    MEASURED_WINDOW_COVERED_DAYS_SCOPE,
    canonical_holding_window_input,
    get_regime,
    get_risk_contribution,
    get_tear_sheet,
    holding_evidence_window,
    holding_provenance,
    holding_window_observation_count,
    publish_holding_coverage,
)
from app.models.database import PortfolioPosition
from app.utils.holdings import effective_start_detail, implied_start_from_price

# Fixture geometry. The intersection start is the INFERRED date of FRESH.NS
# (one bar before its stored stamp), which is what makes the cross-section
# assertion bite: a section that answers from stored dates alone reports the
# next day and the three sections disagree.
FRESH_INFERRED_OFFSET = -42  # index of the matched bar
FRESH_ADDED_OFFSET = -41     # index of the stored import stamp
OLD_ADDED_OFFSET = 5         # ~700 sessions back: outside every evidence window
OLD_BUY_OFFSET = 3           # a bar the WIDE window can see and match
BARS = 700


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


def _pos(ticker, *, added_on, buy_price=None, sector="Tech"):
    return PortfolioPosition(
        id=1, ticker=ticker, weight=0.5, quantity=10.0, buy_price=buy_price,
        last_price=100.0, market_value=10000.0, region="IN", sector=sector,
        industry="Y", added_on=added_on,
    )


class _WindowedMarket:
    """Price frames served for the REQUESTED window only.

    This is the whole point of the fixture: `fetch_historical_data` honours
    `[start, end]`, so a 1100-day request and a 252-day request do not see the
    same bars. A section whose holding dates move with its own analytics window
    cannot pass here.
    """

    def __init__(self, frames: Dict[str, pd.DataFrame]):
        self.frames = frames
        self.requests: List[tuple] = []
        self.fetch_historical_data = AsyncMock(side_effect=self._fetch)

    async def _fetch(self, ticker, start, end):
        self.requests.append((ticker, start, end))
        frame = self.frames.get(ticker)
        if frame is None or frame.empty:
            return pd.DataFrame()
        low = pd.Timestamp(start).normalize() if start else frame.index[0]
        high = pd.Timestamp(end).normalize() if end else frame.index[-1]
        sliced = frame.loc[(frame.index >= low) & (frame.index <= high)]
        return sliced.copy()


def _fixture():
    """One holdings + price world, shared by every section under test."""
    end = pd.Timestamp.now().normalize()
    dates = pd.bdate_range(end=end, periods=BARS)
    rng = np.random.default_rng(20260926)
    closes = {
        "FRESH.NS": 100.0 * np.exp(np.cumsum(rng.normal(0.0006, 0.011, BARS))),
        "OLD.NS": 240.0 * np.exp(np.cumsum(rng.normal(-0.0002, 0.013, BARS))),
    }
    frames = {
        ticker: pd.DataFrame({"adj_close": pd.Series(values, index=dates)})
        for ticker, values in closes.items()
    }
    positions = [
        # The buy price is the close one bar before the import stamp, so the
        # buy-price match is a real bar and the inferred start is a real date.
        _pos(
            "FRESH.NS",
            added_on=dates[FRESH_ADDED_OFFSET].to_pydatetime(),
            buy_price=float(closes["FRESH.NS"][FRESH_INFERRED_OFFSET]),
        ),
        # Imported long ago with a buy price the WIDE 1100-day window can match.
        # A wide window would infer a pre-`added_on` date here; the canonical
        # evidence window has no bar before the stamp at all, so the stored
        # date is the only honest answer - and every section must give it.
        _pos(
            "OLD.NS",
            added_on=dates[OLD_ADDED_OFFSET].to_pydatetime(),
            buy_price=float(closes["OLD.NS"][OLD_BUY_OFFSET]),
        ),
    ]
    return dates, closes, frames, positions


def _market(frames) -> _WindowedMarket:
    return _WindowedMarket(frames)


def _benchmark():
    return SimpleNamespace(get_returns=AsyncMock(return_value=None))


def _regime_payload(conditional_days: int) -> Dict[str, Any]:
    return {
        "current_regime": "calm",
        "regime": "calm",
        "probability_unit": "posterior_probability",
        "benchmark": "^NSEI",
        "posterior_type": "filtered",
        "units": {"returns": "fraction"},
        "portfolio_in_current_regime": {
            "days": conditional_days,
            "ann_ret": None,
            "ann_vol": None,
            "total_ret": 0.02,
            "annualized": False,
        },
    }


# ---------------------------------------------------------------------------
# the shared rule, on its own
# ---------------------------------------------------------------------------
def test_evidence_window_is_anchored_to_the_requested_end():
    window = holding_evidence_window("2026-09-26")
    assert window == {"start": "2026-01-17", "end": "2026-09-26", "days": 252}
    assert window["days"] == HOLDING_PROVENANCE_LOOKBACK_DAYS
    # Deterministic: the same end reproduces the same evidence window, with no
    # clock read, so a re-run of the same export is not a new answer.
    assert holding_evidence_window("2026-09-26") == window
    # An unusable end yields no window rather than a guessed one.
    assert holding_evidence_window(None)["start"] is None
    assert holding_evidence_window("not-a-date")["start"] is None


@pytest.mark.asyncio
async def test_provenance_does_not_depend_on_how_wide_the_frame_is():
    """E-1: the inference sees the canonical slice, never the route's window."""
    dates, closes, frames, positions = _fixture()
    holdings = {
        "OLD.NS": {
            "added_on": str(dates[OLD_ADDED_OFFSET].date()),
            "buy_price": float(closes["OLD.NS"][OLD_BUY_OFFSET]),
        },
    }
    wide = {t: f["adj_close"] for t, f in frames.items()}
    end = str(dates[-1].date())
    canonical_start = holding_evidence_window(end)["start"]
    narrow = {
        ticker: series.loc[series.index >= pd.Timestamp(canonical_start)]
        for ticker, series in wide.items()
    }

    # The fixture is discriminating: a wide window DOES find a pre-`added_on`
    # match for this position, which is exactly what regime used to publish.
    naive = implied_start_from_price(
        wide["OLD.NS"], holdings["OLD.NS"]["buy_price"], holdings["OLD.NS"]["added_on"]
    )
    assert naive is not None and naive < holdings["OLD.NS"]["added_on"]

    narrow_result = await holding_provenance(
        Mock(), holdings, ["OLD.NS"], end=end, frames=narrow,
    )
    wide_result = await holding_provenance(
        Mock(), holdings, ["OLD.NS"], end=end, frames=wide,
    )
    for result in (narrow_result, wide_result):
        entry = result["detail"]["OLD.NS"]
        assert entry["analytics_start"] == holdings["OLD.NS"]["added_on"]
        assert entry["analytics_start_source"] == "stored_added_on"
        assert entry["buy_price_inferred"] is None
        assert result["evidence_window"]["source"] == "in_hand_price_frames"
    assert narrow_result["start"] == wide_result["start"]


@pytest.mark.asyncio
async def test_in_hand_frames_beat_a_second_read():
    """Frames the caller already holds are reused, not re-fetched."""
    dates, closes, frames, _ = _fixture()
    holdings = {
        "FRESH.NS": {
            "added_on": str(dates[FRESH_ADDED_OFFSET].date()),
            "buy_price": float(closes["FRESH.NS"][FRESH_INFERRED_OFFSET]),
        },
    }
    market = _market(frames)
    result = await holding_provenance(
        market, holdings, ["FRESH.NS"],
        end=str(dates[-1].date()),
        frames={t: f["adj_close"] for t, f in frames.items()},
    )
    assert market.fetch_historical_data.await_count == 0
    entry = result["detail"]["FRESH.NS"]
    assert entry["analytics_start"] == str(dates[FRESH_INFERRED_OFFSET].date())
    assert entry["analytics_start_source"] == "buy_price_inferred"
    assert entry["stored_added_on"] == holdings["FRESH.NS"]["added_on"]
    assert result["start"] == entry["analytics_start"]


@pytest.mark.asyncio
async def test_evidence_read_falls_back_to_stored_dates_and_says_so():
    """No readable evidence is a declared degradation, never a silent answer."""
    holdings = {"A.NS": {"added_on": "2026-08-04", "buy_price": 12.5}}
    market = _market({})
    result = await holding_provenance(
        market, holdings, ["A.NS"], end="2026-09-26",
    )
    assert result["evidence_window"]["source"] == "stored_dates_only"
    payload = publish_holding_coverage(
        detail=result["detail"], per_ticker={},
        requested_start="2025-09-26", requested_end="2026-09-26",
        covered_days=3, evidence_window=result["evidence_window"],
    )
    assert payload["intersection_start"] == "2026-08-04"
    assert "provenance_divergence_reason" in payload
    assert "stored import date" in payload["provenance_divergence_reason"]


def test_canonical_holding_window_input_pins_the_start():
    detail = {
        "A.NS": {
            "analytics_start": "2026-08-03", "analytics_start_source": "buy_price_inferred",
            "stored_added_on": "2026-08-04", "buy_price_inferred": "2026-08-03",
        },
        "B.NS": {
            "analytics_start": None, "analytics_start_source": "unknown",
            "stored_added_on": None, "buy_price_inferred": None,
        },
    }
    pinned = canonical_holding_window_input(detail)
    # The start is handed over as the import date and the buy price is withheld,
    # so a masked leg cannot re-infer a different date from a wider window.
    assert pinned == {"A.NS": {"added_on": "2026-08-03", "buy_price": None}}
    # Nothing changes: a leg fed the pinned map resolves the same start.
    dates = pd.bdate_range("2026-07-01", periods=40)
    series = pd.Series(np.arange(40.0), index=dates)
    assert effective_start_detail(pinned, {"A.NS": series})["A.NS"]["analytics_start"] == "2026-08-03"


def test_observation_count_is_return_rows_inside_the_window():
    dates = pd.bdate_range("2026-07-01", periods=40)
    frame = pd.Series(np.arange(40.0), index=dates)
    start = str(dates[9].date())
    # The bar on the start date is the first held price and has no held
    # predecessor: 30 of the 40 rows after it count, and the row ON it does not.
    count, mask = holding_window_observation_count(frame, start)
    assert count == 30
    assert int(mask.sum()) == 30
    assert bool(mask.loc[dates[9]]) is False
    # A frame already masked at this start hands its own measurement in.
    assert holding_window_observation_count(
        frame, start, measured_count=30, measured_start=start,
    )[0] == 30
    # ... and a frame masked to a DIFFERENT start is measured here instead.
    assert holding_window_observation_count(
        frame, start, measured_count=99, measured_start=str(dates[2].date()),
    )[0] == 30
    # An unknown start carries no holding information: nothing is guessed.
    assert holding_window_observation_count(frame, None)[0] == 40
    assert holding_window_observation_count(None, start)[0] == 0


def test_publish_declares_the_unit_and_the_evidence():
    payload = publish_holding_coverage(
        detail={
            "A.NS": {
                "analytics_start": "2026-08-03",
                "analytics_start_source": "buy_price_inferred",
                "stored_added_on": "2026-08-04",
                "buy_price_inferred": "2026-08-03",
            },
        },
        per_ticker={"A.NS": {"raw_days": 40, "masked_days": 40, "return_observations": 39}},
        requested_start="2025-09-26", requested_end="2026-09-26",
        covered_days=39,
        evidence_window={
            "start": "2026-01-17", "end": "2026-09-26", "days": 252,
            "source": HOLDING_EVIDENCE_CANONICAL,
        },
    )
    assert payload["covered_days"] == 39
    assert payload["covered_days_scope"] == HOLDING_COVERED_DAYS_SCOPE
    assert payload["provenance_rule"] == HOLDING_PROVENANCE_RULE
    assert payload["provenance_evidence_window"]["source"] == HOLDING_EVIDENCE_CANONICAL
    assert payload["requested_end"] == "2026-09-26"
    # Every published start carries the source that produced it.
    entry = payload["tickers"]["A.NS"]
    assert entry["analytics_start_source"] == "buy_price_inferred"
    assert entry["stored_added_on"] == "2026-08-04"
    assert payload["inferred_start_tickers"] == ["A.NS"]
    assert "provenance_divergence_reason" not in payload


# ---------------------------------------------------------------------------
# the three sections, one fixture
# ---------------------------------------------------------------------------
async def _three_sections() -> Dict[str, Any]:
    dates, _closes, frames, positions = _fixture()
    db = _db(positions)
    market = _market(frames)
    # The same calendar day every one of these routes defaults to, so all three
    # are asked about one end date and therefore one canonical evidence window.
    today = pd.Timestamp.now().strftime("%Y-%m-%d")

    async def _allocation(_tickers, _db):
        return ["FRESH.NS", "OLD.NS"], {"FRESH.NS": 0.5, "OLD.NS": 0.5}

    tear_sheet = await get_tear_sheet(
        tickers="FRESH.NS,OLD.NS", start="2025-09-26", end=today,
        db=db, data_service=market, benchmark=_benchmark(),
    )
    risk_contribution = await get_risk_contribution(
        tickers="FRESH.NS,OLD.NS", db=db, data_service=market,
    )
    with patch.object(analytics_mod, "resolve_allocation", side_effect=_allocation), \
         patch.object(
             analytics_mod, "detect_regime",
             new=AsyncMock(return_value=_regime_payload(19)),
         ):
        regime = await get_regime(
            lookback_days=1100, with_portfolio=True,
            db=db, data_service=market, benchmark=Mock(),
        )
    return {
        "regime": regime["history_coverage"],
        "tear_sheet": tear_sheet["history_coverage"],
        "risk_contribution": risk_contribution["history_coverage"]["holding_context"],
        "full": {"regime": regime, "tear_sheet": tear_sheet, "risk_contribution": risk_contribution},
        "dates": dates,
        "today": today,
    }


def _starts(coverage: Dict[str, Any]) -> Dict[str, Dict[str, Optional[str]]]:
    return {
        ticker: {
            "analytics_start": entry.get("analytics_start"),
            "analytics_start_source": entry.get("analytics_start_source"),
            "stored_added_on": entry.get("stored_added_on"),
            "buy_price_inferred": entry.get("buy_price_inferred"),
        }
        for ticker, entry in coverage["tickers"].items()
    }


@pytest.mark.asyncio
async def test_three_sections_publish_one_holding_window():
    """The cross-section gate: same start, same count, same unit, three times."""
    result = await _three_sections()
    dates = result["dates"]
    regime, tear_sheet, contribution = (
        result["regime"], result["tear_sheet"], result["risk_contribution"]
    )

    # 1. Per-ticker starts, sources and inference evidence are identical.
    assert _starts(regime) == _starts(tear_sheet) == _starts(contribution)

    # 2. The block start is identical, and it is the INFERRED date (one bar
    #    before FRESH.NS's import stamp) - not the stored date a
    #    stored-only section used to report.
    inferred = str(dates[FRESH_INFERRED_OFFSET].date())
    stored = str(dates[FRESH_ADDED_OFFSET].date())
    for coverage in (regime, tear_sheet, contribution):
        assert coverage["intersection_start"] == inferred
        assert coverage["intersection_start"] != stored
        assert coverage["effective_start"] == inferred
        assert coverage["intersection_start_source"] == "buy_price_inferred"
        assert coverage["inferred_start_tickers"] == ["FRESH.NS"]
        assert coverage["oldest_holding"] == str(dates[OLD_ADDED_OFFSET].date())

    # 3. The count is identical and each section names its own unit.
    counts = {coverage["covered_days"] for coverage in (regime, tear_sheet, contribution)}
    assert len(counts) == 1
    # 42 held price rows produce 41 return observations: the bar on the start
    # date is the first held price and has no held predecessor.
    held_price_rows = -FRESH_INFERRED_OFFSET
    assert counts == {held_price_rows - 1}
    # XS-001: the unit labels are deliberately NOT all the same any more.
    # `regime` and `tear_sheet` count a whole-book complete-coverage series;
    # `risk_contribution` counts the wide per-leg frame, which retains dates on
    # which some leg was unpriced. On THIS fixture the two populations have the
    # same length because no leg is sparse here - which is exactly why the
    # mislabel stayed invisible until a real book had a leg with price gaps, and
    # why "one shared label" was the wrong assertion rather than a stale one.
    assert regime["covered_days_scope"] == HOLDING_COVERED_DAYS_SCOPE
    assert tear_sheet["covered_days_scope"] == HOLDING_COVERED_DAYS_SCOPE
    assert (
        contribution["covered_days_scope"] == HOLDING_WIDE_FRAME_COVERED_DAYS_SCOPE
    )
    # The count is never a price-row count wearing a return-row name.
    assert all(
        coverage["covered_days"] < coverage["tickers"]["FRESH.NS"]["masked_days"] + 2
        for coverage in (regime, tear_sheet, contribution)
    )

    # 4. The evidence window behind those starts is published, so the answer is
    #    auditable rather than asserted.
    for coverage in (regime, tear_sheet, contribution):
        window = coverage["provenance_evidence_window"]
        assert window["end"] == result["today"]
        assert window["days"] == HOLDING_PROVENANCE_LOOKBACK_DAYS
        assert window["source"] == HOLDING_EVIDENCE_CANONICAL
        assert coverage["provenance_rule"] == HOLDING_PROVENANCE_RULE


@pytest.mark.asyncio
async def test_no_section_publishes_an_undeclared_pre_import_date():
    """E-1: a start that contradicts the stored stamp must declare itself."""
    result = await _three_sections()
    dates = result["dates"]
    for name in ("regime", "tear_sheet", "risk_contribution"):
        coverage = result[name]
        for ticker, entry in coverage["tickers"].items():
            stored = entry.get("stored_added_on")
            published = entry.get("analytics_start")
            if stored and published and published < stored:
                # A date earlier than the import stamp is a buy-price
                # reconstruction, and it says so out loud.
                assert entry["analytics_start_source"] == "buy_price_inferred"
                assert entry["buy_price_inferred"] == published
            else:
                assert entry["analytics_start_source"] == "stored_added_on"
                assert entry["buy_price_inferred"] is None
        # The wide HMM window really did contain matching bars for the old leg.
        assert coverage["tickers"]["OLD.NS"]["analytics_start"] == str(
            dates[OLD_ADDED_OFFSET].date()
        )
        assert coverage["tickers"]["OLD.NS"]["buy_price_inferred"] is None
        assert coverage["tickers"]["FRESH.NS"]["analytics_start"] == str(
            dates[FRESH_INFERRED_OFFSET].date()
        )
        assert coverage["tickers"]["FRESH.NS"]["stored_added_on"] == str(
            dates[FRESH_ADDED_OFFSET].date()
        )


@pytest.mark.asyncio
async def test_risk_contribution_keeps_the_buy_price_inference():
    """E-2: the section that had no price frames must not answer from stamps."""
    result = await _three_sections()
    dates = result["dates"]
    coverage = result["risk_contribution"]
    entry = coverage["tickers"]["FRESH.NS"]
    assert entry["analytics_start"] == str(dates[FRESH_INFERRED_OFFSET].date())
    assert entry["stored_added_on"] == str(dates[FRESH_ADDED_OFFSET].date())
    assert entry["buy_price_inferred"] == str(dates[FRESH_INFERRED_OFFSET].date())
    assert entry["analytics_start_source"] == "buy_price_inferred"
    assert coverage["inferred_start_tickers"] == ["FRESH.NS"]
    assert coverage["intersection_start"] == str(dates[FRESH_INFERRED_OFFSET].date())
    # The model evidence is still its own object, on its own count.
    outer = result["full"]["risk_contribution"]["history_coverage"]
    assert outer["covered_days_scope"] == "model_return_observations"
    assert outer["covered_days"] == outer["model_observation_count"]
    assert outer["covered_days"] > coverage["covered_days"] * 2
    assert outer["holding_window_days"] == coverage["covered_days"]
    assert outer["effective_start"] is None
    assert outer["truncated"] is False


@pytest.mark.asyncio
async def test_regime_conditional_sample_keeps_its_own_count():
    """The verified 19-day regime sample is untouched by the shared window."""
    result = await _three_sections()
    regime = result["full"]["regime"]
    conditional = regime["portfolio_in_current_regime"]["history_coverage"]
    assert conditional["covered_days"] == 19
    assert conditional["covered_days_scope"] == "conditional_regime_return_days"
    assert conditional["holding_window_days"] == result["regime"]["covered_days"]
    # Every copy of the holding window regime publishes says the same thing.
    assert regime["holding_context"]["intersection_start"] == result["regime"]["intersection_start"]
    assert _starts(regime["holding_context"]) == _starts(result["regime"])
    assert conditional["holding_context"]["covered_days"] == result["regime"]["covered_days"]
    assert _starts(conditional["holding_context"]) == _starts(result["regime"])
    # Ticket 07's regime metadata is preserved.
    for key in ("probability_unit", "benchmark", "posterior_type", "units"):
        assert key in regime


@pytest.mark.asyncio
async def test_tear_sheet_window_is_a_request_beside_a_measurement():
    """E-3: a 365-day label must never sit on 41 days of numbers unlabelled."""
    result = await _three_sections()
    dates = result["dates"]
    sheet = result["full"]["tear_sheet"]
    coverage = result["tear_sheet"]
    assert sheet["window"] == {
        "start": "2025-09-26", "end": result["today"],
        "kind": "requested_analytics_window",
    }
    assert sheet["requested_window"] == {"start": "2025-09-26", "end": result["today"]}
    measured = sheet["measured_window"]
    assert measured["observation_count"] == coverage["covered_days"]
    assert measured["days"] == coverage["covered_days"]
    # XS-001: the measured window is a SUB-window of the holding window, so it
    # no longer borrows the holding-window unit label. The two counts are still
    # the same number on this dense fixture; what changed is that a reader can
    # now tell the measured complete-coverage rows from the holding window's
    # aligned rows, instead of being handed one label for two populations.
    assert measured["covered_days_scope"] == MEASURED_WINDOW_COVERED_DAYS_SCOPE
    assert measured["covered_days_scope"] != coverage["covered_days_scope"]
    assert coverage["covered_days_scope"] == HOLDING_COVERED_DAYS_SCOPE
    assert measured["truncated_to_holding_window"] is True
    assert measured["holding_window_start"] == coverage["intersection_start"]
    assert measured["end"] == str(dates[-1].date())
    assert measured["start"] > sheet["window"]["start"]
    assert sheet["observation_count"] == coverage["covered_days"]
    assert sheet["annualized"] is coverage["annualized"]


@pytest.mark.asyncio
async def test_tear_sheet_full_history_carries_its_own_evidence():
    """E-3: the hypothetical leg is a separate windowed object, as elsewhere."""
    result = await _three_sections()
    sheet = result["full"]["tear_sheet"]
    full = sheet["full_history"]
    assert full["basis"] == analytics_mod.FULL_HISTORY_BASIS
    assert full["scope"] == "full_exchange_history"
    assert full["truncated_to_holding_window"] is False
    assert full["observation_count"] > 0
    assert full["window"]["start"] and full["window"]["end"]
    assert full["first_observation"] == full["window"]["start"]
    assert full["last_observation"] == full["window"]["end"]
    assert full["requested_window"] == sheet["requested_window"]
    assert full["minimum_observations_required"] == analytics_mod.MIN_ANNUALIZE_DAYS
    # The existing keys survive beside the new evidence block.
    assert full["metrics"]["days"] == full["observation_count"]
    assert "universe_coverage" in full and "relative_vs_nifty" in full and "start" in full
    # A hypothetical leg that spans far more than the holding window, and is
    # never described as the holding window.
    assert full["observation_count"] > result["tear_sheet"]["covered_days"] * 2
    assert full["window"]["start"] < result["tear_sheet"]["intersection_start"]
