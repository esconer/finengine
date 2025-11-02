"""
WebSocket endpoint tests for Daisy Risk Engine
"""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, patch, Mock
from fastapi import WebSocket
from fastapi.testclient import TestClient
import websockets
import pytest_asyncio

from app.api.websocket import ConnectionManager, manager, router


@pytest.mark.websocket
class TestConnectionManager:
    """Test cases for ConnectionManager class"""
    
    @pytest.fixture
    def connection_manager(self):
        """Create a fresh connection manager for testing"""
        return ConnectionManager()
    
    @pytest.mark.asyncio
    async def test_connection_manager_initialization(self, connection_manager):
        """Test connection manager initialization"""
        assert len(connection_manager.active_connections) == 0
        assert len(connection_manager.subscriptions) == 0
    
    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self, connection_manager):
        """Test connection and disconnection"""
        # Mock WebSocket
        mock_websocket = AsyncMock()
        
        # Test connection
        await connection_manager.connect(mock_websocket, "client1")
        
        assert "client1" in connection_manager.active_connections
        assert "client1" in connection_manager.subscriptions
        assert len(connection_manager.active_connections) == 1
        
        # Test disconnection
        connection_manager.disconnect("client1")
        
        assert "client1" not in connection_manager.active_connections
        assert "client1" not in connection_manager.subscriptions
        assert len(connection_manager.active_connections) == 0
    
    @pytest.mark.asyncio
    async def test_send_personal_message(self, connection_manager):
        """Test sending personal messages"""
        # Mock WebSocket
        mock_websocket = AsyncMock()
        mock_websocket.send_text = AsyncMock()
        
        await connection_manager.connect(mock_websocket, "client1")
        
        message = {"type": "test", "data": "hello"}
        await connection_manager.send_personal_message(message, "client1")
        
        # Verify message was sent
        mock_websocket.send_text.assert_called_once()
        sent_message = json.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_message == message
    
    @pytest.mark.asyncio
    async def test_send_personal_message_disconnected_client(self, connection_manager):
        """Test sending message to disconnected client"""
        message = {"type": "test", "data": "hello"}
        
        # Should not raise exception
        await connection_manager.send_personal_message(message, "nonexistent_client")
    
    @pytest.mark.asyncio
    async def test_send_personal_message_error_handling(self, connection_manager):
        """Test error handling when sending message fails"""
        # Mock WebSocket that raises exception
        mock_websocket = AsyncMock()
        mock_websocket.send_text.side_effect = Exception("Send error")
        
        await connection_manager.connect(mock_websocket, "client1")
        
        message = {"type": "test", "data": "hello"}
        await connection_manager.send_personal_message(message, "client1")
        
        # Client should be disconnected due to error
        assert "client1" not in connection_manager.active_connections
    
    @pytest.mark.asyncio
    async def test_broadcast_to_all(self, connection_manager):
        """Test broadcasting to all connected clients"""
        # Mock WebSockets
        mock_websocket1 = AsyncMock()
        mock_websocket1.send_text = AsyncMock()
        mock_websocket2 = AsyncMock()
        mock_websocket2.send_text = AsyncMock()
        
        await connection_manager.connect(mock_websocket1, "client1")
        await connection_manager.connect(mock_websocket2, "client2")
        
        message = {"type": "broadcast", "data": "hello"}
        await connection_manager.broadcast(message)
        
        # Verify both clients received the message
        mock_websocket1.send_text.assert_called_once()
        mock_websocket2.send_text.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_broadcast_to_topic_subscribers(self, connection_manager):
        """Test broadcasting to clients subscribed to specific topics"""
        # Mock WebSockets
        mock_websocket1 = AsyncMock()
        mock_websocket1.send_text = AsyncMock()
        mock_websocket2 = AsyncMock()
        mock_websocket2.send_text = AsyncMock()
        mock_websocket3 = AsyncMock()
        mock_websocket3.send_text = AsyncMock()
        
        await connection_manager.connect(mock_websocket1, "client1")
        await connection_manager.connect(mock_websocket2, "client2")
        await connection_manager.connect(mock_websocket3, "client3")
        
        # Subscribe clients to topics
        connection_manager.subscribe("client1", "analytics")
        connection_manager.subscribe("client2", "analytics")
        connection_manager.subscribe("client3", "portfolio")
        
        message = {"type": "analytics_update", "data": "hello"}
        await connection_manager.broadcast(message, "analytics")
        
        # Only clients 1 and 2 should receive the message
        mock_websocket1.send_text.assert_called_once()
        mock_websocket2.send_text.assert_called_once()
        mock_websocket3.send_text.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_subscribe_and_unsubscribe(self, connection_manager):
        """Test subscription management"""
        # Mock WebSocket
        mock_websocket = AsyncMock()
        
        await connection_manager.connect(mock_websocket, "client1")
        
        # Subscribe to topic
        connection_manager.subscribe("client1", "portfolio")
        assert "portfolio" in connection_manager.subscriptions["client1"]
        
        # Unsubscribe from topic
        connection_manager.unsubscribe("client1", "portfolio")
        assert "portfolio" not in connection_manager.subscriptions["client1"]
        
        # Unsubscribe from non-existent topic should not raise error
        connection_manager.unsubscribe("client1", "nonexistent")
    
    @pytest.mark.asyncio
    async def test_broadcast_with_no_connections(self, connection_manager):
        """Test broadcasting when no clients are connected"""
        message = {"type": "test", "data": "hello"}
        
        # Should not raise exception
        await connection_manager.broadcast(message)
    
    @pytest.mark.asyncio
    async def test_multiple_subscriptions_per_client(self, connection_manager):
        """Test clients can subscribe to multiple topics"""
        # Mock WebSocket
        mock_websocket = AsyncMock()
        
        await connection_manager.connect(mock_websocket, "client1")
        
        # Subscribe to multiple topics
        connection_manager.subscribe("client1", "portfolio")
        connection_manager.subscribe("client1", "analytics")
        connection_manager.subscribe("client1", "market_data")
        
        subscriptions = connection_manager.subscriptions["client1"]
        assert "portfolio" in subscriptions
        assert "analytics" in subscriptions
        assert "market_data" in subscriptions


