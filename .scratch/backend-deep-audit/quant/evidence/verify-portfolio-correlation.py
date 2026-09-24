from __future__ import annotations

import asyncio
import importlib.metadata as metadata
import inspect
import json
import logging
import math
import sys
import warnings
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch

import numpy as np
import pandas as pd
from numpy.exceptions import ComplexWarning
from arch import arch_model
from arch.bootstrap import StationaryBootstrap
from scipy import stats
from scipy.optimize import linprog, minimize
from scipy.spatial.distance import squareform
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint
from statsmodels.tsa.vector_ar.vecm import coint_johansen

SCRIPT_PATH = Path(__file__).resolve()
OUTPUT_PATH = SCRIPT_PATH.parents[1] / "outputs" / "verify-portfolio-correlation.txt"
REPO_ROOT = SCRIPT_PATH.parents[4]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.api import analytics as analytics_api
from app.api.analytics import get_performance_history
from app.api.portfolio import RebalancePayload, add_portfolio_position, get_portfolio
from app.models.database import PortfolioPosition
from app.models.schemas import PortfolioPositionCreate
from app.services.analytics_engine import AnalyticsEngine
from app.services.backtest_service import run_walk_forward_backtest
from app.services.cointegration_service import analyze_pair_cointegration, compute_ou_parameters
from app.services.correlation_service import analyze_correlation_stability, compute_rolling_avg_correlation
from app.services.india_data_service import compute_amihud_illiquidity, compute_days_to_liquidate
from app.services.monte_carlo_service import simulate_goal
from app.services.optimization_service import _hrp_weights, _max_sharpe, _min_cvar, _min_vol, optimize
from app.services.tail_risk_service import TailRiskService
from app.services.volatility_service import VolatilityService
from app.utils.holdings import portfolio_regime_summary

logging.disable(logging.CRITICAL)
warnings.filterwarnings("ignore", category=ComplexWarning)
TRADING_DAYS = 252
LINES: list[str] = []
CASES: list[dict[str, Any]] = []


def emit(value: Any = "") -> None:
    LINES.append(str(value))


def jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, float)):
        return float(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def flatten_numeric(value: Any) -> list[float]:
    if isinstance(value, dict):
        flattened: list[float] = []
        for key in sorted(value):
            flattened.extend(flatten_numeric(value[key]))
        return flattened
    if isinstance(value, (list, tuple, np.ndarray)):
        flattened = []
        for item in value:
            flattened.extend(flatten_numeric(item))
        return flattened
    return [float(value)]


def numeric_pair(backend: Any, reference: Any) -> tuple[np.ndarray, np.ndarray, float, float]:
    backend_array = np.asarray(flatten_numeric(backend), dtype=float)
    reference_array = np.asarray(flatten_numeric(reference), dtype=float)
    difference = np.abs(backend_array - reference_array)
    denominator = np.maximum(np.abs(reference_array), 1e-15)
    return backend_array, reference_array, float(np.max(difference)), float(np.max(difference / denominator))


def record(
    model: str,
    metric: str,
    backend: Any,
    reference: Any,
    atol: float,
    rtol: float,
    verdict: str,
    severity: str,
    reference_name: str,
    note: str,
) -> None:
    backend_value, reference_value, absolute, relative = numeric_pair(backend, reference)
    passed = bool(np.allclose(backend_value, reference_value, atol=atol, rtol=rtol))
    if verdict == "MATCHES":
        assert passed, (
            f"{model} / {metric}: expected MATCHES but values differ; "
            f"backend={backend_value.tolist()}; reference={reference_value.tolist()}"
        )
    CASES.append(
        {
            "model": model,
            "metric": metric,
            "backend": jsonable(backend_value),
            "reference": jsonable(reference_value),
            "abs_diff": absolute,
            "rel_diff": relative,
            "atol": atol,
            "rtol": rtol,
            "verdict": verdict,
            "severity": severity,
            "reference_name": reference_name,
            "note": note,
        }
    )


def raw_case(title: str, values: dict[str, Any]) -> None:
    emit(title)
    for key, value in values.items():
        emit(f"  {key}: {json.dumps(jsonable(value), sort_keys=True)}")


def synthetic_returns(days: int = 360, seed: int = 20260923) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=days)
    shocks = rng.normal(0.00035, 0.012, (days, 3))
    data = {
        "AAA": 0.0004 + 0.85 * shocks[:, 0] + 0.10 * shocks[:, 1],
        "BBB": 0.0002 + 0.40 * shocks[:, 0] - 0.55 * shocks[:, 1],
        "CCC": 0.0001 + 0.20 * shocks[:, 1] + 0.65 * shocks[:, 2],
    }
    return pd.DataFrame(data, index=dates)


