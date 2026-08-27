"""
Walk-Forward Strategy Backtester Service.
Evaluates dynamic portfolio rebalancing strategies out-of-sample over historical daily returns.
"""

from typing import Dict, List, Any, Optional
import numpy as np
import pandas as pd

from app.services.optimization_service import optimize, STRATEGIES
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
    """
    if len(returns) < 30:
        raise ValueError(
            f"Insufficient data for backtest: have {len(returns)} days, "
            f"need at least 30 days."
        )

    if len(returns) < lookback_days + rebalance_freq_days:
        lookback_days = max(20, int(len(returns) * 0.4))
        rebalance_freq_days = max(5, int(len(returns) * 0.1))

    assets = list(returns.columns)
    cost_factor = transaction_cost_bps / 10000.0

    # Rebalance schedule indices
    rebalance_indices = list(range(lookback_days, len(returns), rebalance_freq_days))
    if not rebalance_indices or rebalance_indices[-1] < len(returns) - 1:
        rebalance_indices.append(len(returns) - 1)

    daily_strategy_returns = []
    daily_benchmark_returns = []
    rebalance_events = []
    
    current_weights = np.ones(len(assets)) / len(assets)
    bench_weights = np.ones(len(assets)) / len(assets)
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
                new_weights = np.array([opt_res["weights"].get(a, 0.0) for a in assets])
                new_weights = np.clip(new_weights, 0.0, None)
                if new_weights.sum() > 0:
                    new_weights /= new_weights.sum()
                else:
                    new_weights = np.ones(len(assets)) / len(assets)
            except Exception as e:
                logger.warning(f"Optimization failed on day {t_start} for {strategy}: {e}. Retaining previous weights.")
                new_weights = current_weights.copy()

        turnover = float(np.sum(np.abs(new_weights - current_weights)))
        total_turnover += turnover
        cost_penalty = turnover * cost_factor

        current_weights = new_weights
        rebalance_date = str(returns.index[t_start])[:10] if hasattr(returns.index[t_start], "strftime") else str(returns.index[t_start])
        rebalance_events.append({
            "date": rebalance_date,
            "turnover": round(turnover, 4),
            "cost_penalty": round(cost_penalty, 6),
            "weights": {a: round(float(w), 4) for a, w in zip(assets, current_weights)}
        })

        test_chunk = returns.iloc[t_start:t_end]
        for idx, (_, row) in enumerate(test_chunk.iterrows()):
            ret_vals = row.values
            day_strat_ret = float(np.sum(current_weights * ret_vals))
            day_bench_ret = float(np.sum(bench_weights * ret_vals))
            
            if idx == 0:
                day_strat_ret -= cost_penalty

            date_str = str(row.name)[:10] if hasattr(row.name, "strftime") else str(row.name)
            daily_strategy_returns.append((date_str, day_strat_ret))
            daily_benchmark_returns.append((date_str, day_bench_ret))

    if not daily_strategy_returns:
        raise ValueError("Backtest produced zero out-of-sample return days.")

    strat_rets = np.array([r for _, r in daily_strategy_returns])
    bench_rets = np.array([r for _, r in daily_benchmark_returns])
    dates = [d for d, _ in daily_strategy_returns]

    strat_cum = np.cumprod(1.0 + strat_rets)
    bench_cum = np.cumprod(1.0 + bench_rets)

    strat_peaks = np.maximum.accumulate(strat_cum)
    strat_dds = (strat_cum - strat_peaks) / strat_peaks

    bench_peaks = np.maximum.accumulate(bench_cum)
    bench_dds = (bench_cum - bench_peaks) / bench_peaks

    n_days = len(strat_rets)
    years = n_days / TRADING_DAYS
    
    strat_cagr = float((strat_cum[-1]) ** (1.0 / years) - 1.0) if years > 0 else 0.0
    bench_cagr = float((bench_cum[-1]) ** (1.0 / years) - 1.0) if years > 0 else 0.0

    strat_vol = float(np.std(strat_rets) * np.sqrt(TRADING_DAYS))
    bench_vol = float(np.std(bench_rets) * np.sqrt(TRADING_DAYS))

    strat_sharpe = float((strat_cagr - risk_free_rate) / strat_vol) if strat_vol > 0 else None
    bench_sharpe = float((bench_cagr - risk_free_rate) / bench_vol) if bench_vol > 0 else None

    strat_mdd = float(np.min(strat_dds))
    bench_mdd = float(np.min(bench_dds))

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
        "benchmark_cagr": round(bench_cagr, 4),
        "benchmark_volatility": round(bench_vol, 4),
        "benchmark_sharpe": round(bench_sharpe, 4) if bench_sharpe is not None else None,
        "benchmark_max_drawdown": round(bench_mdd, 4),
        "equity_curve": equity_curve,
        "drawdowns": drawdowns,
        "rebalance_events": rebalance_events,
    }
