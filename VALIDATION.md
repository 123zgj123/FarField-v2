# ScientificState runtime validation — 2026-09-08

This is an implementation and validation record, not a claim of scientific
discovery or demonstrated recursive self-improvement.

## What changed

The CLI and console use one `run_research` / OpenWorld controller. Mature
literature, generation, diagnosis, probe execution, host reproduction, and
writing workers are adapters in that loop. `kernel.py`, `events.py`, the
World/Evidence identity implementations, and ClaimSpec infrastructure were not
rewritten. State extensions and admission checks preserve generated provenance.

Paper-state extraction and grounded transition retrieval live in the existing
exploration code. Three proposal lanes share the worker and event contracts.
Later hops consume canonical parent evidence, or record a bounded failure
reframe without calling failure an experimental result. Belief accounting is
deterministic and replayable; experiment priority estimates hypothesis
disagreement, not measured information gain.

Policy changes are routing-policy candidates, not autonomous kernel or judge
modifications. Admission requires disjoint historical-failure, nearby, heldout,
and regression replay partitions, measured costs, and a protected single-use
receipt with strict heldout improvement. The evaluator is trusted application
code; its absence rejects admission. This is not evidence that live RSI works.

## Required regression coverage

| Requirement | Regression files |
|---|---|
| Arbitrary-topic real literature worker dispatch | `test_openworld_workers.py`, `test_research_control.py`, `test_research_literature_queries.py` |
| THEORIZE independent of validator fixtures | `test_research_branches.py`, `test_research_world_compile.py` |
| GENERATED never promoted to WORLD | `test_research_integrity.py`, `test_research_belief.py` |
| Reject reconstruction of historical target | `test_research_trajectory.py` |
| Same operator across distinct research topics | `test_research_trajectory.py` |
| Detect lightly reworded historical copies | `test_research_trajectory.py` |
| Second hop reads actual first-hop evidence | `test_research_branches.py` |
| Failed first hop permits explicit reframe | `test_research_branches.py` |
| Belief updates replay from events | `test_research_belief.py`, `test_research_control.py` |
| Competitors change experiment selection | `test_research_selection.py` |
| Policy patch requires protected heldout admission | `test_research_policy_admission.py`, `test_research_policy.py` |
| Legacy/OpenWorld execution parity | `test_research_worker_parity.py`, `test_research_replication.py` |
| Root question immutable; drift recorded as debt | `test_research_contract.py` |
| Quality derived from evidence, never asserted | `test_research_quality.py` |
| Judgment dimensions capped by their grounding | `test_research_quality.py` |
| Evidence-requiring objections refuse prose repair | `regressions/test_caveat_only_repair.py` |
| Seven termination outcomes; readiness is a conjunction | `test_research_termination.py` |
| Resource spend measured, budget filter refuses | `test_research_termination.py` |
| Scheduler reads objections, quality, drift, budget | `test_research_decisions.py` |
| Refused actions report a reason | `test_research_decisions.py` |
| Restart keeps evidence and drops narrative | `test_research_decisions.py` |
| Retry needs the action's declared inputs to change | `test_research_efficiency.py` |
| An established outcome is not re-read | `test_research_efficiency.py` |
| Real advancement credited exactly once | `test_research_efficiency.py` |
| Capability-level decision behaviour | `behavioral/test_research_scenarios.py` |
| Long-horizon trajectory guarantees | `behavioral/test_long_horizon.py` |
| Trajectory retrieval fires, and never erases a negation | `test_research_retrieval.py` |
| Known failure conditions exclude a transition | `test_research_retrieval.py` |
| Acquisition binds attested bytes only, never the network | `test_research_acquisition.py` |
| Choosing the object of study needs contract authorisation | `test_research_acquisition.py` |
| A descriptive observation is not a technical defect | `regressions/test_live_run_defects.py` |
| An experiment reports the units it measured, bounded by its world | `regressions/test_live_run_defects.py` |
| One defect raises one objection, never an empty one | `regressions/test_live_run_defects.py` |
| Review is refused when it has nothing new to say | `regressions/test_live_run_defects.py` |

The parity tests run actual registered subprocesses against frozen test worlds
with recorded-model responses. They compare identities, preregistration order,
positive/negative results, reproduction, unavailable services, and policy
refusals. They are **not** a live multi-topic mission parity benchmark.

