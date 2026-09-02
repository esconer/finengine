"""
Benchmark index service - ingests and serves NIFTY 50 (^NSEI) returns.

The benchmark unlocks beta/alpha, R-squared, regime detection and honest
tear-sheet comparisons. Data flows through the existing DataService cache
(stock_timeseries table), so ^NSEI rows are fetched once per TTL window.
"""

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from app.services.data_service import DataService
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

BENCHMARK_SYMBOL = "^NSEI"  # NIFTY 50


def _close_series(df: pd.DataFrame) -> Optional[pd.Series]:
    """Date-indexed close-price series from any DataService frame shape."""
    if df is None or df.empty:
        return None
    price_col = next(
        (c for c in ("adj_close", "close", "Adj Close", "Close") if c in df.columns),
        None,
    )
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

    async def ensure_history(self, days: int = 756):
        """Pull ~`days` calendar days of ^NSEI through the shared cache."""
        end = datetime.now()
        start = end - timedelta(days=days)
        return await self.data_service.fetch_historical_data(
            BENCHMARK_SYMBOL, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
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
        return out.dropna(subset=["close"] if "close" in out.columns else [])

    async def get_returns(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        days: int = 756,
    ) -> Optional[pd.Series]:
        """Daily simple returns of the benchmark, indexed by date."""
        if not end:
            end = datetime.now().strftime("%Y-%m-%d")
        if not start:
            start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        df = await self.ensure_history(days=days)
        series = _close_series(df)
        if series is None:
            logger.warning("No benchmark data available for %s", BENCHMARK_SYMBOL)
            return None

        series = series.loc[(series.index >= start) & (series.index <= end)]
        returns = series.pct_change().dropna()
        returns.name = "benchmark"
        return returns if not returns.empty else None


_service_registry: dict = {}


def get_benchmark_service(db_session) -> BenchmarkService:
    """Request-scoped instance keyed by session identity (DI-friendly)."""
    key = id(db_session)
    svc = _service_registry.get(key)
    if svc is None:
        svc = BenchmarkService(db_session)
        _service_registry[key] = svc
        # opportunistic cleanup so the registry cannot grow unbounded
        if len(_service_registry) > 64:
            for k in list(_service_registry.keys())[:-32]:
                _service_registry.pop(k, None)
    return svc
