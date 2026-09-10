# FarField system design

[English overview](README.md) · [中文概览](README.zh-CN.md) · [Validation](VALIDATION.md)

FarField is an experimental, ScientificState-driven research runtime. Its
trajectory-conditioned and evidence-driven mechanisms are implemented research
infrastructure, not evidence that the system has learned to make discoveries.

## Authority and control

There is one product-level scientific controller:

```text
ResearchContract
       ↓
ScientificState → Frontier → Scheduler → Action → Existing Research Worker
       ↑                                                   ↓
       └── Scientific Event ← Trusted Kernel ← CandidateResult
```

`ScientificState` answers *what do we know*. A long project also has to answer
*what is this project for*, *how good is it*, *what is standing against it*,
and *what is left to spend* — questions a `goal: str` cannot survive fifty
actions. Four derived, event-sourced projections carry them:

| Projection | Module | Answers |
|---|---|---|
| `ResearchContract` | `contract.py` | the root question, scope, quality target, authorised reframes, limits |
| `ResearchQualityState` | `quality.py` | twelve ordinal dimensions and which are short of the contract |
| Review debt | `quality.py` | recorded objections, their severity, and what repair each demands |
| `ResourceState` | `resources.py` | measured spend against declared limits |

All four are recomputed from admitted events on every reduction, so a resumed
or rebuilt state agrees with a live one. None of them can be written by a
worker: a worker produces evidence or an objection, and the projection follows.

[runtime.py](src/farfield/extras/openworld/runtime.py) connects the CLI and console
to OpenWorld. [workers.py](src/farfield/extras/openworld/workers.py) adapts existing
research services. Workers return candidates; they do not choose the next
research action or launch another mission.

The Trusted Kernel, event sourcing, World/Evidence identity, and ClaimSpec
infrastructure were not rewritten in this integration. State extensions and
admission checks operate within those contracts. Models can propose plans,
interpret papers, and write executable candidates; they cannot mint trusted
observations or authorize their own verifier changes.

| Action | Worker integration | Boundary |
|---|---|---|
| SURVEY | arXiv/livefeed, sources, prior work and literature spans | Missing citations or unavailable sources remain gaps |
| THEORIZE | generate, explore, reframe, diagnose | Structured hypotheses are GENERATED proposals |
| PROBE | diagnose, probeexp, hostexp | A generated plan is not an executed result |
| VERIFY | identity checks, registered execution, reproduction, heldout fixtures | Verification is scoped to actual evidence and objects |
| SYNTHESIZE | brief, packet, paperplan, writeup | Text cannot increase claim strength without the evidence contract |
| REVIEW | structural objections over canonical state | Reviewer judgment is a planning signal, never evidence |
| REDESIGN | diagnosis over reviews, failures and quality gaps | A revision is a plan, not a result |
| PROJECT_PIVOT | lineage retirement and clean restart | WORLD evidence and the contract survive; speculation does not |

## Project-level decisions

Producing hypotheses, running experiments and verifying evidence is not the
same as managing a research project. Three further actions cover the decisions
a long horizon actually forces.

**REVIEW** records structured objections: severity, dimension, affected claim
and design, the repair type demanded, and whether new evidence is required. The
default reviewer is deterministic and raises only what the state already proves
— an unreported sample size, a measure blind to its oracle placebo, a control
arm that measured nothing, a single-world result. A model reviewer may add
judgment on top; it cannot remove these, and it cannot raise belief. Ten
reviewers agreeing is still zero measurements.

Novelty and importance are the exception no execution can settle. A recorded
judgment moves them, capped at `partial` unless it cites literature this state
verified. An open objection on the same dimension outranks any assessment.

**Caveat-only repair is refused deterministically.** When an objection requires
new evidence, a rewrite, a narrowed claim, another caveat or a new discussion
section cannot close it. The reducer refuses the resolution, keeps the objection
open, and counts the refusal. Only new admitted WORLD evidence, a replication,
a repaired measurement, a repaired design or a stronger baseline resolves it.

