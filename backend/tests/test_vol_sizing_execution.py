"""Ticket 03: volatility sizing is executable and auditable.

The v3 export published a risk-parity target whose weights summed to
``1.290041`` while reporting ``cash_weight = 0`` and no financing leg (V3-03),
and eight ``shares_delta`` values of ``0`` against large notionals because the
sizing price was a fabricated ``100.0`` and share counts were truncated toward
zero (V3-04). No sizing price, as-of date, or history window was exported at
all.

These regressions pin:

* gross exposure / financing requirement / rebalance eligibility for a
  leveraged analytical target — a 129 % book must never read as zero cash;
* one exported ``sizing_price`` + ``sizing_price_as_of`` per sizing result, and
  a missing price reported as ``unavailable`` rather than assumed;
* amount / integer ``shares_delta`` / sizing-price reconciliation;
* a material sub-lot notional reported as below minimum notional instead of
  silently becoming zero shares;
* the actual history window, observation counts, latest observation, currency
  provenance, and minimum-sample status.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import AnalyticsEngine
from app.utils.allocations import (
    MIN_SIZING_OBSERVATIONS,
    SHARE_ROUNDING_RULE,
    TRADE_RECONCILIATION_RULE,
    build_trade_instructions,
    half_up,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def _frame(spec: dict, days: int = 300, seed: int = 11, start: str = "2025-01-01") -> pd.DataFrame:
    """Deterministic price frame: {ticker: (daily_drift, daily_vol)}."""
    dates = pd.bdate_range(start, periods=days)
    rng = np.random.default_rng(seed)
    data = {}
    for offset, (ticker, (drift, vol)) in enumerate(spec.items()):
        shocks = rng.normal(drift, vol, days)
        data[ticker] = 100.0 * np.cumprod(1.0 + shocks + offset * 0.0001)
    return pd.DataFrame(data, index=dates)


def _low_vol_frame(days: int = 300) -> pd.DataFrame:
    """Two low-volatility legs: a low target is unlevered, a high one borrows."""
    return _frame({"A": (0.0003, 0.004), "B": (0.0002, 0.005)}, days=days, seed=5)


# ---------------------------------------------------------------------------
# gross exposure / financing / eligibility  (V3-03)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_leveraged_target_reports_financing_instead_of_zero_cash():
    engine = AnalyticsEngine()
    prices = _low_vol_frame()
    budget = 1_000_000.0

    result = await engine.volatility_sizing(
        prices, {"A": 0.5, "B": 0.5}, model="EWMA",
        target_volatility=0.40, portfolio_value=budget, price_currency="INR",
    )

    execution = result["execution"]
    gross = sum(abs(v) for v in result["recommended_weights"].values())
    assert gross > 1.0, "fixture must produce a leveraged target"
    assert execution["gross_exposure"] == pytest.approx(gross, abs=1e-6)
    assert execution["financing_required"] is True
    assert execution["execution_eligible"] is False
    assert execution["block_reasons"] == ["financing_required"]
    assert "not a normal rebalance" in execution["block_reason"]
    assert execution["weights_normalized"] is False
    # The financing leg is quantified, never hidden in a zero cash weight.
    assert execution["financing_requirement"] == pytest.approx(
        (gross - 1.0) * budget, abs=0.01
    )
    assert execution["financing_requirement_currency"] == "INR"
    assert execution["net_cash_weight"] < 0
    assert result["cash_weight"] < 0, "a borrowed book must not report zero cash"
    assert result["cash_weight"] == pytest.approx(1.0 - result["scale_factor"], abs=1e-6)
    assert result["leveraged"] is True
    assert "financing required" in result["methodology"]


@pytest.mark.asyncio
async def test_unlevered_target_is_execution_eligible_with_a_cash_residue():
    engine = AnalyticsEngine()
    result = await engine.volatility_sizing(
        _low_vol_frame(), {"A": 0.5, "B": 0.5}, model="EWMA",
        target_volatility=0.03, portfolio_value=1_000_000.0, price_currency="INR",
    )

    execution = result["execution"]
    assert execution["gross_exposure"] < 1.0
    assert execution["normalization_mode"] == "unlevered_long_only_plus_cash"
    assert execution["financing_required"] is False
    assert execution["financing_requirement"] == 0.0
    assert execution["execution_eligible"] is True
    assert execution["block_reasons"] == []
    assert execution["net_cash_weight"] > 0
    assert result["leveraged"] is False
    # Gross exposure plus the cash residue is the whole book.
    assert execution["gross_exposure"] + result["cash_weight"] == pytest.approx(
        1.0, abs=1e-4
    )


@pytest.mark.asyncio
async def test_financing_requirement_is_unavailable_without_a_portfolio_value():
    result = await AnalyticsEngine().volatility_sizing(
        _low_vol_frame(), {"A": 0.5, "B": 0.5}, model="EWMA",
        target_volatility=0.40, price_currency="INR",
    )
    execution = result["execution"]
    assert execution["financing_required"] is True
    assert execution["execution_eligible"] is False
    assert execution["financing_requirement"] is None, (
        "no portfolio value means no quantified financing, not a fabricated zero"
    )


# ---------------------------------------------------------------------------
# sizing price basis  (V3-04)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sizing_price_and_as_of_are_a_single_aligned_snapshot():
    prices = _low_vol_frame()
    result = await AnalyticsEngine().volatility_sizing(
        prices, {"A": 0.5, "B": 0.5}, model="EWMA",
        target_volatility=0.03, portfolio_value=1_000_000.0, price_currency="INR",
    )

    last_date = prices.index[-1].date().isoformat()
    assert result["sizing_price_provenance"] == "measured"
    assert result["sizing_price_as_of"] == last_date
    assert result["sizing_price_currency"] == "INR"
    assert set(result["sizing_price"]) == set(prices.columns)
    for ticker, price in result["sizing_price"].items():
        assert price == pytest.approx(float(prices[ticker].iloc[-1]))
        # Every leg is priced on the same date, so every trade carries it.
        assert result["trades"][ticker]["sizing_price"] == price
    assert result["trade_reconciliation"]["sizing_price_as_of"] == last_date


@pytest.mark.asyncio
async def test_aligned_snapshot_falls_back_to_the_last_common_price_date():
    """A leg that stops quoting moves the whole basis, it is not mixed in."""
    prices = _low_vol_frame()
    stale_from = prices.index[-40]
    prices.loc[prices.index >= stale_from, "B"] = np.nan
    # B must keep enough history to be sized at all.
    assert int(prices["B"].notna().sum()) > MIN_SIZING_OBSERVATIONS

    result = await AnalyticsEngine().volatility_sizing(
        prices, {"A": 0.5, "B": 0.5}, model="EWMA",
        target_volatility=0.03, portfolio_value=1_000_000.0, price_currency="INR",
    )

    expected = prices.index[-41].date().isoformat()
    assert result["sizing_price_as_of"] == expected
    assert "B" in result["recommended_weights"]
    assert result["sizing_price"]["B"] == pytest.approx(float(prices["B"].dropna().iloc[-1]))
    assert result["sizing_price"]["A"] == pytest.approx(float(prices["A"].iloc[-41]))
    assert result["sizing_price_missing_tickers"] == []


@pytest.mark.asyncio
async def test_missing_sizing_price_is_unavailable_never_an_assumed_price():
    """The retired 100.0 fallback is gone: no quote means no executable amount."""
    prices = _low_vol_frame()
    prices["DEAD"] = np.nan  # suspended / delisted: no usable price anywhere
    prices = prices[["A", "B", "DEAD"]]

    result = await AnalyticsEngine().volatility_sizing(
        prices, {"A": 0.4, "B": 0.4, "DEAD": 0.2}, model="EWMA",
        target_volatility=0.03, portfolio_value=1_000_000.0, price_currency="INR",
    )

    assert "DEAD" not in result["recommended_weights"]
    assert result["sizing_price"] == {}
    assert result["sizing_price_provenance"] == "unavailable"
    assert result["sizing_price_as_of"] is None
    assert result["sizing_price_unavailable_reason"] == "no_aligned_price_snapshot"
    assert result["sizing_price_missing_tickers"] == []
    assert result["sizing_price_unpriced_tickers"] == ["DEAD"]
    assert result["trade_instructions_status"] == "unavailable"
    assert result["trade_reconciliation"]["reconciled"] is False
    for trade in result["trades"].values():
        assert trade["sizing_price"] is None
        assert trade["shares_delta"] is None
        assert trade["status"] == "unavailable"
        assert trade["reason"] == "sizing_price_unavailable"
        assert trade["rounding_residual"] is None
        # The notional intent is still reported; only the share count is unknown.
        assert trade["amount"] is not None


@pytest.mark.asyncio
async def test_currency_provenance_is_unavailable_when_the_engine_cannot_infer_it():
    result = await AnalyticsEngine().volatility_sizing(
        _low_vol_frame(), {"A": 0.5, "B": 0.5}, model="EWMA",
        target_volatility=0.03, portfolio_value=1_000_000.0,
    )
    assert result["sizing_price_currency"] is None
    assert result["price_currency_provenance"] == "unavailable"
    assert result["execution"]["financing_requirement_currency"] is None


# ---------------------------------------------------------------------------
# amount / share reconciliation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_trade_amount_and_shares_reconcile_against_the_exported_price():
    budget = 1_000_000.0
    result = await AnalyticsEngine().volatility_sizing(
        _low_vol_frame(), {"A": 0.55, "B": 0.45}, model="EWMA",
        target_volatility=0.03, portfolio_value=budget, price_currency="INR",
    )

    assert result["trade_reconciliation"]["rule"] == TRADE_RECONCILIATION_RULE
    assert result["trade_reconciliation"]["share_rounding_rule"] == SHARE_ROUNDING_RULE
    assert result["trade_reconciliation"]["reconciled"] is True
    assert result["trade_reconciliation"]["priced_trades"] == len(result["trades"])

    for ticker, trade in result["trades"].items():
        price = result["sizing_price"][ticker]
        amount = trade["amount"]
        # The notional is the number that was divided by the sizing price.
        assert amount == pytest.approx(
            (result["recommended_weights"][ticker]
             - ({"A": 0.55, "B": 0.45}[ticker])) * budget, abs=0.01
        )
        assert trade["shares_delta"] == half_up(amount / price)
        assert isinstance(trade["shares_delta"], int)
        assert trade["amount"] == pytest.approx(
            trade["shares_delta"] * price + trade["rounding_residual"], abs=0.01
        )
        assert abs(trade["rounding_residual"]) <= trade["rounding_tolerance"] + 1e-9
        assert trade["amount_currency"] == "INR"
        assert trade["status"] in {"executable", "no_trade_required"}


@pytest.mark.asyncio
async def test_material_sub_lot_trade_is_reported_not_silently_zero_shares():
    """V3-04: a large notional that rounds to zero shares must stay visible."""
    engine = AnalyticsEngine()
    budget = 1_000_000.0
    dates = pd.bdate_range("2025-01-01", periods=300)
    rng = np.random.default_rng(3)
    # B is priced an order of magnitude above the notional floor, so a small
    # weight change is a material notional that cannot buy a whole share.
    prices = pd.DataFrame(
        {
            "A": 100.0 * np.cumprod(1.0 + rng.normal(0.0002, 0.005, len(dates))),
            "B": np.linspace(100.0, 10_000.0, len(dates))
            * np.cumprod(1.0 + rng.normal(0.0, 0.01, len(dates))),
        },
        index=dates,
    )

    first = await engine.volatility_sizing(
        prices, {"A": 0.5, "B": 0.5}, model="EWMA",
        target_volatility=0.03, portfolio_value=budget, price_currency="INR",
    )
    recommended = dict(first["recommended_weights"])
    price_b = first["sizing_price"]["B"]
    assert price_b > 3_000.0, "fixture must keep B above the sub-lot band"

    # Nudge only B's current weight; the analytical target is unchanged because
    # inverse-volatility weights depend on volatilities, not on current sizes.
    delta = 0.0015  # notional 1500.00, floor is 0.1% of budget = 1000.00
    second = await engine.volatility_sizing(
        prices, {"A": recommended["A"], "B": recommended["B"] + delta}, model="EWMA",
        target_volatility=0.03, portfolio_value=budget, price_currency="INR",
    )
    assert second["recommended_weights"] == pytest.approx(recommended, abs=1e-6)

    trade = second["trades"]["B"]
    assert trade["amount"] == pytest.approx(-delta * budget, abs=0.01)
    assert abs(trade["amount"]) >= second["trade_reconciliation"]["notional_floor"]
    assert abs(trade["amount"]) < 0.5 * price_b
    assert trade["shares_delta"] == 0
    assert trade["below_minimum_notional"] is True
    assert trade["status"] == "below_minimum_notional"
    # A sub-lot trade is a real outcome, so it must SAY why it rounds to zero:
    # the notional is above the order floor but below one whole share. An empty
    # reason read as "nothing unusual happened".
    assert trade["reason"], "a sub-lot trade must state why it rounds to zero"
    assert "below one whole share" in trade["reason"]
    # The money that cannot be traded in whole shares is published, not lost.
    assert trade["rounding_residual"] == pytest.approx(trade["amount"], abs=0.01)
    assert second["trade_reconciliation"]["reconciled"] is True
    assert second["trade_reconciliation"]["below_minimum_notional_tickers"] == ["B"]
    # A leg that genuinely does not move is not reported as a suppressed trade.
    assert second["trades"]["A"]["status"] == "no_trade_required"
    assert second["trades"]["A"]["below_minimum_notional"] is False


@pytest.mark.asyncio
async def test_missing_portfolio_value_reports_unavailable_amounts_not_zeroes():
    result = await AnalyticsEngine().volatility_sizing(
        _low_vol_frame(), {"A": 0.4, "B": 0.6}, model="EWMA",
        target_volatility=0.03, price_currency="INR",
    )
    assert result["trade_instructions_status"] == "unavailable"
    assert result["trade_reconciliation"]["reconciled"] is False
    for trade in result["trades"].values():
        assert trade["amount"] is None
        assert trade["shares_delta"] is None
        assert trade["status"] == "unavailable"
        assert trade["reason"] == "portfolio_value_unavailable"


# ---------------------------------------------------------------------------
# history / sample disclosure
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sizing_history_reports_window_observations_and_minimum_sample():
    prices = _low_vol_frame(days=300)
    result = await AnalyticsEngine().volatility_sizing(
        prices, {"A": 0.5, "B": 0.5}, model="EWMA",
        target_volatility=0.03, portfolio_value=1_000_000.0, price_currency="INR",
    )

    history = result["sizing_history"]
    assert history["model"] == "EWMA"
    # A return needs two prices: the measured window starts one bar in.
    assert history["window_start"] == prices.index[1].date().isoformat()
    assert history["window_end"] == prices.index[-1].date().isoformat()
    assert history["price_window_start"] == prices.index[0].date().isoformat()
    assert history["price_window_end"] == prices.index[-1].date().isoformat()
    assert history["return_observations"] == len(prices) - 1
    assert history["latest_observation"] == prices.index[-1].date().isoformat()
    assert history["per_ticker_return_observations"] == {"A": 299, "B": 299}
    assert history["min_return_observations"] == 299
    assert history["max_return_observations"] == 299
    assert history["minimum_observations_required"] == MIN_SIZING_OBSERVATIONS
    assert history["meets_minimum_sample"] is True
    assert history["minimum_sample_status"] == "sufficient"
    assert history["tickers_below_minimum_sample"] == []


@pytest.mark.asyncio
async def test_short_history_is_flagged_instead_of_silently_annualized():
    prices = _low_vol_frame(days=12)
    result = await AnalyticsEngine().volatility_sizing(
        prices, {"A": 0.5, "B": 0.5}, model="EWMA",
        target_volatility=0.03, portfolio_value=1_000_000.0, price_currency="INR",
    )

    history = result["sizing_history"]
    assert history["return_observations"] == 11 < MIN_SIZING_OBSERVATIONS
    assert history["meets_minimum_sample"] is False
    assert history["minimum_sample_status"] == "insufficient"
    assert sorted(history["tickers_below_minimum_sample"]) == ["A", "B"]
    assert history["window_start"] == prices.index[1].date().isoformat()
    assert history["price_window_start"] == prices.index[0].date().isoformat()
    assert history["latest_observation"] == prices.index[-1].date().isoformat()
    # The weights are still real: short history is disclosed, not invented.
    assert set(result["recommended_weights"]) == {"A", "B"}


@pytest.mark.asyncio
async def test_one_short_leg_is_named_in_the_minimum_sample_report():
    prices = _low_vol_frame(days=300)
    # B only quoted for the first 25 bars: 24 return observations, below the gate.
    prices.loc[prices.index[25:], "B"] = np.nan

    result = await AnalyticsEngine().volatility_sizing(
        prices, {"A": 0.5, "B": 0.5}, model="EWMA",
        target_volatility=0.03, portfolio_value=1_000_000.0, price_currency="INR",
    )

    history = result["sizing_history"]
    assert history["tickers_below_minimum_sample"] == ["B"]
    assert history["min_return_observations"] == 24 < MIN_SIZING_OBSERVATIONS
    assert history["max_return_observations"] == 299
    assert history["per_ticker_return_observations"] == {"A": 299, "B": 24}
    assert history["meets_minimum_sample"] is False
    assert history["minimum_sample_status"] == "insufficient"
    assert "B" in result["recommended_weights"]


# ---------------------------------------------------------------------------
# fail-closed paths
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_empty_sizing_publishes_no_price_and_no_execution_block():
    result = await AnalyticsEngine().volatility_sizing(
        pd.DataFrame(), {"A": 1.0}, model="EWMA", target_volatility=0.15
    )
    assert result["recommended_weights"] == {}
    assert result["trades"] == {}
    assert result["error"] == "Insufficient data for volatility sizing"
    # No price may be implied by the empty path either.
    assert "sizing_price" not in result
    assert "execution" not in result


def test_build_trade_instructions_publishes_the_documented_rules():
    result = build_trade_instructions(
        {"X": 0.35}, {"X": 140.0}, portfolio_value=1_000.0, currency="INR",
        sizing_price_as_of="2025-06-30",
    )
    assert result["share_rounding_rule"] == SHARE_ROUNDING_RULE
    assert result["reconciliation"]["rule"] == TRADE_RECONCILIATION_RULE
    assert result["reconciliation"]["sizing_price_as_of"] == "2025-06-30"
    assert result["basis"]["sizing_price_as_of"] == "2025-06-30"
    # 350.00 / 140.00 == 2.5 exactly: half-up buys 3 shares, banker's would buy 2.
    assert result["trades"]["X"]["shares_delta"] == 3
    assert result["trades"]["X"]["amount"] == 350.0
    assert result["trades"]["X"]["rounding_residual"] == -70.0
    assert result["reconciliation"]["reconciled"] is True
