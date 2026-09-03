"""P0-6 contract tests: EVT never fabricates tail numbers.

Regression gate for BACKEND_REVIEW P0-6 (n<20 returned hardcoded
-0.0385/-0.0492/... presented as computed VaR/ES). Short history must
raise; the normal path is unchanged.
"""

import numpy as np
import pandas as pd
import pytest

from app.services.tail_risk_service import TailRiskService


def test_short_history_raises_not_hardcodes():
    with pytest.raises(ValueError, match="Insufficient observations"):
        TailRiskService.calculate_evt_pot_var_es(pd.Series([0.01, -0.02, 0.005]))
    with pytest.raises(ValueError, match="Insufficient observations"):
        TailRiskService.calculate_evt_pot_var_es(np.array([0.01] * 19))


def test_boundary_n20_computes():
    rng = np.random.default_rng(0)
    res = TailRiskService.calculate_evt_pot_var_es(pd.Series(rng.normal(0, 0.02, 20)))
    assert res["total_observations"] == 20
    assert res["evt_pot_es_99"] <= res["evt_pot_var_99"]


def test_normal_path_unchanged():
    rng = np.random.default_rng(42)
    res = TailRiskService.calculate_evt_pot_var_es(
        pd.Series(rng.normal(0.0002, 0.02, 300)),
        confidence_level=0.99, threshold_quantile=0.95,
    )
    assert res["total_observations"] == 300
    assert res["evt_pot_var_99"] < 0
    assert res["evt_pot_es_99"] <= res["evt_pot_var_99"]
    assert "gpd_shape_xi" in res


def test_suite_propagates_short_history():
    df = pd.DataFrame({"A": [0.01, -0.02, 0.005]})
    with pytest.raises(ValueError, match="Insufficient observations"):
        TailRiskService.calculate_full_tail_risk_suite(df, {"A": 1.0})
