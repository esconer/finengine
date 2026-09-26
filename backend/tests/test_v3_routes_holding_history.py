"""Route-layer gates for V3-06: per-position holding provenance (ticket 04).

`app/utils/holdings.py` already publishes the vocabulary; these tests fix the
ROUTE behaviour that consumed it wrongly:

* a window start is published with its source (`stored_added_on` vs
  `buy_price_inferred` vs `unknown`), never as a bare "held since" fact;
* every number inside a per-ticker line is that ticker's OWN measured sample;
* a position's `limited_history` / annualization gate reads that position's own
  return observations, never a portfolio or global count;
* the portfolio-level gates publish the portfolio's own return sample.

The v3 evidence this closes: NIFTYIETF carried 20 own return observations while
the warning line quoted the portfolio's 39/176-day counts, and the line said
"held since" an inferred pre-`added_on` date.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import numpy as np
import pandas as pd
import pytest

from app.api import analytics as analytics_mod
from app.api.analytics import (
    get_analytics_summary,
    get_forecast_risk,
    get_realized_risk,
    get_risk_score,
)
from app.models.database import PortfolioPosition
from app.services.analytics_engine import AnalyticsEngine
from app.utils.holdings import MIN_ANNUALIZE_DAYS


# ---------------------------------------------------------------------------
# seams
# ---------------------------------------------------------------------------
def _rows(rows):
    scalars = MagicMock()
    scalars.all.return_value = list(rows)
    scalars.first.return_value = rows[0] if rows else None
    result = MagicMock()
    result.scalars.return_value = scalars
    result.scalar_one_or_none.return_value = rows[0] if rows else None
    return result


def _db(rows):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=lambda *_a, **_k: _rows(rows))
    return db


def _pos(ticker, *, added_on=None, buy_price=None, market_value=10000.0, sector="X"):
    return PortfolioPosition(
        id=1,
        ticker=ticker,
        weight=0.5,
        quantity=10.0,
        buy_price=buy_price,
        last_price=100.0,
        market_value=market_value,
        region="IN",
        sector=sector,
        industry="Y",
        added_on=added_on,
    )


def _close(dates, *, start=100.0, drift=0.0, seed=3):
    rng = np.random.default_rng(seed)
    return pd.Series(
        start * np.exp(np.cumsum(rng.normal(drift, 0.01, len(dates)))),
        index=dates,
    )


def _bdays(periods: int, end: str = "2026-09-07") -> pd.DatetimeIndex:
    """`periods` business days ending on `end` (three of four parameters only)."""
    return pd.bdate_range(end=end, periods=periods)


def _frame(dates, ticker, **kwargs):
    return pd.DataFrame({"adj_close": _close(dates, **kwargs)}, index=dates)


class _Market:
    """One price frame per ticker; the last request window is echoed back."""

    def __init__(self, frames):
        self.frames = frames
        self.fetch_historical_data = AsyncMock(side_effect=self._fetch)

    async def _fetch(self, ticker, _start, _end):
        frame = self.frames.get(ticker)
        if frame is None:
            return pd.DataFrame()
        return frame.copy()


# ---------------------------------------------------------------------------
# realized risk: per-position provenance and own-sample warnings
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_inferred_start_is_never_published_as_a_holding_date():
    """v3 evidence: a buy-price-inferred 2026-05-19 start was read as "held since"."""
    dates = _bdays(300)
    close = _close(dates, seed=5)
    frame = pd.DataFrame({"adj_close": close}, index=dates)
    # The buy price matches the last close before the stored import stamp, so
    # the effective start resolves to an INFERRED date that PREDATES
    # `added_on` - exactly the v3 shape, and only ~10 sessions long.
    hit = dates.get_indexer([pd.Timestamp("2026-08-25")], method="nearest")[0]
    db = _db([_pos("A.NS", added_on=datetime(2026, 8, 26), buy_price=float(close.iloc[hit]))])

    result = await get_realized_risk(
        tickers="A.NS", start="2025-01-01", end="2026-09-07",
        db=db, data_service=_Market({"A.NS": frame}),
        analytics_engine=AnalyticsEngine(),
    )

    row = result["positions"]["A.NS"]
    assert row["analytics_start_source"] == "buy_price_inferred"
    assert row["stored_added_on"] == "2026-08-26"
    assert row["analytics_start"] < row["stored_added_on"]
    # The warning line must not claim a holding date that was never stored.
    message = next(w["message"] for w in result["warnings"] if w["ticker"] == "A.NS")
    assert "no holding date was stored" in message
    assert "import stamp 2026-08-26" in message
    assert "held since" not in message


@pytest.mark.asyncio
async def test_stored_start_keeps_the_stored_wording():
    dates = _bdays(300)
    db = _db([_pos("A.NS", added_on=datetime(2026, 8, 4), buy_price=None)])

    result = await get_realized_risk(
        tickers="A.NS", start="2025-01-01", end="2026-09-07",
        db=db, data_service=_Market({"A.NS": _frame(dates, "A.NS")}),
        analytics_engine=AnalyticsEngine(),
    )

    row = result["positions"]["A.NS"]
    assert row["analytics_start_source"] == "stored_added_on"
    assert row["analytics_start"] == "2026-08-04"
    entry = result["history_coverage"]["tickers"]["A.NS"]
    assert entry["analytics_start_source"] == "stored_added_on"
    assert entry["stored_added_on"] == "2026-08-04"


@pytest.mark.asyncio
async def test_per_ticker_warning_uses_own_observations_not_the_portfolio():
    """v3 evidence: a 20-observation leg quoted the portfolio's 39/176 days."""
    dates = _bdays(300)
    db = _db([
        _pos("LONG.NS", added_on=datetime(2020, 1, 1)),
        _pos("NIFTYIETF.NS", added_on=datetime(2026, 6, 8)),
    ])
    # The ETF only listed 20 sessions before the intersection start.
    late = dates[-20:]

    result = await get_realized_risk(
        tickers="LONG.NS,NIFTYIETF.NS", start="2025-01-01", end="2026-09-07",
        db=db,
        data_service=_Market({
            "LONG.NS": _frame(dates, "LONG.NS", seed=1),
            "NIFTYIETF.NS": _frame(late, "NIFTYIETF.NS", seed=2),
        }),
        analytics_engine=AnalyticsEngine(),
    )

    covered = result["history_coverage"]["covered_days"]
    etf = result["positions"]["NIFTYIETF.NS"]
    assert etf["return_observations"] == 19
    assert etf["is_limited_history"] is True
    # The portfolio's sample is bounded by its SHORTEST held leg, not its longest.
    # A book containing a 19-observation instrument has 19 days of portfolio
    # history; it does not have LONG's full history with the ETF's absent days
    # renormalised away, which is what previously let this read >= 30 and
    # publish an annualised figure off 19 real observations.
    assert covered == etf["return_observations"] == 19
    assert covered < MIN_ANNUALIZE_DAYS
    assert result["history_coverage"]["annualized"] is False

    message = next(
        w["message"] for w in result["warnings"] if w["ticker"] == "NIFTYIETF.NS"
    )
    assert "19 own return observations" in message
    # No portfolio-level count may appear inside a per-ticker line. This has to be
    # asserted on the LABEL, not on the number: the portfolio sample and this
    # position's own sample are both 19 here (the portfolio is bounded by its
    # shortest leg), so a value-based check can no longer tell the two apart and
    # would silently pass on any wording. The invariant is that the per-ticker
    # line attributes the count to the position and never to the section.
    assert "own return observations" in message
    for portfolio_framing in ("portfolio", "covered_days", "section", "book"):
        assert portfolio_framing not in message.lower()
    assert "realized P&L covers" not in message
    assert result["positions"]["LONG.NS"]["is_limited_history"] is False


