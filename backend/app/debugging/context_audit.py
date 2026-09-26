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

KNOWN-OPEN DEFECTS
------------------
D-01 .. D-06 in ``.scratch/ai-context-v3-remediation-2026-09/open-defects.md``
are deliberately UNFIXED.  The rules that exist to catch them are therefore
expected to be RED against today's export, and are marked ``catches D-0x`` in
their description so nobody "fixes" the rule to make the tool green.  A red
rule with that marker is the tool working, not the tool broken.
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
    """A section ``as_of`` is an OBSERVATION date, not a refresh timestamp.

    If one lands inside [generated_at, completed_at] it is quoting the
    collector's own clock, and a warning has to say so.
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
        if not (generated <= as_of <= completed):
            continue
        warnings = section.get("warnings") or []
        semantics = str(section.get("as_of_semantics") or "")
        disclosed = "refresh" in semantics or any(
            "refresh" in str(w).lower() for w in warnings
        )
        if not disclosed:
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


def env_016_degraded_sections_warn(export: Export) -> list[Finding]:
    findings: list[Finding] = []
    for name, section in export.sections().items():
        if not isinstance(section, dict):
            continue
        status = section.get("status")
        if status not in {"partial", "unavailable"}:
            continue
        warnings = section.get("warnings")
        if isinstance(warnings, list) and warnings:
            continue
        findings.append(
            Finding(
                "ENV-016",
                name,
                f"sections.{name}.warnings",
                f"status is {status!r} but warnings is {warnings!r}; a "
                "degraded section must name why it is degraded",
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


def xs_001_holding_window_agreement(export: Export) -> list[Finding]:
    """Every section publishing the holding window must agree on it.

    ``covered_days_scope`` is the join key: a model window (174 or 251 days)
    and a conditional regime sample (19 days) are legitimately different
    populations, so they are excluded rather than averaged in.
    """
    blocks = _holding_window_blocks(export)
    findings: list[Finding] = []
    if len(blocks) < 2:
        return findings
    # Only well-formed blocks can be compared; a block that publishes
    # covered_days as null is XS-002's problem, not an agreement failure.
    starts = {
        str(node.get("intersection_start"))
        for _, node in blocks
        if _iso_date(node.get("intersection_start"))
    }
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
                f"{len(blocks)} holding-window blocks disagree on "
                f"intersection_start: {sorted(starts)}",
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
    declared: list[tuple[str, str, float]] = []
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
            declared.extend((owner, f"{path}.{key}", value) for key, value in fits.items())
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
    for index, (owner_a, path_a, value_a) in enumerate(declared):
        for _owner_b, path_b, value_b in declared[index + 1 :]:
            if path_a == path_b or _close(value_a, value_b, abs_tol=0.01):
                continue
            findings.append(
                Finding(
                    "XS-009",
                    owner_a,
                    path_a,
                    f"this fit reports {_fmt(value_a)} and another reports "
                    f"{_fmt(value_b)} for the same factor model with no basis "
                    "field distinguishing the windows",
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


def num_018_no_hard_zero_sub_scores(export: Export) -> list[Finding]:
    """Catches D-04: an unmeasured sub-score indistinguishable from a real zero.

    ``risk_score`` published ``correlation: 0`` with
    ``excluded_components: []`` while Risk Studio independently measured an
    average correlation of 0.14.  A hard zero drags ``overall_score`` downward
    and nothing says why.
    """
    findings: list[Finding] = []
    for path, node in export.dicts:
        components = node.get("components")
        excluded = node.get("excluded_components")
        if not isinstance(components, dict) or not isinstance(excluded, list):
            continue
        zeros = [
            name
            for name, value in components.items()
            if _is_number(value) and float(value) == 0.0
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
         "a section as_of does not sit inside the envelope collection window "
         "unless a refresh timestamp is disclosed", env_012_as_of_outside_collection_window),
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
         "every partial/unavailable section has a non-empty warnings array",
         env_016_degraded_sections_warn),
    Rule("ENV-017", CATEGORY_ENVELOPE,
         "no NaN/Infinity anywhere and the bytes re-parse as strict JSON",
         env_017_strict_finite_json),
    Rule("ENV-018", CATEGORY_ENVELOPE,
         "no duplicate object keys in the source bytes", env_018_no_duplicate_keys),
    # ---- cross-section
    Rule("XS-001", CATEGORY_CROSS_SECTION,
         "every section publishing the holding window agrees on intersection_start, "
         "covered_days and covered_days_scope", xs_001_holding_window_agreement),
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
        "  note        : a rule marked 'catches D-0x' is expected to be RED while "
        "that defect is open.  See .scratch/ai-context-v3-remediation-2026-09/"
        "open-defects.md."
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
        "A rule whose description says 'catches D-0x' is RED on purpose while that",
        "defect is open (.scratch/ai-context-v3-remediation-2026-09/open-defects.md).",
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
