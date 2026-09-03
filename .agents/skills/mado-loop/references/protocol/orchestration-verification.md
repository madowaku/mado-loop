# Orchestration & Verification Protocol (OVP)

OVP defines how MADO LOOP may delegate project mutation without giving a worker final authority. It extends the existing read-only worker plane with an isolated mutation lane while preserving one rule: **the actor that makes a change does not decide that the requested outcome is complete**.

OVP is optional. Use it only when isolated parallel implementation creates concrete leverage. Small or deterministic work stays in the ordinary single-orchestrator path.

## Core authority rule

Separate four responsibilities:

1. **Leader / Orchestrator** owns task decomposition, dispatch, integration, acceptance, and final status.
2. **Proposal workers** remain read-only and return untrusted analysis, patch suggestions, tests, or reviews.
3. **Mutation workers** may modify only their assigned isolated workspace and must stop at `REVIEW_READY`.
4. **Proof system** evaluates the integrated project state through P0-P5. A worker report, passing local test, or majority vote is not final proof.

A mutation worker must never mark a task `DONE`, merge its own branch, weaken acceptance criteria, or expand scope merely to make checks pass.

## Execution state machine

Use these canonical states for delegated mutation work:

```text
PLANNED
  -> PREFLIGHT
  -> READY
  -> DISPATCHED
  -> WORKING
  -> REVIEW_READY
  -> ACCEPTED | REWORK | REJECTED
  -> INTEGRATED
  -> PROVEN | FAILED | UNKNOWN
```

Only the orchestrator may move `REVIEW_READY` to `ACCEPTED`, `REWORK`, or `REJECTED`. Only the normal proof path may establish `PROVEN`.

## Preflight before fan-out

Before creating mutation workers, run a disposable worker-equivalent preflight. Validate the environment under the same practical constraints the workers will receive.

At minimum check:

- repository and target ref are readable;
- an isolated workspace can be created and removed safely;
- expected files are writable inside that workspace;
- local commits can be created when the route requires commits;
- required task-board / receipt files are readable and writable when used;
- required deterministic tools, Godot executable, and proof dependencies for the assigned route are available;
- credentials or secret-bearing context will not be copied into a worker lane that is not permitted to receive them.

If preflight fails, do not fan the same failure out across multiple workers. Record the failed capability once and either repair it in the orchestrator lane or return `UNKNOWN` / `FAIL` according to the completion contract.

## Workspace isolation

Mutation workers operate in an isolated Git worktree or an equivalently isolated repository copy. Prefer Git worktrees because they retain repository identity without sharing a writable checkout.

Each mutation assignment receives:

- a stable task id;
- an explicit base ref;
- its own branch or detached isolated workspace according to the integration policy;
- include / exclude scope;
- acceptance checks;
- allowed tools;
- forbidden mutations;
- expected evidence;
- the required terminal state `REVIEW_READY`.

Workers must not edit another worker's workspace, the orchestrator's active checkout, CI configuration outside assigned scope, credentials, global tool configuration, or unrelated project files.

## AI Creole Agent Contract

Use the stable AI Creole core as the compact worker contract. Project-specific fields may extend it, but do not redefine the core meaning.

```text
TASK <stable id and short task>
GOAL <observable requested outcome>
STATE <current delegated state>
TARGET <files/scenes/resources or bounded subsystem>
DO <allowed implementation actions>
KEEP <invariants and compatibility constraints>
NO <explicitly forbidden scope or mutations>
OUT <required patch/commit/evidence/report>
CHECK <worker-side checks to run before review>
RISK <known hazards or unresolved assumptions>
NEXT REVIEW_READY
```

The contract is a dispatch envelope, not proof. `CHECK` tells the worker what evidence to collect; it does not transfer acceptance authority.

## First-party runtime

