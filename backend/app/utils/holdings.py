"""
Holding-aware helpers: realized analytics must never attribute pre-purchase
price action to the portfolio.

A portfolio bulk-imported 7 days ago has 7 days of true history, even when
the requested window spans a year. `resolve_holdings` (DB layer) lives in
`app/api/analytics.py`; everything else here is pure, deterministic and
unit-tested.

Deliberately NOT applied to hypothetical tools (optimize, backtest,
monte-carlo, stress-test, scenario, universe scans): those model "what if we
held X", where full-history simulation is the documented assumption.
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

#: Below this many covered trading days, annualized ratios (CAGR, Sharpe,
#: Sortino, Calmar, annualized vol) are not reported (None) — annualizing a
#: week of history fabricates triple-digit percentages.
MIN_ANNUALIZE_DAYS = 30


def effective_start(active_from: Optional[Dict[str, Optional[str]]]) -> Optional[str]:
    """Latest holding start (ISO date) across tickers, or None if unknown.

    Intersection semantics: the current composition only existed since the
    most recently added position. Ad-hoc tickers (not in DB) carry None and
    never constrain the window — those paths stay hypothetical.
    """
    known = [d for d in (active_from or {}).values() if d]
    return max(known) if known else None


def implied_start_from_price(
    price_series: Optional[pd.Series],
    buy_price: Any,
    added_on: Optional[str],
    tolerance: float = 0.02,
) -> Optional[str]:
    """Most recent pre-import date when close was within tolerance of buy_price.

    Import stamps (`added_on`) reset on delete+re-import while users re-type
    the original cost basis, so `added_on` alone backdates young rows and
    forward-dates old ones. The buy-implied date repairs the old-holding
    case; biased toward understating (most-recent match wins). Returns None
    when buy_price is missing/invalid, no bar matches, or splits/dividends
    broke comparability (unadjusted cost vs adjusted closes) — callers fall
    back to `added_on`.
    """
    try:
        target = float(buy_price)
    except (TypeError, ValueError):
        return None
    if not target or target <= 0 or price_series is None or len(price_series) == 0:
        return None
    try:
        frame = pd.DataFrame({"close": pd.to_numeric(price_series, errors="coerce")})
        frame.index = pd.to_datetime(price_series.index, errors="coerce")
        frame = frame.dropna()
        if getattr(frame.index, "tz", None) is not None:
            frame.index = frame.index.tz_localize(None)
        frame.index = frame.index.normalize()
        if added_on is not None:
            cutoff = pd.Timestamp(added_on).normalize()
            frame = frame[frame.index < cutoff]
        rel = (frame["close"] - target).abs() / target
        hits = frame[rel <= tolerance]
        if hits.empty:
            return None
        return hits.index.max().date().isoformat()
    except Exception:
        return None


def effective_starts(
    holdings: Optional[Dict[str, Dict[str, Any]]],
    frames: Optional[Dict[str, pd.Series]],
    tolerance: float = 0.02,
) -> Dict[str, Optional[str]]:
    """Per-ticker effective start = min(added_on, buy-implied), or None.

    `holdings` maps ticker -> {"added_on": ISO|None, "buy_price": float|None};
    `frames` maps ticker -> raw (unfilled) price series. Tickers missing from
    either map keep whatever date is known (usually just `added_on`).
    """
    out: Dict[str, Optional[str]] = {}
    for ticker, info in (holdings or {}).items():
        info = info or {}
        added = info.get("added_on")
        implied = None
        if frames is not None and ticker in frames:
            implied = implied_start_from_price(frames[ticker], info.get("buy_price"), added, tolerance)
        cands = [d for d in (added, implied) if d]
        out[ticker] = min(cands) if cands else None
    return out


def holding_window(
    price_data_dict: Optional[Dict[str, pd.Series]],
    holdings: Optional[Dict[str, Dict[str, Any]]],
) -> Tuple[Dict[str, pd.Series], Dict[str, Optional[str]]]:
    """Mask every series to the shared effective start (intersection).

    Returns (masked dict, per-ticker effective starts). Empty when nothing
    held in-window. The cutoff applies to the whole dict: portfolio math
    needs aligned dates, so a hypothetical ticker analyzed alongside owned
    holdings shares the owned window. Pure ad-hoc calls (holdings empty)
    pass through fully hypothetical.
    """
    effectives = effective_starts(holdings, price_data_dict)
    eff = effective_start(effectives)
    if not price_data_dict:
        return {}, effectives
    if eff is None:
        return dict(price_data_dict), effectives
    try:
        cutoff = pd.Timestamp(eff).normalize()
    except Exception:
        return dict(price_data_dict), effectives
    masked: Dict[str, pd.Series] = {}
    for ticker, series in price_data_dict.items():
        if series is None or len(series) == 0:
            continue
        if not isinstance(series.index, pd.DatetimeIndex):
            # Dateless frames carry no holding information: pass through
            # untouched (same rule as mask_to_holding), never guessed.
            masked[ticker] = series
            continue
        try:
            idx = series.index
            if idx.tz is not None:
                idx = idx.tz_localize(None)
            keep = idx.normalize() >= cutoff  # ndarray bool mask
            s = series.loc[keep]
            if len(s):
                masked[ticker] = s
        except Exception:
            masked[ticker] = series
    return masked, effectives


def holding_coverage(
    active_from: Optional[Dict[str, Optional[str]]],
    start: str,
    end: str,
    covered_days: int,
) -> Dict[str, Any]:
    """Disclosure payload: how much of the window is true holding history.

    start/end may be non-strings when route functions are invoked directly
    in unit tests (FastAPI Query defaults); only ISO strings participate
    in the truncation comparison, everything else degrades to flags.
    """
    start_s = start if isinstance(start, str) else None
    known = {t: d for t, d in (active_from or {}).items() if d}
    oldest = min(known.values()) if known else None
    eff = effective_start(active_from) or start_s
    return {
        "requested_start": start_s,
        "effective_start": eff,
        "oldest_holding": oldest,
        "covered_days": int(covered_days),
        "truncated": bool(oldest and start_s and oldest > start_s),
        "annualized": int(covered_days) >= MIN_ANNUALIZE_DAYS,
    }


def apply_annualization_gate(
    payload: Dict[str, Any],
    annual_keys: List[str],
    covered_days: int,
) -> Dict[str, Any]:
    """Null annualized ratios when history is too short; always flags."""
    payload["annualized"] = int(covered_days) >= MIN_ANNUALIZE_DAYS
    if int(covered_days) < MIN_ANNUALIZE_DAYS:
        for key in annual_keys:
            if key in payload:
                payload[key] = None
    return payload


def portfolio_regime_summary(sub: pd.Series) -> Dict[str, Any]:
    """Realized stats for returns inside the current regime (pure).

    Below MIN_ANNUALIZE_DAYS the CAGR-style annualization is suppressed
    (ann_ret None) and only the holding-period total is reported, so a
    week-old book can never display a triple-digit "annualized" artefact.
    """
    sub = sub.dropna()
    n = len(sub)
    total = float(np.prod(1.0 + sub.values) - 1.0) if n else 0.0
    ann_v = float(sub.std() * np.sqrt(252)) if n > 1 and not np.isnan(sub.std()) else 0.0
    out: Dict[str, Any] = {
        "days": int(n),
        "ann_ret": None,
        "ann_vol": round(ann_v, 4),
        "total_ret": round(total, 4),
        "annualized": False,
    }
    if n >= MIN_ANNUALIZE_DAYS:
        cum_p = float(np.prod(1.0 + sub.values))
        port_cagr = float((cum_p ** (252.0 / n)) - 1.0) if cum_p > 0 else float(sub.mean() * 252)
        out["ann_ret"] = round(port_cagr, 4)
        out["annualized"] = True
    return out


def coerce_holding_date(value: Any) -> Optional[str]:
    """ORM added_on (datetime/str/None) -> ISO date string or None."""
    if value is None:
        return None
    if hasattr(value, "date"):
        try:
            return value.date().isoformat()
        except Exception:
            return None
    try:
        return str(value)[:10] or None
    except Exception:
        return None
