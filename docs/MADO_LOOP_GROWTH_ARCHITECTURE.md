# MADO LOOP Growth Architecture

Status: design draft

MADO LOOP should not be optimized for one generation of AI models. It should remain useful while models, tools, context systems, computer-use agents, multimodal systems, and agent runtimes continue to improve.

The design target is therefore not a larger orchestration framework. It is a **small evidence-driven kernel that lets changing intelligence safely act on reality, learn from outcomes, and replace obsolete machinery without weakening authority or proof**.

This document defines that growth architecture.

---

## 1. North star

MADO LOOP exists to connect five things that should remain distinct even as AI becomes much more capable:

1. **Intent** — what is being attempted and what counts as done.
2. **Capability** — what available agents, skills, tools, and environments can actually do.
3. **Authority** — what each participant is allowed to read, change, execute, publish, or decide.
4. **Reality** — the repository, engine, application, files, processes, and external systems that can be observed.
5. **Evidence** — what was actually observed strongly enough to support a claim.

A model may become dramatically more intelligent without automatically receiving more authority. A model may claim success without producing evidence. A new tool may be available without being trusted for a particular task. These separations are permanent MADO responsibilities.

The long-term north star is:

> **MADO LOOP is an evidence-driven runtime for evolving AI agents.**

It should become thinner as upstream intelligence becomes stronger.

---

## 2. The 10x-intelligence test

Every major MADO subsystem should be challenged with this question:

> If the primary AI becomes 10x more capable next year, does this subsystem still need to exist?

There are three acceptable answers.

### A. Yes: keep it in the kernel

Examples:

- intent and completion contracts;
- authority and sensitivity policy;
- capability discovery and compatibility;
- evidence provenance;
- state binding and invalidation;
- isolated mutation boundaries;
- release/publish authority;
- experiment provenance.

These solve coordination, trust, and reality-binding problems rather than intelligence shortages.

### B. It becomes smaller: keep it behind an interface

Examples:

- task decomposition;
- routing heuristics;
- worker composition;
- prompt construction;
- context selection;
- retry strategy;
- visual-inspection strategy.

A stronger agent may perform these directly, so MADO should expose contracts rather than hard-code an elaborate implementation.

### C. No: make it removable

Examples may eventually include:

- provider-specific role tables;
- model-specific prompt tuning;
- fixed swarm topologies;
- manual context-packing helpers;
- redundant adapters superseded by native agent capabilities.

Deletion of obsolete machinery is a successful growth outcome.

---

## 3. Architectural rule: stable trunk, replaceable branches

MADO is divided into a small stable trunk and replaceable branches.

```text
                         INTELLIGENCE
                 models / agents / future systems
                              |
                              v
+-----------------------------------------------------------+
|                    MADO STABLE TRUNK                      |
|                                                           |
| Intent -> Authority -> Capability -> State -> Evidence    |
|                                                           |
+-----------------------------------------------------------+
              |                 |                 |
              v                 v                 v
         STRATEGIES          ADAPTERS          MADO LAB
       replaceable        replaceable        experimental
              |                 |                 |
              +-----------------+-----------------+
                                |
                                v
                              REALITY
                  repo / Godot / Blender / web / OS
```

A strategy may disappear. An adapter may be replaced. A model may be retired. The stable trunk must continue to understand the goal, the permissions, the available capabilities, the observed state, and the evidence supporting the result.

---

## 4. Eight architectural layers

### Layer 1 — INTENT

The Intent layer describes the requested outcome without prescribing an unnecessary execution recipe.

An intent should be able to express:

- goal;
- constraints;
- required artifacts;
- acceptance criteria;
- prohibited changes;
- required proof strength;
- sensitivity;
- optional budget/time preferences.

Example conceptual contract:

```yaml
intent:
  id: task-024
  goal: Add a player dash without changing enemy behavior
  acceptance:
    - dash input produces the requested state transition
    - enemy behavior remains invariant
  required_proof: P3
  sensitivity: private
```