Additional regressions reject mismatched hypothesis IDs, graph predicates used
as scientific falsifiers, wrong world/object bindings, changed diagnosis
handles or metrics, and unsupported claim escalation during paper drafting.
Resume rebuilds derived snapshots from unchanged scientific events.

## Behavioural evaluation

Unit tests grade functions. They cannot grade a decision, so the control loop
also has capability-level scenarios in
[benchmark.py](src/farfield/extras/openworld/benchmark.py). Each installs a
research *situation* into canonical state through the reducer and asks what the
controller does next.

| Scenario | Correct behaviour |
|---|---|
| A underpowered positive result | not ready; strengthen the evidence, not the wording |
| B fatal reviewer objection | refuse the caveat; redesign |
| C peripheral progress trap | strategic stagnation rises despite constant activity |
| D dead end, budget left | change direction |
| E dead end, budget nearly gone | do not open a new front |
| F goal drift | drift detected and named as the readiness blocker |
| G ten agreeing reviewers | belief, verified state and quality all unmoved |
| H project restart | WORLD evidence and contract survive; speculation does not |

Before this work 1 of 8 passed and seven of the eight failures chose the same
action, which is a scheduler with one term rather than eight separate bugs. All
eight pass now.

[trajectory_eval.py](src/farfield/extras/openworld/trajectory_eval.py) runs the
real controller against a scripted world for thirty actions and reports the
capability metrics: decision-relevant evidence yield, time to redesign, time to
pivot, wasted actions after a fatal objection, caveat-only repair rate, goal
drift, replication completion, resource efficiency.

| Metric, recoverable project, 30 actions | before | after |
|---|---|---|
| actions that changed nothing | 18 | 7 |
| decision-relevant evidence | 2 | 6 |
| resource efficiency (evidence per call) | 0.067 | 0.20 |
| experiments actually reached | 1 | 3 |

These are **scripted, deterministic, offline** scenarios. They measure how the
controller allocates its actions. They are not evidence that the resulting
science is any good, and passing them establishes only that specific known
failure modes do not occur.

## Reproduce offline verification

Latest complete run: 1,391 tests (6 skipped, no failures or errors) including
30 contract tests, the historical regression tests, the eight behavioural
scenarios and the long-horizon trajectory guarantees. `git diff --check` passed.

```bash
PYTHONPATH=src FARFIELD_LLM_MODE=replay python3.11 -m unittest discover -s tests -q
PYTHONPATH=src FARFIELD_LLM_MODE=replay python3.11 -m unittest discover -s tests/contracts -q
PYTHONPATH=src FARFIELD_LLM_MODE=replay python3.11 -m unittest discover -s tests/regressions -q
PYTHONPATH=src python3.11 -m unittest discover -s tests/behavioral -t . -q
git diff --check
```

## Defects the trajectory evaluation found that unit tests did not

Each of these was present with the whole suite green, and each needed a
thirty-action run to expose:

- derived project views were recomputed before `debt` was overwritten, silently
  erasing goal-drift detection;
- scheduler filters dropped eligible actions with no record — one malformed
  experiment proposal removed every `PROBE` for an entire run while the tick
  view still reported `PROBE` eligible;
- belief refresh overwrote `retired` back to `supported`, resurrecting
  abandoned directions into a pivot/redesign livelock;
- after a pivot every hypothesis is retired, which the quality projection read
  as total goal drift and answered with another pivot;
- `ActionBlocked` counted as productive output, so a repeatedly failing action
  always looked useful;
- the retry key hashed the whole state, so any unrelated change made a
  just-failed action look untried;
- `REFLECT` and `ARCHIVE` emitted no events at all: they always reported success
  and were structurally incapable of changing anything;
- trajectory retrieval compared two independently model-extracted free-text
  fields for byte equality, so the `trajectory_supported` lane effectively never
  fired and degraded into another lane without recording it;
- ACQUIRE supported exactly one gap, so a run could not bind any of the attested
  worlds on disk and `no_acquisition_recipe` was its most common terminal
  blockage.

## Bounded live runs, 2026-09-10

Three bounded segments against `gpt-5.6-sol` (verified served) on the attested
`fisher-iris` world with `uci-letters` bound as an explicit heldout, 12 model
calls and 10 ticks per segment. Credentials were process-only, read from a key
file outside the repository, and never written to source, `.env` or a model
cache. Root question: *does petal geometry separate iris species better than
sepal geometry?*

