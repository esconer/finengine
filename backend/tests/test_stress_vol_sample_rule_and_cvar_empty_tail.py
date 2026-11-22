"""Two statistical fabrications in `analytics_engine.py`, and what replaced them.

1. **An empty tail published CVaR as the VaR restated.**
   `_calculate_risk_metrics` read

       cvar_95 = returns[returns <= var_95].mean() if len(...) > 0 else var_95

   so when the tail came back empty the payload carried ONE number under two
   labels that say they are different quantities - `var_95` is the 5th
   percentile, `cvar_95` is the MEAN of the tail that percentile cuts off.  A
   reader checking the relation the engine's own audit rule
   (`tail_mean_not_milder_than_its_quantile`) asserts would be checking a
   number against itself.

   An empty tail is a missing measurement, so both keys are now withheld with
   `None`, key-for-key, the shape `_empty_metrics` already publishes for this
   pair and the shape `_empty_stress_test` follows.  Measured, not assumed: for
   finite observations the tail is never empty, because the minimum is at or
   below the 5th percentile by construction - so an empty tail is exactly the
   window whose quantile is not a finite number.

2. **Stress volatility filtered on the outcome variable before measuring
   dispersion.**  `non_zero = s[s != 0.0].clip(...)` removed every genuine
   0.00% session from the sample the volatility was estimated on, and its
   multiplier `ticker_vol` feeds `ticker_impact` for the whole book - so every
   published stress loss was inflated for exactly the population this app
   targets: Indian small and mid-caps with flat sessions.  It also got the two
   kinds of zero backwards: `NaN != 0.0` is True, so pre-listing and no-trade
   GAPS were kept, padding the observation count that gates whether a
   dispersion is published at all while contributing nothing to it.

   `_calculate_factor_exposures` writes the correct rule at its own active-day
   mask - "dropna, not `!= 0.0`: keeps genuine 0% days, drops pre-listing/no-
   trade NaN gaps" - about two thousand lines away, with no shared helper, so
   the engine documented one rule and computed another.  Both sites now say
   `dropna`.

   The distinction that makes `dropna()` correct here rather than a different
   blanket filter: a genuine 0.00% return is a MEASUREMENT and stays in the
   sample, and a NaN gap is the ABSENCE of one and leaves.  NaN is missing data;
   0.0 is a measured return of zero.

The clip band at the impact stage is deliberately NOT changed here - see
`test_the_impact_clip_band_is_unchanged_and_still_disclosed` at the end.
"""

from __future__ import annotations

import asyncio
from typing import Dict

import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import (
    FORECAST_INPUT_RETURN_CLIP,
    STRESS_VOL_ADJ_MIN,
    STRESS_VOL_MIN_OBSERVATIONS,
    STRESS_VOL_REFERENCE,
    AnalyticsEngine,
)

ENGINE = AnalyticsEngine()

# The scenario is quoted with the weight of the shock, and its sector table
# gives the unclassified bucket a flat 1.00 elasticity, so
# `position_impact = market_shock * 1.00 * volatility_adjustment` and the only
# thing under test in the impact assertions is the measured factor.
SCENARIO = "market_crash"

SESSIONS = 400
# A flat session rate in the range an Indian small/mid-cap actually shows: most
# closes unchanged, the rest real moves.
FLAT_SESSION_RATE = 0.65
DAILY_SIGMA = 0.022
SEED = 11


def _returns_with_flat_sessions(
    flat_rate: float = FLAT_SESSION_RATE,
    n: int = SESSIONS,
    seed: int = SEED,
) -> pd.Series:
    """A return series with genuine 0.00% days and real moves between them."""
    rng = np.random.default_rng(seed)
    moves = rng.normal(0.0, DAILY_SIGMA, n)
    is_flat = rng.random(n) < flat_rate
    return pd.Series(np.where(is_flat, 0.0, moves))


