"""
WebSocket tests.

Two layers:
- Unit: ConnectionManager with mocked sockets (async).
- Protocol: real server over TestClient in SYNC tests - driving the sync
  TestClient from inside an asyncio test deadlocks its portal, and the
  server is silent on connect, so every receive must follow a send.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.websocket import ConnectionManager, background_updates


# ---------------------------------------------------------------------------
# Unit: ConnectionManager


@pytest.fixture
def connection_manager():
    return ConnectionManager()


@pytest.mark.asyncio
class TestConnectionManager:
    async def test_connect_accepts_and_registers(self, connection_manager):
        ws = AsyncMock()
        await connection_manager.connect(ws, "client1")
        ws.accept.assert_awaited_once()
        assert connection_manager.active_connections["client1"] is ws
        assert connection_manager.subscriptions["client1"] == set()

    async def test_disconnect_removes_state(self, connection_manager):
        await connection_manager.connect(AsyncMock(), "client1")
        connection_manager.disconnect("client1")
        assert "client1" not in connection_manager.active_connections
        assert "client1" not in connection_manager.subscriptions

    async def test_subscribe_unsubscribe(self, connection_manager):
        await connection_manager.connect(AsyncMock(), "client1")
        connection_manager.subscribe("client1", "portfolio")
        assert "portfolio" in connection_manager.subscriptions["client1"]
        connection_manager.unsubscribe("client1", "portfolio")
        assert "portfolio" not in connection_manager.subscriptions["client1"]
        # unknown topic/client must not raise
        connection_manager.unsubscribe("client1", "nope")

    async def test_send_personal_message(self, connection_manager):
        ws = AsyncMock()
        await connection_manager.connect(ws, "client1")
        await connection_manager.send_personal_message({"type": "pong"}, "client1")
        ws.send_text.assert_awaited_once()
        assert '"type": "pong"' in ws.send_text.await_args.args[0]

    async def test_broadcast_topic_filtering(self, connection_manager):
        ws_a, ws_b = AsyncMock(), AsyncMock()
        await connection_manager.connect(ws_a, "a")
        await connection_manager.connect(ws_b, "b")
        connection_manager.subscribe("a", "analytics")

        await connection_manager.broadcast({"type": "x"}, topic="analytics")
        assert ws_a.send_text.await_count == 1
        assert ws_b.send_text.await_count == 0

        await connection_manager.broadcast({"type": "y"})  # no topic -> all
        assert ws_a.send_text.await_count == 2
        assert ws_b.send_text.await_count == 1


# ---------------------------------------------------------------------------
# Protocol: against the live app


@pytest.fixture
def client():
    from main import app

    with TestClient(app) as c:
        yield c


def _subscribe(ws, topic="portfolio"):
    ws.send_json({"type": "subscribe", "topic": topic})
    msg = ws.receive_json()
    assert msg["type"] == "subscription_confirmed"
    assert msg["topic"] == topic


@pytest.mark.websocket
class TestWebSocketEndpoint:
    def test_connect_subscribe_receive_confirmation(self, client):
        with client.websocket_connect("/api/v1/ws/ws/t1") as ws:
            _subscribe(ws, "portfolio")

    def test_unsubscribe_flow(self, client):
        with client.websocket_connect("/api/v1/ws/ws/t2") as ws:
            _subscribe(ws, "market_data")
            ws.send_json({"type": "unsubscribe", "topic": "market_data"})
            msg = ws.receive_json()
            assert msg["type"] == "unsubscription_confirmed"
            assert msg["topic"] == "market_data"

    def test_ping_pong(self, client):
        with client.websocket_connect("/api/v1/ws/ws/t3") as ws:
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"

    def test_invalid_type_then_connection_still_alive(self, client):
        with client.websocket_connect("/api/v1/ws/ws/t4") as ws:
            ws.send_json({"type": "mystery"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"

    def test_malformed_json_closes_connection(self, client):
        with client.websocket_connect("/api/v1/ws/ws/t5") as ws:
            ws.send_text("this-is-not-json")
            # server treats the parse failure as fatal for the socket
            with pytest.raises(Exception):
                ws.receive_json(timeout=5)

    def test_multiple_clients_topic_isolation(self, client):
        with client.websocket_connect("/api/v1/ws/ws/t6a") as ws_a, \
             client.websocket_connect("/api/v1/ws/ws/t6b") as ws_b:
            _subscribe(ws_a, "shared")
            _subscribe(ws_b, "other")

            resp = client.post(
                "/api/v1/ws/broadcast",
                params={"topic": "shared"},
                json={"hello": "world"},
            )
            assert resp.status_code == 200

            got = ws_a.receive_json()
            assert got["type"] == "broadcast" and got["hello"] == "world"
            # b hears nothing on its topic; verify liveness instead
            ws_b.send_json({"type": "ping"})
            assert ws_b.receive_json()["type"] == "pong"

    def test_rapid_subscription_changes(self, client):
        with client.websocket_connect("/api/v1/ws/ws/t7") as ws:
            for i in range(10):
                _subscribe(ws, f"topic{i}")
                ws.send_json({"type": "unsubscribe", "topic": f"topic{i}"})
                assert ws.receive_json()["type"] == "unsubscription_confirmed"


# ---------------------------------------------------------------------------
# Background worker


@pytest.mark.asyncio
class TestBackgroundWorker:
    async def test_cycle_calls_all_senders_then_sleeps(self, monkeypatch):
        import app.api.websocket as ws_mod

        senders = [AsyncMock() for _ in range(3)]
        monkeypatch.setattr(ws_mod, "send_portfolio_update", senders[0])
        monkeypatch.setattr(ws_mod, "send_analytics_update", senders[1])
        monkeypatch.setattr(ws_mod, "send_market_data_update", senders[2])

        sleeps = []

        async def fake_sleep(_seconds):
            sleeps.append(_seconds)
            raise asyncio.CancelledError()  # exit loop after first cycle

        monkeypatch.setattr(ws_mod.asyncio, "sleep", fake_sleep)

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(background_updates(), timeout=2)

        assert all(s.await_count == 1 for s in senders)
        assert sleeps == [30]
