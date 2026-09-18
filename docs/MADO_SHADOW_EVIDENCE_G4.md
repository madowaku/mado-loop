# MADO Shadow Evidence Recorder G4

Status: G4 observational evidence layer

G4 turns G3 shadow comparison into durable, bounded evidence without pretending that an unexecuted strategy has an outcome.

The core flow is:

```text
Intent + Authority + Snapshot
          |
          v
    G3 Shadow Compare
          |
          v
   SHADOW_CAPTURED
          |
          |     current live route executes elsewhere
          |                |
          |                v
          |          real result / eval result
          |                |
          +--------> OUTCOME_JOINED
                           |
                           v
                 materialized receipt
                           |
                           v
                        MADO LAB
```

G4 does not change live routing.

It records facts for later experiments.

---

## 1. The counterfactual rule

The most important G4 invariant is:

> An outcome belongs only to the route that actually executed.

Suppose the current legacy route executes and passes while G3 also produced:

```text
direct-agent-with-tools READY
adaptive-swarm          CONDITIONAL
```

G4 must **not** write:

```text
direct-agent-with-tools PASS
adaptive-swarm PASS
```

because neither G3 strategy was executed.

That would turn a shadow observation into fabricated experiment evidence.

Instead G4 stores:

```text
shadow context:
  G3 candidate set = ...

execution:
  route_kind = legacy
  strategy = actual legacy strategy
  source_ref = actual route receipt

outcome:
  status = PASS
  proof_level = ...
```

The candidate set stays contextual.

Only a future explicit G3 canary execution may attach an outcome to a G3 candidate ID.

---

## 2. Event ledger

G4 uses a small event ledger rather than rewriting completed receipts in place.

Default local path:

```text
.mado-loop/shadow_evidence.jsonl
```

The repository now ignores `.mado-loop/` by default because it contains local runtime observations.

There are exactly two G4 event types in v1.

### `SHADOW_CAPTURED`

Captures the bounded G3 shadow state before or around live execution.

### `OUTCOME_JOINED`

Later binds one observed execution and one real result to that exact shadow digest.

The ledger is semantically append-only.

The implementation writes atomically and preserves prior events. Repeating the same deterministic event with the same semantic payload is idempotent, even if the retry occurs at a later timestamp. The first observation time is preserved. Reusing an event ID with different semantic contents is rejected.

Each receipt has deterministic event IDs:

```text
capture:<receipt_id>
outcome:<receipt_id>
```

G4 v1 therefore permits one captured shadow state and at most one joined outcome per receipt.

If a task needs retries or multiple executions, each execution gets a distinct receipt ID.

---

## 3. Content-free capture

A G3 Shadow Compare contains enough structured information for G4 to discard task prose.

G4 stores these context identities:

```text
intent_id
intent_digest
authority_digest
snapshot_state_digest
registry_digest
```

It does **not** store:

- goal text;
- acceptance claim text;
- prompt text;
- repository source content;
- credentials;
- environment values.

The legacy side is reduced to:

```text
source = projection | observed
strategy
domains
roles
review
source_ref
```

The G3 side is reduced per candidate to:

```text
candidate id
strategy shape
READY / CONDITIONAL / BLOCKED
coordination shape
proof target
required feature ids
matched capability ids
bounded reason ids
```

This is enough to inspect routing structure without turning the evidence ledger into a second context warehouse.

---

## 4. Shadow digest

The normalized shadow payload receives a canonical SHA-256:

```text
shadow_digest = sha256(canonical bounded shadow state)
```

The later `OUTCOME_JOINED` event must bind to the same digest.

If a capture line is modified without updating its semantic digest, ledger validation fails.

The digest is an integrity identity, not a cryptographic signature of trust.

---

## 5. Real outcome support

G4 v1 understands two existing MADO contracts.

### Common Result v1.1

Produced by the normal MADO verification tools.

G4 keeps only:

- source digest;
- status;
- proof level;
- task domains;
- status counts;
- duration;
- counts of checks/artifacts/errors/warnings/unknowns.

It deliberately drops:

- summary text;
- check messages;
- check evidence contents;
- artifact paths;
- environment contents.

### MADO EVALS Eval Result v0.1

G4 keeps only:

- source digest;
- aggregate status;
- proof status;
- highest passed proof ID visible in the result;
- proof/acceptance/regression status counts;
- repair cycles;
- tokens when available;
- wall time when available;
- bounded counts.

It drops:

- outcome detail text;
- evidence paths;
- environment values.

The original result object is canonically hashed before reduction:

```text
source_digest = sha256(full original outcome)
```

That lets a later auditor check the bounded G4 summary against an original result without copying the original content into the shadow ledger.

---

## 6. Execution binding

An `OUTCOME_JOINED` event always names the execution that actually happened.

```json
{
  "route_kind": "legacy",
  "strategy": "legacy-live-route",
  "source_ref": "route:run-123",
  "candidate_id": null
}
```

or, for a future explicit G3 canary:

```json
{
  "route_kind": "g3_candidate",
  "strategy": "direct-agent-with-tools",
  "source_ref": "canary:run-124",
  "candidate_id": "strategy.direct-agent-with-tools"
}
```

For `route_kind=g3_candidate`, G4 requires:

1. candidate ID existed in the captured G3 candidate set;
2. strategy matches that captured candidate;
3. candidate was not `BLOCKED` at capture time.