def _price_frame(series_by_name: Dict[str, pd.Series], index) -> pd.DataFrame:
    """Prices whose `pct_change` is the return series handed in.

    `stress_test` computes `cleaned_prices.pct_change(fill_method=None)` and
    drops the first row, so this reproduces the delivered returns exactly.

    `np.cumprod`, not `Series.cumprod`: the frame is built with an explicit
    `DatetimeIndex`, and a Series carrying a `RangeIndex` would be ALIGNED to
    it by the DataFrame constructor rather than positioned, delivering a frame
    of NaN and proving nothing.
    """
    return pd.DataFrame(
        {
            name: 100.0 * np.cumprod(1.0 + values.to_numpy())
            for name, values in series_by_name.items()
        },
        index=index,
    )


def _stress(returns_by_name: Dict[str, pd.Series], weights: Dict[str, float]):
    index = pd.bdate_range("2023-01-02", periods=len(next(iter(returns_by_name.values()))))
    frame = _price_frame(returns_by_name, index)
    return asyncio.run(ENGINE.stress_test(frame, weights, SCENARIO))


def _expected_factor(returns: pd.Series) -> float:
    """What the engine's own published contract says the factor should be.

    Rebuilt from the constants the payload publishes under
    `shock_inputs.volatility_adjustment`, so this is the documented rule rather
    than a second copy of the implementation.
    """
    active = returns.dropna().clip(
        lower=FORECAST_INPUT_RETURN_CLIP[0], upper=FORECAST_INPUT_RETURN_CLIP[1]
    )
    if len(active) < STRESS_VOL_MIN_OBSERVATIONS:
        return 1.0
    vol = float(active.std() * np.sqrt(252))
    if not vol > 0:
        return 1.0
    return max(STRESS_VOL_ADJ_MIN, min(1.25, vol / STRESS_VOL_REFERENCE))


# ---------------------------------------------------------------------------
# 1. An empty tail must not publish the VaR under the CVaR key
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestEmptyTailIsWithheldRatherThanAliased:
    def test_an_empty_tail_withholds_both_keys(self):
        """THE DEFECT.  Two labels, one number."""
        # A NaN in the window makes `np.percentile` return NaN, and every
        # comparison against NaN is False, so the tail is empty.
        returns = pd.Series([0.01, np.nan, -0.02, 0.03, 0.005])
        metrics = ENGINE._calculate_risk_metrics(returns)

        # Key-for-key with the success payload: never a silently absent key.
        assert "var_95" in metrics
        assert "cvar_95" in metrics
        assert metrics["var_95"] is None
        assert metrics["cvar_95"] is None

    def test_the_two_keys_are_never_the_same_number(self):
        """Whatever the window, a measured CVaR is never the VaR restated."""
        windows = {
            "normal": pd.Series(np.random.default_rng(1).normal(0.0, 0.02, 500)),
            "flat": pd.Series([0.0] * 40),
            "single observation": pd.Series([0.05]),
            "constant positive": pd.Series([0.0007] * 60),
            "with a NaN": pd.Series([0.01, np.nan, -0.02, 0.03]),
            "with an infinity": pd.Series([np.inf, 0.02, -0.01]),
            "all NaN": pd.Series([np.nan] * 6),
        }
        for label, returns in windows.items():
            metrics = ENGINE._calculate_risk_metrics(returns)
            var_95, cvar_95 = metrics["var_95"], metrics["cvar_95"]
            if var_95 is None or cvar_95 is None:
                # A withheld pair, never an aliased one.
                assert var_95 is None and cvar_95 is None, label
                continue
            # Both measured: the tail mean is at least as deep as the quantile
            # that selected it, and it is a different statistic, not a copy.
            assert cvar_95 <= var_95, label
            assert cvar_95 != var_95 or float(var_95) == float(
                returns[returns <= var_95].mean()
            ), label

    def test_a_real_tail_is_still_measured_not_withheld(self):
        """The refusal does not swallow the ordinary case."""
        returns = pd.Series(np.random.default_rng(42).normal(0.0, 0.02, 500))
        metrics = ENGINE._calculate_risk_metrics(returns)

        assert metrics["var_95"] < 0
        assert metrics["cvar_95"] < metrics["var_95"]


