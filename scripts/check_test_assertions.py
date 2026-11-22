#!/usr/bin/env python3
"""Static gate: report test functions that cannot fail on a wrong value.

WHAT THIS IS
    A stdlib-only `ast` reader over the backend test tree that reports test
    functions whose PASS carries no information about values. One question per
    test -- "if the code under test returned a wrong number, would this test go
    red?" -- answered from source text alone.

WHAT THIS IS NOT
    This script NEVER imports pytest, never imports the `app` package, never
    executes a test, and never touches a database or the network. It is a static
    reader: it calls `ast.parse` on files and does nothing else. That is
    asserted at the bottom of this file (`assert_is_static_reader` re-reads its
    own source and exits if the import list ever grows a `pytest`/`app` entry),
    so the property cannot rot silently.

    It also does not act on findings. It reports; a human decides. Nothing here
    deletes or rewrites a test file.

    Also note what "cannot fail" does not mean. A test with no `assert` at all
    still goes red if the code under test raises -- and several NO_ASSERT
    findings below are exactly that shape (a `# must not raise` smoke test).
    They are reported because their pass says nothing about a VALUE, which is
    what this gate is for. Claiming they are unfailable would be false.

DETECTION CLASSES

    NO_ASSERT          A test with no assertion of any kind -- no bare `assert`,
                       no `pytest.raises`/`pytest.warns`, no `self.assert*`, no
                       `np.testing.assert_*`, no `raise AssertionError`, and no
                       transitive call into a helper, fixture, or sibling test
                       module in the test tree that contains one.

    IS_NOT_NONE_ONLY   Every assertion in the test is `assert <x> is not None`
                       with no message and no `and`-chain, AND `<x>`'s root name
                       is never referenced again. A precondition that guards
                       nothing.

    TAUTOLOGY          `assert A == B` where A and B provably resolve to the same
                       module-level binding (`WHOLE_BOOK = HOLDING_COVERED_DAYS_SCOPE`
                       then `assert HOLDING_COVERED_DAYS_SCOPE == WHOLE_BOOK`).

    DUPLICATE_ASSERT   An `assert` statement whose source is byte-identical to an
                       `assert` in a different test function in the same file.

WHY THESE FOUR AND NOT "NO `assert` KEYWORD"
    Because the strongest tests in this repo contain no bare `assert` at all.
    `test_debug_context_audit.py::TestEnvelopeRules` asserts through `assert_only()`,
    which internally pins `rule_ids(export) == {rule_id}` -- a strict failure-set
    check. A keyword-keyed gate would indict it. So every assertion carrier is
    resolved TRANSITIVELY: a call to a helper defined in the test file, in a
    `conftest.py`, in a fixture requested as a test parameter, or in a sibling
    module of the test tree, is followed until an assertion is found or the call
    graph bottoms out. Only calls into the test tree are followed; a call into
    `app` or a third-party library is the code under test, not the test's own
    assertion, and is never assumed to assert.

WHY SAME-NAMED BINDINGS FROM DIFFERENT MODULES ARE NOT TAUTOLOGIES
    `test_ai_context_freshness_disclosure.py:1033` asserts
    `AS_OF_STALENESS_DAYS == ca.AS_OF_STALENESS_DAYS` where the left side is
    `from app.services.ai_context_service import AS_OF_STALENESS_DAYS` and
    `ca` is `from app.debugging import context_audit as ca`. Those are two
    independently editable constants in two modules, and the assert is a
    cross-module drift guard that would fire the moment one drifted. So the
    tautology rule canonicalises each side to `(module_path, attribute)` and
    requires the two module paths to be *the same*. Same name, different module
    => not a tautology. Same for `test_forecast_risk_cpu_offload.py:368`
    (`FORECAST_PORTFOLIO_REFIT_RESAMPLES == UNCERTAINTY_BOOTSTRAP_RESAMPLES`):
    distinct imported names, distinct canonical keys.

WHAT IT DELIBERATELY DOES NOT REPORT
    * `assert x is not None` guarding a real assertion. 238 such sites exist in
      this suite and all are treated as preconditions, because `<x>` is loaded
      again on a later line. That is the single largest class in the repo and
      flagging it would be the ~300-site false positive the brief named.
    * An assert reached through a helper being credited to every test that calls
      that helper. `assert_only()` is called by 113 tests; its one body assert is
      not 113 duplicated assertions. DUPLICATE_ASSERT therefore considers only
      asserts written in a test's OWN body.
    * `json.dumps(x, allow_nan=False)` as a no-assert test. The author wrote the
      failure condition as a keyword; the repo documents this in
      `_strictly_serializable` ("allow_nan=False is the assertion mechanism").

MODES
    advisory (default)  print the report, exit 0.
    --strict            exit 1 if any finding. For CI once the backlog is zero.

Advisory-first is deliberate: a gate with false positives gets deleted by the
next person who trips it. It advises loudly, and blocks only on request. CI
runs it advisory with `|| true` appended, so it cannot fail the build even if
someone later passes --strict by accident.

USAGE
    python scripts/check_test_assertions.py [ROOT] [--strict] [--json]
    ROOT defaults to <repo>/backend/tests.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

#: A call to anything named `assert*` is an assertion. Covers bare
#: `assert_...` helpers, `np.testing.assert_allclose`, `pd.testing.assert_frame_equal`,
#: and Mock's `assert_called_once_with`.
ASSERT_NAME_PREFIX = "assert"

#: Attribute names that assert without saying so.
ASSERT_ATTR_NAMES = frozenset({"raises", "warns", "fail"})

#: `raise AssertionError` -- excluded from coverage in backend/pyproject.toml,
#: so it is an established assertion idiom in this repo.
ASSERT_RAISED = frozenset({"AssertionError"})

#: The repo's own declared fail-if-NaN mechanism. `json.dumps` emits bare
#: `NaN`/`Infinity` by default and raises ONLY when told not to, so
#: `json.dumps(x, allow_nan=False)` is an assertion written as a keyword
#: argument. `_strictly_serializable` in test_p03_coint_collinear_refusal.py
#: says so in its own docstring: "`allow_nan=False` is the assertion
#: mechanism, not a helper." Keying on the keyword rather than on `json`
#: specifically also covers a hand-rolled `strict_dumps(payload, allow_nan=False)`.
ASSERT_KEYWORD = "allow_nan"
ASSERT_KEYWORD_VALUE = False

#: Guard on alias-chain resolution (`A = B = C = ...`), purely defensive.
MAX_ALIAS_DEPTH = 12

#: Guard on helper-call traversal, so a pathological/cyclic call graph in a
#: test file cannot hang the gate.
MAX_CALL_DEPTH = 12

RULE_NO_ASSERT = "NO_ASSERT"
RULE_IS_NOT_NONE = "IS_NOT_NONE_ONLY"
RULE_TAUTOLOGY = "TAUTOLOGY"
RULE_DUPLICATE = "DUPLICATE_ASSERT"

RULE_TITLES = {
    RULE_NO_ASSERT: "no assertion of any kind (directly or through a helper)",
    RULE_IS_NOT_NONE: "every assertion is `assert <x> is not None` and <x> is never used",
    RULE_TAUTOLOGY: "`assert A == B` where A and B resolve to the same module-level binding",
    RULE_DUPLICATE: "byte-identical `assert` shared with another test in this file",
}

#: Printed above the actionable block. Deliberately NOT "cannot fail": a test
#: with no assert still goes red if the code under test raises, so these are
#: tests whose PASS carries no information about values. NO_ASSERT means "no
#: assertion", not "unfailable"; the two are different claims and only the
#: first is one this gate can make statically.
ACTIONABLE_HEADER = (
    "ACTIONABLE -- no assertion, only-`is not None`, or a self-equal comparison.\n"
    "  A test listed here can still go red if the code under test raises. What\n"
    "  it cannot do is fail on a WRONG VALUE."
)


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    detail: str
    test: str
    related_lines: tuple[int, ...] = ()

    def render(self, root: Path) -> str:
        rel = os.path.relpath(self.path, root)
        extra = ""
        if self.related_lines:
            extra = "  [also: " + ", ".join(str(n) for n in self.related_lines) + "]"
        return f"{rel}:{self.line}: [{self.rule}] {self.test} -- {self.detail}{extra}"


@dataclass
class FileReport:
    path: str
    findings: list[Finding] = field(default_factory=list)
    test_count: int = 0
    parse_error: str = ""


# --------------------------------------------------------------------------
# Module index: one per .py file in the test tree
# --------------------------------------------------------------------------


class ModuleIndex:
    """Bindings visible at a module's top level, plus its top-level defs."""

    def __init__(self, path: Path, source: str) -> None:
        self.path = path
        self.source = source
        self.lines = source.splitlines()
        self.tree = ast.parse(source, filename=str(path))
        self.funcs: dict[str, ast.FunctionDef] = {}
        self.classes: dict[str, ast.ClassDef] = {}
        self.consts: dict[str, ast.expr] = {}
        #: name -> (module_dotted, original_name)   from `from M import a as b`
        self.from_imports: dict[str, tuple[str, str]] = {}
        #: name -> module_dotted                    from `import a.b as c`
        self.module_imports: dict[str, str] = {}
        #: name -> module_dotted                    from `from M import sub as a`
        self.submodule_imports: dict[str, str] = {}
        self.fixtures: dict[str, ast.FunctionDef] = {}
        self._build()

    # -- construction -------------------------------------------------------

    def _build(self) -> None:
        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.funcs[node.name] = node
                if _is_fixture(node):
                    self.fixtures[node.name] = node
            elif isinstance(node, ast.ClassDef):
                self.classes[node.name] = node
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if _is_fixture(sub):
                            self.fixtures.setdefault(sub.name, sub)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.consts[target.id] = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    self.consts[node.target.id] = node.value
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        self.module_imports[alias.asname] = alias.name
                    else:
                        head = alias.name.split(".")[0]
                        self.module_imports.setdefault(head, head)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for alias in node.names:
                    bound = alias.asname or alias.name
                    self.from_imports[bound] = (mod, alias.name)

    # -- helpers ------------------------------------------------------------

    def segment(self, node: ast.AST) -> str:
        """Raw source text of `node`, dedented and stripped."""
        lo = (node.lineno or 1) - 1
        hi = node.end_lineno or node.lineno or 1
        return textwrap.dedent("\n".join(self.lines[lo:hi])).strip()

    def methods(self, cls: ast.ClassDef) -> dict[str, ast.FunctionDef]:
        return {
            sub.name: sub
            for sub in cls.body
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
        }


