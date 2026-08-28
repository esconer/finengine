"""
AI Dossier & Prompt Engineering Service for Indian Equities.
Provides institutional initiation coverage memos, forensic audit prompts,
earnings concall summaries, and token-dense LLM contexts via bfinance.ai.
"""

import asyncio
from typing import Any, Dict, List, Literal, Optional, Union

import bfinance as bf
from app.services.data_service import DataService
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _normalize(ticker: str) -> str:
    """Normalize ticker to standard Indian format (.NS default)."""
    return DataService(None)._normalize_indian_ticker(ticker)


async def _to_thread(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


class AIDossierService:
    """AI Context & Prompt Generation Engine for LLM workflows."""

    def __init__(self):
        pass

    async def get_ai_dossier(
        self,
        ticker: str,
        format: Literal["markdown", "json"] = "markdown",
    ) -> Union[str, Dict[str, Any]]:
        """
        Generate complete AI-ready financial dossier for LLMs (Markdown string or structured JSON).
        """
        norm_ticker = _normalize(ticker)

        def _fetch():
            t = bf.Ticker(norm_ticker)
            return t.to_ai_context(format=format)

        try:
            return await _to_thread(_fetch)
        except Exception as e:
            logger.error(f"Error building AI dossier for {ticker}: {e}")
            raise ValueError(f"Failed to generate AI dossier for {ticker}: {e}")

    async def get_investment_memo_prompt(
        self,
        ticker: str,
        custom_instructions: str = "",
    ) -> str:
        """
        Generate a ready-to-run initiation coverage investment memo prompt for LLMs.
        """
        norm_ticker = _normalize(ticker)

        def _fetch():
            t = bf.Ticker(norm_ticker)
            return t.to_investment_memo_prompt(custom_instructions=custom_instructions)

        try:
            return await _to_thread(_fetch)
        except Exception as e:
            logger.error(f"Error generating investment memo prompt for {ticker}: {e}")
            raise ValueError(f"Failed to create investment memo prompt: {e}")

    async def get_forensic_audit_prompt(self, ticker: str) -> str:
        """
        Generate a forensic accounting audit prompt to detect anomalies and accounting red flags.
        """
        norm_ticker = _normalize(ticker)

        def _fetch():
            t = bf.Ticker(norm_ticker)
            return t.to_forensic_audit_prompt()

        try:
            return await _to_thread(_fetch)
        except Exception as e:
            logger.error(f"Error generating forensic audit prompt for {ticker}: {e}")
            raise ValueError(f"Failed to create forensic audit prompt: {e}")

    async def get_concall_prompt(self, ticker: str) -> str:
        """
        Generate earnings conference call takeaways and forward guidance prompt for LLMs.
        """
        norm_ticker = _normalize(ticker)

        def _fetch():
            t = bf.Ticker(norm_ticker)
            return t.to_concall_analyst_prompt()

        try:
            return await _to_thread(_fetch)
        except Exception as e:
            logger.error(f"Error generating concall prompt for {ticker}: {e}")
            raise ValueError(f"Failed to create concall prompt: {e}")


_ai_dossier_service: Optional[AIDossierService] = None


def get_ai_dossier_service() -> AIDossierService:
    global _ai_dossier_service
    if _ai_dossier_service is None:
        _ai_dossier_service = AIDossierService()
    return _ai_dossier_service
