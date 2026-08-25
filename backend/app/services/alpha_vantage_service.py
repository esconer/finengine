"""
Alpha Vantage fallback vendor for Daisy Risk Engine.

Error-classification and request patterns adapted from
TauricResearch/TradingAgents, tradingagents/dataflows/alpha_vantage_common.py
(Apache License 2.0, Copyright Tauric Research).

Modifications from the original:
- async surface (requests offloaded via asyncio.to_thread)
- MULTI-KEY POOL: several free API keys are rotated automatically when one
  hits a rate limit (daily or per-minute), multiplying effective free quota
  to N x 25 req/day. Per-key budgets are tracked in-process so exhausted
  keys are skipped WITHOUT burning a network call.
- error taxonomy distinguishes daily-limit vs call-frequency vs invalid-key
  notices (TradingAgents issue #991): daily phrases retire the key until
  midnight, frequency phrases impose a 60s cooldown, invalid keys are
  dropped from the pool.
- symbol bridge for Indian listings: yfinance's NSE suffix (.NS) maps to
  Alpha Vantage's BSE feed (.BSE); US-style symbols pass through unchanged.
  Caveat: a minority of companies use different ticker letters per exchange;
  failures here simply leave yfinance as sole source.

Licensed under the Apache License, Version 2.0.
"""

import asyncio
import re
import time
from collections import deque
from datetime import date as _date
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from app.config import settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

API_BASE_URL = "https://www.alphavantage.co/query"


def to_av_symbol(ticker: str) -> str:
    """Map our tickers to Alpha Vantage convention.

    .NS (NSE, yfinance style) -> .BSE (Alpha Vantage has no NSE feed; BSE
    lists the same companies). .BO already matches AV convention. Plain
    symbols (US etc.) pass through unchanged.
    """
    t = ticker.upper().strip()
    if t.endswith(".NS"):
        return t[:-3] + ".BSE"
    return t

# Cooldown applied to a key after a per-minute ("call frequency") rejection.
FREQUENCY_COOLDOWN_SECONDS = 60


class AlphaVantageRateLimitError(Exception):
    """All pooled keys are exhausted for today / right now."""


class AlphaVantageNotConfiguredError(Exception):
    """No usable API keys configured."""


def _classify_notice(notice: str) -> Optional[str]:
    """Classify an Information/Note payload.

    Returns 'daily' | 'frequency' | 'invalid_key' | 'other'.
    Rate-limit phrasing is checked BEFORE api-key phrasing because both
    mention "API key" (TradingAgents issue #991).
    """
    low = notice.lower()
    if "requests per day" in low or "rate limit" in low:
        return "daily"
    if "call frequency" in low or "per minute" in low:
        return "frequency"
    if "api key" in low or "apikey" in low:
        return "invalid_key"
    if "premium" in low:
        return "daily"
    return "other"


class _KeyBudget:
    """Per-key spend tracker; rolls over at local midnight."""

    def __init__(self, key: str, daily_limit: int, minute_limit: int):
        self.key = key
        self.daily_limit = daily_limit
        self.minute_limit = minute_limit
        self._day: Optional[_date] = None
        self.used_today = 0
        self._minute_stamps: deque = deque()
        self.cooldown_until = 0.0          # monotonic ts, for frequency hits
        self.retired_on: Optional[_date] = None  # day the key was marked daily-exhausted

    def _roll_day(self) -> None:
        today = _date.today()
        if self._day != today:
            self._day = today
            self.used_today = 0

    def available(self) -> bool:
        now = time.monotonic()
        if self.retired_on == _date.today():
            return False
        if now < self.cooldown_until:
            return False
        self._roll_day()
        if self.used_today >= self.daily_limit:
            return False
        while self._minute_stamps and now - self._minute_stamps[0] > 60:
            self._minute_stamps.popleft()
        return len(self._minute_stamps) < self.minute_limit

    def spend(self) -> None:
        self._roll_day()
        self._minute_stamps.append(time.monotonic())
        self.used_today += 1

    def remaining_today(self) -> int:
        self._roll_day()
        return max(0, self.daily_limit - self.used_today)


