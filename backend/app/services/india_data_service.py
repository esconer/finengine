"""
India Market Microstructure, NSE Ingestion, and ADV Liquidity Service
"""

import os
import io
import csv
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc

from app.models.database import (
    NSEBhavcopy,
    NSEInstitutionalFlow,
    NSEBulkBlockDeal,
    NSEShareholdingPattern,
    PortfolioPosition
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

DATA_NSE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "nse")


def compute_amihud_illiquidity(returns: pd.Series, rupee_volume: pd.Series) -> float:
    """
    Compute Amihud (2002) Illiquidity Ratio:
    Average of (|R_t| / RupeeVolume_t) * 1e6.
    Higher values indicate greater price impact per unit of trading volume.
    """
    if returns.empty or rupee_volume.empty:
        return 0.0
    
    valid_mask = (rupee_volume > 0) & (~returns.isna()) & (~rupee_volume.isna())
    if not valid_mask.any():
        return 0.0
    
    r = returns[valid_mask].abs()
    v = rupee_volume[valid_mask]
    ratio = (r / v) * 1e6
    return float(np.nanmean(ratio)) if len(ratio) > 0 else 0.0


def compute_days_to_liquidate(position_value: float, adv_value: float, participation_rate: float = 0.10) -> float:
    """
    Calculate number of trading days required to exit a position given daily volume participation.
    days = position_value / (participation_rate * ADV_value)
    """
    if position_value <= 0 or adv_value <= 0 or participation_rate <= 0:
        return 0.0
    return float(position_value / (participation_rate * adv_value))


