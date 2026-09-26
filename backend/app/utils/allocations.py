"""
Shared allocation normalization and execution-instruction helpers.

One documented rule, two consumers
----------------------------------
`AnalyticsEngine.volatility_sizing` publishes an *analytical* risk-parity
target: inverse-volatility weights scaled to a target volatility, so the legs
sum to the scale factor (``1.290041`` in the v3 export) rather than to 1.0.
`POST /api/v1/portfolio/rebalance` publishes an *execution* target that must be
funded from the book's own cash.

The two used to normalize independently, which produced a silent
contradiction: the sizing section reported ``cash_weight = 0`` for a 129 %
risky book (no financing leg anywhere), and rebalance divided any submitted
target by its own sum, so the very same weights could be pushed as a plain
100 % rebalance (V3-03).

The single rule
---------------
Targets are expressed as fractions of **gross exposure** and are normalized by
dividing every leg by that same gross total: relative sizes are preserved and
no leg is invented or dropped. What the resulting gross exposure *means* is
then stated explicitly instead of being implied:

* ``fully_funded`` — gross == 1.0: a normal rebalance, no financing.
* ``financed_gross_exposure_exceeds_100_percent`` — gross > 1.0: the book
  borrows ``gross - 1`` and is **not** executable as a normal rebalance.
* ``unlevered_long_only_plus_cash`` — gross < 1.0: the remainder is cash.
* ``empty_target`` — gross == 0.0: a full exit, not an allocation.

Execution instructions
----------------------
A target is only executable when its notional, its integer share delta, and
the price they were derived from are one auditable triple. `build_sizing_basis`
pins a **single** aligned price date, and `build_trade_instructions` derives
whole shares from the reported notional with a documented half-up rule, then
publishes the leftover as an explicit reconciliation residual. A material
notional that rounds to zero shares is reported as below minimum notional
rather than silently becoming a zero-share instruction (V3-04). A missing
price is `unavailable` — never an assumed price (V3-04).

Everything here is pure and deterministic so the engine, the rebalance
workflow, and the regression tests share one definition.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from app.utils.holdings import MIN_ANNUALIZE_DAYS

__all__ = [
    "WEIGHT_NORMALIZATION_RULE",
    "SHARE_ROUNDING_RULE",
    "TRADE_RECONCILIATION_RULE",
    "GROSS_EXPOSURE_TOLERANCE",
    "AMOUNT_DECIMALS",
    "AMOUNT_ROUNDING_QUANTUM",
    "MIN_SIZING_OBSERVATIONS",
    "MATERIAL_LOT_FRACTION",
    "MIN_MATERIAL_NOTIONAL",
    "half_up",
    "half_up_to",
    "gross_exposure",
    "normalization_block",
    "normalize_rebalance_weights",
    "sizing_history_block",
    "build_sizing_basis",
    "resolve_notional_floor",
    "build_trade_instructions",
]


#: The one weight-normalization rule shared by volatility sizing and rebalance.
WEIGHT_NORMALIZATION_RULE = "divide_all_legs_by_gross_exposure"

#: Integer share deltas round half away from zero. Python's built-in ``round``
#: is banker's rounding (round-half-to-even), which would round 0.5 shares to 0
#: and 2.5 shares to 2 depending on the parity of the floor — not a rule a
#: reader can reproduce by eye.
SHARE_ROUNDING_RULE = "half_up_away_from_zero_to_whole_shares"

#: The invariant a regression fixture asserts for every priced trade.
TRADE_RECONCILIATION_RULE = "shares_delta == half_up(amount / sizing_price)"
# Both reconciliation aggregates describe exactly this population, so a reader
# can compare a residual against a tolerance without wondering which trades each
# one covered.
TRADE_RECONCILIATION_SCOPE = "all_trades_with_a_usable_sizing_price"

#: Gross exposure within this distance of 1.0 counts as fully funded; anything
#: above it needs financing.
GROSS_EXPOSURE_TOLERANCE = 1e-6

#: Notional precision for reported trade amounts.
AMOUNT_DECIMALS = 2

#: Half of the notional quantum. The reported residual is computed from an
#: already-rounded amount, so this is the most the money rounding alone can
#: move it.
AMOUNT_ROUNDING_QUANTUM = 0.5 * (10 ** -AMOUNT_DECIMALS)

#: Minimum return observations before sizing output is treated as sampled from a
#: usable history. Matches the annualization gate so "short history" means the
#: same thing in sizing and in realized-risk disclosures.
MIN_SIZING_OBSERVATIONS = MIN_ANNUALIZE_DAYS

#: A sub-lot notional counts as *material* at this fraction of the sizing
#: budget. Below it, "no trade" is genuinely "no trade".
MATERIAL_LOT_FRACTION = 0.001

#: Absolute floor (in the sizing currency) so a rupee-scale rounding artefact is
#: never promoted into a material "below minimum notional" warning.
MIN_MATERIAL_NOTIONAL = 1.0

_MODE_FULLY_FUNDED = "fully_funded"
_MODE_FINANCED = "financed_gross_exposure_exceeds_100_percent"
_MODE_CASH_RESIDUE = "unlevered_long_only_plus_cash"
_MODE_EMPTY = "empty_target"


# ---------------------------------------------------------------------------
# rounding
# ---------------------------------------------------------------------------
def _decimal(value: Any) -> Optional[Decimal]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    try:
        return Decimal(number)
    except (InvalidOperation, ValueError):  # pragma: no cover - defensive
        return None


def _quantize(number: Decimal, decimals: int) -> Decimal:
    """`number` at `decimals` places, half away from zero.

    The default decimal context carries 28 significant digits, which
    `quantize` refuses to exceed; a large notional would otherwise raise
    instead of rounding. Give it exactly the room this value needs.
    """
    places = int(decimals)
    quantum = Decimal(1).scaleb(-places)
    with localcontext() as ctx:
        ctx.prec = max(28, number.adjusted() + places + 6)
        return number.quantize(quantum, rounding=ROUND_HALF_UP)


def _half_away_from_zero(number: float) -> int:
    """Fallback for magnitudes the decimal context cannot represent."""
    sign = -1.0 if number < 0 else 1.0
    return int(sign * math.floor(abs(float(number)) + 0.5))


def half_up_to(value: Any, decimals: int) -> Optional[float]:
    """Round half away from zero to `decimals` places; None when not finite."""
    number = _decimal(value)
    if number is None:
        return None
    try:
        return float(_quantize(number, decimals))
    except (InvalidOperation, ValueError, OverflowError):  # pragma: no cover
        return round(float(number), int(decimals))


def half_up(value: Any) -> Optional[int]:
    """Whole-share rounding: half away from zero, None when not finite."""
    number = _decimal(value)
    if number is None:
        return None
    try:
        return int(_quantize(number, 0))
    except (InvalidOperation, ValueError, OverflowError):  # pragma: no cover
        return _half_away_from_zero(float(number))


# ---------------------------------------------------------------------------
# the shared normalization rule
# ---------------------------------------------------------------------------
def _clean_weights(weights: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    """Finite entries only; non-finite legs are never silently zeroed."""
    cleaned: Dict[str, float] = {}
    for ticker, value in (weights or {}).items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            cleaned[str(ticker)] = number
    return cleaned


def gross_exposure(weights: Optional[Mapping[str, Any]]) -> float:
    """Gross exposure of a long-only target: sum of absolute leg sizes."""
    return float(sum(abs(value) for value in _clean_weights(weights).values()))


def normalization_block(
    weights: Optional[Mapping[str, Any]],
    *,
    portfolio_value: Optional[float] = None,
    currency: Optional[str] = None,
    weights_normalized: bool = False,
    tolerance: float = GROSS_EXPOSURE_TOLERANCE,
) -> Dict[str, Any]:
    """Describe a target's exposure, financing need, and rebalance eligibility.

    `weights_normalized` records whether the caller actually divided the legs
    by the gross total. The analytical sizing target keeps its gross exposure
    (renormalizing a risk-parity target would silently delete the leverage it
    was asked to quantify), so it passes ``False``; the rebalance workflow
    passes ``True`` because it must trade against a fully funded book.

    `execution_eligible` answers exactly one question: may these weights be
    applied as a plain rebalance? It is false whenever gross exposure exceeds
    100 %, and the financing that would be required is quantified rather than
    hidden in a zero cash weight.
    """
    cleaned = _clean_weights(weights)
    gross = float(sum(abs(value) for value in cleaned.values()))
    tol = max(0.0, float(tolerance))

    if gross <= tol:
        mode = _MODE_EMPTY
    elif gross > 1.0 + tol:
        mode = _MODE_FINANCED
    elif gross < 1.0 - tol:
        mode = _MODE_CASH_RESIDUE
    else:
        mode = _MODE_FULLY_FUNDED

    financing_required = mode == _MODE_FINANCED
    net_cash_weight = 1.0 - gross

    try:
        budget = float(portfolio_value) if portfolio_value is not None else None
    except (TypeError, ValueError):
        budget = None
    if budget is not None and (not math.isfinite(budget) or budget <= 0):
        budget = None

    if not financing_required:
        financing_requirement = 0.0
    elif budget is None:
        financing_requirement = None
    else:
        financing_requirement = half_up_to((gross - 1.0) * budget, AMOUNT_DECIMALS)

    execution_eligible = not financing_required
    block_reasons: List[str] = []
    block_reason: Optional[str] = None
    if financing_required:
        block_reasons.append("financing_required")
        block_reason = (
            f"Gross exposure {gross:.6f} exceeds 1.0; the target borrows "
            f"{gross - 1.0:.6f} of the portfolio value and is not a normal "
            "rebalance"
        )
    elif mode == _MODE_EMPTY:
        block_reasons.append("empty_target")
        block_reason = "Target has no allocation; a full exit, not a rebalance"

    return {
        "normalization_rule": WEIGHT_NORMALIZATION_RULE,
        "normalization_mode": mode,
        "weights_normalized": bool(weights_normalized),
        "gross_exposure": round(gross, 6),
        "net_cash_weight": round(net_cash_weight, 6),
        "financing_required": financing_required,
        "financing_requirement": financing_requirement,
        "financing_requirement_currency": currency,
        "execution_eligible": execution_eligible,
        "block_reasons": block_reasons,
        "block_reason": block_reason,
    }


def normalize_rebalance_weights(
    new_weights: Optional[Mapping[str, Any]],
    *,
    tolerance: float = GROSS_EXPOSURE_TOLERANCE,
) -> Dict[str, Any]:
    """Apply the shared rule to a submitted rebalance target.

    Returns a block whose ``weights`` are what the rebalance workflow must
    execute. A target whose gross exposure exceeds 100 % needs financing the
    rebalance workflow cannot create, so it is *rejected* rather than being
    normalized down into a fully funded book (V3-03): the block then carries a
    ``rejection`` and no usable weights. An all-zero target stays a legal full
    exit and is passed through un-normalized (dividing by zero would erase it).
    """
    submitted = _clean_weights(new_weights)
    gross = gross_exposure(submitted)
    tol = max(0.0, float(tolerance))
    block = normalization_block(submitted)

    if gross > 1.0 + tol:
        return {
            "weights": None,
            "submitted_weights": submitted,
            "submitted_gross_exposure": round(gross, 6),
            "gross_exposure": round(gross, 6),
            "normalization_mode": block["normalization_mode"],
            "weights_normalized": False,
            "financing_required": True,
            "financing_requirement_currency": None,
            "execution_eligible": False,
            "rejection": {
                "code": "financing_required",
                "detail": block["block_reason"],
                "gross_exposure": round(gross, 6),
                "financing_requirement_fraction": round(gross - 1.0, 6),
                "normalization_rule": WEIGHT_NORMALIZATION_RULE,
            },
        }

    if gross <= tol:
        # Full exit: no allocation to normalize.
        return {
            "weights": dict(submitted),
            "submitted_weights": submitted,
            "submitted_gross_exposure": round(gross, 6),
            "gross_exposure": 0.0,
            "normalization_mode": block["normalization_mode"],
            "weights_normalized": False,
            "financing_required": False,
            "financing_requirement_currency": None,
            "execution_eligible": True,
            "rejection": None,
        }

    weights = {ticker: value / gross for ticker, value in submitted.items()}
    return {
        "weights": weights,
        "submitted_weights": submitted,
        "submitted_gross_exposure": round(gross, 6),
        "gross_exposure": 1.0,
        "normalization_mode": _MODE_FULLY_FUNDED,
        "weights_normalized": abs(gross - 1.0) > tol,
        "financing_required": False,
        "financing_requirement_currency": None,
        "execution_eligible": True,
        "rejection": None,
    }


# ---------------------------------------------------------------------------
# history / sample disclosure
# ---------------------------------------------------------------------------
def sizing_history_block(
    returns: pd.DataFrame,
    *,
    price_frame: Optional[pd.DataFrame] = None,
    model: str = "",
    minimum_observations: int = MIN_SIZING_OBSERVATIONS,
) -> Dict[str, Any]:
    """Actual window, observation counts, latest observation, min-sample status.

    The sizing section used to publish annualized volatilities with no window
    evidence at all. `returns` is the frame the engine actually measured, so
    the reported window is the delivered one, not the requested one. A return
    needs two prices, so `window_start`/`window_end` describe the measured
    *return* window while `price_window_start`/`price_window_end` describe the
    delivered price window; they differ by one observation at the start.
    """
    frame = returns if isinstance(returns, pd.DataFrame) else pd.DataFrame()
    prices = price_frame if isinstance(price_frame, pd.DataFrame) else None
    per_ticker: Dict[str, int] = {}
    if not frame.empty:
        for ticker in frame.columns:
            per_ticker[str(ticker)] = int(frame[ticker].notna().sum())

    total = int(len(frame))
    counts = list(per_ticker.values())
    minimum = int(min(counts)) if counts else 0
    maximum = int(max(counts)) if counts else 0
    below = sorted(t for t, count in per_ticker.items() if count < int(minimum_observations))

    latest_label = None
    if not frame.empty:
        non_empty = frame.notna().any(axis=1).to_numpy()
        positions = np.flatnonzero(non_empty)
        if positions.size:
            latest_label = frame.index[int(positions[-1])]

    price_rows = int(len(prices)) if prices is not None and not prices.empty else 0
    return {
        "model": model or None,
        "window_start": _iso_date(frame.index[0]) if total else None,
        "window_end": _iso_date(frame.index[-1]) if total else None,
        "price_window_start": _iso_date(prices.index[0]) if price_rows else None,
        "price_window_end": _iso_date(prices.index[-1]) if price_rows else None,
        "return_observations": total,
        "per_ticker_return_observations": per_ticker,
        "min_return_observations": minimum,
        "max_return_observations": maximum,
        "latest_observation": _iso_date(latest_label),
        "minimum_observations_required": int(minimum_observations),
        "meets_minimum_sample": bool(total >= int(minimum_observations) and not below),
        "minimum_sample_status": "sufficient"
        if total >= int(minimum_observations) and not below
        else "insufficient",
        "tickers_below_minimum_sample": below,
    }


# ---------------------------------------------------------------------------
# sizing price basis
# ---------------------------------------------------------------------------
def _iso_date(label: Any) -> Optional[str]:
    """ISO date for a real date-ish index label; None for positional labels.

    A RangeIndex label is a row number, not a date. Converting it would
    fabricate a freshness claim the data cannot support.
    """
    if label is None or isinstance(label, bool):
        return None
    if isinstance(label, (int, float, np.integer, np.floating)):
        return None
    try:
        if isinstance(label, float) and math.isnan(label):
            return None
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None
    try:
        if isinstance(label, np.datetime64):
            stamp = pd.Timestamp(label)
        elif isinstance(label, (pd.Timestamp, datetime, date, pd.Period)):
            stamp = pd.Timestamp(label)
        elif isinstance(label, str):
            stamp = pd.Timestamp(label)
        else:
            return None
    except (ValueError, TypeError, OverflowError):
        return None
    if stamp is None or pd.isna(stamp):
        return None
    return stamp.date().isoformat()


def build_sizing_basis(
    price_frame: Optional[pd.DataFrame],
    tickers: Optional[Sequence[str]] = None,
    *,
    currency: Optional[str] = None,
) -> Dict[str, Any]:
    """Pin ONE aligned price date for the whole sizing basis.

    The last row on which every requested ticker has a finite positive price is
    the snapshot. Mixing per-ticker "last known" prices would let one leg trade
    at a stale date while the report claims a single `sizing_price_as_of`, and
    an assumed price (the retired 100.0 fallback) is worse than no price at
    all. When no such row exists the basis is `unavailable` and the caller
    reports no executable amounts.
    """
    requested = [str(t) for t in (tickers or [])]
    empty = {
        "sizing_price": {},
        "sizing_price_as_of": None,
        "sizing_price_currency": currency,
        "sizing_price_provenance": "unavailable",
        "sizing_price_unavailable_reason": "no_aligned_price_snapshot",
        "missing_tickers": list(requested),
        "unpriced_tickers": [],
        "portfolio_value": None,
        "portfolio_value_currency": currency,
    }
    if not isinstance(price_frame, pd.DataFrame) or price_frame.empty or not requested:
        if not requested:
            empty["sizing_price_unavailable_reason"] = "no_requested_tickers"
            empty["missing_tickers"] = []
            empty["unpriced_tickers"] = []
        return empty

    missing = [ticker for ticker in requested if ticker not in price_frame.columns]
    frame = price_frame.reindex(columns=requested)
    frame = frame.replace([np.inf, -np.inf], np.nan)
    try:
        frame = frame.apply(lambda column: pd.to_numeric(column, errors="coerce"))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return empty

    valid = frame.notna() & (frame > 0)
    complete = valid.all(axis=1).to_numpy()
    positions = np.flatnonzero(complete)
    if not positions.size:
        empty["missing_tickers"] = missing
        empty["unpriced_tickers"] = [
            ticker for ticker in requested if not bool(valid[ticker].any())
        ]
        return empty

    snapshot = frame.iloc[int(positions[-1])]
    prices: Dict[str, float] = {}
    for ticker, value in snapshot.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            prices[str(ticker)] = number

    return {
        "sizing_price": prices,
        "sizing_price_as_of": _iso_date(frame.index[int(positions[-1])]),
        "sizing_price_currency": currency,
        "sizing_price_provenance": "measured",
        "sizing_price_unavailable_reason": None,
        "missing_tickers": missing,
        "unpriced_tickers": [],
        "portfolio_value": None,
        "portfolio_value_currency": currency,
    }


# ---------------------------------------------------------------------------
# trade instructions
# ---------------------------------------------------------------------------
def resolve_notional_floor(
    portfolio_value: Optional[float] = None,
    *,
    override: Optional[float] = None,
) -> float:
    """Notional at which a zero-share rounding is worth reporting.

    Materiality is relative to the sizing budget (0.1 %) with an absolute
    currency floor, so a small book does not flag every sub-lot trade.
    """
    if override is not None:
        try:
            candidate = abs(float(override))
        except (TypeError, ValueError):
            candidate = 0.0
        return candidate
    floor = MIN_MATERIAL_NOTIONAL
    try:
        budget = float(portfolio_value) if portfolio_value is not None else None
    except (TypeError, ValueError):
        budget = None
    if budget is not None and math.isfinite(budget) and budget > 0:
        floor = max(floor, budget * MATERIAL_LOT_FRACTION)
    return float(floor)


def _price_of(prices: Optional[Mapping[str, Any]], ticker: str) -> Optional[float]:
    try:
        number = float((prices or {}).get(ticker))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def build_trade_instructions(
    weight_deltas: Optional[Mapping[str, Any]],
    sizing_prices: Optional[Mapping[str, Any]] = None,
    *,
    portfolio_value: Optional[float] = None,
    currency: Optional[str] = None,
    sizing_price_as_of: Optional[str] = None,
    sizing_price_provenance: str = "measured",
    notional_floor: Optional[float] = None,
) -> Dict[str, Any]:
    """Turn weight deltas into auditable, integer-share trade instructions.

    The reported notional is the number divided by the sizing price, so the
    triple reconciles exactly:

        shares_delta = half_up(amount / sizing_price)
        rounding_residual = amount - shares_delta * sizing_price

    `rounding_residual` is the money the whole-share rule cannot trade. When a
    *material* notional rounds to zero shares, the trade is reported as
    `below_minimum_notional` with its notional intact — never as a silent
    zero-share instruction.
    """
    deltas = _clean_weights(weight_deltas)
    try:
        budget = float(portfolio_value) if portfolio_value is not None else None
    except (TypeError, ValueError):
        budget = None
    if budget is not None and (not math.isfinite(budget) or budget <= 0):
        budget = None
    floor = resolve_notional_floor(budget, override=notional_floor)

    trades: Dict[str, Dict[str, Any]] = {}
    below_minimum: List[str] = []
    immaterial: List[str] = []
    unavailable: List[str] = []
    residuals: List[float] = []
    tolerances: List[float] = []
    residuals_by_ticker: Dict[str, float] = {}
    tolerances_by_ticker: Dict[str, float] = {}
    priced = 0
    reconciled = True

    for ticker, delta in deltas.items():
        price = _price_of(sizing_prices, ticker)
        entry: Dict[str, Any] = {
            "shares_delta": None,
            "amount": None,
            "amount_currency": currency,
            "sizing_price": price,
            "rounding_residual": None,
            "below_minimum_notional": False,
            "status": "executable",
            "reason": None,
        }
        if budget is None:
            entry["status"] = "unavailable"
            entry["reason"] = "portfolio_value_unavailable"
            unavailable.append(ticker)
            trades[ticker] = entry
            continue

        amount = half_up_to(delta * budget, AMOUNT_DECIMALS)
        entry["amount"] = amount
        if price is None:
            # The notional is knowable; the whole-share instruction is not.
            entry["status"] = "unavailable"
            entry["reason"] = "sizing_price_unavailable"
            unavailable.append(ticker)
            trades[ticker] = entry
            continue

        shares = half_up(amount / price)
        residual = half_up_to(amount - (shares or 0) * price, AMOUNT_DECIMALS)
        # Half a share, plus half of the notional quantum the residual was
        # reported at: for a sub-paisa price the money rounding, not the share
        # rounding, is the coarser of the two.
        tolerance = 0.5 * price
        tolerance_bound = tolerance + AMOUNT_ROUNDING_QUANTUM
        entry["shares_delta"] = shares
        entry["rounding_residual"] = residual
        entry["rounding_tolerance"] = round(tolerance, 6)
        priced += 1
        if shares:
            entry["status"] = "executable"
        elif abs(amount) >= floor:
            entry["status"] = "below_minimum_notional"
            entry["below_minimum_notional"] = True
            # The notional is ABOVE the floor; what happened is the notional
            # rounding below one whole share. Say that, rather than leaving
            # `reason` null and implying nothing was wrong.
            entry["reason"] = (
                f"notional {abs(amount):.2f} is below one whole share at "
                f"{price:.4f}, so the instruction rounds to zero shares"
            )
            below_minimum.append(ticker)
        elif amount:
            entry["status"] = "immaterial_no_op"
            entry["reason"] = (
                f"notional {abs(amount):.2f} is below the {floor:.2f} minimum "
                "order notional"
            )
            immaterial.append(ticker)
        else:
            entry["status"] = "no_trade_required"
            entry["reason"] = "target weight already met; no trade is required"

        if residual is not None:
            residuals.append(abs(float(residual)))
            tolerances.append(float(tolerance))
            residuals_by_ticker[ticker] = abs(float(residual))
            tolerances_by_ticker[ticker] = float(tolerance)
        if abs(float(residual or 0.0)) - float(tolerance_bound) > 1e-9:
            reconciled = False
        trades[ticker] = entry

    if not priced:
        status = "unavailable"
    elif not reconciled:
        status = "not_reconciled"
    else:
        status = "reconciled"

    return {
        "trades": trades,
        "status": status,
        "share_rounding_rule": SHARE_ROUNDING_RULE,
        "reconciliation": {
            "rule": TRADE_RECONCILIATION_RULE,
            "share_rounding_rule": SHARE_ROUNDING_RULE,
            "amount_decimals": AMOUNT_DECIMALS,
            "amount_rounding_quantum": AMOUNT_ROUNDING_QUANTUM,
            "notional_floor": floor,
            "notional_floor_currency": currency,
            "sizing_price_as_of": sizing_price_as_of,
            "sizing_price_provenance": sizing_price_provenance,
            "reconciled": bool(priced) and reconciled,
            "priced_trades": priced,
            "max_abs_rounding_residual": round(max(residuals), AMOUNT_DECIMALS)
            if residuals
            else None,
            # Both aggregates describe the same population: every trade that had
            # a usable sizing price. The maximum is the bound that certifies the
            # residual, so publishing the MINIMUM here understated the very
            # tolerance this field exists to state, by ~139x on a real book.
            "reconciliation_scope": TRADE_RECONCILIATION_SCOPE,
            "max_rounding_tolerance": round(max(tolerances), 6) if tolerances else None,
            "min_rounding_tolerance": round(min(tolerances), 6) if tolerances else None,
            "tolerance_breach_tickers": sorted(
                ticker
                for ticker, residual in residuals_by_ticker.items()
                if abs(residual) > tolerances_by_ticker.get(ticker, float("inf")) + 1e-9
            ),
            "below_minimum_notional_tickers": below_minimum,
            "immaterial_no_op_tickers": immaterial,
            "unavailable_tickers": unavailable,
        },
        "basis": {
            "sizing_price": dict(sizing_prices or {}),
            "sizing_price_as_of": sizing_price_as_of,
            "sizing_price_currency": currency,
            "sizing_price_provenance": sizing_price_provenance,
            "portfolio_value": budget,
            "portfolio_value_currency": currency,
        },
    }
