"""
Currency conversion service for portfolio management
Supports conversion between USD and Indian Rupees (INR) with real-time exchange rates
Configured with INR as the default currency for Indian market focus
"""

import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict
from decimal import Decimal
import json
import os

from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class CurrencyConversionService:
    """Service for handling currency conversions between USD and INR"""
    
    def __init__(self):
        self._exchange_rates: Dict[str, float] = {}
        self._last_updated: Optional[datetime] = None
        self._cache_duration = timedelta(minutes=30)  # Cache for 30 minutes
        
    async def get_exchange_rate(self, from_currency: str, to_currency: str) -> float:
        """
        Get exchange rate between two currencies
        
        Args:
            from_currency: Source currency code (e.g., 'USD')
            to_currency: Target currency code (e.g., 'INR')
            
        Returns:
            Exchange rate from source to target currency
        """
        if from_currency == to_currency:
            return 1.0
            
        # Check cache first
        if self._is_cache_valid() and f"{from_currency}_{to_currency}" in self._exchange_rates:
            return self._exchange_rates[f"{from_currency}_{to_currency}"]
        
        # Fetch fresh exchange rate
        rate = await self._fetch_exchange_rate(from_currency, to_currency)
        
        # Update cache
        self._exchange_rates[f"{from_currency}_{to_currency}"] = rate
        self._exchange_rates[f"{to_currency}_{from_currency}"] = 1.0 / rate
        self._last_updated = datetime.utcnow()
        
        return rate
    
    async def convert_amount(self, amount: float, from_currency: str, to_currency: str) -> float:
        """
        Convert amount from one currency to another
        
        Args:
            amount: Amount to convert
            from_currency: Source currency code
            to_currency: Target currency code
            
        Returns:
            Converted amount in target currency
        """
        if amount == 0:
            return 0.0
            
        rate = await self.get_exchange_rate(from_currency, to_currency)
        return amount * rate
    
    def format_currency(self, amount: float, currency: str) -> str:
        """
        Format currency amount with proper symbols
        
        Args:
            amount: Amount to format
            currency: Currency code ('USD' or 'INR')
            
        Returns:
            Formatted currency string
        """
        if currency == 'INR':
            symbol = '₹'
            # Indian number formatting (lakhs, crores)
            if amount >= 10000000:  # 1 crore or more
                return f"{symbol}{amount/10000000:.2f} Cr"
            elif amount >= 100000:  # 1 lakh or more
                return f"{symbol}{amount/100000:.2f} L"
            else:
                return f"{symbol}{amount:,.2f}"
        else:  # USD
            symbol = '$'
            return f"{symbol}{amount:,.2f}"
    
    def format_currency_indian(self, amount: float, currency: str = 'INR') -> str:
        """
        Format currency using Indian numbering system
        
        Args:
            amount: Amount to format
            currency: Currency code
            
        Returns:
            Formatted currency string with Indian abbreviations
        """
        if currency == 'INR':
            symbol = '₹'
            if amount >= 10000000:  # 1 crore
                return f"{symbol}{(amount/10000000):.2f} Cr"
            elif amount >= 100000:  # 1 lakh
                return f"{symbol}{(amount/100000):.2f} L"
            elif amount >= 1000:  # 1 thousand
                return f"{symbol}{(amount/1000):.2f} K"
            else:
                return f"{symbol}{amount:,.2f}"
        else:
            return self.format_currency(amount, currency)
    
    def get_currency_symbol(self, currency: str) -> str:
        """Get currency symbol"""
        return '₹' if currency == 'INR' else '$'
    
    def get_exchange_rate_info(self) -> Dict[str, any]:
        """
        Get information about cached exchange rates
        
        Returns:
            Dictionary with rate info and last update time
        """
        return {
            'last_updated': self._last_updated.isoformat() if self._last_updated else None,
            'cache_duration_minutes': self._cache_duration.total_seconds() / 60,
            'cached_rates': len(self._exchange_rates),
            'usd_to_inr': self._exchange_rates.get('USD_INR', None)
        }
    
    def _is_cache_valid(self) -> bool:
        """Check if cached exchange rates are still valid"""
        if not self._last_updated:
            return False
        
        age = datetime.utcnow() - self._last_updated
        return age < self._cache_duration
    
    async def _fetch_exchange_rate(self, from_currency: str, to_currency: str) -> float:
        """
        Fetch exchange rate from external API or return fallback rate
        
        Args:
            from_currency: Source currency
            to_currency: Target currency
            
        Returns:
            Exchange rate
        """
        # For USD to INR, use a reasonable fallback rate
        # In production, you would integrate with a real API like:
        # - exchangerate-api.com
        # - fixer.io
        # - currencylayer.com
        
        if from_currency == 'USD' and to_currency == 'INR':
            # Fallback rate (should be updated regularly in production)
            # Approximate rate as of late 2024
            return 83.0
        elif from_currency == 'INR' and to_currency == 'USD':
            return 1.0 / 83.0
        else:
            # For other currency pairs, return 1.0 (no conversion)
            logger.warning(f"No exchange rate configured for {from_currency} to {to_currency}")
            return 1.0


# Global currency service instance
_currency_service: Optional[CurrencyConversionService] = None


def get_currency_service() -> CurrencyConversionService:
    """Get global currency service instance"""
    global _currency_service
    if _currency_service is None:
        _currency_service = CurrencyConversionService()
    return _currency_service


# Async context manager for currency service
class CurrencyServiceContext:
    """Context manager for currency service with cleanup"""
    
    def __init__(self):
        self.service = get_currency_service()
    
    async def __aenter__(self) -> CurrencyConversionService:
        return self.service
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Cleanup if needed
        pass


# Convenience functions - NOW DEFAULT TO INR FOR INDIAN MARKET
async def convert_portfolio_value(amount: float, target_currency: str = 'INR') -> float:
    """
    Convert portfolio value to target currency
    
    Args:
        amount: Amount to convert
        target_currency: Target currency ('USD' or 'INR')
        
    Returns:
        Converted amount
    """
    async with CurrencyServiceContext() as service:
        # Default to INR - assume amounts are in INR by default for Indian market
        return await service.convert_amount(amount, 'INR', target_currency)


async def format_portfolio_value(amount: float, currency: str = 'INR') -> str:
    """
    Format portfolio value with currency symbol
    
    Args:
        amount: Amount to format
        currency: Currency code
        
    Returns:
        Formatted currency string
    """
    async with CurrencyServiceContext() as service:
        return service.format_currency(amount, currency)


async def format_portfolio_value_indian(amount: float, currency: str = 'INR') -> str:
    """
    Format portfolio value with Indian numbering system
    
    Args:
        amount: Amount to format
        currency: Currency code
        
    Returns:
        Formatted currency string with Indian formatting
    """
    async with CurrencyServiceContext() as service:
        return service.format_currency_indian(amount, currency)


async def get_exchange_rate_usd_inr() -> float:
    """
    Get current USD to INR exchange rate
    
    Returns:
        Exchange rate
    """
    async with CurrencyServiceContext() as service:
        return await service.get_exchange_rate('USD', 'INR')