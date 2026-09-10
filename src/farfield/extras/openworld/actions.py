"""Action / Affordance registry. Actions are choices; idea kinds are objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .state import ScientificState


SURVEY = "SURVEY"
ASK = "ASK"
OBSERVE = "OBSERVE"
ACQUIRE = "ACQUIRE"
THEORIZE = "THEORIZE"
PROBE = "PROBE"
VERIFY = "VERIFY"
VERIFY_REPLICATION = "VERIFY_REPLICATION"
VERIFY_MEASUREMENT = "VERIFY_MEASUREMENT"
VERIFY_ALTERNATIVE_EXPLANATION = "VERIFY_ALTERNATIVE_EXPLANATION"
VERIFY_WORLD_COMPATIBILITY = "VERIFY_WORLD_COMPATIBILITY"
VERIFY_NEGATIVE_RESULT = "VERIFY_NEGATIVE_RESULT"
VERIFY_HIGH_IMPACT_CLAIM = "VERIFY_HIGH_IMPACT_CLAIM"
REFLECT = "REFLECT"
SYNTHESIZE = "SYNTHESIZE"
ARCHIVE = "ARCHIVE"
FORK_LINEAGE = "FORK_LINEAGE"
EVOLVE_HARNESS = "EVOLVE_HARNESS"
# Project-level research control. SURVEY..SYNTHESIZE ask "what do we do with
# this question?". These three ask "is this project any good, and if not, what
# has to change?" — which is the decision a long-horizon agent actually faces.
REVIEW = "REVIEW"
REDESIGN = "REDESIGN"
PROJECT_PIVOT = "PROJECT_PIVOT"

ACTION_TYPES = (
    SURVEY,
    ASK,
    OBSERVE,
    ACQUIRE,
    THEORIZE,
    PROBE,
    VERIFY,
    REFLECT,
    SYNTHESIZE,
    ARCHIVE,
    FORK_LINEAGE,
    EVOLVE_HARNESS,
    REVIEW,
    REDESIGN,
    PROJECT_PIVOT,
)


@dataclass(frozen=True)
class ActionSpec:
    action_type: str
    preconditions: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    reads: tuple[str, ...]
    possible_outputs: tuple[str, ...]
    executor: str
    validator: str
    estimated_cost: float
    risk: str
    state_effect: str
    evidence_effect: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "preconditions": list(self.preconditions),
            "required_capabilities": list(self.required_capabilities),
            "reads": list(self.reads),
            "possible_outputs": list(self.possible_outputs),
            "executor": self.executor,
            "validator": self.validator,
            "estimated_cost": self.estimated_cost,
            "risk": self.risk,
            "state_effect": self.state_effect,
            "evidence_effect": self.evidence_effect,
        }


@dataclass(frozen=True)
class ActionInstance:
    spec: ActionSpec
    target: str = ""
    reason: str = ""
    lineage_id: str = ""
    frontier_target_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def action_type(self) -> str:
        return self.spec.action_type

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.spec.to_dict(),
            "target": self.target,
            "reason": self.reason,
            "lineage_id": self.lineage_id,
            "frontier_target_id": self.frontier_target_id,
            "extra": dict(self.extra),
        }


SPECS: dict[str, ActionSpec] = {
    SURVEY: ActionSpec(
        SURVEY,
        preconditions=("open_question_or_goal",),
        required_capabilities=(),
        reads=("scientific_archive", "literature"),
        possible_outputs=("citations", "gaps"),
        executor="survey_executor",
        validator="verify_papers",
        estimated_cost=0.4,
        risk="low",
        state_effect="record_citations",
        evidence_effect="none",
    ),
    ASK: ActionSpec(
        ASK,
        preconditions=("research_goal",),
        required_capabilities=(),
        reads=("working_memory",),
        possible_outputs=("question",),
        executor="ask_executor",
        validator="question_schema",
        estimated_cost=0.2,
        risk="low",
        state_effect="add_open_question",
        evidence_effect="none",
    ),
    OBSERVE: ActionSpec(
        OBSERVE,
        preconditions=("open_question", "observable_present"),
        required_capabilities=(),
        reads=("world_version", "capability_registry"),
        possible_outputs=("QuestionEvidence",),
        executor="question_executor",
        validator="observation_attestation",
        estimated_cost=0.5,
        risk="medium",
        state_effect="maybe_resolve_question",
        evidence_effect="question_evidence_if_attested",
    ),
    ACQUIRE: ActionSpec(
        ACQUIRE,
        preconditions=("capability_or_world_gap",),
        required_capabilities=(),
        reads=("missing_capabilities", "world_lineage"),
        possible_outputs=("AcquisitionEvidence", "world_version"),
        executor="acquire_executor",
        validator="world_attestation",
        estimated_cost=0.8,
        risk="medium",
        state_effect="new_world_version",
        evidence_effect="acquisition_evidence",
    ),
    THEORIZE: ActionSpec(
        THEORIZE,
        preconditions=("unexplained_phenomenon",),
        required_capabilities=(),
        reads=("open_questions", "evidence_records"),
        possible_outputs=("theory", "predictions"),
        executor="theory_discriminator",
        validator="theory_schema",
        estimated_cost=0.3,
        risk="low",
        state_effect="add_generated_theory",
        evidence_effect="none",
    ),
    PROBE: ActionSpec(
        PROBE,
        preconditions=("causal_handle", "valid_freeze", "measure"),
        required_capabilities=(),
        reads=("world_version", "harness_probe_executor"),
        possible_outputs=("ProbeEvidence",),
        executor="probe_executor",
        validator="fair_two_arm",
        estimated_cost=1.0,
        risk="high",
        state_effect="record_probe",
        evidence_effect="probe_evidence_if_world",
    ),
    VERIFY: ActionSpec(
        VERIFY,
        preconditions=("existing_evidence",),
        required_capabilities=(),
        reads=("evidence_id", "world_id"),
        possible_outputs=("confirmation_or_gap",),
        executor="verify_executor",
        validator="host_confirmation",
        estimated_cost=0.9,
        risk="medium",
        state_effect="confirmation_gaps",
        evidence_effect="same_evidence_id_only",
    ),
    REFLECT: ActionSpec(
        REFLECT,
        preconditions=("recent_events",),
        required_capabilities=(),
        reads=("failure_archive", "working_memory"),
        possible_outputs=("pathology_or_scientific_note",),
        executor="reflect_executor",
        validator="classify_failure",
        estimated_cost=0.2,
        risk="low",
        state_effect="record_pathology_or_anomaly",
        evidence_effect="none",
    ),
    SYNTHESIZE: ActionSpec(
        SYNTHESIZE,
        preconditions=("evidence_or_theory",),
        required_capabilities=(),
        reads=("scientific_archive",),
        possible_outputs=("brief",),
        executor="synthesize_executor",
        validator="attested_writeup_lock",
        estimated_cost=0.6,
        risk="low",
        state_effect="draft_only",
        evidence_effect="none",
    ),
    ARCHIVE: ActionSpec(
        ARCHIVE,
        preconditions=("closed_or_negative_result",),
        required_capabilities=(),
        reads=("working_memory",),
        possible_outputs=("archive_row",),
        executor="archive_executor",
        validator="epistemic_label",
        estimated_cost=0.1,
        risk="low",
        state_effect="move_to_archive",
        evidence_effect="none",
    ),
    FORK_LINEAGE: ActionSpec(
        FORK_LINEAGE,
        preconditions=("stagnation_or_diversity",),
        required_capabilities=(),
        reads=("scientific_state", "harness_version"),
        possible_outputs=("branches",),
        executor="fork_executor",
        validator="generated_not_merged_as_world",
        estimated_cost=0.7,
        risk="medium",
        state_effect="open_branches",
        evidence_effect="verified_only_merge",
    ),
    EVOLVE_HARNESS: ActionSpec(
        EVOLVE_HARNESS,
        preconditions=("reproducible_harness_pathology",),
        required_capabilities=(),
        reads=("harness_archive", "failure_archive"),
        possible_outputs=("harness_version", "capability"),
        executor="harness_evolver",
        validator="credit_gate",
        estimated_cost=0.9,
        risk="high",
        state_effect="harness_version_if_admitted",
        evidence_effect="none",
    ),
    REVIEW: ActionSpec(
        REVIEW,
        preconditions=("reviewable_claim_or_design",),
        required_capabilities=(),
        reads=("evidence_records", "quality_state", "research_contract"),
        possible_outputs=("review_records",),
        executor="review_executor",
        validator="structured_objection_schema",
        estimated_cost=0.3,
        risk="low",
        state_effect="record_review_debt",
        # A reviewer's agreement is not measurement. Review changes the plan; it
        # never changes what the world was observed to do.
        evidence_effect="none",
    ),
    REDESIGN: ActionSpec(
        REDESIGN,
        preconditions=("unresolved_objection_or_failed_design",),
        required_capabilities=(),
        reads=("reviews", "failed_designs", "quality_state"),
        possible_outputs=("design_revision",),
        executor="redesign_executor",
        validator="revision_addresses_root_cause",
        estimated_cost=0.4,
        risk="medium",
        state_effect="open_design_revision",
        evidence_effect="none",
    ),
    PROJECT_PIVOT: ActionSpec(
        PROJECT_PIVOT,
        preconditions=("direction_not_worth_continuing", "budget_headroom"),
        required_capabilities=(),
        reads=("research_contract", "quality_state", "resources", "reviews"),
        possible_outputs=("clean_restart_projection",),
        executor="pivot_executor",
        validator="preserves_world_evidence_and_contract",
        estimated_cost=0.5,
        risk="high",
        state_effect="retire_lineage_and_restart_from_contract",
        evidence_effect="none",
    ),
}


def spec_of(action_type: str) -> ActionSpec:
    return SPECS[str(action_type)]


def _has_capability(names: Iterable[str], needed: str) -> bool:
    wanted = str(needed or "").strip()
    if not wanted:
        return True
    have = {str(item).strip() for item in names}
    return wanted in have


def _contrast_observations(state: Any, question: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Contrasts a live hypothesis named that the bound world can actually split.

    Read from the hypothesis's own `experiment_proposal`: the observable it
    predicts on, and the contrast lever the compiler bound it to. Both must be
    registered by the world, so this cannot invent a measurement — it only
    reaches one the world already offers.
    """
    qid = str(question.get("id") or "")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for theory in getattr(state, "theories", []) or []:
        if theory.get("role") == "competing_explanation":
            continue
        if str(theory.get("question_id") or "") != qid:
            continue
        proposal = dict(theory.get("experiment_proposal") or {})
        if not proposal:
            proposal = dict((dict(theory.get("card") or {}).get("research_metadata")
                             or {}).get("experiment_proposal") or {})
        outcomes = dict(proposal.get("expected_outcomes") or {})
        observables = [str(dict(row).get("observable") or "")
                       for row in outcomes.values() if isinstance(row, Mapping)]
        lever = str(dict(theory.get("card") or {}).get("lever")
                    or proposal.get("lever") or theory.get("lever") or "")
        for observable in observables:
            key = (lever, observable)
            if not lever or not observable or key in seen:
                continue
            seen.add(key)
            rows.append({"contrast": lever, "observable": observable,
                         "theory_id": str(theory.get("id") or "")})
    return rows


