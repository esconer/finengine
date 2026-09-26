"""The four open defects in the holding-window / risk-score cluster.

D-01 `realized_risk` published a bare `covered_days` with no unit. It is the
reference section `factor_exposure`, `risk_contribution`, `tear_sheet` and
`regime` are all defined against, so the one count a consumer reads first was
the only one whose unit was undeclared.

D-02 The per-ticker counts answered three different questions under three
names. `raw_days` and `masked_days` are PRICE rows; `return_observations` is the
RETURN row count those held prices produced, so on a leg with interior missing
bars the pair is not reconcilable on its face (the v4 export read
`raw_days=108, masked_days=23, return_observations=20` for NIFTYIETF.NS). One
rule now: the per-ticker block measures a price frame, it declares that with
`per_ticker_count_units`, and it publishes the measured terms that relate the
two frames, so the residual is a count of real missing bars instead of a
mystery.

D-06 Two R-squared for one factor model, neither window declared:
`factor_exposure` fitted 0.6511 over 174 full-history observations while the risk
score drove a user-facing "High unexplained risk" alert off 0.2391 fitted over
39 holding-window observations, with nothing to tell a reader they are different
models. The risk score now publishes the factor leg's window, sample and basis
beside the statistic.

D-08 `_build_wide_returns` filtered holdings to the leg's active tickers when it
fetched price data but not when it built the mask cutoff, so a persisted
zero-value row could set the window start and mask a book to a window it has no
price data for.

The rule tests at the bottom drive the real audit rules
(`app.debugging.context_audit`) over the payloads these routes actually
publish, because "the label is non-empty" is only a fix if the rule that
complained about it stops complaining.

No network, no DB, seeded RNG only.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest

from app.api import analytics as analytics_mod
from app.api.analytics import (
    HOLDING_COVERED_DAYS_SCOPE,
    PRICE_FRAME_COUNT_UNITS,
    PRICE_ROW_RECONCILIATION_IDENTITY,
    PRICE_ROW_RECONCILIATION_SCOPE,
    RISK_SCORE_FACTOR_BASIS,
    _build_wide_returns,
    _factor_leg_evidence,
    _price_frame_count_reconciliation,
    get_realized_risk,
    get_risk_score,
)
from app.models.database import PortfolioPosition
from app.services.analytics_engine import AnalyticsEngine

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
# GAP.NS is the export's NIFTYIETF.NS shape reproduced exactly: 23 held price
# rows split into three runs by three missing bars forming two holes, so it
# produces 20 return observations and a 3-row gap that no single row frame
# explains (the audit's tolerated gap is 2).
BARS = 140
GAP_POSITIONS = 25
# Offsets back from the last delivered bar. 6 and 5 are adjacent (one hole), 2
# is isolated (a second hole), so the held prices form three runs.
GAP_MISSING = (6, 5, 2)


def _frame(ticker: str, *, gap: bool = False, days: int = BARS, seed: int = 7) -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-09-25", periods=days)
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.011, days)))
    if gap:
        # Interior missing bars inside the delivered window: two adjacent (one
        # hole) and one isolated (a second hole), so the held prices form three
        # runs and no return can cross either hole.
        drop = {dates[days - 1 - offset] for offset in GAP_MISSING}
        dates = pd.DatetimeIndex([d for d in dates if d not in drop])
        keep = pd.Series(close, index=pd.bdate_range(end="2026-09-25", periods=days)).loc[dates]
        close = keep.to_numpy()
    return pd.DataFrame({"date": dates, "adj_close": close, "volume": np.full(len(dates), 1e6)})


def _rows(rows):
    scalars = MagicMock()
    scalars.all.return_value = list(rows)
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _db(positions):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=lambda *_a, **_k: _rows(positions))
    return db


def _pos(ticker: str, *, added_on, weight=0.5, buy_price=None, market_value=10000.0):
    return PortfolioPosition(
        id=1, ticker=ticker, weight=weight, quantity=10.0, buy_price=buy_price,
        last_price=100.0, market_value=market_value, region="IN", sector="X",
        industry="Y", added_on=added_on,
    )


class _WindowedMarket:
    """Price frames served for the REQUESTED window only."""

    def __init__(self, frames: Dict[str, pd.DataFrame]):
        self.frames = frames
        self.requests: List[tuple] = []
        self.fetch_historical_data = AsyncMock(side_effect=self._fetch)

    async def _fetch(self, ticker, start, end):
        self.requests.append((ticker, start, end))
        frame = self.frames.get(ticker)
        if frame is None or frame.empty:
            return pd.DataFrame()
        low = pd.Timestamp(start).normalize() if start else frame["date"].min()
        high = pd.Timestamp(end).normalize() if end else frame["date"].max()
        sliced = frame.loc[(frame["date"] >= low) & (frame["date"] <= high)]
        return sliced.copy()


def _book() -> Dict[str, Any]:
    """One book: an old leg, a recent leg and a leg with interior missing bars."""
    dates = pd.bdate_range(end="2026-09-25", periods=BARS)
    old_added = dates[3].to_pydatetime()          # outside the holding window
    recent_added = dates[BARS - 1 - GAP_POSITIONS].to_pydatetime()
    frames = {
        "OLD.NS": _frame("OLD.NS", seed=11),
        "NEW.NS": _frame("NEW.NS", seed=13),
        "GAP.NS": _frame("GAP.NS", gap=True, seed=17),
    }
    positions = [
        _pos("OLD.NS", added_on=old_added, weight=0.4),
        _pos("NEW.NS", added_on=recent_added, weight=0.35),
        _pos("GAP.NS", added_on=old_added, weight=0.25),
    ]
    return {
        "frames": frames,
        "positions": positions,
        "market": _WindowedMarket(frames),
        "intersection_start": str(dates[BARS - 1 - GAP_POSITIONS].date()),
    }


def _benchmark():
    dates = pd.bdate_range(end="2026-09-25", periods=BARS)
    rng = np.random.default_rng(3)
    series = pd.Series(rng.normal(0.0004, 0.01, BARS), index=dates)
    return MagicMock(get_returns=AsyncMock(return_value=series))


async def _realized_risk_payload():
    book = _book()
    db = _db(book["positions"])
    return await get_realized_risk(
        tickers="OLD.NS,NEW.NS,GAP.NS", start="2026-01-01", end="2026-09-25",
        db=db, data_service=book["market"], analytics_engine=AnalyticsEngine(),
    ), book


# ---------------------------------------------------------------------------
# D-01
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_realized_risk_declares_the_unit_of_its_own_count():
    """D-01: the reference section publishes the label its siblings publish."""
    res, _book_ = await _realized_risk_payload()
    coverage = res["history_coverage"]
    assert coverage["covered_days"] > 0
    assert coverage["covered_days_scope"] == HOLDING_COVERED_DAYS_SCOPE
    # Not merely non-empty: the same literal the four sibling sections publish,
    # so a consumer can join on the scope instead of parsing prose.
    assert coverage["covered_days_scope"] == "holding_window_aligned_return_rows"


@pytest.mark.asyncio
async def test_realized_risk_scope_joins_the_sibling_windows():
    """D-01 + XS-001: adding the label must not create a second answer."""
    res, book = await _realized_risk_payload()
    coverage = res["history_coverage"]
    assert coverage["intersection_start"] == book["intersection_start"]
    # The declared count is a return-row count, so it can never exceed the
    # longest leg's held price rows.
    assert 0 < coverage["covered_days"] <= max(
        entry["masked_days"] for entry in coverage["tickers"].values()
    )
    # The start that count belongs to is published with its provenance, so the
    # window this section declares is auditable on its own terms.
    assert coverage["intersection_start_source"] in {
        "stored_added_on", "buy_price_inferred", "unknown",
    }


# ---------------------------------------------------------------------------
# D-02
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_realized_risk_publishes_per_ticker_count_units():
    """D-02: the per-ticker keys are declared, not left to be guessed."""
    res, _book_ = await _realized_risk_payload()
    coverage = res["history_coverage"]
    units = coverage["per_ticker_count_units"]
    assert units["raw_days"] == PRICE_FRAME_COUNT_UNITS["raw_days"]
    assert units["masked_days"] == PRICE_FRAME_COUNT_UNITS["masked_days"]
    assert units["return_observations"] == PRICE_FRAME_COUNT_UNITS["return_observations"]
    assert units["counts_identity"]


@pytest.mark.asyncio
async def test_gap_leg_counts_reconcile_through_measured_terms():
    """D-02: the 3-row gap is 1 conversion + 2 real missing bars.

    This is the export's NIFTYIETF.NS row reproduced. The point is not that the
    gap is small enough to be explained away: it is that every row of it is
    accounted for by a MEASURED term, so it cannot be a counting unit in
    disguise.
    """
    res, _book_ = await _realized_risk_payload()
    coverage = res["history_coverage"]
    recon = coverage["per_ticker_count_reconciliation"]
    assert recon["scope"] == PRICE_ROW_RECONCILIATION_SCOPE
    assert recon["identity"] == PRICE_ROW_RECONCILIATION_IDENTITY

    gap = coverage["tickers"]["GAP.NS"]
    row = recon["tickers"]["GAP.NS"]
    # The fixture is discriminating: the two interior holes really do push this
    # leg's gap past the audit's two-row tolerance, and really do reproduce the
    # export's 23-price-row / 20-return-observation row.
    assert (gap["masked_days"], gap["return_observations"]) == (23, 20)
    assert gap["masked_days"] - gap["return_observations"] == 3
    assert row["held_price_rows"] == gap["masked_days"]
    assert row["aligned_return_observations"] == gap["return_observations"]
    assert row["first_held_price_yields_no_return"] == 1
    assert row["interior_price_gaps"] == 2
    assert row["portfolio_alignment_dropped_rows"] == 0
    assert row["reconciles"] is True
    # The identity is arithmetic, not prose: it closes on the published inputs.
    assert (
        row["held_price_rows"]
        - row["first_held_price_yields_no_return"]
        - row["interior_price_gaps"]
        == row["own_return_observations"]
    )
    assert (
        row["own_return_observations"] - row["portfolio_alignment_dropped_rows"]
        == row["aligned_return_observations"]
    )


@pytest.mark.asyncio
async def test_gapless_leg_is_exactly_one_above_its_return_count():
    """D-02: a gapless leg reads masked = returns + 1, with no slack needed."""
    res, _book_ = await _realized_risk_payload()
    recon = res["history_coverage"]["per_ticker_count_reconciliation"]["tickers"]
    for ticker in ("OLD.NS", "NEW.NS"):
        row = recon[ticker]
        assert row["interior_price_gaps"] == 0
        assert row["portfolio_alignment_dropped_rows"] == 0
        assert row["reconciles"] is True
        assert row["held_price_rows"] == row["aligned_return_observations"] + 1


def test_reconciliation_never_invents_a_count():
    """D-02: an unreadable count is left out, not replaced with a zero."""
    payload = _price_frame_count_reconciliation(
        {
            "A.NS": {"masked_days": 10, "return_observations": 9},
            "B.NS": {"masked_days": None, "return_observations": 4},
            "C.NS": {"masked_days": 7},
        },
        {"A.NS": 9},
    )
    assert payload["tickers"]["A.NS"]["reconciles"] is True
    # B has no held-price count and C has no return count: neither is published
    # as a fabricated zero, so a consumer cannot mistake absent for none.
    assert payload["tickers"].get("B.NS") is None
    assert payload["tickers"].get("C.NS") is None
    assert sorted(payload["tickers"]) == ["A.NS"]


@pytest.mark.asyncio
async def test_wide_returns_publishes_the_same_rule():
    """D-02: the shared consumer declares the same units it publishes."""
    book = _book()
    returns, portfolio, coverage = await _build_wide_returns(
        ["OLD.NS", "NEW.NS", "GAP.NS"],
        {"OLD.NS": 0.4, "NEW.NS": 0.35, "GAP.NS": 0.25},
        "2026-01-01", "2026-09-25", book["market"],
        holdings={
            "OLD.NS": {"added_on": book["intersection_start"], "buy_price": None},
            "NEW.NS": {"added_on": book["intersection_start"], "buy_price": None},
            "GAP.NS": {"added_on": book["intersection_start"], "buy_price": None},
        },
    )
    assert not returns.empty and not portfolio.empty
    assert coverage["per_ticker_count_units"] == dict(PRICE_FRAME_COUNT_UNITS)
    recon = coverage["per_ticker_count_reconciliation"]["tickers"]
    for ticker, entry in coverage["tickers"].items():
        row = recon[ticker]
        assert row["held_price_rows"] == entry["masked_days"]
        assert row["aligned_return_observations"] == entry["return_observations"]
        assert row["reconciles"] is True
    # The interior-missing-bar leg is the one with a real gap; the others close
    # on the price-row -> return-row conversion alone.
    assert recon["GAP.NS"]["interior_price_gaps"] == 2
    assert recon["OLD.NS"]["interior_price_gaps"] == 0


# ---------------------------------------------------------------------------
# D-06
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_risk_score_publishes_the_factor_leg_window_and_basis():
    """D-06: the alert's R-squared arrives with the window it was fitted on."""
    book = _book()
    res = await get_risk_score(
        db=_db(book["positions"]), data_service=book["market"],
        analytics_engine=AnalyticsEngine(), benchmark_service=_benchmark(),
    )
    assert res["factor_r_squared"] is not None
    window = res["model_window"]
    assert isinstance(window, dict) and window["start"] and window["end"]
    assert isinstance(res["model_observation_count"], int)
    assert res["model_observation_count"] > 0
    leg = res["factor_model"]
    assert leg["basis"] == RISK_SCORE_FACTOR_BASIS
    assert leg["fitted"] is True and leg["status"] == "fitted"
    assert leg["published_fit_key"] == "factor_r_squared"
    # The count is the regression's own sample, and the scope says so.
    assert leg["model_observation_count"] == res["model_observation_count"]
    assert leg["model_observation_count_scope"] == "active_benchmark_overlap_return_rows"
    assert leg["benchmark_overlap_return_rows"] >= leg["model_observation_count"]
    assert leg["input_return_rows"] >= leg["model_observation_count"]
    # A holding-window fit, declared as one, so it cannot be read against the
    # full-history R-squared `factor_exposure` publishes beside it.
    assert leg["basis"] != analytics_mod.FULL_HISTORY_BASIS
    assert leg["basis"].startswith("holding_window")
    assert "full exchange history" in leg["note"]
    # The block never re-publishes the fit under a key the audit reads as a
    # second, undeclared R-squared for the same model.
    assert "r_squared" not in leg and "adjusted_r_squared" not in leg


