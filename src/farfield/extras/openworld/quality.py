"""ResearchQualityState and ReviewRecord: how good is this research project?

``ScientificState`` answers *what do we know*. It has no way to say *this
project is not good enough yet, and here is exactly which part is not good
enough*. Without that, the controller cannot tell a finished project from an
unfinished one, cannot tell a real objection from a wording complaint, and
cannot notice that ten successful actions moved no quality dimension at all.

Two rules keep this honest:

1. **Ordinal, never a fabricated probability.** A dimension is
   ``unknown / missing / weak / partial / adequate``. There is no
   ``accept_probability = 0.81`` here, because nothing in this runtime has ever
   been calibrated against real acceptance decisions.
2. **Derived, never asserted.** Quality is recomputed from admitted evidence,
   recorded reviews and the contract on every replay. A worker cannot write
   "experimental_adequacy: adequate" into the state; it can only produce
   evidence or an objection, and the projection follows.

Reviewer judgment is a *planning signal*, not evidence. A review can lower a
dimension and open repair debt. It can never raise ``central_claim_support``,
because agreement is not measurement (see ``social_consensus_is_not_evidence``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .contract import ResearchContract, alignment_of_question, contract_from_state


# --------------------------------------------------------------------------
# Ordinal quality scale
# --------------------------------------------------------------------------

STATUS_ORDER = ("unknown", "missing", "weak", "partial", "adequate")
STATUS_RANK = {name: index for index, name in enumerate(STATUS_ORDER)}

DIMENSIONS = (
    "novelty",
    "importance",
    "technical_correctness",
    "experimental_adequacy",
    "baseline_strength",
    "measurement_validity",
    "mechanism_support",
    "robustness",
    "generalization",
    "replication",
    "literature_coverage",
    "central_claim_support",
)

# Dimensions no execution can settle. Only literature and review evidence speak
# to them, so they stay ``unknown`` rather than being invented from a run.
JUDGMENT_DIMENSIONS = frozenset({"novelty", "importance"})

DEFAULT_REQUIREMENTS = {
    "exploratory": {"literature_coverage": "partial", "technical_correctness": "partial"},
    "internal": {
        "literature_coverage": "partial", "technical_correctness": "adequate",
        "measurement_validity": "partial", "experimental_adequacy": "partial",
        "central_claim_support": "partial",
    },
    "workshop": {
        "literature_coverage": "adequate", "technical_correctness": "adequate",
        "measurement_validity": "adequate", "experimental_adequacy": "partial",
        "baseline_strength": "partial", "central_claim_support": "partial",
        "novelty": "partial",
    },
    "conference": {
        "literature_coverage": "adequate", "technical_correctness": "adequate",
        "measurement_validity": "adequate", "experimental_adequacy": "adequate",
        "baseline_strength": "adequate", "mechanism_support": "partial",
        "robustness": "partial", "replication": "partial",
        "central_claim_support": "adequate", "novelty": "partial",
        "importance": "partial",
    },
    "archival": {
        "literature_coverage": "adequate", "technical_correctness": "adequate",
        "measurement_validity": "adequate", "experimental_adequacy": "adequate",
        "baseline_strength": "adequate", "mechanism_support": "adequate",
        "robustness": "adequate", "generalization": "partial",
        "replication": "adequate", "central_claim_support": "adequate",
        "novelty": "partial", "importance": "partial",
    },
}


def meets(status: str, requirement: str) -> bool:
    return STATUS_RANK.get(str(status), 0) >= STATUS_RANK.get(str(requirement), 0)


def cap(status: str, ceiling: str) -> str:
    return status if STATUS_RANK.get(status, 0) <= STATUS_RANK.get(ceiling, 0) else ceiling


def requirements_for(contract: ResearchContract) -> dict[str, str]:
    base = dict(DEFAULT_REQUIREMENTS.get(contract.target_quality, DEFAULT_REQUIREMENTS["exploratory"]))
    for name, value in (contract.quality_requirements or {}).items():
        if name in DIMENSIONS and str(value) in STATUS_RANK:
            base[name] = str(value)
    return base


# --------------------------------------------------------------------------
# Reviews
# --------------------------------------------------------------------------

SEVERITIES = ("fatal", "major", "minor")

REPAIR_TYPES = (
    "writing_only",
    "more_evidence",
    "stronger_baseline",
    "broader_evaluation",
    "measurement_redesign",
    "experiment_redesign",
    "causal_redesign",
    "assumption_reframe",
    "representation_change",
    "project_pivot",
)

# A repair that changes only how the work is described. Everything else needs a
# world to answer it.
PRESENTATION_REPAIRS = frozenset({"writing_only"})

# Repairs that cannot be discharged by running the same design again.
REDESIGN_REPAIRS = frozenset(
    {
        "measurement_redesign",
        "experiment_redesign",
        "causal_redesign",
        "assumption_reframe",
        "representation_change",
    }
)

PIVOT_REPAIRS = frozenset({"project_pivot"})

# Resolution kinds a reviewer-facing worker might propose. The first group is
# text; the second is work. Only the second can close an evidence-requiring
# objection.
CAVEAT_ONLY_RESOLUTIONS = frozenset(
    {
        "rewrite",
        "reword",
        "claim_narrowing",
        "added_caveat",
        "added_limitation",
        "added_discussion",
        "better_wording",
        "clarification",
        "writing_only",
    }
)

EVIDENCE_RESOLUTIONS = frozenset(
    {
        "new_world_evidence",
        "new_valid_experiment",
        "replication",
        "baseline_improvement",
        "measurement_repair",
        "design_repair",
    }
)

REPAIR_DIMENSION = {
    "stronger_baseline": "baseline_strength",
    "broader_evaluation": "generalization",
    "measurement_redesign": "measurement_validity",
    "experiment_redesign": "experimental_adequacy",
    "causal_redesign": "mechanism_support",
    "more_evidence": "central_claim_support",
    "assumption_reframe": "technical_correctness",
    "representation_change": "technical_correctness",
    "project_pivot": "importance",
    "writing_only": "technical_correctness",
}


@dataclass(frozen=True)
class ReviewRecord:
    """A structured objection that is allowed to change the research plan."""

    review_id: str
    severity: str = "minor"
    dimension: str = "technical_correctness"
    objection: str = ""
    affected_claim: str = ""
    affected_design: str = ""
    repair_type: str = "writing_only"
    requires_new_evidence: bool = False
    status: str = "open"  # open | repairing | resolved | withdrawn | superseded
    question_id: str = ""
    theory_id: str = ""
    raised_at_tick: int = 0
    resolution_kind: str = ""
    resolution_evidence_id: str = ""
    resolved_at_tick: int = 0
    source: str = "reviewer_judgment_not_evidence"
    # An assessment records a judgment about a dimension no execution can
    # settle. It is not an objection, and it never corroborates a claim.
    assessment: str = ""
    supporting_refs: tuple[str, ...] = ()
    assessment_basis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "severity": self.severity,
            "dimension": self.dimension,
            "objection": self.objection,
            "affected_claim": self.affected_claim,
            "affected_design": self.affected_design,
            "repair_type": self.repair_type,
            "requires_new_evidence": bool(self.requires_new_evidence),
            "status": self.status,
            "question_id": self.question_id,
            "theory_id": self.theory_id,
            "raised_at_tick": int(self.raised_at_tick),
            "resolution_kind": self.resolution_kind,
            "resolution_evidence_id": self.resolution_evidence_id,
            "resolved_at_tick": int(self.resolved_at_tick),
            "source": self.source,
            "assessment": self.assessment,
            "supporting_refs": list(self.supporting_refs),
            "assessment_basis": self.assessment_basis,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "ReviewRecord":
        row = dict(payload or {})
        severity = str(row.get("severity") or "minor").lower()
        repair = str(row.get("repair_type") or "writing_only")
        dimension = str(row.get("dimension") or "technical_correctness")
        return cls(
            review_id=str(row.get("review_id") or row.get("id") or ""),
            severity=severity if severity in SEVERITIES else "minor",
            dimension=dimension if dimension in DIMENSIONS else "technical_correctness",
            objection=str(row.get("objection") or ""),
            affected_claim=str(row.get("affected_claim") or ""),
            affected_design=str(row.get("affected_design") or ""),
            repair_type=repair if repair in REPAIR_TYPES else "writing_only",
            requires_new_evidence=bool(row.get("requires_new_evidence")),
            status=str(row.get("status") or "open"),
            question_id=str(row.get("question_id") or ""),
            theory_id=str(row.get("theory_id") or ""),
            raised_at_tick=int(row.get("raised_at_tick") or 0),
            resolution_kind=str(row.get("resolution_kind") or ""),
            resolution_evidence_id=str(row.get("resolution_evidence_id") or ""),
            resolved_at_tick=int(row.get("resolved_at_tick") or 0),
            source=str(row.get("source") or "reviewer_judgment_not_evidence"),
            assessment=str(row.get("assessment") or "") if str(
                row.get("assessment") or "") in STATUS_RANK else "",
            supporting_refs=tuple(str(item) for item in row.get("supporting_refs") or []),
            assessment_basis=str(row.get("assessment_basis") or ""),
        )


def normalize_review(payload: Mapping[str, Any], *, tick: int = 0) -> dict[str, Any]:
    """Admit a proposed review into canonical form.

    ``requires_new_evidence`` is not a reviewer's opinion to hand out freely: any
    repair type other than pure presentation *is* an evidence-requiring
    objection, so the flag is forced true. A reviewer cannot mark a
    ``measurement_redesign`` as answerable by rewriting.
    """
    record = ReviewRecord.from_dict(payload)
    needs_world = record.repair_type not in PRESENTATION_REPAIRS
    if record.severity == "fatal":
        needs_world = True
    row = record.to_dict()
    if record.assessment and not record.objection:
        # A rating with no complaint attached is a judgment, not review debt.
        row["status"] = "resolved"
        row["requires_new_evidence"] = False
        row["resolution_kind"] = "assessment_recorded"
        row["review_id"] = row["review_id"] or f"assessment-{record.dimension}"
        return row
    row["requires_new_evidence"] = bool(record.requires_new_evidence or needs_world)
    row["raised_at_tick"] = int(payload.get("raised_at_tick") or tick or 0)
    if not row["review_id"]:
        row["review_id"] = f"review-{row['dimension']}-{row['raised_at_tick']}"
    return row


def resolution_admissible(
    review: Mapping[str, Any],
    *,
    resolution_kind: str,
    evidence_id: str = "",
    evidence_rows: Iterable[Mapping[str, Any]] = (),
) -> tuple[bool, str]:
    """Deterministic caveat-only guard.

    If an objection requires new evidence, prose cannot close it. Not a rewrite,
    not a narrower claim, not another caveat, not a new discussion section. The
    only admissible resolutions are new admitted WORLD evidence, a replication,
    a repaired measurement, a repaired design, or a stronger baseline — each
    identified by an evidence row that actually exists and actually promoted.
    """
    record = ReviewRecord.from_dict(review)
    kind = str(resolution_kind or "").strip().lower()
    if not record.requires_new_evidence:
        return True, ""
    if kind in CAVEAT_ONLY_RESOLUTIONS or not kind:
        return False, (
            f"caveat_only_repair_refused: {record.review_id} requires new evidence; "
            f"'{kind or 'unspecified'}' only changes the text"
        )
    if kind not in EVIDENCE_RESOLUTIONS:
        return False, f"unknown_resolution_kind:{kind}"
    eid = str(evidence_id or "")
    if not eid:
        return False, f"resolution_requires_admitted_evidence_id: {record.review_id}"
    row = next(
        (
            dict(item)
            for item in evidence_rows
            if str(item.get("evidence_id") or "") == eid
        ),
        None,
    )
    if row is None:
        return False, f"resolution_evidence_not_in_state: {eid}"
    if not (row.get("promotion_ok") and str(row.get("epistemic") or "") == "WORLD" and row.get("attested")):
        return False, f"resolution_evidence_did_not_promote_to_world: {eid}"
    admitted = row.get("admitted_at_tick")
    if isinstance(admitted, int) and admitted < record.raised_at_tick:
        return False, f"resolution_evidence_predates_objection: {eid}"
    return True, ""


def open_reviews(rows: Iterable[Mapping[str, Any]], *, severity: str = "") -> list[dict[str, Any]]:
    out = []
    for row in rows or []:
        record = ReviewRecord.from_dict(row)
        if record.status in {"resolved", "withdrawn", "superseded"}:
            continue
        if severity and record.severity != severity:
            continue
        out.append(record.to_dict())
    return out


def review_debt(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    rows = list(rows or [])
    return {
        "fatal_objections": len(open_reviews(rows, severity="fatal")),
        "major_objections": len(open_reviews(rows, severity="major")),
        "minor_objections": len(open_reviews(rows, severity="minor")),
        "evidence_requiring_objections": sum(
            1 for row in open_reviews(rows) if row.get("requires_new_evidence")
        ),
        "redesign_objections": sum(
            1 for row in open_reviews(rows) if row.get("repair_type") in REDESIGN_REPAIRS
        ),
        "pivot_objections": sum(
            1 for row in open_reviews(rows) if row.get("repair_type") in PIVOT_REPAIRS
        ),
    }


# --------------------------------------------------------------------------
# Quality projection
# --------------------------------------------------------------------------


@dataclass
class QualityDimension:
    name: str
    status: str = "unknown"
    blocking_reasons: list[str] = field(default_factory=list)
    supporting_refs: list[str] = field(default_factory=list)
    required_next_work: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "blocking_reasons": list(dict.fromkeys(self.blocking_reasons)),
            "supporting_refs": list(dict.fromkeys(self.supporting_refs)),
            "required_next_work": list(dict.fromkeys(self.required_next_work)),
        }


def _world_rows(state: Any) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in getattr(state, "evidence_records", []) or []
        if str(row.get("epistemic") or "") == "WORLD"
        and row.get("attested")
        and row.get("promotion_ok")
    ]


def _probe_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows if str(row.get("role") or "") == "ProbeEvidence"]


def _replication_possible(state: Any) -> bool:
    """Is there a heldout world a registered script could actually read?

    A run bound to a primary whose heldout shares no payload filename is asked
    for a replication no script can perform. Reporting that as "not attempted"
    invites another attempt; reporting it as impossible names what would fix it.
    """
    from pathlib import Path as _Path

    def payloads(row: Mapping[str, Any]) -> set[str]:
        skip = {"seed.json", "origin.json", "manifest.json"}
        return {_Path(str(name)).name for name in row.get("files") or []
                if _Path(str(name)).name not in skip}

    rows = list(getattr(state, "world_versions", []) or [])
    primary = next((row for row in rows
                    if str(row.get("id") or row.get("world_id") or "")
                    == str(getattr(state, "world_id", ""))), {})
    if not primary or not payloads(primary):
        return True
    for row in rows:
        if row.get("research_role") != "heldout":
            continue
        if not payloads(row):
            return True
        if primary.get("schema") == row.get("schema") and payloads(primary) & payloads(row):
            return True
    return False


def _min_sample(contract: ResearchContract) -> float:
    return float((contract.resource_limits or {}).get("min_sample_size") or 0)


def compute_quality(state: Any) -> dict[str, Any]:
    """Recompute the project's quality state from canonical facts only.

    Every branch here reads admitted evidence, recorded reviews, surveys, or the
    contract. Nothing reads a model's self-assessment.
    """
    contract = contract_from_state(state)
    reviews = list(getattr(state, "reviews", []) or [])
    world = _world_rows(state)
    probes = _probe_rows(world)
    surveys = [
        dict(row)
        for row in getattr(state, "artifacts", []) or []
        if row.get("kind") == "literature_survey" and row.get("works")
    ]
    theories = [dict(row) for row in getattr(state, "theories", []) or []]
    verified = dict(getattr(state, "verified_research_state", {}) or {})
    contradictions = list(getattr(state, "contradictions", []) or [])
    min_sample = _min_sample(contract)

    dims = {name: QualityDimension(name=name) for name in DIMENSIONS}

    def note(name: str, status: str, *, reason: str = "", ref: str = "", work: str = "") -> None:
        row = dims[name]
        if STATUS_RANK.get(status, 0) > STATUS_RANK.get(row.status, 0) or row.status == "unknown":
            row.status = status
        if reason:
            row.blocking_reasons.append(reason)
        if ref:
            row.supporting_refs.append(ref)
        if work:
            row.required_next_work.append(work)

    def force(name: str, status: str, *, reason: str = "", work: str = "") -> None:
        row = dims[name]
        row.status = status
        if reason:
            row.blocking_reasons.append(reason)
        if work:
            row.required_next_work.append(work)

    # -- literature coverage -------------------------------------------------
    if not surveys:
        force("literature_coverage", "missing", reason="no_verified_literature_survey",
              work="SURVEY")
    else:
        hypothesis_checked = {str(row.get("theory_id") or "") for row in surveys}
        substantive = [t for t in theories if t.get("role") != "competing_explanation"]
        unchecked = [str(t.get("id") or "") for t in substantive if str(t.get("id") or "") not in hypothesis_checked]
        if not substantive:
            note("literature_coverage", "partial", reason="survey_without_hypothesis_specific_check",
                 work="THEORIZE")
        elif unchecked:
            note("literature_coverage", "partial",
                 reason=f"hypotheses_without_literature_check:{len(unchecked)}", work="SURVEY")
        else:
            note("literature_coverage", "adequate",
                 ref=str(surveys[-1].get("id") or "literature_survey"))

    # -- technical correctness ----------------------------------------------
    # Only executed experiments speak to this. A descriptive observation carries
    # ``cannot_corroborate`` by construction — that is an honest label meaning
    # "this describes the dataset, it does not test the hypothesis", not a
    # validation failure — and reading it as a defect demanded a redesign of a
    # design that did not exist yet.
    # ``cannot_corroborate`` is set by several different causes, and most of them
    # are owned by a dimension that names them precisely. Counting them here too
    # charged one defect twice and reported it as a validation gap that was not
    # there — the live probe below had an empty ``validation_gaps`` and a missing
    # ablation, and this said "validation_gaps_on_1_evidence_rows".
    OWNED_ELSEWHERE = {
        "ablation_required": "baseline_strength",
        "object_absent": "baseline_strength",
        "dv_blind": "measurement_validity",
    }
    broken = [row for row in probes
              if row.get("validation_gaps")
              or (row.get("cannot_corroborate")
                  and not any(row.get(key) for key in OWNED_ELSEWHERE)
                  and row.get("world_consumed") is not False)]
    if not probes:
        force("technical_correctness", "unknown", reason="no_executed_experiment",
              work="PROBE")
    elif broken:
        gaps = sorted({str(gap) for row in broken for gap in row.get("validation_gaps") or []})
        force("technical_correctness", "weak",
              reason=("; ".join(gaps) if gaps else
                      f"{len(broken)}_evidence_rows_cannot_corroborate_for_an_unrecorded_reason"),
              work="REDESIGN")
    else:
        note("technical_correctness", "adequate", ref=str(world[-1].get("evidence_id") or ""))
    if contradictions:
        force("technical_correctness", cap(dims["technical_correctness"].status, "weak"),
              reason=f"unresolved_contradictions:{len(contradictions)}", work="VERIFY")

    # -- experimental adequacy (power / sample) ------------------------------
    if not probes:
        force("experimental_adequacy", "missing", reason="no_executed_experiment", work="PROBE")
    else:
        sized = [row for row in probes if row.get("sample_size") is not None]
        unsized = [row for row in probes if row.get("sample_size") is None]
        underpowered = [
            row for row in sized
            if min_sample and float(row.get("sample_size") or 0) < min_sample
        ]
        if underpowered:
            force("experimental_adequacy", "weak",
                  reason=(
                      f"underpowered:{len(underpowered)}_of_{len(probes)}_below_"
                      f"contract_min_sample_{min_sample:g}"
                  ),
                  work="REDESIGN")
        elif unsized:
            # A result whose power nobody reported is not an adequate result.
            # The repair is for the experiment to report how many units it
            # measured, which is a measurement change, not another design.
            refused = [row for row in unsized
                       if str(row.get("sample_size_basis") or "").startswith("refused")]
            force("experimental_adequacy", "weak",
                  reason=("reported_sample_exceeded_the_attested_world" if refused
                          else f"experiment_does_not_report_units_measured:{len(unsized)}"),
                  work="REDESIGN")
        else:
            note("experimental_adequacy", "adequate", ref=str(probes[-1].get("evidence_id") or ""))

    # -- baseline strength ---------------------------------------------------
    if not probes:
        force("baseline_strength", "missing", reason="no_control_arm_executed", work="PROBE")
    else:
        needs_ablation = [row for row in probes if row.get("ablation_required")]
        degenerate = [row for row in probes if row.get("object_absent")]
        if degenerate:
            force("baseline_strength", "missing",
                  reason="control_and_treatment_measured_nothing", work="REDESIGN")
        elif needs_ablation:
            force("baseline_strength", "weak",
                  reason="competing_mechanism_ablation_not_registered", work="REDESIGN")
        else:
            note("baseline_strength", "partial", ref=str(probes[-1].get("evidence_id") or ""))
            if any(row.get("mechanism_validated") for row in probes):
                note("baseline_strength", "adequate")

    # -- measurement validity ------------------------------------------------
    if not probes:
        force("measurement_validity", "missing", reason="nothing_measured", work="PROBE")
    else:
        blind = [row for row in probes if row.get("dv_blind")]
        inconsistent = [row for row in probes if row.get("claim_consistent") is False]
        if blind:
            force("measurement_validity", "missing",
                  reason="measure_does_not_respond_to_the_oracle", work="REDESIGN")
        elif inconsistent:
            force("measurement_validity", "weak",
                  reason="measured_quantity_is_not_the_claimed_quantity", work="REDESIGN")
        else:
            note("measurement_validity", "adequate", ref=str(probes[-1].get("evidence_id") or ""))

    # -- mechanism support ---------------------------------------------------
    mechanised = [row for row in probes if row.get("mechanism_validated")]
    if not probes:
        force("mechanism_support", "missing", reason="no_experiment", work="PROBE")
    elif not mechanised:
        force("mechanism_support", "weak",
              reason="positive_result_without_mechanism_validation", work="REDESIGN")
    else:
        note("mechanism_support", "adequate", ref=str(mechanised[-1].get("evidence_id") or ""))

    # -- robustness ----------------------------------------------------------
    if not probes:
        force("robustness", "missing", reason="no_experiment", work="PROBE")
    else:
        consumed = [row for row in probes if row.get("world_consumed") is True]
        unchecked = [row for row in probes if row.get("world_consumed") is None]
        if any(row.get("world_consumed") is False for row in probes):
            force("robustness", "missing",
                  reason="effect_not_separable_from_placebo_worlds", work="REDESIGN")
        elif consumed and not unchecked:
            note("robustness", "adequate", ref=str(consumed[-1].get("evidence_id") or ""))
        elif consumed:
            note("robustness", "partial")
        else:
            force("robustness", "weak", reason="no_placebo_or_sanity_separation", work="VERIFY")

    # -- replication / generalization ---------------------------------------
    replications = [row for row in probes if row.get("replication_of")]
    transferred = [row for row in replications if row.get("transfer_ok")]
    independent = [row for row in replications if row.get("independent_replication")]
    if not probes:
        force("replication", "missing", reason="nothing_to_replicate", work="PROBE")
    elif not replications:
        heldout = [row for row in getattr(state, "world_versions", []) or []
                   if row.get("research_role") == "heldout"]
        force("replication", "missing",
              reason=("no_heldout_world_can_host_the_registered_experiment"
                      if heldout and not _replication_possible(state)
                      else "no_heldout_replication_attempted"),
              work="ACQUIRE" if heldout and not _replication_possible(state) else "VERIFY")
    elif not transferred:
        force("replication", "weak", reason="replication_attempted_but_did_not_transfer",
              work="REDESIGN")
    else:
        note("replication", "adequate", ref=str(transferred[-1].get("evidence_id") or ""))
    if independent:
        note("generalization", "adequate", ref=str(independent[-1].get("evidence_id") or ""))
    elif transferred:
        note("generalization", "partial")
    elif probes:
        force("generalization", "missing",
              reason="single_world_result_does_not_generalize", work="VERIFY")

    # -- central claim support ----------------------------------------------
    aligned_ids = set()
    questions = (
        list(getattr(state, "open_questions", []) or [])
        + list(getattr(state, "resolved_questions", []) or [])
        + list(getattr(state, "partial_questions", []) or [])
    )
    for question in questions:
        if alignment_of_question(contract, question, known=questions).status in {"aligned", "instrumental"}:
            aligned_ids.add(str(question.get("id") or ""))
    live_theories = [row for row in theories if row.get("status") != "retired"]
    central_theories = [
        row for row in live_theories
        if row.get("role") != "competing_explanation"
        and (not aligned_ids or str(row.get("question_id") or "") in aligned_ids)
    ]
    central_verified = [tid for tid in verified if any(str(t.get("id") or "") == tid for t in central_theories)]
    if central_verified:
        note("central_claim_support", "adequate", ref=central_verified[0])
    elif any(str(row.get("theory_id") or "") in {str(t.get("id") or "") for t in central_theories}
             and row.get("outcome") == "supports" for row in probes):
        note("central_claim_support", "partial",
             reason="supported_but_not_promoted_to_verified", work="VERIFY")
    elif probes:
        force("central_claim_support", "weak",
              reason="no_supporting_evidence_for_a_root_aligned_claim", work="REDESIGN")
    else:
        force("central_claim_support", "missing", reason="no_evidence_for_the_root_question",
              work="PROBE")
    if live_theories and not central_theories:
        # Every hypothesis this project is still pursuing has left the root
        # question. Retiring one direction does not count: that is a project
        # that already changed direction, not one that needs to.
        force("central_claim_support", "missing",
              reason="all_active_hypotheses_drifted_from_the_root_question",
              work="PROJECT_PIVOT")

    # -- reviewer objections override upward-looking projections -------------
    for row in open_reviews(reviews):
        record = ReviewRecord.from_dict(row)
        name = record.dimension if record.dimension in dims else REPAIR_DIMENSION.get(
            record.repair_type, "technical_correctness")
        ceiling = {"fatal": "missing", "major": "weak", "minor": "partial"}[record.severity]
        target = dims[name]
        target.status = cap(target.status, ceiling)
        target.blocking_reasons.append(f"{record.severity}_review:{record.review_id}")
        target.required_next_work.append(_work_for_repair(record.repair_type))
        if record.severity == "fatal":
            central = dims["central_claim_support"]
            central.status = cap(central.status, "missing")
            central.blocking_reasons.append(f"fatal_review:{record.review_id}")

    # -- judgment dimensions: assessed, and only as far as their grounding ---
    # No execution settles novelty or importance, so a recorded judgment is the
    # only thing that can move them. A bare opinion is capped at ``partial``;
    # reaching ``adequate`` requires the judgment to cite literature this state
    # actually verified. An assessment is not an objection and does not need to
    # be open, but an open objection on the same dimension still caps it below.
    citations = {
        str(cite)
        for row in surveys
        for cite in list(row.get("citations") or []) + list(row.get("read_first") or [])
    }
    for name in JUDGMENT_DIMENSIONS:
        assessments = [
            row for row in reviews
            if ReviewRecord.from_dict(row).dimension == name
            and str(row.get("assessment") or "") in STATUS_RANK
        ]
        if assessments:
            best, refs = "unknown", []
            for row in assessments:
                grounded = [c for c in (row.get("supporting_refs") or []) if str(c) in citations]
                ceiling = "adequate" if grounded else "partial"
                proposed = cap(str(row["assessment"]), ceiling)
                if STATUS_RANK[proposed] > STATUS_RANK[best]:
                    best, refs = proposed, grounded
            dims[name].status = best
            dims[name].supporting_refs.extend(str(c) for c in refs)
            if not refs:
                dims[name].blocking_reasons.append(
                    "judgment is not grounded in verified literature; capped at partial")
        elif dims[name].status == "unknown" and not any(
            ReviewRecord.from_dict(row).dimension == name for row in reviews
        ):
            dims[name].required_next_work.append("REVIEW")
            dims[name].blocking_reasons.append("no_recorded_judgment_and_no_execution_can_supply_one")
    # Objections outrank assessments: a reviewer cannot rate away their own
    # unresolved complaint.
    for row in open_reviews(reviews):
        record = ReviewRecord.from_dict(row)
        if record.dimension in JUDGMENT_DIMENSIONS:
            ceiling = {"fatal": "missing", "major": "weak", "minor": "partial"}[record.severity]
            dims[record.dimension].status = cap(dims[record.dimension].status, ceiling)

    requirements = requirements_for(contract)
    gaps = [
        name for name, requirement in sorted(requirements.items())
        if not meets(dims[name].status, requirement)
    ]
    return {
        "rule": "ordinal-derived-quality-v1",
        "target_quality": contract.target_quality,
        "requirements": requirements,
        "dimensions": {name: dims[name].to_dict() for name in DIMENSIONS},
        "quality_gap": gaps,
        "quality_gap_size": len(gaps),
        "review_debt": review_debt(reviews),
        "basis": "derived_from_admitted_evidence_and_recorded_reviews_only",
    }


def _work_for_repair(repair_type: str) -> str:
    if repair_type in PIVOT_REPAIRS:
        return "PROJECT_PIVOT"
    if repair_type in REDESIGN_REPAIRS:
        return "REDESIGN"
    if repair_type == "stronger_baseline":
        return "REDESIGN"
    if repair_type == "broader_evaluation":
        return "VERIFY"
    if repair_type == "more_evidence":
        return "PROBE"
    return "SYNTHESIZE"


def quality_gap(state: Any) -> list[str]:
    quality = getattr(state, "quality", None)
    if isinstance(quality, Mapping) and "quality_gap" in quality:
        return [str(item) for item in quality.get("quality_gap") or []]
    return list(compute_quality(state).get("quality_gap") or [])