def _observable_present(state: ScientificState, question: Mapping[str, Any]) -> bool:
    required = str(question.get("required_observable") or "").strip()
    if required:
        blob = " ".join(
            str(row.get("observables") or row.get("id") or "")
            for row in state.world_versions
        )
        if required in blob or required in " ".join(state.available_capabilities):
            return True
        return False
    cap = str(question.get("required_capability") or "").strip()
    if cap:
        return _has_capability(state.available_capabilities, cap)
    return bool(state.world_id)


def _has_theory_for(state: ScientificState, question_id: str) -> bool:
    return any(
        str(row.get("question_id") or row.get("target") or "") == question_id
        or str(row.get("id") or "") == question_id
        for row in state.theories
    )


def sole_support(state: ScientificState, row: Mapping[str, Any]) -> bool:
    """Is this row the only admitted evidence its hypothesis rests on?

    The old test read ``high_impact`` and ``source_count`` from the evidence
    row. Nothing in the runtime wrote either field, so a whole class of
    verification debt — a consequential claim standing on one measurement —
    could never be raised. Whether a row stands alone is a fact about the state
    and is computed here rather than waited for.
    """
    tid = str(row.get("theory_id") or "")
    if not tid:
        return False
    supporting = {
        str(item.get("evidence_id") or "")
        for item in state.evidence_records
        if str(item.get("theory_id") or "") == tid
        and str(item.get("epistemic") or "") == "WORLD"
        and item.get("promotion_ok")
        and (item.get("outcome") or item.get("verdict")) == "supports"
    }
    return supporting == {str(row.get("evidence_id") or "")}


