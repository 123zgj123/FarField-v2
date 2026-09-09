"""Research decision scheduler: which decision matters most, not which action is cheap.

The original scheduler scored actions from a fixed table of per-action-type
constants. It could tell OBSERVE from ACQUIRE, and that was the whole of its
judgment. It could not see that a fatal objection stood against the design it
was about to run again, that the question it was about to observe had drifted
off the contract, that the project's quality gap was in baseline strength and
not in more data, or that the budget was nearly gone. In every situation with
those features it picked the same action, because none of them were terms in
its value function.

The base heuristic is kept — it encodes real dependency structure and existing
behaviour depends on it. On top of it sits a research-decision layer that reads
the contract, the quality state, the review debt and the resource state. That
layer is inert until a project actually has project-level state, so a bare
question-and-world run schedules exactly as it did before.

Every term here is a declared estimate over recorded state. None of them is a
measured information gain, and none is a calibrated probability of anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import math
from typing import Any, Iterable

from .actions import (
    ACQUIRE,
    ASK,
    EVOLVE_HARNESS,
    FORK_LINEAGE,
    OBSERVE,
    PROBE,
    PROJECT_PIVOT,
    REDESIGN,
    REVIEW,
    SURVEY,
    SYNTHESIZE,
    THEORIZE,
    VERIFY,
    ActionInstance,
)
from .contract import alignment_of_question, contract_from_state
from .frontier import MAINTENANCE_ACTIONS, SCIENTIFIC_ACTIONS, blocked_descendants, traces_to_root
from .state import ScientificState


WEIGHTS = {
    "heuristic_information_value": 1.2,
    "expected_unlock_value": 1.6,
    "scientific_relevance": 1.0,
    "novelty": 0.6,
    "execution_cost": -0.8,
    "uncertainty": 0.4,
    "downstream_branching": 0.7,
    "evidence_quality": 1.1,
    "failure_recoverability": 0.5,
    "verification_value": 1.3,
    "debt_pressure": 1.4,
}

# Research-decision weights. These only apply once a project has project-level
# state; see ``project_layer_active``.
RESEARCH_WEIGHTS = {
    "central_question_value": 1.8,
    "objection_repair_value": 2.6,
    "quality_gap_value": 1.4,
    "strategic_escalation": 1.5,
    "resource_discipline": 1.2,
    "goal_drift_penalty": -2.2,
    "blocked_by_fatal_objection": -2.4,
    "repeated_failure_penalty": -1.6,
    "redesign_exhaustion": -1.5,
    "inert_action_penalty": -1.1,
}

# Actions that gather more of the same kind of result. Running one of these
# while a fatal, evidence-requiring objection stands against the current design
# is the definition of wasted work after a fatal objection.
ROUTINE_EVIDENCE_ACTIONS = frozenset({OBSERVE, PROBE, SURVEY, THEORIZE, ASK})

# Actions that open a new front rather than finishing the current one.
EXPANSION_ACTIONS = frozenset({FORK_LINEAGE, PROJECT_PIVOT, ASK, SURVEY, THEORIZE})

# Actions that can still settle something when the budget is nearly gone.
DECISIVE_ACTIONS = frozenset({PROBE, VERIFY, REDESIGN, REVIEW, SYNTHESIZE})


@dataclass(frozen=True)
class ScoredAction:
    action: ActionInstance
    scores: dict[str, float]
    total: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.to_dict(),
            "scores": dict(self.scores),
            "total": self.total,
        }


def epistemic_safe(action: ActionInstance, state: ScientificState) -> bool:
    kind = action.action_type
    if kind == PROBE and not (
        action.extra.get("causal_handle") and action.extra.get("measure") and (
            action.extra.get("freeze") or state.world_id
        )
    ):
        return False
    if kind in SCIENTIFIC_ACTIONS:
        target = action.frontier_target_id or action.target or state.goal
        if not target:
            return False
        if target and not traces_to_root(state, target) and target != state.goal:
            # still allow a brand-new question id that is already on the state
            known = {str(row.get("id") or "") for row in state.open_questions + state.resolved_questions}
            if target not in known and target not in {state.goal, "goal:G0", "G0"}:
                return False
    return True


def budget_ok(action: ActionInstance, state: ScientificState) -> bool:
    """Refuse actions that would cross a declared limit.

    ``metrics["spent_cost"]`` / ``metrics["budget_cap"]`` are kept for callers
    that set them explicitly. The contract's resource limits are the real check:
    before this, both metric keys were read here and written nowhere, so the
    budget filter never refused anything.
    """
    spent = float((state.metrics or {}).get("spent_cost") or 0)
    cap = float((state.metrics or {}).get("budget_cap") or 1e9)
    if spent + float(action.spec.estimated_cost) > cap:
        return False
    from .resources import affordable

    return affordable(state, cost=float(action.spec.estimated_cost))


def expected_frontier_advancement(action: ActionInstance, state: ScientificState) -> float:
    kind = action.action_type
    unlock = blocked_descendants(state, kind, action.target)
    immediate = 0.9 if kind in {OBSERVE, PROBE, VERIFY} else (0.25 if kind == ACQUIRE else 0.15)
    if kind == ACQUIRE and unlock >= 2:
        return immediate + 1.2 * unlock
    if kind == EVOLVE_HARNESS and state.missing_capabilities:
        return immediate + 0.8 * unlock
    if kind == VERIFY and (state.contradictions or (state.debt or {}).get("verification_debt")):
        return immediate + 0.9 * max(1, unlock)
    return immediate + 0.25 * unlock


def _score(action: ActionInstance, state: ScientificState) -> dict[str, float]:
    kind = action.action_type
    blocked = kind == ACQUIRE and action.reason == "blocked_on_capability_or_world"
    unlocks_observe = blocked or kind == EVOLVE_HARNESS
    observe = kind == OBSERVE
    probe = kind == PROBE
    fork = kind == FORK_LINEAGE
    debt = state.debt or {}
    verify_debt = float(debt.get("verification_debt") or 0)
    contra = float(debt.get("contradiction_debt") or 0)
    dep = float(debt.get("unresolved_dependency") or 0)
    orphan = float(debt.get("orphan_theory_debt") or 0)
    advancement = expected_frontier_advancement(action, state)
    debt_pressure = 0.1
    if kind == VERIFY and (verify_debt or contra):
        debt_pressure = 1.0
    elif kind == ACQUIRE and dep:
        debt_pressure = 0.9
    elif kind == THEORIZE and (
        contra or orphan or (state.resolved_questions and not state.theories)
    ):
        debt_pressure = 0.85
    elif kind == FORK_LINEAGE and state.resolved_questions and not state.theories:
        debt_pressure = 0.05
    elif kind == ASK:
        debt_pressure = 0.05
    verification_value = 0.9 if kind == VERIFY else (0.4 if observe or probe else 0.1)
    if observe and state.open_questions:
        debt_pressure = max(debt_pressure, 0.85)
    if kind == VERIFY and state.open_questions:
        debt_pressure = min(debt_pressure, 0.25)
        verification_value = 0.35
    return {
        "heuristic_information_value": advancement if kind == ACQUIRE else (
            0.9 if observe or probe else (0.5 if kind == "SURVEY" else 0.35)
        ),
        "expected_unlock_value": 1.0 if unlocks_observe else (0.2 if observe else 0.1 * advancement),
        "scientific_relevance": 0.8 if action.target or action.frontier_target_id else 0.4,
        "novelty": 0.15 if kind == ASK else (0.3 if fork else 0.2),
        "execution_cost": float(action.spec.estimated_cost),
        "uncertainty": 0.6 if kind == EVOLVE_HARNESS else 0.3,
        "downstream_branching": 0.8 if unlocks_observe or fork else min(0.9, 0.2 * advancement),
        "evidence_quality": 0.9 if observe or probe or kind == VERIFY else 0.2,
        "failure_recoverability": 0.7 if kind in {ACQUIRE, EVOLVE_HARNESS, "REFLECT"} else 0.4,
        "verification_value": verification_value,
        "debt_pressure": debt_pressure,
    }


def hypothesis_resolution_priority(proposal: dict[str, Any], state: ScientificState) -> dict[str, Any]:
    """Estimate discriminating value, never evidence or calibrated information gain.

    Resolution is the posterior-weighted mass of competing pairs separated by
    the declared intervention: sum(2*w_i*w_j), with weights normalized over the
    currently known theories. Belief confidence is a replayable bookkeeping
    scale, not a joint probability distribution. This pair-disagreement proxy
    does not assume a likelihood model that the runtime has not measured.

    Explicit competitor edges restrict eligible pairs; with no recorded edges,
    a proposal may declare a comparison between known theories. Different
    observables or uncertain predictions do not establish discrimination.
    All gain/cost factors are proposal estimates, not measured world values.
    """
    def invalid(reason: str) -> dict[str, Any]:
        return {"valid": False, "reason": reason, "priority": 0.0,
                "score_basis": "proposal_estimate_not_evidence"}

    def number(value: Any, upper: float | None = None) -> bool:
        try:
            return (isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(value) and value >= 0
                    and (upper is None or value <= upper))
        except OverflowError:
            return False

    if not isinstance(proposal, dict):
        return invalid("experiment_proposal_must_be_object")
    known = {row["id"]: row for row in state.theories
             if isinstance(row.get("id"), str) and row["id"]}
    compared = proposal.get("hypotheses_compared")
    if (not isinstance(compared, list) or len(compared) < 2
            or any(not isinstance(hid, str) or hid not in known for hid in compared)
            or len(set(compared)) != len(compared)):
        return invalid("comparison_requires_distinct_known_hypotheses")
    predictions = proposal.get("expected_outcomes")
    if not isinstance(predictions, dict) or set(predictions) != set(compared):
        return invalid("predictions_must_match_compared_hypotheses")
    for prediction in predictions.values():
        if (not isinstance(prediction, dict)
                or not isinstance(prediction.get("observable"), str)
                or not prediction["observable"].strip()
                or prediction.get("direction") not in ("increase", "decrease", "unchanged")):
            return invalid("prediction_requires_observable_and_determinate_direction")
    if len({p["observable"].strip().casefold() for p in predictions.values()}) != 1:
        return invalid("comparison_requires_same_observable")
    nuisance = proposal.get("nuisance_factors")
    if not isinstance(nuisance, list) or any(not isinstance(x, str) or not x.strip() for x in nuisance):
        return invalid("nuisance_factors_must_be_explicit_list")
    intervention = proposal.get("minimal_discriminating_intervention")
    if not isinstance(intervention, str) or not intervention.strip():
        return invalid("minimal_discriminating_intervention_required")
    interpretations = proposal.get("interpretations", {})
    if not isinstance(interpretations, dict):
        return invalid("interpretations_must_be_object")
    for outcome in ("positive", "negative", "inconclusive"):
        value = proposal.get("interpretation_if_" + outcome, interpretations.get(outcome))
        if not isinstance(value, str) or not value.strip():
            return invalid("interpretation_required_for_" + outcome)
    for name in ("expected_scientific_gain", "transfer_value", "frontier_unlock", "cost", "risk"):
        if not number(proposal.get(name), None if name in {"cost", "risk"} else 1.0):
            return invalid("invalid_estimate_" + name)
    weights: dict[str, float] = {}
    competing_pairs: set[frozenset[str]] = set()
    for hid, theory in known.items():
        belief = state.belief_states.get(hid, {})
        confidence = belief.get("posterior_confidence") if isinstance(belief, dict) else None
        if not number(confidence, 1.0):
            return invalid("missing_or_invalid_replayed_belief_" + hid)
        weights[hid] = float(confidence)
        competitors = belief.get("competing_theories") or theory.get("competing") or []
        for other in competitors if isinstance(competitors, list) else []:
            other_id = other.get("id") if isinstance(other, dict) else other
            if isinstance(other_id, str) and other_id in known and other_id != hid:
                competing_pairs.add(frozenset((hid, other_id)))
    mass = sum(weights.values())
    resolution = 0.0
    separated: list[list[str]] = []
    for left, right in combinations(compared, 2):
        if competing_pairs and frozenset((left, right)) not in competing_pairs:
            continue
        if predictions[left]["direction"] != predictions[right]["direction"]:
            separated.append([left, right])
            if mass:
                resolution += 2.0 * (weights[left] / mass) * (weights[right] / mass)
    terms = {name: float(proposal[name]) for name in
             ("expected_scientific_gain", "transfer_value", "frontier_unlock", "cost", "risk")}
    priority = (resolution * terms["expected_scientific_gain"] * terms["transfer_value"]
                * terms["frontier_unlock"] - terms["cost"] - terms["risk"])
    if not math.isfinite(priority):
        return invalid("nonfinite_priority")
    return {"valid": True, "reason": "", "score_basis": "proposal_estimate_not_evidence",
            "expected_hypothesis_resolution": resolution, "separated_pairs": separated,
            "belief_weights": weights, **terms, "priority": priority}


def project_layer_active(state: ScientificState) -> bool:
    """Does this state have anything project-level to reason about yet?

    A workspace with only a goal, a world and some questions is scheduled by the
    original heuristic exactly as before. The research-decision layer switches on
    when a contract, a recorded objection or a design revision exists.
    """
    return bool(
        (state.contract or {}).get("root_question")
        or state.reviews
        or state.design_revisions
        or int(state.project_epoch or 0)
    )


def _fatal_block(state: ScientificState) -> list[dict[str, Any]]:
    """Open fatal objections that no revision is yet addressing.

    While one of these stands, running the same class of design again is not
    research, it is repetition. The objection has to be repaired first.
    """
    from .quality import open_reviews

    addressed = {
        str(rid)
        for revision in state.design_revisions
        if int(revision.get("project_epoch") or 0) == int(state.project_epoch)
        for rid in revision.get("addresses_reviews") or []
    }
    return [
        row for row in open_reviews(state.reviews, severity="fatal")
        if row.get("requires_new_evidence")
        and int(row.get("project_epoch") or 0) == int(state.project_epoch)
        and str(row.get("review_id") or "") not in addressed
    ]


def _target_alignment(action: ActionInstance, state: ScientificState) -> str:
    """Does this action serve the contract's root question?"""
    contract = contract_from_state(state)
    if not contract.is_set:
        return "unknown"
    target = str(action.frontier_target_id or action.target or "")
    known = (state.open_questions + state.resolved_questions
             + state.partial_questions + state.blocked_questions)
    question = next((row for row in known if str(row.get("id") or "") == target), None)
    if question is None:
        theory = next((row for row in state.theories
                       if str(row.get("id") or "") == str(action.target or "")), None)
        if theory is not None:
            question = next((row for row in known
                             if str(row.get("id") or "") == str(theory.get("question_id") or "")), None)
    if question is None:
        return "aligned" if target in {state.goal, "goal:G0", "G0", ""} else "unknown"
    return alignment_of_question(contract, question, known=known).status


