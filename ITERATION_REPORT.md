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

---

## Round 8 — audit, cleanup, and a register that can fail

A full static audit of 116 modules (import reachability, AST reference counting,
event/action contract reconciliation) plus reading three real auto-research
systems.

### What the audit found

**One dead capability.** `state.contradictions` had exactly two writers: a
`ContradictionDetected` event no code emitted, and a branch-merge helper with no
live caller. Twelve consumers read it — contradiction debt, VERIFY eligibility
and kind, SYNTHESIZE eligibility, `blocked_descendants`, contradiction-resolution
progress and rate, the belief refresh's "unresolved contradictions keep the
mechanism speculative" rule, quality's technical-correctness cap, the readiness
gate `no_critical_unresolved_contradiction`, and the decision journal. All
twelve read a list that could not fill. **A gate guarding a condition that
cannot arise reads as permanently satisfied**, which is worse than no gate.

Contradictions are now derived from canonical evidence: two independently
admitted WORLD rows about one hypothesis, on different experiment identities,
pointing opposite ways. Explicitly reported contradictions still come through the
event and survive the derived pass.

**Seven dead reads in decision paths**, each a decision resting on a value that
never arrives:

| Field | Effect | Resolution |
|---|---|---|
| `spent_cost`, `budget_cap` | the budget branch could not be false | removed; measured spend is the check |
| `high_impact`, `source_count` | high-impact verification debt unraisable | computed from state as `sole_support` |
| `working_archive` | `archive_debt` always zero | removed; it is not computable from state |
| `causal_identification_ready` | a second probe-readiness path nothing supplied | removed |
| `valid_in_worlds` | archive cross-world projection always fell back | written where transfer is established |
| `produced_by` | a graph edge never generated | removed |
| `raised_after_tick` | "evidence must not predate the objection" never fired | evidence now carries `admitted_at_tick` |

Three of these were introduced by earlier rounds of this work.

**Sixteen of thirty-nine event types are never emitted**, though the contract is
closed in the dangerous direction: nothing is emitted that the reducer drops.
**Thirty-four functions are defined and never referenced**, six in the control
plane, two of them left by this work.

**About a quarter of the codebase does no work on any product path.** Eleven
modules (~3,500 lines) are unreachable from every entrypoint, including a v1/v2
evaluation stack whose own docstring calls it "the baseline the v2 generator must
beat" — with no entrypoint anywhere that runs the comparison. A further eleven
modules (~10,900 lines) are reachable only because `cli.py` imports one helper
from `mission.py`. One of them, `extras/state.py`, still described itself as *"the
single long-term memory of the production path"* after leaving that path; that
docstring is corrected, since a stale claim of authority is how two stores come
to be believed at once. The dead-module removal is left as an explicit decision
rather than taken unilaterally.

### The structural fix: a register that can fail

Every defect above shares one shape — a claim that outlived its implementation,
described in prose, believed, never asked to demonstrate itself. Fixing them
one at a time does not stop the next one.

`capabilities.py` makes the class machine-checkable. Each of seventeen
capabilities carries the module that performs it, the test that guards it, and an
**executable probe that builds a real state and asserts the mechanism fires**.
A capability claiming `implemented` without a probe is itself a failing entry;
`partial` and `absent` must state their limits. The enforcing test also asserts
that the audit *can* fail, because a check that cannot fail is the thing being
prevented.

Thirteen probes fire, three capabilities are `partial` with stated limits, and
the pivot probe was added when the first version of the register let an
`implemented` claim pass unchecked — the register catching its own instance of
the defect it exists to catch.

### What the reference systems contributed

Three were readable. `apexin-ai/agent-ml-research` is private; access was
supplied. "Microsoft Argus" could not be found — the nearest Microsoft system
located was **Magentic-One** on AutoGen (an outer-loop manager holding a task
ledger, inner-loop specialists), and no claim is made here about a system that
could not be verified to exist.

**apexin-ai/agent-ml-research** — a production SaaS (268 MB, EKS/Terraform/
payments) around ML research agents. Its `agent_ml_shared/contracts/` package is
the strongest idea encountered: every contract is a Markdown file whose YAML
frontmatter declares `authority: normative`, `status: implemented`, and a
`scope:` listing the implementation files **and its own enforcing test**. Its
`EXPERIMENT_STATE.md` states authority per runtime mode in a table — exactly the
ambiguity FarField had between ScientificState, the notebook, and
`extras/state.py`. **Adopted**: the contract shape, in `contracts/`, with the
addition that `live_path` is executable rather than a file reference. Also noted
and not adopted: `immutable_image.py` pins experiments to a container image;
FarField pins source and world digests but not the execution environment.

