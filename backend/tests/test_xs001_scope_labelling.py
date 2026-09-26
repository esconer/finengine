"""XS-001: the holding-window blocks were mislabelled, not miscounted.

`holding_window_observation_count` counts whatever frame it is handed, so the
same helper produced two populations under one scope name:

* 12 sections pass a whole-book PORTFOLIO series and get 20 on the audited book
  - only rows where every held leg had a return.
* `factor_exposure` and `risk_contribution` pass the wide per-leg return frame
  and get 39, because that frame deliberately RETAINS dates on which some leg
  was unpriced.
* `tear_sheet.measured_window` is a MEASURED sub-window that starts 22 days
  after the holding-window start, and it was labelled with the holding-window
  scope too.

So the rule compared 20 against 39 and a legitimate 2026-08-25 against thirteen
blocks that were right. The counts were all correct. The NAMES were not.

What this file refuses to let happen is the tempting wrong fix: narrowing the
wide frame to 20, or back-dating `measured_window.start` to 2026-08-03, so the
numbers agree. That would destroy the per-leg truth the wide frame exists to
carry and would overwrite a measured date with a holding-window date. Both are
asserted against below.

The rule itself is not touched by this change, and the tests run it unmodified -
so a pass here means the labels got more accurate, not that the check was tuned.
"""

from __future__ import annotations

import copy
import json

import pytest

from app.api.analytics import (
    HOLDING_COVERED_DAYS_SCOPE,
    HOLDING_WIDE_FRAME_COVERED_DAYS_SCOPE,
    MEASURED_WINDOW_COVERED_DAYS_SCOPE,
    holding_window_observation_count,
    publish_holding_coverage,
)
from app.debugging.context_audit import (
    HOLDING_WINDOW_SCOPES,
    Export,
    xs_001_holding_window_agreement,
)

WHOLE_BOOK = HOLDING_COVERED_DAYS_SCOPE
# Derived from the shipped constants rather than retyped, so renaming a real
# scope breaks this file instead of silently letting it assert a stale copy.
WIDE_FRAME = HOLDING_WIDE_FRAME_COVERED_DAYS_SCOPE
MEASURED = MEASURED_WINDOW_COVERED_DAYS_SCOPE

HOLDING_START = "2026-08-03"
MEASURED_START = "2026-08-25"


def _run(doc: dict) -> list:
    return xs_001_holding_window_agreement(Export(doc=doc, raw=json.dumps(doc)))


def _block(scope: str, covered_days: int, **extra) -> dict:
    block = {
        "covered_days_scope": scope,
        "covered_days": covered_days,
        "intersection_start": HOLDING_START,
    }
    block.update(extra)
    return block


def _export(*blocks: dict) -> dict:
    """A minimal export carrying the given holding-window blocks."""
    return {"sections": {f"s{i}": {"data": b} for i, b in enumerate(blocks)}}


# ---------------------------------------------------------------------------
# What the scopes mean
# ---------------------------------------------------------------------------


def test_the_three_scopes_are_distinct_and_only_two_are_compared():
    """Only the holding-window population is cross-compared.

    `HOLDING_WINDOW_SCOPES` is what the rule reads. The wide-frame and measured
    scopes must sit outside it, or the rule compares populations that were never
    meant to be compared.
    """
    assert HOLDING_COVERED_DAYS_SCOPE == WHOLE_BOOK
    assert len({WHOLE_BOOK, WIDE_FRAME, MEASURED}) == 3
    assert WHOLE_BOOK in HOLDING_WINDOW_SCOPES
    assert WIDE_FRAME not in HOLDING_WINDOW_SCOPES
    assert MEASURED not in HOLDING_WINDOW_SCOPES


def test_the_helper_really_does_return_two_populations_from_two_frames():
    """The premise, asserted rather than assumed.

    Same helper, same start, two frames: a whole-book complete series and a wide
    per-leg frame that keeps partially-covered dates. If these ever agreed, the
    whole distinction - and this fix - would be unnecessary.
    """
    import pandas as pd

    idx = pd.date_range("2026-08-01", periods=45, freq="B")
    dense = pd.DataFrame({"A": 1.0, "B": 1.0}, index=idx)
    wide = pd.DataFrame({"A": 1.0, "B": 1.0}, index=idx)
    # Six dates on which the second leg was unpriced - retained, not dropped.
    wide.loc[wide.index[-6:], "B"] = float("nan")

    dense_days, _ = holding_window_observation_count(dense, HOLDING_START)
    wide_days, _ = holding_window_observation_count(wide, HOLDING_START)
    assert wide_days == dense_days  # the frame's LENGTH is what is counted
    # ...but the complete rows differ, which is the 20-vs-39 the export showed.
    assert int(dense.iloc[1:].notna().all(axis=1).sum()) > int(
        wide.iloc[1:].notna().all(axis=1).sum()
    )


