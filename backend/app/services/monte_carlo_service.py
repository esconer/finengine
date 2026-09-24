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
# Retained simulation-workload cap.  The public simulator still returns this
# many paths (subject to MAX_PATHS), but materialises them in bounded chunks.
MAX_PATH_ELEMENTS = 50_000_000
# Aggregate live-element budget for all path-sized intermediates.  A single
# path matrix is not a sufficient bound: GBM names several arrays and hstack
# briefly creates another one.
MAX_AGGREGATE_ELEMENTS = 50_000_000
# Keep each low-level path matrix small enough that the aggregate budget is
# useful in practice rather than merely theoretical.
MAX_CHUNK_ELEMENTS = 1_000_000
# Conservative upper bound used when sizing a chunk: shocks/increments/logs,
# the path matrix, and the transient hstack output.
PATH_LIVE_ARRAY_MULTIPLIER = 5
MIN_HIST_OBS = 60
METHODS = ("gbm", "student_t", "bootstrap")


def _steps(horizon_years: float) -> int:
    """Trading-day step count; int(round()) so float horizons don't TypeError."""
    return int(round(float(horizon_years) * TRADING_DAYS))


def _assert_bounded_low_level_chunk(num_paths: int, steps: int) -> None:
    """Prevent direct low-level helpers from recreating the old OOM path."""
    if num_paths <= 0 or steps <= 0:
        raise ValueError("simulation chunk must have positive paths and steps")
    if num_paths * (steps + 1) > MAX_CHUNK_ELEMENTS:
        raise ValueError(
            "low-level simulation chunk exceeds MAX_CHUNK_ELEMENTS; "
            "use simulate_goal for chunked execution"
        )


def _calibrate(portfolio_returns: pd.Series) -> tuple[float, float, np.ndarray]:
    """Annualized mu, sigma plus the raw daily returns array (dropna)."""
    r = pd.Series(portfolio_returns).replace([np.inf, -np.inf], np.nan).dropna()
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
    horizon_years: float,
    num_paths: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """(num_paths, horizon_years*252 + 1) value paths, column 0 = initial."""
    steps = _steps(horizon_years)
    _assert_bounded_low_level_chunk(num_paths, steps)
    dt = 1.0 / TRADING_DAYS
    drift = (mu_annual - 0.5 * sigma_annual**2) * dt
    diffusion = sigma_annual * np.sqrt(dt)
    shocks = rng.standard_normal((num_paths, steps))
    log_increments = drift + diffusion * shocks
    log_paths = np.cumsum(log_increments, axis=1)
    paths = initial_value * np.exp(log_paths)
    return np.hstack([np.full((num_paths, 1), initial_value), paths])


def _fit_student_t(
    daily_returns: np.ndarray,
) -> tuple[float, float, float]:
    """Fit one Student-t innovation law for all simulation chunks."""
    df_, loc_, scale_ = student_t.fit(daily_returns)
    return float(df_), float(loc_), float(scale_)