**Segment 1 produced nothing, and that was the point.** It reached
`no_applicable_grounded_trajectory`, retried the identical doomed lane, ran out
of eligible actions and stopped at `BLOCKED` with zero hypotheses and zero
experiments. It exposed three defects that a green suite did not:

- a failing action's own `ActionBlocked` changed a question's status, and status
  was inside the slice that action declared it reads — so **the failure
  unblocked its own retry**;
- the inert-repetition rule keyed on action type and target while ignoring the
  research lane, so **one lane's failure banned two lanes that were never
  tried**, ending the segment with viable work still available;
- a grounded transition needs one retrieved paper to cite another, and keyword
  retrieval returned seven papers with no citation link among them, so the
  transition library was empty and the `trajectory_supported` lane could only
  fail.

**Segment 2, after those fixes, reached a real experiment.** It generated a
hypothesis with a competing explanation, ran a registered two-arm probe against
the attested world (`treatment 0.2697`, `control 0.2652`), correctly read the
separation as `uninformative` rather than positive, refused corroboration
because a competing mechanism was not ablated, recorded five structural
objections including a fatal one, and stopped at `BUDGET_EXHAUSTED` without
claiming completion. It exposed four further defects:

- `technical_correctness` read *all* WORLD evidence, so a descriptive
  observation's honest `cannot_corroborate` label counted as a validation
  failure and **a redesign was demanded before any design existed**;
- REVIEW was eligible whenever a hypothesis and a survey existed, but the
  structural reviewer draws its objections from executed probes, so a tick was
  spent on a review that returned `no_new_objections`;
- an unablated result raised two objections for one defect, one of them with an
  empty body, because `cannot_corroborate` was set with no validation gap;
- **no worker anywhere reported a sample size.** `experimental_adequacy` demands
  one, so the dimension could never leave `weak`, redesign would have been
  demanded forever, and `RESEARCH_READY` was unreachable for reasons that have
  nothing to do with the science. Registered experiments now report
  `n_treatment` and `n_control`; the smaller arm is the sample, the attested
  world's size is a bound rather than the sample, and a report exceeding that
  bound is refused rather than believed.

