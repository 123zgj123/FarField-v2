"""Which modules the runtime can actually reach, as a checkable fact.

The recurring failure in this codebase is a claim that outlived its
implementation. The capability register makes that checkable for behaviour.
This makes it checkable for *code*: a module no entry point can reach is a
paragraph, however confident its docstring, and the docstrings here were
confident — a control arm that "is the baseline the v2 generator must beat", a
registry of "registered drift/judge operators", a scorer that fixes a defect in
an arm nothing runs.

The walk starts at real entry points and follows imports, so a module kept
alive only by its own tests does not count as reached. Orphans are declared
below with a reason, which turns two different events into two different
failures: a module falling off the path is a surprise, and an orphan being
rewired or removed is a stale declaration.
"""

from __future__ import annotations

import ast
from collections import deque
from pathlib import Path
from typing import Any


# The surfaces this repository ships. `research` is the openworld runtime,
# `cli` the legacy pipeline still exposed as commands, `evaluation` the
# harnesses that grade the runtime without being part of it.
ENTRY_POINTS: dict[str, tuple[str, ...]] = {
    "research": ("farfield.extras.openworld.runtime",),
    "cli": ("farfield.cli", "farfield.__main__"),
    "evaluation": (
        "farfield.extras.openworld.capabilities",
        "farfield.extras.openworld.benchmark",
        "farfield.extras.openworld.trajectory_eval",
        "farfield.extras.openworld.reachability",
    ),
}

# Modules no entry point reaches, and why each is still here. A reason of
# "legacy" is not an excuse: it is a statement that the module's docstring must
# not describe itself in the present tense as part of a running system.
DECLARED_ORPHANS: dict[str, str] = {
    "farfield": "package root; reached by every dotted import rather than by one",
    "farfield.worker": "deliberate tombstone: fails leftover scripts with a named reason",
    "farfield.adapters": "rendering helpers for a handoff the research runtime does not perform",
    "farfield.drift": "pre-openworld graph-walk generator, kept as a measured control arm "
                      "for a comparison nothing currently runs",
    "farfield.novelty": "evaluator-side pair scoring for that same control comparison",
    "farfield.operators": "operator registry for the drift arm",
    "farfield.portfolio": "diversity scheduler for the pre-openworld candidate pool",
    "farfield.probe": "falsifiability checks for drift cards, superseded by "
                      "extras/probeexp.py on the research path",
    "farfield.rank": "two-term plausibility/alienness score proposed for the drift arm",
    "farfield.extras.benchloop": "campaign harness for the drift-vs-v2 comparison",
}


