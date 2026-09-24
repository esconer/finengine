"""C-06 pre-change fixture: heartbeat while a CPU route runs."""
from __future__ import annotations
import asyncio, time
from unittest.mock import AsyncMock, Mock, patch
import pandas as pd
from app.api.analytics import run_optimization
from agent_c_fixture_support import FakeDB, run


async def route():
    async def resolve(*_): return ["A", "B"], {"A": .5, "B": .5}
    async def build(*_): return pd.DataFrame({"A": [0.01, -.01] * 30, "B": [-.01, .01] * 30}), None, {}
    def slow(*args, **kwargs):
        time.sleep(.15)
        return {"weights": {"A": .5, "B": .5}}
    with patch("app.api.analytics.resolve_allocation", side_effect=resolve), \
         patch("app.api.analytics._build_wide_returns", side_effect=build), \
         patch("app.api.analytics.optimize", side_effect=slow):
        return await run_optimization(body={"strategy": "hrp"}, db=FakeDB(), data_service=Mock())


async def main():
    order = []
    async def heartbeat():
        await asyncio.sleep(.02); order.append("heartbeat")
    await asyncio.gather(route(), heartbeat())
    print("before.order", order, "expected_heartbeat_before_route_result", "verdict=REQUIRES_THREAD_OFFLOAD")
    print("tolerance=ordering; no numeric tolerance")


if __name__ == "__main__":
    run(main())
