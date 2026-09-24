"""C-05 pre-change fixture: same tickers, different weights must not share tails."""
from __future__ import annotations
from unittest.mock import AsyncMock, Mock, patch
import pandas as pd
from app.api.analytics import get_tail_risk_and_copula, _TAILS_RESPONSE_CACHE
from agent_c_fixture_support import FakeDB, run


async def main():
    _TAILS_RESPONSE_CACHE.clear()
    ret = pd.DataFrame({"A": [0.01, -0.02] * 30, "B": [-0.01, 0.02] * 30})
    calls = []
    class Tail:
        @staticmethod
        def calculate_evt_pot_var_es(*args, **kwargs):
            calls.append("evt"); return {"evt": 1}
        @staticmethod
        def calculate_tail_dependence_matrix(*args, **kwargs):
            calls.append("copula"); return {"A": {"A": 1}, "B": {"B": 1}}
    async def resolve(_tickers, _db):
        return ["A", "B"], {"A": .8, "B": .2} if len(calls) == 0 else {"A": .2, "B": .8}
    with patch("app.api.analytics.resolve_allocation", side_effect=resolve), \
         patch("app.api.analytics._build_wide_returns", new=AsyncMock(return_value=(ret, ret["A"] * 0 + .01, {}))), \
         patch("app.services.tail_risk_service.TailRiskService", Tail):
        await get_tail_risk_and_copula(tickers="A,B", lookback_days=756, confidence_level=0.99, threshold_quantile=0.95, db=FakeDB(), data_service=Mock())
        await get_tail_risk_and_copula(tickers="A,B", lookback_days=756, confidence_level=0.99, threshold_quantile=0.95, db=FakeDB(), data_service=Mock())
    print("before.service_calls", len(calls), calls, "expected_second_recompute=4", "tolerance=0")
    print("verdict=REQUIRES_WEIGHT_IN_CACHE_KEY")


if __name__ == "__main__":
    run(main())
