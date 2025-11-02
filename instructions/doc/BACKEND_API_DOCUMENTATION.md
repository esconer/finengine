# Daisy Risk Engine Backend API Documentation

## Overview

The Daisy Risk Engine is a FastAPI-based financial risk analytics platform that provides comprehensive portfolio management, market data processing, and risk calculation capabilities. The API is structured with a modular architecture consisting of REST endpoints, WebSocket connections, and a robust service layer.

## API Architecture

### Base Configuration
- **Base URL**: `http://localhost:8000`
- **API Version**: v1
- **Documentation**: `/docs` (Swagger UI), `/redoc` (ReDoc)
- **Health Check**: `/health`

### Core Endpoints

#### 1. Portfolio Management API (`/api/v1/portfolio`)

##### GET `/api/v1/portfolio`
**Purpose**: Retrieve portfolio summary with all positions

**Query Parameters**:
- `region` (optional): Filter by region (e.g., "US")
- `sector` (optional): Filter by sector (e.g., "Technology")
- `currency` (optional): Target currency ("USD" or "INR", default: "USD")

**Request Example**:
```bash
GET /api/v1/portfolio?currency=INR&sector=Technology
```

**Response Structure**:
```json
{
  "positions": [
    {
      "id": 1,
      "ticker": "AAPL",
      "weight": 0.25,
      "quantity": 100,
      "buy_price": 150.0,
      "last_price": 175.0,
      "market_value": 17500.0,
      "sector": "Technology",
      "industry": "Consumer Electronics",
      "custom_name": "Apple Inc",
      "added_on": "2024-01-15T10:30:00",
      "updated_on": "2024-11-02T19:00:00",
      "total_cost": 15000.0,
      "unrealized_gain_loss": 2500.0,
      "unrealized_gain_loss_pct": 16.67,
      "current_value": 17500.0
    }
  ],
  "total_value": 100000.0,
  "total_positions": 4,
  "total_weight": 1.0,
  "sectors": {
    "Technology": 1.0
  }
}
```

**Error Handling**:
- `404`: No positions found in portfolio
- `500`: Internal server error with detailed logging

##### POST `/api/v1/portfolio/add`
**Purpose**: Add a new portfolio position

**Request Body**:
```json
{
  "ticker": "AAPL",
  "weight": 0.25,
  "quantity": 100,
  "buy_price": 150.0,
  "region": "US",
  "custom_name": "Apple Inc"
}
```

**Validation Rules**:
- `ticker`: Must be 1-20 characters, validated against yfinance
- `weight`: Must be > 0 and ≤ 1
- `quantity`: Must be > 0
- `buy_price`: Must be > 0
- `custom_name`: Optional, max 100 characters

**Response Structure**:
```json
{
  "id": 1,
  "ticker": "AAPL",
  "weight": 0.25,
  "quantity": 100,
  "buy_price": 150.0,
  "last_price": 175.0,
  "market_value": 17500.0,
  "sector": "Technology",
  "industry": "Consumer Electronics",
  "custom_name": "Apple Inc",
  "added_on": "2024-01-15T10:30:00",
  "updated_on": "2024-01-15T10:30:00",
  "total_cost": 15000.0,
  "unrealized_gain_loss": 2500.0,
  "unrealized_gain_loss_pct": 16.67,
  "current_value": 17500.0
}
```

**Error Handling**:
- `400`: Invalid ticker or validation error
- `409`: Ticker already exists in portfolio
- `422`: Request validation error with detailed field errors
- `500`: Internal server error

##### POST `/api/v1/portfolio/bulk_add`
**Purpose**: Add multiple positions atomically with transaction integrity

**Request Body**:
```json
{
  "positions": [
    {
      "ticker": "AAPL",
      "weight": 0.25,
      "quantity": 100,
      "buy_price": 150.0,
      "region": "US"
    },
    {
      "ticker": "MSFT",
      "weight": 0.25,
      "quantity": 50,
      "buy_price": 300.0,
      "region": "US"
    }
  ],
  "auto_normalize": true
}
```

