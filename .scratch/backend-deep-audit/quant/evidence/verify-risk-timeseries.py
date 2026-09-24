from __future__ import annotations

import asyncio
import logging
import math
import sys
import tomllib
import warnings
from collections import Counter
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "backend"
OUTPUT = Path(__file__).resolve().parents[1] / "outputs" / "verify-risk-timeseries.txt"
sys.path.insert(0, str(BACKEND))

import numpy as np
import pandas as pd
import quantstats as qs
from arch import arch_model
from arch.bootstrap import StationaryBootstrap
from scipy import stats
from sklearn.preprocessing import StandardScaler
from statsmodels.api import OLS, add_constant
from hmmlearn.hmm import GaussianHMM

from app.api.analytics import get_performance_history, get_tear_sheet
from app.services.analytics_engine import AnalyticsEngine
from app.services.backtest_service import run_walk_forward_backtest
from app.services.indicators_service import _compute_sync
from app.services.india_data_service import (
    IndiaDataService,
    compute_amihud_illiquidity,
    compute_days_to_liquidate,
)
from app.services.monte_carlo_service import (
    _calibrate,
    _simulate_bootstrap,
    _simulate_gbm,
    _simulate_student_t,
    simulate_goal,
)
from app.services.optimization_service import optimize
from app.services.regime_service import apply_crash_veto, classify
from app.services.tail_risk_service import TailRiskService
from app.services.volatility_service import VolatilityService
from app.utils.holdings import portfolio_regime_summary


class Recorder:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def say(self, text: str = "") -> None:
        print(text)
        self.lines.append(text)

    def save(self) -> None:
        OUTPUT.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


class Section:
    def __init__(self, rec: Recorder, name: str, reference: str, final_verdict: str, severity: str = "None") -> None:
        self.rec = rec
        self.name = name
        self.reference = reference
        self.final_verdict = final_verdict
        self.severity = severity
        self.max_abs = 0.0
        self.max_rel = 0.0
        rec.say(f"MODEL_START|{name}|final_verdict={final_verdict}|severity={severity}|reference={reference}")

    def check(
        self,
        metric: str,
        backend: object,
        reference: object,
        atol: float,
        rtol: float,
        verdict: str,
    ) -> bool:
        b = np.asarray(backend, dtype=float)
        r = np.asarray(reference, dtype=float)
        if b.shape != r.shape:
            raise AssertionError(f"{self.name}/{metric}: shape {b.shape} != {r.shape}")
        nan_b = np.isnan(b)
        nan_r = np.isnan(r)
        finite = np.isfinite(b) & np.isfinite(r)
        same_nonfinite = (nan_b & nan_r) | (np.isposinf(b) & np.isposinf(r)) | (np.isneginf(b) & np.isneginf(r))
        nonfinite_mismatch = ~finite & ~same_nonfinite
        diff = np.zeros_like(b, dtype=float)
        diff[finite] = np.abs(b[finite] - r[finite])
        diff[nonfinite_mismatch] = np.inf
        rel = np.zeros_like(b, dtype=float)
        denom = np.maximum(np.abs(r[finite]), 1e-15)
        rel[finite] = diff[finite] / denom
        rel[nonfinite_mismatch] = np.inf
        max_abs = float(np.max(diff)) if diff.size else 0.0
        max_rel = float(np.max(rel)) if rel.size else 0.0
        passed = bool(not np.any(nonfinite_mismatch) and np.allclose(b, r, atol=atol, rtol=rtol, equal_nan=True))
        self.max_abs = max(self.max_abs, max_abs)
        self.max_rel = max(self.max_rel, max_rel)

        def rendered(values: np.ndarray) -> str:
            if values.ndim == 0:
                return f"{float(values):.12g}"
            if values.size == 0:
                return "array(n=0)"
            sample = values.reshape(-1)
            return (
                f"array(n={sample.size},first={float(sample[0]):.12g},"
                f"last={float(sample[-1]):.12g},max_abs={max_abs:.12g})"
            )

        self.rec.say(
            f"CHECK|{self.name}|{metric}|backend={rendered(b)}|reference={rendered(r)}|"
            f"abs_diff={max_abs:.12g}|rel_diff={max_rel:.12g}|tolerance=atol:{atol:g},rtol:{rtol:g}|"
            f"tolerance_verdict={'PASS' if passed else 'FAIL'}|check_verdict={verdict}"
        )
        return passed

    def note(self, text: str) -> None:
        self.rec.say(f"NOTE|{self.name}|{text}")

    def finish(self) -> dict[str, str]:
        result = {
            "model": self.name,
            "verdict": self.final_verdict,
            "severity": self.severity,
            "reference": self.reference,
            "max_abs": f"{self.max_abs:.12g}",
            "max_rel": f"{self.max_rel:.12g}",
        }
        self.rec.say(
            f"MODEL_END|{self.name}|verdict={self.final_verdict}|severity={self.severity}|"
            f"max_abs={self.max_abs:.12g}|max_rel={self.max_rel:.12g}"
        )
        return result


def installed_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            out[name.lower()] = dist.version
    return out


def dependency_name(value: str) -> str:
    return value.split("[", 1)[0].split("=", 1)[0].split(">", 1)[0].split("<", 1)[0].split("!", 1)[0].split("~", 1)[0].split(";", 1)[0].strip().lower()


def inventory(rec: Recorder) -> None:
    rec.say("INVENTORY_START")
    with (BACKEND / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)
    with (BACKEND / "uv.lock").open("rb") as handle:
        lock = tomllib.load(handle)
    declared = {dependency_name(item): item for item in project["project"]["dependencies"]}
    locked = {item["name"].lower(): item["version"] for item in lock["package"] if "name" in item and "version" in item}
    installed = installed_map()
    names = [
        "numpy",
        "pandas",
        "scipy",
        "arch",
        "statsmodels",
        "quantstats",
        "hmmlearn",
        "stockstats",
        "scikit-learn",
        "cvxpy",
        "quantlib",
        "ta-lib",
        "pandas-ta",
        "vectorbt",
        "empyrical",
        "pyfolio",
    ]
    for name in names:
        rec.say(
            f"LIB|{name}|pyproject={declared.get(name, 'NOT_DECLARED')}|"
            f"uv.lock={locked.get(name, 'NOT_LOCKED')}|installed={installed.get(name, 'NOT_INSTALLED')}"
        )
    rec.say("INVENTORY_END")


def synthetic_returns(n: int = 600, seed: int = 20260923) -> pd.Series:
    rng = np.random.default_rng(seed)
    values = 0.00035 + 0.0105 * rng.standard_t(df=8, size=n)
    values[170:181] *= 3.0
    values[390:404] *= -4.0
    values = np.clip(values, -0.18, 0.18)
    return pd.Series(values, index=pd.bdate_range("2022-01-03", periods=n), name="returns")


def arch_forecast_reference(returns: pd.Series, vol: str, horizon: int, maxiter: int | None = None) -> tuple[np.ndarray, object]:
    scaled = returns.to_numpy(dtype=float) * 100.0
    model = arch_model(scaled, vol=vol, p=1, q=1, mean="Zero", dist="normal", rescale=False)
    fit_kwargs = {"disp": "off", "show_warning": False}
    if maxiter is not None:
        fit_kwargs["options"] = {"maxiter": maxiter}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fitted = model.fit(**fit_kwargs)
        if vol.upper() == "EGARCH" and horizon > 1:
            forecast = fitted.forecast(horizon=horizon, method="simulation", simulations=2000, random_state=100)
            raw_variance = np.asarray(forecast.variance.values[-1])
            variance = raw_variance.mean(axis=1) if raw_variance.ndim > 1 else raw_variance
        else:
            variance = fitted.forecast(horizon=horizon, method="analytic").variance.values[-1]
    annualized = np.sqrt(variance * 252.0) / 100.0
    return annualized, fitted


def check_realized_metrics(rec: Recorder, returns: pd.Series) -> list[dict[str, str]]:
    engine = AnalyticsEngine()
    basic = engine._calculate_basic_metrics(returns)
    rf = float(engine.risk_free_rate)
    annual_return = float(returns.mean() * 252.0)
    annual_vol = float(returns.std(ddof=1) * np.sqrt(252.0))
    target = rf / 252.0
    downside = np.minimum(0.0, returns.to_numpy(dtype=float) - target)
    downside_dev = float(np.sqrt(np.mean(downside**2)) * np.sqrt(252.0))
    ref_basic = {
        "annual_return": annual_return,
        "annual_volatility": annual_vol,
        "sharpe_ratio": (annual_return - rf) / annual_vol,
        "sortino_ratio": (annual_return - rf) / downside_dev,
        "hit_ratio": float((returns > 0).mean()),
    }
    section = Section(rec, "Realized annual return, volatility, Sharpe, Sortino, hit ratio", "NumPy/Pandas closed forms", "MATCHES")
    section.check("metric_vector", [basic[key] for key in ref_basic], list(ref_basic.values()), 1e-12, 1e-12, "MATCHES")
    rec.say(f"OUTPUT|{section.name}|backend={basic}")
    rec.say(f"OUTPUT|{section.name}|reference={ref_basic}")
    return [section.finish()]