@pytest.mark.asyncio
async def test_late_listed_leg_has_no_entry_in_the_warning_list():
    """A leg with no measurable own sample states that, with no invented count."""
    dates = _bdays(300)
    db = _db([
        _pos("LONG.NS", added_on=datetime(2020, 1, 1)),
        _pos("GHOST.NS", added_on=datetime(2020, 1, 1)),
    ])

    result = await get_realized_risk(
        tickers="LONG.NS,GHOST.NS", start="2025-01-01", end="2026-09-07",
        db=db,
        data_service=_Market({"LONG.NS": _frame(dates, "LONG.NS", seed=1)}),
        analytics_engine=AnalyticsEngine(),
    )

    # GHOST delivered no price at all, so it is not in `positions` and the
    # coverage map carries no fabricated return count for it.
    assert "GHOST.NS" not in result["positions"]
    ghost = result["history_coverage"]["tickers"]["GHOST.NS"]
    assert ghost.get("return_observations") is None
    assert ghost.get("limited_history") is None


@pytest.mark.asyncio
async def test_limited_flag_agrees_across_row_and_coverage_map():
    dates = _bdays(300)
    db = _db([
        _pos("LONG.NS", added_on=datetime(2020, 1, 1)),
        _pos("SHORT.NS", added_on=datetime(2026, 8, 20)),
    ])

    result = await get_realized_risk(
        tickers="LONG.NS,SHORT.NS", start="2025-01-01", end="2026-09-07",
        db=db,
        data_service=_Market({
            "LONG.NS": _frame(dates, "LONG.NS", seed=1),
            "SHORT.NS": _frame(dates[-10:], "SHORT.NS", seed=2),
        }),
        analytics_engine=AnalyticsEngine(),
    )

    for ticker, row in result["positions"].items():
        entry = result["history_coverage"]["tickers"][ticker]
        assert row["is_limited_history"] == entry["limited_history"]
        assert row["return_observations"] == entry["return_observations"]
        if row["is_limited_history"]:
            assert row["return_observations"] < MIN_ANNUALIZE_DAYS
            assert row["annual_return"] is None
            assert row["sharpe_ratio"] is None


