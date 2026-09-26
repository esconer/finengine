"""
Portfolio API endpoints for portfolio management operations
"""

import asyncio
import inspect
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
import csv
import io

from app.db.database import get_db_session
from app.services.data_service import GlobalDataService, DataService, canonical_ticker
from app.models.database import PortfolioPosition, StockTimeseries
from app.models.schemas import (
    PortfolioPositionCreate, PortfolioPositionUpdate, PortfolioPositionResponse,
    PortfolioSummaryResponse, BulkAddRequest, BulkAddResponse,
    SuccessResponse
)
from app.services.currency_service import (
    CurrencyUnavailableError,
    coerce_live_fx_rate,
    get_currency_service,
)
from app.services.cache_service import ProviderError
from app.utils.allocations import (
    WEIGHT_NORMALIZATION_RULE,
    normalize_rebalance_weights,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Valid ticker format: alphanumeric scrip codes with hyphens/ampersands and
# optional exchange suffixes (3MINDIA.NS, BAJAJ-AUTO.NS, 500112.BO, BRK.B).
# Mirrors the frontend regex in AddPositionModalSimple.
_TICKER_PATTERN = re.compile(r"^[A-Z0-9\-\&\.]{1,20}$")

# Create router
router = APIRouter()


# The currency service currently has a deliberately small, explicit rate
# surface.  Keep the API contract in lock-step with that surface: advertising
# EUR/GBP/JPY/AED would turn a client mistake into a provider error.
_SUPPORTED_CURRENCIES = frozenset({"INR", "USD"})
_DEFAULT_BASE_CURRENCY = "INR"


class PortfolioPositionEnvelope(PortfolioPositionResponse):
    """A position row plus the date its mark is actually measured against.

    AD-16: `last_price` was published beside `updated_on`, which is a quote
    WRITE clock, and beside nothing that says which delivered daily bar the mark
    belongs to. A reader could not check whether two sections pricing the same
    ticker used the same instant, so the disagreement could only be asserted
    globally ("best_effort") instead of located per position. `price_as_of` makes
    it local: two rows are comparable exactly when this field matches.
    """

    #: Newest DELIVERED daily bar date for this one ticker, or null when no bar
    #: has been delivered for it. Never the quote write clock and never the
    #: book-wide `as_of`.
    price_as_of: Optional[str] = None
    price_as_of_semantics: Optional[str] = None


class PortfolioSummaryEnvelope(PortfolioSummaryResponse):
    """Existing summary fields plus an explicit monetary-unit contract."""

    currency: str
    base_currency: str
    currency_provenance: Dict[str, Any] = Field(default_factory=dict)
    position_currencies: Dict[str, str] = Field(default_factory=dict)
    holding_date_provenance: Dict[str, Any] = Field(default_factory=dict)
    as_of: Optional[str] = None
    as_of_semantics: Optional[str] = None
    valuation_refreshed_at: Optional[str] = None
    # AD-16: replaces a one-word adjective. Every price instant used to value the
    # book is counted and bounded here, per clock, instead of being asserted to
    # have lined up.
    snapshot_consistency: Dict[str, Any] = Field(default_factory=dict)
    # AD-8: what these numbers are gross OF, stated once so a reader acting on a
    # per-position P&L or a book total knows the costs that are absent.
    accounting_basis: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class BulkAddEnvelope(BulkAddResponse):
    """Compatible bulk response extension; schemas.py remains owner-owned."""

    submitted: int = 0
    skipped: int = 0
    duplicates: List[str] = Field(default_factory=list)
    failures: List[Dict[str, str]] = Field(default_factory=list)


# Dependency injection
def get_data_service(db: AsyncSession = Depends(get_db_session)) -> DataService:
    """Get data service instance"""
    return GlobalDataService(db).get_service()


def _normalise_currency(value: Any) -> str:
    """Validate the public response currency without accepting fake Query defaults."""
    if not isinstance(value, str) or not value.strip():
        return _DEFAULT_BASE_CURRENCY
    currency = value.strip().upper()
    if currency not in _SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"Unsupported currency: {currency}")
    return currency


#: What `PortfolioSummaryEnvelope.as_of` measures once the two clocks are split.
#: The section names it, so a reader never has to infer it from the shape of the
#: value.
#: What the portfolio's own money figures are. Published on the envelope so a
#: reader knows whether the numbers they are about to act on are gross or net.
PORTFOLIO_ACCOUNTING_BASIS = "gross_of_all_transaction_costs_and_tax_unadjusted_prices"

PORTFOLIO_AS_OF_SEMANTICS = "last_delivered_daily_close_date_for_the_held_universe"

PORTFOLIO_VALUATION_BASIS = "live_quote_last_price_per_position"

#: `positions[].price_as_of` means exactly this and nothing else. It is the
#: book-wide `as_of` resolved to ONE ticker, so a reader can compare two rows -
#: or a row against another section - without inferring anything from a shape.
PORTFOLIO_PRICE_AS_OF_SEMANTICS = "newest_delivered_daily_bar_date_for_this_ticker"

#: The two clocks this section uses to value the book, named once so
#: `snapshot_consistency` keys are self-describing rather than cryptic.
PORTFOLIO_MARK_CLOCK = "live_quote_write_clock"
PORTFOLIO_BAR_CLOCK = "delivered_daily_bar_date"


def _portfolio_freshness_warnings(
    as_of: Optional[str], refreshed_at: Optional[str]
) -> List[str]:
    """The two-clock disclosure the section would otherwise lose.

    `as_of` used to be a quote/update timestamp written during the request, which
    is honest data with an honest meaning and a misleading NAME. Splitting the
    clocks fixes the name, and this sentence keeps the meaning: the position
    values are live quotes, so the market data behind them has no observation
    date, and the instant they were refreshed is published beside the date
    rather than in place of it.
    """
    warnings: List[str] = []
    if refreshed_at:
        warnings.append(
            f"Position values are live quotes refreshed at {refreshed_at} during "
            "this request, so the quote itself carries no observation date; "
            + (
                f"as_of {as_of} is the newest DELIVERED daily close date for the "
                "held universe and is a separate measurement"
                if as_of
                else "no delivered daily bar exists for the held universe, so this "
                "section publishes no as_of at all"
            )
        )
    return warnings


def _price_instant_warnings(consistency: Dict[str, Any]) -> List[str]:
    """Name the disagreement `as_of` cannot express, when there is one.

    A single book-wide date can only ever name the NEWEST delivered bar. If the
    held universe was delivered to more than one date, that one value silently
    dates the newest leg and misdates every other one, so the spread is stated
    here rather than left for a reader to infer from `positions[].price_as_of`.
    """
    bar = (consistency.get("price_clocks") or {}).get(PORTFOLIO_BAR_CLOCK) or {}
    if int(bar.get("distinct_instants") or 0) > 1:
        return [
            f"The held universe spans {bar['distinct_instants']} distinct delivered "
            f"daily bar dates ({bar.get('oldest')} to {bar.get('newest')}, "
            f"{bar.get('spread')} calendar days): as_of "
            f"{bar.get('newest')} dates only the newest leg, and the stale legs sit "
            "on the older instants named in "
            "snapshot_consistency.price_clocks."
            f"{PORTFOLIO_BAR_CLOCK}.positions_at_each_instant."
        ]
    return []


