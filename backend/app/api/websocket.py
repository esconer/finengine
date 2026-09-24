"""
WebSocket API for real-time updates
"""

import asyncio
import json
from contextlib import suppress
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Dict, Set
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from sqlalchemy import select
import numpy as np
import pandas as pd

from app.config import settings
from app.db.database import SessionLocal
from app.models.database import PortfolioPosition, StockTimeseries
from app.services.analytics_engine import AnalyticsEngine
from app.services.cache_service import ProviderError
from app.services.currency_service import (
    CurrencyUnavailableError,
    coerce_live_fx_rate,
    get_currency_service,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

_WEBSOCKET_SEND_TIMEOUT_SECONDS = 5.0

# Create router
router = APIRouter()

# Connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.subscriptions: Dict[str, Set[str]] = {}  # WebSocket -> set of topics

    async def connect(self, websocket: WebSocket, client_id: str) -> bool:
        if not _trusted_websocket(websocket):
            await _reject_websocket(websocket)
            return False
        if client_id in self.active_connections:
            logger.warning(f"Client {client_id} rejected: id already connected")
            await websocket.close(code=1008)
            return False
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.subscriptions[client_id] = set()
        logger.info(f"Client {client_id} connected. Total connections: {len(self.active_connections)}")
        return True

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self.subscriptions:
            del self.subscriptions[client_id]
        logger.info(f"Client {client_id} disconnected. Total connections: {len(self.active_connections)}")

    async def send_personal_message(self, message: dict, client_id: str):
        if client_id in self.active_connections:
            try:
                await asyncio.wait_for(
                    self.active_connections[client_id].send_text(json.dumps(message)),
                    timeout=_WEBSOCKET_SEND_TIMEOUT_SECONDS,
                )
            except Exception:
                logger.error("WebSocket message send failed")
                self.disconnect(client_id)

    async def broadcast(self, message: dict, topic: str = None):
        # Snapshot: send_personal_message may disconnect (mutating subscriptions)
        # mid-iteration, which raised RuntimeError on the live dict.  Independent
        # clients are sent concurrently so one backpressured socket cannot stall
        # the rest of the local dashboard.
        recipients = [
            client_id
            for client_id, subscriptions in list(self.subscriptions.items())
            if topic is None or topic in subscriptions
        ]
        if recipients:
            await asyncio.gather(
                *(self.send_personal_message(message, client_id) for client_id in recipients),
                return_exceptions=True,
            )

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


_DEFAULT_FRONTEND_ORIGINS = frozenset({
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
})


def _header_value(source: object, name: str) -> str | None:
    headers = getattr(source, "headers", None)
    if isinstance(headers, Mapping):
        value = headers.get(name)
        return value if isinstance(value, str) else None
    return None


def _safe_local_host(host: str | None) -> bool:
    if not host:
        return False
    try:
        parsed = urlsplit(f"//{host}")
        hostname = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
        if parsed.username is not None or parsed.password is not None or parsed.path or parsed.query or parsed.fragment:
            return False
    except ValueError:
        return False
    if port is not None and not 1 <= port <= 65535:
        return False
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return True
    # Starlette's in-process TestClient uses testserver.  Keep it out of the
    # production posture while allowing the repository's hermetic protocol
    # tests to exercise the real handshake.
    return hostname == "testserver" and settings.environment != "production"


def _origin_allowed(origin: str | None) -> bool:
    # Non-browser local clients may omit Origin; Host is still mandatory.
    if origin is None:
        return True
    if origin.strip().lower() == "null":
        return False
    try:
        parsed = urlsplit(origin.strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.path or parsed.query or parsed.fragment or parsed.username is not None or parsed.password is not None:
        return False
    normalized = f"{parsed.scheme}://{parsed.netloc}".rstrip("/").lower()
    configured = {
        str(value).strip().rstrip("/").lower()
        for value in getattr(settings, "allowed_origins", [])
        if isinstance(value, str)
    }
    allowed = set(_DEFAULT_FRONTEND_ORIGINS) | configured
    if settings.environment != "production":
        allowed.add("http://testserver")
    return normalized in allowed


def _ws_position_currency(position: object) -> str:
    for attr in ("currency", "position_currency", "quote_currency", "_quote_currency"):
        value = getattr(position, attr, None)
        if isinstance(value, str) and value.strip():
            code = value.strip().upper()
            if code in {"INR", "USD"}:
                return code
            raise ProviderError("Unsupported position currency", provider="portfolio")
    ticker = str(getattr(position, "ticker", "")).upper()
    region = str(getattr(position, "region", "")).upper()
    return "INR" if ticker.endswith((".NS", ".BO")) or region in {"IN", "IND", "INDIA", "INR"} else "USD"


async def _convert_ws_position_values(
    positions: list[PortfolioPosition], *, target_currency: str = "INR"
) -> tuple[dict[str, float], dict[str, str], dict[str, object]]:
    native: dict[str, float] = {}
    sources: dict[str, str] = {}
    for position in positions:
        value = float(
            (getattr(position, "quantity", 0.0) or 0.0)
            * (getattr(position, "last_price", 0.0) or 0.0)
        )
        if not np.isfinite(value) or value < 0:
            value = float(getattr(position, "market_value", 0.0) or 0.0)
        native[position.ticker] = value
        sources[position.ticker] = _ws_position_currency(position)
    unique = set(sources.values())
    if len(unique) <= 1 and next(iter(unique), target_currency) == target_currency:
        return native, sources, {
            "base_currency": target_currency,
            "aggregation": "native_uniform",
            "source_currencies": sorted(unique),
            "pairs": {
                f"{next(iter(unique), target_currency)}->{target_currency}": {
                    "rate": 1.0,
                    "provenance": "identity",
                    "source": "identity",
                    "is_fallback": False,
                }
            },
            "rate_provider": "currency_service",
        }
    service = get_currency_service()
    converted = dict(native)
    pairs: dict[str, object] = {}
    for ticker, value in native.items():
        source = sources[ticker]
        pair_key = f"{source}->{target_currency}"
        if source == target_currency:
            pairs[pair_key] = {
                "rate": 1.0,
                "provenance": "identity",
                "source": "identity",
                "is_fallback": False,
            }
            continue
        try:
            candidate = await service.get_exchange_rate(source, target_currency)
            rate_value, rate_metadata = coerce_live_fx_rate(candidate)
        except CurrencyUnavailableError:
            raise
        except Exception as exc:
            raise CurrencyUnavailableError() from exc
        converted[ticker] = value * rate_value
        pairs[pair_key] = {"rate": rate_value, **rate_metadata}
    return converted, sources, {
        "base_currency": target_currency,
        "aggregation": "per_position_conversion",
        "source_currencies": sorted(unique),
        "pairs": pairs,
        "rate_provider": "currency_service",
    }


def _trusted_websocket(websocket: WebSocket) -> bool:
    host = _header_value(websocket, "host")
    # A mocked unit socket without real headers is handled by the endpoint's
    # concrete Starlette object; real sockets always have a Host header.
    headers = getattr(websocket, "headers", None)
    if not isinstance(headers, Mapping):
        return True
    return _safe_local_host(host) and _origin_allowed(_header_value(websocket, "origin"))


def _trusted_http_request(request: Request | None) -> bool:
    if request is None:
        return True
    return _safe_local_host(request.headers.get("host")) and _origin_allowed(
        request.headers.get("origin")
    )


async def _reject_websocket(websocket: WebSocket) -> None:
    # Starlette sends a close response before accept; no connection is ever
    # registered in ConnectionManager.
    await websocket.close(code=1008)


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

            # If no connections are active, stop the background loop
            if not manager.active_connections:
                break

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("Background update cycle failed")
            await asyncio.sleep(5)  # Wait before retry

async def send_portfolio_update():
    """Send portfolio data update from database"""
    try:
        async with SessionLocal() as db:
            result = await db.execute(select(PortfolioPosition))
            positions = result.scalars().all()
            
            if positions:
                converted_values, source_currencies, currency_provenance = await _convert_ws_position_values(positions)
            else:
                converted_values, source_currencies, currency_provenance = {}, {}, {
                    "base_currency": "INR",
                    "aggregation": "empty",
                    "source_currencies": [],
                    "pairs": {},
                    "rate_provider": "currency_service",
                }
            total_value = sum(converted_values.values())
            total_for_weights = sum(value for value in converted_values.values() if value > 0)
            pos_list = []
            for p in positions:
                converted_value = converted_values.get(p.ticker, 0.0)
                live_weight = (
                    converted_value / total_for_weights
                    if total_for_weights > 0 else float(p.weight or 0.0)
                )
                pos_list.append({
                    "ticker": p.ticker,
                    "weight": round(live_weight, 4),
                    "value": round(float(converted_value), 2),
                    "quantity": p.quantity or 0.0,
                    "last_price": p.last_price or 0.0,
                    # ``value`` is denominated in the aggregate base currency;
                    # retain the native listing currency separately.
                    "currency": "INR",
                    "value_currency": "INR",
                    "native_currency": source_currencies.get(p.ticker, "INR"),
                })
            
            update_data = {
                "type": "portfolio_update",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": {
                    "total_value": round(float(total_value), 2),
                    "currency": "INR",
                    "base_currency": "INR",
                    "currency_provenance": currency_provenance,
                    "positions": pos_list
                }
            }
            await manager.broadcast(update_data, "portfolio")
    except Exception:
        logger.error("Portfolio update failed")

async def send_analytics_update():
    """Send analytics data update from database"""
    try:
        async with SessionLocal() as db:
            result = await db.execute(select(PortfolioPosition))
            positions = result.scalars().all()
            if not positions:
                return

            tickers = [p.ticker for p in positions]
            # Convert mixed native values before deriving analytics weights.
            try:
                converted_values, _source_currencies, _currency_provenance = await _convert_ws_position_values(
                    positions
                )
            except ProviderError:
                logger.error("Analytics currency conversion unavailable")
                return
            mv_weights = converted_values
            total_mv = sum(value for value in mv_weights.values() if value > 0)

            if total_mv > 0:
                weights = {t: v / total_mv for t, v in mv_weights.items() if v > 0}
            else:
                weights = {p.ticker: (p.weight or 0.0) for p in positions}
                w_sum = sum(weights.values())
                if w_sum > 0:
                    weights = {k: v / w_sum for k, v in weights.items()}
                else:
                    weights = {t: 1.0 / len(tickers) for t in tickers}

            # Lookback limited to 1 year (~252 trading days) to prevent unbounded memory growth
            cutoff_date = datetime.now(timezone.utc).date() - timedelta(days=365)
            t_res = await db.execute(
                select(StockTimeseries)
                .where(
                    StockTimeseries.ticker.in_(tickers),
                    StockTimeseries.date >= cutoff_date
                )
                .order_by(StockTimeseries.date.asc())
            )
            rows = t_res.scalars().all()

            realized_vol = None
            sharpe = None
            max_dd = None
            analytics_status = "unavailable"

            if rows:
                data_dict = {}
                for r in rows:
                    data_dict.setdefault(r.ticker, {})[r.date] = r.adj_close or r.close
                # Keep missing/pre-listing observations missing.  The analytics
                # engine's active positive-weight mask uses the longer history
                # without manufacturing flat pre-listing returns.
                price_df = pd.DataFrame(data_dict).sort_index()
                price_df = price_df.replace([float("inf"), float("-inf")], float("nan"))
                if not price_df.empty and len(price_df) > 5:
                    covered = {t: w for t, w in weights.items() if t in price_df.columns}
                    w_sum = sum(covered.values())
                    if w_sum > 0:
                        covered = {k: v / w_sum for k, v in covered.items()}
                        engine = AnalyticsEngine()
                        metrics = await engine.calculate_portfolio_metrics(price_df, covered)
                        candidate_vol = metrics.get("annual_volatility")
                        candidate_sharpe = metrics.get("sharpe_ratio")
                        candidate_dd = metrics.get("max_drawdown")
                        if all(
                            value is not None
                            for value in (candidate_vol, candidate_sharpe, candidate_dd)
                        ):
                            realized_vol = float(candidate_vol)
                            sharpe = float(candidate_sharpe)
                            max_dd = float(candidate_dd)
                            analytics_status = "measured"

            def _rounded_or_none(value):
                return None if value is None else round(float(value), 4)

            update_data = {
                "type": "analytics_update",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": {
                    "realized_volatility": _rounded_or_none(realized_vol),
                    "sharpe_ratio": _rounded_or_none(sharpe),
                    "max_drawdown": _rounded_or_none(max_dd),
                    "data_status": analytics_status,
                    "positions_count": len(positions)
                }
            }
            await manager.broadcast(update_data, "analytics")
    except Exception:
        logger.error("Analytics update failed")

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
            cutoff_date = datetime.now(timezone.utc).date() - timedelta(days=14)
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
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": market_dict
            }
            await manager.broadcast(update_data, "market_data")
    except Exception:
        logger.error("Market data update failed")