**REDESIGN** produces a `DesignRevision`, not another hypothesis: the trigger,
the failure root cause, the invalidated assumption, the repairs considered and
rejected, what is preserved, what changes, and the condition under which the
revision is itself abandoned early. Repair attempts have diminishing returns —
two spent revisions on a dimension that has not moved make a pivot worth more
than a third revision.

**PROJECT_PIVOT** retires a direction. Admitted WORLD evidence, the contract,
live contradictions and compact failure lessons carry forward; the speculative
chain that produced the dead direction does not, because handing the model the
transcript that produced it is how a pivot buys nothing. A direction cannot be
abandoned before it has been tried, and a fresh epoch must do real work before
it may be abandoned in turn.

## Progress, stagnation and termination

Four things used to be called progress: activity, operational progress,
epistemic progress, and research progress. Only the first two were measured, so
an agent could resolve ten peripheral questions, add ten artifacts and never
trip a stagnation check while the project stood still.

Operational idleness and research stagnation now run on separate clocks.
`strategic_stagnation` fires while every tick is still succeeding, when the
central question is no better supported, the major objections are no fewer and
the quality gap has not shrunk — and it raises the priority of REDESIGN, FORK
and PROJECT_PIVOT rather than more of the same.

An action that provably cannot inform anything is refused before it is offered.
The retry key is derived from each action's declared `ActionSpec.reads`, so a
blocked observation retries when the world changes and not when an unrelated
hypothesis appears; and an action that has twice returned the same outcome
while admitting nothing has established that fact.

Termination distinguishes seven outcomes. None of a finished loop, an empty
frontier, a generated paper, or an exhausted budget means the research is ready:

```text
RUN_SEGMENT_DONE  RESEARCH_READY  RESEARCH_INCOMPLETE  BLOCKED
NO_VIABLE_PATH    BUDGET_EXHAUSTED  FRONTIER_EXHAUSTED
```

`RESEARCH_READY` is a conjunction of gates over admitted evidence, recorded
objections, the contract and the claim's scope — central-question support, zero
fatal objections, required comparisons and replication, evidence scope matching
the claim, no unauthorised goal drift, no unresolved contradiction, a closed
quality gap, and the contract's required outputs.

## Trajectory-conditioned exploration

[explore.py](src/farfield/extras/explore.py) represents a paper using its problem,
research question, gap, assumptions, representation, mechanism, objective,
method, evidence, evaluation regime, limitations, and unresolved questions.
Citation identity and source spans remain attached. Extracted interpretations
are GENERATED; absent information stays unknown.

A historical transition needs citation lineage, temporal order, and changed
components grounded in exact source spans. It records source and target states,
trigger, changed and preserved components, operator, mechanism/assumption/
objective/evaluation deltas, supporting evidence, applicability, and failure
conditions. A paper pair is not automatically a reliable transition.

The finite, extensible operator vocabulary includes:

- assumption removal/inversion, problem reframing, representation/objective changes;
- decomposition, mechanism replacement, adaptive control, feedback introduction;
- formalization, boundary search, scaling, cross-domain transfer;
- verifier shift and failure-driven redesign.

An operator is a proposed scientific transformation. In particular,
`verifier_shift` does not grant permission to replace the Trusted Kernel.

The first-hop frontier provides three candidate lanes:

| Lane | Anchor |
|---|---|
| `trajectory_supported` | Applicable, grounded historical transitions |
| `assumption_reframe` | An assumption, gap, or boundary in the current problem |
| `unconstrained` | Exploratory hypotheses without a required retrieved trajectory |

Missing trajectory support blocks that lane rather than fabricating examples.
Candidates retain source trajectories, reused operators, closest prior work,
inherited and genuinely changed components, claim/mechanism deltas, and an
explanation of why they are not historical reconstruction. Copy checks and the
existing apply-X-to-Y rejection rule constrain proposals; neither proves novelty.