def prices_from_returns(returns: pd.DataFrame, initial: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame({column: initial * (1.0 + returns[column]).cumprod() for column in returns}, index=returns.index)


def rolling_pair_reference(returns: pd.DataFrame, window: int, min_periods: int) -> pd.Series:
    output: dict[pd.Timestamp, float] = {}
    for end in range(len(returns)):
        start = max(0, end - window + 1)
        values: list[float] = []
        for first, second in combinations(returns.columns, 2):
            left = returns[first].iloc[start : end + 1].to_numpy(dtype=float)
            right = returns[second].iloc[start : end + 1].to_numpy(dtype=float)
            mask = np.isfinite(left) & np.isfinite(right)
            if int(mask.sum()) < min_periods:
                continue
            values.append(float(np.corrcoef(left[mask], right[mask])[0, 1]))
        if values:
            output[returns.index[end]] = float(np.mean(values))
    return pd.Series(output, dtype=float).dropna()


def drawdown_with_baseline(returns: pd.Series) -> float:
    wealth = pd.concat([pd.Series([1.0]), (1.0 + returns).cumprod()], ignore_index=True)
    drawdown = wealth / wealth.cummax() - 1.0
    return float(drawdown.min())


def tangency_reference(excess: np.ndarray, covariance: np.ndarray) -> np.ndarray:
    count = len(excess)
    initial = np.full(count, 1.0 / count)
    result = minimize(
        lambda values: float(values @ covariance @ values),
        initial,
        method="SLSQP",
        bounds=[(0.0, None)] * count,
        constraints={"type": "eq", "fun": lambda values: float(excess @ values - 1.0)},
        options={"ftol": 1e-13, "maxiter": 2000},
    )
    assert result.success, result.message
    raw = np.asarray(result.x, dtype=float)
    return raw / raw.sum()


def hrp_reference(returns: pd.DataFrame) -> np.ndarray:
    correlation = returns.corr().fillna(0.0)
    matrix = correlation.to_numpy(copy=True)
    np.fill_diagonal(matrix, 1.0)
    distance = np.sqrt(np.clip(0.5 * (1.0 - matrix), 0.0, 1.0))
    from scipy.cluster import hierarchy

    linkage = hierarchy.linkage(squareform(distance, checks=False), method="single")
    children = linkage[:, :2].astype(int)
    leaves = len(linkage) + 1
    order = [int(children[-1, 0]), int(children[-1, 1])]
    while max(order) >= leaves:
        expanded: list[int] = []
        for item in order:
            if item < leaves:
                expanded.append(item)
            else:
                expanded.extend(int(value) for value in children[item - leaves])
        order = expanded
    labels = correlation.index[order].tolist()
    covariance = returns.cov().loc[labels, labels].to_numpy(dtype=float)
    covariance = np.where(np.isfinite(covariance), covariance, 0.0)
    variances = np.diag(covariance).copy()
    valid = variances[np.isfinite(variances) & (variances > 1e-12)]
    fill = float(valid.mean()) if valid.size else 1.0
    variances = np.where(np.isfinite(variances) & (variances > 1e-12), variances, fill)
    np.fill_diagonal(covariance, variances)
    weights = pd.Series(1.0, index=labels)

    def cluster_variance(items: list[int]) -> float:
        submatrix = covariance[np.ix_(items, items)]
        inverse = 1.0 / np.diag(submatrix)
        inverse = np.where(np.isfinite(inverse) & (inverse > 0), inverse, np.nan)
        if np.isnan(inverse).all():
            inverse = np.ones(len(items)) / len(items)
        else:
            inverse = np.where(np.isnan(inverse), 0.0, inverse)
            total = inverse.sum()
            inverse = inverse / total if total > 0 else np.ones(len(items)) / len(items)
        return float(inverse @ submatrix @ inverse)

    clusters = [list(range(len(labels)))]
    while clusters:
        next_clusters: list[list[int]] = []
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            midpoint = len(cluster) // 2
            left, right = cluster[:midpoint], cluster[midpoint:]
            left_variance = cluster_variance(left)
            right_variance = cluster_variance(right)
            denominator = left_variance + right_variance
            alpha = 0.5 if not np.isfinite(denominator) or denominator <= 0 else 1.0 - left_variance / denominator
            weights.iloc[left] *= alpha
            weights.iloc[right] *= 1.0 - alpha
            if len(left) > 1:
                next_clusters.append(left)
            if len(right) > 1:
                next_clusters.append(right)
        clusters = next_clusters
    return (weights / weights.sum()).to_numpy(dtype=float)


def linprog_cvar_reference(returns: pd.DataFrame, beta: float = 0.95) -> np.ndarray:
    scenarios = returns.to_numpy(dtype=float)
    count, assets = scenarios.shape
    losses = -scenarios
    objective = np.concatenate([np.zeros(assets), [1.0], np.full(count, 1.0 / ((1.0 - beta) * count))])
    first_bounds = [(0.0, 1.0)] * assets
    matrix = np.zeros((count + 2, assets + 1 + count))
    rhs = np.zeros(count + 2)
    for row in range(count):
        matrix[row, :assets] = losses[row]
        matrix[row, assets] = -1.0
        matrix[row, assets + 1 + row] = -1.0
        rhs[row] = 0.0
    matrix[count, :assets] = 1.0
    matrix[count, assets] = 0.0
    rhs[count] = 1.0
    matrix[count + 1, assets + 1 :] = 1.0
    rhs[count + 1] = 0.0
    result = linprog(
        objective,
        A_ub=matrix[:count],
        b_ub=rhs[:count],
        A_eq=matrix[count : count + 1],
        b_eq=rhs[count : count + 1],
        bounds=first_bounds + [(None, None)] + [(0.0, None)] * count,
        method="highs",
    )
    assert result.success, result.message
    return np.asarray(result.x[:assets], dtype=float), float(objective @ result.x)


class FakeResult:
    def __init__(self, values: list[Any]):
        self.values = values

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[Any]:
        return self.values


class FakeSession:
    def __init__(self, positions: list[PortfolioPosition] | None = None):
        self.positions = positions or []
        self.added: list[Any] = []

    async def execute(self, statement: Any) -> FakeResult:
        return FakeResult(list(self.positions))

    def add(self, value: Any) -> None:
        self.added.append(value)
        if isinstance(value, PortfolioPosition):
            self.positions.append(value)

    async def commit(self) -> None:
        return None

    async def refresh(self, value: Any) -> None:
        if getattr(value, "id", None) is None:
            value.id = 1

    async def rollback(self) -> None:
        return None


class QuoteService:
    def __init__(self, price: float | None):
        self.price = price

    async def validate_ticker(self, ticker: str) -> bool:
        return True

    async def fetch_quote(self, ticker: str) -> dict[str, Any] | None:
        if self.price is None:
            return None
        return {"current_price": self.price, "sector": "Equity", "industry": "Test"}


class TearSheetBenchmark:
    def __init__(self, returns: pd.Series):
        self.returns = returns

    async def get_returns(self, start: str | None = None, end: str | None = None, days: int = 756) -> pd.Series:
        return self.returns.copy()


class TearSheetDataService:
    pass


async def invoke_tear_sheet(returns: pd.DataFrame, portfolio: pd.Series, benchmark: pd.Series) -> dict[str, Any]:
    async def resolve_allocation(tickers: Optional[str], db: Any) -> tuple[list[str], dict[str, float]]:
        weights = {column: 1.0 / returns.shape[1] for column in returns.columns}
        return list(returns.columns), weights

    async def resolve_holdings(db: Any, tickers: list[str]) -> dict[str, Any]:
        return {}

    async def build_wide_returns(*args: Any, **kwargs: Any) -> tuple[pd.DataFrame, pd.Series, dict[str, Any]]:
        return returns.copy(), portfolio.copy(), {"covered_days": len(portfolio), "annualized": True}

    with (
        patch.object(analytics_api, "resolve_allocation", resolve_allocation),
        patch.object(analytics_api, "resolve_holdings", resolve_holdings),
        patch.object(analytics_api, "_build_wide_returns", build_wide_returns),
    ):
        return await analytics_api.get_tear_sheet(
            tickers="AAA,BBB,CCC",
            start="2024-01-02",
            end="2026-12-31",
            db=object(),
            data_service=TearSheetDataService(),
            benchmark=TearSheetBenchmark(benchmark),
        )


async def invoke_risk_contribution(returns: pd.DataFrame, portfolio: pd.Series, weights: dict[str, float]) -> dict[str, Any]:
    positions = [PortfolioPosition(ticker=column, sector=f"S{index + 1}", weight=weight) for index, (column, weight) in enumerate(weights.items())]
    session = FakeSession(positions)

    async def resolve_allocation(tickers: Optional[str], db: Any) -> tuple[list[str], dict[str, float]]:
        return list(weights), weights

    async def build_wide_returns(*args: Any, **kwargs: Any) -> tuple[pd.DataFrame, pd.Series, dict[str, Any]]:
        return returns.copy(), portfolio.copy(), {"covered_days": len(portfolio), "annualized": True}

    with (
        patch.object(analytics_api, "resolve_allocation", resolve_allocation),
        patch.object(analytics_api, "resolve_holdings", lambda *args: _empty_holder_coroutine()),
        patch.object(analytics_api, "_build_wide_returns", build_wide_returns),
    ):
        return await analytics_api.get_risk_contribution(tickers="AAA,BBB,CCC", db=session, data_service=object())


async def _empty_holder_coroutine() -> dict[str, Any]:
    return {}


async def audit() -> None:
    emit("PORTFOLIO/CORRELATION QUANT EVIDENCE")
    emit("mode=deterministic; seed=20260923; no network; no backend writes")
    emit()
    emit("ENVIRONMENT")
    emit(f"python={sys.version.split()[0]}")
    emit(f"executable={sys.executable}")
    package_names = [
        "numpy",
        "pandas",
        "scipy",
        "statsmodels",
        "quantstats",
        "arch",
        "cvxpy",
        "clarabel",
        "osqp",
        "scs",
        "scikit-learn",
        "hmmlearn",
        "quantlib",
        "riskfolio-lib",
        "PyPortfolioOpt",
    ]
    installed = {distribution.metadata["Name"].lower(): distribution.version for distribution in metadata.distributions() if distribution.metadata.get("Name")}
    inventory: dict[str, str] = {}
    for name in package_names:
        inventory[name] = installed.get(name.lower(), "NOT_INSTALLED")
        emit(f"package.{name}={inventory[name]}")
    import cvxpy as cp

    emit(f"cvxpy.installed_solvers={','.join(cp.installed_solvers())}")
    emit()

    returns = synthetic_returns()
    prices = prices_from_returns(returns)
    weights = {column: 1.0 / len(returns.columns) for column in returns.columns}
    engine = AnalyticsEngine()

    emit("MODEL: portfolio return construction and covariance annualization")
    aligned_backend = engine._calculate_portfolio_returns(returns, weights)
    aligned_reference = returns @ pd.Series(weights)
    record(
        "portfolio_return_construction",
        "aligned_daily_returns",
        aligned_backend.to_numpy(),
        aligned_reference.to_numpy(),
        1e-14,
        1e-13,
        "MATCHES",
        "none",
        "numpy/pandas dot product",
        "Identically dated, finite input.",
    )
    covariance_backend = returns.cov().to_numpy() * TRADING_DAYS
    covariance_reference = np.cov(returns.to_numpy(), rowvar=False, ddof=1) * TRADING_DAYS
    record(
        "portfolio_return_construction",
        "annualized_covariance",
        covariance_backend,
        covariance_reference,
        1e-15,
        1e-12,
        "MATCHES",
        "none",
        "numpy.cov(ddof=1) x 252",
        "Sample covariance assumes synchronized finite daily returns.",
    )
    staggered = prices.copy()
    staggered.iloc[:120, staggered.columns.get_loc("BBB")] = np.nan
    staggered_metrics = await engine.calculate_portfolio_metrics(staggered, weights)
    first_valid = max(pd.to_datetime(staggered[column].first_valid_index()) for column in staggered)
    active_prices = staggered.loc[first_valid:].ffill().dropna()
    active_returns = active_prices.pct_change(fill_method=None).dropna()
    active_portfolio = active_returns @ pd.Series(weights)
    reference_annual = float(active_portfolio.mean() * TRADING_DAYS)
    reference_vol = float(active_portfolio.std(ddof=1) * math.sqrt(TRADING_DAYS))
    record(
        "portfolio_return_construction",
        "prelisting_annual_return",
        staggered_metrics["annual_return"],
        reference_annual,
        1e-12,
        1e-12,
        "BUG (wrong math)",
        "high",
        "active-history common-start reference",
        "Backend bfill creates a non-null pre-listing price and 0% returns; active-history reference starts at latest first valid date.",
    )
    record(
        "portfolio_return_construction",
        "prelisting_annual_volatility",
        staggered_metrics["annual_volatility"],
        reference_vol,
        1e-12,
        1e-12,
        "BUG (wrong math)",
        "high",
        "active-history common-start reference",
        "Zero-dilution of an unlisted constituent changes portfolio moments and correlations.",
    )
    raw_case(
        "portfolio_return_construction.edges",
        {
            "missing_price_rows": int(staggered.isna().any(axis=1).sum()),
            "one_asset_return_sum": float(engine._calculate_portfolio_returns(returns[["AAA"]], {"AAA": 1.0}).sum()),
            "nan_after_active_start": int(active_returns.isna().sum().sum()),
        },
    )
    emit()

    emit("MODEL: realized annual return, volatility, Sharpe, Sortino, hit ratio")
    first_loss = pd.Series([-0.10] + [0.02] * 299, index=pd.bdate_range("2024-01-02", periods=300))
    basic = engine._calculate_basic_metrics(first_loss)
    target = engine.risk_free_rate / TRADING_DAYS
    reference_annual = float(first_loss.mean() * TRADING_DAYS)
    reference_volatility = float(first_loss.std(ddof=1) * math.sqrt(TRADING_DAYS))
    reference_sharpe = (reference_annual - engine.risk_free_rate) / reference_volatility
    downside = np.minimum(0.0, first_loss.to_numpy() - target)
    downside_deviation = float(np.sqrt(np.mean(downside**2)) * math.sqrt(TRADING_DAYS))
    reference_sortino = (reference_annual - engine.risk_free_rate) / downside_deviation
    for metric, backend, reference in [
        ("annual_return", basic["annual_return"], reference_annual),
        ("annual_volatility", basic["annual_volatility"], reference_volatility),
        ("sharpe_ratio", basic["sharpe_ratio"], reference_sharpe),
        ("sortino_ratio", basic["sortino_ratio"], reference_sortino),
        ("hit_ratio", basic["hit_ratio"], float((first_loss > 0).mean())),
    ]:
        record(
            "realized_basic_metrics",
            metric,
            backend,
            reference,
            1e-12,
            1e-12,
            "MATCHES",
            "none",
            "transparent annualized/MAR formula",
            "Annual return is arithmetic mean x 252; volatility uses sample standard deviation x sqrt(252).",
        )
    emit()

    emit("MODEL: historical VaR/CVaR and drawdown")
    risk = engine._calculate_risk_metrics(first_loss)
    reference_var = float(np.percentile(first_loss, 5))
    reference_cvar = float(first_loss[first_loss <= reference_var].mean())
    record(
        "historical_var_cvar",
        "var_95",
        risk["var_95"],
        reference_var,
        1e-12,
        1e-12,
        "MATCHES",
        "none",
        "numpy.percentile linear quantile",
        "Returns are reported as negative numbers; 5th percentile is 95% one-sided VaR.",
    )
    record(
        "historical_var_cvar",
        "cvar_95",
        risk["cvar_95"],
        reference_cvar,
        1e-12,
        1e-12,
        "MATCHES",
        "none",
        "conditional empirical mean",
        "Tail includes all observations equal to the empirical VaR quantile.",
    )
    drawdown = engine._calculate_drawdown_metrics(first_loss)
    reference_drawdown = drawdown_with_baseline(first_loss)
    record(
        "drawdown_baseline",
        "max_drawdown",
        drawdown["max_drawdown"],
        reference_drawdown,
        1e-12,
        1e-12,
        "BUG (wrong math)",
        "high",
        "wealth path initialized at 1.0",
        "A negative first return is omitted from the running peak because the backend starts wealth at 1+r0 rather than initial wealth 1.",
    )
    raw_case(
        "drawdown_baseline.edges",
        {
            "first_return": float(first_loss.iloc[0]),
            "backend_terminal_wealth": float((1.0 + first_loss).prod()),
            "reference_terminal_wealth": float((1.0 + first_loss).prod()),
        },
    )
    emit()

    emit("MODEL: quantstats-backed tear sheet, beta/alpha, and monthly compounding")
    benchmark_returns = pd.Series(
        0.0002 + 0.45 * returns["AAA"] + 0.25 * returns["BBB"] + np.random.default_rng(91).normal(0.0, 0.002, len(returns)),
        index=returns.index,
    )
    portfolio_returns = returns @ pd.Series(weights)
    tear_sheet = await invoke_tear_sheet(returns, portfolio_returns, benchmark_returns)
    total_return = float((1.0 + portfolio_returns).prod() - 1.0)
    cagr = float(abs(total_return + 1.0) ** (TRADING_DAYS / len(portfolio_returns)) - 1.0)
    daily_risk_free = (1.0 + 0.02) ** (1.0 / TRADING_DAYS) - 1.0
    excess = portfolio_returns - daily_risk_free
    qs_sharpe = float(excess.mean() / excess.std(ddof=1) * math.sqrt(TRADING_DAYS))
    qs_downside = np.minimum(0.0, excess.to_numpy())
    qs_downside_deviation = float(np.sqrt((qs_downside[qs_downside < 0.0] ** 2).sum() / len(portfolio_returns)))
    qs_sortino = float(excess.mean() / qs_downside_deviation * math.sqrt(TRADING_DAYS))
    reference_qs_drawdown = drawdown_with_baseline(portfolio_returns)
    qs_calmar = cagr / abs(reference_qs_drawdown)
    omega_numerator = float(portfolio_returns[portfolio_returns > 0.0].sum())
    omega_denominator = float(-portfolio_returns[portfolio_returns < 0.0].sum())
    qs_references = {
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": qs_sharpe,
        "sortino": qs_sortino,
        "calmar": qs_calmar,
        "omega": omega_numerator / omega_denominator,
        "tail_ratio": abs(float(portfolio_returns.quantile(0.95) / portfolio_returns.quantile(0.05))),
        "volatility": float(portfolio_returns.std(ddof=1) * math.sqrt(TRADING_DAYS)),
        "max_drawdown": reference_qs_drawdown,
        "skew": float(portfolio_returns.skew()),
        "kurtosis": float(portfolio_returns.kurtosis()),
    }
    for metric, reference in qs_references.items():
        record(
            "quantstats_tear_sheet",
            metric,
            tear_sheet["metrics"][metric],
            reference,
            5.1e-7,
            1e-10,
            "MATCHES",
            "none",
            "quantstats 0.0.81 installed-source formula",
            "Backend delegates this metric to installed quantstats and rounds to six decimals.",
        )
    aligned_portfolio = portfolio_returns
    aligned_benchmark = benchmark_returns.loc[aligned_portfolio.index]
    beta_reference = float(aligned_portfolio.cov(aligned_benchmark) / aligned_benchmark.var())
    alpha_reference = float((aligned_portfolio.mean() - beta_reference * aligned_benchmark.mean()) * TRADING_DAYS)
    record(
        "benchmark_beta_alpha",
        "beta",
        tear_sheet["relative_vs_nifty"]["beta_vs_nifty"],
        beta_reference,
        5.1e-5,
        1e-10,
        "MATCHES",
        "none",
        "sample covariance/variance",
        "Backend intersects dates before computing beta.",
    )
    record(
        "benchmark_beta_alpha",
        "annualized_alpha",
        tear_sheet["relative_vs_nifty"]["alpha_annualized"],
        alpha_reference,
        5.1e-5,
        1e-10,
        "MATCHES",
        "none",
        "OLS alpha x 252",
        "Alpha is daily intercept arithmetic annualized by 252.",
    )
    factor_backend = await engine.factor_exposure_analysis(prices, benchmark_returns, weights)
    factor_returns = prices.sort_index().pct_change(fill_method=None).iloc[1:]
    factor_benchmark = benchmark_returns.loc[factor_returns.index]
    factor_position_reference = sm.OLS(factor_returns["AAA"].to_numpy(), sm.add_constant(factor_benchmark.to_numpy())).fit()
    factor_portfolio_returns = factor_returns @ pd.Series(weights)
    factor_portfolio_reference = sm.OLS(factor_portfolio_returns.to_numpy(), sm.add_constant(factor_benchmark.to_numpy())).fit()
    for metric, backend, reference, tolerance in [
        ("position_beta", factor_backend["positions"]["AAA"]["market"], factor_position_reference.params[1], 5.1e-5),
        ("position_alpha", factor_backend["positions"]["AAA"]["alpha"], factor_position_reference.params[0], 5.1e-7),
        ("portfolio_r_squared", factor_backend["r_squared"], factor_portfolio_reference.rsquared, 5.1e-5),
    ]:
        record(
            "factor_exposure_ols",
            metric,
            backend,
            reference,
            tolerance,
            1e-10,
            "MATCHES",
            "none",
            "statsmodels OLS point estimates",
            "Backend uses active non-NaN dates and HAC covariance for inference; point estimates match OLS.",
        )
    monthly_reference = (1.0 + portfolio_returns).groupby([portfolio_returns.index.year, portfolio_returns.index.month]).prod() - 1.0
    monthly_backend = [
        float(tear_sheet["monthly_returns"][year][month])
        for year in sorted(tear_sheet["monthly_returns"])
        for month in sorted(tear_sheet["monthly_returns"][year], key=lambda value: int(value))
    ]
    record(
        "monthly_compounding",
        "all_months_chronological",
        monthly_backend,
        monthly_reference.sort_index().tolist(),
        5.1e-7,
        1e-10,
        "MATCHES",
        "none",
        "(1+r).groupby([year,month]).prod()-1",
        "Geometric, not arithmetic, monthly compounding.",
    )
    source_text = inspect.getsource(analytics_api.get_tear_sheet).lower()
    raw_case(
        "tracking_error_information_ratio.inventory",
        {
            "tracking_error_occurrences": source_text.count("tracking_error"),
            "information_ratio_occurrences": source_text.count("information_ratio"),
            "relative_metric_fields_emitted": 6,
        },
    )
    emit()

    emit("MODEL: rolling pairwise correlation and regime thresholds")
    rolling_returns = synthetic_returns(150, seed=144).rename(columns=lambda value: f"R{value}")
    rolling_returns.iloc[20, 1] = np.nan
    rolling_returns.iloc[70, 1] = np.nan
    rolling_backend = compute_rolling_avg_correlation(rolling_returns, window_days=30)
    rolling_reference = rolling_pair_reference(rolling_returns, 30, 30)
    record(
        "rolling_correlation",
        "series_max_abs_error",
        rolling_backend.to_numpy(),
        rolling_reference.reindex(rolling_backend.index).to_numpy(),
        1e-13,
        1e-12,
        "MATCHES",
        "none",
        "independent pairwise numpy Pearson loop",
        "Pairwise finite overlap and skip-NaN averaging match.",
    )
    stability = analyze_correlation_stability(rolling_returns, window_days=30)
    current = float(rolling_reference.iloc[-1])
    raw_case(
        "rolling_correlation.edges",
        {
            "backend_current_rounded": stability.current_avg_correlation,
            "reference_current": current,
            "missing_B_rows": int(rolling_returns["RBBB"].isna().sum()),
            "single_asset_error": "ValueError" if _raises(lambda: compute_rolling_avg_correlation(rolling_returns[["RAAA"]], 30)) else "not_raised",
            "constant_pair_error": "ValueError" if _raises(lambda: compute_rolling_avg_correlation(pd.DataFrame({"A": [0.01] * 100, "B": [0.01] * 100}), 30)) else "not_raised",
        },
    )
    record(
        "rolling_correlation",
        "p90_threshold",
        stability.historical_threshold_90th,
        float(np.percentile(rolling_reference.to_numpy(), 90)),
        5.1e-5,
        1e-10,
        "MATCHES",
        "none",
        "numpy.percentile",
        "Thresholds use the realized rolling-series distribution, including the current point.",
    )
    emit()

    emit("MODEL: cointegration, OLS hedge ratio, OU, and spread z-score")
    rng = np.random.default_rng(222)
    dates = pd.bdate_range("2023-01-02", periods=420)
    price_a_values = 100.0 + np.cumsum(rng.normal(0.03, 0.75, len(dates)))
    stationary_noise = np.zeros(len(dates))
    for index in range(1, len(dates)):
        stationary_noise[index] = 0.55 * stationary_noise[index - 1] + rng.normal(0.0, 0.55)
    price_b_values = 1.7 * price_a_values + 4.0 + stationary_noise
    series_a = pd.Series(price_a_values, index=dates)
    series_b = pd.Series(price_b_values, index=dates)
    series_b = series_b.drop(dates[::29])
    series_b.iloc[100] = np.nan
    pair = analyze_pair_cointegration("AAA", "BBB", series_a, series_b, include_spread_series=True)
    aligned = pd.DataFrame({"a": series_a, "b": series_b}).dropna()
    reference_t, reference_p, _ = coint(aligned["a"].to_numpy(), aligned["b"].to_numpy())
    reference_ols = sm.OLS(aligned["a"].to_numpy(), sm.add_constant(aligned["b"].to_numpy())).fit()
    reference_spread = aligned["a"].to_numpy() - (reference_ols.params[0] + reference_ols.params[1] * aligned["b"].to_numpy())
    reference_z = float((reference_spread[-1] - reference_spread.mean()) / reference_spread.std(ddof=1))
    delta = np.diff(reference_spread)
    reference_ou = sm.OLS(delta, sm.add_constant(reference_spread[:-1])).fit()
    gamma = float(reference_ou.params[1])
    reference_theta = float(-math.log(1.0 + gamma))
    reference_half_life = float(math.log(2.0) / reference_theta)
    johansen = coint_johansen(aligned[["a", "b"]].to_numpy(), det_order=0, k_ar_diff=1)
    reference_johansen = bool(float(johansen.lr1[0]) > float(johansen.cvt[0, 1]))
    for metric, backend, reference, tolerance in [
        ("engle_granger_tstat", pair.engle_granger_tstat, reference_t, 5.1e-5),
        ("engle_granger_pvalue", pair.engle_granger_pvalue, reference_p, 5.1e-7),
        ("hedge_ratio_beta", pair.hedge_ratio_beta, reference_ols.params[1], 5.1e-7),
        ("intercept_alpha", pair.intercept_alpha, reference_ols.params[0], 5.1e-5),
        ("current_spread_zscore", pair.current_spread_zscore, reference_z, 5.1e-5),
        ("ou_reversion_speed_theta", pair.ou_reversion_speed_theta, reference_theta, 5.1e-7),
        ("ou_half_life_days", pair.ou_half_life_days, reference_half_life, 5.1e-3),
        ("johansen_cointegrated", float(pair.johansen_cointegrated), float(reference_johansen), 0.0),
    ]:
        record(
            "pairs_statistics",
            metric,
            backend,
            reference,
            tolerance,
            1e-10,
            "MATCHES",
            "none",
            "statsmodels 0.15.0",
            "Misaligned dates are inner-joined before testing; levels are tested directly.",
        )
    random_walk = 50.0 + np.cumsum(rng.normal(0.0, 1.0, len(dates)))
    non_coint = analyze_pair_cointegration("AAA", "CCC", series_a, pd.Series(random_walk, index=dates))
    raw_case(
        "pairs_statistics.edges",
        {
            "aligned_rows": len(aligned),
            "input_B_missing": int(series_b.isna().sum()),
            "noncointegrated_pvalue": non_coint.engle_granger_pvalue,
            "constant_spread_ou_theta": compute_ou_parameters(np.ones(20))[0],
        },
    )
    emit()

    emit("MODEL: HHI, effective N, diversification score, and Gini")
    weights_for_concentration = {"A": 0.6, "B": 0.3, "C": 0.1}
    concentration_skewed = await engine.concentration_analysis(weights_for_concentration)
    hhi_reference = sum(weight**2 for weight in weights_for_concentration.values())
    diversification_reference = (1.0 - hhi_reference) / (1.0 - 1.0 / 3.0) * 100.0
    record(
        "concentration",
        "herfindahl_index",
        concentration_skewed["herfindahl_index"],
        hhi_reference,
        5.1e-5,
        1e-10,
        "MATCHES",
        "none",
        "sum(w^2)",
        "Positive normalized weights.",
    )
    record(
        "concentration",
        "effective_positions",
        concentration_skewed["effective_positions"],
        1.0 / hhi_reference,
        5.1e-3,
        1e-10,
        "MATCHES",
        "none",
        "1/HHI",
        "Positive normalized weights.",
    )
    record(
        "concentration",
        "diversification_score",
        concentration_skewed["diversification_score"],
        diversification_reference,
        5.1e-2,
        1e-10,
        "MATCHES",
        "none",
        "(1-HHI)/(1-1/N) x 100",
        "Positive normalized weights with N=3.",
    )
    sorted_weights = np.sort(np.array(list(weights_for_concentration.values())))
    gini_reference = float(
        (2.0 * np.sum(np.arange(1, len(sorted_weights) + 1) * sorted_weights) - (len(sorted_weights) + 1) * sorted_weights.sum())
        / len(sorted_weights)
    )
    record(
        "concentration",
        "gini_coefficient",
        concentration_skewed["gini_coefficient"],
        gini_reference,
        5.1e-4,
        1e-9,
        "MATCHES",
        "none",
        "Lorenz Gini finite-sum formula",
        "Positive normalized weights summing to one.",
    )
    single = await engine.concentration_analysis({"ONLY": 1.0})
    equal = await engine.concentration_analysis({f"E{index}": 0.25 for index in range(4)})
    zero_weight = await engine.concentration_analysis({f"A{index}": 0.25 for index in range(4)} | {"ZERO": 0.0})
    record(
        "concentration",
        "single_holding_diversification",
        single["diversification_score"],
        0.0,
        0.0,
        0.0,
        "MATCHES",
        "none",
        "mandatory invariant",
        "One holding must render exactly 0%.",
    )
    record(
        "concentration",
        "equal_active_diversification_with_zero_row",
        zero_weight["diversification_score"],
        equal["diversification_score"],
        1e-12,
        1e-12,
        "DIVERGES (magnitude)",
        "none",
        "active-holdings N=4 reference",
        "A zero-weight rebalance target is accepted, but concentration counts the zero row in theoretical N.",
    )
    negative_rejected = 0
    try:
        PortfolioPositionCreate(ticker="AAA.NS", weight=-0.1, quantity=1.0, buy_price=100.0)
    except Exception:
        negative_rejected = 1
    record(
        "weight_validation",
        "negative_new_position_rejected",
        negative_rejected,
        1.0,
        0.0,
        0.0,
        "MATCHES",
        "none",
        "Pydantic gt=0 trust boundary",
        "Negative weights are not accepted for create/update schema paths.",
    )
    zero_payload = RebalancePayload(new_weights={"AAA": 0.0}, dry_run=True)
    record(
        "weight_validation",
        "zero_rebalance_target_accepted",
        float("AAA" in zero_payload.new_weights),
        1.0,
        0.0,
        0.0,
        "MATCHES",
        "none",
        "rebalance check rejects v<0 only",
        "Zero is accepted by rebalance and can leave a zero-weight persisted position.",
    )
    emit()

    emit("MODEL: zero-state portfolio weight and single-holding allocation")
    initial_request = PortfolioPositionCreate(
        ticker="AAA.NS",
        weight=0.20,
        quantity=1.0,
        buy_price=100.0,
        added_on=pd.Timestamp("2026-09-20").date(),
    )
    initial_db = FakeSession()
    initial_result = await add_portfolio_position(
        initial_request,
        currency="INR",
        db=initial_db,
        data_service=QuoteService(100.0),
    )
    record(
        "zero_state_portfolio_weight",
        "initial_add_weight",
        initial_result.weight,
        1.0,
        1e-12,
        1e-12,
        "BUG (wrong math)",
        "high",
        "mandatory empty-portfolio invariant",
        "Single-position add stores the client weight verbatim; it does not force 100% on an empty book.",
    )
    zero_value_position = PortfolioPosition(
        id=1,
        ticker="AAA.NS",
        weight=0.20,
        quantity=1.0,
        buy_price=100.0,
        last_price=0.0,
        market_value=0.0,
        region="IN",
        sector="Equity",
        industry="Test",
        added_on=pd.Timestamp("2026-09-20").to_pydatetime(),
    )
    zero_value_summary = await get_portfolio(
        region=None,
        sector=None,
        currency="INR",
        force_refresh=False,
        db=FakeSession([zero_value_position]),
        data_service=QuoteService(None),
    )
    record(
        "zero_state_portfolio_weight",
        "zero_total_value_single_position_weight",
        zero_value_summary.positions[0].weight,
        1.0,
        1e-12,
        1e-12,
        "BUG (wrong math)",
        "high",
        "mandatory total_value=0 invariant",
        "Live-weight fallback preserves the stored 20% instead of assigning 100% to the sole holding.",
    )
    one_asset_returns = returns[["AAA"]]
    one_asset_optimization = optimize(one_asset_returns, strategy="min_vol", risk_free_rate=0.02)
    record(
        "zero_state_portfolio_weight",
        "single_holding_optimizer_weight",
        one_asset_optimization["weights"]["AAA"],
        1.0,
        0.0,
        0.0,
        "MATCHES",
        "none",
        "simplex normalization",
        "One active asset receives 100%.",
    )
    emit()

    emit("MODEL: inverse-volatility risk parity, covariance risk, and target scaling")
    parity_prices = prices.copy()
    parity_result = await engine.volatility_sizing(
        parity_prices,
        {"AAA": 0.5, "BBB": 0.3, "CCC": 0.2},
        model="EWMA",
        target_volatility=0.10,
        portfolio_value=100_000.0,
    )
    backend_weights = np.array([parity_result["recommended_weights"][column] for column in returns.columns])
    weight_sum = float(backend_weights.sum())
    backend_normalized = backend_weights / weight_sum
    parity_volatilities = np.array([parity_result["volatilities"][column] for column in returns.columns])
    reference_parity = (1.0 / parity_volatilities) / np.sum(1.0 / parity_volatilities)
    record(
        "inverse_volatility_risk_parity",
        "normalized_weights",
        backend_normalized,
        reference_parity,
        2e-6,
        1e-8,
        "MATCHES",
        "none",
        "w proportional to 1/sigma",
        "Target scaling is removed before comparing ratios; positive estimated volatilities.",
    )
    record(
        "inverse_volatility_risk_parity",
        "achieved_target_volatility",
        parity_result["achieved_volatility"],
        0.10,
        1e-6,
        1e-6,
        "MATCHES",
        "none",
        "scale=target/sigma_p",
        "Cash receives the unlevered remainder.",
    )
    parity_returns = parity_prices.pct_change(fill_method=None).iloc[1:]
    daily_model_volatilities = np.array(
        [parity_result["volatilities"][column] / math.sqrt(TRADING_DAYS) for column in returns.columns]
    )
    backend_covariance = parity_returns.corr().to_numpy() * np.outer(
        daily_model_volatilities,
        daily_model_volatilities,
    )
    current_weights = np.array([0.5, 0.3, 0.2])
    reference_current_vol = math.sqrt(max(0.0, float(current_weights @ backend_covariance @ current_weights)) * TRADING_DAYS)
    record(
        "inverse_volatility_risk_parity",
        "current_portfolio_volatility",
        parity_result["current_volatility"],
        reference_current_vol,
        2e-6,
        1e-8,
        "MATCHES",
        "none",
        "sqrt(w' (D R D) w x 252)",
        "Covariance is rebuilt from modeled volatilities and empirical correlations.",
    )
    zero_vol_prices = parity_prices.copy()
    zero_vol_prices["AAA"] = 100.0
    zero_vol_result = await engine.volatility_sizing(
        zero_vol_prices,
        {"AAA": 0.5, "BBB": 0.5},
        model="EWMA",
        target_volatility=0.10,
        portfolio_value=100_000.0,
    )
    zero_vol_true = np.array([0.0, zero_vol_result["volatilities"]["BBB"]])
    zero_vol_normalized = np.array([zero_vol_result["recommended_weights"][column] for column in ["AAA", "BBB"]])
    zero_vol_normalized /= zero_vol_normalized.sum()
    epsilon_reference = 1.0 / np.maximum(zero_vol_true, 1e-12)
    epsilon_reference /= epsilon_reference.sum()
    record(
        "inverse_volatility_risk_parity",
        "zero_volatility_normalized_weights",
        zero_vol_normalized,
        epsilon_reference,
        1e-12,
        1e-12,
        "DIVERGES (magnitude)",
        "none",
        "true inverse-vol with epsilon=1e-12",
        "A 5% volatility floor regularizes zero volatility away from 1/sigma; backend remains finite.",
    )
    emit()

    emit("MODEL: HRP, minimum variance, maximum Sharpe, minimum CVaR, Black-Litterman")
    optimization_returns = synthetic_returns(300, seed=303)
    optimization_mu = optimization_returns.mean().to_numpy() * TRADING_DAYS
    optimization_cov = optimization_returns.cov().to_numpy() * TRADING_DAYS
    risk_free = 0.02
    hrp_backend = _hrp_weights(optimization_returns).to_numpy()
    reference_hrp = hrp_reference(optimization_returns)
    record(
        "hrp",
        "weights",
        hrp_backend,
        reference_hrp,
        1e-12,
        1e-11,
        "MATCHES",
        "none",
        "canonical Lopez de Prado/SciPy reference",
        "Pearson distance, single linkage, recursive bisection, and cluster IVP variance.",
    )
    min_vol_backend = _min_vol(optimization_cov)
    min_vol_result = minimize(
        lambda values: float(values @ optimization_cov @ values),
        np.full(len(optimization_returns.columns), 1.0 / len(optimization_returns.columns)),
        method="SLSQP",
        bounds=[(0.0, None)] * len(optimization_returns.columns),
        constraints={"type": "eq", "fun": lambda values: float(values.sum() - 1.0)},
        options={"ftol": 1e-14, "maxiter": 3000},
    )
    assert min_vol_result.success
    record(
        "minimum_variance",
        "weights",
        min_vol_backend,
        min_vol_result.x,
        2e-6,
        1e-7,
        "MATCHES",
        "none",
        "SciPy SLSQP independent solve",
        "Long-only, fully invested sample-covariance program.",
    )
    max_sharpe_backend = _max_sharpe(optimization_mu, optimization_cov, risk_free)
    max_sharpe_reference = tangency_reference(optimization_mu - risk_free, optimization_cov)
    record(
        "maximum_sharpe",
        "weights",
        max_sharpe_backend,
        max_sharpe_reference,
        5e-5,
        2e-5,
        "MATCHES",
        "none",
        "SciPy SLSQP homogenized tangency",
        "Positive excess-return normalization; non-unique only for degenerate covariance.",
    )
    cvar_backend = _min_cvar(optimization_returns, beta=0.95)
    cvar_reference, reference_cvar_value = linprog_cvar_reference(optimization_returns, beta=0.95)
    backend_losses = -(optimization_returns.to_numpy() @ cvar_backend)
    reference_losses = -(optimization_returns.to_numpy() @ cvar_reference)
    beta_value = 0.95
    alpha_scale = 1.0 / ((1.0 - beta_value) * len(optimization_returns))
    candidates = np.unique(np.concatenate([backend_losses, reference_losses]))
    backend_candidates = [
        float(alpha + alpha_scale * np.maximum(backend_losses - alpha, 0.0).sum())
        for alpha in candidates
    ]
    backend_cvar_value = min(backend_candidates)
    record(
        "minimum_cvar",
        "weights",
        cvar_backend,
        cvar_reference,
        2e-6,
        1e-7,
        "MATCHES",
        "none",
        "SciPy HiGHS linear program",
        "Empirical CVaR can have multiple minimizers; these independently solved weights agree within tolerance.",
    )
    record(
        "minimum_cvar",
        "optimized_cvar_95",
        backend_cvar_value,
        reference_cvar_value,
        1e-10,
        1e-9,
        "MATCHES",
        "none",
        "Rockafellar-Uryasev objective",
        "Clarabel and HiGHS can select different empirical-tail minimizers with the same optimized CVaR.",
    )
    views = {"AAA": 0.25, "BBB": 0.12}
    bl_backend = optimize(
        optimization_returns,
        strategy="black_litterman",
        risk_free_rate=risk_free,
        views=views,
    )["weights"]
    market = np.full(len(optimization_returns.columns), 1.0 / len(optimization_returns.columns))
    delta_value = 2.5
    tau = 0.05
    prior = delta_value * (optimization_cov @ market)
    pick = np.zeros((2, len(optimization_returns.columns)))
    pick[0, list(optimization_returns.columns).index("AAA")] = 1.0
    pick[1, list(optimization_returns.columns).index("BBB")] = 1.0
    query = np.array([0.25, 0.12])
    tau_cov = tau * optimization_cov
    omega = np.diag(np.clip(np.diag(pick @ tau_cov @ pick.T), 1e-6, None))
    inverse_inner = np.linalg.pinv(pick @ tau_cov @ pick.T + omega)
    posterior = prior + tau_cov @ pick.T @ inverse_inner @ (query - pick @ prior)
    posterior_cov = (1.0 + tau) * optimization_cov - (tau**2) * (optimization_cov @ pick.T @ inverse_inner @ pick @ optimization_cov)
    bl_reference = tangency_reference(posterior - risk_free, posterior_cov)
    bl_reference_values = np.array([bl_backend[column] for column in optimization_returns.columns])
    record(
        "black_litterman",
        "weights",
        bl_reference_values,
        bl_reference,
        1e-5,
        2e-5,
        "MATCHES",
        "none",
        "transparent BL posterior + SciPy tangency",
        "Equal-weight market prior, He-Litterman diagonal Omega, long-only tangency.",
    )
    raw_case(
        "optimization.edges",
        {
            "one_asset_weight": float(optimize(optimization_returns[["AAA"]], "min_vol")["weights"]["AAA"]),
            "all_negative_excess_raises": _raises(lambda: _max_sharpe(np.array([-0.01, -0.02]), np.eye(2) * 0.04, 0.02)),
            "zero_variance_minvol_sum": float(_min_vol(np.eye(1) * 0.0).sum()),
        },
    )
    emit()

    emit("MODEL: volatility and Euler/tail risk contribution")
    contribution = await invoke_risk_contribution(returns, portfolio_returns, weights)
    reference_covariance = returns.cov().to_numpy() * TRADING_DAYS
    weight_vector = np.array([weights[column] for column in returns.columns])
    reference_sigma = math.sqrt(max(0.0, float(weight_vector @ reference_covariance @ weight_vector)))
    reference_vol_contribution = weight_vector * (reference_covariance @ weight_vector) / reference_sigma
    reference_vol_contribution /= reference_vol_contribution.sum()
    backend_vol_contribution = np.array([contribution["positions"]["volatility"][column] for column in returns.columns])
    record(
        "volatility_risk_contribution",
        "weights",
        backend_vol_contribution,
        reference_vol_contribution,
        5.1e-7,
        1e-9,
        "MATCHES",
        "none",
        "Euler w_i(Sigma w)_i/sigma_p",
        "Contributions sum to one for positive weights.",
    )
    tail_cut = float(np.percentile(portfolio_returns, 5))
    tail_mask = portfolio_returns <= tail_cut
    reference_cvar_components = np.array(
        [float(returns.loc[tail_mask, column].fillna(0.0).mean()) * weights[column] for column in returns.columns]
    )
    reference_cvar_components = -reference_cvar_components / np.sum(np.abs(reference_cvar_components))
    backend_cvar_contribution = np.array([contribution["positions"]["cvar_tail"][column] for column in returns.columns])
    record(
        "cvar_risk_contribution",
        "weights",
        backend_cvar_contribution,
        reference_cvar_components,
        5.1e-7,
        1e-9,
        "MATCHES",
        "none",
        "weighted conditional tail mean",
        "Tail is fixed by the portfolio's empirical 5th percentile.",
    )
    record(
        "volatility_risk_contribution",
        "portfolio_annualized_volatility",
        contribution["portfolio_volatility_annualized"],
        reference_sigma,
        5.1e-5,
        1e-9,
        "MATCHES",
        "none",
        "sqrt(w' Sigma_252 w)",
        "Daily covariance is annualized by 252.",
    )
    emit()

    emit("MODEL: rolling realized volatility, EWMA, and volatility cone")
    realized_backend = VolatilityService.calculate_rolling_realized_volatility(portfolio_returns, window=21)
    rolling_reference = portfolio_returns.rolling(21, min_periods=21).std(ddof=1) * math.sqrt(TRADING_DAYS)
    rolling_reference = rolling_reference.dropna()
    record(
        "rolling_realized_volatility",
        "series",
        realized_backend.to_numpy(),
        rolling_reference.reindex(realized_backend.index).to_numpy(),
        1e-14,
        1e-13,
        "MATCHES",
        "none",
        "pandas sample rolling std x sqrt(252)",
        "Same ddof=1 convention.",
    )
    ewma_backend = VolatilityService.calculate_ewma_volatility(portfolio_returns, decay=0.94)
    values = portfolio_returns.to_numpy(dtype=float)
    weights_ewma = (1.0 - 0.94) * (0.94 ** np.arange(len(values))[::-1])
    weights_ewma /= weights_ewma.sum()
    ewma_reference = math.sqrt(max(0.0, float(np.sum(weights_ewma * values**2)))) * math.sqrt(TRADING_DAYS)
    record(
        "ewma_volatility",
        "annualized_value",
        ewma_backend,
        ewma_reference,
        1e-14,
        1e-13,
        "MATCHES",
        "none",
        "normalized exponential weights",
        "Zero-mean RiskMetrics-style second moment.",
    )
    engine_ewma = engine._ewma_forecast(portfolio_returns, horizon=5)
    engine_ewma_values = portfolio_returns.replace([np.inf, -np.inf], np.nan).dropna().clip(-0.20, 0.20).to_numpy()
    engine_ewma_variance = float(np.var(engine_ewma_values))
    for value in engine_ewma_values[-min(len(engine_ewma_values), 60) :]:
        engine_ewma_variance = 0.94 * engine_ewma_variance + 0.06 * value * value
    engine_ewma_reference = float(np.clip(math.sqrt(engine_ewma_variance * TRADING_DAYS), 0.05, 1.20))
    record(
        "analytics_engine_ewma",
        "annualized_forecast",
        engine_ewma["volatility_forecast"],
        engine_ewma_reference,
        1e-14,
        1e-13,
        "MATCHES",
        "none",
        "RiskMetrics single-pass recursion",
        "Population full-sample variance seeds 60 recursions; forecast is clipped and flat across horizons.",
    )
    cone = VolatilityService.calculate_volatility_cone(portfolio_returns, windows=[21, 63], forecast_model="EWMA")
    record(
        "volatility_cone",
        "window21_median",
        cone["windows"][0]["median"],
        float(np.median(realized_backend.to_numpy())),
        5.1e-5,
        1e-9,
        "MATCHES",
        "none",
        "numpy.median",
        "Forecast overlay is separate from realized quantile bands.",
    )
    raw_case(
        "volatility.edges",
        {
            "empty_ewma_raises": _raises(lambda: VolatilityService.calculate_ewma_volatility(pd.Series(dtype=float))),
            "single_return_ewma": VolatilityService.calculate_ewma_volatility(pd.Series([0.05])),
            "window_beyond_history_median": VolatilityService.calculate_volatility_cone(portfolio_returns.iloc[:15], windows=[21], forecast_model="EWMA")["windows"][0]["median"],
        },
    )
    emit()

    emit("MODEL: GARCH/EGARCH horizon VaR and CVaR")
    forecast_returns = portfolio_returns.copy()
    clipped = forecast_returns.clip(-0.20, 0.20)
    scaled = clipped * 100.0
    garch_reference_fit = arch_model(scaled, vol="Garch", p=1, q=1, dist="normal", rescale=False).fit(
        disp="off", show_warning=False, options={"maxiter": 100}
    )
    garch_reference_variance = garch_reference_fit.forecast(horizon=5, method="analytic").variance.values[-1, :]
    horizon_vol_reference = math.sqrt(float(garch_reference_variance[-1]) * TRADING_DAYS) / 100.0
    # arch reports cumulative h-day variance in percent-squared units.  The
    # backend's annualization makes this an annualized cumulative volatility;
    # convert it back to return-space h-day volatility before normal-tail
    # scaling.  The backend's extra sqrt(h/252) is the defect under test.
    return_space_horizon_vol = horizon_vol_reference / math.sqrt(TRADING_DAYS)
    var_reference = -return_space_horizon_vol * 1.645
    cvar_reference = -return_space_horizon_vol * 2.06
    garch_backend = await engine._garch_forecast(forecast_returns, horizon=5)
    record(
        "garch_horizon_risk",
        "var_95_5day",
        garch_backend["var_forecast"],
        var_reference,
        1e-12,
        1e-12,
        "BUG (wrong math)",
        "high",
        "arch 8.0 cumulative 5-day variance",
        "Backend annualizes cumulative h-day variance and then multiplies by sqrt(h/252) again.",
    )
    record(
        "garch_horizon_risk",
        "cvar_95_5day",
        garch_backend["cvar_forecast"],
        cvar_reference,
        1e-12,
        1e-12,
        "BUG (wrong math)",
        "high",
        "arch 8.0 cumulative 5-day variance",
        "Same double-horizon scaling as GARCH VaR.",
    )
    garch_one_day = await engine._garch_forecast(forecast_returns, horizon=1)
    record(
        "garch_horizon_risk",
        "var_95_1day_control",
        garch_one_day["var_forecast"],
        -garch_one_day["volatility_forecast"] * 1.645 / math.sqrt(TRADING_DAYS),
        1e-12,
        1e-12,
        "MATCHES",
        "none",
        "one-day normal VaR reference",
        "At h=1, sqrt(h/252) is the required return-space conversion from annualized volatility.",
    )
    egarch_backend = await engine._egarch_forecast(forecast_returns, horizon=5)
    egarch_reference_fit = arch_model(scaled, vol="EGARCH", p=1, q=1, dist="normal", rescale=False).fit(disp="off", show_warning=False)
    egarch_available = 0
    try:
        egarch_reference_fit.forecast(
            horizon=5,
            method="simulation",
            simulations=100,
            random_state=np.random.RandomState(17),
        )
        egarch_available = 1
    except ValueError:
        egarch_available = 0
    record(
        "egarch_horizon_risk",
        "five_day_forecast_available",
        float(egarch_backend.get("var_forecast") is not None),
        float(egarch_available),
        0.0,
        0.0,
        "BUG (wrong math)",
        "medium",
        "arch 8.0 simulation-availability probe",
        "Installed arch can forecast via simulation, but the backend uses unsupported analytic EGARCH for h>1 and returns an error payload.",
    )
    vol_service_garch = VolatilityService.forecast_garch_volatility(forecast_returns, horizon=5)
    vol_service_reference_fit = arch_model(
        forecast_returns.dropna().to_numpy() * 100.0,
        vol="Garch",
        p=1,
        q=1,
        mean="Zero",
        dist="normal",
        rescale=False,
    ).fit(disp="off", show_warning=False)
    vol_service_reference_variance = vol_service_reference_fit.forecast(horizon=5, reindex=False).variance.iloc[-1].to_numpy()
    vol_service_reference = math.sqrt(float(np.mean(vol_service_reference_variance)) * TRADING_DAYS) / 100.0
    record(
        "garch_average_daily_volatility",
        "annualized_value",
        vol_service_garch["annualized_vol"],
        vol_service_reference,
        1e-12,
        1e-11,
        "MATCHES",
        "none",
        "arch 8.0 zero-mean GARCH mean forecast variance",
        "This separate service explicitly averages arch cumulative variances across the horizon.",
    )
    emit()

    emit("MODEL: EVT-POT VaR/ES and Student-t tail dependence")
    heavy_returns = pd.Series(stats.t.rvs(df=3.2, loc=0.0002, scale=0.02, size=1200, random_state=17))
    evt_backend = TailRiskService.calculate_evt_pot_var_es(heavy_returns, 0.99, 0.95)
    losses = -heavy_returns.to_numpy()
    threshold = float(np.percentile(losses, 95.0))
    exceedances = losses[losses > threshold] - threshold
    shape, _, scale = stats.genpareto.fit(exceedances, floc=0.0)
    shape = float(np.clip(shape, -0.5, 0.95))
    ratio = (len(losses) / len(exceedances)) * (1.0 - 0.99)
    if abs(shape) > 1e-6:
        reference_evt_var = threshold + (scale / shape) * (ratio ** (-shape) - 1.0)
    else:
        reference_evt_var = threshold - scale * np.log(ratio)
    reference_evt_es = (reference_evt_var + scale - shape * threshold) / (1.0 - shape)
    record(
        "evt_pot_var_es",
        "var_99",
        evt_backend["evt_pot_var_99"],
        -reference_evt_var,
        1.1e-6,
        1e-9,
        "MATCHES",
        "none",
        "SciPy GPD + empirical exceedance probability",
        "The observed exceedance fraction n_u/n normalizes the 1% tail probability.",
    )
    record(
        "evt_pot_var_es",
        "expected_shortfall_99",
        evt_backend["evt_pot_es_99"],
        -reference_evt_es,
        1.1e-6,
        1e-9,
        "MATCHES",
        "none",
        "GPD conditional-mean formula",
        "Fitted shape is clipped before the analytic formulas.",
    )
    tail_a = returns["AAA"]
    tail_b = 0.65 * tail_a + np.random.default_rng(881).normal(0.0, 0.006, len(tail_a))
    tail_backend = TailRiskService.calculate_bivariate_tail_dependence(tail_a, tail_b)
    aligned_tail = pd.DataFrame({"a": tail_a, "b": tail_b}).dropna()
    rho = float(np.corrcoef(aligned_tail["a"], aligned_tail["b"])[0, 1])
    nu = float(np.clip((stats.t.fit(aligned_tail["a"])[0] + stats.t.fit(aligned_tail["b"])[0]) / 2.0, 2.1, 30.0))
    rho_clip = float(np.clip(rho, -0.9999, 0.9999))
    argument = -math.sqrt(((nu + 1.0) * (1.0 - rho_clip)) / (1.0 + rho_clip))
    tail_reference = float(np.clip(2.0 * stats.t.cdf(argument, df=nu + 1.0), 0.0, 1.0))
    record(
        "student_t_tail_dependence",
        "lambda_lower",
        tail_backend[0],
        tail_reference,
        1e-12,
        1e-10,
        "MATCHES",
        "none",
        "installed Student-t copula formula",
        "The code and reference use averaged marginal t fits; this is an approximation, not a joint copula fit.",
    )
    raw_case(
        "tail_risk.edges",
        {
            "exceedances": int(evt_backend["exceedances_count"]),
            "gpd_fitted": bool(evt_backend["model_fitted"]),
            "tail_pair_overlap": len(aligned_tail),
            "single_asset_matrix": TailRiskService.calculate_tail_dependence_matrix(tail_a.to_frame("A"))["matrix"],
        },
    )
    emit()

    emit("MODEL: walk-forward backtest mechanics")
    backtest_dates = pd.bdate_range("2023-01-02", periods=180)
    backtest_returns = pd.DataFrame(
        {
            "A": np.r_[-0.10, np.linspace(-0.02, 0.02, 179)],
            "B": np.r_[-0.08, np.linspace(0.01, -0.01, 179)],
        },
        index=backtest_dates,
    )
    fixed_weights = {"A": 0.8, "B": 0.2}

    def fixed_optimizer(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"weights": fixed_weights}

    with patch("app.services.backtest_service.optimize", fixed_optimizer):
        backtest = run_walk_forward_backtest(
            backtest_returns,
            strategy="hrp",
            rebalance_freq_days=60,
            lookback_days=60,
            transaction_cost_bps=100.0,
            risk_free_rate=0.02,
        )
    test_values = backtest_returns.iloc[60:].to_numpy() @ np.array([0.8, 0.2])
    reference_daily = test_values.copy()
    turnover_reference = 0.5 * sum(abs(fixed_weights[column] - 1.0 / 2.0) for column in fixed_weights)
    reference_daily[0] = (1.0 - turnover_reference * 0.01) * (1.0 + reference_daily[0]) - 1.0
    reference_wealth = np.cumprod(1.0 + reference_daily)
    reference_bt_cagr = float(reference_wealth[-1] ** (TRADING_DAYS / len(reference_daily)) - 1.0)
    reference_bt_vol = float(reference_daily.std(ddof=1) * math.sqrt(TRADING_DAYS))
    reference_bt_sharpe = (float(reference_daily.mean()) * TRADING_DAYS - 0.02) / reference_bt_vol
    reference_bt_drawdown_series = np.concatenate([[1.0], reference_wealth])
    reference_bt_drawdown = float(np.min(reference_bt_drawdown_series / np.maximum.accumulate(reference_bt_drawdown_series) - 1.0))
    for metric, backend, reference, tolerance in [
        ("cagr", backtest["cagr"], reference_bt_cagr, 5.1e-5),
        ("annualized_volatility", backtest["annualized_volatility"], reference_bt_vol, 5.1e-5),
        ("sharpe_ratio", backtest["sharpe_ratio"], reference_bt_sharpe, 5.1e-5),
        ("first_rebalance_turnover", backtest["rebalance_events"][0]["turnover"], turnover_reference, 5.1e-5),
        ("max_drawdown", backtest["max_drawdown"], reference_bt_drawdown, 1e-12),
    ]:
        verdict = "BUG (wrong math)" if metric == "max_drawdown" else "MATCHES"
        severity = "high" if metric == "max_drawdown" else "none"
        note = "Initial loss is omitted from the backend drawdown peak." if metric == "max_drawdown" else "Walk-forward schedule, one-way turnover, costs, CAGR, volatility, and mean-based Sharpe."
        record(
            "walk_forward_backtest",
            metric,
            backend,
            reference,
            tolerance,
            1e-9,
            verdict,
            severity,
            "independent daily-return replay",
            note,
        )
    raw_case(
        "walk_forward_backtest.edges",
        {
            "oos_days": len(backtest["equity_curve"]),
            "rebalances": backtest["total_rebalances"],
            "total_turnover": backtest["total_turnover"],
            "one_asset_cagr": run_walk_forward_backtest(backtest_returns[["A"]], strategy="equal_weight", lookback_days=60, rebalance_freq_days=60)["cagr"],
        },
    )
    emit()

    emit("MODEL: Monte Carlo GBM, Student-t, and stationary bootstrap")
    mc_returns = portfolio_returns.copy()
    gbm_result = simulate_goal(mc_returns, 100_000.0, 120_000.0, 1.0, "gbm", 200, 771)
    mu_annual = float(mc_returns.mean() * TRADING_DAYS)
    sigma_annual = float(mc_returns.std(ddof=1) * math.sqrt(TRADING_DAYS))
    reference_rng = np.random.default_rng(771)
    shocks = reference_rng.standard_normal((200, TRADING_DAYS))
    drift = (mu_annual - 0.5 * sigma_annual**2) / TRADING_DAYS
    diffusion = sigma_annual / math.sqrt(TRADING_DAYS)
    reference_terminal = 100_000.0 * np.exp(np.sum(drift + diffusion * shocks, axis=1))
    record(
        "monte_carlo_gbm",
        "terminal_median",
        gbm_result["terminal_percentiles"]["p50"],
        float(np.percentile(reference_terminal, 50)),
        0.01,
        1e-9,
        "MATCHES",
        "none",
        "independent lognormal replay with same seed",
        "Arithmetic historical mean is converted to log drift with -0.5 sigma^2.",
    )
    record(
        "monte_carlo_gbm",
        "success_probability",
        gbm_result["prob_success"],
        float(np.mean(reference_terminal >= 120_000.0)),
        0.0001,
        1e-9,
        "MATCHES",
        "none",
        "independent path replay",
        "Same target and deterministic seed.",
    )
    t_result = simulate_goal(mc_returns, 100_000.0, 120_000.0, 1.0, "student_t", 200, 772)
    daily_mc = mc_returns.to_numpy(dtype=float)
    t_df, t_loc, t_scale = stats.t.fit(daily_mc)
    t_df = max(float(t_df), 2.1)
    t_rng = np.random.default_rng(772)
    t_innovations = stats.t.rvs(
        t_df,
        loc=t_loc,
        scale=t_scale,
        size=(200, TRADING_DAYS),
        random_state=t_rng,
    )
    t_standard_deviation = t_scale * math.sqrt(t_df / (t_df - 2.0))
    t_z = np.clip((t_innovations - t_loc) / t_standard_deviation, -8.0, 8.0)
    t_daily = daily_mc.mean() + daily_mc.std(ddof=1) * t_z
    t_daily = np.clip(t_daily, -0.95, None)
    t_terminal = 100_000.0 * np.exp(np.sum(np.log1p(t_daily), axis=1))
    record(
        "monte_carlo_student_t",
        "terminal_median_rounded",
        t_result["terminal_percentiles"]["p50"],
        round(float(np.percentile(t_terminal, 50)), 2),
        0.0,
        0.0,
        "MATCHES",
        "none",
        "independent scipy Student-t replay with same seed",
        "Innovations are winsorized and moment-matched to historical daily mean/std.",
    )
    bootstrap_a = simulate_goal(mc_returns, 100_000.0, 120_000.0, 1.0, "bootstrap", 200, 773)
    bootstrap_b = simulate_goal(mc_returns, 100_000.0, 120_000.0, 1.0, "bootstrap", 200, 773)
    bootstrap_rng = np.random.default_rng(773)
    bootstrap_seed = int(bootstrap_rng.integers(0, 2**32 - 1))
    bootstrap_reference = StationaryBootstrap(21, daily_mc, seed=bootstrap_seed)
    bootstrap_generator = bootstrap_reference.bootstrap(200)
    bootstrap_terminal = np.empty(200)
    for path_index in range(200):
        chunks: list[np.ndarray] = []
        total = 0
        while total < TRADING_DAYS:
            position, _ = next(bootstrap_generator)
            chunk = np.asarray(position[0]).ravel()
            chunks.append(chunk)
            total += chunk.size
        sequence = np.concatenate(chunks)[:TRADING_DAYS]
        bootstrap_terminal[path_index] = 100_000.0 * np.prod(1.0 + sequence)
    record(
        "monte_carlo_bootstrap",
        "terminal_median_rounded",
        bootstrap_a["terminal_percentiles"]["p50"],
        round(float(np.percentile(bootstrap_terminal, 50)), 2),
        0.0,
        0.0,
        "MATCHES",
        "none",
        "independent arch stationary-bootstrap replay with same derived seed",
        "The second backend call is retained as a same-seed determinism control.",
    )
    if bootstrap_a["prob_success"] != bootstrap_b["prob_success"]:
        raise AssertionError("bootstrap determinism control failed")
    emit()

    emit("MODEL: portfolio performance history and benchmark rebasing")
    history_dates = pd.bdate_range("2025-01-02", periods=90)
    history_prices = pd.DataFrame(
        {"AAA": 100.0 * np.cumprod(1.0 + np.linspace(-0.01, 0.015, 90)), "BBB": 80.0 * np.cumprod(1.0 + np.linspace(0.005, -0.005, 90))},
        index=history_dates,
    )
    history_quantities = {"AAA": 2.0, "BBB": 3.0}
    history_portfolio = history_prices.mul(pd.Series(history_quantities)).sum(axis=1)
    history_returns = history_portfolio.pct_change().fillna(0.0)
    history_positions = [
        PortfolioPosition(
            id=1,
            ticker=ticker,
            weight=0.5,
            quantity=quantity,
            buy_price=float(history_prices[ticker].iloc[0]),
            last_price=float(history_prices[ticker].iloc[-1]),
            market_value=quantity * float(history_prices[ticker].iloc[-1]),
            region="IN",
            sector="Equity",
            industry="Test",
            added_on=pd.Timestamp("2024-01-01").to_pydatetime(),
        )
        for ticker, quantity in history_quantities.items()
    ]

    class HistoryDataService:
        async def fetch_historical_data(self, ticker: str, start: str, end: str) -> pd.DataFrame:
            return pd.DataFrame({"adj_close": history_prices[ticker]}, index=history_dates)

    benchmark_history = pd.Series(np.linspace(0.001, -0.001, 90), index=history_dates)
    history_backend = await get_performance_history(
        days=365,
        tickers=None,
        db=FakeSession(history_positions),
        data_service=HistoryDataService(),
        benchmark_service=TearSheetBenchmark(benchmark_history),
    )
    record(
        "performance_history",
        "last_portfolio_value",
        history_backend[-1]["portfolio_value"],
        float(history_portfolio.iloc[-1]),
        5.1e-3,
        1e-9,
        "MATCHES",
        "none",
        "sum(price x fixed quantity)",
        "Current quantities are backcast over the disclosed holding window; backend rounds to two decimals.",
    )
    record(
        "performance_history",
        "last_daily_return",
        history_backend[-1]["return"],
        float(history_returns.iloc[-1]),
        5.1e-7,
        1e-9,
        "MATCHES",
        "none",
        "portfolio value pct_change",
        "First observation is assigned zero return; backend rounds to six decimals.",
    )
    benchmark_value = 100.0 * (1.0 + benchmark_history).cumprod()
    benchmark_value /= benchmark_value.iloc[0]
    benchmark_value *= float(history_portfolio.iloc[0])
    record(
        "performance_history",
        "last_benchmark_rebased_value",
        history_backend[-1]["benchmark_value"],
        float(benchmark_value.iloc[-1]),
        5.1e-3,
        1e-9,
        "MATCHES",
        "none",
        "cumprod normalized to first common value",
        "Benchmark is rebased, not interpreted as an external total-return portfolio; backend rounds to two decimals.",
    )
    emit()

    emit("MODEL: adjacent portfolio scoring, stress, liquidity, and regime-summary formulas")
    risk_score = await engine.risk_scoring(prices, weights)
    portfolio_from_prices = prices.pct_change(fill_method=None).iloc[1:] @ pd.Series(weights)
    concentration_value = sum(weight**2 for weight in weights.values())
    score_weights = {"concentration": 0.20, "volatility": 0.25, "correlation": 0.20, "market_risk": 0.10}
    active_total = sum(score_weights.values())
    component_refs = {
        "concentration": min(30.0, concentration_value * 100.0),
        "volatility": min(30.0, float(portfolio_from_prices.std() * math.sqrt(TRADING_DAYS) * 100.0)),
        "correlation": min(30.0, max(0.0, (float(returns.corr().to_numpy()[np.triu_indices(3, 1)].mean()) - 0.3) * 50.0)),
        "market_risk": min(30.0, float(portfolio_from_prices.tail(60).std() * math.sqrt(TRADING_DAYS) * 100.0)),
    }
    reference_overall = sum(component_refs[key] * score_weights[key] for key in component_refs) / active_total
    record(
        "risk_score_heuristic",
        "overall_score",
        risk_score["overall_score"],
        reference_overall,
        0.051,
        1e-9,
        "MATCHES",
        "none",
        "declared weighted-score formula",
        "Heuristic scoring rule matches; no external calibration library is claimed.",
    )
    stress = await engine.stress_test(prices, weights, "-10%")
    stress_returns = prices.sort_index().ffill().bfill().pct_change(fill_method=None).fillna(0.0)
    reference_stress_impact = 0.0
    for ticker, weight in weights.items():
        nonzero = stress_returns[ticker][stress_returns[ticker] != 0.0].clip(-0.20, 0.20)
        ticker_volatility = float(nonzero.std() * math.sqrt(TRADING_DAYS)) if len(nonzero) >= 20 else 0.0
        adjustment = max(0.85, min(1.25, ticker_volatility / 0.22)) if ticker_volatility > 0 else 1.0
        position_impact = max(-0.75, min(-0.02, -0.10 * adjustment))
        reference_stress_impact += weight * position_impact
    record(
        "stress_scenario_heuristic",
        "portfolio_impact",
        stress["portfolio_impact"],
        reference_stress_impact,
        5.1e-5,
        1e-9,
        "MATCHES",
        "none",
        "independent capped-volatility shock replay",
        "Custom -10% with unit sector multipliers and independently recomputed bounded volatility adjustments.",
    )
    returns_for_liquidity = pd.Series([0.01, -0.02, 0.005, 0.0], index=pd.bdate_range("2025-01-02", periods=4))
    rupee_volume = pd.Series([10_000_000.0, 20_000_000.0, 40_000_000.0, 0.0], index=returns_for_liquidity.index)
    amihud_backend = compute_amihud_illiquidity(returns_for_liquidity, rupee_volume)
    amihud_reference = float(np.nanmean((returns_for_liquidity.abs() / rupee_volume) * 1e6))
    record(
        "amihud_illiquidity",
        "value",
        amihud_backend,
        amihud_reference,
        1e-12,
        1e-12,
        "MATCHES",
        "none",
        "transparent positive-volume mask",
        "Zero-volume observations are excluded.",
    )
    record(
        "days_to_liquidate",
        "days_at_10pct_adv",
        compute_days_to_liquidate(1_000_000.0, 2_000_000.0, 0.10),
        5.0,
        1e-12,
        1e-12,
        "MATCHES",
        "none",
        "position value/(participation x ADV)",
        "Cash-equity liquidation model.",
    )
    regime_returns = pd.Series(np.r_[-0.10, 0.01 + np.linspace(-0.002, 0.004, 59)], index=pd.bdate_range("2025-01-02", periods=60))
    regime_backend = portfolio_regime_summary(regime_returns)
    regime_total = float(np.prod(1.0 + regime_returns))
    regime_cagr = float(regime_total ** (TRADING_DAYS / len(regime_returns)) - 1.0)
    record(
        "portfolio_regime_summary",
        "geometric_cagr",
        regime_backend["ann_ret"],
        regime_cagr,
        5.1e-5,
        1e-9,
        "MATCHES",
        "none",
        "(prod(1+r))^(252/n)-1",
        "Annualization is gated at 30 observations.",
    )
    raw_case(
        "adjacent_models.edges",
        {
            "risk_factor_excluded_without_benchmark": risk_score["excluded_components"],
            "stress_confidence": stress["confidence_level"],
            "amihud_zero_volume_count": int((rupee_volume <= 0).sum()),
            "liquidity_invalid_days": compute_days_to_liquidate(1.0, 0.0, 0.10),
        },
    )
    emit()

    emit("CASE MATRIX")
    for number, case in enumerate(CASES, start=1):
        emit(
            f"CASE {number:03d} model={case['model']} metric={case['metric']} "
            f"backend={json.dumps(case['backend'], sort_keys=True)} "
            f"reference={json.dumps(case['reference'], sort_keys=True)} "
            f"abs_diff={case['abs_diff']:.12g} rel_diff={case['rel_diff']:.12g} "
            f"atol={case['atol']:.12g} rtol={case['rtol']:.12g} "
            f"verdict={case['verdict']} severity={case['severity']} "
            f"reference_name={case['reference_name']} note={case['note']}"
        )
    emit()
    verdict_counts = Counter(case["verdict"] for case in CASES)
    emit("VERDICT COUNTS")
    for verdict, count in sorted(verdict_counts.items()):
        emit(f"{verdict}={count}")
    emit(f"TOTAL_CASES={len(CASES)}")
    emit("END")


def _raises(function: Any) -> bool:
    try:
        function()
        return False
    except Exception:
        return True


def main() -> None:
    asyncio.run(audit())
    text = "\n".join(LINES) + "\n"
    OUTPUT_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {OUTPUT_PATH}")
    print(f"cases={len(CASES)}")
    print("verdicts=" + json.dumps(dict(Counter(case["verdict"] for case in CASES)), sort_keys=True))


if __name__ == "__main__":
    main()
