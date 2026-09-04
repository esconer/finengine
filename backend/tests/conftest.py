"""
Global test configuration and fixtures for Daisy Risk Engine tests
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, Mock
from typing import Generator, AsyncGenerator
from datetime import datetime
import pandas as pd
import numpy as np
import os

# FastAPI and testing
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

# Application imports
from main import app
from app.db.database import get_db_session, Base
from app.services.data_service import DataService
from app.services.analytics_engine import AnalyticsEngine
from app.services.cache_service import CacheService
from app.models.database import PortfolioPosition, StockTimeseries

# Test configuration
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


# NOTE: no session-scoped event_loop fixture — pytest-asyncio 0.24 auto mode
# provides function-scoped loops; a shared loop broke after asyncio.run() use.


@pytest.fixture
def mock_yfinance_data():
    """Mock yfinance data for testing"""
    dates = pd.date_range(start="2023-01-01", end="2023-12-31", freq="D")
    
    # Create mock price data
    np.random.seed(42)  # For reproducible tests
    price_data = pd.DataFrame({
        'Open': 100 + np.random.randn(len(dates)).cumsum() * 0.5,
        'High': 101 + np.random.randn(len(dates)).cumsum() * 0.5,
        'Low': 99 + np.random.randn(len(dates)).cumsum() * 0.5,
        'Close': 100 + np.random.randn(len(dates)).cumsum() * 0.5,
        'Adj Close': 100 + np.random.randn(len(dates)).cumsum() * 0.5,
        'Volume': np.random.randint(100000, 1000000, len(dates))
    }, index=dates)
    
    return price_data


@pytest.fixture
def mock_portfolio_data():
    """Mock portfolio data for testing"""
    return {
        "AAPL": {"weight": 0.25, "price": 150.0, "sector": "Technology"},
        "MSFT": {"weight": 0.25, "price": 250.0, "sector": "Technology"},
        "GOOGL": {"weight": 0.25, "price": 100.0, "sector": "Technology"},
        "AMZN": {"weight": 0.25, "price": 80.0, "sector": "Consumer Discretionary"}
    }


@pytest.fixture
def mock_price_dataframe():
    """Create a mock price DataFrame for testing"""
    dates = pd.date_range(start="2023-01-01", periods=252, freq="B")
    np.random.seed(42)
    
    data = {}
    for ticker in ["AAPL", "MSFT", "GOOGL", "AMZN"]:
        returns = np.random.randn(len(dates)) * 0.02
        price = 100 * (1 + returns).cumprod()
        data[ticker] = price
    
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def mock_returns_series():
    """Create a mock returns series for testing"""
    dates = pd.date_range(start="2023-01-01", periods=252, freq="B")
    np.random.seed(42)
    returns = pd.Series(np.random.randn(252) * 0.02, index=dates)
    return returns


# ---- Daisy schema fixtures -------------------------------------------------

@pytest.fixture
def ohlcv_frame_factory():
    """OHLCV frames in the project's lowercase cache schema (DataService shape)."""
    def _make(days: int = 260, seed: int = 7, start: str = "2025-01-01", ticker: str = "TEST"):
        dates = pd.date_range(start=start, periods=days, freq="B")
        rng = np.random.default_rng(seed)
        close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, days)))
        return pd.DataFrame({
            "date": dates,
            "open": close * (1 + rng.normal(0, 0.004, days)),
            "high": close * 1.008,
            "low": close * 0.992,
            "close": close,
            "adj_close": close,
            "volume": rng.integers(100_000, 1_000_000, days).astype(float),
            "ticker": ticker,
        })
    return _make


@pytest_asyncio.fixture
async def seeded_positions(test_db: AsyncSession):
    """Two real PortfolioPosition rows; cleaned up afterwards.

    added_on is deliberately old: analytics tests use 2023-2025 synthetic
    price frames, and holding-aware truncation drops pre-holding history.
    """
    from datetime import datetime as _dt
    _old = _dt(2020, 1, 1)
    positions = [
        PortfolioPosition(
            ticker="AAPL", weight=0.4, quantity=100, buy_price=150.0,
            last_price=180.0, market_value=18_000.0,
            sector="Technology", industry="Hardware",
            added_on=_old,
        ),
        PortfolioPosition(
            ticker="MSFT", weight=0.6, quantity=50, buy_price=300.0,
            last_price=420.0, market_value=21_000.0,
            sector="Technology", industry="Software",
            added_on=_old,
        ),
    ]
    test_db.add_all(positions)
    await test_db.commit()
    for pos in positions:
        await test_db.refresh(pos)
    yield positions
    await test_db.execute(PortfolioPosition.__table__.delete())
    await test_db.commit()


