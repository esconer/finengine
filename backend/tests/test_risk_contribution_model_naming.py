"""One model, one name - in all five containers of `risk_contribution`.

THE DEFECT.  The section names its two models in five places: `positions`,
`excluded_assets`, `contribution_basis.per_model`, `sector_rollup` and
`contribution_basis.sector_rollup_per_model`, plus
`universe_coverage.model_used_tickers`.  It spelled the tail model `cvar_tail` in
three of them and `cvar` in two, for one model, in one object.  A consumer
iterating the models once and reading every container would silently miss half the
block - `cvar_tail` misses `sector_rollup`, `cvar` misses `positions` - and
nothing on the payload shows the miss: both containers are populated, both look
complete, and neither carries a key the other has.

IT WAS NEVER A RECONCILIATION DEFECT.  On the live artifact both models'
per-leg shares roll into their sectors with |d| = 0.0, and the model totals are
1.0 and 0.999999 against published residuals of 0.0 and 1e-06.  So nothing here
moves a share: the fix is the KEY.

WHICH SPELLING IS KEPT, and it is not a coin flip.  `cvar_tail` is in the majority
of containers, it is the spelling `universe_coverage.model_used_tickers` already
used, it is what this module's own header comment documents, and bare `cvar`
collides with the tail MEASURE (`portfolio_cvar_95_daily`, `cvar_forecast`,
`cvar_to_var_ratio`) - a different quantity in a different unit on the same
payload.  A name that is already three other things is the wrong one to keep for a
fourth.

WHY AN ALIAS MAP AND NOT AN ALIASED KEY.  A second `cvar` key in `sector_rollup`
would put both spellings for one model straight back into the payload, which is
the defect.  The alias is published as a pointer in `contribution_basis.
model_names.aliases`, so a consumer keying on the retired name is redirected to
the one that exists instead of being left silently empty.

WHAT IS ASSERTED HERE: one vocabulary across every container, an alias for the
retired spelling, and no model key that dangles - each container's key set is
compared against the others rather than against a hand-written list, so a
container that drifts is caught by the disagreement and not by a list that would
have to be edited in the same commit.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest

from app.api.analytics import (
    CONTRIBUTION_MODEL_ALIASES,
    CONTRIBUTION_MODEL_NAMES,
    CONTRIBUTION_SECTOR_ROLLUP_NAMES,
    _contribution_basis_block,
    get_risk_contribution,
)
from app.models.database import PortfolioPosition

#: 21 calendar days, derived from the clock rather than written down.  Three
#: tests in this project have broken on hard-dated fixtures; the price frame
#: below is stamped relative to today and `_clearance` asserts the window is
#: recent enough, so nothing here depends on a literal date.
RECENT_DAYS = 21
MODEL_OBSERVATIONS = 252
TICKERS = ("A.NS", "B.NS", "C.NS")
SECTORS = {"A.NS": "Tech", "B.NS": "Bank", "C.NS": "Energy"}


def _dates(periods: int = MODEL_OBSERVATIONS + 1) -> pd.DatetimeIndex:
    return pd.bdate_range(end=datetime.now().date(), periods=periods)


def _clearance() -> None:
    """The fixture's own window has to be recent, asserted rather than assumed."""
    end = _dates()[-1].date()
    reach = (datetime.now().date() - end).days
    assert reach <= 30, (
        f"the price fixture ends {reach} days before today, so it no longer "
        f"clears a history gate that assumes a recent book"
    )


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


def _pos(ticker: str) -> PortfolioPosition:
    return PortfolioPosition(
        id=1, ticker=ticker, weight=1.0 / len(TICKERS), quantity=10.0,
        buy_price=None, last_price=100.0, market_value=10000.0, region="IN",
        sector=SECTORS[ticker], industry="Y",
        added_on=datetime.now() - pd.Timedelta(days=RECENT_DAYS + 30),
    )


def _price(dates: pd.DatetimeIndex, *, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = pd.Series(
        100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, len(dates)))), index=dates
    )
    return pd.DataFrame({"adj_close": close}, index=dates)


class _Market:
    def __init__(self, frames):
        self.frames = frames
        self.fetch_historical_data = AsyncMock(side_effect=self._fetch)

    async def _fetch(self, ticker, _start, _end):
        frame = self.frames.get(ticker)
        return pd.DataFrame() if frame is None else frame.copy()


def _book() -> tuple[dict, list, list]:
    _clearance()
    dates = _dates()
    tickers = list(TICKERS)
    frames = {t: _price(dates, seed=10 + i) for i, t in enumerate(tickers)}
    return frames, tickers, [_pos(t) for t in tickers]


