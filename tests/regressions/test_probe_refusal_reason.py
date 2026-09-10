"""A refusal reason is repair guidance, so it must be about the claim at hand.

A live run refused a probe for a claim about iris petal geometry and told the
writer to "count the object (protocol field, invariant, index) — not
cut-maintenance hops". Those are the objects of the scenario the sentence was
written for. The reason travels back into the writer's prompt, so a reason
naming another domain's objects steers the retry wrong.
"""

import unittest

from farfield.extras.domain import measure_drift_reason, measure_stays_on_object

CLAIM = ("petal length-width geometry separates iris species better than "
         "sepal length-width geometry")
MECHANISM = "maintain a dynamic min-cut with edge operations"
DRIFTED = "cut-maintenance edge operations per query"


class ProbeRefusalReasonTest(unittest.TestCase):
    def test_the_reason_names_the_claim_s_own_object(self):
        reason = measure_drift_reason(DRIFTED, CLAIM, mechanism=MECHANISM)
        self.assertIn("petal", reason)
        self.assertNotIn("protocol", reason)
        self.assertNotIn("cut-maintenance hops", reason)

    def test_the_reason_names_what_was_counted_instead(self):
        reason = measure_drift_reason(DRIFTED, CLAIM, mechanism=MECHANISM)
        self.assertIn("cut", reason)

    def test_the_refused_condition_is_unchanged(self):
        self.assertFalse(measure_stays_on_object(DRIFTED, CLAIM, mechanism=MECHANISM))
        self.assertTrue(measure_stays_on_object(
            "mean petal length in each species", CLAIM, mechanism=MECHANISM))

    def test_the_plugin_returns_that_reason(self):
        from farfield.extras.plugins import BuiltinPlugin
        import ast

        tree = ast.parse("treatment = 1.0\ncontrol = 0.0\n")
        reason = BuiltinPlugin().validate_probe(
            tree=tree, source="treatment = 1.0", measure=DRIFTED,
            claim=CLAIM, mechanism=MECHANISM)
        self.assertIsNotNone(reason)
        self.assertIn("petal", reason)


if __name__ == "__main__":
    unittest.main()
