"""The v4 audit's remaining NUMERIC contradictions, one test each (V4).

Every defect here was independently recomputed from a regenerated export of
`/api/v1/ai/context?format=json&detail=summary`, and every test below pins the
recomputed value rather than the shape of a block. A test that only asserted
"the key exists" is what let each of these through the first time.

The families:

1. a summary that published a MINIMUM under a `max_` name (vol sizing);
2. a table whose whole purpose is to be added up, where the delta did not close
   against the legs printed beside it (optimizer trades);
3. a 2e-6 shortfall displayed as exactly fully funded (optimizer gross);
4. a headline GPD shape that was not the one the reported risk came from;
5. a POT threshold that read as a contradiction of `confidence_level` and said
   nothing about which level was fitted and which reported;
6. rounding residuals nobody published (liquidity bands, regime percentages) and
   a dimensionless share map sitting next to `annualized: true` with no unit;
7. an undocumented `spread` and an undisclosed score ceiling;
8. a `stability_pct` derivable from nothing, beside a transition matrix whose
   uniform 96.0 diagonal is a PRIOR, not an estimate;
9. two cointegration tests that a consumer would sum to 8 out of 91 pairs;
10. two `portfolio_value`s and a sizing price three sessions stale;
11. per-ticker counts in three units under one name, and one section still
    answering the holding window in price rows.

No network, no DB, no vendor calls: seeded RNG and the route seams only.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from app.api import analytics as analytics_mod
from app.api.analytics import (
    CONTRIBUTION_DECIMALS,
    CONTRIBUTION_UNIT,
    HOLDING_COVERED_DAYS_SCOPE,
    HOLDING_WIDE_FRAME_COVERED_DAYS_SCOPE,
    LIQUIDITY_RECOMPUTATION_ALIASES,
    LIQUIDITY_RECOMPUTATION_BASIS,
    LIQUIDITY_RECOMPUTATION_KEY,
    LIQUIDITY_SPREAD_DEFINITION,
    LIQUIDITY_SPREAD_NOTE,
    LIQUIDITY_SPREAD_UNIT,
    LIQUIDITY_TIER_LADDER,
    PRICE_FRAME_COUNT_UNITS,
    RETURN_FRAME_COUNT_UNITS,
    TRADE_AGGREGATE_SCOPE,
    TRADE_WEIGHT_DECIMALS,
    _contribution_basis_block,
    _gpd_shape_usage_disclosure,
    _liquidity_score_spread_disclosure,
    _liquidity_tier_values,
    _liquidity_volume_band_residual,
    _pairs_test_agreement,
    _pot_threshold_disclosure,
    _regime_percentage_residuals,
    _regime_stability_disclosure,
    _trade_reconciliation_disclosure,
    _weight_normalization_block,
    get_cointegration_pairs,
    get_factor_exposure,
    get_risk_contribution,
    get_volatility_sizing,
    run_optimization,
)
from app.models.database import PortfolioPosition
from app.services.analytics_engine import AnalyticsEngine

BARS = 700
#: The routes read `datetime.now()` for their requested end, so the fixtures are
#: anchored to the same day rather than to a hard-coded one: a hard-coded end in
#: the past would fall outside the canonical holding evidence window and quietly
#: change what a section measures.
END = pd.Timestamp.now().normalize()
TODAY = END.strftime("%Y-%m-%d")


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


def _pos(ticker, *, added_on, buy_price=None, sector="Tech", last_price=100.0):
    return PortfolioPosition(
        id=1, ticker=ticker, weight=0.5, quantity=10.0, buy_price=buy_price,
        last_price=last_price, market_value=10000.0, region="IN",
        sector=sector, industry="Y", added_on=added_on,
    )


class _WindowedMarket:
    """Price frames served for the REQUESTED window only."""

    def __init__(self, frames: Dict[str, pd.DataFrame]):
        self.frames = frames
        self.fetch_historical_data = AsyncMock(side_effect=self._fetch)

    async def _fetch(self, ticker, start, end):
        frame = self.frames.get(ticker)
        if frame is None or frame.empty:
            return pd.DataFrame()
        low = pd.Timestamp(start).normalize() if start else frame.index[0]
        high = pd.Timestamp(end).normalize() if end else frame.index[-1]
        return frame.loc[(frame.index >= low) & (frame.index <= high)].copy()


def _frame(ticker: str, seed: int, periods: int = BARS, end: str = TODAY) -> pd.DataFrame:
    dates = pd.bdate_range(end=pd.Timestamp(end), periods=periods)
    rng = np.random.default_rng(seed)
    walk = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.011, periods)))
    return pd.DataFrame({"adj_close": pd.Series(walk, index=dates)})


#: Sessions inside the canonical holding evidence window, so a fixture position's
#: stored import date is inside the window the buy-price inference may look at.
EVIDENCE_BARS = 170


def _evidence_frame(ticker: str, seed: int) -> pd.DataFrame:
    return _frame(ticker, seed, EVIDENCE_BARS)


def _regime_payload(**overrides):
    payload = {
        "current_regime": "calm",
        "regime": "calm",
        "probability_unit": "posterior_probability",
        "benchmark": "^NSEI",
        "posterior_type": "filtered",
        "units": {"returns": "fraction"},
        "observations": 719,
        "stability_pct": 96.7,
        "regime_probabilities": {"crisis": 99.9993, "calm": 0.0006, "bull": 0.0},
        "states": [
            {"regime": "crisis", "ann_ret": -0.2666, "ann_vol": 0.1124,
             "historical_days_pct": 30.9},
            {"regime": "calm", "ann_ret": 0.1228, "ann_vol": 0.1096,
             "historical_days_pct": 53.3},
            {"regime": "bull", "ann_ret": 0.8627, "ann_vol": 0.1965,
             "historical_days_pct": 15.9},
        ],
        "transition_matrix": {
            "crisis": {"crisis": 96.0, "calm": 3.0, "bull": 1.0},
            "calm": {"crisis": 2.0, "calm": 96.0, "bull": 2.0},
            "bull": {"crisis": 1.0, "calm": 3.0, "bull": 96.0},
        },
        "recent_history": [{"regime": "calm"} for _ in range(120)],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# 1. the `max_rounding_tolerance` that published the minimum
# ---------------------------------------------------------------------------
def _trade(ticker, price, *, amount, shares, status="executable"):
    residual = round(amount - shares * price, 2)
    return {
        ticker: {
            "shares_delta": shares,
            "amount": amount,
            "sizing_price": price,
            "rounding_residual": residual,
            "rounding_tolerance": round(0.5 * price, 6),
            "status": status,
            "below_minimum_notional": status == "below_minimum_notional",
            "reason": None,
        }
    }


# The live book's geometry: MCX.NS has the widest tolerance (3262.60 * 0.5) and
# MIDCAPIETF.NS the narrowest (23.54 * 0.5). The engine published the minimum
# under a `max_` name, understating the bound by 1631.300049 / 11.77 = 138.6x.
MCX_PRICE = 3262.60009765625
ETF_PRICE = 23.540000915527344
CIPLA_PRICE = 1384.0999755859375


def _audit_trades() -> Dict[str, Any]:
    trades: Dict[str, Any] = {}
    trades.update(_trade("MCX.NS", MCX_PRICE, amount=-1109.62, shares=0,
                         status="below_minimum_notional"))
    trades.update(_trade("MIDCAPIETF.NS", ETF_PRICE, amount=2253.91, shares=96))
    trades.update(_trade("CIPLA.NS", CIPLA_PRICE, amount=-418.99, shares=0))
    return trades


def test_max_rounding_tolerance_publishes_the_maximum_not_the_minimum():
    """1: 1631.300049 is the maximum; 11.77 is the minimum."""
    trades = _audit_trades()
    block = _trade_reconciliation_disclosure(
        {
            "rule": "shares_delta == half_up(amount / sizing_price)",
            "amount_decimals": 2,
            "amount_rounding_quantum": 0.005,
            "reconciled": True,
            "priced_trades": 3,
            # What the engine published: the MINIMUM, under a `max_` name.
            "max_rounding_tolerance": round(0.5 * ETF_PRICE, 6),
            "max_abs_rounding_residual": 1109.62,
        },
        trades,
    )
    true_max = max(entry["rounding_tolerance"] for entry in trades.values())
    true_min = min(entry["rounding_tolerance"] for entry in trades.values())
    assert true_max == 1631.300049
    assert true_min == 11.77
    assert block["max_rounding_tolerance"] == true_max
    assert block["max_rounding_tolerance_ticker"] == "MCX.NS"
    # The minimum is not lost: it is published under the name it always was.
    assert block["min_rounding_tolerance"] == true_min
    # The residual maximum is a DIFFERENT measurement, so both declare theirs.
    assert block["max_abs_rounding_residual"] == 1109.62
    assert block["max_abs_rounding_residual_ticker"] == "MCX.NS"
    assert block["max_rounding_tolerance_scope"] == TRADE_AGGREGATE_SCOPE
    assert block["max_abs_rounding_residual_scope"] == TRADE_AGGREGATE_SCOPE
    assert block["aggregates_source"] == "recomputed_from_delivered_trades"
    # Every trade is inside ITS OWN tolerance, so the book is reconciled and the
    # breaches list is empty - the defect was never a bad trade.
    assert block["tolerance_breach_tickers"] == []
    for entry in trades.values():
        assert abs(entry["rounding_residual"]) <= (
            entry["rounding_tolerance"] + 0.005 + 1e-9
        )


def test_tolerance_breach_is_measured_per_trade_not_inferred():
    """A trade outside its own tolerance is named, so `reconciled` is auditable."""
    trades = _audit_trades()
    # A leg whose residual is 10x its own half-share tolerance.
    trades["BROKEN.NS"] = {
        "shares_delta": 1, "amount": 500.0, "sizing_price": 10.0,
        "rounding_residual": 45.0, "rounding_tolerance": 5.0,
        "status": "executable", "below_minimum_notional": False, "reason": None,
    }
    block = _trade_reconciliation_disclosure(
        {"amount_decimals": 2, "amount_rounding_quantum": 0.005,
         "reconciled": True, "priced_trades": 4},
        trades,
    )
    assert block["tolerance_breach_tickers"] == ["BROKEN.NS"]
    # The aggregates still describe the whole priced population, breaches and all.
    assert block["max_abs_rounding_residual"] == 1109.62
    assert block["max_rounding_tolerance"] == 1631.300049


def test_reconciliation_disclosure_is_absent_when_the_engine_published_none():
    """A degraded engine published no block: nothing is invented for it."""
    assert _trade_reconciliation_disclosure(None, _audit_trades()) == {}
    assert _trade_reconciliation_disclosure("not-a-mapping", {}) == {}


# ---------------------------------------------------------------------------
# 2. the trade delta that did not close against its own legs
# ---------------------------------------------------------------------------
def _optimizer_fixture():
    """Two legs whose UNROUNDED difference rounds away from the published legs.

    REDINGTON.NS is the live case: recommended 0.03565 -> 0.0357, current
    0.07475 -> 0.0747. The unrounded delta is -0.0391 while the published legs
    differ by -0.0390, so a table whose purpose is to be added up disagreed with
    itself by 1e-4.
    """
    return {"A": 0.03565, "B": 0.96435}, {"A": 0.07475, "B": 0.92525}


def test_weight_delta_closes_against_the_published_legs():
    solved, current = _optimizer_fixture()
    unrounded_delta = round(solved["A"] - current["A"], TRADE_WEIGHT_DECIMALS)
    published_legs_delta = round(
        round(solved["A"], 4) - round(current["A"], 4), TRADE_WEIGHT_DECIMALS
    )
    assert unrounded_delta == -0.0391
    assert published_legs_delta == -0.0390
    # A trade list is executed and audited from the numbers it prints, so the
    # delta is the difference of the PUBLISHED legs.
    assert published_legs_delta == round(0.0357 - 0.0747, 4)


@pytest.mark.asyncio
async def test_optimizer_trades_close_and_declare_their_basis():
    dates = pd.bdate_range(end=TODAY, periods=400)
    rng = np.random.default_rng(7)
    returns = pd.DataFrame(
        rng.normal(0.0004, 0.01, (len(dates), 2)),
        index=dates,
        columns=["A", "B"],
    )
    # Unrounded solved weights whose 4dp legs differ from the 4dp unrounded delta.
    solved = {"A": 0.03565, "B": 0.96435}
    current = {"A": 0.07475, "B": 0.92525}

    async def allocation(_tickers, _db):
        return ["A", "B"], dict(current)

    async def build(_tickers, _weights, _start, _end, _service):
        return returns, returns.mean(axis=1), {}

    async def fake_optimize(*_a, **_k):
        return {
            "weights": solved,
            "expected_annual_return": 0.1,
            "expected_annual_volatility": 0.15,
            "expected_sharpe": 0.4,
            "solver": "test",
            "error": None,
        }

    with patch.object(analytics_mod, "resolve_allocation", side_effect=allocation), \
         patch.object(analytics_mod, "_build_wide_returns", side_effect=build), \
         patch.object(analytics_mod, "optimize", new=fake_optimize):
        result = await run_optimization(body={"strategy": "hrp"}, db=None, data_service=None)

    trades = result["trades_required"]
    assert trades, "the fixture must produce at least one trade"
    for ticker, row in trades.items():
        # The whole point: a reader can add this up.
        assert row["weight_delta"] == round(
            row["recommended_weight"] - row["current_weight"], TRADE_WEIGHT_DECIMALS
        )
    # The audited export published -0.0391 here, which is what
    # 0.03565 - 0.07475 rounds to; the PUBLISHED legs (0.0357, 0.0747) differ by
    # -0.0390, and the delta now follows the legs.
    assert trades["A"]["weight_delta"] == -0.0390
    assert trades["A"]["recommended_weight"] == 0.0357
    assert trades["A"]["current_weight"] == 0.0747
    assert round(0.03565 - 0.07475, 4) == -0.0391  # the old, non-closing answer
    assert trades["B"]["weight_delta"] == 0.0391
    assert trades["B"]["recommended_weight"] - trades["B"]["current_weight"] == (
        pytest.approx(0.0391, abs=1e-12)
    )

    basis = result["trades_required_basis"]
    assert basis["weight_decimals"] == TRADE_WEIGHT_DECIMALS
    assert basis["trade_count"] == len(trades)
    assert basis["current_weights_rounding_residual"] == pytest.approx(
        1.0 - basis["current_weights_published_total"], abs=1e-12
    )
    assert basis["recommended_weights_rounding_residual"] == pytest.approx(
        1.0 - basis["recommended_weights_published_total"], abs=1e-12
    )


# ---------------------------------------------------------------------------
# 3. the 2e-6 shortfall displayed as exactly fully funded
# ---------------------------------------------------------------------------
def test_gross_exposure_residual_is_published_and_financing_is_unrounded():
    """A 0.999998 target published 1.0 and `financing_required: false`."""
    weights = {
        "A": 0.333333, "B": 0.333333, "C": 0.333332,
    }
    measured = sum(weights.values())
    assert measured == pytest.approx(0.999998, abs=1e-12)
    block = _weight_normalization_block(weights)
    # The residual that rounds away inside the shared rule's 6dp answer.
    assert block["submitted_gross_exposure"] == 0.999998
    assert block["submitted_gross_exposure_measured"] == pytest.approx(0.999998)
    assert block["gross_exposure"] == 1.0
    assert block["gross_exposure_residual"] == pytest.approx(-2e-6, abs=1e-12)
    assert block["weights_normalized"] is False
    # The decision is made on the unrounded figure, and says so.
    assert block["financing_required"] is False
    assert block["financing_required_basis"] == "unrounded_submitted_gross_exposure"
    assert block["gross_exposure_tolerance"] == analytics_mod._SOLVER_GROSS_TOLERANCE


def test_financing_required_follows_the_unrounded_gross_exposure():
    """A genuinely levered target is still rejected, rounding or not."""
    levered = {"A": 0.6, "B": 0.4002}
    assert sum(levered.values()) > 1.0
    block = _weight_normalization_block(levered)
    # The unrounded figure is what the decision is made from. A rejected target
    # reports the submitted gross on both sides, so nothing is normalized away.
    assert block["submitted_gross_exposure_measured"] == pytest.approx(1.0002, abs=1e-12)
    assert block["submitted_gross_exposure"] == pytest.approx(1.0002, abs=1e-9)
    assert block["gross_exposure"] == pytest.approx(1.0002, abs=1e-9)
    assert block["gross_exposure_residual"] == pytest.approx(0.0, abs=1e-12)
    assert block["financing_required"] is True
    assert "rejection" in block


def test_full_exit_still_reports_a_zero_residual():
    block = _weight_normalization_block({"A": 0.0, "B": 0.0})
    assert block["gross_exposure"] == 0.0
    assert block["gross_exposure_residual"] == 0.0
    assert block["financing_required"] is False
    assert block["execution_eligible"] is True


# ---------------------------------------------------------------------------
# 4. the GPD shape that did not produce the reported risk
# ---------------------------------------------------------------------------
def _clipped_evt() -> Dict[str, Any]:
    return {
        "confidence_level": 0.99,
        "evt_pot_var": -0.036708,
        "evt_pot_es": -0.041074,
        "evt_pot_var_unconstrained": -0.034584,
        "gpd_shape_xi": -0.7068,
        "gpd_shape_xi_raw": -0.70676185,
        "gpd_shape_xi_constrained": -0.5,
        "gpd_shape_constrained": True,
        "constraint_applied": True,
        "constraint_reason": "gpd_shape_clipped",
    }


def test_gpd_shape_used_is_the_value_the_risk_came_from():
    stats = _clipped_evt()
    used = _gpd_shape_usage_disclosure(stats)
    # The service deliberately publishes the RAW fit as `gpd_shape_xi`, and the
    # metrics come from the clipped one. The used value is named explicitly.
    assert stats["gpd_shape_xi"] == -0.7068
    assert used["gpd_shape_xi_used"] == -0.5
    assert used["gpd_shape_xi_used_basis"] == "constrained_clip"
    assert used["gpd_shape_xi_used_basis"] != "raw_maximum_likelihood_fit"
    assert used["gpd_shape_constraint_reason"] == "gpd_shape_clipped"
    assert used["gpd_shape_xi_raw_equals_published_headline"] is True
    assert used["gpd_shape_xi_raw_field"] == "gpd_shape_xi_raw"
    # And the service's own raw fields survive untouched beside it.
    assert stats["gpd_shape_xi_raw"] == -0.70676185


def test_unclipped_fit_names_the_raw_value_as_used():
    stats = {
        "gpd_shape_xi": -0.12, "gpd_shape_xi_raw": -0.1204,
        "gpd_shape_xi_constrained": -0.12, "gpd_shape_constrained": False,
        "constraint_reason": None,
    }
    used = _gpd_shape_usage_disclosure(stats)
    assert used["gpd_shape_xi_used"] == -0.1204
    assert used["gpd_shape_xi_used_basis"] == "raw_maximum_likelihood_fit"
    assert used["gpd_shape_constraint_reason"] is None


def test_absent_fit_publishes_unavailable_rather_than_a_number():
    used = _gpd_shape_usage_disclosure({"constraint_reason": "fit_failed"})
    assert used["gpd_shape_xi_used"] is None
    assert used["gpd_shape_xi_used_basis"] == "unavailable"


# ---------------------------------------------------------------------------
# 5. the POT threshold that read as a contradiction of confidence_level
# ---------------------------------------------------------------------------
def test_pot_threshold_basis_is_declared_with_the_measured_fraction():
    """26 / 518 = 5.02% fitted, 0.99 reported. Different levels, both named."""
    stats = {
        "confidence_level": 0.99,
        "threshold_u": 0.020464,
        "exceedances_count": 26,
        "total_observations": 518,
    }
    block = _pot_threshold_disclosure(
        stats, confidence_level=0.99, threshold_quantile=0.95
    )["pot_threshold_basis"]
    assert block["exceedance_fraction"] == pytest.approx(26 / 518, abs=1e-6)
    assert block["exceedance_fraction"] == pytest.approx(0.050193, abs=1e-6)
    assert block["threshold_quantile"] == 0.95
    assert block["reported_level"] == 0.99
    # The two levels are different quantities and the block says which is which.
    assert block["level_fields"] == {
        "fitted": "threshold_u", "reported": "confidence_level",
    }
    assert "different levels" in block["rule"]
    # The `_99` suffix names the REPORTED level, not the fitted threshold.
    assert "REPORTED level" in block["suffixed_field_rule"]
    assert block["threshold_u"] == 0.020464


def test_pot_threshold_basis_degrades_instead_of_inventing_a_fraction():
    block = _pot_threshold_disclosure(
        {"exceedances_count": None, "total_observations": None},
        confidence_level=0.99, threshold_quantile=0.95,
    )["pot_threshold_basis"]
    assert block["exceedance_fraction"] is None
    assert block["exceedances_count"] is None
    # A zero-observation fit cannot be divided.
    block = _pot_threshold_disclosure(
        {"exceedances_count": 0, "total_observations": 0},
        confidence_level=0.99, threshold_quantile=0.95,
    )["pot_threshold_basis"]
    assert block["exceedance_fraction"] is None


# ---------------------------------------------------------------------------
# 6. rounding residuals nobody published
# ---------------------------------------------------------------------------
def test_liquidity_band_residual_is_measured_not_renormalized():
    stats = {"high_volume_pct": 71.4, "medium_volume_pct": 21.4, "low_volume_pct": 7.1}
    block = _liquidity_volume_band_residual(
        stats,
        positions={
            "A": {"category": "High"}, "B": {"category": "High"},
            "C": {"category": "Medium"}, "D": {"category": "Low"},
        },
    )
    assert block["volume_band_pct_total"] == pytest.approx(99.9, abs=1e-9)
    assert block["volume_band_rounding_residual"] == pytest.approx(0.1, abs=1e-9)
    assert block["volume_band_rounding_decimals"] == 1
    assert block["volume_band_measured_positions"] == 4
    assert block["volume_band_position_counts"] == {"High": 2, "Medium": 1, "Low": 1}
    # The 7.1% band is one position in four, not a 0.1%-adjusted one.
    assert 1 / 4 * 100 == 25.0
    assert "rounded to 1 decimal" in block["volume_band_basis"]


def test_incomplete_band_column_reports_unavailable_not_a_zero_residual():
    block = _liquidity_volume_band_residual(
        {"high_volume_pct": 71.4, "medium_volume_pct": None}, positions={}
    )
    assert block["volume_band_rounding_residual"] is None
    assert "unavailable" in block["volume_band_basis"]


def test_regime_percentage_residuals_are_published():
    """states 100.1, probabilities 99.9999, matrix rows 100.0."""
    out = _regime_percentage_residuals(_regime_payload())
    assert out["historical_days_pct_total"] == pytest.approx(100.1, abs=1e-9)
    assert out["historical_days_pct_rounding_residual"] == pytest.approx(-0.1, abs=1e-9)
    assert out["historical_days_pct_rounding_decimals"] == 1
    assert out["regime_probabilities_total"] == pytest.approx(99.9999, abs=1e-9)
    assert out["regime_probabilities_rounding_residual"] == pytest.approx(
        0.0001, abs=1e-9
    )
    assert out["regime_probabilities_rounding_decimals"] == 4
    assert out["transition_matrix_row_residual_max_abs"] == pytest.approx(0.0, abs=1e-9)
    assert set(out["transition_matrix_row_residuals"]) == {"crisis", "calm", "bull"}
    # Nothing is renormalized: the published values are what they were.
    assert sum(s["historical_days_pct"] for s in _regime_payload()["states"]) == 100.1


def test_regime_residuals_degrade_when_an_aggregate_is_missing():
    out = _regime_percentage_residuals({"states": [], "regime_probabilities": {}})
    assert "historical_days_pct_total" not in out
    assert "regime_probabilities_total" not in out
    assert "transition_matrix_row_residuals" not in out


# ---------------------------------------------------------------------------
# 6b. the dimensionless share map beside `annualized: true`
# ---------------------------------------------------------------------------
def test_contribution_shares_declare_their_unit_and_residual():
    positions = {
        "volatility": {"A": 0.333334, "B": 0.333333, "C": 0.333331},
        "cvar_tail": {"A": 0.5, "B": 0.4999995},
    }
    block = _contribution_basis_block(positions, {"volatility": {"Tech": 0.999998}})
    assert block["unit"] == CONTRIBUTION_UNIT == "fraction_of_portfolio_risk"
    assert block["rounding_decimals"] == CONTRIBUTION_DECIMALS
    volatility = block["per_model"]["volatility"]
    assert sum(positions["volatility"].values()) == pytest.approx(0.999998, abs=1e-9)
    assert volatility["published_total"] == pytest.approx(0.999998, abs=1e-9)
    assert volatility["rounding_residual"] == pytest.approx(2e-6, abs=1e-9)
    assert volatility["leg_count"] == 3
    cvar = block["per_model"]["cvar_tail"]
    assert sum(positions["cvar_tail"].values()) == pytest.approx(0.9999995, abs=1e-12)
    assert cvar["rounding_residual"] == pytest.approx(5e-7, abs=1e-9)
    # The residual is the DISPLAY rounding; the shares themselves are not
    # renormalized to hide it.
    assert "normalized to 1.0" in block["normalization"]
    # `annualized: true` describes the volatility model's window, not the shares.
    assert "annualized" in block["annualized_note"]
    assert block["sector_rollup_per_model"]["volatility"]["rounding_residual"] == (
        pytest.approx(2e-6, abs=1e-9)
    )


def test_contribution_block_survives_an_empty_model():
    block = _contribution_basis_block({"volatility": {}}, {})
    assert block["per_model"]["volatility"]["published_total"] is None
    assert block["per_model"]["volatility"]["rounding_residual"] is None
    assert block["per_model"]["volatility"]["leg_count"] == 0


# ---------------------------------------------------------------------------
# 7. the undocumented spread and the undisclosed score ceiling
# ---------------------------------------------------------------------------
def test_spread_is_declared_as_an_assumed_tier_formula_not_a_score_difference():
    positions = {
        "CIPLA.NS": {
            "score": 9.2, "score_raw": 9.240271, "spread": 0.0004,
            "avg_turnover": 1_201_357_007.8095238, "category": "High",
        },
        "SELECTIPO.NS": {
            "score": 3.4, "score_raw": 3.390135, "spread": 0.0056,
            "avg_turnover": 2_690_584.292588234, "category": "Low",
        },
    }
    block, per_position = _liquidity_score_spread_disclosure(positions)
    assert block["unit"] == LIQUIDITY_SPREAD_UNIT == "fraction_of_price"
    assert block["definition"] == LIQUIDITY_SPREAD_DEFINITION
    assert block["provenance"] == "model_assumed"
    assert block["observed"] is False
    assert "NOT abs(score - score_raw)" in block["note"]
    # The obvious wrong reading is off by two orders of magnitude.
    assert abs(positions["CIPLA.NS"]["score"] - positions["CIPLA.NS"]["score_raw"]) == (
        pytest.approx(0.040271, abs=1e-6)
    )
    assert positions["CIPLA.NS"]["spread"] == 0.0004
    # The declared formulas REPRODUCE the published spread, which is what makes
    # the declaration evidence rather than a paraphrase.
    assert block[LIQUIDITY_RECOMPUTATION_KEY]["confirmed_count"] == 2
    assert block[LIQUIDITY_RECOMPUTATION_KEY]["unconfirmed_count"] == 0
    assert per_position["CIPLA.NS"]["spread_formula_confirmed"] is True
    assert per_position["CIPLA.NS"]["spread_tier"] == "tier_1"
    assert per_position["SELECTIPO.NS"]["spread_tier"] == "tier_4"
    assert per_position["CIPLA.NS"]["spread_recomputed"] == 0.0004
    assert per_position["SELECTIPO.NS"]["spread_recomputed"] == 0.0056
    assert len(block["tier_ladder"]) == 4


def test_score_ceiling_is_disclosed_when_a_leg_clamps_to_the_scale_maximum():
    """MCX.NS published score_raw 10.0, which is the tier-1 clamp, not a measurement."""
    saturated = 6_490_322_599.168143
    ladder = _liquidity_tier_values(saturated)
    assert ladder[0][1] == 10.0
    block, per_position = _liquidity_score_spread_disclosure({
        "MCX.NS": {
            "score": 10.0, "score_raw": 10.0, "spread": 0.0003,
            "avg_turnover": saturated, "category": "High",
        },
    })
    assert block["score_ceiling"]["scale_max"] == 10.0
    assert block["score_ceiling"]["positions_at_ceiling"] == ["MCX.NS"]
    assert block["score_ceiling"]["positions_at_ceiling_count"] == 1
    assert per_position["MCX.NS"]["score_ceiling_applied"] is True
    assert "CAPPED value" in block["score_ceiling"]["rule"]
    # The spread is on the tier's own plateau, so it stops responding to turnover.
    assert per_position["MCX.NS"]["spread_at_tier_plateau"] is True
    assert block["spread_at_tier_plateau"]["positions"] == ["MCX.NS"]


def test_a_leg_that_entered_its_tier_on_market_cap_is_still_reproduced():
    """The engine's predicate is `turnover >= X or market_cap >= Y`.

    RELIANCE-like leg: turnover 1e8 is a tier-2 turnover, but a 6e11 cap clears
    tier 1's cap arm, so the engine published tier 1.  Re-deriving on turnover
    alone evaluates [tier_2, tier_3, tier_4]: it reports tier 2's spread, which
    the engine never published, and matches no tier's score, so a correct score
    is stamped "unconfirmed" with a spread from the wrong tier.
    """
    turnover, market_cap = 1e8, 6e11
    # Engine, analytics_engine.py:3935-3937: tier 1 by the cap arm.
    engine_score_raw = round(min(10.0, 9.0 + min(1.0, (turnover / 1e9) * 0.2)), 6)
    engine_spread = round(
        max(0.0002, 0.0006 - min(0.0003, (turnover / 2e9) * 0.0003)), 4
    )
    assert engine_score_raw == 9.02
    assert engine_spread == 0.0006

    # Without the cap the leg is not in tier 1's ladder at all...
    turnover_only = [row[0] for row in _liquidity_tier_values(turnover)]
    assert turnover_only == ["tier_2", "tier_3", "tier_4"]
    # ...and with it, tier 1 is present and reproduces the published values.
    with_cap = {row[0]: row for row in _liquidity_tier_values(turnover, market_cap)}
    assert list(with_cap) == ["tier_1", "tier_2", "tier_3", "tier_4"]
    assert with_cap["tier_1"][1] == engine_score_raw
    assert with_cap["tier_1"][2] == engine_spread

    block, per_position = _liquidity_score_spread_disclosure({
        "CAPDRIVEN.NS": {
            "score": 9.0, "score_raw": engine_score_raw, "spread": engine_spread,
            "avg_turnover": turnover, "market_cap": market_cap, "category": "High",
        },
    })
    facts = per_position["CAPDRIVEN.NS"]
    assert facts["spread_tier"] == "tier_1"
    assert facts["spread_recomputed"] == 0.0006
    assert facts["spread_formula_confirmed"] is True
    assert block[LIQUIDITY_RECOMPUTATION_KEY]["unconfirmed_tickers"] == []


def test_an_absent_market_cap_cannot_satisfy_the_cap_arm():
    """A row with no cap must fall back to the turnover ladder, not guess one."""
    assert [row[0] for row in _liquidity_tier_values(1e8)] == [
        "tier_2", "tier_3", "tier_4",
    ]
    assert [row[0] for row in _liquidity_tier_values(1e8, None)] == [
        "tier_2", "tier_3", "tier_4",
    ]
    _, per_position = _liquidity_score_spread_disclosure({
        "NOCAP.NS": {
            "score": 8.0, "score_raw": 8.02, "spread": 0.0013,
            "avg_turnover": 1e8, "category": "High",
        },
    })
    # An unknown cap cannot raise the ladder to a tier that was never measured.
    # The confirmation still holds here because the published spread is
    # reproduced by a tier the engine could have applied: had the cap arm added
    # tier_1, the engine's published spread would be tier 1's and this leg would
    # have come back unconfirmed instead.
    assert per_position["NOCAP.NS"]["spread_tier"] == "tier_2"
    assert per_position["NOCAP.NS"]["spread_recomputed"] == 0.0013
    assert per_position["NOCAP.NS"]["spread_formula_confirmed"] is True


# ---------------------------------------------------------------------------
# 7b. the count block and the note describe the PREDICATE, not one of its inputs
# ---------------------------------------------------------------------------
# The engine's tier predicate is a disjunction, `avg_turnover >= X or market_cap
# >= Y`, but the block that re-derives the published values was named
# `recomputed_from_avg_turnover` and the note described the spread as coming from
# turnover alone. Both were published strings asserting something the code had
# stopped doing, and they were easy to miss precisely because
# `LIQUIDITY_TIER_LADDER` already published the `or market_cap` arm: the two
# strings agreed with each other and with the table, and all three understated the
# predicate. The rename is the visible fix; the tests below are the durable one -
# they join the note, the ladder table, `_liquidity_tier_values` and the ENGINE
# into one chain, so an arm added to any one of them and not the others fails.

#: (avg_turnover, market_cap, tier the engine scores on), read off the engine's
#: own if/elif chain - `analytics_engine.liquidity_analysis`, the four arms at
#: `daily_turnover >= 500000000.0 or mc >= 500000000000.0` and the two `elif`s
#: below it.  Restated independently on purpose: a table generated from
#: `LIQUIDITY_TIER_LADDER` or from `_liquidity_tier_values` would agree with
#: itself and catch nothing.  Values sit clear of every threshold so a float
#: round-trip cannot land a case on a boundary.
ENGINE_TIER_CASES = (
    (6.0e8, None, "tier_1"),     # tier 1 by the TURNOVER arm
    (1.2e8, 6.0e11, "tier_1"),   # tier 1 by the CAP arm alone
    (1.2e8, 2.0e11, "tier_2"),   # tier 2 by the CAP arm alone
    (1.2e8, None, "tier_2"),     # tier 2 by the TURNOVER arm
    (5.0e7, 2.0e10, "tier_3"),   # tier 3 by the CAP arm alone
    (5.0e7, None, "tier_3"),     # tier 3 by the TURNOVER arm
    (1.0e6, None, "tier_4"),     # neither arm: the otherwise row
)


def _turnover_frame(daily_turnover: float) -> pd.DataFrame:
    """Constant price/volume frame, so the engine's daily turnover is exact."""
    periods = 30
    return pd.DataFrame(
        {
            "Close": [1.0] * periods,
            "Volume": [daily_turnover] * periods,
        },
        index=pd.date_range(start="2024-01-01", periods=periods, freq="D"),
    )


