# MADO CapabilityManifest v2

Status: G1 compatibility layer

CapabilityManifest v2 is the first executable foothold of the MADO Growth Architecture. It describes what a participant can do, what it requires, what sensitivity classes it can support, how its presence can be probed, and what evidence interfaces it can produce.

It is deliberately **not** a new router and **not** an authority system.

```text
Intent / task
    |
    v
CapabilityManifest[] ---- probe ----> availability snapshot
    |
    +---- resolve/filter -----------> advisory candidate set
                                      |
                                      X  no permission grant
                                      X  no proof downgrade
                                      X  no automatic qualification
```

## G1 question

G1 answers one bounded architecture question:

> Can current MADO capabilities be represented, probed, and resolved without changing existing proof or authority behavior?

The implementation is intentionally additive. Existing routing, provider selection, OVP, P0-P5 proof, and completion semantics remain authoritative for MADO LOOP 1.x.

## Files

```text
.agents/skills/mado-loop/capabilities/
  capability-manifest-v2.schema.json
  registry-v2.json

.agents/skills/mado-loop/scripts/
  capability_manifest.py

tests/unit/
  test_capability_manifest.py
```

`registry-v2.json` currently contains 21 capability records. Eighteen records carry `legacy` metadata corresponding to every row in the existing human-readable capability registry. Three additional records make already-existing first-party runtime capabilities explicit: OVP mutation, Visual Broker observation, and release audit.

## Manifest contract

A v2 capability contains these stable categories:

```json
{
  "schema_version": "2.0",
  "id": "engine.godot",
  "kind": "engine",
  "domains": ["CODE", "GAMEPLAY", "UI"],
  "features": ["engine.runtime.execute", "evidence.behavior"],
  "provenance": {
    "source": "vendored+first-party",
    "implementation": "godot-adapter"
  },
  "requirements": {
    "network": "none",
    "credentials": "none",
    "executables": ["godot"],
    "files": [],
    "env": []
  },
  "sensitivity_support": ["public", "private", "secret"],
  "evidence_interfaces": ["runtime.result", "screenshot"],
  "availability": {
    "state": "DECLARED",
    "probe": {
      "type": "env_path_or_executable",
      "env": ["MADO_GODOT_BIN"],
      "candidates": ["godot", "godot4"]
    }
  }
}
```

### Identity and provenance

`id` is the semantic capability identity used by MADO contracts.

Provider, implementation, model/runtime version, and similar details belong under `provenance`. They describe **where the capability comes from**, not why a strategy should choose it.

This preserves the Growth Architecture rule:

```text
semantic selection -> capability/features/policy
provenance          -> provider/model/runtime/version
```

A future model replacement should normally change provenance or runtime qualification, not force a new orchestration architecture.

## Features

`features` are small semantic tokens such as:

```text
agent.delegate.proposal
engine.runtime.execute
image.generate
screenshot.capture
workspace.isolated.mutation
strategy.multi_agent.fixed
artifact.release.audit
```

G1 does not define a global ontology service. Feature names are versioned with this repository and should be added conservatively.

A feature states that a capability can participate in an operation. It does **not** state that the current user/task has authorized that operation.

## Sensitivity and policy requirements

`sensitivity_support` describes the data classes a capability is designed to handle.

Some support is conditional. `policy_requirements` names explicit policy facts that must already be present before the advisory resolver will include the capability.

Example:

```json
{
  "sensitivity_support": ["public", "private"],
  "policy_requirements": {
    "private": ["explicit.nvidia_private"]
  }
}
```

The token does not create consent or authority. It represents a policy decision made elsewhere.

The same pattern is used for the logged-free public lane:

```text
explicit.logged_free
```

## Availability lifecycle

The shared lifecycle vocabulary is:

```text
UNKNOWN
DECLARED
PROBED
QUALIFIED
DEGRADED
UNAVAILABLE
RETIRED
```

G1 implements only conservative local availability observation.

### Critical invariant

```text
PROBED != QUALIFIED
```

A successful probe proves only that a narrow prerequisite is observable now.

Examples:

- a file exists;
- an executable is on PATH;
- required configuration variable names are populated;
- a configured executable path exists.

A probe does not prove task quality, correctness, reliability, or safety. Only a later MADO LAB / GrowthDecision boundary may create scoped `QUALIFIED` state.

## Probe types

G1 probes are intentionally cheap and non-destructive:

- `always`: first-party or host-declared presence can be observed without execution;
- `file_all`: required skill-local files exist;
- `executable_any`: at least one named executable is discoverable;
- `executables_all`: every named executable is discoverable;
- `env_requirements`: required variable names and alternative variable groups are populated;
- `env_path_or_executable`: a configured executable path exists or a bounded executable candidate is discoverable.

