"""API-layer fix regressions (audit 01-api-analytics + 02-api-rest-main).

One gate per nontrivial fix: _q non-finite, resolve_allocation portfolio
sentinel, single-holding optimize never fabricates metrics, factor-exposure
error payload nulls, concentration by_sector from MV weights, ad-hoc
liquidity mode, tails cache clear hook, performance-history qty<=0 exclusion,
benchmark rebase parity, tear-sheet benchmark best-effort, summary risk_score
benchmark kwarg, health environment field, production middleware gate,
config PUT empty / config GET 500, data source/from_cache, and str(e) leak
on equity-research 500s.
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import resolve_allocation, _q
from app.api import analytics as analytics_mod
from app.api import data as data_mod
from app.api import equity_research as er_mod
from app.models.database import PortfolioPosition

BACKEND_DIR = Path(__file__).resolve().parent.parent


# --- report 01: _q + resolve_allocation sentinel ----------------------------


def test_q_metric_guard_non_finite():
    assert _q(lambda: float("nan")) is None
    assert _q(lambda: float("inf")) is None
    assert _q(lambda: 1.25) == 1.25


@pytest.mark.asyncio
async def test_resolve_allocation_portfolio_sentinel(test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    with pytest.raises(ValueError):
        await resolve_allocation("portfolio", test_db)

    test_db.add(PortfolioPosition(
        ticker="TCS.NS", weight=1.0, quantity=1.0, buy_price=100.0,
        last_price=100.0, market_value=100.0,
    ))
    await test_db.commit()

    for param in ("portfolio", "Portfolio"):
        tickers, weights = await resolve_allocation(param, test_db)
        assert tickers == ["TCS.NS"]
        assert weights["TCS.NS"] == 1.0

    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()


# --- report 01: single-holding optimize (P1 fabricated metrics) ------------


@pytest.mark.api
@pytest.mark.asyncio
async def test_optimize_single_holding_never_fabricates_metrics(
    async_client, test_db: AsyncSession
):
    mock_ds = Mock()
    mock_ds.fetch_historical_data = AsyncMock(return_value=None)
    analytics_mod_overrides = {analytics_mod.get_data_service: lambda: mock_ds}
    from main import app
    app.dependency_overrides.update(analytics_mod_overrides)
    try:
        resp = await async_client.post(
            "/api/v1/analytics/optimize/run",
            params={"tickers": "ONLYONE.NS"},
            json={"strategy": "hrp"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["solver"] == "single-holding"
        # Previously hardcoded 0.12 / 0.22 / 0.45 — must be None when
        # history is unavailable (metric-hygiene invariant).
        assert data["expected_annual_return"] is None
        assert data["expected_annual_volatility"] is None
        assert data["expected_sharpe"] is None
    finally:
        for key in analytics_mod_overrides:
            app.dependency_overrides.pop(key, None)


# --- report 01: factor-exposure error payload nulls -------------------------


@pytest.mark.api
@pytest.mark.asyncio
async def test_factor_exposure_error_payload_nulls(async_client, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    resp = await async_client.get("/api/v1/analytics/factor-exposure")
    assert resp.status_code == 200
    data = resp.json()
    assert data["portfolio"]["alpha"] is None
    assert data["portfolio"]["market"] is None
    assert "error" in data


# --- report 01: concentration by_sector from market-value weights ----------


@pytest.mark.api
@pytest.mark.asyncio
async def test_concentration_by_sector_uses_mv_weights(async_client, test_db: AsyncSession):
    await test_db.execute(delete(PortfolioPosition))
    # Stored weights claim Tech-dominant; market values say Energy-dominant.
    test_db.add_all([
        PortfolioPosition(
            ticker="TCS.NS", weight=0.9, quantity=1.0, buy_price=100.0,
            last_price=100.0, market_value=100.0, sector="Technology",
        ),
        PortfolioPosition(
            ticker="ONGC.NS", weight=0.1, quantity=1.0, buy_price=100.0,
            last_price=900.0, market_value=900.0, sector="Energy",
        ),
    ])
    await test_db.commit()

    mock_engine = Mock()

    async def fake_concentration(weights):
        return {
            "largest_position": max(weights.values()),
            "by_weight": dict(weights),
            "herfindahl_index": sum(w * w for w in weights.values()),
        }

    mock_engine.concentration_analysis = AsyncMock(side_effect=fake_concentration)

    from main import app
    app.dependency_overrides[analytics_mod.get_analytics_engine] = lambda: mock_engine
    try:
        resp = await async_client.get("/api/v1/analytics/concentration")
        assert resp.status_code == 200
        by_sector = resp.json()["by_sector"]
        # MV: TCS=100/1000=0.1, ONGC=900/1000=0.9 (not the stored 0.9/0.1)
        assert abs(by_sector.get("Technology", 0.0) - 0.1) < 1e-3
        assert abs(by_sector.get("Energy", 0.0) - 0.9) < 1e-3
    finally:
        app.dependency_overrides.pop(analytics_mod.get_analytics_engine, None)

    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()


# --- report 01: ad-hoc liquidity-limits mode -------------------------------


@pytest.mark.api
@pytest.mark.asyncio
async def test_liquidity_limits_ad_hoc_mode(async_client, test_db: AsyncSession):
    mock_ds = Mock()
    mock_ds.fetch_historical_data = AsyncMock(return_value=None)
    from main import app
    app.dependency_overrides[analytics_mod.get_data_service] = lambda: mock_ds
    try:
        resp = await async_client.get(
            "/api/v1/analytics/liquidity-limits",
            params={"tickers": "AAA,BBB"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "ad_hoc"
        # Synthetic placeholder notional must not be reported as a real
        # portfolio valuation.
        assert data["portfolio_value"] is None
    finally:
        app.dependency_overrides.pop(analytics_mod.get_data_service, None)


# --- report 01: tails response cache clear hook ----------------------------


@pytest.mark.api
@pytest.mark.asyncio
async def test_clear_cache_purges_tails_memo(async_client, test_db: AsyncSession):
    analytics_mod._TAILS_RESPONSE_CACHE.clear()
    analytics_mod._TAILS_RESPONSE_CACHE[("X",)] = (0.0, {"cached": True})
    assert len(analytics_mod._TAILS_RESPONSE_CACHE) == 1

    resp = await async_client.post("/api/v1/data/cache/clear")
    assert resp.status_code == 200
    assert len(analytics_mod._TAILS_RESPONSE_CACHE) == 0
    analytics_mod._TAILS_RESPONSE_CACHE.clear()


# --- report 01: performance-history excludes qty<=0 ------------------------


@pytest.mark.api
@pytest.mark.asyncio
async def test_performance_history_excludes_degenerate_qty(
    async_client, test_db: AsyncSession
):
    await test_db.execute(delete(PortfolioPosition))
    test_db.add(PortfolioPosition(
        ticker="DEGEN.NS", weight=1.0, quantity=0.0, buy_price=100.0,
        last_price=0.0, market_value=0.0,
    ))
    await test_db.commit()

    resp = await async_client.get("/api/v1/analytics/performance-history")
    assert resp.status_code == 200
    assert resp.json() == []

    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()


# --- report 01: benchmark rebase parity ------------------------------------


@pytest.mark.api
@pytest.mark.asyncio
async def test_performance_history_benchmark_rebased_to_portfolio(
    async_client, test_db: AsyncSession, ohlcv_frame_factory
):
    await test_db.execute(delete(PortfolioPosition))
    test_db.add(PortfolioPosition(
        ticker="AAPL", weight=1.0, quantity=10.0, buy_price=100.0,
        last_price=100.0, market_value=1000.0, added_on=datetime(2020, 1, 1),
    ))
    await test_db.commit()

    frame = ohlcv_frame_factory(days=60, start="2026-07-01", ticker="AAPL")
    mock_ds = Mock()
    mock_ds.fetch_historical_data = AsyncMock(return_value=frame)
    bench = pd.Series(0.001, index=pd.to_datetime(frame["date"]))
    mock_bench = Mock()
    mock_bench.get_returns = AsyncMock(return_value=bench)

    from main import app
    app.dependency_overrides[analytics_mod.get_data_service] = lambda: mock_ds
    app.dependency_overrides[analytics_mod.get_benchmark_service] = lambda: mock_bench
    try:
        resp = await async_client.get(
            "/api/v1/analytics/performance-history", params={"days": 60}
        )
        assert resp.status_code == 200
        data = resp.json()
        with_bench = [d for d in data if "benchmark_value" in d]
        assert with_bench, data[:3]
        first = with_bench[0]
        # Both series must start at the same value on the first common date
        # (old code seeded initial_val * (1+r_d0), one return ahead).
        assert abs(first["benchmark_value"] - first["portfolio_value"]) < 0.05
    finally:
        app.dependency_overrides.pop(analytics_mod.get_data_service, None)
        app.dependency_overrides.pop(analytics_mod.get_benchmark_service, None)

    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()


# --- report 01: tear-sheet benchmark best-effort ---------------------------


@pytest.mark.api
@pytest.mark.asyncio
async def test_tear_sheet_survives_benchmark_failure(
    async_client, test_db: AsyncSession, ohlcv_frame_factory
):
    await test_db.execute(delete(PortfolioPosition))
    frame = ohlcv_frame_factory(days=300, start="2025-06-01", ticker="AAPL")
    mock_ds = Mock()
    mock_ds.fetch_historical_data = AsyncMock(return_value=frame)
    mock_bench = Mock()
    mock_bench.get_returns = AsyncMock(side_effect=Exception("bench down"))

    from main import app
    app.dependency_overrides[analytics_mod.get_data_service] = lambda: mock_ds
    app.dependency_overrides[analytics_mod.get_benchmark_service] = lambda: mock_bench
    try:
        resp = await async_client.get(
            "/api/v1/analytics/tear-sheet", params={"tickers": "AAPL"}
        )
        assert resp.status_code == 200
        data = resp.json()
        # Metrics block still present; relative/benchmark legs degrade only.
        assert "metrics" in data or "total_return" in str(data)
    finally:
        app.dependency_overrides.pop(analytics_mod.get_data_service, None)
        app.dependency_overrides.pop(analytics_mod.get_benchmark_service, None)


# --- report 01: summary passes benchmark into risk_scoring -----------------


@pytest.mark.api
@pytest.mark.asyncio
async def test_summary_passes_benchmark_to_risk_scoring(
    async_client, test_db: AsyncSession, ohlcv_frame_factory
):
    await test_db.execute(delete(PortfolioPosition))
    test_db.add(PortfolioPosition(
        ticker="AAPL", weight=1.0, quantity=10.0, buy_price=100.0,
        last_price=100.0, market_value=1000.0, added_on=datetime(2020, 1, 1),
    ))
    await test_db.commit()

    frame = ohlcv_frame_factory(days=120, start="2026-05-01", ticker="AAPL")
    mock_ds = Mock()
    mock_ds.fetch_historical_data = AsyncMock(return_value=frame)

    captured = {}

    async def fake_risk_scoring(price_data, weights, benchmark_data=None):
        captured["benchmark_data"] = benchmark_data
        return {"overall_score": 42.0, "risk_level": "Low"}

    mock_engine = Mock()
    mock_engine.calculate_portfolio_metrics = AsyncMock(
        return_value={"annual_volatility": 0.2, "sharpe_ratio": 1.0, "max_drawdown": -0.1}
    )
    mock_engine.concentration_analysis = AsyncMock(
        return_value={"herfindahl_index": 0.5}
    )
    mock_engine.risk_scoring = AsyncMock(side_effect=fake_risk_scoring)

    mock_bench = Mock()
    mock_bench.get_returns = AsyncMock(return_value=pd.Series(0.001))

    from main import app
    app.dependency_overrides[analytics_mod.get_data_service] = lambda: mock_ds
    app.dependency_overrides[analytics_mod.get_analytics_engine] = lambda: mock_engine
    app.dependency_overrides[analytics_mod.get_benchmark_service] = lambda: mock_bench
    try:
        resp = await async_client.get("/api/v1/analytics/summary")
        assert resp.status_code == 200
        assert captured.get("benchmark_data") is not None
        assert resp.json()["risk_score"] == 42.0
    finally:
        app.dependency_overrides.pop(analytics_mod.get_data_service, None)
        app.dependency_overrides.pop(analytics_mod.get_analytics_engine, None)
        app.dependency_overrides.pop(analytics_mod.get_benchmark_service, None)

    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()


# --- report 02: health environment field -----------------------------------


@pytest.mark.api
def test_health_reports_settings_environment(client):
    from app.config import settings

    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["environment"] == settings.environment


# --- report 02: production middleware gate ---------------------------------


def test_production_middleware_gated_on_settings():
    src = (BACKEND_DIR / "main.py").read_text(encoding="utf-8")
    assert 'settings.environment == "production"' in src
    assert 'os.getenv("ENVIRONMENT"' not in src


# --- report 02: config PUT empty / config GET 500 --------------------------


@pytest.mark.api
@pytest.mark.asyncio
async def test_config_put_requires_params(async_client, test_db: AsyncSession):
    resp = await async_client.put("/api/v1/data/config")
    assert resp.status_code == 400
    assert "No configuration parameters" in resp.json()["detail"]


@pytest.mark.api
@pytest.mark.asyncio
async def test_config_get_propagates_errors(async_client, test_db: AsyncSession):
    mock_cache = Mock()
    mock_cache.get_cache_stats = AsyncMock(side_effect=RuntimeError("cache down"))

    from main import app
    app.dependency_overrides[data_mod.get_cache_service] = lambda: mock_cache
    try:
        resp = await async_client.get("/api/v1/data/config")
        assert resp.status_code == 500
        assert "cache down" not in resp.text
        assert "Internal server error" in resp.text
    finally:
        app.dependency_overrides.pop(data_mod.get_cache_service, None)


# --- report 02: data source / from_cache -----------------------------------


@pytest.mark.api
@pytest.mark.asyncio
async def test_stock_data_reports_source_and_from_cache(
    async_client, test_db: AsyncSession
):
    dates = pd.date_range("2026-01-01", periods=5)
    df = pd.DataFrame({
        "date": dates,
        "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0,
        "adj_close": 1.0, "volume": 1000,
    })
    df._source = "bfinance"

    mock_ds = Mock()
    mock_ds._get_cached_data = AsyncMock(return_value=None)
    mock_ds.fetch_historical_data = AsyncMock(return_value=df)
    mock_ds.fetch_quote = AsyncMock(return_value=None)
    mock_ds._source_of_df = Mock(return_value="bfinance")

    from main import app
    app.dependency_overrides[data_mod.get_data_service] = lambda: mock_ds
    try:
        resp = await async_client.get("/api/v1/data/TEST")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["from_cache"] is False
        assert payload["source"] == "bfinance"
    finally:
        app.dependency_overrides.pop(data_mod.get_data_service, None)

    # Cache-hit path: pre-fetch probe sees rows -> from_cache True
    mock_ds._get_cached_data = AsyncMock(return_value=df)
    app.dependency_overrides[data_mod.get_data_service] = lambda: mock_ds
    try:
        resp = await async_client.get("/api/v1/data/TEST")
        assert resp.status_code == 200
        assert resp.json()["from_cache"] is True
    finally:
        app.dependency_overrides.pop(data_mod.get_data_service, None)


# --- report 02: str(e) leak on equity-research 500s ------------------------


@pytest.mark.api
@pytest.mark.asyncio
async def test_equity_research_500_hides_exception_detail():
    from main import app

    mock_svc = Mock()
    mock_svc.get_full_profile = AsyncMock(side_effect=Exception("boom secret"))
    transport = ASGITransport(app=app)
    with patch.object(er_mod, "get_equity_research_service", return_value=mock_svc):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/company/RELIANCE/full-profile")
    assert resp.status_code == 500
    assert "secret" not in resp.text