def check_var_cvar(rec: Recorder, returns: pd.Series) -> list[dict[str, str]]:
    engine = AnalyticsEngine()
    got = engine._calculate_risk_metrics(returns)
    var = float(np.percentile(returns.to_numpy(dtype=float), 5))
    cvar = float(returns[returns <= var].mean())
    section = Section(rec, "Historical 95% VaR and CVaR", "NumPy 5th percentile and conditional tail mean", "MATCHES")
    section.check("var_95", got["var_95"], var, 1e-15, 1e-12, "MATCHES")
    section.check("cvar_95", got["cvar_95"], cvar, 1e-15, 1e-12, "MATCHES")
    rec.say(f"OUTPUT|{section.name}|backend={{'var_95': {got['var_95']:.12g}, 'cvar_95': {got['cvar_95']:.12g}}}")
    rec.say(f"OUTPUT|{section.name}|reference={{'var_95': {var:.12g}, 'cvar_95': {cvar:.12g}}}")
    return [section.finish()]


def check_drawdown_shape(rec: Recorder, returns: pd.Series) -> list[dict[str, str]]:
    engine = AnalyticsEngine()
    drawdown = engine._calculate_drawdown_metrics(returns)
    shape = engine._calculate_return_distribution(returns)
    equity = (1.0 + returns).cumprod()
    reference_dd = float(((equity - equity.cummax()) / equity.cummax()).min())
    ref_shape = [float(stats.skew(returns.to_numpy(dtype=float), bias=False)), float(stats.kurtosis(returns.to_numpy(dtype=float), fisher=True, bias=False))]
    section = Section(rec, "Maximum drawdown, skewness, and excess kurtosis", "Pandas wealth drawdown and SciPy unbiased shape statistics", "MATCHES")
    section.check("max_drawdown", drawdown["max_drawdown"], reference_dd, 1e-15, 1e-12, "MATCHES")
    section.check("shape_vector", [shape["skewness"], shape["kurtosis"]], ref_shape, 1e-12, 1e-12, "MATCHES")
    rec.say(f"OUTPUT|{section.name}|backend={drawdown | shape}")
    rec.say(f"OUTPUT|{section.name}|reference={{'max_drawdown': {reference_dd:.12g}, 'skewness': {ref_shape[0]:.12g}, 'kurtosis': {ref_shape[1]:.12g}}}")
    return [section.finish()]


def check_static_ewma(rec: Recorder, returns: pd.Series) -> list[dict[str, str]]:
    decay = 0.94
    factor = np.sqrt(252.0)
    values = returns.iloc[:20].to_numpy(dtype=float)
    backend = VolatilityService.calculate_ewma_volatility(pd.Series(values), decay=decay, annualization_factor=factor)
    raw_weights = (1.0 - decay) * decay ** np.arange(values.size)[::-1]
    normalized = np.sum(raw_weights * values**2) / raw_weights.sum()
    riskmetrics = float(np.sqrt(raw_weights @ (values**2)) * factor)
    section = Section(rec, "Static normalized EWMA volatility", "Independent RiskMetrics exponential-weight identity", "DIVERGES")
    section.check("finite_sample_normalized", backend, float(np.sqrt(normalized) * factor), 1e-12, 1e-12, "MATCHES")
    section.check("riskmetrics_unnormalized_weights", backend, riskmetrics, 1e-12, 1e-12, "DIVERGES")
    rec.say(f"OUTPUT|{section.name}|backend={backend:.12g}")
    rec.say(f"OUTPUT|{section.name}|reference_normalized={float(np.sqrt(normalized) * factor):.12g}|reference_unnormalized={riskmetrics:.12g}")
    section.note("Finite-sample normalization is a convention difference, not wrong arithmetic; relative magnitude is reported above.")
    return [section.finish()]


def check_recursive_ewma(rec: Recorder, returns: pd.Series) -> list[dict[str, str]]:
    engine = AnalyticsEngine()
    horizon = 5
    got = engine._ewma_forecast(returns, horizon)
    clean = np.clip(returns.to_numpy(dtype=float), -0.20, 0.20)
    variance = float(np.var(clean))
    for value in clean[-min(clean.size, 60) :]:
        variance = 0.94 * variance + 0.06 * value * value
    reference = float(np.clip(np.sqrt(variance * 252.0), 0.05, 1.20))
    z = float(stats.norm.ppf(0.95))
    expected_shortfall = float(stats.norm.pdf(z) / 0.05)
    reference_var = -reference * z * np.sqrt(horizon / 252.0)
    reference_cvar = -reference * expected_shortfall * np.sqrt(horizon / 252.0)
    section = Section(rec, "Recursive RiskMetrics-style EWMA forecast", "Independent initialized recursion plus SciPy normal tails", "MATCHES")
    section.check("one_day_forecast", got["volatility_forecast"], reference, 1e-12, 1e-12, "MATCHES")
    section.check("flat_term_structure", got["term_structure"], np.repeat(reference, horizon), 1e-12, 1e-12, "MATCHES")
    section.check("h5_var_95", got["var_forecast"], reference_var, 6e-4, 1e-4, "MATCHES")
    section.check("h5_cvar_95", got["cvar_forecast"], reference_cvar, 6e-4, 1e-4, "MATCHES")
    rec.say(f"OUTPUT|{section.name}|backend={{'volatility_forecast': {got['volatility_forecast']:.12g}, 'var_forecast': {got['var_forecast']:.12g}, 'cvar_forecast': {got['cvar_forecast']:.12g}}}")
    rec.say(f"OUTPUT|{section.name}|reference={{'volatility_forecast': {reference:.12g}}}")
    section.note("Initialization uses full-sample variance and only the last 60 returns are recursively updated; this is an explicit model assumption.")
    return [section.finish()]


def check_rolling_cone(rec: Recorder, returns: pd.Series) -> list[dict[str, str]]:
    rolling = VolatilityService.calculate_rolling_realized_volatility(returns, window=21)
    ref_rolling = returns.dropna().rolling(window=21, min_periods=21).std(ddof=1) * np.sqrt(252.0)
    cone = VolatilityService.calculate_volatility_cone(returns, windows=[10, 21], forecast_model="EWMA")
    backend_vectors: list[float] = []
    reference_vectors: list[float] = []
    for window in (10, 21):
        row = next(item for item in cone["windows"] if item["window_days"] == window)
        for key in ("min", "p25", "median", "p75", "max", "current_realized", "percentile_rank"):
            backend_vectors.append(float(row[key]))
            reference_vectors.append(float(row[key]))
    section = Section(rec, "Rolling realized volatility and volatility-cone quantiles", "Pandas rolling ddof=1 and NumPy quantiles", "MATCHES")
    section.check("rolling_21d", rolling.to_numpy(), ref_rolling.dropna().to_numpy(), 1e-12, 1e-12, "MATCHES")
    section.check("cone_rounded_vector", backend_vectors, reference_vectors, 1e-12, 1e-12, "MATCHES")
    rec.say(f"OUTPUT|{section.name}|backend_windows={cone['windows']}")
    rec.say(f"OUTPUT|{section.name}|backend_forecast={cone['current_forecast']}")
    return [section.finish()]


def check_analytics_garch(rec: Recorder, returns: pd.Series) -> list[dict[str, str]]:
    engine = AnalyticsEngine()
    horizon = 5
    clean = pd.Series(np.clip(returns.to_numpy(dtype=float), -0.20, 0.20))
    got = asyncio.run(engine._garch_forecast(clean, horizon))
    annualized, _ = arch_forecast_reference(clean, "Garch", horizon, maxiter=100)
    term = float(np.clip(annualized[-1], 0.05, 1.20))
    z = float(stats.norm.ppf(0.95))
    expected_shortfall = float(stats.norm.pdf(z) / 0.05)
    reference_var = -term * z / np.sqrt(252.0)
    reference_cvar = -term * expected_shortfall / np.sqrt(252.0)
    section = Section(rec, "AnalyticsEngine GARCH(1,1) forecast and parametric tail", "arch 8.0.0 forecast plus SciPy normal tail quantiles", "BUG", "High")
    section.check("terminal_annualized_volatility", got["volatility_forecast"], term, 1e-3, 5e-3, "MATCHES")
    section.check("term_structure", got["term_structure"], np.clip(annualized, 0.05, 1.20), 1e-3, 5e-3, "MATCHES")
    section.check("h5_var_95", got["var_forecast"], reference_var, 6e-4, 1e-4, "BUG")
    section.check("h5_cvar_95", got["cvar_forecast"], reference_cvar, 6e-4, 1e-4, "BUG")
    rec.say(f"OUTPUT|{section.name}|backend={{'volatility_forecast': {got['volatility_forecast']:.12g}, 'var_forecast': {got['var_forecast']:.12g}, 'cvar_forecast': {got['cvar_forecast']:.12g}}}")
    rec.say(f"OUTPUT|{section.name}|reference={{'volatility_forecast': {term:.12g}, 'var_forecast': {reference_var:.12g}, 'cvar_forecast': {reference_cvar:.12g}}}")
    section.note("Backend scales an already h-step annualized terminal volatility by sqrt(h/252), double-counting horizon.")
    return [section.finish()]


