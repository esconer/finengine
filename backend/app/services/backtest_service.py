"""
Walk-Forward Strategy Backtester Service.
Evaluates dynamic portfolio rebalancing strategies out-of-sample over historical daily returns.
"""

from typing import Dict, Any
import math
import numpy as np
import pandas as pd

from app.services.optimization_service import STRATEGIES, optimize
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

TRADING_DAYS = 252


def run_walk_forward_backtest(
    returns: pd.DataFrame,
    strategy: str = "hrp",
    rebalance_freq_days: int = 21,
    lookback_days: int = 252,
    transaction_cost_bps: float = 10.0,
    risk_free_rate: float = 0.02,
) -> Dict[str, Any]:
    """
    Run out-of-sample walk-forward backtest over wide returns dataframe.

    Raises ValueError for invalid input (unknown strategy, bad windows);
    per-window optimizer failures fall back to retaining previous weights.
    """
    # Validate economic controls before any optimizer or simulation work.
    try:
        transaction_cost_bps = float(transaction_cost_bps)
        risk_free_rate = float(risk_free_rate)
    except (TypeError, ValueError) as exc:
        raise ValueError("transaction_cost_bps and risk_free_rate must be finite numbers") from exc
    if not math.isfinite(transaction_cost_bps) or transaction_cost_bps < 0.0:
        raise ValueError("transaction_cost_bps must be finite and >= 0")
    if not math.isfinite(risk_free_rate):
        raise ValueError("risk_free_rate must be finite")

    # Fail fast on invalid input: a bogus strategy must not be silently
    # swallowed by the per-window solver-failure fallback below.
    if strategy not in STRATEGIES and strategy != "equal_weight":
        raise ValueError(
            f"Unknown strategy '{strategy}'. Choose from {list(STRATEGIES)} or 'equal_weight'"
        )
    if lookback_days < 20:
        raise ValueError(f"lookback_days must be >= 20, got {lookback_days}")
    if rebalance_freq_days < 1:
        raise ValueError(f"rebalance_freq_days must be >= 1, got {rebalance_freq_days}")

    if len(returns) < 30:
        raise ValueError(
            f"Insufficient data for backtest: have {len(returns)} days, "
            f"need at least 30 days."
        )
    if returns.empty or len(returns.columns) == 0:
        raise ValueError("returns must contain at least one asset")
    if not np.isfinite(returns.to_numpy(dtype=float)).all():
        raise ValueError("returns must contain only finite values")

    if len(returns) < lookback_days + rebalance_freq_days:
        lookback_days = max(20, int(len(returns) * 0.4))
        rebalance_freq_days = max(5, int(len(returns) * 0.1))

    assets = list(returns.columns)
    cost_factor = transaction_cost_bps / 10000.0

    # Rebalance schedule indices. The final boundary must be len(returns)
    # (exclusive slice end) so the LAST day of the frame is simulated —
    # appending len-1 would silently drop it from every backtest.
    rebalance_indices = list(range(lookback_days, len(returns), rebalance_freq_days))
    if not rebalance_indices or rebalance_indices[-1] != len(returns):
        rebalance_indices.append(len(returns))

    daily_strategy_returns = []
    daily_benchmark_returns = []
    rebalance_events = []

    # Strategy weights are self-financing: after each day, holdings drift with
    # their realised returns until the next scheduled boundary.  The benchmark
    # is an explicitly labelled equal-weight buy-and-hold basket (also drifting,
    # with no rebalance or costs), so the two curves remain economically
    # comparable without hidden daily rebalancing.
    current_weights = np.ones(len(assets)) / len(assets)
    bench_bh_weights = np.ones(len(assets)) / len(assets)
    total_turnover = 0.0

    for i in range(len(rebalance_indices) - 1):
        t_start = rebalance_indices[i]
        t_end = rebalance_indices[i + 1]
        if t_end <= t_start:
            continue

        train_window = returns.iloc[t_start - lookback_days:t_start]

        if len(assets) == 1 or strategy == "equal_weight":
            new_weights = np.ones(len(assets)) / len(assets)
        else:
            try:
                opt_res = optimize(train_window, strategy=strategy, risk_free_rate=risk_free_rate)
                new_weights = np.array([opt_res["weights"].get(a, 0.0) for a in assets], dtype=float)
                new_weights = np.clip(new_weights, 0.0, None)
                if new_weights.sum() > 0 and np.isfinite(new_weights).all():
                    new_weights /= new_weights.sum()
                else:
                    new_weights = np.ones(len(assets)) / len(assets)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Optimization failed on day {t_start} for {strategy}: {e}. Retaining previous weights.")
                new_weights = current_weights.copy()

        # One-way turnover: sum|Δw| double-counts (10% A→B reads 0.2 turnover),
        # so halve it before applying the cost rate.  Turnover is measured from
        # the drifted pre-boundary holdings, not from yesterday's target.
        turnover = float(0.5 * np.sum(np.abs(new_weights - current_weights)))
        total_turnover += turnover
        cost_penalty = turnover * cost_factor

        current_weights = new_weights.copy()
        rebalance_date = str(returns.index[t_start])[:10] if hasattr(returns.index[t_start], "strftime") else str(returns.index[t_start])
        rebalance_events.append({
            "date": rebalance_date,
            "turnover": round(turnover, 4),
            "cost_penalty": round(cost_penalty, 6),
            "weights": {a: round(float(w), 4) for a, w in zip(assets, new_weights)}
        })

        test_chunk = returns.iloc[t_start:t_end]
        chunk_vals = test_chunk.to_numpy(dtype=float)
        chunk_index = test_chunk.index

        for offset, row_name in enumerate(chunk_index):
            row = chunk_vals[offset]
            gross_strat_ret = float(current_weights @ row)
            gross_bench_ret = float(bench_bh_weights @ row)

            day_strat_ret = gross_strat_ret
            if offset == 0:
                # Pay scheduled-boundary friction on capital before earning the
                # first return of the new holding period.
                day_strat_ret = (1.0 - cost_penalty) * (1.0 + gross_strat_ret) - 1.0

            strat_denominator = 1.0 + gross_strat_ret
            bench_denominator = 1.0 + gross_bench_ret
            if (
                strat_denominator <= 1e-12
                or bench_denominator <= 1e-12
                or not np.isfinite(strat_denominator)
                or not np.isfinite(bench_denominator)
            ):
                raise ValueError("backtest encountered non-positive/non-finite simulated wealth")

            # w[t+1] = w[t] * (1 + r[t]) / (1 + w[t]ᵀr[t]).
            current_weights = current_weights * (1.0 + row) / strat_denominator
            bench_bh_weights = bench_bh_weights * (1.0 + row) / bench_denominator

            date_str = str(row_name)[:10] if hasattr(row_name, "strftime") else str(row_name)
            daily_strategy_returns.append((date_str, day_strat_ret))
            daily_benchmark_returns.append((date_str, gross_bench_ret))

    if not daily_strategy_returns:
        raise ValueError("Backtest produced zero out-of-sample return days.")

    strat_rets = np.array([r for _, r in daily_strategy_returns])
    bench_rets = np.array([r for _, r in daily_benchmark_returns])
    dates = [d for d, _ in daily_strategy_returns]

    # Include initial wealth 1.0 as the first peak.  The first out-of-sample
    # loss must be able to create a drawdown immediately.
    strat_cum = np.cumprod(1.0 + strat_rets)
    bench_cum = np.cumprod(1.0 + bench_rets)
    strat_wealth = np.concatenate(([1.0], strat_cum))
    bench_wealth = np.concatenate(([1.0], bench_cum))

    strat_peaks = np.maximum.accumulate(strat_wealth)
    bench_peaks = np.maximum.accumulate(bench_wealth)
    strat_dd_all = (strat_wealth - strat_peaks) / strat_peaks
    bench_dd_all = (bench_wealth - bench_peaks) / bench_peaks
    strat_dds = strat_dd_all[1:]
    bench_dds = bench_dd_all[1:]

    n_days = len(strat_rets)
    years = n_days / TRADING_DAYS
    
    strat_cagr = float((strat_cum[-1]) ** (1.0 / years) - 1.0) if years > 0 else 0.0
    bench_cagr = float((bench_cum[-1]) ** (1.0 / years) - 1.0) if years > 0 else 0.0

    # Sharpe (1966) / Lo (2002): mean-based excess return over ddof=1 sample
    # volatility — not geometric CAGR over population std.
    strat_mu_d = float(np.mean(strat_rets))
    strat_sd_d = float(np.std(strat_rets, ddof=1)) if n_days > 1 else 0.0
    bench_mu_d = float(np.mean(bench_rets))
    bench_sd_d = float(np.std(bench_rets, ddof=1)) if n_days > 1 else 0.0

    strat_vol = float(strat_sd_d * np.sqrt(TRADING_DAYS))
    bench_vol = float(bench_sd_d * np.sqrt(TRADING_DAYS))

    strat_sharpe = float((strat_mu_d * TRADING_DAYS - risk_free_rate) / strat_vol) if strat_vol > 0 else None
    bench_sharpe = float((bench_mu_d * TRADING_DAYS - risk_free_rate) / bench_vol) if bench_vol > 0 else None

    strat_mdd = float(np.min(strat_dd_all))
    bench_mdd = float(np.min(bench_dd_all))

    strat_calmar = float(strat_cagr / abs(strat_mdd)) if abs(strat_mdd) > 0 else None

    equity_curve = [
        {"date": d, "strategy": round(float(s), 4), "benchmark": round(float(b), 4)}
        for d, s, b in zip(dates, strat_cum, bench_cum)
    ]

    drawdowns = [
        {"date": d, "strategy": round(float(s), 4), "benchmark": round(float(b), 4)}
        for d, s, b in zip(dates, strat_dds, bench_dds)
    ]

    return {
        "strategy": strategy,
        "cagr": round(strat_cagr, 4),
        "annualized_volatility": round(strat_vol, 4),
        "sharpe_ratio": round(strat_sharpe, 4) if strat_sharpe is not None else None,
        "max_drawdown": round(strat_mdd, 4),
        "calmar_ratio": round(strat_calmar, 4) if strat_calmar is not None else None,
        "total_turnover": round(total_turnover, 2),
        "total_rebalances": len(rebalance_events),
        "benchmark_method": "equal_weight_buy_and_hold",
        "strategy_accounting": "self_financing_weight_drift",
        "benchmark_cagr": round(bench_cagr, 4),
        "benchmark_volatility": round(bench_vol, 4),
        "benchmark_sharpe": round(bench_sharpe, 4) if bench_sharpe is not None else None,
        "benchmark_max_drawdown": round(bench_mdd, 4),
        "equity_curve": equity_curve,
        "drawdowns": drawdowns,
        "rebalance_events": rebalance_events,
    }
