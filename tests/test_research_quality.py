"""Quality is derived from what happened, never asserted by a worker."""

import unittest

from farfield.extras.openworld.events import make_event
from farfield.extras.openworld.quality import (
    DIMENSIONS,
    STATUS_ORDER,
    compute_quality,
    requirements_for,
    review_debt,
)
from farfield.extras.openworld.contract import ResearchContract
from farfield.extras.openworld.reducer import apply_events
from farfield.extras.openworld.state import ScientificState


ROOT = "Does retrieval augmentation improve factual accuracy?"

PROBE = {
    "evidence_id": "E1", "role": "ProbeEvidence", "epistemic": "WORLD",
    "attested": True, "promotion_ok": True, "execution_status": "ran",
    "world_id": "W0", "world_digest": "d0", "experiment_digest": "x1",
    "theory_id": "T1", "question_id": "Q1", "outcome": "supports",
    "claim_consistent": True, "identity_ok": True, "reproduction_ok": True,
}


def _state(*events, contract=None):
    state = ScientificState(goal=ROOT)
    payload = {"root_question": ROOT, "target_quality": "conference",
               "resource_limits": {"min_sample_size": 100}}
    payload.update(contract or {})
    return apply_events(state, [make_event("ContractSet", payload), *events])


class QualityStateTest(unittest.TestCase):
    def test_every_dimension_is_ordinal_and_never_a_probability(self):
        quality = compute_quality(_state())
        self.assertEqual(set(quality["dimensions"]), set(DIMENSIONS))
        for row in quality["dimensions"].values():
            self.assertIn(row["status"], STATUS_ORDER)
        self.assertNotIn("accept_probability", quality)

    def test_an_empty_project_is_short_on_everything_it_promised(self):
        quality = compute_quality(_state())
        self.assertIn("central_claim_support", quality["quality_gap"])
        self.assertIn("literature_coverage", quality["quality_gap"])

    def test_an_unreported_sample_size_is_not_adequate_evidence(self):
        state = _state(make_event("EvidenceAdded", PROBE))
        row = compute_quality(state)["dimensions"]["experimental_adequacy"]
        self.assertEqual(row["status"], "weak")
        self.assertTrue(any("does_not_report_units_measured" in r for r in row["blocking_reasons"]))
        # The repair has to be one the pipeline can actually perform.
        self.assertIn("REDESIGN", row["required_next_work"])

    def test_a_sample_below_the_contract_minimum_is_weak(self):
        state = _state(make_event("EvidenceAdded", {**PROBE, "sample_size": 6}))
        row = compute_quality(state)["dimensions"]["experimental_adequacy"]
        self.assertEqual(row["status"], "weak")
        self.assertTrue(any("underpowered" in r for r in row["blocking_reasons"]))
        self.assertIn("REDESIGN", row["required_next_work"])

    def test_a_sufficient_sample_clears_the_dimension(self):
        state = _state(make_event("EvidenceAdded", {**PROBE, "sample_size": 500}))
        self.assertEqual(
            compute_quality(state)["dimensions"]["experimental_adequacy"]["status"], "adequate")

    def test_a_measure_blind_to_the_oracle_is_a_missing_measurement(self):
        state = _state(make_event("EvidenceAdded", {**PROBE, "sample_size": 500, "dv_blind": True}))
        self.assertEqual(
            compute_quality(state)["dimensions"]["measurement_validity"]["status"], "missing")

    def test_a_positive_result_is_not_a_verified_mechanism(self):
        state = _state(make_event("EvidenceAdded", {**PROBE, "sample_size": 500}))
        self.assertEqual(
            compute_quality(state)["dimensions"]["mechanism_support"]["status"], "weak")

    def test_a_single_world_result_does_not_generalize(self):
        state = _state(make_event("EvidenceAdded", {**PROBE, "sample_size": 500}))
        dims = compute_quality(state)["dimensions"]
        self.assertEqual(dims["replication"]["status"], "missing")
        self.assertEqual(dims["generalization"]["status"], "missing")

    def test_judgment_dimensions_stay_unknown_without_a_recorded_judgment(self):
        state = _state(make_event("EvidenceAdded", {**PROBE, "sample_size": 500}))
        dims = compute_quality(state)["dimensions"]
        for name in ("novelty", "importance"):
            self.assertEqual(dims[name]["status"], "unknown")
            self.assertIn("REVIEW", dims[name]["required_next_work"])

    def test_a_fatal_objection_forces_its_dimension_to_missing(self):
        state = _state(
            make_event("EvidenceAdded", {**PROBE, "sample_size": 500}),
            make_event("ReviewRecorded", {
                "review_id": "RF1", "severity": "fatal", "dimension": "experimental_adequacy",
                "objection": "cannot answer the question", "repair_type": "experiment_redesign"}))
        dims = compute_quality(state)["dimensions"]
        self.assertEqual(dims["experimental_adequacy"]["status"], "missing")
        self.assertEqual(dims["central_claim_support"]["status"], "missing")

    def test_a_major_objection_caps_its_dimension_at_weak(self):
        state = _state(
            make_event("EvidenceAdded", {**PROBE, "sample_size": 500}),
            make_event("ReviewRecorded", {
                "review_id": "RM1", "severity": "major", "dimension": "experimental_adequacy",
                "objection": "power is marginal", "repair_type": "experiment_redesign"}))
        self.assertEqual(
            compute_quality(state)["dimensions"]["experimental_adequacy"]["status"], "weak")

    def test_a_worker_cannot_write_its_own_quality_rating(self):
        state = _state(make_event("EvidenceAdded", {**PROBE, "sample_size": 6}))
        state.quality = {"quality_gap": [], "dimensions": {
            name: {"status": "adequate"} for name in DIMENSIONS}}
        # The next admitted event recomputes it from canonical facts.
        state = apply_events(state, [make_event("ArtifactAdded", {"kind": "note"})])
        self.assertEqual(state.quality["dimensions"]["experimental_adequacy"]["status"], "weak")
        self.assertTrue(state.quality["quality_gap"])

    def test_requirements_rise_with_the_contract_target(self):
        low = requirements_for(ResearchContract.from_dict(
            {"root_question": ROOT, "target_quality": "exploratory"}))
        high = requirements_for(ResearchContract.from_dict(
            {"root_question": ROOT, "target_quality": "archival"}))
        self.assertLess(len(low), len(high))
        self.assertIn("replication", high)

    def test_review_debt_separates_severity_and_repair_kind(self):
        debt = review_debt([
            {"review_id": "a", "severity": "fatal", "repair_type": "experiment_redesign"},
            {"review_id": "b", "severity": "major", "repair_type": "writing_only"},
            {"review_id": "c", "severity": "major", "repair_type": "project_pivot"},
            {"review_id": "d", "severity": "minor", "repair_type": "writing_only",
             "status": "resolved"},
        ])
        self.assertEqual(debt["fatal_objections"], 1)
        self.assertEqual(debt["major_objections"], 2)
        self.assertEqual(debt["minor_objections"], 0)
        self.assertEqual(debt["pivot_objections"], 1)