def _simulate_student_t(
    mu_annual: float,
    sigma_annual: float,
    daily_returns: np.ndarray,
    initial_value: float,
    horizon_years: float,
    num_paths: int,
    rng: np.random.Generator,
    fit_params: Optional[tuple[float, float, float]] = None,
) -> tuple[np.ndarray, float]:
    """GBM with Student-t innovations fitted to history, moment-matched back.

    Moments use the ANALYTIC t formulas (not sample stats of the draws —
    a single extreme t draw would otherwise poison every z). Innovations are
    winsorized at +/-8 z and simple returns floored at -95% so log1p stays
    finite even when the fit lands near the Cauchy boundary.
    """
    steps = _steps(horizon_years)
    _assert_bounded_low_level_chunk(num_paths, steps)
    df_, loc_, scale_ = fit_params or _fit_student_t(daily_returns)
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
    horizon_years: float,
    num_paths: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Stationary bootstrap (arch.bootstrap); chains resamples for long horizons."""
    steps = _steps(horizon_years)
    _assert_bounded_low_level_chunk(num_paths, steps)
    data = np.asarray(daily_returns, dtype=float)
    draws_per_path = int(np.ceil(steps / data.size))
    # arch StationaryBootstrap takes an int seed on older versions — derive one
    # from the Generator instead of passing the Generator itself.
    bs = StationaryBootstrap(BLOCK_LENGTH, data, seed=int(rng.integers(0, 2**32 - 1)))
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


def _checkpoint_steps(steps: int, checkpoints_per_year: int = 2) -> list[int]:
    """Return deterministic half-year (by default) checkpoint columns."""
    interval = max(1, TRADING_DAYS // max(1, checkpoints_per_year))
    checkpoints = list(range(0, steps + 1, interval))
    if not checkpoints or checkpoints[-1] != steps:
        checkpoints.append(steps)
    return checkpoints


def _chunk_path_count(num_paths: int, steps: int) -> int:
    """Choose a path count whose live intermediates fit both budgets."""
    path_cap = max(
        1,
        MAX_AGGREGATE_ELEMENTS
        // max(1, steps * PATH_LIVE_ARRAY_MULTIPLIER),
    )
    chunk_cap = max(1, MAX_CHUNK_ELEMENTS // max(1, steps + 1))
    return max(1, min(int(num_paths), path_cap, chunk_cap))


def _fan_from_checkpoints(
    checkpoint_values: np.ndarray,
    checkpoint_steps: list[int],
) -> list[Dict[str, float]]:
    """Build the percentile fan from retained checkpoint columns only."""
    fan: list[Dict[str, float]] = []
    for column, step in enumerate(checkpoint_steps):
        p = np.percentile(checkpoint_values[:, column], [5, 25, 50, 75, 95])
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


def _simulate_bounded_checkpoints(
    mu_annual: float,
    sigma_annual: float,
    daily: np.ndarray,
    initial_value: float,
    horizon_years: float,
    num_paths: int,
    method: str,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, list[int], int]:
    """Run a method in bounded chunks and retain only fan/terminal columns."""
    steps = _steps(horizon_years)
    checkpoint_steps = _checkpoint_steps(steps)
    chunk_paths = _chunk_path_count(num_paths, steps)
    terminal = np.empty(num_paths, dtype=float)
    checkpoint_values = np.empty((num_paths, len(checkpoint_steps)), dtype=float)
    student_fit = _fit_student_t(daily) if method == "student_t" else None

    for start in range(0, num_paths, chunk_paths):
        count = min(chunk_paths, num_paths - start)
        if method == "gbm":
            paths = _simulate_gbm(
                mu_annual, sigma_annual, initial_value, horizon_years, count, rng
            )
        elif method == "student_t":
            paths, _ = _simulate_student_t(
                mu_annual,
                sigma_annual,
                daily,
                initial_value,
                horizon_years,
                count,
                rng,
                fit_params=student_fit,
            )
        else:
            paths = _simulate_bootstrap(
                daily, initial_value, horizon_years, count, rng
            )

        expected_shape = (count, steps + 1)
        if paths.shape != expected_shape:
            # Keep deterministic test doubles and third-party adapters from
            # accidentally reintroducing an unbounded allocation: a one-row
            # result is broadcast only inside this bounded view.
            if paths.ndim == 2 and paths.shape[0] == 1:
                paths = np.broadcast_to(paths[0], expected_shape)
            else:
                raise ValueError(
                    f"{method} simulation returned {paths.shape}, expected {expected_shape}"
                )
        if not np.isfinite(paths).all():
            raise ValueError(f"{method} simulation returned non-finite path values")

        stop = start + count
        terminal[start:stop] = paths[:, -1]
        for column, step in enumerate(checkpoint_steps):
            checkpoint_values[start:stop, column] = paths[:, step]
        # Drop the reference before the next chunk is allocated.
        del paths

    return terminal, checkpoint_values, checkpoint_steps, chunk_paths


def _fan_from_paths(
    paths: np.ndarray, checkpoints_per_year: int = 2
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
    horizon_years: float,
    method: str = "gbm",
    num_paths: int = DEFAULT_PATHS,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Run a bounded, checkpointed goal simulation.

    The effective path count retains the historical per-workload cap, while
    path matrices are generated in chunks and discarded after their terminal
    and fan checkpoint columns are copied.  This keeps aggregate live memory
    bounded for long horizons without changing the seeded output contract.
    """
    try:
        initial_value = float(initial_value)
        target_value = float(target_value)
        horizon_years = float(horizon_years)
        requested_paths = int(num_paths)
    except (TypeError, ValueError) as exc:
        raise ValueError("simulation inputs must be finite numbers") from exc
    if not np.isfinite(initial_value) or initial_value <= 0:
        raise ValueError("initial_value must be positive")
    if not np.isfinite(target_value) or target_value <= 0:
        raise ValueError("target_value must be positive")
    if not np.isfinite(horizon_years) or horizon_years < 1 or horizon_years > 40:
        raise ValueError("horizon_years must be between 1 and 40")
    if method not in METHODS:
        raise ValueError(f"method must be one of {list(METHODS)}")
    if requested_paths < 1:
        raise ValueError("num_paths must be positive")

    steps = _steps(horizon_years)
    retained_cap = max(100, MAX_PATH_ELEMENTS // max(steps, 1))
    num_paths = max(100, min(requested_paths, MAX_PATHS, retained_cap))

    mu_annual, sigma_annual, daily = _calibrate(portfolio_returns)
    rng = np.random.default_rng(seed)
    terminal, checkpoint_values, checkpoint_steps, chunk_paths = _simulate_bounded_checkpoints(
        mu_annual,
        sigma_annual,
        daily,
        initial_value,
        horizon_years,
        num_paths,
        method,
        rng,
    )
    student_t_df = _fit_student_t(daily)[0] if method == "student_t" else None

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
        "fan": _fan_from_checkpoints(checkpoint_values, checkpoint_steps),
        "expected_shortfall_vs_target": expected_shortfall,
        "historical_mu_annual": round(mu_annual, 4),
        "historical_sigma_annual": round(sigma_annual, 4),
        "student_t_df": round(student_t_df, 2) if student_t_df is not None else None,
        "memory_budget_elements": MAX_AGGREGATE_ELEMENTS,
        "chunk_size_paths": int(chunk_paths),
        "checkpoint_count": int(len(checkpoint_steps)),
        "disclaimer": "Probabilities are model estimates from historical data; not investment advice.",
    }
