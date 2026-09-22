"""Quant-services fix-pass regressions (backend-audit 04-quant-services).

One gate per nontrivial service fix; each went red against the audited code:
param-keyed coint caches, max_half_life count/list invariant, mem-cache TTL
eviction, non-deprecated UTC timestamps, backtest fail-fast input validation,
EVT no-fabrication (n_u<5 honesty / threshold guard / no 1.05 ES gap),
indicator calendar warmup for close_200_sma, MC element budget cap,
vol-cone empty windows, correlation flag/alert agreement, regime
n_components guard + pooled Parkinson, copula short-overlap raise,
honest high_tail_risk_pairs, benchmark start-span fetch, single
_as_matrices pass, SolverError->ValueError, and unknown date-index names.
"""

import inspect
import warnings
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import cvxpy as cp
import numpy as np
import pandas as pd
import pytest
from scipy import stats

from app.models.schemas import CointPairResult
from app.services import cointegration_service as coint
from app.services.backtest_service import run_walk_forward_backtest
from app.services.benchmark_service import BenchmarkService
from app.services.correlation_service import analyze_correlation_stability
from app.services.cointegration_service import (
    CointegrationService,
    _db_cache_keys,
    _mem_cache_key,
)
from app.services.indicators_service import IndicatorsService, _clean_dataframe
from app.services.monte_carlo_service import simulate_goal
from app.services.regime_service import classify
from app.services.tail_risk_service import TailRiskService
from app.services.volatility_service import DEFAULT_CONE_WINDOWS, VolatilityService


def _pair(a, b, pvalue=0.01):
    return CointPairResult(
        ticker_a=a,
        ticker_b=b,
        engle_granger_pvalue=pvalue,
        engle_granger_tstat=-3.5,
        is_cointegrated=True,
        hedge_ratio_beta=1.0,
        intercept_alpha=0.0,
        ou_half_life_days=10.0,
        ou_reversion_speed_theta=0.07,
        current_spread_zscore=0.5,
        johansen_cointegrated=True,
        last_price_a=100.0,
        last_price_b=200.0,
        signal="hold",
    )


class _FakeCache:
    """Minimal dict-backed get/set with real (ticker, metric) keying."""

    def __init__(self):
        self.store = {}
        self.set_calls = []

    async def get_cached_analytics(self, ticker, metric_name):
        hit = self.store.get((ticker, metric_name))
        if hit is None:
            return None
        return {"value": hit["metric_value"], "model_params": hit["model_params"]}

    async def set_cached_analytics(self, ticker, metric_name, metric_value, calculation_date, model_params=None):
        self.store[(ticker, metric_name)] = {"metric_value": metric_value, "model_params": model_params}
        self.set_calls.append((ticker, metric_name))


# ---------------------------------------------------------------------------
# P1: coint cache keys must include result-affecting query params
# ---------------------------------------------------------------------------

async def test_coint_cache_keys_include_query_params():
    coint._IN_MEMORY_COINT_CACHE.clear()

    assert _mem_cache_key("A", "B", "d", 0.05, False) != _mem_cache_key("A", "B", "d", 0.10, False)
    assert _mem_cache_key("A", "B", "d", 0.05, False) != _mem_cache_key("A", "B", "d", 0.05, True)
    assert _db_cache_keys("A", "B", "d", 0.05, False) != _db_cache_keys("A", "B", "d", 0.10, True)

    fake = _FakeCache()
    svc = CointegrationService(db_session=None, cache_service=fake)
    p = _pair("A", "B")
    await svc._set_cached_pair("A", "B", "2026-09-22", p,
                               p_value_threshold=0.05, include_spread_series=False)

    assert await svc._get_cached_pair("A", "B", "2026-09-22", 0.05, False) is not None
    # Old key omitted both params: a different-threshold request got the stale hit
    assert await svc._get_cached_pair("A", "B", "2026-09-22", 0.10, False) is None
    assert await svc._get_cached_pair("A", "B", "2026-09-22", 0.05, True) is None

    # Two param sets -> two durable DB rows, not one overwritten entry
    await svc._set_cached_pair("A", "B", "2026-09-22", p,
                               p_value_threshold=0.10, include_spread_series=True)
    assert len(fake.store) == 2

    coint._IN_MEMORY_COINT_CACHE.clear()


# ---------------------------------------------------------------------------
# P1: max_half_life must filter pairs, keeping count == listed cointegrated
# ---------------------------------------------------------------------------

