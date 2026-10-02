"""
Regression tests for SESSION-SCOPED DB exclusion (SVC-3 / SVC-5).

`data_service.py` states the invariant in its own words: "SQLAlchemy sessions
are not concurrency-safe: parallel commits/rollbacks on one session collide."
Two services are handed the SAME `AsyncSession` by `get_db_session`
(`api/analytics.py:12095,12147,12252` build `IndiaDataService(db=db)` from the
session `api/portfolio.py:107` gives `DataService`).  An instance-level
`asyncio.Lock` therefore cannot exclude across them -- the gate has to hang off
the session.

Before the fix:
  * `DataService._store_timeseries_data` and `DataService.check_data_integrity`
    executed/committed with no gate at all (the Alpha Vantage path at
    `data_service.py:1339` calls the store helper directly, holding nothing);
  * `IndiaDataService` had zero gate sites -- 23 unguarded
    `db.execute`/`commit`/`rollback` calls.

The trace below records the real [enter, exit) window of every session
operation and reports any two that overlap, so a missing gate is shown as a
concrete interleaving (not merely "no exception was raised").
"""

import asyncio
from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import NSEBhavcopy, StockTimeseries
from app.services.data_service import DataService
from app.services.india_data_service import IndiaDataService


def _ohlcv_df(ticker: str = "RACE.NS", days: int = 3) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=days, freq="B")
    close = np.linspace(2500.0, 2510.0, days)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.99,
            "high": close * 1.01,
            "low": close * 0.98,
            "close": close,
            "adj_close": close,
            "volume": np.full(days, 100000),
            "ticker": ticker,
        }
    )


def _bhav(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "open": 800.0, "high": 815.0, "low": 795.0, "close": 810.0,
        "prev_close": 800.0, "avg_price": 805.0, "ttl_trd_qnty": 1000000,
        "turnover_lacs": 8050.0, "no_of_trades": 50000,
        "deliv_qty": 500000, "deliv_per": 50.0,
    }


async def _stored_rows(session: AsyncSession, ticker: str) -> list:
    rows = (await session.execute(
        select(StockTimeseries)
        .where(StockTimeseries.ticker == ticker)
        .order_by(StockTimeseries.date)
    )).scalars().all()
    return [
        (r.date, r.open, r.high, r.low, r.close, r.adj_close, r.volume, r.source_used)
        for r in rows
    ]


async def _acquire(lock) -> None:
    async with lock:
        await asyncio.sleep(0)


class TracingSession:
    """AsyncSession proxy recording the [enter, exit) window of every DB call.

    ``overlaps`` holds every pair of operations that were in flight at the same
    time on the same session.  Two overlapping operations on one AsyncSession
    means two coroutines were inside its transaction state simultaneously --
    the exact defect the gate exists to prevent.
    """

    OPERATIONS = ("execute", "commit", "rollback", "flush", "refresh")

    def __init__(self, inner: AsyncSession, yields: int = 2):
        self._inner = inner
        self._yields = yields
        self.trace: list = []
        self.overlaps: list = []
        self._in_flight: list = []

    async def _enter(self, label: str, task_id: int) -> None:
        if self._in_flight:
            self.overlaps.append((tuple(self._in_flight), (task_id, label)))
        self._in_flight.append(label)
        self.trace.append((task_id, "enter", label))
        # Widen each window so a missing gate interleaves deterministically
        # instead of depending on the scheduler's good mood.
        for _ in range(self._yields):
            await asyncio.sleep(0)

    async def _exit(self, label: str, task_id: int) -> None:
        self.trace.append((task_id, "exit", label))
        self._in_flight.remove(label)
        await asyncio.sleep(0)

    def __getattr__(self, name):
        if name in TracingSession.OPERATIONS:
            async def _traced(*args, **kwargs):
                task_id = id(asyncio.current_task())
                await self._enter(name, task_id)
                try:
                    return await getattr(self._inner, name)(*args, **kwargs)
                finally:
                    await self._exit(name, task_id)

            return _traced
        return getattr(self._inner, name)

    @property
    def task_ids(self) -> set:
        return {task_id for task_id, _, _ in self.trace}

    def render(self, limit: int = 24) -> str:
        rows = [f"  task{tid} {kind:5s} {label}" for tid, kind, label in self.trace[:limit]]
        rows.append(f"  ... {len(self.trace)} events, {len(self.overlaps)} overlaps")
        return "\n".join(rows)