def _utc_stamp(value: Any) -> Optional[str]:
    """One naive-or-aware datetime as a UTC ISO-8601 instant, or None."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _quote_refresh_instant(positions: List[PortfolioPosition]) -> Optional[str]:
    """Newest persisted quote WRITE time, for refresh provenance only.

    This is a database write clock, not an observation date: it is re-stamped
    every time this route refreshes a stale leg, and it is written DURING the
    export, so a value built from it is necessarily later than the envelope that
    contains it. It belongs in `valuation_refreshed_at` and nowhere else.
    """
    values = [
        stamp
        for stamp in (
            _utc_stamp(getattr(position, "updated_on", None)) for position in positions
        )
        if stamp
    ]
    return max(values) if values else None


async def _delivered_close_dates(
    db: AsyncSession, tickers: List[str]
) -> Dict[str, str]:
    """Newest stored daily bar date PER TICKER, keyed by ticker.

    `_latest_delivered_close_date` used to take one `max()` over the whole
    universe. That is a single number standing in for up to N distinct price
    instants: if one held name delivered through the 25th and another only
    through the 22nd, the book published the 25th and the 3-day gap vanished.
    Grouping by ticker keeps the identical column and the identical clock and
    refuses to average a spread away.

    `StockTimeseries.date` is an exchange session date, so every value here is a
    real observation made before any refresh could run. An empty table, a
    lookup failure, or a ticker with no delivered bar yields an absent entry -
    never a borrowed clock.
    """
    candidates = sorted({t for t in tickers if isinstance(t, str) and t.strip()})
    if not candidates:
        return {}
    latest: Dict[str, str] = {}
    try:
        result = await db.execute(
            select(StockTimeseries.ticker, func.max(StockTimeseries.date))
            .where(StockTimeseries.ticker.in_(candidates))
            .group_by(StockTimeseries.ticker)
        )
        for row in result.all():
            ticker, value = row[0], row[1]
            if not isinstance(ticker, str) or not isinstance(value, datetime):
                continue
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            latest[ticker] = value.date().isoformat()
    except Exception:
        logger.warning("Portfolio observation date lookup failed")
        return {}
    return latest


async def _latest_delivered_close_date(
    db: AsyncSession, tickers: List[str]
) -> Optional[str]:
    """Newest stored daily bar date across the held universe: a real observation.

    Retained as the book-wide roll-up of `_delivered_close_dates`, so the one
    value that `as_of` publishes is derived from exactly the per-ticker map the
    section now discloses rather than from a second, independent query.
    """
    dates = await _delivered_close_dates(db, tickers)
    return max(dates.values()) if dates else None


def _holding_date_provenance() -> Dict[str, Any]:
    return {
        "added_on": "PortfolioPosition.added_on (stored import date)",
        "updated_on": "PortfolioPosition.updated_on (persisted quote timestamp)",
        "effective_start": (
            "Analytics holding_window uses the earliest valid added_on or "
            "buy-price-implied start; it is not the quote timestamp."
        ),
        "quote_timestamp_timezone": (
            "updated_on is a naive datetime column and carries no offset. "
            "valuation_refreshed_at renders it as UTC (a trailing Z) so the "
            "envelope stays ISO-parseable; the UTC designation is an "
            "interpretation, not a stored fact."
        ),
        "as_of": (
            "as_of is the newest DELIVERED daily close date across the held "
            f"tickers ({PORTFOLIO_AS_OF_SEMANTICS}), read from "
            "StockTimeseries.date. It is a real observation date and it always "
            "precedes the refresh that produced this response."
        ),
        "valuation_refreshed_at": (
            "valuation_refreshed_at is the newest PortfolioPosition.updated_on: "
            "the instant the newest quote was WRITTEN to the database during "
            "this request. It is a refresh clock, not an observation date, and it "
            "can be later than the response that contains it. Position values "
            f"are live quotes ({PORTFOLIO_VALUATION_BASIS}), so the market data "
            "itself has no observation date; the two fields are deliberately "
            "separate."
        ),
        "price_as_of": (
            "positions[].price_as_of is "
            f"{PORTFOLIO_PRICE_AS_OF_SEMANTICS}. It resolves the book-wide as_of "
            "to one ticker so two marks can be compared directly; it is the only "
            "per-position price date, and a null means NO bar has been delivered "
            "for that ticker rather than a fall-back to a neighbour's date."
        ),
    }


def _mark_clock_block(positions: List[PortfolioPosition]) -> Dict[str, Any]:
    """Every instant at which a PUBLISHED MARK was written, counted.

    `_update_portfolio_prices` re-stamps each refreshed leg with its own
    `datetime.now()`, so a 14-position book refreshed from a 15-minute-stale
    state is written at 14 distinct instants, not one. That is not a bug and it
    is not hidden here either: the count and the span are published so a reader
    knows the book is a set of asynchronously fetched quotes, and so a later
    reconciliation against another section can be scoped to seconds rather than
    days.
    """
    stamps: Dict[str, str] = {}
    for position in positions:
        ticker = getattr(position, "ticker", None)
        if not isinstance(ticker, str) or not ticker:
            continue
        stamp = _utc_stamp(getattr(position, "updated_on", None))
        if stamp:
            stamps[ticker] = stamp
    distinct = sorted(set(stamps.values()))
    block: Dict[str, Any] = {
        "clock": PORTFOLIO_MARK_CLOCK,
        "source": "PortfolioPosition.updated_on (quote write time, per leg)",
        "measures": (
            "The instant each position's last_price was written. A database "
            "write clock, not an observation date: it is restamped on every "
            "refresh and is always later than the delivered bar it is dated "
            "against."
        ),
        "distinct_instants": len(distinct),
        "oldest": distinct[0] if distinct else None,
        "newest": distinct[-1] if distinct else None,
        "spread_unit": "seconds",
        "spread": None,
        "per_ticker": dict(sorted(stamps.items())),
    }
    if len(distinct) >= 2:
        oldest = datetime.fromisoformat(distinct[0].replace("Z", "+00:00"))
        newest = datetime.fromisoformat(distinct[-1].replace("Z", "+00:00"))
        block["spread"] = round((newest - oldest).total_seconds(), 6)
    return block


def _bar_clock_block(
    price_as_of: Dict[str, str], held_tickers: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Every delivered daily bar date in the book, counted and attributed.

    This is the clock the export's cross-section staleness is really made of: a
    reader comparing this ticker against another section's mark needs to know
    which leg is the stale one, and `as_of` can only ever name the newest.

    `held_tickers` is the full roster. The grouped query only returns tickers
    that HAVE a bar, so without the roster a leg with no delivered bar at all
    would be indistinguishable from a leg that is not held - and the count of
    distinct instants would silently exclude the leg that cannot be dated.
    """
    roster = sorted({
        t for t in list(held_tickers or []) + list(price_as_of)
        if isinstance(t, str) and t
    })
    resolved: Dict[str, Optional[str]] = {t: None for t in roster}
    for ticker, value in price_as_of.items():
        if isinstance(ticker, str) and ticker:
            resolved[ticker] = value if isinstance(value, str) and value else None
    per_date: Dict[str, List[str]] = {}
    for ticker, value in sorted(resolved.items()):
        if value:
            per_date.setdefault(value, []).append(ticker)
    dates = sorted(per_date)
    undated = sorted(ticker for ticker, value in resolved.items() if not value)
    spread: Optional[int] = None
    if len(dates) >= 2:
        try:
            spread = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days
        except ValueError:
            spread = None
    return {
        "clock": PORTFOLIO_BAR_CLOCK,
        "source": "max(StockTimeseries.date) grouped by ticker",
        "measures": (
            "The exchange session date of the newest daily bar DELIVERED for each "
            "held ticker. A real observation date that always precedes the quote "
            "refresh above."
        ),
        "semantics": PORTFOLIO_PRICE_AS_OF_SEMANTICS,
        "distinct_instants": len(dates),
        "oldest": dates[0] if dates else None,
        "newest": dates[-1] if dates else None,
        "spread_unit": "calendar_days",
        "spread": spread,
        "positions_at_each_instant": {key: per_date[key] for key in dates},
        "positions_without_a_delivered_bar": undated,
        "per_ticker": dict(sorted(resolved.items())),
    }


def _price_snapshot_consistency(
    positions: List[PortfolioPosition], price_as_of: Dict[str, str]
) -> Dict[str, Any]:
    """AD-16: measure the price spread instead of asserting it did not happen.

    The export published `snapshot_consistency: "best_effort"` and an empty
    warnings list while its own sections valued the same 14 tickers from
    different instants - a reviewer later counted 31 mismatching (ticker, price)
    pairs, up to 3.5% apart, and the `pairs` trade signals rested on the
    stalest set. One adjective cannot carry that: it says nothing about how many
    instants, how far apart, or which section disagrees.

    This block answers the first two from measurements this route can actually
    make - one per clock, counted and bounded - and is explicit that the third
    requires comparing `positions[].price_as_of` across sections, which no
    single route can do. Nothing here claims a cross-section measurement it did
    not take.
    """
    marks = _mark_clock_block(positions)
    held = [
        getattr(position, "ticker", None) for position in positions
    ]
    bars = _bar_clock_block(price_as_of, held)
    mark_count = int(marks["distinct_instants"])
    bar_count = int(bars["distinct_instants"])
    if mark_count == 0 and bar_count == 0:
        status = "unmeasured"
    elif mark_count > 1 or bar_count > 1:
        status = "multiple_instants"
    elif bars["positions_without_a_delivered_bar"]:
        status = "partial"
    else:
        status = "single_instant"

    invalidates: List[str] = []
    if mark_count > 1:
        invalidates.append(
            f"The {len(price_as_of)} position marks were written at {mark_count} "
            f"distinct instants spanning {marks['spread']}s, so the book is not a "
            "single simultaneous snapshot: a weight or sector share here is a ratio "
            "of prices fetched at different moments, and no cross-section figure "
            "that sums these marks is co-temporal with any single quote."
        )
    if bar_count > 1:
        invalidates.append(
            f"The delivered daily bars behind the held universe span {bar_count} "
            f"distinct dates ({bars['oldest']} to {bars['newest']}, "
            f"{bars['spread']} calendar days). The envelope `as_of` names only the "
            "newest of them, so it is the correct date for the newest leg and a "
            f"WRONG date for the {sum(len(v) for k, v in bars['positions_at_each_instant'].items() if k != bars['newest'])} "
            "stale leg(s); use positions[].price_as_of, not as_of, per position."
        )
    if bars["positions_without_a_delivered_bar"]:
        invalidates.append(
            f"{len(bars['positions_without_a_delivered_bar'])} held position(s) "
            "have no delivered daily bar at all, so they are absent from the bar "
            "clock and from any date comparison that trusts as_of; the count is "
            "published rather than omitted because a missing date is a fact."
        )
    invalidates.append(
        "This block does NOT reconcile another section. Sections that price the "
        "same tickers from their own delivered bars or their own quote fetches "
        "publish their own price dates, and the pairs / volatility_sizing trade "
        "signals in particular are struck from a different set of prices than "
        "these marks. Comparing one ticker's number in this section with the same "
        "ticker in one of those sections compares two instants unless "
        "positions[].price_as_of agrees; that comparison is the reader's to make "
        "and this route cannot make it for them."
    )

    return {
        "status": status,
        # Headline count for the clock that produced the published prices.
        "distinct_price_instants": mark_count,
        # And the count for the clock every date-based figure is aligned to.
        "distinct_delivered_bar_dates": bar_count,
        "delivered_bar_spread_calendar_days": bars["spread"],
        "mark_instant_spread_seconds": marks["spread"],
        "price_clocks": {
            PORTFOLIO_MARK_CLOCK: marks,
            PORTFOLIO_BAR_CLOCK: bars,
        },
        "per_position_price_as_of": dict(
            sorted(bars["per_ticker"].items())
        ),
        "cross_section_reconciliation": {
            "measured_here": False,
            "reason": (
                "This route values the held universe and returns; it cannot observe "
                "the price instant any other section used, so it publishes its own "
                "clocks and refuses to assert an alignment it did not measure."
            ),
            "rule_for_a_reader": (
                "Treat two numbers for the same ticker as one fact only when their "
                "published price dates match; otherwise the gap is a snapshot gap, "
                "not an arithmetic disagreement."
            ),
        },
        "what_this_invalidates": invalidates,
    }


