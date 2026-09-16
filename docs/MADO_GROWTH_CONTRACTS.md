# MADO Growth Contracts

Status: design sketch

This document turns the Growth Architecture into a small set of interoperable contracts. It intentionally stops before implementation schemas. The purpose is to stabilize semantics first so future models, agents, tools, and storage formats can change without rewriting MADO's core meaning.

See [MADO_LOOP_GROWTH_ARCHITECTURE.md](MADO_LOOP_GROWTH_ARCHITECTURE.md).

---

## 1. Contract graph

```text
IntentContract
      |
      +------------------------+
      |                        |
      v                        v
AuthorityContract       WorldStateQuery
      |                        |
      +------------+-----------+
                   |
                   v
          CapabilityManifest[]
                   |
                   v
             StrategyPlan
                   |
                   v
              Execution
                   |
                   v
            EvidenceRecord[]
                   |
                   v
             Completion
                   |
            +------+------+
            |             |
            v             v
      Live Feedback   ExperimentRecord
                          |
                          v
                     GrowthDecision
```

No edge in this graph implies permission escalation. Authority remains an independent gate at every execution boundary.

---

## 2. IntentContract

### Purpose

Describe **what must become true** without over-specifying how an agent should make it true.

### Stable semantics

```yaml
intent:
  schema_version: "future"
  id: task-024
  goal: Add a player dash without changing enemy behavior
  constraints:
    - Do not change enemy behavior
  acceptance:
    - id: dash.transition
      required: true
      claim: dash input changes player state as specified
    - id: enemy.invariant
      required: true
      claim: existing enemy behavior remains unchanged
  required_proof: P3
  sensitivity: private
  preferences:
    cost: balanced
    latency: interactive
```

### Must not contain

- mandatory model brand unless explicitly requested by the user;
- mandatory worker count unless worker topology itself is the task;
- prompt implementation details;
- implicit permission grants;
- acceptance rules invented solely to fit a chosen strategy.

### Design test

Two radically different agents should be able to satisfy the same IntentContract.

---

## 3. AuthorityContract

### Purpose

Define what actions are permitted independently of agent intelligence.

### Conceptual shape

```yaml
authority:
  subject: runtime.primary-agent
  scope:
    read:
      - repo
      - approved_context
    write:
      - isolated_workspace
    execute:
      - approved_tools
    network: allowed
    install: denied
    integrate: denied
    merge: denied
    publish: denied
  sensitivity_ceiling: private
  expires_on: task_end
```

### Core properties

- explicit subject;
- explicit scope;
- explicit lifetime;
- sensitivity ceiling;
- provenance of grant;
- optional revocation condition.

### Non-transitivity

If Agent A may delegate to Agent B, B does not automatically inherit all of A's authority.

Delegation requires an explicit derived AuthorityContract whose permissions are equal to or narrower than the parent's grant.

### Permanent invariant

```text
child_authority <= parent_authority <= owner_policy
```

---

## 4. CapabilityManifest

### Purpose

Describe **what a participant can do** and how MADO can verify that the capability is available.

### Capability kinds

Initial conceptual kinds:

- `agent`
- `skill`
- `tool`
- `engine`
- `observer`
- `adapter`
- `environment`

This list should remain extensible.

### Conceptual shape

```yaml
capability:
  schema_version: "future"
  id: runtime.agent.primary
  kind: agent
  provenance:
    provider: configured-provider
    implementation: configured-model-or-runtime
    version: optional
  features:
    coding: true
    vision: true
    computer_use: true
    async_tools: true
    subagents: true
  requirements:
    network: true
    credentials: external
  sensitivity_support:
    - public
    - private
  evidence_interfaces:
    - tool_receipt
    - test_result
    - screenshot
  availability:
    state: declared
    probe_id: agent.basic-capability-probe
```

### Availability states

Suggested lifecycle:

```text
UNKNOWN
DECLARED
PROBED
QUALIFIED
DEGRADED
UNAVAILABLE
RETIRED
```

`QUALIFIED` should always be scoped.

Example:

```yaml
qualification:
  scope: ui.smoke-observation
  state: qualified
  evidence: exp-881
```

This must not imply qualification for unrelated scopes such as release publication.

### Provider/model boundary

