"""XS-001/MY-1: `performance_history` declared no holding window at all.

The measured facts on the v13 export, and the reason this file exists:

* Twelve sibling holding-window blocks publish `intersection_start 2026-08-03`
  (`buy_price_inferred`) and `covered_days 20`
  (`holding_window_aligned_return_rows`).
* `tear_sheet.data.measured_window` publishes the SAME 20 observations as
  `start 2026-08-25` / `end 2026-09-23`, and already reconciles the two dates
  with `holding_window_start`, `holding_window_to_measured_start_gap_days 22`
  and a `measured_start_basis`.
* `performance_history` delivered the same 20 returns (21 rows, row 0 a warm-up
  row carrying `return: null`) from the same 2026-08-25, and published NONE of
  that: no `covered_days_scope`, no `intersection_start`, no provenance, and one
  causally empty sentence - "the requested start was not delivered" - which reads
  as absent data rather than as the refusal it is.

So the date was never the defect, and the sections never actually disagreed.
The defect was that the one section a reader most likely asks "how far back does
my portfolio chart go?" could not be checked against any other section, and that
its only explanation asserted a cause (`data unavailability`) that the artifact
itself contradicts. These tests pin the CAUSE, not the date:

1. the window start comes from the CANONICAL evidence window, not from this
   route's own request window (the v4 three-holding-dates mechanism);
2. a delivered start later than the window start is attributed to named legs,
   and the warning restates that attribution in checkable numbers;
3. the published block reconciles against a sibling under the real XS-001 rule,
   and a genuinely divergent sibling is still caught.
"""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from app.api.analytics import (
    HOLDING_COVERED_DAYS_SCOPE,
    HOLDING_EVIDENCE_CANONICAL,
    HOLDING_PROVENANCE_LOOKBACK_DAYS,
    PERFORMANCE_MEASURED_START_BASIS,
    get_performance_history,
)
from app.debugging import context_audit as ca
from app.utils.holdings import holding_window

# The route reads the wall clock for its requested window, so the fixtures are
# anchored on today rather than on a date that silently rots.
TODAY = pd.Timestamp(datetime.now()).normalize()

#: The one close in the fixture history that is within 2% of the buy price.
SPIKE_PRICE = 150.0


def _sessions(count, end=TODAY):
    return pd.bdate_range(end=pd.Timestamp(end), periods=count)


def _rising(count, *, step, end=TODAY):
    index = _sessions(count, end=end)
    return pd.Series(100.0 * np.exp(np.arange(len(index)) * step), index=index)


def _position(ticker, *, quantity=1.0, last_price=100.0, added_on=None, buy_price=None):
    return SimpleNamespace(
        ticker=ticker, region="IN", quantity=quantity, last_price=last_price,
        market_value=quantity * last_price, buy_price=buy_price, added_on=added_on,
    )


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        inner = self

        class _Scalars:
            def all(self_inner):
                return inner._rows

        return _Scalars()


def _db(rows):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=lambda *_a, **_k: _Rows(rows))
    return db


def _no_benchmark():
    return SimpleNamespace(get_returns=AsyncMock(return_value=pd.Series(dtype=float)))


class _Frames:
    """A per-ticker close series, optionally with a sparse (late) quote history.

    `sparse_before` maps a ticker to the date its bars start at, and the removal
    applies to EVERY response for that ticker, the canonical evidence window
    included, so nothing here can make a wider request look richer than a narrow
    one. It models one leg of a book that is simply not quoted on the early
    holding-window sessions - the condition the whole-basket refusal exists for.
    """

    def __init__(self, series, sparse_before=None):
        self.series = dict(series)
        self.sparse_before = dict(sparse_before or {})
        self.requests = []
        self.fetch_historical_data = AsyncMock(side_effect=self._fetch)

    def window(self, ticker, start, end):
        index = self.series[ticker].index
        cutoff = self.sparse_before.get(ticker)
        if cutoff is not None:
            index = index[index.normalize() >= pd.Timestamp(cutoff)]
        return index[(index >= pd.Timestamp(start)) & (index <= pd.Timestamp(end))]

    async def _fetch(self, ticker, start, end):
        self.requests.append((ticker, start, end))
        index = self.window(ticker, start, end)
        # Real supplied closes, reindexed to the requested window: a fixture that
        # regenerated prices would quietly discard the buy-price match the
        # canonical-evidence test depends on.
        return pd.DataFrame({"close": self.series[ticker].reindex(index)}, index=index)


