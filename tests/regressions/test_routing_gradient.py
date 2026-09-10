"""The routing reward was structurally zero on the production path.

`_card_credit` paid only for `promoted` or `host_ok is True`. Promotion needs
the whole ladder including heldout replication, so it is almost never reached;
and `host_ok` is written only by `mission.py`, a vocabulary the production
controller does not speak. Every card the OpenWorld path produced therefore
earned zero, every operator drew the same Laplace-smoothed weight, and the
policy that was supposed to make exploration better over time had no gradient
to follow. Two consecutive live runs produced near-identical hypotheses.

The reward also paid only for `verdict == supports`, which is a
confirmation-seeking incentive: an operator that reliably produces decisive
negative results earned nothing.
"""

import unittest

from farfield.extras.openworld.exploration import select_operator
from farfield.extras.openworld.state import ScientificState
from farfield.extras.routing import (
    _card_credit,
    decisive_world_result,
    operator_report,
    propose_policy,
)


def card(operator="decomposition", verdict="supports", **extra):
    return {
        "ledger": "scientific", "operator": operator, "verdict": verdict,
        "outcome": verdict, "evidence_id": f"E-{operator}-{verdict}",
        "epistemic": "WORLD", "attested": True, "promotion_ok": True,
        "execution_status": "ran", "probe_kind": "WORLD",
        "reproduction_ok": True, "identity_ok": True,
        "world_digest": "d", "experiment_digest": "x", "claim_consistent": True,
        **extra,
    }


def missions(*cards):
    return [{"mission_id": "m1", "status": "completed", "cards": list(cards)}]


class RewardReadsTheProductionVocabularyTest(unittest.TestCase):
    def test_a_reproduced_admitted_result_earns_credit_without_host_ok(self):
        """host_ok is the legacy pipeline's field; the controller writes
        reproduction_ok and identity_ok instead."""
        row = card()
        self.assertIsNone(row.get("host_ok"))
        self.assertEqual(_card_credit(row), 1.0)

    def test_the_legacy_host_confirmed_path_still_earns_credit(self):
        self.assertEqual(_card_credit({
            "ledger": "scientific", "operator": "x", "verdict": "supports",
            "probe_kind": "WORLD", "host_ok": True}), 1.0)


class RewardPaysForSettlingNotAgreeingTest(unittest.TestCase):
    def test_a_decisive_negative_result_earns_full_credit(self):
        """Ruling something out is research. Paying only for agreement would
        train exploration toward operators that confirm."""
        self.assertEqual(_card_credit(card(verdict="weakens")), 1.0)

    def test_an_inconclusive_result_earns_nothing(self):
        self.assertEqual(_card_credit(card(verdict="uninformative")), 0.0)

    def test_an_unreproduced_result_earns_nothing(self):
        self.assertEqual(_card_credit(card(reproduction_ok=False)), 0.0)

    def test_a_result_the_kernel_refused_earns_nothing(self):
        for refusal in ({"promotion_ok": False}, {"cannot_corroborate": True},
                        {"epistemic": "GENERATED"}, {"attested": False},
                        {"execution_status": "blocked"}):
            with self.subTest(refusal=refusal):
                self.assertEqual(_card_credit(card(**refusal)), 0.0)
                self.assertFalse(decisive_world_result(card(**refusal)))

    def test_an_infrastructure_failure_earns_nothing(self):
        self.assertEqual(_card_credit(card(ledger="diagnostic")), 0.0)


class WeightsCanDifferentiateTest(unittest.TestCase):
    def test_promotion_alone_cannot_fit_anything(self):
        """It requires the whole ladder, so on the production path every
        operator would draw the same smoothed weight."""
        report = operator_report(missions(
            *[card("a") for _ in range(5)], *[card("b", "uninformative") for _ in range(5)]))
        self.assertEqual(report["a"]["promotion_rate"], 0.0)
        self.assertEqual(report["b"]["promotion_rate"], 0.0)

    def test_settled_results_do_differentiate(self):
        report = operator_report(missions(
            *[card("a") for _ in range(3)], *[card("a", "weakens") for _ in range(2)],
            *[card("b", "uninformative") for _ in range(5)]))
        self.assertEqual(report["a"]["decisive"], 5)
        self.assertEqual(report["b"]["decisive"], 0)
        weights = propose_policy(missions(
            *[card("a") for _ in range(5)],
            *[card("b", "uninformative") for _ in range(5)]))["weights"]
        self.assertGreater(weights["a"], weights["b"])


class TheLoopClosesTest(unittest.TestCase):
    """Mission results → report → weights → the next session's actual choice."""

    def _policy(self):
        return propose_policy(missions(
            *[card("decomposition") for _ in range(3)],
            *[card("decomposition", "weakens") for _ in range(2)],
            *[card("assumption_removal", "uninformative") for _ in range(5)]))

    def _state(self):
        state = ScientificState(goal="does X improve Y in Z?")
        state.contract = {"root_question": state.goal}
        return state

    def test_an_admitted_policy_changes_which_operator_is_tried(self):
        state = self._state()
        plain = select_operator(state, lane="assumption_reframe", question_id="Q1")
        learned = select_operator(state, lane="assumption_reframe", question_id="Q1",
                                  policy=self._policy())
        self.assertNotEqual(learned["operator"], plain["operator"])
        self.assertEqual(learned["operator"], "decomposition")
        self.assertEqual(learned["basis"], "admitted_policy_weight")

    def test_without_a_policy_the_situation_still_decides(self):
        chosen = select_operator(self._state(), lane="assumption_reframe", question_id="Q1")
        self.assertEqual(chosen["basis"], "situationally_apt_and_unattempted")

    def test_a_policy_cannot_reach_an_inapplicable_operator(self):
        """Applicability stays a hard filter; only the ordering is learned."""
        chosen = select_operator(self._state(), lane="assumption_reframe", question_id="Q1",
                                 policy={"weights": {"failure_driven_redesign": 1.0}})
        self.assertNotEqual(chosen["operator"], "failure_driven_redesign")

    def test_an_out_of_range_weight_cannot_steamroll_the_choice(self):
        """Weights are rates; a value outside [0, 1] is not a real policy."""
        state = self._state()
        state.theories = [{"id": "T0", "question_id": "Q9", "research_lane": "assumption_reframe",
                           "operator_reused": "assumption_inversion"}]
        state.evidence_records = [{
            "evidence_id": "E1", "theory_id": "T0", "role": "ProbeEvidence",
            "epistemic": "WORLD", "attested": True, "promotion_ok": True,
            "execution_status": "ran", "world_digest": "d", "experiment_digest": "x"}]
        chosen = select_operator(state, lane="assumption_reframe", question_id="Q1",
                                 policy={"weights": {"decomposition": 9999.0}})
        self.assertEqual(chosen["operator"], "assumption_inversion")
        self.assertEqual(chosen["basis"], "own_measured_yield")


if __name__ == "__main__":
    unittest.main()
