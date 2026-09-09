"""The root question has to survive the project that pursues it."""

import unittest

from farfield.extras.openworld.contract import (
    ResearchContract,
    alignment_of_question,
    anchor_terms,
    root_alignment,
)
from farfield.extras.openworld.events import make_event
from farfield.extras.openworld.reducer import apply_events
from farfield.extras.openworld.state import ScientificState


ROOT = "Does retrieval augmentation improve factual accuracy of small language models?"


class ContractTest(unittest.TestCase):
    def setUp(self):
        self.contract = ResearchContract.from_dict({"root_question": ROOT})

    def test_anchor_terms_drop_stopwords_and_fold_plurals(self):
        terms = anchor_terms("Do the retrieval models improve accuracy?")
        self.assertIn("retrieval", terms)
        self.assertIn("model", terms)
        self.assertNotIn("the", terms)

    def test_a_narrower_version_of_the_root_question_is_aligned(self):
        verdict = root_alignment(
            self.contract,
            text="Does retrieval augmentation improve factual accuracy under distribution shift?")
        self.assertEqual(verdict.status, "aligned")

    def test_an_easier_measurable_proxy_is_drift_not_progress(self):
        verdict = root_alignment(self.contract, text="How should token overlap be scored?")
        self.assertEqual(verdict.status, "drifted")
        self.assertIn("no_aligned_parent_declared", verdict.reasons)

    def test_a_declared_instrumental_subgoal_is_allowed(self):
        verdict = root_alignment(
            self.contract,
            text="How should token overlap be scored?",
            justification="needed to measure factual accuracy for the retrieval comparison",
            instrumental_for="Q1",
            depth=1)
        self.assertEqual(verdict.status, "instrumental")

    def test_instrumental_chains_cannot_run_away_from_the_root(self):
        verdict = root_alignment(
            self.contract,
            text="How should token overlap be scored?",
            justification="needed to measure factual accuracy",
            instrumental_for="Q9",
            depth=5)
        self.assertEqual(verdict.status, "drifted")
        self.assertTrue(any("instrumental_depth" in r for r in verdict.reasons))

    def test_forbidden_scope_changes_are_refused_outright(self):
        contract = ResearchContract.from_dict(
            {"root_question": ROOT, "forbidden_scope_changes": ["synthetic benchmarks"]})
        verdict = root_alignment(
            contract, text="Does retrieval augmentation improve factual accuracy "
                           "on synthetic benchmarks?")
        self.assertEqual(verdict.status, "drifted")

    def test_root_question_is_immutable_within_a_project(self):
        state = ScientificState()
        state = apply_events(state, [make_event("ContractSet", {"root_question": ROOT})])
        state = apply_events(state, [make_event("ContractSet", {"root_question": "something else"})])
        self.assertEqual(state.contract["root_question"], ROOT)
        self.assertTrue(any(row.get("kind") == "contract_change_refused"
                            for row in state.artifacts))

    def test_amendment_records_provenance_and_keeps_the_root(self):
        amended = self.contract.amended({"target_quality": "conference",
                                         "root_question": "a different project"})
        self.assertEqual(amended.root_question, ROOT)
        self.assertEqual(amended.target_quality, "conference")
        self.assertEqual(len(amended.amendments), 1)

    def test_drift_is_recorded_as_debt_on_the_canonical_state(self):
        state = ScientificState()
        state = apply_events(state, [
            make_event("ContractSet", {"root_question": ROOT}),
            make_event("QuestionCreated", {"id": "Q2", "text": "how do we score token overlap?"}),
        ])
        self.assertEqual(state.debt["goal_drift_debt"], 1)
        self.assertEqual(state.open_questions[0]["root_alignment"], "drifted")

    def test_alignment_resolves_a_declared_parent_chain(self):
        known = [
            {"id": "Q1", "text": ROOT},
            {"id": "Q2", "text": "how should token overlap be scored?",
             "instrumental_for": "Q1",
             "root_link": "scores factual accuracy for the retrieval comparison"},
        ]
        self.assertEqual(alignment_of_question(self.contract, known[1], known=known).status,
                         "instrumental")


if __name__ == "__main__":
    unittest.main()
