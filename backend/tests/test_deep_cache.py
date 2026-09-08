"""Phase 1 deep-cache regressions (issue 14).

Vendor-max backfill on miss/stale (capped 10y back from `end`), union
accumulation via upsert, requested-slice serving from SQLite, ticker-keyed
L1 shared across windows, stale-tail refresh, and the get_coverage aggregate.

The vendor seam is mocked at _download_with_timeout (call-counted, no timing).
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import StockTimeseries
from app.services.data_service import DataService


@pytest.fixture(autouse=True)
def _clear_l1():
    """Class-level L1 must not leak across tests."""
    DataService._in_memory_df_cache.clear()
    yield
    DataService._in_memory_df_cache.clear()


def _raw_frame(dates, ticker="DEEP.NS", base=100.0):
    """Raw vendor-style frame (TitleCase columns, 'Date'-named DatetimeIndex)."""
    dates = pd.DatetimeIndex(dates)
    n = len(dates)
    close = base + np.arange(n, dtype=float)
    df = pd.DataFrame(
        {
            "Open": close - 1.0,
            "High": close + 1.0,
            "Low": close - 2.0,
            "Close": close,
            "Adj Close": close,
            "Volume": np.full(n, 100000),
        },
        index=dates,
    )
    df.index.name = "Date"
    return df


def _biz(start, end):
    return pd.date_range(start=start, end=end, freq="B")


class _VendorMax:
    """Download-seam double: always returns the full-depth frame, counts calls."""

    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    async def __call__(self, ticker, start, end, source_order=None):
        self.calls.append((ticker, start, end))
        return self.frame


@pytest.mark.asyncio
class TestVendorMaxBackfill:
    async def test_miss_downloads_deep_window_once(self, test_db: AsyncSession):
        """Cold fetch of a narrow window downloads [end-10y, end], not [start, end]."""
        service = DataService(test_db)
        full = _raw_frame(_biz("2024-01-01", "2024-06-28"))
        vendor = _VendorMax(full)

        with patch.object(service, "_download_with_timeout", new=vendor):
            df = await service.fetch_historical_data("DEEP.NS", "2024-06-01", "2024-06-28")

        assert len(vendor.calls) == 1
        _, dl_start, dl_end = vendor.calls[0]
        assert dl_start == "2014-06-28", f"10y floor expected, got {dl_start}"
        assert dl_end == "2024-06-28"
        # Served slice is the requested window, not the max frame
        assert len(df) < len(full)
        assert pd.to_datetime(df["date"]).min() >= pd.to_datetime("2024-06-01")
        assert pd.to_datetime(df["date"]).max() <= pd.to_datetime("2024-06-28")

    async def test_deep_start_never_shrinks_wider_request(self):
        assert DataService._deep_start("2000-01-01", "2024-06-28") == "2000-01-01"
        assert DataService._deep_start("2024-06-01", "2024-06-28") == "2014-06-28"

    async def test_union_accumulates_across_windows_single_download(
        self, test_db: AsyncSession
    ):
        """Two disjoint windows, L1 cleared between: one download, DB holds union."""
        service = DataService(test_db)
        full = _raw_frame(_biz("2024-01-01", "2024-03-29"))
        vendor = _VendorMax(full)

        with patch.object(service, "_download_with_timeout", new=vendor):
            a = await service.fetch_historical_data("DEEPUN.NS", "2024-01-01", "2024-01-31")
            DataService._in_memory_df_cache.clear()
            b = await service.fetch_historical_data("DEEPUN.NS", "2024-03-01", "2024-03-29")

        assert len(vendor.calls) == 1, "second window must come from DB, not vendor"
        assert (pd.to_datetime(a["date"]).dt.strftime("%Y-%m") == "2024-01").all()
        assert (pd.to_datetime(b["date"]).dt.strftime("%Y-%m") == "2024-03").all()
        rows = (
            (await test_db.execute(select(StockTimeseries).where(StockTimeseries.ticker == "DEEPUN.NS")))
            .scalars()
            .all()
        )
        assert len(rows) == len(full), "union of max frame must be stored"

    async def test_no_duplicate_rows_on_refetch(self, test_db: AsyncSession):
        """force_refresh re-download upserts in place: row count never grows."""
        service = DataService(test_db)
        full = _raw_frame(_biz("2024-01-01", "2024-02-29"))
        vendor = _VendorMax(full)

        async def _count():
            return (
                (
                    await test_db.execute(
                        select(StockTimeseries).where(StockTimeseries.ticker == "DEEPDUP.NS")
                    )
                )
                .scalars()
                .all()
            ).__len__()

        with patch.object(service, "_download_with_timeout", new=vendor):
            await service.fetch_historical_data("DEEPDUP.NS", "2024-01-01", "2024-02-29")
            n1 = await _count()
            await service.fetch_historical_data(
                "DEEPDUP.NS", "2024-01-01", "2024-02-29", force_refresh=True
            )
            n2 = await _count()

        assert n1 == len(full) and n2 == n1


@pytest.mark.asyncio
class TestL1TickerKeyed:
    async def test_unrelated_windows_share_one_l1_entry(self, test_db: AsyncSession):
        service = DataService(test_db)
        full = _raw_frame(_biz("2024-01-01", "2024-03-29"))
        vendor = _VendorMax(full)

        with patch.object(service, "_download_with_timeout", new=vendor):
            a = await service.fetch_historical_data("DEEPWIN.NS", "2024-01-01", "2024-01-31")
            b = await service.fetch_historical_data("DEEPWIN.NS", "2024-03-01", "2024-03-29")

        assert len(vendor.calls) == 1, "second window must be sliced from L1"
        assert list(DataService._in_memory_df_cache.keys()) == ["DEEPWIN.NS"]
        assert (pd.to_datetime(a["date"]).dt.strftime("%Y-%m") == "2024-01").all()
        assert (pd.to_datetime(b["date"]).dt.strftime("%Y-%m") == "2024-03").all()
        assert len(b) == len(_biz("2024-03-01", "2024-03-29"))

    async def test_l1_miss_outside_depth_falls_through_correctly(
        self, test_db: AsyncSession
    ):
        """A window outside L1 depth must not return a wrong slice (DB/vendor path)."""
        service = DataService(test_db)
        full = _raw_frame(_biz("2024-01-01", "2024-01-31"))
        vendor = _VendorMax(full)

        with patch.object(service, "_download_with_timeout", new=vendor):
            # NOTE: window end sits past the last trading day on purpose: the
            # SQLite `date <= end` string comparison is end-exclusive at
            # midnight (pre-existing _get_cached_data behavior, untouched).
            a = await service.fetch_historical_data("DEEPOUT.NS", "2024-01-01", "2024-02-02")
            # Window entirely outside cached depth: vendor seam would need a hit,
            # but the mock only knows January -> falls back to empty slice, never
            # January rows mislabeled as February.
            b = await service.fetch_historical_data("DEEPOUT.NS", "2024-02-01", "2024-02-29")

        assert len(a) == len(full)
        assert b.empty or pd.to_datetime(b["date"]).min() >= pd.to_datetime("2024-02-01")


@pytest.mark.asyncio
class TestStaleTail:
    async def _seed_tail(self, service, test_db, ticker, end_today, seed_end_days_ago=10):
        end = pd.to_datetime(end_today)
        seed_dates = _biz((end - timedelta(days=60)).strftime("%Y-%m-%d"),
                          (end - timedelta(days=seed_end_days_ago)).strftime("%Y-%m-%d"))
        await service._store_timeseries_data(
            ticker,
            pd.DataFrame(
                {
                    "date": seed_dates,
                    "open": 100.0, "high": 101.0, "low": 99.0,
                    "close": 100.0, "adj_close": 100.0,
                    "volume": 1000, "ticker": ticker,
                }
            ),
        )
        return seed_dates

    async def test_stale_tail_with_old_fetch_refreshes(self, test_db: AsyncSession):
        """Stale tail + fetched_on older than 1h -> exactly one vendor-max refresh."""
        service = DataService(test_db)
        today = datetime.utcnow().strftime("%Y-%m-%d")
        ticker = "DEEPSTALE.NS"
        end = pd.to_datetime(today)
        seed_dates = await self._seed_tail(service, test_db, ticker, today)
        await test_db.execute(
            update(StockTimeseries)
            .where(StockTimeseries.ticker == ticker)
            .values(fetched_on=datetime.utcnow() - timedelta(hours=2))
        )
        await test_db.commit()

        fresh = _raw_frame(_biz(seed_dates[0].strftime("%Y-%m-%d"), today))
        vendor = _VendorMax(fresh)
        start = (end - timedelta(days=30)).strftime("%Y-%m-%d")

        with patch.object(service, "_download_with_timeout", new=vendor):
            df = await service.fetch_historical_data(ticker, start, today)

        assert len(vendor.calls) == 1
        _, dl_start, _ = vendor.calls[0]
        assert dl_start == (end - pd.DateOffset(years=10)).strftime("%Y-%m-%d")
        assert pd.to_datetime(df["date"]).max() >= end - timedelta(days=3)

    async def test_stale_tail_with_recent_fetch_serves_db_no_download(
        self, test_db: AsyncSession
    ):
        """Stale tail + fetched_on within 1h -> DB serves, vendor untouched (>60d
        recent-fetch path keeps working with deep cache: no hourly re-download)."""
        service = DataService(test_db)
        today = datetime.utcnow().strftime("%Y-%m-%d")
        ticker = "DEEPFRESH.NS"
        await self._seed_tail(service, test_db, ticker, today)
        vendor = _VendorMax(_raw_frame(_biz("2020-01-01", today)))
        start = (pd.to_datetime(today) - timedelta(days=30)).strftime("%Y-%m-%d")

        with patch.object(service, "_download_with_timeout", new=vendor):
            df = await service.fetch_historical_data(ticker, start, today)

        assert vendor.calls == []
        assert df is not None and not df.empty


@pytest.mark.asyncio
class TestGetCoverage:
    async def test_coverage_reports_min_max_count(self, test_db: AsyncSession):
        service = DataService(test_db)
        dates = _biz("2024-01-01", "2024-01-31")
        await service._store_timeseries_data(
            "DEEPCOV.NS",
            pd.DataFrame(
                {
                    "date": dates,
                    "open": 100.0, "high": 101.0, "low": 99.0,
                    "close": 100.0, "adj_close": 100.0,
                    "volume": 1000, "ticker": "DEEPCOV.NS",
                }
            ),
        )
        cov = await service.get_coverage("DEEPCOV.NS")
        assert cov["ticker"] == "DEEPCOV.NS"
        assert cov["cached_start"] == "2024-01-01"
        assert cov["cached_end"] == "2024-01-31"
        assert cov["trading_days"] == len(dates)

    async def test_coverage_empty_ticker(self, test_db: AsyncSession):
        service = DataService(test_db)
        cov = await service.get_coverage("NODATAXYZ.NS")
        assert cov == {
            "ticker": "NODATAXYZ.NS",
            "cached_start": None,
            "cached_end": None,
            "trading_days": 0,
        }
