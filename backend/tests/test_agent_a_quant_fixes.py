"""Agent A quantitative remediation regressions (A-01..A-13).

These tests are deterministic and use synthetic frames only; no vendor calls
or portfolio database are involved.
"""
from __future__ import annotations

import math
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
from arch import arch_model

from app.api.analytics import _build_wide_returns
from app.services.analytics_engine import AnalyticsEngine
from app.services.cache_service import advance_cache_generation, get_cache_generation
from app.services.backtest_service import run_walk_forward_backtest
from app.services.benchmark_service import BenchmarkService
from app.services.cointegration_service import (
    CointegrationService,
    _IN_MEMORY_COINT_CACHE,
    _db_cache_keys,
    _mem_cache_key,
)
from app.services.indicators_service import _clean_dataframe, _compute_sync
from app.services.monte_carlo_service import simulate_goal
from app.services.tail_risk_service import TailRiskService
from app.services.volatility_service import VolatilityService


def _forecast_returns(n: int = 240, seed: int = 2026) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(
        np.clip(0.0003 + 0.01 * rng.standard_t(df=8, size=n), -0.18, 0.18),
        index=pd.bdate_range("2022-01-03", periods=n),
    )


@pytest.mark.asyncio
async def test_a01_garch_tail_uses_cumulative_horizon_and_egarch_simulates():
    engine = AnalyticsEngine()
    returns = _forecast_returns()

    def independent_garch_var(horizon: int) -> float:
        scaled = returns.to_numpy(dtype=float) * 100.0
        fitted = arch_model(scaled, vol="Garch", p=1, q=1, dist="normal", rescale=False).fit(
            disp="off", show_warning=False, options={"maxiter": 100}
        )
        path = fitted.forecast(horizon=horizon, method="analytic").variance.values[-1]
        cumulative = np.asarray(path, dtype=float)
        return_space = math.sqrt(float(np.sum(cumulative))) / 100.0
        return -return_space * 1.645

    for horizon in (1, 5, 21):
        result = await engine._garch_forecast(returns, horizon)
        assert result["var_forecast"] == pytest.approx(
            independent_garch_var(horizon), rel=2e-3, abs=2e-4
        )
        assert result["volatility_forecast"] == pytest.approx(
            math.sqrt(
                float(np.sum(
                    arch_model(returns.to_numpy(dtype=float) * 100.0, vol="Garch", p=1, q=1,
                               dist="normal", rescale=False).fit(
                                   disp="off", show_warning=False, options={"maxiter": 100}
                               ).forecast(horizon=horizon, method="analytic").variance.values[-1]
                )) * 252.0 / horizon
            ) / 100.0,
            rel=2e-3,
            abs=2e-4,
        )

    egarch = await engine._egarch_forecast(returns, 5)
    assert egarch["volatility_forecast"] is not None
    assert egarch["var_forecast"] is not None
    assert np.isfinite(egarch["volatility_forecast"])
    assert egarch["model_params"]["forecast_method"] == "simulation"
    assert egarch["model_params"]["random_state"] == 100


@pytest.mark.asyncio
async def test_a02_active_weights_are_renormalized_without_prelisting_zeroes():
    idx = pd.bdate_range("2024-01-02", periods=180)
    rng = np.random.default_rng(17)
    a = 100 * np.cumprod(1 + rng.normal(0.0004, 0.009, len(idx)))
    b = np.full(len(idx), np.nan)
    b[60:] = 80 * np.cumprod(1 + rng.normal(-0.0001, 0.014, len(idx) - 60))
    prices = pd.DataFrame({"A": a, "B": b}, index=idx)
    result = await AnalyticsEngine().calculate_portfolio_metrics(
        prices, {"A": 0.5, "B": 0.5}
    )
    raw = prices.pct_change(fill_method=None).iloc[1:]
    active_weight = raw.notna().mul({"A": 0.5, "B": 0.5}, axis=1).sum(axis=1)
    reference = raw.fillna(0).mul({"A": 0.5, "B": 0.5}, axis=1).sum(axis=1)
    reference = reference.loc[active_weight > 0] / active_weight.loc[active_weight > 0]
    assert result["annual_return"] == pytest.approx(reference.mean() * 252)
    assert result["annual_volatility"] == pytest.approx(reference.std(ddof=1) * math.sqrt(252))
    assert result["active_observations"] == int(reference.size)


