"""P0-8 contract tests: analytics cache upsert on (ticker, metric).

Regression gate for BACKEND_REVIEW P0-8 (blind insert created duplicate
rows; get_cached_analytics' scalar_one_or_none then raised
MultipleResultsFound, caught -> perpetual miss). Isolated in-memory DB.
"""

from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.database import AnalyticsCache
from app.services.cache_service import CacheService


async def _count(test_db, ticker, metric):
    q = select(func.count()).select_from(AnalyticsCache).where(
        AnalyticsCache.ticker == ticker, AnalyticsCache.metric_name == metric
    )
    return (await test_db.execute(q)).scalar()


async def test_repeated_set_keeps_single_row_and_latest_value(test_db):
    svc = CacheService(test_db)
    await svc.set_cached_analytics("RELIANCE", "sharpe", 1.0, datetime(2026, 1, 1), {"v": 1})
    await svc.set_cached_analytics("RELIANCE", "sharpe", 2.0, datetime(2026, 1, 2), {"v": 2})
    await svc.set_cached_analytics("RELIANCE", "sharpe", 3.0, datetime(2026, 1, 3), {"v": 3})
    assert await _count(test_db, "RELIANCE", "sharpe") == 1
    got = await svc.get_cached_analytics("RELIANCE", "sharpe")
    assert got is not None
    assert got["value"] == 3.0
    assert got["model_params"] == {"v": 3}


async def test_preexisting_duplicate_insert_raises(test_db):
    test_db.add(
        AnalyticsCache(
            ticker="INFY", metric_name="sharpe", metric_value=1.0,
            calculation_date=datetime(2026, 1, 1),
            expires_at=datetime(2030, 1, 1), model_params={},
        )
    )
    await test_db.commit()
    test_db.add(
        AnalyticsCache(
            ticker="INFY", metric_name="sharpe", metric_value=9.0,
            calculation_date=datetime(2026, 1, 1),
            expires_at=datetime(2030, 1, 1), model_params={},
        )
    )
    with pytest.raises(IntegrityError):
        await test_db.commit()
    await test_db.rollback()


async def test_distinct_keys_coexist(test_db):
    svc = CacheService(test_db)
    await svc.set_cached_analytics("A", "m1", 1.0, datetime(2026, 1, 1), {})
    await svc.set_cached_analytics("A", "m2", 2.0, datetime(2026, 1, 1), {})
    await svc.set_cached_analytics("B", "m1", 3.0, datetime(2026, 1, 1), {})
    assert (await svc.get_cached_analytics("A", "m1"))["value"] == 1.0
    assert (await svc.get_cached_analytics("A", "m2"))["value"] == 2.0
    assert (await svc.get_cached_analytics("B", "m1"))["value"] == 3.0