**Response Structure**:
```json
{
  "added": 2,
  "failed": 0,
  "normalized": true,
  "positions": [
    {
      "id": 1,
      "ticker": "AAPL",
      "weight": 0.5,
      "quantity": 100,
      "buy_price": 150.0,
      "last_price": 175.0,
      "market_value": 17500.0,
      "sector": "Technology",
      "industry": "Consumer Electronics",
      "custom_name": null,
      "added_on": "2024-01-15T10:30:00",
      "updated_on": "2024-01-15T10:30:00",
      "total_cost": 15000.0,
      "unrealized_gain_loss": 2500.0,
      "unrealized_gain_loss_pct": 16.67,
      "current_value": 17500.0
    }
  ]
}
```

**Features**:
- Atomic transaction with rollback on failure
- Pre-validation of all positions before commit
- Duplicate ticker filtering
- Automatic weight normalization
- Detailed failure tracking

##### PUT `/api/v1/portfolio/{ticker}`
**Purpose**: Update an existing position

**Path Parameter**: `ticker` - Stock ticker symbol

**Request Body**:
```json
{
  "weight": 0.30,
  "quantity": 120,
  "buy_price": 145.0,
  "custom_name": "Updated Apple Position"
}
```

**Validation**:
- All fields are optional
- Same validation rules as POST request
- Recalculates market value and metrics

##### DELETE `/api/v1/portfolio/{ticker}`
**Purpose**: Remove a position from portfolio

**Path Parameter**: `ticker` - Stock ticker symbol

**Response**:
```json
{
  "success": true,
  "message": "Position AAPL deleted successfully"
}
```

##### GET `/api/v1/portfolio/export/csv`
**Purpose**: Export portfolio as CSV

**Response**: CSV file content with portfolio data

**CSV Columns**:
- ticker, weight, region, last_price, market_value, sector, industry, custom_name, added_on, updated_on

##### POST `/api/v1/portfolio/normalize`
**Purpose**: Normalize portfolio weights to sum to 1.0

**Query Parameters**:
- `method` (optional): Normalization method, default "proportional"

**Response**:
```json
{
  "success": true,
  "message": "Portfolio weights normalized. Total weight: 1.0000"
}
```

#### 2. Market Data API (`/api/v1/data`)

##### GET `/api/v1/data/{ticker}`
**Purpose**: Get historical OHLCV data for a ticker

**Path Parameter**: `ticker` - Stock ticker symbol

**Query Parameters**:
- `start` (optional): Start date (YYYY-MM-DD), defaults to 1 year ago
- `end` (optional): End date (YYYY-MM-DD), defaults to today
- `force_refresh` (optional): Force refresh from yfinance, default false

**Request Example**:
```bash
GET /api/v1/data/AAPL?start=2023-01-01&end=2024-01-01&force_refresh=false
```

**Response Structure**:
```json
{
  "ticker": "AAPL",
  "data": [
    {
      "ticker": "AAPL",
      "date": "2024-01-02",
      "open": 185.64,
      "high": 186.50,
      "low": 184.23,
      "close": 185.64,
      "adj_close": 185.64,
      "volume": 78923000
    }
  ],
  "source": "yfinance",
  "from_cache": true,
  "metadata": {
    "sector": "Technology",
    "industry": "Consumer Electronics"
  }
}
```

**Features**:
- Automatic caching with TTL
- Data normalization for yfinance compatibility
- Corporate action adjustments (splits, dividends)
- Rate limiting with retry logic

##### GET `/api/v1/data/quote/{ticker}`
**Purpose**: Get latest quote and metadata for a ticker

**Path Parameter**: `ticker` - Stock ticker symbol

**Response Structure**:
```json
{
  "ticker": "AAPL",
  "current_price": 175.43,
  "volume": 45670000,
  "market_cap": 2780000000000,
  "sector": "Technology",
  "industry": "Consumer Electronics",
  "52_week_high": 199.62,
  "52_week_low": 164.08,
  "pe_ratio": 29.5,
  "dividend_yield": 0.0052,
  "timestamp": "2024-11-02T19:05:00"
}
```

##### POST `/api/v1/data/batch`
**Purpose**: Get OHLCV data for multiple tickers efficiently

**Request Body**:
```json
{
  "tickers": ["AAPL", "MSFT", "GOOGL"],
  "start": "2024-01-01",
  "end": "2024-11-01",
  "force_refresh": false
}
```

