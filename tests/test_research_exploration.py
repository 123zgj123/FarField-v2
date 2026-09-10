"""Far-field exploration: a score, credit for what produced it, and a real choice.

Three bounded live runs showed the named mechanism was not running. Both runs
that produced a hypothesis recorded `trajectory_applicability: none`,
`source_trajectories_used: []`, and `operator: assumption_removal` — which was
not chosen but was the hard-coded fallback taken whenever no grounded trajectory
was retrieved, which was every time. The installed routing policy reordered
retrieved operators only, so with an empty library it touched nothing, and two
consecutive runs produced nearly identical hypotheses because no mechanism
existed by which the second could differ.
"""

import unittest

from farfield.extras.openworld.events import make_event
from farfield.extras.openworld.exploration import (
    admitted_evidence_for,
    applicable_operators,
    exploration_credit,
    paper_relevance,
    relevance_report,
    select_operator,
    situational_tier,
    tried_operators,
)
from farfield.extras.openworld.objective import (
    SuccessMetric,
    is_breakthrough,
    objective_state,
    score_of,
)
from farfield.extras.openworld.reducer import apply_events
from farfield.extras.openworld.state import ScientificState


ROOT = "does petal geometry separate iris species better than sepal geometry?"

METRIC = {"name": "separation", "source": "separation",
          "direction": "higher_is_better", "min_improvement": 0.05}


def probe(eid, separation=None, **extra):
    row = {
        "evidence_id": eid, "role": "ProbeEvidence", "epistemic": "WORLD",
        "attested": True, "promotion_ok": True, "execution_status": "ran",
        "world_id": "W0", "world_digest": "d0", "experiment_digest": f"x-{eid}",
        "theory_id": "T1", "question_id": "Q1", "outcome": "supports", **extra,
    }
    if separation is not None:
        row["separation"] = separation
    return row


def state(metric=METRIC, *events):
    payload = {"root_question": ROOT}
    if metric:
        payload["success_metric"] = metric
    return apply_events(ScientificState(goal=ROOT),
                        [make_event("ContractSet", payload), *events])


class TaskObjectiveTest(unittest.TestCase):
    """Without a comparable task score, "better" has no definition."""

    def test_an_undeclared_metric_says_so_rather_than_inventing_one(self):
        row = state(metric=None).objective
        self.assertEqual(row["status"], "no_task_metric_declared")
        self.assertIsNone(row["frontier"])

    def test_the_frontier_is_the_best_admitted_result(self):
        current = state(METRIC, *[make_event("EvidenceAdded", probe(e, s))
                                  for e, s in (("E1", 0.30), ("E2", 0.55), ("E3", 0.40))])
        self.assertEqual(current.objective["frontier"], 0.55)
        self.assertEqual(current.objective["frontier_evidence_id"], "E2")

    def test_an_improvement_below_epsilon_is_not_a_breakthrough(self):
        current = state(METRIC, *[make_event("EvidenceAdded", probe(e, s))
                                  for e, s in (("E1", 0.30), ("E2", 0.31))])
        self.assertEqual(current.objective["breakthrough_count"], 1)

    def test_lower_is_better_reverses_the_comparison(self):
        metric = {**METRIC, "direction": "lower_is_better"}
        current = state(metric, *[make_event("EvidenceAdded", probe(e, s))
                                  for e, s in (("E1", 0.90), ("E2", 0.10))])
        self.assertEqual(current.objective["frontier"], 0.10)

    def test_only_admitted_world_evidence_scores(self):
        for bad in ({"epistemic": "GENERATED"}, {"attested": False},
                    {"promotion_ok": False}, {"cannot_corroborate": True},
                    {"execution_status": "blocked"}):
            with self.subTest(row=bad):
                current = state(METRIC, make_event("EvidenceAdded", probe("E1", 0.9, **bad)))
                self.assertEqual(current.objective["results"], 0)

    def test_a_metric_may_only_read_a_registered_field(self):
        """Otherwise the scorer and the thing scored share an author."""
        metric = SuccessMetric.from_dict({**METRIC, "source": "model_confidence"})
        self.assertFalse(metric.is_declared)
        self.assertIsNone(score_of(metric, probe("E1", 0.9, model_confidence=0.99)))

    def test_a_non_numeric_or_boolean_score_is_refused(self):
        metric = SuccessMetric.from_dict(METRIC)
        for value in ("high", True, None):
            with self.subTest(value=value):
                self.assertIsNone(score_of(metric, probe("E1", separation=value)))

    def test_a_breakthrough_is_visible_as_a_tick_level_change(self):
        before = state(METRIC, make_event("EvidenceAdded", probe("E1", 0.30)))
        after = apply_events(before, [make_event("EvidenceAdded", probe("E2", 0.90))])
        self.assertTrue(is_breakthrough(before, after))
        self.assertFalse(is_breakthrough(before, before))

    def test_the_objective_replays_from_the_event_log(self):
        from farfield.extras.openworld.events import EventLog
        from farfield.extras.openworld.reducer import rebuild_state, state_digest

        log = EventLog(baseline=ScientificState(goal=ROOT).to_dict())
        current = apply_events(ScientificState(goal=ROOT), [
            make_event("ContractSet", {"root_question": ROOT, "success_metric": METRIC}),
            make_event("EvidenceAdded", probe("E1", 0.3)),
            make_event("EvidenceAdded", probe("E2", 0.9)),
        ], log=log)
        self.assertEqual(state_digest(current), state_digest(rebuild_state(log)))
        self.assertEqual(rebuild_state(log).objective["frontier"], 0.9)


