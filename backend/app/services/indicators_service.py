"""
Technical indicator engine for Daisy Risk Engine.

Adapted from TauricResearch/TradingAgents, tradingagents/dataflows/stockstats_utils.py,
market_data_validator.py and y_finance.py
(Apache License 2.0, Copyright Tauric Research).

Modifications from the original:
- consumes this project's SQLite-backed DataService cache instead of per-symbol CSV files
- async service surface; CPU-bound stockstats work offloaded to a worker thread
- Indian ticker normalization inherited from DataService (.NS/.BO suffixing)
- indicator catalogue trimmed to the curated set the dashboard consumes

Licensed under the Apache License, Version 2.0.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.services.data_service import DataService
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# A vendor's latest OHLCV row this many calendar days before the requested date
# is treated as stale (TradingAgents MAX_OHLCV_STALE_DAYS).
MAX_STALE_DAYS = 10

# Curated indicator catalogue with usage guidance (TradingAgents best_ind_params).
SUPPORTED_INDICATORS: Dict[str, str] = {
    "close_50_sma": "50 SMA: medium-term trend direction; dynamic support/resistance. Lags price.",
    "close_200_sma": "200 SMA: long-term trend benchmark; golden/death cross setups.",
    "close_10_ema": "10 EMA: responsive short-term momentum; prone to noise in choppy markets.",
    "macd": "MACD: momentum via EMA differences; watch crossovers/divergence.",
    "macds": "MACD Signal: EMA smoothing of MACD line; crossovers trigger trades.",
    "macdh": "MACD Histogram: gap between MACD and signal; early divergence spotting.",
    "rsi": "RSI: momentum; 70/30 overbought/oversold thresholds.",
    "boll": "Bollinger Middle: 20 SMA basis of Bollinger Bands.",
    "boll_ub": "Bollinger Upper Band: ~2 std above middle; overbought/breakout zone.",
    "boll_lb": "Bollinger Lower Band: ~2 std below middle; oversold/reversal zone.",
    "atr": "ATR: average true range volatility; stop-loss sizing input.",
    "vwma": "VWMA: volume-weighted moving average; confirms trends with volume.",
    "mfi": "MFI: Money Flow Index; >80 overbought / <20 oversold using volume.",
}

DEFAULT_INDICATORS: tuple = (
    "close_10_ema", "close_50_sma", "close_200_sma",
    "rsi", "boll", "boll_ub", "boll_lb",
    "macd", "macds", "macdh", "atr",
)


class StaleMarketDataError(Exception):
    """Raised when cached OHLCV's latest row is far older than the requested date."""


# Our DataService stores lowercase columns (yfinance raw is Title-case);
# stockstats requires Date/Open/High/Low/Close/Volume.
_COLUMN_MAP = {
    "date": "Date", "open": "Open", "high": "High",
    "low": "Low", "close": "Close", "volume": "Volume", "adj_close": "Adj Close",
}


def _ensure_date_column(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize to stockstats' expected schema: Date + Title-case OHLCV."""
    data = data.rename(columns={k: v for k, v in _COLUMN_MAP.items() if k in data.columns})
    if "Date" in data.columns:
        return data
    # Cache-hit path returns dates as the index instead of a column.
    out = data.reset_index()
    for candidate in ("date", "index", "Datetime"):
        if candidate in out.columns:
            return out.rename(columns={candidate: "Date"})
    # Index under any other name (e.g. "timestamp"): after reset_index the
    # first column holds the date axis — rename it rather than KeyError on
    # data["Date"] downstream.
    return out.rename(columns={out.columns[0]: "Date"})


def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    """Parse dates and coerce numerics while preserving the price time axis."""
    data = _ensure_date_column(data)
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])

    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    # Preserve genuine missing observations.  Dropping a missing Close row
    # would compress the time axis and make the next observation look adjacent
    # to the prior one; filling it would invent a price instead.
    return data


def assert_not_stale(data: pd.DataFrame, end_date: str) -> None:
    """Reject frames whose latest row is much older than the requested end date.

    Guards against serving year-old cached frames to indicators (a silent
    wrong-numbers failure mode identified by TradingAgents issue #1021).
    """
    if data is None or data.empty or "Date" not in data.columns:
        return
    requested = pd.to_datetime(end_date, errors="coerce")
    if pd.isna(requested):
        return
    latest = data["Date"].max().normalize()
    stale_days = (requested.normalize() - latest).days
    if stale_days > MAX_STALE_DAYS:
        raise StaleMarketDataError(
            f"Latest row is {latest.date()}, {stale_days} days before requested "
            f"{requested.date()} - refusing to compute indicators on stale data"
        )


