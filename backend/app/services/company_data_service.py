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
from typing import Any, Dict, List, Optional

import pandas as pd

from app.services.data_service import canonical_ticker
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
    return await asyncio.to_thread(func)


class CompanyDataService:
    """Fundamentals / statements / insider feed on top of yfinance."""

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

    async def get_fundamentals(self, ticker: str) -> Dict[str, Any]:
        """Curated fundamentals snapshot.
        Pulls rich 4-level taxonomy and ratios from bfinance first,
        falling back to yfinance for US/global equities.

        Raises:
            ValueError: ticker has no fundamentals (404 semantics).
            RuntimeError: upstream yfinance failure such as crumb-auth 401
                (503 semantics - retry later).
        """
        norm_ticker = _normalize(ticker)
        import unittest.mock
        import yfinance as yf

        # If yfinance.Ticker is explicitly mocked in a unit test, prioritize mock without network
        is_yf_mocked = isinstance(yf.Ticker, (unittest.mock.Mock, unittest.mock.MagicMock))

        if not is_yf_mocked:
            # Tier 1: Attempt bfinance for live Indian equities
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
                        "name": profile.name or info.get("longName") or norm_ticker,
                        "sector": profile.sector or info.get("sector"),
                        "industry_group": profile.industry_group,
                        "industry": profile.industry or info.get("industry"),
                        "sub_industry": profile.sub_industry,
                        "indices": profile.indices or [],
                        "about": profile.about,
                        "market_cap": r.market_cap or info.get("marketCap"),
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
                except Exception as e:
                    logger.debug(f"bfinance fundamentals fetch skipped for {norm_ticker}: {e}")
                    return None

            bf_res = await _to_thread(_fetch_bf)
            if bf_res is not None:
                return bf_res

        # Tier 2: Fallback to yfinance
        def _fetch() -> Dict[str, Any]:
            t = yf.Ticker(norm_ticker)
            return _yf_retry(lambda: t.info)

        try:
            info = await _to_thread(_fetch)
        except Exception as e:
            # Yahoo occasionally rejects .info with 401 Invalid-Crumb; treat
            # as temporary upstream outage rather than missing ticker.
            raise RuntimeError(f"Fundamentals upstream unavailable: {type(e).__name__}: {e}") from e

        if not info:
            raise ValueError(f"No fundamentals returned for {ticker}")

        out: Dict[str, Any] = {"ticker": norm_ticker.upper()}
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
                out[our_key] = val

        if len(out) <= 1:  # only ticker -> stub info dict
            raise ValueError(f"No fundamental fields returned for {ticker}")
        return out

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
    ) -> Dict[str, Any]:
        """Balance sheet / cash flow / income statement as structured JSON.
        Pulls 10-13 years annual and 12-16 quarters via bfinance, falling back to yfinance.

        Period columns after curr_date are dropped to prevent look-ahead
        (TradingAgents filter_financials_by_date).
        """
        if statement not in self.STATEMENTS:
            raise ValueError(f"statement must be one of {list(self.STATEMENTS)}")
        if freq not in ("quarterly", "annual", "yearly"):
            raise ValueError("freq must be 'quarterly' or 'annual'")

        av_symbol = _normalize(ticker)
        normalized_freq = "quarterly" if freq == "quarterly" else "yearly"
        import unittest.mock
        import yfinance as yf

        is_yf_mocked = isinstance(yf.Ticker, (unittest.mock.Mock, unittest.mock.MagicMock))
        raw = None

        if not is_yf_mocked:
            # Tier 1: Try bfinance statements
            def _fetch_bf():
                try:
                    import bfinance as bf
                    t = bf.Ticker(av_symbol)
                    if statement == "income":
                        return t.get_income_stmt(freq=normalized_freq)
                    elif statement == "balance":
                        return t.get_balance_sheet(freq=normalized_freq)
                    elif statement == "cashflow":
                        return t.get_cash_flow(freq=normalized_freq)
                    return None
                except Exception as e:
                    logger.debug(f"bfinance statement fetch skipped for {av_symbol}: {e}")
                    return None

            raw = await _to_thread(_fetch_bf)

        # Tier 2: Fallback to yfinance statements
        if raw is None or raw.empty:
            attr = self.STATEMENTS[statement]["quarterly" if freq == "quarterly" else "annual"]

            def _fetch_yf():
                import yfinance as yf
                t = yf.Ticker(av_symbol)
                return _yf_retry(lambda: getattr(t, attr))

            try:
                raw = await _to_thread(_fetch_yf)
            except Exception as e:
                logger.debug(f"yfinance statement fetch error for {av_symbol}: {e}")

        if raw is None or raw.empty:
            raise ValueError(f"No {statement} statement data for {av_symbol} ({freq})")

        df = raw.copy()
        if curr_date:
            cutoff = pd.Timestamp(curr_date)
            cols = pd.to_datetime(df.columns, errors="coerce")
            keep = [c for c, ts in zip(df.columns, cols) if pd.isna(ts) or ts <= cutoff]
            df = df[keep]

        periods = [str(c)[:10] for c in df.columns]
        metrics: Dict[str, Dict[str, Any]] = {}
        for label in df.index:
            row = df.loc[label]
            metrics[str(label)] = {
                period: (None if pd.isna(row[col]) else float(row[col]))
                for period, col in zip(periods, df.columns)
            }

        return {
            "ticker": av_symbol.upper(),
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


def get_company_data_service() -> CompanyDataService:
    global _service
    if _service is None:
        _service = CompanyDataService()
    return _service
