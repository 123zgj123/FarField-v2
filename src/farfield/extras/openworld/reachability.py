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
