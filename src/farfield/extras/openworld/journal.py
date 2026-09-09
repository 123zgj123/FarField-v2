"""Decision journal and outcome contingencies: the compact project brief.

A worker used to receive ``deepcopy(state.to_dict())`` — the entire scientific
state, growing without bound — and a ``projection`` argument that no worker ever
read. Over a long trajectory that is the worst of both worlds: the prompt is
dominated by accumulated narrative, and the carefully-computed relevant slice is
thrown away.

The journal is a *derived* view. It is recomputed from canonical state every
time it is asked for, it is versioned, and nothing reads it as authority. It
answers the five questions a researcher would actually want answered before
choosing the next action:

    what is this project for
    what is the current strategy and why is it still viable
    what is the strongest thing standing against it
    what is the next decisive action
    what is left to spend

Contingency planning is the other half. A long-horizon agent should know before
running an experiment what each outcome would mean — and should say so in
branches, not in a fabricated ``P(success) = 0.82``. Nothing in this runtime is
a calibrated predictor, so nothing here emits a probability.
"""

from __future__ import annotations

from typing import Any, Mapping

from .contract import contract_from_state
from .quality import ReviewRecord, open_reviews
from .resources import budget_phase, budget_state


JOURNAL_VERSION = "decision-journal-v1"

MAX_EVIDENCE = 6
MAX_FAILURES = 4
MAX_OBJECTIONS = 5


def _relevant_evidence(state: Any, *, question_id: str = "", theory_id: str = "") -> list[dict[str, Any]]:
    rows = [
        row for row in getattr(state, "evidence_records", []) or []
        if str(row.get("epistemic") or "") == "WORLD" and row.get("promotion_ok")
    ]
    if theory_id:
        focused = [row for row in rows if str(row.get("theory_id") or "") == theory_id]
        rows = focused or rows
    if question_id:
        focused = [row for row in rows if str(row.get("question_id") or "") == question_id]
        rows = focused or rows
    return [
        {
            key: row.get(key)
            for key in ("evidence_id", "theory_id", "question_id", "outcome", "verdict",
                        "treatment", "control", "sample_size", "world_id",
                        "reproduction_ok", "transfer_ok", "cannot_corroborate")
            if row.get(key) is not None
        }
        for row in rows[-MAX_EVIDENCE:]
    ]


def current_strategy(state: Any) -> dict[str, Any]:
    """What the project is currently trying, and whether it still holds up."""
    contract = contract_from_state(state)
    quality = getattr(state, "quality", {}) or {}
    dimensions = quality.get("dimensions") or {}
    live = [
        row for row in getattr(state, "theories", []) or []
        if row.get("status") not in {"retired"} and row.get("role") != "competing_explanation"
    ]
    gap = list(quality.get("quality_gap") or [])
    fatal = open_reviews(getattr(state, "reviews", []) or [], severity="fatal")
    revisions = [
        row for row in getattr(state, "design_revisions", []) or []
        if int(row.get("project_epoch") or 0) == int(getattr(state, "project_epoch", 0) or 0)
    ]
    viable: list[str] = []
    doubts: list[str] = []
    if live:
        viable.append(f"{len(live)} live hypotheses still attached to the contract")
    else:
        doubts.append("no live hypothesis is attached to the root question")
    if fatal:
        doubts.append(f"{len(fatal)} fatal objections stand unrepaired")
    if len(revisions) >= 2 and all(str(r.get("outcome") or "open") != "resolved" for r in revisions):
        doubts.append(f"{len(revisions)} redesigns have not moved their dimension")
    if int((getattr(state, "debt", {}) or {}).get("goal_drift_debt") or 0):
        doubts.append("open questions have drifted off the root question")
    if not gap:
        viable.append("the contract's quality requirements are met")
    return {
        "root_question": contract.root_question,
        "target_quality": contract.target_quality,
        "project_epoch": int(getattr(state, "project_epoch", 0) or 0),
        "live_hypotheses": [str(row.get("id") or "") for row in live][-6:],
        "quality_gap": gap,
        "weakest_dimensions": sorted(
            gap, key=lambda name: str((dimensions.get(name) or {}).get("status") or ""))[:3],
        "why_still_viable": viable,
        "why_it_might_not_be": doubts,
        "verdict": "viable" if viable and not doubts else (
            "under_doubt" if viable else "not_viable_as_stated"),
    }


