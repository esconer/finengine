"""The concurrent price refresh must not drop a leg.

`_update_portfolio_prices` runs one gather worker per stale leg, and every
worker runs its quote lookup through the ONE AsyncSession the request owns.
`DataService.fetch_quote` reads runtime config and the vendor preference off
that session (data_service.py:894-895), so each worker's `db.execute()`
autoflushes whatever the other workers have already written. Autoflush is on
because `app/db/database.py:29-33` never passes it and SQLAlchemy's default is
True.

That is a lost-update hazard for the mapped attributes the refresh assigns,
not merely a noisy one: a value written while a sibling's flush sits between
its dirty snapshot (sqlalchemy/orm/session.py:4373) and its post-flush
`_commit_all_states` (session.py:4457-4474) is not part of that flush, and is
reset without a database update. `last_price`/`market_value` are what
portfolio.py:1569-1571 validates and what analytics.py derives every portfolio
weight from, and `updated_on` is the 15-minute staleness gate
(portfolio.py:2259), so a dropped write leaves a stale valuation feeding the
whole product.

The four tests below drive a real session; none of them inspects the source of
`_update_portfolio_prices`. The first two force the interleave and fail on the
code that assigns inside the gather. The last two pin behaviour the fix had to
preserve: partial failure, and the per-leg refresh instant.
"""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.portfolio import _update_portfolio_prices
from app.db.database import Base
from app.models.database import PortfolioPosition


# The gather starts its workers in list order, so the gated leg comes first and
# the leg that drives the flush comes second.
_TICKERS = ("CCC.NS", "BBB.NS", "AAA.NS", "DDD.NS")
_GATED = "CCC.NS"  # clean when the gather starts; its write is the one at risk
_FLUSHER = "BBB.NS"  # issues the db.execute() that autoflushes

_QUOTES = {"CCC.NS": 33.0, "BBB.NS": 22.0, "AAA.NS": 11.0, "DDD.NS": 44.0}
# Pending before the refresh starts. They give the in-gather flush real work,
# which is what makes it await and so creates the yield point the gated leg
# needs in order to land mid-flush.
_SEEDED = {"AAA.NS": 7.0, "DDD.NS": 8.0}


def _position(ticker: str, price: float = 1.0) -> PortfolioPosition:
    return PortfolioPosition(
        ticker=ticker,
        weight=0.25,
        quantity=10.0,
        buy_price=price,
        last_price=price,
        market_value=10.0 * price,
        region="IN",
        sector="Unknown",
        industry="Unknown",
    )


class _FakeQuotes:
    """Stands in for DataService without touching the network.

    `fetch_quote` reproduces the one property that matters: it runs a
    `db.execute()` on the session the caller owns, exactly as the real
    DataService does when it reads runtime config and source preference, so
    the refresh's concurrent workers drive autoflush on a shared session.

    `gate` holds the one leg whose write is under test until a cursor
    statement has gone out inside the flush.
    """

    def __init__(self, db):
        self._db = db
        self.gate = asyncio.Event()

    def open_gate(self):
        self.gate.set()

    async def fetch_quote(self, ticker):
        if ticker == _GATED:
            await self.gate.wait()
            return {"current_price": _QUOTES[ticker], "currency": "INR"}
        # Autoflushes the shared session: sibling legs' pending writes go out
        # here, from inside the gather.
        await self._db.execute(select(PortfolioPosition.ticker))
        return {"current_price": _QUOTES[ticker], "currency": "INR"}


