"""Trusted StateReducer: the only writer of canonical ScientificState."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from .events import EventLog, ScientificEvent
from .frontier import debt_from_state, frontier_from_state, graph_from_state
from .contract import ResearchContract, alignment_of_question, contract_from_state
from .kernel import refuse_generated_promotion
from .progress import update_metrics
from .quality import (
    ReviewRecord,
    compute_quality,
    normalize_review,
    resolution_admissible,
)
from .resources import compute_resources
from .state import ScientificState, refresh_research_views


def state_digest(state: ScientificState) -> str:
    raw = json.dumps(state.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def reduce_event(
    state: ScientificState,
    event: ScientificEvent,
    *,
    action: Any = None,
) -> ScientificState:
    current = ScientificState.from_dict(state.to_dict())
    payload = dict(event.payload or {})
    kind = event.event_type
    current.event_seq = max(current.event_seq, int(event.seq or 0))

    if kind == "GoalSet":
        current.goal = str(payload.get("goal") or current.goal)
    elif kind == "QuestionCreated":
        qid = str(payload.get("id") or payload.get("question_id") or "")
        if qid and not any(row.get("id") == qid for row in current.open_questions):
            current.add_question(
                question_id=qid,
                text=str(payload.get("text") or ""),
                required_observable=str(payload.get("required_observable") or ""),
                required_capability=str(payload.get("required_capability") or ""),
                lineage_id=str(payload.get("lineage_id") or ""),
                epistemic=str(payload.get("epistemic") or "GENERATED"),
            )
        gap = str(payload.get("required_capability") or "")
        if gap and gap not in current.available_capabilities:
            current.note_missing(gap)
    elif kind == "QuestionResolved":
        current.resolve_question(
            str(payload.get("id") or payload.get("question_id") or ""),
            evidence_id=str(payload.get("evidence_id") or ""),
            partial=False,
        )
    elif kind == "QuestionPartiallyResolved":
        current.resolve_question(
            str(payload.get("id") or payload.get("question_id") or ""),
            evidence_id=str(payload.get("evidence_id") or ""),
            partial=True,
        )
    elif kind == "QuestionBlocked":
        current.block_question(
            str(payload.get("id") or payload.get("question_id") or ""),
            reason=str(payload.get("reason") or ""),
        )
    elif kind == "TheoryCreated":
        row = dict(payload)
        row.setdefault("epistemic", "GENERATED")
        if refuse_generated_promotion(row):
            row["epistemic"] = "GENERATED"
        tid = str(row.get("id") or row.get("text") or "")
        if tid and not any(
            str(item.get("id") or item.get("text") or "") == tid for item in current.theories
        ):
            current.theories.append(row)
        for item in row.get("competing") or []:
            text = str(item)
            if text and text not in current.competing_explanations:
                current.competing_explanations.append(text)
    elif kind == "TheoryWeakened":
        _touch_theory(current, payload, status="weakened")
    elif kind == "TheorySupported":
        _touch_theory(current, payload, status="supported")
    elif kind == "TheoryContradicted":
        _touch_theory(current, payload, status="contradicted")
    elif kind == "EvidenceAdded":
        row = dict(payload)
        row.setdefault("scientific_event_id", event.event_id)
        if refuse_generated_promotion(row) and str(row.get("epistemic") or "") == "WORLD":
            row["epistemic"] = "GENERATED"
            row["promotion_refused"] = refuse_generated_promotion(row)
        eid = str(row.get("evidence_id") or "")
        existing = next(
            (
                item
                for item in current.evidence_records
                if eid and str(item.get("evidence_id") or "") == eid
            ),
            None,
        )
        if existing is not None:
            same_identity = all(row.get(k) == existing.get(k) for k in
                                ("world_id", "world_digest", "experiment_digest"))
            admitted_update = (row.get("epistemic") == "WORLD" and row.get("attested")
                               and row.get("promotion_ok") and not refuse_generated_promotion(row))
            if admitted_update and same_identity and (row.get("verify_count") is not None or row.get("verify_kind")):
                existing.update(
                    {
                        key: row[key]
                        for key in (
                            "verify_count",
                            "verify_kind",
                            "verified_by",
                            "world_compatible",
                            "replay_ok",
                            "reproduction_ok", "identity_ok", "executable_ok", "claim_consistent",
                            "transfer_ok", "transfer_evidence_id", "mechanism_validated",
                            "host_record", "measured_cost",
                        )
                        if key in row
                    }
                )
                existing["verification_event_id"] = event.event_id
            # do not duplicate the same EvidenceID
        else:
            current.evidence_records.append(row)
        if eid and eid not in current.archive_ids:
            current.archive_ids.append(eid)
    elif kind == "EvidenceRejected":
        current.rejected_ideas.append(dict(payload))
    elif kind == "WorldCreated":
        row = dict(payload)
        wid = str(row.get("id") or row.get("world_id") or "")
        if wid:
            current.world_id = wid
            if not any(
                str(item.get("id") or item.get("world_id") or "") == wid
                for item in current.world_versions
            ):
                current.world_versions.append(row)
        obs = str(row.get("observables") or "")
        if obs and obs in current.missing_capabilities:
            current.missing_capabilities.remove(obs)
    elif kind == "WorldAttested":
        wid = str(payload.get("id") or payload.get("world_id") or "")
        for item in current.world_versions:
            if str(item.get("id") or item.get("world_id") or "") == wid:
                item["attested"] = True
                item["digest"] = payload.get("digest") or item.get("digest")
                item["world_evidence_id"] = payload.get("world_evidence_id") or item.get(
                    "world_evidence_id"
                )
        if wid:
            current.world_id = wid
        for row in list(current.blocked_questions):
            current.reopen_question(str(row.get("id") or ""))
    elif kind == "WorldDeprecated":
        wid = str(payload.get("id") or payload.get("world_id") or "")
        for item in current.world_versions:
            if str(item.get("id") or item.get("world_id") or "") == wid:
                item["deprecated"] = True
    elif kind == "CapabilityProposed":
        name = str(payload.get("name") or "")
        if name and name not in current.missing_capabilities and name not in current.available_capabilities:
            current.note_missing(name)
    elif kind == "CapabilityValidated":
        name = str(payload.get("name") or "")
        if name:
            current.note_available(name)
    elif kind == "CapabilityTrusted":
        name = str(payload.get("name") or "")
        if name:
            current.note_available(name)
    elif kind == "CapabilityRevoked":
        name = str(payload.get("name") or "")
        if name in current.available_capabilities:
            current.available_capabilities.remove(name)
        current.note_missing(name)
    elif kind == "CapabilityDeprecated":
        name = str(payload.get("name") or "")
        if name in current.available_capabilities:
            current.available_capabilities.remove(name)
    elif kind == "HarnessAdmitted":
        current.harness_version = str(payload.get("harness_version") or current.harness_version)
        cap = str(payload.get("capability") or "")
        if cap:
            current.note_available(cap)
    elif kind == "HarnessPatchProposed":
        pass
    elif kind == "ActionFailed":
        current.failed_designs.append(dict(payload, action_type=event.action_type or payload.get("action_type", "")))
    elif kind == "ActionBlocked":
        if payload.get("theory_id"):
            failure = dict(payload, action_type=event.action_type or payload.get("action_type", ""))
            if failure not in current.failed_designs:
                current.failed_designs.append(failure)
        qid = str(payload.get("question_id") or payload.get("target") or "")
        if qid and any(row.get("id") == qid for row in current.open_questions):
            current.block_question(qid, reason=str(payload.get("reason") or ""))
        elif payload.get("gap"):
            current.note_missing(str(payload.get("gap")))
    elif kind == "ContradictionDetected":
        row = dict(payload)
        if row not in current.contradictions:
            current.contradictions.append(row)
    elif kind == "LineageForked":
        for lid in payload.get("lineages") or []:
            text = str(lid)
            if text and text not in current.active_lineages:
                current.active_lineages.append(text)
    elif kind == "LineageMerged":
        for lid in payload.get("retired") or []:
            text = str(lid)
            if text in current.active_lineages and len(current.active_lineages) > 1:
                current.active_lineages.remove(text)
    elif kind == "FrontierChanged":
        current.frontier = dict(payload.get("frontier") or payload)
        current.metrics["last_synthesis_events"] = int(current.metrics.get("meaningful_events") or 0)
        current.metrics["meaningful_events"] = int(current.metrics.get("meaningful_events") or 0) + 1
    elif kind == "DebtUpdated":
        merged = dict(current.debt)
        merged.update({str(k): int(v) for k, v in dict(payload.get("debt") or payload).items()})
        current.debt = merged
    elif kind == "ContractSet":
        # A project gets exactly one root question. Replacing it is a different
        # project and must be a new contract, never a quiet in-place rewrite.
        contract = ResearchContract.from_dict(payload)
        existing = ResearchContract.from_dict(current.contract)
        if existing.is_set and existing.root_question != contract.root_question:
            current.artifacts.append({
                "kind": "contract_change_refused",
                "reason": "root_question_is_immutable_within_a_project",
                "existing_root_question": existing.root_question,
                "rejected_root_question": contract.root_question,
            })
        else:
            current.contract = contract.to_dict()
            if not current.goal:
                current.goal = contract.root_question
    elif kind == "ContractAmended":
        existing = ResearchContract.from_dict(current.contract)
        if existing.is_set:
            current.contract = existing.amended(payload).to_dict()
    elif kind == "ReviewRecorded":
        row = normalize_review(payload, tick=int(current.ticks))
        row["project_epoch"] = int(current.project_epoch)
        if not any(str(item.get("review_id") or "") == row["review_id"] for item in current.reviews):
            current.reviews.append(row)
    elif kind == "ReviewResolved":
        rid = str(payload.get("review_id") or "")
        target = next((item for item in current.reviews
                       if str(item.get("review_id") or "") == rid), None)
        if target is not None and str(target.get("status") or "") != "resolved":
            ok, why = resolution_admissible(
                target,
                resolution_kind=str(payload.get("resolution_kind") or ""),
                evidence_id=str(payload.get("resolution_evidence_id") or ""),
                evidence_rows=current.evidence_records,
            )
            if ok:
                target.update(
                    status="resolved",
                    resolution_kind=str(payload.get("resolution_kind") or ""),
                    resolution_evidence_id=str(payload.get("resolution_evidence_id") or ""),
                    resolved_at_tick=int(current.ticks),
                )
            else:
                # Refusing prose repair is itself state: it is how the system
                # learns that it wasted a turn writing instead of measuring.
                target["repair_refusals"] = int(target.get("repair_refusals") or 0) + 1
                target["last_repair_refusal"] = why
                current.metrics["caveat_only_repair_refused"] = int(
                    current.metrics.get("caveat_only_repair_refused") or 0) + 1
    elif kind == "ReviewRepairRefused":
        current.metrics["caveat_only_repair_refused"] = int(
            current.metrics.get("caveat_only_repair_refused") or 0) + 1
    elif kind == "DesignRevised":
        row = dict(payload)
        row.setdefault("epistemic", "GENERATED")
        row.setdefault("project_epoch", int(current.project_epoch))
        row.setdefault("revised_at_tick", int(current.ticks))
        if not any(str(item.get("revision_id") or "") == str(row.get("revision_id") or "")
                   for item in current.design_revisions if row.get("revision_id")):
            current.design_revisions.append(row)
        for rid in row.get("addresses_reviews") or []:
            for item in current.reviews:
                if str(item.get("review_id") or "") == str(rid) and item.get("status") == "open":
                    item["status"] = "repairing"
                    item["repairing_revision_id"] = str(row.get("revision_id") or "")
    elif kind == "LineageRetired":
        row = dict(payload)
        row.setdefault("retired_at_tick", int(current.ticks))
        row.setdefault("project_epoch", int(current.project_epoch))
        lid = str(row.get("lineage_id") or "")
        if lid and lid in current.active_lineages:
            current.active_lineages.remove(lid)
        if not any(str(item.get("lineage_id") or "") == lid for item in current.retired_lineages):
            current.retired_lineages.append(row)
        for theory in current.theories:
            if str(theory.get("lineage_id") or "") == lid or str(theory.get("id") or "") in set(
                    str(x) for x in row.get("theory_ids") or []):
                theory["status"] = "retired"
                theory["retired_reason"] = str(row.get("reason") or "")
    elif kind == "ProjectPivoted":
        # WORLD evidence, the contract and the failure record survive a pivot.
        # Speculative narrative does not: that is the whole point.
        current.project_epoch = int(current.project_epoch) + 1
        row = dict(payload, project_epoch=current.project_epoch,
                   pivoted_at_tick=int(current.ticks))
        for theory in current.theories:
            if theory.get("status") not in {"retired"}:
                theory["status"] = "retired"
                theory["retired_reason"] = str(payload.get("reason") or "project_pivot")
                theory["retired_epoch"] = int(current.project_epoch)
        for lineage in list(current.active_lineages):
            if not any(str(item.get("lineage_id") or "") == lineage
                       for item in current.retired_lineages):
                current.retired_lineages.append({
                    "lineage_id": lineage, "reason": str(payload.get("reason") or "project_pivot"),
                    "project_epoch": current.project_epoch, "retired_at_tick": int(current.ticks),
                })
        current.active_lineages = []
        for question in list(current.open_questions):
            current.block_question(str(question.get("id") or ""), reason="retired_by_project_pivot")
        for review in current.reviews:
            if review.get("status") == "open" and review.get("repair_type") == "project_pivot":
                review["status"] = "resolved"
                review["resolution_kind"] = "design_repair"
                review["resolved_at_tick"] = int(current.ticks)
        current.artifacts.append({"kind": "project_pivot", **row})
        current.decision_journal.append({
            "kind": "project_pivot", "tick": int(current.ticks),
            "project_epoch": current.project_epoch,
            "reason": str(payload.get("reason") or ""),
            "preserved": "world_evidence_contract_failure_lessons",
        })
    elif kind == "DecisionRecorded":
        row = dict(payload)
        row.setdefault("tick", int(current.ticks))
        row.setdefault("project_epoch", int(current.project_epoch))
        current.decision_journal.append(row)
        if len(current.decision_journal) > 40:
            current.decision_journal = current.decision_journal[-40:]
    elif kind == "ArtifactAdded":
        row = dict(payload)
        if row not in current.artifacts:
            current.artifacts.append(row)
        if row.get("kind") == "action_attempt":
            # Watermarks for the value preconditions: what had been recorded the
            # last time a reflecting or archiving action ran.
            if str(row.get("action_type") or "") == "REFLECT":
                current.metrics["failures_at_last_reflect"] = len(current.failed_designs)
            elif str(row.get("action_type") or "") == "ARCHIVE":
                current.metrics["closed_at_last_archive"] = (
                    len(current.resolved_questions) + len(current.failed_designs))
    elif kind == "TickAdvanced":
        current.ticks = int(current.ticks) + 1
        if payload.get("meaningful"):
            current.last_progress_tick = current.ticks
            current.metrics["meaningful_events"] = int(current.metrics.get("meaningful_events") or 0) + 1
        if payload.get("research_meaningful"):
            current.last_research_progress_tick = current.ticks
            current.metrics["research_progress_events"] = int(
                current.metrics.get("research_progress_events") or 0) + 1
        for name in ("central_question_progress", "decision_relevant_evidence",
                     "quality_gap_reduction", "critical_review_resolution",
                     "peripheral_question_progress", "caveat_only_repair",
                     "same_failure_repetition", "low_value_activity",
                     "successful_reorientation", "replication_progress",
                     "quality_dimension_progress", "objection_discovery",
                     "failure_information"):
            value = int(payload.get(name) or 0)
            if value:
                current.metrics[name] = int(current.metrics.get(name) or 0) + value
        if payload.get("goal_drift"):
            current.metrics["goal_drift"] = int(current.metrics.get("goal_drift") or 0) + 1
        current.debt = debt_from_state(current)
        current.frontier = frontier_from_state(current)
        current.graph = graph_from_state(current)
        update_metrics(
            current,
            action=action,
            action_type=str(payload.get("action_type") or event.action_type or ""),
            scripted=bool(payload.get("scripted")),
            unlock=bool(payload.get("unlock")),
            integrity_gap=str(payload.get("integrity_gap") or ""),
            archive_hit=bool(payload.get("archive_hit")),
            harness_general=bool(payload.get("harness_general")),
            regression=bool(payload.get("regression")),
        )
        refresh_project_views(current)
        return current
    refresh_research_views(current)
    current.debt = debt_from_state(current)
    current.frontier = frontier_from_state(current)
    current.graph = graph_from_state(current)
    refresh_project_views(current)
    return current


def refresh_project_views(state: ScientificState) -> None:
    """Recompute contract-level projections after every admitted event.

    Quality and resources are derived, not written: no worker and no reviewer
    can assert that this project is good enough or that it has budget left.
    """
    state.quality = compute_quality(state)
    state.resources = compute_resources(state)
    contract = contract_from_state(state)
    if contract.is_set:
        questions = (
            list(state.open_questions) + list(state.resolved_questions)
            + list(state.partial_questions) + list(state.blocked_questions)
        )
        drifted = []
        for question in questions:
            alignment = alignment_of_question(contract, question, known=questions)
            question["root_alignment"] = alignment.status
            if alignment.drifted:
                drifted.append(str(question.get("id") or ""))
        state.debt = dict(state.debt or {})
        state.debt["goal_drift_debt"] = len(drifted)
        state.debt.update({
            key: value for key, value in
            compute_quality(state)["review_debt"].items()
        })
        state.debt["quality_gap"] = int(state.quality.get("quality_gap_size") or 0)
        state.metrics["drifted_questions"] = drifted


def apply_events(
    state: ScientificState,
    events: Iterable[ScientificEvent],
    *,
    log: EventLog | None = None,
    action: Any = None,
    tick: int | None = None,
) -> ScientificState:
    current = ScientificState.from_dict(state.to_dict())
    now = int(current.ticks if tick is None else tick)
    for event in events:
        if log is not None:
            event = log.append(event, tick=now)
        current = reduce_event(current, event, action=action)
    current.debt = debt_from_state(current)
    current.frontier = frontier_from_state(current)
    current.graph = graph_from_state(current)
    # Project views are derived from the state these recomputations just
    # rebuilt, so they must be refreshed last or their debt keys are erased.
    refresh_project_views(current)
    return current


def rebuild_state(log: EventLog) -> ScientificState:
    state = ScientificState.from_dict(log.baseline)
    for event in log.events:
        state = reduce_event(state, event)
    state.debt = debt_from_state(state)
    state.frontier = frontier_from_state(state)
    state.graph = graph_from_state(state)
    refresh_project_views(state)
    return state


def _touch_theory(state: ScientificState, payload: Mapping[str, Any], *, status: str) -> None:
    tid = str(payload.get("id") or payload.get("theory_id") or payload.get("text") or "")
    for row in state.theories:
        if str(row.get("id") or row.get("text") or "") == tid:
            row["status"] = status
            if payload.get("evidence_id"):
                row.setdefault("evidence_ids", [])
                if isinstance(row["evidence_ids"], list):
                    eid = str(payload.get("evidence_id"))
                    if eid not in row["evidence_ids"]:
                        row["evidence_ids"].append(eid)
            return
    row = dict(payload)
    row["status"] = status
    row.setdefault("epistemic", "GENERATED")
    state.theories.append(row)
