"""C-11 pre-change fixture: internal exception text must not cross HTTP boundary."""
from __future__ import annotations
from unittest.mock import AsyncMock, Mock
from fastapi import HTTPException
from app.api import data as data_mod
from agent_c_fixture_support import FakeDB, run


async def main():
    db = FakeDB()
    async def fail(*_): raise RuntimeError("provider=https://secret.example?api_key=DO_NOT_LOG")
    db.commit = fail
    try:
        await data_mod.update_api_config(primary_source=None, cache_ttl_minutes=10, enable_cache=True, db=db, cache_service=Mock())
        print("before.status", 200)
    except HTTPException as exc:
        print("before.status", exc.status_code, "detail", exc.detail)
    print("verdict=REQUIRES_STABLE_REDACTED_ERROR")


if __name__ == "__main__":
    run(main())