class TestTheReDerivationNamesBothInputs:
    def test_the_count_block_is_named_for_the_inputs_it_is_evaluated_on(self):
        """The canonical name may not assert turnover alone.  It is not a
        function of turnover: `_liquidity_tier_values` is handed the cap as well,
        and dropping it re-derives a ladder the engine never applied."""
        assert LIQUIDITY_RECOMPUTATION_KEY == "recomputed_from_avg_turnover_and_market_cap"
        assert "avg_turnover" in LIQUIDITY_RECOMPUTATION_KEY
        assert "market_cap" in LIQUIDITY_RECOMPUTATION_KEY
        block, _ = _liquidity_score_spread_disclosure({})
        assert LIQUIDITY_RECOMPUTATION_KEY in block
        assert block["recomputation"]["canonical"] == LIQUIDITY_RECOMPUTATION_KEY
        assert block["recomputation"]["inputs"] == ["avg_turnover", "market_cap"]
        assert block["recomputation"]["basis"] == LIQUIDITY_RECOMPUTATION_BASIS
        assert "or market_cap >=" in block["recomputation"]["basis"]


class TestTheRetiredCountKeyIsRedirectedNotDropped:
    def test_the_old_key_resolves_through_the_alias_map(self):
        """A consumer keying on `recomputed_from_avg_turnover` must be able to
        find its way.  Dropping the name without publishing the rename is the same
        defect from the other side: the key would resolve to nothing and nothing
        would say why."""
        assert LIQUIDITY_RECOMPUTATION_ALIASES == {
            "recomputed_from_avg_turnover": LIQUIDITY_RECOMPUTATION_KEY,
        }
        block, _ = _liquidity_score_spread_disclosure({
            "A.NS": {
                "score": 9.2, "score_raw": 9.240271, "spread": 0.0004,
                "avg_turnover": 1_201_357_007.8095238, "category": "High",
            },
        })
        recomputation = block["recomputation"]
        assert recomputation["aliases"] == LIQUIDITY_RECOMPUTATION_ALIASES
        for retired, canonical in recomputation["aliases"].items():
            assert canonical in recomputation["canonical"], (retired, canonical)
            # the key it redirects to is one this block actually publishes
            assert canonical in block, canonical
            assert block[canonical] is block[LIQUIDITY_RECOMPUTATION_KEY]
            assert block[canonical]["confirmed_tickers"] == ["A.NS"]
        assert "recomputed_from_avg_turnover" in LIQUIDITY_RECOMPUTATION_BASIS

    def test_the_retired_name_is_not_published_as_a_second_key(self):
        """The failure mode an alias KEY would reintroduce.

        A second key is not a migration aid here: it puts two names for one block
        in one object, which is the original defect.
        """
        block, _ = _liquidity_score_spread_disclosure({})
        assert not set(LIQUIDITY_RECOMPUTATION_ALIASES) & set(block)

    def test_no_published_number_moved_under_the_rename(self):
        """Pins the block's whole payload, so a rename that also recomputed
        something would fail rather than read as a naming change."""
        block, _ = _liquidity_score_spread_disclosure({
            "CIPLA.NS": {
                "score": 9.2, "score_raw": 9.240271, "spread": 0.0004,
                "avg_turnover": 1_201_357_007.8095238, "category": "High",
            },
            "GHOST.NS": {
                "score": 7.0, "score_raw": 7.0, "spread": 0.0099,
                "avg_turnover": 1_000_000.0, "category": "High",
            },
        })
        assert block[LIQUIDITY_RECOMPUTATION_KEY] == {
            "confirmed_count": 1,
            "unconfirmed_count": 1,
            "confirmed_tickers": ["CIPLA.NS"],
            "unconfirmed_tickers": ["GHOST.NS"],
        }


