# Architecture Proposal: SQLite WAL Mode Caching & Multi-Tier Optimization

**Document Status**: Proposed / Draft for Future Implementation  
**Location**: `.scratch/caching-architecture-sqlite-wal-optimization.md`  
**Date**: September 2026  
**Context**: Evaluation following `bfinance v0.1.3` WAL engine hardening vs. `finengine` backend caching.

---

## 1. Executive Summary

Both `bfinance v0.1.3` and `finengine` employ SQLite Write-Ahead Logging (WAL) mode, but apply it to fundamentally different caching tiers. 

* **`bfinance`** implements a **stateless, lock-resilient L2 upstream gateway cache** designed to throttle and protect external rate-limits with atomic key-value upserts.
* **`finengine`** implements a **two-tier cache (in-memory L1 DataFrame cache + relational L2 database cache)** via SQLAlchemy and `aiosqlite`.

While `finengine` benefits from in-memory speed and rich relational SQL queries, it suffers from several concurrency anti-patterns:
1. **Missing `busy_timeout`** in connection pragmas, leading to potential `database is locked` exceptions under parallel analytics workloads.
2. **Non-atomic `DELETE`-then-`INSERT`** operations in `AnalyticsCache`, creating race conditions during concurrent metric calculations.
3. **Unbounded in-memory dictionary caching** in `DataService._in_memory_df_cache`, posing a long-term memory leak / OOM hazard.
4. **Coupled storage**, where high-frequency analytics and price cache writes churn the same database file (`finengine.db`) that holds critical portfolio transactions and positions.

This document details the comparative architecture, identifies root hazards, and provides a clear 4-step implementation blueprint to make `finengine` caching best-in-class.

---

## 2. Comparative Matrix: `bfinance` vs. `finengine`

| Architectural Dimension | `bfinance v0.1.3` SQLite Cache | `finengine` Current Cache |
| :--- | :--- | :--- |
| **Layer & Purpose** | Upstream HTTP/Scraper gateway cache | L1 In-Memory + L2 Relational application cache |
| **Storage Engine** | Standard library `sqlite3` direct connection | SQLAlchemy AsyncEngine via `aiosqlite` |
| **Storage File** | Isolated `~/.bfinance/cache.db` | Shared `backend/data/finengine.db` |
| **Data Format** | Serialized JSON blobs with TTL timestamps | Normalized relational rows (`MarketData`, `AnalyticsCache`) |
| **Concurrency Pragma** | `journal_mode=WAL`<br>`busy_timeout=5000` | `journal_mode=WAL`<br>`synchronous=NORMAL`<br>`mmap_size=268435456` (256MB) |
| **Thread / Process Safety** | `threading.Lock()` + WAL write isolation | Async event loop sessions |
| **Write Strategy** | **Atomic native upsert** (`INSERT ... ON CONFLICT DO UPDATE`) | **Delete-then-Insert** (two roundtrips, non-atomic) |
| **Memory Bounding** | Zero persistent memory overhead (reads directly from disk) | Unbounded Python `dict` (`_in_memory_df_cache`) |

---

## 3. Analysis of Current `finengine` Caching Hazards

### Hazard 1: Missing `busy_timeout` in SQLite Connection Pragmas
In `backend/app/db/database.py`, SQLite pragmas are registered via SQLAlchemy connection listener:
```python
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA temp_store=memory")
        cursor.execute("PRAGMA mmap_size=268435456")  # 256MB
        # MISSING: cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
```
**Impact**: In SQLite WAL mode, readers do not block writers and writers do not block readers, but **two writers still cannot write at the exact same moment**. Without `PRAGMA busy_timeout=5000`, a second write query that hits a momentary lock fails immediately with:
```
sqlite3.OperationalError: database is locked
```

### Hazard 2: Delete-then-Insert Anti-Pattern in `AnalyticsCache`
In `backend/app/services/cache_service.py`:
```python
async def set_cached_analytics(self, ticker, metric_name, metric_value, calculation_date, model_params=None):
    # Step 1: Delete
    await self.db.execute(
        delete(AnalyticsCache).where(
            AnalyticsCache.ticker == ticker,
            AnalyticsCache.metric_name == metric_name,
        )
    )
    # Step 2: Insert
    cache_entry = AnalyticsCache(...)
    self.db.add(cache_entry)
    await self.db.commit()
```
**Impact**:
* If two concurrent tasks compute metrics for the same symbol (e.g., VaR calculation triggered by a dashboard refresh and a background job), Task A deletes, Task B deletes, Task A inserts, Task B inserts — resulting in duplicate rows or transient locking.
* As documented in the codebase comments: *“duplicates previously made `get_cached_analytics` raise MultipleResultsFound (caught -> perpetual miss).”*

### Hazard 3: Unbounded In-Memory DataFrame Cache
In `backend/app/services/data_service.py`:
```python
class DataService:
    _in_memory_df_cache: Dict[str, Any] = {}
```
**Impact**:
* Each price history DataFrame stored consumes 50KB–2MB of RAM.
* Because this is a static dictionary without an eviction strategy, scanning or screening 2,000 tickers permanently retains 2,000 DataFrames in server memory until application restart.

