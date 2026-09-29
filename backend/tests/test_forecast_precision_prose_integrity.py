"""`forecast_risk`'s precision block: prose that parses, and arithmetic that adds up.

ITEM 4 - A SENTENCE SPLICED INTO THE MIDDLE OF ANOTHER, ON EVERY LEG.
`precision.derived_values['positions.<TICKER>.var_forecast'].inherits_precision_reason`
ended with a path terminated by a period and then had a clause appended with `+`:

    "...The portfolio leg's sigma IS measured on this same payload, at
     precision.estimated_statistics.portfolio.estimates.the fitted leg's
     return-space sigma is its own published annualized volatility times
     sqrt(h / 252), which is an identity of the cumulative-variance path..."

A path glued to a subject-less clause. Ungrammatical, and the path it appears to
name resolves to nothing. The fragment was a well-formed sentence on its own, so
the defect was the missing boundary rather than the words - which is why the fix
is a JOINER (`_forecast_sentences`) that terminates every part before attaching
the next, and why the test below is scoped to the splice SIGNATURE rather than to
English.

The previous sentence in the same string was also FALSE: "there is no figure at
the far end of it and none is claimed". The far end publishes
`point = 0.19598052754718792`, an observation count and an effective_n. What it
does not publish is that point's STANDARD ERROR and its INTERVAL. The target's
own `reason` says so precisely, so the payload carried two sentences disagreeing
about the same absence.

WHY THE PROSE RULE IS NARROW, and this is measured, not asserted.  The obvious
rules are not implementable here.  Over the 105 prose strings this block
publishes: `\\.[A-Za-z]` fires **35** times and `[a-z]\\.[a-z]` **27**, and every
one of those is a legitimate dotted path - `app/services/analytics_engine.py`,
`np.clip`, `precision.derived_values[...].derivation_precondition_evidence`.  A
second rule, sentence-initial lowercase, fires **11** times on legitimate key
names that open a sentence (`"...rather than dropped. at_clip_bound is the
number of..."`).  The parallel agent measured the same thing artifact-wide: a
naive sentence rule fires 1,118 times over 1,314 prose strings.  So the rule here
is the one signature that is actually a defect - a period with NO space after it
whose following word is an English function word, which no dotted path in this
payload can contain.  `TestTheRuleIsNotVacuous` proves it still fires on the
pre-fix string, so a future relaxation cannot quietly turn it green.

ITEM 5 - TWO STRINGS IN ONE BLOCK DISAGREEING ABOUT ONE MEASUREMENT.
`measurements_withheld.why_not_measured` said "3800 refits in total" beside a
portfolio leg of "1001 refits" and fourteen legs of "2800". 1001 + 2800 = 3801.
The sibling `resample_count_rule` said 1000 for the same portfolio leg. The
`+1` is now settled: it is the ORIGINAL fit, which is not a resample and is not
counted by `bootstrap_resamples`. Every count in the paragraph is now interpolated
from module constants, and the same arithmetic is published structurally under
`refit_arithmetic` so a reader - and a test - can check it without parsing prose.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, List, Tuple
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import pandas as pd
import pytest

from app.api import analytics as analytics_api
from app.api.analytics import (
    FORECAST_LEG_REFIT_RESAMPLES_WITHHELD,
    FORECAST_WITHHELD_BOOK_LEGS,
    FORECAST_WITHHELD_LEG_FITS,
    FORECAST_WITHHELD_LEG_RESAMPLES,
    FORECAST_WITHHELD_PORTFOLIO_FITS,
    FORECAST_WITHHELD_PORTFOLIO_RESAMPLES,
    FORECAST_WITHHELD_TOTAL_FITS,
    FORECAST_REFIT_COUNT_RULE,
    _forecast_precision_block,
    _forecast_sentences,
    get_forecast_risk,
)
from app.services.analytics_engine import AnalyticsEngine

TEST_RESAMPLES = 60
TICKERS = ("AAA.NS", "BBB.NS", "CCC.NS")
OBSERVATIONS = 60

#: A short draw count, so the suite is not dominated by optimiser runs.  The block
#: publishes whichever count it was given, so a reduced count is visible.
PROSE_KEY = re.compile(
    r"(_reason|_basis|_note|_rule|_policy|_limitation|_convention|_semantics"
    r"|_provenance|_basis|message|methodology|evidence|scope)$"
)


# ---------------------------------------------------------------------------
# fixtures - anchored to the clock, never to a literal date
# ---------------------------------------------------------------------------
def _prices(*, seed: int = 3, observations: int = OBSERVATIONS):
    end = pd.Timestamp(pd.Timestamp.now().normalize())
    dates = pd.bdate_range(end=end, periods=observations)
    rng = np.random.default_rng(seed)
    return {
        t: pd.Series(
            100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.010, observations))),
            index=dates,
        )
        for t in TICKERS
    }


def _clearance() -> None:
    """The fixture must be recent, asserted as a precondition rather than assumed.

    Three tests in this project have broken on hard-dated fixtures; the price
    frame here is stamped relative to today and this is where that is checked, so
    a fixture that stops being recent says so here rather than failing three
    assertions later.
    """
    end = _prices()[TICKERS[0]].index[-1].date()
    reach = (pd.Timestamp.now().normalize().date() - end).days
    assert reach <= 30, (
        f"the price fixture ends {reach} days before today, so it no longer "
        f"clears a history gate that assumes a recent book"
    )


async def _payload() -> dict:
    _clearance()
    series = _prices()

    async def allocation(_tickers, _db):
        return list(TICKERS), {t: 1.0 / len(TICKERS) for t in TICKERS}

    with patch("app.api.analytics.resolve_allocation", side_effect=allocation), \
         patch("app.api.analytics._fetch_price_series_dict",
               new=AsyncMock(return_value=series)), \
         patch.object(analytics_api, "FORECAST_PORTFOLIO_REFIT_RESAMPLES",
                      TEST_RESAMPLES):
        return await get_forecast_risk(
            model="GARCH", horizon=1, tickers=",".join(TICKERS),
            start=series[TICKERS[0]].index[0].date(),
            end=series[TICKERS[0]].index[-1].date(),
            db=Mock(), data_service=Mock(), analytics_engine=AnalyticsEngine(),
        )


@pytest.fixture
def fast_resamples(monkeypatch):
    monkeypatch.setattr(
        analytics_api, "FORECAST_PORTFOLIO_REFIT_RESAMPLES", TEST_RESAMPLES
    )


def _prose(node: Any, path: str = "", out: List[Tuple[str, str]] | None = None):
    out = [] if out is None else out
    if isinstance(node, dict):
        for key, value in node.items():
            _prose(value, f"{path}.{key}", out)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _prose(value, f"{path}[{index}]", out)
    elif isinstance(node, str) and PROSE_KEY.search(path):
        out.append((path, node))
    return out


#: English words that cannot be an element of a dotted identifier anywhere in
#: this payload, so a period immediately followed by one of them is a sentence
#: that lost its boundary and not a path.
_NOT_IDENTIFIER_ELEMENTS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "has", "have", "in", "is", "it", "its", "no", "not", "of", "on", "or",
    "so", "than", "that", "the", "then", "there", "this", "to", "was", "were",
    "which", "while", "with",
})

#: A period, NO space, then a function word: `...estimates.the fitted leg's...`
_FUSED_SENTENCE = re.compile(
    r"\.(?:" + "|".join(sorted(_NOT_IDENTIFIER_ELEMENTS)) + r")\b"
)


def _fused(text: str) -> List[str]:
    return [m.group(0) for m in _FUSED_SENTENCE.finditer(text)]


#: The exact string this file exists to remove, on one leg.  Kept verbatim so the
#: rule cannot be relaxed into vacuity, and so the pre-fix wording stays on
#: record next to the test that rejects it.
PRE_FIX_INHERITANCE_REASON = (
    "the entire precision of this value would be the precision of this leg's own "
    "fitted conditional sigma, at precision.estimated_statistics.positions.X."
    "estimates.volatility_forecast - and that node is ITSELF undisclosed: this "
    "leg's estimator was withheld rather than run, for the cost reason published "
    "at precision.measurements_withheld. The pointer is kept because the "
    "inheritance is real and the node it names is on this payload, but there is "
    "no figure at the far end of it and none is claimed; the target does publish "
    "the part of its precision that is free, its observation count, AR(1) and "
    "effective_n. The portfolio leg's sigma IS measured on this same payload, at "
    "precision.estimated_statistics.portfolio.estimates.the fitted leg's "
    "return-space sigma is its own published annualized volatility times "
    "sqrt(h / 252), which is an identity of the cumulative-variance path - exact "
    "unless the published annualized clip bounds are active on this leg, and "
    "derivation_residual says which case this is"
)


# ---------------------------------------------------------------------------
# 1. the splice
# ---------------------------------------------------------------------------
class TestNoSplicedSentence:
    @pytest.mark.asyncio
    async def test_no_prose_string_in_this_block_lost_a_sentence_boundary(
        self, fast_resamples
    ):
        """Every prose string in `forecast_risk.precision`, walked the rule's own way.

        Scoped to the block this file owns.  The general artifact-wide version is
        not implementable without an allowlist - see the module docstring for the
        counts that rule that out - and a rule nobody can apply is a rule nobody
        enforces.
        """
        data = await _payload()
        strings = _prose(data["precision"])
        assert len(strings) > 50, (
            f"the walk found only {len(strings)} prose strings, so it is not "
            f"covering the block and the rule is vacuous"
        )
        offenders = [
            (path, _fused(text)) for path, text in strings if _fused(text)
        ]
        assert not offenders, (
            "a sentence lost its boundary and is fused to a path: "
            + "; ".join(f"{path} -> {hits}" for path, hits in offenders)
        )

    def test_the_rule_is_not_vacuous(self):
        """It must still fire on the string this change removed.

        Without this the rule could be relaxed - the function-word list emptied,
        the space requirement dropped - and go green without fixing anything.
        """
        hits = _fused(PRE_FIX_INHERITANCE_REASON)
        assert hits, (
            "the pre-fix string no longer trips the rule, so the rule has been "
            "relaxed into vacuity and proves nothing"
        )
        assert ".the" in hits, hits

    def test_the_rule_does_not_fire_on_a_real_dotted_path(self):
        """The negative direction, on the paths this block actually publishes."""
        for path in (
            "app/services/analytics_engine.py",
            "np.clip",
            "precision.derived_values['positions.<ticker>.var_forecast']"
            ".derivation_precondition_evidence",
            "precision.estimated_statistics.positions.CIPLA.NS.estimates",
            "np.percentile(portfolio_returns, 5)",
            "tail_support.window_effective_n",
        ):
            assert not _fused(path), (path, _fused(path))

    def test_the_joiner_terminates_every_part_before_attaching_the_next(self):
        """The structural half of the fix, tested directly.

        The point is that there is no concatenation left in which a boundary can
        be forgotten: a part that does not end a sentence is given one.
        """
        assert _forecast_sentences("a path.", "the second") == (
            "a path. the second."
        )
        # a part with no terminator gets one rather than running into the next
        assert _forecast_sentences("a path", "the second") == "a path. the second."
        # empty parts are dropped, not rendered as a bare boundary
        assert _forecast_sentences("a.", "", "   ", "b.") == "a. b."
        assert _forecast_sentences("a.") == "a."
        # and the output can never contain the splice signature
        for parts in (
            ("x.estimates.", "the clause"),
            ("y.estimates", "the clause"),
            ("z", "the clause"),
        ):
            assert not _fused(_forecast_sentences(*parts)), parts

    def test_the_published_reasons_are_strings_and_not_tuple_reprs(self):
        """The bug this caught, kept as a test.

        `*` was missing on the conditional that chooses the branch, so the joiner
        received a TUPLE as its single argument, stringified it, and the payload
        published a repr of a tuple of sentences. It type-checks, it reads as
        English at a glance, and the existing pointer test caught it only
        incidentally - by failing on a token that had been in the repr.
        """
        data = asyncio.run(_payload())
        derived = data["precision"]["derived_values"]
        for name, entry in derived.items():
            reason = entry["inherits_precision_reason"]
            assert isinstance(reason, str), (name, type(reason))
            assert not reason.startswith("("), (name, reason[:80])
            assert "', '" not in reason, (name, reason[:120])
        for name in ("var_forecast", "cvar_forecast",
                     "tail_measure.cvar_to_var_ratio"):
            reason = derived[name]["inherits_precision_reason"]
            assert not reason.startswith("("), (name, reason[:80])


class TestTheInheritanceReasonIsTrue:
    @pytest.mark.asyncio
    async def test_the_leg_reason_names_a_path_that_resolves(self, fast_resamples):
        """The last path in the string used to be truncated by a period.

        `precision.estimated_statistics.portfolio.estimates.` resolved to
        nothing; the node that actually carries the portfolio leg's sigma is one
        segment longer. Every segment is a plain identifier, so this one IS
        resolvable by splitting on '.', unlike the per-leg path earlier in the
        same string (which the payload already discloses, because a ticker key
        contains dots of its own).
        """
        data = await _payload()
        reason = data["precision"]["derived_values"][
            "positions.AAA.NS.var_forecast"
        ]["inherits_precision_reason"]

        assert "precision.estimated_statistics.portfolio.estimates." in reason
        assert "estimates.the" not in reason
        node: Any = data
        for segment in (
            "precision.estimated_statistics.portfolio.estimates."
            "volatility_forecast".split(".")
        ):
            assert isinstance(node, dict), (segment, type(node))
            node = node[segment]
        # ...and it is a real figure, so the sentence's claim is checkable
        assert node["point"] is not None, node
        assert node["standard_error"] is not None, node

    @pytest.mark.asyncio
    async def test_the_leg_reason_no_longer_calls_the_point_absent(
        self, fast_resamples
    ):
        """An absent INTERVAL and an absent POINT are different facts.

        The string used to say "there is no figure at the far end of it and none
        is claimed", while the node it names published
        `point = 0.19598052754718792` with an observation count and an
        effective_n - and its own reason said the leg's re-fit estimator was
        declined. Two sentences, one object, disagreeing about the same absence.
        """
        data = await _payload()
        derived = data["precision"]["derived_values"]["positions.AAA.NS.var_forecast"]
        reason = derived["inherits_precision_reason"]
        assert "no figure at the far end" not in reason, reason
        assert "none is claimed" not in reason, reason
        # it now says which figure is missing, and which is present
        assert "standard error" in reason, reason
        assert "interval" in reason, reason
        assert "the point is there" in reason.lower(), reason

        # and the claim matches the node: the point IS published
        block = data["precision"]["estimated_statistics"]["positions"]["AAA.NS"]
        entry = block["estimates"]["volatility_forecast"]
        assert entry["point"] is not None, entry
        assert entry["point"] == data["positions"]["AAA.NS"]["volatility_forecast"]
        assert entry["standard_error"] is None, entry
        assert entry["conf_int"] is None, entry
        # ...and the node's own reason agrees with the sentence about why
        assert "too expensive" in entry["reason"], entry

    @pytest.mark.asyncio
    async def test_every_leg_gets_the_same_true_sentence(self, fast_resamples):
        """The defect was on every leg, so the fix is asserted on every leg."""
        data = await _payload()
        for ticker in TICKERS:
            reason = data["precision"]["derived_values"][
                f"positions.{ticker}.var_forecast"
            ]["inherits_precision_reason"]
            assert not _fused(reason), (ticker, reason)
            assert "no figure at the far end" not in reason, ticker
            assert "standard error" in reason, ticker


# ---------------------------------------------------------------------------
# 2. the arithmetic
# ---------------------------------------------------------------------------
class TestTheRefitArithmeticAddsUp:
    @pytest.mark.asyncio
    async def test_the_stated_total_is_the_sum_of_its_stated_parts(
        self, fast_resamples
    ):
        """Parse the paragraph and check it against itself.

        The defect was a total that did not equal its own parts, so the test is
        the general form of that: extract the counts as the prose states them and
        require the sum. Nothing here is compared against a literal, so the test
        cannot rot - it re-derives from whatever the sentence says.
        """
        text = (await _payload())["precision"]["measurements_withheld"][
            "why_not_measured"
        ]
        total = re.search(r"(\d+) refits in total", text)
        portfolio = re.search(r"portfolio leg's (\d+) refits", text)
        legs = re.search(r"legs' (\d+) were", text)
        assert total and portfolio and legs, text
        assert int(portfolio.group(1)) + int(legs.group(1)) == int(total.group(1)), (
            f"the paragraph states {total.group(1)} in total but its parts sum "
            f"to {int(portfolio.group(1)) + int(legs.group(1))}"
        )

    @pytest.mark.asyncio
    async def test_the_seconds_add_up_too(self, fast_resamples):
        """Left exactly as measured - 17.3 + 51.3 is 68.6 - and still checked."""
        text = (await _payload())["precision"]["measurements_withheld"][
            "why_not_measured"
        ]
        total = re.search(
            r"([\d.]+) s of pure optimiser time and ([\d.]+) s of route wall time",
            text,
        )
        # "…were the remaining 51.3 s" - anchored on 'remaining' because the
        # phrase before it also contains "were <n> s and the <n> legs' <n> were".
        parts = re.search(r"the remaining ([\d.]+) s", text)
        portfolio = re.search(r"refits were ([\d.]+) s", text)
        assert total and parts and portfolio, text
        assert float(portfolio.group(1)) + float(parts.group(1)) == float(
            total.group(1)
        ), (portfolio.group(1), parts.group(1), total.group(1))

    @pytest.mark.asyncio
    async def test_the_paragraph_and_the_structured_block_are_the_same_numbers(
        self, fast_resamples
    ):
        """One source, so the sentence cannot state a different total.

        The block publishes the arithmetic as NUMBERS as well as prose. That is
        what makes the sentence checkable without trusting a regex, and it is why
        a future edit to any of these constants moves both.
        """
        block = (await _payload())["precision"]["measurements_withheld"]
        arithmetic = block["refit_arithmetic"]
        text = block["why_not_measured"]

        # The IMPORT-TIME figures, not the live globals: this block is a record of
        # a cost that was measured, and the `fast_resamples` fixture deliberately
        # reduces the live draw count to 60. Reading the live global here is what
        # made the first version of this block publish
        # `portfolio_resamples: 60` beside `portfolio_fits: 1001`.
        assert arithmetic["portfolio_resamples"] == (
            FORECAST_WITHHELD_PORTFOLIO_RESAMPLES
        )
        assert FORECAST_WITHHELD_PORTFOLIO_RESAMPLES == 1000, (
            "the measured cost was taken at the module's standard draw count; if "
            "that constant moved, the recorded measurement is stale and has to "
            "be re-measured rather than restated"
        )
        assert arithmetic["resamples_per_leg"] == FORECAST_WITHHELD_LEG_RESAMPLES
        assert arithmetic["book_leg_count"] == FORECAST_WITHHELD_BOOK_LEGS
        # and explicitly NOT the reduced live count, which is the point
        assert arithmetic["portfolio_resamples"] != TEST_RESAMPLES
        # the freeze is observable: the LIVE global is patched to 60 by this
        # test's fixture while the recorded cost still reads the 1000 the
        # measurement was taken at.  Read off the module, not off the
        # `from ... import` copy, which is bound at import and is exactly the
        # thing that cannot see the patch.
        assert analytics_api.FORECAST_PORTFOLIO_REFIT_RESAMPLES == TEST_RESAMPLES, (
            "the fixture is supposed to reduce the live draw count; if it does "
            "not, the freeze assertion below is vacuous"
        )
        assert FORECAST_WITHHELD_PORTFOLIO_RESAMPLES == 1000
        assert FORECAST_WITHHELD_PORTFOLIO_RESAMPLES != (
            analytics_api.FORECAST_PORTFOLIO_REFIT_RESAMPLES
        )
        # every identity, checked rather than narrated
        assert arithmetic["portfolio_fits"] == (
            arithmetic["portfolio_resamples"] + arithmetic["portfolio_original_fits"]
        )
        assert arithmetic["leg_fits"] == (
            arithmetic["resamples_per_leg"] * arithmetic["book_leg_count"]
        )
        assert arithmetic["total_fits"] == (
            arithmetic["portfolio_fits"] + arithmetic["leg_fits"]
        )
        assert arithmetic["optimiser_seconds"] == pytest.approx(
            arithmetic["portfolio_seconds"] + arithmetic["leg_seconds"]
        )
        # and each of those numbers is the one the prose states
        for key in ("total_fits", "portfolio_fits", "leg_fits"):
            assert f"{arithmetic[key]} refits" in text or (
                f"{arithmetic[key]} were" in text
            ), (key, arithmetic[key], text[:400])
        assert f"{arithmetic['total_fits']} refits in total" in text, text[:400]
        assert f"portfolio leg's {arithmetic['portfolio_fits']} refits" in text

    @pytest.mark.asyncio
    async def test_the_plus_one_is_named_rather_than_absorbed(self, fast_resamples):
        """The `+1` is the ORIGINAL fit, and the payload says so.

        A reader who sees 1001 next to a `bootstrap_resamples` of 1000 has to be
        able to find out what the difference is without leaving the object, and
        the answer has to be that the extra fit is not a resample.
        """
        block = (await _payload())["precision"]["measurements_withheld"]
        arithmetic, text = block["refit_arithmetic"], block["why_not_measured"]
        assert arithmetic["portfolio_original_fits"] == 1
        assert FORECAST_WITHHELD_PORTFOLIO_FITS == (
            FORECAST_WITHHELD_PORTFOLIO_RESAMPLES + 1
        )
        assert "ORIGINAL" in text and "RESAMPLED" in text, text
        assert "not a resample" in text, text
        # and the two totals the block publishes agree with each other
        assert FORECAST_WITHHELD_TOTAL_FITS == (
            FORECAST_WITHHELD_PORTFOLIO_FITS + FORECAST_WITHHELD_LEG_FITS
        )
        assert str(FORECAST_WITHHELD_TOTAL_FITS) in text
        # the old wrong total is gone from the object
        assert "3800 refits" not in text
        assert arithmetic["total_fits"] == FORECAST_WITHHELD_TOTAL_FITS

    @pytest.mark.asyncio
    async def test_it_agrees_with_the_sibling_resample_count_rule(
        self, fast_resamples
    ):
        """Two strings in ONE block about ONE measurement must agree.

        `resample_count_rule` says the portfolio leg is resampled at the module's
        standard N. The withheld paragraph said a different number for the same
        leg. The reconciliation is that N is the RESAMPLE count and N + 1 is the
        FIT count, and both strings now say which they are quoting.
        """
        data = await _payload()
        precision = data["precision"]
        rule = precision["resample_count_rule"]
        arithmetic = precision["measurements_withheld"]["refit_arithmetic"]
        assert str(FORECAST_WITHHELD_PORTFOLIO_RESAMPLES) in rule, rule
        assert (
            f"{FORECAST_WITHHELD_PORTFOLIO_RESAMPLES} circular moving-block draws"
            in rule
        ), rule
        # the rule quotes the resample count; the arithmetic adds the original
        assert rule != precision["measurements_withheld"]["why_not_measured"]
        assert arithmetic["portfolio_resamples"] == (
            FORECAST_WITHHELD_PORTFOLIO_RESAMPLES
        )
        assert FORECAST_REFIT_COUNT_RULE == rule
        # the declined per-leg count is the same figure in both places
        assert str(FORECAST_WITHHELD_LEG_RESAMPLES) in rule
        assert arithmetic["resamples_per_leg"] == FORECAST_WITHHELD_LEG_RESAMPLES
        assert (
            precision["measurements_withheld"]["declined_draws_per_leg"]
            == FORECAST_LEG_REFIT_RESAMPLES_WITHHELD
        )

    @pytest.mark.asyncio
    async def test_the_declined_count_beside_the_paragraph_still_adds_up(
        self, fast_resamples
    ):
        """`leg_fits` is the declined count multiplied by the legs it applies to.

        The paragraph and the structured block are derived from the same
        constants, so this is the identity that would break first if a leg count
        and a per-leg count were ever quoted against each other.
        """
        withheld = (await _payload())["precision"]["measurements_withheld"]
        assert withheld["count"] == len(withheld["applies_to"])
        assert withheld["refit_arithmetic"]["book_leg_count"] == (
            FORECAST_WITHHELD_BOOK_LEGS
        )
        assert withheld["refit_arithmetic"]["leg_fits"] == (
            withheld["declined_draws_per_leg"] * FORECAST_WITHHELD_BOOK_LEGS
        )


# ---------------------------------------------------------------------------
# 3. nothing the fix touched moved
# ---------------------------------------------------------------------------
class TestNothingElseMoved:
    @pytest.mark.asyncio
    async def test_the_block_is_still_assembled_after_the_fit(self, fast_resamples):
        """`precision` is still a read-only view of the published skeleton.

        The block is built from `positions`, `forecast_result` and `estimated`
        and can only read them, so a fix that rewrote a published forecast rather
        than describing it would have to change one of these.  Every leg's
        `point` is the leg's published `volatility_forecast`, exactly.
        """
        data = await _payload()
        for ticker in TICKERS:
            entry = data["precision"]["estimated_statistics"]["positions"][
                ticker
            ]["estimates"]["volatility_forecast"]
            assert entry["point"] == data["positions"][ticker]["volatility_forecast"]
        derived = data["precision"]["derived_values"]
        assert set(derived) >= {
            "var_forecast", "cvar_forecast", "tail_measure.cvar_to_var_ratio",
        }
        # the block still publishes the declared constants it always did
        assert data["precision"]["declared_constants"]["constants"]["var_z_multiplier"]

    def test_the_precision_block_still_takes_the_same_arguments(self):
        """`model_sample`-style keyword discipline, for this block's own signature.

        Asserted rather than eyeballed because a positional argument slipping in
        is how a caller and a signature drift apart without either failing.
        """
        import inspect

        params = inspect.signature(_forecast_precision_block).parameters
        assert list(params) == [
            "model", "horizon", "forecast_result", "positions", "estimated",
            "raw_volatility",
        ], list(params)
        assert all(
            param.kind is inspect.Parameter.KEYWORD_ONLY
            for param in params.values()
        ), params