class ExplorationCreditTest:
    pass


class CreditTest(unittest.TestCase):
    """A policy over exploration with no attribution is fitting noise."""

    def _project(self):
        return state(METRIC,
            make_event("TheoryCreated", {"id": "T1", "question_id": "Q1", "text": "a",
                                         "research_lane": "assumption_reframe",
                                         "operator_reused": "assumption_removal"}),
            make_event("TheoryCreated", {"id": "T2", "question_id": "Q1", "text": "b",
                                         "research_lane": "unconstrained",
                                         "operator_reused": "unconstrained_exploration"}),
            make_event("EvidenceAdded", probe("E1", 0.30, theory_id="T1")),
            make_event("EvidenceAdded", probe("E2", 0.90, theory_id="T1")),
            make_event("ActionFailed", {"theory_id": "T2", "reason": "no handle"}))

    def test_results_are_attributed_to_the_move_that_produced_them(self):
        moves = {(m["lane"], m["operator"]): m
                 for m in exploration_credit(self._project())["moves"]}
        good = moves[("assumption_reframe", "assumption_removal")]
        self.assertEqual(good["admitted_evidence"], 2)
        self.assertEqual(good["decision_relevant"], 2)
        self.assertEqual(good["breakthroughs"], 2)
        self.assertEqual(moves[("unconstrained", "unconstrained_exploration")]["failures"], 1)

    def test_a_competing_explanation_is_not_credited_as_a_hypothesis(self):
        current = apply_events(self._project(), [make_event("TheoryCreated", {
            "id": "T3", "question_id": "Q1", "text": "alt", "role": "competing_explanation",
            "research_lane": "assumption_reframe", "operator_reused": "assumption_removal"})])
        moves = {(m["lane"], m["operator"]): m for m in exploration_credit(current)["moves"]}
        self.assertEqual(moves[("assumption_reframe", "assumption_removal")]["hypotheses"], 1)

    def test_yield_rate_is_per_hypothesis(self):
        moves = {m["operator"]: m for m in exploration_credit(self._project())["moves"]}
        self.assertEqual(moves["assumption_removal"]["yield_rate"], 2.0)

    def test_evidence_the_kernel_refused_earns_no_credit(self):
        current = state(METRIC,
            make_event("TheoryCreated", {"id": "T1", "question_id": "Q1", "text": "a",
                                         "research_lane": "assumption_reframe",
                                         "operator_reused": "assumption_removal"}),
            make_event("EvidenceAdded", probe("E1", 0.9, epistemic="GENERATED",
                                              attested=False, promotion_ok=False)))
        moves = {m["operator"]: m for m in exploration_credit(current)["moves"]}
        self.assertEqual(moves["assumption_removal"]["admitted_evidence"], 0)


