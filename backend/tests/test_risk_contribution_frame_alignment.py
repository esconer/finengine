"""`risk_contribution` 500s on every book that has a leg with a price gap.

The section has published `status: "unavailable"` with no data in every export
since the project began, and no audit rule caught it. The cause is not a
refusal and not missing data - it is two boolean masks built on the PORTFOLIO
series being used to index the WIDE per-leg frame, which is a different frame
with a deliberately different index:

* `returns_df` retains every date on which any leg was measurable (per-leg
  truth, NaN-masked dates kept - see `_build_wide_returns`).
* `port_ret` DROPS every date whose surviving positive weight did not cover the
  whole declared book (`aggregate_active_returns`, `min_coverage = 1.0`).

So `port_ret.index` is a strict SUBSET of `returns_df.index` on exactly the
books that have a gap, and `returns_df[something][mask]` raises
`IndexingError: Unalignable boolean Series provided as indexer`. The blanket
`except Exception` at the foot of `get_risk_contribution` turned that into a
bare 500, and a consumer could not tell a crash from a genuine refusal.

Two sites, same defect:
  1. the holding-window mask, cut per ticker out of `returns_df`;
  2. the CVaR tail selection, `returns_df.loc[tail]`.

These tests pin the CAUSE (a mask/index that cannot address the frame it is
applied to), not the numbers the fix happens to produce. The tempting wrong
fixes are refused explicitly: narrowing the wide frame to the portfolio index
would discard the partially-covered dates the frame exists to carry, and
narrowing the tail to the wide frame would answer a portfolio question with a
per-leg one.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest

from app.api.analytics import (
    HOLDING_WIDE_FRAME_COVERED_DAYS_SCOPE,
    _build_wide_returns,
    get_risk_contribution,
    holding_window_observation_count,
)
from app.models.database import PortfolioPosition

TODAY = "2026-09-07"
HOLDING_START = datetime(2026, 8, 4)
MODEL_OBSERVATIONS = 252


# ---------------------------------------------------------------------------
# seams
# ---------------------------------------------------------------------------
def _rows(rows):
    scalars = MagicMock()
    scalars.all.return_value = list(rows)
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _db(rows):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=lambda *_a, **_k: _rows(rows))
    return db


def _pos(ticker, *, added_on=HOLDING_START, sector="Tech"):
    return PortfolioPosition(
        id=1, ticker=ticker, weight=0.5, quantity=10.0, buy_price=None,
        last_price=100.0, market_value=10000.0, region="IN",
        sector=sector, industry="Y", added_on=added_on,
    )


def _dates(periods: int = MODEL_OBSERVATIONS + 1) -> pd.DatetimeIndex:
    return pd.bdate_range(end=TODAY, periods=periods)


def _walk(dates, *, seed=1) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(
        100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, len(dates)))), index=dates
    )


def _price(dates, *, seed=1, gap: int = 0) -> pd.DataFrame:
    close = _walk(dates, seed=seed)
    if gap:
        close = close.copy()
        close.iloc[-gap:] = np.nan
    return pd.DataFrame({"adj_close": close}, index=dates)


class _Market:
    def __init__(self, frames):
        self.frames = frames
        self.fetch_historical_data = AsyncMock(side_effect=self._fetch)

    async def _fetch(self, ticker, _start, _end):
        frame = self.frames.get(ticker)
        return pd.DataFrame() if frame is None else frame.copy()


def _sparse_book(*, gap_legs: int = 1, gap: int = 2) -> tuple[dict, list, list]:
    """A book whose second leg has a price gap on its last `gap` sessions.

    The gap is what makes `port_ret` shorter than `returns_df`: on those dates
    the surviving positive weight cannot cover the whole declared book, so the
    portfolio aggregate refuses them while the wide frame keeps them as NaN.
    """
    dates = _dates()
    tickers = ["A.NS", "B.NS", "C.NS"][: 1 + gap_legs]
    frames = {
        ticker: _price(dates, seed=10 + i, gap=(gap if i else 0))
        for i, ticker in enumerate(tickers)
    }
    weights = {t: 1.0 / len(tickers) for t in tickers}
    positions = [_pos(t) for t in tickers]
    return frames, tickers, positions, weights


# ---------------------------------------------------------------------------
# The premise: the two frames really do have different indexes
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_gapped_leg_makes_the_portfolio_index_a_strict_subset_of_the_wide_one():
    """If this ever stopped holding, neither fix would be necessary.

    Asserted rather than assumed: the whole defect is that a mask built on one
    index is applied to the other, and that is only possible because the two
    differ.
    """
    frames, tickers, _positions, weights = _sparse_book()
    returns_df, port_ret, coverage = await _build_wide_returns(
        tickers, weights, "2025-09-27", "2026-09-27", _Market(frames),
    )
    assert len(returns_df) > len(port_ret)
    assert not returns_df.index.equals(port_ret.index)
    assert port_ret.index.isin(returns_df.index).all()
    # The dropped dates are the ones a leg was unpriced on, and they are
    # RETAINED in the wide frame rather than removed.
    assert coverage["partial_coverage_days"] == len(returns_df) - len(port_ret)
    for dropped in port_ret.index.difference(returns_df.index):
        assert returns_df.loc[dropped].isna().all()


@pytest.mark.asyncio
async def test_the_ungapped_book_has_matching_indexes_which_is_why_every_test_passed():
    """The control: why 5 existing risk-contribution tests were green.

    Their fixtures have no leg with a price gap, so the two indexes coincide,
    the misaligned mask indexes fine, and the defect is invisible. A fixture
    that cannot fail is not evidence the code is correct.
    """
    frames, tickers, _positions, weights = _sparse_book(gap=0)
    returns_df, port_ret, _cov = await _build_wide_returns(
        tickers, weights, "2025-09-27", "2026-09-27", _Market(frames),
    )
    assert returns_df.index.equals(port_ret.index)
    # Which is exactly why `returns_df[col][mask]` succeeds there: the mask
    # carries the very index of the frame it is applied to.
    _days, mask = holding_window_observation_count(port_ret, "2026-08-04")
    selected = returns_df["A.NS"][mask]
    assert len(selected) == int(mask.sum())
    assert not selected.empty


def test_pandas_refuses_the_mask_the_route_was_using():
    """The exact failure, isolated from the route.

    A boolean Series carrying one frame's index cannot index a differently
    indexed frame. This is the exception the blanket handler was swallowing;
    pinning it means a future "fix" that narrows the frame or reindexes the
    mask has to confront the reason the code was wrong.
    """
    wide_index = pd.bdate_range("2026-08-04", periods=10)
    port_index = wide_index[[0, 1, 3, 4, 5, 7, 8]]
    wide = pd.DataFrame({"A": 0.01}, index=wide_index)
    _days, mask = holding_window_observation_count(
        pd.Series(0.01, index=port_index), "2026-08-01",
    )
    with pytest.raises(Exception) as excinfo:
        wide["A"][mask]
    assert "boolean" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# 1. The route must not 500 on a book it can compute
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_section_computes_on_a_book_with_a_leg_that_has_a_price_gap():
    """The section IS computable for this book, so it must publish, not 500.

    Before the fix this raised `IndexingError`, which the route's blanket
    handler converted into `HTTPException(500, "Internal server error")` - a
    consumer could not distinguish a crash from a refusal.
    """
    frames, tickers, positions, _weights = _sparse_book()
    result = await get_risk_contribution(
        tickers=",".join(tickers), db=_db(positions), data_service=_Market(frames),
    )
    # Both models produced a normalised share map over the legs they kept.
    assert set(result["positions"]["volatility"]) == set(tickers)
    assert set(result["positions"]["cvar_tail"]) == set(tickers)
    assert result["positions"]["volatility"]
    assert result["positions"]["cvar_tail"]
    assert result["data_status"] == "available"
    assert result["universe_coverage"]["status"] == "complete"
    assert result["excluded_assets"] == {"volatility": [], "cvar_tail": []}


# ---------------------------------------------------------------------------
# 2. ...with its SCOPE intact (the wide frame was not narrowed)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_fix_does_not_narrow_the_wide_frame_to_make_the_indexes_agree():
    """The tempting wrong fix, refused: reindexing or slicing the wide frame.

    XS-001 gave this section `HOLDING_WIDE_FRAME_COVERED_DAYS_SCOPE` precisely
    because it measures the wide per-leg frame, which RETAINS dates on which
    some leg was unpriced. Narrowing it to `port_ret.index` would make the two
    indexes agree and destroy the per-leg truth the frame exists to carry.
    """
    frames, tickers, positions, weights = _sparse_book()
    returns_df, port_ret, coverage = await _build_wide_returns(
        tickers, weights, "2025-09-27", "2026-09-27", _Market(frames),
    )
    result = await get_risk_contribution(
        tickers=",".join(tickers), db=_db(positions), data_service=_Market(frames),
    )
    holding = result["history_coverage"]["holding_context"]

    # The scope name is unchanged: still the wide-frame population.
    assert holding["covered_days_scope"] == HOLDING_WIDE_FRAME_COVERED_DAYS_SCOPE
    # And the count is the WIDE frame's, so it is strictly greater than the
    # whole-book complete rows the covariance and tail models consumed. Had
    # the frame been narrowed, the two would be equal and the scope name a lie.
    expected = int(
        (returns_df.index.normalize() > pd.Timestamp("2026-08-04")).sum()
    )
    assert expected == len(returns_df) - int(
        (returns_df.index.normalize() <= pd.Timestamp("2026-08-04")).sum()
    )
    assert holding["covered_days"] == expected
    assert holding["covered_days"] > len(port_ret.loc[
        port_ret.index.normalize() > pd.Timestamp("2026-08-04")
    ])
    # The block still publishes the gap it did not hide.
    assert coverage["partial_coverage_days"] > 0
    # `annualized` is still driven by the count against the real policy floor.
    assert holding["annualized"] == (holding["covered_days"] >= 30)


@pytest.mark.asyncio
async def test_the_per_ticker_counts_are_cut_from_the_frame_they_are_measured_on():
    """The per-ticker `masked_days` is a wide-frame cut, and says which frame.

    `RETURN_FRAME_COUNT_UNITS` declares `masked_days` to be
    `aligned_return_rows_inside_the_canonical_holding_window`, so the identity
    `raw_days - masked_days = the rows OUTSIDE the window` must hold on the
    wide frame. The gapped leg is the one that proves it: its own non-null
    return rows are fewer than the frame's length.
    """
    frames, tickers, positions, weights = _sparse_book()
    returns_df, _port, _cov = await _build_wide_returns(
        tickers, weights, "2025-09-27", "2026-09-27", _Market(frames),
    )
    result = await get_risk_contribution(
        tickers=",".join(tickers), db=_db(positions), data_service=_Market(frames),
    )
    holding = result["history_coverage"]["holding_context"]
    cutoff = pd.Timestamp("2026-08-04")
    for ticker in tickers:
        entry = holding["tickers"][ticker]
        series = returns_df[ticker]
        assert entry["raw_days"] == int(series.notna().sum())
        assert entry["return_observations"] == entry["raw_days"]
        assert entry["holding_window_return_observations"] == entry["masked_days"]
        expected_masked = int(series[series.index.normalize() > cutoff].notna().sum())
        assert entry["masked_days"] == expected_masked
        # The declared identity, checked rather than quoted.
        assert entry["raw_days"] - entry["masked_days"] == int(
            series[series.index.normalize() <= cutoff].notna().sum()
        )


# ---------------------------------------------------------------------------
# 3. The CVaR tail is a PORTFOLIO question - the second site
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_cvar_tail_is_the_portfolios_worst_days_not_the_wide_frames():
    """`var_95` and the tail are computed on `port_ret`, and stay that way.

    The bug at this site was never the population, only the selection: the tail
    mask carried `port_ret`'s index and was used to index `returns_df`. So the
    fix must not answer a portfolio question with a per-leg one - a date the
    aggregate refused is not a portfolio day and must not become a tail day.
    """
    frames, tickers, positions, weights = _sparse_book()
    returns_df, port_ret, _cov = await _build_wide_returns(
        tickers, weights, "2025-09-27", "2026-09-27", _Market(frames),
    )
    result = await get_risk_contribution(
        tickers=",".join(tickers), db=_db(positions), data_service=_Market(frames),
    )
    # The published VaR is the portfolio's own 5th percentile, unchanged.
    assert result["portfolio_var_95_daily"] == pytest.approx(
        round(float(np.percentile(port_ret, 5)), 6), abs=1e-9
    )
    # Published CVaR is the mean of the portfolio's tail days.
    tail = port_ret <= float(np.percentile(port_ret, 5))
    assert result["portfolio_cvar_95_daily"] == pytest.approx(
        round(float(port_ret[tail].mean()), 6), abs=1e-9
    )
    # The refused dates are NOT in the tail population: the tail is defined on
    # the portfolio series, which does not contain them. `calculation_window`
    # describes that portfolio series, so it is strictly shorter than the wide
    # frame the covariance model consumed.
    assert len(tail) == len(port_ret)
    assert result["calculation_window"]["days"] == len(port_ret)
    assert result["full_history"]["observation_count"] == len(returns_df)
    assert len(returns_df) > result["calculation_window"]["days"]


@pytest.mark.asyncio
async def test_a_refused_date_cannot_become_a_tail_day_even_if_it_would_have_qualified():
    """The per-leg truth is preserved on tail days: NaN is never a zero loss.

    The gapped leg is unpriced on exactly the dates the aggregate refused. If
    the tail were selected from the wide frame instead, those dates could
    enter it and the unpriced leg would contribute a zero (or an imputed) loss
    to a tail that is supposed to describe the whole book.
    """
    frames, tickers, positions, weights = _sparse_book()
    returns_df, port_ret, _cov = await _build_wide_returns(
        tickers, weights, "2025-09-27", "2026-09-27", _Market(frames),
    )
    result = await get_risk_contribution(
        tickers=",".join(tickers), db=_db(positions), data_service=_Market(frames),
    )
    # Every tail day is a portfolio day; no refused date leaked into it.
    tail_dates = set(port_ret.index[port_ret <= float(np.percentile(port_ret, 5))])
    assert tail_dates
    assert tail_dates.issubset(set(port_ret.index))
    assert tail_dates.issubset(set(returns_df.index))
    # The contributions still sum to 1 over the legs the model kept, which is
    # only true if the active-weight denominator refused the unpriced rows
    # rather than treating them as flat.
    assert sum(result["positions"]["cvar_tail"].values()) == pytest.approx(1.0, abs=1e-4)


# ---------------------------------------------------------------------------
# 4. No fabricated numbers, and the degradation stays declared
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_book_that_cannot_support_a_model_excludes_the_leg_and_says_so():
    """A leg with underdetermined history is excluded and NAMED, not zeroed.

    A leg with fewer than two usable observations has no variance, so it
    cannot enter the covariance model. It is published in `excluded_assets`
    and removed from the published universe, rather than contributing a
    fabricated zero share.
    """
    dates = _dates()
    frames = {
        "A.NS": _price(dates, seed=11),
        "B.NS": _price(dates, seed=12),
        # C carries two price bars inside the window: one return observation,
        # which is underdetermined for a covariance (a std needs two).
        "C.NS": _price(dates, seed=13, gap=len(dates) - 2),
    }
    result = await get_risk_contribution(
        tickers="A.NS,B.NS,C.NS",
        db=_db([_pos("A.NS"), _pos("B.NS"), _pos("C.NS")]),
        data_service=_Market(frames),
    )
    excluded = result["excluded_assets"]["volatility"]
    assert "C.NS" in excluded
    assert "C.NS" not in result["positions"]["volatility"]
    # It is not a zero share either - it is absent.
    assert result["positions"]["volatility"].get("C.NS", 1.0) != 0.0
    # The surviving shares still describe the surviving book, and the block
    # says the delivered universe is not the requested one.
    assert sum(result["positions"]["volatility"].values()) == pytest.approx(
        1.0, abs=1e-4
    )
    assert result["universe_coverage"]["status"] == "partial"
    assert result["universe_coverage"]["complete"] is False
    assert "C.NS" in result["universe_coverage"]["missing_tickers"]


@pytest.mark.asyncio
async def test_the_contribution_basis_block_declares_the_unit_of_the_shares():
    """The section publishes what `positions.*` is a number OF (NUM-003).

    A section that starts publishing is a section the audit rules can read for
    the first time, so the basis block has to be there and has to be complete.
    """
    frames, tickers, positions, _weights = _sparse_book()
    result = await get_risk_contribution(
        tickers=",".join(tickers), db=_db(positions), data_service=_Market(frames),
    )
    basis = result["contribution_basis"]
    assert basis["unit"] == "fraction_of_portfolio_risk"
    assert basis["rounding_decimals"] == 6
    for model in ("volatility", "cvar_tail"):
        record = basis["per_model"][model]
        assert record["leg_count"] == len(result["positions"][model])
        assert record["published_total"] == pytest.approx(1.0, abs=1e-4)
        assert record["rounding_residual"] == pytest.approx(
            1.0 - record["published_total"], abs=1e-9
        )


@pytest.mark.asyncio
async def test_a_dense_book_publishes_exactly_what_it_published_before():
    """No regression on the books that already worked.

    With no leg gap the two indexes coincide, so the mask that used to be built
    on `port_ret` was already addressing the right rows. Every published number
    must therefore be unchanged - this fix moves nothing on a dense book.
    """
    frames, tickers, positions, _weights = _sparse_book(gap=0)
    result = await get_risk_contribution(
        tickers=",".join(tickers), db=_db(positions), data_service=_Market(frames),
    )
    returns_df, port_ret, _cov = await _build_wide_returns(
        tickers, {t: 1.0 / len(tickers) for t in tickers},
        "2025-09-27", "2026-09-27", _Market(frames),
    )
    holding = result["history_coverage"]["holding_context"]
    expected = int((port_ret.index.normalize() > pd.Timestamp("2026-08-04")).sum())
    assert holding["covered_days"] == expected
    # Identical indexes => the wide-frame count and the portfolio count agree.
    assert holding["covered_days"] == int(
        (returns_df.index.normalize() > pd.Timestamp("2026-08-04")).sum()
    )
    assert holding["covered_days_scope"] == HOLDING_WIDE_FRAME_COVERED_DAYS_SCOPE
    assert result["data_status"] == "available"