class KeyPool:
    """Ordered pool of API keys with per-key free-tier budgeting."""

    def __init__(self, keys: List[str], daily_limit: int, minute_limit: int):
        self.budgets = [_KeyBudget(k.strip(), daily_limit, minute_limit) for k in keys if k.strip()]
        # Positional cursor spreads load round-robin across healthy keys.
        self._cursor = 0

    @property
    def enabled(self) -> bool:
        return bool(self.budgets)

    def acquire(self) -> Optional[_KeyBudget]:
        """Return the next available key budget, scanning once from the cursor."""
        n = len(self.budgets)
        for i in range(n):
            b = self.budgets[(self._cursor + i) % n]
            if b.available():
                self._cursor = (self._cursor + i + 1) % n
                return b
        return None

    def mark_daily_exhausted(self, budget: _KeyBudget) -> None:
        budget.retired_on = _date.today()
        logger.warning(f"Alpha Vantage key ...{budget.key[-4:]} retired until midnight (daily limit)")

    def mark_frequency_limited(self, budget: _KeyBudget) -> None:
        budget.cooldown_until = time.monotonic() + FREQUENCY_COOLDOWN_SECONDS
        logger.warning(f"Alpha Vantage key ...{budget.key[-4:]} cooling down {FREQUENCY_COOLDOWN_SECONDS}s (frequency limit)")

    def drop_invalid(self, budget: _KeyBudget) -> None:
        logger.error(f"Alpha Vantage key ...{budget.key[-4:]} rejected - removing from pool")
        if budget in self.budgets:
            self.budgets.remove(budget)

    def total_remaining_today(self) -> int:
        return sum(b.remaining_today() for b in self.budgets)


def _configured_keys() -> List[str]:
    keys: List[str] = []
    if settings.alpha_vantage_api_key:
        keys.append(settings.alpha_vantage_api_key)
    raw = settings.alpha_vantage_api_keys or ""
    for part in re.split(r"[,;\s]+", raw):
        k = part.strip()
        if k and k not in keys:
            keys.append(k)
    return keys


