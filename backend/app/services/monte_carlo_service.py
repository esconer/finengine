"""
Monte Carlo goal-probability engine.

Simulates portfolio value paths from historical return statistics and answers
one question: what is the probability of reaching a target value within a
horizon, and what does the distribution of outcomes look like?

Three engines:
- gbm       : Geometric Brownian Motion calibrated on historical mu/sigma.
              Smooth, fast, but assumes lognormal iid returns.
- student_t : GBM with Student-t innovations fitted to the historical daily
              returns (scipy.stats.t), then moment-matched back. Captures the
              fat tails Indian equity indices exhibit.
- bootstrap : Politis-Romano STATIONARY bootstrap via arch.bootstrap
              (already a dependency via GARCH forecasting). Preserves fat
              tails AND autocorrelation without parametric assumptions.
              Horizons longer than history chain consecutive resamples.

No new dependencies: numpy / scipy / arch only. Seeded for determinism in tests.
"""

from __future__ import annotations

from typing import Dict, Any, Optional

import numpy as np
import pandas as pd
from arch.bootstrap import StationaryBootstrap
from scipy.stats import t as student_t

TRADING_DAYS = 252
BLOCK_LENGTH = 21
DEFAULT_PATHS = 2000
MAX_PATHS = 20000
MIN_HIST_OBS = 60
METHODS = ("gbm", "student_t", "bootstrap")


def _calibrate(portfolio_returns: pd.Series) -> tuple[float, float, np.ndarray]:
    """Annualized mu, sigma plus the raw daily returns array (dropna)."""
    r = pd.Series(portfolio_returns).dropna()
    if len(r) < MIN_HIST_OBS:
        raise ValueError(
            f"Need at least {MIN_HIST_OBS} daily observations, got {len(r)}"
        )
    mu_annual = float(r.mean() * TRADING_DAYS)
    sigma_annual = float(r.std(ddof=1) * np.sqrt(TRADING_DAYS))
    return mu_annual, sigma_annual, r.to_numpy(dtype=float)