def _portfolio_accounting_basis() -> Dict[str, Any]:
    """AD-8: state, once, what the portfolio's numbers do and do not account for.

    The artifact carried per-position P&L, a book total, a weight vector and a
    day-change figure and never said whether any of it was gross or net. It also
    never named dividends, fees, tax, slippage, survivorship, corporate actions
    or splits - each appeared zero times across 784 KB - so a reader could not
    tell a price-only series from a total-return one, or assume the unmentioned
    costs were deducted.

    Nothing is deducted here. Deducting them would move every published figure
    and is a different mission; this block's whole job is to make the ABSENCE
    explicit and countable. Every `accounted_for: false` is a real, checked
    property of this route's arithmetic, not a placeholder: the marks come from
    `fetch_quote` current_price with no adjustment, and the buy price is the
    single stored `PortfolioPosition.buy_price`.
    """
    return {
        "basis": PORTFOLIO_ACCOUNTING_BASIS,
        "gross_or_net": "gross",
        "net_of_costs": False,
        "value_mark": {
            "field": "positions[].last_price",
            "source": (
                "DataService.fetch_quote -> current_price, written to "
                "PortfolioPosition.last_price. A live vendor last-trade price."
            ),
            "adjusted": False,
            "note": (
                "StockTimeseries.adj_close is stored alongside the delivered bars "
                "and is NOT used to value a position here. No split, bonus or "
                "dividend adjustment is applied to any mark in this section, so "
                "the marks are unadjusted prices, not a total-return series."
            ),
        },
        "arithmetic": {
            "market_value": "quantity * last_price, native currency",
            "total_cost": (
                "quantity * PortfolioPosition.buy_price, native currency. One "
                "stored buy price per position: not FIFO, not lot-weighted, and not "
                "a broker statement."
            ),
            "unrealized_gain_loss": (
                "quantity * (last_price - buy_price) in the native currency, then "
                "converted at the SAME fx rate used for market_value_base. A paper "
                "mark on an unclosed position, not a settled P&L."
            ),
            "realised_pnl": (
                "NOT produced by this route. A closed or deleted position leaves "
                "no realised ledger here, so no realised return can be computed "
                "from this section."
            ),
            "weights": (
                "converted_value / total_mv_target, restated from the live marks "
                "on every request. A weight therefore implies a trade that has not "
                "happened, at a cost that is not deducted anywhere."
            ),
        },
        "accounted_for": [
            (
                "fx_conversion: every position is converted at one rate published "
                "in currency_provenance.pairs, and a same-currency pair is an "
                "identity at rate 1.0 with provenance 'identity'."
            ),
            (
                "quantity: shares are taken as stored, and a non-positive quantity "
                "is valued at 0.0 rather than at a negative value."
            ),
        ],
        "not_accounted_for": [
            {
                "item": "dividends",
                "accounted_for": False,
                "effect": (
                    "Marks are unadjusted last prices, so dividend income is "
                    "neither added to a position's value nor compounded into "
                    "anything this section publishes. The stored adj_close column "
                    "is not used here."
                ),
            },
            {
                "item": "corporate actions (splits, bonus issues, rights issues, demergers, ticker or ISIN changes)",
                "accounted_for": False,
                "effect": (
                    "No split or bonus adjustment is applied to last_price and none "
                    "to the stored quantity, so an unadjusted corporate action "
                    "surfaces as a price move and as a phantom gain or loss."
                ),
            },
            {
                "item": "fees, brokerage, STT, GST, stamp duty and every other transaction charge",
                "accounted_for": False,
                "effect": (
                    "buy_price is taken as stored with no charge loading, and no "
                    "charge is deducted from any mark, so unrealized_gain_loss is a "
                    "pre-cost figure and the true break-even is above last_price by "
                    "an amount this section cannot quantify."
                ),
            },
            {
                "item": "tax (capital gains, dividend withholding, TDS)",
                "accounted_for": False,
                "effect": (
                    "No tax liability is computed, accrued or reserved, realised or "
                    "unrealised, anywhere in this section."
                ),
            },
            {
                "item": "slippage and market impact",
                "accounted_for": False,
                "effect": (
                    "Marks are the quoted last price. The cost of actually trading "
                    "at that price, at this book's size, is not modelled and not "
                    "deducted."
                ),
            },
            {
                "item": "turnover and rebalancing cost",
                "accounted_for": False,
                "effect": (
                    "Weights move with the marks on every request while the "
                    "holdings do not, so a published target silently assumes a "
                    "rebalance whose cost is absent from every projection built on "
                    "it."
                ),
            },
            {
                "item": "survivorship and selection bias in the universe",
                "accounted_for": False,
                "effect": (
                    "The universe is exactly the tickers currently held. Names that "
                    "were delisted, merged or failed are absent by construction, so "
                    "any long-horizon statistic a reader builds from these names is "
                    "optimistically biased, and the bias grows with the horizon."
                ),
            },
        ],
        "scope": {
            "covers": (
                "sections.portfolio only: positions[*] (market_value, total_cost, "
                "unrealized_gain_loss and their base-currency twins), total_value "
                "and sectors."
            ),
            "does_not_cover": (
                "Every other section's return series, the monte_carlo projection, "
                "the tear sheet, tear-down risk rows and the optimiser target are "
                "computed elsewhere from their own delivered bars and declare no "
                "basis of their own. This block must not be read as stating theirs: "
                "read a number from one of those sections and its gross-or-net "
                "status is UNKNOWN, not gross."
            ),
        },
        "reader_consequence": (
            "These are GROSS figures. A reader sizing a position, projecting "
            "terminal wealth or comparing a return against a benchmark must add "
            "the unmodelled costs above themselves; the published numbers are an "
            "upper bound on net outcome, not an estimate of it."
        ),
    }


def _raise_provider_http_error(exc: ProviderError) -> None:
    """Expose only the stable provider taxonomy to portfolio clients."""
    status_code = int(getattr(exc, "status_code", 502) or 502)
    if not 400 <= status_code <= 599:
        status_code = 502
    if str(getattr(exc, "provider", "")).strip().lower() == "currency":
        raise HTTPException(status_code=503, detail="Live FX unavailable") from exc
    kind = str(getattr(exc, "kind", "provider_error"))
    detail = {
        "rate_limit": "Upstream data service rate limit",
        "auth": "Upstream data service unavailable",
        "unknown_ticker": "Requested ticker was not found",
        "invalid_input": "Invalid market-data request",
    }.get(kind, "Upstream data service unavailable")
    raise HTTPException(status_code=status_code, detail=detail) from exc


def _position_currency(position: Any, quote_data: Optional[Dict[str, Any]] = None) -> str:
    """Resolve a position's native currency from the available metadata seam.

    The current ORM has no currency column (D owns that migration).  Prefer a
    future/attached ``currency`` attribute and quote metadata, then use the
    exchange convention already used by DataService: NSE/BSE = INR and other
    cash equities = USD.  Unknown explicit values fail closed rather than being
    silently treated as a supported currency.
    """
    ticker = str(getattr(position, "ticker", "")).strip().upper()
    expected_currency = None
    if ticker:
        canonical = canonical_ticker(ticker)
        expected_currency = "INR" if canonical.endswith((".NS", ".BO")) else "USD"

    def resolve_metadata(value: Any) -> Optional[str]:
        if not isinstance(value, str) or not value.strip():
            return None
        currency = value.strip().upper()
        if currency not in _SUPPORTED_CURRENCIES:
            raise HTTPException(status_code=400, detail="Position currency is not supported")
        if expected_currency and currency != expected_currency:
            raise HTTPException(
                status_code=400,
                detail=f"Currency {value!r} conflicts with ticker {ticker!r}",
            )
        return currency

    for attr in ("currency", "position_currency", "quote_currency", "_quote_currency"):
        try:
            value = getattr(position, attr, None)
        except Exception:
            value = None
        resolved = resolve_metadata(value)
        if resolved:
            return resolved
    if isinstance(quote_data, dict):
        resolved = resolve_metadata(quote_data.get("currency"))
        if resolved:
            return resolved

    if expected_currency:
        return expected_currency
    region = str(getattr(position, "region", "")).upper()
    if region in {"IN", "IND", "INDIA", "INR"}:
        return "INR"
    return "USD"


def _expected_position_region(ticker: str) -> str:
    """Return the listing region implied by the canonical ticker identity."""
    canonical = canonical_ticker(ticker)
    return "IN" if canonical.endswith((".NS", ".BO")) else "US"


def _resolve_position_region(ticker: str, requested: Optional[str]) -> str:
    """Infer region when omitted and reject contradictory display metadata."""
    expected = _expected_position_region(ticker)
    if requested is None or not str(requested).strip():
        return expected
    normalized = str(requested).strip().upper()
    aliases = {"IN": "IN", "IND": "IN", "INDIA": "IN", "US": "US", "USA": "US"}
    resolved = aliases.get(normalized)
    if resolved is None or resolved != expected:
        raise HTTPException(
            status_code=400,
            detail=f"Region {requested!r} conflicts with ticker {ticker!r}; expected {expected}",
        )
    return resolved


def _native_position_value(position: Any) -> float:
    """Return live native value; explicit zero quantity means exited."""
    try:
        quantity_raw = getattr(position, "quantity", None)
        quantity = float(quantity_raw) if quantity_raw is not None else None
    except (TypeError, ValueError):
        quantity = None
    if quantity is not None and quantity <= 0:
        return 0.0
    try:
        price = float(getattr(position, "last_price", 0.0) or 0.0)
    except (TypeError, ValueError):
        price = 0.0
    value = (quantity or 0.0) * price
    if math.isfinite(value) and value > 0:
        return value
    try:
        stored = float(getattr(position, "market_value", 0.0) or 0.0)
    except (TypeError, ValueError):
        stored = 0.0
    return stored if math.isfinite(stored) and stored > 0 else 0.0


async def _convert_money(
    amount: float,
    source_currency: str,
    target_currency: str,
    currency_service: Any,
) -> tuple[float, Optional[float], Dict[str, Any]]:
    """Convert one amount using a verified live rate and return its provenance."""
    value = float(amount or 0.0)
    if not math.isfinite(value):
        raise HTTPException(status_code=422, detail="Monetary values must be finite")
    source = _normalise_currency(source_currency)
    target = _normalise_currency(target_currency)
    if source == target:
        return value, 1.0, {
            "provenance": "identity",
            "source": "identity",
            "is_fallback": False,
        }

    try:
        convert_with_provenance = getattr(
            currency_service, "convert_amount_with_provenance", None
        )
        if callable(convert_with_provenance):
            result = convert_with_provenance(value, source, target)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, dict):
                raise CurrencyUnavailableError()
            rate, provenance = coerce_live_fx_rate(result.get("rate"))
            converted = value * rate
        else:
            get_rate = getattr(currency_service, "get_exchange_rate", None)
            if not callable(get_rate):
                raise CurrencyUnavailableError()
            candidate = get_rate(source, target)
            if inspect.isawaitable(candidate):
                candidate = await candidate
            rate, provenance = coerce_live_fx_rate(candidate)
            converted = value * rate
    except CurrencyUnavailableError:
        raise
    except Exception as exc:
        # A live FX seam has one public failure taxonomy.  Do not leak vendor
        # exceptions or let an outage fall through as a generic HTTP 500.
        raise CurrencyUnavailableError() from exc

    try:
        converted = float(converted)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CurrencyUnavailableError() from exc
    if not math.isfinite(converted):
        raise CurrencyUnavailableError()
    return converted, rate, provenance


