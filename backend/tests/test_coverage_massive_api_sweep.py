"""
Massive API branch coverage sweep to push backend coverage well past 80%.
"""

from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime
import zlib
import pandas as pd
import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete

from app.models.database import PortfolioPosition


#: Per-step mean and sigma of the sampled price walk. Sigma is the fixture's
#: original 10 on a 2800 price (~5.7% annualized); the MEAN is what changed,
#: and why, is in `_sample_ohlcv`.
_STEP_SIGMA = 10.0
_STEP_MEAN = 3.0


def _sample_ohlcv(days=300, ticker="RELIANCE.NS"):
    """Sampled price walk with a POSITIVE expected return, seeded per ticker.

    This file asserts `/optimize/run` returns 200 for `max_sharpe`, and
    `_max_sharpe` refuses by design when no leg beats the risk-free rate:
    `(excess <= 0).all()` raises ValueError
    (app/services/optimization_service.py:968), which the route turns into a
    400 "Invalid analytics request" (app/api/analytics.py:10675). That guard
    is correct -- there is no tangency portfolio when nothing has excess
    return -- so the fixture is what has to give.

    It used to step with mean 0, i.e. assets whose expected return is ~0%
    against a 2% risk-free rate, while the sample mean of 300 daily returns
    has a standard error of 252 * (10/2800) / sqrt(300) = 5.2% annualized --
    2.6x the risk-free rate itself. So `mu = returns.mean() * 252`
    (optimization_service.py:88) landed under the rf for ALL THREE legs on
    roughly a quarter of draws, and the route correctly answered 400. A
    zero-expectation universe is not a universe with a tangency portfolio; the
    old fixture asserted one existed.

    Step mean 3.0 puts every leg's realized `mu` at 0.23-0.27 annualized --
    over four standard errors ABOVE the rf, not merely on the lucky side of it
    -- and holds for every ticker at any step mean from 1.0 up, so this is a
    corrected premise rather than a lucky draw.

    The RNG is seeded off the ticker with `zlib.crc32`, as conftest.py:535
    does, instead of `np.random.normal` off the global stream: the drift fixes
    the premise, the seed makes the fixture reproducible. Both halves are
    needed. Seeding alone would only freeze whichever side of the rf a draw
    happened to land on. Distinct legs must keep distinct seeds -- two legs on
    one seed would make the sample covariance exactly singular and trade this
    flake for a worse one.
    """
    dates = pd.date_range("2024-01-01", periods=days, freq="B")
    rng = np.random.default_rng(zlib.crc32(ticker.encode()) % 2**32)
    close = 2800.0 + np.cumsum(rng.normal(_STEP_MEAN, _STEP_SIGMA, days))
    return pd.DataFrame({
        "date": dates,
        "open": close * 0.99,
        "high": close * 1.01,
        "low": close * 0.98,
        "close": close,
        "adj_close": close,
        "Volume": np.full(days, 300000.0),
        "volume": np.full(days, 300000.0),
        "ticker": ticker
    })


