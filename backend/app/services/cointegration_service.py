"""
Cointegration Pairs Scanner Service
Implements Engle-Granger two-step test, Johansen rank test, OLS hedge ratio estimation,
Ornstein-Uhlenbeck (OU) mean-reversion speed/half-life, spread z-scores, and caching.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha1
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint
from statsmodels.tsa.vector_ar.vecm import coint_johansen
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schemas import CointPairResult, CointScannerResponse
from app.services.cache_service import (
    CacheService,
    cache_generation_is_current,
    get_cache_generation,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# In-memory TTL cache for cointegration computations
_IN_MEMORY_COINT_CACHE: Dict[str, Tuple[datetime, Dict[str, Any]]] = {}
CACHE_TTL_HOURS = 24

# DB cache namespace. AnalyticsCache.ticker is String(10) and metric_name is
# String(50), so full tickers cannot be embedded: the pair identity is a
# stable sha1 digest of "A|B" (order-sensitive; scan_pairs emits sorted
# combos so keys are canonical). Previously f"{a[:4]}_{b[:4]}" collided
# (e.g. RELIANCE/RELCAP) and metric coint_{date} was shared by every pair,
# so each write evicted all other pairs of the day (last-write-wins).
COINT_DB_TICKER = "COINT"

# ---------------------------------------------------------------------------
# Pairs depth + dual-test contract (V3-14)
# ---------------------------------------------------------------------------
# Two cointegration tests run on every pair but only ONE of them decides.
# `is_cointegrated` is the Engle-Granger verdict; the Johansen rank test is a
# diagnostic cross-check whose disagreement is reported, never acted on.
DECISION_TEST = "engle_granger"
DIAGNOSTIC_TEST = "johansen"
JOHANSEN_ROLE = "diagnostic_only"

# The engine's own minimum usable-observation gate. `analyze_pair_cointegration`
# returns None below it, so the route and the engine can share this number
# instead of each keeping its own idea of "enough history".
MIN_PAIR_OBSERVATIONS = 30

# Depth ratio against the deepest pair of the same scan below which a pair is
# materially under-sampled. Engle-Granger p-values and OU half-lives both lose
# power as the sample shrinks, so a pair that clears the absolute gate but only
# covers, say, 106 of a possible 174 sessions is `partial`, not `complete`.
MIN_PAIR_DEPTH_RATIO = 0.75

# `universe_scope` is set by the route (only the caller knows whether the
# universe came from holdings alone or from holdings + watchlist).
UNIVERSE_SCOPES = ("holdings_only", "holdings_and_watchlist")

# One place for a consumer to learn which test decided and which one only
# cross-checks; published on the scanner response.
TEST_ROLES = {
    DECISION_TEST: "published_decision",
    DIAGNOSTIC_TEST: JOHANSEN_ROLE,
}


def _count_usable(series: Any) -> int:
    """Finite, non-null observations in a price series.

    0 is a measured count here, not a missing value: the series WAS inspected
    and contained no usable observation. Callers that need to distinguish
    "empty" from "not inspected" must handle None themselves.
    """
    if series is None:
        return 0
    try:
        values = pd.Series(series)
    except (TypeError, ValueError):
        return 0
    try:
        return int(values.replace([np.inf, -np.inf], np.nan).dropna().size)
    except (TypeError, ValueError):
        return 0


def usable_observations_by_ticker(price_data: Optional[Dict[str, pd.Series]]) -> Dict[str, int]:
    """Usable price observations per ticker, for per-ticker depth disclosure.

    ETFs and recent listings routinely have far less history than their peers
    (NIFTYIETF ~106-109 usable sessions against 168-174 for its peers over the
    same window), so an aggregate "how much data did this scan use" figure
    hides a materially thinner pair. The route publishes this map so the
    asymmetry is visible instead of implied.
    """
    if not price_data:
        return {}
    return {ticker: _count_usable(series) for ticker, series in price_data.items()}


def pair_depth_ratio(
    overlap_observations: Optional[int],
    reference_observations: Optional[int],
) -> Optional[float]:
    """Overlap as a fraction of the deepest pair in the same scan.

    None whenever either count is unknown or the reference is not positive: a
    ratio against a missing or zero reference would be invented.
    """
    if overlap_observations is None or reference_observations is None:
        return None
    if isinstance(overlap_observations, bool) or isinstance(reference_observations, bool):
        return None
    try:
        overlap = float(overlap_observations)
        reference = float(reference_observations)
    except (TypeError, ValueError):
        return None
    if overlap < 0 or reference <= 0:
        return None
    return round(overlap / reference, 4)


def assess_pair_depth(
    overlap_observations: Optional[int],
    reference_observations: Optional[int],
) -> Dict[str, Any]:
    """Depth verdict for one pair of a scan.

    ``status`` uses the shared public vocabulary:
    ``available``  - the pair ran on at least MIN_PAIR_DEPTH_RATIO of the
      deepest pair's history;
    ``partial``    - the pair ran, but on materially less history;
    ``unavailable``- the overlap was never measured, so completeness cannot be
      claimed in either direction.
    """
    ratio = pair_depth_ratio(overlap_observations, reference_observations)
    if ratio is None:
        return {"status": "unavailable", "depth_ratio": None, "depth_limited": None}
    return {
        "status": "partial" if ratio < MIN_PAIR_DEPTH_RATIO else "available",
        "depth_ratio": ratio,
        "depth_limited": ratio < MIN_PAIR_DEPTH_RATIO,
    }


def summarize_pair_depth(depths: List[Dict[str, Any]]) -> Tuple[str, int]:
    """Roll per-pair depth verdicts up to (response status, limited count).

    ``unavailable`` dominates ``partial`` dominates ``available``: a single
    unmeasured pair already means the section cannot be called complete.
    """
    statuses = {depth.get("status") for depth in depths}
    if not statuses:
        return "available", 0
    limited = sum(1 for depth in depths if depth.get("depth_limited") is True)
    if "unavailable" in statuses:
        return "unavailable", limited
    if "partial" in statuses:
        return "partial", limited
    return "available", limited


def shallow_tickers(
    counts: Dict[str, int],
    minimum_ratio: float = MIN_PAIR_DEPTH_RATIO,
) -> List[str]:
    """Tickers whose own history is materially thinner than the deepest one.

    Per-ticker version of the pair depth rule: a ticker listed halfway through
    the window drags every pair it enters down with it.
    """
    if not counts:
        return []
    deepest = max(counts.values())
    if deepest <= 0:
        # Nothing was measured anywhere; no ticker can be singled out.
        return []
    return sorted(
        ticker
        for ticker, count in counts.items()
        if count / deepest < minimum_ratio
    )


def with_test_role_metadata(pair: CointPairResult) -> CointPairResult:
    """Fill the dual-test role fields on a (possibly legacy) pair result.

    Cache rows written before these fields existed load fine because every one
    of them is Optional; this upgrades them from the engine's own constants
    instead of leaving the contract hole open. Nothing here is measured data
    beyond `johansen_agrees_with_decision`, which is a comparison of two
    booleans the row already carries.
    """
    if (
        pair.decision_test == DECISION_TEST
        and pair.johansen_role == JOHANSEN_ROLE
        and pair.johansen_agrees_with_decision is not None
    ):
        return pair
    return pair.model_copy(
        update={
            "decision_test": DECISION_TEST,
            "johansen_role": JOHANSEN_ROLE,
            "johansen_agrees_with_decision": pair.johansen_cointegrated == pair.is_cointegrated,
        }
    )


def _utcnow() -> datetime:
    """Naive UTC now: datetime.utcnow() replacement (DeprecationWarning on
    Python >= 3.12). Strips tz so stored values stay comparable with legacy
    cached rows (aware vs naive subtraction would raise TypeError)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _db_cache_keys(
    ticker_a: str,
    ticker_b: str,
    last_date: str,
    p_value_threshold: float = 0.05,
    include_spread_series: bool = False,
    lookback_days: Optional[int] = None,
    history_coverage: Optional[str] = None,
) -> Tuple[str, str]:
    """Build a durable key including effective history coverage.

    Pair/date/threshold/spread flags alone are insufficient: the same pair
    requested over 60 versus 2,520 observations has different p-values,
    spread points, and OU diagnostics.
    """
    coverage = history_coverage or ("lookback:unknown" if lookback_days is None else f"lookback:{int(lookback_days)}")
    raw = (
        f"{ticker_a}|{ticker_b}|{p_value_threshold}|"
        f"{int(include_spread_series)}|lookback:{lookback_days}|coverage:{coverage}"
    )
    digest = sha1(raw.encode("utf-8")).hexdigest()[:8]
    return COINT_DB_TICKER, f"coint_{digest}_{last_date}"