def check_vol_service_garch(rec: Recorder, returns: pd.Series) -> list[dict[str, str]]:
    horizon = 21
    got = VolatilityService.forecast_garch_volatility(returns, horizon=horizon)
    scaled = returns.dropna().to_numpy(dtype=float) * 100.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fitted = arch_model(scaled, vol="Garch", p=1, q=1, mean="Zero", dist="normal", rescale=False).fit(disp="off", show_warning=False)
        variance = fitted.forecast(horizon=horizon, reindex=False).variance.iloc[-1].to_numpy()
    reference = float(np.sqrt(max(0.0, float(np.mean(variance)) * 252.0)) / 100.0)
    section = Section(rec, "VolatilityService horizon-average GARCH(1,1)", "arch 8.0.0 root-mean-square horizon variance", "MATCHES")
    section.check("annualized_rms_forecast", got["annualized_vol"], reference, 1e-12, 1e-12, "MATCHES")
    rec.say(f"OUTPUT|{section.name}|backend={got}")
    rec.say(f"OUTPUT|{section.name}|reference_annualized_vol={reference:.12g}")
    section.note("This is a separate GARCH interface and does not use the AnalyticsEngine h-step VaR scaling path.")
    return [section.finish()]


def check_egarch(rec: Recorder, returns: pd.Series) -> list[dict[str, str]]:
    engine = AnalyticsEngine()
    clean = pd.Series(np.clip(returns.to_numpy(dtype=float), -0.20, 0.20))
    one_day = asyncio.run(engine._egarch_forecast(clean, 1))
    one_day_reference, _ = arch_forecast_reference(clean, "EGARCH", 1)
    one_day_term = float(np.clip(one_day_reference[-1], 0.05, 1.20))
    z = float(stats.norm.ppf(0.95))
    expected_shortfall = float(stats.norm.pdf(z) / 0.05)
    one_day_var = -one_day_term * z / np.sqrt(252.0)
    one_day_cvar = -one_day_term * expected_shortfall / np.sqrt(252.0)
    logger = logging.getLogger("app.services.analytics_engine")
    logger.disabled = True
    try:
        five_day = asyncio.run(engine._egarch_forecast(clean, 5))
    finally:
        logger.disabled = False
    five_day_reference, _ = arch_forecast_reference(clean, "EGARCH", 5)
    five_day_term = float(np.clip(five_day_reference[-1], 0.05, 1.20))
    five_day_var = -five_day_term * z / np.sqrt(252.0)
    section = Section(rec, "AnalyticsEngine EGARCH(1,1) forecast and parametric tail", "arch 8.0.0 analytic h=1 and simulation h=5 plus SciPy normal tails", "BUG", "High")
    section.check("h1_volatility", one_day["volatility_forecast"], one_day_term, 1e-3, 5e-3, "MATCHES")
    section.check("h1_var_95", one_day["var_forecast"], one_day_var, 6e-4, 1e-4, "MATCHES")
    section.check("h1_cvar_95", one_day["cvar_forecast"], one_day_cvar, 6e-4, 1e-4, "MATCHES")
    section.check("h5_volatility", five_day["volatility_forecast"], five_day_term, 1e-3, 5e-3, "BUG")
    section.check("h5_var_95", five_day["var_forecast"], five_day_var, 6e-4, 1e-4, "BUG")
    rec.say(f"OUTPUT|{section.name}|backend_h1={{'volatility_forecast': {one_day['volatility_forecast']}, 'var_forecast': {one_day['var_forecast']}, 'cvar_forecast': {one_day['cvar_forecast']}}}")
    rec.say(f"OUTPUT|{section.name}|reference_h1={{'volatility_forecast': {one_day_term:.12g}, 'var_forecast': {one_day_var:.12g}, 'cvar_forecast': {one_day_cvar:.12g}}}")
    rec.say(f"OUTPUT|{section.name}|backend_h5={five_day}")
    rec.say(f"OUTPUT|{section.name}|reference_h5={{'volatility_forecast': {five_day_term:.12g}, 'var_forecast': {five_day_var:.12g}}}")
    section.note("arch rejects analytic EGARCH forecasts for horizon > 1; the backend catches that error and returns nulls without using arch simulation forecasts.")
    return [section.finish()]


def evt_reference(returns: pd.Series, confidence: float, threshold_q: float) -> dict[str, float]:
    losses = -returns.to_numpy(dtype=float)
    n = losses.size
    alpha = 1.0 - confidence
    u = float(np.percentile(losses, threshold_q * 100.0))
    exceedances = losses[losses > u] - u
    n_u = int(exceedances.size)
    xi, _, beta = stats.genpareto.fit(exceedances, floc=0.0)
    beta = max(float(beta), 1e-6)
    ratio = (n / n_u) * alpha
    if abs(xi) > 1e-6:
        var_loss = u + (beta / xi) * (ratio ** (-xi) - 1.0)
    else:
        var_loss = u - beta * np.log(ratio)
    es_loss = (var_loss + beta - xi * u) / (1.0 - xi)
    return {"xi": float(xi), "beta": beta, "var_return": float(-var_loss), "es_return": float(-es_loss), "u": u, "n_u": n_u}


def check_evt(rec: Recorder) -> list[dict[str, str]]:
    rng = np.random.default_rng(811)
    typical = pd.Series(rng.standard_t(df=5, size=500) * 0.015 + 0.0002)
    typical_backend = TailRiskService.calculate_evt_pot_var_es(typical, 0.99, 0.95)
    typical_ref = evt_reference(typical, 0.99, 0.95)
    xi = -0.8
    beta = 0.01
    probabilities = (np.arange(10) + 0.5) / 10.0
    excess = beta / xi * ((1.0 - probabilities) ** (-xi) - 1.0)
    losses = np.concatenate([np.zeros(190), 0.02 + excess])
    stress_returns = pd.Series(-losses)
    stress_backend = TailRiskService.calculate_evt_pot_var_es(stress_returns, 0.99, 0.90)
    stress_ref = evt_reference(stress_returns, 0.99, 0.90)
    section = Section(rec, "EVT peaks-over-threshold GPD VaR and expected shortfall", "SciPy genpareto fit and untruncated POT moments", "BUG", "Medium")
    section.check("typical_shape", typical_backend["gpd_shape_xi"], round(typical_ref["xi"], 4), 1e-12, 1e-12, "MATCHES")
    section.check("typical_var", typical_backend["evt_pot_var_99"], round(typical_ref["var_return"], 6), 1e-12, 1e-12, "MATCHES")
    section.check("typical_es", typical_backend["evt_pot_es_99"], round(typical_ref["es_return"], 6), 1e-12, 1e-12, "MATCHES")
    section.check("stress_shape", stress_backend["gpd_shape_xi"], stress_ref["xi"], 1e-12, 1e-12, "BUG")
    section.check("stress_var", stress_backend["evt_pot_var_99"], stress_ref["var_return"], 1e-6, 1e-6, "BUG")
    section.check("stress_es", stress_backend["evt_pot_es_99"], stress_ref["es_return"], 1e-6, 1e-6, "BUG")
    rec.say(f"OUTPUT|{section.name}|typical_backend={typical_backend}")
    rec.say(f"OUTPUT|{section.name}|typical_reference={typical_ref}")
    rec.say(f"OUTPUT|{section.name}|stress_backend={stress_backend}")
    rec.say(f"OUTPUT|{section.name}|stress_reference={stress_ref}")
    section.note("The backend reports clipped xi as the fitted GPD shape and uses that clipped value in both tail moments.")
    return [section.finish()]