def _simulate_gbm(
    mu_annual: float,
    sigma_annual: float,
    initial_value: float,
    horizon_years: int,
    num_paths: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """(num_paths, horizon_years*252 + 1) value paths, column 0 = initial."""
    steps = horizon_years * TRADING_DAYS
    dt = 1.0 / TRADING_DAYS
    drift = (mu_annual - 0.5 * sigma_annual**2) * dt
    diffusion = sigma_annual * np.sqrt(dt)
    shocks = rng.standard_normal((num_paths, steps))
    log_increments = drift + diffusion * shocks
    log_paths = np.cumsum(log_increments, axis=1)
    paths = initial_value * np.exp(log_paths)
    return np.hstack([np.full((num_paths, 1), initial_value), paths])


def _simulate_student_t(
    mu_annual: float,
    sigma_annual: float,
    daily_returns: np.ndarray,
    initial_value: float,
    horizon_years: int,
    num_paths: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, float]:
    """GBM with Student-t innovations fitted to history, moment-matched back.

    Moments use the ANALYTIC t formulas (not sample stats of the draws —
    a single extreme t draw would otherwise poison every z). Innovations are
    winsorized at +/-8 z and simple returns floored at -95% so log1p stays
    finite even when the fit lands near the Cauchy boundary.
    """
    steps = horizon_years * TRADING_DAYS
    df_, loc_, scale_ = student_t.fit(daily_returns)
    df_fit = float(max(df_, 2.1))  # variance undefined at df <= 2
    innov = student_t.rvs(df_fit, loc=loc_, scale=scale_,
                          size=(num_paths, steps), random_state=rng)
    analytic_std = scale_ * np.sqrt(df_fit / (df_fit - 2.0))
    z = np.clip((innov - loc_) / analytic_std, -8.0, 8.0)
    daily_sim = daily_returns.mean() + daily_returns.std(ddof=1) * z
    daily_sim = np.clip(daily_sim, -0.95, None)
    log_paths = np.cumsum(np.log1p(daily_sim), axis=1)
    paths = initial_value * np.exp(log_paths)
    return np.hstack([np.full((num_paths, 1), initial_value), paths]), float(df_)


def _simulate_bootstrap(
    daily_returns: np.ndarray,
    initial_value: float,
    horizon_years: int,
    num_paths: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Stationary bootstrap (arch.bootstrap); chains resamples for long horizons."""
    steps = horizon_years * TRADING_DAYS
    data = np.asarray(daily_returns, dtype=float)
    draws_per_path = int(np.ceil(steps / data.size))
    bs = StationaryBootstrap(BLOCK_LENGTH, data, seed=rng)
    gen = bs.bootstrap(num_paths * draws_per_path)
    paths = np.empty((num_paths, steps + 1))
    paths[:, 0] = initial_value
    for i in range(num_paths):
        chunks: list[np.ndarray] = []
        total = 0
        while total < steps:
            pos, _ = next(gen)
            arr = np.asarray(pos[0]).ravel()
            chunks.append(arr)
            total += arr.size
        seq = np.concatenate(chunks)[:steps]
        paths[i, 1:] = initial_value * np.cumprod(1.0 + seq)
    return paths


def _fan_from_paths(
    paths: np.ndarray, horizon_years: int, checkpoints_per_year: int = 2
) -> list[Dict[str, float]]:
    """Percentile fan at half-year checkpoints."""
    checkpoints = list(range(0, paths.shape[1], max(1, TRADING_DAYS // checkpoints_per_year)))
    if checkpoints[-1] != paths.shape[1] - 1:
        checkpoints.append(paths.shape[1] - 1)
    fan = []
    for step in checkpoints:
        p = np.percentile(paths[:, step], [5, 25, 50, 75, 95])
        fan.append(
            {
                "year": round(step / TRADING_DAYS, 2),
                "p5": round(float(p[0]), 2),
                "p25": round(float(p[1]), 2),
                "p50": round(float(p[2]), 2),
                "p75": round(float(p[3]), 2),
                "p95": round(float(p[4]), 2),
            }
        )
    return fan


def simulate_goal(
    portfolio_returns: pd.Series,
    initial_value: float,
    target_value: float,
    horizon_years: int,
    method: str = "gbm",
    num_paths: int = DEFAULT_PATHS,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Run the goal simulation and return a JSON-ready payload.

    Raises ValueError on bad inputs (caller maps to 400).
    """
    if initial_value <= 0:
        raise ValueError("initial_value must be positive")
    if target_value <= 0:
        raise ValueError("target_value must be positive")
    if horizon_years < 1 or horizon_years > 40:
        raise ValueError("horizon_years must be between 1 and 40")
    if method not in METHODS:
        raise ValueError(f"method must be one of {list(METHODS)}")
    num_paths = max(100, min(int(num_paths), MAX_PATHS))

    mu_annual, sigma_annual, daily = _calibrate(portfolio_returns)
    rng = np.random.default_rng(seed)

    if method == "gbm":
        paths = _simulate_gbm(mu_annual, sigma_annual, initial_value, horizon_years, num_paths, rng)
        student_t_df = None
    elif method == "student_t":
        paths, student_t_df = _simulate_student_t(mu_annual, sigma_annual, daily, initial_value, horizon_years, num_paths, rng)
    else:
        paths = _simulate_bootstrap(daily, initial_value, horizon_years, num_paths, rng)
        student_t_df = None

    terminal = paths[:, -1]
    prob_success = float(np.mean(terminal >= target_value))
    failing = terminal[terminal < target_value]
    expected_shortfall = (
        round(float(failing.mean() - target_value), 2) if len(failing) else 0.0
    )

    p5, p25, p50, p75, p95 = np.percentile(terminal, [5, 25, 50, 75, 95])

    return {
        "method": method,
        "initial_value": round(float(initial_value), 2),
        "target_value": round(float(target_value), 2),
        "horizon_years": horizon_years,
        "num_paths": num_paths,
        "prob_success": round(prob_success, 4),
        "terminal_percentiles": {
            "p5": round(float(p5), 2),
            "p25": round(float(p25), 2),
            "p50": round(float(p50), 2),
            "p75": round(float(p75), 2),
            "p95": round(float(p95), 2),
        },
        "fan": _fan_from_paths(paths, horizon_years),
        "expected_shortfall_vs_target": expected_shortfall,
        "historical_mu_annual": round(mu_annual, 4),
        "historical_sigma_annual": round(sigma_annual, 4),
        "student_t_df": round(student_t_df, 2) if student_t_df is not None else None,
        "disclaimer": "Probabilities are model estimates from historical data; not investment advice.",
    }
