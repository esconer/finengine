"""C-08 pre-change fixture: one config update must have one commit boundary."""
from __future__ import annotations
from unittest.mock import Mock
from app.api import data as data_mod
from agent_c_fixture_support import FakeDB, run


async def main():
    db = FakeDB()
    async def source_commit(_db, source):
        db.commits += 1
        return source
    try:
        await data_mod.update_api_config(primary_source="yfinance", cache_ttl_minutes=90, enable_cache=True, db=db, cache_service=Mock())
    except Exception as exc:
        print("before.error", type(exc).__name__)
    print("before.commits", db.commits, "expected=1", "tolerance=0")
    print("verdict=REQUIRES_API_OWNED_ATOMIC_TRANSACTION")


if __name__ == "__main__":
    run(main())
