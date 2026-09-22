"""Regression tests for backend-audit report 03 (core services).

One permanent gate per confirmed finding whose fix needed a test:
factor-exposure placeholder overwrite (both triggers), fabricated empty
payloads, zero-weight metrics, empty-forecast model label, unnormalizable-
frame cascade bypass, partial-history perpetual refetch, stress-scenario
matching/parsing, event-loop blocking arch/yfinance calls, quote memo, and
the scoped warnings filter.

Fixes already gated elsewhere stay there: is_indian canonical ticker
(test_coverage_data_service), exception-path canonical ticker (same file),
cache UNIQUE upsert (test_p08_cache), beta genuine-0%-day mask
(test_quant_math_p1_batch), enshrine-the-fabrication assertion
(test_analytics_engine).
"""

import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import StockTimeseries
from app.services.analytics_engine import AnalyticsEngine
from app.services.data_service import DataService


@pytest.fixture(autouse=True)
def _clear_memo_caches():
    DataService._in_memory_df_cache.clear()
    DataService._quote_memo.clear()
    yield
    DataService._in_memory_df_cache.clear()
    DataService._quote_memo.clear()


async def _progress_during(work_factory, *, tick=0.005):
    """Sentinel ticks observed before ``work_factory()`` finishes.

    Work that blocks the event loop yields ~0 (the sentinel cannot run while
    the loop is stuck in a synchronous sleep); work offloaded via
    ``asyncio.to_thread`` leaves the loop free, so a 300ms in-thread sleep
    produces ~60 ticks (fewer under coverage). Threshold 3 separates the
    two: blocked work yields ~0, any offloaded work clears 3.
    """
    progress = 0
    done = False

    async def sentinel():
        nonlocal progress
        while not done:
            await asyncio.sleep(tick)
            progress += 1

    async def runner():
        nonlocal done
        out = await work_factory()
        snap = progress
        done = True
        return out, snap

    sent = asyncio.create_task(sentinel())
    try:
        out, snap = await runner()
    finally:
        done = True
        await sent
    return out, snap


@pytest.mark.asyncio
class TestFactorExposurePlaceholders:
    async def test_missing_benchmark_returns_nulls_not_market_one(
        self, mock_price_dataframe
    ):
        """P1: no benchmark -> market None + error, never {alpha:0, market:1}."""
        engine = AnalyticsEngine()
        res = await engine.factor_exposure_analysis(mock_price_dataframe)

        assert res["portfolio"]["market"] is None
        assert res["portfolio"]["alpha"] is None
        assert res["r_squared"] is None
        assert "error" in res
        assert res["positions"]
        for pos in res["positions"].values():
            assert pos["market"] is None
            assert pos["alpha"] is None
            assert "error" in pos

    async def test_portfolio_failure_keeps_valid_position_results(
        self, mock_price_dataframe
    ):
        """P1: portfolio leg unavailable -> portfolio nulled, positions kept."""
        engine = AnalyticsEngine()
        dates = mock_price_dataframe.index
        bench = pd.Series(
            np.random.default_rng(3).normal(0.0005, 0.01, len(dates)),
            index=dates,
        )
        with patch.object(
            AnalyticsEngine,
            "_calculate_portfolio_returns",
            return_value=pd.Series(dtype=float),
        ):
            res = await engine.factor_exposure_analysis(
                mock_price_dataframe, benchmark_data=bench
            )

        assert res["portfolio"]["market"] is None
        assert res["r_squared"] is None
        assert "error" in res
        # Valid per-position regressions must survive the portfolio-leg failure
        for pos in res["positions"].values():
            assert pos["market"] is not None
            assert "error" not in pos
            assert pos["data_points"] >= 10


