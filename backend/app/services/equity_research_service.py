"""
Equity Research Service for Indian Equities (NSE/BSE).
Powered by bfinance with 10-13 years audited statements, concall audio MP3s,
dual shareholding trends, custom ratios, and 8-tab Excel financial model exporter.
"""

import asyncio
import io
import math
import os
import tempfile
from typing import Any, Dict, List, Optional
import pandas as pd

import bfinance as bf
from app.services.data_service import canonical_ticker
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _normalize(ticker: str) -> str:
    """Normalize ticker to standard Indian format (.NS default)."""
    return canonical_ticker(ticker)


async def _to_thread(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


class EquityResearchService:
    """Comprehensive equity research and financial modeling engine."""

    def __init__(self):
        pass

    async def get_full_profile(self, ticker: str) -> Dict[str, Any]:
        """
        Fetch 360-degree company profile with 4-level taxonomy, live ratios,
        CAGR growth matrix, qualitative pros/cons, and peer comparison.
        """
        norm_ticker = _normalize(ticker)

        def _fetch():
            t = bf.Ticker(norm_ticker)
            profile = t._ensure_profile()
            if not profile or not profile.name:
                raise ValueError(f"No equity profile found for {ticker}")

            r = profile.ratios
            info = getattr(t, "info", {}) or {}

            # Piotroski & Graham calculation
            custom_ratios = getattr(t, "custom_ratios", {}) or {}
            piotroski = custom_ratios.get("piotroski_score") or getattr(t, "piotroski_score", 0)
            graham_num = custom_ratios.get("graham_number") or getattr(t, "graham_number", None)
            
            cmp = r.current_price or info.get("currentPrice") or 0.0
            graham_upside = None
            if graham_num and cmp and cmp > 0:
                graham_upside = round(((graham_num - cmp) / cmp) * 100, 2)

            ev_cr = custom_ratios.get("enterprise_value_cr") or getattr(t, "enterprise_value", None)
            ev_ebitda = custom_ratios.get("ev_to_ebitda") or getattr(t, "ev_to_ebitda", None)
            interest_cov = custom_ratios.get("interest_coverage") or getattr(t, "interest_coverage", None)
            cfo_pat = custom_ratios.get("cfo_to_pat_ratio") or custom_ratios.get("cfo_pat_ratio")

            peers_data = []
            if profile.peers:
                for p in profile.peers:
                    peers_data.append(p.model_dump())

            return {
                "symbol": profile.symbol,
                "ticker": norm_ticker.upper(),
                "name": profile.name,
                "about": profile.about,
                "website": profile.website,
                "bse_code": profile.bse_code,
                "nse_symbol": profile.nse_symbol or profile.symbol,
                "sector": profile.sector,
                "industry_group": profile.industry_group,
                "industry": profile.industry,
                "sub_industry": profile.sub_industry,
                "indices": profile.indices or [],
                "current_price": cmp,
                "market_cap_cr": r.market_cap or info.get("marketCapInCr"),
                "high_52w": r.high_52w or info.get("fiftyTwoWeekHigh"),
                "low_52w": r.low_52w or info.get("fiftyTwoWeekLow"),
                "stock_pe": r.stock_pe or info.get("trailingPE"),
                "book_value": r.book_value or info.get("bookValue"),
                "dividend_yield": r.dividend_yield if r.dividend_yield is not None else info.get("dividendYield"),
                "roce": r.roce or info.get("returnOnCapitalEmployed"),
                "roe": r.roe if r.roe is not None else info.get("returnOnEquity"),
                "face_value": r.face_value,
                "debt_to_equity": r.debt_to_equity or info.get("debtToEquity"),
                "peg_ratio": r.peg_ratio or info.get("pegRatio"),
                "eps_ttm": r.eps_ttm or info.get("trailingEps"),
                "promoter_holding": r.promoter_holding,
                "promoter_pledged": r.promoter_pledged,
                "custom_ratios": {
                    "piotroski_score": piotroski,
                    "graham_number": graham_num,
                    "graham_upside_pct": graham_upside,
                    "enterprise_value_cr": ev_cr,
                    "ev_to_ebitda": ev_ebitda,
                    "interest_coverage": interest_cov,
                    "cfo_to_pat_ratio": cfo_pat,
                },
                "cagrs": profile.cagrs or {},
                "pros": profile.analysis.pros if profile.analysis else [],
                "cons": profile.analysis.cons if profile.analysis else [],
                "peers": peers_data,
                "concall_count": len(profile.concalls),
                "annual_reports": profile.annual_reports or [],
                "credit_ratings": profile.credit_ratings or [],
            }

        try:
            return await _to_thread(_fetch)
        except Exception as e:
            logger.error(f"Error getting full profile for {ticker}: {e}")
            raise ValueError(f"Failed to load research profile for {ticker}: {e}")

    async def get_shareholding(self, ticker: str) -> Dict[str, Any]:
        """
        Get 12-quarter quarterly + 11-year annual institutional shareholding trends
        formatted for Recharts visualization.
        """
        norm_ticker = _normalize(ticker)

        def _fetch():
            t = bf.Ticker(norm_ticker)
            profile = t._ensure_profile()
            if not profile:
                raise ValueError(f"No shareholding data for {ticker}")

            # Quarterly
            q_df = profile.shareholding.to_dataframe(orient="columns")
            q_series = []
            if not q_df.empty:
                for col in q_df.columns:
                    col_str = str(col)[:10]
                    entry: Dict[str, Any] = {"period": col_str}
                    for idx in q_df.index:
                        val = q_df.loc[idx, col]
                        key = str(idx).replace("+", "").strip().lower().replace(" ", "_")
                        try:
                            entry[key] = float(val) if pd.notna(val) else 0.0
                        except (ValueError, TypeError):
                            entry[key] = 0.0
                    q_series.append(entry)

            # Yearly
            y_df = profile.shareholding_yearly.to_dataframe(orient="columns")
            y_series = []
            if not y_df.empty:
                for col in y_df.columns:
                    col_str = str(col)[:10]
                    entry = {"period": col_str}
                    for idx in y_df.index:
                        val = y_df.loc[idx, col]
                        key = str(idx).replace("+", "").strip().lower().replace(" ", "_")
                        try:
                            entry[key] = float(val) if pd.notna(val) else 0.0
                        except (ValueError, TypeError):
                            entry[key] = 0.0
                    y_series.append(entry)

            return {
                "ticker": norm_ticker.upper(),
                "quarterly": {
                    "periods": [str(c)[:10] for c in q_df.columns] if not q_df.empty else [],
                    "rows": profile.shareholding.rows,
                    "chart_series": q_series,
                },
                "yearly": {
                    "periods": [str(c)[:10] for c in y_df.columns] if not y_df.empty else [],
                    "rows": profile.shareholding_yearly.rows,
                    "chart_series": y_series,
                },
            }

        try:
            return await _to_thread(_fetch)
        except Exception as e:
            logger.error(f"Error fetching shareholding for {ticker}: {e}")
            raise ValueError(f"Failed to load shareholding for {ticker}: {e}")

    async def get_concalls(self, ticker: str) -> List[Dict[str, Any]]:
        """
        Fetch 40+ conference calls with BSE transcript PDFs, PPT links, and streamable audio MP3 links.
        """
        norm_ticker = _normalize(ticker)

        def _fetch():
            t = bf.Ticker(norm_ticker)
            profile = t._ensure_profile()
            if not profile or not profile.concalls:
                return []
            return [c.model_dump() for c in profile.concalls]

        try:
            return await _to_thread(_fetch)
        except Exception as e:
            logger.error(f"Error fetching concalls for {ticker}: {e}")
            return []

    async def get_custom_ratios(self, ticker: str) -> Dict[str, Any]:
        """
        Fetch comprehensive forensic & valuation ratios: Piotroski, Graham Number,
        EV/EBITDA, Interest Coverage, CFO/PAT, and historical operating metrics.
        """
        norm_ticker = _normalize(ticker)

        def _fetch():
            t = bf.Ticker(norm_ticker)
            profile = t._ensure_profile()
            if not profile:
                raise ValueError(f"No profile for {ticker}")

            custom = getattr(t, "custom_ratios", {}) or {}
            rh_df = profile.ratios_history.to_dataframe(orient="columns")
            
            cmp = profile.ratios.current_price or 0.0
            graham = custom.get("graham_number")
            graham_upside = None
            if graham and cmp > 0:
                graham_upside = round(((graham - cmp) / cmp) * 100, 2)

            return {
                "ticker": norm_ticker.upper(),
                "piotroski_score": custom.get("piotroski_score") or getattr(t, "piotroski_score", 0),
                "graham_number": graham,
                "graham_upside_pct": graham_upside,
                "enterprise_value_cr": custom.get("enterprise_value_cr") or getattr(t, "enterprise_value", 0.0),
                "ev_to_ebitda": custom.get("ev_to_ebitda") or getattr(t, "ev_to_ebitda", None),
                "interest_coverage": custom.get("interest_coverage") or getattr(t, "interest_coverage", None),
                "cfo_to_pat_ratio": custom.get("cfo_to_pat_ratio") or custom.get("cfo_pat_ratio", None),
                "current_price": cmp,
                "ratios_history": {
                    "periods": [str(c)[:10] for c in rh_df.columns] if not rh_df.empty else [],
                    "rows": profile.ratios_history.rows,
                },
            }

        try:
            return await _to_thread(_fetch)
        except Exception as e:
            logger.error(f"Error fetching custom ratios for {ticker}: {e}")
            raise ValueError(f"Failed to compute custom ratios for {ticker}: {e}")

    async def export_excel_model(self, ticker: str) -> bytes:
        """
        Generate 8-tab Excel financial model workbook (.xlsx) as bytes for download.
        """
        norm_ticker = _normalize(ticker)

        def _generate() -> bytes:
            t = bf.Ticker(norm_ticker)
            profile = t._ensure_profile()
            if not profile or not profile.name:
                raise ValueError(f"Cannot generate financial model for {ticker}")

            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                from bfinance.utils.excel import FinancialModelExcelExporter
                FinancialModelExcelExporter.export(profile, tmp_path)
                with open(tmp_path, "rb") as f:
                    content = f.read()
                return content
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

        try:
            return await _to_thread(_generate)
        except Exception as e:
            logger.error(f"Error generating Excel model for {ticker}: {e}")
            raise ValueError(f"Failed to export Excel model: {e}")


_equity_research_service: Optional[EquityResearchService] = None


def get_equity_research_service() -> EquityResearchService:
    global _equity_research_service
    if _equity_research_service is None:
        _equity_research_service = EquityResearchService()
    return _equity_research_service
