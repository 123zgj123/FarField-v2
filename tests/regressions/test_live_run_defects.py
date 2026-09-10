"""Four defects a bounded live run exposed that a green suite did not.

Each of these produced a wrong research decision against a real model and a
real attested world, and none of them was reachable from the offline scenarios:
they need an actual descriptive observation, an actual executed probe, and an
actual experiment script that never reported its own sample size.
"""

import tempfile
import unittest
from pathlib import Path

from farfield.extras.openworld.actions import SPECS, ActionInstance, information_precondition
from farfield.extras.openworld.benchmark import (
    make_env, seed_probe_evidence, seed_question, seed_survey, seed_theory,
)
from farfield.extras.openworld.events import make_event
from farfield.extras.openworld.executors import _structural_objections
from farfield.extras.openworld.quality import compute_quality
from farfield.extras.openworld.reducer import apply_events


ROOT = "does petal geometry separate iris species better than sepal geometry?"

DESCRIPTIVE = {
    "evidence_id": "obs-1", "role": "QuestionEvidence", "epistemic": "WORLD",
    "attested": True, "promotion_ok": True, "question_id": "Q1", "world_id": "W0",
    "world_digest": "d0", "outcome": "PARTIALLY_RESOLVED", "exploratory": True,
    # A descriptive observation carries this by construction.
    "cannot_corroborate": True,
    "interpretation": "Dataset descriptives; the research question remains open.",
}