@pytest.mark.asyncio
class TestFabricatedValueContracts:
    async def test_zero_weight_portfolio_error_flagged_nulls(
        self, mock_price_dataframe
    ):
        """P2: all-zero weights must not yield success-flagged Sharpe/Sortino."""
        engine = AnalyticsEngine()
        weights = {c: 0.0 for c in mock_price_dataframe.columns}
        res = await engine.calculate_portfolio_metrics(mock_price_dataframe, weights)

        assert "error" in res
        assert res["sharpe_ratio"] is None
        assert res["sortino_ratio"] is None
        assert res["annual_volatility"] is None
        assert res["hit_ratio"] is None

    async def test_empty_forecast_echoes_requested_model(self):
        """P2: a failed EGARCH request must not be labeled GARCH."""
        engine = AnalyticsEngine()
        short = pd.Series([0.01, -0.02, 0.03])
        res = await engine.forecast_volatility(short, model="EGARCH")

        assert "error" in res
        assert res["model"] == "EGARCH"
        assert res["volatility_forecast"] is None

        res_g = await engine.forecast_volatility(short, model="GARCH")
        assert res_g["model"] == "GARCH"

    async def test_empty_payloads_are_null_not_fabricated(self):
        """P2: _empty_* helpers return None + error, never invented numbers."""
        engine = AnalyticsEngine()

        m = engine._empty_metrics()
        assert m["error"]
        assert m["annual_volatility"] is None
        assert m["hit_ratio"] is None
        assert m["kurtosis"] is None
        assert m["sharpe_ratio"] is None

        s = engine._empty_stress_test()
        assert s["error"]
        assert s["max_drawdown"] is None
        assert s["portfolio_impact"] is None
        assert s["recovery_time"] is None

        r = engine._empty_risk_score()
        assert r["error"]
        assert r["overall_score"] is None
        assert r["risk_level"] is None
        assert all(v is None for v in r["components"].values())

        # End-to-end empty inputs hit the same contract
        rr = await engine.risk_scoring(pd.DataFrame(), {})
        assert rr["error"] and rr["overall_score"] is None
        mm = await engine.calculate_portfolio_metrics(pd.DataFrame(), {"A": 1.0})
        assert mm["error"] and mm["annual_volatility"] is None


@pytest.mark.asyncio
class TestStressScenarioMatching:
    async def test_empty_scenario_does_not_match_market_crash(
        self, mock_price_dataframe, sample_portfolio_weights
    ):
        """P3: scenario="" must fall to the custom branch, not market_crash."""
        engine = AnalyticsEngine()
        res = await engine.stress_test(
            mock_price_dataframe, sample_portfolio_weights, scenario=""
        )

        assert res["scenario_description"] == "Custom Scenario Shock"
        assert "Global Financial Crisis" not in str(res.get("scenario_description"))

    async def test_custom_scenario_parses_signed_percent(
        self, mock_price_dataframe, sample_portfolio_weights
    ):
        """P3: "crash -10%" parses -10%, not the fixed -20% default."""
        engine = AnalyticsEngine()
        res = await engine.stress_test(
            mock_price_dataframe, sample_portfolio_weights, scenario="crash -10%"
        )

        assert res["scenario_description"] == "crash -10%"
        # -10% scaled by bounded vol/sector factors stays near -10%;
        # the old -20% default lands outside this window.
        assert -0.14 <= res["portfolio_impact"] <= -0.08