Retrieval matches research-state conditions structurally, never embedding
distance as scientific value. A condition and a current research state are both
free text a model extracted from different papers, so requiring them to be
byte-identical was not a strict test but one that never fired — the trajectory
lane was a claimed capability the runtime did not have, and losing it degraded
silently into another lane.

Matching is therefore graded, and the grade travels with the result. Normalized
equality **establishes** applicability. Same-polarity content-word overlap above
threshold **proposes** it, labelled as such because lexical proximity is not
applicability. Disagreeing polarity is a contradiction and never a match, so a
near-identical sentence with the opposite sense cannot be retrieved as support.
A transition whose recorded `known_failure_conditions` describe the situation at
hand is excluded however well its applicability conditions match. A lane that
falls back records the substitution on the hypothesis.

Retrieval lives entirely in GENERATED space upstream of the kernel: its output
is prompt input, and a hypothesis it inspires still has to pass the copy screen,
the literature check, registration, execution and the promotion ladder. It
cannot mint evidence; its real risk is anchoring on an irrelevant historical
operator, which is bounded by the labelling and the failure-condition exclusion.

Coverage remains limited: there is no broad learned transition corpus or trained
`P(operator | research_state, gap, evidence)` yet. Corpus size was never the
binding constraint while the matcher could not use one.

## Evidence-driven later hops

A later scientific branch reads its canonical parent's admitted evidence,
unresolved questions, and relevant failure or contradiction state. Hypotheses
undergo a separate literature check and propose a discriminating experiment
against explicit competing explanations.

```text
State → operator → hypothesis → literature / competing explanations
  ↑                                      ↓
  └──────── admitted evidence ← registered probe
```

An execution failure can justify a bounded `failure_reframe` branch. This is
recovery from a failed research attempt, not a scientifically negative result
or an evidence-supported discovery. Further exploration is not an unrestricted
sequence of latent-space jumps.

## Belief and experiment selection

[state.py](src/farfield/extras/openworld/state.py) and
[reducer.py](src/farfield/extras/openworld/reducer.py) record prior confidence,
supporting/contradicting evidence, reliability, competitors, unresolved
assumptions, posterior score, and update provenance.

Replay deterministically derives reliability-weighted Beta-count bookkeeping
from admitted evidence, starting from Beta(2, 2). Generated proposals and
infrastructure failures give no production belief credit. This is not a
calibrated Bayesian model: competing theories are recorded, not jointly inferred,
and repetitions must not be interpreted as independent samples.

Experiment proposals specify hypotheses compared, outcomes under each,
nuisance factors, a minimal discriminating intervention, and positive,
negative, and inconclusive interpretations.

[scheduler.py](src/farfield/extras/openworld/scheduler.py) retains the heuristic
scheduler and adds hypothesis-aware disagreement/resolution estimates alongside
scientific gain, transfer, frontier value, cost, and risk. Changing competing
hypotheses can change the experiment ranking. These are estimates from declared
predictions—not measured information gain or validated utility signals for RL.

Above that heuristic sits a research-decision layer reading the contract, the
quality state, the review debt and the resource state: central-question value,
objection repair value, quality-gap value, redesign exhaustion, resource
discipline, goal-drift penalty, a block on routine evidence-gathering while a
fatal objection stands unrepaired, and a penalty for action types that are
currently inert. The layer is inert until a project has recorded project-level
state, so a bare question-and-world run schedules exactly as it did before.
A refused action returns its reason rather than disappearing from the menu.

Worker context is the derived decision journal — contract, current strategy and
why it may not hold, the next decisive action, relevant WORLD evidence, standing
objections, remaining budget — not the accumulated trajectory. For experiments
it also carries outcome contingencies in branches. Nothing in this runtime is a
calibrated predictor, so no branch carries a probability.

## Evidence and promotion

