# MADO EVALS v0.1

MADO EVALS is the evidence-driven evaluation layer for MADO LOOP.

Its job is not to decide whether a model output looks good. Its job is to replay bounded development tasks, collect the same kinds of evidence MADO LOOP already trusts, compare results without hiding failures behind a single score, and make skill or routing changes safer to promote.

## 1. Goal

Turn MADO LOOP's improvement cycle into a reproducible loop:

```text
TASK CORPUS
    |
    v
RUN -> EVIDENCE -> EVALUATE -> COMPARE -> PROMOTE / HOLD / REJECT
 ^                                                |
 |                                                v
 +---------------------- REPLAY <---------- CHALLENGER
```

MADO EVALS extends, rather than replaces, the existing P0-P5 proof ladder and bounded skill feedback loop.

- Live feedback answers: "What happened in real use?"
- Eval replay answers: "Does this candidate still work on known cases?"
- P0-P5 answers: "What is actually proven for this run?"

These three signals must remain distinguishable.

## 2. Non-goals

v0.1 does not:

- let an LLM grade its own work as the authoritative result;
- create a global leaderboard of models or skills;
- auto-promote a challenger into the canonical skill;
- mutate the source project outside an explicitly isolated eval workspace;
- treat token count, latency, popularity, or model-graded preference as proof;
- replay secret/private fixtures through hosted providers without the normal routing policy;
- replace domain-specific tests, game playtests, visual inspection, or release gates.

## 3. Core invariants

### 3.1 Evidence before efficiency

A cheaper or faster run may not beat a run that satisfies required proof when it does not.

Comparison order is:

1. required proof gates;
2. required acceptance checks;
3. regressions and invariant violations;
4. repair cycles;
5. token usage when observed;
6. wall-clock duration when observed.

Cost metrics are tie-breakers after correctness and evidence, never compensation for failed proof.

### 3.2 No single magic score

v0.1 emits a structured result and verdict. It does not collapse all dimensions into one weighted scalar.

This prevents a configuration from "winning" by trading a blocker for lower token use.

### 3.3 Deterministic case identity

Each eval case has a stable opaque `id` and schema version. The case definition is versioned in Git. A result binds to:

- eval case id;
- eval case content digest;
- candidate id;
- candidate revision or digest when available;
- project/fixture revision when available;
- exact evidence paths and hashes when available.

### 3.4 Candidate output is not proof

Worker, reviewer, scorer, or judge-model text remains advisory unless a case explicitly declares it as a non-authoritative diagnostic metric.

P0-P5 evidence, deterministic tests, runtime observations, and explicitly required human/orchestrator inspection remain authoritative.

### 3.5 Champion remains canonical until promotion

A challenger may be evaluated without changing normal routing. Evaluation results can recommend `PROMOTE`, `HOLD`, or `REJECT`, but v0.1 does not update the canonical skill registry automatically.

## 4. Repository layout

```text
.agents/skills/mado-loop/evals/
  README.md
  schema/
    eval-case.schema.json
    eval-result.schema.json
  cases/
    <domain>/
      <case-id>/
        case.json
        task.md
        fixture/        # optional, immutable input fixture
        expected/       # optional golden/non-secret deterministic assets

docs/
  MADO_EVALS_SPEC.md
```

Generated run artifacts should not be committed by default:

```text
.mado-loop/evals/
  runs/<run-id>/
    manifest.json
    evidence/
    result.json
  comparisons/<comparison-id>.json
```

A future corpus may commit small canonical `result` snapshots when they are intentionally used as regression fixtures, but live logs, screenshots, videos, credentials, prompts, and private source must not be committed implicitly.

## 5. Eval case contract

The machine-readable case is `case.json`. Human task wording lives in `task.md` so it can evolve independently while remaining digest-bound.

Required fields:

- `schema_version`: `"0.1"`
- `id`: stable id such as `ui.settings-menu.basic`
- `title`: human-readable name
- `domains`: one or more MADO LOOP task domains
- `task_file`: repository-relative path from the case directory, normally `task.md`
- `required_proof`: ordered subset of `P0` through `P5`
- `acceptance`: deterministic acceptance checks with stable ids
- `policy`: execution restrictions for the case

Optional fields include fixture path, expected artifact paths, tags, allowed platforms, timeout, and observational metrics.

### 5.1 Acceptance checks

An acceptance check is intentionally small:

```json
{
  "id": "ui.quit-button-visible",
  "kind": "evidence",
  "required": true,
  "description": "A visible QUIT button exists in the running UI"
}
```

v0.1 check kinds are:

- `proof`: satisfied by a named P0-P5 proof result;
- `test`: deterministic command/test receipt supplied by the runner;
- `artifact`: required path/hash/schema property;
- `evidence`: runtime/screenshot/video/interaction evidence requiring an adapter or explicit inspection;
- `invariant`: property that must remain true and is treated as a regression gate.

The schema describes the contract. Domain adapters decide how a check is actually observed.

## 6. Eval result contract

Each candidate run emits `result.json` with:

- run and case identity;
- candidate identity;
- `status`: `PASS`, `WARN`, `UNKNOWN`, or `FAIL`;
- required proof outcomes;
- acceptance outcomes;
- regression/invariant outcomes;
- evidence references;
- repair cycles;
- observed tokens, if trustworthy and available;
- observed wall time, if available;
- failure signatures;
- environment summary that contains no credentials;
- `proof_status` separate from transport/execution status.

