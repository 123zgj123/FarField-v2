# Changelog

## 2026-09-10 — Trajectory retrieval and world acquisition

Two mechanisms the runtime claimed and did not have.

- **Trajectory retrieval could not fire.** Applicability conditions and current
  research states are both free text a model extracted from different papers,
  and matching required byte equality, so the `trajectory_supported` lane
  effectively never matched and degraded into `assumption_reframe` without
  recording it. Matching is now graded and the grade travels with the result:
  normalized equality establishes applicability, same-polarity content-word
  overlap above threshold proposes it and is labelled `proposed`, and
  disagreeing polarity is a contradiction that can never be a match — a
  near-identical sentence with the opposite sense cannot be retrieved as
  support. `known_failure_conditions`, extracted since the beginning and read by
  nothing, now exclude a transition whose recorded failure describes the
  situation at hand. A lane that falls back records the substitution.
- **Acquisition had one recipe.** Seventeen attested worlds sat on disk that a
  blocked run had no way to bind, which made `no_acquisition_recipe` the most
  common terminal blockage. ACQUIRE now resolves a gap against a recipe
  registry: derive a child from the attested parent, or bind an already-attested
  catalog world whose own manifest declares the schema or domains the gap names.
  Nothing is fetched and nothing is synthesized. No recipe reaches the network,
  because letting a model name a URL lets it choose its own evidence.
- **Choosing the object of study is a scope decision.** Binding a different
  world decides what the results are about, so the contract owns it:
  `world_selection` defaults to `declared_only`. A run that would otherwise pick
  its own subject matter blocks and reports which world would have satisfied the
  gap. A wrongly matched world still produces genuine WORLD evidence — about a
  question nobody asked — so the default is to stay blocked and say so.

Tests: 1353 passing (6 skipped), up from 1311.

## 2026-09-09 — Research project management

The runtime could already produce hypotheses, run experiments and verify
evidence. This round addresses the difference between doing research operations
and managing a research project: knowing which question is worth answering,
whether the current answer is good enough, when a design has to be redesigned
rather than rerun, when a direction should be abandoned, and what the run is
allowed to spend.

- `ResearchContract` gives a project a root question that outlives any single
  hypothesis, lineage, world or design. It is immutable inside a project: a
  rewrite is refused by the reducer and recorded. Questions carry a root
  alignment — aligned, instrumental, or drifted — and drift becomes debt that
  blocks readiness. The alignment check is a lexical anchor guard, not semantic
  understanding; it asks for a justification rather than accepting silently.
- `ResearchQualityState` records twelve ordinal dimensions derived from admitted
  evidence and recorded reviews. There is no fabricated acceptance probability.
  A worker cannot write its own rating; it produces evidence or an objection and
  the projection follows. Novelty and importance move only on a recorded
  judgment, capped at `partial` unless that judgment cites literature the state
  verified, and an open objection outranks any assessment.
- REVIEW, REDESIGN and PROJECT_PIVOT are first-class actions with deterministic
  default executors, so the control loop is exercisable offline. Review is a
  planning signal that opens repair debt and lowers quality; it never raises
  belief. A `DesignRevision` names the failure root cause, the invalidated
  assumption, the repairs rejected, what is preserved and what changes, and its
  own early-kill condition. A pivot preserves WORLD evidence, the contract,
  contradictions and compact failure lessons, and drops the speculative chain
  that produced the retired direction.
- An objection requiring new evidence cannot be closed by prose. A rewrite, a
  narrowed claim, another caveat or a new discussion section is refused; the
  objection stays open and the refusal is counted.
- Progress separates activity, operational progress, epistemic progress and
  research progress, on two clocks. Strategic stagnation fires while every tick
  still succeeds, when the central question is no better supported, the major
  objections are no fewer and the quality gap has not shrunk.
- Resource accounting is derived from `measured_cost` already on admitted
  events, so the budget filter refuses something for the first time; both metric
  keys it used to read were never written by anything.