def next_decisive_action(state: Any) -> dict[str, Any]:
    """The single most informative thing to do next, and what makes it decisive.

    Derived from the quality gap and the review debt, not from a ranking of
    whatever happened to be eligible. Where they disagree the disagreement is
    itself worth seeing.
    """
    quality = getattr(state, "quality", {}) or {}
    dimensions = quality.get("dimensions") or {}
    fatal = open_reviews(getattr(state, "reviews", []) or [], severity="fatal")
    major = open_reviews(getattr(state, "reviews", []) or [], severity="major")
    if fatal:
        record = ReviewRecord.from_dict(fatal[0])
        return {
            "action": "REDESIGN", "because": record.objection,
            "review_id": record.review_id, "repair_type": record.repair_type,
            "decisive_because": "no further result of this design can answer this objection",
        }
    for name in list(quality.get("quality_gap") or []):
        work = (dimensions.get(name) or {}).get("required_next_work") or []
        if work:
            return {
                "action": str(work[0]), "because": f"{name} is below the contract",
                "dimension": name,
                "blocking_reasons": list((dimensions.get(name) or {}).get("blocking_reasons") or []),
                "decisive_because": f"{name} is the binding constraint on the central claim",
            }
    if major:
        record = ReviewRecord.from_dict(major[0])
        return {"action": "REDESIGN", "because": record.objection,
                "review_id": record.review_id, "repair_type": record.repair_type,
                "decisive_because": "an unrepaired major objection caps the claim"}
    return {"action": "", "because": "no binding constraint recorded",
            "decisive_because": "the quality gap is closed; check readiness, not more actions"}


def research_journal(
    state: Any, *, question_id: str = "", theory_id: str = ""
) -> dict[str, Any]:
    """The compact, derived project brief a worker should see instead of history."""
    contract = contract_from_state(state)
    reviews = getattr(state, "reviews", []) or []
    budget = budget_state(state)
    contradictions = list(getattr(state, "contradictions", []) or [])
    failures = list(getattr(state, "failed_designs", []) or [])[-MAX_FAILURES:]
    decisions = list(getattr(state, "decision_journal", []) or [])[-6:]
    return {
        "version": JOURNAL_VERSION,
        "is_derived_projection": True,
        "not_authoritative": "recomputed from ScientificState; never a second truth",
        "research_contract": contract.to_dict(),
        "strategy": current_strategy(state),
        "next_decisive_action": next_decisive_action(state),
        "relevant_world_evidence": _relevant_evidence(
            state, question_id=question_id, theory_id=theory_id),
        "strongest_contradiction": contradictions[0] if contradictions else None,
        "open_objections": [
            {k: row.get(k) for k in
             ("review_id", "severity", "dimension", "objection", "repair_type",
              "requires_new_evidence")}
            for row in open_reviews(reviews)
            if ReviewRecord.from_dict(row).severity in {"fatal", "major"}
        ][:MAX_OBJECTIONS],
        "recent_failures": [
            {k: row.get(k) for k in ("action_type", "reason", "theory_id") if row.get(k)}
            for row in failures
        ],
        "recorded_decisions": decisions,
        "resources": {
            "phase": budget_phase(state),
            "remaining": dict(budget.get("remaining") or {}),
            "budget_pressure": budget.get("budget_pressure"),
        },
        "epistemic_reminders": [
            "reviewer judgment is not evidence",
            "a GENERATED hypothesis never becomes WORLD by being restated",
            "an objection requiring new evidence cannot be closed by rewriting",
        ],
    }


# ---------------------------------------------------------------------------
# Outcome contingencies
# ---------------------------------------------------------------------------


def contingency_plan(state: Any, action: Any = None) -> dict[str, Any]:
    """What each outcome of the next experiment would mean, in branches.

    Deliberately not a forecast. There is no calibrated predictor in this
    runtime, so no branch carries a probability; each branch says what the
    project would do, and why, if that outcome occurred.
    """
    quality = getattr(state, "quality", {}) or {}
    dimensions = quality.get("dimensions") or {}
    adequacy = str((dimensions.get("experimental_adequacy") or {}).get("status") or "unknown")
    replication = str((dimensions.get("replication") or {}).get("status") or "unknown")
    mechanism = str((dimensions.get("mechanism_support") or {}).get("status") or "unknown")
    powered = adequacy in {"partial", "adequate"}
    target = str(getattr(action, "target", "") or "")

    supports_next = ["VERIFY: replicate on a heldout world"] if replication != "adequate" else []
    if mechanism != "adequate":
        supports_next.append("PROBE: test the mechanism against its competing explanation")
    if not supports_next:
        supports_next = ["REVIEW: look for what a reviewer would still refuse"]

    weakens_next = (
        ["REDESIGN: the result is informative, so change the account, not the measurement",
         "PROJECT_PIVOT: if no repaired design can support the root question"]
        if powered else
        ["REDESIGN: power is inadequate, so this outcome does not discriminate yet"]
    )
    return {
        "kind": "outcome_contingency_plan",
        "target": target,
        "is_forecast": False,
        "no_probabilities_because": "this runtime has no calibrated outcome predictor",
        "power_state": adequacy,
        "branches": [
            {
                "outcome": "supports",
                "means": "the prediction held under the registered comparison",
                "does_not_mean": "the mechanism is established or the effect generalizes",
                "next": supports_next,
            },
            {
                "outcome": "weakens",
                "means": ("the prediction failed at adequate power" if powered
                          else "the prediction failed, but power was not adequate"),
                "does_not_mean": "the hypothesis is refuted in general",
                "next": weakens_next,
            },
            {
                "outcome": "inconclusive",
                "means": "the arms did not separate beyond the registered margin",
                "does_not_mean": "a negative result",
                "next": [
                    "REDESIGN: diagnose the measurement before spending another run",
                    "REVIEW: record what this design cannot answer",
                ],
            },
        ],
    }
