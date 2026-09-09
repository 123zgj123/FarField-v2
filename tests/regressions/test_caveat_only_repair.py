"""An objection that needs a world cannot be answered with prose.

This is the invariant that separates a research agent from a text generator.
When a reviewer says the evaluation cannot answer the question, the repair is
a new experiment — not a rewrite, not a narrower claim, not another caveat, not
a new discussion section. The runtime must refuse the prose repair, keep the
objection open, and count the refusal.
"""

import unittest

from farfield.extras.openworld.events import make_event
from farfield.extras.openworld.quality import (
    CAVEAT_ONLY_RESOLUTIONS,
    EVIDENCE_RESOLUTIONS,
    normalize_review,
    resolution_admissible,
)
from farfield.extras.openworld.reducer import apply_events
from farfield.extras.openworld.state import ScientificState


FATAL = {
    "review_id": "RF1",
    "severity": "fatal",
    "dimension": "experimental_adequacy",
    "objection": "the evaluation as designed cannot answer the central question",
    "repair_type": "experiment_redesign",
    "requires_new_evidence": True,
}

ADMITTED_EVIDENCE = {
    "evidence_id": "E-new", "epistemic": "WORLD", "attested": True,
    "promotion_ok": True, "role": "ProbeEvidence", "world_id": "W0",
    "world_digest": "d0", "experiment_digest": "x1", "outcome": "supports",
    "execution_status": "ran", "claim_consistent": True,
}


class CaveatOnlyRepairTest(unittest.TestCase):
    def _state(self, *extra):
        state = ScientificState(goal="g")
        return apply_events(state, [
            make_event("ContractSet", {"root_question": "g"}),
            make_event("ReviewRecorded", FATAL),
            *extra,
        ])

    def test_every_prose_repair_is_refused(self):
        for kind in sorted(CAVEAT_ONLY_RESOLUTIONS):
            with self.subTest(resolution=kind):
                ok, why = resolution_admissible(normalize_review(FATAL), resolution_kind=kind)
                self.assertFalse(ok)
                self.assertIn("caveat_only_repair_refused", why)

    def test_an_unspecified_repair_is_refused(self):
        ok, why = resolution_admissible(normalize_review(FATAL), resolution_kind="")
        self.assertFalse(ok)
        self.assertIn("caveat_only_repair_refused", why)

    def test_evidence_repairs_still_need_evidence_that_actually_exists(self):
        for kind in sorted(EVIDENCE_RESOLUTIONS):
            with self.subTest(resolution=kind):
                ok, why = resolution_admissible(normalize_review(FATAL), resolution_kind=kind)
                self.assertFalse(ok)
                self.assertIn("resolution_requires_admitted_evidence_id", why)
                ok, why = resolution_admissible(
                    normalize_review(FATAL), resolution_kind=kind, evidence_id="E-ghost",
                    evidence_rows=[])
                self.assertFalse(ok)
                self.assertIn("resolution_evidence_not_in_state", why)

    def test_evidence_that_did_not_promote_cannot_close_an_objection(self):
        ok, why = resolution_admissible(
            normalize_review(FATAL), resolution_kind="new_valid_experiment",
            evidence_id="E-gen",
            evidence_rows=[{**ADMITTED_EVIDENCE, "evidence_id": "E-gen",
                            "epistemic": "GENERATED", "promotion_ok": False}])
        self.assertFalse(ok)
        self.assertIn("did_not_promote_to_world", why)

    def test_the_reducer_refuses_a_caveat_and_counts_it(self):
        state = self._state()
        state = apply_events(state, [make_event(
            "ReviewResolved", {"review_id": "RF1", "resolution_kind": "added_caveat"})])
        review = state.reviews[0]
        self.assertEqual(review["status"], "open")
        self.assertEqual(review["repair_refusals"], 1)
        self.assertEqual(state.metrics["caveat_only_repair_refused"], 1)

    def test_the_reducer_admits_a_real_evidence_repair(self):
        state = self._state(make_event("EvidenceAdded", ADMITTED_EVIDENCE))
        state = apply_events(state, [make_event("ReviewResolved", {
            "review_id": "RF1", "resolution_kind": "new_valid_experiment",
            "resolution_evidence_id": "E-new"})])
        self.assertEqual(state.reviews[0]["status"], "resolved")
        self.assertEqual(state.reviews[0]["resolution_evidence_id"], "E-new")

    def test_a_reviewer_cannot_declare_a_redesign_answerable_by_rewriting(self):
        record = normalize_review({**FATAL, "requires_new_evidence": False})
        self.assertTrue(record["requires_new_evidence"])

    def test_a_pure_wording_objection_may_be_closed_by_wording(self):
        record = normalize_review({
            "review_id": "RM1", "severity": "minor", "dimension": "technical_correctness",
            "objection": "the abstract overstates the scope", "repair_type": "writing_only"})
        self.assertFalse(record["requires_new_evidence"])
        ok, _ = resolution_admissible(record, resolution_kind="rewrite")
        self.assertTrue(ok)

    def test_refused_repairs_survive_event_replay(self):
        from farfield.extras.openworld.events import EventLog
        from farfield.extras.openworld.reducer import rebuild_state, state_digest

        log = EventLog(baseline=ScientificState(goal="g").to_dict())
        state = apply_events(ScientificState(goal="g"), [
            make_event("ContractSet", {"root_question": "g"}),
            make_event("ReviewRecorded", FATAL),
            make_event("ReviewResolved", {"review_id": "RF1", "resolution_kind": "rewrite"}),
        ], log=log)
        self.assertEqual(state_digest(state), state_digest(rebuild_state(log)))
        self.assertEqual(rebuild_state(log).metrics["caveat_only_repair_refused"], 1)


if __name__ == "__main__":
    unittest.main()