@pytest.mark.asyncio
async def test_risk_score_factor_leg_is_published_even_without_a_benchmark():
    """D-06: an unfitted leg is an exclusion, never a zero-sample window."""
    book = _book()
    res = await get_risk_score(
        db=_db(book["positions"]), data_service=book["market"],
        analytics_engine=AnalyticsEngine(),
        benchmark_service=MagicMock(get_returns=AsyncMock(return_value=None)),
    )
    assert res["factor_r_squared"] is None
    assert "factor_risk" in res["excluded_components"]
    leg = res["factor_model"]
    assert leg["fitted"] is False
    assert leg["status"] == "excluded_not_fitted"
    assert leg["model_window"] is None
    assert leg["model_observation_count"] is None
    assert leg["status_reason"]


def test_factor_leg_measures_the_active_benchmark_overlap_not_the_whole_frame():
    """D-06: the published count is the fit's sample, not the input frame.

    A hand-built frame whose benchmark only overlaps part of the window: the
    count must be the overlap, never the larger input row count wearing the
    same name.
    """
    dates = pd.bdate_range("2026-08-03", periods=40)
    prices = pd.DataFrame(
        {"A.NS": pd.Series(np.linspace(100.0, 140.0, 40), index=dates)}
    )
    benchmark = pd.Series(
        np.linspace(0.001, 0.002, 25), index=dates[:25]
    )
    leg = _factor_leg_evidence(prices, benchmark, r_squared=0.4)
    # 40 held prices produce 39 return rows; the benchmark covers 25 of the
    # 40 dates, one of which is the first bar and so has no return.
    assert leg["input_return_rows"] == 39
    assert leg["benchmark_overlap_return_rows"] == 24
    assert leg["model_observation_count"] == 24
    assert leg["model_observation_count"] < leg["input_return_rows"]
    assert leg["model_window"]["start"] == str(dates[1].date())
    assert leg["model_window"]["end"] == str(dates[24].date())