@pytest.mark.asyncio
class TestSessionScopedDbGate:
    async def test_store_and_india_write_on_one_session_never_interleave(self, test_db: AsyncSession):
        """RED PROOF.  Two services, one AsyncSession, two concurrent writers.

        Pre-fix this records concrete interleaved execute/commit pairs: the
        store helper held no gate and IndiaDataService had none at all.  The
        gate must now serialize them, and both writes must survive.
        """
        trace = TracingSession(test_db)
        data = DataService(trace)
        india = IndiaDataService(trace)

        stored, applied = await asyncio.gather(
            data._store_timeseries_data("RACE.NS", _ohlcv_df("RACE.NS")),
            india.ingest_bhavcopy_records([_bhav("RACE")], datetime(2025, 1, 1)),
        )

        # Not vacuous: BOTH services really did drive the shared session.
        assert len(trace.task_ids) == 2, (
            "the test never exercised two coroutines on one session:\n" + trace.render()
        )
        assert len(trace.trace) >= 4, trace.render()
        assert trace.overlaps == [], (
            f"{len(trace.overlaps)} overlapping session operations across two "
            f"services on ONE AsyncSession:\n{trace.render()}\n"
            f"first overlaps: {trace.overlaps[:3]}"
        )

        # And nothing was lost: both writers committed.
        assert stored is True
        assert applied == 1
        assert await _stored_rows(test_db, "RACE.NS")
        assert (await test_db.execute(
            select(NSEBhavcopy).where(NSEBhavcopy.symbol == "RACE")
        )).scalars().all()

    async def test_integrity_check_does_not_race_an_india_write(self, test_db: AsyncSession):
        """`check_data_integrity` runs three un-gated reads; a concurrent
        bhavcopy upsert must not be able to sit inside one of them."""
        trace = TracingSession(test_db)
        data = DataService(trace)
        india = IndiaDataService(trace)

        report, applied = await asyncio.gather(
            data.check_data_integrity(ticker="RACE.NS"),
            india.ingest_bhavcopy_records([_bhav("INTEG")], datetime(2025, 1, 2)),
        )

        assert len(trace.task_ids) == 2
        assert trace.overlaps == [], (
            f"{len(trace.overlaps)} overlapping session operations:\n{trace.render()}"
        )
        assert applied == 1
        assert report["ticker"] == "RACE.NS"

    async def test_both_india_writes_and_reads_are_gated(self, test_db: AsyncSession):
        """Every IndiaDataService DB method resolves the same session gate."""
        trace = TracingSession(test_db)
        data = DataService(trace)
        india = IndiaDataService(trace)
        day = datetime(2025, 1, 3)

        await india.ingest_institutional_flow(day, "FII", 100.0, 40.0)
        await asyncio.gather(
            india.ingest_bhavcopy_records([_bhav("GATED")], day),
            india.ingest_institutional_flow(day, "DII", 10.0, 5.0),
            india.get_institutional_flows(lookback_days=5),
            india.get_delivery_anomalies(["GATED"]),
            data.check_data_integrity(),
        )

        assert len(trace.task_ids) >= 2
        assert trace.overlaps == [], (
            f"{len(trace.overlaps)} overlapping session operations:\n{trace.render()}"
        )

    async def test_gate_identity_is_per_session_not_per_service(self, test_db: AsyncSession):
        """The whole point: two service instances on ONE session share ONE
        gate; two different sessions must not share one."""
        trace = TracingSession(test_db)
        assert DataService(trace)._db_lock is IndiaDataService(trace)._db_lock
        assert DataService(trace)._db_lock is IndiaDataService(trace)._db_lock

        other = AsyncSession()
        try:
            assert DataService(other)._db_lock is not DataService(trace)._db_lock
        finally:
            await other.close()

    async def test_gate_is_reentrant_for_already_locked_callers(self, test_db: AsyncSession):
        """`fetch_historical_data` holds the gate at data_service.py:704 and
        :771 BEFORE calling `_store_timeseries_data`.  A naive `async with`
        inside the helper would deadlock; `wait_for` turns that hang into a
        failure instead of a wedged suite."""
        data = DataService(test_db)
        stored = None
        applied = None
        async with data._db_lock:
            stored = await asyncio.wait_for(
                data._store_timeseries_data("NEST.NS", _ohlcv_df("NEST.NS")), timeout=5
            )
            report = await asyncio.wait_for(
                data.check_data_integrity(ticker="NEST.NS"), timeout=5
            )
            # A different service, holding the same gate, on the same session.
            applied = await asyncio.wait_for(
                IndiaDataService(test_db).ingest_bhavcopy_records(
                    [_bhav("NEST")], datetime(2025, 1, 4)
                ),
                timeout=5,
            )
        assert stored is True
        assert report["ticker"] == "NEST.NS"
        assert applied == 1

    async def test_timeout_harness_would_catch_a_non_reentrant_gate(self):
        """Negative control for the re-entrancy test above: the same nesting
        shape against a plain asyncio.Lock really does hang, so a passing
        `wait_for` there is evidence and not an accident."""
        plain = asyncio.Lock()
        async with plain:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(_acquire(plain), timeout=0.2)

    async def test_gate_releases_on_exception(self, test_db: AsyncSession):
        """A raising body must not leave the shared session gate held."""
        trace = TracingSession(test_db)
        data = DataService(trace)
        with pytest.raises(RuntimeError):
            async with data._db_lock:
                raise RuntimeError("boom")
        assert await asyncio.wait_for(
            data._store_timeseries_data("AFTER.NS", _ohlcv_df("AFTER.NS")), timeout=5
        ) is True
        assert trace.overlaps == []

    async def test_gate_preserves_the_persisted_rows(self, test_db: AsyncSession):
        """No published figure may move: the gated entry point and the raw
        write path must persist identical OHLCV values for the same frame."""
        frame = _ohlcv_df("FIG.NS")
        assert await DataService(test_db)._store_timeseries_data("FIGA.NS", frame) is True

        ungated = DataService(test_db)
        async with ungated._db_lock:
            assert await ungated._write_timeseries_rows("FIGB.NS", frame) is True

        assert await _stored_rows(test_db, "FIGA.NS") == await _stored_rows(test_db, "FIGB.NS")