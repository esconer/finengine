"""
Equity Research & Screener API Endpoints for Daisy Risk Engine.
Provides REST routes for full company profile, 12Q/11Y institutional shareholding,
40+ concalls with audio MP3s, custom ratios, Excel exporter, and screeners.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.services.equity_research_service import get_equity_research_service
from app.services.screener_service import get_screener_service
from app.services.ai_dossier_service import get_ai_dossier_service
from app.models.schemas import (
    EquityResearchProfileResponse,
    ShareholdingResponse,
    CustomRatiosResponse,
    ScreenerResponse,
    CustomScreenRequest,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()


# ------------------------------------------------------------- Equity Research
@router.get("/company/{ticker}/full-profile", response_model=EquityResearchProfileResponse)
async def get_company_full_profile(ticker: str):
    """
    Get 360-degree company profile with 4-level taxonomy, live ratios,
    CAGR growth matrix, qualitative pros/cons, and peer comparison.
    """
    try:
        service = get_equity_research_service()
        data = await service.get_full_profile(ticker)
        return data
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error fetching full profile for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/company/{ticker}/shareholding", response_model=ShareholdingResponse)
async def get_company_shareholding(ticker: str):
    """
    Get 12-quarter quarterly + 11-year annual institutional shareholding trends.
    """
    try:
        service = get_equity_research_service()
        return await service.get_shareholding(ticker)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error fetching shareholding for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/company/{ticker}/concalls")
async def get_company_concalls(ticker: str):
    """
    Get 40+ conference calls with BSE transcript PDFs, PPT links, and streamable audio MP3 links.
    """
    try:
        service = get_equity_research_service()
        concalls = await service.get_concalls(ticker)
        return {"ticker": ticker.upper(), "count": len(concalls), "concalls": concalls}
    except Exception as e:
        logger.error(f"Error fetching concalls for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/company/{ticker}/custom-ratios", response_model=CustomRatiosResponse)
async def get_company_custom_ratios(ticker: str):
    """
    Get forensic & valuation ratios: Piotroski score, Graham Number, EV/EBITDA,
    Interest Coverage, CFO/PAT, and historical operating metrics.
    """
    try:
        service = get_equity_research_service()
        return await service.get_custom_ratios(ticker)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error fetching custom ratios for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/company/{ticker}/export-excel")
async def export_company_excel_model(ticker: str):
    """
    Stream a generated 8-tab Excel financial model workbook (.xlsx) for download.
    """
    try:
        service = get_equity_research_service()
        content = await service.export_excel_model(ticker)
        filename = f"{ticker.upper().replace('.NS', '').replace('.BO', '')}_financial_model.xlsx"
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error exporting Excel for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


# ------------------------------------------------------------- AI Prompts & Dossiers
@router.get("/company/{ticker}/ai-memo-prompt")
async def get_ai_investment_memo_prompt(
    ticker: str,
    custom_instructions: Optional[str] = Query(default="", description="Custom instructions for investment memo"),
):
    """
    Generate an initiation coverage investment memo prompt for LLMs.
    """
    try:
        service = get_ai_dossier_service()
        prompt = await service.get_investment_memo_prompt(ticker, custom_instructions=custom_instructions)
        return {"ticker": ticker.upper(), "prompt": prompt}
    except Exception as e:
        logger.error(f"Error generating memo prompt for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/company/{ticker}/ai-forensic-prompt")
async def get_ai_forensic_prompt(ticker: str):
    """
    Generate a forensic accounting audit prompt for LLMs.
    """
    try:
        service = get_ai_dossier_service()
        prompt = await service.get_forensic_audit_prompt(ticker)
        return {"ticker": ticker.upper(), "prompt": prompt}
    except Exception as e:
        logger.error(f"Error generating forensic prompt for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/company/{ticker}/ai-dossier")
async def get_ai_dossier(
    ticker: str,
    format: str = Query(default="markdown", description="markdown | json"),
):
    """
    Generate token-dense Markdown or JSON financial dossier for LLM ingestion.
    """
    try:
        service = get_ai_dossier_service()
        dossier = await service.get_ai_dossier(ticker, format=format)
        if format == "json":
            return {"ticker": ticker.upper(), "format": format, "data": dossier}
        return {"ticker": ticker.upper(), "format": format, "content": dossier}
    except Exception as e:
        logger.error(f"Error generating AI dossier for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


# ------------------------------------------------------------- Institutional Screeners
@router.get("/screens", response_model=List[Dict[str, Any]])
async def list_screener_strategies():
    """
    List all pre-built quantitative screening strategies.
    """
    service = get_screener_service()
    return await service.get_available_strategies()


@router.get("/screens/{strategy}", response_model=ScreenerResponse)
async def run_screener_strategy(
    strategy: str,
    max_stocks: int = Query(default=50, ge=5, le=100, description="Max stocks to scan"),
):
    """
    Run an institutional screening strategy:
    - coffee_can: Saurabh Mukherjea Coffee Can (ROCE > 15%, ROE > 15%)
    - magic_formula: Joel Greenblatt Magic Formula (High ROCE + Low P/E)
    - debt_free: Debt-Free Compounders (ROCE >= 20%, Mcap >= 10k Cr)
    - high_dividend: High Dividend Champions (Yield >= 2.5%, ROCE >= 12%)
    - undervalued_growth: Undervalued Growth (P/E <= 22, ROE >= 15%)
    """
    try:
        service = get_screener_service()
        return await service.run_screen(strategy, max_stocks=max_stocks)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error running screener {strategy}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/screens/custom", response_model=ScreenerResponse)
async def run_custom_screen(request: CustomScreenRequest):
    """
    Run custom multi-ratio screener.
    """
    try:
        service = get_screener_service()
        return await service.run_custom_screen(
            min_roce=request.min_roce,
            min_roe=request.min_roe,
            max_pe=request.max_pe,
            min_mcap_cr=request.min_mcap_cr,
            min_div_yield=request.min_div_yield,
            max_stocks=request.max_stocks or 50,
        )
    except Exception as e:
        logger.error(f"Error running custom screener: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
