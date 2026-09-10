# Architecture audit

Target: a *Verified Self-Evolving Open-World Research Runtime* — one control
loop, one canonical state, evidence admitted only by the Trusted Kernel,
Discovery and Harness RSI able to widen the search and sharpen the method but
never to change what counts as true.

Everything below was measured on the current tree, not read off documentation.
Each finding names how it was checked. No code was changed in producing it.

---

## 1. Who owns next-action authority

**OpenWorld does, and nothing else calls it.**

`runtime.py:256` holds the only `env.tick()` in the repository. `tick()` is the
sole path from state to action:

```
eligible_actions(state) → admissible(state, actions) → schedule(state, pool)
    → execute(action) → _admit(action, candidate) → apply_events(...)
```

Every other caller of `env.execute(...)` is an evaluation harness
(`benchmark.py`, `capabilities.py`), never a second controller.

**Verdict: clean.** There is one next-action authority.

## 2. Is there still a legacy pipeline

**It exists in the tree; it controls nothing.**

`extras/mission.py` is 6,734 lines and contains `run_mission` with its own stage
sequence (`generate`, `diagnose`, `probe`, `writeup`, `intern`). Measured:

- `run_mission` is called from **no entry point** — the only occurrence outside
  its own file is a docstring in `campaign.py`.
- Exactly **one** symbol from mission.py is imported anywhere else:
  `resolve_production_corpus`, used twice in `cli.py`.
- The research runtime never imports mission.

So this is not a competing controller to migrate away from. It is ~272KB of
unreachable stage logic plus one live helper. The work is extraction and
deletion, not migration — and it is lower risk than it looks.

## 3. Is there more than one canonical state

**No.** An AST sweep of every class on the research path for research-state
fields (`theories`, `evidence_records`, `open_questions`, …) returns exactly
one: `ScientificState`, 41 fields. The only other hit, `MoveCredit.hypotheses`,
is a local scoring struct with no persistence.

The separations the target requires hold:

| | relation to state |
|---|---|
| `WorldVersion` | referenced by id + digest; bytes live on disk |
| `HarnessVersion` | separate store, stamped onto state as a version string |
| `Archive` | separate store |
| `Notebook` | **derived** — `notebook_projection(state)`, one direction |
| Mission stage | does not exist on the live path |

**One gap.** `sync_from_notebook` writes *back* into state when the state file
is empty and a notebook exists. It is the only notebook→state direction and it
is bootstrap-only, but it means the notebook is not purely a projection at all
times.

## 4. Which actions are interface without real execution

Measured per action: executor size, whether it can produce evidence, whether a
worker overrides it, and whether it has ever produced an event in a live run.

| action | executor | evidence | live | assessment |
|---|---|---|---|---|
| OBSERVE | 184 lines | yes | yes | real; reads world, emits QuestionEvidence |
| ACQUIRE | 203 lines | yes | **no** | **real but never exercised live** (see below) |
| THEORIZE | 62 + worker | – | yes | real |
| PROBE | 34 + worker | yes | yes | real |
| VERIFY | 61 + worker | yes | yes | real |
| SURVEY | 6 + worker | – | yes | real (worker does the work) |
| SYNTHESIZE | 33 + worker | – | yes | real |
| REVIEW | 30 lines | – | yes | real |
| REDESIGN | 95 lines | – | yes | real |
| REFLECT | 43 lines | – | yes | real |
| ARCHIVE | 22 lines | – | yes | real |
| PROJECT_PIVOT | 48 lines | – | **no** | real, offline-validated only |
| ASK | 19 lines | – | no | real; bootstraps the first question only |
| **FORK_LINEAGE** | 27 lines | – | yes | **interface without the thing it names** |
| EVOLVE_HARNESS | 0 | – | no | handled by `OpenWorld.evolve`, proposes only |

**ACQUIRE is real.** Tested directly: with `world_selection: catalog_match`
authorised it acquired `openevolve-fnmin-s11`, wrote `origin.json` and
`world.json` to disk, and emitted `WorldCreated` with digest `2430ba07…`
against a parent digest of `e2c14d30…`. That is a genuine W0→W1 artifact delta,
not a copy with new metadata. It has never run in a live mission because no
live contract authorised catalog matching.

**FORK_LINEAGE is not.** It emits `LineageForked` carrying *lane name strings*,
which land in `state.active_lineages`. `fork_trajectories` does build branch
objects — and they are returned in `extras` and discarded. There is no
independent per-branch state, event buffer, or budget. `merge_branches` exists
and is called only by a backward-compatible wrapper that the loop never
invokes. In `ws-rsi` this produced nine "lineages" that are quality-dimension
labels. This is the largest interface-without-implementation gap in the system.

## 5. Which semantics are defined in more than one place

One subsystem has been converged; seven have not. Counted as "how many places
must agree for one name to work":

| vocabulary | places | where |
|---|---|---|
| world measures/levers (`program_state`) | **1** | one registry object |
| world levers (7 other schemas) | 2 | static tuple + `apply()` if/elif |
| event types | **4** | `EVENT_TYPES`, reducer if/elif, emitters, `DECLARED_UNEMITTED` |
| state fields | **4** | dataclass, `to_dict`, `from_dict`, reducer writers |
| action types | 3 | `SPECS`, `DEFAULT_EXECUTORS`, worker `executors()` |
| research operators | 3 | `RESEARCH_OPERATORS`, `reframe.OPERATORS`, `default_moves` |
| quality dimensions | 3 | `DIMENSIONS`, `compute_quality`, repair vocabulary |
| scheduler weights | 2 | `RESEARCH_WEIGHTS`, `_research_score` |

