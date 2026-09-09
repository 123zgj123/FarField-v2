"""Resource accounting the scheduler can actually read.

Before this module the scheduler asked ``metrics["spent_cost"]`` against
``metrics["budget_cap"]`` — and nothing in the runtime ever wrote either field.
The budget filter was dead code, the token ledger lived inside the LLM client
where no research decision could see it, and wall-clock was recorded per action
and then dropped. An agent that cannot see its own remaining budget cannot
choose between "run the decisive experiment" and "open a new branch".

Everything here is derived by replay from ``measured_cost`` already stamped on
admitted events, so resumed sessions and rebuilt states agree.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


METERS = ("api_calls", "tokens", "wall_seconds", "probe_runs", "ticks")

DEFAULT_LIMITS: dict[str, float] = {}


def _limits(contract_limits: Mapping[str, Any] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, value in dict(contract_limits or {}).items():
        if name in METERS and isinstance(value, (int, float)) and not isinstance(value, bool):
            out[str(name)] = float(value)
    return out


def spend_from_events(rows: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    """Sum the costs that were actually measured, never estimated."""
    spent = {name: 0.0 for name in METERS}
    for row in rows or []:
        cost = row.get("measured_cost")
        if not isinstance(cost, Mapping):
            continue
        spent["tokens"] += float(cost.get("tokens") or 0)
        spent["wall_seconds"] += float(cost.get("wall_seconds") or 0)
        spent["api_calls"] += float(cost.get("api_calls") or 0)
    return spent


def compute_resources(state: Any) -> dict[str, Any]:
    """Canonical resource view: limits, measured spend, remaining, pressure."""
    from .contract import contract_from_state

    contract = contract_from_state(state)
    limits = _limits(contract.resource_limits)
    attempts = [
        dict(row)
        for row in getattr(state, "artifacts", []) or []
        if row.get("kind") == "action_attempt"
    ]
    evidence = [dict(row) for row in getattr(state, "evidence_records", []) or []]
    spent = spend_from_events(attempts)
    # Evidence rows carry their own measured cost; count each EvidenceID once so
    # a re-admitted verification update is not billed twice.
    seen: set[str] = set()
    for row in evidence:
        eid = str(row.get("evidence_id") or "")
        if eid and eid in seen:
            continue
        if eid:
            seen.add(eid)
    spent["api_calls"] = spent["api_calls"] or float(len(attempts))
    spent["probe_runs"] = float(
        sum(1 for row in attempts if row.get("action_type") in {"PROBE", "VERIFY"})
    )
    spent["ticks"] = float(int(getattr(state, "ticks", 0) or 0))

    remaining: dict[str, float] = {}
    fractions: dict[str, float] = {}
    for name, cap in limits.items():
        used = float(spent.get(name) or 0)
        remaining[name] = max(0.0, cap - used)
        fractions[name] = min(1.0, used / cap) if cap > 0 else 0.0
    pressure = max(fractions.values()) if fractions else 0.0
    exhausted = sorted(name for name, value in fractions.items() if value >= 1.0)
    return {
        "rule": "measured-spend-v1",
        "limits": limits,
        "spent": {name: round(float(spent.get(name) or 0), 6) for name in METERS},
        "remaining": {name: round(value, 6) for name, value in sorted(remaining.items())},
        "fraction_used": {name: round(value, 6) for name, value in sorted(fractions.items())},
        "budget_pressure": round(pressure, 6),
        "exhausted": exhausted,
        "basis": "measured_cost_from_admitted_events_not_estimates",
    }


def budget_state(state: Any) -> dict[str, Any]:
    raw = getattr(state, "resources", None)
    if isinstance(raw, Mapping) and raw.get("rule"):
        return dict(raw)
    return compute_resources(state)


def affordable(state: Any, *, cost: Mapping[str, float] | float = 0.0) -> bool:
    """Would this action's estimated cost cross a hard contract limit?

    Estimated cost is a spec constant, not a measurement. This only refuses
    actions that would exceed an explicitly declared limit.
    """
    budget = budget_state(state)
    limits = dict(budget.get("limits") or {})
    if not limits:
        return True
    if budget.get("exhausted"):
        return False
    if isinstance(cost, Mapping):
        for name, value in cost.items():
            cap = limits.get(str(name))
            if cap is None:
                continue
            if float(budget["spent"].get(str(name)) or 0) + float(value) > cap:
                return False
        return True
    cap = limits.get("api_calls")
    if cap is None:
        return True
    return float(budget["spent"].get("api_calls") or 0) + float(cost) <= cap


def budget_phase(state: Any) -> str:
    """Coarse ordinal phase. Not a prediction of how much work remains.

    ``opening``  plenty of room: exploration and new branches are cheap.
    ``working``  normal.
    ``closing``  most of the budget is gone: prefer the decisive test over a
                 new lineage.
    ``exhausted`` nothing left to spend.
    """
    budget = budget_state(state)
    if not budget.get("limits"):
        return "unmetered"
    if budget.get("exhausted"):
        return "exhausted"
    pressure = float(budget.get("budget_pressure") or 0)
    if pressure >= 0.75:
        return "closing"
    if pressure >= 0.3:
        return "working"
    return "opening"