def test_a03_drawdown_includes_initial_wealth_in_engine_and_backtest():
    engine = AnalyticsEngine()
    assert engine._calculate_drawdown_metrics(pd.Series([-0.10]))["max_drawdown"] == pytest.approx(-0.10)
    idx = pd.bdate_range("2024-01-01", periods=40)
    returns = pd.DataFrame(0.0, index=idx, columns=["A"])
    returns.iloc[20, 0] = -0.10
    result = run_walk_forward_backtest(
        returns, strategy="equal_weight", lookback_days=20,
        rebalance_freq_days=20, transaction_cost_bps=0,
    )
    assert result["max_drawdown"] == pytest.approx(-0.10, abs=5e-5)


def test_a04_evt_keeps_raw_fit_and_discloses_constraints():
    probabilities = (np.arange(10) + 0.5) / 10.0
    xi = -0.8
    beta = 0.01
    excess = beta / xi * ((1 - probabilities) ** (-xi) - 1)
    returns = pd.Series(-np.concatenate([np.zeros(190), 0.02 + excess]))
    result = TailRiskService.calculate_evt_pot_var_es(
        returns, confidence_level=0.99, threshold_quantile=0.90
    )
    assert result["model_fitted"] is True
    assert result["gpd_shape_xi_raw"] < -0.5
    assert result["gpd_shape_xi"] == pytest.approx(result["gpd_shape_xi_raw"], abs=1e-3)
    assert result["gpd_shape_xi_constrained"] == pytest.approx(-0.5)
    assert result["metrics_constrained"] is True
    assert result["evt_pot_var_unconstrained"] is not None
    assert result["evt_pot_es_unconstrained"] is not None
    assert result["constraint_reason"]


def test_a05_mfi_is_canonical_zero_to_one_hundred_scale():
    rng = np.random.default_rng(314)
    n = 80
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.012, n)))
    frame = pd.DataFrame({
        "Date": pd.bdate_range("2024-01-01", periods=n),
        "Open": close,
        "High": close * 1.01,
        "Low": close * 0.99,
        "Close": close,
        "Volume": rng.integers(10_000, 100_000, n),
    })
    got = float(_compute_sync(frame, ["mfi"])["mfi"].iloc[-1])
    typical = (frame["High"] + frame["Low"] + frame["Close"]) / 3
    flow = typical * frame["Volume"]
    delta = np.diff(typical.to_numpy(), prepend=typical.iloc[0])
    positive = np.where(delta > 0, flow, 0)[-14:].sum()
    negative = np.where(delta < 0, flow, 0)[-14:].sum()
    expected = 100 * positive / (positive + negative)
    assert got == pytest.approx(expected, abs=1e-10)


def test_a05_indicator_cleaner_preserves_interior_missing_price_time_axis():
    idx = pd.bdate_range("2024-01-01", periods=60)
    close = np.arange(60, dtype=float) + 100.0
    frame = pd.DataFrame(
        {
            "date": idx,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000.0,
        }
    )
    frame.loc[20, "close"] = np.nan
    cleaned = _clean_dataframe(frame)
    assert len(cleaned) == len(frame)
    assert pd.isna(cleaned.loc[20, "Close"])
    computed = _compute_sync(cleaned, ["close_50_sma", "mfi"])
    assert len(computed) == len(frame)
    assert pd.isna(computed.iloc[20]["mfi"])


def test_a05_mfi_masks_rows_with_nonpositive_price():
    idx = pd.bdate_range("2024-01-01", periods=40)
    close = np.linspace(100.0, 110.0, len(idx))
    frame = pd.DataFrame(
        {
            "Date": idx,
            "Open": close,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": 10_000.0,
        }
    )
    frame.loc[20, "Close"] = 0.0

    computed = _compute_sync(frame, ["mfi"])

    assert pd.isna(computed.iloc[20]["mfi"])


