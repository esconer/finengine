"""
Screener Service for Indian Equities.
Provides institutional strategies: Coffee Can, Magic Formula, Debt-Free Compounders,
High Dividend Yield, and Undervalued Growth.
"""

import asyncio
import hashlib
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

import bfinance as bf
from app.services.cache_service import CacheService
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Debt-free enforcement: Screener.in-style D/E ceiling. Applied as a
# finengine-side post-filter because the upstream bfinance
# debt_free_compounders definition does not check debt (logged for bfinance).
DEBT_FREE_MAX_DE_RATIO = 0.2

# L2 DB persistence (cointegration precedent: `_db_cache_keys` /
# `COINT_DB_TICKER` via `CacheService`/`AnalyticsCache`). AnalyticsCache.ticker
# is String(10) so the namespace is a short tag, not the strategy; the screen
# identity (strategy + universe hash + date) lives in metric_name (String(50)).
# TTL ~24h is governed by the injected CacheService's ttl_minutes.
SCREENER_DB_TICKER = "SCREENER"
SCREENER_DB_TTL_MINUTES = 24 * 60


def _db_cache_keys(strategy: str, universe_token: str, asof_date: str) -> Tuple[str, str]:
    """Collision-free (ticker, metric_name) for a strategy-universe-day."""
    return SCREENER_DB_TICKER, f"screen_{strategy}_{universe_token}_{asof_date}"


def _screen_ticker(sym: str) -> str:
    """Map a screen Symbol to a Yahoo ticker: numeric BSE scrips keep .BO."""
    s = str(sym).upper().strip()
    if s.endswith((".NS", ".BO")):
        return s
    if s.isdigit():
        return f"{s}.BO"
    return f"{s}.NS"


def _universe_cache_token(universe: Optional[List[str]]) -> str:
    if not universe:
        return "default"
    return hashlib.sha1("|".join(sorted(u.upper().strip() for u in universe)).encode("utf-8")).hexdigest()[:12]


