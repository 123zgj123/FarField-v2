"""Guarantees that only appear over a long trajectory.

A controller can answer every single-decision scenario correctly and still fail
over thirty actions: abandon a direction it never tried, pivot in a loop, lose
the root question, or spend its whole budget on the cheapest available action.
These run the real controller against a scripted world and assert the
properties that hold across the whole run.
"""

import tempfile
import unittest
from pathlib import Path

from farfield.extras.openworld.trajectory_eval import (
    DEAD_SCRIPT,
    HARD_SCRIPT,
    ROOT,
    run_trajectory,
)


CONTRACT = {"target_quality": "workshop",
            "resource_limits": {"api_calls": 40, "min_sample_size": 100}}


class LongHorizonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        cls.recoverable = run_trajectory(
            root / "recoverable", root_question=ROOT, probe_script=HARD_SCRIPT,
            horizon=30, contract=CONTRACT)
        cls.dead = run_trajectory(
            root / "dead", root_question=ROOT, probe_script=DEAD_SCRIPT,
            horizon=30, contract=CONTRACT)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_root_question_survives_the_whole_trajectory(self):
        for name, run in (("recoverable", self.recoverable), ("dead", self.dead)):
            with self.subTest(trajectory=name):
                self.assertEqual(run.root_question, ROOT)

    def test_the_state_replays_from_its_own_event_log(self):
        for name, run in (("recoverable", self.recoverable), ("dead", self.dead)):
            with self.subTest(trajectory=name):
                self.assertTrue(run.replay_ok)

    def test_no_objection_is_ever_closed_by_prose(self):
        for name, run in (("recoverable", self.recoverable), ("dead", self.dead)):
            with self.subTest(trajectory=name):
                self.assertEqual(run.metrics["caveat_only_repair_rate"], 0.0)
                for review in run.reviews:
                    if review.get("status") == "resolved" and review.get("requires_new_evidence"):
                        self.assertIn(review.get("resolution_kind"),
                                      {"new_world_evidence", "new_valid_experiment",
                                       "replication", "baseline_improvement",
                                       "measurement_repair", "design_repair"})

    def test_the_project_never_drifts_off_its_root_question(self):
        for name, run in (("recoverable", self.recoverable), ("dead", self.dead)):
            with self.subTest(trajectory=name):
                self.assertEqual(run.metrics["goal_drift_rate"], 0.0)

    def test_a_direction_is_never_abandoned_before_it_is_tried(self):
        for name, run in (("recoverable", self.recoverable), ("dead", self.dead)):
            with self.subTest(trajectory=name):
                first_pivot = run.metrics["time_to_project_pivot"]
                if first_pivot is None:
                    continue
                tried = [a for a in run.actions[:first_pivot]
                         if a in {"PROBE", "VERIFY", "OBSERVE"}]
                self.assertTrue(tried, "pivoted before running any experiment")

    def test_a_dead_direction_is_actually_abandoned(self):
        self.assertIsNotNone(self.dead.metrics["time_to_project_pivot"],
                             "never gave up on a direction where every arm measured nothing")

    def test_a_pivot_does_not_loop(self):
        """Pivot, pivot, pivot is not backtracking; it is a livelock."""
        for name, run in (("recoverable", self.recoverable), ("dead", self.dead)):
            with self.subTest(trajectory=name):
                for index in range(len(run.actions) - 1):
                    if run.actions[index] == "PROJECT_PIVOT":
                        self.assertNotEqual(run.actions[index + 1], "PROJECT_PIVOT")

    def test_a_retired_hypothesis_is_never_resurrected_by_belief_refresh(self):
        run = self.dead
        self.assertGreaterEqual(run.metrics["branch_retirement_precision"], 1)

    def test_an_experiment_is_actually_reached(self):
        """The most important action type must not vanish from a whole run."""
        for name, run in (("recoverable", self.recoverable), ("dead", self.dead)):
            with self.subTest(trajectory=name):
                self.assertIn("PROBE", run.actions)

    def test_evidence_that_was_admitted_is_decision_relevant(self):
        self.assertGreaterEqual(self.recoverable.metrics["decision_relevant_evidence_yield"], 1)

    def test_neither_run_claims_to_be_finished_research(self):
        for name, run in (("recoverable", self.recoverable), ("dead", self.dead)):
            with self.subTest(trajectory=name):
                self.assertNotEqual(run.readiness, "RESEARCH_READY")


if __name__ == "__main__":
    unittest.main()


class TrajectoryEfficiencyTest(unittest.TestCase):
    """Most of a long run must be spent on work that informs the next decision.

    These thresholds are floors measured against the current controller, not
    targets. They exist so a change that quietly reintroduces idle ticks — an
    action that always succeeds and changes nothing — fails visibly.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.trajectory = run_trajectory(
            Path(cls._tmp.name) / "recoverable", root_question=ROOT,
            probe_script=HARD_SCRIPT, horizon=30, contract=CONTRACT)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_idle_ticks_stay_a_minority_of_the_run(self):
        idle = self.trajectory.metrics["low_value_activity"]
        self.assertLessEqual(
            idle, len(self.trajectory.actions) // 2,
            f"{idle} of {len(self.trajectory.actions)} actions changed nothing")

    def test_the_run_reaches_several_experiments_not_one(self):
        self.assertGreaterEqual(self.trajectory.actions.count("PROBE"), 2)

    def test_evidence_yield_per_call_does_not_collapse(self):
        self.assertGreaterEqual(self.trajectory.metrics["resource_efficiency"], 0.1)

    def test_the_same_failure_is_not_repeated(self):
        self.assertEqual(self.trajectory.metrics["same_failure_repetition"], 0)

    def test_no_action_type_is_run_into_the_ground(self):
        """No single action may dominate the run; that is spinning, not research."""
        from collections import Counter

        counts = Counter(self.trajectory.actions)
        top, count = counts.most_common(1)[0]
        self.assertLessEqual(count, len(self.trajectory.actions) // 2,
                             f"{top} took {count} of {len(self.trajectory.actions)} actions")