# Database fixtures
@pytest_asyncio.fixture
async def test_db():
    """Create test database with proper async support and per-test cleanup"""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
        try:
            for table in reversed(Base.metadata.sorted_tables):
                await session.execute(table.delete())
            await session.commit()
        except Exception:
            await session.rollback()
    
    await engine.dispose()


@pytest_asyncio.fixture
async def mock_data_service(test_db: AsyncSession):
    """Mock data service for testing"""
    service = Mock(spec=DataService)
    service.db = test_db
    
    # Mock async methods
    service.fetch_historical_data = AsyncMock()
    service.fetch_quote = AsyncMock()
    service.validate_ticker = AsyncMock(return_value=True)
    service.fetch_ohlcv_batch = AsyncMock()
    
    return service


@pytest_asyncio.fixture
async def mock_analytics_engine():
    """Mock analytics engine for testing"""
    engine = Mock(spec=AnalyticsEngine)
    
    # Mock async methods
    engine.calculate_portfolio_metrics = AsyncMock()
    engine.forecast_volatility = AsyncMock()
    engine.factor_exposure_analysis = AsyncMock()
    engine.concentration_analysis = AsyncMock()
    engine.liquidity_analysis = AsyncMock()
    engine.stress_test = AsyncMock()
    engine.volatility_sizing = AsyncMock()
    engine.risk_scoring = AsyncMock()
    
    return engine


@pytest_asyncio.fixture
async def mock_cache_service(test_db: AsyncSession):
    """Mock cache service for testing"""
    service = Mock(spec=CacheService)
    service.db = test_db
    
    # Mock async methods
    service.get_cache_stats = AsyncMock(return_value={"ttl_minutes": 60})
    service.clear_cache = AsyncMock()
    
    return service


# Application fixtures
def _override_get_db(session: AsyncSession):
    async def _gen():
        yield session
    return _gen


