"""A finished run, a full paper and an empty budget are not answers."""

import unittest

from farfield.extras.openworld.events import make_event
from farfield.extras.openworld.reducer import apply_events
from farfield.extras.openworld.resources import budget_phase, compute_resources
from farfield.extras.openworld.state import ScientificState
from farfield.extras.openworld.termination import (
    BUDGET_EXHAUSTED,
    NO_VIABLE_PATH,
    RESEARCH_INCOMPLETE,
    RESEARCH_READY,
    readiness,
    run_outcome,
)


ROOT = "Does retrieval augmentation improve factual accuracy?"


def _probe(eid, **extra):
    return {
        "evidence_id": eid, "role": "ProbeEvidence", "epistemic": "WORLD",
        "attested": True, "promotion_ok": True, "execution_status": "ran",
        "world_id": "W0", "world_digest": "d0", "experiment_digest": f"x{eid}",
        "theory_id": "T1", "question_id": "Q1", "outcome": "supports",
        "claim_consistent": True, "identity_ok": True, "reproduction_ok": True,
        "executable_ok": True, "literature_checked": True, "mechanism_validated": True,
        "sample_size": 500, "world_consumed": True, **extra,
    }


def _ready_state():
    """A project that has actually done the work the contract asked for."""
    state = ScientificState(goal=ROOT)
    return apply_events(state, [
        make_event("ContractSet", {
            "root_question": ROOT, "target_quality": "conference",
            "resource_limits": {"api_calls": 100, "min_sample_size": 100}}),
        make_event("QuestionCreated", {"id": "Q1", "text": ROOT}),
        make_event("ArtifactAdded", {
            "id": "s1", "kind": "literature_survey", "question_id": "Q1", "theory_id": "T1",
            "works": [{"arxiv_id": "1", "title": "t", "abstract": "a"}]}),
        make_event("TheoryCreated", {"id": "T1", "question_id": "Q1", "text": "m",
                                     "epistemic": "GENERATED"}),
        make_event("EvidenceAdded", _probe("E1")),
        make_event("EvidenceAdded", _probe(
            "E2", replication_of="E1", transfer_ok=True, independent_replication=True,
            world_id="W1", world_digest="d1")),
        make_event("QuestionResolved", {"id": "Q1", "evidence_id": "E1"}),
        # Novelty and importance are judgments; nothing executed can settle them.
        make_event("ReviewRecorded", {
            "review_id": "assessment-novelty", "dimension": "novelty", "severity": "minor",
            "assessment": "adequate", "supporting_refs": ["1"], "repair_type": "writing_only"}),
        make_event("ReviewRecorded", {
            "review_id": "assessment-importance", "dimension": "importance", "severity": "minor",
            "assessment": "adequate", "supporting_refs": ["1"], "repair_type": "writing_only"}),
    ])


