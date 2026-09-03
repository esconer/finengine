"""Crash-veto contract tests: a -10%/21d day is never displayed as bull/calm.

Regression gate for the Mar-2026 inversion (crash leg wore Bull Rally
colors: trailing 21d windows stay positive for weeks into a fast crash,
so crash days join a high-mean state that global-mean labeling crowns
'bull'). Synthetic prices only: no DB, no network.
"""

import numpy as np
import pandas as pd

from app.services.regime_service import (
    CRASH_VETO_RET21,
    apply_crash_veto,
    classify,
)


def _prices(n=250, seed=7, crash=None, vol=0.008):
    rng = np.random.default_rng(seed)
    daily = rng.normal(0.0004, vol, n)
    if crash is not None:
        start, length, drift, noise = crash
        daily[start:start + length] = drift + rng.normal(0, noise, length)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.Series(100.0 * np.exp(np.cumsum(daily)), index=idx)


def _trailing_ret21(prices):
    return np.log(prices / prices.shift(21))


def test_apply_crash_veto_unit():
    label_map = {0: "bull", 1: "calm", 2: "crisis"}
    states = np.array([0, 0, 1, 1, 2, 0])
    ret21 = np.array([-0.15, -0.05, -0.12, 0.03, -0.20, 0.10])
    display, count = apply_crash_veto(states, label_map, ret21)
    assert list(display) == [2, 0, 2, 1, 2, 0]
    assert count == 2
    # input untouched, deterministic
    assert list(states) == [0, 0, 1, 1, 2, 0]
    display2, count2 = apply_crash_veto(states, label_map, ret21)
    assert list(display2) == list(display) and count2 == count


def test_apply_crash_veto_no_crisis_label_is_noop():
    display, count = apply_crash_veto(
        np.array([0, 1]), {0: "bull", 1: "calm"}, np.array([-0.5, -0.5])
    )
    assert list(display) == [0, 1] and count == 0


def test_crash_days_never_displayed_bull_or_calm():
    # Whipsaw crash: relief bounces pull crash days into high-mean states.
    prices = _prices(crash=(150, 20, -0.015, 0.030))
    res = classify(prices)
    assert res is not None
    assert res["label_overrides"]["crash_veto_threshold"] == CRASH_VETO_RET21
    hist = pd.Series(res["all_regimes"])
    hist.index = pd.to_datetime(hist.index)
    frame = pd.DataFrame({"regime": hist, "ret21": _trailing_ret21(prices).reindex(hist.index)})
    bad = frame[(frame["ret21"] < CRASH_VETO_RET21) & (frame["regime"] != "crisis")]
    assert bad.empty, bad.to_string()


def test_benign_series_untouched():
    prices = _prices(seed=11, vol=0.004)
    res = classify(prices)
    assert res is not None
    assert res["label_overrides"]["crash_veto_days"] == 0
    assert {s["regime"] for s in res["states"]} == {"crisis", "calm", "bull"}


def test_veto_deterministic_and_stable():
    prices = _prices(crash=(150, 20, -0.015, 0.030))
    first = classify(prices)
    second = classify(prices)
    assert first["current_regime"] == second["current_regime"]
    assert first["label_overrides"] == second["label_overrides"]
    assert first["stability_pct"] >= 80.0