def _needs_verify(state: ScientificState) -> bool:
    if state.contradictions:
        return True
    seen: set[str] = set()
    for row in state.evidence_records:
        eid = str(row.get("evidence_id") or "")
        if not eid or eid in seen:
            continue
        seen.add(eid)
        if str(row.get("epistemic") or "") != "WORLD":
            continue
        if int(row.get("verify_count") or 0) < 1:
            return True
        if sole_support(state, row) and not row.get("replication_of"):
            return True
    return False


def _verify_kind(state: ScientificState) -> str:
    if state.contradictions:
        return VERIFY_ALTERNATIVE_EXPLANATION
    for row in state.evidence_records:
        if sole_support(state, row) and not row.get("replication_of"):
            return VERIFY_HIGH_IMPACT_CLAIM
        if str(row.get("outcome") or row.get("verdict") or "") in {"weakens", "negative"}:
            return VERIFY_NEGATIVE_RESULT
    return VERIFY_REPLICATION


def _causal_ready(state: ScientificState, extra: Mapping[str, Any] | None = None) -> bool:
    row = dict(extra or {})
    # A handle, a measure and a freeze. There was a second path here reading
    # ``causal_identification_ready``, which nothing ever set.
    return bool(row.get("causal_handle") and row.get("measure")
                and (row.get("freeze") or state.world_id))


def eligible_actions(
    state: ScientificState,
    *,
    capabilities: Iterable[str] = (),
    pathology_ready: bool = False,
    stagnation: bool = False,
    probe_ready: Mapping[str, Any] | None = None,
    workers_connected: bool = False,
    strategic_stagnation: Any = None,
) -> list[ActionInstance]:
    """Deterministic eligibility. Not a pipeline stage list."""
    caps = tuple(str(item) for item in capabilities) + tuple(state.available_capabilities)
    found: list[ActionInstance] = []
    goal_id = "goal:G0" if state.goal else ""

    if (state.goal or state.open_questions) and (
        state.ticks == 0 or not state.archive_ids
    ):
        found.append(
            ActionInstance(
                SPECS[SURVEY],
                target=state.goal,
                reason="goal_or_question",
                frontier_target_id=goal_id,
            )
        )
    if state.goal and not state.open_questions and not state.resolved_questions and not state.blocked_questions:
        found.append(
            ActionInstance(
                SPECS[ASK],
                target=state.goal,
                reason="research_goal",
                frontier_target_id=goal_id,
            )
        )

    for question in list(state.open_questions) + list(state.blocked_questions):
        qid = str(question.get("id") or "")
        lineage = str(question.get("lineage_id") or "")
        required_cap = str(question.get("required_capability") or "").strip()
        if _observable_present(state, question) and (
            not required_cap or _has_capability(caps, required_cap)
        ):
            found.append(
                ActionInstance(
                    SPECS[OBSERVE],
                    target=qid,
                    reason="observable_present",
                    lineage_id=lineage,
                    frontier_target_id=qid,
                    extra={"question": dict(question)},
                )
            )
            # A hypothesis may name an observational contrast the bound world
            # already registers. Without this the contrast is unreachable: the
            # generic OBSERVE returns dataset descriptives, and PROBE refuses a
            # question card because a stratum comparison is not an intervention.
            # A live run produced two well-formed contrasts and could execute
            # neither, so the whole observational family of questions — most of
            # empirical software engineering — dead-ended.
            for row in _contrast_observations(state, question):
                found.append(
                    ActionInstance(
                        SPECS[OBSERVE],
                        target=qid,
                        reason="named_contrast_on_the_bound_world",
                        lineage_id=lineage,
                        frontier_target_id=qid,
                        extra={"question": dict(question), **row},
                    )
                )
        else:
            gap = required_cap or str(question.get("required_observable") or "observable")
            found.append(
                ActionInstance(
                    SPECS[ACQUIRE],
                    target=qid,
                    reason="blocked_on_capability_or_world",
                    lineage_id=lineage,
                    frontier_target_id=qid,
                    extra={"gap": gap, "question": dict(question)},
                )
            )
        if not _has_theory_for(state, qid):
            found.append(
                ActionInstance(
                    SPECS[THEORIZE],
                    target=qid,
                    reason="unexplained_question",
                    lineage_id=lineage,
                    frontier_target_id=qid,
                )
            )

    for question in state.resolved_questions:
        qid = str(question.get("id") or "")
        if qid and not _has_theory_for(state, qid):
            found.append(
                ActionInstance(
                    SPECS[THEORIZE],
                    target=qid,
                    reason="discriminate_resolved_phenomenon",
                    lineage_id=str(question.get("lineage_id") or ""),
                    frontier_target_id=qid,
                )
            )

    if state.missing_capabilities and not any(item.action_type == ACQUIRE for item in found):
        found.append(
            ActionInstance(
                SPECS[ACQUIRE],
                target=state.missing_capabilities[0],
                reason="capability_or_world_gap",
                frontier_target_id=state.open_questions[0]["id"] if state.open_questions else goal_id,
                extra={"gap": state.missing_capabilities[0]},
            )
        )

    if (state.open_questions or state.anomalies) and not any(
        item.action_type == THEORIZE for item in found
    ):
        found.append(
            ActionInstance(
                SPECS[THEORIZE],
                reason="unexplained_phenomenon",
                frontier_target_id=goal_id,
            )
        )

    if _causal_ready(state, probe_ready):
        found.append(
            ActionInstance(
                SPECS[PROBE],
                target=str((probe_ready or {}).get("hypothesis") or ""),
                reason="causal_handle_and_freeze",
                frontier_target_id=str((probe_ready or {}).get("question_id") or goal_id),
                extra=dict(probe_ready or {}),
            )
        )

    if _needs_verify(state):
        found.append(
            ActionInstance(
                SPECS[VERIFY],
                reason="existing_evidence",
                frontier_target_id=goal_id or (
                    str(state.evidence_records[-1].get("question_id") or "")
                    if state.evidence_records
                    else ""
                ),
                extra={"verify_kind": _verify_kind(state)},
            )
        )

    if state.ticks > 0:
        found.append(ActionInstance(SPECS[REFLECT], reason="recent_events"))

    last_synth = int((state.metrics or {}).get("last_synthesis_events") or 0)
    meaningful = int((state.metrics or {}).get("meaningful_events") or 0)
    if (state.evidence_records or state.theories) and (
        meaningful - last_synth >= 5 or state.contradictions or state.ticks == 1
    ):
        found.append(ActionInstance(SPECS[SYNTHESIZE], reason="evidence_or_theory"))

    if state.resolved_questions or state.failed_designs:
        found.append(ActionInstance(SPECS[ARCHIVE], reason="closed_or_negative_result"))

    if stagnation and len(state.active_lineages) < 4:
        from .executors import fork_candidates

        # A fork with nothing distinct to branch on is a wasted tick that then
        # blocks the next real fork. Only offer it when lanes exist.
        candidates = fork_candidates(state)
        # Diversifying is only worth a tick when the lanes are not already on
        # the menu. If every lane's next action is directly available, forking
        # renames work the controller can simply do.
        offered = {item.action_type for item in found}
        if len(candidates) >= 2 and not all(
                str(row.get("next_action") or "") in offered for row in candidates):
            found.append(
                ActionInstance(
                    SPECS[FORK_LINEAGE],
                    reason="stagnation_or_diversity",
                    extra={"fork_candidates": candidates},
                )
            )

    if pathology_ready:
        found.append(
            ActionInstance(
                SPECS[EVOLVE_HARNESS],
                reason="reproducible_harness_pathology",
            )
        )

    found.extend(project_actions(state, strategic_stagnation=strategic_stagnation))

    if workers_connected:
        found = worker_actions(state, found)
    # An action that provably cannot inform anything is not eligible. Spending a
    # tick to leave the state exactly as it was is a resource decision, and the
    # honest place to make it is here, before the action is ever offered.
    return [item for item in found if not information_precondition(state, item)]