def _research_score(action: ActionInstance, state: ScientificState) -> dict[str, float]:
    """Project-level value terms. Estimates over recorded state, not measurements."""
    from .progress import maybe_strategic_stagnation
    from .quality import open_reviews
    from .resources import budget_phase

    kind = action.action_type
    quality = state.quality or {}
    dimensions = quality.get("dimensions") or {}
    gap = list(quality.get("quality_gap") or [])
    alignment = _target_alignment(action, state)
    fatal_open = _fatal_block(state)
    phase = budget_phase(state)
    strategic = maybe_strategic_stagnation(state)

    # -- does this action move the root question? ---------------------------
    central = 0.0
    if alignment == "aligned":
        central = 0.9 if kind in {PROBE, VERIFY, REDESIGN} else 0.5
    elif alignment == "instrumental":
        central = 0.4 if kind in {PROBE, VERIFY, REDESIGN} else 0.2
    if kind in {REVIEW, PROJECT_PIVOT}:
        # These act on the project as a whole, so they inherit the project's
        # own alignment rather than a node's.
        central = 0.5
    drift = 1.0 if alignment == "drifted" else 0.0

    # -- does it discharge review debt? -------------------------------------
    demand = dict(action.extra.get("demand") or {})
    # Repair attempts have diminishing returns. Two open revisions on a
    # dimension that still has not moved are evidence about the direction, not
    # an invitation to write a third revision of the same shape.
    epoch_revisions = [row for row in state.design_revisions
                       if int(row.get("project_epoch") or 0) == int(state.project_epoch)]
    unresolved_revisions = [row for row in epoch_revisions
                            if str(row.get("outcome") or "open") != "resolved"]
    dimension = str(demand.get("dimension") or "")
    same_dimension = [row for row in unresolved_revisions
                      if str(row.get("dimension") or "") == dimension] if dimension else []
    exhaustion = 0.0
    repair = 0.0
    if kind == REDESIGN:
        severity = str(demand.get("severity") or "major")
        repair = {"fatal": 1.4, "major": 0.9, "minor": 0.3}.get(severity, 0.6)
        exhaustion = float(len(same_dimension) or max(0, len(unresolved_revisions) - 1))
    elif kind == PROJECT_PIVOT:
        repair = 1.2 if fatal_open else 0.7
        # Every redesign this direction already spent without moving is a
        # reason to stop repairing it.
        repair += 0.5 * len(unresolved_revisions)
    elif kind == REVIEW:
        # Reviewing is valuable exactly when there is something unexamined.
        examined = {str(row.get("affected_design") or "") for row in state.reviews}
        unexamined = [row for row in state.evidence_records
                      if str(row.get("role") or "") == "ProbeEvidence"
                      and str(row.get("evidence_id") or "") not in examined]
        repair = 0.9 if unexamined else 0.15
    elif kind == VERIFY:
        repair = 0.5 if any(row.get("repair_type") == "broader_evaluation"
                            for row in open_reviews(state.reviews)) else 0.1

    # -- does it close the project's actual quality gap? ---------------------
    wanted: set[str] = set()
    for name in gap:
        wanted.update(str(item) for item in (dimensions.get(name) or {}).get("required_next_work") or [])
    quality_value = 0.0
    if kind in wanted:
        quality_value = 0.8
    elif kind == REDESIGN and "REDESIGN" in wanted:
        quality_value = 0.8
    if kind == SYNTHESIZE and gap:
        # Writing it up does not close an evidence gap, and reads as if it did.
        quality_value = -0.4

    # -- busy and going nowhere: widen the option set ------------------------
    escalation = 0.0
    if strategic is not None and kind in {REDESIGN, FORK_LINEAGE, PROJECT_PIVOT}:
        escalation = 1.0
    elif strategic is not None and kind in ROUTINE_EVIDENCE_ACTIONS:
        escalation = -0.5

    # -- spend the remaining budget on decisions, not on new fronts ----------
    discipline = 0.0
    if phase == "closing":
        discipline = 0.6 if kind in DECISIVE_ACTIONS else 0.0
        if kind in EXPANSION_ACTIONS:
            discipline = -1.0
    elif phase == "opening" and kind in EXPANSION_ACTIONS:
        discipline = 0.3

    # -- do not re-run a design a fatal objection already killed -------------
    blocked = 0.0
    if fatal_open and kind in ROUTINE_EVIDENCE_ACTIONS:
        blocked = 1.0

    # -- do not repeat a failure that already has a signature ----------------
    repeated = 0.0
    signature = f"{kind}|{action.target}"
    if sum(1 for row in state.failed_designs
           if f"{row.get('action_type')}|{row.get('theory_id')}" == signature) >= 1:
        repeated = 1.0

    # -- an action type that keeps admitting nothing is currently inert -------
    # ARCHIVE and REFLECT always "succeed" and often change nothing. Costing a
    # tick to do nothing is a resource decision, so it belongs in the score.
    attempts = [row for row in state.artifacts
                if row.get("kind") == "action_attempt"
                and str(row.get("action_type") or "") == kind][-4:]
    inert = 0.0
    if len(attempts) >= 2 and all(not int(row.get("events_admitted") or 0) for row in attempts):
        inert = float(min(3, len(attempts)))

    return {
        "central_question_value": central,
        "objection_repair_value": repair,
        "quality_gap_value": quality_value,
        "strategic_escalation": escalation,
        "resource_discipline": discipline,
        "goal_drift_penalty": drift,
        "blocked_by_fatal_objection": blocked,
        "repeated_failure_penalty": repeated,
        "redesign_exhaustion": exhaustion,
        "inert_action_penalty": inert,
    }