def _clear_portfolio_dependent_memos() -> None:
    """Invalidate weight-dependent analytics after a durable portfolio change."""
    try:
        from app.api.analytics import clear_tails_cache
        clear_tails_cache()
    except Exception:
        # Cache invalidation is best effort; never turn a successful DB commit
        # into a misleading client-side rollback.
        logger.warning("Portfolio-dependent analytics cache invalidation failed")


def _safe_csv_cell(value: Any) -> Any:
    """Prevent spreadsheet formula execution while retaining CSV structure."""
    if isinstance(value, str) and value and value.lstrip() and value.lstrip()[0] in "=+-@":
        return "'" + value
    return value


# asyncio locks are loop-affine when contended.  Keep one small lock per active
# loop so concurrent same-process API calls serialize the check/commit window;
# the database constraint remains the cross-process authority (D-owned).
_portfolio_locks: Dict[Any, asyncio.Lock] = {}


def _portfolio_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _portfolio_locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _portfolio_locks[loop] = lock
    return lock


# Dependency injection


@router.get("", response_model=PortfolioSummaryEnvelope)
async def get_portfolio(
    region: Optional[str] = Query(default=None, description="Filter by region"),
    sector: Optional[str] = Query(default=None, description="Filter by sector"),
    currency: str = Query(default="INR", description="Target currency (INR or USD)"),
    force_refresh: bool = Query(default=False, description="Force refresh prices from upstream"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service)
) -> PortfolioSummaryEnvelope:
    """Return a summary whose total is denominated in one explicit currency."""
    try:
        target_currency = _normalise_currency(currency)
        query = select(PortfolioPosition)
        if isinstance(region, str) and region:
            query = query.where(PortfolioPosition.region == region)
        if isinstance(sector, str) and sector:
            query = query.where(PortfolioPosition.sector == sector)

        result = await db.execute(query)
        positions = list(result.scalars().all())
        if not positions:
            return PortfolioSummaryEnvelope(
                positions=[], total_value=0.0, total_positions=0, total_weight=0.0,
                sectors={}, currency=target_currency, base_currency=target_currency,
                currency_provenance={
                    "aggregation": "per_position_conversion",
                    "base_currency": target_currency,
                    "source_currencies": [],
                    "supported_currencies": sorted(_SUPPORTED_CURRENCIES),
                    "pairs": {},
                },
                position_currencies={},
                holding_date_provenance=_holding_date_provenance(),
                as_of=None,
                as_of_semantics=None,
                valuation_refreshed_at=None,
                # An empty book has no marks and no instants, so the block says
                # `unmeasured` rather than implying a single consistent snapshot.
                snapshot_consistency=_price_snapshot_consistency([], {}),
                accounting_basis=_portfolio_accounting_basis(),
            )

        await _update_portfolio_prices(positions, data_service, force=bool(force_refresh))
        await db.commit()
        _clear_portfolio_dependent_memos()

        currency_service = get_currency_service()
        fx_info = {}
        get_fx_info = getattr(currency_service, "get_exchange_rate_info", None)
        if callable(get_fx_info):
            candidate_info = get_fx_info()
            if inspect.isawaitable(candidate_info):
                candidate_info = await candidate_info
            if isinstance(candidate_info, dict):
                fx_info = candidate_info
        position_responses: List[PortfolioPositionResponse] = []
        total_value = 0.0
        total_mv_target = 0.0
        sectors: Dict[str, float] = {}
        position_currencies: Dict[str, str] = {}
        pairs: Dict[str, Dict[str, Any]] = {}
        source_currencies = set()

        # One grouped query serves BOTH the book-wide `as_of` and the
        # per-position `price_as_of`, so the two can never disagree. Two
        # independent lookups are exactly how a per-ticker spread goes invisible.
        # Queried before the render loop because every row carries its own date.
        price_as_of_by_ticker = await _delivered_close_dates(
            db, [getattr(p, "ticker", None) for p in positions]
        )

        # First pass is required: weights and sector shares must use the same
        # converted values as the aggregate total.
        converted_values: List[Tuple[float, Optional[float], Dict[str, Any]]] = []
        for position in positions:
            source_currency = _position_currency(position)
            position_currencies[position.ticker] = source_currency
            source_currencies.add(source_currency)
            native_value = _native_position_value(position)
            if native_value > 0:
                converted_value, rate, conversion_provenance = await _convert_money(
                    native_value, source_currency, target_currency, currency_service
                )
                if source_currency != target_currency and rate is None:
                    raise CurrencyUnavailableError()
                converted_values.append((converted_value, rate, conversion_provenance))
                total_mv_target += converted_value
            else:
                converted_value, rate, conversion_provenance = 0.0, None, {
                    "provenance": "not_applicable",
                    "source": "identity",
                    "is_fallback": False,
                }
                converted_values.append((converted_value, rate, conversion_provenance))
            if source_currency == target_currency:
                pairs.setdefault(f"{source_currency}->{target_currency}", {
                    "rate": 1.0,
                    "provenance": "identity",
                    "source": "identity",
                    "is_fallback": False,
                })
            elif converted_value > 0:
                pair_key = f"{source_currency}->{target_currency}"
                pair_data = pairs.setdefault(pair_key, {
                    "rate": rate,
                    "source": conversion_provenance.get("source", "currency_service"),
                })
                if rate is not None:
                    pair_data["rate"] = rate
                for key in ("provenance", "is_fallback", "fetched_at", "age_seconds"):
                    if key in conversion_provenance:
                        pair_data[key] = conversion_provenance[key]
                if "last_updated" not in pair_data:
                    pair_data["last_updated"] = fx_info.get("last_updated")
                if "fallback" not in pair_data:
                    pair_data["fallback"] = bool(
                        conversion_provenance.get("is_fallback")
                        or (bool(fx_info) and fx_info.get("last_updated") is None)
                    )

        for position, (converted_value, rate, conversion_provenance) in zip(
            positions, converted_values
        ):
            source_currency = position_currencies[position.ticker]
            native_cost = float((position.quantity or 0.0) * (position.buy_price or 0.0))
            native_current = float((position.quantity or 0.0) * (position.last_price or 0.0))
            native_gain_loss = native_current - native_cost
            native_gain_loss_pct = (
                (native_gain_loss / native_cost * 100) if native_cost > 0 else 0.0
            )
            # Reuse the exact FX rate/provenance used for current value so
            # cost, current value, and P&L share one conversion snapshot.
            base_cost = native_cost * rate if rate is not None else native_cost
            base_gain_loss = converted_value - base_cost
            base_gain_loss_pct = (
                (base_gain_loss / base_cost * 100) if base_cost > 0 else 0.0
            )
            live_weight = (
                converted_value / total_mv_target
                if total_mv_target > 0 else float(position.weight or 0.0)
            )
            # AD-16: the mark's own price date, resolved to this ticker. Null is a
            # measurement (no delivered bar for this name), never a neighbour's.
            leg_price_as_of = price_as_of_by_ticker.get(position.ticker) or None
            position_responses.append(PortfolioPositionEnvelope(
                id=position.id,
                ticker=position.ticker,
                weight=live_weight,
                quantity=position.quantity,
                buy_price=position.buy_price,
                last_price=position.last_price,
                market_value=native_current,
                sector=position.sector,
                industry=position.industry,
                region=_expected_position_region(position.ticker),
                custom_name=position.custom_name,
                added_on=position.added_on,
                updated_on=position.updated_on,
                # Legacy fields remain in the position's native currency.
                total_cost=native_cost,
                unrealized_gain_loss=native_gain_loss,
                unrealized_gain_loss_pct=native_gain_loss_pct,
                current_value=native_current,
                # Explicit base-currency fields are safe for clients to sum.
                native_currency=source_currency,
                value_currency=target_currency,
                fx_rate=rate,
                fx_provenance=conversion_provenance,
                market_value_base=converted_value,
                buy_price_base=(float(position.buy_price or 0.0) * rate) if rate is not None else position.buy_price,
                last_price_base=(float(position.last_price or 0.0) * rate) if rate is not None else position.last_price,
                current_value_base=converted_value,
                total_cost_base=base_cost,
                unrealized_gain_loss_base=base_gain_loss,
                unrealized_gain_loss_pct_base=base_gain_loss_pct,
                # AD-16: sit `price_as_of` next to the `last_price` it dates, so
                # alignment with another section is checkable per row rather than
                # asserted once for the whole export.
                price_as_of=leg_price_as_of,
                price_as_of_semantics=(
                    PORTFOLIO_PRICE_AS_OF_SEMANTICS if leg_price_as_of else None
                ),
            ))
            total_value += converted_value
            sector_key = position.sector or "Unknown"
            sectors[sector_key] = sectors.get(sector_key, 0.0) + converted_value

        normalized_sectors = (
            {key: value / total_mv_target for key, value in sectors.items()}
            if total_mv_target > 0 else {}
        )
        provenance = {
            "aggregation": "per_position_conversion",
            "base_currency": target_currency,
            "source_currencies": sorted(source_currencies),
            "supported_currencies": sorted(_SUPPORTED_CURRENCIES),
            "pairs": pairs,
            "rates": {pair: data.get("rate") for pair, data in pairs.items()},
            "rate_provider": "currency_service",
        }
        # ONE grouped query now serves both the book-wide `as_of` and the
        # per-position `price_as_of`, so the two can never disagree: a second
        # independent lookup is exactly how a spread becomes invisible.
        price_as_of_by_ticker = await _delivered_close_dates(db, list(position_currencies))
        # One grouped query now serves both the book-wide `as_of` and the
        # per-position `price_as_of`, so the two can never disagree: a second
        # independent lookup is exactly how a spread becomes invisible.
        observation_date = max(price_as_of_by_ticker.values(), default=None)
        refreshed_at = _quote_refresh_instant(positions)
        snapshot_consistency = _price_snapshot_consistency(
            positions, price_as_of_by_ticker
        )
        return PortfolioSummaryEnvelope(
            positions=position_responses,
            total_value=total_value,
            total_positions=len(positions),
            total_weight=sum(float(p.weight or 0.0) for p in position_responses),
            sectors=normalized_sectors,
            currency=target_currency,
            base_currency=target_currency,
            currency_provenance=provenance,
            position_currencies=position_currencies,
            holding_date_provenance=_holding_date_provenance(),
            # DI-1: `as_of` is a real observation date, so it can never postdate
            # the envelope that carries it, and it never names a day the exchange
            # was shut. The quote WRITE clock moves to its own field, because it
            # is a refresh instant and saying so in a warning while leaving it in
            # `as_of` is what made the value misleading in the first place.
            as_of=observation_date,
            # The label describes `as_of`, so it exists only when `as_of` does.
            as_of_semantics=(
                PORTFOLIO_AS_OF_SEMANTICS if observation_date else None
            ),
            valuation_refreshed_at=refreshed_at,
            # AD-16: the measured count of price instants and the spread between
            # them, replacing the one-word `best_effort` the export used to
            # publish about the same fact.
            snapshot_consistency=snapshot_consistency,
            # AD-8: one declaration of what these money figures are gross OF.
            accounting_basis=_portfolio_accounting_basis(),
            # The disclosure the split would otherwise drop: the values are live
            # quotes, and the refresh instant is beside the date, not in it. The
            # second sentence is the spread the single `as_of` cannot express.
            warnings=(
                _portfolio_freshness_warnings(observation_date, refreshed_at)
                + _price_instant_warnings(snapshot_consistency)
            ),
        )
    except ProviderError as exc:
        _raise_provider_http_error(exc)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid portfolio value") from exc
    except Exception as exc:
        logger.error("Error in get_portfolio")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/add", response_model=PortfolioPositionResponse)
