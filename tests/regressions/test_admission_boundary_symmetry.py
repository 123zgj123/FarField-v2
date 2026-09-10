"""The kernel boundary must not depend on how a worker packages its result.

A worker can return evidence two ways: as `candidate.evidence`, or as an
`EvidenceAdded` event inside `candidate.events`. Reading `_admit`, only the
first is followed by an explicit `can_promote_to_world` call, so the second
looked like it might reach canonical state having passed fewer checks. It does
not — the sanitiser inside `checked()` applies the same gate — and that is
exactly the kind of property that should be pinned rather than re-derived by
reading the function again next time.
"""

import tempfile
import unittest
from pathlib import Path

from farfield.extras.openworld import CandidateResult, OpenWorld
from farfield.extras.openworld.actions import SPECS, ActionInstance
from farfield.extras.openworld.events import make_event


def row(**extra):
    return {
        "evidence_id": "E1", "role": "ProbeEvidence", "epistemic": "WORLD",
        "attested": True, "promotion_ok": True, "execution_status": "ran",
        "world_id": "W0", "world_digest": "d0", "experiment_digest": "x",
        "theory_id": "T1", "question_id": "Q1", "outcome": "supports",
        "claim_consistent": True, "identity_ok": True, "reproduction_ok": True,
        "literature_checked": True, "sample_size": 500, **extra,
    }


class AdmissionBoundarySymmetryTest(unittest.TestCase):
    def admit(self, candidate):
        with tempfile.TemporaryDirectory() as workspace:
            env = OpenWorld(workspace=Path(workspace))
            action = ActionInstance(SPECS["PROBE"], target="T1",
                                    frontier_target_id="Q1")
            return env._admit(action, candidate)

    def both_carriers(self, payload):
        as_event = self.admit(CandidateResult(
            status="probe_positive",
            events=[make_event("EvidenceAdded", dict(payload))]))
        as_evidence = self.admit(CandidateResult(
            status="probe_positive", evidence=dict(payload)))
        return (as_event.events[0].payload, as_evidence.evidence)

    def test_a_social_signal_is_refused_through_either_carrier(self):
        event, evidence = self.both_carriers(row(sibling_agreement=3))
        for name, admitted in (("event", event), ("evidence", evidence)):
            with self.subTest(carrier=name):
                self.assertEqual(admitted["epistemic"], "GENERATED")
                self.assertFalse(admitted["promotion_ok"])
                self.assertTrue(any("social signal" in gap
                                    for gap in admitted["promotion_gaps"]))

    def test_an_unattested_world_digest_is_refused_through_either_carrier(self):
        """No attested freeze exists in this workspace, so WORLD cannot hold."""
        event, evidence = self.both_carriers(row())
        for name, admitted in (("event", event), ("evidence", evidence)):
            with self.subTest(carrier=name):
                self.assertEqual(admitted["epistemic"], "GENERATED")
                self.assertFalse(admitted["promotion_ok"])

    def test_generated_provenance_cannot_be_relabelled(self):
        event, evidence = self.both_carriers(row(probe_kind="GENERATED"))
        for name, admitted in (("event", event), ("evidence", evidence)):
            with self.subTest(carrier=name):
                self.assertEqual(admitted["epistemic"], "GENERATED")
                self.assertFalse(admitted.get("attested"))

    def test_both_carriers_report_the_same_gaps(self):
        event, evidence = self.both_carriers(row(citation_count=99))
        self.assertEqual(sorted(event["promotion_gaps"]),
                         sorted(evidence["promotion_gaps"]))


if __name__ == "__main__":
    unittest.main()