**Response Structure**:
```json
{
  "data": {
    "AAPL": [...],
    "MSFT": [...],
    "GOOGL": [...]
  },
  "failed_tickers": []
}
```

##### POST `/api/v1/data/validate`
**Purpose**: Validate if a ticker exists and has data

**Request Body**:
```json
{
  "ticker": "AAPL"
}
```

**Response**:
```json
{
  "valid": true,
  "message": "Ticker AAPL is valid"
}
```

##### POST `/api/v1/data/refresh`
**Purpose**: Force refresh data for specified tickers

**Request Body**: Array of ticker strings

**Response**:
```json
{
  "refreshed": 3,
  "failed": 0,
  "message": "Refreshed 3 tickers successfully"
}
```

##### GET `/api/v1/data/config`
**Purpose**: Get API configuration and cache settings

**Response**:
```json
{
  "primary_source": "yfinance",
  "cache_ttl_minutes": 60,
  "enable_cache": true
}
```

##### PUT `/api/v1/data/config`
**Purpose**: Update API configuration

**Query Parameters**:
- `cache_ttl_minutes` (optional): Cache TTL in minutes (1-1440)
- `enable_cache` (optional): Enable/disable caching

**Response**:
```json
{
  "updated": true,
  "settings": {
    "cache_ttl_minutes": 120
  },
  "message": "Configuration updated successfully"
}
```

#### 3. Analytics API (`/api/v1/analytics`)

##### GET `/api/v1/analytics/realized-risk`
**Purpose**: Get realized risk metrics for portfolio or individual assets

**Query Parameters**:
- `tickers` (optional): Comma-separated tickers or 'portfolio'
- `start` (optional): Start date (YYYY-MM-DD), defaults to 252 trading days ago
- `end` (optional): End date (YYYY-MM-DD), defaults to today

**Request Example**:
```bash
GET /api/v1/analytics/realized-risk?tickers=AAPL,MSFT&start=2023-01-01&end=2024-01-01
```

**Response Structure**:
```json
{
  "portfolio": {
    "annual_return": 0.15,
    "annual_volatility": 0.22,
    "sharpe_ratio": 0.68,
    "sortino_ratio": 0.89,
    "skewness": -0.15,
    "kurtosis": 3.2,
    "max_drawdown": -0.18,
    "var_95": -0.032,
    "cvar_95": -0.047,
    "hit_ratio": 0.58
  },
  "positions": {
    "AAPL": {
      "annual_return": 0.12,
      "annual_volatility": 0.25,
      "sharpe_ratio": 0.48,
      "max_drawdown": -0.22,
      "var_95": -0.038,
      "weight": 0.5
    }
  },
  "data_range": {
    "start": "2023-01-01",
    "end": "2024-01-01"
  },
  "methodology": "Real-time calculations using quantstats and statistical models"
}
```

##### GET `/api/v1/analytics/forecast-risk`
**Purpose**: Get forecast risk metrics using specified model

**Query Parameters**:
- `model` (optional): Risk model ("EWMA", "GARCH", or "EGARCH"), default "GARCH"
- `horizon` (optional): Forecast horizon in days (1-30), default 1
- `tickers` (optional): Comma-separated tickers

**Request Example**:
```bash
GET /api/v1/analytics/forecast-risk?model=GARCH&horizon=5&tickers=AAPL,MSFT
```

**Response Structure**:
```json
{
  "model": "GARCH",
  "horizon": 5,
  "portfolio": {
    "volatility_forecast": 0.24,
    "var_forecast": -0.035,
    "cvar_forecast": -0.051,
    "confidence_interval": [0.19, 0.29]
  },
  "positions": {
    "AAPL": {
      "volatility_forecast": 0.26,
      "var_forecast": -0.039
    }
  },
  "model_params": {
    "p": 1,
    "q": 1,
    "type": "GARCH"
  },
  "data_range": {
    "start": "2023-01-01",
    "end": "2024-01-01"
  },
  "methodology": "Volatility forecasting using GARCH model with 5-day horizon"
}
```

##### GET `/api/v1/analytics/factor-exposure`
**Purpose**: Get factor exposure analysis

