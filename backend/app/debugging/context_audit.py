"""Read-only audit CLI for the portfolio AI-context export.

WHY THIS EXISTS
---------------
Every regression in the v3/v4 remediation was found the same way: generate an
export, read a handful of fields by hand, diff it against a baseline, argue
about whether the number is a defect or a rounding artefact.  That loop was run
by hand many times and it is the reason the audit trail in
``.scratch/ai-context-v3-remediation-2026-09/`` reads like a lab notebook.

This module turns the loop into three commands so the *next* regression is a
non-zero exit code rather than a subagent's opinion:

``generate``
    Fetch a fresh export over plain ``urllib`` and write the response BYTES to
    a gitignored path.  Bytes, not a decoded string: PowerShell's
    ``Invoke-WebRequest`` decodes UTF-8 as Latin-1 and silently turns an em
    dash into ``â\\x80\\x94``, which was very nearly reported as a product bug.

``check``
    Run every rule in :data:`RULES` against a parsed export and exit non-zero
    on any finding.  The table is data-driven so a new invariant is one entry
    and ``rules`` prints it for free.

``diff``
    Walk two exports field by field and report every added / removed / changed
    path, minus a small, *printed* allow-list of genuinely volatile fields.  The
    allow-list is printed rather than trusted so a reader can see what was
    excluded instead of wondering why a re-run was quiet.

The tool never writes to a portfolio endpoint and never mutates an export.  It
only reads them.

DEFECT PROVENANCE
-----------------
Six rules were written against specific defects recorded in
``.scratch/ai-context-v3-remediation-2026-09/open-defects.md`` and are still
marked ``catches D-0x`` in their descriptions.  Those defects are now FIXED, so
the rules are expected to be GREEN; the marker is kept so nobody deletes a rule
believing it was written speculatively, and so the reason each exists stays
readable.  If one of them ever goes red again, the same defect has returned.

Two further defects from that file are NOT checkable from an artifact and so
have no rule: D-07 is a FastAPI ``response_model`` re-serialisation issue
visible only over HTTP, and D-08 is filtering logic that publishes nothing.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path
from typing import Any, NamedTuple

# --------------------------------------------------------------------------
# Contract constants.  These mirror docs/ai-context.md; when the doc moves,
# they move here in the same change.
# --------------------------------------------------------------------------

EXPECTED_SCHEMA_VERSION = "2.0"

SECTION_STATUS_VOCABULARY = frozenset({"available", "partial", "unavailable"})
DATA_STATUS_VOCABULARY = frozenset({"available", "partial", "unavailable"})
COVERAGE_STATUS_VOCABULARY = frozenset(
    {"complete", "partial", "unavailable", "unknown"}
)
#: Words that belong to the coverage axis.  ``data_status`` must never borrow
#: them -- "did measurable data exist" and "how much of the universe reached
#: the result" are different questions (docs/ai-context.md, "Three separate
#: status axes").
COVERAGE_ONLY_WORDS = frozenset({"complete", "unknown"})

CANONICAL_WEIGHT_BASIS = "active_weights_renormalized_to_100_percent"
ANALYTICS_START_SOURCES = frozenset(
    {"stored_added_on", "buy_price_inferred", "unknown"}
)
EXPLICIT_ZERO_SHARE_STATUSES = frozenset(
    {"below_minimum_notional", "price_unavailable", "immaterial_no_op"}
)

#: A section publishes its unit by echoing the first non-blank of these keys,
#: scanning ``inputs`` then ``data`` then each component payload.  If one of
#: them is populated and ``section.currency`` is null, the section is carrying
#: money without declaring what it is denominated in.
CURRENCY_SOURCE_KEYS = ("currency", "base_currency", "portfolio_value_currency", "value_currency")

#: Keys that, when non-null, prove the payload contains dated observations.
#: Deliberately EXCLUDES ``data_range`` / ``requested_*`` / ``window``: the docs
#: keep requested window bounds beside the data precisely so they are never
#: substituted for an observation date.
DATED_OBSERVATION_KEYS = (
    "latest_observation_date",
    "last_observation",
    "last_observation_date",
    "first_observation",
    "observation_date",
    "delivered_start",
    "delivered_end",
    "model_as_of",
    "valuation_date",
    "quote_date",
    "pricing_date",
    "trading_date",
    "as_of",
)

#: ``covered_days_scope`` literals that all describe THE SAME holding window.
#: Any other scope (model windows, conditional regime days) legitimately has a
#: different count and must not be cross-compared with these.
HOLDING_WINDOW_SCOPES = frozenset(
    {"holding_window_aligned_return_rows", "portfolio_return_observations"}
)

#: Rows a return series can legitimately lose when it is differenced and
#: aligned across tickers: the first price row yields no return, and exchange
#: calendars can drop a further row.  A ``masked_days`` / ``return_observations``
#: gap wider than this means the two fields are in different units.
RETURN_ROW_SLACK = 2

#: Two independently 4dp-rounded products of the same 4dp inputs can differ by
#: up to one rounding step each, so the stress identity is checked at 2 steps.
ROUNDING_STEP_TOLERANCE = 1e-4
#: Money tolerance: relative 1e-9 with a 1e-6 absolute floor for small books.
MONEY_ABS_TOLERANCE = 1e-6
MONEY_REL_TOLERANCE = 1e-9
#: Optimizer legs are published at 4dp, so a delta closed from them can drift by
#: one 4dp step per operand.
WEIGHT_DELTA_TOLERANCE = 1e-4

PERCENT_TOTAL_TOLERANCE = 0.5

#: Two states whose posterior probabilities are published to 4 decimals and sit
#: within one display step of each other are not distinguishable from the export,
#: so NUM-025 treats them as tied rather than as an argmax with a winner.
POSTERIOR_TIE_TOLERANCE = 1e-4

#: Relative slack on the tail-mean relation.  A tail mean is never allowed to be
#: MILDER than the quantile that selects its tail, but it is not required to be
#: strictly deeper either: on a small empirical sample the tail can be a single
#: observation, and then the two figures coincide exactly.  The check is on
#: magnitude, so it holds under either sign convention.
TAIL_MEAN_REL_TOLERANCE = 1e-9

#: How old a section ``as_of`` may be before ENV-012 calls it STALE.
#:
#: Seven calendar days, and not a smaller number, because the question is not
#: "is this date old" but "could this still be the newest observation behind an
#: export collected today".  One calendar week is the smallest window that
#: reliably contains a full set of NSE sessions, so an ``as_of`` a week or more
#: behind ``generated_at`` means at least one complete trading week closed with
#: nothing delivered, whatever the section's status says.  A tighter threshold
#: (3 days) would be defensible on a book with no weekend or holiday gaps and
#: would be noise on one with them; a looser one (14) would let a two-week-old
#: quote through.  The threshold is a judgement call and it is stated here so
#: that a future disagreement is an edit to this constant, not a re-derivation.
AS_OF_STALENESS_DAYS = 7.0

#: Statuses on the data-existence axis that mean "degraded".  ENV-016 treats
#: these as a self-disclosure the section owes a warning for.
DEGRADED_STATUSES = frozenset({"partial", "unavailable"})

#: Keys whose presence, with a USABLE value, is the payload telling a reader
#: that something was blocked, withheld, refused, suppressed or excluded.  These
#: are what makes a section's own ``status`` irrelevant to ENV-016: a payload
#: that publishes ``block_reasons`` is degraded whether or not the section
#: bothered to say so, and the fix is a warning, never a changed number.
DEGRADATION_MARKER_TOKENS = (
    "block_reason",
    "block_reasons",
    "omitted_field",
    "withheld",
    "refused",
    "refusal",
    "suppressed",
    "excluded",
)

#: Record ``status`` values that assert the record can be acted on.  ENV-019
#: fires when one of these appears inside a section whose own gate says the
#: opposite.
EXECUTABLE_STATUSES = frozenset(
    {"executable", "execute", "ready", "actionable", "tradable", "tradeable"}
)

#: Keys whose presence (with a usable value) is a statement about the PRECISION
#: of an estimate: a standard error, an interval, or an effective-sample-size
#: adjustment that acknowledges serial correlation.  ENV-020 is satisfied by any
#: one of them.
#:
#: A p-value is deliberately NOT in this set.  ``engle_granger_pvalue`` says the
#: cointegration test rejected stationarity of the price pair; it says nothing
#: about the precision of the ``hedge_ratio_beta`` published beside it, and
#: admitting p-values here would let a section pass on a significance flag while
#: every number it publishes stays a naked point estimate.
UNCERTAINTY_KEY_TOKENS = (
    "standard_error",
    "standarderror",
    "stderr",
    # `std_error` is this repo's own convention -- `alpha_std_error`,
    # `market_std_error` on factor_exposure, published when the HAC standard
    # errors were kept instead of discarded. This rule was written before that
    # naming existed, so it could not see a real, correctly-computed, robust
    # standard error because it was looking for a different word. A rule blind to
    # the codebase's own vocabulary is not strict, it is broken.
    "std_error",
    "conf_int",
    "confidence_interval",
    "confidence_band",
    "interval",
    "ci_low",
    "ci_high",
    "effective_n",
    "effective_observation",
    "effective_sample",
    "autocorrel",
    "hac_",
    "newey",
    "bootstrap",
    "degrees_of_freedom",
    "t_critical",
)

#: Classifications under which a published number has NO sampling distribution,
#: so a null beside a stated reason IS the complete and honest disclosure. A rule
#: that demanded a figure in these cases would be demanding a fabricated one: a
#: design constant cannot be resampled, and a deterministic function of an
#: already-published input has no independent uncertainty. These are the labels
#: ``score_audit.precision`` publishes for exactly that distinction.
NON_ESTIMATE_CLASSIFICATIONS = frozenset(
    {
        "declared_constant",
        "deterministic_derivation",
        "derived_value",
        "inherited_precision",
    }
)

#: Key names that match an uncertainty token but are METHOD PARAMETERS rather
#: than statements about precision. ``bootstrap_resamples: 1000`` says how many
#: draws were taken; it says nothing about how tightly anything was estimated.
#: Matched as whole-name fragments so a real figure that merely shares a prefix
#: -- ``hac_se``, ``bootstrap_standard_error`` -- is not swept up with them.
METHOD_PARAMETER_FRAGMENTS = (
    "resample",
    "maxlags",
    "iterations",
    "draws",
    "seed",
    "n_boot",
)

#: Key fragments that make a numeric field an ESTIMATED quantity (a fitted
#: parameter or a ratio) rather than a measured level.  Deliberately excludes
#: z-scores and p-values: a z-score is a measured level put on a scale, and a
#: p-value is a hypothesis verdict, not a parameter.
ESTIMATE_KEY_TOKENS = (
    "alpha",
    "beta",
    "sharpe",
    "sortino",
    "calmar",
    "omega",
    "information_ratio",
    "tracking_error",
    "treynor",
    "r_squared",
    "correlation",
    "var_",
    "cvar_",
    "expected_annual",
    "expected_sharpe",
    "expected_volatility",
)

#: Key fragments that constitute a per-observation BREADTH disclosure: how many
#: constituents were actually in the basket on a given date.  The universe-size
#: family (``*_position_count``, ``*_asset_count``, ``*_holding_count``) is
#: deliberately NOT here, because those name how many legs COULD have been in
#: the basket, which is the number the defect is not about.
BREADTH_KEY_TOKENS = (
    "constituent",
    "breadth",
    "basket",
    "renorm",
    "legs_active",
    "active_leg",
    "active_count",
    "active_position",
    "observed_position",
    "held_count",
)

#: Key fragments that name a two-element INTERVAL.
#:
#: ``conf_int`` is this repo's own naming, and it was MISSING here.  The tuple was
#: written when the only interval in the document was
#: ``forecast_risk.data.portfolio.confidence_interval``; the export has since
#: published 244 keys literally named ``conf_int`` (215 of them inside an
#: ``estimate_uncertainty`` block), and none of the four tokens below is a
#: substring of that word.  NUM-022 was therefore blind to every interval the
#: system actually emits -- a rule written for a key name that no longer exists.
#: A rule blind to the codebase's own vocabulary is not strict, it is broken, and
#: the same hazard has now been measured three times (``data_status`` -> ENV-007,
#: ``interval`` -> ENV-020, ``conf_int`` -> NUM-022).
#:
#: ``bounds`` closes the same gap for the clip bands, by the same measurement
#: rather than by guesswork: the export publishes 14
#: ``annualized_volatility_clip_bounds`` pairs under ``forecast_risk`` and four
#: ``bounds`` pairs under ``stress_testing``, and ``bounds`` was not a substring
#: any token here matched.  Adding it takes NUM-022's reach on two-element
#: positive-ordered numeric pairs from 48 to 66 and produces ZERO new findings on
#: the real export -- every one of the 18 newly visible pairs was measured
#: against the rule's own round-multiple test first.  The substring also matches
#: ``clip_bounds`` (32) and the string-valued ``bound_basis`` / ``at_clip_bound``
#: (45), which the rule's own two-element-numeric gate discards, so the wider
#: name costs nothing.
INTERVAL_KEY_TOKENS = (
    "confidence_interval",
    "interval",
    "_ci",
    "ci_",
    "conf_int",
    "bounds",
)

#: A fabricated band is a round multiple of the estimate.  Multiples are
#: accepted only on a 0.05 grid inside [0.5, 2.0], so a computed interval whose
#: endpoints happen to be 0.643x and 1.357x the centre is not mistaken for one.
ROUND_INTERVAL_STEP = 0.05
MIN_INTERVAL_MULTIPLE = 0.5
MAX_INTERVAL_MULTIPLE = 2.0

#: Key fragments that name a TRADE DIRECTIVE field, and the directional verbs
#: that turn such a field's value into an instruction rather than a label.
DIRECTIVE_KEY_TOKENS = ("signal", "directive", "recommendation", "trade_instruction")
DIRECTIVE_ACTION_RE = re.compile(
    r"\b(LONG|SHORT|SELL|BUY|COVER|EXIT|ENTER|ADD|REDUCE|OVERWEIGHT|UNDERWEIGHT|"
    r"GO_LONG|GO_SHORT|SQUARE)\b",
    re.IGNORECASE,
)

#: The five things a directive has to publish for a reader to be able to check
#: it.  Each is satisfied by a key fragment appearing on the record itself or on
#: any mapping that encloses it, so a scan-level constant does not have to be
#: duplicated onto all 91 records to pass.
DIRECTIVE_BASIS_TOKENS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("decision threshold", ("threshold", "entry_z", "z_entry", "cutoff")),
    ("diagnostic test agreement", ("agrees_with", "agreement", "diagnostic")),
    ("number of comparisons", ("scanned_pairs", "comparisons", "pairs_tested",
                               "tests_run", "n_pairs", "hypotheses", "tests_performed")),
    ("multiplicity correction", ("bonferroni", "fdr", "multiplicity",
                                 "multiple_testing", "false_discovery", "holm",
                                 "benjamini")),
    ("size ratio", ("hedge_ratio", "size_ratio", "hedge_beta", "notional_ratio")),
)

#: Prefixes that mark a number as the thing an ``achieved_*`` field is claiming
#: to have hit.  ``achieved_volatility`` is compared against ``target_volatility``
#: because both name the same quantity and the first is prefixed with the word
#: that claims it was measured.
TARGET_KEY_PREFIXES = ("target_", "input_", "desired_", "requested_", "goal_")

#: Keys a holding-window block may publish its window START under.  ``XS-001``
#: used to read only ``intersection_start``, so a block that named its start any
#: other way dropped out of the comparison set instead of contradicting it.
WINDOW_START_KEYS = ("intersection_start", "delivered_start")
MEASURED_WINDOW_KEY = "measured_window"

#: Counts that mean "how many of the requested X were actually measured".  A
#: null beside a published ratio is ENV-021's defect.
COVERAGE_COUNT_KEYS = (
    "covered_count",
    "available_count",
    "delivered_count",
    "observed_count",
    "measured_count",
)

CATEGORY_ENVELOPE = "envelope"
CATEGORY_CROSS_SECTION = "cross-section"
CATEGORY_NUMERIC = "numeric"
CATEGORY_ORDER = (CATEGORY_ENVELOPE, CATEGORY_CROSS_SECTION, CATEGORY_NUMERIC)

DEFAULT_EXPORT_URL = "http://127.0.0.1:8000/api/v1/ai/context?format=json&detail=summary"
SERVER_HINT = (
    "Start the API yourself, then retry:\n"
    "    cd backend && uv run uvicorn main:app --host 127.0.0.1 --port 8000"
)
#: Exports contain live holdings, quantities, cost basis and P&L.  They are
#: written here and never committed; see the .gitignore entry.
EXPORT_DIR_NAME = ".audit-exports"
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_EXPORT_DIR = REPO_ROOT / EXPORT_DIR_NAME

DIFF_TRUNCATE_CHARS = 160


class VolatilePattern(NamedTuple):
    """One entry of the diff allow-list, with the reason it is excluded.

    Printed by ``diff`` so a quiet re-run is visibly a consequence of these
    patterns rather than of a rule silently dropping the interesting changes.
    """

    label: str
    pattern: re.Pattern[str]
    why: str


def _volatile(label: str, pattern: str, why: str) -> VolatilePattern:
    return VolatilePattern(label, re.compile(pattern), why)


#: Fields a re-run legitimately changes.  Anything NOT here is a real delta and
#: is reported.
VOLATILE_PATTERNS: tuple[VolatilePattern, ...] = (
    _volatile(
        "export_id",
        r"(?:^|\.)export_id$",
        "a fresh identity per collection",
    ),
    _volatile(
        "generated_at",
        r"(?:^|\.)generated_at$",
        "the collection clock, published on the envelope and on each section",
    ),
    _volatile(
        "completed_at",
        r"(?:^|\.)completed_at$",
        "the collection end clock",
    ),
    _volatile(
        "snapshot_consistency",
        r"(?:^|\.)snapshot_consistency$",
        "depends on whether live quote times happened to line up",
    ),
    _volatile(
        "positions[].updated_on",
        r"(?:^|\.)positions\[\d+\]\.updated_on$",
        "per-position live quote refresh time",
    ),
    _volatile(
        "quote refresh keys",
        r"(?:^|\.)(?:quote_updated_at|quote_as_of|quote_refreshed_at|quote_timestamp|fetched_at|price_updated_on)$",
        "upstream quote refresh markers",
    ),
    _volatile(
        "portfolio as_of (quote clock)",
        r"^sections\.portfolio\.as_of$|(?:^|\.)component_as_of\.portfolio\.as_of$",
        "the portfolio as_of is the newest persisted quote timestamp, so it moves on every collection",
    ),
)


# --------------------------------------------------------------------------
# Value objects
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Finding:
    """One rule violation.  Every finding is a hard failure by design."""

    rule_id: str
    section: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class Rule:
    rule_id: str
    category: str
    description: str
    fn: Callable[["Export"], list[Finding]]


@dataclass
class Export:
    """A parsed export plus the raw text the rules need for lexical checks.

    The raw text is kept because three rules (no NaN/Infinity, strict
    re-parseability, duplicate object keys) are properties of the BYTES, not of
    the decoded object graph: ``json.loads`` accepts ``NaN`` and silently keeps
    the last of a set of duplicate keys, so a decoded object cannot tell you
    either happened.
    """

    doc: dict[str, Any]
    raw: str
    path: Path | None = None
    strict_error: str | None = None
    duplicate_keys: tuple[str, ...] = ()

    @cached_property
    def nodes(self) -> list[tuple[str, Any]]:
        """Every value in the tree as ``(path, value)``, document order."""
        return list(_walk(self.doc))

    @cached_property
    def dicts(self) -> list[tuple[str, dict[str, Any]]]:
        """Every mapping in the tree as ``(path, mapping)``, document order."""
        return [(p, v) for p, v in self.nodes if isinstance(v, dict)]

    def keyed(self, key: str) -> list[tuple[str, Any]]:
        """``(path, value)`` for every mapping that actually carries ``key``."""
        return [
            (f"{p}.{key}", v[key])
            for p, v in self.dicts
            if key in v
        ]

    def sections(self) -> dict[str, dict[str, Any]]:
        raw = self.doc.get("sections")
        return raw if isinstance(raw, dict) else {}


def _section_of(path: str) -> str:
    """Which top-level section a deep path belongs to, for reporting."""
    if path.startswith("sections."):
        rest = path[len("sections.") :]
        return rest.split(".", 1)[0].split("[", 1)[0] or "(envelope)"
    return "envelope"


# --------------------------------------------------------------------------
# Small tree / number helpers
# --------------------------------------------------------------------------


def _walk(node: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    yield path, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _finite(value: Any) -> bool:
    return _is_number(value) and math.isfinite(float(value))


def _close(left: float, right: float, *, abs_tol: float, rel_tol: float = 0.0) -> bool:
    return math.isclose(left, right, abs_tol=abs_tol, rel_tol=rel_tol)


def _money_close(left: float, right: float) -> bool:
    return math.isclose(
        left, right, abs_tol=MONEY_ABS_TOLERANCE, rel_tol=MONEY_REL_TOLERANCE
    )


def _fmt(value: Any, *, digits: int = 6) -> str:
    if isinstance(value, float):
        return f"{value:.{digits}g}"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, default=str)
        return text if len(text) <= 120 else text[:117] + "..."
    return repr(value)


def _iso_date(value: Any) -> bool:
    """True only for a real ISO date/timestamp string.

    Provenance blocks publish prose UNDER a key called ``effective_start``
    (e.g. ``portfolio.data.holding_date_provenance``), so a naive key check
    would read a sentence as a window start.
    """
    return isinstance(value, str) and bool(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ].*)?", value.strip())
    )


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    """Naive and aware timestamps must not be compared directly.

    The envelope publishes ``...Z`` timestamps while an observation-only section
    publishes a bare date, so a raw comparison raises TypeError rather than
    answering the question.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _numbers_in(mapping: Any) -> dict[str, float]:
    if not isinstance(mapping, dict):
        return {}
    return {
        key: float(value)
        for key, value in mapping.items()
        if _finite(value)
    }


def _publishes_something(value: Any) -> bool:
    """Is this value an actual disclosure rather than an empty placeholder?

    ``0`` and ``False`` count (they are statements); ``None``, ``""``, ``[]`` and
    ``{}`` do not.  A dict is judged by its values, so
    ``excluded_assets={"volatility": [], "cvar_tail": []}`` is NOT a disclosure:
    it says two exclusions were considered and neither happened.
    """
    if value is None or value is False:
        return False
    if isinstance(value, dict):
        return any(_publishes_something(inner) for inner in value.values())
    if isinstance(value, (list, tuple, set, str)):
        return len(value) > 0
    return True


def _keys_matching(node: dict[str, Any], tokens: tuple[str, ...]) -> set[str]:
    """Keys of ``node`` whose name contains a token AND whose value is a disclosure."""
    return {
        key
        for key, value in node.items()
        if any(token in key.lower() for token in tokens) and _publishes_something(value)
    }


def _is_method_parameter(key: str) -> bool:
    """True when ``key`` names a knob of a method rather than a figure it produced."""
    lowered = key.lower()
    return any(fragment in lowered for fragment in METHOD_PARAMETER_FRAGMENTS)


