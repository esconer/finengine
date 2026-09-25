"""Ticket 03: one execution-normalization rule shared by sizing and rebalance.

Volatility sizing publishes an analytical risk-parity target whose legs sum to
the scale factor; the rebalance workflow publishes an execution target that must
be funded from the book's own cash. Before this wave they normalized
independently, so the very same 129 % weights could be pushed through rebalance
and silently executed as a fully funded 100 % book (V3-03).

These regressions pin:

* the single rule name reported by both consumers;
* `half_up` share rounding (half away from zero, not Python's banker's
  rounding) and the reconciliation invariant that depends on it;
* below-minimum-notional reporting for a material sub-lot notional;
* a financed rebalance target being *rejected* instead of normalized down, with
  no durable state change;
* the fully funded, under-funded, and full-exit targets behaving as before.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete, select

from app.models.database import PortfolioPosition
from app.services.analytics_engine import AnalyticsEngine
from app.utils.allocations import (
    AMOUNT_ROUNDING_QUANTUM,
    SHARE_ROUNDING_RULE,
    TRADE_RECONCILIATION_RULE,
    WEIGHT_NORMALIZATION_RULE,
    build_trade_instructions,
    gross_exposure,
    half_up,
    normalization_block,
    normalize_rebalance_weights,
)


# ---------------------------------------------------------------------------
# rounding: half away from zero, not banker's rounding
# ---------------------------------------------------------------------------
def test_half_up_rounds_away_from_zero_where_python_rounds_to_even():
    assert half_up(0.5) == 1
    assert half_up(1.5) == 2
    assert half_up(2.5) == 3  # round(2.5) == 2 (banker's)
    assert half_up(3.5) == 4
    assert half_up(-0.5) == -1
    assert half_up(-2.5) == -3
    assert half_up(0.4999999999) == 0
    assert half_up(0.0) == 0
    assert half_up(2.5) != round(2.5)
    assert half_up(0.5) != round(0.5)


def test_half_up_refuses_non_finite_input_instead_of_inventing_a_count():
    assert half_up(None) is None
    assert half_up(float("nan")) is None
    assert half_up(float("inf")) is None
    assert half_up("not-a-number") is None


# ---------------------------------------------------------------------------
# the shared rule
# ---------------------------------------------------------------------------
def test_gross_exposure_is_the_sum_of_absolute_leg_sizes():
    assert gross_exposure({"A": 0.6, "B": 0.4}) == pytest.approx(1.0)
    assert gross_exposure({"A": 0.9, "B": 0.39}) == pytest.approx(1.29)
    assert gross_exposure({}) == 0.0
    assert gross_exposure({"A": float("nan")}) == 0.0
    assert gross_exposure(None) == 0.0


@pytest.mark.parametrize(
    "weights,mode,eligible",
    [
        ({"A": 0.6, "B": 0.4}, "fully_funded", True),
        ({"A": 0.35, "B": 0.35}, "unlevered_long_only_plus_cash", True),
        ({"A": 0.9, "B": 0.39}, "financed_gross_exposure_exceeds_100_percent", False),
        ({}, "empty_target", True),
    ],
)
def test_normalization_block_names_the_exposure_it_measured(weights, mode, eligible):
    block = normalization_block(weights, portfolio_value=1_000_000.0, currency="INR")
    assert block["normalization_rule"] == WEIGHT_NORMALIZATION_RULE
    assert block["normalization_mode"] == mode
    assert block["execution_eligible"] is eligible
    assert block["financing_required"] is (mode.startswith("financed"))
    if mode.startswith("financed"):
        assert block["financing_requirement"] == pytest.approx(
            (block["gross_exposure"] - 1.0) * 1_000_000.0, abs=0.01
        )
        assert block["financing_requirement_currency"] == "INR"
        assert block["block_reasons"] == ["financing_required"]
    else:
        assert block["financing_requirement"] == 0.0
        assert block["block_reason"] is None or mode == "empty_target"


def test_normalization_block_keeps_financing_unquantified_without_a_budget():
    block = normalization_block({"A": 0.9, "B": 0.39}, currency="INR")
    assert block["financing_required"] is True
    assert block["financing_requirement"] is None
    assert block["execution_eligible"] is False


def test_normalize_rebalance_weights_divides_by_gross_exposure():
    block = normalize_rebalance_weights({"A": 0.35, "B": 0.21})
    assert block["rejection"] is None
    assert block["execution_eligible"] is True
    assert block["weights"] == pytest.approx({"A": 0.625, "B": 0.375})
    assert sum(block["weights"].values()) == pytest.approx(1.0)
    assert block["submitted_gross_exposure"] == pytest.approx(0.56)
    assert block["weights_normalized"] is True
    # An already funded target needs no arithmetic.
    funded = normalize_rebalance_weights({"A": 0.6, "B": 0.4})
    assert funded["weights"] == pytest.approx({"A": 0.6, "B": 0.4})
    assert funded["weights_normalized"] is False


def test_normalize_rebalance_weights_rejects_a_financed_target():
    block = normalize_rebalance_weights({"A": 0.9, "B": 0.39})
    assert block["rejection"]["code"] == "financing_required"
    assert block["rejection"]["gross_exposure"] == pytest.approx(1.29)
    assert block["rejection"]["financing_requirement_fraction"] == pytest.approx(0.29)
    assert block["weights"] is None
    assert block["execution_eligible"] is False
    assert "not a normal rebalance" in block["rejection"]["detail"]


def test_normalize_rebalance_weights_keeps_a_full_exit_legal():
    block = normalize_rebalance_weights({"A": 0.0, "B": 0.0})
    assert block["rejection"] is None
    assert block["weights"] == {"A": 0.0, "B": 0.0}
    assert block["normalization_mode"] == "empty_target"
    assert block["weights_normalized"] is False
    assert block["execution_eligible"] is True


# ---------------------------------------------------------------------------
# trade instruction rules
# ---------------------------------------------------------------------------
def test_material_sub_lot_notional_is_reported_instead_of_zero_shares():
    result = build_trade_instructions(
        {"X": -0.002}, {"X": 10_000.0}, portfolio_value=1_000_000.0, currency="INR",
    )
    trade = result["trades"]["X"]
    assert trade["amount"] == pytest.approx(-2_000.0)
    assert result["reconciliation"]["notional_floor"] == pytest.approx(1_000.0)
    assert abs(trade["amount"]) >= result["reconciliation"]["notional_floor"]
    assert trade["shares_delta"] == 0
    assert trade["below_minimum_notional"] is True
    assert trade["status"] == "below_minimum_notional"
    assert trade["rounding_residual"] == pytest.approx(trade["amount"])
    assert result["reconciliation"]["reconciled"] is True
    assert result["reconciliation"]["below_minimum_notional_tickers"] == ["X"]


def test_immaterial_notional_is_a_no_op_not_a_suppressed_instruction():
    result = build_trade_instructions(
        {"X": 0.00002}, {"X": 10_000.0}, portfolio_value=1_000_000.0, currency="INR",
    )
    trade = result["trades"]["X"]
    assert trade["amount"] == pytest.approx(20.0)
    assert trade["amount"] < result["reconciliation"]["notional_floor"]
    assert trade["shares_delta"] == 0
    assert trade["status"] == "immaterial_no_op"
    assert trade["below_minimum_notional"] is False
    assert result["reconciliation"]["immaterial_no_op_tickers"] == ["X"]
    assert result["reconciliation"]["below_minimum_notional_tickers"] == []


def test_half_up_boundary_reconciles_against_its_rounding_tolerance():
    result = build_trade_instructions(
        {"X": 0.35}, {"X": 140.0}, portfolio_value=1_000.0, currency="INR",
        sizing_price_as_of="2025-06-30",
    )
    trade = result["trades"]["X"]
    # 350.00 / 140.00 == 2.5 exactly.  Half-up buys 3 shares; banker's would buy 2.
    assert trade["shares_delta"] == 3
    assert trade["rounding_residual"] == pytest.approx(350.0 - 3 * 140.0)
    assert abs(trade["rounding_residual"]) <= trade["rounding_tolerance"]
    assert result["share_rounding_rule"] == SHARE_ROUNDING_RULE
    assert result["reconciliation"]["rule"] == TRADE_RECONCILIATION_RULE
    assert result["reconciliation"]["sizing_price_as_of"] == "2025-06-30"
    assert result["reconciliation"]["sizing_price_provenance"] == "measured"
    assert result["reconciliation"]["reconciled"] is True
    assert result["reconciliation"]["max_rounding_tolerance"] == pytest.approx(70.0)


def test_every_priced_trade_reconciles_exactly_to_its_reported_notional():
    result = build_trade_instructions(
        {"A": 0.1, "B": -0.25, "C": 0.0}, {"A": 140.0, "B": 10_000.0, "C": 1.0},
        portfolio_value=250_000.0, currency="INR",
    )
    for trade in result["trades"].values():
        price = trade["sizing_price"]
        assert trade["shares_delta"] == half_up(trade["amount"] / price)
        assert trade["amount"] == pytest.approx(
            trade["shares_delta"] * price + trade["rounding_residual"], abs=0.01
        )
    assert result["reconciliation"]["reconciled"] is True
    assert result["trades"]["C"]["status"] == "no_trade_required"


def test_sub_paisa_price_still_reconciles_within_its_tolerance():
    # The notional is reported at 2 dp, which for a sub-paisa price is coarser
    # than half a share; the published bound has to say so.
    result = build_trade_instructions(
        {"X": 0.0001}, {"X": 0.001}, portfolio_value=100.0, currency="INR",
    )
    trade = result["trades"]["X"]
    assert trade["amount"] == pytest.approx(0.01)
    assert trade["shares_delta"] == half_up(trade["amount"] / 0.001)
    assert abs(trade["rounding_residual"]) <= trade["rounding_tolerance"] + AMOUNT_ROUNDING_QUANTUM
    assert result["reconciliation"]["reconciled"] is True
    assert result["reconciliation"]["amount_rounding_quantum"] == AMOUNT_ROUNDING_QUANTUM


def test_missing_price_is_unavailable_not_an_assumed_one():
    result = build_trade_instructions(
        {"A": 0.1}, {}, portfolio_value=1_000.0, currency="INR",
        sizing_price_provenance="unavailable",
    )
    trade = result["trades"]["A"]
    assert trade["sizing_price"] is None
    assert trade["shares_delta"] is None
    assert trade["status"] == "unavailable"
    assert trade["reason"] == "sizing_price_unavailable"
    # The notional intent survives; only the share count is unknown.
    assert trade["amount"] == pytest.approx(100.0)
    assert result["status"] == "unavailable"
    assert result["reconciliation"]["reconciled"] is False
    assert result["reconciliation"]["unavailable_tickers"] == ["A"]


def test_missing_budget_reports_unavailable_amounts_not_zeroes():
    result = build_trade_instructions(
        {"A": 0.1}, {"A": 140.0}, portfolio_value=None, currency="INR",
    )
    trade = result["trades"]["A"]
    assert trade["amount"] is None
    assert trade["shares_delta"] is None
    assert trade["status"] == "unavailable"
    assert trade["reason"] == "portfolio_value_unavailable"
    assert result["basis"]["portfolio_value"] is None


# ---------------------------------------------------------------------------
# the engine and rebalance publish the same rule
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_engine_publishes_the_rule_the_rebalance_workflow_enforces():
    dates = pd.bdate_range("2025-01-01", periods=300)
    rng = np.random.default_rng(4)
    prices = pd.DataFrame(
        {
            "A": 100.0 * np.cumprod(1.0 + rng.normal(0.0003, 0.004, len(dates))),
            "B": 100.0 * np.cumprod(1.0 + rng.normal(0.0002, 0.005, len(dates))),
        },
        index=dates,
    )
    result = await AnalyticsEngine().volatility_sizing(
        prices, {"A": 0.5, "B": 0.5}, model="EWMA",
        target_volatility=0.40, portfolio_value=1_000_000.0, price_currency="INR",
    )
    assert result["execution"]["normalization_rule"] == WEIGHT_NORMALIZATION_RULE
    assert result["execution"]["execution_eligible"] is False

    # The very weights the engine published are refused as a rebalance target.
    block = normalize_rebalance_weights(result["recommended_weights"])
    assert block["rejection"] is not None
    assert block["rejection"]["code"] == "financing_required"
    assert block["rejection"]["gross_exposure"] == pytest.approx(
        result["execution"]["gross_exposure"], abs=1e-6
    )


# ---------------------------------------------------------------------------
# rebalance route
# ---------------------------------------------------------------------------
async def _seed(db, rows) -> None:
    await db.execute(delete(PortfolioPosition))
    await db.commit()
    db.add_all([PortfolioPosition(**row) for row in rows])
    await db.commit()


_BOOK = [
    {"ticker": "A.NS", "weight": 0.5, "quantity": 10.0, "buy_price": 100.0,
     "last_price": 100.0, "market_value": 1_000.0, "region": "IN", "sector": "Tech"},
    {"ticker": "B.NS", "weight": 0.5, "quantity": 20.0, "buy_price": 250.0,
     "last_price": 250.0, "market_value": 5_000.0, "region": "IN", "sector": "Tech"},
]


@pytest.mark.asyncio
async def test_rebalance_rejects_a_financed_target_without_touching_the_book(
    async_client, test_db
):
    await _seed(test_db, _BOOK)
    resp = await async_client.post(
        "/api/v1/portfolio/rebalance",
        json={"new_weights": {"A.NS": 0.9, "B.NS": 0.39}, "dry_run": True},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "financing_required" in detail
    assert "not a normal rebalance" in detail
    assert WEIGHT_NORMALIZATION_RULE in detail

    rows = (await test_db.execute(select(PortfolioPosition))).scalars().all()
    assert {row.ticker: row.weight for row in rows} == {"A.NS": 0.5, "B.NS": 0.5}


@pytest.mark.asyncio
async def test_rebalance_reports_the_shared_normalization_rule(async_client, test_db):
    await _seed(test_db, _BOOK)
    resp = await async_client.post(
        "/api/v1/portfolio/rebalance",
        json={"new_weights": {"A.NS": 0.7, "B.NS": 0.3}, "dry_run": True},
    )
    assert resp.status_code == 200
    block = resp.json()["weight_normalization"]
    assert block["normalization_rule"] == WEIGHT_NORMALIZATION_RULE
    assert block["normalization_mode"] == "fully_funded"
    assert block["execution_eligible"] is True
    assert block["financing_required"] is False
    assert block["gross_exposure"] == 1.0
    assert block["net_cash_weight"] == 0.0
    assert block["weights_normalized"] is False
    assert sum(resp.json()["simulated_weights"].values()) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_rebalance_normalizes_an_under_funded_target_by_the_same_rule(
    async_client, test_db
):
    await _seed(test_db, _BOOK)
    resp = await async_client.post(
        "/api/v1/portfolio/rebalance",
        json={"new_weights": {"A.NS": 0.35, "B.NS": 0.35}, "dry_run": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    block = data["weight_normalization"]
    assert block["weights_normalized"] is True
    assert block["submitted_gross_exposure"] == pytest.approx(0.7)
    assert block["normalization_mode"] == "fully_funded"
    # Divide every leg by the same gross total: relative sizes are preserved.
    assert data["simulated_weights"] == pytest.approx({"A.NS": 0.5, "B.NS": 0.5})


@pytest.mark.asyncio
async def test_rebalance_rejects_non_finite_and_unknown_targets(
    async_client, test_db
):
    await _seed(test_db, _BOOK)
    # `NaN` is not strict JSON but Python's parser accepts it, so a raw body can
    # still reach the route with a leg that carries no instruction.
    resp = await async_client.post(
        "/api/v1/portfolio/rebalance",
        content='{"new_weights": {"A.NS": 0.5, "B.NS": NaN}, "dry_run": true}',
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 400
    assert "Non-finite" in resp.json()["detail"]

    resp_unknown = await async_client.post(
        "/api/v1/portfolio/rebalance",
        json={"new_weights": {"A.NS": 0.5, "GHOST.NS": 0.5}, "dry_run": True},
    )
    assert resp_unknown.status_code == 400
    assert "Unknown tickers" in resp_unknown.json()["detail"]


@pytest.mark.asyncio
async def test_rebalance_still_allows_a_full_exit(async_client, test_db):
    await _seed(test_db, _BOOK)
    resp = await async_client.post(
        "/api/v1/portfolio/rebalance",
        json={"new_weights": {"A.NS": 0.0, "B.NS": 0.0}, "dry_run": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["simulated_weights"] == {"A.NS": 0.0, "B.NS": 0.0}
    assert data["weight_normalization"]["execution_eligible"] is True
    assert {order["shares_delta"] for order in data["orders"]} == {-10.0, -20.0}