The intent says **what must become true**, not which model, worker count, or prompt template must be used.

#### Invariant

Execution strategy may change without changing intent semantics.

---

### Layer 2 — AUTHORITY

Authority is separate from intelligence and capability.

A participant can be highly capable while receiving narrowly bounded authority.

Authority examples:

```yaml
authority:
  read_repo: true
  mutate_isolated_workspace: true
  mutate_leader_checkout: false
  use_network: true
  publish_release: false
  merge_main: false
  install_tools: false
```

Authority also carries sensitivity and data-flow rules.

#### Permanent rule

> **No agent, skill, model, or tool may increase its own authority.**

It may propose an authority change. The policy owner must grant it through an explicit boundary.

This rule remains even if future models become substantially more reliable.

---

### Layer 3 — CAPABILITY BUS

The Capability Bus replaces model-name-centric architecture.

MADO asks:

> What can this participant do, under what conditions, with what evidence interface?

not:

> Is this Astra, Luna, Gemini, Claude, or model X?

A capability manifest should eventually describe dimensions such as:

```yaml
capability:
  id: agent.runtime.primary
  kind: agent
  features:
    coding: true
    vision: true
    computer_use: true
    async_tools: true
    long_context: true
    subagents: true
  execution:
    mutating: true
    network: true
  evidence_interfaces:
    - tool_receipt
    - screenshot
    - test_result
  cost_class: premium
  latency_class: medium
```

Model/provider identity remains provenance and configuration, not the semantic role.

#### Capability lifecycle

```text
DISCOVER
  -> DECLARE
  -> PROBE
  -> QUALIFY
  -> USE
  -> RECHECK
  -> DEGRADE / RETIRE
```

Static declarations are not sufficient for critical capabilities. MADO may require bounded probes before considering a capability available.

#### Compatibility with current MADO

The existing capability registry already separates provider capability from transient model identity. Growth Architecture extends this principle so the registry becomes machine-readable, probeable, and versioned rather than replacing it wholesale.

---

### Layer 4 — AGENT RUNTIME / STRATEGY

The runtime chooses **how** to satisfy an intent using currently qualified capabilities.

This layer is replaceable.

Possible strategies include:

- one strong agent;
- one agent plus deterministic tools;
- planner + executor;
- specialist delegation;
- parallel proposal swarm;
- isolated mutation workers;
- computer-use loop;
- future native agent runtime.

The default growth rule is:

> **Single agent first. Add coordination only when measured leverage justifies coordination cost.**

Multi-agent execution is therefore a strategy, not an architectural assumption.

#### Strategy contract

Every strategy must respect the same:

- intent;
- authority policy;
- sensitivity policy;
- capability requirements;
- evidence requirements;
- completion contract.

A strategy cannot lower acceptance or proof requirements in order to make itself succeed.

#### Adaptive execution

The runtime may re-plan after observations:

```text
intent
  -> inspect
  -> choose next useful action
  -> observe
  -> update working hypothesis
  -> continue / delegate / stop
```

MADO should avoid forcing a fixed universal sequence when the agent can plan effectively. The familiar

`UNDERSTAND -> ROUTE -> MAKE -> INTEGRATE -> RUN -> INSPECT -> VERIFY -> FIX -> PROVE`

remains a conceptual lifecycle, not a mandatory instruction-by-instruction pipeline.

---

### Layer 5 — WORLD STATE

MADO should retain **state, not prose memory**.

Durable state contains externally checkable facts and decisions such as:

- repository revision;
- architecture facts;
- accepted decisions;
- artifact identities;
- requirement state;
- known risks;
- environment capabilities;
- proof history;
- invalidated assumptions.

Conceptual state record:

```yaml
fact:
  id: project.engine-version
  value: 4.7.2
  source: project.godot
  observed_at: 2026-09-17T00:00:00+09:00
  bound_to: sha256:...
  confidence: observed
  invalidates_on:
    - project.godot change
```

#### State properties