def _compute_sync(df: pd.DataFrame, indicators: List[str]) -> pd.DataFrame:
    """Run stockstats computations; return original schema + indicator columns.

    stockstats' ``wrap()`` may lowercase base columns internally, so we never
    read prices back from the wrapped frame - we take indicator series
    positionally and merge onto our own normalized OHLCV.
    """
    from stockstats import wrap

    stock_df = wrap(df.copy())
    computed = {}
    for ind in indicators:
        _ = stock_df[ind]  # attribute access triggers lazy calculation
        computed[ind] = pd.to_numeric(stock_df[ind], errors="coerce").to_numpy()

    base_cols = [c for c in ["Date", "Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    out = df[base_cols].reset_index(drop=True).copy()
    if len(stock_df) != len(out):
        raise ValueError("stockstats returned a different number of rows than input")
    required_inputs = {
        "close_10_ema": ("Close",),
        "close_50_sma": ("Close",),
        "close_200_sma": ("Close",),
        "rsi": ("Close",),
        "boll": ("Close",),
        "boll_ub": ("Close",),
        "boll_lb": ("Close",),
        "macd": ("Close",),
        "macds": ("Close",),
        "macdh": ("Close",),
        "atr": ("High", "Low", "Close"),
        "vwma": ("Close", "Volume"),
        "mfi": ("High", "Low", "Close", "Volume"),
    }
    for ind, values in computed.items():
        # The installed stockstats implementation exposes MFI as a
        # positive/(positive+negative) fraction, while this service's public
        # contract documents the conventional 0–100 oscillator (>80/<20).
        # Convert at the adapter boundary rather than exposing two scales.
        if ind == "mfi":
            values = values * 100.0
        values = np.asarray(values, dtype=float).copy()
        needed = [column for column in required_inputs.get(ind, ()) if column in df.columns]
        if needed:
            invalid_inputs = df[needed].isna().any(axis=1).to_numpy(copy=True)
            if ind == "mfi":
                price_columns = [
                    column for column in ("Open", "High", "Low", "Close")
                    if column in df.columns
                ]
                prices = df[price_columns].to_numpy(dtype=float)
                invalid_prices = (
                    ~np.isfinite(prices).all(axis=1)
                    | (prices <= 0).any(axis=1)
                )
                invalid_inputs |= invalid_prices
            values[invalid_inputs] = np.nan
        out[ind] = values
    return out


class IndicatorsService:
    """Compute technical indicators on top of the shared market-data cache."""

    def __init__(self, db_session):
        self.data_service = DataService(db_session)

    def _resolve_dates(self, lookback_days: int, end_date: Optional[str]):
        # Fetch warmup in CALENDAR days (floor 365 ≈ 240+ trading rows even
        # after NSE holidays) so long-window indicators like close_200_sma
        # have enough history even when lookback_days itself is short.
        end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else datetime.now()
        start = end - timedelta(days=max(int(lookback_days * 1.6) + 120, 365))
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    async def compute_window(
        self,
        ticker: str,
        indicators: Optional[List[str]] = None,
        lookback_days: int = 90,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Compute indicator series over a window ending at end_date (default today).
        Returns records of [{date, close, <indicator>...}], plus metadata.
        """
        requested = [i.strip() for i in (indicators or list(DEFAULT_INDICATORS)) if i.strip()]
        unknown = [i for i in requested if i not in SUPPORTED_INDICATORS]
        if unknown:
            raise ValueError(f"Unsupported indicators: {unknown}. Choose from {list(SUPPORTED_INDICATORS)}")

        start, end = self._resolve_dates(lookback_days, end_date)
        raw = await self.data_service.fetch_historical_data(ticker, start, end)
        if raw is None or raw.empty:
            raise ValueError(f"No OHLCV data available for {ticker}")

        df = _clean_dataframe(raw)
        df = df[df["Date"] <= pd.to_datetime(end)]
        assert_not_stale(df, end)

        stock_df = await asyncio.to_thread(_compute_sync, df, requested)

        cutoff = pd.Timestamp(end) - pd.Timedelta(days=lookback_days)
        out_df = stock_df[stock_df["Date"] >= cutoff]

        records = []
        for _, row in out_df.iterrows():
            close_value = row.get("Close")
            entry: Dict[str, Any] = {
                "date": row["Date"].strftime("%Y-%m-%d"),
                "close": None if pd.isna(close_value) else round(float(close_value), 2),
            }
            for ind in requested:
                val = row.get(ind)
                entry[ind] = None if pd.isna(val) else round(float(val), 4)
            records.append(entry)

        return {
            "ticker": ticker.upper(),
            "indicators": requested,
            "descriptions": {i: SUPPORTED_INDICATORS[i] for i in requested},
            "window": {"start": cutoff.strftime("%Y-%m-%d"), "end": end},
            "records": records,
        }

    async def verified_snapshot(
        self,
        ticker: str,
        end_date: Optional[str] = None,
        look_back_days: int = 30,
    ) -> Dict[str, Any]:
        """
        Deterministic ground-truth snapshot (TradingAgents build_verified_market_snapshot):
        latest verified OHLCV row + default indicator values + recent closes. No estimates.
        """
        # Output window must hold at least look_back_days trading rows
        # (2 calendar days per trading day + floor); indicator warmup inside
        # compute_window is handled by _resolve_dates' 365-day fetch floor.
        _, end = self._resolve_dates(0, end_date)
        result = await self.compute_window(
            ticker,
            list(DEFAULT_INDICATORS),
            lookback_days=max(look_back_days * 2, 60),
            end_date=end,
        )
        records = result["records"]
        if not records:
            raise ValueError(f"No verified rows for {ticker}")

        latest = records[-1]
        recent = [
            {"date": r["date"], "close": r["close"]} for r in records[-look_back_days:]
        ]
        return {
            "ticker": result["ticker"],
            "snapshot_date": latest["date"],
            "latest_row": latest,
            "recent_closes": recent,
            "note": (
                "Deterministic snapshot computed from cached OHLCV. Treat these exact "
                "numbers as source of truth; flag any conflicting tool output instead "
                "of reconciling."
            ),
        }