def _open_reviews(state: ScientificState, severity: str = "") -> list[dict[str, Any]]:
    from .quality import open_reviews

    return open_reviews(state.reviews, severity=severity)


def _reviewable(state: ScientificState) -> bool:
    """Would a review actually say something that is not already recorded?

    Asked the weaker question — "is there anything reviewable?" — this returned
    true as soon as a hypothesis and a survey existed, and a live run spent a
    tick on a review that had no evidence to object to and returned
    ``no_new_objections``. The reviewer's own output is the only honest
    precondition, so it is computed and checked for something new.
    """
    from .executors import _structural_objections

    known = {str(row.get("review_id") or "") for row in state.reviews}
    return any(str(row.get("review_id") or "") not in known
               for row in _structural_objections(state))


def _redesign_demands(state: ScientificState) -> list[dict[str, Any]]:
    """Objections and quality gaps that a rerun of the same design cannot fix.

    A redesign needs a design. After a pivot the previous epoch's evidence still
    leaves quality dimensions short — correctly, that evidence is preserved —
    but there is nothing in the new epoch to revise, and the honest next step is
    to build a design, not to revise one that was retired.
    """
    from .quality import REDESIGN_REPAIRS

    epoch = int(state.project_epoch)
    live_designs = [row for row in state.theories
                    if row.get("status") != "retired"
                    and row.get("role") != "competing_explanation"]
    demands: list[dict[str, Any]] = []
    addressed = {
        str(rid)
        for revision in state.design_revisions
        if int(revision.get("project_epoch") or 0) == epoch
        for rid in revision.get("addresses_reviews") or []
    }
    for review in _open_reviews(state):
        repair = str(review.get("repair_type") or "")
        if repair not in REDESIGN_REPAIRS and repair != "stronger_baseline":
            continue
        if int(review.get("project_epoch") or 0) != epoch:
            continue  # an objection against a retired direction is history
        if str(review.get("review_id") or "") in addressed:
            continue
        demands.append({
            "kind": "review", "review_id": review.get("review_id"),
            "repair_type": repair, "dimension": review.get("dimension"),
            "objection": review.get("objection"), "theory_id": review.get("theory_id"),
            "question_id": review.get("question_id"), "severity": review.get("severity"),
        })
    dimensions = (state.quality or {}).get("dimensions") or {}
    for name, row in sorted(dimensions.items()):
        if not live_designs:
            break  # nothing to revise; the frontier owns this gap
        if "REDESIGN" not in (row.get("required_next_work") or []):
            continue
        if any(item.get("dimension") == name for item in demands):
            continue
        if any(str(revision.get("dimension") or "") == name
               and int(revision.get("project_epoch") or 0) == int(state.project_epoch)
               for revision in state.design_revisions):
            continue
        demands.append({
            "kind": "quality_gap", "dimension": name, "severity": "major",
            "repair_type": "experiment_redesign",
            "objection": "; ".join(row.get("blocking_reasons") or []) or f"{name}_below_contract",
        })
    return demands