async def _envelope(frames, positions, *, days=90):
    return await get_performance_history(
        days=days,
        tickers=",".join(p.ticker for p in positions),
        include_metadata=True,
        db=_db(positions),
        data_service=frames,
        benchmark_service=_no_benchmark(),
    )


# ---------------------------------------------------------------------------
# 1. the cause: the window start came from THIS route's request window
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_window_start_comes_from_the_canonical_evidence_window():
    """The buy-price inference must see the canonical window, not `days` of bars.

    A narrow request window is a viewing choice. When the inference was fed it,
    a position whose buy price matches a bar months earlier resolved to its
    stored import date instead - a second holding-window start for one portfolio,
    which is the v4 defect the canonical rule exists to remove.
    """
    index = _sessions(320)
    match = index[index <= TODAY - pd.Timedelta(days=180)][-1]
    values = np.full(len(index), 100.0)
    values[index == match] = SPIKE_PRICE

    frames = _Frames({"AAA.NS": pd.Series(values, index=index)})
    imported_on = str((TODAY - pd.Timedelta(days=2)).date())
    envelope = await _envelope(frames, [_position("AAA.NS", added_on=imported_on,
                                                   buy_price=SPIKE_PRICE)])
    coverage = envelope["history_coverage"]
    holding = coverage["holding_window"]

    # The canonical window was actually read, and it is wider than the request.
    canonical = holding["provenance_evidence_window"]
    assert canonical["days"] == HOLDING_PROVENANCE_LOOKBACK_DAYS
    assert canonical["source"] == HOLDING_EVIDENCE_CANONICAL
    assert canonical["start"] < coverage["requested_start"]

    # One holding date for the portfolio, resolved from evidence, not from the
    # stored stamp: the inferred start wins and the stored date is published.
    assert holding["intersection_start"] == str(match.date())
    assert holding["intersection_start_source"] == "buy_price_inferred"
    leg = holding["tickers"]["AAA.NS"]
    assert leg["analytics_start"] == str(match.date())
    assert leg["buy_price_inferred"] == str(match.date())
    assert leg["stored_added_on"] == imported_on

    # The mechanism this replaces, demonstrated rather than described: fed its
    # OWN request frames, the same inference resolves the stored import date.
    request_window = frames.window("AAA.NS", coverage["requested_start"], coverage["requested_end"])
    _, local_effectives = holding_window(
        {"AAA.NS": pd.Series(1.0, index=request_window)},
        {"AAA.NS": {"added_on": imported_on, "buy_price": SPIKE_PRICE}},
    )
    assert local_effectives["AAA.NS"] == imported_on
    assert local_effectives["AAA.NS"] != holding["intersection_start"]

    # And the series is masked to the start the block PUBLISHES, not to the one
    # the local inference would have produced. A block that declared a canonical
    # start while masking at a different one would be exactly the two-dates
    # defect, wearing the canonical label.
    canonical_rows = int((request_window >= pd.Timestamp(match)).sum())
    local_rows = int((request_window >= pd.Timestamp(imported_on)).sum())
    assert canonical_rows > local_rows
    assert leg["masked_days"] == canonical_rows
    assert leg["masked_days"] != local_rows


