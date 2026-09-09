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

Latest complete run: 1,311 tests (6 skipped, no failures or errors) including
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
  and were structurally incapable of changing anything.

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

The project-management layer added in this round is **offline validated only**.
No live model or live world run exercised the contract, quality, review,
redesign, pivot or termination paths; the trajectory world is a deterministic
script. Root-question alignment is a lexical anchor guard and cannot recognise
that two phrasings share an estimand. Quality dimensions are ordinal
bookkeeping, calibrated against nothing. Efficiency thresholds in the
long-horizon tests are floors measured against the current controller, not
targets derived from any external standard.

Open validation requirements remain: diverse real mission parity, a useful
grounded trajectory corpus, independent replication worlds with suitable
scientific scope, and an application-owned heldout policy evaluation benchmark.
Lexical copy checks do not certify novelty; registered names and source checks
do not fully prove arbitrary generated programs implement their prose claims;
the deterministic draft guard is not a complete semantic audit. None of these
limits is replaced by LLM votes or fabricated observations.
