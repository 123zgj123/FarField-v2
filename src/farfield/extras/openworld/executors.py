"""Real scientific action executors. They return candidates, never write state."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..lifecycle import derive_world_version, next_world_label
from ..world import WorldFixture, digest_files, load_fixture
from .worldio import is_attested, summarize
from .actions import (
    ACQUIRE,
    ARCHIVE,
    ASK,
    FORK_LINEAGE,
    PROJECT_PIVOT,
    REDESIGN,
    REVIEW,
    OBSERVE,
    PROBE,
    REFLECT,
    SURVEY,
    SYNTHESIZE,
    THEORIZE,
    VERIFY,
    ActionInstance,
)
from .capability import run_capability
from .env import gc_harness
from .events import make_event
from .evolve import HARNESS_FAILURE
from .frontier import frontier_from_state
from .kernel import CandidateResult
from .progress import fork_trajectories


RESOLVED = "RESOLVED"
PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
AMBIGUOUS = "AMBIGUOUS"
NO_DATA = "NO_DATA"
MEASUREMENT_INVALID = "MEASUREMENT_INVALID"
WORLD_INCOMPATIBLE = "WORLD_INCOMPATIBLE"

SNAPSHOT_FILE = "validator_snapshots.json"


@dataclass
class ObservationPlan:
    target_question: str
    required_world: str
    required_artifacts: tuple[str, ...] = ()
    observable: str = ""
    alignment: str = "validator_version"
    contrast: str = ""
    measurement: str = "compare_validator_snapshots"
    sanity_checks: tuple[str, ...] = ("aligned", "contrast")
    missingness_policy: str = "block"
    interpretation_scope: str = "observational"
    expected_failure_modes: tuple[str, ...] = (
        NO_DATA,
        MEASUREMENT_INVALID,
        WORLD_INCOMPATIBLE,
    )
    causal_scope: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_question": self.target_question,
            "required_world": self.required_world,
            "required_artifacts": list(self.required_artifacts),
            "observable": self.observable,
            "alignment": self.alignment,
            "contrast": self.contrast,
            "measurement": self.measurement,
            "sanity_checks": list(self.sanity_checks),
            "missingness_policy": self.missingness_policy,
            "interpretation_scope": self.interpretation_scope,
            "expected_failure_modes": list(self.expected_failure_modes),
            "causal_scope": self.causal_scope,
        }


@dataclass
class AcquirePlan:
    required_inputs: tuple[str, ...] = ("parent_world",)
    actions: tuple[str, ...] = ("extract_or_build_validator_snapshots",)
    tools: tuple[str, ...] = ("derive_world_version",)
    expected_artifacts: tuple[str, ...] = (
        SNAPSHOT_FILE,
        "binaries/config.json",
        "validation/outputs.json",
        "replay_interface.json",
        "provenance.json",
    )
    artifact_schema: str = "validator_snapshots/v1"
    validator: str = "snapshot_files_present"
    success_predicates: tuple[str, ...] = ("digest_differs", "artifacts_present")
    failure_predicates: tuple[str, ...] = ("no_parent_world",)
    rollback: str = "leave_parent_untouched"
    cost: float = 0.8
    timeout: float = 30.0
    provenance: str = "harvested"

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_inputs": list(self.required_inputs),
            "actions": list(self.actions),
            "tools": list(self.tools),
            "expected_artifacts": list(self.expected_artifacts),
            "artifact_schema": self.artifact_schema,
            "validator": self.validator,
            "success_predicates": list(self.success_predicates),
            "failure_predicates": list(self.failure_predicates),
            "rollback": self.rollback,
            "cost": self.cost,
            "timeout": self.timeout,
            "provenance": self.provenance,
        }


def resolve_world_root(workspace: Path | None, world_id: str) -> Path | None:
    if workspace is None or not world_id:
        return None
    dest = Path(workspace)
    for candidate in (
        dest / "worlds" / world_id,
        dest / world_id,
        dest / "data",
    ):
        if candidate.is_dir() and any(candidate.iterdir()):
            return candidate
    return None


def fixture_from_root(root: Path, world_id: str) -> WorldFixture:
    if (root / "manifest.json").is_file():
        fixture = load_fixture(root)
        if fixture.id != world_id:
            raise ValueError("world id differs from workspace manifest")
        return fixture
    files = sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.name != "manifest.json"
    )
    digest = digest_files(root, files) if files else ""
    return WorldFixture(
        id=world_id,
        title=world_id,
        source="workspace",
        retrieved_at="2026-09-07",
        digest=digest,
        files=tuple(files),
        root=root,
        role="generated",
        provenance="generated",
        version=world_id,
    )


def load_json_artifact(root: Path | None, rel: str) -> Any | None:
    if root is None:
        return None
    path = Path(root) / rel
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def observation_plan_from(action: ActionInstance, state: Mapping[str, Any]) -> ObservationPlan:
    question = dict(action.extra.get("question") or {})
    observable = str(
        question.get("required_observable")
        or action.extra.get("observable")
        or "validator_snapshots"
    )
    artifacts = tuple(
        item
        for item in (
            SNAPSHOT_FILE,
            observable if observable.endswith(".json") else "",
        )
        if item
    )
    return ObservationPlan(
        target_question=str(question.get("id") or action.target or ""),
        required_world=str(state.get("world_id") or action.extra.get("world_id") or ""),
        required_artifacts=artifacts or (SNAPSHOT_FILE,),
        observable=observable,
        contrast=str(question.get("text") or action.target or ""),
    )


def execute_observe(env: Any, action: ActionInstance) -> CandidateResult:
    view = env.state.view()
    question = dict(action.extra.get("question") or {})
    qid = str(question.get("id") or action.target or "")
    needed = str(question.get("required_capability") or "").strip()
    plan = observation_plan_from(action, view)
    if needed and not env.capabilities.has(needed):
        env.note_harness_failure(
            where="question_observation_executor",
            why="cannot_align_versioned_records",
            example=qid,
        )
        return CandidateResult(
            status="observe_failed",
            events=[
                make_event(
                    "ActionFailed",
                    {
                        "class": HARNESS_FAILURE,
                        "where": "question_observation_executor",
                        "why": "cannot_align_versioned_records",
                        "question_id": qid,
                    },
                    action_type=OBSERVE,
                    frontier_target_id=qid,
                )
            ],
            extras={
                "class": HARNESS_FAILURE,
                "where": "question_observation_executor",
                "why": "cannot_align_versioned_records",
                "plan": plan.to_dict(),
            },
        )

    world_id = str(view.get("world_id") or "")
    world_root = resolve_world_root(env.workspace, world_id)
    fixture = fixture_from_root(world_root, world_id) if world_root else None
    if fixture is not None and plan.observable != "validator_snapshots" and not needed:
        result = summarize(fixture)
        evidence_id = "obs-" + hashlib.sha256(
            json.dumps([world_id, fixture.digest, qid, "descriptives-v1"]).encode()
        ).hexdigest()
        return CandidateResult(
            status="observed",
            evidence={
                "role": "QuestionEvidence", "question_id": qid,
                "question": question.get("text") or action.target,
                "world_id": world_id, "world_digest": fixture.digest,
                "evidence_id": evidence_id, "result": result,
                "epistemic": "WORLD" if is_attested(fixture) else "GENERATED",
                "attested": is_attested(fixture), "outcome": PARTIALLY_RESOLVED,
                "exploratory": True, "cannot_corroborate": True,
                "interpretation": "Dataset descriptives; the research question remains open.",
                "measurement": "descriptives-v1", "read_from_world": True,
                "harness_version": env.harness.version_id,
            },
            world_id=world_id, evidence_id=evidence_id,
            extras={"outcome": PARTIALLY_RESOLVED},
        )
    records = list(action.extra.get("records") or [])
    read_from_world = False
    if not records and world_root is not None:
        for rel in plan.required_artifacts:
            if fixture is not None and rel not in fixture.files:
                continue
            payload = load_json_artifact(world_root, rel)
            if isinstance(payload, Mapping) and payload.get("records"):
                records = list(payload.get("records") or [])
                read_from_world = True
                break
            if isinstance(payload, list):
                records = list(payload)
                read_from_world = True
                break

    if not records:
        if plan.missingness_policy == "block":
            return CandidateResult(
                status="blocked",
                events=[
                    make_event(
                        "ActionBlocked",
                        {
                            "reason": NO_DATA,
                            "question_id": qid,
                            "gap": plan.observable or SNAPSHOT_FILE,
                            "unlocks": ACQUIRE,
                        },
                        action_type=OBSERVE,
                        frontier_target_id=qid,
                    )
                ],
                extras={"outcome": NO_DATA, "plan": plan.to_dict(), "gap": plan.observable},
            )
        return CandidateResult(status="observe_failed", extras={"outcome": NO_DATA})

    if world_id and action.extra.get("required_world") and action.extra.get("required_world") != world_id:
        return CandidateResult(
            status="observe_failed",
            extras={"outcome": WORLD_INCOMPATIBLE, "plan": plan.to_dict()},
        )

    if needed:
        observed = run_capability(needed, records=records)
        env.capabilities.record_use(needed, success=bool(observed.get("aligned")), tick=int(view.get("ticks") or 0))
    else:
        versions = sorted(
            {
                str(row.get("validator_version") or row.get("version") or "")
                for row in records
                if isinstance(row, Mapping)
            }
            - {""}
        )
        observed = {
            "versions": versions,
            "aligned": len(versions) >= 2,
            "contrast": f"{versions[0]} vs {versions[-1]}" if len(versions) >= 2 else "",
        }

    if not isinstance(observed, Mapping):
        outcome = MEASUREMENT_INVALID
    elif not observed.get("aligned"):
        outcome = AMBIGUOUS
    elif observed.get("aligned") and observed.get("contrast"):
        outcome = RESOLVED
    else:
        outcome = PARTIALLY_RESOLVED

    attested = bool(read_from_world and fixture and is_attested(fixture))
    evidence_id = "obs-" + hashlib.sha256(json.dumps(
        [world_id, fixture.digest if fixture else "", qid, observed], sort_keys=True
    ).encode()).hexdigest()
    evidence = {
        "role": "QuestionEvidence",
        "question": question.get("text") or action.target,
        "question_id": qid,
        "contrast": observed.get("contrast") if isinstance(observed, Mapping) else "",
        "result": observed,
        "outcome": outcome,
        "interpretation": "observational contrast; not a causal claim",
        "causal_scope": "none",
        "epistemic": "WORLD" if attested else "GENERATED",
        "attested": attested,
        "world_id": world_id,
        "world_digest": fixture.digest if fixture else "",
        "evidence_id": evidence_id,
        "harness_version": env.harness.version_id,
        "capability": needed,
        "read_from_world": read_from_world,
        "plan": plan.to_dict(),
    }
    events = []
    if outcome == RESOLVED and question.get("resolution_contract") == "validator_version_contrast":
        events.append(
            make_event(
                "QuestionResolved",
                {"id": qid, "evidence_id": evidence_id, "outcome": outcome},
                action_type=OBSERVE,
                frontier_target_id=qid,
            )
        )
    elif outcome == PARTIALLY_RESOLVED and question.get("resolution_contract") == "validator_version_contrast":
        events.append(
            make_event(
                "QuestionPartiallyResolved",
                {"id": qid, "evidence_id": evidence_id, "outcome": outcome},
                action_type=OBSERVE,
                frontier_target_id=qid,
            )
        )
    return CandidateResult(
        status="observed",
        events=events,
        evidence=evidence,
        evidence_id=evidence_id,
        world_id=world_id,
        unlocked=bool(events),
        extras={"outcome": outcome, "plan": plan.to_dict()},
    )


def _parent_records(root: Path | None) -> list[dict[str, Any]]:
    payload = load_json_artifact(root, "world.json")
    if isinstance(payload, Mapping):
        traces = payload.get("records") or payload.get("traces") or []
        if isinstance(traces, list) and traces:
            records = []
            for index, item in enumerate(traces):
                if isinstance(item, Mapping) and (item.get("validator_version") or item.get("version")):
                    row = dict(item)
                    row.setdefault("validator_version", row.get("version"))
                    records.append(row)
            return records
    return []


def build_acquire_artifacts(parent_root: Path | None, *, child_id: str, parent_id: str) -> dict[str, str]:
    records = _parent_records(parent_root)
    snapshots = {
        "schema": "validator_snapshots/v1",
        "world_id": child_id,
        "parent_id": parent_id,
        "records": records,
        "binaries": {"validator": "offline-config"},
    }
    config = {
        "child_id": child_id,
        "parent_id": parent_id,
        "dependency_digest": hashlib.sha256(
            json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16],
        "replay": "replay_interface.json",
    }
    validation = {
        "passed": len({r["validator_version"] for r in records}) >= 2,
        "checks": ["schema", "two_versions", "parent_untouched"],
        "n_records": len(records),
    }
    replay = {
        "interface": "compare_validator_snapshots",
        "input": SNAPSHOT_FILE,
        "output": ["versions", "contrast", "aligned"],
    }
    provenance = {
        "parent_id": parent_id,
        "child_id": child_id,
        "recipe": "extract_or_build_validator_snapshots",
        "attested": bool(parent_root and is_attested(fixture_from_root(parent_root, parent_id))),
    }
    return {
        SNAPSHOT_FILE: json.dumps(snapshots, ensure_ascii=False, indent=2) + "\n",
        "binaries/config.json": json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        "validation/outputs.json": json.dumps(validation, ensure_ascii=False, indent=2) + "\n",
        "replay_interface.json": json.dumps(replay, ensure_ascii=False, indent=2) + "\n",
        "provenance.json": json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
    }


def execute_acquire(env: Any, action: ActionInstance) -> CandidateResult:
    plan = AcquirePlan()
    view = env.state.view()
    parent_id = str(view.get("world_id") or "")
    parent_root = resolve_world_root(env.workspace, parent_id)
    extra_root = action.extra.get("world_root")
    if extra_root:
        parent_root = Path(extra_root)
        parent_id = parent_id or parent_root.name
    if parent_root is None:
        return CandidateResult(
            status="acquire_proposed",
            extras={
                "gap": action.extra.get("gap") or action.target,
                "world_id": parent_id,
                "harness_version": env.harness.version_id,
                "plan": plan.to_dict(),
                "reason": "no_parent_world_on_disk",
            },
            world_id=parent_id,
        )
    parent = fixture_from_root(parent_root, parent_id or parent_root.name)
    gap = str(action.extra.get("gap") or "validator_snapshots")
    from .recipes import CATALOG_BINDING, resolve_recipe

    bound = {str(row.get("id") or row.get("world_id") or "")
             for row in view.get("world_versions") or []}
    catalog = action.extra.get("catalog")
    if catalog is None:
        from ..freeze import default_catalog

        catalog = default_catalog()
    question = dict(action.extra.get("question") or {})
    from .contract import contract_from_state

    # Deriving a child from the bound parent stays with the current object of
    # study. Binding a *different* world changes what the results are about, so
    # the contract has to authorise it.
    authorised = contract_from_state(env.state).world_selection == "catalog_match"
    recipe = resolve_recipe(
        gap, catalog=Path(catalog),
        parent_supports_derivation=bool(_parent_records(parent_root)),
        exclude=bound,
        question=str(question.get("text") or view.get("goal") or ""))
    if recipe is not None and recipe.kind == CATALOG_BINDING and not authorised:
        # Report what *would* satisfy this gap. A blocked run that names its
        # unlock is useful; one that silently picks its own subject matter is
        # answering a question nobody asked.
        return CandidateResult(
            status="blocked", world_id=parent.id,
            events=[make_event("ActionBlocked", {
                "reason": "world_selection_not_authorised_by_contract",
                "question_id": action.target, "gap": gap,
                "candidate_world": recipe.world_id,
            }, action_type=ACQUIRE,
                frontier_target_id=action.frontier_target_id or action.target)],
            extras={"reason": "world_selection_not_authorised_by_contract", "gap": gap,
                    "candidate_recipes": [recipe.to_dict()],
                    "next": ("Bind the world explicitly, or set the contract's "
                             "world_selection to 'catalog_match' to let the run choose "
                             "an attested catalog world for itself.")},
        )
    if recipe is None:
        return CandidateResult(
            status="blocked", world_id=parent.id,
            events=[make_event("ActionBlocked", {
                "reason": "no_acquisition_recipe", "question_id": action.target,
                "gap": gap,
            }, action_type=ACQUIRE, frontier_target_id=action.frontier_target_id or action.target)],
            extras={"reason": "no_acquisition_recipe", "gap": gap,
                    "next": "Provide a frozen dataset and a matching acquisition recipe."},
        )
    if recipe.kind == CATALOG_BINDING:
        # Bind bytes that were already attested. Nothing is fetched, nothing is
        # synthesized, and the attestation check still decides.
        from .worldio import bind_fixture

        try:
            bound_world = bind_fixture(Path(env.workspace), load_fixture(Path(recipe.root)),
                                       recipe.world_id)
        except (OSError, ValueError, KeyError) as exc:
            return CandidateResult(
                status="blocked", world_id=parent.id,
                events=[make_event("ActionBlocked", {
                    "reason": "catalog_world_could_not_be_bound", "gap": gap,
                    "world_id": recipe.world_id, "detail": str(exc),
                }, action_type=ACQUIRE,
                    frontier_target_id=action.frontier_target_id or action.target)],
                extras={"reason": "catalog_world_could_not_be_bound", "gap": gap})
        if not is_attested(bound_world):
            return CandidateResult(
                status="blocked", world_id=parent.id,
                events=[make_event("ActionBlocked", {
                    "reason": "bound_world_is_not_attested", "gap": gap,
                    "world_id": recipe.world_id,
                }, action_type=ACQUIRE,
                    frontier_target_id=action.frontier_target_id or action.target)],
                extras={"reason": "bound_world_is_not_attested", "gap": gap})
        payload = {
            "id": bound_world.id, "world_id": bound_world.id, "digest": bound_world.digest,
            "observables": bound_world.schema, "files": list(bound_world.files),
            "path": str(bound_world.root), "schema": bound_world.schema,
            "domains": list(bound_world.domains or ()),
            # An acquired world is the object under study, never a heldout
            # replication world: naming it so would let a single freeze
            # replicate itself.
            "research_role": "world", "role": "world",
            "acquisition_recipe": recipe.to_dict(),
        }
        return CandidateResult(
            status="acquired", world_id=bound_world.id, unlocked=True,
            events=[
                make_event("WorldCreated", payload, action_type=ACQUIRE,
                           frontier_target_id=action.frontier_target_id or action.target),
                make_event("WorldAttested", {
                    "id": bound_world.id, "world_id": bound_world.id,
                    "digest": bound_world.digest,
                    "world_evidence_id": bound_world.world_evidence_id,
                }, action_type=ACQUIRE,
                    frontier_target_id=action.frontier_target_id or action.target),
                make_event("CapabilityValidated", {"name": gap, "world_id": bound_world.id,
                                                   "basis": "attested_catalog_world"},
                           action_type=ACQUIRE),
            ],
            extras={"gap": gap, "recipe": recipe.to_dict(), "world_id": bound_world.id,
                    "plan": plan.to_dict()},
        )
    child_id = next_world_label(parent_id or "W0")
    dest = Path(env.workspace) / "worlds" / child_id if env.workspace else parent_root.parent / child_id
    artifacts = build_acquire_artifacts(parent_root, child_id=child_id, parent_id=parent.id)
    child = derive_world_version(
        parent,
        dest,
        new_id=child_id,
        acquisition_event=f"acquire:{action.target or child_id}",
        idea_id=str(action.target or ""),
        parent_version=parent_id or "W0",
        extra_artifacts=artifacts,
    )
    events = [
        make_event(
            "WorldCreated",
            {
                "id": child.id,
                "world_id": child.id,
                "parent_id": parent.id,
                "digest": child.digest,
                "observables": "validator_snapshots",
                "files": list(child.files),
                "path": str(child.root),
            },
            action_type=ACQUIRE,
            frontier_target_id=action.frontier_target_id or action.target,
        ),
        make_event(
            "WorldAttested",
            {
                "id": child.id,
                "world_id": child.id,
                "digest": child.digest,
                "world_evidence_id": child.world_evidence_id,
            },
            action_type=ACQUIRE,
            frontier_target_id=action.frontier_target_id or action.target,
        ),
        make_event(
            "ArtifactAdded",
            {"world_id": child.id, "files": list(plan.expected_artifacts), "digest": child.digest},
            action_type=ACQUIRE,
            frontier_target_id=action.frontier_target_id or action.target,
        ),
    ]
    attested = is_attested(child)
    if not attested:
        events = [event for event in events if event.event_type != "WorldAttested"]
    evidence = {
        "role": "AcquisitionEvidence",
        "world_id": child.id,
        "parent_world": parent.id,
        "evidence_id": child.world_evidence_id,
        "digest": child.digest,
        "parent_digest": parent.digest,
        "epistemic": "WORLD" if attested else "GENERATED",
        "attested": attested,
        "harness_version": env.harness.version_id,
        "artifacts": list(plan.expected_artifacts),
        "plan": plan.to_dict(),
    }
    return CandidateResult(
        status="acquired",
        events=events,
        evidence=evidence,
        world_id=child.id,
        evidence_id=child.world_evidence_id,
        unlocked=True,
        extras={
            "parent_digest": parent.digest,
            "child_digest": child.digest,
            "files": list(child.files),
            "harness_version": env.harness.version_id,
            "plan": plan.to_dict(),
        },
    )


def execute_theorize(env: Any, action: ActionInstance) -> CandidateResult:
    view = env.state.view()
    qid = action.target or action.frontier_target_id
    question = next(
        (row for row in view.get("open_questions") or [] if row.get("id") == qid),
        {},
    )
    if not any("validator" in str(item).lower() for item in [question, view.get("goal")]):
        return CandidateResult(status="blocked", extras={
            "reason": "topic_theory_executor_not_connected",
            "next": "Connect the research workers through run_research with a configured model.",
        })
    evidence = list(view.get("evidence_records") or [])
    anomalies = list(view.get("anomalies") or [])
    competing = list(view.get("competing_explanations") or ["null_no_version_effect"])
    mechanism = (
        "validator-version history changes acceptance if snapshots differ"
        if any("validator" in str(item).lower() for item in [question, view.get("goal")])
        else f"mechanism for {qid or view.get('goal')}"
    )
    tid = f"T-{qid or 'goal'}"
    preds = [
        {
            "prediction": "aligned validator snapshots yield a contrast",
            "maps_to": OBSERVE,
            "competitor_differs": True,
            "competitor": competing[0] if competing else "null",
        },
        {
            "prediction": "a two-arm freeze on the same measure separates the mechanism",
            "maps_to": PROBE,
            "competitor_differs": True,
            "competitor": competing[0] if competing else "null",
        },
    ]
    theory = {
        "id": tid,
        "question_id": qid,
        "target": qid,
        "text": action.target or mechanism,
        "assumptions": ["world artifacts are versioned", "measurement is observational"],
        "mechanism": mechanism,
        "predictions": [item["prediction"] for item in preds],
        "boundary_conditions": ["same world lineage", "no harness rewrite of evidence"],
        "competing": competing,
        "discriminating_predictions": preds,
        "anomalies": anomalies[:4],
        "evidence_considered": [str(row.get("evidence_id") or "") for row in evidence[:6]],
        "epistemic": "GENERATED",
    }
    return CandidateResult(
        status="theorized",
        events=[
            make_event(
                "TheoryCreated",
                theory,
                action_type=THEORIZE,
                frontier_target_id=qid or action.frontier_target_id,
            )
        ],
        extras={"epistemic": "GENERATED", "theory": theory},
    )


def execute_verify(env: Any, action: ActionInstance) -> CandidateResult:
    view = env.state.view()
    kind = str(action.extra.get("verify_kind") or "VERIFY_REPLICATION")
    world_id = str(view.get("world_id") or "")
    world_root = resolve_world_root(env.workspace, world_id)
    candidates = [
        row
        for row in view.get("evidence_records") or []
        if row.get("evidence_id")
    ]
    target = None
    for row in candidates:
        if str(row.get("epistemic") or "") == "WORLD" and int(row.get("verify_count") or 0) < 1:
            target = dict(row)
            break
    if target is None and candidates:
        target = dict(candidates[-1])
    if target is None:
        return CandidateResult(status="verify_skipped", extras={"reason": "no_evidence"})

    records = []
    if world_root is not None:
        payload = load_json_artifact(world_root, SNAPSHOT_FILE)
        if isinstance(payload, Mapping):
            records = list(payload.get("records") or [])
    fixture = fixture_from_root(world_root, world_id) if world_root else None
    replay_ok = False
    if fixture and is_attested(fixture):
        if target.get("measurement") == "descriptives-v1":
            replay_ok = (target.get("world_digest") == fixture.digest and target.get("result") == summarize(fixture))
        elif target.get("role") == "AcquisitionEvidence":
            replay_ok = target.get("digest") == fixture.digest
    compatible = str(target.get("world_id") or "") in {"", world_id}
    if not compatible:
        kind = "VERIFY_WORLD_COMPATIBILITY"
        replay_ok = False
    updated = dict(target)
    updated["verify_count"] = int(target.get("verify_count") or 0) + 1
    updated["verify_kind"] = kind
    updated["verified_by"] = f"verify-{env.harness.version_id}-{updated['verify_count']}"
    updated["world_compatible"] = compatible
    updated["replay_ok"] = replay_ok
    if str(updated.get("epistemic") or "") != "WORLD":
        updated["epistemic"] = str(target.get("epistemic") or "GENERATED")
        updated["attested"] = False
    events = [
        make_event(
            "EvidenceAdded",
            updated,
            action_type=VERIFY,
            frontier_target_id=action.frontier_target_id or str(target.get("question_id") or ""),
        )
    ]
    return CandidateResult(
        status="verified",
        events=events,
        extras={"verify_kind": kind, "replay_ok": replay_ok, "world_compatible": compatible},
        evidence_id=str(updated.get("evidence_id") or ""),
        world_id=world_id,
        unlocked=replay_ok,
    )


def execute_probe(env: Any, action: ActionInstance) -> CandidateResult:
    extra = dict(action.extra or {})
    if not (extra.get("causal_handle") and extra.get("measure") and (extra.get("freeze") or env.state.world_id)):
        return CandidateResult(
            status="probe_not_forced",
            extras={"reason": "no_default_two_arm"},
        )
    treatment = extra.get("treatment")
    control = extra.get("control")
    if treatment is None or control is None:
        return CandidateResult(
            status="probe_not_forced",
            extras={"reason": "arms_not_provided", "reuse": "diagnose.judge_probe"},
        )
    evidence_id = f"probe-{env.state.world_id}-{action.target or 'h'}"
    evidence = {
        "role": "ProbeEvidence",
        "evidence_id": evidence_id,
        "world_id": env.state.world_id,
        "causal_handle": extra.get("causal_handle"),
        "measure": extra.get("measure"),
        "treatment": treatment,
        "control": control,
        "epistemic": "GENERATED",
        "attested": False,
        "harness_version": env.harness.version_id,
    }
    return CandidateResult(
        status="probed",
        evidence=evidence,
        evidence_id=evidence_id,
        world_id=env.state.world_id,
        extras={"reuse": "diagnose.judge_probe"},
    )


def execute_ask(env: Any, action: ActionInstance) -> CandidateResult:
    qid = f"q-{len(env.state.open_questions)+1}"
    return CandidateResult(
        status="asked",
        events=[
            make_event(
                "QuestionCreated",
                {
                    "id": qid,
                    "text": action.target or env.state.goal,
                    "epistemic": "GENERATED",
                    "lineage_id": action.lineage_id,
                },
                action_type=ASK,
                frontier_target_id=action.frontier_target_id or qid,
            )
        ],
        extras={"question_id": qid},
    )


def execute_survey(env: Any, action: ActionInstance) -> CandidateResult:
    return CandidateResult(
        status="blocked",
        extras={"citations": [], "reason": "literature_executor_not_connected",
                "gaps": list(env.state.missing_capabilities)},
    )


def execute_reflect(env: Any, action: ActionInstance) -> CandidateResult:
    """Turn failures into reusable lessons and name the ones that keep recurring.

    This used to return a summary and emit no events at all — an action that
    always reported success and was structurally incapable of changing anything.
    Reflection's declared effect is ``record_pathology_or_anomaly``; it now does
    that, and a repeated failure signature becomes an anomaly the controller can
    act on rather than a fact only a human reader would notice.
    """
    from .evolve import pathology_ready
    from .restart import failure_lesson

    ready = pathology_ready(env.pathologies)
    known = {str(row.get("signature") or "") for row in env.state.artifacts
             if row.get("kind") == "failure_lesson"}
    counts: dict[str, int] = {}
    events, lessons = [], []
    for row in env.state.failed_designs:
        signature = "|".join(str(row.get(key) or "") for key in
                             ("action_type", "theory_id", "reason"))
        counts[signature] = counts.get(signature, 0) + 1
        if signature in known:
            continue
        known.add(signature)
        lesson = {**failure_lesson(row), "kind": "failure_lesson", "signature": signature,
                  "id": f"lesson-{len(known)}"}
        lessons.append(lesson)
        events.append(make_event("ArtifactAdded", lesson, action_type=REFLECT))
    repeated = sorted(name for name, count in counts.items() if count >= 2)
    for signature in repeated:
        text = f"repeated_failure:{signature}"
        if text not in env.state.anomalies:
            events.append(make_event("ArtifactAdded", {
                "kind": "anomaly", "id": text, "text": text,
                "why_it_matters": "the same design failed the same way twice; "
                                  "repeating it is not an experiment",
            }, action_type=REFLECT))
    return CandidateResult(
        status="reflected" if events else "nothing_new_to_reflect_on",
        events=events,
        extras={"pathologies": [row.to_dict() for row in ready],
                "lessons": lessons, "repeated_failures": repeated},
    )


def execute_synthesize(env: Any, action: ActionInstance) -> CandidateResult:
    snapshot = frontier_from_state(env.state)
    snapshot.update(
        {
            "known": [row.get("evidence_id") for row in env.state.evidence_records if row.get("attested")],
            "weaker": [row.get("id") for row in env.state.theories if row.get("status") == "weakened"],
            "unresolved": [row.get("id") for row in env.state.open_questions],
            "surviving_theories": [row.get("id") for row in env.state.theories],
            "conflicts": list(env.state.contradictions),
            "capabilities": list(env.state.available_capabilities),
            "stale_worlds": [
                row.get("id") or row.get("world_id")
                for row in env.state.world_versions
                if str(row.get("id") or row.get("world_id") or "") != env.state.world_id
            ],
            "debt": dict(env.state.debt),
        }
    )
    if env.workspace is not None:
        dest = Path(env.workspace) / "FRONTIER_SNAPSHOT.json"
        dest.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return CandidateResult(
        status="synthesized",
        events=[
            make_event(
                "FrontierChanged",
                {"frontier": snapshot},
                action_type=SYNTHESIZE,
                frontier_target_id=action.frontier_target_id,
            )
        ],
        extras={"snapshot": snapshot},
    )


def execute_archive(env: Any, action: ActionInstance) -> CandidateResult:
    """Record what was closed, so archiving is idempotent and inspectable.

    Previously a no-op that reported success, which made it look like work every
    time it ran and gave the value precondition nothing to check against.
    """
    closed = sorted(str(row.get("id") or "") for row in env.state.resolved_questions)
    failed = sorted({"|".join(str(row.get(key) or "") for key in ("action_type", "theory_id"))
                     for row in env.state.failed_designs})
    previous = next((row for row in reversed(env.state.artifacts)
                     if row.get("kind") == "archive_record"), {})
    if (list(previous.get("closed_questions") or []) == closed
            and list(previous.get("closed_designs") or []) == failed):
        return CandidateResult(status="nothing_new_to_archive",
                               extras={"reason": "archive_already_records_this_set"})
    record = {"kind": "archive_record", "id": f"archive-{len(env.state.artifacts) + 1}",
              "closed_questions": closed, "closed_designs": failed,
              "epistemic": "GENERATED",
              "note": "an archive entry is bookkeeping, never a promotion"}
    return CandidateResult(status="archived",
                           events=[make_event("ArtifactAdded", record, action_type=ARCHIVE)],
                           extras=record)


def fork_candidates(state: Any) -> list[dict[str, Any]]:
    """Directions this project could pursue in parallel, grounded in its state.

    A lane is only real if a later tick can act on it. These come from recorded
    facts — quality dimensions that are short and name their own repair, and
    competing explanations that were written down and never tested — not from
    invented alternatives.
    """
    quality = getattr(state, "quality", {}) or {}
    if not quality.get("dimensions"):
        from .quality import compute_quality

        quality = compute_quality(state)
    dimensions = quality.get("dimensions") or {}
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    # Capability gaps and untheorized questions are branch points too, and they
    # exist before any quality projection does.
    for name in list(getattr(state, "missing_capabilities", []) or []):
        if name in seen:
            continue
        seen.add(name)
        out.append({"lane": f"capability:{name}", "capability": name,
                    "next_action": "ACQUIRE",
                    "because": "a missing capability blocks part of the frontier"})
    explained = {str(row.get("question_id") or row.get("target") or "")
                 for row in getattr(state, "theories", []) or []}
    for question in list(getattr(state, "open_questions", []) or []) + list(
            getattr(state, "blocked_questions", []) or []):
        qid = str(question.get("id") or "")
        if not qid or qid in explained or qid in seen:
            continue
        seen.add(qid)
        out.append({"lane": f"understanding:{qid}", "question_id": qid,
                    "next_action": "THEORIZE",
                    "because": "an open question has no candidate explanation"})
    for name in list(quality.get("quality_gap") or []):
        work = list((dimensions.get(name) or {}).get("required_next_work") or [])
        if not work or name in seen:
            continue
        seen.add(name)
        out.append({
            "lane": f"quality:{name}", "dimension": name, "next_action": work[0],
            "because": "; ".join((dimensions.get(name) or {}).get("blocking_reasons") or []),
        })
    measured = {str(row.get("theory_id") or "") for row in getattr(state, "evidence_records", []) or []}
    for theory in getattr(state, "theories", []) or []:
        tid = str(theory.get("id") or "")
        if (theory.get("role") != "competing_explanation" or not tid
                or tid in measured or tid in seen or theory.get("status") == "retired"):
            continue
        seen.add(tid)
        out.append({
            "lane": f"competing:{tid}", "theory_id": tid, "next_action": "PROBE",
            "because": "a recorded competing explanation has never been tested",
        })
    return out


def execute_fork(env: Any, action: ActionInstance) -> CandidateResult:
    """Open lineages that later ticks can actually pursue."""
    candidates = list(action.extra.get("fork_candidates") or fork_candidates(env.state))
    if len(candidates) < 2:
        return CandidateResult(
            status="blocked",
            events=[make_event("ActionBlocked", {"reason": "no_distinct_branch_to_open"},
                               action_type=FORK_LINEAGE)],
            extras={"reason": "no_distinct_branch_to_open"})
    branches = fork_trajectories(env.state, harness_version=env.harness.version_id,
                                 n=len(candidates),
                                 preferred_actions=tuple(row["next_action"] for row in candidates))
    lineages = [str(row["lane"]) for row in candidates]
    events = [make_event("LineageForked", {
        "lineages": lineages,
        "candidates": candidates,
        "harness_version": env.harness.version_id,
    }, action_type=FORK_LINEAGE)]
    return CandidateResult(
        status="forked",
        events=events,
        extras={
            "lanes": lineages,
            "next_actions": [row["next_action"] for row in candidates],
            "branches": [row.to_dict() for row in branches],
        },
    )


# ---------------------------------------------------------------------------
# Project-level executors
# ---------------------------------------------------------------------------


def _structural_objections(state: Any) -> list[dict[str, Any]]:
    """Objections the canonical state already proves, with no model in the loop.

    This is deliberately *not* an LLM reviewer. Everything below is a fact the
    runtime recorded about its own evidence: an unreported sample size, a
    measure that did not move for the oracle, a control arm that measured
    nothing, a single-world result. Making these structural means the control
    loop keeps working offline and cannot be talked out of an objection.

    A model reviewer can add judgment dimensions on top; it cannot remove these.
    """
    from .contract import contract_from_state
    from .quality import DIMENSIONS

    contract = contract_from_state(state)
    min_sample = float((contract.resource_limits or {}).get("min_sample_size") or 0)
    probes = [
        dict(row) for row in state.evidence_records
        if str(row.get("role") or "") == "ProbeEvidence"
        and str(row.get("epistemic") or "") == "WORLD"
        and row.get("attested")
    ]
    out: list[dict[str, Any]] = []

    def add(**row: Any) -> None:
        row.setdefault("dimension", "technical_correctness")
        if row["dimension"] not in DIMENSIONS:
            row["dimension"] = "technical_correctness"
        out.append(row)

    for row in probes:
        eid = str(row.get("evidence_id") or "")
        tid = str(row.get("theory_id") or "")
        qid = str(row.get("question_id") or "")
        sample = row.get("sample_size")
        if sample is None:
            add(review_id=f"review-power-{eid}", severity="major",
                dimension="experimental_adequacy",
                objection=("the result reports no sample size, so its power is "
                           "unknown and it cannot support the claim"),
                affected_claim=str(row.get("claim") or tid), affected_design=eid,
                repair_type="experiment_redesign", requires_new_evidence=True,
                theory_id=tid, question_id=qid)
        elif min_sample and float(sample) < min_sample:
            add(review_id=f"review-power-{eid}", severity="major",
                dimension="experimental_adequacy",
                objection=(f"n={sample:g} is below the contract's minimum "
                           f"informative sample of {min_sample:g}; a positive "
                           "result at this size is not decisive"),
                affected_claim=str(row.get("claim") or tid), affected_design=eid,
                repair_type="experiment_redesign", requires_new_evidence=True,
                theory_id=tid, question_id=qid)
        if row.get("dv_blind"):
            add(review_id=f"review-measure-{eid}", severity="fatal",
                dimension="measurement_validity",
                objection="the measure did not respond to the oracle placebo; it "
                          "is not measuring the claimed quantity",
                affected_design=eid, repair_type="measurement_redesign",
                requires_new_evidence=True, theory_id=tid, question_id=qid)
        if row.get("object_absent"):
            add(review_id=f"review-baseline-{eid}", severity="fatal",
                dimension="baseline_strength",
                objection="both arms measured nothing; there is no comparison here",
                affected_design=eid, repair_type="experiment_redesign",
                requires_new_evidence=True, theory_id=tid, question_id=qid)
        elif row.get("ablation_required"):
            add(review_id=f"review-ablation-{eid}", severity="major",
                dimension="baseline_strength",
                objection="a competing mechanism is not ablated, so the effect is "
                          "not attributable to the proposed one",
                affected_design=eid, repair_type="stronger_baseline",
                requires_new_evidence=True, theory_id=tid, question_id=qid)
        if row.get("cannot_corroborate"):
            add(review_id=f"review-validity-{eid}", severity="fatal",
                dimension="technical_correctness",
                objection="; ".join(str(x) for x in row.get("validation_gaps") or [])
                          or "validation gates did not pass for this evidence",
                affected_design=eid, repair_type="experiment_redesign",
                requires_new_evidence=True, theory_id=tid, question_id=qid)
        if row.get("outcome") == "supports" and not row.get("mechanism_validated"):
            add(review_id=f"review-mechanism-{eid}", severity="major",
                dimension="mechanism_support",
                objection="a positive arithmetic result is not a verified "
                          "mechanism; the causal account is untested",
                affected_design=eid, repair_type="causal_redesign",
                requires_new_evidence=True, theory_id=tid, question_id=qid)
        if not any(other.get("replication_of") == eid for other in probes):
            add(review_id=f"review-replication-{eid}", severity="major",
                dimension="replication",
                objection="a single-world result does not generalize; no heldout "
                          "replication has been attempted",
                affected_design=eid, repair_type="broader_evaluation",
                requires_new_evidence=True, theory_id=tid, question_id=qid)

    # Novelty and importance cannot be executed into existence. What the state
    # *can* ground is that a literature check ran and did not find the claim
    # already stated — which supports "not obviously known", not "important".
    surveys = [row for row in state.artifacts
               if row.get("kind") == "literature_survey" and row.get("works")]
    for theory in state.theories:
        tid = str(theory.get("id") or "")
        if theory.get("role") == "competing_explanation" or not tid:
            continue
        checks = [row for row in surveys if str(row.get("theory_id") or "") == tid]
        if not checks:
            continue
        prior = (checks[-1].get("prior") or {})
        if prior.get("kills"):
            add(review_id=f"review-novelty-{tid}", severity="fatal", dimension="novelty",
                objection="verified literature already states this claim",
                affected_claim=str(theory.get("claim") or tid),
                repair_type="project_pivot", requires_new_evidence=True, theory_id=tid)
            continue
        refs = [str(c) for c in checks[-1].get("citations") or []]
        add(review_id=f"assessment-novelty-{tid}", severity="minor", dimension="novelty",
            objection="", assessment="partial", supporting_refs=refs,
            assessment_basis=("a prior check over verified literature did not find this "
                              "claim already stated; that is not a novelty proof"),
            repair_type="writing_only", theory_id=tid)

    drifted = list((state.metrics or {}).get("drifted_questions") or [])
    if drifted:
        central = ((state.quality or {}).get("dimensions") or {}).get(
            "central_claim_support") or {}
        all_drifted = "PROJECT_PIVOT" in (central.get("required_next_work") or [])
        add(review_id=f"review-drift-epoch{int(getattr(state, 'project_epoch', 0))}",
            severity="fatal" if all_drifted else "major",
            dimension="central_claim_support",
            objection=("the active line of work no longer answers the contract's "
                       f"root question; drifted questions: {sorted(drifted)}"),
            repair_type="project_pivot" if all_drifted else "assumption_reframe",
            requires_new_evidence=True)
    return out


def execute_review(env: Any, action: ActionInstance) -> CandidateResult:
    """Record structured objections against the current project state.

    Reviewer judgment is a planning signal. It opens repair debt and lowers
    quality dimensions; it never adds evidence and never raises belief. Ten
    reviewers agreeing is still zero measurements.
    """
    from .quality import normalize_review

    proposed = list(action.extra.get("reviews") or []) + _structural_objections(env.state)
    known = {str(row.get("review_id") or "") for row in env.state.reviews}
    events, recorded = [], []
    for row in proposed:
        record = normalize_review(row, tick=int(env.state.ticks))
        if record["review_id"] in known:
            continue
        known.add(record["review_id"])
        recorded.append(record)
        events.append(make_event("ReviewRecorded", record, action_type=REVIEW,
                                 frontier_target_id=action.frontier_target_id))
    return CandidateResult(
        status="reviewed" if recorded else "no_new_objections",
        events=events,
        extras={
            "reviews": recorded,
            "objection_count": len(recorded),
            "basis": "structural_objections_from_canonical_state",
            "not_evidence": "reviewer judgment never corroborates a claim",
        },
    )


def execute_redesign(env: Any, action: ActionInstance) -> CandidateResult:
    """Turn an objection into an explicit DesignRevision.

    Not "generate another hypothesis". A revision has to name what failed, which
    assumption it invalidates, which repairs were considered and rejected, what
    is preserved, what changes, and the condition under which this revision is
    itself abandoned early.
    """
    from .quality import REPAIR_DIMENSION, ReviewRecord

    demand = dict(action.extra.get("demand") or {})
    review = next((dict(row) for row in env.state.reviews
                   if str(row.get("review_id") or "") == str(demand.get("review_id") or "")
                   and demand.get("review_id")), {})
    record = ReviewRecord.from_dict(review) if review else None
    dimension = str(demand.get("dimension") or (record.dimension if record else "technical_correctness"))
    selected = str(demand.get("repair_type") or (record.repair_type if record else "experiment_redesign"))
    theory_id = str(demand.get("theory_id") or action.target or "")
    parent = next((dict(row) for row in env.state.theories
                   if str(row.get("id") or "") == theory_id), {})
    failures = [dict(row) for row in env.state.failed_designs
                if str(row.get("theory_id") or "") == theory_id]

    candidates = [
        name for name in
        ("experiment_redesign", "measurement_redesign", "stronger_baseline",
         "causal_redesign", "broader_evaluation", "assumption_reframe",
         "representation_change")
        if REPAIR_DIMENSION.get(name) == dimension or name == selected
    ] or [selected]
    rejected = [
        {"repair": name,
         "why_not": f"does not address {dimension}: the objection survives it"}
        for name in candidates if name != selected
    ]
    root_cause = (
        str(demand.get("objection") or "")
        or (failures[-1].get("reason") if failures else "")
        or f"{dimension}_below_contract"
    )
    revision = {
        "revision_id": (
            f"rev-{int(env.state.project_epoch)}-{dimension}-"
            f"{len(env.state.design_revisions) + 1}"
        ),
        "trigger": str(action.reason or "unresolved_objection"),
        "parent_design": theory_id or str(demand.get("dimension") or ""),
        "failure_root_cause": root_cause,
        "invalidated_assumption": (
            (parent.get("assumptions") or [""])[0] if parent.get("assumptions")
            else f"the current design can establish {dimension}"
        ),
        "unresolved_objection": str(demand.get("review_id") or "") or root_cause,
        "candidate_repairs": candidates,
        "selected_repair": selected,
        "rejected_repairs": rejected,
        "preserved_components": [
            name for name in
            ("research_contract", "admitted_world_evidence", "verified_literature")
        ] + ([f"question:{parent.get('question_id')}"] if parent.get("question_id") else []),
        "changed_components": [dimension, selected],
        "expected_resolution": (
            f"new WORLD evidence that settles {dimension}; prose cannot close this"
            if (record.requires_new_evidence if record else True)
            else "a clearer statement of the existing result"
        ),
        "early_kill_condition": (
            f"if the repaired design still cannot move {dimension} above its "
            "contract requirement, retire this direction instead of repeating it"
        ),
        "addresses_reviews": [str(demand.get("review_id"))] if demand.get("review_id") else [],
        "dimension": dimension,
        "epistemic": "GENERATED",
        "outcome": "open",
    }
    events = [make_event("DesignRevised", revision, action_type=REDESIGN,
                         frontier_target_id=action.frontier_target_id)]
    if theory_id and parent:
        events.append(make_event("ActionFailed", {
            "theory_id": theory_id, "reason": f"superseded_by_{revision['revision_id']}",
            "question_id": parent.get("question_id"), "revision_id": revision["revision_id"],
        }, action_type=REDESIGN))
    return CandidateResult(status="redesigned", events=events,
                           extras={"revision": revision, "selected_repair": selected})


def execute_project_pivot(env: Any, action: ActionInstance) -> CandidateResult:
    """Retire a direction without losing what it actually established.

    WORLD evidence, the contract, live contradictions and failure lessons carry
    forward. The speculative chain that produced the dead direction does not.
    """
    from .restart import clean_restart_projection

    trigger = dict(action.extra.get("trigger") or {})
    reason = str(trigger.get("reason") or action.reason or "direction_not_worth_continuing")
    projection = clean_restart_projection(env.state, reason=reason)
    events = [
        make_event("LineageRetired", {
            "lineage_id": lineage, "reason": reason,
            "theory_ids": [row.get("id") for row in env.state.theories
                           if str(row.get("lineage_id") or "") == lineage],
        }, action_type=PROJECT_PIVOT)
        for lineage in list(env.state.active_lineages)
    ]
    events.append(make_event("ProjectPivoted", {
        "reason": reason, "trigger": trigger,
        "preserved_world_evidence": [row.get("evidence_id")
                                     for row in projection["world_evidence"]],
        "failure_lessons": projection["failure_lessons"],
        "root_question": projection["root_question"],
        "remaining_resources": projection["remaining_resources"],
    }, action_type=PROJECT_PIVOT, frontier_target_id=action.frontier_target_id))
    events.append(make_event("ArtifactAdded", projection, action_type=PROJECT_PIVOT))
    if env.workspace is not None:
        dest = Path(env.workspace)
        dest.mkdir(parents=True, exist_ok=True)
        dest = dest / "CLEAN_RESTART.json"
        dest.write_text(json.dumps(projection, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    # The frontier must not be left empty: a pivot restates the root question as
    # a fresh, contract-aligned question rather than inventing a new topic.
    contract_root = projection["root_question"] or env.state.goal
    if contract_root:
        events.append(make_event("QuestionCreated", {
            "id": f"Q-root-e{int(env.state.project_epoch) + 1}",
            "text": contract_root,
            "lineage_id": f"line-root-e{int(env.state.project_epoch) + 1}",
            "epistemic": "GENERATED",
            "root_link": contract_root,
            "restarted_from": "clean_restart_projection",
        }, action_type=PROJECT_PIVOT))
    return CandidateResult(status="pivoted", events=events,
                           extras={"clean_restart": projection, "reason": reason})


def maybe_gc(env: Any) -> None:
    if env.state.ticks and env.state.ticks % 20 == 0:
        env.harness, deprecated = gc_harness(env.harness, tick=env.state.ticks)
        for item in deprecated:
            if item.name in env.capabilities.items:
                env.capabilities.deprecate(item.name)


DEFAULT_EXECUTORS = {
    OBSERVE: execute_observe,
    ACQUIRE: execute_acquire,
    THEORIZE: execute_theorize,
    VERIFY: execute_verify,
    PROBE: execute_probe,
    ASK: execute_ask,
    SURVEY: execute_survey,
    REFLECT: execute_reflect,
    SYNTHESIZE: execute_synthesize,
    ARCHIVE: execute_archive,
    FORK_LINEAGE: execute_fork,
    REVIEW: execute_review,
    REDESIGN: execute_redesign,
    PROJECT_PIVOT: execute_project_pivot,
}