# ---------------------------------------------------------------------------
# 2. the late delivered start is attributed, and the warning matches it
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_late_delivered_start_is_attributed_to_named_legs():
    """A start after the holding window is a REFUSAL, and must name its cause.

    The delivered start is later than the holding window because a whole-book
    portfolio value needs a price on every leg. Publishing only "the requested
    start was not delivered" made that read as absent data; the legs and the
    refused-session count are what make it checkable.
    """
    window_start = str((TODAY - pd.Timedelta(days=40)).date())
    quoted_from = TODAY - pd.Timedelta(days=20)
    frames = _Frames(
        {
            "AAA.NS": _rising(60, step=0.0010),
            "BBB.NS": _rising(60, step=0.0012),
            "SPARSE.NS": _rising(60, step=0.0009),
        },
        sparse_before={"SPARSE.NS": quoted_from},
    )
    positions = [_position(t, added_on=window_start) for t in ("AAA.NS", "BBB.NS", "SPARSE.NS")]

    envelope = await _envelope(frames, positions)
    coverage = envelope["history_coverage"]
    holding = coverage["holding_window"]

    assert holding["intersection_start"] == window_start
    # The window start and the delivered start are different facts, both true,
    # and the block reconciles them instead of leaving the pair unexplained.
    assert coverage["delivered_start"] > window_start
    assert holding["holding_window_start"] == window_start
    assert holding["delivered_measured_start"] == coverage["delivered_start"]
    assert holding["holding_window_to_measured_start_gap_days"] == (
        pd.Timestamp(coverage["delivered_start"]) - pd.Timestamp(window_start)
    ).days
    assert holding["measured_start_basis"] == PERFORMANCE_MEASURED_START_BASIS

    # The cause, by name: only the leg that is genuinely unquoted is blamed.
    assert [entry["ticker"] for entry in holding["refused_coverage_legs"]] == ["SPARSE.NS"]
    blamed = holding["refused_coverage_legs"][0]
    assert blamed["refused_price_rows"] > 0
    assert blamed["refused_price_rows"] == holding["refused_partial_coverage_price_rows"]
    assert blamed["held_price_rows"] < holding["tickers"]["AAA.NS"]["masked_days"]

    # The count is in the sibling sections' unit, so the two are comparable: it
    # is the measured return rows, and row 0 of the series is the warm-up row
    # whose own return is null, not a return observation.
    assert holding["covered_days_scope"] == HOLDING_COVERED_DAYS_SCOPE
    assert holding["covered_days"] == len(envelope["data"])
    assert envelope["data"][0]["return"] is None
    assert sum(1 for row in envelope["data"] if row["return"] is not None) == (
        holding["covered_days"] - 1
    )

    # The warning states the cause in numbers that are also on the block.
    truncated = [text for text in envelope["warnings"] if "was not delivered" in text]
    assert len(truncated) == 1, envelope["warnings"]
    text = truncated[0]
    assert window_start in text
    assert "refused" in text
    assert "SPARSE.NS" in text
    assert f"{blamed['refused_price_rows']} holding-window session(s)" in text
    assert "AAA.NS" not in text and "BBB.NS" not in text


# ---------------------------------------------------------------------------
# 3. the block now reconciles against a sibling, and still catches a liar
# ---------------------------------------------------------------------------
def _component(envelope):
    return {
        "status": envelope["data_status"],
        "data": envelope["data"],
        "as_of": envelope["as_of"],
        "as_of_semantics": envelope["as_of_semantics"],
        "history_coverage": envelope["history_coverage"],
        "warnings": envelope["warnings"],
    }


def _export(components):
    return {
        "schema_version": "2.0",
        "generated_at": f"{TODAY.date()}T10:00:00Z",
        "completed_at": f"{TODAY.date()}T10:05:00Z",
        "base_currency": "INR",
        "sections": {
            "dashboard": {
                "as_of": f"{TODAY.date()}T10:00:00Z",
                "data": {"components": components},
            }
        },
    }


def _findings(doc, rule):
    return rule(ca.Export(doc=doc, raw=json.dumps(doc)))


def _sibling(holding, covered_days):
    """A `realized_risk`-shaped block carrying the same measured window."""
    return {
        "history_coverage": {
            "requested_start": holding["requested_start"],
            "requested_end": holding["requested_end"],
            "effective_start": holding["intersection_start"],
            "intersection_start": holding["intersection_start"],
            "intersection_start_source": holding["intersection_start_source"],
            "covered_days": covered_days,
            "covered_days_scope": HOLDING_COVERED_DAYS_SCOPE,
            "truncated": True,
            "annualized": False,
        }
    }