- Termination distinguishes seven outcomes. A finished loop, an empty frontier,
  a generated paper and an exhausted budget are each reported as themselves and
  none of them means the research is ready.
- The scheduler gains a research-decision layer over the existing heuristic:
  central-question value, objection repair, quality gap, redesign exhaustion,
  resource discipline, goal drift, a block on gathering more of the same while
  a fatal objection stands, and a penalty for currently inert action types. It
  is inert without recorded project state, so legacy runs schedule unchanged. A
  refused action returns its reason instead of vanishing from the menu.
- Worker context is the derived decision journal rather than the accumulated
  trajectory, and experiments carry outcome contingencies in branches. No branch
  carries a probability, because nothing here is a calibrated predictor. The
  projection computed for every action was previously read by no worker at all.
- Action retry derives from each action's declared `ActionSpec.reads` instead of
  a hash of the whole state, and an action that has twice returned the same
  outcome while admitting nothing is not offered again. `REFLECT` and `ARCHIVE`
  emitted no events and could not change state; reflection now records reusable
  failure lessons with their applicability and raises an anomaly on a repeated
  failure signature, and archiving records what it closed.
- Capability-level behavioural scenarios and long-horizon trajectory evaluation
  are part of the suite. See `ITERATION_REPORT.md` for the round-by-round record
  and `VALIDATION.md` for scope and limits. This layer is offline validated
  only: no live model or live world run exercised it.

## 2026-09-08 — ScientificState research workers and policy admission

- Refresh the English and Chinese project introductions, document actual CLI
  workspace creation and Python resumption, and separate system design from
  validation evidence. Remove placeholder demo emphasis from the READMEs.
- CLI research and the local console now call the same `run_research` entry.
  OpenWorld selects actions from `ScientificState`; the existing literature,
  hypothesis, registered-probe, verification, and synthesis workers execute
  those actions. `--legacy-pipeline` is a deprecated compatibility flag for
  that same controller. The historical Python pipeline remains a regression
  oracle, not another product control loop.
- Literature artifacts preserve verified citation identities, dates, and
  source spans. Paper states and transitions remain GENERATED interpretations;
  missing fields remain unknown. Transitions require citation lineage,
  temporal order, and grounded conceptual change. Structural applicability
  and historical-copy checks constrain operator reuse without proving novelty.
- First-hop exploration has trajectory-supported, assumption-reframe, and
  unconstrained speculative lanes. Later hops use canonical parent evidence;
  explicit execution failures can motivate a bounded failure reframe without
  being treated as scientific negatives.
- Experiments register identities and execute actual source against bound
  world bytes. Hypothesis-disagreement and gain/cost estimates guide scheduling
  as declared heuristics, not measured information gain. Replayable belief
  scores use reliability-weighted counts, not calibrated Bayesian inference.
  Scoped verified state requires the relevant reproduction, mechanism,
  identity, and independent heldout checks.
- Python callers can supply explicit `heldout_worlds`; the CLI accepts
  repeatable `--heldout-world` arguments. Each session records
  its service configuration and policy snapshot; `policy_file` and
  `policy_log` connect the existing mission-end research-policy workflow.
  Admission requires an evaluator-issued immutable single-use receipt binding
  the candidate, baseline, failure replay, nearby/heldout/regression cases,
  costs, and strictly positive heldout gain. Missing evaluation rejects an
  update. Research-time evolution only records proposals; it does not install
  capabilities or automatically promote judges.
- Trusted Python applications can supply `policy_suite` and `policy_evaluator`.
  Evaluation occurs after segment completion and log append, then admission
  consumes the evaluator-issued receipt. Missing trusted evaluation rejects.
- Synthesis and optional paper compilation now derive scientific scope and
  exact world identity from the same registered protocol/probe. Saved generated
  fact-sheet overrides cannot clear `cannot_corroborate` or prohibited
  inferences. Explicit identity mismatches and unsupported confirmation are
  rejected; the deterministic prose guard is not a complete semantic audit.
  Missing world provenance is labelled unknown, not published.
