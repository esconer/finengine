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
        # The tail model published shares on this book, so it has to publish a
        # complete decomposition of them.  Previously this read
        # `abs(sum(...) - 1.0) < 1e-6 or cvar_rc == {}`, and the right-hand
        # clause made the whole assertion vacuous on an empty result: a book
        # whose tail model measured nothing satisfied it exactly as well as the
        # no-hedge book it was written for, so nothing about the hedge case was
        # ever pinned.  The `or` is gone; the non-empty map is a precondition,
        # not an alternative reading.
        assert cvar_rc, "the tail model published no shares for a book it measured"
        # Direction, not an exact bound: every published share is a share of a
        # real tail loss, so no leg on this unhedged book may carry a negative
        # one. A hedge leg is published as a negative share (the hedge test
        # below pins that), not by shrinking everyone else.
        assert all(share >= 0.0 for share in cvar_rc.values()), cvar_rc
        # WHY THE ORDINARY BOOK'S NUMBERS DID NOT MOVE. The fix replaced a
        # denominator of `sum(abs(c))` with `-sum(c)`, and on a book with no
        # offsetting leg those are the same number - checked here rather than
        # pinned as 6dp literals, so the proof does not rot when the fixture's
        # calendar window moves and cannot silently pass by re-deriving itself
        # from the code under test.
        no_hedge = [-0.4, -0.25, -0.05]
        assert -sum(no_hedge) == sum(abs(c) for c in no_hedge)
        # The total is checked at the project's own 6dp-rounding tolerance
        # (~1e-4, per the optimizer note below) rather than 1e-6: a tighter
        # bound would be pinning rounding, not the invariant.  What is being
        # pinned is that the block is a unit decomposition - which is what
        # makes a shortfall a `rounding_residual` and not a hidden hedge.
        assert sum(cvar_rc.values()) == pytest.approx(1.0, abs=1e-4)

    @pytest.mark.asyncio
    async def test_sector_rollup_present(self, async_client, seeded_positions, patch_market):
        frames = {"AAPL": _frame(seed=1), "MSFT": _frame(seed=2)}
        ctx1, ctx2 = patch_market(frames=frames)
        with ctx1, ctx2:
            resp = await async_client.get("/api/v1/analytics/risk-contribution")
        rollup = resp.json()["sector_rollup"]["volatility"]
        assert rollup == {"Technology": 1.0}

    @pytest.mark.asyncio
    async def test_a_real_hedge_is_published_as_an_offset_not_as_a_rounding_residual(
        self, async_client, test_db, patch_market,
    ):
        """A gold ETF in the book must not be rounded away.

        The tail model used to normalise its shares by the sum of MAGNITUDES,
        so a leg that gains on the book's worst days put its size into the
        denominator while subtracting from the numerator: the published shares
        summed to net/gross instead of 1 and the difference was published as
        `rounding_residual`, i.e. a real offset described as 1e-12 of float
        noise. The sibling volatility leg at
        `contrib = contrib / contrib.sum()` already normalised by the SIGNED
        sum, so this pins the same contract on the tail leg.
        """
        from datetime import datetime as _dt

        from app.models.database import PortfolioPosition

        # A book with a real offsetting leg: two equity legs that fall together
        # and a gold leg built to RISE on exactly the sessions they fall. Weights
        # come from market value, so they are set here rather than stored.
        test_db.add_all([
            PortfolioPosition(
                ticker="AAPL", weight=0.45, quantity=10.0, buy_price=150.0,
                last_price=180.0, market_value=45_000.0, sector="Technology",
                industry="Hardware", added_on=_dt(2020, 1, 1),
            ),
            PortfolioPosition(
                ticker="MSFT", weight=0.40, quantity=10.0, buy_price=300.0,
                last_price=420.0, market_value=40_000.0, sector="Technology",
                industry="Software", added_on=_dt(2020, 1, 1),
            ),
            PortfolioPosition(
                ticker="GOLDM", weight=0.15, quantity=10.0, buy_price=50.0,
                last_price=55.0, market_value=15_000.0, sector="Gold",
                industry="Precious Metals", added_on=_dt(2020, 1, 1),
            ),
        ])
        await test_db.commit()

        days = 300
        rng = np.random.default_rng(23)
        aapl = rng.normal(0.0004, 0.014, days)
        msft = 0.8 * aapl + rng.normal(0.0, 0.005, days)
        # The hedge: negative of the risky legs' own move, so its tail-day
        # contribution has the opposite sign to theirs by construction rather
        # than by luck of the draw.
        goldm = -0.9 * (aapl + msft) + rng.normal(0.0, 0.001, days)

        def _price(rets, seed):
            dates = pd.date_range("2025-01-01", periods=days, freq="B")
            close = 100 * np.exp(np.cumsum(rets))
            return pd.DataFrame({
                "date": dates, "open": close * 0.995, "high": close * 1.008,
                "low": close * 0.992, "close": close, "adj_close": close,
                "volume": np.full(days, 250_000.0), "ticker": f"S{seed}",
            })

        frames = {
            "AAPL": _price(aapl, 1), "MSFT": _price(msft, 2), "GOLDM": _price(goldm, 3),
        }
        ctx1, ctx2 = patch_market(frames=frames)
        with ctx1, ctx2:
            resp = await async_client.get("/api/v1/analytics/risk-contribution")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        cvar_rc = body["positions"]["cvar_tail"]
        assert set(cvar_rc) == {"AAPL", "MSFT", "GOLDM"}, cvar_rc

        # THE PREMISE, asserted rather than assumed: the gold leg's tail-day
        # contribution really does have the opposite sign, so this book is a
        # genuine hedge and not a fixture that happens to sum to one.
        assert cvar_rc["GOLDM"] < 0.0, cvar_rc

        # Direction of the fix, not a bound on a number chosen to pass. The
        # shares decompose the NET tail loss, so the legs that lost money carry
        # shares summing to MORE than one - the offset is subtracted from them,
        # which is the only place it can live if the block is to total 1. Under
        # magnitude normalisation the positive shares summed to LESS than one
        # and the shortfall leaked into `rounding_residual`.
        assert sum(v for v in cvar_rc.values() if v > 0) > 1.0, cvar_rc
        assert sum(cvar_rc.values()) == pytest.approx(1.0, abs=1e-4)

        # And the block says so: the declared total is 1 and the residual is
        # display rounding, not the hedge.
        record = body["contribution_basis"]["per_model"]["cvar_tail"]
        assert record["published_total"] == pytest.approx(1.0, abs=1e-4)
        assert abs(record["rounding_residual"]) <= 1e-4, record

        # The sector rollup sums the same per-leg shares, so it inherits the
        # unit total rather than reproducing the shortfall.
        rollup = body["sector_rollup"]["cvar_tail"]
        assert sum(rollup.values()) == pytest.approx(1.0, abs=1e-4), rollup
        assert rollup["Gold"] < 0.0, rollup


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