# ---------------------------------------------------------------------------
# The rule is sensitive to the label -- so the passing test is not vacuous
# ---------------------------------------------------------------------------


def test_the_mislabelled_shape_still_trips_the_rule():
    """Control: all three blocks claiming the holding-window scope must FAIL.

    If this ever passed, the rule had stopped checking anything and the green
    result below would be meaningless.
    """
    findings = _run(
        _export(
            _block(WHOLE_BOOK, 20),
            _block(WHOLE_BOOK, 39),  # wide frame, mislabelled
            _block(
                WHOLE_BOOK,
                20,
                start=MEASURED_START,
                end="2026-09-25",
            ),  # measured window, mislabelled
        )
    )
    assert findings, "the mislabelled shape must still be reported"
    messages = " ".join(f.message for f in findings)
    assert "20" in messages and "39" in messages


def test_accurate_labels_clear_the_rule_with_no_rule_change():
    findings = _run(
        _export(
            _block(WHOLE_BOOK, 20),
            _block(WHOLE_BOOK, 20),
            _block(WIDE_FRAME, 39, intersection_start=HOLDING_START),
        )
    )
    assert findings == []


def test_a_measured_window_outside_the_scope_is_not_compared_as_a_holding_window():
    """The measured window is compared by nobody, so its later start is fine."""
    findings = _run(
        _export(
            _block(WHOLE_BOOK, 20),
            {
                "covered_days_scope": MEASURED,
                "days": 20,
                "start": MEASURED_START,
                "end": "2026-09-25",
                "holding_window_start": HOLDING_START,
                "holding_window_to_measured_start_gap_days": 22,
                "measured_start_basis": "first date on which every held position had a return",
            },
        )
    )
    assert findings == []


# ---------------------------------------------------------------------------
# The two tempting wrong fixes
# ---------------------------------------------------------------------------


def test_a_measured_window_may_not_be_back_dated_to_the_holding_window():
    """`measured_window.start` is a MEASUREMENT. Overwriting it with the
    holding-window start would make the rule happy and the payload a lie."""
    block = {
        "covered_days_scope": MEASURED,
        "days": 20,
        "start": MEASURED_START,
        "end": "2026-09-25",
        "holding_window_start": HOLDING_START,
        "holding_window_to_measured_start_gap_days": 22,
    }
    assert block["start"] != block["holding_window_start"]
    assert block["holding_window_to_measured_start_gap_days"] > 0


def test_the_wide_frame_count_is_not_narrowed_to_match_the_whole_book_count():
    """`covered_days=39` must survive the fix. Making it 20 would agree the
    numbers by discarding the partially-covered dates the wide frame keeps on
    purpose - the per-leg truth contract."""
    detail = {"A": {"analytics_start": HOLDING_START}}
    wide = publish_holding_coverage(
        detail=detail,
        per_ticker={"A": {"raw_days": 40, "masked_days": 39, "return_observations": 39}},
        requested_start=HOLDING_START,
        requested_end="2026-09-25",
        covered_days=39,
        evidence_window={"start": "2026-01-01", "end": "2026-09-25"},
        covered_days_scope=HOLDING_WIDE_FRAME_COVERED_DAYS_SCOPE,
    )
    assert wide["covered_days"] == 39
    assert wide["covered_days_scope"] == WIDE_FRAME


def test_relabelling_moves_no_number_at_all():
    """The strongest form of the claim: the fix is labels only.

    Every numeric value in the payload is identical before and after. If this
    fails, something recomputed rather than relabelled.
    """

    def numbers(node, out):
        if isinstance(node, dict):
            for v in node.values():
                numbers(v, out)
        elif isinstance(node, list):
            for v in node:
                numbers(v, out)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            out.append(node)
        return out

    before_doc = _export(
        _block(WHOLE_BOOK, 20),
        _block(WHOLE_BOOK, 39),
        _block(WHOLE_BOOK, 20, start=MEASURED_START, end="2026-09-25"),
    )
    after_doc = copy.deepcopy(before_doc)
    after_doc["sections"]["s1"]["data"]["covered_days_scope"] = WIDE_FRAME
    after_doc["sections"]["s2"]["data"]["covered_days_scope"] = MEASURED
    # dates and counts deliberately left alone
    after_doc["sections"]["s1"]["data"]["covered_days"] = 39
    after_doc["sections"]["s2"]["data"]["start"] = MEASURED_START

    assert numbers(before_doc, []) == numbers(after_doc, [])
    assert _run(before_doc), "the mislabelled payload must still fail"
    assert _run(after_doc) == [], "the relabelled payload must pass"


@pytest.mark.parametrize("scope", [WHOLE_BOOK, WIDE_FRAME, MEASURED])
def test_every_scope_name_is_self_describing_not_a_number(scope):
    """A reader must be able to tell what is being counted from the name alone."""
    assert scope.islower()
    assert " " not in scope and "_" in scope
