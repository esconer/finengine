"""
Comprehensive tests for EquityResearchService, ScreenerService, AIDossierService,
and REST endpoints in equity_research.py.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from httpx import AsyncClient, ASGITransport
import pandas as pd
import bfinance as bf

from main import app
from app.services.equity_research_service import EquityResearchService
from app.services.screener_service import ScreenerService
from app.services.ai_dossier_service import AIDossierService


@pytest.fixture
def mock_bfinance_ticker():
    mock_t = Mock()
    mock_t.symbol = "RELIANCE"
    mock_t.ticker = "RELIANCE.NS"
    mock_t.piotroski_score = 7
    mock_t.graham_number = 3250.0
    mock_t.enterprise_value = 1950000.0
    mock_t.ev_to_ebitda = 12.4
    mock_t.interest_coverage = 8.5
    mock_t.custom_ratios = {
        "piotroski_score": 7,
        "graham_number": 3250.0,
        "enterprise_value_cr": 1950000.0,
        "ev_to_ebitda": 12.4,
        "interest_coverage": 8.5,
        "cfo_to_pat_ratio": 1.15,
    }
    mock_t.info = {
        "shortName": "Reliance Industries",
        "currentPrice": 2900.0,
        "marketCapInCr": 1900000.0,
        "trailingPE": 24.5,
        "returnOnCapitalEmployed": 16.2,
        "returnOnEquity": 0.145,
        "dividendYield": 0.004,
        "bookValue": 1200.0,
    }

    mock_profile = Mock()
    mock_profile.symbol = "RELIANCE"
    mock_profile.name = "Reliance Industries Limited"
    mock_profile.about = "Conglomerate in energy, retail, telecom."
    mock_profile.website = "https://www.ril.com"
    mock_profile.bse_code = "500325"
    mock_profile.nse_symbol = "RELIANCE"
    mock_profile.sector = "Energy"
    mock_profile.industry_group = "Oil & Gas"
    mock_profile.industry = "Refining & Marketing"
    mock_profile.sub_industry = "Integrated Oil & Gas"
    mock_profile.indices = ["NIFTY 50", "BSE SENSEX"]
    
    mock_ratios = Mock()
    mock_ratios.market_cap = 1900000.0
    mock_ratios.current_price = 2900.0
    mock_ratios.high_52w = 3217.0
    mock_ratios.low_52w = 2220.0
    mock_ratios.stock_pe = 24.5
    mock_ratios.book_value = 1200.0
    mock_ratios.dividend_yield = 0.4
    mock_ratios.roce = 16.2
    mock_ratios.roe = 14.5
    mock_ratios.face_value = 10.0
    mock_ratios.debt_to_equity = 0.42
    mock_ratios.peg_ratio = 1.8
    mock_ratios.eps_ttm = 118.0
    mock_ratios.promoter_holding = 50.3
    mock_ratios.promoter_pledged = 0.0
    mock_profile.ratios = mock_ratios

    mock_analysis = Mock()
    mock_analysis.pros = ["Company is almost debt free", "Good profit growth"]
    mock_analysis.cons = ["Stock is trading at 2.4x book value"]
    mock_profile.analysis = mock_analysis

    mock_profile.cagrs = {
        "Compounded Sales Growth": {"10 Years:": "12%", "5 Years:": "15%"},
        "Compounded Profit Growth": {"10 Years:": "14%", "5 Years:": "18%"},
    }

    mock_peer = Mock()
    mock_peer.model_dump.return_value = {
        "rank": 1,
        "name": "TCS",
        "symbol": "TCS",
        "cmp": 4100.0,
        "pe": 28.5,
        "market_cap_cr": 1500000.0,
        "roce": 52.0,
        "dividend_yield": 1.2,
    }
    mock_profile.peers = [mock_peer]

    mock_concall = Mock()
    mock_concall.date = "2026-01-20"
    mock_concall.quarter = "Q3 FY26"
    mock_concall.title = "Q3 FY26 Earnings Call"
    mock_concall.transcript_url = "https://example.com/transcript.pdf"
    mock_concall.audio_url = "https://example.com/audio.mp3"
    mock_concall.presentation_url = "https://example.com/presentation.pdf"
    mock_concall.model_dump.return_value = {
        "date": "2026-01-20",
        "quarter": "Q3 FY26",
        "title": "Q3 FY26 Earnings Call",
        "transcript_url": "https://example.com/transcript.pdf",
        "audio_url": "https://example.com/audio.mp3",
        "presentation_url": "https://example.com/presentation.pdf",
    }
    mock_profile.concalls = [mock_concall]
    mock_profile.annual_reports = [{"year": "2025", "url": "https://example.com/ar2025.pdf"}]
    mock_profile.credit_ratings = [{"agency": "CRISIL", "rating": "AAA"}]

    # Financial statements
    sh_stmt = Mock()
    sh_stmt.to_dataframe.return_value = pd.DataFrame(
        {"2025-09-30": [50.3, 21.5, 16.2, 0.2, 11.8]},
        index=["Promoters", "FIIs", "DIIs", "Government", "Public"]
    )
    sh_stmt.rows = {"Promoters": [50.3], "FIIs": [21.5], "DIIs": [16.2]}
    mock_profile.shareholding = sh_stmt
    mock_profile.shareholding_yearly = sh_stmt

    rh_stmt = Mock()
    rh_stmt.to_dataframe.return_value = pd.DataFrame(
        {"Mar 2025": [12.0, 16.2]},
        index=["Debtor Days", "ROCE %"]
    )
    rh_stmt.rows = {"Debtor Days": [12.0]}
    mock_profile.ratios_history = rh_stmt

    mock_t._ensure_profile.return_value = mock_profile
    mock_t.to_ai_context.return_value = "# AI Dossier Markdown"
    mock_t.to_investment_memo_prompt.return_value = "<INSTRUCTIONS>Draft memo</INSTRUCTIONS>"
    mock_t.to_forensic_audit_prompt.return_value = "<INSTRUCTIONS>Forensic Audit</INSTRUCTIONS>"
    mock_t.to_concall_analyst_prompt.return_value = "<INSTRUCTIONS>Concall Summary</INSTRUCTIONS>"

    return mock_t


@pytest.mark.asyncio
class TestEquityResearchService:
    async def test_get_full_profile(self, mock_bfinance_ticker):
        with patch("bfinance.Ticker", return_value=mock_bfinance_ticker):
            service = EquityResearchService()
            profile = await service.get_full_profile("RELIANCE")
            assert profile["ticker"] == "RELIANCE.NS"
            assert profile["name"] == "Reliance Industries Limited"
            assert profile["sector"] == "Energy"
            assert profile["custom_ratios"]["piotroski_score"] == 7
            assert profile["custom_ratios"]["graham_number"] == 3250.0
            assert profile["concall_count"] == 1
            assert len(profile["pros"]) > 0

    async def test_get_shareholding(self, mock_bfinance_ticker):
        with patch("bfinance.Ticker", return_value=mock_bfinance_ticker):
            service = EquityResearchService()
            sh = await service.get_shareholding("RELIANCE")
            assert sh["ticker"] == "RELIANCE.NS"
            assert len(sh["quarterly"]["periods"]) >= 1
            assert len(sh["quarterly"]["chart_series"]) >= 1

    async def test_get_concalls(self, mock_bfinance_ticker):
        with patch("bfinance.Ticker", return_value=mock_bfinance_ticker):
            service = EquityResearchService()
            concalls = await service.get_concalls("RELIANCE")
            assert len(concalls) == 1
            assert concalls[0]["audio_url"] == "https://example.com/audio.mp3"

    async def test_get_custom_ratios(self, mock_bfinance_ticker):
        with patch("bfinance.Ticker", return_value=mock_bfinance_ticker):
            service = EquityResearchService()
            ratios = await service.get_custom_ratios("RELIANCE")
            assert ratios["ticker"] == "RELIANCE.NS"
            assert ratios["piotroski_score"] == 7
            assert ratios["cfo_to_pat_ratio"] == 1.15

    async def test_export_excel_model(self, mock_bfinance_ticker):
        with patch("bfinance.Ticker", return_value=mock_bfinance_ticker), \
             patch("bfinance.utils.excel.FinancialModelExcelExporter.export", return_value="test.xlsx"):
            service = EquityResearchService()
            content = await service.export_excel_model("RELIANCE")
            assert isinstance(content, bytes)


@pytest.mark.asyncio
class TestScreenerService:
    async def test_get_available_strategies(self):
        service = ScreenerService()
        strategies = await service.get_available_strategies()
        assert len(strategies) >= 5
        keys = [s["key"] for s in strategies]
        assert "coffee_can" in keys
        assert "magic_formula" in keys
        assert "debt_free" in keys

    async def test_run_screen_strategy(self):
        service = ScreenerService()
        mock_df = pd.DataFrame([
            {
                "Symbol": "TCS",
                "Name": "Tata Consultancy Services",
                "Price": 4100.0,
                "MarketCap_Cr": 1500000.0,
                "PE": 28.5,
                "ROCE_%": 52.0,
                "ROE_%": 48.0,
                "DivYield_%": 1.2,
                "BookValue": 250.0,
            }
        ])

        with patch.object(bf.Screen, "run", return_value=mock_df):
            result = await service.run_screen("coffee_can")
            assert result["strategy"] == "coffee_can"
            assert result["count"] == 1
            assert result["stocks"][0]["symbol"] == "TCS"
            assert result["stocks"][0]["price"] == 4100.0

    async def test_unknown_strategy_raises_value_error(self):
        service = ScreenerService()
        with pytest.raises(ValueError, match="Unknown strategy"):
            await service.run_screen("non_existent_strategy")


@pytest.mark.asyncio
class TestAIDossierService:
    async def test_get_ai_dossier(self, mock_bfinance_ticker):
        with patch("bfinance.Ticker", return_value=mock_bfinance_ticker):
            service = AIDossierService()
            dossier = await service.get_ai_dossier("RELIANCE", format="markdown")
            assert "AI Dossier" in dossier

    async def test_get_investment_memo_prompt(self, mock_bfinance_ticker):
        with patch("bfinance.Ticker", return_value=mock_bfinance_ticker):
            service = AIDossierService()
            prompt = await service.get_investment_memo_prompt("RELIANCE")
            assert "<INSTRUCTIONS>" in prompt


@pytest.mark.asyncio
class TestEquityResearchAPIRoutes:
    async def test_api_full_profile(self, mock_bfinance_ticker):
        transport = ASGITransport(app=app)
        with patch("bfinance.Ticker", return_value=mock_bfinance_ticker):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/v1/company/RELIANCE/full-profile")
                assert resp.status_code == 200
                data = resp.json()
                assert data["symbol"] == "RELIANCE"
                assert data["sector"] == "Energy"
                assert data["custom_ratios"]["piotroski_score"] == 7

    async def test_api_shareholding(self, mock_bfinance_ticker):
        transport = ASGITransport(app=app)
        with patch("bfinance.Ticker", return_value=mock_bfinance_ticker):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/v1/company/RELIANCE/shareholding")
                assert resp.status_code == 200
                data = resp.json()
                assert data["ticker"] == "RELIANCE.NS"
                assert "quarterly" in data
                assert "yearly" in data

    async def test_api_concalls(self, mock_bfinance_ticker):
        transport = ASGITransport(app=app)
        with patch("bfinance.Ticker", return_value=mock_bfinance_ticker):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/v1/company/RELIANCE/concalls")
                assert resp.status_code == 200
                data = resp.json()
                assert data["count"] == 1
                assert data["concalls"][0]["audio_url"] == "https://example.com/audio.mp3"

    async def test_api_custom_ratios(self, mock_bfinance_ticker):
        transport = ASGITransport(app=app)
        with patch("bfinance.Ticker", return_value=mock_bfinance_ticker):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/v1/company/RELIANCE/custom-ratios")
                assert resp.status_code == 200
                data = resp.json()
                assert data["piotroski_score"] == 7
                assert data["graham_number"] == 3250.0

    async def test_api_export_excel(self, mock_bfinance_ticker):
        transport = ASGITransport(app=app)
        with patch("bfinance.Ticker", return_value=mock_bfinance_ticker), \
             patch("bfinance.utils.excel.FinancialModelExcelExporter.export", return_value="model.xlsx"):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/v1/company/RELIANCE/export-excel")
                assert resp.status_code == 200
                assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                assert "attachment" in resp.headers["content-disposition"]

    async def test_api_ai_prompts(self, mock_bfinance_ticker):
        transport = ASGITransport(app=app)
        with patch("bfinance.Ticker", return_value=mock_bfinance_ticker):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                r1 = await ac.get("/api/v1/company/RELIANCE/ai-memo-prompt")
                assert r1.status_code == 200
                assert "prompt" in r1.json()

                r2 = await ac.get("/api/v1/company/RELIANCE/ai-forensic-prompt")
                assert r2.status_code == 200
                assert "prompt" in r2.json()

                r3 = await ac.get("/api/v1/company/RELIANCE/ai-dossier?format=markdown")
                assert r3.status_code == 200
                assert "content" in r3.json()

    async def test_api_screens_list(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/screens")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) >= 5