async def test_max_half_life_filters_pairs_matching_count(monkeypatch):
    coint._IN_MEMORY_COINT_CACHE.clear()

    outcomes = {
        ("AAA.NS", "BBB.NS"): dict(is_coint=True, hl=10.0, pv=0.01),
        ("AAA.NS", "CCC.NS"): dict(is_coint=True, hl=None, pv=0.02),
        ("BBB.NS", "CCC.NS"): dict(is_coint=False, hl=None, pv=0.40),
    }

    def fake_analyze(ticker_a, ticker_b, series_a, series_b,
                     p_value_threshold=0.05, include_spread_series=False):
        o = outcomes[(ticker_a, ticker_b)]
        return CointPairResult(
            ticker_a=ticker_a,
            ticker_b=ticker_b,
            engle_granger_pvalue=o["pv"],
            engle_granger_tstat=-3.0,
            is_cointegrated=o["is_coint"],
            hedge_ratio_beta=1.0,
            intercept_alpha=0.0,
            ou_half_life_days=o["hl"],
            ou_reversion_speed_theta=None if o["hl"] is None else 0.05,
            current_spread_zscore=0.1,
            johansen_cointegrated=o["is_coint"],
            last_price_a=100.0,
            last_price_b=100.0,
            signal="NOT_COINTEGRATED" if not o["is_coint"] else "NEUTRAL",
        )

    monkeypatch.setattr(coint, "analyze_pair_cointegration", fake_analyze)
    idx = pd.bdate_range("2026-09-22", periods=40)
    price_data = {
        t: pd.Series(100.0 + i + np.arange(40) * 0.1, index=idx)
        for i, t in enumerate(("AAA.NS", "BBB.NS", "CCC.NS"))
    }
    svc = CointegrationService(db_session=None, cache_service=None)
    res = await svc.scan_pairs(price_data, p_value_threshold=0.05, max_half_life=60)

    listed_coint = [p for p in res.pairs if p.is_cointegrated]
    # Invariant: the count equals exactly the cointegrated pairs still listed
    assert res.cointegrated_pairs_count == len(listed_coint) == 1
    for p in listed_coint:
        assert p.ou_half_life_days is not None and p.ou_half_life_days <= 60
    # hl=None cointegrated pair filtered out; non-cointegrated pair retained
    assert not any(p.ticker_a == "AAA.NS" and p.ticker_b == "CCC.NS" for p in res.pairs)
    assert any(p.ticker_a == "BBB.NS" and not p.is_cointegrated for p in res.pairs)

    coint._IN_MEMORY_COINT_CACHE.clear()


# ---------------------------------------------------------------------------
# P2: in-memory cache TTL must be enforced on write, not only on hit
# ---------------------------------------------------------------------------

async def test_mem_cache_purges_expired_entries_on_write():
    coint._IN_MEMORY_COINT_CACHE.clear()
    stale_ts = coint._utcnow() - timedelta(hours=coint.CACHE_TTL_HOURS + 1)
    coint._IN_MEMORY_COINT_CACHE["stale_x"] = (stale_ts, {"ticker_a": "X"})

    svc = CointegrationService(db_session=None, cache_service=None)
    await svc._set_cached_pair("W.NS", "Z.NS", "2026-09-22", _pair("W.NS", "Z.NS"))

    assert "stale_x" not in coint._IN_MEMORY_COINT_CACHE
    assert len(coint._IN_MEMORY_COINT_CACHE) == 1  # fresh entry written
    coint._IN_MEMORY_COINT_CACHE.clear()


# ---------------------------------------------------------------------------
# P3: cache timestamps must not use deprecated datetime.utcnow()
# ---------------------------------------------------------------------------

async def test_cache_timestamps_use_non_deprecated_utc():
    coint._IN_MEMORY_COINT_CACHE.clear()
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        ts = coint._utcnow()
        assert ts.tzinfo is None  # naive, comparable with legacy cached rows

        svc = CointegrationService(db_session=None, cache_service=None)
        await svc._set_cached_pair("U.NS", "V.NS", "2026-09-22", _pair("U.NS", "V.NS"))
        assert await svc._get_cached_pair("U.NS", "V.NS", "2026-09-22") is not None
    coint._IN_MEMORY_COINT_CACHE.clear()


# ---------------------------------------------------------------------------
# P1/P2: backtest fail-fast input validation (strategy + windows)
# ---------------------------------------------------------------------------

def _bt_frame(rows=120, seed=9):
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        rng.normal(0.0005, 0.01, (rows, 2)),
        index=pd.bdate_range("2024-01-01", periods=rows),
        columns=["A", "B"],
    )