def _module_name(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _index(root: Path) -> dict[str, Path]:
    return {_module_name(path, root): path for path in root.rglob("*.py")}


def _imports(path: Path, module: str, known: dict[str, Path]) -> set[str]:
    """Every module in this package that this file imports, relative or absolute."""
    found: set[str] = set()
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                climb = node.level - 1
                parts = parts[: len(parts) - climb] if climb else parts
                target = ".".join(parts + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            found.add(target)
            # `from x import y` may name a module rather than an attribute.
            found.update(f"{target}.{alias.name}" for alias in node.names)
    return {name for name in found if name in known}


def reachable(root: Path | None = None) -> dict[str, Any]:
    """Modules each entry point reaches, and the ones nothing does."""
    root = Path(root or Path(__file__).resolve().parents[2])
    known = _index(root)
    by_surface: dict[str, set[str]] = {}
    for surface, entries in ENTRY_POINTS.items():
        seen: set[str] = set()
        queue = deque(entries)
        while queue:
            module = queue.popleft()
            if module in seen or module not in known:
                continue
            seen.add(module)
            queue.extend(dep for dep in _imports(known[module], module, known)
                         if dep not in seen)
        by_surface[surface] = seen
    live: set[str] = set().union(*by_surface.values()) if by_surface else set()
    return {
        "rule": "import-reachability-v1",
        "modules": len(known),
        "by_surface": {name: sorted(found) for name, found in by_surface.items()},
        "reachable": sorted(live),
        "orphans": sorted(set(known) - live),
        "declared_orphans": dict(DECLARED_ORPHANS),
        "undeclared_orphans": sorted(set(known) - live - set(DECLARED_ORPHANS)),
        "stale_declarations": sorted(set(DECLARED_ORPHANS) & live),
        "basis": "static imports from real entry points; a module kept alive only "
                 "by its own tests is not reached",
    }


# ---------------------------------------------------------------------------
# Event vocabulary
# ---------------------------------------------------------------------------

# Event types the reducer handles that no production code emits. Each branch is
# a state transition the runtime can perform and never asks for, so each needs a
# reason — and the reason must not be "we might one day", which is how
# `TheorySupported` came to accept a belief assertion backed by no evidence at
# all, inside the single writer.
DECLARED_UNEMITTED: dict[str, str] = {
    "TheorySupported": "belief is derived from admitted evidence; this branch now "
                       "only records an evidence link and refuses a bare assertion",
    "TheoryWeakened": "as TheorySupported",
    "TheoryContradicted": "as TheorySupported",
    "DebtUpdated": "debt is derived and recomputed after every batch, so this "
                   "branch cannot change anything; kept for old logs",
    "ReviewRepairRefused": "the refusal counter is written by ReviewResolved; this "
                           "would double-count it",
    "ContradictionDetected": "for a contradiction the runtime cannot derive, such as "
                             "one with verified literature; nothing reports one yet",
    "ContractAmended": "amendment path exercised by tests only; no worker amends a "
                       "contract mid-project",
    "QuestionBlocked": "the reducer blocks questions directly inside other branches",
    "LineageMerged": "lineages fork and retire; nothing merges them",
    "WorldDeprecated": "no path deprecates an attested world",
    "CapabilityProposed": "harness capability lifecycle, status partial in the register",
    "CapabilityTrusted": "as CapabilityProposed",
    "CapabilityRevoked": "as CapabilityProposed",
    "CapabilityDeprecated": "as CapabilityProposed",
    "HarnessAdmitted": "as CapabilityProposed",
    "DecisionRecorded": "the decision journal is written directly by the pivot "
                        "branch; no tick records why it chose what it chose",
}


def _emitted_types(root: Path) -> dict[str, list[str]]:
    """Event types constructed anywhere under `root`, by AST rather than by grep.

    A regex over `make_event("X"` misses every call that wraps its arguments
    onto the next line, which is most of the interesting ones.
    """
    found: dict[str, set[str]] = {}
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in {"make_event", "Event"}:
                continue
            kind = None
            if node.args and isinstance(node.args[0], ast.Constant):
                kind = node.args[0].value
            for keyword in node.keywords:
                if keyword.arg in {"event_type", "kind"} and isinstance(
                        keyword.value, ast.Constant):
                    kind = keyword.value.value
            if isinstance(kind, str):
                found.setdefault(kind, set()).add(str(path))
    return {kind: sorted(paths) for kind, paths in found.items()}


def event_vocabulary(root: Path | None = None) -> dict[str, Any]:
    """Declared event types against what emits them and what reduces them."""
    import re

    from .events import EVENT_TYPES

    root = Path(root or Path(__file__).resolve().parents[2])
    reducer = (root / "extras/openworld/reducer.py").read_text(encoding="utf-8")
    branches = set(re.findall(r'kind == "([A-Za-z]+)"', reducer))
    emitted = _emitted_types(root)
    declared = set(EVENT_TYPES)
    return {
        "rule": "event-vocabulary-v1",
        "declared": sorted(declared),
        "emitted": {kind: paths for kind, paths in sorted(emitted.items())},
        "reduced": sorted(branches),
        "emitted_without_a_reducer_branch": sorted(set(emitted) - branches),
        "reduced_without_a_declaration": sorted(branches - declared),
        "emitted_but_undeclared": sorted(set(emitted) - declared),
        "unemitted": sorted(declared & branches - set(emitted)),
        "undeclared_unemitted": sorted(
            declared & branches - set(emitted) - set(DECLARED_UNEMITTED)),
        "stale_unemitted_declarations": sorted(set(DECLARED_UNEMITTED) & set(emitted)),
    }
