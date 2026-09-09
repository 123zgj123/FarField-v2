# Iteration report: from research operations to research project management

Baseline before this work: 1218 unit/contract/regression tests passing, 1/8
behavioural research scenarios passing, no long-horizon evaluation.

Current: 1311 tests passing, 8/8 behavioural scenarios, 16 long-horizon
trajectory guarantees, and a capability-metric harness.

Everything below is **offline validated**. No live model run has been performed
in this work; see *Remaining limitations*.

---

## Architecture reconstruction (before any code changed)

Tracing the real call chain confirmed the control plane was already correct:
`OpenWorld.tick()` is the only next-action authority, the reducer is the only
state writer, workers only return candidates. That skeleton did not need
replacing. What it lacked was anything to *decide with*.

Mechanisms that existed and changed no decision:

| Mechanism | Existed | Changed the next decision? |
|---|---|---|
| `budget_ok` / `spent_cost` | yes | **no** — both metric keys were read and never written |
| `review.py` | yes | **no** — reachable only from `mission.py` |
| `project_for()` context projection | yes | **no** — computed per action, read by no worker |
| `goal_drift` metric | yes | **no** — graph reachability, true for anything under the goal |
| `FORK_LINEAGE` | yes | **barely** — emitted lane names no later tick could act on |
| `merge_branches` | yes | **no** — no live caller in the runtime |
| termination | yes | **weak** — seven outcomes collapsed into `research_complete: False` |
| quality / review debt / redesign / pivot | **no** | — |

---

## Round 1 — state representation

`ResearchContract` (`contract.py`), `ResearchQualityState` + `ReviewRecord`
(`quality.py`), `ResourceState` (`resources.py`); all event-sourced and
replay-derived.

- The root question is immutable inside a project; a rewrite is refused by the
  reducer and recorded as `contract_change_refused`.
- Quality is 12 ordinal dimensions derived from admitted evidence and recorded
  reviews. No `accept_probability`. A worker cannot assert its own rating.
- Resource spend is derived from `measured_cost` already on admitted events, so
  `budget_ok` refuses something for the first time.

## Round 2 — control semantics

`REVIEW` / `REDESIGN` / `PROJECT_PIVOT` as first-class actions with
deterministic default executors, so the control loop is exercisable offline.
Progress split into activity / operational / epistemic / research with two
independent clocks, and `strategic_stagnation` that fires while every tick is
still succeeding.

**Caveat-only repair invariant**: an objection requiring new evidence cannot be
closed by prose. The reducer refuses the resolution, keeps the objection open
and counts the refusal (`tests/regressions/test_caveat_only_repair.py`).

## Round 3 — decision policy

Behavioural benchmark first: **1/8**, and seven of the eight failures chose
`OBSERVE`. One mechanism, not eight bugs.

The scheduler scored actions from a table of per-action-type constants. It was
given a research-decision layer reading the contract, quality state, review debt
and resources, and — critically — the principle that repair attempts have
diminishing returns, so two spent redesigns make a pivot worth more than a
third. Result: **8/8**. The layer is inert without a recorded contract, so
legacy runs schedule exactly as before.

## Round 4 — long-horizon trajectories

Six defects that only a 30-action run exposes, all found with a full green
suite:

1. `apply_events` / `rebuild_state` recomputed `debt` *after* the project views,
   silently erasing goal-drift detection.
2. The scheduler's filters dropped eligible actions with **no record**. One null
   `experiment_proposal` removed every `PROBE` for an entire run while the tick
   view still reported `PROBE` eligible. Filtering now returns reasons.
3. `refresh_research_views` overwrote `retired` back to `supported`, resurrecting
   abandoned directions and producing a PIVOT→REDESIGN→PIVOT livelock.
4. After a pivot every hypothesis is retired, so quality read "all hypotheses
   drifted" and demanded another pivot — self-triggering.
5. `ActionBlocked` counted as productive output, so a repeatedly failing action
   always looked useful.
6. A project that could execute nothing reported `RESEARCH_INCOMPLETE` rather
   than `BLOCKED`, hiding that it was waiting on a capability.

## Round 5 — every action must inform something

Attribution over a 30-action run: **18 of 30 actions changed nothing.** Two root
causes, not eighteen.

**Cause A — the retry guard never worked.** `action_input_key` hashed the whole
state, so any unrelated change made a just-failed action look untried. The key
now derives from `ActionSpec.reads` — the inputs each action already declares.
A blocked `OBSERVE` retries when the world changes, not when a theory appears.

**Cause B — actions that structurally cannot inform anything.** `REFLECT` and
`ARCHIVE` were stub executors emitting no events at all: they always reported
success and were incapable of changing state. `REFLECT` now records reusable
failure lessons (with *applies when* / *does not apply when*, so one failure
does not become a permanent taboo) and raises an anomaly when a signature
repeats. `ARCHIVE` records what it closed. `FORK_LINEAGE` is refused when its
own lanes are already directly on the menu.

Above both sits one general rule replacing a family of special cases: **an
action that has twice returned the same outcome while admitting nothing has
established that fact**, and is refused until a pivot changes the situation.

Measurement was corrected in the same round, because under-crediting real work
is the same error as over-crediting idling: advancing a dimension short of the
contract bar, discovering a serious flaw, and learning that a design fails all
count as research progress — each exactly once.

One over-correction was caught and reversed inside the round: excluding
`ArtifactAdded` from "admitted anything" made `SURVEY` look inert, truncating
the run and *lowering* evidence yield. Counting a survey's artifact restored it.

---

## Behavioural evaluation

Deterministic offline decision scenarios (`benchmark.py`):

| | before | after |
|---|---|---|
| A underpowered positive result | fail — called it progress | pass — REDESIGN |
| B fatal reviewer objection | fail | pass — refuses the caveat, redesigns |
| C peripheral progress trap | fail | pass — strategic stagnation rises |
| D dead end, budget left | fail | pass — PROJECT_PIVOT |
| E dead end, no budget | fail | pass — no new front opened |
| F goal drift | fail | pass — drift named as the blocker |
| G consensus is not evidence | pass | pass |
| H clean project restart | fail | pass — evidence and contract survive |

Long-horizon trajectories against a scripted world, 30 actions:

| metric | before round 5 | after |
|---|---|---|
| idle actions (recoverable) | 18 / 30 | **7 / 30** |
| decision-relevant evidence | 2 | **6** |
| resource efficiency | 0.067 | **0.20** |
| experiments reached | 1 | **3** |
| idle actions (dead project) | 14 / 30 | **9 / 30** |
| pivot on a dead direction | never | action 9 |

---

## Remaining limitations

- **Offline validated only.** No live model or live world run was performed.
  The trajectory world is a deterministic script; it measures how the controller
  allocates actions, not whether the resulting science is any good.
- Root-question alignment is a **lexical anchor guard**, not semantic
  understanding. It cannot tell that two phrasings share an estimand; it is
  conservative and asks for a justification rather than accepting silently.
- The structural reviewer only raises objections the state already proves. It
  does not assess novelty or importance beyond a literature prior check, and a
  judgment not grounded in verified literature is capped at `partial`.
- Quality dimensions are ordinal bookkeeping. They are not calibrated against
  any real acceptance decision and must not be read as one.
- Efficiency thresholds in the long-horizon tests are floors measured against
  the current controller, not targets derived from anything external.
- `merge_branches` remains without a live caller in the runtime.