async def add_portfolio_position(
    position: PortfolioPositionCreate,
    currency: str = Query(default="INR", description="Target currency (INR or USD)"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service)
) -> PortfolioPositionResponse:
    """Validate, commit, and then render a position without false rollback semantics."""
    _normalise_currency(currency)  # retain and validate the public query contract
    canonical = canonical_ticker(position.ticker)
    position_region = _resolve_position_region(canonical, position.region)
    committed = False

    try:
        if not await data_service.validate_ticker(position.ticker, strict_errors=True):
            suggestions = _generate_ticker_suggestions(position.ticker)
            suggestion_text = f". Did you mean: {', '.join(suggestions)}?" if suggestions else ""
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "INVALID_TICKER",
                    "message": f"'{position.ticker}' is not a valid stock ticker symbol",
                    "suggestions": suggestions,
                    "help": f"Please enter a valid ticker symbol like AAPL, GOOGL, MSFT, TSLA, BRK.B{suggestion_text}",
                    "ticker": position.ticker,
                },
            )

        # Friendly duplicate rejection precedes vendor I/O.  The locked check
        # below is still repeated at commit time to close the race window.
        existing_result = await db.execute(select(PortfolioPosition))
        existing_positions = list(existing_result.scalars().all())
        if canonical in {
            canonical_ticker(item.ticker) for item in existing_positions
            if getattr(item, "ticker", None)
        }:
            raise HTTPException(status_code=409, detail=f"Ticker {canonical} already exists in portfolio")

        quote_data = await data_service.fetch_quote(position.ticker)
        if not isinstance(quote_data, dict) or quote_data.get("current_price") is None:
            raise HTTPException(status_code=400, detail="Could not fetch price data for ticker")
        try:
            current_price = float(quote_data["current_price"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Quote price must be finite") from exc
        if not math.isfinite(current_price) or current_price <= 0:
            raise HTTPException(status_code=422, detail="Quote price must be positive and finite")

        async with _portfolio_lock():
            existing_result = await db.execute(select(PortfolioPosition))
            existing_positions = list(existing_result.scalars().all())
            existing_set = {
                canonical_ticker(item.ticker) for item in existing_positions
                if getattr(item, "ticker", None)
            }
            if canonical in existing_set:
                raise HTTPException(status_code=409, detail=f"Ticker {canonical} already exists in portfolio")

            existing_value = 0.0
            for item in existing_positions:
                value = float(getattr(item, "market_value", 0.0) or 0.0)
                if value <= 0:
                    value = float(getattr(item, "quantity", 0.0) or 0.0) * float(getattr(item, "last_price", 0.0) or 0.0)
                if math.isfinite(value) and value > 0:
                    existing_value += value

            # The zero-state rule is applied to the object that is committed,
            # not merely to the returned representation.
            effective_weight = 1.0 if not existing_positions or existing_value <= 0 else position.weight
            current_value = position.quantity * current_price
            new_position = PortfolioPosition(
                ticker=canonical,
                weight=effective_weight,
                quantity=position.quantity,
                buy_price=position.buy_price,
                region=position_region,
                added_on=(
                    datetime.combine(position.added_on, datetime.min.time())
                    if position.added_on else None
                ),
                primary_source=quote_data.get("source", "yfinance"),
                last_validated_source=quote_data.get("source", "yfinance"),
                last_price=current_price,
                market_value=current_value,
                sector=quote_data.get("sector") or "Unknown",
                industry=quote_data.get("industry") or "Unknown",
                custom_name=position.custom_name,
            )
            db.add(new_position)
            try:
                # Flush exposes a DB uniqueness/integrity race at the narrowest
                # pre-commit boundary; the commit below remains the durability
                # boundary.
                await db.flush()
                await db.commit()
                committed = True
                _clear_portfolio_dependent_memos()
            except IntegrityError as exc:
                await db.rollback()
                raise HTTPException(status_code=409, detail="Position conflicts with an existing holding") from exc
            except Exception as exc:
                await db.rollback()
                raise HTTPException(status_code=500, detail="Position could not be saved") from exc

        # Post-commit refresh/response errors are distinct: the row is durable,
        # so never roll it back or claim that the write was undone.
        try:
            await db.refresh(new_position)
            total_cost = float(new_position.quantity * new_position.buy_price)
            current_value = float(new_position.quantity * new_position.last_price)
            unrealized_gain_loss = current_value - total_cost
            unrealized_gain_loss_pct = (
                (unrealized_gain_loss / total_cost * 100) if total_cost > 0 else 0.0
            )
            response = PortfolioPositionResponse(
                id=new_position.id,
                ticker=new_position.ticker,
                weight=new_position.weight,
                quantity=new_position.quantity,
                buy_price=new_position.buy_price,
                last_price=new_position.last_price,
                market_value=new_position.market_value,
                sector=new_position.sector,
                industry=new_position.industry,
                region=position_region,
                custom_name=new_position.custom_name,
                added_on=new_position.added_on,
                updated_on=new_position.updated_on,
                total_cost=total_cost,
                unrealized_gain_loss=unrealized_gain_loss,
                unrealized_gain_loss_pct=unrealized_gain_loss_pct,
                current_value=current_value,
            )
            return response
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Position committed but response refresh failed")
            raise HTTPException(
                status_code=500,
                detail="Position committed, but the response could not be refreshed",
            ) from exc
    except ProviderError as exc:
        if not committed:
            await db.rollback()
        _raise_provider_http_error(exc)
    except HTTPException:
        raise
    except IntegrityError as exc:
        if not committed:
            await db.rollback()
        raise HTTPException(status_code=409, detail="Position conflicts with an existing holding") from exc
    except Exception as exc:
        if not committed:
            await db.rollback()
        logger.error("Error adding portfolio position")
        raise HTTPException(status_code=500, detail="Internal server error") from exc



@router.post("/bulk_add", response_model=BulkAddEnvelope)
async def bulk_add_positions(
    request: BulkAddRequest,
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service)
) -> BulkAddEnvelope:
    """Bulk add with explicit skipped-row accounting and one commit boundary."""
    submitted_count = len(request.positions)
    added_count = 0
    failed_count = 0
    duplicate_tickers: List[str] = []
    failures: List[Dict[str, str]] = []
    added_positions: List[PortfolioPosition] = []
    committed = False

    try:
        validated_positions = []
        validation_errors = []
        for index, pos_data in enumerate(request.positions, start=1):
            if not pos_data.ticker or not _TICKER_PATTERN.match(pos_data.ticker.upper()):
                validation_errors.append(f"Position {index}: invalid ticker format")
            else:
                validated_positions.append(pos_data)
        resolved_regions: Dict[str, str] = {}
        for pos_data in validated_positions:
            canonical = canonical_ticker(pos_data.ticker)
            try:
                resolved_regions[canonical] = _resolve_position_region(
                    canonical, pos_data.region
                )
            except HTTPException as exc:
                validation_errors.append(
                    f"Position {pos_data.ticker}: {exc.detail}"
                )
        if validation_errors:
            raise HTTPException(
                status_code=400,
                detail=f"Business rule validation failed: {'; '.join(validation_errors)}",
            )

        invalid_tickers = [
            pos_data.ticker for pos_data in validated_positions
            if not await data_service.validate_ticker(pos_data.ticker, strict_errors=True)
        ]
        if invalid_tickers:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tickers (do not exist): {', '.join(invalid_tickers)}",
            )

        # First duplicate pass gives a stable disclosure and avoids quote work
        # for rows already known to be skipped.
        async with _portfolio_lock():
            existing_result = await db.execute(select(PortfolioPosition.ticker))
            existing_set = {
                canonical_ticker(ticker) for ticker in existing_result.scalars().all()
            }
        seen_in_payload = set()
        unique_positions = []
        for pos_data in validated_positions:
            canonical = canonical_ticker(pos_data.ticker)
            if canonical in existing_set or canonical in seen_in_payload:
                duplicate_tickers.append(canonical)
                failures.append({"ticker": canonical, "reason": "DUPLICATE"})
                continue
            seen_in_payload.add(canonical)
            unique_positions.append(pos_data)

        sem = asyncio.Semaphore(5)

        async def fetch_quote(pos_data):
            async with sem:
                try:
                    quote = await data_service.fetch_quote(canonical_ticker(pos_data.ticker))
                    return pos_data, quote, None
                except Exception:
                    logger.error("Bulk quote fetch failed")
                    return pos_data, None, True

        quote_results = await asyncio.gather(*(fetch_quote(pos) for pos in unique_positions))
        for pos_data, quote_data, failed in quote_results:
            ticker = canonical_ticker(pos_data.ticker)
            if failed or not isinstance(quote_data, dict) or quote_data.get("current_price") is None:
                failures.append({"ticker": ticker, "reason": "QUOTE_UNAVAILABLE"})
                failed_count += 1
                continue
            try:
                price = float(quote_data["current_price"])
            except (TypeError, ValueError):
                price = math.nan
            if not math.isfinite(price) or price <= 0:
                failures.append({"ticker": ticker, "reason": "INVALID_PRICE"})
                failed_count += 1
                continue
            position = PortfolioPosition(
                ticker=ticker,
                weight=pos_data.weight,
                quantity=pos_data.quantity,
                buy_price=pos_data.buy_price,
                region=resolved_regions.get(ticker, _expected_position_region(ticker)),
                added_on=(
                    datetime.combine(pos_data.added_on, datetime.min.time())
                    if pos_data.added_on else None
                ),
                primary_source=quote_data.get("source", "yfinance"),
                last_validated_source=quote_data.get("source", "yfinance"),
                last_price=price,
                market_value=pos_data.quantity * price,
                sector=quote_data.get("sector") or "Unknown",
                industry=quote_data.get("industry") or "Unknown",
                custom_name=pos_data.custom_name,
            )
            if not _validate_portfolio_position(position):
                failures.append({"ticker": ticker, "reason": "POSITION_VALIDATION_FAILED"})
                failed_count += 1
                continue
            added_positions.append(position)

        # A single-position write to an empty/zero-value book gets the same
        # effective 100% weight as POST /add, regardless of auto_normalize.
        if len(added_positions) == 1:
            existing_rows = (await db.execute(select(PortfolioPosition))).scalars().all()
            existing_value = sum(
                max(
                    float(getattr(row, "market_value", 0.0) or 0.0),
                    float(getattr(row, "quantity", 0.0) or 0.0) * float(getattr(row, "last_price", 0.0) or 0.0),
                )
                for row in existing_rows
            )
            if not existing_rows or existing_value <= 0:
                added_positions[0].weight = 1.0

        normalized = False
        if request.auto_normalize and added_positions:
            existing_rows = (await db.execute(select(PortfolioPosition))).scalars().all()
            total_weight = sum(float(row.weight or 0.0) for row in existing_rows) + sum(
                float(position.weight or 0.0) for position in added_positions
            )
            if total_weight > 0 and abs(total_weight - 1.0) > 1e-9:
                normalized = True
                for position in added_positions:
                    position.weight = float(position.weight or 0.0) / total_weight
                for row in existing_rows:
                    row.weight = float(row.weight or 0.0) / total_weight

        response_errors = []
        for position in added_positions:
            if not position.ticker or not (0 < position.weight <= 1):
                response_errors.append("invalid response data")
            if position.quantity <= 0 or position.buy_price <= 0 or position.last_price <= 0:
                response_errors.append("invalid business data")
        if response_errors:
            raise HTTPException(status_code=422, detail="Bulk position validation failed")

        if added_positions:
            # Recheck under the same process lock immediately before commit;
            # IntegrityError is still mapped for cross-process races.
            async with _portfolio_lock():
                current_result = await db.execute(select(PortfolioPosition.ticker))
                current_set = {canonical_ticker(ticker) for ticker in current_result.scalars().all()}
                raced = [
                    position for position in added_positions
                    if position.ticker in current_set
                ]
                if raced:
                    for position in raced:
                        duplicate_tickers.append(position.ticker)
                        failures.append({"ticker": position.ticker, "reason": "DUPLICATE"})
                    added_positions = [p for p in added_positions if p not in raced]
                if added_positions:
                    try:
                        for position in added_positions:
                            db.add(position)
                        await db.flush()
                        await db.commit()
                        committed = True
                        _clear_portfolio_dependent_memos()
                    except IntegrityError as exc:
                        await db.rollback()
                        raise HTTPException(status_code=409, detail="Bulk add conflicts with an existing holding") from exc
                    except Exception as exc:
                        await db.rollback()
                        raise HTTPException(status_code=500, detail="Bulk add could not be saved") from exc

        # Refresh and response construction happen after the durable commit.
        if committed:
            try:
                for position in added_positions:
                    await db.refresh(position)
            except Exception as exc:
                logger.error("Bulk positions committed but response refresh failed")
                raise HTTPException(
                    status_code=500,
                    detail="Bulk positions committed, but the response could not be refreshed",
                ) from exc

        position_responses = []
        for position in added_positions:
            total_cost = float(position.quantity * position.buy_price)
            current_value = float(position.quantity * position.last_price)
            unrealized_gain_loss = current_value - total_cost
            unrealized_gain_loss_pct = (
                (unrealized_gain_loss / total_cost * 100) if total_cost > 0 else 0.0
            )
            position_responses.append(PortfolioPositionResponse(
                id=position.id,
                ticker=position.ticker,
                weight=position.weight,
                quantity=position.quantity,
                buy_price=position.buy_price,
                last_price=position.last_price,
                market_value=position.market_value,
                sector=position.sector,
                industry=position.industry,
                region=_expected_position_region(ticker),
                custom_name=position.custom_name,
                added_on=position.added_on,
                updated_on=position.updated_on,
                total_cost=total_cost,
                unrealized_gain_loss=unrealized_gain_loss,
                unrealized_gain_loss_pct=unrealized_gain_loss_pct,
                current_value=current_value,
            ))

        added_count = len(position_responses)
        return BulkAddEnvelope(
            added=added_count,
            failed=failed_count,
            normalized=normalized,
            positions=position_responses,
            submitted=submitted_count,
            skipped=len(duplicate_tickers),
            duplicates=duplicate_tickers,
            failures=failures,
        )
    except ProviderError as exc:
        if not committed:
            await db.rollback()
        _raise_provider_http_error(exc)
    except HTTPException:
        raise
    except IntegrityError as exc:
        if not committed:
            await db.rollback()
        raise HTTPException(status_code=409, detail="Bulk add conflicts with an existing holding") from exc
    except Exception as exc:
        if not committed:
            await db.rollback()
        logger.error("Critical error in bulk_add_positions")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


