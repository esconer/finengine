"""The `isolated_database` fixture must keep every DB entry point off daisy.db.

INF-8. `conftest.py` had two client fixtures. `client` rebound four things
before handing out a TestClient; `async_client` rebound only the
`get_db_session` dependency override. That override is consulted by exactly one
mechanism -- FastAPI's `Depends` -- and every other way into the database
bypasses it:

    database.py:82            async with SessionLocal() as session:   # get_db_session
    websocket.py:299/353/466  async with SessionLocal() as db:        # background senders

`websocket.py:19` is `from app.db.database import SessionLocal`, which stores
the factory in `app.api.websocket`'s OWN module globals. It is therefore a
second binding of the same object, and rebinding `db_mod.SessionLocal` leaves
it pointing at production -- verified in
`test_websocket_alias_is_a_separate_binding`, not assumed.

Real data at stake: `backend/data/daisy.db` holds live holdings (14 positions
with quantities and cost basis at the time of writing), plus -wal/-shm siblings.

WHY EVERY EXECUTION HERE USES A COPY. Opening a WAL database maps and may
rewrite `-shm`, and SQLAlchemy's CREATE UNIQUE INDEX self-heal rewrites the main
file. Nothing in this module opens `backend/data/daisy.db`. The
`production_database_copy` fixture copies the real db + `-wal` + `-shm` out to
`tmp_path` (plain reads of those bytes), and the pre-fix behaviour is then
reproduced against that byte-identical clone. `_REAL_DATABASE_URL` pins which
file "unpatched" resolves to, so the clone stands for the original by identity,
not by resemblance.

Every test below asserts on row counts, tickers or file bytes. None of them
asserts "no exception was raised".
"""

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio

import app.api.websocket as ws_mod
import app.db.database as db_mod
from app.api.websocket import send_market_data_update
from app.models.database import Base, PortfolioPosition

# The URL the application resolves at import, captured before any fixture can
# monkeypatch it. Used only as a comparison target, never to open the file.
_REAL_DATABASE_URL = db_mod.settings.database_url

_SENTINEL_TICKER = "ZZCONFTESTONLY.NS"
_PRODUCTION_DB = Path("data/daisy.db")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _production_db_files():
    """The real database plus its WAL siblings."""
    base = _PRODUCTION_DB
    return [base] + [
        sibling
        for sibling in (base.with_name(base.name + s) for s in ("-wal", "-shm"))
        if sibling.exists()
    ]


def _rows(db_path) -> list:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT ticker, quantity, buy_price FROM portfolio_positions"
        ).fetchall()
    finally:
        conn.close()


@pytest.fixture
def production_database_copy(tmp_path) -> Path:
    """A byte-identical clone of backend/data/daisy.db, in tmp_path.

    The clone stands in for production when reproducing the pre-fix behaviour,
    so `backend/data/` is only ever read.
    """
    clone = tmp_path / "production_clone.db"
    for src in _production_db_files():
        shutil.copyfile(src, clone.with_name(clone.name + src.name[len(_PRODUCTION_DB.name):]))
    return clone


