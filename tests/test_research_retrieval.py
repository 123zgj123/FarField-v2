"""Retrieval must be able to fire, and must never erase a negation.

Applicability conditions and current research states are both free text a model
extracted from different papers. Requiring them to be byte-identical is not a
strict test — it is a test that never fires, which left the trajectory lane a
claimed capability the runtime did not have and did not report losing.
"""

import unittest

from farfield.extras.explore import (
    CONDITION_CONTAINMENT,
    CONDITION_MIN_SHARED,
    ResearchPaperState,
    ResearchTransition,
    condition_match,
    condition_polarity,
    retrieve_transitions,
)


GAP = "attention is quadratic in sequence length"


def transition(condition=GAP, *, operator="representation_change", failure=None,
               source="a", target="b"):
    return ResearchTransition(
        source_state=ResearchPaperState(cite_id=source, bottleneck_gap=condition),
        target_state=ResearchPaperState(cite_id=target, bottleneck_gap="linear attention"),
        operator=operator, status="extracted",
        applicability_conditions={"bottleneck_gap": condition},
        known_failure_conditions=failure or {},
        changed_component="representation",
        source_cite_id=source, target_cite_id=target)


class PolarityTest(unittest.TestCase):
    def test_explicit_negation_markers_are_detected(self):
        for text in ("x is not quadratic", "the method cannot scale",
                     "no improvement was observed", "it fails beyond ten nodes",
                     "the approach lacks a baseline"):
            with self.subTest(text=text):
                self.assertEqual(condition_polarity(text), "negative")

    def test_plain_statements_are_positive(self):
        for text in (GAP, "the cache reduces scanned records", "accuracy increases"):
            with self.subTest(text=text):
                self.assertEqual(condition_polarity(text), "positive")

    def test_prefixes_are_not_read_as_negation(self):
        """Guessing at non-/in- prefixes would cause the flip this guard prevents."""
        self.assertEqual(condition_polarity("nonlinear inference is intractable"), "positive")


class ConditionMatchTest(unittest.TestCase):
    def test_identical_text_establishes_applicability(self):
        self.assertEqual(condition_match(GAP, GAP)["basis"], "exact")

    def test_whitespace_and_case_still_establish_it(self):
        self.assertEqual(
            condition_match(GAP, "Attention is quadratic in sequence length ")["basis"], "exact")

    def test_a_paraphrase_proposes_rather_than_establishes(self):
        row = condition_match(GAP, "attention cost grows quadratically with sequence length")
        self.assertEqual(row["basis"], "overlap")
        self.assertGreaterEqual(row["shared"], CONDITION_MIN_SHARED)
        self.assertGreaterEqual(row["score"], CONDITION_CONTAINMENT)

    def test_a_negated_near_duplicate_is_refused(self):
        """The most dangerous available false match: same words, opposite sense."""
        row = condition_match(GAP, "attention is not quadratic in sequence length")
        self.assertEqual(row["basis"], "none")
        self.assertEqual(row["reason"], "polarity_differs")

    def test_a_negated_condition_does_not_match_a_positive_state(self):
        row = condition_match("attention is not quadratic in sequence length", GAP)
        self.assertEqual(row["reason"], "polarity_differs")

    def test_two_negated_texts_may_still_match_each_other(self):
        row = condition_match("the method cannot scale beyond ten nodes",
                              "the method cannot scale past ten nodes")
        self.assertEqual(row["basis"], "overlap")

    def test_thin_overlap_is_refused(self):
        row = condition_match(GAP, "the quadratic cost of attention limits long contexts")
        self.assertEqual(row["basis"], "none")
        self.assertEqual(row["reason"], "below_overlap_threshold")

    def test_unrelated_text_is_refused(self):
        self.assertEqual(
            condition_match(GAP, "the optimizer diverges on sparse gradients")["basis"], "none")

    def test_unknown_or_empty_conditions_never_match(self):
        for value in ("", "   ", None):
            with self.subTest(value=value):
                self.assertEqual(condition_match(GAP, value)["basis"], "none")


