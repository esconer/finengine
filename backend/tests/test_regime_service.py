import numpy as np
import pandas as pd
import pytest
from app.services.regime_service import _label_states_by_risk, classify, detect_regime, MIN_OBSERVATIONS


def test_label_states_by_risk():
    # State 0: Negative return -> crisis
    # State 1: Low vol, steady return -> calm
    # State 2: High return, elevated vol -> bull
    df = pd.DataFrame([
        {'ann_ret': -0.28, 'ann_vol': 0.22},
        {'ann_ret': 0.07, 'ann_vol': 0.09},
        {'ann_ret': 0.50, 'ann_vol': 0.21},
    ])
    mapping = _label_states_by_risk(df)
    assert mapping[0] == 'crisis'
    assert mapping[1] == 'calm'
    assert mapping[2] == 'bull'


def test_classify_insufficient_data():
    s = pd.Series([0.01] * 50)
    assert classify(s) is None
    assert classify(None) is None


def test_classify_synthetic_dataframe():
    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=300, freq='B')
    close = 100 * np.cumprod(1 + np.random.normal(0.0005, 0.01, 300))
    high = close * 1.005
    low = close * 0.995
    bench_df = pd.DataFrame({'close': close, 'high': high, 'low': low}, index=dates)

    res = classify(bench_df)
    assert res is not None
    assert res['current_regime'] in ['calm', 'bull', 'crisis']
    assert 0 <= res['stability_pct'] <= 100
    assert 'transition_matrix' in res
    assert 'regime_probabilities' in res
    assert len(res['states']) == 3
    assert res['realtime_ewma_vol'] is not None
    assert res['observations'] >= MIN_OBSERVATIONS


def test_classify_synthetic_series():
    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=250, freq='B')
    close = pd.Series(100 * np.cumprod(1 + np.random.normal(0.0005, 0.01, 250)), index=dates)

    res = classify(close)
    assert res is not None
    assert res['current_regime'] in ['calm', 'bull', 'crisis']
    assert res['realtime_parkinson_vol'] is None