def test_a13_rolling_volatility_preserves_interior_gap_axis():
    idx = pd.bdate_range("2024-01-01", periods=80)
    returns = pd.Series(np.linspace(-0.01, 0.01, len(idx)), index=idx)
    returns.iloc[40] = np.nan
    rolling = VolatilityService.calculate_rolling_realized_volatility(returns, window=21)
    assert rolling.index.isin(idx).all()
    assert (rolling.index > idx[40]).any()
    assert len(rolling) < len(idx)


def test_a06_backtest_rejects_invalid_cost_and_risk_free_before_work():
    idx = pd.bdate_range("2024-01-01", periods=40)
    returns = pd.DataFrame({"A": np.zeros(40)}, index=idx)
    for kwargs in (
        {"transaction_cost_bps": -1},
        {"transaction_cost_bps": float("nan")},
        {"transaction_cost_bps": float("inf")},
        {"risk_free_rate": float("nan")},
    ):
        with pytest.raises(ValueError):
            run_walk_forward_backtest(
                returns, strategy="equal_weight", lookback_days=20,
                rebalance_freq_days=10, **kwargs
            )


def test_a07_backtest_drifts_weights_and_charges_costs_at_boundaries(monkeypatch):
    import app.services.backtest_service as bt

    idx = pd.bdate_range("2024-01-01", periods=60)
    values = np.zeros((60, 2))
    values[20] = [0.10, 0.00]
    values[21] = [0.00, 0.05]
    returns = pd.DataFrame(values, index=idx, columns=["A", "B"])
    monkeypatch.setattr(
        bt, "optimize",
        lambda train_window, strategy="hrp", risk_free_rate=0.02:
        {"weights": {"A": 0.8, "B": 0.2}},
    )
    result = run_walk_forward_backtest(
        returns, strategy="hrp", lookback_days=20,
        rebalance_freq_days=20, transaction_cost_bps=0,
    )
    assert result["rebalance_events"][0]["turnover"] == pytest.approx(0.3)
    assert result["rebalance_events"][1]["turnover"] > 0
    assert result["benchmark_method"] == "equal_weight_buy_and_hold"
    assert result["strategy_accounting"] == "self_financing_weight_drift"


def test_a08_monte_carlo_uses_bounded_chunks_and_checkpoints(monkeypatch):
    import app.services.monte_carlo_service as mc

    calls = []

    def fake_gbm(mu_annual, sigma_annual, initial_value, horizon_years, num_paths, rng):
        calls.append(num_paths)
        steps = int(round(float(horizon_years) * mc.TRADING_DAYS))
        return np.broadcast_to(np.array([[float(initial_value)]]), (num_paths, steps + 1))

    monkeypatch.setattr(mc, "_simulate_gbm", fake_gbm)
    returns = pd.Series(np.random.default_rng(1).normal(0.0004, 0.01, 300))
    result = simulate_goal(returns, 100_000, 150_000, 40, method="gbm", num_paths=20_000, seed=1)
    assert result["num_paths"] == 4_960
    assert len(calls) > 1
    assert max(calls) <= mc.MAX_CHUNK_ELEMENTS // (40 * mc.TRADING_DAYS) + 1
    assert result["checkpoint_count"] > 1
    assert result["fan"][0]["year"] == 0.0
    assert result["fan"][-1]["year"] == 40.0


def test_a09_coint_cache_keys_include_lookback_and_coverage():
    assert _mem_cache_key("A", "B", "2026-09-24", lookback_days=60) != _mem_cache_key(
        "A", "B", "2026-09-24", lookback_days=2520
    )
    assert _db_cache_keys("A", "B", "2026-09-24", lookback_days=60) != _db_cache_keys(
        "A", "B", "2026-09-24", lookback_days=2520
    )
    assert _mem_cache_key("A", "B", "2026-09-24", history_coverage="60:2026-01-01:2026-09-24") != _mem_cache_key(
        "A", "B", "2026-09-24", history_coverage="2520:2020-01-01:2026-09-24"
    )


