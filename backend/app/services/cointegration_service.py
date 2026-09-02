"""
Cointegration Pairs Scanner Service
Implements Engle-Granger two-step test, Johansen rank test, OLS hedge ratio estimation,
Ornstein-Uhlenbeck (OU) mean-reversion speed/half-life, spread z-scores, and caching.
"""

from datetime import datetime, timedelta
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint
from statsmodels.tsa.vector_ar.vecm import coint_johansen
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schemas import CointPairResult, CointScannerResponse
from app.services.cache_service import CacheService
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# In-memory TTL cache for cointegration computations
_IN_MEMORY_COINT_CACHE: Dict[str, Tuple[datetime, Dict[str, Any]]] = {}
CACHE_TTL_HOURS = 24


def compute_ou_parameters(spread: np.ndarray) -> Tuple[Optional[float], Optional[float]]:
    """
    Estimate Ornstein-Uhlenbeck (OU) mean-reversion speed (theta) and half-life (t_1/2).

    Continuous: dz_t = theta * (mu - z_t) dt + sigma dW_t
    Discrete AR(1) regression: Delta z_t = a + gamma * z_{t-1} + e_t

    where gamma = e^(-theta) - 1 => theta = -ln(1 + gamma)
    Half-life: t_{1/2} = -ln(2) / ln(1 + gamma) = ln(2) / theta

    Returns:
        (ou_reversion_speed_theta, ou_half_life_days)
    """
    if len(spread) < 10:
        return None, None

    z = np.asarray(spread, dtype=float)
    # Filter non-finite values
    valid_mask = np.isfinite(z)
    z = z[valid_mask]
    if len(z) < 10:
        return None, None

    dz = z[1:] - z[:-1]
    z_lag = z[:-1]

    # Guard against zero or degenerate variance in spread series
    if float(np.var(z_lag)) < 1e-12:
        return None, None

    # Linear regression: dz = a + gamma * z_lag
    try:
        # np.polyfit returns [gamma, a] for degree 1
        gamma, _ = np.polyfit(z_lag, dz, 1)
    except Exception as e:
        logger.debug(f"OU polyfit error: {e}")
        return None, None

    # Mean reverting requires -2 < gamma < 0
    if gamma >= 0:
        # Non-mean-reverting / explosive or unit root
        return None, None

    if -1.0 < gamma < 0:
        theta = float(-np.log(1.0 + gamma))
        if theta > 1e-8:
            half_life = float(np.log(2.0) / theta)
            return round(theta, 6), round(half_life, 2)
        return None, None
    elif -2.0 < gamma <= -1.0:
        # Strongly oscillatory / immediate mean reversion
        theta = float(-np.log(max(1e-6, 1.0 + gamma + 1.0)))  # numerical guard
        return round(abs(float(gamma)), 6), 1.0
    else:
        return None, None


def test_johansen_cointegration(series_a: np.ndarray, series_b: np.ndarray) -> bool:
    """
    Perform Johansen cointegration rank test on a bivariate system.
    Returns True if trace statistic for r=0 exceeds 95% critical value.
    """
    try:
        data = np.column_stack([series_a, series_b])
        # det_order=0 (constant term), k_ar_diff=1 (lag order)
        res = coint_johansen(data, det_order=0, k_ar_diff=1)
        # Trace statistic for rank 0: res.lr1[0]
        # 95% critical value for rank 0: res.cvt[0, 1]
        trace_stat_r0 = float(res.lr1[0])
        crit_val_95_r0 = float(res.cvt[0, 1])
        return bool(trace_stat_r0 > crit_val_95_r0)
    except Exception as e:
        logger.debug(f"Johansen test error: {e}")
        return False


