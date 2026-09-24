"""C-01 pre-change fixture: mixed INR/USD aggregation and currency whitelist."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent_c_fixture_support import FakeDB, run
from app.api.portfolio import get_portfolio
from fastapi import HTTPException


class FX:
    def __init__(self): self.calls = []
    async def convert_amount_with_provenance(self, amount, source, target):
        self.calls.append((amount, source, target))
        rate = 83.0 if (source, target) == ("USD", "INR") else 1 / 83
        return {
            "amount": amount * rate,
            "rate": {"rate": rate, "provenance": "live", "source": "mock-fx"},
            "from_currency": source,
            "to_currency": target,
        }
    async def convert_amount(self, amount, source, target):
        self.calls.append((amount, source, target))
        rate = 83.0 if (source, target) == ("USD", "INR") else 1 / 83
        return amount * rate


async def main():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    positions = [
        SimpleNamespace(id=1, ticker="AAPL", weight=.5, quantity=1, buy_price=100,
                        last_price=100, market_value=100, sector="Tech", industry="Software",
                        custom_name="US", added_on=now, updated_on=now, region="US"),
        SimpleNamespace(id=2, ticker="TCS.NS", weight=.5, quantity=1, buy_price=830,
                        last_price=830, market_value=830, sector="Tech", industry="Software",
                        custom_name="IN", added_on=now, updated_on=now, region="IN"),
    ]
    db = FakeDB(positions)
    service = SimpleNamespace(fetch_quote=AsyncMock(return_value=None))
    fx = FX()
    with patch("app.api.portfolio.get_currency_service", return_value=fx):
        result = await get_portfolio(currency="INR", db=db, data_service=service)
        print("before.total_value", result.total_value, "expected", 9130.0, "tolerance=1e-6")
        try:
            await get_portfolio(currency="EUR", db=db, data_service=service)
            print("before.unsupported_status", 200)
        except HTTPException as exc:
            print("before.unsupported_status", exc.status_code, exc.detail)
    print("before.fx_calls", fx.calls)
    print("verdict=REQUIRES_CONVERSION_AND_PROVENANCE")


if __name__ == "__main__":
    run(main())