def _is_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            func = dec.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in ("fixture", "fixture_async"):
                return True
        elif isinstance(dec, ast.Attribute) and dec.attr in ("fixture", "fixture_async"):
            return True
        elif isinstance(dec, ast.Name) and dec.id in ("fixture", "fixture_async"):
            return True
    return False


def _is_unittest_assert(name: str) -> bool:
    return name.startswith("assert") or name in ASSERT_ATTR_NAMES


def _pytest_expectation(name: str) -> bool:
    return name in ("raises", "warns")


# --------------------------------------------------------------------------
# Loader: parses the test tree once, memoised
# --------------------------------------------------------------------------


class TreeLoader:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._indexes: dict[str, ModuleIndex | None] = {}
        self._module_files: dict[str, Path | None] = {}
        self._conftests: dict[str, tuple[Path, ...]] = {}

    def files(self) -> list[Path]:
        return sorted(p for p in self.root.rglob("*.py") if "__pycache__" not in p.parts)

    def index(self, path: Path) -> ModuleIndex | None:
        # os.path.normcase+abspath, NOT Path.resolve(): resolve() stats the
        # filesystem on every call, and this lookup happens ~170k times per run.
        key = os.path.normcase(os.path.abspath(path))
        if key in self._indexes:
            return self._indexes[key]
        try:
            # utf-8-sig, not utf-8: two files in this tree carry a BOM, and
            # `ast.parse` rejects U+FEFF outright. pytest strips it via
            # importlib; skipping those files would silently under-count.
            source = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            self._indexes[key] = None
            return None
        try:
            idx = ModuleIndex(path, source)
        except SyntaxError:
            self._indexes[key] = None
            return None
        self._indexes[key] = idx
        return idx

    def module_file(self, dotted: str) -> Path | None:
        """`app.api.analytics` -> backend/app/api/analytics.py, or None.

        Used to decide whether a `from X import y` binding is a module object
        (`ca = context_audit`) or a symbol. A stat-only check: nothing is
        imported, so this stays a static reader.
        """
        if dotted in self._module_files:
            return self._module_files[dotted]
        rel = Path(*dotted.split("."))
        for candidate in (
            self.root.parent / rel.with_suffix(".py"),
            self.root.parent / rel / "__init__.py",
        ):
            if candidate.is_file():
                self._module_files[dotted] = candidate
                return candidate
        self._module_files[dotted] = None
        return None

    def test_tree_module_file(self, dotted: str, package: str) -> Path | None:
        """Resolve an import target that lives inside the test tree.

        Handles absolute (`tests.conftest`) and relative (`.helper`) forms, so
        `from .test_correlation_stability import _analyze` resolves to a file
        this gate can actually read.
        """
        key = f"{package}|{dotted}"
        if key in self._module_files:
            return self._module_files[key]
        rel_parts: list[str] = []
        if dotted:
            rel_parts = [p for p in dotted.split(".") if p]
        base = self.root if not package else self.root
        candidate = base.joinpath(*rel_parts) if rel_parts else base
        found: Path | None = None
        for suffix in (".py", "/__init__.py"):
            probe = Path(str(candidate) + suffix) if suffix == ".py" else candidate / "__init__.py"
            if probe.is_file() and probe != candidate:
                found = probe
                break
        self._module_files[key] = found
        return found