**Query Parameters**:
- `tickers` (optional): Comma-separated tickers
- `lookback_days` (optional): Lookback period in days (30-756), default 252

**Response Structure**:
```json
{
  "portfolio": {
    "alpha": 0.02,
    "market": 1.08,
    "momentum": 0.15,
    "size": -0.08,
    "value": 0.12,
    "min_vol": -0.18,
    "quality": 0.25,
    "rates": 0.10,
    "volatility": -0.12,
    "meme": 0.03,
    "ai": 0.08
  },
  "r_squared": 0.75,
  "adjusted_r_squared": 0.73,
  "data_range": {
    "start": "2023-01-01",
    "end": "2024-01-01"
  },
  "lookback_days": 252,
  "methodology": "Statistical factor model with market benchmark regression"
}
```

##### GET `/api/v1/analytics/concentration`
**Purpose**: Get portfolio concentration metrics

**Response Structure**:
```json
{
  "largest_position": 0.30,
  "top_3": 0.75,
  "top_5": 0.90,
  "top_10": 1.0,
  "herfindahl_index": 0.22,
  "effective_positions": 4.5,
  "diversification_ratio": 1.2,
  "by_weight": {
    "AAPL": 0.30,
    "MSFT": 0.25,
    "GOOGL": 0.25,
    "AMZN": 0.20
  },
  "by_sector": {
    "Technology": 1.0,
    "Communication_Services": 0.0,
    "Finance": 0.0,
    "Healthcare": 0.0,
    "Other": 0.0
  },
  "methodology": "Concentration analysis using Herfindahl-Hirschman Index and effective number of positions"
}
```

##### GET `/api/v1/analytics/liquidity`
**Purpose**: Get portfolio liquidity analysis

**Response Structure**:
```json
{
  "overall_score": 7.8,
  "liquidation_time_days": "2-5",
  "risk_level": "Medium",
  "by_position": {
    "AAPL": {
      "score": 8.5,
      "avg_volume": 45000000,
      "category": "High",
      "spread": 0.001,
      "liquidation_days": "1-2"
    }
  },
  "volume_stats": {
    "avg_volume": 38000000,
    "total_portfolio_volume": 152000000,
    "high_volume_pct": 100,
    "medium_volume_pct": 0,
    "low_volume_pct": 0
  },
  "methodology": "Liquidity scoring based on trading volume and market capitalization"
}
```

##### POST `/api/v1/analytics/stress-test`
**Purpose**: Run stress test on portfolio

**Request Body**:
```json
{
  "scenario": "2020_covid",
  "tickers": ["AAPL", "MSFT"]
}
```

**Available Scenarios**:
- `2018_q4`: Q4 2018 Correction
- `2020_covid`: COVID-19 Crash
- `2022_inflation`: Inflation Peak
- `volatility_spike`: Volatility Spike

**Response Structure**:
```json
{
  "scenario": "2020_covid",
  "scenario_description": "COVID-19 Crash",
  "max_drawdown": -0.35,
  "portfolio_impact": -0.30,
  "position_impacts": {
    "AAPL": -0.32,
    "MSFT": -0.28
  },
  "recovery_time": 45,
  "confidence_level": 0.95,
  "methodology": "Historical simulation with portfolio weighting"
}
```

##### GET `/api/v1/analytics/volatility-sizing`
**Purpose**: Get volatility-adjusted position sizing recommendations

**Query Parameters**:
- `model` (optional): Volatility model, default "EWMA"
- `target_volatility` (optional): Target volatility, default 0.15

**Response Structure**:
```json
{
  "current_weights": {
    "AAPL": 0.25,
    "MSFT": 0.25,
    "GOOGL": 0.25,
    "AMZN": 0.25
  },
  "recommended_weights": {
    "AAPL": 0.22,
    "MSFT": 0.28,
    "GOOGL": 0.30,
    "AMZN": 0.20
  },
  "trades": {
    "AAPL": {
      "shares_delta": -150,
      "amount": -26250
    }
  },
  "target_volatility": 0.15,
  "current_volatility": 0.18,
  "volatilities": {
    "AAPL": 0.25,
    "MSFT": 0.22,
    "GOOGL": 0.28,
    "AMZN": 0.30
  },
  "methodology": "EWMA volatility estimation with target volatility scaling"
}
```