def score_action(action: ActionInstance, state: ScientificState) -> ScoredAction:
    scores = _score(action, state)
    total = sum(WEIGHTS[name] * scores[name] for name in WEIGHTS)
    if project_layer_active(state):
        research = _research_score(action, state)
        scores.update(research)
        scores["research_decision_layer"] = 1.0
        total += sum(RESEARCH_WEIGHTS[name] * research[name] for name in RESEARCH_WEIGHTS)
    if "experiment_proposal" in action.extra:
        priority = hypothesis_resolution_priority(action.extra["experiment_proposal"], state)
        if not priority["valid"]:
            raise ValueError("invalid experiment proposal: " + priority["reason"])
        scores.update({name: priority[name] for name in (
            "expected_hypothesis_resolution", "expected_scientific_gain", "transfer_value",
            "frontier_unlock", "cost", "risk")})
        scores["hypothesis_resolution_priority"] = priority["priority"]
        scores["proposal_estimate_not_evidence"] = 1.0
        total += priority["priority"]
    return ScoredAction(action=action, scores=scores, total=total)


def _experiment_gap(action: ActionInstance, state: ScientificState) -> str:
    if "experiment_proposal" not in action.extra:
        return ""
    verdict = hypothesis_resolution_priority(action.extra["experiment_proposal"], state)
    return "" if verdict["valid"] else f"invalid_experiment_proposal:{verdict['reason']}"


