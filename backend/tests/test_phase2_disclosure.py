"""Phase 2 truthful disclosure: intersection-based coverage + 3-case warnings.

Seeded only; exercises the real AnalyticsEngine on synthetic frames so the
masked/intersection path matches production (masking logic itself untouched).

V3-06 addition: a window start is only ever published with its provenance
(stored `added_on` vs buy-price-inferred vs unknown) and a position's
limited-history status comes from that position's OWN return observations.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock

import numpy as np
import pandas as pd

from app.api.analytics import get_realized_risk
from app.models.database import PortfolioPosition
from app.services.analytics_engine import AnalyticsEngine
from app.utils.holdings import (
    analytics_start_claim,
    annualizable,
    effective_start_detail,
    effective_starts,
    holding_coverage,
    position_history_note,
    position_limited_history,
)


def _frame(days: int, end: str = "2026-09-07", seed: int = 11) -> pd.DataFrame:
    dates = pd.date_range(end=end, periods=days, freq="B")
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, days)))
    return pd.DataFrame({"date": dates, "adj_close": close, "volume": np.full(days, 1e6)})


def _mock_db(positions):
    mock_db = AsyncMock()
    scalars = MagicMock()
    scalars.all.return_value = positions
    res = MagicMock()
    res.scalars.return_value = scalars
    mock_db.execute = AsyncMock(return_value=res)
    return mock_db


def _pos(ticker, added_on, seed_mv=10000.0):
    return PortfolioPosition(
        id=1, ticker=ticker, weight=0.5, quantity=10.0, buy_price=None,
        last_price=100.0, market_value=seed_mv, region="IN",
        sector="X", industry="Y", added_on=added_on,
    )


def test_coverage_truncated_on_intersection_not_oldest():
    # Oldest holding predates the request but the newest (intersection) does
    # not: realized history for the current composition is still truncated.
    cov = holding_coverage(
        {"OLD.NS": "2024-01-01", "NEW.NS": "2026-08-04"},
        "2025-01-01", "2026-09-07", 25,
        {"OLD.NS": {"raw_days": 300, "masked_days": 25},
         "NEW.NS": {"raw_days": 300, "masked_days": 25}},
    )
    assert cov["truncated"] is True
    assert cov["intersection_start"] == "2026-08-04"
    assert cov["effective_start"] == "2026-08-04"
    assert cov["oldest_holding"] == "2024-01-01"
    assert cov["tickers"]["OLD.NS"] == {
        "effective_start": "2024-01-01", "raw_days": 300, "masked_days": 25,
    }
    assert cov["tickers"]["NEW.NS"]["effective_start"] == "2026-08-04"


def test_coverage_backward_compat_without_per_ticker():
    cov = holding_coverage({"A": "2026-08-27"}, "2025-09-03", "2026-09-03", 7)
    assert cov["truncated"] is True
    assert cov["intersection_start"] == "2026-08-27"
    assert cov["tickers"]["A"] == {
        "effective_start": "2026-08-27", "raw_days": None, "masked_days": None,
    }
    cov2 = holding_coverage({"A": "2020-01-01"}, "2025-09-03", "2026-09-03", 300)
    assert cov2["truncated"] is False and cov2["annualized"] is True


async def test_realized_risk_case_a_intersection_copy():
    db = _mock_db([
        _pos("OLD.NS", datetime(2020, 1, 1)),
        _pos("NEW.NS", datetime(2026, 8, 4)),
    ])
    long_frame = _frame(300)
    mock_ds = Mock()
    mock_ds.fetch_historical_data = AsyncMock(return_value=long_frame)
    res = await get_realized_risk(
        tickers="OLD.NS,NEW.NS", start="2025-01-01", end="2026-09-07",
        db=db, data_service=mock_ds,
        analytics_engine=AnalyticsEngine(),
    )
    cov = res["history_coverage"]
    assert cov["truncated"] is True
    assert cov["intersection_start"] == "2026-08-04"
    assert cov["tickers"]["OLD.NS"]["raw_days"] == 300
    assert cov["tickers"]["OLD.NS"]["masked_days"] == cov["covered_days"]
    assert cov["tickers"]["OLD.NS"]["masked_days"] < 300
    assert cov["full_history_days"] == 300
    by_ticker = {w["ticker"]: w["message"] for w in res["warnings"]}
    old_msg = by_ticker["OLD.NS"]
    assert "realized P&L covers" in old_msg
    assert "2026-08-04" in old_msg
    assert "held since 2020-01-01" in old_msg
    assert "instrument risk uses full" in old_msg
    assert "exchange feeds" not in old_msg


async def test_realized_risk_case_b_short_feed_copy():
    db = _mock_db([_pos("SHORT.NS", datetime(2020, 1, 1))])
    mock_ds = Mock()
    mock_ds.fetch_historical_data = AsyncMock(return_value=_frame(10, seed=23))
    res = await get_realized_risk(
        tickers="SHORT.NS", start="2025-01-01", end="2026-09-07",
        db=db, data_service=mock_ds,
        analytics_engine=AnalyticsEngine(),
    )
    cov = res["history_coverage"]
    assert cov["tickers"]["SHORT.NS"]["raw_days"] == 10
    by_ticker = {w["ticker"]: w["message"] for w in res["warnings"]}
    assert "SHORT.NS" in by_ticker
    assert "exchange feeds" in by_ticker["SHORT.NS"]
    assert "realized P&L covers" not in by_ticker["SHORT.NS"]


# --- V3-06: provenance + own-observation history semantics -------------------


def _ladder(periods: int = 200):
    dates = pd.date_range("2025-01-01", periods=periods, freq="B")
    return dates, pd.Series(100 + np.arange(periods) * 1.0, index=dates)


def test_buy_price_predating_import_stays_inferred_not_stored():
    """Imported holding whose buy price predates added_on: the repaired start is
    preserved, but it is never reported as a stored holding date."""
    dates, close = _ladder()
    holdings = {
        "NIFTYIETF.NS": {"added_on": "2025-12-01", "buy_price": 200.0},
        "OLD.NS": {"added_on": "2025-12-01", "buy_price": None},
        "ADHOC.NS": {"added_on": None, "buy_price": None},
    }
    frames = {"NIFTYIETF.NS": close, "OLD.NS": close}
    detail = effective_start_detail(holdings, frames)

    etf = detail["NIFTYIETF.NS"]
    assert etf["analytics_start"] == str(dates[104].date())  # repair preserved
    assert etf["analytics_start_source"] == "buy_price_inferred"
    assert etf["stored_added_on"] == "2025-12-01"           # never overwritten
    assert etf["buy_price_inferred"] == etf["analytics_start"]

    assert detail["OLD.NS"]["analytics_start_source"] == "stored_added_on"
    assert detail["ADHOC.NS"]["analytics_start"] is None
    assert detail["ADHOC.NS"]["analytics_start_source"] == "unknown"

    # Date-only helper is unchanged: still the earliest known start.
    starts = effective_starts(holdings, frames)
    assert starts["NIFTYIETF.NS"] == etf["analytics_start"]
    assert starts["ADHOC.NS"] is None


def test_coverage_provenance_is_additive_and_own_observation_limited():
    """A late-listed leg keeps its own limited-history status even when the
    portfolio itself has a long measured history."""
    _, close = _ladder()
    holdings = {
        "NIFTYIETF.NS": {"added_on": "2025-12-01", "buy_price": 200.0},
        "OLD.NS": {"added_on": "2025-06-02", "buy_price": None},
    }
    detail = effective_start_detail(holdings, {"NIFTYIETF.NS": close, "OLD.NS": close})
    cov = holding_coverage(
        effective_starts(holdings, {"NIFTYIETF.NS": close, "OLD.NS": close}),
        "2025-01-01", "2026-09-07", 176,                 # portfolio: long history
        {
            "NIFTYIETF.NS": {"raw_days": 21, "masked_days": 21, "return_observations": 20},
            "OLD.NS": {"raw_days": 300, "masked_days": 176, "return_observations": 175},
        },
        detail,
    )

    etf = cov["tickers"]["NIFTYIETF.NS"]
    assert etf["return_observations"] == 20
    assert etf["limited_history"] is True      # own 20 observations, not 176
    assert etf["analytics_start_source"] == "buy_price_inferred"
    assert etf["stored_added_on"] == "2025-12-01"
    assert cov["tickers"]["OLD.NS"]["limited_history"] is False
    assert cov["annualized"] is True            # portfolio-level gate is separate
    # The intersection is the NEWEST start (OLD.NS 2025-06-02, a stored date),
    # so the window itself is stored-anchored even though one leg is inferred.
    assert cov["intersection_start"] == "2025-06-02"
    assert cov["effective_start_source"] == "stored_added_on"
    assert cov["inferred_start_tickers"] == ["NIFTYIETF.NS"]


def test_inferred_start_that_is_the_newest_drives_the_window_source():
    """No stored import date at all: the buy-price match IS the window start and
    the payload must say so instead of implying a holding date."""
    _, close = _ladder()
    holdings = {
        "NOBUY.NS": {"added_on": None, "buy_price": 290.0},
        "OLD.NS": {"added_on": "2025-06-02", "buy_price": None},
    }
    frames = {"NOBUY.NS": close, "OLD.NS": close}
    cov = holding_coverage(
        effective_starts(holdings, frames),
        "2025-01-01", "2026-09-07", 40,
        {"NOBUY.NS": {"raw_days": 300, "masked_days": 40, "return_observations": 39}},
        effective_start_detail(holdings, frames),
    )
    assert cov["tickers"]["NOBUY.NS"]["stored_added_on"] is None
    assert cov["intersection_start"] == cov["tickers"]["NOBUY.NS"]["analytics_start"]
    assert cov["effective_start_source"] == "buy_price_inferred"
    assert cov["inferred_start_tickers"] == ["NOBUY.NS"]


def test_coverage_without_provenance_keeps_legacy_entries():
    """Provenance is additive: no provenance map means the documented shape."""
    cov = holding_coverage({"A": "2026-08-27"}, "2025-09-03", "2026-09-03", 7)
    assert cov["tickers"]["A"] == {
        "effective_start": "2026-08-27", "raw_days": None, "masked_days": None,
    }
    assert "effective_start_source" not in cov
    assert "inferred_start_tickers" not in cov


def test_own_observation_gates_ignore_portfolio_and_global_counts():
    assert position_limited_history(20) is True
    assert position_limited_history(30) is False
    # A late-listing declaration still holds without a measured count…
    assert position_limited_history(None, declared_limited=True) is True
    # …and a measured count can never be overridden by a stale declaration.
    assert position_limited_history(175, declared_limited=False) is False
    assert annualizable(29) is False and annualizable(30) is True
    assert annualizable(None) is False


def test_history_copy_never_claims_an_unstored_holding_date():
    inferred = position_history_note(
        "NIFTYIETF.NS",
        return_observations=20,
        analytics_start="2026-05-19",
        analytics_start_source="buy_price_inferred",
        stored_added_on="2026-06-08",
        coverage_reason="accepted_late_listing",
        full_history_days=176,
    )
    assert "20 own return observations" in inferred
    assert "inferred from the buy price" in inferred
    assert "2026-06-08" in inferred              # the stored stamp is disclosed
    assert "held since" not in inferred
    # Full-history instrument metrics are named, but never as a longer window.
    assert "176 exchange days" in inferred
    assert "does not extend this holding window" in inferred

    stored = position_history_note(
        "OLD.NS",
        return_observations=175,
        analytics_start="2020-01-01",
        analytics_start_source="stored_added_on",
        stored_added_on="2020-01-01",
    )
    assert "held since 2020-01-01 (stored import date)" in stored
    assert "175 own return observations" in stored

    unknown = position_history_note("ADHOC.NS", return_observations=None)
    assert "own return observations were not measured" in unknown
    assert "holding start unknown" in unknown

    # A date with no declared provenance is never called a holding date.
    assert "provenance not reported" in analytics_start_claim("2026-08-04")
    assert analytics_start_claim(None) == "holding start unknown"
