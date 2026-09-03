"""
Phase 1+2 endpoint tests: tear-sheet, risk-contribution, optimizer, regime.

Market seam fully mocked (GlobalDataService + BenchmarkService inside the
analytics namespace); all math downstream runs for real.
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import pandas as pd
import pytest


def _frame(days=260, seed=7, vol=0.015):
    dates = pd.date_range("2025-01-01", periods=days, freq="B")
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, vol, days)))
    return pd.DataFrame({
        "date": dates, "open": close * 0.995, "high": close * 1.008,
        "low": close * 0.992, "close": close, "adj_close": close,
        "volume": np.full(days, 250_000.0), "ticker": "TEST",
    })


@pytest.fixture
def patch_market():
    """Patch both market seams inside app.api.analytics and regime_service."""

    def _apply(frames=None, bench_returns=None):
        service = Mock()
        def _fetch(ticker, start, end, force_refresh=False):
            f = (frames or {}).get(ticker)
            return f if f is not None else _frame(seed=len(ticker))
        service.get_service.return_value.fetch_historical_data = AsyncMock(
            side_effect=lambda t, s, e, force_refresh=False: _fetch(t, s, e, force_refresh)
        )
        bench = Mock()
        # detect_regime awaits get_benchmark_df FIRST: it must be async and
        # miss (None) so the fallback get_returns path is exercised.
        bench.get_benchmark_df = AsyncMock(return_value=None)
        if bench_returns is not None:
            bench.get_returns = AsyncMock(return_value=bench_returns)
        else:
            bench.get_returns = AsyncMock(return_value=None)

        ctx1 = patch("app.api.analytics.GlobalDataService", return_value=service)
        
        @contextmanager
        def _bench_ctx():
            with patch("app.api.analytics.BenchmarkService", return_value=bench), \
                 patch("app.services.regime_service.BenchmarkService", return_value=bench):
                yield
        ctx2 = _bench_ctx()
        return ctx1, ctx2

    return _apply


def _bench_series(days=400, seed=11):
    idx = pd.date_range("2024-06-01", periods=days, freq="B")
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0004, 0.011, days), index=idx)


@pytest.mark.api
class TestTearSheet:
    @pytest.mark.asyncio
    async def test_metrics_and_relative_block(self, async_client, seeded_positions, patch_market):
        ctx1, ctx2 = patch_market(bench_returns=_bench_series())
        with ctx1, ctx2:
            resp = await async_client.get("/api/v1/analytics/tear-sheet")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        for key in ("total_return", "cagr", "sharpe", "sortino", "calmar", "volatility", "max_drawdown"):
            assert key in data["metrics"]
            assert data["metrics"][key] is not None
        assert "beta_vs_nifty" in data["relative_vs_nifty"]
        assert data["holdings"].keys() == {"AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_no_positions_404(self, async_client, patch_market):
        ctx1, ctx2 = patch_market(bench_returns=_bench_series())
        with ctx1, ctx2:
            resp = await async_client.get("/api/v1/analytics/tear-sheet")
        assert resp.status_code == 404


@pytest.mark.api
class TestRiskContribution:
    @pytest.mark.asyncio
    async def test_contributions_sum_to_one_and_ranking(self, async_client, seeded_positions, patch_market):
        # MSFT gets 3x AAPL's volatility -> should dominate vol contribution
        frames = {"AAPL": _frame(seed=1, vol=0.010), "MSFT": _frame(seed=2, vol=0.030)}
        ctx1, ctx2 = patch_market(frames=frames)
        with ctx1, ctx2:
            resp = await async_client.get("/api/v1/analytics/risk-contribution")
        assert resp.status_code == 200, resp.text
        data = resp.json()["positions"]
        vol_rc = data["volatility"]
        assert abs(sum(vol_rc.values()) - 1.0) < 1e-4
        assert vol_rc["MSFT"] > vol_rc["AAPL"]

        cvar_rc = data["cvar_tail"]
        assert abs(sum(cvar_rc.values()) - 1.0) < 1e-6 or cvar_rc == {}

    @pytest.mark.asyncio
    async def test_sector_rollup_present(self, async_client, seeded_positions, patch_market):
        frames = {"AAPL": _frame(seed=1), "MSFT": _frame(seed=2)}
        ctx1, ctx2 = patch_market(frames=frames)
        with ctx1, ctx2:
            resp = await async_client.get("/api/v1/analytics/risk-contribution")
        rollup = resp.json()["sector_rollup"]["volatility"]
        assert rollup == {"Technology": 1.0}


@pytest.mark.api
class TestOptimizerEndpoint:
    @pytest.mark.asyncio
    async def test_hrp_explicit_universe(self, async_client, seeded_positions, patch_market):
        frames = {"RELIANCE.NS": _frame(seed=1), "TCS.NS": _frame(seed=2), "INFY.NS": _frame(seed=3)}
        ctx1, ctx2 = patch_market(frames=frames)
        with ctx1, ctx2:
            resp = await async_client.post(
                "/api/v1/analytics/optimize/run",
                json={"strategy": "hrp", "tickers": ["RELIANCE.NS", "TCS.NS", "INFY.NS"]},
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert set(data["weights"].keys()) == {"RELIANCE.NS", "TCS.NS", "INFY.NS"}
        # 6dp weight rounding leaves up to N*5e-7 residual; project
        # convention (CONTEXT gotcha #5) is ~1e-4, not 1e-6.
        assert abs(sum(data["weights"].values()) - 1.0) < 1e-4
        assert "trades_required" in data

    @pytest.mark.asyncio
    async def test_unknown_strategy_400(self, async_client, seeded_positions, patch_market):
        frames = {"AAPL": _frame(seed=1), "MSFT": _frame(seed=2)}
        ctx1, ctx2 = patch_market(frames=frames)
        with ctx1, ctx2:
            resp = await async_client.post(
                "/api/v1/analytics/optimize/run", json={"strategy": "moon_math"}
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_all_four_strategies(self, async_client, seeded_positions, patch_market):
        frames = {"AAPL": _frame(seed=1), "MSFT": _frame(seed=2)}
        for strategy in ("hrp", "min_vol", "max_sharpe", "min_cvar"):
            ctx1, ctx2 = patch_market(frames=frames)
            with ctx1, ctx2:
                resp = await async_client.post(
                    "/api/v1/analytics/optimize/run", json={"strategy": strategy}
                )
            assert resp.status_code == 200, f"{strategy}: {resp.text}"
            assert abs(sum(resp.json()["weights"].values()) - 1.0) < 1e-6


@pytest.mark.api
class TestRegime:
    @pytest.mark.asyncio
    async def test_labels_and_stability(self, async_client, patch_market):
        ctx1, ctx2 = patch_market(bench_returns=_bench_series(days=500))
        with ctx1, ctx2:
            resp = await async_client.get("/api/v1/analytics/regime?with_portfolio=false")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["current_regime"] in {"calm", "volatile", "crisis", "bull"}
        assert 0 <= data["stability_pct"] <= 100
        assert len(data["states"]) == 3
        labels = {s["regime"] for s in data["states"]}
        assert labels.issubset({"calm", "volatile", "crisis", "bull"}) and len(labels) == 3
        # worst regime must actually have the worst composite profile
        by_label = {s["regime"]: s for s in data["states"]}
        assert (
            by_label["crisis"]["ann_ret"] - 0.5 * by_label["crisis"]["ann_vol"]
            <= by_label["calm"]["ann_ret"] - 0.5 * by_label["calm"]["ann_vol"]
        )

    @pytest.mark.asyncio
    async def test_insufficient_history_409(self, async_client):
        # regime_service imports its own BenchmarkService - patch THERE
        with patch("app.services.regime_service.BenchmarkService") as rb:
            rb.return_value.get_benchmark_df = AsyncMock(return_value=None)
            rb.return_value.get_returns = AsyncMock(return_value=_bench_series(days=50))
            resp = await async_client.get("/api/v1/analytics/regime?with_portfolio=false")
        assert resp.status_code == 409
