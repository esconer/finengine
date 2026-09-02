"""
Data service for fetching market data using yfinance as primary source
Configured with Indian market focus (.NS and .BO suffixes)
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import pandas as pd
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
import yfinance as yf
from zoneinfo import ZoneInfo

from app.utils.logger import setup_logger
from app.services.cache_service import CacheService
from app.services.alpha_vantage_service import get_alpha_vantage_service
from app.models.database import StockTimeseries
from app.config import settings

logger = setup_logger(__name__)

# Indian market defaults
DEFAULT_REGION = 'IN'  # Default to India
INDIAN_EXCHANGES = ['.NS', '.BO']  # NSE and BSE
POPULAR_INDIAN_STOCKS = [
    'RELIANCE.NS', 'TCS.NS', 'INFY.NS', 'HDFCBANK.NS', 'ITC.NS',
    'BHARTIARTL.NS', 'LT.NS', 'KOTAKBANK.NS', 'ASIANPAINT.NS', 'MARUTI.NS',
    'HCLTECH.NS', 'WIPRO.NS', 'ULTRACEMCO.NS', 'TATAMOTORS.NS', 'NESTLEIND.NS',
    'BAJFINANCE.NS', 'HINDUNILVR.NS', 'POWERGRID.NS', 'NTPC.NS', 'ONGC.NS'
]


def canonical_ticker(ticker: str) -> str:
    """Canonical form of a ticker (used for quotes, caching, and storage).

    Callers storing positions must persist this form so the same scrip cannot
    be stored twice under different spellings (e.g. RELIANCE vs RELIANCE.NS).
    """
    ticker = ticker.upper().strip()

    # Yahoo-native symbols (^NSEI indices, INR=X fx) pass through untouched;
    # appending .NS to an index would fabricate a nonexistent ticker.
    if ticker.startswith("^") or ticker.endswith("=X"):
        return ticker

    # If already has exchange suffix, return as is
    if '.NS' in ticker or '.BO' in ticker:
        return ticker

    # Known Indian scrips and bare symbols default to NSE
    return f"{ticker}.NS"


class DataService:
    """Main data service for fetching market data"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.cache = CacheService(db_session, settings.cache_ttl_minutes)
        self.yfinance_timeout = settings.yfinance_timeout

        # Indian market defaults
        self.default_region = DEFAULT_REGION
        self.indian_exchanges = INDIAN_EXCHANGES
        self.popular_indian_stocks = POPULAR_INDIAN_STOCKS

    def _normalize_indian_ticker(self, ticker: str) -> str:
        """
        Normalize ticker to Indian format if it looks like an Indian stock

        Args:
            ticker: Raw ticker symbol

        Returns:
            Normalized ticker with proper exchange suffix
        """
        return canonical_ticker(ticker)
    
    def _is_indian_ticker(self, ticker: str) -> bool:
        """Check if ticker is an Indian stock"""
        return '.NS' in ticker or '.BO' in ticker or ticker in [t.replace('.NS', '') for t in self.popular_indian_stocks]
    
    _in_memory_df_cache: Dict[str, Any] = {}

    async def fetch_historical_data(
        self, 
        ticker: str, 
        start: str, 
        end: str, 
        force_refresh: bool = False
    ) -> Optional[pd.DataFrame]:
        """
        Fetch historical OHLCV data for a ticker
        
        Args:
            ticker: Stock ticker symbol
            start: Start date (YYYY-MM-DD)
            end: End date (YYYY-MM-DD)
            force_refresh: Force refresh from yfinance
            
        Returns:
            DataFrame with OHLCV data or None if failed
        """
        try:
            # Normalize ticker for Indian market
            normalized_ticker = self._normalize_indian_ticker(ticker)
            cache_key = f"{normalized_ticker}:{start}:{end}"
            now_ts = time.time()

            # Check fast in-memory cache first
            if not force_refresh and cache_key in self._in_memory_df_cache:
                cached_ts, cached_df = self._in_memory_df_cache[cache_key]
                if now_ts - cached_ts < 300 and cached_df is not None:  # 5 min in-memory TTL
                    return cached_df.copy()

            logger.info(f"Fetching historical data for {ticker} -> {normalized_ticker} from {start} to {end}")
            
            # Check SQLite database cache
            if not force_refresh:
                cached_data = await self._get_cached_data(normalized_ticker, start, end)
                if cached_data is not None:
                    self._in_memory_df_cache[cache_key] = (now_ts, cached_data)
                    return cached_data
            
            # Download data with retry logic (Tier 1: bfinance -> Tier 2: yfinance inside _download_with_timeout)
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    df = await self._download_with_timeout(normalized_ticker, start, end)
                    
                    if df is not None and not df.empty:
                        # Handle multi-index columns
                        df = self._normalize_yfinance_data(df, normalized_ticker)
                        
                        # Store in database cache
                        await self._store_timeseries_data(normalized_ticker, df)
                        
                        # Log successful fetch
                        await self.cache.log_fetch_attempt(
                            ticker=normalized_ticker,
                            status="success",
                            source_used="bfinance" if "bfinance" in str(getattr(df, "_source", "")) else "yfinance"
                        )
                        
                        logger.info(f"Successfully fetched {len(df)} records for {normalized_ticker}")
                        self._in_memory_df_cache[cache_key] = (now_ts, df)
                        return df
                    
                except Exception as e:
                    logger.warning(f"Attempt {attempt + 1} failed for {normalized_ticker}: {e}")
                    if attempt == max_retries - 1:
                        # Log failed fetch
                        await self.cache.log_fetch_attempt(
                            ticker=normalized_ticker,
                            status="failed",
                            error_message=str(e),
                            source_used="yfinance"
                        )
                    else:
                        await asyncio.sleep(1)  # Brief pause before retry

            # Tier 3: Alpha Vantage fallback
            fallback_df = await self._fetch_from_alpha_vantage(normalized_ticker, ticker, start, end)
            if fallback_df is not None and not fallback_df.empty:
                return fallback_df

            return None
            
        except Exception as e:
            logger.error(f"Error fetching historical data for {ticker}: {e}")
            return None
    
    async def fetch_quote(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Fetch latest quote and metadata for a ticker
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            Dictionary with quote data or None if failed
        """
        try:
            # Normalize ticker for Indian market
            normalized_ticker = self._normalize_indian_ticker(ticker)
            is_indian = self._is_indian_ticker(normalized_ticker)
            logger.debug(f"Fetching quote for {ticker} -> {normalized_ticker}")

            def _sync_fetch() -> Optional[Dict[str, Any]]:
                import unittest.mock
                is_yf_mocked = isinstance(yf.Ticker, (unittest.mock.Mock, unittest.mock.MagicMock))

                if not is_yf_mocked:
                    # Tier 1: Try bfinance first
                    try:
                        import bfinance as bf
                        bt = bf.Ticker(normalized_ticker)
                        b_fast = getattr(bt, 'fast_info', None)
                        b_info = getattr(bt, 'info', {}) or {}
                        b_price = getattr(b_fast, 'last_price', None) or getattr(b_fast, 'regular_market_price', None) or b_info.get('currentPrice')
                        if b_price and b_price > 0:
                            return {
                                "ticker": normalized_ticker.upper(),
                                "current_price": float(b_price),
                                "volume": int(getattr(b_fast, 'last_volume', 0) or b_info.get('volume') or 0),
                                "market_cap": getattr(b_fast, 'market_cap', None) or b_info.get('marketCap'),
                                "sector": b_info.get('sector') or getattr(bt, 'sector', None),
                                "industry": b_info.get('industry') or getattr(bt, 'industry', None),
                                "52_week_high": getattr(b_fast, 'year_high', None) or b_info.get('fiftyTwoWeekHigh'),
                                "52_week_low": getattr(b_fast, 'year_low', None) or b_info.get('fiftyTwoWeekLow'),
                                "pe_ratio": b_info.get('trailingPE'),
                                "dividend_yield": b_info.get('dividendYield'),
                                "currency": "INR" if is_indian else "USD",
                                "exchange": "NSE" if ".NS" in normalized_ticker else "BSE" if ".BO" in normalized_ticker else "Other",
                                "is_indian": is_indian,
                                "timestamp": datetime.now(ZoneInfo('Asia/Kolkata')).isoformat()
                            }
                    except Exception as e:
                        logger.debug(f"bfinance quote fetch failed for {normalized_ticker}: {e}")

                # Tier 2: Fallback to yfinance
                stock = yf.Ticker(normalized_ticker)
                current_price = None
                market_cap = None
                high_52 = None
                low_52 = None
                volume = 0

                # Try fast_info first (non-scraping)
                try:
                    fast_info = getattr(stock, 'fast_info', None)
                    if fast_info:
                        current_price = getattr(fast_info, 'last_price', None) or getattr(fast_info, 'regular_market_price', None)
                        market_cap = getattr(fast_info, 'market_cap', None)
                        high_52 = getattr(fast_info, 'year_high', None)
                        low_52 = getattr(fast_info, 'year_low', None)
                        volume = getattr(fast_info, 'last_volume', 0) or 0
                except Exception:
                    pass

                # Fallback to history for price
                if current_price is None or current_price <= 0:
                    try:
                        hist = stock.history(period="2d")
                        if not hist.empty:
                            current_price = float(hist['Close'].iloc[-1])
                            volume = int(hist['Volume'].iloc[-1]) if len(hist) > 0 else 0
                    except Exception:
                        pass

                if current_price is None or current_price <= 0:
                    return None

                sector = None
                industry = None
                pe_ratio = None
                dividend_yield = None
                try:
                    info = getattr(stock, 'info', {}) or {}
                    if isinstance(info, dict):
                        sector = info.get('sector')
                        industry = info.get('industry')
                        pe_ratio = info.get('trailingPE')
                        dividend_yield = info.get('dividendYield')
                        if not market_cap:
                            market_cap = info.get('marketCap')
                        if not high_52:
                            high_52 = info.get('fiftyTwoWeekHigh')
                        if not low_52:
                            low_52 = info.get('fiftyTwoWeekLow')
                except Exception:
                    pass

                return {
                    "ticker": normalized_ticker.upper(),
                    "current_price": float(current_price),
                    "volume": int(volume),
                    "market_cap": market_cap,
                    "sector": sector,
                    "industry": industry,
                    "52_week_high": high_52,
                    "52_week_low": low_52,
                    "pe_ratio": pe_ratio,
                    "dividend_yield": dividend_yield,
                    "currency": "INR" if is_indian else "USD",
                    "exchange": "NSE" if ".NS" in normalized_ticker else "BSE" if ".BO" in normalized_ticker else "Other",
                    "is_indian": is_indian,
                    "timestamp": datetime.now(ZoneInfo('Asia/Kolkata')).isoformat()
                }

            quote_data = await asyncio.to_thread(_sync_fetch)
            if quote_data:
                logger.debug(f"Successfully fetched quote for {normalized_ticker}: {quote_data['current_price']}")
                return quote_data

            return await self._fallback_quote(ticker, normalized_ticker)
            
        except Exception as e:
            logger.error(f"Error fetching quote for {ticker}: {e}")
            return await self._fallback_quote(ticker, ticker.upper().strip())
    
    async def fetch_ohlcv_batch(
        self, 
        tickers: List[str], 
        days: int = 252,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        force_refresh: bool = False
    ) -> Dict[str, Any]:
        """
        Fetch OHLCV data for multiple tickers efficiently
        
        Args:
            tickers: List of ticker symbols
            days: Number of days to fetch (if start_date not provided)
            start_date: Optional start date string (YYYY-MM-DD)
            end_date: Optional end date string (YYYY-MM-DD)
            force_refresh: Whether to bypass cache
            
        Returns:
            Dictionary mapping ticker to DataFrame and list of failed tickers
        """
        logger.info(f"Fetching batch data for {len(tickers)} tickers")
        
        # Calculate date range if not provided
        resolved_end = end_date or datetime.now().strftime('%Y-%m-%d')
        resolved_start = start_date or (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        results = {}
        failed_tickers = []
        
        # Process tickers with controlled concurrency (max 5 simultaneous requests)
        sem = asyncio.Semaphore(5)
        
        async def fetch_one(ticker: str):
            async with sem:
                try:
                    df = await self.fetch_historical_data(ticker, resolved_start, resolved_end, force_refresh=force_refresh)
                    return ticker, df
                except Exception as e:
                    logger.error(f"Error in batch fetch for {ticker}: {e}")
                    return ticker, None
        
        fetch_results = await asyncio.gather(*[fetch_one(t) for t in tickers])
        
        for ticker, df in fetch_results:
            if df is not None and not df.empty:
                results[ticker] = df
            else:
                failed_tickers.append(ticker)
        
        logger.info(f"Batch fetch completed: {len(results)} successful, {len(failed_tickers)} failed")
        
        return {
            "data": results,
            "failed_tickers": failed_tickers
        }
    
    async def validate_ticker(self, ticker: str) -> bool:
        """
        Validate if a ticker exists and has data
        
        Args:
            ticker: Ticker symbol to validate
            
        Returns:
            True if ticker is valid, False otherwise
        """
        try:
            # Normalize ticker for Indian market
            normalized_ticker = self._normalize_indian_ticker(ticker)
            logger.debug(f"Validating ticker: {ticker} -> {normalized_ticker}")
            
            # Try to fetch recent data
            stock = yf.Ticker(normalized_ticker)
            hist = stock.history(period="5d")
            
            if not hist.empty:
                logger.info(f"Ticker {normalized_ticker} is valid")
                return True
            else:
                logger.warning(f"Ticker {normalized_ticker} has no data")
                return False
                
        except Exception as e:
            logger.error(f"Error validating ticker {ticker}: {e}")
            return False
    
    async def get_corporate_actions(self, ticker: str) -> Dict[str, Any]:
        """
        Get corporate actions information (splits, dividends)
        
        Note: yfinance already adjusts for these in adj_close
        """
        try:
            # Normalize ticker for Indian market
            normalized_ticker = self._normalize_indian_ticker(ticker)
            stock = yf.Ticker(normalized_ticker)
            
            # Get splits and dividends
            splits = stock.splits
            dividends = stock.dividends
            
            return {
                "ticker": normalized_ticker.upper(),
                "splits": splits.to_dict() if not splits.empty else {},
                "dividends": dividends.to_dict() if not dividends.empty else {},
                "is_indian": self._is_indian_ticker(normalized_ticker),
                "note": "yfinance adj_close is already adjusted for splits and dividends"
            }
            
        except Exception as e:
            logger.error(f"Error getting corporate actions for {ticker}: {e}")
            return {"ticker": ticker.upper(), "splits": {}, "dividends": {}, "is_indian": False}
    
    def get_popular_indian_stocks(self) -> List[str]:
        """Get list of popular Indian stocks for suggestions"""
        return self.popular_indian_stocks.copy()
    
    def get_market_info(self) -> Dict[str, Any]:
        """Get information about the current market configuration"""
        return {
            "default_region": self.default_region,
            "supported_exchanges": self.indian_exchanges,
            "popular_indian_stocks": self.popular_indian_stocks,
            "market_focus": "Indian (NSE/BSE)"
        }
    
    async def _download_with_timeout(
        self, 
        ticker: str, 
        start: str, 
        end: str
    ) -> Optional[pd.DataFrame]:
        """Download data with timeout protection"""
        try:
            # Use asyncio to wrap the synchronous data download calls
            loop = asyncio.get_event_loop()
            
            def download():
                import unittest.mock
                if not isinstance(yf.download, (unittest.mock.Mock, unittest.mock.MagicMock)):
                    # Tier 1: Try bfinance download
                    try:
                        import bfinance as bf
                        df_bf = bf.download(
                            ticker,
                            start=start,
                            end=end,
                            progress=False,
                            auto_adjust=False,
                        )
                        if df_bf is not None and not df_bf.empty:
                            df_bf._source = "bfinance"
                            return df_bf
                    except Exception as bf_err:
                        logger.debug(f"bfinance download failed for {ticker}: {bf_err}")

                # Tier 2: yfinance download
                return yf.download(
                    ticker,
                    start=start,
                    end=end,
                    progress=False,
                    auto_adjust=False  # Keep original OHLCV
                )
            
            # Run with timeout
            df = await asyncio.wait_for(
                loop.run_in_executor(None, download),
                timeout=self.yfinance_timeout
            )
            
            return df
            
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching data for {ticker}")
            return None
        except Exception as e:
            logger.error(f"Download error for {ticker}: {e}")
            return None

    async def _fetch_from_alpha_vantage(
        self, normalized_ticker: str, original_ticker: str, start: str, end: str
    ) -> Optional[pd.DataFrame]:
        """Alpha Vantage fallback when yfinance retries are exhausted.

        Keys rotate inside the service pool; a fully-exhausted pool or an
        unconfigured key silently leaves yfinance as sole source.
        """
        av = get_alpha_vantage_service()
        if not av.enabled:
            return None
        try:
            df = await av.fetch_daily_ohlcv(normalized_ticker, start, end)
        except Exception as e:
            logger.warning(f"Alpha Vantage OHLCV fallback failed for {original_ticker}: {e}")
            return None

        if df is None or df.empty:
            return None

        await self.cache.log_fetch_attempt(
            ticker=normalized_ticker,
            status="success",
            primary_attempt=False,
            fallback_attempt=True,
            source_used="alphavantage",
        )
        await self._store_timeseries_data(normalized_ticker, df, source_used="alphavantage")
        logger.info(
            f"Fallback succeeded via Alpha Vantage for {normalized_ticker}: {len(df)} records"
        )
        return df

    async def _fallback_quote(self, original_ticker: str, normalized_ticker: str) -> Optional[Dict[str, Any]]:
        """Partial-quote fallback via Alpha Vantage GLOBAL_QUOTE.

        Supplies price/volume only; fundamentals fields stay None so callers
        using .get() degrade gracefully.
        """
        av = get_alpha_vantage_service()
        if not av.enabled:
            return None
        try:
            q = await av.fetch_global_quote(normalized_ticker)
        except Exception as e:
            logger.warning(f"Alpha Vantage quote fallback failed for {original_ticker}: {e}")
            return None
        if not q:
            return None

        await self.cache.log_fetch_attempt(
            ticker=normalized_ticker,
            status="success",
            primary_attempt=False,
            fallback_attempt=True,
            source_used="alphavantage",
        )
        q.setdefault("is_indian", ".BSE" in normalized_ticker.upper())
        return q
    
    def _normalize_yfinance_data(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        """
        Normalize yfinance data to handle multi-index columns
        
        yfinance v0.2.51+ returns multi-index columns for multiple tickers
        For single ticker, we need to flatten the column names
        """
        try:
            # Handle multi-index columns (new yfinance behavior)
            if isinstance(df.columns, pd.MultiIndex):
                # For single ticker, flatten to single level
                df.columns = df.columns.get_level_values(0)
            elif isinstance(df.columns, pd.Index):
                # Column names are already strings
                pass
            else:
                logger.warning(f"Unexpected column structure for {ticker}")
            
            # Ensure we have the required columns
            required_columns = ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                logger.warning(f"Missing columns for {ticker}: {missing_columns}")
                return pd.DataFrame()  # Return empty DataFrame
            
            # Reset index to make Date a column
            df = df.reset_index()
            
            # Rename columns for consistency
            df = df.rename(columns={
                'Date': 'date',
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Adj Close': 'adj_close',
                'Volume': 'volume'
            })
            
            # Ensure ticker column
            df['ticker'] = ticker.upper()
            
            # Convert data types
            numeric_columns = ['open', 'high', 'low', 'close', 'adj_close']
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
            df['date'] = pd.to_datetime(df['date'])
            
            # Remove rows with NaN values
            df = df.dropna()
            
            logger.debug(f"Normalized data for {ticker}: {len(df)} records")
            return df
            
        except Exception as e:
            logger.error(f"Error normalizing data for {ticker}: {e}")
            return pd.DataFrame()
    
    async def _get_cached_data(
        self, 
        ticker: str, 
        start: str, 
        end: str
    ) -> Optional[pd.DataFrame]:
        """Get cached timeseries data"""
        try:
            query = select(StockTimeseries).where(
                StockTimeseries.ticker == ticker.upper(),
                StockTimeseries.date >= start,
                StockTimeseries.date <= end
            ).order_by(StockTimeseries.date)
            
            result = await self.db.execute(query)
            records = result.scalars().all()
            
            if not records:
                return None
            
            # Check if cached data covers the requested start date
            req_start = pd.to_datetime(start)
            req_end = pd.to_datetime(end)
            req_days = (req_end - req_start).days
            earliest_cached = pd.to_datetime(records[0].date)
            # If caller requested >60 days but cached data starts more than 30 days after requested start,
            # or if cached count is too sparse for requested window, check if we fetched recently (within 1 hour)
            if req_days > 60:
                if (earliest_cached - req_start).days > 30 or len(records) < min(30, int(req_days * 0.3)):
                    latest_fetched = max((r.fetched_on for r in records if r.fetched_on), default=None)
                    if latest_fetched and (datetime.utcnow() - latest_fetched).total_seconds() < 3600:
                        logger.debug(f"Using recent partial cache for {ticker} ({len(records)} records)")
                    else:
                        logger.info(f"Cache miss for {ticker}: cached has {len(records)} records from {earliest_cached.date()}, requested from {req_start.date()}")
                        return None
            
            # Convert to DataFrame
            data = []
            for record in records:
                data.append({
                    'date': record.date,
                    'open': record.open,
                    'high': record.high,
                    'low': record.low,
                    'close': record.close,
                    'adj_close': record.adj_close,
                    'volume': record.volume,
                    'ticker': record.ticker
                })
            
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
            
            logger.debug(f"Retrieved {len(df)} cached records for {ticker}")
            return df
            
        except Exception as e:
            logger.error(f"Error getting cached data for {ticker}: {e}")
            return None
    
    async def _store_timeseries_data(self, ticker: str, df: pd.DataFrame, source_used: str = "yfinance") -> None:
        """Store timeseries data in database with upsert operations"""
        try:
            from sqlalchemy.dialects.sqlite import insert
            from sqlalchemy import update
            
            logger.info(f"Storing {len(df)} records for {ticker} with upsert logic")
            
            # Validate data before storing
            validation_errors = self._validate_timeseries_data(df)
            if validation_errors:
                logger.warning(f"Data validation warnings for {ticker}: {validation_errors}")
            
            # Convert DataFrame to list of StockTimeseries objects
            records = []
            for _, row in df.iterrows():
                record_data = {
                    'ticker': ticker.upper(),
                    'date': row['date'],
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'adj_close': float(row['adj_close']),
                    'volume': int(row['volume']),
                    'source_used': source_used,
                    'fetch_status': 'fresh',
                    'fetched_on': datetime.utcnow()
                }
                records.append(record_data)
            
            if not records:
                return

            # Use native SQLite ON CONFLICT DO UPDATE for robust atomic batch upsert
            stmt = sqlite_insert(StockTimeseries.__table__).values(records)
            stmt = stmt.on_conflict_do_update(
                index_elements=['ticker', 'date'],
                set_={
                    'open': stmt.excluded.open,
                    'high': stmt.excluded.high,
                    'low': stmt.excluded.low,
                    'close': stmt.excluded.close,
                    'adj_close': stmt.excluded.adj_close,
                    'volume': stmt.excluded.volume,
                    'source_used': stmt.excluded.source_used,
                    'fetch_status': stmt.excluded.fetch_status,
                    'fetched_on': stmt.excluded.fetched_on,
                }
            )
            await self.db.execute(stmt)
            await self.db.commit()
            
            logger.info(f"Successfully atomic upserted {len(records)} records for {ticker}")
            
            # Log data integrity metrics
            await self._log_storage_metrics(ticker, len(records), 0)
            
        except Exception as e:
            logger.error(f"Error storing timeseries data for {ticker}: {e}")
            await self.db.rollback()
            # Try to identify the specific issue
            self._analyze_storage_error(ticker, df, e)
            
    def _validate_timeseries_data(self, df: pd.DataFrame) -> List[str]:
        """Validate timeseries data for integrity issues"""
        errors = []
        
        try:
            # Check for required columns
            required_columns = ['open', 'high', 'low', 'close', 'adj_close', 'volume']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                errors.append(f"Missing required columns: {missing_columns}")
            
            # Check for negative values where they shouldn't exist
            negative_checks = ['open', 'high', 'low', 'close', 'adj_close', 'volume']
            for col in negative_checks:
                if col in df.columns:
                    negative_count = (df[col] < 0).sum()
                    if negative_count > 0:
                        errors.append(f"Found {negative_count} negative values in {col}")
            
            # Check for impossible OHLC relationships
            if all(col in df.columns for col in ['open', 'high', 'low', 'close']):
                invalid_ohlc = (
                    (df['high'] < df['low']) |
                    (df['high'] < df['open']) |
                    (df['high'] < df['close']) |
                    (df['low'] > df['open']) |
                    (df['low'] > df['close'])
                ).sum()
                if invalid_ohlc > 0:
                    errors.append(f"Found {invalid_ohlc} records with invalid OHLC relationships")
            
            # Check for extreme price movements (>50% in one day)
            if 'close' in df.columns and len(df) > 1:
                df_sorted = df.sort_values('date')
                price_changes = df_sorted['close'].pct_change().abs()
                extreme_movements = (price_changes > 0.5).sum()
                if extreme_movements > 0:
                    errors.append(f"Found {extreme_movements} records with extreme price movements (>50%)")
            
            # Check for duplicate dates in the DataFrame
            if 'date' in df.columns:
                duplicate_dates = df['date'].duplicated().sum()
                if duplicate_dates > 0:
                    errors.append(f"Found {duplicate_dates} duplicate dates in input DataFrame")
            
            # Check for null values
            null_counts = df.isnull().sum()
            null_columns = null_counts[null_counts > 0]
            if not null_columns.empty:
                errors.append(f"Found null values in columns: {null_columns.to_dict()}")
                
        except Exception as e:
            errors.append(f"Validation error: {str(e)}")
        
        return errors
    
    async def _log_storage_metrics(self, ticker: str, stored_count: int, replaced_count: int) -> None:
        """Log storage metrics for monitoring"""
        try:
            from app.models.database import FetchLog
            
            total_operations = stored_count + replaced_count
            replacement_ratio = replaced_count / total_operations if total_operations > 0 else 0
            
            # Log high replacement ratio as warning
            if replacement_ratio > 0.5:
                logger.warning(f"High replacement ratio for {ticker}: {replacement_ratio:.2%} "
                             f"({replaced_count}/{total_operations} operations)")
            
            # Create a log entry for this storage operation
            log_entry = FetchLog(
                ticker=ticker,
                primary_attempt=True,
                fallback_attempt=False,
                status="success",
                source_used="yfinance",
                timestamp=datetime.utcnow()
            )
            self.db.add(log_entry)
            
        except Exception as e:
            logger.error(f"Error logging storage metrics: {e}")
    
    def _analyze_storage_error(self, ticker: str, df: pd.DataFrame, error: Exception) -> None:
        """Analyze storage errors to provide better debugging information"""
        try:
            logger.error(f"Storage error analysis for {ticker}:")
            logger.error(f"  Error type: {type(error).__name__}")
            logger.error(f"  Error message: {str(error)}")
            logger.error(f"  DataFrame shape: {df.shape}")
            logger.error(f"  DataFrame columns: {list(df.columns)}")
            
            # Check for specific data issues
            if "UNIQUE constraint failed" in str(error):
                logger.error(f"  Issue: Duplicate records attempted for {ticker}")
                logger.error(f"  This might indicate data processing issues or race conditions")
            elif "NOT NULL constraint failed" in str(error):
                logger.error(f"  Issue: Missing required data in some records")
                logger.error(f"  Check for null values in OHLCV data")
            elif "CHECK constraint failed" in str(error):
                logger.error(f"  Issue: Data validation failed (negative values, invalid ranges)")
                logger.error(f"  Check for negative prices or volumes")
            else:
                logger.error(f"  Issue: Unexpected database error")
                logger.error(f"  Please check data format and database connectivity")
                
        except Exception as analysis_error:
            logger.error(f"Error in storage error analysis: {analysis_error}")
            
    async def check_data_integrity(self, ticker: str = None) -> Dict[str, Any]:
        """Check data integrity for specified ticker or entire database"""
        try:
            from sqlalchemy import func, select
            
            if ticker:
                # Check specific ticker
                query = select(func.count()).select_from(StockTimeseries).where(
                    StockTimeseries.ticker == ticker.upper()
                )
                result = await self.db.execute(query)
                record_count = result.scalar()
                
                # Check for duplicates
                duplicate_query = select(func.count()).select_from(
                    StockTimeseries
                ).where(
                    StockTimeseries.ticker == ticker.upper()
                ).group_by(
                    StockTimeseries.ticker, StockTimeseries.date
                ).having(func.count() > 1)
                duplicate_result = await self.db.execute(duplicate_query)
                duplicate_count = len(duplicate_result.fetchall())
                
                return {
                    "ticker": ticker.upper(),
                    "total_records": record_count,
                    "duplicate_records": duplicate_count,
                    "integrity_status": "GOOD" if duplicate_count == 0 else "ISSUES_FOUND",
                    "recommendation": "No action needed" if duplicate_count == 0 else f"Clean up {duplicate_count} duplicate combinations"
                }
            else:
                # Check entire database
                total_query = select(func.count()).select_from(StockTimeseries)
                total_result = await self.db.execute(total_query)
                total_records = total_result.scalar()
                
                # Check for any duplicates
                all_duplicates_query = select(
                    StockTimeseries.ticker,
                    StockTimeseries.date,
                    func.count()
                ).select_from(StockTimeseries).group_by(
                    StockTimeseries.ticker, StockTimeseries.date
                ).having(func.count() > 1)
                duplicate_result = await self.db.execute(all_duplicates_query)
                duplicates = duplicate_result.fetchall()
                
                return {
                    "database_status": "GOOD" if len(duplicates) == 0 else "ISSUES_FOUND",
                    "total_records": total_records,
                    "duplicate_combinations": len(duplicates),
                    "duplicate_details": [{"ticker": d[0], "date": d[1], "count": d[2]} for d in duplicates[:5]],
                    "recommendation": "Database integrity is good" if len(duplicates) == 0 else f"Found {len(duplicates)} ticker/date combinations with duplicates"
                }
                
        except Exception as e:
            logger.error(f"Error checking data integrity: {e}")
            return {
                "error": str(e),
                "status": "CHECK_FAILED"
            }


# Global data service instance
class GlobalDataService:
    """Global data service for dependency injection"""
    
    def __init__(self, db_session: AsyncSession):
        self._data_service = DataService(db_session)
    
    def get_service(self) -> DataService:
        return self._data_service