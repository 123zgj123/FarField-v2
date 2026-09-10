"""Every live experiment was refused for the same reason, and it was unreachable.

Two bounded live segments each produced one probe and both were marked
`cannot_corroborate` by `ablation_required`, so neither could ever score against
the declared task metric. The rule reads: a competing explanation must name
another declared lever of this world and the experiment must shut it; an
alternative naming no lever is also required, because the mechanism is then not
identified.

For fisher-iris the levers are `dropout` and `noise`. The competing explanation
the science actually had — "one dominant coordinate carries the effect rather
than redundancy across both" — is neither of them, so no design could ever
satisfy the rule and every result was permanently unidentified.

Two further blockers sat behind it. `discriminator_registered` required the
proposal's observable string to equal the registered identifier, though the two
are written independently; and it mapped only increase/decrease onto arm
directions, so an alternative predicting "unchanged" — the most common competing
explanation there is — could never register.
"""

import unittest

from farfield.extras.evidence import ablation_reason, ablation_required
from farfield.extras.openworld.workers import _names_observable


LEVERS = ("dropout", "noise")


class AblationReasonTest(unittest.TestCase):
    """The boolean collapsed two situations that call for different answers."""

    def test_an_unshut_competing_lever_is_named_as_such(self):
        reason = ablation_reason("the noise lever explains it", "we vary dropout only",
                                 levers=LEVERS, world_lever="dropout")
        self.assertTrue(reason.startswith("unshut_competing_lever"))
        self.assertIn("noise", reason)

    def test_a_shut_competing_lever_needs_nothing(self):
        self.assertEqual(ablation_reason("the noise lever explains it",
                                         "we hold noise fixed while varying dropout",
                                         levers=LEVERS, world_lever="dropout"), "")

    def test_an_alternative_naming_no_lever_is_a_different_situation(self):
        self.assertEqual(
            ablation_reason("one dominant coordinate carries the effect",
                            "drop the stronger coordinate versus the weaker",
                            levers=LEVERS, world_lever="dropout"),
            "alternative_names_no_lever_of_this_world")

    def test_an_empty_alternative_is_its_own_reason(self):
        self.assertEqual(ablation_reason("", "anything", levers=LEVERS,
                                         world_lever="dropout"),
                         "no_alternative_stated")

    def test_a_world_without_levers_requires_nothing(self):
        self.assertEqual(ablation_reason("anything", "anything", levers=()), "")

    def test_the_reason_agrees_with_the_original_boolean(self):
        cases = [
            ("the noise lever explains it", "we vary dropout only"),
            ("the noise lever explains it", "we hold noise fixed"),
            ("one dominant coordinate", "drop stronger versus weaker"),
            ("", "anything"),
        ]
        for alternative, experiment in cases:
            with self.subTest(alternative=alternative):
                self.assertEqual(
                    bool(ablation_reason(alternative, experiment, levers=LEVERS,
                                         world_lever="dropout")),
                    ablation_required(alternative, experiment, levers=LEVERS,
                                      world_lever="dropout"))


class ObservableIsNamedNotRestatedTest(unittest.TestCase):
    """Two independently written strings had to be equal."""

    REGISTERED = "mean_pairwise_distance"
    LIVE = "dropout-induced petal-minus-sepal mean_pairwise_distance contrast"

    def test_the_live_declaration_names_the_registered_observable(self):
        self.assertTrue(_names_observable(self.LIVE, self.REGISTERED))

    def test_an_exact_match_still_counts(self):
        self.assertTrue(_names_observable(self.REGISTERED, self.REGISTERED))

    def test_a_different_observable_does_not(self):
        self.assertFalse(_names_observable("mean_column_spread contrast", self.REGISTERED))

    def test_a_substring_of_a_longer_identifier_does_not_count(self):
        """`mean_pairwise_distance_squared` is not `mean_pairwise_distance`."""
        self.assertFalse(_names_observable("mean_pairwise_distance_squared",
                                           self.REGISTERED))
        self.assertFalse(_names_observable("xmean_pairwise_distance", self.REGISTERED))

    def test_empty_sides_never_match(self):
        for left, right in (("", self.REGISTERED), (self.LIVE, ""), ("", "")):
            with self.subTest(left=left, right=right):
                self.assertFalse(_names_observable(left, right))


class ReliefRequiresAnExplicitLinkTest(unittest.TestCase):
    """A registered comparison against competitor C says nothing about a prose
    alternative A, and the two are not required to be the same thing."""

    def _gate(self, *, discriminator, linked):
        from farfield.extras.openworld.workers import LegacyResearchWorkers
        from farfield.extras.diagnose import diagnosis_from_payload

        class World:
            root = None
            schema = "numeric_table"

        diagnosis = diagnosis_from_payload("card", {
            "alternative": "one dominant coordinate carries the effect",
            "experiment": "drop the stronger coordinate versus the weaker",
            "treatment_arm": "t", "control_arm": "c",
            "expected_direction": "treatment_higher",
            "alternative_direction": "treatment_lower",
            "expected_if_alternative": "the contrast reverses under coordinate ranking",
            "alternative_hypothesis_id": "card:alternative:0" if linked else "",
            "margin": 0.05, "margin_reason": "r",
            "world_lever": "dropout", "world_observable": "mean_pairwise_distance",
        })
        import farfield.extras.dynworld as dynworld
        original = dynworld.levers_of
        dynworld.levers_of = lambda world: LEVERS
        try:
            worker = LegacyResearchWorkers.__new__(LegacyResearchWorkers)
            gate = LegacyResearchWorkers._gates(
                worker, card=None, diagnosis=diagnosis, spec=None,
                result=type("R", (), {"treatment": 1.0, "control": 0.5,
                                      "metrics": {}, "status": "ran"})(),
                world=World(), folder=None, tier=None,
                discriminator=discriminator,
                discriminated_alternative="card:alternative:0" if linked else "")
        finally:
            dynworld.levers_of = original
        return gate

    def test_an_unlinked_discriminator_grants_no_relief(self):
        gate = self._gate(discriminator=True, linked=False)
        self.assertTrue(gate["ablation_required"])
        self.assertTrue(gate.get("cannot_corroborate"))

    def test_a_linked_discriminator_identifies_the_mechanism(self):
        gate = self._gate(discriminator=True, linked=True)
        self.assertFalse(gate["ablation_required"])
        self.assertEqual(gate["mechanism_identified"],
                         "registered_discriminating_comparison")

    def test_no_discriminator_grants_no_relief_however_linked(self):
        gate = self._gate(discriminator=False, linked=True)
        self.assertTrue(gate["ablation_required"])

    def test_the_reason_is_recorded_either_way(self):
        self.assertEqual(self._gate(discriminator=False, linked=False)["ablation_reason"],
                         "alternative_names_no_lever_of_this_world")


if __name__ == "__main__":
    unittest.main()