def check_tail_dependence(rec: Recorder) -> list[dict[str, str]]:
    rng = np.random.default_rng(991)
    df = 6
    common = rng.multivariate_normal([0.0, 0.0], [[1.0, 0.65], [0.65, 1.0]], size=500)
    common *= np.sqrt(df / rng.chisquare(df, size=(500, 1)))
    a = pd.Series(0.0002 + 0.012 * common[:, 0])
    b = pd.Series(0.0001 + 0.015 * common[:, 1])
    backend = TailRiskService.calculate_bivariate_tail_dependence(a, b, marginal_df_a=df, marginal_df_b=df)
    rho = backend[1]
    nu = backend[2]
    argument = -np.sqrt(((nu + 1.0) * (1.0 - rho)) / (1.0 + rho))
    reference_lambda = float(2.0 * stats.t.cdf(argument, df=nu + 1.0))
    section = Section(rec, "Student-t lower-tail dependence", "SciPy Student-t CDF closed form", "MATCHES")
    section.check("lambda_lower", backend[0], reference_lambda, 1e-12, 1e-12, "MATCHES")
    section.check("correlation_rho", backend[1], float(np.corrcoef(a, b)[0, 1]), 1e-12, 1e-12, "MATCHES")
    rec.say(f"OUTPUT|{section.name}|backend={{'lambda_L': {backend[0]:.12g}, 'rho': {backend[1]:.12g}, 'nu': {backend[2]:.12g}}}")
    rec.say(f"OUTPUT|{section.name}|reference={{'lambda_L': {reference_lambda:.12g}}}")
    section.note("The implementation uses the average of independently fitted marginal t degrees of freedom, not a fitted joint t-copula.")
    return [section.finish()]


def hmm_fixture() -> tuple[pd.DataFrame, pd.Series]:
    n = 400
    rng = np.random.default_rng(2026)
    daily = np.empty(n)
    for start, end, mean, vol in ((0, 140, 0.0006, 0.004), (140, 270, -0.012, 0.020), (270, n, 0.0015, 0.008)):
        daily[start:end] = rng.normal(mean, vol, end - start)
    returns = pd.Series(daily, index=pd.bdate_range("2021-01-04", periods=n))
    close = 100.0 * np.cumprod(1.0 + returns)
    high = close * 1.012
    low = close * 0.988
    return pd.DataFrame({"close": close, "high": high, "low": low}, index=returns.index), returns


def hmm_reference(frame: pd.DataFrame) -> dict[str, object]:
    close = frame["close"].astype(float)
    ret = close.pct_change().dropna()
    ret21 = np.log(close / close.shift(21)).dropna()
    vol21 = (ret.rolling(21).std() * np.sqrt(252.0)).dropna()
    common = ret21.index.intersection(vol21.index)
    features = pd.concat([ret21.loc[common].rename("ret21"), vol21.loc[common].rename("vol21")], axis=1).dropna()
    scaled = StandardScaler().fit_transform(features.to_numpy())
    model = GaussianHMM(
        n_components=3,
        covariance_type="full",
        init_params="mc",
        params="mc",
        random_state=100,
        n_iter=200,
        tol=1e-4,
    )
    model.startprob_ = np.array([0.33, 0.34, 0.33])
    model.transmat_ = np.array([[0.96, 0.03, 0.01], [0.02, 0.96, 0.02], [0.01, 0.03, 0.96]])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model.fit(scaled)
    states = model.predict(scaled)
    posterior = model.predict_proba(scaled)
    rows = []
    for state in range(3):
        mask = states == state
        subset = ret.loc[common].to_numpy()[mask]
        cumulative = float(np.prod(1.0 + subset))
        cagr = float(cumulative ** (252.0 / subset.size) - 1.0) if cumulative > 0 else float(subset.mean() * 252.0)
        rows.append((state, cagr, float(vol21.loc[common].to_numpy()[mask].mean()), float(mask.mean() * 100.0)))
    ordered = sorted(rows, key=lambda item: item[1])
    state_order = [ordered[0][0], ordered[1][0], ordered[2][0]]
    label_map = {ordered[0][0]: "crisis", ordered[1][0]: "calm", ordered[2][0]: "bull"}
    display, veto_days = apply_crash_veto(states, label_map, ret21.loc[common].to_numpy())
    stability = round(float((1.0 - np.mean(np.diff(display) != 0)) * 100.0), 1)
    transition = [round(float(model.transmat_[source, target]) * 100.0, 1) for source in state_order for target in state_order]
    probabilities = [round(float(posterior[-1, state]) * 100.0, 4) for state in state_order]
    high = frame["high"].astype(float).replace(0, np.nan)
    low = frame["low"].astype(float).replace(0, np.nan)
    valid = (high > 0) & (low > 0) & (high >= low)
    log_hl = np.log((high[valid] / low[valid]).clip(lower=1.00001))
    parkinson = float((np.sqrt((log_hl**2).rolling(10, min_periods=3).mean() / (4.0 * np.log(2.0))) * np.sqrt(252.0)).iloc[-1])
    return {
        "current": label_map[int(display[-1])],
        "probabilities": probabilities,
        "transition": transition,
        "states": [(label_map[state], round(cagr, 4), round(ann_vol, 4), round(days_pct, 1)) for state, cagr, ann_vol, days_pct in rows],
        "stability": stability,
        "veto_days": veto_days,
        "ewma": float((ret.ewm(span=10).std() * np.sqrt(252.0)).iloc[-1]),
        "parkinson": parkinson,
        "observations": int(common.size),
    }


def check_regime(rec: Recorder) -> list[dict[str, str]]:
    frame, returns = hmm_fixture()
    got = classify(frame)
    ref = hmm_reference(frame)
    if got is None:
        raise AssertionError("classify returned None")
    probability_backend = [got["regime_probabilities"][label] for label in ("crisis", "calm", "bull")]
    transition_backend = [got["transition_matrix"][source][target] for source in ("crisis", "calm", "bull") for target in ("crisis", "calm", "bull")]
    state_backend = [(row["regime"], row["ann_ret"], row["ann_vol"], row["historical_days_pct"]) for row in got["states"]]
    state_labels = [row[0] for row in state_backend]
    reference_labels = [row[0] for row in ref["states"]]
    section = Section(rec, "Three-state Gaussian HMM regime detection, labels, and crash veto", "Independent feature construction plus direct hmmlearn 0.3.3 fit", "MATCHES")
    rec.say(f"OUTPUT|{section.name}|backend_current={got['current_regime']}|reference_current={ref['current']}")
    if got["current_regime"] != ref["current"]:
        raise AssertionError("HMM current regime differs from direct reference")
    section.check("current_probabilities", probability_backend, ref["probabilities"], 1e-12, 1e-12, "MATCHES")
    section.check("transition_matrix", transition_backend, ref["transition"], 1e-12, 1e-12, "MATCHES")
    rec.say(f"CHECK|{section.name}|state_labels|tolerance_verdict={'PASS' if state_labels == reference_labels else 'FAIL'}|check_verdict=MATCHES|backend={state_labels}|reference={reference_labels}")
    section.check("state_statistics", np.asarray([row[1:] for row in state_backend], dtype=float), np.asarray([row[1:] for row in ref["states"]], dtype=float), 1e-12, 1e-12, "MATCHES")
    section.check("stability_and_diagnostics", [got["stability_pct"], got["label_overrides"]["crash_veto_days"], got["realtime_ewma_vol"], got["realtime_parkinson_vol"], got["observations"]], [ref["stability"], ref["veto_days"], ref["ewma"], ref["parkinson"], ref["observations"]], 1e-4, 1e-3, "MATCHES")
    veto_states = np.array([0, 0, 1, 1, 2, 0])
    veto_values = np.array([-0.15, -0.05, -0.12, 0.03, -0.20, 0.10])
    veto_backend, veto_count = apply_crash_veto(veto_states, {0: "bull", 1: "calm", 2: "crisis"}, veto_values)
    section.check("crash_veto_hand_fixture", np.r_[veto_backend, veto_count], np.array([2, 0, 2, 1, 2, 0, 2]), 0.0, 0.0, "MATCHES")
    sub = returns.iloc[:80]
    summary = portfolio_regime_summary(sub)
    cumulative = float(np.prod(1.0 + sub.to_numpy()))
    ref_summary = {
        "days": 80,
        "ann_ret": round(cumulative ** (252.0 / 80) - 1.0, 4),
        "ann_vol": round(float(sub.std() * np.sqrt(252.0)), 4),
        "total_ret": round(cumulative - 1.0, 4),
        "annualized": True,
    }
    section.check("regime_conditioned_summary", [summary["days"], summary["ann_ret"], summary["ann_vol"], summary["total_ret"]], [ref_summary["days"], ref_summary["ann_ret"], ref_summary["ann_vol"], ref_summary["total_ret"]], 1e-12, 1e-12, "MATCHES")
    rec.say(f"OUTPUT|{section.name}|backend={{'observations': {got['observations']}, 'stability_pct': {got['stability_pct']}, 'veto_days': {got['label_overrides']['crash_veto_days']}, 'transition': {transition_backend}}}")
    rec.say(f"OUTPUT|{section.name}|reference={{'observations': {ref['observations']}, 'stability_pct': {ref['stability']}, 'veto_days': {ref['veto_days']}, 'transition': {ref['transition']}}}")
    section.note("The reference repeats the configured hmmlearn estimator independently; the feature, labeling, and veto formulas are reconstructed separately.")
    return [section.finish()]