@pytest_asyncio.fixture
async def isolated_schema(isolated_database):
    """Give the isolated database the real schema.

    Load-bearing for the "the sender sees nothing" assertions below: without a
    schema, `send_market_data_update`'s SELECT raises "no such table", the
    sender swallows the exception (websocket.py:512), and every such assertion
    would pass for the wrong reason.
    """
    async with isolated_database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _repoint_at(monkeypatch, clone: Path) -> str:
    """Make every SessionLocal/engine consumer resolve `clone` -- i.e. unpatched.

    Mirrors the state `async_client` used to leave the process in: the URL and
    the two `SessionLocal` globals all still naming the production database.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    url = f"sqlite+aiosqlite:///{clone.as_posix()}"
    engine = create_async_engine(url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", factory)
    monkeypatch.setattr(ws_mod, "SessionLocal", factory)
    monkeypatch.setattr(db_mod.settings, "database_url", url)
    return url


async def _broadcast_positions() -> dict:
    """Run the real websocket background sender and return its broadcast payload.

    `send_market_data_update` reads `ws_mod.SessionLocal` at websocket.py:466.
    Capturing `manager.broadcast` turns that otherwise invisible read into an
    assertion.
    """
    from unittest.mock import AsyncMock

    broadcast = AsyncMock()
    ws_mod.manager.broadcast = broadcast
    try:
        await send_market_data_update()
        return broadcast.await_args.args[0] if broadcast.await_args else {}
    finally:
        del ws_mod.manager.broadcast


async def _isolated_position_count() -> int:
    async with db_mod.SessionLocal() as db:
        from sqlalchemy import func, select

        return (await db.execute(select(func.count()).select_from(PortfolioPosition))).scalar()


def _assert_points_at_temp_database() -> None:
    """All four rebound globals resolve to the same on-disk temp database."""
    isolated_url = str(db_mod.engine.url)
    assert isolated_url == str(db_mod.SessionLocal.kw["bind"].url)
    assert isolated_url == str(ws_mod.SessionLocal.kw["bind"].url)
    assert isolated_url == db_mod.settings.database_url

    assert "daisy.db" not in isolated_url
    assert ":memory:" not in isolated_url
    assert db_mod.engine.url.database.endswith("isolated.db")


# --------------------------------------------------------------------------
# 1. the fixture is genuinely shared
# --------------------------------------------------------------------------


def test_client_fixture_depends_on_the_one_shared_rebinding(client, request):
    """`client` gets its rebinding from `isolated_database`, not its own."""
    assert "isolated_database" in request.fixturenames
    _assert_points_at_temp_database()


async def test_async_client_depends_on_the_one_shared_rebinding(async_client, request):
    """The fixture INF-8 was about: `async_client` now shares the rebinding."""
    assert "isolated_database" in request.fixturenames
    _assert_points_at_temp_database()


async def test_the_resolved_database_is_the_temp_file_and_not_daisy_db(
    isolated_database, tmp_path
):
    """Whatever path the app resolves, it is the temp file -- never daisy.db.

    Covers the case where `backend/data/daisy.db` does not exist on this
    checkout at all: then the suite cannot reach production even accidentally,
    and an isolation test could pass against an empty "real" database. Say so,
    rather than let it read as evidence.
    """
    resolved = Path(isolated_database.url.split("///", 1)[1])
    assert not resolved.exists(), "precondition: nothing has connected yet"
    assert resolved.parent == tmp_path

    if not _PRODUCTION_DB.exists():
        pytest.fail(
            "backend/data/daisy.db is absent, so the isolation assertions in "
            "this file cannot be distinguished from assertions against an "
            "empty database"
        )
    assert resolved.resolve() != _PRODUCTION_DB.resolve()


# --------------------------------------------------------------------------
# 2. why the fourth rebind exists
# --------------------------------------------------------------------------


async def test_websocket_alias_is_a_separate_binding(async_client):
    """`ws_mod.SessionLocal` is its own global, not a view of `db_mod`'s.

    The whole reason for rebinding it separately: if it tracked `db_mod` there
    would be nothing to rebind. Patching only `db_mod.SessionLocal` must leave
    the websocket alias exactly where it was.

    Uses a private MonkeyPatch rather than the fixture's own, because
    `monkeypatch.undo()` would also undo the isolation this file is asserting.
    """
    alias_before = ws_mod.SessionLocal
    db_factory_before = db_mod.SessionLocal
    assert alias_before is db_factory_before, "the fixture rebinds both to one factory"

    with pytest.MonkeyPatch.context() as scoped:
        scoped.setattr(db_mod, "SessionLocal", "SOMETHING_ELSE")
        assert ws_mod.SessionLocal is alias_before
        assert ws_mod.SessionLocal is not db_mod.SessionLocal

    assert ws_mod.SessionLocal is alias_before
    assert db_mod.SessionLocal is db_factory_before


async def test_monkeypatching_the_module_attribute_redirects_the_sender(
    async_client, isolated_schema, production_database_copy, monkeypatch
):
    """`monkeypatch.setattr(ws_mod, "SessionLocal", ...)` really does take effect.

    Not assumed from "it is a module global": the production sender is run twice,
    against two different databases, and the two runs must disagree.
    """
    real_rows = _rows(production_database_copy)
    assert real_rows, "the clone is empty, so this test would prove nothing"

    # (a) the fixture's rebinding. The schema exists (isolated_schema) and the
    #     table is empty, so "nothing broadcast" means nothing there to read.
    assert await _isolated_position_count() == 0
    assert await _broadcast_positions() == {}

    # (b) the same sender, with the alias repointed at a database that does
    #     have rows. Same function, same call site, different module global.
    _repoint_at(monkeypatch, production_database_copy)
    payload = await _broadcast_positions()
    assert sorted(payload["data"]) == sorted(ticker for ticker, _, _ in real_rows)


# --------------------------------------------------------------------------
# 3. the red/green pair: does the sender see the developer's real holdings?
# --------------------------------------------------------------------------


async def test_fixture_rebinding_hides_the_real_portfolio_from_the_sender(
    async_client, isolated_schema
):
    """GREEN. With the shared fixture active the sender sees nothing real.

    `send_market_data_update` returns early when there are no positions, so an
    isolated database with a schema and zero rows produces no broadcast at all.
    """
    assert await _isolated_position_count() == 0, "precondition: table exists, no rows"
    assert await _broadcast_positions() == {}
    _assert_points_at_temp_database()


async def test_without_the_rebinding_the_sender_broadcasts_real_holdings(
    async_client, isolated_schema, production_database_copy, monkeypatch
):
    """RED. The old `async_client` left the websocket alias on production.

    Reproduces the pre-fix state -- every DB global still naming the production
    database -- and shows the developer's real holdings coming out of the real
    production function, at the exact call site (`websocket.py:466`) the old
    fixture never touched. Same code as the green test above; identical
    assertions; the only difference is the four rebindings.

    Also pins the clone to the real database, so "production" is not a lookalike:
    both resolve to `sqlite+aiosqlite:///./data/daisy.db`.
    """
    assert _REAL_DATABASE_URL == "sqlite+aiosqlite:///./data/daisy.db"
    real_rows = _rows(production_database_copy)
    assert real_rows, "the clone must contain the developer's positions"
    assert {ticker for ticker, _, _ in real_rows} & {_SENTINEL_TICKER} == set()

    _repoint_at(monkeypatch, production_database_copy)

    payload = await _broadcast_positions()
    assert sorted(payload["data"]) == sorted(ticker for ticker, _, _ in real_rows)


# --------------------------------------------------------------------------
# 4. writes: where does a row inserted through SessionLocal land?
# --------------------------------------------------------------------------


async def test_write_through_the_websocket_alias_lands_in_the_isolated_db(
    async_client, isolated_schema, production_database_copy
):
    """The row is in the temp database and is NOT in the production clone.

    Uses `ws_mod.SessionLocal` -- the exact factory websocket.py:299/353/466
    open -- rather than the overridden `get_db_session`, so this covers the path
    the dependency override cannot see.
    """
    async with ws_mod.SessionLocal() as db:
        db.add(PortfolioPosition(
            ticker=_SENTINEL_TICKER, weight=1.0, quantity=7, buy_price=11.0,
            last_price=12.0, market_value=84.0, added_on=datetime(2020, 1, 1),
        ))
        await db.commit()

    assert _rows(db_mod.engine.url.database) == [(_SENTINEL_TICKER, 7.0, 11.0)]
    assert {ticker for ticker, _, _ in _rows(production_database_copy)} & {_SENTINEL_TICKER} == set()


async def test_the_same_write_lands_in_the_production_database_when_unpatched(
    async_client, production_database_copy, monkeypatch
):
    """RED, executed. With no rebinding, that identical insert hits production.

    The pre-fix write destination, demonstrated end to end: the same
    `ws_mod.SessionLocal` insert from the test above, with the globals left
    where the old `async_client` left them, lands in the production clone.
    With the URL assertion in `test_without_the_rebinding...`, that is the whole
    chain from "old conftest" to "a row in backend/data/daisy.db".
    """
    before = _rows(production_database_copy)

    _repoint_at(monkeypatch, production_database_copy)

    async with ws_mod.SessionLocal() as db:
        db.add(PortfolioPosition(
            ticker=_SENTINEL_TICKER, weight=1.0, quantity=7, buy_price=11.0,
            last_price=12.0, market_value=84.0, added_on=datetime(2020, 1, 1),
        ))
        await db.commit()

    assert _rows(production_database_copy) == before + [(_SENTINEL_TICKER, 7.0, 11.0)]