@pytest.mark.asyncio
class TestOffEventLoopWork:
    async def test_garch_fit_runs_off_event_loop(self):
        """P2 opt: arch model.fit must not block the event loop."""
        engine = AnalyticsEngine()
        fitted = MagicMock()
        fcast = MagicMock()
        fcast.variance.values = np.array([[0.04]])
        fitted.forecast.return_value = fcast

        model = MagicMock()

        def _slow_fit(*_a, **_k):
            time.sleep(0.3)
            return fitted

        model.fit.side_effect = _slow_fit
        returns = pd.Series(
            np.random.default_rng(1).normal(0, 0.01, 100),
            index=pd.bdate_range("2024-01-01", periods=100),
        )

        with patch(
            "app.services.analytics_engine.arch_model", return_value=model
        ):
            res, ticks = await _progress_during(
                lambda: engine.forecast_volatility(returns, model="GARCH", horizon=1)
            )

        assert "error" not in res, res
        assert res["model"] == "GARCH"
        assert ticks >= 3, f"event loop stalled during fit ({ticks} sentinel ticks)"

    async def test_validate_ticker_history_runs_off_event_loop(
        self, test_db: AsyncSession
    ):
        """P2: yfinance stock.history in validate_ticker must not block the loop."""
        service = DataService(test_db)
        fake = MagicMock()

        def _slow_history(*_a, **_k):
            time.sleep(0.3)
            return pd.DataFrame({"Close": [100.0]})

        fake.history.side_effect = _slow_history

        with patch("yfinance.Ticker", return_value=fake):
            valid, ticks = await _progress_during(
                lambda: service.validate_ticker("RELIANCE")
            )

        assert valid is True
        assert ticks >= 3, f"event loop stalled in history() ({ticks} sentinel ticks)"

    async def test_validate_ticker_identity_skips_real_bfinance(
        self, test_db: AsyncSession
    ):
        """P2: a yf-only mock must never reach the REAL bfinance tier.

        validate_ticker now carries the same module-load identity skip as
        fetch_quote/_download_with_timeout: default source order puts
        bfinance first, so without the skip this unit test would open a
        live network call via bfinance.Ticker.
        """
        service = DataService(test_db)

        bf_calls = []

        def _bf_spy(symbol):
            bf_calls.append(symbol)
            raise AssertionError("real bfinance.Ticker must not be constructed")

        class _FakeYf:
            def __init__(self, symbol):
                self.symbol = symbol

            def history(self, period=None):
                return pd.DataFrame({"Close": [100.0]})

        import bfinance as bf_mod

        # Install the spy as bfinance.Ticker AND as the identity original so
        # is_bf_mocked stays False (guard must treat bfinance as unpatched)
        # while construction remains observable.
        with patch.object(bf_mod, "Ticker", _bf_spy), \
             patch.object(DataService, "_BF_TICKER_REAL", staticmethod(_bf_spy)), \
             patch("yfinance.Ticker", _FakeYf):
            valid = await service.validate_ticker("RELIANCE")

        assert valid is True
        assert bf_calls == [], "bfinance.Ticker constructed despite yf-only mock"

    async def test_corporate_actions_runs_off_event_loop(
        self, test_db: AsyncSession
    ):
        """P2: yfinance splits/dividends access must not block the loop."""
        service = DataService(test_db)

        class _SlowTicker:
            @property
            def splits(self):
                time.sleep(0.15)
                return pd.Series([2.0], index=[pd.Timestamp("2024-01-01")])

            @property
            def dividends(self):
                time.sleep(0.15)
                return pd.Series([10.0], index=[pd.Timestamp("2024-06-01")])

        with patch("yfinance.Ticker", return_value=_SlowTicker()):
            actions, ticks = await _progress_during(
                lambda: service.get_corporate_actions("TCS.NS")
            )

        assert actions["ticker"] == "TCS.NS"
        assert len(actions["splits"]) == 1
        assert ticks >= 3, f"event loop stalled in splits/dividends ({ticks} ticks)"