# ---------------------------------------------------------------------------
# summary: the per-position gate must be visible to the coverage call
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_summary_per_ticker_limited_flag_comes_from_own_observations():
    """The route used to patch `return_observations` on AFTER the coverage call."""
    dates = _bdays(300)
    # Both were imported long ago, but only 20 sessions exist for the late
    # listed leg, so the intersection stays put and only that leg is short.
    db = _db([
        _pos("LONG.NS", added_on=datetime(2020, 1, 1)),
        _pos("LATE.NS", added_on=datetime(2020, 1, 1)),
    ])

    result = await get_analytics_summary(
        db=db,
        data_service=_Market({
            "LONG.NS": _frame(dates, "LONG.NS", seed=1),
            "LATE.NS": _frame(dates[-20:], "LATE.NS", seed=2),
        }),
        analytics_engine=AnalyticsEngine(),
    )

    coverage = result["history_coverage"]
    assert coverage["tickers"]["LATE.NS"]["limited_history"] is True
    assert coverage["tickers"]["LONG.NS"]["limited_history"] is False
    assert coverage["tickers"]["LATE.NS"]["return_observations"] == 19
    assert coverage["position_observations"]["LATE.NS"]["limited_history"] is True
    assert coverage["position_observations"]["LATE.NS"]["analytics_start"] == "2020-01-01"
    assert coverage["position_observations"]["LATE.NS"]["analytics_start_source"] == "stored_added_on"
    # The portfolio-level gate is the portfolio's own measured return sample, and
    # that sample is bounded by the shortest held leg (LATE.NS, 19 observations).
    # The gate therefore refuses to annualise, and `annualized` must agree with
    # the count rather than being asserted True independently of it.
    assert result["portfolio_return_observations"] == coverage["covered_days"]
    assert coverage["covered_days"] == 19 < MIN_ANNUALIZE_DAYS
    assert coverage["annualized"] is (coverage["covered_days"] >= MIN_ANNUALIZE_DAYS)
    assert coverage["annualized"] is False


# ---------------------------------------------------------------------------
# risk score: the same provenance, measured before the coverage call
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_risk_score_publishes_position_own_sample_and_provenance():
    dates = _bdays(300)
    db = _db([
        _pos("LONG.NS", added_on=datetime(2020, 1, 1)),
        _pos("LATE.NS", added_on=datetime(2020, 1, 1)),
    ])

    result = await get_risk_score(
        db=db,
        data_service=_Market({
            "LONG.NS": _frame(dates, "LONG.NS", seed=1),
            "LATE.NS": _frame(dates[-20:], "LATE.NS", seed=2),
        }),
        analytics_engine=AnalyticsEngine(),
        benchmark_service=Mock(get_returns=AsyncMock(return_value=None)),
    )

    coverage = result["history_coverage"]
    assert coverage["position_observations"]["LATE.NS"]["return_observations"] == 19
    assert coverage["position_observations"]["LATE.NS"]["limited_history"] is True
    assert coverage["position_observations"]["LATE.NS"]["analytics_start_source"] == "stored_added_on"
    assert coverage["position_observations"]["LONG.NS"]["limited_history"] is False
    assert coverage["tickers"]["LATE.NS"]["limited_history"] is True
    assert coverage["tickers"]["LONG.NS"]["limited_history"] is False
    # The portfolio's own sample is published, and it is a PORTFOLIO count: it is
    # the set of dates the whole book was measurable on, which here is bounded by
    # the late-listed leg rather than inflated by the long-history leg.
    assert coverage["portfolio_return_observations"] == coverage["covered_days"]
    assert coverage["covered_days"] == 19
    assert coverage["covered_days"] < MIN_ANNUALIZE_DAYS
    assert coverage["annualized"] is False
    assert coverage["covered_days_scope"] == "portfolio_return_observations"