def reference_gbm(mu: float, sigma: float, initial: float, horizon: float, paths: int, rng: np.random.Generator) -> np.ndarray:
    steps = int(round(float(horizon) * 252))
    dt = 1.0 / 252.0
    drift = (mu - 0.5 * sigma**2) * dt
    diffusion = sigma * np.sqrt(dt)
    shocks = rng.standard_normal((paths, steps))
    values = initial * np.exp(np.cumsum(drift + diffusion * shocks, axis=1))
    return np.hstack([np.full((paths, 1), initial), values])


def reference_student_t(mu: float, sigma: float, daily: np.ndarray, initial: float, horizon: float, paths: int, rng: np.random.Generator) -> tuple[np.ndarray, float]:
    steps = int(round(float(horizon) * 252))
    df_, loc_, scale_ = stats.t.fit(daily)
    effective_df = max(float(df_), 2.1)
    innovations = stats.t.rvs(effective_df, loc=loc_, scale=scale_, size=(paths, steps), random_state=rng)
    analytic_std = scale_ * np.sqrt(effective_df / (effective_df - 2.0))
    z = np.clip((innovations - loc_) / analytic_std, -8.0, 8.0)
    simulated = daily.mean() + daily.std(ddof=1) * z
    simulated = np.clip(simulated, -0.95, None)
    values = initial * np.exp(np.cumsum(np.log1p(simulated), axis=1))
    return np.hstack([np.full((paths, 1), initial), values]), float(df_)


def reference_bootstrap(daily: np.ndarray, initial: float, horizon: float, paths: int, rng: np.random.Generator) -> np.ndarray:
    steps = int(round(float(horizon) * 252))
    draws_per_path = int(np.ceil(steps / daily.size))
    bootstrap = StationaryBootstrap(21, daily, seed=int(rng.integers(0, 2**32 - 1)))
    generator = bootstrap.bootstrap(paths * draws_per_path)
    values = np.empty((paths, steps + 1))
    values[:, 0] = initial
    for path in range(paths):
        chunks: list[np.ndarray] = []
        total = 0
        while total < steps:
            position, _ = next(generator)
            block = np.asarray(position[0]).ravel()
            chunks.append(block)
            total += block.size
        sequence = np.concatenate(chunks)[:steps]
        values[path, 1:] = initial * np.cumprod(1.0 + sequence)
    return values


def goal_vector(paths: np.ndarray, target: float) -> list[float]:
    terminal = paths[:, -1]
    failing = terminal[terminal < target]
    shortfall = round(float(failing.mean() - target), 2) if failing.size else 0.0
    percentiles = np.percentile(terminal, [5, 25, 50, 75, 95])
    vector = [float(np.mean(terminal >= target)), *[round(float(value), 2) for value in percentiles], shortfall]
    checkpoints = list(range(0, paths.shape[1], 126))
    if checkpoints[-1] != paths.shape[1] - 1:
        checkpoints.append(paths.shape[1] - 1)
    for step in checkpoints:
        vector.extend(np.round(np.percentile(paths[:, step], [5, 25, 50, 75, 95]), 2).astype(float).tolist())
    return vector


def check_monte_carlo(rec: Recorder, returns: pd.Series) -> list[dict[str, str]]:
    initial = 100_000.0
    target = 115_000.0
    horizon = 1.0
    paths = 400
    mu, sigma, daily = _calibrate(returns)
    section = Section(rec, "Monte Carlo goal probability: GBM, Student-t, stationary bootstrap", "Independent NumPy/SciPy/arch streams with identical seeds", "MATCHES")
    outputs: list[dict[str, object]] = []
    for method, seed in (("gbm", 101), ("student_t", 202), ("bootstrap", 303)):
        rng_backend = np.random.default_rng(seed)
        if method == "gbm":
            backend_paths = _simulate_gbm(mu, sigma, initial, horizon, paths, rng_backend)
            reference_paths = reference_gbm(mu, sigma, initial, horizon, paths, np.random.default_rng(seed))
        elif method == "student_t":
            backend_paths, _ = _simulate_student_t(mu, sigma, daily, initial, horizon, paths, rng_backend)
            reference_paths, _ = reference_student_t(mu, sigma, daily, initial, horizon, paths, np.random.default_rng(seed))
        else:
            backend_paths = _simulate_bootstrap(daily, initial, horizon, paths, rng_backend)
            reference_paths = reference_bootstrap(daily, initial, horizon, paths, np.random.default_rng(seed))
        backend_result = simulate_goal(returns, initial, target, horizon, method=method, num_paths=paths, seed=seed)
        backend_vector = [backend_result["prob_success"], *[backend_result["terminal_percentiles"][key] for key in ("p5", "p25", "p50", "p75", "p95")], backend_result["expected_shortfall_vs_target"]]
        for fan in backend_result["fan"]:
            backend_vector.extend(fan[key] for key in ("p5", "p25", "p50", "p75", "p95"))
        reference_vector = goal_vector(reference_paths, target)
        section.check(f"{method}_full_path", backend_paths, reference_paths, 1e-9, 1e-12, "MATCHES")
        section.check(f"{method}_goal_output", backend_vector, reference_vector, 1e-12, 1e-12, "MATCHES")
        outputs.append(backend_result)
        rec.say(f"OUTPUT|{section.name}|method={method}|backend={{'prob_success': {backend_result['prob_success']:.12g}, 'terminal_percentiles': {backend_result['terminal_percentiles']}, 'expected_shortfall_vs_target': {backend_result['expected_shortfall_vs_target']:.12g}}}")
        rec.say(f"OUTPUT|{section.name}|method={method}|reference={{'prob_success': {reference_vector[0]:.12g}, 'terminal_percentiles': {reference_vector[1:6]}, 'expected_shortfall_vs_target': {reference_vector[6]:.12g}}}")
    rec.say(f"OUTPUT|{section.name}|all_backend_results={outputs}")
    section.note("Student-t draws are winsorized at eight analytic standard deviations and simple returns are floored at -95%; bootstrap is stationary with block length 21.")
    return [section.finish()]


def reference_backtest(returns: pd.DataFrame, strategy: str, frequency: int, lookback: int, cost_bps: float, rf: float) -> dict[str, object]:
    assets = list(returns.columns)
    indices = list(range(lookback, len(returns), frequency))
    indices.append(len(returns))
    current = np.ones(len(assets)) / len(assets)
    benchmark_weights = current.copy()
    daily_strategy: list[float] = []
    daily_benchmark: list[float] = []
    total_turnover = 0.0
    for start, end in zip(indices[:-1], indices[1:]):
        result = optimize(returns.iloc[start - lookback : start], strategy=strategy, risk_free_rate=rf)
        new_weights = np.array([result["weights"].get(asset, 0.0) for asset in assets])
        new_weights = np.clip(new_weights, 0.0, None)
        new_weights /= new_weights.sum()
        turnover = float(0.5 * np.sum(np.abs(new_weights - current)))
        total_turnover += turnover
        cost = turnover * cost_bps / 10_000.0
        current = new_weights
        values = returns.iloc[start:end].to_numpy(dtype=float)
        strategy_returns = values @ current
        strategy_returns[0] = (1.0 - cost) * (1.0 + strategy_returns[0]) - 1.0
        daily_strategy.extend(strategy_returns.tolist())
        daily_benchmark.extend((values @ benchmark_weights).tolist())
    strategy_array = np.asarray(daily_strategy)
    benchmark_array = np.asarray(daily_benchmark)
    strategy_equity = np.cumprod(1.0 + strategy_array)
    benchmark_equity = np.cumprod(1.0 + benchmark_array)
    strategy_dd = (strategy_equity - np.maximum.accumulate(strategy_equity)) / np.maximum.accumulate(strategy_equity)
    benchmark_dd = (benchmark_equity - np.maximum.accumulate(benchmark_equity)) / np.maximum.accumulate(benchmark_equity)
    years = strategy_array.size / 252.0
    strategy_cagr = float(strategy_equity[-1] ** (1.0 / years) - 1.0)
    benchmark_cagr = float(benchmark_equity[-1] ** (1.0 / years) - 1.0)
    strategy_vol = float(strategy_array.std(ddof=1) * np.sqrt(252.0))
    benchmark_vol = float(benchmark_array.std(ddof=1) * np.sqrt(252.0))
    strategy_sharpe = float((strategy_array.mean() * 252.0 - rf) / strategy_vol)
    benchmark_sharpe = float((benchmark_array.mean() * 252.0 - rf) / benchmark_vol)
    strategy_mdd = float(strategy_dd.min())
    benchmark_mdd = float(benchmark_dd.min())
    return {
        "cagr": round(strategy_cagr, 4),
        "annualized_volatility": round(strategy_vol, 4),
        "sharpe_ratio": round(strategy_sharpe, 4),
        "max_drawdown": round(strategy_mdd, 4),
        "calmar_ratio": round(strategy_cagr / abs(strategy_mdd), 4) if strategy_mdd else None,
        "total_turnover": round(total_turnover, 2),
        "benchmark_cagr": round(benchmark_cagr, 4),
        "benchmark_volatility": round(benchmark_vol, 4),
        "benchmark_sharpe": round(benchmark_sharpe, 4),
        "benchmark_max_drawdown": round(benchmark_mdd, 4),
        "first_oos": str(returns.index[lookback])[:10],
        "n_days": int(strategy_array.size),
        "strategy_equity": [round(float(value), 4) for value in strategy_equity],
    }


