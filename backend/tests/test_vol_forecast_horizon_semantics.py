"""An EWMA spot estimate publishes no horizon, and no volatility, when there is
none to measure.

Two defects in `volatility_service`, one class: a missing measurement published
as a plausible number.

**Defect 1 - `horizon_days` carries two different quantities.**  An EWMA
(RiskMetrics) spot estimate is a one-step number that takes no horizon at all:
`calculate_ewma_volatility` is not a function of `horizon`.  The GARCH branch
really does forecast `forecast_horizon` steps, so `horizon_days: 21` beside an
`"EWMA"` label told a reader that a 1-day number covered 21 days.  The label
`"EWMA"` reaches `current_forecast` two ways - the direct
`forecast_model="EWMA"` branch, and the GARCH call's own EWMA fallback (too few
returns, or a failed fit) - so both publish `horizon_days: None` plus a
`horizon_note`.  A GARCH(1,1) row is unchanged: its 21 is a measurement.

**Defect 2 - `calculate_ewma_volatility` returned `0.0` for one observation.**
A single return contains no dispersion estimate.  `0.0` is the strongest
possible volatility claim ("this book does not move") and it is a *number*:
rankable, comparable, and - sitting below any non-negative p25 - published as
`valuation: "cheap"`.  It now returns `None`, and the cone withholds the level,
the rank and the verdict through the same `"unknown"` branch it already uses for
a benchmark window with no distribution.

`horizon_note` / `annualized_vol_withheld_reason` are published ONLY where the
value they explain is absent.  They are deliberately not always-present keys:
`test_vol_cone_forecast_disclosure.py::test_payload_key_sets_are_unchanged`
pins the GARCH cone's key set byte-for-byte, and for a GARCH row the horizon is
a measurement that needs no excuse.

No DB, no network, no audit CLI: seeded RNG only.
"""

import numpy as np
import pandas as pd
import pytest

from app.services.volatility_service import VolatilityService

SEED = 4242
AS_OF = "2026-01-02"


def _returns(n=500, seed=SEED, scale=0.0105):
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0004, scale, n))


# ---------------------------------------------------------------------------
# Defect 1: horizon_days must not be a number on a horizon-free estimate
# ---------------------------------------------------------------------------
class TestEwmaPublishesNoHorizon:
    def test_direct_ewma_branch_withholds_the_horizon(self):
        cone = VolatilityService.calculate_volatility_cone(
            _returns(), windows=[10, 21], forecast_model="EWMA", as_of=AS_OF
        )
        fc = cone["current_forecast"]
        assert fc["model"] == "EWMA"
        # RED on the shipped code: 21.
        assert fc["horizon_days"] is None
        # RED on the shipped code: KeyError.
        assert isinstance(fc["horizon_note"], str)
        assert fc["horizon_note"]

    def test_the_garch_call_own_ewma_fallback_also_withholds_it(self):
        """`forecast_model="GARCH"` on <30 returns still publishes model EWMA.

        This is the path the brief's two-line view misses: the label reaches the
        overlay without the caller ever asking for EWMA.
        """
        cone = VolatilityService.calculate_volatility_cone(
            _returns(n=25), windows=[10, 21], forecast_model="GARCH", as_of=AS_OF
        )
        fc = cone["current_forecast"]
        assert fc["model"] == "EWMA"  # fell back
        assert fc["horizon_days"] is None
        assert fc["horizon_note"]

    def test_a_garch_row_is_untouched(self):
        """The horizon is a real measurement on this branch - do not over-refuse."""
        cone = VolatilityService.calculate_volatility_cone(
            _returns(), windows=[10, 21], forecast_model="GARCH", as_of=AS_OF
        )
        fc = cone["current_forecast"]
        assert fc["model"] == "GARCH(1,1)"
        assert fc["horizon_days"] == 21
        assert "horizon_note" not in fc

    def test_the_two_models_no_longer_claim_the_same_quantity(self):
        """The defect itself: one field name, two quantities, chosen by label."""
        garch = VolatilityService.calculate_volatility_cone(
            _returns(), windows=[10, 21], forecast_model="GARCH", as_of=AS_OF
        )["current_forecast"]
        ewma = VolatilityService.calculate_volatility_cone(
            _returns(), windows=[10, 21], forecast_model="EWMA", as_of=AS_OF
        )["current_forecast"]
        # Same input, same field, two different meanings - and the reader could
        # not tell, because both said 21.
        assert ewma["annualized_vol"] is not None
        assert garch["horizon_days"] != ewma["horizon_days"]

    def test_the_forecast_garch_dict_does_not_publish_a_horizon_for_its_fallback(self):
        """`forecast_garch_volatility`'s EWMA fallback is the same defect.

        `{"annualized_vol": ..., "model": "EWMA", "horizon": 21}` asserted a
        21-day horizon for an estimate that takes no horizon.
        """
        res = VolatilityService.forecast_garch_volatility(
            _returns(n=25), horizon=21
        )
        assert res["model"] == "EWMA"
        assert res["horizon"] is None  # RED on the shipped code: 21

        fitted = VolatilityService.forecast_garch_volatility(
            _returns(n=400), horizon=21
        )
        assert fitted["model"] == "GARCH(1,1)"
        assert fitted["horizon"] == 21


