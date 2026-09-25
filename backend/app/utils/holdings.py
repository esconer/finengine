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

Disclosure vocabulary (V3-06): a window start is only ever published with the
source that produced it — `stored_added_on` (the user's own import date),
`buy_price_inferred` (our buy-price reconstruction, no holding date was ever
stored) or `unknown` — and a position's limited-history status is read from
that position's own return observations, never from a portfolio or global
count. Full-history instrument metrics stay available and are named as
exchange-history measurements that do not lengthen a holding window.
"""

from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Tuple

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

#: Below this many covered trading days, annualized ratios (CAGR, Sharpe,
#: Sortino, Calmar, annualized vol) are not reported (None) — annualizing a
#: week of history fabricates triple-digit percentages.
MIN_ANNUALIZE_DAYS = 30

#: How a holding-window start is known. `stored_added_on` is the date the user
#: actually stored; `buy_price_inferred` is our reconstruction from the buy
#: price (no holding date was ever recorded); `unknown` means neither. A
#: window start is never reported without its source: claiming "held since"
#: for an inferred date invents a holding date the user never entered.
ANALYTICS_START_SOURCE_STORED = "stored_added_on"
ANALYTICS_START_SOURCE_INFERRED = "buy_price_inferred"
ANALYTICS_START_SOURCE_UNKNOWN = "unknown"
ANALYTICS_START_SOURCES = (
    ANALYTICS_START_SOURCE_STORED,
    ANALYTICS_START_SOURCE_INFERRED,
    ANALYTICS_START_SOURCE_UNKNOWN,
)


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


def effective_start_detail(
    holdings: Optional[Dict[str, Dict[str, Any]]],
    frames: Optional[Dict[str, pd.Series]],
    tolerance: float = 0.02,
) -> Dict[str, Dict[str, Optional[str]]]:
    """Per-ticker effective start WITH its provenance (see `effective_starts`).

    Each entry keeps the stored import date and the buy-price inference as
    separate fields plus the single window start they resolve to, so callers
    can disclose *how* the start is known instead of implying a holding date
    that was never stored:

        {"analytics_start": "2026-05-19", "analytics_start_source":
         "buy_price_inferred", "stored_added_on": "2026-06-08",
         "buy_price_inferred": "2026-05-19"}

    The repair rule is unchanged: the earliest known date wins, so a
    re-imported long-held position keeps its reconstructed start.
    """
    out: Dict[str, Dict[str, Optional[str]]] = {}
    for ticker, info in (holdings or {}).items():
        info = info or {}
        added = info.get("added_on")
        implied = None
        if frames is not None and ticker in frames:
            implied = implied_start_from_price(frames[ticker], info.get("buy_price"), added, tolerance)
        if implied and (not added or implied < added):
            start, source = implied, ANALYTICS_START_SOURCE_INFERRED
        elif added:
            start, source = added, ANALYTICS_START_SOURCE_STORED
        else:
            start, source = None, ANALYTICS_START_SOURCE_UNKNOWN
        out[ticker] = {
            "analytics_start": start,
            "analytics_start_source": source,
            "stored_added_on": added,
            "buy_price_inferred": implied,
        }
    return out


def effective_starts(
    holdings: Optional[Dict[str, Dict[str, Any]]],
    frames: Optional[Dict[str, pd.Series]],
    tolerance: float = 0.02,
) -> Dict[str, Optional[str]]:
    """Per-ticker effective start = min(added_on, buy-implied), or None.

    `holdings` maps ticker -> {"added_on": ISO|None, "buy_price": float|None};
    `frames` maps ticker -> raw (unfilled) price series. Tickers missing from
    either map keep whatever date is known (usually just `added_on`).

    Dates only — use `effective_start_detail` when the caller must also
    disclose where the start came from.
    """
    return {
        ticker: detail.get("analytics_start")
        for ticker, detail in effective_start_detail(holdings, frames, tolerance).items()
    }


def holding_window_detail(
    price_data_dict: Optional[Dict[str, pd.Series]],
    holdings: Optional[Dict[str, Dict[str, Any]]],
    tolerance: float = 0.02,
) -> Tuple[Dict[str, pd.Series], Dict[str, Optional[str]], Dict[str, Dict[str, Optional[str]]]]:
    """`holding_window` plus the per-ticker start provenance.

    Returns (masked dict, per-ticker effective starts, per-ticker detail from
    `effective_start_detail`). Masking semantics are identical to
    `holding_window`; only the disclosure is richer.
    """
    detail = effective_start_detail(holdings, price_data_dict, tolerance)
    effectives = {
        ticker: entry.get("analytics_start") for ticker, entry in detail.items()
    }
    eff = effective_start(effectives)
    if not price_data_dict:
        return {}, effectives, detail
    if eff is None:
        return dict(price_data_dict), effectives, detail
    try:
        cutoff = pd.Timestamp(eff).normalize()
    except Exception:
        return dict(price_data_dict), effectives, detail
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
            # Never pass an unmaskable series through: that silently
            # re-attributes pre-purchase action (the failure this module
            # exists to prevent). Warn and leave a visible gap instead.
            logger.warning(
                "holding_window: failed to mask %s to holding window; dropping series",
                ticker, exc_info=True,
            )
    return masked, effectives, detail


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
    masked, effectives, _ = holding_window_detail(price_data_dict, holdings)
    return masked, effectives


def position_limited_history(
    return_observations: Optional[int],
    declared_limited: bool = False,
) -> bool:
    """Is ONE position's own history too short to annualize?

    The gate reads that position's own measured return observations (or the
    feed's own late-listing/partial-coverage declaration). Portfolio-wide and
    global counts are never consulted: a 176-observation book does not make a
    20-observation leg "full history", which is exactly the mislabelling the
    annualization gate exists to prevent.
    """
    if return_observations is None:
        return bool(declared_limited)
    return int(return_observations) < MIN_ANNUALIZE_DAYS or bool(declared_limited)


def annualizable(observations: Optional[int]) -> bool:
    """Annualization gate for a measured return sample (its own count)."""
    return observations is not None and int(observations) >= MIN_ANNUALIZE_DAYS


def holding_coverage(
    active_from: Optional[Dict[str, Optional[str]]],
    start: str,
    end: str,
    covered_days: int,
    per_ticker: Optional[Dict[str, Dict[str, Any]]] = None,
    provenance: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Disclosure payload: how much of the window is true holding history.

    start/end may be non-strings when route functions are invoked directly
    in unit tests (FastAPI Query defaults); only ISO strings participate
    in the truncation comparison, everything else degrades to flags.

    `truncated` compares the INTERSECTION start (newest holding — the date
    the current composition first existed) against the requested start, not
    the oldest holding: a book held for years but rebalanced yesterday only
    has days of realized history for its current composition. `per_ticker`
    optionally carries {"raw_days", "masked_days"} counts per ticker (the
    caller owns the raw/masked frames); without it the per-ticker entries
    still report effective starts with None counts.

    `provenance` is the `effective_start_detail` map. It is purely additive:
    per-ticker entries gain `stored_added_on`, `buy_price_inferred` and
    `analytics_start_source`, and the payload gains
    `effective_start_source` / `intersection_start_source` plus
    `inferred_start_tickers`, so a consumer can tell an inferred analytics
    start from a stored holding date. A start that predates the stored import
    date is labelled inferred, never "held since".

    `limited_history` per ticker is derived from that ticker's OWN
    `return_observations` (`position_limited_history`) whenever the caller
    supplies them, and only falls back to the feed's declaration when the
    count is unmeasured.
    """
    start_s = start if isinstance(start, str) else None
    counts = per_ticker or {}
    prov = provenance or {}
    starts: Dict[str, Optional[str]] = {
        t: (v if isinstance(v, str) else None)
        for t, v in (active_from or {}).items()
    }
    for t, p in prov.items():
        if not starts.get(t) and isinstance(p, Mapping) and isinstance(p.get("analytics_start"), str):
            starts[t] = p["analytics_start"]
    known = {t: d for t, d in starts.items() if d}
    oldest = min(known.values()) if known else None
    intersection = effective_start(starts)
    eff = intersection or start_s
    tickers: Dict[str, Any] = {}
    for t in sorted(set(starts) | set(counts) | set(prov)):
        c = counts.get(t) or {}
        p = prov.get(t) if isinstance(prov.get(t), Mapping) else {}
        entry = {
            "effective_start": starts.get(t),
            "raw_days": c.get("raw_days"),
            "masked_days": c.get("masked_days"),
        }
        for key in ("return_observations", "coverage_reason"):
            if key in c:
                entry[key] = c[key]
        if "limited_history" in c or "return_observations" in c:
            entry["limited_history"] = position_limited_history(
                c.get("return_observations"),
                bool(c.get("limited_history", False)),
            )
        if p:
            entry["stored_added_on"] = p.get("stored_added_on")
            entry["buy_price_inferred"] = p.get("buy_price_inferred")
            entry["analytics_start"] = p.get("analytics_start")
            entry["analytics_start_source"] = p.get("analytics_start_source")
        tickers[t] = entry
    payload = {
        "requested_start": start_s,
        "effective_start": eff,
        "intersection_start": intersection,
        "oldest_holding": oldest,
        "covered_days": int(covered_days),
        "truncated": bool(intersection and start_s and intersection > start_s),
        "annualized": int(covered_days) >= MIN_ANNUALIZE_DAYS,
        "tickers": tickers,
    }
    if prov:
        # The intersection is the newest known start, so its provenance is
        # that of whichever ticker carries that date.
        source = ANALYTICS_START_SOURCE_UNKNOWN
        for p in prov.values():
            if not isinstance(p, Mapping):
                continue
            if p.get("analytics_start") and p.get("analytics_start") == intersection:
                source = p.get("analytics_start_source") or ANALYTICS_START_SOURCE_UNKNOWN
                break
        payload["effective_start_source"] = source
        payload["intersection_start_source"] = source
        payload["inferred_start_tickers"] = sorted(
            t for t, p in prov.items()
            if isinstance(p, Mapping) and p.get("analytics_start_source") == ANALYTICS_START_SOURCE_INFERRED
        )
    return payload


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


def analytics_start_claim(
    start: Optional[str],
    source: Optional[str] = None,
    stored_added_on: Optional[str] = None,
) -> str:
    """One honest phrase for how a holding-window start is known.

    * `stored_added_on`     -> "held since 2026-06-08 (stored import date)"
    * `buy_price_inferred`  -> "analytics start 2026-05-19 is inferred from the
      buy price; no holding date was stored (import stamp 2026-06-08)"
    * no date at all        -> "holding start unknown"

    A date with no declared source is described as an analytics start, never
    as a holding date: an unverified date must not be reported as a fact the
    user stored.
    """
    if not start:
        return "holding start unknown"
    if source == ANALYTICS_START_SOURCE_STORED:
        return f"held since {start} (stored import date)"
    if source == ANALYTICS_START_SOURCE_INFERRED:
        stamp = f" (import stamp {stored_added_on})" if stored_added_on else ""
        return (
            f"analytics start {start} is inferred from the buy price; "
            f"no holding date was stored{stamp}"
        )
    return f"analytics start {start} (provenance not reported)"


def position_history_note(
    ticker: str,
    return_observations: Optional[int] = None,
    analytics_start: Optional[str] = None,
    analytics_start_source: Optional[str] = None,
    stored_added_on: Optional[str] = None,
    buy_price_inferred: Optional[str] = None,
    coverage_reason: Optional[str] = None,
    full_history_days: Optional[int] = None,
    declared_limited: Optional[bool] = None,
) -> str:
    """User-facing per-position history disclosure.

    Every number in this sentence is that position's OWN measured sample
    (return observations), and the start date is described with its
    provenance. Full-history instrument metrics may be named, but only as
    what they are: exchange-history measurements that do not lengthen this
    position's holding window.
    """
    if return_observations is None:
        head = f"{ticker}: own return observations were not measured"
    else:
        head = (
            f"{ticker}: {int(return_observations)} own return "
            f"observation{'' if int(return_observations) == 1 else 's'}"
        )
    parts = [f"{head} — {analytics_start_claim(analytics_start, analytics_start_source, stored_added_on)}"]
    if coverage_reason:
        parts.append(f"Exchange coverage: {coverage_reason}")
    if declared_limited is not None:
        parts.append("Feed reports limited exchange history for this ticker")
    if buy_price_inferred and buy_price_inferred != analytics_start:
        parts.append(f"A later buy-price match on {buy_price_inferred} was not used")
    if full_history_days:
        parts.append(
            f"Instrument risk uses the full {int(full_history_days)} exchange days of price "
            "history, which does not extend this holding window"
        )
    return "; ".join(parts) + "."


def portfolio_regime_summary(sub: pd.Series) -> Dict[str, Any]:
    """Realized stats for returns inside the current regime (pure).

    Below MIN_ANNUALIZE_DAYS the CAGR-style annualization is suppressed
    (ann_ret and ann_vol are None) and only the holding-period total is
    reported, so a week-old book can never display a triple-digit
    "annualized" artefact.
    """
    sub = sub.dropna()
    n = len(sub)
    total = float(np.prod(1.0 + sub.values) - 1.0) if n else 0.0
    ann_v = (
        float(sub.std() * np.sqrt(252))
        if n >= MIN_ANNUALIZE_DAYS and n > 1 and not np.isnan(sub.std())
        else None
    )
    out: Dict[str, Any] = {
        "days": int(n),
        "ann_ret": None,
        "ann_vol": round(ann_v, 4) if ann_v is not None else None,
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
    """ORM added_on (datetime/str/None) -> ISO date string or None.

    Anything that is not a real ISO date (``"abc"``, ``"None"``) is None —
    a truncated junk string must never masquerade as a holding start.
    """
    if value is None:
        return None
    if hasattr(value, "date"):
        try:
            return value.date().isoformat()
        except Exception:
            return None
    try:
        iso = str(value)[:10]
        date.fromisoformat(iso)
        return iso
    except (TypeError, ValueError):
        return None