def _mem_cache_key(
    ticker_a: str,
    ticker_b: str,
    last_date: str,
    p_value_threshold: float = 0.05,
    include_spread_series: bool = False,
    lookback_days: Optional[int] = None,
    history_coverage: Optional[str] = None,
) -> str:
    """Single source of truth for the in-memory key."""
    coverage = history_coverage or ("lookback:unknown" if lookback_days is None else f"lookback:{int(lookback_days)}")
    return (
        f"coint_{ticker_a}_{ticker_b}_{last_date}"
        f"_{p_value_threshold}_{int(include_spread_series)}"
        f"_{lookback_days}_{coverage}"
    )


def _history_coverage(series_a: pd.Series, series_b: pd.Series) -> str:
    """Return a deterministic effective-overlap identity for cache keys."""
    frame = pd.DataFrame({"a": series_a, "b": series_b}).replace([np.inf, -np.inf], np.nan).dropna()
    if frame.empty:
        return "empty:0"
    start = frame.index[0]
    end = frame.index[-1]
    start_text = start.strftime("%Y-%m-%d") if hasattr(start, "strftime") else str(start)[:32]
    end_text = end.strftime("%Y-%m-%d") if hasattr(end, "strftime") else str(end)[:32]
    numeric = frame.apply(pd.to_numeric, errors="coerce")
    if numeric.notna().any().any():
        payload = np.ascontiguousarray(numeric.fillna(0.0).to_numpy(dtype=float))
    else:
        payload = np.ascontiguousarray(frame.astype(str).to_numpy())
    value_digest = sha1(payload.tobytes()).hexdigest()[:12]
    return f"{len(frame)}:{start_text}:{end_text}:{value_digest}"


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
        # Oscillatory overshoot: the discrete AR(1) flips sign each step, so no
        # continuous-time half-life exists. Return (None, None) as the
        # oscillatory flag — never fabricate half_life=1.0.
        logger.debug(f"OU oscillatory regime (gamma={gamma:.4f}); no half-life defined")
        return None, None
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
    if len(df) < MIN_PAIR_OBSERVATIONS:
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

    # 7. Trading Signal — gated on cointegration: a z-score extreme on a
    # non-cointegrated pair (p >= threshold) is spurious mean-reversion, not
    # a trade. Such pairs render "Not cointegrated" downstream.
    last_p_a = float(p_a[-1])
    last_p_b = float(p_b[-1])

    if not is_coint:
        signal = "NOT_COINTEGRATED"
    elif current_zscore is not None:
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

    def _date_text(value: Any) -> Optional[str]:
        if isinstance(value, (int, float, np.integer, np.floating)):
            return None
        try:
            parsed = pd.Timestamp(value)
            if pd.isna(parsed):
                return None
            return parsed.strftime("%Y-%m-%d")
        except (TypeError, ValueError, OverflowError):
            return None

    overlap_start = _date_text(df.index[0])
    overlap_end = _date_text(df.index[-1])
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
        observation_date_a=overlap_end,
        observation_date_b=overlap_end,
        overlap_start=overlap_start,
        overlap_end=overlap_end,
        overlap_observations=len(df),
        price_basis="adjusted_close_when_available",
        signal=signal,
        spread_series=spread_points,
        # Engle-Granger decided `is_cointegrated`; Johansen is diagnostic only,
        # so a disagreement is reported rather than acted on.
        decision_test=DECISION_TEST,
        johansen_role=JOHANSEN_ROLE,
        johansen_agrees_with_decision=bool(johansen_coint == is_coint),
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
        self,
        ticker_a: str,
        ticker_b: str,
        last_date: str,
        p_value_threshold: float = 0.05,
        include_spread_series: bool = False,
        lookback_days: Optional[int] = None,
        history_coverage: Optional[str] = None,
        cache_generation: Optional[int] = None,
    ) -> Optional[CointPairResult]:
        """Check in-memory cache and DB cache for computed pair result"""
        if cache_generation is not None and not cache_generation_is_current(cache_generation):
            return None
        cache_key = _mem_cache_key(
            ticker_a,
            ticker_b,
            last_date,
            p_value_threshold,
            include_spread_series,
            lookback_days=lookback_days,
            history_coverage=history_coverage,
        )

        # 1. In-memory check
        if cache_key in _IN_MEMORY_COINT_CACHE:
            if cache_generation is not None and not cache_generation_is_current(cache_generation):
                return None
            ts, data = _IN_MEMORY_COINT_CACHE[cache_key]
            if _utcnow() - ts < timedelta(hours=CACHE_TTL_HOURS):
                try:
                    return with_test_role_metadata(CointPairResult(**data))
                except Exception:
                    pass

        # 2. Database check
        if self.cache_service is not None:
            try:
                db_ticker, metric_name = _db_cache_keys(
                    ticker_a,
                    ticker_b,
                    last_date,
                    p_value_threshold,
                    include_spread_series,
                    lookback_days=lookback_days,
                    history_coverage=history_coverage,
                )
                cached = await self.cache_service.get_cached_analytics(
                    ticker=db_ticker,
                    metric_name=metric_name,
                )
                if cached and cached.get("model_params"):
                    pair_data = cached["model_params"]
                    if pair_data.get("ticker_a") == ticker_a and pair_data.get("ticker_b") == ticker_b:
                        # Rows written by older builds carry none of the
                        # role/depth fields; every one of them is Optional, so
                        # the load still succeeds and the roles are backfilled
                        # from the engine constants.
                        res = with_test_role_metadata(CointPairResult(**pair_data))
                        if cache_generation is not None and not cache_generation_is_current(cache_generation):
                            return None
                        _IN_MEMORY_COINT_CACHE[cache_key] = (_utcnow(), pair_data)
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
        p_value_threshold: float = 0.05,
        include_spread_series: bool = False,
        lookback_days: Optional[int] = None,
        history_coverage: Optional[str] = None,
        cache_generation: Optional[int] = None,
    ) -> None:
        """Store pair result in memory and DB cache.

        ``cache_generation`` is captured before the expensive pair analysis;
        a purge/source switch that advances the token makes this late write
        stale instead of repopulating a cleared memo.
        """
        if cache_generation is not None and not cache_generation_is_current(cache_generation):
            return
        cache_key = _mem_cache_key(
            ticker_a,
            ticker_b,
            last_date,
            p_value_threshold,
            include_spread_series,
            lookback_days=lookback_days,
            history_coverage=history_coverage,
        )
        pair_dict = result.model_dump() if hasattr(result, "model_dump") else result.dict()

        # 1. In-memory store
        if cache_generation is not None and not cache_generation_is_current(cache_generation):
            return
        _IN_MEMORY_COINT_CACHE[cache_key] = (_utcnow(), pair_dict)
        # Bounded memory: drop expired entries on every write (cache is
        # per-key-per-day-per-params, so long-running scanners grow it otherwise)
        now = _utcnow()
        stale = [k for k, (ts, _) in _IN_MEMORY_COINT_CACHE.items()
                 if now - ts >= timedelta(hours=CACHE_TTL_HOURS)]
        for k in stale:
            _IN_MEMORY_COINT_CACHE.pop(k, None)

        # 2. Database store
        if cache_generation is not None and not cache_generation_is_current(cache_generation):
            return
        if self.cache_service is not None:
            try:
                db_ticker, metric_name = _db_cache_keys(
                    ticker_a,
                    ticker_b,
                    last_date,
                    p_value_threshold,
                    include_spread_series,
                    lookback_days=lookback_days,
                    history_coverage=history_coverage,
                )
                await self.cache_service.set_cached_analytics(
                    ticker=db_ticker,
                    metric_name=metric_name,
                    metric_value=float(result.engle_granger_pvalue),
                    calculation_date=_utcnow(),
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
        lookback_days: Optional[int] = None,
    ) -> CointScannerResponse:
        """
        Scan all pairwise combinations in the universe for cointegration.

        Args:
            price_data: Dictionary mapping ticker to close price pd.Series
            p_value_threshold: Maximum Engle-Granger p-value for cointegration
            max_half_life: Optional maximum OU half-life filter in trading days
            include_spread_series: Whether to include historical spread data
            lookback_days: Optional requested lookback; actual pair coverage is
                also fingerprinted so sliced histories cannot share results.

        Returns:
            CointScannerResponse with scanned & cointegrated pair metrics
        """
        tickers = sorted([t for t in price_data.keys() if price_data[t] is not None and not price_data[t].empty])
        n = len(tickers)
        # Per-ticker depth, measured once and published so an uneven universe
        # (young ETF next to decade-old stocks) is visible in the contract
        # rather than hidden behind a single "how much data" impression.
        ticker_observations = usable_observations_by_ticker(price_data)
        thin_tickers = shallow_tickers(ticker_observations)

        if n < 2:
            return CointScannerResponse(
                as_of=_utcnow().strftime("%Y-%m-%d"),
                latest_observation_date=None,
                as_of_semantics="latest_available_observation",
                universe_size=n,
                scanned_pairs_count=0,
                analyzed_pairs_count=0,
                cointegrated_pairs_count=0,
                returned_pairs_count=0,
                returned_cointegrated_pairs_count=0,
                returned_non_cointegrated_pairs_count=0,
                data_status="unavailable",
                test_roles=dict(TEST_ROLES),
                usable_observations_by_ticker=ticker_observations,
                minimum_pair_observations=MIN_PAIR_OBSERVATIONS,
                minimum_depth_ratio=MIN_PAIR_DEPTH_RATIO,
                depth_status="unavailable",
                depth_limited_pair_count=0,
                shallow_tickers=thin_tickers,
                pairs=[],
            )

        # Find latest available date across series
        all_dates = []
        for s in price_data.values():
            if s is not None and not s.empty and hasattr(s.index[-1], "strftime"):
                all_dates.append(s.index[-1].strftime("%Y-%m-%d"))
            elif s is not None and not s.empty:
                all_dates.append(str(s.index[-1])[:10])
        as_of_date = max(all_dates) if all_dates else _utcnow().strftime("%Y-%m-%d")

        pair_combinations = list(combinations(tickers, 2))
        # Fence late cache writes if a purge/source switch happens while the
        # pair's statsmodels analysis is running.
        cache_generation = get_cache_generation()
        scanned_count = 0
        all_results: List[CointPairResult] = []

        for t1, t2 in pair_combinations:
            scanned_count += 1
            s1 = price_data[t1]
            s2 = price_data[t2]
            coverage = _history_coverage(s1, s2)

            # Check cache first
            cached_result = await self._get_cached_pair(
                t1,
                t2,
                as_of_date,
                p_value_threshold,
                include_spread_series,
                lookback_days=lookback_days,
                history_coverage=coverage,
                cache_generation=cache_generation,
            )
            if cached_result is not None:
                all_results.append(cached_result)
                continue

            # analyze_pair_cointegration is CPU-bound statsmodels work; run in a
            # worker thread so the event loop stays responsive during scans.
            pair_res = await asyncio.to_thread(
                analyze_pair_cointegration,
                ticker_a=t1,
                ticker_b=t2,
                series_a=s1,
                series_b=s2,
                p_value_threshold=p_value_threshold,
                include_spread_series=include_spread_series,
            )

            if pair_res is not None:
                await self._set_cached_pair(
                    t1,
                    t2,
                    as_of_date,
                    pair_res,
                    p_value_threshold,
                    include_spread_series,
                    lookback_days=lookback_days,
                    history_coverage=coverage,
                    cache_generation=cache_generation,
                )
                all_results.append(pair_res)

        # Filter and rank pairs
        # Primary rank: cointegrated first, then ascending p-value
        def rank_key(p: CointPairResult) -> Tuple[int, float]:
            return (0 if p.is_cointegrated else 1, p.engle_granger_pvalue)

        sorted_pairs = sorted(all_results, key=rank_key)

        # max_half_life: a cointegrated pair with missing/oversized OU half-life
        # is filtered OUT of pairs (and the count) so the response invariant
        # count == sum(p.is_cointegrated for p in pairs) holds. Non-cointegrated
        # pairs remain listed (they are never counted).
        def half_life_ok(p: CointPairResult) -> bool:
            if max_half_life is None:
                return True
            return p.ou_half_life_days is not None and p.ou_half_life_days <= max_half_life

        kept_pairs = [
            p for p in sorted_pairs
            if (not p.is_cointegrated) or half_life_ok(p)
        ]
        cointegrated_count = sum(1 for p in kept_pairs if p.is_cointegrated)

        returned_cointegrated = sum(1 for pair in kept_pairs if pair.is_cointegrated)
        returned_universe = {
            ticker
            for pair in kept_pairs
            for ticker in (pair.ticker_a, pair.ticker_b)
        }

        # Pair depth: the reference is the deepest OVERLAP actually analyzed in
        # this scan (a cached pair reports the same overlap it was computed
        # on, so fresh and cached results are treated identically). A pair that
        # clears the absolute gate but covers materially less of that window
        # is published as `partial` instead of silently passing as complete.
        measured_overlaps = [
            int(pair.overlap_observations)
            for pair in kept_pairs
            if isinstance(pair.overlap_observations, int)
            and not isinstance(pair.overlap_observations, bool)
        ]
        reference_overlap = max(measured_overlaps) if measured_overlaps else None
        depths = [
            assess_pair_depth(pair.overlap_observations, reference_overlap)
            for pair in kept_pairs
        ]
        depth_status, depth_limited_count = summarize_pair_depth(depths)
        pairs_with_depth = [
            pair.model_copy(
                update={
                    "depth_ratio": depths[index]["depth_ratio"],
                    "depth_status": depths[index]["status"],
                }
            )
            for index, pair in enumerate(kept_pairs)
        ]

        unpairable = sorted(set(tickers) - returned_universe)
        return CointScannerResponse(
            as_of=as_of_date,
            latest_observation_date=as_of_date,
            as_of_semantics="latest_available_observation",
            universe_size=n,
            requested_universe_size=n,
            scanned_pairs_count=scanned_count,
            analyzed_pairs_count=scanned_count,
            cointegrated_pairs_count=cointegrated_count,
            returned_pairs_count=len(pairs_with_depth),
            returned_cointegrated_pairs_count=returned_cointegrated,
            returned_non_cointegrated_pairs_count=len(pairs_with_depth) - returned_cointegrated,
            unpairable_tickers=unpairable,
            # Depth-limited pairs are real results on thin history, so the
            # section reports `partial` rather than `complete`.
            data_status=(
                "partial"
                if (unpairable or depth_status != "available")
                else "available"
            ),
            usable_observations_by_ticker=ticker_observations,
            minimum_pair_observations=MIN_PAIR_OBSERVATIONS,
            minimum_depth_ratio=MIN_PAIR_DEPTH_RATIO,
            reference_pair_observations=reference_overlap,
            depth_status=depth_status,
            depth_limited_pair_count=depth_limited_count,
            shallow_tickers=thin_tickers,
            test_roles=dict(TEST_ROLES),
            pairs=pairs_with_depth,
        )