class AlphaVantageService:
    """Async client over Alpha Vantage with multi-key rotation and budgeting."""

    def __init__(self):
        self.pool = KeyPool(
            _configured_keys(),
            settings.alpha_vantage_daily_limit,
            settings.alpha_vantage_minute_limit,
        )
        self.timeout = settings.alpha_vantage_timeout

    @property
    def enabled(self) -> bool:
        return self.pool.enabled

    # ------------------------------------------------------------------ core

    async def _make_request(self, function_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Issue an API call, rotating through keys on rate limits.

        Tries at most len(pool) keys per logical request; each rate-limited
        key is demoted (cooldown / retired / dropped) before the next try.

        Raises:
            AlphaVantageNotConfiguredError: no keys configured.
            AlphaVantageRateLimitError: every key exhausted.
            ValueError: non-rate-limit vendor error or malformed payload.
        """
        if not self.pool.enabled:
            raise AlphaVantageNotConfiguredError("No ALPHA_VANTAGE_API_KEY(S) configured")

        # Default error: local budgets ran dry without any server rejection.
        last_error: Exception = AlphaVantageRateLimitError(
            f"All {len(self.pool.budgets)} Alpha Vantage key(s) are exhausted"
        )
        for _ in range(max(1, len(self.pool.budgets))):
            budget = self.pool.acquire()
            if budget is None:
                break

            query = {"function": function_name, "apikey": budget.key, **params}

            def _get() -> requests.Response:
                return requests.get(API_BASE_URL, params=query, timeout=self.timeout)

            response = await asyncio.to_thread(_get)
            response.raise_for_status()

            try:
                data = response.json()
            except ValueError:
                raise ValueError(f"Alpha Vantage returned non-JSON payload for {function_name}")

            notice = data.get("Information") or data.get("Note") or data.get("Error Message")
            if not notice:
                budget.spend()
                return data

            kind = _classify_notice(str(notice))
            if kind == "daily":
                self.pool.mark_daily_exhausted(budget)
                last_error = AlphaVantageRateLimitError(str(notice))
            elif kind == "frequency":
                self.pool.mark_frequency_limited(budget)
                last_error = AlphaVantageRateLimitError(str(notice))
            elif kind == "invalid_key":
                self.pool.drop_invalid(budget)
                last_error = AlphaVantageNotConfiguredError(str(notice))
            else:
                raise ValueError(f"Alpha Vantage notice: {notice}")

        raise last_error

    # --------------------------------------------------------------- series

    async def fetch_daily_ohlcv(self, ticker: str, start: str, end: str) -> Optional[pd.DataFrame]:
        """TIME_SERIES_DAILY -> DataFrame in our lowercase cache schema.

        adj_close mirrors close: TIME_SERIES_DAILY serves unadjusted prices
        (the adjusted variant is premium-only), recorded here for transparency.
        Returns None when the vendor yields no rows in range.
        """
        av_symbol = to_av_symbol(ticker)
        data = await self._make_request("TIME_SERIES_DAILY", {"symbol": av_symbol})

        series = data.get("Time Series (Daily)") or {}
        rows: List[Dict[str, Any]] = []
        start_dt, end_dt = pd.to_datetime(start), pd.to_datetime(end)
        for day, values in sorted(series.items()):
            day_dt = pd.to_datetime(day)
            if not (start_dt <= day_dt <= end_dt):
                continue
            try:
                rows.append({
                    "date": day_dt,
                    "open": float(values["1. open"]),
                    "high": float(values["2. high"]),
                    "low": float(values["3. low"]),
                    "close": float(values["4. close"]),
                    "adj_close": float(values["4. close"]),  # unadjusted source
                    "volume": int(float(values.get("5. volume", 0))),
                })
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"Skipping malformed AV row {av_symbol} {day}: {e}")

        if not rows:
            logger.info(f"Alpha Vantage returned no rows for {av_symbol} in range")
            return None
        df = pd.DataFrame(rows)
        df.insert(0, "ticker", av_symbol.upper())
        logger.info(f"Alpha Vantage supplied {len(df)} rows for {av_symbol}")
        return df

    # ---------------------------------------------------------------- quote

    async def fetch_global_quote(self, ticker: str) -> Optional[Dict[str, Any]]:
        """GLOBAL_QUOTE -> partial quote dict matching our quote schema.

        Fills price/volume/day-range only; fundamentals fields (sector,
        industry, PE...) are absent from this endpoint and left None so
        callers using .get() degrade gracefully.
        """
        av_symbol = to_av_symbol(ticker)
        data = await self._make_request("GLOBAL_QUOTE", {"symbol": av_symbol})
        q = data.get("Global Quote") or {}
        price_raw = q.get("05. price")
        if not price_raw:
            return None
        try:
            return {
                "ticker": av_symbol.upper(),
                "current_price": float(price_raw),
                "volume": int(float(q.get("06. volume") or 0)),
                "market_cap": None,
                "sector": None,
                "industry": None,
                "52_week_high": None,
                "52_week_low": None,
                "pe_ratio": None,
                "dividend_yield": None,
                "previous_close": float(q["08. previous close"]) if q.get("08. previous close") else None,
                "change_percent": q.get("10. change percent"),
                "currency": "INR" if ".BSE" in av_symbol else "USD",
                "exchange": "BSE" if ".BSE" in av_symbol else "Other",
                "source": "alphavantage",
                "timestamp": pd.Timestamp.utcnow().isoformat(),
            }
        except (KeyError, TypeError, ValueError) as e:
            logger.warning(f"Malformed AV quote for {av_symbol}: {e}")
            return None


_service: Optional[AlphaVantageService] = None


def get_alpha_vantage_service() -> AlphaVantageService:
    """Process-wide service instance (keys read once from settings)."""
    global _service
    if _service is None:
        _service = AlphaVantageService()
    return _service