async def _to_thread(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


class ScreenerService:
    """Quantitative stock screening engine backed by bfinance.screens."""

    _cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
    CACHE_TTL_SECONDS = 300  # 5 minutes cache

    def __init__(
        self,
        db_session=None,
        cache_service: Optional[CacheService] = None,
    ):
        self.db = db_session
        self.cache_service = cache_service

    STRATEGIES = {
        "coffee_can": {
            "name": "Coffee Can Portfolio",
            "description": "Saurabh Mukherjea Coffee Can Screen: ROCE > 15%, ROE > 15%, and Market Cap > ₹5,000 Cr",
            "screen_getter": lambda: bf.screens.coffee_can,
        },
        "magic_formula": {
            "name": "Magic Formula (India)",
            "description": "Joel Greenblatt Magic Formula: High ROCE (>= 20%) combined with attractive P/E valuation (<= 25)",
            "screen_getter": lambda: bf.screens.magic_formula,
        },
        "debt_free": {
            "name": "Debt Free Compounders",
            "description": "Negligible leverage (D/E <= 0.2), ROCE >= 20% and Market Cap > ₹10,000 Cr",
            "screen_getter": lambda: bf.screens.debt_free_compounders,
        },
        "high_dividend": {
            "name": "High Dividend Champions",
            "description": "Dividend champions: Yield >= 2.5% and ROCE >= 12% with stable cash generation",
            "screen_getter": lambda: bf.screens.high_dividend_yield,
        },
        "undervalued_growth": {
            "name": "Undervalued Growth",
            "description": "Growing businesses trading at reasonable multiples (P/E <= 22, ROE >= 15%)",
            "screen_getter": lambda: bf.screens.undervalued_growth,
        },
    }

    async def get_available_strategies(self) -> List[Dict[str, Any]]:
        """List all supported screening strategies."""
        return [
            {
                "key": key,
                "name": val["name"],
                "description": val["description"],
            }
            for key, val in self.STRATEGIES.items()
        ]

    async def _get_cached_screen(
        self,
        strategy: str,
        universe_token: str,
        asof_day: str,
        max_stocks: int,
    ) -> Optional[Dict[str, Any]]:
        """L2 DB lookup on L1 miss. Never fabricates: identity-checked, None on doubt."""
        if self.cache_service is None:
            return None
        try:
            db_ticker, metric_name = _db_cache_keys(strategy, universe_token, asof_day)
            cached = await self.cache_service.get_cached_analytics(
                ticker=db_ticker,
                metric_name=metric_name,
            )
            if not cached or not cached.get("model_params"):
                return None
            payload = cached["model_params"]
            if payload.get("strategy") != strategy or payload.get("universe_token") != universe_token:
                return None
            stored = payload.get("response")
            if not stored:
                return None
            # Stored payload was capped at its own max_stocks: slicing down to
            # a smaller request is exact; a larger request must recompute.
            stored_cap = payload.get("max_stocks") or 50
            want = max_stocks or 50
            if stored_cap < want:
                return None
            stocks = stored.get("stocks", [])[:want]
            return {**stored, "stocks": stocks, "count": len(stocks)}
        except Exception as e:
            logger.debug(f"Screener L2 cache read error: {e}")
            return None

    async def _set_cached_screen(
        self,
        strategy: str,
        universe_token: str,
        asof_day: str,
        max_stocks: int,
        response_data: Dict[str, Any],
    ) -> None:
        """Write-through L2 store (best-effort; compute result never depends on it)."""
        if self.cache_service is None:
            return
        try:
            db_ticker, metric_name = _db_cache_keys(strategy, universe_token, asof_day)
            await self.cache_service.set_cached_analytics(
                ticker=db_ticker,
                metric_name=metric_name,
                metric_value=float(response_data.get("count", 0)),
                calculation_date=datetime.utcnow(),
                model_params={
                    "strategy": strategy,
                    "universe_token": universe_token,
                    "max_stocks": max_stocks or 50,
                    "response": response_data,
                },
            )
        except Exception as e:
            logger.debug(f"Screener L2 cache write error: {e}")

    async def run_screen(
        self,
        strategy: str,
        universe: Optional[List[str]] = None,
        max_stocks: int = 50,
    ) -> Dict[str, Any]:
        """
        Execute prebuilt quantitative screener strategy.
        """
        strat_key = strategy.lower().strip()
        if strat_key not in self.STRATEGIES:
            raise ValueError(f"Unknown strategy '{strategy}'. Supported: {list(self.STRATEGIES.keys())}")

        strategy_meta = self.STRATEGIES[strat_key]

        # Check in-memory cache (universe is part of the key: a custom
        # universe must never be served default-universe results).
        universe_token = _universe_cache_token(universe)
        cache_key = f"{strat_key}_{max_stocks}_{universe_token}"
        now_ts = time.time()
        if cache_key in self._cache:
            ts, cached_res = self._cache[cache_key]
            if now_ts - ts < self.CACHE_TTL_SECONDS:
                return cached_res

        # L2 DB cache on L1 miss (survives restarts; ~24h TTL).
        asof_day = datetime.utcnow().strftime("%Y-%m-%d")
        l2_hit = await self._get_cached_screen(strat_key, universe_token, asof_day, max_stocks)
        if l2_hit is not None:
            self._cache[cache_key] = (now_ts, l2_hit)
            return l2_hit

        def _execute():
            screen = strategy_meta["screen_getter"]()
            # Scan the FULL universe: upstream slices symbols[:max_stocks]
            # before filtering, so passing max_stocks would silently skip
            # the tail of the universe. Cap the ranked results below.
            df = screen.run(universe=universe, max_stocks=None)
            results = []
            if not df.empty:
                for _, row in df.iterrows():
                    sym = str(row.get("Symbol", ""))
                    results.append({
                        "symbol": sym,
                        "ticker": _screen_ticker(sym),
                        "name": str(row.get("Name", sym)),
                        "price": float(row["Price"]) if pd.notna(row.get("Price")) else 0.0,
                        "market_cap_cr": float(row["MarketCap_Cr"]) if pd.notna(row.get("MarketCap_Cr")) else 0.0,
                        "pe_ratio": float(row["PE"]) if pd.notna(row.get("PE")) else None,
                        "roce_pct": float(row["ROCE_%"]) if pd.notna(row.get("ROCE_%")) else None,
                        "roe_pct": float(row["ROE_%"]) if pd.notna(row.get("ROE_%")) else None,
                        "dividend_yield_pct": float(row["DivYield_%"]) if pd.notna(row.get("DivYield_%")) else None,
                        "book_value": float(row["BookValue"]) if pd.notna(row.get("BookValue")) else None,
                    })
            return results

        try:
            results = await _to_thread(_execute)
            if strat_key == "debt_free":
                # Upstream debt_free_compounders does not check debt; enforce
                # D/E here (fail-closed: unknown leverage is excluded) so the
                # strategy name is not a mislabel.
                results = await self._enforce_debt_free(results)
            results = results[: max_stocks or 50]
            response_data = {
                "strategy": strat_key,
                "name": strategy_meta["name"],
                "description": strategy_meta["description"],
                "count": len(results),
                "stocks": results,
            }
            self._cache[cache_key] = (now_ts, response_data)
            await self._set_cached_screen(strat_key, universe_token, asof_day, max_stocks, response_data)
            return response_data
        except Exception as e:
            logger.error(f"Error running screener {strategy}: {e}")
            raise ValueError(f"Screen execution failed: {e}")

    async def _enforce_debt_free(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Keep only matches with D/E <= ceiling (fail-closed on unknown)."""
        def _check():
            kept = []
            for r in results:
                try:
                    info = bf.Ticker(r.get("symbol", "")).info or {}
                    de = info.get("debtToEquity")
                    if de is not None and float(de) <= DEBT_FREE_MAX_DE_RATIO:
                        kept.append(r)
                except Exception:
                    continue
            return kept

        try:
            return await _to_thread(_check)
        except Exception as e:
            logger.error(f"Debt-free enforcement failed: {e}")
            return []

    async def run_custom_screen(
        self,
        min_roce: Optional[float] = None,
        min_roe: Optional[float] = None,
        max_pe: Optional[float] = None,
        min_mcap_cr: Optional[float] = None,
        min_div_yield: Optional[float] = None,
        max_stocks: int = 50,
    ) -> Dict[str, Any]:
        """
        Execute dynamic custom screen based on ratio criteria.
        """
        def _filter(t: bf.Ticker) -> bool:
            info = t.info
            if not info:
                return False

            roce = info.get("returnOnCapitalEmployed") or 0.0
            roe = (info.get("returnOnEquity") or 0.0) * 100
            pe = info.get("trailingPE") or 999.0
            mcap = info.get("marketCapInCr") or 0.0
            div_yield = (info.get("dividendYield") or 0.0) * 100

            if min_roce is not None and roce < min_roce:
                return False
            if min_roe is not None and roe < min_roe:
                return False
            if max_pe is not None and (pe <= 0 or pe > max_pe):
                return False
            if min_mcap_cr is not None and mcap < min_mcap_cr:
                return False
            if min_div_yield is not None and div_yield < min_div_yield:
                return False

            return True

        def _execute():
            custom_screen = bf.Screen(
                name="Custom Screen",
                description="Custom multi-parameter equity screen",
                filter_fn=_filter,
            )
            df = custom_screen.run(max_stocks=None)
            results = []
            if not df.empty:
                for _, row in df.iterrows():
                    sym = str(row.get("Symbol", ""))
                    results.append({
                        "symbol": sym,
                        "ticker": _screen_ticker(sym),
                        "name": str(row.get("Name", sym)),
                        "price": float(row["Price"]) if pd.notna(row.get("Price")) else 0.0,
                        "market_cap_cr": float(row["MarketCap_Cr"]) if pd.notna(row.get("MarketCap_Cr")) else 0.0,
                        "pe_ratio": float(row["PE"]) if pd.notna(row.get("PE")) else None,
                        "roce_pct": float(row["ROCE_%"]) if pd.notna(row.get("ROCE_%")) else None,
                        "roe_pct": float(row["ROE_%"]) if pd.notna(row.get("ROE_%")) else None,
                        "dividend_yield_pct": float(row["DivYield_%"]) if pd.notna(row.get("DivYield_%")) else None,
                    })
            return results

        try:
            results = await _to_thread(_execute)
            results = results[: max_stocks or 50]
            return {
                "strategy": "custom",
                "name": "Custom Filter",
                "description": f"Custom filter: ROCE>={min_roce}, ROE>={min_roe}, PE<={max_pe}, Mcap>={min_mcap_cr}Cr",
                "count": len(results),
                "stocks": results,
            }
        except Exception as e:
            logger.error(f"Error running custom screener: {e}")
            raise ValueError(f"Custom screen execution failed: {e}")


_screener_service: Optional[ScreenerService] = None


def get_screener_service(
    db_session=None,
    cache_service: Optional[CacheService] = None,
) -> ScreenerService:
    global _screener_service
    if _screener_service is None:
        _screener_service = ScreenerService(db_session=db_session, cache_service=cache_service)
    return _screener_service
