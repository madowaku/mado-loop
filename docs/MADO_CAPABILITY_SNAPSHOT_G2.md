# MADO Capability Snapshot G2

Status: G2 observational layer

Capability Snapshot is a read-only answer to one question:

> What capabilities does this MADO runtime declare, what narrow prerequisites are observable now, and which scoped qualifications still bind to the current capability definitions?

It does not answer which strategy should run next.

```text
CapabilityManifest v2
        |
        +---- local probe -----------+
        |                            |
GrowthDecision projection -----------+--> Capability Snapshot
(source-bound qualification)         |          |
                                     |          X no authority grant
                                     |          X no strategy selection
                                     |          X no proof downgrade
                                     |          X no self-promotion
                                     v
                              current body state
```

## The G2 split: availability is not qualification

G2 deliberately stops treating capability lifecycle as one scalar state.

Two independent axes are preserved:

```text
Availability                         Qualification
------------                         -------------
DECLARED                             QUALIFY(scope)
PROBED                               CANARY(scope)
UNAVAILABLE                          ADOPT(scope)
UNKNOWN                              HOLD(scope)
RETIRED                              DEGRADE(scope)
                                     RETIRE(scope)
```

`PROBED` means a narrow prerequisite is observable now. A qualification means an explicit growth boundary accepted evidence for a particular scope.

Neither implies the other.

Examples:

- a local model endpoint can be `PROBED` with no qualification history;
- a capability can have an old `QUALIFY(ui.smoke-observation)` record while currently being unavailable;
- a valid qualification never turns `DECLARED` availability into `QUALIFIED`;
- a stale qualification remains visible as history but is not current evidence.

This keeps the G1 invariant intact:

```text
PROBED != QUALIFIED
```

## Source-bound qualification

Every qualification record carries the digest of the exact normalized CapabilityManifest it evaluated:

```json
{
  "schema_version": "1.0",
  "id": "growth.091",
  "capability_id": "engine.godot",
  "scope": "ui.smoke-observation",
  "decision": "QUALIFY",
  "bound_manifest_digest": "sha256:...",
  "basis": {
    "experiments": ["exp-881", "exp-886"],
    "evidence": ["ev-203"]
  },
  "approved_by": "explicit-promotion-boundary"
}
```

At snapshot time the record is compared with the capability's current manifest digest.

```text
same digest      -> ACTIVE
changed manifest -> STALE
```

A changed provider/model provenance, feature declaration, sensitivity support, requirement, evidence interface, or other manifest meaning therefore invalidates the old binding instead of silently inheriting it.

G2 does not decide whether a stale qualification should be re-run. That belongs to MADO LAB / a later growth policy.

## Qualification source files

Qualification records are grouped in explicit sources:

```json
{
  "schema_version": "1.0",
  "source_id": "mado-lab.accepted",
  "records": []
}
```

The snapshot stores a canonical SHA-256 digest for every source. Local source paths are never emitted.

Record IDs must be unique across all supplied sources. Unknown capability IDs are rejected rather than retained as dangling claims.

## Snapshot shape

A snapshot contains:

```text
registry identity + digest
observation timestamp
semantic state digest
source digests
capability entries
  manifest digest
  sanitized availability observation
  scoped qualification records
```

Each capability looks conceptually like:

```json
{
  "id": "engine.godot",
  "kind": "engine",
  "manifest_digest": "sha256:...",
  "availability": {
    "capability_id": "engine.godot",
    "declared_state": "DECLARED",
    "effective_state": "PROBED",
    "probe_type": "env_path_or_executable",
    "observed": {}
  },
  "qualifications": []
}
```

The availability object is produced by the G1 probe implementation. G2 therefore inherits its privacy boundary: environment variable values and credential values are never emitted.

## `state_digest`

`observed_at` identifies when the snapshot was taken, but timestamps are deliberately excluded from `state_digest`.

If two observations have identical:

- normalized registry;
- manifest definitions;
- sanitized probe observations;
- qualification source contents and bindings;

then they have the same `state_digest` even when observed at different times.

This gives future MADO components a cheap way to ask:

> Did the capability body actually change, or did we merely observe it again?

The digest is not a security signature and does not grant trust.

## CLI

Create a current snapshot using only local, bounded G1 probes:

```powershell
python .agents/skills/mado-loop/scripts/capability_snapshot.py --pretty
```

Create a declaration-only snapshot:

```powershell
python .agents/skills/mado-loop/scripts/capability_snapshot.py --no-probe --pretty
```

Compose one or more explicit qualification sources:

```powershell
python .agents/skills/mado-loop/scripts/capability_snapshot.py `
  --qualification evidence/accepted-growth-decisions.json `
  --pretty
```

For deterministic fixtures, an observation time may be supplied explicitly:

```powershell
python .agents/skills/mado-loop/scripts/capability_snapshot.py `
  --observed-at 2026-09-17T00:00:00Z `
  --pretty
```

The command writes JSON to stdout only. G2 creates no repository files, makes no network calls, invokes no model, and changes no capability state.

## G2 invariants

1. snapshot creation is observational and read-only;
2. availability and qualification remain separate axes;
3. qualification cannot promote probe state;
4. each qualification is scope-bound;
5. each qualification is bound to an exact manifest digest;
6. changed manifests make old qualification records `STALE`;
7. stale records stay visible rather than disappearing silently;
8. source paths and environment values are not emitted;
9. unknown capability references are rejected;
10. `state_digest` excludes observation time;
11. Snapshot is not an AuthorityContract;
12. Snapshot is not a StrategyPlan;
13. Snapshot is not Proof.

## What G2 does not do

G2 does not:

- discover arbitrary capabilities;
- call a provider or model;
- benchmark capability quality;
- invent or approve qualification records;
- make qualification records from live success counts;
- grant permissions;
- choose models, tools, skills, or worker topologies;
- replace `provider_router.py`;
- replace P0-P5 proof;
- automatically re-run stale qualifications;
- automatically retire old adapters.

## Exit condition

G2 is successful when this statement is true:

> MADO can produce a reproducible, privacy-bounded view of its currently declared and locally observed capabilities, while attaching only explicit source-bound scoped qualification history and without turning that view into execution authority.

The next architectural step should consume this snapshot **advisorially** before any live routing change. A sensible G3 is a Strategy Candidate interface that can explain which capability combinations could satisfy an IntentContract under an AuthorityContract, while still leaving existing MADO LOOP 1.x routing authoritative until evidence justifies migration.
