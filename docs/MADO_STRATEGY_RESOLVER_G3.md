# MADO Advisory Strategy Resolver G3

Status: G3 shadow/advisory layer

G3 connects the future-facing contracts without taking control away from MADO LOOP 1.x.

Its central flow is:

```text
Intent Contract v1
        +
Authority Contract v1
        +
Capability Snapshot v1
        |
        v
Advisory Strategy Resolver
        |
        v
Strategy Candidate[]
        |
        +---- no execution
        +---- no authority grant
        +---- no provider/model selection
        +---- no proof downgrade
        |
        v
Shadow Compare <---- current routing policy / observed legacy plan
```

The current router remains authoritative.

G3 exists to answer a narrower question:

> Given the requested outcome, the authority ceiling, and the body MADO can observe right now, which strategy shapes are structurally possible, conditional, or blocked?

It does not answer which candidate is best.

---

## 1. Why G3 is advisory first

Replacing the current router immediately would combine several migrations at once:

- task semantics;
- authority semantics;
- capability semantics;
- provider policy;
- worker topology;
- proof expectations;
- runtime behavior.

That would make regressions difficult to attribute.

G3 therefore runs beside the current route.

```text
                    +--> current MADO 1.x routing ------+
Intent / task ------+                                   +--> compare
                    +--> G3 advisory candidates --------+
```

No live decision changes merely because G3 produces a candidate.

---

## 2. Contracts

### Intent Contract v1

G3 uses a deliberately small routing projection of the future IntentContract.

```json
{
  "schema_version": "1.0",
  "id": "task-024",
  "goal": "Add and verify a player dash",
  "domains": ["CODE", "GAMEPLAY"],
  "work_mode": "modify",
  "required_proof": "P3",
  "sensitivity": "private",
  "acceptance": [
    {
      "id": "dash.transition",
      "required": true,
      "claim": "dash input changes player state"
    }
  ],
  "preferences": {
    "coordination": "minimal"
  }
}
```

The new `work_mode` is not a worker topology.

It states the outcome class relevant to authority:

- `observe`
- `propose`
- `modify`
- `release`

A `modify` intent does not say which model should edit, how many agents should run, or which provider should be used.

### Authority Contract v1

```json
{
  "schema_version": "1.0",
  "subject": "runtime.primary-agent",
  "permissions": {
    "read_repo": true,
    "write_isolated_workspace": true,
    "write_repo": false,
    "execute_tools": true,
    "delegate": false,
    "network": false,
    "integrate": false,
    "merge": false,
    "publish": false
  },
  "sensitivity_ceiling": "private",
  "policy_tokens": [],
  "expires_on": "task_end"
}
```

G3 treats every permission as an upper bound.

A candidate cannot:

- turn `false` into `true`;
- create a policy token;
- increase the sensitivity ceiling;
- infer merge/publish permission from mutation permission;
- inherit authority from capability availability.

`policy_tokens` are references to already granted policy exceptions such as an explicit private hosted-worker consent. G3 does not create them.

---

## 3. Capability Snapshot semantics

G3 consumes the G2 Snapshot as the source of current body state.

The canonical CapabilityManifest registry is still loaded to interpret semantic fields such as:

- features;
- domains;
- sensitivity support;
- network requirements;
- policy requirements.

This is not an independent fourth routing input. The registry is accepted only when its canonical digest exactly matches `snapshot.registry_digest`.

```text
Snapshot.registry_digest
          |
          X mismatch -> configuration error
          |
          v
matching CapabilityManifest registry
```

This prevents a snapshot of one body from being interpreted using a different capability dictionary.

---

## 4. Candidate states

Each strategy candidate is one of:

### `READY`

All required features have at least one currently `PROBED` compatible binding and all relevant authority checks pass.

`READY` means:

> structurally available as an advisory candidate now.

It does **not** mean:

- qualified;
- proven correct;
- preferred;
- authorized to execute automatically;
- safe to merge or publish.

### `CONDITIONAL`

The shape is not authority-blocked, but at least one condition remains advisory, for example:

- required capability is only `DECLARED`;
- capability is degraded/unknown;
- multi-agent coordination is available but not preferred by Intent.

### `BLOCKED`

At least one hard structural boundary fails:

- missing capability;
- sensitivity ceiling violation;
- denied permission;
- required policy token absent;
- incompatible sensitivity;
- no network-safe capability match;
- unsupported mutation shape.

---

## 5. Current G3 strategy shapes

G3 v1 emits strategy **shapes**, not provider/model choices.

### `direct-agent-with-tools`

Single-coordination path through the MADO runtime and deterministic tools.

For `modify` intents G3 intentionally blocks this shape in v1. Mutation is advised through the isolated mutation boundary instead.

### `isolated-mutation-agent`

Only emitted for `modify` intents.

Requires:

- isolated-workspace write authority;
- tool execution authority;
- `workspace.isolated.mutation`;
- `repo.worktree`;
- `review.boundary`;
- domain/proof features.

This keeps G3's first mutation advice aligned with the existing OVP safety boundary.

### `single-delegate-proposal`

Adds semantic requirement:

```text
agent.delegate.proposal
```

It does not choose OpenRouter, NVIDIA, local, or any model.

Instead the candidate binding lists all currently compatible capability IDs satisfying that feature under:

- sensitivity;
- network authority;
- policy tokens;
- current availability.

Provider/model identity remains provenance behind those capabilities.

### `adaptive-swarm`

Requires both:

```text
agent.delegate.proposal
strategy.multi_agent.adaptive
```

Even when both are available, the candidate stays `CONDITIONAL` unless Intent explicitly uses:

```json
{"coordination": "parallel_ok"}
```