def _disclosure_figures(node: dict[str, Any]) -> set[str]:
    """Token-matching keys in ``node`` that actually carry a NUMBER.

    ``_keys_matching`` accepts any published value, which made this rule
    satisfiable without a figure. Three shapes did it, all measured against
    ``env_020`` directly:

      ``standard_error: null`` beside ``standard_error_reason: "not computed"``
      -- the reason key contains the token as a substring and publishes a
         string, so *the explanation of why there is no figure* was read as
         *a figure*. This is the worst of the three, because it inverts the
         disclosure: the more honestly a section explains an absent number, the
         more certainly the rule went green.

      ``bootstrap_resamples: 1000`` -- a draw count, which is a method knob.

      ``effective_n_basis: "the Quenouille formula ..."`` -- prose about a
         figure that is published elsewhere, standing in for the figure here.

    An interval counts as a figure, so ``conf_int: [1.7, 2.1]`` still passes.
    """
    figures: set[str] = set()
    for key, value in node.items():
        lowered = key.lower()
        if not any(token in lowered for token in UNCERTAINTY_KEY_TOKENS):
            continue
        if _is_method_parameter(key):
            continue
        if _finite(value):
            figures.add(key)
        elif isinstance(value, (list, tuple)) and len(value) == 2 and all(_finite(v) for v in value):
            figures.add(key)
    return figures


def _declared_absence(node: dict[str, Any]) -> set[str]:
    """Token-matching keys in a node that declares a NON-ESTIMATE class and says why.

    This is the shape that makes a null legitimate rather than hollow: the
    classification says the number has no sampling distribution, and a reason
    says so in words. Requiring all three - class, null, reason - is what
    separates an explained absence from a missing figure.
    """
    classification = None
    for key in ("classification", "precision_class", "value_class"):
        value = node.get(key)
        if isinstance(value, str) and value.strip().lower() in NON_ESTIMATE_CLASSIFICATIONS:
            classification = value
            break
    if classification is None:
        return set()
    absent = {
        key
        for key, value in node.items()
        if any(token in key.lower() for token in UNCERTAINTY_KEY_TOKENS)
        and not _is_method_parameter(key)
        and not _publishes_something(value)
    }
    reasons = {
        key
        for key, value in node.items()
        if isinstance(value, str)
        and value.strip()
        and any(token in key.lower() for token in UNCERTAINTY_KEY_TOKENS)
    }
    return absent | reasons if absent and reasons else set()


def _ancestor_paths(export: Export, path: str) -> list[str]:
    """Mapping paths that strictly enclose ``path``, outermost last."""
    out = [candidate for candidate, _ in export.dicts
           if candidate != path and (path.startswith(f"{candidate}.")
                                     or path.startswith(f"{candidate}["))]
    out.sort(key=len)
    return out


def _truncate(text: str, limit: int | None) -> str:
    if limit is None or len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."


# --------------------------------------------------------------------------
# ENVELOPE / CONTRACT RULES
# --------------------------------------------------------------------------


def env_001_schema_version(export: Export) -> list[Finding]:
    got = export.doc.get("schema_version")
    if got == EXPECTED_SCHEMA_VERSION:
        return []
    return [
        Finding(
            "ENV-001",
            "envelope",
            "schema_version",
            f"schema_version is {got!r}; docs/ai-context.md pins it to "
            f"{EXPECTED_SCHEMA_VERSION!r}",
        )
    ]


def env_002_generation_order(export: Export) -> list[Finding]:
    generated = _parse_ts(export.doc.get("generated_at"))
    completed = _parse_ts(export.doc.get("completed_at"))
    if generated is None or completed is None:
        return [
            Finding(
                "ENV-002",
                "envelope",
                "generated_at/completed_at",
                "both generated_at and completed_at must be parseable timestamps; "
                f"got {export.doc.get('generated_at')!r} and "
                f"{export.doc.get('completed_at')!r}",
            )
        ]
    if generated <= completed:
        return []
    return [
        Finding(
            "ENV-002",
            "envelope",
            "generated_at/completed_at",
            f"generated_at {generated.isoformat()} is AFTER completed_at "
            f"{completed.isoformat()}",
        )
    ]


def env_003_scope_matches_sections(export: Export) -> list[Finding]:
    scope = export.doc.get("scope")
    sections = export.sections()
    if not isinstance(scope, list) or not all(isinstance(s, str) for s in scope):
        return [
            Finding(
                "ENV-003",
                "envelope",
                "scope",
                f"scope must be a list of section keys; got {type(scope).__name__}",
            )
        ]
    findings: list[Finding] = []
    if set(scope) != set(sections):
        only_scope = sorted(set(scope) - set(sections))
        only_sections = sorted(set(sections) - set(scope))
        if only_scope:
            findings.append(
                Finding(
                    "ENV-003",
                    "envelope",
                    "scope",
                    f"scope names sections that are absent: {only_scope}",
                )
            )
        if only_sections:
            findings.append(
                Finding(
                    "ENV-003",
                    "envelope",
                    "sections",
                    f"sections carries keys missing from scope: {only_sections}",
                )
            )
    if scope != list(sections):
        findings.append(
            Finding(
                "ENV-003",
                "envelope",
                "scope",
                "scope order does not match the sections insertion order; the "
                "contract pins sections to scope order",
            )
        )
    return findings