No G1 probe:

- performs a network request;
- calls a model;
- mutates the repository;
- installs dependencies;
- reads or emits credential values;
- promotes itself to `QUALIFIED`.

Provider probes expose environment variable **names only**. Values are never included in output.

## Advisory resolver

The resolver filters manifests using:

```text
required features
+ task domain
+ sensitivity
+ already-granted policy tokens
+ optional availability probe
```

It does not choose a final StrategyPlan and does not replace `provider_router.py` in G1.

This is intentional. We first want evidence that capability-language resolution can faithfully represent the current system before making it authoritative.

### Example: validate

```powershell
python .agents/skills/mado-loop/scripts/capability_manifest.py validate --pretty
```

If using the global options supported by the current CLI ordering:

```powershell
python .agents/skills/mado-loop/scripts/capability_manifest.py --pretty validate
```

### Example: inspect probes

```powershell
python .agents/skills/mado-loop/scripts/capability_manifest.py --pretty probe --id engine.godot
```

### Example: find proposal-worker capabilities

```powershell
python .agents/skills/mado-loop/scripts/capability_manifest.py --pretty resolve `
  --feature agent.delegate.proposal `
  --sensitivity private
```

### Example: require observed availability

```powershell
python .agents/skills/mado-loop/scripts/capability_manifest.py --pretty resolve `
  --feature agent.delegate.proposal `
  --sensitivity secret `
  --probe `
  --require-probed
```

With current manifests, a secret proposal-worker query can only resolve the configured local OpenAI-compatible lane. Hosted worker manifests do not advertise secret support.

### Example: explicit policy fact

```powershell
python .agents/skills/mado-loop/scripts/capability_manifest.py --pretty resolve `
  --feature code.proposal `
  --sensitivity private `
  --policy explicit.nvidia_private `
  --probe
```

Again, the policy token does not grant permission. It tells the resolver that a separate policy boundary already supplied that fact.

## Relationship to the existing registry

The existing Markdown capability registry remains the human-facing MADO LOOP 1.x selection contract during G1.

`registry-v2.json` is a compatibility projection plus a few explicit runtime capabilities. The `legacy` block stores the old capability name, mode, and absence behavior so migrations can be checked rather than hand-waved.

The G1 unit suite requires all 18 legacy rows to remain represented.

## Relationship to provider_router.py

`provider_router.py` still owns current provider execution and privacy enforcement.

CapabilityManifest v2 intentionally does not duplicate provider request construction, API calls, credentials, or transport behavior. It describes semantic capability and availability only.

In a later phase, a Strategy resolver may consume qualified manifests and then delegate transport selection to an adapter such as the provider router.

## Relationship to P0-P5

Nothing in G1 changes proof authority.

A capability can advertise evidence interfaces such as `runtime.result`, `screenshot`, `worker.receipt`, or `artifact`, but advertising an interface is not proof that evidence exists for a particular run.

Completion remains evidence-driven:

```text
capability selected  != proof
probe passed         != proof
provider call passed != proof
required evidence    -> proof/completion contract
```

## G1 invariants

The implementation and tests protect these boundaries:

1. all current legacy capability-registry rows remain representable;
2. duplicate capability identities are rejected;
3. capability-relative probe paths cannot traverse upward;
4. provider configuration values are not emitted by probes;
5. probe success stops at `PROBED`;
6. `--require-probed` rejects merely declared host capabilities;
7. secret proposal-worker resolution cannot select hosted worker manifests;
8. conditional lanes require explicit policy tokens;
9. provider/model provenance is not used as the semantic feature selector;
10. no existing router, proof gate, or authority path imports this module in G1.

## What G1 deliberately does not do

G1 does not:

- auto-discover arbitrary tools;
- ask a model what it can do and trust the answer;
- benchmark or qualify a capability;
- generate AuthorityContracts;
- create StrategyPlans;
- replace `mado_doctor.py`;
- replace `provider_router.py`;
- change live MADO routing;
- mutate capability state based on historical success;
- auto-promote, canary, adopt, or retire anything.

## Exit condition

G1 is successful when the following statement is true:

> Current MADO capabilities can be represented in one semantic format, narrowly probed without side effects, and filtered by feature/domain/sensitivity/policy without changing MADO LOOP's existing execution or proof authority.

If that remains true under CI, the next useful step is **G2: Capability Snapshot**, which can compose declared manifests with runtime probe observations and source-bound qualification records without yet changing strategy selection.