Missing evidence must become `UNKNOWN`; it must not be inferred as `PASS`.

## 7. Comparison semantics

Champion/challenger comparison is lexicographic, not weighted.

### Gate A: required proof

A challenger cannot be recommended for promotion if it newly fails or loses a required proof gate that the champion satisfies.

### Gate B: required acceptance

A challenger cannot be recommended for promotion with a new required acceptance failure.

### Gate C: regression invariants

Any new required invariant failure yields `REJECT` unless the case definition itself changed and therefore requires a new baseline.

### Gate D: stability

When hard gates are equivalent, compare:

- fewer `UNKNOWN` outcomes;
- fewer repair cycles;
- fewer repeated failure signatures.

### Gate E: efficiency

Only after the above are non-inferior may observed tokens and wall time be used as tie-breakers.

Efficiency changes should be reported as deltas, not converted into proof.

## 8. Champion / challenger verdicts

Comparison emits one of:

- `PROMOTE_CANDIDATE`: challenger is non-inferior on all hard gates and improves at least one declared dimension;
- `HOLD`: evidence is equivalent, insufficient, noisy, or mixed;
- `REJECT`: challenger introduces a hard regression;
- `UNKNOWN`: the comparison cannot be completed with available evidence.

`PROMOTE_CANDIDATE` is advisory. Promotion remains an orchestrator/human-controlled repository change in v0.1.

## 9. Relationship to live skill feedback

The existing `.mado-loop/skill_feedback.jsonl` and `skill_stats.json` remain a separate live-usage signal.

MADO EVALS must not write synthetic replay results into the live feedback ledger as if they were user task receipts.

Future routing may consume both sources with explicit provenance:

```text
semantic match
  + bounded live feedback nudge
  + eval qualification / regression state
  -> routing recommendation
```

Eval qualification may disqualify a known-regressing challenger, but it must not create a semantic candidate that the task router would not otherwise select.

## 10. Privacy and data policy

Eval artifacts follow the strictest sensitivity of the task, fixture, and generated evidence.

- `secret`: local-only providers and local artifacts unless the user explicitly changes policy;
- `private`: only providers allowed by the existing MADO routing policy;
- `public`: normal allowed provider set.

No eval manifest or aggregate should contain API keys, full prompts by default, private source blobs, model credentials, or raw user data.

Hashes and opaque identifiers are preferred for provenance.

## 11. Runner phases

The implementation sequence is intentionally bounded.

### Phase 0: Case contract

- schemas;
- static validator;
- canonical digest;
- deterministic manifest.

No model calls are required.

### Phase 1: Eval runner

- create disposable workspace;
- materialize fixture;
- invoke one bounded candidate configuration;
- collect receipts/evidence;
- emit `result.json`.

A failed runner must preserve enough artifact metadata to diagnose the failure without claiming task failure equals product failure.

### Phase 2: Evidence scorer

- map proof results and acceptance checks into result status;
- never infer missing evidence;
- produce stable failure signatures;
- report efficiency metrics independently.

### Phase 3: Regression comparator

- compare two results for the same case digest;
- emit gate-by-gate deltas and verdict;
- reject incomparable case revisions unless an explicit migration/baseline action is used.

### Phase 4: Champion / challenger suite

- replay a selected corpus against champion and challenger;
- aggregate hard regressions first;
- emit `PROMOTE_CANDIDATE`, `HOLD`, `REJECT`, or `UNKNOWN`;
- never mutate the canonical skill automatically.

### Phase 5: MADO LOOP integration

- optional eval qualification in skill routing;
- final receipts record eval provenance when a qualified challenger is intentionally used;
- release audit can require a named eval suite.

## 12. Initial corpus strategy

Do not start with hundreds of synthetic cases. Begin with 5-10 high-value cases derived from real MADO LOOP failure modes.

Suggested first set:

1. `ui.visible-control` - visible UI change + P2/P3 evidence;
2. `gameplay.dash-regression` - gameplay change without changing unrelated enemy behavior;
3. `playtest.first-time-entry` - game-test-player black-box first-time flow;
4. `visual.reference-to-ui` - reference-driven UI with layout/legibility evidence;
5. `release.windows-export` - P0-P5/release artifact audit;
6. `routing.skill-selection` - deterministic skill routing with no unrelated-skill introduction.

Each case should exist because it protects a real behavior, not because it is easy to score.

## 13. v0.1 success criteria

MADO EVALS v0.1 is complete when:

- eval case and result schemas are versioned;
- malformed cases fail deterministically before execution;
- a case digest binds results to the exact contract;
- at least three real cases can be replayed without model-as-judge authority;
- champion/challenger comparison detects an intentional regression;
- missing evidence becomes `UNKNOWN` rather than accidental `PASS`;
- token/time metrics cannot override failed proof;
- no replay result contaminates the live feedback ledger;
- CI can validate schemas and deterministic comparison logic without external model calls.

## 14. Next implementation slice

The first code slice after this spec is deliberately small:

```text
case.json
   |
   v
validate_eval_case.py
   |
   +--> canonical normalized payload
   +--> SHA-256 case digest
   +--> deterministic manifest stub
```

Then add `eval_result.py`, followed by `compare_eval_results.py`. Only after those deterministic pieces are tested should the runner invoke Codex, Godot, game-test-player, Visual Broker, or other external adapters.
