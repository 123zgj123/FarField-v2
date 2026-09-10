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

---

## Round 6 — two mechanisms the runtime claimed and did not have

Analysis of where academic capability was actually constrained produced one
result worth stating plainly: **the obvious "get more data" answer was wrong.**

`ARCHITECTURE.md` recorded the missing piece as a broad learned transition
corpus. Testing the retriever showed why that would have been wasted work:

| current research state vs. a historical applicability condition | matched |
|---|---|
| identical | yes |
| case / whitespace difference | yes |
| paraphrase | **no** |
| more specific restatement | **no** |
| same meaning, different words | **no** |

Both sides are free text a model extracted from *different* papers. Requiring
byte equality is not a strict test, it is a test that never fires. Ten thousand
transitions would have changed nothing; the bottleneck was representational.

**Fix 1 — graded, negation-safe retrieval.** Normalized equality establishes
applicability. Same-polarity content-word overlap above threshold proposes it,
labelled `proposed` because lexical proximity is not applicability. Disagreeing
polarity is a contradiction and never a match, so the most dangerous available
false match — the same sentence with the opposite sense — is refused explicitly.
`known_failure_conditions` had been extracted since the beginning and read by
nothing; a transition recorded as failing under the present circumstances is now
excluded. A lane that falls back records the substitution instead of swallowing
it. Retrieval sits in GENERATED space upstream of the kernel, so its risk is
anchoring, not false evidence, and the labelling bounds it.

**Fix 2 — an acquisition recipe registry.** ACQUIRE supported exactly one gap
and failed closed on everything else, while seventeen attested worlds sat on
disk it had no way to bind. `no_acquisition_recipe` was the most common terminal
blockage in a run. Recipes now cover derivation from the attested parent and
binding of an already-attested catalog world whose own manifest declares what
the gap names. Nothing is fetched, nothing is synthesized, and no recipe reaches
the network — an operator-pinned URL with an expected source digest would be the
minimum for that, because letting a model name a URL lets it choose its own
evidence.

**The integrity tests caught the real hazard, and they were right.** With
binding enabled, two tests that assert auto mode does not invent observations
began to fail. Reading attested Iris bytes is not inventing an observation — but
*deciding for itself what the object of study is* is a scope decision, and a
wrongly matched world produces genuine WORLD evidence that answers a question
nobody asked. Scope belongs to the contract, so `world_selection` defaults to
`declared_only`; an unauthorised run blocks and reports which world would have
satisfied the gap. Both tests pass unchanged.

End-to-end, replay mode, same topic:

```
before  ACQUIRE blocked(no_acquisition_recipe) ... -> BLOCKED, nothing observed
after   ACQUIRE blocked(world_selection_not_authorised_by_contract)   [default]
        ACQUIRE acquired -> OBSERVE observed -> VERIFY verified       [authorised]
```

Tests: 1353 passing, up from 1311. Behavioural 8/8 and trajectory metrics
unchanged.

**What this says about the data question.** Executable worlds are the binding
constraint on academic capability, not papers and not trajectories — without a
world that can answer the question, `central_claim_support` can never leave
`missing` and `RESEARCH_READY` is unreachable. The useful next investment is
more recipe kinds and more attested worlds in domains people actually want to
study, not corpus volume. A transition corpus only starts paying back now that
the retriever can use one.

One thing deliberately not done: calibrating `novelty` and `importance` against
real acceptance decisions. That trains a predictor of acceptance, not of
scientific value, and would contradict the system's own rule that reviewer
judgment is not evidence.

---

## Round 7 — three bounded live runs

`gpt-5.6-sol`, verified served. Attested `fisher-iris` with `uci-letters` bound
as an explicit heldout. 12 model calls and 10 ticks per segment. Credentials
process-only from a key file outside the repository. Root question: *does petal
geometry separate iris species better than sepal geometry?*

Seven defects, every one present with a green suite, **three of them introduced
by earlier rounds of this same work**.

### Segment 1 — produced nothing, and was the most informative of the three

Zero hypotheses, zero experiments, dead at `BLOCKED` after eight ticks.

1. A failing action's own `ActionBlocked` changed a question's status, and
   status sat inside the slice that action declared it reads. **The failure
   unblocked its own retry.** This was a hole in Round 5's own fix.
2. The inert-repetition rule keyed on action type and target while ignoring the
   research lane, so **one lane's failure banned two lanes never tried**. Also
   Round 5's.