# --------------------------------------------------------------------------
# Assertion discovery
# --------------------------------------------------------------------------


@dataclass
class AssertionScan:
    """What one test function asserts, and how far we had to look to find out."""

    asserts: list[ast.Assert]
    has_other_assertion: bool  # anything that is not a bare `assert`
    helpers_reached: int
    #: asserts written in the test function's OWN body. Kept apart from
    #: `asserts` because a helper's internal assert is not "this test's assert":
    #: `test_debug_context_audit.py` has 113 tests calling `assert_only()`, whose
    #: single body assert would otherwise be attributed to all 113 as a
    #: duplicated assertion. Only `own_asserts` feeds the duplicate rule.
    own_asserts: list[ast.Assert] = field(default_factory=list)
    #: bare-name calls this gate could not tie to a definition in the test tree,
    #: recorded as `name`. Kept for the report; drives `assert_free_unresolved`.
    unresolved_callees: set[str] = field(default_factory=set)
    #: unresolved calls that COULD have been a test-tree assertion helper: bound
    #: by `from tests.x import y`, or bound nowhere this gate can see. A call into
    #: `app` or a library is the code under test and is not counted here.
    unresolved_test_tree_callees: set[str] = field(default_factory=set)
    #: (id(node), name) for every Name LOADED in the test body or in a helper it
    #: reaches. A name only ever STORED into is not a use -- that is what
    #: separates `x = f(); assert x is not None` from the same plus a later
    #: `assert x["k"] == 1`.
    name_uses: list[tuple[int, str]] = field(default_factory=list)
    #: ids of the Name nodes that were the subject of a collected `assert`, so an
    #: assert does not count as a use of its own subject.
    assert_subject_ids: set[int] = field(default_factory=set)
    #: bare `name(...)` calls with no definition this gate can read. Split by
    #: whether the name could plausibly be a test-tree assertion helper: an
    #: unresolved `np.array`/`some_service` is the code under test, but an
    #: unresolved name bound by `from tests.x import y` is a helper we failed to
    #: follow, and that is real uncertainty.
    unresolved_callees: set[str] = field(default_factory=set)
    unresolved_test_tree_callees: set[str] = field(default_factory=set)

    def dereferenced(self) -> set[str]:
        return {name for nid, name in self.name_uses if nid not in self.assert_subject_ids}