class OperatorSelectionTest(unittest.TestCase):
    """The transformation is chosen, not defaulted."""

    def test_a_bare_question_admits_only_situation_free_operators(self):
        names = applicable_operators(state())
        self.assertIn("assumption_removal", names)
        self.assertNotIn("failure_driven_redesign", names)
        self.assertNotIn("mechanism_replacement", names)

    def test_a_failure_admits_redesign_operators(self):
        current = state(METRIC, make_event("ActionFailed", {"theory_id": "T1", "reason": "x"}))
        self.assertIn("failure_driven_redesign",
                      applicable_operators(current, parent={"id": "T1"}))

    def test_weakening_evidence_calls_for_a_different_account(self):
        current = state(METRIC,
            make_event("TheoryCreated", {"id": "T1", "question_id": "Q1", "text": "a"}),
            make_event("EvidenceAdded", probe("E1", 0.1, outcome="weakens")))
        tier = situational_tier(current, question_id="Q1", parent={"id": "T1"})
        self.assertEqual(tier[0], "representation_change")
        self.assertIn("mechanism_replacement", tier)

    def test_an_inconclusive_result_asks_about_the_measurement(self):
        current = state(METRIC,
            make_event("TheoryCreated", {"id": "T1", "question_id": "Q1", "text": "a"}),
            make_event("EvidenceAdded", probe("E1", 0.0, outcome="uninformative")))
        tier = situational_tier(current, question_id="Q1", parent={"id": "T1"})
        self.assertTrue({"objective_change", "verifier_shift"} & set(tier))

    def test_the_choice_is_never_alphabetical(self):
        """With no credit and no policy the situation still decides."""
        current = state(METRIC,
            make_event("TheoryCreated", {"id": "T1", "question_id": "Q1", "text": "a"}),
            make_event("EvidenceAdded", probe("E1", 0.1, outcome="weakens")))
        chosen = select_operator(current, lane="assumption_reframe",
                                 question_id="Q1", parent={"id": "T1"})
        self.assertEqual(chosen["operator"], "representation_change")
        self.assertEqual(chosen["basis"], "situationally_apt_and_unattempted")

    def test_the_same_question_is_not_asked_the_same_way_twice(self):
        current = state()
        first = select_operator(current, lane="assumption_reframe", question_id="Q1")
        current = apply_events(current, [make_event("TheoryCreated", {
            "id": "T1", "question_id": "Q1", "text": "a",
            "research_lane": "assumption_reframe",
            "operator_reused": first["operator"]})])
        second = select_operator(current, lane="assumption_reframe", question_id="Q1")
        self.assertNotEqual(second["operator"], first["operator"])
        self.assertEqual(tried_operators(current, "Q1"), (first["operator"],))

    def test_an_installed_policy_reaches_the_actual_choice(self):
        """Its only interface used to reorder retrieved operators, and the
        library was empty in every live run, so it touched nothing."""
        current = state()
        plain = select_operator(current, lane="assumption_reframe", question_id="Q1")
        other = next(n for n in applicable_operators(current) if n != plain["operator"])
        weighted = select_operator(current, lane="assumption_reframe", question_id="Q1",
                                   policy={"weights": {other: 10.0}})
        self.assertEqual(weighted["operator"], other)
        self.assertTrue(weighted["policy_weighted"])

    def test_this_projects_own_credit_outranks_the_policy(self):
        current = state(METRIC,
            make_event("TheoryCreated", {"id": "T1", "question_id": "Q2", "text": "a",
                                         "research_lane": "assumption_reframe",
                                         "operator_reused": "assumption_inversion"}),
            make_event("EvidenceAdded", probe("E1", 0.9, theory_id="T1", question_id="Q2")))
        chosen = select_operator(current, lane="assumption_reframe", question_id="Q1",
                                 policy={"weights": {"decomposition": 99.0}})
        self.assertEqual(chosen["operator"], "assumption_inversion")

    def test_the_unconstrained_lane_keeps_its_own_marker(self):
        self.assertEqual(
            select_operator(state(), lane="unconstrained", question_id="Q1")["operator"],
            "unconstrained_exploration")

    def test_selection_records_what_it_considered(self):
        chosen = select_operator(state(), lane="assumption_reframe", question_id="Q1")
        self.assertTrue(chosen["considered"])
        self.assertIn("basis", chosen)