class _FlushWitness:
    """Observes autoflush on the real session and releases the gated worker.

    The flush has to emit more than one statement, or there is no await in the
    middle of it for the gated leg to slip through. A pending INSERT supplies
    the second statement: `save_obj` emits every UPDATE and then every INSERT
    (persistence.py:86-94), with a real await between them.

    What the witness records is the invariant itself -- was the gated worker
    released while a flush was in flight? -- rather than a statement count,
    which would be an accident of the driver's batching.
    """

    def __init__(self, db, service):
        self._db = db
        self._service = service
        self.updates = []
        self.gate_opened_in_flush = None
        self.gate_opened_after_updates = None
        self.dirty_at_flush_start = []
        self.dirty_at_flush_end = []
        self.flushes = 0

    def attach(self):
        sync_session = self._db.sync_session
        # The sync engine, not the AsyncEngine: `after_cursor_execute` on an
        # AsyncEngine is dispatched after the greenlet has already resumed, so
        # the gate would open after the flush instead of inside it.
        engine = self._db.bind.sync_engine

        def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("UPDATE"):
                self.updates.append(statement)
            if not self._service.gate.is_set():
                # `Session._flushing` is the flag `Session.flush` sets around
                # `_flush` (session.py:4352-4355). There is no public reader for
                # it; this is the state that makes a mid-flush assignment lossy.
                self.gate_opened_in_flush = bool(sync_session._flushing)
                self.gate_opened_after_updates = len(self.updates)
                self._service.open_gate()

        def before_flush(session, flush_context, objects):
            self.flushes += 1
            self.dirty_at_flush_start.append(self._dirty_tickers())

        def after_flush(session, flush_context):
            self.dirty_at_flush_end.append(self._dirty_tickers())

        event.listen(engine, "after_cursor_execute", after_cursor_execute)
        event.listen(sync_session, "before_flush", before_flush)
        event.listen(sync_session, "after_flush", after_flush)
        return (
            lambda: event.remove(engine, "after_cursor_execute", after_cursor_execute),
            lambda: event.remove(sync_session, "before_flush", before_flush),
            lambda: event.remove(sync_session, "after_flush", after_flush),
        )

    def _dirty_tickers(self):
        modified = self._db.sync_session.identity_map._modified
        return {
            state.dict.get("ticker")
            for state in modified
            if state.dict.get("ticker") is not None
        }


class _StaggeredQuotes:
    """Quotes that arrive a measurable distance apart, in a known order.

    `asyncio.sleep` is a genuine await, so the workers still overlap exactly as
    they do behind the real `fetch_quote`'s network call.
    """

    def __init__(self, delays):
        self._delays = delays

    async def fetch_quote(self, ticker):
        await asyncio.sleep(self._delays[ticker])
        return {"current_price": _QUOTES[ticker], "currency": "INR"}


@pytest.fixture
async def book():
    """A real AsyncSession over the real table, with the refresh legs loaded."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session = async_sessionmaker(engine, expire_on_commit=False)()
    for ticker in _TICKERS:
        session.add(_position(ticker))

    by_ticker = {
        p.ticker: p
        for p in (
            await session.execute(
                select(PortfolioPosition).order_by(PortfolioPosition.ticker)
            )
        )
        .scalars()
        .all()
    }
    for ticker, price in _SEEDED.items():
        by_ticker[ticker].last_price = price
        by_ticker[ticker].market_value = 10.0 * price
    # Added AFTER the reads above, which would otherwise autoflush it: this is
    # the pending INSERT that gives the in-gather flush a second statement, and
    # so an await in the middle of it. Not a refresh target.
    session.add(_position("EEE.NS", 5.0))

    try:
        yield session, [by_ticker[t] for t in _TICKERS], engine
    finally:
        await session.close()
        await engine.dispose()


async def _read_committed(engine):
    """Read through a separate session so the writer's identity map cannot lie."""
    reader = async_sessionmaker(engine, expire_on_commit=False)()
    try:
        rows = (
            await reader.execute(
                select(PortfolioPosition).order_by(PortfolioPosition.ticker)
            )
        ).scalars().all()
        return {p.ticker: p for p in rows}
    finally:
        await reader.close()