class AssertionFinder:
    def __init__(self, loader: TreeLoader, root: Path) -> None:
        self.loader = loader
        self.root = root
        self._local_defs_cache: dict[int, dict[str, ast.AST]] = {}

    # -- callable resolution ------------------------------------------------

    def is_plausible_helper(self, mod: ModuleIndex, name: str) -> bool:
        """Could `name` be a test-tree assertion helper we failed to follow?

        Conservative in the right direction. A name is plausible only if it is
        bound by a `from tests...` import, or if it is bound NOWHERE this gate
        can see -- an unbound name is a helper it could not index, or a builtin.
        A name bound by `from app... import x` / `import numpy as np` is the code
        under test, so it never counts.
        """
        binding = mod.from_imports.get(name)
        if binding is not None:
            return binding[0].startswith("tests") or binding[0].startswith(".")
        if name in mod.module_imports or name in mod.consts or name in mod.funcs:
            return False
        if name in mod.classes or name in mod.fixtures:
            return False
        return True

    def resolve_callee(self, mod: ModuleIndex, name: str) -> tuple[ModuleIndex, str] | None:
        """Map a bare `name(...)` call to `(owning module, definition name)`.

        Search order: the module's own functions/classes, then a same-package
        `conftest.py`, then any test-tree module this file imports the name
        from. Returns None when the callee is not readable -- which happens for
        every call into `app` or a third-party library. Those are the code under
        test, never the test's own assertion, so they are not treated as
        assertion carriers.
        """
        if name in mod.funcs:
            return (mod, name)
        if name in mod.classes:
            return (mod, name)
        for conftest in _conftests_above(self.loader, mod.path, self.root):
            cidx = self.loader.index(conftest)
            if cidx is not None and (name in cidx.funcs or name in cidx.classes):
                return (cidx, name)
        binding = mod.from_imports.get(name)
        if binding is not None:
            dotted, orig = binding
            if dotted.startswith("tests"):
                target = self.loader.test_tree_module_file(dotted, "")
                if target is not None and target != mod.path:
                    other = self.loader.index(target)
                    if other is not None and (orig in other.funcs or orig in other.classes):
                        return (other, orig)
        return None

    def _local_defs(self, func: ast.FunctionDef) -> dict[str, ast.AST]:
        """Nested defs/classes inside `func` -- they shadow module scope."""
        cached = self._local_defs_cache.get(id(func))
        if cached is not None:
            return cached
        found: dict[str, ast.AST] = {}
        for node in ast.walk(func):
            if node is func:
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found.setdefault(node.name, node)
        self._local_defs_cache[id(func)] = found
        return found

    # -- the scan -----------------------------------------------------------

    def scan(self, mod: ModuleIndex, func: ast.FunctionDef, owner: ast.ClassDef | None) -> AssertionScan:
        out = AssertionScan(asserts=[], has_other_assertion=False, helpers_reached=0)
        self._walk(mod, func, out, depth=0, owner=owner, locals_={})
        # Fixtures requested as parameters assert on the test's behalf too.
        for arg in _param_names(func):
            fixture = mod.fixtures.get(arg)
            if fixture is None:
                for conftest in _conftests_above(self.loader, mod.path, self.root):
                    cidx = self.loader.index(conftest)
                    if cidx is not None and arg in cidx.fixtures:
                        fixture = cidx.fixtures[arg]
                        break
            if fixture is not None:
                self._walk(mod, fixture, out, depth=0, owner=None, locals_={})
        return out

    def _walk(
        self,
        mod: ModuleIndex,
        func: ast.FunctionDef,
        out: AssertionScan,
        depth: int,
        owner: ast.ClassDef | None,
        locals_: dict[str, ast.AST],
    ) -> None:
        if depth > MAX_CALL_DEPTH:
            return
        local_defs = self._local_defs(func)
        local_defs.update(locals_)
        for node in ast.walk(func):
            if node is func or node in func.decorator_list:
                continue

            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                out.name_uses.append((id(node), node.id))

            if isinstance(node, ast.Assert):
                out.asserts.append(node)
                if depth == 0:
                    out.own_asserts.append(node)
                for sub in ast.walk(node.test):
                    if isinstance(sub, ast.Name):
                        out.assert_subject_ids.add(id(sub))
                continue

            if isinstance(node, ast.Raise) and node.exc is not None:
                exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
                name = _callee_name(exc)
                if name in ASSERT_RAISED:
                    out.has_other_assertion = True
                continue

            if isinstance(node, (ast.With, ast.AsyncWith)):
                if _any_with_assertion(node.items):
                    out.has_other_assertion = True
                continue

            if not isinstance(node, ast.Call):
                continue

            callee = node.func
            attr = callee.attr if isinstance(callee, ast.Attribute) else None
            if attr is not None:
                if attr.startswith(ASSERT_NAME_PREFIX):
                    out.has_other_assertion = True
                    continue
                if attr in ASSERT_ATTR_NAMES:
                    out.has_other_assertion = True
                    continue
                if _pytest_expectation(attr) and _root_is_pytest(callee.value):
                    out.has_other_assertion = True
                    continue
                if _declares_assertion(node):
                    out.has_other_assertion = True
                    continue
                if attr in ("wait_for", "gather", "create_task", "run", "sleep"):
                    self._walk_children(mod, node, out, depth, owner, local_defs)
                    continue
                # An attribute call is `obj.method()`: a client, a session, a
                # mock. Not a bare-name helper, so not chased. Its own callees
                # are still scanned below via the generic walk.
                self._walk_children(mod, node, out, depth, owner, local_defs)
                continue

            name = callee.id if isinstance(callee, ast.Name) else None
            if name is None:
                self._walk_children(mod, node, out, depth, owner, local_defs)
                continue
            if _declares_assertion(node):
                out.has_other_assertion = True
                continue
            if name.startswith("_") and name in local_defs:
                pass  # nested helper, handled below
            elif owner is not None and name in ("self", "cls"):
                self._walk_children(mod, node, out, depth, owner, local_defs)
                continue

            # 1. a nested def inside the test
            if name in local_defs and isinstance(local_defs[name], (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.helpers_reached += 1
                self._walk(
                    mod, local_defs[name], out, depth + 1, owner,
                    {k: v for k, v in local_defs.items() if k != name},
                )
                continue

            # 2. `self.helper()` / `cls.helper()` inside a test class
            if owner is not None and isinstance(callee, ast.Attribute):
                pass

            # 3. a module / conftest / sibling-test-module helper
            resolved = self.resolve_callee(mod, name)
            if resolved is None:
                out.unresolved_callees.add(name)
                if self.is_plausible_helper(mod, name):
                    out.unresolved_test_tree_callees.add(name)
                continue
            rmod, rname = resolved
            if rname in rmod.classes:
                continue  # a class instantiation is not an assertion carrier
            target = rmod.funcs.get(rname)
            if target is None:
                continue
            out.helpers_reached += 1
            self._walk(rmod, target, out, depth + 1, None, {})

    def _walk_children(
        self,
        mod: ModuleIndex,
        call: ast.Call,
        out: AssertionScan,
        depth: int,
        owner: ast.ClassDef | None,
        local_defs: dict[str, ast.AST],
    ) -> None:
        """Handle `self.helper()` / `obj.helper()` shapes."""
        callee = call.func
        if not isinstance(callee, ast.Attribute):
            return
        base = callee.value
        if owner is not None and isinstance(base, ast.Name) and base.id in ("self", "cls"):
            for cls in _enclosing_classes(owner):
                methods = self._methods_of(mod, cls)
                target = methods.get(callee.attr)
                if target is not None:
                    out.helpers_reached += 1
                    self._walk(mod, target, out, depth + 1, cls, {})

    def _methods_of(self, mod: ModuleIndex, cls: ast.ClassDef) -> dict[str, ast.FunctionDef]:
        return mod.methods(cls)


def _enclosing_classes(cls: ast.ClassDef) -> list[ast.ClassDef]:
    return [cls]


def _declares_assertion(call: ast.Call) -> bool:
    """True for `f(..., allow_nan=False)`.

    The author declaring that a NaN/Inf is a failure. In this repo that is
    literally documented as the assertion mechanism -- see
    `_strictly_serializable` in test_p03_coint_collinear_refusal.py.
    """
    for keyword in call.keywords:
        if keyword.arg != ASSERT_KEYWORD:
            continue
        value = keyword.value
        if isinstance(value, ast.Constant) and value.value is ASSERT_KEYWORD_VALUE:
            return True
    return False


def _any_with_assertion(items: list[ast.withitem]) -> bool:
    for item in items:
        ctx = item.context_expr
        target = ctx.func if isinstance(ctx, ast.Call) else ctx
        name = _callee_name(target)
        if name in ("raises", "warns") and _root_is_pytest(target):
            return True
        if name == "assertRaises" or (name or "").startswith("assertRaises"):
            return True
    return False


def _root_is_pytest(expr: ast.AST | None) -> bool:
    """True when the attribute chain roots at the name `pytest`."""
    node = expr
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name) and node.id == "pytest"


def _callee_name(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _param_names(func: ast.FunctionDef) -> list[str]:
    a = func.args
    names = [p.arg for p in a.posonlyargs + a.args]
    if a.vararg:
        names.append(a.vararg.arg)
    names += [p.arg for p in a.kwonlyargs]
    if a.kwarg:
        names.append(a.kwarg.arg)
    return names


def _conftests_above(loader: TreeLoader, path: Path, root: Path) -> list[Path]:
    key = os.path.normcase(os.path.abspath(path))
    if key in loader._conftests:
        return list(loader._conftests[key])
    found: list[Path] = []
    parent = path.parent
    while True:
        probe = parent / "conftest.py"
        if probe.is_file():
            found.append(probe)
        if parent == root or parent == root.parent:
            break
        parent = parent.parent
    loader._conftests[key] = tuple(found)
    return found


# --------------------------------------------------------------------------
# Canonical binding resolution (for the tautology rule)
# --------------------------------------------------------------------------


class BindingResolver:
    """Map an expression to the module-level constant it provably reads.

    Returns a `(module_dotted, attribute)` pair, or None when the expression is
    not a resolvable module-level binding. Requiring a *resolved* key on both
    sides is what keeps the rule honest: an unresolvable expression is never
    called a tautology, and two resolved keys are only equal when they name the
    same attribute of the same module.
    """

    def __init__(self, loader: TreeLoader, root: Path) -> None:
        self.loader = loader
        self.root = root

    def key(self, expr: ast.AST, mod: ModuleIndex) -> tuple[str, str] | None:
        return self._key(expr, mod, 0)

    def _key(self, expr: ast.AST, mod: ModuleIndex, depth: int) -> tuple[str, str] | None:
        if depth > MAX_ALIAS_DEPTH:
            return None
        if isinstance(expr, ast.Name):
            return self._name_key(expr.id, mod, depth)
        if isinstance(expr, ast.Attribute):
            module = self._module_object(expr.value, mod)
            if module is None:
                return None
            return (module, expr.attr)
        return None

    def _name_key(self, name: str, mod: ModuleIndex, depth: int) -> tuple[str, str] | None:
        if name in mod.consts:
            return self._key(mod.consts[name], mod, depth + 1)
        binding = mod.from_imports.get(name)
        if binding is None:
            return None
        dotted, orig = binding
        # `from app.api import analytics` binds a MODULE. `from app.api.analytics
        # import HOLDING_COVERED_DAYS_SCOPE` binds a CONSTANT of that module.
        # Both spellings end in `from ... import <name>`, so the only
        # discriminator is whether `<dotted>.<orig>` is itself a file on disk --
        # a stat, not an import.
        if self.loader.module_file(f"{dotted}.{orig}") is not None:
            return (f"{dotted}.{orig}", "<module>")
        return (dotted, orig)

    def _module_object(self, expr: ast.AST, mod: ModuleIndex) -> str | None:
        if not isinstance(expr, ast.Name):
            return None
        name = expr.id
        if name in mod.module_imports:
            return mod.module_imports[name]
        binding = mod.from_imports.get(name)
        if binding is None:
            return None
        dotted, orig = binding
        probe = f"{dotted}.{orig}"
        if self.loader.module_file(probe) is not None:
            return probe
        return None


# --------------------------------------------------------------------------
# The four rules
# --------------------------------------------------------------------------


def rule_is_not_none_only(mod: ModuleIndex, scan: AssertionScan) -> bool:
    """Every assertion is a bare `assert <x> is not None`, guarding nothing.

    Two conditions, both required:
      * the assert is exactly `X is not None` -- no message, no `and`-chain;
      * X's root name is never LOADED again anywhere in the test (or in a helper
        it reaches), so the value is never dereferenced and the assert is not a
        precondition for anything. The ~300 legitimate `assert x is not None`
        guards in this repo all fail this second condition, because the very
        next line indexes into x.
    """
    if not scan.asserts or scan.has_other_assertion:
        return False
    referenced = scan.dereferenced()
    for node in scan.asserts:
        if not is_is_not_none(node):
            return False
        assert isinstance(node.test, ast.Compare)
        root = _root_name(node.test.left)
        if root is None:
            return False  # `assert f() is not None` -- a real call, not this class
        if root in referenced:
            return False  # it is a precondition for a real use
    return True


def is_is_not_none(node: ast.Assert) -> bool:
    """Exactly `assert <x> is not None`: no message, no `and`-chain."""
    if node.msg is not None:
        return False
    test = node.test
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1):
        return False
    if not isinstance(test.ops[0], ast.IsNot):
        return False
    if not (len(test.comparators) == 1 and isinstance(test.comparators[0], ast.Constant)):
        return False
    return test.comparators[0].value is None


def _root_name(expr: ast.AST) -> str | None:
    node = expr
    while True:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            node = node.value
            continue
        return None


def rule_tautology(
    resolver: BindingResolver, mod: ModuleIndex, node: ast.Assert
) -> tuple[str, str] | None:
    """`assert A == B` where both sides resolve to the same constant binding."""
    test = node.test
    if node.msg is not None:
        return None
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1):
        return None
    if not isinstance(test.ops[0], ast.Eq):
        return None
    if len(test.comparators) != 1:
        return None
    left = resolver.key(test.left, mod)
    right = resolver.key(test.comparators[0], mod)
    if left is None or right is None or left != right:
        return None
    if left[1] == "<module>":
        return None
    return left, right


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


