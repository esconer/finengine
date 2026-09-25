"""Regression gates for v3 findings V3-09 and V3-10 (ticket 06, engine half).

V3-09 (liquidity): the published score, the category, the liquidation window
and the high/medium/low counts must all read the SAME rounded score, a market
cap that was annualised from turnover or floored at INR 1bn must be labelled,
and an unavailable result must claim nothing.

V3-10 (stress): `max_drawdown`, `confidence_level` and `recovery_time` are a
deterministic factor proxy, not simulated statistics, and must say so.

V3-08 (concentration sector rounding) is fixed at the API layer in
``app/api/analytics.py`` and is deliberately not gated here.
"""

import json
import re

import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import (
    LIQUIDITY_MARKET_CAP_FLOOR_INR,
    AnalyticsEngine,
)

# Independent restatement of the published band rule.  If the engine's rule
# changes, this table has to change with it, on purpose.
BAND_TABLE = (
    ("High", 8.0, None, "1-2", "high"),
    ("Medium", 6.0, 8.0, "2-5", "medium"),
    ("Low", None, 6.0, "5-10", "low"),
)


def expected_band(published_score):
    """Band label, liquidation window and volume bucket for a published score."""
    for band, floor, _ceiling, window, bucket in BAND_TABLE:
        if floor is None or published_score >= floor:
            return band, window, bucket
    return BAND_TABLE[-1][0], BAND_TABLE[-1][3], BAND_TABLE[-1][4]


def ohlcv(price, volume, periods=30):
    """Constant price/volume frame; volume drives turnover deterministically."""
    dates = pd.date_range(start="2024-01-01", periods=periods, freq="D")
    return pd.DataFrame(
        {"Close": [price] * periods, "Volume": [volume] * periods}, index=dates
    )


def turnover_frame(daily_turnover, price=100.0):
    return ohlcv(price, daily_turnover / price)


def price_window():
    """300 sessions: one volatile leg, one leg with too few moving days."""
    rng = np.random.default_rng(7)
    dates = pd.date_range(start="2022-01-01", periods=300, freq="D")
    volatile = pd.Series(rng.normal(0, 0.01, 300), index=dates).cumsum() + 100.0
    flat = np.concatenate([np.zeros(290), rng.normal(0, 0.01, 10)]) + 50.0
    return pd.DataFrame({"VOL.NS": volatile.values, "FLAT.NS": flat}, index=dates)


