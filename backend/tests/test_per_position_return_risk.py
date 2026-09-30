"""`instrument_risk.positions` publishes the return/risk keys it computes.

`instrument_risk` (DSP-10) measures each leg on the FULL exchange window, so
the per-position block and the `portfolio` block beside it are the same
measurement taken over two different row sets. They must therefore agree on
WHICH fields the `apply_annualization_gate` policy covers.

The defect this file exists for: the per-position gate listed only
`["annual_volatility", "sharpe_ratio"]` while the portfolio gate listed
`["annual_return", "annual_volatility", "sharpe_ratio", "sortino_ratio"]`.
`_calculate_basic_metrics` withholds `annual_return`/`sortino_ratio` only
below 10 return observations, so a leg with 10-29 observations published a
10-day mean x 252 under an "annual" label that no gate ever saw. The value was
real arithmetic over real data; it was simply not an annual return.

`total_return` is a DIFFERENT measure -- cumulative first-to-last price move,
never annualized -- and is deliberately left ungated. Pinning it here is what
stops a future reader from "harmonising" it into `annual_return`.

Driven through the real route on synthetic frames with the real
`AnalyticsEngine`, so the assertions are about what the endpoint publishes.
"""

import ast
import inspect
import textwrap
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock

import numpy as np
import pandas as pd
import pytest

import app.api.analytics as analytics_mod
from app.api.analytics import get_realized_risk
from app.models.database import PortfolioPosition
from app.services.analytics_engine import AnalyticsEngine
from app.utils.holdings import MIN_ANNUALIZE_DAYS

#: Window the assertions below are anchored to. Kept in one place so a leg's
#: row count is the only thing that varies between the short and long cases.
START = "2025-01-01"
END = "2026-09-07"

#: Fields the engine computes per position but the route used to discard.
#: Every one must be published, copied from `_calculate_position_metrics`.
DISCARDED_KEYS = ("annual_return", "sortino_ratio", "cvar_95", "hit_ratio", "var_95")


def _frame(days: int, seed: int = 11, ticker: str = "AAA.NS") -> pd.DataFrame:
    """A single-ticker OHLCV-ish frame of exactly `days` PRICE rows.

    `days` price rows yield `days - 1` return observations -- the one-apart
    relationship the reconciliation block in this route already documents.
    """
    dates = pd.date_range(end=END, periods=days, freq="B")
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, days)))
    return pd.DataFrame({
        "date": dates, "adj_close": close, "close": close,
        "volume": np.full(days, 1e6), "ticker": ticker,
    })


def _mock_db(positions):
    mock_db = AsyncMock()
    scalars = MagicMock()
    scalars.all.return_value = positions
    res = MagicMock()
    res.scalars.return_value = scalars
    mock_db.execute = AsyncMock(return_value=res)
    return mock_db


def _pos(ticker: str, added_on=datetime(2020, 1, 1)):
    return PortfolioPosition(
        id=1, ticker=ticker, weight=1.0, quantity=10.0, buy_price=None,
        last_price=100.0, market_value=10000.0, region="IN",
        sector="X", industry="Y", added_on=added_on,
    )


async def _published_positions(ticker: str, days: int, seed: int = 11) -> dict:
    """The endpoint's `instrument_risk.positions` entry for one leg."""
    mock_ds = Mock()
    mock_ds.fetch_historical_data = AsyncMock(
        return_value=_frame(days, seed=seed, ticker=ticker)
    )
    result = await get_realized_risk(
        tickers=ticker, start=START, end=END,
        db=_mock_db([_pos(ticker)]), data_service=mock_ds,
        analytics_engine=AnalyticsEngine(),
    )
    return result["instrument_risk"]["positions"][ticker]


async def _engine_position_metrics(ticker: str, days: int, seed: int = 11) -> dict:
    """The UNGATED per-position metrics, straight from the engine.

    Read on the same frame the route builds, so a test can show that the
    route's `null` is the gate's doing and not the engine's -- i.e. that a
    number existed and the route declined to publish it.
    """
    from app.api.analytics import _assign_price

    price_data_dict = {}
    _assign_price(price_data_dict, ticker, _frame(days, seed=seed, ticker=ticker))
    frame = pd.DataFrame(price_data_dict)
    metrics = await AnalyticsEngine().calculate_portfolio_metrics(frame, {ticker: 1.0})
    return (metrics.get("positions") or {})[ticker]


# --------------------------------------------------------------------------
# Load-bearing: a 10-29 observation leg must publish null, not a number.
# --------------------------------------------------------------------------