This still does not create authority. It only rejects internally inconsistent evidence after an execution has been explicitly identified.

For `route_kind=legacy`, `candidate_id` must be null.

Therefore a legacy outcome can never silently become a G3 candidate outcome.

---

## 7. Projection vs observation

G3 already distinguishes:

```text
legacy.source = projection
legacy.source = observed
```

G4 preserves that distinction.

A projection is a deterministic reconstruction using current legacy policy code. It is useful for structural comparison but is not evidence that the projected route actually executed.

The joined execution has its own explicit `source_ref`, so the ledger can say:

```text
legacy projection at capture time
        +
actual execution receipt
        +
actual proof outcome
```

without collapsing them into one claim.

---

## 8. Materialized receipt

G4 can materialize immutable events into a convenient current view.

Before a result is joined:

```text
join_state = PENDING
execution = null
outcome = null
```

After the result is joined:

```text
join_state = JOINED
execution = {...}
outcome = {...}
```

The materialized view contains no winner and no strategy score.

It is an observation record.

---

## 9. CLI

Capture one G3 shadow comparison:

```powershell
python .agents/skills/mado-loop/scripts/shadow_evidence.py `
  --ledger .mado-loop/shadow_evidence.jsonl `
  capture `
  --receipt-id run:20260918:001 `
  --shadow shadow-compare.json
```

Join a real legacy execution outcome:

```powershell
python .agents/skills/mado-loop/scripts/shadow_evidence.py `
  --ledger .mado-loop/shadow_evidence.jsonl `
  join `
  --receipt-id run:20260918:001 `
  --outcome proof-result.json `
  --outcome-ref proof:20260918:001 `
  --route-kind legacy `
  --strategy legacy-live-route `
  --execution-ref route:20260918:001
```

Materialize one receipt:

```powershell
python .agents/skills/mado-loop/scripts/shadow_evidence.py `
  --ledger .mado-loop/shadow_evidence.jsonl `
  materialize `
  --receipt-id run:20260918:001 `
  --pretty
```

Materialize all captured receipts:

```powershell
python .agents/skills/mado-loop/scripts/shadow_evidence.py `
  --ledger .mado-loop/shadow_evidence.jsonl `
  materialize `
  --pretty
```

For deterministic fixtures, both `capture` and `join` accept an explicit ISO-8601 `--observed-at`.

---

## 10. Why G4 does not calculate a winner

A normal shadow record usually contains:

```text
legacy executed outcome
G3 candidates not executed
```

That dataset can answer questions such as:

- how often did G3 expose a ready single-agent route?
- how often did legacy policy expand to multiple roles?
- how often did G3 have no ready candidate?
- what capability or authority boundary commonly blocked G3?

It cannot yet answer:

> Would the G3 candidate have produced a better result?

That requires actual controlled execution of both candidate configurations or a canary experiment.

Therefore G4 intentionally records no:

- winner;
- preferred strategy;
- strategy success rate for unexecuted candidates;
- promotion decision;
- automatic router weight.

---

## 11. Relationship to MADO EVALS and MADO LAB

G4 does not replace the existing MADO EVALS result contract.

The two layers have different grains.

```text
G4 shadow evidence
  = what routing alternatives were visible around a real execution?

MADO EVALS / future MADO LAB
  = what happened when a particular candidate configuration was actually run?
```

G4 can ingest an existing Eval Result as the real outcome of an executed route.

Later MADO LAB can combine:

- G4 structural shadow history;
- controlled ExperimentRecords;
- Eval Results;
- proof evidence;
- capability qualification state.

That is the point where evidence-based strategy policy evolution becomes justified.

---

## 12. Hard invariants

1. the ledger is observational;
2. current live routing is unchanged;
3. one outcome is attributed only to the route that actually executed;
4. legacy outcomes never become G3 candidate outcomes;
5. a G3 candidate join must name a captured non-blocked candidate;
6. shadow task prose is not persisted;
7. outcome prose, evidence paths, and environment values are not persisted;
8. full original outcomes are represented by canonical digest plus bounded metrics/status only;
9. capture and join are separate immutable event types;
10. duplicate identical events are idempotent;
11. conflicting duplicate event IDs are rejected;
12. joined outcome must bind to the exact captured shadow digest;
13. projection and observation provenance remain distinct;
14. no winner or promotion is computed.

---

## 13. What G4 does not do

G4 does not:

- execute G3 candidates;
- rerun legacy routes;
- schedule canaries;
- evaluate counterfactual quality;
- rank strategy shapes;
- update provider routing;
- update skill routing;
- create GrowthDecisions;
- grant qualifications;
- change AuthorityContracts;
- upload local ledger contents;
- commit local runtime ledgers by default.

---

## 14. Exit condition

G4 is successful when:

> Every shadow comparison can be captured as bounded structural evidence, later joined to the real route that actually executed, and materialized without leaking task/result content or fabricating outcomes for unexecuted candidates.

A sensible next step is **G5: MADO LAB Shadow Analysis**.

G5 should consume many G4 receipts and produce descriptive cohort evidence first:

- agreement rates;
- blocked-reason distributions;
- coordination-shape distributions;
- outcome distributions conditioned on the route that actually executed;
- candidate coverage gaps.

Only controlled executions should support candidate-vs-candidate effectiveness claims.

The first G5 output should therefore be an analysis report, not an automatic router mutation.