# ---------------------------------------------------------------------------
# 2. Genuine 0.00% days belong in the sample the dispersion is measured on
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestFlatSessionsContributeToStressVolatility:
    def test_a_series_of_flat_sessions_measures_rather_than_refuses(self):
        """THE CAUSE.  The old filter made this leg unmeasurable.

        `s != 0.0` dropped every 0.00% day, so a book that sat still most of
        the time was left with only its moving days.  When those numbered fewer
        than `STRESS_VOL_MIN_OBSERVATIONS`, the engine published
        `unavailable_insufficient_observations` - a claim about the filter, not
        about the leg.  The 300+ measured returns on this series are all real.
        """
        returns = _returns_with_flat_sessions(flat_rate=0.97, n=300, seed=5)
        assert int((returns == 0.0).sum()) > 20
        assert int((returns != 0.0).sum()) < STRESS_VOL_MIN_OBSERVATIONS

        result = _stress({"FLAT.NS": returns}, {"FLAT.NS": 1.0})
        entry = result["shock_inputs"]["volatility_adjustment"]["by_ticker"]["FLAT.NS"]

        assert entry["basis"] == "measured_annualized_volatility_over_reference"
        assert entry["factor"] == pytest.approx(_expected_factor(returns), abs=1e-4)

    def test_the_flat_days_reach_the_measured_dispersion(self):
        """Not just counted - they change the number, in the honest direction.

        A book with many flat sessions genuinely has a lower dispersion than
        the same book with those sessions deleted, and the filter was deleting
        them.  This is the inflation, stated as a difference between the two
        candidate samples.
        """
        returns = _returns_with_flat_sessions()
        flat_days = int((returns == 0.0).sum())
        assert flat_days > 0

        with_zeros = float(returns.dropna().std())
        without_zeros = float(returns[returns != 0.0].std())
        # Deleting the flat sessions raises the measured dispersion.
        assert without_zeros > with_zeros, (without_zeros, with_zeros)

        result = _stress({"MID.NS": returns}, {"MID.NS": 1.0})
        entry = result["shock_inputs"]["volatility_adjustment"]["by_ticker"]["MID.NS"]

        # The published factor is the one built over the full delivered sample.
        expected = max(
            STRESS_VOL_ADJ_MIN,
            min(
                1.25,
                float(returns.dropna().std() * np.sqrt(252)) / STRESS_VOL_REFERENCE,
            ),
        )
        assert entry["factor"] == pytest.approx(expected, abs=1e-4)
        # And it is materially below the factor the zero-filtered sample yields,
        # which is the direction of the error that was being published.
        inflated = max(
            STRESS_VOL_ADJ_MIN,
            min(
                1.25,
                float(returns[returns != 0.0].std() * np.sqrt(252)) / STRESS_VOL_REFERENCE,
            ),
        )
        assert entry["factor"] < inflated, (entry["factor"], inflated)

    def test_a_book_with_flat_sessions_publishes_a_smaller_stress_loss(self):
        """The user-visible consequence: the whole book, weighted."""
        calm = _returns_with_flat_sessions(flat_rate=FLAT_SESSION_RATE, seed=11)
        busy = _returns_with_flat_sessions(flat_rate=0.0, seed=12)

        calm_result = _stress({"AAA.NS": calm}, {"AAA.NS": 1.0})
        busy_result = _stress({"AAA.NS": busy}, {"AAA.NS": 1.0})

        calm_impact = calm_result["position_impacts"]["AAA.NS"]
        busy_impact = busy_result["position_impacts"]["AAA.NS"]
        assert calm_impact > busy_impact, (calm_impact, busy_impact)
        # And every published impact still reproduces from the published
        # operands, so the discount is visible rather than hidden in a factor.
        for result in (calm_result, busy_result):
            shock = result["shock_inputs"]
            factor = shock["volatility_adjustment"]["by_ticker"]["AAA.NS"]["factor"]
            elasticity = shock["co_movement"]["by_ticker"]["AAA.NS"]["applied_elasticity"]
            assert result["position_impacts"]["AAA.NS"] == pytest.approx(
                round(shock["market_shock"] * elasticity * factor, 4), abs=1e-4
            )


