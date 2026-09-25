"""Ticket 03, route wave: volatility sizing and the optimizer are executable.

The engine and the shared normalization rule already existed
(`tests/test_vol_sizing_execution.py`, `tests/test_execution_normalization.py`).
What was missing was the route contract: the budget/base currency never reached
the engine, so `sizing_price_currency` and its provenance stayed `unavailable`
even though the route knew the whole book was valued in INR, and the response
published no history window, no freshness, and no exposure block for the export
to cite.

These regressions pin:

* the base currency passed into the engine, and the price series the engine
  received re-expressed in the same currency as the notional it is divided into
  (a USD price against an INR budget would mis-size every share delta);
* `execution` / `exposure` / `sizing_basis` / `sizing_history` /
  `latest_observation_date` / `history_window` on the sizing response, with the
  delivered window reported next to the requested one;
* a degraded engine that publishes no rule block still being measured, and an
  engine that published no target publishing no execution claim at all;
* the optimizer reporting the same `weight_normalization` block as the rebalance
  workflow, the risk-free rate it used, and the window it solved over - and
  staying `execution_eligible` for a rounded long-only solver vector.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from app.api import analytics as analytics_mod
from app.api.analytics import get_volatility_sizing, run_optimization
from app.services.analytics_engine import AnalyticsEngine
from app.services.currency_service import FXRate
from app.utils.allocations import (
    WEIGHT_NORMALIZATION_RULE,
    half_up,
    normalize_rebalance_weights,
)

USD_INR = 80.0


# ---------------------------------------------------------------------------
# doubles
# ---------------------------------------------------------------------------
class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)


class _DB:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    async def execute(self, _statement):
        return _Rows(self.rows)


class _FX:
    async def get_exchange_rate(self, source, target):
        rate = USD_INR if (source, target) == ("USD", "INR") else 1 / USD_INR
        return FXRate(rate, provenance="live", source="mock-fx")

    async def convert_amount_with_provenance(self, amount, source, target):
        rate = USD_INR if (source, target) == ("USD", "INR") else 1 / USD_INR
        return {
            "amount": amount * rate,
            "rate": {
                "rate": rate,
                "provenance": "live",
                "source": "mock-fx",
                "is_fallback": False,
            },
        }

    async def convert_amount(self, amount, source, target):
        rate = USD_INR if (source, target) == ("USD", "INR") else 1 / USD_INR
        return amount * rate


def _position(ticker, region, last_price, quantity=10.0, weight=0.5):
    return SimpleNamespace(
        ticker=ticker,
        region=region,
        quantity=quantity,
        last_price=last_price,
        market_value=last_price * quantity,
        weight=weight,
    )


# A mixed book: one USD leg, one INR leg, valued off the same FX snapshot.
_BOOK = [
    _position("AAPL", "US", 100.0),
    _position("TCS.NS", "IN", 200.0),
]
# 10 * 100 USD + 10 * 200 INR, converted once at the live rate.
_BUDGET_INR = 10 * 100.0 * USD_INR + 10 * 200.0


def _dates(days: int, lag_days: int = 7) -> pd.DatetimeIndex:
    """Deterministic window that stops before today, so freshness is provable."""
    end = pd.Timestamp(datetime.now().date() - timedelta(days=lag_days))
    return pd.bdate_range(end=end, periods=days)


def _native_frames(dates: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    """Native-quote price frames: AAPL is quoted in USD, TCS.NS in INR."""
    rng = np.random.default_rng(17)
    return {
        "AAPL": pd.DataFrame(
            {"adj_close": 100.0 * np.cumprod(1.0 + rng.normal(0.0002, 0.004, len(dates)))},
            index=dates,
        ),
        "TCS.NS": pd.DataFrame(
            {"adj_close": 2_000.0 * np.cumprod(1.0 + rng.normal(0.0003, 0.003, len(dates)))},
            index=dates,
        ),
    }


class _Market:
    def __init__(self, frames: dict[str, pd.DataFrame]):
        self.frames = frames

    async def fetch_historical_data(self, ticker, start, end):
        frame = self.frames.get(ticker)
        return None if frame is None else frame.copy()


class _RecordingEngine:
    """Real engine behind a recorder, so the delivered inputs can be asserted."""

    def __init__(self, engine=None):
        self.engine = engine or AnalyticsEngine()
        self.calls: list[dict] = []

    async def volatility_sizing(
        self, price_data, weights, model, target_volatility, **kwargs
    ):
        self.calls.append(
            {
                "price_data": price_data.copy(),
                "weights": dict(weights),
                "model": model,
                "target_volatility": target_volatility,
                "kwargs": dict(kwargs),
            }
        )
        return await self.engine.volatility_sizing(
            price_data, weights, model, target_volatility, **kwargs
        )


async def _size(target_volatility=0.03, *, days=300, positions=None, lag_days=7):
    """Run the route over the mixed book; return (response, recorder, dates)."""
    dates = _dates(days, lag_days=lag_days)
    engine = _RecordingEngine()
    with patch.object(analytics_mod, "get_currency_service", return_value=_FX()):
        result = await get_volatility_sizing(
            model="EWMA",
            target_volatility=target_volatility,
            portfolio_value=None,
            db=_DB(positions if positions is not None else _BOOK),
            data_service=_Market(_native_frames(dates)),
            analytics_engine=engine,
        )
    return result, engine, dates


# ---------------------------------------------------------------------------
# the base currency reaches the engine, and the prices it measured
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_budget_currency_reaches_the_engine_and_prices_are_in_it():
    result, engine, dates = await _size(target_volatility=0.03)
    call = engine.calls[0]

    assert call["kwargs"]["price_currency"] == "INR"
    assert call["kwargs"]["portfolio_value"] == pytest.approx(_BUDGET_INR)

    delivered = call["price_data"]
    frames = _native_frames(dates)
    # A share delta is the INR notional divided by a price, so that price has to
    # be INR. The USD leg is re-expressed with the same verified rate the book
    # was valued at; scaling one series leaves its measured returns unchanged.
    assert float(delivered["AAPL"].iloc[-1]) == pytest.approx(
        float(frames["AAPL"]["adj_close"].iloc[-1]) * USD_INR
    )
    assert float(delivered["TCS.NS"].iloc[-1]) == pytest.approx(
        float(frames["TCS.NS"]["adj_close"].iloc[-1])
    )

    basis = result["sizing_basis"]
    assert basis["sizing_price"]["AAPL"] == pytest.approx(
        float(delivered["AAPL"].iloc[-1])
    )
    assert basis["sizing_price_currency"] == basis["price_currency"] == "INR"
    assert basis["price_currency_provenance"] == "measured"
    assert basis["sizing_price_provenance"] == "measured"
    assert basis["sizing_price_unavailable_reason"] is None
    assert basis["portfolio_value"] == pytest.approx(_BUDGET_INR)
    assert basis["portfolio_value_currency"] == "INR"


@pytest.mark.asyncio
async def test_trade_instructions_reconcile_in_the_published_currency():
    result, _, _ = await _size(target_volatility=0.03)
    basis = result["sizing_basis"]
    assert result["trade_instructions_status"] == "reconciled"
    for ticker, trade in result["trades"].items():
        price = basis["sizing_price"][ticker]
        # One price per result: the basis and every instruction share it.
        assert trade["sizing_price"] == pytest.approx(price)
        assert trade["amount_currency"] == "INR"
        assert trade["shares_delta"] == half_up(trade["amount"] / price)
        assert trade["amount"] == pytest.approx(
            trade["shares_delta"] * price + trade["rounding_residual"], abs=0.01
        )


# ---------------------------------------------------------------------------
# exposure, eligibility, and the one rule string
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_leveraged_target_reports_financing_instead_of_zero_cash():
    result, _, _ = await _size(target_volatility=0.05)
    gross = sum(abs(value) for value in result["recommended_weights"].values())
    assert gross > 1.0, "fixture must produce a leveraged analytical target"

    execution = result["execution"]
    assert result["execution_normalization_rule"] == WEIGHT_NORMALIZATION_RULE
    assert execution["normalization_rule"] == WEIGHT_NORMALIZATION_RULE
    assert execution["gross_exposure"] == pytest.approx(gross, abs=1e-6)
    assert execution["financing_required"] is True
    assert execution["execution_eligible"] is False
    assert "not a normal rebalance" in execution["block_reason"]
    assert execution["financing_requirement"] == pytest.approx(
        (gross - 1.0) * _BUDGET_INR, abs=0.01
    )
    assert execution["financing_requirement_currency"] == "INR"
    # The analytical target keeps its gross exposure; the rebalance rule is the
    # one the book is measured against, not one applied to it.
    assert execution["weights_normalized"] is False
    assert result["cash_weight"] < 0

    # The flat projection is the same measurement, not a second computation.
    exposure = result["exposure"]
    assert exposure["gross_exposure"] == execution["gross_exposure"]
    assert exposure["net_cash_weight"] == execution["net_cash_weight"]
    assert exposure["financing_required"] is True
    assert exposure["financing_requirement"] == execution["financing_requirement"]
    assert exposure["financing_requirement_currency"] == "INR"
    assert exposure["financing_fraction"] == pytest.approx(gross - 1.0, abs=1e-6)
    assert exposure["execution_eligible"] is False
    assert exposure["block_reason"] == execution["block_reason"]

    # The exact weights this route published are refused by the rebalance
    # workflow, so a leveraged sizing target cannot be applied as a rebalance.
    refused = normalize_rebalance_weights(result["recommended_weights"])
    assert refused["rejection"]["code"] == "financing_required"
    assert refused["rejection"]["gross_exposure"] == pytest.approx(
        execution["gross_exposure"], abs=1e-6
    )


@pytest.mark.asyncio
async def test_unlevered_target_stays_execution_eligible():
    result, _, _ = await _size(target_volatility=0.02)
    execution = result["execution"]
    assert execution["gross_exposure"] < 1.0
    assert execution["normalization_mode"] == "unlevered_long_only_plus_cash"
    assert execution["financing_required"] is False
    assert execution["financing_requirement"] == 0.0
    assert execution["execution_eligible"] is True
    assert result["exposure"]["execution_eligible"] is True
    assert result["cash_weight"] > 0
    # Fully funded: the rebalance workflow would accept these weights.
    assert normalize_rebalance_weights(result["recommended_weights"])["rejection"] is None


# ---------------------------------------------------------------------------
# freshness and the measured window
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_freshness_is_the_newest_delivered_observation():
    result, _, dates = await _size(target_volatility=0.03, days=300, lag_days=7)
    latest = dates[-1].date().isoformat()

    assert result["latest_observation_date"] == latest
    assert result["sizing_price_as_of"] == latest

    window = result["history_window"]
    # The requested end is a request, never evidence.
    assert window["requested_start"] and window["requested_end"] >= latest
    assert window["requested_end"] != window["latest_observation"]
    assert window["first_observation"] == dates[0].date().isoformat()
    assert window["latest_observation"] == latest
    assert window["return_observations"] == len(dates) - 1
    assert window["per_ticker_return_observations"] == {
        ticker: len(dates) - 1 for ticker in ("AAPL", "TCS.NS")
    }
    assert window["meets_minimum_sample"] is True

    history = result["sizing_history"]
    assert history["model"] == "EWMA"
    assert history["window_end"] == latest
    assert history["price_window_start"] == dates[0].date().isoformat()
    assert history["return_observations"] == len(dates) - 1
    assert history["meets_minimum_sample"] is True


@pytest.mark.asyncio
async def test_short_history_is_disclosed_not_annualized_silently():
    result, _, dates = await _size(target_volatility=0.03, days=12)
    window = result["history_window"]
    assert window["return_observations"] == len(dates) - 1
    assert window["meets_minimum_sample"] is False
    assert window["latest_observation"] == dates[-1].date().isoformat()
    assert result["sizing_history"]["meets_minimum_sample"] is False
    assert result["sizing_history"]["minimum_sample_status"] == "insufficient"
    # Short history is a disclosed partial, and the delivered weights are real.
    assert result["data_status"] == "partial"
    assert set(result["recommended_weights"]) == {"AAPL", "TCS.NS"}


# ---------------------------------------------------------------------------
# degraded / fail-closed engine results
# ---------------------------------------------------------------------------
class _StubEngine:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def volatility_sizing(self, *_args, **_kwargs):
        self.calls += 1
        return self.result


@pytest.mark.asyncio
async def test_rule_block_is_derived_when_the_engine_publishes_none():
    """A degraded engine still leaves a target, so the rule still measures it."""
    dates = _dates(300)
    stub = _StubEngine(
        {
            "current_weights": {"AAPL": 0.97, "TCS.NS": 0.03},
            "recommended_weights": {"AAPL": 0.9, "TCS.NS": 0.39},
            "cash_weight": -0.29,
            "scale_factor": 1.29,
            "trades": {},
        }
    )
    with patch.object(analytics_mod, "get_currency_service", return_value=_FX()):
        result = await get_volatility_sizing(
            model="EWMA",
            target_volatility=0.15,
            portfolio_value=None,
            db=_DB(_BOOK),
            data_service=_Market(_native_frames(dates)),
            analytics_engine=stub,
        )

    execution = result["execution"]
    assert execution["gross_exposure"] == pytest.approx(1.29, abs=1e-6)
    assert execution["financing_required"] is True
    assert execution["execution_eligible"] is False
    assert execution["financing_requirement"] == pytest.approx(
        0.29 * _BUDGET_INR, abs=0.01
    )
    assert result["exposure"]["execution_eligible"] is False
    assert result["execution_normalization_rule"] == WEIGHT_NORMALIZATION_RULE

    # No price was measured, so none is claimed: the retired 100.0 placeholder
    # must not reappear through a degraded engine.
    basis = result["sizing_basis"]
    assert basis["sizing_price"] == {}
    assert basis["sizing_price_as_of"] is None
    assert basis["sizing_price_provenance"] == "unavailable"
    assert basis["sizing_price_unavailable_reason"] == "no_aligned_price_snapshot"
    # ...but the window evidence is the route's own, rebuilt from the frame it
    # actually delivered.
    history = result["sizing_history"]
    assert history["return_observations"] == len(dates) - 1
    assert history["window_end"] == dates[-1].date().isoformat()
    assert history["model"] == "EWMA"
    assert result["history_window"]["latest_observation"] == dates[-1].date().isoformat()


@pytest.mark.asyncio
async def test_no_target_means_no_execution_claim():
    """A fail-closed engine result publishes the rule, not a green light."""
    dates = _dates(300)
    stub = _StubEngine(
        {
            "current_weights": {},
            "recommended_weights": {},
            "trades": {},
            "error": "Insufficient data for volatility sizing",
        }
    )
    with patch.object(analytics_mod, "get_currency_service", return_value=_FX()):
        result = await get_volatility_sizing(
            model="EWMA",
            target_volatility=0.15,
            portfolio_value=None,
            db=_DB(_BOOK),
            data_service=_Market(_native_frames(dates)),
            analytics_engine=stub,
        )

    assert "execution" not in result
    assert "exposure" not in result
    assert result["execution_normalization_rule"] == WEIGHT_NORMALIZATION_RULE
    assert result["sizing_basis"]["sizing_price_provenance"] == "unavailable"
    assert result["latest_observation_date"] == dates[-1].date().isoformat()
    assert result["data_status"] == "partial"
    assert "Insufficient data" in result["error"]


@pytest.mark.asyncio
async def test_missing_budget_keeps_the_faithful_error_envelope():
    """No market value means no executable amount, and no invented price."""
    dates = _dates(300)
    stub = _StubEngine({"recommended_weights": {"AAPL": 1.0}})
    dead_book = [
        _position("NOPV.NS", "IN", 0.0, quantity=10.0, weight=1.0),
    ]
    with patch.object(analytics_mod, "get_currency_service", return_value=_FX()):
        result = await get_volatility_sizing(
            model="EWMA",
            target_volatility=0.15,
            portfolio_value=None,
            db=_DB(dead_book),
            data_service=_Market(_native_frames(dates)),
            analytics_engine=stub,
        )

    assert stub.calls == 0, "no sizing may run without a budget"
    assert result["trades"] == {"NOPV.NS": {"shares_delta": 0, "amount": 0.0}}
    assert result["data_status"] == "unavailable"
    assert result["execution_normalization_rule"] == WEIGHT_NORMALIZATION_RULE
    assert result["latest_observation_date"] is None
    assert "Portfolio market value unavailable" in result["error"]


# ---------------------------------------------------------------------------
# optimizer: the same block, the rate used, the window solved over
# ---------------------------------------------------------------------------
def _returns(days: int = 300, tickers=("A", "B", "C")) -> pd.DataFrame:
    dates = _dates(days, lag_days=7)
    rng = np.random.default_rng(23)
    data = {
        ticker: rng.normal(0.0004, 0.01 + 0.002 * offset, len(dates))
        for offset, ticker in enumerate(tickers)
    }
    return pd.DataFrame(data, index=dates)


async def _optimize(returns, weights, *, rf=0.02, solved=None):
    tickers = list(returns.columns)

    async def allocation(_tickers, _db):
        return tickers, weights

    async def build(*_args, **_kwargs):
        return returns, returns[tickers[0]], {"covered_days": len(returns)}

    def fake_optimize(_returns, strategy, risk_free_rate=0.02, **_kwargs):
        return {
            "strategy": strategy,
            "weights": dict(solved or {}),
            "expected_annual_return": 0.11,
            "expected_annual_volatility": 0.12,
            "expected_sharpe": 0.5,
            "solver": "stub",
            "risk_free_rate": risk_free_rate,
        }

    with patch.object(analytics_mod, "resolve_allocation", side_effect=allocation), \
         patch.object(analytics_mod, "_build_wide_returns", side_effect=build), \
         patch.object(analytics_mod, "optimize", new=fake_optimize):
        return await run_optimization(
            body={"strategy": "hrp", "risk_free_rate": rf},
            db=None,
            data_service=None,
        )


@pytest.mark.asyncio
async def test_optimizer_publishes_the_shared_rule_rate_and_window():
    returns = _returns()
    solved = {"A": 0.5, "B": 0.3, "C": 0.2}
    result = await _optimize(returns, {"A": 0.4, "B": 0.4, "C": 0.2}, solved=solved)

    block = result["weight_normalization"]
    assert block["normalization_rule"] == WEIGHT_NORMALIZATION_RULE
    assert block["normalization_mode"] == "fully_funded"
    assert block["execution_eligible"] is True
    assert block["financing_required"] is False
    assert block["gross_exposure"] == pytest.approx(1.0)
    assert block["submitted_gross_exposure"] == pytest.approx(1.0)
    assert block["weights_normalized"] is False
    assert block["net_cash_weight"] == pytest.approx(0.0)
    assert "rejection" not in block
    # The solver's answer is reported, never rewritten by the check.
    assert result["weights"] == pytest.approx(solved)

    assert result["risk_free_rate"] == pytest.approx(0.02)
    assert result["latest_observation_date"] == returns.index[-1].date().isoformat()
    window = result["history_window"]
    assert window["return_observations"] == len(returns)
    assert window["first_observation"] == returns.index[0].date().isoformat()
    assert window["latest_observation"] == returns.index[-1].date().isoformat()
    assert window["requested_start"] and window["requested_end"]
    assert window["meets_minimum_sample"] is True
    # The published weights are exactly what a rebalance would have to fund.
    assert normalize_rebalance_weights(result["weights"])["rejection"] is None


@pytest.mark.asyncio
async def test_optimizer_reports_the_risk_free_rate_it_actually_used():
    result = await _optimize(
        _returns(), {"A": 0.4, "B": 0.4, "C": 0.2}, rf=0.045, solved={"A": 0.4, "B": 0.35, "C": 0.25}
    )
    assert result["risk_free_rate"] == pytest.approx(0.045)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tickers,solved",
    [
        # Three equal legs at 6 dp: 1.000002 instead of 1.0.
        (["A", "B", "C"], {"A": 0.333334, "B": 0.333334, "C": 0.333334}),
        # Fifty equal legs at 6 dp: 1.000004 instead of 1.0.
        (
            [f"T{i:02d}" for i in range(50)],
            {f"T{i:02d}": (0.020004 if i == 49 else 0.02) for i in range(50)},
        ),
    ],
)
async def test_rounded_solver_weights_are_not_read_as_financing(tickers, solved):
    """Solver weights are published at 6 dp; that rounding is not leverage.

    A long-only target can sit up to n / 2e6 above 1.0 purely from rounding, and
    the shared rule's default 1e-6 tolerance would call that financing and
    refuse a target the book can fund. (Rounding *below* 1.0 is safe by
    construction: the rule normalizes an under-funded target up to 100 %.)
    """
    returns = _returns(300, tickers=tickers)
    weights = {ticker: 1 / len(tickers) for ticker in tickers}
    gross = sum(solved.values())
    assert 0 < gross - 1.0 <= 2.5e-5, "fixture must be rounding, not leverage"
    assert normalize_rebalance_weights(solved)["rejection"] is not None, (
        "the default tolerance would have refused this funded target"
    )

    result = await _optimize(returns, weights, solved=solved)
    block = result["weight_normalization"]
    assert block["execution_eligible"] is True
    assert block["financing_required"] is False
    assert block["normalization_mode"] == "fully_funded"
    assert block["gross_exposure"] == pytest.approx(1.0)
    assert block["weights_normalized"] is False
    assert "rejection" not in block
    assert result["weights"] == pytest.approx(solved)


@pytest.mark.asyncio
async def test_optimizer_single_holding_reports_a_funded_block():
    dates = _dates(300)
    prices = pd.Series(
        2_000.0 * np.cumprod(1.0 + np.random.default_rng(31).normal(0.0003, 0.01, len(dates))),
        index=dates,
    )

    async def allocation(_tickers, _db):
        return ["A"], {"A": 1.0}

    class Market:
        async def fetch_historical_data(self, *_args):
            return pd.DataFrame({"adj_close": prices}, index=dates)

    with patch.object(analytics_mod, "resolve_allocation", side_effect=allocation):
        result = await run_optimization(
            body={"strategy": "hrp", "risk_free_rate": 0.03},
            db=None,
            data_service=Market(),
        )

    block = result["weight_normalization"]
    assert block["normalization_rule"] == WEIGHT_NORMALIZATION_RULE
    assert block["execution_eligible"] is True
    assert block["gross_exposure"] == pytest.approx(1.0)
    assert block["net_cash_weight"] == pytest.approx(0.0)
    assert result["risk_free_rate"] == pytest.approx(0.03)
    assert result["latest_observation_date"] == dates[-1].date().isoformat()
    assert result["history_window"]["meets_minimum_sample"] is True
