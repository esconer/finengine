"""
Regression gates for audit 05-market-data-services (B-01..B-19 + HANDOFF #1).

One permanent test per nontrivial fix in this pass:
- B-01/B-03 cross-tier unit contract (market_cap absolute INR, ROE percent)
- B-04 AV outputsize=full
- B-05/B-11 error taxonomy: outages -> RuntimeError (5xx), not-found -> ValueError (404)
- B-06 screener vendor failure -> RuntimeError (route no longer 400)
- B-07 FX fallback never enters the cache
- B-09 _to_thread forwards *args
- B-10 AV quote echoes the requested ticker
- B-13 dividend-yield filter reads bfinance percent as percent
- B-14 volume-only frame -> ADV defaults, no StopIteration
- B-15 None OHLC record fields ingest as 0 instead of TypeError
- I-07 dead mutable participation_rates default removed
- HANDOFF #1 (06-foundation): concurrent same-key NSE ingests do not raise
"""

import inspect
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import numpy as np
import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.services.screener_service as ss
from main import app
from app.models.database import NSEBhavcopy
from app.services.ai_dossier_service import AIDossierService
from app.services.alpha_vantage_service import AlphaVantageService
from app.services.company_data_service import CompanyDataService, _to_thread
from app.services.currency_service import CurrencyConversionService
from app.services.equity_research_service import EquityResearchService
from app.services.india_data_service import IndiaDataService
from app.models.database import PortfolioPosition
from app.services.screener_service import ScreenerService


# ---------------------------------------------------------------- B-01 / B-03

def _bf_ticker(market_cap_cr: float, roe: float) -> Mock:
    profile = Mock()
    profile.name = "Test Co"
    profile.sector = "Energy"
    profile.industry_group = "Conglomerate"
    profile.industry = "Refining"
    profile.sub_industry = "Oil"
    profile.indices = ["NIFTY 50"]
    profile.about = "about"
    profile.analysis = None
    profile.ratios = Mock(market_cap=market_cap_cr, roe=roe)
    t = Mock()
    t._ensure_profile.return_value = profile
    t.info = {}
    t.piotroski_score = None
    t.graham_number = None
    t.enterprise_value = None
    t.ev_to_ebitda = None
    t.interest_coverage = None
    return t


async def test_cross_tier_market_cap_and_roe_share_one_unit_contract():
    """Same economics via both vendors -> same magnitude and scale.

    bfinance tier: Ratios.market_cap is INR Cr (models/company.py:13),
    converted to absolute INR (*1e7, B-01); yfinance tier maps raw
    marketCap (absolute INR). ROE: bfinance r.roe is percent, yfinance
    returnOnEquity is a fraction converted to percent (B-03).
    """
    # 190_000 Cr = 1.9e12 INR; economic ROE = 14.5% both sides.
    with patch("bfinance.Ticker", return_value=_bf_ticker(190_000.0, 14.5)):
        bf_out = await CompanyDataService().get_fundamentals(
            "RELIANCE", source_order=["bfinance"]
        )

    info = {"longName": "Test Co", "marketCap": 1.9e12, "returnOnEquity": 0.145}
    with patch("yfinance.Ticker", return_value=Mock(info=info)):
        yf_out = await CompanyDataService().get_fundamentals(
            "RELIANCE", source_order=["yfinance"]
        )

    assert bf_out["market_cap"] == pytest.approx(1.9e12, rel=1e-9)
    assert yf_out["market_cap"] == pytest.approx(1.9e12, rel=1e-9)
    # magnitudes must agree across tiers (a unit flip is off by ~1e7)
    assert abs(bf_out["market_cap"] - yf_out["market_cap"]) < 1e-4 * 1.9e12
    assert bf_out["return_on_equity"] == pytest.approx(14.5)
    assert yf_out["return_on_equity"] == pytest.approx(14.5)


# ---------------------------------------------------------------------- B-04

async def test_av_daily_ohlcv_requests_full_outputsize():
    svc = AlphaVantageService()
    payload = {
        "Time Series (Daily)": {
            "2026-01-02": {"1. open": "10", "2. high": "11", "3. low": "9",
                            "4. close": "10.5", "5. volume": "1000"}
        }
    }
    with patch.object(svc, "_make_request", new=AsyncMock(return_value=payload)) as m:
        await svc.fetch_daily_ohlcv("RELIANCE.NS", "2026-01-01", "2026-01-05")
    assert m.call_args[0][0] == "TIME_SERIES_DAILY"
    assert m.call_args[0][1]["outputsize"] == "full"


# ---------------------------------------------------------------------- B-10

async def test_av_quote_echoes_requested_ticker_not_bridged():
    svc = AlphaVantageService()
    payload = {"Global Quote": {
        "05. price": "2500.55", "06. volume": "100",
        "08. previous close": "2490.00",
    }}
    with patch.object(svc, "_make_request", new=AsyncMock(return_value=payload)):
        q = await svc.fetch_global_quote("RELIANCE.NS")
    assert q["ticker"] == "RELIANCE.NS"      # requested, not RELIANCE.BSE
    assert q["currency"] == "INR"            # BSE context still reflected
    assert q["exchange"] == "BSE"