class DescriptiveObservationIsNotADefect(unittest.TestCase):
    """F1: reading an honest exploratory label as a validation failure asked for
    a redesign of a design that did not exist yet."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = make_env(Path(self._tmp.name) / "p", contract={"root_question": ROOT})
        seed_question(self.env, "Q1", ROOT)
        seed_survey(self.env, "Q1")
        seed_theory(self.env, "T1", "Q1")
        self.env.state = apply_events(self.env.state,
                                      [make_event("EvidenceAdded", DESCRIPTIVE)],
                                      log=self.env.log)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_descriptive_observation_does_not_make_the_work_technically_wrong(self):
        row = compute_quality(self.env.state)["dimensions"]["technical_correctness"]
        self.assertEqual(row["status"], "unknown")
        self.assertNotIn("REDESIGN", row["required_next_work"])

    def test_no_redesign_is_demanded_before_any_experiment_exists(self):
        self.assertNotIn("REDESIGN", {a.action_type for a in self.env.eligible()})

    def test_an_executed_experiment_with_real_gaps_still_counts(self):
        seed_probe_evidence(self.env, "E1", "T1", "Q1", sample_size=500,
                            cannot_corroborate=True, validation_gaps=["oracle_sanity_failed"])
        self.assertEqual(
            compute_quality(self.env.state)["dimensions"]["technical_correctness"]["status"],
            "weak")


class SampleSizeIsReachable(unittest.TestCase):
    """F4: nothing in the pipeline reported sample size, so experimental
    adequacy could never leave 'weak' — an unreachable bar that would drive
    endless redesign for reasons that have nothing to do with the science."""

    def test_an_experiment_may_report_what_it_measured(self):
        from farfield.extras.openworld.workers import _reported_sample

        class World:
            root = Path(".")
        row = _reported_sample({"n_treatment": 60, "n_control": 60}, None)
        self.assertEqual(row["sample_size"], 60)
        self.assertIn("reported_by_the_registered_experiment", row["sample_size_basis"])

    def test_the_smaller_arm_is_the_sample_size(self):
        from farfield.extras.openworld.workers import _reported_sample

        self.assertEqual(_reported_sample({"n_treatment": 90, "n_control": 12}, None)["sample_size"], 12)

    def test_an_unreported_count_stays_honestly_absent(self):
        from farfield.extras.openworld.workers import _reported_sample

        row = _reported_sample({"treatment": 1.0, "control": 2.0}, None)
        self.assertIsNone(row["sample_size"])
        self.assertIn("not_reported", row["sample_size_basis"])

    def test_a_negative_or_non_integer_count_is_not_a_sample_size(self):
        from farfield.extras.openworld.workers import _reported_sample

        for bad in ({"n_treatment": -1, "n_control": 5}, {"n_treatment": 1.5, "n_control": 5},
                    {"n_treatment": True, "n_control": 5}):
            with self.subTest(metrics=bad):
                self.assertIsNone(_reported_sample(bad, None)["sample_size"])

    def test_the_world_size_is_a_bound_not_the_sample(self):
        """A 150-row table measured twenty rows has n=20. Reading the bound as
        the sample would overstate power."""
        from farfield.extras.openworld.workers import _reported_sample

        row = _reported_sample({"n_treatment": 20, "n_control": 20}, None)
        self.assertEqual(row["sample_size"], 20)

    def test_a_report_larger_than_the_attested_world_is_refused(self):
        from farfield.extras.openworld.workers import _reported_sample

        class Fixture:
            pass
        import farfield.extras.openworld.worldio as worldio
        original = worldio.summarize
        worldio.summarize = lambda world: {"n_rows": 150}
        try:
            row = _reported_sample({"n_treatment": 10 ** 6, "n_control": 10 ** 6}, Fixture())
        finally:
            worldio.summarize = original
        self.assertIsNone(row["sample_size"])
        self.assertIn("refused", row["sample_size_basis"])

    def test_a_reported_sample_actually_clears_the_dimension(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = make_env(Path(tmp) / "p", contract={"root_question": ROOT})
            seed_question(env, "Q1", ROOT)
            seed_survey(env, "Q1")
            seed_theory(env, "T1", "Q1")
            seed_probe_evidence(env, "E1", "T1", "Q1", sample_size=500,
                                sample_size_basis="reported_by_the_registered_experiment")
            self.assertEqual(
                compute_quality(env.state)["dimensions"]["experimental_adequacy"]["status"],
                "adequate")


class OneDefectIsOneObjection(unittest.TestCase):
    """F3: an unablated result produced two objections, one of them with an
    empty body, because cannot_corroborate was set with no validation gap."""

    def _state(self, **extra):
        env = make_env(Path(tempfile.mkdtemp()) / "p", contract={"root_question": ROOT})
        seed_question(env, "Q1", ROOT)
        seed_survey(env, "Q1")
        seed_theory(env, "T1", "Q1")
        seed_probe_evidence(env, "E1", "T1", "Q1", **{"sample_size": 500, **extra})
        return env.state

    def test_no_objection_is_ever_recorded_with_an_empty_body(self):
        state = self._state(cannot_corroborate=True, ablation_required=True)
        for row in _structural_objections(state):
            if row.get("assessment"):
                continue
            self.assertTrue(str(row.get("objection") or "").strip(),
                            f"{row['review_id']} has no stated reason")

    def test_a_missing_ablation_is_one_complaint_not_two(self):
        state = self._state(cannot_corroborate=True, ablation_required=True)
        rows = [r for r in _structural_objections(state) if not r.get("assessment")]
        self.assertIn("review-ablation-E1", {r["review_id"] for r in rows})
        self.assertNotIn("review-validity-E1", {r["review_id"] for r in rows})

    def test_a_real_validation_gap_still_raises_its_own_fatal_objection(self):
        state = self._state(cannot_corroborate=True,
                            validation_gaps=["oracle_sanity_execution_failed"])
        row = next(r for r in _structural_objections(state)
                   if r["review_id"] == "review-validity-E1")
        self.assertEqual(row["severity"], "fatal")
        self.assertIn("oracle_sanity_execution_failed", row["objection"])

    def test_an_unexplained_refusal_says_that_it_is_unexplained(self):
        state = self._state(cannot_corroborate=True)
        row = next(r for r in _structural_objections(state)
                   if r["review_id"] == "review-validity-E1")
        self.assertIn("reason was not recorded", row["objection"])

    def test_the_power_objection_names_the_repair_that_can_work(self):
        state = self._state(sample_size=None)
        row = next(r for r in _structural_objections(state)
                   if r["review_id"] == "review-power-E1")
        self.assertIn("n_treatment", row["objection"])
        self.assertEqual(row["repair_type"], "measurement_redesign")


class ReviewNeedsSomethingToSay(unittest.TestCase):
    """F2: a live tick was spent reviewing a hypothesis with no evidence behind
    it, and came back with no_new_objections."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = make_env(Path(self._tmp.name) / "p", contract={"root_question": ROOT})
        seed_question(self.env, "Q1", ROOT)
        seed_survey(self.env, "Q1")
        seed_theory(self.env, "T1", "Q1")
        self.action = ActionInstance(SPECS["REVIEW"], target="Q1", frontier_target_id="Q1")

    def tearDown(self):
        self._tmp.cleanup()

    def test_review_is_refused_with_nothing_to_object_to(self):
        self.assertIn("nothing_to_add", information_precondition(self.env.state, self.action))

    def test_review_opens_once_an_experiment_has_run(self):
        seed_probe_evidence(self.env, "E1", "T1", "Q1", sample_size=6)
        self.assertEqual(information_precondition(self.env.state, self.action), "")

    def test_review_closes_again_once_it_has_said_everything(self):
        seed_probe_evidence(self.env, "E1", "T1", "Q1", sample_size=6)
        self.env.execute(next(a for a in self.env.eligible() if a.action_type == "REVIEW"))
        self.assertIn("nothing_to_add", information_precondition(self.env.state, self.action))

    def test_drift_alone_is_enough_for_a_reviewer_to_speak(self):
        self.env.state = apply_events(self.env.state, [make_event(
            "QuestionCreated", {"id": "Q9", "text": "how should token overlap be scored?"})],
            log=self.env.log)
        self.assertEqual(information_precondition(self.env.state, self.action), "")


