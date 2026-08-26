# Completion Contract

Completion is an evidence claim, not a statement of effort. Emit the common schema-v1.1 result and support every claimed proof level with checks and artifacts that actually exist.

## Status semantics

Aggregate status in this precedence: **FAIL > UNKNOWN > WARN > PASS**.

- `FAIL`: a required executed check disproves the requested outcome.
- `UNKNOWN`: an unresolved fact can invalidate the claim, a required check is `UNKNOWN` or `SKIPPED`, or a required dependency is missing.
- `WARN`: the outcome is supported but has warnings, or an optional check/capability is non-PASS, including optional `SKIPPED`.
- `PASS`: all required claims at the reported proof level are supported and no unknown remains.
- Top-level `SKIPPED`: the entire operation was legitimately not applicable or not requested. It is not a substitute for missing evidence.

FAIL remains dominant even when unknowns also exist. Keep `unknowns` for unresolved facts; do not use them for an unavailable optional capability.

## Evidence and artifacts

Each check identifies whether it is required, what was evaluated, its status, and concrete evidence. List material outputs as artifacts with existence, size, and digest where supported by `scripts/common/result.py`. Do not claim visual, runtime, gameplay, export, or release success from source inspection alone.

The completion report states:

1. requested scope and routed task domains;
2. changes and integrations made;
3. commands or observations used for verification;
4. highest achieved P0-P5 level;
5. result status, artifacts, warnings, errors, and unknowns;
6. the next bounded repair or proof action when status is not PASS.