This encodes the Growth Architecture rule:

> Single Agent First. Multi-Agent When Useful.

Capability existence alone is not evidence that coordination cost is worthwhile.

---

## 6. Domain and proof feature projection

G3 currently uses a small deterministic mapping from semantic domains and required proof to capability features.

Examples:

```text
CODE      -> engine.project.inspect
GAMEPLAY  -> engine.project.inspect + engine.runtime.execute
UI        -> engine.project.inspect + evidence.layout
PLAYTEST  -> engine.runtime.execute
RELEASE   -> artifact.release.audit
```

Proof expectations are claim-relevant in G3 v1. Higher proof keeps the lower gates relevant to that claim, but does not blindly require every lower modality.

```text
P0 -> static evidence
P1 -> static + runtime execution
P2 -> static + runtime + layout evidence
P3 -> static + runtime + behavior evidence
P4 -> static + runtime + screenshot capture
P5 -> static + runtime + artifact export + release audit
```

This mirrors the proof ladder rule that irrelevant levels may be skipped explicitly. A P5 release candidate therefore does not automatically require P4 motion capture.

These mappings are deliberately inspectable policy, not model judgment.

They can later move into versioned strategy policy data after shadow evidence shows the right abstraction.

---

## 7. Qualification is visible but not self-promoting

G2 qualifications remain attached to candidate bindings as active qualification scopes.

G3 v1 does **not** require qualification for every candidate because most current capabilities have not yet passed through MADO LAB.

It also does not turn a probe into qualification.

```text
PROBED != QUALIFIED
READY  != QUALIFIED
```

A future G4/G5 policy may require scoped qualification for particular high-risk strategy features, but that must be explicit and evidence-backed.

---

## 8. Shadow comparison

`strategy_shadow_compare.py` runs both lenses without executing either route.

### Default legacy projection

Without an observed legacy plan, the shadow comparator reuses current deterministic code:

```text
classify_task.classify_domains()
        +
adaptive_swarm.choose_roles()
```

The output is clearly labeled:

```json
{"source": "projection"}
```

This is not represented as an actual worker execution.

### Observed legacy input

An actual legacy routing receipt can be supplied later:

```json
{
  "strategy": "legacy-observed-route",
  "domains": ["CODE", "GAMEPLAY"],
  "roles": ["implementer", "test_writer"],
  "review": true,
  "source_ref": "run-123"
}
```

Then the comparator labels it:

```json
{"source": "observed"}
```

This makes historical shadow data usable without conflating prediction and observation.

### Comparison output

G3 compares facts such as:

- domain exact match;
- legacy role count;
- G3 `READY` strategies;
- G3 `CONDITIONAL` strategies;
- G3 `BLOCKED` strategies;
- whether legacy policy projected parallel roles;
- whether G3 found a ready single-coordination shape.

It intentionally has no:

- `winner`;
- `best`;
- `recommended`;
- auto-promotion action.

MADO LAB should later decide whether a strategy migration is justified from real outcome evidence.

---

## 9. CLI

First create a current G2 snapshot:

```powershell
python .agents/skills/mado-loop/scripts/capability_snapshot.py --pretty > capability-snapshot.json
```

Generate advisory candidates:

```powershell
python .agents/skills/mado-loop/scripts/strategy_resolver.py `
  --intent intent.json `
  --authority authority.json `
  --snapshot capability-snapshot.json `
  --pretty
```

Run shadow comparison against the deterministic legacy projection:

```powershell
python .agents/skills/mado-loop/scripts/strategy_shadow_compare.py `
  --intent intent.json `
  --authority authority.json `
  --snapshot capability-snapshot.json `
  --pretty
```

Compare against an explicitly captured legacy observation:

```powershell
python .agents/skills/mado-loop/scripts/strategy_shadow_compare.py `
  --intent intent.json `
  --authority authority.json `
  --snapshot capability-snapshot.json `
  --legacy-plan legacy-plan.json `
  --pretty
```

All G3 commands are stdout-only.

They make no network calls, invoke no model, mutate no repository, and execute no strategy.

---

## 10. Hard invariants

1. current MADO LOOP 1.x routing remains authoritative;
2. G3 is advisory only;
3. candidate availability never grants authority;
4. candidate `READY` never means `QUALIFIED`;
5. provider/model identity is not a strategy type;
6. network-required capabilities are excluded when network authority is denied;
7. sensitivity-incompatible capabilities are excluded;
8. policy-gated capabilities require pre-existing policy tokens;
9. `modify` is conservative and prefers the isolated mutation boundary;
10. swarm availability does not make swarm automatically preferred;
11. Snapshot and registry digest must match exactly;
12. shadow projection is distinguished from observed legacy routing;
13. comparison declares no winner;
14. proof requirements are never lowered by candidate generation.

---

## 11. What G3 does not do

G3 does not:

- replace `classify_task.py`;
- replace `provider_router.py`;
- replace `adaptive_swarm.py`;
- choose a provider or model;
- execute a worker;
- mutate a worktree;
- integrate a diff;
- grant merge/publish authority;
- convert live feedback into qualification;
- promote a candidate;
- decide that a swarm is better;
- change P0-P5 completion semantics.

---

## 12. Exit condition

G3 is successful when:

> MADO can derive inspectable strategy candidates from Intent + Authority + Capability Snapshot, run them in shadow beside current routing, and explain structural agreement/disagreement without changing live execution.

After enough shadow observations exist, the next step should not be immediate replacement.

A sensible **G4** is a Shadow Evidence Recorder that stores bounded comparison receipts and joins them to real execution outcomes. Only after that dataset exists should MADO LAB evaluate whether any G3 strategy policy deserves qualification or canary use.