def _pivot_trigger(state: ScientificState, *, strategic_stagnation: Any = None) -> dict[str, Any] | None:
    """When is the honest move to stop repairing and change direction?

    Not "the experiment failed" — that is REDESIGN. This is the case where even
    a successful next experiment would not make the project worth finishing:
    the direction carries an unrepairable objection, its redesigns are spent, or
    the whole hypothesis set has drifted off the contract's root question.
    """
    from .quality import PIVOT_REPAIRS
    from .resources import budget_phase

    epoch = int(state.project_epoch)
    # A direction cannot be abandoned before it has been tried. After a pivot the
    # fresh epoch has to do real work before it may be abandoned in turn,
    # otherwise the controller can pivot forever without researching anything.
    epoch_work = [row for row in state.artifacts
                  if row.get("kind") == "action_attempt"
                  and str(row.get("action_type") or "") in {"PROBE", "VERIFY", "OBSERVE"}
                  and int(row.get("project_epoch") or 0) == epoch]
    if epoch and not epoch_work:
        return None

    demanded = [r for r in _open_reviews(state)
                if str(r.get("repair_type") or "") in PIVOT_REPAIRS
                and int(r.get("project_epoch") or 0) == epoch]
    if demanded:
        return {"reason": "reviewer_demanded_project_pivot",
                "review_ids": [r.get("review_id") for r in demanded]}

    # Opening a new direction costs a full research arc. With the budget nearly
    # gone that is not courage, it is guaranteeing two unfinished projects.
    phase = budget_phase(state)
    if phase in {"closing", "exhausted"}:
        return None

    revisions = [r for r in state.design_revisions if int(r.get("project_epoch") or 0) == epoch]
    fatal = _open_reviews(state, severity="fatal")
    quality = state.quality or {}
    central = ((quality.get("dimensions") or {}).get("central_claim_support") or {})
    exhausted = len(revisions) >= 2 and all(
        str(r.get("outcome") or "open") != "resolved" for r in revisions)

    if fatal and exhausted:
        return {"reason": "fatal_objection_survived_the_available_redesigns",
                "review_ids": [r.get("review_id") for r in fatal],
                "revisions_tried": len(revisions)}
    if "PROJECT_PIVOT" in (central.get("required_next_work") or []):
        return {"reason": "no_active_hypothesis_still_serves_the_root_question",
                "blocking_reasons": list(central.get("blocking_reasons") or [])}
    if strategic_stagnation is not None and exhausted:
        reasons = list(getattr(strategic_stagnation, "reasons", ()) or [])
        return {"reason": "strategic_stagnation_after_exhausted_redesign", "detail": reasons}
    return None


def _action_variant(action: ActionInstance) -> str:
    """What distinguishes this action from a sibling of the same type and target.

    Three THEORIZE actions on one question differ only by research lane. Keying
    established outcomes on type and target alone let one lane's failure ban the
    two lanes that were never tried.
    """
    import json

    return json.dumps(
        {name: action.extra.get(name) for name in
         ("research_lane", "hop", "parent_theory_id", "theory_id",
          "replication_world_id", "verify_kind")},
        sort_keys=True, default=str)


def information_precondition(state: ScientificState, action: ActionInstance) -> str:
    """Could this action tell the project anything it does not already know?

    A value precondition, not a score. Some actions always "succeed" and
    routinely change nothing — REFLECT with no unexamined failure, ARCHIVE with
    nothing newly closed, REVIEW over evidence every objection already covers.
    Offering them costs a tick and a call and returns the state unchanged, so
    they are refused at the eligibility layer where preconditions belong.

    Returns a refusal reason, or "" when the action can still inform something.
    """
    kind = action.action_type
    attempts = [row for row in state.artifacts if row.get("kind") == "action_attempt"]

    # The general rule, before any per-action one. If this exact action on this
    # exact target has already come back twice with the same outcome and
    # admitted nothing, the project has learned that fact. Running it a third
    # time is not an experiment, it is a re-read of a known answer — and this
    # holds even when unrelated parts of the state have moved on.
    variant = _action_variant(action)
    inert = [row for row in attempts
             if str(row.get("action_type") or "") == kind
             and str(row.get("target") or "") == str(action.target or "")
             and str(row.get("variant") or "") == variant
             and int(row.get("project_epoch") or 0) == int(state.project_epoch)
             and not int(row.get("events_admitted") or 0)]
    outcomes = [str(row.get("outcome_key") or "") for row in inert]
    for outcome in set(outcomes):
        if outcome and outcomes.count(outcome) >= 2:
            return f"already_established_that_this_returns_{outcome}"

    if kind == REFLECT:
        # Reflection needs an unexamined failure to reflect on.
        if not state.failed_designs and not state.anomalies:
            return "nothing_has_failed_yet"
        known = {str(row.get("signature") or "") for row in state.artifacts
                 if row.get("kind") == "failure_lesson"}
        signatures = {"|".join(str(row.get(key) or "") for key in
                               ("action_type", "theory_id", "reason"))
                      for row in state.failed_designs}
        if signatures and signatures <= known:
            return "every_recorded_failure_already_has_a_lesson"

    if kind == ARCHIVE:
        closed = sorted(str(row.get("id") or "") for row in state.resolved_questions)
        failed = sorted({"|".join(str(row.get(key) or "") for key in ("action_type", "theory_id"))
                         for row in state.failed_designs})
        if not (closed or failed):
            return "nothing_is_closed_to_archive"
        previous = next((row for row in reversed(state.artifacts)
                         if row.get("kind") == "archive_record"), {})
        if (list(previous.get("closed_questions") or []) == closed
                and list(previous.get("closed_designs") or []) == failed):
            return "the_archive_already_records_this_set"

    if kind == REVIEW and not _reviewable(state):
        return "the_reviewer_has_nothing_to_add_that_is_not_already_recorded"

    if kind == SYNTHESIZE:
        gap = list((state.quality or {}).get("quality_gap") or [])
        drafted = {str(row.get("evidence_id") or "") for row in state.artifacts
                   if row.get("kind") == "research_synthesis"}
        measured = {str(row.get("evidence_id") or "") for row in state.evidence_records
                    if str(row.get("role") or "") == "ProbeEvidence"}
        if gap and measured and measured <= drafted:
            return "a_redraft_does_not_close_an_open_evidence_gap"

    return ""