3. A grounded transition needs one retrieved paper to cite another. Keyword
   retrieval returned seven papers with no citation link among them, so the
   transition library was empty and the lane could only fail.

Defect 3 revises Round 6's conclusion. Retrieval was described there as limited
by corpus size; in fact both the matcher *and* the step that builds the corpus
were unusable, and no corpus would have helped while retrieval produced nothing
to match. Round 6 fixed the half it could see.

A fourth observation was recorded and not fixed: the anchor research state is
assembled from every retrieved paper with no relevance filter, so an iris
question was anchored to a paper on first-order conic optimisation. That needs a
relevance criterion, which is larger than this round.

### Segment 2 — reached a real experiment, and exposed four more

Generated a hypothesis with a competing explanation, ran a registered two-arm
probe (`treatment 0.2697`, `control 0.2652`), read the separation as
`uninformative` rather than positive, refused corroboration for a missing
ablation, recorded five structural objections including a fatal one, and stopped
at `BUDGET_EXHAUSTED` without claiming completion.

4. `technical_correctness` read *all* WORLD evidence, so a descriptive
   observation's honest `cannot_corroborate` — which means "this describes the
   dataset, it does not test the hypothesis" — counted as a validation failure
   and **a redesign was demanded before any design existed**.
5. REVIEW was eligible whenever a hypothesis and a survey existed, but the
   structural reviewer draws objections from executed probes. A tick was spent
   on a review that returned `no_new_objections`. Its precondition is now the
   reviewer's own output, so the check and the executor cannot drift apart.
6. One unablated result raised two objections, one with an empty body.
7. **No worker anywhere reported a sample size.** `experimental_adequacy`
   demands one, so the dimension could never leave `weak`, redesign would have
   been demanded forever, and `RESEARCH_READY` was unreachable for reasons that
   have nothing to do with the science — a quality bar that existed and could
   not be met. This was Round 1's, and it took a live run to notice.

### Segment 3 — verified all four fixes, and found the half-fix in 6

No redesign before an experiment. One review instead of a wasted one. No
empty-bodied objection. `experimental_adequacy` reached `adequate` from a sample
the experiment reported itself — `n_treatment` and `n_control` both 150, inside
the attested world's bound of 150.

| | segment 1 | segment 2 | segment 3 |
|---|---|---|---|
| hypotheses | 0 | 1 + competitor | 1 + competitor |
| experiments | 0 | 1 | 1 |
| objections recorded | 0 | 5 | 4 |
| `experimental_adequacy` | — | weak (unreachable) | **adequate** |
| quality gap | 7 dimensions | 4 | **1** |
| ending | `BLOCKED` | `BUDGET_EXHAUSTED` | `BUDGET_EXHAUSTED` |

Segment 3's probe returned a **positive** result — petal geometry separating
iris species, which is the known answer — and the runtime still refused to
corroborate it, because the competing mechanism was not ablated.
`mechanism_validated` stayed false, `central_claim_support` stayed `partial`,
the review recorded "a positive arithmetic result is not a verified mechanism",
and the segment ended `research_complete: false`. A live positive result on a
question with a known answer did not become a finding. That is the single
observation in this whole report that most needed a live run to produce.

It also showed defect 6 had only been half fixed: the reviewer stopped
duplicating, but the quality projection still charged one unablated result to
both `baseline_strength` and `technical_correctness`, reporting the second as
`validation_gaps_on_1_evidence_rows` when that row's gaps were empty. Recomputed
against the real segment-3 state after the fix, the quality gap falls from two
dimensions to one, and the remaining one is the ablation that is genuinely
missing.

Also found while checking coverage: `tests/regressions/` had no `__init__.py`,
so the documented main discovery command had been silently skipping the entire
directory — including the caveat-only-repair regression, the invariant this
whole effort rests on.

Tests: 1391 passing, up from 1353. Behavioural 8/8 and long-horizon trajectory
metrics unchanged.

### Status change

The project-management, retrieval and acquisition layers are no longer
*offline validated only*. Three bounded segments exercised the contract, quality
state, review, redesign, resource and termination paths against a real model and
a real attested world. What remains unvalidated live: PROJECT_PIVOT, heldout
replication transfer, and any run long enough to test goal maintenance across
tens of actions — every segment here ended on budget at ten ticks.
