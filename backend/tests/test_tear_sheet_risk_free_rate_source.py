"""The tear sheet must spend the CONFIGURED risk-free rate, and publish it.

THE DEFECT.  Two literals for one number:

    app/config.py:53       risk_free_rate: float = Field(default=0.02)
    app/api/analytics.py   TEAR_SHEET_RISK_FREE_RATE = 0.02

and five more at the points of use, `rf=0.02` handed straight to `quantstats`
in the three metric blocks.  So the tear sheet deducted a rate compiled into its
own source while every other consumer - the engine (`self.risk_free_rate =
settings.risk_free_rate`, `analytics_engine.py:3630`), the optimizer, the
backtester - read the configured one.  An operator who set `RISK_FREE_RATE` got
a portfolio whose Sharpe, Sortino and every band around them were computed at a
different rate than the rest of the product reports, and the payload's own
`notes.risk_free_rate` said 0.06 beside numbers that were 0.02.  That is the
fabricated stand-in this repo's recurring defect is about: the number on the
page is not the number the number claims to be.

WHY THE HELPERS MATTER.  Two of the five literals had travelled off the event
loop with `_tear_sheet_holding_metrics` (:9335) and `_tear_sheet_payload`
(:9398), whose bodies were moved verbatim.  A literal does not stop being a
literal because the function around it was refactored onto a worker thread, and
both of those functions are called from `_run_cpu`, so the check below reads
them the way the route reaches them.

WHAT IS ASSERTED, AND WHY IT IS NOT A VALUE CHECK.  Nothing here asserts 0.02.
2% may or may not be the right number for an Indian book; that is an open
question with an owner and this change does not take a position on it.  What is
asserted is that there is exactly ONE definition left, it is `settings`, and
every published figure and every disclosure on the tear sheet names the same
value - which is what makes the rate auditable no matter what it is set to.

No network: seeded RNG only, isolated in-memory DB.
"""

from __future__ import annotations

import inspect
import re

import pytest

from app.api import analytics as analytics_mod
from app.api.analytics import (
    _tear_sheet_holding_metrics,
    _tear_sheet_payload,
    _tear_sheet_uncertainty,
)
from app.config import settings

#: The three functions the tear sheet's published numbers come out of.  Read by
#: `inspect`, not imported and re-listed, so this file cannot drift from the
#: route by naming a function the route stopped calling.
_TEAR_SHEET_WORKERS = (
    _tear_sheet_holding_metrics,
    _tear_sheet_uncertainty,
    _tear_sheet_payload,
)


def _source(function) -> str:
    return inspect.getsource(function)


def _bare_rate_literals(source: str) -> list[str]:
    """Every `0.02`-shaped literal in `source`, comments and docstrings excluded.

    Comments are stripped rather than excluded by hand because the reasoning
    that a value came from settings has to be allowed to NAME the value it came
    from - a check that failed on its own explanation would be a check that
    silences the next reader.
    """
    code = "\n".join(
        line.split("#", 1)[0] for line in source.splitlines()
    )
    return re.findall(r"(?<![\w.])0\.02(?![\w])", code)


def _rate_reader_defects(source: str, label: str) -> list[str]:
    """Every point of use in `source` that does NOT read the configured rate.

    Two reader shapes, because the route has two call shapes:
    `qs.stats.*(..., rf=rf)` for the published figures, and
    `quantstats_ratio_statistics(rf)` for the restatements their bands are
    measured with.  A band built over a different rate than the point estimate
    beside it is a band of a different statistic, so both are checked.

    A pure function of the source TEXT, not of the imported module, so the same
    predicate can be pointed at a copy of the file to show it is not vacuous.
    """
    defects: list[str] = []
    aliases = dict(re.findall(r"^ *(\w+) = (\S+)$", source, re.MULTILINE))
    named = [value.strip() for value in re.findall(r"rf=([^,)]+)", source)]
    positional = [
        value.strip()
        for value in re.findall(r"quantstats_ratio_statistics\(\s*([^)]+?)\s*\)", source)
    ]
    if not named and not positional:
        defects.append(
            f"{label} hands no rate to anything - did the metric block change "
            "shape?"
        )
    for name in named:
        if name not in aliases:
            defects.append(f"{label} passes rf={name!r}, which nothing binds")
        elif aliases[name] != "settings.risk_free_rate":
            defects.append(
                f"{label} binds {name} from {aliases[name]!r}, not from the "
                "configured rate"
            )
    for value in positional:
        if value != "settings.risk_free_rate":
            defects.append(
                f"{label} builds its restatement suite at {value!r}, not at the "
                "configured rate"
            )
    return defects