def project_actions(
    state: ScientificState, *, strategic_stagnation: Any = None
) -> list[ActionInstance]:
    """REVIEW / REDESIGN / PROJECT_PIVOT eligibility from canonical state."""
    found: list[ActionInstance] = []
    if _reviewable(state):
        found.append(
            ActionInstance(
                SPECS[REVIEW],
                target=str(state.goal or ""),
                reason="reviewable_claim_or_design",
                frontier_target_id="goal:G0" if state.goal else "",
                extra={"project_epoch": int(state.project_epoch)},
            )
        )
    for demand in _redesign_demands(state):
        found.append(
            ActionInstance(
                SPECS[REDESIGN],
                target=str(demand.get("theory_id") or demand.get("dimension") or ""),
                reason=f"unresolved_{demand.get('kind')}",
                frontier_target_id=str(demand.get("question_id") or "goal:G0"),
                extra={"demand": demand, "project_epoch": int(state.project_epoch)},
            )
        )
    trigger = _pivot_trigger(state, strategic_stagnation=strategic_stagnation)
    if trigger is not None:
        found.append(
            ActionInstance(
                SPECS[PROJECT_PIVOT],
                target=str(state.goal or ""),
                reason=str(trigger.get("reason") or "direction_not_worth_continuing"),
                frontier_target_id="goal:G0" if state.goal else "",
                extra={"trigger": trigger, "project_epoch": int(state.project_epoch)},
            )
        )
    return found


def worker_actions(state: ScientificState, actions: list[ActionInstance]) -> list[ActionInstance]:
    """Readiness from persisted scientific artifacts, not a second pipeline."""
    surveys = [r for r in state.artifacts if r.get("kind") == "literature_survey" and r.get("works")]
    # The control-plane observer is still useful, but cannot substitute for survey.
    found = [a for a in actions if a.action_type not in {SURVEY, THEORIZE, PROBE, VERIFY, SYNTHESIZE}]
    found = [a for a in found if a.action_type != OBSERVE or not any(
        r.get("role") == "QuestionEvidence" and r.get("question_id") == a.target
        and r.get("world_id") == state.world_id for r in state.evidence_records)]
    for row in state.evidence_records:
        if row.get("epistemic") == "WORLD" and not row.get("verify_count"):
            found.append(ActionInstance(SPECS[VERIFY], target=str(row.get("evidence_id") or ""),
                frontier_target_id=str(row.get("question_id") or "goal:G0"),
                reason="check_exact_evidence_identity", extra={"verify_kind": VERIFY_REPLICATION,
                                                               "evidence_role": row.get("role")}))
        elif row.get("role") == "ProbeEvidence" and row.get("reproduction_ok") and not row.get("replication_of"):
            for world in state.world_versions:
                wid = str(world.get("id") or world.get("world_id") or "")
                if world.get("research_role") != "heldout" or wid == row.get("world_id"):
                    continue
                # A registered script names the file it reads, so two worlds can
                # only host the same experiment when they share a payload name.
                # Demanding a replication no script can perform left the
                # dimension permanently missing and spent a tick each time.
                if not _replication_compatible_ids(state, str(row.get("world_id") or ""), wid):
                    continue
                if any(r.get("replication_of") == row.get("evidence_id") and r.get("world_id") == wid for r in state.evidence_records):
                    continue
                found.append(ActionInstance(SPECS[VERIFY], target=str(row.get("evidence_id")),
                    frontier_target_id=str(row.get("question_id") or "goal:G0"), reason="heldout_replication_debt",
                    extra={"replication_world_id": wid, "evidence_role": "ProbeEvidence"}))
    if not surveys:
        questions = state.open_questions + state.blocked_questions
        target = str(questions[0].get("id")) if questions else "goal:G0"
        found.append(ActionInstance(SPECS[SURVEY], target=target,
                                   frontier_target_id=target, reason="literature_gap",
                                   extra={"extract_trajectories": True}))
        return unattempted_actions(state, found)
    found.extend(repair_actions(state))
    questions = state.open_questions + state.blocked_questions + state.resolved_questions
    for question in questions:
        qid = str(question.get("id") or "")
        if not any(r.get("question_id") in {"", qid} for r in surveys):
            found.append(ActionInstance(SPECS[SURVEY], target=qid, frontier_target_id=qid,
                reason="question_literature_gap", extra={"extract_trajectories": True}))
            continue
        theories = [t for t in state.theories if t.get("question_id") == qid]
        # A grounded transition needs one retrieved paper to cite another. Keyword
        # retrieval rarely returns a citation-linked pair, so this library is
        # often empty — and offering a lane with nothing to ground it spends a
        # tick to fail in a way the state already predicts.
        grounded = any(r.get("research_transitions") for r in surveys)
        for lane in ("trajectory_supported", "assumption_reframe", "unconstrained"):
            if lane == "trajectory_supported" and not grounded:
                continue
            if not any(t.get("research_lane") == lane and int(t.get("hop") or 1) == 1 for t in theories):
                found.append(ActionInstance(SPECS[THEORIZE], target=qid, frontier_target_id=qid,
                    lineage_id=str(question.get("lineage_id") or ""), reason="first_hop_branch_gap",
                    extra={"research_lane": lane, "hop": 1}))
        for theory in theories:
            if theory.get("role") == "competing_explanation":
                continue
            tid = str(theory.get("id") or "")
            card = theory.get("card") or {}
            measured = any(r.get("theory_id") == tid for r in state.evidence_records)
            attempted = any(r.get("theory_id") == tid and r.get("action_type") == PROBE
                            for r in state.failed_designs)
            literature_checked = any(r.get("theory_id") == tid for r in surveys)
            if card and not literature_checked:
                found.append(ActionInstance(SPECS[SURVEY], target=qid, frontier_target_id=qid,
                    reason="hypothesis_literature_check", extra={"theory_id": tid, "claim": theory.get("claim") or card.get("claim")}))
            if card and literature_checked and not measured and not attempted:
                found.append(ActionInstance(SPECS[PROBE], target=tid, frontier_target_id=qid,
                    reason="discriminate_competing_hypotheses" if str(card.get("idea_kind") or "probe").lower() == "probe"
                           else "check_missing_probe_compilation", extra={
                        "theory_id": tid, "question_id": qid, "card": card,
                        "causal_handle": card.get("world_lever") or theory.get("mechanism"),
                        "measure": card.get("world_observable") or card.get("prediction"),
                        "freeze": state.world_id,
                        # Only attach a proposal when one exists: an absent
                        # proposal is a plain probe, a null one is a filter that
                        # silently removes every experiment from the menu.
                        **({"experiment_proposal": theory["experiment_proposal"]}
                           if isinstance(theory.get("experiment_proposal"), dict) else {}),
                    }))
            if measured:
                found.append(ActionInstance(SPECS[SYNTHESIZE], target=tid, frontier_target_id=qid,
                                           reason="synthesize_measured_branch"))
            evidence = [r for r in state.evidence_records if r.get("theory_id") == tid
                        and r.get("epistemic") == "WORLD" and r.get("attested")
                        and r.get("execution_status") == "ran" and r.get("world_digest")
                        and r.get("experiment_digest")]
            failures = [r for r in state.failed_designs if r.get("theory_id") == tid]
            has_child = any(t.get("parent_theory_id") == tid for t in theories)
            # A blocked method can be reframed once; it is never called an evidence hop.
            pivot = failures and int(theory.get("failure_pivots") or 0) < 1
            if not has_child and (evidence or pivot):
                found.append(ActionInstance(SPECS[THEORIZE], target=qid, frontier_target_id=qid,
                    lineage_id=str(question.get("lineage_id") or ""),
                    reason="evidence_driven_transition" if evidence else "failure_driven_reframe",
                    extra={"research_lane": "trajectory_supported" if evidence else "assumption_reframe",
                           "hop": int(theory.get("hop") or 1) + 1, "parent_theory_id": tid,
                           "transition_kind": "evidence_driven" if evidence else "failure_reframe",
                           "evidence_context": evidence, "failure_context": failures,
                           "failure_pivots": int(theory.get("failure_pivots") or 0) + (0 if evidence else 1)}))
    return unattempted_actions(state, found)