**dualverse-ai/station** — an open-world multi-agent research environment with
published mathematical discoveries. Two things it does that FarField does not:

1. **It scopes itself honestly.** "Station is suitable for tasks that meet two
   conditions: *scorable* — each run can be evaluated with a clear score; *fast
   iteration* — each run finishes within roughly two hours." FarField accepts an
   arbitrary topic and then fails closed. Station's precondition is the more
   useful contract.
2. **The evaluator is per-task code**, not a generic heuristic —
   `research/evaluators/evaluator.py` beside `baseline.yaml` and
   `research_task.md`. Its **breakthrough detector** is canonical, deterministic,
   persisted, and consumed by stagnation, lineage evolution and reporting alike,
   with an explicit `BREAKTHROUGH_EPS` and reconstruction on restart. FarField's
   quality state is twelve generic ordinal dimensions with **no task-defined
   score**, so it has no notion of a breakthrough at all.

   Station's stagnation escalates through levels on 320 ticks without a
   breakthrough and assigns lanes — Exploration, Exploitation, Revival,
   Understanding, Strategy. FarField's `LANES` constant is *the same five lanes*
   minus Strategy, which suggests shared lineage; but FarField's fork does not
   run parallel branches, while Station's multistart genuinely forks seeds at
   init and at stagnation and selects among them.

   **Not adopted this round.** A per-task evaluator and real parallel multistart
   are the two largest genuine capability gaps, and both are substantial enough
   that claiming them without building them would repeat the exact defect this
   round exists to remove.

**wanshuiyin/Auto-claude-code-research-in-sleep (ARIS)** — 82 Markdown skills,
no framework. Two ideas worth recording: its guide states *"This file is a
routing index, not a specification... if this guide conflicts with a SKILL.md,
the SKILL.md wins"* — a declared conflict-resolution rule between documents,
which `contracts/README.md` now mirrors. And it records **reviewer
independence** on the acceptance record: a same-model-family review is stamped
`review_independence: same-family`, `acceptance_status: provisional`, and *"never
describe base Codex self-review as cross-model acceptance."* FarField's
`ReviewRecord` marks reviewer judgment as not-evidence but has no notion of
reviewer independence; the same model that wrote a hypothesis could assess its
novelty. **Recorded as a gap, not claimed as fixed.**

Tests: 1416 passing, up from 1391.

### On "the strongest system"

That is not a claim this round can support, and the register exists specifically
to stop such claims being made. What this round did is narrower and checkable:
the capabilities FarField lists are now the capabilities it has, each with a
probe that fails when that stops being true. Matching claims to reality is a
precondition for being good at research, not evidence of it. The two gaps most
likely to matter — a task-defined score, and multistart that actually branches —
are named above and remain unbuilt.

---

## Round 9 — giving RSI a gradient

The question this round answers is *how does each far-field exploration get
better than the last*. The answer found by tracing the live runs was: it does
not, and could not, because three separate links were severed.

### What the live runs actually showed about far-field exploration

Both live segments that produced a hypothesis recorded:

```
lane                     assumption_reframe
trajectory_applicability none
source_trajectories_used []
operator                 assumption_removal
```

`assumption_removal` was not chosen. It was the hard-coded fallback taken
whenever no grounded trajectory was retrieved, which was every time. The
hypotheses themselves were well-formed — falsifiable, with a quantitative
bootstrap criterion, a named competing explanation, an explicit claim delta —
but the mechanism the system is named after contributed nothing, and two
consecutive runs produced near-identical hypotheses because no mechanism existed
by which the second could differ.

The novelty grounding was worse than absent. `closest_prior_work` cited verified
retrieved papers, and the retrieved papers for *does petal geometry separate
iris species better than sepal geometry?* were: linear conic programming,
exoplanet apodization, petal wax layers, Petunia transcription factors,
cut-flower ethylene. None was about morphometric discrimination. The prior check
passed because nothing retrieved stated the claim — which is not novelty. And
the generated hypothesis defended itself against the flower-reconstruction
paper, so an irrelevant retrieval had reached into the framing of the science.

### Four modules, each fixed and verified on its own

**A task objective** (`objective.py`). A contract may declare what better means
for its root question: a metric name, which registered field of admitted
evidence carries it, a direction, and a minimum improvement. The project then
has a frontier and a notion of beating it. Only admitted WORLD evidence scores,
and the metric may only read a registered field — otherwise the scorer and the
thing scored share an author. A breakthrough here is a measurement, not a
discovery. Without this, "better" had no definition and nothing downstream could
have one.

