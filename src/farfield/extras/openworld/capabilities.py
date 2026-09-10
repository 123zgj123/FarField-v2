"""The capability register: every claim this runtime makes, and its live path.

The recurring failure in this codebase has not been broken code. It has been
*claims that outlived their implementation* — a contradiction tracker whose only
writer was an event nobody emitted, a budget filter reading two keys nothing
wrote, a quality bar demanding a sample size no worker reported, a module still
describing itself as "the single long-term memory of the production path" long
after it left that path. Each was a capability the documentation listed and the
runtime could not perform, and each was found by a person reading code or by a
live run, not by a test.

This register makes that class of failure machine-checkable. A capability is not
a description; it is a claim with three obligations:

``implemented_by``  the module that performs it
``enforced_by``     the test that fails when it stops working
``live_path``       a predicate over a real state that must hold, so a claim
                    whose mechanism can never fire is a failing claim rather
                    than a paragraph

The shape is borrowed from the contract packages in production research systems
(`agent_ml_shared/contracts` in apexin-ai/agent-ml-research), where every
contract carries `authority`, `status` and a `scope` naming its own enforcing
test. The difference here is that `live_path` is executable: a capability must
demonstrate itself against a constructed state, not merely point at a file.

Adding a capability entry is a promise. If the promise cannot be kept, the entry
is `status="absent"` with a stated reason, which is an honest register rather
than an aspirational one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


IMPLEMENTED = "implemented"
PARTIAL = "partial"
ABSENT = "absent"
STATUSES = (IMPLEMENTED, PARTIAL, ABSENT)


@dataclass(frozen=True)
class Capability:
    """One claim, with the module that keeps it and the test that guards it."""

    name: str
    claim: str
    implemented_by: tuple[str, ...]
    enforced_by: tuple[str, ...]
    status: str = IMPLEMENTED
    live_path: Callable[[], bool] | None = None
    limits: str = ""
    validated: str = "offline"          # offline | live
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "claim": self.claim,
            "implemented_by": list(self.implemented_by),
            "enforced_by": list(self.enforced_by),
            "status": self.status, "limits": self.limits,
            "validated": self.validated, "note": self.note,
            "has_live_path_check": self.live_path is not None,
        }


# ---------------------------------------------------------------------------
# Live-path probes. Each builds a minimal real state and asks whether the
# mechanism actually fires. These are the checks that would have caught the
# defects listed above at the moment they were introduced.
# ---------------------------------------------------------------------------


def _state(**contract: Any):
    from .events import make_event
    from .reducer import apply_events
    from .state import ScientificState

    root = contract.pop("root_question", "does X improve Y in Z?")
    base = ScientificState(goal=root)
    return apply_events(base, [make_event("ContractSet", {"root_question": root, **contract})])


def _probe_row(eid: str, **extra: Any) -> dict[str, Any]:
    return {
        "evidence_id": eid, "role": "ProbeEvidence", "epistemic": "WORLD",
        "attested": True, "promotion_ok": True, "execution_status": "ran",
        "world_id": "W0", "world_digest": "d0", "experiment_digest": f"x-{eid}",
        "theory_id": "T1", "question_id": "Q1", "outcome": "supports",
        "claim_consistent": True, "identity_ok": True, "reproduction_ok": True,
        "literature_checked": True, "sample_size": 500, **extra,
    }


def _contradiction_fires() -> bool:
    """Two admitted results disagreeing about one hypothesis become a contradiction."""
    from .events import make_event
    from .reducer import apply_events

    state = apply_events(_state(), [
        make_event("TheoryCreated", {"id": "T1", "question_id": "Q1", "text": "m"}),
        make_event("EvidenceAdded", _probe_row("E1")),
        make_event("EvidenceAdded", _probe_row("E2", outcome="weakens", world_id="W1",
                                               world_digest="d1")),
    ])
    return bool(state.contradictions) and int(state.debt.get("contradiction_debt") or 0) > 0


def _budget_filter_refuses() -> bool:
    """The budget filter can actually refuse an action."""
    from .actions import SPECS, ActionInstance
    from .events import make_event
    from .reducer import apply_events
    from .scheduler import budget_ok

    state = _state(resource_limits={"api_calls": 1})
    state = apply_events(state, [make_event("ArtifactAdded", {
        "kind": "action_attempt", "action_type": "PROBE", "input_key": f"k{i}",
        "measured_cost": {"tokens": 1.0, "wall_seconds": 1.0}}) for i in range(3)])
    return not budget_ok(ActionInstance(SPECS["PROBE"]), state)


def _sole_support_debt_fires() -> bool:
    """A claim standing on one measurement raises verification debt."""
    from .actions import VERIFY_HIGH_IMPACT_CLAIM, _verify_kind
    from .events import make_event
    from .reducer import apply_events

    state = apply_events(_state(), [
        make_event("TheoryCreated", {"id": "T1", "question_id": "Q1", "text": "m"}),
        make_event("EvidenceAdded", _probe_row("E1", verify_count=1)),
    ])
    return _verify_kind(state) == VERIFY_HIGH_IMPACT_CLAIM


def _sample_size_reachable() -> bool:
    """An experiment can report power, so the adequacy bar can be met."""
    from .events import make_event
    from .quality import compute_quality
    from .reducer import apply_events

    state = apply_events(_state(target_quality="workshop"), [
        make_event("QuestionCreated", {"id": "Q1", "text": "does X improve Y in Z?"}),
        make_event("ArtifactAdded", {"id": "s", "kind": "literature_survey", "question_id": "Q1",
                                     "theory_id": "T1", "works": [{"arxiv_id": "1"}]}),
        make_event("TheoryCreated", {"id": "T1", "question_id": "Q1", "text": "m"}),
        make_event("EvidenceAdded", _probe_row(
            "E1", sample_size_basis="reported_by_the_registered_experiment")),
    ])
    return compute_quality(state)["dimensions"]["experimental_adequacy"]["status"] == "adequate"


def _caveat_repair_refused() -> bool:
    """An objection needing a world cannot be closed by prose."""
    from .events import make_event
    from .reducer import apply_events

    state = apply_events(_state(), [make_event("ReviewRecorded", {
        "review_id": "R1", "severity": "fatal", "dimension": "measurement_validity",
        "objection": "the measure is blind", "repair_type": "measurement_redesign"})])
    state = apply_events(state, [make_event(
        "ReviewResolved", {"review_id": "R1", "resolution_kind": "added_caveat"})])
    return (state.reviews[0]["status"] == "open"
            and int(state.metrics.get("caveat_only_repair_refused") or 0) == 1)


def _goal_drift_detected() -> bool:
    """A question that left the root question is recorded as drift."""
    from .events import make_event
    from .reducer import apply_events

    state = apply_events(_state(root_question="does retrieval improve factual accuracy?"),
                         [make_event("QuestionCreated",
                                     {"id": "Q9", "text": "how should token overlap be scored?"})])
    return int(state.debt.get("goal_drift_debt") or 0) > 0


def _readiness_can_refuse_and_grant() -> bool:
    """Readiness is a real conjunction: it refuses an empty project."""
    from .termination import RESEARCH_READY, readiness

    return readiness(_state()).status != RESEARCH_READY


def _consensus_is_not_evidence() -> bool:
    """Agreeing reviewers move no belief and no verified state."""
    from .events import make_event
    from .reducer import apply_events

    state = apply_events(_state(), [
        make_event("TheoryCreated", {"id": "T1", "question_id": "Q1", "text": "m"}),
        *[make_event("ReviewRecorded", {
            "review_id": f"R{i}", "severity": "minor", "dimension": "importance",
            "objection": "convincing", "repair_type": "writing_only", "theory_id": "T1"})
          for i in range(10)],
    ])
    belief = state.belief_states.get("T1") or {}
    return (float(belief.get("posterior_confidence") or 0.5) == 0.5
            and not state.verified_research_state)


def _generated_never_becomes_world() -> bool:
    """A GENERATED row cannot enter the state labelled WORLD."""
    from .events import make_event
    from .reducer import apply_events

    state = apply_events(_state(), [make_event("EvidenceAdded", {
        "evidence_id": "E-gen", "epistemic": "WORLD", "attested": True,
        "probe_kind": "GENERATED", "role": "ProbeEvidence"})])
    return state.evidence_records[0]["epistemic"] == "GENERATED"


def _replay_is_deterministic() -> bool:
    """State rebuilds from its own event log."""
    from .events import EventLog, make_event
    from .reducer import apply_events, rebuild_state, state_digest
    from .state import ScientificState

    log = EventLog(baseline=ScientificState().to_dict())
    state = apply_events(ScientificState(), [
        make_event("GoalSet", {"goal": "g"}),
        make_event("ContractSet", {"root_question": "g"}),
        make_event("QuestionCreated", {"id": "Q1", "text": "g"}),
    ], log=log)
    return state_digest(state) == state_digest(rebuild_state(log))


def _acquisition_needs_authorisation() -> bool:
    """Choosing the object of study is a contract decision, not a run's."""
    from .contract import ResearchContract

    return ResearchContract().world_selection == "declared_only"