##### GET `/api/v1/analytics/risk-score`
**Purpose**: Get overall portfolio risk score

**Response Structure**:
```json
{
  "overall_score": 22.5,
  "risk_level": "MEDIUM",
  "change": -1,
  "components": {
    "concentration": 18.0,
    "volatility": 25.0,
    "correlation": 15.0,
    "factor_risk": 20.0,
    "market_risk": 12.0
  },
  "alerts": [
    "High concentration risk (HHI: 0.220)",
    "High volatility risk (22.0% annualized)"
  ],
  "methodology": "Multi-factor risk scoring with weighted components"
}
```

##### GET `/api/v1/analytics/summary`
**Purpose**: Get analytics summary for dashboard

**Response Structure**:
```json
{
  "portfolio_value": 100000.0,
  "total_positions": 4,
  "realized_volatility": 0.20,
  "forecast_volatility": 0.22,
  "sharpe_ratio": 0.68,
  "max_drawdown": -0.18,
  "risk_score": 22.5,
  "risk_level": "MEDIUM",
  "liquidity_score": 7.8,
  "concentration_score": 22.0,
  "last_updated": "2024-11-02T19:05:00",
  "methodology": "Real-time portfolio analytics summary with multi-factor risk assessment"
}
```

#### 4. WebSocket API (`/api/v1/ws`)

##### WebSocket Endpoint: `/ws/{client_id}`
**Purpose**: Real-time updates for portfolio, analytics, and market data

**Connection**:
```javascript
const ws = new WebSocket('ws://localhost:8000/api/v1/ws/client123?token=optional_token');
```

**Client Messages**:

**Subscribe to Topics**:
```json
{
  "type": "subscribe",
  "topic": "portfolio"
}
```

**Unsubscribe from Topics**:
```json
{
  "type": "unsubscribe",
  "topic": "analytics"
}
```

**Ping**:
```json
{
  "type": "ping"
}
```

**Server Messages**:

**Portfolio Update**:
```json
{
  "type": "portfolio_update",
  "timestamp": "2024-11-02T19:05:00",
  "data": {
    "total_value": 105432.50,
    "positions": [
      {
        "ticker": "AAPL",
        "weight": 0.25,
        "value": 26358.12
      }
    ]
  }
}
```

**Analytics Update**:
```json
{
  "type": "analytics_update",
  "timestamp": "2024-11-02T19:05:00",
  "data": {
    "realized_volatility": 0.205,
    "sharpe_ratio": 0.72,
    "max_drawdown": -0.165,
    "risk_score": 21.8
  }
}
```

**Market Data Update**:
```json
{
  "type": "market_data_update",
  "timestamp": "2024-11-02T19:05:00",
  "data": {
    "AAPL": {
      "price": 175.43,
      "change": 2.15,
      "volume": 45670000
    }
  }
}
```

**Available Topics**:
- `portfolio`: Portfolio value and position updates
- `analytics`: Risk metrics and analytics updates
- `market_data`: Real-time market data updates

##### GET `/api/v1/ws/status`
**Purpose**: Get WebSocket connection status

**Response**:
```json
{
  "status": "connected",
  "active_connections": 5,
  "timestamp": "2024-11-02T19:05:00"
}
```

##### POST `/api/v1/ws/broadcast`
**Purpose**: Broadcast a message to all subscribers of a topic

**Request Body**:
```json
{
  "topic": "portfolio",
  "message": {
    "custom_data": "value"
  }
}
```

## Core Services

### 1. AnalyticsEngine
**Purpose**: Core analytics calculations using quantstats, arch, and statsmodels

**Key Methods**:
- `calculate_portfolio_metrics()`: Comprehensive portfolio metrics
- `forecast_volatility()`: Volatility forecasting (GARCH, EGARCH, EWMA)
- `factor_exposure_analysis()`: Factor model analysis
- `concentration_analysis()`: Portfolio concentration metrics
- `liquidity_analysis()`: Liquidity scoring
- `stress_test()`: Historical stress testing
- `volatility_sizing()`: Risk-based position sizing
- `risk_scoring()`: Multi-factor risk scoring

