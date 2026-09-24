"""India market microstructure, NSE ingestion, and measured liquidity services."""

import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy import and_, desc, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import NSEBhavcopy, NSEInstitutionalFlow, PortfolioPosition
from app.services.cache_service import (
    ProviderInvalidInputError,
    ProviderUnavailableError,
    cache_generation_is_current,
    get_cache_generation,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

DATA_NSE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "nse")

# These are the fields that cannot be inferred safely from a bhavcopy row.
BHAV_REQUIRED_FIELDS = (
    "symbol", "open", "high", "low", "close", "prev_close",
    "avg_price", "ttl_trd_qnty", "turnover_lacs", "no_of_trades",
)


def compute_amihud_illiquidity(returns: pd.Series, rupee_volume: pd.Series) -> Optional[float]:
    """Return measured Amihud illiquidity, or ``None`` without valid history."""
    if returns is None or rupee_volume is None or returns.empty or rupee_volume.empty:
        return None
    aligned = pd.concat(
        [pd.to_numeric(returns, errors="coerce"), pd.to_numeric(rupee_volume, errors="coerce")],
        axis=1,
    ).dropna()
    if aligned.empty:
        return None
    aligned.columns = ["return", "rupee_volume"]
    valid = aligned[(aligned["rupee_volume"] > 0) & np.isfinite(aligned["return"])]
    if valid.empty:
        return None
    ratio = valid["return"].abs() / valid["rupee_volume"] * 1e6
    ratio = ratio[np.isfinite(ratio)]
    return float(ratio.mean()) if not ratio.empty else None


def compute_days_to_liquidate(
    position_value: float, adv_value: float, participation_rate: float = 0.10
) -> Optional[float]:
    """Return measured liquidation days, or ``None`` when ADV is unavailable."""
    if position_value < 0 or adv_value is None or adv_value <= 0 or participation_rate <= 0:
        return None
    if position_value == 0:
        return 0.0
    result = float(position_value / (participation_rate * adv_value))
    return result if math.isfinite(result) else None


def _naive_date(value: datetime) -> datetime:
    return datetime(value.year, value.month, value.day)


