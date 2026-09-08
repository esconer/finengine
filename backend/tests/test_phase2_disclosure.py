"""Phase 2 truthful disclosure: intersection-based coverage + 3-case warnings.

Seeded only; exercises the real AnalyticsEngine on synthetic frames so the
masked/intersection path matches production (masking logic itself untouched).
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock

import numpy as np
import pandas as pd

from app.api.analytics import get_realized_risk
from app.models.database import PortfolioPosition
from app.services.analytics_engine import AnalyticsEngine
from app.utils.holdings import holding_coverage


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
        db=db, data_service=mock_ds, cache_service=Mock(),
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
        db=db, data_service=mock_ds, cache_service=Mock(),
        analytics_engine=AnalyticsEngine(),
    )
    cov = res["history_coverage"]
    assert cov["tickers"]["SHORT.NS"]["raw_days"] == 10
    by_ticker = {w["ticker"]: w["message"] for w in res["warnings"]}
    assert "SHORT.NS" in by_ticker
    assert "exchange feeds" in by_ticker["SHORT.NS"]
    assert "realized P&L covers" not in by_ticker["SHORT.NS"]
