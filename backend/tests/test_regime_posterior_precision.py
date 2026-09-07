"""Issue 04: regime posterior precision — small posteriors must survive the service.

`classify` used to round `regime_probabilities` to 1dp, destroying
display-layer information at the source (0.04% -> 0.0%). Now 4dp.
The HMM is faked with a controlled last-row posterior
[0.6, 0.3996, 0.0004] so the 0.04% tail is asserted exactly; the
transition matrix rounding (1dp) is pinned unchanged.
"""

from unittest.mock import patch

import numpy as np
import pandas as pd

from app.services.regime_service import classify


class _FakeScaler:
    def fit_transform(self, x):
        return np.asarray(x, dtype=float)


class _FakeHMM:
    def __init__(self, *args, **kwargs):
        self.startprob_ = np.array([0.33, 0.34, 0.33])
        self.transmat_ = np.eye(3)

    def fit(self, x):
        self.transmat_ = np.array([
            [0.96, 0.03, 0.01],
            [0.02, 0.96, 0.02],
            [0.01, 0.03, 0.96],
        ])
        return self

    def predict(self, x):
        return np.array([i % 3 for i in range(len(x))])

    def predict_proba(self, x):
        n = len(x)
        return np.tile(np.array([0.6, 0.3996, 0.0004]), (n, 1))


def _bench_df():
    np.random.seed(7)
    dates = pd.date_range("2024-01-01", periods=300, freq="B")
    close = 100 * np.cumprod(1 + np.random.normal(0.0005, 0.01, 300))
    return pd.DataFrame(
        {"close": close, "high": close * 1.005, "low": close * 0.995},
        index=dates,
    )


def _classify_with_tiny_tail():
    with (
        patch("sklearn.preprocessing.StandardScaler", _FakeScaler),
        patch("hmmlearn.hmm.GaussianHMM", _FakeHMM),
    ):
        return classify(_bench_df())


def test_small_posterior_survives_unrounded_to_zero():
    res = _classify_with_tiny_tail()
    probs = res["regime_probabilities"]
    assert set(probs) == {"crisis", "calm", "bull"}
    assert min(probs.values()) == 0.04  # 0.0004 * 100; was 0.0 at 1dp
    assert 0.0 not in probs.values()
    assert abs(sum(probs.values()) - 100.0) < 0.01


def test_transition_matrix_rounding_unchanged():
    res = _classify_with_tiny_tail()
    flat = sorted(v for row in res["transition_matrix"].values() for v in row.values())
    assert flat == [1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 96.0, 96.0, 96.0]