# ---------------------------------------------------------------------------
# V3-09: one rounded score, one band rule
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestLiquidityScoreBand:
    @pytest.mark.asyncio
    async def test_raw_7_96_publishes_the_high_band_not_medium(self):
        """v3 evidence: score 8 published with a Medium band and counted high."""
        engine = AnalyticsEngine()
        # 7.2727 Cr/day turnover with a measured 20,000 Cr cap lands on the
        # tier-2 curve at a raw 7.96, which used to publish score=8.0 while the
        # category stayed "Medium" and the volume split counted it as high.
        result = await engine.liquidity_analysis(
            {"AAA.NS": turnover_frame(72_727_272.727272727)},
            market_caps={"AAA.NS": 2.0e11},
        )
        position = result["by_position"]["AAA.NS"]

        assert position["score_raw"] == pytest.approx(7.96, abs=1e-6)
        assert position["score"] == 8.0
        assert position["score"] == round(position["score_raw"], 1)
        assert position["category"] == "High"
        assert position["liquidation_days"] == "1-2"
        assert result["volume_stats"]["high_volume_pct"] == 100.0
        assert result["overall_score"] == 8.0
        assert result["risk_level"] == "Low"
        assert result["liquidation_time_days"] == "1-2"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "turnover, market_cap, label",
        [
            (600_000_000.0, None, "tier 1 mega turnover"),
            (100_000_000.0, None, "tier 2 high turnover"),
            (50_000_000.0, 2.0e11, "tier 2 measured cap, medium score"),
            (50_000_000.0, None, "tier 3 moderate turnover"),
            (1_000_000.0, None, "tier 4 subscale turnover"),
        ],
    )
    async def test_every_band_reads_the_published_score(self, turnover, market_cap, label):
        engine = AnalyticsEngine()
        caps = {"AAA.NS": market_cap} if market_cap is not None else None

        result = await engine.liquidity_analysis(
            {"AAA.NS": turnover_frame(turnover)}, market_caps=caps
        )
        position = result["by_position"]["AAA.NS"]
        band, window, bucket = expected_band(position["score"])

        assert position["score"] == round(position["score_raw"], 1), label
        assert position["category"] == band, label
        assert position["liquidation_days"] == window, label
        assert result["volume_stats"][f"{bucket}_volume_pct"] == 100.0, label
        assert result["overall_band"] == expected_band(result["overall_score"])[0], label
        assert result["liquidation_time_days"] == expected_band(result["overall_score"])[1], label
        assert result["risk_level"] == {
            "High": "Low", "Medium": "Medium", "Low": "High"
        }[result["overall_band"]], label

    @pytest.mark.asyncio
    async def test_published_band_rule_documents_the_threshold(self):
        engine = AnalyticsEngine()
        result = await engine.liquidity_analysis(
            {"AAA.NS": turnover_frame(100_000_000.0)}
        )

        rule = result["score_band_rule"]
        assert rule["band_source"] == "published_score"
        assert rule["raw_score_field"] == "score_raw"
        assert rule["published_score_field"] == "score"
        published = [
            (band["band"], band["min_published_score"], band["max_published_score"],
             band["liquidation_days"], band["volume_stats_bucket"])
            for band in rule["bands"]
        ]
        assert tuple(published) == BAND_TABLE

    @pytest.mark.asyncio
    async def test_mixed_portfolio_volume_split_matches_position_bands(self):
        engine = AnalyticsEngine()
        result = await engine.liquidity_analysis(
            {
                "MEGA.NS": turnover_frame(600_000_000.0),
                "MID.NS": turnover_frame(50_000_000.0),
                "MICRO.NS": turnover_frame(1_000_000.0),
            }
        )
        bands = [p["category"] for p in result["by_position"].values()]

        assert bands == ["High", "Medium", "Low"]
        assert result["volume_stats"]["high_volume_pct"] == pytest.approx(100 / 3, abs=0.1)
        assert result["volume_stats"]["medium_volume_pct"] == pytest.approx(100 / 3, abs=0.1)
        assert result["volume_stats"]["low_volume_pct"] == pytest.approx(100 / 3, abs=0.1)


