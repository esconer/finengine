"""Framework-level test-isolation invariants (tests/conftest.py).

Two kinds of process-global state used to leak across test files, so that a
test's result depended on which files ran before it. Both are now reset once,
at the framework level, in conftest. Every test below is written to FAIL if
its reset is removed or made a no-op -- an isolation fixture that cannot fail
is not evidence of anything.

1. `_current_app()`: `importlib.reload(main)` -- which
   test_agent_d_deployment_contract performs to exercise the production-only
   middleware gate -- builds a brand-new FastAPI instance carrying a
   brand-new `dependency_overrides` dict, and orphans the previous one forever.
   A conftest that captured `app` at import time kept driving the orphan while
   every test installed overrides on the live one, so those overrides silently
   became no-ops and real services (and live yfinance calls) answered instead
   of the mocks. Three test_bugfix_api_layer tests failed only in suite order
   for exactly this reason.

2. `reset_service_memos`: the DataService/cointegration class-level memos plus
   the cache_service runtime-config snapshot. These used to be cleared by a
   file-local fixture in test_agent_b_data_audit and by nothing else.
"""

import importlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import main as main_module
from app.api import data as data_mod
from app.models.database import PortfolioPosition
from app.services import cache_service, cointegration_service
from app.services.data_service import DataService


def _frame(source: str = "bfinance") -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=5),
            "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0,
            "adj_close": 1.0, "volume": 1000,
        }
    )
    frame._source = source
    return frame


# --- 1. the driven app is the configured app, across main reloads ------------


def test_a_reload_main_like_the_deployment_contract_gate():
    """Rebuild `main.app`, exactly as test_agent_d_deployment_contract does.

    Deliberately NOT undone. That gate reloads twice and leaves the last
    reload's instance behind, and the point of this pair is that the leftover
    instance must not be able to strand anyone -- so the leftover stays.
    """
    before = main_module.app
    before_overrides = before.dependency_overrides
    importlib.reload(main_module)

    # Assert the reload really did swap in a new app with a new overrides
    # dict, so this pair cannot pass vacuously because the reload stopped
    # rebuilding the application.
    assert main_module.app is not before
    assert main_module.app.dependency_overrides is not before_overrides


@pytest.mark.asyncio
async def test_b_dependency_overrides_reach_the_client_after_a_main_reload(
    async_client, test_db: AsyncSession
):
    """The gate from the previous test must not strand this test's overrides.

    Red without the conftest fix: the override lands on a dependency_overrides
    dict that the already-built client never reads, the real DataService
    answers, and the assertion sees a live-vendor payload (or a 404) instead
    of the mock's. Red with the network down too -- which is the point: it
    must not be able to reach a vendor at all.
    """
    from tests.conftest import _current_app

    # The invariant in one line: same object, same dependency_overrides dict.
    assert _current_app() is main_module.app
    assert async_client._transport.app is main_module.app

    mock_ds = Mock()
    mock_ds._get_cached_data = AsyncMock(return_value=None)
    mock_ds.fetch_historical_data = AsyncMock(return_value=_frame())
    mock_ds.fetch_quote = AsyncMock(return_value=None)
    mock_ds._source_of_df = Mock(return_value="bfinance")

    main_module.app.dependency_overrides[data_mod.get_data_service] = lambda: mock_ds
    try:
        resp = await async_client.get("/api/v1/data/ZZTOPOLOGY")
        assert resp.status_code == 200
        payload = resp.json()
        # 'bfinance' is reachable only from the mock; a live fallback would
        # answer with yfinance, or with nothing at all.
        assert payload["source"] == "bfinance"
        assert payload["from_cache"] is False
    finally:
        main_module.app.dependency_overrides.pop(data_mod.get_data_service, None)


@pytest.mark.asyncio
async def test_c_conftest_client_drives_the_live_app(async_client, test_db: AsyncSession):
    """`async_client` must be bound to `main.app`, not to a captured import."""
    from tests.conftest import _current_app

    assert _current_app() is main_module.app

    await test_db.execute(PortfolioPosition.__table__.delete())
    await test_db.commit()
    resp = await async_client.get("/api/v1/analytics/factor-exposure")
    assert resp.status_code == 200


# --- 2. the memo reset is load-bearing ---------------------------------------


def test_reset_service_memos_actually_clears():
    """First of a pair: poison every memo, and prove the poisoning is real."""
    stamp = datetime.now(timezone.utc).timestamp()
    DataService._in_memory_df_cache["POISON.NS"] = (stamp, pd.DataFrame())
    DataService._quote_memo["POISON.NS"] = (stamp, {"price": 1.0})
    DataService._l1_sources["POISON.NS"] = "yfinance"
    DataService._l1_preferences["POISON.NS"] = "bfinance"
    DataService._quote_sources["POISON.NS"] = "yfinance"
    cointegration_service._IN_MEMORY_COINT_CACHE["POISON/PAIR"] = (stamp, {})
    # The runtime-config snapshot records the enable_cache / cache_ttl_minutes
    # rows of whichever DB was last consulted; poisoning it with the
    # cache-enabled default is what makes a later cache-bypass test lie.
    cache_service._note_runtime_config("60:true")

    # Guard against the poisoning being silently impossible, which would make
    # the next test vacuous.
    assert len(DataService._in_memory_df_cache) == 1
    assert len(DataService._quote_memo) == 1
    assert len(DataService._l1_sources) == 1
    assert len(DataService._l1_preferences) == 1
    assert len(DataService._quote_sources) == 1
    assert len(cointegration_service._IN_MEMORY_COINT_CACHE) == 1
    assert cache_service.get_runtime_cache_snapshot() is not None
    assert cache_service.get_runtime_cache_snapshot().enabled is True


def test_reset_service_memos_leaves_nothing_for_the_next_test():
    """Second of the pair: fails if the conftest autouse reset stops running.

    Relies on the test above having run first; `-p no:randomly` (what CI uses)
    keeps that order. Under random ordering this test still passes, because an
    already-empty memo satisfies it -- the poisoning test is the one that
    establishes there was something to clear.
    """
    assert DataService._in_memory_df_cache == {}
    assert DataService._quote_memo == {}
    assert DataService._l1_sources == {}
    assert DataService._l1_preferences == {}
    assert DataService._quote_sources == {}
    assert cointegration_service._IN_MEMORY_COINT_CACHE == {}
    assert cache_service.get_runtime_cache_snapshot() is None