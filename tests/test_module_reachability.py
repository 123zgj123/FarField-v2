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


class EventVocabularyTest(unittest.TestCase):
    """An event nothing emits is a state transition nobody asks for.

    Sixteen of thirty-nine declared event types are emitted by no production
    code, and one of them — `TheorySupported` — accepted a bare assertion that
    a hypothesis was supported, wrote it onto the row, and survived the derived
    refresh because that refresh only overwrites a status when admitted
    evidence exists. A hypothesis could be believed on the strength of nothing,
    through the single writer, inside the trusted kernel.
    """

    @classmethod
    def setUpClass(cls):
        from farfield.extras.openworld.reachability import event_vocabulary

        cls.vocab = event_vocabulary()

    def test_every_emitted_event_has_a_reducer_branch(self):
        self.assertEqual(self.vocab["emitted_without_a_reducer_branch"], [],
                         "these are constructed and then change no state")

    def test_every_emitted_event_is_declared(self):
        self.assertEqual(self.vocab["emitted_but_undeclared"], [])

    def test_every_reducer_branch_is_declared(self):
        self.assertEqual(self.vocab["reduced_without_a_declaration"], [])

    def test_no_unemitted_branch_goes_undeclared(self):
        self.assertEqual(
            self.vocab["undeclared_unemitted"], [],
            "these reducer branches are reachable by no emitter; declare each "
            "in DECLARED_UNEMITTED with a reason, or remove the branch")

    def test_no_declaration_outlives_its_silence(self):
        self.assertEqual(self.vocab["stale_unemitted_declarations"], [],
                         "declared as unemitted and in fact emitted")


class DerivedBeliefTest(unittest.TestCase):
    """Belief follows evidence. No event may shortcut that."""

    def state(self):
        from farfield.extras.openworld.events import make_event
        from farfield.extras.openworld.reducer import apply_events
        from farfield.extras.openworld.state import ScientificState

        root = "does X improve Y in Z?"
        return apply_events(ScientificState(goal=root), [
            make_event("ContractSet", {"root_question": root}),
            make_event("QuestionCreated", {"id": "Q1", "text": root}),
            make_event("TheoryCreated", {"id": "T1", "question_id": "Q1", "text": "m"}),
        ])

    def apply(self, state, kind, payload):
        from farfield.extras.openworld.events import make_event
        from farfield.extras.openworld.reducer import apply_events

        return apply_events(state, [make_event(kind, payload)])

    def test_a_bare_belief_assertion_changes_no_belief(self):
        for kind in ("TheorySupported", "TheoryWeakened", "TheoryContradicted"):
            with self.subTest(event=kind):
                after = self.apply(self.state(), kind, {"id": "T1"})
                theory = after.theories[0]
                self.assertIsNone(theory.get("status"),
                                  "a hypothesis was believed on the strength of nothing")
                self.assertEqual(
                    int(after.metrics.get(
                        "belief_assertion_without_evidence_refused") or 0), 1)

    def test_a_belief_event_cannot_conjure_a_hypothesis(self):
        after = self.apply(self.state(), "TheorySupported", {"id": "nobody"})
        self.assertEqual([row.get("id") for row in after.theories], ["T1"])
        self.assertEqual(
            int(after.metrics.get("belief_event_for_unknown_hypothesis_refused") or 0), 1)

    def test_an_evidence_link_is_still_recorded(self):
        after = self.apply(self.state(), "TheorySupported",
                           {"id": "T1", "evidence_id": "E1"})
        self.assertEqual(after.theories[0].get("evidence_ids"), ["E1"])
        self.assertIsNone(after.theories[0].get("status"),
                          "a link is not a verdict; derivation decides")

    def test_debt_cannot_be_set_by_an_event(self):
        """It is derived after every batch, so the payload is discarded."""
        before = dict(self.state().debt)
        after = self.apply(self.state(), "DebtUpdated",
                           {"debt": {"contradiction_debt": 999, "quality_gap": 0}})
        self.assertEqual(dict(after.debt), before)