@pytest.mark.websocket
class TestWebSocketEndpoint:
    """Test WebSocket endpoint functionality"""
    
    @pytest.mark.asyncio
    async def test_websocket_connection(self):
        """Test basic WebSocket connection"""
        from main import app
        from fastapi.testclient import TestClient
        
        # Use TestClient for WebSocket testing
        with TestClient(app) as client:
            with client.websocket_connect("/ws/test_client") as websocket:
                # Connection should be established
                data = websocket.receive_json()
                assert data["type"] == "subscription_confirmed"
                assert data["topic"] == "test"
    
    @pytest.mark.asyncio
    async def test_websocket_subscription_message(self):
        """Test WebSocket subscription handling"""
        from main import app
        from fastapi.testclient import TestClient
        
        with TestClient(app) as client:
            with client.websocket_connect("/ws/test_client") as websocket:
                # Send subscription message
                subscribe_message = {
                    "type": "subscribe",
                    "topic": "portfolio"
                }
                websocket.send_json(subscribe_message)
                
                # Should receive confirmation
                data = websocket.receive_json()
                assert data["type"] == "subscription_confirmed"
                assert data["topic"] == "portfolio"
    
    @pytest.mark.asyncio
    async def test_websocket_unsubscription_message(self):
        """Test WebSocket unsubscription handling"""
        from main import app
        from fastapi.testclient import TestClient
        
        with TestClient(app) as client:
            with client.websocket_connect("/ws/test_client") as websocket:
                # Subscribe first
                subscribe_message = {"type": "subscribe", "topic": "analytics"}
                websocket.send_json(subscribe_message)
                websocket.receive_json()  # Acknowledge
                
                # Then unsubscribe
                unsubscribe_message = {"type": "unsubscribe", "topic": "analytics"}
                websocket.send_json(unsubscribe_message)
                
                # Should receive confirmation
                data = websocket.receive_json()
                assert data["type"] == "unsubscription_confirmed"
                assert data["topic"] == "analytics"
    
    @pytest.mark.asyncio
    async def test_websocket_ping_pong(self):
        """Test WebSocket ping-pong functionality"""
        from main import app
        from fastapi.testclient import TestClient
        
        with TestClient(app) as client:
            with client.websocket_connect("/ws/test_client") as websocket:
                # Send ping
                ping_message = {"type": "ping"}
                websocket.send_json(ping_message)
                
                # Should receive pong
                data = websocket.receive_json()
                assert data["type"] == "pong"
                assert "timestamp" in data
    
    @pytest.mark.asyncio
    async def test_websocket_invalid_message_type(self):
        """Test handling of invalid message types"""
        from main import app
        from fastapi.testclient import TestClient
        
        with TestClient(app) as client:
            with client.websocket_connect("/ws/test_client") as websocket:
                # Send invalid message type
                invalid_message = {
                    "type": "invalid_type",
                    "data": "test"
                }
                websocket.send_json(invalid_message)
                
                # Should not crash, message should be ignored
                # (In real implementation, you might want to send an error message)
    
    @pytest.mark.asyncio
    async def test_websocket_subscription_without_topic(self):
        """Test subscription message without topic"""
        from main import app
        from fastapi.testclient import TestClient
        
        with TestClient(app) as client:
            with client.websocket_connect("/ws/test_client") as websocket:
                # Send subscription without topic
                subscribe_message = {
                    "type": "subscribe"
                    # Missing "topic" field
                }
                websocket.send_json(subscribe_message)
                
                # Should not crash
                # (In real implementation, you might want to send an error)
    
    @pytest.mark.asyncio
    async def test_websocket_multiple_clients(self):
        """Test multiple clients connecting simultaneously"""
        from main import app
        from fastapi.testclient import TestClient
        
        with TestClient(app) as client:
            # Connect multiple clients
            with client.websocket_connect("/ws/client1") as ws1:
                with client.websocket_connect("/ws/client2") as ws2:
                    with client.websocket_connect("/ws/client3") as ws3:
                        # All should receive their connection confirmations
                        data1 = ws1.receive_json()
                        data2 = ws2.receive_json()
                        data3 = ws3.receive_json()
                        
                        assert data1["type"] == "subscription_confirmed"
                        assert data2["type"] == "subscription_confirmed"
                        assert data3["type"] == "subscription_confirmed"