def test_backtest_unknown_strategy_raises_before_running():
    rets = _bt_frame()
    # Old code: optimize() raised per window and the broad except silently
    # ran equal-weight under the bogus strategy label.
    with pytest.raises(ValueError, match="Unknown strategy"):
        run_walk_forward_backtest(rets, strategy="bogus")

    # equal_weight stays a valid alias outside STRATEGIES
    res = run_walk_forward_backtest(
        rets, strategy="equal_weight", rebalance_freq_days=30, lookback_days=40,
    )
    assert res["strategy"] == "equal_weight"


def test_backtest_rejects_bad_windows():
    rets = _bt_frame()
    with pytest.raises(ValueError, match="lookback_days"):
        run_walk_forward_backtest(rets, strategy="equal_weight", lookback_days=5)
    with pytest.raises(ValueError, match="rebalance_freq_days"):
        run_walk_forward_backtest(rets, strategy="equal_weight", rebalance_freq_days=0)


# ---------------------------------------------------------------------------
# P1: EVT never fabricates GPD parameters / inflated tail numbers
# ---------------------------------------------------------------------------

def test_evt_insufficient_exceedances_reports_unfitted():
    # 60 observations -> 95% threshold yields < 5 exceedances
    r = pd.Series(np.random.default_rng(2).normal(0.0005, 0.02, 60))
    res = TailRiskService.calculate_evt_pot_var_es(
        r, confidence_level=0.99, threshold_quantile=0.95,
    )
    assert res["exceedances_count"] < 5
    assert res["model_fitted"] is False
    assert res["gpd_shape_xi"] is None
    assert res["gpd_scale_beta"] is None
    # Honest historical-only numbers: no *1.15 / *1.20 inflation
    assert res["evt_pot_var_99"] == res["historical_var_99"]
    assert res["evt_pot_es_99"] == res["historical_es_99"]
    # Fatness comes from empirical kurtosis only (never forced True)
    kurt = float(stats.kurtosis(r.values))
    assert res["is_fat_tailed"] == bool(kurt > 0.5)


def test_evt_rejects_threshold_at_or_above_confidence():
    r = pd.Series(np.random.default_rng(3).normal(0, 0.02, 100))
    # Old code fit GPD above the reported confidence and the threshold clamp
    # systematically overstated the "90% VaR".
    with pytest.raises(ValueError, match="threshold_quantile"):
        TailRiskService.calculate_evt_pot_var_es(
            r, confidence_level=0.90, threshold_quantile=0.98,
        )
    # Valid combo unchanged
    ok = TailRiskService.calculate_evt_pot_var_es(
        r, confidence_level=0.99, threshold_quantile=0.95,
    )
    assert ok["total_observations"] == 100


def test_evt_es_clamp_has_no_cosmetic_five_pct_gap():
    src = inspect.getsource(TailRiskService.calculate_evt_pot_var_es)
    # Old: es_evt_loss = max(es_evt_loss, var_evt_loss * 1.05) forced a
    # >=5% VaR->ES gap beyond the real ES >= VaR bound.
    assert "* 1.05" not in src
    assert "max(es_evt_loss, var_evt_loss)" in src


# ---------------------------------------------------------------------------
# P1: indicator warmup must fetch enough calendar days for close_200_sma
# ---------------------------------------------------------------------------

def _ohlcv_frame(days=400, end="2026-08-20", seed=3):
    dates = pd.date_range(end=end, periods=days, freq="B")
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, days)))
    return pd.DataFrame({
        "Date": dates,
        "Open": close * 0.995,
        "High": close * 1.008,
        "Low": close * 0.992,
        "Close": close,
        "Volume": rng.integers(1_000, 50_000, days).astype(float),
    })


async def test_indicator_warmup_yields_200sma_at_default_lookback():
    frame = _ohlcv_frame(days=400, end="2026-08-20")
    seen = []

    async def fake_fetch(ticker, start, end):
        seen.append((start, end))
        # Honor the requested window like the real fetcher does
        return frame[frame["Date"] >= pd.Timestamp(start)]

    seam = Mock()
    seam.fetch_historical_data = AsyncMock(side_effect=fake_fetch)
    with patch("app.services.indicators_service.DataService", return_value=seam):
        svc = IndicatorsService(db_session=Mock())
        out = await svc.compute_window("TEST.NS", lookback_days=90, end_date="2026-08-20")

    start_arg, end_arg = seen[0]
    span = (pd.Timestamp(end_arg) - pd.Timestamp(start_arg)).days
    # Old: int(90 * 1.6) + 120 = 264 calendar days (~187 trading rows) < 200
    assert span >= 300, f"calendar warmup {span}d cannot cover the 200-row SMA"
    assert out["records"][-1]["close_200_sma"] is not None