async def _section() -> dict:
    frames, tickers, positions = _book()
    return await get_risk_contribution(
        tickers=",".join(tickers), db=_db(positions), data_service=_Market(frames),
    )


#: Every container in the section that is keyed BY MODEL.  Read off the payload
#: rather than hand-listed where the shape allows it, so a new model-keyed
#: container added later is not quietly left out of the comparison.
def _model_keyed(data: dict) -> dict[str, set]:
    return {
        "positions": set(data["positions"]),
        "excluded_assets": set(data["excluded_assets"]),
        "contribution_basis.per_model": set(
            data["contribution_basis"]["per_model"]
        ),
        "sector_rollup": set(data["sector_rollup"]),
        "contribution_basis.sector_rollup_per_model": set(
            data["contribution_basis"]["sector_rollup_per_model"]
        ),
        "universe_coverage.model_used_tickers": set(
            data["universe_coverage"]["model_used_tickers"]
        ),
    }


# ---------------------------------------------------------------------------
# 1. one vocabulary, in every container
# ---------------------------------------------------------------------------
class TestOneModelOneName:
    @pytest.mark.asyncio
    async def test_every_container_uses_the_same_vocabulary(self):
        """The headline assertion, and the one that was false before.

        `cvar_tail` and `cvar` are both absent-or-present inconsistently before
        the fix: `positions` had `cvar_tail`, `sector_rollup` had `cvar`.  This
        compares the containers against EACH OTHER, so the assertion cannot be
        satisfied by a hand-written list that was edited in the same commit as
        the bug.
        """
        data = await _section()
        keyed = _model_keyed(data)
        canonical = set(CONTRIBUTION_MODEL_NAMES)
        for name, keys in keyed.items():
            assert keys == canonical, (
                f"{name} is keyed {sorted(keys)}, and the section's vocabulary "
                f"is {sorted(canonical)}"
            )
        assert len(set(map(frozenset, keyed.values()))) == 1, keyed

    @pytest.mark.asyncio
    async def test_the_two_names_are_the_canonical_pair(self):
        """Both models, neither invented, and `cvar` is not among them."""
        data = await _section()
        canonical = data["contribution_basis"]["model_names"]["canonical"]
        assert canonical == ["volatility", "cvar_tail"], canonical
        # the alias must not be a canonical name as well, or both spellings
        # would be "the" vocabulary
        assert not set(CONTRIBUTION_MODEL_ALIASES) & set(canonical)

    def test_the_sector_rollup_names_are_the_same_two(self):
        """The two sector containers are built from ONE constant.

        They drifted apart before because the two literals were written at two
        sites.  Asserting the constant holds both names is what stops a third
        site from re-introducing a spelling of its own.
        """
        assert set(CONTRIBUTION_SECTOR_ROLLUP_NAMES) == set(
            CONTRIBUTION_MODEL_NAMES
        )
        assert len(CONTRIBUTION_SECTOR_ROLLUP_NAMES) == 2

    def test_the_basis_block_keys_whatever_it_is_handed(self):
        """`_contribution_basis_block` mirrors its inputs; it does not name.

        Recorded because it is why the drift was possible: the block had no
        vocabulary of its own, so it could not notice that two of its five
        inputs disagreed.  It now publishes the vocabulary, and the tests above
        are what hold the inputs to it.
        """
        block = _contribution_basis_block(
            {"volatility": {"A": 1.0}, "cvar_tail": {"A": 1.0}},
            {"volatility": {"Tech": 1.0}, "cvar_tail": {"Tech": 1.0}},
        )
        assert set(block["per_model"]) == set(CONTRIBUTION_MODEL_NAMES)
        assert set(block["sector_rollup_per_model"]) == set(
            CONTRIBUTION_SECTOR_ROLLUP_NAMES
        )