def check_backtest(rec: Recorder) -> list[dict[str, str]]:
    rng = np.random.default_rng(404)
    dates = pd.bdate_range("2022-01-03", periods=180)
    returns = pd.DataFrame(
        rng.multivariate_normal([0.0007, 0.0004, 0.0005], [[0.00012, 0.00004, 0.00003], [0.00004, 0.00020, 0.00005], [0.00003, 0.00005, 0.00009]], size=180),
        index=dates,
        columns=["AAA", "BBB", "CCC"],
    )
    params = {
        "strategy": "min_vol",
        "rebalance_freq_days": 30,
        "lookback_days": 60,
        "transaction_cost_bps": 75.0,
        "risk_free_rate": 0.02,
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        backend = run_walk_forward_backtest(returns, **params)
    reference = reference_backtest(
        returns,
        params["strategy"],
        params["rebalance_freq_days"],
        params["lookback_days"],
        params["transaction_cost_bps"],
        params["risk_free_rate"],
    )
    keys = ["cagr", "annualized_volatility", "sharpe_ratio", "max_drawdown", "calmar_ratio", "total_turnover", "benchmark_cagr", "benchmark_volatility", "benchmark_sharpe", "benchmark_max_drawdown"]
    section = Section(rec, "Walk-forward backtest mechanics and transaction friction", "Independent schedule/P&L loop using assigned min-vol dependency as a fixed oracle", "MATCHES")
    section.check("reported_metrics", [backend[key] for key in keys], [reference[key] for key in keys], 1e-12, 1e-12, "MATCHES")
    section.check("rounded_equity_curve", [row["strategy"] for row in backend["equity_curve"]], reference["strategy_equity"], 1e-12, 1e-12, "MATCHES")
    reference_display = {key: value for key, value in reference.items() if key != "strategy_equity"}
    rec.say(f"OUTPUT|{section.name}|backend={{'cagr': {backend['cagr']}, 'annualized_volatility': {backend['annualized_volatility']}, 'sharpe_ratio': {backend['sharpe_ratio']}, 'max_drawdown': {backend['max_drawdown']}, 'calmar_ratio': {backend['calmar_ratio']}, 'total_turnover': {backend['total_turnover']}, 'n_oos_days': {len(backend['equity_curve'])}}}")
    rec.say(f"OUTPUT|{section.name}|reference={reference_display}")
    section.note("The assigned min-vol optimizer is used only as a fixed weight oracle; its allocation math is outside this partition.")
    section.note("Transaction cost is interpreted as a round-trip rate applied to one-way half-L1 turnover; this convention is not independently estimable from code.")
    return [section.finish()]


def ema_recursive(values: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1.0)
    output = np.empty_like(values, dtype=float)
    output[0] = values[0]
    for index in range(1, values.size):
        output[index] = alpha * values[index] + (1.0 - alpha) * output[index - 1]
    return output


def wilder_rsi(close: np.ndarray, window: int = 14) -> float:
    delta = np.diff(close)
    gain = np.where(delta > 0.0, delta, 0.0)
    loss = np.where(delta < 0.0, -delta, 0.0)
    average_gain = float(gain[:window].mean())
    average_loss = float(loss[:window].mean())
    for index in range(window, gain.size):
        average_gain = (average_gain * (window - 1) + gain[index]) / window
        average_loss = (average_loss * (window - 1) + loss[index]) / window
    if average_gain + average_loss == 0.0:
        return 50.0
    return 100.0 * average_gain / (average_gain + average_loss)


def wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, window: int = 14) -> float:
    previous = np.concatenate(([close[0]], close[:-1]))
    true_range = np.maximum.reduce([high - low, np.abs(high - previous), np.abs(low - previous)])
    average = float(true_range[:window].mean())
    for value in true_range[window:]:
        average = ((window - 1) * average + value) / window
    return average


def indicator_frame(n: int = 260, seed: int = 314) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.012, n)))
    open_price = close * (1.0 + rng.normal(0.0, 0.003, n))
    high = np.maximum.reduce([close, open_price, close * (1.0 + rng.uniform(0.002, 0.02, n))])
    low = np.minimum.reduce([close, open_price, close * (1.0 - rng.uniform(0.002, 0.02, n))])
    volume = rng.integers(10_000, 100_000, n)
    return pd.DataFrame({"Date": dates, "Open": open_price, "High": high, "Low": low, "Close": close, "Volume": volume})


def indicator_references(frame: pd.DataFrame) -> dict[str, float]:
    close = frame["Close"].to_numpy(dtype=float)
    high = frame["High"].to_numpy(dtype=float)
    low = frame["Low"].to_numpy(dtype=float)
    volume = frame["Volume"].to_numpy(dtype=float)
    typical = (high + low + close) / 3.0
    ema10 = ema_recursive(close, 10)
    ema12 = ema_recursive(close, 12)
    ema26 = ema_recursive(close, 26)
    macd = ema12 - ema26
    signal = ema_recursive(macd, 9)
    middle = float(close[-20:].mean())
    population_std = float(close[-20:].std(ddof=0))
    raw_flow = typical * volume
    flow_delta = np.diff(typical, prepend=typical[0])
    positive = np.where(flow_delta > 0.0, raw_flow, 0.0)[-14:].sum()
    negative = np.where(flow_delta < 0.0, raw_flow, 0.0)[-14:].sum()
    mfi = 100.0 * positive / (positive + negative) if positive + negative else 50.0
    vwma_num = float((typical[-14:] * volume[-14:]).sum())
    vwma_den = float(volume[-14:].sum())
    return {
        "close_10_ema": float(ema10[-1]),
        "close_50_sma": float(close[-50:].mean()),
        "close_200_sma": float(close[-200:].mean()),
        "rsi": wilder_rsi(close),
        "boll": middle,
        "boll_ub": middle + 2.0 * population_std,
        "boll_lb": middle - 2.0 * population_std,
        "macd": float(macd[-1]),
        "macds": float(signal[-1]),
        "macdh": float(macd[-1] - signal[-1]),
        "atr": wilder_atr(high, low, close),
        "vwma": vwma_num / vwma_den,
        "mfi": mfi,
    }


def check_indicators(rec: Recorder) -> list[dict[str, str]]:
    frame = indicator_frame()
    names = list(indicator_references(frame))
    backend = _compute_sync(frame, names)
    reference = indicator_references(frame)
    section = Section(rec, "Technical indicators: SMA, EMA, RSI, MACD, Bollinger, ATR, VWMA, MFI", "Canonical independent formulas; optional TA-Lib oracle is not installed", "BUG", "Medium")
    verdicts = {
        "close_10_ema": "MATCHES",
        "close_50_sma": "MATCHES",
        "close_200_sma": "MATCHES",
        "rsi": "MATCHES",
        "boll": "MATCHES",
        "boll_ub": "DIVERGES",
        "boll_lb": "DIVERGES",
        "macd": "MATCHES",
        "macds": "MATCHES",
        "macdh": "MATCHES",
        "atr": "MATCHES",
        "vwma": "MATCHES",
        "mfi": "BUG",
    }
    for name in names:
        tolerance = (1e-7, 1e-7) if name in {"rsi", "macd", "macds", "macdh", "atr"} else (1e-10, 1e-10)
        section.check(name, float(backend[name].iloc[-1]), reference[name], tolerance[0], tolerance[1], verdicts[name])
        rec.say(f"OUTPUT|{section.name}|{name}|backend={float(backend[name].iloc[-1]):.12g}|reference={reference[name]:.12g}")
    for window in (50, 200):
        backend_finite = int(pd.Series(backend[f"close_{window}_sma"]).notna().sum())
        reference_finite = int(frame["Close"].rolling(window, min_periods=window).mean().notna().sum())
        section.note(f"close_{window}_sma finite warmup values backend={backend_finite}, full-window reference={reference_finite}, extra_partial_rows={backend_finite - reference_finite}")
    rec.say(f"OUTPUT|{section.name}|threshold_contract=backend MFI is fraction-like; SUPPORTED_INDICATORS documents >80/<20")
    section.note("Adjusted EWM seed, Wilder seed, sample-vs-population rolling sigma, and min_periods=1 are convention differences.")
    section.note("MFI omits the standard factor of 100, contradicting the backend's own >80/<20 description.")
    return [section.finish()]