@pytest.mark.asyncio
class TestDataCascadeAndCache:
    async def test_unnormalizable_frame_still_reaches_alpha_vantage(
        self, test_db: AsyncSession
    ):
        """P2: a frame missing Adj Close must consume retries, not abort the
        3-tier cascade before the Alpha Vantage tier runs."""
        service = DataService(test_db)
        bad = pd.DataFrame(
            {"Open": [100.0, 101.0], "Close": [104.0, 105.0]},
            index=pd.to_datetime(["2025-01-01", "2025-01-02"]),
        )
        bad.index.name = "Date"
        good = pd.DataFrame(
            {
                "date": pd.date_range("2025-01-01", periods=3, freq="B"),
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.5, 101.5, 102.5],
                "adj_close": [100.5, 101.5, 102.5],
                "volume": [1000, 1100, 1200],
                "ticker": "NOADJ.NS",
            }
        )

        with patch.object(
            service, "_download_with_timeout", new=AsyncMock(return_value=bad)
        ) as dl, patch.object(
            service,
            "_fetch_from_alpha_vantage",
            new=AsyncMock(return_value=good),
        ) as av:
            df = await service.fetch_historical_data(
                "NOADJ.NS", "2025-01-01", "2025-01-03"
            )

        assert dl.await_count == 3, "all retries must run after an empty normalize"
        av.assert_awaited_once()
        assert df is not None and not df.empty

    async def test_partial_history_start_gap_served_after_backfill_marker(
        self, test_db: AsyncSession
    ):
        """P2: IPO/new-ETF start gap >30d + aged fetched_on must still be a
        cache hit once the deep-backfill marker exists (no perpetual refetch)."""
        service = DataService(test_db)
        ticker = "IPOGAP.NS"
        # Real history starts 60 days after the requested start (2023-01-01)
        dates = pd.bdate_range("2023-03-02", "2024-06-28")
        await service._store_timeseries_data(
            ticker,
            pd.DataFrame(
                {
                    "date": dates,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "adj_close": 100.0,
                    "volume": 1000,
                    "ticker": ticker,
                }
            ),
        )
        await service._set_backfill_marker(ticker)
        # Age every row past the 1-hour wall-clock grace
        await test_db.execute(
            update(StockTimeseries)
            .where(StockTimeseries.ticker == ticker)
            .values(fetched_on=datetime.utcnow() - timedelta(hours=2))
        )
        await test_db.commit()
        DataService._in_memory_df_cache.clear()

        vendor = AsyncMock(return_value=None)
        with patch.object(service, "_download_with_timeout", new=vendor):
            df = await service.fetch_historical_data(
                ticker, "2023-01-01", "2024-06-28"
            )

        assert vendor.await_count == 0, "backfill marker must stop the refetch loop"
        assert df is not None and not df.empty
        assert pd.to_datetime(df["date"]).min() >= pd.to_datetime("2023-03-02")


@pytest.mark.asyncio
class TestQuoteMemoAndWarningFilter:
    async def test_quote_memo_serves_repeat_within_ttl(self, test_db: AsyncSession):
        """P3 opt: two quote calls inside the TTL hit the vendor once."""
        service = DataService(test_db)
        mock_stock = MagicMock()
        mock_stock.info = {}
        mock_stock.fast_info = {}
        mock_stock.history.return_value = pd.DataFrame(
            {"Close": [1590.0, 1600.0], "Volume": [500000, 600000]},
            index=pd.to_datetime(["2025-01-01", "2025-01-02"]),
        )

        with patch("yfinance.Ticker", return_value=mock_stock) as yf_ticker:
            q1 = await service.fetch_quote("MEMOTEST.NS")
            q2 = await service.fetch_quote("MEMOTEST.NS")

        assert q1 is not None and q1["current_price"] == 1600.0
        assert q2 == q1
        assert yf_ticker.call_count == 1, "second call must be served from the memo"

    def test_warning_filter_is_scoped_not_bare_ignore(self):
        """P2 improvement: module import must not install a process-wide
        warnings ignore-all entry (scope = ConvergenceWarning only)."""
        from app.services import analytics_engine as ae

        assert ae.ConvergenceWarning is not None
        bare = [
            f
            for f in __import__("warnings").filters
            if f[0] == "ignore" and f[1] is None and f[2] is None
        ]
        assert bare == [], f"process-wide ignore-all filters installed: {bare}"