`scripts/ovp_runtime.py` is the first-party implementation of the mutation boundary. It stores task state under the repository's Git common directory, outside the tracked working tree, and creates worker worktrees under a bounded workspace root. The default workspace root is the sibling `.mado-loop-worktrees/<repo-name>/` directory. The runtime uses atomic manifests and a per-task lock so concurrent state transitions do not silently overwrite each other.

The current runtime deliberately requires mutation work to be committed before `REVIEW_READY`. This keeps review, integration, rollback, and branch identity deterministic. Proposal-only workers remain available when a committed isolated mutation lane is unnecessary.

Preflight only:

```powershell
python .agents/skills/mado-loop/scripts/ovp_runtime.py preflight `
  --repo . `
  --base-ref HEAD `
  --require-tool python `
  --pretty
```

Prepare one bounded mutation task. Required acceptance checks use stable IDs so the receipt must report the same contract:

```powershell
python .agents/skills/mado-loop/scripts/ovp_runtime.py prepare `
  --repo . `
  --task-id KAN-024 `
  --goal "Player dash works without changing enemy behavior" `
  --include "player/" `
  --exclude "enemy/" `
  --acceptance "unit=dash unit tests pass" `
  --optional-acceptance "visual=dash capture is legible" `
  --domain GAMEPLAY `
  --domain CODE `
  --pretty
```

The command creates a `mado/ovp/<task-id>` branch, an isolated worktree, a manifest, and `AI_CREOLE.txt`. Provider execution remains a separate capability boundary from the state runtime, but MADO LOOP now provides the first-party [OVP Dispatch Adapter](ovp-dispatch.md) in `scripts/ovp_dispatch.py` for Codex, Claude, or an explicitly configured local agent. The adapter keeps OVP state/receipt authority in the orchestrator-side process rather than the mutation worker. Manual dispatch may still record progress with `mark --state DISPATCHED` and `mark --state WORKING`.

A mutation worker must commit its bounded change, leave the worktree clean, then submit the exact acceptance IDs. When `ovp_dispatch.py` is used, the worker returns `mado-mutation-handoff/v1` and the adapter performs this authoritative receipt submission. For a manual mutation lane, submit the receipt directly:

```powershell
python .agents/skills/mado-loop/scripts/ovp_runtime.py receipt `
  --repo <worker-worktree> `
  --task-id KAN-024 `
  --summary "Implemented dash and regression test" `
  --check "unit=PASS" `
  --optional-check "visual=PASS" `
  --evidence "unit=python -m unittest tests.test_dash" `
  --evidence "visual=artifacts/dash.png" `
  --pretty
```

The runtime verifies branch identity, a clean committed worker state, include/exclude scope, and receipt/check identity before moving the task to `REVIEW_READY`.

Acceptance requires an explicit orchestrator assertion that the diff was inspected. Structural gates are re-evaluated at review time so a worker cannot change HEAD after submitting its receipt and still be accepted:

```powershell
python .agents/skills/mado-loop/scripts/ovp_runtime.py review `
  --repo . `
  --task-id KAN-024 `
  --decision accept `
  --reason "Diff and evidence satisfy bounded task" `
  --inspected-diff `
  --pretty
```

Use `--decision rework` or `--decision reject` when the result should not be accepted. An accepted task may then be integrated with `merge` or `cherry-pick`. Failed integration is aborted and leaves the task `ACCEPTED` for a bounded recovery decision.

```powershell
python .agents/skills/mado-loop/scripts/ovp_runtime.py integrate --repo . --task-id KAN-024 --strategy merge --pretty
```

Integration is still not completion. Run the normal MADO LOOP P0-P5 path, persist its schema-v1.1 result JSON, then bind that result to the exact integrated HEAD:

```powershell
python .agents/skills/mado-loop/scripts/ovp_runtime.py proof `
  --repo . `
  --task-id KAN-024 `
  --result artifacts/result.json `
  --pretty
```

