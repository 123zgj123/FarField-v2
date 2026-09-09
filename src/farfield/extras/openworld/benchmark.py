"""Capability-level behavioural evaluation for the research controller.

Unit tests answer "does this function do what it says". They cannot answer the
question this system actually needs answered:

    given a research situation, does the controller decide well?

Each scenario below installs a *situation* into canonical ScientificState —
seeded through the reducer, so it is a state the runtime could really reach —
and then asks what the controller does next. The assertions are about decisions:
which action is scheduled, whether stagnation is recognised, whether a repair is
refused, whether the project is called finished.

Scope, stated honestly: these are deterministic offline scenarios with no model
and no live world. They test the control plane's judgment, not the quality of
generated hypotheses, and passing them is not evidence that FarField does good
science. It is evidence that it does not do several specific stupid things.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import OpenWorld
from .actions import PROBE, PROJECT_PIVOT, REDESIGN, REVIEW, VERIFY, FORK_LINEAGE
from .contract import ResearchContract
from .events import make_event
from .progress import maybe_strategic_stagnation
from .reducer import apply_events, rebuild_state, state_digest
from .state import ScientificState
from .termination import readiness


ROOT_QUESTION = "Does retrieval augmentation improve factual accuracy of small language models?"


# ---------------------------------------------------------------------------
# Scenario construction helpers
# ---------------------------------------------------------------------------


def make_env(workspace: Path, *, contract: dict[str, Any] | None = None,
             worlds: list[Any] | None = None) -> OpenWorld:
    env = OpenWorld(workspace=workspace)
    payload = {
        "root_question": ROOT_QUESTION,
        "success_target": "a measured accuracy comparison with and without retrieval",
        "target_quality": "conference",
        "required_outputs": [],
        "resource_limits": {"api_calls": 100, "min_sample_size": 100},
        "hard_constraints": ["only attested worlds"],
        **(contract or {}),
    }
    env._ensure_baseline()
    env.state = apply_events(env.state, [
        make_event("GoalSet", {"goal": payload["root_question"]}),
        make_event("ContractSet", payload),
    ], log=env.log)
    if worlds:
        # Real frozen fixtures, so the trusted kernel's attestation path runs.
        env.state = apply_events(env.state, [
            make_event("WorldCreated", {
                "id": fixture.id, "world_id": fixture.id, "digest": fixture.digest,
                "observables": fixture.schema, "research_role": role, "role": role,
                "path": str(fixture.root)})
            for fixture, role in worlds], log=env.log)
        primary = worlds[0][0]
        env.state = apply_events(env.state, [make_event("WorldCreated", {
            "id": primary.id, "world_id": primary.id, "digest": primary.digest,
            "observables": primary.schema, "research_role": "world", "role": "world",
            "path": str(primary.root)})], log=env.log)
    else:
        env.state = apply_events(env.state, [make_event(
            "WorldCreated", {"id": "W0", "world_id": "W0", "digest": "d0",
                             "observables": "accuracy"})], log=env.log)
    return env


def _emit(env: OpenWorld, events: list[Any]) -> None:
    env.state = apply_events(env.state, events, log=env.log)


def seed_question(env: OpenWorld, qid: str, text: str, **extra: Any) -> None:
    _emit(env, [make_event("QuestionCreated", {
        "id": qid, "text": text, "lineage_id": f"line-{qid}", "epistemic": "GENERATED",
        **extra})])


def seed_survey(env: OpenWorld, qid: str = "", theory_id: str = "") -> None:
    _emit(env, [make_event("ArtifactAdded", {
        "id": f"survey-{qid or 'root'}-{theory_id or 'x'}", "kind": "literature_survey",
        "question_id": qid, "theory_id": theory_id,
        "works": [{"arxiv_id": "2401.00001", "title": "prior", "abstract": "a"}],
        "citations": ["2401.00001"]})])


def seed_theory(env: OpenWorld, tid: str, qid: str, **extra: Any) -> None:
    _emit(env, [make_event("TheoryCreated", {
        "id": tid, "question_id": qid, "text": f"mechanism for {qid}",
        "claim": f"claim of {tid}", "epistemic": "GENERATED",
        "lineage_id": f"line-{qid}", "assumptions": ["retrieval quality is constant"],
        **extra})])


def seed_probe_evidence(env: OpenWorld, eid: str, tid: str, qid: str, **extra: Any) -> None:
    """A ProbeEvidence row as the kernel would have admitted it.

    Seeding through the reducer keeps this a state the runtime could reach; it
    does not claim the trusted kernel was exercised.
    """
    row = {
        "evidence_id": eid, "role": "ProbeEvidence", "epistemic": "WORLD",
        "attested": True, "promotion_ok": True, "promotion_gaps": [],
        "execution_status": "ran", "executor_status": "ran",
        "world_id": "W0", "world_digest": "d0", "experiment_digest": f"x-{eid}",
        "data_digest": f"dd-{eid}", "protocol_digest": f"p-{eid}",
        "theory_id": tid, "question_id": qid, "outcome": "supports", "verdict": "supports",
        "claim_consistent": True, "identity_ok": True, "executable_ok": True,
        "reproduction_ok": True, "literature_checked": True,
        "treatment": 3.0, "control": 2.0,
        "measured_cost": {"tokens": 1000.0, "wall_seconds": 3.0},
        **extra,
    }
    _emit(env, [make_event("EvidenceAdded", row, action_type=PROBE, frontier_target_id=qid)])


def seed_review(env: OpenWorld, **row: Any) -> None:
    _emit(env, [make_event("ReviewRecorded", row, action_type=REVIEW)])


def seed_spend(env: OpenWorld, calls: int, *, action_type: str = "PROBE") -> None:
    _emit(env, [make_event("ArtifactAdded", {
        "kind": "action_attempt", "action_type": action_type, "status": "ok",
        "input_key": f"spend-{index}-{action_type}",
        "measured_cost": {"tokens": 1000.0, "wall_seconds": 1.0}})
        for index in range(calls)])


def seed_tick(env: OpenWorld, before: Any, *, action_type: str = "SURVEY") -> None:
    """Advance a tick through the real progress measurement, not a hand-written
    payload — otherwise the scenario would be grading its own answer."""
    from .progress import measure_progress

    progress = measure_progress(before, env.state)
    _emit(env, [make_event("TickAdvanced", {
        "meaningful": progress.meaningful,
        "research_meaningful": progress.research_meaningful,
        **{name: getattr(progress, name) for name in (
            "central_question_progress", "decision_relevant_evidence",
            "quality_gap_reduction", "critical_review_resolution",
            "peripheral_question_progress", "caveat_only_repair",
            "same_failure_repetition", "low_value_activity",
            "successful_reorientation", "replication_progress")},
        "action_type": action_type}, action_type=action_type)])


# ---------------------------------------------------------------------------
# Scenario protocol
# ---------------------------------------------------------------------------


@dataclass
class Observation:
    """Everything the checks are allowed to look at."""

    env: OpenWorld
    eligible: tuple[str, ...]
    ranked: tuple[tuple[str, float], ...]
    chosen: str
    readiness: dict[str, Any]
    strategic_stagnation: dict[str, Any] | None
    quality: dict[str, Any]
    resources: dict[str, Any]
    debt: dict[str, Any]
    replay_ok: bool

    def rank_of(self, action_type: str) -> int:
        for index, (name, _) in enumerate(self.ranked):
            if name == action_type:
                return index
        return len(self.ranked)


@dataclass
class Scenario:
    name: str
    title: str
    build: Callable[[Path], OpenWorld]
    check: Callable[[Observation], list[str]]
    capability: str = ""


def observe(env: OpenWorld) -> Observation:
    from .scheduler import schedule_all

    actions = env.eligible()
    ranked = schedule_all(env.state, actions)
    chosen = ranked[0].action.action_type if ranked else ""
    strategic = maybe_strategic_stagnation(env.state)
    return Observation(
        env=env,
        eligible=tuple(dict.fromkeys(item.action_type for item in actions)),
        ranked=tuple((row.action.action_type, round(row.total, 6)) for row in ranked),
        chosen=chosen,
        readiness=readiness(env.state).to_dict(),
        strategic_stagnation=None if strategic is None else strategic.to_dict(),
        quality=dict(env.state.quality),
        resources=dict(env.state.resources),
        debt=dict(env.state.debt),
        replay_ok=state_digest(env.state) == state_digest(rebuild_state(env.log)),
    )


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def _grounded_project(workspace: Path, **contract: Any) -> OpenWorld:
    env = make_env(workspace, contract=contract or None)
    seed_question(env, "Q1", ROOT_QUESTION)
    seed_survey(env, "Q1")
    seed_theory(env, "T1", "Q1")
    seed_survey(env, "Q1", theory_id="T1")
    return env


def build_a(workspace: Path) -> OpenWorld:
    """A positive result from six samples against a contract minimum of 100."""
    env = _grounded_project(workspace)
    seed_probe_evidence(env, "E1", "T1", "Q1", sample_size=6)
    return env


def check_a(obs: Observation) -> list[str]:
    bad: list[str] = []
    if obs.readiness["status"] == "RESEARCH_READY":
        bad.append("called an n=6 result ready")
    adequacy = obs.quality["dimensions"]["experimental_adequacy"]
    if adequacy["status"] in {"adequate", "partial"}:
        bad.append(f"rated experimental_adequacy={adequacy['status']} at n=6")
    if REVIEW not in obs.eligible:
        bad.append("no REVIEW available for an unexamined positive result")
    obs.env.execute(next(a for a in obs.env.eligible() if a.action_type == REVIEW))
    power = [r for r in obs.env.state.reviews
             if r.get("dimension") == "experimental_adequacy" and r.get("status") == "open"]
    if not power:
        bad.append("review did not raise the sample-size objection")
    elif not power[0].get("requires_new_evidence"):
        bad.append("sample-size objection was marked answerable without new evidence")
    after = observe(obs.env)
    if REDESIGN not in after.eligible:
        bad.append("no REDESIGN offered after an underpowered result")
    if after.chosen not in {REDESIGN, PROBE, VERIFY, REVIEW}:
        bad.append(f"chose {after.chosen} instead of strengthening the evidence")
    return bad


def build_b(workspace: Path) -> OpenWorld:
    """A reviewer says the evaluation cannot answer the central question."""
    env = _grounded_project(workspace)
    seed_probe_evidence(env, "E1", "T1", "Q1", sample_size=500, mechanism_validated=True)
    seed_review(
        env, review_id="RF1", severity="fatal", dimension="experimental_adequacy",
        objection="the evaluation as designed cannot answer the central question",
        affected_design="E1", repair_type="experiment_redesign",
        requires_new_evidence=True, theory_id="T1", question_id="Q1")
    return env


def check_b(obs: Observation) -> list[str]:
    bad: list[str] = []
    if obs.readiness["status"] == "RESEARCH_READY":
        bad.append("ready with an open fatal objection")
    # Prose must not close it.
    obs.env.state = apply_events(obs.env.state, [make_event("ReviewResolved", {
        "review_id": "RF1", "resolution_kind": "added_caveat"})], log=obs.env.log)
    record = next(r for r in obs.env.state.reviews if r["review_id"] == "RF1")
    if record["status"] == "resolved":
        bad.append("a caveat closed a fatal evidence-requiring objection")
    if not int(obs.env.state.metrics.get("caveat_only_repair_refused") or 0):
        bad.append("caveat-only repair was not counted")
    after = observe(obs.env)
    if REDESIGN not in after.eligible:
        bad.append("no REDESIGN offered for a fatal design objection")
    if after.chosen != REDESIGN:
        bad.append(f"chose {after.chosen} rather than redesigning")
    return bad


def build_c(workspace: Path) -> OpenWorld:
    """Ten peripheral wins in a row. Every tick succeeds; nothing advances."""
    env = _grounded_project(workspace)
    for index in range(8):
        before = ScientificState.from_dict(env.state.to_dict())
        qid = f"P{index}"
        seed_question(env, qid, f"how should we format cache key {index} for the tokenizer?")
        _emit(env, [make_event("ArtifactAdded", {
            "kind": "note", "id": f"n{index}", "text": "peripheral finding"})])
        _emit(env, [make_event("QuestionResolved", {"id": qid})])
        seed_tick(env, before, action_type="OBSERVE")
    return env


def check_c(obs: Observation) -> list[str]:
    bad: list[str] = []
    if obs.strategic_stagnation is None:
        bad.append("no strategic stagnation after eight busy but peripheral ticks")
    if obs.env.state.ticks - obs.env.state.last_progress_tick >= 4:
        bad.append("scenario did not actually keep the runtime operationally busy")
    if obs.readiness["status"] == "RESEARCH_READY":
        bad.append("peripheral resolutions were read as a finished project")
    if int(obs.env.state.metrics.get("peripheral_question_progress") or 0) < 1:
        bad.append("peripheral progress was not distinguished from central progress")
    return bad


def build_d(workspace: Path) -> OpenWorld:
    """A dead direction with most of the budget still unspent."""
    env = _grounded_project(workspace)
    seed_probe_evidence(env, "E1", "T1", "Q1", sample_size=500, outcome="weakens",
                        verdict="weakens", cannot_corroborate=True,
                        validation_gaps=["oracle_sanity_execution_failed"])
    seed_review(env, review_id="RF1", severity="fatal", dimension="technical_correctness",
                objection="the design cannot establish the claim on any available world",
                repair_type="experiment_redesign", requires_new_evidence=True,
                theory_id="T1", question_id="Q1")
    for index in (1, 2):
        _emit(env, [make_event("DesignRevised", {
            "revision_id": f"rev-0-technical_correctness-{index}",
            "dimension": "technical_correctness", "selected_repair": "experiment_redesign",
            "addresses_reviews": [], "outcome": "open"}, action_type=REDESIGN)])
    seed_spend(env, 10)
    return env


def check_d(obs: Observation) -> list[str]:
    bad: list[str] = []
    if obs.resources.get("budget_pressure", 1.0) > 0.5:
        bad.append("scenario did not leave real budget headroom")
    if PROJECT_PIVOT not in obs.eligible:
        bad.append("no PROJECT_PIVOT offered on a dead direction with budget left")
    if obs.chosen != PROJECT_PIVOT:
        bad.append(f"chose {obs.chosen} instead of changing direction")
    return bad


def build_e(workspace: Path) -> OpenWorld:
    """The same dead direction with the budget nearly gone."""
    env = build_d(workspace)
    seed_spend(env, 85)
    return env


def check_e(obs: Observation) -> list[str]:
    bad: list[str] = []
    if obs.resources.get("budget_pressure", 0.0) < 0.75:
        bad.append("scenario did not actually exhaust the budget")
    if PROJECT_PIVOT in obs.eligible:
        bad.append("opened a new research direction with the budget nearly gone")
    if FORK_LINEAGE in obs.eligible:
        bad.append("offered to fork lineages with the budget nearly gone")
    if obs.readiness["status"] == "RESEARCH_READY":
        bad.append("called an unfinished project ready because the money ran out")
    if obs.chosen and obs.chosen not in {REDESIGN, PROBE, VERIFY, REVIEW, "SYNTHESIZE",
                                         "ARCHIVE", "REFLECT", "SURVEY", "THEORIZE"}:
        bad.append(f"chose {obs.chosen} under budget pressure")
    return bad


def build_f(workspace: Path) -> OpenWorld:
    """The project quietly became a measurement paper about something else."""
    env = make_env(workspace)
    seed_question(env, "Q1", ROOT_QUESTION)
    seed_survey(env, "Q1")
    _emit(env, [make_event("QuestionResolved", {"id": "Q1"})])
    seed_question(env, "Q2", "how should token overlap between candidate spans be scored?")
    seed_theory(env, "T2", "Q2")
    seed_survey(env, "Q2", theory_id="T2")
    seed_probe_evidence(env, "E2", "T2", "Q2", sample_size=500)
    return env


def check_f(obs: Observation) -> list[str]:
    bad: list[str] = []
    if int(obs.debt.get("goal_drift_debt") or 0) < 1:
        bad.append("semantic drift to a measurement sub-problem was not detected")
    central = obs.quality["dimensions"]["central_claim_support"]
    if central["status"] == "adequate":
        bad.append("a drifted claim counted as central-question support")
    if obs.readiness["status"] == "RESEARCH_READY":
        bad.append("ready while researching a different question")
    if "no_unauthorized_goal_drift" not in obs.readiness["failed_gates"]:
        bad.append("readiness did not name goal drift as the blocker")
    obs.env.execute(next(a for a in obs.env.eligible() if a.action_type == REVIEW))
    if not any(r.get("dimension") == "central_claim_support" for r in obs.env.state.reviews):
        bad.append("review did not object to the drift")
    return bad


def build_g(workspace: Path) -> OpenWorld:
    """Ten reviewers agree with H1 and nobody measured anything."""
    env = _grounded_project(workspace)
    for index in range(10):
        seed_review(env, review_id=f"RS{index}", severity="minor", dimension="importance",
                    objection="I find this hypothesis convincing", repair_type="writing_only",
                    theory_id="T1", question_id="Q1")
        _emit(env, [make_event("ArtifactAdded", {
            "kind": "reviewer_opinion", "id": f"op{index}", "theory_id": "T1",
            "agrees": True, "sibling_agreement": True})])
    return env


def check_g(obs: Observation) -> list[str]:
    bad: list[str] = []
    belief = obs.env.state.belief_states.get("T1") or {}
    if float(belief.get("posterior_confidence") or 0.5) != 0.5:
        bad.append("reviewer agreement moved the posterior")
    if belief.get("supporting_evidence"):
        bad.append("reviewer agreement was recorded as supporting evidence")
    if obs.env.state.verified_research_state:
        bad.append("agreement produced verified knowledge")
    if obs.quality["dimensions"]["central_claim_support"]["status"] in {"adequate", "partial"}:
        bad.append("agreement raised central_claim_support")
    if obs.readiness["status"] == "RESEARCH_READY":
        bad.append("ten agreeing reviewers finished the project")
    return bad


def build_h(workspace: Path) -> OpenWorld:
    """A project that has just decided to restart."""
    return build_d(workspace)


def check_h(obs: Observation) -> list[str]:
    bad: list[str] = []
    env = obs.env
    before_evidence = {r["evidence_id"] for r in env.state.evidence_records
                       if r.get("epistemic") == "WORLD"}
    before_root = dict(env.state.contract).get("root_question")
    pivot = next((a for a in env.eligible() if a.action_type == PROJECT_PIVOT), None)
    if pivot is None:
        return ["PROJECT_PIVOT was not available to restart from"]
    env.execute(pivot)
    after_evidence = {r["evidence_id"] for r in env.state.evidence_records
                      if r.get("epistemic") == "WORLD"}
    if not before_evidence <= after_evidence:
        bad.append("the restart lost admitted WORLD evidence")
    if dict(env.state.contract).get("root_question") != before_root:
        bad.append("the restart changed the root question")
    if env.state.project_epoch != 1:
        bad.append("the restart did not open a new project epoch")
    if any(t.get("status") != "retired" for t in env.state.theories):
        bad.append("speculative hypotheses survived the restart")
    if not env.state.retired_lineages:
        bad.append("no lineage was recorded as retired")
    projection = next((a for a in env.state.artifacts
                       if a.get("kind") == "clean_restart_projection"), None)
    if projection is None:
        bad.append("no clean restart projection was produced")
    else:
        blob = json.dumps(projection)
        if "speculative_hypothesis_chains" not in blob:
            bad.append("the restart projection did not drop speculative chains")
        if not projection.get("failure_lessons"):
            bad.append("the restart discarded the failure lessons")
        if projection.get("root_question") != before_root:
            bad.append("the restart projection lost the root question")
    if not env.state.open_questions:
        bad.append("the restart left the frontier empty")
    if state_digest(env.state) != state_digest(rebuild_state(env.log)):
        bad.append("the restart broke event replay")
    return bad


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("A", "underpowered positive result", build_a, check_a, "research_judgment"),
    Scenario("B", "fatal reviewer objection", build_b, check_b, "research_adaptation"),
    Scenario("C", "peripheral progress trap", build_c, check_c, "goal_maintenance"),
    Scenario("D", "dead end with budget left", build_d, check_d, "project_backtracking"),
    Scenario("E", "dead end with no budget", build_e, check_e, "resource_awareness"),
    Scenario("F", "goal drift", build_f, check_f, "goal_maintenance"),
    Scenario("G", "consensus is not evidence", build_g, check_g, "evidence_grounding"),
    Scenario("H", "clean project restart", build_h, check_h, "project_backtracking"),
)


def run_scenario(scenario: Scenario, workspace: Path) -> dict[str, Any]:
    root = Path(workspace) / f"scenario-{scenario.name}"
    root.mkdir(parents=True, exist_ok=True)
    env = scenario.build(root)
    observation = observe(env)
    failures = list(scenario.check(observation))
    if not observation.replay_ok:
        failures.append("state does not replay from its own event log")
    return {
        "scenario": scenario.name,
        "title": scenario.title,
        "capability": scenario.capability,
        "passed": not failures,
        "failures": failures,
        "chosen": observation.chosen,
        "eligible": list(observation.eligible),
        "ranked": [list(row) for row in observation.ranked[:5]],
        "readiness": observation.readiness["status"],
        "failed_gates": observation.readiness["failed_gates"],
        "quality_gap": list(observation.quality.get("quality_gap") or []),
        "budget_pressure": observation.resources.get("budget_pressure"),
        "strategic_stagnation": bool(observation.strategic_stagnation),
    }


def run_all(workspace: Path) -> dict[str, Any]:
    rows = [run_scenario(scenario, Path(workspace)) for scenario in SCENARIOS]
    passed = [row for row in rows if row["passed"]]
    by_capability: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = by_capability.setdefault(row["capability"], {"passed": 0, "total": 0})
        bucket["total"] += 1
        bucket["passed"] += int(row["passed"])
    return {
        "kind": "behavioural_research_evaluation",
        "scenarios": rows,
        "passed": len(passed),
        "total": len(rows),
        "by_capability": by_capability,
        "scope": (
            "deterministic offline decision scenarios; no live model, no live world. "
            "Passing is not evidence of good science, only of specific avoided failures."
        ),
    }