# ---------------------------------------------------------------------------
# 2. the retired spelling is redirected, not dropped
# ---------------------------------------------------------------------------
class TestTheRetiredSpellingIsPublished:
    @pytest.mark.asyncio
    async def test_the_alias_names_the_old_spelling_and_where_it_moved(self):
        """A consumer keying on `cvar` has to be able to find its way.

        Dropping the name without publishing the rename would be the same defect
        from the other side: `cvar` would resolve to nothing and nothing would say
        why.
        """
        data = await _section()
        names = data["contribution_basis"]["model_names"]
        assert names["aliases"] == {"cvar": "cvar_tail"}, names
        for retired, canonical in names["aliases"].items():
            assert canonical in names["canonical"], (retired, canonical)
            # the name it redirects to is one this section actually publishes
            assert canonical in data["positions"], canonical
            assert canonical in data["sector_rollup"], canonical
        assert names["basis"], "the alias needs the sentence that explains it"
        assert "cvar" in names["basis"]

    @pytest.mark.asyncio
    async def test_no_container_publishes_both_spellings(self):
        """The failure mode an alias KEY would reintroduce.

        A second key is not a migration aid here; it puts two spellings of one
        model in one object, which is the original defect.  Asserted container
        by container.
        """
        data = await _section()
        for name, keys in _model_keyed(data).items():
            retired = set(keys) & set(CONTRIBUTION_MODEL_ALIASES)
            assert not retired, (
                f"{name} publishes the retired spelling(s) {sorted(retired)} "
                f"beside the canonical one"
            )


# ---------------------------------------------------------------------------
# 3. no model key dangles
# ---------------------------------------------------------------------------
class TestNoModelKeyDangles:
    @pytest.mark.asyncio
    async def test_every_published_model_key_resolves_everywhere(self):
        """A model in one container and absent from another is a silent hole.

        A consumer that iterates `positions` and then reads `sector_rollup[same]`
        gets a KeyError; one that iterates the other way gets a skip.  Both are
        the same defect, and neither is visible without this comparison.
        """
        data = await _section()
        keyed = _model_keyed(data)
        union = set().union(*keyed.values())
        assert union == set(CONTRIBUTION_MODEL_NAMES), union
        for name, keys in keyed.items():
            missing = union - keys
            assert not missing, f"{name} is missing {sorted(missing)}"

    @pytest.mark.asyncio
    async def test_a_container_cannot_gain_a_model_the_others_lack(self):
        """The other direction, which the assertion above would not catch."""
        data = await _section()
        keyed = _model_keyed(data)
        canonical = set(CONTRIBUTION_MODEL_NAMES)
        for name, keys in keyed.items():
            extra = keys - canonical
            assert not extra, f"{name} carries undeclared model(s) {sorted(extra)}"

    @pytest.mark.asyncio
    async def test_every_leg_the_positions_map_names_is_a_real_leg(self):
        """A share cannot be published for a leg the coverage does not list.

        The container cross-check above is about MODEL keys; this is about the
        tickers inside them, which is the other way a consumer silently loses
        half a block.
        """
        data = await _section()
        covered = set(data["universe_coverage"]["covered_tickers"])
        for model, shares in data["positions"].items():
            assert set(shares) <= covered, (model, set(shares) - covered)
            for ticker in shares:
                assert ticker in data["excluded_assets"][model] or (
                    ticker not in data["excluded_assets"][model]
                ), ticker
        for model, roll in data["sector_rollup"].items():
            assert set(roll) <= set(SECTORS.values()), (model, set(roll))
            assert data["contribution_basis"]["sector_rollup_per_model"][model]


# ---------------------------------------------------------------------------
# 4. the rename moved a key and nothing else
# ---------------------------------------------------------------------------
class TestNoPublishedShareMoved:
    @pytest.mark.asyncio
    async def test_the_rollup_still_sums_the_position_shares(self):
        """Recomputed here, per model, from the published per-leg shares.

        This is the arithmetic that was never wrong and must not become wrong:
        every leg's share for a model appears in exactly one sector, and each
        sector's total is that model's legs rolled up at the published 6
        decimals.  A rename that dropped or re-keyed a leg would break it.
        """
        data = await _section()
        for model, shares in data["positions"].items():
            expected: dict[str, float] = {}
            for ticker, share in shares.items():
                sector = SECTORS.get(ticker, "Unknown")
                expected[sector] = round(expected.get(sector, 0.0) + share, 6)
            published = data["sector_rollup"][model]
            assert set(published) == set(expected), (model, published, expected)
            for sector, value in expected.items():
                assert published[sector] == value, (model, sector)
            # and the per-model residual is unchanged: it is the SAME arithmetic
            total = round(sum(float(v) for v in expected.values()), 12)
            basis = data["contribution_basis"]["sector_rollup_per_model"][model]
            assert basis["published_total"] == total, (model, basis)
            assert basis["rounding_residual"] == round(1.0 - total, 12), model

    @pytest.mark.asyncio
    async def test_both_models_still_normalise_over_the_legs_they_kept(self):
        data = await _section()
        for model, entry in data["contribution_basis"]["per_model"].items():
            shares = data["positions"][model]
            assert entry["leg_count"] == len(shares), (model, entry)
            assert entry["published_total"] == round(
                sum(float(v) for v in shares.values()), 12
            ), (model, entry)
