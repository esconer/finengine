"""Phases 3+4: full-history headlines from cache depth + summary instrument vol.

Seeded only; exercises the real AnalyticsEngine/quantstats paths so the
headline-vs-holding split matches production.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock

import numpy as np
import pandas as pd

from app.api.analytics import get_analytics_summary, get_tear_sheet
from app.models.database import PortfolioPosition
from app.services.analytics_engine import AnalyticsEngine


def _frame(days: int, end: str = "2026-09-07", seed: int = 11) -> pd.DataFrame:
    dates = pd.date_range(end=end, periods=days, freq="B")
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, days)))
    return pd.DataFrame({"date": dates, "adj_close": close, "volume": np.full(days, 1e6)})


def _bench(days: int = 300, end: str = "2026-09-07") -> pd.Series:
    rng = np.random.default_rng(4)
    return pd.Series(
        rng.normal(0.0005, 0.01, days),
        index=pd.date_range(end=end, periods=days, freq="B"),
    )


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


async def test_tearsheet_headline_from_cache_depth_not_intersection():
    """Staggered book: holding leg gates, full-history headline stays populated."""
    db = _mock_db([
        _pos("OLD.NS", datetime(2020, 1, 1)),
        _pos("NEW.NS", datetime(2026, 8, 4)),
    ])
    mock_ds = Mock()
    mock_ds.fetch_historical_data = AsyncMock(return_value=_frame(300))
    mock_ds.get_coverage = AsyncMock(return_value={
        "ticker": "X", "cached_start": "2024-08-12",
        "cached_end": "2026-09-07", "trading_days": 518,
    })
    mock_bench = Mock()
    mock_bench.get_returns = AsyncMock(return_value=_bench())
    res = await get_tear_sheet(
        tickers="OLD.NS,NEW.NS", start="2025-09-08", end="2026-09-07",
        db=db, data_service=mock_ds, benchmark=mock_bench,
    )
    # Holding-truthed leg gates on the ~25d intersection.
    assert res["metrics"]["cagr"] is None
    assert res["relative_vs_nifty"]["beta_vs_nifty"] is None
    assert res["history_coverage"]["intersection_start"] == "2026-08-04"
    # Full-history headline spans cache depth, disclosed in the payload.
    full = res["full_history"]["metrics"]
    assert full["cagr"] is not None
    assert full["days"] >= 290
    assert res["full_history"]["start"] < "2025-09-08"
    assert res["full_history"]["relative_vs_nifty"]["beta_vs_nifty"] is not None
    # The full-history build was issued at the cached depth, not the window.
    starts = [c.args[1] for c in mock_ds.fetch_historical_data.call_args_list]
    assert "2024-08-12" in starts


async def test_tearsheet_full_history_without_coverage_api():
    """DataService without get_coverage (older mock) falls back to the window."""
    db = _mock_db([_pos("OLD.NS", datetime(2020, 1, 1))])
    mock_ds = Mock(spec=["fetch_historical_data"])
    mock_ds.fetch_historical_data = AsyncMock(return_value=_frame(300))
    mock_bench = Mock()
    mock_bench.get_returns = AsyncMock(return_value=_bench())
    res = await get_tear_sheet(
        tickers="OLD.NS", start="2025-09-08", end="2026-09-07",
        db=db, data_service=mock_ds, benchmark=mock_bench,
    )
    assert res["full_history"]["metrics"]["days"] >= 290
    assert res["full_history"]["start"] is not None


async def test_summary_instrument_volatility_ungated_by_intersection():
    """Staggered book: realized vol gates, instrument vol stays populated."""
    db = _mock_db([
        _pos("OLD.NS", datetime(2020, 1, 1)),
        _pos("NEW.NS", datetime(2026, 8, 4)),
    ])
    mock_ds = Mock()
    mock_ds.fetch_historical_data = AsyncMock(return_value=_frame(300))
    res = await get_analytics_summary(
        db=db, data_service=mock_ds, analytics_engine=AnalyticsEngine(),
    )
    assert res["realized_volatility"] is None
    assert res["instrument_volatility"] is not None
    assert res["instrument_volatility_days"] >= 290
