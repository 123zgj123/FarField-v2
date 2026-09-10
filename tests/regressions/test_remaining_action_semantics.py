"""The three actions the earlier audits had not opened: ASK, ACQUIRE, EVOLVE_HARNESS.

None of them turned out to be broken. Recording that is the point: a sweep that
only writes down the defects it finds leaves the reader unable to tell what was
examined from what was skipped.
"""

import tempfile
import unittest
from pathlib import Path

from farfield.extras.openworld import DEFAULT_EXECUTORS, EVOLVE_HARNESS, OpenWorld
from farfield.extras.openworld.actions import SPECS, eligible_actions
from farfield.extras.openworld.events import make_event
from farfield.extras.openworld.reducer import apply_events
from farfield.extras.openworld.state import ScientificState

ROOT = "does retrieval augmentation improve factual accuracy in long-context models?"


def base():
    return apply_events(ScientificState(goal=ROOT),
                        [make_event("ContractSet", {"root_question": ROOT})])


def offered(state):
    return {item.action_type for item in eligible_actions(
        state, capabilities=(), workers_connected=True)}


class AskTest(unittest.TestCase):
    """ASK asks the root question, once, and then never again.

    Its executor writes `action.target or state.goal` as the new question's
    text, so if it were offered while questions already existed it would keep
    minting duplicates of the goal and each one would look like progress.
    """

    def test_ask_bootstraps_the_first_question(self):
        self.assertIn("ASK", offered(base()))

    def test_ask_is_not_offered_once_a_question_exists(self):
        for kind in ("QuestionCreated", "QuestionResolved", "QuestionBlocked"):
            with self.subTest(existing=kind):
                state = apply_events(base(), [
                    make_event("QuestionCreated", {"id": "Q1", "text": ROOT})])
                if kind != "QuestionCreated":
                    state = apply_events(state, [make_event(kind, {"id": "Q1"})])
                self.assertNotIn("ASK", offered(state),
                                 "a second ASK would duplicate the root question")

    def test_the_first_question_is_the_root_question(self):
        state = base()
        action = next(item for item in eligible_actions(
            state, capabilities=(), workers_connected=True)
            if item.action_type == "ASK")
        result = DEFAULT_EXECUTORS["ASK"](OpenWorld(workspace=None), action)
        self.assertEqual(result.events[0].payload["text"], ROOT)
        self.assertEqual(result.events[0].payload["epistemic"], "GENERATED")


class AcquireTest(unittest.TestCase):
    def test_acquire_is_offered_only_against_a_named_missing_capability(self):
        state = base()
        self.assertNotIn("ACQUIRE", offered(state))
        state = apply_events(state, [
            make_event("QuestionCreated", {"id": "Q1", "text": ROOT,
                                           "required_capability": "world:tabular"})])
        self.assertIn("ACQUIRE", offered(state))


class EvolveHarnessTest(unittest.TestCase):
    """A harness patch is proposed during research and installed by nobody."""

    def test_evolve_without_a_pathology_does_nothing(self):
        env = OpenWorld(workspace=None)
        self.assertEqual(env.evolve()["status"], "no_pathology")

    def test_evolve_harness_has_no_executor_and_is_handled_directly(self):
        spec = SPECS[EVOLVE_HARNESS]
        self.assertNotIn(EVOLVE_HARNESS, DEFAULT_EXECUTORS)
        self.assertNotIn(spec.executor, DEFAULT_EXECUTORS)

    def test_a_research_time_patch_is_never_installed(self):
        with tempfile.TemporaryDirectory() as workspace:
            env = OpenWorld(workspace=Path(workspace))
            before = env.harness.version_id
            env.evolve()
            self.assertEqual(env.harness.version_id, before,
                             "research may propose a harness change, not install one")


if __name__ == "__main__":
    unittest.main()
