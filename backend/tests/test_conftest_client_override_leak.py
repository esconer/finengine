"""`async_client` must drop its `dependency_overrides` entry on EVERY exit path.

`conftest.py` installed `app.dependency_overrides[get_db_session] =
_override_get_db(test_db)` and, at the end of the fixture, popped it. The pop
was a bare trailing statement after the `yield`, so it was *unreachable
whenever the test body raised* -- the normal shape of a failing test.

The override is not inert state: it yields the `test_db` of the test that is
running. A surviving entry therefore points the next test's
`Depends(get_db_session)` at a dead `:memory:` StaticPool database belonging to
a finished test. That is invisible today only by luck -- the line above
reassigns the override unconditionally on every setup, so the stale value is
overwritten before anyone reads it. Any fixture that ever came to depend on the
pop actually running (a client that skipped the override, a `None` override, a
teardown ordering change) would leak.

These tests drive the *shipped* fixture rather than a copy of it:
`pytest_asyncio.fixture(f)` returns `pytest.fixture(f)`, and pytest 8.3 hands
that back as the function wrapped in a guard that `fail()`s on a direct call --
so `inspect.unwrap` (public API, the guard is `functools.wraps`-ed) recovers the
real async-generator function. Calling that and then `athrow`-ing is precisely
what pytest-asyncio's finalizer does when a test body raises, and it is what
lets the assertion run *after* teardown -- the only point at which the leak is
visible.
"""

import inspect

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import main as main_module
from app.db.database import get_db_session
from app.models.database import PortfolioPosition
from tests.conftest import _current_app, _override_get_db

# A route whose handler takes `db: AsyncSession = Depends(get_db_session)`
# (analytics.py:7013), so the override installed by the fixture is genuinely on
# the request path rather than decoration. Proven network-free and 200 against
# an empty database by test_c_conftest_client_drives_the_live_app in
# test_test_isolation_invariants.py.
_ROUTE = "/api/v1/analytics/factor-exposure"


@pytest.fixture(autouse=True)
def _this_module_cannot_poison_the_suite():
    """Restore `dependency_overrides` around every test in this file.

    `test_the_pre_fix_fixture_body_really_leaks` deliberately reproduces the
    pre-fix teardown, so without this the leak would be real rather than
    hypothetical -- the module that documents a bug must not ship it.
    """
    before = main_module.app
    saved = dict(before.dependency_overrides)
    try:
        yield
    finally:
        live = _current_app()
        for target in (before, live):
            target.dependency_overrides.clear()
            target.dependency_overrides.update(saved)


async def _empty_the_positions(test_db: AsyncSession) -> None:
    await test_db.execute(PortfolioPosition.__table__.delete())
    await test_db.commit()


async def _installed_override_yields_this_tests_session(
    test_db: AsyncSession,
) -> None:
    """Prove the live override hands out *this* test's `test_db`.

    That is what makes a surviving entry harmful rather than merely untidy: the
    next test's `Depends(get_db_session)` would resolve to a session on a
    `:memory:` database whose engine was disposed at the end of this test.
    """
    app = _current_app()
    assert get_db_session in app.dependency_overrides, (
        "precondition: the fixture is supposed to install the override for the "
        "whole life of the test, so this test cannot observe a teardown leak"
    )
    override = app.dependency_overrides[get_db_session]
    probe = override()
    try:
        assert await probe.__anext__() is test_db
    finally:
        await probe.aclose()


def _shipped_async_client_fixture(test_db: AsyncSession, isolated_database):
    """Enter the REAL `conftest.async_client`, returned as a live generator.

    pytest 8.3 substitutes a wrapper that `fail()`s when a fixture is called
    directly, so the module attribute is unwrapped first. The returned object is
    the async generator the fixture actually is; `__anext__` is fixture setup
    and the second advance is pytest-asyncio's teardown finalizer.
    """
    from tests import conftest as conftest_mod

    gen = inspect.unwrap(conftest_mod.async_client)(test_db, isolated_database)
    assert inspect.isasyncgen(gen), (
        f"conftest.async_client did not unwrap to an async generator "
        f"({gen!r}); pytest 8.4 replaced the fixture object with a "
        f"FixtureFunctionDefinition and this test must be rewritten"
    )
    return gen