### 2. DataService
**Purpose**: Market data fetching and caching using yfinance

**Key Methods**:
- `fetch_historical_data()`: OHLCV data with caching
- `fetch_quote()`: Latest quotes and metadata
- `fetch_ohlcv_batch()`: Efficient multi-ticker fetching
- `validate_ticker()`: Ticker existence validation
- `get_corporate_actions()`: Splits and dividends
- `check_data_integrity()`: Data quality validation

**Features**:
- Automatic retry logic (3 attempts)
- Rate limiting (500ms between requests)
- Data normalization for yfinance compatibility
- Comprehensive caching with TTL
- Data integrity validation

### 3. CacheService
**Purpose**: Analytics result caching and fetch attempt logging

**Key Methods**:
- `get_cached_analytics()`: Retrieve cached results
- `set_cached_analytics()`: Store calculation results
- `log_fetch_attempt()`: Track data fetch attempts
- `clear_expired_cache()`: Clean expired entries
- `get_cache_stats()`: Cache performance metrics

### 4. CurrencyConversionService
**Purpose**: Currency conversion between USD and INR

**Key Methods**:
- `get_exchange_rate()`: Fetch exchange rates
- `convert_amount()`: Convert between currencies
- `format_currency()`: Format with currency symbols

**Features**:
- 30-minute exchange rate caching
- Fallback rate for USD/INR (83.0)
- Currency symbol formatting

## Data Models

### PortfolioPosition
**Database Model**:
- `id`: Primary key
- `ticker`: Stock symbol (String[10])
- `weight`: Portfolio weight (Float, 0-1)
- `quantity`: Shares/units (Float, >0)
- `buy_price`: Purchase price (Float, >0)
- `region`: Geographic region (String[10])
- `sector`: Industry sector (String[50])
- `industry`: Industry classification (String[50])
- `custom_name`: User-defined name (String[100])
- `last_price`: Current market price (Float)
- `market_value`: Current value (Float)
- `added_on`, `updated_on`: Timestamps

### StockTimeseries
**Database Model**:
- `id`: Primary key
- `ticker`: Stock symbol (String[10])
- `date`: Trading date (DateTime)
- `open`, `high`, `low`, `close`, `adj_close`: OHLCV data (Float)
- `volume`: Trading volume (Integer)
- `source_used`: Data source ("yfinance")
- `fetch_status`: Data freshness ("fresh")
- `fetched_on`: Fetch timestamp

**Indexes**:
- `ix_ticker_date`: Composite index for performance
- Unique constraint on (ticker, date)

### AnalyticsCache
**Database Model**:
- `id`: Primary key
- `ticker`: Stock symbol (String[10])
- `metric_name`: Analytics metric (String[50])
- `metric_value`: Calculated value (Float)
- `calculation_date`: Reference date (DateTime)
- `expires_at`: Cache expiration (DateTime)
- `model_params`: Model parameters (JSON)

### FetchLog
**Database Model**:
- `id`: Primary key
- `ticker`: Stock symbol (String[10])
- `timestamp`: Attempt timestamp (DateTime)
- `status`: Success/failure status (String[20])
- `error_message`: Error details (String[500])
- `source_used`: Data source (String[20])

## Authentication & Authorization

### Current Implementation
- **No Authentication**: Currently open API for development
- **CORS**: Configured for frontend on `localhost:3000`
- **Security Headers**: Comprehensive security headers added
- **HTTPS**: Enforced in production environment

### Future Enhancement
- API key authentication
- JWT token-based authentication
- Role-based access control
- Rate limiting per user

## Rate Limiting & Constraints

### Current Implementation
- **Data Fetching**: 500ms delay between yfinance requests
- **Timeout Protection**: 30-second timeout for data requests
- **Retry Logic**: 3 attempts with 1-second delays
- **Cache TTL**: 60 minutes for analytics results

### Rate Limits
- **Portfolio Operations**: No explicit limits
- **Data Requests**: Managed through caching and delays
- **WebSocket Connections**: No connection limits
- **Batch Operations**: Efficient handling of multiple requests

## Error Handling Patterns

