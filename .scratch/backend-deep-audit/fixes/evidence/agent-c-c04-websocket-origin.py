"""C-04 pre-change fixture: WebSocket handshake trust boundary."""
from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock
from app.api.websocket import ConnectionManager
from agent_c_fixture_support import run


async def main():
    ws = AsyncMock()
    ws.headers = {"host": "evil.example", "origin": "https://evil.example"}
    manager = ConnectionManager()
    accepted = await manager.connect(ws, "c1")
    print("before.accepted", accepted, "accept_awaited", ws.accept.await_count, "close_awaited", ws.close.await_count)
    print("verdict=REQUIRES_PRE_ACCEPT_ORIGIN_HOST_REJECTION")


if __name__ == "__main__":
    run(main())