# ---------------------------------------------------------------------------
# P1: Monte Carlo (num_paths x steps) element budget
# ---------------------------------------------------------------------------

def test_mc_caps_paths_by_element_budget(monkeypatch):
    from app.services import monte_carlo_service as mc

    captured = []

    def fake_gbm(mu_annual, sigma_annual, initial_value, horizon_years, num_paths, rng):
        captured.append(num_paths)
        steps = int(round(float(horizon_years) * mc.TRADING_DAYS))
        return np.full((1, steps + 1), float(initial_value))

    monkeypatch.setattr(mc, "_simulate_gbm", fake_gbm)
    r = pd.Series(np.random.default_rng(10).normal(0.0004, 0.01, 300))

    out = simulate_goal(r, 100_000, 150_000, 40, method="gbm", num_paths=20_000, seed=1)
    steps = int(round(40 * 252))
    expected = max(100, min(20_000, mc.MAX_PATH_ELEMENTS // steps))
    assert captured[0] == expected
    assert captured[0] * steps <= mc.MAX_PATH_ELEMENTS
    assert out["num_paths"] == expected

    # Requests within the budget pass through unchanged
    simulate_goal(r, 100_000, 150_000, 1, method="gbm", num_paths=500, seed=1)
    assert captured[-1] == 500


# ---------------------------------------------------------------------------
# P2: vol-cone windows=[] must fall back to defaults, not IndexError
# ---------------------------------------------------------------------------

def test_vol_cone_empty_windows_falls_back_to_defaults():
    s = pd.Series(np.random.default_rng(7).normal(0, 0.015, 300))
    cone = VolatilityService.calculate_volatility_cone(s, windows=[])
    assert len(cone["windows"]) == len(DEFAULT_CONE_WINDOWS)


# ---------------------------------------------------------------------------
# P2: correlation regime-break flag and CRITICAL alert must agree
# ---------------------------------------------------------------------------

def test_correlation_flat_series_flag_agrees_with_alert(monkeypatch):
    # Flat series -> current == p90 exactly. Old code: flag used `>` (False)
    # while the alert used `>=` (CRITICAL) — payload contradicted itself.
    # Patch the rolling series so equality is bit-exact (real rolling corr of
    # identical columns has sub-ulp float noise).
    idx = pd.bdate_range("2024-01-01", periods=120)
    flat = pd.Series(np.full(120, 0.9), index=idx)
    monkeypatch.setattr(
        "app.services.correlation_service.compute_rolling_avg_correlation",
        lambda *args, **kwargs: flat,
    )
    res = analyze_correlation_stability(
        pd.DataFrame({"A": [0.01] * 120, "B": [0.01] * 120}, index=idx),
        window_days=30,
    )
    assert res.is_regime_break is True
    assert res.alert_level == "CRITICAL"
    assert res.is_regime_break == (res.alert_level == "CRITICAL")


# ---------------------------------------------------------------------------
# P2: benchmark get_returns must derive the fetch window from start
# ---------------------------------------------------------------------------

async def test_benchmark_get_returns_derives_fetch_span_from_start(monkeypatch):
    svc = BenchmarkService(db_session=Mock())
    seen = []
    dates = pd.date_range(end=pd.Timestamp.now().normalize(), periods=30)
    frame = pd.DataFrame({"date": dates, "adj_close": np.linspace(100.0, 110.0, 30)})

    async def fake_ensure(days=756):
        seen.append(days)
        return frame

    monkeypatch.setattr(svc, "ensure_history", fake_ensure)
    start = (pd.Timestamp.now().normalize() - pd.Timedelta(days=1000)).strftime("%Y-%m-%d")
    await svc.get_returns(start=start)  # days left at its 756 default

    # Old code always fetched `days` (756) and silently truncated start
    assert seen and seen[0] >= 1000


# ---------------------------------------------------------------------------
# P3: regime n_components validated up front
# ---------------------------------------------------------------------------

def test_regime_n_components_rejects_non_three():
    # Sticky init matrices and crisis/calm/bull labels are 3-state only;
    # hmmlearn used to fail deep inside fit with an opaque shape error.
    with pytest.raises(ValueError, match="n_components"):
        classify(None, n_components=2)


# ---------------------------------------------------------------------------
# P3: Parkinson variance pooled before annualizing (Jensen-correct)
# ---------------------------------------------------------------------------

def test_parkinson_vol_pools_before_annualizing():
    rng = np.random.default_rng(2)
    n = 300
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.010, n)))
    gap = np.where(np.arange(n) % 2 == 0, 1.02, 1.06)  # High/Low ratio alternates
    df = pd.DataFrame({
        "date": dates,
        "open": close,
        "close": close,
        "high": close * np.sqrt(gap),
        "low": close / np.sqrt(gap),
        "volume": rng.integers(1000, 9000, n).astype(float),
    })

    res = classify(df)
    assert res is not None

    log_hl = np.log(gap)
    expected = float(np.sqrt(np.mean(log_hl[-10:] ** 2) / (4.0 * np.log(2.0))) * np.sqrt(252.0))
    got = res["realtime_parkinson_vol"]
    assert got == pytest.approx(expected, abs=1e-4)

    # Old formula annualized per observation first, then averaged the sigmas
    # (mean-of-sqrt) — strictly smaller by Jensen's inequality.
    old = float(np.mean(np.sqrt(log_hl[-10:] ** 2 / (4.0 * np.log(2.0)))) * np.sqrt(252.0))
    assert abs(got - old) > 1e-3