# ---------------------------------------------------------------------------
# forecast risk: the gate is the position's own RETURNS, not price rows
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_forecast_gate_reads_own_returns_not_price_rows():
    """30 price rows are 29 returns, which is below the annualization gate."""
    dates = _bdays(30)
    captured = []

    async def forecast(series, model, horizon):
        captured.append(series)
        return {
            "volatility_forecast": 0.2, "var_forecast": -0.02, "cvar_forecast": -0.03,
            "confidence_interval": [0.1, 0.3], "term_structure": [0.2],
            "model_params": {"type": model},
        }

    engine = SimpleNamespace(forecast_volatility=forecast)
    with patch.object(
        analytics_mod, "resolve_allocation",
        side_effect=AsyncMock(return_value=(["A.NS"], {"A.NS": 1.0})),
    ):
        result = await get_forecast_risk(
            model="EWMA", horizon=1, tickers="A.NS",
            start="2025-01-01", end="2026-09-07",
            db=Mock(), data_service=_Market({"A.NS": _frame(dates, "A.NS")}),
            analytics_engine=engine,
        )

    row = result["positions"]["A.NS"]
    assert row["data_points"] == 30
    assert row["return_observations"] == 29
    assert row["is_limited_history"] is True
    # Only the portfolio leg was modelled: the thin position leg was not.
    assert len(captured) == 1
    assert result["warnings"][0]["return_observations"] == 29


@pytest.mark.asyncio
async def test_forecast_publishes_the_portfolio_own_return_sample():
    dates = _bdays(60)

    async def forecast(_series, model, horizon):
        return {
            "volatility_forecast": 0.2, "var_forecast": -0.02, "cvar_forecast": -0.03,
            "confidence_interval": [0.1, 0.3], "term_structure": [0.2],
            "model_params": {"type": model},
        }

    engine = SimpleNamespace(forecast_volatility=forecast)
    with patch.object(
        analytics_mod, "resolve_allocation",
        side_effect=AsyncMock(return_value=(["A.NS"], {"A.NS": 1.0})),
    ):
        result = await get_forecast_risk(
            model="EWMA", horizon=1, tickers="A.NS",
            start="2025-01-01", end="2026-09-07",
            db=Mock(), data_service=_Market({"A.NS": _frame(dates, "A.NS")}),
            analytics_engine=engine,
        )

    # V3-17: the portfolio forecast is fitted to the aggregated portfolio
    # return series, so its sample is that series' length (59), never the
    # 60 price rows and never the number of tickers (1).
    assert result["portfolio_observations"] == 59
    assert result["portfolio"]["observations"] == 59
    assert result["portfolio_observations"] != 1
    assert result["portfolio"]["annualized"] is True
    assert result["portfolio"]["minimum_observations_required"] == MIN_ANNUALIZE_DAYS


@pytest.mark.asyncio
async def test_forecast_unavailable_leg_publishes_zero_observations_not_a_guess():
    async def _allocation(_tickers, _db):
        return ["A.NS"], {"A.NS": 1.0}

    with patch.object(analytics_mod, "resolve_allocation", side_effect=_allocation):
        result = await get_forecast_risk(
            model="EWMA", horizon=1, tickers="A.NS",
            start="2025-01-01", end="2026-09-07",
            db=Mock(), data_service=Mock(), analytics_engine=Mock(),
        )

    assert result["portfolio_observations"] == 0
    assert result["portfolio"]["observations"] == 0
    assert result["portfolio"]["annualized"] is False
    assert result["data_status"] == "unavailable"