Every durable fact should have, where applicable:

- source;
- observation time;
- revision/hash binding;
- confidence class;
- invalidation rule;
- sensitivity.

This lets future agents retrieve compact truth without inheriting stale narrative context.

#### Model memory boundary

Native model memory or long-context features are welcome but remain an optimization. They do not replace source-bound MADO state for claims that matter to execution or proof.

---

### Layer 6 — EXECUTION & ADAPTERS

Adapters connect MADO contracts to reality.

Examples:

- repository/Git;
- Godot;
- Blender;
- browser/computer use;
- image generation/editing;
- test runners;
- package/release tooling;
- external playtest observers;
- future native agent tools.

Adapters should be thin and replaceable. They should translate between MADO contracts and external systems rather than own orchestration policy.

#### Adapter rule

A new native capability should be able to replace an old adapter without changing:

- intent semantics;
- authority semantics;
- evidence semantics;
- completion semantics.

#### Mutation rule

Mutation must remain isolated when the caller lacks direct leader authority. The existing OVP worktree boundary is a useful implementation of this principle, not the only possible future implementation.

---

### Layer 7 — EVIDENCE

Evidence is MADO's connection to reality.

The current P0-P5 ladder remains valuable because it represents increasingly strong classes of externally observable proof:

- P0 static;
- P1 runtime;
- P2 layout/static visual;
- P3 behavior;
- P4 temporal visual/motion;
- P5 release artifact.

Growth Architecture treats P0-P5 as an evidence taxonomy rather than a model-evaluation score.

A future agent can be vastly smarter while still needing to demonstrate that a game boots, a button is visible, a state transition occurred, an animation behaved correctly, or a release artifact exists.

#### Evidence record

Evidence should carry:

```yaml
evidence:
  id: ev-203
  kind: runtime_observation
  claim: dash-transition-occurs
  status: PASS
  source: godot-adapter
  artifact: evidence/run-203.json
  sha256: ...
  environment: ...
  bound_revision: ...
```

#### Permanent rules

- Missing evidence is not PASS.
- Agent confidence is not proof.
- Transport success is not product success.
- A reviewer model cannot silently become proof authority.
- Evidence authority is explicit per claim type.

---

### Layer 8 — MADO LAB

MADO EVALS grows into the broader experimental layer called **MADO LAB**.

MADO LAB asks:

> Under the same intent, authority, environment, and evidence contract, did this candidate configuration actually improve?

A candidate configuration can include more than a Skill:

```yaml
experiment:
  model: ...
  agent_runtime: ...
  reasoning_profile: ...
  skills: ...
  tools: ...
  context_strategy: ...
  execution_strategy: ...
  adapter_versions: ...
```

MADO LAB can therefore compare:

- model generations;
- Skill versions;
- prompts;
- reasoning settings;
- context selection;
- single-agent vs multi-agent strategy;
- adapters;
- tool combinations;
- routing policy;
- future systems not yet known.

#### Existing MADO EVALS is retained

The current MADO EVALS contracts remain useful as the first substrate:

`TASK -> EVIDENCE -> EVALUATE -> COMPARE`

They should be generalized, not discarded.

Champion/challenger remains one experiment pattern inside MADO LAB rather than the definition of the whole system.

#### No magic score

MADO LAB preserves the current evidence-first lexicographic principle:

1. authority/safety violations;
2. required proof;
3. required acceptance;
4. regressions/invariants;
5. stability/unknowns/repair cycles;
6. efficiency and cost;
7. advisory preference metrics.

A cheaper candidate cannot compensate for a correctness regression.

---

## 5. The growth loop

MADO's own evolution should follow a bounded lifecycle.

```text
NEW CAPABILITY / STRATEGY / SKILL
            |
            v
        DISCOVER
            |
            v
          PROBE
            |
            v
         SANDBOX
            |
            v
         EVIDENCE
            |
            v
         QUALIFY
            |
            v
          CANARY
            |
            v
          ADOPT
            |
            v
      OBSERVE IN USE
            |
       +----+----+
       |         |
       v         v
     KEEP      PRUNE
```