@pytest.mark.api
class TestMassiveAPISweep:
    @pytest.mark.asyncio
    async def test_full_analytics_and_portfolio_sweep(self, async_client, test_db: AsyncSession):
        # Seed 3 positions
        p1 = PortfolioPosition(ticker="RELIANCE.NS", quantity=20.0, buy_price=2700.0, last_price=2800.0, market_value=56000.0, weight=0.5, region="IN", sector="Energy")
        p2 = PortfolioPosition(ticker="INFY.NS", quantity=30.0, buy_price=1500.0, last_price=1600.0, market_value=48000.0, weight=0.3, region="IN", sector="Technology")
        p3 = PortfolioPosition(ticker="TCS.NS", quantity=10.0, buy_price=3300.0, last_price=3400.0, market_value=34000.0, weight=0.2, region="IN", sector="Technology")
        test_db.add_all([p1, p2, p3])
        await test_db.commit()

        df_rel = _sample_ohlcv(300, "RELIANCE.NS")
        df_infy = _sample_ohlcv(300, "INFY.NS")
        df_tcs = _sample_ohlcv(300, "TCS.NS")

        mock_ds = Mock()
        async def _fetch(ticker, start, end, force_refresh=False):
            if "RELIANCE" in ticker: return df_rel
            if "INFY" in ticker: return df_infy
            return df_tcs
        mock_ds.fetch_historical_data = AsyncMock(side_effect=_fetch)
        mock_ds.validate_ticker = AsyncMock(return_value=True)
        mock_ds.fetch_quote = AsyncMock(return_value={
            "ticker": "RELIANCE.NS", "current_price": 2800.0, "open_price": 2790.0,
            "high_price": 2820.0, "low_price": 2780.0, "previous_close": 2795.0,
            "change": 5.0, "change_percent": 0.18, "volume": 300000,
            "market_cap": 1800000000000.0, "timestamp": datetime.utcnow(),
            "sector": "Energy", "industry": "Oil & Gas"
        })

        try:
            with patch("app.api.analytics.GlobalDataService") as mock_gds,                  patch("app.api.portfolio.GlobalDataService") as mock_port_gds,                  patch("app.api.analytics.BenchmarkService") as mock_bs, \
                 patch("app.services.regime_service.BenchmarkService") as mock_rs_bs:
                
                mock_gds.return_value.get_service.return_value = mock_ds
                mock_port_gds.return_value.get_service.return_value = mock_ds
                mock_bs.return_value.get_returns = AsyncMock(
                    return_value=pd.Series(np.random.normal(0.0005, 0.01, 300), index=df_rel["date"])
                )
                # detect_regime builds its OWN BenchmarkService inside
                # app.services.regime_service, so the analytics-namespace patch
                # never reaches it and /regime fetched ^NSEI from the live
                # vendor (3x, via the DataService retry loop) -> 409 on a
                # vendor miss. Both seams must be mocked, as
                # test_advanced_analytics.patch_market does.
                mock_rs_bs.return_value.get_benchmark_df = AsyncMock(return_value=None)
                mock_rs_bs.return_value.get_returns = AsyncMock(
                    return_value=pd.Series(
                        np.random.normal(0.0005, 0.01, 300),
                        index=pd.date_range("2025-01-01", periods=300, freq="B"),
                    )
                )

                # Sweep all analytics endpoints
                endpoints = [
                    "/api/v1/analytics/summary",
                    "/api/v1/analytics/realized-risk?lookback_days=60",
                    "/api/v1/analytics/forecast-risk?model=GARCH&horizon=5",
                    "/api/v1/analytics/forecast-risk?model=EWMA&horizon=10",
                    "/api/v1/analytics/factor-exposure",
                    "/api/v1/analytics/concentration",
                    "/api/v1/analytics/liquidity",
                    "/api/v1/analytics/volatility-sizing?target_volatility=0.15",
                    "/api/v1/analytics/risk-score",
                    "/api/v1/analytics/performance-history?timeframe=3M",
                    "/api/v1/analytics/tear-sheet",
                    "/api/v1/analytics/regime",
                    "/api/v1/analytics/vol-cone?symbol=RELIANCE.NS&horizon=21&model=GARCH",
                    "/api/v1/analytics/tail-risk?tickers=RELIANCE.NS,INFY.NS",
                    "/api/v1/analytics/coint?tickers=RELIANCE.NS,INFY.NS,TCS.NS&lookback_days=180",
                    "/api/v1/analytics/correlation-stability?tickers=RELIANCE.NS,INFY.NS,TCS.NS&window_days=60"
                ]

                for ep in endpoints:
                    res = await async_client.get(ep)
                    assert res.status_code in [200, 404]

                # Monte Carlo post
                res_mc = await async_client.post("/api/v1/analytics/monte-carlo", json={
                    "initial_value": 138000.0,
                    "target_value": 200000.0,
                    "horizon_years": 2,
                    "method": "bootstrap",
                    "num_paths": 100
                })
                assert res_mc.status_code == 200

                # Stress test post
                res_st = await async_client.post("/api/v1/analytics/stress-test", json={
                    "scenario": "demonetization_2016"
                })
                assert res_st.status_code == 200

                # Optimize post
                for strat in ["max_sharpe", "min_vol", "min_cvar", "hrp"]:
                    res_opt = await async_client.post("/api/v1/analytics/optimize/run", json={"strategy": strat})
                    assert res_opt.status_code == 200

                # Portfolio CRUD sweep
                res_pos = await async_client.get("/api/v1/portfolio/RELIANCE.NS")
                assert res_pos.status_code == 200

                res_csv = await async_client.get("/api/v1/portfolio/export/csv")
                assert res_csv.status_code == 200

                res_norm = await async_client.post("/api/v1/portfolio/normalize")
                assert res_norm.status_code == 200

        finally:
            await test_db.execute(delete(PortfolioPosition))
            await test_db.commit()