### Global Exception Handler
```python
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return {
        "error": "Internal server error",
        "message": "An unexpected error occurred",
        "status_code": 500
    }
```

### HTTP Exception Codes
- `400`: Bad Request (validation errors, invalid tickers)
- `404`: Not Found (missing positions, invalid tickers)
- `409`: Conflict (duplicate tickers)
- `422`: Unprocessable Entity (request validation errors)
- `500`: Internal Server Error (system errors)

### Error Response Format
```json
{
  "error": "Invalid input",
  "message": "Ticker validation failed: XYZ does not exist",
  "status_code": 400
}
```

### Logging
- **Structured Logging**: JSON-formatted logs with context
- **Error Tracking**: Comprehensive error logging with stack traces
- **Performance Monitoring**: Request timing and response metrics
- **Data Integrity**: Validation errors and cache hit/miss rates

## Security Features

### Security Headers
```python
response.headers["X-Content-Type-Options"] = "nosniff"
response.headers["X-Frame-Options"] = "DENY"
response.headers["X-XSS-Protection"] = "1; mode=block"
response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
```

### Production Security
- HTTPS enforcement
- Trusted host middleware
- CORS configuration
- Input validation and sanitization

## Performance Optimizations

### Caching Strategy
- **Analytics Cache**: 60-minute TTL for calculation results
- **Market Data Cache**: Automatic caching with data integrity validation
- **Exchange Rate Cache**: 30-minute TTL for currency rates

### Database Optimization
- **Composite Indexes**: Performance optimization for common queries
- **Connection Pooling**: Efficient database connection management
- **Async Operations**: Non-blocking database operations

### Request Optimization
- **Compression**: GZip compression for responses > 1000 bytes
- **Batch Operations**: Efficient handling of multiple data requests
- **Rate Limiting**: Prevent API abuse and ensure stability

## Code Examples

### JavaScript/TypeScript Integration

#### Portfolio Management
```javascript
// Add a new position
const addPosition = async (position) => {
  try {
    const response = await fetch('/api/v1/portfolio/add', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(position),
    });
    
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.detail);
    }
    
    return result;
  } catch (error) {
    console.error('Error adding position:', error);
    throw error;
  }
};

// Get portfolio summary
const getPortfolio = async (filters = {}) => {
  const params = new URLSearchParams(filters);
  const response = await fetch(`/api/v1/portfolio?${params}`);
  return await response.json();
};
```

#### Market Data Fetching
```javascript
// Get historical data
const getStockData = async (ticker, start, end) => {
  const params = new URLSearchParams({ start, end });
  const response = await fetch(`/api/v1/data/${ticker}?${params}`);
  return await response.json();
};

// Batch fetch
const getBatchData = async (tickers) => {
  const response = await fetch('/api/v1/data/batch', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ tickers }),
  });
  return await response.json();
};
```

#### Analytics Integration
```javascript
// Get risk metrics
const getRiskMetrics = async (tickers) => {
  const params = new URLSearchParams({ tickers: tickers.join(',') });
  const response = await fetch(`/api/v1/analytics/realized-risk?${params}`);
  return await response.json();
};

// Run stress test
const runStressTest = async (scenario, tickers) => {
  const response = await fetch('/api/v1/analytics/stress-test', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ scenario, tickers }),
  });
  return await response.json();
};
```

#### WebSocket Integration
```javascript
// Connect to WebSocket
const connectWebSocket = (clientId) => {
  const ws = new WebSocket(`ws://localhost:8000/api/v1/ws/${clientId}`);
  
  ws.onopen = () => {
    console.log('WebSocket connected');
    // Subscribe to topics
    ws.send(JSON.stringify({ type: 'subscribe', topic: 'portfolio' }));
    ws.send(JSON.stringify({ type: 'subscribe', topic: 'analytics' }));
  };
  
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    handleRealtimeUpdate(message);
  };
  
  ws.onclose = () => {
    console.log('WebSocket disconnected');
  };
  
  return ws;
};

const handleRealtimeUpdate = (message) => {
  switch (message.type) {
    case 'portfolio_update':
      updatePortfolioDisplay(message.data);
      break;
    case 'analytics_update':
      updateAnalyticsDisplay(message.data);
      break;
    case 'market_data_update':
      updateMarketDataDisplay(message.data);
      break;
  }
};
```

### Python Integration

#### Using httpx
```python
import httpx
import asyncio