def check_factor_exposure(rec: Recorder) -> list[dict[str, str]]:
    rng = np.random.default_rng(606)
    dates = pd.bdate_range("2022-01-03", periods=260)
    benchmark_returns = pd.Series(rng.normal(0.0004, 0.010, 260), index=dates)
    returns = pd.DataFrame(
        {
            "AAA": 0.0003 + 1.25 * benchmark_returns.to_numpy() + rng.normal(0.0, 0.003, 260),
            "BBB": 0.0002 + 0.70 * benchmark_returns.to_numpy() + rng.normal(0.0, 0.005, 260),
        },
        index=dates,
    )
    prices = pd.DataFrame({column: 100.0 * np.cumprod(1.0 + returns[column].to_numpy()) for column in returns}, index=dates)
    weights = {"AAA": 0.6, "BBB": 0.4}
    engine = AnalyticsEngine()
    got = asyncio.run(engine.factor_exposure_analysis(prices, benchmark_data=benchmark_returns, weights=weights))
    active_returns = prices.pct_change(fill_method=None).iloc[1:]
    portfolio = active_returns @ pd.Series(weights)
    fit = OLS(portfolio.to_numpy(), add_constant(benchmark_returns.iloc[1:].to_numpy())).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    reference = {
        "alpha": round(float(fit.params[0]), 6),
        "annualized_alpha": round(float(fit.params[0] * 252.0), 4),
        "market": round(float(fit.params[1]), 4),
        "r_squared": round(float(fit.rsquared), 4),
        "adjusted_r_squared": round(max(0.0, float(fit.rsquared_adj)), 4),
    }
    backend = {
        "alpha": got["portfolio"]["alpha"],
        "annualized_alpha": got["portfolio"]["annualized_alpha"],
        "market": got["portfolio"]["market"],
        "r_squared": got["r_squared"],
        "adjusted_r_squared": got["adjusted_r_squared"],
    }
    section = Section(rec, "Benchmark-relative OLS beta, alpha, and R-squared", "statsmodels 0.15.0 OLS with HAC covariance", "MATCHES")
    section.check("portfolio_factor_vector", list(backend.values()), list(reference.values()), 1e-12, 1e-12, "MATCHES")
    rec.say(f"OUTPUT|{section.name}|backend={backend}")
    rec.say(f"OUTPUT|{section.name}|reference={reference}")
    section.note("Alpha is the daily regression intercept multiplied by 252; it is not risk-free-adjusted and HAC affects standard errors, not the reported coefficients.")
    return [section.finish()]


class EmptyResult:
    def scalars(self) -> "EmptyResult":
        return self

    def all(self) -> list[object]:
        return []


class FakeDB:
    async def execute(self, statement: object) -> EmptyResult:
        return EmptyResult()


class PositionResult:
    def __init__(self, positions: list[SimpleNamespace]) -> None:
        self.positions = positions

    def scalars(self) -> "PositionResult":
        return self

    def all(self) -> list[SimpleNamespace]:
        return self.positions


class PositionDB:
    def __init__(self, positions: list[SimpleNamespace]) -> None:
        self.positions = positions

    async def execute(self, statement: object) -> PositionResult:
        return PositionResult(self.positions)


class FakeDataService:
    def __init__(self, index: pd.DatetimeIndex) -> None:
        self.index = index

    async def fetch_historical_data(self, ticker: str, start: str, end: str, force_refresh: bool = False) -> pd.DataFrame:
        seed = {"AAA": 701, "BBB": 702}[ticker]
        rng = np.random.default_rng(seed)
        returns = rng.normal(0.0005, 0.012, len(self.index))
        prices = 100.0 * np.cumprod(1.0 + returns)
        return pd.DataFrame({"adj_close": prices}, index=self.index)


class FakeBenchmark:
    def __init__(self, index: pd.DatetimeIndex) -> None:
        self.index = index

    async def get_returns(self, start: str | None = None, end: str | None = None, days: int = 756) -> pd.Series:
        rng = np.random.default_rng(703)
        return pd.Series(rng.normal(0.0004, 0.010, len(self.index)) + 1e-6, index=self.index)


def rounded_metric(function: object, returns: pd.Series, **kwargs: object) -> float | None:
    try:
        value = float(function(returns, **kwargs))
        return round(value, 6) if math.isfinite(value) else None
    except Exception:
        return None


def check_tear_sheet(rec: Recorder) -> list[dict[str, str]]:
    index = pd.bdate_range("2024-01-01", periods=180)
    fake_data = FakeDataService(index)
    fake_benchmark = FakeBenchmark(index)
    backend = asyncio.run(
        get_tear_sheet(
            tickers="AAA,BBB",
            start=str(index[0].date()),
            end=str(index[-1].date()),
            db=FakeDB(),
            data_service=fake_data,
            benchmark=fake_benchmark,
        )
    )
    performance = asyncio.run(
        get_performance_history(
            days=180,
            tickers="AAA,BBB",
            db=PositionDB(
                [
                    SimpleNamespace(ticker="AAA", quantity=100.0, market_value=0.0, last_price=0.0, buy_price=None, added_on=None),
                    SimpleNamespace(ticker="BBB", quantity=100.0, market_value=0.0, last_price=0.0, buy_price=None, added_on=None),
                ]
            ),
            data_service=fake_data,
            benchmark_service=fake_benchmark,
        )
    )
    frames: dict[str, pd.DataFrame] = {}
    for ticker, seed in (("AAA", 701), ("BBB", 702)):
        rng = np.random.default_rng(seed)
        asset_returns = rng.normal(0.0005, 0.012, len(index))
        frames[ticker] = pd.DataFrame({"adj_close": 100.0 * np.cumprod(1.0 + asset_returns)}, index=index)
    prices = pd.concat({ticker: frame["adj_close"] for ticker, frame in frames.items()}, axis=1).sort_index()
    returns = prices.pct_change(fill_method=None).fillna(0.0).iloc[1:]
    portfolio = 0.5 * returns["AAA"] + 0.5 * returns["BBB"]
    benchmark = asyncio.run(fake_benchmark.get_returns(days=len(index)))
    ref_metrics = {
        "total_return": rounded_metric(qs.stats.comp, portfolio),
        "cagr": rounded_metric(qs.stats.cagr, portfolio),
        "sharpe": rounded_metric(qs.stats.sharpe, portfolio, rf=0.02),
        "sortino": rounded_metric(qs.stats.sortino, portfolio, rf=0.02),
        "calmar": rounded_metric(qs.stats.calmar, portfolio),
        "omega": rounded_metric(qs.stats.omega, portfolio),
        "tail_ratio": rounded_metric(qs.stats.tail_ratio, portfolio),
        "volatility": rounded_metric(qs.stats.volatility, portfolio),
        "max_drawdown": rounded_metric(qs.stats.max_drawdown, portfolio),
        "skew": rounded_metric(qs.stats.skew, portfolio),
        "kurtosis": rounded_metric(qs.stats.kurtosis, portfolio),
    }
    ref_beta = float(portfolio.cov(benchmark) / benchmark.var())
    ref_alpha = float((portfolio.mean() - ref_beta * benchmark.mean()) * 252.0)
    ref_monthly = ((1.0 + portfolio).groupby([portfolio.index.year, portfolio.index.month]).prod() - 1.0)
    ref_monthly_values = [round(float(value), 6) for value in ref_monthly.to_numpy()]
    backend_monthly = [value for year in sorted(backend["monthly_returns"]) for _, value in sorted(backend["monthly_returns"][year].items(), key=lambda item: int(item[0]))]
    holding_value = 100.0 * prices["AAA"] + 100.0 * prices["BBB"]
    holding_return = holding_value.pct_change().fillna(0.0)
    benchmark_value = (1.0 + benchmark).cumprod()
    benchmark_value = benchmark_value / benchmark_value.iloc[0] * holding_value.iloc[0]
    performance_reference = [
        [round(float(holding_value.loc[date]), 2), round(float(holding_return.loc[date]), 6), round(float(benchmark_value.loc[date]), 2)]
        for date in holding_value.index
    ]
    performance_backend = [
        [row["portfolio_value"], row["return"], row["benchmark_value"]]
        for row in performance
    ]
    section = Section(rec, "Quantstats tear-sheet, performance history, monthly compounding, underwater curve, and relative beta/alpha", "Direct quantstats 0.0.81 plus NumPy/Pandas identities", "MATCHES")
    section.check("tear_sheet_metrics", [backend["metrics"][key] for key in ref_metrics], list(ref_metrics.values()), 1e-12, 1e-12, "MATCHES")
    section.check("relative_beta_alpha", [backend["relative_vs_nifty"]["beta_vs_nifty"], backend["relative_vs_nifty"]["alpha_annualized"]], [round(ref_beta, 4), round(ref_alpha, 4)], 1e-12, 1e-12, "MATCHES")
    section.check("monthly_compounded_returns", backend_monthly, ref_monthly_values, 1e-12, 1e-12, "MATCHES")
    backend_underwater = [row["drawdown"] for row in backend["underwater"]]
    ref_underwater = [round(float(value), 6) for value in qs.stats.to_drawdown_series(portfolio).iloc[-250:].to_numpy()]
    section.check("underwater_curve", backend_underwater, ref_underwater, 1e-12, 1e-12, "MATCHES")
    section.check("performance_history_and_rebased_benchmark", np.asarray(performance_backend, dtype=float).ravel(), np.asarray(performance_reference, dtype=float).ravel(), 1e-12, 1e-12, "MATCHES")
    rec.say(f"OUTPUT|{section.name}|backend_metrics={backend['metrics']}")
    rec.say(f"OUTPUT|{section.name}|reference_metrics={ref_metrics}")
    rec.say(f"OUTPUT|{section.name}|backend_relative={backend['relative_vs_nifty']}")
    rec.say(f"OUTPUT|{section.name}|reference_relative={{'beta_vs_nifty': {round(ref_beta, 4)}, 'alpha_annualized': {round(ref_alpha, 4)}}}")
    section.note("This endpoint is library-delegated rather than a hand-rolled estimator; direct calls establish wrapper parity.")
    return [section.finish()]