async def _two_leg_envelope():
    frames = _Frames(
        {"AAA.NS": _rising(60, step=0.0010), "BBB.NS": _rising(60, step=0.0012)},
        sparse_before={"BBB.NS": TODAY - pd.Timedelta(days=20)},
    )
    window_start = str((TODAY - pd.Timedelta(days=40)).date())
    positions = [_position(t, added_on=window_start) for t in ("AAA.NS", "BBB.NS")]
    return await _envelope(frames, positions)


@pytest.mark.asyncio
async def test_published_window_agrees_with_a_sibling_block_under_xs_001():
    """The section is now comparable, and a divergent sibling is still reported."""
    envelope = await _two_leg_envelope()
    holding = envelope["history_coverage"]["holding_window"]

    agree = _export({
        "performance_history": _component(envelope),
        "realized_risk": _sibling(holding, holding["covered_days"]),
    })
    assert _findings(agree, ca.xs_001_holding_window_agreement) == []

    # Not vacuous: change the sibling's count and the rule still reports it.
    disagree = _export({
        "performance_history": _component(envelope),
        "realized_risk": _sibling(holding, holding["covered_days"] + 3),
    })
    findings = _findings(disagree, ca.xs_001_holding_window_agreement)
    assert [f.rule_id for f in findings] == ["XS-001"]
    assert "covered_days" in findings[0].message

    # And a block that publishes both dates must still reconcile them (XS-010).
    assert _findings(agree, ca.xs_010_holding_window_start_matches_itself) == []


@pytest.mark.asyncio
async def test_covered_days_does_not_move_with_the_benchmark_leg():
    """The holding-window count is measured on the book, not on the deliveries.

    A session withheld because the benchmark had no measurement is still a
    measured whole-book return. Counting deliveries instead would make this
    section's `covered_days` disagree with its siblings' for a reason that has
    nothing to do with the holding window - which is the disagreement XS-001
    exists to report.
    """
    window_start = str((TODAY - pd.Timedelta(days=40)).date())
    frames = _Frames(
        {"AAA.NS": _rising(60, step=0.0010), "BBB.NS": _rising(60, step=0.0012)},
    )
    positions = [_position(t, added_on=window_start) for t in ("AAA.NS", "BBB.NS")]
    index = frames.series["AAA.NS"].index

    whole = await get_performance_history(
        days=90, tickers="AAA.NS,BBB.NS", include_metadata=True, db=_db(positions),
        data_service=frames, benchmark_service=_no_benchmark(),
    )
    # A benchmark whose returns stop before the book's newest price: that session
    # has no measured benchmark, so it is withheld, not delivered.
    short_bench = SimpleNamespace(get_returns=AsyncMock(
        return_value=pd.Series(0.002, index=index[index < index[-1]])
    ))
    withheld = await get_performance_history(
        days=90, tickers="AAA.NS,BBB.NS", include_metadata=True, db=_db(positions),
        data_service=frames, benchmark_service=short_bench,
    )

    assert len(withheld["data"]) == len(whole["data"]) - 1
    whole_days = whole["history_coverage"]["holding_window"]["covered_days"]
    withheld_days = withheld["history_coverage"]["holding_window"]["covered_days"]
    # Identical, because the withheld session was still a measured book return,
    # and equal to the WHOLE delivery count rather than the shorter one.
    assert withheld_days == whole_days == len(whole["data"])
    assert withheld_days != len(withheld["data"])


@pytest.mark.asyncio
async def test_no_holding_window_is_declared_as_none_not_as_a_bare_count():
    """An unresolvable window publishes no count, so it joins no comparison.

    A `covered_days` with no `covered_days_scope` is an unlabelled number
    (XS-002), and a block that claimed the holding-window scope without one would
    be cross-compared against a population it does not belong to.
    """
    frames = _Frames({"AAA.NS": _rising(60, step=0.0010)})
    envelope = await _envelope(frames, [_position("AAA.NS")])

    assert envelope["data"], "the series itself is still delivered"
    assert envelope["history_coverage"]["holding_window"] is None
    doc = _export({"performance_history": _component(envelope)})
    assert _findings(doc, ca.xs_002_covered_days_requires_scope) == []
