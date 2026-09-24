"""
Company reference data (fundamentals, financial statements, insider trades).

Function set adapted from TauricResearch/TradingAgents,
tradingagents/dataflows/y_finance.py (Apache License 2.0,
Copyright Tauric Research).

Modifications from the original:
- async surface (blocking yfinance calls offloaded via asyncio.to_thread)
- structured JSON output instead of CSV text blobs
- Indian ticker normalization delegated to the project's DataService
- fundamentals: stub-info guard retained (unknown symbols return a truthy
  but empty info dict on yfinance - treated as "no data")
- statements: look-ahead filter retained (period columns after curr_date
  dropped when curr_date supplied)

Licensed under the Apache License, Version 2.0.
"""

import asyncio
import time
from typing import Any, Dict, List, Optional

import pandas as pd

from app.services.cache_service import (
    ProviderError,
    ProviderUnavailableError,
    UnknownTickerError,
    cache_generation_is_current,
    get_cache_generation,
    get_runtime_cache_snapshot,
)
from app.services.data_service import canonical_ticker, DataService
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _normalize(ticker: str) -> str:
    """Reuse the project's NSE/BSE suffix logic (no session needed)."""
    return canonical_ticker(ticker)


def _yf_retry(func, max_retries: int = 3, base_delay: float = 2.0):
    """Exponential backoff around yfinance rate limits (TradingAgents)."""
    import time

    from yfinance.exceptions import YFRateLimitError

    for attempt in range(max_retries + 1):
        try:
            return func()
        except YFRateLimitError:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"yfinance rate limited, retry in {delay:.0f}s ({attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                raise


async def _to_thread(func, *args):
    return await asyncio.to_thread(func, *args)


# Mirror bfinance's 24h SQLite cache (bfinance/ticker.py) for the yfinance
# fundamentals tier so fallback requests don't re-hit Yahoo every call (O-01).
YF_FUNDAMENTALS_TTL_SECONDS = 24 * 60 * 60