Two of these four-place entries include an audit table added to detect drift —
`DECLARED_UNEMITTED` is itself one of the four places that must now agree.
Detection was added where definition should have been merged.

## 6. Which advertised capabilities are actually unusable

Checked by running every advertised lever on every world at full intensity and
asking whether any advertised observable moved.

```
levers that move something : 39
levers that move nothing   : 2
    zachary-karate    rewire   (undirected_graph)
    tcp-linux-server  rewire   (symbolic_trace)
```

Both live in schemas that still use the two-place pattern. **Their cause is not
the same as the registry defects**, and the difference matters:

- `freeze_validators` (fixed) wrote a field **no observable reads** —
  `IMPLEMENTATION_INERT`.
- These two rewire the graph or trace genuinely; the world's observables are
  too coarse to see it — `MEASUREMENT_BLINDNESS`.

The runtime already reports the second honestly: `stop_reason: plateau`,
`room_to_move: false`, *"observables did not move; the prediction has no
trajectory here."* So no false null is produced. The cost is wasted budget: a
hypothesis can be built on such a lever and only discover at execution that
nothing can be measured.

**No capability advertised by the register is unusable.** All 22 entries have
executable probes and 20/22 fire; 2 are `partial` with stated limits.

## 7. Which experiments carry undeclared randomness

**Now: none on the research path.** An AST sweep for global-RNG calls
(`random.choice/shuffle/sample/...` on the module generator) and for
`list({...})` feeding an index returns zero hits.

**It did, until this week.** `_lever_graph`'s rewire built its pool as
`list({...})` and indexed into it with a seeded `choice`: the generator was
reproducible and the set's iteration order was not. Three runs of an identical
script returned three different graphs and three different `report_digest`
values — and `report_digest` is recorded as evidence provenance. Fixed with
`sorted()`; in-process and cross-process replay tests now cover it.

`make_event` is pure — no wall clock, no uuid — so the event log is
content-reproducible.

**Gap against the target:** stochastic executors are not *declared* as such.
There is no `stochastic=true / seed / sampling protocol / replication criterion`
field on an executor or a protocol. Determinism is currently a property that
holds and is spot-checked, not a contract each executor states.

## 8. Which state mutations bypass the TrustedReducer

An AST sweep for assignments and in-place mutations of `ScientificState` fields
outside `state.py`/`reducer.py` finds 16. Classified:

| site | count | verdict |
|---|---|---|
| `progress.py` (`update_metrics`, contradiction append) | 2 | **not a bypass** — called *by* the reducer (`reducer.py:409`) |
| `runtime.py` bootstrap, `__init__.py` load/baseline | 12 | bootstrap before the loop; captured in `log.baseline` |
| `lifecycle.py` (`self.failed_designs`, `self.missing_capabilities`) | 2 | a different class's own fields — false positive |

**No executor writes state.** The `_admit` boundary is the only path in, and it
applies identically whether a worker returns `candidate.evidence` or an
`EvidenceAdded` event — pinned by regression.

**Real gap:** bootstrap sets `goal`, `world_id`, `world_versions` and
`harness_version` by direct assignment rather than by emitting events. Replay
reproduces them only because `log.baseline` snapshots the post-bootstrap state.
The rule "all state changes go through Event → Reducer" therefore holds for the
loop and not for bootstrap.

---

## What this audit changes about the plan

Three things are better than the brief assumes:

1. **There is already exactly one controller and one canonical state.** No
   migration is needed for §2 and §3 — only deletion of unreachable stage code.
2. **ACQUIRE is real.** §8's "不能只复制 W0 加 metadata" is already satisfied;
   what it lacks is a live exercise, not an implementation.
3. **Undeclared randomness on the research path is now zero.** §7's remaining
   work is making determinism a *declared contract* rather than finding more
   violations.

Three are worse or more specific:

1. **FORK_LINEAGE is a name, not a branch.** §15 is a build, not a fix.
2. **Event types and state fields are four-place definitions** — worse than the
   subsystem already converged, and two of the four places are audit tables I
   added. §5 should start here.
3. **The two inert levers are `MEASUREMENT_BLINDNESS`, not implementation
   defects.** §6's five-way distinction is needed to avoid "fix" meaning
   "delete a lever that a better-instrumented world could use".

## Order of work implied by the evidence

| # | work | risk | why this order |
|---|---|---|---|
| 1 | `WorldSchemaSpec` for the 7 remaining schemas | low | pattern proven on `program_state`; clears both inert levers |
| 2 | Capability state machine §6 (`SCHEMA_CAPABLE` … `SCIENTIFIC_EFFECT`) | low | must precede any lever pruning, or a true null gets deleted as a defect |
| 3 | `EventSchema`: 4 places → 1 | **high** | touches the Trusted Kernel; snapshot behaviour first |
| 4 | Executor determinism contract §7 | medium | declare `stochastic`, seed, replication per executor |
| 5 | Real `FORK_LINEAGE` §15 | medium | branch state, buffer, budget, merge/contradiction |
| 6 | Extract `resolve_production_corpus`, delete `run_mission` | low | 272KB of unreachable stage logic |
| 7 | `ResearchOperatorSpec`: 3 places → 1 | low | deletes the contract test that currently guards the split |

Items 1 and 2 are coupled and should land together: pruning a lever without the
capability state machine is exactly the "提前偷看科学结果" the brief forbids.
