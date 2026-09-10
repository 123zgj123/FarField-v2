"""The register must be able to fail, and every claim must demonstrate itself.

The defects this codebase kept producing were not broken functions. They were
claims that outlived their implementation: a contradiction tracker whose only
writer was an event nobody emitted, a budget filter reading two keys nothing
wrote, a quality bar demanding a sample size no worker reported, a module still
calling itself the production path long after it left. Every one was described
in prose, believed, and never asked to demonstrate itself.

These tests are what asks.
"""

import ast
import unittest
from pathlib import Path

from farfield.extras.openworld.capabilities import (
    ABSENT,
    IMPLEMENTED,
    PARTIAL,
    REGISTER,
    STATUSES,
    audit,
    register,
)


ROOT = Path(__file__).resolve().parents[2]


class RegisterShapeTest(unittest.TestCase):
    def test_every_capability_names_an_implementation_that_exists(self):
        for capability in REGISTER:
            for module in capability.implemented_by:
                with self.subTest(capability=capability.name, module=module):
                    self.assertTrue((ROOT / "src/farfield/extras" / module).is_file(),
                                    f"{capability.name} points at a module that is not there")

    def test_every_capability_names_a_test_that_exists(self):
        for capability in REGISTER:
            self.assertTrue(capability.enforced_by,
                            f"{capability.name} names no enforcing test")
            for path in capability.enforced_by:
                with self.subTest(capability=capability.name, test=path):
                    self.assertTrue((ROOT / path).is_file(),
                                    f"{capability.name} points at a test that is not there")

    def test_statuses_are_from_the_declared_vocabulary(self):
        for capability in REGISTER:
            self.assertIn(capability.status, STATUSES)
            self.assertIn(capability.validated, {"offline", "live"})

    def test_names_are_unique(self):
        names = [capability.name for capability in REGISTER]
        self.assertEqual(len(names), len(set(names)))

    def test_a_claim_states_what_it_claims(self):
        for capability in REGISTER:
            self.assertGreater(len(capability.claim), 30,
                               f"{capability.name} does not say what it claims")


class LivePathTest(unittest.TestCase):
    """Every claimed capability has to fire against a real state."""

    def test_the_audit_passes(self):
        report = audit()
        self.assertTrue(report["ok"], report["live_path_failures"])

    def test_each_implemented_capability_fires_individually(self):
        for capability in REGISTER:
            if capability.status != IMPLEMENTED:
                continue
            with self.subTest(capability=capability.name):
                self.assertIsNotNone(
                    capability.live_path,
                    f"{capability.name} claims implemented with no live-path check")
                self.assertTrue(capability.live_path(),
                                f"{capability.name} is claimed but does not fire")

    def test_a_partial_or_absent_capability_states_its_limits(self):
        for capability in REGISTER:
            if capability.status in {PARTIAL, ABSENT}:
                with self.subTest(capability=capability.name):
                    self.assertTrue(capability.limits.strip(),
                                    f"{capability.name} is {capability.status} and says nothing "
                                    "about what is missing")

    def test_the_audit_actually_fails_when_a_claim_stops_holding(self):
        """A check that cannot fail is the thing this register exists to prevent."""
        import farfield.extras.openworld.capabilities as caps
        from dataclasses import replace

        broken = replace(REGISTER[0], live_path=lambda: False)
        original = caps.REGISTER
        try:
            caps.REGISTER = (broken,) + original[1:]
            report = caps.audit()
        finally:
            caps.REGISTER = original
        self.assertFalse(report["ok"])
        self.assertIn(broken.name, report["live_path_failures"])

    def test_the_audit_fails_an_implemented_claim_with_no_probe(self):
        import farfield.extras.openworld.capabilities as caps
        from dataclasses import replace

        unchecked = replace(REGISTER[0], live_path=None, status=IMPLEMENTED)
        original = caps.REGISTER
        try:
            caps.REGISTER = (unchecked,)
            report = caps.audit()
        finally:
            caps.REGISTER = original
        self.assertFalse(report["ok"])
        self.assertIn("no live-path check", " ".join(report["live_path_failures"]))


class NoResurrectedGhostsTest(unittest.TestCase):
    """The specific dead reads that made claims unkeepable must stay dead."""

    GHOSTS = {
        "spent_cost": "the budget filter read it and nothing wrote it",
        "budget_cap": "the budget filter read it and nothing wrote it",
        "working_archive": "archive_debt was always zero",
        "causal_identification_ready": "a second probe-readiness path nothing supplied",
        "high_impact": "high-impact verification debt could never be raised",
    }

    @staticmethod
    def _read_keys(path):
        """Keys actually read from a row: ``x.get("k")`` and ``x["k"]``.

        Matched on the parse tree, not on the file text — the modules explain
        these ghosts in their docstrings, and a prose mention is not a read.
        """
        tree = ast.parse(path.read_text(encoding="utf-8"))
        keys = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                keys.add(node.args[0].value)
            if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
                    and isinstance(node.slice.value, str)
                    and isinstance(node.ctx, ast.Load)):
                keys.add(node.slice.value)
        return keys

    def test_no_decision_reads_a_field_nothing_writes(self):
        for path in (ROOT / "src/farfield/extras/openworld").glob("*.py"):
            keys = self._read_keys(path)
            for ghost, why in self.GHOSTS.items():
                with self.subTest(module=path.name, field=ghost):
                    self.assertNotIn(ghost, keys,
                                     f"{path.name} reads {ghost!r} again: {why}")

    def test_contradiction_tracking_has_a_writer_that_runs(self):
        """Its only writers were an event nobody emitted and a helper nobody called."""
        source = (ROOT / "src/farfield/extras/openworld/state.py").read_text()
        self.assertIn("def refresh_contradictions", source)
        tree = ast.parse(source)
        called = {node.func.id for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertIn("refresh_contradictions", called,
                      "refresh_contradictions is defined but never called")


if __name__ == "__main__":
    unittest.main()
