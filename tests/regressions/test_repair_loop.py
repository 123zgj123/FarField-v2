"""A design revision must become an experiment, or it is a note.

A live segment with a doubled budget produced four DesignRevisions, every one
recording "new WORLD evidence that settles X; prose cannot close this", and ran
exactly one experiment. Nothing converted a revision into a hypothesis, so the
project could not act on its own diagnosis and the repair loop ended at a note.
The behavioural scenarios did not catch it: they assert that REDESIGN is
*chosen*, never that it *leads to a repaired design*.
"""

import tempfile
import unittest
from pathlib import Path

from farfield.extras.openworld.actions import REPAIR_OPERATOR, repair_actions
from farfield.extras.openworld.benchmark import (
    make_env, seed_probe_evidence, seed_question, seed_review, seed_survey, seed_theory,
)
from farfield.extras.openworld.events import make_event
from farfield.extras.openworld.reducer import apply_events, rebuild_state, state_digest


ROOT = "does petal geometry separate iris species better than sepal geometry?"


class RepairBecomesAnExperimentTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = make_env(Path(self._tmp.name) / "p", contract={"root_question": ROOT})
        seed_question(self.env, "Q1", ROOT)
        seed_survey(self.env, "Q1")
        seed_theory(self.env, "T1", "Q1")
        seed_survey(self.env, "Q1", theory_id="T1")
        seed_probe_evidence(self.env, "E1", "T1", "Q1", sample_size=500,
                            ablation_required=True, cannot_corroborate=True)
        seed_review(self.env, review_id="R1", severity="major",
                    dimension="baseline_strength",
                    objection="a competing mechanism is not ablated",
                    repair_type="stronger_baseline", requires_new_evidence=True,
                    theory_id="T1", question_id="Q1")

    def tearDown(self):
        self._tmp.cleanup()

    def _redesign(self):
        action = next(a for a in self.env.eligible() if a.action_type == "REDESIGN")
        return self.env.execute(action)["revision"]

    def test_a_revision_opens_an_obligation_to_carry_it_out(self):
        self.assertEqual(repair_actions(self.env.state), [])
        self._redesign()
        actions = repair_actions(self.env.state)
        self.assertTrue(actions, "a revision produced no obligation to act on it")
        self.assertEqual(actions[0].action_type, "THEORIZE")
        self.assertEqual(actions[0].reason, "carry_out_design_revision")

    def test_the_obligation_carries_the_diagnosis_not_just_a_retry(self):
        revision = self._redesign()
        extra = repair_actions(self.env.state)[0].extra
        self.assertEqual(extra["revision_id"], revision["revision_id"])
        self.assertEqual(extra["repair"], revision["selected_repair"])
        self.assertTrue(extra["failure_root_cause"])
        self.assertTrue(extra["early_kill_condition"])
        self.assertTrue(extra["changed_components"])

    def test_the_repair_names_the_transformation_that_changes_it(self):
        revision = self._redesign()
        extra = repair_actions(self.env.state)[0].extra
        self.assertEqual(extra["repair_operator"],
                         REPAIR_OPERATOR[revision["selected_repair"]])

    def test_the_obligation_is_on_the_controller_menu(self):
        """THEORIZE eligibility belongs to the worker path, so the repair has to
        reach the menu there — that is where a live run would look for it."""
        class Stub:
            client = None

            def executors(self):
                return {}

        self._redesign()
        self.env.connect_workers(Stub())
        theorize = [a for a in self.env.eligible()
                    if a.action_type == "THEORIZE" and a.extra.get("revision_id")]
        self.assertTrue(theorize, "the repair never reached the eligible actions")
        self.assertEqual(theorize[0].extra["transition_kind"], "design_repair")

    def test_each_repair_type_maps_to_a_transformation(self):
        from farfield.extras.openworld.quality import REDESIGN_REPAIRS

        for repair in REDESIGN_REPAIRS | {"stronger_baseline", "broader_evaluation"}:
            with self.subTest(repair=repair):
                self.assertIn(repair, REPAIR_OPERATOR)


