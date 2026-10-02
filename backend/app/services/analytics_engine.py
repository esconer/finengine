"""
Real-time Analytics Engine for Portfolio Risk Calculations
Implements comprehensive financial analytics using quantstats, arch, and statsmodels
"""

import asyncio
import re

import numpy as np
import pandas as pd
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import warnings

# Financial analytics libraries
from arch import arch_model
try:
    from arch.utility.exceptions import ConvergenceWarning
    warnings.filterwarnings('ignore', category=ConvergenceWarning)
except ImportError:  # pragma: no cover - arch layout guard
    ConvergenceWarning = None
import statsmodels.api as sm

from app.config import settings
from app.utils.allocations import (
    build_sizing_basis,
    build_trade_instructions,
    normalization_block,
    sizing_history_block,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _finite_weight(weights: Optional[Dict[str, Any]], ticker: str) -> float:
    """Current weight of `ticker` as a finite float; 0.0 when unusable.

    A malformed or non-finite stored weight must not poison a weight delta.
    """
    try:
        value = float((weights or {}).get(ticker, 0.0))
    except (TypeError, ValueError):
        return 0.0
    return value if np.isfinite(value) else 0.0


#: Minimum fraction of gross positive weight a date must cover before it is
#: published as a PORTFOLIO return.  The previous contract kept any date with
#: one live constituent and renormalised the survivors to 1.0, so a date on
#: which a single 3.3 % leg traded was published as if the whole book had
#: moved, with that leg's weight inflated by 1/0.033 = 30x.  A partial basket
#: is not the portfolio; it is a different, smaller portfolio whose identity
#: changes from day to day.  Below the threshold the date is DROPPED (never
#: zero-filled, never renormalised) so the published series only ever contains
#: dates on which the whole declared book was measurable.
PORTFOLIO_RETURN_MIN_COVERAGE = 1.0

#: Relative tolerance for the coverage comparison.  ``covered == gross`` must
#: not be rejected because the two sums were accumulated in a different order.
COVERAGE_TOLERANCE = 1e-12


def _active_weight_frame(
    clean: pd.DataFrame, weights: Dict[str, float]
) -> Optional[pd.Series]:
    """Positive, finite weights aligned to `clean`'s columns, else ``None``."""
    usable_weights: Dict[str, float] = {}
    for column in clean.columns:
        try:
            weight = float(weights.get(column, 0.0))
        except (TypeError, ValueError):
            continue
        if np.isfinite(weight) and weight > 0.0:
            usable_weights[column] = weight
    if not usable_weights:
        return None
    return pd.Series(usable_weights, dtype=float).reindex(
        clean.columns, fill_value=0.0
    )


def active_return_coverage(
    returns: pd.DataFrame,
    weights: Dict[str, float],
    min_coverage: Optional[float] = None,
) -> pd.DataFrame:
    """Per-date constituent count and covered weight fraction.

    One row per date in `returns`, in the caller's index order:

    ``constituent_count``
        How many positive-weight legs had a finite return that date.
    ``covered_weight`` / ``gross_weight``
        The weight that traded, and the weight that was declared.
    ``covered_weight_fraction``
        ``covered_weight / gross_weight`` -- 1.0 means the whole book traded.
    ``renormalization_uplift``
        ``gross_weight / covered_weight``.  The factor by which the OLD
        contract inflated the surviving legs' weights.  Always 1.0 on a
        published date; the value it reaches on a dropped date is exactly the
        size of the distortion that used to ship silently.
    ``published``
        Whether the date clears `min_coverage` and carries any weight at all.
    """
    columns = [
        "constituent_count",
        "covered_weight",
        "gross_weight",
        "covered_weight_fraction",
        "renormalization_uplift",
        "published",
    ]
    threshold = (
        PORTFOLIO_RETURN_MIN_COVERAGE if min_coverage is None else float(min_coverage)
    )
    empty = pd.DataFrame(columns=columns)
    if not isinstance(returns, pd.DataFrame) or returns.empty:
        return empty

    clean = returns.replace([np.inf, -np.inf], np.nan)
    weight_frame = _active_weight_frame(clean, weights)
    if weight_frame is None:
        return empty

    gross_weight = float(weight_frame.sum())
    active = clean.notna() & (weight_frame > 0.0)
    covered_weight = active.mul(weight_frame, axis=1).sum(axis=1)
    fraction = (
        covered_weight / gross_weight if gross_weight > 0.0 else covered_weight * 0.0
    )
    covered_values = covered_weight.to_numpy(dtype=float)
    safe_covered = np.where(covered_values > 0.0, covered_values, 1.0)
    frame = pd.DataFrame(
        {
            "constituent_count": active.sum(axis=1).astype(int),
            "covered_weight": covered_weight.astype(float),
            "gross_weight": float(gross_weight),
            "covered_weight_fraction": fraction.astype(float),
            # The factor by which the old contract inflated the survivors.
            # Infinite when a date had no live weight at all -- exactly the
            # dates the old contract omitted outright.
            "renormalization_uplift": np.where(
                covered_values > 0.0, gross_weight / safe_covered, np.inf
            ),
        },
        index=clean.index,
    )
    frame["published"] = (
        (frame["covered_weight_fraction"] >= threshold - COVERAGE_TOLERANCE)
        & (frame["covered_weight"] > 0.0)
    )
    return frame[columns]


def _iso_date(index: Any) -> Optional[str]:
    """`index` as an ISO date string, or None when it is not a real date."""
    try:
        return pd.Timestamp(index).date().isoformat()
    except (TypeError, ValueError):
        return None


def portfolio_return_coverage_block(
    returns: pd.DataFrame,
    weights: Dict[str, float],
    min_coverage: Optional[float] = None,
) -> Dict[str, Any]:
    """Publishable audit trail for the portfolio-return coverage rule.

    The gate drops dates silently from the metric series; this block is how a
    reader finds out which dates went, how thin they were, and how far the old
    renormalisation would have inflated them.
    """
    threshold = (
        PORTFOLIO_RETURN_MIN_COVERAGE if min_coverage is None else float(min_coverage)
    )
    frame = active_return_coverage(returns, weights, threshold)
    if frame.empty:
        return {
            "basis": (
                "per-date fraction of gross positive weight with a finite "
                "constituent return"
            ),
            "min_covered_weight_fraction": float(threshold),
            "coverage_rule": (
                "a date is published as a portfolio return only when its "
                "covered weight fraction reaches the minimum; short dates are "
                "dropped, never zero-filled and never renormalised"
            ),
            "total_dates": 0,
            "published_dates": 0,
            "dropped_dates": 0,
            "dates": [],
            "error": "no positive-weight constituents with return history",
        }

    published = frame[frame["published"]]
    dropped = frame[~frame["published"]]

    def _finite_max(source: pd.DataFrame, column: str) -> Optional[float]:
        """Largest finite value in `column`, or None.

        A date with no covered weight at all has an infinite uplift, and
        `Infinity` is not valid JSON -- the old rule omitted those dates
        outright, so there is no distortion to report for them.
        """
        values = source[column].to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        return float(values.max()) if values.size else None

    return {
        "basis": (
            "per-date fraction of gross positive weight with a finite "
            "constituent return"
        ),
        "min_covered_weight_fraction": float(threshold),
        "coverage_rule": (
            "a date is published as a portfolio return only when its covered "
            "weight fraction reaches the minimum; short dates are dropped, "
            "never zero-filled and never renormalised"
        ),
        "total_dates": int(len(frame)),
        "published_dates": int(len(published)),
        "dropped_dates": int(len(dropped)),
        # Spelled out for a reader (and an audit rule) that greps for the
        # defect by name. Both are exact counts, not claims.
        "renorm": "not_applied",
        "partial_basket_days": int(len(dropped)),
        "min_published_constituent_count": (
            int(published["constituent_count"].min()) if not published.empty else None
        ),
        "max_published_renormalization_uplift": _finite_max(
            published, "renormalization_uplift"
        ),
        "max_dropped_renormalization_uplift": _finite_max(
            dropped, "renormalization_uplift"
        ),
        "max_dropped_covered_weight_fraction": _finite_max(
            dropped, "covered_weight_fraction"
        ),
        "dates": [
            {
                "date": _iso_date(index),
                "constituent_count": int(row["constituent_count"]),
                "covered_weight_fraction": round(
                    float(row["covered_weight_fraction"]), 6
                ),
                "published": bool(row["published"]),
            }
            for index, row in frame.iterrows()
        ],
    }


def aggregate_active_returns(
    returns: pd.DataFrame,
    weights: Dict[str, float],
    min_coverage: Optional[float] = None,
) -> pd.Series:
    """Aggregate returns using the shared active positive-weight contract.

    A date is published only when at least one positive-weight constituent has
    a finite return AND the covered weight fraction reaches `min_coverage`
    (default :data:`PORTFOLIO_RETURN_MIN_COVERAGE` = 1.0, i.e. the whole
    declared book traded).  Dates that fall short are DROPPED.  They are not
    zero-filled -- that would assert a flat day for a leg that did not trade --
    and they are not renormalised, because renormalisation republishes a
    partial basket under the portfolio's name: on a day where one 3.3 % leg is
    the only live constituent, renormalising hands that leg 100 % of the
    portfolio's return and 30x its weight.  Such a day is a *different*
    portfolio, and the resulting series is not the one the reader is holding.

    Keeping this helper at module scope lets API orchestration use exactly the
    same rule as the service.
    """
    if not isinstance(returns, pd.DataFrame) or returns.empty:
        return pd.Series(dtype=float)

    clean = returns.replace([np.inf, -np.inf], np.nan)
    weight_frame = _active_weight_frame(clean, weights)
    if weight_frame is None:
        return pd.Series(dtype=float)

    coverage = active_return_coverage(clean, weights, min_coverage)
    keep = coverage.index[coverage["published"]]
    if len(keep) == 0:
        return pd.Series(dtype=float)

    active = clean.notna() & (weight_frame > 0.0)
    numerator = clean.where(active, 0.0).mul(weight_frame, axis=1).sum(axis=1)
    covered_weight = coverage["covered_weight"]
    portfolio = (numerator.loc[keep] / covered_weight.loc[keep]).astype(float)
    return portfolio.replace([np.inf, -np.inf], np.nan).dropna().astype(float)


# ---------------------------------------------------------------------------
# liquidity: one documented score-band contract (V3-09)
# ---------------------------------------------------------------------------
# The published `score` is the raw score rounded once, and the band is a
# function of THAT published value.  Deriving the band from the unrounded score
# let a raw 7.96 publish `score=8.0` with a "Medium" band while the volume
# distribution counted the same position as high.  Every band label, every
# liquidation window and every high/medium/low count now reads the published
# score through the single table below.
LIQUIDITY_SCORE_PRECISION = 1

# (band, inclusive lower bound on the published score, liquidation window)
LIQUIDITY_SCORE_BANDS = (
    ("High", 8.0, "1-2"),
    ("Medium", 6.0, "2-5"),
    ("Low", None, "5-10"),
)

# Risk level inverts the score band: a high liquidity score is a low risk.
LIQUIDITY_BAND_RISK_LEVEL = {"High": "Low", "Medium": "Medium", "Low": "High"}

LIQUIDITY_SCORE_BAND_RULE = {
    "raw_score_field": "score_raw",
    "published_score_field": "score",
    "rounding": "round(raw_score, 1) applied once; `score` is that rounded value",
    "band_source": "published_score",
    "score_range": [0.0, 10.0],
    "bands": [
        {
            "band": "High",
            "min_published_score": 8.0,
            "max_published_score": None,
            "liquidation_days": "1-2",
            "volume_stats_bucket": "high",
        },
        {
            "band": "Medium",
            "min_published_score": 6.0,
            "max_published_score": 8.0,
            "liquidation_days": "2-5",
            "volume_stats_bucket": "medium",
        },
        {
            "band": "Low",
            "min_published_score": None,
            "max_published_score": 6.0,
            "liquidation_days": "5-10",
            "volume_stats_bucket": "low",
        },
    ],
    "volume_stats_basis": "positions per published-score band, as a share of measured positions",
    "risk_level_rule": "inverted band: High->Low, Medium->Medium, Low->High",
}

# Market cap provenance (V3-09).  The only market-cap input is the quote the
# route supplies; a missing cap is either annualised from measured turnover or
# floored, and both substitutes must be labelled instead of looking measured.
LIQUIDITY_MARKET_CAP_FLOOR_INR = 1_000_000_000.0
LIQUIDITY_IMPLIED_TURNOVER_DAYS = 250

# Stress shock-proxy configuration (V3-10).  These are the inputs behind the
# deterministic factor proxy; they travel with the result so a reader can see
# that the published drawdown is a proxy, not a simulated statistic.
STRESS_VOL_REFERENCE = 0.22
STRESS_VOL_ADJ_MIN = 0.85
STRESS_VOL_ADJ_MAX = 1.25
STRESS_VOL_MIN_OBSERVATIONS = 20
STRESS_DRAWDOWN_UPLIFT = 1.15
STRESS_CONFIDENCE_LABEL = 0.95

#: The sector a holding lands in when the route supplied none.  The route fills
#: `sectors` from `PortfolioPosition.sector`, so this is the UNCLASSIFIED bucket
#: and NOT a statement that its members are exchange traded funds: a holding
#: whose sector is NULL lands here whatever instrument it is -- a domestic
#: broad index tracker, a domestic midcap tracker, an Indian IPO/small-cap
#: fund and a US-listed mega-cap technology fund all share it.  The engine has
#: no other classification for a holding, and nothing in this repository
#: carries one (see `shock_inputs.bucket_disclosure`).
STRESS_UNCLASSIFIED_SECTOR = "Exchange Traded Fund"

#: The measured co-movement published beside the flat table entry, so the claim
#: that one index sensitivity fits the whole bucket is CHECKABLE instead of
#: asserted.  Fewer other holdings than this and the leave-one-out reference
#: degenerates: on a two-name book each holding IS the other's reference, so
#: the coefficient would be exactly 1.0 for both of them -- arithmetic, not a
#: measurement.
STRESS_CO_MOVEMENT_MIN_REFERENCE_LEGS = 3
#: Paired daily observations the regression needs before it is a measurement.
STRESS_CO_MOVEMENT_MIN_OBSERVATIONS = 30
#: What the coefficient is, in one string.  It is deliberately NOT called a
#: market beta: see `_stress_holding_co_movement` for why using it as the
#: shock elasticity would publish a different statistic than the scenario's.
STRESS_CO_MOVEMENT_BASIS = (
    "measured_co_movement_with_the_rest_of_the_delivered_book_not_a_market_beta"
)

# ---------------------------------------------------------------------------
# concentration / diversification disclosure
# ---------------------------------------------------------------------------
#: `diversification_score` was published as a bare 0-100 number with no scale, no
#: formula and no holding count: 98.5 on the v26 book, and a reader could neither
#: reproduce it nor tell what the top of the scale means.  The two anchors below
#: are the repo's own stated intent -- `tests/test_quantitative_invariants.py`
#: asserts equal weight scores 100.0 and a single holding scores 0.0 -- so the
#: scale is declared from the behaviour that is already tested, not invented.
#: `n_holdings` is published because NEITHER formula can be evaluated without it
#: and it was previously recoverable only by counting `by_weight`.
CONCENTRATION_DIVERSIFICATION_SCALE = {
    "min": 0.0,
    "max": 100.0,
    "unit": "index_0_to_100_higher_is_better_diversified",
    "at_max": (
        "100 is every holding carrying the SAME weight, i.e. "
        "herfindahl_index == 1 / n_holdings. It is a normalized value, not a "
        "count: 100 does not mean many holdings, it means evenly held whatever "
        "the count is"
    ),
    "at_min": (
        "0 is one holding carrying the whole book, i.e. herfindahl_index == 1. "
        "A single-holding book (n_holdings == 1) is published as 0.0 because "
        "the formula's denominator 1 - 1/n_holdings is exactly 0 there and the "
        "limit of the expression is 0"
    ),
    "holdings_basis": (
        "n_holdings counts the rows with a strictly positive, finite weight "
        "AFTER the weights are normalized to sum to 1. Zero, negative and "
        "non-finite rows are not holdings and are excluded before the count. "
        "Each holding is counted ONCE, at its own weight, with no look-through "
        "into its own constituents: a holding that is itself a fund is one row "
        "here and is never decomposed into what it holds. That is a LIMITATION "
        "of this measure rather than a claim about it - the concentration inside "
        "a single holding is not measured here, is not in n_holdings, and is not "
        "in herfindahl_index. On a book of Indian listings that means a US "
        "megacap-technology fund is ONE of fourteen holdings, so the book reads "
        "as fourteen-way diversified while the technology exposure inside that "
        "one row is unmeasured, and any currency the holding trades in a currency "
        "other than the book's is likewise not represented anywhere in this "
        "block"
    ),
}

CONCENTRATION_DIVERSIFICATION_SCORE_FORMULA = (
    "diversification_score = ((1 - herfindahl_index) / (1 - 1/n_holdings)) * 100, "
    "where herfindahl_index = sum(w_i^2) over the normalized weights. It is the "
    "Herfindahl index placed on a 0-100 scale by normalizing against the "
    "equal-weight value 1/n_holdings, and it is published as 0.0 when "
    "n_holdings <= 1"
)

CONCENTRATION_DIVERSIFICATION_RATIO_FORMULA = (
    "diversification_ratio = effective_positions / n_holdings, where "
    "effective_positions = 1 / herfindahl_index. This is a DIFFERENT statistic "
    "from diversification_score, not a second expression of it: the ratio "
    "coincides with the score (as a fraction) only at equal weight, and it "
    "falls as the book concentrates while the score is normalized against "
    "n_holdings. The two are not expected to agree and are not reconciled here. "
    "ORIENTATION, because the two run on different scales and reading one as the "
    "other makes a single book look self-contradictory: the ratio's MAXIMUM is "
    "1.0, at equal weight, which is exactly where diversification_score is at "
    "its 100, and the ratio's MINIMUM is 1 / n_holdings, at one holding "
    "carrying the whole book, which is exactly where diversification_score is at "
    "its 0. Both therefore point the same way - larger is better diversified - "
    "so the ratio reads as the fraction of the book that behaves as if it were "
    "independently and equally weighted (a ratio of r on a book of n holdings "
    "is a book behaving as if it held about r * n equal names), while the score "
    "reads as the percentage of the way from one holding to equal weight. A "
    "book can and does publish a ratio near 0.8 next to a score near 100: those "
    "are the same concentration on two scales, not two numbers that disagree, "
    "and the ratio is not a percentage of diversification to be compared with "
    "the score"
)

#: `effective_positions` is built from the UNROUNDED Herfindahl index while
#: `herfindahl_index` is published at 4 decimals, so `1 / herfindahl_index` does
#: not reproduce it exactly on an arbitrary book.  Stated rather than left for a
#: reader to trip over -- the gap is a rounding one, not an error, and no
#: published value is changed to hide it.
CONCENTRATION_EFFECTIVE_POSITIONS_NOTE = (
    "effective_positions = 1 / herfindahl_index computed on the UNROUNDED index, "
    "while herfindahl_index is published rounded to 4 decimals, so dividing the "
    "PUBLISHED index does not reproduce effective_positions exactly. "
    "diversification_score and diversification_ratio are both built from the "
    "same unrounded index. herfindahl_index is published at 4 decimals because "
    "the concentration leg of overall_score is scored from it, and rounding it "
    "further would move that leg's sub-score"
)

#: Risk points, on the 0-30 sub-score scale, per unit of measured average
#: pairwise correlation. The sub-score is `min(30, POINTS * max(0, avg_corr))`.
#: There is deliberately no "free" correlation baseline: the previous form,
#: `clip((avg_corr - 0.3) * 50, 0, 30)`, mapped every measured average
#: correlation at or below 0.3 onto exactly 0, which is the same value an
#: UNMEASURED leg publishes, so a real measurement shipped as an
#: indistinguishable hard zero and dragged `overall_score` down (D-04).
RISK_CORRELATION_POINTS_PER_UNIT = 50.0

#: Shared finite return rows below which a Pearson correlation is not a
#: measurement. pandas' `.corr()` is PAIRWISE COMPLETE -- each pair is measured
#: on the rows where THAT pair is finite -- and its own answer for a pair under
#: this floor is NaN. NaN means "not measurable"; it is never the number 0.0.
#: This is the same floor `pairwise_average_correlation_statistics` applies
#: when it reproduces the risk-score leg's own statistic.
MIN_SHARED_ROWS_FOR_CORRELATION = 2

#: Why a correlation is refused rather than substituted, wherever one is
#: consumed. Three paths carried `.fillna(0.0)` on a pairwise-complete
#: correlation matrix -- the risk score's own leg was already fixed, and the
#: volatility-sizing current book, the volatility-sizing scale, and HRP's
#: distance matrix were not. In a correlation matrix 0.0 is not a neutral
#: placeholder, it is the strongest available claim ("no relationship
#: whatsoever"), so filling a hole with it told the reader a late-listed,
#: barely-overlapping leg was a free diversifier, and in HRP it placed the pair
#: at `sqrt(0.5 * (1 - 0))` -- the largest distance the matrix contains.
#: Vocabulary matches the risk-score leg, which publishes `None` plus an
#: `excluded` entry rather than a stand-in number.
UNMEASURABLE_CORRELATION_REASON = (
    "fewer than two shared return rows, so the pairwise correlation is not "
    "measurable; it is unknown, not zero"
)

#: Lower bound of the 0-30 sub-score scale, and the reason a leg can publish
#: exactly 0.0 for a MEASURED input.  The scale has no negative risk points: a
#: negatively-correlated book is a real measurement, but "correlated" is not a
#: signed risk quantity, so the only way to publish it on a 0-30 higher-is-
#: riskier scale is to clamp it at zero.  That clamp is what used to be
#: invisible -- `max(0, avg)` floored a measured -0.13 onto a sub-score of 0.0
#: that reads exactly like a measured zero.  The cap has always been declared
#: (:data:`RISK_SCORE_CAP`, plus the per-leg saturation state), so the floor is
#: declared the same way: the bound, the input at which it binds, whether it
#: bound for this score, and the number of points it added.
#:
#: The floor is deliberately NOT removed.  Letting a negative average
#: correlation publish negative risk points would move `overall_score` and can
#: flip `risk_level` -- a product decision, not an engineering one -- and it
#: would break the 0-30 scale every other leg and the published methodology
#: claim.  The clamp stays; what changes is that it is now legible.
RISK_SCORE_FLOOR = 0.0

# ---------------------------------------------------------------------------
# risk-score composition disclosure (RL-3)
# ---------------------------------------------------------------------------
# `overall_score` is a weighted average of five 0-30 sub-scores, and the
# arithmetic was never wrong.  What the payload did not say is how much of the
# headline is evidence.  Two of the five legs are not independent measurements,
# and a third is pinned at its ceiling, so a reader counting five components was
# counting one twice and a constant once.  The constants below are what make
# each leg recomputable from one published input, and they are the single source
# of truth for BOTH the applied weights and the published weights, so a
# published weight cannot drift from the applied one.

#: Ceiling of every leg's 0-30 sub-score scale (higher is riskier).  Each leg is
#: ``min(CAP, <expression of exactly one published input>)``, so a leg sitting ON
#: this number is not a measurement of a large risk: it is the ceiling, reached
#: by every input past that leg's own unpinning threshold.  That is why
#: saturation has to be stated rather than left for the reader to infer from the
#: value: 30 is a reading and a ceiling at the same time.
RISK_SCORE_CAP = 30.0

#: Rows in the market-risk leg's "recent" window.  When the delivered portfolio
#: return series is no longer than this the window IS the whole series, so the
#: market leg measures exactly the statistic the volatility leg already measured
#: and the two sub-scores are the same number.  The duplication is a property of
#: the SAMPLE LENGTH, not of the code, so it is measured from the series that was
#: actually delivered and published either way -- it clears itself as history
#: grows past 60 rows, and a hard-coded "these two are the same" would be wrong
#: the moment the book is older than the window.
RISK_MARKET_WINDOW_ROWS = 60

#: Nominal leg weights, in report order.  Sums to 1.0.  A leg that could not be
#: measured is dropped and the remainder renormalized (`excluded_components`).
RISK_SCORE_WEIGHTS: Dict[str, float] = {
    "concentration": 0.20,
    "volatility": 0.25,
    "correlation": 0.20,
    "factor_risk": 0.25,
    "market_risk": 0.10,
}

#: R-squared at or below which the factor leg's uncapped expression
#: ``(1 - R^2) * 100`` has already reached :data:`RISK_SCORE_CAP`.  The leg
#: publishes 30 for EVERY R^2 at or under this, so on a book whose benchmark
#: explains little variance it contributes a constant.
RISK_FACTOR_UNPIN_R_SQUARED = 1.0 - RISK_SCORE_CAP / 100.0

#: One row per leg: what the leg is computed FROM, so a reader can recompute it
#: instead of trusting it.  ``cap_binding_input`` is the input value at which the
#: leg's uncapped expression equals :data:`RISK_SCORE_CAP`, and
#: ``unpin_condition`` says which side of it the leg is on -- a leg at its cap
#: can only move when its input crosses back over that threshold.
#:
#: ``duplication_group`` names the statistic family in which a SECOND leg would
#: stop being independent evidence.  ``None`` means no other leg measures the
#: same quantity, so duplication is structurally impossible for that leg; it is
#: a claim about the table, and the table is published beside the scores.
RISK_SCORE_LEG_SPECS: Dict[str, Dict[str, Any]] = {
    "concentration": {
        "input_statistic": "herfindahl_index",
        "input_units": "sum_of_squared_active_portfolio_weights",
        "formula": "min(30, herfindahl_index * 100)",
        "cap_binding_input": RISK_SCORE_CAP / 100.0,
        "cap_binds_when_input_is": ">= 0.30",
        "unpin_condition": "herfindahl_index < 0.30",
        "published_input_as": "score_audit.components.concentration.input_statistic_value",
        "duplication_group": None,
    },
    "volatility": {
        "input_statistic": "portfolio_return_annualized_volatility",
        "input_units": "annualized_fraction_of_1",
        "formula": "min(30, portfolio_returns.std() * sqrt(252) * 100)",
        "cap_binding_input": RISK_SCORE_CAP / 100.0,
        "cap_binds_when_input_is": ">= 0.30 (30% annualized)",
        "unpin_condition": "annualized portfolio volatility < 0.30",
        "published_input_as": "score_audit.components.volatility.input_statistic_value",
        "duplication_group": "portfolio_volatility",
    },
    "correlation": {
        "input_statistic": "avg_pairwise_correlation",
        "input_units": "pearson_r_over_upper_triangle",
        "formula": (
            "min(30, "
            f"{RISK_CORRELATION_POINTS_PER_UNIT:g} * max(0, avg_pairwise_correlation))"
        ),
        "cap_binding_input": RISK_SCORE_CAP / RISK_CORRELATION_POINTS_PER_UNIT,
        "cap_binds_when_input_is": ">= 0.60",
        "unpin_condition": "avg pairwise correlation < 0.60",
        # The floor is reachable for this leg and for no other: it is the only
        # leg whose expression can go negative. `cap_binding_input` /
        # `unpin_condition` describe the ceiling; these describe the floor, and
        # the per-leg state (`clamped_at_floor`, `floor_clamp_points`) says
        # whether it bound for this score.
        "floor_binding_input": RISK_SCORE_FLOOR,
        "floor_binds_when_input_is": "<= 0.00 (a measured average correlation at or below zero)",
        "floor_reason": (
            "the 0-30 sub-score scale has no negative risk points, so a "
            "measured average pairwise correlation at or below zero cannot be "
            "published as negative risk and is clamped at "
            f"{RISK_SCORE_FLOOR:g}. The measurement itself is not changed: "
            "avg_pairwise_correlation and the input_statistic_value below are "
            "the measured sign, and floor_clamp_points is how far the sub-score "
            "was moved to express it on this scale"
        ),
        "published_input_as": "avg_pairwise_correlation",
        "duplication_group": None,
    },
    "factor_risk": {
        "input_statistic": "benchmark_regression_r_squared",
        "input_units": "fraction_of_portfolio_return_variance_explained",
        "formula": "min(30, (1 - r_squared) * 100)",
        "cap_binding_input": RISK_FACTOR_UNPIN_R_SQUARED,
        "cap_binds_when_input_is": "<= 0.70",
        "unpin_condition": "R-squared > 0.70",
        "published_input_as": "factor_r_squared",
        "duplication_group": None,
    },
    "market_risk": {
        "input_statistic": "recent_portfolio_return_annualized_volatility",
        "input_units": "annualized_fraction_of_1",
        "formula": (
            f"min(30, portfolio_returns.tail({RISK_MARKET_WINDOW_ROWS})"
            ".std() * sqrt(252) * 100)"
        ),
        "cap_binding_input": RISK_SCORE_CAP / 100.0,
        "cap_binds_when_input_is": ">= 0.30 (30% annualized)",
        "unpin_condition": "annualized recent portfolio volatility < 0.30",
        "published_input_as": "score_audit.components.market_risk.input_statistic_value",
        "duplication_group": "portfolio_volatility",
    },
}

# ---------------------------------------------------------------------------
# risk-score precision disclosure (SI-5 tail)
# ---------------------------------------------------------------------------
# `score_audit` above says what the headline is MADE OF.  It does not say how
# precisely each ingredient is known, and the three ingredients are three
# different kinds of number:
#
#   * an ESTIMATED STATISTIC - `avg_pairwise_correlation`, `factor_r_squared` -
#     is measured from data, so it gets a resampling standard error, an interval
#     and an effective-sample-size figure from `measure_estimate_uncertainty`.
#   * a DERIVED SUB-SCORE - every leg's `min(30, <expression of one published
#     input>)` - is a deterministic function of a number already on the payload.
#     Its precision is INHERITED from that input, and it is given no interval of
#     its own: an independent band for a function of a published value would be
#     a second, fabricated estimate of something already published.
#   * a DECLARED CONSTANT - the leg weights - is chosen by design.  It has no
#     sampling distribution at all, so a standard error for it would be a
#     statement about a design decision wearing the clothes of a measurement.
#
# Publishing the three differently is the whole disclosure.  A rule that cannot
# tell a declared constant from an estimated parameter cannot be satisfied here
# honestly, and that is a limitation of the rule rather than a licence to
# manufacture a confidence interval for a weight somebody typed.
RISK_SCORE_PRECISION_BASIS = (
    "the numbers a risk score is made of are three different kinds of thing, "
    "and a standard error is only a statement about one of them. Estimated "
    "statistics are measured from data and carry a resampling standard error, "
    "an interval and an effective-sample-size figure. Sub-scores are "
    "deterministic functions of exactly one published input, so their precision "
    "is INHERITED from that input and they carry no interval of their own. The "
    "leg weights are declared policy constants: they have no sampling "
    "distribution, so they carry no standard error at all."
)

#: Where the weight table lives, named so a reader can find the constants rather
#: than take the payload's word that they are constants.
RISK_SCORE_WEIGHT_TABLE = (
    "app/services/analytics_engine.py: RISK_SCORE_WEIGHTS (the module-level "
    "table this section's nominal weights and the applied weights are both read "
    "from; one source, so a published weight cannot drift from the applied one)"
)

RISK_SCORE_DECLARED_CONSTANT_BASIS = (
    "declared policy constant, not an estimated parameter. RISK_SCORE_WEIGHTS "
    "is a design decision about how much of the headline each leg should carry; "
    "it is chosen before any return series is measured and is not inferred from "
    "one. A standard error would describe the sampling variability of a number "
    "estimated from data, and there is no such variability here: re-running the "
    "score on a different window changes the sub-scores but never the weight. "
    "It is therefore published with no standard error and no interval, which is "
    "a statement about the number rather than a gap in one."
)

#: What a rule that requires a standard error, an interval or an
#: effective-sample-size figure would need in order to read this section
#: correctly.  Recorded in the payload because the payload IS the audit
#: surface: a consumer that treats a declared constant as a bare point estimate
#: will keep reporting a defect that is not there.
RISK_SCORE_RULE_LIMITATION = (
    "a precision-disclosure rule keyed on key names alone cannot distinguish a "
    "declared constant (a weight) from an estimated parameter (a correlation or "
    "an R-squared), and cannot tell a derived value from a measured one. This "
    "section therefore classifies every number it publishes (estimated / "
    "deterministic_derivation / declared_constant) and gives each class the "
    "disclosure that class admits, instead of giving all of them the same band."
)

#: Both estimated inputs this section publishes are rounded to 4 decimal
#: places, so half a display step is 5e-5 and `measure_estimate_uncertainty` is
#: held to 1e-4: the same margin the tear sheet uses for its own 4 dp betas.
#: Wider would admit a restatement that measures a neighbouring statistic.
RISK_SCORE_STATISTIC_DECIMALS = 4
RISK_SCORE_PUBLISHED_DP_TOLERANCE = 1e-4

#: Where each leg input's own precision is published, when it is.  A leg whose
#: input is absent from this map has NO precision disclosure in this section,
#: and the leg says so rather than borrowing one.
#:
#: EVERY value here must resolve to a node that actually carries a standard error
#: or an interval.  That is the whole contract, and it is not decorative: this
#: map used to carry `"herfindahl_index": "score_audit.precision.declared_constants"`,
#: which pointed a MEASURED input (`input_statistic_provenance: "measured"`) at
#: the weight table - a node whose own class definition says it "was never
#: estimated" and whose `standard_error` and `conf_int` are both `null`.  The
#: sub-score therefore claimed to inherit a precision from a node that declares
#: it has none, and the node it should have pointed at
#: (`score_audit.precision.estimated_statistics`) holds only the two estimated
#: statistics, so there was no Herfindahl disclosure anywhere in the block.  A
#: null pointer with the reason is strictly more informative than a pointer to
#: nothing, and `test_every_inherits_precision_pointer_resolves_to_a_real_figure`
#: is the general form that catches the whole class.
RISK_SCORE_INPUT_PRECISION_AT: Dict[str, str] = {
    "avg_pairwise_correlation": (
        "score_audit.precision.estimated_statistics.avg_pairwise_correlation"
        ".estimates.avg_pairwise_correlation"
    ),
    "benchmark_regression_r_squared": (
        "score_audit.precision.estimated_statistics.factor_r_squared"
        ".estimates.factor_r_squared"
    ),
}

RISK_SCORE_PAIRWISE_ESTIMATOR_BASIS = (
    "pairwise_average_correlation_statistics: a vectorised restatement of this "
    "section's own correlation leg - the mean of the finite upper-triangle "
    "Pearson correlations of the constituent return frame, exactly as "
    "returns.corr() computes it. The pair, the date and the frame are all the "
    "published ones, so the interval belongs to the published number; the "
    "reproduction guard in measure_estimate_uncertainty refuses the band if it "
    "does not."
)

RISK_SCORE_PAIRWISE_RESAMPLE_RULE = (
    "the resample count is the standard one on any book whose pairwise work "
    "fits the budget, and is REDUCED - and published as bootstrap_resamples - on "
    "a book too wide for the disclosure to fit in a request. The statistic costs "
    "O(rows x draws x pairs), so a 200-name book at 1000 draws is two orders of "
    "magnitude more work than a 14-name book. The reduction is a cost decision "
    "about how many draws the interval is read from, not a change to the "
    "estimator, the sample, or the published point"
)

#: Which rows the correlation statistic is measured on.  Every row is kept: the
#: statistic is pairwise, so a row a single leg was unpriced on is still a row
#: for every other pair.  Only a wholly non-finite row is dropped, and it is
#: counted in dropped_non_finite_observations.
def _pairwise_row_filter(raw: Any) -> np.ndarray:
    values = np.asarray(raw, dtype=float)
    if values.ndim != 2:
        return np.zeros(0, dtype=bool)
    return np.isfinite(values).any(axis=1)


RISK_SCORE_PAIRWISE_ROW_FILTER = _pairwise_row_filter

RISK_SCORE_PAIRWISE_ROW_FILTER_BASIS = (
    "every row that carries a finite return for AT LEAST ONE constituent. The "
    "published statistic is the mean of PAIRWISE correlations and pandas' .corr() "
    "is pairwise complete, so a row unpriced for one leg is still a measurement "
    "for every other pair; dropping it would measure the complete-case mean "
    "instead, which is a different number on any book with a late-listed leg. "
    "Rows with no finite return at all are dropped and counted."
)

#: Identity of the factor leg's own fit, so two fits of the "same" model over
#: different windows are told apart rather than reported as contradicting.
RISK_SCORE_ADJUSTED_R_SQUARED_BASIS = (
    "risk_score factor leg: portfolio return regressed on a constant plus the "
    "benchmark over the score's own holding-window price frame. It is a "
    "DIFFERENT model from factor_exposure's full-exchange-history fit of the "
    "same pair, and the two are expected to disagree; only a disagreement "
    "between fits claiming THIS basis is a contradiction. This is statsmodels' "
    "rsquared_adj from the same fit as the published factor_r_squared, at the "
    "same observation count - a restatement of one fit, not a second estimate"
)

# ---------------------------------------------------------------------------
# forecast tail contract (SI-3 / QM-3 / AD-2)
# ---------------------------------------------------------------------------
# The fitted GARCH/EGARCH models use `dist='normal'`, so their conditional
# distribution is N(0, sigma_t^2) and the two numbers below ARE the correct
# quantiles of THAT distribution -- a 95% VaR is -1.645 * sigma_t and a 95%
# expected shortfall is -2.06 * sigma_t.  They are constants because the
# normal distribution's quantiles are constants, not because the risk was
# faked.  What was indefensible is that NONE of this was published: no level,
# no units, no sign convention, and a "confidence interval" that was a fixed
# +/-20 % haircut on the point forecast.  The values below are therefore
# published as the declared contract they always were.
TAIL_CONFIDENCE_LEVEL = 0.95
TAIL_Z_MULTIPLIER = 1.645
TAIL_ES_MULTIPLIER = 2.06
#: Tail losses are published as negative returns, floored so a "loss" can
#: never round to a gain and can never reach -100 % of capital.
TAIL_CLIP_LOW = -0.99
TAIL_CLIP_HIGH = -0.001

#: Annualized-volatility clip bounds on the published `volatility_forecast`.
#: GARCH and EWMA floor at 0.05; EGARCH floors at 0.0 because its log-variance
#: recursion can drive the conditional variance below any positive floor without
#: that being an error.  These were inline literals inside each forecast method.
#: They are named now because the precision disclosure RE-FITS the same model on
#: every resample and has to clip identically: a restatement that clipped
#: differently would fail `measure_estimate_uncertainty`'s reproduction guard and
#: the band would be withheld for a reason that has nothing to do with precision.
FORECAST_VOL_CLIP_LOW = 0.05
FORECAST_VOL_CLIP_HIGH = 1.20
EGARCH_VOL_CLIP_LOW = 0.0
#: RiskMetrics (1996) single-pass decay factor.  Named for the same reason as
#: the clip bounds: the resampling restatement re-runs this exact recursion, and
#: a decay factor written twice is a drift waiting to happen.
EWMA_LAMBDA = 0.94

#: Draw count for arch's SIMULATION branch, and the seed it is drawn with.
#: Both are published on `model_params` next to every simulated forecast, and
#: named here for the reason the clip bounds are: the resampling restatement
#: re-runs this exact branch, and a simulation count or a seed written twice is
#: a drift waiting to happen.  `EGARCH_SIMULATION_SEED` is a LITERAL 100 rather
#: than `UNCERTAINTY_BOOTSTRAP_SEED` on purpose - it was already 100 before any
#: of it was read, so borrowing the bootstrap seed here would silently move a
#: published number for no reason.
#:
#: WHY THE SEED IS PUBLISHED AT ALL.  arch 8.0.0's simulation branch ignores the
#: `random_state` this module used to pass it (see the call site in
#: `volatility_forecast_point`), so the published point was one arbitrary draw
#: and two forecasts from the same fitted model already differed.  A seed that
#: is not read is a false provenance claim on the payload, which is worse than
#: publishing no seed at all.
FORECAST_SIMULATIONS = 2000
EGARCH_SIMULATION_SEED = 100

#: Why `confidence_interval` is null.  Published rather than left implicit so
#: a consumer reading the absence learns the reason instead of assuming a bug.
FORECAST_NO_INTERVAL_REASON = (
    "not computed: this forecast publishes a point estimate of conditional "
    "volatility from a fitted model and derives no sampling distribution for "
    "that estimate. The field previously carried a fixed +/-20% band around "
    "the point forecast, which is not an interval at any confidence level. "
    "It is null rather than a plausible-looking band because a band with no "
    "level, no degrees of freedom and no sampling error is worse than an "
    "explicit absence: a reader takes 'confidence interval' as a statement "
    "about estimator uncertainty and concludes the forecast is well "
    "identified."
)


# ---------------------------------------------------------------------------
# Estimator uncertainty (SI-5)
# ---------------------------------------------------------------------------
# The export publishes on the order of two thousand point estimates and, before
# this block existed, not one of them carried a standard error, an interval or
# an effective-sample-size figure.  A point estimate published with the visual
# authority of a measurement IS the defect, so every estimate now carries one
# of two things:
#
#   * a real interval, with its method, its confidence level and the n it rests
#     on, or
#   * `not_computed` (nothing was measured) / `not_applicable` (the field is a
#     threshold, not an estimate) with the reason.
#
# Nothing here invents an interval.  An interval fabricated to satisfy the rule
# is worse than the absence, because it converts a known gap into a false
# precision - which is why `measure_estimate_uncertainty` refuses to publish a
# band unless the resampling estimator reproduces the PUBLISHED point value
# first (see `point_tolerance`).
#
# METHOD: a circular moving-block bootstrap (Politis & Romano 1994), reported
# as a percentile interval.  It is the right tool for this payload for two
# reasons.  (1) Every quantity measured here is a ratio of two estimated
# quantities - Sharpe, Sortino, Calmar, Omega, beta, alpha, expected return -
# or a path statistic, and none of them has a usable closed-form standard error.
# (2) Daily equity returns are serially dependent, so the naive sqrt(n) interval
# is too narrow; an iid bootstrap would destroy exactly the dependence that
# causes the understatement.  Resampling contiguous blocks keeps the dependence
# inside a block, and `effective_n` publishes how far the naive n sits from the
# count that carries the same information about the mean.
UNCERTAINTY_CONFIDENCE_LEVEL = 0.95
UNCERTAINTY_BOOTSTRAP_RESAMPLES = 1000
#: Fixed so every interval in the export is reproducible from the payload alone.
UNCERTAINTY_BOOTSTRAP_SEED = 20260925
#: A percentile interval needs enough draws for its own 2.5 % tail to mean
#: anything.  Below this the block publishes `not_computed` plus the count.
UNCERTAINTY_MIN_OBSERVATIONS = 20
#: How far the resampling estimator's OWN point value may sit from the value
#: the payload publishes before the band is withheld.  An interval for a
#: neighbouring function is a fabricated precision, not a wider honest one.
#:
#: This is a BAND-PROVENANCE test, not a truth test.  It can only ever say "these
#: two numbers disagree"; on its own it cannot say which of them is wrong, and
#: for most of this module's history it did not try - it withheld the band and
#: published a point that might have been correct, under a reason string that
#: asserted the point was the wrong one.  `measure_estimate_uncertainty` now
#: adjudicates that disagreement against an independent witness; see
#: POINT_STATUS_VALUES.
UNCERTAINTY_POINT_TOLERANCE = 1e-6
#: Display rounding for a standard error or interval bound.  Half a 6-decimal
#: step, so a reader recomputing from the published numbers lands inside 1e-6.
UNCERTAINTY_DECIMALS = 6

#: The closed vocabulary of `estimates.<field>.point_status`: what happened to
#: the POINT VALUE, which is a different question from `status` (whether a band
#: was published).  Every value here describes a point the payload still
#: carries, except POINT_NOT_REPRODUCED_BY_ANY_WITNESS - the only branch in this
#: module that withholds a POINT rather than a band, and one no live data
#: currently reaches.
#:
#: The enumeration, because the ENUMERATION was the incomplete thing rather
#: than any one branch.  A point on a live `point_status` reached a
#: `measure_estimate_uncertainty` block by one of six routes, and five had a
#: word and the sixth did not:
#:
#:   estimator ran, reproduced the point to tolerance -> REPRODUCED_BY_ESTIMATOR
#:   estimator ran, a second path also reproduced it    -> VERIFIED_BY_WITNESS
#:   estimator ran, witness reproduced it, ESTIMATOR did not
#:                                                      -> REPRODUCED_BY_WITNESS_ONLY
#:   estimator ran, witness also missed it              -> NOT_REPRODUCED_BY_ANY_WITNESS
#:   estimator ran, witness could not deliver a verdict -> UNVERIFIED
#:   estimator NEVER INVOKED - declined, reason published -> ESTIMATOR_DECLINED
#:
#: The sixth row is why ESTIMATOR_DECLINED exists.  `unverified` means "a check
#: was attempted and could not conclude", which is the false-positive-safe
#: default on a point the guard was actually asked about.  A declined estimator
#: is not that: nobody asked the guard anything, the resampler was never
#: called, `bootstrap_resamples` reads 0 and the reason is published on the
#: block.  Publishing it as `unverified` made a deliberate, costed, disclosed
#: refusal indistinguishable from a check that ran and failed - and it made a
#: declined leg read as a more-uncertain one than a measured leg on the same
#: payload, which is the opposite of what happened.  Five of the six values
#: describe what a DERIVATION did to the point; this one is named for the actor
#: that did not act, and the reason it did not act stays in `reason` and
#: `estimator_withheld` rather than in the label, because the label cannot know
#: the reason - a caller may decline for cost today and for a licence tomorrow,
#: and baking today's reason into a status word would be a claim about the
#: future.
POINT_REPRODUCED_BY_ESTIMATOR = "reproduced_by_estimator"
POINT_VERIFIED_BY_WITNESS = "verified_against_independent_witness"
POINT_REPRODUCED_BY_WITNESS_ONLY = (
    "published_point_reproduced_by_independent_witness"
)
POINT_NOT_REPRODUCED_BY_ANY_WITNESS = (
    "published_point_not_reproduced_by_independent_witness"
)
POINT_UNVERIFIED = "unverified"
#: Named for the ACTOR and the fact it did not act, in the same grammar as
#: `reproduced_by_estimator`, which is also actor-named.  Rejected alternatives:
#: `estimator_withheld` (already the name of a different key on the block, and
#: that key is a reason STRING - two vocabularies sharing a word is a hazard a
#: consumer switches on by accident), `estimator_not_invoked` (mechanism, and it
#: drops the "deliberate, with a published reason" half that is the entire
#: point of distinguishing the case), `declined_by_cost` (a fact about today's
#: caller, not about the state, and a lie the day the reason changes).
POINT_ESTIMATOR_DECLINED = "estimator_declined"
POINT_STATUS_VALUES = frozenset({
    POINT_REPRODUCED_BY_ESTIMATOR,
    POINT_VERIFIED_BY_WITNESS,
    POINT_REPRODUCED_BY_WITNESS_ONLY,
    POINT_NOT_REPRODUCED_BY_ANY_WITNESS,
    POINT_UNVERIFIED,
    POINT_ESTIMATOR_DECLINED,
})

BOOTSTRAP_METHOD = "circular_moving_block_bootstrap_percentile"
BOOTSTRAP_METHOD_BASIS = (
    "Circular moving-block bootstrap (Politis & Romano 1994) of the measured "
    "return series, reported as a percentile interval at the stated level. "
    "Contiguous blocks are resampled rather than individual observations "
    "because daily equity returns are serially dependent: an iid bootstrap "
    "would destroy the dependence that makes the naive sqrt(n) interval too "
    "narrow. The standard error is the sample standard deviation (ddof=1) of "
    "the resampled statistic."
)
BOOTSTRAP_RESAMPLING_BASIS = (
    "For each draw, ceil(n / block_size) start offsets are drawn uniformly from "
    "0..n-1 and concatenated circularly, then truncated to n. Indices wrap "
    "modulo n, so every observation enters every resample and none is dropped."
)


def ar1_autocorrelation(values: Any) -> Optional[float]:
    """Sample AR(1) coefficient: OLS slope of r_t on r_(t-1).

    ``None`` when too few lagged pairs survive to fit a slope.  An absence, not
    0.0 - a "no autocorrelation" claim is itself an estimate.
    """
    series = np.asarray(values, dtype=float).ravel()
    if series.size < 5:
        return None
    left, right = series[1:], series[:-1]
    mask = np.isfinite(left) & np.isfinite(right)
    if int(mask.sum()) < 3:
        return None
    left, right = left[mask], right[mask]
    denominator = float(np.sum((right - right.mean()) ** 2))
    if denominator <= 0.0 or not np.isfinite(denominator):
        return None
    rho = float(np.sum((right - right.mean()) * (left - left.mean())) / denominator)
    return rho if np.isfinite(rho) else None


def effective_sample_size(
    observations: Optional[int], ar1: Optional[float]
) -> Optional[float]:
    """Quenouille/Bartlett AR(1) variance-inflation adjustment of the mean.

    ``n_eff = n * (1 - rho) / (1 + rho)`` is the count of iid observations that
    carries the same information about the sample mean as these ``n``
    autocorrelated ones.  With ``rho > 0`` it is below ``n``, which is the
    entire point: autocorrelated daily returns are not independent daily
    returns, and pretending otherwise understates every interval in this
    payload.
    """
    if observations is None or int(observations) <= 0 or ar1 is None:
        return None
    rho = float(ar1)
    if not np.isfinite(rho) or rho <= -1.0 or rho >= 1.0:
        return None
    return float(int(observations)) * (1.0 - rho) / (1.0 + rho)


#: The PUBLISHED precision of both numbers on an `autocorrelation_disclosure`
#: block, declared rather than left implicit in a `round()` call.
#:
#: This was a real and separate defect, not a style one.  `ar1` was published
#: rounded to 6 decimals and `effective_n` rounded to 4, but `effective_n` was
#: COMPUTED from the unrounded `ar1`.  The block publishes the formula
#: `n * (1 - ar1) / (1 + ar1)` next to both figures, so a reader who does what the
#: payload invites - substitute the published `ar1` and the published `n` - gets
#: a different `effective_n` than the one printed.  On the v26 book that
#: happened on 19 of the 40 blocks carrying all three numbers, worst at
#: `positions.MOTILALOFS.NS` (n = 173, ar1 = -0.090892, published
#: effective_n 207.5926) where recomputation gives 207.5928449.
#:
#: WHY A SHARED DECIMAL COUNT IS NOT THE FIX, stated because it looks like the
#: fix and is not.  Rounding `ar1` to `d` decimals moves `effective_n` by at
#: most `2n / (1 + ar1)^2 * 0.5 * 10^-d`.  For n = 173 and ar1 = -0.09 that is
#: 385 * 0.5 * 10^-d, and the half-ulp of a 4-decimal `effective_n` is 5e-5, so
#: agreement to the last published place would need `d >= 8` - on a book of
#: several hundred names, `d >= 10`.  Publishing noise digits to make a formula
#: line up is the wrong trade, and moving `effective_n` to match the published
#: `ar1` would move a published number to flatter a formula.
#:
#: So the DECLARATION is the fix: both precisions are published, and the block
#: publishes the agreement it actually has, as a bound a reader can recompute
#: from `n`, `ar1` and the two declared decimals.  See
#: `effective_n_reproducibility_bound`.
AUTOCORRELATION_AR1_DECIMALS = UNCERTAINTY_DECIMALS
AUTOCORRELATION_EFFECTIVE_N_DECIMALS = 4

AUTOCORRELATION_EFFECTIVE_N_REPRODUCIBILITY_BASIS = (
    "effective_n is computed from the UNROUNDED ar1 and ar1 is published "
    "rounded, so substituting the published ar1 and the published n into the "
    "published formula does not return the published effective_n exactly. The "
    "difference is bounded by the half-ulp of effective_n's own last published "
    "place plus the ar1 rounding amplified through the formula's sensitivity "
    "d/dar1 = -2n / (1 + ar1)^2, which is the recomputation_deviation_bound "
    "published here. That bound is a statement about the rounding, not an "
    "error: neither figure was moved to make the other agree, and a reader who "
    "recomputes from the published inputs will land inside the bound rather than "
    "on the last digit"
)


def effective_n_reproducibility_bound(
    observations: Optional[int], published_ar1: Optional[float]
) -> Optional[float]:
    """The worst-case disagreement between the published figure and a recomputation.

    Computed from PUBLISHED inputs only - ``n``, the rounded ``ar1`` and the two
    declared decimal counts - so a reader can reproduce the bound itself rather
    than take it on trust.

    ``effective_n = f(n, ar1)`` is smooth with ``f'(rho) = -2n / (1 + rho)^2``, so
    by the mean value theorem the error from a half-step of `ar1` rounding is at
    most ``|f'| * half_step``, evaluated where ``|f'|`` is largest - at the small
    ``1 + rho`` end of the rounding interval.  Added to that is the half-ulp of
    `effective_n`'s own rounding.  The two terms are the whole story.
    """
    if observations is None or published_ar1 is None:
        return None
    count = int(observations)
    rho = float(published_ar1)
    if count <= 0 or not np.isfinite(rho):
        return None
    ar1_half_step = 0.5 * 10.0 ** (-AUTOCORRELATION_AR1_DECIMALS)
    effective_half_step = 0.5 * 10.0 ** (-AUTOCORRELATION_EFFECTIVE_N_DECIMALS)
    # The worst `|f'|` sits at the smallest `1 + rho` the rounding interval can
    # reach.  Clamped at the stationary boundary, where `f` is not defined.
    worst_rho = max(rho - ar1_half_step, -1.0 + 1e-9)
    amplification = 2.0 * count / (1.0 + worst_rho) ** 2
    return float(effective_half_step + amplification * ar1_half_step)


def autocorrelation_disclosure(observations: Any) -> Dict[str, Any]:
    """`ar1` / `effective_n` for a block, or the reason neither exists."""
    values = np.asarray(observations, dtype=float)
    series = values[:, 0] if values.ndim == 2 else values
    count = int(series.size)
    ar1 = ar1_autocorrelation(series)
    effective = effective_sample_size(count, ar1)
    computed = ar1 is not None and effective is not None
    published_ar1 = (
        round(ar1, AUTOCORRELATION_AR1_DECIMALS) if ar1 is not None else None
    )
    published_effective = (
        round(effective, AUTOCORRELATION_EFFECTIVE_N_DECIMALS)
        if effective is not None else None
    )
    # Recomputed from the PUBLISHED inputs, exactly as a reader would, so the
    # agreement this block claims is measured rather than asserted.
    recomputed = effective_sample_size(count, published_ar1)
    deviation = (
        abs(recomputed - published_effective)
        if recomputed is not None and published_effective is not None
        else None
    )
    bound = effective_n_reproducibility_bound(count, published_ar1)
    return {
        "ar1": published_ar1,
        "ar1_decimals": AUTOCORRELATION_AR1_DECIMALS,
        "ar1_basis": "OLS slope of r_t on r_(t-1) over the measured window",
        "effective_n": published_effective,
        "effective_n_decimals": AUTOCORRELATION_EFFECTIVE_N_DECIMALS,
        "effective_n_formula": "n * (1 - ar1) / (1 + ar1)",
        "effective_n_basis": (
            "Quenouille/Bartlett AR(1) variance-inflation adjustment applied to "
            "the sample mean. It is the count of independent observations that "
            "carries the same information about the mean as the measured n; "
            "below n whenever the returns are positively autocorrelated."
        ),
        "effective_n_reproducibility": {
            "recomputes_from_published_ar1": (
                None if deviation is None else bool(deviation == 0.0)
            ),
            "recomputation_deviation": deviation,
            "recomputation_deviation_bound": bound,
            "bound_basis": (
                AUTOCORRELATION_EFFECTIVE_N_REPRODUCIBILITY_BASIS
                if computed
                else None
            ),
        },
        "observations": count,
        "naive_n_would_assume": "independent observations, which the measured "
        "AR(1) does not support",
        "status": "computed" if computed else "not_computed",
        "reason": None if computed else (
            "the measured window is too short, or has too little variation in "
            "the lagged series, to fit an AR(1) slope; the effective sample "
            "size is therefore not published rather than assumed to equal n"
        ),
    }


def moving_block_size(observations: int) -> int:
    """Politis & White (2004) rule of thumb: ``n ** (1/3)`` trading days."""
    count = int(observations)
    if count <= 0:
        return 1
    return max(1, int(round(float(count) ** (1.0 / 3.0))))


def moving_block_indices(
    observations: int,
    block_size: int,
    resamples: int,
    seed: int,
) -> np.ndarray:
    """``(resamples, n)`` index matrix of circular, contiguous blocks.

    Published with the interval via `bootstrap_resamples` / `resample_seed` /
    `block_size`, so the exact draws behind a published band can be regenerated.
    """
    count = max(1, int(observations))
    length = max(1, min(int(block_size), count))
    draws = max(1, int(resamples))
    starts_count = int(np.ceil(count / length))
    rng = np.random.default_rng(int(seed))
    starts = rng.integers(0, count, size=(draws, starts_count))
    offsets = np.arange(length)
    indices = (starts[:, :, None] + offsets[None, None, :]) % count
    return indices.reshape(draws, starts_count * length)[:, :count]


def _percentile_interval(
    draws: np.ndarray, level: float
) -> Optional[List[float]]:
    """Percentile interval at `level`, or None when too few draws are finite."""
    values = np.asarray(draws, dtype=float).ravel()
    finite = values[np.isfinite(values)]
    if finite.size < 30:
        return None
    alpha = 1.0 - float(level)
    low, high = np.percentile(finite, [50.0 * alpha, 50.0 * (2.0 - alpha)])
    return [float(low), float(high)]


def _finite_observation_block(
    observations: Any, row_filter: Optional[Any] = None
) -> Tuple[np.ndarray, int]:
    """``(n, k)`` float block with unusable rows dropped, plus the drop count.

    The default filter is COMPLETE CASE: a row survives only if every column is
    finite, which is the right reading for any statistic that is a function of
    the columns jointly.  It is the WRONG reading for a statistic that is
    itself pairwise - a mean of pairwise Pearson correlations, for instance, is
    exactly what pandas' pairwise-complete `.corr()` measures, and dropping the
    rows a leg was unpriced on would measure the mean over the complete-case
    subset instead, i.e. a different number that the reproduction guard would
    (correctly) refuse.  `row_filter` lets such a caller say which rows ITS
    statistic is defined on; it must return a boolean mask over rows.  A filter
    of the wrong length refuses the whole block rather than guessing.
    """
    raw = np.asarray(observations, dtype=float)
    if raw.ndim == 1:
        raw = raw.reshape(-1, 1)
    elif raw.ndim != 2:
        return np.zeros((0, 0), dtype=float), 0
    if row_filter is None:
        keep = np.isfinite(raw).all(axis=1)
    else:
        try:
            keep = np.asarray(row_filter(raw), dtype=bool).ravel()
        except Exception as exc:  # noqa: BLE001 - degrade, never guess
            return np.zeros((0, 0), dtype=float), 0, str(exc)
        if keep.shape[0] != raw.shape[0]:
            return np.zeros((0, 0), dtype=float), 0, (
                "the caller's row filter returned "
                f"{keep.shape[0]} mask(s) for a {raw.shape[0]}-row frame"
            )
    return raw[keep], int(raw.shape[0] - int(keep.sum())), None


def _uncertainty_entry(
    field: str,
    *,
    point: Optional[float],
    status: str,
    reason: Optional[str],
    observations: Optional[int],
    effective_n: Optional[float],
    point_status: str,
    standard_error: Optional[float] = None,
    conf_int: Optional[List[float]] = None,
    method: Optional[str] = None,
    method_basis: Optional[str] = None,
) -> Dict[str, Any]:
    """One field's precision disclosure.

    `conf_int` is ALWAYS present, `None` when there is no interval: a payload
    that simply omits the key leaves a consumer unable to tell "no interval was
    computed" from "this field has no uncertainty", which is the ambiguity this
    whole block exists to remove.

    `point_status` is required rather than defaulted, because the guard that
    decides it is the one place in this module that can silently become
    one-sided. It says what was done to the POINT, which `status` does not: a
    field can be `not_computed` (no band) and still carry a fully believed point
    value, and before this key existed nothing in the payload separated "this
    number is settled" from "this number survived because withholding it was
    the safer default". The vocabulary is closed and is asserted by
    `POINT_STATUS_VALUES`.

    `point_within_conf_int` is published because a percentile bootstrap does NOT
    guarantee the observed value lies inside its own interval. It does not, for
    a statistic whose denominator is a non-smooth functional - a maximum
    drawdown, an order statistic - because the resampling distribution of such
    a ratio is shifted relative to the observed one. A band that silently
    excludes the number printed beside it is exactly the kind of thing a reader
    cannot check, so the fact is stated rather than smoothed over.
    """
    inside: Optional[bool] = None
    if conf_int is not None and point is not None:
        inside = bool(float(conf_int[0]) <= float(point) <= float(conf_int[1]))
    entry = {
        "point": point,
        "standard_error": standard_error,
        "conf_int": conf_int,
        "conf_int_level": (
            UNCERTAINTY_CONFIDENCE_LEVEL if conf_int is not None else None
        ),
        "conf_int_method": method if conf_int is not None else None,
        "conf_int_basis": method_basis if conf_int is not None else None,
        "point_within_conf_int": inside,
        "point_within_conf_int_note": (
            None
            if inside is not False
            else (
                "the observed point value lies outside its own percentile "
                "interval. That is a real property of a percentile bootstrap on "
                "a statistic whose denominator is a non-smooth functional (a "
                "maximum drawdown, an order statistic) or whose resampling "
                "distribution is shifted relative to the observed one. It is "
                "published rather than hidden: read the interval as the spread "
                "of the resampled statistic, not as a guarantee of coverage."
            )
        ),
        "observations": observations,
        "effective_n": effective_n,
        "point_status": point_status,
        "status": status,
        "reason": reason,
    }
    return entry


def _statistic_matrix_from(statistics: Any) -> Any:
    """Accept either a callable or a `{field: callable}` mapping.

    The factories above return the mapping form because it is what a caller
    wants to read; `measure_estimate_uncertainty` wants the callable form
    because it evaluates the whole set on every resample. Accepting both keeps
    the call sites free of adapter noise.
    """
    if isinstance(statistics, Mapping):
        def _evaluate(block: Any) -> Dict[str, Any]:
            return {name: fn(block) for name, fn in statistics.items()}

        return _evaluate
    return statistics


def _witness_verdicts(
    witness: Any,
    witness_observations: Any,
    source_field: Mapping[str, str],
) -> Tuple[Dict[str, Optional[float]], Optional[str], Optional[Tuple[int, int]]]:
    """The independent re-derivations, keyed by PUBLISHED field name.

    Returns ``(verdicts, failure, shape)``.  `verdicts[field]` is a finite float
    the witness derived for that published field, or ``None`` when it produced
    nothing usable.  `failure` is a single human-readable string explaining why
    the witness could not run at all, and it is deliberately a FAILURE rather
    than a verdict: a witness that could not be evaluated leaves the published
    point RETAINED and flagged `unverified`, because the cost of a bad witness
    must never be a correct number removed.  `shape` is the witness frame's
    ``(rows, columns)``, published so a reader can see that the two sides of
    the adjudication were measured on different frames.

    The witness is evaluated with a single column - one evaluation of the
    caller's callable over ``(n, 1, k)`` - so it re-derives a point value and
    never a resampling distribution.  Keys are read through `source_field` so a
    caller may key the witness by either the published name (`beta_vs_nifty`)
    or the source name (`beta`), which is the same aliasing `statistic_names`
    already does for `statistics`.
    """
    if witness is None:
        return {}, "no independent witness was supplied for this block", None
    published_by_source = {source: field for field, source in source_field.items()}
    try:
        evaluate = _statistic_matrix_from(witness)
        values, _, _ = _finite_observation_block(witness_observations)
    except Exception as exc:  # noqa: BLE001 - degrade, never guess
        return {}, (
            "the independent witness could not be prepared on the published "
            f"sample ({type(exc).__name__}: {exc})"
        ), None
    count = int(values.shape[0])
    shape = (count, int(values.shape[1]))
    if count == 0:
        return {}, (
            "the independent witness was handed no finite observation of the "
            "published sample"
        ), shape
    try:
        raw = evaluate(values[:, None, :])
        if not isinstance(raw, Mapping):
            raw = {"": raw}
    except Exception as exc:  # noqa: BLE001 - degrade, never guess
        return {}, (
            "the independent witness raised while re-deriving the published "
            f"point value ({type(exc).__name__}: {exc})"
        ), shape
    verdicts: Dict[str, Optional[float]] = {}
    for key, value in raw.items():
        field = source_field.get(str(key), published_by_source.get(str(key)))
        if field is None:
            continue
        try:
            verdicts[field] = _scalar_or_none(value)
        except Exception:  # noqa: BLE001 - an unusable witness is a failure
            verdicts[field] = None
    return verdicts, None, shape


def measure_estimate_uncertainty(
    observations: Any,
    statistics: Any,
    published: Mapping[str, Any],
    *,
    scope: str,
    point_tolerance: float = UNCERTAINTY_POINT_TOLERANCE,
    level: float = UNCERTAINTY_CONFIDENCE_LEVEL,
    resamples: int = UNCERTAINTY_BOOTSTRAP_RESAMPLES,
    seed: int = UNCERTAINTY_BOOTSTRAP_SEED,
    not_computed: Optional[Mapping[str, str]] = None,
    not_applicable: Optional[Mapping[str, str]] = None,
    statistic_names: Optional[Mapping[str, str]] = None,
    witness: Any = None,
    witness_observations: Any = None,
    witness_tolerance: Optional[float] = None,
    witness_basis: Optional[str] = None,
    row_filter: Optional[Any] = None,
    row_filter_basis: Optional[str] = None,
    estimator_withheld: Optional[str] = None,
    notes: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Precision disclosure for one block of published estimates.

    `observations` is the measured sample, shape ``(n,)`` or ``(n, k)``.
    `statistics` is either a `{field: callable}` mapping or a single callable;
    it is invoked as ``statistics(block)`` with ``block`` of shape
    ``(n, draws, k)`` and must return ``{field: array of shape (draws,)}`` -
    the same statistic, computed on each resample.  `published` maps every
    field this block is responsible for to the value the payload publishes, and
    EVERY key in it appears in the result, whatever happens next.

    Rows are measured COMPLETE CASE by default (every column finite).  A
    statistic that is itself PAIRWISE is defined on a different population, and
    `row_filter` + `row_filter_basis` let such a caller name the rows its own
    point value was measured on; both are published on the block.

    The safety property that makes the whole thing trustworthy: the estimator
    is also run on the ORIGINAL sample, and a field's interval is published
    only if that own point value reproduces the published one to within
    `point_tolerance`.  A statistic that quietly measures something else gets
    `not_computed` with the discrepancy in the reason, instead of lending the
    published number a band that was never its own.

    ADJUDICATION.  That test compares two numbers, so on its own it cannot say
    WHICH of them is wrong - and for a long time it did not try.  It withheld
    the band, kept the point, and wrote a reason that read as an accusation
    against the point, so a payload could sit there publishing a number nobody
    had checked next to a sentence saying that number was wrong.  In the live
    case that deleted nothing but mislabelled everything: the published
    `beta_vs_nifty` was correct and the ESTIMATOR was the side that had been
    handed a mis-aligned frame.

    `witness` closes that.  It is a SECOND derivation of `published` by a
    genuinely different code path - for beta and alpha that is `np.linalg.lstsq`
    on the design matrix, against the estimator's `cov(p, b) / var(b)` closed
    form - and it is evaluated on `witness_observations`, which is the frame
    the PUBLISHED value was measured on, not necessarily the frame the
    estimator was handed.  When the estimator's own point value misses the
    published one, the witness is the third number that decides which side is
    lying.

    `witness_observations` defaults to `observations`.  That default is the
    trap this design exists to avoid: a witness run over a mis-aligned frame
    agrees with the mis-aligned ESTIMATOR, not with the published point, and
    would take the withholding branch and delete a correct number.  So a caller
    whose published value came from a differently-aligned frame must pass that
    frame here explicitly.  The witness is evaluated with a single column
    (one evaluation, never resampled) - it re-derives a point, it does not
    produce a distribution.

    `estimator_withheld` is for the case where the ESTIMATOR ITSELF is too
    expensive to run - a GARCH(1,1) refit is a full optimiser run, so a
    per-leg re-fit bootstrap costs a book's worth of them.  The reason is
    published on every field and on the block, `bootstrap_resamples` reads 0,
    the resampler is never called, and the point is retained with
    ``point_status = estimator_declined`` - the sixth route in the enumeration
    at POINT_STATUS_VALUES.  It is its own word and not `unverified`, because
    `unverified` is what a guard that WAS asked and could not conclude
    publishes; here nobody asked, and conflating the two makes a declined leg
    read as a less-trusted one than a measured leg carrying the same
    `unverified` on the same payload.  It is a
    parameter rather than a hand-built second copy of this function's output
    shape precisely so the unmeasured block cannot drift away from the measured
    one: a withheld disclosure with a different set of keys would be the reason
    a consumer's reader broke on the fields that were kept.  The alternative to
    withholding - narrowing the draw count until the block fits - is only
    correct while the remaining tail still means something, and below this
    module's floor it does not.

    THE ASYMMETRY IS DELIBERATE.  On a witness that cannot be run - it raises,
    it returns a non-finite value, it is absent, it is handed no finite
    observation - the point is RETAINED and flagged `unverified`.  It is never
    nulled.  A wrong witness must never cost a reader a correct number, because
    the failure mode being fixed here is publishing a number nobody checked,
    and a fix that traded it for hiding a number that was right would have
    replaced one defect with a worse one.  `point: null` is reachable only when
    the witness runs, produces a finite verdict, and that verdict also misses
    the published value - two independent derivations contradicting the payload,
    which is the one case where withholding is the honest answer.
    """
    values, dropped, filter_failure = _finite_observation_block(
        observations, row_filter
    )
    evaluate = _statistic_matrix_from(statistics)
    count = int(values.shape[0])
    width = int(values.shape[1])
    autocorrelation = (
        autocorrelation_disclosure(values)
        if count
        else {
            # Same shape as the computed branch, so a consumer reads one block.
            # The two DECLARED keys are the convention itself and are published
            # even with nothing to apply them to: the precision a figure would
            # be published at is a property of the convention, not of the data.
            "ar1": None,
            "ar1_decimals": AUTOCORRELATION_AR1_DECIMALS,
            "ar1_basis": "OLS slope of r_t on r_(t-1) over the measured window",
            "effective_n": None,
            "effective_n_decimals": AUTOCORRELATION_EFFECTIVE_N_DECIMALS,
            "effective_n_formula": "n * (1 - ar1) / (1 + ar1)",
            "effective_n_basis": None,
            "effective_n_reproducibility": {
                "recomputes_from_published_ar1": None,
                "recomputation_deviation": None,
                "recomputation_deviation_bound": None,
                "bound_basis": None,
            },
            "observations": 0,
            "naive_n_would_assume": None,
            "status": "not_computed",
            "reason": filter_failure or (
                "no finite observation was measured for this block"
            ),
        }
    )
    effective_n = autocorrelation.get("effective_n")
    block_length = moving_block_size(count)

    draws: Dict[str, np.ndarray] = {}
    own_point: Dict[str, Optional[float]] = {}
    blocked_reason: Optional[str] = None
    if estimator_withheld is not None:
        # Declared before any work is done, not after a timeout or a failure.
        # The caller is not reporting that the estimator broke; it is reporting
        # that running it was a decision it could not afford, and the estimator
        # never runs at all.
        blocked_reason = estimator_withheld
    elif count >= UNCERTAINTY_MIN_OBSERVATIONS:
        try:
            indices = moving_block_indices(count, block_length, resamples, seed)
            # (draws, n, k) -> (n, draws, k): time axis first, one draw per column.
            sample = values[indices]
            draws = {
                field: np.asarray(value, dtype=float).ravel()
                for field, value in evaluate(np.swapaxes(sample, 0, 1)).items()
            }
            own_point = {
                field: _scalar_or_none(value)
                for field, value in evaluate(values[:, None, :]).items()
            }
        except Exception as exc:  # noqa: BLE001 - degrade, never guess
            blocked_reason = (
                "the resampling estimator could not be evaluated on this sample "
                f"({type(exc).__name__}: {exc})"
            )
            draws, own_point = {}, {}
    elif count == 0:
        blocked_reason = filter_failure or (
            "no finite observation was measured for this block"
        )
    else:
        blocked_reason = (
            f"{count} measured observation(s) is below the "
            f"{UNCERTAINTY_MIN_OBSERVATIONS} a percentile interval needs before "
            "its own 2.5 % tail carries any information"
        )

    declared_not_computed = dict(not_computed or {})
    declared_not_applicable = dict(not_applicable or {})
    #: published field -> key in the statistics mapping. Identity when absent;
    #: it exists because one payload field (`benchmark_sharpe`) is one
    #: estimator (`sharpe`) under a section-specific name.
    source_field = {field: (statistic_names or {}).get(field, field) for field in published}
    witness_point, witness_failure, witness_shape = _witness_verdicts(
        witness, witness_observations, source_field
    )
    #: How close the witness's own verdict must sit to the published value for
    #: the witness to be treated as corroborating it.  Defaults to the same
    #: tolerance the estimator is held to, because a witness that only agrees
    #: to a looser tolerance is not corroborating anything.
    witness_limit = (
        float(point_tolerance)
        if witness_tolerance is None
        else float(witness_tolerance)
    )
    estimates: Dict[str, Any] = {}
    for field, published_value in published.items():
        point = (
            float(published_value)
            if isinstance(published_value, (int, float))
            and not isinstance(published_value, bool)
            and np.isfinite(float(published_value))
            else None
        )
        if field in declared_not_applicable:
            estimates[field] = _uncertainty_entry(
                field, point=point, status="not_applicable",
                reason=declared_not_applicable[field], observations=count or None,
                effective_n=effective_n,
                point_status=POINT_UNVERIFIED,
            )
            continue
        if field in declared_not_computed:
            estimates[field] = _uncertainty_entry(
                field, point=point, status="not_computed",
                reason=declared_not_computed[field], observations=count or None,
                effective_n=effective_n,
                point_status=POINT_UNVERIFIED,
            )
            continue
        if estimator_withheld is not None:
            # A field-specific `not_computed` above is the caller naming a
            # reason about THIS field; this is the caller saying the estimator
            # was not run at all.  `effective_n` is still real and still
            # published: it is measured from the sample, costs nothing, and is
            # the part of this leg's precision that IS known.
            #
            # `estimator_declined`, NOT `unverified`.  `unverified` is the
            # false-positive-safe default of a guard that WAS asked and could
            # not conclude; here nobody asked, the resampler was never called,
            # and the refusal is published.  Labelling a deliberate refusal as
            # an inconclusive check is the one move this block must not make:
            # it makes a declined leg read as a less-trusted one than a
            # measured leg on the same payload.  The point is retained either
            # way, which is what makes this safe to publish - the new word
            # costs the reader no number.
            estimates[field] = _uncertainty_entry(
                field, point=point, status="not_computed",
                reason=estimator_withheld, observations=count or None,
                effective_n=effective_n,
                point_status=POINT_ESTIMATOR_DECLINED,
            )
            continue
        if point is None:
            estimates[field] = _uncertainty_entry(
                field, point=None, status="not_computed",
                reason=(
                    "the point estimate itself is withheld (below the "
                    "annualization gate, or unmeasurable on this window), so "
                    "there is no number to put an interval around"
                ),
                observations=count or None, effective_n=effective_n,
                point_status=POINT_UNVERIFIED,
            )
            continue
        source = source_field[field]
        distribution = draws.get(source)
        reproduced = own_point.get(source)
        if distribution is None or reproduced is None or not np.isfinite(reproduced):
            if draws and source not in draws:
                missing_reason = (
                    f"no resampling estimator is registered for {field} (looked "
                    f"for '{source}' among {sorted(draws)}), so no interval can "
                    "belong to it"
                )
            else:
                missing_reason = (
                    f"the resampling estimator produces no finite value for "
                    f"{field} on this sample"
                )
            estimates[field] = _uncertainty_entry(
                field, point=point, status="not_computed",
                reason=blocked_reason or missing_reason,
                observations=count or None, effective_n=effective_n,
                point_status=POINT_UNVERIFIED,
            )
            continue
        difference = abs(float(reproduced) - point)
        if difference > float(point_tolerance):
            estimates[field] = _adjudicated_entry(
                field,
                point=point,
                reproduced=float(reproduced),
                difference=float(difference),
                point_tolerance=float(point_tolerance),
                witness_tolerance=witness_limit,
                witness_verdict=witness_point.get(field),
                witness_failure=witness_failure,
                observations=count,
                effective_n=effective_n,
            )
            continue
        interval = _percentile_interval(distribution, level)
        if interval is None:
            finite = int(np.isfinite(distribution).sum())
            estimates[field] = _uncertainty_entry(
                field, point=point, status="not_computed",
                reason=(
                    f"only {finite} of {int(resamples)} resamples produced a "
                    "finite value, too few for a percentile interval"
                ),
                observations=count, effective_n=effective_n,
                point_status=(
                    POINT_VERIFIED_BY_WITNESS
                    if witness_point.get(field) is not None
                    else POINT_REPRODUCED_BY_ESTIMATOR
                ),
            )
            continue
        finite = distribution[np.isfinite(distribution)]
        standard_error = float(finite.std(ddof=1)) if finite.size > 1 else None
        estimates[field] = _uncertainty_entry(
            field, point=point, status="computed", reason=None,
            observations=count, effective_n=effective_n,
            point_status=(
                POINT_VERIFIED_BY_WITNESS
                if witness_point.get(field) is not None
                else POINT_REPRODUCED_BY_ESTIMATOR
            ),
            standard_error=(
                None if standard_error is None
                else round(standard_error, UNCERTAINTY_DECIMALS)
            ),
            conf_int=[round(bound, UNCERTAINTY_DECIMALS) for bound in interval],
            method=BOOTSTRAP_METHOD,
            method_basis=(
                f"percentile interval at level {level:g} over "
                f"{int(resamples)} circular moving-block resamples of block "
                f"length {block_length}, drawn from the {count} measured "
                f"observations (effective_n {effective_n})"
            ),
        )

    with_interval = sorted(
        field for field, entry in estimates.items() if entry["status"] == "computed"
    )
    #: True when the caller declined to run the estimator at all, as opposed to
    #: the estimator running and declining to produce a band.  The two are
    #: published differently because they are different facts, and a reader who
    #: cannot tell them apart has to assume the worse one.
    withheld = estimator_withheld is not None
    block: Dict[str, Any] = {
        "scope": scope,
        "status": "computed" if with_interval else "not_computed",
        "reason": None if with_interval else (
            "no field in this block carries a resampling interval; each field "
            "states its own reason under estimates.<field>.reason"
        ),
        "method": (None if (withheld or not with_interval) else BOOTSTRAP_METHOD),
        "method_basis": (None if withheld else BOOTSTRAP_METHOD_BASIS),
        "confidence_level": (None if withheld else level),
        "observations": count,
        "observation_columns": width,
        "observation_filter": (
            "caller_supplied_row_filter" if row_filter is not None
            else "complete_case_all_columns_finite"
        ),
        "observation_filter_basis": row_filter_basis or (
            "complete case: a row is measured only when every column is finite, "
            "which is the right reading for a statistic that is a function of the "
            "columns jointly. A pairwise statistic (a mean of pairwise Pearson "
            "correlations) is defined on a different population - the rows on "
            "which the PAIR is finite - and a caller with one passes row_filter "
            "so the band is measured on the sample its point value was measured "
            "on."
        ),
        "dropped_non_finite_observations": dropped,
        "block_size": block_length,
        "block_size_basis": "Politis & White (2004) rule of thumb n ** (1/3) "
        "trading days",
        "bootstrap_resamples": 0 if withheld else int(resamples),
        "resample_seed": int(seed),
        "resampling_basis": (None if withheld else BOOTSTRAP_RESAMPLING_BASIS),
        # Only meaningful when the estimator ran.  Publishing the tolerance on a
        # block where no reproduction test happened would imply a check that was
        # never made, and `estimator_withheld` is the key that says so instead.
        "point_tolerance": (
            None if withheld else float(point_tolerance)
        ),
        # These two explain what a RUNNING estimator does.  A withheld block ran
        # none, so publishing their prose would describe a check that never
        # happened; the keys stay (the shape is identical either way) and the
        # values go, which is the same rule as method / point_tolerance above.
        "band_provenance_tolerance_basis": (
            None if withheld else (
                "a BAND-PROVENANCE test, not a truth test. An interval is published "
                "only after the resampling estimator's own point value reproduces "
                "the published value to within this tolerance, which is what makes "
                "the band belong to the statistic the reader can see. It says "
                "nothing about whether either number is CORRECT: on its own the "
                "test cannot tell which of the two is wrong. A disagreement is "
                "adjudicated against an independent witness - see "
                "estimates.<field>.point_status, which states which side failed, "
                "and witness_status / witness_tolerance on this block."
            )
        ),
        "estimator_withheld": estimator_withheld,
        "estimator_withheld_basis": (
            "set when the caller declared the resampling estimator too expensive "
            "to run, so the estimator was never called rather than having run and "
            "produced nothing. bootstrap_resamples reads 0 and the point is "
            "retained with point_status estimator_declined, because no "
            "re-derivation checked it. That is a different sentence from the "
            "point_status unverified a field gets when a witness WAS asked and "
            "could not deliver a verdict: nothing was asked here, so publishing "
            "an inconclusive check would misreport a deliberate, disclosed "
            "refusal as a doubtful measurement. The alternative to withholding "
            "- narrowing the draw count until the block fits - is only honest "
            "while the remaining tail of the percentile interval still means "
            "something, and below this module's floor it does not"
            if withheld else None
        ),
        "witness_tolerance": witness_limit,
        "witness_status": (
            "witness_ran" if witness_failure is None and witness else
            "not_supplied" if witness is None else "witness_failed"
        ),
        "witness_status_basis": (
            None if withheld else (
                "an independent second derivation of the published point value, by "
                "a different code path over the sample the point was published "
                "from, used ONLY to decide which side of a failed reproduction test "
                "is wrong. It never produces an interval: the band still comes from "
                "the resampling estimator, and it is withheld whenever the "
                "estimator's own point value misses the published one."
                + (
                    f" The witness was evaluated over {witness_shape[0]} finite "
                    f"observation(s) and {witness_shape[1]} column(s) - the sample "
                    "the PUBLISHED value was measured on, which is not necessarily "
                    "the frame the resampling estimator was handed "
                    f"({count} observation(s), {width} column(s), published above as "
                    "observation_columns). A witness run over a mis-aligned frame "
                    "would agree with a mis-aligned ESTIMATOR rather than with the "
                    "published value and would withhold a correct point, which is "
                    "why the two frame sizes are published side by side."
                    if witness_shape is not None
                    else ""
                )
                + (f" Caller's basis: {witness_basis}." if witness_basis else "")
                + (f" Not available: {witness_failure}." if witness_failure else "")
            )
        ),
        "autocorrelation": autocorrelation,
        "estimates": estimates,
    }
    if notes:
        block["notes"] = dict(notes)
    return block


def _adjudicated_entry(
    field: str,
    *,
    point: float,
    reproduced: float,
    difference: float,
    point_tolerance: float,
    witness_tolerance: float,
    witness_verdict: Optional[float],
    witness_failure: Optional[str],
    observations: int,
    effective_n: Optional[float],
) -> Dict[str, Any]:
    """The identity test failed. Decide which of the two values is the liar.

    The test itself is unchanged and still does its original job: the band is
    withheld in every branch below, because an interval for a neighbouring
    statistic is a fabricated precision. What changed is what happens to the
    POINT, and the reason text, which used to assert that the published value
    was the wrong one when it had no way of knowing.

    Three outcomes, in the order they are tested:

    1. The witness reproduced the published value. Then the published point is
       corroborated by a second, independent code path and the ESTIMATOR is the
       failing side - the frame the resampler was handed is not the sample the
       point was measured on. The point is RETAINED.
    2. The witness ran and also missed the published value. Then two
       independent derivations contradict the payload and the point is
       UNVERIFIED, so it is withheld (`point: null`) rather than published as a
       number no code path in this module can produce. This branch is
       unreachable on today's data; it exists so the guard is not one-sided.
    3. Otherwise - no witness, or the witness raised, produced a non-finite
       value, or was handed an empty frame - the point is RETAINED and flagged
       `unverified`. NEVER withheld. A witness that cannot deliver a verdict
       must not cost a reader a correct number, because the failure mode being
       fixed is publishing a number nobody checked, and a fix that traded that
       for hiding a number that was right would have replaced one defect with a
       worse one.
    """
    discrepancy = (
        f"the resampling estimator's own point value ({reproduced:.12g}) does "
        f"not reproduce the published {field} ({point:.12g}); difference "
        f"{difference:.3g} exceeds the {point_tolerance:g} band-provenance "
        "tolerance. The band would describe a different statistic, so it is "
        "withheld."
    )
    if witness_verdict is None:
        return _uncertainty_entry(
            field,
            point=point,
            status="not_computed",
            reason=(
                f"{discrepancy} The published point is RETAINED and flagged "
                f"unverified: this guard holds two numbers and cannot say which "
                f"is wrong without a third, and none could be produced - "
                f"{witness_failure}. An independent re-derivation of the "
                "published value on the sample it was published from is what "
                "settles which side failed, and withholding a point on the "
                "strength of a bare disagreement would have deleted correct "
                "numbers - including this one if the estimator, not the point, "
                "is the side that was handed a mis-aligned frame."
            ),
            observations=observations,
            effective_n=effective_n,
            point_status=POINT_UNVERIFIED,
        )
    witness_gap = abs(float(witness_verdict) - float(point))
    if witness_gap <= float(witness_tolerance):
        return _uncertainty_entry(
            field,
            point=point,
            status="not_computed",
            reason=(
                f"{discrepancy} The ESTIMATOR is the failing side: the published "
                f"{field} ({point:.12g}) IS reproduced ({witness_verdict:.12g}, "
                f"difference {witness_gap:.3g}) by an independent re-derivation "
                f"on the sample the point was published from, so the frame the "
                f"resampling estimator was handed is not that sample. The point "
                "is RETAINED as published."
            ),
            observations=observations,
            effective_n=effective_n,
            point_status=POINT_REPRODUCED_BY_WITNESS_ONLY,
        )
    return _uncertainty_entry(
        field,
        point=None,
        status="not_computed",
        reason=(
            f"{discrepancy} The published {field} ({point:.12g}) is ALSO not "
            f"reproduced by the independent re-derivation "
            f"({witness_verdict:.12g}, difference {witness_gap:.3g} against the "
            f"{witness_tolerance:g} witness tolerance), so two independent code "
            "paths contradict the value the payload publishes. The point is "
            "withheld rather than published as a number no available "
            "derivation can produce."
        ),
        observations=observations,
        effective_n=effective_n,
        point_status=POINT_NOT_REPRODUCED_BY_ANY_WITNESS,
    )


def _scalar_or_none(value: Any) -> Optional[float]:
    """First element of `value` as a finite float, else None."""
    array = np.asarray(value, dtype=float).ravel()
    if array.size == 0 or not np.isfinite(array[0]):
        return None
    return float(array[0])


def _statistic_column(block: Any, column: int = 0) -> np.ndarray:
    """``(n, draws)`` slice of an ``(n, draws, k)`` statistic input."""
    values = np.asarray(block, dtype=float)
    if values.ndim == 3:
        return values[:, :, column]
    return values


def quantstats_returns_look_like_prices(returns: Any) -> bool:
    """True when quantstats would reclassify this return series as a price series.

    `quantstats.utils._prepare_returns` treats any series with
    ``min >= 0 and max > 1`` as PRICES and differences it.  A daily equity
    return series does not look like that, but "does not" is not "cannot": if a
    window ever did, every ratio in this module would silently change meaning,
    so the caller checks and degrades with a reason instead of publishing a
    band for a statistic that is no longer the published one.
    """
    values = np.asarray(returns, dtype=float)
    if values.size == 0:
        return False
    return bool(np.nanmin(values) >= 0.0 and np.nanmax(values) > 1.0)


def quantstats_ratio_statistics(
    risk_free_rate: float, periods: int = 252
) -> Any:
    """Vectorised restatements of the quantstats ratios this payload publishes.

    Each entry reproduces `quantstats.stats.<name>` on the SAME return series to
    floating-point noise.  That fidelity is what lets
    `measure_estimate_uncertainty` verify the resampling distribution belongs to
    the published statistic before it publishes a band beside it - without it
    the block would be measuring a neighbour and calling it the same number.

    `block` has shape ``(n, draws, k)``; the single-series case uses column 0.
    """
    root_periods = float(np.sqrt(periods))
    # quantstats deannualises the risk-free rate COMPOUNDED
    # (`(1 + rf) ** (1 / periods) - 1`), not by dividing it by the period
    # count. The two differ at the fourth decimal at rf=0.02 over 252 days,
    # which is far wider than the identity tolerance below, so the published
    # point value has to come from the same deannualisation.
    daily_rf = float((1.0 + float(risk_free_rate)) ** (1.0 / float(periods)) - 1.0)

    def sharpe(block: Any) -> np.ndarray:
        series = _statistic_column(block)
        deviation = series.std(axis=0, ddof=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            return (series.mean(axis=0) - daily_rf) / deviation * root_periods

    def sortino(block: Any) -> np.ndarray:
        series = _statistic_column(block)
        shortfall = np.minimum(0.0, series - daily_rf)
        downside = np.sqrt((shortfall ** 2).sum(axis=0) / series.shape[0])
        with np.errstate(divide="ignore", invalid="ignore"):
            return (series.mean(axis=0) - daily_rf) / downside * root_periods

    def omega(block: Any) -> np.ndarray:
        # quantstats' `omega` with rf=0 and required_return=0: the threshold is
        # the per-period zero, so numerator and denominator are the positive
        # and negative parts of the return series.
        series = _statistic_column(block)
        gains = np.clip(series, 0.0, None).sum(axis=0)
        losses = -np.clip(series, -np.inf, 0.0).sum(axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            return gains / losses

    def total_return(block: Any) -> np.ndarray:
        series = _statistic_column(block)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.expm1(np.log1p(series).sum(axis=0))

    def cagr(block: Any) -> np.ndarray:
        series = _statistic_column(block)
        years = series.shape[0] / float(periods)
        with np.errstate(divide="ignore", invalid="ignore"):
            growth = np.exp(np.log1p(series).sum(axis=0) / years)
        return np.abs(growth) - 1.0

    def volatility(block: Any) -> np.ndarray:
        series = _statistic_column(block)
        return series.std(axis=0, ddof=1) * root_periods

    def max_drawdown(block: Any) -> np.ndarray:
        # quantstats' max_drawdown: `_prepare_prices` turns returns into
        # `1 + compsum(r)` at base 1.0, and compsum is a cumulative PRODUCT, so
        # the price path is `cumprod(1 + r)`. A phantom baseline is prepended
        # (so a first-day loss has a drawdown) and the deepest fall from a
        # running peak is returned.
        #
        # Since quantstats 0.0.82 that baseline is decided by whether the input
        # WAS returns (`_get_baseline_value(prices, from_returns)`), captured
        # before conversion -- not by the magnitude of the first rebuilt price.
        # The superseded heuristic inferred a baseline from the price level
        # (>1000 -> 1e5, >10 -> 100.0), which invented a peak the portfolio
        # never reached: a series whose first cumulative price clears 10
        # reported -70% drawdown here against quantstats' -9.6%. These inputs
        # are always returns, so the baseline is 1.0.
        series = _statistic_column(block)
        prices = np.cumprod(1.0 + series, axis=0)
        baseline = np.ones((1, series.shape[1]), dtype=prices.dtype)
        extended = np.vstack([baseline, prices])
        running_peak = np.maximum.accumulate(extended, axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            return (extended / running_peak).min(axis=0) - 1.0

    def calmar(block: Any) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            return cagr(block) / np.abs(max_drawdown(block))

    def tail_ratio(block: Any) -> np.ndarray:
        # quantstats' tail_ratio: |q95 / q05| under pandas' default linear
        # interpolation, which is numpy's default quantile method.
        series = _statistic_column(block)
        upper = np.quantile(series, 0.95, axis=0)
        lower = np.quantile(series, 0.05, axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.abs(upper / lower)

    return {
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "omega": omega,
        "tail_ratio": tail_ratio,
        "total_return": total_return,
        "cagr": cagr,
        "volatility": volatility,
        "max_drawdown": max_drawdown,
    }


def market_model_statistics(periods: int = 252) -> Any:
    """Vectorised `beta = cov(p, b) / var(b)` and the annualised Jensen alpha.

    Reproduces the tear-sheet's own closed form (`p.cov(b) / b.var()`, then
    `(p.mean() - beta * b.mean()) * periods`, both ddof=1) so the published
    band belongs to the published number.  `block` is ``(n, draws, 2)``:
    column 0 is the portfolio, column 1 the benchmark, resampled JOINTLY so the
    pair of series keeps the co-movement that produces the estimate.
    """
    count = int(periods)

    def _beta_alpha(block: Any) -> Tuple[np.ndarray, np.ndarray]:
        values = np.asarray(block, dtype=float)
        portfolio = values[:, :, 0]
        benchmark = values[:, :, 1]
        bench_mean = benchmark.mean(axis=0)
        port_mean = portfolio.mean(axis=0)
        centred_bench = benchmark - bench_mean
        denominator = (centred_bench ** 2).sum(axis=0) / max(1, values.shape[0] - 1)
        numerator = ((portfolio - port_mean) * centred_bench).sum(axis=0) / max(
            1, values.shape[0] - 1
        )
        with np.errstate(divide="ignore", invalid="ignore"):
            beta = numerator / denominator
        return beta, (port_mean - beta * bench_mean) * float(count)

    def beta(block: Any) -> np.ndarray:
        return _beta_alpha(block)[0]

    def alpha_annualized(block: Any) -> np.ndarray:
        return _beta_alpha(block)[1]

    return {"beta": beta, "alpha_annualized": alpha_annualized}


def market_model_witness(periods: int = 252) -> Dict[str, Any]:
    """A SECOND, independent derivation of beta and alpha, by least squares.

    This is the `witness` for the market-model block, and it exists to answer
    one question `market_model_statistics` structurally cannot: when the
    resampling estimator's own point value misses the published value, WHICH of
    the two is the liar?  A witness that restated the same expression would
    always agree with the estimator and would be worthless as an arbiter, so
    this deliberately shares no arithmetic with it:

      * `market_model_statistics` uses the tear sheet's closed form,
        `cov(p, b) / var(b)`, with both terms on ddof=1, and gets alpha by
        subtracting `beta * b.mean()` from `p.mean()`.  It divides by a variance,
        so a degenerate benchmark column makes it `0 / 0`.
      * this solves the normal equations directly with `np.linalg.lstsq` on the
        design matrix `[1, b]` and reads the slope and the intercept straight out
        of the solution vector.  No covariance, no variance, no ddof.  The
        intercept IS the daily Jensen alpha, so `alpha_annualized` is that
        intercept scaled by `periods` rather than the mean subtraction restated.

    The two are algebraically equivalent where both are well defined, so on a
    correctly aligned frame they agree to floating-point noise - which is what
    makes agreement meaningful evidence.  Where the closed form is not defined
    they are not equivalent at all: on a rank-deficient design `lstsq` returns
    the minimum-norm solution where the closed form returns a non-finite value,
    and that divergence is the proof that these are two different code paths and
    not one expression written twice.

    `block` is ``(n, draws, 2)``, column 0 the portfolio and column 1 the
    benchmark, exactly as for `market_model_statistics`.
    """
    scale = float(periods)

    def _solve(block: Any) -> Tuple[np.ndarray, np.ndarray]:
        values = np.asarray(block, dtype=float)
        rows, draws = int(values.shape[0]), int(values.shape[1])
        # [intercept, benchmark] - the design matrix a regression on a constant
        # column is actually solving, assembled rather than assumed.
        design = np.empty((rows, 2), dtype=float)
        design[:, 0] = 1.0
        design[:, 1] = values[:, 0, 1]
        slopes = np.empty(draws, dtype=float)
        intercepts = np.empty(draws, dtype=float)
        for draw in range(draws):
            solution, *_ = np.linalg.lstsq(design, values[:, draw, 0], rcond=None)
            slopes[draw] = float(solution[1])
            intercepts[draw] = float(solution[0])
        return slopes, intercepts

    def beta(block: Any) -> np.ndarray:
        return _solve(block)[0]

    def alpha_annualized(block: Any) -> np.ndarray:
        return _solve(block)[1] * scale

    return {"beta": beta, "alpha_annualized": alpha_annualized}


def engine_risk_statistics(
    risk_free_rate: float, periods: int = 252
) -> Any:
    """Vectorised restatements of the realized-risk engine's own formulas.

    Mirrors `_calculate_basic_metrics`, `_calculate_risk_metrics` and
    `_calculate_drawdown_metrics` exactly - including the Sortino downside
    deviation over the FULL sample length, the ddof=1 volatility, the
    `np.percentile(r, 5)` VaR and the `r <= var_95` ES mask - so the interval
    published beside `sharpe_ratio` or `cvar_95` is an interval for the number
    the engine actually printed.  `block` is ``(n, draws, k)``, column 0 in the
    single-series case.
    """
    root_periods = float(np.sqrt(periods))
    daily_rf = float(risk_free_rate) / float(periods)

    def annual_return(block: Any) -> np.ndarray:
        return _statistic_column(block).mean(axis=0) * float(periods)

    def annual_volatility(block: Any) -> np.ndarray:
        return _statistic_column(block).std(axis=0, ddof=1) * root_periods

    def sharpe_ratio(block: Any) -> np.ndarray:
        series = _statistic_column(block)
        with np.errstate(divide="ignore", invalid="ignore"):
            return (
                (series.mean(axis=0) * float(periods) - float(risk_free_rate))
                / (series.std(axis=0, ddof=1) * root_periods)
            )

    def sortino_ratio(block: Any) -> np.ndarray:
        series = _statistic_column(block)
        shortfall = np.minimum(0.0, series - daily_rf)
        downside = np.sqrt((shortfall ** 2).mean(axis=0)) * root_periods
        with np.errstate(divide="ignore", invalid="ignore"):
            return (
                series.mean(axis=0) * float(periods) - float(risk_free_rate)
            ) / downside

    def hit_ratio(block: Any) -> np.ndarray:
        return (_statistic_column(block) > 0.0).mean(axis=0)

    def var_95(block: Any) -> np.ndarray:
        return np.percentile(_statistic_column(block), 5, axis=0)

    def cvar_95(block: Any) -> np.ndarray:
        series = _statistic_column(block)
        threshold = np.percentile(series, 5, axis=0)
        mask = series <= threshold[None, :]
        support = mask.sum(axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            total = np.where(mask, series, 0.0).sum(axis=0) / support
        # The engine falls back to the VaR itself when the tail is empty; a
        # bootstrap resample with no observation at or below its own 5th
        # percentile cannot, so it stays non-finite and is reported as such.
        return np.where(support > 0, total, np.nan)

    def max_drawdown(block: Any) -> np.ndarray:
        series = _statistic_column(block)
        wealth = np.cumprod(1.0 + series, axis=0)
        extended = np.vstack([np.ones((1, series.shape[1]), dtype=float), wealth])
        running_peak = np.maximum.accumulate(extended, axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            return ((extended - running_peak) / running_peak).min(axis=0)

    return {
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "hit_ratio": hit_ratio,
        "var_95": var_95,
        "cvar_95": cvar_95,
        "max_drawdown": max_drawdown,
    }


#: Resampling draws evaluated per chunk by the pairwise-correlation
#: restatement.  The statistic is O(rows x draws x columns^2), so a wide book
#: would otherwise materialise a ``(draws, columns, columns)`` float array per
#: accumulator - six of them - before the first percentile is taken.  Chunking
#: bounds that peak without changing a single draw: the same resample indices,
#: the same arithmetic, the same numbers.
PAIRWISE_STATISTIC_DRAW_CHUNK = 100

#: Draw-count ceiling for the pairwise restatement, expressed as the
#: rows x draws x pairs work it is allowed.  At the book sizes this section
#: actually sees (14 legs, 39 rows, 91 pairs) the standard
#: :data:`UNCERTAINTY_BOOTSTRAP_RESAMPLES` is unchanged; the rule only bites on
#: a book wide enough that the disclosure would cost more than the request
#: budget.  Whatever count is used is published as `bootstrap_resamples` and the
#: rule that chose it as `resample_count_rule`, so the band stays reproducible
#: from the payload and a reduced count is visible rather than silent.
PAIRWISE_STATISTIC_RESAMPLE_BUDGET = 400_000

#: Floor on the reduced count.  Below this a percentile interval's own 2.5 %
#: tail is estimated from a handful of draws, which is worse than a wider band.
PAIRWISE_STATISTIC_MIN_RESAMPLES = 200


def pairwise_resample_count(
    pairs: int, budget: int = PAIRWISE_STATISTIC_RESAMPLE_BUDGET
) -> int:
    """Resamples the pairwise restatement may spend on `pairs` pairs."""
    count = int(pairs)
    if count <= 0:
        return int(UNCERTAINTY_BOOTSTRAP_RESAMPLES)
    return int(max(
        PAIRWISE_STATISTIC_MIN_RESAMPLES,
        min(
            int(UNCERTAINTY_BOOTSTRAP_RESAMPLES),
            int(budget) // count,
        ),
    ))


def pairwise_average_correlation_statistics(
    draw_chunk: int = PAIRWISE_STATISTIC_DRAW_CHUNK,
) -> Any:
    """Vectorised restatement of the risk-score correlation leg's own statistic.

    The leg publishes the mean of the finite upper-triangle Pearson
    correlations of the constituent return frame, i.e. of
    ``returns.corr()`` - and pandas' `.corr()` is PAIRWISE COMPLETE: each pair
    is measured on the rows where THAT pair is finite.  On a book with a leg
    that was listed part way through the window (the live export has one at 22
    return rows out of 39) the complete-case mean and the pairwise mean are
    different numbers, so a complete-case estimator would fail
    `measure_estimate_uncertainty`'s reproduction guard and the correct
    published value would be left without a band.

    So the pairwise population is reproduced here rather than approximated, with
    the means and sums-of-squares taken over each PAIR's own overlapping rows:

        r_ij = (P_ij - mi*Sxj - mj*Sxi + mi*mj*C_ij)
               / sqrt((Q_ij - 2*mi*Sxi + mi^2*C_ij) * (Q_ij - 2*mj*Sxj + mj^2*C_ij))

    over ``C_ij`` shared finite rows, with ``X`` the frame with non-finite
    entries zeroed (so a non-finite entry contributes to no sum at all).  Every
    one of the five accumulators is a batched ``(k, rows) @ (rows, k)`` product.
    A pair with fewer than two shared rows, or no variation in either leg, is
    NaN - pandas' own "not measurable" answer - and the mean skips it, exactly
    as ``finite_pairs`` in the leg does.

    `block` has shape ``(rows, draws, columns)``.
    """
    chunk = max(1, int(draw_chunk))

    def _mean_upper_triangle(draws_first: np.ndarray) -> np.ndarray:
        draws, rows, columns = draws_first.shape
        if columns < 2 or rows < 1:
            return np.full(draws, np.nan)
        finite = np.isfinite(draws_first)
        filled = np.where(finite, draws_first, 0.0)
        indicator = finite.astype(float)
        squared = filled * filled
        # (draws, i, j) accumulators over the rows on which BOTH i and j are
        # finite. `filled` is already zero wherever a column is not finite, so a
        # plain product over it carries the pairwise mask for free.
        overlap = np.matmul(indicator.transpose(0, 2, 1), indicator)
        sum_i = np.matmul(filled.transpose(0, 2, 1), indicator)
        sum_j = np.matmul(indicator.transpose(0, 2, 1), filled)
        cross = np.matmul(filled.transpose(0, 2, 1), filled)
        sum_sq_i = np.matmul(squared.transpose(0, 2, 1), indicator)
        sum_sq_j = np.matmul(indicator.transpose(0, 2, 1), squared)
        upper_index = np.triu_indices(columns, k=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            mean_i = sum_i / overlap
            mean_j = sum_j / overlap
            covariance = (
                cross - mean_i * sum_j - mean_j * sum_i + mean_i * mean_j * overlap
            )
            variance_i = (
                sum_sq_i - 2.0 * mean_i * sum_i + mean_i * mean_i * overlap
            )
            variance_j = (
                sum_sq_j - 2.0 * mean_j * sum_j + mean_j * mean_j * overlap
            )
            correlations = covariance / np.sqrt(variance_i * variance_j)
            upper = correlations[:, upper_index[0], upper_index[1]]
            # pandas' own "not measurable": a pair with fewer than two shared
            # rows, or no variation, contributes nothing to the mean.
            usable = np.isfinite(upper) & (
                overlap[:, upper_index[0], upper_index[1]] >= 2
            )
            count = usable.sum(axis=1)
            total = np.where(usable, np.nan_to_num(upper), 0.0).sum(axis=1)
        return np.where(count > 0, total / np.maximum(count, 1), np.nan)

    def avg_pairwise_correlation(block: Any) -> np.ndarray:
        values = np.asarray(block, dtype=float)
        draws = int(values.shape[1]) if values.ndim == 3 else 0
        if draws < 1:
            return np.zeros(0, dtype=float)
        out = np.empty(draws, dtype=float)
        for start in range(0, draws, chunk):
            stop = min(draws, start + chunk)
            out[start:stop] = _mean_upper_triangle(
                np.swapaxes(values[:, start:stop, :], 0, 1)
            )
        return out

    return {"avg_pairwise_correlation": avg_pairwise_correlation}


def regression_r_squared_statistics() -> Any:
    """Vectorised R-squared of a simple regression on a two-column block.

    The risk score's factor leg is ``min(30, (1 - r_squared) * 100)`` over a
    statsmodels OLS fit of the portfolio return on a constant plus the
    benchmark, and statsmodels' ``rsquared`` is
    ``Sxy^2 / (Sxx * Syy)`` on centred sums - no ddof, because the ddof cancels
    between numerator and denominator.  That is exactly what is computed here,
    so a resampled draw's value belongs to the same statistic the payload
    published.

    `block` has shape ``(rows, draws, 2)``: column 0 is the regressand, column 1
    the regressor, resampled JOINTLY so the co-movement that produces the
    estimate survives the resampling.
    """
    def r_squared(block: Any) -> np.ndarray:
        values = np.asarray(block, dtype=float)
        if values.ndim != 3 or values.shape[2] < 2:
            return np.zeros(int(values.shape[1]) if values.ndim == 3 else 0)
        regressand = values[:, :, 0] - values[:, :, 0].mean(axis=0)
        regressor = values[:, :, 1] - values[:, :, 1].mean(axis=0)
        sum_xx = (regressor * regressor).sum(axis=0)
        sum_yy = (regressand * regressand).sum(axis=0)
        sum_xy = (regressor * regressand).sum(axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            return (sum_xy * sum_xy) / (sum_xx * sum_yy)

    return {"factor_r_squared": r_squared}


def _benchmark_return_series(benchmark_data: Any) -> pd.Series:
    """The benchmark as RETURNS, by `factor_exposure_analysis`'s own rule.

    A benchmark above 1.0 in absolute value is a PRICE series and is
    differenced; anything else is taken as already being returns.  Duplicated
    here rather than shared, because `_calculate_factor_exposures` receives the
    converted series as a parameter and does not do the conversion itself - and
    the frame this disclosure resamples has to be the frame the fit was handed.
    """
    if benchmark_data is None:
        return pd.Series(dtype=float)
    series = (
        benchmark_data if isinstance(benchmark_data, pd.Series)
        else pd.Series(benchmark_data)
    )
    if series.empty:
        return pd.Series(dtype=float)
    if bool(series.abs().gt(1.0).any()):
        return series.pct_change(fill_method=None).dropna()
    return series.dropna()


#: `_calculate_factor_exposures` refuses to fit below this many paired rows
#: twice (once on the common index, once on the published-portfolio subset).
_FACTOR_FIT_MIN_ROWS = 10


def _factor_regression_frame(
    returns: pd.DataFrame, benchmark_data: Any, weights: Mapping[str, float]
) -> Tuple[np.ndarray, Optional[str]]:
    """The ``(n, 2)`` frame the factor leg's R-squared was fitted on.

    Column 0 is the coverage-gated portfolio return, column 1 the benchmark,
    paired BY DATE.  The population is re-derived through the same four steps
    `_calculate_factor_exposures` runs - align on the shared index, aggregate
    the portfolio over positive active weight, keep only dates the aggregate
    actually published, intersect with the benchmark - because a bootstrap over
    a different sample would measure a different regression.

    Returns ``(frame, window, reason)``; `reason` is set when no usable frame
    exists, and is published rather than absorbed, so a missing band is always
    explained.  `window` is the fit's own first/last DATES, because a fit
    statistic published without them cannot be compared with the same model's fit
    over a different window.
    """
    empty = np.zeros((0, 2), dtype=float)
    if not isinstance(returns, pd.DataFrame) or returns.empty:
        return empty, None, (
            "no constituent return frame was delivered, so the regression's "
            "sample does not exist"
        )
    normalized = {
        key: float(value)
        for key, value in dict(weights).items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        and np.isfinite(float(value)) and float(value) > 0.0
    }
    total = sum(normalized.values())
    if total > 0:
        normalized = {key: value / total for key, value in normalized.items()}
    benchmark = _benchmark_return_series(benchmark_data)
    if len(benchmark) <= 10:
        return empty, None, (
            f"the benchmark contributes {len(benchmark)} usable return row(s), "
            f"and the factor regression is not fitted on fewer than {_FACTOR_FIT_MIN_ROWS}"
        )
    common = returns.index.intersection(benchmark.index)
    if len(common) <= 10:
        return empty, None, (
            f"the portfolio return frame and the benchmark share only "
            f"{len(common)} date(s), and the factor regression is not fitted on "
            f"fewer than {_FACTOR_FIT_MIN_ROWS}"
        )
    aligned = returns.loc[common]
    coverage = active_return_coverage(aligned, normalized)
    published_dates = coverage.index[coverage["published"]]
    portfolio = aggregate_active_returns(aligned, normalized).dropna()
    active = published_dates.intersection(benchmark.index).intersection(
        portfolio.index
    )
    if len(active) < _FACTOR_FIT_MIN_ROWS:
        return empty, None, (
            f"only {len(active)} date(s) carried both a published portfolio "
            f"return and a benchmark return, and the factor regression is not "
            f"fitted on fewer than {_FACTOR_FIT_MIN_ROWS}"
        )
    frame = np.column_stack([
        portfolio.loc[active].to_numpy(dtype=float),
        benchmark.loc[active].to_numpy(dtype=float),
    ])
    return frame, _fit_window(active, int(len(active))), None


def _iso_day(label: Any) -> Optional[str]:
    """One index label as an ISO calendar day, or None if it is not a date."""
    try:
        return pd.Timestamp(label).date().isoformat()
    except Exception:  # noqa: BLE001 - a non-date label is an absence, not a crash
        return None


def _fit_window(labels: Any, count: int) -> Dict[str, Any]:
    """The fit's own `model_window` shape: first date, last date, row count."""
    values = list(labels)
    first = _iso_day(values[0]) if values else None
    last = _iso_day(values[-1]) if values else None
    return {
        "start": first,
        "end": last,
        "days": int(count),
        "declared": bool(first and last),
    }


def _liquidity_band(published_score: float) -> tuple[str, str]:
    """Band label and liquidation window for an ALREADY-ROUNDED published score."""
    for band, floor, window in LIQUIDITY_SCORE_BANDS:
        if floor is None or published_score >= floor:
            return band, window
    last_band, _floor, last_window = LIQUIDITY_SCORE_BANDS[-1]
    return last_band, last_window


def _market_cap_provenance(
    supplied: Any, daily_turnover: float
) -> tuple[float, str, str]:
    """Resolve `(market_cap, provenance, source)` for one position.

    `measured` means a quote supplied a finite positive market cap.
    `estimated` means the cap was annualised from measured daily turnover, and
    `fallback` means the fixed INR 1bn floor was used because turnover was not
    measured at all.  The last two are estimates; neither is a measured cap.
    """
    try:
        candidate = float(supplied)
    except (TypeError, ValueError):
        candidate = 0.0
    if np.isfinite(candidate) and candidate > 0.0:
        return candidate, "measured", "quote"

    implied = float(daily_turnover) * LIQUIDITY_IMPLIED_TURNOVER_DAYS
    if np.isfinite(implied) and implied > LIQUIDITY_MARKET_CAP_FLOOR_INR:
        return implied, "estimated", "implied_annual_turnover"
    return LIQUIDITY_MARKET_CAP_FLOOR_INR, "fallback", "fixed_floor_1e9_inr"


def _leg_series_relation(
    leg: Optional[pd.Series], canonical: Optional[pd.Series]
) -> Optional[str]:
    """How `leg`'s input rows relate to the same-statistic leg's input rows.

    ``"identical"`` -- the same rows, so both legs are one measurement.
    ``"strict_subset"`` -- `leg` is a proper suffix of `canonical`, so it
    re-measures the same statistic over a shorter window of the same series.
    ``None`` -- genuinely different rows, so the two legs are separate
    measurements and neither duplicates the other.
    """
    if leg is None or canonical is None or len(leg) == 0:
        return None
    if len(leg) == len(canonical) and leg.index.equals(canonical.index):
        return "identical"
    if len(leg) < len(canonical) and canonical.index[-len(leg) :].equals(leg.index):
        return "strict_subset"
    return None


#: Why ``sub_score`` and ``headroom_to_cap`` on the same leg do not subtract to
#: ``cap``.  Published as data on every leg rather than left to be inferred: the
#: two are one quantity at two roundings, the payload published them side by side
#: with no precision basis, and a reader checking ``cap - sub_score ==
#: headroom_to_cap`` concluded four of the five legs were inconsistent.  Nothing
#: moved; the note says which number answers which question.
RISK_SCORE_SUB_SCORE_PRECISION_NOTE = (
    "sub_score is this leg's sub-score rounded to 1 decimal for display, and "
    "headroom_to_cap is cap minus the UNROUNDED sub-score, so the two differ by "
    "up to 0.05 and are not meant to subtract to cap. Use sub_score to read the "
    "leg. Use headroom_to_cap, or reconstruct the unrounded sub-score as cap - "
    "headroom_to_cap, when reconciling against input_statistic_value: that "
    "reconstruction is the value every other figure on this leg "
    "(headline_contribution, headline_share) was built from"
)


def _risk_score_audit(
    *,
    scores: Mapping[str, Optional[float]],
    inputs: Mapping[str, Optional[float]],
    input_reasons: Mapping[str, str],
    input_samples: Mapping[str, Dict[str, Any]],
    input_series: Mapping[str, Optional[pd.Series]],
    floor_clamps: Mapping[str, float],
    excluded: Sequence[str],
    excluded_reasons: Mapping[str, str],
    active_weights: Mapping[str, float],
    overall_score: float,
    returns: Optional[pd.DataFrame] = None,
    benchmark_data: Any = None,
    weights: Optional[Mapping[str, float]] = None,
    avg_pairwise_correlation_published: Optional[float] = None,
    r_squared: Optional[float] = None,
    factor_result: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Publish the composition of `overall_score`, leg by leg.

    Everything here is derived from numbers the score itself was built from, so
    a reader can recompute the headline instead of trusting it:

      * the input statistic, its units, and the rows it was measured over,
      * the formula, the nominal weight, the weight actually applied, the cap,
      * whether the leg is AT that cap and the input at which it would leave it,
      * the scale's floor, whether it bound, and the points it added,
      * whether the leg's input is the same rows as another leg's, and why,
      * what share of the headline each leg is actually responsible for,
      * and, under `precision`, how precisely each of those three kinds of
        number is known.

    Nothing here changes a score, a weight or a cap.  If a leg's input cannot be
    established it is published as unavailable with the reason, never inferred.
    """
    included = [
        name
        for name in RISK_SCORE_WEIGHTS
        if name not in excluded and scores.get(name) is not None
    ]
    # A numpy scalar would serialise as a different JSON type, and the published
    # share has to be a plain number a reader can divide with.
    #
    # Every share is divided by the UNROUNDED headline. Dividing the unrounded
    # contributions by the ROUNDED one -- the old code, on the reasoning that "a
    # share a reader cannot reproduce from the number on the payload is a number
    # nobody can check" -- made the five published shares sum to 1.001419 on the
    # v26 book: 13.118601 of contribution over a 13.1 denominator. Rounding at
    # 6 dp can move the sum by at most 5 x 2.5e-6, so the 1.4e-3 excess was a
    # normalisation error and not a display artefact. The old reasoning was
    # sound and the fix it asked for was the wrong one: the payload now publishes
    # the unrounded total as `headline_basis_score` / `overall_score_raw` beside
    # the 1-decimal display value, so a reader reproduces every share exactly
    # AND still sees the number the score is quoted at.
    total_unrounded = float(overall_score)
    total = round(total_unrounded, 1)

    # Which leg in a shared statistic family is credited with the independent
    # measurement: the first measured leg of the family, in report order.
    family_canonical: Dict[str, str] = {}
    duplicate_of: Dict[str, Optional[str]] = {n: None for n in RISK_SCORE_WEIGHTS}
    duplicate_relation: Dict[str, Optional[str]] = {n: None for n in RISK_SCORE_WEIGHTS}
    for name in included:
        group = RISK_SCORE_LEG_SPECS[name].get("duplication_group")
        if group is None:
            continue
        if group not in family_canonical:
            family_canonical[group] = name
            continue
        canonical = family_canonical[group]
        relation = _leg_series_relation(
            input_series.get(name), input_series.get(canonical)
        )
        if relation is None:
            continue
        duplicate_of[name] = canonical
        duplicate_relation[name] = relation

    # A leg is pinned when its UNROUNDED sub-score is the cap.  A leg merely
    # near the cap has headroom and is not described as pinned.
    def _is_saturated(name: str) -> bool:
        score = scores.get(name)
        return (
            name in included
            and score is not None
            and float(score) >= RISK_SCORE_CAP
        )

    components: Dict[str, Any] = {}
    contributions: Dict[str, float] = {}
    for name, nominal_weight in RISK_SCORE_WEIGHTS.items():
        spec = RISK_SCORE_LEG_SPECS[name]
        score = scores.get(name)
        measured = name in included
        saturated = _is_saturated(name)
        weight = active_weights.get(name)
        sample = dict(input_samples.get(name) or {})
        # The floor is a property of the scale, so it is published on every
        # leg; whether it BOUND is per leg, and only a leg whose expression can
        # go negative can ever bind it (see RISK_SCORE_FLOOR).
        floor_clamp = (
            round(float(floor_clamps.get(name, 0.0)), 6)
            if measured and scores.get(name) is not None
            else None
        )
        entry: Dict[str, Any] = {
            "status": (
                "saturated_at_cap"
                if saturated
                else ("measured" if measured else "unmeasured")
            ),
            "input_statistic": spec["input_statistic"],
            "input_statistic_value": (
                round(float(inputs[name]), 6)
                if measured and inputs.get(name) is not None
                else None
            ),
            "input_statistic_units": spec["input_units"],
            "input_statistic_provenance": (
                "measured" if measured and inputs.get(name) is not None else "unavailable"
            ),
            "input_statistic_unavailable_reason": (
                None
                if measured and inputs.get(name) is not None
                else input_reasons.get(name) or excluded_reasons.get(name)
            ),
            "input_sample": sample,
            "formula": spec["formula"],
            "nominal_weight": nominal_weight,
            "effective_weight": round(weight, 6) if weight is not None else None,
            "cap": RISK_SCORE_CAP,
            "sub_score": round(float(score), 1) if score is not None else None,
            "headroom_to_cap": (
                round(RISK_SCORE_CAP - float(score), 6) if score is not None else None
            ),
            # The two numbers above are the SAME quantity at two roundings, and
            # the payload published them with nothing saying so: 4 of the 5 legs
            # on the v26 book disagreed (concentration published sub_score 8.6
            # beside headroom 21.44, which is cap - 8.56). Both are right, and
            # which one to use depends on the question.
            "sub_score_precision_note": RISK_SCORE_SUB_SCORE_PRECISION_NOTE,
            "saturated": saturated,
            "cap_binding_input": round(float(spec["cap_binding_input"]), 6),
            "cap_binds_when_input_is": spec["cap_binds_when_input_is"],
            "unpin_condition": spec["unpin_condition"],
            "floor": RISK_SCORE_FLOOR,
            "clamped_at_floor": bool(floor_clamp),
            "floor_clamp_points": floor_clamp,
            "floor_binding_input": (
                round(float(spec["floor_binding_input"]), 6)
                if "floor_binding_input" in spec
                else None
            ),
            "floor_binds_when_input_is": spec.get("floor_binds_when_input_is"),
            "floor_reason": spec.get("floor_reason"),
            "duplicate_of": duplicate_of[name],
            "duplicate_relation": duplicate_relation[name],
            "counts_as_independent_evidence": bool(measured and not duplicate_of[name]),
            "exclusion_reason": excluded_reasons.get(name),
            "published_input_as": spec["published_input_as"],
            # How this sub-score's PRECISION is known, which is a different
            # question from how its value was derived: the value is a
            # deterministic function of one published input, so the sub-score
            # never carries an independent standard error. The pointer says
            # which input's disclosure it inherits.
            "precision_classification": "deterministic_derivation",
            "precision_inherits_from": spec["input_statistic"],
            "precision_disclosure_at": f"score_audit.precision.derived_values.{name}",
        }
        if duplicate_of[name] == "volatility":
            # The one duplication this table can produce, explained by the
            # numbers that cause it rather than by a standing claim.
            whole_rows = sample.get("rows")
            if duplicate_relation[name] == "identical":
                entry["duplicate_reason"] = (
                    f"the market leg's tail({RISK_MARKET_WINDOW_ROWS}) window is "
                    f"not shorter than the {whole_rows}-row portfolio return series "
                    f"it reads, so both legs are min(30, std * sqrt(252) * 100) "
                    f"over the same rows and publish the same number"
                )
                entry["duplicate_is_sample_dependent"] = True
                entry["duplicate_clears_when"] = (
                    f"the delivered portfolio return series grows past "
                    f"{RISK_MARKET_WINDOW_ROWS} rows, at which point the market "
                    f"leg reads a shorter window of the same series and stops "
                    f"being the same number"
                )
            else:
                entry["duplicate_reason"] = (
                    "both legs measure the volatility of the SAME portfolio "
                    f"return series: the market leg reads its last {whole_rows} "
                    "rows and volatility reads all of them, so this is one "
                    "statistic over one series rather than two"
                )
                entry["duplicate_is_sample_dependent"] = False
                entry["duplicate_clears_when"] = (
                    "only measuring a different statistic would clear this; the "
                    "leg is a shorter window on the same series, not a second "
                    "measurement"
                )
        elif measured:
            entry["duplicate_is_sample_dependent"] = False
            entry["duplicate_clears_when"] = None
        else:
            entry["duplicate_is_sample_dependent"] = None
            entry["duplicate_clears_when"] = None
        if measured and weight is not None:
            contribution = float(score) * float(weight)
            contributions[name] = round(contribution, 6)
            entry["headline_contribution"] = round(contribution, 6)
            # Divided by the UNROUNDED total, so the shares partition the
            # headline instead of over-claiming it by the rounding of the
            # denominator (see `total_unrounded` above).
            entry["headline_share"] = (
                round(contribution / total_unrounded, 6) if total_unrounded else None
            )
            entry["headline_share_reason"] = (
                None
                if total_unrounded
                else "overall_score is 0, so a share of it is undefined"
            )
        else:
            # An unmeasured leg has no share to publish, and the old expression
            # published 0.0 with a reason when the headline was zero and None
            # with NO reason when it was not -- the one case that actually
            # occurs, and an absent value without one. The reason is now always
            # the one that actually applies, so the two branches agree on the
            # pairing (value or null, plus why).
            entry["headline_contribution"] = 0.0
            entry["headline_share"] = 0.0 if not total_unrounded else None
            entry["headline_share_reason"] = (
                "leg was not measured, so it contributes nothing to the headline"
            )
        components[name] = entry

    saturated_legs = [n for n in RISK_SCORE_WEIGHTS if _is_saturated(n)]
    floor_clamped_legs = [
        n for n in RISK_SCORE_WEIGHTS
        if n in included and components[n].get("clamped_at_floor")
    ]
    duplicate_legs = [n for n in RISK_SCORE_WEIGHTS if duplicate_of[n]]
    independent_legs = [
        n
        for n in RISK_SCORE_WEIGHTS
        if n in included and not duplicate_of[n]
    ]
    # Every leg lands in exactly ONE bucket, so the buckets partition the
    # headline and a leg that is BOTH a duplicate and at its cap cannot inflate
    # two of the shares at once. The raw facts (`saturated_components`,
    # `duplicate_components`) are published beside this and do NOT partition: a
    # saturated duplicate is reported in both and bucketed in one.
    bucket: Dict[str, str] = {}
    for name in RISK_SCORE_WEIGHTS:
        if name not in included:
            bucket[name] = "excluded"
        elif duplicate_of[name]:
            bucket[name] = "duplicate"
        elif name in saturated_legs:
            bucket[name] = "pinned"
        else:
            bucket[name] = "responsive"
    for name, value in bucket.items():
        components[name]["headline_bucket"] = value
    bucket_legs = {
        key: [n for n in RISK_SCORE_WEIGHTS if bucket[n] == key]
        for key in ("responsive", "pinned", "duplicate", "excluded")
    }

    def _weight_of(names: Sequence[str]) -> float:
        return round(
            sum(float(active_weights.get(n) or 0.0) for n in names), 6
        )

    def _nominal_weight_of(names: Sequence[str]) -> float:
        return round(
            sum(float(RISK_SCORE_WEIGHTS.get(n) or 0.0) for n in names), 6
        )

    def _share(names: Sequence[str]) -> Optional[float]:
        """Share of the headline carried by `names`, recomputable from it.

        Same denominator as the per-leg `headline_share` and for the same reason:
        the UNROUNDED total, so the three bucket shares partition the headline
        rather than exceeding it by the denominator's rounding.
        """
        if not total_unrounded:
            return None
        return round(
            sum(contributions.get(n, 0.0) for n in names) / total_unrounded, 6
        )

    headline_weight = round(
        _weight_of(bucket_legs["responsive"])
        + _weight_of(bucket_legs["pinned"])
        + _weight_of(bucket_legs["duplicate"]),
        6,
    )
    effective_information: Dict[str, Any] = {
        "measured_leg_count": len(included),
        "independent_leg_count": len(independent_legs),
        "responsive_leg_count": len(bucket_legs["responsive"]),
        "responsive_legs": bucket_legs["responsive"],
        "responsive_weight": _weight_of(bucket_legs["responsive"]),
        "responsive_share_of_headline": _share(bucket_legs["responsive"]),
        "pinned_legs": bucket_legs["pinned"],
        "pinned_weight": _weight_of(bucket_legs["pinned"]),
        "pinned_share_of_headline": _share(bucket_legs["pinned"]),
        "duplicate_legs": bucket_legs["duplicate"],
        "duplicate_weight": _weight_of(bucket_legs["duplicate"]),
        "duplicate_share_of_headline": _share(bucket_legs["duplicate"]),
        "independent_weight": _weight_of(independent_legs),
        # The headline is the weighted average of the legs that were MEASURED,
        # with their weights renormalized to sum to 1, so the three weights above
        # are the whole of it and always add up to 1. A leg that was excluded
        # carries none of the headline by construction -- which is not the same
        # statement as being pinned, and is kept apart from it here.
        #
        # This sentence is published DATA, so it is held to the same standard as
        # a number: the old wording ended "the first three sum to 1 -- the whole
        # headline" with no noun, in a block whose three preceding keys are
        # `*_share_of_headline`, and the shares summed to 1.001419. A disclosure
        # that names no quantity cannot be checked by a reader, and the one a
        # reader would have read was false. So both sums are named, and both are
        # true.
        "headline_weight_basis": (
            "effective (renormalized) weights; each leg sits in exactly one of "
            "headline_bucket responsive/pinned/duplicate/excluded, and the first "
            "three buckets' WEIGHTS sum to 1 -- the whole headline. Their shares "
            "of the headline (responsive_share_of_headline, "
            "pinned_share_of_headline, duplicate_share_of_headline) also sum to 1, "
            "divided by headline_basis_score, the UNROUNDED total; overall_score "
            "is that same total rounded to 1 decimal for display"
        ),
        # The denominator every share on this payload is computed from, at the
        # precision it is computed at. `headline_basis_score_rounded` is the
        # display value beside it, and `overall_score_raw` is the same number
        # under the name `liquidity` already publishes it under.
        "headline_basis_score": round(total_unrounded, 6),
        "headline_basis_score_rounded": total,
        "overall_score_raw": round(total_unrounded, 6),
        "headline_basis_score_note": (
            "the unrounded weighted mean of the measured legs' sub-scores, i.e. "
            "the value that becomes overall_score once rounded to 1 decimal. Every "
            "headline_share and every *_share_of_headline on this payload is "
            "divided by it, so those shares sum to 1; dividing by the rounded "
            "overall_score instead made them sum to 1.001419 on the v26 book"
        ),
        "headline_weight_total": headline_weight,
        "unmeasured_leg_count": len(excluded),
        "unmeasured_nominal_weight": _nominal_weight_of(list(excluded)),
        "responsive_nominal_weight": _nominal_weight_of(bucket_legs["responsive"]),
        "pinned_nominal_weight": _nominal_weight_of(bucket_legs["pinned"]),
        "duplicate_nominal_weight": _nominal_weight_of(bucket_legs["duplicate"]),
        "headline_attribution": contributions,
        "headline_attribution_note": (
            "contribution = unrounded sub_score x effective_weight; the "
            "contributions sum to the unrounded overall_score, which the "
            "payload publishes rounded to 1 decimal as overall_score, so their "
            "sum can differ from it by up to 0.05. The unrounded total they sum "
            "to is published as headline_basis_score, and it is what each "
            "contribution is divided by to give headline_share"
        ),
        "share_undefined_reason": (
            None
            if total_unrounded
            else "overall_score is 0, so no share of the headline is defined"
        ),
    }

    return {
        "scale": "risk_points_0_to_30_higher_is_riskier",
        "cap": RISK_SCORE_CAP,
        "nominal_weights": dict(RISK_SCORE_WEIGHTS),
        "nominal_weight_total": round(sum(RISK_SCORE_WEIGHTS.values()), 6),
        "weight_rule": (
            "a leg that could not be measured is dropped and the remaining "
            "weights are renormalized to sum to 1; effective_weight is the "
            "weight actually applied"
        ),
        "excluded_components": list(excluded),
        "excluded_reasons": dict(excluded_reasons),
        "saturated_components": saturated_legs,
        # The floor is the scale's other bound, declared the way the cap is:
        # a leg clamped here published 0.0 for a MEASURED input, and without
        # this block that 0.0 is indistinguishable from a measurement of no
        # correlation at all.
        "floor": RISK_SCORE_FLOOR,
        "floor_reason": (
            "the 0-30 scale has no negative risk points, so a measured input "
            "that maps below zero is clamped rather than published as negative "
            "risk; a clamped leg keeps its measured input_statistic_value and "
            "publishes the points the floor added in floor_clamp_points. "
            "Removing the floor would move overall_score and could flip "
            "risk_level, which is a product decision"
        ),
        "floor_clamped_components": floor_clamped_legs,
        "floor_clamp_detail": [
            {
                "component": n,
                "input_statistic": components[n].get("input_statistic"),
                "input_statistic_value": components[n].get("input_statistic_value"),
                "clamp_points": components[n].get("floor_clamp_points"),
                "binds_when_input_is": components[n].get(
                    "floor_binds_when_input_is"
                ),
            }
            for n in floor_clamped_legs
        ],
        "duplicate_components": [
            {
                "component": n,
                "duplicate_of": duplicate_of[n],
                "relation": duplicate_relation[n],
                "sample_dependent": components[n].get("duplicate_is_sample_dependent"),
                "clears_when": components[n].get("duplicate_clears_when"),
            }
            for n in duplicate_legs
        ],
        "independent_components": independent_legs,
        "components": components,
        "effective_information": effective_information,
        "precision": _risk_score_precision(
            returns=returns,
            benchmark_data=benchmark_data,
            weights=weights,
            audit_components=components,
            avg_pairwise_correlation=avg_pairwise_correlation_published,
            factor_r_squared=r_squared,
            factor_result=factor_result,
        ),
    }


#: Why a derived sub-score gets no interval of its own.  Published as data
#: rather than as a comment so a consumer that reads only the numbers cannot
#: mistake the absence for an oversight.
#:
#: TWO forms, not one form with a hole in it.  The single-template version had a
#: null `inherits_precision_at` substituted into the middle of a sentence, which
#: produced "... published at no precision disclosure for this input is published
#: in this section ..." - a clause spliced into a clause, published on the
#: `volatility` and `market_risk` legs.  The two branches below share the same
#: opening and the same closing sentence, so a reader sees one shape; only the
#: middle sentence differs, because a pointer and its absence are different facts
#: and only one of them can end a sentence.
RISK_SCORE_DERIVED_NO_INTERVAL_REASON = (
    "not computed: this sub-score is a deterministic function of one published "
    "input ({input_statistic} = {input_value}), not an independent estimate. Its "
    "precision is entirely INHERITED from that input's own disclosure, published "
    "at {inherits_at}. A second resampling interval here would describe a "
    "function of an already-published number, not the uncertainty of anything "
    "this sub-score measured, and a reader could not tell the two apart."
)

#: The same reason for a leg whose input is MEASURED but has no precision block
#: in this section.  A measured input is not a declared constant: it has a real
#: sampling distribution, and the honest statement is that this section does not
#: publish a band for it and names where such a band would go - not that one was
#: asked for and does not exist.
RISK_SCORE_DERIVED_UNPUBLISHED_INPUT_REASON = (
    "not computed: this sub-score is a deterministic function of one published "
    "input ({input_statistic} = {input_value}), not an independent estimate. That "
    "input is {provenance}, so it has a real sampling distribution, and this "
    "section publishes no standard error or interval for it: the measured inputs "
    "that DO carry a band are published under "
    "score_audit.precision.estimated_statistics, and this input has no block "
    "there. Its precision is therefore declared UNSTATED rather than asserted, "
    "and the input's own row in score_audit.components.{leg}.input_sample is the "
    "sample any such band would be measured on. A second resampling interval "
    "here would describe a function of an already-published number, not the "
    "uncertainty of anything this sub-score measured, and a reader could not "
    "tell the two apart."
)


def _risk_score_derived_no_interval_reason(
    *,
    leg: str,
    input_statistic: str,
    input_value: Any,
    provenance: Any,
    inherits_at: Optional[str],
) -> str:
    """The one reason for a derived sub-score, in whichever of its two forms.

    Kept as a function rather than a second `.format()` at the call site so the
    branch is chosen in exactly one place: an `inherits_precision_at` that is
    `None` cannot be substituted into the resolved-pointer sentence, and the
    earlier template did exactly that.
    """
    if inherits_at:
        return RISK_SCORE_DERIVED_NO_INTERVAL_REASON.format(
            input_statistic=input_statistic,
            input_value=input_value,
            inherits_at=inherits_at,
        )
    return RISK_SCORE_DERIVED_UNPUBLISHED_INPUT_REASON.format(
        input_statistic=input_statistic,
        input_value=input_value,
        provenance=provenance or "not classified",
        leg=leg,
    )

RISK_SCORE_DECLARED_NO_STANDARD_ERROR_REASON = (
    "not applicable: this is a declared policy constant read from "
    f"{RISK_SCORE_WEIGHT_TABLE}. It is not estimated from data and has no "
    "sampling distribution, so there is no standard error to report."
)


def _risk_score_precision(
    *,
    returns: Optional[pd.DataFrame],
    benchmark_data: Any,
    weights: Optional[Mapping[str, float]],
    audit_components: Mapping[str, Mapping[str, Any]],
    avg_pairwise_correlation: Optional[float],
    factor_r_squared: Optional[float],
    factor_result: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """How precisely each number behind `overall_score` is known.

    Three classes, three different answers, and no band that does not belong to
    the number printed beside it:

      * `estimated_statistics` - the two inputs that are measured from data.
        Each gets its own `measure_estimate_uncertainty` block over the sample it
        was actually measured on, which is why they are two blocks and not one:
        `avg_pairwise_correlation` is a mean over the constituent return frame
        and `factor_r_squared` is a regression on the portfolio/benchmark pair,
        and a single bootstrap cannot resample both populations at once.

      * `derived_values` - every leg's sub-score.  A pointer to the input whose
        precision it inherits, and a `null` standard error and interval with the
        reason attached.

      * `declared_constants` - the leg weights, with the table they come from.
    """
    estimated: Dict[str, Any] = {}
    frame = returns if isinstance(returns, pd.DataFrame) else pd.DataFrame()
    columns = [str(column) for column in frame.columns]

    # --- the correlation leg's input, measured on the constituent return frame
    correlation_block: Dict[str, Any]
    if avg_pairwise_correlation is None or len(columns) < 2:
        correlation_block = measure_estimate_uncertainty(
            np.zeros((0, 0), dtype=float),
            pairwise_average_correlation_statistics(),
            {"avg_pairwise_correlation": avg_pairwise_correlation},
            scope=(
                "risk_score.avg_pairwise_correlation: the finite upper-triangle "
                "Pearson correlations of this section's own constituent return "
                "frame"
            ),
            point_tolerance=RISK_SCORE_PUBLISHED_DP_TOLERANCE,
            not_computed={
                "avg_pairwise_correlation": (
                    "not computed: no average pairwise correlation was measured "
                    "for this score, so there is no number to put an interval "
                    "around. A single-leg book has no pair to correlate, and an "
                    "unmeasured leg is excluded from the weighted score rather "
                    "than scored zero (see score_audit.excluded_reasons)"
                )
            },
            notes={"estimator": RISK_SCORE_PAIRWISE_ESTIMATOR_BASIS},
        )
    else:
        correlation_block = measure_estimate_uncertainty(
            frame.to_numpy(dtype=float),
            pairwise_average_correlation_statistics(),
            {"avg_pairwise_correlation": avg_pairwise_correlation},
            scope=(
                "risk_score.avg_pairwise_correlation: the finite upper-triangle "
                "Pearson correlations of this section's own constituent return "
                "frame"
            ),
            # Published at RISK_SCORE_STATISTIC_DECIMALS dp, so half a display
            # step is the floor; the margin above it absorbs the restatement's
            # float noise without admitting a different estimator.
            point_tolerance=RISK_SCORE_PUBLISHED_DP_TOLERANCE,
            # The pairwise restatement is O(rows x draws x pairs), so a very wide
            # book reduces the DRAW COUNT rather than being measured at any
            # cost.  The count is published as bootstrap_resamples, so a reduced
            # one is visible and the band stays reproducible.
            resamples=pairwise_resample_count(len(columns) * (len(columns) - 1) // 2),
            # The leg's own statistic is PAIRWISE COMPLETE, because that is what
            # `returns.corr()` is.  The default complete-case filter would drop
            # every row a late-listed leg was unpriced on and measure the mean
            # over the remaining subset - a different number, which the
            # reproduction guard would then (correctly) refuse to band.
            row_filter=RISK_SCORE_PAIRWISE_ROW_FILTER,
            row_filter_basis=RISK_SCORE_PAIRWISE_ROW_FILTER_BASIS,
            notes={
                "estimator": RISK_SCORE_PAIRWISE_ESTIMATOR_BASIS,
                "pair_count": len(columns) * (len(columns) - 1) // 2,
                "resample_count_rule": RISK_SCORE_PAIRWISE_RESAMPLE_RULE,
                "constituent_count": len(columns),
                "constituents": columns,
                "constituent_finite_observations": {
                    str(column): int(np.isfinite(
                        frame[column].to_numpy(dtype=float)
                    ).sum())
                    for column in frame.columns
                },
                "effective_n_basis_note": (
                    "effective_n is this payload's payload-wide Quenouille/Bartlett "
                    "AR(1) adjustment, measured on the FIRST column of the block "
                    f"({columns[0] if columns else None}) by the shared "
                    "convention in autocorrelation_disclosure. The resampling "
                    "interval above already accounts for serial dependence "
                    "directly, because contiguous blocks are resampled; "
                    "effective_n is the naive-n comparison, not the interval's "
                    "width"
                ),
            },
        )
    estimated["avg_pairwise_correlation"] = correlation_block

    # --- the factor leg's input, measured on the regression's own sample
    regression_frame, fit_window, frame_reason = _factor_regression_frame(
        frame, benchmark_data, dict(weights or {})
    )
    fit_observations = None
    if isinstance(factor_result, Mapping):
        portfolio_fit = factor_result.get("portfolio")
        if isinstance(portfolio_fit, Mapping):
            fit_observations = portfolio_fit.get("observations")
    factor_notes: Dict[str, Any] = {
        "estimator": (
            "regression_r_squared_statistics: Sxy^2 / (Sxx * Syy) on centred "
            "sums, which is what statsmodels' rsquared is for a simple "
            "regression with an intercept, so the resampled values belong to "
            "the published R-squared"
        ),
        "sample": (
            "the (portfolio return, benchmark return) pairs the fit was run on, "
            "paired BY DATE through the same alignment the factor regression "
            "uses: the shared index, the coverage-gated portfolio aggregate, "
            "and only dates that aggregate actually published"
        ),
        "fit_observation_count": fit_observations,
        "fit_observation_count_scope": "portfolio_vs_benchmark_ols_rows",
        "fit_observation_count_matches_frame": (
            None if fit_observations is None
            else bool(int(fit_observations) == int(regression_frame.shape[0]))
        ),
        "fit_window": fit_window,
    }
    if frame_reason:
        factor_notes["frame_unavailable_reason"] = frame_reason
    if isinstance(factor_result, Mapping) and factor_result.get("adjusted_r_squared") is not None:
        # The SAME fit's adjusted R-squared, published beside the band: it needs
        # no resampling of its own to be a real measurement, and at this sample
        # size it is the number that says whether the fit is more than the
        # intercept. It is published as a mapping that DECLARES its own window
        # and observation count rather than as a bare number, because a fit
        # statistic without the sample it was fitted on cannot be compared with
        # the same model's fit over a different window - which is the whole
        # reason the adjusted value is worth publishing at all.
        factor_notes["adjusted_r_squared_fit"] = {
            "adjusted_r_squared": factor_result.get("adjusted_r_squared"),
            "model_window": fit_window if (fit_window or {}).get("declared") else None,
            "model_observation_count": fit_observations,
            "model_observation_count_scope": "portfolio_vs_benchmark_ols_rows",
            "basis": RISK_SCORE_ADJUSTED_R_SQUARED_BASIS,
            "same_fit_as": (
                "score_audit.precision.estimated_statistics.factor_r_squared"
            ),
        }
    if isinstance(factor_result, Mapping):
        portfolio_fit = factor_result.get("portfolio")
        if isinstance(portfolio_fit, Mapping) and portfolio_fit.get("market_std_error") is not None:
            factor_notes["market_beta_std_error"] = portfolio_fit.get("market_std_error")
            factor_notes["market_beta_std_error_basis"] = (
                f"the fit's own coefficient standard error ({portfolio_fit.get('std_error_basis')}"
                f"{', robust' if portfolio_fit.get('std_error_robust') else ''}), "
                "published here because it is the only standard error this "
                "regression computed. It belongs to the beta coefficient, NOT "
                "to R-squared: no standard error for R-squared itself is "
                "published, and none is invented from the coefficient's"
            )
    # Declared absences are declared per FIELD and only for a field with no
    # point: a reason attached to a field that WAS measured would suppress its
    # band and mislabel a real measurement as an unmeasured one.
    declared_factor: Dict[str, str] = {}
    if factor_r_squared is None:
        declared_factor["factor_r_squared"] = frame_reason or (
            "not computed: no benchmark R-squared was measured for this score, "
            "so there is no number to put an interval around. The leg is "
            "excluded from the weighted score and the remaining legs "
            "renormalized rather than scored from an assumed R-squared of zero "
            "(see score_audit.excluded_reasons)"
        )
    estimated["factor_r_squared"] = measure_estimate_uncertainty(
        regression_frame,
        regression_r_squared_statistics(),
        {"factor_r_squared": factor_r_squared},
        scope=(
            "risk_score.factor_r_squared: the portfolio-vs-benchmark OLS fit's "
            "own paired sample, resampled jointly"
        ),
        point_tolerance=RISK_SCORE_PUBLISHED_DP_TOLERANCE,
        not_computed=declared_factor,
        notes=factor_notes,
    )

    # --- the legs: derived from one published input, so they inherit
    derived: Dict[str, Any] = {}
    for name in RISK_SCORE_WEIGHTS:
        spec = RISK_SCORE_LEG_SPECS[name]
        input_statistic = str(spec["input_statistic"])
        entry = audit_components.get(name) or {}
        inherits_at = RISK_SCORE_INPUT_PRECISION_AT.get(input_statistic)
        # One reason string, built once, and used for BOTH the standard error and
        # the interval.  The two were previously formatted separately from the
        # same template with different fallbacks, so a leg could publish two
        # differently-worded statements about the same absent interval.
        no_interval_reason = _risk_score_derived_no_interval_reason(
            leg=name,
            input_statistic=input_statistic,
            input_value=entry.get("input_statistic_value"),
            provenance=entry.get("input_statistic_provenance"),
            inherits_at=inherits_at,
        )
        derived[name] = {
            "classification": "deterministic_derivation",
            "published_value_at": f"components.{name}",
            "sub_score": entry.get("sub_score"),
            "formula": spec["formula"],
            "input_statistic": input_statistic,
            "input_statistic_value": entry.get("input_statistic_value"),
            "input_statistic_provenance": entry.get("input_statistic_provenance"),
            "inherits_precision_from": input_statistic,
            "inherits_precision_at": inherits_at,
            "standard_error": None,
            "standard_error_reason": no_interval_reason,
            "conf_int": None,
            "conf_int_reason": no_interval_reason,
        }

    declared = {
        "classification": "declared_constant",
        "table": RISK_SCORE_WEIGHT_TABLE,
        "table_identifier": "RISK_SCORE_WEIGHTS",
        "published_at": [
            "score_audit.nominal_weights",
            "score_audit.nominal_weight_total",
            "score_audit.components.<component>.nominal_weight",
            "score_audit.components.<component>.effective_weight",
        ],
        "basis": RISK_SCORE_DECLARED_CONSTANT_BASIS,
        "nominal_weights": dict(RISK_SCORE_WEIGHTS),
        "effective_weights": {
            name: (audit_components.get(name) or {}).get("effective_weight")
            for name in RISK_SCORE_WEIGHTS
        },
        "renormalization": (
            "a leg that could not be measured is dropped and the remaining "
            "weights are renormalized, so an effective weight is the nominal "
            "weight of a MEASURED leg rescaled; it is still a declared "
            "constant, and it moves only when a leg is excluded"
        ),
        "standard_error": None,
        "standard_error_reason": RISK_SCORE_DECLARED_NO_STANDARD_ERROR_REASON,
        "conf_int": None,
        "conf_int_reason": RISK_SCORE_DECLARED_NO_STANDARD_ERROR_REASON,
    }

    attribution = {
        "classification": "deterministic_derivation",
        "published_at": (
            "score_audit.effective_information.headline_attribution"
        ),
        "formula": (
            "unrounded sub_score x effective_weight (see "
            "score_audit.effective_information.headline_attribution_note)"
        ),
        "inherits_precision_from": [
            f"score_audit.components.{name}.sub_score" for name in RISK_SCORE_WEIGHTS
        ] + [
            f"score_audit.nominal_weights.{name}" for name in RISK_SCORE_WEIGHTS
        ],
        "standard_error": None,
        "standard_error_reason": (
            "not computed: a headline contribution is a product of a derived "
            "sub-score and a declared weight, so its precision is the "
            "sub-score's (inherited, see score_audit.precision.derived_values) "
            "and the weight's is nil. It is arithmetic on two published "
            "numbers, not a third measurement, and it is published at full "
            "precision because the payload is expected to be exactly "
            "recomputable from its inputs"
        ),
        "conf_int": None,
        "conf_int_reason": (
            "not computed: see standard_error_reason - a product of two "
            "published numbers has no sampling distribution of its own"
        ),
    }

    return {
        "basis": RISK_SCORE_PRECISION_BASIS,
        "classes": {
            "estimated_statistics": (
                "measured from data on this section's own sample; carries a "
                "resampling standard error, an interval and an effective n"
            ),
            "deterministic_derivation": (
                "a published function of published numbers; carries no "
                "standard error of its own and inherits the precision of the "
                "input it names"
            ),
            "declared_constant": (
                "chosen by design; carries no standard error and no interval, "
                "because it was never estimated"
            ),
        },
        "estimated_statistics": estimated,
        "derived_values": derived,
        "declared_constants": declared,
        "headline_attribution": attribution,
        "rule_limitation": RISK_SCORE_RULE_LIMITATION,
    }


def _risk_score_composition_alerts(audit: Mapping[str, Any]) -> List[str]:
    """Alerts for the legs that are not what a five-component map implies.

    The `components` map is read as five independent measurements; these lines
    are where it stops being one.
    """
    alerts: List[str] = []
    components = audit.get("components") or {}
    information = audit.get("effective_information") or {}

    for entry in audit.get("duplicate_components") or []:
        leg = entry.get("component")
        detail = components.get(leg) or {}
        alerts.append(
            f"{leg} is not independent evidence: on this sample it is "
            f"{entry.get('relation')} to {entry.get('duplicate_of')} "
            f"({detail.get('duplicate_reason')})"
        )

    for leg in audit.get("saturated_components") or []:
        detail = components.get(leg) or {}
        share = (
            f"; it carries {detail.get('headline_share')} of the headline"
            if detail.get("headline_share") is not None
            else ""
        )
        alerts.append(
            f"{leg} is pinned at the {RISK_SCORE_CAP:g}-point cap: its input "
            f"{detail.get('input_statistic')} = {detail.get('input_statistic_value')} "
            f"is {detail.get('cap_binds_when_input_is')}, so the leg could only "
            f"move if that input reached {detail.get('unpin_condition')}{share}"
        )

    for leg in audit.get("floor_clamped_components") or []:
        detail = components.get(leg) or {}
        alerts.append(
            f"{leg} is clamped at the {RISK_SCORE_FLOOR:g}-point floor: its input "
            f"{detail.get('input_statistic')} = "
            f"{detail.get('input_statistic_value')} is "
            f"{detail.get('floor_binds_when_input_is')}, and the floor added "
            f"{detail.get('floor_clamp_points')} points this scale cannot "
            f"express as negative risk (the measurement itself is "
            f"unchanged)"
        )

    responsive = information.get("responsive_weight")
    if responsive is not None and responsive < 1.0 - 1e-9:
        alerts.append(
            f"only {responsive:g} of the headline weight is carried by legs that "
            f"are distinct, measured and off their cap; the remaining "
            f"{round(1.0 - float(responsive), 6):g} is pinned, duplicated or "
            f"unmeasured (see score_audit.effective_information)"
        )
    return alerts


def _stress_holding_co_movement(returns: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """How far each holding actually co-moved with the rest of the book.

    WHY THIS IS A DIAGNOSTIC AND NOT THE SHOCK'S ELASTICITY.

    The scenario table's ``Exchange Traded Fund`` entry is a flat 1.00-1.05 for
    every holding in that bucket, which asserts that a US-listed mega-cap
    technology fund moves exactly as much as a domestic broad index tracker in
    a -35% NIFTY crash.  The bucket is the route's *unclassified* bucket and
    this repository carries no per-holding classification that could separate
    its members, so a per-instrument constant would be a fabricated input
    wearing a table's clothes -- the same defect in a new place.

    The obvious cheap substitute is to regress each holding on the rest of the
    book and use that coefficient as the elasticity.  It is measurable here, and
    it is the WRONG statistic, and the reason is worth recording because it is
    not obvious: this coefficient measures co-movement *within the delivered
    book*, which is a diversification fact, not a market sensitivity.  On four
    mutually uncorrelated holdings it returns 0.13, 0.02, 0.04 and -0.07, so
    applying it to a -10% market shock publishes a ~0% loss on a market crash
    and a GAIN on one of them.  A holding that happens not to co-move with the
    rest of THIS book is not thereby insulated from the market; it may be more
    exposed to it.  Substituting it for a market beta would ship a new
    undeclared floor in place of an undeclared constant.

    So it is published as what it is -- a measurement that makes the flat table
    entry checkable, with the reference, the row count and the coefficient for
    every holding -- and NOT applied to any shock.  A real per-holding market
    beta needs a benchmark series delivered to `stress_test`, and separating the
    members of the bucket by what they track needs a classification this
    repository does not carry.  Both are reported, neither is guessed.

    Leave-one-out on purpose: the reference is the equal-weighted mean of the
    OTHER holdings, so a holding is never regressed on a reference containing
    itself.  With fewer than
    :data:`STRESS_CO_MOVEMENT_MIN_REFERENCE_LEGS` constituents the reference
    degenerates -- on a two-name book each holding is the other's reference and
    both coefficients are exactly 1.0 by construction -- so the value is
    published unavailable with the reason rather than dressed up as measured.
    """
    result: Dict[str, Dict[str, Any]] = {}
    if not isinstance(returns, pd.DataFrame) or returns.empty:
        return result

    for ticker in returns.columns:
        others = [c for c in returns.columns if c != ticker]
        entry: Dict[str, Any] = {
            "co_movement": None,
            "co_movement_basis": None,
            "co_movement_unavailable_reason": None,
            "reference": "equal_weighted_mean_of_the_other_holdings_returns",
            "reference_leg_count": len(others),
            "observations": int(returns[ticker].notna().sum()),
        }
        if len(others) < STRESS_CO_MOVEMENT_MIN_REFERENCE_LEGS:
            entry["co_movement_unavailable_reason"] = (
                f"only {len(others)} other holding(s) in the delivered frame, "
                f"fewer than the {STRESS_CO_MOVEMENT_MIN_REFERENCE_LEGS} a "
                f"reference needs; on a two-name book the leave-one-out "
                f"coefficient is 1.0 by construction, which is arithmetic "
                f"rather than a measurement"
            )
            result[ticker] = entry
            continue

        reference = returns[others].mean(axis=1, skipna=True)
        paired = pd.concat(
            [returns[ticker].rename("holding"), reference.rename("reference")],
            axis=1,
        ).dropna()
        rows = int(len(paired))
        entry["paired_observations"] = rows
        if rows < STRESS_CO_MOVEMENT_MIN_OBSERVATIONS:
            entry["co_movement_unavailable_reason"] = (
                f"{rows} paired daily returns against a minimum of "
                f"{STRESS_CO_MOVEMENT_MIN_OBSERVATIONS}"
            )
            result[ticker] = entry
            continue

        holding_values = paired["holding"].to_numpy(dtype=float)
        reference_values = paired["reference"].to_numpy(dtype=float)
        centred_holding = holding_values - holding_values.mean()
        centred_reference = reference_values - reference_values.mean()
        denominator = float(centred_reference @ centred_reference)
        if not np.isfinite(denominator) or denominator <= 0.0:
            entry["co_movement_unavailable_reason"] = (
                "the reference series has no dispersion over the paired rows, "
                "so a coefficient against it is not defined"
            )
            result[ticker] = entry
            continue

        coefficient = float((centred_holding @ centred_reference) / denominator)
        if not np.isfinite(coefficient):
            entry["co_movement_unavailable_reason"] = (
                "the coefficient against the reference series is not a finite "
                "number"
            )
            result[ticker] = entry
            continue

        entry["co_movement"] = round(coefficient, 4)
        entry["co_movement_basis"] = STRESS_CO_MOVEMENT_BASIS
        result[ticker] = entry
    return result


class AnalyticsEngine:
    """
    Comprehensive analytics engine for portfolio risk calculations
    """
    
    def __init__(self):
        self.risk_free_rate = settings.risk_free_rate  # Settings default: 2% annual
        
    async def calculate_portfolio_metrics(
        self, 
        price_data: pd.DataFrame, 
        weights: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive portfolio metrics using real price data
        
        Args:
            price_data: DataFrame with Date index and ticker columns containing prices
            weights: Dictionary mapping tickers to portfolio weights
            
        Returns:
            Dictionary with all portfolio metrics
        """
        try:
            if price_data.empty or price_data.shape[1] == 0:
                logger.warning("Empty price data provided")
                return self._empty_metrics()
            
            # Preserve the active-price mask.  Back-filling a newly listed
            # instrument with its first future price creates a flat synthetic
            # history; zero-filling the resulting gaps creates a different
            # synthetic history.  Returns remain NaN until both endpoints of a
            # price observation are available.
            cleaned_prices = price_data.replace([np.inf, -np.inf], np.nan).sort_index()
            returns = cleaned_prices.pct_change(fill_method=None)
            if returns.empty or len(returns) < 2:
                return self._empty_metrics()
            returns = returns.iloc[1:]

            # Handle only finite, strictly positive weights.  A date becomes a
            # portfolio return only when the whole declared book traded that
            # day; short dates are dropped rather than renormalised, so the
            # series is never a moving basket published under one name.
            if weights is None:
                weights = {col: 1.0 / len(returns.columns) for col in returns.columns}
            else:
                weights = {
                    key: float(value)
                    for key, value in weights.items()
                    if key in returns.columns
                    and np.isfinite(float(value))
                    and float(value) > 0.0
                }
                weight_sum = sum(weights.values())
                if weight_sum <= 0:
                    return self._empty_metrics()
                weights = {key: value / weight_sum for key, value in weights.items()}

            coverage = portfolio_return_coverage_block(returns, weights)
            portfolio_returns = self._calculate_portfolio_returns(returns, weights)
            if portfolio_returns.empty:
                return self._empty_metrics()

            metrics = {
                "observations": int(len(portfolio_returns)),
                "active_observations": int(len(portfolio_returns)),
                "portfolio_return_coverage": coverage,
            }
            metrics.update(self._calculate_basic_metrics(portfolio_returns))
            metrics.update(self._calculate_risk_metrics(portfolio_returns))
            metrics.update(self._calculate_drawdown_metrics(portfolio_returns))
            metrics.update(self._calculate_return_distribution(portfolio_returns))
            # SI-5: the twelve numbers above were all naked point estimates.
            # This block is the one place the whole realized-risk family states
            # its precision, so the route forwards it verbatim and no consumer
            # has to reconstruct it per field.
            metrics["estimate_uncertainty"] = self._estimate_uncertainty_block(
                portfolio_returns,
                metrics,
                scope=(
                    "realized_risk portfolio block: the published portfolio "
                    "return observations every metric in this block was "
                    "computed from"
                ),
            )

            # Position-level metrics using active price series
            metrics['positions'] = self._calculate_position_metrics(returns, weights, raw_prices=price_data)

            return metrics
            
        except Exception as e:
            logger.error(f"Error calculating portfolio metrics: {e}")
            return self._empty_metrics()
    
    async def forecast_volatility(
        self, 
        returns: pd.Series, 
        model: str = "GARCH", 
        horizon: int = 1,
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Forecast volatility using specified model
        
        Args:
            returns: Series of returns
            model: Model type (GARCH, EGARCH, EWMA)
            horizon: Forecast horizon in days
            params: Model parameters
            
        Returns:
            Dictionary with forecast results
        """
        try:
            if len(returns) < 30:  # Need sufficient data
                return self._empty_forecast(model=model.upper())
            
            if model.upper() == "GARCH":
                return await self._garch_forecast(returns, horizon)
            elif model.upper() == "EGARCH":
                return await self._egarch_forecast(returns, horizon)
            elif model.upper() == "EWMA":
                return self._ewma_forecast(returns, horizon)
            else:
                return await self._garch_forecast(returns, horizon)
                
        except Exception as e:
            logger.error(f"Error in volatility forecast: {e}")
            return self._empty_forecast(model=model.upper())
    
    async def factor_exposure_analysis(
        self, 
        price_data: pd.DataFrame, 
        benchmark_data: Optional[pd.Series] = None,
        weights: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Perform factor exposure analysis
        
        Args:
            price_data: Price data for assets
            benchmark_data: Benchmark returns (or prices) for comparison
            weights: Portfolio weights dictionary
            
        Returns:
            Dictionary with factor exposures (alpha, market beta, r_squared)
        """
        try:
            if price_data.empty or len(price_data.columns) == 0:
                return self._empty_factor_exposure()
            
            # Keep raw NaN so the regression active mask can separate
            # pre-listing gaps from genuine 0% return days.
            returns = price_data.sort_index().pct_change(fill_method=None)
            if returns.empty or len(returns) < 2:
                return self._empty_factor_exposure()
            returns = returns.iloc[1:]

            if weights is None:
                eq = 1.0 / len(returns.columns)
                weights = {col: eq for col in returns.columns}
            else:
                w_sum = sum(weights.values())
                if w_sum > 0:
                    weights = {k: v / w_sum for k, v in weights.items()}
                else:
                    eq = 1.0 / len(returns.columns)
                    weights = {col: eq for col in returns.columns}
            
            # Benchmark returns
            if benchmark_data is None or benchmark_data.empty:
                benchmark_returns = pd.Series(dtype=float)
            else:
                if (benchmark_data.abs() > 1.0).any():
                    benchmark_returns = benchmark_data.pct_change(fill_method=None).dropna()
                else:
                    benchmark_returns = benchmark_data.dropna()
            
            exposures_result = self._calculate_factor_exposures(returns, benchmark_returns, weights)
            results = {
                'portfolio': exposures_result.get('portfolio') or {'alpha': None, 'market': None},
                'positions': exposures_result.get('positions', {}),
                'r_squared': exposures_result.get('r_squared'),
                'adjusted_r_squared': exposures_result.get('adjusted_r_squared'),
            }
            if exposures_result.get('error'):
                results['error'] = exposures_result['error']
            return results
            
        except Exception as e:
            logger.error(f"Error in factor exposure analysis: {e}")
            return self._empty_factor_exposure()
    
    async def concentration_analysis(
        self, 
        weights: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Analyze portfolio concentration
        
        Args:
            weights: Portfolio weights by asset
            
        Returns:
            Dictionary with concentration metrics
        """
        try:
            if not weights:
                return self._empty_concentration()

            # Zero/negative/non-finite rows are not active holdings and must
            # not dilute the HHI denominator or diversification baseline.
            weights = {
                key: float(value)
                for key, value in weights.items()
                if np.isfinite(float(value)) and float(value) > 0.0
            }
            if not weights:
                return self._empty_concentration()
            
            # Normalize weights
            weight_sum = sum(weights.values())
            if weight_sum > 0:
                weights = {k: v/weight_sum for k, v in weights.items()}
            else:
                return self._empty_concentration()
            
            weights_array = np.array(list(weights.values()))
            
            # Calculate concentration metrics
            largest_position = np.max(weights_array)
            top_3 = np.sum(np.sort(weights_array)[-3:])
            top_5 = np.sum(np.sort(weights_array)[-5:])
            top_10 = np.sum(np.sort(weights_array)[-10:]) if len(weights_array) >= 10 else 1.0
            
            # Herfindahl Index
            herfindahl = float(np.sum(weights_array ** 2))
            
            # Effective number of positions
            effective_positions = float(1 / herfindahl if herfindahl > 0 else len(weights))
            
            # Diversification score (normalized against theoretical maximum 1 - 1/N)
            n_assets = len(weights)
            diversification_score = float(((1 - herfindahl) / (1 - 1/n_assets)) * 100) if n_assets > 1 else 0.0
            diversification_ratio = float(effective_positions / n_assets) if n_assets > 0 else 1.0
            
            # Gini Inequality Coefficient
            sorted_w = np.sort(weights_array)
            gini = float((2 * np.sum((np.arange(1, n_assets + 1) * sorted_w)) - (n_assets + 1)) / n_assets) if n_assets > 1 else 0.0

            return {
                "largest_position": float(largest_position),
                "top_3": float(top_3),
                "top_5": float(top_5),
                "top_10": float(top_10),
                "herfindahl_index": round(herfindahl, 4),
                "effective_positions": round(effective_positions, 2),
                "diversification_score": round(diversification_score, 1),
                "diversification_ratio": round(diversification_ratio, 2),
                "gini_coefficient": round(gini, 3),
                # The score and the ratio above are on different scales built
                # from the same index, and neither could be evaluated without
                # the holding count, so all four are published here rather than
                # left to be reconstructed from `by_weight` by a reader.
                "n_holdings": n_assets,
                "scale": dict(CONCENTRATION_DIVERSIFICATION_SCALE),
                "diversification_score_formula": (
                    CONCENTRATION_DIVERSIFICATION_SCORE_FORMULA
                ),
                "diversification_ratio_formula": (
                    CONCENTRATION_DIVERSIFICATION_RATIO_FORMULA
                ),
                "effective_positions_note": CONCENTRATION_EFFECTIVE_POSITIONS_NOTE,
                "by_weight": dict(sorted(weights.items(), key=lambda x: x[1], reverse=True))
            }
            
        except Exception as e:
            logger.error(f"Error in concentration analysis: {e}")
            return self._empty_concentration()
    
    async def liquidity_analysis(
        self, 
        price_data: Dict[str, pd.DataFrame],
        market_caps: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Analyze portfolio liquidity using turnover (volume * price), market cap, and empirical spreads.

        The published `score` is the raw tier score rounded once, and the
        category, liquidation window and high/medium/low counts are all derived
        from that published score through `LIQUIDITY_SCORE_BAND_RULE`, which is
        returned with the result so the threshold is discoverable.  A market cap
        that was annualised from turnover or floored at INR 1bn is reported with
        its provenance and `is_estimate=True` instead of passing as measured.

        Args:
            price_data: Dictionary mapping tickers to price DataFrames
            market_caps: Optional mapping of tickers to market cap in INR
            
        Returns:
            Dictionary with liquidity metrics
        """
        try:
            if not price_data:
                return self._empty_liquidity()
            
            liquidity_scores = {}
            volume_stats = {'volumes': [], 'total_volume': 0}
            
            for ticker, df in price_data.items():
                if df is None or df.empty:
                    continue
                
                vol_col = 'Volume' if 'Volume' in df.columns else ('volume' if 'volume' in df.columns else None)
                close_col = 'Close' if 'Close' in df.columns else ('close' if 'close' in df.columns else None)
                
                if not vol_col:
                    continue
                
                # Calculate liquidity score based on volume, price, and daily turnover
                volume = float(df[vol_col].mean())
                price = float(df[close_col].iloc[-1]) if close_col and not df.empty else 0.0
                daily_turnover = volume * price

                # Market cap / AUM dynamic resolution, with its provenance.  A
                # missing or unusable cap is never allowed to look measured: the
                # annualised-turnover substitute and the INR 1bn floor are both
                # reported as estimates, because that is what they are.
                mc, mc_provenance, mc_source = _market_cap_provenance(
                    (market_caps or {}).get(ticker), daily_turnover
                )

                # Institutional Turnover & Market Cap Liquidity Scoring (0 - 10)
                # Tier 1: Mega / Large Turnover (> 50 Cr/day) or Mega Cap (> 50,000 Cr)
                if daily_turnover >= 500000000.0 or mc >= 500000000000.0:
                    score_raw = min(10.0, 9.0 + min(1.0, (daily_turnover / 1e9) * 0.2))
                    spread = round(max(0.0002, 0.0006 - min(0.0003, (daily_turnover / 2e9) * 0.0003)), 4)
                # Tier 2: Liquid Midcap / Top ETF (Turnover 10 Cr - 50 Cr/day) or Cap 10,000 Cr - 50,000 Cr
                elif daily_turnover >= 100000000.0 or mc >= 100000000000.0:
                    score_raw = min(8.9, 7.8 + (daily_turnover / 5e8) * 1.1)
                    spread = round(max(0.0006, 0.0014 - (daily_turnover / 5e8) * 0.0006), 4)
                # Tier 3: Moderate Turnover (Turnover 2 Cr - 10 Cr/day)
                elif daily_turnover >= 20000000.0 or mc >= 10000000000.0:
                    score_raw = min(7.7, 6.2 + (daily_turnover / 1e8) * 0.15)
                    spread = round(max(0.0012, 0.0028 - (daily_turnover / 1e8) * 0.0012), 4)
                # Tier 4: Smallcap / Lower Turnover (< 2 Cr/day)
                else:
                    score_raw = max(2.5, min(5.9, 3.0 + (daily_turnover / 2e7) * 2.9))
                    spread = round(max(0.0025, 0.0060 - (daily_turnover / 2e7) * 0.0030), 4)

                # Round once, then band the published score.  Banding the raw
                # score is what let a raw 7.96 publish score=8.0 as "Medium".
                score = round(float(score_raw), LIQUIDITY_SCORE_PRECISION)
                category, liquidation_days = _liquidity_band(score)

                liquidity_scores[ticker] = {
                    'score': score,
                    'score_raw': round(float(score_raw), 6),
                    'avg_volume': volume,
                    'avg_turnover': daily_turnover,
                    'market_cap': mc,
                    'market_cap_provenance': mc_provenance,
                    'market_cap_source': mc_source,
                    'is_estimate': mc_provenance in ('estimated', 'fallback'),
                    'category': category,
                    'spread': spread,
                    'liquidation_days': liquidation_days
                }
                
                volume_stats['volumes'].append(volume)
                volume_stats['total_volume'] += volume
            
            # Calculate overall metrics
            if liquidity_scores:
                published_scores = [data['score'] for data in liquidity_scores.values()]
                overall_score_raw = float(np.mean(published_scores))
                overall_score = round(overall_score_raw, LIQUIDITY_SCORE_PRECISION)
                avg_volume = float(np.mean(volume_stats['volumes'])) if volume_stats['volumes'] else 0.0

                # Volume & Score distribution: buckets follow the same published
                # score band as `category`, so a position cannot be "High" here
                # and "Medium" there.
                bands = [_liquidity_band(value)[0] for value in published_scores]
                high_count = bands.count("High")
                medium_count = bands.count("Medium")
                low_count = bands.count("Low")
                total_positions = len(liquidity_scores)
                
                volume_pct = lambda x: (x / total_positions * 100.0) if total_positions > 0 else 0.0
                
                # Liquidation time and risk level come from the same band rule
                overall_band, liquidation_time = _liquidity_band(overall_score)
                risk_level = LIQUIDITY_BAND_RISK_LEVEL[overall_band]
                
                return {
                    "overall_score": overall_score,
                    "overall_score_raw": round(overall_score_raw, 6),
                    "liquidation_time_days": liquidation_time,
                    "risk_level": risk_level,
                    "overall_band": overall_band,
                    "score_band_rule": dict(LIQUIDITY_SCORE_BAND_RULE),
                    "by_position": liquidity_scores,
                    "volume_stats": {
                        "avg_volume": avg_volume,
                        "total_portfolio_volume": volume_stats['total_volume'],
                        "high_volume_pct": round(volume_pct(high_count), 1),
                        "medium_volume_pct": round(volume_pct(medium_count), 1),
                        "low_volume_pct": round(volume_pct(low_count), 1)
                    }
                }
            else:
                return self._empty_liquidity()
                
        except Exception as e:
            logger.error(f"Error in liquidity analysis: {e}")
            return self._empty_liquidity()
    
    async def stress_test(
        self, 
        price_data: pd.DataFrame, 
        weights: Dict[str, float], 
        scenario: str,
        sectors: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Run multi-factor sector-elastic stress test scenario

        This is a deterministic factor shock proxy, not a simulation: no price
        paths are sampled, `max_drawdown` is `portfolio_impact * 1.15` on that
        same proxy, and `confidence_level` is a nominal label.  Every published
        figure therefore ships with a `*_basis` tag, the `shock_inputs` it was
        built from, and its `units`, so a reader cannot read a proxy as a
        simulated statistic (V3-10).

        Args:
            price_data: Historical price data
            weights: Portfolio weights
            scenario: Stress scenario name
            sectors: Optional dictionary mapping ticker to sector
            
        Returns:
            Dictionary with stress test results
        """
        try:
            if price_data.empty or not weights:
                return self._empty_stress_test()
            
            scenario_key = (scenario or "").lower().strip().replace(" ", "_").replace("-", "_")

            # Multi-Factor Macro & Sector Elasticity Matrix
            scenarios_config = {
                "market_crash": {
                    "market_shock": -0.35, 
                    "recovery_months": 24, 
                    "description": "Global Financial Crisis / Severe Market Crash (-35% NIFTY shock)",
                    "sectors": {
                        "Healthcare": 0.55, "Utilities": 0.50, "Technology": 1.10,
                        "Financial Services": 1.45, "Consumer Cyclical": 1.55, "Industrials": 1.40,
                        "Exchange Traded Fund": 1.00
                    }
                },
                "interest_rate_shock": {
                    "market_shock": -0.15, 
                    "recovery_months": 9, 
                    "description": "300bp RBI / Global Central Bank Interest Rate Hike (-15% shock)",
                    "sectors": {
                        "Healthcare": 0.50, "Utilities": 0.70, "Technology": 1.10,
                        "Financial Services": 1.50, "Consumer Cyclical": 1.35, "Industrials": 1.40,
                        "Exchange Traded Fund": 1.00
                    }
                },
                "volatility_spike": {
                    "market_shock": -0.22, 
                    "recovery_months": 5, 
                    "description": "COVID-19 style VIX > 40 Sudden Volatility Spike (-22% shock)",
                    "sectors": {
                        "Healthcare": 0.40, "Utilities": 0.55, "Technology": 0.95,
                        "Financial Services": 1.30, "Consumer Cyclical": 1.50, "Industrials": 1.45,
                        "Exchange Traded Fund": 1.05
                    }
                },
                "tech_sector_correction": {
                    "market_shock": -0.18, 
                    "recovery_months": 12, 
                    "description": "Broad Tech & Growth Multiple De-rating (-18% shock)",
                    "sectors": {
                        "Healthcare": 0.25, "Utilities": 0.20, "Technology": 1.80,
                        "Financial Services": 0.50, "Consumer Cyclical": 0.60, "Industrials": 0.45,
                        "Exchange Traded Fund": 0.60
                    }
                },
                "2020_covid": {
                    "market_shock": -0.28, 
                    "recovery_months": 6, 
                    "description": "March 2020 COVID Market Crash",
                    "sectors": {
                        "Healthcare": 0.45, "Utilities": 0.60, "Technology": 0.90,
                        "Financial Services": 1.40, "Consumer Cyclical": 1.50, "Industrials": 1.45,
                        "Exchange Traded Fund": 1.05
                    }
                },
                "2022_inflation": {
                    "market_shock": -0.16, 
                    "recovery_months": 10, 
                    "description": "2022 Global Inflationary Tightening",
                    "sectors": {
                        "Healthcare": 0.60, "Utilities": 0.80, "Technology": 1.50,
                        "Financial Services": 1.10, "Consumer Cyclical": 1.20, "Industrials": 1.10,
                        "Exchange Traded Fund": 1.00
                    }
                },
                "2018_q4": {
                    "market_shock": -0.14, 
                    "recovery_months": 7, 
                    "description": "Q4 2018 Market Correction",
                    "sectors": {
                        "Healthcare": 0.70, "Utilities": 0.50, "Technology": 1.40,
                        "Financial Services": 1.20, "Consumer Cyclical": 1.10, "Industrials": 1.00,
                        "Exchange Traded Fund": 1.00
                    }
                },
            }

            matched_scenario = None
            for k, cfg in scenarios_config.items():
                if scenario_key and (k in scenario_key or scenario_key in k):
                    matched_scenario = (k, cfg)
                    break
            
            if not matched_scenario:
                # Custom shock: parse a signed percentage if present, else fixed -20%
                shock_match = re.search(r'([+-]?\d+(?:\.\d+)?)\s*%', scenario or "")
                custom_shock = float(shock_match.group(1)) / 100.0 if shock_match else -0.20
                shock_basis = (
                    "parsed_from_scenario_text" if shock_match else "default_minus_20pct"
                )
                matched_scenario = ("custom_stress", {
                    "market_shock": custom_shock,
                    "recovery_months": 12,
                    "description": scenario or "Custom Scenario Shock",
                    "sectors": {}
                })
            else:
                shock_basis = "scenario_config"

            sc_name, sc_cfg = matched_scenario
            market_shock = sc_cfg["market_shock"]
            recovery_months = sc_cfg["recovery_months"]
            description = sc_cfg["description"]
            sector_table = sc_cfg.get("sectors", {})

            # Keep the active observation mask; missing prices are not economic
            # zero returns and must not influence the volatility adjustment.
            cleaned_prices = price_data.replace([np.inf, -np.inf], np.nan).sort_index()
            returns = cleaned_prices.pct_change(fill_method=None)
            if returns.empty or len(returns) < 2:
                return self._empty_stress_test()
            returns = returns.iloc[1:]
            
            position_impacts: Dict[str, float] = {}
            weighted_impact = 0.0
            sectors_map = sectors or {}
            instrument_overrides: Dict[str, Any] = {}
            volatility_adjustment: Dict[str, Any] = {}
            sensitivity: Dict[str, Any] = {}
            # One measured co-movement per holding, against the rest of THIS
            # delivered book.  Published as a diagnostic, NOT applied to any
            # shock: it measures diversification within the book, not
            # sensitivity to the market the shock is defined on.  See
            # `_stress_holding_co_movement`.
            holding_co_movement = _stress_holding_co_movement(returns)

            for ticker, weight in weights.items():
                sec = sectors_map.get(ticker, STRESS_UNCLASSIFIED_SECTOR)
                sec_mult = sector_table.get(sec, 1.0)
                elasticity_basis = (
                    "scenario_sector_table" if sec in sector_table
                    else "default_elasticity_1.0"
                )
                
                # Special instrument sensitivity
                if ticker == "MAFANG.NS" and sc_name == "tech_sector_correction":
                    sec_mult = 2.0
                    elasticity_basis = "instrument_override_mafang_tech_correction"
                elif ticker == "MIDCAPIETF.NS" and sc_name in ["market_crash", "volatility_spike"]:
                    sec_mult = 1.30
                    elasticity_basis = "instrument_override_midcap_etf"
                elif ticker == "SELECTIPO.NS":
                    sec_mult = 1.15
                    elasticity_basis = "instrument_override_selectipo"

                if elasticity_basis.startswith("instrument_override"):
                    instrument_overrides[ticker] = {
                        "sector": sec,
                        "sector_elasticity": sec_mult,
                        "basis": elasticity_basis,
                    }

                # What the flat table entry is, per holding, beside the
                # co-movement that was measured for the same holding.  The
                # elasticity above is UNCHANGED: a per-holding market beta is
                # not obtainable here (see
                # `_stress_holding_co_movement`), and the cheap substitute is a
                # different statistic whose use would publish a new undeclared
                # floor.  So the number that shocked this holding is published
                # with its basis, the measurement that contradicts the idea
                # that one sensitivity fits a whole bucket is published beside
                # it, and no fabricated per-instrument beta appears.
                co_movement_entry = holding_co_movement.get(ticker) or {}
                sensitivity[ticker] = {
                    "sector": sec,
                    "sector_is_unclassified_bucket": sec == STRESS_UNCLASSIFIED_SECTOR,
                    "applied_elasticity": round(float(sec_mult), 4),
                    "applied_elasticity_basis": elasticity_basis,
                    "applied_elasticity_is_per_instrument": elasticity_basis.startswith(
                        "instrument_override"
                    ),
                    "co_movement_with_rest_of_book": co_movement_entry.get(
                        "co_movement"
                    ),
                    "co_movement_basis": co_movement_entry.get("co_movement_basis"),
                    "co_movement_reference_leg_count": co_movement_entry.get(
                        "reference_leg_count"
                    ),
                    "co_movement_paired_observations": co_movement_entry.get(
                        "paired_observations"
                    ),
                    "co_movement_unavailable_reason": co_movement_entry.get(
                        "co_movement_unavailable_reason"
                    ),
                    "co_movement_is_used_as_elasticity": False,
                }

                # Idiosyncratic volatility factor adjustment (bounded between 0.85 and 1.25)
                vol_adj = 1.0
                vol_basis = "unavailable_no_price_window"
                if ticker in returns.columns:
                    s = returns[ticker]
                    non_zero = s[s != 0.0].clip(lower=-0.20, upper=0.20)
                    if len(non_zero) >= STRESS_VOL_MIN_OBSERVATIONS:
                        ticker_vol = float(non_zero.std() * np.sqrt(252))
                        vol_adj = (
                            max(STRESS_VOL_ADJ_MIN, min(STRESS_VOL_ADJ_MAX, ticker_vol / STRESS_VOL_REFERENCE))
                            if ticker_vol > 0 else 1.0
                        )
                        vol_basis = (
                            "measured_annualized_volatility_over_reference"
                            if ticker_vol > 0 else "unavailable_zero_dispersion"
                        )
                    else:
                        vol_basis = "unavailable_insufficient_observations"
                volatility_adjustment[ticker] = {
                    "factor": round(float(vol_adj), 4),
                    "basis": vol_basis,
                }

                ticker_impact = float(market_shock * sec_mult * vol_adj)
                ticker_impact = max(-0.75, min(-0.02, ticker_impact)) if market_shock < 0 else ticker_impact
                
                position_impacts[ticker] = round(ticker_impact, 4)
                weighted_impact += ticker_impact * weight

            portfolio_impact = round(weighted_impact, 4)
            max_drawdown = round(portfolio_impact * STRESS_DRAWDOWN_UPLIFT, 4)

            # Who is in the unclassified bucket, what number was applied to all
            # of them, and what was measured about each.  The bucket's NAME says
            # exchange traded fund and its MEMBERSHIP says nothing of the kind:
            # the route fills sectors from the position's stored sector and a
            # NULL one lands here whatever the instrument is.  Publishing the
            # membership, the applied value and the per-holding co-movement is
            # what makes the flat table entry checkable instead of asserted.
            unclassified_members = sorted(
                ticker for ticker, entry in sensitivity.items()
                if entry["sector_is_unclassified_bucket"]
            )
            bucket_static = sector_table.get(STRESS_UNCLASSIFIED_SECTOR)
            bucket_static_text = (
                f"this scenario's flat {float(bucket_static):g} table row for "
                f"that bucket"
                if bucket_static is not None
                else f"the flat {1.0:g} default elasticity, this scenario "
                     f"declares no table row for the bucket"
            )
            bucket_applied = sorted(
                {
                    entry["applied_elasticity"]
                    for entry in sensitivity.values()
                    if entry["sector_is_unclassified_bucket"]
                }
            )
            bucket_co_movement = [
                entry["co_movement_with_rest_of_book"]
                for entry in sensitivity.values()
                if entry["sector_is_unclassified_bucket"]
                and entry["co_movement_with_rest_of_book"] is not None
            ]
            if len(bucket_applied) == 1:
                bucket_applied_text = (
                    f"Every one of them is shocked by the same "
                    f"{bucket_applied[0]:g} elasticity ({bucket_static_text})"
                )
            else:
                bucket_applied_text = (
                    f"The elasticity applied to them is not one number: "
                    f"{sorted(bucket_applied)}, because "
                    f"{sum(1 for e in sensitivity.values() if e['applied_elasticity_is_per_instrument'])} "
                    f"of them carry a named per-instrument override"
                )
            bucket_disclosure = (
                f"'{STRESS_UNCLASSIFIED_SECTOR}' is this engine's UNCLASSIFIED "
                f"sector, not a classification that its "
                f"{len(unclassified_members)} member(s) are exchange traded "
                f"funds: a holding whose stored sector is null lands in it "
                f"whatever the instrument is. Those members are not one thing, "
                f"and the engine publishes no per-holding market, index or "
                f"currency exposure for any of them, so nothing in this payload "
                f"says which market a member tracks. {bucket_applied_text}. "
                + (
                    f"The measured co-movement of the bucket's members with "
                    f"the rest of this book ranges "
                    f"{min(bucket_co_movement):g} to "
                    f"{max(bucket_co_movement):g}, so the single elasticity is "
                    f"not representative of all of them; that co-movement is "
                    f"book diversification, not a market beta, and it is not "
                    f"applied to the shock (see co_movement_is_not_a_market_beta)"
                    if bucket_co_movement
                    else "No member's co-movement with the rest of this book "
                         "could be measured on the delivered frame, so nothing "
                         "here contradicts the single elasticity with a "
                         "measurement."
                )
            )

            # The published drawdown is a fixed 1.15 uplift on the same
            # deterministic factor proxy, and the confidence is a nominal
            # label: neither is a simulated statistic, so the inputs and units
            # ship with the result instead of the word "simulation".
            shock_inputs = {
                "market_shock": market_shock,
                "market_shock_basis": shock_basis,
                "sector_elasticity_table": dict(sector_table),
                "sector_elasticity_basis": "static_configured_table",
                "sector_elasticity_default": 1.0,
                "default_sector": STRESS_UNCLASSIFIED_SECTOR,
                "default_sector_meaning": (
                    "the sector a holding is given when the route supplied "
                    "none (a null stored sector), NOT an asset-class label"
                ),
                "instrument_overrides": instrument_overrides,
                "position_impact_clip": [-0.75, -0.02],
                "position_impact_clip_basis": "configured_bounds_not_simulated",
                "bucket_disclosure": bucket_disclosure,
                "unclassified_bucket_members": unclassified_members,
                "unclassified_bucket_member_count": len(unclassified_members),
                "unclassified_bucket_applied_elasticities": bucket_applied,
                "sector_elasticity_is_one_number_for_the_bucket": (
                    len(bucket_applied) == 1
                ),
                "co_movement": {
                    "basis": STRESS_CO_MOVEMENT_BASIS,
                    "is_applied_to_the_shock": False,
                    "what_it_is": (
                        "each holding's measured co-movement with the "
                        "equal-weighted mean return of the OTHER holdings in "
                        "this delivered frame (leave-one-out, so a holding is "
                        "never regressed on a reference containing itself)"
                    ),
                    "co_movement_is_not_a_market_beta": (
                        "it measures diversification WITHIN this book, not "
                        "sensitivity to the market the shock is defined on. On "
                        "four mutually uncorrelated holdings it returns "
                        "0.13, 0.02, 0.04 and -0.07, so applying it to a -10% "
                        "market shock would publish a ~0% loss on a market "
                        "crash and a gain on one of them. A holding that does "
                        "not co-move with the rest of THIS book is not thereby "
                        "insulated from the market"
                    ),
                    "why_no_per_holding_elasticity_is_published": (
                        "a per-holding market beta needs a benchmark series "
                        "delivered to this function, and separating the "
                        "bucket's members by what they track needs a per-"
                        "position classification. Neither is an input here: "
                        "stress_test is called with a price frame, weights and "
                        "the stored sectors, and the benchmark is delivered to "
                        "the risk-score and factor-exposure calls but not to "
                        "this one. A per-ticker sensitivity table would be the "
                        "same defect in a new place, so none is published"
                    ),
                    "reference": "equal_weighted_mean_of_the_other_holdings_returns",
                    "min_reference_legs": STRESS_CO_MOVEMENT_MIN_REFERENCE_LEGS,
                    "min_paired_observations": STRESS_CO_MOVEMENT_MIN_OBSERVATIONS,
                    "by_ticker": sensitivity,
                },
                "volatility_adjustment": {
                    "basis": "measured_annualized_volatility_over_reference",
                    "reference_annualized_volatility": STRESS_VOL_REFERENCE,
                    "bounds": [STRESS_VOL_ADJ_MIN, STRESS_VOL_ADJ_MAX],
                    "min_observations": STRESS_VOL_MIN_OBSERVATIONS,
                    "return_clip": [-0.20, 0.20],
                    "annualization_trading_days": 252,
                    "by_ticker": volatility_adjustment,
                },
            }
            units = {
                "market_shock": "fraction_return_signed",
                "portfolio_impact": "fraction_of_portfolio_value",
                "position_impacts": "fraction_of_position_value",
                "max_drawdown": "fraction_of_portfolio_value",
                "recovery_time": "months",
                "confidence_level": "unitless_nominal_label",
                "co_movement.by_ticker.co_movement_with_rest_of_book": (
                    "regression_slope_unitless_diagnostic_only"
                ),
                "co_movement.by_ticker.applied_elasticity": (
                    "unitless_multiplier_on_market_shock"
                ),
            }
            methodology = (
                "Deterministic factor shock proxy; no path sampling and no simulation. "
                "position_impact = market_shock * sector_elasticity (a named "
                "instrument override, or this scenario's static table row for the "
                "holding's sector, where an unclassified holding's row is a single "
                "index sensitivity shared by every member of that bucket -- see "
                "shock_inputs.bucket_disclosure) * volatility_adjustment "
                "(measured annualized volatility divided by "
                f"{STRESS_VOL_REFERENCE}, clipped to "
                f"[{STRESS_VOL_ADJ_MIN}, {STRESS_VOL_ADJ_MAX}]) and clipped to "
                "[-0.75, -0.02] for a negative shock; the per-holding "
                "co-movement in shock_inputs.co_movement is measured, published "
                "and NOT applied to any shock, because it is diversification "
                "within this book and not a market beta; portfolio_impact = sum "
                "of position_impact * weight; max_drawdown = portfolio_impact * "
                "1.15, a "
                "fixed uplift on that same proxy, not a simulated peak-to-trough "
                "path; recovery_time is the scenario's configured month estimate, "
                "not a simulated recovery path; confidence_level is a nominal 0.95 "
                "label with no simulated distribution behind it"
            )

            return {
                "scenario": scenario,
                "scenario_description": description,
                "max_drawdown": max_drawdown,
                "max_drawdown_basis": "derived_from_shock_proxy",
                "max_drawdown_formula": f"portfolio_impact * {STRESS_DRAWDOWN_UPLIFT}",
                "portfolio_impact": portfolio_impact,
                "impact_basis": "deterministic_factor_proxy",
                "position_impacts": position_impacts,
                "recovery_time": recovery_months,
                "recovery_time_basis": "configured_recovery_estimate_not_simulated",
                "confidence_level": STRESS_CONFIDENCE_LABEL,
                "confidence_basis": "nominal_label_not_simulated",
                "shock_inputs": shock_inputs,
                "units": units,
                "methodology": methodology
            }
            
        except Exception as e:
            logger.error(f"Error in stress test: {e}")
            return self._empty_stress_test()
    
    @staticmethod
    def _sample_covariance_volatility(
        returns: pd.DataFrame,
        tickers: Sequence[str],
        weight_values: Sequence[float],
    ) -> tuple[Optional[float], Optional[str]]:
        """Annualised volatility of a weighted book on the SAMPLE covariance.

        Returns `(value, unavailable_reason)`; exactly one is not None.  The
        modelling covariance used for inverse-volatility sizing is a
        correlation matrix times recency-weighted marginal volatilities, which
        is a deliberate, smoothable convention -- but it is not the only
        number that can be called "this book's volatility", and publishing one
        of them as a *measurement* while deriving the scale from another is
        how a 15 % target was published beside a realised 22 %.  This is the
        convention that reconciles with the rest of the artifact (it is the one
        `risk_contribution` and `realized_risk` use), so it is what
        `achieved_volatility` now reports.
        """
        if not isinstance(returns, pd.DataFrame) or returns.empty:
            return None, "no return history for the measured legs"
        available = [t for t in tickers if t in returns.columns]
        if not available:
            return None, "no measured leg is present in the return frame"
        vector = np.asarray(
            [float(w) for w, t in zip(weight_values, tickers) if t in returns.columns],
            dtype=float,
        )
        if vector.size == 0 or not np.isfinite(vector).all() or vector.sum() <= 0.0:
            return None, "no positive finite weight on the measured legs"
        sample = returns[available].dropna(how="all")
        if len(sample) < 2:
            return None, "fewer than two dates with any measured leg return"
        covariance = sample.cov().to_numpy(dtype=float)
        if not np.isfinite(covariance).all():
            return None, "sample covariance is not finite for these legs"
        variance = float(vector @ covariance @ vector)
        if not np.isfinite(variance) or variance < 0.0:
            return None, "sample-covariance quadratic form is not a finite variance"
        return float(np.sqrt(variance) * np.sqrt(252.0)), None

    async def volatility_sizing(
        self, 
        price_data: pd.DataFrame, 
        weights: Dict[str, float], 
        model: str = "EWMA", 
        target_volatility: float = 0.15,
        portfolio_value: Optional[float] = None,
        price_currency: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calculate volatility-adjusted position sizing

        The analytical target is inverse-volatility risk parity scaled to
        `target_volatility`, so the legs sum to the scale factor rather than to
        1.0. That gross exposure is preserved (renormalizing a risk-parity
        target to 100 % would delete the leverage it was asked to quantify) and
        reported through the shared normalization rule consumed by the rebalance
        workflow: `execution` states gross exposure, the financing it needs, and
        whether the target may be applied as a plain rebalance.

        Trade instructions are pinned to ONE aligned sizing price date and
        whole shares are derived from the reported notional with a documented
        half-up rule, so amount, `shares_delta`, and `sizing_price` reconcile.

        Three volatilities describe this one book and each is published under
        the convention that produced it, because publishing one of them as
        "the" volatility is what made a 15 % target look verified:

        * `sizing_volatility` -- the modelled volatility of the parity book
          (correlation x EWMA marginals).  The scale is DEFINED as
          `target / sizing_volatility`, so this is the number the sizing
          actually used and it used to be discarded.
        * `achieved_volatility` -- a MEASUREMENT: the recommended, scaled
          book's volatility on the sample covariance of the measured returns.
          It is not `sizing_volatility * scale`, because that product is the
          target identically.
        * `current_volatility_sample_covariance` -- the same measurement for
          the book as it stands, so the target, the current book and the
          recommendation are comparable in one convention.

        `imposed_target_volatility` publishes the algebraic identity openly
        instead of passing it off as an achievement.

        Args:
            price_data: Historical price data
            weights: Current portfolio weights
            model: Volatility model
            target_volatility: Target portfolio volatility
            portfolio_value: Budget for notional sizing; without it no trade
                amount is computable and instructions report `unavailable`
                instead of a fabricated zero
            price_currency: Currency of `price_data`; the engine cannot infer
                it, so it stays `unavailable` when the caller omits it
        
        Returns:
            Dictionary with sizing recommendations
        """
        try:
            if price_data.empty or not weights:
                return self._empty_volatility_sizing()
            
            # Missing observations remain missing.  The inverse-volatility
            # calculation uses each asset's active history and pairwise
            # correlation rather than manufacturing pre-listing zeroes.
            cleaned_prices = price_data.replace([np.inf, -np.inf], np.nan).sort_index()
            returns = cleaned_prices.pct_change(fill_method=None)
            if returns.empty or len(returns) < 2:
                return self._empty_volatility_sizing()
            returns = returns.iloc[1:]
            
            # Calculate volatilities using the selected model (EWMA, GARCH, EGARCH).
            # Keep the source of each estimate visible: a model that cannot fit a
            # short sample may use a measured sample-volatility fallback, but
            # never an invented constant.
            annualized_vols = {}
            daily_vols = {}
            volatility_sources = {}
            model_type = (model or "EWMA").upper()

            for ticker in returns.columns:
                series = returns[ticker].replace([np.inf, -np.inf], np.nan).dropna()
                if model_type == "EWMA" and len(series) < 2:
                    # A single return has no sample dispersion; do not turn the
                    # model's zero convention into a fabricated allocation.
                    continue
                sample_vol = (
                    float(series.std(ddof=1) * np.sqrt(252))
                    if len(series) > 1 else None
                )
                if sample_vol is not None and (not np.isfinite(sample_vol) or sample_vol < 0):
                    sample_vol = None
                vol_ann = None
                source = model_type
                try:
                    if model_type == "GARCH":
                        res = await self._garch_forecast(series, 1)
                    elif model_type == "EGARCH":
                        res = await self._egarch_forecast(series, 1)
                    else:
                        res = self._ewma_forecast(series, 1)
                    # Use the un-floored model estimate for inverse-volatility
                    # parity.  The public forecast remains clipped for stable
                    # UI bounds, but a 1% asset must not become a 5% peer.
                    raw_value = res.get("raw_volatility_forecast")
                    if raw_value is None:
                        raw_value = res.get("volatility_forecast")
                    if raw_value is not None:
                        candidate = float(raw_value)
                        if np.isfinite(candidate) and candidate >= 0.0:
                            vol_ann = candidate
                except Exception:
                    vol_ann = None
                if vol_ann is None and sample_vol is not None:
                    vol_ann = sample_vol
                    source = "sample_fallback"
                if vol_ann is None:
                    # No finite estimate means no inverse-volatility allocation;
                    # retaining a made-up floor would distort relative sizing.
                    continue
                annualized_vols[ticker] = float(vol_ann)
                daily_vols[ticker] = float(vol_ann) / np.sqrt(252)
                volatility_sources[ticker] = source

            available_tickers = list(returns.columns)
            current_tickers = []
            current_weight_values = []
            current_vol_values = []
            for ticker in available_tickers:
                try:
                    weight = float(weights.get(ticker, 0.0))
                    vol = float(annualized_vols.get(ticker, np.nan))
                except (TypeError, ValueError):
                    continue
                if weight > 0.0 and np.isfinite(weight) and np.isfinite(vol) and vol >= 0.0:
                    current_tickers.append(ticker)
                    current_weight_values.append(weight)
                    current_vol_values.append(vol / np.sqrt(252))
            current_volatility = None
            current_volatility_reason: Optional[str] = None
            current_unmeasurable: list[str] = []
            if current_tickers:
                current_corr = returns[current_tickers].corr()
                current_corr = current_corr.replace([np.inf, -np.inf], np.nan)
                # A pair with fewer than two shared return rows -- or with no
                # variation in either leg -- is NaN here, and NaN means NOT
                # MEASURABLE. The old `.fillna(0.0)` asserted the strongest
                # claim a correlation matrix can make, that the two legs have
                # no relationship whatsoever, and then published a portfolio
                # volatility computed from it: a leg that was merely unobserved
                # read as a free diversifier, understating the book's risk.
                # The risk-score correlation leg already refuses this
                # measurement the same way (`finite_pairs` only, `None` plus
                # `excluded`); so does this one. The quadratic form needs a
                # full matrix to be a measurement at all, so the figure is
                # absent rather than approximated.
                columns = list(current_corr.columns)
                current_unmeasurable = [
                    f"{columns[i]}/{columns[j]}"
                    for i in range(len(columns))
                    for j in range(i + 1, len(columns))
                    if not np.isfinite(current_corr.iat[i, j])
                ]
                if current_unmeasurable:
                    current_volatility_reason = (
                        f"{UNMEASURABLE_CORRELATION_REASON}: "
                        f"{', '.join(current_unmeasurable)}"
                    )
                else:
                    current_corr_values = current_corr.to_numpy(dtype=float).copy()
                    np.fill_diagonal(current_corr_values, 1.0)
                    current_cov = current_corr_values * np.outer(current_vol_values, current_vol_values)
                    current_vec = np.asarray(current_weight_values, dtype=float)
                    variance = float(current_vec @ current_cov @ current_vec)
                    if np.isfinite(variance):
                        current_volatility = float(np.sqrt(max(0.0, variance)) * np.sqrt(252))
                    else:
                        current_volatility_reason = (
                            "the correlation quadratic form did not evaluate to a "
                            "finite variance on the measured legs"
                        )
            # The same book measured on the sample covariance.  Published
            # because `current_volatility` above is a MODEL quantity
            # (correlation x EWMA marginals) and the artifact used to carry it
            # with no label, beside a realised figure ~36 % away and with no
            # reconciliation note.  Three volatilities for one book is a defect
            # whichever one is right; naming the convention of each is the fix.
            current_volatility_sample, current_volatility_sample_reason = (
                self._sample_covariance_volatility(
                    returns, current_tickers, current_weight_values
                )
            )

            # Calculate true inverse-volatility risk parity weights for
            # positive, finite target holdings: w_i \propto 1 / \sigma_i.
            # Zero-weight positions must not receive a synthetic allocation.
            inv_vols = {}
            for ticker, weight in weights.items():
                sigma = annualized_vols.get(ticker)
                try:
                    weight = float(weight)
                    sigma = float(sigma)
                except (TypeError, ValueError):
                    continue
                if (
                    ticker in returns.columns
                    and weight > 0.0
                    and np.isfinite(weight)
                    and np.isfinite(sigma)
                    and sigma > 0.0
                ):
                    inv_vols[ticker] = 1.0 / sigma
            sum_inv_vol = sum(inv_vols.values())

            if sum_inv_vol <= 0:
                return self._empty_volatility_sizing()
            recommended_weights = {k: v / sum_inv_vol for k, v in inv_vols.items()}

            # Scale-to-target using only the recommended, positive-volatility
            # legs.  Excluding a zero-variance leg is not enough if its NaN
            # correlation remains in the matrix: 0 * NaN would still poison the
            # quadratic form.
            rec_tickers = list(recommended_weights)
            rec_vec = np.asarray([recommended_weights[ticker] for ticker in rec_tickers], dtype=float)
            rec_vol_vec = np.asarray([annualized_vols[ticker] / np.sqrt(252) for ticker in rec_tickers], dtype=float)
            rec_unmeasurable: list[str] = []
            if len(rec_tickers) == 1:
                rec_vol_ann = float(rec_vol_vec[0] * np.sqrt(252))
            else:
                rec_corr = returns[rec_tickers].corr()
                rec_corr = rec_corr.replace([np.inf, -np.inf], np.nan)
                # Same refusal as the current book above, and here it is
                # load-bearing: `rec_vol_ann` is the divisor of
                # `scale = target / rec_vol_ann`, so an unmeasurable pair here
                # scales every published weight. Filling it with 0.0 published
                # a target that leaned on a leg for having no measurable
                # relationship to the rest of the book.
                rec_columns = list(rec_corr.columns)
                rec_unmeasurable = [
                    f"{rec_columns[i]}/{rec_columns[j]}"
                    for i in range(len(rec_columns))
                    for j in range(i + 1, len(rec_columns))
                    if not np.isfinite(rec_corr.iat[i, j])
                ]
                if rec_unmeasurable:
                    # Refuse rather than drop the leg. Dropping it from the
                    # matrix alone would leave it in `recommended_weights` and
                    # poison the very form it was meant to protect; dropping it
                    # from `recommended_weights` as well would make
                    # `build_trade_instructions` emit a full-liquidation trade
                    # for a holding that is merely unobserved. A refusal is the
                    # only answer that neither invents a number nor orders a
                    # sale the data does not justify, and it is published.
                    return self._empty_volatility_sizing(
                        reason=(
                            f"{UNMEASURABLE_CORRELATION_REASON}: "
                            f"{', '.join(rec_unmeasurable)}; the recommended "
                            "book cannot be scaled to a target volatility "
                            "without inventing one"
                        ),
                        unmeasurable_pairs=rec_unmeasurable,
                    )
                rec_corr_values = rec_corr.to_numpy(dtype=float).copy()
                np.fill_diagonal(rec_corr_values, 1.0)
                rec_cov = rec_corr_values * np.outer(rec_vol_vec, rec_vol_vec)
                rec_variance = float(rec_vec @ rec_cov @ rec_vec)
                rec_vol_ann = (
                    float(np.sqrt(max(0.0, rec_variance)) * np.sqrt(252))
                    if np.isfinite(rec_variance) else 0.0
                )
            if not np.isfinite(rec_vol_ann) or rec_vol_ann <= 0.0:
                return self._empty_volatility_sizing()
            scale = float(target_volatility / rec_vol_ann)
            scaled_weights = {k: round(v * scale, 6) for k, v in recommended_weights.items()}

            # `rec_vol_ann` is the volatility the scale was built from.  It
            # used to be discarded, which is how a third, unpublished number
            # ended up driving the recommendation: the published
            # `current_volatility` was 0.145, the vol the scale used was
            # 0.1158, and neither was named.  It is now published under its own
            # key with its own basis.
            sizing_volatility = float(rec_vol_ann)
            sizing_volatility_basis = (
                "single_leg_ewma_volatility"
                if len(rec_tickers) == 1
                else "correlation_x_ewma_volatility"
            )
            # `rec_vol_ann * scale` is the target, identically, for every input:
            # `scale` was DEFINED as target / rec_vol_ann.  Publishing that
            # product as `achieved_volatility` published the target's own
            # restatement and labelled it a measurement.  What a reader needs
            # is the volatility the recommended book actually carries on the
            # measured returns, so that is what the field now holds.
            imposed_target_volatility = float(rec_vol_ann * scale)
            scaled_vector = [
                scaled_weights.get(ticker, 0.0) for ticker in rec_tickers
            ]
            achieved_vol, achieved_vol_reason = self._sample_covariance_volatility(
                returns, rec_tickers, scaled_vector
            )
            parity_vol, parity_vol_reason = self._sample_covariance_volatility(
                returns, rec_tickers, [recommended_weights[t] for t in rec_tickers]
            )

            # One documented normalization rule, shared with the rebalance
            # workflow.  The analytical target keeps its gross exposure and
            # reports the financing that exposure requires; `cash_weight` is the
            # signed net cash weight, so a 129 % book can no longer read as
            # "zero cash" with no financing leg anywhere.
            execution = normalization_block(
                scaled_weights,
                portfolio_value=portfolio_value,
                currency=price_currency,
                weights_normalized=False,
            )
            leveraged = bool(execution["financing_required"])
            # Signed net cash weight: a 129 % book reports -0.29 here, never 0.
            # `execution.net_cash_weight` is the same quantity derived from the
            # rounded published legs; the two agree to the published precision.
            cash_weight = round(1.0 - scale, 6)

            history = sizing_history_block(
                returns, price_frame=cleaned_prices, model=model_type
            )
            basis = build_sizing_basis(
                cleaned_prices, list(returns.columns), currency=price_currency
            )
            instructions = build_trade_instructions(
                {
                    ticker: scaled_weights.get(ticker, 0.0) - _finite_weight(weights, ticker)
                    for ticker in returns.columns
                },
                basis["sizing_price"],
                portfolio_value=portfolio_value,
                currency=price_currency,
                sizing_price_as_of=basis["sizing_price_as_of"],
                sizing_price_provenance=basis["sizing_price_provenance"],
            )
            trades = instructions["trades"]

            financing_text = (
                f"financing required {execution['financing_requirement']} "
                f"{price_currency or 'in the sizing currency'}"
                if execution["financing_requirement"] is not None
                else "financing required (unquantified: no portfolio value)"
            )
            achieved_text = (
                f"achieved_vol={round(achieved_vol, 4)} on the sample covariance"
                if achieved_vol is not None
                else f"achieved_vol=unavailable ({achieved_vol_reason})"
            )
            methodology = (
                f"{model} inverse-volatility risk parity scaled to target volatility "
                f"{target_volatility} (scale={round(scale, 4)}, "
                f"gross_exposure={execution['gross_exposure']}, cash={cash_weight}, "
                f"sizing_vol={round(sizing_volatility, 4)} on "
                f"{sizing_volatility_basis}, {achieved_text}; the target is "
                f"imposed algebraically by scale, not verified against the data"
                + (
                    f", {financing_text}; not executable as a normal rebalance"
                    if leveraged
                    else ", unlevered long-only + cash"
                )
                + "; not full ERC: no Euler RC_i decomposition)"
            )
            return {
                "current_weights": weights,
                "recommended_weights": scaled_weights,
                "trades": trades,
                "target_volatility": target_volatility,
                "current_volatility": current_volatility,
                "current_volatility_basis": (
                    "correlation_x_ewma_volatility"
                    if current_tickers and current_volatility is not None
                    else None
                ),
                # Why the figure above is absent, and which pairs had no
                # correlation to measure. Published so that a null here is
                # distinguishable from a payload that predates the key, and so
                # the reader can see the book was refused rather than guessed.
                "current_volatility_reason": current_volatility_reason,
                "current_volatility_unmeasurable_pairs": current_unmeasurable,
                "current_volatility_sample_covariance": (
                    round(current_volatility_sample, 6)
                    if current_volatility_sample is not None
                    else None
                ),
                "current_volatility_sample_covariance_reason": (
                    current_volatility_sample_reason
                ),
                "volatilities": annualized_vols,
                "volatility_sources": volatility_sources,
                "scale_factor": round(scale, 6),
                "cash_weight": cash_weight,
                "leveraged": leveraged,
                # A MEASUREMENT: the volatility of the recommended, scaled book
                # on the sample covariance of the measured returns.  It is
                # deliberately NOT `sizing_volatility * scale`, which is the
                # target restated.
                "achieved_volatility": (
                    round(achieved_vol, 6) if achieved_vol is not None else None
                ),
                "achieved_volatility_basis": "sample_covariance_of_measured_returns",
                "achieved_volatility_reason": achieved_vol_reason,
                # The vol the scale was actually built from, which used to be
                # computed and thrown away.
                "sizing_volatility": round(sizing_volatility, 6),
                "sizing_volatility_basis": sizing_volatility_basis,
                # Both empty on a book whose pairs are all measurable; a
                # non-empty list is the refusal path's payload instead, and
                # these two keys are what tell the two apart in one place.
                "sizing_volatility_reason": None,
                "sizing_volatility_unmeasurable_pairs": rec_unmeasurable,
                # What the target becomes under the sizing covariance. An
                # identity, published as one so it is never mistaken for a
                # second, independent measurement.
                "imposed_target_volatility": round(imposed_target_volatility, 6),
                "imposed_target_volatility_basis": (
                    "sizing_volatility_times_scale_equals_target_by_construction"
                ),
                "recommended_volatility_sample_covariance": (
                    round(parity_vol, 6) if parity_vol is not None else None
                ),
                "recommended_volatility_sample_covariance_reason": parity_vol_reason,
                "methodology": methodology,
                "execution": execution,
                "sizing_history": history,
                "trade_instructions_status": instructions["status"],
                "trade_reconciliation": instructions["reconciliation"],
                "sizing_price": basis["sizing_price"],
                "sizing_price_as_of": basis["sizing_price_as_of"],
                "sizing_price_currency": basis["sizing_price_currency"],
                "sizing_price_provenance": basis["sizing_price_provenance"],
                "sizing_price_unavailable_reason": basis["sizing_price_unavailable_reason"],
                "sizing_price_missing_tickers": basis["missing_tickers"],
                "sizing_price_unpriced_tickers": basis["unpriced_tickers"],
                "price_currency_provenance": (
                    "measured" if price_currency else "unavailable"
                ),
            }
            
        except Exception as e:
            logger.error(f"Error in volatility sizing: {e}")
            return self._empty_volatility_sizing()
    
    async def risk_scoring(
        self, 
        price_data: pd.DataFrame, 
        weights: Dict[str, float],
        benchmark_data: Optional[pd.Series] = None
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive risk score

        Args:
            price_data: Historical price data
            weights: Portfolio weights
            benchmark_data: Optional benchmark returns (or prices) for the
                factor leg. Without it the factor leg is excluded and the
                remaining legs renormalized (never a silent R²=0 → max score).

        Returns:
            Dictionary with risk score and components
        """
        try:
            if price_data.empty or not weights:
                return self._empty_risk_score()
            
            cleaned_prices = price_data.replace([np.inf, -np.inf], np.nan).sort_index()
            returns = cleaned_prices.pct_change(fill_method=None)
            if returns.empty or len(returns) < 2:
                return self._empty_risk_score()
            returns = returns.iloc[1:]
            
            portfolio_returns = self._calculate_portfolio_returns(returns, weights)
            
            # Calculate component scores (0-30 scale, higher is riskier)
            scores = {}
            # A leg that could not be measured is listed here, and the weight
            # below is dropped + the rest renormalized. `excluded` and
            # `scores[...] is None` are kept in agreement deliberately: a null
            # sub-score that was still counted would be a fabricated 0.
            excluded: list[str] = []
            excluded_reasons: dict[str, str] = {}
            # The published input each leg was scored from, so `score_audit`
            # can state provenance instead of asserting it. `None` + a reason is
            # the only way a leg's input is ever absent: an input that cannot be
            # established is published as unknown, never inferred.
            inputs: dict[str, Optional[float]] = {}
            input_reasons: dict[str, str] = {}
            
            # Concentration risk (20% weight in overall score)
            concentration_result = await self.concentration_analysis(weights)
            # `herfindahl_index` is the whole input of this leg, and the analysis
            # publishes 0.0 with an `error` when it measured nothing -- a 0.0
            # Herfindahl is impossible for a non-empty book (sum(w^2) >=
            # 1/n > 0), so a 0.0 here is an absence wearing a measurement's
            # clothes. The sub-score below is the original expression, untouched;
            # only the PROVENANCE of its input is published, because a reader
            # cannot otherwise tell a real 0.0 from an unmeasured one.
            concentration_unavailable = bool(concentration_result.get("error"))
            hhi = concentration_result.get('herfindahl_index', 0.1)
            concentration_score = min(30, hhi * 100)
            scores['concentration'] = concentration_score
            inputs['concentration'] = None if concentration_unavailable else float(hhi)
            input_reasons['concentration'] = (
                "concentration analysis published no measured Herfindahl index "
                f"({concentration_result.get('error')})"
                if concentration_unavailable
                else "measured over the active portfolio weights"
            )

            # Volatility risk (25% weight). An empty series is UNMEASURED, and
            # `min(30, nan * 100)` returns 30 in Python -- a fabricated maximum
            # risk score out of nothing. The coverage gate can empty the series
            # (a book with a never-listed leg has no full-basket day at all), so
            # null + exclude, exactly as the correlation leg below does.
            portfolio_vol = (
                portfolio_returns.std() * np.sqrt(252)  # Annualized
                if not portfolio_returns.empty
                else None
            )
            if portfolio_vol is None or not np.isfinite(portfolio_vol):
                volatility_score = None
                excluded.append('volatility')
                excluded_reasons['volatility'] = (
                    "no date carried a return for the whole book, so there is "
                    "no portfolio volatility to measure"
                )
            else:
                volatility_score = min(30, portfolio_vol * 100)
            scores['volatility'] = volatility_score
            inputs['volatility'] = (
                float(portfolio_vol)
                if volatility_score is not None and portfolio_vol is not None
                and np.isfinite(portfolio_vol)
                else None
            )
            input_reasons.setdefault(
                'volatility',
                "std of the delivered portfolio return series, annualized by "
                "sqrt(252)",
            )
            if volatility_score is None:
                input_reasons['volatility'] = excluded_reasons.get(
                    'volatility', "not measured"
                )

            # Correlation risk (20% weight)
            #
            # The sub-score is RISK POINTS on a 0-30 scale, so 0 has to mean one
            # thing only: "this leg was not measured". The old expression,
            # `clip((avg - 0.3) * 50, 0, 30)`, collapsed into that same 0 for
            # every measured average correlation at or below the 0.3 baseline,
            # and a one-asset book - which has no cross-asset correlation at all
            # - published 0 as well. Both looked identical to a real reading and
            # both pulled `overall_score` down, while Risk Studio measured
            # 0.1404 over its own window. So: measure the average, publish the
            # measurement, score the measurement, and null + exclude the leg
            # when there is nothing to measure.
            avg_correlation: Optional[float] = None
            # Points the scale's zero floor added to this leg's sub-score. Zero
            # when the floor did not bind; published per leg so a clamped 0.0 is
            # not read as a measured zero.
            correlation_floor_clamp = 0.0
            if len(returns.columns) > 1:
                corr_values = returns.corr().to_numpy(dtype=float)
                upper_triangle = corr_values[np.triu_indices_from(corr_values, k=1)]
                finite_pairs = upper_triangle[np.isfinite(upper_triangle)]
                if finite_pairs.size:
                    avg_correlation = float(finite_pairs.mean())
            if avg_correlation is None:
                correlation_score = None
                excluded.append('correlation')
                excluded_reasons['correlation'] = (
                    "fewer than two return series, or no finite pairwise "
                    "correlation to measure"
                )
            else:
                # Risk points per unit of measured average pairwise correlation.
                # The slope and the 30-point cap are unchanged; only the
                # collapsing `max(0, . - 0.3)` baseline is gone, so a book that
                # measures positively-correlated still contributes to the score
                # instead of reading as an unmeasured leg.
                #
                # What remains is the SCALE's floor at zero. A measured average
                # correlation below zero is a real measurement that a 0-30
                # higher-is-riskier scale cannot express as negative risk, so it
                # is clamped -- and the clamp is measured here and published by
                # `score_audit`, so a sub-score of 0.0 cannot be read as a
                # measured zero correlation.
                uncapped_correlation = (
                    avg_correlation * RISK_CORRELATION_POINTS_PER_UNIT
                )
                correlation_score = min(RISK_SCORE_CAP, max(
                    RISK_SCORE_FLOOR, uncapped_correlation
                ))
                correlation_floor_clamp = round(
                    max(0.0, RISK_SCORE_FLOOR - uncapped_correlation), 6
                )
            scores['correlation'] = correlation_score
            inputs['correlation'] = avg_correlation
            # The PUBLISHED precision of the measurement, hoisted out of the
            # response dict below so the disclosure block and the published key
            # are the same number by construction rather than by two copies of
            # one expression agreeing.
            avg_pairwise_correlation_published = (
                round(avg_correlation, RISK_SCORE_STATISTIC_DECIMALS)
                if avg_correlation is not None
                else None
            )
            input_reasons['correlation'] = (
                "mean of the finite upper-triangle pairwise Pearson correlations "
                "of the constituent return frame"
                if correlation_score is not None
                else excluded_reasons.get('correlation', "not measured")
            )

            # Factor risk (25% weight) — only with a real benchmark. Calling
            # factor_exposure_analysis without one yields R²=0 always, which
            # would pin this leg at max risk, so exclude + renormalize instead.
            factor_result: Optional[Dict[str, Any]] = None
            if benchmark_data is not None and not benchmark_data.empty:
                factor_result = await self.factor_exposure_analysis(
                    price_data, benchmark_data=benchmark_data, weights=weights
                )
                r_squared = factor_result.get('r_squared')
                if r_squared is None:
                    factor_score = None
                    excluded.append('factor_risk')
                    excluded_reasons['factor_risk'] = (
                        "a benchmark was supplied but the factor fit published no "
                        "R-squared"
                    )
                else:
                    factor_score = min(30, (1 - r_squared) * 100)
            else:
                r_squared = None
                factor_score = None
                excluded.append('factor_risk')
                excluded_reasons['factor_risk'] = "no benchmark supplied"
            # The regression's OWN row count, taken from the fit rather than
            # re-measured here, so the sample an R-squared was estimated on is
            # the sample the disclosure says it was estimated on.
            portfolio_fit = (
                factor_result.get("portfolio") if isinstance(factor_result, dict)
                else None
            )
            factor_fit_observations = (
                portfolio_fit.get("observations")
                if isinstance(portfolio_fit, dict)
                and isinstance(portfolio_fit.get("observations"), int)
                else None
            )
            scores['factor_risk'] = factor_score
            inputs['factor_risk'] = (
                float(r_squared)
                if isinstance(r_squared, (int, float)) and not isinstance(r_squared, bool)
                and np.isfinite(r_squared)
                else None
            )
            if factor_score is None:
                input_reasons['factor_risk'] = excluded_reasons.get(
                    'factor_risk', "not measured"
                )
            else:
                input_reasons['factor_risk'] = (
                    "R-squared of the portfolio-vs-benchmark OLS fit over the "
                    f"{factor_fit_observations} paired return rows the fit kept; "
                    "the route measures the same population from the published "
                    "inputs and publishes it as model_observation_count"
                )

            # Market risk (10% weight) - based on recent volatility. Same
            # unmeasured-is-not-zero rule as the volatility leg above.
            recent_returns = portfolio_returns.tail(RISK_MARKET_WINDOW_ROWS)
            recent_vol = (
                recent_returns.std() * np.sqrt(252)
                if len(recent_returns) > 1
                else None
            )
            if recent_vol is None or not np.isfinite(recent_vol):
                market_score = None
                excluded.append('market_risk')
                excluded_reasons['market_risk'] = (
                    "fewer than two published portfolio return rows in the "
                    "recent window, so there is no recent volatility to measure"
                )
            else:
                market_score = min(30, recent_vol * 100)
            scores['market_risk'] = market_score
            inputs['market_risk'] = (
                float(recent_vol)
                if market_score is not None and recent_vol is not None
                and np.isfinite(recent_vol)
                else None
            )
            input_reasons['market_risk'] = (
                "std of the last "
                f"{len(recent_returns)} delivered portfolio return rows, "
                f"annualized by sqrt(252)"
                if market_score is not None
                else excluded_reasons.get('market_risk', "not measured")
            )

            # Calculate overall score (weighted average; excluded legs are
            # dropped and the remaining weights renormalized to sum to 1).
            # The table is the module-level RISK_SCORE_WEIGHTS, which the audit
            # below also publishes: one source, so a published weight cannot
            # drift from the applied one.
            weights_scores = dict(RISK_SCORE_WEIGHTS)
            # Belt and braces: a null sub-score is never counted, whether or not
            # it reached `excluded`. `sum()` over a None would raise, and
            # treating None as 0 is the hard-zero fabrication D-04 is about.
            active_weights = {
                k: w
                for k, w in weights_scores.items()
                if k not in excluded and scores.get(k) is not None
            }
            w_total = sum(active_weights.values()) or 1.0
            active_weights = {k: w / w_total for k, w in active_weights.items()}

            overall_score = sum(scores[component] * active_weights[component]
                              for component in active_weights)
            
            # Determine risk level (stateless: no cross-request score memory,
            # so no singleton bleed or async race. Scoring is stateless: no
            # prior score is persisted anywhere, so there is NO genuine delta to
            # report. Publishing `change: 0` would present an unmeasured value
            # as a measured "unchanged" score.
            if overall_score < 15:
                risk_level = "LOW"
            elif overall_score < 25:
                risk_level = "MEDIUM"
            else:
                risk_level = "HIGH"
            change = None

            # What the five sub-scores are made of. The arithmetic above is
            # unchanged; this states, from the same numbers the score was built
            # from, which legs are measurements, which are pinned at the cap and
            # which re-measure a statistic another leg already measured.
            score_audit = _risk_score_audit(
                scores=scores,
                inputs=inputs,
                input_reasons=input_reasons,
                input_samples={
                    'concentration': {
                        'row_kind': 'active_holdings',
                        'rows': len(
                            [
                                w for w in weights.values()
                                if isinstance(w, (int, float)) and w > 0
                            ]
                        ),
                    },
                    'volatility': {
                        'row_kind': 'portfolio_return_rows',
                        'rows': int(len(portfolio_returns)),
                    },
                    'correlation': {
                        'row_kind': 'constituent_return_rows',
                        'rows': int(len(returns)),
                    },
                    'factor_risk': {
                        'row_kind': 'regression_rows',
                        # Left exactly as it was: this row count is the ROUTE's
                        # measurement to make. The engine's own fit count is
                        # published where it belongs for the precision question,
                        # at score_audit.precision.estimated_statistics
                        # .factor_r_squared.notes.fit_observation_count; moving it
                        # here would move a disclosure another wave's test pins,
                        # for no gain.
                        'rows': None,
                        'rows_reason': (
                            "the engine fits the regression from price_data and the "
                            "benchmark but does not count the rows the fit kept; the "
                            "route measures it and publishes model_observation_count"
                        ),
                    },
                    'market_risk': {
                        'row_kind': (
                            f'portfolio_return_rows_tail_{RISK_MARKET_WINDOW_ROWS}'
                        ),
                        'rows': int(len(recent_returns)),
                    },
                },
                input_series={
                    'volatility': portfolio_returns,
                    'market_risk': recent_returns,
                },
                floor_clamps={'correlation': correlation_floor_clamp},
                excluded=excluded,
                excluded_reasons=excluded_reasons,
                active_weights=active_weights,
                overall_score=overall_score,
                returns=returns,
                benchmark_data=benchmark_data,
                weights=weights,
                avg_pairwise_correlation_published=avg_pairwise_correlation_published,
                r_squared=r_squared,
                factor_result=factor_result,
            )
            
            # Generate alerts
            alerts = []
            if concentration_score > 20:
                alerts.append(f"High concentration risk (HHI: {concentration_result.get('herfindahl_index', 0):.3f})")
            if volatility_score is not None and volatility_score > 20:
                alerts.append(f"High volatility risk ({portfolio_vol:.1%} annualized)")
            if correlation_score is not None and correlation_score > 15:
                alerts.append(f"High correlation risk (avg correlation: {avg_correlation:.2f})")
            if factor_score is not None and factor_score > 15:
                alerts.append(f"High unexplained risk (low R-squared: {r_squared:.2f})")
            if excluded:
                named = "; ".join(
                    f"{name}: {excluded_reasons.get(name, 'not measured')}"
                    for name in excluded
                )
                alerts.append(
                    f"Excluded from the weighted score ({named}); "
                    "remaining legs renormalized"
                )
            if concentration_unavailable:
                alerts.append(
                    "Concentration leg input unavailable: the sub-score was "
                    "scored from an unmeasured Herfindahl index, not a measured "
                    "one (see score_audit.components.concentration)"
                )
            alerts.extend(_risk_score_composition_alerts(score_audit))
            
            return {
                # `float()` on the way out: `portfolio_returns.std()` is a numpy
                # scalar, so `min(30, that * 100)` is one, and `round()` keeps it
                # one. Harmless to today's serialiser, but a numpy scalar is not
                # a plain number to anything that type-checks the payload, and a
                # key added later would inherit it. Coerced here, on the two keys
                # this function computes from `scores`, and nowhere else.
                "overall_score": round(float(overall_score), 1),
                "risk_level": risk_level,
                "change": change,
                "change_status": "unavailable",
                "change_reason": "no_persisted_prior_score",
                "components": {
                    k: (round(float(v), 1) if v is not None else None)
                    for k, v in scores.items()
                },
                # The measurement the correlation leg was scored from, so a low
                # sub-score is explicable rather than a bare number. Null means
                # the same thing it means on `factor_r_squared`: not measured.
                # The precision disclosure for it lives at
                # `score_audit.precision.estimated_statistics.avg_pairwise_correlation`.
                "avg_pairwise_correlation": avg_pairwise_correlation_published,
                "alerts": alerts,
                "excluded_components": excluded,
                # Siblings of `excluded_components`, same level and vocabulary: a
                # leg that is at its ceiling, and a leg whose input is the same
                # measurement as another leg's, are as much a part of what this
                # score is NOT as an unmeasured leg is. `score_audit` carries the
                # per-leg detail behind both.
                "saturated_components": score_audit["saturated_components"],
                "duplicate_components": score_audit["duplicate_components"],
                "independent_component_count": score_audit["effective_information"][
                    "independent_leg_count"
                ],
                "score_audit": score_audit,
                "factor_r_squared": r_squared,
                "methodology": (
                    "Multi-factor risk scoring with weighted components, 0-30 per "
                    "leg (stateless; weights concentration 0.20, volatility 0.25, "
                    "correlation 0.20, factor_risk 0.25, market_risk 0.10, "
                    "renormalized over the legs that were measured; correlation "
                    f"leg = min(30, {RISK_CORRELATION_POINTS_PER_UNIT:g} x max(0, "
                    "avg pairwise correlation) and is null + excluded when no "
                    "finite pairwise correlation exists; factor leg requires a "
                    "benchmark, else excluded; every leg's input statistic, "
                    "formula, weight, cap, saturation and duplication status is "
                    "published in score_audit)"
                )
            }
            
        except Exception as e:
            logger.error(f"Error in risk scoring: {e}")
            return self._empty_risk_score()
    
    # Helper methods for calculations
    
    def _calculate_portfolio_returns(self, returns: pd.DataFrame, weights: Dict[str, float]) -> pd.Series:
        """Delegate to the shared active positive-weight aggregation contract."""
        try:
            return aggregate_active_returns(returns, weights)
        except Exception:
            return pd.Series(dtype=float)
    
    def _calculate_basic_metrics(self, returns: pd.Series) -> Dict[str, Any]:
        """Calculate basic return and risk metrics.

        `annual_return`, `sharpe_ratio` and `sortino_ratio` are `None` below
        10 observations, never a number.  A mean annualization needs a window
        long enough to mean something, and the two ratios divide by a
        dispersion estimated from the same short window, so they inherit its
        thinness rather than correcting it.  The stated reason is published per
        field in `estimate_uncertainty.estimates.<field>.reason`; see
        `_SHORT_SAMPLE_ANNUALIZATION_REASON` and `_estimate_uncertainty_block`.

        The two ratios have a SECOND way to have no value, and it needs no
        short window at all: their OWN denominator measured nothing.  A window
        whose every return is exactly `0.0` - one ticker that never moved, or a
        stale-price frame that clears the ten-day `assert_not_stale` gate - has
        `annual_volatility == 0.0`, and a window that never undershot the
        Sortino target has a zero downside deviation.  Both used to publish
        `0.0` off the ternary on the annualizing branch, which is the defect
        the `< 10` branch above was fixed for, reproduced 30 lines below it:
        the repair reached the short window and never reached the
        zero-dispersion one.  Both are `None` now, with their own reason, for
        the reason given there - a zero published for a ratio that was never
        computed cannot be told apart from a measured zero.  See
        `_zero_dispersion_reason`.  `annual_return` and `annual_volatility` are
        NOT withheld on that window: a zero mean and a zero dispersion over a
        flat series are real measurements over the observations that exist.
        """
        try:
            if returns.empty:
                return {}
            
            if len(returns) < 10:
                # Insufficient sample size for reliable annualization.
                #
                # These three used to be published as a CUMULATIVE period sum
                # under the key `annual_return`, and as a hard 0.0 for both
                # ratios.  Both were fabrications rather than measurements: the
                # sum is a period figure wearing an annual label (it disagrees
                # with `engine_risk_statistics.annual_return` at :2209, which
                # has always used mean x 252 on every window), and a 0.0
                # Sharpe is indistinguishable from a measured zero, which is
                # what makes a hard zero on an unmeasured quantity the one
                # number a reader must never be handed.
                #
                # `annual_volatility` and `hit_ratio` STAY: both are genuine
                # measurements over the observed window (a sample standard
                # deviation and a proportion).  Whether a short window is
                # allowed to ANNUALIZE is the separate, deliberate policy
                # question owned by `apply_annualization_gate` /
                # MIN_ANNUALIZE_DAYS in `app/utils/holdings.py`, which the
                # routes already apply; that gate is not this method's to
                # re-decide, and widening it here would change published
                # numbers on the >= 30-day path this branch never reaches.
                annual_return = None
                annual_volatility = float(returns.std() * np.sqrt(252)) if len(returns) > 1 else 0.0
                sharpe_ratio = None
                sortino_ratio = None
            else:
                # Annual return and volatility
                annual_return = float(returns.mean() * 252)
                annual_volatility = float(returns.std() * np.sqrt(252))
                
                # Sharpe ratio
                #
                # `None`, never 0.0, when the dispersion measured nothing.  A
                # ratio over a zero denominator has no value, and publishing
                # 0.0 there hands the reader a number that cannot be told apart
                # from a measured zero Sharpe - the exact reason the sibling
                # branch above withholds instead of substituting.  No epsilon
                # floor and no small number: either would be a value this
                # method did not measure.  `annual_volatility > 0` is False for
                # a non-finite dispersion as well as a zero one, which is the
                # same absence - a NaN denominator has no ratio either.
                sharpe_ratio = (
                    float((annual_return - self.risk_free_rate) / annual_volatility)
                    if annual_volatility > 0
                    else None
                )
                
                # Sortino ratio (Sortino & Price 1994): downside deviation of the
                # full return series below a target, not std of negative subsample.
                # Target matches the numerator (annual rf -> daily equivalent).
                target = self.risk_free_rate / 252
                downside = np.minimum(0.0, returns.to_numpy(dtype=float) - target)
                downside_deviation = float(np.sqrt(np.mean(downside ** 2)) * np.sqrt(252)) if len(returns) else 0.0
                # Same contract as the Sharpe above, on its own denominator: a
                # window that never undershot the target has no downside to
                # divide by, so the ratio has no value rather than a zero one.
                sortino_ratio = (
                    float((annual_return - self.risk_free_rate) / downside_deviation)
                    if downside_deviation > 0
                    else None
                )
            
            # Hit ratio
            hit_ratio = float((returns > 0).mean())
            
            return {
                "annual_return": annual_return,
                "annual_volatility": annual_volatility,
                "sharpe_ratio": sharpe_ratio,
                "sortino_ratio": sortino_ratio,
                "hit_ratio": hit_ratio
            }
        except Exception:
            return {}
    
    def _calculate_risk_metrics(self, returns: pd.Series) -> Dict[str, float]:
        """Calculate risk metrics (VaR, CVaR)"""
        try:
            if returns.empty:
                return {}
            
            # Historical VaR (95%)
            var_95 = np.percentile(returns, 5)
            
            # Conditional VaR (Expected Shortfall)
            cvar_95 = returns[returns <= var_95].mean() if len(returns[returns <= var_95]) > 0 else var_95
            
            return {
                "var_95": var_95,
                "cvar_95": cvar_95
            }
        except Exception:
            return {}
    
    def _calculate_drawdown_metrics(self, returns: pd.Series) -> Dict[str, float]:
        """Calculate baseline-aware drawdown metrics.

        Initial wealth of 1.0 is a valid peak before the first return.  Without
        that baseline, a first-day loss appears to have no drawdown.
        """
        try:
            clean = pd.Series(returns).replace([np.inf, -np.inf], np.nan).dropna()
            if clean.empty:
                return {}

            wealth = (1.0 + clean).cumprod()
            wealth_with_baseline = pd.concat(
                [pd.Series([1.0]), wealth], ignore_index=True
            )
            running_max = wealth_with_baseline.cummax()
            drawdown = (wealth_with_baseline - running_max) / running_max

            return {
                "max_drawdown": float(drawdown.min())
            }
        except Exception:
            return {}
    
    def _calculate_return_distribution(self, returns: pd.Series) -> Dict[str, float]:
        """Calculate return distribution metrics"""
        try:
            if returns.empty:
                return {}
            
            return {
                "skewness": returns.skew(),
                "kurtosis": returns.kurtosis()
            }
        except Exception:
            return {}

    #: Fields this engine publishes per realized-risk block, in publication
    #: order.  Every one of them appears in the block's `estimates` map whether
    #: or not an interval could be computed, so a null interval is never a
    #: silently absent key.
    REALIZED_RISK_ESTIMATE_FIELDS = (
        "annual_return",
        "annual_volatility",
        "sharpe_ratio",
        "sortino_ratio",
        "hit_ratio",
        "var_95",
        "cvar_95",
        "max_drawdown",
        "skewness",
        "kurtosis",
    )

    #: The two distribution shapes have no honest interval here, and the reason
    #: is a missing estimator rather than a missing measurement.
    _DISTRIBUTION_SHAPE_REASON = (
        "not computed: pandas' sample skewness and kurtosis are bias-corrected "
        "shape statistics whose adjustment coefficients are not reimplemented "
        "here, so a resampling distribution over the SAME statistic cannot be "
        "produced. Hand-rolling a second implementation of an unmeasured "
        "estimator to satisfy an interval rule would trade a declared gap for "
        "an unverified number. The point estimate stands; its precision is "
        "declared absent rather than approximated."
    )

    #: Minimum observations before a mean-based annualization, and before the
    #: two ratios that divide by a dispersion estimated from the same window,
    #: are published at all.  Below it the three are `None` with this reason
    #: attached; see `_calculate_basic_metrics`.
    SHORT_SAMPLE_MIN_OBSERVATIONS = 10

    #: The three fields `_calculate_basic_metrics` withholds on a short window.
    SHORT_SAMPLE_WITHHELD_FIELDS = ("annual_return", "sharpe_ratio", "sortino_ratio")

    _SHORT_SAMPLE_ANNUALIZATION_REASON = (
        "withheld: fewer than {minimum} return observations were measured on "
        "this window, which is too few for a mean-based annualization to be a "
        "measurement rather than an extrapolation, and too few for the "
        "dispersion that {ratios} divide by to be stable. No cumulative period "
        "sum is published under the key 'annual_return', because a period "
        "total and an annualized rate are different quantities, and no zero is "
        "published for either ratio, because an unmeasured ratio is not a "
        "measured zero. This is a missing measurement, not a low one: it says "
        "nothing about whether performance was good. Widen the history window "
        "or lower SHORT_SAMPLE_MIN_OBSERVATIONS to obtain the value. Note the "
        "routes apply a separate annualization policy gate at "
        "MIN_ANNUALIZE_DAYS (30) in app/utils/holdings.py, which is stricter "
        "than this one and nulls these same keys on the published payload."
    )

    def _short_sample_reason(self) -> Dict[str, str]:
        """The per-field reason published when a window is too short."""
        return {
            field: self._SHORT_SAMPLE_ANNUALIZATION_REASON.format(
                minimum=self.SHORT_SAMPLE_MIN_OBSERVATIONS,
                ratios="sharpe_ratio and sortino_ratio",
            )
            for field in self.SHORT_SAMPLE_WITHHELD_FIELDS
        }

    #: The zero-dispersion sibling of `_SHORT_SAMPLE_ANNUALIZATION_REASON`:
    #: the OTHER way one of the two ratios has no value, and unlike the short
    #: window it needs no short window to reach.  Reached when the ratio's own
    #: denominator is not a positive, finite dispersion - a window whose every
    #: return is exactly 0.0, or which never undershot the Sortino target.
    #: Only the two ratios are withheld here; `annual_return` and
    #: `annual_volatility` beside them are real measurements over a flat
    #: window, which is why the sibling reason withholds three fields and this
    #: one withholds two.
    _ZERO_VOLATILITY_SHARPE_REASON = (
        "withheld: sharpe_ratio divides by this window's own annualized "
        "volatility, which measured {volatility} - not a positive finite "
        "dispersion - so the ratio has no value rather than a low one. No zero "
        "is published in its place, because a Sharpe published as 0.0 cannot "
        "be told apart from a portfolio that was measured and produced none, "
        "and a window with no dispersion is exactly the case where a reader "
        "would most want to know which of the two happened. Such a window is "
        "consistent with EVERY performance level, including an excellent one, "
        "so this absence says nothing about whether performance was good or "
        "bad. annual_return and annual_volatility beside it are still "
        "measurements over the observations that exist. This is a missing "
        "measurement, not a low one: it is a zero-dispersion window (a flat or "
        "stale price series, where every return is the same number), not a "
        "portfolio with no risk."
    )

    _ZERO_DOWNSIDE_SORTINO_REASON = (
        "withheld: sortino_ratio divides by this window's downside deviation "
        "below the risk-free target, which measured zero: the window never "
        "undershot the target, so there is no downside to divide by and the "
        "ratio has no value rather than a low one. No zero is published in its "
        "place, because a Sortino published as 0.0 cannot be told apart from a "
        "portfolio that was measured and suffered no downside. A window with "
        "no downside deviation is consistent with EVERY performance level, "
        "including an excellent one, so this absence says nothing about whether "
        "performance was good or bad. This is a missing measurement, not a low "
        "one."
    )

    def _zero_dispersion_reason(
        self, declared: Mapping[str, Any]
    ) -> Dict[str, str]:
        """Per-field reason published when a ratio's own denominator is nothing.

        Filtered to the fields whose point is actually withheld, so a window
        that measured ONE of the two ratios keeps the interval that ratio
        earned instead of losing it to its sibling's absence.  Read off
        `declared` - the values the payload publishes - so the reason cannot
        describe a different window than the point it is attached to.
        """
        reasons = {
            "sharpe_ratio": self._ZERO_VOLATILITY_SHARPE_REASON.format(
                volatility=declared.get("annual_volatility")
            ),
            "sortino_ratio": self._ZERO_DOWNSIDE_SORTINO_REASON,
        }
        return {
            field: reason
            for field, reason in reasons.items()
            if declared.get(field) is None
        }

    def _estimate_uncertainty_block(
        self,
        returns: pd.Series,
        published: Mapping[str, Any],
        *,
        scope: str,
    ) -> Dict[str, Any]:
        """Precision disclosure for one realized-risk block (SI-5).

        The statistics handed to `measure_estimate_uncertainty` are vectorised
        restatements of `_calculate_basic_metrics`, `_calculate_risk_metrics`
        and `_calculate_drawdown_metrics` - not of a textbook formula that
        happens to look similar - so the band published beside `sharpe_ratio`
        or `cvar_95` is a band for the number this engine actually printed.
        """
        clean = pd.Series(returns).replace([np.inf, -np.inf], np.nan).dropna()
        values = clean.to_numpy(dtype=float) if not clean.empty else np.zeros(0)
        declared = {
            name: published.get(name) for name in self.REALIZED_RISK_ESTIMATE_FIELDS
        }
        # A short window's withheld three get a FIELD-SPECIFIC reason rather
        # than the generic `point is None` text further down, so a reader can
        # see that the value is absent because the window is short and not
        # because the resampler declined.  Keyed off the measured count, which
        # is the same `len(returns)` `_calculate_basic_metrics` branched on.
        not_computed = {
            "skewness": self._DISTRIBUTION_SHAPE_REASON,
            "kurtosis": self._DISTRIBUTION_SHAPE_REASON,
        }
        if 0 < int(values.size) < self.SHORT_SAMPLE_MIN_OBSERVATIONS:
            not_computed.update(self._short_sample_reason())
        elif int(values.size) >= self.SHORT_SAMPLE_MIN_OBSERVATIONS:
            # Long enough to annualize, but a ratio whose OWN denominator
            # measured nothing: its point is withheld for THAT reason, and the
            # reason has to name it rather than borrow the short-window one,
            # which would send a reader off to widen a window that is already
            # wide enough.  `_zero_dispersion_reason` filters to the fields
            # that are actually absent, so a measured sibling keeps its band.
            not_computed.update(self._zero_dispersion_reason(declared))
        return measure_estimate_uncertainty(
            values,
            engine_risk_statistics(self.risk_free_rate),
            declared,
            scope=scope,
            point_tolerance=1e-9,
            not_computed=not_computed,
            notes={
                "estimator": (
                    "engine_risk_statistics: vectorised restatements of the "
                    "engine's own _calculate_basic_metrics / "
                    "_calculate_risk_metrics / _calculate_drawdown_metrics "
                    "formulas, so the interval belongs to the published point "
                    "value"
                ),
                "risk_free_rate": self.risk_free_rate,
                "risk_free_rate_basis": (
                    "the engine's configured annual risk-free rate, used as "
                    "risk_free_rate / 252 for the Sortino downside target and "
                    "as the numerator deduction for both ratios"
                ),
                "cvar_95_support_note": (
                    "cvar_95 is the mean of the return observations at or below "
                    "this block's own 5th percentile, so the number of "
                    "observations that support it is the tail count, not the "
                    "sample size"
                ),
            },
        )

    def _calculate_position_metrics(
        self,
        returns: pd.DataFrame,
        weights: Dict[str, float],
        raw_prices: Optional[pd.DataFrame] = None
    ) -> Dict[str, Any]:
        """Calculate metrics for individual positions based on active price history"""
        try:
            if returns.empty:
                return {}
            
            position_metrics = {}
            for ticker in returns.columns:
                # Use raw active price series if available to avoid artificial zero-dilution on newly listed assets
                if raw_prices is not None and ticker in raw_prices.columns:
                    raw_s = raw_prices[ticker].replace([np.inf, -np.inf], np.nan)
                    if raw_s.notna().sum() >= 2:
                        # Keep missing dates in the index while calculating
                        # returns; dropping them first would create a return
                        # spanning an unobserved interval.
                        ticker_returns = raw_s.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).dropna()
                    else:
                        ticker_returns = returns[ticker].replace([np.inf, -np.inf], np.nan).dropna()
                else:
                    ticker_returns = returns[ticker].replace([np.inf, -np.inf], np.nan).dropna()

                if not ticker_returns.empty:
                    data_points = len(ticker_returns)
                    is_limited = data_points < 30
                    metrics = self._calculate_basic_metrics(ticker_returns)
                    metrics.update(self._calculate_risk_metrics(ticker_returns))
                    metrics.update(self._calculate_drawdown_metrics(ticker_returns))
                    # SI-5: one precision block per leg, over that leg's OWN
                    # return observations - never the portfolio's count, which
                    # is the number a consumer cannot use to judge this leg.
                    metrics["estimate_uncertainty"] = self._estimate_uncertainty_block(
                        ticker_returns,
                        metrics,
                        scope=(
                            f"realized_risk position {ticker}: this leg's own "
                            "published return observations, not the portfolio's"
                        ),
                    )
                    position_metrics[ticker] = {
                        **metrics,
                        "weight": weights.get(ticker, 0),
                        "data_points": data_points,
                        "is_limited_history": is_limited,
                        "history_warning": f"Only {data_points} trading days in the analyzed window" if is_limited else None
                    }
            
            return position_metrics
        except Exception:
            return {}
            
    @staticmethod
    def _forecast_variance_path(forecast: Any, horizon: int, simulated: bool = False) -> np.ndarray:
        """Return the per-period variance path from an arch forecast.

        ``arch`` reports analytic GARCH variance as ``(1, horizon)`` and
        EGARCH simulation variance as ``(1, horizon, simulations)``.  The
        simulation axis is an ensemble dimension, not a time dimension, so it
        must be averaged before the caller cumulatively sums the periods.
        """
        values = np.asarray(forecast.variance.values, dtype=float)
        if values.ndim == 0:
            values = values.reshape(1)
        if simulated and values.ndim >= 3:
            values = values.mean(axis=tuple(range(2, values.ndim)))
        elif simulated and values.ndim == 2:
            # A few arch-compatible adapters drop the leading origin axis and
            # return ``(horizon, simulations)`` instead.  Distinguish that
            # from the ordinary analytic ``(1, horizon)`` shape.
            if values.shape[0] != 1 and values.shape[-1] >= values.shape[0]:
                values = values.mean(axis=-1)
        values = np.squeeze(values)
        if values.ndim == 0:
            path = values.reshape(1)
        elif values.ndim == 1:
            path = values
        else:
            # Analytic forecasts have one origin row; retain the last origin
            # row if a test double supplies more than one.
            path = values[-1]
        return np.asarray(path, dtype=float).reshape(-1)[: max(1, int(horizon))]

    @staticmethod
    def _cumulative_forecast_volatility(
        variance_path: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Convert per-period arch variances to cumulative horizon units.

        ``arch`` returns one conditional variance for each future period, not
        a cumulative terminal variance.  The public volatility field remains
        annualized (the h-day cumulative variance divided by h and scaled by
        252), while the return-space path is the unscaled h-day sigma used for
        VaR/ES.
        """
        values = np.maximum(np.asarray(variance_path, dtype=float), 0.0)
        cumulative = np.cumsum(values)
        steps = np.arange(1, len(cumulative) + 1, dtype=float)
        annualized = np.sqrt(cumulative * 252.0 / steps) / 100.0
        return_space = np.sqrt(cumulative) / 100.0
        return annualized, return_space

    @staticmethod
    def _tail_measure_disclosure(
        horizon: int,
        return_space_vol: float,
        var_forecast: float,
        cvar_forecast: float,
        var_clip_high: float = TAIL_CLIP_HIGH,
    ) -> Dict[str, Any]:
        """Declare what `var_forecast` / `cvar_forecast` are, in the units they are in.

        The two multipliers are the quantiles of the fitted models' OWN normal
        innovation distribution, so the numbers are defensible; what was not
        published was anything that let a reader know that.  Every field below
        exists because its absence produced a wrong inference:

        * `var_confidence_level` -- 1.645/2.06 are 95 % normal multipliers;
          undeclared, a reader could not tell 95 % from 99 %.
        * `var_units` / `volatility_forecast_units` -- the volatility is
          ANNUALIZED and the tail is an h-DAY RETURN.  They differ by
          sqrt(252 / h); treating a `annualized: true` object as if its VaR
          were annualized is wrong by 15.87x at h=1.
        * `var_sign_convention` -- the field is negative because a loss is
          negative, not because the sign is a forecast.
        * `cvar_to_var_ratio_fixed_by_construction` -- CVaR is the normal
          expected-shortfall multiple of the same sigma, so the ratio is
          2.06 / 1.645 for every input.  Publishing it as a measurement would
          be false; publishing it as an identity is true and lets a reader
          stop treating CVaR as independent information.
        """
        ratio = (
            TAIL_ES_MULTIPLIER / TAIL_Z_MULTIPLIER
            if TAIL_Z_MULTIPLIER
            else None
        )
        return {
            "var_confidence_level": TAIL_CONFIDENCE_LEVEL,
            "var_horizon_days": int(horizon),
            "var_units": f"{int(horizon)}_day_cumulative_return_decimal",
            "var_sign_convention": "negative_is_loss",
            "var_distribution": "normal",
            "var_method": "fitted_conditional_sigma_x_normal_quantile",
            "var_z_multiplier": TAIL_Z_MULTIPLIER,
            "cvar_method": "fitted_conditional_sigma_x_normal_expected_shortfall",
            "cvar_es_multiplier": TAIL_ES_MULTIPLIER,
            "cvar_to_var_ratio": ratio,
            "cvar_to_var_ratio_fixed_by_construction": True,
            "var_clip_bounds": [TAIL_CLIP_LOW, float(var_clip_high)],
            "var_clipped_by_bounds": bool(
                abs(var_forecast - float(np.clip(
                    -return_space_vol * TAIL_Z_MULTIPLIER, TAIL_CLIP_LOW, var_clip_high
                ))) > 1e-15
            ),
            "cvar_clip_bounds": [TAIL_CLIP_LOW, float(var_clip_high)],
            "volatility_forecast_units": "annualized",
            "annualization_note": (
                "`annualized` on the enclosing payload describes "
                "volatility_forecast ONLY. var_forecast and cvar_forecast are "
                f"{int(horizon)}-day returns and must NOT be annualized again."
            ),
            "return_space_volatility": float(return_space_vol),
        }

    async def _garch_forecast(self, returns: pd.Series, horizon: int) -> Dict[str, Any]:
        """GARCH volatility forecast with cumulative-horizon tail units.

        ``arch`` returns one conditional variance per future period.  The
        adapter sums that path before converting to return-space VaR/CVaR;
        applying a second ``sqrt(horizon / 252)`` would double-count time.

        The numeric core lives in :func:`volatility_forecast_point` so the
        precision disclosure's resampling restatement and this method are the
        SAME code and cannot drift apart.  See that function for why.
        """
        h = int(max(1, horizon))
        try:
            point = await asyncio.to_thread(
                volatility_forecast_point, returns, "GARCH", h
            )
        except _InsufficientForecast:
            return self._empty_forecast(h, "GARCH")
        except Exception as e:
            logger.error(f"GARCH forecast error: {e}")
            return self._empty_forecast(h, "GARCH", error="GARCH forecast failed")
        try:
            vol_final = point["volatility_forecast"]
            raw_vol_final = point["raw_volatility_forecast"]
            return_space_vol = point["return_space_volatility"]
            var_forecast = float(
                np.clip(-return_space_vol * TAIL_Z_MULTIPLIER, TAIL_CLIP_LOW, TAIL_CLIP_HIGH)
            )
            cvar_forecast = float(
                np.clip(-return_space_vol * TAIL_ES_MULTIPLIER, TAIL_CLIP_LOW, TAIL_CLIP_HIGH)
            )
            tail = self._tail_measure_disclosure(
                h, return_space_vol, var_forecast, cvar_forecast
            )

            return {
                "model": "GARCH",
                "horizon": h,
                "volatility_forecast": vol_final,
                "raw_volatility_forecast": raw_vol_final,
                "var_forecast": var_forecast,
                "cvar_forecast": cvar_forecast,
                # No interval.  The previous value was `vol * [0.8, 1.2]` --
                # a fixed +/-20 % haircut, exact to the last bit, carrying no
                # level and no sampling error.  A null plus a reason is the
                # only honest value; inventing a band is what created the
                # defect.  The point estimate's own precision is published
                # separately, as a measured resampling band, on
                # `precision.estimated_statistics` - see the route.
                "confidence_interval": None,
                "confidence_interval_status": "not_computed",
                "confidence_interval_reason": FORECAST_NO_INTERVAL_REASON,
                "tail_measure": tail,
                "term_structure": [
                    float(np.clip(v, FORECAST_VOL_CLIP_LOW, FORECAST_VOL_CLIP_HIGH))
                    for v in point["annualized_volatility_path"]
                ],
                "model_params": {
                    "p": 1,
                    "q": 1,
                    "type": "GARCH",
                    "forecast_method": "analytic",
                    "innovation_distribution": "normal",
                    "volatility_units": "annualized",
                    # Mirrored so the declaration actually reaches the artifact:
                    # the forecast route forwards `model_params` verbatim and
                    # nothing else from this dict.
                    "tail_measure": tail,
                    "confidence_interval_status": "not_computed",
                },
            }
        except Exception as e:
            logger.error(f"GARCH forecast error: {e}")
            return self._empty_forecast(
                h, "GARCH", error="GARCH forecast failed"
            )

    async def _egarch_forecast(self, returns: pd.Series, horizon: int) -> Dict[str, Any]:
        """EGARCH forecast using analytic h=1 and seeded simulation for h>1.

        The numeric core lives in :func:`volatility_forecast_point`, shared with
        the precision disclosure's resampling restatement.  See that function.
        """
        h = int(max(1, horizon))
        try:
            point = await asyncio.to_thread(
                volatility_forecast_point, returns, "EGARCH", h
            )
            method = point["forecast_method"]
            simulated = point["simulated"]
            vol_final = point["volatility_forecast"]
            raw_vol_final = point["raw_volatility_forecast"]
            return_space_vol = point["return_space_volatility"]
            # EGARCH's tail is clipped at 0.0 on the loss side, not at the
            # -0.001 floor GARCH/EWMA use; the bound travels with the number.
            egarch_clip_high = 0.0
            var_forecast = float(
                np.clip(
                    -return_space_vol * TAIL_Z_MULTIPLIER,
                    TAIL_CLIP_LOW,
                    egarch_clip_high,
                )
            )
            cvar_forecast = float(
                np.clip(
                    -return_space_vol * TAIL_ES_MULTIPLIER,
                    TAIL_CLIP_LOW,
                    egarch_clip_high,
                )
            )
            tail = self._tail_measure_disclosure(
                h, return_space_vol, var_forecast, cvar_forecast,
                var_clip_high=egarch_clip_high,
            )

            return {
                "model": "EGARCH",
                "horizon": h,
                "volatility_forecast": vol_final,
                "raw_volatility_forecast": raw_vol_final,
                "var_forecast": var_forecast,
                "cvar_forecast": cvar_forecast,
                # See `_garch_forecast`: null + reason, never a fabricated band.
                "confidence_interval": None,
                "confidence_interval_status": "not_computed",
                "confidence_interval_reason": FORECAST_NO_INTERVAL_REASON,
                "tail_measure": tail,
                "term_structure": [
                    float(np.clip(v, EGARCH_VOL_CLIP_LOW, FORECAST_VOL_CLIP_HIGH))
                    for v in point["annualized_volatility_path"]
                ],
                "model_params": {
                    "p": 1,
                    "q": 1,
                    "type": "EGARCH",
                    "forecast_method": method,
                    "simulations": FORECAST_SIMULATIONS if simulated else None,
                    # The seed is now the one arch actually reads on the
                    # simulation branch, so this is a true provenance claim
                    # rather than a number arch ignored. Published from the
                    # constant the forecast was drawn with, so the payload and
                    # the draw cannot drift apart.
                    "random_state": EGARCH_SIMULATION_SEED if simulated else None,
                    "innovation_distribution": "normal",
                    "volatility_units": "annualized",
                    "tail_measure": tail,
                    "confidence_interval_status": "not_computed",
                },
            }
        except _InsufficientForecast:
            return self._empty_forecast(h, "EGARCH")
        except Exception as e:
            logger.error(f"EGARCH forecast error: {e}")
            return self._empty_forecast(
                h, "EGARCH", error="EGARCH forecast failed"
            )
    
    def _ewma_forecast(self, returns: pd.Series, horizon: int) -> Dict[str, Any]:
        """EWMA volatility forecast (RiskMetrics 1996 single-pass recursion)."""
        try:
            h = max(1, horizon)
            # The numeric core is shared with the precision disclosure's
            # resampling restatement; see `volatility_forecast_point`.
            point = volatility_forecast_point(returns, "EWMA", h)
            lambda_val = EWMA_LAMBDA
            forecast_volatility = point["volatility_forecast"]
            raw_forecast_volatility = point["raw_volatility_forecast"]
            # RiskMetrics has no mean reversion: flat h-step term structure
            term_structure = [forecast_volatility] * h
            h_factor = np.sqrt(h / 252.0)
            # RiskMetrics has no distribution, so the normal quantiles below are
            # a STATED assumption, not a property of the fitted model.  The
            # disclosure says so rather than letting `model: EWMA` imply a
            # parametric tail it does not have.
            #
            # The tail is built from the core's RAW sigma, not the clipped
            # `volatility_forecast` this method used to multiply here.  On a
            # low-volatility book that sigma is below `FORECAST_VOL_CLIP_LOW`,
            # so the published VaR/CVaR were the 5 % floor's tail while the two
            # branches beside it published the raw sigma's tail -- the same
            # input yielding two different risk numbers depending on which
            # model was selected.  `volatility_forecast` itself stays clipped:
            # the term structure above and the public field keep their UI
            # bounds, and only the DERIVED risk measure moves to the raw sigma.
            #
            # THE MULTIPLICATION ORDER IS UNCHANGED, deliberately.  The defect
            # was the sigma, not the association; rewriting this as
            # `(raw * h_factor) * multiplier` reassociates the product and
            # moves a published value by one ULP on inputs where the clip was
            # already inert -- which
            # `test_forecast_precision_disclosure.py::test_every_model_series_and_horizon_is_bit_identical`
            # correctly catches.  Keeping `raw_sigma * M * h_factor` leaves every
            # already-correct input bit-identical and moves only the inputs the
            # clip was actually corrupting.
            raw_sigma = point["raw_volatility_forecast"]
            if raw_sigma is None or not np.isfinite(float(raw_sigma)):
                # Refuse, never substitute the clipped sigma for a missing one.
                raise ValueError("EWMA core published no finite raw sigma")
            raw_sigma = float(raw_sigma)
            return_space_vol = float(raw_sigma * h_factor)
            var_forecast = float(
                np.clip(
                    -raw_sigma * TAIL_Z_MULTIPLIER * h_factor,
                    TAIL_CLIP_LOW,
                    TAIL_CLIP_HIGH,
                )
            )
            cvar_forecast = float(
                np.clip(
                    -raw_sigma * TAIL_ES_MULTIPLIER * h_factor,
                    TAIL_CLIP_LOW,
                    TAIL_CLIP_HIGH,
                )
            )
            tail = self._tail_measure_disclosure(
                h, return_space_vol, var_forecast, cvar_forecast
            )
            tail["var_method"] = "ewma_sigma_x_normal_quantile"
            tail["var_distribution"] = "normal_assumed_no_parametric_fit"
            tail["var_distribution_note"] = (
                "RiskMetrics EWMA estimates variance only; it fits no "
                "distribution. The normal quantiles are a declared assumption, "
                "not a property of the model."
            )

            return {
                "model": "EWMA",
                "horizon": h,
                "volatility_forecast": forecast_volatility,
                "raw_volatility_forecast": raw_forecast_volatility,
                "var_forecast": var_forecast,
                "cvar_forecast": cvar_forecast,
                # See `_garch_forecast`: null + reason, never a fabricated band.
                "confidence_interval": None,
                "confidence_interval_status": "not_computed",
                "confidence_interval_reason": FORECAST_NO_INTERVAL_REASON,
                "tail_measure": tail,
                "term_structure": term_structure,
                "model_params": {
                    "lambda": lambda_val,
                    "type": "EWMA",
                    "innovation_distribution": "none_normal_assumed",
                    "volatility_units": "annualized",
                    "tail_measure": tail,
                    "confidence_interval_status": "not_computed",
                },
            }
        except Exception as e:
            logger.error(f"EWMA forecast error: {e}")
            return self._empty_forecast(h, "EWMA")
    
    @staticmethod
    def _ols_with_published_se(
        y: Any, X: Any, maxlags: int = 5
    ) -> tuple[Any, str, bool]:
        """OLS with a Newey-West (HAC) covariance, and the SE basis as a label.

        Returning the basis with the fit is the point.  A regression whose
        autocorrelation-corrected standard errors are computed and then
        discarded has paid for a correction no reader can see, and the
        uncorrected alternative must never be published as if it were robust.
        """
        try:
            model = sm.OLS(y, X).fit(
                cov_type="HAC", cov_kwds={"maxlags": maxlags}
            )
            return model, f"newey_west_hac_maxlags_{maxlags}", True
        except Exception:
            model = sm.OLS(y, X).fit()
            return model, "ols_uncorrected_hac_unavailable", False

    @staticmethod
    def _finite_param(series: Any, position: int) -> Optional[float]:
        """`series[position]` as a finite float, else ``None`` (never 0.0)."""
        try:
            value = float(series.iloc[position])
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return None
        return value if np.isfinite(value) else None

    def _calculate_factor_exposures(
        self, 
        returns: pd.DataFrame, 
        benchmark_returns: pd.Series, 
        weights: Dict[str, float]
    ) -> Dict[str, Any]:
        """Calculate factor exposures using OLS regression against market benchmark"""
        err_portfolio = {
            'alpha': None, 'annualized_alpha': None, 'market': None,
            'alpha_std_error': None, 'market_std_error': None,
            'std_error_basis': None, 'std_error_robust': None,
            'is_limited_history': False, 'history_warning': None,
            'data_points': 0, 'observations': 0,
            'error': 'insufficient data for factor regression'
        }
        try:
            if returns.empty:
                return {
                    'portfolio': dict(err_portfolio), 'positions': {},
                    'r_squared': None, 'adjusted_r_squared': None,
                    'error': 'insufficient data for factor regression'
                }

            positions_exp: Dict[str, Any] = {}
            if not benchmark_returns.empty and len(benchmark_returns) > 10:
                common_dates = returns.index.intersection(benchmark_returns.index)
                if len(common_dates) > 10:
                    aligned_returns = returns.loc[common_dates]
                    aligned_benchmark = benchmark_returns.loc[common_dates]

                    for ticker in aligned_returns.columns:
                        try:
                            s = aligned_returns[ticker]
                            # dropna, not `!= 0.0`: keeps genuine 0% days, drops
                            # pre-listing/no-trade NaN gaps
                            active = s.dropna().index.intersection(aligned_benchmark.index)
                            data_pts = int(len(active))
                            is_limited = data_pts < 30

                            if data_pts >= 10:
                                # Active-history filter: regress only on days the asset
                                # actually traded (zero-filled pre-listing rows would
                                # attenuate beta toward 0). HAC SEs, statsmodels-local.
                                X = sm.add_constant(aligned_benchmark.loc[active])
                                y = s.loc[active]
                                # The autocorrelation correction is only worth
                                # paying for if it is published: `cov_bse` is
                                # the SE the fit actually used, and a failed
                                # HAC fit is labelled uncorrected rather than
                                # silently passing off OLS errors as robust.
                                model, se_basis, se_robust = self._ols_with_published_se(
                                    y, X
                                )
                                alpha = float(model.params.iloc[0]) if len(model.params) > 0 else None
                                beta = float(model.params.iloc[1]) if len(model.params) > 1 else None
                                alpha_se = self._finite_param(model.bse, 0)
                                beta_se = self._finite_param(model.bse, 1)
                            else:
                                alpha = None
                                beta = None
                                se_basis = None
                                se_robust = False
                                alpha_se = None
                                beta_se = None

                            positions_exp[ticker] = {
                                'alpha': round(alpha, 6) if alpha is not None else None,
                                'annualized_alpha': round(alpha * 252.0, 4) if alpha is not None else None,
                                'market': round(beta, 4) if beta is not None else None,
                                # The correction that was computed and dropped
                                # is now the published uncertainty on the two
                                # coefficients above.
                                'alpha_std_error': round(alpha_se, 6) if alpha_se is not None else None,
                                'market_std_error': round(beta_se, 6) if beta_se is not None else None,
                                'std_error_basis': se_basis,
                                'std_error_robust': se_robust,
                                'is_limited_history': is_limited,
                                'history_warning': f"Only {data_pts} active trading days in the analyzed window" if is_limited else None,
                                'data_points': data_pts,
                                **({'error': 'insufficient history for factor regression'} if alpha is None else {})
                            }
                        except Exception:
                            positions_exp[ticker] = {
                                'alpha': None, 'annualized_alpha': None, 'market': None,
                                'alpha_std_error': None, 'market_std_error': None,
                                'std_error_basis': None, 'std_error_robust': None,
                                'is_limited_history': False, 'history_warning': None,
                                'data_points': 0, 'error': 'factor regression failed'
                            }

                    port_returns = self._calculate_portfolio_returns(aligned_returns, weights).dropna()
                    if not port_returns.empty:
                        try:
                            # The regression must run on the dates the published
                            # portfolio series actually contains.  The old mask
                            # ("any constituent traded") was wider than the
                            # series, so on a coverage-gated series
                            # `.loc[port_active]` could miss labels entirely.
                            port_coverage = active_return_coverage(
                                aligned_returns, weights
                            )
                            port_active = port_coverage.index[
                                port_coverage["published"]
                            ].intersection(aligned_benchmark.index)
                            port_active = port_active.intersection(port_returns.index)
                            if len(port_active) < 10:
                                raise ValueError("insufficient active portfolio history")
                            X_port = sm.add_constant(aligned_benchmark.loc[port_active])
                            port_model, port_se_basis, port_se_robust = (
                                self._ols_with_published_se(
                                    port_returns.loc[port_active], X_port
                                )
                            )
                            port_alpha = float(port_model.params.iloc[0]) if len(port_model.params) > 0 else None
                            port_beta = float(port_model.params.iloc[1]) if len(port_model.params) > 1 else None
                            port_alpha_se = self._finite_param(port_model.bse, 0)
                            port_beta_se = self._finite_param(port_model.bse, 1)
                            r_squared = round(float(port_model.rsquared), 4)
                            # Published UNCLIPPED, negatives included.
                            # `rsquared_adj` is 1-(1-R^2)(n-1)/(n-2), so it is
                            # negative whenever R^2 < 1/(n-1).  The fit is
                            # gated by `len(common_dates) > 10` above, so 11 is
                            # the smallest sample this section can publish and
                            # the sign boundary sits at 1/(n-1) = 0.100 there --
                            # a threshold an ordinary 4-name book against a
                            # benchmark clears by nothing.  The `max(0.0, ...)`
                            # that stood here published 0.0 for every such fit: a
                            # model explaining 5% of variance reported the same
                            # number as a model explaining none, and 0.0 is also
                            # what a fit explaining NONE would publish on its
                            # own terms, so no threshold reading the field could
                            # tell the three apart.  The negative value carries
                            # the real information -- the model is worse than
                            # the sample mean -- and the identity the rest of the
                            # repo checks the pair against
                            # (`tests/test_model_sample_and_aggregation_disclosure.py`)
                            # only holds for the unclipped value.  `r_squared`
                            # itself is never negative, so the pair's own
                            # invariant `adjusted <= raw` is preserved.
                            adj_r_squared = round(float(port_model.rsquared_adj), 4)
                            return {
                                'portfolio': {
                                    'alpha': round(port_alpha, 6) if port_alpha is not None else None,
                                    'annualized_alpha': round(port_alpha * 252.0, 4) if port_alpha is not None else None,
                                    'market': round(port_beta, 4) if port_beta is not None else None,
                                    'alpha_std_error': round(port_alpha_se, 6) if port_alpha_se is not None else None,
                                    'market_std_error': round(port_beta_se, 6) if port_beta_se is not None else None,
                                    'std_error_basis': port_se_basis,
                                    'std_error_robust': port_se_robust,
                                    'observations': int(len(port_active)),
                                },
                                'positions': positions_exp,
                                'r_squared': r_squared,
                                'adjusted_r_squared': adj_r_squared
                            }
                        except Exception as pe:
                            logger.warning(f"Portfolio factor regression failed: {pe}")
                            return {
                                'portfolio': dict(err_portfolio),
                                'positions': positions_exp,
                                'r_squared': None, 'adjusted_r_squared': None,
                                'error': 'portfolio factor regression failed'
                            }

            # No usable benchmark window: fill ONLY tickers not already computed
            for ticker in returns.columns:
                if ticker not in positions_exp:
                    positions_exp[ticker] = {
                        'alpha': None, 'annualized_alpha': None, 'market': None,
                        'is_limited_history': False, 'history_warning': None,
                        'data_points': 0, 'error': 'insufficient data for factor regression'
                    }
            return {
                'portfolio': dict(err_portfolio),
                'positions': positions_exp,
                'r_squared': None, 'adjusted_r_squared': None,
                'error': 'insufficient data for factor regression'
            }
        except Exception as e:
            logger.error(f"Factor exposure calculation error: {e}")
            return {
                'portfolio': dict(err_portfolio), 'positions': {},
                'r_squared': None, 'adjusted_r_squared': None,
                'error': 'factor exposure calculation failed'
            }

    # Empty result methods for error handling
    
    def _empty_metrics(self) -> Dict[str, Any]:
        return {
            "annual_return": None,
            "annual_volatility": None,
            "sharpe_ratio": None,
            "sortino_ratio": None,
            "skewness": None,
            "kurtosis": None,
            "max_drawdown": None,
            "var_95": None,
            "cvar_95": None,
            "hit_ratio": None,
            "observations": 0,
            "active_observations": 0,
            "positions": {},
            "error": "Insufficient data for calculations"
        }
    
    def _empty_forecast(
        self,
        horizon: int = 1,
        model: str = "GARCH",
        error: str = "Insufficient data for forecast",
    ) -> Dict[str, Any]:
        h = max(1, horizon)
        return {
            "model": model,
            "horizon": h,
            "volatility_forecast": None,
            "var_forecast": None,
            "cvar_forecast": None,
            # An unavailable forecast has no point estimate, so it has no band
            # either -- and the reason travels with the null so a consumer
            # never reads the absence as a transport failure.
            "confidence_interval": None,
            "confidence_interval_status": "not_computed",
            "confidence_interval_reason": FORECAST_NO_INTERVAL_REASON,
            "tail_measure": None,
            "term_structure": None,
            "model_params": None,
            "error": error
        }
    
    def _empty_factor_exposure(self) -> Dict[str, Any]:
        return {
            "portfolio": {
                "alpha": None,
                "market": None
            },
            "positions": {},
            "r_squared": None,
            "adjusted_r_squared": None,
            "error": "Insufficient data for factor analysis"
        }
    
    def _empty_concentration(self) -> Dict[str, Any]:
        return {
            "largest_position": 0.0,
            "top_3": 0.0,
            "top_5": 0.0,
            "top_10": 0.0,
            "herfindahl_index": 0.0,
            "effective_positions": 0.0,
            "diversification_score": 0.0,
            "diversification_ratio": 1.0,
            "gini_coefficient": 0.0,
            # The disclosure keys are published here too, so a consumer sees one
            # shape rather than two. `n_holdings` is 0 because no holding was
            # measured -- that is a true statement about an absent book. The
            # three numbers above are NOT: diversification_score 0.0 on an empty
            # book is indistinguishable from a measured single-holding book, the
            # same class of defect the liquidity `_empty_liquidity` comment
            # records (V3-09). Left exactly as they were -- changing them is
            # outside this disclosure, and a consumer that needs the difference
            # has `error` and `n_holdings` == 0 to read it from.
            "n_holdings": 0,
            "scale": dict(CONCENTRATION_DIVERSIFICATION_SCALE),
            "diversification_score_formula": (
                CONCENTRATION_DIVERSIFICATION_SCORE_FORMULA
            ),
            "diversification_ratio_formula": (
                CONCENTRATION_DIVERSIFICATION_RATIO_FORMULA
            ),
            "effective_positions_note": CONCENTRATION_EFFECTIVE_POSITIONS_NOTE,
            "by_weight": {},
            "error": "No position data available"
        }
    
    def _empty_liquidity(self) -> Dict[str, Any]:
        # An unavailable result claims nothing.  Returning a plausible
        # overall_score=5.0 / risk_level="Medium" / "5-10" made an absence
        # indistinguishable from a measured mid-liquidity portfolio (V3-09).
        # The volume split is all zeros because no position was measured:
        # publishing `low_volume_pct=100` asserted a worst-case book nobody
        # observed.
        return {
            "overall_score": None,
            "overall_score_raw": None,
            "liquidation_time_days": None,
            "risk_level": None,
            "overall_band": None,
            "by_position": {},
            "volume_stats": {
                "avg_volume": 0,
                "total_portfolio_volume": 0,
                "high_volume_pct": 0,
                "medium_volume_pct": 0,
                "low_volume_pct": 0
            },
            "score_band_rule": dict(LIQUIDITY_SCORE_BAND_RULE),
            "error": "No liquidity data available"
        }
    
    def _empty_stress_test(self) -> Dict[str, Any]:
        # Mirrors the success payload key-for-key with None values: with no
        # price history there is no proxy, no recovery estimate, no confidence
        # label and no shock input to report.
        return {
            "scenario": "unknown",
            "scenario_description": None,
            "max_drawdown": None,
            "max_drawdown_basis": None,
            "max_drawdown_formula": None,
            "portfolio_impact": None,
            "impact_basis": None,
            "position_impacts": {},
            "recovery_time": None,
            "recovery_time_basis": None,
            "confidence_level": None,
            "confidence_basis": None,
            "shock_inputs": None,
            "units": None,
            "methodology": None,
            "error": "Insufficient data for stress testing"
        }
    
    def _empty_volatility_sizing(
        self,
        reason: Optional[str] = None,
        unmeasurable_pairs: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """The refusal payload.

        `reason` / `unmeasurable_pairs` let a caller say WHICH measurement was
        refused rather than falling back to the generic "insufficient data",
        so a book rejected for an unmeasurable correlation is never mistaken
        for a book that had no history at all.
        """
        unavailable = reason or "sizing unavailable: no measured return history"
        pairs = list(unmeasurable_pairs or [])
        return {
            "current_weights": {},
            "recommended_weights": {},
            "trades": {},
            "target_volatility": 0.15,
            "current_volatility": None,
            "current_volatility_basis": None,
            "current_volatility_reason": unavailable,
            "current_volatility_unmeasurable_pairs": pairs,
            "current_volatility_sample_covariance": None,
            "current_volatility_sample_covariance_reason": unavailable,
            # Absent, not zero and not the target: nothing was measured.
            "achieved_volatility": None,
            "achieved_volatility_basis": "sample_covariance_of_measured_returns",
            "achieved_volatility_reason": unavailable,
            "sizing_volatility": None,
            "sizing_volatility_basis": None,
            "sizing_volatility_reason": unavailable,
            "sizing_volatility_unmeasurable_pairs": pairs,
            "imposed_target_volatility": None,
            "imposed_target_volatility_basis": None,
            "recommended_volatility_sample_covariance": None,
            "recommended_volatility_sample_covariance_reason": unavailable,
            "error": "Insufficient data for volatility sizing"
        }
    
    def _empty_risk_score(self) -> Dict[str, Any]:
        return {
            "overall_score": None,
            # Null, not 0.0: nothing was measured. Published beside the score for
            # the same reason `liquidity` publishes it -- the pair is what lets a
            # consumer tell a rounded display value from the value it came from
            # without re-deriving it.
            "overall_score_raw": None,
            "risk_level": None,
            "change": None,
            "components": {
                "concentration": None,
                "volatility": None,
                "correlation": None,
                "factor_risk": None,
                "market_risk": None
            },
            # Nothing was measured, so there is no composition to describe. The
            # absence is stated rather than left implicit, because a consumer
            # that reads `score_audit` on every other response has to be able to
            # tell "no legs" from "a payload shape that predates the disclosure".
            "saturated_components": [],
            "duplicate_components": [],
            "independent_component_count": None,
            "score_audit": None,
            "score_audit_reason": "no risk sub-score was measured",
            "alerts": ["Insufficient data for comprehensive risk analysis"],
            "error": "Insufficient data for risk scoring"
        }


# ---------------------------------------------------------------------------
# Volatility forecast: the point, and the precision of the point (ENV-020)
# ---------------------------------------------------------------------------
# `volatility_forecast` is the one genuinely ESTIMATED quantity this section
# publishes: the terminal conditional sigma of a model fitted to a measured
# return series.  `var_forecast` and `cvar_forecast` are a DECLARED normal
# quantile times that sigma, so they are deterministic functions of a published
# number plus a published constant and carry no independent uncertainty.  The
# z / ES multipliers, the confidence level and the horizon are declared
# parameters with no sampling distribution at all.
#
# The precision of the estimated quantity is measured the only way it can be:
# the model is RE-FITTED on every moving-block resample and the dispersion of the
# re-fitted terminal sigma is the standard error.  Nothing about a conditional
# volatility forecast has a usable closed-form standard error, and the
# alternative - publishing an interval around a function of an already-published
# sigma - would describe a number the reader can already see.


class _InsufficientForecast(Exception):
    """Too few finite returns for a volatility forecast at all.

    Distinct from every other failure on purpose.  The three forecast methods
    report "Insufficient data for forecast" for this case and
    "<MODEL> forecast failed" for everything else, and that distinction is a
    published string, so it cannot be collapsed into one handler.
    """


def volatility_forecast_point(
    returns: Any, model: str = "GARCH", horizon: int = 1
) -> Dict[str, Any]:
    """The engine's OWN conditional-volatility point, as a pure synchronous core.

    This is the single source of truth for what the section publishes as
    `volatility_forecast`, `raw_volatility_forecast` and
    `return_space_volatility`, for all three models.  It exists because
    :func:`volatility_forecast_statistics` has to re-run exactly this
    computation once per resample, and a restatement written as a second copy
    of a GARCH fit is a restatement that will drift: the day the clip bound or
    the arch call options change here and not there, the band silently stops
    describing the published number and `measure_estimate_uncertainty`'s
    reproduction guard will withhold it for a reason that has nothing to do
    with precision.

    `AnalyticsEngine._garch_forecast` / `_egarch_forecast` / `_ewma_forecast`
    call this too, so the published value and the resampled value are the same
    code by construction rather than by review.

    Raises `_InsufficientForecast` below the model's minimum sample and
    propagates any other failure (a failed fit, a non-finite variance path).
    """
    h = int(max(1, int(horizon)))
    name = str(model or "GARCH").upper()
    # Anything that is not EWMA or EGARCH is fitted as GARCH, which is the same
    # fallback `forecast_volatility`'s own dispatch applies. `returns` is held to
    # the pandas interface the three forecast methods have always been handed:
    # a non-pandas input raises here exactly as it raised there, rather than
    # being quietly accepted and producing a number where there used to be none.
    clean = returns.replace([np.inf, -np.inf], np.nan).dropna()
    clean = clean.clip(lower=-0.20, upper=0.20)

    if name == "EWMA":
        # Single-pass recursion:
        # sigma^2_t = lambda*sigma^2_{t-1} + (1-lambda)*r^2_{t-1}
        # NOTE the absent minimum-sample gate.  EWMA has never had one - the
        # recursion is a closed form over whatever it is handed - and adding one
        # here would have turned a published number into a null.  The 30-day
        # floor that does apply to this section lives on
        # `AnalyticsEngine.forecast_volatility`, above the model dispatch.
        r = clean.to_numpy(dtype=float)
        # The seed is the variance OF THE WINDOW THIS RECURSION ITERATES OVER,
        # and was the FULL-sample population variance.  That let a full-history
        # statistic survive into a number that reads as a 60-observation
        # recursion: after the last recursion the seed still carries
        # 0.94**60 = 2.4 % of itself, and on a SHORT window it carries far
        # more - 0.94**25 = 21 % at n=25 - so the shorter the history, the more
        # of the answer came from outside the window.  A regime that ended
        # 300 rows ago could not decay out of the published volatility.
        #
        # ddof=1, not 0, to match `engine_risk_statistics.annual_volatility`
        # (:2236), the sibling restatement of this engine's own realized
        # volatility.  Below 2 window observations a sample variance is
        # undefined, so the seed falls back to 0.0 and the recursion - and
        # every field derived from it below - publishes a 0.0 sigma.
        #
        # That is NOT the contract `volatility_service.calculate_ewma_volatility`
        # (:231) uses: it WITHHOLDS instead, returning None for a single
        # observation (:271-276) and raising ValueError on empty input
        # (:267-270), because 0.0 is not a missing measurement but the
        # strongest possible claim - "this book does not move" - and it stays
        # rankable against the realized-vol distribution, where any
        # non-negative p25 puts it in the CHEAP band.  A book with no
        # measurable volatility is not cheap.  The two paths were previously
        # documented as sharing one contract; they do not, and closing that
        # difference here is a separate decision from this comment.
        window = r[-min(len(r), 60):]
        var = float(np.var(window, ddof=1)) if len(window) > 1 else 0.0
        for x in window:
            var = EWMA_LAMBDA * var + (1.0 - EWMA_LAMBDA) * x * x
        raw = float(np.sqrt(max(0.0, var) * 252))
        if not np.isfinite(raw):
            # Refuse rather than fall back to the clipped path below.  Every
            # other consumer of this raw value (`_volatility_sizing`'s
            # inverse-volatility parity) reads `raw_volatility_forecast`
            # directly, so a non-finite raw that quietly became the 5% floor
            # here would put a fabricated risk measure on the wire while the
            # sizing leg read the same field as though it were measured.  This
            # is the same contract the GARCH/EGARCH branch applies to its
            # variance path (:6640).  Both enclosing handlers treat a refusal
            # as an absent measurement rather than a number:
            # `volatility_forecast_statistics` counts the draw NaN and
            # `_ewma_forecast`'s `except` returns the empty-forecast contract,
            # where `var_forecast`, `cvar_forecast` and `tail_measure` are all
            # None.  (That handler's published `error` string is
            # `_empty_forecast`'s default -- pre-existing, and not this
            # function's to relabel.)
            raise ValueError("EWMA recursion produced a non-finite sigma")
        annualized = np.array([float(np.clip(raw, FORECAST_VOL_CLIP_LOW,
                                            FORECAST_VOL_CLIP_HIGH))] * h)
        return {
            "model": "EWMA",
            "horizon": h,
            "volatility_forecast": float(annualized[-1]),
            "raw_volatility_forecast": raw,
            # The RAW sigma, not `annualized[-1]`.  This is the convention the
            # GARCH/EGARCH branch already follows (:6652, built from the
            # un-clipped `return_space_path`), and `return_space_volatility` is
            # what VaR and CVaR are derived from -- so reading the clipped path
            # here published a 3%-volatility book at a VaR computed from the
            # 5% floor, 73% high, while the public `volatility_forecast`
            # beside it stayed correctly clipped for UI bounds.  The sizing leg
            # made the same distinction at :4628-4631 for the same reason: a
            # clip is a display bound, not a measurement.  `np.isfinite` rather
            # than the builtin `min`, which returns 5.9 for `min(5.9, nan)`
            # and would let a NaN through as the clipped value.
            "return_space_volatility": float(raw * np.sqrt(h / 252.0)),
            "annualized_volatility_path": annualized,
            "forecast_method": "riskmetrics_recursion",
            "simulated": False,
        }

    if len(clean) < 20:
        raise _InsufficientForecast(
            f"{len(clean)} finite return(s) is below the 20 a volatility model "
            "needs to be fitted at all"
        )

    name = "EGARCH" if name == "EGARCH" else "GARCH"
    clip_low = EGARCH_VOL_CLIP_LOW if name == "EGARCH" else FORECAST_VOL_CLIP_LOW
    # Scale returns by 100 for arch optimizer numerical convergence stability.
    scaled = clean * 100.0
    if name == "EGARCH":
        model_obj = arch_model(scaled, vol="EGARCH", p=1, q=1, dist="normal",
                               rescale=False)
        fitted = model_obj.fit(disp="off", show_warning=False)
    else:
        model_obj = arch_model(scaled, vol="Garch", p=1, q=1, dist="normal",
                               rescale=False)
        fitted = model_obj.fit(disp="off", show_warning=False,
                               options={"maxiter": 100})

    if name == "EGARCH" and h > 1:
        # Simulation here is NOT a choice.  arch 8.0.0 refuses an analytic
        # multi-step EGARCH forecast outright - `ValueError: Analytic forecasts
        # not available for horizon > 1`, raised by `_check_forecasting_method`
        # because the EGARCH log-variance recursion does not evolve in squares.
        # The innovation is `dist="normal"`, so this is not a fat-tail
        # limitation; no distribution this engine can configure would make the
        # analytic path exist.  Simulation is the only route.
        #
        # WHAT WAS ACTUALLY WRONG is the seed, and the seed the engine passed was
        # never read.  `forecast(..., random_state=100)` puts an int where arch
        # documents a `np.random.RandomState`, and `ARCHVolatility.forecast`
        # forwards `random_state` to `_bootstrap_forecast` ONLY - never to
        # `_simulation_forecast` (volatility.py:762-797).  The simulation branch
        # draws from `rng`, which `ConstantMean.forecast` fills from
        # `self._distribution.simulate(dp)` (mean.py:998), and the model built
        # above leaves that distribution unseeded.  Passing a real
        # `RandomState(100)` does not help either; only `rng` is read on this
        # branch.  So the published point was one arbitrary draw, and two
        # forecasts from the same fitted model already differed in the 4th
        # decimal.
        #
        # `rng` takes a CALLABLE, not a Generator: a `np.random.Generator` is not
        # callable and arch rejects it with TypeError, so the bound sampler is
        # what is passed.  It is taken from a fresh instance of the model's OWN
        # distribution class rather than written out as a normal draw, so the
        # innovation law is preserved by construction instead of by a literal
        # that would silently keep feeding Gaussian shocks if `dist` were ever
        # changed to a class with estimated shape parameters - StudentsT's
        # simulator reads `self._parameters`, which a fresh instance does not
        # have, so that case raises here rather than returning a wrong law.  The
        # instance is rebuilt on every call, so the stream restarts at the same
        # point each time instead of advancing.
        seeded = type(fitted.model.distribution)(seed=EGARCH_SIMULATION_SEED)
        forecast = fitted.forecast(
            horizon=h,
            method="simulation",
            simulations=FORECAST_SIMULATIONS,
            rng=seeded.simulate([]),
        )
        simulated, method = True, "simulation"
    else:
        forecast = fitted.forecast(horizon=1 if name == "EGARCH" else h,
                                   method="analytic")
        simulated, method = False, "analytic"

    variance_path = AnalyticsEngine._forecast_variance_path(forecast, h,
                                                            simulated=simulated)
    if variance_path.size == 0 or not np.isfinite(variance_path).all():
        raise ValueError(f"arch returned no finite {name} variance path")
    variance_path = np.maximum(variance_path, 0.0)
    annualized_path, return_space_path = (
        AnalyticsEngine._cumulative_forecast_volatility(variance_path)
    )
    raw = float(annualized_path[-1])
    clipped = np.clip(annualized_path, clip_low, FORECAST_VOL_CLIP_HIGH)
    return {
        "model": name,
        "horizon": h,
        "volatility_forecast": float(clipped[-1]),
        "raw_volatility_forecast": raw,
        "return_space_volatility": float(return_space_path[-1]),
        "annualized_volatility_path": [float(v) for v in clipped],
        "forecast_method": method,
        "simulated": simulated,
    }


#: Resamples spent on the PORTFOLIO leg's refit.  The full
#: :data:`UNCERTAINTY_BOOTSTRAP_RESAMPLES`, because this is the number the
#: section is named for and it is the one re-fit set the export can afford.
FORECAST_PORTFOLIO_REFIT_RESAMPLES = UNCERTAINTY_BOOTSTRAP_RESAMPLES

#: The draw count a POSITION leg's re-fit bootstrap WOULD need, published because
#: it is not spent.  This is a record of a declined cost, not a knob: no leg is
#: re-fitted, so nothing reads this except the reason text a leg publishes.
#:
#: WHY NO LEG IS RE-FITTED.  Measuring a fitted leg's conditional sigma means
#: re-running the ARCH optimiser once per draw - a full fit, not a vectorised
#: reduction - so a book of N legs costs N times what one costs.  Measured on the
#: real 14-position book: 1001 refits for the portfolio leg cost 17.3 s, and 200
#: per leg across the fourteen legs cost a further 51.3 s - 3801 fits in total,
#: and the arithmetic is the point: the 1001 is the
#: :data:`FORECAST_PORTFOLIO_REFIT_RESAMPLES` RESAMPLED fits plus the one original
#: fit the section measured, so it is `RESAMPLES + 1` and not a round number, and
#: `1001 + 200 * 14 = 3801`.  An earlier version of this comment said "3800 fits
#: in total" beside those same two parts, which is the arithmetic defect the
#: `measurements_withheld.why_not_measured` prose still carries on the route
#: module.  On
#: a host a few times slower that is more than this section's 180 s assembly
#: budget (`ai_context_service._SECTION_TIMEOUT_SECONDS`), and a section that
#: overruns its budget is not merely slow: `asyncio.wait_for` cancels the
#: coroutine but cannot cancel the thread the refits are already running on, so
#: the optimiser keeps burning CPU against every section collected after it.
#: Three sections (factor_exposure, optimization, regime) were published
#: `unavailable` for exactly that reason and seven more degraded to `partial`.
#:
#: A per-leg forecast is DERIVED from that leg's own inputs, and its precision
#: belongs to those inputs rather than to a fresh bootstrap per leg.  So the leg
#: states the truth instead: estimated, not separately measured, and here is
#: what it does publish and why the band is missing.  A withheld figure is an
#: honest outcome; an invented one is the defect this disclosure exists to fix,
#: and so is a figure that costs three other sections their output.
#:
#: 200 is this module's own published floor for a percentile interval to mean
#: anything (:data:`PAIRWISE_STATISTIC_MIN_RESAMPLES`).  It is the floor the
#: declined measurement would have used, and it is named here so a reader can
#: see that what was dropped was a real interval rather than a token one.
FORECAST_LEG_REFIT_RESAMPLES_WITHHELD = PAIRWISE_STATISTIC_MIN_RESAMPLES

#: Published on every block in this section's precision disclosure, so the
#: count a reader is looking at - or not looking at - is on the payload rather
#: than in a diff.
FORECAST_REFIT_COUNT_RULE = (
    "the portfolio leg is resampled at the module's standard "
    f"{FORECAST_PORTFOLIO_REFIT_RESAMPLES} circular moving-block draws, and its "
    "conditional sigma is the only figure on this section measured by re-fitting "
    "the model. No position leg is re-fitted. A leg's volatility_forecast comes "
    "out of the same kind of ARCH fit, so measuring it would mean one optimiser "
    f"run per draw, {FORECAST_LEG_REFIT_RESAMPLES_WITHHELD} of them at this "
    "module's own floor for a percentile interval, and once per leg of the book. "
    "On the measured 14-position book that was 2800 additional optimiser runs "
    "and roughly 51 s of pure refit time, which does not fit the 180 s budget this "
    "section is assembled under - and overrunning that budget costs OTHER "
    "sections their output, because the cancelled refit thread keeps running. So "
    "each leg publishes a null standard error with the reason, and the "
    f"declined count is published here as {FORECAST_LEG_REFIT_RESAMPLES_WITHHELD}"
    ". The count actually spent is published as bootstrap_resamples on each "
    "block, where a leg that was not measured reads 0"
)


def volatility_forecast_statistics(
    model: str = "GARCH",
    horizon: int = 1,
    fields: tuple[str, ...] = ("volatility_forecast", "return_space_volatility"),
) -> Any:
    """A resampling statistic that RE-FITS the volatility model on every draw.

    Returned as a single callable rather than the `{field: callable}` mapping
    the other providers here use, and deliberately so: one fit produces every
    field, and the mapping form would re-run the optimiser once per field.  On
    a two-field block that doubles a ~15 s leg for no additional information.
    `measure_estimate_uncertainty` accepts either shape
    (`_statistic_matrix_from`), so this costs the caller nothing.

    A draw that cannot produce a finite value - a fit that does not converge, a
    variance path that goes non-finite - is reported as NaN and counted in the
    published `status`, never quietly dropped.  Dropping it would shrink the
    sample the percentile interval is read off without saying so.
    """
    names = tuple(fields)

    def volatility_forecast(block: Any) -> Dict[str, np.ndarray]:
        column = _statistic_column(block)
        draws = int(column.shape[1]) if column.ndim == 2 else 0
        out = {name: np.full(draws, np.nan, dtype=float) for name in names}
        for index in range(draws):
            try:
                point = volatility_forecast_point(
                    pd.Series(column[:, index]), model, horizon
                )
            except Exception:  # noqa: BLE001 - a failed draw is NaN, not a band
                continue
            for name in names:
                value = point.get(name)
                if value is not None and np.isfinite(float(value)):
                    out[name][index] = float(value)
        return out

    return volatility_forecast


# Global analytics engine instance
class GlobalAnalyticsEngine:
    """Global analytics engine for dependency injection"""
    
    def __init__(self):
        self._analytics_engine = AnalyticsEngine()
    
    def get_engine(self) -> AnalyticsEngine:
        return self._analytics_engine