def _finite_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class IndiaDataService:
    """Service managing Indian microstructure, NSE archives, and liquidity limits."""

    def __init__(self, db: AsyncSession):
        self.db = db
        os.makedirs(DATA_NSE_DIR, exist_ok=True)

    def _normalize_bhav_record(self, record: Dict[str, Any], date_dt: datetime) -> Optional[Dict[str, Any]]:
        missing = [field for field in BHAV_REQUIRED_FIELDS if field not in record or record[field] is None]
        if missing:
            logger.warning("Rejecting bhavcopy row with missing fields: %s", ",".join(missing))
            return None
        symbol = str(record.get("symbol", "")).upper().strip()
        if not symbol:
            return None
        numbers = {field: _finite_number(record.get(field)) for field in BHAV_REQUIRED_FIELDS if field != "symbol"}
        if any(value is None for value in numbers.values()) or any(value < 0 for value in numbers.values()):
            logger.warning("Rejecting non-finite/negative bhavcopy row for %s", symbol)
            return None
        if numbers["high"] < max(numbers["open"], numbers["close"], numbers["low"]):
            return None
        if numbers["low"] > min(numbers["open"], numbers["close"], numbers["high"]):
            return None
        if any(numbers[field] <= 0 for field in ("open", "high", "low", "close")):
            return None
        try:
            delivery_qty = None if record.get("deliv_qty") is None else int(record["deliv_qty"])
            delivery_pct = None if record.get("deliv_per") is None else float(record["deliv_per"])
        except (TypeError, ValueError, OverflowError):
            return None
        return {
            "symbol": symbol,
            "date": _naive_date(date_dt),
            "series": str(record.get("series") or "EQ"),
            "open": numbers["open"],
            "high": numbers["high"],
            "low": numbers["low"],
            "close": numbers["close"],
            "prev_close": numbers["prev_close"],
            "avg_price": numbers["avg_price"],
            "ttl_trd_qnty": int(numbers["ttl_trd_qnty"]),
            "turnover_lacs": numbers["turnover_lacs"],
            "no_of_trades": int(numbers["no_of_trades"]),
            "deliv_qty": delivery_qty,
            "deliv_per": delivery_pct,
        }

    async def ingest_bhavcopy_records(self, records: List[Dict[str, Any]], date_dt: datetime) -> int:
        """Validate, deduplicate, and upsert bhavcopy rows; invalid rows are quarantined."""
        if not records:
            return 0
        generation = get_cache_generation()
        # Last input row for a symbol is the correction within this payload.
        unique: Dict[str, Dict[str, Any]] = {}
        for record in records:
            normalized = self._normalize_bhav_record(record or {}, date_dt)
            if normalized is None:
                continue
            unique[normalized["symbol"]] = normalized
        if not unique:
            return 0

        existing_result = await self.db.execute(
            select(NSEBhavcopy).where(
                NSEBhavcopy.date == _naive_date(date_dt),
                NSEBhavcopy.symbol.in_(tuple(unique)),
            )
        )
        existing = {row.symbol: row for row in existing_result.scalars().all()}
        changed: List[Dict[str, Any]] = []
        for symbol, values in unique.items():
            prior = existing.get(symbol)
            if prior is not None and all(
                getattr(prior, field) == values[field]
                for field in (
                    "series", "open", "high", "low", "close", "prev_close", "avg_price",
                    "ttl_trd_qnty", "turnover_lacs", "no_of_trades", "deliv_qty", "deliv_per",
                )
            ):
                continue
            changed.append(values)
        if not changed:
            return 0

        stmt = sqlite_insert(NSEBhavcopy.__table__).values(changed)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "date"],
            set_={
                field: stmt.excluded[field]
                for field in (
                    "series", "open", "high", "low", "close", "prev_close", "avg_price",
                    "ttl_trd_qnty", "turnover_lacs", "no_of_trades", "deliv_qty", "deliv_per",
                )
            },
        )
        try:
            await self.db.execute(stmt)
            if not cache_generation_is_current(generation):
                await self.db.rollback()
                return 0
            await self.db.commit()
            return len(changed)
        except IntegrityError:
            # A race on one natural key must not discard other valid rows.
            await self.db.rollback()
            applied = 0
            for values in changed:
                try:
                    one = sqlite_insert(NSEBhavcopy.__table__).values(**values)
                    one = one.on_conflict_do_update(
                        index_elements=["symbol", "date"],
                        set_={field: one.excluded[field] for field in (
                            "series", "open", "high", "low", "close", "prev_close", "avg_price",
                            "ttl_trd_qnty", "turnover_lacs", "no_of_trades", "deliv_qty", "deliv_per",
                        )},
                    )
                    await self.db.execute(one)
                    await self.db.commit()
                    applied += 1
                except IntegrityError:
                    await self.db.rollback()
            return applied
        except Exception as exc:
            await self.db.rollback()
            raise ProviderUnavailableError("Bhavcopy persistence failed", provider="india_data") from exc

    async def ingest_institutional_flow(
        self, date_dt: datetime, category: str, buy_crores: float, sell_crores: float
    ) -> bool:
        """Upsert one FII/DII flow row, including same-day corrections."""
        if not category or not str(category).strip():
            return False
        category = str(category).upper().strip()
        buy = _finite_number(buy_crores)
        sell = _finite_number(sell_crores)
        if buy is None or sell is None or buy < 0 or sell < 0:
            raise ProviderInvalidInputError("FII/DII values must be finite and non-negative", provider="india_data")
        values = {
            "date": _naive_date(date_dt),
            "category": category,
            "buy_value_crores": buy,
            "sell_value_crores": sell,
            "net_value_crores": buy - sell,
        }
        generation = get_cache_generation()
        stmt = sqlite_insert(NSEInstitutionalFlow.__table__).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["date", "category"],
            set_={
                "buy_value_crores": stmt.excluded.buy_value_crores,
                "sell_value_crores": stmt.excluded.sell_value_crores,
                "net_value_crores": stmt.excluded.net_value_crores,
            },
        )
        try:
            # Read first for legacy schemas and deterministic correction behavior;
            # the write still uses ON CONFLICT so concurrent inserts are safe.
            prior_result = await self.db.execute(
                select(NSEInstitutionalFlow).where(
                    NSEInstitutionalFlow.date == values["date"],
                    NSEInstitutionalFlow.category == category,
                )
            )
            prior = prior_result.scalar_one_or_none()
            if prior is not None:
                prior.buy_value_crores = buy
                prior.sell_value_crores = sell
                prior.net_value_crores = buy - sell
                if not cache_generation_is_current(generation):
                    await self.db.rollback()
                    return False
                await self.db.commit()
                return True
            await self.db.execute(stmt)
            # A racer may have won between the read and write.  Re-read and
            # apply the correction rather than returning a phantom success.
            winner_result = await self.db.execute(
                select(NSEInstitutionalFlow).where(
                    NSEInstitutionalFlow.date == values["date"],
                    NSEInstitutionalFlow.category == category,
                )
            )
            winner = winner_result.scalar_one_or_none()
            if winner is not None:
                winner.buy_value_crores = buy
                winner.sell_value_crores = sell
                winner.net_value_crores = buy - sell
            if not cache_generation_is_current(generation):
                await self.db.rollback()
                return False
            await self.db.commit()
            return True
        except IntegrityError:
            await self.db.rollback()
            # Compatibility recovery for legacy schemas without the unique index.
            result = await self.db.execute(
                select(NSEInstitutionalFlow).where(
                    NSEInstitutionalFlow.date == values["date"],
                    NSEInstitutionalFlow.category == category,
                )
            )
            record = result.scalar_one_or_none()
            if record is None:
                return False
            record.buy_value_crores = buy
            record.sell_value_crores = sell
            record.net_value_crores = buy - sell
            try:
                await self.db.commit()
                return True
            except Exception:
                await self.db.rollback()
                return False
        except Exception as exc:
            await self.db.rollback()
            raise ProviderUnavailableError("Institutional-flow persistence failed", provider="india_data") from exc

    async def get_institutional_flows(self, lookback_days: int = 30) -> List[Dict[str, Any]]:
        """Return the latest N stored trading sessions, not N calendar days."""
        if not isinstance(lookback_days, int) or isinstance(lookback_days, bool) or lookback_days < 1:
            raise ProviderInvalidInputError("lookback_days must be a positive integer", provider="india_data")
        result = await self.db.execute(
            select(NSEInstitutionalFlow).order_by(desc(NSEInstitutionalFlow.date))
        )
        flows = result.scalars().all()
        date_map: Dict[str, Dict[str, Any]] = {}
        for flow in flows:
            day = flow.date.strftime("%Y-%m-%d")
            if day not in date_map and len(date_map) >= lookback_days:
                break
            item = date_map.setdefault(
                day, {"date": day, "fii_net_crores": 0.0, "dii_net_crores": 0.0, "total_net_crores": 0.0}
            )
            if flow.category == "FII":
                item["fii_net_crores"] = round(flow.net_value_crores, 2)
            elif flow.category == "DII":
                item["dii_net_crores"] = round(flow.net_value_crores, 2)
            item["total_net_crores"] = round(item["fii_net_crores"] + item["dii_net_crores"], 2)
        return sorted(date_map.values(), key=lambda item: item["date"])

    async def get_delivery_anomalies(
        self, symbols: List[str], lookback_days: int = 20, sigma_threshold: float = 2.0
    ) -> List[Dict[str, Any]]:
        anomalies = []
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=lookback_days * 2)
        for symbol in symbols:
            clean_symbol = str(symbol).replace(".NS", "").replace(".BO", "").upper().strip()
            result = await self.db.execute(
                select(NSEBhavcopy)
                .where(and_(NSEBhavcopy.symbol == clean_symbol, NSEBhavcopy.date >= cutoff))
                .order_by(desc(NSEBhavcopy.date))
            )
            rows = result.scalars().all()
            if len(rows) < 3:
                continue
            delivery = [row.deliv_per for row in rows if row.deliv_per is not None]
            if len(delivery) < 3:
                continue
            current = delivery[0]
            historical = delivery[1: lookback_days + 1]
            mean = float(np.mean(historical))
            std = float(np.std(historical))
            if not math.isfinite(std) or std <= 0:
                continue
            z_score = (current - mean) / std
            is_anomaly = bool(z_score >= sigma_threshold)
            anomalies.append({
                "symbol": clean_symbol,
                "current_delivery_pct": round(current, 2),
                "avg_20d_delivery_pct": round(mean, 2),
                "delivery_std_pct": round(std, 2),
                "z_score": round(z_score, 2),
                "is_anomaly": is_anomaly,
                "signal": "ACCUMULATION_SPIKE" if is_anomaly else "NORMAL",
                "last_price": rows[0].close,
                "turnover_lacs": rows[0].turnover_lacs,
            })
        return anomalies

    @staticmethod
    def _find_frame(price_history: Dict[str, pd.DataFrame], ticker: str) -> Optional[pd.DataFrame]:
        for key in (ticker, str(ticker).upper(), str(ticker).replace(".NS", ""), str(ticker).replace(".BO", "")):
            frame = price_history.get(key)
            if frame is not None and not frame.empty:
                return frame
        return None

    async def calculate_portfolio_liquidity_limits(
        self,
        positions: List[PortfolioPosition],
        price_history: Dict[str, pd.DataFrame],
        *,
        converted_values: Optional[Dict[str, float]] = None,
        fx_rates: Optional[Dict[str, float]] = None,
        base_currency: str = "INR",
        currency_provenance: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Compute measured ADV/liquidation/Amihud values in one base currency."""
        position_limits: List[Dict[str, Any]] = []
        converted_values = converted_values or {}
        fx_rates = fx_rates or {}
        base_currency = str(base_currency or "INR").upper()
        currency_provenance = currency_provenance or {
            "aggregation": "native_uniform",
            "base_currency": base_currency,
        }

        def position_values(position: PortfolioPosition) -> tuple[float, float, float, str]:
            native_value = float(
                position.market_value
                if position.market_value and position.market_value > 0
                else (position.quantity or 0) * (position.last_price or 0)
            )
            base_value = float(converted_values.get(position.ticker, native_value))
            rate = float(fx_rates.get(position.ticker, 1.0) or 1.0)
            ticker = str(position.ticker or "").upper()
            region = str(getattr(position, "region", "") or "").upper()
            native_currency = "INR" if ticker.endswith((".NS", ".BO")) or region in {
                "IN", "IND", "INDIA", "INR"
            } else "USD"
            return native_value, base_value, rate, native_currency

        total_value = sum(position_values(position)[1] for position in positions)
        weighted_amihud: Optional[float] = 0.0
        weighted_days_10: Optional[float] = 0.0
        weighted_days_20: Optional[float] = 0.0
        all_available = True

        for position in positions:
            native_value, position_value, fx_rate, native_currency = position_values(position)
            weight = position_value / total_value if total_value > 0 else (1.0 / len(positions) if positions else 0.0)
            frame = self._find_frame(price_history, position.ticker)
            volume_col = close_col = None
            if frame is not None:
                volume_col = next((column for column in frame.columns if str(column).lower() == "volume"), None)
                close_col = next((column for column in frame.columns if str(column).lower() in ("close", "adj_close")), None)

            adv_shares = adv_rupees = amihud = days_10 = days_20 = None
            data_status = "unavailable"
            if volume_col and close_col:
                close_series = pd.to_numeric(frame[close_col], errors="coerce")
                volume_series = pd.to_numeric(frame[volume_col], errors="coerce")
                rupee_volume = close_series * volume_series * fx_rate
                measured_volume = volume_series.replace([np.inf, -np.inf], np.nan).dropna()
                measured_rupee = rupee_volume.replace([np.inf, -np.inf], np.nan).dropna()
                if not measured_volume.empty and not measured_rupee.empty:
                    candidate_adv_shares = float(measured_volume.tail(30).mean())
                    candidate_adv_rupees = float(measured_rupee.tail(30).mean())
                    if candidate_adv_shares > 0 and candidate_adv_rupees > 0:
                        adv_shares = candidate_adv_shares
                        adv_rupees = candidate_adv_rupees
                        returns = close_series.pct_change(fill_method=None).dropna()
                        amihud = compute_amihud_illiquidity(returns, rupee_volume)
                        days_10 = compute_days_to_liquidate(position_value, adv_rupees, 0.10)
                        days_20 = compute_days_to_liquidate(position_value, adv_rupees, 0.20)
                        data_status = "measured" if amihud is not None and days_10 is not None else "partial"
            if days_10 is None or adv_rupees is None:
                all_available = False
            else:
                weighted_days_10 = (weighted_days_10 or 0.0) + weight * days_10
                weighted_days_20 = (weighted_days_20 or 0.0) + weight * (days_20 or 0.0)
            if amihud is not None:
                weighted_amihud = (weighted_amihud or 0.0) + weight * amihud
            else:
                all_available = False

            if days_10 is None or adv_rupees is None:
                tier = "UNAVAILABLE"
                max_position = None
                oversized = None
            else:
                tier = "HIGHLY_LIQUID" if days_10 <= 1 else "MODERATE_LIQUIDITY" if days_10 <= 5 else "ILLIQUID_TAIL"
                max_position = round(adv_rupees * 0.05, 2)
                oversized = bool(position_value > max_position)
            position_limits.append({
                "ticker": position.ticker,
                "position_value": round(position_value, 2),
                "position_value_native": round(native_value, 2),
                "native_currency": native_currency,
                "base_currency": base_currency,
                "fx_rate": fx_rate,
                "weight": round(weight, 4),
                "adv_30d_shares": None if adv_shares is None else round(adv_shares, 0),
                "adv_30d_rupees": None if adv_rupees is None else round(adv_rupees, 2),
                "days_to_liquidate_10pct_adv": None if days_10 is None else round(days_10, 2),
                "days_to_liquidate_20pct_adv": None if days_20 is None else round(days_20, 2),
                "amihud_illiquidity": None if amihud is None else round(amihud, 6),
                "max_sane_position_value": max_position,
                "liquidity_tier": tier,
                "is_oversized_vs_adv": oversized,
                "data_status": data_status,
            })

        return {
            "portfolio_value": round(total_value, 2),
            "currency": base_currency,
            "base_currency": base_currency,
            "currency_provenance": currency_provenance,
            "portfolio_weighted_days_to_liquidate_10pct": None if not all_available else round(weighted_days_10 or 0.0, 2),
            "portfolio_weighted_days_to_liquidate_20pct": None if not all_available else round(weighted_days_20 or 0.0, 2),
            "portfolio_amihud_score": None if not all_available else round(weighted_amihud or 0.0, 6),
            "data_status": "measured" if all_available else "unavailable",
            "positions": position_limits,
        }