# ---------------------------------------------------------------------- B-09

async def test_to_thread_forwards_args():
    assert await _to_thread(lambda a, b: a + b, 1, 2) == 3


# ---------------------------------------------------------------------- B-07

async def test_fx_fallback_is_served_but_never_cached():
    svc = CurrencyConversionService()
    with patch("yfinance.Ticker", side_effect=Exception("API down")):
        assert await svc.get_exchange_rate("USD", "INR") == 83.0

    info = svc.get_exchange_rate_info()
    assert info["usd_to_inr"] is None       # 83.0 must not read as live
    assert info["last_updated"] is None     # cache untouched by fallback
    assert "USD_INR" not in svc._exchange_rates

    # next successful fetch must overwrite/enter the cache normally
    mock_ticker = MagicMock()
    mock_ticker.fast_info = MagicMock(last_price=85.0)
    with patch("yfinance.Ticker", return_value=mock_ticker):
        assert await svc.get_exchange_rate("USD", "INR") == 85.0
    assert svc.get_exchange_rate_info()["usd_to_inr"] == 85.0


# ----------------------------------------------------------------- B-05 / B-11

async def test_full_profile_outage_raises_runtime_error_not_value_error():
    with patch("bfinance.Ticker", side_effect=ConnectionError("bfinance down")):
        with pytest.raises(RuntimeError, match="Failed to load research profile"):
            await EquityResearchService().get_full_profile("RELIANCE")


async def test_full_profile_not_found_stays_value_error():
    mock_t = Mock()
    mock_t._ensure_profile.return_value = None
    with patch("bfinance.Ticker", return_value=mock_t):
        with pytest.raises(ValueError, match="No equity profile found"):
            await EquityResearchService().get_full_profile("RELIANCE")


async def test_full_profile_outage_route_is_not_404():
    transport = ASGITransport(app=app)
    mock_svc = Mock()
    mock_svc.get_full_profile = AsyncMock(side_effect=RuntimeError("upstream down"))
    with patch("app.api.equity_research.get_equity_research_service", return_value=mock_svc):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/company/RELIANCE/full-profile")
    # 503 once the API handoff lands; never 404 for an outage
    assert resp.status_code in (500, 503)


async def test_full_profile_not_found_route_stays_404():
    transport = ASGITransport(app=app)
    mock_svc = Mock()
    mock_svc.get_full_profile = AsyncMock(side_effect=ValueError("No equity profile found"))
    with patch("app.api.equity_research.get_equity_research_service", return_value=mock_svc):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/company/NOPE/full-profile")
    assert resp.status_code == 404


async def test_concalls_outage_raises_instead_of_empty_list():
    with patch("bfinance.Ticker", side_effect=ConnectionError("bfinance down")):
        with pytest.raises(RuntimeError, match="concalls"):
            await EquityResearchService().get_concalls("RELIANCE")


async def test_concalls_legitimately_empty_profile_returns_empty_list():
    mock_t = Mock()
    profile = Mock()
    profile.concalls = []
    mock_t._ensure_profile.return_value = profile
    with patch("bfinance.Ticker", return_value=mock_t):
        assert await EquityResearchService().get_concalls("RELIANCE") == []


async def test_ai_dossier_outage_raises_runtime_error():
    # verified-05 B-05 claimed AI routes map these to 500; they map
    # ValueError -> 404 first (api/equity_research.py:173) — so the service
    # must not wrap upstream failures as ValueError.
    with patch("bfinance.Ticker", side_effect=ConnectionError("bfinance down")):
        with pytest.raises(RuntimeError, match="AI dossier"):
            await AIDossierService().get_ai_dossier("RELIANCE")


# ---------------------------------------------------------------------- B-06

async def test_screen_vendor_failure_raises_runtime_error(monkeypatch):
    class _Boom:
        def run(self, *args, **kwargs):
            raise ConnectionError("bfinance down")

    ScreenerService._cache.clear()
    monkeypatch.setitem(
        ScreenerService.STRATEGIES["coffee_can"], "screen_getter", lambda: _Boom()
    )
    try:
        with pytest.raises(RuntimeError, match="Screen execution failed"):
            await ScreenerService().run_screen("coffee_can")
    finally:
        ScreenerService._cache.clear()


async def test_screen_route_taxonomy_outage_not_400_unknown_strategy_400():
    transport = ASGITransport(app=app)
    with patch("app.api.equity_research.ScreenerService") as mock_cls:
        mock_cls.return_value.run_screen = AsyncMock(side_effect=RuntimeError("down"))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/screens/coffee_can")
        assert resp.status_code in (500, 503)  # never 400 for a vendor outage

        mock_cls.return_value.run_screen = AsyncMock(side_effect=ValueError("Unknown strategy"))
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/screens/not_a_strategy")
        assert resp.status_code == 400