# ---------------------------------------------------------------------------
# P3: copula short-overlap raises instead of returning a fabricated triple
# ---------------------------------------------------------------------------

def test_tail_dependence_raises_on_short_overlap():
    a = pd.Series(np.random.default_rng(4).normal(0, 0.01, 5))
    b = pd.Series(np.random.default_rng(5).normal(0, 0.01, 5))
    # Old code returned (0.0, 0.0, 4.0) — a fabricated "no tail dependence"
    # triple with no insufficient-data signal.
    with pytest.raises(ValueError, match="Insufficient overlapping"):
        TailRiskService.calculate_bivariate_tail_dependence(a, b)


# ---------------------------------------------------------------------------
# P3: high_tail_risk_pairs is never backfilled with low-risk pairs
# ---------------------------------------------------------------------------

def test_high_tail_risk_pairs_stays_empty_when_none_qualify():
    rng = np.random.default_rng(6)
    n = 200
    a = rng.normal(0.0005, 0.012, n)
    b = -0.9 * a + rng.normal(0.0, 0.008, n)  # anti-dependent: lambda_L ~ 0
    df = pd.DataFrame({"A": a, "B": b})
    res = TailRiskService.calculate_tail_dependence_matrix(df)
    # Old code backfilled pairs_list[:5], so the section could never be empty
    assert res["high_tail_risk_pairs"] == []
    assert res["matrix"][0][1] < 0.20


# ---------------------------------------------------------------------------
# P3: optimize computes moments once (no second _as_matrices pass)
# ---------------------------------------------------------------------------

def test_optimize_computes_moments_once(monkeypatch):
    import app.services.optimization_service as opt

    calls = []
    real = opt._as_matrices

    def spy(returns):
        calls.append(returns.shape)
        return real(returns)

    monkeypatch.setattr(opt, "_as_matrices", spy)
    rets = pd.DataFrame(
        np.random.default_rng(8).normal(0.0005, 0.01, (250, 3)),
        columns=list("ABC"),
    )
    out = opt.optimize(rets, "min_vol")
    assert abs(sum(out["weights"].values()) - 1.0) < 1e-4
    assert len(calls) == 1  # old code ran diagnostics on a second full pass


# ---------------------------------------------------------------------------
# P3: cvxpy SolverError maps to ValueError (API 400, not 500)
# ---------------------------------------------------------------------------

def test_solver_error_becomes_value_error(monkeypatch):
    from app.services import optimization_service as opt

    def boom(*args, **kwargs):
        raise cp.error.SolverError("CLARABEL failed")

    monkeypatch.setattr(cp.Problem, "solve", boom)
    # SolverError is not a ValueError subclass; old code let it propagate.
    with pytest.raises(ValueError, match="solver failed"):
        opt._min_vol(np.eye(3) * 0.04)


# ---------------------------------------------------------------------------
# P3: unknown date-index names must not KeyError downstream
# ---------------------------------------------------------------------------

def test_clean_dataframe_tolerates_unknown_index_name():
    dates = pd.date_range("2024-01-01", periods=30, freq="B")
    rng = np.random.default_rng(12)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, 30)))
    raw = pd.DataFrame({
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": rng.integers(1000, 9000, 30).astype(float),
    }, index=dates)
    raw.index.name = "timestamp"  # not in ("date", "index", "Datetime")
    out = _clean_dataframe(raw)
    assert "Date" in out.columns
    assert len(out) == 30
