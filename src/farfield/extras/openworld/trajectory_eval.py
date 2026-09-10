"""Long-horizon trajectory evaluation and capability metrics.

Single-decision scenarios catch a controller that answers one situation wrongly.
They cannot catch the failures that only appear over a long run: an objection
that stands for twenty ticks while the agent keeps gathering more of the same
evidence, a root question that is never formally abandoned but is no longer what
anything is measuring, a budget spent evenly across everything instead of on the
decision that mattered.

This module runs the real controller against a scripted research world for tens
of actions and reports the capability metrics from the evaluation contract:
time to redesign, wasted actions after a fatal objection, caveat-only repair
rate, goal drift, decision-relevant evidence yield, resource efficiency.

The world is scripted, not live. It is a stand-in that answers PROBE and SURVEY
deterministically so the *controller's* behaviour is what varies. A good score
here says the control loop allocates its actions sensibly; it says nothing about
whether the science would be any good.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import OpenWorld
from .actions import PROBE, PROJECT_PIVOT, REDESIGN, REVIEW, SURVEY, THEORIZE, VERIFY
from .events import make_event
from .kernel import CandidateResult
from .exploration import exploration_credit
from .quality import open_reviews
from .reducer import rebuild_state, state_digest
from .termination import readiness


ROUTINE = frozenset({"OBSERVE", "PROBE", "SURVEY", "THEORIZE", "ASK"})


@dataclass
class ScriptedWorld:
    """A deterministic stand-in world. It answers actions; it never decides them.

    ``probe_script`` is consumed in order: each entry is the evidence a PROBE
    would produce. Entries deliberately include the hard cases — an underpowered
    positive, a result with validation gaps — so the controller has something to
    exercise judgment on.
    """

    probe_script: list[dict[str, Any]] = field(default_factory=list)
    survey_works: int = 3
    fixed_operator: bool = False
    policy: dict[str, Any] | None = None
    world_id: str = "w0-primary"
    world_digest: str = "d0"
    heldout_id: str = "w1-heldout"
    heldout_digest: str = "d1"
    _probes: int = 0
    _theories: int = 0
    _surveys: int = 0

    def executors(self) -> dict[str, Any]:
        return {SURVEY: self.survey, THEORIZE: self.theorize, PROBE: self.probe,
                VERIFY: self.verify}

    def survey(self, action, state, **kwargs):
        self._surveys += 1
        qid = str(action.target or "")
        artifact = {
            "id": f"survey-{self._surveys}", "kind": "literature_survey",
            "question_id": qid, "theory_id": str(action.extra.get("theory_id") or ""),
            "citations": [f"24{index:02d}.0000{index}" for index in range(self.survey_works)],
            "works": [{"arxiv_id": f"24{index:02d}.0000{index}", "title": f"prior {index}",
                       "abstract": "a"} for index in range(self.survey_works)],
            "prior": {"kills": False},
        }
        return CandidateResult(status="surveyed", events=[make_event(
            "ArtifactAdded", artifact, action_type=SURVEY,
            frontier_target_id=action.frontier_target_id)], extras=artifact)

    def theorize(self, action, state, **kwargs):
        from .exploration import select_operator
        from .state import ScientificState

        self._theories += 1
        qid = str(action.target or "")
        tid = f"T{self._theories}"
        lane = str(action.extra.get("research_lane") or "assumption_reframe")
        parent = next((t for t in state.get("theories", [])
                       if t.get("id") == action.extra.get("parent_theory_id")), None)
        if self.fixed_operator:
            # The behaviour before operator selection existed: whatever the
            # absence of a grounded trajectory left behind, every time.
            selection = {"operator": "assumption_removal", "basis": "hard_coded_fallback"}
        else:
            selection = select_operator(
                ScientificState.from_dict(dict(state)), lane=lane,
                question_id=qid, parent=parent, policy=self.policy)
        claim = f"retrieval augmentation improves factual accuracy ({self._theories})"
        theory = {
            "id": tid, "question_id": qid,
            "text": f"retrieval augmentation improves factual accuracy via mechanism "
                    f"{self._theories}",
            "claim": claim,
            "epistemic": "GENERATED", "lineage_id": f"line-{qid}",
            "assumptions": ["retrieval quality is held constant"],
            "research_lane": lane,
            "operator_reused": selection["operator"],
            "operator_selection": selection,
            "hop": int(action.extra.get("hop") or 1),
            "parent_theory_id": str(action.extra.get("parent_theory_id") or ""),
            # The executable handle a PROBE needs. In a live run this is a
            # compiled card; here it is the minimum the controller reads.
            "card": {"card_id": tid, "idea_kind": "probe", "claim": claim,
                     "mechanism": "retrieved context constrains generation",
                     "prediction": "accuracy increases with retrieval enabled",
                     "world_lever": "retrieval_enabled", "world_observable": "accuracy"},
            "discriminating_predictions": [
                {"prediction": "accuracy increases", "maps_to": "PROBE",
                 "competitor": "prompt length alone", "competitor_differs": True}],
        }
        return CandidateResult(status="theorized", events=[make_event(
            "TheoryCreated", theory, action_type=THEORIZE,
            frontier_target_id=action.frontier_target_id)], extras={"theory": theory})

    def probe(self, action, state, **kwargs):
        if self._probes >= len(self.probe_script):
            return CandidateResult(status="probe_execution_blocked", events=[make_event(
                "ActionBlocked", {"reason": "scripted_world_exhausted",
                                  "theory_id": action.target}, action_type=PROBE)],
                extras={"reason": "scripted_world_exhausted"})
        row = dict(self.probe_script[self._probes])
        self._probes += 1
        tid = str(action.extra.get("theory_id") or action.target or "")
        theory = next((t for t in state.get("theories", []) if t.get("id") == tid), {})
        evidence = {
            "evidence_id": f"E{self._probes}", "role": "ProbeEvidence", "epistemic": "WORLD",
            "attested": True, "promotion_ok": True, "promotion_gaps": [],
            "execution_status": "ran", "executor_status": "ran",
            "world_id": self.world_id, "world_digest": self.world_digest,
            "experiment_digest": f"x{self._probes}", "data_digest": f"dd{self._probes}",
            "protocol_digest": f"p{self._probes}",
            "theory_id": tid, "question_id": str(theory.get("question_id") or action.frontier_target_id),
            "claim": str(theory.get("claim") or ""), "claim_consistent": True,
            "identity_ok": True, "executable_ok": True, "reproduction_ok": True,
            "literature_checked": True, "treatment": 3.0, "control": 2.0,
            "measured_cost": {"tokens": 2000.0, "wall_seconds": 4.0},
            **row,
        }
        evidence.setdefault("separation", round(abs(
            float(evidence.get("treatment") or 0) - float(evidence.get("control") or 0)), 6))
        return CandidateResult(status="probe_positive", evidence=evidence,
                               evidence_id=evidence["evidence_id"], world_id=self.world_id,
                               extras={"executor_status": "ran"})

    def verify(self, action, state, **kwargs):
        target = next((r for r in state.get("evidence_records", [])
                       if r.get("evidence_id") == action.target), None)
        if target is None:
            return CandidateResult(status="blocked", events=[make_event(
                "ActionBlocked", {"reason": "no_target_evidence"}, action_type=VERIFY)],
                extras={"reason": "no_target_evidence"})
        replicated = {
            **target, "evidence_id": f"{target['evidence_id']}-rep",
            "replication_of": target["evidence_id"], "world_id": self.heldout_id,
            "world_digest": self.heldout_digest,
            "transfer_ok": True, "independent_replication": True, "verify_count": 1,
            "verify_kind": "VERIFY_REPLICATION", "reproduction_ok": True, "identity_ok": True,
            "measured_cost": {"tokens": 1500.0, "wall_seconds": 3.0},
        }
        return CandidateResult(status="replicated", evidence=replicated,
                               evidence_id=replicated["evidence_id"], world_id=self.heldout_id,
                               extras={"transfer_ok": True})


# ---------------------------------------------------------------------------


@dataclass
class TrajectoryResult:
    actions: list[str]
    ticks: int
    metrics: dict[str, Any]
    readiness: str
    replay_ok: bool
    root_question: str
    reviews: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": list(self.actions),
            "ticks": self.ticks,
            "metrics": dict(self.metrics),
            "readiness": self.readiness,
            "replay_ok": self.replay_ok,
            "root_question": self.root_question,
            "open_objections": [r["review_id"] for r in open_reviews(self.reviews)],
        }


def capability_metrics(env: OpenWorld, actions: list[str],
                       fatal_seen_at: dict[str, int]) -> dict[str, Any]:
    """The §26 metrics. Counts over a real trajectory, not proxies for quality."""
    state = env.state
    reviews = list(state.reviews)
    fatal = [r for r in reviews if r.get("severity") == "fatal"]
    major = [r for r in reviews if r.get("severity") == "major"]
    resolved_fatal = [r for r in fatal if r.get("status") == "resolved"]
    resolved_major = [r for r in major if r.get("status") == "resolved"]

    first_fatal = min(fatal_seen_at.values()) if fatal_seen_at else None
    first_redesign = next((index for index, name in enumerate(actions)
                           if name == REDESIGN), None)
    first_pivot = next((index for index, name in enumerate(actions)
                        if name == PROJECT_PIVOT), None)
    wasted = 0
    if first_fatal is not None:
        end = first_redesign if first_redesign is not None else len(actions)
        wasted = sum(1 for name in actions[first_fatal:end] if name in ROUTINE)

    world_rows = [r for r in state.evidence_records
                  if str(r.get("epistemic") or "") == "WORLD" and r.get("promotion_ok")]
    central = {str(t.get("id") or "") for t in state.theories
               if t.get("role") != "competing_explanation"}
    decision_relevant = [r for r in world_rows if str(r.get("theory_id") or "") in central]
    spent = dict((state.resources or {}).get("spent") or {})
    calls = float(spent.get("api_calls") or 0) or float(len(actions) or 1)

    return {
        "decision_relevant_evidence_yield": len(decision_relevant),
        "central_question_progress": int(state.metrics.get("central_question_progress") or 0),
        "quality_gap_reduction": int(state.metrics.get("quality_gap_reduction") or 0),
        "quality_gap_remaining": int((state.quality or {}).get("quality_gap_size") or 0),
        "major_objection_resolution_rate": round(
            len(resolved_major) / len(major), 4) if major else None,
        "fatal_objection_resolution_rate": round(
            len(resolved_fatal) / len(fatal), 4) if fatal else None,
        "caveat_only_repair_rate": round(
            float(state.metrics.get("caveat_only_repair_refused") or 0) / max(1, len(actions)), 4),
        "time_to_redesign": (first_redesign - first_fatal)
            if (first_fatal is not None and first_redesign is not None
                and first_redesign >= first_fatal) else None,
        "proactive_redesigns": sum(1 for index, name in enumerate(actions)
                                   if name == REDESIGN
                                   and (first_fatal is None or index < first_fatal)),
        "time_to_project_pivot": first_pivot,
        "wasted_actions_after_fatal_objection": wasted,
        "resource_efficiency": round(len(decision_relevant) / calls, 4),
        "goal_drift_rate": round(
            float((state.debt or {}).get("goal_drift_debt") or 0)
            / max(1, len(state.open_questions) + len(state.resolved_questions)), 4),
        "peripheral_activity": int(state.metrics.get("peripheral_question_progress") or 0),
        "low_value_activity": int(state.metrics.get("low_value_activity") or 0),
        "same_failure_repetition": int(state.metrics.get("same_failure_repetition") or 0),
        "successful_reorientation": int(state.metrics.get("successful_reorientation") or 0),
        "replication_completion_rate": round(
            sum(1 for r in world_rows if r.get("replication_of") and r.get("transfer_ok"))
            / max(1, len({str(r.get("theory_id") or "") for r in world_rows if r.get("theory_id")})),
            4),
        "branch_retirement_precision": len(state.retired_lineages),
        # Did exploration vary at all, and did the project's own objective move?
        "operators_tried": sorted({str(t.get("operator_reused") or "") for t in state.theories
                                   if t.get("role") != "competing_explanation"
                                   and t.get("operator_reused")}),
        "operator_diversity": len({str(t.get("operator_reused") or "") for t in state.theories
                                   if t.get("role") != "competing_explanation"
                                   and t.get("operator_reused")}),
        "objective_frontier": (state.objective or {}).get("frontier"),
        "breakthroughs": int((state.objective or {}).get("breakthrough_count") or 0),
        "attributed_hypotheses": int(
            exploration_credit(state)["attributed_hypotheses"]),
        "strategic_stagnation_recovery": int(state.metrics.get("successful_reorientation") or 0),
    }


def run_trajectory(
    workspace: Path,
    *,
    root_question: str,
    probe_script: list[dict[str, Any]],
    horizon: int = 30,
    contract: dict[str, Any] | None = None,
    fixed_operator: bool = False,
    policy: dict[str, Any] | None = None,
) -> TrajectoryResult:
    """Run the real controller against a scripted world for a long horizon."""
    from ..freeze import freeze_world
    from .benchmark import make_env, seed_question

    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    source = root / "source.csv"
    source.write_text("key,value\na,1\na,1\nb,2\nb,2\n", encoding="utf-8")
    primary = freeze_world(world_id="w0-primary", schema="numeric_table", slice_rule="first_rows:4",
                           catalog=root / "worlds", url="https://example.invalid/a.csv",
                           source_file=source)
    heldout_source = root / "heldout.csv"
    heldout_source.write_text("key,value\nc,3\nc,3\nd,4\nd,4\n", encoding="utf-8")
    heldout = freeze_world(world_id="w1-heldout", schema="numeric_table", slice_rule="first_rows:4",
                           catalog=root / "worlds", url="https://example.invalid/b.csv",
                           source_file=heldout_source)
    env = make_env(root, contract={"root_question": root_question, **(contract or {})},
                   worlds=[(primary, "world"), (heldout, "heldout")])
    seed_question(env, "Q1", root_question)
    env.connect_workers(ScriptedWorld(probe_script=list(probe_script),
                                      fixed_operator=fixed_operator, policy=policy,
                                      world_id=primary.id, world_digest=primary.digest,
                                      heldout_id=heldout.id, heldout_digest=heldout.digest))

    actions: list[str] = []
    fatal_seen_at: dict[str, int] = {}
    for _ in range(horizon):
        event = env.tick()
        scheduled = event.get("scheduled")
        if scheduled is None:
            break
        actions.append(scheduled["action"]["action_type"])
        for review in env.state.reviews:
            if review.get("severity") == "fatal" and review["review_id"] not in fatal_seen_at:
                fatal_seen_at[review["review_id"]] = len(actions) - 1
    return TrajectoryResult(
        actions=actions,
        ticks=int(env.state.ticks),
        metrics=capability_metrics(env, actions, fatal_seen_at),
        readiness=readiness(env.state).status,
        replay_ok=state_digest(env.state) == state_digest(rebuild_state(env.log)),
        root_question=str((env.state.contract or {}).get("root_question") or ""),
        reviews=list(env.state.reviews),
    )


# ---------------------------------------------------------------------------
# Named long-horizon situations
# ---------------------------------------------------------------------------

ROOT = "Does retrieval augmentation improve factual accuracy of small language models?"

# The first result looks good and is underpowered; the second is properly
# powered but its measure is blind; only the third is a design worth believing.
HARD_SCRIPT = [
    {"outcome": "supports", "verdict": "supports", "sample_size": 6},
    {"outcome": "supports", "verdict": "supports", "sample_size": 800, "dv_blind": True,
     "cannot_corroborate": True, "validation_gaps": ["oracle_sanity_failed"]},
    {"outcome": "supports", "verdict": "supports", "sample_size": 800,
     "mechanism_validated": True, "world_consumed": True},
    {"outcome": "supports", "verdict": "supports", "sample_size": 800,
     "mechanism_validated": True, "world_consumed": True},
]

# Nothing this direction produces can be believed.
DEAD_SCRIPT = [
    {"outcome": "weakens", "verdict": "weakens", "sample_size": 800,
     "cannot_corroborate": True, "validation_gaps": ["object_absent"], "object_absent": True}
] * 5


TRAJECTORIES = {
    "recoverable_project": {
        "root_question": ROOT,
        "probe_script": HARD_SCRIPT,
        "contract": {"target_quality": "workshop",
                     "resource_limits": {"api_calls": 40, "min_sample_size": 100}},
    },
    "dead_project": {
        "root_question": ROOT,
        "probe_script": DEAD_SCRIPT,
        "contract": {"target_quality": "workshop",
                     "resource_limits": {"api_calls": 40, "min_sample_size": 100}},
    },
}


def run_all(workspace: Path, *, horizon: int = 30) -> dict[str, Any]:
    rows = {}
    for name, spec in TRAJECTORIES.items():
        result = run_trajectory(Path(workspace) / name, horizon=horizon, **spec)
        rows[name] = result.to_dict()
    return {
        "kind": "long_horizon_trajectory_evaluation",
        "horizon": horizon,
        "trajectories": rows,
        "scope": (
            "scripted deterministic world; measures how the controller allocates "
            "actions, not whether the resulting science is any good."
        ),
    }
