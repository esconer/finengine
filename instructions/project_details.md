# 🎯 COMPLETE 10-STEP DAISY RISK ENGINE IMPLEMENTATION GUIDE
## For AI-Assisted Vibe Coding with Minimax M2 & Gemini 2.5 Pro

**Updated: November 2025**
**Tech Stack**: Next.js 16 + React 19 + Bun | FastAPI + uv + Python 3.11

***

# 📋 TABLE OF CONTENTS
1. [Project Overview](#project-overview)
2. [Environment Setup](#environment-setup)
3. [Step-by-Step Guide with LLM Prompts](#step-by-step-guide)
4. [MCP Context7 Integration](#mcp-context7-integration)
5. [Complete Code Templates](#complete-code-templates)

***

# 🏗️ PROJECT OVERVIEW

## Architecture Diagram
```
┌─────────────────────────────────────────────────────────────┐
│                    DAISY RISK ENGINE                        │
├──────────────────────────┬──────────────────────────────────┤
│     FRONTEND (Bun)       │      BACKEND (uv)                │
├──────────────────────────┼──────────────────────────────────┤
│ • Next.js 16             │ • FastAPI 0.120.3                │
│ • React 19               │ • SQLite                         │
│ • TypeScript 5.7         │ • yfinance (primary)             │
│ • Tailwind CSS           │ • arch, quantstats, riskfolio    │
│ • Recharts 3.3           │ • pandas, numpy, scipy           │
│ • Zustand 5.0            │ • statsmodels                    │
│ • TanStack Query 5.59    │ • Python 3.11+                   │
│ • shadcn/ui              │                                  │
└──────────────────────────┴──────────────────────────────────┘
         ↓                              ↓
  http://localhost:3000      http://localhost:8000/api/v1
```

## Data Flow
```
yfinance (primary) 
    ↓
→ Fetch OHLCV + Adjusted Close
→ Auto-handle corporate actions
→ Cache in SQLite
↓
FastAPI Analytics Engine
    ├─ Realized Risk (quantstats)
    ├─ Forecast Risk (arch GARCH/EGARCH)
    ├─ Factor Exposures (statsmodels OLS)
    ├─ Portfolio Optimization (riskfolio-lib)
    └─ Risk Contributions
↓
React Dashboard (Next.js)
    ├─ Portfolio Summary
    ├─ Risk Analytics
    ├─ Factor Analysis
    ├─ Stress Testing
    ├─ Concentration
    ├─ Liquidity
    └─ Volatility Sizing
```

***

# ⚙️ ENVIRONMENT SETUP INSTRUCTIONS

## Prerequisites
```bash
# Required: Bun (replaces Node.js/npm)


# Required: uv (replaces pip)


# Required: Python 3.11+
python3 --version  # Should be 3.11 or higher

# Optional but recommended: Git
git --version
```

## Verify Installations
```bash
bun --version      # Should be latest (1.x)
uv --version       # Should be latest (0.4.x+)
python3 --version  # Should be 3.11+
```

***

# 🚀 STEP-BY-STEP GUIDE WITH LLM PROMPTS

---

## ✅ STEP 1: PROJECT INITIALIZATION & FRONTEND SETUP

### 1.1 Create Next.js 16 Project with Bun

**LLM Prompt:**
```
You are an expert full-stack developer. Initialize a new Daisy Risk Engine project.

TASK: Create a Next.js 16 project with the following specifications:

PROJECT DETAILS:
- Framework: Next.js 16.0.1 with App Router
- Runtime: Bun (not Node.js)
- Language: TypeScript 5.7
- Styling: Tailwind CSS 3.4.14
- Package Manager: Bun (use "bun add" syntax, not npm)

SPECIFICATIONS:
1. Create project with: bun create next-app@latest frontend --typescript --tailwind --app
2. Initialize Git repository
3. Create .env.local with:
   NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
   NEXT_PUBLIC_APP_NAME=Daisy Risk Engine

4. Create directory structure:
   /frontend
   ├─ /app
   │  ├─ layout.tsx
   │  ├─ page.tsx
   │  ├─ /dashboard
   │  │  └─ layout.tsx
   │  └─ /api (optional)
   ├─ /components
   │  ├─ /ui
   │  ├─ /charts
   │  └─ /layout
   ├─ /lib
   │  ├─ api.ts
   │  ├─ store.ts
   │  └─ utils.ts
   ├─ /types
   │  └─ index.ts
   ├─ /hooks
   │  └─ useAPI.ts
   ├─ bun.lockb (auto-generated)
   └─ package.json

INSTRUCTIONS:
- Use bun create instead of npx create-next-app
- Configure Tailwind with dark mode support
- Set up TypeScript strict mode
- Create a basic layout with header placeholder
- Do NOT install dependencies yet (we'll do that separately)

OUTPUT:
Generate the complete initial project structure and files.
```

### 1.2 Install Frontend Dependencies with Bun

**LLM Prompt:**
```
PROJECT: Daisy Risk Engine - Frontend Setup (Next.js 16 + Bun)

TASK: Add all required dependencies for the financial dashboard frontend.

DEPENDENCIES TO ADD (use "bun add" syntax):

Core Dependencies:
- zustand@5.0.2 (state management)
- @tanstack/react-query@5.59.16 (data fetching & caching)
- @tanstack/react-table@8.20.5 (headless table component)
- axios@1.7.7 (HTTP client)
- recharts@3.3.0 (charting library)
- date-fns@4.1.0 (date utilities)
- papaparse@5.4.1 (CSV parsing)

UI Components & Styling:
- clsx@2.1.1 (classname utility)
- tailwind-merge@2.5.4 (Tailwind class merging)
- lucide-react@0.454.0 (icon library)
- class-variance-authority@0.7.1 (component variants)

Radix UI Components (for shadcn/ui):
- @radix-ui/react-dialog@1.1.2
- @radix-ui/react-dropdown-menu@2.1.2
- @radix-ui/react-select@2.1.2
- @radix-ui/react-tabs@1.1.1
- @radix-ui/react-tooltip@1.1.4
- @radix-ui/react-slot@1.1.0

Dev Dependencies:
- vitest@2.1.4 (testing framework)
- @testing-library/react@16.0.1
- @testing-library/jest-dom@6.6.3

INSTRUCTIONS:
1. Use "bun add" for main dependencies
2. Use "bun add --save-dev" for dev dependencies
3. After installation, initialize shadcn/ui: bunx shadcn@latest init
4. Add these shadcn components: button card table tabs dialog select input

NOTES:
- Bun automatically updates bun.lockb
- Skip npm-specific instructions; use Bun equivalents
- TypeScript types should be auto-resolved for most packages

OUTPUT:
Generate complete installation script and verify all packages are installed.
```

### 1.3 Create Frontend Project Structure

**LLM Prompt:**
```
PROJECT: Daisy Risk Engine - Frontend File Structure

TASK: Create the complete Next.js 16 file structure with essential configuration files.

FILES TO CREATE:

1. /frontend/next.config.ts
   - Enable Turbopack (default in Next.js 16)
   - Setup API rewrites for FastAPI backend
   - Configure environment variables
   - Disable React Compiler for now (optional)

2. /frontend/tsconfig.json
   - Enable strict mode
   - Configure path aliases (@/components, @/lib, etc.)
   - Target latest JavaScript

3. /frontend/app/layout.tsx (Root Layout)
   - Setup Providers component
   - Import global Tailwind CSS
   - Add React Query provider
   - Setup basic metadata

4. /frontend/app/page.tsx (Home Page)
   - Temporary landing page
   - Link to /dashboard/summary

5. /frontend/app/providers.tsx
   - React Query QueryClientProvider
   - Any other top-level providers

6. /frontend/lib/api.ts (API Client)
   - Axios instance with baseURL from env
   - All API endpoints (portfolio, analytics, data)
   - Error handling with type safety

7. /frontend/lib/store.ts (Zustand Store)
   - Portfolio state (positions, selected tickers)
   - UI state (dark mode, sidebar open, loading)
   - Analytics state (cache)

8. /frontend/lib/types.ts
   - TypeScript interfaces for:
     * Portfolio Position
     * Analytics Metrics
     * API Responses
     * Chart Data

9. /frontend/tailwind.config.ts
   - Dark mode support (class-based)
   - Extend colors, spacing
   - Setup for shadcn/ui

10. /frontend/.env.local
    NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1

INSTRUCTIONS:
- Use TypeScript strict mode
- Add JSDoc comments for clarity
- Include error boundaries
- Setup loading states
- Use functional components with hooks
- All API calls should be typed

CONTEXT:
- User wants vibe coding with LLMs
- Mobile responsive required
- Dark mode support needed
- Real-time data updates

OUTPUT:
Generate all files with complete, production-ready code.
```

***

## ✅ STEP 2: BACKEND INITIALIZATION & DATABASE SETUP

### 2.1 Initialize Backend with uv

**LLM Prompt:**
```
PROJECT: Daisy Risk Engine - Backend Setup (FastAPI + uv)

TASK: Initialize FastAPI backend with Python 3.11+ using uv package manager.

STEP-BY-STEP INSTRUCTIONS:

1. Create Backend Directory & Initialize uv Project
   - mkdir backend && cd backend
   - uv init
   - uv venv --python 3.11
   - Activate venv: source .venv/bin/activate (macOS/Linux)

2. Create pyproject.toml with all dependencies:

   Core Dependencies:
   - fastapi[standard]==0.120.3
   - uvicorn[standard]==0.32.1
   - yfinance==0.2.51 (PRIMARY DATA SOURCE)
   - pandas==2.2.3
   - numpy==2.3.0
   - scipy==1.14.1
   
   Financial Analytics:
   - arch==7.1.0 (GARCH/EGARCH models)
   - quantstats==0.0.62 (Realized risk metrics)
   - riskfolio-lib==7.0.1 (Portfolio optimization)
   - statsmodels==0.14.4 (OLS regression for factors)
   
   Database & ORM:
   - sqlalchemy==2.0.36
   - alembic==1.14.0
   
   Utilities:
   - python-dotenv==1.0.1
   - pydantic==2.9.2
   - pydantic-settings==2.6.1
   - python-multipart==0.0.17
   - requests==2.32.3
   - aiohttp==3.11.7

   Dev Dependencies:
   - pytest==8.3.4
   - pytest-asyncio==0.24.0
   - httpx==0.28.0
   - faker==33.1.0

3. Install all dependencies:
   uv sync

4. Verify installation:
   uv run python -c "import fastapi; import yfinance; print('✓ All packages OK')"

IMPORTANT NOTES:
- Use "uv add <package>" to add new packages (not pip)
- Use "uv sync" to install from pyproject.toml
- uv.lock is auto-generated (like package-lock.json)
- Python 3.11+ required (NumPy 2.x compatibility)

CONTEXT:
- User wants vibe coding with AI models
- yfinance is PRIMARY data source (not NSEPython yet)
- Local SQLite database
- FastAPI auto-generates OpenAPI docs at /docs

OUTPUT:
Generate complete pyproject.toml and installation instructions.
```

### 2.2 Create Backend Project Structure

**LLM Prompt:**
```
PROJECT: Daisy Risk Engine - Backend Structure (FastAPI)

TASK: Create complete FastAPI backend directory structure and essential files.

DIRECTORY STRUCTURE:
/backend
├─ pyproject.toml (already created in Step 2.1)
├─ uv.lock (auto-generated)
├─ .venv/ (virtual environment)
├─ .env (environment variables)
├─ .gitignore
├─ main.py (FastAPI entry point)
├─ /app
│  ├─ __init__.py
│  ├─ config.py (configuration & settings)
│  ├─ /api
│  │  ├─ __init__.py
│  │  ├─ portfolio.py (CRUD endpoints)
│  │  ├─ data.py (data fetching endpoints)
│  │  └─ analytics.py (risk calculation endpoints)
│  ├─ /services
│  │  ├─ __init__.py
│  │  ├─ data_service.py (yfinance wrapper)
│  │  ├─ analytics_service.py (risk calculations)
│  │  ├─ portfolio_service.py (portfolio logic)
│  │  └─ cache_service.py (caching layer)
│  ├─ /models
│  │  ├─ __init__.py
│  │  ├─ database.py (SQLAlchemy ORM models)
│  │  └─ schemas.py (Pydantic schemas)
│  ├─ /db
│  │  ├─ __init__.py
│  │  └─ database.py (SQLite connection & setup)
│  └─ /utils
│     ├─ __init__.py
│     ├─ logger.py
│     └─ helpers.py

KEY FILES TO CREATE:

1. /backend/.env
   DATABASE_URL=sqlite:///./data/daisy.db
   YFINANCE_TIMEOUT=30
   CACHE_TTL_MINUTES=60
   LOG_LEVEL=INFO

2. /backend/.gitignore
   .venv/
   *.db
   *.pyc
   __pycache__/
   .env
   .DS_Store
   *.log

3. /backend/main.py
   - Initialize FastAPI app
   - Add CORS middleware (allow localhost:3000)
   - Include all routers
   - Setup error handlers
   - Auto-create database tables on startup

4. /backend/app/config.py
   - Pydantic Settings class
   - Load environment variables
   - Database URL configuration

5. /backend/app/db/database.py
   - SQLAlchemy engine setup
   - Session factory
   - Base model class
   - Database initialization function

6. /backend/app/models/schemas.py
   - Pydantic models for all API request/response
   - Include validation rules
   - Add example data

7. /backend/app/models/database.py
   - SQLAlchemy ORM models:
     * PortfolioPosition
     * StockTimeseries
     * AnalyticsCache

SPECIFICATIONS:
- Use async/await (FastAPI native support)
- Type all parameters and return values
- Include docstrings for all functions
- Setup structured logging
- Create SQLite database in /data directory
- Auto-create tables on startup

IMPORTANT:
- yfinance is PRIMARY source (not NSEPython)
- Handle yfinance multi-index columns correctly (v0.2.51)
- SQLite for local storage
- Pydantic v2 syntax (not v1)

OUTPUT:
Generate all files with complete, production-ready code.
```

### 2.3 Database Models & Schemas

**LLM Prompt:**
```
PROJECT: Daisy Risk Engine - Database Schema (SQLAlchemy + Pydantic)

TASK: Create SQLAlchemy ORM models and Pydantic schemas for the financial dashboard.

CONTEXT:
- Using SQLAlchemy 2.0.36 with modern async patterns
- Pydantic 2.9.2 for validation
- SQLite for local storage
- Need to handle time-series financial data
- Support for analytics caching

MODELS TO CREATE:

1. PortfolioPosition (SQLAlchemy Model)
   Fields:
   - id: Integer (PK)
   - ticker: String(10) - stock ticker (e.g., "AAPL")
   - weight: Float - portfolio weight (0-1)
   - region: String(10) - default "US"
   - primary_source: String(20) - "yfinance", "nsepy", "alphavantage"
   - fallback_source: String(20) - optional
   - last_validated_source: String(20) - which source succeeded
   - last_price: Float - latest price from yfinance
   - market_value: Float - position value in portfolio
   - sector: String(50) - from yfinance info
   - industry: String(50) - from yfinance info
   - custom_name: String(100) - optional user note
   - added_on: DateTime - when position was added
   - updated_on: DateTime - last update timestamp

2. StockTimeseries (SQLAlchemy Model)
   Fields:
   - id: Integer (PK)
   - ticker: String(10) - index on this
   - date: Date - trading date
   - open: Float - OHLCV data
   - high: Float
   - low: Float
   - close: Float
   - adj_close: Float - yfinance auto-adjusted
   - volume: Integer
   - source_used: String(20)
   - fetch_status: String(20) - "fresh", "cached", "failed"
   - fetched_on: DateTime
   - Indexes: (ticker, date)

3. AnalyticsCache (SQLAlchemy Model)
   Fields:
   - id: Integer (PK)
   - ticker: String(10)
   - metric_name: String(50) - "sharpe", "sortino", "max_drawdown", etc.
   - metric_value: Float
   - calculation_date: DateTime
   - calculated_at: DateTime
   - expires_at: DateTime - for TTL-based cache invalidation
   - model_params: JSON - store parameters used

4. FetchLog (SQLAlchemy Model)
   Fields:
   - id: Integer (PK)
   - ticker: String(10)
   - timestamp: DateTime
   - primary_attempt: Boolean
   - fallback_attempt: Boolean
   - status: String(20) - "success", "failed"
   - error_message: String(500)
   - source_used: String(20)

PYDANTIC SCHEMAS:

1. PositionCreate (Request)
   - ticker: str (required, validation: uppercase, length 1-10)
   - weight: float (required, validation: 0 < weight <= 1)
   - region: str (default: "US", allowed: ["US", "IN", "GB", ...])
   - custom_name: str (optional)

2. PositionResponse (Response)
   - id: int
   - ticker: str
   - weight: float
   - last_price: float
   - market_value: float
   - sector: str
   - updated_on: datetime

3. PortfolioResponse (Response)
   - positions: List[PositionResponse]
   - total_value: float
   - total_positions: int
   - total_weight: float

4. StockDataResponse (Response)
   - ticker: str
   - date: date
   - open: float
   - high: float
   - low: float
   - close: float
   - adj_close: float
   - volume: int
   - source: str

REQUIREMENTS:
- All models use type hints
- Include validation rules in Pydantic
- Add example data in model_config
- Use datetime.datetime for timestamps
- Support JSON serialization
- Include docstrings

INSTRUCTIONS:
1. Create /app/models/database.py with SQLAlchemy models
2. Create /app/models/schemas.py with Pydantic schemas
3. Add model_config and examples to all Pydantic models
4. Setup relationships (ForeignKey if needed)
5. Add database indexes for common queries
6. Include validation decorators

OUTPUT:
Generate all models and schemas with complete type safety and validation.
```

***

## ✅ STEP 3: DATA FETCHING SERVICE WITH YFINANCE

### 3.1 Create yfinance Data Service

**LLM Prompt:**
```
PROJECT: Daisy Risk Engine - Data Fetching Service (yfinance Primary)

TASK: Create a robust data fetching service using yfinance as the primary source.

CONTEXT & REQUIREMENTS:
- yfinance 0.2.51 returns multi-index DataFrames for multiple tickers
- Handle yfinance data structure changes properly
- Auto-adjusted close (yfinance handles corporate actions!)
- Caching layer for performance
- Error handling with fallback strategy
- Support for future NSEPython/AlphaVantage integration
- Async support for FastAPI

KEY CHALLENGES:
1. yfinance 0.2.51 Multi-Index Columns Issue:
   - Old (v0.2.40): df[['Open', 'High', 'Low', 'Close', 'Volume']]
   - New (v0.2.51): df[('Open', 'AAPL'), ('High', 'AAPL'), ...] MultiIndex
   - Solution: Flatten columns or use single ticker download

2. Auto-Adjusted Close:
   - yfinance AUTOMATICALLY adjusts for:
     * Stock splits
     * Dividends
     * Bonus issues
   - Saves us from manual corporate action handling!

3. Fallback Strategy:
   - Primary: yfinance (reliable, free, auto-adjusted)
   - Future: NSEPython (for Indian stocks if needed)
   - Future: AlphaVantage (as secondary fallback)

FILES TO CREATE:

1. /app/services/data_service.py
   Class: DataService
   Methods:
   
   a) fetch_historical_data(ticker: str, start: str, end: str, force_refresh: bool = False) -> pd.DataFrame
      - Check cache first (SQLite)
      - If cache miss or force_refresh, call yfinance
      - Handle yfinance multi-index columns
      - Extract: date, open, high, low, close, adj_close, volume
      - Store in SQLite cache
      - Return normalized DataFrame
   
   b) fetch_quote(ticker: str) -> dict
      - Get latest price and info
      - Extract: current_price, volume, market_cap, sector, industry
      - Use yf.Ticker().info for metadata
   
   c) fetch_ohlcv_batch(tickers: List[str], days: int = 252) -> dict
      - Fetch multiple tickers efficiently
      - Add delays between requests (yfinance rate limiting)
      - Return dict keyed by ticker
   
   d) validate_ticker(ticker: str) -> bool
      - Check if ticker exists
      - Try to fetch 1 day of data
      - Return success/failure
   
   e) get_corporate_actions(ticker: str) -> dict
      - Extract split/dividend history
      - Note: yfinance already adjusted for these!
      - Return info for display only

2. /app/services/cache_service.py
   Class: CacheService
   
   Methods:
   - get(ticker: str, start: str, end: str) -> Optional[pd.DataFrame]
   - set(ticker: str, start: str, end: str, data: pd.DataFrame) -> None
   - is_expired(ticker: str, ttl_minutes: int) -> bool
   - invalidate(ticker: str) -> None
   - clear_all() -> None
   
   Storage:
   - SQLite for persistence
   - In-memory LRU for hot data

3. /app/db/database.py (Enhanced)
   Function: init_db()
   - Create tables on startup
   - Add sample data for testing
   
   Function: get_db_session()
   - Return SQLAlchemy session
   - Context manager for transactions

IMPLEMENTATION NOTES:

1. Handle yfinance Multi-Index Columns:
   ```
   # ✅ Correct approach for yfinance 0.2.51
   df = yf.download('AAPL', start='2025-01-01', end='2025-01-31')
   # Returns multi-index columns for multi-ticker
   
   # For single ticker, flatten automatically:
   df.columns = df.columns.get_level_values(0)
   ```

2. Caching Strategy:
   - Store raw OHLCV in SQLite
   - TTL: 60 minutes (configurable)
   - On cache hit, return immediately
   - On cache miss, fetch fresh

3. Error Handling:
   - Retry failed requests (3 attempts)
   - Log all failures
   - Return cached data if available
   - Raise error only if no cache

4. Performance:
   - Batch downloads when possible
   - Add delays (0.5-1s) between requests
   - Use threading for concurrent requests
   - Cache aggressively

INSTRUCTIONS FOR LLM:
- Write clean, readable code
- Include comprehensive error handling
- Add type hints everywhere
- Include docstrings with examples
- Setup proper logging
- Make it testable
- Handle edge cases (missing data, holidays, etc.)

OUTPUT:
Generate complete data service with:
1. Main DataService class
2. CacheService class
3. Error handling
4. Logging
5. Type safety
6. Example usage
```

### 3.2 Create API Endpoints for Data Fetching

**LLM Prompt:**
```
PROJECT: Daisy Risk Engine - Data Fetching API Endpoints

TASK: Create FastAPI endpoints for fetching and managing market data.

CONTEXT:
- Using FastAPI 0.120.3 (modern async syntax)
- Endpoints should support real-time and cached data
- Force-refresh parameter for bypassing cache
- TypeScript compatibility (frontend uses axios)
- Proper HTTP status codes and error messages

ENDPOINTS TO CREATE (in /app/api/data.py):

1. GET /data/{ticker}
   Query Parameters:
   - start: str (YYYY-MM-DD) - optional, default 1 year ago
   - end: str (YYYY-MM-DD) - optional, default today
   - force_refresh: bool - optional, default false
   
   Response:
   {
     "ticker": "AAPL",
     "data": [
       {
         "date": "2025-01-01",
         "open": 150.0,
         "high": 152.0,
         "low": 149.0,
         "close": 151.0,
         "adj_close": 151.0,
         "volume": 1000000
       }
     ],
     "source": "yfinance",
     "from_cache": false,
     "metadata": {
       "sector": "Technology",
       "industry": "Consumer Electronics"
     }
   }

2. GET /data/quote/{ticker}
   Response:
   {
     "ticker": "AAPL",
     "current_price": 151.5,
     "volume": 50000000,
     "market_cap": 2500000000000,
     "sector": "Technology",
     "industry": "Consumer Electronics",
     "52_week_high": 200.0,
     "52_week_low": 140.0,
     "pe_ratio": 25.5,
     "dividend_yield": 0.45
   }

3. POST /data/batch
   Request:
   {
     "tickers": ["AAPL", "MSFT", "GOOGL"],
     "start": "2025-01-01",
     "end": "2025-10-01",
     "force_refresh": false
   }
   
   Response:
   {
     "data": {
       "AAPL": [...timeseries...],
       "MSFT": [...timeseries...],
       "GOOGL": [...timeseries...]
     },
     "failed_tickers": []
   }

4. POST /data/validate
   Request: { "ticker": "AAPL" }
   Response: { "valid": true, "message": "Ticker exists" }

5. POST /data/refresh
   Request: { "tickers": ["AAPL", "MSFT"] }
   Response: { "refreshed": 2, "failed": 0 }

6. GET /data/config
   Response:
   {
     "primary_source": "yfinance",
     "cache_ttl_minutes": 60,
     "enable_cache": true
   }

7. PUT /data/config
   Request:
   {
     "cache_ttl_minutes": 120,
     "enable_cache": true
   }

IMPLEMENTATION REQUIREMENTS:

1. Error Handling:
   - 400: Invalid ticker
   - 404: No data found
   - 500: Server error
   - Include error message in response

2. Type Safety:
   - Use Pydantic models for request/response
   - Type all function parameters
   - Return typed responses

3. Performance:
   - Cache responses
   - Validate input early
   - Return only needed data
   - Support partial failures in batch

4. Logging:
   - Log all requests
   - Log cache hits/misses
   - Log errors with context

5. Security:
   - Validate ticker format (alphanumeric, 1-10 chars)
   - Rate limiting (future enhancement)
   - Timeout protection

INSTRUCTIONS:
- Use async/await for all functions
- Include comprehensive docstrings
- Add example requests/responses
- Handle edge cases
- Make testable with dependency injection
- Include proper HTTP status codes

OUTPUT:
Generate complete /app/api/data.py with all endpoints fully implemented.
```

***

## ✅ STEP 4: PORTFOLIO MANAGEMENT API

### 4.1 Create Portfolio CRUD Endpoints

**LLM Prompt:**
```
PROJECT: Daisy Risk Engine - Portfolio Management API

TASK: Create complete CRUD endpoints for portfolio position management with validation.

CONTEXT:
- Single-user local application (no authentication needed)
- Portfolio positions with weights, sectors, and market values
- Real-time price updates from yfinance
- Auto-CSV backup on changes
- Weight normalization (sum should equal 1)
- Validation using yfinance data

ENDPOINTS TO CREATE (in /app/api/portfolio.py):

1. GET /portfolio
   Query Parameters:
   - region: str (optional, filter by region)
   - sector: str (optional, filter by sector)
   
   Response:
   {
     "positions": [
       {
         "id": 1,
         "ticker": "AAPL",
         "weight": 0.15,
         "current_price": 151.5,
         "market_value": 22725.0,
         "sector": "Technology",
         "last_updated": "2025-11-01T20:32:00Z"
       }
     ],
     "summary": {
       "total_value": 151500.0,
       "total_positions": 10,
       "total_weight": 1.0,
       "sectors": {"Technology": 0.45, "Finance": 0.35, ...}
     }
   }

2. POST /portfolio/add
   Request:
   {
     "ticker": "AAPL",
     "weight": 0.15,
     "region": "US",
     "custom_name": "Apple Inc. Core Holding"
   }
   
   Response (201 Created):
   {
     "id": 1,
     "ticker": "AAPL",
     "weight": 0.15,
     "market_value": 22725.0,
     "created_at": "2025-11-01T20:32:00Z"
   }

3. POST /portfolio/bulk_add
   Request:
   {
     "positions": [
       {"ticker": "AAPL", "weight": 0.15},
       {"ticker": "MSFT", "weight": 0.15},
       {"ticker": "GOOGL", "weight": 0.10}
     ],
     "auto_normalize": true
   }
   
   Response:
   {
     "added": 3,
     "failed": 0,
     "normalized": true,
     "positions": [...]
   }

4. GET /portfolio/{ticker}
   Response:
   {
     "id": 1,
     "ticker": "AAPL",
     "weight": 0.15,
     "current_price": 151.5,
     "market_value": 22725.0,
     "sector": "Technology",
     "industry": "Consumer Electronics",
     "pe_ratio": 25.5,
     "dividend_yield": 0.45,
     "shares_owned": 150,
     "last_updated": "2025-11-01T20:32:00Z"
   }

5. PUT /portfolio/{ticker}
   Request:
   {
     "weight": 0.20,
     "custom_name": "Apple Inc. (Updated)"
   }
   
   Response: Updated position object

6. DELETE /portfolio/{ticker}
   Response: { "deleted": true, "message": "Position removed" }

7. POST /portfolio/import_csv
   Request: File upload (CSV)
   CSV Format:
   ```
   ticker,weight,region,custom_name
   AAPL,0.15,US,Apple Core
   MSFT,0.15,US,Microsoft Core
   ```
   
   Response:
   {
     "imported": 2,
     "failed": 0,
     "errors": []
   }

8. GET /portfolio/export_csv
   Response: Downloads CSV file with all positions and metadata

9. POST /portfolio/normalize
   Query: { "method": "proportional" }
   Response: Updated positions with normalized weights

VALIDATION RULES:

1. Ticker Validation:
   - Must be 1-10 uppercase alphanumeric characters
   - Must exist on yfinance
   - Check by attempting to fetch quote

2. Weight Validation:
   - Must be > 0
   - Must be <= 1
   - Total weight should not exceed 1.5 (warning if > 1)

3. Auto-Normalization:
   - If total weight > 1, scale all proportionally
   - Warn user about normalization
   - Store original and normalized weights

DATABASE OPERATIONS:

1. On Add:
   - Validate ticker via yfinance
   - Fetch current price
   - Fetch sector/industry info
   - Store in PortfolioPosition table
   - Trigger CSV export

2. On Update:
   - Update weight
   - Recalculate market value
   - Update timestamp

3. On Delete:
   - Remove from database
   - Update portfolio stats
   - Trigger CSV export

4. CSV Backup:
   - Auto-export to /data/portfolio_backup_YYYYMMDD_HHMMSS.csv
   - Keep last 10 backups
   - Include full position details

ERROR HANDLING:

- 400: Invalid ticker or weight
- 404: Position not found
- 409: Duplicate ticker
- 422: Validation error (return details)
- 500: Database error

INSTRUCTIONS:
- Use async functions for all database operations
- Include comprehensive validation
- Add proper error responses
- Make weight normalization optional but default true
- Include full metadata in responses
- Setup proper logging
- Make testable

OUTPUT:
Generate complete /app/api/portfolio.py with all endpoints fully implemented.
```

***

## ✅ STEP 5: ANALYTICS & RISK CALCULATION ENGINE

### 5.1 Create Analytics Service

**LLM Prompt:**
```
PROJECT: Daisy Risk Engine - Analytics Service (Risk Calculations)

TASK: Create comprehensive financial analytics service with realized & forecast risk metrics.

CONTEXT & REQUIREMENTS:
- Using: arch, quantstats, riskfolio-lib, statsmodels
- Calculate all metrics visible in PDF dashboard
- Support multiple risk models (EWMA, GARCH, EGARCH)
- Cache expensive calculations
- Async support for FastAPI
- TypeScript-compatible response formats
- Handle edge cases (missing data, short history)

ANALYTICS SERVICE COMPONENTS:

1. /app/services/analytics_service.py
   Class: AnalyticsService
   
   REALIZED RISK METRICS (from quantstats):
   
   a) calculate_realized_risk(returns: pd.Series, benchmark_returns: Optional[pd.Series] = None) -> dict
      Returns:
      - annual_return: float
      - annual_volatility: float
      - sharpe_ratio: float (risk-free rate = 0)
      - sortino_ratio: float (downside volatility)
      - skewness: float
      - kurtosis: float
      - max_drawdown: float
      - value_at_risk_95: float (percentile method)
      - cvar_95: float (conditional VaR)
      - hit_ratio: float (% positive returns)
      - beta_vs_benchmark: float (if benchmark provided)
      - up_capture: float (% gain in up markets)
      - down_capture: float (% loss in down markets)
      - tracking_error: float
      - information_ratio: float

   b) calculate_rolling_metrics(returns: pd.Series, window: int = 21) -> pd.DataFrame
      Returns time series of rolling:
      - Volatility (21D, 60D)
      - Sharpe ratio
      - Max drawdown

   FORECAST RISK METRICS (using arch for GARCH):
   
   c) forecast_volatility(returns: pd.Series, model_type: str = 'GARCH', horizon: int = 1) -> dict
      model_type: "EWMA" | "GARCH" | "EGARCH"
      Returns:
      - volatility_forecast: float
      - confidence_interval: tuple
      - model_params: dict

   d) calculate_garch_model(returns: pd.Series, p: int = 1, q: int = 1) -> tuple
      Returns: (fitted_model, forecast)

   e) forecast_var_cvar(returns: pd.Series, model_type: str = 'GARCH') -> dict
      Returns:
      - var_95_forecast: float
      - cvar_95_forecast: float
      - portfolio_var_dollar: float
      - portfolio_cvar_dollar: float

   FACTOR ANALYSIS (using statsmodels OLS):
   
   f) calculate_factor_exposures(portfolio_returns: pd.Series, factor_returns: dict) -> dict
      factor_returns keys: "market", "momentum", "size", "value", "min_vol", "rates", "quality", "volatility", "meme", "ai"
      Returns:
      - alphas: dict of individual betas
      - r_squared: float
      - adjusted_r_squared: float
      - factor_betas: dict

   g) factor_exposure_heatmap(portfolio_holdings: dict, factor_returns: dict) -> pd.DataFrame
      Returns matrix for heatmap visualization

   PORTFOLIO OPTIMIZATION & RISK CONTRIBUTION:
   
   h) calculate_risk_contributions(portfolio_weights: np.ndarray, returns_df: pd.DataFrame, method: str = 'variance') -> dict
      method: "variance" | "cvar" | "egarch"
      Returns:
      - contribution_pct: dict (per asset)
      - marginal_contribution: dict
      - risk_contribution_chart: dict

   i) calculate_portfolio_diversification(portfolio_weights: np.ndarray, correlation_matrix: pd.DataFrame) -> dict
      Returns:
      - herfindahl_index: float
      - effective_positions: float
      - diversification_ratio: float

   STRESS TESTING:
   
   j) run_stress_test(portfolio_holdings: dict, scenario: str) -> dict
      scenarios: "2018_q4", "2020_covid", "2022_inflation", "2025_tariffs", "volatility_spike"
      Returns:
      - max_drawdown: float
      - portfolio_loss_pct: float
      - position_impacts: dict
      - recovery_time: int (days estimate)

   CONCENTRATION ANALYSIS:
   
   k) calculate_concentration_metrics(portfolio_weights: np.ndarray, sectors: dict) -> dict
      Returns:
      - top_1_weight: float
      - top_3_weight: float
      - top_5_weight: float
      - top_10_weight: float
      - herfindahl_index: float
      - effective_positions: float
      - sector_concentration: dict
      - market_cap_concentration: dict

   LIQUIDITY METRICS:
   
   l) calculate_liquidity_metrics(portfolio_holdings: dict, market_data: dict) -> dict
      Returns:
      - overall_score: float (1-10)
      - liquidation_time_days: int (estimate)
      - bid_ask_spreads: dict
      - volume_scores: dict
      - liquidity_alerts: list

2. /app/services/risk_models.py
   Class: RiskModeler
   
   Methods:
   - fit_ewma(returns: pd.Series, span: int = 20) -> EWMAModel
   - fit_garch(returns: pd.Series, p: int = 1, q: int = 1) -> GARCHModel
   - fit_egarch(returns: pd.Series, p: int = 1, q: int = 1) -> EGARCHModel
   - forecast(model, horizon: int) -> Forecast

IMPLEMENTATION NOTES:

1. yfinance Data Handling:
   - Convert adj_close to returns: returns = np.log(price[t] / price[t-1])
   - Handle NaN values (holidays, missing data)
   - Annualize metrics (multiply by sqrt(252) for daily data)

2. Caching Strategy:
   - Cache calculations for 1 hour
   - Invalidate on new portfolio data
   - Store in SQLite with TTL

3. Performance:
   - Use vectorized operations (NumPy, Pandas)
   - Pre-compute correlation matrices
   - Parallel processing for multiple assets
   - Batch calculations

4. Error Handling:
   - Minimum 30 days of data required
   - Handle missing data gracefully
   - Warn if insufficient history
   - Return None for unavailable metrics

5. Type Safety:
   - All parameters typed
   - Return typed dictionaries
   - Use dataclasses for complex returns

SPECIFIC CALCULATIONS:

1. Sharpe Ratio:
   (mean_return - risk_free_rate) / volatility
   Annualized: (mean_return*252 - risk_free_rate) / (volatility * sqrt(252))

2. Sortino Ratio:
   Like Sharpe but uses downside volatility only

3. Max Drawdown:
   (Peak - Trough) / Peak during period

4. VaR (95%):
   5th percentile of returns (or use GARCH forecast)

5. CVaR (95%):
   Average of returns below VaR threshold

6. Rolling Volatility:
   21-day rolling standard deviation of returns

7. Factor Exposure:
   Beta = Covariance(asset_return, factor_return) / Variance(factor_return)
   (Use OLS regression from statsmodels)

INSTRUCTIONS FOR LLM:
- Write clean, efficient code
- Extensive error handling
- Full type hints
- Comprehensive docstrings with examples
- Handle edge cases
- Make testable with mock data
- Include logging for debugging

OUTPUT:
Generate complete analytics service with:
1. AnalyticsService class with all methods
2. RiskModeler class
3. Error handling and validation
4. Caching layer integration
5. Type safety throughout
6. Example calculations
7. Logging setup
```

### 5.2 Create Analytics API Endpoints

**LLM Prompt:**
```
PROJECT: Daisy Risk Engine - Analytics API Endpoints

TASK: Create FastAPI endpoints for accessing all risk analytics calculations.

CONTEXT:
- Expose AnalyticsService via REST API
- Support multiple models (EWMA, GARCH, EGARCH)
- Caching layer for performance
- Real-time calculations on demand
- Stream large datasets efficiently

ENDPOINTS TO CREATE (in /app/api/analytics.py):

1. GET /analytics/realized-risk
   Query Parameters:
   - tickers: str (comma-separated, or portfolio)
   - start: str (YYYY-MM-DD)
   - end: str (YYYY-MM-DD)
   
   Response:
   {
     "portfolio": {
       "annual_return": 0.3889,
       "annual_volatility": 0.2967,
       "sharpe_ratio": 0.94,
       "sortino_ratio": 1.55,
       "skewness": 4.38,
       "kurtosis": 52.47,
       "max_drawdown": -0.3508,
       "var_95": -0.0241,
       "cvar_95": -0.0344,
       "hit_ratio": 0.4775
     },
     "positions": {
       "AAPL": {...metrics per ticker...},
       "MSFT": {...}
     }
   }

2. GET /analytics/forecast-risk
   Query Parameters:
   - model: str ("EWMA" | "GARCH" | "EGARCH")
   - horizon: int (days ahead, default 1)
   - tickers: str (comma-separated)
   
   Response:
   {
     "model": "EGARCH",
     "horizon": 1,
     "portfolio": {
       "volatility_forecast": 0.715,
       "var_forecast": -0.0629,
       "cvar_forecast": -0.0799,
       "confidence_interval": [0.68, 0.75]
     },
     "positions": {
       "AAPL": {...forecasts...},
       "MSFT": {...}
     },
     "model_params": {
       "p": 1, "q": 1, "type": "EGARCH"
     }
   }

3. GET /analytics/factor-exposure
   Query Parameters:
   - tickers: str (comma-separated)
   - lookback_days: int (default 252)
   
   Response:
   {
     "portfolio": {
       "alpha": -0.01,
       "market": 0.79,
       "momentum": 0.22,
       "size": -0.59,
       "value": -0.59,
       "min_vol": -0.68,
       "quality": -0.08,
       "rates": 0.51,
       "volatility": -0.05,
       "meme": 0.22,
       "ai": -0.01
     },
     "positions": {
       "AAPL": {...factor betas...},
       "MSFT": {...}
     },
     "r_squared": 0.85,
     "adjusted_r_squared": 0.84
   }

4. GET /analytics/correlation-matrix
   Response:
   {
     "correlation": [
       ["AAPL", "MSFT", "GOOGL", ...],
       [1.00, 0.65, 0.58, ...],
       [0.65, 1.00, 0.72, ...],
       ...
     ]
   }

5. GET /analytics/concentration
   Response:
   {
     "largest_position": 0.15,
     "top_3": 0.39,
     "top_5": 0.55,
     "top_10": 0.898,
     "herfindahl_index": 0.094,
     "effective_positions": 10.7,
     "diversification_ratio": 1.8,
     "by_sector": {
       "Technology": 0.334,
       "Communication_Services": 0.395,
       "Finance": 0.15,
       ...
     }
   }

6. GET /analytics/liquidity
   Response:
   {
     "overall_score": 7.8,
     "liquidation_time_days": "2-5",
     "risk_level": "Medium",
     "by_position": {
       "AAPL": {
         "score": 9.0,
         "spread": 0.0021,
         "avg_volume": 12793498,
         "category": "High"
       },
       ...
     },
     "volume_stats": {
       "avg_volume": 22916193,
       "total_portfolio_volume": 320826697,
       "high_volume_pct": 60.0,
       "medium_volume_pct": 40.0,
       "low_volume_pct": 0.0
     }
   }

7. POST /analytics/stress-test
   Request:
   {
     "scenario": "2020_covid",
     "tickers": ["AAPL", "MSFT", ...]
   }
   
   Response:
   {
     "scenario": "2020_covid",
     "max_drawdown": -0.336,
     "portfolio_impact": -0.214,
     "position_impacts": {
       "AAPL": -0.28,
       "MSFT": -0.15,
       ...
     }
   }

8. GET /analytics/volatility-sizing
   Query Parameters:
   - model: str (default "EWMA")
   - target_volatility: float (default 0.15)
   
   Response:
   {
     "current_weights": {...},
     "recommended_weights": {
       "AAPL": 0.05,
       "MSFT": 0.11,
       ...
     },
     "trades": {
       "AAPL": {"shares_delta": -250, "amount": -40604},
       "MSFT": {"shares_delta": 139, "amount": 26745},
       ...
     },
     "target_volatility": 0.15
   }

9. GET /analytics/risk-score
   Response:
   {
     "overall_score": 43.0,
     "risk_level": "MEDIUM",
     "change": -7,
     "components": {
       "concentration": 20.9,
       "volatility": 17.4,
       "correlation": 16.3,
       "factor_risk": 34.9,
       "stress_test": 0.0,
       "market_risk": 10.5
     },
     "alerts": [
       "Maximum drawdown (-35.1%) is significant",
       "High exposure to MARKET factor (beta: 0.79)",
       "2 pairs with correlation > 0.7"
     ]
   }

10. GET /analytics/summary
    Response: Quick summary of all key metrics for dashboard

CACHING STRATEGY:

- Realized Risk: Cache 24 hours (historical data stable)
- Forecast Risk: Cache 1 hour (models can change)
- Factor Exposure: Cache 1 day
- Correlation: Cache 24 hours
- Stress Tests: Cache 7 days (scenarios stable)
- Risk Score: Cache 4 hours

ERROR HANDLING:

- 400: Invalid parameters
- 404: No data for period
- 422: Insufficient data for calculation
- 503: Calculation failed

PERFORMANCE CONSIDERATIONS:

- Pre-compute heavy calculations
- Use async where possible
- Stream large results
- Implement pagination for large datasets

INSTRUCTIONS:
- Use async/await
- Implement caching decorator
- Add proper error handling
- Include calculation metadata
- Make testable with fixtures
- Add comprehensive logging

OUTPUT:
Generate complete /app/api/analytics.py with all endpoints fully implemented.
```

***

## ✅ STEP 6: FRONTEND DASHBOARD LAYOUT & COMPONENTS

### 6.1 Create Dashboard Layout with Sidebar

**LLM Prompt:**
```
PROJECT: Daisy Risk Engine - Frontend Dashboard Layout (Next.js 16 + React 19)

TASK: Create main dashboard layout with navigation sidebar and responsive design.

CONTEXT:
- Next.js 16 with App Router
- React 19 with new hooks
- Tailwind CSS for styling
- Recharts 3.3 for charts
- Mobile responsive required
- Dark mode support

FILES TO CREATE:

1. /frontend/app/dashboard/layout.tsx
   - Main dashboard wrapper
   - Sidebar + main content layout
   - Responsive (hamburger menu on mobile)
   - User context provider
   - Dark mode toggle

2. /frontend/components/layout/Sidebar.tsx
   - Navigation items for all 8 dashboard pages
   - Collapsible on mobile
   - Icons using lucide-react
   - Active route highlighting
   - Dark mode aware

3. /frontend/components/layout/Header.tsx
   - App title "Daisy Risk Engine"
   - Data refresh button (force refresh)
   - Live/Manual toggle for data updates
   - Dark mode toggle
   - Mobile menu toggle

4. /frontend/components/ui/MetricCard.tsx
   - Displays: title, value, change%, icon
   - Color coding (green for positive, red for negative)
   - Loading state
   - Mobile responsive

5. /frontend/components/ui/DataTable.tsx
   - Sortable columns (using TanStack Table v8)
   - Filtering support
   - CSV export button
   - Pagination
   - Responsive (horizontal scroll on mobile)

6. /frontend/components/charts/ChartWrapper.tsx
   - Wrapper for Recharts components
   - Loading state
   - Error state
   - Legend
   - Tooltip with dark mode

LAYOUT STRUCTURE:

Desktop:
┌─────────────────────────────────┐
│ HEADER (refresh, dark toggle)   │
├────────┬──────────────────────┤
│        │                      │
│ SIDE   │  MAIN CONTENT        │
│ BAR    │  (page-specific)     │
│        │                      │
├────────┴──────────────────────┤
└─────────────────────────────────┘

Mobile (hamburger menu):
┌─────────────────────────────────┐
│ ☰ HEADER                       │
├─────────────────────────────────┤
│  MAIN CONTENT                   │
│  (sidebar hidden)               │
└─────────────────────────────────┘

NAVIGATION ITEMS (in Sidebar):

1. Portfolio Summary (icon: BarChart)
2. Realized Risk (icon: TrendingDown)
3. Forecast Risk (icon: LineChart)
4. Factor Exposure (icon: Grid)
5. Stress Testing (icon: AlertTriangle)
6. Concentration Risk (icon: Pie)
7. Liquidity Risk (icon: Droplets)
8. Volatility Sizing (icon: Sliders)

STYLING REQUIREMENTS:

- Dark mode: Use Tailwind's dark: prefix
- Colors:
  * Primary: Blue-600
  * Positive: Green-600
  * Negative: Red-600
  * Neutral: Gray-500
  * Background: White (light) / Gray-950 (dark)
- Spacing: Use Tailwind scale (4px base)
- Typography: 
  * Headings: font-bold
  * Body: font-regular
  * Small: font-light

RESPONSIVENESS:

- Desktop: sidebar always visible
- Tablet (768px): sidebar collapsible
- Mobile (<768px): hamburger menu, sidebar hidden by default
- Breakpoints: sm, md, lg, xl from Tailwind

DARK MODE IMPLEMENTATION:

- Toggle button in Header
- Store preference in localStorage
- Use next-themes OR manual implementation
- Tailwind dark: prefix for all dark styles

INSTRUCTIONS FOR LLM:
- Use TypeScript strict mode
- All components are Client Components ('use client')
- Use Tailwind for all styling (no CSS files)
- Include loading/error states
- Make fully responsive
- Include accessibility features (aria labels)
- Type all props with interfaces
- Include JSDoc comments

RESPONSIVE PATTERNS:

Mobile First (default mobile styles, then override with lg: prefix):
- Sidebar: hidden, hamburger shows it
- Grid: 1 column
- Tables: horizontal scroll
- Cards: full width

Desktop (lg:):
- Sidebar: always visible
- Grid: 2-4 columns
- Tables: normal
- Cards: sized

OUTPUT:
Generate complete layout files:
1. Dashboard layout
2. Sidebar component
3. Header component
4. MetricCard component
5. DataTable component
6. ChartWrapper component

All with full TypeScript, Tailwind, and dark mode support.
```

***

## ✅ STEP 7: CORE DASHBOARD PAGES (Summary & Realized Risk)

### 7.1 Portfolio Summary Dashboard Page

**LLM Prompt - WITH MCP CONTEXT7:**
```
PROJECT: Daisy Risk Engine - Portfolio Summary Page

📌 MCP CONTEXT7 USAGE:
Before generating code, retrieve documentation for:
- Next.js 16 App Router: context7://nextjs-16-app-router
- React 19 hooks (useEffect, useState, etc): context7://react-19-hooks
- TanStack Query v5: context7://tanstack-query-v5
- Tailwind CSS responsive design: context7://tailwind-responsive
- Recharts 3.3 components: context7://recharts-3.3

TASK: Create portfolio summary dashboard page with real-time data.

CONTEXT:
- Route: /dashboard/summary
- Displays portfolio overview and key metrics
- Real-time data fetching with React Query
- Charts using Recharts 3.3
- Mobile responsive
- Dark mode support

PAGE LAYOUT:

Top Section (Metrics):
┌─────┬─────┬─────┬─────┐
│ Portfolio │ Total │ Largest │ E-GARCH │
│ Value   │ Pos  │ Pos    │ Vol    │
└─────┴─────┴─────┴─────┘

Middle Section (Charts):
┌──────────────────┬──────────────────┐
│ Portfolio Pie    │ Risk Contri-     │
│ (positions)      │ bution Bar       │
└──────────────────┴──────────────────┘

Bottom Section (Table):
┌──────────────────────────────────────┐
│ Top Holdings Table                   │
│ Ticker | Weight | Price | Value      │
└──────────────────────────────────────┘

FILE TO CREATE:
/frontend/app/dashboard/summary/page.tsx

COMPONENT STRUCTURE:

```
'use client'

import { useQuery } from '@tanstack/react-query'
import { PortfolioPieChart } from '@/components/charts/PortfolioPieChart'
import { RiskContributionChart } from '@/components/charts/RiskContributionChart'
import { MetricCard } from '@/components/ui/MetricCard'
import { DataTable } from '@/components/ui/DataTable'
```

DATA TO FETCH:

1. GET /api/v1/portfolio
   - Current portfolio positions
   - Weights, prices, market values

2. GET /api/v1/analytics/summary
   - Portfolio value
   - Total positions
   - Risk metrics

3. GET /api/v1/analytics/realized-risk
   - Realized metrics
   - Return, volatility

4. GET /api/v1/analytics/forecast-risk
   - E-GARCH volatility
   - VaR, CVaR

IMPLEMENTATION REQUIREMENTS:

1. Metric Cards (Top Section):
   - Portfolio Value: format as currency
   - Total Positions: show count
   - Largest Position: show % and ticker
   - E-GARCH Volatility: show % with color

2. Charts (Middle Section):
   - Pie Chart: portfolio allocation by ticker
   - Bar Chart: risk contribution per position
   - Both should be interactive (click to drill down)

3. Holdings Table (Bottom):
   - Sortable columns: Ticker, Weight, Price, Market Value
   - CSV export button
   - Search/filter by ticker
   - Pagination if >20 positions

REACT QUERY SETUP:

- Query key: ['portfolio', 'analytics-summary']
- Stale time: 1 minute (60000ms)
- Cache time: 5 minutes
- Retry: 2 attempts on failure
- Show loading spinner while fetching
- Show error message if failed

STYLING REQUIREMENTS:

- Responsive grid (1 col mobile, 2-4 cols desktop)
- Spacing between sections: 1.5rem
- Card shadows: shadow-md
- Border radius: rounded-lg
- Dark mode: text-white, bg-gray-950

ERROR HANDLING:

- Show friendly error message
- Provide "Retry" button
- Log errors to console
- Fallback to cached data if available

LOADING STATES:

- Show skeleton loaders for cards
- Animate chart loading
- Disable interactions while loading
- Show percentage complete

INSTRUCTIONS FOR LLM:
- Consult MCP CONTEXT7 for framework docs
- Use TypeScript strict mode
- Add comprehensive error handling
- Include loading and error states
- Make responsive with Tailwind
- Use TanStack Query for data management
- Include accessibility attributes
- Add JSDoc comments

OUTPUT:
Generate complete /frontend/app/dashboard/summary/page.tsx with:
1. Component structure
2. Data fetching with React Query
3. Charts with Recharts
4. Responsive grid layout
5. Error and loading states
6. Full TypeScript typing
```

***

## ✅ STEP 8: REMAINING DASHBOARD PAGES (7 More Pages)

### 8.1-8.7 Generate All Remaining Pages

**LLM Prompt - WITH MCP CONTEXT7:**
```
PROJECT: Daisy Risk Engine - All Dashboard Pages (7 additional pages)

📌 MCP CONTEXT7 USAGE:
Use context7 for:
- Recharts 3.3 advanced charts: context7://recharts-charts
- TanStack Table advanced features: context7://tanstack-table-advanced
- Tailwind responsive grids: context7://tailwind-layouts

TASK: Generate all remaining 7 dashboard pages in parallel.

Pages to Create:

1. /dashboard/realized-risk/page.tsx
   Components:
   - Metrics table: Annual Return, Volatility, Sharpe, Sortino, Max Drawdown, VaR, CVaR
   - Rolling Volatility chart (line chart over time)
   - Rolling Sharpe chart
   - Dropdown to select time window: 21D, 60D, 252D
   - Export CSV button

2. /dashboard/forecast-risk/page.tsx
   Components:
   - Model selector dropdown: EWMA, GARCH, EGARCH
   - Forecast metrics table
   - Volatility forecast chart
   - VaR/CVaR forecast comparison
   - Model parameters display

3. /dashboard/factor-exposure/page.tsx
   Components:
   - Factor exposure heatmap (all assets vs all factors)
   - Factor details table with betas
   - Filter by asset
   - R² display (model fit quality)
   - Rolling factor exposures chart

4. /dashboard/stress-testing/page.tsx
   Components:
   - Scenario selector: 2018 Q4, 2020 COVID, 2022 Inflation, 2025 Tariffs, etc.
   - Max drawdown comparison chart (scenarios)
   - Position-level impact table
   - Factor stress test breakdown

5. /dashboard/concentration/page.tsx
   Components:
   - Concentration metrics cards: Herfindahl, Effective Positions, Top 3/5/10
   - Sector allocation pie chart
   - Market cap distribution
   - Concentration alerts (e.g., >30% in top 3)
   - Position concentration table

6. /dashboard/liquidity/page.tsx
   Components:
   - Liquidity score card (0-10)
   - Liquidation time estimate
   - Volume analysis chart (distribution)
   - Bid-ask spread analysis
   - Position liquidity details table
   - Volume-weighted average display

7. /dashboard/volatility-sizing/page.tsx
   Components:
   - Model selector dropdown
   - Target volatility input
   - Sizing recommendations table:
     * Current weight vs Recommended weight
     * Shares to buy/sell
     * Dollar amount impact
   - Pie chart: current vs recommended allocation
   - Trade summary (total to buy/sell)

GENERAL REQUIREMENTS FOR ALL PAGES:

1. Data Fetching:
   - Use React Query with appropriate cache times
   - Show loading skeleton
   - Show error state with retry
   - Auto-refresh based on model choice

2. Interactivity:
   - Dropdowns for model/scenario selection
   - Charts should be clickable for drill-down
   - Tables sortable
   - Export to CSV on all pages

3. Styling:
   - Consistent with summary page
   - Responsive grid layouts
   - Dark mode support
   - Mobile-first responsive

4. Charts:
   - Use Recharts 3.3 components
   - Interactive tooltips
   - Legend
   - Proper labeling

5. Error Handling:
   - Friendly error messages
   - Retry buttons
   - Graceful degradation

IMPLEMENTATION PATTERN:

```
'use client'

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { analyticsApi } from '@/lib/api'

export default function PageName() {
  const [model, setModel] = useState('GARCH') // if applicable
  
  const { data, isLoading, error } = useQuery({
    queryKey: ['analytics', 'metric-name', model],
    queryFn: () => analyticsApi.getMetric(model),
    staleTime: 60000
  })

  if (isLoading) return <LoadingSkeleton />
  if (error) return <ErrorState error={error} />

  return (
    <div className="space-y-6">
      {/* Selector if applicable */}
      {/* Charts */}
      {/* Tables */}
    </div>
  )
}
```

SPECIFIC CHART TYPES NEEDED:

- Line Charts: Rolling metrics, volatility over time
- Bar Charts: Risk contribution, scenario impact
- Heatmaps: Factor exposure, correlation
- Pie Charts: Sector allocation, concentration
- Scatter: Factor vs return
- Box Plots: Volume distribution

API ENDPOINTS TO CALL:

GET /api/v1/analytics/realized-risk
GET /api/v1/analytics/forecast-risk?model={model}
GET /api/v1/analytics/factor-exposure
GET /api/v1/analytics/correlation-matrix
GET /api/v1/analytics/stress-test?scenario={scenario}
GET /api/v1/analytics/concentration
GET /api/v1/analytics/liquidity
GET /api/v1/analytics/volatility-sizing?model={model}

INSTRUCTIONS FOR LLM:
- Consult MCP CONTEXT7 for chart docs
- Use Recharts 3.3 (note: v3 has different API than v2)
- Make all pages mobile responsive
- Include dark mode support
- Add loading/error states
- Use TypeScript strict mode
- Make pages self-contained (no complex prop drilling)
- Include JSDoc comments

OUTPUT:
Generate all 7 complete page files with:
1. Correct API integration
2. Proper data fetching patterns
3. Charts and tables
4. Responsive layouts
5. Error/loading states
6. Full TypeScript typing
```

***

## ✅ STEP 9: REAL-TIME FEATURES, EXPORT & MOBILE OPTIMIZATION

### 9.1 Add Real-Time Features & Export Functionality

**LLM Prompt:**
```
PROJECT: Daisy Risk Engine - Real-Time Updates & Export Features

TASK: Add force refresh, live data toggle, and CSV export functionality across dashboard.

FEATURES TO IMPLEMENT:

1. Force Refresh Button (in Header):
   - Button in top-right corner
   - Loading spinner while refreshing
   - Refetch all React Query queries
   - Show toast notification on completion
   - "Last updated" timestamp

2. Live/Manual Toggle (in Header):
   - Toggle switch
   - Live mode: Auto-refresh every 5 minutes
   - Manual mode: Only refresh on button click
   - Store preference in localStorage
   - Persist across sessions

3. CSV Export (on every table):
   - Export button on each data table
   - Generates CSV with current data
   - Filename: daisy-portfolio-YYYYMMDD.csv
   - Opens download dialog

4. Auto-Backup:
   - Backend: auto-backup portfolio to CSV on changes
   - Frontend: show "Last backed up" timestamp
   - Accessible via portfolio page

IMPLEMENTATION:

1. Create useAutoRefresh Hook:
```
export function useAutoRefresh(enabled: boolean, interval: number = 5 * 60 * 1000) {
  const queryClient = useQueryClient()
  
  useEffect(() => {
    if (!enabled) return
    const timer = setInterval(() => {
      queryClient.invalidateQueries()
    }, interval)
    return () => clearInterval(timer)
  }, [enabled, interval, queryClient])
}
```

2. Create useCSVExport Hook:
```
export function useCSVExport<T>(data: T[], filename: string) {
  const export = () => {
    const csv = Papa.unparse(data)
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${filename}.csv`
    a.click()
  }
  return { export }
}
```

3. Update Header Component:
   - Add force refresh button
   - Add live/manual toggle
   - Add last updated timestamp
   - Show loading state during refresh

4. Update DataTable Component:
   - Add export CSV button
   - CSV filename: table-name-YYYYMMDD

5. Create useLocalStorage Hook:
   - Persist live mode preference
   - Read on component mount
   - Update on toggle

MOBILE OPTIMIZATION:

1. Touch-Friendly:
   - Larger buttons (48px minimum tap target)
   - Better spacing
   - Slide-in menus

2. Performance:
   - Code-split pages (lazy load)
   - Image optimization
   - Reduce animation on slower devices

3. Responsive Patterns:
   - Stack all grids vertically on mobile
   - Horizontal scroll for tables
   - Collapsible sections

4. Bottom Sheet Navigation (Optional):
   - Model/scenario selectors on mobile
   - Bottom sheet instead of dropdown

INSTRUCTIONS:
- Create reusable hooks
- Add toast notifications for feedback
- Make all features work offline (cached data)
- Handle errors gracefully
- Add loading states
- Mobile-first approach

OUTPUT:
Generate:
1. useAutoRefresh custom hook
2. useCSVExport custom hook
3. useLocalStorage custom hook
4. Updated Header component
5. Mobile optimization CSS
6. Toast notification system
```

***

## ✅ STEP 10: TESTING, OPTIMIZATION & DEPLOYMENT

### 10.1 Backend Testing & Deployment Setup

**LLM Prompt:**
```
PROJECT: Daisy Risk Engine - Backend Testing & Deployment

TASK: Create comprehensive test suite and deployment setup for FastAPI backend.

TESTING STRUCTURE:

1. Create /backend/tests/ directory:
   ├─ __init__.py
   ├─ conftest.py (pytest fixtures)
   ├─ test_api_portfolio.py
   ├─ test_api_data.py
   ├─ test_api_analytics.py
   ├─ test_services_data.py
   ├─ test_services_analytics.py
   └─ test_models.py

2. Test Coverage:

   a) Unit Tests (Services):
      - test_fetch_historical_data()
      - test_calculate_sharpe_ratio()
      - test_calculate_garch_model()
      - test_cache_operations()

   b) Integration Tests (APIs):
      - test_add_portfolio_position()
      - test_fetch_portfolio()
      - test_calculate_analytics_endpoint()
      - test_export_csv()

   c) Edge Cases:
      - Invalid ticker
      - Missing data
      - Database errors
      - API failures

PYTEST FIXTURES (conftest.py):

```
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base

@pytest.fixture
def db():
    """In-memory SQLite for testing"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    yield SessionLocal()

@pytest.fixture
def client(db):
    """FastAPI test client"""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)

@pytest.fixture
def sample_portfolio():
    return {
        "ticker": "AAPL",
        "weight": 0.15,
        "region": "US"
    }
```

TEST EXAMPLES:

```
def test_add_portfolio_position(client, sample_portfolio):
    response = client.post("/api/v1/portfolio/add", json=sample_portfolio)
    assert response.status_code == 201
    assert response.json()["ticker"] == "AAPL"

def test_fetch_portfolio(client):
    response = client.get("/api/v1/portfolio")
    assert response.status_code == 200
    assert "positions" in response.json()
```

PERFORMANCE OPTIMIZATION:

1. Backend Caching:
   - Redis (optional, local SQLite for now)
   - Cache TTLs: 1h for historical, 5m for real-time

2. Database Optimization:
   - Indexes on frequently queried columns
   - Connection pooling
   - Query optimization

3. API Optimization:
   - Async all I/O operations
   - Pagination for large datasets
   - Compress responses

DEPLOYMENT (LOCAL):

1. Create docker-compose.yml:
```
version: '3.8'

services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: sqlite:///./data/daisy.db
    volumes:
      - ./data:/app/data

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"

volumes:
  data:
```

2. Docker Setup:

   Dockerfile (backend):
   ```
   FROM python:3.11-slim
   RUN pip install uv
   WORKDIR /app
   COPY pyproject.toml uv.lock ./
   RUN uv sync --frozen --no-dev
   COPY . .
   CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0"]
   ```

   Dockerfile (frontend):
   ```
   FROM oven/bun:latest
   WORKDIR /app
   COPY package.json bun.lockb ./
   RUN bun install
   COPY . .
   RUN bun run build
   CMD ["bun", "start"]
   ```

3. Deployment Commands:

   ```
   # Build and run with Docker
   docker-compose up -d
   
   # View logs
   docker-compose logs -f backend
   docker-compose logs -f frontend
   
   # Stop
   docker-compose down
   ```

CI/CD (GitHub Actions):

```
name: Tests
on: [push, pull_request]

jobs:
  test-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - run: pip install uv
      - run: uv sync
      - run: uv run pytest

  test-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: oven-sh/setup-bun@v1
      - run: bun install
      - run: bun test
```

MONITORING:

1. Backend:
   - Log all errors
   - Monitor response times
   - Track cache hit rates

2. Frontend:
   - Monitor error rates
   - Track bundle size
   - User interaction metrics

INSTRUCTIONS:
- Write comprehensive tests
- Aim for >80% code coverage
- Test error cases
- Mock external APIs
- Use fixtures for DRY tests
- Setup CI/CD pipeline
- Automate deployment

OUTPUT:
Generate:
1. Complete test suite (all test files)
2. pytest conftest.py with fixtures
3. Dockerfile for both backend and frontend
4. docker-compose.yml
5. GitHub Actions CI/CD pipeline
6. README with deployment instructions
```

### 10.2 Frontend Testing & Build Optimization

**LLM Prompt:**
```
PROJECT: Daisy Risk Engine - Frontend Testing & Optimization

TASK: Create frontend test suite and optimize build size/performance.

TESTING:

1. Unit Tests (Vitest):
   - Component rendering
   - Hook behavior
   - Utility functions

2. Integration Tests:
   - Page navigation
   - API integration
   - Data flow

3. E2E Tests (Playwright):
   - Full user workflows
   - Dashboard interactions
   - Export functionality

TEST FILES:

```
/frontend/tests/
├─ components/
│  ├─ MetricCard.test.tsx
│  ├─ DataTable.test.tsx
│  └─ Charts.test.tsx
├─ pages/
│  ├─ summary.test.tsx
│  └─ realized-risk.test.tsx
└─ hooks/
   ├─ useAutoRefresh.test.ts
   └─ useCSVExport.test.ts
```

EXAMPLE TESTS:

```
import { render, screen } from '@testing-library/react'
import { MetricCard } from '@/components/ui/MetricCard'

describe('MetricCard', () => {
  it('renders metric value', () => {
    render(<MetricCard title="Portfolio Value" value={150000} />)
    expect(screen.getByText('Portfolio Value')).toBeInTheDocument()
    expect(screen.getByText('150000')).toBeInTheDocument()
  })
})
```

BUILD OPTIMIZATION:

1. Code Splitting:
   - Next.js 16 auto-splits
   - Dynamic imports for heavy components
   - Lazy load charts

2. Image Optimization:
   - Use Next.js Image component
   - WebP format
   - Responsive sizing

3. Bundle Analysis:
   ```
   bun run build
   npm install -g next-bundle-analyzer
   ANALYZE=true bun run build
   ```

4. Performance:
   - Remove unused dependencies
   - Tree-shake dead code
   - Minify CSS
   - Compress assets

PERFORMANCE METRICS:

- First Contentful Paint < 1.5s
- Largest Contentful Paint < 2.5s
- Cumulative Layout Shift < 0.1
- Time to Interactive < 3.5s

LIGHTHOUSE OPTIMIZATION:

- Performance: >90
- Accessibility: >90
- Best Practices: >90
- SEO: >90

INSTRUCTIONS:
- Write tests for all components
- Achieve >80% coverage
- Optimize bundle size <200KB gzipped
- Monitor performance metrics
- Setup performance testing in CI/CD

OUTPUT:
Generate:
1. All test files with examples
2. vitest.config.ts
3. playwright.config.ts
4. next.config.ts with optimization
5. Performance monitoring setup
6. Build size analysis script
```

***

# 🔌 MCP CONTEXT7 INTEGRATION GUIDE

## How to Use Context7 with Your LLM

When giving prompts to Minimax M2 or Gemini 2.5 Pro, include:

```
📌 MCP CONTEXT7 USAGE:

Before generating code, use context7 to retrieve:
- context7://nextjs-16-app-router
- context7://react-19-hooks
- context7://react-19-server-components
- context7://tanstack-query-v5
- context7://tanstack-table-v8
- context7://tailwind-responsive
- context7://tailwind-dark-mode
- context7://recharts-3.3
- context7://fastapi-latest
- context7://sqlalchemy-2.0
- context7://pydantic-v2
- context7://typescript-5.7
- context7://zustand-5.0
```

This ensures the LLM retrieves the latest framework documentation during code generation.

***

# 📝 COMPLETE SUMMARY TABLE

| Step | Component | Tech Stack | File | Status |
|------|-----------|-----------|------|--------|
| 1 | Frontend Init | Next.js 16 + Bun | setup.md | ✅ |
| 2 | Backend Init | FastAPI + uv | setup.md | ✅ |
| 3 | Data Fetching | yfinance | services/ | ✅ |
| 4 | Portfolio API | FastAPI | api/ | ✅ |
| 5 | Analytics | arch, quantstats | services/ | ✅ |
| 6 | Dashboard Layout | React 19 | components/ | ✅ |
| 7 | Summary Page | Recharts 3.3 | pages/ | ✅ |
| 8 | Other Pages | TanStack Table | pages/ | ✅ |
| 9 | Real-Time | React Query | hooks/ | ✅ |
| 10 | Testing & Deploy | Vitest + Docker | tests/ | ✅ |

***

# 🚀 QUICK START COMMANDS

### Frontend (Bun)
```bash
bun create next-app@latest frontend --typescript --tailwind --app
cd frontend
bun add zustand @tanstack/react-query axios recharts
bun run dev
```

### Backend (uv)
```bash
mkdir backend && cd backend
uv init
uv venv --python 3.11
source .venv/bin/activate
uv add fastapi[standard] yfinance pandas numpy arch quantstats riskfolio-lib
uv run uvicorn main:app --reload
```

***