**Segment 3, after those four fixes, behaved differently in every one of them.**
No redesign before an experiment existed, one review instead of a wasted one,
no empty-bodied objection, and `experimental_adequacy` reached `adequate` from a
sample the experiment reported itself (`n_treatment` and `n_control` both 150,
inside the attested world's bound of 150). The registered probe returned
`treatment 0.0445` against `control -0.0124`, a positive result — and the
runtime still refused to corroborate it, because the competing mechanism was not
ablated. `mechanism_validated` stayed false, `central_claim_support` stayed
`partial`, the review recorded "a positive arithmetic result is not a verified
mechanism", and the segment stopped at `BUDGET_EXHAUSTED` with
`research_complete: false`. A live positive result did not become a finding.

Segment 3 also showed that the duplicate-objection fix had only been applied to
the reviewer: the quality projection still charged one unablated result to both
`baseline_strength` and `technical_correctness`, reporting the second as
`validation_gaps_on_1_evidence_rows` when that row's validation gaps were empty.
Causes owned by a named dimension are no longer charged twice, and an
unexplained refusal now says that its reason was not recorded.

Also found while checking coverage: `tests/regressions/` lacked an
`__init__.py`, so the main discovery command had been silently skipping it.

Segment 1's finding revises an earlier conclusion recorded here. Trajectory
retrieval was described as limited by corpus size; both the matcher *and* the
step that builds the corpus were unusable, and no amount of corpus would have
helped while retrieval returned nothing to match.

## Far-field exploration, live: what each fix moved

Seven bounded live segments against `gpt-5.6-sol`, run one after each fix, on
the same question: *does petal geometry separate iris species better than sepal
geometry?* The numbers are from the runtime's own trajectory telemetry.

| run | nodes | provenance edges | transitions | restorable | retrieved | what changed before it |
|-----|-------|------------------|-------------|------------|-----------|------------------------|
| 1–6 | 0 | 0 | 0 | — | 0 | (the lane was offered and never used) |
| 9 | 23 | 27 | 7 | 0 of 7 | 0 | citation expansion, canonical identity |
| 10 | 22 | 28 | 10 | 0 of 10 | 0 | operator vocabulary, verifier_shift mapping |
| 11 | 22 | 28 | 10 | **10 of 10** | 0 | lineage re-verified from recorded identifiers |
| 12 | 37 | 63 | 4 | 4 of 4 | 0 | subject-anchored search phrase |
| 13 | 37 | 63 | 4 | 4 of 4 | **1** | subject screen scoped to objects studied |

Run 13 is the first in which a hypothesis carried `source_trajectories_used`.

Each run failed at a *later* point than the one before it, which is the only
evidence that the fixes were causal rather than incidental. Runs 9 and 10 built
a real graph and could not read it back. Run 11 could read it back and had
nothing to compare against, because the anchor was built from conic programming
and nanophotonics. Run 12 retrieved the right genus and screened all of it away.
Run 13 admits three Iris papers, populates the anchor, and retrieves one
grounded historical transition on an exact representation match.

Run 13 then produced the hypothesis. `research_lane: trajectory_supported`,
`requested_lane` the same and `lane_fallback` empty, so it is the lane it claims
to be. Operator basis `grounded_historical_transition`; one source trajectory,
matched exactly on `representation`, applicability `established`. Its target,
`doi:10.1021/acs.jafc.2c06132`, is a node reached by citation expansion and not
one of the five papers the keyword search returned — the expansion is what
supplied it.

What is **not** established: that a hypothesis conditioned on a historical
transition is better than one generated without it. Nothing here measures
hypothesis quality, no claim anywhere rests on this lane, and the register says
so in the entry's own limits.

Cost, measured: one SURVEY spends at most twelve model calls — ten paper
extractions capped by budget, two transition annotations — plus one call to name
the search subject and one to screen the retrieval. Expanded citation nodes are
read from title, abstract, year and reported references; no full text is fetched
for them. In run 13 the shared extraction cache avoided nineteen re-reads of
papers already extracted.

## Live-service observations and remaining validation

The exact official model `gpt-5.6-sol` answered a connectivity request. Subsequent
bounded research runs used the same model and the attested Fisher Iris world.
Credentials were process-only, not persisted in source or model caches.

Live retrieval exposed malformed stemmed queries; the corrected queries
retrieved four verified papers. Model outputs subsequently exposed inconsistent
competitor identifiers, missing closest-prior citations, and missing world
compilation context. The interface defects have regression coverage. Missing
citations or grounded historical trajectories still block honestly.

A later live response produced a speculative hypothesis with a concrete
falsifier, named competing explanation, discriminating proposal, and compiled
world/object identity. The controller performed a separate literature check on
that hypothesis. This establishes worker integration, **not** novelty, correct
causal interpretation, or verification of the hypothesis.

The final bounded segment invoked diagnosis and probe-writing workers. It
rejected a generated measurement description that did not match the registered
metric identifier (`probe_execution_blocked`), then generated an explicit
failure-reframe branch. No arm values or WORLD probe evidence were invented.
It used four model calls / 22,549 tokens and stopped at its declared envelope;
the final state digest matched event replay. A subsequent code correction makes
the registered measurement identifier explicit in the writer prompt while
retaining the rejection guard. This last prompt change has offline regression
coverage and has not been retried live.

The project-management layer was offline-validated when it was written. It has
since been exercised live: thirteen bounded Iris sessions produced
`ContractSet`, `ReviewRecorded`, `DesignRevised` and `LineageForked` events and
terminated through the declared statuses. **`PROJECT_PIVOT` has still never
fired in a live run** and remains offline-validated only, as does the
deterministic trajectory world used by the long-horizon tests.

The limits of the mechanisms themselves are unchanged by any of that.
Root-question alignment is a lexical anchor guard and cannot recognise that two
phrasings share an estimand. Quality dimensions are ordinal bookkeeping,
calibrated against nothing. Efficiency thresholds in the long-horizon tests are
floors measured against the current controller, not targets derived from any
external standard.

Open validation requirements remain: diverse real mission parity, a useful
grounded trajectory corpus, independent replication worlds with suitable
scientific scope, and an application-owned heldout policy evaluation benchmark.
Lexical copy checks do not certify novelty; registered names and source checks
do not fully prove arbitrary generated programs implement their prose claims;
the deterministic draft guard is not a complete semantic audit. None of these
limits is replaced by LLM votes or fabricated observations.