**Attribution** (`exploration.py`). Every admitted result traces through its
hypothesis to the lane and operator that produced it. A policy over exploration
without this is fitting noise.

**A real choice** (`exploration.py`). The transformation is selected from what
the situation admits, what this project has measured, and what has not been
asked of this question. Applicability is a declared table over the operator
vocabulary; a weakened hypothesis calls for a different representation or
mechanism, a blocked design for a redesign, a comparison that did not separate
for a question about the objective or the verifier.

The first version of the ranking put the situation strictly first, which made a
hand-written table unbeatable by measurement — an operator this project had seen
settle things could never overcome a static prior. The ranking is additive:
applicability remains a hard filter, and within it measured yield outranks an
admitted policy, which outranks the table.

**Retrieval relevance** (`exploration.py`). A retrieved paper frames the research
state only if it bears on the root question, using the same lexical anchor guard
as goal drift and carrying the same stated limit. Off-topic papers are recorded,
not silently dropped: that a search returned nothing on topic is a finding about
the question's literature, and hiding it would turn an empty result into a
confident one. `closest_prior_work` is restricted to papers that bear on the
question.

### The link that mattered most

With all four built, the loop still had no gradient. Tracing it end to end:

```
mission cards carry the operator      ✓ runtime.py already did this
report counts per-operator outcomes   ✓ routing.operator_report
candidate weights per operator        ✓ routing.propose_policy
next session's operator selection     ✗ severed
```

Two failures at the reward, both the same shape as defects found in earlier
rounds — a signal that is structurally always zero:

1. `_card_credit` paid for `promoted` or `host_ok is True`. Promotion requires
   the whole ladder including heldout replication and is almost never reached.
   `host_ok` is written **only by `mission.py`** — the legacy pipeline's
   vocabulary. The production controller writes `reproduction_ok` and
   `identity_ok` instead. So every card the OpenWorld path produced earned zero,
   every operator drew the same smoothed weight, and there was no gradient.
2. The reward paid only for `verdict == supports`. **That is a
   confirmation-seeking incentive**: an operator that reliably produces decisive
   negative results earned nothing. Ruling something out is research.

The reward now reads the production vocabulary and pays for results that
*settled* something — reproduced, identity-checked, admitted, either direction —
and refuses inconclusive, unreproduced, or kernel-refused results. The heldout
receipt gate in `maybe_update` is untouched: this changes the signal, not the
admission.

End to end, with five settled results from one operator and five inconclusive
from another:

```
weights            decomposition 0.857   assumption_removal 0.143
without a policy   -> assumption_removal   (situationally apt)
with the policy    -> decomposition        (admitted policy weight)
```

### What the assembled system does and does not show

| | operators tried | frontier | breakthroughs | decision-relevant evidence |
|---|---|---|---|---|
| A old, hard-coded operator | `assumption_removal` | 1.0 | 1 | 6 |
| B situation-selected | `assumption_removal`, `unconstrained_exploration` | 1.0 | 1 | 6 |
| C plus an admitted policy | **`decomposition`**, `unconstrained_exploration` | 1.0 | 1 | 6 |

The behaviour changed in the intended direction: the move is now chosen, and an
admitted policy reaches the choice. **The outcome columns are identical, and
that is not evidence of improvement.** The scripted world's results do not
depend on which operator produced the hypothesis, so this evaluation cannot show
that better exploration yields better science — and making the simulation depend
on the operator would only measure an assumption written into it. What is shown
is that the gradient exists; whether following it improves research is the
question a live study would have to answer.

Tests: 1459 passing, up from 1416. Capability register: nineteen implemented
with firing probes, three partial with stated limits.

---

## Round 10 — the far-field lane had nothing to read

Six live segments reported `trajectory_supported` as an available lane and used
it zero times. Round 9 read that as a corpus problem: keyword retrieval rarely
returns one paper that cites another, so the library stayed empty and the lane
was "correctly not offered". That was true and it was not the whole cause. The
audit that opened this round asked six questions of the real code and got six
answers, none of them about corpus size:

- transitions were sought **inside one search's six results**, pairwise;
- the references those results carried were kept as strings and **never
  dereferenced**;
- the two indexes **named the same paper differently**, so an OpenAlex work
  keyed by DOI could never match its own `referenced_works` keyed by W-id;
- hop 2 rewrites the anchor and re-retrieves, which does nothing against an
  empty library;
- there is **no embedding, cosine or concept-graph** anywhere in this path, and
  the legacy `drift.py` / `novelty.py` stack is unreachable;