def _validate_portfolio_position(position: PortfolioPosition) -> bool:
    """Validate portfolio position data integrity.

    Module-level helper (the stray ``self`` parameter previously made every
    bulk-add call raise TypeError, silently failing each position).
    """
    try:
        # Business rule validations
        if not position.ticker or not _TICKER_PATTERN.match(position.ticker.upper()):
            return False
        if not (0 < position.weight <= 1):
            return False
        if position.quantity <= 0:
            return False
        if position.buy_price <= 0:
            return False
        if position.last_price <= 0:
            return False
        if position.market_value < 0:
            return False
        
        # Data consistency checks
        expected_market_value = position.quantity * position.last_price
        if abs(position.market_value - expected_market_value) > 0.01:  # Allow small floating point errors
            return False
        
        return True
        
    except Exception:
        logger.error("Portfolio position validation failed")
        return False


@router.get("/{ticker}", response_model=PortfolioPositionResponse)
async def get_portfolio_position(
    ticker: str,
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service)
) -> PortfolioPositionResponse:
    """
    Get a specific portfolio position by ticker
    """
    try:
        result = await db.execute(
            select(PortfolioPosition).where(
                PortfolioPosition.ticker.in_([ticker.upper(), canonical_ticker(ticker)])
            )
        )
        position = result.scalars().first()
        
        if not position:
            raise HTTPException(
                status_code=404,
                detail=f"Position for ticker {ticker} not found"
            )
        
        # Update price; market_value always derives from quantity x last_price.
        quote_data = await data_service.fetch_quote(ticker)
        if quote_data:
            position.last_price = quote_data["current_price"]
            position.market_value = (position.quantity or 0) * position.last_price
            position.updated_on = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.commit()
            _clear_portfolio_dependent_memos()

        # Reload eagerly: on-update server columns (updated_on) are otherwise
        # unfetched on fresh rows and lazy-load with sync IO outside greenlet.
        await db.refresh(position)

        total_cost = position.quantity * position.buy_price
        current_value = position.quantity * position.last_price
        unrealized_gain_loss = current_value - total_cost
        unrealized_gain_loss_pct = (unrealized_gain_loss / total_cost * 100) if total_cost > 0 else 0.0

        return PortfolioPositionResponse(
            id=position.id,
            ticker=position.ticker,
            weight=position.weight,
            quantity=position.quantity,
            buy_price=position.buy_price,
            last_price=position.last_price,
            market_value=position.market_value,
            sector=position.sector,
            industry=position.industry,
            region=_expected_position_region(position.ticker),
            custom_name=position.custom_name,
            added_on=position.added_on,
            updated_on=position.updated_on,
            total_cost=total_cost,
            unrealized_gain_loss=unrealized_gain_loss,
            unrealized_gain_loss_pct=unrealized_gain_loss_pct,
            current_value=current_value
        )
        
    except ProviderError as exc:
        _raise_provider_http_error(exc)
    except HTTPException:
        raise
    except Exception:
        logger.error("Portfolio position read failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/{ticker}", response_model=PortfolioPositionResponse)