Provider and model/runtime identity are provenance. Semantic strategy selection should depend on capability and policy.

---

## 5. StateRecord

### Purpose

Store durable, source-bound facts or decisions without turning MADO into a prose-memory warehouse.

### Record classes

Possible classes:

- observed fact;
- accepted decision;
- artifact identity;
- known risk;
- requirement state;
- proof reference;
- capability qualification;
- invalidation event.

### Conceptual shape

```yaml
state_record:
  id: fact.engine.version
  class: fact
  key: project.engine.version
  value: 4.7.2
  provenance:
    source: project.godot
    observed_at: 2026-09-17T00:00:00+09:00
    bound_revision: sha256:...
  confidence: observed
  invalidation:
    on_source_change: project.godot
  sensitivity: public
```

### Confidence classes

Suggested non-numeric classes:

- `observed`
- `derived`
- `declared`
- `advisory`

Important claims should prefer `observed` or a clearly traceable derivation.

### Invalidation first

A stale fact should become invalid/unknown, not quietly survive because it was once true.

---

## 6. StrategyPlan

### Purpose

Describe a chosen approach for satisfying an intent with currently available and authorized capabilities.

The plan is **not** proof and **not** permanent architecture.

### Conceptual shape

```yaml
strategy_plan:
  id: plan-204
  intent_id: task-024
  strategy: direct-agent-with-tools
  capabilities:
    - runtime.agent.primary
    - engine.godot
    - tool.git
  delegation: []
  expected_observations:
    - P0
    - P1
    - P3
  rationale:
    coordination: single_agent_sufficient
```

### Candidate strategies

Current/future examples:

- direct agent;
- deterministic tool-only path;
- direct agent + tools;
- proposal specialist;
- fixed swarm;
- adaptive swarm;
- isolated mutation agent;
- computer-use loop;
- planner/executor split;
- future native runtime.

### Least-coordination principle

If two strategies are expected to satisfy the same contract, prefer the one with less coordination unless evidence shows the extra coordination improves outcomes enough to justify itself.

This is a preference, not a correctness rule.

---

## 7. EvidenceRecord

### Purpose

Bind a claim to an observation.

### Conceptual shape

```yaml
evidence:
  id: ev-203
  claim_id: dash.transition
  kind: runtime_observation
  status: PASS
  authority_class: deterministic-runtime
  provenance:
    producer: engine.godot.adapter
    observed_at: ...
    bound_revision: ...
  artifacts:
    - path: evidence/run.json
      sha256: ...
  environment:
    engine_version: 4.7.2
```

### Evidence authority

Different evidence sources can support different claim classes.

Examples:

- parser/test runner for deterministic static claims;
- runtime adapter for state transitions;
- screenshot plus visual observer for visible layout claims;
- video/temporal observer for motion claims;
- release audit for artifact claims.

A model statement can be attached as advisory evidence but does not automatically become authoritative evidence.

### Evidence aggregation

Aggregators may combine records, but the original provenance must remain inspectable.

---

## 8. ExperimentRecord

### Purpose

Describe a replayable comparison of one complete candidate configuration.

### Candidate identity

Candidate identity may include:

```yaml
candidate:
  model_runtime: ...
  reasoning_profile: ...
  skills:
    - id: game-ui
      version: ...
  strategy: direct-agent-with-tools
  adapters:
    godot: ...
  context_policy: retrieve-minimal-state
```

Not every field must be present. The record should include only dimensions intentionally varied or required for provenance.

### Experiment identity

```yaml
experiment:
  id: exp-881
  case_digest: sha256:...
  intent_digest: sha256:...
  authority_digest: sha256:...
  environment_digest: sha256:...
  candidate_digest: sha256:...
```

### Comparison order

Experiments preserve lexicographic evidence-first comparison:

1. authority/safety violations;
2. required proof;
3. required acceptance;
4. regressions/invariants;
5. UNKNOWN/stability/repair behavior;
6. efficiency;
7. advisory preference.

No single weighted score is required.

---

## 9. GrowthDecision

### Purpose

Record what MADO has learned about a capability/configuration without automatically granting it broader power.

### Decision types

```text
QUALIFY
CANARY
ADOPT
HOLD
DEGRADE
RETIRE
```

### Conceptual shape

