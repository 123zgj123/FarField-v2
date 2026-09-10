"""A module no entry point can reach is a paragraph, not a capability.

Ninety-five kilobytes of this repository describe themselves in the present
tense as parts of a running system — a control arm the v2 generator "must
beat", a registry of "registered" operators, a scorer that fixes a defect in an
arm — and no entry point reaches any of it. That is the same failure the
capability register exists to catch, one level down: a claim nobody executes.

This does not delete anything. It makes the orphan list a declared fact, so a
module falling off the path fails as a surprise and an orphan being rewired
fails as a stale declaration.
"""

import unittest

from farfield.extras.openworld.reachability import (
    DECLARED_ORPHANS,
    ENTRY_POINTS,
    reachable,
)


class ReachabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = reachable()

    def test_no_module_falls_off_the_path_unnoticed(self):
        self.assertEqual(
            self.report["undeclared_orphans"], [],
            "these modules are reachable from no entry point; either wire them "
            "in, delete them, or declare them in DECLARED_ORPHANS with a reason")

    def test_no_orphan_declaration_outlives_its_orphan(self):
        self.assertEqual(
            self.report["stale_declarations"], [],
            "these are declared as orphans and are in fact reachable; remove "
            "the declaration so the list keeps meaning something")

    def test_the_research_runtime_reaches_what_it_claims_to_use(self):
        research = set(self.report["by_surface"]["research"])
        for module in ("farfield.extras.citations", "farfield.extras.workid",
                       "farfield.extras.explore", "farfield.extras.sources",
                       "farfield.extras.openworld.exploration",
                       "farfield.extras.openworld.scheduler",
                       "farfield.extras.openworld.reducer"):
            with self.subTest(module=module):
                self.assertIn(module, research)

    def test_every_entry_point_resolves(self):
        for surface, entries in ENTRY_POINTS.items():
            with self.subTest(surface=surface):
                reached = self.report["by_surface"][surface]
                self.assertTrue(reached, f"{surface} reaches nothing")
                for entry in entries:
                    self.assertIn(entry, reached)

    def test_every_declared_orphan_says_why_it_is_still_here(self):
        for name, reason in DECLARED_ORPHANS.items():
            with self.subTest(module=name):
                self.assertGreater(len(reason.split()), 4,
                                   "a reason short enough to be a shrug")

    def test_an_orphan_says_so_where_a_reader_will_see_it(self):
        """The declaration is in one file; the reader is in another.

        Every one of these opened with a confident present-tense sentence
        about its role in a running system. A reader who opens drift.py has
        no reason to check a reachability table first.
        """
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "src"
        for name in DECLARED_ORPHANS:
            if name in {"farfield", "farfield.worker"}:
                continue  # package root; tombstone that already says it
            path = root / (name.replace(".", "/") + ".py")
            with self.subTest(module=name):
                self.assertTrue(path.is_file(), path)
                doc = ast.get_docstring(ast.parse(path.read_text())) or ""
                self.assertIn("NOT ON ANY PATH THE RUNTIME EXECUTES", doc)

    def test_the_trusted_kernel_is_on_the_research_path(self):
        """A kernel nothing reaches guards nothing."""
        from farfield.extras.openworld.kernel import TRUSTED_KERNEL_FILES

        research = set(self.report["by_surface"]["research"])
        for path in TRUSTED_KERNEL_FILES:
            module = path.removeprefix("src/").removesuffix(".py").replace("/", ".")
            with self.subTest(module=module):
                self.assertIn(module, research)


if __name__ == "__main__":
    unittest.main()