@pytest_asyncio.fixture
async def async_client(test_db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Async test client bound to the ISOLATED test database (never daisy.db)."""
    app.dependency_overrides[get_db_session] = _override_get_db(test_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Create test client"""
    with TestClient(app) as client:
        yield client


# Factory fixtures for creating test data
@pytest.fixture
def portfolio_position_factory():
    """Factory for creating test portfolio positions (long-held: 2020)."""
    def create_position(
        ticker: str = "AAPL",
        weight: float = 0.1,
        region: str = "US",
        sector: str = "Technology",
        industry: str = "Consumer Electronics"
    ):
        return PortfolioPosition(
            ticker=ticker.upper(),
            weight=weight,
            region=region,
            primary_source="yfinance",
            last_price=100.0,
            market_value=10000.0,
            sector=sector,
            industry=industry,
            custom_name="",
            added_on=datetime(2020, 1, 1),
        )
    
    return create_position


@pytest.fixture
def stock_timeseries_factory():
    """Factory for creating test stock timeseries data"""
    def create_timeseries(
        ticker: str = "AAPL",
        date: datetime = datetime.now().date(),
        open_price: float = 100.0,
        high_price: float = 101.0,
        low_price: float = 99.0,
        close_price: float = 100.5,
        adj_close: float = 100.5,
        volume: int = 1000000
    ):
        return StockTimeseries(
            ticker=ticker.upper(),
            date=date,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            adj_close=adj_close,
            volume=volume,
            source_used="yfinance",
            fetch_status="fresh"
        )
    
    return create_timeseries


# Test data fixtures
@pytest.fixture
def sample_portfolio_weights():
    """Sample portfolio weights for testing"""
    return {
        "AAPL": 0.25,
        "MSFT": 0.25,
        "GOOGL": 0.25,
        "AMZN": 0.25
    }


@pytest.fixture
def expected_analytics_metrics():
    """Expected analytics metrics for validation"""
    return {
        "annual_return": 0.08,
        "annual_volatility": 0.20,
        "sharpe_ratio": 0.3,
        "sortino_ratio": 0.4,
        "var_95": -0.025,
        "cvar_95": -0.035,
        "max_drawdown": -0.15,
        "hit_ratio": 0.55
    }


@pytest.fixture
def mock_websocket_messages():
    """Mock WebSocket messages for testing"""
    return {
        "subscribe": {
            "type": "subscribe",
            "topic": "portfolio"
        },
        "unsubscribe": {
            "type": "unsubscribe", 
            "topic": "analytics"
        },
        "ping": {
            "type": "ping"
        }
    }


# Environment fixtures
@pytest.fixture
def test_env_vars():
    """Set up test environment variables"""
    test_vars = {
        "DATABASE_URL": TEST_DATABASE_URL,
        "TESTING": "True",
        "LOG_LEVEL": "DEBUG"
    }
    
    original_vars = {}
    for key, value in test_vars.items():
        original_vars[key] = os.environ.get(key)
        os.environ[key] = value
    
    yield test_vars
    
    # Restore original values
    for key, original_value in original_vars.items():
        if original_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original_value


# Performance testing fixtures
@pytest.fixture
def performance_test_data():
    """Generate large dataset for performance testing"""
    # Generate 1000 days of data for 10 tickers
    dates = pd.date_range(start="2020-01-01", periods=1000, freq="D")
    tickers = [f"TEST{i:02d}" for i in range(10)]
    
    data = {}
    np.random.seed(42)
    
    for ticker in tickers:
        returns = np.random.randn(1000) * 0.02
        price = 100 * (1 + returns).cumprod()
        data[ticker] = price
    
    return pd.DataFrame(data, index=dates)


# Error simulation fixtures
@pytest.fixture
def error_simulation_config():
    """Configuration for error simulation tests"""
    return {
        "network_errors": True,
        "database_errors": True,
        "yfinance_errors": True,
        "validation_errors": True
    }


# Cleanup fixtures
@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Automatically clean up test data after each test"""
    yield
    
    # Clean up any temporary files, database records, etc.
    # This runs after each test
    pass


# Test markers and categories
pytestmark = [
    pytest.mark.unit,
    pytest.mark.asyncio
]


# Utility functions for tests
def create_test_portfolio_data(num_positions: int = 10) -> dict:
    """Create test portfolio data with specified number of positions"""
    tickers = [f"TICKER{i:02d}" for i in range(num_positions)]
    weights = {ticker: 1.0/num_positions for ticker in tickers}
    return weights


def create_test_price_data(ticker: str, num_days: int = 252) -> pd.DataFrame:
    """Create test price data for a single ticker"""
    dates = pd.date_range(start="2023-01-01", periods=num_days, freq="B")
    np.random.seed(hash(ticker) % 2**32)  # Seed based on ticker for consistency
    
    returns = np.random.randn(num_days) * 0.02
    price = 100 * (1 + returns).cumprod()
    
    return pd.DataFrame({
        'Open': price * (1 + np.random.randn(num_days) * 0.001),
        'High': price * (1 + np.random.rand(num_days) * 0.002),
        'Low': price * (1 - np.random.rand(num_days) * 0.002),
        'Close': price,
        'Adj Close': price,
        'Volume': np.random.randint(100000, 2000000, num_days)
    }, index=dates)


class AsyncContextManager:
    """Helper class for async context managers in tests"""
    
    def __init__(self, async_func):
        self.async_func = async_func
    
    async def __aenter__(self):
        return await self.async_func()
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


# Export commonly used fixtures
__all__ = [
    "test_db", 
    "async_client",
    "client",
    "mock_data_service",
    "mock_analytics_engine", 
    "mock_cache_service",
    "mock_yfinance_data",
    "mock_portfolio_data",
    "mock_price_dataframe",
    "mock_returns_series",
    "sample_portfolio_weights",
    "expected_analytics_metrics",
    "mock_websocket_messages",
    "portfolio_position_factory",
    "stock_timeseries_factory",
    "performance_test_data",
    "test_env_vars",
    "create_test_portfolio_data",
    "create_test_price_data"
]