class DaisyAPIClient:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def get_portfolio(self, currency="USD", sector=None):
        params = {"currency": currency}
        if sector:
            params["sector"] = sector
        
        response = await self.client.get(f"{self.base_url}/api/v1/portfolio", params=params)
        response.raise_for_status()
        return response.json()
    
    async def add_position(self, position):
        response = await self.client.post(
            f"{self.base_url}/api/v1/portfolio/add",
            json=position
        )
        response.raise_for_status()
        return response.json()
    
    async def get_risk_metrics(self, tickers):
        params = {"tickers": ",".join(tickers)}
        response = await self.client.get(
            f"{self.base_url}/api/v1/analytics/realized-risk",
            params=params
        )
        response.raise_for_status()
        return response.json()
    
    async def close(self):
        await self.client.aclose()

# Usage
async def main():
    client = DaisyAPIClient()
    
    try:
        # Get portfolio
        portfolio = await client.get_portfolio(currency="INR")
        print(f"Portfolio value: ₹{portfolio['total_value']:,.2f}")
        
        # Add position
        position = {
            "ticker": "RELIANCE",
            "weight": 0.15,
            "quantity": 100,
            "buy_price": 2500.0,
            "region": "IN"
        }
        
        result = await client.add_position(position)
        print(f"Added position: {result['ticker']}")
        
        # Get risk metrics
        risk = await client.get_risk_metrics(["RELIANCE", "TCS"])
        print(f"Portfolio volatility: {risk['portfolio']['annual_volatility']:.2%}")
        
    finally:
        await client.close()

# Run
asyncio.run(main())
```

#### Using FastAPI Client
```python
from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.get("/external/portfolio/{ticker}")
async def get_external_portfolio(ticker: str):
    # Make request to Daisy API
    async with httpx.AsyncClient() as client:
        response = await client.get(f"http://localhost:8000/api/v1/portfolio/{ticker}")
        return response.json()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
```

## Testing Integration

### API Testing with pytest
```python
import pytest
import httpx
import asyncio
from backend.app.models.schemas import PortfolioPositionCreate

@pytest.mark.asyncio
async def test_add_portfolio_position():
    async with httpx.AsyncClient() as client:
        position = PortfolioPositionCreate(
            ticker="TEST",
            weight=0.1,
            quantity=100,
            buy_price=50.0,
            region="US"
        )
        
        response = await client.post(
            "http://localhost:8000/api/v1/portfolio/add",
            json=position.dict()
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["ticker"] == "TEST"
        assert data["weight"] == 0.1

@pytest.mark.asyncio
async def test_analytics_endpoints():
    async with httpx.AsyncClient() as client:
        # Test realized risk
        response = await client.get(
            "http://localhost:8000/api/v1/analytics/realized-risk?tickers=AAPL,MSFT"
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "portfolio" in data
        assert "positions" in data
        
        # Test factor exposure
        response = await client.get(
            "http://localhost:8000/api/v1/analytics/factor-exposure?tickers=AAPL"
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "portfolio" in data
        assert "r_squared" in data
```

## Deployment Considerations

### Environment Variables
```bash
# Database
DATABASE_URL=sqlite:///./data/daisy.db

# API Configuration
ENVIRONMENT=production
CORS_ORIGINS=https://daisy-risk-engine.com,https://app.daisy-risk-engine.com
YFINANCE_TIMEOUT=30
CACHE_TTL_MINUTES=60

# Security
SECRET_KEY=your-secret-key-here
```

### Docker Configuration
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Production Deployment
- Use Gunicorn with multiple workers
- Configure proper database connection pooling
- Set up monitoring and alerting
- Implement backup strategies for SQLite or migrate to PostgreSQL
- Configure load balancing for high availability

---

This comprehensive documentation provides developers with all the necessary information to effectively integrate with and utilize the Daisy Risk Engine Backend API. The API is designed with flexibility, performance, and developer experience in mind, offering both REST and real-time WebSocket interfaces for comprehensive portfolio and risk analytics.