# ---------------------------------------------------------------------------
# D-08
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_zero_weight_row_cannot_drive_the_holding_window_mask():
    """D-08: only the legs whose price data this call fetched set the cutoff."""
    book = _book()
    dates = pd.bdate_range(end="2026-09-25", periods=BARS)
    holdings = {
        "OLD.NS": {"added_on": str(dates[3].date()), "buy_price": None},
        "NEW.NS": {"added_on": str(dates[5].date()), "buy_price": None},
        # A zero-weight persisted row stamped on the last delivered bar: no bars
        # are fetched for it here, so its stamp must not be allowed to mask the
        # book to a one-bar window.
        "GHOST.NS": {"added_on": str(dates[-1].date()), "buy_price": None},
    }
    weights = {"OLD.NS": 0.6, "NEW.NS": 0.4, "GHOST.NS": 0.0}
    returns, portfolio, coverage = await _build_wide_returns(
        ["OLD.NS", "NEW.NS", "GHOST.NS"], weights,
        "2026-01-01", "2026-09-25", book["market"], holdings=holdings,
    )
    # The cutoff is the intersection of the two ACTIVE legs, not the ghost's.
    assert coverage["intersection_start"] == str(dates[5].date())
    assert coverage["truncated"] is True
    # ... and the book still measures a real window rather than one bar.
    assert len(portfolio) > 20
    assert "GHOST.NS" not in coverage["tickers"]
    assert coverage["per_ticker_count_reconciliation"]["tickers"].keys() == {
        "OLD.NS", "NEW.NS",
    }


