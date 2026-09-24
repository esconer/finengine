"""Alpha Vantage fallback client with identity-safe symbols and typed errors."""

import asyncio
import math
import re
import time
from collections import deque
from datetime import date as _date, datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from app.config import settings
from app.services.cache_service import (
    ProviderAuthError,
    ProviderError,
    ProviderInvalidInputError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderUnavailableError,
    UnknownTickerError,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

API_BASE_URL = "https://www.alphavantage.co/query"
FREQUENCY_COOLDOWN_SECONDS = 60

# No exchange substitution is implicit.  An operator may add a verified,
# identity-specific mapping here after checking the issuer/security identity.
AV_SYMBOL_MAP: Dict[str, str] = {}


class AlphaVantageRateLimitError(ProviderRateLimitError):
    """All pooled keys are exhausted for today or right now."""

    def __init__(self, message: str) -> None:
        super().__init__(message, provider="alphavantage")


class AlphaVantageNotConfiguredError(ProviderAuthError):
    """No usable API keys are configured."""

    def __init__(self, message: str) -> None:
        super().__init__(message, provider="alphavantage")


class AlphaVantageInvalidInputError(ProviderInvalidInputError):
    """The request or returned payload is structurally invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, provider="alphavantage")


class AlphaVantageUnknownTickerError(UnknownTickerError):
    """The provider explicitly reported that the symbol is unknown."""

    def __init__(self, message: str) -> None:
        super().__init__(message, provider="alphavantage")


class AlphaVantageIdentityError(ProviderUnavailableError):
    """A requested exchange/listing cannot be proven equivalent to AV's feed."""

    def __init__(self, message: str) -> None:
        super().__init__(message, provider="alphavantage", status_code=503, retryable=False)


def to_av_symbol(ticker: str, *, allow_exchange_mapping: bool = False) -> Optional[str]:
    """Resolve a ticker without silently changing its exchange identity.

    Alpha Vantage has no general NSE feed and a ``.BO``/``.BSE`` spelling is
    not enough proof that the security is the same listing.  Exchange-suffixed
    Indian tickers therefore return ``None`` unless an operator has added a
    verified entry to ``AV_SYMBOL_MAP``.  Plain/global symbols pass through unchanged.
    """
    raw = str(ticker or "").upper().strip()
    if not raw:
        return None
    if raw in AV_SYMBOL_MAP:
        return AV_SYMBOL_MAP[raw]
    if raw.endswith((".NS", ".BO", ".BSE")):
        # Even an opt-in flag is not identity verification.  Only entries in
        # AV_SYMBOL_MAP (checked above) may cross an exchange boundary.
        return None
    if any(ch.isspace() for ch in raw):
        return None
    return raw


def _quota_day() -> _date:
    """Alpha Vantage free-tier quota resets at US Eastern midnight."""
    try:
        return datetime.now(ZoneInfo("America/New_York")).date()
    except Exception:
        return _date.today()


def _classify_notice(notice: str) -> Optional[str]:
    """Classify an Information/Note/Error payload without exposing it."""
    low = str(notice).lower()
    if "requests per day" in low or "rate limit" in low or "daily limit" in low:
        return "daily"
    if "call frequency" in low or "per minute" in low or "frequency" in low:
        return "frequency"
    if "api key" in low or "apikey" in low or "invalid key" in low:
        return "invalid_key"
    if any(token in low for token in ("invalid api call", "unknown symbol", "symbol not found", "ticker not found", "not found")):
        return "unknown_ticker"
    return "other"


def _safe_notice(notice: Any, secrets: Optional[List[str]] = None) -> str:
    """Return a bounded notice with query/key material removed."""
    text = str(notice or "")
    text = re.sub(r"(?i)(apikey|api_key|key)=([^&\s]+)", r"\1=<REDACTED>", text)
    for secret in secrets or []:
        if secret:
            text = text.replace(secret, "<REDACTED>")
    return text[:240]


class _KeyBudget:
    """Per-key spend tracker; rolls over at local midnight."""

    def __init__(self, key: str, daily_limit: int, minute_limit: int):
        self.key = key
        self.daily_limit = daily_limit
        self.minute_limit = minute_limit
        self._day: Optional[_date] = None
        self.used_today = 0
        self._minute_stamps: deque = deque()
        self.cooldown_until = 0.0
        self.retired_on: Optional[_date] = None

    def _roll_day(self) -> None:
        today = _quota_day()
        if self._day != today:
            self._day = today
            self.used_today = 0

    def available(self) -> bool:
        now = time.monotonic()
        if self.retired_on == _quota_day():
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
        self._cursor = 0

    @property
    def enabled(self) -> bool:
        return bool(self.budgets)

    def acquire(self) -> Optional[_KeyBudget]:
        n = len(self.budgets)
        for i in range(n):
            budget = self.budgets[(self._cursor + i) % n]
            if budget.available():
                self._cursor = (self._cursor + i + 1) % n
                return budget
        return None

    def mark_daily_exhausted(self, budget: _KeyBudget) -> None:
        budget.retired_on = _quota_day()
        logger.warning("Alpha Vantage key retired until midnight (daily limit)")

    def mark_frequency_limited(self, budget: _KeyBudget) -> None:
        budget.cooldown_until = time.monotonic() + FREQUENCY_COOLDOWN_SECONDS
        logger.warning("Alpha Vantage key cooling down for frequency limit")

    def drop_invalid(self, budget: _KeyBudget) -> None:
        logger.error("Alpha Vantage key rejected; removing it from the pool")
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
        key = part.strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def _parse_bounds(start: str, end: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    try:
        start_dt = pd.Timestamp(start).normalize()
        end_dt = pd.Timestamp(end).normalize()
    except (TypeError, ValueError) as exc:
        raise AlphaVantageInvalidInputError("Invalid historical date bounds") from exc
    if pd.isna(start_dt) or pd.isna(end_dt) or start_dt > end_dt:
        raise AlphaVantageInvalidInputError("Historical date bounds are invalid")
    return start_dt, end_dt


def _finite_positive(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


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

    async def _make_request(self, function_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Issue a request and classify failures without logging request URLs."""
        if not self.pool.enabled:
            raise AlphaVantageNotConfiguredError("No Alpha Vantage keys configured")

        last_error: ProviderError = AlphaVantageRateLimitError("All Alpha Vantage keys are exhausted")
        for _ in range(max(1, len(self.pool.budgets))):
            budget = self.pool.acquire()
            if budget is None:
                break
            query = {"function": function_name, "apikey": budget.key, **params}

            def _get() -> requests.Response:
                return requests.get(API_BASE_URL, params=query, timeout=self.timeout)

            try:
                response = await asyncio.to_thread(_get)
            except requests.Timeout:
                last_error = ProviderUnavailableError("Alpha Vantage request timed out", provider="alphavantage")
                # A transport timeout is not evidence of a per-minute quota
                # violation; do not retire/cool down a key for the wrong cause.
                logger.warning("AV timeout on %s", function_name)
                continue
            except requests.RequestException as exc:
                last_error = ProviderUnavailableError("Alpha Vantage network failure", provider="alphavantage")
                logger.warning("AV network error on %s: %s", function_name, type(exc).__name__)
                continue

            try:
                response.raise_for_status()
            except requests.HTTPError:
                status = int(getattr(response, "status_code", 0) or 0)
                if status == 429:
                    self.pool.mark_frequency_limited(budget)
                    last_error = AlphaVantageRateLimitError("Alpha Vantage rate limit")
                elif status in (401, 403):
                    self.pool.drop_invalid(budget)
                    last_error = AlphaVantageNotConfiguredError("Alpha Vantage authentication rejected")
                elif status >= 500:
                    # Server failures are retryable outages, not frequency
                    # notices; preserve the key for the next bounded attempt.
                    last_error = ProviderServerError("Alpha Vantage server unavailable", provider="alphavantage")
                elif status == 400:
                    last_error = AlphaVantageInvalidInputError("Alpha Vantage rejected the request")
                elif status == 404:
                    last_error = AlphaVantageUnknownTickerError("Alpha Vantage symbol is unknown")
                else:
                    last_error = ProviderUnavailableError("Alpha Vantage HTTP failure", provider="alphavantage")
                # Never interpolate HTTPError: requests embeds the query URL/key.
                logger.warning("AV HTTP error on %s: status=%s", function_name, status)
                continue

            try:
                data = response.json()
            except (TypeError, ValueError) as exc:
                raise ProviderServerError("Alpha Vantage returned a non-JSON response", provider="alphavantage") from exc

            if not isinstance(data, dict):
                raise AlphaVantageInvalidInputError("Alpha Vantage returned an invalid payload")
            notice = data.get("Information") or data.get("Note") or data.get("Error Message")
            if not notice:
                budget.spend()
                return data

            safe_notice = _safe_notice(notice, [budget.key])
            kind = _classify_notice(safe_notice)
            if kind == "daily":
                self.pool.mark_daily_exhausted(budget)
                last_error = AlphaVantageRateLimitError("Alpha Vantage daily limit")
            elif kind == "frequency":
                self.pool.mark_frequency_limited(budget)
                last_error = AlphaVantageRateLimitError("Alpha Vantage call frequency limit")
            elif kind == "invalid_key":
                self.pool.drop_invalid(budget)
                last_error = AlphaVantageNotConfiguredError("Alpha Vantage key rejected")
            elif kind == "unknown_ticker":
                last_error = AlphaVantageUnknownTickerError("Alpha Vantage symbol is unknown")
            else:
                last_error = AlphaVantageInvalidInputError("Alpha Vantage notice: request rejected")
            logger.warning("AV notice on %s: %s", function_name, safe_notice)

        raise last_error

    async def fetch_daily_ohlcv(self, ticker: str, start: str, end: str) -> Optional[pd.DataFrame]:
        """Fetch inclusive historical OHLCV, returning only structurally valid rows."""
        requested_ticker = str(ticker or "").upper().strip()
        av_symbol = to_av_symbol(requested_ticker)
        if not av_symbol:
            raise AlphaVantageIdentityError("Alpha Vantage listing identity is unavailable for this exchange")
        start_dt, end_dt = _parse_bounds(start, end)
        data = await self._make_request(
            "TIME_SERIES_DAILY", {"symbol": av_symbol, "outputsize": "full"}
        )
        if not isinstance(data, dict):
            raise AlphaVantageInvalidInputError("Alpha Vantage returned an invalid series payload")
        metadata = data.get("Meta Data") or data.get("MetaData") or {}
        returned_symbol = metadata.get("2. Symbol") or metadata.get("Symbol")
        if returned_symbol and str(returned_symbol).upper() != av_symbol.upper():
            raise AlphaVantageIdentityError("Alpha Vantage returned a different security identity")

        series = data.get("Time Series (Daily)") or {}
        rows: List[Dict[str, Any]] = []
        for day, values in sorted(series.items()):
            try:
                day_dt = pd.Timestamp(day).normalize()
            except (TypeError, ValueError):
                continue
            if not (start_dt <= day_dt <= end_dt):
                continue
            try:
                open_price = float(values["1. open"])
                high = float(values["2. high"])
                low = float(values["3. low"])
                close = float(values["4. close"])
                volume = float(values.get("5. volume", 0))
                valid = all(math.isfinite(v) and v > 0 for v in (open_price, high, low, close))
                valid = valid and high >= max(open_price, close, low) and low <= min(open_price, close, high) and volume >= 0
                if not valid:
                    continue
                rows.append({
                    "date": day_dt,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "adj_close": close,
                    "volume": int(volume),
                    "ticker": requested_ticker,
                })
            except (KeyError, TypeError, ValueError, OverflowError):
                logger.warning("Skipping malformed AV historical row for %s", requested_ticker)

        if not rows:
            return None
        return pd.DataFrame(rows)

    async def fetch_global_quote(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch a quote while preserving the requested listing identity."""
        requested_ticker = str(ticker or "").upper().strip()
        av_symbol = to_av_symbol(requested_ticker)
        if not av_symbol:
            raise AlphaVantageIdentityError("Alpha Vantage listing identity is unavailable for this exchange")
        data = await self._make_request("GLOBAL_QUOTE", {"symbol": av_symbol})
        quote = data.get("Global Quote") or {}
        returned_symbol = quote.get("01. symbol")
        if returned_symbol and str(returned_symbol).upper() != av_symbol.upper():
            raise AlphaVantageIdentityError("Alpha Vantage returned a different security identity")
        price_raw = quote.get("05. price")
        if not _finite_positive(price_raw):
            return None
        try:
            change = quote.get("10. change percent")
            previous = quote.get("08. previous close")
            return {
                "ticker": requested_ticker,
                "current_price": float(price_raw),
                "volume": int(float(quote.get("06. volume") or 0)),
                "market_cap": None,
                "sector": None,
                "industry": None,
                "52_week_high": None,
                "52_week_low": None,
                "week_52_high": None,
                "week_52_low": None,
                "pe_ratio": None,
                "dividend_yield": None,
                "previous_close": float(previous) if previous else None,
                "change_percent": float(str(change).rstrip("%")) if change else None,
                "currency": "INR" if _is_indian(requested_ticker) else "USD",
                "exchange": "BSE" if av_symbol.endswith(".BSE") else "Other",
                "source": "alphavantage",
                "is_indian": _is_indian(requested_ticker),
                "timestamp": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
            }
        except (KeyError, TypeError, ValueError):
            raise AlphaVantageInvalidInputError("Alpha Vantage returned a malformed quote")


def _is_indian(ticker: str) -> bool:
    return str(ticker).upper().endswith((".NS", ".BO", ".BSE"))


_service: Optional[AlphaVantageService] = None


def get_alpha_vantage_service() -> AlphaVantageService:
    global _service
    if _service is None:
        _service = AlphaVantageService()
    return _service