async def test_a_raising_body_leaves_no_dependency_override(
    test_db: AsyncSession, isolated_database
):
    """GREEN. Request through the client, then raise, exactly as a failing test
    does -- and no `dependency_overrides` entry survives the teardown.

    Fails against the pre-change conftest: the pop sat after the `yield`, so
    `athrow` skipped it and the assertion below found the override still there.
    """
    gen = _shipped_async_client_fixture(test_db, isolated_database)

    client = await gen.__anext__()
    app = _current_app()
    await _empty_the_positions(test_db)
    await _installed_override_yields_this_tests_session(test_db)

    resp = await client.get(_ROUTE)
    assert resp.status_code == 200, resp.text

    # The test body raising. pytest-asyncio's finalizer advances the generator a
    # second time, which is exactly this `athrow`.
    with pytest.raises(RuntimeError, match="test body raised"):
        await gen.athrow(RuntimeError("test body raised"))

    survivors = dict(app.dependency_overrides)
    assert get_db_session not in survivors, (
        "conftest.async_client's teardown did not pop get_db_session when the "
        "test body raised; the override yielding this test's now-disposed "
        f"test_db survives into the next test: {survivors}"
    )


async def test_the_normal_exit_still_pops_the_override(
    test_db: AsyncSession, isolated_database
):
    """GREEN. The passing path is unchanged: a clean `__anext__` past the yield
    also empties `dependency_overrides`.

    Without this the fix above could pass by popping on every path *except* the
    one the suite actually uses.
    """
    gen = _shipped_async_client_fixture(test_db, isolated_database)

    client = await gen.__anext__()
    app = _current_app()
    await _empty_the_positions(test_db)

    resp = await client.get(_ROUTE)
    assert resp.status_code == 200, resp.text
    assert get_db_session in app.dependency_overrides, (
        "precondition: the override is live while the test is running"
    )

    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()  # fixture teardown: resume and finish

    assert get_db_session not in app.dependency_overrides


async def _pre_fix_async_client(test_db: AsyncSession, isolated_database):
    """`conftest.async_client` verbatim as it stood before the `try`/`finally`.

    Kept as a real async generator, driven by the same `__anext__`/`athrow`
    pair as `test_a_raising_body_leaves_no_dependency_override`, so the two
    differ in exactly one thing: whether the pop is guarded. A hand-written
    `raise` outside a generator would not demonstrate anything -- the pre-fix
    code never had a generator whose tail was skipped, it had a generator whose
    tail WAS skipped.
    """
    app = _current_app()
    app.dependency_overrides[get_db_session] = _override_get_db(test_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.pop(get_db_session, None)


async def test_the_pre_fix_fixture_body_really_leaks(
    test_db: AsyncSession, isolated_database
):
    """RED, executed. Same fixture arguments, same request, same raise as the
    green test above -- and the override IS still installed afterwards.

    A negative control, so the two green tests are known to be observing a real
    mechanism: if `athrow` did not reproduce what pytest does at teardown, they
    would pass for the wrong reason.

    The module-level `_this_module_cannot_poison_the_suite` fixture cleans up
    after the leak this test deliberately creates.
    """
    gen = _pre_fix_async_client(test_db, isolated_database)
    assert inspect.isasyncgen(gen)

    client = await gen.__anext__()
    app = _current_app()
    await _empty_the_positions(test_db)
    await _installed_override_yields_this_tests_session(test_db)

    resp = await client.get(_ROUTE)
    assert resp.status_code == 200, resp.text

    with pytest.raises(RuntimeError, match="test body raised"):
        await gen.athrow(RuntimeError("test body raised"))

    assert get_db_session in app.dependency_overrides, (
        "the pre-fix shape no longer leaks, so test_a_... is no longer proving "
        "that the try/finally is what closes the leak"
    )