@pytest.mark.asyncio
async def test_active_leg_still_owns_the_window_without_a_ghost():
    """D-08: the filter changes only the ghost's influence, not the rule."""
    book = _book()
    dates = pd.bdate_range(end="2026-09-25", periods=BARS)
    weights = {"OLD.NS": 0.6, "NEW.NS": 0.4}
    holdings = {
        "OLD.NS": {"added_on": str(dates[3].date()), "buy_price": None},
        "NEW.NS": {"added_on": str(dates[5].date()), "buy_price": None},
    }
    _returns, portfolio, coverage = await _build_wide_returns(
        ["OLD.NS", "NEW.NS"], weights, "2026-01-01", "2026-09-25",
        book["market"], holdings=holdings,
    )
    assert coverage["intersection_start"] == str(dates[5].date())
    assert len(portfolio) > 20


# ---------------------------------------------------------------------------
# the audit rules, over what these routes actually publish
# ---------------------------------------------------------------------------
def _export(sections: Dict[str, Any]):
    from app.debugging.context_audit import Export

    doc = {"schema_version": "2.0", "sections": sections}
    return Export(doc=doc, raw="", path=Path("memory"))


def _rules():
    from app.debugging import context_audit as audit

    return {
        "XS-001": audit.xs_001_holding_window_agreement,
        "XS-002": audit.xs_002_covered_days_requires_scope,
        "XS-005": audit.xs_005_per_ticker_counts_reconcilable,
        "XS-009": audit.xs_009_factor_fit_declares_window,
        "ENV-017": audit.env_017_strict_finite_json,
    }


