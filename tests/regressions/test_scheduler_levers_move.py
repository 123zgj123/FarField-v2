"""Every scheduler weight must be a lever that can actually move.

A term that is structurally always zero is a policy knob doing nothing, and it
reads as live in every table that lists it. This is the same failure the
capability register and the reachability audit exist to catch, applied to the
decision policy: each of the ten research weights is exercised on a state
constructed to trigger it, so a term that stops being reachable fails here.

Sampling thirteen live workspaces and eight behavioural scenarios left
`strategic_escalation` and `goal_drift_penalty` at zero throughout — not
because they are dead, but because no sampled run drifted or stagnated.
Absence of a signal in a sample is not evidence that the signal cannot fire,
which is exactly why each one is constructed here instead.
"""

import unittest

from farfield.extras.openworld.actions import ActionInstance, SPECS
from farfield.extras.openworld.events import make_event
from farfield.extras.openworld.reducer import apply_events
from farfield.extras.openworld.scheduler import (
    RESEARCH_WEIGHTS,
    _research_score,
    project_layer_active,
)
from farfield.extras.openworld.state import ScientificState

ROOT = "does retrieval augmentation improve factual accuracy in long-context models?"


def base(**contract):
    return apply_events(ScientificState(goal=ROOT), [
        make_event("ContractSet", {"root_question": ROOT, **contract}),
        make_event("QuestionCreated", {"id": "Q1", "text": ROOT}),
    ])


def act(kind, target="Q1", **extra):
    return ActionInstance(SPECS[kind], target=target, frontier_target_id=target,
                          extra=extra)


def term(state, action, name):
    return float(_research_score(action, state)[name])


class SchedulerLeverTest(unittest.TestCase):
    def assertMoves(self, state, action, name):
        self.assertTrue(project_layer_active(state),
                        "the research layer is off, so no weight applies")
        self.assertNotEqual(term(state, action, name), 0.0,
                            f"{name} is zero on a state built to trigger it")

    def test_central_question_value(self):
        self.assertMoves(base(), act("PROBE"), "central_question_value")

    def test_objection_repair_value(self):
        state = apply_events(base(), [make_event("ReviewRecorded", {
            "review_id": "R1", "severity": "major", "dimension": "baseline_strength",
            "objection": "no baseline", "repair_type": "stronger_baseline"})])
        self.assertMoves(state, act("REDESIGN"), "objection_repair_value")

    def test_quality_gap_value(self):
        state = base(target_quality="workshop")
        self.assertMoves(state, act("PROBE"), "quality_gap_value")

    def test_strategic_escalation(self):
        from farfield.extras.openworld.progress import maybe_strategic_stagnation

        state = base()
        for index in range(12):
            state = apply_events(state, [
                make_event("ArtifactAdded", {"kind": "action_attempt",
                                             "action_type": "PROBE",
                                             "input_key": f"k{index}"}),
                make_event("ActionFailed", {"theory_id": "T1",
                                            "reason": "the measure never moved"}),
                make_event("TickAdvanced", {"tick": index + 1}),
            ])
        self.assertIsNotNone(maybe_strategic_stagnation(state))
        self.assertMoves(state, act("FORK_LINEAGE"), "strategic_escalation")
        self.assertLess(term(state, act("PROBE"), "strategic_escalation"), 0.0,
                        "more of the same should be discouraged, not neutral")

    def test_resource_discipline(self):
        state = base(resource_limits={"api_calls": 4})
        for index in range(3):
            state = apply_events(state, [make_event("ArtifactAdded", {
                "kind": "action_attempt", "action_type": "PROBE",
                "input_key": f"k{index}",
                "measured_cost": {"api_calls": 1.0, "tokens": 1.0}})])
        self.assertEqual(state.resources["budget_pressure"], 0.75)
        self.assertMoves(state, act("PROBE"), "resource_discipline")

    def test_goal_drift_penalty(self):
        state = apply_events(base(), [make_event("QuestionCreated", {
            "id": "Q2",
            "text": "which GPU kernel schedule minimises memory bandwidth stalls?"})])
        self.assertEqual(state.debt.get("goal_drift_debt"), 1)
        self.assertMoves(state, act("PROBE", target="Q2"), "goal_drift_penalty")

    def test_blocked_by_fatal_objection(self):
        state = apply_events(base(), [make_event("ReviewRecorded", {
            "review_id": "R1", "severity": "fatal", "dimension": "measurement_validity",
            "objection": "the measure is blind to the effect",
            "repair_type": "measurement_redesign", "requires_new_evidence": True})])
        self.assertMoves(state, act("PROBE"), "blocked_by_fatal_objection")

    def test_repeated_failure_penalty(self):
        """The signature is action type against the theory the failure names."""
        state = apply_events(base(), [make_event(
            "ActionFailed", {"theory_id": "T1", "action_type": "PROBE",
                             "reason": "the arms were never comparable"})])
        self.assertTrue(state.failed_designs)
        self.assertMoves(state, act("PROBE", target="T1"), "repeated_failure_penalty")

    def test_redesign_exhaustion(self):
        state = base()
        for index in range(3):
            state = apply_events(state, [make_event("DesignRevised", {
                "revision_id": f"D{index}", "question_id": "Q1", "theory_id": "T1",
                "repair": "experiment_redesign", "parent_design": "T1",
                "changed": "the arm", "reason": "the arms were not comparable"})])
        self.assertMoves(state, act("REDESIGN"), "redesign_exhaustion")

    def test_inert_action_penalty(self):
        """Two consecutive attempts of a type that admitted no event."""
        state = base()
        for index in range(2):
            state = apply_events(state, [make_event("ArtifactAdded", {
                "kind": "action_attempt", "action_type": "ARCHIVE",
                "target": "Q1", "input_key": f"k{index}", "events_admitted": 0})])
        self.assertMoves(state, act("ARCHIVE"), "inert_action_penalty")

    def test_every_declared_weight_has_a_test_here(self):
        """A weight added without a lever test would otherwise go unchecked."""
        tested = {name.removeprefix("test_") for name in dir(self)
                  if name.startswith("test_")}
        missing = [name for name in RESEARCH_WEIGHTS if name not in tested]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