```yaml
growth_decision:
  id: growth-091
  subject: runtime.agent.primary
  decision: QUALIFY
  scope: ui.smoke-observation
  basis:
    experiments:
      - exp-881
      - exp-886
  restrictions:
    publish: false
    merge: false
  approved_by: explicit-promotion-boundary
```

### Scope is mandatory

A qualification such as `ui.smoke-observation` does not imply qualification for `code-mutation`, `release-audit`, or `publish`.

### Authority separation

A GrowthDecision can influence strategy selection but may not create permissions absent from AuthorityContract.

---

## 10. Completion contract

Completion is computed from Intent + Evidence, not from StrategyPlan self-report.

Conceptually:

```text
required acceptance claims
        +
required proof level
        +
required invariants
        +
valid provenance
        |
        v
PASS / WARN / UNKNOWN / FAIL
```

Strategy transport success is a separate diagnostic signal.

Examples:

```text
agent call succeeded + runtime not observed = UNKNOWN
agent call failed + deterministic test proves regression = FAIL
agent call succeeded + all required evidence passes = PASS
```

---

## 11. Delegation contract

Delegation should become a derived contract, not a free-form recursive behavior.

A delegation request needs:

- bounded subgoal;
- derived authority;
- sensitivity;
- available context;
- expected output type;
- evidence expectations;
- termination condition.

Conceptually:

```yaml
delegation:
  id: subtask-2
  parent_intent: task-024
  goal: Inspect dash-state implementation options
  authority:
    read_repo: true
    mutate: false
  output: proposal
  proof_authority: none
```

This lets future agents delegate dynamically without turning delegation into unbounded authority inheritance.

---

## 12. Capability probing contract

A probe asks whether a declared capability can perform a narrowly defined operation now.

Probe properties:

- bounded;
- cheap relative to real work;
- non-destructive by default;
- explicit success evidence;
- no authority escalation;
- expiration/recheck semantics when relevant.

Example:

```yaml
probe:
  id: computer-use.basic-screen-observation
  requires:
    - screenshot capability
  action: inspect a controlled fixture
  success_claim: expected marker is observable
  expiry: session
```

A failed probe should usually degrade availability to `UNKNOWN`, `DEGRADED`, or `UNAVAILABLE` depending on the failure evidence. It should not imply the underlying model is globally incapable.

---

## 13. Strategy resolver inputs

The future resolver should consume contracts rather than provider-brand conditionals.

```text
IntentContract
AuthorityContract
qualified CapabilityManifest set
relevant StateRecords
current environment
budget preference
live-feedback summary with provenance
MADO LAB qualification state
```

The output is a StrategyPlan.

### Resolver constraints

It must not:

- create capabilities that are not available;
- grant authority;
- lower proof requirements;
- route secret data through a capability without matching sensitivity support;
- treat historical success as semantic task relevance;
- require a swarm merely because swarm support exists.

---

## 14. Stable IDs and versioning

Contracts should use stable opaque or semantic IDs and explicit schema versions.

Versioning rules should favor compatibility:

- additive optional fields: compatible minor evolution;
- changed meaning: new schema version;
- changed evidence authority: explicit migration;
- changed acceptance semantics: new intent/case digest;
- changed capability qualification: new qualification record rather than silent mutation of history.

Historical experiment records should remain interpretable after newer contract versions appear.

---

## 15. What should remain free-form

Not everything should become a schema.

Free-form/advisory content may include:

- model reasoning summaries;
- implementation proposals;
- reviewer commentary;
- design alternatives;
- task-specific notes;
- creative direction.

Schemas should protect boundaries and provenance, not suffocate useful intelligence.

A useful rule is:

> **Structure what must be trusted or compared. Leave exploratory thought flexible.**

---

## 16. First implementation candidate

When architecture discussion stabilizes, the first implementation should probably be **CapabilityManifest v2**, not a new orchestrator.

Why:

1. current MADO already has a capability registry;
2. provider and model identity are already partially separated;
3. every future strategy depends on knowing what is actually available;
4. capability manifests can initially wrap existing behavior without changing execution;
5. they create a migration path away from model-name-specific branching.

A small G1 experiment should answer only:

> Can current MADO capabilities be represented, probed, and resolved without changing existing proof or authority behavior?

If yes, the architecture has a safe first foothold.