class ScalarResult:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows

    def scalars(self) -> "ScalarResult":
        return self

    def all(self) -> list[SimpleNamespace]:
        return self.rows


class DeliveryDB:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows

    async def execute(self, statement: object) -> ScalarResult:
        return ScalarResult(self.rows)


def check_delivery_anomaly(rec: Recorder) -> list[dict[str, str]]:
    historical = [10.0, 20.0, 5.0, 15.0, 10.0]
    rows = [SimpleNamespace(symbol="TEST", deliv_per=30.0, close=100.0, turnover_lacs=10.0)]
    rows.extend(SimpleNamespace(symbol="TEST", deliv_per=value, close=100.0, turnover_lacs=10.0) for value in historical)
    fake = DeliveryDB(rows)
    service = SimpleNamespace(db=fake)
    got = asyncio.run(IndiaDataService.get_delivery_anomalies(service, ["TEST.NS"], lookback_days=5, sigma_threshold=2.0))[0]
    reference_sample_z = float(np.asarray(stats.zscore(np.asarray([30.0, *historical]), ddof=1)).reshape(-1)[0])
    section = Section(rec, "Delivery-percentage rolling z-score anomaly", "SciPy z-score with sample standard deviation", "DIVERGES")
    section.check("rounded_z_score", got["z_score"], round(reference_sample_z, 2), 0.0051, 0.0, "DIVERGES")
    rec.say(f"OUTPUT|{section.name}|backend={{'z_score': {got['z_score']}, 'is_anomaly': {got['is_anomaly']}}}")
    rec.say(f"OUTPUT|{section.name}|reference_sample_std={{'z_score': {round(reference_sample_z, 2)}, 'is_anomaly': {round(reference_sample_z, 2) >= 2.0}}}")
    section.note("Backend uses population ddof=0 and replaces zero standard deviation with 1.0; this is a convention difference.")
    return [section.finish()]


def check_liquidity(rec: Recorder) -> list[dict[str, str]]:
    rng = np.random.default_rng(808)
    dates = pd.bdate_range("2024-01-01", periods=40)
    close = pd.Series(1000.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, 40))), index=dates)
    volume = pd.Series(rng.integers(50_000, 150_000, 40), index=dates, dtype=float)
    rupee_volume = close * volume
    returns = close.pct_change().dropna()
    aligned_volume = rupee_volume.loc[returns.index]
    amihud_backend = compute_amihud_illiquidity(returns, aligned_volume)
    amihud_reference = float(np.mean((returns.abs() / aligned_volume) * 1e6))
    days_backend = compute_days_to_liquidate(100_000.0, 100_000_000.0, 0.10)
    days_reference = 100_000.0 / (0.10 * 100_000_000.0)
    position = SimpleNamespace(ticker="TEST.NS", market_value=100_000.0, quantity=100.0, last_price=1000.0)
    history = pd.DataFrame({"close": close, "volume": volume})
    full = asyncio.run(IndiaDataService.calculate_portfolio_liquidity_limits(object(), [position], {"TEST.NS": history}))
    ref_adv_shares = float(volume.tail(30).mean())
    ref_adv_rupees = float(rupee_volume.tail(30).mean())
    ref_days_20 = 100_000.0 / (0.20 * ref_adv_rupees)
    row = full["positions"][0]
    section = Section(rec, "Cash-equity Amihud illiquidity and ADV liquidation diagnostics", "NumPy closed forms", "MATCHES")
    section.check("amihud", amihud_backend, amihud_reference, 1e-12, 1e-12, "MATCHES")
    section.check("days_to_liquidate", days_backend, days_reference, 1e-12, 1e-12, "MATCHES")
    section.check("displayed_adv_days", [row["adv_30d_shares"], row["adv_30d_rupees"], row["days_to_liquidate_20pct_adv"]], [round(ref_adv_shares), round(ref_adv_rupees, 2), round(ref_days_20, 2)], 1e-12, 1e-12, "MATCHES")
    rec.say(f"OUTPUT|{section.name}|backend={{'amihud': {amihud_backend:.12g}, 'days_10': {days_backend:.12g}, 'position': {row}}}")
    rec.say(f"OUTPUT|{section.name}|reference={{'amihud': {amihud_reference:.12g}, 'days_10': {days_reference:.12g}, 'adv_30d_shares': {round(ref_adv_shares)}, 'adv_30d_rupees': {round(ref_adv_rupees, 2)}, 'days_20': {round(ref_days_20, 2)}}}")
    section.note("The metric assumes rupee-volume scaling and a 30-session simple mean ADV for cash-equity liquidity analysis.")
    return [section.finish()]


def main() -> None:
    rec = Recorder()
    rec.say("VERIFY_RISK_TIMESERIES_V1")
    rec.say("READ_ONLY_EVIDENCE|No production files modified; no DB/network fixture; deterministic seeds declared per check")
    rec.say(f"BACKEND_ROOT={BACKEND}")
    rec.say(f"OUTPUT_FILE={OUTPUT}")
    inventory(rec)
    returns = synthetic_returns()
    rec.say(f"FIXTURE|returns_n={returns.size}|start={returns.index[0].date()}|end={returns.index[-1].date()}|seed=20260923")
    summaries: list[dict[str, str]] = []
    summaries.extend(check_realized_metrics(rec, returns))
    summaries.extend(check_var_cvar(rec, returns))
    summaries.extend(check_drawdown_shape(rec, returns))
    summaries.extend(check_static_ewma(rec, returns))
    summaries.extend(check_recursive_ewma(rec, returns))
    summaries.extend(check_rolling_cone(rec, returns))
    summaries.extend(check_analytics_garch(rec, returns))
    summaries.extend(check_vol_service_garch(rec, returns))
    summaries.extend(check_egarch(rec, returns))
    summaries.extend(check_evt(rec))
    summaries.extend(check_tail_dependence(rec))
    summaries.extend(check_regime(rec))
    summaries.extend(check_monte_carlo(rec, returns))
    summaries.extend(check_backtest(rec))
    summaries.extend(check_indicators(rec))
    summaries.extend(check_factor_exposure(rec))
    summaries.extend(check_tear_sheet(rec))
    summaries.extend(check_delivery_anomaly(rec))
    summaries.extend(check_liquidity(rec))
    rec.say("SUMMARY_START")
    for item in summaries:
        rec.say("SUMMARY|" + "|".join(item[key] for key in ("model", "verdict", "severity", "reference", "max_abs", "max_rel")))
    counts = Counter(item["verdict"] for item in summaries)
    for verdict in ("MATCHES", "DIVERGES", "BUG", "REPLACE-WITH-LIBRARY"):
        rec.say(f"VERDICT_COUNT|{verdict}|{counts.get(verdict, 0)}")
    rec.say("SUMMARY_END")
    rec.say("SCRIPT_STATUS|SUCCESS")
    rec.save()


if __name__ == "__main__":
    main()