def _read_slice(state: ScientificState, name: str, action: ActionInstance) -> Any:
    """The part of the state one declared ``ActionSpec.reads`` entry refers to.

    Deliberately narrow. An action whose declared inputs have not changed will
    produce the same result it produced last time, so it must not be offered
    again — and an action whose inputs *have* changed must be.
    """
    if name == "literature":
        return [r.get("id") for r in state.artifacts if r.get("kind") == "literature_survey"]
    if name in {"scientific_archive", "evidence_records"}:
        return [(r.get("evidence_id"), r.get("verify_count"), r.get("outcome"))
                for r in state.evidence_records]
    if name in {"world_version", "world_lineage", "world_id"}:
        return [(r.get("id") or r.get("world_id"), r.get("digest"), r.get("role"))
                for r in state.world_versions] + [state.world_id]
    if name in {"capability_registry",}:
        return sorted(state.available_capabilities)
    if name == "missing_capabilities":
        return sorted(state.missing_capabilities)
    if name == "open_questions":
        # Identity only. A failing action records an ActionBlocked that changes
        # the question's status, and status in this slice let that action
        # unblock its own retry — the same doomed lane was rescheduled every
        # tick because its own failure looked like a changed input.
        return sorted(str(r.get("id") or "") for r in
                      state.open_questions + state.blocked_questions
                      + state.partial_questions + state.resolved_questions)
    if name in {"failure_archive", "failed_designs"}:
        return [(r.get("action_type"), r.get("theory_id"), r.get("reason"))
                for r in state.failed_designs]
    if name == "working_memory":
        # What an archiving or reflecting action would have to work on.
        return {"closed": [r.get("id") for r in state.resolved_questions],
                "failures": len(state.failed_designs),
                "anomalies": list(state.anomalies)}
    if name == "evidence_id":
        target = next((r for r in state.evidence_records
                       if str(r.get("evidence_id") or "") == str(action.target or "")), {})
        return (target.get("evidence_id"), target.get("verify_count"),
                target.get("reproduction_ok"), target.get("replication_of"),
                action.extra.get("replication_world_id"))
    if name in {"harness_probe_executor", "harness_version", "harness_archive"}:
        return state.harness_version
    if name == "reviews":
        return [(r.get("review_id"), r.get("status"), r.get("severity")) for r in state.reviews]
    if name == "quality_state":
        return {"gap": sorted((state.quality or {}).get("quality_gap") or []),
                "statuses": {k: v.get("status") for k, v in
                             sorted(((state.quality or {}).get("dimensions") or {}).items())}}
    if name == "research_contract":
        return (state.contract or {}).get("root_question", "")
    if name == "resources":
        return (state.resources or {}).get("exhausted")
    if name == "scientific_state":
        # Only for actions that genuinely branch on the whole project shape.
        return {"questions": [r.get("id") for r in state.open_questions],
                "theories": [(r.get("id"), r.get("status")) for r in state.theories],
                "capabilities": sorted(state.missing_capabilities)}
    return name


# A repair type names what has to change; the transformation that changes it.
REPAIR_OPERATOR = {
    "experiment_redesign": "representation_change",
    "measurement_redesign": "verifier_shift",
    "causal_redesign": "mechanism_replacement",
    "stronger_baseline": "boundary_search",
    "broader_evaluation": "scaling",
    "assumption_reframe": "assumption_inversion",
    "representation_change": "representation_change",
}


def repair_actions(state: ScientificState) -> list[ActionInstance]:
    """Turn an open design revision into the hypothesis that carries its repair.

    A revision states what failed, what must change, and that only new WORLD
    evidence can settle it. Nothing converted that into an experiment: four
    revisions in one live segment produced no new hypothesis and no second
    probe, so the project could not act on its own redesign and the repair loop
    ended at a note. The revision now opens the obligation that produces the
    repaired design; the experiment itself follows the ordinary probe path.
    """
    epoch = int(state.project_epoch)
    attempted = {
        str(row.get("revision_id") or "")
        for row in state.theories if row.get("revision_id")
    }
    found: list[ActionInstance] = []
    for revision in state.design_revisions:
        rid = str(revision.get("revision_id") or "")
        if (not rid or rid in attempted
                or int(revision.get("project_epoch") or 0) != epoch
                or str(revision.get("outcome") or "open") != "open"):
            continue
        # Resolve the parent to a hypothesis that exists, or to none. A repair
        # aimed at a hypothesis id the state does not hold is refused downstream
        # as a lineage mismatch, which is how four live revisions produced no
        # experiment even after they reached the menu.
        # The parent the revision recorded, and only that. A fallback that
        # re-derived it from the newest hypothesis made this action's identity
        # change every tick, so the retry guard could never recognise it.
        named = str(revision.get("parent_design") or "")
        parent = next((row for row in state.theories
                       if named and str(row.get("id") or "") == named), {})
        parent_id = str(parent.get("id") or "")
        qid = str(parent.get("question_id") or "")
        if not qid:
            qid = next((str(row.get("id") or "") for row in
                        state.open_questions + state.blocked_questions), "")
        if not qid:
            continue
        repair = str(revision.get("selected_repair") or "experiment_redesign")
        found.append(ActionInstance(
            SPECS[THEORIZE], target=qid, frontier_target_id=qid,
            lineage_id=str(parent.get("lineage_id") or ""),
            reason="carry_out_design_revision",
            extra={
                "research_lane": "assumption_reframe",
                "hop": int(parent.get("hop") or 1) + 1 if parent else 1,
                "parent_theory_id": parent_id,
                "transition_kind": "design_repair",
                "revision_id": rid,
                "repair": repair,
                "repair_operator": REPAIR_OPERATOR.get(repair, "representation_change"),
                "changed_components": list(revision.get("changed_components") or []),
                "failure_root_cause": str(revision.get("failure_root_cause") or ""),
                "early_kill_condition": str(revision.get("early_kill_condition") or ""),
            }))
    return found