if __name__ == "__main__":
    unittest.main()


class JudgmentDimensionTest(unittest.TestCase):
    """Novelty and importance are judgments. They still have to be grounded."""

    def _with_survey(self, *events):
        return _state(
            make_event("ArtifactAdded", {
                "id": "s1", "kind": "literature_survey", "question_id": "Q1", "theory_id": "T1",
                "citations": ["2401.00001"],
                "works": [{"arxiv_id": "2401.00001", "title": "t", "abstract": "a"}]}),
            *events)

    def test_an_ungrounded_judgment_is_capped_at_partial(self):
        state = self._with_survey(make_event("ReviewRecorded", {
            "review_id": "a1", "dimension": "novelty", "severity": "minor",
            "assessment": "adequate", "repair_type": "writing_only"}))
        row = compute_quality(state)["dimensions"]["novelty"]
        self.assertEqual(row["status"], "partial")
        self.assertTrue(any("not grounded" in r for r in row["blocking_reasons"]))

    def test_a_judgment_citing_verified_literature_may_reach_adequate(self):
        state = self._with_survey(make_event("ReviewRecorded", {
            "review_id": "a1", "dimension": "novelty", "severity": "minor",
            "assessment": "adequate", "supporting_refs": ["2401.00001"],
            "repair_type": "writing_only"}))
        self.assertEqual(compute_quality(state)["dimensions"]["novelty"]["status"], "adequate")

    def test_a_judgment_citing_literature_the_state_never_verified_is_not_grounded(self):
        state = self._with_survey(make_event("ReviewRecorded", {
            "review_id": "a1", "dimension": "novelty", "severity": "minor",
            "assessment": "adequate", "supporting_refs": ["9999.99999"],
            "repair_type": "writing_only"}))
        self.assertEqual(compute_quality(state)["dimensions"]["novelty"]["status"], "partial")

    def test_an_open_objection_outranks_a_flattering_self_assessment(self):
        state = self._with_survey(
            make_event("ReviewRecorded", {
                "review_id": "a1", "dimension": "novelty", "severity": "minor",
                "assessment": "adequate", "supporting_refs": ["2401.00001"],
                "repair_type": "writing_only"}),
            make_event("ReviewRecorded", {
                "review_id": "o1", "dimension": "novelty", "severity": "fatal",
                "objection": "the literature already states this",
                "repair_type": "project_pivot"}))
        self.assertEqual(compute_quality(state)["dimensions"]["novelty"]["status"], "missing")

    def test_an_assessment_does_not_open_repair_debt(self):
        state = self._with_survey(make_event("ReviewRecorded", {
            "review_id": "a1", "dimension": "importance", "severity": "minor",
            "assessment": "partial", "repair_type": "writing_only"}))
        self.assertEqual(review_debt(state.reviews)["minor_objections"], 0)