if __name__ == "__main__":
    unittest.main()


class OneDefectIsOneQualityPenalty(unittest.TestCase):
    """The reviewer stopped double-reporting an owned defect; the quality
    projection still did. A live probe with an empty ``validation_gaps`` and a
    missing ablation was reported as ``validation_gaps_on_1_evidence_rows``,
    which named a cause that was not there and kept technical_correctness in the
    quality gap for a defect baseline_strength already charged."""

    def _state(self, **extra):
        env = make_env(Path(tempfile.mkdtemp()) / "p", contract={"root_question": ROOT})
        seed_question(env, "Q1", ROOT)
        seed_survey(env, "Q1")
        seed_theory(env, "T1", "Q1")
        seed_probe_evidence(env, "E1", "T1", "Q1",
                            **{"sample_size": 150, "validation_gaps": [], **extra})
        return env.state

    def test_a_missing_ablation_is_charged_to_baselines_only(self):
        dims = compute_quality(
            self._state(cannot_corroborate=True, ablation_required=True))["dimensions"]
        self.assertEqual(dims["baseline_strength"]["status"], "weak")
        self.assertEqual(dims["technical_correctness"]["status"], "adequate")

    def test_a_blind_measure_is_charged_to_measurement_only(self):
        dims = compute_quality(
            self._state(cannot_corroborate=True, dv_blind=True))["dimensions"]
        self.assertEqual(dims["measurement_validity"]["status"], "missing")
        self.assertEqual(dims["technical_correctness"]["status"], "adequate")

    def test_a_real_validation_gap_is_still_charged_and_named(self):
        dims = compute_quality(self._state(
            cannot_corroborate=True,
            validation_gaps=["oracle_sanity_execution_failed"]))["dimensions"]
        row = dims["technical_correctness"]
        self.assertEqual(row["status"], "weak")
        self.assertIn("oracle_sanity_execution_failed", row["blocking_reasons"])

    def test_an_unexplained_refusal_says_it_is_unrecorded(self):
        row = compute_quality(self._state(cannot_corroborate=True))["dimensions"]
        self.assertIn("unrecorded_reason",
                      " ".join(row["technical_correctness"]["blocking_reasons"]))