def _valid_experiment(action: ActionInstance, state: ScientificState) -> bool:
    return not _experiment_gap(action, state)


def admissible(
    state: ScientificState, actions: Iterable[ActionInstance]
) -> tuple[list[ActionInstance], list[dict[str, Any]]]:
    """Split the menu into what can be scheduled and why the rest cannot.

    Silent filtering is how a controller loses its most important action type
    for an entire run while still reporting it as eligible. Every refusal is
    returned with a reason so the tick view can show it.
    """
    kept: list[ActionInstance] = []
    rejected: list[dict[str, Any]] = []
    for item in actions:
        if not (item.action_type in MAINTENANCE_ACTIONS or epistemic_safe(item, state)):
            rejected.append({"action_type": item.action_type, "target": item.target,
                             "reason": "not_epistemically_safe_for_this_frontier"})
            continue
        if not budget_ok(item, state):
            rejected.append({"action_type": item.action_type, "target": item.target,
                             "reason": "would_cross_a_declared_resource_limit"})
            continue
        gap = _experiment_gap(item, state)
        if gap:
            rejected.append({"action_type": item.action_type, "target": item.target,
                             "reason": gap})
            continue
        kept.append(item)
    return kept, rejected


def schedule(
    state: ScientificState,
    actions: Iterable[ActionInstance],
) -> ScoredAction | None:
    """Heuristic research-value scheduling. Not immediate-score-only."""
    ranked = schedule_all(state, actions)
    return ranked[0] if ranked else None


def schedule_all(
    state: ScientificState,
    actions: Iterable[ActionInstance],
) -> list[ScoredAction]:
    kept, _ = admissible(state, actions)
    return sorted(
        (score_action(item, state) for item in kept),
        key=lambda row: (-row.total, row.action.action_type, row.action.target),
    )