def _inert_action_refused() -> bool:
    """An action that twice returned the same nothing is not offered again."""
    from .actions import SPECS, ActionInstance, information_precondition, _action_variant
    from .events import make_event
    from .reducer import apply_events

    action = ActionInstance(SPECS["OBSERVE"], target="Q1", frontier_target_id="Q1")
    state = apply_events(_state(), [make_event("ArtifactAdded", {
        "kind": "action_attempt", "action_type": "OBSERVE", "target": "Q1",
        "outcome_key": "NO_DATA", "events_admitted": 0, "project_epoch": 0,
        "variant": _action_variant(action), "input_key": f"k{i}"}) for i in range(2)])
    return "already_established" in information_precondition(state, action)


def _pivot_preserves_evidence() -> bool:
    """A retired direction keeps its WORLD evidence, its contract and its lessons."""
    from . import OpenWorld
    from .actions import SPECS, ActionInstance
    from .events import make_event
    from .reducer import apply_events

    env = OpenWorld(workspace=None)
    env.state = apply_events(_state(), [
        make_event("QuestionCreated", {"id": "Q1", "text": "does X improve Y in Z?"}),
        make_event("TheoryCreated", {"id": "T1", "question_id": "Q1", "text": "m",
                                     "lineage_id": "line-Q1"}),
        make_event("EvidenceAdded", _probe_row("E1")),
        make_event("ActionFailed", {"theory_id": "T1", "reason": "the measure never moved"}),
    ])
    env._ensure_baseline()
    root = dict(env.state.contract).get("root_question")
    env.execute(ActionInstance(SPECS["PROJECT_PIVOT"], target="Q1",
                               frontier_target_id="Q1", reason="probe",
                               extra={"trigger": {"reason": "probe"}}))
    restart = next((row for row in env.state.artifacts
                    if row.get("kind") == "clean_restart_projection"), {})
    return bool(
        any(row.get("evidence_id") == "E1" and row.get("epistemic") == "WORLD"
            for row in env.state.evidence_records)
        and dict(env.state.contract).get("root_question") == root
        and env.state.project_epoch == 1
        and all(row.get("status") == "retired" for row in env.state.theories)
        and restart.get("failure_lessons")
        and env.state.open_questions
    )