async def update_portfolio_position(
    ticker: str,
    updates: PortfolioPositionUpdate,
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service)
) -> PortfolioPositionResponse:
    """
    Update a portfolio position
    """
    committed = False
    try:
        result = await db.execute(
            select(PortfolioPosition).where(
                PortfolioPosition.ticker.in_([ticker.upper(), canonical_ticker(ticker)])
            )
        )
        position = result.scalars().first()
        
        if not position:
            raise HTTPException(
                status_code=404,
                detail=f"Position for ticker {ticker} not found"
            )
        
        # Apply updates
        if updates.custom_name is not None:
            position.custom_name = updates.custom_name

        if updates.added_on is not None:
            position.added_on = datetime.combine(updates.added_on, datetime.min.time())
        
        if updates.weight is not None:
            position.weight = updates.weight
        if updates.quantity is not None:
            position.quantity = updates.quantity
        if updates.buy_price is not None:
            position.buy_price = updates.buy_price
        
        # Recalculate market value and metrics
        position.market_value = position.quantity * position.last_price
        position.updated_on = datetime.now(timezone.utc).replace(tzinfo=None)
        
        await db.commit()
        committed = True
        await db.refresh(position)
        _clear_portfolio_dependent_memos()
        
        # Calculate response metrics
        total_cost = position.quantity * position.buy_price
        current_value = position.quantity * position.last_price
        unrealized_gain_loss = current_value - total_cost
        unrealized_gain_loss_pct = (unrealized_gain_loss / total_cost * 100) if total_cost > 0 else 0.0
        
        return PortfolioPositionResponse(
            id=position.id,
            ticker=position.ticker,
            weight=position.weight,
            quantity=position.quantity,
            buy_price=position.buy_price,
            last_price=position.last_price,
            market_value=position.market_value,
            sector=position.sector,
            industry=position.industry,
            region=_expected_position_region(position.ticker),
            custom_name=position.custom_name,
            added_on=position.added_on,
            updated_on=position.updated_on,
            total_cost=total_cost,
            unrealized_gain_loss=unrealized_gain_loss,
            unrealized_gain_loss_pct=unrealized_gain_loss_pct,
            current_value=current_value
        )
        
    except HTTPException:
        raise
    except Exception as exc:
        if not committed:
            await db.rollback()
        logger.error("Portfolio position update failed")
        detail = "Position committed, but the response could not be refreshed" if committed else "Internal server error"
        raise HTTPException(status_code=500, detail=detail) from exc


@router.delete("/{ticker}")
async def delete_portfolio_position(
    ticker: str,
    db: AsyncSession = Depends(get_db_session)
) -> SuccessResponse:
    """
    Delete a portfolio position and auto-normalize remaining position weights
    """
    committed = False
    try:
        result = await db.execute(
            select(PortfolioPosition).where(
                PortfolioPosition.ticker.in_([ticker.upper(), canonical_ticker(ticker)])
            )
        )
        position = result.scalars().first()
        
        if not position:
            raise HTTPException(
                status_code=404,
                detail=f"Position for ticker {ticker} not found"
            )
        
        await db.delete(position)
        
        # Auto-normalize remaining position weights to sum to 1.0
        remaining_result = await db.execute(select(PortfolioPosition))
        remaining_positions = remaining_result.scalars().all()
        
        if remaining_positions:
            total_current_weight = sum(p.weight for p in remaining_positions if p.weight and p.weight > 0)
            if total_current_weight > 0:
                for p in remaining_positions:
                    p.weight = round(p.weight / total_current_weight, 6)
            else:
                equal_w = round(1.0 / len(remaining_positions), 6)
                for p in remaining_positions:
                    p.weight = equal_w
                    
        await db.commit()
        committed = True
        _clear_portfolio_dependent_memos()
        
        return SuccessResponse(
            success=True,
            message=f"Position {ticker} deleted successfully and remaining weights normalized",
            data={"weights_renormalized": bool(remaining_positions)}
        )
        
    except HTTPException:
        raise
    except Exception as exc:
        if not committed:
            await db.rollback()
        logger.error("Portfolio position deletion failed")
        detail = "Position committed, but the response could not be prepared" if committed else "Internal server error"
        raise HTTPException(status_code=500, detail=detail) from exc


@router.get("/export/csv")
async def export_portfolio_csv(
    db: AsyncSession = Depends(get_db_session)
) -> Response:
    """
    Export portfolio as CSV
    """
    try:
        result = await db.execute(select(PortfolioPosition))
        positions = result.scalars().all()
        
        if not positions:
            raise HTTPException(status_code=404, detail="No positions to export")
        
        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            'ticker', 'weight', 'region', 'last_price', 'market_value',
            'sector', 'industry', 'custom_name', 'added_on', 'updated_on'
        ])
        
        # Write data
        for position in positions:
            writer.writerow([
                _safe_csv_cell(position.ticker),
                position.weight,
                _safe_csv_cell(position.region),
                position.last_price,
                position.market_value,
                _safe_csv_cell(position.sector),
                _safe_csv_cell(position.industry),
                _safe_csv_cell(position.custom_name or ''),
                position.added_on.isoformat() if position.added_on else '',
                # fresh rows have NULL updated_on until first update
                (position.updated_on or position.added_on).isoformat()
                if (position.updated_on or position.added_on) else '',
            ])
        
        # Return CSV content
        csv_content = output.getvalue()
        output.close()
        
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=portfolio.csv"},
        )
        
    except HTTPException:
        raise
    except Exception:
        logger.error("Portfolio CSV export failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/normalize")
async def normalize_portfolio_weights(
    method: str = Query(default="proportional", description="Normalization method (only 'proportional' supported)"),
    db: AsyncSession = Depends(get_db_session)
) -> SuccessResponse:
    """
    Normalize portfolio weights to sum to 1.0
    """
    committed = False
    try:
        if method != "proportional":
            raise HTTPException(status_code=400, detail=f"Unsupported normalization method: {method}")
        result = await db.execute(select(PortfolioPosition))
        positions = result.scalars().all()
        
        if not positions:
            raise HTTPException(status_code=404, detail="No positions to normalize")
        
        total_weight = sum(pos.weight for pos in positions)
        
        if total_weight <= 0:
            raise HTTPException(status_code=400, detail="Total weight must be positive")
        
        # Normalize weights only — market values are quantity x price and are
        # owned by the price-refresh path, not by weight bookkeeping.
        for position in positions:
            position.weight = position.weight / total_weight
            position.updated_on = datetime.now(timezone.utc).replace(tzinfo=None)
        
        await db.commit()
        committed = True
        _clear_portfolio_dependent_memos()
        
        return SuccessResponse(
            success=True,
            message=f"Portfolio weights normalized. Total weight: {sum(pos.weight for pos in positions):.4f}"
        )
        
    except HTTPException:
        raise
    except Exception as exc:
        if not committed:
            await db.rollback()
        logger.error("Portfolio normalization failed")
        detail = "Portfolio committed, but the response could not be prepared" if committed else "Internal server error"
        raise HTTPException(status_code=500, detail=detail) from exc


class RebalancePayload(BaseModel):
    new_weights: Dict[str, float]
    dry_run: Optional[bool] = False