`PASS` or `WARN` proof maps to `PROVEN`, `FAIL` maps to `FAILED`, and unresolved or skipped required proof maps to `UNKNOWN`. If leader HEAD changed after integration, proof binding is rejected rather than attached to the wrong project state.

After a final state or rejection, `cleanup` removes only the recorded owned worktree and refuses a dirty workspace. Worker branches are preserved by default. `--delete-branch` attempts only Git's safe `branch -d`; it never force-deletes an unmerged branch.

## Evidence bundle

A mutation worker returns a bounded evidence bundle when entering `REVIEW_READY`:

- task id and workspace / branch identity;
- changed file list;
- commit id or patch identity when applicable;
- concise implementation summary;
- commands/checks actually executed and their statuses;
- artifacts such as screenshots, captures, proof sheets, or logs when relevant;
- known risks, skipped checks, and unresolved assumptions;
- explicit statement that final acceptance and integration remain with the orchestrator.

Do not paste giant transient logs into the receipt. Store durable artifacts and summarize the relevant evidence.

## Visual broker boundary

For UI, animation, sprite, gameplay, or other visually observable work, a mutation worker may be granted a narrow visual broker instead of general desktop control.

Preferred broker actions are typed and minimal, for example:

```text
launch(target)
capture(target, artifact_path)
stop(target)
```

Additional actions require an explicit project contract. The broker should expose only the application or test surface needed for the task, not unrestricted operating-system automation. Visual output remains worker evidence until inspected and, where required, reproduced after integration.

## Review and integration

When a worker reports `REVIEW_READY`, the orchestrator:

1. verifies the assignment scope and workspace identity;
2. inspects the diff and evidence bundle;
3. checks for unrelated mutations, weakened tests, generated junk, or hidden dependency changes;
4. requests `REWORK` or marks `REJECTED` when acceptance criteria are not satisfied;
5. integrates only the smallest accepted coherent change;
6. resolves cross-worker conflicts using project facts, never majority vote;
7. runs the ordinary MADO LOOP proof ladder against the integrated project state.

Worker-local success may justify review, never completion.

## Parallelism rules

Parallel mutation is appropriate when assignments have low write overlap and independently checkable outcomes. Prefer read-only proposal workers when tasks share the same files or when decomposition itself is uncertain.

Before fan-out, identify likely collision surfaces. If two mutation assignments need the same central scene, configuration file, import metadata, or stateful asset, either serialize them or assign one integration owner and keep the other worker read-only.

Do not recursively let a worker create mutation workers. Team composition and dispatch remain deterministic orchestrator responsibilities.

## Failure semantics

- One worker failure does not automatically cancel unrelated siblings.
- A contaminated, out-of-scope, or unverifiable worker result is `REJECTED`, not silently salvaged.
- Missing required integrated proof yields `UNKNOWN` unless an executed check already establishes `FAIL`.
- A failed disposable preflight blocks mutation fan-out but does not prevent safe read-only analysis.
- Cleanup failure for a worktree or temporary branch is reported as a warning/risk and must not be hidden.

## Relationship to existing worker swarms

`worker_swarm.py`, `adaptive_swarm.py`, Codex-native workers, and Budget Governor lanes remain proposal systems unless an implementation explicitly opts into OVP and provides the isolation, preflight, mutation receipt, and review boundary described here.

Do not reinterpret existing `proof_status: UNPROVEN` workers as mutation workers. OVP adds a new capability boundary; it does not weaken the existing one.

## Relationship to P0-P5

OVP governs **who may change what and who may accept it**. P0-P5 governs **what has actually been demonstrated**.

The final sequence is:

```text
UNDERSTAND
  -> ROUTE
  -> PREFLIGHT
  -> ISOLATE
  -> DISPATCH / MUTATE
  -> REVIEW
  -> INTEGRATE
  -> RUN / INSPECT / VERIFY / FIX
  -> PROVE
```

For non-delegated work, omit the OVP-specific steps and keep the standard MADO LOOP operating loop.