- Production artifacts live in `SCIENTIFIC_STATE.json`,
  `SCIENTIFIC_EVENTS.json`, `literature/`, and
  `research_workers/<evidence-id>/candidates/<card-id>/`.
  `RESEARCH_STATUS.md` and `research_complete: false` describe an open study,
  not a successfully completed paper. Both READMEs distinguish these outputs
  from historical bilingual research packets and document the current model
  configuration without including credentials.

Partial live validation: `gpt-5.6-sol` returned `OK` on a connectivity request
(17 tokens). An initial research mission encountered source HTTP 429/timeouts.
After the raw-term retrieval correction, a later check retrieved four real
verified papers and made four extraction calls totaling 2,731 tokens. Subsequent
bounded runs generated a typed speculative hypothesis, performed its literature
check, and invoked real diagnosis/probe-writing workers. A generated script's
measurement identifier differed from registration and was blocked, not counted
as scientific evidence. The controller then produced a failure-reframe branch.
The last segment exhausted its four-call budget and ended with event replay
matching the persisted state. The writer now receives an explicit registered
measurement identifier; that final prompt correction has offline regression
coverage, not a subsequent live result. These checks do not demonstrate completed
research, scientific novelty, live mission parity, or effective policy
self-improvement. See [VALIDATION.md](VALIDATION.md) for tests and limitations.

中文：CLI 与控制台统一由 ScientificState 驱动，接通真实文献与已登记实验 worker。
论文轨迹、三条探索分支和优先级仍是推测或启发；信念分数是可回放记账，非校准贝叶斯。
研究策略只能在任务结束后凭完整留出评估回执准入，不自动晋升评判器。
真实调用已覆盖生成、假设文献检查、诊断/脚本生成和失败重构；指标不一致被拒绝，
没有变成实验结果。最后一个有上限的运行段状态回放一致。运行结束不等于研究成功。

## 2026-09-07 — OpenWorld research integrity fixes

Historical entry: the CLI routing distinction below was superseded by the
single-controller integration on 2026-09-08.

- Explicit world ids now load the catalog manifest, verify the recorded digest,
  and copy the original artifacts into the mission workspace. Missing worlds
  and changed data fail instead of producing a substitute.
- Manifestless inputs remain GENERATED regardless of their names. Generated
  provenance survives derivation, and derived manifests use stable file order.
- Evidence submitted through events passes the same admission checks as direct
  evidence. A matching frozen-world digest is required for WORLD admission.
- Default research no longer invents validator snapshots for arbitrary topics.
  Builtin exploratory summaries describe available tables, graphs, and sequences
  while leaving the research question open. Verification recomputes supported
  observations instead of trusting an attestation flag alone.
- OpenWorld writes `RESEARCH_STATUS.md` and explicitly reports
  `research_complete: false`. General LLM/literature work and research packets
  remain available through `--legacy-pipeline`; both READMEs and CLI help explain
  this distinction.
- Anchor events expose the actual memory key. Tests use this key instead of
  assuming the nearest graph concept is also the memory anchor.
- Live-SWE raw trajectories are documented as optional external data. Their two
  integration tests skip when absent; missing-world checks still run. CI now
  also discovers the contract and historical regression test directories.

Validation on Python 3.11: 1,072 main-suite tests (6 skipped), 30 contract tests,
and 2 historical regression tests; no failures. Ten research-integrity regression
tests cover the fixes. A local Iris smoke run read 150 original rows, preserved
the open prediction question, and reproduced its event-state digest. Live model
research quality was not evaluated in this update.

中文：本次修复重点是恢复真实数据绑定、阻止生成数据晋升为 WORLD、校验事件证据，
并明确默认 OpenWorld 的能力边界。完整文献、提案和实验流程请使用
`--legacy-pipeline`；默认路径提供本地探索性观测及研究状态记录。
