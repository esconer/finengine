"""Route-layer gates for V3-05: full-history models vs holding context (ticket 05).

Factor Exposure and Risk Contribution answer hypothetical current-weight
questions over FULL exchange history. Publishing holding-window
`effective_start`/`truncated` there claimed the model was cut to a window it
never used, and a copied `covered_days` reported the model's own 252
observations as if they were the holding window's 39 days.

The regime block adds the other half: a portfolio-in-current-regime summary is a
CONDITIONAL sample, so its coverage has to describe that sample (19 regime days),
not the holding window it was drawn from.

These tests therefore fix three distinct counts side by side: 39 total holding
days, 19 days in the current regime, and 252 hypothetical model observations.
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
    FULL_HISTORY_BASIS,
    HOLDING_CONTEXT_SCOPE,
    get_factor_exposure,
    get_regime,
    get_risk_contribution,
)
from app.models.database import PortfolioPosition
from app.utils.holdings import MIN_ANNUALIZE_DAYS

# The three windows this suite keeps apart. Chosen so a test that accidentally
# reads the wrong one fails loudly instead of passing by coincidence.
HOLDING_DAYS = 39
REGIME_DAYS = 19
MODEL_OBSERVATIONS = 252


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


def _pos(ticker, *, added_on, sector="Tech", market_value=10000.0):
    return PortfolioPosition(
        id=1, ticker=ticker, weight=0.5, quantity=10.0, buy_price=None,
        last_price=100.0, market_value=market_value, region="IN",
        sector=sector, industry="Y", added_on=added_on,
    )


def _bdays(periods: int, end: str = "2026-09-07") -> pd.DatetimeIndex:
    return pd.bdate_range(end=end, periods=periods)


def _walk(dates, *, seed=1, drift=0.0):
    rng = np.random.default_rng(seed)
    return pd.Series(
        100.0 * np.exp(np.cumsum(rng.normal(drift, 0.01, len(dates)))), index=dates
    )


def _frame(dates, ticker, *, seed=1, market=True):
    close = _walk(dates, seed=seed)
    data = {"adj_close": close}
    if market:
        bench = _walk(dates, seed=seed + 50, drift=0.0002)
        data["adj_close"] = 0.6 * close + 0.4 * bench
    return pd.DataFrame(data, index=dates)


class _Market:
    def __init__(self, frames):
        self.frames = frames
        self.fetch_historical_data = AsyncMock(side_effect=self._fetch)

    async def _fetch(self, ticker, _start, _end):
        frame = self.frames.get(ticker)
        return pd.DataFrame() if frame is None else frame.copy()


def _benchmark(dates, *, seed=99):
    return _walk(dates, seed=seed, drift=0.0003)


# ---------------------------------------------------------------------------
# factor exposure
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_factor_exposure_model_window_is_not_the_holding_window():
    dates = _bdays(MODEL_OBSERVATIONS + 1)
    db = _db([_pos("A.NS", added_on=datetime(2026, 8, 4))])
    bench = SimpleNamespace(
        get_returns=AsyncMock(return_value=_benchmark(dates, seed=7))
    )

    result = await get_factor_exposure(
        tickers="A.NS", lookback_days=365, db=db,
        data_service=_Market({"A.NS": _frame(dates, "A.NS", seed=3)}),
        benchmark_service=bench,
        analytics_engine=analytics_mod.AnalyticsEngine(),
    )

    coverage = result["history_coverage"]
    full = coverage["full_history"]
    assert coverage["scope"] == HOLDING_CONTEXT_SCOPE
    assert coverage["calculation_basis"] == FULL_HISTORY_BASIS
    # The model is NOT truncated to holdings: no holding start is published for
    # it and `truncated` is unconditionally false.
    assert coverage["truncated"] is False
    assert coverage["effective_start"] is None
    assert full["truncated_to_holding_window"] is False
    assert full["observation_count"] == MODEL_OBSERVATIONS
    assert full["annualized"] is True
    # The window describes the returns the regression consumed, so it starts
    # one session after the first price bar (which has no return).
    assert full["window"]["start"] == str(dates[1].date())
    assert full["window"]["end"] == str(dates[-1].date())
    assert full["first_observation"] == str(dates[1].date())
    assert full["last_observation"] == str(dates[-1].date())
    assert full["latest_observation_date"] == str(dates[-1].date())
    # The holding window is present, but only as clearly ancillary context.
    holding = coverage["holding_context"]
    # Same canonical rule as the risk-contribution sibling below: the count a
    # holding-window section publishes is the rows STRICTLY AFTER the start,
    # because the bar on the start date is the first held price and has no held
    # predecessor. Counting the start row itself reports a pre-purchase return.
    expected_holding_days = int((dates[1:] > pd.Timestamp("2026-08-04")).sum())
    assert expected_holding_days < MODEL_OBSERVATIONS // 2
    assert holding["covered_days"] == expected_holding_days
    assert holding["covered_days_scope"] == "holding_window_aligned_return_rows"
    assert holding["intersection_start"] == "2026-08-04"
    assert coverage["holding_window_days"] == holding["covered_days"]
    assert coverage["covered_days"] == MODEL_OBSERVATIONS
    assert coverage["covered_days_scope"] == "model_return_observations"
    assert coverage["annualized"] is True


@pytest.mark.asyncio
async def test_factor_exposure_exposes_per_ticker_usable_observations():
    dates = _bdays(MODEL_OBSERVATIONS + 1)
    db = _db([
        _pos("A.NS", added_on=datetime(2020, 1, 1)),
        _pos("LATE.NS", added_on=datetime(2020, 1, 1)),
    ])
    bench = SimpleNamespace(
        get_returns=AsyncMock(return_value=_benchmark(dates, seed=11))
    )

    result = await get_factor_exposure(
        tickers="A.NS,LATE.NS", lookback_days=365, db=db,
        data_service=_Market({
            "A.NS": _frame(dates, "A.NS", seed=3),
            # A late-listed leg keeps 20 usable observations and is labelled.
            "LATE.NS": _frame(dates[-20:], "LATE.NS", seed=4),
        }),
        benchmark_service=bench,
        analytics_engine=analytics_mod.AnalyticsEngine(),
    )

    tickers = result["full_history"]["tickers"]
    assert tickers["LATE.NS"]["return_observations"] == 19
    assert tickers["LATE.NS"]["usable_observations"] == 19
    assert tickers["LATE.NS"]["limited_history"] is True
    assert tickers["A.NS"]["return_observations"] == MODEL_OBSERVATIONS
    assert tickers["A.NS"]["limited_history"] is False
    # The model annualization flag is the AND over the legs, never the best one.
    assert result["full_history"]["annualized"] is False
    # Sparse legs surface in the warning list with their own counts.
    warning = next(
        w for w in result["warnings"] if w["ticker"] == "LATE.NS"
    )
    assert warning["return_observations"] == 19
    assert "19 own return observations" in warning["message"]


@pytest.mark.asyncio
async def test_factor_exposure_holding_context_never_overwrites_model_evidence():
    dates = _bdays(120)
    db = _db([_pos("A.NS", added_on=datetime(2026, 8, 4))])
    bench = SimpleNamespace(
        get_returns=AsyncMock(return_value=_benchmark(dates, seed=13))
    )

    result = await get_factor_exposure(
        tickers="A.NS", lookback_days=365, db=db,
        data_service=_Market({"A.NS": _frame(dates, "A.NS", seed=5)}),
        benchmark_service=bench,
        analytics_engine=analytics_mod.AnalyticsEngine(),
    )

    coverage = result["history_coverage"]
    # Writing a holding-window verdict into the top level cannot change what the
    # model block says, because the model block is a separate object.
    coverage["annualized"] = False
    coverage["covered_days"] = 1
    coverage["truncated"] = True
    assert result["full_history"]["annualized"] is True
    assert result["full_history"]["observation_count"] == 119
    assert result["full_history"]["truncated_to_holding_window"] is False
    assert result["full_history"]["window"]["start"] == str(dates[1].date())


# ---------------------------------------------------------------------------
# risk contribution
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_risk_contribution_separates_model_observations_from_holding():
    dates = _bdays(MODEL_OBSERVATIONS + 1)
    db = _db([
        _pos("A.NS", added_on=datetime(2020, 1, 1), sector="Tech"),
        _pos("B.NS", added_on=datetime(2020, 1, 1), sector="Energy"),
    ])

    result = await get_risk_contribution(
        tickers="A.NS,B.NS", db=db,
        data_service=_Market({
            "A.NS": _frame(dates, "A.NS", seed=21, market=False),
            "B.NS": _frame(dates, "B.NS", seed=22, market=False),
        }),
    )

    coverage = result["history_coverage"]
    full = coverage["full_history"]
    assert coverage["truncated"] is False
    assert coverage["effective_start"] is None
    assert full["observation_count"] == MODEL_OBSERVATIONS
    assert full["annualized"] is True
    assert full["basis"] == FULL_HISTORY_BASIS
    # The historical `covered_days` for this route used to be the model's own
    # 252 observations wearing holding-window names.
    assert coverage["covered_days"] == MODEL_OBSERVATIONS
    assert coverage["covered_days_scope"] == "model_return_observations"
    assert coverage["calculation_observations"] == MODEL_OBSERVATIONS
    assert coverage["holding_window_days"] == coverage["holding_context"]["covered_days"]
    assert result["full_history"] == full


@pytest.mark.asyncio
async def test_risk_contribution_holding_context_keeps_its_own_window():
    dates = _bdays(MODEL_OBSERVATIONS + 1)
    db = _db([_pos("A.NS", added_on=datetime(2026, 8, 4), sector="Tech")])

    result = await get_risk_contribution(
        tickers="A.NS", db=db,
        data_service=_Market({"A.NS": _frame(dates, "A.NS", seed=31, market=False)}),
    )

    coverage = result["history_coverage"]
    holding = coverage["holding_context"]
    # A return needs two HELD prices, and the bar on the start date is the first
    # held price: it has no held predecessor, so the return dated on it is a
    # pre-purchase return the user never earned on this position. `>=` counted
    # it; the count every holding-window section now publishes is the strictly
    # after rows, which is why the window is 24 observations and not 25 (V3-08).
    expected_holding_days = int((dates[1:] > pd.Timestamp("2026-08-04")).sum())
    assert holding["intersection_start"] == "2026-08-04"
    assert holding["tickers"]["A.NS"]["analytics_start"] == "2026-08-04"
    assert holding["tickers"]["A.NS"]["analytics_start_source"] == "stored_added_on"
    assert result["full_history"]["observation_count"] == MODEL_OBSERVATIONS
    # The holding context counts the HELD rows, not the model's whole span.
    assert holding["covered_days"] == expected_holding_days
    assert holding["covered_days"] < MODEL_OBSERVATIONS // 2
    assert holding["covered_days_scope"] == "holding_window_aligned_return_rows"
    assert coverage["holding_window_days"] == expected_holding_days
    assert coverage["covered_days"] == MODEL_OBSERVATIONS


# ---------------------------------------------------------------------------
# regime: the conditional sample is not the holding window
# ---------------------------------------------------------------------------
def _regime_result(days: int) -> dict:
    return {
        "current_regime": "calm",
        "regime": "calm",
        "portfolio_in_current_regime": {
            "days": days,
            "ann_ret": None,
            "ann_vol": None,
            "total_ret": 0.03,
            "annualized": False,
        },
    }


@pytest.mark.asyncio
async def test_regime_conditional_coverage_counts_the_conditional_sample():
    dates = _bdays(MODEL_OBSERVATIONS + 1)
    returns = pd.DataFrame(
        {
            "A.NS": _walk(dates, seed=41).pct_change(fill_method=None).iloc[1:].to_numpy(),
        },
        index=dates[1:],
    )
    port_ret = returns["A.NS"]

    async def _allocation(_tickers, _db):
        return ["A.NS"], {"A.NS": 1.0}

    async def _holdings(*_a, **_k):
        return {"A.NS": {"added_on": "2026-08-04", "buy_price": None}}

    async def _build(*_a, **_k):
        # The holding pool is 39 days; the conditional sample is 19 of them.
        pool = port_ret.tail(HOLDING_DAYS)
        return returns, pool, {
            "covered_days": len(pool),
            "annualized": len(pool) >= MIN_ANNUALIZE_DAYS,
            "requested_start": "2025-01-01",
            "requested_end": "2026-09-07",
            "effective_start": "2026-08-04",
            "intersection_start": "2026-08-04",
            "oldest_holding": "2020-01-01",
            "model_used_tickers": ["A.NS"],
            "tickers": {},
        }

    with patch.object(analytics_mod, "resolve_allocation", side_effect=_allocation), \
         patch.object(analytics_mod, "resolve_holdings", side_effect=_holdings), \
         patch.object(analytics_mod, "_build_wide_returns", side_effect=_build), \
         patch.object(
             analytics_mod, "detect_regime",
             new=AsyncMock(return_value=_regime_result(REGIME_DAYS)),
         ):
        result = await get_regime(
            lookback_days=1100, with_portfolio=True,
            db=Mock(), data_service=Mock(), benchmark=Mock(),
        )

    conditional = result["portfolio_in_current_regime"]["history_coverage"]
    # The 39-day holding window, the 19-day conditional sample and the 252
    # model observations are three different numbers and stay that way.
    assert conditional["covered_days"] == REGIME_DAYS
    assert conditional["covered_days_scope"] == "conditional_regime_return_days"
    assert conditional["observations"] == REGIME_DAYS
    assert conditional["holding_window_days"] == HOLDING_DAYS
    assert conditional["annualized"] is False
    assert conditional["truncated"] is True
    assert conditional["scope"] == "conditional_current_regime"
    assert conditional["effective_start"] is None
    assert conditional["holding_context"]["covered_days"] == HOLDING_DAYS
    assert conditional["covered_days"] != conditional["holding_context"]["covered_days"]
    assert conditional["covered_days"] != MODEL_OBSERVATIONS
    # The top-level copy is the POOL the sample was drawn from.
    assert result["history_coverage"]["covered_days"] == HOLDING_DAYS


@pytest.mark.asyncio
async def test_regime_omits_conditional_coverage_when_no_sample_was_taken():
    """No conditional block means no coverage object is invented for it."""
    payload = {"current_regime": "calm", "regime": "calm"}

    async def _allocation(_tickers, _db):
        return ["A.NS"], {"A.NS": 1.0}

    async def _holdings(*_a, **_k):
        return {}

    with patch.object(analytics_mod, "resolve_allocation", side_effect=_allocation), \
         patch.object(analytics_mod, "resolve_holdings", side_effect=_holdings), \
         patch.object(
             analytics_mod, "_build_wide_returns", side_effect=ValueError("no data")
         ), \
         patch.object(
             analytics_mod, "detect_regime", new=AsyncMock(return_value=payload)
         ):
        result = await get_regime(
            lookback_days=1100, with_portfolio=True,
            db=Mock(), data_service=Mock(), benchmark=Mock(),
        )

    assert "portfolio_in_current_regime" not in result
