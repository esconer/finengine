"""
WebSocket API for real-time updates
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from fastapi.websockets import WebSocketState
import logging

from app.services.data_service import GlobalDataService
from app.services.analytics_engine import GlobalAnalyticsEngine
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Create router
router = APIRouter()

# Connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.subscriptions: Dict[str, Set[str]] = {}  # WebSocket -> set of topics

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.subscriptions[client_id] = set()
        logger.info(f"Client {client_id} connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self.subscriptions:
            del self.subscriptions[client_id]
        logger.info(f"Client {client_id} disconnected. Total connections: {len(self.active_connections)}")

    async def send_personal_message(self, message: dict, client_id: str):
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Error sending message to client {client_id}: {e}")
                self.disconnect(client_id)

    async def broadcast(self, message: dict, topic: str = None):
        # Send to all connections subscribed to the topic
        for client_id, subscriptions in self.subscriptions.items():
            if topic is None or topic in subscriptions:
                await self.send_personal_message(message, client_id)

    def subscribe(self, client_id: str, topic: str):
        if client_id in self.subscriptions:
            self.subscriptions[client_id].add(topic)
            logger.info(f"Client {client_id} subscribed to topic: {topic}")

    def unsubscribe(self, client_id: str, topic: str):
        if client_id in self.subscriptions and topic in self.subscriptions[client_id]:
            self.subscriptions[client_id].remove(topic)
            logger.info(f"Client {client_id} unsubscribed from topic: {topic}")

# Global connection manager
manager = ConnectionManager()

# Real-time update background task
update_task = None

async def background_updates():
    """Background task for sending periodic updates"""
    data_service = GlobalDataService()
    analytics_engine = GlobalAnalyticsEngine()
    
    while True:
        try:
            # Send periodic portfolio updates
            await send_portfolio_update()
            
            # Send periodic analytics updates
            await send_analytics_update()
            
            # Send market data updates
            await send_market_data_update()
            
            # Wait 30 seconds between updates
            await asyncio.sleep(30)
            
        except Exception as e:
            logger.error(f"Error in background updates: {e}")
            await asyncio.sleep(5)  # Wait before retry

async def send_portfolio_update():
    """Send portfolio data update"""
    try:
        # Mock portfolio update data
        update_data = {
            "type": "portfolio_update",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "total_value": 100000 + (hash(str(datetime.now())) % 10000),
                "positions": [
                    {"ticker": "AAPL", "weight": 0.25, "value": 25000 + (hash("AAPL") % 1000)},
                    {"ticker": "MSFT", "weight": 0.25, "value": 25000 + (hash("MSFT") % 1000)},
                    {"ticker": "GOOGL", "weight": 0.25, "value": 25000 + (hash("GOOGL") % 1000)},
                    {"ticker": "AMZN", "weight": 0.25, "value": 25000 + (hash("AMZN") % 1000)}
                ]
            }
        }
        await manager.broadcast(update_data, "portfolio")
    except Exception as e:
        logger.error(f"Error sending portfolio update: {e}")

async def send_analytics_update():
    """Send analytics data update"""
    try:
        # Mock analytics update data
        update_data = {
            "type": "analytics_update",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "realized_volatility": 0.20 + (hash(str(datetime.now())) % 100 / 1000),
                "sharpe_ratio": 0.5 + (hash("sharpe") % 100 / 1000),
                "max_drawdown": -0.15 + (hash("drawdown") % 100 / 1000),
                "risk_score": 25 + (hash("risk") % 100 / 10)
            }
        }
        await manager.broadcast(update_data, "analytics")
    except Exception as e:
        logger.error(f"Error sending analytics update: {e}")

async def send_market_data_update():
    """Send market data update"""
    try:
        # Mock market data update
        update_data = {
            "type": "market_data_update",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "AAPL": {
                    "price": 150 + (hash("AAPL_price") % 100) / 10,
                    "change": (hash("AAPL_change") % 200 - 100) / 100,
                    "volume": 1000000 + (hash("AAPL_vol") % 100000)
                },
                "MSFT": {
                    "price": 250 + (hash("MSFT_price") % 100) / 10,
                    "change": (hash("MSFT_change") % 200 - 100) / 100,
                    "volume": 800000 + (hash("MSFT_vol") % 100000)
                },
                "GOOGL": {
                    "price": 100 + (hash("GOOGL_price") % 100) / 10,
                    "change": (hash("GOOGL_change") % 200 - 100) / 100,
                    "volume": 600000 + (hash("GOOGL_vol") % 100000)
                },
                "AMZN": {
                    "price": 80 + (hash("AMZN_price") % 100) / 10,
                    "change": (hash("AMZN_change") % 200 - 100) / 100,
                    "volume": 700000 + (hash("AMZN_vol") % 100000)
                }
            }
        }
        await manager.broadcast(update_data, "market_data")
    except Exception as e:
        logger.error(f"Error sending market data update: {e}")

@router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str, token: str = Query(None)):
    """
    WebSocket endpoint for real-time updates
    """
    await manager.connect(websocket, client_id)
    
    global update_task
    # Start background update task if not already running
    if update_task is None or update_task.done():
        update_task = asyncio.create_task(background_updates())
    
    try:
        while True:
            # Receive messages from client
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Handle subscription messages
            if message.get("type") == "subscribe":
                topic = message.get("topic")
                if topic:
                    manager.subscribe(client_id, topic)
                    await manager.send_personal_message({
                        "type": "subscription_confirmed",
                        "topic": topic,
                        "timestamp": datetime.utcnow().isoformat()
                    }, client_id)
            
            elif message.get("type") == "unsubscribe":
                topic = message.get("topic")
                if topic:
                    manager.unsubscribe(client_id, topic)
                    await manager.send_personal_message({
                        "type": "unsubscription_confirmed",
                        "topic": topic,
                        "timestamp": datetime.utcnow().isoformat()
                    }, client_id)
            
            elif message.get("type") == "ping":
                # Respond to ping with pong
                await manager.send_personal_message({
                    "type": "pong",
                    "timestamp": datetime.utcnow().isoformat()
                }, client_id)
            
    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket error for client {client_id}: {e}")
        manager.disconnect(client_id)

@router.get("/status")
async def websocket_status():
    """
    Get WebSocket connection status
    """
    return {
        "status": "connected",
        "active_connections": len(manager.active_connections),
        "timestamp": datetime.utcnow().isoformat()
    }

@router.post("/broadcast")
async def broadcast_message(
    topic: str,
    message: dict
):
    """
    Broadcast a message to all subscribers of a topic
    """
    message["type"] = "broadcast"
    message["topic"] = topic
    message["timestamp"] = datetime.utcnow().isoformat()
    
    await manager.broadcast(message, topic)
    
    return {
        "status": "broadcast_sent",
        "topic": topic,
        "connections": len(manager.active_connections)
    }