def _findings(rule_id: str, export) -> List[str]:
    return [f.message for f in _rules()[rule_id](export)]


@pytest.mark.asyncio
async def test_the_published_shape_silences_the_rules_that_flagged_it():
    """D-01 + D-02: the checker must stop reporting, not just be satisfied."""
    res, book = await _realized_risk_payload()
    coverage = copy.deepcopy(res["history_coverage"])
    tickers = {
        ticker: {
            "raw_days": entry["raw_days"],
            "masked_days": entry["masked_days"],
            "return_observations": entry["return_observations"],
        }
        for ticker, entry in coverage["tickers"].items()
    }
    # The shape as it was BEFORE the fix: the count with no scope, and a
    # `masked_days` / `return_observations` pair no single frame explains.
    assert coverage["covered_days_scope"] == HOLDING_COVERED_DAYS_SCOPE
    assert any(
        entry["masked_days"] - entry["return_observations"] > 2
        for entry in tickers.values()
    ), "fixture must reproduce the 3-row gap the rule rejected"

    stripped = copy.deepcopy(coverage)
    stripped.pop("covered_days_scope")
    stripped.pop("per_ticker_count_units", None)
    stripped.pop("per_ticker_count_reconciliation", None)
    before = _export({"realized_risk": {"data": {"history_coverage": stripped}}})
    assert _findings("XS-002", before), "the pre-fix shape must be red"
    assert _findings("XS-005", before), "the pre-fix shape must be red"

    after = _export({"realized_risk": {"data": {"history_coverage": coverage}}})
    assert _findings("XS-002", after) == []
    assert _findings("XS-005", after) == []
    # The sibling that declares the same window must not now disagree with it.
    sibling = _export({
        "realized_risk": {"data": {"history_coverage": coverage}},
        "tear_sheet": {"data": {"history_coverage": {
            **copy.deepcopy(coverage),
            "requested_start": coverage["requested_start"],
        }}},
    })
    assert _findings("XS-001", sibling) == []
    # Every published number is finite, so the new block trips no numeric rule.
    assert _findings("ENV-017", after) == []
    assert coverage["intersection_start"] == book["intersection_start"]