# ---------------------------------------------------------------------------
# V3-09: market-cap provenance
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMarketCapProvenance:
    @pytest.mark.asyncio
    async def test_quote_supplied_cap_is_measured(self):
        engine = AnalyticsEngine()
        result = await engine.liquidity_analysis(
            {"AAA.NS": turnover_frame(600_000_000.0)},
            market_caps={"AAA.NS": 7.5e11},
        )
        position = result["by_position"]["AAA.NS"]

        assert position["market_cap"] == 7.5e11
        assert position["market_cap_provenance"] == "measured"
        assert position["market_cap_source"] == "quote"
        assert position["is_estimate"] is False

    @pytest.mark.asyncio
    async def test_implied_annual_turnover_cap_is_an_estimate(self):
        engine = AnalyticsEngine()
        result = await engine.liquidity_analysis(
            {"AAA.NS": turnover_frame(10_000_000.0)}
        )
        position = result["by_position"]["AAA.NS"]

        assert position["market_cap"] == pytest.approx(10_000_000.0 * 250.0)
        assert position["market_cap_provenance"] == "estimated"
        assert position["market_cap_source"] == "implied_annual_turnover"
        assert position["is_estimate"] is True

    @pytest.mark.asyncio
    async def test_selectipo_floor_is_never_silent(self):
        """v3 evidence: SELECTIPO market cap equalled the INR 1bn fallback."""
        engine = AnalyticsEngine()
        result = await engine.liquidity_analysis(
            {"SELECTIPO.NS": ohlcv(10.0, 1_000.0)}
        )
        position = result["by_position"]["SELECTIPO.NS"]

        assert position["market_cap"] == LIQUIDITY_MARKET_CAP_FLOOR_INR
        assert position["market_cap_provenance"] == "fallback"
        assert position["market_cap_source"] == "fixed_floor_1e9_inr"
        assert position["is_estimate"] is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("supplied", [0, 0.0, None, -5.0, "not-a-number", float("nan")])
    async def test_unusable_supplied_cap_never_publishes_nan(self, supplied):
        engine = AnalyticsEngine()
        result = await engine.liquidity_analysis(
            {"AAA.NS": turnover_frame(1_000.0)}, market_caps={"AAA.NS": supplied}
        )
        position = result["by_position"]["AAA.NS"]

        assert np.isfinite(position["market_cap"])
        assert position["market_cap"] == LIQUIDITY_MARKET_CAP_FLOOR_INR
        assert position["market_cap_provenance"] == "fallback"
        assert position["is_estimate"] is True

    @pytest.mark.asyncio
    async def test_provenance_vocabulary_is_the_shared_one(self):
        engine = AnalyticsEngine()
        result = await engine.liquidity_analysis(
            {
                "MEASURED.NS": turnover_frame(600_000_000.0),
                "IMPLIED.NS": turnover_frame(10_000_000.0),
                "FLOORED.NS": ohlcv(10.0, 1_000.0),
            },
            market_caps={"MEASURED.NS": 9.0e11},
        )
        provenances = {
            p["market_cap_provenance"] for p in result["by_position"].values()
        }

        # measured | derived | estimated | fallback | unavailable
        assert provenances <= {"measured", "derived", "estimated", "fallback", "unavailable"}
        assert provenances == {"measured", "estimated", "fallback"}


# ---------------------------------------------------------------------------
# V3-09: an unavailable liquidity result claims nothing
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestEmptyLiquidityIsHonest:
    def test_empty_liquidity_publishes_no_score_or_band(self):
        engine = AnalyticsEngine()
        empty = engine._empty_liquidity()

        assert empty["error"]
        assert empty["overall_score"] is None
        assert empty["overall_score_raw"] is None
        assert empty["risk_level"] is None
        assert empty["liquidation_time_days"] is None
        assert empty["overall_band"] is None
        assert empty["by_position"] == {}

    def test_empty_liquidity_does_not_assert_a_worst_case_book(self):
        engine = AnalyticsEngine()
        stats = engine._empty_liquidity()["volume_stats"]

        # Nothing was measured, so nothing is in any band; 100% low-liquidity
        # described a portfolio nobody observed.
        assert stats["low_volume_pct"] == 0
        assert stats["high_volume_pct"] == 0
        assert stats["medium_volume_pct"] == 0

    @pytest.mark.asyncio
    async def test_no_volume_frames_report_the_honest_empty_result(self):
        engine = AnalyticsEngine()
        result = await engine.liquidity_analysis(
            {"AAA.NS": pd.DataFrame({"Close": [100.0] * 30},
                                    index=pd.date_range("2024-01-01", periods=30))}
        )

        assert result["error"]
        assert result["overall_score"] is None
        assert result["risk_level"] is None
        assert result["liquidation_time_days"] is None
        assert result["by_position"] == {}

    @pytest.mark.asyncio
    async def test_empty_input_reports_the_honest_empty_result(self):
        engine = AnalyticsEngine()
        result = await engine.liquidity_analysis({})

        assert result["overall_score"] is None
        assert result["risk_level"] is None
        assert result["liquidation_time_days"] is None


