"""AI-ready portfolio context export endpoints."""

from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import model_serializer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.models.schemas import AIContextResponse, AIContextSection
from app.services.ai_context_service import (
    ContextOptions,
    PortfolioContextService,
    parse_include,
    render_markdown,
)

router = APIRouter()


class AIContextSectionExport(AIContextSection):
    """Public section shape: a successful section carries no `error` field.

    The exporter already omits the key for successful sections. The shared
    response model would otherwise re-publish `error: null` as a misleading
    sentinel, so the boundary drops only that inapplicable field while every
    other documented key (including `data: null` and `coverage: null`) is kept.
    """

    @model_serializer(mode="wrap")
    def _drop_inapplicable_error(self, handler) -> Dict[str, Any]:
        payload = handler(self)
        if isinstance(payload, dict) and payload.get("error") is None:
            payload.pop("error", None)
        return payload


class AIContextExport(AIContextResponse):
    """Envelope whose sections use the public section shape above."""

    sections: Dict[str, AIContextSectionExport]


@router.get(
    "/context",
    response_model=AIContextExport,
    summary="Export all portfolio analytics as AI-ready JSON or Markdown",
)
async def get_portfolio_context(
    format: Literal["json", "markdown"] = Query(default="json"),
    detail: Literal["summary", "full"] = Query(default="summary"),
    include: Optional[str] = Query(default=None, description="Comma-separated page section keys"),
    base_currency: str = Query(default="INR", description="Target currency: INR or USD"),
    forecast_model: str = Query(default="GARCH", description="GARCH, EGARCH, or EWMA"),
    forecast_horizon: int = Query(default=1, ge=1, le=30),
    factor_lookback_days: int = Query(default=252, ge=30, le=756),
    optimization_strategy: str = Query(default="hrp"),
    monte_carlo_method: str = Query(default="student_t"),
    monte_carlo_horizon_years: float = Query(default=5.0, ge=1.0, le=40.0),
    monte_carlo_target_value: Optional[float] = Query(default=None, gt=0.0),
    monte_carlo_seed: int = Query(default=42, ge=0, le=4294967295),
    db: AsyncSession = Depends(get_db_session),
):
    """Return one canonical snapshot; Markdown is rendered from that JSON."""
    try:
        options = ContextOptions(
            detail=detail,
            include=parse_include(include),
            base_currency=base_currency,
            forecast_model=forecast_model,
            forecast_horizon=forecast_horizon,
            factor_lookback_days=factor_lookback_days,
            optimization_strategy=optimization_strategy,
            monte_carlo_method=monte_carlo_method,
            monte_carlo_horizon_years=monte_carlo_horizon_years,
            monte_carlo_target_value=monte_carlo_target_value,
            monte_carlo_seed=monte_carlo_seed,
        )
        payload = await PortfolioContextService(db).build(options)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if format == "markdown":
        return Response(
            content=render_markdown(payload),
            media_type="text/markdown; charset=utf-8",
        )
    return payload