def _replication_compatible_ids(state: ScientificState, primary: str, heldout: str) -> bool:
    """Can these two recorded worlds host the same registered experiment?"""
    rows = {str(row.get("id") or row.get("world_id") or ""): dict(row)
            for row in state.world_versions}
    left, right = rows.get(primary) or {}, rows.get(heldout) or {}
    if not left or not right:
        return False
    if left.get("schema") and right.get("schema") and left["schema"] != right["schema"]:
        return False

    def payloads(row: Mapping[str, Any]) -> set[str]:
        from pathlib import Path as _Path

        skip = {"seed.json", "origin.json", "manifest.json"}
        return {_Path(str(name)).name for name in row.get("files") or []
                if _Path(str(name)).name not in skip}

    known = payloads(left), payloads(right)
    if not all(known):
        return True  # files not recorded on the row; let the worker decide
    return bool(known[0] & known[1])


def action_input_key(state: ScientificState, action: ActionInstance) -> str:
    """A retry needs changed *declared inputs*, not just a later clock tick.

    This used to hash the whole scientific state, which defeated its own
    purpose: any unrelated change — one new evidence row, one new artifact —
    made every previously-failed action look untried again, so a blocked
    OBSERVE or an ACQUIRE with no recipe was rescheduled indefinitely. The key
    is now built from ``ActionSpec.reads``, the inputs the action itself
    declares. If a spec under-declares its inputs that is a spec to fix, not a
    reason to hash the world.
    """
    import hashlib
    import json

    inputs = {
        "action": action.action_type,
        "target": action.target,
        "reads": {name: _read_slice(state, name, action)
                  for name in sorted(action.spec.reads)},
        "branch": {k: action.extra.get(k) for k in
                   ("research_lane", "parent_theory_id", "hop", "theory_id",
                    "replication_world_id")},
        "project": {
            "epoch": state.project_epoch,
            "demand": (action.extra.get("demand") or {}).get("review_id")
                      or (action.extra.get("demand") or {}).get("dimension") or "",
            "lanes": sorted(str(row.get("lane") or "")
                            for row in action.extra.get("fork_candidates") or []),
        },
    }
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()


def unattempted_actions(state: ScientificState, actions: list[ActionInstance]) -> list[ActionInstance]:
    attempted = {r.get("input_key") for r in state.artifacts if r.get("kind") == "action_attempt"}
    return [a for a in actions if action_input_key(state, a) not in attempted]


def types_of(actions: Iterable[ActionInstance]) -> tuple[str, ...]:
    return tuple(item.action_type for item in actions)


ACTION_COMPLETENESS: dict[str, dict[str, bool]] = {
    SURVEY: {
        "eligibility": True,
        "planner": True,
        "executor": True,
        "validator": True,
        "typed_evidence": False,
        "reducer": True,
        "regression_test": True,
    },
    ASK: {
        "eligibility": True,
        "planner": True,
        "executor": True,
        "validator": True,
        "typed_evidence": False,
        "reducer": True,
        "regression_test": True,
    },
    OBSERVE: {
        "eligibility": True,
        "planner": True,
        "executor": True,
        "validator": True,
        "typed_evidence": True,
        "reducer": True,
        "regression_test": True,
    },
    ACQUIRE: {
        "eligibility": True,
        "planner": True,
        "executor": True,
        "validator": True,
        "typed_evidence": True,
        "reducer": True,
        "regression_test": True,
    },
    THEORIZE: {
        "eligibility": True,
        "planner": True,
        "executor": True,
        "validator": True,
        "typed_evidence": True,
        "reducer": True,
        "regression_test": True,
    },
    PROBE: {
        "eligibility": True,
        "planner": True,
        "executor": True,
        "validator": True,
        "typed_evidence": True,
        "reducer": True,
        "regression_test": True,
    },
    VERIFY: {
        "eligibility": True,
        "planner": True,
        "executor": True,
        "validator": True,
        "typed_evidence": True,
        "reducer": True,
        "regression_test": True,
    },
    REFLECT: {
        "eligibility": True,
        "planner": True,
        "executor": True,
        "validator": True,
        "typed_evidence": False,
        "reducer": True,
        "regression_test": True,
    },
    SYNTHESIZE: {
        "eligibility": True,
        "planner": True,
        "executor": True,
        "validator": True,
        "typed_evidence": False,
        "reducer": True,
        "regression_test": True,
    },
    ARCHIVE: {
        "eligibility": True,
        "planner": True,
        "executor": True,
        "validator": True,
        "typed_evidence": False,
        "reducer": True,
        "regression_test": False,
    },
    FORK_LINEAGE: {
        "eligibility": True,
        "planner": True,
        "executor": True,
        "validator": True,
        "typed_evidence": False,
        "reducer": True,
        "regression_test": True,
    },
    EVOLVE_HARNESS: {
        "eligibility": True,
        "planner": True,
        "executor": True,
        "validator": True,
        "typed_evidence": False,
        "reducer": True,
        "regression_test": True,
    },
}