#: pytest's default `python_files`. A file outside these patterns is indexed for
#: helper resolution but never contributes test functions -- which is how
#: `conftest.py`'s `test_db` fixture stays out of the "test with no assert" count.
PYTEST_PYTHON_FILES = ("test_*.py", "*_test.py")


def is_test_module(path: Path) -> bool:
    import fnmatch

    name = path.name
    return any(fnmatch.fnmatch(name, pattern) for pattern in PYTEST_PYTHON_FILES)


def test_functions(index: ModuleIndex) -> list[tuple[ast.FunctionDef, ast.ClassDef | None]]:
    """Test functions pytest would collect: module-level `test_*` and methods
    of `Test*` classes. `python_classes` is not overridden in
    backend/pyproject.toml, so pytest's default `Test*` prefix applies."""
    found: list[tuple[ast.FunctionDef, ast.ClassDef | None]] = []
    if not is_test_module(index.path):
        return found
    for name, node in index.funcs.items():
        if name.startswith("test"):
            found.append((node, None))
    for node in index.tree.body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if sub.name.startswith("test"):
                        found.append((sub, node))
    found.sort(key=lambda pair: (pair[0].lineno or 0, pair[0].name))
    return found


def collect_uncounted_tests(index: ModuleIndex) -> int:
    """`test_*` methods on non-`Test*` classes. pytest never collects these, so
    they are excluded from every count below -- but a non-zero result means the
    suite has tests nobody runs, which is worth surfacing."""
    n = 0
    if not is_test_module(index.path):
        return n
    for node in index.tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("Test"):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name.startswith("test"):
                    n += 1
    return n