### Discover

Learn that a new capability exists. Discovery alone grants no authority.

### Probe

Run a minimal bounded capability test where practical.

### Sandbox

Exercise the candidate away from canonical state.

### Evidence

Collect the same types of evidence trusted in normal execution.

### Qualify

Declare where the candidate is safe and useful. Qualification is scoped, not universal.

### Canary

Use on a narrow slice of real work while keeping rollback simple.

### Adopt

Allow normal strategy selection to choose it.

### Observe

Keep provenance-aware live results separate from replay experiments.

### Prune

Retire redundant prompts, adapters, role tables, or routing logic when evidence shows they no longer add value.

Pruning is part of the architecture, not cleanup after the architecture.

---

## 6. Core contracts

Growth Architecture should converge on a small set of versioned contracts.

### 6.1 IntentContract

Defines goal, constraints, acceptance, sensitivity, and proof requirement.

### 6.2 AuthorityContract

Defines allowed reads, writes, network access, process execution, installation, integration, merge, and publish actions.

### 6.3 CapabilityManifest

Defines features, execution requirements, evidence interfaces, availability/probe state, provider/model provenance, and compatibility.

### 6.4 StateRecord

Defines source-bound durable world facts and invalidation semantics.

### 6.5 StrategyPlan

Defines the chosen execution approach and which qualified capabilities it intends to use. Strategy plans are advisory until executed and observed.

### 6.6 EvidenceRecord

Defines observable support for a claim and binds it to artifacts/environment/revision.

### 6.7 ExperimentRecord

Defines a replayable candidate configuration, input identity, results, and provenance.

### 6.8 GrowthDecision

Defines a scoped decision such as:

- qualify;
- canary;
- adopt;
- hold;
- degrade;
- retire.

A GrowthDecision never grants more authority than the governing AuthorityContract permits.

---

## 7. Authority matrix for future agents

MADO should make the distinction between intelligence and authority visible.

| Action | Observer | Proposal agent | Isolated mutation agent | Integrator | Human/owner |
| --- | --- | --- | --- | --- | --- |
| Read allowed context | yes | yes | yes | yes | yes |
| Run approved observations | yes | yes | yes | yes | yes |
| Propose change | yes | yes | yes | yes | yes |
| Mutate isolated workspace | no | no | scoped | yes | yes |
| Mutate leader state | no | no | no | scoped | yes |
| Change acceptance criteria | no | no | no | no by default | yes |
| Increase own permissions | no | no | no | no | policy owner only |
| Merge/publish | no | no | no | explicit only | yes |
| Declare proof without evidence | no | no | no | no | no |

The concrete roles may change over time. The authority distinctions should not.

---

## 8. Strategy selection without model lock-in

Current model/provider routing should gradually become a resolver over capabilities and policy.

Conceptually:

```text
Intent
  + Authority
  + Qualified capabilities
  + Current environment
  + Budget preference
  + Historical evidence
        |
        v
  Strategy Resolver
        |
        +-> one agent
        +-> agent + deterministic tools
        +-> specialist delegation
        +-> parallel proposal
        +-> isolated mutation
        +-> computer-use path
        +-> future strategy
```

The resolver should prefer the **least coordination that satisfies the contract**.

This avoids building permanent complexity around temporary model limitations.

---

## 9. World-state retrieval instead of context hoarding

Future models may have much larger context windows and better native memory. MADO should still avoid dumping the entire project history into every task.

The preferred pattern is:

```text
Intent
  -> determine required facts
  -> retrieve source-bound state
  -> inspect live source when stale or missing
  -> act
  -> write back only durable facts/decisions/evidence
```

This resembles a small queryable project world model, not a giant diary.

Possible future layout:

```text
.mado/
  state/
    facts.jsonl
    decisions.jsonl
    artifacts.jsonl
    risks.jsonl
    capabilities.json
    proof-index.jsonl
```