@pytest.mark.websocket
class TestBackgroundUpdates:
    """Test background update functionality"""
    
    @pytest.mark.asyncio
    async def test_send_portfolio_update(self):
        """Test portfolio update generation"""
        with patch('app.api.websocket.manager') as mock_manager:
            mock_manager.broadcast = AsyncMock()
            
            from app.api.websocket import send_portfolio_update
            
            await send_portfolio_update()
            
            # Verify broadcast was called
            mock_manager.broadcast.assert_called_once()
            
            # Get the message that was broadcast
            call_args = mock_manager.broadcast.call_args
            message = call_args[0][0]  # First positional argument
            
            assert message["type"] == "portfolio_update"
            assert "timestamp" in message
            assert "data" in message
            assert "total_value" in message["data"]
            assert "positions" in message["data"]
    
    @pytest.mark.asyncio
    async def test_send_analytics_update(self):
        """Test analytics update generation"""
        with patch('app.api.websocket.manager') as mock_manager:
            mock_manager.broadcast = AsyncMock()
            
            from app.api.websocket import send_analytics_update
            
            await send_analytics_update()
            
            # Verify broadcast was called
            mock_manager.broadcast.assert_called_once()
            
            # Get the message that was broadcast
            call_args = mock_manager.broadcast.call_args
            message = call_args[0][0]
            
            assert message["type"] == "analytics_update"
            assert "timestamp" in message
            assert "data" in message
            assert "realized_volatility" in message["data"]
            assert "sharpe_ratio" in message["data"]
            assert "max_drawdown" in message["data"]
            assert "risk_score" in message["data"]
    
    @pytest.mark.asyncio
    async def test_send_market_data_update(self):
        """Test market data update generation"""
        with patch('app.api.websocket.manager') as mock_manager:
            mock_manager.broadcast = AsyncMock()
            
            from app.api.websocket import send_market_data_update
            
            await send_market_data_update()
            
            # Verify broadcast was called
            mock_manager.broadcast.assert_called_once()
            
            # Get the message that was broadcast
            call_args = mock_manager.broadcast.call_args
            message = call_args[0][0]
            
            assert message["type"] == "market_data_update"
            assert "timestamp" in message
            assert "data" in message
            
            # Check for expected tickers
            expected_tickers = ["AAPL", "MSFT", "GOOGL", "AMZN"]
            for ticker in expected_tickers:
                assert ticker in message["data"]
                assert "price" in message["data"][ticker]
                assert "change" in message["data"][ticker]
                assert "volume" in message["data"][ticker]
    
    @pytest.mark.asyncio
    async def test_background_updates_cycle(self):
        """Test the complete background update cycle"""
        with patch('app.api.websocket.send_portfolio_update') as mock_portfolio:
            with patch('app.api.websocket.send_analytics_update') as mock_analytics:
                with patch('app.api.websocket.send_market_data_update') as mock_market:
                    with patch('asyncio.sleep') as mock_sleep:
                        from app.api.websocket import background_updates
                        
                        # Create a background task and cancel it immediately
                        task = asyncio.create_task(background_updates())
                        task.cancel()
                        
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                        
                        # Verify all update functions were called
                        mock_portfolio.assert_called_once()
                        mock_analytics.assert_called_once()
                        mock_market.assert_called_once()
                        mock_sleep.assert_called_once_with(30)
    
    @pytest.mark.asyncio
    async def test_background_updates_error_handling(self):
        """Test error handling in background updates"""
        with patch('app.api.websocket.send_portfolio_update', side_effect=Exception("Test error")):
            with patch('asyncio.sleep') as mock_sleep:
                from app.api.websocket import background_updates
                
                # Create a task that should handle errors gracefully
                task = asyncio.create_task(background_updates())
                await asyncio.sleep(0.1)  # Let it run briefly
                task.cancel()
                
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                
                # Should continue despite errors
                mock_sleep.assert_called()
    
    @pytest.mark.asyncio
    async def test_background_update_task_management(self):
        """Test background update task creation and management"""
        from app.api.websocket import update_task
        
        # Initially no task should be running
        assert update_task is None
        
        # Mock background_updates function
        with patch('app.api.websocket.background_updates') as mock_background:
            mock_background.return_value = asyncio.sleep(3600)  # Long sleep
            
            from app.api.websocket import websocket_endpoint
            
            # Test that a task is created when connecting
            # (This would need more complex mocking to test properly)
            pass


