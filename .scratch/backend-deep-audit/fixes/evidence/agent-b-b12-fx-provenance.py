"""Agent B B-12 baseline: fallback FX looks like an ordinary live rate."""
import asyncio
from unittest.mock import patch
from app.services.currency_service import CurrencyConversionService
async def main():
    s=CurrencyConversionService()
    with patch("yfinance.Ticker", side_effect=Exception("vendor down")):
        rate=await s.get_exchange_rate("USD","INR")
        strict = "available"
        try:
            await s.convert_amount(100, "USD", "INR")
        except Exception as exc:
            strict = type(exc).__name__
    info=s.get_exchange_rate_info()
    print({"rate":rate,"provenance":info.get("provenance"),"is_fallback":info.get("is_fallback"),"age":info.get("age_seconds"),"strict_conversion":strict})
asyncio.run(main())