@pytest.mark.asyncio
async def test_a09_cache_generation_drops_late_cointegration_write():
    class Result:
        engle_granger_pvalue = 0.01

        def model_dump(self):
            return {
                "ticker_a": "A", "ticker_b": "B", "engle_granger_pvalue": 0.01,
                "engle_granger_tstat": -3.0, "is_cointegrated": True,
                "hedge_ratio_beta": 1.0, "intercept_alpha": 0.0,
                "johansen_cointegrated": False, "last_price_a": 100.0,
                "last_price_b": 100.0, "signal": "None",
            }

    _IN_MEMORY_COINT_CACHE.clear()
    cache = Mock()
    service = CointegrationService(cache_service=cache)
    generation = get_cache_generation()
    advance_cache_generation("test purge")
    await service._set_cached_pair(
        "A", "B", "2026-09-24", Result(), cache_generation=generation
    )
    assert _IN_MEMORY_COINT_CACHE == {}
    cache.set_cached_analytics.assert_not_called()


@pytest.mark.asyncio
async def test_a10_benchmark_fetch_is_anchored_to_requested_end():
    class FakeData:
        def __init__(self):
            self.calls = []

        async def fetch_historical_data(self, ticker, start, end):
            self.calls.append((ticker, start, end))
            return pd.DataFrame({
                "date": pd.date_range("2020-01-01", "2020-02-15"),
                "adj_close": np.linspace(100, 130, 46),
            })

    service = BenchmarkService(db_session=Mock())
    fake = FakeData()
    service.data_service = fake
    await service.get_returns(start="2020-01-01", end="2020-02-01", days=10)
    assert fake.calls == [("^NSEI", "2020-01-01", "2020-02-01")]


def test_a11_tail_confidence_uses_neutral_fields_for_non_default_level():
    returns = pd.Series(np.random.default_rng(811).standard_t(df=5, size=500) * 0.015 + 0.0002)
    result = TailRiskService.calculate_evt_pot_var_es(
        returns, confidence_level=0.95, threshold_quantile=0.90
    )
    assert "evt_pot_var" in result and "evt_pot_es" in result
    assert "evt_pot_var_99" not in result
    assert result["confidence_level"] == pytest.approx(0.95)


def test_a12_one_observation_ewma_uses_explicit_zero_contract():
    assert VolatilityService.calculate_ewma_volatility(pd.Series([0.05])) == 0.0
    with pytest.raises(ValueError):
        VolatilityService.calculate_ewma_volatility(pd.Series(dtype=float))


@pytest.mark.asyncio
async def test_a13_hhi_inverse_vol_and_monthly_invariants_remain_true():
    engine = AnalyticsEngine()
    conc = await engine.concentration_analysis({"A": 0.8, "B": 0.1, "C": 0.1})
    assert conc["herfindahl_index"] == pytest.approx(0.66)
    assert conc["effective_positions"] == pytest.approx(round(1 / 0.66, 2))
    assert conc["diversification_score"] == pytest.approx(51.0)
    single = await engine.concentration_analysis({"A": 1.0})
    assert single["diversification_score"] == 0.0
    with_zero = await engine.concentration_analysis({"A": 0.8, "B": 0.2, "ZERO": 0.0})
    assert with_zero["diversification_score"] == pytest.approx(64.0)

    dates = pd.bdate_range("2024-01-01", periods=80)
    returns = pd.DataFrame({"A": 0.01, "B": -0.005, "ZERO": 0.0}, index=dates)
    prices = pd.DataFrame(
        {col: 100 * (1 + returns[col]).cumprod() for col in returns}, index=dates
    )
    sized = await engine.volatility_sizing(
        prices, {"A": 0.5, "B": 0.5, "ZERO": 0.0}, model="EWMA", target_volatility=1.0
    )
    assert "ZERO" not in sized["recommended_weights"]
    ratio = sized["recommended_weights"]["A"] / sized["recommended_weights"]["B"]
    expected = (1 / sized["volatilities"]["A"]) / (1 / sized["volatilities"]["B"])
    assert ratio == pytest.approx(expected, rel=1e-5)

    class FakeData:
        async def fetch_historical_data(self, ticker, start, end):
            return pd.DataFrame({"adj_close": prices["A"].to_numpy()}, index=dates)

    returns_df, _, _ = await _build_wide_returns(
        ["A"], {"A": 1.0}, str(dates[0].date()), str(dates[-1].date()), FakeData()
    )
    monthly = (1 + returns_df["A"]).groupby([returns_df.index.year, returns_df.index.month]).prod().iloc[0] - 1
    assert monthly == pytest.approx((1 + returns_df["A"].iloc[:22]).prod() - 1)