- `corpus.py` already had bounded citation expansion — as an offline corpus
  builder, wired to nothing.

### Six defects, each sufficient on its own

Every one was found by running the thing, and each became visible only after the
one above it was fixed.

| defect | how it presented | what it actually was |
|---|---|---|
| no expansion | 0 edges, six segments | references never dereferenced |
| namespace mismatch | 0 edges after expansion | DOI keys against W-id references |
| forward index | 31 backward edges, 0 forward | `cites:` takes W-ids; nodes are DOIs |
| quadratic cost | 48 calls in a 24-call run | both endpoints re-extracted per edge |
| restore mismatch | 10 extracted → 10 blocked | registry at write, strings at read |
| unrelated ≠ disagrees | 7 transitions, 0 retrieved | one non-match vetoed everything |

Then the lane found something and could not act on it: fifteen research
operators against a card table of four.

### Retrieval was asking for the wrong thing

The clearest single finding of the round. For *does petal geometry separate
iris species better than sepal geometry?* the query issued was
`all:"does petal" OR all:"petal geometry"` — the phrase builder takes adjacent
word pairs in sentence order, so `"iris species"` ranked fifth and was never
asked for. The survey returned conic programming, nanophotonics, bee electric
fields and cut-flower senescence, and the lexical relevance guard called the
**conic programming** paper on topic because its abstract contained "petal" and
"geometry".

Two fixes, and one over-correction found by running it again: the first version
of the subject screen asked for "the same objects and the same phenomenon" and
rejected a QTL study of floral traits in Iris hybrids — the right organs of the
right genus, measured — which left the anchor empty and the lane with nothing to
compare against. The test is now the objects studied, not the question asked
about them.

### What the live sequence shows

| run | nodes | edges | transitions | restorable | retrieved | used |
|---|---|---|---|---|---|---|
| 1–6 | 0 | 0 | 0 | — | 0 | 0 |
| 9 | 23 | 27 | 7 | 0/7 | 0 | 0 |
| 10 | 22 | 28 | 10 | 0/10 | 0 | 0 |
| 11 | 22 | 28 | 10 | 10/10 | 0 | 0 |
| 12 | 37 | 63 | 4 | 4/4 | 0 | 0 |
| 13 | 37 | 63 | 4 | 4/4 | 1 | **1** |

Run 13 produced a hypothesis on `trajectory_supported` with `lane_fallback`
empty, operator basis `grounded_historical_transition`, one source trajectory
matched exactly on `representation`, and that trajectory's target reached by
citation expansion rather than by the keyword search. Run 13's graph also
contains 16 forward-citation edges — zero in every earlier run — and a
three-paper lineage with the operator sequence
`[representation_change, representation_change]`.

An ablation on the same artifacts, at no cost: with the recovered transitions
the operator is `representation_change` on basis
`grounded_historical_transition`; with the transitions removed, retrieval
returns nothing and the lane falls back to `assumption_reframe`. **The lane
changes the decision.** Whether the decision it produces is better is not
measured here, by anything, and the capability register says so in the entry's
own limits.

### Cost, measured rather than assumed

One SURVEY: at most twelve model calls (ten paper extractions capped by budget,
two transition annotations), plus one to name the search subject and one to
screen the retrieval. Expanded citation nodes are read from title, abstract,
year and reported references — no full text is fetched for them. Run 13's shared
cache avoided nineteen re-reads. The extractions run concurrently, which turned
a fifteen-minute survey into a forty-second one.

The resource view had been billing a whole SURVEY as one `api_call` while the
ledger enforcing the envelope counted every model call — two meters of the same
name, an order of magnitude apart.

### Two claims retired

`SEMANTIC_NEIGHBOR` and `TEMPORAL_NEIGHBOR` were declared edge kinds that no
code built, so the provenance/retrieval separation this module exists for had
only one side. Bibliographic coupling and co-citation are now computed from
reference lists already in the graph — no request, no model call — and the two
kinds nothing computed are gone. A test builds one graph shaped to produce every
declared kind and compares it against the vocabulary.

A probe refusal told the writer of an iris-geometry claim to "count the object
(protocol field, invariant, index) — not cut-maintenance hops". The refusal text
reaches the writer as repair guidance, so a reason from another domain steers
the retry wrong. It now reports the actual overlap. The condition refused is
unchanged, and a regression pins that.

Tests: 1574 passing, up from 1526. Behavioural 8/8, long-horizon 18/18.
Capability register: twenty implemented with firing probes, two partial with
stated limits; `trajectory_conditioned_exploration` moved from partial to
implemented, `validated: live`.
