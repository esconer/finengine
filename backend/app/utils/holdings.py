"""
Holding-aware helpers: realized analytics must never attribute pre-purchase
price action to the portfolio.

A portfolio bulk-imported 7 days ago has 7 days of true history, even when
the requested window spans a year. Every helper here is pure (no DB, no I/O)
except resolve_holding_starts; all are deterministic and unit-tested.

Deliberately NOT applied to hypothetical tools (optimize, backtest,
monte-carlo, stress-test, scenario, universe scans): those model "what if we
held X", where full-history simulation is the documented assumption.
"""

from typing import Any, Dict, List, Optional

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
    never constrain the window — their paths stay hypothetical.
    """
    known = [d for d in (active_from or {}).values() if d]
    return max(known) if known else None


def mask_to_holding(frame: pd.DataFrame, active_from: Optional[Dict[str, Optional[str]]]) -> pd.DataFrame:
    """Drop rows before the current composition existed. No-op when unknown.

    Only applies to DatetimeIndex frames; anything else passes through
    untouched (documented, never guessed).
    """
    if frame is None or frame.empty:
        return frame
    eff = effective_start(active_from)
    if eff is None or not isinstance(frame.index, pd.DatetimeIndex):
        return frame
    cutoff = pd.Timestamp(eff).normalize()
    mask = frame.index.normalize() >= cutoff
    return frame.loc[mask]


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
