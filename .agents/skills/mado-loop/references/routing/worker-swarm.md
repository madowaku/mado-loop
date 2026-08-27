# Parallel worker swarm

Read this reference when a bounded task benefits from several independent model proposals and the desired role set is already known. This is the **fixed swarm** contract. When task domains should compose roles automatically, use [adaptive worker swarm](adaptive-swarm.md) instead. Both swarm modes remain execution patterns below MADO LOOP orchestration and never receive mutation or proof authority.

## Shape

The default fixed swarm is a two-stage fan-out/fan-in graph:

```text
                         +--> ARCHITECT ------+
TASK + BOUNDED CONTEXT --+--> IMPLEMENTER ----+--> REVIEWER --> ORCHESTRATOR
                         +--> TEST WRITER -----+                    |
                                                                  v
                                                        INTEGRATE / RUN / PROVE
```

`architect`, `implementer`, and `test_writer` run concurrently. Their outputs are collected in canonical role order regardless of completion order. The optional `reviewer` runs only after at least one primary worker succeeds and receives the primary outputs for contradiction and proof-gap review.

The reviewer is not an integrator. It cannot choose the final patch, mutate the repository, or declare completion. The MADO LOOP orchestrator performs the fan-in decision, applies only accepted changes, and validates resulting project state through the normal P0-P5 ladder.

## Role contracts

| Role | Responsibility | Explicit non-authority |
| --- | --- | --- |
| `architect` | boundaries, dependencies, invariants, risks, minimal implementation shape | does not mutate or claim execution |
| `implementer` | concrete bounded code/project proposal, touched files, assumptions | does not apply patches or claim runtime success |
| `test_writer` | tests, edge cases, failure conditions, relevant P0-P5 gates | does not claim tests ran |
| `reviewer` | disagreements, unsafe assumptions, scope creep, missing proof, integration recommendation | does not pick/apply the final patch or establish proof |

Keep primary workers independent enough that one worker's framing does not collapse the value of the others. Shared task/context is acceptable; do not feed one primary worker another primary worker's answer. Cross-worker synthesis belongs in the review stage or orchestrator.

## Bounded inputs

The swarm runtime requires a task and accepts optional bounded context. The first-party implementation enforces finite input and concurrency limits so a routing mistake cannot explode into an unbounded model fan-out.

Current first-party bounds:

- task: at most 20,000 characters;
- shared context: at most 120,000 characters;
- primary roles: the declared built-in fixed role set, unique;
- parallel worker threads: 1 through 8, default 3;
- reviewer: one sequential fan-in call after primary workers;
- provider/model selection: one provider policy for the whole fixed-swarm invocation.

These are orchestration safety bounds, not model context-window claims. A configured provider/model may impose tighter limits and can fail independently.

## Provider and sensitivity

Run [worker provider router](provider-router.md) before the fixed swarm. The fixed swarm selects one permitted provider/model configuration and reuses that data-policy boundary across all workers in the invocation.

- `secret` still requires local-only execution.
- `private` never falls to a logged public lane.
- Empero/free remains public-only and explicit opt-in.
- OpenRouter requests retain the provider privacy constraints imposed by `provider_router.py`.

Do not split one fixed-swarm private task across mixed providers. Per-assignment routing is defined only by the [adaptive worker swarm](adaptive-swarm.md), where every role independently passes through the same sensitivity policy.

## Failure semantics

Primary workers are failure-isolated. One provider call failing does not cancel siblings that may still provide useful proposals.

- all scheduled workers succeed: swarm transport status `PASS`;
- at least one succeeds and at least one fails: `WARN`;
- no worker succeeds: `FAIL`;
- reviewer failure produces `WARN` when primary proposals remain available.

These statuses describe swarm execution only. Every swarm result sets `proof_status: UNPROVEN` and `integration_required: true`. Never map swarm `PASS` directly to a MADO LOOP completion status.

When every primary worker fails, skip the reviewer because there is no proposal set to review. Provider failure remains an optional capability failure unless the user explicitly made worker delegation required.

## Deterministic fan-in

Network completion order must not leak into orchestration semantics. Store primary results in canonical requested-role order and include role names on every result. Each result records only credential-redacted provider metadata, response content, usage metadata when available, error summary, and duration.

Do not persist provider API keys in swarm artifacts. Treat model responses as potentially sensitive according to the original payload classification.

## CLI

Inspect the fixed swarm without network calls:

```powershell
python .agents/skills/mado-loop/scripts/worker_swarm.py plan --sensitivity private
```

Run the default three-way primary fan-out plus reviewer:

```powershell
python .agents/skills/mado-loop/scripts/worker_swarm.py run `
  --sensitivity private `
  --task-file .mado/swarm-task.txt `
  --context-file .mado/swarm-context.txt `
  --output .mado/swarm-result.json
```

Use only selected primary roles when the task does not benefit from the full set:

```powershell
python .agents/skills/mado-loop/scripts/worker_swarm.py run `
  --roles architect,test_writer `
  --task-file .mado/swarm-task.txt
```

Use `--no-review` only when independent proposals are sufficient and the orchestrator will perform the comparison directly.

## Orchestrator integration checklist

Before using any swarm proposal:

1. inspect each worker result and reviewer findings;
2. identify agreement, conflict, unsupported assumptions, and scope expansion;
3. choose the smallest coherent change based on project facts, not worker majority vote;
4. apply changes through the normal project-safe tool path;
5. run the required proof gates and inspect actual output;
6. record worker delegation in AI Creole only as a capability route/proposal source, never as proof.

A fixed swarm is useful when independent perspectives reduce blind spots and the role set is already clear. It is wasteful when the task is trivial, deterministic tooling already answers the question, or domain-driven adaptive composition would avoid redundant roles.