def analyse(root: Path) -> tuple[list[FileReport], dict[str, int]]:
    loader = TreeLoader(root)
    finder = AssertionFinder(loader, root)
    resolver = BindingResolver(loader, root)
    reports: list[FileReport] = []
    stats = {
        "files": 0,
        "test_functions": 0,
        "uncollected_test_methods": 0,
        "assert_free_provable": 0,
        "assert_free_unresolved": 0,
        "is_not_none_sites": 0,
    }

    for path in loader.files():
        index = loader.index(path)
        if index is None:
            report = FileReport(path=str(path), parse_error="unparseable or unreadable")
            reports.append(report)
            continue
        stats["files"] += 1
        stats["uncollected_test_methods"] += collect_uncounted_tests(index)

        report = FileReport(path=str(path))
        tests = test_functions(index)
        report.test_count = len(tests)
        stats["test_functions"] += len(tests)

        # rule 4 needs every test's assert sources before judging any one of them
        per_test_asserts: list[tuple[ast.FunctionDef, ast.ClassDef | None, AssertionScan]] = []
        for func, owner in tests:
            per_test_asserts.append((func, owner, finder.scan(index, func, owner)))

        dup_sites: dict[str, list[tuple[ast.Assert, ast.FunctionDef]]] = {}
        for func, _owner, scan in per_test_asserts:
            for node in scan.own_asserts:
                dup_sites.setdefault(index.segment(node), []).append((node, func))

        for func, owner, scan in per_test_asserts:
            qual = f"{func.name}()" if owner is None else f"{owner.name}::{func.name}()"
            stats["is_not_none_sites"] += sum(1 for a in scan.asserts if is_is_not_none(a))

            if not scan.asserts and not scan.has_other_assertion:
                # An unreadable callee means "I could not prove it", which is not
                # the same as "it has no assertion". It is counted separately.
                if scan.unresolved_test_tree_callees:
                    stats["assert_free_unresolved"] += 1
                report.findings.append(
                    Finding(
                        path=str(path),
                        line=func.lineno or 0,
                        rule=RULE_NO_ASSERT,
                        detail=(
                            "no assert, no pytest.raises/warns, no self.assert*, "
                            f"no assertion reached through {scan.helpers_reached} "
                            f"helper call(s); {len(scan.unresolved_test_tree_callees)} "
                            "unresolved callee name(s) in the test tree"
                        ),
                        test=qual,
                    )
                )
                stats["assert_free_provable"] += 1
            elif rule_is_not_none_only(index, scan):
                count = len(scan.asserts)
                report.findings.append(
                    Finding(
                        path=str(path),
                        line=scan.asserts[0].lineno or 0,
                        rule=RULE_IS_NOT_NONE,
                        detail=(
                            f"{count} assertion(s), every one of them "
                            "`is not None`, and the asserted value is never used"
                        ),
                        test=qual,
                    )
                )

            for node in scan.asserts:
                hit = rule_tautology(resolver, index, node)
                if hit is not None:
                    (module, attr), _ = hit
                    report.findings.append(
                        Finding(
                            path=str(path),
                            line=node.lineno or 0,
                            rule=RULE_TAUTOLOGY,
                            detail=f"both sides resolve to {module}.{attr}",
                            test=qual,
                        )
                    )

        for source, sites in sorted(dup_sites.items()):
            tests_seen: dict[tuple[int, str], ast.FunctionDef] = {}
            for node, func in sites:
                tests_seen.setdefault((func.lineno or 0, func.name), func)
            if len(tests_seen) < 2:
                continue
            ordered = sorted(sites, key=lambda pair: (pair[0].lineno or 0, pair[1].lineno or 0))
            lines = tuple(sorted({n.lineno or 0 for n, _ in ordered}))
            first_node, first_func = ordered[0]
            report.findings.append(
                Finding(
                    path=str(path),
                    line=first_node.lineno or 0,
                    rule=RULE_DUPLICATE,
                    detail=(
                        "byte-identical assert written in the body of "
                        f"{len(tests_seen)} tests in this file, e.g. "
                        f"`{source.splitlines()[0]}`"
                    ),
                    test=first_func.name,
                    related_lines=lines[1:],
                )
            )

        report.findings.sort(key=lambda f: (f.line, f.rule))
        if report.findings:
            reports.append(report)

    return reports, stats