class ReadinessTest(unittest.TestCase):
    def test_a_bare_project_is_not_ready(self):
        state = apply_events(ScientificState(goal=ROOT),
                             [make_event("ContractSet", {"root_question": ROOT})])
        self.assertNotEqual(readiness(state).status, RESEARCH_READY)

    def test_a_completed_project_can_actually_reach_ready(self):
        verdict = readiness(_ready_state())
        self.assertEqual(verdict.status, RESEARCH_READY, verdict.failed_gates)
        self.assertTrue(verdict.ready)

    def test_one_open_fatal_objection_blocks_readiness(self):
        state = apply_events(_ready_state(), [make_event("ReviewRecorded", {
            "review_id": "RF1", "severity": "fatal", "dimension": "measurement_validity",
            "objection": "the measure is wrong", "repair_type": "measurement_redesign"})])
        verdict = readiness(state)
        self.assertNotEqual(verdict.status, RESEARCH_READY)
        self.assertIn("no_fatal_objections", verdict.failed_gates)

    def test_goal_drift_blocks_readiness_even_with_good_evidence(self):
        state = apply_events(_ready_state(), [make_event(
            "QuestionCreated", {"id": "Q9", "text": "how should token overlap be scored?"})])
        verdict = readiness(state)
        self.assertIn("no_unauthorized_goal_drift", verdict.failed_gates)

    def test_an_unresolved_contradiction_blocks_readiness(self):
        state = apply_events(_ready_state(), [make_event(
            "ContradictionDetected", {"evidence_id": "E1", "theory_id": "T1"})])
        self.assertIn("no_critical_unresolved_contradiction", readiness(state).failed_gates)

    def test_evidence_with_validation_gaps_does_not_match_its_claim(self):
        state = apply_events(_ready_state(), [make_event(
            "EvidenceAdded", _probe("E3", cannot_corroborate=True,
                                    validation_gaps=["oracle_sanity_not_identifiable"]))])
        self.assertIn("evidence_scope_matches_claim", readiness(state).failed_gates)

    def test_a_missing_required_output_blocks_readiness(self):
        state = apply_events(_ready_state(), [make_event(
            "ContractAmended", {"required_outputs": ["research_synthesis"]})])
        self.assertIn("required_outputs_present", readiness(state).failed_gates)

    def test_an_exhausted_budget_is_its_own_status_not_an_answer(self):
        state = apply_events(ScientificState(goal=ROOT), [
            make_event("ContractSet", {"root_question": ROOT,
                                       "resource_limits": {"api_calls": 2}}),
            make_event("QuestionCreated", {"id": "Q1", "text": ROOT}),
            *[make_event("ArtifactAdded", {
                "kind": "action_attempt", "action_type": "PROBE", "input_key": f"k{i}",
                "measured_cost": {"tokens": 10.0, "wall_seconds": 1.0}}) for i in range(3)],
        ])
        verdict = readiness(state)
        self.assertEqual(verdict.status, BUDGET_EXHAUSTED)
        self.assertFalse(verdict.ready)

    def test_no_viable_path_needs_exhausted_repairs_not_one_bad_result(self):
        base = apply_events(ScientificState(goal=ROOT), [
            make_event("ContractSet", {"root_question": ROOT}),
            make_event("QuestionCreated", {"id": "Q1", "text": ROOT}),
            make_event("ReviewRecorded", {
                "review_id": "RP1", "severity": "fatal", "dimension": "importance",
                "objection": "this direction cannot matter", "repair_type": "project_pivot"}),
        ])
        self.assertEqual(readiness(base).status, RESEARCH_INCOMPLETE)
        spent = apply_events(base, [make_event("DesignRevised", {
            "revision_id": f"rev-{i}", "dimension": "importance", "outcome": "open"})
            for i in range(3)])
        self.assertEqual(readiness(spent).status, NO_VIABLE_PATH)

    def test_run_outcome_reports_the_segment_separately_from_the_research(self):
        payload = run_outcome(_ready_state(), horizon_reached=True)
        self.assertTrue(payload["research_complete"])
        self.assertNotIn("segment", payload)
        state = apply_events(_ready_state(), [make_event("ReviewRecorded", {
            "review_id": "RF1", "severity": "fatal", "dimension": "robustness",
            "objection": "not robust", "repair_type": "experiment_redesign"})])
        payload = run_outcome(state, horizon_reached=True)
        self.assertFalse(payload["research_complete"])
        self.assertEqual(payload["segment"], "RUN_SEGMENT_DONE")


class ResourceTest(unittest.TestCase):
    def test_spend_is_derived_from_measured_costs_not_estimates(self):
        state = apply_events(ScientificState(goal=ROOT), [
            make_event("ContractSet", {"root_question": ROOT,
                                       "resource_limits": {"api_calls": 10, "tokens": 5000}}),
            *[make_event("ArtifactAdded", {
                "kind": "action_attempt", "action_type": "PROBE", "input_key": f"k{i}",
                "measured_cost": {"tokens": 1000.0, "wall_seconds": 2.0}}) for i in range(4)],
        ])
        resources = compute_resources(state)
        self.assertEqual(resources["spent"]["tokens"], 4000.0)
        self.assertEqual(resources["spent"]["api_calls"], 4.0)
        self.assertEqual(resources["remaining"]["api_calls"], 6.0)
        self.assertEqual(budget_phase(state), "closing")  # tokens are 80% spent

    def test_an_unmetered_project_reports_it_rather_than_guessing(self):
        state = apply_events(ScientificState(goal=ROOT),
                             [make_event("ContractSet", {"root_question": ROOT})])
        self.assertEqual(budget_phase(state), "unmetered")

    def test_budget_ok_actually_refuses_once_a_limit_is_crossed(self):
        from farfield.extras.openworld.actions import SPECS, ActionInstance
        from farfield.extras.openworld.scheduler import budget_ok

        state = apply_events(ScientificState(goal=ROOT), [
            make_event("ContractSet", {"root_question": ROOT,
                                       "resource_limits": {"api_calls": 2}}),
            *[make_event("ArtifactAdded", {
                "kind": "action_attempt", "action_type": "PROBE", "input_key": f"k{i}",
                "measured_cost": {"tokens": 1.0, "wall_seconds": 1.0}}) for i in range(3)],
        ])
        self.assertFalse(budget_ok(ActionInstance(SPECS["PROBE"]), state))


if __name__ == "__main__":
    unittest.main()