# ---------------------------------------------------------------------- B-13

async def test_custom_screen_div_yield_filter_reads_bfinance_percent(monkeypatch):
    # bfinance info["dividendYield"] is raw percent (0.85 = 0.85%), so a
    # 2.5% floor must exclude it; the old *100 admitted it (85 >= 2.5).
    candidates = {
        "LOWDIV": {"dividendYield": 0.85},
        "HIDIV": {"dividendYield": 2.81},
    }

    class _T:
        def __init__(self, info):
            self.info = info

    class _FakeCustomScreen:
        def __init__(self, *args, **kwargs):
            self.filter_fn = kwargs.get("filter_fn")

        def run(self, max_stocks=None, **kwargs):
            rows = []
            for sym, info in candidates.items():
                if self.filter_fn(_T(info)):
                    rows.append({
                        "Symbol": sym, "Name": sym, "Price": 100.0,
                        "MarketCap_Cr": 10000.0, "PE": 15.0, "ROCE_%": 25.0,
                        "ROE_%": 20.0, "DivYield_%": info["dividendYield"],
                    })
            return pd.DataFrame(rows)

    monkeypatch.setattr(ss.bf, "Screen", _FakeCustomScreen)
    res = await ScreenerService().run_custom_screen(min_div_yield=2.5)
    assert [s["symbol"] for s in res["stocks"]] == ["HIDIV"]


# ---------------------------------------------------------------------- B-14

async def test_liquidity_limits_volume_only_frame_falls_back_to_defaults(test_db):
    service = IndiaDataService(db=test_db)
    p = PortfolioPosition(
        ticker="X.NS", quantity=100.0, buy_price=10.0, last_price=12.0,
        market_value=1200.0, weight=1.0,
    )
    df = pd.DataFrame(
        {"volume": np.full(40, 5000.0)},
        index=pd.date_range("2024-01-01", periods=40, freq="B"),
    )
    limits = await service.calculate_portfolio_liquidity_limits([p], {"X.NS": df})
    assert limits["positions"][0]["adv_30d_shares"] == 50000.0  # default branch
    assert limits["positions"][0]["liquidity_tier"]


# ---------------------------------------------------------------------- B-15

async def test_bhavcopy_none_ohlc_fields_ingest_without_typeerror(test_db):
    service = IndiaDataService(db=test_db)
    rec = {
        "symbol": "NILTEST", "open": None, "high": None, "low": None,
        "close": None, "prev_close": None, "avg_price": None,
        "ttl_trd_qnty": None, "turnover_lacs": None, "no_of_trades": None,
    }
    count = await service.ingest_bhavcopy_records([rec], datetime.utcnow())
    assert count == 1


# ---------------------------------------------------------------------- I-07

def test_liquidity_limits_signature_has_no_mutable_default():
    sig = inspect.signature(IndiaDataService.calculate_portfolio_liquidity_limits)
    assert "participation_rates" not in sig.parameters
    for p in sig.parameters.values():
        assert not isinstance(p.default, (list, dict, set))  # no shared mutable


# ------------------------------------------------------- HANDOFF #1 (foundation)

async def test_concurrent_bhavcopy_ingest_does_not_raise(test_db):
    service = IndiaDataService(db=test_db)
    today = datetime.utcnow()
    recs = [{"symbol": "RACER", "close": 100.0, "ttl_trd_qnty": 1000}]
    assert await service.ingest_bhavcopy_records(list(recs), today) == 1

    # Simulate the concurrent racer: its existence-select saw nothing, then
    # its insert collides with uq_bhav_symbol_date.
    empty = Mock()
    empty.scalars.return_value.all.return_value = []
    with patch.object(test_db, "execute", new=AsyncMock(return_value=empty)):
        assert await service.ingest_bhavcopy_records(list(recs), today) == 0

    res = await test_db.execute(select(NSEBhavcopy).where(NSEBhavcopy.symbol == "RACER"))
    assert len(res.scalars().all()) == 1  # deduped, no exception


async def test_concurrent_institutional_flow_ingest_updates_winner(test_db):
    service = IndiaDataService(db=test_db)
    today = datetime.utcnow()
    assert await service.ingest_institutional_flow(today, "FII", 100.0, 50.0) is True

    # Racer: select lies (empty), insert collides with uq_flow_date_cat,
    # handler reselects the winner row and updates it.
    empty = Mock()
    empty.scalar_one_or_none.return_value = None  # flow select saw no row
    winner_res = Mock()
    winner_row = Mock()
    winner_res.scalar_one_or_none.return_value = winner_row
    with patch.object(
        test_db, "execute", new=AsyncMock(side_effect=[empty, winner_res])
    ):
        ok = await service.ingest_institutional_flow(today, "FII", 999.0, 444.0)

    assert ok is True
    assert winner_row.buy_value_crores == 999.0
    assert winner_row.sell_value_crores == 444.0
    assert winner_row.net_value_crores == 999.0 - 444.0