def analyze_pair_cointegration(
    ticker_a: str,
    ticker_b: str,
    series_a: pd.Series,
    series_b: pd.Series,
    p_value_threshold: float = 0.05,
    include_spread_series: bool = False,
) -> Optional[CointPairResult]:
    """
    Analyze a single pair of price series for cointegration.

    Args:
        ticker_a: Symbol of asset A (dependent variable)
        ticker_b: Symbol of asset B (independent variable)
        series_a: Price series for asset A
        series_b: Price series for asset B
        p_value_threshold: Cointegration p-value significance threshold
        include_spread_series: Whether to include historical spread data points

    Returns:
        CointPairResult or None if insufficient overlapping data
    """
    # Synchronize price series
    df = pd.DataFrame({"a": series_a, "b": series_b}).dropna()
    if len(df) < 30:
        return None

    p_a = df["a"].values.astype(float)
    p_b = df["b"].values.astype(float)

    # 1. Engle-Granger Two-Step Test
    try:
        t_stat, p_val, _ = coint(p_a, p_b)
        engle_granger_tstat = float(t_stat)
        engle_granger_pvalue = float(p_val)
    except Exception as e:
        logger.debug(f"Engle-Granger error for {ticker_a}-{ticker_b}: {e}")
        return None

    is_coint = bool(engle_granger_pvalue < p_value_threshold)

    # 2. OLS Hedge Ratio (beta) and Intercept (alpha): P_A = alpha + beta * P_B + epsilon
    try:
        # np.polyfit(p_b, p_a, 1) returns [beta, alpha]
        beta, alpha = np.polyfit(p_b, p_a, 1)
        beta = float(beta)
        alpha = float(alpha)
    except Exception as e:
        logger.debug(f"OLS hedge ratio error for {ticker_a}-{ticker_b}: {e}")
        return None

    # 3. Spread time series: z_t = P_A - (alpha + beta * P_B)
    spread = p_a - (alpha + beta * p_b)

    # 4. Johansen Rank Test
    johansen_coint = test_johansen_cointegration(p_a, p_b)

    # 5. Ornstein-Uhlenbeck Mean-Reversion Parameters
    theta, half_life = compute_ou_parameters(spread)

    # 6. Current Spread Z-Score
    spread_mean = float(np.mean(spread))
    spread_std = float(np.std(spread, ddof=1)) if len(spread) > 1 else 0.0
    current_zscore: Optional[float] = None
    if spread_std > 1e-8:
        current_zscore = round(float((spread[-1] - spread_mean) / spread_std), 4)

    # 7. Trading Signal
    last_p_a = float(p_a[-1])
    last_p_b = float(p_b[-1])

    if current_zscore is not None:
        if current_zscore >= 1.5:
            signal = f"SHORT_SPREAD (Short {ticker_a}, Long {ticker_b})"
        elif current_zscore <= -1.5:
            signal = f"LONG_SPREAD (Long {ticker_a}, Short {ticker_b})"
        else:
            signal = "NEUTRAL"
    else:
        signal = "NEUTRAL"

    # 8. Optional Spread Series
    spread_points = None
    if include_spread_series:
        spread_points = []
        dates = df.index
        for dt, s_val in zip(dates, spread):
            d_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
            z_val = round(float((s_val - spread_mean) / spread_std), 4) if spread_std > 1e-8 else 0.0
            spread_points.append({
                "date": d_str,
                "spread": round(float(s_val), 4),
                "zscore": z_val,
            })

    return CointPairResult(
        ticker_a=ticker_a,
        ticker_b=ticker_b,
        engle_granger_pvalue=round(engle_granger_pvalue, 6),
        engle_granger_tstat=round(engle_granger_tstat, 4),
        is_cointegrated=is_coint,
        hedge_ratio_beta=round(beta, 6),
        intercept_alpha=round(alpha, 4),
        ou_half_life_days=half_life,
        ou_reversion_speed_theta=theta,
        current_spread_zscore=current_zscore,
        johansen_cointegrated=johansen_coint,
        last_price_a=round(last_p_a, 2),
        last_price_b=round(last_p_b, 2),
        signal=signal,
        spread_series=spread_points,
    )