def _strategic_stagnation_fires() -> bool:
    """A busy project that is going nowhere is recognised as stagnant."""
    from .events import make_event
    from .progress import maybe_strategic_stagnation
    from .reducer import apply_events

    state = _state()
    for index in range(9):
        state = apply_events(state, [make_event("TickAdvanced", {
            "meaningful": True, "research_meaningful": False, "action_type": "OBSERVE"})])
    return maybe_strategic_stagnation(state) is not None


REGISTER: tuple[Capability, ...] = (
    Capability(
        "evidence_admission",
        "A GENERATED or unattested result never enters canonical state labelled WORLD.",
        ("openworld/kernel.py", "openworld/reducer.py"),
        ("tests/test_research_integrity.py",),
        live_path=_generated_never_becomes_world, validated="live",
    ),
    Capability(
        "event_replay",
        "Canonical state rebuilds exactly from its own append-only event log.",
        ("openworld/events.py", "openworld/reducer.py"),
        ("tests/test_research_control.py", "tests/behavioral/test_long_horizon.py"),
        live_path=_replay_is_deterministic, validated="live",
    ),
    Capability(
        "contradiction_tracking",
        "Two admitted WORLD results that disagree about one hypothesis are recorded "
        "as a contradiction and raise verification debt.",
        ("openworld/state.py",),
        ("tests/regressions/test_capability_register.py",),
        live_path=_contradiction_fires,
        limits="Derived from evidence outcome disagreement on differing experiment "
               "identities. A conflict with literature must be reported explicitly.",
    ),
    Capability(
        "resource_awareness",
        "Measured spend against declared limits can refuse an action.",
        ("openworld/resources.py", "openworld/scheduler.py"),
        ("tests/test_research_termination.py",),
        live_path=_budget_filter_refuses, validated="live",
    ),
    Capability(
        "verification_debt",
        "A claim standing on a single measurement raises high-impact verification debt.",
        ("openworld/actions.py", "openworld/frontier.py"),
        ("tests/regressions/test_capability_register.py",),
        live_path=_sole_support_debt_fires,
    ),
    Capability(
        "experimental_power",
        "A registered experiment reports the units it measured, so the adequacy bar "
        "is reachable rather than permanently unmet.",
        ("probeexp.py", "openworld/workers.py", "openworld/quality.py"),
        ("tests/regressions/test_live_run_defects.py",),
        live_path=_sample_size_reachable, validated="live",
        limits="The attested world's size bounds the report; a larger claim is refused. "
               "No power calculation is performed, only a reported count.",
    ),
    Capability(
        "no_caveat_only_repair",
        "An objection requiring new evidence cannot be closed by rewriting.",
        ("openworld/quality.py", "openworld/reducer.py"),
        ("tests/regressions/test_caveat_only_repair.py",),
        live_path=_caveat_repair_refused, validated="live",
    ),
    Capability(
        "goal_maintenance",
        "A question that has left the contract's root question is recorded as drift "
        "and blocks readiness.",
        ("openworld/contract.py", "openworld/reducer.py"),
        ("tests/test_research_contract.py", "tests/behavioral/test_research_scenarios.py"),
        live_path=_goal_drift_detected, validated="live",
        limits="A lexical anchor guard. It cannot tell that two phrasings share an estimand.",
    ),
    Capability(
        "termination_semantics",
        "Readiness is a conjunction of gates over evidence, objections and scope; a "
        "finished loop or an exhausted budget is not an answer.",
        ("openworld/termination.py",),
        ("tests/test_research_termination.py",),
        live_path=_readiness_can_refuse_and_grant, validated="live",
    ),
    Capability(
        "consensus_is_not_evidence",
        "Agreeing reviewers move no belief and produce no verified knowledge.",
        ("openworld/state.py", "openworld/kernel.py", "openworld/quality.py"),
        ("tests/behavioral/test_research_scenarios.py",),
        live_path=_consensus_is_not_evidence,
    ),
    Capability(
        "world_selection_authority",
        "Choosing the object of study is a contract decision; a blocked run reports "
        "what would unlock it instead of picking its own subject matter.",
        ("openworld/recipes.py", "openworld/executors.py", "openworld/contract.py"),
        ("tests/test_research_acquisition.py",),
        live_path=_acquisition_needs_authorisation,
    ),
    Capability(
        "no_idle_repetition",
        "An action that twice returned the same outcome while admitting nothing is "
        "not offered again.",
        ("openworld/actions.py",),
        ("tests/test_research_efficiency.py",),
        live_path=_inert_action_refused, validated="live",
    ),
    Capability(
        "strategic_stagnation",
        "A project whose every tick succeeds while the central question does not move "
        "is recognised as stagnant.",
        ("openworld/progress.py",),
        ("tests/behavioral/test_research_scenarios.py",),
        live_path=_strategic_stagnation_fires,
    ),
    Capability(
        "trajectory_conditioned_exploration",
        "Historical scientific transitions, grounded in citation lineage, propose "
        "operators for a first-hop hypothesis.",
        ("explore.py", "openworld/workers.py"),
        ("tests/test_research_retrieval.py",),
        status=PARTIAL, live_path=None,
        limits="The matcher works, but building the library needs one retrieved paper "
               "to cite another, and keyword retrieval rarely returns such a pair. In "
               "three live runs the library was empty every time and the lane was "
               "correctly not offered.",
        note="Blocked on retrieval that can follow citation edges, not on corpus size.",
    ),
    Capability(
        "project_pivot",
        "A direction that cannot be repaired is retired, preserving its WORLD evidence "
        "and the contract while dropping its speculative narrative.",
        ("openworld/executors.py", "openworld/restart.py", "openworld/reducer.py"),
        ("tests/behavioral/test_research_scenarios.py", "tests/behavioral/test_long_horizon.py"),
        live_path=_pivot_preserves_evidence,
        limits="Exercised in offline scenarios and long-horizon trajectories only. No "
               "live segment has reached a pivot; all three ended on budget at ten ticks.",
    ),
    Capability(
        "heldout_replication",
        "A result is replicated on a different attested world before it generalises.",
        ("openworld/workers.py",),
        ("tests/test_research_replication.py",),
        status=PARTIAL, live_path=None,
        limits="Implemented and offline-tested. No live segment has completed a transfer; "
               "the replication path was reached but not finished within budget.",
    ),
    Capability(
        "harness_self_improvement",
        "A routing-policy change is admitted only on an evaluator-issued single-use "
        "receipt with strict heldout improvement.",
        ("routing.py", "openworld/evolve.py"),
        ("tests/test_research_policy_admission.py",),
        status=PARTIAL, live_path=None,
        limits="Research-time evolution records proposals only. Admission requires "
               "trusted application-supplied evaluation, which no live run has exercised. "
               "This is not evidence that recursive self-improvement works.",
    ),
)