# ---------------------------------------------------------------------------
# V3-10: the stress scenario is a deterministic proxy, and says so
# ---------------------------------------------------------------------------
NEGATION_BEFORE = re.compile(r"(?:\bno|\bnot a|\bnot an|\bnever)\s+$")


def unqualified_simulation_mentions(text):
    """Every 'simulat...' in `text` that is not negated in the same clause."""
    lowered = text.lower()
    return [
        lowered[max(0, match.start() - 30): match.start() + 12]
        for match in re.finditer(r"simulat", lowered)
        if not NEGATION_BEFORE.search(lowered[: match.start()])
    ]


@pytest.mark.unit
class TestStressProxySemantics:
    @pytest.mark.asyncio
    async def test_published_values_are_unchanged(self):
        """Every pre-existing key keeps its pre-existing value."""
        engine = AnalyticsEngine()
        result = await engine.stress_test(
            price_window(), {"VOL.NS": 0.6, "FLAT.NS": 0.4}, "2020_covid"
        )

        assert result["scenario"] == "2020_covid"
        assert result["scenario_description"] == "March 2020 COVID Market Crash"
        assert result["recovery_time"] == 6
        assert result["confidence_level"] == 0.95
        assert result["portfolio_impact"] == pytest.approx(
            round(
                sum(result["position_impacts"][t] * w for t, w in
                    {"VOL.NS": 0.6, "FLAT.NS": 0.4}.items()),
                4,
            ),
            abs=1e-3,
        )
        # The published drawdown is still the 1.15 uplift on the proxy.
        assert result["max_drawdown"] == round(result["portfolio_impact"] * 1.15, 4)
        assert result["max_drawdown_formula"] == "portfolio_impact * 1.15"

    @pytest.mark.asyncio
    async def test_derived_statistics_carry_their_basis(self):
        engine = AnalyticsEngine()
        result = await engine.stress_test(
            price_window(), {"VOL.NS": 0.6, "FLAT.NS": 0.4}, "2020_covid"
        )

        assert result["impact_basis"] == "deterministic_factor_proxy"
        assert result["max_drawdown_basis"] == "derived_from_shock_proxy"
        assert result["confidence_basis"] == "nominal_label_not_simulated"
        assert result["recovery_time_basis"] == "configured_recovery_estimate_not_simulated"

    @pytest.mark.asyncio
    async def test_shock_inputs_disclose_every_input(self):
        engine = AnalyticsEngine()
        result = await engine.stress_test(
            price_window(),
            {"VOL.NS": 0.6, "FLAT.NS": 0.4},
            "2020_covid",
            sectors={"VOL.NS": "Financial Services"},
        )
        shock = result["shock_inputs"]

        assert shock["market_shock"] == -0.28
        assert shock["market_shock_basis"] == "scenario_config"
        assert shock["sector_elasticity_table"]["Financial Services"] == 1.40
        assert shock["sector_elasticity_basis"] == "static_configured_table"

        volatility = shock["volatility_adjustment"]
        assert volatility["reference_annualized_volatility"] == 0.22
        assert volatility["bounds"] == [0.85, 1.25]
        assert volatility["min_observations"] == 20
        assert set(volatility["by_ticker"]) == {"VOL.NS", "FLAT.NS"}
        for entry in volatility["by_ticker"].values():
            assert 0.85 <= entry["factor"] <= 1.25
            assert entry["basis"]

    @pytest.mark.asyncio
    async def test_unmeasured_volatility_adjustment_states_its_basis(self):
        engine = AnalyticsEngine()
        result = await engine.stress_test(
            price_window(), {"VOL.NS": 0.6, "FLAT.NS": 0.4}, "market_crash"
        )
        by_ticker = result["shock_inputs"]["volatility_adjustment"]["by_ticker"]

        assert by_ticker["VOL.NS"]["basis"] == "measured_annualized_volatility_over_reference"
        assert by_ticker["FLAT.NS"]["basis"] == "unavailable_insufficient_observations"
        assert by_ticker["FLAT.NS"]["factor"] == 1.0

    @pytest.mark.asyncio
    async def test_instrument_override_is_disclosed(self):
        engine = AnalyticsEngine()
        result = await engine.stress_test(
            price_window(), {"SELECTIPO.NS": 1.0}, "2020_covid"
        )
        override = result["shock_inputs"]["instrument_overrides"]["SELECTIPO.NS"]

        assert override["sector_elasticity"] == 1.15
        assert override["basis"] == "instrument_override_selectipo"

    @pytest.mark.asyncio
    async def test_custom_shock_discloses_its_origin(self):
        engine = AnalyticsEngine()
        parsed = await engine.stress_test(
            price_window(), {"VOL.NS": 1.0}, "crash -10%"
        )
        defaulted = await engine.stress_test(
            price_window(), {"VOL.NS": 1.0}, "unheard-of scenario"
        )

        assert parsed["shock_inputs"]["market_shock_basis"] == "parsed_from_scenario_text"
        assert parsed["shock_inputs"]["market_shock"] == -0.10
        assert defaulted["shock_inputs"]["market_shock_basis"] == "default_minus_20pct"
        assert defaulted["shock_inputs"]["market_shock"] == -0.20

    @pytest.mark.asyncio
    async def test_units_state_fraction_units_and_months(self):
        engine = AnalyticsEngine()
        result = await engine.stress_test(
            price_window(), {"VOL.NS": 1.0}, "2020_covid"
        )
        units = result["units"]

        assert units["max_drawdown"] == "fraction_of_portfolio_value"
        assert units["portfolio_impact"] == "fraction_of_portfolio_value"
        assert units["position_impacts"] == "fraction_of_position_value"
        assert units["recovery_time"] == "months"
        assert units["confidence_level"] == "unitless_nominal_label"

    @pytest.mark.asyncio
    async def test_methodology_never_claims_an_independent_simulation(self):
        engine = AnalyticsEngine()
        result = await engine.stress_test(
            price_window(), {"VOL.NS": 1.0}, "2020_covid"
        )
        methodology = result["methodology"]

        assert unqualified_simulation_mentions(methodology) == []
        assert "shock simulation" not in methodology.lower()
        assert "deterministic factor shock proxy" in methodology.lower()

    @pytest.mark.asyncio
    async def test_payload_is_strict_json_with_finite_numbers(self):
        engine = AnalyticsEngine()
        result = await engine.stress_test(
            price_window(), {"VOL.NS": 0.6, "FLAT.NS": 0.4}, "2020_covid"
        )
        liquidity = await engine.liquidity_analysis(
            {"AAA.NS": turnover_frame(72_727_272.727272727)},
            market_caps={"AAA.NS": 2.0e11},
        )

        json.dumps(result, allow_nan=False)
        json.dumps(liquidity, allow_nan=False)

    @pytest.mark.asyncio
    async def test_empty_stress_test_mirrors_the_success_payload_as_none(self):
        engine = AnalyticsEngine()
        result = await engine.stress_test(
            price_window(), {"VOL.NS": 1.0}, "2020_covid"
        )
        empty = engine._empty_stress_test()

        assert set(empty) - {"error"} == set(result)
        for key in result:
            if key in ("scenario", "position_impacts"):
                continue
            assert empty[key] is None, key
        assert empty["position_impacts"] == {}

    @pytest.mark.asyncio
    async def test_unavailable_stress_inputs_report_the_empty_payload(self):
        engine = AnalyticsEngine()
        for result in (
            await engine.stress_test(pd.DataFrame(), {"VOL.NS": 1.0}, "2020_covid"),
            await engine.stress_test(price_window(), {}, "2020_covid"),
        ):
            assert result["error"]
            assert result["max_drawdown"] is None
            assert result["impact_basis"] is None
            assert result["max_drawdown_basis"] is None
            assert result["confidence_level"] is None
            assert result["confidence_basis"] is None
            assert result["shock_inputs"] is None
            assert result["units"] is None