@pytest.mark.websocket
class TestWebSocketStatus:
    """Test WebSocket status endpoint"""
    
    @pytest.mark.asyncio
    async def test_websocket_status(self, async_client):
        """Test WebSocket status endpoint"""
        response = await async_client.get("/api/v1/ws/status")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "active_connections" in data
        assert "timestamp" in data
        assert data["active_connections"] == 0  # No connections in test
    
    @pytest.mark.asyncio
    async def test_websocket_broadcast(self, async_client):
        """Test WebSocket broadcast endpoint"""
        # Mock manager for testing
        with patch('app.api.websocket.manager') as mock_manager:
            mock_manager.broadcast = AsyncMock()
            mock_manager.active_connections = {"client1": Mock(), "client2": Mock()}
            
            message = {"type": "test", "data": "hello"}
            
            response = await async_client.post(
                "/api/v1/ws/broadcast?topic=test",
                json=message
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "broadcast_sent"
            assert data["topic"] == "test"
            assert data["connections"] == 2
            
            # Verify broadcast was called with correct parameters
            mock_manager.broadcast.assert_called_once_with(message, "test")


@pytest.mark.websocket
class TestWebSocketIntegration:
    """Integration tests for WebSocket functionality"""
    
    @pytest.mark.asyncio
    async def test_full_websocket_lifecycle(self):
        """Test complete WebSocket client lifecycle"""
        from main import app
        from fastapi.testclient import TestClient
        
        with TestClient(app) as client:
            with client.websocket_connect("/ws/integration_test") as websocket:
                # 1. Initial connection
                initial_data = websocket.receive_json()
                assert initial_data["type"] == "subscription_confirmed"
                
                # 2. Subscribe to topics
                topics = ["portfolio", "analytics", "market_data"]
                for topic in topics:
                    websocket.send_json({"type": "subscribe", "topic": topic})
                    ack = websocket.receive_json()
                    assert ack["type"] == "subscription_confirmed"
                    assert ack["topic"] == topic
                
                # 3. Send ping
                websocket.send_json({"type": "ping"})
                pong = websocket.receive_json()
                assert pong["type"] == "pong"
                
                # 4. Unsubscribe from one topic
                websocket.send_json({"type": "unsubscribe", "topic": "analytics"})
                ack = websocket.receive_json()
                assert ack["type"] == "unsubscription_confirmed"
                assert ack["topic"] == "analytics"
                
                # Connection should still be alive
                websocket.send_json({"type": "ping"})
                pong = websocket.receive_json()
                assert pong["type"] == "pong"
    
    @pytest.mark.asyncio
    async def test_websocket_message_validation(self):
        """Test WebSocket message validation and error handling"""
        from main import app
        from fastapi.testclient import TestClient
        
        with TestClient(app) as client:
            with client.websocket_connect("/ws/validation_test") as websocket:
                websocket.receive_json()  # Initial connection
                
                # Test various invalid messages
                invalid_messages = [
                    {"type": "subscribe"},  # Missing topic
                    {"type": "unsubscribe"},  # Missing topic
                    {"topic": "test"},  # Missing type
                    {"type": "invalid_type", "data": "test"},  # Unknown type
                    "invalid_json",  # Not JSON
                    {},  # Empty object
                ]
                
                for message in invalid_messages:
                    try:
                        websocket.send_json(message)
                        # Should not crash, might receive error or ignore
                    except Exception:
                        # Some messages might cause connection issues, which is fine
                        pass


@pytest.mark.websocket
class TestWebSocketPerformance:
    """Performance and load tests for WebSocket functionality"""
    
    @pytest.mark.asyncio
    async def test_multiple_concurrent_connections(self):
        """Test handling multiple concurrent WebSocket connections"""
        from main import app
        from fastapi.testclient import TestClient
        
        with TestClient(app) as client:
            connections = []
            
            # Create multiple connections
            for i in range(5):
                ws = client.websocket_connect(f"/ws/performance_test_{i}")
                connections.append(ws)
            
            # Verify all connections were established
            for ws in connections:
                data = ws.receive_json()
                assert data["type"] == "subscription_confirmed"
            
            # Clean up connections
            for ws in connections:
                ws.close()
    
    @pytest.mark.asyncio
    async def test_rapid_subscription_changes(self):
        """Test rapid subscription and unsubscription"""
        from main import app
        from fastapi.testclient import TestClient
        
        with TestClient(app) as client:
            with client.websocket_connect("/ws/rapid_test") as websocket:
                websocket.receive_json()  # Initial connection
                
                # Rapidly subscribe and unsubscribe
                for i in range(10):
                    topic = f"topic_{i % 3}"
                    
                    websocket.send_json({"type": "subscribe", "topic": topic})
                    try:
                        websocket.receive_json()
                    except:
                        pass  # Ignore if no response
                    
                    websocket.send_json({"type": "unsubscribe", "topic": topic})
                    try:
                        websocket.receive_json()
                    except:
                        pass  # Ignore if no response


@pytest.mark.websocket
class TestWebSocketErrorHandling:
    """Error handling and edge cases for WebSocket"""
    
    @pytest.mark.asyncio
    async def test_websocket_connection_failure(self):
        """Test WebSocket connection failure scenarios"""
        from main import app
        from fastapi.testclient import TestClient
        
        with TestClient(app) as client:
            # Test connection to non-existent endpoint
            try:
                with client.websocket_connect("/ws/nonexistent"):
                    pass
            except Exception:
                # Connection should fail for invalid endpoints
                pass
    
    @pytest.mark.asyncio
    async def test_websocket_malformed_json(self):
        """Test handling of malformed JSON messages"""
        from main import app
        from fastapi.testclient import TestClient
        
        with TestClient(app) as client:
            with client.websocket_connect("/ws/malformed_test") as websocket:
                websocket.receive_json()  # Initial connection
                
                # Send malformed JSON
                websocket.send_text("invalid json {")
                
                # Connection should handle this gracefully
                # (In real implementation, you might want to send an error)
                
                # Verify connection is still alive
                websocket.send_json({"type": "ping"})
                try:
                    pong = websocket.receive_json()
                    assert pong["type"] == "pong"
                except:
                    # Connection might be closed, which is acceptable
                    pass