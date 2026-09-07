"""
Regression tests for the shared-AsyncSession race in concurrent batch fetching
(DSP-08 / QH-06 follow-up).

Before the fix, `fetch_ohlcv_batch` ran 5 concurrent workers that all issued
commits/rollbacks on ONE AsyncSession, producing bursts of
"commit() can't be called here" / "transaction is closed" errors on every
portfolio refresh (145 failed stores in one 20s burst on 2026-09-06).

The fix serializes DB operations through an instance-level asyncio gate
(`DataService._db_lock`) while keeping the network fetches parallel.

These tests use a session proxy that counts in-flight DB operations: any
overlap = violation. With a sleep inside each op, the pre-fix code violates
deterministically; the fixed code must show zero violations.
"""

import asyncio
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.database import StockTimeseries
from app.services.data_service import DataService
from app.services.source_preference_service import set_primary_source


def _vendor_df(ticker: str, days: int = 5) -> pd.DataFrame:
    """Raw vendor-style frame ('Date'-named index, TitleCase columns).

    Values are numpy arrays on purpose: pd.Series values would be aligned
    against the DatetimeIndex by the DataFrame constructor and become all-NaN.
    """
    dates = pd.date_range("2025-01-01", periods=days, freq="B")
    close = np.linspace(100.0, 104.0, days)
    df = pd.DataFrame(
        {
            "Open": close * 0.99,
            "High": close * 1.01,
            "Low": close * 0.98,
            "Close": close,
            "Adj Close": close,
            "Volume": np.full(days, 1000),
        },
        index=dates,
    )
    df.index.name = "Date"
    return df


class OverlapGuardSession:
    """Proxy around an AsyncSession that flags overlapping DB operations."""

    def __init__(self, inner: AsyncSession):
        self._inner = inner
        self.active = 0
        self.max_active = 0
        self.violations = 0
        self.execute_calls = 0
        self.commit_calls = 0

    async def _enter(self):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.active > 1:
            self.violations += 1
        # Widen the interleaving window so a missing gate fails reliably
        await asyncio.sleep(0.005)

    async def _exit(self):
        self.active -= 1

    async def execute(self, *args, **kwargs):
        await self._enter()
        try:
            self.execute_calls += 1
            return await self._inner.execute(*args, **kwargs)
        finally:
            await self._exit()

    async def commit(self, *args, **kwargs):
        await self._enter()
        try:
            self.commit_calls += 1
            return await self._inner.commit(*args, **kwargs)
        finally:
            await self._exit()

    async def rollback(self, *args, **kwargs):
        await self._enter()
        try:
            return await self._inner.rollback(*args, **kwargs)
        finally:
            await self._exit()

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.mark.asyncio
class TestConcurrentBatchDbGate:
    async def test_batch_has_zero_db_overlap_and_stores_everything(self, test_db: AsyncSession):
        """10 tickers fetched concurrently through the REAL pipeline: no two
        DB operations may ever overlap on the shared session, and every
        ticker must land in the cache."""
        await set_primary_source(test_db, "yfinance")
        guard = OverlapGuardSession(test_db)
        service = DataService(guard)

        tickers = [f"BATCH{i:02d}.NS" for i in range(10)]

        def _yf_dl(*a, **k):
            return pd.DataFrame()  # yfinance (primary) yields nothing -> cascade

        bf_frames = {t: _vendor_df(t) for t in tickers}

        with patch("bfinance.download", Mock(side_effect=lambda ticker, **k: bf_frames[ticker])), \
             patch("app.services.data_service.yf.download", _yf_dl), \
             patch("app.services.data_service.get_alpha_vantage_service", return_value=Mock(enabled=False)):
            res = await service.fetch_ohlcv_batch(
                tickers,
                start_date="2025-01-01",
                end_date="2025-01-10",
                force_refresh=True,
            )

        assert res["failed_tickers"] == [], f"all tickers should succeed: {res['failed_tickers']}"
        assert len(res["data"]) == 10
        assert guard.violations == 0, (
            f"{guard.violations} overlapping DB ops (max_active={guard.max_active}) — "
            "the DB gate must serialize session access"
        )

        rows = (await test_db.execute(select(StockTimeseries))).scalars().all()
        stored = {r.ticker for r in rows}
        assert stored == set(tickers)
        assert all(r.source_used == "bfinance" for r in rows)  # cascade fallback recorded

    async def test_preference_read_once_per_batch(self, test_db: AsyncSession):
        """One batch = one preference read, and every worker gets the same
        cascade even if the setting would change mid-flight."""
        await set_primary_source(test_db, "bfinance")
        service = DataService(test_db)

        read_count = {"n": 0}

        async def counting_read(db):
            read_count["n"] += 1
            return "bfinance"

        captured = []

        async def spy_fetch(ticker, start, end, force_refresh=False, source_order=None):
            captured.append((ticker, source_order))
            return _vendor_df(ticker)

        with patch("app.services.data_service.get_primary_source", side_effect=counting_read), \
             patch.object(service, "fetch_historical_data", side_effect=spy_fetch):
            await service.fetch_ohlcv_batch(
                [f"ONCE{i}.NS" for i in range(6)],
                start_date="2025-01-01",
                end_date="2025-01-10",
                force_refresh=True,
            )

        assert read_count["n"] == 1, "batch must resolve the preference exactly once"
        assert len(captured) == 6
        assert all(order == ["bfinance", "yfinance"] for _, order in captured)

    async def test_concurrent_single_ticker_fetches_stay_isolated(self, test_db: AsyncSession):
        """Direct concurrent fetch_historical_data calls (no batch wrapper)
        share the service instance; the DB gate must still serialize them."""
        await set_primary_source(test_db, "yfinance")
        guard = OverlapGuardSession(test_db)
        service = DataService(guard)

        bf_frames = {f"PAR{i}.NS": _vendor_df(f"PAR{i}.NS") for i in range(8)}

        def _yf_dl(*a, **k):
            return pd.DataFrame()

        with patch("bfinance.download", Mock(side_effect=lambda ticker, **k: bf_frames[ticker])), \
             patch("app.services.data_service.yf.download", _yf_dl), \
             patch("app.services.data_service.get_alpha_vantage_service", return_value=Mock(enabled=False)):
            results = await asyncio.gather(*[
                service.fetch_historical_data(t, "2025-01-01", "2025-01-10", force_refresh=True)
                for t in bf_frames
            ])

        assert all(df is not None and not df.empty for df in results)
        assert guard.violations == 0, f"overlap detected (max_active={guard.max_active})"

        rows = (await test_db.execute(select(StockTimeseries))).scalars().all()
        assert {r.ticker for r in rows} == set(bf_frames)