async def test_refresh_persists_a_leg_assigned_during_a_sibling_autoflush(book):
    """The written value must reach the database, not just the identity map.

    With the ORM assigned inside the gather, CCC.NS is written after the
    flush's dirty snapshot and is reset by `_commit_all_states` without an
    UPDATE, so the committed row keeps its seeded price and the mark stays
    stale for every downstream reader.
    """
    session, positions, engine = book
    service = _FakeQuotes(session)
    witness = _FlushWitness(session, service)
    removes = witness.attach()
    try:
        await _update_portfolio_prices(positions, service, force=True)
        await session.commit()  # portfolio.py:919
    finally:
        for remove in removes:
            remove()

    # The interleave is only meaningful if the gate really opened inside a
    # flush, not after it.
    assert witness.updates, "no UPDATE was emitted; the interleave never happened"
    assert witness.gate_opened_in_flush is True, (
        "the gate opened with no flush in flight, so the gated write did not "
        "land mid-flush and this run proves nothing"
    )
    assert witness.gate_opened_after_updates >= 1
    assert witness.flushes >= 1, "no flush was observed on the shared session"

    rows = await _read_committed(engine)

    assert rows[_GATED].last_price == _QUOTES[_GATED], (
        f"{_GATED} lost its price refresh: it was assigned while a sibling "
        "worker's autoflush was in flight and was reset without an UPDATE"
    )
    assert rows[_GATED].market_value == 10.0 * _QUOTES[_GATED]
    assert rows[_GATED].updated_on is not None

    # Every other leg refreshes too; no published value changes.
    for ticker, price in _QUOTES.items():
        assert rows[ticker].last_price == price, ticker
        assert rows[ticker].market_value == 10.0 * price, ticker
        assert rows[ticker].updated_on is not None, ticker


async def test_no_gather_worker_assigns_a_mapped_attribute_mid_flush(book):
    """No in-gather flush may gain a dirty row.

    SQLAlchemy resets -- and silently drops -- any instance that becomes dirty
    between `before_flush` and `after_flush`. Asserting that no flush on this
    shared session ever gains a dirty row is a statement about the session's
    behaviour, not about the source text of `_update_portfolio_prices`.
    """
    session, positions, engine = book
    service = _FakeQuotes(session)
    witness = _FlushWitness(session, service)
    removes = witness.attach()
    try:
        await _update_portfolio_prices(positions, service, force=True)
    finally:
        for remove in removes:
            remove()

    assert witness.dirty_at_flush_start, (
        "no flush was observed inside the gather; the interleave never happened"
    )
    for start, end in zip(witness.dirty_at_flush_start, witness.dirty_at_flush_end):
        assert end <= start, (
            f"a flush inside the gather gained dirty rows {sorted(end - start)}; "
            "a sibling worker assigned a mapped attribute mid-flush and that "
            "write was reset without a database update"
        )


async def test_refresh_keeps_the_other_legs_when_one_quote_fails(book):
    """Partial-failure behaviour is unchanged: a failing ticker blocks only itself."""
    session, positions, engine = book

    async def fetch_quote(ticker):
        if ticker == _FLUSHER:
            raise RuntimeError("quote unavailable")
        return {"current_price": _QUOTES[ticker], "currency": "INR"}

    service = type("_S", (), {"fetch_quote": staticmethod(fetch_quote)})()

    await _update_portfolio_prices(positions, service, force=True)
    await session.commit()

    rows = await _read_committed(engine)

    assert rows[_FLUSHER].last_price == 1.0, "a failed fetch must not be written"
    for ticker in (_GATED, "AAA.NS", "DDD.NS"):
        assert rows[ticker].last_price == _QUOTES[ticker], ticker


async def test_each_leg_keeps_its_own_refresh_instant(book):
    """`updated_on` stays a per-leg write clock, one stamp per fetched leg.

    `_mark_clock_block` (portfolio.py:313-323) publishes the count and the
    spread of these instants precisely because the legs are written at
    different times. Applying the refresh serially must stamp each leg when
    its own quote arrived, not all of them at the end of the gather.
    """
    session, positions, engine = book
    # Arrival order is DDD, AAA, BBB, CCC, ~0.12s apart.
    delays = {"CCC.NS": 0.36, "BBB.NS": 0.24, "AAA.NS": 0.12, "DDD.NS": 0.0}

    await _update_portfolio_prices(positions, _StaggeredQuotes(delays), force=True)
    await session.commit()

    rows = await _read_committed(engine)

    assert rows["DDD.NS"].updated_on < rows["AAA.NS"].updated_on
    assert rows["AAA.NS"].updated_on < rows["BBB.NS"].updated_on
    assert rows["BBB.NS"].updated_on < rows["CCC.NS"].updated_on
    span = rows["CCC.NS"].updated_on - rows["DDD.NS"].updated_on
    assert span >= timedelta(seconds=0.25), (
        f"the legs were stamped {span.total_seconds():.4f}s apart; the "
        "per-leg write clock collapsed into a single instant"
    )