class SharedEvidencePredicateTest(unittest.TestCase):
    """Two parts of one decision disagreeing about what evidence exists is a defect."""

    def test_the_hop_gate_and_the_operator_choice_read_the_same_rows(self):
        current = state(METRIC, make_event("EvidenceAdded", probe(
            "E1", 0.1, theory_id="T1", outcome="weakens")))
        rows = admitted_evidence_for(current, "T1")
        self.assertEqual([row["evidence_id"] for row in rows], ["E1"])
        self.assertEqual(situational_tier(current, question_id="Q1",
                                          parent={"id": "T1"})[0], "representation_change")

    def test_a_row_missing_execution_identity_is_not_parent_evidence(self):
        current = state(METRIC, make_event("EvidenceAdded", {
            "evidence_id": "E9", "theory_id": "T1", "epistemic": "WORLD",
            "attested": True, "execution_status": "ran"}))
        self.assertEqual(admitted_evidence_for(current, "T1"), [])


class RetrievalRelevanceTest(unittest.TestCase):
    """A live survey anchored an iris question to a conic-programming paper."""

    LIVE = [
        {"cite_id": "2609.09449", "title": "Afterimage Slow Regions in First-Order "
                                           "Methods for Linear Conic Programming", "abstract": ""},
        {"cite_id": "2508.11724", "title": "BeeNet: Reconstructing Flower Shapes from "
                                           "Electric Fields using Deep Learning", "abstract": ""},
        {"cite_id": "on-topic", "title": "Discriminant analysis of iris species using "
                                         "petal and sepal geometry", "abstract": "separating "
                                         "iris species by petal and sepal measurements"},
    ]

    def test_the_actually_retrieved_off_topic_papers_are_recognised(self):
        report = relevance_report(ROOT, self.LIVE)
        self.assertIn("2609.09449", report["off_topic"])
        self.assertIn("2508.11724", report["off_topic"])
        self.assertIn("on-topic", report["on_topic"])

    def test_an_all_off_topic_survey_reports_a_gap_rather_than_anchoring(self):
        report = relevance_report(ROOT, self.LIVE[:2])
        self.assertEqual(report["gap"], "no_retrieved_paper_is_on_topic")
        self.assertEqual(report["usable"], [])

    def test_off_topic_papers_are_kept_and_reported_not_dropped(self):
        report = relevance_report(ROOT, self.LIVE)
        self.assertEqual(len(report["papers"]), 3)

    def test_relevance_is_graded_not_binary(self):
        self.assertEqual(
            paper_relevance(ROOT, {"title": "Petal wax layers and water loss"})["relevance"],
            "adjacent")

    def test_no_root_question_yields_unknown_rather_than_a_guess(self):
        self.assertEqual(paper_relevance("", {"title": "anything"})["relevance"], "unknown")


if __name__ == "__main__":
    unittest.main()
