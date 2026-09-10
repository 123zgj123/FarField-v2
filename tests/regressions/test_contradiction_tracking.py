"""Contradiction tracking had two writers and neither could run.

`ContradictionDetected` was declared, handled by the reducer, and emitted by no
code anywhere. The only other writer was a branch-merge helper with no live
caller. Twelve consumers read the result — verification debt, VERIFY
eligibility, the belief refresh's "unresolved contradictions keep the mechanism
speculative" rule, the readiness gate `no_critical_unresolved_contradiction` —
and every one of them read a list that could not fill. A gate guarding an
impossible condition reads as permanently satisfied, which is worse than an
absent gate.
"""

import unittest

from farfield.extras.openworld.events import make_event
from farfield.extras.openworld.reducer import apply_events, rebuild_state, state_digest
from farfield.extras.openworld.state import ScientificState
from farfield.extras.openworld.termination import readiness


def probe(eid, outcome="supports", **extra):
    return {
        "evidence_id": eid, "role": "ProbeEvidence", "epistemic": "WORLD",
        "attested": True, "promotion_ok": True, "execution_status": "ran",
        "world_id": "W0", "world_digest": "d0", "experiment_digest": f"x-{eid}",
        "theory_id": "T1", "question_id": "Q1", "outcome": outcome,
        "claim_consistent": True, "identity_ok": True, "reproduction_ok": True,
        "literature_checked": True, "sample_size": 500, **extra,
    }


def state(*events):
    base = apply_events(ScientificState(goal="g"), [
        make_event("ContractSet", {"root_question": "g"}),
        make_event("QuestionCreated", {"id": "Q1", "text": "g"}),
        make_event("TheoryCreated", {"id": "T1", "question_id": "Q1", "text": "m"}),
    ])
    return apply_events(base, list(events))


class ContradictionDetectionTest(unittest.TestCase):
    def test_two_disagreeing_results_become_a_contradiction(self):
        current = state(
            make_event("EvidenceAdded", probe("E1")),
            make_event("EvidenceAdded", probe("E2", outcome="weakens",
                                              world_id="W1", world_digest="d1")))
        self.assertEqual(len(current.contradictions), 1)
        row = current.contradictions[0]
        self.assertEqual(row["theory_id"], "T1")
        self.assertEqual(row["source"], "derived")
        self.assertEqual(
            {row["supporting_evidence_id"], row["contradicting_evidence_id"]}, {"E1", "E2"})

    def test_agreeing_results_are_not_a_contradiction(self):
        current = state(
            make_event("EvidenceAdded", probe("E1")),
            make_event("EvidenceAdded", probe("E2", world_id="W1", world_digest="d1")))
        self.assertEqual(current.contradictions, [])

    def test_the_same_experiment_cannot_contradict_itself(self):
        """Two runs of one design on one freeze are one observation."""
        current = state(
            make_event("EvidenceAdded", probe("E1", experiment_digest="same")),
            make_event("EvidenceAdded", probe("E2", outcome="weakens",
                                              experiment_digest="same",
                                              world_id="W1", world_digest="d1")))
        self.assertEqual(current.contradictions, [])

    def test_generated_evidence_raises_no_contradiction(self):
        current = state(
            make_event("EvidenceAdded", probe("E1")),
            make_event("EvidenceAdded", probe("E2", outcome="weakens", epistemic="GENERATED",
                                              attested=False, promotion_ok=False)))
        self.assertEqual(current.contradictions, [])


class ConsumersActuallyReactTest(unittest.TestCase):
    """The twelve readers were the point; each must now be reachable."""

    def setUp(self):
        self.state = state(
            make_event("EvidenceAdded", probe("E1")),
            make_event("EvidenceAdded", probe("E2", outcome="weakens",
                                              world_id="W1", world_digest="d1")))

    def test_contradiction_debt_rises(self):
        self.assertEqual(self.state.debt["contradiction_debt"], 1)

    def test_verify_becomes_eligible_and_targets_the_alternative(self):
        from farfield.extras.openworld.actions import (
            VERIFY_ALTERNATIVE_EXPLANATION, _needs_verify, _verify_kind)

        self.assertTrue(_needs_verify(self.state))
        self.assertEqual(_verify_kind(self.state), VERIFY_ALTERNATIVE_EXPLANATION)

    def test_readiness_names_the_contradiction_as_a_blocker(self):
        self.assertIn("no_critical_unresolved_contradiction",
                      readiness(self.state).failed_gates)

    def test_an_unresolved_contradiction_keeps_the_mechanism_speculative(self):
        self.assertNotIn("T1", self.state.verified_research_state)

    def test_quality_caps_technical_correctness(self):
        row = self.state.quality["dimensions"]["technical_correctness"]
        self.assertTrue(any("contradiction" in r for r in row["blocking_reasons"]))

    def test_the_journal_surfaces_the_strongest_contradiction(self):
        from farfield.extras.openworld.journal import research_journal

        self.assertIsNotNone(research_journal(self.state)["strongest_contradiction"])


class ReportedAndDerivedCoexistTest(unittest.TestCase):
    def test_an_explicitly_reported_contradiction_survives_the_derived_pass(self):
        current = state(make_event("ContradictionDetected", {
            "theory_id": "T1", "note": "conflicts with verified literature"}))
        self.assertEqual(len(current.contradictions), 1)
        self.assertEqual(current.contradictions[0]["source"], "reported")
        current = apply_events(current, [make_event("EvidenceAdded", probe("E1"))])
        self.assertTrue(any(row["source"] == "reported" for row in current.contradictions))

    def test_reported_and_derived_rows_both_appear(self):
        current = state(
            make_event("ContradictionDetected", {"theory_id": "T1", "note": "literature"}),
            make_event("EvidenceAdded", probe("E1")),
            make_event("EvidenceAdded", probe("E2", outcome="weakens",
                                              world_id="W1", world_digest="d1")))
        self.assertEqual({row["source"] for row in current.contradictions},
                         {"reported", "derived"})

    def test_contradictions_replay_from_the_event_log(self):
        from farfield.extras.openworld.events import EventLog

        log = EventLog(baseline=ScientificState(goal="g").to_dict())
        current = apply_events(ScientificState(goal="g"), [
            make_event("ContractSet", {"root_question": "g"}),
            make_event("TheoryCreated", {"id": "T1", "question_id": "Q1", "text": "m"}),
            make_event("ContradictionDetected", {"theory_id": "T1", "note": "literature"}),
            make_event("EvidenceAdded", probe("E1")),
            make_event("EvidenceAdded", probe("E2", outcome="weakens",
                                              world_id="W1", world_digest="d1")),
        ], log=log)
        self.assertEqual(state_digest(current), state_digest(rebuild_state(log)))
        self.assertEqual(len(rebuild_state(log).contradictions), 2)


if __name__ == "__main__":
    unittest.main()
