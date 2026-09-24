"""Coordinator integration oracle for the backend remediation.

Deterministic, no-network checks for seams that crossed A/B/C ownership.
Run from the repository root with:
  uv run --project backend python .scratch/backend-deep-audit/fixes/evidence/agent-coordinator-integration.py
"""
from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import pandas as pd

# Make the script runnable directly from a checkout without installing a package.
REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "backend"))

from app.api.analytics import _build_wide_returns, get_cointegration_pairs  # noqa: E402
from app.api.data import _frame_source_for_window, _raise_provider_http_error  # noqa: E402
from app.api.websocket import _trusted_websocket  # noqa: E402
from app.models.schemas import EVTPOTVarMetrics  # noqa: E402
from app.services.cache_service import ProviderUnavailableError  # noqa: E402
from app.services.currency_service import CurrencyConversionService  # noqa: E402
from app.services.india_data_service import IndiaDataService, compute_days_to_liquidate  # noqa: E402
from app.services.data_service import DataService  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str) -> None:
    RESULTS.append((name, bool(condition), detail))
    print(f"{'PASS' if condition else 'FAIL'} {name}: {detail}")


async def active_returns_check() -> None:
    dates = pd.date_range("2025-01-01", periods=4, freq="D")
    service = SimpleNamespace()

    async def fetch(ticker, _start, _end):
        if ticker == "A":
            return pd.DataFrame({"close": [100.0, 110.0, 120.0, 121.0]}, index=dates)
        return pd.DataFrame({"close": [50.0, 55.0]}, index=dates[2:])

    service.fetch_historical_data = fetch
    frame, portfolio, _coverage = await _build_wide_returns(
        ["A", "B"], {"A": 0.5, "B": 0.5}, "2025-01-01", "2025-01-04", service
    )
    expected = [0.10, 120.0 / 110.0 - 1.0, 0.5 * (121.0 / 120.0 - 1.0) + 0.5 * 0.10]
    ok = (
        pd.isna(frame.loc[dates[1], "B"])
        and np.allclose(portfolio.to_numpy(), expected)
        and len(portfolio) == 3
    )
    check("A-02 API active returns", ok, f"active_dates={len(portfolio)} values={portfolio.round(8).tolist()}")


async def coint_lookback_check() -> None:
    dates = pd.date_range("2025-01-01", periods=80, freq="B")
    market = SimpleNamespace()

    async def fetch(_ticker, _start, _end):
        return pd.DataFrame({"close": np.linspace(100.0, 120.0, len(dates))}, index=dates)

    market.fetch_historical_data = fetch
    captured: dict = {}

    class FakeScanner:
        def __init__(self, **_kwargs):
            pass

        async def scan_pairs(self, **kwargs):
            captured.update(kwargs)
            from app.api.analytics import CointScannerResponse
            return CointScannerResponse(
                as_of="2025-04-01", universe_size=2, scanned_pairs_count=1,
                cointegrated_pairs_count=0, pairs=[],
            )

    with patch("app.api.analytics.CointegrationService", FakeScanner):
        await get_cointegration_pairs(
            tickers="A,B", lookback_days=60, p_value_threshold=0.05,
            max_half_life=None, include_spread_series=False,
            db=Mock(), data_service=market, cache_service=Mock(),
        )
    check("A-09 coint lookback identity", captured.get("lookback_days") == 60, f"threaded={captured.get('lookback_days')}")


async def provenance_and_redaction_check() -> None:
    frame = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=2)})
    frame.attrs["source"] = "yfinance"
    source = await _frame_source_for_window(frame, "AAPL", Mock())
    check("B-13 returned-window source", source == "yfinance", f"source={source}")

    try:
        _raise_provider_http_error(
            ProviderUnavailableError("https://provider.invalid/?apikey=DO_NOT_LEAK")
        )
    except Exception as exc:  # HTTPException is intentionally inspected here.
        text = str(exc)
        leaked = "DO_NOT_LEAK" in text or "apikey" in text
        check("B-09/B-14 provider redaction", not leaked, f"status={getattr(exc, 'status_code', None)}")
    else:
        check("B-09/B-14 provider redaction", False, "provider error was not translated")


def tail_schema_check() -> None:
    model = EVTPOTVarMetrics(
        confidence_level=0.95,
        evt_pot_var=-0.02,
        evt_pot_es=-0.03,
        historical_var=-0.015,
        historical_es=-0.02,
        threshold_u=-0.01,
        exceedances_count=5,
        total_observations=100,
        is_fat_tailed=True,
    )
    check("A-11 neutral tail schema", model.evt_pot_var == -0.02 and model.evt_pot_var_99 is None, f"fields={model.model_dump()}")


async def fx_provenance_check() -> None:
    service = CurrencyConversionService()
    with patch("yfinance.Ticker", side_effect=ConnectionError("offline")):
        rate = await service.get_exchange_rate("USD", "INR")
    info = service.get_exchange_rate_info()
    check(
        "B-12 FX provenance",
        float(rate) == 83.0 and rate.is_fallback and info["provenance"] == "fallback",
        f"rate={float(rate)} provenance={info['provenance']} age={info['age_seconds']}",
    )


async def liquidity_check() -> None:
    service = object.__new__(IndiaDataService)
    position = SimpleNamespace(
        ticker="B11.NS", quantity=10.0, buy_price=10.0, last_price=10.0, market_value=100.0,
    )
    result = await service.calculate_portfolio_liquidity_limits([position], {})
    row = result["positions"][0]
    check(
        "B-11 missing liquidity is unavailable",
        row["adv_30d_shares"] is None and row["amihud_illiquidity"] is None,
        f"status={row['data_status']} days={row['days_to_liquidate_10pct_adv']}",
    )
    check("B-11 measured day formula", compute_days_to_liquidate(100.0, 1000.0, 0.1) == 1.0, "100/(0.1*1000)=1")


async def websocket_check() -> None:
    class Headers(dict):
        pass

    socket = SimpleNamespace(headers=Headers({"host": "evil.example", "origin": "https://evil.example"}))
    check("C-04 websocket origin", not _trusted_websocket(socket), "evil origin rejected before accept")


async def main() -> int:
    await active_returns_check()
    await coint_lookback_check()
    await provenance_and_redaction_check()
    tail_schema_check()
    await fx_provenance_check()
    await liquidity_check()
    await websocket_check()
    # Keep the imported service seam explicit in the evidence: its source
    # identifier is part of the returned-window provenance contract.
    check("B source seam present", inspect.isclass(DataService), "DataService imported without network/DB setup")
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"SUMMARY passed={len(RESULTS) - len(failed)} failed={len(failed)}")
    if failed:
        print("FAILED_CHECKS=" + ",".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
