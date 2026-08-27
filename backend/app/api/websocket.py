"""
WebSocket API for real-time updates
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from fastapi.websockets import WebSocketState
import logging

from sqlalchemy import select
import pandas as pd

from app.db.database import SessionLocal
from app.models.database import PortfolioPosition, StockTimeseries
from app.services.analytics_engine import AnalyticsEngine
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
    """Background task for sending periodic updates."""
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
    """Send portfolio data update from database"""
    try:
        async with SessionLocal() as db:
            result = await db.execute(select(PortfolioPosition))
            positions = result.scalars().all()
            
            total_value = 0.0
            pos_list = []
            for p in positions:
                mv = p.market_value or ((p.quantity or 0.0) * (p.last_price or 0.0))
                total_value += mv
                pos_list.append({
                    "ticker": p.ticker,
                    "weight": round(float(p.weight or 0.0), 4),
                    "value": round(float(mv), 2),
                    "quantity": p.quantity or 0.0,
                    "last_price": p.last_price or 0.0,
                })
            
            update_data = {
                "type": "portfolio_update",
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    "total_value": round(float(total_value), 2),
                    "positions": pos_list
                }
            }
            await manager.broadcast(update_data, "portfolio")
    except Exception as e:
        logger.error(f"Error sending portfolio update: {e}")

async def send_analytics_update():
    """Send analytics data update from database"""
    try:
        async with SessionLocal() as db:
            result = await db.execute(select(PortfolioPosition))
            positions = result.scalars().all()
            if not positions:
                return

            tickers = [p.ticker for p in positions]
            weights = {p.ticker: (p.weight or 0.0) for p in positions}
            w_sum = sum(weights.values())
            if w_sum > 0:
                weights = {k: v / w_sum for k, v in weights.items()}
            else:
                weights = {t: 1.0 / len(tickers) for t in tickers}

            # Lookback limited to 1 year (~252 trading days) to prevent unbounded memory growth
            cutoff_date = datetime.utcnow().date() - timedelta(days=365)
            t_res = await db.execute(
                select(StockTimeseries)
                .where(
                    StockTimeseries.ticker.in_(tickers),
                    StockTimeseries.date >= cutoff_date
                )
                .order_by(StockTimeseries.date.asc())
            )
            rows = t_res.scalars().all()

            realized_vol = 0.0
            sharpe = 0.0
            max_dd = 0.0

            if rows:
                data_dict = {}
                for r in rows:
                    data_dict.setdefault(r.ticker, {})[r.date] = r.adj_close or r.close
                price_df = pd.DataFrame(data_dict).dropna()
                if not price_df.empty and len(price_df) > 5:
                    engine = AnalyticsEngine()
                    metrics = await engine.calculate_portfolio_metrics(price_df, weights)
                    realized_vol = metrics.get("annual_volatility", 0.0)
                    sharpe = metrics.get("sharpe_ratio", 0.0)
                    max_dd = metrics.get("max_drawdown", 0.0)

            update_data = {
                "type": "analytics_update",
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    "realized_volatility": round(float(realized_vol), 4),
                    "sharpe_ratio": round(float(sharpe), 4),
                    "max_drawdown": round(float(max_dd), 4),
                    "positions_count": len(positions)
                }
            }
            await manager.broadcast(update_data, "analytics")
    except Exception as e:
        logger.error(f"Error sending analytics update: {e}")

async def send_market_data_update():
    """Send market data update from database using a single batched query"""
    try:
        async with SessionLocal() as db:
            result = await db.execute(select(PortfolioPosition))
            positions = result.scalars().all()
            if not positions:
                return

            tickers = [p.ticker for p in positions]
            # Fetch recent timeseries for all portfolio tickers in a single batched query
            cutoff_date = datetime.utcnow().date() - timedelta(days=14)
            t_res = await db.execute(
                select(StockTimeseries)
                .where(
                    StockTimeseries.ticker.in_(tickers),
                    StockTimeseries.date >= cutoff_date
                )
                .order_by(StockTimeseries.ticker, StockTimeseries.date.desc())
            )
            all_ts_rows = t_res.scalars().all()
            ts_by_ticker = {}
            for r in all_ts_rows:
                ts_by_ticker.setdefault(r.ticker, []).append(r)

            market_dict = {}
            for p in positions:
                ts_rows = ts_by_ticker.get(p.ticker, [])
                price = p.last_price or 0.0
                change = 0.0
                volume = 0
                if ts_rows:
                    price = ts_rows[0].close
                    volume = ts_rows[0].volume
                    if len(ts_rows) > 1 and ts_rows[1].close:
                        change = (ts_rows[0].close - ts_rows[1].close) / ts_rows[1].close * 100.0

                market_dict[p.ticker] = {
                    "price": round(float(price), 2),
                    "change": round(float(change), 2),
                    "volume": int(volume)
                }

            update_data = {
                "type": "market_data_update",
                "timestamp": datetime.utcnow().isoformat(),
                "data": market_dict
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