# ---------------------------------------------------------------------------
# 3. A pre-listing / no-trade NaN gap is still dropped
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestNaNGapsAreStillDropped:
    def test_a_pre_listing_gap_is_not_an_observation(self):
        """`NaN != 0.0` is True, so the old filter KEPT every gap.

        It padded the count that gates whether a dispersion is published, while
        contributing nothing to that dispersion (pandas skips NaN in `std`).
        So a leg with 15 real sessions and 40 pre-listing gaps was scored on 15
        observations wearing 55.
        """
        rng = np.random.default_rng(9)
        listed_late = pd.Series(
            rng.normal(0.0, 0.02, 15),
            index=pd.bdate_range("2023-01-02", periods=15),
        )
        prices = pd.Series(np.nan, index=pd.bdate_range("2022-09-01", periods=55))
        prices = pd.concat([prices, 50.0 * (1.0 + listed_late).cumprod()])

        returns = prices.pct_change(fill_method=None).iloc[1:]
        measured = int(returns.notna().sum())
        gaps = int(returns.isna().sum())
        assert measured == 14 and gaps == 55, (measured, gaps)
        assert measured < STRESS_VOL_MIN_OBSERVATIONS
        # The old filter would have counted the gaps as observations.
        assert len(returns[returns != 0.0]) >= STRESS_VOL_MIN_OBSERVATIONS

        index = pd.bdate_range("2022-09-01", periods=len(prices))
        frame = pd.DataFrame({"IPO.NS": prices.values}, index=index)
        result = asyncio.run(ENGINE.stress_test(frame, {"IPO.NS": 1.0}, SCENARIO))
        entry = result["shock_inputs"]["volatility_adjustment"]["by_ticker"]["IPO.NS"]

        assert entry["basis"] == "unavailable_insufficient_observations"
        assert entry["factor"] == 1.0

    def test_gaps_and_flat_days_are_treated_as_the_two_different_things_they_are(self):
        """A NaN is absent data; a 0.00% return is a measured zero.

        Two legs with the SAME number of measured returns and the same measured
        values, one delivered with NaN gaps around them and one without, must
        produce the same factor - and both must differ from a leg whose measured
        returns were replaced by gaps.
        """
        rng = np.random.default_rng(21)
        measured = rng.normal(0.0, 0.02, 60)
        n = 200
        index = pd.bdate_range("2023-01-02", periods=n)

        # The same 60 measured returns, delivered inside a frame padded with
        # NaN so that 140 of the 200 rows are pre-listing gaps.
        padded = pd.Series(np.nan, index=index)
        padded.iloc[-60:] = 100.0 * (1.0 + measured).cumprod()
        # ...and the same 60 delivered with no gaps at all, in their own window.
        bare_index = pd.bdate_range("2024-01-02", periods=60)
        bare = pd.Series(100.0 * (1.0 + measured).cumprod(), index=bare_index)

        padded_result = asyncio.run(
            ENGINE.stress_test(pd.DataFrame({"IPO.NS": padded.values}, index=index), {"IPO.NS": 1.0}, SCENARIO)
        )
        bare_result = asyncio.run(
            ENGINE.stress_test(pd.DataFrame({"OLD.NS": bare.values}, index=bare_index), {"OLD.NS": 1.0}, SCENARIO)
        )
        padded_entry = padded_result["shock_inputs"]["volatility_adjustment"]["by_ticker"]["IPO.NS"]
        bare_entry = bare_result["shock_inputs"]["volatility_adjustment"]["by_ticker"]["OLD.NS"]

        # 140 gaps around 60 measured returns is still 60 measured returns.
        assert padded_entry["basis"] == "measured_annualized_volatility_over_reference"
        assert padded_entry["factor"] == pytest.approx(bare_entry["factor"], abs=1e-4)

    def test_the_code_matches_the_rule_the_engine_documents(self):
        """Converge on the documented rule, so the two sites cannot drift.

        `_calculate_factor_exposures` writes the rule in prose next to its own
        mask.  This asserts no `!= 0.0` mask on a return series survives
        anywhere in the engine, which is what "converged" means: the opposite
        rule is no longer in force anywhere it could be copied from.

        The scan is over the PARSED AST rather than the source text, because the
        comment recording the old filter necessarily quotes it - scanning text
        would flag the explanation of the defect as an instance of the defect.
        """
        import ast
        import inspect

        import app.services.analytics_engine as module

        tree = ast.parse(inspect.getsource(module))

        def _zero_compares(node: ast.AST) -> bool:
            return isinstance(node, ast.Compare) and any(
                isinstance(op, (ast.NotEq, ast.Eq)) for op in node.ops
            ) and any(
                isinstance(c, ast.Constant)
                and isinstance(c.value, float)
                and c.value == 0.0
                for c in node.comparators
            )

        # The defect's shape specifically: a SERIES filtered by a comparison
        # against zero, i.e. `s[s != 0.0]`.  A bare `deviation == 0.0` on a
        # scalar is a different thing entirely and is not this rule.
        offenders = [
            f"{node.lineno}: {ast.unparse(node)}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Subscript)
            and _zero_compares(node.slice)
        ]
        assert not offenders, offenders

        # The documented rule is stated at both sites, in the file's own words.
        source = inspect.getsource(module)
        assert source.count(
            "dropna, not `!= 0.0`: keeps genuine 0% days, drops"
        ) == 2, "both the factor-exposure mask and the stress filter must state it"