@pytest.mark.asyncio
async def test_a13_inverse_vol_uses_raw_low_volatility_estimate(monkeypatch):
    idx = pd.bdate_range("2024-01-01", periods=40)
    prices = pd.DataFrame(
        {
            "A": 100.0 * np.exp(np.cumsum(np.full(len(idx), 0.0001))),
            "B": 100.0 * np.exp(np.cumsum(np.linspace(-0.002, 0.002, len(idx)))),
        },
        index=idx,
    )
    engine = AnalyticsEngine()
    raw_vols = {"A": 0.01, "B": 0.10}

    async def fake_garch(series, _horizon):
        return {
            "raw_volatility_forecast": raw_vols[series.name],
            "volatility_forecast": 0.05,
        }

    monkeypatch.setattr(engine, "_garch_forecast", fake_garch)
    result = await engine.volatility_sizing(
        prices, {"A": 0.5, "B": 0.5}, model="GARCH", target_volatility=1.0
    )
    assert result["volatilities"]["A"] == pytest.approx(0.01)
    ratio = result["recommended_weights"]["A"] / result["recommended_weights"]["B"]
    assert ratio == pytest.approx(10.0, rel=1e-5)


@pytest.mark.asyncio
async def test_a13_zero_variance_excluded_leg_does_not_poison_sizing():
    idx = pd.bdate_range("2024-01-01", periods=80)
    rng = np.random.default_rng(42)
    prices = pd.DataFrame(
        {
            "FLAT": np.full(len(idx), 100.0),
            "VAR": 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, len(idx)))),
        },
        index=idx,
    )
    result = await AnalyticsEngine().volatility_sizing(
        prices, {"FLAT": 0.1, "VAR": 0.9}, model="EWMA", target_volatility=0.1
    )
    assert "FLAT" not in result["recommended_weights"]
    assert result["achieved_volatility"] == pytest.approx(0.1, rel=1e-9)
    assert result["current_volatility"] is not None
    assert np.isfinite(result["scale_factor"])
    assert result["cash_weight"] > 0.0


@pytest.mark.asyncio
async def test_a13_short_model_history_does_not_fabricate_volatility():
    idx = pd.bdate_range("2024-01-01", periods=2)
    prices = pd.DataFrame({"A": [100.0, 101.0], "B": [100.0, 102.0]}, index=idx)
    result = await AnalyticsEngine().volatility_sizing(
        prices, {"A": 0.5, "B": 0.5}, model="GARCH", target_volatility=0.1
    )
    assert result["recommended_weights"] == {}
    assert result["error"] == "Insufficient data for volatility sizing"
    assert "volatilities" not in result


@pytest.mark.asyncio
async def test_a13_short_ewma_sizing_requires_two_observations():
    idx = pd.bdate_range("2024-01-01", periods=2)
    prices = pd.DataFrame({"A": [100.0, 101.0], "B": [100.0, 102.0]}, index=idx)
    result = await AnalyticsEngine().volatility_sizing(
        prices, {"A": 0.5, "B": 0.5}, model="EWMA", target_volatility=0.1
    )
    assert result["recommended_weights"] == {}
    assert result["error"] == "Insufficient data for volatility sizing"
