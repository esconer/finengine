"""C-07 pre-change fixture: non-finite and oversized body before solver/vendor."""
from __future__ import annotations
from unittest.mock import AsyncMock, Mock, patch
from fastapi import HTTPException
from app.api.analytics import run_optimization
from agent_c_fixture_support import FakeDB, run


async def main():
    calls = []
    async def resolve(*_):
        calls.append("resolve"); return ["A", "B"], {"A": .5, "B": .5}
    with patch("app.api.analytics.resolve_allocation", side_effect=resolve):
        try:
            await run_optimization(body={"strategy": "hrp", "risk_free_rate": float("nan")}, db=FakeDB(), data_service=Mock())
            print("before.nonfinite_status", 200)
        except HTTPException as exc:
            print("before.nonfinite_status", exc.status_code, "resolve_calls", calls)
    print("verdict=REQUIRES_PRE_SOLVER_422_AND_BOUNDS")


if __name__ == "__main__":
    run(main())