def env_004_section_status_vocabulary(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for name, section in export.sections().items():
        status = section.get("status") if isinstance(section, dict) else None
        if status not in SECTION_STATUS_VOCABULARY:
            findings.append(
                Finding(
                    "ENV-004",
                    name,
                    f"sections.{name}.status",
                    f"status {status!r} is not in {sorted(SECTION_STATUS_VOCABULARY)}",
                )
            )
    return findings


def env_005_no_not_requested(export: Export) -> list[Finding]:
    """``not_requested`` was documented and typed but never emitted.

    An unrequested section is ABSENT.  Publishing the word keeps a consumer
    building a branch that can never fire.
    """
    findings: list[Finding] = []
    for path, node in export.nodes:
        if isinstance(node, dict):
            for key in node:
                if key == "not_requested":
                    findings.append(
                        Finding(
                            "ENV-005",
                            _section_of(path),
                            f"{path}.not_requested",
                            "an 'not_requested' key is published; an unrequested "
                            "section must be absent instead",
                        )
                    )
        elif isinstance(node, str) and "not_requested" in node:
            findings.append(
                Finding(
                    "ENV-005",
                    _section_of(path),
                    path,
                    f"the literal 'not_requested' appears in a published value: "
                    f"{_fmt(node)}",
                )
            )
    return findings


def env_006_no_null_error(export: Export) -> list[Finding]:
    """A successful section OMITS ``error``; a null sentinel is ambiguous.

    ``error: null`` on a healthy section is indistinguishable from a suppressed
    failure, so it is checked at every depth, not just on sections.
    """
    findings: list[Finding] = []
    for path, node in export.nodes:
        if not isinstance(node, dict) or "error" not in node:
            continue
        value = node["error"]
        empty = value is None or value == "" or value == []
        if empty:
            findings.append(
                Finding(
                    "ENV-006",
                    _section_of(path),
                    f"{path}.error",
                    f"error is published as {value!r}; omit the key on success "
                    "and use a non-empty string on failure",
                )
            )
    return findings


def env_007_data_status_vocabulary(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, value in export.keyed("data_status"):
        if value in DATA_STATUS_VOCABULARY:
            continue
        borrowed = (
            " (that is a COVERAGE word, not a data-existence word)"
            if isinstance(value, str) and value in COVERAGE_ONLY_WORDS
            else ""
        )
        findings.append(
            Finding(
                "ENV-007",
                _section_of(path),
                path,
                f"data_status is {value!r}; the normalized vocabulary is "
                f"{sorted(DATA_STATUS_VOCABULARY)}{borrowed}",
            )
        )
    return findings


def _coverage_block(path: str, node: dict[str, Any]) -> bool:
    """Heuristic: is this mapping a coverage block?

    A coverage block carries a ``status`` next to ticker-universe bookkeeping.
    The india composite's ``component_coverage`` entries are NOT one: they use
    ``*_symbols`` keys and publish ``coverage_status`` separately, and their
    ``status`` is on the data-existence axis.  A sibling ``coverage_status`` is
    therefore treated as an explicit disambiguation and disables detection.
    """
    if "status" not in node or "coverage_status" in node:
        return False
    if "coverage_ratio" in node or "covered_tickers" in node or "missing_tickers" in node:
        return True
    return "requested_tickers" in node and "complete" in node


def env_008_coverage_status_vocabulary(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        if _coverage_block(path, node):
            status = node.get("status")
            if status not in COVERAGE_STATUS_VOCABULARY:
                findings.append(
                    Finding(
                        "ENV-008",
                        _section_of(path),
                        f"{path}.status",
                        f"coverage status {status!r} is not in "
                        f"{sorted(COVERAGE_STATUS_VOCABULARY)}",
                    )
                )
        if "coverage_status" in node and isinstance(node["coverage_status"], str):
            status = node["coverage_status"]
            if status not in COVERAGE_STATUS_VOCABULARY:
                findings.append(
                    Finding(
                        "ENV-008",
                        _section_of(path),
                        f"{path}.coverage_status",
                        f"coverage_status {status!r} is not in "
                        f"{sorted(COVERAGE_STATUS_VOCABULARY)}",
                    )
                )
    return findings


def env_009_weight_basis_conditional(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        if "weight_basis" not in node:
            continue
        basis = node["weight_basis"]
        if basis != CANONICAL_WEIGHT_BASIS:
            findings.append(
                Finding(
                    "ENV-009",
                    _section_of(path),
                    f"{path}.weight_basis",
                    f"weight_basis is {basis!r}; the single canonical literal is "
                    f"{CANONICAL_WEIGHT_BASIS!r}",
                )
            )
        missing = node.get("missing_tickers") or []
        if not missing:
            findings.append(
                Finding(
                    "ENV-009",
                    _section_of(path),
                    f"{path}.weight_basis",
                    "weight_basis is published with no missing_tickers; it is "
                    "only meaningful when an active leg was dropped and the "
                    "survivors were renormalized",
                )
            )
    return findings


def env_010_covered_plus_missing_partitions_requested(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        if "requested_tickers" not in node or "covered_tickers" not in node:
            continue
        requested = node.get("requested_tickers")
        covered = node.get("covered_tickers")
        missing = node.get("missing_tickers")
        if not isinstance(requested, list) or not isinstance(covered, list):
            continue
        missing = missing if isinstance(missing, list) else []
        overlap = sorted(set(covered) & set(missing))
        if overlap:
            findings.append(
                Finding(
                    "ENV-010",
                    _section_of(path),
                    f"{path}.covered_tickers",
                    f"tickers are both covered and missing: {overlap}",
                )
            )
        union = list(covered) + list(missing)
        if sorted(union) != sorted(requested):
            findings.append(
                Finding(
                    "ENV-010",
                    _section_of(path),
                    f"{path}.covered_tickers",
                    f"covered U missing ({len(union)} entries) is not "
                    f"requested ({len(requested)}); "
                    f"unmatched={sorted(set(requested) ^ set(union))}",
                )
            )
        for name, values in (("covered_tickers", covered), ("missing_tickers", missing)):
            order = [t for t in requested if t in set(values)]
            if list(values) != order:
                findings.append(
                    Finding(
                        "ENV-010",
                        _section_of(path),
                        f"{path}.{name}",
                        f"{name} does not follow requested_tickers order",
                    )
                )
    return findings


def env_011_available_within_requested(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        requested = node.get("requested_tickers")
        available = node.get("available_tickers")
        if not isinstance(requested, list) or not isinstance(available, list):
            continue
        extras = sorted(set(available) - set(requested))
        if not extras:
            continue
        raw = node.get("raw_available_tickers")
        if not isinstance(raw, list) or not set(extras) <= set(raw):
            findings.append(
                Finding(
                    "ENV-011",
                    _section_of(path),
                    f"{path}.available_tickers",
                    f"available_tickers claims tickers outside the requested "
                    f"universe {extras} and raw_available_tickers does not "
                    f"document them",
                )
            )
    return findings


def env_012_as_of_outside_collection_window(export: Export) -> list[Finding]:
    """A section ``as_of`` is ORDERED against the collection clock.

    The previous version tested MEMBERSHIP in the collector's own clock window
    and did nothing else, so it was blind in both directions that matter: an
    ``as_of`` five months in the future and an ``as_of`` ten years stale both
    sailed through, while the one case it did catch (a date inside the window)
    was the one that already had a legitimate explanation.  Three arms now:

    ``as_of > completed_at``
        An observation cannot be dated after the export that contains it.  Hard
        fail unless the section discloses a quote-refresh clock, which is the
        one honest reading of a future date.
    ``generated_at - as_of`` > :data:`AS_OF_STALENESS_DAYS`
        Stale.  Fails and publishes the age in days, because a reader who does
        not know the age cannot weigh the section.  Disclosed staleness (a
        warning naming it) passes: the fix is a sentence, not a number.
    ``generated_at <= as_of <= completed_at``
        The date is quoting the collector's own clock, so it is a refresh
        timestamp and has to say so.  This arm is unchanged in strength — the
        ``portfolio`` section legitimately discloses one and still passes.
    """
    generated = _parse_ts(export.doc.get("generated_at"))
    completed = _parse_ts(export.doc.get("completed_at"))
    findings: list[Finding] = []
    if generated is None or completed is None:
        return findings
    generated, completed = _as_utc(generated), _as_utc(completed)
    for name, section in export.sections().items():
        as_of = _parse_ts(section.get("as_of")) if isinstance(section, dict) else None
        if as_of is None:
            continue
        as_of = _as_utc(as_of)
        warnings = section.get("warnings") or []
        semantics = str(section.get("as_of_semantics") or "").lower()
        disclosed_refresh = "refresh" in semantics or any(
            "refresh" in str(w).lower() for w in warnings
        )

        if as_of > completed:
            if not disclosed_refresh:
                findings.append(
                    Finding(
                        "ENV-012",
                        name,
                        f"sections.{name}.as_of",
                        f"as_of {as_of.isoformat()} is AFTER completed_at "
                        f"{completed.isoformat()}: an observation cannot be "
                        "dated in the future, and only a disclosed quote-refresh "
                        "clock legitimately sits there",
                    )
                )
            continue

        age_days = (generated - as_of).total_seconds() / 86400.0
        if age_days > AS_OF_STALENESS_DAYS:
            disclosed_stale = "stale" in semantics or any(
                token in str(w).lower() for w in warnings
                for token in ("stale", "outdated", "not current")
            )
            if not disclosed_stale:
                findings.append(
                    Finding(
                        "ENV-012",
                        name,
                        f"sections.{name}.as_of",
                        f"as_of {as_of.isoformat()} is {age_days:.2f} calendar "
                        f"days older than generated_at {generated.isoformat()}; "
                        f"an observation more than {AS_OF_STALENESS_DAYS:g} days "
                        "old cannot be the newest one behind this export, and no "
                        "warning says the section is stale",
                    )
                )
            continue

        if as_of < generated:
            # Older than the collection started but inside the staleness bound:
            # a plausible observation date.  Nothing to say.
            continue

        if not disclosed_refresh:
            findings.append(
                Finding(
                    "ENV-012",
                    name,
                    f"sections.{name}.as_of",
                    f"as_of {as_of.isoformat()} sits inside the collection "
                    f"window {generated.isoformat()}..{completed.isoformat()}; "
                    "either it is a refresh timestamp (disclose it in "
                    "as_of_semantics or a warning) or it is the wrong date",
                )
            )
    return findings


def env_013_no_null_as_of_with_dated_payload(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for name, section in export.sections().items():
        if not isinstance(section, dict) or section.get("as_of") is not None:
            continue
        data = section.get("data")
        if not isinstance(data, dict):
            continue
        observed = [
            f"{path}.{key}={_fmt(value)}"
            for path, node in _walk(data, f"sections.{name}.data")
            if isinstance(node, dict)
            for key, value in node.items()
            if key in DATED_OBSERVATION_KEYS and _iso_date(value)
        ]
        if observed:
            findings.append(
                Finding(
                    "ENV-013",
                    name,
                    f"sections.{name}.as_of",
                    "as_of is null but the payload carries dated observations "
                    f"({'; '.join(observed[:4])})",
                )
            )
    return findings


def env_014_as_of_requires_semantics(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for name, section in export.sections().items():
        if not isinstance(section, dict):
            continue
        as_of = section.get("as_of")
        if as_of is None:
            continue
        semantics = section.get("as_of_semantics")
        if not isinstance(semantics, str) or not semantics.strip():
            findings.append(
                Finding(
                    "ENV-014",
                    name,
                    f"sections.{name}.as_of_semantics",
                    f"as_of {as_of!r} is published with no as_of_semantics label; "
                    "a consumer cannot tell what the date measures",
                )
            )
    return findings


def env_015_monetary_sections_declare_currency(export: Export) -> list[Finding]:
    """Money in the payload with no declared unit is a unit-less number.

    Detection is contract-derived rather than a hand-listed set of field names:
    the docs define currency inference over ``inputs``, then ``data``, then each
    component payload, taking the first non-blank of
    :data:`CURRENCY_SOURCE_KEYS`.  If that scan finds a unit, the section must
    echo it; if it finds nothing, the section is weightless and ``null`` is
    correct.
    """
    findings: list[Finding] = []
    for name, section in export.sections().items():
        if not isinstance(section, dict):
            continue
        sources: list[tuple[str, Any]] = []
        for container_name in ("inputs", "data"):
            container = section.get(container_name)
            if not isinstance(container, dict):
                continue
            for path, node in _walk(container, f"sections.{name}.{container_name}"):
                if not isinstance(node, dict):
                    continue
                for key in CURRENCY_SOURCE_KEYS:
                    value = node.get(key)
                    if isinstance(value, str) and value.strip():
                        sources.append((f"{path}.{key}", value))
        if not sources:
            continue
        declared = section.get("currency")
        if isinstance(declared, str) and declared.strip():
            expected = sources[0][1].strip().upper()
            if declared.strip().upper() != expected:
                findings.append(
                    Finding(
                        "ENV-015",
                        name,
                        f"sections.{name}.currency",
                        f"section.currency is {declared!r} but the payload's own "
                        f"first unit declaration ({sources[0][0]}) is "
                        f"{sources[0][1]!r}",
                    )
                )
            continue
        findings.append(
            Finding(
                "ENV-015",
                name,
                f"sections.{name}.currency",
                f"the payload declares monetary values ({sources[0][0]}="
                f"{sources[0][1]!r}) but section.currency is "
                f"{declared!r}; money without a unit is not usable",
            )
        )
    return findings


def _degradation_markers(section: dict[str, Any], prefix: str) -> list[str]:
    """Where this section's own payload says something was not done."""
    return [
        f"{path}.{key}"
        for path, node in _walk(section, prefix)
        if isinstance(node, dict)
        for key in _keys_matching(node, DEGRADATION_MARKER_TOKENS)
    ]


def env_016_degraded_sections_warn(export: Export) -> list[Finding]:
    """A section that publishes a degradation must name it in ``warnings``.

    The old version read ``status in {partial, unavailable}`` and stopped there,
    which made ``available`` a promise that nothing needed saying.  That is the
    status every P0 in the v5 review carries: ``volatility_sizing`` reads
    ``available`` while its own ``execution`` block publishes
    ``block_reasons: ["financing_required"]`` and a ``block_reason`` ending "is
    not a normal rebalance", and ``risk_studio`` reads ``available`` while
    publishing ``omitted_fields``.

    The obligation is therefore no longer keyed on the section's own status.  It
    fires when EITHER the status is degraded OR the payload publishes a
    degradation marker (:data:`DEGRADATION_MARKER_TOKENS`) with a usable value.
    The exit is a warning that says what was degraded, which is a sentence an
    engineer can write truthfully — no value anywhere has to change, so this
    rule cannot be silenced by fabricating one.
    """
    findings: list[Finding] = []
    for name, section in export.sections().items():
        if not isinstance(section, dict):
            continue
        status = section.get("status")
        markers = _degradation_markers(section, f"sections.{name}")
        degraded_status = status in DEGRADED_STATUSES
        if not (degraded_status or markers):
            continue
        warnings = section.get("warnings")
        if isinstance(warnings, list) and warnings:
            continue
        if degraded_status and markers:
            because = (f"status is {status!r} and the payload withholds "
                       f"{markers[:3]}")
        elif degraded_status:
            because = f"status is {status!r}"
        else:
            because = (f"status is {status!r} but the payload withholds "
                       f"{markers[:3]}")
        findings.append(
            Finding(
                "ENV-016",
                name,
                f"sections.{name}.warnings",
                f"{because} while warnings is {warnings!r}; a section that "
                "publishes a degradation has to name it whatever its own status "
                "says",
            )
        )
    return findings


# --------------------------------------------------------------------------
# ENVELOPE RULES WRITTEN AGAINST THE v5 REVIEW
# --------------------------------------------------------------------------


def env_019_record_status_respects_section_gate(export: Export) -> list[Finding]:
    """Catches AD-5/G3: a record asserting executability inside a gated section.

    ``volatility_sizing`` published 13 of its 14 trades as
    ``status: "executable"`` while the section's own
    ``execution.execution_eligible`` was ``false``, its ``block_reasons`` read
    ``["financing_required"]`` and its ``methodology`` said the target "is not
    executable as a normal rebalance".  A per-record label that overrides a
    section-level gate is the most dangerous kind of contradiction in this
    export, because the gate is a field a consumer has to go looking for and the
    label is on the row an agent acts on.

    Nothing here names ``volatility_sizing`` or a ticker.  The rule is: if a
    section publishes ``execution_eligible: false`` anywhere, no record inside it
    may claim to be executable.  A record that carries its own gate is
    disclosing the conflict rather than asserting against it, so it passes.
    """
    findings: list[Finding] = []
    for name, section in export.sections().items():
        if not isinstance(section, dict):
            continue
        prefix = f"sections.{name}"
        gates = [
            path
            for path, node in _walk(section, prefix)
            if isinstance(node, dict) and node.get("execution_eligible") is False
        ]
        if not gates:
            continue
        offending: dict[str, list[str]] = {}
        mapping_paths = {path for path, _ in export.dicts}
        for path, node in _walk(section, prefix):
            if not isinstance(node, dict):
                continue
            status = node.get("status")
            if not (isinstance(status, str)
                    and status.strip().lower() in EXECUTABLE_STATUSES):
                continue
            if any(key in node for key in ("execution_eligible", "blocked", "blocked_by")):
                continue
            # Group on the nearest enclosing MAPPING, not on a dot split: a
            # record keyed by an NSE scrip ends in '.NS' and a naive rsplit
            # files it under its own ticker.
            container = max(
                (candidate for candidate in mapping_paths
                 if candidate != path
                 and (path.startswith(f"{candidate}.") or path.startswith(f"{candidate}["))),
                key=len,
                default=prefix,
            )
            label = path[len(container) + 1 :]
            offending.setdefault(container, []).append(label)
        for container, labels in sorted(offending.items()):
            findings.append(
                Finding(
                    "ENV-019",
                    name,
                    container,
                    f"{len(labels)} record(s) claim {sorted(set(labels))[0]!r} "
                    f"status inside a section whose own "
                    f"{gates[0]}.execution_eligible is false: {labels[:6]}",
                )
            )
    return findings


def env_020_point_estimates_carry_uncertainty(export: Export) -> list[Finding]:
    """Catches SI-5: a section of naked point estimates.

    The v5 artifact publishes on the order of two thousand estimated parameters
    and ratios — alphas, betas, Sharpe ratios, Sortinos, R-squareds, VaRs,
    CVaRs, correlations — and exactly one interval, which
    :func:`num_022_interval_is_not_a_constant_band` shows to be a constant
    multiple of the estimate.  ``standard_error``, ``conf_int``,
    ``effective_n``, an autocorrelation adjustment and a HAC/Newey-West standard
    error appear zero times in 876 KB.

    The escape is a precision disclosure anywhere in the section's own subtree
    (:data:`UNCERTAINTY_KEY_TOKENS`) — a standard error, an interval, or an
    effective-sample-size figure that acknowledges that 39 autocorrelated daily
    returns are not 39 independent observations.

    A raw observation or window count is deliberately NOT an escape.  The
    artifact publishes those everywhere (``covered_days: 39``,
    ``observations: 174``), and counting the rows is not a statement about how
    precisely anything was estimated; letting a row count pass this rule would
    have made it green on an artifact that discloses no uncertainty at all.

    The escape must be a FIGURE or an EXPLAINED ABSENCE, never a key name. It
    used to be a key name, and three shapes satisfied it while the section
    disclosed nothing - each measured against this rule rather than argued, and
    documented in :func:`_disclosure_figures`:

      ``{"sharpe_ratio": 1.9, "standard_error": null,
        "standard_error_reason": "not applicable: a declared policy constant"}``
      ``{"sharpe_ratio": 1.9, "bootstrap_resamples": 1000}``
      ``{"sharpe_ratio": 1.9, "conf_int": null, "conf_int_reason": "inherited"}``

    The first is the one that matters.  ``standard_error_reason`` contains the
    token as a substring and publishes a string, so the rule read *the
    explanation of why there is no figure* as *a figure*.  That inverts the
    disclosure: the more carefully a section explains an absent number, the more
    certainly this rule went green - and the more a reader should trust a green
    gate that never checked anything.  A rule that cannot tell a stated absence
    from a published number is not lenient, it is blind.

    An explained absence is still accepted, but only in the shape that means it:
    a node declaring a :data:`NON_ESTIMATE_CLASSIFICATIONS` class AND publishing
    a reason.  That is what lets a declared constant or a deterministic
    derivation state ``null`` honestly instead of fabricating an interval - the
    alternative would be to invent precision figures for design choices, which is
    the worse defect.
    """
    findings: list[Finding] = []
    for name, section in export.sections().items():
        if not isinstance(section, dict):
            continue
        prefix = f"sections.{name}"
        estimates: list[str] = []
        uncertainty: set[str] = set()
        for path, node in _walk(section, prefix):
            if not isinstance(node, dict):
                continue
            uncertainty |= _disclosure_figures(node)
            uncertainty |= _declared_absence(node)
            estimates.extend(
                f"{path}.{key}"
                for key, value in node.items()
                if _finite(value) and any(t in key.lower() for t in ESTIMATE_KEY_TOKENS)
            )
        if not estimates or uncertainty:
            continue
        families = sorted({key.rsplit(".", 1)[-1] for key in estimates})
        findings.append(
            Finding(
                "ENV-020",
                name,
                prefix,
                f"{len(estimates)} point estimate(s) {families[:8]} are published "
                f"with no standard error, no interval and no effective-sample-size "
                f"figure anywhere in this section, and no node declaring why a "
                f"figure is absent; a key name, a draw count and a reason string "
                f"are not precision figures",
            )
        )
    return findings


def env_021_zero_ratio_needs_a_count(export: Export) -> list[Finding]:
    """Catches AD-10/G4: a hard zero beside a null count.

    ``india_flows.data.component_coverage.delivery_anomalies`` published
    ``coverage_ratio: 0`` beside ``covered_count: null`` and
    ``covered_symbols: null``.  ``0`` is a measurement — it asserts that zero of
    fourteen scrips had usable delivery history.  ``null`` is an absence — it
    says the count was never taken.  Publishing the first beside the second
    claims a ratio out of a number that does not exist, and a consumer that
    multiplies a ratio by a universe gets ``0`` instead of "unknown".

    Fires only when the ratio and a null count are in the SAME mapping, so a
    block that correctly omits the ratio (the ``institutional_flows`` sibling
    does) is untouched.  The honest fix is ``covered_count: 0``, which is the
    measurement the ratio already asserts.
    """
    findings: list[Finding] = []
    for path, node in export.dicts:
        ratio = node.get("coverage_ratio")
        if not (_finite(ratio) and float(ratio) == 0.0):
            continue
        nulls = [key for key in COVERAGE_COUNT_KEYS if key in node and node[key] is None]
        if not nulls:
            continue
        findings.append(
            Finding(
                "ENV-021",
                _section_of(path),
                f"{path}.coverage_ratio",
                f"coverage_ratio is a hard 0 beside {sorted(nulls)} = null: 0 is "
                "a measurement and null is an absence, so this ratio is asserted "
                "over a count that was never taken",
            )
        )
    return findings


def env_017_strict_finite_json(export: Export) -> list[Finding]:
    """No NaN / Infinity anywhere, and the bytes re-parse strictly.

    ``json.loads`` accepts the bare tokens ``NaN``/``Infinity``/``-Infinity`` by
    default, so a decoded object cannot prove their absence.
    """
    findings: list[Finding] = []
    if export.strict_error is not None:
        findings.append(
            Finding(
                "ENV-017",
                "envelope",
                "<document>",
                f"the export is not strict JSON: {export.strict_error}",
            )
        )
    for path, node in export.nodes:
        if isinstance(node, float) and not math.isfinite(node):
            findings.append(
                Finding(
                    "ENV-017",
                    _section_of(path),
                    path,
                    f"non-finite number {node!r} is published",
                )
            )
    return findings


def env_018_no_duplicate_keys(export: Export) -> list[Finding]:
    if not export.duplicate_keys:
        return []
    return [
        Finding(
            "ENV-018",
            _section_of(path),
            path,
            f"object key {key!r} is defined more than once; the later value "
            "silently wins on parse",
        )
        for path, key in export.duplicate_keys
    ]


# --------------------------------------------------------------------------
# CROSS-SECTION RULES -- the class that hurt most
# --------------------------------------------------------------------------


def _holding_window_blocks(export: Export) -> list[tuple[str, dict[str, Any]]]:
    return [
        (path, node)
        for path, node in export.dicts
        if node.get("covered_days_scope") in HOLDING_WINDOW_SCOPES
    ]


def _holding_window_start(node: dict[str, Any]) -> tuple[Any, str | None]:
    """The window start a holding-window block claims, and the key it used.

    A block that dates its holding window under any name other than
    ``intersection_start`` used to drop out of the cross-section comparison
    altogether, so the contradiction it carried was invisible rather than
    reported.  ``intersection_start``, the block's own ``start``/``end`` pair,
    ``measured_window.start`` and ``delivered_start`` are all consulted, in that
    order of specificity.

    Deliberately does NOT consult a bare ``start`` on a block that is not itself
    a scoped window, and never looks outside the block: ``dashboard``'s
    ``performance_history`` publishes ``history_coverage.delivered_start =
    2026-08-25`` for a 90-day requested dashboard window that it already reports
    as ``partial``/``truncated``/``stale``, and it publishes no
    ``covered_days_scope`` — so it is a different population, not a
    contradiction, and admitting it would be a false positive that only an
    honest fix could not silence.  A block that DID claim a holding-window scope
    and a ``delivered_start`` is compared, because then the two names describe
    the same window.
    """
    for key in WINDOW_START_KEYS:
        if key == "delivered_start":
            break
        if _iso_date(node.get(key)):
            return node[key], key
    if (
        node.get("covered_days_scope") in HOLDING_WINDOW_SCOPES
        and _iso_date(node.get("start"))
        and _iso_date(node.get("end"))
    ):
        return node["start"], "start"
    window = node.get(MEASURED_WINDOW_KEY)
    if isinstance(window, dict) and _iso_date(window.get("start")):
        return window["start"], f"{MEASURED_WINDOW_KEY}.start"
    if _iso_date(node.get("delivered_start")):
        return node["delivered_start"], "delivered_start"
    return None, None


def xs_001_holding_window_agreement(export: Export) -> list[Finding]:
    """Every section publishing the holding window must agree on it.

    ``covered_days_scope`` is the join key: a model window (174 or 251 days)
    and a conditional regime sample (19 days) are legitimately different
    populations, so they are excluded rather than averaged in.

    MY-1, fixed: the start comparison reads whichever key a block used (see
    :func:`_holding_window_start`) instead of only ``intersection_start``.
    """
    blocks = _holding_window_blocks(export)
    findings: list[Finding] = []
    if len(blocks) < 2:
        return findings
    # Only well-formed blocks can be compared; a block that publishes
    # covered_days as null is XS-002's problem, not an agreement failure.
    starts: dict[str, list[str]] = {}
    for path, node in blocks:
        value, key = _holding_window_start(node)
        if value is None:
            continue
        starts.setdefault(str(value), []).append(f"{path} ({key})")
    days = {
        node.get("covered_days")
        for _, node in blocks
        if _is_number(node.get("covered_days"))
    }
    if len(starts) > 1:
        findings.append(
            Finding(
                "XS-001",
                _section_of(blocks[0][0]),
                blocks[0][0],
                f"{len(blocks)} holding-window blocks disagree on their start: "
                + "; ".join(
                    f"{value} declared by {len(holders)} block(s) e.g. {holders[0]}"
                    for value, holders in sorted(starts.items())
                ),
            )
        )
    if len(days) > 1:
        findings.append(
            Finding(
                "XS-001",
                _section_of(blocks[0][0]),
                blocks[0][0],
                f"{len(blocks)} holding-window blocks disagree on covered_days: "
                f"{sorted(days)}",
            )
        )
    return findings


def xs_010_holding_window_start_matches_itself(export: Export) -> list[Finding]:
    """MY-1: a block that publishes its own ``holding_window_start`` must not
    date itself differently.

    ``tear_sheet.data.measured_window`` claims
    ``covered_days_scope: "holding_window_aligned_return_rows"`` with
    ``start: "2026-08-04"`` and ``days: 39``, publishes
    ``holding_window_start: "2026-08-03"`` on the same mapping, and twenty
    sibling holding-window blocks all say ``intersection_start: "2026-08-03"``.
    The block states the contradiction itself and then publishes it anyway.

    A block may hold BOTH dates when they describe different things AND it
    reconciles them. A portfolio return is only measurable once every held leg
    has a price, so the first measurable date is legitimately later than the
    holding window's own start. Publishing the gap and its basis resolves the
    contradiction; publishing both dates silently does not.
    """
    findings: list[Finding] = []
    for path, node in export.dicts:
        declared = node.get("holding_window_start")
        if not _iso_date(declared):
            continue
        value, key = _holding_window_start(node)
        if value is None or value == declared:
            continue
        # Reconciled: the block names the gap and says what produced it.
        gap = node.get("holding_window_to_measured_start_gap_days")
        basis = node.get("measured_start_basis")
        if _is_number(gap) and isinstance(basis, str) and basis.strip():
            continue
        findings.append(
            Finding(
                "XS-010",
                _section_of(path),
                f"{path}.{key}",
                f"{key}={value!r} contradicts the holding_window_start="
                f"{declared!r} published on the same block, which claims "
                f"covered_days_scope={node.get('covered_days_scope')!r}"
                + (
                    "; the block states no "
                    "holding_window_to_measured_start_gap_days and no "
                    "measured_start_basis explaining the difference"
                    if not (isinstance(basis, str) and basis.strip())
                    else ""
                ),
            )
        )
    return findings


def xs_002_covered_days_requires_scope(export: Export) -> list[Finding]:
    """Catches D-01: a bare count is an unlabelled number.

    ``realized_risk`` -- the reference section every other window is defined
    against -- published ``covered_days`` with an empty/absent
    ``covered_days_scope`` while four sibling sections labelled theirs.
    """
    findings: list[Finding] = []
    for path, node in export.dicts:
        if "covered_days" not in node:
            continue
        scope = node.get("covered_days_scope")
        if isinstance(scope, str) and scope.strip():
            continue
        findings.append(
            Finding(
                "XS-002",
                _section_of(path),
                f"{path}.covered_days",
                f"covered_days={node['covered_days']!r} is published with "
                f"covered_days_scope={scope!r}; a count with no unit cannot be "
                "compared with a sibling section's count",
            )
        )
    return findings


def _start_provenance(node: dict[str, Any]) -> tuple[Any, str | None]:
    for key in ("analytics_start_source", "effective_start_source"):
        if key in node:
            return node.get(key), key
    return None, None


def _start_value(node: dict[str, Any]) -> tuple[Any, str | None]:
    for key in ("analytics_start", "effective_start"):
        value = node.get(key)
        if _iso_date(value):
            return value, key
    return None, None


def xs_003_effective_start_provenance(export: Export) -> list[Finding]:
    """Catches a window start nobody can trace.

    Every published ``effective_start`` needs a source label from
    :data:`ANALYTICS_START_SOURCES`, and an inferred start has to publish the
    stored ``added_on`` it displaced.
    """
    findings: list[Finding] = []
    for path, node in export.dicts:
        value, _ = _start_value(node)
        if value is None:
            continue
        source, source_key = _start_provenance(node)
        if source not in ANALYTICS_START_SOURCES:
            findings.append(
                Finding(
                    "XS-003",
                    _section_of(path),
                    f"{path}.{_start_value(node)[1]}",
                    f"effective_start {value!r} has no usable provenance "
                    f"({source_key}={source!r}); expected one of "
                    f"{sorted(ANALYTICS_START_SOURCES)}",
                )
            )
            continue
        if source != "buy_price_inferred":
            continue
        stored = node.get("stored_added_on")
        disclosed = bool(stored) or bool(node.get("inferred_start_tickers")) or bool(
            node.get("provenance_evidence_window")
        )
        if not disclosed:
            findings.append(
                Finding(
                    "XS-003",
                    _section_of(path),
                    f"{path}.stored_added_on",
                    "effective_start is declared buy_price_inferred but the "
                    "stored_added_on it displaced is not published",
                )
            )
    return findings


def xs_004_effective_start_contradiction(export: Export) -> list[Finding]:
    """A start that disagrees with the stored date must declare the inference."""
    findings: list[Finding] = []
    for path, node in export.dicts:
        value, value_key = _start_value(node)
        if value is None:
            continue
        source, _ = _start_provenance(node)
        stored = node.get("stored_added_on")
        if source == "stored_added_on":
            if _iso_date(stored) and stored != value:
                findings.append(
                    Finding(
                        "XS-004",
                        _section_of(path),
                        f"{path}.{value_key}",
                        f"{value_key}={value!r} claims stored_added_on but the "
                        f"stored date is {stored!r}",
                    )
                )
        elif source == "buy_price_inferred":
            if _iso_date(stored) and node.get("buy_price_inferred") in (None, ""):
                findings.append(
                    Finding(
                        "XS-004",
                        _section_of(path),
                        f"{path}.buy_price_inferred",
                        f"{value_key}={value!r} is inferred from a buy price but "
                        "no inferred date is published",
                    )
                )
        elif source is None:
            oldest = node.get("oldest_holding")
            if _iso_date(oldest) and oldest != value and not node.get(
                "inferred_start_tickers"
            ):
                findings.append(
                    Finding(
                        "XS-004",
                        _section_of(path),
                        f"{path}.{value_key}",
                        f"{value_key}={value!r} contradicts oldest_holding="
                        f"{oldest!r} with no buy-price inference declared",
                    )
                )
    return findings


def xs_005_per_ticker_counts_reconcilable(export: Export) -> list[Finding]:
    """Catches D-02: per-ticker counts still in mixed units.

    ``raw_days``/``masked_days``/``return_observations`` are only comparable if
    the block says which frame each is measured over.  A section that does not
    declare ``per_ticker_count_units`` has to be reconcilable on its face, i.e.
    the two counts are drawn from the same rows.
    """
    findings: list[Finding] = []
    for path, node in export.dicts:
        tickers = node.get("tickers")
        if not isinstance(tickers, dict):
            continue
        rows = {
            ticker: row
            for ticker, row in tickers.items()
            if isinstance(row, dict) and "masked_days" in row and "return_observations" in row
        }
        if not rows:
            continue
        if isinstance(node.get("per_ticker_count_units"), dict):
            continue
        for ticker, row in rows.items():
            masked = row.get("masked_days")
            returns = row.get("return_observations")
            raw = row.get("raw_days")
            if not (_finite(masked) and _finite(returns)):
                continue
            if _finite(raw) and float(raw) < float(masked):
                findings.append(
                    Finding(
                        "XS-005",
                        _section_of(path),
                        f"{path}.tickers.{ticker}",
                        f"masked_days={masked!r} exceeds raw_days={raw!r}",
                    )
                )
            low = float(masked) - RETURN_ROW_SLACK
            if not (low <= float(returns) <= float(masked)):
                findings.append(
                    Finding(
                        "XS-005",
                        _section_of(path),
                        f"{path}.tickers.{ticker}",
                        f"masked_days={masked!r} and return_observations="
                        f"{returns!r} are {abs(float(masked) - float(returns)):g} "
                        f"apart, which no single row frame explains (tolerated "
                        f"gap is {RETURN_ROW_SLACK}); declare "
                        "per_ticker_count_units or use one unit",
                    )
                )
    return findings


def xs_006_full_history_declares_window(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        for key, value in node.items():
            if key != "full_history" or not isinstance(value, dict):
                continue
            block = f"{path}.full_history"
            scope = value.get("scope")
            count = value.get("observation_count")
            window = value.get("window")
            if not (isinstance(scope, str) and scope.strip()):
                findings.append(
                    Finding("XS-006", _section_of(path), f"{block}.scope",
                            f"full_history declares no scope (got {scope!r})")
                )
            if not _is_number(count):
                findings.append(
                    Finding("XS-006", _section_of(path), f"{block}.observation_count",
                            f"full_history observation_count is {count!r}")
                )
            if not (
                isinstance(window, dict)
                and _iso_date(window.get("start"))
                and _iso_date(window.get("end"))
            ):
                findings.append(
                    Finding("XS-006", _section_of(path), f"{block}.window",
                            f"full_history window is {window!r}; it needs start and end")
                )
    return findings


def xs_007_conditional_coverage_uses_conditional_sample(export: Export) -> list[Finding]:
    """A conditional statistic's coverage is the CONDITIONAL sample.

    Reporting the holding pool (39 days) or the model window instead makes a
    19-observation conditional number look like a 39-observation one.
    """
    findings: list[Finding] = []
    for path, node in export.dicts:
        if node.get("conditional") is not True:
            continue
        observations = node.get("observations")
        covered = node.get("covered_days")
        scope = node.get("covered_days_scope")
        if _finite(observations) and _finite(covered):
            if not _close(
                float(observations), float(covered), abs_tol=1e-9
            ):
                findings.append(
                    Finding(
                        "XS-007",
                        _section_of(path),
                        f"{path}.covered_days",
                        f"conditional sample is {observations!r} observations but "
                        f"covered_days={covered!r}",
                    )
                )
        elif not _finite(covered):
            findings.append(
                Finding(
                    "XS-007",
                    _section_of(path),
                    f"{path}.covered_days",
                    "a conditional coverage block publishes no covered_days",
                )
            )
        if scope in HOLDING_WINDOW_SCOPES:
            findings.append(
                Finding(
                    "XS-007",
                    _section_of(path),
                    f"{path}.covered_days_scope",
                    f"a conditional block claims the holding-window scope "
                    f"{scope!r}; the holding pool is not the conditional sample",
                )
            )
    return findings


def xs_008_composite_coverage_honesty(export: Export) -> list[Finding]:
    """A composite may not read ``complete`` while a component is unusable.

    The escape hatch is the contract's own: the section must name the
    components its status describes, via a promoted ``source_component``, a
    distinct composite ``coverage_status``, or published ``coverage_notes``.
    """
    findings: list[Finding] = []
    for name, section in export.sections().items():
        if not isinstance(section, dict):
            continue
        data = section.get("data")
        if not isinstance(data, dict):
            continue
        components = data.get("component_status")
        if not isinstance(components, dict):
            continue
        degraded = {
            component: status
            for component, status in components.items()
            if status in {"partial", "unavailable"}
        }
        if not degraded:
            continue
        coverage = section.get("coverage")
        coverage = coverage if isinstance(coverage, dict) else {}
        composite_status = data.get("coverage_status")
        effective = (
            composite_status
            if composite_status in COVERAGE_STATUS_VOCABULARY
            else coverage.get("status")
        )
        if effective != "complete":
            continue
        names_components = bool(coverage.get("source_component")) or bool(
            data.get("coverage_notes")
        ) or bool(data.get("component_coverage"))
        publishes_own = composite_status in COVERAGE_STATUS_VOCABULARY
        if names_components and publishes_own:
            continue
        findings.append(
            Finding(
                "XS-008",
                name,
                f"sections.{name}.coverage.status",
                f"coverage reads 'complete' while components are degraded "
                f"({degraded}) and nothing in the coverage block names which "
                "components the status describes",
            )
        )
    return findings


_FIT_KEYS = ("r_squared", "adjusted_r_squared", "factor_r_squared")
# Where a payload states WHICH calculation produced a fit statistic. Two fits
# that disagree are only a defect when they claim the same basis; two fits over
# genuinely different windows are supposed to disagree, and that difference is
# the disclosure working.
_FIT_BASIS_KEYS = (
    "factor_model",
    "factor_leg",
    "calculation_basis",
    "basis",
)


def _fit_basis(data: dict[str, Any]) -> str | None:
    """A stable identity for the calculation behind a fit, or None if undeclared.

    Compares the declared window, observation count and basis label together, so
    a 174-observation full-history fit and a 39-observation holding-window fit
    get different identities instead of colliding and being reported as a
    contradiction.
    """
    window = data.get("model_window") or data.get("window")
    start = end = None
    if isinstance(window, dict):
        start, end = window.get("start"), window.get("end")
    count = data.get("model_observation_count")
    if not _is_number(count):
        coverage = data.get("history_coverage")
        if isinstance(coverage, dict):
            count = coverage.get("model_observation_count") or coverage.get(
                "covered_days"
            )
    full = data.get("full_history")
    if not _is_number(count) and isinstance(full, dict):
        count = full.get("observation_count")
        if isinstance(full.get("window"), dict):
            start = start or full["window"].get("start")
            end = end or full["window"].get("end")
    if not (_iso_date(start) or _is_number(count)):
        return None
    label = None
    for key in _FIT_BASIS_KEYS:
        block = data.get(key)
        if isinstance(block, str) and block.strip():
            label = block.strip()
            break
        if isinstance(block, dict):
            for field in ("basis", "scope", "status"):
                value = block.get(field)
                if isinstance(value, str) and value.strip():
                    label = value.strip()
                    break
        if label:
            break
    return f"{label or 'undeclared'}|{start}|{end}|{count}"


def _declares_window_and_observations(data: dict[str, Any]) -> bool:
    """Does this mapping state WHICH window a model statistic was fitted over?

    Checked on the mapping that publishes the statistic, not on its section:
    ``risk_score`` is a dashboard COMPONENT, so a section-level look-up would
    never see it and the whole rule would silently pass.
    """
    window = data.get("model_window") or data.get("window")
    has_window = isinstance(window, dict) and _iso_date(window.get("start"))
    count = data.get("model_observation_count")
    if not _is_number(count):
        coverage = data.get("history_coverage")
        if isinstance(coverage, dict):
            count = coverage.get("model_observation_count") or coverage.get(
                "covered_days"
            )
    full = data.get("full_history")
    if not _is_number(count) and isinstance(full, dict):
        count = full.get("observation_count")
    return bool(has_window and _is_number(count))


def xs_009_factor_fit_declares_window(export: Export) -> list[Finding]:
    """Catches D-06: two R-squared for one model, neither window comparable.

    ``factor_exposure`` fitted over 174 model observations and ``risk_score``
    fitted over the 39-day holding window published 0.6511 and 0.2391 with
    nothing to tell a reader they are different models.  Every published fit
    statistic therefore has to declare its window and observation count, and two
    mappings that both declare one must still say how they differ.
    """
    findings: list[Finding] = []
    declared: list[tuple[str, str, float, str | None]] = []
    for path, node in export.dicts:
        fits = {
            key: float(node[key])
            for key in _FIT_KEYS
            if _finite(node.get(key))
        }
        if not fits:
            continue
        owner = _section_of(path)
        if _declares_window_and_observations(node):
            basis = _fit_basis(node)
            declared.extend(
                (owner, f"{path}.{key}", value, basis) for key, value in fits.items()
            )
            continue
        for key, value in fits.items():
            findings.append(
                Finding(
                    "XS-009",
                    owner,
                    f"{path}.{key}",
                    f"{key}={value!r} is published with no model window and no "
                    "observation count, so it cannot be compared with the other "
                    "section's R-squared for the same factor model",
                )
            )
    for index, (owner_a, path_a, value_a, basis_a) in enumerate(declared):
        for _owner_b, path_b, value_b, basis_b in declared[index + 1 :]:
            if path_a == path_b or _close(value_a, value_b, abs_tol=0.01):
                continue
            # Only a contradiction when BOTH claim the same calculation. Two
            # fits over different windows are expected to differ, and flagging
            # that would force a real disclosure to be deleted to silence the
            # check — the opposite of what this rule is for.
            if basis_a is not None and basis_a == basis_b:
                findings.append(
                    Finding(
                        "XS-009",
                        owner_a,
                        path_a,
                        f"this fit reports {_fmt(value_a)} and another reports "
                        f"{_fmt(value_b)} for the same factor model over the "
                        f"same declared basis {basis_a!r}, so at least one is "
                        "wrong",
                    )
                )
    return findings


# --------------------------------------------------------------------------
# NUMERIC RULES
# --------------------------------------------------------------------------


def num_001_portfolio_totals(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for name, section in export.sections().items():
        if not isinstance(section, dict):
            continue
        data = section.get("data")
        if not isinstance(data, dict):
            continue
        positions = data.get("positions")
        if not isinstance(positions, list) or not positions:
            continue
        if "total_value" not in data:
            continue
        market = [
            float(row["market_value"])
            for row in positions
            if isinstance(row, dict) and _finite(row.get("market_value"))
        ]
        total = data.get("total_value")
        if len(market) == len(positions) and _finite(total) and not _money_close(
            sum(market), float(total)
        ):
            findings.append(
                Finding(
                    "NUM-001",
                    name,
                    f"sections.{name}.data.total_value",
                    f"sum(market_value)={_fmt(sum(market))} does not equal "
                    f"total_value={_fmt(total)}",
                )
            )
        weights = [
            float(row["weight"])
            for row in positions
            if isinstance(row, dict) and _finite(row.get("weight"))
        ]
        if len(weights) == len(positions) and not _close(
            sum(weights), 1.0, abs_tol=1e-6
        ):
            findings.append(
                Finding(
                    "NUM-001",
                    name,
                    f"sections.{name}.data.positions[].weight",
                    f"sum(weight)={_fmt(sum(weights))} does not equal 1",
                )
            )
    return findings


def num_002_sector_weight_residual(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        by_sector = node.get("by_sector")
        published = node.get("by_sector_published_total")
        if not isinstance(by_sector, dict) or not _finite(published):
            continue
        values = _numbers_in(by_sector)
        if len(values) != len(by_sector):
            continue
        total = sum(values.values())
        if not _close(total, float(published), abs_tol=1e-9):
            findings.append(
                Finding(
                    "NUM-002",
                    _section_of(path),
                    f"{path}.by_sector_published_total",
                    f"published sector total {_fmt(published)} does not equal the "
                    f"sum of the published sector weights {_fmt(total)}",
                )
            )
        residual = node.get("by_sector_rounding_residual")
        if not _finite(residual):
            findings.append(
                Finding(
                    "NUM-002",
                    _section_of(path),
                    f"{path}.by_sector_rounding_residual",
                    "no rounding residual is published, so the sector weights "
                    "cannot be shown to add up to less than 1.0",
                )
            )
        elif not _close(float(residual), 1.0 - float(published), abs_tol=1e-9):
            findings.append(
                Finding(
                    "NUM-002",
                    _section_of(path),
                    f"{path}.by_sector_rounding_residual",
                    f"residual {_fmt(residual)} does not equal 1 - published "
                    f"total ({_fmt(1.0 - float(published))})",
                )
            )
        decimals = node.get("by_sector_rounding_decimals")
        if _finite(residual) and abs(float(residual)) > 1e-12:
            if not _finite(decimals) or float(decimals) <= 0:
                findings.append(
                    Finding(
                        "NUM-002",
                        _section_of(path),
                        f"{path}.by_sector",
                        f"sector weights are off 1.0 by {_fmt(residual)} with no "
                        "rounding declared; renormalizing to force 1.0 would "
                        "invent precision",
                    )
                )
    return findings


def num_003_risk_contribution_basis(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        basis = node.get("contribution_basis")
        if not isinstance(basis, dict):
            continue
        unit = basis.get("unit")
        if not (isinstance(unit, str) and unit.strip()):
            findings.append(
                Finding(
                    "NUM-003",
                    _section_of(path),
                    f"{path}.contribution_basis.unit",
                    f"risk contributions declare no unit (got {unit!r})",
                )
            )
        per_model = basis.get("per_model")
        positions = node.get("positions")
        if not isinstance(per_model, dict) or not isinstance(positions, dict):
            continue
        for model, record in per_model.items():
            if not isinstance(record, dict):
                continue
            published = record.get("published_total")
            if not _finite(published):
                findings.append(
                    Finding(
                        "NUM-003",
                        _section_of(path),
                        f"{path}.contribution_basis.per_model.{model}",
                        f"no published_total for the {model} model",
                    )
                )
                continue
            if not _close(float(published), 1.0, abs_tol=1e-4):
                findings.append(
                    Finding(
                        "NUM-003",
                        _section_of(path),
                        f"{path}.contribution_basis.per_model.{model}.published_total",
                        f"{model} contributions total {_fmt(published)}, not ~1",
                    )
                )
            residual = record.get("rounding_residual")
            if _finite(residual) and not _close(
                float(residual), 1.0 - float(published), abs_tol=1e-9
            ):
                findings.append(
                    Finding(
                        "NUM-003",
                        _section_of(path),
                        f"{path}.contribution_basis.per_model.{model}.rounding_residual",
                        f"residual {_fmt(residual)} does not equal 1 - "
                        f"published_total ({_fmt(1.0 - float(published))})",
                    )
                )
            legs = positions.get(model)
            if not isinstance(legs, dict):
                continue
            values = _numbers_in(legs)
            if len(values) != len(legs) or not values:
                continue
            if not _close(sum(values.values()), float(published), abs_tol=1e-6):
                findings.append(
                    Finding(
                        "NUM-003",
                        _section_of(path),
                        f"{path}.positions.{model}",
                        f"sum of published {model} shares "
                        f"{_fmt(sum(values.values()))} does not equal the "
                        f"published_total {_fmt(published)}",
                    )
                )
    return findings


def _band_for(score: float, bands: list[dict[str, Any]]) -> str | None:
    for band in bands:
        if not isinstance(band, dict):
            continue
        low = band.get("min_published_score")
        high = band.get("max_published_score")
        if low is not None and score < float(low):
            continue
        if high is not None and score >= float(high):
            continue
        name = band.get("band")
        return name if isinstance(name, str) else None
    return None


def num_004_liquidity_band_matches_score(export: Export) -> list[Finding]:
    """Recompute the band; trust neither the score nor the band.

    A published 8.0 can never carry a ``Medium`` band because the band follows
    the same rounded value.  The band table is the declaration, wherever it
    lives (``scoring.bands`` today, ``score_band_rule`` is the accepted
    alternative name).
    """
    findings: list[Finding] = []
    for path, node in export.dicts:
        scoring = node.get("scoring")
        if not isinstance(scoring, dict):
            continue
        bands = scoring.get("bands")
        if not isinstance(bands, list) or not bands:
            continue
        candidates: list[tuple[str, Any, Any]] = []
        overall_score = node.get("overall_score")
        if _finite(overall_score):
            candidates.append((f"{path}.overall_band", overall_score, node.get("overall_band")))
        by_position = node.get("by_position")
        if isinstance(by_position, dict):
            for ticker, row in by_position.items():
                if isinstance(row, dict) and _finite(row.get("score")):
                    candidates.append(
                        (f"{path}.by_position.{ticker}.category", row.get("score"), row.get("category"))
                    )
        for field, score, category in candidates:
            recomputed = _band_for(float(score), bands)
            if recomputed != category:
                findings.append(
                    Finding(
                        "NUM-004",
                        _section_of(path),
                        field,
                        f"score {_fmt(score)} falls in band {recomputed!r} under the "
                        f"published band table, but the row says {category!r}",
                    )
                )
    return findings


def num_005_unavailable_liquidity_is_null(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        if not isinstance(node.get("scoring"), dict) or "overall_score" not in node:
            continue
        if node.get("data_status") != "unavailable":
            continue
        for key in ("overall_score", "risk_level"):
            if key in node and node[key] is not None:
                findings.append(
                    Finding(
                        "NUM-005",
                        _section_of(path),
                        f"{path}.{key}",
                        f"an unavailable liquidity result publishes {key}="
                        f"{_fmt(node[key])}; a plausible mid value is worse than "
                        "null because it cannot be told from a measurement",
                    )
                )
    return findings


def num_006_non_measured_market_caps_disclosed(export: Export) -> list[Finding]:
    """Catches D-03: a clean score over estimated inputs.

    Per-position ``market_cap_provenance``/``is_estimate`` were correct while the
    section headline aggregated none of them, so 5 of 14 legs were estimated or
    floored and the section still read ``available`` with zero warnings.
    """
    disclosure_keys = (
        "estimated_market_cap_count",
        "non_measured_market_cap_count",
        "unmeasured_market_cap_count",
    )
    findings: list[Finding] = []
    for path, node in export.dicts:
        by_position = node.get("by_position")
        if not isinstance(by_position, dict):
            continue
        rows = [row for row in by_position.values() if isinstance(row, dict)]
        if not any("market_cap_provenance" in row for row in rows):
            continue
        estimated = [
            ticker
            for ticker, row in by_position.items()
            if isinstance(row, dict) and row.get("market_cap_provenance") != "measured"
        ]
        if not estimated:
            continue
        disclosed = next(
            (node[key] for key in disclosure_keys if _is_number(node.get(key))), None
        )
        if disclosed is not None and int(disclosed) == len(estimated):
            continue
        status = node.get("data_status")
        warnings = node.get("warnings")
        warned = isinstance(warnings, list) and bool(warnings)
        if status == "partial" and warned:
            continue
        findings.append(
            Finding(
                "NUM-006",
                _section_of(path),
                f"{path}.data_status",
                f"{len(estimated)} of {len(rows)} market caps are not measured "
                f"({estimated[:5]}) but the section reports data_status="
                f"{status!r} with {len(warnings or [])} warnings and no "
                "section-level count",
            )
        )
    return findings


def _stress_rows(node: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for key in ("scenarios", "results", "stress_scenarios"):
        value = node.get(key)
        if isinstance(value, dict):
            for name, row in value.items():
                if isinstance(row, dict):
                    rows.append((f"{key}.{name}", row))
        elif isinstance(value, list):
            for index, row in enumerate(value):
                if isinstance(row, dict):
                    rows.append((f"{key}[{index}]", row))
    return rows


def num_007_stress_drawdown_identity(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        rows = _stress_rows(node)
        for label, row in rows:
            impact = row.get("portfolio_impact")
            drawdown = row.get("max_drawdown")
            if not (_finite(impact) and _finite(drawdown)):
                continue
            expected = float(impact) * 1.15
            if not _close(
                float(drawdown), expected, abs_tol=ROUNDING_STEP_TOLERANCE
            ):
                findings.append(
                    Finding(
                        "NUM-007",
                        _section_of(path),
                        f"{path}.{label}.max_drawdown",
                        f"max_drawdown {_fmt(drawdown)} is not portfolio_impact x "
                        f"1.15 ({_fmt(expected)})",
                    )
                )
            if not str(row.get("max_drawdown_basis") or "").strip():
                findings.append(
                    Finding(
                        "NUM-007",
                        _section_of(path),
                        f"{path}.{label}.max_drawdown_basis",
                        "a published max_drawdown declares no basis; a reader "
                        "cannot tell a shock proxy from a simulation",
                    )
                )
    return findings


def _sizing_trades(node: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    basis = node.get("sizing_basis")
    prices = basis.get("sizing_price") if isinstance(basis, dict) else None
    trades = node.get("trades")
    reconciliation = node.get("trade_reconciliation")
    return (
        prices if isinstance(prices, dict) else {},
        trades if isinstance(trades, dict) else {},
        reconciliation if isinstance(reconciliation, dict) else {},
    )


def num_008_trade_amount_reconciles(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        prices, trades, _ = _sizing_trades(node)
        if not trades:
            continue
        for ticker, trade in trades.items():
            if not isinstance(trade, dict):
                continue
            shares = trade.get("shares_delta")
            amount = trade.get("amount")
            price = trade.get("sizing_price")
            if price is None:
                price = prices.get(ticker)
            if not (_finite(shares) and _finite(amount) and _finite(price)):
                continue
            residual = trade.get("rounding_residual")
            if not _finite(residual):
                findings.append(
                    Finding(
                        "NUM-008",
                        _section_of(path),
                        f"{path}.trades.{ticker}",
                        "a priced trade publishes no rounding_residual, so "
                        "amount cannot be reconciled to shares x price",
                    )
                )
                continue
            expected = float(shares) * float(price) + float(residual)
            tolerance = trade.get("rounding_tolerance")
            tolerance = float(tolerance) if _finite(tolerance) else MONEY_ABS_TOLERANCE
            if not _money_close(float(amount), expected) and abs(
                float(amount) - expected
            ) > max(tolerance, MONEY_ABS_TOLERANCE):
                findings.append(
                    Finding(
                        "NUM-008",
                        _section_of(path),
                        f"{path}.trades.{ticker}.amount",
                        f"amount {_fmt(amount)} != shares_delta x sizing_price + "
                        f"rounding_residual ({_fmt(expected)}), outside the "
                        f"published tolerance {_fmt(tolerance)}",
                    )
                )
    return findings


def num_009_zero_share_trades_are_labelled(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        _, trades, _ = _sizing_trades(node)
        for ticker, trade in trades.items():
            if not isinstance(trade, dict):
                continue
            shares = trade.get("shares_delta")
            amount = trade.get("amount")
            if not _finite(amount):
                continue
            amount = float(amount)
            zero_shares = shares in (None, 0)
            if zero_shares and abs(amount) > 0:
                status = trade.get("status")
                if status not in EXPLICIT_ZERO_SHARE_STATUSES:
                    findings.append(
                        Finding(
                            "NUM-009",
                            _section_of(path),
                            f"{path}.trades.{ticker}.status",
                            f"a {_fmt(amount)} notional against shares_delta="
                            f"{shares!r} carries status {status!r}; a sub-lot "
                            "trade is a real outcome and must say so",
                        )
                    )
            if not zero_shares and _finite(shares) and abs(amount) <= 0:
                findings.append(
                    Finding(
                        "NUM-009",
                        _section_of(path),
                        f"{path}.trades.{ticker}.amount",
                        f"amount is {amount!r} while shares_delta={shares!r}; a "
                        "fabricated zero notional hides a real share move",
                    )
                )
    return findings


def num_010_reconciliation_maxima_are_maxima(export: Export) -> list[Finding]:
    """Catches the min-in-a-max-name bug.

    A published maximum that is really a minimum (or a maximum over a
    different population than the residual beside it) makes a tolerance check
    look like it passed for the wrong reason.
    """
    findings: list[Finding] = []
    for path, node in export.dicts:
        prices, trades, reconciliation = _sizing_trades(node)
        if not trades or not reconciliation:
            continue
        priced = {
            ticker: trade
            for ticker, trade in trades.items()
            if isinstance(trade, dict)
            and _finite(trade.get("shares_delta"))
            and _finite(prices.get(ticker))
        }
        if not priced:
            continue
        residuals = {
            ticker: abs(float(trade["rounding_residual"]))
            for ticker, trade in priced.items()
            if _finite(trade.get("rounding_residual"))
        }
        tolerances = {
            ticker: float(trade["rounding_tolerance"])
            for ticker, trade in priced.items()
            if _finite(trade.get("rounding_tolerance"))
        }
        checks = (
            ("max_abs_rounding_residual", "max_abs_rounding_residual_ticker", residuals),
            ("max_rounding_tolerance", "max_rounding_tolerance_ticker", tolerances),
        )
        for total_key, ticker_key, population in checks:
            published = reconciliation.get(total_key)
            if not _finite(published) or not population:
                continue
            expected = max(population.values())
            if not _money_close(float(published), expected):
                findings.append(
                    Finding(
                        "NUM-010",
                        _section_of(path),
                        f"{path}.trade_reconciliation.{total_key}",
                        f"published {total_key}={_fmt(published)} is not the max "
                        f"over its own population ({_fmt(expected)})",
                    )
                )
            named = reconciliation.get(ticker_key)
            argmax = max(population, key=lambda t: (population[t], t))
            if isinstance(named, str) and population.get(named) != max(population.values()):
                findings.append(
                    Finding(
                        "NUM-010",
                        _section_of(path),
                        f"{path}.trade_reconciliation.{ticker_key}",
                        f"named max ticker {named!r} holds {population.get(named)!r} "
                        f"but the maximum is {max(population.values())!r} at "
                        f"{argmax!r}",
                    )
                )
        scopes = {
            reconciliation.get(f"{key}_scope")
            for key, _ticker_key, _population in checks
        }
        scopes.discard(None)
        if len(scopes) > 1:
            findings.append(
                Finding(
                    "NUM-010",
                    _section_of(path),
                    f"{path}.trade_reconciliation",
                    f"the residual and the tolerance are summarised over "
                    f"different populations {sorted(scopes)}; a max compared with "
                    "a residual from another set proves nothing",
                )
            )
    return findings


def _is_optimizer_payload(node: dict[str, Any]) -> bool:
    return "weights" in node and isinstance(node.get("weight_normalization"), dict)


def num_011_optimizer_weight_delta_closes(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        if not _is_optimizer_payload(node):
            continue
        trades = node.get("trades_required")
        if not isinstance(trades, dict):
            continue
        for ticker, record in trades.items():
            if not isinstance(record, dict):
                continue
            current = record.get("current_weight")
            recommended = record.get("recommended_weight")
            delta = record.get("weight_delta")
            if not (_finite(current) and _finite(recommended) and _finite(delta)):
                continue
            expected = float(recommended) - float(current)
            if not _close(
                float(delta), expected, abs_tol=WEIGHT_DELTA_TOLERANCE
            ):
                findings.append(
                    Finding(
                        "NUM-011",
                        _section_of(path),
                        f"{path}.trades_required.{ticker}.weight_delta",
                        f"weight_delta={_fmt(delta)} does not close against its "
                        f"own legs ({_fmt(recommended)} - {_fmt(current)} = "
                        f"{_fmt(expected)})",
                    )
                )
    return findings


def num_012_gross_exposure_residual(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        if not _is_optimizer_payload(node):
            continue
        normalization = node.get("weight_normalization") or {}
        gross = normalization.get("gross_exposure")
        measured = normalization.get("submitted_gross_exposure_measured")
        residual = normalization.get("gross_exposure_residual")
        if not (_finite(gross) and _finite(measured)):
            findings.append(
                Finding(
                    "NUM-012",
                    _section_of(path),
                    f"{path}.weight_normalization.gross_exposure",
                    f"gross_exposure={_fmt(gross)} and "
                    f"submitted_gross_exposure_measured={_fmt(measured)} are not "
                    "both published, so the target cannot be audited",
                )
            )
        elif not _finite(residual):
            findings.append(
                Finding(
                    "NUM-012",
                    _section_of(path),
                    f"{path}.weight_normalization.gross_exposure_residual",
                    "no gross-exposure residual is published; the amount the "
                    "normalization absorbs must be visible",
                )
            )
        elif not _close(float(residual), float(measured) - float(gross), abs_tol=1e-9):
            findings.append(
                Finding(
                    "NUM-012",
                    _section_of(path),
                    f"{path}.weight_normalization.gross_exposure_residual",
                    f"residual {_fmt(residual)} does not equal "
                    f"submitted_gross_exposure_measured - gross_exposure "
                    f"({_fmt(float(measured) - float(gross))})",
                )
            )
        financing = normalization.get("financing_required")
        basis = str(normalization.get("financing_required_basis") or "")
        if not isinstance(financing, bool):
            findings.append(
                Finding(
                    "NUM-012",
                    _section_of(path),
                    f"{path}.weight_normalization.financing_required",
                    f"financing_required is published as {financing!r}; it must be "
                    "a boolean, not a number a consumer has to guess at",
                )
            )
        elif financing != bool(float(measured) > 1.0) and _finite(gross):
            findings.append(
                Finding(
                    "NUM-012",
                    _section_of(path),
                    f"{path}.weight_normalization.financing_required",
                    f"financing_required={financing!r} contradicts an unrounded "
                    f"submitted gross exposure of {_fmt(measured)}",
                )
            )
        if _finite(measured) and "unrounded" not in basis and "measured" not in basis:
            findings.append(
                Finding(
                    "NUM-012",
                    _section_of(path),
                    f"{path}.weight_normalization.financing_required_basis",
                    f"financing_required_basis is {basis!r}; the decision must be "
                    "derived from the unrounded figure, not the rounded one",
                )
            )
    return findings


_PERCENTILE_KEY = re.compile(r"^p(\d+(?:\.\d+)?)$")


def _percentile_sort_key(key: str) -> float | None:
    match = _PERCENTILE_KEY.match(key)
    return float(match.group(1)) if match else None


def num_013_monte_carlo_quantiles(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        percentiles = node.get("terminal_percentiles")
        if not isinstance(percentiles, dict) or not percentiles:
            continue
        keyed = [
            (_percentile_sort_key(key), float(value))
            for key, value in percentiles.items()
            if _percentile_sort_key(key) is not None and _finite(value)
        ]
        for (low_p, low_v), (high_p, high_v) in zip(keyed, keyed[1:]):
            if low_v > high_v:
                findings.append(
                    Finding(
                        "NUM-013",
                        _section_of(path),
                        f"{path}.terminal_percentiles",
                        f"p{low_p:g}={_fmt(low_v)} exceeds p{high_p:g}="
                        f"{_fmt(high_v)}; terminal quantiles must be "
                        "non-decreasing across percentiles",
                    )
                )
        fan = node.get("fan")
        if isinstance(fan, list):
            for index, row in enumerate(fan):
                if not isinstance(row, dict):
                    continue
                values = [
                    float(row[key])
                    for key in ("p5", "p25", "p50", "p75", "p95")
                    if _finite(row.get(key))
                ]
                if any(a > b for a, b in zip(values, values[1:])):
                    findings.append(
                        Finding(
                            "NUM-013",
                            _section_of(path),
                            f"{path}.fan[{index}]",
                            f"fan row quantiles are not non-decreasing: "
                            f"{[round(v, 4) for v in values]}",
                        )
                    )
        definition = node.get("success_definition")
        if not (isinstance(definition, str) and definition.strip()):
            findings.append(
                Finding(
                    "NUM-013",
                    _section_of(path),
                    f"{path}.success_definition",
                    f"prob_success is published with success_definition="
                    f"{definition!r}; terminal and path-touch success are very "
                    "different numbers",
                )
            )
    return findings


def num_014_pairs_counting(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        scanned = node.get("scanned_pairs_count")
        if not _finite(scanned):
            continue
        size = node.get("universe_size")
        if _finite(size):
            expected = int(size) * (int(size) - 1) // 2
            if int(scanned) != expected:
                findings.append(
                    Finding(
                        "NUM-014",
                        _section_of(path),
                        f"{path}.scanned_pairs_count",
                        f"n*(n-1)/2 over universe_size={int(size)} is {expected}, "
                        f"not {int(scanned)}",
                    )
                )
        shallow = node.get("shallow_tickers")
        if isinstance(shallow, list) and shallow:
            if node.get("data_status") != "partial":
                findings.append(
                    Finding(
                        "NUM-014",
                        _section_of(path),
                        f"{path}.data_status",
                        f"{len(shallow)} shallow leg(s) {shallow[:4]} but "
                        f"data_status={node.get('data_status')!r}; a weaker scan "
                        "must report partial",
                    )
                )
        agreement = node.get("test_agreement")
        if not isinstance(agreement, dict):
            findings.append(
                Finding(
                    "NUM-014",
                    _section_of(path),
                    f"{path}.test_agreement",
                    "no test_agreement block; the Engle-Granger decision and the "
                    "Johansen diagnostic are never compared",
                )
            )
            continue
        counts = [
            agreement.get("agreement_count"),
            agreement.get("disagreement_count"),
            agreement.get("counted_pairs"),
        ]
        if not all(_is_number(count) for count in counts):
            findings.append(
                Finding(
                    "NUM-014",
                    _section_of(path),
                    f"{path}.test_agreement",
                    f"agreement counts are not published: "
                    f"{ {k: agreement.get(k) for k in ('agreement_count', 'disagreement_count', 'counted_pairs')} }",
                )
            )
        elif int(counts[0]) + int(counts[1]) != int(counts[2]):
            findings.append(
                Finding(
                    "NUM-014",
                    _section_of(path),
                    f"{path}.test_agreement",
                    f"agreement ({counts[0]}) + disagreement ({counts[1]}) != "
                    f"counted_pairs ({counts[2]})",
                )
            )
    return findings


def num_015_regime_percentages(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        probabilities = node.get("regime_probabilities")
        if not isinstance(probabilities, dict) or not probabilities:
            continue
        values = _numbers_in(probabilities)
        if len(values) != len(probabilities) or not values:
            continue
        total = sum(values.values())
        published = node.get("regime_probabilities_total")
        if not _finite(published):
            findings.append(
                Finding(
                    "NUM-015",
                    _section_of(path),
                    f"{path}.regime_probabilities_total",
                    "no published total beside the probabilities",
                )
            )
        elif not _close(total, float(published), abs_tol=1e-6):
            findings.append(
                Finding(
                    "NUM-015",
                    _section_of(path),
                    f"{path}.regime_probabilities_total",
                    f"probabilities sum to {_fmt(total)} but the published total "
                    f"is {_fmt(published)}",
                )
            )
        elif not _close(
            abs(total - 100.0), 0.0, abs_tol=PERCENT_TOTAL_TOLERANCE
        ) and not _finite(node.get("regime_probabilities_rounding_residual")):
            findings.append(
                Finding(
                    "NUM-015",
                    _section_of(path),
                    f"{path}.regime_probabilities_rounding_residual",
                    f"probabilities sum to {_fmt(total)} with no published "
                    "rounding residual",
                )
            )
        matrix = node.get("transition_matrix")
        residuals = node.get("transition_matrix_row_residuals")
        if isinstance(matrix, dict) and matrix:
            if not isinstance(residuals, dict):
                findings.append(
                    Finding(
                        "NUM-015",
                        _section_of(path),
                        f"{path}.transition_matrix_row_residuals",
                        "transition rows are published with no per-row residual",
                    )
                )
            for state, row in matrix.items():
                numbers = _numbers_in(row)
                if len(numbers) != len(row) or not numbers:
                    continue
                row_total = sum(numbers.values())
                if not _close(row_total, 100.0, abs_tol=PERCENT_TOTAL_TOLERANCE):
                    findings.append(
                        Finding(
                            "NUM-015",
                            _section_of(path),
                            f"{path}.transition_matrix.{state}",
                            f"transition row sums to {_fmt(row_total)}, not ~100",
                        )
                    )
        stability = node.get("stability_pct")
        if _finite(stability):
            for key in ("stability_pct_rule", "stability_pct_scope"):
                if not str(node.get(key) or "").strip():
                    findings.append(
                        Finding(
                            "NUM-015",
                            _section_of(path),
                            f"{path}.{key}",
                            f"stability_pct={_fmt(stability)} is published with "
                            f"no {key}; the figure is not reproducible without it",
                        )
                    )
    return findings


def _tail_matrices(node: dict[str, Any]) -> list[tuple[str, list[list[Any]], list[str]]]:
    out: list[tuple[str, list[list[Any]], list[str]]] = []
    block = node.get("tail_dependence_matrix")
    if isinstance(block, dict) and isinstance(block.get("matrix"), list):
        tickers = block.get("tickers")
        out.append(
            (
                "tail_dependence_matrix",
                block["matrix"],
                [str(t) for t in tickers] if isinstance(tickers, list) else [],
            )
        )
    elif isinstance(block, list) and block and isinstance(block[0], list):
        tickers = node.get("tickers")
        out.append(
            (
                "tail_dependence_matrix",
                block,
                [str(t) for t in tickers] if isinstance(tickers, list) else [],
            )
        )
    return out


def num_016_tail_dependence_matrix(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        for label, matrix, tickers in _tail_matrices(node):
            field = f"{path}.{label}"
            size = len(matrix)
            if any(not isinstance(row, list) for row in matrix):
                continue
            if any(len(row) != size for row in matrix):
                findings.append(
                    Finding(
                        "NUM-016",
                        _section_of(path),
                        field,
                        f"matrix is not square: row lengths {[len(row) for row in matrix]}",
                    )
                )
                continue
            if tickers and len(tickers) != size:
                findings.append(
                    Finding(
                        "NUM-016",
                        _section_of(path),
                        f"{field}.tickers",
                        f"{len(tickers)} tickers bound to a {size}x{size} matrix",
                    )
                )
            for i in range(size):
                for j in range(i + 1, size):
                    a, b = matrix[i][j], matrix[j][i]
                    if _finite(a) and _finite(b) and not _close(float(a), float(b), abs_tol=1e-9):
                        findings.append(
                            Finding(
                                "NUM-016",
                                _section_of(path),
                                f"{field}[{i}][{j}]",
                                f"matrix is not symmetric: [{i}][{j}]={_fmt(a)} vs "
                                f"[{j}][{i}]={_fmt(b)}",
                            )
                        )
                        break
            for i in range(size):
                value = matrix[i][i]
                if _finite(value) and not _close(float(value), 1.0, abs_tol=1e-9):
                    findings.append(
                        Finding(
                            "NUM-016",
                            _section_of(path),
                            f"{field}[{i}][{i}]",
                            f"diagonal is {_fmt(value)}, not 1; tail dependence "
                            "with itself is certainty",
                        )
                    )
                    break
    return findings


def num_017_evt_declares_xi(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        if "gpd_shape_xi" not in node:
            continue
        published = node.get("gpd_shape_xi")
        used = node.get("gpd_shape_xi_used")
        basis = str(node.get("gpd_shape_xi_used_basis") or "").strip()
        if not _finite(used) or not basis:
            findings.append(
                Finding(
                    "NUM-017",
                    _section_of(path),
                    f"{path}.gpd_shape_xi_used",
                    f"EVT metrics are published beside gpd_shape_xi="
                    f"{_fmt(published)} without declaring which xi produced them "
                    f"(gpd_shape_xi_used={_fmt(used)}, basis={basis!r})",
                )
            )
            continue
        candidates = {
            _fmt(node.get(key))
            for key in (
                "gpd_shape_xi",
                "gpd_shape_xi_raw",
                "gpd_shape_xi_constrained",
            )
            if _finite(node.get(key))
        }
        if _fmt(used) not in candidates:
            findings.append(
                Finding(
                    "NUM-017",
                    _section_of(path),
                    f"{path}.gpd_shape_xi_used",
                    f"gpd_shape_xi_used={_fmt(used)} matches none of the published "
                    f"xi values {sorted(candidates)}",
                )
            )
    return findings


# Payload keys that prove a sub-score was MEASURED rather than defaulted. Without
# one of these, a sub-score of exactly 0 is indistinguishable from a leg that was
# never computed. Keys are tried on the node that owns the sub-scores.
_SUB_SCORE_EVIDENCE: dict[str, tuple[str, ...]] = {
    "correlation": ("avg_pairwise_correlation", "measured_avg_correlation"),
}


def num_018_no_hard_zero_sub_scores(export: Export) -> list[Finding]:
    """Catches D-04: an unmeasured sub-score indistinguishable from a real zero.

    ``risk_score`` published ``correlation: 0`` with
    ``excluded_components: []`` while Risk Studio independently measured an
    average correlation of 0.14.  A hard zero drags ``overall_score`` downward
    and nothing says why.

    A sub-score of exactly zero is NOT a defect when the payload publishes the
    measurement behind it. A genuinely uncorrelated portfolio also measures 0,
    and that is a real result, not a floored placeholder — flagging it would
    push the next engineer into fabricating an epsilon floor to silence the
    check, which is strictly worse than the ambiguity this rule was written to
    catch.
    """
    findings: list[Finding] = []
    for path, node in export.dicts:
        components = node.get("components")
        excluded = node.get("excluded_components")
        if not isinstance(components, dict) or not isinstance(excluded, list):
            continue

        # A sub-score of exactly 0 is only suspicious when nothing measured it.
        # A genuinely uncorrelated portfolio also measures 0, and reporting that
        # honestly must not be flagged as the same defect as an unmeasured leg
        # being silently floored to 0. A component is therefore treated as
        # MEASURED when the payload publishes the quantity behind it, e.g.
        # `avg_pairwise_correlation` for the correlation sub-score.
        measured_evidence = {
            name: node[key]
            for name in components
            for key in _SUB_SCORE_EVIDENCE.get(name, ())
            if key in node and _is_number(node[key])
        }
        zeros = [
            name
            for name, value in components.items()
            if _is_number(value)
            and float(value) == 0.0
            and name not in measured_evidence
        ]
        if not zeros:
            continue
        undeclared = [name for name in zeros if name not in excluded]
        if undeclared and not excluded:
            findings.append(
                Finding(
                    "NUM-018",
                    _section_of(path),
                    f"{path}.components",
                    f"sub-score(s) {undeclared} are a hard 0 while "
                    "excluded_components is empty; an unmeasured component must "
                    "be null or listed as excluded",
                )
            )
        elif undeclared:
            findings.append(
                Finding(
                    "NUM-018",
                    _section_of(path),
                    f"{path}.components",
                    f"sub-score(s) {undeclared} are a hard 0 but only "
                    f"{excluded} is declared excluded",
                )
            )
    return findings


def _performance_rows(node: dict[str, Any]) -> list[dict[str, Any]] | None:
    rows = node.get("data")
    if not isinstance(rows, list) or not rows:
        return None
    if not all(isinstance(row, dict) for row in rows):
        return None
    if not any("portfolio_value" in row for row in rows):
        return None
    if not any("return" in row or "benchmark_value" in row for row in rows):
        return None
    return rows


def _is_flagged(row: dict[str, Any]) -> bool:
    return any(
        "flag" in key or "warm" in key or "excluded" in key
        for key in row
    )


def num_019_performance_benchmark_series(export: Export) -> list[Finding]:
    """Catches D-05: a benchmark series that is wrong at both ends.

    Row 0 copied the portfolio value into the benchmark slot (so every chart
    starts the two lines on top of each other) and published a return computed
    against a prior value never delivered, while the newest observation had no
    benchmark point at all.
    """
    findings: list[Finding] = []
    for path, node in export.dicts:
        rows = _performance_rows(node)
        if not rows:
            continue
        for index, row in enumerate(rows):
            if index == 0 and "return" in row and row.get("return") is not None:
                if not _is_flagged(row):
                    findings.append(
                        Finding(
                            "NUM-019",
                            _section_of(path),
                            f"{path}.data[0].return",
                            f"the first delivered row publishes return="
                            f"{_fmt(row.get('return'))}, derived from a prior "
                            "value that was never delivered; suppress it or flag "
                            "the warm-up row",
                        )
                    )
            benchmark = row.get("benchmark_value")
            if benchmark is None:
                findings.append(
                    Finding(
                        "NUM-019",
                        _section_of(path),
                        f"{path}.data[{index}].benchmark_value",
                        f"row {index} (date {row.get('date')!r}) has no benchmark "
                        "value; the newest observation is the one a reader cares "
                        "about most",
                    )
                )
                continue
            portfolio = row.get("portfolio_value")
            if _finite(benchmark) and _finite(portfolio) and float(benchmark) == float(
                portfolio
            ) and not _is_flagged(row):
                findings.append(
                    Finding(
                        "NUM-019",
                        _section_of(path),
                        f"{path}.data[{index}].benchmark_value",
                        f"row {index} benchmark_value is bit-identical to its own "
                        f"portfolio_value ({_fmt(portfolio)}) and is not flagged",
                    )
                )
    return findings


def _delivered_series_coverage(node: dict[str, Any]) -> dict[str, Any] | None:
    """The ``history_coverage`` of a DELIVERED series, if this mapping has one.

    Scoped deliberately.  A holding-window block also carries
    ``history_coverage`` with ``truncated: true``, but there "truncated" means
    the window was clipped to the oldest holding, not that the series came back
    short -- flagging those would be 7 false positives on today's export.  A
    delivered-series block counts REQUESTED DAYS and states what it delivered.
    """
    coverage = node.get("history_coverage")
    if not isinstance(coverage, dict) or not _is_number(coverage.get("requested_days")):
        return None
    if not any(
        key in coverage
        for key in ("delivered_start", "expected_observation_count", "observation_count")
    ):
        return None
    return coverage


def num_020_short_window_is_reported_partial(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for path, node in export.dicts:
        coverage = _delivered_series_coverage(node)
        if coverage is None:
            continue
        owner = _section_of(path)
        ratio = coverage.get("coverage_ratio")
        degraded = (_finite(ratio) and float(ratio) < 0.8) or bool(
            coverage.get("truncated")
        ) or bool(coverage.get("stale"))
        if not degraded:
            continue
        status = node.get("status")
        if isinstance(status, str) and status == "available":
            findings.append(
                Finding(
                    "NUM-020",
                    owner,
                    f"{path}.status",
                    f"the series delivers {coverage.get('coverage_ratio')!r} of "
                    f"{coverage.get('requested_days')!r} requested days but status "
                    "is 'available'",
                )
            )
        warnings = node.get("warnings")
        if not (isinstance(warnings, list) and warnings):
            findings.append(
                Finding(
                    "NUM-020",
                    owner,
                    f"{path}.warnings",
                    "a short or stale history window publishes no warning naming "
                    "the delivered range",
                )
            )
        if ".data.components." in path:
            section = export.sections().get(owner) or {}
            if isinstance(section, dict) and section.get("status") == "available":
                findings.append(
                    Finding(
                        "NUM-020",
                        owner,
                        f"sections.{owner}.status",
                        f"the section reads 'available' while its "
                        f"{path.rsplit('.', 1)[-2]} component delivers a "
                        "short/stale window",
                    )
                )
    return findings


# --------------------------------------------------------------------------
# NUMERIC RULES WRITTEN AGAINST THE v5 REVIEW
# --------------------------------------------------------------------------


def num_021_return_series_declares_breadth(export: Export) -> list[Finding]:
    """Catches QM-1: a return series that never says how many legs it held.

    ``analytics_engine.py:74-77`` renormalises the surviving weights on every
    date, so a day where only some tickers have a finite return is a return for
    the PARTIAL basket, scaled to 1.0.  In the v5 export 20 of the 39 holding
    window days are partial, and the final day is one small-cap alone at
    ``1/0.033177 = 30.14x`` its weight — and that observation is the one that
    sets the terminal value, CAGR, Sharpe and Sortino.  All seven occurrences of
    "renormaliz" in the artifact are about risk-score weights, regime rounding
    and ``india_flows``.

    A series therefore has to say, per row or in aggregate, how many
    constituents were active — or state that every observation used the full
    universe (``renorm: "not_applied"``, ``partial_basket_days: 0``).  Either is
    a disclosure, so an engineer who genuinely stops renormalising can pass this
    with one true line.  ``*_position_count``-style universe sizes are NOT
    accepted: "the book has 14 holdings" does not say how many were in the
    basket on 2026-09-25.
    """
    findings: list[Finding] = []
    for path, node in export.dicts:
        rows = _performance_rows(node)
        if not rows:
            continue
        measured = [row for row in rows if _finite(row.get("return"))]
        if not measured:
            continue
        per_row = sum(1 for row in rows if _keys_matching(row, BREADTH_KEY_TOKENS))
        if per_row == len(rows):
            continue
        beside = _keys_matching(node, BREADTH_KEY_TOKENS)
        enclosing = next(
            (node_at for candidate, node_at in reversed(export.dicts)
             if candidate == path.rsplit(".", 1)[0]),
            None,
        )
        if not beside and (enclosing is None
                           or not _keys_matching(enclosing, BREADTH_KEY_TOKENS)):
            findings.append(
                Finding(
                    "NUM-021",
                    _section_of(path),
                    f"{path}.data",
                    f"a {len(rows)}-row ({len(measured)} measured) portfolio return "
                    f"series publishes a constituent count on {per_row} rows and "
                    "no breadth aggregate beside it; there is no way to tell a "
                    "full-basket day from a partial-basket day whose surviving "
                    "weights were renormalised to 1.0",
                )
            )
    return findings


def _round_interval_multiple(ratio: float) -> float | None:
    """``ratio`` as a round band multiplier, or None if it is not one.

    Round means a multiple of :data:`ROUND_INTERVAL_STEP` (0.05) inside
    ``[0.5, 2.0]``, and not 1.0 itself.  A computed interval whose endpoints
    land on 0.643x and 1.357x the centre — which is what most real ones do —
    returns None and is left alone.
    """
    if not (MIN_INTERVAL_MULTIPLE <= ratio <= MAX_INTERVAL_MULTIPLE):
        return None
    steps = ratio / ROUND_INTERVAL_STEP
    nearest = round(steps)
    if nearest < 1 or not _close(steps, float(nearest), abs_tol=0.0, rel_tol=1e-9):
        return None
    multiple = nearest * ROUND_INTERVAL_STEP
    if _close(multiple, 1.0, abs_tol=1e-12):
        return None
    return multiple


def num_022_interval_is_not_a_constant_band(export: Export) -> list[Finding]:
    """Catches SI-3/QM-3: a confidence interval that is a constant multiple.

    ``forecast_risk.data.portfolio.confidence_interval`` is
    ``[midpoint*0.8, midpoint*1.2]`` to exact float equality — not a computed
    interval, a hardcoded +/-20% band wearing the field's name.  It is worse
    than a wrong number because the SAME export has ``stress_testing`` labelling
    its nominal 0.95 ``nominal_label_not_simulated``: the artifact knows the
    honest spelling and uses the dishonest one a section over.

    Symmetry alone is NOT the finding — plenty of legitimate intervals are
    symmetric.  The finding is symmetry whose half-width is a round constant
    fraction of the centre, so a computed interval is never a false positive
    here.
    """
    findings: list[Finding] = []
    for path, node in export.dicts:
        for key, value in node.items():
            if not any(token in key.lower() for token in INTERVAL_KEY_TOKENS):
                continue
            if not (isinstance(value, list) and len(value) == 2):
                continue
            if not all(_finite(endpoint) for endpoint in value):
                continue
            low, high = float(value[0]), float(value[1])
            if not (0.0 < low < high):
                continue
            centre = (low + high) / 2.0
            low_multiple = _round_interval_multiple(low / centre)
            high_multiple = _round_interval_multiple(high / centre)
            if low_multiple is None or high_multiple is None:
                continue
            findings.append(
                Finding(
                    "NUM-022",
                    _section_of(path),
                    f"{path}.{key}",
                    f"{key}=[{_fmt(low)}, {_fmt(high)}] is exactly the centre "
                    f"{_fmt(centre)} multiplied by [{low_multiple:g}, "
                    f"{high_multiple:g}] — a fixed band is not an interval, and "
                    "no sample can produce one to the last bit",
                )
            )
    return findings


def num_023_achieved_value_is_not_its_own_target(export: Export) -> list[Finding]:
    """Catches QM-4: an ``achieved_*`` field that restates its target.

    ``volatility_sizing`` published ``achieved_volatility == target_volatility ==
    0.15`` to 1e-12 beside ``scale_factor: 1.295309``.  The scale is defined as
    ``target / rec_vol`` and the "achieved" value is ``rec_vol * scale``, so the
    identity closes on ``target`` by construction: it is a restatement dressed
    as a measurement, and the review's own retraction of agent 05 recorded that
    the published ``current_volatility`` (0.145465) is not the volatility the
    sizing used (0.1158) either.

    The guard is ``scale_factor``: a scaling step that exists to hit a target
    makes a later equality with that target an identity rather than evidence.
    Without a published scale the equality might be a genuine coincidence of a
    re-measurement, and the rule stays quiet.
    """
    findings: list[Finding] = []
    for path, node in export.dicts:
        scaled = any(
            "scale" in key.lower() and _finite(value)
            for key, value in node.items()
        )
        if not scaled:
            continue
        for key, value in node.items():
            if not (key.startswith("achieved_") and _finite(value)):
                continue
            quantity = key[len("achieved_") :]
            targets = [
                other
                for other, candidate in node.items()
                if other != key
                and quantity in other
                and other.startswith(TARGET_KEY_PREFIXES)
                and _finite(candidate)
            ]
            for target_key in sorted(targets):
                if _close(float(value), float(node[target_key]),
                          abs_tol=1e-12, rel_tol=1e-12):
                    findings.append(
                        Finding(
                            "NUM-023",
                            _section_of(path),
                            f"{path}.{key}",
                            f"{key}={_fmt(value)} equals {target_key}="
                            f"{_fmt(node[target_key])} exactly while a scale "
                            "factor is published; a scaling step defined as "
                            "target/v reproduces its own target, so this is a "
                            "restatement, not an achieved measurement",
                        )
                    )
    return findings


def _directives(export: Export) -> list[tuple[str, str, dict[str, Any]]]:
    """Every ``(path, key, value)`` whose field is a trade DIRECTIVE.

    A directive is a directive-named field whose value names a directional
    action with a word boundary.  ``"NOT_COINTEGRATED"`` and ``"NEUTRAL"`` are
    labels, and prose elsewhere in the artifact that happens to contain the
    substring "buy" is never looked at, because only directive-named keys are
    read.
    """
    out: list[tuple[str, str, dict[str, Any]]] = []
    for path, node in export.dicts:
        for key, value in node.items():
            if not any(token in key.lower() for token in DIRECTIVE_KEY_TOKENS):
                continue
            if not (isinstance(value, str) and DIRECTIVE_ACTION_RE.search(value)):
                continue
            out.append((path, key, node))
    return out


def num_024_trade_directive_publishes_its_basis(export: Export) -> list[Finding]:
    """Catches SI-1/G9: an actionable directive with no published basis.

    ``pairs`` published ``"LONG_SPREAD (Long ELECTCAST.NS, Short MCX.NS)"`` and
    ``"SHORT_SPREAD (Short JUNIORBEES.NS, Long MIDCAPIETF.NS)"`` on pairs where
    ``johansen_agrees_with_decision`` is ``false``, out of 91 Engle-Granger
    tests whose p-values are indistinguishable from Uniform(0,1)
    (D=0.131, p=0.080).  ``bonferroni``/``fdr``/``multiple_testing``/
    ``false_discovery`` appear zero times in 876 KB, so four declared positives
    where 4.55 are expected by chance are published as instructions with no
    correction and no hedge ratio in the string.

    A directive has to publish, on the record or on any mapping enclosing it:
    the decision threshold, the diagnostic test's agreement, how many
    comparisons were made, whether a multiplicity correction was applied, and
    the size ratio.  Scan-level constants count from the enclosing mapping, so
    publishing one honest ``bonferroni_alpha`` beside the record list is enough
    for all of them.
    """
    findings: list[Finding] = []
    for path, key, node in _directives(export):
        scope = [node] + [
            ancestor
            for candidate, ancestor in export.dicts
            if candidate in _ancestor_paths(export, path)
        ]
        visible: set[str] = set()
        for mapping in scope:
            visible |= set(mapping)
        missing = [
            label
            for label, tokens in DIRECTIVE_BASIS_TOKENS
            if not any(any(token in name.lower() for token in tokens) for name in visible)
        ]
        if not missing:
            continue
        findings.append(
            Finding(
                "NUM-024",
                _section_of(path),
                f"{path}.{key}",
                f"{key}={_fmt(node[key])} is an actionable instruction that "
                f"publishes none of: {', '.join(missing)}; a reader cannot "
                "tell whether the decision survived its own correction",
            )
        )
    return findings


def num_025_current_regime_is_its_own_argmax(export: Export) -> list[Finding]:
    """A state LABEL that contradicts the model's own posterior behind it.

    ``regime.data.current_regime`` is a state a consumer acts on -- it is the one
    field in the section that is not a probability, a matrix or a residual -- and
    the posterior published beside it decides which state that is.  The two
    disagreeed by a factor of a million on the export this rule was written
    against (``current_regime: "bull"`` beside ``crisis: 99.9967``), and nothing
    in the document said so, because a label and a distribution are two fields
    the system emitted together and every rule in the table is an identity
    BETWEEN two such fields.

    A label is the argmax of its posterior, with three cases handled explicitly
    rather than by default:

    * **a tie for the maximum** -- the posterior does not single out a state, so
      publishing one as settled is an overclaim.  A finding, not a pass.
    * **an absent, empty or wholly null posterior** -- the label is then
      unverified rather than correct, and "unverified" is the one thing this
      rule must never report as a pass.  Also a finding.
    * **a label that is not a state the posterior names** -- a finding.

    The tie tolerance is one display step of the published posterior
    (percentages at 4 decimals), so two states the export cannot tell apart are
    treated as tied.
    """
    findings: list[Finding] = []
    for path, node in export.dicts:
        label = node.get("current_regime")
        if not (isinstance(label, str) and label.strip()):
            continue
        label = label.strip()
        posterior = node.get("regime_probabilities")
        if not isinstance(posterior, dict) or not posterior:
            findings.append(
                Finding(
                    "NUM-025",
                    _section_of(path),
                    f"{path}.current_regime",
                    f"current_regime={label!r} is published with no "
                    "regime_probabilities beside it, so the label is an "
                    "unverified action input rather than a verified one; an "
                    "unverifiable label is not a passing label",
                )
            )
            continue
        published = {str(state): value for state, value in posterior.items()}
        finite = {
            state: float(value)
            for state, value in published.items()
            if _finite(value)
        }
        if not finite:
            findings.append(
                Finding(
                    "NUM-025",
                    _section_of(path),
                    f"{path}.current_regime",
                    f"current_regime={label!r} is published against a posterior "
                    f"of {len(published)} state(s) and not one finite "
                    "probability, so the state is undetermined, not correct",
                )
            )
            continue
        top = max(finite.values())
        leaders = sorted(
            state for state, value in finite.items()
            if value >= top - POSTERIOR_TIE_TOLERANCE
        )
        if len(leaders) > 1:
            findings.append(
                Finding(
                    "NUM-025",
                    _section_of(path),
                    f"{path}.current_regime",
                    f"current_regime={label!r} but the posterior is tied at the "
                    f"top between {leaders} at {top:g}%; a tied posterior does "
                    "not single out a state, so publishing one as settled is an "
                    "overclaim",
                )
            )
            continue
        if label not in finite:
            findings.append(
                Finding(
                    "NUM-025",
                    _section_of(path),
                    f"{path}.current_regime",
                    f"current_regime={label!r} is not a state the posterior "
                    f"names; it publishes {sorted(finite)}",
                )
            )
            continue
        if finite[label] < top - POSTERIOR_TIE_TOLERANCE:
            ranked = sorted(finite.items(), key=lambda item: -item[1])
            findings.append(
                Finding(
                    "NUM-025",
                    _section_of(path),
                    f"{path}.current_regime",
                    f"current_regime={label!r} carries {finite[label]:g}% while "
                    f"the posterior published beside it puts "
                    f"{ranked[0][0]!r} at {ranked[0][1]:g}%; the state label is "
                    f"wrong by a factor of "
                    f"{ranked[0][1] / finite[label]:.4g} on the model's own "
                    "posterior",
                )
            )
    return findings


# --------------------------------------------------------------------------
# AN ESTIMATE AGAINST THE COMPANION STATISTIC IT SUMMARISES
# --------------------------------------------------------------------------
#: A rule keyed on a key name checks that a field exists.  A rule keyed on a
#: RELATION checks that a field means what its name says.  Everything in the
#: table above is the first kind, which is why a fabricated precision band, a
#: percentile-scale probability and a state label three million percent away
#: from the posterior beside it all passed it: the document was internally
#: consistent and each of those numbers was wrong.
#:
#: The identities below are the ones a consumer acts on, and they are declared as
#: DATA -- a table of (point key, companion keys, relation) -- so a new pair is
#: one line.  The rule fires on the relation, never on the key names alone: a
#: section may publish ``cvar_95`` without a ``var_95`` beside it, or publish a
#: ``var_95`` that is not comparable, and in both cases the pair is simply not
#: testable and the rule says nothing.

#: ``estimate_uncertainty.estimates.<stat>`` wraps its figure in a block whose
#: point value is named ``point``.  Unwrapping it is what lets the tail-mean
#: relation reach 16 nodes instead of the single headline block it would
#: otherwise see, and it is the export's own name for the point estimate rather
#: than a word matched by substring.
ESTIMATE_POINT_KEY = "point"

#: ``herfindahl_index`` is published at 4 decimals and ``effective_positions`` at
#: 2, and the block states in ``effective_positions_note`` that N_eff is computed
#: on the UNROUNDED index -- so the identity can only be checked against the band
#: the published rounding admits, not against a point equality.  Both halves of
#: that band are declared here so the tolerance is inspectable rather than
#: emergent.
HHI_DISPLAY_DECIMALS = 4
EFFECTIVE_POSITIONS_DISPLAY_DECIMALS = 2

#: The optimization moments carry NO declared step.  The block states
#: ``moments_basis.display_rounding.moment_decimals`` (4) and is then printed
#: inconsistently against it -- ``expected_annual_volatility`` 0.14 and
#: ``risk_free_rate`` 0.02 at two decimals -- so the band is derived from the
#: digits each figure was actually written with, by :func:`_display_step`, and
#: the declared precision is used only as a ceiling.  The consequence is
#: measured and is a finding about the exporter rather than about this rule: a
#: reader holding only a 2-decimal volatility cannot pin the rebuilt ratio to
#: better than +/-0.037, so ``optimization`` currently publishes a Sharpe ratio
#: its own numbers can only corroborate to about four percent.

#: The correlation-stability block does NOT round its four figures alike, so
#: there is no one step to declare: measured on the real export it publishes
#: ``current_avg_correlation`` 0.1483, ``historical_threshold_75th`` 0.4129 and
#: ``historical_threshold_10th`` 0.2179 at four decimals but
#: ``historical_threshold_90th`` 0.459 at THREE.  A single 4-decimal step is ten
#: times too fine for that arm, and a current correlation of 0.4585 -- a value
#: the export can express to the digit it published -- would be read as ELEVATED
#: while the block itself called it CRITICAL.  The band is therefore DERIVED per
#: figure by :func:`_display_step`, the fourth time in this file that a declared
#: token or step stopped matching the export's own vocabulary (``data_status``
#: -> ENV-007, ``interval`` -> ENV-020, ``conf_int`` -> NUM-022).  A correlation
#: this far from every threshold is still decided exactly; the band only admits a
#: figure the published digits cannot separate from the threshold, so it costs no
#: discrimination on a correlation that actually moved.
#:
#: ``correlation_service.analyze_correlation_stability`` publishes these arms
#: and sets ``alert_level``/``alert_direction``/``is_regime_break`` from the arm
#: the numbers select.  The arms are reproduced here as data so the relation is
#: inspectable, and they are read back out of the payload's own four figures --
#: the rule does not ask which arm was intended.
CORRELATION_ALERT_ARMS: tuple[tuple[str, float, str, str, bool], ...] = (
    # (threshold key, comparison, level, direction, is_regime_break)
    ("historical_threshold_90th", "ge", "CRITICAL", "upper_tail_critical", True),
    ("historical_threshold_75th", "ge", "ELEVATED", "upper_tail_elevation", False),
    ("historical_threshold_10th", "le", "ELEVATED", "lower_tail_collapse", True),
)

#: The four published percentile thresholds of the same block, for the arm that
#: fires when none of the three tails does.
CORRELATION_ALERT_NEUTRAL = ("NORMAL", "within_band", False)

#: One declared identity: a POINT estimate and the COMPANION it summarises.
#:
#: ``companion_keys`` must all be present on the SAME mapping for the pair to be
#: testable.  ``section_keys`` are dotted paths into the section's ``data`` for
#: the companions a whole scan declares once beside its rows.
@dataclass(frozen=True, slots=True)
class Companion:
    point_key: str
    relation: str
    companion_keys: tuple[str, ...] = ()
    section_keys: tuple[str, ...] = ()
    note: str = ""


#: The companion map.  A new (point, companion) identity is one line here and
#: nothing else: the rule walks this table, the relation decides.
#:
#: Nothing in this table names a section or a ticker.  The reach follows the key
#: names, so a section that starts publishing one of these pairs is covered
#: without an edit here, and a section that stops publishing it drops out
#: silently -- which is the hazard the token sweep in the report exists to
#: measure rather than hide.
COMPANION_MAP: tuple[Companion, ...] = (
    Companion(
        "prob_success",
        "probability_bounded_by_its_own_percentiles",
        ("target_value", "terminal_percentiles", "success_definition",
         "prob_success_units"),
        note="the fraction of paths that end above the target cannot disagree "
             "with the percentile table of those same paths",
    ),
    Companion(
        "initial_value",
        "point_equals_its_own_distribution_origin",
        ("fan",),
        note="every simulated path starts at the same value, so the row at "
             "year 0 is the fan's own origin restated five times",
    ),
    Companion(
        "effective_positions",
        "reciprocal_of_its_own_index",
        ("herfindahl_index",),
        note="N_eff = 1 / HHI, checked against the band the published rounding "
             "of both operands admits",
    ),
    Companion(
        "cvar_95",
        "tail_mean_not_milder_than_its_quantile",
        ("var_95",),
        note="the tail mean is the mean of the tail the quantile selects",
    ),
    Companion(
        "portfolio_cvar_95_daily",
        "tail_mean_not_milder_than_its_quantile",
        ("portfolio_var_95_daily",),
        note="the same identity on the section that publishes it under its own "
             "vocabulary",
    ),
    Companion(
        "expected_sharpe",
        "ratio_of_its_own_operands",
        ("expected_annual_return", "expected_annual_volatility",
         "risk_free_rate"),
        note="(return - risk_free_rate) / volatility, rebuilt from the operands "
             "the block publishes beside it",
    ),
    Companion(
        "is_cointegrated",
        "verdict_under_its_own_declared_threshold",
        (),
        ("test_agreement.decision_test",
         "signal_policy.p_value_threshold_comparison"),
        note="the boolean the scan declares as its decision, against the "
             "p-value and the threshold the same scan publishes. The p-value "
             "key and the threshold key are DERIVED from the declared "
             "decision-test name, so renaming the test cannot silently drop "
             "the check the way a hardcoded key would.",
    ),
    Companion(
        "alert_level",
        "alert_arm_selected_by_its_own_correlation",
        ("current_avg_correlation", "historical_threshold_10th",
         "historical_threshold_75th", "historical_threshold_90th",
         "alert_direction", "is_regime_break"),
        note="the severity, the direction and the break flag are three fields "
             "for one comparison; the numbers beside them decide which",
    ),
)


def _point_estimate(value: Any) -> Any:
    """The point figure of a published value, unwrapping an estimate block.

    ``estimate_uncertainty.estimates.<stat>`` publishes
    ``{"point": ..., "standard_error": ..., "conf_int": [...]}``.  A bare figure
    is returned unchanged, so a relation written against a number accepts either
    spelling.
    """
    if isinstance(value, dict):
        return value.get(ESTIMATE_POINT_KEY)
    return value


def _dig(node: Any, dotted: str) -> Any:
    """A dotted path into a mapping, or None if any step is missing."""
    cursor: Any = node
    for part in dotted.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return None
        cursor = cursor[part]
    return cursor


def _ok(*values: Any) -> bool:
    return all(_finite(_point_estimate(value)) for value in values)


def _declared_digits(value: Any) -> int:
    """Decimal places the export WROTE for this figure, recovered from the float.

    Python prints a float as the shortest string that reads back as the same
    float, so for a value decoded from ``0.459`` that string carries no more
    decimal places than the export wrote -- which makes the count an upper bound
    on the published precision, and therefore a safe one to reason from.
    """
    text = repr(abs(float(_point_estimate(value))))
    if "." not in text or "e" in text or "E" in text:
        return 0
    return len(text.partition(".")[2])


def _display_step(value: Any, *, declared_decimals: int | None = None) -> float:
    """Half the last decimal place the export actually WROTE for this figure.

    A relation that compares two published numbers has to allow for their
    rounding, and the export does not round them alike.  Measured on the real
    export, ``risk_studio`` publishes ``historical_threshold_90th`` 0.459 at three
    decimals beside ``historical_threshold_75th`` 0.4129 at four, ``pairs``
    publishes its p-values to six, and ``optimization`` publishes
    ``expected_annual_volatility`` 0.14 at two beside a
    ``display_rounding.moment_decimals`` of four.  One declared step for a whole
    block is therefore wrong on part of that block, and where it is too tight the
    rule fires on a figure that is correct to the digit the export published.

    So the step is derived from the figure itself, which -- see
    :func:`_declared_digits` -- is never FINER than the published rounding, the
    only direction in which a rounding band cannot manufacture a false positive.

    ``declared_decimals`` is an optional ceiling, for a block that states the
    precision it means to publish.  The narrower of the two is taken, because a
    block claiming four decimals while writing ``0.14`` is claiming a precision
    its own reader does not get.
    """
    places = _declared_digits(value)
    if isinstance(declared_decimals, int) and declared_decimals >= 0:
        places = min(places, declared_decimals)
    return 0.5 * 10.0 ** -places


def _rel_probability_bounded_by_its_own_percentiles(
    node: dict[str, Any],
    point_key: str,
    companions: tuple[tuple[str, Any], ...],
    section: dict[str, Any] | None,
) -> tuple[bool, str | None]:
    """``prob_success`` inside the bracket the published percentile table implies.

    Let ``T`` be a path's terminal value, ``t`` the published target, and
    ``p_c`` the published ``c``-th percentile of the ``N`` paths.  The defining
    property of a quantile is the pair ``P(T < p_c) <= c/100 <= P(T <= p_c)``,
    and the whole relation is the two inclusions that follow from it.  Both are
    written out rather than summarised, because this derivation has been got
    wrong twice and a reader has to be able to check it rather than trust it.

    * ``p_a >= t``.  At least ``a`` percent of the mass is at or BELOW ``p_a``,
      so the mass at or above it -- ``100 - a`` percent -- is at or above
      ``p_a`` and therefore at or above ``t``.  That gives the FLOOR
      ``P(T >= t) >= 1 - a/100``.  Every clearing level yields such a floor and
      the SMALLEST clearing level yields the TIGHTEST one, so the floor is
      ``1 - min(at_or_above)/100``.  The direction is the whole content of the
      clause: the share that clears the target is the share ABOVE the clearing
      percentile, so the level enters complemented.  A target below ``p_a``
      says nothing about the share above ``t`` except that it is at least the
      share above ``p_a``.
    * ``p_c < t``.  Symmetrically, at least ``c`` percent of the mass is at or
      below ``p_c`` and all of it falls short of ``t``, so at most ``100 - c``
      percent of the mass clears it: ``P(T >= t) <= 1 - c/100``.  The SMALLEST
      falling-short level gives the WEAKEST ceiling, which is the one taken
      here.  The strongest available ceiling is ``1 - max(below)/100``, and the
      block's own ``terminal_percentiles_basis_detail`` publishes the weaker
      bracket, so the rule checks the bracket the export declares for itself
      rather than a tighter one it never claimed.

    So the bracket is ``[1 - min(at_or_above)/100, 1 - min(below)/100]``, and on
    this export's table -- target 85249.0, p5 79001.08 below it, p25 117447.13
    above it -- that is ``[0.75, 0.95]``, which the published 0.922 sits inside.

    The floor has been wrong twice, in mirror images, and both errors were
    invisible because each coincided with the ceiling on a symmetric table.
    ``1 - max(at_or_above)/100`` is the share ABOVE the LARGEST clearing level
    -- a valid bound, but the weakest one available, so it reported
    ``[0.05, 0.95]`` here and accepted a ``prob_success`` of 0.42 that the
    distribution beside it contradicts.  ``max(at_or_above)/100`` is that
    quantity's own mirror image -- the level read as the share -- and reported
    ``[0.95, 0.95]``, rejecting the correct 0.922.  Only ``min`` inside the
    complement is both a lower bound and the strongest one available, which is
    what makes it the only one of the three that is worth publishing.

    One path of the mass is the width of the band, and nothing else is.  The
    levels are numpy percentiles under linear interpolation -- the block says so
    in ``terminal_percentiles_basis_detail`` -- so each sits BETWEEN the two
    order statistics it blends, and that is how far the bound can move.  With
    ``h = a/100 * (N - 1)``, ``p_a`` is a blend of the ``floor(h)``-th and
    ``(floor(h) + 1)``-th order statistics of the sorted sample, so the mass
    strictly below it is at most ``(floor(h) + 1)/N`` -- within ``1/N`` of
    ``a/100`` -- and the mass at or below it is at least ``(floor(h) + 1)/N``,
    again within ``1/N``.  Repeated values do not break this: a blend of two
    equal order statistics IS that shared value, whose mass below is smaller
    still, and a blend of two distinct ones has no sample point strictly
    between them, so its mass below is exactly the earlier count.  Each edge is
    therefore widened OUTWARD by ``1/num_paths``, and by nothing else: at this
    export's 2000 paths that is 0.0005 against a bracket 0.20 wide, one
    four-hundredth of it.  It is derived from the interpolation rather than
    fitted to a case, and it was checked rather than assumed -- over 30,991
    (sample, target) pairs drawn from continuous, integer-tied, two-tone-gap
    and half-tied samples, 1056 pairs sat outside the exact bracket, every one
    of them inside one path of it and none outside.  A block that published the
    table without a path count is checked with no width at all, which is the
    stricter reading of the same derivation.

    The block states in ``success_definition_detail`` that ``prob_success``
    counts the very paths whose terminal percentiles are published beside it,
    so the two are one sample and the bracket binds rather than merely
    describing.
    """
    if not _ok(node.get(point_key)):
        return False, None
    target_key, target_value = companions[0]
    percentiles = companions[1][1]
    target = _point_estimate(target_value)
    if not _finite(target) or not isinstance(percentiles, dict) or not percentiles:
        return False, None
    levels = {key: _percentile_sort_key(str(key)) for key in percentiles}
    below = [
        level for key, level in levels.items()
        if level is not None
        and _finite(percentiles[key])
        and float(percentiles[key]) < float(target)
    ]
    at_or_above = [
        level for key, level in levels.items()
        if level is not None
        and _finite(percentiles[key])
        and float(percentiles[key]) >= float(target)
    ]
    if not below and not at_or_above:
        return False, None
    # See the docstring: the share that clears the target is the share AT OR
    # ABOVE the clearing percentile, so the floor is the level COMPLEMENTED,
    # and the tightest one is the SMALLEST clearing level.
    clearing = min(at_or_above) if at_or_above else None
    short = min(below) if below else None
    low = 1.0 - clearing / 100.0 if clearing is not None else 0.0
    high = 1.0 - short / 100.0 if short is not None else 1.0
    paths = node.get("num_paths")
    tolerance = (
        1.0 / float(paths)
        if _is_number(paths) and float(paths) > 0
        else 0.0
    )
    value = float(_point_estimate(node[point_key]))
    if low - tolerance <= value <= high + tolerance:
        return True, None
    floor = (
        f"the published p{clearing:g} is at or above "
        f"{target_key}={_fmt(target)}, so at least {low * 100:g}% of the paths "
        f"clear it"
        if clearing is not None else
        f"no published percentile is at or above {target_key}={_fmt(target)}, "
        f"so the table puts no floor under {point_key}"
    )
    ceiling = (
        f"the published p{short:g} is below {target_key}={_fmt(target)}, "
        f"so at most {high * 100:g}% of the paths clear it"
        if short is not None else
        f"no published percentile is below {target_key}={_fmt(target)}, so the "
        f"table puts no ceiling on {point_key}"
    )
    return True, (
        f"{point_key}={_fmt(value)} lies outside [{low:g}, {high:g}], the "
        f"bracket the published percentile table requires: {floor}, and "
        f"{ceiling}, so the fraction of paths that clear the target cannot be a "
        "number the distribution behind it contradicts"
    )


def _rel_point_equals_its_own_distribution_origin(
    node: dict[str, Any],
    point_key: str,
    companions: tuple[tuple[str, Any], ...],
    section: dict[str, Any] | None,
) -> tuple[bool, str | None]:
    """``initial_value`` is the value every simulated path starts from.

    A Monte Carlo fan is a set of simulated paths, and all of them start at the
    same value, so the fan's row at the earliest year is that value repeated
    across its percentile columns.  A headline that says otherwise is a
    simulation of a book the caller did not ask about.
    """
    point = node.get(point_key)
    fan = companions[0][1]
    if not _finite(point) or not isinstance(fan, list) or not fan:
        return False, None
    rows = [row for row in fan
            if isinstance(row, dict) and _finite(row.get("year"))]
    if not rows:
        return False, None
    origin = min(rows, key=lambda row: float(row["year"]))
    columns = {
        key: value for key, value in origin.items()
        if key != "year" and _percentile_sort_key(str(key)) is not None
    }
    if not columns:
        return False, None
    drifted = sorted(
        key for key, value in columns.items()
        if not _money_close(float(value), float(point))
    )
    return True, None if not drifted else (
        f"{point_key}={_fmt(point)} but the fan's own row at year "
        f"{_fmt(origin['year'])} reads "
        + ", ".join(f"{key}={_fmt(columns[key])}" for key in drifted)
        + f"; every simulated path starts at {point_key}, so the origin row is "
        f"the fan's starting value repeated across {len(columns)} columns"
    )


def _rel_reciprocal_of_its_own_index(
    node: dict[str, Any],
    point_key: str,
    companions: tuple[tuple[str, Any], ...],
    section: dict[str, Any] | None,
) -> tuple[bool, str | None]:
    """``effective_positions`` is the reciprocal of the index beside it.

    ``N_eff = 1 / HHI``, which is the identity the project's own CONTEXT states
    and which the block's ``effective_positions_note`` explains it cannot be
    checked at point equality through -- the note is right, and the reason is
    the published rounding of both operands, so the check is made against the
    band that rounding admits and not against a figure the export never claimed.
    """
    index_key, index = companions[0]
    if not _ok(node.get(point_key), index):
        return False, None
    hhi = float(_point_estimate(index))
    if not (0.0 < hhi < 1.0):
        return False, None
    step = 0.5 * 10.0 ** (-HHI_DISPLAY_DECIMALS)
    point_step = 0.5 * 10.0 ** (-EFFECTIVE_POSITIONS_DISPLAY_DECIMALS)
    low = 1.0 / (hhi + step) - point_step
    high = 1.0 / (hhi - step) + point_step
    value = float(_point_estimate(node[point_key]))
    inside = low <= value <= high
    return True, None if inside else (
        f"{point_key}={_fmt(value)} but 1/{index_key}={1.0 / hhi:.6g} at the "
        f"published {index_key}={_fmt(hhi)}; outside the band "
        f"[{low:.6g}, {high:.6g}] that {HHI_DISPLAY_DECIMALS}-decimal "
        f"{index_key} and {EFFECTIVE_POSITIONS_DISPLAY_DECIMALS}-decimal "
        f"{point_key} rounding admit, and N_eff is defined as 1/HHI"
    )


def _rel_tail_mean_not_milder_than_its_quantile(
    node: dict[str, Any],
    point_key: str,
    companions: tuple[tuple[str, Any], ...],
    section: dict[str, Any] | None,
) -> tuple[bool, str | None]:
    """A conditional tail mean can never be milder than the quantile selecting it.

    CVaR/ES is the MEAN of the tail the VaR quantile cuts off, so it lies at
    least as deep as that quantile.  The comparison is on magnitude, which makes
    it sign-convention agnostic: it holds whether the block publishes losses as
    negative returns or as positive loss fractions, and it is deliberately NOT
    strict, because on a small empirical sample the tail can be a single
    observation and the two figures then coincide exactly.
    """
    var_key, var = companions[0]
    if not _ok(node.get(point_key), var):
        return False, None
    tail = abs(float(_point_estimate(node[point_key])))
    quantile = abs(float(_point_estimate(var)))
    if tail >= quantile - quantile * TAIL_MEAN_REL_TOLERANCE:
        return True, None
    return True, (
        f"{point_key}={_fmt(node[point_key])} is {_fmt(tail)} in magnitude while "
        f"{var_key} beside it is {_fmt(quantile)}; {point_key} is the MEAN of "
        f"the tail {var_key} selects, so it cannot be the milder of the two"
    )


def _rel_ratio_of_its_own_operands(
    node: dict[str, Any],
    point_key: str,
    companions: tuple[tuple[str, Any], ...],
    section: dict[str, Any] | None,
) -> tuple[bool, str | None]:
    """A ratio rebuilt from the operands published beside it.

    ``expected_sharpe == (expected_annual_return - risk_free_rate) /
    expected_annual_volatility`` -- the identity ``moments_basis.formulas``
    publishes as prose in the same block.  The tolerance is the rounding of THIS
    node's own published digits, propagated through the division, and not a
    constant: a book whose volatility is an order of magnitude smaller gets an
    order of magnitude wider tolerance, without anyone writing that down per node.

    The digits are what the reader gets, and this block does not print them
    alike.  It publishes ``expected_annual_return`` 0.1614 and
    ``expected_sharpe`` 1.0102 at four decimals -- and ``moments_basis.
    display_rounding.moment_decimals`` claims four -- but
    ``expected_annual_volatility`` 0.14 and ``risk_free_rate`` 0.02 at TWO.  A
    volatility carried to two decimals moves the rebuilt ratio by 0.037, so a
    band declared at the claimed 4-decimal step (0.0015) would fire on a
    re-export that printed nothing false.  The band is therefore derived from the
    figures themselves, and the block's declared precision is used only as a
    ceiling -- a block claiming more digits than it writes does not get a
    tighter band than it wrote.
    """
    if not _ok(*(value for _key, value in companions)):
        return False, None
    return_key, return_value = companions[0]
    vol_key, vol_value = companions[1]
    free_key, free_value = companions[2]
    volatility = float(_point_estimate(vol_value))
    if volatility == 0.0:
        return False, None
    declared = _dig(section, "moments_basis.display_rounding.moment_decimals")
    declared_decimals = int(declared) if _finite(declared) else None
    excess = float(_point_estimate(return_value)) - float(_point_estimate(free_value))
    rebuilt = excess / volatility
    # d(r - f) / v  +  (r - f) * d(v) / v^2, then the ratio's own display step.
    tolerance = (
        (_display_step(return_value, declared_decimals=declared_decimals)
         + _display_step(free_value, declared_decimals=declared_decimals))
        / abs(volatility)
        + abs(excess) / (volatility * volatility)
        * _display_step(vol_value, declared_decimals=declared_decimals)
        + _display_step(node[point_key], declared_decimals=declared_decimals)
    )
    published = float(_point_estimate(node[point_key]))
    if abs(rebuilt - published) <= tolerance:
        return True, None
    return True, (
        f"{point_key}={_fmt(published)} but ({return_key}-"
        f"{free_key})/{vol_key} = ({_fmt(return_value)} - {_fmt(free_value)})"
        f"/{_fmt(vol_value)} = {_fmt(rebuilt)}; the block publishes that formula "
        f"in moments_basis.formulas, and a ratio that does not rebuild from its "
        f"own operands (tolerance {_fmt(tolerance)}, the display step of the "
        f"digits this block actually wrote: {return_key} and {free_key} and "
        f"{vol_key} and {point_key} at "
        f"{_declared_digits(return_value)}/{_declared_digits(free_value)}/"
        f"{_declared_digits(vol_value)}/{_declared_digits(node[point_key])} "
        f"decimals) is one of them being restated rather than computed"
    )


def _rel_verdict_under_its_own_declared_threshold(
    node: dict[str, Any],
    point_key: str,
    companions: tuple[tuple[str, Any], ...],
    section: dict[str, Any] | None,
) -> tuple[bool, str | None]:
    """A test VERDICT against the p-value and the threshold the scan declares.

    The scan publishes which test decides (``test_agreement.decision_test``),
    what its p-value key is named, at what level, and with which comparison
    (``signal_policy``).  The verdict is therefore checkable without knowing
    anything about cointegration: the p-value key and the threshold key are
    derived from the declared test name, so a scan that renames its decision
    test is still checked.
    """
    if section is None:
        return False, None
    verdict = node.get(point_key)
    if not isinstance(verdict, bool):
        return False, None
    test = _dig(section, "test_agreement.decision_test")
    comparison = _dig(section, "signal_policy.p_value_threshold_comparison")
    if not (isinstance(test, str) and test.strip() and isinstance(comparison, str)):
        return False, None
    test = test.strip()
    comparison = comparison.strip().lower()
    threshold = _dig(section, f"signal_policy.{test}_p_value_threshold")
    pvalue_key = f"{test}_pvalue"
    if not (_finite(threshold) and _finite(node.get(pvalue_key))):
        return False, None
    pvalue = float(node[pvalue_key])
    level = float(threshold)
    # The band is half a display step of the p-VALUE alone, and not of the
    # threshold: the threshold is a declared policy constant, published exactly,
    # while a p-value is a measured figure and one rounded onto the threshold
    # from below does not make a verdict of False a contradiction.  The p-values
    # under ``pairs`` are published to six decimals, so the band is 5e-7 -- four
    # orders of magnitude below the tightest margin measured on the real export.
    band = _display_step(pvalue)
    if comparison == "strictly_less_than":
        expected = pvalue < level - band
    elif comparison in ("less_than", "at_most"):
        expected = pvalue <= level + band
    elif comparison == "strictly_greater_than":
        expected = pvalue > level + band
    elif comparison in ("greater_than", "at_least"):
        expected = pvalue >= level - band
    else:
        return False, None
    if expected == verdict:
        return True, None
    return True, (
        f"{point_key}={verdict!r} while {pvalue_key}={_fmt(pvalue)} is "
        f"{comparison} {test}_p_value_threshold {_fmt(level)} on the model's "
        f"own declared decision test (tolerance {_fmt(band)}, half the last "
        f"decimal place the {pvalue_key} was published to); a verdict its own "
        "p-value contradicts is a label, not a result"
    )


def _rel_alert_arm_selected_by_its_own_correlation(
    node: dict[str, Any],
    point_key: str,
    companions: tuple[tuple[str, Any], ...],
    section: dict[str, Any] | None,
) -> tuple[bool, str | None]:
    """The alert arm must be the one the published correlation selects.

    ``alert_level``, ``alert_direction`` and ``is_regime_break`` are three fields
    describing ONE comparison of the current average correlation against the
    10th / 75th / 90th percentiles of its own history, and the service sets all
    three from the arm the numbers land in.  The arms are re-derived here from
    the block's own four figures and compared to the three published labels, so
    a correlation that moved while the labels stood still is a finding rather
    than a sentence a reader has to re-check by hand.
    """
    published_level = node.get(point_key)
    direction_key, direction = companions[4]
    break_key, is_break = companions[5]
    current = _point_estimate(companions[0][1])
    if not (
        isinstance(published_level, str)
        and isinstance(direction, str)
        and isinstance(is_break, bool)
        and _finite(current)
    ):
        return False, None
    value = float(current)
    for threshold_key, comparison, level, arm_direction, arm_break in (
        CORRELATION_ALERT_ARMS
    ):
        threshold = _point_estimate(node.get(threshold_key))
        if not _finite(threshold):
            return False, None
        limit = float(threshold)
        # The band is half a display step of BOTH figures the comparison is made
        # from, so a current correlation the export cannot print as different
        # from the threshold is not read as a different arm.
        band = _display_step(current) + _display_step(threshold)
        in_arm = (value >= limit - band if comparison == "ge"
                  else value <= limit + band)
        if not in_arm:
            continue
        if (published_level, direction, is_break) == (level, arm_direction,
                                                       arm_break):
            return True, None
        return True, (
            f"{point_key}={published_level!r} with {direction_key}="
            f"{direction!r} and {break_key}={is_break!r}, but "
            f"{companions[0][0]}={_fmt(value)} is "
            f"{'at or above' if comparison == 'ge' else 'at or below'} "
            f"{threshold_key}={_fmt(limit)}, which is the "
            f"({level!r}, {arm_direction!r}, {arm_break!r}) arm"
        )
    neutral_level, neutral_direction, neutral_break = CORRELATION_ALERT_NEUTRAL
    if (published_level, direction, is_break) == (neutral_level, neutral_direction,
                                                  neutral_break):
        return True, None
    return True, (
        f"{point_key}={published_level!r} with {direction_key}={direction!r} and "
        f"{break_key}={is_break!r}, but {companions[0][0]}={_fmt(value)} is "
        f"inside the {COMPANION_ALERT_BAND[0]}..{COMPANION_ALERT_BAND[1]} "
        f"percentile band the three published thresholds describe, which is the "
        f"({neutral_level!r}, {neutral_direction!r}, {neutral_break!r}) arm"
    )


#: Named in the message above so the reader is not left counting thresholds.
COMPANION_ALERT_BAND = ("10th", "90th")

#: Relation name -> the function that decides it.  Data in, data out: a
#: relation returns ``(testable, violation)`` and never raises, never widens
#: itself, and never returns a violation for a pair it could not test.
RELATIONS: dict[str, Callable[
    [dict[str, Any], str, tuple[tuple[str, Any], ...], dict[str, Any] | None],
    tuple[bool, str | None],
]] = {
    "probability_bounded_by_its_own_percentiles":
        _rel_probability_bounded_by_its_own_percentiles,
    "point_equals_its_own_distribution_origin":
        _rel_point_equals_its_own_distribution_origin,
    "reciprocal_of_its_own_index": _rel_reciprocal_of_its_own_index,
    "tail_mean_not_milder_than_its_quantile":
        _rel_tail_mean_not_milder_than_its_quantile,
    "ratio_of_its_own_operands": _rel_ratio_of_its_own_operands,
    "verdict_under_its_own_declared_threshold":
        _rel_verdict_under_its_own_declared_threshold,
    "alert_arm_selected_by_its_own_correlation":
        _rel_alert_arm_selected_by_its_own_correlation,
}


def num_026_estimate_agrees_with_its_own_companion(
    export: Export,
) -> list[Finding]:
    """A point estimate must lie inside the companion statistic it summarises.

    Every rule above asks whether two fields the system emitted TOGETHER are
    consistent.  This one asks whether a single figure means what its name says,
    by testing it against the distribution or the decision it was computed from
    and the block publishes beside it: a success probability against the
    percentile table of the paths it counts, a Monte Carlo origin against the
    fan's own first row, an effective-position count against the Herfindahl index
    it is the reciprocal of, a tail mean against the quantile that selects the
    tail, a Sharpe ratio against the return and volatility it divides, a test
    verdict against the p-value and threshold the same scan declares, a
    correlation alert against the percentiles that arm it, and a regime label
    against the posterior that produced it (NUM-025, which carries the state
    case because a state label is an action input in its own right).

    The identities are :data:`COMPANION_MAP` -- one line each -- and the rule
    fires on the RELATION, so a section that publishes ``cvar_95`` with no
    ``var_95`` beside it, or with a null one, is not testable and produces
    nothing.  That is the failure mode a rule of this shape has to avoid: a gate
    that is always red is not stricter, it is ignored, so the reach of this rule
    is measured and printed rather than assumed.
    """
    findings: list[Finding] = []
    section_data: dict[str, dict[str, Any]] = {
        name: section["data"]
        for name, section in export.sections().items()
        if isinstance(section, dict) and isinstance(section.get("data"), dict)
    }
    for path, node in export.dicts:
        for companion in COMPANION_MAP:
            if companion.point_key not in node:
                continue
            if not all(key in node for key in companion.companion_keys):
                continue
            section = section_data.get(_section_of(path))
            if companion.section_keys and (
                section is None
                or any(_dig(section, key) is None for key in companion.section_keys)
            ):
                continue
            decide = RELATIONS[companion.relation]
            testable, violation = decide(
                node,
                companion.point_key,
                tuple((key, node[key]) for key in companion.companion_keys),
                section,
            )
            if not testable or violation is None:
                continue
            findings.append(
                Finding(
                    "NUM-026",
                    _section_of(path),
                    f"{path}.{companion.point_key}",
                    violation,
                )
            )
    return findings


# --------------------------------------------------------------------------
# The rule table.  A new invariant is one entry here.
# --------------------------------------------------------------------------

RULES: tuple[Rule, ...] = (
    # ---- envelope / contract
    Rule("ENV-001", CATEGORY_ENVELOPE,
         f"schema_version equals {EXPECTED_SCHEMA_VERSION!r}", env_001_schema_version),
    Rule("ENV-002", CATEGORY_ENVELOPE,
         "generated_at <= completed_at", env_002_generation_order),
    Rule("ENV-003", CATEGORY_ENVELOPE,
         "scope equals the sections keys, as a set AND in order", env_003_scope_matches_sections),
    Rule("ENV-004", CATEGORY_ENVELOPE,
         "every section.status is in {available, partial, unavailable}", env_004_section_status_vocabulary),
    Rule("ENV-005", CATEGORY_ENVELOPE,
         "the literal 'not_requested' never appears; an unrequested section is absent",
         env_005_no_not_requested),
    Rule("ENV-006", CATEGORY_ENVELOPE,
         "no error: null (or empty) at ANY depth; a successful section omits the key",
         env_006_no_null_error),
    Rule("ENV-007", CATEGORY_ENVELOPE,
         "every data_status at any depth is in {available, partial, unavailable}, "
         "never a coverage word", env_007_data_status_vocabulary),
    Rule("ENV-008", CATEGORY_ENVELOPE,
         "every coverage.status is in {complete, partial, unavailable, unknown}",
         env_008_coverage_status_vocabulary),
    Rule("ENV-009", CATEGORY_ENVELOPE,
         "coverage.weight_basis appears only with non-empty missing_tickers and "
         f"is always {CANONICAL_WEIGHT_BASIS!r}", env_009_weight_basis_conditional),
    Rule("ENV-010", CATEGORY_ENVELOPE,
         "covered_tickers disjointly partitions requested_tickers, in request order",
         env_010_covered_plus_missing_partitions_requested),
    Rule("ENV-011", CATEGORY_ENVELOPE,
         "available_tickers is a subset of requested_tickers unless "
         "raw_available_tickers documents the extras", env_011_available_within_requested),
    Rule("ENV-012", CATEGORY_ENVELOPE,
         "a section as_of is ORDERED against the collection clock: not after "
         "completed_at, not older than "
         f"{AS_OF_STALENESS_DAYS:g} days before generated_at, and a date inside "
         "the collection window only with a disclosed refresh timestamp",
         env_012_as_of_outside_collection_window),
    Rule("ENV-013", CATEGORY_ENVELOPE,
         "a section does not report as_of: null while its payload carries dated "
         "observations", env_013_no_null_as_of_with_dated_payload),
    Rule("ENV-014", CATEGORY_ENVELOPE,
         "every non-null as_of carries a non-empty as_of_semantics",
         env_014_as_of_requires_semantics),
    Rule("ENV-015", CATEGORY_ENVELOPE,
         "a section whose payload declares a monetary unit also declares "
         "section.currency", env_015_monetary_sections_declare_currency),
    Rule("ENV-016", CATEGORY_ENVELOPE,
         "a section that publishes a degradation — a partial/unavailable status "
         "OR a non-empty block_reason/omitted/withheld/excluded marker — has a "
         "non-empty warnings array, whatever its own status",
         env_016_degraded_sections_warn),
    Rule("ENV-017", CATEGORY_ENVELOPE,
         "no NaN/Infinity anywhere and the bytes re-parse as strict JSON",
         env_017_strict_finite_json),
    Rule("ENV-018", CATEGORY_ENVELOPE,
         "no duplicate object keys in the source bytes", env_018_no_duplicate_keys),
    Rule("ENV-019", CATEGORY_ENVELOPE,
         "catches AD-5/G3: no record claims an executable status inside a "
         "section whose own execution_eligible is false", env_019_record_status_respects_section_gate),
    Rule("ENV-020", CATEGORY_ENVELOPE,
         "catches SI-5: a section publishing estimated parameters/ratios carries "
         "a standard error, an interval or an effective-sample-size figure",
         env_020_point_estimates_carry_uncertainty),
    Rule("ENV-021", CATEGORY_ENVELOPE,
         "catches AD-10/G4: a hard 0 coverage_ratio is never published beside a "
         "null covered_count in the same block", env_021_zero_ratio_needs_a_count),
    # ---- cross-section
    Rule("XS-001", CATEGORY_CROSS_SECTION,
         "every section publishing the holding window agrees on its start "
         "(intersection_start, the block's own start, measured_window.start or "
         "delivered_start), covered_days and covered_days_scope",
         xs_001_holding_window_agreement),
    Rule("XS-002", CATEGORY_CROSS_SECTION,
         "catches D-01: a published covered_days carries a non-empty covered_days_scope",
         xs_002_covered_days_requires_scope),
    Rule("XS-003", CATEGORY_CROSS_SECTION,
         "every effective_start has provenance and an inferred start publishes the "
         "stored_added_on it displaced", xs_003_effective_start_provenance),
    Rule("XS-004", CATEGORY_CROSS_SECTION,
         "an effective_start never contradicts the stored added_on without "
         "declaring a buy-price inference", xs_004_effective_start_contradiction),
    Rule("XS-005", CATEGORY_CROSS_SECTION,
         "catches D-02: per-ticker masked_days/return_observations are reconcilable "
         "or the block declares per_ticker_count_units", xs_005_per_ticker_counts_reconcilable),
    Rule("XS-006", CATEGORY_CROSS_SECTION,
         "every full_history block declares a scope, an observation count and a window",
         xs_006_full_history_declares_window),
    Rule("XS-007", CATEGORY_CROSS_SECTION,
         "regime conditional coverage equals the conditional sample, not the "
         "holding pool or the model window", xs_007_conditional_coverage_uses_conditional_sample),
    Rule("XS-008", CATEGORY_CROSS_SECTION,
         "a composite does not read 'complete' coverage while a component is "
         "unavailable unless the coverage block names the components it describes",
         xs_008_composite_coverage_honesty),
    Rule("XS-009", CATEGORY_CROSS_SECTION,
         "catches D-06: every published factor fit statistic declares its window "
         "and observation count, and disagreeing sections distinguish their windows",
         xs_009_factor_fit_declares_window),
    Rule("XS-010", CATEGORY_CROSS_SECTION,
         "catches MY-1: a holding-window block's own start matches the "
         "holding_window_start it publishes beside it", xs_010_holding_window_start_matches_itself),
    # ---- numeric
    Rule("NUM-001", CATEGORY_NUMERIC,
         "sum(market_value) == total_value and sum(weight) == 1",
         num_001_portfolio_totals),
    Rule("NUM-002", CATEGORY_NUMERIC,
         "sector weights: the published total equals the sum of the published "
         "values, the residual equals 1 - total, and nothing is renormalized to 1.0",
         num_002_sector_weight_residual),
    Rule("NUM-003", CATEGORY_NUMERIC,
         "risk contributions declare a unit and publish a residual summing to ~1",
         num_003_risk_contribution_basis),
    Rule("NUM-004", CATEGORY_NUMERIC,
         "every liquidity category matches its own published score under the "
         "declared band rule (recomputed, not trusted)", num_004_liquidity_band_matches_score),
    Rule("NUM-005", CATEGORY_NUMERIC,
         "an unavailable liquidity result reports a null score, not a plausible "
         "mid value", num_005_unavailable_liquidity_is_null),
    Rule("NUM-006", CATEGORY_NUMERIC,
         "catches D-03: non-measured market caps are counted and disclosed at "
         "section level", num_006_non_measured_market_caps_disclosed),
    Rule("NUM-007", CATEGORY_NUMERIC,
         "max_drawdown == portfolio_impact * 1.15 for every stress scenario",
         num_007_stress_drawdown_identity),
    Rule("NUM-008", CATEGORY_NUMERIC,
         "every priced sizing trade: amount == shares_delta * sizing_price + "
         "rounding_residual", num_008_trade_amount_reconciles),
    Rule("NUM-009", CATEGORY_NUMERIC,
         "a zero-share trade carries an explicit status and preserves its notional",
         num_009_zero_share_trades_are_labelled),
    Rule("NUM-010", CATEGORY_NUMERIC,
         "the reconciliation max tolerance is really the max over the same "
         "population as the residual", num_010_reconciliation_maxima_are_maxima),
    Rule("NUM-011", CATEGORY_NUMERIC,
         "optimizer weight_delta closes against its own published legs on every record",
         num_011_optimizer_weight_delta_closes),
    Rule("NUM-012", CATEGORY_NUMERIC,
         "optimizer publishes a gross-exposure residual and derives "
         "financing_required from the unrounded figure", num_012_gross_exposure_residual),
    Rule("NUM-013", CATEGORY_NUMERIC,
         "Monte Carlo quantiles are non-decreasing across percentiles and "
         "success_definition is present", num_013_monte_carlo_quantiles),
    Rule("NUM-014", CATEGORY_NUMERIC,
         "pairs: n*(n-1)/2 == scanned_pairs_count, a shallow leg forces partial, "
         "EG/Johansen agreement counts are published", num_014_pairs_counting),
    Rule("NUM-015", CATEGORY_NUMERIC,
         "regime probabilities and transition rows sum to ~100 with a published "
         "residual; stability_pct declares its rule", num_015_regime_percentages),
    Rule("NUM-016", CATEGORY_NUMERIC,
         "the tail-dependence matrix is square, symmetric and unit-diagonal",
         num_016_tail_dependence_matrix),
    Rule("NUM-017", CATEGORY_NUMERIC,
         "EVT declares which gpd_shape_xi produced the metrics",
         num_017_evt_declares_xi),
    Rule("NUM-018", CATEGORY_NUMERIC,
         "catches D-04: no risk sub-score is a hard 0 while excluded_components is empty",
         num_018_no_hard_zero_sub_scores),
    Rule("NUM-019", CATEGORY_NUMERIC,
         "catches D-05: no performance row's benchmark_value equals its own "
         "portfolio_value unless flagged, no return on the first row, every row "
         "carries a benchmark", num_019_performance_benchmark_series),
    Rule("NUM-020", CATEGORY_NUMERIC,
         "a short or stale performance window is reported as partial and the "
         "dashboard section reflects it", num_020_short_window_is_reported_partial),
    Rule("NUM-021", CATEGORY_NUMERIC,
         "catches QM-1: a portfolio return series publishes, per row or in "
         "aggregate, how many constituents were active on each date",
         num_021_return_series_declares_breadth),
    Rule("NUM-022", CATEGORY_NUMERIC,
         "catches SI-3/QM-3: a two-element interval is never exactly a round "
         "constant multiple of its own centre", num_022_interval_is_not_a_constant_band),
    Rule("NUM-023", CATEGORY_NUMERIC,
         "catches QM-4: an achieved_* field does not restate its own target while "
         "a scale factor is published", num_023_achieved_value_is_not_its_own_target),
    Rule("NUM-024", CATEGORY_NUMERIC,
         "catches SI-1/G9: a trade directive publishes its threshold, diagnostic "
         "agreement, comparison count, multiplicity correction and size ratio",
         num_024_trade_directive_publishes_its_basis),
    Rule("NUM-025", CATEGORY_NUMERIC,
         "regime.current_regime is the argmax of the regime_probabilities "
         "published beside it; a tied, absent or wholly null posterior is "
         "undetermined, not a pass",
         num_025_current_regime_is_its_own_argmax),
    Rule("NUM-026", CATEGORY_NUMERIC,
         "a point estimate agrees with the companion statistic it summarises: "
         "the identities of COMPANION_MAP (success probability vs its own "
         "percentile table, simulation origin vs its own fan, effective "
         "positions vs its own HHI, tail mean vs the quantile selecting it, "
         "Sharpe vs its own moments, a test verdict vs its own declared "
         "p-value threshold, a correlation alert vs the percentiles that arm it)",
         num_026_estimate_agrees_with_its_own_companion),
)

RULES_BY_ID: dict[str, Rule] = {rule.rule_id: rule for rule in RULES}


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------


def _reject_constant(token: str) -> Any:
    raise ValueError(f"non-finite JSON constant {token!r}")


def _strict_loads(raw: str) -> Any:
    return json.loads(raw, parse_constant=_reject_constant)


def load_export(path: Path) -> Export:
    """Read an export file, reporting the three failure modes separately.

    A missing file, a file that is not UTF-8, and a file that is not a JSON
    object are three different user problems and each gets its own message.
    """
    try:
        raw_bytes = path.read_bytes()
    except FileNotFoundError:
        raise FileNotFoundError(f"export not found: {path}") from None
    except IsADirectoryError:
        raise IsADirectoryError(f"export path is a directory, not a file: {path}") from None
    except OSError as exc:
        raise OSError(f"could not read export {path}: {exc}") from exc
    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnicodeDecodeError(
            "utf-8", raw_bytes, exc.start, exc.end, f"{exc.reason} in {path}"
        ) from None

    strict_error: str | None = None
    try:
        _strict_loads(raw)
    except ValueError as exc:
        strict_error = str(exc)

    duplicates: list[tuple[str, str]] = []

    def _pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        for key, _value in pairs:
            if key in seen:
                duplicates.append(("<document>", key))
            seen.add(key)
        return dict(pairs)

    try:
        doc = json.loads(raw, object_pairs_hook=_pairs_hook)
    except ValueError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError(
            f"{path} is a JSON {type(doc).__name__}, not the export envelope object"
        )
    return Export(
        doc=doc, raw=raw, path=path, strict_error=strict_error,
        duplicate_keys=tuple(dict.fromkeys(duplicates)),
    )


def run_rules(export: Export, rule_ids: list[str] | None = None) -> tuple[list[Finding], list[tuple[Rule, str]]]:
    """Run the table.  Returns findings plus any rule that itself blew up.

    A rule raising is reported as a tool error rather than swallowed: a crash
    must never be mistaken for a pass.
    """
    selected = RULES if not rule_ids else [RULES_BY_ID[r] for r in rule_ids]
    findings: list[Finding] = []
    errors: list[tuple[Rule, str]] = []
    for rule in selected:
        try:
            findings.extend(rule.fn(export))
        except Exception as exc:  # noqa: BLE001 - a broken rule must not hide others
            errors.append((rule, f"{type(exc).__name__}: {exc}"))
    return findings, errors


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

_VERDICT_WIDTH = 8
_DESC_WIDTH = 74


def _rule_lines(text: str, width: int = _DESC_WIDTH) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines or [""]


def _volatile_allow_list_lines(indent: str = "  ") -> list[str]:
    """The allow-list as text, so ``render_diff`` stays a pure function.

    Printed rather than merely applied: a quiet re-run should be visibly a
    consequence of these seven patterns, not something a reader has to trust.
    """
    lines = [
        f"{indent}allow-listed volatile fields EXCLUDED from this diff "
        f"({len(VOLATILE_PATTERNS)} patterns):"
    ]
    for entry in VOLATILE_PATTERNS:
        lines.append(f"{indent}  - {entry.label}")
        lines.append(f"{indent}      pattern: {entry.pattern.pattern}")
        lines.append(f"{indent}      why:     {entry.why}")
    return lines


def render_check(export: Export, findings: list[Finding], errors: list[tuple[Rule, str]],
                 *, rule_ids: list[str] | None) -> str:
    out: list[str] = []
    by_rule: dict[str, list[Finding]] = {rule.rule_id: [] for rule in RULES}
    for finding in findings:
        by_rule.setdefault(finding.rule_id, []).append(finding)
    source = export.path or "<in-memory>"

    out.append(f"export       : {source}")
    out.append(
        f"envelope     : schema_version={export.doc.get('schema_version')!r} "
        f"export_id={export.doc.get('export_id')!r} "
        f"sections={len(export.sections())}"
    )
    out.append(
        f"rules        : {len(RULES) if not rule_ids else len(rule_ids)} selected "
        f"of {len(RULES)}"
    )
    out.append("")

    for category in CATEGORY_ORDER:
        rules = [
            rule
            for rule in RULES
            if rule.category == category and (not rule_ids or rule.rule_id in rule_ids)
        ]
        if not rules:
            continue
        out.append("=" * 100)
        out.append(f"{category.upper()}  ({len(rules)} rules)")
        out.append("=" * 100)
        for rule in rules:
            hits = by_rule.get(rule.rule_id, [])
            crashed = next((msg for r, msg in errors if r.rule_id == rule.rule_id), None)
            verdict = "ERROR" if crashed else ("FAIL" if hits else "pass")
            lines = _rule_lines(rule.description)
            out.append(f"  {rule.rule_id:<8} {verdict:>{_VERDICT_WIDTH}}  {lines[0]}")
            for extra in lines[1:]:
                out.append(f"  {'':<8} {'':>{_VERDICT_WIDTH}}  {extra}")
            if crashed:
                out.append(f"  {'':<8} {'':>{_VERDICT_WIDTH}}  !! rule raised: {crashed}")
            for hit in hits:
                out.append(
                    f"  {'':<8} {'':>{_VERDICT_WIDTH}}  - [{hit.section}] {hit.path}: {hit.message}"
                )
        out.append("")

    out.append("=" * 100)
    out.append("PER-SECTION VERDICT")
    out.append("=" * 100)
    out.append(f"  {'section':<22} {'status':<13} {'findings':<9} rules")
    touched: dict[str, set[str]] = {}
    for finding in findings:
        touched.setdefault(finding.section, set()).add(finding.rule_id)
    for name, section in export.sections().items():
        status = section.get("status") if isinstance(section, dict) else None
        hits = touched.get(name, set())
        verdict = "pass" if not hits else "FAIL"
        out.append(
            f"  {name:<22} {str(status):<13} {len(hits):<9} {verdict} "
            f"{sorted(hits) if hits else ''}"
        )
    for name in sorted(set(touched) - set(export.sections())):
        out.append(f"  {name:<22} {'-':<13} {len(touched[name]):<9} FAIL {sorted(touched[name])}")
    out.append("")

    failed_rules = sorted({f.rule_id for f in findings} | {r.rule_id for r, _ in errors})
    passed_rules = [
        rule.rule_id
        for rule in RULES
        if (not rule_ids or rule.rule_id in rule_ids) and rule.rule_id not in failed_rules
    ]
    out.append("=" * 100)
    out.append("SUMMARY")
    out.append("=" * 100)
    out.append(f"  rules run   : {len(RULES) if not rule_ids else len(rule_ids)}")
    out.append(f"  passed      : {len(passed_rules)}  {passed_rules}")
    out.append(f"  failed      : {len(failed_rules)}  {failed_rules}")
    out.append(f"  findings    : {len(findings)}")
    if errors:
        out.append(f"  rule errors : {len(errors)}")
    out.append(
        "  note        : rules marked 'catches D-0x' guard defects that were "
        "recorded in .scratch/ai-context-v3-remediation-2026-09/open-defects.md. "
        "They are expected to be GREEN; red means that defect returned."
    )
    for rule, message in errors:
        out.append(f"  !! {rule.rule_id} raised: {message}")
    return "\n".join(out)


def render_check_json(export: Export, findings: list[Finding],
                      errors: list[tuple[Rule, str]], *, rule_ids: list[str] | None) -> str:
    failed = sorted({f.rule_id for f in findings} | {r.rule_id for r, _ in errors})
    selected = [r.rule_id for r in RULES if not rule_ids or r.rule_id in rule_ids]
    payload = {
        "export": str(export.path) if export.path else None,
        "export_id": export.doc.get("export_id"),
        "schema_version": export.doc.get("schema_version"),
        "section_count": len(export.sections()),
        "rules_run": selected,
        "rules_passed": [r for r in selected if r not in failed],
        "rules_failed": failed,
        "counts": {
            "rules_run": len(selected),
            "rules_passed": len([r for r in selected if r not in failed]),
            "rules_failed": len(failed),
            "findings": len(findings),
            "rule_errors": len(errors),
        },
        "by_category": {
            category: {
                "rules": sum(
                    1 for r in RULES if r.category == category and r.rule_id in selected
                )
            }
            for category in CATEGORY_ORDER
        },
        "findings": [
            {
                "rule_id": f.rule_id,
                "section": f.section,
                "path": f.path,
                "message": f.message,
            }
            for f in findings
        ],
        "rule_errors": [{"rule_id": r.rule_id, "error": m} for r, m in errors],
    }
    return json.dumps(payload, indent=2, default=str)


def render_rules() -> str:
    out: list[str] = [
        "=" * 100,
        f"AI-CONTEXT EXPORT AUDIT RULES ({len(RULES)} total)",
        "=" * 100,
        "Every rule is hard-failing: one finding exits non-zero.",
        "A rule marked 'catches D-0x' guards a defect recorded in",
        ".scratch/ai-context-v3-remediation-2026-09/open-defects.md. Those are",
        "fixed, so those rules are expected to be GREEN; red means a regression.",
        "",
    ]
    for category in CATEGORY_ORDER:
        rules = [rule for rule in RULES if rule.category == category]
        out.append(f"{category.upper()}  ({len(rules)})")
        out.append("-" * 100)
        for rule in rules:
            out.append(f"  {rule.rule_id:<9} {rule.description}")
        out.append("")
    counts = {category: sum(1 for r in RULES if r.category == category) for category in CATEGORY_ORDER}
    out.append("COUNTS: " + "  ".join(f"{c}={n}" for c, n in counts.items()) + f"  total={len(RULES)}")
    return "\n".join(out)


# --------------------------------------------------------------------------
# diff
# --------------------------------------------------------------------------


def flatten(node: Any, path: str = "") -> dict[str, Any]:
    """Flatten a document to ``{path: leaf}``.

    Dict key order is invisible here (a path is keyed by name, not position), so
    a section that re-serialises its maps in a different order is not a change.
    List order IS visible, which is correct: the contract pins list ordering.
    Empty containers are recorded as leaves so that gaining or losing one is
    still a diff.
    """
    flat: dict[str, Any] = {}
    if isinstance(node, dict):
        if not node:
            flat[path or "<document>"] = {}
            return flat
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            flat.update(flatten(value, child))
        return flat
    if isinstance(node, list):
        if not node:
            flat[path or "<document>"] = []
            return flat
        for index, value in enumerate(node):
            flat.update(flatten(value, f"{path}[{index}]"))
        return flat
    flat[path or "<document>"] = node
    return flat


def volatile_label(path: str) -> str | None:
    for entry in VOLATILE_PATTERNS:
        if entry.pattern.search(path):
            return entry.label
    return None


@dataclass(frozen=True, slots=True)
class DiffEntry:
    kind: str  # added | removed | changed
    path: str
    old: Any = None
    new: Any = None
    volatile: str | None = None


def diff_exports(base: Export, head: Export, *, include_volatile: bool = False) -> list[DiffEntry]:
    old = flatten(base.doc)
    new = flatten(head.doc)
    entries: list[DiffEntry] = []
    for path in sorted(set(old) | set(new)):
        label = volatile_label(path)
        if label and not include_volatile:
            continue
        in_old, in_new = path in old, path in new
        if in_old and not in_new:
            entries.append(DiffEntry("removed", path, old[path], None, label))
        elif in_new and not in_old:
            entries.append(DiffEntry("added", path, None, new[path], label))
        elif old[path] != new[path]:
            entries.append(DiffEntry("changed", path, old[path], new[path], label))
    return entries


def render_diff(base: Export, head: Export, entries: list[DiffEntry], *,
                summary_only: bool, truncate: int | None,
                include_volatile: bool) -> str:
    out: list[str] = [
        f"base : {base.path or '<in-memory>'}",
        f"head : {head.path or '<in-memory>'}",
        "",
    ]
    out.extend(_volatile_allow_list_lines())
    if include_volatile:
        out.append("  (--include-volatile: the allow-list above is NOT applied)")
    out.append("")

    counts = {"added": 0, "removed": 0, "changed": 0}
    for entry in entries:
        counts[entry.kind] += 1
    total = len(entries)
    out.append(
        f"compared {len(flatten(base.doc))} base / {len(flatten(head.doc))} head leaf paths"
    )
    out.append(
        f"  added {counts['added']}   removed {counts['removed']}   "
        f"changed {counts['changed']}   total {total}"
    )
    out.append("")
    if total == 0:
        out.append("no differences outside the allow-list above.")
        return "\n".join(out)
    if summary_only:
        by_prefix: dict[str, int] = {}
        for entry in entries:
            head_segment = entry.path.split(".")[0]
            by_prefix[head_segment] = by_prefix.get(head_segment, 0) + 1
        out.append("differences by top-level key:")
        for key in sorted(by_prefix):
            out.append(f"  {key:<24} {by_prefix[key]}")
        return "\n".join(out)
    width = max((len(e.path) for e in entries), default=10)
    width = min(width, 70)
    for entry in entries:
        marker = {"added": "+", "removed": "-", "changed": "~"}[entry.kind]
        flag = f" [volatile:{entry.volatile}]" if entry.volatile else ""
        out.append(f"{marker} {entry.path:<{width}}{flag}")
        if entry.kind == "changed":
            out.append(
                f"    old: {_truncate(json.dumps(entry.old, default=str), truncate)}"
            )
            out.append(
                f"    new: {_truncate(json.dumps(entry.new, default=str), truncate)}"
            )
        elif entry.kind == "added":
            out.append(
                f"    new: {_truncate(json.dumps(entry.new, default=str), truncate)}"
            )
        else:
            out.append(
                f"    old: {_truncate(json.dumps(entry.old, default=str), truncate)}"
            )
    return "\n".join(out)


# --------------------------------------------------------------------------
# generate
# --------------------------------------------------------------------------


def fetch_export(url: str, *, timeout: float) -> bytes:
    """Fetch the export and return the RAW BYTES.

    Deliberately ``urllib.request`` + ``.read()``.  Decoding on the way in is
    how an em dash became ``â\\x80\\x94`` and looked like a product bug: any
    client that decodes UTF-8 as Latin-1 corrupts non-ASCII silently, and the
    damage is only visible in a diff of bytes nobody was looking at.
    """
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _is_relative_to(path: Path, root: Path) -> bool:
    """``Path.is_relative_to`` that tolerates a non-resolved root."""
    try:
        return path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def cmd_generate(args: argparse.Namespace) -> int:
    url = args.url
    out_dir = Path(args.dir) if args.dir else DEFAULT_EXPORT_DIR
    print(f"fetching {url}")
    try:
        raw = fetch_export(url, timeout=args.timeout)
    except urllib.error.HTTPError as exc:
        print(f"error: the server answered HTTP {exc.code} for {url}", file=sys.stderr)
        print(f"       body: {_truncate(exc.read().decode('utf-8', 'replace'), 400)}", file=sys.stderr)
        print(f"       {SERVER_HINT}", file=sys.stderr)
        return 2
    except urllib.error.URLError as exc:
        print(f"error: could not reach {url}", file=sys.stderr)
        print(f"       reason: {exc.reason}", file=sys.stderr)
        print(f"       {SERVER_HINT}", file=sys.stderr)
        return 2
    except (TimeoutError, OSError) as exc:
        print(f"error: request to {url} failed: {exc}", file=sys.stderr)
        print(f"       {SERVER_HINT}", file=sys.stderr)
        return 2

    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        print(f"error: the response is not UTF-8 JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(doc, dict):
        print("error: the response is not an export envelope object", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        export_id = str(doc.get("export_id") or "export")
        completed = str(doc.get("completed_at") or "").replace(":", "").replace("-", "")
        stamp = completed[:15] if completed else "unknown"
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", export_id)
        target = out_dir / f"{safe_id}-{stamp}.json"

    if target.exists() and not args.force:
        print(f"error: {target} already exists; pass --force to overwrite", file=sys.stderr)
        return 2

    # A loud warning, not a block: --out is the caller's explicit choice, but
    # an export dropped anywhere else inside the repo is one `git add -A` away
    # from being committed, and it carries live holdings.
    in_default_dir = _is_relative_to(target, DEFAULT_EXPORT_DIR)
    if _is_relative_to(target, REPO_ROOT) and not in_default_dir:
        print(
            f"WARNING: {target} is inside the repo but NOT under the gitignored "
            f"{EXPORT_DIR_NAME}/.",
            file=sys.stderr,
        )
        print(
            "         It contains live holdings, quantities, cost basis and P&L. "
            "Do not commit it.",
            file=sys.stderr,
        )

    # BYTES, unmodified.  No encode(), no decode-and-re-encode round trip.
    target.write_bytes(raw)

    print(f"wrote        : {target}")
    print(f"bytes        : {len(raw)}")
    print(f"export_id    : {doc.get('export_id')!r}")
    print(f"sections     : {len(doc.get('sections') or {})}")
    print(f"schema_version: {doc.get('schema_version')!r}")
    print(
        "note         : this file contains live holdings, quantities, cost basis "
        "and P&L."
    )
    print(
        f"               gitignored: {in_default_dir} "
        f"(the default output dir is {EXPORT_DIR_NAME}/ at the repo root)"
    )
    return 0


# --------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------


def _resolve_export_path(args: argparse.Namespace) -> Path:
    if args.export:
        return Path(args.export)
    if not DEFAULT_EXPORT_DIR.is_dir():
        raise FileNotFoundError(
            f"no --export given and {DEFAULT_EXPORT_DIR} does not exist.\n"
            "       Run:  uv run python -m app.debugging.context_audit generate"
        )
    candidates = sorted(DEFAULT_EXPORT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError(
            f"no --export given and {DEFAULT_EXPORT_DIR} holds no *.json.\n"
            "       Run:  uv run python -m app.debugging.context_audit generate"
        )
    return candidates[-1]


def cmd_check(args: argparse.Namespace) -> int:
    rule_ids: list[str] = args.rule or []
    unknown = [r for r in rule_ids if r not in RULES_BY_ID]
    if unknown:
        print(f"error: unknown rule id(s): {unknown}", file=sys.stderr)
        print(f"       known ids: {sorted(RULES_BY_ID)}", file=sys.stderr)
        return 2
    try:
        path = _resolve_export_path(args)
        export = load_export(path)
    except (FileNotFoundError, IsADirectoryError, OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    findings, errors = run_rules(export, rule_ids)
    if args.as_json:
        print(render_check_json(export, findings, errors, rule_ids=rule_ids))
    else:
        print(render_check(export, findings, errors, rule_ids=rule_ids))
    return 1 if (findings or errors) else 0


# --------------------------------------------------------------------------
# diff command
# --------------------------------------------------------------------------


def cmd_diff(args: argparse.Namespace) -> int:
    try:
        base = load_export(Path(args.base))
    except (FileNotFoundError, IsADirectoryError, OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"error: base: {exc}", file=sys.stderr)
        return 2
    try:
        head = load_export(Path(args.head))
    except (FileNotFoundError, IsADirectoryError, OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"error: head: {exc}", file=sys.stderr)
        return 2

    entries = diff_exports(base, head, include_volatile=args.include_volatile)
    truncate = None if args.full else (args.truncate_chars or DIFF_TRUNCATE_CHARS)
    print(
        render_diff(
            base, head, entries,
            summary_only=args.summary_only, truncate=truncate,
            include_volatile=args.include_volatile,
        )
    )
    if args.fail_on_change and entries:
        return 1
    return 0


# --------------------------------------------------------------------------
# rules command
# --------------------------------------------------------------------------


def cmd_rules(_args: argparse.Namespace) -> int:
    print(render_rules())
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.debugging.context_audit",
        description=(
            "Read-only audit CLI for the portfolio AI-context export. "
            "Every rule is hard-failing; `check` exits non-zero on any finding."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser(
        "generate",
        help="fetch a fresh export and write the raw bytes to a gitignored path",
    )
    gen.add_argument("--url", default=DEFAULT_EXPORT_URL, help="override the export URL")
    gen.add_argument("--dir", default=None,
                     help=f"output directory (default: {EXPORT_DIR_NAME}/ at the repo root)")
    gen.add_argument("--out", default=None, help="explicit output file path")
    gen.add_argument("--timeout", type=float, default=180.0, help="request timeout seconds")
    gen.add_argument("--force", action="store_true", help="overwrite an existing file")
    gen.set_defaults(func=cmd_generate)

    chk = sub.add_parser("check", help="run every rule against an export")
    chk.add_argument("--export", default=None,
                     help="path to an export (default: newest *.json in the baseline dir)")
    chk.add_argument("--json", action="store_true", dest="as_json",
                     help="machine-readable output")
    chk.add_argument("--rule", action="append", default=None,
                     help="run only this rule id (repeatable)")
    chk.set_defaults(func=cmd_check)

    dif = sub.add_parser("diff", help="field-level diff of two exports")
    dif.add_argument("base")
    dif.add_argument("head")
    dif.add_argument("--full", action="store_true", help="print untruncated values")
    dif.add_argument("--summary-only", action="store_true", dest="summary_only",
                     help="counts only, no per-path lines")
    dif.add_argument("--truncate-chars", type=int, default=DIFF_TRUNCATE_CHARS,
                     help="value truncation width in the default output")
    dif.add_argument("--include-volatile", action="store_true", dest="include_volatile",
                     help="do not apply the volatile allow-list")
    dif.add_argument("--fail-on-change", action="store_true", dest="fail_on_change",
                     help="exit 1 when any non-allow-listed difference exists")
    dif.set_defaults(func=cmd_diff)

    rul = sub.add_parser("rules", help="list every rule id and what it asserts")
    rul.set_defaults(func=cmd_rules)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
