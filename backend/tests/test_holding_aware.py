"""Holding-aware analytics: no pre-purchase attribution, no short-window annualization.

Regression gate for the phantom-history bug (14 positions bulk-imported
7 days ago rendered a -21.2% 'annualized' crisis return over 273 phantom
days while the ledger showed +13.4% realized). No network; seeded only.
"""

import numpy as np
import pandas as pd
import pytest
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock, Mock

from app.api.analytics import (
    _build_wide_returns,
    get_tear_sheet,
    resolve_holdings,
)
from app.models.database import PortfolioPosition
from app.utils.holdings import (
    apply_annualization_gate,
    coerce_holding_date,
    effective_start,
    effective_starts,
    holding_coverage,
    holding_window,
    implied_start_from_price,
    portfolio_regime_summary,
)


def _prices(dates, seed=5, start_price=100.0):
    rng = np.random.default_rng(seed)
    close = start_price * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(dates))))
    return pd.Series(close, index=dates)


def test_effective_start_and_coverage():
    assert effective_start({}) is None
    assert effective_start({"A": None}) is None
    assert effective_start({"A": "2026-08-27", "B": "2024-01-01"}) == "2026-08-27"
    cov = holding_coverage({"A": "2026-08-27"}, "2025-09-03", "2026-09-03", 7)
    assert cov["truncated"] is True
    assert cov["annualized"] is False
    assert cov["oldest_holding"] == "2026-08-27"
    assert cov["covered_days"] == 7
    cov2 = holding_coverage({"A": "2020-01-01"}, "2025-09-03", "2026-09-03", 300)
    assert cov2["truncated"] is False and cov2["annualized"] is True


def test_coerce_holding_date():
    assert coerce_holding_date(datetime(2026, 8, 27, 14, 54)) == "2026-08-27"
    assert coerce_holding_date(None) is None
    assert coerce_holding_date("2024-05-01T00:00:00") == "2024-05-01"


def test_implied_start_from_price():
    dates = pd.date_range("2025-01-01", periods=200, freq="B")
    # synthetic ladder 100 -> 300: buy 150 last touched mid-window
    close = pd.Series(100 + np.arange(200) * 1.0, index=dates)
    hit = implied_start_from_price(close, 200.0, "2025-12-01")
    # 2% band spans values 196..204 -> most-recent match wins (index 104)
    assert hit == str(dates[104].date())
    # tolerance edge: >2% away matches nothing
    assert implied_start_from_price(close, 1000.0, "2025-12-01") is None
    # invalid buy / empty series
    assert implied_start_from_price(close, None, "2025-12-01") is None
    assert implied_start_from_price(close, 0.0, "2025-12-01") is None
    assert implied_start_from_price(pd.Series([], dtype=float), 150.0, "2025-12-01") is None
    # matches on/after added_on do not count (most-recent BEFORE wins)
    assert implied_start_from_price(close, 290.0, "2025-06-01") is None


def test_effective_starts_min_rule():
    dates = pd.date_range("2025-01-01", periods=200, freq="B")
    close = pd.Series(100 + np.arange(200) * 1.0, index=dates)
    holdings = {
        "OLD.NS": {"added_on": "2025-12-01", "buy_price": 200.0},  # touched day 100
        "NEW.NS": {"added_on": "2025-12-01", "buy_price": None},   # import stamp only
        "ADHOC.NS": {"added_on": None, "buy_price": None},        # unknown stays unknown
    }
    out = effective_starts(holdings, {"OLD.NS": close, "NEW.NS": close})
    assert out["OLD.NS"] == str(dates[104].date())
    assert out["NEW.NS"] == "2025-12-01"
    assert out["ADHOC.NS"] is None


def test_holding_window():
    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    frames = {
        "A": pd.Series(np.arange(100.0), index=dates),
        "B": pd.Series(np.arange(100.0), index=dates),
    }
    masked, eff = holding_window(
        frames, {"A": {"added_on": "2024-03-01", "buy_price": None}, "B": {"added_on": None, "buy_price": None}}
    )
    # shared intersection cutoff applies to the whole dict (aligned math);
    # pure-ad-hoc calls (holdings empty) stay fully hypothetical.
    assert str(masked["A"].index[0].date()) == "2024-03-01"
    assert len(masked["A"]) < 100 and len(masked["B"]) < 100
    assert eff["A"] == "2024-03-01" and eff["B"] is None
    # fully unknown stays hypothetical
    masked2, _ = holding_window(frames, {})
    assert len(masked2["A"]) == 100
    # dateless frames pass through untouched
    plain = {"A": pd.Series([1.0, 2.0])}
    masked3, _ = holding_window(plain, {"A": {"added_on": "2024-03-01", "buy_price": None}})
    assert len(masked3["A"]) == 2


def test_apply_annualization_gate():
    payload = {"cagr": 5.0, "sharpe": 2.0, "total_return": 0.1}
    out = apply_annualization_gate(dict(payload), ["cagr", "sharpe"], 7)
    assert out["cagr"] is None and out["sharpe"] is None
    assert out["total_return"] == 0.1 and out["annualized"] is False
    out2 = apply_annualization_gate(dict(payload), ["cagr", "sharpe"], 300)
    assert out2["cagr"] == 5.0 and out2["annualized"] is True