### Hazard 4: Database File Coupling
`finengine.db` currently stores:
1. Critical entity models: `Portfolio`, `Position`, `Transaction`, `User`
2. High-frequency volatile cache: `MarketData` (tens of thousands of rows), `AnalyticsCache`, `FetchLog`
* High write churn from cache eviction and ingestion triggers frequent WAL checkpoints (`-wal` and `-shm` growth) on the primary transactional database file.

---

## 4. Target Multi-Tier Architecture

```mermaid
graph TD
    Client[API Request: Portfolio Risk / Metrics] --> L1{L1: Bounded LRU Memory Cache}
    
    L1 -->|Hit: < 0.5ms| Ret[Return Response]
    L1 -->|Miss| L2{L2: Dedicated Cache DB (WAL)}
    
    subgraph "L2 Isolated Cache Engine (data/cache.db)"
        L2 --> RelationalQuery[Query MarketData / AnalyticsCache]
        RelationalQuery -->|Hit: < 5ms| PopulateL1[Populate L1]
        PopulateL1 --> Ret
    end
    
    subgraph "Upstream Gateway Engine"
        RelationalQuery -->|Miss / Stale| UpstreamGateway[bfinance v0.1.3 Ticker / Engine]
        UpstreamGateway --> GatewayCache[bfinance WAL Gateway Cache]
        GatewayCache --> ScreenerAPI[Screener.in / Live Sources]
    end
    
    ScreenerAPI --> GatewayCache
    GatewayCache --> AtomicUpsert[Atomic SQLite ON CONFLICT Upsert]
    AtomicUpsert --> RelationalQuery
```

---

## 5. Implementation Blueprint

### Phase 1: Immediate Safety Fixes (Zero Breaking Changes)

#### A. Add `busy_timeout` in `backend/app/db/database.py`
Add `PRAGMA busy_timeout=5000;` to ensure any SQLite lock waits gracefully up to 5 seconds before erroring:
```python
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA temp_store=memory")
        cursor.execute("PRAGMA mmap_size=268435456")  # 256MB
        cursor.execute("PRAGMA busy_timeout=5000")    # 5s lock tolerance
        cursor.close()
```

#### B. Atomic Native Upsert in `backend/app/services/cache_service.py`
Replace delete-then-insert with native SQLite `insert().on_conflict_do_update()`:
```python
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

async def set_cached_analytics(
    self,
    ticker: str,
    metric_name: str,
    metric_value: float,
    calculation_date: datetime,
    model_params: Optional[Dict[str, Any]] = None
) -> None:
    try:
        expires_at = datetime.utcnow() + timedelta(minutes=self.ttl_minutes)
        
        stmt = sqlite_insert(AnalyticsCache).values(
            ticker=ticker,
            metric_name=metric_name,
            metric_value=metric_value,
            calculation_date=calculation_date,
            expires_at=expires_at,
            model_params=model_params or {}
        )
        
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker", "metric_name"],
            set_={
                "metric_value": stmt.excluded.metric_value,
                "calculation_date": stmt.excluded.calculation_date,
                "expires_at": stmt.excluded.expires_at,
                "model_params": stmt.excluded.model_params
            }
        )
        
        await self.db.execute(stmt)
        await self.db.commit()
    except Exception as e:
        logger.error(f"Error caching analytics: {e}")
        await self.db.rollback()
```
*(Requires `UniqueConstraint("ticker", "metric_name", name="uq_analytics_cache_ticker_metric")` in `AnalyticsCache`)*.

---

### Phase 2: Memory Bounding in `backend/app/services/data_service.py`

Replace the bare dictionary with a bounded LRU/TTL cache:
```python
from collections import OrderedDict
import threading
import time

class BoundedTTLCache:
    """Thread-safe, bounded in-memory LRU cache with TTL expiration."""
    def __init__(self, maxsize: int = 500, ttl_seconds: int = 300):
        self._maxsize = maxsize
        self._ttl = ttl_seconds
        self._data = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            if key not in self._data:
                return None
            ts, val = self._data[key]
            if time.time() - ts > self._ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return val

    def set(self, key: str, val: Any):
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (time.time(), val)
            if len(self._data) > self._maxsize:
                self._data.popitem(last=False)
```

---

### Phase 3: Storage Segregation (Production Architecture)

Separate volatile analytics/market data from relational portfolio accounting:
1. **`finengine_app.db`**:
   - `portfolios`, `positions`, `transactions`, `users`, `settings`
   - Backup schedule: High priority (point-in-time recovery, zero data loss)
2. **`finengine_cache.db`**:
   - `market_data`, `analytics_cache`, `fetch_logs`
   - Backup schedule: Ephemeral / Disposable (can be recreated on demand)
   - Configuration: Aggressive WAL checkpoints, smaller vacuum window

---

## 6. Verification and Regression Checklist

When executing this plan in the future:
1. Run `uv run pytest tests/test_coverage_india_data.py` and `tests/test_equity_research_and_screens.py`.
2. Concurrency stress test: Launch 20 parallel async requests against `/api/analytics/portfolio/{id}/risk` to confirm zero `OperationalError: database is locked`.
3. Memory verification: Query 1,000 distinct tickers via `DataService` and assert process RSS memory stays bounded under 250MB.