# ---------------------------------------------------------------------------
# Defect 2: one observation has no dispersion estimate
# ---------------------------------------------------------------------------
class TestSingleObservationIsNotZeroVolatility:
    def test_the_estimator_withholds_instead_of_returning_zero(self):
        # RED on the shipped code: 0.0.
        assert VolatilityService.calculate_ewma_volatility(pd.Series([0.02])) is None

    def test_empty_input_still_raises(self):
        """The existing no-fabrication contract for n == 0 is preserved."""
        with pytest.raises(ValueError, match="empty"):
            VolatilityService.calculate_ewma_volatility(pd.Series(dtype=float))

    def test_two_or_more_observations_still_measure(self):
        """Do not over-refuse: the answer appears as soon as it is knowable."""
        two = VolatilityService.calculate_ewma_volatility(pd.Series([0.02, -0.01]))
        assert two is not None and two > 0.0

    def test_the_garch_fallback_does_not_publish_a_zero_volatility(self):
        res = VolatilityService.forecast_garch_volatility(pd.Series([0.02]), horizon=21)
        assert res["model"] == "EWMA"
        assert res["annualized_vol"] is None  # RED: 0.0
        assert res["horizon"] is None

    def test_the_cone_withholds_the_level_the_rank_and_the_verdict(self):
        cone = VolatilityService.calculate_volatility_cone(
            pd.Series([0.02]), windows=[10, 21], forecast_model="EWMA", as_of=AS_OF
        )
        fc = cone["current_forecast"]
        assert fc["annualized_vol"] is None  # RED: 0.0
        assert fc["percentile_rank"] is None
        assert fc["valuation"] == "unknown"
        assert isinstance(fc["annualized_vol_withheld_reason"], str)
        assert fc["annualized_vol_withheld_reason"]
        assert fc["horizon_note"]

    def test_an_unmeasurable_forecast_never_raises_and_never_verdicts(self, monkeypatch):
        """The cone must tolerate a null level against a REAL distribution.

        `np.sum(series <= None)` raises and `None <= p25` raises, so this is
        the guard that keeps a missing measurement from becoming a 500 or,
        worse, a cheap verdict once a future caller supplies one. 800 returns
        so the benchmark distribution exists and the rank is otherwise
        publishable.
        """
        monkeypatch.setattr(
            VolatilityService,
            "calculate_ewma_volatility",
            staticmethod(lambda *a, **k: None),
        )
        cone = VolatilityService.calculate_volatility_cone(
            _returns(n=800), windows=[10, 21], forecast_model="EWMA", as_of=AS_OF
        )
        fc = cone["current_forecast"]
        assert fc["annualized_vol"] is None
        assert fc["percentile_rank"] is None
        assert fc["valuation"] == "unknown"
        # A withheld rank still ships with a reason naming the absent level.
        assert fc["percentile_rank_withheld_reason"]
        assert "annualized_vol" in fc["percentile_rank_withheld_reason"]
        # And the measured distribution beside it is untouched.
        row21 = cone["windows"][1]
        assert row21["p25"] is not None and row21["p75"] is not None
        assert row21["current_realized"] is not None

    def test_a_measured_forecast_still_verdicts(self, monkeypatch):
        """The guard must not swallow real verdicts: 0.5 sits above the p75 band.

        800 returns so the 21-day benchmark clears the effective-observation gate
        (800-21+1 = 780 windows / 21 = 37.1 >= 30) and a rank is publishable at
        all; the point here is that the null guard did not eat it.
        """
        monkeypatch.setattr(
            VolatilityService,
            "calculate_ewma_volatility",
            staticmethod(lambda *a, **k: 0.5),
        )
        fc = VolatilityService.calculate_volatility_cone(
            _returns(n=800), windows=[10, 21], forecast_model="EWMA", as_of=AS_OF
        )["current_forecast"]
        assert fc["annualized_vol"] == 0.5
        assert fc["valuation"] == "rich"
        assert fc["percentile_rank"] is not None
        assert "annualized_vol_withheld_reason" not in fc