# ---------------------------------------------------------------------------
# 4. The clip band is a disclosed policy bound - reported, not changed
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTheImpactClipBandIsUnchangedAndStillDisclosed:
    @pytest.mark.asyncio
    async def test_the_disclosed_band_is_the_band_that_binds(self):
        """`-1%` still publishes `-2.00%`, and the payload still says so.

        `max(-0.75, min(-0.02, ticker_impact))` floors the magnitude of every
        negative-shock impact at 2%, disclosed at
        `shock_inputs.position_impact_clip`.  This was NOT changed by the
        volatility filter above: it is a configured bound, it is published, and
        changing it would move every published impact for a different reason
        than the one under repair.  It is pinned here so that a future change
        to it is a deliberate, visible act.
        """
        returns = _returns_with_flat_sessions()
        result = await ENGINE.stress_test(
            _price_frame({"AAA.NS": returns}, pd.bdate_range("2023-01-02", periods=len(returns))),
            {"AAA.NS": 1.0},
            "crash -1%",
        )
        shock = result["shock_inputs"]

        assert shock["market_shock"] == -0.01
        assert shock["position_impact_clip"] == [-0.75, -0.02]
        assert shock["position_impact_clip_basis"] == "configured_bounds_not_simulated"
        # A -1% request publishing -2.00%: the floor, not the request.
        assert result["position_impacts"]["AAA.NS"] == -0.02

    @pytest.mark.asyncio
    async def test_the_clip_does_not_bind_a_shock_deeper_than_the_floor(self):
        """The band is a floor on magnitude, not a ceiling on it."""
        returns = _returns_with_flat_sessions()
        result = await ENGINE.stress_test(
            _price_frame({"AAA.NS": returns}, pd.bdate_range("2023-01-02", periods=len(returns))),
            {"AAA.NS": 1.0},
            "market_crash",
        )
        impact = result["position_impacts"]["AAA.NS"]
        assert impact < -0.02, impact