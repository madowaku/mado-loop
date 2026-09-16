# MADO EVALS

MADO EVALS is the replayable evaluation layer for MADO LOOP. It uses deterministic case contracts and MADO LOOP evidence rather than a model-as-judge as the authority.

The design contract is in [`docs/MADO_EVALS_SPEC.md`](../../../../docs/MADO_EVALS_SPEC.md).

## v0.1 foundation

Phase 0 provides:

- `schema/eval-case.schema.json` - case contract;
- `schema/eval-result.schema.json` - run-result contract;
- `scripts/validate_eval_case.py` - strict validation, input manifesting, and SHA-256 case digests;
- unit coverage in `tests/unit/test_validate_eval_case.py`.

A case has this shape:

```text
cases/<domain>/<case-id>/
  case.json
  task.md
  fixture/       # optional
  expected/      # optional
```

Validate a case before any runner or model call:

```powershell
python .agents/skills/mado-loop/scripts/validate_eval_case.py `
  .agents/skills/mado-loop/evals/cases/<domain>/<case-id>/case.json `
  --pretty
```

The validator emits a canonical case payload, a manifest of the task/fixture/expected files, and a `sha256:` case digest. The digest changes when any bound input changes.

## Boundary with live feedback

Eval replays must not be written to `.mado-loop/skill_feedback.jsonl` as though they were real user-task receipts. Live feedback and replay evals are separate signals with separate provenance.

## Planned next slices

1. `eval_result.py` to build canonical result records from proof and acceptance evidence.
2. `compare_eval_results.py` for lexicographic champion/challenger comparison.
3. isolated eval runner adapters.
4. a small real-world corpus derived from MADO LOOP failure modes.
5. optional routing qualification after deterministic comparison is stable.
