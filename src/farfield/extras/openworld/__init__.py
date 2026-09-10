"""Verified open-world research environment.

Production control plane: ScientificState → Frontier → Affordance →
Scheduler → Executor → TrustedKernel → Event → Reducer.

mission.py may bootstrap this environment. It must not own the next action.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping

from ..generate import GeneratedCard
from ..ideakind import idea_kind_of
from ..lifecycle import ResearchNotebook, load_notebook, save_notebook
from .actions import (
    ACQUIRE,
    ACTION_TYPES,
    ASK,
    PROJECT_PIVOT,
    REDESIGN,
    REVIEW,
    VERIFY,
    EVOLVE_HARNESS,
    FORK_LINEAGE,
    OBSERVE,
    PROBE,
    REFLECT,
    SPECS,
    THEORIZE,
    ActionInstance,
    eligible_actions,
)
from .capability import (
    CapabilityRegistry,
    load_capabilities,
    run_capability,
    save_capabilities,
)
from .env import (
    HarnessVersion,
    load_harness,
    project_harness,
    projection_lines,
    save_harness,
)
from .events import EventLog, load_event_log, make_event, save_event_log
from .evolve import (
    HARNESS_FAILURE,
    PATHOLOGY_FLOOR,
    SCIENTIFIC_FAILURE,
    CandidatePatch,
    CreditReport,
    Pathology,
    accumulate_pathology,
    apply_admitted_patch,
    classify_failure,
    evaluate_patch,
    load_pathologies,
    pathology_ready,
    propose_patch,
    save_pathologies,
)
from .executors import DEFAULT_EXECUTORS, maybe_gc, resolve_world_root, fixture_from_root
from .worldio import is_attested
from .frontier import SCIENTIFIC_ACTIONS, traces_to_root
from .kernel import (
    MUTABLE_MODULES,
    TRUSTED_KERNEL,
    CandidateResult,
    as_candidate,
    can_promote_to_world,
    make_run_context,
    preserve_evidence_provenance,
    sanitize_evidence_candidate,
    social_consensus_is_not_evidence,
)
from .memory import (
    ArchiveStore,
    add_failure,
    add_harness,
    add_scientific,
    add_working,
    load_archives,
    project_archive,
    projection_token_count,
    save_archives,
)
from .contract import ResearchContract, contract_from_state, root_alignment
from .progress import (
    LANES,
    fork_trajectories,
    judge_branches,
    maybe_stagnation,
    maybe_strategic_stagnation,
    measure_progress,
    merge_branch,
    merge_branches,
    should_terminate,
    update_metrics,
)
from .quality import compute_quality, open_reviews, review_debt
from .resources import budget_phase, budget_state
from .restart import clean_restart_projection
from .reducer import apply_events, rebuild_state, state_digest
from .scheduler import ScoredAction, admissible, schedule, schedule_all
from .state import (
    SCIENTIFIC_STATE_FILE,
    ScientificState,
    load_scientific_state,
    notebook_projection,
    save_scientific_state,
    state_is_empty,
    sync_from_notebook,
)


Executor = Callable[["OpenWorld", ActionInstance], Any]


@dataclass
class OpenWorld:
    workspace: Path | None
    state: ScientificState = field(default_factory=ScientificState)
    harness: HarnessVersion = field(default_factory=lambda: HarnessVersion(version_id="H0"))
    capabilities: CapabilityRegistry = field(default_factory=CapabilityRegistry)
    archives: ArchiveStore = field(default_factory=ArchiveStore)
    pathologies: dict[str, Pathology] = field(default_factory=dict)
    executors: dict[str, Executor] = field(default_factory=dict)
    last_scheduled: ScoredAction | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    log: EventLog = field(default_factory=EventLog)
    workers_connected: bool = False

    def connect_workers(self, adapter: Any) -> None:
        """Bind worker services, never their own orchestration loop or state writer."""
        from copy import deepcopy
        import time

        for kind, worker in adapter.executors().items():
            def invoke(env: "OpenWorld", action: ActionInstance, worker: Any = worker) -> Any:
                if action.action_type == "VERIFY" and action.extra.get("evidence_role") == "QuestionEvidence":
                    return DEFAULT_EXECUTORS["VERIFY"](env, action)
                ledger = getattr(getattr(adapter, "client", None), "ledger", None)
                before_tokens = float(getattr(ledger, "spent_tokens", 0))
                before_calls = float(getattr(ledger, "spent_calls", 0))
                started = time.monotonic()
                result = as_candidate(worker(action, deepcopy(env.state.to_dict()), workspace=env.workspace,
                              world_id=env.state.world_id, projection=env.project_for(action)))
                # Calls, not actions. One SURVEY can extract a dozen papers, and
                # the resource view billing it as a single api_call disagreed
                # with the ledger that actually enforces the envelope — two
                # meters of the same name, an order of magnitude apart.
                cost = {"tokens": float(getattr(ledger, "spent_tokens", 0)) - before_tokens,
                        "api_calls": float(getattr(ledger, "spent_calls", 0)) - before_calls,
                        "wall_seconds": time.monotonic() - started}
                result.extras["measured_cost"] = cost
                if result.evidence is not None:
                    result.evidence["measured_cost"] = cost
                result.events = [replace(event, payload={**event.payload, "measured_cost": {
                    k: float((event.payload.get("measured_cost") or {}).get(k) or 0) + cost[k] for k in cost}})
                    if event.event_type == "EvidenceAdded" else event for event in result.events]
                return result
            self.executors[kind] = invoke
        self.workers_connected = True

    @classmethod
    def load(cls, workspace: Path | None) -> "OpenWorld":
        env = cls(workspace=workspace)
        env.state = load_scientific_state(workspace)
        env.harness = load_harness(workspace)
        env.capabilities = load_capabilities(workspace)
        env.archives = load_archives(workspace)
        env.pathologies = load_pathologies(workspace)
        env.log = load_event_log(workspace)
        notebook = load_notebook(workspace)
        if state_is_empty(env.state) and notebook is not None:
            sync_from_notebook(env.state, notebook)
        env.state.harness_version = env.harness.version_id
        env.state.available_capabilities = list(
            dict.fromkeys(
                list(env.state.available_capabilities) + list(env.capabilities.names())
            )
        )
        return env

    def persist(self) -> None:
        self.state.harness_version = self.harness.version_id
        save_scientific_state(self.workspace, self.state)
        save_harness(self.workspace, self.harness)
        save_capabilities(self.workspace, self.capabilities)
        save_archives(self.workspace, self.archives)
        save_pathologies(self.workspace, self.pathologies)
        save_event_log(self.workspace, self.log)
        if self.workspace is not None:
            save_notebook(
                self.workspace,
                ResearchNotebook.from_dict(notebook_projection(self.state)),
            )

    def eligible(self, *, probe_ready: Mapping[str, Any] | None = None) -> list[ActionInstance]:
        strategic = maybe_strategic_stagnation(self.state)
        # A busy-but-stuck project should widen its options, not only an idle one.
        stagnant = maybe_stagnation(self.state) is not None or strategic is not None
        return eligible_actions(
            self.state,
            capabilities=self.capabilities.names(),
            pathology_ready=bool(pathology_ready(self.pathologies)),
            stagnation=stagnant,
            probe_ready=probe_ready,
            workers_connected=self.workers_connected,
            strategic_stagnation=strategic,
        )

    def schedule(self, actions: list[ActionInstance] | None = None) -> ScoredAction | None:
        pool = actions if actions is not None else self.eligible()
        chosen = schedule(self.state, pool)
        self.last_scheduled = chosen
        return chosen

    def project_for(self, action: ActionInstance) -> dict[str, Any]:
        """The context this action should see — not the whole trajectory.

        The projection carries the contract, the derived decision journal, the
        evidence relevant to this action's target, the standing objections and
        the remaining budget. After a pivot it carries the clean restart instead
        of the retired direction's narrative, so an abandoned line cannot anchor
        the work that replaces it.
        """
        from .journal import contingency_plan, research_journal

        overlay = project_harness(
            self.harness,
            action_type=action.action_type,
            lineage_id=action.lineage_id,
        )
        archive = project_archive(
            self.archives,
            action_type=action.action_type,
            world_id=self.state.world_id,
        )
        theory_id = str(action.extra.get("theory_id") or action.target or "")
        journal = research_journal(
            self.state,
            question_id=str(action.frontier_target_id or ""),
            theory_id=theory_id,
        )
        payload = {
            "harness_lines": projection_lines(
                self.harness, action_type=action.action_type, lineage_id=action.lineage_id
            ),
            "archive": archive,
            "archive_tokens": projection_token_count(archive),
            "overlay_names": [item.name for item in overlay],
            "research_journal": journal,
            "research_contract": journal["research_contract"],
            "open_objections": journal["open_objections"],
            "relevant_world_evidence": journal["relevant_world_evidence"],
            "remaining_resources": journal["resources"],
        }
        if action.action_type in {PROBE, VERIFY}:
            payload["contingency_plan"] = contingency_plan(self.state, action)
        if int(self.state.project_epoch or 0):
            restart = next(
                (row for row in reversed(self.state.artifacts)
                 if row.get("kind") == "clean_restart_projection"), None)
            if restart is not None:
                payload["clean_restart"] = restart
        payload["projection_tokens"] = projection_token_count(payload)
        return payload

    def note_harness_failure(self, *, where: str, why: str, example: str = "") -> Pathology:
        row = accumulate_pathology(self.pathologies, where=where, why=why, example=example)
        add_failure(
            self.archives,
            {
                "class": HARNESS_FAILURE,
                "where": where,
                "why": why,
                "example": example,
                "count": row.count,
            },
        )
        return row

    def note_scientific_failure(self, *, why: str, example: str = "") -> None:
        add_failure(
            self.archives,
            {"class": SCIENTIFIC_FAILURE, "why": why, "example": example},
        )

    def _ensure_baseline(self) -> None:
        if not self.log.baseline:
            self.log.baseline = self.state.to_dict()

    def _admit(self, action: ActionInstance, candidate: CandidateResult) -> CandidateResult:
        """TrustedKernel mutation boundary. Executors cannot write WORLD or state."""
        def checked(row: Mapping[str, Any]) -> dict[str, Any]:
            payload = dict(row)
            generated_origin = any(str(payload.get(k) or "").upper() in {"GENERATED", "SYNTHETIC", "PLACEBO", "E0_SYNTHETIC"}
                for k in ("kind", "probe_kind", "world_role", "provenance", "world_provenance"))
            if generated_origin:
                payload.update(epistemic="GENERATED", attested=False,
                               promotion_refused="generated provenance cannot be relabelled WORLD")
            if payload.get("epistemic") == "WORLD":
                wid = str(payload.get("world_id") or "")
                root = resolve_world_root(self.workspace, wid)
                fixture = fixture_from_root(root, wid) if root else None
                if not (fixture and is_attested(fixture)
                        and (payload.get("world_digest") or payload.get("digest")) == fixture.digest):
                    payload.update(epistemic="GENERATED", attested=False,
                                   promotion_refused="WORLD evidence needs a matching attested freeze digest")
            sanitized, _ = sanitize_evidence_candidate(payload)
            return sanitized or payload

        world = None
        events = [replace(event, payload=checked(event.payload))
                  if event.event_type == "EvidenceAdded" else event
                  for event in candidate.events or []]
        evidence = checked(candidate.evidence) if candidate.evidence is not None else None
        gap = str((evidence or {}).get("promotion_refused") or "")
        if evidence is not None:
            ok, gaps = can_promote_to_world(evidence, world=world)
            evidence["promotion_ok"] = ok
            evidence["promotion_gaps"] = list(gaps)
            if not ok and str(evidence.get("epistemic") or "") == "WORLD":
                evidence["epistemic"] = "GENERATED"
                evidence["attested"] = False
                gap = gap or "; ".join(gaps)
            already = any(
                getattr(item, "event_type", "") == "EvidenceAdded"
                and dict(getattr(item, "payload", {})).get("evidence_id") == evidence.get("evidence_id")
                for item in events
            )
            if not already:
                events.append(
                    make_event(
                        "EvidenceAdded",
                        evidence,
                        action_type=action.action_type,
                        frontier_target_id=action.frontier_target_id or action.target,
                    )
                )
        admitted_evidence = [event.payload for event in events if event.event_type == "EvidenceAdded"]
        valid_ids = {row.get("evidence_id") for row in admitted_evidence
                     if row.get("promotion_ok") and not row.get("cannot_corroborate")}
        events = [event for event in events
                  if event.event_type not in {"QuestionResolved", "QuestionPartiallyResolved"}
                  or event.payload.get("evidence_id") in valid_ids]
        return CandidateResult(
            status=candidate.status,
            events=events,
            evidence=evidence,
            world_id=candidate.world_id or self.state.world_id,
            evidence_id=candidate.evidence_id or str((evidence or {}).get("evidence_id") or ""),
            unlocked=candidate.unlocked,
            integrity_gap=gap or candidate.integrity_gap,
            harness_general=candidate.harness_general,
            extras=dict(candidate.extras),
        )

    def execute(self, action: ActionInstance) -> dict[str, Any]:
        before = ScientificState.from_dict(self.state.to_dict())
        self._ensure_baseline()
        projection = self.project_for(action)
        frontier_id = action.frontier_target_id or action.target or self.state.goal
        if action.action_type in SCIENTIFIC_ACTIONS and not frontier_id:
            candidate = CandidateResult(
                status="blocked",
                events=[
                    make_event(
                        "ActionBlocked",
                        {"reason": "no_frontier_target"},
                        action_type=action.action_type,
                    )
                ],
                extras={"reason": "no_frontier_target"},
            )
        else:
            fn = self.executors.get(action.action_type)
            if fn is None:
                fn = self.executors.get(action.spec.executor)
            if fn is None:
                fn = DEFAULT_EXECUTORS.get(action.action_type)
            if fn is None:
                # "recorded" reads as success. An action nothing can perform
                # should say that, so a spec added without an executor fails
                # loudly instead of appearing to do its job.
                raw: Any = {"status": "blocked", "action": action.action_type,
                            "reason": "no_executor_for_this_action"}
            else:
                raw = fn(self, action)
            if action.action_type == EVOLVE_HARNESS and not callable(
                self.executors.get(EVOLVE_HARNESS)
            ):
                raw = self.evolve()
            candidate = as_candidate(raw)
        admitted = self._admit(action, candidate)
        if self.workers_connected:
            from .actions import _action_variant, action_input_key
            admitted.events.append(make_event("ArtifactAdded", {
                "kind": "action_attempt", "action_type": action.action_type,
                "project_epoch": int(before.project_epoch),
                "target": action.target, "status": admitted.status,
                "input_key": action_input_key(before, action),
                # What made this attempt distinct from its siblings, so a
                # repeated failure can be diagnosed without replaying the log.
                "variant": _action_variant(action),
                "research_lane": action.extra.get("research_lane", ""),
                # How much this attempt actually changed, so a repeatedly inert
                # action type can be recognised within the run rather than
                # rediscovered every tick.
                "events_admitted": len([
                    e for e in admitted.events
                    if e.event_type not in {"ActionBlocked", "ActionFailed"}]),
                "reason": admitted.extras.get("reason", ""),
                # What this attempt actually came back with. Two identical
                # outcomes from the same action on the same target is a fact the
                # controller has already learned.
                "outcome_key": str(
                    admitted.extras.get("reason")
                    or admitted.extras.get("outcome")
                    or admitted.integrity_gap
                    or admitted.status or ""),
                "theory_id": action.extra.get("theory_id", ""),
                "question_id": action.extra.get("question_id", ""),
                "measured_cost": admitted.extras.get("measured_cost", {}),
            }, action_type=action.action_type))
        preview = apply_events(self.state, admitted.events)
        progress = measure_progress(before, preview)
        tick_event = make_event(
            "TickAdvanced",
            {
                "meaningful": progress.meaningful,
                # Operational progress and research progress are different
                # claims and drive different clocks.
                "research_meaningful": progress.research_meaningful,
                "central_question_progress": progress.central_question_progress,
                "decision_relevant_evidence": progress.decision_relevant_evidence,
                "quality_gap_reduction": progress.quality_gap_reduction,
                "critical_review_resolution": progress.critical_review_resolution,
                "peripheral_question_progress": progress.peripheral_question_progress,
                "caveat_only_repair": progress.caveat_only_repair,
                "same_failure_repetition": progress.same_failure_repetition,
                "low_value_activity": progress.low_value_activity,
                "successful_reorientation": progress.successful_reorientation,
                "replication_progress": progress.replication_progress,
                "quality_dimension_progress": progress.quality_dimension_progress,
                "objection_discovery": progress.objection_discovery,
                "failure_information": progress.failure_information,
                "action_type": action.action_type,
                "frontier_target_id": frontier_id,
                "scripted": False,
                "unlock": admitted.unlocked,
                "integrity_gap": admitted.integrity_gap,
                "archive_hit": bool(
                    projection["archive"].get("scientific") or projection["archive"].get("harness")
                ),
                "harness_general": admitted.harness_general,
                "goal_drift": bool(
                    action.action_type in SCIENTIFIC_ACTIONS
                    and frontier_id
                    and not traces_to_root(before, frontier_id)
                ),
            },
            action_type=action.action_type,
            frontier_target_id=frontier_id,
        )
        self.state = apply_events(
            self.state,
            list(admitted.events) + [tick_event],
            log=self.log,
            action=action,
        )
        context = make_run_context(
            world_id=str(admitted.world_id or self.state.world_id),
            evidence_id=str(admitted.evidence_id or ""),
            harness_version=self.harness.version_id,
            capability_versions={
                name: self.capabilities.items[name].version
                for name in self.capabilities.names()
                if name in self.capabilities.items
            },
        )
        result = admitted.to_dict()
        result.setdefault("action_type", action.action_type)
        result.setdefault("target", action.target)
        result["frontier_target_id"] = frontier_id
        result["projection"] = {
            "overlay_names": projection["overlay_names"],
            "archive_tokens": projection["archive_tokens"],
            "projection_tokens": projection.get("projection_tokens"),
            "harness_lines": list(projection["harness_lines"]),
            "objections_shown": [row.get("review_id") for row in projection["open_objections"]],
            "next_decisive_action": projection["research_journal"]["next_decisive_action"],
        }
        result["run_context"] = context.to_dict()
        result["harness_version"] = self.harness.version_id
        result["world_id"] = self.state.world_id or admitted.world_id
        if admitted.evidence:
            evidence = dict(admitted.evidence)
            evidence.setdefault("run_context", context.to_dict())
            evidence.setdefault("harness_version", self.harness.version_id)
            if evidence.get("promotion_ok"):
                add_scientific(self.archives, evidence)
            else:
                add_working(self.archives, evidence)
            result["evidence"] = evidence
        maybe_gc(self)
        self.history.append(result)
        self.persist()
        return result

    def evolve(self, patch: CandidatePatch | None = None, **gate: Any) -> dict[str, Any]:
        """Record research-time proposals; admission belongs after mission settlement.

        Legacy caller-supplied cases are accepted for API compatibility, but
        cannot authorize installation during scientific research.
        """
        ready = pathology_ready(self.pathologies)
        if patch is None:
            if not ready:
                return {"status": "no_pathology"}
            patch = propose_patch(ready[0])
        parent_world = self.state.world_id
        parent_harness = self.harness.version_id
        reason = "research_policy_requires_completed_mission_and_heldout_receipt"
        events = [
            make_event(
                "HarnessPatchProposed",
                {
                    "pathology": patch.pathology,
                    "module": patch.module,
                    "status": "proposed",
                    "reason": reason,
                },
                action_type=EVOLVE_HARNESS,
            )
        ]
        add_harness(
            self.archives,
            {
                "patch": patch.to_dict(),
                "status": "proposed",
                "reason": reason,
                "harness_version": parent_harness,
                "parent": parent_harness,
                "world_unchanged": True,
            },
        )
        self._ensure_baseline()
        self.state = apply_events(self.state, events, log=self.log)
        return {
            "status": "proposed",
            "reason": reason,
            "harness_version": self.harness.version_id,
            "parent_harness": parent_harness,
            "world_id": self.state.world_id,
            "world_unchanged": self.state.world_id == parent_world,
            "capability": patch.capability.name if patch.capability else "",
            "unlocked": False,
            "harness_general": False,
            "events_applied": True,
        }

    def tick(self, *, probe_ready: Mapping[str, Any] | None = None) -> dict[str, Any]:
        actions = self.eligible(probe_ready=probe_ready)
        _, refused = admissible(self.state, actions)
        chosen = self.schedule(actions)
        event = {
            "stage": "openworld_tick",
            "controller": "OpenWorld",
            "eligible": [item.to_dict() for item in actions],
            "eligible_types": [item.action_type for item in actions],
            # An eligible action that the scheduler refuses must say why, or a
            # whole action type can vanish from a run unnoticed.
            "refused": refused,
            "stagnation": None
            if maybe_stagnation(self.state) is None
            else maybe_stagnation(self.state).to_dict(),
            "strategic_stagnation": None
            if maybe_strategic_stagnation(self.state) is None
            else maybe_strategic_stagnation(self.state).to_dict(),
        }
        if chosen is None:
            event["scheduled"] = None
            return event
        event["scheduled"] = chosen.to_dict()
        result = self.execute(chosen.action)
        event["result"] = result
        event["metrics"] = dict(self.state.metrics)
        event["harness_version"] = self.harness.version_id
        event["world_id"] = self.state.world_id
        event["frontier"] = dict(self.state.frontier)
        event["debt"] = dict(self.state.debt)
        event["quality"] = dict(self.state.quality)
        event["objective"] = dict(self.state.objective)
        from .exploration import trajectory_metrics

        event["trajectory"] = trajectory_metrics(self.state)
        event["resources"] = dict(self.state.resources)
        event["project_epoch"] = int(self.state.project_epoch)
        return event

    def run(
        self,
        horizon: int,
        *,
        probe_ready: Mapping[str, Any] | None = None,
        stop_on_exhaust: bool = True,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for _ in range(max(0, int(horizon))):
            if stop_on_exhaust:
                reason = should_terminate(self.state, horizon=horizon)
                if reason and reason != "budget":
                    events.append({"stage": "terminate", "reason": reason})
                    break
            events.append(self.tick(probe_ready=probe_ready))
        return events


def after_card(
    workspace: Path | None,
    card: GeneratedCard | Mapping[str, Any] | None,
    bundle: Mapping[str, Any] | None = None,
    *,
    world: Any = None,
) -> list[dict[str, Any]]:
    """Legacy mission hook. Sync state and emit one scheduler view.

    Does not decide generate → review → diagnose → experiment.
    Production research uses OpenWorld.run / run_research.
    """
    if workspace is None:
        return []
    env = OpenWorld.load(workspace)
    if card is not None:
        kind = idea_kind_of(card)
        claim = (
            str(card.get("claim") or "")
            if isinstance(card, Mapping)
            else str(getattr(card, "claim", "") or "")
        )
        qid = (
            str(card.get("card_id") or "")
            if isinstance(card, Mapping)
            else str(getattr(card, "card_id", "") or "")
        )
        lineage = (
            str(card.get("lineage_id") or "")
            if isinstance(card, Mapping)
            else str(getattr(card, "lineage_id", "") or "")
        )
        if kind == "question" and claim:
            env.state.add_question(
                question_id=qid or f"q-{len(env.state.open_questions)+1}",
                text=claim,
                required_capability=_card_required_capability(card),
                lineage_id=lineage,
                epistemic="GENERATED",
            )
        if kind == "acquire":
            env.state.note_missing(claim or "world")
        if world is not None:
            env.state.world_id = str(getattr(world, "id", "") or env.state.world_id)
    probe_ready = None
    if bundle and bundle.get("diagnosis"):
        diag = bundle["diagnosis"]
        lever = str(getattr(diag, "world_lever", "") or "")
        measure = str(getattr(diag, "world_observable", "") or "")
        if lever and measure:
            probe_ready = {
                "causal_handle": lever,
                "measure": measure,
                "freeze": env.state.world_id,
            }
    actions = env.eligible(probe_ready=probe_ready)
    chosen = env.schedule(actions)
    env.persist()
    return [
        {
            "stage": "openworld_tick",
            "eligible_types": [item.action_type for item in actions],
            "scheduled": None if chosen is None else chosen.to_dict(),
            "executed": False,
            "harness_version": env.harness.version_id,
            "world_id": env.state.world_id,
            "reason": "state_driven_affordance",
        }
    ]


def _card_required_capability(card: Any) -> str:
    fields = {}
    if isinstance(card, Mapping):
        raw = card.get("kind_fields")
        if isinstance(raw, Mapping):
            fields = dict(raw)
        fields.setdefault("required_world_state", card.get("required_world_state") or "")
        fields.setdefault("capability_gap", card.get("capability_gap") or "")
    else:
        raw = getattr(card, "kind_fields", None)
        if isinstance(raw, Mapping):
            fields = dict(raw)
    return str(
        fields.get("required_capability")
        or fields.get("capability_gap")
        or fields.get("required_world_state")
        or ""
    ).strip()


def dry_run_openworld(workspace: Path) -> list[dict[str, Any]]:
    """The required architecture chain, deterministic, no live API."""
    env = OpenWorld(workspace=workspace)
    env.state.goal = "does validator-version history change acceptance?"
    env.state.world_id = "W0"
    env.state.world_versions.append({"id": "W0", "world_id": "W0", "observables": ""})
    env.state.add_question(
        question_id="Q13",
        text="does validator-version history change acceptance?",
        required_capability="compare_validator_snapshots",
        lineage_id="line-q13",
        epistemic="GENERATED",
    )
    env.state.note_missing("compare_validator_snapshots")
    env.persist()
    events: list[dict[str, Any]] = []

    for _ in range(PATHOLOGY_FLOOR):
        observe = ActionInstance(
            SPECS[OBSERVE],
            target="Q13",
            reason="forced_observe_attempt",
            frontier_target_id="Q13",
            extra={
                "question": {
                    "id": "Q13",
                    "required_capability": "compare_validator_snapshots",
                    "text": env.state.goal,
                }
            },
        )
        events.append({"stage": "forced_observe", **env.execute(observe)})

    ev = env.tick()
    events.append(ev)
    if env.harness.version_id == "H0" and pathology_ready(env.pathologies):
        events.append({"stage": "forced_evolve", **env.evolve()})

    observe_now = ActionInstance(
        SPECS[OBSERVE],
        target="Q13",
        reason="capability_unlocked",
        frontier_target_id="Q13",
        extra={
            "question": {
                "id": "Q13",
                "required_capability": "compare_validator_snapshots",
                "text": env.state.goal,
            },
            "records": [
                {"validator_version": "v1", "ok": True},
                {"validator_version": "v2", "ok": False},
            ],
        },
    )
    events.append({"stage": "observe_after_h1", **env.execute(observe_now)})

    if env.state.open_questions or env.state.resolved_questions:
        theory = ActionInstance(
            SPECS[THEORIZE],
            target="Q13",
            reason="after_observation",
            lineage_id="line-q13",
            frontier_target_id="Q13",
        )
        events.append({"stage": "theory_eligible", **env.execute(theory)})
    env.persist()
    events.append(
        {
            "stage": "dry_run_summary",
            "harness_version": env.harness.version_id,
            "world_id": env.state.world_id,
            "capabilities": list(env.capabilities.names()),
            "resolved": [row.get("id") for row in env.state.resolved_questions],
            "metrics": dict(env.state.metrics),
        }
    )
    return events