def test_portfolio_regime_summary_branches():
    idx = pd.date_range("2026-01-01", periods=60, freq="B")
    big = pd.Series(np.full(60, 0.001), index=idx)
    out = portfolio_regime_summary(big)
    assert out["days"] == 60 and out["annualized"] is True
    assert out["ann_ret"] is not None and out["total_ret"] is not None
    small = pd.Series(np.full(7, 0.01), index=idx[:7])
    out2 = portfolio_regime_summary(small)
    assert out2["days"] == 7 and out2["annualized"] is False
    assert out2["ann_ret"] is None
    assert out2["total_ret"] == pytest.approx(round(float((1.01 ** 7) - 1), 4))
    empty = portfolio_regime_summary(pd.Series([], dtype=float))
    assert empty["days"] == 0 and empty["ann_ret"] is None


async def test_build_truncates_pre_holding():
    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    frame = pd.DataFrame({"date": dates, "adj_close": _prices(dates).values,
                          "volume": np.full(100, 1000.0)})
    mock_ds = Mock()
    mock_ds.fetch_historical_data = AsyncMock(return_value=frame)
    rdf, pret, cov = await _build_wide_returns(
        ["AAA.NS"], {"AAA.NS": 1.0}, "2024-01-01", "2024-06-01", mock_ds,
        holdings={"AAA.NS": {"added_on": "2024-03-01", "buy_price": None}},
    )
    assert str(rdf.index[0].date()) >= "2024-03-01"
    assert len(pret) < 100
    assert cov["truncated"] is True and cov["covered_days"] == len(pret)
    # 56 covered days still annualizes (>= 30); the gate is tested below
    assert cov["annualized"] is True
    # ad-hoc (unknown) tickers keep full hypothetical history
    rdf2, pret2, cov2 = await _build_wide_returns(
        ["AAA.NS"], {"AAA.NS": 1.0}, "2024-01-01", "2024-06-01", mock_ds,
        holdings={},
    )
    assert len(pret2) == 99
    assert cov2["truncated"] is False
    # holding starts after the window -> honest failure, not phantom data
    with pytest.raises(ValueError, match="holding period"):
        await _build_wide_returns(
            ["AAA.NS"], {"AAA.NS": 1.0}, "2024-01-01", "2024-06-01", mock_ds,
            holdings={"AAA.NS": {"added_on": "2026-01-01", "buy_price": None}},
        )


async def test_resolve_holdings(test_db: AsyncSession, seeded_positions):
    holdings = await resolve_holdings(test_db, ["AAPL", "MSFT", "GHOST.NS"])
    assert holdings["AAPL"]["added_on"] == "2020-01-01"
    assert "buy_price" in holdings["MSFT"]
    assert "GHOST.NS" not in holdings


async def test_tearsheet_gates_short_history(test_db: AsyncSession):
    fresh = PortfolioPosition(
        ticker="NEW.NS", weight=1.0, quantity=10, buy_price=100.0,
        last_price=110.0, market_value=1100.0, sector="X", industry="Y",
        added_on=datetime.now(),
    )
    test_db.add(fresh)
    await test_db.commit()
    dates = pd.date_range(end=pd.Timestamp.now().normalize(), periods=10, freq="B")
    frame = pd.DataFrame({"date": dates, "adj_close": _prices(dates, seed=9).values,
                          "volume": np.full(10, 1000.0)})
    mock_ds = Mock()
    mock_ds.fetch_historical_data = AsyncMock(return_value=frame)
    mock_bench = Mock()
    mock_bench.get_returns = AsyncMock(return_value=None)
    today = pd.Timestamp.now().normalize().strftime("%Y-%m-%d")
    res = await get_tear_sheet(
        tickers="NEW.NS", start="2026-01-01", end=today,
        db=test_db, data_service=mock_ds, benchmark=mock_bench,
    )
    assert res["metrics"]["cagr"] is None
    assert res["metrics"]["annualized"] is False
    assert res["metrics"]["total_return"] is not None
    assert res["history_coverage"]["truncated"] is True
    assert res["history_coverage"]["annualized"] is False


async def test_tearsheet_relative_gated_on_short_overlap(test_db: AsyncSession):
    fresh = PortfolioPosition(
        ticker="NEW2.NS", weight=1.0, quantity=10, buy_price=100.0,
        last_price=110.0, market_value=1100.0, sector="X", industry="Y",
        added_on=datetime.now(),
    )
    test_db.add(fresh)
    await test_db.commit()
    dates = pd.date_range(end=pd.Timestamp.now().normalize(), periods=10, freq="B")
    frame = pd.DataFrame({"date": dates, "adj_close": _prices(dates, seed=9).values,
                          "volume": np.full(10, 1000.0)})
    mock_ds = Mock()
    mock_ds.fetch_historical_data = AsyncMock(return_value=frame)
    bench = pd.Series(np.random.default_rng(4).normal(0.0005, 0.01, 300),
                      index=pd.date_range(end=pd.Timestamp.now().normalize(), periods=300, freq="B"))
    mock_bench = Mock()
    mock_bench.get_returns = AsyncMock(return_value=bench)
    today = pd.Timestamp.now().normalize().strftime("%Y-%m-%d")
    res = await get_tear_sheet(
        tickers="NEW2.NS", start="2025-01-01", end=today,
        db=test_db, data_service=mock_ds, benchmark=mock_bench,
    )
    rel = res["relative_vs_nifty"]
    assert rel["beta_vs_nifty"] is None
    assert rel["alpha_annualized"] is None
    assert rel["overlap_days"] < 30
    # benchmark standalone stats still describe the full index window
    assert rel["benchmark_volatility"] is not None
    assert rel["benchmark_total_return"] is not None
