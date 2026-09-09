"""Every action should tell the project something it did not already know.

The failures these guard against all look like success: an action runs, reports
"ok", and leaves the state exactly as it was. Over a long run that is most of
the budget.
"""

import tempfile
import unittest
from pathlib import Path

from farfield.extras.openworld.actions import (
    SPECS, ActionInstance, action_input_key, information_precondition,
)
from farfield.extras.openworld.benchmark import (
    make_env, seed_probe_evidence, seed_question, seed_review, seed_survey, seed_theory,
)
from farfield.extras.openworld.events import make_event
from farfield.extras.openworld.progress import measure_progress
from farfield.extras.openworld.reducer import apply_events
from farfield.extras.openworld.state import ScientificState


ROOT = "Does retrieval augmentation improve factual accuracy of small language models?"


class RetryKeyTest(unittest.TestCase):
    """A retry needs the action's own inputs to change, not the world's."""

    def setUp(self):
        self.state = ScientificState(goal=ROOT, world_id="W0")
        self.state.world_versions.append({"id": "W0", "world_id": "W0", "digest": "d0"})
        self.state.add_question(question_id="Q1", text=ROOT)
        self.reflect = ActionInstance(SPECS["REFLECT"], reason="recent_events")

    def test_unrelated_state_changes_do_not_make_an_action_retryable(self):
        before = action_input_key(self.state, self.reflect)
        after = apply_events(self.state, [make_event("EvidenceAdded", {
            "evidence_id": "E1", "role": "ProbeEvidence", "epistemic": "GENERATED"})])
        self.assertEqual(before, action_input_key(after, self.reflect),
                         "an unrelated evidence row made REFLECT look untried again")

    def test_the_inputs_an_action_declares_do_make_it_retryable(self):
        before = action_input_key(self.state, self.reflect)
        after = apply_events(self.state, [make_event("ActionFailed", {
            "theory_id": "T1", "reason": "the measure never moved"})])
        self.assertNotEqual(before, action_input_key(after, self.reflect))

    def test_observation_retries_when_the_world_changes_not_when_a_theory_does(self):
        observe = ActionInstance(SPECS["OBSERVE"], target="Q1", frontier_target_id="Q1")
        base = action_input_key(self.state, observe)
        theorized = apply_events(self.state, [make_event("TheoryCreated", {
            "id": "T1", "question_id": "Q1", "text": "m"})])
        self.assertEqual(base, action_input_key(theorized, observe))
        rebound = apply_events(self.state, [make_event("WorldCreated", {
            "id": "W1", "world_id": "W1", "digest": "d1"})])
        self.assertNotEqual(base, action_input_key(rebound, observe))


class InertRepetitionTest(unittest.TestCase):
    """A known answer is not worth re-reading."""

    def _attempts(self, state, kind, target, outcome, times, admitted=0, epoch=0):
        return apply_events(state, [make_event("ArtifactAdded", {
            "kind": "action_attempt", "action_type": kind, "target": target,
            "outcome_key": outcome, "events_admitted": admitted,
            "project_epoch": epoch, "input_key": f"{kind}-{target}-{index}"})
            for index in range(times)])

    def setUp(self):
        self.state = apply_events(ScientificState(goal=ROOT),
                                  [make_event("ContractSet", {"root_question": ROOT})])
        self.action = ActionInstance(SPECS["OBSERVE"], target="Q1", frontier_target_id="Q1")

    def test_one_blocked_attempt_is_information_and_is_allowed_again(self):
        state = self._attempts(self.state, "OBSERVE", "Q1", "NO_DATA", 1)
        self.assertEqual(information_precondition(state, self.action), "")

    def test_the_same_outcome_twice_is_established_and_refused(self):
        state = self._attempts(self.state, "OBSERVE", "Q1", "NO_DATA", 2)
        self.assertIn("already_established", information_precondition(state, self.action))

    def test_an_attempt_that_admitted_something_is_never_counted_inert(self):
        state = self._attempts(self.state, "OBSERVE", "Q1", "observed", 3, admitted=1)
        self.assertEqual(information_precondition(state, self.action), "")

    def test_a_different_outcome_is_a_different_fact(self):
        state = self._attempts(self.state, "OBSERVE", "Q1", "NO_DATA", 1)
        state = self._attempts(state, "OBSERVE", "Q1", "WORLD_INCOMPATIBLE", 1)
        self.assertEqual(information_precondition(state, self.action), "")

    def test_a_pivot_lifts_what_the_retired_direction_established(self):
        state = self._attempts(self.state, "OBSERVE", "Q1", "NO_DATA", 2, epoch=0)
        self.assertIn("already_established", information_precondition(state, self.action))
        state = apply_events(state, [make_event("ProjectPivoted", {"reason": "dead"})])
        self.assertEqual(information_precondition(state, self.action), "")


class NoOpPreconditionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = make_env(Path(self._tmp.name) / "p")
        seed_question(self.env, "Q1", ROOT)
        seed_survey(self.env, "Q1")
        seed_theory(self.env, "T1", "Q1")

    def tearDown(self):
        self._tmp.cleanup()

    def test_reflection_needs_something_that_has_failed(self):
        action = ActionInstance(SPECS["REFLECT"], reason="recent_events")
        self.assertIn("nothing_has_failed", information_precondition(self.env.state, action))

    def test_reflection_is_refused_once_every_failure_has_a_lesson(self):
        self.env.state = apply_events(self.env.state, [make_event("ActionFailed", {
            "theory_id": "T1", "reason": "the measure never moved"})], log=self.env.log)
        action = ActionInstance(SPECS["REFLECT"], reason="recent_events")
        self.assertEqual(information_precondition(self.env.state, action), "")
        self.env.execute(action)
        self.assertIn("already_has_a_lesson",
                      information_precondition(self.env.state, action))

    def test_reflection_actually_records_the_lesson_rather_than_reporting_success(self):
        self.env.state = apply_events(self.env.state, [make_event("ActionFailed", {
            "theory_id": "T1", "reason": "the measure never moved"})], log=self.env.log)
        self.env.execute(ActionInstance(SPECS["REFLECT"], reason="recent_events"))
        lessons = [row for row in self.env.state.artifacts if row.get("kind") == "failure_lesson"]
        self.assertTrue(lessons)
        self.assertTrue(lessons[0]["applies_when"])
        self.assertTrue(lessons[0]["does_not_apply_when"])

    def test_a_repeated_failure_becomes_an_anomaly_the_controller_can_act_on(self):
        for index in range(2):
            self.env.state = apply_events(self.env.state, [make_event("ActionFailed", {
                "theory_id": "T1", "reason": "the measure never moved",
                "attempt": index})], log=self.env.log)
        result = self.env.execute(ActionInstance(SPECS["REFLECT"], reason="recent_events"))
        self.assertTrue(result["repeated_failures"])
        self.assertTrue([row for row in self.env.state.artifacts if row.get("kind") == "anomaly"])

    def test_archiving_records_what_it_closed_and_then_stops(self):
        self.env.state = apply_events(self.env.state, [make_event(
            "QuestionResolved", {"id": "Q1"})], log=self.env.log)
        action = ActionInstance(SPECS["ARCHIVE"], reason="closed_or_negative_result")
        self.assertEqual(information_precondition(self.env.state, action), "")
        self.env.execute(action)
        self.assertTrue([row for row in self.env.state.artifacts
                         if row.get("kind") == "archive_record"])
        self.assertIn("already_records_this_set",
                      information_precondition(self.env.state, action))

    def test_review_stops_once_every_design_carries_an_objection(self):
        seed_probe_evidence(self.env, "E1", "T1", "Q1", sample_size=6)
        action = next(a for a in self.env.eligible() if a.action_type == "REVIEW")
        self.assertEqual(information_precondition(self.env.state, action), "")
        self.env.execute(action)
        self.assertIn("already_carries_a_review",
                      information_precondition(self.env.state, action))

    def test_redrafting_does_not_close_an_evidence_gap(self):
        seed_probe_evidence(self.env, "E1", "T1", "Q1", sample_size=6)
        self.env.state = apply_events(self.env.state, [make_event("ArtifactAdded", {
            "kind": "research_synthesis", "id": "syn-1", "evidence_id": "E1"})],
            log=self.env.log)
        action = ActionInstance(SPECS["SYNTHESIZE"], reason="evidence_or_theory")
        self.assertIn("redraft", information_precondition(self.env.state, action))


class ProgressCreditTest(unittest.TestCase):
    """Real advancement must be credited, or the agent looks idle while working."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = make_env(Path(self._tmp.name) / "p")
        seed_question(self.env, "Q1", ROOT)

    def tearDown(self):
        self._tmp.cleanup()

    def test_advancing_a_dimension_short_of_the_bar_still_counts(self):
        before = ScientificState.from_dict(self.env.state.to_dict())
        seed_survey(self.env, "Q1")
        progress = measure_progress(before, self.env.state)
        self.assertGreaterEqual(progress.quality_dimension_progress, 1)
        self.assertTrue(progress.research_meaningful)

    def test_discovering_a_serious_flaw_is_research_progress(self):
        seed_survey(self.env, "Q1")
        seed_theory(self.env, "T1", "Q1")
        before = ScientificState.from_dict(self.env.state.to_dict())
        seed_review(self.env, review_id="RF1", severity="fatal",
                    dimension="measurement_validity", objection="the measure is blind",
                    repair_type="measurement_redesign", requires_new_evidence=True)
        progress = measure_progress(before, self.env.state)
        self.assertEqual(progress.objection_discovery, 1)
        self.assertTrue(progress.research_meaningful)

    def test_learning_a_design_does_not_work_is_information_once(self):
        before = ScientificState.from_dict(self.env.state.to_dict())
        self.env.state = apply_events(self.env.state, [make_event("ActionFailed", {
            "action_type": "PROBE", "theory_id": "T1", "reason": "no handle"})],
            log=self.env.log)
        first = measure_progress(before, self.env.state)
        self.assertEqual(first.failure_information, 1)
        middle = ScientificState.from_dict(self.env.state.to_dict())
        self.env.state = apply_events(self.env.state, [make_event("ActionFailed", {
            "action_type": "PROBE", "theory_id": "T1", "reason": "no handle"})],
            log=self.env.log)
        second = measure_progress(middle, self.env.state)
        self.assertEqual(second.failure_information, 0)
        self.assertEqual(second.same_failure_repetition, 1)
        self.assertFalse(second.research_meaningful)


if __name__ == "__main__":
    unittest.main()