def register() -> tuple[Capability, ...]:
    return REGISTER


def audit() -> dict[str, Any]:
    """Run every live-path probe. A claim whose mechanism cannot fire is a failure.

    A capability claiming ``implemented`` without a live-path probe is itself a
    failure. An unchecked claim is how every defect in this register's history
    survived: the mechanism was described, the description was believed, and
    nothing asked it to demonstrate itself.
    """
    rows, failures = [], []
    for capability in REGISTER:
        row = capability.to_dict()
        if capability.live_path is None:
            row["live_path"] = "not_checked"
            if capability.status == IMPLEMENTED:
                failures.append(f"{capability.name}: claims implemented with no live-path check")
            elif not capability.limits:
                failures.append(f"{capability.name}: {capability.status} without stated limits")
        else:
            try:
                ok = bool(capability.live_path())
            except Exception as exc:  # a probe that raises is a failing claim
                ok, row["error"] = False, repr(exc)
            row["live_path"] = "fires" if ok else "DOES_NOT_FIRE"
            if not ok and capability.status == IMPLEMENTED:
                failures.append(capability.name)
        rows.append(row)
    return {
        "kind": "capability_register_audit",
        "capabilities": rows,
        "claimed_implemented": sum(1 for c in REGISTER if c.status == IMPLEMENTED),
        "partial": sum(1 for c in REGISTER if c.status == PARTIAL),
        "live_path_failures": failures,
        "ok": not failures,
    }