class RetrievalTest(unittest.TestCase):
    def test_an_exact_condition_is_retrieved_as_established(self):
        rows = retrieve_transitions({"bottleneck_gap": GAP}, [transition()])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].retrieval["applicability"], "established")

    def test_a_paraphrased_state_now_retrieves_at_all(self):
        rows = retrieve_transitions(
            {"bottleneck_gap": "attention cost grows quadratically with sequence length"},
            [transition()])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].retrieval["applicability"], "proposed")
        self.assertIn("does not establish", rows[0].retrieval["note"])

    def test_a_negated_state_retrieves_nothing(self):
        self.assertEqual(retrieve_transitions(
            {"bottleneck_gap": "attention is not quadratic in sequence length"},
            [transition()]), [])

    def test_a_known_failure_condition_excludes_the_transition(self):
        """The one transition that must not be reused is the one recorded as
        failing under exactly these circumstances."""
        rows = retrieve_transitions({"bottleneck_gap": GAP},
                                    [transition(failure={"bottleneck_gap": GAP})])
        self.assertEqual(rows, [])

    def test_a_failure_condition_elsewhere_does_not_exclude(self):
        rows = retrieve_transitions({"bottleneck_gap": GAP},
                                    [transition(failure={"bottleneck_gap": "streaming inputs only"})])
        self.assertEqual(len(rows), 1)

    def test_a_contradicted_condition_still_excludes_the_transition(self):
        """A condition the current state denies is a disagreement, and vetoes."""
        row = transition()
        row = type(row)(**{**row.to_dict(),
                           "source_state": row.source_state, "target_state": row.target_state,
                           "applicability_conditions": {
                               "bottleneck_gap": GAP,
                               "representation": "the index is a dense token grid"}})
        rows = retrieve_transitions(
            {"bottleneck_gap": GAP,
             "representation": "the index is not a dense token grid"}, [row])
        self.assertEqual(rows, [])

    def test_an_unrelated_condition_abstains_and_is_named(self):
        """Unrelated is not disagreement.

        Counting "no lexical relation" as a disagreement made this lane
        unreachable outside a fixture: a survey anchor holds a known value for
        every structural field, so a condition drawn from someone else's paper
        always disagreed with something. A real citation graph produced seven
        grounded transitions and retrieved none of them.
        """
        row = transition()
        row = type(row)(**{**row.to_dict(),
                           "source_state": row.source_state, "target_state": row.target_state,
                           "applicability_conditions": {"bottleneck_gap": GAP,
                                                        "representation": "dense token grid"}})
        rows = retrieve_transitions(
            {"bottleneck_gap": GAP, "representation": "a sparse retrieval index"}, [row])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].retrieval["applicability"], "proposed",
                         "one condition established and one unexamined is not "
                         "established applicability")
        self.assertEqual(rows[0].retrieval["unmatched_conditions"], ["representation"])

    def test_a_fully_matched_transition_outranks_a_partly_unmatched_one(self):
        clean = transition(source="clean", target="c2")
        partial = transition(source="partial", target="p2")
        partial = type(partial)(**{**partial.to_dict(),
                                   "source_state": partial.source_state,
                                   "target_state": partial.target_state,
                                   "applicability_conditions": {
                                       "bottleneck_gap": GAP,
                                       "representation": "dense token grid"}})
        rows = retrieve_transitions(
            {"bottleneck_gap": GAP, "representation": "a sparse retrieval index"},
            [partial, clean])
        self.assertEqual([r.source_cite_id for r in rows], ["clean", "partial"])
        self.assertEqual(rows[0].retrieval["applicability"], "established")

    def test_unknown_current_fields_do_not_vote(self):
        rows = retrieve_transitions({"bottleneck_gap": GAP, "representation": "unknown"},
                                    [transition()])
        self.assertEqual(len(rows), 1)

    def test_established_matches_outrank_proposed_ones(self):
        rows = retrieve_transitions(
            {"bottleneck_gap": GAP},
            [transition("self-attention is quadratic in the input sequence length",
                        source="p", target="q"),
             transition(source="x", target="y")])
        self.assertEqual(rows[0].retrieval["applicability"], "established")
        self.assertEqual(rows[1].retrieval["applicability"], "proposed")

    def test_ranking_is_deterministic(self):
        pool = [transition(source="b", target="c"), transition(source="a", target="d")]
        first = [t.source_cite_id for t in retrieve_transitions({"bottleneck_gap": GAP}, pool)]
        second = [t.source_cite_id for t in retrieve_transitions({"bottleneck_gap": GAP},
                                                                 list(reversed(pool)))]
        self.assertEqual(first, second)

    def test_a_blocked_transition_is_never_retrieved(self):
        row = transition()
        blocked = type(row)(**{**row.to_dict(), "source_state": row.source_state,
                               "target_state": row.target_state, "status": "blocked"})
        self.assertEqual(retrieve_transitions({"bottleneck_gap": GAP}, [blocked]), [])

    def test_retrieval_metadata_is_recomputed_not_trusted(self):
        """A persisted verdict from an earlier query must not be believed."""
        row = transition()
        forged = type(row)(**{**row.to_dict(), "source_state": row.source_state,
                              "target_state": row.target_state,
                              "retrieval": {"applicability": "established"}})
        rows = retrieve_transitions({"bottleneck_gap": "an entirely different bottleneck"},
                                    [forged])
        self.assertEqual(rows, [])


class OperatorVocabularyTest(unittest.TestCase):
    """CASE 8: an operator the system can choose must be one it can carry out.

    A live run recovered a grounded transition, named its operator, and was
    then blocked with "unknown reframe operator 'failure_driven_redesign'".
    The research layer's vocabulary had fifteen operators and the card
    generator's table had four, so most of what the lane could find could not
    be acted on — the failure appeared only at the moment the lane finally
    started working.
    """

    def test_every_research_operator_can_be_generated(self):
        from farfield.extras.explore import RESEARCH_OPERATORS
        from farfield.extras.reframe import OPERATORS

        missing = [name for name in RESEARCH_OPERATORS if name not in OPERATORS]
        self.assertEqual(missing, [],
                         "a transition naming these operators is retrievable and "
                         "then unusable")

    def test_no_operator_is_registered_without_an_instruction(self):
        """A name with nothing behind it steers generation no better than none."""
        from farfield.extras.reframe import OPERATORS

        for name, text in OPERATORS.items():
            with self.subTest(operator=name):
                self.assertGreater(len(text.split()), 15)
                self.assertNotIn(name.replace("_", " "), text.casefold(),
                                 "the instruction only restates the operator name")


if __name__ == "__main__":
    unittest.main()
