# MADO EVALS

MADO EVALS is the replayable evaluation layer for MADO LOOP. It uses deterministic case contracts and MADO LOOP evidence rather than a model-as-judge as the authority.

The design contract is in [`docs/MADO_EVALS_SPEC.md`](../../../../docs/MADO_EVALS_SPEC.md).

## v0.1 foundation

The deterministic foundation provides:

- `schema/eval-case.schema.json` - case contract;
- `schema/eval-result.schema.json` - run-result contract;
- `schema/eval-runner.schema.json` - typed allowlisted runner contract;
- `scripts/validate_eval_case.py` - strict validation, input manifesting, and SHA-256 case digests;
- `scripts/eval_result.py` - canonical proof/acceptance result construction;
- `scripts/compare_eval_results.py` - gate-first champion/challenger comparison;
- `scripts/run_eval_case.py` - isolated fixture replay through allowlisted adapters.

A replayable case has this shape:

```text
cases/<domain>/<case-id>/
  case.json
  runner.json     # must be listed in expected_paths, so it is digest-bound
  task.md
  fixture/        # optional immutable replay input
  expected/       # optional golden/non-secret deterministic assets
```

Validate a case before execution:

```powershell
python .agents/skills/mado-loop/scripts/validate_eval_case.py `
  .agents/skills/mado-loop/evals/cases/<domain>/<case-id>/case.json `
  --pretty
```

The validator emits a canonical case payload, a manifest of the task/fixture/expected files, and a `sha256:` case digest. The digest changes when any bound input changes.

## Typed Phase 1 runner

`run_eval_case.py` does not execute arbitrary commands from the corpus. `runner.json` chooses one allowlisted adapter:

- `skill_router` - deterministic MADO LOOP skill routing, no network/model call;
- `godot_layout` - P2 layout evidence through the existing Godot layout proof adapter;
- `godot_behavior` - P3 state-transition evidence through the existing behavior proof adapter;
- `external_receipt` - imports an explicit receipt from a black-box observer such as game-test-player without granting that observer proof authority.

The runner copies fixture inputs into `.mado-loop/evals/runs/<run-id>/workspace` before observation. Generated logs/reports live under that run directory and are not committed by default.

Example offline routing replay:

```powershell
python .agents/skills/mado-loop/scripts/run_eval_case.py `
  .agents/skills/mado-loop/evals/cases/routing/routing.skill-selection/case.json `
  --candidate-id current `
  --pretty
```

Example Godot replay when `MADO_GODOT_BIN` is configured:

```powershell
python .agents/skills/mado-loop/scripts/run_eval_case.py `
  .agents/skills/mado-loop/evals/cases/ui/ui.visible-control/case.json `
  --candidate-id current `
  --pretty
```

Adapter execution failures are recorded as `UNKNOWN` with `runner-error.json` evidence. They do not become product `FAIL` merely because the observation infrastructure failed.

## Initial corpus

Phase 1 includes:

1. `routing.skill-selection` - offline semantic skill selection and unrelated-skill invariant;
2. `ui.visible-control` - P2 layout evidence at wide and compact viewports;
3. `gameplay.stable-transition` - repeated P3 input/state-transition proof;
4. `playtest.first-time-entry` - external black-box receipt boundary for future game-test-player integration.

The first three can be replayed without model-as-judge authority. The playtest case intentionally requires an external evidence receipt.

## Boundary with live feedback

Eval replays must not be written to `.mado-loop/skill_feedback.jsonl` as though they were real user-task receipts. Live feedback and replay evals are separate signals with separate provenance.

## Next slices

1. suite-level champion/challenger aggregation across selected case sets;
2. first direct game-test-player receipt producer;
3. mutation-enabled candidate runs through an explicitly isolated OVP worktree lane;
4. optional routing qualification only after deterministic comparison and suite replay are stable.