def render(reports: list[FileReport], stats: dict[str, int], root: Path) -> str:
    out: list[str] = []
    actionable = (RULE_NO_ASSERT, RULE_IS_NOT_NONE, RULE_TAUTOLOGY)
    total = sum(len(r.findings) for r in reports)

    def emit(rules: tuple[str, ...], title: str) -> None:
        rows = [
            f for r in reports for f in r.findings if f.rule in rules
        ]
        if not rows:
            return
        out.append("")
        out.append("-" * 78)
        out.append(title)
        for report in reports:
            for finding in report.findings:
                if finding.rule in rules:
                    out.append("  " + finding.render(root))

    out.append("=" * 78)
    out.append("static test-assertion gate (advisory)")
    out.append(f"root: {root}")
    out.append("=" * 78)
    emit(actionable, ACTIONABLE_HEADER)
    emit(
        (RULE_DUPLICATE,),
        "INVENTORY -- byte-identical asserts shared between tests in one file.\n"
        "  Usually a deliberate shared idiom rather than a defect; listed in full\n"
        "  because the count is the point, not because every line needs action.",
    )

    out.append("")
    out.append("-" * 78)
    out.append("findings by rule")
    for rule in (RULE_NO_ASSERT, RULE_IS_NOT_NONE, RULE_TAUTOLOGY, RULE_DUPLICATE):
        n = sum(1 for r in reports for f in r.findings if f.rule == rule)
        out.append(f"  {rule:<16} {n:>4}   {RULE_TITLES[rule]}")
    out.append(f"  {'TOTAL':<16} {total:>4}")
    out.append("")
    out.append("measurement")
    out.append(f"  files scanned                        {stats['files']:>6}")
    out.append(f"  test functions scanned               {stats['test_functions']:>6}")
    out.append(
        f"  test functions with NO assert        {stats['assert_free_provable']:>6}"
        "   <- the number nobody had"
    )
    out.append(
        f"  ...of those, reaching an unreadable  {stats['assert_free_unresolved']:>6}"
        "   (callee name this gate could not tie to source)"
    )
    out.append(
        f"  `assert x is not None` sites in tests {stats['is_not_none_sites']:>6}"
        "   <- the precondition class, correctly NOT flagged"
    )
    out.append(
        f"  test_* methods pytest does not collect{stats['uncollected_test_methods']:>6}"
        "   (test_* method on a non-Test* class)"
    )
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Self-assertion: this script must stay a static reader
# --------------------------------------------------------------------------