@pytest.mark.asyncio
async def test_risk_score_fit_declares_its_window_to_the_audit():
    """D-06: the node carrying the fit statistic is the one that declares it.

    `factor_exposure` already declares its own full-history fit, so this is the
    two-fit case the rule exists for: the risk score's holding-window fit has to
    answer for ITSELF, and its basis has to say the two are different models.
    """
    book = _book()
    res = await get_risk_score(
        db=_db(book["positions"]), data_service=book["market"],
        analytics_engine=AnalyticsEngine(), benchmark_service=_benchmark(),
    )
    assert res["factor_r_squared"] is not None

    from app.debugging.context_audit import _declares_window_and_observations

    assert _declares_window_and_observations(res) is True

    undeclared = {k: v for k, v in res.items() if k not in {
        "model_window", "model_observation_count", "factor_model",
    }}
    assert _findings("XS-009", _export({"dashboard": {"data": {"risk_score": undeclared}}}))

    declared = _export({"dashboard": {"data": {"risk_score": res}}})
    messages = _findings("XS-009", declared)
    assert not any("no model window" in m for m in messages), messages
    assert res["factor_model"]["basis"] != analytics_mod.FULL_HISTORY_BASIS

    # KNOWN CHECKER GAP, deliberately not asserted away here. XS-009 has a
    # second clause that fires for ANY two declaring fits whose values differ by
    # more than 0.01; its message blames a missing "basis field" but the code
    # never reads one. So once the risk score declares its window, the rule can
    # only be satisfied by the two R-squared agreeing - i.e. by fabricating a
    # 39-observation fit as a 174-observation one. The product fix is the
    # declared window/sample/basis above; clearing the second clause needs a
    # change in `context_audit.py` (read `basis` before reporting), which is
    # outside this file's ownership. What is asserted here is the part the
    # product owns: the fit is no longer published undeclared.
