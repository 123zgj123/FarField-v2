"""Termination semantics: seven different endings that were all one ending.

The old runtime had exactly two vocabularies for stopping — a ``should_terminate``
reason string (``budget`` / ``frontier_exhausted`` / ``stagnation``) and a final
report hard-coded to ``research_complete: False``. That is honest but useless:
it cannot tell "we answered the question" from "we ran out of money" from "this
direction cannot be answered with the worlds we have", and a controller that
cannot tell those apart cannot choose differently between them.

None of the following, alone or together, means the research is ready:

    the runtime loop finished normally
    every currently open question is resolved
    a complete paper was generated
    the budget ran out
    the frontier is momentarily empty

Readiness is a conjunction of gates over admitted evidence, recorded
objections, the contract, and the claim's actual scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contract import contract_from_state
from .quality import STATUS_RANK, meets, open_reviews, requirements_for


RUN_SEGMENT_DONE = "RUN_SEGMENT_DONE"
RESEARCH_READY = "RESEARCH_READY"
RESEARCH_INCOMPLETE = "RESEARCH_INCOMPLETE"
BLOCKED = "BLOCKED"
NO_VIABLE_PATH = "NO_VIABLE_PATH"
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
FRONTIER_EXHAUSTED = "FRONTIER_EXHAUSTED"

STATUSES = (
    RUN_SEGMENT_DONE,
    RESEARCH_READY,
    RESEARCH_INCOMPLETE,
    BLOCKED,
    NO_VIABLE_PATH,
    BUDGET_EXHAUSTED,
    FRONTIER_EXHAUSTED,
)


@dataclass(frozen=True)
class Readiness:
    status: str
    gates: tuple[tuple[str, bool, str], ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status == RESEARCH_READY

    @property
    def failed_gates(self) -> tuple[str, ...]:
        return tuple(name for name, ok, _ in self.gates if not ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ready": self.ready,
            "gates": [
                {"gate": name, "ok": bool(ok), "detail": detail}
                for name, ok, detail in self.gates
            ],
            "failed_gates": list(self.failed_gates),
            "reasons": list(self.reasons),
            "note": (
                "A finished run, a full paper, an empty frontier and an empty "
                "budget are all compatible with unfinished research."
            ),
        }


def _dimension(state: Any, name: str) -> dict[str, Any]:
    return dict(((state.quality or {}).get("dimensions") or {}).get(name) or {})


def _status(state: Any, name: str) -> str:
    return str(_dimension(state, name).get("status") or "unknown")


def readiness(state: Any, *, no_executable_action: bool = False) -> Readiness:
    """Is this project actually done, and if not, in what way is it not done?

    ``no_executable_action`` is the controller reporting that nothing in the
    frontier can currently run. That is a blockage to report, not a result.
    """
    contract = contract_from_state(state)
    quality = state.quality or {}
    requirements = requirements_for(contract)
    reviews = list(getattr(state, "reviews", []) or [])
    fatal = open_reviews(reviews, severity="fatal")
    major = open_reviews(reviews, severity="major")
    resources = dict(getattr(state, "resources", {}) or {})
    allowed_major = int((contract.quality_requirements or {}).get("allowed_open_major") or 0)

    supporting = [
        row for row in getattr(state, "evidence_records", []) or []
        if str(row.get("epistemic") or "") == "WORLD"
        and row.get("outcome") in {"supports", "weakens"}
    ]
    out_of_scope = [row for row in supporting if row.get("cannot_corroborate")]
    outputs = {str(row.get("kind") or "") for row in getattr(state, "artifacts", []) or []}
    missing_outputs = [name for name in contract.required_outputs if name not in outputs]

    gates: list[tuple[str, bool, str]] = [
        (
            "central_question_supported",
            meets(_status(state, "central_claim_support"),
                  requirements.get("central_claim_support", "adequate")),
            f"central_claim_support={_status(state, 'central_claim_support')}",
        ),
        ("no_fatal_objections", not fatal,
         f"{len(fatal)} open fatal objections"),
        ("major_objections_within_contract", len(major) <= allowed_major,
         f"{len(major)} open major objections, contract allows {allowed_major}"),
        (
            "required_comparisons_done",
            meets(_status(state, "baseline_strength"), requirements.get("baseline_strength", "partial")),
            f"baseline_strength={_status(state, 'baseline_strength')}",
        ),
        (
            "required_replication_done",
            meets(_status(state, "replication"), requirements.get("replication", "missing")),
            f"replication={_status(state, 'replication')}",
        ),
        ("evidence_scope_matches_claim", not out_of_scope,
         f"{len(out_of_scope)} supporting rows carry validation gaps"),
        ("no_unauthorized_goal_drift",
         int((getattr(state, "debt", {}) or {}).get("goal_drift_debt") or 0) == 0,
         f"{int((getattr(state, 'debt', {}) or {}).get('goal_drift_debt') or 0)} drifted questions"),
        ("no_critical_unresolved_contradiction",
         not list(getattr(state, "contradictions", []) or []),
         f"{len(list(getattr(state, 'contradictions', []) or []))} open contradictions"),
        ("quality_gap_closed", not list(quality.get("quality_gap") or []),
         f"short on: {sorted(quality.get('quality_gap') or [])}"),
        ("required_outputs_present", not missing_outputs,
         f"missing outputs: {missing_outputs}"),
    ]
    if all(ok for _, ok, _ in gates):
        return Readiness(status=RESEARCH_READY, gates=tuple(gates))

    reasons = tuple(detail for name, ok, detail in gates if not ok)

    # Budget exhaustion settles the *run*, never the science. It is reported as
    # its own status so nobody reads it as an answer.
    if resources.get("exhausted"):
        return Readiness(status=BUDGET_EXHAUSTED, gates=tuple(gates), reasons=reasons)

    # No viable path: the objection cannot be repaired inside this project, or
    # the question cannot be asked of any world we have.
    pivot_demanded = [row for row in open_reviews(reviews)
                      if str(row.get("repair_type") or "") == "project_pivot"]
    revisions = [row for row in getattr(state, "design_revisions", []) or []
                 if int(row.get("project_epoch") or 0) == int(getattr(state, "project_epoch", 0))]
    exhausted_repairs = len(revisions) >= 3 and all(
        str(row.get("outcome") or "open") != "resolved" for row in revisions)
    if pivot_demanded and exhausted_repairs:
        return Readiness(status=NO_VIABLE_PATH, gates=tuple(gates),
                         reasons=reasons + ("redesign_alternatives_exhausted",))

    blocked = list(getattr(state, "blocked_questions", []) or [])
    missing = list(getattr(state, "missing_capabilities", []) or [])
    if blocked and not list(getattr(state, "open_questions", []) or []) and missing:
        return Readiness(status=BLOCKED, gates=tuple(gates),
                         reasons=reasons + (f"missing capabilities: {missing}",))
    if no_executable_action and (blocked or missing or
                                 list(getattr(state, "open_questions", []) or [])):
        # Unanswered questions and nothing that can be run against them: the
        # project is waiting on capability, not finished and not out of ideas.
        detail = f"missing capabilities: {missing}" if missing else (
            "no eligible action can execute against the open frontier")
        return Readiness(status=BLOCKED, gates=tuple(gates), reasons=reasons + (detail,))

    if not (getattr(state, "open_questions", None) or getattr(state, "blocked_questions", None)):
        return Readiness(status=FRONTIER_EXHAUSTED, gates=tuple(gates),
                         reasons=reasons + ("frontier is empty; that is not an answer",))

    return Readiness(status=RESEARCH_INCOMPLETE, gates=tuple(gates), reasons=reasons)


def run_outcome(state: Any, *, horizon_reached: bool = False,
                no_executable_action: bool = False) -> dict[str, Any]:
    """The report a caller should actually read at the end of a segment."""
    verdict = readiness(state, no_executable_action=no_executable_action)
    payload = verdict.to_dict()
    payload["research_complete"] = verdict.ready
    if horizon_reached and not verdict.ready:
        # A segment ending is not a research ending; say both.
        payload["segment"] = RUN_SEGMENT_DONE
    return payload