Speculative and verified research are separate views of the scientific state.
Bold proposals are allowed in the speculative frontier; they cannot silently
become long-term verified knowledge.

- WORLD evidence requires attested bytes and actual execution against the bound
  object. A schema match alone does not establish scientific object identity.
- GENERATED/SYNTHETIC results cannot corroborate the target-world claim.
  Constructed checks may reveal scoped coherence or feasibility limitations.
- Registration binds claim, source, world, arms, measure, expected direction,
  and protocol identity before execution. Both arms use the same measurement.
- Probe outcomes distinguish execution blocked, policy refused, scientific
  negative, positive, and inconclusive. A refusal supplies no arm values.
- Exact-instance reproduction checks the same EvidenceID. Independent transfer
  or replication needs suitable explicitly supplied heldout conditions.
- Scoped promotion requires the relevant literature, falsification, mechanism,
  executable evidence, identity, reproduction, and heldout checks.

Synthesis reads authoritative protocol/probe facts and preserves unknowns,
scope gaps, and prohibited inferences. A deterministic guard rejects explicit
unsupported confirmation; it does not completely audit arbitrary scientific
prose. Likewise, matching registered identifiers and source bytes does not
fully prove a generated program implements the stated causal mechanism.

## Research-policy admission

Policy improvement is a separate mission-boundary workflow using
[routing.py](src/farfield/extras/routing.py), not another scientific controller:

```text
Completed segment → recurring failure → candidate routing-policy patch
  → historical failure replay / nearby tasks / heldout / regression / cost
  → evaluator-issued receipt → admit or reject for a later session
```

The current candidate schema is restricted to routing-policy weights and fitting
provenance. It is not a general facility for autonomous source-code, kernel,
judge, or skill replacement.

Trusted Python applications can provide `policy_suite` and `policy_evaluator`
to `run_research`. Admission requires disjoint evaluation partitions, measured
costs, strict heldout improvement, and an immutable single-use receipt binding
the candidate and incumbent. Missing trusted evaluation rejects the update.
The active policy is snapshotted for a session; admission affects later sessions.

Research-time `OpenWorld.evolve()` only records proposals. A model score,
single-task improvement, survival rate, or self-consistency is not an admission
receipt. Tests establish these local guards, not successful live RSI.

## Obtaining a world

An agent that cannot obtain the object its question is about cannot answer the
question, and no amount of scheduling changes that. ACQUIRE resolves a declared
gap against a recipe registry:

- `derived` — build a child world from the attested parent already bound. This
  stays with the current object of study.
- `catalog_binding` — bind an already-attested world from the local catalog
  whose own manifest declares the schema or domains the gap names. Nothing is
  fetched and nothing is synthesized; the attestation check still decides.

No recipe reaches the network. A network recipe would need an operator-pinned
URL *and* an expected source digest, because letting a model name a URL lets it
choose its own evidence. An unresolved gap fails closed, unchanged.

Binding a *different* world decides what the project's results will be about, so
it is a scope decision the contract owns: `world_selection` defaults to
`declared_only`, and a run that would otherwise pick its own subject matter
blocks and reports which world would have satisfied the gap. A wrongly matched
world still produces genuine WORLD evidence — it just answers a question nobody
asked, which is why the default is to stay blocked and say so.

## Operational boundaries

- Sessions have a finite horizon and service budget. Python callers can resume
  an existing workspace from events; the CLI currently creates a new directory.
- Arbitrary-topic literature dispatch does not imply arbitrary-topic execution.
  Catalog and acquisition recipes remain limited; missing capabilities fail closed.
- Offline worker parity uses actual subprocesses with recorded model responses.
  It is not a diverse live mission benchmark.
- The latest bounded live validation reached real retrieval and probe construction,
  but a metric mismatch blocked execution; it did not produce verified findings.

See [VALIDATION.md](VALIDATION.md) for reproducible checks and remaining work.