class CointegrationService:
    """
    Service for Cointegration scanning, parameter estimation, and caching.
    """

    def __init__(
        self,
        db_session: Optional[AsyncSession] = None,
        cache_service: Optional[CacheService] = None,
    ):
        self.db = db_session
        self.cache_service = cache_service

    async def _get_cached_pair(
        self, ticker_a: str, ticker_b: str, last_date: str
    ) -> Optional[CointPairResult]:
        """Check in-memory cache and DB cache for computed pair result"""
        cache_key = f"coint_{ticker_a}_{ticker_b}_{last_date}"

        # 1. In-memory check
        if cache_key in _IN_MEMORY_COINT_CACHE:
            ts, data = _IN_MEMORY_COINT_CACHE[cache_key]
            if datetime.utcnow() - ts < timedelta(hours=CACHE_TTL_HOURS):
                try:
                    return CointPairResult(**data)
                except Exception:
                    pass

        # 2. Database check
        if self.cache_service is not None:
            try:
                cached = await self.cache_service.get_cached_analytics(
                    ticker=f"{ticker_a[:4]}_{ticker_b[:4]}",
                    metric_name=f"coint_{last_date}",
                )
                if cached and cached.get("model_params"):
                    pair_data = cached["model_params"]
                    if pair_data.get("ticker_a") == ticker_a and pair_data.get("ticker_b") == ticker_b:
                        res = CointPairResult(**pair_data)
                        _IN_MEMORY_COINT_CACHE[cache_key] = (datetime.utcnow(), pair_data)
                        return res
            except Exception as e:
                logger.debug(f"DB cache read error: {e}")

        return None

    async def _set_cached_pair(
        self,
        ticker_a: str,
        ticker_b: str,
        last_date: str,
        result: CointPairResult,
    ) -> None:
        """Store pair result in memory and DB cache"""
        cache_key = f"coint_{ticker_a}_{ticker_b}_{last_date}"
        pair_dict = result.model_dump() if hasattr(result, "model_dump") else result.dict()

        # 1. In-memory store
        _IN_MEMORY_COINT_CACHE[cache_key] = (datetime.utcnow(), pair_dict)

        # 2. Database store
        if self.cache_service is not None:
            try:
                await self.cache_service.set_cached_analytics(
                    ticker=f"{ticker_a[:4]}_{ticker_b[:4]}",
                    metric_name=f"coint_{last_date}",
                    metric_value=float(result.engle_granger_pvalue),
                    calculation_date=datetime.utcnow(),
                    model_params=pair_dict,
                )
            except Exception as e:
                logger.debug(f"DB cache write error: {e}")

    async def scan_pairs(
        self,
        price_data: Dict[str, pd.Series],
        p_value_threshold: float = 0.05,
        max_half_life: Optional[int] = 60,
        include_spread_series: bool = False,
    ) -> CointScannerResponse:
        """
        Scan all pairwise combinations in the universe for cointegration.

        Args:
            price_data: Dictionary mapping ticker to close price pd.Series
            p_value_threshold: Maximum Engle-Granger p-value for cointegration
            max_half_life: Optional maximum OU half-life filter in trading days
            include_spread_series: Whether to include historical spread data

        Returns:
            CointScannerResponse with scanned & cointegrated pair metrics
        """
        tickers = sorted([t for t in price_data.keys() if price_data[t] is not None and not price_data[t].empty])
        n = len(tickers)

        if n < 2:
            return CointScannerResponse(
                as_of=datetime.utcnow().strftime("%Y-%m-%d"),
                universe_size=n,
                scanned_pairs_count=0,
                cointegrated_pairs_count=0,
                pairs=[],
            )

        # Find latest available date across series
        all_dates = []
        for s in price_data.values():
            if s is not None and not s.empty and hasattr(s.index[-1], "strftime"):
                all_dates.append(s.index[-1].strftime("%Y-%m-%d"))
            elif s is not None and not s.empty:
                all_dates.append(str(s.index[-1])[:10])
        as_of_date = max(all_dates) if all_dates else datetime.utcnow().strftime("%Y-%m-%d")

        pair_combinations = list(combinations(tickers, 2))
        scanned_count = 0
        all_results: List[CointPairResult] = []

        for t1, t2 in pair_combinations:
            scanned_count += 1
            s1 = price_data[t1]
            s2 = price_data[t2]

            # Check cache first
            cached_result = await self._get_cached_pair(t1, t2, as_of_date)
            if cached_result is not None:
                all_results.append(cached_result)
                continue

            pair_res = analyze_pair_cointegration(
                ticker_a=t1,
                ticker_b=t2,
                series_a=s1,
                series_b=s2,
                p_value_threshold=p_value_threshold,
                include_spread_series=include_spread_series,
            )

            if pair_res is not None:
                await self._set_cached_pair(t1, t2, as_of_date, pair_res)
                all_results.append(pair_res)

        # Filter and rank pairs
        # Primary rank: cointegrated first, then ascending p-value
        def rank_key(p: CointPairResult) -> Tuple[int, float]:
            return (0 if p.is_cointegrated else 1, p.engle_granger_pvalue)

        sorted_pairs = sorted(all_results, key=rank_key)

        # If max_half_life is requested, filter cointegrated pairs or flag them
        cointegrated_count = sum(
            1 for p in sorted_pairs
            if p.is_cointegrated and (max_half_life is None or (p.ou_half_life_days is not None and p.ou_half_life_days <= max_half_life))
        )

        return CointScannerResponse(
            as_of=as_of_date,
            universe_size=n,
            scanned_pairs_count=scanned_count,
            cointegrated_pairs_count=cointegrated_count,
            pairs=sorted_pairs,
        )
