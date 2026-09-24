"""
Currency conversion service for portfolio management.

The service supports the currencies it can actually quote: INR and USD (plus
their inverse).  A hard-coded emergency rate is never represented as a live
quote: it is returned as a float-compatible ``FXRate`` carrying explicit
provenance and age, and it is not written to the live-rate cache.
"""

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.services.cache_service import (
    CacheService,
    ProviderUnavailableError,
    cache_generation_is_current,
    get_cache_generation,
    get_runtime_cache_snapshot,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Served (never cached as live) when the live FX vendor is unreachable.
FALLBACK_USD_INR = 83.0
SUPPORTED_CURRENCIES = ("INR", "USD")


class CurrencyUnavailableError(ProviderUnavailableError):
    """A portfolio FX conversion could not be completed from a live quote."""

    def __init__(self, message: str = "Live FX unavailable") -> None:
        super().__init__(message, provider="currency")


class FXRate(float):
    """Float-compatible rate with honest provenance metadata.

    Existing numeric callers remain source-compatible, while new callers can
    inspect ``provenance``/``fetched_at`` instead of treating 83.0 as live.
    """

    def __new__(
        cls,
        value: float,
        *,
        provenance: str = "live",
        source: str = "yfinance",
        fetched_at: Optional[datetime] = None,
    ) -> "FXRate":
        obj = float.__new__(cls, value)
        obj.provenance = provenance
        obj.source = source
        obj.fetched_at = fetched_at or datetime.now(timezone.utc)
        obj.is_fallback = provenance == "fallback"
        return obj

    @property
    def age_seconds(self) -> float:
        age = datetime.now(timezone.utc) - self.fetched_at
        return max(0.0, age.total_seconds())

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rate": float(self),
            "provenance": self.provenance,
            "source": self.source,
            "is_fallback": self.is_fallback,
            "fetched_at": self.fetched_at.isoformat(),
            "age_seconds": round(self.age_seconds, 3),
        }