class CompanyDataService:
    """Fundamentals / statements / insider feed on top of yfinance."""

    def __init__(self, db_session=None, cache_service=None):
        # norm_ticker -> (generation, fetched_at_epoch, payload); local to the
        # instance (process-wide singleton in prod, fresh per test).
        self._yf_fundamentals_cache: Dict[str, tuple] = {}
        self.cache_service = cache_service
        if self.cache_service is None and db_session is not None:
            from app.services.cache_service import CacheService
            self.cache_service = CacheService(db_session)

    async def _fundamentals_cache_enabled(self) -> bool:
        if self.cache_service is not None and hasattr(self.cache_service, "get_runtime_config"):
            return (await self.cache_service.get_runtime_config()).enabled
        snapshot = get_runtime_cache_snapshot()
        return snapshot.enabled if snapshot is not None else True

    # ---------------------------------------------------------- fundamentals

    FUNDAMENTAL_FIELDS = [
        ("name", "longName"),
        ("sector", "sector"),
        ("industry", "industry"),
        ("market_cap", "marketCap"),
        ("pe_ratio_ttm", "trailingPE"),
        ("forward_pe", "forwardPE"),
        ("peg_ratio", "pegRatio"),
        ("price_to_book", "priceToBook"),
        ("eps_ttm", "trailingEps"),
        ("forward_eps", "forwardEps"),
        ("dividend_yield", "dividendYield"),
        ("beta", "beta"),
        ("week_52_high", "fiftyTwoWeekHigh"),
        ("week_52_low", "fiftyTwoWeekLow"),
        ("ma_50_day", "fiftyDayAverage"),
        ("ma_200_day", "twoHundredDayAverage"),
        ("revenue_ttm", "totalRevenue"),
        ("ebitda", "ebitda"),
        ("net_income_common", "netIncomeToCommon"),
        ("profit_margin", "profitMargins"),
        ("operating_margin", "operatingMargins"),
        ("return_on_equity", "returnOnEquity"),
        ("return_on_assets", "returnOnAssets"),
        ("debt_to_equity", "debtToEquity"),
        ("current_ratio", "currentRatio"),
        ("book_value", "bookValue"),
        ("free_cash_flow", "freeCashflow"),
    ]

    async def get_fundamentals(
        self, ticker: str, source_order: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Curated fundamentals snapshot.
        Pulls rich 4-level taxonomy and ratios from bfinance first,
        falling back to yfinance for US/global equities.

        Args:
            ticker: Raw scrip symbol.
            source_order: Vendor cascade honoring the user's primary-source
                preference (defaults to bfinance -> yfinance).

        Raises:
            ValueError: ticker has no fundamentals (404 semantics).
            RuntimeError: upstream yfinance failure such as crumb-auth 401
                (503 semantics - retry later).
        """
        norm_ticker = _normalize(ticker)
        cache_enabled = await self._fundamentals_cache_enabled()
        generation = get_cache_generation()
        import bfinance
        import yfinance as yf

        if source_order is None:
            from app.services.source_preference_service import get_active_source_order
            order = get_active_source_order()
        else:
            order = source_order
        had_outage = False
        # Fail fast on typos/unknown tiers instead of silently serving
        # yfinance for anything that isn't exactly "bfinance" (I-02).
        unknown = [v for v in order if v not in ("bfinance", "yfinance")]
        if unknown:
            raise ValueError(f"Unknown data source(s) in source_order: {unknown}")

        # Identity check against module-load originals (data_service pattern):
        # a replaced Ticker means mocked mode; bfinance stays usable when the
        # test patched it too.
        is_yf_mocked = yf.Ticker is not DataService._YF_TICKER_REAL
        is_bf_mocked = bfinance.Ticker is not DataService._BF_TICKER_REAL

        def _fetch_bf() -> Optional[Dict[str, Any]]:
            try:
                import bfinance as bf
                t = bf.Ticker(norm_ticker)
                profile = t._ensure_profile()
                if not profile or not profile.name:
                    return None
                r = profile.ratios
                info = getattr(t, 'info', {}) or {}

                out = {
                    "ticker": norm_ticker.upper(),
                    "source": "bfinance",
                    "name": profile.name or info.get("longName") or norm_ticker,
                    "sector": profile.sector or info.get("sector"),
                    "industry_group": profile.industry_group,
                    "industry": profile.industry or info.get("industry"),
                    "sub_industry": profile.sub_industry,
                    "indices": profile.indices or [],
                    "about": profile.about,
                    # bfinance Ratios.market_cap is ₹ Cr; the house contract
                    # for `market_cap` is absolute ₹ (yfinance marketCap,
                    # bfinance info["marketCap"] = r.market_cap * 1e7) (B-01).
                    "market_cap": (r.market_cap * 1e7) if r.market_cap else info.get("marketCap"),
                    "pe_ratio_ttm": r.stock_pe or info.get("trailingPE"),
                    "forward_pe": info.get("forwardPE"),
                    "peg_ratio": r.peg_ratio or info.get("pegRatio"),
                    "price_to_book": r.price_to_book or info.get("priceToBook") or (r.current_price / r.book_value if r.current_price and r.book_value else None),
                    "eps_ttm": r.eps_ttm or info.get("trailingEps"),
                    "forward_eps": info.get("forwardEps"),
                    "dividend_yield": r.dividend_yield if r.dividend_yield is not None else info.get("dividendYield"),
                    "week_52_high": r.high_52w or info.get("fiftyTwoWeekHigh"),
                    "week_52_low": r.low_52w or info.get("fiftyTwoWeekLow"),
                    "return_on_equity": r.roe if r.roe is not None else info.get("returnOnEquity"),
                    "return_on_capital_employed": r.roce,
                    "debt_to_equity": r.debt_to_equity or info.get("debtToEquity"),
                    "book_value": r.book_value or info.get("bookValue"),
                    "face_value": r.face_value,
                    "piotroski_score": getattr(t, 'piotroski_score', None),
                    "graham_number": getattr(t, 'graham_number', None),
                    "enterprise_value_cr": getattr(t, 'enterprise_value', None),
                    "ev_to_ebitda": getattr(t, 'ev_to_ebitda', None),
                    "interest_coverage": getattr(t, 'interest_coverage', None),
                    "pros": profile.analysis.pros if profile.analysis else [],
                    "cons": profile.analysis.cons if profile.analysis else [],
                }
                filtered = {k: v for k, v in out.items() if v is not None}
                return filtered if len(filtered) > 2 else None
            except Exception as exc:
                nonlocal had_outage
                had_outage = True
                logger.debug("bfinance fundamentals unavailable for %s: %s", norm_ticker, type(exc).__name__)
                return None

        async def _fetch_yf() -> Dict[str, Any]:
            cached = self._yf_fundamentals_cache.get(norm_ticker)
            if cached:
                cached_generation = cached[0] if len(cached) == 3 else None
                cached_ts = cached[1] if len(cached) == 3 else cached[0]
                cached_payload = cached[2] if len(cached) == 3 else cached[1]
                if (
                    cache_enabled
                    and cached_generation in (None, generation)
                    and time.time() - cached_ts < YF_FUNDAMENTALS_TTL_SECONDS
                    and cache_generation_is_current(generation)
                ):
                    return cached_payload

            def _fetch() -> Dict[str, Any]:
                t = yf.Ticker(norm_ticker)
                return _yf_retry(lambda: t.info)

            try:
                info = await _to_thread(_fetch)
            except Exception as exc:
                # Yahoo occasionally rejects .info with 401 Invalid-Crumb; treat
                # as temporary upstream outage rather than missing ticker.
                raise ProviderUnavailableError("Fundamentals upstream unavailable", provider="yfinance") from exc

            if not info:
                raise UnknownTickerError("No fundamentals returned", provider="yfinance")

            out: Dict[str, Any] = {"ticker": norm_ticker.upper(), "source": "yfinance"}
            fallback_map = {
                "longName": ["shortName", "companyName"],
                "fiftyTwoWeekHigh": ["52WeekHigh", "fifty_two_week_high", "yearHigh"],
                "fiftyTwoWeekLow": ["52WeekLow", "fifty_two_week_low", "yearLow"],
                "trailingPE": ["pe_ratio", "trailing_pe", "trailingPe"],
                "marketCap": ["market_cap", "totalMarketCap"],
                "returnOnEquity": ["roe", "return_on_equity"],
            }
            for our_key, yf_key in self.FUNDAMENTAL_FIELDS:
                val = info.get(yf_key)
                if val is None and yf_key in fallback_map:
                    for alt_key in fallback_map[yf_key]:
                        val = info.get(alt_key)
                        if val is not None:
                            break
                if val is not None:
                    if our_key == "return_on_equity":
                        # yfinance emits a fraction (0.145); house contract is
                        # percent to match the bfinance tier's Ratios.roe (B-03).
                        val = val * 100
                    out[our_key] = val

            if len(out) <= 2:  # only ticker/source -> stub info dict
                raise UnknownTickerError("No fundamental fields returned", provider="yfinance")
            if cache_enabled and cache_generation_is_current(generation):
                self._yf_fundamentals_cache[norm_ticker] = (generation, time.time(), out)
            return out

        # Cascade per the user's preferred vendor order.  Preserve the deepest
        # typed error after every tier has declined the request.
        last_error: Optional[Exception] = None
        for vendor in order:
            if vendor == "bfinance":
                if is_yf_mocked and not is_bf_mocked:
                    continue
                bf_res = await _to_thread(_fetch_bf)
                if bf_res is not None:
                    return bf_res
            elif vendor == "yfinance":
                try:
                    return await _fetch_yf()
                except (ProviderUnavailableError, UnknownTickerError) as exc:
                    if isinstance(exc, ProviderUnavailableError):
                        had_outage = True
                    last_error = exc
                    logger.warning("yfinance fundamentals unavailable for %s: %s", norm_ticker, exc.safe_message)
            else:
                raise ValueError(f"Unknown data source(s) in source_order: {[vendor]}")

        if had_outage:
            raise ProviderUnavailableError("Fundamentals upstream unavailable", provider="company_data")
        if last_error is not None:
            raise last_error
        raise UnknownTickerError("No fundamentals returned", provider="company_data")

    # ----------------------------------------------------------- statements

    STATEMENTS = {
        "income": {"quarterly": "quarterly_income_stmt", "annual": "income_stmt"},
        "balance": {"quarterly": "quarterly_balance_sheet", "annual": "balance_sheet"},
        "cashflow": {"quarterly": "quarterly_cashflow", "annual": "cashflow"},
    }

    async def get_financial_statements(
        self,
        ticker: str,
        statement: str = "income",
        freq: str = "quarterly",
        curr_date: Optional[str] = None,
        source_order: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Return statements with the actual vendor recorded in ``source``."""
        if statement not in self.STATEMENTS:
            raise ValueError(f"statement must be one of {list(self.STATEMENTS)}")
        if freq not in ("quarterly", "annual", "yearly"):
            raise ValueError("freq must be 'quarterly' or 'annual'")
        if source_order is None:
            from app.services.source_preference_service import get_active_source_order
            order = get_active_source_order()
        else:
            order = source_order
        unknown = [vendor for vendor in order if vendor not in ("bfinance", "yfinance")]
        if unknown:
            raise ValueError(f"Unknown data source(s) in source_order: {unknown}")

        av_symbol = _normalize(ticker)
        normalized_freq = "quarterly" if freq == "quarterly" else "yearly"
        import bfinance
        import yfinance as yf
        is_yf_mocked = yf.Ticker is not DataService._YF_TICKER_REAL
        is_bf_mocked = bfinance.Ticker is not DataService._BF_TICKER_REAL
        raw = None
        source_used: Optional[str] = None
        errors: List[ProviderError] = []

        for vendor in order:
            try:
                if vendor == "bfinance":
                    if is_yf_mocked and not is_bf_mocked:
                        continue
                    def _fetch_bf():
                        ticker_obj = bfinance.Ticker(av_symbol)
                        if statement == "income":
                            return ticker_obj.get_income_stmt(freq=normalized_freq)
                        if statement == "balance":
                            return ticker_obj.get_balance_sheet(freq=normalized_freq)
                        return ticker_obj.get_cash_flow(freq=normalized_freq)
                    raw = await _to_thread(_fetch_bf)
                else:
                    attr = self.STATEMENTS[statement]["quarterly" if freq == "quarterly" else "annual"]
                    def _fetch_yf():
                        ticker_obj = yf.Ticker(av_symbol)
                        return _yf_retry(lambda: getattr(ticker_obj, attr))
                    raw = await _to_thread(_fetch_yf)
                if raw is not None and not raw.empty:
                    source_used = vendor
                    break
            except Exception as exc:
                errors.append(ProviderUnavailableError("Statement provider unavailable", provider=vendor))
                logger.debug("Statement fetch failed via %s: %s", vendor, type(exc).__name__)

        if raw is None or raw.empty:
            if errors:
                raise errors[-1]
            raise UnknownTickerError(
                f"No {statement} statement data for {av_symbol} ({freq})", provider="company_data"
            )

        frame = raw.copy()
        if curr_date:
            cutoff = pd.Timestamp(curr_date)
            parsed = pd.to_datetime(frame.columns, errors="coerce")
            keep = [column for column, stamp in zip(frame.columns, parsed) if pd.isna(stamp) or stamp <= cutoff]
            frame = frame[keep]
        periods = [str(column)[:10] for column in frame.columns]
        metrics: Dict[str, Dict[str, Any]] = {}
        for label in frame.index:
            row = frame.loc[label]
            metrics[str(label)] = {
                period: (None if pd.isna(row[column]) else float(row[column]))
                for period, column in zip(periods, frame.columns)
            }
        return {
            "ticker": av_symbol.upper(),
            "source": source_used,
            "statement": statement,
            "freq": freq,
            "periods": periods,
            "metrics": metrics,
        }

    # -------------------------------------------------------------- insider

    async def get_insider_transactions(self, ticker: str) -> List[Dict[str, Any]]:
        """Recent insider transactions; empty list is normal for many names."""

        def _fetch():
            import yfinance as yf

            t = yf.Ticker(_normalize(ticker))
            return _yf_retry(lambda: t.insider_transactions)

        raw = await _to_thread(_fetch)
        if raw is None or raw.empty:
            return []

        records = []
        for _, row in raw.iterrows():
            clean = {}
            for key, val in row.items():
                if pd.isna(val):
                    clean[str(key)] = None
                elif isinstance(val, (pd.Timestamp,)):
                    clean[str(key)] = val.isoformat()
                elif isinstance(val, (int, float, str)):
                    clean[str(key)] = val
            records.append(clean)
        return records


_service: Optional[CompanyDataService] = None


def get_company_data_service(db_session=None) -> CompanyDataService:
    global _service
    if _service is None:
        _service = CompanyDataService(db_session=db_session)
    elif db_session is not None and _service.cache_service is None:
        from app.services.cache_service import CacheService
        _service.cache_service = CacheService(db_session)
    return _service