@router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """
    WebSocket endpoint for real-time updates
    """
    if not _trusted_websocket(websocket):
        await _reject_websocket(websocket)
        return
    if not await manager.connect(websocket, client_id):
        return
    
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
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }, client_id)
            
            elif message.get("type") == "unsubscribe":
                topic = message.get("topic")
                if topic:
                    manager.unsubscribe(client_id, topic)
                    await manager.send_personal_message({
                        "type": "unsubscription_confirmed",
                        "topic": topic,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }, client_id)
            
            elif message.get("type") == "ping":
                # Respond to ping with pong
                await manager.send_personal_message({
                    "type": "pong",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }, client_id)
            
    except WebSocketDisconnect:
        manager.disconnect(client_id)
        if not manager.active_connections and update_task and not update_task.done():
            update_task.cancel()
            with suppress(asyncio.CancelledError):
                await update_task
    except Exception:
        logger.error("WebSocket connection error")
        manager.disconnect(client_id)
        if not manager.active_connections and update_task and not update_task.done():
            update_task.cancel()
            with suppress(asyncio.CancelledError):
                await update_task

@router.get("/status")
async def websocket_status():
    """
    Get WebSocket connection status
    """
    return {
        "status": "connected" if manager.active_connections else "disconnected",
        "active_connections": len(manager.active_connections),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@router.post("/broadcast")
async def broadcast_message(
    topic: str,
    message: dict,
    request: Request = None,
):
    """
    Broadcast a message to all subscribers of a topic after the same trust
    boundary used by the WebSocket handshake.
    """
    if not _trusted_http_request(request):
        raise HTTPException(status_code=403, detail="WebSocket origin is not allowed")
    message["type"] = "broadcast"
    message["topic"] = topic
    message["timestamp"] = datetime.now(timezone.utc).isoformat()
    
    await manager.broadcast(message, topic)
    
    return {
        "status": "broadcast_sent",
        "topic": topic,
        "connections": len(manager.active_connections)
    }