def coerce_live_fx_rate(candidate: Any) -> tuple[float, Dict[str, Any]]:
    """Validate an FX quote as live, returning its rate and safe metadata.

    API conversion seams must not infer that an unlabelled number is live.  The
    only accepted non-identity quote therefore carries ``provenance="live"``;
    emergency constants and metadata-free adapters fail closed as a typed FX
    outage instead of entering portfolio arithmetic.
    """
    if isinstance(candidate, dict):
        rate_value = candidate.get("rate")
        metadata = {
            key: candidate.get(key)
            for key in ("provenance", "source", "is_fallback", "fetched_at", "age_seconds")
            if key in candidate
        }
    else:
        rate_value = candidate
        metadata = {
            key: getattr(candidate, key)
            for key in ("provenance", "source", "is_fallback", "fetched_at", "age_seconds")
            if hasattr(candidate, key)
        }

    fallback_flag = metadata.get("is_fallback")
    is_fallback = (
        fallback_flag is True
        or str(fallback_flag).strip().lower() in {"1", "true", "yes"}
        or str(metadata.get("provenance", "")).strip().lower() == "fallback"
        or str(metadata.get("source", "")).strip().lower() == "fallback_constant"
    )
    provenance = str(metadata.get("provenance", "")).strip().lower()
    if is_fallback or provenance != "live":
        raise CurrencyUnavailableError()

    try:
        numeric_rate = float(rate_value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CurrencyUnavailableError() from exc
    if not math.isfinite(numeric_rate) or numeric_rate <= 0:
        raise CurrencyUnavailableError()

    if isinstance(metadata.get("fetched_at"), datetime):
        metadata["fetched_at"] = metadata["fetched_at"].isoformat()
    if "age_seconds" in metadata:
        try:
            metadata["age_seconds"] = round(float(metadata["age_seconds"]), 3)
        except (TypeError, ValueError, OverflowError):
            metadata.pop("age_seconds", None)
    return numeric_rate, metadata


class CurrencyConversionService:
    """USD/INR conversion with explicit live-versus-fallback provenance."""

    def __init__(self, db_session=None):
        self._exchange_rates: Dict[str, float] = {}
        self._rate_metadata: Dict[str, Dict[str, Any]] = {}
        self._last_rate_metadata: Optional[Dict[str, Any]] = None
        self._last_rate_value: Optional[float] = None
        self._last_updated: Optional[datetime] = None
        self._cache_duration = timedelta(minutes=30)
        self._refresh_lock = asyncio.Lock()
        self.cache_service = CacheService(db_session) if db_session is not None else None

    @staticmethod
    def _currency(value: str) -> str:
        code = str(value or "").strip().upper()
        if code not in SUPPORTED_CURRENCIES:
            raise ValueError(
                f"No exchange rate configured for {value!r}; supported currencies: {', '.join(SUPPORTED_CURRENCIES)}"
            )
        return code

    async def _cache_enabled(self) -> bool:
        if self.cache_service is not None:
            return (await self.cache_service.get_runtime_config()).enabled
        snapshot = get_runtime_cache_snapshot()
        return snapshot.enabled if snapshot is not None else True

    async def get_exchange_rate(self, from_currency: str, to_currency: str) -> FXRate:
        """Return a float-compatible rate with provenance metadata.

        ``FXRate`` behaves exactly like a float for existing arithmetic callers.
        Consumers that need to distinguish a fallback should inspect
        ``is_fallback``/``provenance`` or use ``get_exchange_rate_info``.
        """
        source = self._currency(from_currency)
        target = self._currency(to_currency)
        if source == target:
            return FXRate(1.0, provenance="identity", source="identity")

        cache_key = f"{source}_{target}"
        use_cache = await self._cache_enabled()

        if use_cache and self._is_cache_valid() and cache_key in self._exchange_rates:
            metadata = self._rate_metadata.get(cache_key, {})
            cached_rate = FXRate(
                self._exchange_rates[cache_key],
                provenance=metadata.get("provenance", "live"),
                source=metadata.get("source", "yfinance"),
                fetched_at=metadata.get("fetched_at"),
            )
            self._last_rate_value = float(cached_rate)
            return cached_rate

        async with self._refresh_lock:
            if use_cache and self._is_cache_valid() and cache_key in self._exchange_rates:
                metadata = self._rate_metadata.get(cache_key, {})
                return FXRate(
                    self._exchange_rates[cache_key],
                    provenance=metadata.get("provenance", "live"),
                    source=metadata.get("source", "yfinance"),
                    fetched_at=metadata.get("fetched_at"),
                )

            generation = get_cache_generation()
            rate_value, is_fallback = await self._fetch_exchange_rate(source, target)
            rate = FXRate(
                float(rate_value),
                provenance="fallback" if is_fallback else "live",
                source="fallback_constant" if is_fallback else "yfinance",
            )
            self._last_rate_value = float(rate)
            if not cache_generation_is_current(generation):
                raise CurrencyUnavailableError("FX result superseded by cache purge")
            if not is_fallback:
                self._exchange_rates[cache_key] = float(rate)
                inverse = 1.0 / float(rate) if float(rate) > 0 else None
                if inverse is not None:
                    inverse_key = f"{target}_{source}"
                    self._exchange_rates[inverse_key] = inverse
                    self._rate_metadata[inverse_key] = {
                        "provenance": "live",
                        "source": "yfinance",
                        "fetched_at": rate.fetched_at,
                    }
                self._rate_metadata[cache_key] = {
                    "provenance": "live",
                    "source": "yfinance",
                    "fetched_at": rate.fetched_at,
                }
                self._last_rate_metadata = self._rate_metadata[cache_key]
                self._last_updated = rate.fetched_at
            else:
                self._last_rate_metadata = {
                    "provenance": "fallback",
                    "source": "fallback_constant",
                    "fetched_at": rate.fetched_at,
                }
                logger.warning(
                    "FX fallback served for %s (not cached): live vendor unavailable", cache_key
                )
            return rate

    async def convert_amount(
        self,
        amount: float,
        from_currency: str,
        to_currency: str,
        *,
        allow_fallback: bool = False,
    ) -> float:
        """Convert an amount; live FX is required unless fallback is explicit."""
        value = float(amount)
        if not math.isfinite(value):
            raise ValueError("amount must be finite")
        if value == 0:
            return 0.0
        rate = await self.get_exchange_rate(from_currency, to_currency)
        if bool(getattr(rate, "is_fallback", False)) and not allow_fallback:
            raise CurrencyUnavailableError("Live FX unavailable; fallback conversion refused")
        return value * float(rate)

    async def convert_amount_with_provenance(
        self,
        amount: float,
        from_currency: str,
        to_currency: str,
        *,
        allow_fallback: bool = False,
    ) -> Dict[str, Any]:
        """Return converted value plus rate provenance; fallback is opt-in."""
        rate = await self.get_exchange_rate(from_currency, to_currency)
        value = float(amount)
        if not math.isfinite(value):
            raise ValueError("amount must be finite")
        if bool(getattr(rate, "is_fallback", False)) and not allow_fallback:
            raise CurrencyUnavailableError("Live FX unavailable; fallback conversion refused")
        return {
            "amount": value * float(rate),
            "rate": rate.as_dict(),
            "from_currency": self._currency(from_currency),
            "to_currency": self._currency(to_currency),
        }

    def format_currency(self, amount: float, currency: str) -> str:
        """Format a supported currency without silently labelling others as USD."""
        code = self._currency(currency)
        if code == 'INR':
            if amount >= 10000000:
                return f"₹{amount/10000000:.2f} Cr"
            if amount >= 100000:
                return f"₹{amount/100000:.2f} L"
            return f"₹{amount:,.2f}"
        return f"${amount:,.2f}"

    def format_currency_indian(self, amount: float, currency: str = 'INR') -> str:
        if self._currency(currency) == 'INR' and 1000 <= amount < 100000:
            return f"₹{amount/1000:.2f} K"
        return self.format_currency(amount, currency)

    def get_currency_symbol(self, currency: str) -> str:
        code = self._currency(currency)
        return '₹' if code == 'INR' else '$'

    def get_exchange_rate_info(self) -> Dict[str, Any]:
        """Describe cached live rates and the most recent fallback provenance."""
        usd_meta = self._rate_metadata.get("USD_INR")
        latest_meta = usd_meta or self._last_rate_metadata
        if latest_meta:
            fetched_at = latest_meta.get("fetched_at")
            age = (
                max(0.0, (datetime.now(timezone.utc) - fetched_at).total_seconds())
                if isinstance(fetched_at, datetime)
                else None
            )
        else:
            fetched_at = None
            age = None
        return {
            'last_updated': self._last_updated.isoformat() if self._last_updated else None,
            'cache_duration_minutes': self._cache_duration.total_seconds() / 60,
            'cached_rates': len([k for k in self._exchange_rates if not k.endswith("_meta")]),
            'usd_to_inr': self._exchange_rates.get('USD_INR'),
            'last_served_rate': self._last_rate_value,
            'supported_currencies': list(SUPPORTED_CURRENCIES),
            'provenance': latest_meta.get('provenance') if latest_meta else None,
            'source': latest_meta.get('source') if latest_meta else None,
            'is_fallback': bool(latest_meta and latest_meta.get('provenance') == 'fallback'),
            'fetched_at': fetched_at.isoformat() if isinstance(fetched_at, datetime) else None,
            'age_seconds': round(age, 3) if age is not None else None,
        }

    def _is_cache_valid(self) -> bool:
        if not self._last_updated:
            return False
        age = datetime.now(timezone.utc) - self._last_updated
        return age < self._cache_duration

    async def _fetch_exchange_rate(self, from_currency: str, to_currency: str) -> tuple[float, bool]:
        """Fetch USDINR=X, or return the marked emergency fallback."""
        source = self._currency(from_currency)
        target = self._currency(to_currency)
        if {source, target} != {"USD", "INR"}:
            raise ValueError(f"No exchange rate configured for {source} to {target}")

        def _get_live_rate() -> Optional[float]:
            try:
                import yfinance as yf
                ticker = yf.Ticker("USDINR=X")
                fast_info = getattr(ticker, "fast_info", None)
                if fast_info:
                    price = getattr(fast_info, "last_price", None) or getattr(
                        fast_info, "regular_market_price", None
                    )
                    if price and float(price) > 0 and math.isfinite(float(price)):
                        return float(price)
                hist = ticker.history(period="5d")
                if not hist.empty and "Close" in hist.columns:
                    closes = pd_numeric(hist["Close"])
                    if not closes.empty and float(closes.iloc[-1]) > 0:
                        return float(closes.iloc[-1])
            except Exception as exc:
                # Never log the upstream text: it can contain a request URL/query.
                logger.warning("Live USDINR=X fetch failed: %s", type(exc).__name__)
            return None

        try:
            live_usd_inr = await asyncio.to_thread(_get_live_rate)
        except Exception as exc:
            logger.warning("Async USDINR=X fetch failed: %s", type(exc).__name__)
            live_usd_inr = None

        if live_usd_inr is not None and live_usd_inr > 0 and math.isfinite(live_usd_inr):
            rate = live_usd_inr if source == "USD" else 1.0 / live_usd_inr
            return rate, False
        fallback = FALLBACK_USD_INR if source == "USD" else 1.0 / FALLBACK_USD_INR
        return fallback, True


def pd_numeric(values):
    """Small local coercion helper; avoids importing pandas for one FX series."""
    import pandas as pd

    return pd.to_numeric(values, errors="coerce").dropna()


_currency_service: Optional[CurrencyConversionService] = None


def get_currency_service(db_session=None) -> CurrencyConversionService:
    global _currency_service
    if _currency_service is None:
        _currency_service = CurrencyConversionService(db_session=db_session)
    elif db_session is not None and _currency_service.cache_service is None:
        _currency_service.cache_service = CacheService(db_session)
    return _currency_service


async def convert_portfolio_value(amount: float, target_currency: str = 'INR') -> float:
    return await get_currency_service().convert_amount(amount, 'INR', target_currency)


async def format_portfolio_value(amount: float, currency: str = 'INR') -> str:
    return get_currency_service().format_currency(amount, currency)


async def format_portfolio_value_indian(amount: float, currency: str = 'INR') -> str:
    return get_currency_service().format_currency_indian(amount, currency)


async def get_exchange_rate_usd_inr() -> FXRate:
    return await get_currency_service().get_exchange_rate('USD', 'INR')