class IndiaDataService:
    """Service managing Indian equities microstructure, NSE archives, and liquidity limits"""

    def __init__(self, db: AsyncSession):
        self.db = db
        os.makedirs(DATA_NSE_DIR, exist_ok=True)

    async def ingest_bhavcopy_records(self, records: List[Dict[str, Any]], date_dt: datetime) -> int:
        """
        Idempotently ingest daily NSE bhavcopy records into SQLite database.
        """
        if not records:
            return 0

        # Check existing records for this date
        existing_res = await self.db.execute(
            select(NSEBhavcopy.symbol).where(func.date(NSEBhavcopy.date) == date_dt.date())
        )
        existing_symbols = set(existing_res.scalars().all())

        new_entities = []
        for rec in records:
            symbol = str(rec.get("symbol", "")).upper().strip()
            if not symbol or symbol in existing_symbols:
                continue

            entity = NSEBhavcopy(
                symbol=symbol,
                date=date_dt,
                series=rec.get("series", "EQ"),
                open=float(rec.get("open", 0.0)),
                high=float(rec.get("high", 0.0)),
                low=float(rec.get("low", 0.0)),
                close=float(rec.get("close", 0.0)),
                prev_close=float(rec.get("prev_close", 0.0)),
                avg_price=float(rec.get("avg_price", rec.get("close", 0.0))),
                ttl_trd_qnty=int(rec.get("ttl_trd_qnty", 0)),
                turnover_lacs=float(rec.get("turnover_lacs", 0.0)),
                no_of_trades=int(rec.get("no_of_trades", 0)),
                deliv_qty=int(rec.get("deliv_qty", 0)) if rec.get("deliv_qty") is not None else None,
                deliv_per=float(rec.get("deliv_per", 0.0)) if rec.get("deliv_per") is not None else None,
            )
            new_entities.append(entity)

        if new_entities:
            self.db.add_all(new_entities)
            await self.db.commit()

        return len(new_entities)

    async def ingest_institutional_flow(
        self, date_dt: datetime, category: str, buy_crores: float, sell_crores: float
    ) -> bool:
        """
        Record FII/DII daily cash market institutional flow.
        """
        category = category.upper().strip()
        existing = await self.db.execute(
            select(NSEInstitutionalFlow).where(
                and_(
                    func.date(NSEInstitutionalFlow.date) == date_dt.date(),
                    NSEInstitutionalFlow.category == category
                )
            )
        )
        flow_record = existing.scalar_one_or_none()
        net_crores = buy_crores - sell_crores

        if flow_record:
            flow_record.buy_value_crores = buy_crores
            flow_record.sell_value_crores = sell_crores
            flow_record.net_value_crores = net_crores
        else:
            flow_record = NSEInstitutionalFlow(
                date=date_dt,
                category=category,
                buy_value_crores=buy_crores,
                sell_value_crores=sell_crores,
                net_value_crores=net_crores,
            )
            self.db.add(flow_record)

        await self.db.commit()
        return True

    async def get_institutional_flows(self, lookback_days: int = 30) -> List[Dict[str, Any]]:
        """
        Retrieve daily FII / DII net cash flows for the last N trading sessions.
        """
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        result = await self.db.execute(
            select(NSEInstitutionalFlow)
            .where(NSEInstitutionalFlow.date >= cutoff)
            .order_by(desc(NSEInstitutionalFlow.date))
        )
        flows = result.scalars().all()

        date_map: Dict[str, Dict[str, Any]] = {}
        for f in flows:
            d_str = f.date.strftime("%Y-%m-%d")
            if d_str not in date_map:
                date_map[d_str] = {"date": d_str, "fii_net_crores": 0.0, "dii_net_crores": 0.0, "total_net_crores": 0.0}
            if f.category == "FII":
                date_map[d_str]["fii_net_crores"] = round(f.net_value_crores, 2)
            elif f.category == "DII":
                date_map[d_str]["dii_net_crores"] = round(f.net_value_crores, 2)
            date_map[d_str]["total_net_crores"] = round(
                date_map[d_str]["fii_net_crores"] + date_map[d_str]["dii_net_crores"], 2
            )

        return sorted(list(date_map.values()), key=lambda x: x["date"])

    async def get_delivery_anomalies(
        self, symbols: List[str], lookback_days: int = 20, sigma_threshold: float = 2.0
    ) -> List[Dict[str, Any]]:
        """
        Detect delivery percentage spikes (> N standard deviations over 20-day mean)
        across specified holdings/watchlists.
        """
        anomalies = []
        cutoff = datetime.utcnow() - timedelta(days=lookback_days * 2)

        for sym in symbols:
            clean_sym = sym.replace(".NS", "").replace(".BO", "").upper().strip()
            res = await self.db.execute(
                select(NSEBhavcopy)
                .where(and_(NSEBhavcopy.symbol == clean_sym, NSEBhavcopy.date >= cutoff))
                .order_by(desc(NSEBhavcopy.date))
            )
            rows = res.scalars().all()
            if not rows or len(rows) < 3:
                continue

            deliv_series = [r.deliv_per for r in rows if r.deliv_per is not None]
            if len(deliv_series) < 3:
                continue

            current_deliv = deliv_series[0]
            historical_deliv = deliv_series[1 : lookback_days + 1]
            if not historical_deliv:
                continue

            mean_deliv = float(np.mean(historical_deliv))
            std_deliv = float(np.std(historical_deliv)) or 1.0
            z_score = float((current_deliv - mean_deliv) / std_deliv)

            is_anomaly = bool(z_score >= sigma_threshold)
            anomalies.append({
                "symbol": clean_sym,
                "current_delivery_pct": round(current_deliv, 2),
                "avg_20d_delivery_pct": round(mean_deliv, 2),
                "delivery_std_pct": round(std_deliv, 2),
                "z_score": round(z_score, 2),
                "is_anomaly": is_anomaly,
                "signal": "ACCUMULATION_SPIKE" if is_anomaly else "NORMAL",
                "last_price": rows[0].close,
                "turnover_lacs": rows[0].turnover_lacs,
            })

        return anomalies

    async def calculate_portfolio_liquidity_limits(
        self,
        positions: List[PortfolioPosition],
        price_history: Dict[str, pd.DataFrame],
        participation_rates: List[float] = [0.10, 0.20],
    ) -> Dict[str, Any]:
        """
        Compute participation-based liquidation limits, days-to-liquidate @ 10% & 20% ADV,
        and Amihud illiquidity ratios per holding and for the aggregate portfolio.
        """
        position_limits = []
        total_port_val = sum(
            (p.market_value if (p.market_value and p.market_value > 0) else (p.quantity or 0) * (p.last_price or 0))
            for p in positions
        )

        weighted_amihud = 0.0
        weighted_days_10 = 0.0
        weighted_days_20 = 0.0

        for p in positions:
            pos_val = (
                p.market_value if (p.market_value and p.market_value > 0) else (p.quantity or 0) * (p.last_price or 0)
            )
            w = (pos_val / total_port_val) if total_port_val > 0 else (1.0 / len(positions) if positions else 0.0)

            df = price_history.get(p.ticker)
            if df is None or df.empty:
                df = price_history.get(p.ticker.replace(".NS", ""))

            if df is not None and not df.empty and "volume" in [c.lower() for c in df.columns]:
                vol_col = next(c for c in df.columns if c.lower() == "volume")
                close_col = next(c for c in df.columns if c.lower() in ["close", "adj_close"])

                close_s = pd.to_numeric(df[close_col], errors="coerce").ffill()
                vol_s = pd.to_numeric(df[vol_col], errors="coerce").fillna(0.0)
                rupee_vol = close_s * vol_s

                adv_shares = float(vol_s.tail(30).mean()) or 10000.0
                adv_rupees = float(rupee_vol.tail(30).mean()) or (adv_shares * (p.last_price or 100.0))
                ret_s = close_s.pct_change().dropna()
                amihud = compute_amihud_illiquidity(ret_s, rupee_vol)
            else:
                adv_shares = 50000.0
                adv_rupees = adv_shares * (p.last_price or 100.0)
                amihud = 0.05

            days_10 = compute_days_to_liquidate(pos_val, adv_rupees, 0.10)
            days_20 = compute_days_to_liquidate(pos_val, adv_rupees, 0.20)
            max_sane_pos_value = round(adv_rupees * 0.05, 2)  # 5% ADV max position rule

            weighted_amihud += w * amihud
            weighted_days_10 += w * days_10
            weighted_days_20 += w * days_20

            # Classification
            if days_10 <= 1.0:
                tier = "HIGHLY_LIQUID"
            elif days_10 <= 5.0:
                tier = "MODERATE_LIQUIDITY"
            else:
                tier = "ILLIQUID_TAIL"

            position_limits.append({
                "ticker": p.ticker,
                "position_value": round(pos_val, 2),
                "weight": round(w, 4),
                "adv_30d_shares": round(adv_shares, 0),
                "adv_30d_rupees": round(adv_rupees, 2),
                "days_to_liquidate_10pct_adv": round(days_10, 2),
                "days_to_liquidate_20pct_adv": round(days_20, 2),
                "amihud_illiquidity": round(amihud, 6),
                "max_sane_position_value": max_sane_pos_value,
                "liquidity_tier": tier,
                "is_oversized_vs_adv": bool(pos_val > max_sane_pos_value),
            })

        return {
            "portfolio_value": round(total_port_val, 2),
            "portfolio_weighted_days_to_liquidate_10pct": round(weighted_days_10, 2),
            "portfolio_weighted_days_to_liquidate_20pct": round(weighted_days_20, 2),
            "portfolio_amihud_score": round(weighted_amihud, 6),
            "positions": position_limits,
        }