async def test_ten_to_twenty_nine_observation_leg_publishes_null_not_a_number():
    """20 price rows -> 19 return observations -> null, not a 19-day "annual".

    This is the whole fix. Before it, the endpoint published the engine's
    `annual_return` for this leg (a 19-day mean x 252) as if it were annual,
    because the gate never listed the field.
    """
    row = await _published_positions("SHORT.NS", days=20)

    # Precondition: the leg really is inside the 10-29 observation band, so
    # this test exercises the gate and not the engine's own <10 withholding.
    assert 10 <= row["data_points"] <= 29, row["data_points"]
    assert row["annualized"] is False

    assert row["annual_return"] is None, (
        "a 19-observation mean x 252 is not an annual return"
    )
    assert row["sortino_ratio"] is None


async def test_the_null_above_is_the_route_gate_not_the_engine_withholding():
    """The engine DID compute a number for that leg; the route nulled it.

    Without this, a null could always be explained away as "the engine never
    had one", which would make the test above pass for the wrong reason.
    """
    ungated = await _engine_position_metrics("SHORT.NS", days=20)

    assert 10 <= ungated["data_points"] <= 29, ungated["data_points"]
    # _calculate_basic_metrics withholds only below 10 observations, so at 19
    # it returns a real float for both fields.
    assert isinstance(ungated["annual_return"], float)
    assert isinstance(ungated["sortino_ratio"], float)

    row = await _published_positions("SHORT.NS", days=20)
    assert row["annual_return"] is None
    assert row["sortino_ratio"] is None


# --------------------------------------------------------------------------
# The gate is not simply refusing everything.
# --------------------------------------------------------------------------


async def test_thirty_plus_observation_leg_still_publishes_annual_return_and_sortino():
    """90 price rows -> 89 return observations -> both fields survive."""
    row = await _published_positions("LONG.NS", days=90)

    assert row["annualized"] is True
    assert isinstance(row["annual_return"], float)
    assert isinstance(row["sortino_ratio"], float)
    # And they are the engine's values, not the route's own arithmetic.
    ungated = await _engine_position_metrics("LONG.NS", days=90)
    assert row["annual_return"] == pytest.approx(ungated["annual_return"])


# --------------------------------------------------------------------------
# The two blocks must gate the same field names.
# --------------------------------------------------------------------------


def _gate_field_lists() -> dict:
    """Field-name list per `apply_annualization_gate` call in the route.

    Keyed by the day-count argument's source name, so the portfolio block
    (`full_days`) and the per-position block (`own_days`) are identified by
    something structural rather than by list order.
    """
    source = textwrap.dedent(inspect.getsource(analytics_mod.get_realized_risk))
    found = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "apply_annualization_gate"):
            continue
        found[ast.unparse(node.args[2])] = [ast.literal_eval(e) for e in node.args[1].elts]
    return found


def test_per_position_block_gates_the_same_fields_as_the_portfolio_block():
    """A key added to one gate and not the other must fail here.

    The two blocks are the same measurement over two row sets; a field
    annualization policy covers for the portfolio must cover it per leg too,
    or a short leg publishes what the portfolio is forbidden to.
    """
    gates = _gate_field_lists()

    assert "full_days" in gates, "instrument_risk portfolio gate not found"
    assert "own_days" in gates, "instrument_risk per-position gate not found"
    assert gates["own_days"] == gates["full_days"], (
        f"per-position gates {gates['own_days']} but portfolio gates "
        f"{gates['full_days']}"
    )
    # Spell the policy out so a wholesale rename cannot pass unnoticed.
    assert sorted(gates["own_days"]) == [
        "annual_return", "annual_volatility", "sharpe_ratio", "sortino_ratio",
    ]


# --------------------------------------------------------------------------
# The discarded keys are published, copied -- never recomputed.
# --------------------------------------------------------------------------


async def test_discarded_engine_keys_are_now_published():
    """Every computed-but-dropped key appears, with the engine's value."""
    row = await _published_positions("LONG.NS", days=90)
    ungated = await _engine_position_metrics("LONG.NS", days=90)

    for key in DISCARDED_KEYS:
        assert key in row, f"{key} is computed and then discarded"
        assert row[key] == pytest.approx(ungated[key]), key


# --------------------------------------------------------------------------
# total_return is a different measure and stays ungated.
# --------------------------------------------------------------------------


async def test_total_return_stays_cumulative_and_is_not_gated():
    """`total_return` is first-to-last, not annualized, so the gate leaves it.

    A 20-row leg has `annual_return` nulled but `total_return` intact: two
    different measures of the same window, deliberately not harmonised.
    """
    row = await _published_positions("SHORT.NS", days=20)

    assert row["annual_return"] is None
    assert isinstance(row["total_return"], float)

    prices = pd.Series(_frame(20, seed=11, ticker="SHORT.NS")["adj_close"])
    expected = round(float(prices.iloc[-1]) / float(prices.iloc[0]) - 1.0, 6)
    assert row["total_return"] == pytest.approx(expected)


def test_min_annualize_days_constant_unchanged():
    """Guard the policy constant this change leans on. Not modified here."""
    assert MIN_ANNUALIZE_DAYS == 30
