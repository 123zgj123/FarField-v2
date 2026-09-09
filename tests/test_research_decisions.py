"""The scheduler must be able to see the things a researcher decides on."""

import tempfile
import unittest
from pathlib import Path

from farfield.extras.openworld.actions import SPECS, ActionInstance
from farfield.extras.openworld.benchmark import (
    make_env, seed_probe_evidence, seed_question, seed_review, seed_spend,
    seed_survey, seed_theory,
)
from farfield.extras.openworld.events import make_event
from farfield.extras.openworld.journal import contingency_plan, research_journal
from farfield.extras.openworld.reducer import apply_events, rebuild_state, state_digest
from farfield.extras.openworld.restart import clean_restart_projection
from farfield.extras.openworld.scheduler import admissible, project_layer_active, schedule_all
from farfield.extras.openworld.state import ScientificState


ROOT = "Does retrieval augmentation improve factual accuracy of small language models?"


class SchedulerLayerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _project(self, **contract):
        env = make_env(self.root / "p", contract=contract or None)
        seed_question(env, "Q1", ROOT)
        seed_survey(env, "Q1")
        seed_theory(env, "T1", "Q1")
        seed_survey(env, "Q1", theory_id="T1")
        return env

    def test_the_layer_is_inert_without_project_state(self):
        """A bare question-and-world run must schedule exactly as it did before."""
        bare = ScientificState(goal="validator versions", world_id="W0")
        bare.add_question(question_id="Q1", text="does history change acceptance?")
        self.assertFalse(project_layer_active(bare))
        ranked = schedule_all(bare, [ActionInstance(SPECS["OBSERVE"], target="Q1",
                                                    frontier_target_id="Q1")])
        self.assertNotIn("central_question_value", ranked[0].scores)

    def test_the_layer_switches_on_with_a_contract(self):
        env = self._project()
        self.assertTrue(project_layer_active(env.state))

    def test_a_fatal_objection_outranks_gathering_more_of_the_same(self):
        env = self._project()
        seed_probe_evidence(env, "E1", "T1", "Q1", sample_size=500)
        seed_review(env, review_id="RF1", severity="fatal", dimension="measurement_validity",
                    objection="the measure cannot answer the question",
                    repair_type="measurement_redesign", requires_new_evidence=True,
                    theory_id="T1", question_id="Q1")
        ranked = schedule_all(env.state, env.eligible())
        self.assertEqual(ranked[0].action.action_type, "REDESIGN")
        routine = [row for row in ranked if row.action.action_type in {"OBSERVE", "PROBE"}]
        for row in routine:
            self.assertEqual(row.scores["blocked_by_fatal_objection"], 1.0)

    def test_repair_attempts_have_diminishing_returns(self):
        env = self._project()
        seed_probe_evidence(env, "E1", "T1", "Q1", sample_size=500, cannot_corroborate=True,
                            validation_gaps=["oracle_failed"])
        seed_review(env, review_id="RF1", severity="fatal", dimension="technical_correctness",
                    objection="cannot establish the claim", repair_type="experiment_redesign",
                    requires_new_evidence=True, theory_id="T1", question_id="Q1")
        first = {row.action.action_type: row.total for row in schedule_all(env.state, env.eligible())}
        for index in (1, 2):
            env.state = apply_events(env.state, [make_event("DesignRevised", {
                "revision_id": f"rev-{index}", "dimension": "technical_correctness",
                "outcome": "open"})], log=env.log)
        seed_spend(env, 5)
        after = schedule_all(env.state, env.eligible())
        pivot = next(row for row in after if row.action.action_type == "PROJECT_PIVOT")
        redesign = next(row for row in after if row.action.action_type == "REDESIGN")
        self.assertGreater(pivot.total, redesign.total)
        self.assertGreater(redesign.scores["redesign_exhaustion"], 0)
        self.assertIn("REDESIGN", first)

    def test_budget_pressure_stops_the_project_opening_new_fronts(self):
        env = self._project(resource_limits={"api_calls": 20, "min_sample_size": 100})
        seed_probe_evidence(env, "E1", "T1", "Q1", sample_size=500, cannot_corroborate=True,
                            validation_gaps=["oracle_failed"])
        seed_review(env, review_id="RF1", severity="fatal", dimension="technical_correctness",
                    objection="cannot establish the claim", repair_type="experiment_redesign",
                    requires_new_evidence=True, theory_id="T1", question_id="Q1")
        for index in (1, 2):
            env.state = apply_events(env.state, [make_event("DesignRevised", {
                "revision_id": f"rev-{index}", "dimension": "technical_correctness",
                "outcome": "open"})], log=env.log)
        seed_spend(env, 3)
        self.assertIn("PROJECT_PIVOT", {a.action_type for a in env.eligible()})
        seed_spend(env, 15)
        self.assertNotIn("PROJECT_PIVOT", {a.action_type for a in env.eligible()})

    def test_a_refused_action_says_why_instead_of_vanishing(self):
        env = self._project()
        action = ActionInstance(SPECS["PROBE"], target="T1", frontier_target_id="Q1",
                                extra={"causal_handle": "h", "measure": "m",
                                       "experiment_proposal": None})
        kept, refused = admissible(env.state, [action])
        self.assertEqual(kept, [])
        self.assertEqual(len(refused), 1)
        self.assertIn("invalid_experiment_proposal", refused[0]["reason"])

    def test_the_tick_view_reports_refusals(self):
        env = self._project()
        event = env.tick()
        self.assertIn("refused", event)


class ProjectionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _project(self):
        env = make_env(self.root / "p")
        seed_question(env, "Q1", ROOT)
        seed_survey(env, "Q1")
        seed_theory(env, "T1", "Q1")
        seed_probe_evidence(env, "E1", "T1", "Q1", sample_size=6)
        return env

    def test_the_journal_is_derived_and_says_so(self):
        journal = research_journal(self._project().state)
        self.assertTrue(journal["is_derived_projection"])
        self.assertEqual(journal["research_contract"]["root_question"], ROOT)
        self.assertTrue(journal["next_decisive_action"]["action"])

    def test_the_journal_names_why_the_strategy_might_not_hold(self):
        env = self._project()
        seed_review(env, review_id="RF1", severity="fatal", dimension="technical_correctness",
                    objection="broken", repair_type="experiment_redesign",
                    requires_new_evidence=True)
        strategy = research_journal(env.state)["strategy"]
        self.assertEqual(strategy["verdict"], "under_doubt")
        self.assertTrue(any("fatal" in text for text in strategy["why_it_might_not_be"]))

    def test_contingency_planning_emits_branches_not_probabilities(self):
        plan = contingency_plan(self._project().state)
        self.assertFalse(plan["is_forecast"])
        self.assertEqual([b["outcome"] for b in plan["branches"]],
                         ["supports", "weakens", "inconclusive"])
        blob = str(plan)
        self.assertNotIn("P(", blob)
        for branch in plan["branches"]:
            self.assertTrue(branch["next"])
            self.assertTrue(branch["does_not_mean"])

    def test_an_underpowered_negative_is_not_read_as_a_refutation(self):
        plan = contingency_plan(self._project().state)
        weakens = next(b for b in plan["branches"] if b["outcome"] == "weakens")
        self.assertIn("power", weakens["means"])

    def test_the_action_projection_carries_the_contract_not_the_transcript(self):
        env = self._project()
        action = next(a for a in env.eligible() if a.action_type == "REVIEW")
        projection = env.project_for(action)
        self.assertEqual(projection["research_contract"]["root_question"], ROOT)
        self.assertIn("research_journal", projection)
        self.assertIsInstance(projection["projection_tokens"], int)

    def test_a_restart_keeps_facts_and_drops_narrative(self):
        env = self._project()
        env.state = apply_events(env.state, [make_event("ActionFailed", {
            "theory_id": "T1", "reason": "the measure never moved"})], log=env.log)
        projection = clean_restart_projection(env.state, reason="dead direction")
        self.assertEqual(projection["root_question"], ROOT)
        self.assertTrue(projection["world_evidence"])
        self.assertTrue(projection["failure_lessons"])
        for lesson in projection["failure_lessons"]:
            self.assertTrue(lesson["applies_when"])
            self.assertTrue(lesson["does_not_apply_when"])
        self.assertIn("speculative_hypothesis_chains", projection["dropped"])

    def test_a_pivot_preserves_world_evidence_and_replays(self):
        env = self._project()
        seed_review(env, review_id="RP1", severity="fatal", dimension="importance",
                    objection="this direction cannot matter", repair_type="project_pivot",
                    requires_new_evidence=True)
        before = {r["evidence_id"] for r in env.state.evidence_records
                  if r.get("epistemic") == "WORLD"}
        pivot = next(a for a in env.eligible() if a.action_type == "PROJECT_PIVOT")
        env.execute(pivot)
        after = {r["evidence_id"] for r in env.state.evidence_records
                 if r.get("epistemic") == "WORLD"}
        self.assertTrue(before <= after)
        self.assertEqual(env.state.project_epoch, 1)
        self.assertTrue(env.state.open_questions)
        self.assertEqual(state_digest(env.state), state_digest(rebuild_state(env.log)))

    def test_a_retired_hypothesis_stays_retired_through_belief_refresh(self):
        env = self._project()
        env.state = apply_events(env.state, [make_event("LineageRetired", {
            "lineage_id": "line-Q1", "reason": "dead", "theory_ids": ["T1"]})], log=env.log)
        self.assertEqual(env.state.theories[0]["status"], "retired")
        env.state = apply_events(env.state, [make_event(
            "EvidenceAdded", {**dict(env.state.evidence_records[0]), "evidence_id": "E2",
                              "experiment_digest": "x2"})], log=env.log)
        self.assertEqual(env.state.theories[0]["status"], "retired")


if __name__ == "__main__":
    unittest.main()
