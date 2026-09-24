"""
Benchmark index service - ingests and serves NIFTY 50 (^NSEI) returns.

The benchmark unlocks beta/alpha, R-squared, regime detection and honest
tear-sheet comparisons. Data flows through the existing DataService cache
(stock_timeseries table), so ^NSEI rows are fetched once per TTL window.
"""

from datetime import datetime, timedelta
import inspect
from typing import Optional

import pandas as pd

from app.services.data_service import DataService
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

BENCHMARK_SYMBOL = "^NSEI"  # NIFTY 50

# Close-price column candidates, in DataService (lowercase) and yfinance
# (Title-case) spellings — single source shared by frame and series readers.
_CLOSE_CANDIDATES = ("adj_close", "close", "Adj Close", "Close")


def _close_series(df: pd.DataFrame) -> Optional[pd.Series]:
    """Date-indexed close-price series from any DataService frame shape."""
    if df is None or df.empty:
        return None
    price_col = next((c for c in _CLOSE_CANDIDATES if c in df.columns), None)
    if price_col is None:
        return None
    values = df[price_col]
    for dcol in ("date", "Date"):
        if dcol in df.columns:
            idx = pd.to_datetime(df[dcol], errors="coerce")
            return pd.Series(values.values, index=idx, name=price_col).dropna()
    if isinstance(df.index, pd.DatetimeIndex):
        out = values.copy()
        out.index = pd.to_datetime(df.index)
        return out
    return None


class BenchmarkService:
    """Fetch/cache the NIFTY 50 index and expose daily returns."""

    def __init__(self, db_session):
        self.data_service = DataService(db_session)

    async def ensure_history(
        self,
        days: int = 756,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ):
        """Fetch ^NSEI through the shared cache for an explicit date window.

        ``start``/``end`` are part of the service contract so historical
        callers are not silently anchored to the server's current date.
        ``days`` remains the default-window convenience for existing callers.
        """
        end_dt = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now()
        start_dt = (
            datetime.strptime(start, "%Y-%m-%d")
            if start
            else end_dt - timedelta(days=int(days))
        )
        return await self.data_service.fetch_historical_data(
            BENCHMARK_SYMBOL,
            start_dt.strftime("%Y-%m-%d"),
            end_dt.strftime("%Y-%m-%d"),
        )

    async def get_benchmark_df(self, days: int = 1100) -> Optional[pd.DataFrame]:
        """Date-indexed OHLCV DataFrame of the benchmark."""
        df = await self.ensure_history(days=days)
        if df is None or df.empty:
            return None
        out = df.copy()
        for dcol in ("date", "Date"):
            if dcol in out.columns:
                out.index = pd.to_datetime(out[dcol], errors="coerce")
                break
        close_col = next((c for c in _CLOSE_CANDIDATES if c in out.columns), None)
        return out.dropna(subset=[close_col]) if close_col else out

    async def get_returns(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        days: int = 756,
    ) -> Optional[pd.Series]:
        """Daily simple returns of the benchmark, indexed by date.

        The fetch window is anchored to the requested ``end`` date, not to
        ``datetime.now()``.  This is essential for historical tear sheets and
        factor windows.
        """
        end_dt = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now()
        start_dt = (
            datetime.strptime(start, "%Y-%m-%d")
            if start
            else end_dt - timedelta(days=int(days))
        )
        start_text = start_dt.strftime("%Y-%m-%d")
        end_text = end_dt.strftime("%Y-%m-%d")
        span_days = max(0, (end_dt - start_dt).days)
        fetch_days = max(int(days), span_days)

        # Keep compatibility with lightweight test doubles/older subclasses
        # that expose the historical ``ensure_history(days=...)`` signature.
        try:
            parameters = inspect.signature(self.ensure_history).parameters
        except (TypeError, ValueError):
            parameters = {}
        accepts_explicit_window = (
            "start" in parameters
            or "end" in parameters
            or any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
        )
        if accepts_explicit_window:
            df = await self.ensure_history(
                days=fetch_days, start=start_text, end=end_text
            )
        else:
            df = await self.ensure_history(days=fetch_days)

        series = _close_series(df)
        if series is None:
            logger.warning("No benchmark data available for %s", BENCHMARK_SYMBOL)
            return None

        series = series.loc[
            (series.index >= pd.Timestamp(start_text))
            & (series.index <= pd.Timestamp(end_text))
        ]
        returns = series.pct_change(fill_method=None).dropna()
        returns.name = "benchmark"
        return returns if not returns.empty else None