def assert_is_static_reader() -> None:
    """Fail loudly if this file ever imports pytest or the app under test."""
    src = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"pytest", "app", "main", "pandas", "numpy", "httpx", "fastapi", "sqlalchemy"}
    offending = sorted(imported & forbidden)
    if offending:
        raise SystemExit(
            "check_test_assertions.py must stay a static reader; it now imports: "
            + ", ".join(offending)
        )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def default_root() -> Path:
    return Path(__file__).resolve().parent.parent / "backend" / "tests"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report test functions that cannot fail (advisory by default)."
    )
    parser.add_argument("root", nargs="?", type=Path, default=None, help="test tree to scan")
    parser.add_argument("--strict", action="store_true", help="exit 1 when any finding exists")
    parser.add_argument("--json", action="store_true", help="also emit findings as JSON")
    args = parser.parse_args(argv)

    assert_is_static_reader()

    root = (args.root or default_root()).resolve()
    if not root.is_dir():
        print(f"error: no such directory: {root}", file=sys.stderr)
        return 2

    reports, stats = analyse(root)
    total = sum(len(r.findings) for r in reports)
    print(render(reports, stats, root))

    if args.json:
        payload = [
            {
                "file": os.path.relpath(f.path, root),
                "line": f.line,
                "rule": f.rule,
                "test": f.test,
                "detail": f.detail,
                "related_lines": list(f.related_lines),
            }
            for r in reports
            for f in r.findings
        ]
        print(json.dumps(payload, indent=2, sort_keys=True))

    if args.strict and total:
        print(
            f"strict: {total} finding(s). --strict is OFF by default in CI; the "
            "advisory step is there so the backlog drains first.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())