"""P0-1 contract tests: HRP recursive bisection on cluster variance.

Regression gate for BACKEND_REVIEW P0-1
(`optimization_service._hrp_weights` used weight-sum rescaling and dropped
singletons, so N=3 never bisected and allocation violated Lopez de Prado 2016).
Pure tests: no DB, no network, seeded RNG only.
"""

import numpy as np
import pandas as pd

from app.services.optimization_service import (
    _hrp_weights,
    measurable_clustering_universe,
    optimize,
)


def _seeded_returns(n_obs=500, vols=(0.01, 0.01, 0.04, 0.04), seed=0):
    rng = np.random.default_rng(seed)
    data = {f"A{i}": rng.normal(0.0005, v, n_obs) for i, v in enumerate(vols)}
    dates = pd.date_range("2020-01-01", periods=n_obs, freq="B")
    return pd.DataFrame(data, index=dates)


def test_hrp_sums_to_one_and_nonnegative():
    rets = _seeded_returns()
    w = _hrp_weights(rets)
    assert abs(w.sum() - 1.0) < 1e-4
    assert (w.values >= 0).all()
    assert np.isfinite(w.values).all()


def test_hrp_odd_n_actually_bisects():
    """N=3 must not return raw inverse-variance weights (the old bug)."""
    rets = _seeded_returns(vols=(0.01, 0.02, 0.03), seed=1).iloc[:, :3]
    w = _hrp_weights(rets)
    cov = rets.cov().values
    raw_ivp = 1.0 / np.diag(cov)
    raw_ivp /= raw_ivp.sum()
    raw = pd.Series(raw_ivp, index=rets.columns)
    raw_ordered = raw.loc[w.index]
    assert not np.allclose(w.values, raw_ordered.values, atol=1e-6)
    assert abs(w.sum() - 1.0) < 1e-4


def test_hrp_favors_low_variance_cluster():
    rets = _seeded_returns()
    w = _hrp_weights(rets)
    low = w[["A0", "A1"]].sum()
    high = w[["A2", "A3"]].sum()
    assert low > high


def test_hrp_flat_series_is_declined_not_treated_as_uncorrelated():
    """A leg that never moves has no correlation to anything, and must be said so.

    The old assertion was:

        rets["A3"] = 0.0  # zero-variance leg: NaN corr guard must hold
        w = _hrp_weights(rets)
        assert np.isfinite(w.values).all()
        assert abs(w.sum() - 1.0) < 1e-4
        assert (w.values >= 0).all()

    which passed only because `corr().fillna(0.0)` turned A3's three NaN pairs
    into "no relationship whatsoever" and clustered it at the maximum distance
    in the matrix. That encoded the defect: a leg with no measurable
    correlation was allocated as though it were a diversifier. The assertions
    that matter are kept; the leg is now declined from the clustering instead,
    and the refusal is visible.
    """
    rets = _seeded_returns()
    rets["A3"] = 0.0  # zero-variance leg: no correlation is measurable to anyone
    w = _hrp_weights(rets)
    assert np.isfinite(w.values).all()
    assert abs(w.sum() - 1.0) < 1e-4
    assert (w.values >= 0).all()
    # Declined, not silently kept at a fabricated distance.
    assert set(w.index) == {"A0", "A1", "A2"}
    kept, dropped = measurable_clustering_universe(rets)
    assert dropped == ["A3"]
    assert kept == ["A0", "A1", "A2"]
    # And `optimize` says so in the payload rather than dropping it in silence.
    res = optimize(rets, "hrp")
    assert res["excluded"] == ["A3"]
    assert "fewer than two shared return rows" in res["excluded_reasons"]["A3"]
    assert res["weights"]["A3"] == 0.0
    assert abs(sum(res["weights"].values()) - 1.0) < 1e-4


def test_hrp_deterministic():
    rets = _seeded_returns(seed=7)
    w1 = _hrp_weights(rets)
    w2 = _hrp_weights(rets)
    pd.testing.assert_series_equal(w1, w2)


def test_optimize_hrp_end_to_end_sum():
    rets = _seeded_returns()
    res = optimize(rets, "hrp")
    assert abs(sum(res["weights"].values()) - 1.0) < 1e-4