def test_the_module_no_longer_carries_its_own_risk_free_rate():
    """The duplicated constant is gone, and nothing took its place."""
    assert not hasattr(analytics_mod, "TEAR_SHEET_RISK_FREE_RATE"), (
        "the module-level copy is back: a request that reads it gets a rate "
        "captured at import, not the configured one"
    )
    literals = _bare_rate_literals(_source(analytics_mod))
    assert literals == [], (
        f"analytics.py still carries a bare 0.02 literal ({literals}); the "
        "risk-free rate is defined once, in app/config.py"
    )


@pytest.mark.parametrize("worker", _TEAR_SHEET_WORKERS, ids=lambda f: f.__name__)
def test_no_tear_sheet_worker_deducts_a_hardcoded_rate(worker):
    """The moved-verbatim bodies did not take a literal with them.

    `rf=0.02` used to sit in the holding-window block, in the full-depth block
    and in the benchmark block.  Two of those three were inside the two
    functions that were moved onto a worker thread, so reading the ROUTE would
    not see them - the functions have to be read directly.
    """
    literals = _bare_rate_literals(_source(worker))
    assert literals == [], (
        f"{worker.__name__} deducts a hardcoded rate: {literals}. quantstats "
        "must be handed settings.risk_free_rate, so a configured rate moves "
        "this route's figures with it"
    )


@pytest.mark.parametrize("worker", _TEAR_SHEET_WORKERS, ids=lambda f: f.__name__)
def test_every_published_quantstats_call_reads_the_configured_rate(worker):
    """The call SITES name settings, not merely the absence of a literal.

    A regex for `0.02` is satisfied by a refactor that reads the rate into a
    local once, and equally by one that passes a different hardcoded number.  So
    the point of use is checked directly, through the NAME each `rf=` is handed:
    that name has to be bound by an assignment whose right-hand side is
    `settings.risk_free_rate`, the only definition left in the module.
    """
    defects = _rate_reader_defects(_source(worker), worker.__name__)
    assert defects == [], defects


def test_the_configured_rate_is_what_the_settings_object_carries():
    """Non-vacuity for the check above.

    The point-of-use assertions pass on a module whose `settings` is not the
    application's settings object.  Pin that the name resolves to the same
    object the engine and every service read, and that it carries a real finite
    rate - a `None` or a NaN default would make every figure above agree with
    every other figure while all of them were wrong.
    """
    import math

    assert analytics_mod.settings is settings
    assert isinstance(settings.risk_free_rate, float)
    assert math.isfinite(settings.risk_free_rate)


def test_the_tear_sheet_publishes_the_rate_it_deducted():
    """`notes.risk_free_rate` must equal the rate quantstats was handed.

    This is the disclosure the duplication made false: the note is what a reader
    checks the published Sharpe against, and it is the field that would have
    said 0.06 beside 0.02 numbers.  It predates this change and is not touched by
    it; it is checked here because a disclosure that stops describing the figure
    beside it is the defect in its purest form.
    """
    import numpy as np

    series = np.random.default_rng(5).normal(0.0004, 0.011, 400)
    import pandas as pd

    frame = pd.Series(series, index=pd.bdate_range("2024-01-01", periods=400))
    published = {"sharpe": None, "sortino": None}
    block = _tear_sheet_uncertainty(
        frame, published, scope="the rate check's own fixture"
    )
    notes = block["notes"]
    assert notes["risk_free_rate"] == settings.risk_free_rate
    assert notes["risk_free_rate_basis"], (
        "the basis sentence that explains how quantstats deannualises the rate "
        "must stay beside the rate"
    )
    # A stored `None` would satisfy `.get(key, default)`; the key must be there.
    assert "risk_free_rate" in notes