class RevisionLifecycleTest(unittest.TestCase):
    """Four revisions accumulated at `open` because nothing closed them."""

    def _state(self, *events):
        env = make_env(Path(tempfile.mkdtemp()) / "p", contract={"root_question": ROOT})
        seed_question(env, "Q1", ROOT)
        env.state = apply_events(env.state, [
            make_event("DesignRevised", {
                "revision_id": "rev-1", "dimension": "baseline_strength",
                "selected_repair": "stronger_baseline", "parent_design": "T1",
                "outcome": "open"}),
            *events], log=env.log)
        return env

    def test_a_revision_nothing_carried_out_stays_open(self):
        env = self._state()
        self.assertEqual(env.state.design_revisions[0]["outcome"], "open")

    def test_a_revision_a_hypothesis_carries_becomes_attempted(self):
        env = self._state(make_event("TheoryCreated", {
            "id": "T2", "question_id": "Q1", "text": "repaired", "revision_id": "rev-1"}))
        row = env.state.design_revisions[0]
        self.assertEqual(row["outcome"], "attempted")
        self.assertEqual(row["carried_out_by"], ["T2"])

    def test_a_revision_whose_child_produced_evidence_is_settled(self):
        env = self._state(make_event("TheoryCreated", {
            "id": "T2", "question_id": "Q1", "text": "repaired", "revision_id": "rev-1"}))
        seed_probe_evidence(env, "E2", "T2", "Q1", sample_size=500)
        self.assertEqual(env.state.design_revisions[0]["outcome"], "settled")

    def test_an_attempted_revision_is_not_offered_again(self):
        env = self._state(make_event("TheoryCreated", {
            "id": "T2", "question_id": "Q1", "text": "repaired", "revision_id": "rev-1"}))
        self.assertEqual(repair_actions(env.state), [])

    def test_the_lifecycle_replays_from_the_event_log(self):
        env = self._state(make_event("TheoryCreated", {
            "id": "T2", "question_id": "Q1", "text": "repaired", "revision_id": "rev-1"}))
        self.assertEqual(state_digest(env.state), state_digest(rebuild_state(env.log)))
        self.assertEqual(rebuild_state(env.log).design_revisions[0]["outcome"], "attempted")

    def test_a_pivot_does_not_leave_last_epochs_revisions_open(self):
        env = self._state()
        env.state = apply_events(env.state, [make_event("ProjectPivoted", {"reason": "dead"})],
                                 log=env.log)
        self.assertEqual(repair_actions(env.state), [],
                         "a retired epoch's revision was offered in the new one")


if __name__ == "__main__":
    unittest.main()


class RepairTargetsAHypothesisThatExistsTest(unittest.TestCase):
    """A live repair reached the menu and was refused as a lineage mismatch.

    Quality-gap demands carry no hypothesis, so the revision recorded the
    dimension name in `parent_design`, and the repair hop then pointed at a
    hypothesis id the state did not hold. The branch worker was right to refuse
    it; the defect was upstream.
    """

    def _env(self):
        env = make_env(Path(tempfile.mkdtemp()) / "p", contract={"root_question": ROOT})
        seed_question(env, "Q1", ROOT)
        seed_survey(env, "Q1")
        seed_theory(env, "T1", "Q1")
        seed_probe_evidence(env, "E1", "T1", "Q1", sample_size=500,
                            ablation_required=True, cannot_corroborate=True)
        return env

    def test_a_quality_gap_revision_does_not_name_a_dimension_as_its_parent(self):
        env = self._env()
        action = next(a for a in env.eligible()
                      if a.action_type == "REDESIGN"
                      and (a.extra.get("demand") or {}).get("kind") == "quality_gap")
        revision = env.execute(action)["revision"]
        self.assertNotIn(revision["parent_design"],
                         {"baseline_strength", "mechanism_support", "technical_correctness"})

    def test_every_repair_points_at_a_hypothesis_the_state_holds(self):
        env = self._env()
        for action in [a for a in env.eligible() if a.action_type == "REDESIGN"][:2]:
            env.execute(action)
        known = {str(row.get("id") or "") for row in env.state.theories}
        for repair in repair_actions(env.state):
            parent = str(repair.extra.get("parent_theory_id") or "")
            with self.subTest(revision=repair.extra.get("revision_id")):
                self.assertTrue(not parent or parent in known,
                                f"repair points at {parent!r}, which is not a hypothesis")

    def test_the_repair_hop_matches_what_the_branch_worker_requires(self):
        """hop must be the parent's hop + 1, and the parent must own the question."""
        env = self._env()
        env.execute(next(a for a in env.eligible() if a.action_type == "REDESIGN"))
        for repair in repair_actions(env.state):
            parent = next((t for t in env.state.theories
                           if t.get("id") == repair.extra.get("parent_theory_id")), None)
            with self.subTest(revision=repair.extra.get("revision_id")):
                self.assertIsNotNone(parent)
                self.assertEqual(repair.extra["hop"], int(parent.get("hop") or 1) + 1)
                self.assertEqual(parent.get("question_id"), repair.target)