The exact storage format is deliberately not fixed by this design document.

---

## 10. Self-improvement boundary

MADO may eventually help create or modify its own Skills, prompts, adapters, strategies, and tests.

It must distinguish **self-improvement proposal** from **self-authorized self-modification**.

Allowed growth pattern:

```text
observe weakness
  -> propose candidate
  -> isolate candidate
  -> replay experiments
  -> collect evidence
  -> produce GrowthDecision proposal
  -> explicit promotion boundary
  -> monitor canary
```

Forbidden shortcut:

```text
model believes new version is better
  -> overwrite canonical MADO
```

Even highly capable future agents should pass through a promotion boundary for kernel, authority, evidence, and release-policy changes.

---

## 11. Failure semantics

Growth Architecture preserves conservative result semantics.

### FAIL

Observed evidence contradicts a required claim or invariant.

### UNKNOWN

Required observation could not be obtained or provenance is insufficient.

### WARN

Requested outcome is substantially supported but a declared non-blocking issue remains.

### PASS

The required claim is supported at the requested evidence strength.

Infrastructure failure must not be silently transformed into product failure, and product failure must not be hidden as infrastructure uncertainty.

---

## 12. Relationship to current MADO LOOP components

### P0-P5 proof ladder

**Keep.** It belongs close to the stable trunk because better intelligence does not eliminate the need to bind claims to reality.

### OVP isolated mutation runtime

**Keep the principle, loosen the implementation.** Isolation, scope, receipts, review, and post-integration proof are durable. The exact Git/worktree mechanics may eventually be replaced.

### Capability registry

**Evolve.** Move from primarily human-readable capability rows toward versioned `CapabilityManifest` records with probes and qualification state.

### Provider router

**Shrink over time.** Provider/model-specific policy remains useful, but semantic routing should target capabilities rather than model names.

### Fixed / adaptive swarm

**Demote to strategies.** They are useful implementations today, not permanent architecture.

### Skill feedback ledger

**Keep provenance separation.** Live usage is valuable but must remain distinguishable from replay experiments.

### MADO EVALS

**Generalize into MADO LAB.** Preserve case digests, evidence-first comparison, and no-magic-score semantics. Expand candidate identity from Skill-only changes to full runtime configurations.

### README's fixed lifecycle

**Reframe.** Keep it as a human mental model, while allowing runtime strategies to plan dynamically under the same contracts.

---

## 13. Migration plan

This architecture should be adopted incrementally. No flag day rewrite.

### Phase G0 — Architecture only

- agree on stable-trunk responsibilities;
- keep current runtime unchanged;
- mark provider/swarm specifics as replaceable strategy implementations;
- pause expansion that assumes a particular model generation.

### Phase G1 — Capability Manifest v2

Introduce a machine-readable capability schema that can represent current providers, local tools, Skills, Godot, computer use, vision, and future agents.

Existing capability registry remains the source until migrated.

Minimum fields:

- stable capability id;
- kind;
- declared features;
- authority requirements;
- sensitivity support;
- evidence interfaces;
- availability state;
- optional probe;
- provenance/version.

### Phase G2 — Strategy interface

Wrap current execution forms behind a common strategy contract:

- direct/single-agent;
- deterministic tool path;
- proposal worker;
- fixed swarm;
- adaptive swarm;
- OVP mutation.

Do not add more strategies until current ones can be compared under one contract.

### Phase G3 — Source-bound world state

Add a minimal state store for facts, decisions, proof references, and invalidation.

Start with a small number of high-value facts rather than automatic whole-project memory extraction.

### Phase G4 — MADO LAB generalization

Extend MADO EVALS so experiment identity can include model/runtime/Skill/tool/strategy configuration.

Retain evidence-first comparison and advisory promotion.

### Phase G5 — Capability qualification

Allow bounded probes and MADO LAB evidence to produce scoped qualification records.

Example:

```text
computer-use-agent X
qualified for: UI smoke observation
not qualified for: release publication
```

### Phase G6 — Evidence-informed strategy resolver

Let strategy selection use:

- intent requirements;
- authority;
- currently qualified capabilities;
- environment;
- live feedback provenance;
- MADO LAB qualification;
- budget preference.

Do not let historical statistics create semantic task relevance by themselves.

### Phase G7 — Pruning loop

Regularly identify machinery that no longer changes outcomes.

Candidates for removal might include:

- obsolete model-specific branches;
- redundant prompt wrappers;
- role splits no longer providing measurable leverage;
- adapters replaced by native capabilities;
- duplicated context plumbing.

A shrinking codebase can represent a stronger MADO LOOP.

---

## 14. What we should not build yet

Growth Architecture deliberately avoids premature implementation of:

- an autonomous system that rewrites canonical MADO without review;
- arbitrary dynamic tool installation;
- recursive unbounded agent spawning;
- a global scalar intelligence/quality score;
- giant automatically generated project memory;
- a permanent taxonomy of current model brands;
- provider-specific architecture in the stable trunk;
- automatic merge/release authority based only on eval performance;
- a universal workflow DSL before real strategy interfaces require one.

The goal is to create **optionality**, not speculative infrastructure.

---

## 15. Design invariants

These are intended to survive future MADO versions.

1. **Intent is independent of execution strategy.**
2. **Intelligence, capability, and authority are separate concepts.**
3. **Agents cannot grant themselves authority.**
4. **Model/provider identity is provenance, not architecture.**
5. **Single-agent execution is sufficient until additional coordination proves useful.**
6. **State must be source-bound and invalidatable when used for important claims.**
7. **Missing evidence is never silently upgraded to PASS.**
8. **Agent/reviewer opinion is not automatically proof authority.**
9. **Efficiency cannot compensate for required proof regressions.**
10. **Live feedback and replay experiments retain distinct provenance.**
11. **Self-improvement proposals pass through an explicit promotion boundary.**
12. **Replaceable strategies and adapters must remain replaceable.**
13. **Pruning obsolete machinery is a first-class growth operation.**
14. **The stable trunk should become smaller, not larger, as upstream AI improves.**

---

## 16. A future MADO session

A mature version may look conceptually like this:

```text
USER INTENT
    |
    v
IntentContract
    |
    +-> AuthorityContract
    |
    +-> query source-bound World State
    |
    +-> discover/probe qualified Capabilities
    |
    v
Strategy Resolver
    |
    +-> one strong agent, if sufficient
    |       |
    |       +-> tools / computer use / engine adapters
    |
    +-> bounded delegation only when useful
    |
    v
REAL EXECUTION
    |
    v
Evidence Records
    |
    +-> P0-P5 claims
    +-> acceptance/invariants
    |
    v
Completion
    |
    +-> live provenance feedback
    |
    +-> optional MADO LAB experiment data
    |
    v
GROWTH LOOP
  qualify / canary / adopt / prune
```

The interesting property is what is absent: there is no required permanent model brand, worker topology, or fixed step-by-step recipe.

---

## 17. Success criteria for the architecture

Growth Architecture is working when all of the following become true:

- a new model can be introduced mostly through capability/provenance configuration rather than core rewrites;
- a new native tool can replace an adapter without changing intent/evidence semantics;
- single-agent and multi-agent execution can satisfy the same completion contract;
- MADO can say that a capability is qualified for one scope but not another;
- stale project knowledge is invalidated rather than endlessly accumulated;
- an experiment can compare full runtime configurations, not only Skills;
- stronger models allow MADO to remove orchestration code safely;
- no increase in model intelligence silently expands permissions;
- final claims remain traceable to evidence rather than model confidence.

The final test is simple:

> **If tomorrow's AI is dramatically better than today's, MADO LOOP should become simpler to operate and simpler internally without losing safety, truthfulness, or evidence.**

That is the kind of system that can grow rather than merely accumulate features.