@router.post("/rebalance")
async def rebalance_portfolio(
    payload: RebalancePayload,
    db: AsyncSession = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    Execute portfolio rebalancing or simulate a dry-run without modifying the database.
    """
    committed = False
    try:
        if not payload.new_weights:
            raise HTTPException(status_code=400, detail="New weights dictionary cannot be empty")
        
        result = await db.execute(select(PortfolioPosition))
        positions = result.scalars().all()
        
        if not positions:
            raise HTTPException(status_code=404, detail="No positions found in portfolio")
        
        currency_service = get_currency_service()
        converted_values: Dict[str, float] = {}
        converted_prices: Dict[str, float] = {}
        source_currencies: Dict[str, str] = {}
        fx_pairs: Dict[str, Dict[str, Any]] = {}
        for position in positions:
            source = _position_currency(position)
            source_currencies[position.ticker] = source
            native_price = float(position.last_price or 0.0)
            if native_price <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing price for {position.ticker}; rebalancing requires live position values",
                )
            # Target quantities and total value use the exact same converted
            # price.  A stale stored market_value or a second FX refresh must not
            # change the INR budget and make the proposed orders inconsistent.
            converted_price, rate, conversion_provenance = await _convert_money(
                native_price, source, "INR", currency_service
            )
            if converted_price <= 0:
                raise HTTPException(
                    status_code=503,
                    detail="Currency conversion unavailable for rebalance price",
                )
            pair_key = f"{source}->INR"
            if source == "INR":
                fx_pairs.setdefault(pair_key, {
                    "rate": 1.0,
                    "provenance": "identity",
                    "source": "identity",
                    "is_fallback": False,
                })
            else:
                pair = fx_pairs.setdefault(pair_key, {"rate": rate})
                pair.update(conversion_provenance)
                pair["rate"] = rate
            converted_value = float(position.quantity or 0.0) * converted_price
            converted_values[position.ticker] = converted_value
            converted_prices[position.ticker] = converted_price
        total_pv = sum(value for value in converted_values.values() if value > 0)
        if total_pv <= 0:
            raise HTTPException(
                status_code=400,
                detail="Portfolio market value is unavailable (zero or missing prices); rebalancing requires live position values"
            )
        current_market_weights = {
            ticker: value / total_pv
            for ticker, value in converted_values.items()
            if value > 0
        }
        currency_provenance = {
            "base_currency": "INR",
            "aggregation": (
                "per_position_conversion"
                if any(source != "INR" for source in source_currencies.values())
                else "native_uniform"
            ),
            "source_currencies": sorted(set(source_currencies.values())),
            "pairs": fx_pairs,
            "rate_provider": "currency_service",
        }
        
        known = {p.ticker for p in positions}
        negatives = [k for k, v in payload.new_weights.items() if v < 0]
        if negatives:
            raise HTTPException(
                status_code=400,
                detail=f"Negative weights not allowed: {', '.join(negatives)}"
            )
        # A non-finite leg carries no instruction; dropping it silently would
        # trade the book against a target the caller never asked for.
        non_finite = [
            k for k, v in payload.new_weights.items()
            if not math.isfinite(float(v))
        ]
        if non_finite:
            raise HTTPException(
                status_code=400,
                detail=f"Non-finite weights not allowed: {', '.join(non_finite)}"
            )
        unknown = [k for k in payload.new_weights if k not in known]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown tickers: {', '.join(unknown)}"
            )
            
        # The same normalization rule the volatility-sizing engine publishes
        # (`divide_all_legs_by_gross_exposure`).  A submitted target whose gross
        # exposure exceeds 100 % needs financing this workflow cannot create,
        # so it is rejected instead of being normalized down into a fully
        # funded book: that silent 129 % -> 100 % rewrite is what made a
        # leveraged sizing target look applicable as a plain rebalance (V3-03).
        normalization = normalize_rebalance_weights(payload.new_weights)
        if normalization["rejection"] is not None:
            rejection = normalization["rejection"]
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Rebalance target rejected ({rejection['code']}): "
                    f"{rejection['detail']}. Normalization rule "
                    f"'{WEIGHT_NORMALIZATION_RULE}' does not create financing; "
                    "submit a fully funded target or size the position explicitly."
                ),
            )
        normalized_weights = normalization["weights"]
        weight_normalization = {
            "normalization_rule": WEIGHT_NORMALIZATION_RULE,
            "normalization_mode": normalization["normalization_mode"],
            "weights_normalized": normalization["weights_normalized"],
            "submitted_gross_exposure": normalization["submitted_gross_exposure"],
            "gross_exposure": normalization["gross_exposure"],
            "execution_eligible": normalization["execution_eligible"],
            "financing_required": normalization["financing_required"],
            "net_cash_weight": round(1.0 - normalization["gross_exposure"], 6),
        }
        
        simulated_orders = []
        total_buy_inr = 0.0
        total_sell_inr = 0.0
        total_weight_delta = 0.0
        
        for pos in positions:
            if pos.ticker in normalized_weights:
                curr_w = float(current_market_weights.get(pos.ticker, 0.0))
                new_w = round(float(normalized_weights[pos.ticker]), 4)
                w_delta = new_w - curr_w
                native_price = float(pos.last_price or 0.0)
                price_inr = float(converted_prices.get(pos.ticker, 0.0))
                if native_price <= 0 or price_inr <= 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Missing price for {pos.ticker}; rebalancing requires live position values"
                    )
                target_mv = new_w * total_pv
                # A zero target weight must fully exit the position (qty 0), not hold 1 share
                target_qty = round(target_mv / price_inr, 4)
                curr_qty = float(pos.quantity or 0.0)
                shares_delta = round(target_qty - curr_qty, 4)
                cash_delta = round(w_delta * total_pv, 2)
                
                if cash_delta > 0:
                    total_buy_inr += cash_delta
                else:
                    total_sell_inr += abs(cash_delta)
                total_weight_delta += abs(w_delta)
                
                simulated_orders.append({
                    "ticker": pos.ticker,
                    "current_weight": curr_w,
                    "target_weight": new_w,
                    "weight_delta": round(w_delta, 4),
                    "current_quantity": curr_qty,
                    "target_quantity": target_qty,
                    "shares_delta": shares_delta,
                    "price": native_price,
                    "price_currency": source_currencies[pos.ticker],
                    "value_currency": "INR",
                    "cash_delta": cash_delta,
                    "cash_delta_currency": "INR",
                    "action": "Hold" if abs(w_delta) < 0.005 else "Buy" if w_delta > 0 else "Sell"
                })
                
                if not payload.dry_run:
                    pos.weight = new_w
                    if pos.last_price and pos.last_price > 0:
                        pos.quantity = target_qty
                        pos.market_value = round(pos.quantity * pos.last_price, 2)
                    pos.updated_on = datetime.now(timezone.utc).replace(tzinfo=None)
        
        if not payload.dry_run:
            await db.commit()
            committed = True
            _clear_portfolio_dependent_memos()
            return {
                "success": True,
                "dry_run": False,
                "message": f"Successfully rebalanced {len(simulated_orders)} live positions in database",
                "total_portfolio_value": round(total_pv, 2),
                "total_portfolio_value_currency": "INR",
                "currency": "INR",
                "base_currency": "INR",
                "currency_provenance": currency_provenance,
                "total_turnover_pct": round(total_weight_delta / 2.0, 4),
                "weights": {p.ticker: p.weight for p in positions},
                "weight_normalization": weight_normalization,
                "orders": simulated_orders
            }
        else:
            return {
                "success": True,
                "dry_run": True,
                "message": "Simulation completed successfully (0 database records altered)",
                "total_portfolio_value": round(total_pv, 2),
                "total_portfolio_value_currency": "INR",
                "currency": "INR",
                "base_currency": "INR",
                "currency_provenance": currency_provenance,
                "total_turnover_pct": round(total_weight_delta / 2.0, 4),
                "total_buy_inr": round(total_buy_inr, 2),
                "total_sell_inr": round(total_sell_inr, 2),
                "weight_normalization": weight_normalization,
                "orders": simulated_orders,
                "simulated_weights": normalized_weights
            }
    except ProviderError as exc:
        if not committed:
            await db.rollback()
        _raise_provider_http_error(exc)
    except HTTPException:
        raise
    except Exception as exc:
        if not committed:
            await db.rollback()
        logger.error("Portfolio rebalance failed")
        detail = "Portfolio committed, but the response could not be prepared" if committed else "Internal server error"
        raise HTTPException(status_code=500, detail=detail) from exc


def _generate_ticker_suggestions(invalid_ticker: str) -> List[str]:
    """
    Generate helpful ticker suggestions based on common typos and similar tickers
    
    Args:
        invalid_ticker: The invalid ticker entered by user
        
    Returns:
        List of suggested ticker corrections
    """
    suggestions = []
    
    # Common ticker corrections and examples
    common_corrections = {
        # US Stocks
        'APPL': ['AAPL'],
        'GOOG': ['GOOGL'],
        'MSFT': ['MSFT'],
        'TSLA': ['TSLA'],
        'AMZN': ['AMZN'],
        'META': ['META'],
        'NVDA': ['NVDA'],
        'BRKB': ['BRK.B'],
        'GOOGL': ['GOOG'],
        # Popular Indian Stocks (NSE)
        'RELIANCE': ['RELIANCE.NS'],
        'TCS': ['TCS.NS'],
        'INFY': ['INFY.NS'],
        'HDFC': ['HDFCBANK.NS'],
        'ITC': ['ITC.NS'],
        'BHARTI': ['BHARTIARTL.NS'],
        'LT': ['LT.NS'],
        'KOTAK': ['KOTAKBANK.NS'],
        'ASIAN': ['ASIANPAINT.NS'],
        'MARUTI': ['MARUTI.NS'],
        'HCL': ['HCLTECH.NS'],
        'WIPRO': ['WIPRO.NS'],
        'ULTRA': ['ULTRACEMCO.NS'],
        'TATA': ['TATAMOTORS.NS'],
        'NESTLE': ['NESTLEIND.NS'],
        'BAJAJ': ['BAJFINANCE.NS'],
        'HINDU': ['HINDUNILVR.NS'],
        'POWER': ['POWERGRID.NS'],
        'NTPC': ['NTPC.NS'],
        'ONGC': ['ONGC.NS']
    }
    
    # Check for exact matches with common corrections
    if invalid_ticker.upper() in common_corrections:
        suggestions.extend(common_corrections[invalid_ticker.upper()])
    
    # Common pattern corrections
    ticker_upper = invalid_ticker.upper()
    
    # Check for missing letters (common typos)
    common_tick = ['AAPL', 'GOOGL', 'MSFT', 'TSLA', 'AMZN', 'META', 'NVDA', 'BRK.B']
    for ticker in common_tick:
        # Calculate edit distance
        if _is_similar_ticker(ticker_upper, ticker):
            suggestions.append(ticker)
    
    # Remove duplicates and limit to 3 suggestions
    unique_suggestions = list(dict.fromkeys(suggestions))[:3]
    
    return unique_suggestions


def _is_similar_ticker(ticker1: str, ticker2: str, max_distance: int = 2) -> bool:
    """
    Check if two tickers are similar within edit distance threshold
    
    Args:
        ticker1: First ticker
        ticker2: Second ticker
        max_distance: Maximum allowed edit distance
        
    Returns:
        True if tickers are similar, False otherwise
    """
    if len(ticker1) > 10 or len(ticker2) > 10:
        return False
        
    # Simple edit distance calculation
    distances = [[0] * (len(ticker2) + 1) for _ in range(len(ticker1) + 1)]
    
    for i in range(len(ticker1) + 1):
        distances[i][0] = i
    
    for j in range(len(ticker2) + 1):
        distances[0][j] = j
    
    for i in range(1, len(ticker1) + 1):
        for j in range(1, len(ticker2) + 1):
            if ticker1[i - 1] == ticker2[j - 1]:
                distances[i][j] = distances[i - 1][j - 1]
            else:
                distances[i][j] = 1 + min(
                    distances[i - 1][j],    # deletion
                    distances[i][j - 1],    # insertion
                    distances[i - 1][j - 1] # substitution
                )
    
    return distances[len(ticker1)][len(ticker2)] <= max_distance


async def _update_portfolio_prices(
    positions: List[PortfolioPosition], 
    data_service: DataService,
    force: bool = False
) -> None:
    """Update portfolio position prices concurrently if stale or forced"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stale_cutoff = now - timedelta(minutes=15)

    positions_to_update = [
        p for p in positions
        if force or not p.last_price or p.last_price <= 0 or not p.updated_on or p.updated_on < stale_cutoff
    ]

    if not positions_to_update:
        return

    sem = asyncio.Semaphore(5)

    async def update_one(position: PortfolioPosition):
        async with sem:
            try:
                quote_data = await data_service.fetch_quote(position.ticker)
                if quote_data and quote_data.get("current_price"):
                    position.last_price = quote_data["current_price"]
                    position.market_value = (position.quantity or 0) * position.last_price
                    if quote_data.get("sector") and not position.sector:
                        position.sector = quote_data["sector"]
                    if quote_data.get("industry") and not position.industry:
                        position.industry = quote_data["industry"]
                    if quote_data.get("currency"):
                        # Transient request metadata; persistence belongs to the
                        # D-owned position migration, not this API shim.
                        position._quote_currency = quote_data["currency"]
                    position.updated_on = datetime.now(timezone.utc).replace(tzinfo=None)
            except Exception:
                logger.error("Portfolio price refresh failed")

    await asyncio.gather(*[update_one(p) for p in positions_to_update])