class TestTheNoteDescribesThePredicate:
    def test_the_note_restates_every_predicate_the_ladder_publishes(self):
        """The link that failed: the ladder published `or market_cap >= Y` and
        the prose did not.  An arm added to the table and not the note is the
        exact next drift, and this is the test that catches it."""
        for tier in LIQUIDITY_TIER_LADDER:
            assert tier["applies_when"] in LIQUIDITY_SPREAD_NOTE, tier["id"]

    def test_the_note_states_the_cap_thresholds_rather_than_gesturing_at_them(self):
        """A disclosure that cannot be checked against the code is worse than a
        wrong one, because it looks like evidence."""
        for threshold in ("5e11", "1e11", "1e10"):
            assert f"market_cap >= {threshold}" in LIQUIDITY_SPREAD_NOTE, threshold
        # And the fact that makes the arm matter: the NUMBER is turnover-only
        # while the ROW is not.  Stated as the distinction, not as a hedge.
        assert "THE NUMBER IS A FUNCTION OF avg_turnover ALONE" in LIQUIDITY_SPREAD_NOTE
        assert "WHICH LADDER ROW APPLIES IS NOT" in LIQUIDITY_SPREAD_NOTE
        assert "NOT abs(score - score_raw)" in LIQUIDITY_SPREAD_NOTE
        # `LIQUIDITY_SPREAD_DEFINITION` is deliberately NOT renamed: the spread
        # VALUE really is a function of a turnover formula, so the enum is true
        # of the number and only the TIER is turnover-or-cap.  Pinned so a later
        # wave cannot quietly fold the two together.
        assert LIQUIDITY_SPREAD_DEFINITION == (
            "assumed_bid_ask_spread_from_turnover_tier_formula"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("turnover, market_cap, engine_tier", ENGINE_TIER_CASES)
    async def test_the_note_the_ladder_and_the_engine_agree_on_one_predicate(
        self, turnover, market_cap, engine_tier
    ):
        """The whole chain, against the real engine rather than a restatement.

        `_liquidity_tier_values` is the predicate the route actually evaluates,
        `LIQUIDITY_TIER_LADDER` is the published table, `LIQUIDITY_SPREAD_NOTE` is
        the published prose, and `liquidity_analysis` is what produced the
        published number.  An arm added to any one of the four and not the other
        three breaks a link here.
        """
        engine = AnalyticsEngine()
        result = await engine.liquidity_analysis(
            {"AAA.NS": _turnover_frame(turnover)},
            market_caps=({"AAA.NS": market_cap} if market_cap is not None else None),
        )
        published = result["by_position"]["AAA.NS"]
        # The engine's cap is never absent, which is what the note claims; the
        # re-derivation is handed the same value the engine used.
        assert published["market_cap"] > 0.0

        ladder = _liquidity_tier_values(turnover, published["market_cap"])
        # 1. the first row the re-derivation offers IS the tier the engine used
        assert ladder[0][0] == engine_tier
        assert ladder[0][1] == published["score_raw"]
        assert ladder[0][2] == published["spread"]
        # 2. the published table has a row for it...
        row = next(t for t in LIQUIDITY_TIER_LADDER if t["id"] == engine_tier)
        # 3. ...and the published prose restates that row's predicate verbatim.
        assert row["applies_when"] in LIQUIDITY_SPREAD_NOTE
        # 4. and the block confirms the leg rather than publishing a guess.
        block, per_position = _liquidity_score_spread_disclosure(
            result["by_position"]
        )
        assert per_position["AAA.NS"]["spread_tier"] == engine_tier
        assert per_position["AAA.NS"]["spread_formula_confirmed"] is True
        assert per_position["AAA.NS"]["spread_recomputed"] == published["spread"]
        assert block[LIQUIDITY_RECOMPUTATION_KEY]["confirmed_count"] == 1
        assert block[LIQUIDITY_RECOMPUTATION_KEY]["unconfirmed_count"] == 0

    @pytest.mark.asyncio
    async def test_dropping_the_cap_arm_would_break_the_chain(self):
        """Why the cap arm is in the name, demonstrated rather than asserted.

        Re-derive this leg on turnover alone and the ladder is a different
        ladder: the engine published tier_1 through its cap, the turnover-only
        ladder does not contain tier_1 at all, and the leg's published values
        are unreproducible.  That is what the old key name asserted was not
        happening.
        """
        engine = AnalyticsEngine()
        result = await engine.liquidity_analysis(
            {"AAA.NS": _turnover_frame(1.2e8)}, market_caps={"AAA.NS": 6.0e11}
        )
        published = result["by_position"]["AAA.NS"]
        assert published["score_raw"] == pytest.approx(9.024, abs=1e-9)

        without_cap = _liquidity_tier_values(published["avg_turnover"], None)
        assert "tier_1" not in {row[0] for row in without_cap}
        assert not any(row[1] == published["score_raw"] for row in without_cap)

        _, per_position = _liquidity_score_spread_disclosure({
            "AAA.NS": {k: v for k, v in published.items() if k != "market_cap"},
        })
        assert per_position["AAA.NS"]["spread_formula_confirmed"] is False
        assert per_position["AAA.NS"]["spread_tier"] is None



def test_a_leg_the_formulas_cannot_reproduce_says_so():
    positions = {
        "GHOST.NS": {
            "score": 7.0, "score_raw": 7.0, "spread": 0.0099,
            "avg_turnover": 1_000_000.0, "category": "High",
        },
    }
    block, per_position = _liquidity_score_spread_disclosure(positions)
    assert per_position["GHOST.NS"]["spread_formula_confirmed"] is False
    assert per_position["GHOST.NS"]["spread_tier"] is None
    assert block[LIQUIDITY_RECOMPUTATION_KEY]["unconfirmed_tickers"] == ["GHOST.NS"]
    assert per_position["GHOST.NS"]["score_ceiling_applied"] is False


def test_a_leg_with_no_turnover_publishes_null_not_a_guess():
    _, per_position = _liquidity_score_spread_disclosure({
        "NONE.NS": {"score": None, "score_raw": None, "spread": None,
                    "avg_turnover": None, "category": None},
    })
    entry = per_position["NONE.NS"]
    assert entry["spread_tier"] is None
    assert entry["spread_recomputed"] is None
    assert entry["spread_formula_confirmed"] is False
    assert entry["score_ceiling_applied"] is False


# ---------------------------------------------------------------------------
# 8. the stability_pct derivable from nothing, and the prior transition matrix
# ---------------------------------------------------------------------------
def test_stability_pct_declares_its_rule_and_is_not_the_transition_diagonal():
    result = _regime_payload()
    block = _regime_stability_disclosure(result)
    assert result["stability_pct"] == 96.7
    # The uniform diagonal is 96.0, so stability_pct is not that number.
    assert {row[state] for row in result["transition_matrix"].values() for state in row} == {
        96.0, 3.0, 1.0, 2.0
    }
    assert result["stability_pct"] != 96.0
    assert block["stability_pct_scope"] == (
        "full_classification_sample_consecutive_label_transitions"
    )
    assert block["stability_pct_unit"] == "percent_0_to_100"
    assert block["stability_pct_observations"] == 719
    assert "1 - share of consecutive observations" in block["stability_pct_rule"]
    # 96.7 over 718 transitions is 24 flips; 96.64 is the 120-day rate.
    flips = round((1.0 - 96.7 / 100.0) * 718)
    assert 1 - flips / 718 == pytest.approx(0.966573, abs=1e-6)


def test_transition_matrix_declares_that_it_is_a_configured_prior():
    block = _regime_stability_disclosure(_regime_payload())
    provenance = block["transition_matrix_provenance"]
    assert provenance["source"] == "configured_sticky_prior"
    assert provenance["estimated"] is False
    assert provenance["estimated_parameters"] == "means_and_covariances_only"
    assert "never re-estimated" in provenance["rule"]
    assert provenance["rounding_decimals"] == 1
    # The uniform 96.0 diagonal is the prior's persistence, not an estimate.
    diagonals = {state: row[state] for state, row in _regime_payload()["transition_matrix"].items()}
    assert set(diagonals.values()) == {96.0}


def test_recent_history_rate_is_recomputed_and_labelled_separately():
    history = [{"regime": "bull"} for _ in range(120)]
    for index in (5, 30, 60, 90, 110):
        history[index]["regime"] = "crisis"  # five transitions change label
    block = _regime_stability_disclosure(_regime_payload(recent_history=history))
    assert block["recent_history_transitions"] == 119
    # Each isolated flip changes two consecutive transitions, so ten of 119.
    assert block["recent_history_self_transition_pct"] == pytest.approx(
        100.0 * 109 / 119, abs=1e-4
    )
    assert "NOT stability_pct" in block["recent_history_note"]
    # The live export's 115/119 = 96.6387, which is not 96.7 either.
    assert block["recent_history_self_transition_pct"] != 96.7


def test_stability_disclosure_without_a_recent_history():
    block = _regime_stability_disclosure({"stability_pct": 96.7})
    assert "recent_history_self_transition_pct" not in block
    assert block["stability_pct_observations"] is None


# ---------------------------------------------------------------------------
# 9. the two cointegration tests a consumer would sum to 8
# ---------------------------------------------------------------------------
class _Pair:
    def __init__(self, a, b, decision, diagnostic):
        self.ticker_a = a
        self.ticker_b = b
        self.is_cointegrated = decision
        self.johansen_cointegrated = diagnostic


def test_pairs_agreement_is_counted_so_the_two_tests_are_never_summed():
    """Engle-Granger 4, Johansen 4, ZERO overlap: summing them reports 8."""
    pairs = [
        _Pair("A", "B", True, False), _Pair("C", "D", True, False),
        _Pair("E", "F", True, False), _Pair("G", "H", True, False),
        _Pair("I", "J", False, True), _Pair("K", "L", False, True),
        _Pair("M", "N", False, True), _Pair("O", "P", False, True),
        _Pair("Q", "R", True, True), _Pair("S", "T", False, False),
    ]
    block = _pairs_test_agreement(pairs)
    assert block["decision_positive_count"] == 5
    assert block["diagnostic_positive_count"] == 5
    assert block["counted_pairs"] == 10
    # Q/R carries both flags and S/T carries neither: those are the agreements.
    assert block["agreement_count"] == 2
    assert block["disagreement_count"] == 8
    assert block["decision_positive_only_count"] == 4
    assert block["diagnostic_positive_only_count"] == 4
    # Summing the two positives is 10; only 9 pairs carry at least one flag.
    assert block["decision_positive_count"] + block["diagnostic_positive_count"] == 10
    assert "must NOT be added" in block["summed_count_note"]
    assert "9 are flagged by at least one test" in block["summed_count_note"]
    # Johansen stays the diagnostic it was declared to be.
    assert block["test_roles"]["johansen"] == "diagnostic_only"
    assert block["decision_test"] == "engle_granger"


def test_pairs_agreement_on_the_exported_geometry():
    """The audited book: 4 and 4, no overlap, out of 91 scanned pairs."""
    decision = [("JUNIORBEES.NS", "MOTILALOFS.NS"), ("JKIL.NS", "NIFTYIETF.NS"),
                ("ELECTCAST.NS", "MCX.NS"), ("JUNIORBEES.NS", "MIDCAPIETF.NS")]
    diagnostic = [("CIPLA.NS", "JUNIORBEES.NS"), ("ELECTCAST.NS", "JKIL.NS"),
                  ("CIPLA.NS", "MIDCAPIETF.NS"), ("CIPLA.NS", "NTPC.NS")]
    pairs = [
        _Pair(a, b, (a, b) in decision, (a, b) in diagnostic)
        for a, b in decision + diagnostic
    ]
    block = _pairs_test_agreement(pairs)
    assert block["decision_positive_count"] == 4
    assert block["diagnostic_positive_count"] == 4
    assert block["agreement_count"] == 0
    assert block["disagreement_count"] == 8
    assert not set(block["decision_positive_pairs"]) & set(
        block["diagnostic_positive_pairs"]
    )


@pytest.mark.asyncio
async def test_pairs_route_publishes_the_agreement_block():
    """End to end over a real scan: the block counts the delivered rows."""
    frames = {
        "A": _frame("A", 1, 300), "B": _frame("B", 2, 300),
        "C": _frame("C", 3, 300), "D": _frame("D", 4, 300),
    }
    market = _WindowedMarket(frames)
    result = await get_cointegration_pairs(
        tickers="A,B,C,D", lookback_days=756, p_value_threshold=0.05,
        max_half_life=60, include_spread_series=False,
        db=None, data_service=market, cache_service=SimpleNamespace(),
    )
    block = result.test_agreement
    rows = list(result.pairs)
    assert block["counted_pairs"] == len(rows)
    assert block["decision_positive_count"] == sum(
        1 for row in rows if row.is_cointegrated
    )
    assert block["diagnostic_positive_count"] == sum(
        1 for row in rows if row.johansen_cointegrated
    )
    # Agreement plus disagreement is every delivered row, exactly once.
    assert block["agreement_count"] + block["disagreement_count"] == len(rows)
    # And the published pair lists are the rows the two flags name, so a
    # consumer can rebuild the union instead of adding two counts.
    union = set(block["decision_positive_pairs"]) | set(block["diagnostic_positive_pairs"])
    expected = {
        f"{row.ticker_a}/{row.ticker_b}"
        for row in rows
        if row.is_cointegrated or row.johansen_cointegrated
    }
    assert union == expected
    assert block["decision_positive_only_count"] + block[
        "diagnostic_positive_only_count"
    ] <= len(union)
    assert block["test_roles"]["johansen"] == "diagnostic_only"
    assert "must NOT be added" in block["summed_count_note"]
    # The disclosure subclass still drops a clean scan's `error` key.
    assert "error" not in result.model_dump()


# ---------------------------------------------------------------------------
# 9b. a diagnostic that produced NO verdict is not a disagreement
# ---------------------------------------------------------------------------
# `johansen_cointegrated` is a tri-state: `None` says the statistic was not
# computable, so no second verdict exists to compare the decision against. The
# aggregate folded it into the disagreement bucket, and both halves of that fold
# are silent: `bool(None)` is `False`, and `None == False` is `True` in Python,
# so the coercion and the equality each publish a refused computation as a
# measured negative. The whole block then closed over two buckets and read as
# though every pair had been compared.


def _tri_state_pairs() -> list:
    """Two pairs whose diagnostic refused, among pairs that measured cleanly."""
    return [
        _Pair("A", "B", True, True),     # measured agreement
        _Pair("C", "D", True, False),    # measured disagreement
        _Pair("E", "F", False, False),   # measured agreement
        _Pair("G", "H", True, None),     # REFUSED
        _Pair("I", "J", False, None),    # REFUSED
    ]


def test_a_refused_diagnostic_is_counted_as_unavailable_not_as_a_disagreement():
    block = _pairs_test_agreement(_tri_state_pairs())

    assert block["unavailable_count"] == 2
    assert block["unavailable_pairs"] == ["G/H", "I/J"]
    # Only the ONE pair where two tests ran and opposed each other.
    assert block["disagreement_count"] == 1
    assert block["agreement_count"] == 2
    # And the three buckets close over every delivered row, exactly once.
    assert (
        block["agreement_count"]
        + block["disagreement_count"]
        + block["unavailable_count"]
        == block["counted_pairs"]
    )


def test_a_refused_diagnostic_is_still_a_decision_measurement():
    """G/H is decision-positive and the decision test DID run on it. Recording it
    only in `unavailable` would drop it out of the positive counts and make the
    summed-count note under-report the decision test's own hits."""
    block = _pairs_test_agreement(_tri_state_pairs())

    assert block["decision_positive_count"] == 3  # A/B, C/D and G/H
    assert block["diagnostic_positive_count"] == 1  # A/B only
    assert "G/H" in block["decision_positive_pairs"]
    assert "G/H" not in block["diagnostic_positive_pairs"]
    # Exactly one pair is both decision-positive and refused: G/H. I/J is
    # refused too, but Engle-Granger never declared it cointegrated, so nothing
    # was withheld from it.
    assert set(block["decision_positive_pairs"]) & set(block["unavailable_pairs"]) == {
        "G/H"
    }


def test_the_note_states_that_a_refusal_exists_and_how_many():
    """`summed_count_note` is where a reader learns what the counts mean. A
    refusal in neither positive list makes the note's arithmetic quietly
    incomplete, so the note has to name the third bucket itself."""
    block = _pairs_test_agreement(_tri_state_pairs())
    note = block["summed_count_note"]

    assert "must NOT be added" in note
    assert "9 are flagged by at least one test" not in note  # 4 are, here
    assert "3 are flagged by at least one test" in note
    assert "2 of the 5 counted pairs published NO johansen verdict" in note
    assert "unavailable_count" in note
    assert "not a disagreement between two verdicts" in note


def test_a_fully_measured_book_publishes_the_same_note_it_always_did():
    """The negative half. A note that grew a sentence on every clean scan would
    be noise, and noise is how a real degradation goes unread."""
    block = _pairs_test_agreement([_Pair("A", "B", True, True)])
    note = block["summed_count_note"]

    assert "unavailable_count" not in note
    assert "NO johansen verdict" not in note
    assert block["unavailable_count"] == 0
    assert block["unavailable_pairs"] == []


def test_a_fully_measured_book_is_byte_identical_to_the_two_bucket_block():
    """No published figure may move when every pair computed.

    The regression this guards is the quiet one: a fix that routes `None` to a
    third bucket has no reason to touch a book with no `None` in it, but
    "has no reason to" is not a measurement. The reference below is the
    pre-fix two-bucket aggregate, transcribed, and every key it publishes is
    compared for EQUALITY - not for approximate equality, not for the keys
    this file happens to assert on.
    """
    # The audited book's real geometry: 5 decision-positive, 5 diagnostic-
    # positive, one overlap, every pair computed.
    decision = {
        "ARROWGREEN.NS/MOTHERSON.NS", "ELECTCAST.NS/MCX.NS", "JKIL.NS/NIFTYIETF.NS",
        "JUNIORBEES.NS/MOTILALOFS.NS", "MOTHERSON.NS/NTPC.NS",
    }
    diagnostic = {
        "CIPLA.NS/JUNIORBEES.NS", "ELECTCAST.NS/JKIL.NS", "CIPLA.NS/MIDCAPIETF.NS",
        "CIPLA.NS/NTPC.NS", "JKIL.NS/NIFTYIETF.NS",
    }
    pairs = [
        _Pair(*key.split("/"), key in decision, key in diagnostic)
        for key in decision | diagnostic
    ]
    block = _pairs_test_agreement(pairs)

    before = {
        "decision_test": "engle_granger",
        "diagnostic_test": "johansen",
        "test_roles": {
            "engle_granger": "published_decision",
            "johansen": "diagnostic_only",
        },
        "counted_pairs": 9,
        "decision_positive_count": 5,
        "diagnostic_positive_count": 5,
        "agreement_count": 1,
        "disagreement_count": 8,
        "decision_positive_only_count": 4,
        "diagnostic_positive_only_count": 4,
        "decision_positive_pairs": sorted(decision),
        "diagnostic_positive_pairs": sorted(diagnostic),
        "summed_count_note": (
            "is_cointegrated and johansen_cointegrated are different tests and "
            "must NOT be added: a pair can carry both. is_cointegrated "
            "(engle_granger) is the published decision; johansen_cointegrated "
            "is diagnostic_only. Summing the two positive counts would report "
            "10 pairs where only 9 are flagged by at least one test."
        ),
    }

    assert block.keys() - before.keys() == {"unavailable_count", "unavailable_pairs"}
    assert before.keys() - block.keys() == set()
    for key, value in before.items():
        assert block[key] == value, key


def test_a_refused_pair_is_never_published_as_a_data_conflict():
    """The defect class, stated as the invariant it violates: a computation that
    could not run is not evidence about a pair, so it may not appear in any
    count that names a comparison between the two tests."""
    block = _pairs_test_agreement(_tri_state_pairs())
    refused = set(block["unavailable_pairs"])
    decision_positive = set(block["decision_positive_pairs"])

    # G/H is decision-positive and refused. It is the one pair where the old
    # aggregate asserted a conflict between two verdicts that were never both
    # produced, so it is the pair this invariant is about.
    assert (refused & decision_positive) == {"G/H"}
    # The refusal reached neither bucket. agreement_count is 2 (A/B, E/F) and
    # disagreement_count is 1 (C/D): one measured conflict on the whole book,
    # not three.
    assert block["disagreement_count"] == 1
    assert block["agreement_count"] == 2
    # And the positive lists, which are the only place a consumer rebuilds the
    # comparison from, name no refusal as a diagnostic measurement.
    assert not set(block["diagnostic_positive_pairs"]) & refused
    assert refused.isdisjoint({"A/B", "C/D", "E/F"})


# ---------------------------------------------------------------------------
# 10/11. the routes: sizing price freshness, portfolio value, per-ticker units
# ---------------------------------------------------------------------------
def _sizing_engine_result(portfolio_value: float) -> Dict[str, Any]:
    prices = {"A": 48.84, "B": 100.0}
    return {
        "recommended_weights": {"A": 0.6, "B": 0.4},
        "trades": {
            ticker: {
                "shares_delta": 5, "amount": 5.0 * price,
                "sizing_price": price, "rounding_residual": 0.0,
                "rounding_tolerance": round(0.5 * price, 6),
                "status": "executable", "below_minimum_notional": False,
                "reason": None,
            }
            for ticker, price in prices.items()
        },
        "trade_reconciliation": {
            "rule": "shares_delta == half_up(amount / sizing_price)",
            "amount_decimals": 2,
            "amount_rounding_quantum": 0.005,
            "reconciled": True,
            "priced_trades": 2,
            "max_rounding_tolerance": 24.42,
            "max_abs_rounding_residual": 0.0,
        },
        "sizing_price": prices,
        "sizing_price_as_of": "2026-09-22",
        "sizing_price_currency": "INR",
        "price_currency_provenance": "measured",
        "sizing_price_provenance": "measured",
        "sizing_history": {"window_start": "2026-01-02", "window_end": "2026-09-25"},
        "error": None,
        "_pv": portfolio_value,
    }


@pytest.mark.asyncio
async def test_sizing_publishes_one_budget_with_its_rounding_and_its_price_date():
    """10: 43608.67 vs 43608.66989852906, and a sizing price 3 sessions old."""
    portfolio_value = 43_608.66989852906
    positions = [
        _pos("A", added_on="2025-01-01", last_price=48.20),
        _pos("B", added_on="2025-01-01", last_price=100.0),
    ]
    db = _db(positions)
    market = _WindowedMarket({"A": _frame("A", 11), "B": _frame("B", 12)})
    engine_result = _sizing_engine_result(portfolio_value)

    async def sizing(*_a, **_k):
        return {k: v for k, v in engine_result.items() if k != "_pv"}

    engine = SimpleNamespace(volatility_sizing=AsyncMock(side_effect=sizing))
    result = await get_volatility_sizing(
        model="EWMA", target_volatility=0.15, portfolio_value=portfolio_value,
        db=db, data_service=market, analytics_engine=engine,
    )
    # One budget, its published form, and the rounding that relates them.
    assert result["portfolio_value"] == 43608.67
    assert result["portfolio_value_decimals"] == 2
    assert result["portfolio_value_exact"] == pytest.approx(portfolio_value, abs=1e-9)
    assert result["portfolio_value_rounding_residual"] == pytest.approx(
        portfolio_value - 43608.67, abs=1e-9
    )
    assert result["sizing_basis"]["portfolio_value"] == pytest.approx(
        portfolio_value, abs=1e-9
    )
    assert result["sizing_basis"]["portfolio_value_role"] == (
        "exact_budget_every_trade_amount_was_struck_from"
    )
    # The sizing price date is the freshness of the trade list, and its staleness
    # against the newest delivered bar is measured, not asserted.
    #
    # This used to assert two literals -- `sizing_price_as_of == "2026-09-22"` and
    # `sizing_price_calendar_days_behind == 3` -- which contradicted the sentence
    # directly above them. The fixtures are deliberately anchored to
    # `datetime.now()` (END, at the top of this file, explains why: a hard-coded
    # end date falls outside the canonical holding evidence window), and
    # `calendar_days_behind` is a CALENDAR count, so a fixed number of business
    # days back spans a different number of calendar days depending on the
    # weekday. Measured over 14 consecutive run dates: the old assertion held on
    # 8 of 14 (Thu-Sun) and failed on 6 (Mon-Wed). So it was flaky, not slowly
    # drifting, and no single replacement number would have fixed it.
    #
    # Assert the measurement, which is what the comment always claimed.
    freshness = result["sizing_basis"]["price_freshness"]
    delivered_index = market.frames["A"].index.append(market.frames["B"].index)
    latest = pd.Timestamp(result["latest_observation_date"])
    sizing_as_of = pd.Timestamp(freshness["sizing_price_as_of"])
    # A genuinely delivered bar, and strictly older than the newest one.
    assert sizing_as_of in delivered_index
    assert sizing_as_of < latest
    assert latest == delivered_index.max()
    assert freshness["latest_delivered_observation"] == result["latest_observation_date"]
    assert freshness["sizing_price_calendar_days_behind"] == (latest - sizing_as_of).days
    assert freshness["sizing_price_as_of_status"] == "measured"
    # The drift between the sizing price and the position's own last_price.
    comparison = result["sizing_basis"]["position_last_price_comparison"]
    assert comparison["compared_legs"] == 2
    assert comparison["max_abs_relative_gap_ticker"] == "A"
    assert comparison["per_ticker_relative_gap"]["A"] == pytest.approx(
        (48.84 - 48.20) / 48.20, abs=1e-6
    )
    assert comparison["per_ticker_relative_gap"]["B"] == 0.0
    # The reconciliation aggregates arrive corrected.
    assert result["trade_reconciliation"]["max_rounding_tolerance"] == 50.0
    assert result["trade_reconciliation"]["min_rounding_tolerance"] == 24.42


def test_sizing_price_freshness_degrades_without_a_dated_price():
    from app.api.analytics import _sizing_price_freshness

    block = _sizing_price_freshness(None, "2026-09-25")
    assert block["sizing_price_calendar_days_behind"] is None
    assert block["sizing_price_as_of_status"] == "unavailable"
    block = _sizing_price_freshness("2026-09-22", None)
    assert block["sizing_price_calendar_days_behind"] is None
    assert block["sizing_price_as_of_status"] == "unavailable"


# ---------------------------------------------------------------------------
# 11. per-ticker counts in three units under one name
# ---------------------------------------------------------------------------
def test_price_frame_and_return_frame_units_are_both_declared():
    """The same three key names answer two different questions."""
    price = PRICE_FRAME_COUNT_UNITS
    returns = RETURN_FRAME_COUNT_UNITS
    assert price["raw_days"] == "delivered_price_rows_before_the_holding_window_mask"
    assert returns["raw_days"] == "aligned_return_rows_in_the_delivered_model_frame"
    # The identity a reader would assume is explicitly denied on the price side.
    assert "NOT raw_days - masked_days" in price["counts_identity"]
    # ... and stated on the return side, where it does hold.
    assert "OUTSIDE the window" in returns["counts_identity"]
    assert returns["return_observations"] == returns["raw_days"]


def test_return_frame_counts_close_over_the_delivered_frame():
    """`risk_contribution` published 246 where the frame holds 248 return rows."""
    dates = pd.bdate_range("2026-01-01", periods=250)
    returns = pd.DataFrame({"A": 0.001}, index=dates)
    own = int(returns["A"].notna().sum())
    # The bug: differencing a RETURN frame to "make" returns again loses the
    # first row as well, so the published count is one short of the truth.
    doubled = int(returns.pct_change(fill_method=None).iloc[1:]["A"].notna().sum())
    assert own == 250
    assert doubled == 249
    assert own - doubled == 1
    from app.api.analytics import _own_return_observations

    assert _own_return_observations(returns)["A"] == doubled
    # On a PRICE frame the same helper is exactly right: 250 bars are 249 returns.
    prices = pd.DataFrame({"A": 100.0 * (1.001 ** np.arange(250))}, index=dates)
    assert _own_return_observations(prices)["A"] == 249


@pytest.mark.asyncio
async def test_risk_contribution_publishes_return_row_counts_and_their_unit():
    """A return frame measured as returns-of-returns was the mislabelled count."""
    dates = pd.bdate_range(end=TODAY, periods=400)
    rng = np.random.default_rng(3)
    returns = pd.DataFrame(
        rng.normal(0.0003, 0.01, (len(dates), 2)),
        index=dates,
        columns=["A", "B"],
    )
    positions = [
        _pos("A", added_on="2026-08-04"), _pos("B", added_on="2026-08-04"),
    ]
    market = _WindowedMarket({})  # no price frames: stored dates only, declared

    async def build(_tickers, _weights, _start, _end, _service, **_k):
        return returns, returns.mean(axis=1), {
            "tickers": {
                "A": {"raw_days": 10, "masked_days": 5, "return_observations": 9},
                "B": {"raw_days": 10, "masked_days": 5, "return_observations": 9},
            }
        }

    with patch.object(analytics_mod, "_build_wide_returns", side_effect=build):
        result = await get_risk_contribution(
            tickers="A,B", db=_db(positions), data_service=market
        )
    context = result["history_coverage"]["holding_context"]
    units = context["per_ticker_count_units"]
    assert units == RETURN_FRAME_COUNT_UNITS
    entry = context["tickers"]["A"]
    # The count is now the frame's own aligned return rows, not a second
    # difference of them.
    assert entry["return_observations"] == int(returns["A"].notna().sum())
    assert entry["return_observations"] == entry["raw_days"]
    assert entry["holding_window_return_observations"] == entry["masked_days"]
    # The unit is declared at the block level too, and the block count keeps its
    # own scope label. XS-001: this section measures the wide per-leg frame, so
    # the label says so rather than borrowing the whole-book one.
    assert context["covered_days_scope"] == HOLDING_WIDE_FRAME_COVERED_DAYS_SCOPE
    assert result["history_coverage"]["per_ticker_count_units"] == RETURN_FRAME_COUNT_UNITS
    assert result["history_coverage"]["holding_window_days_scope"] == (
        HOLDING_WIDE_FRAME_COVERED_DAYS_SCOPE
    )
    # And the share map beside `annualized: true` declares what it is.
    basis = result["contribution_basis"]
    assert basis["unit"] == CONTRIBUTION_UNIT
    assert set(basis["per_model"]) == {"volatility", "cvar_tail"}


@pytest.mark.asyncio
async def test_factor_exposure_answers_the_holding_window_in_return_rows():
    """11: 40 held price rows are 39 aligned return rows, like every other section."""
    frame = _evidence_frame("A", 5)
    dates = frame.index
    positions = [_pos("A", added_on=dates[100].to_pydatetime())]
    market = _WindowedMarket({"A": frame})
    bench = SimpleNamespace(get_returns=AsyncMock(return_value=None))
    engine = SimpleNamespace(
        factor_exposure_analysis=AsyncMock(return_value={
            "portfolio": {"alpha": 0.01, "market": 0.02, "beta": 0.9, "r_squared": 0.4},
            "positions": {
                "A": {
                    "alpha": 0.01, "beta": 0.9, "market": 0.02, "r_squared": 0.4,
                    "data_points": 250, "is_limited_history": False,
                }
            },
            "r_squared": 0.4, "adjusted_r_squared": 0.3, "error": None,
        })
    )
    result = await get_factor_exposure(
        tickers="A", lookback_days=252, db=_db(positions),
        data_service=market, benchmark_service=bench, analytics_engine=engine,
    )
    context = result["history_coverage"]["holding_context"]
    start = dates[100].date().isoformat()
    price_rows = int((dates >= pd.Timestamp(start)).sum())
    assert price_rows == EVIDENCE_BARS - 100
    assert context["covered_days"] == price_rows - 1
    # XS-001: `port_ret` is the wide per-leg frame and keeps partially-covered
    # dates, so this count is NOT the whole-book population the other sections
    # publish. The name says which one it is; the count itself is untouched.
    assert context["covered_days_scope"] == HOLDING_WIDE_FRAME_COVERED_DAYS_SCOPE
    # The price-row count is kept, labelled, one larger because the bar on the
    # start date has no held predecessor.
    assert context["holding_window_price_rows"] == price_rows
    assert context["holding_window_price_rows_scope"] == "held_price_rows_incl_start_bar"
    # The model-scoped mirror carries the unit too.
    assert result["history_coverage"]["per_ticker_count_units"] == (
        PRICE_FRAME_COUNT_UNITS
    )
    assert result["history_coverage"]["covered_days_scope"] == (
        "model_return_observations"
    )


@pytest.mark.asyncio
async def test_factor_exposure_reads_its_starts_through_the_canonical_rule():
    """A section with its own frames must not re-infer a different date."""
    dates = pd.bdate_range(end=END, periods=EVIDENCE_BARS)
    # A strictly declining series, so exactly one bar is within the buy-price
    # tolerance of `closes[19]`: the most recent match is the one we placed.
    closes = 100.0 * (0.98 ** np.arange(EVIDENCE_BARS))
    frame = pd.DataFrame({"adj_close": pd.Series(closes, index=dates)})
    positions = [
        _pos("A", added_on=dates[20].to_pydatetime(), buy_price=float(closes[19]))
    ]
    market = _WindowedMarket({"A": frame})
    bench = SimpleNamespace(get_returns=AsyncMock(return_value=None))
    engine = SimpleNamespace(
        factor_exposure_analysis=AsyncMock(return_value={
            "portfolio": {"alpha": 0.01, "market": 0.02, "beta": 0.9, "r_squared": 0.4},
            "positions": {
                "A": {
                    "alpha": 0.01, "beta": 0.9, "market": 0.02, "r_squared": 0.4,
                    "data_points": 250, "is_limited_history": False,
                }
            },
            "r_squared": 0.4, "adjusted_r_squared": 0.3, "error": None,
        })
    )
    result = await get_factor_exposure(
        tickers="A", lookback_days=252, db=_db(positions),
        data_service=market, benchmark_service=bench, analytics_engine=engine,
    )
    context = result["history_coverage"]["holding_context"]
    entry = context["tickers"]["A"]
    # The inferred date is the bar before the import stamp, and it says so.
    assert entry["analytics_start"] == dates[19].date().isoformat()
    assert entry["analytics_start_source"] == "buy_price_inferred"
    assert entry["stored_added_on"] == dates[20].date().isoformat()
    assert context["intersection_start"] == dates[19].date().isoformat()
    assert context["provenance_evidence_window"]["days"] == (
        analytics_mod.HOLDING_PROVENANCE_LOOKBACK_DAYS
    )


# ---------------------------------------------------------------------------
# preserved contracts
# ---------------------------------------------------------------------------
def test_preserved_contracts_survive():
    """Ticket 03/07/09 shapes the new disclosures must not have displaced."""
    assert analytics_mod.WEIGHT_NORMALIZATION_RULE
    assert analytics_mod.FULL_HISTORY_BASIS == "full_exchange_history_current_weights"
    assert analytics_mod.HOLDING_CONTEXT_SCOPE == "holding_context_ancillary"
    assert analytics_mod.HOLDING_COVERED_DAYS_SCOPE == (
        "holding_window_aligned_return_rows"
    )
    assert analytics_mod.ACTIVE_WEIGHT_BASIS
    # The regime conditional sample keeps its own count and its own scope.
    from app.api.analytics import _conditional_regime_coverage

    conditional = _conditional_regime_coverage(
        {"days": 19},
        {"covered_days": 39, "covered_days_scope": HOLDING_COVERED_DAYS_SCOPE,
         "tickers": {}, "intersection_start": "2026-08-03"},
    )
    assert conditional["covered_days"] == 19
    assert conditional["covered_days_scope"] == "conditional_regime_return_days"
    assert conditional["holding_window_days"] == 39
